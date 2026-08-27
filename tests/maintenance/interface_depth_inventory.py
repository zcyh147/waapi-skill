"""Build the reviewed exact-version interface-depth inventory for GitHub #55."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.canonical import canonical_sha256, strict_json_copy
from wwise_waapi.operation_registry import (
    OPERATION_SPECS,
    audio_import_business_contract,
    operation_business_contract,
    operation_input_mode,
)
from wwise_waapi.typed_requests import TypedRequestError, request_contract
from wwise_waapi.typed_queries import (
    typed_query_contract,
    typed_query_schema_payload,
)
from wwise_waapi.typed_topics import topic_match_contract, topic_options_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "docs/interface-depth-review-policy.json"
INVENTORY_PATH = REPO_ROOT / "docs/interface-depth-inventory.json"
INVENTORY_DOC_PATH = REPO_ROOT / "docs/interface-depth-inventory.md"
SURFACE_PATH = (
    REPO_ROOT
    / "skills/waapi-skill/resources/manifest/typed-request-surface.json"
)
CONTRACT = "waapi-skill.interface-depth-inventory/v1"
GATEWAY_PATH = REPO_ROOT / "skills/waapi-skill/scripts/gateway.py"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain one JSON object")
    return value


def _public_operation_contract(
    name: str, spec: Any, version: str
) -> dict[str, Any]:
    if operation_input_mode(name, version) == "business_declaration":
        return operation_business_contract(name, version)
    return spec.as_dict(version=version)


def _operation_contract_rows() -> list[dict[str, Any]]:
    return [
        {
            "operation": name,
            "version": version,
            "contract": _public_operation_contract(name, spec, version),
        }
        for name, spec in sorted(OPERATION_SPECS.items())
        for version in spec.supported_versions
    ]


@lru_cache(maxsize=1)
def _gateway_subparsers() -> Mapping[str, argparse.ArgumentParser]:
    """Load the actual public CLI parser used by fixed Gateway commands.

    Argparse has no public schema-introspection API.  Keep its private action
    walk isolated here and project only semantic command facts below.
    """

    module_name = "_waapi_skill_interface_depth_gateway"
    spec = importlib.util.spec_from_file_location(module_name, GATEWAY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the packaged Gateway parser")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    parser = module.build_parser()
    subparsers = next(
        (
            action.choices
            for action in _parser_actions(parser)
            if isinstance(action.choices, Mapping)
            and all(
                isinstance(value, argparse.ArgumentParser)
                for value in action.choices.values()
            )
        ),
        None,
    )
    if not isinstance(subparsers, Mapping):
        raise RuntimeError("Gateway parser has no public subcommand registry")
    return subparsers


def _parser_actions(parser: argparse.ArgumentParser) -> tuple[argparse.Action, ...]:
    actions = getattr(parser, "_actions", None)
    if not isinstance(actions, list) or not all(
        isinstance(action, argparse.Action) for action in actions
    ):
        raise RuntimeError("Gateway argparse action registry is malformed")
    return tuple(actions)


def _semantic_parameter_shape(action: argparse.Action) -> tuple[str, bool]:
    action_kind = type(action).__name__
    repeatable = action_kind in {"_AppendAction", "_AppendConstAction"}
    multiple = (
        repeatable
        or action.nargs in {"*", "+"}
        or isinstance(action.nargs, int)
        and action.nargs > 1
    )
    return ("array" if multiple else "scalar", repeatable)


def _json_default(value: Any) -> Any:
    if value is argparse.SUPPRESS:
        return "<SUPPRESS>"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_default(item) for item in value]
    return f"<{type(value).__name__}>"


def _gateway_command_contract(command_spec: str) -> dict[str, Any]:
    """Project one fixed command's actual argparse fields deterministically."""

    tokens = command_spec.split()
    parser = _gateway_subparsers().get(tokens[0])
    if parser is None:
        raise RuntimeError(f"unknown fixed Gateway command {command_spec!r}")
    fixed_positionals = iter(tokens[1:])
    parameters: list[dict[str, Any]] = []
    for action in _parser_actions(parser):
        if action.dest == "help":
            continue
        if not action.option_strings:
            fixed_value = next(fixed_positionals, None)
            if fixed_value is not None:
                continue
        long_options = sorted(
            option for option in action.option_strings if option.startswith("--")
        )
        name = (
            long_options[0][2:]
            if long_options
            else str(action.dest).replace("_", "-")
        )
        choices = (
            sorted(str(choice) for choice in action.choices)
            if action.choices is not None
            else None
        )
        shape, repeatable = _semantic_parameter_shape(action)
        parameters.append(
            {
                "name": name,
                "dest": action.dest,
                "option_strings": sorted(action.option_strings),
                "shape": shape,
                "repeatable": repeatable,
                "required": bool(action.required),
                "nargs": action.nargs,
                "metavar": _json_default(action.metavar),
                "choices": choices,
                "type": (
                    getattr(action.type, "__name__", str(action.type))
                    if action.type is not None
                    else None
                ),
                "default": _json_default(action.default),
            }
        )
    try:
        unexpected = next(fixed_positionals)
    except StopIteration:
        unexpected = None
    if unexpected is not None:
        raise RuntimeError(
            f"fixed Gateway command {command_spec!r} has excess bound tokens"
        )
    return {
        "command": command_spec,
        "parameters": parameters,
    }


def _fixed_command_contracts(lane: Mapping[str, Any]) -> list[dict[str, Any]]:
    if lane["execution_policy"]["route"] != "fixed_command":
        return []
    return [
        _gateway_command_contract(command)
        for command in lane["execution_policy"]["gateway_commands"]
    ]


def _fixed_command_has_model_values(lane: Mapping[str, Any]) -> bool:
    return any(
        contract["parameters"] for contract in _fixed_command_contracts(lane)
    )


def _gateway_parser_contract_rows() -> list[dict[str, Any]]:
    """Return the authoritative schema projection for every public command."""

    return [
        _gateway_command_contract(command)
        for command in sorted(_gateway_subparsers())
    ]


def _lane_gateway_command_contracts(
    lane: Mapping[str, Any],
) -> list[dict[str, Any]]:
    command_specs = set(lane["execution_policy"]["gateway_commands"])
    if lane["item_type"] == "topic":
        command_specs.add("topic-schema")
    if "request-schema" in command_specs:
        command_specs.update(
            {
                "request-array-item",
                "request-map-container",
                "typed-call",
                "typed-zero-call",
            }
        )
    if "operation-schema" in command_specs:
        command_specs.update(
            {
                "draft-apply",
                "draft-business-configure",
                "draft-check",
                "draft-start",
                "preview-from-draft",
                "typed-operation",
            }
        )
    return [
        _gateway_command_contract(command)
        for command in sorted(command_specs)
    ]


def _public_continuation_rows(
    surface: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lane in surface["lanes"]:
        row: dict[str, Any] = {
            "version": lane["version"],
            "item_type": lane["item_type"],
            "uri": lane["uri"],
            "gateway_commands": lane["execution_policy"]["gateway_commands"],
            "gateway_command_contracts": _lane_gateway_command_contracts(lane),
        }
        fixed_contracts = _fixed_command_contracts(lane)
        if fixed_contracts:
            row["fixed_command_contracts"] = fixed_contracts
        if lane["item_type"] == "topic":
            row["typed"] = {
                "options": topic_options_contract(
                    lane["version"], lane["uri"]
                ).as_gateway_payload(),
                "match": topic_match_contract(
                    lane["version"], lane["uri"]
                ).as_gateway_payload(),
            }
        elif "request-schema" in lane["execution_policy"]["gateway_commands"]:
            try:
                row["typed"] = request_contract(
                    lane["version"], lane["uri"]
                ).as_gateway_payload()
            except TypedRequestError as exc:
                row["dedicated_boundary"] = str(exc)
        if (
            lane["item_type"] == "function"
            and lane["uri"] == "ak.wwise.core.object.get"
        ):
            row["query_layers"] = {
                "structured": typed_query_schema_payload(
                    lane["version"], advanced=False
                ),
                "advanced": typed_query_schema_payload(
                    lane["version"], advanced=True
                ),
            }
        rows.append(row)
    return rows


def _validate_policy(
    policy: Mapping[str, Any], surface: Mapping[str, Any]
) -> None:
    expected = policy["source_contracts"]
    observed = {
        "typed_request_surface_sha256": surface["inventory_sha256"],
        "operation_contract_sha256": canonical_sha256(_operation_contract_rows()),
        "public_continuation_sha256": canonical_sha256(
            _public_continuation_rows(surface)
        ),
        "gateway_parser_sha256": canonical_sha256(
            _gateway_parser_contract_rows()
        ),
    }
    if observed != expected:
        raise RuntimeError(
            "interface-depth source changed without reviewed policy: "
            f"expected={expected!r}, observed={observed!r}"
        )


def _named_assignments(policy: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for group in policy["named_operation_groups"]:
        for operation in group["operations"]:
            if operation in result:
                raise RuntimeError(f"duplicate named-operation assignment: {operation}")
            result[operation] = group
    missing = set(OPERATION_SPECS) - set(result)
    extra = set(result) - set(OPERATION_SPECS)
    if missing or extra:
        raise RuntimeError(
            f"named-operation policy mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return result


def _matches(
    rule: Mapping[str, Any],
    lane: Mapping[str, Any],
    *,
    dedicated_uris: frozenset[str],
) -> bool:
    match = rule["match"]
    if "item_types" in match and lane["item_type"] not in match["item_types"]:
        return False
    if "routes" in match and lane["execution_policy"]["route"] not in match["routes"]:
        return False
    if "gateway_commands_none" in match and any(
        command in lane["execution_policy"]["gateway_commands"]
        for command in match["gateway_commands_none"]
    ):
        return False
    if (
        "fixed_command_model_values" in match
        and _fixed_command_has_model_values(lane)
        is not match["fixed_command_model_values"]
    ):
        return False
    if (
        "construction_shapes" in match
        and lane["construction_shape"] not in match["construction_shapes"]
    ):
        return False
    if match.get("dedicated_operation_uri") is True and lane["uri"] not in dedicated_uris:
        return False
    if "uri_prefixes" in match and not any(
        lane["uri"].startswith(prefix) for prefix in match["uri_prefixes"]
    ):
        return False
    return True


def _native_assignment(
    policy: Mapping[str, Any],
    lane: Mapping[str, Any],
    *,
    dedicated_uris: frozenset[str],
) -> Mapping[str, Any]:
    for rule in policy["native_lane_rules"]:
        if _matches(rule, lane, dedicated_uris=dedicated_uris):
            return rule
    raise RuntimeError(
        "unowned native interface-depth lane: "
        f"{lane['version']} {lane['item_type']} {lane['uri']}"
    )


def _name_ownership(
    name: str,
    policy: Mapping[str, Any],
    *,
    uri: str | None = None,
) -> str | None:
    rules = policy["field_ownership_rules"]
    normalized = name.replace("-", "_").lower()
    if normalized in rules["gateway_derivation_names"]:
        return "gateway_derivation"
    if normalized in rules["reviewed_adapter_names"]:
        return "reviewed_adapter"
    if normalized in rules["exact_artifact_names"]:
        return "exact_user_artifact"
    if normalized in rules["filesystem_artifact_names"] and uri is not None and any(
        uri.startswith(prefix) for prefix in rules["filesystem_path_uris"]
    ):
        return "exact_user_artifact"
    if any(normalized.endswith(suffix) for suffix in rules["exact_artifact_suffixes"]):
        return "exact_user_artifact"
    if normalized == "path":
        if uri is not None and any(
            uri.startswith(prefix) for prefix in rules["filesystem_path_uris"]
        ):
            return "exact_user_artifact"
        return "reviewed_adapter"
    if normalized in rules["bounded_expression_names"]:
        return "bounded_domain_expression"
    if normalized in rules["live_bound_names"]:
        return "live_bound_handle"
    return None


def _field_ownership(
    field: Mapping[str, Any], policy: Mapping[str, Any], *, uri: str
) -> str:
    named = _name_ownership(str(field["name"]), policy, uri=uri)
    if named is not None:
        return named
    rules = policy["field_ownership_rules"]
    if field["shape"] in rules["gateway_structure_shapes"]:
        return "reviewed_adapter"
    return "stable_business_declaration"


def _typed_field_rows(
    lane: Mapping[str, Any], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    contracts = []
    if lane["item_type"] == "topic":
        contracts = [
            ("options", topic_options_contract(lane["version"], lane["uri"])),
            ("match", topic_match_contract(lane["version"], lane["uri"])),
        ]
    elif "request-schema" in lane["execution_policy"]["gateway_commands"]:
        try:
            contracts = [("request", request_contract(lane["version"], lane["uri"]))]
        except TypedRequestError:
            contracts = []
    if lane["item_type"] == "function" and lane["uri"] == "ak.wwise.core.object.get":
        contracts.extend(
            [
                (
                    "query.structured",
                    typed_query_contract(lane["version"], advanced=False),
                ),
                (
                    "query.advanced",
                    typed_query_contract(lane["version"], advanced=True),
                ),
            ]
        )
    rows: list[dict[str, Any]] = []
    for command in _fixed_command_contracts(lane):
        for parameter in command["parameters"]:
            normalized = parameter["name"].replace("-", "_")
            rules = policy["field_ownership_rules"]
            if normalized in rules["fixed_gateway_derivation_names"]:
                ownership = "gateway_derivation"
            elif normalized in rules["fixed_reviewed_adapter_names"]:
                ownership = "reviewed_adapter"
            else:
                ownership = _name_ownership(
                    parameter["name"], policy, uri=lane["uri"]
                ) or "stable_business_declaration"
            rows.append(
                {
                    "channel": f"fixed.{command['command']}",
                    "path": ["fixed_command", command["command"], parameter["name"]],
                    "name": parameter["name"],
                    "shape": parameter["shape"],
                    "required": parameter["required"],
                    "value_ownership": ownership,
                    "transport_ownership": "gateway_derivation",
                    **(
                        {
                            "components": [
                                {
                                    "name": component,
                                    "value_ownership": component_ownership,
                                    "transport_ownership": "gateway_derivation",
                                }
                                for component, component_ownership in rules[
                                    "fixed_tuple_component_ownership"
                                ][normalized].items()
                            ]
                        }
                        if normalized
                        in rules["fixed_tuple_component_ownership"]
                        else {}
                    ),
                }
            )
    for channel, contract in contracts:
        for field in contract.as_gateway_payload().get("fields", []):
            ownership = _field_ownership(field, policy, uri=lane["uri"])
            if channel == "query.advanced" and field["name"] == "waql":
                ownership = "bounded_domain_expression"
            elif channel.startswith("query.") and field["name"] == "return":
                ownership = "gateway_derivation"
            rows.append(
                {
                    "channel": channel,
                    "path": field["path"],
                    "name": field["name"],
                    "shape": field["shape"],
                    "required": field["required"],
                    "value_ownership": ownership,
                    "transport_ownership": "gateway_derivation",
                }
            )
    return rows


def _schema_shape(schema: Mapping[str, Any]) -> str:
    if isinstance(schema.get("oneOf"), list) or isinstance(schema.get("anyOf"), list):
        return "branch"
    schema_type = schema.get("type")
    if schema_type == "array":
        return "array"
    if schema_type == "object":
        if schema.get("additionalProperties") is True or isinstance(
            schema.get("additionalProperties"), Mapping
        ) or isinstance(schema.get("patternProperties"), Mapping):
            return "map"
        return "object"
    return "scalar"


def _schema_value_ownership(
    name: str,
    schema: Mapping[str, Any],
    *,
    shape: str,
    uri: str,
    policy: Mapping[str, Any],
) -> str:
    if any(
        schema.get(key) is True
        for key in (
            "absoluteRegularFile",
            "absoluteExistingDirectory",
            "absoluteWritableFile",
        )
    ):
        return "exact_user_artifact"
    named = _name_ownership(name, policy, uri=uri)
    if named is not None:
        return named
    description = str(schema.get("description", "")).lower()
    rules = policy["field_ownership_rules"]
    if any(
        phrase in description for phrase in rules["live_bound_description_phrases"]
    ):
        return "live_bound_handle"
    if any(
        all(phrase in description for phrase in phrase_group)
        for phrase_group in rules["reviewed_adapter_description_all"]
    ):
        return "reviewed_adapter"
    if shape in rules["gateway_structure_shapes"] or shape == "object":
        return "reviewed_adapter"
    return "stable_business_declaration"


def _walk_operation_schema(
    schema: Mapping[str, Any],
    *,
    path: tuple[str, ...],
    name: str,
    required: bool,
    uri: str,
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    shape = _schema_shape(schema)
    rows = [
        {
            "path": list(path),
            "name": name,
            "shape": shape,
            "required": required,
            "value_ownership": _schema_value_ownership(
                name,
                schema,
                shape=shape,
                uri=uri,
                policy=policy,
            ),
            "transport_ownership": "gateway_derivation",
            "schema_sha256": canonical_sha256(schema),
        }
    ]
    for keyword in ("oneOf", "anyOf"):
        branches = schema.get(keyword)
        if isinstance(branches, list):
            for index, branch in enumerate(branches):
                if isinstance(branch, Mapping):
                    rows.extend(
                        _walk_operation_schema(
                            branch,
                            path=(*path, f"<{keyword}:{index}>"),
                            name=name,
                            required=required,
                            uri=uri,
                            policy=policy,
                        )
                    )
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        required_names = set(schema.get("required", []))
        for child_name, child in sorted(properties.items()):
            if isinstance(child, Mapping):
                rows.extend(
                    _walk_operation_schema(
                        child,
                        path=(*path, child_name),
                        name=child_name,
                        required=child_name in required_names,
                        uri=uri,
                        policy=policy,
                    )
                )
    items = schema.get("items")
    if isinstance(items, Mapping):
        rows.extend(
            _walk_operation_schema(
                items,
                path=(*path, "[]"),
                name=name,
                required=required,
                uri=uri,
                policy=policy,
            )
        )
    pattern_properties = schema.get("patternProperties")
    if isinstance(pattern_properties, Mapping):
        for pattern, child in sorted(pattern_properties.items()):
            if isinstance(child, Mapping):
                rows.extend(
                    _walk_operation_schema(
                        child,
                        path=(*path, f"<pattern:{pattern}>"),
                        name=f"pattern:{pattern}",
                        required=False,
                        uri=uri,
                        policy=policy,
                    )
                )
    additional = schema.get("additionalProperties")
    if isinstance(additional, Mapping):
        rows.extend(
            _walk_operation_schema(
                additional,
                path=(*path, "<additional>"),
                name="additional",
                required=False,
                uri=uri,
                policy=policy,
            )
        )
    return rows


def _audio_import_model_values(version: str) -> list[dict[str, Any]]:
    contract = audio_import_business_contract(version)
    exact = set(contract["exact_user_artifacts"])
    live = set(contract["live_handles"])
    live.update(contract["field_transport"]["bound_object_handle_fields"])
    live.add(contract["field_transport"]["bound_field_handle_container"])
    rows: list[dict[str, Any]] = []

    def add(
        path: tuple[str, ...],
        *,
        name: str,
        shape: str,
        ownership: str,
        required: bool = False,
        source: Any = None,
    ) -> None:
        rows.append(
            {
                "path": list(path),
                "name": name,
                "shape": shape,
                "required": required,
                "value_ownership": ownership,
                "transport_ownership": "gateway_derivation",
                "schema_sha256": canonical_sha256(
                    {"path": list(path), "source": source}
                ),
            }
        )

    def add_business_field(prefix: tuple[str, ...], name: str) -> None:
        path = (*prefix, name)
        if name == "event":
            add(
                path,
                name=name,
                shape="object",
                ownership="gateway_derivation",
                source=contract["event_actions"],
            )
            add(
                (*path, "parent_handle"),
                name="parent_handle",
                shape="scalar",
                ownership="live_bound_handle",
            )
            add(
                (*path, "name"),
                name="name",
                shape="scalar",
                ownership="stable_business_declaration",
            )
            add(
                (*path, "action"),
                name="action",
                shape="scalar",
                ownership="stable_business_declaration",
                source=contract["event_actions"],
            )
            return
        if name == "field_values":
            add(
                path,
                name=name,
                shape="map",
                ownership="gateway_derivation",
            )
            add(
                (*path, "<field_handle>"),
                name="field_handle",
                shape="scalar",
                ownership="live_bound_handle",
            )
            add(
                (*path, "<value_variant>"),
                name="value_variant",
                shape="branch",
                ownership="gateway_derivation",
            )
            add(
                (*path, "<value_variant>", "scalar_business_value"),
                name="scalar_business_value",
                shape="scalar",
                ownership="stable_business_declaration",
            )
            add(
                (*path, "<value_variant>", "reference_object_handle"),
                name="reference_object_handle",
                shape="scalar",
                ownership="live_bound_handle",
            )
            return
        ownership = (
            "exact_user_artifact"
            if name in exact
            else "live_bound_handle"
            if name in live
            else "stable_business_declaration"
        )
        add(
            path,
            name=name,
            shape="scalar",
            ownership=ownership,
            source=contract["field_value_types"].get(name),
        )

    for setting in contract["settings"]:
        if setting == "defaults":
            add(
                ("settings", "defaults"),
                name="defaults",
                shape="map",
                ownership="gateway_derivation",
            )
            for field_name in contract["declaration_fields"]:
                add_business_field(("settings", "defaults"), field_name)
        else:
            add(
                ("settings", setting),
                name=setting,
                shape="scalar",
                ownership="stable_business_declaration",
                source=(
                    contract["modes"] if setting == "mode" else "boolean"
                ),
            )
    for field_name in contract["declaration_fields"]:
        add_business_field(("declaration",), field_name)

    add(
        ("target", "declaration_id"),
        name="declaration_id",
        shape="scalar",
        ownership="gateway_derivation",
    )
    add(
        ("target", "new", "parent_handle"),
        name="parent_handle",
        shape="scalar",
        ownership="live_bound_handle",
    )
    add(
        ("target", "new", "name"),
        name="name",
        shape="scalar",
        ownership="stable_business_declaration",
    )
    add(
        ("target", "new", "semantic_kind"),
        name="semantic_kind",
        shape="scalar",
        ownership="stable_business_declaration",
        required=True,
        source=contract["semantic_kinds"],
    )
    add(
        ("target", "existing", "object_handle"),
        name="object_handle",
        shape="scalar",
        ownership="live_bound_handle",
    )
    return rows


def _operation_model_values(
    name: str,
    spec: Any,
    version: str,
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if operation_input_mode(name, version) == "business_declaration":
        if name == "audio.import":
            return _audio_import_model_values(version)
        business_contract = operation_business_contract(name, version)
        if name in {
            "object.create",
            "object.createPlugin",
            "object.set",
            "object.setRTPC",
        }:
            return _object_graph_model_values(name, business_contract)
        if name.startswith("soundbank."):
            return _soundbank_model_values(name)
        if name.startswith("ui."):
            return _authoring_ui_model_values(name, business_contract)
        if name.startswith("debug."):
            declaration = business_contract["declaration"]
            return [
                {
                    "path": ["debug_intent", field_name],
                    "name": field_name,
                    "shape": "scalar",
                    "required": True,
                    "value_ownership": "stable_business_declaration",
                    "transport_ownership": "gateway_derivation",
                    "schema_sha256": canonical_sha256(
                        {
                            "operation": name,
                            "field": field_name,
                            "type": "boolean",
                            "business_contract": business_contract["contract"],
                        }
                    ),
                }
                for field_name in declaration["public_fields"]
            ]
        if name == "waapi.undoGroup":
            return _compound_undo_model_values(business_contract)
        declaration = business_contract["declaration"]
        required = set(declaration["required_fields"])
        if name in {
            "audio.importTabDelimited",
            "lua.executeCliFile",
            "lua.executeCoreFile",
            "lua.executeCoreInline",
        }:
            properties = declaration["schema"]["properties"]
            exact = set(business_contract["exact_user_artifacts"])
            return [
                {
                    "path": ["declaration", field_name],
                    "name": field_name,
                    "shape": (
                        "map"
                        if properties[field_name].get("type") == "object"
                        else "array"
                        if properties[field_name].get("type") == "array"
                        else "scalar"
                    ),
                    "required": field_name in required,
                    "value_ownership": (
                        "live_bound_handle"
                        if field_name == "location_handle"
                        else "exact_user_artifact"
                        if field_name in exact
                        else "stable_business_declaration"
                    ),
                    "transport_ownership": "gateway_derivation",
                    "schema_sha256": canonical_sha256(properties[field_name]),
                }
                for field_name in (
                    *declaration["required_fields"],
                    *declaration["optional_fields"],
                )
            ]
        return [
            {
                "path": ["declaration", field_name],
                "name": field_name,
                "shape": "scalar",
                "required": field_name in required,
                "value_ownership": (
                    "live_bound_handle"
                    if declaration["field_types"][field_name]
                    == "bound_object_handle"
                    else "stable_business_declaration"
                ),
                "transport_ownership": "gateway_derivation",
                "schema_sha256": canonical_sha256(
                    {
                        "field": field_name,
                        "type": declaration["field_types"][field_name],
                    }
                ),
            }
            for field_name in (
                *declaration["required_fields"],
                *declaration["optional_fields"],
            )
        ]
    contract = spec.as_dict(version=version)["argument_contract"]
    properties = contract.get("properties")
    if not isinstance(properties, Mapping):
        return []
    required_names = set(contract.get("required", []))
    rows: list[dict[str, Any]] = []
    for argument, schema in sorted(properties.items()):
        if isinstance(schema, Mapping):
            rows.extend(
                _walk_operation_schema(
                    schema,
                    path=("arguments", argument),
                    name=argument,
                    required=argument in required_names,
                    uri=spec.uri,
                    policy=policy,
                )
            )
    return rows


def _compound_undo_model_values(
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project only the display name and checked child Draft capabilities."""

    values = (
        (("display_name",), "scalar", "stable_business_declaration"),
        (("child_drafts",), "array", "stable_business_declaration"),
        (("child_drafts", "[]", "draft_id"), "scalar", "live_bound_handle"),
        (
            ("child_drafts", "[]", "task_authority"),
            "scalar",
            "live_bound_handle",
        ),
    )
    return [
        {
            "path": ["undo_plan", *path],
            "name": path[-1],
            "shape": shape,
            "required": True,
            "value_ownership": ownership,
            "transport_ownership": "gateway_derivation",
            "schema_sha256": canonical_sha256(
                {
                    "operation": "waapi.undoGroup",
                    "path": path,
                    "shape": shape,
                    "ownership": ownership,
                    "business_contract": contract["contract"],
                }
            ),
        }
        for path, shape, ownership in values
    ]


def _authoring_ui_model_values(
    name: str,
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project only high-level Authoring UI choices, never native fields."""

    rows: list[dict[str, Any]] = []

    def add(
        path: tuple[str, ...],
        *,
        shape: str,
        required: bool,
        ownership: str,
    ) -> None:
        rows.append(
            {
                "path": ["ui_plan", *path],
                "name": path[-1],
                "shape": shape,
                "required": required,
                "value_ownership": ownership,
                "transport_ownership": "gateway_derivation",
                "schema_sha256": canonical_sha256(
                    {
                        "operation": name,
                        "path": path,
                        "shape": shape,
                        "ownership": ownership,
                        "business_contract": contract["contract"],
                    }
                ),
            }
        )

    if name == "ui.captureScreen":
        for path, shape in (
            (("view_name",), "scalar"),
            (("view_channel",), "scalar"),
            (("rectangle",), "map"),
            (("rectangle", "x"), "scalar"),
            (("rectangle", "y"), "scalar"),
            (("rectangle", "width"), "scalar"),
            (("rectangle", "height"), "scalar"),
        ):
            add(
                path,
                shape=shape,
                required=False,
                ownership="stable_business_declaration",
            )
        return rows
    if name == "ui.commands.execute":
        properties = contract["declaration"]["schema"]["properties"]
        for field_name, schema in properties.items():
            add(
                (field_name,),
                shape=("array" if schema.get("type") == "array" else "scalar"),
                required=field_name == "command_id",
                ownership=(
                    "exact_user_artifact"
                    if field_name == "files"
                    else "stable_business_declaration"
                ),
            )
        return rows
    if name == "ui.commands.register":
        values = (
            (("command_count",), "scalar", True, "stable_business_declaration"),
            (("commands",), "array", True, "gateway_derivation"),
            (("commands", "[]", "key"), "scalar", True, "stable_business_declaration"),
            (("commands", "[]", "display_name"), "scalar", True, "stable_business_declaration"),
            (("commands", "[]", "handler"), "branch", True, "gateway_derivation"),
            (("commands", "[]", "handler", "kind"), "scalar", True, "stable_business_declaration"),
            (("commands", "[]", "handler", "program_path"), "scalar", False, "exact_user_artifact"),
            (("commands", "[]", "handler", "lua_script_path"), "scalar", False, "exact_user_artifact"),
            (("commands", "[]", "handler", "argument_tokens"), "array", False, "exact_user_artifact"),
            (("commands", "[]", "handler", "working_directory"), "scalar", False, "exact_user_artifact"),
            (("commands", "[]", "handler", "start_mode"), "scalar", False, "stable_business_declaration"),
            (("commands", "[]", "handler", "redirect_outputs"), "scalar", False, "stable_business_declaration"),
            (("commands", "[]", "handler", "lua_module_directories"), "array", False, "exact_user_artifact"),
            (("commands", "[]", "handler", "lua_selected_return"), "array", False, "stable_business_declaration"),
            (("commands", "[]", "default_shortcut"), "scalar", False, "stable_business_declaration"),
            (("commands", "[]", "context_menu"), "map", False, "gateway_derivation"),
            (("commands", "[]", "context_menu", "base_path"), "array", False, "stable_business_declaration"),
            (("commands", "[]", "context_menu", "visible_for"), "array", False, "stable_business_declaration"),
            (("commands", "[]", "context_menu", "enabled_for"), "array", False, "stable_business_declaration"),
            (("commands", "[]", "main_menu"), "map", False, "gateway_derivation"),
            (("commands", "[]", "main_menu", "base_path"), "array", False, "stable_business_declaration"),
        )
    else:
        values = (
            (("registered_command_keys",), "array", False, "stable_business_declaration"),
            (("existing_command_ids",), "array", False, "stable_business_declaration"),
            (("confirm_unknown_ownership",), "scalar", False, "stable_business_declaration"),
        )
    for path, shape, required, ownership in values:
        add(
            path,
            shape=shape,
            required=required,
            ownership=ownership,
        )
    return rows


def _soundbank_model_values(name: str) -> list[dict[str, Any]]:
    """Project the high-level #79 plan rather than its derived native rows."""

    rows: list[dict[str, Any]] = []

    def add(
        path: tuple[str, ...],
        *,
        field_name: str,
        shape: str,
        required: bool,
        ownership: str,
    ) -> None:
        rows.append(
            {
                "path": ["soundbank_plan", *path],
                "name": field_name,
                "shape": shape,
                "required": required,
                "value_ownership": ownership,
                "transport_ownership": "gateway_derivation",
                "schema_sha256": canonical_sha256(
                    {
                        "operation": name,
                        "path": path,
                        "shape": shape,
                        "ownership": ownership,
                    }
                ),
            }
        )

    if name == "soundbank.generate":
        for path, field, shape, required, ownership in (
            (("soundbanks",), "soundbanks", "array", True, "gateway_derivation"),
            (("soundbanks", "[]", "soundbank_handle"), "soundbank_handle", "scalar", True, "live_bound_handle"),
            (("soundbanks", "[]", "artifact_expectation"), "artifact_expectation", "scalar", True, "stable_business_declaration"),
            (("soundbanks", "[]", "rebuild"), "rebuild", "scalar", False, "stable_business_declaration"),
            (("soundbanks", "[]", "event_handles"), "event_handles", "array", False, "live_bound_handle"),
            (("soundbanks", "[]", "aux_bus_handles"), "aux_bus_handles", "array", False, "live_bound_handle"),
            (("soundbanks", "[]", "inclusions"), "inclusions", "array", False, "stable_business_declaration"),
            (("platforms",), "platforms", "array", True, "stable_business_declaration"),
            (("languages",), "languages", "array", False, "stable_business_declaration"),
            (("rebuild_soundbanks",), "rebuild_soundbanks", "scalar", False, "stable_business_declaration"),
            (("clear_audio_file_cache",), "clear_audio_file_cache", "scalar", False, "stable_business_declaration"),
            (("rebuild_init_bank",), "rebuild_init_bank", "scalar", False, "stable_business_declaration"),
            (("io_root",), "io_root", "scalar", True, "exact_user_artifact"),
        ):
            add(path, field_name=field, shape=shape, required=required, ownership=ownership)
        return rows
    if name == "soundbank.setInclusions":
        values = (
            (("soundbank_handle",), "soundbank_handle", "scalar", True, "live_bound_handle"),
            (("mode",), "mode", "scalar", True, "stable_business_declaration"),
            (("inclusions",), "inclusions", "array", True, "gateway_derivation"),
            (("inclusions", "[]", "object_handle"), "object_handle", "scalar", True, "live_bound_handle"),
            (("inclusions", "[]", "filters"), "filters", "array", True, "stable_business_declaration"),
        )
    elif name == "soundbank.convertExternalSources":
        values = (
            (("sources",), "sources", "array", True, "gateway_derivation"),
            (("sources", "[]", "input"), "input", "scalar", True, "exact_user_artifact"),
            (("sources", "[]", "platform"), "platform", "scalar", True, "stable_business_declaration"),
            (("sources", "[]", "output"), "output", "scalar", True, "exact_user_artifact"),
            (("io_root",), "io_root", "scalar", True, "exact_user_artifact"),
        )
    else:
        values = (
            (("files",), "files", "array", True, "exact_user_artifact"),
            (("io_root",), "io_root", "scalar", True, "exact_user_artifact"),
        )
    for path, field, shape, required, ownership in values:
        add(
            path,
            field_name=field,
            shape=shape,
            required=required,
            ownership=ownership,
        )
    return rows


def _object_graph_model_values(
    name: str,
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project every public #78 business value without restoring native shapes."""

    rows: list[dict[str, Any]] = []

    def add(
        path: tuple[str, ...],
        *,
        field_name: str,
        value_type: str,
        required: bool,
        ownership: str = "stable_business_declaration",
        shape: str = "scalar",
    ) -> None:
        rows.append(
            {
                "path": list(path),
                "name": field_name,
                "shape": shape,
                "required": required,
                "value_ownership": ownership,
                "transport_ownership": "gateway_derivation",
                "schema_sha256": canonical_sha256(
                    {
                        "field": field_name,
                        "type": value_type,
                        "shape": shape,
                        "ownership": ownership,
                    }
                ),
            }
        )

    handle_fields = {
        "control_input_handle",
        "field_handle",
        "object_handle",
        "output_bus",
        "parent_handle",
        "plugin_type_handle",
        "replace_owner_handle",
    }
    exact_artifact_fields = {"media_files", "object_list"}

    def add_fields(
        prefix: tuple[str, ...],
        fields: Sequence[str],
        *,
        required: set[str],
        field_types: Mapping[str, Any],
    ) -> None:
        for field_name in fields:
            value_type = str(field_types.get(field_name, "business_value"))
            ownership = (
                "exact_user_artifact"
                if field_name in exact_artifact_fields
                else "live_bound_handle"
                if field_name in handle_fields or field_name == "field_values"
                else "stable_business_declaration"
            )
            add(
                (*prefix, field_name),
                field_name=field_name,
                value_type=value_type,
                required=field_name in required,
                ownership=ownership,
                shape=(
                    "map"
                    if field_name == "field_values"
                    else "array"
                    if field_name == "media_files"
                    else "scalar"
                ),
            )

    declaration = contract["declaration"]
    if name == "object.create":
        required = set(declaration["target_fields"])
        add_fields(
            ("declaration", "new"),
            declaration["target_fields"],
            required=required,
            field_types={
                "parent_handle": "bound_object_handle",
                "name": "string",
                "kind": "semantic_kind_or_bound_type_handle",
            },
        )
        stable = list(declaration["stable_fields"])
        add_fields(
            ("declaration", "new"),
            [*stable, "field_values"],
            required=set(),
            field_types={**declaration["stable_fields"], "field_values": "map"},
        )
    elif name == "object.createPlugin":
        required = set(declaration["required_fields"])
        fields = [*declaration["required_fields"], *declaration["optional_fields"]]
        add_fields(
            ("declaration", "plugin"),
            fields,
            required=required,
            field_types=declaration["field_value_types"],
        )
    elif name == "object.setRTPC":
        required = set(declaration["required_fields"])
        fields = [*declaration["required_fields"], *declaration["optional_fields"]]
        add_fields(
            ("declaration", "rtpc"),
            fields,
            required=required,
            field_types={"curve_points": "ordered_curve_points"},
        )
        for point_field in declaration["point_fields"]:
            add(
                ("declaration", "rtpc", "curve_points", "*", point_field),
                field_name=point_field,
                value_type=("number" if point_field in {"x", "y"} else "curve_shape"),
                required=True,
            )
    else:
        existing_required = set(declaration["existing_required_fields"])
        add_fields(
            ("declaration", "existing"),
            [*declaration["existing_required_fields"], *declaration["optional_fields"]],
            required=existing_required,
            field_types=declaration["field_value_types"],
        )
        new_required = set(declaration["new_required_fields"])
        add_fields(
            ("declaration", "new"),
            [*declaration["new_required_fields"], *declaration["optional_fields"]],
            required=new_required,
            field_types=declaration["field_value_types"],
        )
        media = contract["media_declaration"]
        for source in media["source_forms"]:
            add(
                ("media", source),
                field_name=source,
                value_type="exact_media_artifact",
                required=False,
                ownership="exact_user_artifact",
            )
        for field_name in media["optional_fields"]:
            add(
                ("media", field_name),
                field_name=field_name,
                value_type="business_value",
                required=False,
            )

    for setting in contract.get("settings", {}):
        add(
            ("settings", setting),
            field_name=setting,
            value_type="business_setting",
            required=False,
            ownership=(
                "live_bound_handle"
                if setting == "replace_owner_handle"
                else "stable_business_declaration"
            ),
        )
    return rows


def _mechanic_states(
    policy: Mapping[str, Any], leaked: list[str]
) -> dict[str, str]:
    leaked_set = set(leaked)
    return {
        mechanic: (
            "model_owned_leak" if mechanic in leaked_set else "gateway_owned"
        )
        for mechanic in policy["mechanic_owners"]
    }


def build_interface_depth_inventory() -> dict[str, Any]:
    policy = _load(POLICY_PATH)
    surface = _load(SURFACE_PATH)
    _validate_policy(policy, surface)
    assignments = _named_assignments(policy)
    dedicated_uris = frozenset(
        spec.uri
        for name, spec in OPERATION_SPECS.items()
        if name != "waapi.call"
    )

    native_rows: list[dict[str, Any]] = []
    for lane in surface["lanes"]:
        assignment = _native_assignment(
            policy, lane, dedicated_uris=dedicated_uris
        )
        leaked_mechanics = list(assignment["leaked_mechanics"])
        native_rows.append(
            {
                "version": lane["version"],
                "item_type": lane["item_type"],
                "uri": lane["uri"],
                "host": lane["correct_host"],
                "route": lane["execution_policy"]["route"],
                "construction_shape": lane["construction_shape"],
                "schema_sha256": lane["schema_sha256"],
                "execution_policy_sha256": lane["execution_policy_sha256"],
                "classification": assignment["id"],
                "disposition": assignment["disposition"],
                "owner_issue": assignment["owner_issue"],
                "leaked_mechanics": leaked_mechanics,
                "mechanic_states": _mechanic_states(policy, leaked_mechanics),
                "audit_evidence": assignment.get("audit_evidence"),
                "fields": _typed_field_rows(lane, policy),
                "continuation_commands": lane["execution_policy"]["gateway_commands"],
            }
        )

    operation_rows: list[dict[str, Any]] = []
    for name, spec in sorted(OPERATION_SPECS.items()):
        assignment = assignments[name]
        for version in spec.supported_versions:
            arguments = _operation_model_values(
                name, spec, version, policy
            )
            leaked_mechanics = list(assignment["leaked_mechanics"])
            public_contract = _public_operation_contract(name, spec, version)
            operation_rows.append(
                {
                    "operation": name,
                    "version": version,
                    "uri": spec.uri,
                    "input_mode": operation_input_mode(name, version),
                    "classification": assignment["id"],
                    "disposition": assignment["disposition"],
                    "owner_issue": assignment["owner_issue"],
                    "leaked_mechanics": leaked_mechanics,
                    "mechanic_states": _mechanic_states(
                        policy, leaked_mechanics
                    ),
                    "audit_evidence": assignment.get("audit_evidence"),
                    "arguments": arguments,
                    "contract_sha256": canonical_sha256(public_contract),
                }
            )

    field_contracts: dict[str, list[dict[str, Any]]] = {}
    for row in native_rows:
        fields = row.pop("fields")
        digest = canonical_sha256(fields)
        existing = field_contracts.setdefault(digest, fields)
        if existing != fields:
            raise RuntimeError("native field contract digest collision")
        row["field_contract_sha256"] = digest
    argument_contracts: dict[str, list[dict[str, Any]]] = {}
    for row in operation_rows:
        arguments = row.pop("arguments")
        digest = canonical_sha256(arguments)
        existing = argument_contracts.setdefault(digest, arguments)
        if existing != arguments:
            raise RuntimeError("operation argument contract digest collision")
        row["argument_contract_sha256"] = digest

    ticket_rows: dict[str, list[str]] = defaultdict(list)
    for row in native_rows:
        if row["disposition"] == "migration_required":
            ticket_rows[row["classification"]].append(
                f"{row['version']}|{row['item_type']}|{row['uri']}"
            )
    for row in operation_rows:
        if row["disposition"] == "migration_required":
            ticket_rows[row["classification"]].append(
                f"{row['version']}|operation|{row['operation']}"
            )

    dispositions = Counter(row["disposition"] for row in native_rows)
    operation_dispositions = Counter(row["disposition"] for row in operation_rows)
    blueprints = policy["ticket_blueprints"]
    issue_numbers = policy["ticket_issue_numbers"]
    if set(blueprints) != set(ticket_rows):
        raise RuntimeError(
            "ticket blueprint mismatch: "
            f"missing={sorted(set(ticket_rows) - set(blueprints))}, "
            f"extra={sorted(set(blueprints) - set(ticket_rows))}"
        )
    if set(issue_numbers) != set(ticket_rows):
        raise RuntimeError(
            "ticket issue-number mismatch: "
            f"missing={sorted(set(ticket_rows) - set(issue_numbers))}, "
            f"extra={sorted(set(issue_numbers) - set(ticket_rows))}"
        )
    payload: dict[str, Any] = {
        "contract": CONTRACT,
        "uniform_migration_invariant": strict_json_copy(
            policy["uniform_migration_invariant"]
        ),
        "source_contracts": strict_json_copy(policy["source_contracts"]),
        "ownership_classes": strict_json_copy(policy["ownership_classes"]),
        "mechanic_owners": strict_json_copy(policy["mechanic_owners"]),
        "summary": {
            "native_lanes": len(native_rows),
            "operation_lanes": len(operation_rows),
            "native_dispositions": dict(sorted(dispositions.items())),
            "operation_dispositions": dict(sorted(operation_dispositions.items())),
            "migration_ticket_families": len(ticket_rows),
            "unowned_migration_rows": 0,
        },
        "ticket_families": [
            {
                "id": ticket_id,
                "github_issue": issue_numbers[ticket_id],
                **strict_json_copy(blueprints[ticket_id]),
                "rows": sorted(rows),
                "row_count": len(rows),
                "rows_sha256": canonical_sha256(sorted(rows)),
            }
            for ticket_id, rows in sorted(ticket_rows.items())
        ],
        "field_contracts": [
            {"sha256": digest, "model_values": fields}
            for digest, fields in sorted(field_contracts.items())
        ],
        "argument_contracts": [
            {"sha256": digest, "model_values": arguments}
            for digest, arguments in sorted(argument_contracts.items())
        ],
        "native_lanes": native_rows,
        "operation_lanes": operation_rows,
        "historical_baseline": {
            "contract": surface["contract"],
            "total_lanes": surface["totals"]["total_lanes"],
            "construction_coverage_is_depth_evidence": False,
        },
    }
    payload["inventory_sha256"] = canonical_sha256(payload)
    return strict_json_copy(payload)


def render_interface_depth_inventory(inventory: Mapping[str, Any]) -> str:
    """Render the compact review map; exact rows remain in the JSON artifact."""

    summary = inventory["summary"]
    lines = [
        "# Interface-depth inventory",
        "",
        "This report is generated from the exact five-version public surface and the reviewed policy in `interface-depth-review-policy.json`. The 824-lane construction baseline proves typed request construction only; it is not evidence that every interface is deep. Every permitted public API and supported version lane must converge on the same Gateway-owned business/domain boundary; simplicity and prior test PASS are not migration exemptions.",
        "",
        "## Exact coverage",
        "",
        f"- Native function/Topic lanes: **{summary['native_lanes']}**",
        f"- Named-operation lanes: **{summary['operation_lanes']}**",
        f"- Migration families: **{summary['migration_ticket_families']}**",
        f"- Unowned migration rows: **{summary['unowned_migration_rows']}**",
        "",
        "Every exact row, version, schema digest, continuation command, field ownership, disposition, and owner is recorded in `interface-depth-inventory.json`.",
        "",
        "## Ownership boundary",
        "",
        "| Class | Meaning |",
        "| --- | --- |",
    ]
    for name, meaning in inventory["ownership_classes"].items():
        lines.append(f"| `{name}` | {meaning} |")
    lines.extend(
        [
            "",
            "Business scalar values remain visible. Native paths, metadata scope, property/reference tokens, dependency order, batch layout, revision arithmetic, request fragments, continuation selection, wire types, and shell quoting are Gateway-owned.",
            "",
            "## Migration ticket families",
            "",
            "| Family | Roll-up | Exact rows | Versions | Unique API/operation names | Row digest |",
            "| --- | ---: | ---: | --- | ---: | --- |",
        ]
    )
    lane_index = {
        f"{row['version']}|{row['item_type']}|{row['uri']}": row
        for row in inventory["native_lanes"]
    }
    operation_index = {
        f"{row['version']}|operation|{row['operation']}": row
        for row in inventory["operation_lanes"]
    }
    for family in inventory["ticket_families"]:
        indexed = [
            lane_index.get(key) or operation_index[key] for key in family["rows"]
        ]
        versions = sorted({row["version"] for row in indexed})
        names = {
            row.get("operation") or row["uri"]
            for row in indexed
        }
        owner = next(row["owner_issue"] for row in indexed)
        lines.append(
            f"| [`{family['id']}`](https://github.com/zcyh147/waapi-skill/issues/{family['github_issue']}) | #{owner} | {family['row_count']} | "
            f"{', '.join(versions)} | {len(names)} | `{family['rows_sha256']}` |"
        )
    reviewed_groups: dict[tuple[str, str, str], int] = Counter()
    for row in (*inventory["native_lanes"], *inventory["operation_lanes"]):
        if row["disposition"] == "migration_required":
            continue
        key = (
            row["classification"],
            row["disposition"],
            row["audit_evidence"],
        )
        reviewed_groups[key] += 1
    lines.extend(
        [
            "",
            "## Already-deep and boundary evidence",
            "",
            "| Classification | Disposition | Exact lanes | Audit evidence |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for (classification, disposition, evidence), count in sorted(
        reviewed_groups.items()
    ):
        lines.append(
            f"| `{classification}` | `{disposition}` | {count} | {evidence} |"
        )
    lines.extend(
        [
            "",
            "Generated tests seal the native surface digest, every operation/version contract, and every public continuation. A new lane, field, version delta, or continuation therefore fails until this review policy and generated inventory are intentionally updated.",
            "",
        ]
    )
    return "\n".join(lines)
