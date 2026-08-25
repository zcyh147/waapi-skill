"""Build the reviewed exact-version interface-depth inventory for GitHub #55."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.canonical import canonical_sha256, strict_json_copy
from wwise_waapi.operation_registry import OPERATION_SPECS, operation_input_mode
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


def _operation_contract_rows() -> list[dict[str, Any]]:
    return [
        {
            "operation": name,
            "version": version,
            "contract": spec.as_dict(version=version),
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


def _field_ownership(
    field: Mapping[str, Any], policy: Mapping[str, Any]
) -> str:
    rules = policy["field_ownership_rules"]
    name = str(field["name"]).replace("-", "_").lower()
    if name in rules["exact_artifact_names"]:
        return "exact_user_artifact"
    if name in rules["bounded_expression_names"]:
        return "bounded_domain_expression"
    if name in rules["live_bound_names"]:
        return "live_bound_handle"
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
                    "value_ownership": _field_ownership(field, policy),
                    "transport_ownership": "gateway_derivation",
                }
            )
    return rows


def _operation_argument_ownership(
    operation: str, argument: str, policy: Mapping[str, Any]
) -> str:
    if argument == "acknowledge":
        return "gateway_derivation"
    normalized = argument.replace("-", "_").lower()
    rules = policy["field_ownership_rules"]
    if normalized in rules["exact_artifact_names"] or normalized in {
        "io_root",
        "source_authority",
    }:
        return "exact_user_artifact"
    if normalized in rules["bounded_expression_names"]:
        return "bounded_domain_expression"
    if normalized in rules["live_bound_names"]:
        return "live_bound_handle"
    if normalized in {
        "calls",
        "children",
        "commands",
        "control_input",
        "inclusions",
        "objects",
        "plugin",
        "points",
        "type",
    }:
        return "reviewed_adapter"
    return "stable_business_declaration"


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
                "leaked_mechanics": assignment["leaked_mechanics"],
                "fields": _typed_field_rows(lane, policy),
                "continuation_commands": lane["execution_policy"]["gateway_commands"],
            }
        )

    operation_rows: list[dict[str, Any]] = []
    for name, spec in sorted(OPERATION_SPECS.items()):
        assignment = assignments[name]
        for version in spec.supported_versions:
            arguments = [
                {
                    "name": argument,
                    "required": argument in spec.required_arguments,
                    "value_ownership": _operation_argument_ownership(
                        name, argument, policy
                    ),
                    "transport_ownership": "gateway_derivation",
                }
                for argument in (*spec.required_arguments, *spec.optional_arguments)
            ]
            operation_rows.append(
                {
                    "operation": name,
                    "version": version,
                    "uri": spec.uri,
                    "input_mode": operation_input_mode(name, version),
                    "classification": assignment["id"],
                    "disposition": assignment["disposition"],
                    "owner_issue": assignment["owner_issue"],
                    "leaked_mechanics": assignment["leaked_mechanics"],
                    "arguments": arguments,
                    "contract_sha256": canonical_sha256(spec.as_dict(version=version)),
                }
            )

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
    if set(blueprints) != set(ticket_rows):
        raise RuntimeError(
            "ticket blueprint mismatch: "
            f"missing={sorted(set(ticket_rows) - set(blueprints))}, "
            f"extra={sorted(set(blueprints) - set(ticket_rows))}"
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
                **strict_json_copy(blueprints[ticket_id]),
                "rows": sorted(rows),
                "row_count": len(rows),
                "rows_sha256": canonical_sha256(sorted(rows)),
            }
            for ticket_id, rows in sorted(ticket_rows.items())
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
            f"| `{family['id']}` | #{owner} | {family['row_count']} | "
            f"{', '.join(versions)} | {len(names)} | `{family['rows_sha256']}` |"
        )
    lines.extend(
        [
            "",
            "## Already-deep and boundary evidence",
            "",
            "Named operations classified `already_deep` already accept closed business selectors/scalars or exact user artifacts without a model-authored construction plan. `audio.import` is the proved business-declaration reference Adapter. Generic rows behind a dedicated operation are a prohibited bypass boundary; the internal `waapi.call` representation is not public. Pure fixed commands and zero-input native lanes have no model-authored native request structure.",
            "",
            "Generated tests seal the native surface digest, every operation/version contract, and every public continuation. A new lane, field, version delta, or continuation therefore fails until this review policy and generated inventory are intentionally updated.",
            "",
        ]
    )
    return "\n".join(lines)
