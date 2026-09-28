"""Worker process: `python -m app.worker` (run N of these; each claims jobs atomically)."""
from __future__ import annotations

import logging
import signal
import sys
import threading
import time

from . import db, jobs
from .services.pipeline import HANDLERS, on_failed

log = logging.getLogger("rushline.worker")
_stop = threading.Event()


def run_once(kinds: list[str] | None = None) -> bool:
    job = jobs.claim(kinds)
    if not job:
        return False
    h = HANDLERS.get(job["kind"])
    try:
        if not h:
            raise jobs.PermanentError(f"no handler for {job['kind']}")
        log.info("job %s %s start", job["kind"], job["id"])
        res = h(job)
        jobs.finish(job["id"], res)
        log.info("job %s %s done", job["kind"], job["id"])
    except Exception as e:  # noqa: BLE001 — every failure is recorded, never crashes the worker
        retry = jobs.fail(job, e)
        log.exception("job %s %s failed (retry=%s)", job["kind"], job["id"], retry)
        if not retry:
            try:
                on_failed(job, str(e))
            except Exception:
                log.exception("on_failed handler error")
    return True


def loop(kinds: list[str] | None = None, idle: float = 0.5) -> None:
    db.init()
    while not _stop.is_set():
        try:
            if not run_once(kinds):
                _stop.wait(idle)
        except Exception:
            log.exception("worker loop error")
            time.sleep(2)


def start_background(n: int = 1) -> list[threading.Thread]:
    ts = []
    for i in range(n):
        t = threading.Thread(target=loop, name=f"worker-{i}", daemon=True)
        t.start()
        ts.append(t)
    return ts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    kinds = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    loop(kinds)
