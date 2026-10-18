"""Retain bounded native file bytes inside the existing category evidence row."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from wwise_waapi.operation_soundbank import capture_file_proof, open_regular_artifact_file


def observe_console_file(path: Path, *, io_root: Path) -> dict[str, Any]:
    """Capture a file without inferring its format or a successful business effect.

    The existing category finalizer retains this row before deleting a passing
    sandbox. No separate launcher, client, evidence publisher or oracle is added.
    """
    limit = 8 * 1024 * 1024
    proof = capture_file_proof(str(path), field="Console observation", max_bytes=limit, io_root=str(io_root))
    _, descriptor, before = open_regular_artifact_file(str(path), field="Console observation", io_root=str(io_root))
    with os.fdopen(descriptor, "rb") as stream:
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if (len(raw) != proof["size"] or hashlib.sha256(raw).hexdigest() != proof["sha256"]
            or any(getattr(before, key) != getattr(after, key)
                   for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))
            or capture_file_proof(str(path), field="Console observation", max_bytes=limit, io_root=str(io_root)) != proof):
        raise ValueError("Console artifact changed during evidence capture")
    return {"file_proof": proof, "content_base64": base64.b64encode(raw).decode("ascii"),
            "representation": "uninterpreted_native_file_bytes", "business_effect_verified": False}


class ConsoleModelImageIndex:
    """Durable local images of already observed sandbox XML, never an oracle."""

    MAX_WORK_UNITS = 512
    MAX_WORK_UNIT_BYTES = 256 * 1024 * 1024
    MAX_FILE_BYTES = 8 * 1024 * 1024
    MAX_INDEX_BYTES = 2 * 1024 * 1024

    def __init__(self, *, root: Path, project: Path, phase: str, link: dict[str, Any]):
        self.root, self.project, self.phase, self.link = root, project, phase, link
        assert phase in {"before", "after"}
        self.directory = root / phase
        self.directory.mkdir(exist_ok=False)
        self.index_path = self.directory / "index.json"
        self.files: dict[str, Any] = {}
        self.errors: list[str] = []
        self.work_units = self.work_unit_bytes = self.total_bytes = 0
        self._publish(complete=False)

    def _publish(self, *, complete: bool) -> None:
        import uuid
        body = {"representation": "exact_sandbox_model_file_images", "phase": self.phase,
            "complete": complete and not self.errors,
            "limits": {"work_units": self.MAX_WORK_UNITS, "project_files": 1,
                "work_unit_bytes": self.MAX_WORK_UNIT_BYTES, "file_bytes": self.MAX_FILE_BYTES,
                "project_bytes": self.MAX_FILE_BYTES, "index_bytes": self.MAX_INDEX_BYTES},
            "total_bytes": self.total_bytes, "files": self.files, "errors": self.errors}
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        assert len(raw) <= self.MAX_INDEX_BYTES, "Console model image index exceeds its byte bound"
        temporary = self.index_path.with_name("index-" + uuid.uuid4().hex + ".tmp")
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.index_path)
        proof = capture_file_proof(self.index_path, field="Console model image index",
            max_bytes=self.MAX_INDEX_BYTES, io_root=self.root)
        assert proof["sha256"] == hashlib.sha256(raw).hexdigest()
        self.link.update(index_path=str(self.index_path), sha256=proof["sha256"], size=proof["size"],
            complete=body["complete"], file_count=len(self.files), total_bytes=self.total_bytes)

    def save(self, path: Path, observation: dict[str, Any]) -> bytes:
        from wwise_waapi.operation_soundbank import prove_artifact_path
        relative = path.relative_to(self.project.parent).as_posix()
        assert relative not in self.files
        assert path == self.project or path.suffix == ".wwu"
        assert len(self.files) < self.MAX_WORK_UNITS + 1, "Console model image file count exceeded"
        raw = base64.b64decode(observation["content_base64"], validate=True)
        proof = observation["file_proof"]
        assert len(raw) <= self.MAX_FILE_BYTES and len(raw) == proof["size"]
        assert hashlib.sha256(raw).hexdigest() == proof["sha256"]
        if path != self.project:
            assert self.work_units < self.MAX_WORK_UNITS, "Console model image Work Unit count exceeded"
            assert self.work_unit_bytes + len(raw) <= self.MAX_WORK_UNIT_BYTES, "Console model image Work Unit byte bound exceeded"
        destination = self.directory / "files" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        prove_artifact_path(destination, io_root=self.root, field="Console model image", must_exist=False, expect_directory=False)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        copied = capture_file_proof(destination, field="Console model image", max_bytes=self.MAX_FILE_BYTES, io_root=self.root)
        assert copied["size"] == len(raw) and copied["sha256"] == proof["sha256"]
        self.files[relative] = {"status": "captured", "size": len(raw), "sha256": proof["sha256"],
            "file_proof": proof, "artifact_path": destination.relative_to(self.root).as_posix(), "artifact_proof": copied}
        self.total_bytes += len(raw)
        if path != self.project:
            self.work_units += 1
            self.work_unit_bytes += len(raw)
        self._publish(complete=False)
        return raw

    def error(self, path: Path | None, exc: Exception) -> None:
        message = str(exc)[:2048]
        if len(self.errors) < self.MAX_WORK_UNITS + 2:
            self.errors.append(message)
        if path is not None and len(self.files) < self.MAX_WORK_UNITS + 1:
            relative = path.relative_to(self.project.parent).as_posix()
            if relative not in self.files:
                self.files[relative] = {"status": "missing" if not path.exists() and not path.is_symlink()
                    else "capture_error", "capture_error": message}
        self.link.update(complete=False, capture_error=message)

    def finish(self) -> None:
        self._publish(complete=True)
