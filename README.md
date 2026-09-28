---
title: Rushline
emoji: 🎬
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Rushline

**Raw takes in, ready ads out.** Rushline is an AI video editor for TikTok Shop, affiliate, UGC and talking-head creators.
You upload messy footage. The AI works out what you said and what you're selling, cleans the footage, and builds several
high-retention ad versions. You review them and export.

The brand, UI, visual identity and code are all original. See `docs/ARCHITECTURE.md` for the full plan: architecture,
user flow, screen map, schema, AI, video and rendering pipelines, security, infrastructure, risks, and phases.

## Run it

**Quick local run (macOS/Linux; needs Python 3.11+, Node 18+, ffmpeg):**
```bash
./run.sh            # builds the web app, installs deps, serves http://localhost:8000
```
**On your iPhone:** connect to the same Wi-Fi and open `http://<your-computer-ip>:8000` in Safari.
To use it as a full-screen app, tap Share, then **Add to Home Screen**. For the complete installed-app experience
(offline shell, standalone mode), serve it over HTTPS. The Docker setup below does this automatically.

**Production-style (HTTPS, separate workers):**
```bash
cd deploy
RUSHLINE_SECRET=$(openssl rand -hex 32) RUSHLINE_DOMAIN=edit.yourdomain.com docker compose up -d --build
```

### Speech-to-text
Transcription is pluggable (`backend/app/ai/transcribe.py`):
- `pip install faster-whisper` gives you local Whisper with word timestamps. This is the default, and the model downloads on first use.
- Setting `OPENAI_API_KEY` uses the hosted Whisper API instead. Long files are chunked automatically.
- With neither set, the app still works as a visual editor, and a notice explains why there's no transcript.

`ANTHROPIC_API_KEY` is optional. When set, it improves sales-section labeling and understands free-form assistant
requests. The LLM only proposes actions from the same validated action list. It never edits the timeline or writes speech.

## What works (MVP)
Auth · project dashboard · multi-clip upload from iPhone Photos or Files · proxy generation (HEVC/HDR/rotation normalized) ·
transcription · transcript-based editing · dead-space, retake, false-start, stutter, spoken-mistake and filler removal
(cuts snap to word edges) · editable timeline (split, delete, duplicate, move/drag, trim, speed, volume, zoom, rotate) ·
auto captions with 9 presets and customization · TikTok safe-zone preview · product library and TikTok Shop profile ·
hook detection and ranking · 15-type sales-structure detection with notices about missing sections · restructuring (plan first) ·
fitting to a target duration · a natural-language assistant (plan, then Apply / Edit plan / Cancel) · AI edit history
with per-step undo, checkpoints and reset · Original vs AI preview · audio cleanup with A/B · color and one-tap enhance ·
product-visibility tracking (from product photos plus manual tags) · ad variations (hook × structure) as separate versions ·
compliance flags · pre-export and post-render quality checks · 9:16, 1:1 and 16:9 export at 720p/1080p (1440p/4K on Pro) ·
export queue · iPhone share sheet (save to Photos) · account and media deletion · plan limits and usage metering.

Anything not built yet is labeled **COMING SOON** in the app: smart B-roll, music, retention map, split-screen,
scripts/teleprompter/recording, style profiles, analytics, billing checkout and direct publishing.

## Tests
```bash
cd backend
python tests/make_fixture.py /tmp/fx      # synthetic messy footage + known transcript
python tests/e2e_test.py /tmp/fx          # 49 end-to-end checks: upload → AI → plans → undo → variations → export → QC
```
