"""Speech-to-text providers with word timestamps. All return: [{i, t, s, e, p}] (text, start, end, probability).

Providers:
  faster_whisper  local CTranslate2 Whisper (pip install faster-whisper)       — default when installed
  openai          OpenAI audio transcription API (OPENAI_API_KEY)             — chunked in 10-min windows
  sidecar         reads transcript.json next to the media (imports & tests)
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import wave
from pathlib import Path

from .. import config

# Whisper tends to "clean up" disfluencies; priming the prompt with them makes it transcribe fillers verbatim.
VERBATIM_PROMPT = "Umm, so, uh, I was like, you know, trying this. Uh, okay. Hmm."
CHUNK_SECONDS = 600
OVERLAP = 5


class TranscriptionUnavailable(Exception):
    pass


def _wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def _clean_words(raw: list[dict]) -> list[dict]:
    out = []
    for w in raw:
        t = (w.get("t") or "").strip()
        if not t:
            continue
        s, e = float(w["s"]), float(w["e"])
        if e <= s:
            e = s + 0.08
        if out and s < out[-1]["e"]:
            s = out[-1]["e"]
            e = max(e, s + 0.05)
        out.append({"i": len(out), "t": t, "s": round(s, 3), "e": round(e, 3), "p": round(float(w.get("p", 0.9)), 3)})
    return out


class SidecarProvider:
    name = "sidecar"

    def available(self, media_dir: Path) -> bool:
        return (media_dir / "transcript.json").exists()

    def transcribe(self, wav: Path, media_dir: Path, prompt: str = "") -> tuple[list[dict], str]:
        data = json.loads((media_dir / "transcript.json").read_text())
        words = data["words"] if isinstance(data, dict) else data
        return _clean_words([{"t": w.get("t") or w.get("word") or w.get("text"), "s": w.get("s", w.get("start")),
                              "e": w.get("e", w.get("end")), "p": w.get("p", w.get("probability", 0.95))} for w in words]), \
            (data.get("language", "en") if isinstance(data, dict) else "en")


class FasterWhisperProvider:
    name = "faster_whisper"
    _model = None

    def available(self, media_dir: Path) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def transcribe(self, wav: Path, media_dir: Path, prompt: str = "") -> tuple[list[dict], str]:
        try:
            return self._run(wav, prompt)
        except RuntimeError as e:
            # NVIDIA GPU present but CUDA libraries (cuBLAS/cuDNN) missing → fall back to CPU instead of failing
            if FasterWhisperProvider._device != "cpu" and any(k in str(e).lower() for k in ("cublas", "cudnn", "cuda")):
                FasterWhisperProvider._model = None
                FasterWhisperProvider._device = "cpu"
                return self._run(wav, prompt)
            raise

    _device = config.WHISPER_DEVICE

    def _run(self, wav: Path, prompt: str) -> tuple[list[dict], str]:
        from faster_whisper import WhisperModel
        if FasterWhisperProvider._model is None:
            dev = FasterWhisperProvider._device
            FasterWhisperProvider._model = WhisperModel(config.WHISPER_MODEL, device=dev,
                                                        compute_type="int8" if dev == "cpu" else "auto")
        segments, info = FasterWhisperProvider._model.transcribe(
            str(wav), word_timestamps=True, initial_prompt=(VERBATIM_PROMPT + " " + prompt).strip(),
            # VAD keeps timestamps anchored around long pauses (fillers are speech, so they're still transcribed)
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 150},
            condition_on_previous_text=False, beam_size=5)
        raw = []
        for seg in segments:  # generator — streams long files chunk by chunk
            for w in seg.words or []:
                raw.append({"t": w.word, "s": w.start, "e": w.end, "p": w.probability})
        return _clean_words(raw), info.language


class OpenAIProvider:
    name = "openai"

    def available(self, media_dir: Path) -> bool:
        return bool(config.OPENAI_API_KEY)

    def transcribe(self, wav: Path, media_dir: Path, prompt: str = "") -> tuple[list[dict], str]:
        import httpx
        total = _wav_duration(wav)
        raw, lang = [], "en"
        start = 0.0
        while start < total:
            length = min(CHUNK_SECONDS + OVERLAP, total - start)
            with tempfile.NamedTemporaryFile(suffix=".mp3") as tmp:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start}", "-t", f"{length}", "-i", str(wav),
                                "-ac", "1", "-b:a", "64k", tmp.name], check=True, timeout=600)
                with open(tmp.name, "rb") as f:
                    r = httpx.post("https://api.openai.com/v1/audio/transcriptions",
                                   headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                                   data={"model": "whisper-1", "response_format": "verbose_json",
                                         "timestamp_granularities[]": "word", "prompt": (VERBATIM_PROMPT + " " + prompt)[:800]},
                                   files={"file": ("audio.mp3", f, "audio/mpeg")}, timeout=600)
            r.raise_for_status()
            data = r.json()
            lang = data.get("language", lang)
            for w in data.get("words", []):
                s = w["start"] + start
                # drop words from the overlap region already covered by the previous chunk
                if raw and s < raw[-1]["e"] - 0.01:
                    continue
                if start > 0 and w["start"] < OVERLAP / 2:
                    continue
                raw.append({"t": w["word"], "s": s, "e": w["end"] + start, "p": 0.9})
            start += CHUNK_SECONDS
        return _clean_words(raw), lang


PROVIDERS = {"sidecar": SidecarProvider(), "faster_whisper": FasterWhisperProvider(), "openai": OpenAIProvider()}


def transcribe(wav: Path, media_dir: Path, prompt: str = "") -> tuple[list[dict], str, str]:
    """Returns (words, language, provider_name). Raises TranscriptionUnavailable if nothing is configured."""
    order = ["sidecar"]
    if config.TRANSCRIBE_PROVIDER in ("auto", "faster_whisper"):
        order += ["faster_whisper", "openai"]
    elif config.TRANSCRIBE_PROVIDER == "openai":
        order += ["openai", "faster_whisper"]
    for name in order:
        p = PROVIDERS[name]
        if p.available(media_dir):
            words, lang = p.transcribe(wav, media_dir, prompt)
            return words, lang, name
    raise TranscriptionUnavailable(
        "No speech-to-text engine configured. Install faster-whisper (pip install faster-whisper) or set OPENAI_API_KEY.")
