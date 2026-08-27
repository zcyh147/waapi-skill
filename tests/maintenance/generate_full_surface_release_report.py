"""Build the deterministic release audit for the maximum typed WAAPI surface."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from wwise_waapi.authoring_ui_commands_manifest import (  # noqa: E402
    AUTHORING_UI_COMMAND_URIS,
)
from wwise_waapi.capabilities import CapabilityCatalog  # noqa: E402
from wwise_waapi.execution_contracts import (  # noqa: E402
    AUTHORING_UI_EXECUTION_PROFILE,
)
from wwise_waapi.manifest import DeterministicJsonWriter  # noqa: E402
from wwise_waapi.schema_inventory import (  # noqa: E402
    validate_packaged_typed_request_surface,
)


REPORT_CONTRACT = "waapi-skill.full-surface-release-report/v1"
REPORT_RELATIVE_PATH = Path("docs/full-surface-release-report.json")
MANIFEST_RELATIVE_PATH = Path("skills/waapi-skill/resources/manifest")


def build_full_surface_release_report(*, repo_root: Path) -> dict[str, Any]:
    """Project packaged inventory truth into one bounded release-review report."""

    root = Path(repo_root).resolve()
    surface = validate_packaged_typed_request_surface(
        root=root / MANIFEST_RELATIVE_PATH
    )
    lanes = surface["lanes"]
    if not isinstance(lanes, list):  # pragma: no cover - inventory validator owns it
        raise ValueError("Typed request surface lanes must be an array")

    catalog = CapabilityCatalog(manifest_root=root / MANIFEST_RELATIVE_PATH)
    expected_lanes = {
        (entry.version, entry.item_type, entry.uri): entry
        for version in surface["versions"]
        for entry in catalog.entries_for_profile(
            version,
            profile=AUTHORING_UI_EXECUTION_PROFILE,
        )
    }
    gateway, public_commands = _load_public_gateway(root)
    identities: Counter[tuple[str, str, str]] = Counter()
    shapes: Counter[str] = Counter()
    routes: Counter[str] = Counter()
    hosts: Counter[str] = Counter()
    missing_continuations: list[dict[str, str]] = []
    missing_host_overlays: list[dict[str, str]] = []
    missing_semantic_overlays: list[dict[str, str]] = []
    construction_covered: set[tuple[str, str, str]] = set()
    for raw_lane in lanes:
        if not isinstance(raw_lane, Mapping):  # pragma: no cover - validated resource
            raise ValueError("Typed request surface lane must be an object")
        version = str(raw_lane["version"])
        item_type = str(raw_lane["item_type"])
        uri = str(raw_lane["uri"])
        host = str(raw_lane["correct_host"])
        identity = (version, item_type, uri)
        identities[identity] += 1
        shapes[str(raw_lane["construction_shape"])] += 1
        hosts[host] += 1

        policy = raw_lane["execution_policy"]
        if not isinstance(policy, Mapping):  # pragma: no cover - validated resource
            raise ValueError("Typed request execution policy must be an object")
        routes[str(policy["route"])] += 1
        capability = expected_lanes.get(identity)
        commands = policy.get("gateway_commands")
        continuation_error = _continuation_error(
            gateway=gateway,
            public_commands=public_commands,
            capability=capability,
            version=version,
            item_type=item_type,
            uri=uri,
            construction_shape=str(raw_lane["construction_shape"]),
            commands=commands,
        )
        if continuation_error is not None:
            missing_continuations.append(
                {
                    "version": version,
                    "item_type": item_type,
                    "uri": uri,
                    "error": continuation_error,
                }
            )
        else:
            construction_covered.add(identity)

        if (
            capability is None
            or capability.host_surface != host
            or (host == "wwise-authoring" and uri not in AUTHORING_UI_COMMAND_URIS)
        ):
            missing_host_overlays.append(
                {"version": version, "item_type": item_type, "uri": uri}
            )
        if capability is None or dict(capability.execution_contract) != dict(policy):
            missing_semantic_overlays.append(
                {"version": version, "item_type": item_type, "uri": uri}
            )

    duplicate_lanes = [
        {"version": version, "item_type": item_type, "uri": uri, "count": count}
        for (version, item_type, uri), count in sorted(identities.items())
        if count != 1
    ]
    actual_identities = set(identities)
    missing_lanes = [
        {"version": version, "item_type": item_type, "uri": uri}
        for version, item_type, uri in sorted(set(expected_lanes) - actual_identities)
    ]
    unexpected_lanes = [
        {"version": version, "item_type": item_type, "uri": uri}
        for version, item_type, uri in sorted(actual_identities - set(expected_lanes))
    ]
    coverage = dict(surface["totals"])
    coverage["construction_covered_lanes"] = len(construction_covered)
    coverage = dict(sorted(coverage.items()))
    return {
        "contract": REPORT_CONTRACT,
        "source_inventory": {
            "contract": surface["contract"],
            "inventory_sha256": surface["inventory_sha256"],
            "versions": surface["versions"],
        },
        "coverage": coverage,
        "construction_shapes": dict(sorted(shapes.items())),
        "execution_routes": dict(sorted(routes.items())),
        "host_lanes": dict(sorted(hosts.items())),
        "intentionally_blocked_field_occurrences": surface[
            "intentionally_blocked_field_occurrences"
        ],
        "audit": {
            "duplicate_lanes": duplicate_lanes,
            "missing_continuations": missing_continuations,
            "missing_host_overlays": missing_host_overlays,
            "missing_lanes": missing_lanes,
            "missing_semantic_overlays": missing_semantic_overlays,
            "unexpected_lanes": unexpected_lanes,
            "unknown_schema_keywords": surface["unknown_schema_keywords"],
            "unresolved_references": surface["unresolved_references"],
        },
    }


def _load_public_gateway(repo_root: Path) -> tuple[Any, frozenset[str]]:
    gateway_path = repo_root / "skills/waapi-skill/scripts/gateway.py"
    spec = importlib.util.spec_from_file_location(
        "waapi_full_surface_release_gateway",
        gateway_path,
    )
    if spec is None or spec.loader is None:
        raise ValueError("Could not load the packaged Gateway parser")
    gateway = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gateway
    spec.loader.exec_module(gateway)
    parser = gateway.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return gateway, frozenset(subparsers.choices)


def _continuation_error(
    *,
    gateway: Any,
    public_commands: frozenset[str],
    capability: Any,
    version: str,
    item_type: str,
    uri: str,
    construction_shape: str,
    commands: Any,
) -> str | None:
    if capability is None:
        return "lane is absent from the exact maximum-profile Capability Catalog"
    expected_commands = list(capability.execution_contract["gateway_commands"])
    if commands != expected_commands:
        return "lane continuation differs from the exact execution contract"
    if not commands or not all(
        isinstance(command, str)
        and command
        and command.split(maxsplit=1)[0] in public_commands
        for command in commands
    ):
        return "lane continuation is not a packaged Gateway command"
    try:
        if item_type == "topic":
            if commands != ["wait-topic", "stream-topic"]:
                return "Topic lifecycle continuation is not the exact wait/stream pair"
            options = gateway.topic_options_contract(version, uri)
            match = gateway.topic_match_contract(version, uri)
            if not options.schema_digest or not match.schema_digest:
                return "Topic typed contracts do not bind both schema digests"
        elif "operation-schema" in commands:
            operations = tuple(capability.transaction_operations)
            if not operations:
                return "dedicated continuation has no exact operation binding"
            for operation in operations:
                mode = gateway.operation_input_mode(operation, version)
                if mode == gateway.COMPOSER_INPUT_MODE:
                    contract = gateway.operation_composer_input_contract(
                        operation,
                        version,
                    )
                    start = contract["start"]
                    subcommands = tuple(
                        start[key]
                        for key in (
                            "subcommand",
                            "subcommand_after_preconditions",
                        )
                        if key in start
                    )
                    argv_values = tuple(
                        start[key]
                        for key in (
                            "gateway_argv",
                            "gateway_argv_after_preconditions",
                        )
                        if key in start
                    )
                    if subcommands != ("draft-start",) or argv_values != (
                        ["draft-start", operation],
                    ):
                        return "Composer continuation does not start one Draft"
                elif mode == gateway.BUSINESS_DECLARATION_INPUT_MODE:
                    contract = gateway.operation_business_contract(
                        operation,
                        version,
                    )
                    start = contract.get("start")
                    if (
                        contract.get("operation") != operation
                        or contract.get("version") != version
                        or not isinstance(start, Mapping)
                        or start.get("gateway_argv")
                        != ["draft-start", operation]
                    ):
                        return "business declaration Adapter is incomplete"
                    if operation == "audio.import":
                        if (
                            not contract.get("semantic_kinds")
                            or not contract.get("declaration_fields")
                        ):
                            return "business declaration Adapter is incomplete"
                    else:
                        declaration = contract.get("declaration")
                        if operation in {
                            "object.create",
                            "object.createPlugin",
                            "object.set",
                            "object.setRTPC",
                        }:
                            required_groups = {
                                "object.create": ("target_fields",),
                                "object.createPlugin": ("required_fields",),
                                "object.set": (
                                    "existing_required_fields",
                                    "new_required_fields",
                                ),
                                "object.setRTPC": ("required_fields",),
                            }[operation]
                            if (
                                not isinstance(declaration, Mapping)
                                or any(
                                    not declaration.get(key)
                                    for key in required_groups
                                )
                                or contract.get("legacy_shallow_composer_public")
                                is not False
                                or not contract.get("gateway_derivations")
                            ):
                                return "business declaration Adapter is incomplete"
                        elif operation in {
                            "soundbank.convertExternalSources",
                            "soundbank.generate",
                            "soundbank.processDefinitionFiles",
                            "soundbank.setInclusions",
                        }:
                            if (
                                not isinstance(declaration, Mapping)
                                or declaration.get("subcommand")
                                != "draft-declare-soundbank-plan"
                                or not declaration.get("required_fields")
                                or contract.get("legacy_composer_public")
                                is not False
                                or contract.get("legacy_inline_typed_public")
                                is not False
                                or not contract.get("gateway_derivations")
                            ):
                                return "business declaration Adapter is incomplete"
                        elif operation in {
                            "audio.importTabDelimited",
                            "lua.executeCliFile",
                            "lua.executeCoreFile",
                            "lua.executeCoreInline",
                        }:
                            if (
                                not isinstance(declaration, Mapping)
                                or declaration.get("subcommand")
                                != "draft-declare-artifact-plan"
                                or not declaration.get("required_fields")
                                or not declaration.get("public_fields")
                                or contract.get("legacy_composer_public")
                                is not False
                                or contract.get("legacy_inline_typed_public")
                                is not False
                                or not contract.get("gateway_derivations")
                            ):
                                return "business declaration Adapter is incomplete"
                        elif operation in {
                            "ui.captureScreen",
                            "ui.commands.execute",
                            "ui.commands.register",
                            "ui.commands.unregister",
                        }:
                            has_closed_shape = (
                                isinstance(declaration.get("schema"), Mapping)
                                or (
                                    isinstance(
                                        declaration.get("header_schema"),
                                        Mapping,
                                    )
                                    and isinstance(
                                        declaration.get("item_schema"),
                                        Mapping,
                                    )
                                )
                            ) if isinstance(declaration, Mapping) else False
                            if (
                                not isinstance(declaration, Mapping)
                                or declaration.get("subcommand")
                                != "draft-declare-ui-plan"
                                or not has_closed_shape
                                or contract.get("legacy_composer_public")
                                is not False
                                or contract.get("legacy_inline_typed_public")
                                is not False
                                or not contract.get("gateway_derivations")
                            ):
                                return "business declaration Adapter is incomplete"
                        elif operation in {
                            "debug.restartWaapiServers",
                            "debug.setAsserts",
                            "debug.setAutomationMode",
                            "debug.testAssert",
                            "debug.testCrash",
                        }:
                            if (
                                not isinstance(declaration, Mapping)
                                or declaration.get("subcommand")
                                != "draft-declare-debug-intent"
                                or declaration.get("native_request_fields")
                                != "forbidden"
                                or contract.get("legacy_composer_public")
                                is not False
                                or contract.get("legacy_inline_typed_public")
                                is not False
                                or not contract.get("gateway_derivations")
                            ):
                                return "business declaration Adapter is incomplete"
                        elif operation == "waapi.undoGroup":
                            if (
                                not isinstance(declaration, Mapping)
                                or declaration.get("subcommand")
                                != "draft-declare-undo-plan"
                                or declaration.get("required_fields")
                                != ["display_name", "child_drafts"]
                                or declaration.get("child_input")
                                != "ordered_checked_closed_draft_snapshot"
                                or declaration.get("native_request_input")
                                != "forbidden"
                                or declaration.get("child_call_handle_input")
                                != "forbidden"
                                or declaration.get("action_ordering_grammar")
                                != "forbidden"
                                or contract.get("legacy_composer_public")
                                is not False
                                or contract.get("legacy_child_schema_public")
                                is not False
                                or not contract.get("gateway_derivations")
                            ):
                                return "business declaration Adapter is incomplete"
                        elif (
                            not isinstance(declaration, Mapping)
                            or not declaration.get("required_fields")
                            or not isinstance(
                                declaration.get("field_types"),
                                Mapping,
                            )
                        ):
                            return "business declaration Adapter is incomplete"
                elif mode == gateway.INLINE_TYPED_INPUT_MODE:
                    contract = gateway.inline_operation_contract(operation, version)
                    if contract["continuation"]["subcommand"] != "typed-operation":
                        return "inline operation continuation is not typed-operation"
                else:
                    return "dedicated operation retained a non-typed input mode"
        elif "request-schema" in commands:
            contract = gateway.public_typed_contract(version, uri)
            payload = contract.as_gateway_payload()
            public_input_shape = payload["input_shape"]
            if payload["input_shape"] != public_input_shape:
                return "typed continuation shape differs from the inventory"
            subcommand = payload.get("continuation", {}).get("subcommand")
            expected_subcommand = {
                "zero": "typed-zero-call",
                "inline": "typed-call",
                "draft": "draft-start",
            }.get(public_input_shape)
            if subcommand != expected_subcommand:
                return "typed continuation subcommand differs from its compiled shape"
    except Exception as exc:
        return f"exact public construction failed: {type(exc).__name__}: {exc}"
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or check the deterministic full-surface release report."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    path = repo_root / REPORT_RELATIVE_PATH
    rendered = DeterministicJsonWriter().dumps(
        build_full_surface_release_report(repo_root=repo_root)
    )
    if args.write:
        path.write_text(rendered, encoding="utf-8")
        return 0
    if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
        raise SystemExit(
            f"Full-surface release report is stale; run {Path(__file__).name} --write"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
