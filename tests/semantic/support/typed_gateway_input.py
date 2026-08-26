"""Execute the existing typed V3 construction protocol in trusted test code.

This adapter deliberately stops at the immutable Preview.  The destructive
callers retain ownership of confirmation, execution, verification, and business
readback assertions while sharing the exact typed construction grammar used by
the semantic Broker and its live fixture lifecycle.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tests.semantic.support.codex_eval_protocol_v3 import (
    OBJECT_LIFECYCLE_BUSINESS_OPERATIONS,
    build_transaction_protocol,
    wait_topic_step,
)
from tests.semantic.support.codex_gateway_broker import (
    DraftTypedActionArgument,
    DraftTypedActionBatchArgument,
    ExpectedGatewayStep,
    InlineTypedOperationArgument,
    ResponseBinding,
    TypedRequestFactsArgument,
)
from wwise_waapi.operation_composer import typed_action_cli_arguments
from wwise_waapi.typed_operations import inline_operation_cli_arguments
from wwise_waapi.typed_requests import (
    TypedRequestFact,
    typed_request_construction_for_values,
)


GatewayCall = Callable[[Sequence[str]], Mapping[str, Any]]
def create_object_lifecycle_business_preview(
    gateway: GatewayCall,
    *,
    version: str,
    operation: str,
    object_id: str,
    parent_id: str | None = None,
    new_name: str | None = None,
    notes: str | None = None,
    name_conflict: str | None = None,
    auto_add_to_source_control: bool | None = None,
    auto_check_out_to_source_control: bool | None = None,
) -> dict[str, Any]:
    """Close test parameters and use the sole typed/business Preview executor."""

    if operation not in OBJECT_LIFECYCLE_BUSINESS_OPERATIONS:
        raise ValueError("operation has no object-lifecycle Business Adapter")
    fields = {
        "parent_id": parent_id,
        "new_name": new_name,
        "notes": notes,
        "name_conflict": name_conflict,
        "auto_add_to_source_control": auto_add_to_source_control,
        "auto_check_out_to_source_control": auto_check_out_to_source_control,
    }
    required = {
        "object.copy": {"parent_id"},
        "object.delete": set(),
        "object.move": {"parent_id"},
        "object.setName": {"new_name"},
        "object.setNotes": {"notes"},
    }[operation]
    allowed = {
        "object.copy": {
            "parent_id",
            "name_conflict",
            "auto_add_to_source_control",
            "auto_check_out_to_source_control",
        },
        "object.delete": {"auto_check_out_to_source_control"},
        "object.move": {
            "parent_id",
            "name_conflict",
            "auto_check_out_to_source_control",
        },
        "object.setName": {"new_name"},
        "object.setNotes": {"notes"},
    }[operation]
    supplied = {name for name, value in fields.items() if value is not None}
    if not required.issubset(supplied) or supplied - allowed:
        raise ValueError("business fields do not match the object lifecycle operation")

    arguments: dict[str, Any] = {
        "object": {"kind": "id", "value": object_id}
    }
    if parent_id is not None:
        arguments["parent"] = {"kind": "id", "value": parent_id}
    if new_name is not None:
        arguments["value"] = new_name
    if notes is not None:
        arguments["value"] = notes
    if name_conflict is not None:
        arguments["on_name_conflict"] = name_conflict
    if auto_add_to_source_control is not None:
        arguments["auto_add_to_source_control"] = auto_add_to_source_control
    if auto_check_out_to_source_control is not None:
        arguments["auto_check_out_to_source_control"] = (
            auto_check_out_to_source_control
        )
    return create_typed_transaction_preview(
        gateway,
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": version,
            "operation": operation,
            "arguments": arguments,
        },
    )


def create_object_metadata_business_preview(
    gateway: GatewayCall,
    *,
    version: str,
    operation: str,
    object_id: str,
    field_name: str,
    value: Any = None,
    target_id: str | None = None,
    clear_reference: bool = False,
    platform: str | None = None,
    linked: bool | None = None,
) -> dict[str, Any]:
    """Exercise the public field-discovery Business Draft through Preview."""

    if operation not in {
        "object.setLinked",
        "object.setProperty",
        "object.setReference",
    }:
        raise ValueError("operation has no object-metadata Business Adapter")
    arguments: dict[str, Any] = {
        "object": {"kind": "id", "value": object_id},
    }
    if operation == "object.setProperty":
        if target_id is not None or clear_reference or linked is not None:
            raise ValueError("property business fields are inconsistent")
        arguments.update({"property": field_name, "value": value})
    elif operation == "object.setReference":
        if linked is not None or (target_id is None) == (not clear_reference):
            raise ValueError("reference requires exactly one target or clear")
        arguments.update(
            {
                "reference": field_name,
                "target": (
                    {"kind": "id", "value": target_id}
                    if target_id is not None
                    else None
                ),
            }
        )
    else:
        if linked is None or platform is None or target_id is not None or clear_reference:
            raise ValueError("link state requires platform and linked only")
        arguments.update(
            {
                "property": field_name,
                "platform": platform,
                "linked": linked,
            }
        )
    if platform is not None and operation != "object.setLinked":
        arguments["platform"] = platform
    return create_typed_transaction_preview(
        gateway,
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": version,
            "operation": operation,
            "arguments": arguments,
        },
    )


def create_typed_transaction_preview(
    gateway: GatewayCall,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Follow the existing public typed protocol through its one Preview."""

    protocol = build_transaction_protocol((request,))
    responses: dict[str, Mapping[str, Any]] = {}
    preview: dict[str, Any] | None = None
    previous: tuple[ExpectedGatewayStep, Mapping[str, Any]] | None = None
    operation_schema: Mapping[str, Any] | None = None
    pending_container_actions: list[list[str]] = []
    for step in protocol.steps:
        command = [step.subcommand, *_render_step_arguments(step, responses)]
        if command[0] in {"request-map-container", "request-array-item"}:
            if "--schema-digest" in command:
                _require_container_disclosure(operation_schema, command)
            elif previous is not None:
                _require_nested_container_disclosure(previous[1], command)
            else:
                raise AssertionError("nested container command has no disclosure source")
        elif previous is not None:
            _require_disclosed_continuation(
                previous[0],
                previous[1],
                command,
                pending_container_actions=pending_container_actions,
            )
        payload = dict(gateway(command))
        responses[step.name] = payload
        if step.subcommand == "operation-schema":
            operation_schema = payload
        if step.subcommand in {"request-map-container", "request-array-item"}:
            action = _container_action(payload)
            if action is not None:
                pending_container_actions.append(action)
        if step.name == "tx01.preview":
            if pending_container_actions:
                raise AssertionError("not every disclosed container fact was consumed")
            _require_preview_continuation(payload)
            preview = payload
            break
        previous = (step, payload)
    if preview is None:
        raise AssertionError("typed transaction protocol did not produce one Preview")
    return preview


def _require_container_disclosure(
    operation_schema: Mapping[str, Any] | None,
    command: Sequence[str],
) -> None:
    composer = operation_schema.get("composer") if isinstance(operation_schema, Mapping) else None
    dynamic = composer.get("dynamic_container_commands") if isinstance(composer, Mapping) else None
    expected = (
        dynamic.get("map_value")
        if command[0] == "request-map-container" and isinstance(dynamic, Mapping)
        else dynamic.get("array_item")
        if isinstance(dynamic, Mapping)
        else None
    )
    if expected != command[0] or dynamic.get("schema_digest") != command[3]:
        raise AssertionError("operation-schema did not disclose exact dynamic container construction")


def _require_nested_container_disclosure(
    payload: Mapping[str, Any],
    command: Sequence[str],
) -> None:
    if not _contains_disclosed_argv(
        payload,
        command,
        payload=payload,
    ):
        raise AssertionError("container response did not disclose exact nested construction")


def _contains_disclosed_argv(
    value: Any,
    command: Sequence[str],
    *,
    payload: Mapping[str, Any],
) -> bool:
    if isinstance(value, list):
        if _argv_template_matches(value, command, payload=payload):
            return True
        return any(
            _contains_disclosed_argv(item, command, payload=payload)
            for item in value
        )
    if isinstance(value, Mapping):
        return any(
            _contains_disclosed_argv(item, command, payload=payload)
            for item in value.values()
        )
    return False


def _argv_template_matches(
    template: Sequence[Any],
    command: Sequence[str],
    *,
    payload: Mapping[str, Any],
) -> bool:
    if len(template) != len(command) or any(not isinstance(item, str) for item in template):
        return False
    choice_handles = {
        str(node["handle"])
        for node in _mapping_nodes(payload.get("child_contract", {}))
        if isinstance(node.get("handle"), str)
    }
    for expected, actual in zip(template, command, strict=True):
        if expected == "<exact-key>":
            if not actual:
                return False
        elif expected == "<selected-choice-handle-from-child_contract>":
            if actual not in choice_handles:
                return False
        elif expected != actual:
            return False
    return True


def _require_disclosed_continuation(
    previous_step: ExpectedGatewayStep,
    payload: Mapping[str, Any],
    command: Sequence[str],
    pending_container_actions: list[list[str]],
) -> None:
    """Prove each real command follows the preceding public Gateway result."""

    matched_container_action = False
    if command[0] == "draft-apply" and pending_container_actions:
        try:
            action_offset = command.index("--action")
        except ValueError as exc:
            raise AssertionError("container continuation was not applied as a typed action") from exc
        for index, expected_action in enumerate(pending_container_actions):
            if command[action_offset : action_offset + len(expected_action)] == expected_action:
                pending_container_actions.pop(index)
                matched_container_action = True
                break

    if previous_step.subcommand == "operation-schema":
        if command[0] == "typed-operation":
            typed = payload.get("typed_operation")
            continuation = typed.get("continuation") if isinstance(typed, Mapping) else None
            if not isinstance(continuation, Mapping) or continuation.get("subcommand") != command[0]:
                raise AssertionError("operation-schema did not disclose typed-operation")
            if continuation.get("operation") != command[1]:
                raise AssertionError("typed-operation continuation changed operation identity")
            return
        starts = [
            adapter.get("start")
            for key in ("business_adapter", "composer")
            if isinstance((adapter := payload.get(key)), Mapping)
            and isinstance(adapter.get("start"), Mapping)
        ]
        disclosed_start: Any = None
        if len(starts) == 1:
            next_command = starts[0].get("next_command")
            disclosed_start = (
                next_command.get("gateway_argv")
                if isinstance(next_command, Mapping)
                else starts[0].get("gateway_argv")
            )
        if disclosed_start != list(command):
            raise AssertionError("operation-schema did not disclose the exact draft-start")
        return

    if _business_copy_binding_was_used(payload, command):
        return

    if command[0] == "draft-apply":
        if previous_step.subcommand in {"request-map-container", "request-array-item"}:
            if not matched_container_action:
                # The protocol may compose an independent scalar fact before a
                # previously disclosed container fact. Its authority/revision
                # still come from draft-start and are checked by Gateway.
                return
            return
        draft = payload.get("draft")
        binding = draft.get("next_action_binding") if isinstance(draft, Mapping) else None
        prefix = binding.get("fixed_argv_prefix") if isinstance(binding, Mapping) else None
        gateway_prefix = prefix[3:] if isinstance(prefix, list) else None
        if isinstance(gateway_prefix, list):
            gateway_prefix = [
                command[index]
                if value == "<task-authority-from-draft-start>"
                else value
                for index, value in enumerate(gateway_prefix)
            ]
        if (
            not isinstance(gateway_prefix, list)
            or list(command[: len(gateway_prefix)]) != gateway_prefix
        ):
            raise AssertionError("Draft response did not bind the exact next action prefix")
        if list(command[len(gateway_prefix) : len(gateway_prefix) + 1]) != ["--action"]:
            raise AssertionError("Draft response did not bind one typed action")
        return

    if command[0] == "draft-check":
        draft = payload.get("draft")
        if not isinstance(draft, Mapping):
            raise AssertionError("Draft response did not disclose its revision")
        if (
            command[1] != draft.get("draft_id")
            or command[-2:] != ["--expected-revision", str(draft.get("revision"))]
        ):
            raise AssertionError("draft-check did not consume the disclosed authority/revision")
        return

    next_command = payload.get("next_command")
    argv = next_command.get("gateway_argv") if isinstance(next_command, Mapping) else None
    if argv != list(command):
        raise AssertionError(
            f"{previous_step.subcommand} did not disclose exact continuation {list(command)!r}"
        )


def _business_copy_binding_was_used(
    payload: Mapping[str, Any],
    command: Sequence[str],
) -> bool:
    draft = payload.get("draft")
    binding = draft.get("next_action_binding") if isinstance(draft, Mapping) else None
    if (
        not isinstance(binding, Mapping)
        or binding.get("contract") != "waapi-skill.business-draft-next-action/v1"
    ):
        return False
    for candidate in _mapping_nodes(binding):
        prefix = candidate.get("fixed_argv_prefix")
        if (
            not isinstance(prefix, list)
            or len(prefix) < 4
            or prefix[:1] != ["python"]
            or prefix[2:3] != ["gateway.py"]
        ):
            continue
        gateway_prefix = [
            command[index]
            if value == "<task-authority-from-draft-start>"
            else value
            for index, value in enumerate(prefix[3:])
        ]
        if list(command[: len(gateway_prefix)]) != gateway_prefix:
            continue
        suffix = list(command[len(gateway_prefix) :])
        if _business_binding_suffix_matches(candidate, suffix):
            return True
    return False


def _mapping_nodes(value: Any) -> list[Mapping[str, Any]]:
    nodes: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        nodes.append(value)
        for item in value.values():
            nodes.extend(_mapping_nodes(item))
    elif isinstance(value, list):
        for item in value:
            nodes.extend(_mapping_nodes(item))
    return nodes


def _business_binding_suffix_matches(
    candidate: Mapping[str, Any],
    suffix: Sequence[str],
) -> bool:
    repeated = candidate.get("append_repeated")
    if isinstance(repeated, list):
        if (
            len(repeated) != 2
            or not all(isinstance(item, str) and item for item in repeated)
            or not suffix
            or len(suffix) % 2
        ):
            return False
        return all(
            suffix[index] == repeated[0] and bool(suffix[index + 1])
            for index in range(0, len(suffix), 2)
        )

    append = candidate.get("append")
    if not isinstance(append, list):
        return True
    mandatory: list[str] = []
    has_optional = False
    for item in append:
        if not isinstance(item, str) or not item:
            return False
        if item.startswith("["):
            has_optional = True
            break
        mandatory.append(item)
    if len(suffix) < len(mandatory) or (not has_optional and len(suffix) != len(mandatory)):
        return False
    return all(
        bool(actual) if expected.startswith("<") and expected.endswith(">") else actual == expected
        for expected, actual in zip(
            mandatory,
            suffix[: len(mandatory)],
            strict=True,
        )
    )


def _container_action(payload: Mapping[str, Any]) -> list[str] | None:
    continuation = payload.get("continuation")
    action_argv = continuation.get("action_argv") if isinstance(continuation, Mapping) else None
    if not isinstance(action_argv, list):
        if payload.get("status") == "choice_required":
            return None
        decision = (
            continuation.get("next_command_decision")
            if isinstance(continuation, Mapping)
            else None
        )
        candidates = decision.get("evaluate_in_order") if isinstance(decision, Mapping) else None
        if isinstance(candidates, list) and candidates:
            return None
        raise AssertionError("container response did not disclose a typed action")
    return [payload.get("handle") if value == "<child_handle>" else value for value in action_argv]


def _require_preview_continuation(payload: Mapping[str, Any]) -> None:
    transaction_id = payload.get("transaction_id")
    next_command = payload.get("next_command")
    argv = next_command.get("gateway_argv") if isinstance(next_command, Mapping) else None
    if argv != ["transaction-show", transaction_id, "--summary-only"]:
        raise AssertionError("Preview did not disclose its exact transaction-show continuation")


def _render_step_arguments(
    step: ExpectedGatewayStep,
    responses: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    result: list[str] = []
    for argument in step.arguments:
        if isinstance(argument, str):
            result.append(argument)
        elif isinstance(argument, ResponseBinding):
            result.append(_bound_scalar(responses, argument.step, argument.pointer))
        elif isinstance(argument, InlineTypedOperationArgument):
            argv = inline_operation_cli_arguments(argument.expected)
            if not result or argv[0] != result[0]:
                raise AssertionError("inline typed operation witness is misbound")
            result.extend(argv[1:])
        elif isinstance(argument, DraftTypedActionArgument):
            result.extend(_draft_action_argv(argument, responses))
        elif isinstance(argument, DraftTypedActionBatchArgument):
            for action in argument.actions:
                result.extend(_draft_action_argv(action, responses))
        elif isinstance(argument, TypedRequestFactsArgument):
            construction = typed_request_construction_for_values(
                argument.contract,
                args=argument.expected_args,
                options=argument.expected_options,
            )
            result.extend(_typed_fact_argv(construction.facts, prefix=argument.prefix))
        else:
            raise AssertionError(
                f"typed real-test adapter does not support {type(argument).__name__}"
            )
    return result


def _draft_action_argv(
    argument: DraftTypedActionArgument,
    responses: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    action = json.loads(json.dumps(dict(argument.expected)))
    for binding in argument.response_bindings:
        _set_json_pointer(
            action,
            binding.pointer,
            _bound_scalar(
                responses,
                binding.step,
                binding.response_pointer,
            ),
        )
    return typed_action_cli_arguments(action)


def _typed_fact_argv(
    facts: Sequence[TypedRequestFact],
    *,
    prefix: str,
) -> tuple[str, ...]:
    flag_prefix = f"{prefix}-" if prefix else ""
    result: list[str] = []
    for fact in facts:
        result.append(f"--{flag_prefix}{fact.action}")
        if fact.action in {"set", "append"}:
            result.extend((fact.handle, fact.value_type, fact.value))
        elif fact.action == "present":
            result.append(fact.handle)
        elif fact.action == "choose":
            result.extend((fact.handle, fact.value))
        elif fact.action == "choose-dynamic":
            if fact.key is None:
                raise AssertionError("dynamic choice fact has no key")
            result.extend((fact.handle, fact.key, fact.value))
        elif fact.action in {"map-put", "map-correct"}:
            if fact.key is None:
                raise AssertionError("typed map fact has no key")
            result.extend((fact.handle, fact.key, fact.value_type, fact.value))
        elif fact.action == "map-remove":
            if fact.key is None:
                raise AssertionError("typed map removal has no key")
            result.extend((fact.handle, fact.key))
        else:
            raise AssertionError(f"unsupported typed fact action {fact.action!r}")
    return tuple(result)


def _bound_scalar(
    responses: Mapping[str, Mapping[str, Any]],
    step: str,
    pointer: str,
) -> str:
    source = responses.get(step)
    if source is None:
        raise AssertionError(f"typed response binding source {step!r} is unavailable")
    value: Any = source
    for token in pointer.removeprefix("/").split("/") if pointer else ():
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, Mapping):
            value = value[token]
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            value = value[int(token)]
        else:
            raise AssertionError(f"typed response binding {pointer!r} is invalid")
    if not isinstance(value, (str, int, float, bool)) or value is None:
        raise AssertionError(f"typed response binding {pointer!r} is not scalar")
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _set_json_pointer(target: dict[str, Any], pointer: str, value: str) -> None:
    tokens = pointer.removeprefix("/").split("/") if pointer else []
    if not tokens:
        raise AssertionError("typed action binding cannot replace its root")
    current: Any = target
    for raw_token in tokens[:-1]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    final = tokens[-1].replace("~1", "/").replace("~0", "~")
    if isinstance(current, list):
        current[int(final)] = value
    else:
        current[final] = value


def typed_wait_topic_command(
    *,
    name: str,
    topic: str,
    version: str,
    event_count: int,
    match: Mapping[str, Any],
    options: Mapping[str, Any],
) -> tuple[str, ...]:
    """Render the existing V3 Topic step into its public typed argv."""

    step = wait_topic_step(
        name,
        topic,
        version=version,
        event_count=event_count,
        match=match,
        options=options,
    )
    return (step.subcommand, *_render_step_arguments(step, {}))


__all__ = [
    "create_object_lifecycle_business_preview",
    "create_object_metadata_business_preview",
    "create_typed_transaction_preview",
    "typed_wait_topic_command",
]
