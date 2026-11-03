"""Lossless bounded delivery of one exact bounded object-query observation.

Plans retain the original projection and optional origin packet diagnostics.
Pages deliver that historical observation within the same attested context.
"""
from __future__ import annotations
import json
import re
from typing import Any, Callable, Mapping
from .canonical import canonical_json_bytes, canonical_sha256
from .media_pool_continuation import MediaPoolQueryStore, MediaPoolContinuationError
from .metadata_detail import detail_entries


class QueryResultPageError(ValueError):
    code = "QUERY_RESULT_CONTINUATION_CHANGED"


class QueryResultProjectionLimitError(QueryResultPageError):
    code = "QUERY_RESULT_PROJECTION_LIMIT_EXCEEDED"


def _has_oversized_pointer(value: Any) -> bool:
    # Count escaped pointer bytes without first copying a giant native key into
    # every descendant path. Use document fragments when a path cannot fit.
    pending = [(value, 0)]
    while pending:
        item, prefix_bytes = pending.pop()
        if isinstance(item, Mapping):
            children = ((key, child) for key, child in item.items())
        elif isinstance(item, list):
            children = ((str(index), child) for index, child in enumerate(item))
        else:
            continue
        for key, child in children:
            size = prefix_bytes + 1 + len(key.encode("utf-8")) + key.count("~") + key.count("/")
            if size > 2048:
                return True
            pending.append((child, size))
    return False


MAX_QUERY_REQUEST_BYTES = 256 * 1024
MAX_QUERY_BASE_RECORD_BYTES = MediaPoolQueryStore.MAX_RECORD_BYTES
MAX_QUERY_ORIGIN_EVIDENCE_BYTES = MediaPoolQueryStore.MAX_TOTAL_BYTES - MAX_QUERY_BASE_RECORD_BYTES


def validate_plan(plan: Mapping[str, Any]) -> None:
    argv = plan.get("argv") if isinstance(plan, dict) else None
    if (not isinstance(plan, dict) or not {"argv"} <= set(plan) <= {"argv", "origin_related_read_evidence", "projection"} or not isinstance(argv, list) or not argv
            or "query-object" not in argv or len(argv) > 2048
            or not all(isinstance(item, str) for item in argv)
            or any(item in {"--result-query", "--result-page"} for item in argv)
            or len(canonical_json_bytes({"argv": argv})) > MAX_QUERY_REQUEST_BYTES):
        raise MediaPoolContinuationError("Stored query is not a bounded original public business request")
    if "origin_related_read_evidence" in plan:
        evidence = plan["origin_related_read_evidence"]
        if (not isinstance(evidence, list) or any(not isinstance(read, dict)
                or set(read) != {"api", "args", "options", "result_sha256", "call"}
                or not isinstance(read["api"], str) or not isinstance(read["args"], dict)
                or not isinstance(read["options"], dict) or not isinstance(read["call"], dict)
                or not isinstance(read["result_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", read["result_sha256"])
                for read in evidence)
                or len(canonical_json_bytes(evidence)) > MAX_QUERY_ORIGIN_EVIDENCE_BYTES):
            raise MediaPoolContinuationError("Origin query evidence is malformed or exceeds its separate bounded storage allowance")

    if "projection" in plan:
        projection = plan["projection"]
        payload = projection.get("payload") if isinstance(projection, dict) else None
        if (not isinstance(projection, dict) or set(projection) != {"detail", "payload", "native_result_sha256"}
                or type(projection["detail"]) is not bool
                or not isinstance(projection["native_result_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", projection["native_result_sha256"])
                or not isinstance(payload, dict) or payload.get("ok") is not True
                or not isinstance(payload.get("objects"), list)
                or not all(isinstance(row, dict) for row in payload["objects"])):
            raise MediaPoolContinuationError("Stored query projection is malformed")


class ObjectQueryPlanStore(MediaPoolQueryStore):
    DIRECTORY = "object-query-read-plans-v1"
    CONTRACT = "waapi-skill.object-query-read-plan/v1"
    PREFIX = "oq1-"
    _HANDLE = re.compile(r"^oq1-[0-9a-f]{32}$")
    validate_plan = staticmethod(validate_plan)
    # Keep the original request/context allowance independent of diagnostic data.
    # Origin data shares the existing total store quota, not the argv ceiling.
    MAX_RECORD_BYTES = MediaPoolQueryStore.MAX_TOTAL_BYTES

    def _validate_base_record(self, *, plan, context, expires_at):
        if not isinstance(plan, dict) or "argv" not in plan:
            raise MediaPoolContinuationError("Query plan no longer contains its original request")
        base = {"contract": self.CONTRACT, "handle": self.PREFIX + "0" * 32,
            "plan": {"argv": plan["argv"]}, "context": context, "expires_at": expires_at, "sha256": "0" * 64}
        if len(canonical_json_bytes(base)) > MAX_QUERY_BASE_RECORD_BYTES:
            raise MediaPoolContinuationError("Query request/context exceeds its original bounded record allowance")

    def _load(self, handle, *, allow_expired=False):
        try:
            record = super()._load(handle, allow_expired=allow_expired)
            self._validate_base_record(plan=record["plan"], context=record["context"], expires_at=record["expires_at"])
            return record
        except MediaPoolContinuationError as exc:
            raise QueryResultPageError(str(exc)) from exc

    def issue(self, *, plan, context, issued):
        try:
            self.validate_plan(plan)
            self._validate_base_record(plan=plan, context=context, expires_at=issued + 900)
            return super().issue(plan=plan, context=context, issued=issued)
        except (MediaPoolContinuationError, QueryResultPageError) as exc:
            raise QueryResultProjectionLimitError(f"Query plan/evidence storage is unavailable or exceeds its bounded capacity: {exc}") from exc


def page_token(offset: int, seal: str) -> str:
    return f"oqp2.{offset}.{canonical_sha256([offset, seal])}"


def parse_offset(token: str | None, seal: str) -> int:
    if token is None:
        return 0
    try:
        _, position, _ = token.split(".")
        offset = int(position)
        valid = (0 < offset < 1024 * 1024 and token == page_token(offset, seal))
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise QueryResultPageError("Query result page is invalid or does not match the retained observation; restart the original read")
    return offset


def build_page(payload: Mapping[str, Any], *, offset: int, seal: str, native_result_sha256: str,
               expires_at: int | float,
               next_command: Callable[[str], Mapping[str, Any]] | None, maximum_entries: int = 32) -> dict[str, Any]:
    observation = {"objects": payload["objects"]}
    if "native_observation" in payload:
        observation["native_observation"] = payload["native_observation"]
    if payload.get("detail_fragment_required"):
        observation["semantic_preview"] = payload["semantic_preview"]
    if payload.get("scope_fragment_required"):
        observation["related_scope_binding"] = payload["related_scope_binding"]
    if payload.get("evidence_fragment_required"):
        observation["related_read_evidence"] = payload["related_read_evidence"]
    encoded_observation = canonical_json_bytes(observation)
    document_fragments = _has_oversized_pointer(observation)
    # Canonical traversal makes entry positions stable when only native object
    # member order changes; arrays retain their exact native order.
    entries = detail_entries(encoded_observation.decode("utf-8") if document_fragments
                             else json.loads(encoded_observation))
    if not 0 <= offset < len(entries):
        raise QueryResultPageError("Query result page is outside the exact observation")
    # Identity atoms remain exact or explicitly omitted. No previews can be
    # mistaken for a native identity or certify a later selected mutation.
    headers = []
    for row in payload["objects"][:4]:
        header = {key: row[key] for key in ("id", "name", "type", "path")
                  if key in row and len(canonical_json_bytes(row[key])) <= 512}
        omitted = [key for key in row if key not in header]
        if omitted:
            header["projection_omitted_fields"] = omitted
        headers.append(header)
    end = min(len(entries), offset + maximum_entries)
    while True:
        complete = end == len(entries)
        result = {"objects": headers, "entries": entries[offset:end],
            "entries_encoding": "json-document-fragments" if document_fragments else "json-pointer-entries",
            **({"entry_reconstruction": "Concatenate value strings in offset order, then read the single JSON document; native field names and values remain exact"}
               if document_fragments else {}),
            "projection_complete": complete, "identity_header_row_count": len(headers),
            "identity_headers_complete": (len(headers) == len(payload["objects"])
                and all(all(isinstance(header.get(key), str) for key in ("id", "name", "type", "path"))
                        for header in headers)),
            "query_exhaustion": "not_certified_by_projection_completion",
            "page": {"offset": offset, "next_offset": end, "total_positions": len(entries),
                "position_unit": ("canonical JSON document string fragments with exact character offsets" if document_fragments
                    else "lossless JSON entries with exact pointers and string offsets"),
                "native_read": "retained_historical_observation",
                "observed_at_unix_seconds": expires_at - 900,
                "native_result_sha256": native_result_sha256,
                "expires_at": expires_at, "mutation_authority": False}}
        if not complete and next_command is not None:
            result["next_command"] = next_command(page_token(end, seal))
        if len(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")) <= 20 * 1024:
            return result
        if end <= offset + 1:
            raise QueryResultProjectionLimitError("One query entry or identity inventory exceeds the bounded projection; refine the original read")
        end = offset + max(1, (end - offset) // 2)
