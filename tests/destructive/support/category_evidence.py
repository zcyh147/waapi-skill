"""Durable, exact evidence rows for the real host category gates."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


EVIDENCE_ROOT = Path(".waapi-skill-state/evidence/full-typed-input")


def current_evidence_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    raise AssertionError(f"real category evidence does not support host platform {sys.platform!r}")


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
    invocation: Mapping[str, Any] | None = None,
    transactions: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    if len(candidate) != 40 or any(character not in "0123456789abcdef" for character in candidate):
        raise AssertionError("category evidence candidate is not an exact Git commit")
    required_category_fields = {"category", "status", "verifier_strength"}
    for category in categories:
        if not required_category_fields.issubset(category):
            raise AssertionError("category evidence row is incomplete")
        if category["status"] not in {"PASS", "FAIL", "blocked"}:
            raise AssertionError("category evidence status is not closed")
    platform_name = current_evidence_platform()
    if (invocation is None) != (transactions is None):
        raise AssertionError(
            "exact category evidence requires invocation and transactions together"
        )
    if invocation is not None and transactions is not None:
        required_invocation_fields = {
            "selected_test_nodeids",
            "started_at_unix_ns",
            "finished_at_unix_ns",
            "outcome",
        }
        if set(invocation) != required_invocation_fields:
            raise AssertionError("exact category evidence invocation fields are invalid")
        nodeids = invocation["selected_test_nodeids"]
        started_at = invocation["started_at_unix_ns"]
        finished_at = invocation["finished_at_unix_ns"]
        if (
            not isinstance(nodeids, list)
            or not nodeids
            or not all(isinstance(nodeid, str) and nodeid for nodeid in nodeids)
            or not isinstance(started_at, int)
            or isinstance(started_at, bool)
            or not isinstance(finished_at, int)
            or isinstance(finished_at, bool)
            or finished_at < started_at
            or invocation["outcome"] not in {"PASS", "FAIL"}
        ):
            raise AssertionError("exact category evidence invocation values are invalid")
        required_transaction_fields = {
            "transaction_id",
            "state",
            "artifact_hash",
            "event_sequence",
        }
        if any(set(transaction) != required_transaction_fields for transaction in transactions):
            raise AssertionError("exact category evidence transaction fields are invalid")
    payload = {
        "contract": (
            "waapi-skill.host-category-evidence/v2"
            if invocation is not None
            else "waapi-skill.host-category-evidence/v1"
        ),
        "recorded_at_unix": int(time.time()),
        "platform": platform_name,
        "candidate": candidate,
        "version": version,
        "host": dict(host),
        "categories": [dict(category) for category in categories],
        "source": dict(source),
        "residual_state": dict(residual_state),
    }
    if invocation is not None and transactions is not None:
        payload["invocation"] = dict(invocation)
        payload["transactions"] = [dict(transaction) for transaction in transactions]
    configured = os.getenv("WWISE_CATEGORY_EVIDENCE_PATH")
    if configured is None and platform_name == "macos":
        configured = os.getenv("WWISE_MACOS_CATEGORY_EVIDENCE_PATH")
    default_path = EVIDENCE_ROOT / f"{platform_name}-category-evidence.jsonl"
    target = (
        Path(configured).expanduser().resolve(strict=False)
        if configured
        else (repo_root / default_path).resolve(strict=False)
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


__all__ = ["append_category_evidence", "current_evidence_platform", "exact_git_candidate"]
