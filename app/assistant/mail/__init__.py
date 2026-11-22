"""Powiadomienia e-mail dla przełożonych: „dawno bez notatki” z linkiem prosto do nowej notatki.

Maile nie są wyświetlane w aplikacji — to wyłącznie przypominajka w skrzynce pocztowej.
Transport `outbox` (domyślny) niczego nie wysyła, tylko zapisuje dziennik (deduplikacja);
`smtp` wysyła przez serwer pocztowy (dane z .env). Do demo: MAIL_REDIRECT_TO kieruje wszystkie
maile na jeden adres, MAIL_ONLY_FOR ogranicza wysyłkę do wybranych przełożonych.
W treści maila nie ma treści notatek: imię i nazwisko, data ostatniej notatki, termin oceny, link.
"""

from __future__ import annotations

import logging
import os
import smtplib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from typing import Protocol

from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.assistant.display import ago
from app.assistant.notes.repository import NotesRepository
from app.assistant.nudges.snooze import SnoozeRepository
from app.contracts.models import Employee, EvaluationSummary, Reminder
from app.contracts.ports import EmployeeDirectory, EvaluationReader
from app.db import Base

log = logging.getLogger("asystent.mail")


# --- konfiguracja -----------------------------------------------------------------------------


@dataclass(frozen=True)
class SmtpConfig:
    host_env: str = "SMTP_HOST"
    port_env: str = "SMTP_PORT"
    user_env: str = "SMTP_USER"
    password_env: str = "SMTP_PASSWORD"
    starttls: bool = True


@dataclass(frozen=True)
class MailConfig:
    enabled: bool = True
    transport: str = "outbox"  # outbox | smtp
    base_url: str = "http://127.0.0.1:8000"
    sender: str = "AsystentPLUS <asystentplus@przyklady.example>"
    repeat_after_days: int = 21
    max_per_day: int = 3
    redirect_to: str = ""  # demo: wszystkie maile na ten adres zamiast do przełożonych
    only_for: tuple[str, ...] = ()  # demo: tylko ci przełożeni (id pracownika), pusto = wszyscy
    smtp: SmtpConfig = field(default_factory=SmtpConfig)

    # Zmienne środowiskowe (.env) nadpisują config/nudges.yaml — dzięki temu własną skrzynkę
    # podłącza się bez zmian w repozytorium.
    ENV = {"MAIL_TRANSPORT": "transport", "APP_BASE_URL": "base_url", "MAIL_FROM": "sender",
           "MAIL_REDIRECT_TO": "redirect_to", "MAIL_ONLY_FOR": "only_for"}

    @classmethod
    def from_dict(cls, data: dict | None) -> MailConfig:
        data = dict(data or {})
        smtp = SmtpConfig(**(data.pop("smtp", None) or {}))
        values = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        for env, name in cls.ENV.items():
            if os.environ.get(env):
                values[name] = os.environ[env].strip()
        only = values.get("only_for") or ()
        values["only_for"] = tuple(x.strip() for x in (only.split(",") if isinstance(only, str) else only) if x.strip())
        return cls(**values, smtp=smtp)


# --- dziennik wysyłki (deduplikacja; nie jest wyświetlany w aplikacji) ---------------------------


class EmailRow(Base):
    __tablename__ = "asst_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    recipient_id: Mapped[str] = mapped_column(String(20), index=True)
    to_address: Mapped[str] = mapped_column(String(200))
    subject_id: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(300))
    body_text: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str] = mapped_column(Text)
    transport: Mapped[str] = mapped_column(String(20))
    sent_at: Mapped[datetime] = mapped_column(DateTime)
    error: Mapped[str] = mapped_column(String(300), default="")


@dataclass(frozen=True)
class Mail:
    dedupe_key: str
    recipient: Employee
    subject_id: str
    subject: str
    text: str
    html: str


class MailStore:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    def sent_keys(self, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        with self._sf() as s:
            return set(s.scalars(select(EmailRow.dedupe_key).where(EmailRow.dedupe_key.in_(keys))))

    def last_for(self, recipient_id: str, subject_id: str) -> EmailRow | None:
        # nieudana wysyłka (błąd SMTP) nie blokuje ponownej próby następnego dnia
        stmt = (select(EmailRow).where(EmailRow.recipient_id == recipient_id, EmailRow.subject_id == subject_id,
                                       EmailRow.error == "")
                .order_by(EmailRow.sent_at.desc()).limit(1))  # fmt: skip
        with self._sf() as s:
            row = s.scalars(stmt).first()
            if row:
                s.expunge(row)
            return row

    def sent_today(self, recipient_id: str, day: date) -> int:
        start = datetime.combine(day, datetime.min.time())
        stmt = select(EmailRow.id).where(EmailRow.recipient_id == recipient_id, EmailRow.sent_at >= start)
        with self._sf() as s:
            return len(list(s.scalars(stmt)))

    def save(self, mail: Mail, *, transport: str, now: datetime, error: str = "", to: str | None = None) -> None:
        with self._sf.begin() as s:
            s.add(EmailRow(
                dedupe_key=mail.dedupe_key, recipient_id=mail.recipient.id, to_address=to or mail.recipient.email or "",
                subject_id=mail.subject_id, subject=mail.subject, body_text=mail.text, body_html=mail.html,
                transport=transport, sent_at=now, error=error[:300],
            ))  # fmt: skip

    def inbox(self, recipient_id: str) -> list[EmailRow]:
        stmt = select(EmailRow).where(EmailRow.recipient_id == recipient_id).order_by(EmailRow.sent_at.desc(), EmailRow.id.desc())
        with self._sf() as s:
            rows = list(s.scalars(stmt))
            for r in rows:
                s.expunge(r)
            return rows

    def inbox_all(self) -> list[EmailRow]:
        with self._sf() as s:
            rows = list(s.scalars(select(EmailRow).order_by(EmailRow.id)))
            for r in rows:
                s.expunge(r)
            return rows

    def get(self, recipient_id: str, email_id: int) -> EmailRow | None:
        with self._sf() as s:
            row = s.get(EmailRow, email_id)
            if row is None or row.recipient_id != recipient_id:
                return None
            s.expunge(row)
            return row


# --- transport -----------------------------------------------------------------------------------


class Transport(Protocol):
    name: str

    def send(self, mail: Mail, sender: str) -> None: ...


class OutboxTransport:
    """Nic nie wysyła — zostaje tylko wpis w dzienniku (MailStore). Domyślne, gdy nie podłączono poczty."""

    name = "outbox"

    def send(self, mail: Mail, sender: str) -> None:
        return None


def delivery_address(mail: Mail, cfg: MailConfig) -> str:
    return cfg.redirect_to or mail.recipient.email or ""


class SmtpTransport:
    name = "smtp"

    def __init__(self, cfg: SmtpConfig, mail_cfg: MailConfig | None = None) -> None:
        self.cfg = cfg
        self.mail_cfg = mail_cfg or MailConfig(smtp=cfg)

    def sender(self, configured: str) -> str:
        """Domeny .example nie istnieją — wtedy nadawcą jest konto SMTP (np. własny Gmail)."""
        user = os.environ.get(self.cfg.user_env, "")
        if configured.rstrip(">").endswith(".example") and "@" in user:
            return formataddr(("AsystentPLUS", user))
        return configured

    def send(self, mail: Mail, sender: str) -> None:
        to = delivery_address(mail, self.mail_cfg)
        if not to:
            raise ValueError("brak adresu e-mail przełożonego")
        host = os.environ.get(self.cfg.host_env)
        if not host:
            raise ValueError(f"brak {self.cfg.host_env}")
        msg = EmailMessage()
        msg["From"] = self.sender(sender)
        redirected = bool(self.mail_cfg.redirect_to)
        msg["To"] = to if redirected else formataddr((mail.recipient.full_name, to))
        msg["Subject"] = f"[demo → {mail.recipient.full_name}] {mail.subject}" if redirected else mail.subject
        msg.set_content(mail.text)
        msg.add_alternative(mail.html, subtype="html")
        with smtplib.SMTP(host, int(os.environ.get(self.cfg.port_env, "587")), timeout=20) as smtp:
            if self.cfg.starttls:
                smtp.starttls()
            user = os.environ.get(self.cfg.user_env)
            if user:
                smtp.login(user, os.environ.get(self.cfg.password_env, ""))
            smtp.send_message(msg)


def build_transport(cfg: MailConfig) -> Transport:
    return SmtpTransport(cfg.smtp, cfg) if cfg.transport == "smtp" else OutboxTransport()


# --- treść ---------------------------------------------------------------------------------------


def compose(*, supervisor: Employee, subject: Employee, evaluation: EvaluationSummary, last: date | None,
            today: date, base_url: str, dedupe_key: str) -> Mail:
    link = f"{base_url.rstrip('/')}/asystent/notatka/nowa?osoba={subject.id}"
    when = f"{last:%d.%m.%Y} ({ago(last, today)})" if last else "jeszcze żadnej"
    due = f"{evaluation.due_date:%d.%m.%Y}" if evaluation.due_date else None
    title = f"{subject.full_name} — dawno bez notatki. Masz teraz chwilę?"
    lines = [
        "Dzień dobry,",
        "",
        f"od dłuższego czasu nie było notatki o pracy: {subject.full_name} ({subject.position.title}).",
        f"Ostatnia notatka: {when}.",
    ]
    if due:
        lines.append(f"Termin oceny okresowej: {due}.")
    lines += [
        "",
        "Jeśli masz teraz chwilę — krótka notatka zajmuje minutę:",
        link,
        "",
        "Wiadomość z AsystentaPLUS. W mailu nie ma treści Twoich notatek — są tylko w aplikacji.",
    ]
    html = f"""<div style="font-family: Arial, sans-serif; font-size: 16px; line-height: 1.45; color: #1B1B1B; max-width: 560px">
  <p>Dzień dobry,</p>
  <p>od dłuższego czasu nie było notatki o pracy: <strong>{escape(subject.full_name)}</strong> ({escape(subject.position.title)}).</p>
  <p>Ostatnia notatka: <strong>{escape(when)}</strong>.{f"<br>Termin oceny okresowej: <strong>{due}</strong>." if due else ""}</p>
  <p>Jeśli masz teraz chwilę — krótka notatka zajmuje minutę:</p>
  <p><a href="{escape(link)}" style="display: inline-block; padding: 10px 18px; background: #0052A5; color: #ffffff; font-weight: bold; text-decoration: none; border: 2px solid #0052A5">Dodaj notatkę: {escape(subject.full_name)}</a></p>
  <p style="font-size: 13px; color: #555555">Wiadomość z AsystentaPLUS. W mailu nie ma treści Twoich notatek — są tylko w aplikacji.</p>
</div>"""
    return Mail(dedupe_key, supervisor, subject.id, title, "\n".join(lines), html)


# --- codzienne przypomnienia ---------------------------------------------------------------------


class StaleNoteEmails:
    """`ReminderProvider`: wysyła maile i nie zwraca przypomnień w aplikacji (te są w „Do zrobienia”).

    Kto: przełożony, którego podwładny ma trwający okres oceny i brak notatki dłużej niż
    `no_note_after_days` (jak w przypomnieniach w aplikacji). Bez osób „odłożonych” w teczce.
    Ile: jeden mail na osobę; ponownie po `repeat_after_days`, jeśli nadal brak notatki;
    najwyżej `max_per_day` dziennie na przełożonego, najdawniej bez notatki najpierw.
    """

    name = "assistant.note_emails"

    def __init__(self, *, employees: Callable[[], EmployeeDirectory], evaluations: Callable[[], EvaluationReader],
                 notes: NotesRepository, snoozes: SnoozeRepository, store: MailStore, transport: Transport,
                 cfg: MailConfig, threshold_days: Callable[[], int], now: Callable[[], datetime]) -> None:
        self._employees, self._evaluations = employees, evaluations
        self._notes, self._snoozes, self._store = notes, snoozes, store
        self.transport, self.cfg = transport, cfg
        self._threshold, self._now = threshold_days, now

    def candidates(self, supervisor: Employee, today: date) -> list[tuple[Employee, EvaluationSummary, date | None]]:
        employees = self._employees()
        snoozed = self._snoozes.active(supervisor.id, today)
        out = []
        for ev in self._evaluations().for_evaluator(supervisor.id):
            if ev.employee_id in snoozed:
                continue
            notes = self._notes.current(supervisor.id, ev.employee_id)
            last = max((n.observed_on for n in notes), default=None)
            start = last or ev.period_from or ev.criteria_set_on
            if start is None or (today - start).days <= self._threshold():
                continue
            try:
                out.append((employees.get(ev.employee_id), ev, last))
            except KeyError:
                continue
        return sorted(out, key=lambda t: (t[2] is not None, t[2] or date.min))

    def due(self, today: date) -> list[Reminder]:
        if not self.cfg.enabled:
            return []
        for supervisor in self._employees().all():
            if self.cfg.only_for and supervisor.id not in self.cfg.only_for:
                continue
            budget = self.cfg.max_per_day - self._store.sent_today(supervisor.id, today)
            for subject, ev, last in self.candidates(supervisor, today):
                if budget <= 0:
                    break
                previous = self._store.last_for(supervisor.id, subject.id)
                if previous and (today - previous.sent_at.date()).days < self.cfg.repeat_after_days:
                    continue
                key = f"mail:no-note:{supervisor.id}:{subject.id}:{today.isoformat()}"
                mail = compose(supervisor=supervisor, subject=subject, evaluation=ev, last=last, today=today,
                               base_url=self.cfg.base_url, dedupe_key=key)
                error = ""
                try:
                    self.transport.send(mail, self.cfg.sender)
                except Exception as exc:  # serwer pocztowy nie może zatrzymać przypomnień o terminach
                    log.warning("mail do %s nie wysłany: %s", supervisor.id, exc)
                    error = str(exc) or type(exc).__name__
                self._store.save(mail, transport=self.transport.name, now=self._now(), error=error,
                                 to=delivery_address(mail, self.cfg))
                budget -= 1
        return []
