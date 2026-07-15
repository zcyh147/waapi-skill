"""Canonical JSON and SHA-256 helpers used by durable local artifacts.

The encoding contract is deliberately small and explicit.  Keeping it in one
module prevents a confirmation hash from changing because one caller happened
to use pretty printing, ASCII escaping, or a different key order.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize *value* with the repository's canonical JSON contract.

    ``allow_nan=False`` is important for durable hashes: NaN and infinities are
    not JSON values and have multiple surprising comparison behaviours.
    """

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return the UTF-8 bytes of :func:`canonical_json`."""

    return canonical_json(value).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return a lowercase hexadecimal SHA-256 digest for *data*."""

    if not isinstance(data, bytes):
        raise TypeError("sha256_hex data must be bytes")
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: Any) -> str:
    """Hash the canonical UTF-8 JSON representation of *value*."""

    return sha256_hex(canonical_json_bytes(value))
