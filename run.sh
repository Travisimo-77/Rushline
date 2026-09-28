#!/usr/bin/env bash
# One-command local run: builds the web app (if needed) and starts API + in-process worker on :8000.
set -euo pipefail
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "Please install ffmpeg first (macOS: brew install ffmpeg)"; exit 1; }
if [ ! -f frontend/dist/app.js ]; then (cd frontend && npm install && npm run build); fi
cd backend
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
echo "Rushline → http://localhost:8000   (on your iPhone, same Wi-Fi: http://$(ipconfig getifaddr en0 2>/dev/null || hostname -I | awk '{print $1}'):8000)"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
