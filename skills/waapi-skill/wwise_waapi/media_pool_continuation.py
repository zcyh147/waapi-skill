"""Content-bound continuations for a native search with no offset argument.

A continuation explicitly asks for a larger bounded prefix. It certifies the
entire preceding native prefix before exposing later rows. Tokens carry no
write authority and never authorize a different query or host session.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import time
from typing import Any, Mapping, Sequence

from .canonical import canonical_sha256
from .media_build_business import MAX_MEDIA_POOL_RESULTS


class MediaPoolContinuationError(ValueError):
    code = "MEDIA_POOL_CONTINUATION_CHANGED"


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
