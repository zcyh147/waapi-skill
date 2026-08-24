"""Frozen test-only codec for pre-cutover ``audio.import`` Draft evidence.

This module is deliberately outside the packaged Skill. It preserves only the
historical archive grammar needed to inspect sealed evidence; no Gateway or
Agent execution path imports it.
"""

from __future__ import annotations

import json
import math
from typing import Any, Callable, Mapping, Sequence

from wwise_waapi.operation_composer import OperationComposerError


ACTION_CONTRACT = "waapi-skill.operation-draft-action/v1"
COMPOSITION_CONTRACT = "waapi-skill.operation-composition/v1"
ACTION_BYTES = 384 * 1024
ACTIONS = (
    "set_import_operation",
    "set_import_option",
    "clear_import_option",
    "set_import_default",
    "clear_import_default",
    "add_import_row",
    "set_import_row_field",
    "clear_import_row_field",
    "remove_import_row",
)


def contract(version: str) -> dict[str, Any]:
    if version not in {"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"}:
        raise OperationComposerError("retired audio.import version is invalid")
    return {
        "contract": "waapi-skill.retired-audio-import-composer/v1",
        "operation": "audio.import",
        "version": version,
        "actions": list(ACTIONS),
        "limits": {"action_bytes": ACTION_BYTES},
    }


def parse_typed_action(arguments: Sequence[str]) -> dict[str, Any]:
    tokens = tuple(arguments)
    if len(tokens) < 2 or tokens[:1] != ("--action",):
        raise OperationComposerError("retired audio.import action prefix is invalid")
    action: dict[str, Any] = {"contract": ACTION_CONTRACT, "action": tokens[1]}
    index = 2
    properties: dict[str, list[dict[str, Any]]] = {}
    references: dict[str, list[dict[str, Any]]] = {}
    while index < len(tokens):
        flag = tokens[index]
        if flag == "--value" and index + 3 < len(tokens):
            field, value_type, raw = tokens[index + 1 : index + 4]
            action[field] = _scalar(value_type, raw)
            index += 4
        elif flag == "--selector" and index + 3 < len(tokens):
            field = tokens[index + 1]
            action[field], consumed = _selector(tokens[index + 2 :])
            index += 2 + consumed
        elif flag == "--property" and index + 4 < len(tokens):
            field, name, value_type, raw = tokens[index + 1 : index + 5]
            properties.setdefault(field, []).append(
                {"name": name, "value": _scalar(value_type, raw)}
            )
            index += 5
        elif flag == "--reference" and index + 4 < len(tokens):
            field, name = tokens[index + 1 : index + 3]
            target, consumed = _selector(tokens[index + 3 :])
            references.setdefault(field, []).append({"name": name, "target": target})
            index += 3 + consumed
        elif flag == "--event" and index + 3 < len(tokens):
            field, event_action, path = tokens[index + 1 : index + 4]
            action[field] = {"action": event_action, "path": path}
            index += 4
        elif flag == "--event-path" and index + 1 < len(tokens):
            action["event"] = {"path": tokens[index + 1]}
            index += 2
        elif flag == "--assignment" and index + 1 < len(tokens):
            mode = tokens[index + 1]
            if mode == "none":
                action["assignment"] = {"mode": "none"}
                index += 2
            elif mode == "switch" and index + 2 < len(tokens):
                action["assignment"] = {"mode": "switch", "value": tokens[index + 2]}
                index += 3
            else:
                raise OperationComposerError("retired assignment is invalid")
        else:
            raise OperationComposerError("retired audio.import typed argv is invalid")
    action.update(properties)
    action.update(references)
    return action


def new_composition(version: str) -> dict[str, Any]:
    contract(version)
    return {
        "contract": COMPOSITION_CONTRACT,
        "request_options": {"import_operation": "createNew"},
        "defaults": {},
        "imports": [],
    }


def apply_action(
    version: str,
    composition: Mapping[str, Any],
    action: Mapping[str, Any],
    *,
    handle_factory: Callable[[], str] | None,
) -> tuple[dict[str, Any], str]:
    contract(version)
    normalized = _composition(composition)
    name = action.get("action")
    if name not in ACTIONS or action.get("contract") != ACTION_CONTRACT:
        raise OperationComposerError("retired audio.import action is invalid")
    if name == "set_import_operation":
        normalized["request_options"]["import_operation"] = action["mode"]
    elif name in {"set_import_option", "set_import_default"}:
        target = (
            normalized["request_options"]
            if name == "set_import_option"
            else normalized["defaults"]
        )
        target[str(action["name"])] = action["value"]
    elif name in {"clear_import_option", "clear_import_default"}:
        target = (
            normalized["request_options"]
            if name == "clear_import_option"
            else normalized["defaults"]
        )
        target.pop(str(action["name"]), None)
    elif name == "add_import_row":
        if handle_factory is None:
            raise OperationComposerError("retired import row needs one sealed handle")
        fields = {
            key: value
            for key, value in action.items()
            if key not in {"contract", "action", "assignment"}
        }
        assignment = action.get("assignment")
        if isinstance(assignment, Mapping) and assignment.get("mode") == "switch":
            fields["switch_assignment"] = assignment.get("value")
        normalized["imports"].append(
            {"handle": handle_factory(), "fields": _json(fields)}
        )
    else:
        handle = action.get("import_handle")
        rows = [row for row in normalized["imports"] if row["handle"] == handle]
        if len(rows) != 1:
            raise OperationComposerError("retired import handle is unavailable")
        row = rows[0]
        if name == "set_import_row_field":
            row["fields"][str(action["name"])] = _json(action["value"])
        elif name == "clear_import_row_field":
            row["fields"].pop(str(action["name"]), None)
        else:
            normalized["imports"].remove(row)
    return normalized, str(name)


def projection(version: str, composition: Mapping[str, Any]) -> dict[str, Any]:
    contract(version)
    normalized = _composition(composition)
    facts = [
        {"handle": row["handle"], **_json(row["fields"])}
        for row in normalized["imports"]
    ]
    missing = [] if facts else ["import_row"]
    return {
        "request_options": _json(normalized["request_options"]),
        "defaults": _json(normalized["defaults"]),
        "current_facts": facts,
        "missing_fields": missing,
        "missing_fields_status": "complete" if not missing else "incomplete",
        "allowed_actions": [*ACTIONS, "check", "inspect", "cancel"],
    }


def _composition(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("contract") != COMPOSITION_CONTRACT:
        raise OperationComposerError("retired composition contract is invalid")
    return _json(
        {
            "contract": COMPOSITION_CONTRACT,
            "request_options": value.get("request_options", {}),
            "defaults": value.get("defaults", {}),
            "imports": value.get("imports", []),
        }
    )


def _selector(tokens: Sequence[str]) -> tuple[dict[str, Any], int]:
    if len(tokens) < 2 or tokens[0] not in {"id", "id-string", "path"}:
        raise OperationComposerError("retired selector is invalid")
    return {
        "kind": "id" if tokens[0] in {"id", "id-string"} else "path",
        "value": tokens[1],
    }, 2


def _scalar(value_type: str, raw: str) -> Any:
    if value_type == "string":
        return raw
    if value_type == "boolean" and raw in {"true", "false"}:
        return raw == "true"
    if value_type == "integer":
        return int(raw)
    if value_type == "number":
        value = json.loads(raw)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise OperationComposerError("retired number is invalid")
        return value
    raise OperationComposerError("retired scalar is invalid")


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


__all__ = [
    "ACTION_BYTES",
    "apply_action",
    "contract",
    "new_composition",
    "parse_typed_action",
    "projection",
]
