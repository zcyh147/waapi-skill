"""Offline public disclosure distinguishes new objects from existing ranges."""
import json
import pytest
from tests.unit.test_core_business_gateway import gateway

VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
RANGE = "ak.wwise.core.gameParameter.setRange"


def offline(version, *argv):
    def no_client(*args, **kwargs):
        raise AssertionError("offline disclosure must not connect")
    return gateway.execute_gateway(["--version", version, *argv], client_factory=no_client)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("detail", [False, True])
def test_directory_discloses_new_parameter_route_before_existing_range(version, detail):
    code, directory = offline(version, "operations", *(["--detail"] if detail else []))
    assert code == 0
    guidance = directory["selection_guidance"]
    creation = guidance["game_parameter_creation"]
    assert creation["choose"] == ["operation-schema", "object.create"]
    assert "new Game Parameter" in creation["use_when"]
    assert all(word in creation["use_when"] for word in ("minimum", "maximum", "default"))
    existing = guidance["game_parameter_range"]
    assert existing["choose"] == ["request-schema", RANGE]
    assert "existing Game Parameter" in existing["use_when"]
    assert "InitialValue" in existing["avoid_when"]
    row = next(row for row in directory["operations"] if row["name"] == "object.create")
    assert "GameParameter" in json.dumps(row)
    range_rows = [row for row in directory["request_schema_routes"] if row["api"] == RANGE]
    assert bool(range_rows) is (detail or version in {"2024.1", "2025.1"})
    if detail:
        assert range_rows[0]["supported_versions"] == ["2024.1", "2025.1"]
    if range_rows:
        assert "existing Game Parameter" in range_rows[0]["intent"]
        assert "InitialValue" in range_rows[0]["intent"]


@pytest.mark.parametrize("version", VERSIONS)
def test_creation_and_range_schemas_disclose_disjoint_business_outcomes(version):
    code, creation = offline(version, "operation-schema", "object.create")
    assert code == 0
    text = json.dumps(creation["operation"]["selection_guidance"])
    assert "new GameParameter" in text
    assert all(word in text for word in ("Min", "Max", "InitialValue"))
    code, existing = offline(version, "request-schema", RANGE)
    if version not in {"2024.1", "2025.1"}:
        assert code != 0
        return
    assert code == 0
    guidance = existing["business_adapter"]["selection_guidance"]
    assert "existing Game Parameter" in json.dumps(guidance["use_when"])
    assert "InitialValue" in json.dumps(guidance["avoid_when"])
    assert any(row["target"] == "object.create" and "new" in row["when"] for row in guidance["choose_instead"])
