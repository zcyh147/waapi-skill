from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from wwise_waapi.schema_inventory import (
    DEFINITION_GRAPH_CONTRACT,
    TYPED_REQUEST_SURFACE_CONTRACT,
    SchemaInventoryError,
    build_typed_request_surface,
    load_definition_graph,
    validate_schema_envelope,
    validate_packaged_typed_request_surface,
)
from wwise_waapi.manifest import DeterministicJsonWriter
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


RESOURCE_ROOT = Path("skills/waapi-skill/resources/manifest")


def test_packaged_definition_graphs_are_exact_version_resources() -> None:
    expected_builds = {
        "2021.1": "2021.1.14.8108",
        "2022.1": "2022.1.19.8584",
        "2023.1": "2023.1.19.8928",
        "2024.1": "2024.1.13.9056",
        "2025.1": "2025.1.7.9143",
    }

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        graph = load_definition_graph(version, root=RESOURCE_ROOT)

        assert graph.contract == DEFINITION_GRAPH_CONTRACT
        assert graph.version == version
        assert graph.wwise_build == expected_builds[version]
        assert graph.documents
        assert graph.inventory_sha256
        assert "objectArg" in graph.definition_names
        assert "propertyValue" in graph.definition_names


def test_schema_inventory_resources_have_deterministic_bytes() -> None:
    writer = DeterministicJsonWriter()
    paths = [
        RESOURCE_ROOT / version / "definitions.json"
        for version in SUPPORTED_WWISE_VERSION_KEYS
    ]
    paths.append(RESOURCE_ROOT / "typed-request-surface.json")

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert path.read_text(encoding="utf-8") == writer.dumps(payload)


def test_packaged_surface_closes_all_824_exact_lanes() -> None:
    result = validate_packaged_typed_request_surface(root=RESOURCE_ROOT)

    assert result["contract"] == TYPED_REQUEST_SURFACE_CONTRACT
    assert result["versions"] == list(SUPPORTED_WWISE_VERSION_KEYS)
    assert result["totals"] == {
        "function_lanes": 670,
        "topic_lanes": 154,
        "total_lanes": 824,
        "unique_function_uris": 167,
        "unique_topic_uris": 33,
    }
    assert result["unresolved_references"] == []
    assert result["unknown_schema_keywords"] == []
    assert result["intentionally_blocked_field_occurrences"] == 79
    blocked = [
        (row["version"], row["uri"], item["pointer"], item["field"])
        for row in result["lanes"]
        for item in row["intentionally_blocked_fields"]
    ]
    assert len(blocked) == 79
    assert (
        "2025.1",
        "ak.wwise.cli.generateSoundbank",
        "/argsSchema",
        "custom-pre-gen-cmd",
    ) in blocked
    assert (
        "2025.1",
        "ak.wwise.core.object.set",
        "/argsSchema/properties/objects/items",
        "pattern:^@[:_a-zA-Z0-9]+$",
    ) in blocked
    assert (
        "2025.1",
        "ak.wwise.core.executeLuaScript",
        "/argsSchema",
        "requires",
    ) in blocked
    soundbank_topic = next(
        row
        for row in result["lanes"]
        if row["version"] == "2025.1"
        and row["uri"] == "ak.wwise.core.soundbank.generated"
        and row["item_type"] == "topic"
    )
    assert soundbank_topic["execution_policy"]["timeout_seconds"] == 120.0
    assert soundbank_topic["execution_policy"]["result_limit_bytes"] == 262144
    assert soundbank_topic["execution_policy"]["gateway_commands"] == [
        "wait-topic",
        "stream-topic",
    ]
    assert soundbank_topic["execution_policy_sha256"]


def test_definition_graph_never_falls_back_to_another_version(tmp_path: Path) -> None:
    source = RESOURCE_ROOT / "2025.1" / "definitions.json"
    target = tmp_path / "2024.1"
    target.mkdir(parents=True)
    (target / "definitions.json").write_bytes(source.read_bytes())

    with pytest.raises(SchemaInventoryError, match="expected 2024.1"):
        load_definition_graph("2024.1", root=tmp_path)


def test_definition_graph_digest_detects_tampering(tmp_path: Path) -> None:
    source = RESOURCE_ROOT / "2025.1" / "definitions.json"
    target = tmp_path / "2025.1"
    target.mkdir(parents=True)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["documents"]["waapi_definitions.json"]["definitions"]["objectArg"] = {
        "type": "boolean"
    }
    (target / "definitions.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(SchemaInventoryError, match="inventory digest"):
        load_definition_graph("2025.1", root=tmp_path)


def test_2021_soundbank_legacy_implicit_properties_are_a_closed_known_shape() -> None:
    result = build_typed_request_surface(root=RESOURCE_ROOT)
    row = next(
        row
        for row in result["lanes"]
        if row["version"] == "2021.1"
        and row["uri"] == "ak.wwise.core.soundbank.generated"
        and row["item_type"] == "topic"
    )

    assert row["reference_count"] == 19
    assert result["unknown_schema_keywords"] == []


def test_surface_rejects_an_unresolved_same_version_reference(tmp_path: Path) -> None:
    shutil.copytree(RESOURCE_ROOT, tmp_path / "manifest")
    path = tmp_path / "manifest" / "2025.1" / "definitions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["documents"]["waapi_definitions.json"]["definitions"]["objectArg"]
    unsigned = dict(payload)
    unsigned.pop("inventory_sha256")
    payload["inventory_sha256"] = _canonical_sha256(unsigned)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = build_typed_request_surface(root=tmp_path / "manifest")

    assert any(
        row["version"] == "2025.1" and "objectArg" in row["reference"]
        for row in result["unresolved_references"]
    )
    with pytest.raises(SchemaInventoryError, match="unresolved same-version"):
        validate_packaged_typed_request_surface(root=tmp_path / "manifest")


def test_surface_rejects_an_unknown_schema_keyword(tmp_path: Path) -> None:
    shutil.copytree(RESOURCE_ROOT, tmp_path / "manifest")
    path = tmp_path / "manifest" / "2025.1" / "definitions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["documents"]["waapi_definitions.json"]["definitions"]["objectArg"][
        "mysteryKeyword"
    ] = True
    unsigned = dict(payload)
    unsigned.pop("inventory_sha256")
    payload["inventory_sha256"] = _canonical_sha256(unsigned)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = build_typed_request_surface(root=tmp_path / "manifest")

    assert any(
        row["version"] == "2025.1" and row["keyword"] == "mysteryKeyword"
        for row in result["unknown_schema_keywords"]
    )
    with pytest.raises(SchemaInventoryError, match="unknown schema keywords"):
        validate_packaged_typed_request_surface(root=tmp_path / "manifest")


def test_arbitrary_uppercase_schema_keyword_is_not_legacy_compatible(
    tmp_path: Path,
) -> None:
    shutil.copytree(RESOURCE_ROOT, tmp_path / "manifest")
    path = tmp_path / "manifest" / "2021.1" / "definitions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["documents"]["waapi_definitions.json"]["definitions"]["objectArg"][
        "InventedField"
    ] = {"type": "boolean"}
    unsigned = dict(payload)
    unsigned.pop("inventory_sha256")
    payload["inventory_sha256"] = _canonical_sha256(unsigned)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SchemaInventoryError, match="unknown schema keywords"):
        validate_packaged_typed_request_surface(root=tmp_path / "manifest")


def test_legacy_2021_soundbank_name_is_not_a_global_keyword_escape(
    tmp_path: Path,
) -> None:
    shutil.copytree(RESOURCE_ROOT, tmp_path / "manifest")
    path = tmp_path / "manifest" / "2025.1" / "definitions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["documents"]["waapi_definitions.json"]["definitions"]["objectArg"][
        "GameParameters"
    ] = {"type": "boolean"}
    unsigned = dict(payload)
    unsigned.pop("inventory_sha256")
    payload["inventory_sha256"] = _canonical_sha256(unsigned)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SchemaInventoryError, match="unknown schema keywords"):
        validate_packaged_typed_request_surface(root=tmp_path / "manifest")


@pytest.mark.parametrize(
    ("keyword", "bad_value", "message"),
    (
        ("properties", [{"$ref": "#/definitions/DOES_NOT_EXIST"}], "object"),
        ("oneOf", {"$ref": "#/definitions/DOES_NOT_EXIST"}, "array"),
        ("items", "not-a-schema", "object"),
    ),
)
def test_malformed_schema_container_never_hides_a_reference(
    tmp_path: Path,
    keyword: str,
    bad_value: object,
    message: str,
) -> None:
    shutil.copytree(RESOURCE_ROOT, tmp_path / "manifest")
    path = tmp_path / "manifest" / "2025.1" / "definitions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["documents"]["waapi_definitions.json"]["definitions"]["objectArg"][
        keyword
    ] = bad_value
    unsigned = dict(payload)
    unsigned.pop("inventory_sha256")
    payload["inventory_sha256"] = _canonical_sha256(unsigned)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SchemaInventoryError, match=message):
        validate_packaged_typed_request_surface(root=tmp_path / "manifest")


def test_unknown_schema_envelope_section_blocks_the_inventory() -> None:
    unknown = validate_schema_envelope(
        {
            "argsSchema": {"type": "object"},
            "optionsSchema": {"type": "object"},
            "resultSchema": {"type": "object"},
            "requestSchema": {"type": "object"},
        },
        version="2025.1",
        uri="ak.example.future",
    )

    assert unknown == [
        {
            "version": "2025.1",
            "uri": "ak.example.future",
            "section": "<envelope>",
            "pointer": "/",
            "keyword": "requestSchema",
        }
    ]


def test_malformed_known_schema_envelope_section_fails_closed() -> None:
    with pytest.raises(SchemaInventoryError, match="argsSchema.*must be an object"):
        validate_schema_envelope(
            {"argsSchema": []},
            version="2025.1",
            uri="ak.example.future",
        )


def test_execution_policy_drift_changes_the_lane_contract() -> None:
    result = build_typed_request_surface(root=RESOURCE_ROOT)
    row = next(
        row
        for row in result["lanes"]
        if row["version"] == "2025.1"
        and row["uri"] == "ak.wwise.core.soundbank.generated"
        and row["item_type"] == "topic"
    )
    original_digest = row["execution_policy_sha256"]
    changed = dict(row["execution_policy"])
    changed["timeout_seconds"] = 121.0

    assert _canonical_sha256(changed) != original_digest


def test_surface_digest_detects_lane_or_policy_drift(tmp_path: Path) -> None:
    shutil.copytree(RESOURCE_ROOT, tmp_path / "manifest")
    surface = tmp_path / "manifest" / "typed-request-surface.json"
    payload = json.loads(surface.read_text(encoding="utf-8"))
    payload["lanes"][0]["correct_host"] = "invented-host"
    unsigned = dict(payload)
    unsigned.pop("inventory_sha256")
    payload["inventory_sha256"] = _canonical_sha256(unsigned)
    surface.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SchemaInventoryError, match="does not match"):
        validate_packaged_typed_request_surface(root=tmp_path / "manifest")


def _canonical_sha256(value: object) -> str:
    import hashlib

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
