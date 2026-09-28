"""Runtime configuration (env-driven, 12-factor)."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RUSHLINE_DATA_DIR", BASE_DIR / "data")).resolve()
STORAGE_DIR = DATA_DIR / "storage"
DB_PATH = Path(os.environ.get("RUSHLINE_DB", DATA_DIR / "rushline.db"))
FRONTEND_DIST = Path(os.environ.get("RUSHLINE_FRONTEND", BASE_DIR.parent / "frontend" / "dist"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def _secret() -> str:
    env = os.environ.get("RUSHLINE_SECRET")
    if env:
        return env
    f = DATA_DIR / ".secret"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return f.read_text().strip()


SECRET = _secret()
JWT_TTL_SECONDS = 7 * 24 * 3600
MEDIA_TOKEN_TTL = 3600

MAX_UPLOAD_BYTES = int(os.environ.get("RUSHLINE_MAX_UPLOAD_MB", "4096")) * 1024 * 1024

# Transcription: "auto" tries faster-whisper, then OpenAI, then sidecar files.
TRANSCRIBE_PROVIDER = os.environ.get("RUSHLINE_ASR", "auto")
WHISPER_MODEL = os.environ.get("RUSHLINE_WHISPER_MODEL", "small")
# "cpu" works everywhere; set RUSHLINE_WHISPER_DEVICE=cuda only if NVIDIA CUDA 12 + cuDNN are installed
WHISPER_DEVICE = os.environ.get("RUSHLINE_WHISPER_DEVICE", "cpu")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("RUSHLINE_LLM_MODEL", "claude-sonnet-4-5")

PROXY_SHORT_SIDE = 540
PROXY_FPS = 30
EXPORT_RETENTION_DAYS = 30

PLANS = {
    # processing minutes per month; essential recovery/source access is never gated
    "free": {"minutes": 30, "max_height": 720, "watermark": True, "variations": 2},
    "creator": {"minutes": 300, "max_height": 1080, "watermark": False, "variations": 5},
    "pro": {"minutes": 1500, "max_height": 2160, "watermark": False, "variations": 20},
    "agency": {"minutes": 6000, "max_height": 2160, "watermark": False, "variations": 50},
}
DEFAULT_PLAN = os.environ.get("RUSHLINE_DEFAULT_PLAN", "creator")
# "open" = anyone can sign up; "closed" = only the first (owner) account can be created
SIGNUPS = os.environ.get("RUSHLINE_SIGNUPS", "open").strip().lower()
