"""Audit through the maintainer generator and its independent source boundary."""
from __future__ import annotations

from tests.maintenance.branch_coverage_audit import schema_branches


def test_schema_inventory_retains_optional_enum_union_and_nested_collection_branches():
    schema = {"type": "object", "properties": {
        "mode": {"enum": ["create", "replace"]},
        "children": {"type": "array", "items": {"oneOf": [
            {"type": "string"}, {"type": "integer"}]}}
    }, "required": ["children"]}
    branches = {row["pointer"]: row for row in schema_branches(schema)}
    assert branches["/properties/mode/enum/1"]["value"] == "replace"
    assert branches["/properties/mode/@presence/absent"]["value"] == "absent"
    assert "/properties/children/@presence/absent" not in branches
    assert branches["/properties/children/items/oneOf/1"]["value"] == {"type": "integer"}


def test_independent_reflection_rejects_same_count_route_substitution():
    import json
    import pytest
    from tests.maintenance.branch_coverage_audit import ROOT, build_inventory
    surface = json.loads((ROOT / "skills/waapi-skill/resources/manifest/typed-request-surface.json").read_text())
    surface["lanes"][0]["uri"] = "ak.wwise.invented.sameCount"
    with pytest.raises(ValueError, match="route partition mismatch"):
        build_inventory(surface=surface)


def test_checker_rejects_removed_branch_mapping_and_shareset_false_completion():
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import build_inventory, check_inventory
    inventory = build_inventory()
    assert check_inventory(inventory) == []
    missing = deepcopy(inventory)
    del missing["branches"][0]["mapping"]
    assert "branch ledger differs" in check_inventory(missing)
    dishonest = deepcopy(inventory)
    shareset = next(row for row in dishonest["business_branches"] if row["id"] == "2025.1|independent-effect-shareset")
    shareset["implementation"] = "complete"
    assert "business ledger differs" in check_inventory(dishonest)


def test_cli_distinguishes_reproducible_inventory_from_complete_coverage(tmp_path):
    import subprocess
    import sys
    from tests.maintenance.branch_coverage_audit import ROOT
    path = tmp_path / "audit.json"
    command = [sys.executable, str(ROOT / "tests/maintenance/branch_coverage_audit.py"), "--output", str(path)]
    generated = subprocess.run(command, capture_output=True, text=True)
    assert generated.returncode == 0, generated.stderr
    checked = subprocess.run(command + ["--check", "--require-complete"], capture_output=True, text=True)
    assert checked.returncode == 2, checked.stderr
    assert '"business_coverage": "incomplete"' in checked.stdout
    path.write_text('{"contract":"waapi-skill.branch-audit/v1"}')
    damaged = subprocess.run(command + ["--check"], capture_output=True, text=True)
    assert damaged.returncode == 1
    assert "branch ledger differs" in damaged.stdout


def test_schema_type_unions_and_unfamiliar_nested_keywords_cannot_disappear():
    branches = {row["pointer"]: row for row in schema_branches({
        "type": ["string", "null"], "futureBranch": {"enum": ["new"]}})}
    assert branches["/type/1"]["value"] == "null"
    assert branches["/futureBranch"]["kind"] == "unreviewed_keyword"
