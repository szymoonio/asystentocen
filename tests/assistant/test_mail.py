"""Powiadomienia e-mail „dawno bez notatki” — bez sieci (transport outbox albo podstawiony SMTP)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.assistant.mail import MailConfig, SmtpTransport, StaleNoteEmails
from app.assistant.services import services

TODAY = date(2026, 11, 21)


@pytest.fixture
def mailer(container) -> StaleNoteEmails:
    return next(p for p in container.reminder_providers if getattr(p, "name", "") == "assistant.note_emails")


def test_email_for_stale_subordinate_with_direct_note_link(container, mailer):
    assert mailer.due(TODAY) == []  # maile, nie przypomnienia w aplikacji
    inbox = services(container).mail.inbox("E05")
    ewa = next(m for m in inbox if m.subject_id == "E07")  # ostatnia notatka 15.04.2026
    assert ewa.subject == "Ewa Rzetelna — dawno bez notatki. Masz teraz chwilę?"
    assert "http://127.0.0.1:8000/asystent/notatka/nowa?osoba=E07" in ewa.body_text
    assert 'href="http://127.0.0.1:8000/asystent/notatka/nowa?osoba=E07"' in ewa.body_html
    assert "15.04.2026" in ewa.body_text and "10.12.2026" in ewa.body_text
    assert "glosariusz" not in ewa.body_text.lower()  # treść notatek nie wychodzi mailem
    assert ewa.to_address == "henryk.pryncypal@przyklady.example" and ewa.transport == "outbox"
    assert "E06" not in {m.subject_id for m in inbox}  # notatka sprzed 2 tygodni
    assert "E09" not in {m.subject_id for m in inbox}  # kryteria jeszcze nieustalone — okres oceny się nie zaczął


def test_no_duplicates_and_repeat_after_three_weeks(container, mailer):
    store = services(container).mail

    def ewa():
        return [m for m in store.inbox("E05") if m.subject_id == "E07"]

    mailer.due(TODAY)
    mailer.due(TODAY)
    mailer.due(TODAY + timedelta(days=7))
    assert len(ewa()) == 1  # bez duplikatów w ciągu 3 tygodni
    container.clock = type(container.clock)(TODAY + timedelta(days=21))
    mailer._now = container.clock.now
    mailer.due(TODAY + timedelta(days=21))
    assert len(ewa()) == 2  # nadal brak notatki → ponowne przypomnienie


def test_daily_limit_and_oldest_first(container, mailer):
    mailer.cfg = MailConfig(max_per_day=1)
    mailer.due(TODAY)
    inbox = services(container).mail.inbox("E05")
    assert len(inbox) == 1 and inbox[0].subject_id == "E07"  # najdawniej bez notatki


def test_snoozed_person_gets_no_email(container, mailer):
    services(container).snoozes.snooze("E05", "E07", TODAY + timedelta(days=14))
    mailer.due(TODAY)
    assert "E07" not in {m.subject_id for m in services(container).mail.inbox("E05")}


def test_smtp_failure_is_recorded_and_retried_next_day(container, mailer):
    class Broken:
        name = "smtp"

        def send(self, mail, sender):
            raise ConnectionRefusedError("serwer pocztowy niedostępny")

    mailer.transport = Broken()
    mailer.due(TODAY)
    failed = services(container).mail.inbox("E05")
    assert failed and all("niedostępny" in m.error for m in failed)
    mailer.transport = type("Ok", (), {"name": "smtp", "send": lambda self, m, s: None})()
    mailer.due(TODAY + timedelta(days=1))
    assert any(not m.error for m in services(container).mail.inbox("E05"))


def test_smtp_transport_builds_message(monkeypatch, container, mailer):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            sent.append(("starttls",))

        def login(self, user, password):
            sent.append(("login", user))

        def send_message(self, msg):
            sent.append(("msg", msg["To"], msg["Subject"], msg.get_body(("plain",)).get_content()))

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    monkeypatch.setenv("SMTP_HOST", "poczta.urzad.example")
    monkeypatch.setenv("SMTP_USER", "asystent")
    mailer.transport = SmtpTransport(MailConfig().smtp)
    mailer.due(TODAY)
    assert ("connect", "poczta.urzad.example", 587) in sent and ("login", "asystent") in sent
    to, subject, body = next(x[1:] for x in sent if x[0] == "msg" and "henryk" in x[1])
    assert "dawno bez notatki" in subject and "/asystent/notatka/nowa?osoba=" in body


def test_env_overrides_config(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://oceny.urzad.example")
    monkeypatch.setenv("MAIL_TRANSPORT", "smtp")
    monkeypatch.setenv("MAIL_REDIRECT_TO", "ja@poczta.example")
    monkeypatch.setenv("MAIL_ONLY_FOR", "E05, E04")
    cfg = MailConfig.from_dict({"transport": "outbox", "only_for": []})
    assert (cfg.base_url, cfg.transport, cfg.redirect_to, cfg.only_for) == (
        "https://oceny.urzad.example", "smtp", "ja@poczta.example", ("E05", "E04"))


def test_disabled_sends_nothing(container, mailer):
    mailer.cfg = MailConfig(enabled=False)
    mailer.due(TODAY)
    assert services(container).mail.inbox("E05") == []


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_redirect_to_own_mailbox_for_demo(monkeypatch, container, mailer):
    FakeSMTP.sent = []
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USER", "ja@gmail.example.com")
    cfg = MailConfig(transport="smtp", redirect_to="ja@gmail.example.com", only_for=("E05",))
    mailer.cfg, mailer.transport = cfg, SmtpTransport(cfg.smtp, cfg)
    mailer.due(TODAY)
    assert FakeSMTP.sent and all(m["To"] == "ja@gmail.example.com" for m in FakeSMTP.sent)
    assert all(m["Subject"].startswith("[demo → Henryk Pryncypał] ") for m in FakeSMTP.sent)  # tylko przełożony E05
    assert "AsystentPLUS" in FakeSMTP.sent[0]["From"] and "ja@gmail.example.com" in FakeSMTP.sent[0]["From"]
    log = services(container).mail.inbox_all()
    assert {r.recipient_id for r in log} == {"E05"} and {r.to_address for r in log} == {"ja@gmail.example.com"}


def test_no_inbox_in_app(client):
    assert client.get("/asystent/poczta").status_code == 404
    assert "/asystent/poczta" not in client.get("/asystent/teczka").text


def test_cli_sends_one_test_reminder(monkeypatch, tmp_path, capsys):
    from app.assistant.mail.__main__ import main

    FakeSMTP.sent = []
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    for key, value in {"DATABASE_URL": f"sqlite:///{tmp_path / 'cli.db'}", "DEMO_TODAY": "2026-11-21",
                       "MAIL_TRANSPORT": "smtp", "SMTP_HOST": "smtp.example", "MAIL_REDIRECT_TO": "ja@poczta.example"}.items():
        monkeypatch.setenv(key, value)
    assert main(["--osoba", "E06", "--env-file", str(tmp_path / "brak.env")]) == 0
    assert "Wysłano → ja@poczta.example" in capsys.readouterr().out
    msg = FakeSMTP.sent[-1]
    assert "Grzegorz Wzór" in msg["Subject"] and "/asystent/notatka/nowa?osoba=E06" in msg.get_body(("plain",)).get_content()
