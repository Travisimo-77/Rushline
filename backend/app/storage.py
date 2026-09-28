"""Storage abstraction. LocalStorage for dev; an S3-compatible backend implements the same interface.

Original uploads are write-once: `write_original` refuses to overwrite and nothing in the codebase
opens originals for writing afterwards.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import STORAGE_DIR


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root

    def user_dir(self, user_id: str) -> Path:
        return self.root / "users" / user_id

    def media_dir(self, user_id: str, media_id: str) -> Path:
        p = self.user_dir(user_id) / "media" / media_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def product_dir(self, user_id: str, product_id: str) -> Path:
        p = self.user_dir(user_id) / "products" / product_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def export_path(self, user_id: str, export_id: str) -> Path:
        p = self.user_dir(user_id) / "exports"
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{export_id}.mp4"

    def abs(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise PermissionError("path escapes storage root")
        return p

    def rel(self, p: Path) -> str:
        return str(Path(p).resolve().relative_to(self.root.resolve()))

    def write_original(self, dest: Path, stream_chunks) -> int:
        if dest.exists():
            raise FileExistsError("original media is immutable")
        tmp = dest.with_suffix(dest.suffix + ".part")
        size = 0
        with open(tmp, "wb") as f:
            for chunk in stream_chunks:
                f.write(chunk)
                size += len(chunk)
            f.flush()
            os.fsync(f.fileno())
        tmp.rename(dest)
        dest.chmod(0o440)  # read-only on disk as an extra guard
        return size

    def delete_tree(self, p: Path) -> None:
        if p.exists():
            for root, dirs, files in os.walk(p):
                for f in files:
                    try:
                        os.chmod(os.path.join(root, f), 0o640)
                    except OSError:
                        pass
            shutil.rmtree(p, ignore_errors=True)


storage = LocalStorage(STORAGE_DIR)
