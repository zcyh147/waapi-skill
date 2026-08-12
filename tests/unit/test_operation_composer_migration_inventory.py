from __future__ import annotations

import json
import hashlib
from pathlib import Path

from wwise_waapi.operation_registry import (
    COMPOSER_INPUT_MODE,
    INLINE_TYPED_INPUT_MODE,
    LEGACY_JSON_INPUT_MODE,
    OPERATION_SPECS,
    operation_input_mode,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = REPO_ROOT / "docs" / "operation-composer-migration-inventory.json"
INVENTORY_DOC_PATH = REPO_ROOT / "docs" / "operation-composer-migration-inventory.md"


def _inventory() -> dict[str, object]:
    raw = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _assignments(inventory: dict[str, object]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for disposition, collection in (
        ("migration_wave", inventory["waves"]),
        ("exception_candidate", inventory["exceptions"]),
        ("non_model_facing_exclusion", inventory["exclusions"]),
    ):
        for group in collection:
            for operation in group["operations"]:
                assert operation not in result
                result[operation] = (disposition, group["id"])
    return result


def test_inventory_exactly_covers_every_registry_operation_and_version_lane() -> None:
    inventory = _inventory()
    assignments = _assignments(inventory)
    assert len(assignments) == 34
    assert set(assignments) == set(OPERATION_SPECS)

    lanes = {
        (name, version)
        for name, spec in OPERATION_SPECS.items()
        for version in spec.supported_versions
    }
    assert len(lanes) == 153
    assert inventory["scope"]["registry_operations"] == len(assignments)
    assert inventory["scope"]["registry_version_lanes"] == len(lanes)

    lane_rows = []
    for name, spec in OPERATION_SPECS.items():
        modes = {operation_input_mode(name, version) for version in spec.supported_versions}
        expected_mode = LEGACY_JSON_INPUT_MODE
        if assignments[name][1] == "wave-00-complete" or name == "object.create":
            expected_mode = COMPOSER_INPUT_MODE
        elif assignments[name][1] in {
            "wave-01-single-object-edits",
            "wave-02-object-lifecycle",
        }:
            expected_mode = INLINE_TYPED_INPUT_MODE
        assert modes == {expected_mode}
        for version in spec.supported_versions:
            lane_rows.append(
                {
                    "operation": name,
                    "version": version,
                    "input_mode": operation_input_mode(name, version),
                    "disposition": assignments[name][0],
                    "assignment": assignments[name][1],
                }
            )

    lane_rows.sort(key=lambda row: (row["operation"], row["version"]))
    encoded = json.dumps(
        lane_rows,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == inventory["scope"]["lane_inventory_sha256"]
    assert sum(row["input_mode"] == COMPOSER_INPUT_MODE for row in lane_rows) == inventory["scope"]["composer_version_lanes"]
    assert sum(row["input_mode"] == INLINE_TYPED_INPUT_MODE for row in lane_rows) == inventory["scope"]["inline_typed_version_lanes"]
    assert sum(row["input_mode"] == LEGACY_JSON_INPUT_MODE for row in lane_rows) == inventory["scope"]["legacy_json_version_lanes"]


def test_every_assignment_has_reason_or_complete_wave_evidence() -> None:
    inventory = _inventory()
    for wave in inventory["waves"]:
        assert wave["status"] in {"complete", "planned"}
        assert wave["operations"]
        assert wave["reuse"]
        assert wave["isolation_regressions"]
        assert wave["minimum_real_evidence"]
    for group in (*inventory["exceptions"], *inventory["exclusions"]):
        assert group["operations"]
        assert group["reason"]
    for group in inventory["exclusions"]:
        for operation in group["operations"]:
            assert OPERATION_SPECS[operation].implemented is False


def test_human_inventory_names_every_exact_operation_once() -> None:
    rows = [
        line.split("`", 2)[1]
        for line in INVENTORY_DOC_PATH.read_text(encoding="utf-8").splitlines()
        if line.startswith("| `")
    ]
    assert len(rows) == 34
    assert len(set(rows)) == len(rows)
    assert set(rows) == set(OPERATION_SPECS)


def test_inventory_preserves_single_normal_input_and_exact_name_isolation() -> None:
    inventory = _inventory()
    assignments = _assignments(inventory)
    assert assignments["object.set"] == ("migration_wave", "wave-00-complete")
    assert assignments["object.setRTPC"] == ("migration_wave", "wave-02-object-graph")
    assert assignments["object.createPlugin"] == ("migration_wave", "wave-02-object-graph")
    assert {
        OPERATION_SPECS[name].uri
        for name in ("object.set", "object.setRTPC", "object.createPlugin")
    } == {"ak.wwise.core.object.set"}
    scope = inventory["scope"]
    assert "never chooses" in scope["normal_input_rule"]
    assert "exact operation name" in scope["native_uri_rule"]


def test_legacy_exit_is_a_later_evidence_decision_not_deletion_authority() -> None:
    inventory = _inventory()
    gates = {gate["id"]: gate["requirement"] for gate in inventory["legacy_exit_gates"]}
    assert set(gates) == {
        "all-lanes-decided",
        "normal-surface-single-entry",
        "consumer-inventory",
        "archive-and-replay",
        "cross-platform-release-evidence",
        "explicit-removal-decision",
    }
    assert "retain or remove" in gates["explicit-removal-decision"]
    assert "neither authorizes removal" in gates["explicit-removal-decision"]
    assert "macOS and native Windows" in gates["cross-platform-release-evidence"]
    assert "cumulative or failed roots" in gates["cross-platform-release-evidence"]
    second_round = inventory["second_round_ticketing"]
    assert len(second_round["required_ticket_slices"]) == 5
    assert "Legacy removal depends" in second_round["dependency_rule"]
