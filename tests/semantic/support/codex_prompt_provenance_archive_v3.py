"""Offline-only decoder for sealed pre-typed V3 prompt provenance.

This module is deliberately imported only by verify-only campaign code after
the sealed manifest has been classified as historical.  It upgrades the old
protocol document in memory, but it never writes the upgraded representation
and never makes the retired JSON/action grammar available to the current
Broker, runner, or prompt-provenance reader.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_eval_bundle_v3 import OnlineScenario
from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    V3ProtocolError,
    materialize_typed_transaction_protocol_requests,
    operation_request_equivalence,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    PromptProvenanceError,
    PromptProvenanceEvidence,
    _canonicalize_legacy_protocol_manifest,
    _json_clone,
    _read_prompt_provenance_with_codec,
    _sha256_json,
    deserialize_protocol,
)
from wwise_waapi.operation_registry import parse_operation_request


_SEMANTIC_EQUIVALENCE_BY_KIND = {
    "semantic_json": "wire_exact",
    "semantic_json_audio_import_default_operation_v1": (
        "audio_import_default_operation_v1"
    ),
    "semantic_json_object_operation_v1": "object_operation_v1",
    "semantic_json_soundbank_generate_v1": "soundbank_generate_v1",
    "semantic_json_switch_container_remove_assignment_v1": (
        "switch_container_remove_assignment_v1"
    ),
}
_SEALED_QUERY_KIND = "sealed_query_identity_object_operation_json"


def is_archived_prompt_protocol(value: Mapping[str, Any]) -> bool:
    """Return whether a sealed protocol uses the retired manifest grammar."""

    steps = value.get("steps")
    if not isinstance(steps, list):
        return False
    return any(
        isinstance(step, Mapping)
        and (
            "metadata_binding" not in step
            or any(
                isinstance(argument, Mapping)
                and argument.get("kind") == "draft_action_json"
                for argument in step.get("arguments", [])
            )
        )
        for step in steps
    )


def read_archived_prompt_provenance(
    path: Path,
    *,
    scenario: OnlineScenario,
    version: str,
    scenario_root: Path,
    expected_prompts: Sequence[str] | None = None,
    require_paths: bool,
) -> PromptProvenanceEvidence:
    """Validate one immutable historical prompt document without current ingress."""

    return _read_prompt_provenance_with_codec(
        path,
        scenario=scenario,
        version=version,
        scenario_root=scenario_root,
        expected_prompts=expected_prompts,
        expected_protocol=None,
        require_paths=require_paths,
        protocol_decoder=deserialize_archived_protocol,
        protocol_canonicalizer=_canonicalize_archived_protocol,
        protocol_request_materializer=lambda value: _archived_protocol_requests(
            value,
            version=version,
        ),
    )


def deserialize_archived_protocol(
    value: Mapping[str, Any],
) -> V3GatewayProtocol:
    """Upgrade one reviewed historical manifest and invoke the strict model."""

    if not is_archived_prompt_protocol(value):
        raise PromptProvenanceError(
            "offline archive codec requires a historical protocol manifest"
        )
    return deserialize_protocol(_canonicalize_archived_protocol(value))


def _canonicalize_archived_protocol(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    canonical = _canonicalize_legacy_protocol_manifest(value)
    steps = canonical.get("steps")
    if not isinstance(steps, list):
        raise PromptProvenanceError("archived protocol steps are unavailable")
    for step in steps:
        if not isinstance(step, dict):
            raise PromptProvenanceError("archived protocol step is invalid")
        step.setdefault("metadata_binding", None)
        arguments = step.get("arguments")
        if not isinstance(arguments, list):
            raise PromptProvenanceError("archived protocol arguments are invalid")
        for argument in arguments:
            if (
                isinstance(argument, dict)
                and argument.get("kind") == "draft_action_json"
            ):
                argument["kind"] = "draft_typed_action"
    return canonical


def _archived_protocol_requests(
    value: Mapping[str, Any],
    *,
    version: str,
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    """Replay old raw previews plus old Composer actions into canonical requests."""

    steps = value.get("steps")
    if not isinstance(steps, list):
        raise PromptProvenanceError("archived protocol steps are unavailable")
    indexed: list[tuple[int, str, Mapping[str, Any]]] = []
    for step_index, step in enumerate(steps):
        if not isinstance(step, Mapping) or step.get("subcommand") != "preview":
            continue
        arguments = step.get("arguments")
        if not isinstance(arguments, list):
            raise PromptProvenanceError(
                "archived preview request argument topology drifted"
            )
        semantic_index = _archived_preview_semantic_index(arguments)
        semantic = arguments[semantic_index]
        if not isinstance(semantic, Mapping):
            raise PromptProvenanceError("archived preview request is invalid")
        request = _archived_semantic_request(semantic, version=version)
        indexed.append(
            (
                step_index,
                f"/steps/{step_index}/arguments/{semantic_index}/value",
                request,
            )
        )

    protocol = deserialize_archived_protocol(value)
    try:
        composer = materialize_typed_transaction_protocol_requests(
            protocol,
            version=version,
        )
    except V3ProtocolError as exc:
        raise PromptProvenanceError(
            "archived Composer protocol cannot materialize its request"
        ) from exc
    step_indexes = {step.name: index for index, step in enumerate(protocol.steps)}
    for base, request in composer:
        preview_name = base.removeprefix("/composer/")
        indexed.append((step_indexes.get(preview_name, len(steps)), base, request))
    indexed.sort(key=lambda item: item[0])
    return tuple((base, request) for _index, base, request in indexed)


def _archived_preview_semantic_index(arguments: list[Any]) -> int:
    if (
        len(arguments) == 3
        and arguments[0] == {"kind": "literal", "value": "--apply"}
        and arguments[1] == {"kind": "literal", "value": "--request-json"}
    ):
        return 2
    if (
        len(arguments) == 2
        and arguments[0] == {"kind": "literal", "value": "--request-json"}
    ):
        return 1
    raise PromptProvenanceError("archived preview request flag drifted")


def _archived_semantic_request(
    semantic: Mapping[str, Any],
    *,
    version: str,
) -> Mapping[str, Any]:
    kind = semantic.get("kind")
    request = semantic.get("value")
    if not isinstance(request, Mapping) or semantic.get("sha256") != _sha256_json(
        request
    ):
        raise PromptProvenanceError("archived preview request digest is invalid")
    if kind == "metadata_bound_json":
        equivalence = semantic.get("equivalence")
    elif kind == _SEALED_QUERY_KIND:
        equivalence = "object_operation_v1"
    else:
        equivalence = _SEMANTIC_EQUIVALENCE_BY_KIND.get(str(kind))
    if not isinstance(equivalence, str):
        raise PromptProvenanceError("archived preview request kind is unsupported")
    try:
        normalized = parse_operation_request(request, expected_version=version)
    except (TypeError, ValueError) as exc:
        raise PromptProvenanceError(
            "archived preview canonical request is invalid"
        ) from exc
    operation = normalized.operation
    accepted = {"wire_exact", operation_request_equivalence(operation)}
    if operation == "audio.import":
        accepted.add("audio_import_default_operation_v1")
    if equivalence not in accepted:
        raise PromptProvenanceError(
            "archived preview equivalence does not match its operation"
        )
    return _json_clone(normalized.as_dict())


__all__ = [
    "deserialize_archived_protocol",
    "is_archived_prompt_protocol",
    "read_archived_prompt_provenance",
]
