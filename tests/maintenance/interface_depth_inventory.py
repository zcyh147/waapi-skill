"""Build the reviewed exact-version interface-depth inventory for GitHub #55."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.canonical import canonical_sha256, strict_json_copy
from wwise_waapi.operation_registry import (
    OPERATION_SPECS,
    audio_import_business_contract,
    operation_input_mode,
)
from wwise_waapi.typed_requests import TypedRequestError, request_contract
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


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain one JSON object")
    return value


def _public_operation_contract(
    name: str, spec: Any, version: str
) -> dict[str, Any]:
    return (
        audio_import_business_contract(version)
        if name == "audio.import"
        else spec.as_dict(version=version)
    )


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
        }
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
    if normalized in rules["reviewed_adapter_names"]:
        return "reviewed_adapter"
    if normalized in rules["exact_artifact_names"]:
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
    rows: list[dict[str, Any]] = []
    for channel, contract in contracts:
        for field in contract.as_gateway_payload().get("fields", []):
            rows.append(
                {
                    "channel": channel,
                    "path": field["path"],
                    "name": field["name"],
                    "shape": field["shape"],
                    "required": field["required"],
                    "value_ownership": _field_ownership(
                        field, policy, uri=lane["uri"]
                    ),
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
    normalized = name.replace("-", "_").lower()
    if normalized == "acknowledge":
        return "gateway_derivation"
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
    if "mutation token" in description or "property metadata" in description:
        return "live_bound_handle"
    if "exact wwise" in description and "token" in description:
        return "reviewed_adapter"
    if normalized in {
        "calls",
        "children",
        "commands",
        "control_input",
        "inclusions",
        "kind",
        "objects",
        "plugin",
        "points",
        "type",
    }:
        return "reviewed_adapter"
    if shape in policy["field_ownership_rules"]["gateway_structure_shapes"] or shape == "object":
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
    for channel, names in (
        ("settings", contract["settings"]),
        ("declaration", contract["declaration_fields"]),
    ):
        for name in names:
            ownership = (
                "exact_user_artifact"
                if name in exact
                else "live_bound_handle"
                if name in live
                else "stable_business_declaration"
            )
            rows.append(
                {
                    "path": [channel, name],
                    "name": name,
                    "shape": "scalar",
                    "required": False,
                    "value_ownership": ownership,
                    "transport_ownership": "gateway_derivation",
                    "schema_sha256": canonical_sha256(
                        {
                            "channel": channel,
                            "name": name,
                            "value_type": contract["field_value_types"].get(name),
                        }
                    ),
                }
            )
    for name in ("semantic_kind", "mode", "event_action"):
        source = {
            "semantic_kind": contract["semantic_kinds"],
            "mode": contract["modes"],
            "event_action": contract["event_actions"],
        }[name]
        rows.append(
            {
                "path": ["business_choice", name],
                "name": name,
                "shape": "scalar",
                "required": name in {"semantic_kind", "mode"},
                "value_ownership": "stable_business_declaration",
                "transport_ownership": "gateway_derivation",
                "schema_sha256": canonical_sha256(source),
            }
        )
    return rows


def _operation_model_values(
    name: str,
    spec: Any,
    version: str,
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if name == "audio.import":
        return _audio_import_model_values(version)
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
        "This report is generated from the exact five-version public surface and the reviewed policy in `interface-depth-review-policy.json`. The 824-lane construction baseline proves typed request construction only; it is not evidence that every interface is deep.",
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
