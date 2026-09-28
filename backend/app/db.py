"""Database access. SQLite (WAL) for dev/single-node; schema kept Postgres-portable."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterable

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  name TEXT, plan TEXT NOT NULL DEFAULT 'creator', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_products_user ON products(user_id);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'tiktok_shop',
  product_id TEXT, target_duration REAL, strength TEXT NOT NULL DEFAULT 'fast',
  settings TEXT NOT NULL DEFAULT '{}', active_version_id TEXT, status TEXT NOT NULL DEFAULT 'new',
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_projects_user ON projects(user_id);
CREATE TABLE IF NOT EXISTS media (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT, kind TEXT NOT NULL DEFAULT 'video',
  filename TEXT, original_path TEXT NOT NULL, proxy_path TEXT, enhanced_path TEXT, thumb_path TEXT, audio_path TEXT,
  duration REAL, width INTEGER, height INTEGER, fps REAL, has_audio INTEGER, info TEXT NOT NULL DEFAULT '{}',
  analysis TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'uploaded', error TEXT,
  position INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_media_project ON media(project_id);
CREATE INDEX IF NOT EXISTS ix_media_user ON media(user_id);
CREATE TABLE IF NOT EXISTS transcripts (
  media_id TEXT PRIMARY KEY, provider TEXT, language TEXT, words TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}',
  settings TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_versions_project ON versions(project_id);
CREATE TABLE IF NOT EXISTS ops (
  id TEXT PRIMARY KEY, version_id TEXT NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL,
  params TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'user', enabled INTEGER NOT NULL DEFAULT 1,
  group_id TEXT, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ops_version ON ops(version_id, seq);
CREATE TABLE IF NOT EXISTS checkpoints (
  id TEXT PRIMARY KEY, version_id TEXT NOT NULL, label TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, user_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
  progress REAL NOT NULL DEFAULT 0, message TEXT, attempts INTEGER NOT NULL DEFAULT 0, error TEXT, result TEXT,
  run_after REAL NOT NULL DEFAULT 0, locked_at REAL, created_at REAL NOT NULL, finished_at REAL
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status, run_after);
CREATE TABLE IF NOT EXISTS exports (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL, version_id TEXT NOT NULL,
  settings TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', output_path TEXT, qc TEXT, job_id TEXT,
  name TEXT, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_exports_user ON exports(user_id);
CREATE TABLE IF NOT EXISTS performance (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT, version_id TEXT, export_id TEXT, title TEXT,
  url TEXT, posted_at TEXT, metrics TEXT NOT NULL DEFAULT '{}', features TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_perf_user ON performance(user_id);
CREATE TABLE IF NOT EXISTS usage (
  user_id TEXT NOT NULL, period TEXT NOT NULL, processing_seconds REAL NOT NULL DEFAULT 0,
  exports INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id, period)
);
"""

JSON_COLS = {"data", "settings", "info", "analysis", "words", "meta", "params", "state", "payload", "result", "qc", "metrics", "features"}

_local = threading.local()
_init_lock = threading.Lock()
_initialized = False


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:20]


def now() -> float:
    return time.time()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def conn() -> sqlite3.Connection:
    global _initialized
    c = getattr(_local, "conn", None)
    if c is None:
        c = _connect()
        _local.conn = c
        with _init_lock:
            if not _initialized:
                c.executescript(SCHEMA)
                _initialized = True
    return c


def _decode(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in list(d):
        if k in JSON_COLS and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


def _encode(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"))
    if isinstance(v, bool):
        return int(v)
    return v


def one(sql: str, *args) -> dict | None:
    return _decode(conn().execute(sql, [_encode(a) for a in args]).fetchone())


def all_(sql: str, *args) -> list[dict]:
    return [_decode(r) for r in conn().execute(sql, [_encode(a) for a in args]).fetchall()]


def execute(sql: str, *args) -> int:
    return conn().execute(sql, [_encode(a) for a in args]).rowcount


def insert(table: str, row: dict) -> dict:
    cols = list(row)
    conn().execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [_encode(row[c]) for c in cols],
    )
    return row


def update(table: str, key: str, key_val: Any, fields: dict) -> None:
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    conn().execute(f"UPDATE {table} SET {sets} WHERE {key}=?", [_encode(v) for v in fields.values()] + [key_val])


@contextmanager
def transaction():
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def init() -> None:
    conn()


def placeholders(items: Iterable) -> str:
    return ",".join("?" * len(list(items)))
