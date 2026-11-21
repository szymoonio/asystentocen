"""Notatki głosowe: transkrypcja lokalna (ARCHITEKTURA § 4 B2, § 6.3 „Głos”).

- Silnik za interfejsem `Transcriber` (wymienny): `FasterWhisperTranscriber` albo `NullTranscriber`.
- Audio nigdy nie opuszcza serwera i jest kasowane zaraz po transkrypcji.
- Wyłącznie transkrypcja: żadnej analizy tonu ani emocji (AI Act art. 5 ust. 1 lit. f).
- Gdy `faster-whisper` nie jest zainstalowany, przycisk nagrywania jest ukryty.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

log = logging.getLogger("asystent.stt")


class TranscriptionError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@runtime_checkable
class Transcriber(Protocol):
    def available(self) -> bool: ...

    def transcribe(self, audio_path: Path) -> str: ...


class NullTranscriber:
    def available(self) -> bool:
        return False

    def transcribe(self, audio_path: Path) -> str:
        raise TranscriptionError("Transkrypcja jest wyłączona.")


@dataclass(frozen=True)
class SttConfig:
    engine: str = "faster-whisper"  # faster-whisper | none
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "pl"
    max_seconds: int = 300
    max_upload_mb: int = 25

    @classmethod
    def load(cls, config_dir: Path) -> SttConfig:
        path = config_dir / "llm.yaml"
        if not path.exists():
            return cls()
        data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("stt") or {}
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class FasterWhisperTranscriber:
    """faster-whisper (CTranslate2) na CPU. Model ładowany leniwie przy pierwszym nagraniu."""

    def __init__(self, config: SttConfig) -> None:
        self.config = config
        self._model: Any = None

    def available(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def _load(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel

            log.info("ładuję model faster-whisper %s (%s/%s)", self.config.model, self.config.device, self.config.compute_type)
            self._model = WhisperModel(self.config.model, device=self.config.device, compute_type=self.config.compute_type)
        return self._model

    def transcribe(self, audio_path: Path) -> str:
        try:
            segments, info = self._load().transcribe(
                str(audio_path), language=self.config.language, beam_size=5, vad_filter=True
            )
            if getattr(info, "duration", 0) and info.duration > self.config.max_seconds:
                raise TranscriptionError(
                    f"Nagranie jest za długie ({int(info.duration)} s). Limit: {self.config.max_seconds} s."
                )
            text = " ".join(s.text.strip() for s in segments).strip()
        except TranscriptionError:
            raise
        except Exception as exc:  # błędy dekodowania audio, modelu itp.
            log.warning("transkrypcja nieudana: %s", exc)
            raise TranscriptionError("Nie udało się odczytać nagrania. Spróbuj nagrać jeszcze raz.") from exc
        if not text:
            raise TranscriptionError("W nagraniu nie rozpoznano mowy.")
        return text


def build_transcriber(config: SttConfig) -> Transcriber:
    if config.engine == "faster-whisper":
        transcriber = FasterWhisperTranscriber(config)
        if transcriber.available():
            return transcriber
        log.info("Notatki głosowe wyłączone: brak pakietu faster-whisper")
    return NullTranscriber()
