"""Moduł ASSISTANT — agent B. Teczka (notatki), przypomnienia o notatkach, LLM, HR partner.

Kontrakt z resztą aplikacji (nie zmieniać nazw):
    router                      — APIRouter montowany pod /asystent
    register(c: Container)      — podmienia porty B na prawdziwe implementacje,
                                  rejestruje ReminderProvider-y i importuje modele bazy.

Zakres i definicja ukończenia: docs/AGENT_B.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.assistant.api import router

if TYPE_CHECKING:
    from app.container import Container

__all__ = ["register", "router"]


def register(c: Container) -> None:
    from app.assistant.analysis.store import AnalysisRow, AnalysisStore
    from app.assistant.config import NudgesConfig
    from app.assistant.hr.boundaries import HrConfig
    from app.assistant.hr.knowledge import default_knowledge
    from app.assistant.hr.roleplay import RoleplayRow, RoleplayStore
    from app.assistant.llm import LLMConfig, build_client
    from app.assistant.mail import EmailRow, MailConfig, MailStore, StaleNoteEmails, build_transport
    from app.assistant.notes import models
    from app.assistant.notes.reader import DbNotesReader
    from app.assistant.notes.repository import NotesRepository, import_seed_if_empty
    from app.assistant.nudges.provider import NoteNudges
    from app.assistant.nudges.snooze import SnoozeRepository, SnoozeRow
    from app.assistant.privacy import Pseudonymizer
    from app.assistant.services import AssistantServices, attach, services
    from app.assistant.stt import SttConfig, build_transcriber
    from app.assistant.summarize.evidence import EvidenceBuilder, load_development_actions
    from app.assistant.summarize.provider import AssistantDraftProvider
    from app.assistant.summarize.store import DraftRow, DraftStore

    # Tabele asst_* zakładamy od razu (create_all w kontenerze jest dopiero po register),
    # bo przy pustej bazie importujemy notatki z seedu.
    tables = [models.NoteRow.__table__, models.CriteriaHintRow.__table__, SnoozeRow.__table__, DraftRow.__table__,
              RoleplayRow.__table__, AnalysisRow.__table__,
              EmailRow.__table__]
    models.Base.metadata.create_all(c.engine, tables=tables)
    repo = NotesRepository(c.session_factory)
    import_seed_if_empty(repo, c.seed.notes)

    config = NudgesConfig.load(c.settings.config_dir)
    snoozes = SnoozeRepository(c.session_factory)
    nudges = NoteNudges(
        employees=lambda: c.employees,
        evaluations=lambda: c.evaluations,
        catalog=c.catalog,
        notes=repo,
        snoozes=snoozes,
        config=config,
    )
    llm_config = LLMConfig.load(c.settings.config_dir)
    stt_config = SttConfig.load(c.settings.config_dir)
    drafts = AssistantDraftProvider(
        builder=lambda: EvidenceBuilder(repo=repo, evaluations=c.evaluations, employees=c.employees, catalog=c.catalog),
        store=DraftStore(c.session_factory),
        actions=load_development_actions(),
        now=c.clock.now,
    )
    attach(
        c,
        AssistantServices(
            notes_repo=repo,
            nudges=config,
            snoozes=snoozes,
            note_nudges=nudges,
            llm_config=llm_config,
            llm=build_client(llm_config),
            pseudonymizer=lambda: Pseudonymizer(c.employees.all()),
            drafts=drafts,
            hr=HrConfig.load(),
            roleplays=RoleplayStore(c.session_factory),
            knowledge=default_knowledge,
            stt_config=stt_config,
            stt=build_transcriber(stt_config),
            analyses=AnalysisStore(c.session_factory),
        ),
    )
    c.notes = DbNotesReader(repo, lambda: c.evaluations, c.catalog)
    c.reminder_providers.append(nudges)
    mail_config = MailConfig.from_dict(config.extra.get("email"))
    services(c).mail = MailStore(c.session_factory)
    c.reminder_providers.append(
        StaleNoteEmails(
            employees=lambda: c.employees, evaluations=lambda: c.evaluations, notes=repo, snoozes=snoozes,
            store=services(c).mail, transport=build_transport(mail_config), cfg=mail_config,
            threshold_days=lambda: config.no_note_after_days, now=c.clock.now,
        )
    )
    c.drafts = drafts
