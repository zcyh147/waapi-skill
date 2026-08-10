"""Pre-Codex prompt/protocol provenance for the reviewed heavy V3 suite.

The live runner writes exactly one immutable document after fixture and request
materialization, but before it creates a Codex process.  The document is not a
second source of business truth: each visible value is tied to the frozen
scenario, the closed gateway protocol, or a regular case-owned filesystem
object.  Structured inputs bind every leaf independently.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_oracle_plan_v3 import (
    BUSINESS_ORACLE_PLAN_FILE,
    BusinessOraclePlanEvidence,
)
from tests.semantic.support.codex_filesystem_security import binary_file_open_flags
from tests.semantic.support.codex_eval_bundle_v3 import OnlineScenario
from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    V3ProtocolError,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_modification_policy_protocol,
    build_transaction_protocol,
    materialize_audio_import_composer_protocol_request,
    operation_request_equivalence,
)
from tests.semantic.support.codex_gateway_broker import (
    BoundedIntegerArgument,
    DraftActionJsonArgument,
    DraftActionMetadataBinding,
    DraftActionQueryIdentityBinding,
    DraftActionResponseBinding,
    ExpectedGatewayStep,
    GatewayDerivedReferenceActivationAllowance,
    MetadataBoundJsonArgument,
    MetadataQueryArgument,
    MetadataTokenProjection,
    ResponseBinding,
    SealedQueryIdentityBoundJsonArgument,
    SemanticJsonArgument,
)
from tests.semantic.support.codex_integration_workflows_v1 import (
    EXPECTED_PRIMARY_API as INTEGRATION_V1_PRIMARY_API,
    WORKFLOW_IDS as INTEGRATION_V1_WORKFLOW_IDS,
)
from tests.semantic.support.codex_integration_workflows_v2 import (
    EXPECTED_PRIMARY_API as INTEGRATION_V2_PRIMARY_API,
    WORKFLOW_IDS as INTEGRATION_V2_WORKFLOW_IDS,
)
from tests.semantic.support.codex_soundbank_runtime_v3 import (
    render_soundbank_generation_build_locations,
)


PROMPT_PROVENANCE_CONTRACT = "waapi-skill.codex-prompt-provenance/v1"
PROMPT_PROVENANCE_FILE = "prompt-provenance.json"
PROMPT_MATERIALIZATION_RECEIPT_CONTRACT = (
    "waapi-skill.codex-semantic-prompt-materialization/v3"
)
PROMPT_MATERIALIZATION_RECEIPT_FILE = "prompt-materialization.json"
MAX_PROVENANCE_BYTES = 8 * 1024 * 1024
MAX_PROOF_FILES = 8192
MAX_PROOF_BYTES = 512 * 1024 * 1024
_SEMANTIC_JSON_KIND_BY_EQUIVALENCE = {
    "wire_exact": "semantic_json",
    "audio_import_default_operation_v1": (
        "semantic_json_audio_import_default_operation_v1"
    ),
    "object_operation_v1": "semantic_json_object_operation_v1",
    "soundbank_generate_v1": "semantic_json_soundbank_generate_v1",
    "switch_container_remove_assignment_v1": (
        "semantic_json_switch_container_remove_assignment_v1"
    ),
}
_SEMANTIC_JSON_EQUIVALENCE_BY_KIND = {
    kind: equivalence
    for equivalence, kind in _SEMANTIC_JSON_KIND_BY_EQUIVALENCE.items()
}
_SEALED_QUERY_IDENTITY_JSON_KIND = "sealed_query_identity_object_operation_json"

HEAVY_APIS = frozenset(
    {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
        "ak.wwise.core.object.setReference",
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
        "ak.wwise.core.audio.convert",
        "ak.wwise.core.mediaPool.get",
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.generated",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.setInclusions",
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.migrate",
    }
)
VISIBLE_KINDS = frozenset(
    {
        "absolute_file_path",
        "absolute_directory_path",
        "object_path",
        "structured_array",
        "structured_object",
    }
)
INTEGRATION_VISIBLE_KINDS = frozenset(
    {
        "absolute_directory_path",
        "object_path",
        "string",
        "structured_array",
    }
)
INTEGRATION_VISIBLE_INPUT_SOURCE = "integration_visible_inputs"
MAX_INTEGRATION_SCALAR_BYTES = 16 * 1024
MAX_INTEGRATION_STRUCTURED_BYTES = 256 * 1024
MAX_INTEGRATION_ARRAY_ITEMS = 64
MAX_INTEGRATION_LEAVES = 4096
INTEGRATION_PRIMARY_API = {
    **INTEGRATION_V1_PRIMARY_API,
    **INTEGRATION_V2_PRIMARY_API,
}
INTEGRATION_WORKFLOW_IDS = (
    *INTEGRATION_V1_WORKFLOW_IDS,
    *INTEGRATION_V2_WORKFLOW_IDS,
)


class PromptProvenanceError(RuntimeError):
    """The pre-Codex prompt source chain is incomplete or ambiguous."""


@dataclass(frozen=True, slots=True)
class PromptProvenanceEvidence:
    path: Path
    sha256: str
    payload: Mapping[str, Any]
    prompts: tuple[str, ...]
    visible_values: Mapping[str, str]
    protocol: V3GatewayProtocol


@dataclass(frozen=True, slots=True)
class _DerivedInput:
    value: str
    leaf_origins: Mapping[str, str]


def write_prompt_provenance(
    *,
    scenario: OnlineScenario,
    version: str,
    scenario_root: Path,
    prompts: Sequence[str],
    visible_values: Mapping[str, str],
    protocol: V3GatewayProtocol,
    trusted_sources: Mapping[str, Any] | None = None,
) -> PromptProvenanceEvidence:
    """Write the one fixed no-overwrite provenance document."""

    root = _scenario_root(scenario_root, require_exists=True)
    if scenario.api not in HEAVY_APIS:
        raise PromptProvenanceError(
            f"prompt provenance is closed to the heavy API set: {scenario.api}"
        )
    values = _visible_values(scenario, visible_values)
    prompt_values = _expected_prompts(
        scenario,
        values,
        prompts,
        protocol=protocol,
    )
    protocol_value = serialize_protocol(protocol)
    if len(prompt_values) != len(protocol.turn_prefix_counts):
        raise PromptProvenanceError(
            "prompt count differs from the closed protocol turn boundaries"
        )
    source_value = _trusted_sources(
        scenario,
        root=root,
        values=values,
        protocol_value=protocol_value,
        supplied=trusted_sources or {},
        require_paths=True,
    )
    input_rows = _input_rows(
        scenario,
        root=root,
        values=values,
        protocol_value=protocol_value,
        trusted_sources=source_value,
        require_paths=True,
    )
    payload: dict[str, Any] = {
        "contract": PROMPT_PROVENANCE_CONTRACT,
        "scenario_id": scenario.id,
        "version": version,
        "api": scenario.api,
        "scenario_root": str(root),
        "owned_root": str(root / "owned"),
        "template": {
            "text": scenario.prompt,
            "sha256": scenario.prompt_sha256,
            "visible_inputs": [
                {
                    "name": item.name,
                    "kind": item.kind,
                    "description": item.description,
                }
                for item in scenario.visible_inputs
            ],
        },
        "request": {
            "rendered_prompt": prompt_values[0],
            "sha256": _sha256_text(prompt_values[0]),
            "inputs": input_rows,
        },
        "turns": [
            {
                "index": index,
                "kind": "request" if index == 1 else "confirmation",
                "prompt": prompt,
                "sha256": _sha256_text(prompt),
            }
            for index, prompt in enumerate(prompt_values, start=1)
        ],
        "protocol": {
            "value": protocol_value,
            "sha256": _sha256_json(protocol_value),
        },
        "trusted_sources": source_value,
    }
    path = root / "evidence" / PROMPT_PROVENANCE_FILE
    _write_exclusive_json(path, payload)
    return read_prompt_provenance(
        path,
        scenario=scenario,
        version=version,
        scenario_root=root,
        expected_prompts=prompt_values,
        expected_protocol=protocol,
        require_paths=True,
    )


def read_prompt_provenance(
    path: Path,
    *,
    scenario: OnlineScenario,
    version: str,
    scenario_root: Path,
    expected_prompts: Sequence[str] | None = None,
    expected_protocol: V3GatewayProtocol | None = None,
    require_paths: bool,
) -> PromptProvenanceEvidence:
    """Read once, reject links/duplicates, and rederive every prompt input."""

    root = _scenario_root(scenario_root, require_exists=True)
    expected_path = root / "evidence" / PROMPT_PROVENANCE_FILE
    candidate = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
    if candidate != expected_path:
        raise PromptProvenanceError("prompt provenance path is not the fixed scenario path")
    raw, value = _read_one_json(candidate)
    if not isinstance(value, Mapping) or set(value) != {
        "contract",
        "scenario_id",
        "version",
        "api",
        "scenario_root",
        "owned_root",
        "template",
        "request",
        "turns",
        "protocol",
        "trusted_sources",
    }:
        raise PromptProvenanceError("prompt provenance top-level schema is not closed")
    if (
        value.get("contract") != PROMPT_PROVENANCE_CONTRACT
        or value.get("scenario_id") != scenario.id
        or value.get("version") != version
        or value.get("api") != scenario.api
        or value.get("scenario_root") != str(root)
        or value.get("owned_root") != str(root / "owned")
        or scenario.api not in HEAVY_APIS
    ):
        raise PromptProvenanceError("prompt provenance identity is misbound")

    template = value.get("template")
    expected_template = {
        "text": scenario.prompt,
        "sha256": scenario.prompt_sha256,
        "visible_inputs": [
            {
                "name": item.name,
                "kind": item.kind,
                "description": item.description,
            }
            for item in scenario.visible_inputs
        ],
    }
    if template != expected_template:
        raise PromptProvenanceError("prompt provenance template differs from the suite")

    protocol_row = value.get("protocol")
    if not isinstance(protocol_row, Mapping) or set(protocol_row) != {"value", "sha256"}:
        raise PromptProvenanceError("prompt provenance protocol envelope is invalid")
    protocol_value = protocol_row.get("value")
    if (
        not isinstance(protocol_value, Mapping)
        or protocol_row.get("sha256") != _sha256_json(protocol_value)
    ):
        raise PromptProvenanceError("prompt provenance protocol digest is invalid")
    protocol = deserialize_protocol(protocol_value)
    canonical_protocol_value = _canonicalize_legacy_protocol_manifest(
        protocol_value
    )
    if serialize_protocol(protocol) != canonical_protocol_value:
        raise PromptProvenanceError("protocol manifest is not round-trip exact")
    if (
        expected_protocol is not None
        and canonical_protocol_value != serialize_protocol(expected_protocol)
    ):
        raise PromptProvenanceError("in-memory protocol differs from sealed provenance")

    request = value.get("request")
    if not isinstance(request, Mapping) or set(request) != {
        "rendered_prompt",
        "sha256",
        "inputs",
    }:
        raise PromptProvenanceError("prompt provenance request schema is invalid")
    rows = request.get("inputs")
    if not isinstance(rows, list):
        raise PromptProvenanceError("prompt provenance input rows are invalid")
    visible_values = _validate_input_rows(
        scenario,
        root=root,
        rows=rows,
        protocol_value=protocol_value,
        trusted_sources=value.get("trusted_sources"),
        require_paths=require_paths,
    )
    rendered = scenario.render_prompt(visible_values)
    if (
        request.get("rendered_prompt") != rendered
        or request.get("sha256") != _sha256_text(rendered)
    ):
        raise PromptProvenanceError("rendered request is not reproducible")

    turns = value.get("turns")
    expected = _expected_prompts(
        scenario,
        visible_values,
        expected_prompts,
        protocol=protocol,
    )
    expected_turns = [
        {
            "index": index,
            "kind": "request" if index == 1 else "confirmation",
            "prompt": prompt,
            "sha256": _sha256_text(prompt),
        }
        for index, prompt in enumerate(expected, start=1)
    ]
    if turns != expected_turns or len(expected) != len(protocol.turn_prefix_counts):
        raise PromptProvenanceError("prompt provenance turn topology is invalid")
    canonical = _canonical_json_bytes(value) + b"\n"
    if raw != canonical:
        raise PromptProvenanceError("prompt provenance is not canonical JSON")
    return PromptProvenanceEvidence(
        path=candidate,
        sha256=hashlib.sha256(raw).hexdigest(),
        payload=value,
        prompts=expected,
        visible_values=visible_values,
        protocol=protocol,
    )


def prompt_materialization_receipt(
    provenance: PromptProvenanceEvidence,
    *,
    business_oracle_plan: BusinessOraclePlanEvidence,
) -> dict[str, Any]:
    """Return the small task-local receipt; it contains no independent values."""

    protocol_row = provenance.payload["protocol"]
    expected_plan_path = provenance.path.parent / BUSINESS_ORACLE_PLAN_FILE
    plan_payload = business_oracle_plan.payload
    if (
        business_oracle_plan.path != expected_plan_path
        or not isinstance(business_oracle_plan.sha256, str)
        or len(business_oracle_plan.sha256) != 64
        or any(character not in "0123456789abcdef" for character in business_oracle_plan.sha256)
        or plan_payload.get("scenario_id") != provenance.payload["scenario_id"]
        or plan_payload.get("version") != provenance.payload["version"]
        or plan_payload.get("scenario_root") != str(provenance.path.parent.parent)
        or plan_payload.get("protocol_sha256") != protocol_row["sha256"]
        or plan_payload.get("provenance_sha256") != provenance.sha256
    ):
        raise PromptProvenanceError(
            "prompt receipt business-oracle plan is not bound to provenance"
        )
    return {
        "contract": PROMPT_MATERIALIZATION_RECEIPT_CONTRACT,
        "scenario_id": provenance.payload["scenario_id"],
        "version": provenance.payload["version"],
        "provenance_path": str(provenance.path),
        "provenance_sha256": provenance.sha256,
        "protocol_sha256": protocol_row["sha256"],
        "business_oracle_plan_path": str(business_oracle_plan.path),
        "business_oracle_plan_sha256": business_oracle_plan.sha256,
        "expected_turn_count": len(provenance.prompts),
        "turns": [
            {
                "index": index,
                "kind": "request" if index == 1 else "confirmation",
                "prompt_sha256": _sha256_text(prompt),
            }
            for index, prompt in enumerate(provenance.prompts, start=1)
        ],
    }


def serialize_protocol(protocol: V3GatewayProtocol) -> dict[str, Any]:
    value = {
        "turn_prefix_counts": list(protocol.turn_prefix_counts),
        "steps": [_serialize_step(step) for step in protocol.steps],
    }
    if protocol.allowed_turn_prefix_counts:
        value["allowed_turn_prefix_counts"] = [
            list(item) for item in protocol.allowed_turn_prefix_counts
        ]
        value["terminal_prefix_counts"] = list(protocol.terminal_prefix_counts)
    if protocol.commutative_read_only_step_groups:
        value["commutative_read_only_step_groups"] = [
            list(group)
            for group in protocol.commutative_read_only_step_groups
        ]
    if protocol.commutative_composer_setup_step_groups:
        value["commutative_composer_setup_step_groups"] = [
            list(group)
            for group in protocol.commutative_composer_setup_step_groups
        ]
    return value


def _canonicalize_legacy_protocol_manifest(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Upgrade the one reviewed v1 metadata-bound additive field in memory."""

    canonical = _json_clone(value)
    for step in canonical.get("steps", []):
        for argument in step.get("arguments", []):
            if (
                argument.get("kind") == "metadata_bound_json"
                and "gateway_derived_reference_activations" not in argument
            ):
                argument["gateway_derived_reference_activations"] = []
    return canonical


def deserialize_protocol(value: Mapping[str, Any]) -> V3GatewayProtocol:
    keys = set(value)
    required_keys = {"turn_prefix_counts", "steps"}
    optional_prefix_keys = {
        "allowed_turn_prefix_counts",
        "terminal_prefix_counts",
    }
    allowed_keys = {
        *required_keys,
        *optional_prefix_keys,
        "commutative_read_only_step_groups",
        "commutative_composer_setup_step_groups",
    }
    if (
        not required_keys.issubset(keys)
        or not keys.issubset(allowed_keys)
        or bool(keys & optional_prefix_keys)
        != optional_prefix_keys.issubset(keys)
    ):
        raise PromptProvenanceError("protocol manifest schema is invalid")
    prefixes = value.get("turn_prefix_counts")
    steps = value.get("steps")
    if (
        not isinstance(prefixes, list)
        or any(type(item) is not int for item in prefixes)
        or not isinstance(steps, list)
    ):
        raise PromptProvenanceError("protocol manifest topology is invalid")
    allowed: tuple[tuple[int, ...], ...] = ()
    terminal: tuple[int, ...] = ()
    commutative_groups: tuple[tuple[str, str], ...] = ()
    composer_setup_groups: tuple[tuple[str, ...], ...] = ()
    if "allowed_turn_prefix_counts" in value:
        raw_allowed = value.get("allowed_turn_prefix_counts")
        raw_terminal = value.get("terminal_prefix_counts")
        if (
            not isinstance(raw_allowed, list)
            or any(
                not isinstance(row, list)
                or any(type(item) is not int for item in row)
                for row in raw_allowed
            )
            or not isinstance(raw_terminal, list)
            or any(type(item) is not int for item in raw_terminal)
        ):
            raise PromptProvenanceError(
                "optional protocol prefix topology is invalid"
            )
        allowed = tuple(tuple(row) for row in raw_allowed)
        terminal = tuple(raw_terminal)
    if "commutative_read_only_step_groups" in value:
        raw_groups = value.get("commutative_read_only_step_groups")
        if (
            not isinstance(raw_groups, list)
            or any(
                not isinstance(group, list)
                or len(group) != 2
                or any(not isinstance(item, str) for item in group)
                for group in raw_groups
            )
        ):
            raise PromptProvenanceError(
                "commutative read-only protocol groups are invalid"
            )
        commutative_groups = tuple(
            (group[0], group[1]) for group in raw_groups
        )
    if "commutative_composer_setup_step_groups" in value:
        raw_groups = value.get("commutative_composer_setup_step_groups")
        if (
            not isinstance(raw_groups, list)
            or any(
                not isinstance(group, list)
                or len(group) < 2
                or any(not isinstance(item, str) for item in group)
                for group in raw_groups
            )
        ):
            raise PromptProvenanceError(
                "commutative Composer setup protocol groups are invalid"
            )
        composer_setup_groups = tuple(tuple(group) for group in raw_groups)
    try:
        return V3GatewayProtocol(
            tuple(_deserialize_step(item) for item in steps),
            tuple(prefixes),
            allowed,
            terminal,
            commutative_groups,
            composer_setup_groups,
        )
    except (TypeError, ValueError) as exc:
        raise PromptProvenanceError(
            f"protocol manifest topology is invalid: {exc}"
        ) from exc


def _serialize_step(step: ExpectedGatewayStep) -> dict[str, Any]:
    arguments: list[dict[str, Any]] = []
    for item in step.arguments:
        if isinstance(item, str):
            arguments.append({"kind": "literal", "value": item})
        elif isinstance(item, SealedQueryIdentityBoundJsonArgument):
            cloned = _json_clone(item.expected)
            arguments.append(
                {
                    "kind": _SEALED_QUERY_IDENTITY_JSON_KIND,
                    "value": cloned,
                    "sha256": _sha256_json(cloned),
                    "source_step": item.source_step,
                    "target_pointers": list(item.target_pointers),
                }
            )
        elif isinstance(item, SemanticJsonArgument):
            cloned = _json_clone(item.expected)
            arguments.append(
                {
                    "kind": _SEMANTIC_JSON_KIND_BY_EQUIVALENCE[
                        item.equivalence
                    ],
                    "value": cloned,
                    "sha256": _sha256_json(cloned),
                }
            )
        elif isinstance(item, MetadataQueryArgument):
            arguments.append(
                {
                    "kind": "metadata_query",
                    "label": item.label,
                    "maximum_chars": item.maximum_chars,
                }
            )
        elif isinstance(item, BoundedIntegerArgument):
            arguments.append(
                {
                    "kind": "bounded_integer",
                    "minimum": item.minimum,
                    "maximum": item.maximum,
                }
            )
        elif isinstance(item, MetadataBoundJsonArgument):
            cloned = _json_clone(item.expected)
            arguments.append(
                {
                    "kind": "metadata_bound_json",
                    "value": cloned,
                    "sha256": _sha256_json(cloned),
                    "equivalence": item.equivalence,
                    "metadata_step": item.metadata_step,
                    "object_type": item.object_type,
                    "required_tokens": list(item.required_tokens),
                    "expected_required_token_projection": (
                        [
                            value.as_dict()
                            for value in item.expected_required_token_projection
                        ]
                        if item.expected_required_token_projection is not None
                        else None
                    ),
                    "gateway_derived_reference_activations": [
                        value.as_dict()
                        for value in item.gateway_derived_reference_activations
                    ],
                }
            )
        elif isinstance(item, DraftActionJsonArgument):
            cloned = _json_clone(item.expected)
            row = {
                "kind": "draft_action_json",
                "value": cloned,
                "sha256": _sha256_json(cloned),
                "response_bindings": [
                    {
                        "pointer": binding.pointer,
                        "step": binding.step,
                        "response_pointer": binding.response_pointer,
                    }
                    for binding in item.response_bindings
                ],
            }
            if item.query_identity_bindings:
                row["query_identity_bindings"] = [
                    {
                        "pointer": binding.pointer,
                        "step": binding.step,
                    }
                    for binding in item.query_identity_bindings
                ]
            if item.operation != "object.set":
                row["operation"] = item.operation
            if item.metadata_binding is not None:
                binding = item.metadata_binding
                row["metadata_binding"] = {
                    "step": binding.step,
                    "object_type": binding.object_type,
                    "required_tokens": list(binding.required_tokens),
                    "expected_projection": (
                        None
                        if binding.expected_projection is None
                        else [
                            item.as_dict()
                            for item in binding.expected_projection
                        ]
                    ),
                }
            arguments.append(row)
        elif isinstance(item, ResponseBinding):
            arguments.append(
                {
                    "kind": "response_binding",
                    "step": item.step,
                    "pointer": item.pointer,
                }
            )
        else:
            raise PromptProvenanceError("protocol contains an unsupported argument")
    return {
        "name": step.name,
        "subcommand": step.subcommand,
        "arguments": arguments,
        "allowed_exit_codes": list(step.allowed_exit_codes),
        "gateway_global_arguments": list(step.gateway_global_arguments),
        "allow_omitted_empty_json_objects": step.allow_omitted_empty_json_objects,
        "allow_omitted_default_event_count_one": (
            step.allow_omitted_default_event_count_one
        ),
        "expected_error_code": step.expected_error_code,
        "expected_result_command": step.expected_result_command,
        "terminal_execute": step.terminal_execute,
    }


def _deserialize_step(value: Any) -> ExpectedGatewayStep:
    if not isinstance(value, Mapping) or set(value) != {
        "name",
        "subcommand",
        "arguments",
        "allowed_exit_codes",
        "gateway_global_arguments",
        "allow_omitted_empty_json_objects",
        "allow_omitted_default_event_count_one",
        "expected_error_code",
        "expected_result_command",
        "terminal_execute",
    }:
        raise PromptProvenanceError("protocol step schema is invalid")
    raw_arguments = value.get("arguments")
    if (
        not isinstance(value.get("name"), str)
        or not value.get("name")
        or not isinstance(value.get("subcommand"), str)
        or not value.get("subcommand")
        or type(value.get("allow_omitted_empty_json_objects")) is not bool
        or type(value.get("allow_omitted_default_event_count_one")) is not bool
        or not isinstance(value.get("expected_error_code"), str)
        or not isinstance(value.get("expected_result_command"), str)
        or type(value.get("terminal_execute")) is not bool
    ):
        raise PromptProvenanceError("protocol step scalar fields are invalid")
    if not isinstance(raw_arguments, list):
        raise PromptProvenanceError("protocol step arguments are invalid")
    arguments: list[Any] = []
    for row in raw_arguments:
        if not isinstance(row, Mapping) or "kind" not in row:
            raise PromptProvenanceError("protocol argument schema is invalid")
        kind = row.get("kind")
        if kind == "literal" and set(row) == {"kind", "value"}:
            if not isinstance(row.get("value"), str):
                raise PromptProvenanceError("literal protocol argument is invalid")
            arguments.append(row["value"])
        elif (
            kind == _SEALED_QUERY_IDENTITY_JSON_KIND
            and set(row)
            == {
                "kind",
                "value",
                "sha256",
                "source_step",
                "target_pointers",
            }
        ):
            raw_pointers = row.get("target_pointers")
            if (
                row.get("sha256") != _sha256_json(row.get("value"))
                or not isinstance(row.get("source_step"), str)
                or not isinstance(raw_pointers, list)
                or any(not isinstance(item, str) for item in raw_pointers)
            ):
                raise PromptProvenanceError(
                    "sealed-query-identity protocol argument is invalid"
                )
            try:
                arguments.append(
                    SealedQueryIdentityBoundJsonArgument(
                        expected=_json_clone(row.get("value")),
                        source_step=str(row["source_step"]),
                        target_pointers=tuple(raw_pointers),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise PromptProvenanceError(
                    "sealed-query-identity protocol argument is invalid"
                ) from exc
        elif (
            kind in _SEMANTIC_JSON_EQUIVALENCE_BY_KIND
            and set(row) == {"kind", "value", "sha256"}
        ):
            if row.get("sha256") != _sha256_json(row.get("value")):
                raise PromptProvenanceError("semantic protocol argument digest is invalid")
            arguments.append(
                SemanticJsonArgument(
                    _json_clone(row.get("value")),
                    equivalence=_SEMANTIC_JSON_EQUIVALENCE_BY_KIND[str(kind)],
                )
            )
        elif kind == "metadata_query" and set(row) == {
            "kind",
            "label",
            "maximum_chars",
        }:
            if (
                not isinstance(row.get("label"), str)
                or not row.get("label")
                or type(row.get("maximum_chars")) is not int
            ):
                raise PromptProvenanceError(
                    "metadata-query protocol argument is invalid"
                )
            arguments.append(
                MetadataQueryArgument(
                    str(row["label"]),
                    int(row["maximum_chars"]),
                )
            )
        elif kind == "bounded_integer" and set(row) == {
            "kind",
            "minimum",
            "maximum",
        }:
            if (
                type(row.get("minimum")) is not int
                or type(row.get("maximum")) is not int
            ):
                raise PromptProvenanceError(
                    "bounded-integer protocol argument is invalid"
                )
            arguments.append(
                BoundedIntegerArgument(
                    int(row["minimum"]),
                    int(row["maximum"]),
                )
            )
        elif kind == "metadata_bound_json" and set(row) in (
            {
                "kind",
                "value",
                "sha256",
                "equivalence",
                "metadata_step",
                "object_type",
                "required_tokens",
                "expected_required_token_projection",
            },
            {
                "kind",
                "value",
                "sha256",
                "equivalence",
                "metadata_step",
                "object_type",
                "required_tokens",
                "expected_required_token_projection",
                "gateway_derived_reference_activations",
            },
        ):
            raw_tokens = row.get("required_tokens")
            raw_projection = row.get(
                "expected_required_token_projection"
            )
            raw_activations = row.get(
                "gateway_derived_reference_activations",
                [],
            )
            if (
                row.get("sha256") != _sha256_json(row.get("value"))
                or row.get("equivalence")
                not in {
                    "wire_exact",
                    "audio_import_v1",
                    "audio_import_tab_v1",
                    "object_set_v1",
                    "object_set_rtpc_v1",
                }
                or not isinstance(row.get("metadata_step"), str)
                or not isinstance(row.get("object_type"), str)
                or not isinstance(raw_tokens, list)
                or any(not isinstance(item, str) for item in raw_tokens)
                or not isinstance(raw_activations, list)
                or any(
                    not isinstance(item, Mapping)
                    or set(item)
                    != {
                        "row_index",
                        "property_name",
                        "property_value",
                        "reference_name",
                    }
                    or type(item.get("row_index")) is not int
                    or not isinstance(item.get("property_name"), str)
                    or type(item.get("property_value")) is not bool
                    or not isinstance(item.get("reference_name"), str)
                    for item in raw_activations
                )
                or (
                    raw_projection is not None
                    and (
                        not isinstance(raw_projection, list)
                        or any(
                            not isinstance(item, Mapping)
                            or set(item)
                            != {"name", "kind", "metadata_type"}
                            or any(
                                not isinstance(item.get(field), str)
                                for field in (
                                    "name",
                                    "kind",
                                    "metadata_type",
                                )
                            )
                            for item in raw_projection
                        )
                    )
                )
            ):
                raise PromptProvenanceError(
                    "metadata-bound JSON protocol argument is invalid"
                )
            try:
                arguments.append(
                    MetadataBoundJsonArgument(
                        expected=_json_clone(row.get("value")),
                        metadata_step=str(row["metadata_step"]),
                        object_type=str(row["object_type"]),
                        required_tokens=tuple(raw_tokens),
                        expected_required_token_projection=(
                            tuple(
                                MetadataTokenProjection(
                                    name=str(item["name"]),
                                    kind=str(item["kind"]),
                                    metadata_type=str(item["metadata_type"]),
                                )
                                for item in raw_projection
                            )
                            if isinstance(raw_projection, list)
                            else None
                        ),
                        equivalence=str(row["equivalence"]),
                        gateway_derived_reference_activations=tuple(
                            GatewayDerivedReferenceActivationAllowance(
                                row_index=int(item["row_index"]),
                                property_name=str(item["property_name"]),
                                property_value=item["property_value"],
                                reference_name=str(item["reference_name"]),
                            )
                            for item in raw_activations
                        ),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise PromptProvenanceError(
                    "metadata-bound JSON protocol argument is invalid"
                ) from exc
        elif kind == "draft_action_json" and set(row).issubset(
            {
                "kind",
                "value",
                "sha256",
                "response_bindings",
                "query_identity_bindings",
                "operation",
                "metadata_binding",
            }
        ) and {"kind", "value", "sha256", "response_bindings"}.issubset(row):
            raw_bindings = row.get("response_bindings")
            raw_identity_bindings = row.get("query_identity_bindings", [])
            raw_metadata_binding = row.get("metadata_binding")
            if (
                row.get("sha256") != _sha256_json(row.get("value"))
                or not isinstance(raw_bindings, list)
                or any(
                    not isinstance(binding, Mapping)
                    or set(binding) != {"pointer", "step", "response_pointer"}
                    or any(
                        not isinstance(binding.get(field), str)
                        for field in ("pointer", "step", "response_pointer")
                    )
                    for binding in raw_bindings
                )
                or not isinstance(raw_identity_bindings, list)
                or any(
                    not isinstance(binding, Mapping)
                    or set(binding) != {"pointer", "step"}
                    or not isinstance(binding.get("pointer"), str)
                    or not isinstance(binding.get("step"), str)
                    for binding in raw_identity_bindings
                )
                or (
                    "operation" in row
                    and not isinstance(row.get("operation"), str)
                )
                or (
                    raw_metadata_binding is not None
                    and (
                        not isinstance(raw_metadata_binding, Mapping)
                        or set(raw_metadata_binding)
                        != {
                            "step",
                            "object_type",
                            "required_tokens",
                            "expected_projection",
                        }
                        or not isinstance(
                            raw_metadata_binding.get("required_tokens"),
                            list,
                        )
                        or not all(
                            isinstance(token, str)
                            for token in raw_metadata_binding.get(
                                "required_tokens",
                                (),
                            )
                        )
                        or (
                            raw_metadata_binding.get("expected_projection")
                            is not None
                            and (
                                not isinstance(
                                    raw_metadata_binding.get(
                                        "expected_projection"
                                    ),
                                    list,
                                )
                                or any(
                                    not isinstance(item, Mapping)
                                    or set(item)
                                    != {"name", "kind", "metadata_type"}
                                    for item in raw_metadata_binding.get(
                                        "expected_projection",
                                        (),
                                    )
                                )
                            )
                        )
                    )
                )
            ):
                raise PromptProvenanceError(
                    "Draft-action JSON protocol argument is invalid"
                )
            try:
                arguments.append(
                    DraftActionJsonArgument(
                        expected=_json_clone(row.get("value")),
                        response_bindings=tuple(
                            DraftActionResponseBinding(
                                pointer=str(binding["pointer"]),
                                step=str(binding["step"]),
                                response_pointer=str(binding["response_pointer"]),
                            )
                            for binding in raw_bindings
                        ),
                        query_identity_bindings=tuple(
                            DraftActionQueryIdentityBinding(
                                pointer=str(binding["pointer"]),
                                step=str(binding["step"]),
                            )
                            for binding in raw_identity_bindings
                        ),
                        operation=str(row.get("operation", "object.set")),
                        metadata_binding=(
                            None
                            if raw_metadata_binding is None
                            else DraftActionMetadataBinding(
                                step=str(raw_metadata_binding["step"]),
                                object_type=str(
                                    raw_metadata_binding["object_type"]
                                ),
                                required_tokens=tuple(
                                    raw_metadata_binding["required_tokens"]
                                ),
                                expected_projection=(
                                    None
                                    if raw_metadata_binding[
                                        "expected_projection"
                                    ]
                                    is None
                                    else tuple(
                                        MetadataTokenProjection(
                                            name=str(item["name"]),
                                            kind=str(item["kind"]),
                                            metadata_type=str(
                                                item["metadata_type"]
                                            ),
                                        )
                                        for item in raw_metadata_binding[
                                            "expected_projection"
                                        ]
                                    )
                                ),
                            )
                        ),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise PromptProvenanceError(
                    "Draft-action JSON protocol argument is invalid"
                ) from exc
        elif kind == "response_binding" and set(row) == {"kind", "step", "pointer"}:
            if not isinstance(row.get("step"), str) or not isinstance(row.get("pointer"), str):
                raise PromptProvenanceError("response-binding protocol argument is invalid")
            arguments.append(ResponseBinding(str(row["step"]), str(row["pointer"])))
        else:
            raise PromptProvenanceError("protocol argument fields are not closed")
    allowed = value.get("allowed_exit_codes")
    globals_ = value.get("gateway_global_arguments")
    if (
        not isinstance(allowed, list)
        or any(type(item) is not int for item in allowed)
        or not isinstance(globals_, list)
        or any(not isinstance(item, str) for item in globals_)
    ):
        raise PromptProvenanceError("protocol step option arrays are invalid")
    try:
        return ExpectedGatewayStep(
            name=value["name"],
            subcommand=value["subcommand"],
            arguments=tuple(arguments),
            allowed_exit_codes=tuple(allowed),
            gateway_global_arguments=tuple(globals_),
            allow_omitted_empty_json_objects=value["allow_omitted_empty_json_objects"],
            allow_omitted_default_event_count_one=value[
                "allow_omitted_default_event_count_one"
            ],
            expected_error_code=value["expected_error_code"],
            expected_result_command=value["expected_result_command"],
            terminal_execute=value["terminal_execute"],
        )
    except (TypeError, ValueError) as exc:
        raise PromptProvenanceError(f"protocol step is invalid: {exc}") from exc


def _input_rows(
    scenario: OnlineScenario,
    *,
    root: Path,
    values: Mapping[str, str],
    protocol_value: Mapping[str, Any],
    trusted_sources: Mapping[str, Any],
    require_paths: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    integration_workflow = _integration_workflow_id(scenario)
    allowed_kinds = (
        INTEGRATION_VISIBLE_KINDS
        if integration_workflow is not None
        else VISIBLE_KINDS
    )
    for declared in scenario.visible_inputs:
        if declared.kind not in allowed_kinds:
            raise PromptProvenanceError(
                f"heavy prompt uses an unreviewed visible kind: {declared.kind}"
            )
        value = values[declared.name]
        derived = _derive_input(
            scenario,
            input_name=declared.name,
            root=root,
            protocol_value=protocol_value,
            trusted_sources=trusted_sources,
        )
        if value != derived.value:
            raise PromptProvenanceError(
                f"{scenario.id} {declared.name} differs from its reviewed source mapping"
            )
        parsed: Any = None
        canonical: str | None = None
        if declared.kind in {"structured_array", "structured_object"}:
            parsed = _strict_json_text(value)
            expected_type = list if declared.kind == "structured_array" else dict
            if type(parsed) is not expected_type:
                raise PromptProvenanceError(
                    f"{declared.name} does not match {declared.kind}"
                )
            canonical = _canonical_json_bytes(parsed).decode("utf-8")
            if value != canonical:
                raise PromptProvenanceError(
                    f"{declared.name} is not canonical structured JSON"
                )
            leaf_values = tuple(_walk_leaves(parsed))
            if not leaf_values:
                raise PromptProvenanceError(
                    f"{declared.name} has no independently bindable leaves"
                )
        else:
            leaf_values = (("", value),)
        bindings = [
            _leaf_binding(
                scenario,
                input_name=declared.name,
                input_kind=declared.kind,
                pointer=pointer,
                leaf=leaf,
                root=root,
                protocol_value=protocol_value,
                trusted_sources=trusted_sources,
                reviewed_origin=derived.leaf_origins.get(pointer),
                require_paths=require_paths,
            )
            for pointer, leaf in leaf_values
        ]
        rows.append(
            {
                "name": declared.name,
                "kind": declared.kind,
                "value": value,
                "value_sha256": _sha256_text(value),
                "canonical_json": canonical,
                "leaf_bindings": bindings,
            }
        )
    return rows


def _validate_input_rows(
    scenario: OnlineScenario,
    *,
    root: Path,
    rows: Sequence[Any],
    protocol_value: Mapping[str, Any],
    trusted_sources: Any,
    require_paths: bool,
) -> dict[str, str]:
    source_value = _trusted_sources(
        scenario,
        root=root,
        values={
            str(row.get("name")): str(row.get("value"))
            for row in rows
            if isinstance(row, Mapping)
        },
        protocol_value=protocol_value,
        supplied=trusted_sources if isinstance(trusted_sources, Mapping) else {},
        require_paths=require_paths,
        serialized=True,
    )
    if len(rows) != len(scenario.visible_inputs):
        raise PromptProvenanceError("prompt provenance visible-input count drifted")
    values: dict[str, str] = {}
    for row, declared in zip(rows, scenario.visible_inputs, strict=True):
        if not isinstance(row, Mapping) or set(row) != {
            "name",
            "kind",
            "value",
            "value_sha256",
            "canonical_json",
            "leaf_bindings",
        }:
            raise PromptProvenanceError("prompt provenance input row is not closed")
        value = row.get("value")
        if (
            row.get("name") != declared.name
            or row.get("kind") != declared.kind
            or not isinstance(value, str)
            or row.get("value_sha256") != _sha256_text(value)
            or not isinstance(row.get("leaf_bindings"), list)
        ):
            raise PromptProvenanceError("prompt provenance input identity is invalid")
        values[declared.name] = value
    expected = _input_rows(
        scenario,
        root=root,
        values=values,
        protocol_value=protocol_value,
        trusted_sources=source_value,
        require_paths=require_paths,
    )
    if not require_paths:
        for actual_row, expected_row in zip(rows, expected, strict=True):
            actual_bindings = actual_row["leaf_bindings"]
            expected_bindings = expected_row["leaf_bindings"]
            for actual, derived in zip(actual_bindings, expected_bindings, strict=True):
                if derived["origin_kind"] != "owned_path":
                    continue
                _validate_archived_path_binding(actual, derived)
                for key in ("size", "sha256", "mtime_ns"):
                    derived[key] = actual[key]
    if list(rows) != expected:
        raise PromptProvenanceError("prompt provenance leaf origins are not reproducible")
    return values


def _leaf_binding(
    scenario: OnlineScenario,
    *,
    input_name: str,
    input_kind: str,
    pointer: str,
    leaf: Any,
    root: Path,
    protocol_value: Mapping[str, Any],
    trusted_sources: Mapping[str, Any],
    reviewed_origin: str | None,
    require_paths: bool,
) -> dict[str, Any]:
    base = {
        "pointer": pointer,
        "value_sha256": _sha256_json(leaf),
        "origin_kind": "",
        "origin_pointer": "",
        "path_kind": "",
        "owned_relative_path": "",
        "size": None,
        "sha256": "",
        "mtime_ns": None,
    }
    trusted_origin = bool(
        reviewed_origin
        and reviewed_origin.startswith(
            (
                "/compound_import_visible_rows/",
                f"/{INTEGRATION_VISIBLE_INPUT_SOURCE}/",
            )
        )
    )
    if scenario.api == "ak.wwise.core.soundbank.generate" and input_name == "build_locations":
        source_pointer = _build_location_source_pointer(pointer)
        source_leaf = _json_pointer(trusted_sources, source_pointer)
        expected_build = _strict_json_text(
            _derive_input(
                scenario,
                input_name=input_name,
                root=root,
                protocol_value=protocol_value,
                trusted_sources=trusted_sources,
            ).value
        )
        if not _json_equal(_json_pointer(expected_build, pointer), leaf):
            raise PromptProvenanceError(
                "SoundBank build_locations leaf differs from its pure projection"
            )
        # Path aliases intentionally differ from the absolute live source.
        # Non-path leaves (platform names) must still be byte-for-byte equal.
        if pointer.endswith("/name") and not _json_equal(source_leaf, leaf):
            raise PromptProvenanceError(
                "SoundBank build_locations name differs from project info"
            )
        base.update(
            {
                "origin_kind": "trusted_source",
                "origin_pointer": source_pointer,
            }
        )
        return base
    if isinstance(leaf, str) and os.path.isabs(leaf):
        expected_path_kind = _expected_leaf_path_kind(
            scenario,
            input_name=input_name,
            input_kind=input_kind,
            pointer=pointer,
        )
        proof = _path_proof(
            leaf,
            root=root,
            expected_kind=expected_path_kind,
            require_exists=require_paths,
        )
        if reviewed_origin:
            source_leaf = _json_pointer(
                trusted_sources if trusted_origin else protocol_value,
                reviewed_origin,
            )
            if not _json_equal(source_leaf, leaf):
                projection_exception = (
                    scenario.api == "ak.wwise.cli.generateSoundbank"
                    and input_name == "output_directory"
                    and reviewed_origin.endswith("/arguments/args/soundbank-path")
                )
                if not projection_exception:
                    raise PromptProvenanceError(
                        f"reviewed path mapping differs at {reviewed_origin}"
                    )
        _enforce_fixed_path(scenario.api, input_name, proof, root=root)
        base.update(
            {
                "origin_kind": "owned_path",
                "origin_pointer": reviewed_origin or "",
                "path_kind": proof["path_kind"],
                "owned_relative_path": proof["owned_relative_path"],
                "size": proof["size"],
                "sha256": proof["sha256"],
                "mtime_ns": proof["mtime_ns"],
            }
        )
        return base
    if reviewed_origin:
        source_leaf = _json_pointer(
            trusted_sources if trusted_origin else protocol_value,
            reviewed_origin,
        )
        if not _json_equal(source_leaf, leaf):
            raise PromptProvenanceError(
                f"reviewed protocol mapping differs at {reviewed_origin}"
            )
        base.update(
            {
                "origin_kind": (
                    "trusted_source" if trusted_origin else "protocol"
                ),
                "origin_pointer": reviewed_origin,
            }
        )
        return base
    raise PromptProvenanceError(
        f"{scenario.id} {input_name}{pointer} has no trusted leaf origin"
    )


def _derive_input(
    scenario: OnlineScenario,
    *,
    input_name: str,
    root: Path,
    protocol_value: Mapping[str, Any],
    trusted_sources: Mapping[str, Any],
) -> _DerivedInput:
    """Apply the closed reviewed input mapping, never a value search."""

    workflow_id = _integration_workflow_id(scenario)
    if workflow_id is not None:
        return _derive_integration_visible_input(
            scenario,
            workflow_id=workflow_id,
            input_name=input_name,
            trusted_sources=trusted_sources,
        )

    scenario_versions = tuple(getattr(scenario, "versions", ()))
    requests = _protocol_requests(
        protocol_value,
        version=(scenario_versions[0] if len(scenario_versions) == 1 else None),
    )
    api = scenario.api
    if api in {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
        "ak.wwise.core.mediaPool.get",
        "ak.wwise.core.soundbank.generated",
    }:
        raise PromptProvenanceError(f"{api} has no reviewed visible input {input_name}")
    if not requests:
        raise PromptProvenanceError(f"{api} visible input lacks a preview request")
    base, request = requests[0]
    arguments = _mapping_at(request, "arguments")

    if api == "ak.wwise.core.audio.import":
        if input_name == "media_directory":
            return _DerivedInput(
                str(root / "owned" / "assets" / "import-case" / "sources"),
                {"": ""},
            )
        if input_name == "import_rows":
            source = trusted_sources.get("compound_import_visible_rows")
            source_value = (
                source.get("value")
                if isinstance(source, Mapping)
                else None
            )
            if source_value is not None:
                if not isinstance(source_value, list):
                    raise PromptProvenanceError(
                        "compound import visible-row source is invalid"
                    )
                return _DerivedInput(
                    _canonical_json_bytes(source_value).decode("utf-8"),
                    {
                        pointer: (
                            "/compound_import_visible_rows/value"
                            + pointer
                        )
                        for pointer, _ in _walk_leaves(source_value)
                    },
                )
            value = arguments.get("imports")
            if base.startswith("/composer/"):
                if not isinstance(value, list):
                    raise PromptProvenanceError(
                        "audio.import Composer request rows are invalid"
                    )
                return _DerivedInput(
                    _canonical_json_bytes(value).decode("utf-8"),
                    _audio_import_composer_row_origins(protocol_value, value),
                )
            pointer = base + "/arguments/imports"
            return _structured_derived(value, pointer)

    if api == "ak.wwise.core.audio.importTabDelimited":
        location = _mapping_at(arguments, "import_location").get("value")
        if input_name == "import_location":
            pointer = base + "/arguments/import_location/value"
            if any(
                _mapping_at(_mapping_at(item, "arguments"), "import_location").get("value")
                != location
                for _, item in requests
            ):
                raise PromptProvenanceError("tab import locations differ across requests")
            return _scalar_derived(location, pointer)
        if input_name == "import_file":
            return _scalar_derived(
                arguments.get("import_file"),
                base + "/arguments/import_file",
            )
        if input_name == "language_import_files":
            rows: list[dict[str, Any]] = []
            origins: dict[str, str] = {}
            for index, (request_base, item) in enumerate(requests):
                item_arguments = _mapping_at(item, "arguments")
                rows.append(
                    {
                        "file": item_arguments.get("import_file"),
                        "language": item_arguments.get("import_language"),
                        "import_operation": item_arguments.get("import_operation"),
                    }
                )
                origins[f"/{index}/file"] = request_base + "/arguments/import_file"
                origins[f"/{index}/language"] = request_base + "/arguments/import_language"
                origins[f"/{index}/import_operation"] = (
                    request_base + "/arguments/import_operation"
                )
            return _DerivedInput(_canonical_json_bytes(rows).decode("utf-8"), origins)

    if api == "ak.wwise.core.audio.convert" and input_name == "io_root":
        return _scalar_derived(arguments.get("io_root"), base + "/arguments/io_root")

    if api == "ak.wwise.core.soundbank.convertExternalSources" and input_name == "source_jobs":
        return _structured_derived(
            arguments.get("sources"),
            base + "/arguments/sources",
        )

    if api == "ak.wwise.core.soundbank.generate":
        if input_name == "generation_request":
            return _structured_derived(arguments, base + "/arguments")
        if input_name == "build_locations":
            source = trusted_sources.get("soundbank_generate_project_info")
            projection = source.get("value") if isinstance(source, Mapping) else None
            if not isinstance(projection, Mapping):
                raise PromptProvenanceError("SoundBank build projection is unavailable")
            rendered = render_soundbank_generation_build_locations(
                projection,
                io_root=root / "owned",
            )
            origins = {
                pointer: _build_location_source_pointer(pointer)
                for pointer, _ in _walk_leaves(rendered)
            }
            return _DerivedInput(
                _canonical_json_bytes(rendered).decode("utf-8"), origins
            )

    if api == "ak.wwise.core.soundbank.processDefinitionFiles":
        if input_name == "definition_files":
            return _structured_derived(
                arguments.get("files"), base + "/arguments/files"
            )
        if input_name == "io_root":
            return _scalar_derived(
                arguments.get("io_root"), base + "/arguments/io_root"
            )

    if api == "ak.wwise.core.soundbank.setInclusions":
        if input_name == "soundbank_path":
            soundbank = _mapping_at(arguments, "soundbank")
            if soundbank.get("kind") != "path":
                raise PromptProvenanceError("SoundBank identity kind is not path")
            return _scalar_derived(
                soundbank.get("value"),
                base + "/arguments/soundbank/value",
            )
        if input_name == "inclusion_changes":
            projected = {
                "mode": arguments.get("mode"),
                "inclusions": arguments.get("inclusions"),
            }
            origins: dict[str, str] = {}
            for pointer, _ in _walk_leaves(projected):
                if pointer == "/mode":
                    origins[pointer] = base + "/arguments/mode"
                elif pointer.startswith("/inclusions"):
                    origins[pointer] = base + "/arguments" + pointer
                else:
                    raise PromptProvenanceError("unreviewed inclusion projection leaf")
            return _DerivedInput(
                _canonical_json_bytes(projected).decode("utf-8"), origins
            )

    if api.startswith("ak.wwise.cli."):
        return _derive_cli_input(
            api,
            input_name=input_name,
            request_base=base,
            request=request,
        )
    raise PromptProvenanceError(f"no reviewed provenance mapping for {api}/{input_name}")


def _derive_cli_input(
    api: str,
    *,
    input_name: str,
    request_base: str,
    request: Mapping[str, Any],
) -> _DerivedInput:
    envelope = _mapping_at(request, "arguments")
    if envelope.get("api") != api or envelope.get("options") != {}:
        raise PromptProvenanceError("CLI request envelope is not exact")
    args = _mapping_at(envelope, "args")
    args_base = request_base + "/arguments/args"
    direct_fields = {
        "project_path": "project",
        "bank_list_path": "bank",
        "cache_directory": "cache",
        "root_output_directory": "root-output-path",
        "import_file": "tab-delimited-import-file",
    }
    if input_name in direct_fields:
        field = direct_fields[input_name]
        return _scalar_derived(args.get(field), f"{args_base}/{_escape_pointer(field)}")
    if api == "ak.wwise.cli.convertExternalSource":
        if input_name == "source_list_path":
            return _scalar_derived(args.get("source-file"), args_base + "/source-file")
        source_names = {
            "windows_source_list": ("source-by-platform", "Windows"),
            "mac_source_list": ("source-by-platform", "Mac"),
        }
        if input_name in source_names:
            field, selector = source_names[input_name]
            value, suffix = _select_cli_value(args.get(field), selector)
            return _scalar_derived(value, f"{args_base}/{field}{suffix}")
        shared_manifest_indexes = {
            "ambience_source_list": 0,
            "mission_source_list": 1,
        }
        if input_name in shared_manifest_indexes:
            if "source-by-platform" in args:
                value, suffix = _select_shared_cli_manifest(
                    args.get("source-by-platform"),
                    platforms=args.get("platform"),
                    manifest_index=shared_manifest_indexes[input_name],
                )
                return _scalar_derived(
                    value,
                    f"{args_base}/source-by-platform{suffix}",
                )
            value, suffix = _select_cli_value(
                args.get("source-file"),
                shared_manifest_indexes[input_name],
            )
            return _scalar_derived(value, f"{args_base}/source-file{suffix}")
        output_names = {
            "output_directory": "Windows",
            "windows_output_directory": "Windows",
            "mac_output_directory": "Mac",
        }
        if input_name in output_names:
            selector = output_names[input_name]
            value, suffix = _select_cli_value(args.get("output"), selector)
            return _scalar_derived(value, f"{args_base}/output{suffix}")
    if api == "ak.wwise.cli.generateSoundbank":
        if input_name == "output_directory":
            paths = _cli_platform_paths(args.get("soundbank-path"))
            if not paths:
                raise PromptProvenanceError("CLI SoundBank output paths are empty")
            common = os.path.commonpath(paths)
            return _DerivedInput(common, {"": args_base + "/soundbank-path"})
        if input_name in {"ui_definition_file", "gameplay_definition_file"}:
            index = 0 if input_name == "ui_definition_file" else 1
            value, suffix = _select_cli_value(
                args.get("import-definition-file"), index
            )
            return _scalar_derived(
                value, f"{args_base}/import-definition-file{suffix}"
            )
    if api == "ak.wwise.cli.tabDelimitedImport" and input_name == "project_path":
        return _scalar_derived(args.get("project"), args_base + "/project")
    if api == "ak.wwise.cli.migrate" and input_name == "project_path":
        return _scalar_derived(args.get("project"), args_base + "/project")
    raise PromptProvenanceError(f"no reviewed CLI provenance mapping for {api}/{input_name}")


def _protocol_requests(
    protocol_value: Mapping[str, Any],
    *,
    version: str | None = None,
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    steps = protocol_value.get("steps")
    if not isinstance(steps, list):
        raise PromptProvenanceError("protocol steps are unavailable")
    result: list[tuple[str, Mapping[str, Any]]] = []
    for step_index, step in enumerate(steps):
        if not isinstance(step, Mapping) or step.get("subcommand") != "preview":
            continue
        arguments = step.get("arguments")
        if not isinstance(arguments, list):
            raise PromptProvenanceError("preview request argument topology drifted")
        if (
            len(arguments) == 3
            and arguments[0] == {"kind": "literal", "value": "--apply"}
            and arguments[1]
            == {"kind": "literal", "value": "--request-json"}
        ):
            semantic_index = 2
        elif (
            len(arguments) == 2
            and arguments[0]
            == {"kind": "literal", "value": "--request-json"}
        ):
            semantic_index = 1
        else:
            raise PromptProvenanceError("preview request flag drifted")
        semantic = arguments[semantic_index]
        if not isinstance(semantic, Mapping):
            raise PromptProvenanceError("preview request manifest is invalid")
        semantic_kind = semantic.get("kind")
        if semantic_kind == "metadata_bound_json":
            expected_keys = {
                "kind",
                "value",
                "sha256",
                "equivalence",
                "metadata_step",
                "object_type",
                "required_tokens",
                "expected_required_token_projection",
                "gateway_derived_reference_activations",
            }
            legacy_expected_keys = expected_keys - {
                "gateway_derived_reference_activations"
            }
            projection = semantic.get("expected_required_token_projection")
            if (
                set(semantic) not in (expected_keys, legacy_expected_keys)
                or semantic.get("equivalence")
                not in {
                    "wire_exact",
                    "audio_import_v1",
                    "audio_import_tab_v1",
                    "object_set_v1",
                    "object_set_rtpc_v1",
                }
                or not isinstance(semantic.get("metadata_step"), str)
                or not semantic.get("metadata_step")
                or not isinstance(semantic.get("object_type"), str)
                or not semantic.get("object_type")
                or not isinstance(semantic.get("required_tokens"), list)
                or not semantic.get("required_tokens")
                or projection is not None
                and not isinstance(projection, list)
                or not isinstance(
                    semantic.get(
                        "gateway_derived_reference_activations",
                        [],
                    ),
                    list,
                )
            ):
                raise PromptProvenanceError(
                    "metadata-bound preview request manifest is invalid"
                )
        elif semantic_kind == _SEALED_QUERY_IDENTITY_JSON_KIND:
            if (
                set(semantic)
                != {
                    "kind",
                    "value",
                    "sha256",
                    "source_step",
                    "target_pointers",
                }
                or not isinstance(semantic.get("source_step"), str)
                or not semantic.get("source_step")
                or not isinstance(semantic.get("target_pointers"), list)
                or len(semantic["target_pointers"]) != 2
                or any(
                    not isinstance(pointer, str)
                    for pointer in semantic["target_pointers"]
                )
            ):
                raise PromptProvenanceError(
                    "sealed-query-identity preview request manifest is invalid"
                )
        elif (
            semantic_kind not in _SEMANTIC_JSON_EQUIVALENCE_BY_KIND
            or set(semantic) != {"kind", "value", "sha256"}
        ):
            raise PromptProvenanceError("preview request manifest is invalid")
        if (
            semantic.get("sha256") != _sha256_json(semantic.get("value"))
            or not isinstance(semantic.get("value"), Mapping)
        ):
            raise PromptProvenanceError("preview request manifest is invalid")
        request = semantic["value"]
        if set(request) != {"contract", "version", "operation", "arguments"}:
            raise PromptProvenanceError("operation request envelope is not closed")
        request_operation = request.get("operation")
        if semantic_kind == "metadata_bound_json":
            equivalence = semantic.get("equivalence")
            if (
                equivalence == "audio_import_v1"
                and request.get("operation") != "audio.import"
            ):
                raise PromptProvenanceError(
                    "metadata-bound request JSON equivalence contract is invalid"
                )
            if (
                equivalence == "audio_import_tab_v1"
                and request.get("operation")
                != "audio.importTabDelimited"
            ):
                raise PromptProvenanceError(
                    "metadata-bound request JSON equivalence contract is invalid"
                )
            if (
                equivalence == "object_set_v1"
                and request.get("operation") != "object.set"
            ):
                raise PromptProvenanceError(
                    "metadata-bound request JSON equivalence contract is invalid"
                )
            if (
                equivalence == "object_set_rtpc_v1"
                and request.get("operation") != "object.setRTPC"
            ):
                raise PromptProvenanceError(
                    "metadata-bound request JSON equivalence contract is invalid"
                )
        elif semantic_kind == _SEALED_QUERY_IDENTITY_JSON_KIND:
            if request.get("operation") != "object.set":
                raise PromptProvenanceError(
                    "sealed-query-identity request must be object.set"
                )
        else:
            equivalence = _SEMANTIC_JSON_EQUIVALENCE_BY_KIND[
                str(semantic_kind)
            ]
            if (
                equivalence != "wire_exact"
                and equivalence
                != operation_request_equivalence(str(request_operation))
                and not (
                    request_operation == "audio.import"
                    and equivalence
                    == "audio_import_default_operation_v1"
                )
            ):
                raise PromptProvenanceError(
                    "operation request JSON equivalence contract is invalid"
                )
        result.append(
            (
                f"/steps/{step_index}/arguments/{semantic_index}/value",
                request,
            )
        )
    if result:
        return tuple(result)
    protocol = deserialize_protocol(protocol_value)
    starts = [
        (index, step)
        for index, step in enumerate(protocol.steps)
        if step.subcommand == "draft-start"
        and step.arguments == ("audio.import",)
    ]
    previews = [
        (index, step)
        for index, step in enumerate(protocol.steps)
        if step.subcommand == "preview-from-draft"
    ]
    if not starts and not previews:
        return ()
    if version is None or len(starts) != 1 or len(previews) != 1:
        raise PromptProvenanceError(
            "Composer preview request topology or version binding drifted"
        )
    start_index, _start = starts[0]
    preview_index, preview = previews[0]
    if start_index >= preview_index:
        raise PromptProvenanceError("Composer preview precedes its draft start")
    try:
        request = materialize_audio_import_composer_protocol_request(
            protocol,
            version=version,
        )
    except V3ProtocolError as exc:
        raise PromptProvenanceError(
            "audio.import Composer provenance cannot materialize its request"
        ) from exc
    return ((f"/composer/{preview.name}", request),)


def _audio_import_composer_row_origins(
    protocol_value: Mapping[str, Any],
    rows: Sequence[Any],
) -> Mapping[str, str]:
    """Bind every visible import-row leaf to its exact typed action leaf."""

    steps = protocol_value.get("steps")
    if not isinstance(steps, list):
        raise PromptProvenanceError("protocol steps are unavailable")
    action_rows: list[tuple[int, int, Mapping[str, Any]]] = []
    for step_index, step in enumerate(steps):
        if not isinstance(step, Mapping) or step.get("subcommand") != "draft-apply":
            continue
        arguments = step.get("arguments")
        if not isinstance(arguments, list):
            raise PromptProvenanceError("draft-apply arguments are invalid")
        for argument_index, argument in enumerate(arguments):
            if (
                not isinstance(argument, Mapping)
                or argument.get("kind") != "draft_action_json"
                or argument.get("operation") != "audio.import"
            ):
                continue
            action = argument.get("value")
            if (
                isinstance(action, Mapping)
                and action.get("contract")
                == "waapi-skill.operation-draft-action/v1"
                and action.get("action")
                in {"add_import_row", "add_switch_assigned_import_row"}
            ):
                action_rows.append((step_index, argument_index, action))
    if len(action_rows) != len(rows):
        raise PromptProvenanceError(
            "audio.import visible rows differ from typed row actions"
        )
    origins: dict[str, str] = {}
    for row_index, (row, (step_index, argument_index, action)) in enumerate(
        zip(rows, action_rows, strict=True)
    ):
        if not isinstance(row, Mapping):
            raise PromptProvenanceError("audio.import visible row is invalid")
        action_fields = {
            key: value
            for key, value in action.items()
            if key not in {"contract", "action"}
        }
        if not _json_equal(action_fields, row):
            raise PromptProvenanceError(
                "audio.import visible row differs from its typed action"
            )
        for pointer, _leaf in _walk_leaves(row):
            origins[f"/{row_index}{pointer}"] = (
                f"/steps/{step_index}/arguments/{argument_index}/value{pointer}"
            )
    return origins


def _structured_derived(value: Any, base_pointer: str) -> _DerivedInput:
    if not isinstance(value, (list, Mapping)):
        raise PromptProvenanceError("reviewed structured source is not JSON")
    cloned = _json_clone(value)
    origins = {
        pointer: base_pointer + pointer for pointer, _ in _walk_leaves(cloned)
    }
    return _DerivedInput(_canonical_json_bytes(cloned).decode("utf-8"), origins)


def _scalar_derived(value: Any, pointer: str) -> _DerivedInput:
    if not isinstance(value, str) or not value:
        raise PromptProvenanceError("reviewed scalar source is not a non-empty string")
    return _DerivedInput(value, {"": pointer})


def _mapping_at(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(value.get(field), Mapping):
        raise PromptProvenanceError(f"reviewed {field} source is not an object")
    return value[field]


def _select_cli_value(value: Any, selector: str | int | None) -> tuple[str, str]:
    if selector is None:
        if not isinstance(value, str):
            raise PromptProvenanceError("CLI scalar path mapping is invalid")
        return value, ""
    if isinstance(selector, int):
        if not isinstance(value, list) or not 0 <= selector < len(value):
            raise PromptProvenanceError("CLI indexed path mapping is invalid")
        selected = value[selector]
        if not isinstance(selected, str):
            raise PromptProvenanceError("CLI indexed path is not a string")
        return selected, f"/{selector}"
    if not isinstance(value, list):
        raise PromptProvenanceError("CLI platform path mapping is invalid")
    if len(value) == 2 and all(isinstance(item, str) for item in value):
        if value[0] != selector:
            raise PromptProvenanceError(
                f"CLI platform {selector} path is not unique"
            )
        return value[1], "/1"
    rows = [
        (index, row)
        for index, row in enumerate(value)
        if isinstance(row, list) and len(row) == 2 and row[0] == selector
    ]
    if len(rows) != 1 or not isinstance(rows[0][1][1], str):
        raise PromptProvenanceError(f"CLI platform {selector} path is not unique")
    index, row = rows[0]
    return row[1], f"/{index}/1"


def _select_shared_cli_manifest(
    value: Any,
    *,
    platforms: Any,
    manifest_index: int,
) -> tuple[str, str]:
    if (
        not isinstance(platforms, list)
        or not platforms
        or any(not isinstance(platform, str) or not platform for platform in platforms)
        or len(set(platforms)) != len(platforms)
        or not isinstance(value, list)
    ):
        raise PromptProvenanceError("CLI shared-manifest platform mapping is invalid")
    grouped: dict[str, list[tuple[int, str]]] = {
        platform: [] for platform in platforms
    }
    for index, row in enumerate(value):
        if (
            not isinstance(row, list)
            or len(row) != 2
            or row[0] not in grouped
            or not isinstance(row[1], str)
            or not row[1]
        ):
            raise PromptProvenanceError(
                "CLI shared-manifest platform row is invalid"
            )
        grouped[row[0]].append((index, row[1]))
    lengths = {len(rows) for rows in grouped.values()}
    if (
        len(lengths) != 1
        or not lengths
        or manifest_index < 0
        or manifest_index >= next(iter(lengths))
    ):
        raise PromptProvenanceError(
            "CLI shared-manifest platform rows are incomplete"
        )
    selected = tuple(
        grouped[platform][manifest_index] for platform in platforms
    )
    paths = {path for _, path in selected}
    if len(paths) != 1:
        raise PromptProvenanceError(
            "CLI shared-manifest path differs across platforms"
        )
    first_index, first_path = selected[0]
    return first_path, f"/{first_index}/1"


def _cli_platform_paths(value: Any) -> list[str]:
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, str) for item in value)
    ):
        return [value[1]]
    if isinstance(value, list) and all(
        isinstance(row, list)
        and len(row) == 2
        and isinstance(row[1], str)
        for row in value
    ):
        return [row[1] for row in value]
    raise PromptProvenanceError("CLI SoundBank platform path mapping is invalid")


def _integration_workflow_id(scenario: OnlineScenario) -> str | None:
    candidates = tuple(
        value
        for value in (
            getattr(scenario, "workflow_id", None),
            getattr(scenario, "scenario_family", None),
        )
        if isinstance(value, str) and value in INTEGRATION_WORKFLOW_IDS
    )
    if not candidates:
        return None
    if len(set(candidates)) != 1:
        raise PromptProvenanceError(
            "integration workflow identity attributes disagree"
        )
    workflow_id = candidates[0]
    if scenario.api != INTEGRATION_PRIMARY_API[workflow_id]:
        raise PromptProvenanceError(
            "integration workflow primary API identity drifted"
        )
    return workflow_id


def _integration_visible_input_source(
    scenario: OnlineScenario,
    *,
    workflow_id: str,
    root: Path,
    values: Mapping[str, str],
    supplied: Mapping[str, Any],
    require_paths: bool,
    serialized: bool,
) -> dict[str, Any]:
    key = INTEGRATION_VISIBLE_INPUT_SOURCE
    if set(supplied) != {key}:
        raise PromptProvenanceError(
            "integration visible-input source is missing or not closed"
        )
    source = supplied[key]
    declarations = tuple(scenario.visible_inputs)
    expected_names = tuple(item.name for item in declarations)
    if len(expected_names) != len(set(expected_names)):
        raise PromptProvenanceError(
            "integration visible-input declarations are not unique"
        )

    archived_rows: Sequence[Any] | None = None
    if serialized:
        if not isinstance(source, Mapping) or set(source) != {
            "workflow_id",
            "inputs",
            "sha256",
        }:
            raise PromptProvenanceError(
                "sealed integration visible-input source schema is invalid"
            )
        if source.get("workflow_id") != workflow_id:
            raise PromptProvenanceError(
                "sealed integration visible-input workflow is misbound"
            )
        archived_rows = source.get("inputs")
        if (
            not isinstance(archived_rows, list)
            or len(archived_rows) != len(declarations)
        ):
            raise PromptProvenanceError(
                "sealed integration visible-input rows are incomplete"
            )
        raw_values: dict[str, str] = {}
        for index, (declared, row) in enumerate(
            zip(declarations, archived_rows, strict=True)
        ):
            if (
                not isinstance(row, Mapping)
                or row.get("name") != declared.name
                or row.get("kind") != declared.kind
                or not isinstance(row.get("value"), str)
            ):
                raise PromptProvenanceError(
                    "sealed integration visible-input identity drifted"
                )
            raw_values[declared.name] = str(row["value"])
    else:
        if not isinstance(source, Mapping):
            raise PromptProvenanceError(
                "integration_visible_inputs must be a mapping"
            )
        raw_values = dict(source)

    if (
        set(raw_values) != set(expected_names)
        or any(
            not isinstance(name, str) or not isinstance(value, str)
            for name, value in raw_values.items()
        )
        or raw_values != dict(values)
    ):
        raise PromptProvenanceError(
            "integration visible-input keys or values differ from "
            "visible_values"
        )

    rows = [
        _seal_integration_visible_input(
            declared,
            value=raw_values[declared.name],
            index=index,
            root=root,
            require_paths=require_paths,
            archived=(
                archived_rows[index]
                if archived_rows is not None
                else None
            ),
        )
        for index, declared in enumerate(declarations)
    ]
    sealed_value = {
        "workflow_id": workflow_id,
        "inputs": rows,
    }
    result = {
        key: {
            **sealed_value,
            "sha256": _sha256_json(sealed_value),
        }
    }
    if serialized and supplied != result:
        raise PromptProvenanceError(
            "sealed integration visible-input source was rewrapped"
        )
    return result


def _seal_integration_visible_input(
    declared: Any,
    *,
    value: str,
    index: int,
    root: Path,
    require_paths: bool,
    archived: Any,
) -> dict[str, Any]:
    if declared.kind not in INTEGRATION_VISIBLE_KINDS:
        raise PromptProvenanceError(
            f"integration prompt uses an unreviewed visible kind: "
            f"{declared.kind}"
    )
    value_bytes = value.encode("utf-8")
    value_ceiling = (
        MAX_INTEGRATION_STRUCTURED_BYTES
        if declared.kind == "structured_array"
        else MAX_INTEGRATION_SCALAR_BYTES
    )
    if (
        not value
        or b"\x00" in value_bytes
        or len(value_bytes) > value_ceiling
    ):
        raise PromptProvenanceError(
            f"integration visible input {declared.name} exceeds its "
            "bounded scalar contract"
        )

    canonical_json: Any = None
    if declared.kind == "structured_array":
        parsed = _strict_json_text(value)
        if (
            not isinstance(parsed, list)
            or not 1 <= len(parsed) <= MAX_INTEGRATION_ARRAY_ITEMS
        ):
            raise PromptProvenanceError(
                f"integration visible input {declared.name} must be a "
                "bounded non-empty JSON array"
            )
        if _canonical_json_bytes(parsed).decode("utf-8") != value:
            raise PromptProvenanceError(
                f"integration visible input {declared.name} is not "
                "canonical JSON"
            )
        leaves = tuple(_walk_leaves(parsed))
        if not leaves or len(leaves) > MAX_INTEGRATION_LEAVES:
            raise PromptProvenanceError(
                f"integration visible input {declared.name} has an "
                "invalid leaf count"
            )
        canonical_json = parsed
    elif declared.kind == "object_path":
        if (
            not value.startswith("\\")
            or "\n" in value
            or "\r" in value
        ):
            raise PromptProvenanceError(
                f"integration visible input {declared.name} is not a "
                "bounded Wwise object path"
            )
    elif declared.kind == "string":
        if "\n" in value or "\r" in value:
            raise PromptProvenanceError(
                f"integration visible input {declared.name} is not a "
                "bounded scalar string"
            )

    path_proof: dict[str, Any] | None = None
    if declared.kind == "absolute_directory_path":
        pointer = f"/inputs/{index}/value"
        expected_proof = {
            "pointer": pointer,
            **_path_proof(
                value,
                root=root,
                expected_kind="directory",
                require_exists=require_paths,
            ),
        }
        if archived is not None and not require_paths:
            actual_proof = (
                archived.get("path_proof")
                if isinstance(archived, Mapping)
                else None
            )
            if (
                not isinstance(actual_proof, Mapping)
                or set(actual_proof) != set(expected_proof)
            ):
                raise PromptProvenanceError(
                    "archived integration directory proof is invalid"
                )
            _validate_archived_path_proof(
                actual_proof,
                expected_kind="directory",
            )
            if (
                actual_proof.get("pointer") != pointer
                or actual_proof.get("owned_relative_path")
                != expected_proof["owned_relative_path"]
            ):
                raise PromptProvenanceError(
                    "archived integration directory proof is misbound"
                )
            path_proof = dict(actual_proof)
        else:
            path_proof = expected_proof

    row = {
        "name": declared.name,
        "kind": declared.kind,
        "value": value,
        "value_sha256": _sha256_text(value),
        "canonical_json": canonical_json,
        "path_proof": path_proof,
    }
    if archived is not None and dict(archived) != row:
        raise PromptProvenanceError(
            "sealed integration visible-input row was rewrapped"
        )
    return row


def _derive_integration_visible_input(
    scenario: OnlineScenario,
    *,
    workflow_id: str,
    input_name: str,
    trusted_sources: Mapping[str, Any],
) -> _DerivedInput:
    source = trusted_sources.get(INTEGRATION_VISIBLE_INPUT_SOURCE)
    if (
        not isinstance(source, Mapping)
        or source.get("workflow_id") != workflow_id
        or not isinstance(source.get("inputs"), list)
    ):
        raise PromptProvenanceError(
            "sealed integration visible-input source is unavailable"
        )
    declarations = tuple(scenario.visible_inputs)
    indexes = [
        index
        for index, declared in enumerate(declarations)
        if declared.name == input_name
    ]
    if len(indexes) != 1:
        raise PromptProvenanceError(
            f"integration visible input is not uniquely declared: {input_name}"
        )
    index = indexes[0]
    rows = source["inputs"]
    if index >= len(rows):
        raise PromptProvenanceError(
            "sealed integration visible-input rows are incomplete"
        )
    row = rows[index]
    declared = declarations[index]
    if (
        not isinstance(row, Mapping)
        or row.get("name") != input_name
        or row.get("kind") != declared.kind
        or not isinstance(row.get("value"), str)
    ):
        raise PromptProvenanceError(
            "sealed integration visible-input row is misbound"
        )
    value = str(row["value"])
    source_base = (
        f"/{INTEGRATION_VISIBLE_INPUT_SOURCE}/inputs/{index}"
    )
    if declared.kind == "structured_array":
        parsed = row.get("canonical_json")
        if not isinstance(parsed, list):
            raise PromptProvenanceError(
                "sealed integration structured input is unavailable"
            )
        origins = {
            pointer: source_base + "/canonical_json" + pointer
            for pointer, _ in _walk_leaves(parsed)
        }
    else:
        origins = {"": source_base + "/value"}
    return _DerivedInput(value, origins)


def _trusted_sources(
    scenario: OnlineScenario,
    *,
    root: Path,
    values: Mapping[str, str],
    protocol_value: Mapping[str, Any],
    supplied: Mapping[str, Any],
    require_paths: bool,
    serialized: bool = False,
) -> dict[str, Any]:
    del protocol_value
    workflow_id = _integration_workflow_id(scenario)
    if workflow_id is not None:
        return _integration_visible_input_source(
            scenario,
            workflow_id=workflow_id,
            root=root,
            values=values,
            supplied=supplied,
            require_paths=require_paths,
            serialized=serialized,
        )

    asset_spec = (
        scenario.fixture.get("asset_spec")
        if isinstance(scenario.fixture, Mapping)
        else None
    )
    is_compound_import = (
        scenario.api == "ak.wwise.core.audio.import"
        and isinstance(asset_spec, Mapping)
        and isinstance(asset_spec.get("compound"), Mapping)
    )
    if is_compound_import:
        return _compound_import_trusted_source(
            scenario,
            root=root,
            values=values,
            supplied=supplied,
            require_paths=require_paths,
            serialized=serialized,
        )
    if scenario.api != "ak.wwise.core.soundbank.generate":
        if supplied:
            raise PromptProvenanceError("unexpected trusted prompt source")
        return {}
    if set(supplied) != {"soundbank_generate_project_info"}:
        raise PromptProvenanceError("SoundBank generation project-info source is missing")
    source = supplied["soundbank_generate_project_info"]
    if serialized:
        if not isinstance(source, Mapping) or set(source) != {
            "value",
            "sha256",
            "path_proofs",
        }:
            raise PromptProvenanceError("SoundBank project-info source schema is invalid")
        projection = source.get("value")
    else:
        projection = source
    if not isinstance(projection, Mapping):
        raise PromptProvenanceError("SoundBank project-info projection is invalid")
    if set(projection) != {"path", "directories", "platforms"}:
        raise PromptProvenanceError("SoundBank project-info projection fields drifted")
    directories = projection.get("directories")
    platforms = projection.get("platforms")
    if (
        not isinstance(directories, Mapping)
        or set(directories) != {"cache"}
        or not isinstance(platforms, list)
        or not platforms
        or any(
            not isinstance(row, Mapping)
            or set(row) != {"name", "soundBankPath", "copiedMediaPath"}
            or not isinstance(row.get("name"), str)
            or not row.get("name")
            for row in platforms
        )
    ):
        raise PromptProvenanceError("SoundBank project-info projection is not closed")
    paths: list[tuple[str, str, str]] = [
        ("/value/path", str(projection.get("path")), "file"),
        ("/value/directories/cache", str(directories.get("cache")), "directory"),
    ]
    for index, row in enumerate(platforms):
        paths.extend(
            (
                (
                    f"/value/platforms/{index}/soundBankPath",
                    str(row.get("soundBankPath")),
                    "directory",
                ),
                (
                    f"/value/platforms/{index}/copiedMediaPath",
                    str(row.get("copiedMediaPath")),
                    "directory",
                ),
            )
        )
    if serialized and not require_paths:
        raw_proofs = source.get("path_proofs")
        if not isinstance(raw_proofs, list) or len(raw_proofs) != len(paths):
            raise PromptProvenanceError("SoundBank project-info path proofs are incomplete")
        proofs = []
        for actual, (pointer, path, kind) in zip(raw_proofs, paths, strict=True):
            expected = {
                "pointer": pointer,
                **_path_proof(
                    path,
                    root=root,
                    expected_kind=kind,
                    require_exists=False,
                ),
            }
            if not isinstance(actual, Mapping) or set(actual) != set(expected):
                raise PromptProvenanceError("SoundBank project-info path proof is invalid")
            _validate_archived_path_proof(actual, expected_kind=kind)
            if (
                actual.get("pointer") != pointer
                or actual.get("owned_relative_path")
                != expected["owned_relative_path"]
            ):
                raise PromptProvenanceError("SoundBank project-info path proof is misbound")
            proofs.append(dict(actual))
    else:
        proofs = [
            {
                "pointer": pointer,
                **_path_proof(
                    path,
                    root=root,
                    expected_kind=kind,
                    require_exists=require_paths,
                ),
            }
            for pointer, path, kind in paths
        ]
    expected_build = _canonical_json_bytes(
        render_soundbank_generation_build_locations(
            projection,
            io_root=root / "owned",
        )
    ).decode("utf-8")
    if values.get("build_locations") != expected_build:
        raise PromptProvenanceError(
            "SoundBank build_locations is not reproducible from project info"
        )
    result = {
        "soundbank_generate_project_info": {
            "value": _json_clone(projection),
            "sha256": _sha256_json(projection),
            "path_proofs": proofs,
        }
    }
    if serialized and supplied != result:
        raise PromptProvenanceError("SoundBank project-info proof was rewrapped")
    return result


def _compound_import_trusted_source(
    scenario: OnlineScenario,
    *,
    root: Path,
    values: Mapping[str, str],
    supplied: Mapping[str, Any],
    require_paths: bool,
    serialized: bool,
) -> dict[str, Any]:
    key = "compound_import_visible_rows"
    if set(supplied) != {key}:
        raise PromptProvenanceError(
            "compound import visible-row source is missing"
        )
    source = supplied[key]
    if serialized:
        if not isinstance(source, Mapping) or set(source) != {
            "value",
            "sha256",
            "path_proofs",
        }:
            raise PromptProvenanceError(
                "compound import visible-row source schema is invalid"
            )
        value = source.get("value")
    else:
        value = source
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 64
        or any(not isinstance(row, Mapping) for row in value)
        or _canonical_json_bytes(value).decode("utf-8")
        != values.get("import_rows")
    ):
        raise PromptProvenanceError(
            "compound import visible rows differ from the rendered prompt"
        )
    paths = [
        (pointer, leaf)
        for pointer, leaf in _walk_leaves(value)
        if isinstance(leaf, str) and os.path.isabs(leaf)
    ]
    if serialized and not require_paths:
        raw_proofs = source.get("path_proofs")
        if not isinstance(raw_proofs, list) or len(raw_proofs) != len(paths):
            raise PromptProvenanceError(
                "compound import visible-row path proofs are incomplete"
            )
        proofs: list[dict[str, Any]] = []
        for actual, (pointer, path) in zip(raw_proofs, paths, strict=True):
            expected = {
                "pointer": f"/value{pointer}",
                **_path_proof(
                    path,
                    root=root,
                    expected_kind=_expected_leaf_path_kind(
                        scenario,
                        input_name="import_rows",
                        input_kind="structured_array",
                        pointer=pointer,
                    ),
                    require_exists=False,
                ),
            }
            if not isinstance(actual, Mapping) or set(actual) != set(expected):
                raise PromptProvenanceError(
                    "compound import visible-row path proof is invalid"
                )
            _validate_archived_path_proof(
                actual,
                expected_kind=expected["path_kind"],
            )
            if (
                actual.get("pointer") != expected["pointer"]
                or actual.get("owned_relative_path")
                != expected["owned_relative_path"]
            ):
                raise PromptProvenanceError(
                    "compound import visible-row path proof is misbound"
                )
            proofs.append(dict(actual))
    else:
        proofs = [
            {
                "pointer": f"/value{pointer}",
                **_path_proof(
                    path,
                    root=root,
                    expected_kind=_expected_leaf_path_kind(
                        scenario,
                        input_name="import_rows",
                        input_kind="structured_array",
                        pointer=pointer,
                    ),
                    require_exists=require_paths,
                ),
            }
            for pointer, path in paths
        ]
    result = {
        key: {
            "value": _json_clone(value),
            "sha256": _sha256_json(value),
            "path_proofs": proofs,
        }
    }
    if serialized and supplied != result:
        raise PromptProvenanceError(
            "compound import visible-row source was rewrapped"
        )
    return result


def _build_location_source_pointer(pointer: str) -> str:
    parts = _pointer_parts(pointer)
    if parts == ("project",):
        return "/soundbank_generate_project_info/value/path"
    if parts == ("cache",):
        return "/soundbank_generate_project_info/value/directories/cache"
    if len(parts) == 3 and parts[0] == "platforms" and parts[1].isdigit():
        field = parts[2]
        if field in {"name", "soundBankPath", "copiedMediaPath"}:
            return (
                "/soundbank_generate_project_info/value/platforms/"
                f"{parts[1]}/{_escape_pointer(field)}"
            )
    raise PromptProvenanceError(
        f"unreviewed SoundBank build_locations leaf: {pointer}"
    )


def _enforce_fixed_path(
    api: str,
    name: str,
    proof: Mapping[str, Any],
    *,
    root: Path,
) -> None:
    relative = proof["owned_relative_path"]
    if api == "ak.wwise.cli.migrate" and name == "project_path":
        if relative != "case/project/SampleProject.wproj":
            raise PromptProvenanceError("migrate project_path is not the fixed owned target")
    if api == "ak.wwise.core.audio.convert" and name == "io_root":
        if relative != "io":
            raise PromptProvenanceError("audio.convert io_root is not owned/io")
    if api == "ak.wwise.core.audio.import" and name == "media_directory":
        if relative != "assets/import-case/sources":
            raise PromptProvenanceError("audio.import media_directory drifted")
    if api == "ak.wwise.core.soundbank.processDefinitionFiles" and name == "io_root":
        if relative != ".":
            raise PromptProvenanceError("SoundBank definition io_root is not owned root")
    del root


def _path_proof(
    value: str,
    *,
    root: Path,
    expected_kind: str | None,
    require_exists: bool,
) -> dict[str, Any]:
    owned = root / "owned"
    candidate = Path(value).expanduser()
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise PromptProvenanceError("case-owned prompt path is not absolute/normalized")
    lexical = Path(os.path.abspath(os.fspath(candidate)))
    try:
        relative = lexical.relative_to(owned)
    except ValueError as exc:
        raise PromptProvenanceError("prompt path escapes scenario_root/owned") from exc
    relative_text = relative.as_posix() or "."
    if relative_text.startswith("../") or PurePosixPath(relative_text).is_absolute():
        raise PromptProvenanceError("prompt path has an unsafe owned-relative form")
    if not require_exists:
        if expected_kind not in {None, "file", "directory"}:
            raise PromptProvenanceError("prompt path expected kind is invalid")
        return {
            "path_kind": expected_kind or "",
            "owned_relative_path": relative_text,
            "size": 0,
            "sha256": "0" * 64,
            "mtime_ns": 0,
        }
    _assert_no_symlink_path(lexical, stop=owned)
    try:
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(owned.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise PromptProvenanceError("prompt path is not a real owned path") from exc
    metadata = resolved.stat()
    if stat.S_ISREG(metadata.st_mode):
        kind = "file"
        size = metadata.st_size
        if size > MAX_PROOF_BYTES:
            raise PromptProvenanceError("prompt input file exceeds proof ceiling")
        digest = _sha256_regular_file(resolved)
    elif stat.S_ISDIR(metadata.st_mode):
        kind = "directory"
        size, digest = _directory_digest(resolved)
    else:
        raise PromptProvenanceError("prompt path is not a regular file/directory")
    if expected_kind is not None and kind != expected_kind:
        raise PromptProvenanceError(
            f"prompt path kind {kind} differs from declared {expected_kind}"
        )
    return {
        "path_kind": kind,
        "owned_relative_path": relative_text,
        "size": size,
        "sha256": digest,
        "mtime_ns": metadata.st_mtime_ns,
    }


def _directory_digest(root: Path) -> tuple[int, str]:
    rows: list[list[Any]] = []
    total = 0
    count = 0
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in sorted((*directories, *files)):
            candidate = current_path / name
            if candidate.is_symlink():
                raise PromptProvenanceError("directory proof contains a symlink")
        directories.sort()
        files.sort()
        for name in files:
            path = current_path / name
            metadata = path.stat()
            if not stat.S_ISREG(metadata.st_mode):
                raise PromptProvenanceError("directory proof contains a non-regular file")
            count += 1
            total += metadata.st_size
            if count > MAX_PROOF_FILES or total > MAX_PROOF_BYTES:
                raise PromptProvenanceError("directory proof exceeds its bounded ceiling")
            rows.append(
                [
                    path.relative_to(root).as_posix(),
                    metadata.st_size,
                    _sha256_regular_file(path),
                ]
            )
    return total, _sha256_json(rows)


def _assert_no_symlink_path(path: Path, *, stop: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise PromptProvenanceError("prompt path or ancestor is a symlink")
        if current == stop:
            return
        parent = current.parent
        if parent == current:
            raise PromptProvenanceError("prompt path is outside its owned root")
        current = parent


def _validate_archived_path_binding(
    actual: Any,
    derived: Mapping[str, Any],
) -> None:
    if not isinstance(actual, Mapping) or set(actual) != set(derived):
        raise PromptProvenanceError("archived prompt path binding schema is invalid")
    for key in (
        "pointer",
        "value_sha256",
        "origin_kind",
        "origin_pointer",
        "owned_relative_path",
    ):
        if actual.get(key) != derived.get(key):
            raise PromptProvenanceError("archived prompt path binding was rewrapped")
    expected_kind = derived.get("path_kind")
    if expected_kind not in {"file", "directory"}:
        raise PromptProvenanceError("reviewed prompt path kind is unavailable")
    _validate_archived_path_proof(actual, expected_kind=str(expected_kind))


def _expected_leaf_path_kind(
    scenario: OnlineScenario,
    *,
    input_name: str,
    input_kind: str,
    pointer: str,
) -> str:
    if input_kind == "absolute_file_path":
        return "file"
    if input_kind == "absolute_directory_path":
        return "directory"
    reviewed: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {
        ("ak.wwise.core.audio.import", "import_rows"): (
            ("/audio_file", "file"),
        ),
        (
            "ak.wwise.core.audio.importTabDelimited",
            "language_import_files",
        ): (("/file", "file"),),
        (
            "ak.wwise.core.soundbank.convertExternalSources",
            "source_jobs",
        ): (("/input", "file"), ("/output", "directory")),
        (
            "ak.wwise.core.soundbank.generate",
            "generation_request",
        ): (("/io_root", "directory"),),
        (
            "ak.wwise.core.soundbank.processDefinitionFiles",
            "definition_files",
        ): (("", "file"),),
    }
    matches = [
        kind
        for suffix, kind in reviewed.get((scenario.api, input_name), ())
        if pointer.endswith(suffix)
    ]
    if len(matches) != 1:
        raise PromptProvenanceError(
            f"absolute structured leaf lacks a reviewed file kind: "
            f"{scenario.api}/{input_name}{pointer}"
        )
    return matches[0]


def _validate_archived_path_proof(
    value: Mapping[str, Any],
    *,
    expected_kind: str | None,
) -> None:
    kind = value.get("path_kind")
    relative = value.get("owned_relative_path")
    size = value.get("size")
    digest = value.get("sha256")
    mtime_ns = value.get("mtime_ns")
    if (
        kind not in {"file", "directory"}
        or (expected_kind is not None and kind != expected_kind)
        or not isinstance(relative, str)
        or not relative
        or PurePosixPath(relative).is_absolute()
        or ".." in PurePosixPath(relative).parts
        or type(size) is not int
        or size < 0
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or type(mtime_ns) is not int
        or mtime_ns <= 0
    ):
        raise PromptProvenanceError("archived prompt path proof fields are invalid")


def _visible_values(
    scenario: OnlineScenario,
    values: Mapping[str, str],
) -> dict[str, str]:
    result = dict(values)
    expected = [item.name for item in scenario.visible_inputs]
    if set(result) != set(expected) or any(
        not isinstance(key, str) or not isinstance(value, str) or not value
        for key, value in result.items()
    ):
        raise PromptProvenanceError("visible values differ from the frozen declarations")
    return {name: result[name] for name in expected}


def _expected_prompts(
    scenario: OnlineScenario,
    values: Mapping[str, str],
    supplied: Sequence[str] | None,
    *,
    protocol: V3GatewayProtocol,
) -> tuple[str, ...]:
    request = scenario.render_prompt(values)
    if not isinstance(request, str) or not request.strip():
        raise PromptProvenanceError("initial prompt must be non-empty")
    explicit_follow_ups = _explicit_follow_up_prompts(scenario)
    if explicit_follow_ups is not None:
        expected_follow_up_count = len(protocol.turn_prefix_counts) - 1
        if len(explicit_follow_ups) != expected_follow_up_count:
            raise PromptProvenanceError(
                "explicit follow-up prompt count differs from the closed "
                "protocol turn boundaries"
            )
        if scenario.scenario_family in INTEGRATION_V2_WORKFLOW_IDS:
            explicit_follow_ups = tuple(
                prompt.format_map(values) for prompt in explicit_follow_ups
            )
        expected = (request, *explicit_follow_ups)
    else:
        policy = _modification_policy_for_protocol(protocol)
        if policy == "read_only":
            from tests.semantic.support.codex_modification_policy_v3 import (
                READ_ONLY_FOLLOW_UP_PROMPT,
            )

            expected = (request, READ_ONLY_FOLLOW_UP_PROMPT)
        elif policy == "allow_changes":
            expected = (request,)
        else:
            count = 1 + scenario.confirmation_turn_count
            if count == 1:
                expected = (request,)
            else:
                confirmation = scenario.confirmation_prompt
                if not isinstance(confirmation, str) or not confirmation.strip():
                    raise PromptProvenanceError("confirmation prompt is missing")
                expected = (request, *((confirmation,) * (count - 1)))
    if supplied is not None:
        supplied_prompts = _nonempty_prompt_sequence(
            supplied,
            label="in-memory prompts",
        )
        if len(supplied_prompts) != len(expected):
            raise PromptProvenanceError(
                "in-memory prompt count differs from the frozen scenario"
            )
        if supplied_prompts != expected:
            raise PromptProvenanceError(
                "in-memory prompts differ from the frozen scenario"
            )
    return expected


def _explicit_follow_up_prompts(
    scenario: OnlineScenario,
) -> tuple[str, ...] | None:
    raw = getattr(scenario, "follow_up_prompts", None)
    if raw is None:
        return None
    return _nonempty_prompt_sequence(raw, label="explicit follow-up prompts")


def _nonempty_prompt_sequence(
    value: Sequence[str],
    *,
    label: str,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PromptProvenanceError(f"{label} must be a prompt sequence")
    prompts = tuple(value)
    if any(not isinstance(prompt, str) or not prompt.strip() for prompt in prompts):
        raise PromptProvenanceError(f"{label} must contain only non-empty prompts")
    return prompts


def _modification_policy_for_protocol(
    protocol: V3GatewayProtocol,
) -> str | None:
    previews = tuple(
        step for step in protocol.steps if step.subcommand == "preview"
    )
    if not previews:
        if (
            protocol.turn_prefix_counts == (1, 1)
            and protocol.allowed_turn_prefix_counts == ((1,), (1,))
            and protocol.terminal_prefix_counts == (1,)
            and len(protocol.steps) == 1
            and protocol.steps[0].subcommand == "operation-schema"
        ):
            return "read_only"
        return None
    if len(previews) != 1 or previews[0].arguments[:1] != ("--apply",):
        return None
    preview = previews[0]
    if (
        len(preview.arguments) == 3
        and preview.arguments[1] == "--request-json"
        and isinstance(preview.arguments[2], MetadataBoundJsonArgument)
    ):
        # A metadata-bound transaction is an ordinary ask-before-changes
        # protocol with one supporting read.  It is not one of the special
        # modification-policy topologies rederived below.
        return None
    if (
        len(preview.arguments) != 3
        or preview.arguments[1] != "--request-json"
        or not isinstance(preview.arguments[2], SemanticJsonArgument)
        or not isinstance(preview.arguments[2].expected, Mapping)
    ):
        raise PromptProvenanceError(
            "modification-policy preview request topology is invalid"
        )
    try:
        base = build_transaction_protocol([preview.arguments[2].expected])
        matches = tuple(
            policy
            for policy in ("ask_before_changes", "allow_changes")
            if protocol
            == build_modification_policy_protocol(base, policy=policy)
        )
    except (TypeError, ValueError) as exc:
        raise PromptProvenanceError(
            f"modification-policy protocol cannot be rederived: {exc}"
        ) from exc
    return matches[0] if len(matches) == 1 else None


def _scenario_root(path: Path, *, require_exists: bool) -> Path:
    raw = Path(path).expanduser()
    root = Path(os.path.abspath(os.fspath(raw)))
    if raw.is_symlink() or root.is_symlink():
        raise PromptProvenanceError("scenario root must not be a symlink")
    if require_exists and not root.is_dir():
        raise PromptProvenanceError("scenario root must be an existing directory")
    evidence = root / "evidence"
    if require_exists and (evidence.is_symlink() or not evidence.is_dir()):
        raise PromptProvenanceError("scenario evidence root is not a real directory")
    return root


def _walk_leaves(value: Any, pointer: str = ""):
    if isinstance(value, Mapping):
        for key in sorted(value):
            yield from _walk_leaves(
                value[key], pointer + "/" + _escape_pointer(str(key))
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_leaves(item, pointer + f"/{index}")
        return
    yield pointer, value


def _first_leaf_pointer(value: Any, expected: Any) -> str | None:
    matches = [pointer for pointer, leaf in _walk_leaves(value) if _json_equal(leaf, expected)]
    return min(matches) if matches else None


def _json_equal(left: Any, right: Any) -> bool:
    return type(left) is type(right) and _canonical_json_bytes(left) == _canonical_json_bytes(right)


def _json_pointer(value: Any, pointer: str) -> Any:
    current = value
    for part in _pointer_parts(pointer):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise PromptProvenanceError(f"provenance pointer does not resolve: {pointer}")
    return current


def _pointer_parts(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise PromptProvenanceError("provenance pointer is not RFC 6901")
    return tuple(
        part.replace("~1", "/").replace("~0", "~")
        for part in pointer[1:].split("/")
    )


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _strict_json_text(value: str) -> Any:
    try:
        return json.loads(
            value,
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise PromptProvenanceError(f"structured prompt value is invalid JSON: {exc}") from exc


def _read_one_json(path: Path) -> tuple[bytes, Any]:
    flags = binary_file_open_flags(os.O_RDONLY)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PromptProvenanceError(f"cannot open prompt provenance: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_PROVENANCE_BYTES:
            raise PromptProvenanceError("prompt provenance is not one bounded regular file")
        raw = os.read(descriptor, MAX_PROVENANCE_BYTES + 1)
        if len(raw) != metadata.st_size:
            raise PromptProvenanceError("prompt provenance changed during its single read")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PromptProvenanceError(f"prompt provenance JSON is invalid: {exc}") from exc
    return raw, value


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical_json_bytes(value) + b"\n"
    flags = binary_file_open_flags(os.O_WRONLY, os.O_CREAT, os.O_EXCL)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise PromptProvenanceError("prompt provenance write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _closed_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON value: {value}")


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            _plain_json(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PromptProvenanceError(f"value is not canonical JSON: {exc}") from exc


def _json_clone(value: Any) -> Any:
    return json.loads(_canonical_json_bytes(value).decode("utf-8"))


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_regular_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "HEAVY_APIS",
    "MAX_PROVENANCE_BYTES",
    "PROMPT_MATERIALIZATION_RECEIPT_CONTRACT",
    "PROMPT_MATERIALIZATION_RECEIPT_FILE",
    "PROMPT_PROVENANCE_CONTRACT",
    "PROMPT_PROVENANCE_FILE",
    "PromptProvenanceError",
    "PromptProvenanceEvidence",
    "deserialize_protocol",
    "prompt_materialization_receipt",
    "read_prompt_provenance",
    "serialize_protocol",
    "write_prompt_provenance",
]
