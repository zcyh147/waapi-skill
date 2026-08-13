"""Durable, exact evidence rows for the #47 real macOS category gate."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


EVIDENCE_RELATIVE_PATH = Path(
    ".waapi-skill-state/evidence/full-typed-input/macos-category-evidence.jsonl"
)


def exact_git_candidate(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    candidate = completed.stdout.strip()
    if len(candidate) != 40:
        raise AssertionError("real category evidence requires an exact Git candidate")
    return candidate


def append_category_evidence(
    *,
    repo_root: Path,
    candidate: str,
    version: str,
    host: Mapping[str, Any],
    categories: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    residual_state: Mapping[str, Any],
) -> None:
    if len(candidate) != 40 or any(character not in "0123456789abcdef" for character in candidate):
        raise AssertionError("category evidence candidate is not an exact Git commit")
    required_category_fields = {"category", "status", "verifier_strength"}
    for category in categories:
        if not required_category_fields.issubset(category):
            raise AssertionError("category evidence row is incomplete")
        if category["status"] not in {"PASS", "FAIL", "blocked"}:
            raise AssertionError("category evidence status is not closed")
    payload = {
        "contract": "waapi-skill.macos-category-evidence/v1",
        "recorded_at_unix": int(time.time()),
        "candidate": candidate,
        "version": version,
        "host": dict(host),
        "categories": [dict(category) for category in categories],
        "source": dict(source),
        "residual_state": dict(residual_state),
    }
    configured = os.getenv("WWISE_MACOS_CATEGORY_EVIDENCE_PATH")
    target = (
        Path(configured).expanduser().resolve(strict=False)
        if configured
        else (repo_root / EVIDENCE_RELATIVE_PATH).resolve(strict=False)
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


__all__ = ["append_category_evidence", "exact_git_candidate"]
