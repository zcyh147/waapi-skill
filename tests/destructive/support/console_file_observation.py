"""Retain bounded native file bytes inside the existing category evidence row."""
from __future__ import annotations

import base64
import hashlib
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
