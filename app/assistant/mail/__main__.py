"""Wysyłka przypomnień e-mail z wiersza poleceń.

    python -m app.assistant.mail                # dzisiejsze przypomnienia (jak codzienny scheduler)
    python -m app.assistant.mail --osoba E07    # od razu jeden mail o tej osobie — test podłączenia poczty

Konfiguracja poczty z pliku .env (MAIL_TRANSPORT, SMTP_*, MAIL_REDIRECT_TO, MAIL_ONLY_FOR, APP_BASE_URL).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _load_env(path: str) -> None:
    if not Path(path).exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # bez python-dotenv: proste KLUCZ=wartość
        import os

        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return
    load_dotenv(path, override=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.assistant.mail", description=__doc__.split("\n")[0])
    parser.add_argument("--osoba", help="id pracownika (np. E07): wyślij teraz jedno przypomnienie o nim")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    _load_env(args.env_file)

    from app.assistant.mail import StaleNoteEmails, compose, delivery_address
    from app.assistant.services import services
    from app.container import build_container

    c = build_container()
    mailer = next(p for p in c.reminder_providers if isinstance(p, StaleNoteEmails))
    store = services(c).mail
    today = c.clock.today()
    print(f"Poczta: {mailer.transport.name}" + (f" · wszystko na {mailer.cfg.redirect_to}" if mailer.cfg.redirect_to else ""))
    if mailer.transport.name == "outbox":
        print("Uwaga: MAIL_TRANSPORT nie jest ustawione na smtp — nic nie zostanie naprawdę wysłane.")

    if args.osoba:
        try:
            subject = c.employees.get(args.osoba)
        except KeyError:
            print(f"Nie ma pracownika {args.osoba}.")
            return 2
        ev = c.evaluations.current_for(subject.id)
        if ev is None or not ev.evaluator_id:
            print(f"{subject.full_name} nie ma trwającej oceny z oceniającym w urzędzie.")
            return 2
        supervisor = c.employees.get(ev.evaluator_id)
        notes = services(c).notes_repo.current(supervisor.id, subject.id)
        last = max((n.observed_on for n in notes), default=None)
        mail = compose(supervisor=supervisor, subject=subject, evaluation=ev, last=last, today=today,
                       base_url=mailer.cfg.base_url, dedupe_key=f"mail:test:{supervisor.id}:{subject.id}:{c.clock.now().isoformat()}")
        error = ""
        try:
            mailer.transport.send(mail, mailer.cfg.sender)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        store.save(mail, transport=mailer.transport.name, now=c.clock.now(), error=error,
                   to=delivery_address(mail, mailer.cfg))
        target = delivery_address(mail, mailer.cfg)
        print(f"{'BŁĄD: ' + error if error else 'Wysłano'} → {target}: {mail.subject}")
        return 1 if error else 0

    before = {r.id for r in store.inbox_all()}
    mailer.due(today)
    new = [r for r in store.inbox_all() if r.id not in before]
    for r in new:
        print(f"{'BŁĄD: ' + r.error if r.error else 'Wysłano'} → {r.to_address}: {r.subject}")
    if not new:
        print("Dziś nie ma nowych przypomnień (albo już zostały wysłane).")
    return 1 if any(r.error for r in new) else 0


if __name__ == "__main__":
    sys.exit(main())
