# Rushline — single-container web app (API + AI worker + web app in one).
# Works on Hugging Face Spaces (Docker), Render, Railway, Fly.io, Koyeb, a VPS, etc.
# The web app is already built in frontend/dist, so no Node.js is needed here.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fontconfig \
    && rm -rf /var/lib/apt/lists/*

# run as a normal user (required by Hugging Face Spaces, good practice everywhere)
RUN useradd -m -u 1000 rushline
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=rushline backend/ ./
COPY --chown=rushline frontend/dist /app/frontend/dist
RUN mkdir -p /data && chown -R rushline /data

USER rushline
ENV RUSHLINE_DATA_DIR=/data \
    RUSHLINE_FRONTEND=/app/frontend/dist \
    RUSHLINE_INPROC_WORKERS=2 \
    HF_HOME=/data/.models \
    PORT=7860
EXPOSE 7860

# download the speech-to-text model on first use; the host gives us $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
