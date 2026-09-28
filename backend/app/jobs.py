"""Durable DB-backed job queue with leases, retries and progress."""
from __future__ import annotations

import time
import traceback

from . import db

LEASE_SECONDS = 30 * 60
MAX_ATTEMPTS = 3


def enqueue(kind: str, payload: dict, user_id: str | None = None, delay: float = 0) -> str:
    jid = db.new_id("job_")
    db.insert("jobs", {
        "id": jid, "user_id": user_id, "kind": kind, "payload": payload, "status": "queued",
        "run_after": db.now() + delay, "created_at": db.now(),
    })
    return jid


def claim(kinds: list[str] | None = None) -> dict | None:
    """Atomically claim the next runnable job. Also recovers jobs whose worker died (lease expired)."""
    now = db.now()
    with db.transaction() as c:
        c.execute(
            "UPDATE jobs SET status='queued', run_after=? WHERE status='running' AND locked_at < ?",
            (now, now - LEASE_SECONDS),
        )
        q = "SELECT id FROM jobs WHERE status='queued' AND run_after<=?"
        args: list = [now]
        if kinds:
            q += f" AND kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        q += " ORDER BY created_at LIMIT 1"
        row = c.execute(q, args).fetchone()
        if not row:
            return None
        c.execute(
            "UPDATE jobs SET status='running', locked_at=?, attempts=attempts+1, progress=0 WHERE id=?",
            (now, row["id"]),
        )
    return db.one("SELECT * FROM jobs WHERE id=?", row["id"])


def progress(job_id: str, p: float, message: str | None = None) -> None:
    db.update("jobs", "id", job_id, {"progress": max(0.0, min(1.0, p)), "message": message, "locked_at": db.now()})


def finish(job_id: str, result: dict | None = None) -> None:
    db.update("jobs", "id", job_id, {"status": "done", "progress": 1.0, "result": result or {}, "finished_at": db.now()})


def fail(job: dict, exc: BaseException) -> bool:
    """Returns True if the job will be retried."""
    err = "".join(traceback.format_exception_only(type(exc), exc)).strip()[:2000]
    if job["attempts"] < MAX_ATTEMPTS and not isinstance(exc, PermanentError):
        db.update("jobs", "id", job["id"], {"status": "queued", "error": err, "run_after": time.time() + 5 * job["attempts"] ** 2})
        return True
    db.update("jobs", "id", job["id"], {"status": "failed", "error": err, "finished_at": db.now()})
    return False


class PermanentError(Exception):
    """Raise for errors retrying won't fix (bad input file, etc.)."""


def recover_after_restart() -> int:
    """Single-process mode: any job marked running belongs to a worker that died with the old process."""
    return db.execute("UPDATE jobs SET status='queued', run_after=0, attempts=0, error=NULL WHERE status='running'")
