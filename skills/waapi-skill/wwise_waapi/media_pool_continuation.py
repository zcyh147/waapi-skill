"""Content-bound continuations for a native search with no offset argument.

A continuation explicitly asks for a larger bounded prefix. It certifies the
entire preceding native prefix before exposing later rows. Tokens carry no
write authority and never authorize a different query or host session.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Any, Mapping, Sequence

from .canonical import canonical_json_bytes, canonical_sha256
from .filesystem_security import path_is_link_or_reparse
from .media_build_business import MAX_MEDIA_POOL_RESULTS, validate_media_pool_business_plan


class MediaPoolContinuationError(ValueError):
    code = "MEDIA_POOL_CONTINUATION_CHANGED"


class MediaPoolQueryStore:
    """Immutable read plans, outside the project, with no mutation authority."""

    _HANDLE = re.compile(r"^mpq1-[0-9a-f]{32}$")
    MAX_RECORDS = 128
    MAX_RECORD_BYTES = 512 * 1024
    MAX_TOTAL_BYTES = 16 * 1024 * 1024

    def __init__(self, state_dir: Path):
        self.root = state_dir / "media-pool-query-plans-v1"

    @classmethod
    def validate_handle(cls, handle: str) -> None:
        if not isinstance(handle, str) or not cls._HANDLE.fullmatch(handle):
            raise MediaPoolContinuationError("Expected one Gateway-issued Media Pool query handle")

    def _directory(self, *, create: bool) -> None:
        for path in [*reversed(self.root.parents), self.root]:
            if os.path.lexists(path):
                if path_is_link_or_reparse(path) or not path.is_dir():
                    raise MediaPoolContinuationError("Media Pool query storage rejects links, reparse points and non-directories")
            elif create:
                path.mkdir(mode=0o700)
            else:
                raise MediaPoolContinuationError("Media Pool query state is unavailable; start the search again")

    def _load(self, handle: str, *, allow_expired: bool = False) -> dict[str, Any]:
        self.validate_handle(handle)
        self._directory(create=False)
        path = self.root / f"{handle}.json"
        try:
            if path_is_link_or_reparse(path):
                raise MediaPoolContinuationError("Media Pool query record rejects links and reparse points")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as stream:
                metadata = os.fstat(stream.fileno())
                if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                        or metadata.st_size > self.MAX_RECORD_BYTES
                        or path_is_link_or_reparse(path, metadata=metadata)):
                    raise MediaPoolContinuationError("Media Pool query record is not one bounded regular file")
                payload = json.loads(stream.read(self.MAX_RECORD_BYTES + 1))
            fields = {"contract", "handle", "plan", "context", "expires_at", "sha256"}
            if not isinstance(payload, dict) or set(payload) != fields:
                raise ValueError("record fields changed")
            digest = payload.pop("sha256")
            expiry = payload["expires_at"]
            if (payload["contract"] != "waapi-skill.media-pool-query-plan/v1" or payload["handle"] != handle
                    or not isinstance(digest, str) or not hmac.compare_digest(canonical_sha256(payload), digest)
                    or type(expiry) not in (int, float) or not 0 < expiry <= time.time() + 900
                    or not isinstance(payload["plan"], dict) or not isinstance(payload["context"], dict)):
                raise ValueError("record binding changed")
            if not allow_expired or expiry > time.time():
                validate_media_pool_business_plan(payload["plan"])
            if not allow_expired and expiry <= time.time():
                raise MediaPoolContinuationError("Media Pool query expired; start the search again")
            return payload
        except (OSError, ValueError, TypeError) as exc:
            if isinstance(exc, MediaPoolContinuationError):
                raise
            raise MediaPoolContinuationError("Media Pool query record is missing, malformed or changed; start the search again") from exc

    def resolve(self, handle: str) -> dict[str, Any]:
        return self._load(handle)

    def retire(self, handle: str) -> None:
        self._load(handle, allow_expired=True)
        (self.root / f"{handle}.json").unlink()

    def issue(self, *, plan: Mapping[str, Any], context: Mapping[str, Any], issued: int) -> str:
        validate_media_pool_business_plan(plan)
        self._directory(create=True)
        paths = []
        for index, path in enumerate(self.root.iterdir()):
            if index >= self.MAX_RECORDS or path.suffix != ".json" or not self._HANDLE.fullmatch(path.stem):
                raise MediaPoolContinuationError("Media Pool query storage reached its bounded record ceiling or contains an unknown entry")
            paths.append(path)
        count, total_bytes = 0, 0
        for path in paths:
            record = self._load(path.stem, allow_expired=True)
            if record["expires_at"] <= time.time():
                path.unlink()
            else:
                count += 1
                total_bytes += path.stat().st_size
        handle = "mpq1-" + secrets.token_hex(16)
        body = {"contract": "waapi-skill.media-pool-query-plan/v1", "handle": handle,
                "plan": dict(plan), "context": dict(context), "expires_at": issued + 900}
        encoded = canonical_json_bytes({**body, "sha256": canonical_sha256(body)})
        if len(encoded) > self.MAX_RECORD_BYTES or count >= self.MAX_RECORDS or total_bytes + len(encoded) > self.MAX_TOTAL_BYTES:
            raise MediaPoolContinuationError("Media Pool query storage reached its bounded capacity; retry after expiry or narrow the search")
        path = self.root / f"{handle}.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return handle


@dataclass(frozen=True, slots=True)
class MediaPoolPage:
    issued: int
    offset: int
    step: int
    query_hash: str
    prefix_hash: str
    context_hash: str


def parse_media_pool_page(token: str) -> MediaPoolPage:
    if not isinstance(token, str) or len(token) > 512:
        raise MediaPoolContinuationError("Media Pool continuation exceeds its fixed token bound")
    try:
        version, stamp, start, size, query, prefix, context, digest = token.split(".")
        issued, offset, step = int(stamp), int(start), int(size)
        unsigned = token.rsplit(".", 1)[0]
        valid = (version == "mp1" and str(issued) == stamp and str(offset) == start and str(step) == size
                 and all(len(value) == 64 and all(char in "0123456789abcdef" for char in value) for value in (query, prefix, context, digest))
                 and hmac.compare_digest(canonical_sha256(unsigned), digest)
                 and 0 < offset < MAX_MEDIA_POOL_RESULTS and 1 <= step <= MAX_MEDIA_POOL_RESULTS
                 and issued <= time.time() <= issued + 900)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise MediaPoolContinuationError("Media Pool continuation is malformed or expired; start the bounded search again")
    return MediaPoolPage(issued, offset, step, query, prefix, context)


def _query_hash(request: Mapping[str, Any]) -> str:
    return canonical_sha256({
        "args": {key: value for key, value in request["args"].items() if key != "maxResults"},
        "options": request["options"],
        "result_plan": {key: value for key, value in request["result_plan"].items() if key != "candidate_limit"},
    })


def prepare_media_pool_page(request: Mapping[str, Any], *, token: str | None, context: Mapping[str, Any]) -> MediaPoolPage:
    query, binding = _query_hash(request), canonical_sha256(context)
    maximum = request["args"]["maxResults"]
    if token is None:
        return MediaPoolPage(int(time.time()), 0, maximum, query, "", binding)
    page = parse_media_pool_page(token)
    if (not hmac.compare_digest(page.query_hash, query) or not hmac.compare_digest(page.context_hash, binding)
            or maximum != min(MAX_MEDIA_POOL_RESULTS, page.offset + page.step)):
        raise MediaPoolContinuationError("Media Pool query, configuration, project, host session or expected prefix bound changed; start the search again")
    return page


def finish_media_pool_page(page: MediaPoolPage, *, rows: Sequence[Mapping[str, Any]], request: Mapping[str, Any],
                           normalized: Mapping[str, Any], context_available: bool) -> tuple[dict[str, Any], str | None, int | None]:
    if page.offset and (len(rows) < page.offset or not hmac.compare_digest(canonical_sha256(rows[:page.offset]), page.prefix_hash)):
        raise MediaPoolContinuationError("The preceding Media Pool prefix changed or reordered; no later rows were certified")
    result = dict(normalized)
    plan = request["result_plan"]
    replacement = bool(plan.get("exact_name_contains") is not None or plan.get("sort_bindings") or plan.get("final_limit") is not None)
    if not replacement:
        result["items"] = list(result["items"])[page.offset:]
        result["returned_count"] = len(result["items"])
    if not page.offset and result["complete"]:
        return result, None, None
    boundary = not result["complete"] and len(rows) >= MAX_MEDIA_POOL_RESULTS
    result["page"] = {
        "mode": "larger_bounded_prefix_reread", "native_offset_supported": False,
        "presentation": "replace_previous_prefix" if replacement else "append_verified_later_rows",
        "offset": page.offset, "prefix_count": len(rows), "preceding_prefix_verified": bool(page.offset),
        "resource_boundary_reached": boundary, "maximum_prefix_count": MAX_MEDIA_POOL_RESULTS,
        "host_session_bound": context_available,
    }
    expired = time.time() > page.issued + 900
    unavailable = "maximum_supported_prefix_reached" if boundary else "host_session_identity_unavailable" if not context_available else "continuation_expired" if expired else None
    if unavailable is not None and not result["complete"]:
        result["page"]["continuation_unavailable_reason"] = unavailable
    if result["complete"] or unavailable is not None:
        return result, None, None
    unsigned = f"mp1.{page.issued}.{len(rows)}.{page.step}.{page.query_hash}.{canonical_sha256(rows)}.{page.context_hash}"
    token = unsigned + "." + canonical_sha256(unsigned)
    return result, token, min(MAX_MEDIA_POOL_RESULTS, len(rows) + page.step)


def media_pool_continuation_argv(plan: Mapping[str, Any], *, token: str, maximum: int) -> list[str]:
    """Serialize only the existing closed business declaration, never native args."""
    argv = ["core-call", "ak.wwise.core.mediaPool.get", "--max-results", str(maximum)]
    scalar = {"search_text": "--search-text", "exact_name_contains": "--exact-name-contains", "final_limit": "--final-limit"}
    repeated = {"database_scopes": "--database-scope", "database_ids": "--database-id", "audio_descriptions": "--audio-description",
                "audio_similarity_files": "--audio-similarity-file", "return_field_meanings": "--include-field"}
    tuples = {"text_filters": "--text-filter", "number_filters": "--number-filter", "weighted_audio_descriptions": "--weighted-audio-description",
              "weighted_audio_similarity_files": "--weighted-audio-similarity-file", "sort_rules": "--sort-by"}
    for field, flag in scalar.items():
        if field in plan:
            argv.extend([flag, str(plan[field])])
    for field, flag in repeated.items():
        for value in plan.get(field, ()):
            argv.extend([flag, str(value)])
    for field, flag in tuples.items():
        for values in plan.get(field, ()):
            argv.extend([flag, *map(str, values)])
    return [*argv, "--media-page", token]
