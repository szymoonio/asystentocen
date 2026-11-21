"""Notatki głosowe: transkrypcja lokalna, audio kasowane po transkrypcji (fake transcriber, bez modelu)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from app.assistant.services import services
from app.assistant.stt import (
    FasterWhisperTranscriber,
    NullTranscriber,
    SttConfig,
    Transcriber,
    TranscriptionError,
    build_transcriber,
)
from app.contracts.enums import NoteSource
from app.settings import ROOT


class FakeTranscriber:
    def __init__(self, text: str = "Oddał tłumaczenie przed terminem.", error: str | None = None) -> None:
        self.text = text
        self.error = error
        self.paths: list[Path] = []
        self.existed: list[bool] = []

    def available(self) -> bool:
        return True

    def transcribe(self, audio_path: Path) -> str:
        self.paths.append(audio_path)
        self.existed.append(audio_path.exists())
        if self.error:
            raise TranscriptionError(self.error)
        return self.text


AUDIO = {"audio": ("nagranie.webm", b"\x1a\x45\xdf\xa3fake-webm-bytes", "audio/webm")}


@pytest.fixture
def fake_stt(container):
    fake = FakeTranscriber()
    services(container).stt = fake
    return fake


def test_config_and_default_without_package():
    cfg = SttConfig.load(ROOT / "config")
    assert (cfg.engine, cfg.language, cfg.max_seconds) == ("faster-whisper", "pl", 300)
    assert isinstance(build_transcriber(cfg), NullTranscriber)  # faster-whisper nie jest zainstalowany w CI
    assert isinstance(build_transcriber(SttConfig(engine="none")), NullTranscriber)


def test_faster_whisper_wrapper_with_stub_module(monkeypatch, tmp_path):
    calls = {}

    class WhisperModel:
        def __init__(self, size, device, compute_type):
            calls["init"] = (size, device, compute_type)

        def transcribe(self, path, language, beam_size, vad_filter):
            calls["transcribe"] = (path, language, vad_filter)
            segs = [types.SimpleNamespace(text=" Dzień dobry, "), types.SimpleNamespace(text="notatka o pracy. ")]
            return iter(segs), types.SimpleNamespace(duration=12.0)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=WhisperModel))
    t = FasterWhisperTranscriber(SttConfig(model="tiny"))
    assert isinstance(t, Transcriber)
    audio = tmp_path / "a.webm"
    audio.write_bytes(b"x")
    assert t.transcribe(audio) == "Dzień dobry, notatka o pracy."
    assert calls["init"] == ("tiny", "cpu", "int8") and calls["transcribe"][1:] == ("pl", True)


def test_faster_whisper_rejects_long_and_empty(monkeypatch, tmp_path):
    class WhisperModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, path, **kw):
            return iter([]), types.SimpleNamespace(duration=self.duration)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=WhisperModel))
    t = FasterWhisperTranscriber(SttConfig(max_seconds=60))
    WhisperModel.duration = 61.0
    with pytest.raises(TranscriptionError, match="za długie"):
        t.transcribe(tmp_path / "a.webm")
    WhisperModel.duration = 5.0
    with pytest.raises(TranscriptionError, match="nie rozpoznano"):
        t.transcribe(tmp_path / "a.webm")


def test_record_button_hidden_without_engine(client):
    page = client.get("/asystent/teczka/E06/nowa").text
    assert "Nagraj notatkę głosową" not in page and "Wgraj je" not in page
    assert client.post("/asystent/teczka/E06/glos", files=AUDIO, headers={"Accept": "application/json"}).status_code == 422


def test_record_button_shown_with_engine(client, fake_stt):
    page = client.get("/asystent/teczka/E06/nowa").text
    assert "Nagraj notatkę głosową" in page and "Masz nagranie z telefonu" in page
    assert "Nagraj notatkę głosową" not in client.get("/asystent/teczka/E06/notatka/N001/edytuj").text


def test_json_upload_transcribes_and_deletes_audio(client, fake_stt):
    response = client.post("/asystent/teczka/E06/glos", files=AUDIO, headers={"Accept": "application/json"})
    assert response.status_code == 200 and response.json() == {"text": "Oddał tłumaczenie przed terminem."}
    assert fake_stt.existed == [True]  # plik był na dysku w trakcie transkrypcji…
    assert not fake_stt.paths[0].exists()  # …i zniknął zaraz po niej
    assert fake_stt.paths[0].suffix == ".webm"


def test_audio_deleted_on_transcription_error(client, container):
    fake = FakeTranscriber(error="W nagraniu nie rozpoznano mowy.")
    services(container).stt = fake
    response = client.post("/asystent/teczka/E06/glos", files=AUDIO, headers={"Accept": "application/json"})
    assert response.status_code == 422 and response.json()["error"] == "W nagraniu nie rozpoznano mowy."
    assert not fake.paths[0].exists()


def test_upload_limits(client, container, fake_stt):
    services(container).stt_config = SttConfig(max_upload_mb=0)
    response = client.post("/asystent/teczka/E06/glos", files=AUDIO, headers={"Accept": "application/json"})
    assert response.status_code == 422 and "za duży" in response.json()["error"]
    services(container).stt_config = SttConfig()
    empty = {"audio": ("n.webm", b"", "audio/webm")}
    assert "puste" in client.post("/asystent/teczka/E06/glos", files=empty, headers={"Accept": "application/json"}).json()["error"]
    assert fake_stt.paths == []


def test_phone_upload_without_js_prefills_form_and_saves_voice_note(client, container, fake_stt):
    page = client.post("/asystent/teczka/E06/glos", files=AUDIO).text
    assert "Oddał tłumaczenie przed terminem.</textarea>" in page
    assert 'name="source" id="source" value="VOICE"' in page and "Nagranie zostało usunięte" in page
    client.post("/asystent/teczka/E06/nowa", data={"observed_on": "2026-11-21", "body": "Oddał tłumaczenie przed terminem.", "source": "VOICE"})
    assert container.notes.notes_for("E05", "E06")[-1].source == NoteSource.VOICE


def test_only_own_subordinates(client, fake_stt):
    client.get("/login/E04")
    assert client.post("/asystent/teczka/E06/glos", files=AUDIO, headers={"Accept": "application/json"}).status_code == 403
    assert fake_stt.paths == []
