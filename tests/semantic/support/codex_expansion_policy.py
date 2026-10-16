"""Outcome-oriented admission primitives for the new expansion profile only.

This module does not launch commands or accept Agent-authored authorizations.
The authenticated Broker must call it with trusted Preview-store observations
and runner-owned turn intent. Existing exact-step profiles do not use it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Sequence

from wwise_waapi.builders.query import MAX_QUERY_TAKE


POLICY_CONTRACT = "waapi-skill.integration-expansion-outcome-policy/v1"
_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_POLICIES = frozenset({"read_only", "ask_before_changes", "allow_changes"})
_CURVE_ROLES = frozenset({"volume-dry", "game-defined-aux-send-volume",
                          "user-defined-aux-send-volume", "low-pass-filter",
                          "high-pass-filter", "spread", "focus"})
_EVENT_ACTIONS_RELATIONSHIP = "event-actions"
# The Gateway query-schema owns this fixed preset bound in every supported
# lane. The focused broker regression compares this value with that public
# schema so policy admission fails closed if the packaged contract changes.
_EVENT_ACTIONS_FIXED_MAX_RESULTS = 100
_EVENT_ACTIONS_AUTOMATIC_OUTPUTS = frozenset({"action-type", "target"})


class ExpansionPolicyError(ValueError):
    """A proposed action cannot be proven inside the sealed business scope."""


def is_public_query_timeout_failure(payload: Mapping[str, object]) -> bool:
    """Recognize only the fixed public object-query deadline failure envelope.

    This receipt proves an authenticated failed read, never object data or a
    safe infrastructure checkpoint. Unknown nested dispatch errors stay closed.
    The caller separately enforces the admitted command and receipt byte cap.
    """
    call = payload.get("call")
    if (payload.get("contract") != "waapi-skill.gateway-result/v1"
            or payload.get("command") != "query-object"
            or payload.get("ok") is not False or payload.get("status") != "error"
            or "error_code" in payload
            or any(key not in payload or payload[key] is not None
                   for key in ("count", "objects", "agent_result"))
            or not isinstance(call, Mapping)):
        return False
    if (call.get("api") != "ak.wwise.core.object.get"
            or call.get("item_type") != "function" or call.get("ok") is not False
            or call.get("error_code") != "TIMEOUT" or call.get("result") is not None
            or call.get("version") not in {"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"}
            or call.get("version") != payload.get("detected_version")
            or not isinstance(call.get("message"), str) or not call["message"]
            or not isinstance(call.get("evidence_path"), str) or not call["evidence_path"]):
        return False
    details = call.get("details")
    if (not isinstance(details, Mapping)
            or details.get("provenance") != "waapi-skill.gateway-deadline/v1"
            or details.get("phase") != "WAAPI call ak.wwise.core.object.get"
            or details.get("timeout_mode") != "finite"
            or details.get("deadline_exhausted") is not True
            or type(details.get("cleanup_pending")) is not bool
            or details.get("abort_requested") is not True):
        return False
    for key in ("configured_timeout_seconds", "elapsed_seconds", "operation_timeout_seconds"):
        number = details.get(key)
        if type(number) not in (int, float) or not math.isfinite(number) or number <= 0:
            return False
    cleanup = payload.get("details")
    if cleanup is not None:
        if not isinstance(cleanup, Mapping):
            return False
        failure = cleanup.get("cleanup_failure")
        if (not isinstance(failure, Mapping) or failure.get("error_code") != "TIMEOUT"
                or failure.get("details") != details
                or not isinstance(failure.get("message"), str) or not failure["message"]):
            return False
    elif details["cleanup_pending"]:
        return False
    return True


def is_public_recoverable_query_failure(payload: Mapping[str, object]) -> bool:
    """Current recovery receipts may refine a read; old verdicts stay unchanged."""
    recovery, call = payload.get("recovery"), payload.get("call")
    if not isinstance(recovery, Mapping) or not isinstance(call, Mapping):
        return False
    required = {
        "contract": "waapi-skill.recovery/v1", "stage": "read_failure",
        "project_write_outcome": "no_project_write_in_this_invocation",
        "read_only_continuation_allowed": True, "cleanup_complete": True,
        "additional_read_permission_required": False,
        "scope": "existing_authorized_task_only", "original_write_replay_allowed": False,
    }
    if any(recovery.get(key) != value or type(recovery.get(key)) is not type(value)
           for key, value in required.items()):
        return False
    if recovery.get("modification_policy") not in _POLICIES:
        return False
    policy = recovery["modification_policy"]
    if (recovery.get("next_change") != {"read_only": "blocked", "ask_before_changes": "preview_then_explicit_confirmation",
                                       "allow_changes": "preview_then_policy_authorization"}[policy]
            or type(recovery.get("max_reconnect_attempts")) is not int or recovery["max_reconnect_attempts"] != 1
            or recovery.get("service_start_requires_existing_task_authorization") is not True
            or not isinstance(recovery.get("actions"), list)
            or recovery["actions"] != ["refine_read", "page_discovery", "inspect_configuration", "reconnect_once"]):
        return False
    if (payload.get("contract") != "waapi-skill.gateway-result/v1"
            or payload.get("command") != "query-object" or payload.get("ok") is not False
            or payload.get("status") != "error" or payload.get("executed") is True
            or any(key not in payload or payload[key] is not None for key in ("count", "objects", "agent_result"))
            or call.get("api") != "ak.wwise.core.object.get" or call.get("item_type") != "function"
            or call.get("ok") is not False or call.get("result") is not None
            or not isinstance(call.get("error_code"), str) or not call["error_code"]
            or call.get("version") not in {"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"}
            or call.get("version") != payload.get("detected_version")):
        return False
    for details in (payload.get("details"), call.get("details")):
        if isinstance(details, Mapping) and (details.get("cleanup_failure") is not None or details.get("cleanup_pending") is True):
            return False
    return True


def canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _digest(value: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ExpansionPolicyError("expected an exact SHA-256 digest")
    return value


@dataclass(frozen=True)
class ExpansionReadScope:
    """Closed read obligations sealed before the Agent sees its prompt."""

    object_ids: frozenset[str]
    operations: frozenset[str]
    includes: frozenset[str] = frozenset()
    relationship_sources: frozenset[str] = frozenset()
    max_rows: int = 64
    max_calls: int = 48
    max_result_bytes: int = 131_072
    fields: frozenset[str] = frozenset()
    curve_roles: frozenset[str] = frozenset()
    platforms: frozenset[str] = frozenset()
    owned_project_reads: bool = False

    def __post_init__(self) -> None:
        if type(self.owned_project_reads) is not bool:
            raise ExpansionPolicyError("owned-project read scope flag must be boolean")
        if not self.object_ids or any(not _GUID.fullmatch(item) for item in self.object_ids):
            raise ExpansionPolicyError("read scope requires canonical object GUIDs")
        if not self.relationship_sources.issubset(self.object_ids):
            raise ExpansionPolicyError("relationship roots must be in the sealed scope")
        if not self.operations or any(not isinstance(item, str) or not item for item in self.operations):
            raise ExpansionPolicyError("read scope requires closed operation names")
        if not self.curve_roles.issubset(_CURVE_ROLES):
            raise ExpansionPolicyError("unknown public attenuation curve role")
        row_ceiling = MAX_QUERY_TAKE if self.owned_project_reads is True else 64
        for value, ceiling in ((self.max_rows, row_ceiling), (self.max_calls, 128),
                               (self.max_result_bytes, 1_048_576)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ExpansionPolicyError("read scope exceeds expansion ceilings")

    @property
    def digest(self) -> str:
        return canonical_digest({
            "contract": POLICY_CONTRACT,
            "object_ids": sorted(self.object_ids), "operations": sorted(self.operations),
            "includes": sorted(self.includes),
            "fields": sorted(self.fields),
            "curve_roles": sorted(self.curve_roles), "platforms": sorted(self.platforms),
            "relationship_sources": sorted(self.relationship_sources),
            "max_rows": self.max_rows, "max_calls": self.max_calls,
            "max_result_bytes": self.max_result_bytes,
            "owned_project_reads": self.owned_project_reads,
        })


class BoundedExpansionReads:
    """Admit bounded public reads without granting a native-call escape hatch.

    The expansion runner may attest the whole disposable project for reads;
    that mode uses the real public parser and Gateway-owned advanced compiler.
    The narrower exact-ID mode remains available for focused policy tests.
    Failed attempts consume capacity too. A pending receipt prevents overlap.
    """

    def __init__(self, scope: ExpansionReadScope, *, public_parser=None) -> None:
        self.scope = scope
        self.calls = 0
        self._pending: tuple[str, ...] | None = None
        self.receipts: list[tuple[tuple[str, ...], str]] = []
        self.failed_receipts: list[tuple[tuple[str, ...], str]] = []
        self.public_parser = public_parser
        self.advanced_disclosed = False

    def _admit_owned_project(self, argv: tuple[str, ...]) -> tuple[str, ...]:
        # The parent runner attests one disposable project and fixes its
        # endpoint. Reading it never adds mutation identities to the case.
        if self.public_parser is None:
            raise ExpansionPolicyError("owned-project reads require the public parser")
        args = self.public_parser(argv)
        if args.command not in {"status", "operations", "query-schema", "operation-schema",
                                "request-schema", "query-object", "metadata"}:
            raise ExpansionPolicyError("not a public read command")
        if args.command == "query-object":
            relationships = tuple(getattr(args, "relationships", ()) or ())
            limit = getattr(args, "max_results", None)
            exact = bool(getattr(args, "object_id", None) or getattr(args, "path_segments", None))
            if _EVENT_ACTIONS_RELATIONSHIP in relationships:
                if relationships != (_EVENT_ACTIONS_RELATIONSHIP,):
                    raise ExpansionPolicyError("event-actions preset cannot be composed with another relationship")
                source_id = getattr(args, "object_id", None)
                if (not isinstance(source_id, str) or not _GUID.fullmatch(source_id)
                        or source_id.casefold() not in {item.casefold() for item in self.scope.relationship_sources}):
                    raise ExpansionPolicyError("event-actions source must be a sealed exact Event identity")
                if limit is not None and (type(limit) is not int or limit != _EVENT_ACTIONS_FIXED_MAX_RESULTS):
                    raise ExpansionPolicyError("event-actions uses its fixed Gateway result bound")
                for flag in ("--max-results", "--exact-id", "--relationship"):
                    if sum(item == flag or item.startswith(flag + "=") for item in argv) > 1:
                        raise ExpansionPolicyError("event-actions selectors and fixed bound must be unique")
                if (getattr(args, "business_view", None) is not None
                        or getattr(args, "business_predicates", None)
                        or getattr(args, "custom_kind_meaning", None) is not None
                        or getattr(args, "semantic_kind", None) is not None
                        or getattr(args, "search", None) is not None
                        or getattr(args, "query", None) is not None
                        or getattr(args, "advanced_waql", None) is not None
                        or getattr(args, "match_original_file_paths", None)):
                    raise ExpansionPolicyError("event-actions requires its exact uncomposed public query")
                includes = tuple(getattr(args, "business_outputs", ()) or ())
                custom_fields = tuple(getattr(args, "custom_field_meanings", ()) or ())
                if (len(includes) != len(set(includes))
                        or not set(includes).issubset(self.scope.includes)
                        or not _EVENT_ACTIONS_AUTOMATIC_OUTPUTS.union(includes).issubset(self.scope.includes)
                        or custom_fields):
                    raise ExpansionPolicyError("event-actions projection exceeds the sealed read scope")
            elif relationships:
                exact = False
            if _EVENT_ACTIONS_RELATIONSHIP not in relationships and (
                    limit is not None and (type(limit) is not int or not 1 <= limit <= self.scope.max_rows)
                    or limit is None and not exact):
                raise ExpansionPolicyError("project query requires a bounded public source")
            if getattr(args, "advanced_waql", None) and not self.advanced_disclosed:
                raise ExpansionPolicyError("advanced contract must first be disclosed by query-schema")
        self._pending = argv
        return argv

    def admit(self, arguments: Sequence[str]) -> tuple[str, ...]:
        if self._pending is not None or self.calls >= self.scope.max_calls:
            raise ExpansionPolicyError("read capacity exhausted or receipt still pending")
        self.calls += 1
        argv = tuple(arguments)
        if not argv or any(not isinstance(item, str) for item in argv):
            raise ExpansionPolicyError("read argv must be strings")
        if self.scope.owned_project_reads:
            return self._admit_owned_project(argv)
        if argv == ("operations",) or argv == ("query-schema",):
            self._pending = argv
            return argv
        if (len(argv) == 2 and argv[0] in {"operation-schema", "request-schema"}
                and argv[1] in self.scope.operations):
            self._pending = argv
            return argv
        if argv[:2] == ("metadata", "attenuation"):
            tail = argv[2:]
            if len(tail) not in {4, 6}:
                raise ExpansionPolicyError("attenuation read requires exact closed scope")
            pairs = dict(zip(tail[::2], tail[1::2], strict=True))
            if (len(pairs) * 2 != len(tail)
                    or set(pairs) - {"--exact-id", "--curve-role", "--platform"}
                    or pairs.get("--exact-id") not in self.scope.object_ids
                    or pairs.get("--curve-role") not in self.scope.curve_roles
                    or ("--platform" in pairs and pairs["--platform"] not in self.scope.platforms)):
                raise ExpansionPolicyError("attenuation read exceeds the sealed field/platform scope")
            self._pending = argv
            return argv
        if argv[0] != "query-object":
            raise ExpansionPolicyError("command is outside the closed read surface")
        pairs = argv[1:]
        if len(pairs) % 2:
            raise ExpansionPolicyError("query options require exact values")
        values: dict[str, list[str]] = {}
        for flag, value in zip(pairs[::2], pairs[1::2], strict=True):
            if flag not in {"--exact-id", "--relationship", "--include", "--include-field", "--max-results"}:
                raise ExpansionPolicyError("query option is outside the read scope")
            values.setdefault(flag, []).append(value)
        for flag in ("--exact-id", "--relationship", "--max-results"):
            if len(values.get(flag, [])) > 1:
                raise ExpansionPolicyError("duplicate query selector or ceiling")
        ids, limits = values.get("--exact-id", []), values.get("--max-results", [])
        if len(ids) != 1 or ids[0] not in self.scope.object_ids:
            raise ExpansionPolicyError("query requires one sealed GUID")
        # Exact-ID has at most one object, irrespective of the Gateway's
        # default row ceiling. Relationship reads need the explicit scope cap.
        if not limits and values.get("--relationship"):
            raise ExpansionPolicyError("relationship read needs an explicit scope ceiling")
        if limits and (not limits[0].isascii() or not limits[0].isdigit() or not 1 <= int(limits[0]) <= self.scope.max_rows):
            raise ExpansionPolicyError("query row limit exceeds scope")
        relationship = values.get("--relationship", [])
        if relationship and (relationship != ["children"] or ids[0] not in self.scope.relationship_sources):
            raise ExpansionPolicyError("relationship is not authorized for this source")
        includes = values.get("--include", [])
        if len(includes) != len(set(includes)) or not set(includes).issubset(self.scope.includes):
            raise ExpansionPolicyError("projection is outside the sealed read scope")
        fields = values.get("--include-field", [])
        if len(fields) != len(set(fields)) or not set(fields).issubset(self.scope.fields):
            raise ExpansionPolicyError("field projection is outside the sealed read scope")
        self._pending = argv
        return argv

    def observe(self, payload: Mapping[str, object]) -> bool:
        if self._pending is None:
            raise ExpansionPolicyError("no pending read receipt")
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(serialized) > self.scope.max_result_bytes:
            raise ExpansionPolicyError("read receipt exceeds byte ceiling")
        if payload.get("command") != self._pending[0]:
            raise ExpansionPolicyError("read receipt does not match the admitted command")
        if (is_public_query_timeout_failure(payload) or is_public_recoverable_query_failure(payload)
                or (payload.get("ok") is False and isinstance(payload.get("error_code"), str))
                or (payload.get("ok") is True and payload.get("status") == "needs_clarification")):
            # Failed reads never prove business state. Input rejection may be
            # repaired; only a current cleanup-complete recovery receipt can
            # keep a failed dispatched read open for bounded refinement.
            self.failed_receipts.append((self._pending, canonical_digest(payload)))
            self._pending = None
            return False
        if payload.get("ok") is not True:
            raise ExpansionPolicyError("read receipt has no definite outcome")
        if self._pending[0] == "query-object":
            rows = payload.get("objects")
            if self.scope.owned_project_reads:
                query_args = self.public_parser(self._pending)
                relationships = tuple(getattr(query_args, "relationships", ()) or ())
                explicit_limit = getattr(query_args, "max_results", None) is not None
                if relationships == (_EVENT_ACTIONS_RELATIONSHIP,):
                    requested_limit = _EVENT_ACTIONS_FIXED_MAX_RESULTS
                else:
                    requested_limit = getattr(query_args, "max_results", None) or 1
            else:
                requested_limit = (int(self._pending[self._pending.index("--max-results") + 1])
                                   if "--max-results" in self._pending else 1)
                explicit_limit = "--max-results" in self._pending
            if (not isinstance(rows, list) or len(rows) > requested_limit
                    or len(rows) > self.scope.max_rows
                    or type(payload.get("count")) is not int or payload["count"] != len(rows)):
                raise ExpansionPolicyError("query rows exceed scope")
            bound = payload.get("query_bound")
            exact = "--relationship" not in self._pending and ("--exact-id" in self._pending or "--path-segment" in self._pending)
            # The real compact query envelope has query_bound/count, not
            # response_integrity (that field belongs to other Gateway lanes).
            expected_bound = ({"mode": "gateway-appended-take", "value": requested_limit}
                              if "--advanced-waql" in self._pending else
                              {"mode": "take", "value": requested_limit}
                              if explicit_limit or self.scope.owned_project_reads
                              and relationships == (_EVENT_ACTIONS_RELATIONSHIP,)
                              else {"mode": "exact-object"})
            if bound != expected_bound:
                raise ExpansionPolicyError("query completeness is not proven")
            if payload.get("limit_reached") is True or not exact and len(rows) >= requested_limit:
                if not self.scope.owned_project_reads:
                    raise ExpansionPolicyError("relationship read reached its ceiling")
                self.failed_receipts.append((self._pending, canonical_digest(payload)))
                self._pending = None
                return False
            ids = [row.get("id") if isinstance(row, Mapping) else None for row in rows]
            if any(not isinstance(key, str) or not _GUID.fullmatch(key) for key in ids) or len(ids) != len(set(ids)):
                raise ExpansionPolicyError("query identities are malformed or duplicate")
            source_id = (self._pending[self._pending.index("--exact-id") + 1]
                         if "--exact-id" in self._pending else None)
            if exact and (len(rows) > 1 or source_id is not None and any(key.upper() != source_id.upper() for key in ids)):
                raise ExpansionPolicyError("exact read returned another identity")
        if self._pending == ("query-schema", "--advanced"):
            self.advanced_disclosed = True
        self.receipts.append((self._pending, canonical_digest(payload)))
        self._pending = None
        return True


@dataclass(frozen=True)
class ExecutionPermit:
    transaction_id: str
    artifact_sha256: str
    authorization_nonce: str
    preview_turn: int
    authorized_turn: int


class ExpansionTransaction:
    """Runner-owned authorization plus at-most-once execution reservation.

    This complements, never replaces, durable Gateway authorization. The
    integration adapter must also compare the actual Gateway artifact/store
    and authorization receipt before launching execute. ``approve_preview``
    is a trusted independent fixture check, not an Agent-supplied predicate.
    """

    def __init__(self, *, policy: str, request_prompt_sha256: str,
                 required_assertions: frozenset[str],
                 approve_preview: Callable[[Mapping[str, object]], bool],
                 accepted_verification_states: frozenset[str] = frozenset({"verified"})) -> None:
        if policy not in _POLICIES or not required_assertions:
            raise ExpansionPolicyError("invalid modification policy or empty oracle obligations")
        self.policy = policy
        self.prompt_sha256 = _digest(request_prompt_sha256)
        self.required_assertions = required_assertions
        if (not accepted_verification_states
                or not accepted_verification_states.issubset({"verified", "result_schema_checked"})):
            raise ExpansionPolicyError("unrecognized Gateway verification boundary")
        self.accepted_verification_states = accepted_verification_states
        self.gateway_verification_state: str | None = None
        self.approve_preview = approve_preview
        self.state = "unprepared"
        self._permit: ExecutionPermit | None = None
        self._turn = 0

    def begin_turn(self, turn: int) -> None:
        if type(turn) is not int or turn != self._turn + 1:
            raise ExpansionPolicyError("turn sequence must be runner-owned and contiguous")
        self._turn = turn

    def seal_preview(self, *, transaction_id: str, artifact: Mapping[str, object],
                     artifact_sha256: str, before_sha256: str, after_sha256: str) -> None:
        if self.policy == "read_only" or self.state != "unprepared" or self._turn < 1:
            raise ExpansionPolicyError("this policy/state cannot admit a mutation Preview")
        if not isinstance(transaction_id, str) or not transaction_id.startswith("tx1-"):
            raise ExpansionPolicyError("invalid transaction identity")
        if (_digest(before_sha256) != _digest(after_sha256)
                or _digest(artifact_sha256) != canonical_digest(artifact)
                or self.approve_preview(artifact) is not True):
            raise ExpansionPolicyError("Preview changed state or failed independent effect approval")
        self._permit = ExecutionPermit(transaction_id, artifact_sha256, secrets.token_hex(32), self._turn, 0)
        self.state = "previewed"

    def authorize(self, *, turn_prompt_sha256: str, explicit_intent: str) -> ExecutionPermit:
        if self.state != "previewed" or self._permit is None:
            raise ExpansionPolicyError("authorization requires the current immutable Preview")
        _digest(turn_prompt_sha256)
        if self.policy == "allow_changes":
            valid = (explicit_intent == "perform_changes" and self._turn == 1
                     and turn_prompt_sha256 == self.prompt_sha256)
        else:
            valid = (self.policy == "ask_before_changes" and explicit_intent == "confirm_current_preview"
                     and self._turn > self._permit.preview_turn
                     and turn_prompt_sha256 != self.prompt_sha256)
        if not valid:
            raise ExpansionPolicyError("configuration or an earlier turn is not explicit authorization")
        self._permit = ExecutionPermit(self._permit.transaction_id, self._permit.artifact_sha256,
                                       self._permit.authorization_nonce, self._permit.preview_turn, self._turn)
        self.state = "authorized"
        return self._permit

    def reserve_execute(self, permit: ExecutionPermit, *, live_artifact_sha256: str,
                        gateway_authorization_bound: bool) -> None:
        if (self.state != "authorized" or permit != self._permit
                or gateway_authorization_bound is not True
                or _digest(live_artifact_sha256) != permit.artifact_sha256):
            raise ExpansionPolicyError("execute lacks exact artifact and dual authorization binding")
        # Consume before dispatch: an exception/timeout can never authorize retry.
        self.state = "execution_reserved"

    def observe_execution(self, *, transaction_id: str, artifact_sha256: str,
                          completed: bool, terminal_indeterminate: bool = False) -> None:
        if self.state != "execution_reserved" or self._permit is None:
            raise ExpansionPolicyError("execution receipt has no reserved call")
        self.state = "indeterminate"
        if (transaction_id != self._permit.transaction_id
                or artifact_sha256 != self._permit.artifact_sha256
                or (completed is not True and terminal_indeterminate is not True)):
            raise ExpansionPolicyError("execution outcome is ambiguous or misbound; do not retry")
        if not terminal_indeterminate:
            self.state = "executed"

    def verify(self, *, transaction_id: str, artifact_sha256: str,
               assertions: Mapping[str, bool], gateway_verification_state: str) -> None:
        if (self.state != "executed" or self._permit is None
                or transaction_id != self._permit.transaction_id
                or artifact_sha256 != self._permit.artifact_sha256
                or gateway_verification_state not in self.accepted_verification_states
                or set(assertions) != self.required_assertions
                or any(value is not True for value in assertions.values())):
            raise ExpansionPolicyError("verification lacks complete independent business evidence")
        self.gateway_verification_state = gateway_verification_state
        self.state = "verified"

    def extend_read_scope(self, gate: BoundedExpansionReads, *, transaction_id: str,
                          artifact_sha256: str, execution_rows: Sequence[Mapping[str, object]],
                          approved_paths: frozenset[str]) -> None:
        """Bind newly created identities to the approved effect after execution.

        Only the runner calls this, using actual execution rows and paths from
        its independently approved Preview. No Agent command can extend scope.
        Extra/missing paths or duplicate GUIDs are rejected atomically.
        """
        if (self.state != "executed" or self._permit is None
                or transaction_id != self._permit.transaction_id
                or artifact_sha256 != self._permit.artifact_sha256
                or gate._pending is not None or not 1 <= len(execution_rows) <= 64
                or not approved_paths):
            raise ExpansionPolicyError("scope extension lacks a bound execution receipt")
        ids: list[str] = []
        paths: list[str] = []
        for row in execution_rows:
            object_id, path = row.get("id"), row.get("path")
            if (not isinstance(object_id, str) or not _GUID.fullmatch(object_id)
                    or not isinstance(path, str) or path not in approved_paths):
                raise ExpansionPolicyError("execution identity is outside the approved Preview paths")
            ids.append(object_id)
            paths.append(path)
        if (len({item.upper() for item in ids}) != len(ids)
                or len(set(paths)) != len(paths) or set(paths) != approved_paths):
            raise ExpansionPolicyError("execution identities do not exactly cover the approved paths")
        gate.scope = replace(gate.scope, object_ids=gate.scope.object_ids | frozenset(ids))


class CumulativeAgentBudget:
    """Case-wide model-call budget; fixture and cleanup time are excluded."""

    def __init__(self, *, hard_seconds: float = 600, slow_seconds: float = 420) -> None:
        if (any(isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) for value in (hard_seconds, slow_seconds))
                or not 0 < slow_seconds < hard_seconds):
            raise ExpansionPolicyError("budget bounds must be finite and ordered")
        self.hard_seconds = float(hard_seconds)
        self.slow_seconds = float(slow_seconds)
        self.elapsed_seconds = 0.0
        self._started: float | None = None
        self.turn_measurements: list[dict[str, float]] = []

    def start_turn(self, monotonic_now: float) -> float:
        if self._started is not None or not math.isfinite(monotonic_now):
            raise ExpansionPolicyError("invalid or overlapping Agent turn")
        remaining = self.hard_seconds - self.elapsed_seconds
        if remaining <= 0:
            raise ExpansionPolicyError("cumulative Agent case budget exhausted")
        self._started = monotonic_now
        return remaining

    def finish_turn(self, monotonic_now: float) -> None:
        if self._started is None or not math.isfinite(monotonic_now) or monotonic_now < self._started:
            raise ExpansionPolicyError("invalid Agent turn duration")
        elapsed = monotonic_now - self._started
        self.turn_measurements.append({"started_monotonic": self._started,
                                      "finished_monotonic": monotonic_now, "elapsed_seconds": elapsed})
        self.elapsed_seconds += elapsed
        self._started = None

    @property
    def slow(self) -> bool:
        return self.elapsed_seconds >= self.slow_seconds


def classify_expansion_outcome(*, passed: bool, records: Sequence[Mapping[str, object]],
                               events: Sequence[Mapping[str, object]],
                               infrastructure: Mapping[str, object] | None = None) -> str:
    """Preserve uncertainty and proven pre-action infrastructure independently.

    Admission consumes a reservation even when the runner returns no JSON.
    Only a durable terminal execution event proves completion or definite
    failure; an oracle snapshot never upgrades an incomplete Agent task.
    """
    if passed:
        return "PASS"
    reserved = any(row.get("accepted") is True and tuple(row.get("gateway_arguments", ()))[:1] == ("execute",)
                   for row in records)
    states = [event.get("to_state") for event in events]
    state = states[-1] if states else None
    if state == "indeterminate" or ((reserved or "executing" in states) and state not in {
            "executed_unverified", "verified", "result_schema_checked", "verification_failed",
            "execution_failed", "execution_cancelled", "repreview_required"}):
        return "INDETERMINATE"
    if infrastructure and infrastructure.get("agent_item_event_count") == 0 and infrastructure.get("category") in {
            "authentication", "quota_or_rate_limit", "service_unavailable", "timeout_before_agent_action",
            "turn_failed_before_agent_action"}:
        return "BLOCKED"
    return "FAIL"
