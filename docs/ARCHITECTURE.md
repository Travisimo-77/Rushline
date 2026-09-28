# Rushline — Architecture & Build Plan

> **Rushline** turns raw creator footage ("rushes") into sales-ready short-form ads.
> Original brand, UI, and code. Not affiliated with, or derived from, any other editor.

Core loop: **UPLOAD RAW → UNDERSTAND (speech + product + sales intent) → CLEAN → BUILD ADS → REVIEW → EXPORT**

What makes it different: a normal auto-editor models *video*. Rushline also models
*what is said*, *what is sold*, *how the ad is structured*, *what footage exists*, and, in Phase 3,
*what has worked for this creator before*.

---

## 1. Product architecture

```
┌──────────────────────────── Clients ────────────────────────────┐
│ Mobile-first web app / PWA (iPhone Safari, Android, desktop)     │
│ Future: native iOS/Android shell (Capacitor) for camera + share   │
└───────────────┬──────────────────────────────────────────────────┘
                │ HTTPS (JSON API + signed media URLs)
┌───────────────▼──────────────────────────────────────────────────┐
│ API service (ASGI, stateless)                                     │
│  auth · projects · media · products · timeline ops · AI plans ·   │
│  exports · billing/usage · signed-URL media streaming             │
└───────┬───────────────┬──────────────────────┬───────────────────┘
        │               │                      │
   ┌────▼────┐    ┌─────▼─────┐          ┌─────▼─────────────┐
   │   DB    │    │  Object   │          │  Job queue         │
   │(SQLite →│    │  storage  │          │ (DB-backed, SKIP   │
   │Postgres)│    │(local→S3) │          │  LOCKED in PG)     │
   └─────────┘    └───────────┘          └─────┬─────────────┘
                                               │
             ┌─────────────────────────────────▼───────────────────────┐
             │ Workers (horizontally scalable, one job type per queue)  │
             │ ingest/probe → proxy → audio analysis → transcription →  │
             │ visual analysis → AI analysis → render → export QC       │
             └──────────────────────────────────────────────────────────┘
```

Every AI capability is a **provider behind an interface** (`app/ai/*`), so Whisper can be swapped for
another ASR, heuristics for an LLM, ORB matching for a vision model, without touching the editor.

## 2. Complete user flow

1. **Sign up / sign in** (email + password; OAuth later).
2. **Home** → pick an intent: *TikTok Shop Edit*, *Clean Raw Footage*, *Generate Ad Variations*, or *New Project*.
3. **Create project** → name, mode (Clean / TikTok Shop), target length, cleanup strength (Clean / Fast / Viral),
   optional linked **product** from the library.
4. **Upload** one or many clips (iPhone camera roll, files, drag & drop). Upload is chunked/resumable-ready.
5. **Processing** (background, visible progress): probe → proxy → audio analysis → transcript → visual/product scan → AI analysis.
6. **Editor opens with an AI first-pass** (a checkpoint is created first):
   dead space, fillers, stutters, retakes removed per the chosen strength; sections labelled; hooks ranked.
7. **Review**: watch AI edit vs original, read AI history, undo any single action, edit by transcript or timeline.
8. **Improve**: TikTok Shop optimize, restructure (plan shown first), target duration, show product earlier,
   natural-language requests ("make this 20 seconds and use the price hook").
9. **Variations**: generate multiple ad versions (hook × structure); each version is independently editable.
10. **Captions / audio / color** styling.
11. **Export**: quality check → warnings → queue → notification → download (Files app on iPhone / Share sheet).

## 3. Screen map

```
Auth ─ Sign in / Sign up
App shell (bottom tab bar on phones, left rail on desktop)
├─ Home          quick actions · recent projects · saved products · recent exports
├─ Projects      list/grid · search · create
│   └─ Editor    preview · quick AI actions · timeline · transcript · AI panel
│       ├─ AI tab: Plan/Assistant chat · Recommendations · Hooks · Structure · Product visibility
│       ├─ Transcript tab
│       ├─ History tab (AI + manual edits, per-item undo, checkpoints)
│       ├─ Style tab: captions · audio · color
│       ├─ Versions sheet
│       └─ Export sheet (QC report → queue)
├─ Products      library · product profile editor (photos, claims, CTA…)
├─ Media         all uploaded media, processing status, delete controls
├─ Exports       queue + finished files
├─ Scripts       COMING SOON (Phase 2)
├─ Templates     COMING SOON (Phase 2 — creator style profiles)
├─ Analytics     COMING SOON (Phase 3)
└─ Account       plan & usage, data export/deletion, sign out
```

## 4. Wireframe descriptions

**Home (phone):** greeting header; 2×2 grid of large rounded action cards (TikTok Shop Edit — accent, Clean Raw Footage,
Generate Variations, New Project); horizontal scroller of recent projects (thumbnail + duration + status chip);
saved products row; recent exports list. Bottom tab bar: Home · Projects · Products · Exports · Account.

**Editor (phone, portrait):** top bar (back, project name, save indicator, Export button).
9:16 preview fills ~55% of height with play/scrub, Original/AI toggle, safe-zone toggle.
Below: horizontal chip row of quick AI actions (scrollable). Then a compact timeline (section-coloured clip blocks,
playhead, pinch-free zoom via +/- buttons, tap to select, drag handle to reorder). Bottom sheet with tabs:
AI · Transcript · History · Style · Versions. Plans from the AI appear as a card with **Apply / Edit plan / Cancel**.

**Editor (desktop):** 3 columns — left: transcript; centre: preview + quick actions + timeline; right: AI panel.

**Product profile:** stacked form cards: basics (name, category, price, discount, URL), media (photos used for
product detection), selling points (features, benefits, audience), compliance (approved claims, claims to avoid),
CTA & brand requirements, desired length.

**Export sheet:** aspect (9:16 / 1:1 / 16:9), resolution, fps, quality preset → **Run quality check** → list of
pass/warn/fail items → **Queue export**.

## 5. Database schema

(Implemented in `backend/app/db.py`; SQLite for dev, same schema portable to Postgres.)

| table | key columns |
|---|---|
| `users` | id, email (unique), password_hash (PBKDF2-SHA256, 310k iters), name, plan, created_at, deleted_at |
| `products` | id, user_id, name, category, price, discount, shipping, url, cta, features[], benefits[], audience, approved_claims[], avoid_claims[], notes, brand_requirements, desired_length, photos[] |
| `projects` | id, user_id, name, mode, product_id, target_duration, strength, settings(json), active_version_id, created_at, updated_at |
| `media` | id, user_id, project_id, kind(video/image/product_photo), original_path, proxy_path, enhanced_proxy_path, thumb_path, duration, width, height, fps, rotation, has_audio, codec, status, error, analysis(json: silences, loudness, visual, product_hits) |
| `transcripts` | id, media_id, provider, language, words(json: [{i,t,s,e,p,filler}]), segments(json) |
| `versions` | id, project_id, name, label, meta(json: hook, structure, target) , created_at |
| `ops` | id, version_id, seq, kind, label, params(json), source ('ai'/'user'/'assistant'), enabled, group_id, created_at |
| `checkpoints` | id, version_id, label, enabled_op_ids(json), created_at |
| `jobs` | id, user_id, kind, payload(json), status(queued/running/done/failed), progress, attempts, error, result(json), locked_at, created_at |
| `exports` | id, user_id, project_id, version_id, settings(json), status, output_path, qc(json), job_id, created_at |
| `usage` | id, user_id, period, processing_seconds, exports |

**Non-destructive guarantee:** no table ever stores a modified copy of source media. Timelines are *derived* by replaying
`ops` over the immutable source + transcript.

## 6. Backend architecture

- `app/main.py` — ASGI app, routing, static PWA hosting.
- `app/api/*` — thin HTTP handlers; validate, authorize (user owns resource), call services.
- `app/services/*` — business logic (project creation, first-pass pipeline orchestration, variations).
- `app/timeline.py` — the edit model: op vocabulary + deterministic replay engine.
- `app/jobs.py` + `app/worker.py` — durable queue, retries with backoff, idempotent handlers, progress reporting.
- `app/media/*` — ffmpeg/ffprobe wrappers (probe, proxy, audio, visual, render, QC).
- `app/ai/*` — pluggable AI providers.
- Stateless API → scale behind a load balancer. Workers scale independently (CPU for render, GPU for ASR).

## 7. AI architecture

| capability | MVP provider | upgrade path |
|---|---|---|
| Transcription + word timestamps | faster-whisper (local), OpenAI Whisper API | WhisperX alignment, Deepgram/AssemblyAI |
| Silence / dead space | RMS energy + adaptive noise floor (numpy) | VAD model (Silero) |
| Fillers / stutters / false starts | lexical + timing rules on word stream | disfluency classifier |
| Retake detection | sentence similarity + prefix (false start) matching, best-take scoring | embedding similarity + audio quality |
| Sales structure | weighted lexicon + product-profile matching; optional LLM classifier | fine-tuned classifier |
| Hook analysis | feature scoring over real recorded lines only | LLM + creator history |
| Restructuring / duration | constraint-based planner (keep hook/product/CTA, drop by priority) | LLM planner validated by same constraints |
| NL assistant | intent grammar → op plan; optional LLM (Anthropic) emitting the same JSON op schema | tool-use agent |
| Product visibility | ORB feature matching vs product photos + optional manual tagging | CLIP / open-vocabulary detector |
| Visual quality | blackdetect / freezedetect / luma & saturation stats | aesthetic model |

**Safety rules baked into the planner:** only whole recorded sentences are moved; dependent sentences ("and that's why…")
travel with their antecedent; nothing is synthesized; hooks come only from recorded lines unless the user asks for
*script* suggestions; every AI change is an op that can be disabled; big structural changes are returned as a **plan**
before application.

## 8. Video-processing architecture

1. **Ingest:** upload streamed to storage → `ffprobe` (duration, streams, rotation, HDR/HEVC, VFR).
2. **Proxy:** H.264 High / AAC, 540p (short side), constant 30 fps, `+faststart`, rotation baked in → plays inline on iPhone Safari.
   Originals untouched and used for export.
3. **Audio analysis:** 16 kHz mono WAV → RMS frames (10 ms) → silence spans; loudness & peak.
4. **Transcription** on the WAV (chunked in 10-minute windows with 5 s overlap for long recordings, merged on word time).
5. **Visual analysis:** 2 fps frame samples → black/blank frames, motion, product matches.
6. **AI analysis** → first-pass ops.
Long recordings: every stage is chunk-aware, results merged into project-level context.

## 9. Rendering architecture

- Replay ops → **render plan**: ordered clips (source file, in/out, speed, volume, zoom, rotation, colour).
- One ffmpeg process: per-clip accurate input seek (`-ss/-t`), per-clip filters (scale/crop to target aspect,
  punch-in zoom, eq, speed with `setpts`/`atempo`), audio padded/trimmed to exact video length **per clip**
  (prevents cumulative A/V drift), `concat` filter, master audio chain (high-pass → denoise → compressor → loudnorm −14 LUFS
  → true-peak limiter), captions burned via ASS (libass).
- Post-render QC: stream durations, A/V delta, black/frozen frames, resolution, loudness.
- Atomic output: render to `*.part`, verify, rename. Failed renders never overwrite a good file.

## 10. Recommended technology stack

| layer | choice | why |
|---|---|---|
| Frontend | React 19 + TypeScript, esbuild; PWA (manifest + service worker) | fast, one codebase for iPhone/desktop |
| API | Python 3.11 + Starlette (ASGI) + Uvicorn | same language as media/AI stack |
| DB | SQLite (dev/single node) → PostgreSQL 16 (prod) | portable schema |
| Queue | DB-backed jobs (→ PG `SKIP LOCKED`; Redis/Celery optional) | no extra infra for MVP |
| Storage | local FS → S3/R2/GCS with signed URLs | |
| Media | FFmpeg 6+ with libx264, libass | |
| ASR | faster-whisper (CTranslate2) / OpenAI API | |
| Vision | OpenCV (ORB); later CLIP/ONNX | |
| LLM (optional) | Anthropic Messages API | structured plans |
| Payments | Stripe Billing (Phase 1.5) | |
| Deploy | Docker Compose → containers on Fly/Render/ECS; Caddy for automatic HTTPS | HTTPS needed for iPhone PWA install |

## 11. API architecture (REST, JSON, `/api/v1`)

```
POST   /auth/signup | /auth/login          GET /auth/me
GET    /projects            POST /projects          GET|PATCH|DELETE /projects/{id}
POST   /projects/{id}/media (multipart upload)      GET /projects/{id}/state
POST   /projects/{id}/first-pass            (queue AI first pass)
GET    /versions/{id}/timeline              (derived timeline, captions, sections, diagnostics)
POST   /versions/{id}/ops                   (append op(s))  PATCH /ops/{id} (enable/disable)
POST   /versions/{id}/checkpoints           POST /checkpoints/{id}/restore
POST   /versions/{id}/ai/{action}           (returns a PLAN; apply = POST ops)
POST   /versions/{id}/assistant             (NL → plan)
POST   /projects/{id}/variations            (plan / create versions)
GET    /versions/{id}/qc                    POST /versions/{id}/exports
GET    /exports   GET /jobs/{id}
CRUD   /products  POST /products/{id}/photos
GET    /media     DELETE /media/{id}        GET /media/{id}/stream?token=… (signed, Range-enabled)
DELETE /account
```

## 12. Storage architecture

```
storage/
  users/{user_id}/
    media/{media_id}/original.ext        (immutable, never modified)
    media/{media_id}/proxy.mp4           (derived, regenerable)
    media/{media_id}/proxy_enhanced.mp4  (derived)
    media/{media_id}/audio16k.wav        (derived)
    media/{media_id}/thumb.jpg
    products/{product_id}/{photo}.jpg
    exports/{export_id}.mp4
```
Derived files are disposable (can be regenerated); originals are the only precious data. Per-user prefix + signed
URLs (HMAC, 1 h TTL) mean one user's media cannot be addressed by another.

## 13. Background-job architecture

- Job kinds: `ingest`, `transcribe`, `analyze`, `first_pass`, `enhance_audio`, `render`.
- Chains: `ingest` enqueues `transcribe` → `analyze`; `first_pass` waits for all media `ready`.
- Claim: atomic `UPDATE … SET status='running' WHERE id=(SELECT … LIMIT 1) RETURNING` (PG: `FOR UPDATE SKIP LOCKED`).
- Retries: 3 attempts with backoff; stale `running` jobs (worker died) are re-queued after timeout.
- Idempotent handlers (outputs written to temp then renamed).
- Progress written to the job row; the UI polls (SSE/WebSocket later).

## 14. MVP breakdown (✅ = implemented in this codebase)

| # | Feature | Status |
|---|---|---|
|1|Authentication|✅ email/password, PBKDF2, JWT|
|2|Project dashboard|✅|
|3|Video upload (multi-clip, iPhone camera roll)|✅|
|4|Proxy generation|✅ H.264 540p/30fps faststart|
|5|Automatic transcription|✅ provider interface: faster-whisper / OpenAI / sidecar|
|6|Transcript-based editing|✅ select words → delete/restore; filler highlights; search|
|7|Dead-space removal|✅ energy-based, word-boundary protected|
|8|Retake detection|✅ similarity + false-start detection, best-take choice|
|9|Filler-word removal|✅ um/uh/like (contextual) etc. + stutters|
|10|Editable timeline|✅ select, split, delete, duplicate, move, trim, speed, volume, zoom, rotate|
|11|Auto captions|✅ derived from words, always in sync|
|12|Caption styling|✅ 9 presets + custom, safe-zone preview|
|13|TikTok Shop product profile|✅|
|14|Hook detection|✅ ranked recorded hooks with categories|
|15|Problem/solution/benefit/CTA detection|✅ 15 section types + missing-section notices|
|16|Basic AI restructuring|✅ plan → apply|
|17|Target video duration|✅|
|18|NL editing assistant|✅ grammar-based; optional LLM|
|19|AI edit history|✅ per-op undo + checkpoints|
|20|Before/after preview|✅ Original ↔ AI toggle|
|21|Audio cleanup|✅ denoise/HPF/compress/loudnorm/limiter + A/B preview|
|22|Basic color adjustment|✅ brightness/contrast/saturation/temperature + auto enhance|
|23|Product visibility tracking|✅ ORB vs product photos + manual tags|
|24|9:16 export|✅ (+1:1, 16:9)|
|25|1080p export|✅ (+720p)|
|26|Multiple ad variations|✅ hook × structure versions|
|27|Product library|✅|
|28|Stable autosave|✅ every edit persisted as an op; checkpoints|
|29|Export quality check|✅ pre + post render|
|30|Non-destructive edits|✅ op-replay model|

## 15. Phase 2

Advanced B-roll engine & semantic footage search · automatic creative variations at scale · retention map with one-tap fixes ·
split-screen comparisons · recording assistant + teleprompter (iPhone camera via `getUserMedia`/MediaRecorder) · script generator & quality check ·
creator style profiles · long-recording support (60 min+, chunked ASR already designed in) · batch generation · 4K export ·
advanced audio (voice isolation, music + ducking) · advanced colour (curves, skin-tone protection) · compliance assistant with claim sources.

## 16. Phase 3

Performance data import/entry & creator learning · official TikTok / TikTok Shop / YouTube / Instagram integrations where APIs allow ·
personalised recommendations · feedback loops · advanced A/B (hook-only, CTA-only) · team workspaces, brand accounts, shared libraries,
collaboration, approval workflows · direct publishing.

## 17. Folder structure

```
rushline/
  README.md  run.sh
  docs/ARCHITECTURE.md
  backend/
    app/
      main.py            ASGI app, security headers, static PWA
      config.py db.py security.py storage.py jobs.py worker.py
      timeline.py        non-destructive op model + deterministic replay
      api/routes.py      REST API (/api/v1)
      services/          context.py (derived view) · plans.py (AI planners) · versions.py (apply/checkpoints/variations) · pipeline.py (jobs)
      media/             ffmpeg.py · proxy.py · analysis.py (audio/visual/product) · captions.py (layout + ASS) · render.py · qc.py
      ai/                text.py · cleanup.py (dead space/fillers/stutters/mistakes/retakes) · structure.py (sections/hooks/diagnostics)
                         assistant.py (NL grammar) · llm.py (optional) · transcribe.py (providers) · compliance.py
    fonts/               Poppins (OFL) — identical captions in preview and export
    tests/               make_fixture.py · e2e_test.py
    requirements.txt
  frontend/
    public/              index.html · manifest.webmanifest · sw.js · icons/
    src/                 main.tsx · app.tsx · api.ts · ui.tsx · styles.css
      pages/             Auth · Home · NewProject · Projects · Products · Media · Exports · Account · Soon
      editor/            Editor · Player (EDL playback) · Timeline · Transcript · Panels · PlanCard · ExportSheet
    build.mjs package.json tsconfig.json
  deploy/                Dockerfile · docker-compose.yml · Caddyfile (auto-HTTPS)
```

## 18. Security considerations

- TLS everywhere (Caddy auto-HTTPS); HSTS.
- Passwords: PBKDF2-SHA256 310k iterations, per-user salt; constant-time compare.
- JWT (HS256, 7-day) for API; **separate short-lived HMAC media tokens** for `<video src>` (iOS can't send headers).
- Every query scoped by `user_id`; ownership checked on every resource id (no IDOR).
- Uploads: size limit, extension + ffprobe validation, files stored under random ids (no user-controlled paths).
- ffmpeg invoked with argument arrays (no shell), captions written to files (no filter injection), timeouts.
- Media deletion + account deletion endpoints purge storage; retention policy: exports auto-expire after 30 days (configurable).
- Project recovery and source access are never plan-gated.
- Rate limiting and audit log: Phase 2 (reverse-proxy level for MVP).

## 19. Estimated infrastructure requirements

| scale | API | workers | storage | notes |
|---|---|---|---|---|
| Dev / single creator | 1 small VM (2 vCPU/4 GB) running everything | same box | local disk | CPU Whisper `small` ≈ 0.3–0.5× realtime |
| 1k creators, ~20k raw min/mo | 2× API (1 vCPU) | 4× CPU render (8 vCPU) + 1 GPU (T4/L4) for ASR | S3 ~2–5 TB | Postgres managed |
| 50k creators | autoscaled API | render pool autoscaled on queue depth; GPU ASR pool | S3 + CDN, lifecycle rules | move queue to Redis/SQS |

Rule of thumb: 1080p 30 s ad render ≈ 10–20 s CPU on 4 vCPU; proxy of 10 min 4K ≈ 1–2 min.

## 20. Major technical risks

1. A/V desync at cut points (VFR iPhone footage, AAC priming).
2. Cutting into words (clipped consonants) → unnatural speech.
3. Retake detection deleting the *wrong* take or unique content.
4. Restructuring changing meaning.
5. ASR errors on product names / slang.
6. Long files: memory/time blowups; worker crashes mid-render.
7. iPhone specifics: HEVC/HDR (Dolby Vision) sources, rotation metadata, Safari video quirks, PWA limits.
8. Product detection false positives/negatives.
9. Cost of GPU ASR at scale.
10. Data loss / project corruption.

## 21. Solutions

1. Proxies & renders forced to constant frame rate; per-clip audio `apad+atrim` to exact video length; post-render A/V delta check.
2. All cuts snapped to word boundaries with 60–90 ms guard bands; minimum-gap rule prevents micro-cuts.
3. Only near-duplicate sentences grouped; best take scored; removed takes remain visible in transcript & history, one tap to restore.
4. Only whole recorded sentences move; dependent-clause detection keeps pairs together; restructures always shown as a plan.
5. Product name & terms passed as ASR `initial_prompt`; transcript editable.
6. Chunked processing; streaming reads; job leases with re-queue; atomic output writes.
7. Proxy transcode normalizes HEVC/HDR→SDR H.264 with rotation baked in; `playsinline`, `+faststart`; export H.264 High/AAC (plays everywhere); HTTPS for PWA install.
8. Detection is labelled a heuristic; manual "product visible here" tagging overrides.
9. Provider abstraction lets you route short jobs to API, long to self-hosted GPU.
10. Ops append-only in DB (WAL), checkpoints before every AI pass, originals immutable.

## 22. Development order

1. Repo skeleton, config, DB schema, auth → 2. storage + upload + probe + proxy → 3. job queue/worker →
4. audio analysis + transcription providers → 5. timeline op model + replay → 6. cleanup (silence, fillers, retakes) →
7. structure/hook analysis + diagnostics → 8. restructure/duration/variations planners → 9. NL assistant →
10. render + captions + audio/colour + QC → 11. frontend shell/PWA → 12. editor (player, timeline, transcript, AI panel) →
13. products/media/exports/account pages → 14. end-to-end tests → 15. deployment (Docker + HTTPS).

---

## iPhone access

Rushline is a **mobile-first Progressive Web App**:
- Open the site in Safari → Share → **Add to Home Screen** → it launches full-screen like a native app (needs HTTPS).
- Upload directly from **Photos** or **Files**; HEVC/HDR/Dolby Vision clips are normalized server-side.
- Video uses `playsinline` H.264 proxies (instant playback, seekable via HTTP Range).
- Layout respects the notch/Dynamic Island & home indicator (`env(safe-area-inset-*)`), 44 pt touch targets,
  bottom tab bar, bottom sheets, no hover-only controls.
- Exports download to Files or open the iOS share sheet (Web Share API) to save to Photos / post.
- Native App Store wrapper (Capacitor) is a Phase 2 option for background upload & in-app camera.
