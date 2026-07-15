from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.capabilities import (
    FIXED_COMMANDS_BY_URI,
    CapabilityCatalog,
    CapabilityCatalogError,
    CapabilityNotFoundError,
    CapabilityRecord,
)
from wwise_waapi.safety import (
    BOUNDED_CALL_CANDIDATES,
    EXPLICIT_UNSUPPORTED_LIVE_URIS,
    IMMEDIATE_UNSUPPORTED_CALL_URIS,
    REVIEWED_FIXED_FUNCTION_URIS,
    REVIEWED_PUBLIC_CALL_URIS,
    REVIEWED_TOPIC_URIS,
)
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOT = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "manifest"
EXPECTED_COUNTS = {
    "2021.1": (99, 27),
    "2022.1": (112, 32),
    "2023.1": (149, 32),
    "2024.1": (148, 30),
    "2025.1": (154, 31),
}


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_catalog_exactly_reconciles_every_manifest_function_topic_and_schema(version: str) -> None:
    catalog = CapabilityCatalog()
    entries = catalog.entries(version)
    functions = json.loads((MANIFEST_ROOT / version / "functions.json").read_text(encoding="utf-8"))["functions"]
    topics = json.loads((MANIFEST_ROOT / version / "topics.json").read_text(encoding="utf-8"))["topics"]
    expected = {(entry["uri"], "function") for entry in functions}
    expected.update((entry["uri"], "topic") for entry in topics)

    assert {(entry.uri, entry.item_type) for entry in entries} == expected
    assert (sum(entry.item_type == "function" for entry in entries), sum(entry.item_type == "topic" for entry in entries)) == EXPECTED_COUNTS[version]
    assert {entry.schema_status for entry in entries} == {"ok"}


def test_catalog_separates_route_safety_and_evidence_without_overclaiming() -> None:
    catalog = CapabilityCatalog()
    read = catalog.describe("2025.1", "ak.wwise.core.object.get")
    closed_mutation = catalog.describe("2025.1", "ak.wwise.core.object.create")
    mutation = catalog.describe("2025.1", "ak.wwise.core.soundbank.generate")
    assignment = catalog.describe("2025.1", "ak.wwise.core.switchContainer.addAssignment")
    unsafe = catalog.describe("2025.1", "ak.wwise.debug.testCrash")

    assert read.preferred_route == "fixed_command"
    assert read.fixed_commands == ("query-object", "buses")
    assert read.gateway_commands == ("query-object", "buses")
    assert read.safety.read_only is True
    assert read.safety.requires_destructive_gate is False
    assert closed_mutation.preferred_route == "transaction_operation"
    assert closed_mutation.transaction_operations == ("object.create",)
    assert closed_mutation.gateway_commands == (
        "operation-schema",
        "preview",
        "transaction-show",
        "confirm",
        "reject",
        "execute",
        "verify",
    )
    assert closed_mutation.safety.interface_status == "available_via_transaction"
    assert mutation.semantic_family == "soundbank"
    assert mutation.safety.requires_destructive_gate is True
    assert mutation.safety.requires_confirmation is True
    assert mutation.preferred_route == "unsupported_boundary"
    assert mutation.safety.interface_status == "unsupported_by_skill_interface"
    assert assignment.safety.requires_destructive_gate is True
    assert unsafe.preferred_route == "unsupported_boundary"
    assert unsafe.safety.interface_status == "unsupported_by_skill_interface"
    assert read.evidence["registry_status"] in {"deferred", "not_listed_in_packaged_deferred_registry"}


def test_catalog_uses_closed_operation_registry_as_mutation_interface_truth() -> None:
    catalog = CapabilityCatalog()

    create = catalog.describe("2021.1", "ak.wwise.core.object.create")
    set_name = catalog.describe("2025.1", "ak.wwise.core.object.setName")
    batch = catalog.describe("2025.1", "ak.wwise.core.object.set")
    copy = catalog.describe("2025.1", "ak.wwise.core.object.copy")
    audio_import = catalog.describe("2025.1", "ak.wwise.core.audio.import")
    tab_import = catalog.describe("2025.1", "ak.wwise.core.audio.importTabDelimited")

    assert create.transaction_operations == ("object.create",)
    assert set_name.transaction_operations == ("object.setName",)
    assert create.preferred_route == set_name.preferred_route == "transaction_operation"
    assert batch.transaction_operations == ()
    assert batch.transaction_boundaries == (
        {
            "operation": "object.set",
            "boundary": "Batch partial-success semantics and per-field readback are not yet closed; 2021.1 also lacks the URI.",
        },
    )
    assert copy.transaction_boundaries[0]["operation"] == "object.copy"
    assert audio_import.transaction_operations == ("audio.import",)
    assert audio_import.preferred_route == "transaction_operation"
    assert tab_import.transaction_operations == ()
    assert tab_import.transaction_boundaries[0]["operation"] == "audio.importTabDelimited"
    for unsupported in (batch, copy, tab_import):
        assert unsupported.preferred_route == "unsupported_boundary"
        assert unsupported.safety.interface_status == "unsupported_by_skill_interface"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_only_reviewed_topics_expose_a_bounded_wait_route(version: str) -> None:
    topics = CapabilityCatalog().select(version, item_type="topic")
    reviewed = [entry for entry in topics if entry.uri in REVIEWED_TOPIC_URIS]
    unsupported = [entry for entry in topics if entry.uri not in REVIEWED_TOPIC_URIS]

    assert topics
    assert {entry.execution_mode for entry in topics} == {"bounded_topic_wait"}
    assert reviewed
    assert all(entry.preferred_route == "bounded_topic_wait" for entry in reviewed)
    assert all(entry.gateway_commands == ("wait-topic",) for entry in reviewed)
    assert all(entry.safety.read_only for entry in reviewed)
    assert all(not entry.safety.requires_destructive_gate for entry in reviewed)
    assert all(entry.preferred_route == "unsupported_boundary" for entry in unsupported)
    assert all(entry.gateway_commands == () for entry in unsupported)
    assert all(not entry.safety.read_only for entry in unsupported)
    assert all(entry.safety.requires_destructive_gate for entry in unsupported)


def test_semantic_inventory_is_version_aware_and_bounded_candidates_stay_closed() -> None:
    catalog = CapabilityCatalog()

    with pytest.raises(CapabilityNotFoundError, match="not reflected"):
        catalog.describe("2021.1", "ak.wwise.core.object.set")
    linked = catalog.describe("2025.1", "ak.wwise.core.object.isLinked")
    assert linked.semantic_family == "property-reference"
    assert linked.safety.read_only is False
    assert linked.safety.interface_status == "unsupported_by_skill_interface"
    assert linked.preferred_route == "unsupported_boundary"
    assert linked.gateway_commands == ()
    assert linked.safety.reason == BOUNDED_CALL_CANDIDATES[linked.uri]


def test_catalog_summary_reconciles_all_five_version_totals() -> None:
    summary = CapabilityCatalog().summary(SUPPORTED_WWISE_VERSION_KEYS)

    assert summary["totals"]["functions"] == 662
    assert summary["totals"]["topics"] == 152
    assert summary["totals"]["total"] == 814
    assert summary["totals"]["schema_status"] == {"ok": 814}
    assert summary["totals"]["interface_status"] == {
        "available": 193,
        "available_via_transaction": 50,
        "unsupported_by_skill_interface": 571,
    }
    assert summary["totals"]["preferred_routes"] == {
        "bounded_topic_wait": 141,
        "fixed_command": 42,
        "manifest_dispatch": 10,
        "transaction_operation": 50,
        "unsupported_boundary": 571,
    }
    assert "semantic_builder" not in summary["totals"]["preferred_routes"]
    for version, (functions, topics) in EXPECTED_COUNTS.items():
        assert summary["by_version"][version]["functions"] == functions
        assert summary["by_version"][version]["topics"] == topics


def test_all_semantic_read_records_resolve_to_public_gateway_routes() -> None:
    catalog = CapabilityCatalog()
    entries = [entry for version in SUPPORTED_WWISE_VERSION_KEYS for entry in catalog.entries(version)]
    semantic_reads = [entry for entry in entries if entry.semantic_family is not None and entry.safety.read_only]

    assert len(semantic_reads) == 55
    assert sum(entry.preferred_route == "fixed_command" for entry in semantic_reads) == 30
    assert sum(entry.preferred_route == "bounded_topic_wait" for entry in semantic_reads) == 25
    assert sum(entry.preferred_route == "manifest_dispatch" for entry in semantic_reads) == 0
    assert all(entry.preferred_route != "semantic_builder" for entry in entries)
    assert all(
        entry.gateway_commands
        for entry in entries
        if entry.safety.interface_status != "unsupported_by_skill_interface"
    )

    object_get = catalog.describe("2022.1", "ak.wwise.core.object.get")
    property_info = catalog.describe("2022.1", "ak.wwise.core.object.getPropertyInfo")
    imported = catalog.describe("2022.1", "ak.wwise.core.audio.imported")
    inclusions = catalog.describe("2022.1", "ak.wwise.core.soundbank.getInclusions")
    assert object_get.gateway_commands == ("query-object", "buses")
    assert property_info.gateway_commands == ("metadata property-info",)
    assert imported.gateway_commands == ("wait-topic",)
    assert inclusions.gateway_commands == ()
    assert inclusions.preferred_route == "unsupported_boundary"
    assert inclusions.safety.reason == BOUNDED_CALL_CANDIDATES[inclusions.uri]

    public = object_get.as_dict(detail=True)["interface"]
    assert "semantic_builder_ref" not in public
    assert public["gateway_commands"] == ["query-object", "buses"]


def test_public_manifest_dispatch_is_exactly_the_immutable_reviewed_call_allowlist() -> None:
    catalog = CapabilityCatalog()
    entries = [entry for version in SUPPORTED_WWISE_VERSION_KEYS for entry in catalog.entries(version)]
    public_calls = {entry.uri for entry in entries if entry.preferred_route == "manifest_dispatch"}
    public_fixed = {entry.uri for entry in entries if entry.preferred_route == "fixed_command"}
    public_topics = {entry.uri for entry in entries if entry.preferred_route == "bounded_topic_wait"}

    assert REVIEWED_PUBLIC_CALL_URIS == frozenset(
        {
            "ak.wwise.waapi.getFunctions",
            "ak.wwise.waapi.getTopics",
        }
    )
    assert public_calls == REVIEWED_PUBLIC_CALL_URIS
    assert public_fixed == REVIEWED_FIXED_FUNCTION_URIS
    assert public_topics == REVIEWED_TOPIC_URIS
    assert frozenset(FIXED_COMMANDS_BY_URI) == REVIEWED_FIXED_FUNCTION_URIS
    assert all(
        entry.gateway_commands == ("call",)
        for entry in entries
        if entry.preferred_route == "manifest_dispatch"
    )


def test_audited_non_generic_reads_are_exact_disjoint_structured_boundaries() -> None:
    expected_candidates = {
        "ak.soundengine.getState",
        "ak.soundengine.getSwitch",
        "ak.wwise.core.blendContainer.getAssignments",
        "ak.wwise.core.mediaPool.getFields",
        "ak.wwise.core.object.diff",
        "ak.wwise.core.object.isLinked",
        "ak.wwise.core.ping",
        "ak.wwise.core.profiler.getAudioObjects",
        "ak.wwise.core.profiler.getBusses",
        "ak.wwise.core.profiler.getCursorTime",
        "ak.wwise.core.profiler.getPerformanceMonitor",
        "ak.wwise.core.profiler.getVoiceContributions",
        "ak.wwise.core.profiler.getVoices",
        "ak.wwise.core.remote.getConnectionStatus",
        "ak.wwise.core.soundbank.getInclusions",
        "ak.wwise.core.switchContainer.getAssignments",
        "ak.wwise.core.transport.getList",
        "ak.wwise.core.transport.getState",
        "ak.wwise.ui.commands.getCommands",
        "ak.wwise.waapi.getSchema",
    }
    expected_immediate = {
        "ak.wwise.core.log.get",
        "ak.wwise.core.profiler.getCpuUsage",
        "ak.wwise.core.profiler.getGameObjects",
        "ak.wwise.core.profiler.getLoadedMedia",
        "ak.wwise.core.profiler.getMeters",
        "ak.wwise.core.profiler.getRTPCs",
        "ak.wwise.core.profiler.getStreamedMedia",
        "ak.wwise.core.remote.getAvailableConsoles",
        "ak.wwise.debug.validateCall",
    }

    assert set(BOUNDED_CALL_CANDIDATES) == expected_candidates
    assert IMMEDIATE_UNSUPPORTED_CALL_URIS == expected_immediate
    assert expected_immediate <= set(EXPLICIT_UNSUPPORTED_LIVE_URIS)
    assert not (REVIEWED_PUBLIC_CALL_URIS & expected_candidates)
    assert not (REVIEWED_PUBLIC_CALL_URIS & expected_immediate)
    assert not (expected_candidates & expected_immediate)

    catalog = CapabilityCatalog()
    records_by_uri: dict[str, list[CapabilityRecord]] = {
        uri: [] for uri in expected_candidates | expected_immediate
    }
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for record in catalog.entries(version):
            if record.uri in records_by_uri:
                records_by_uri[record.uri].append(record)

    assert all(records_by_uri.values())
    for uri, records in records_by_uri.items():
        expected_reason = (
            BOUNDED_CALL_CANDIDATES[uri]
            if uri in BOUNDED_CALL_CANDIDATES
            else EXPLICIT_UNSUPPORTED_LIVE_URIS[uri]
        )
        for record in records:
            assert record.safety.interface_status == "unsupported_by_skill_interface"
            assert record.safety.read_only is False
            assert record.preferred_route == "unsupported_boundary"
            assert record.gateway_commands == ()
            assert record.safety.reason == expected_reason


@pytest.mark.parametrize("operation", ("getUnreviewed", "verifyUnreviewed", "dumpUnreviewed"))
def test_future_name_shaped_manifest_function_fails_closed(
    tmp_path: Path,
    operation: str,
) -> None:
    manifest_root = tmp_path / "manifest"
    shutil.copytree(MANIFEST_ROOT / "2022.1", manifest_root / "2022.1")
    uri = f"ak.wwise.core.future.{operation}"
    functions_path = manifest_root / "2022.1" / "functions.json"
    functions_payload = json.loads(functions_path.read_text(encoding="utf-8"))
    functions_payload["functions"].append(
        {"reflection": {"uri": uri}, "type": "function", "uri": uri}
    )
    functions_path.write_text(json.dumps(functions_payload), encoding="utf-8")
    schemas_path = manifest_root / "2022.1" / "schemas.json"
    schemas_payload = json.loads(schemas_path.read_text(encoding="utf-8"))
    schemas_payload["schemas"].append(
        {
            "status": "ok",
            "uri": uri,
            "schema": {
                "argsSchema": {"type": "object", "additionalProperties": False},
                "optionsSchema": {"type": "object", "additionalProperties": False},
                "returnSchema": {"type": "object"},
            },
        }
    )
    schemas_path.write_text(json.dumps(schemas_payload), encoding="utf-8")

    record = CapabilityCatalog(manifest_root=manifest_root).describe("2022.1", uri)

    assert record.safety.read_only is False
    assert record.safety.interface_status == "unsupported_by_skill_interface"
    assert record.preferred_route == "unsupported_boundary"
    assert record.gateway_commands == ()
    assert "not in the immutable reviewed read-only function allowlist" in record.safety.reason


def test_future_manifest_topic_fails_closed_until_explicitly_reviewed(tmp_path: Path) -> None:
    manifest_root = tmp_path / "manifest"
    shutil.copytree(MANIFEST_ROOT / "2022.1", manifest_root / "2022.1")
    uri = "ak.wwise.core.future.changed"
    topics_path = manifest_root / "2022.1" / "topics.json"
    topics_payload = json.loads(topics_path.read_text(encoding="utf-8"))
    topics_payload["topics"].append(
        {"reflection": {"uri": uri}, "type": "topic", "uri": uri}
    )
    topics_path.write_text(json.dumps(topics_payload), encoding="utf-8")
    schemas_path = manifest_root / "2022.1" / "schemas.json"
    schemas_payload = json.loads(schemas_path.read_text(encoding="utf-8"))
    schemas_payload["schemas"].append(
        {
            "status": "ok",
            "uri": uri,
            "schema": {
                "argsSchema": {"type": "object", "additionalProperties": False},
                "returnSchema": {"type": "object"},
            },
        }
    )
    schemas_path.write_text(json.dumps(schemas_payload), encoding="utf-8")

    record = CapabilityCatalog(manifest_root=manifest_root).describe("2022.1", uri)

    assert record.safety.read_only is False
    assert record.safety.interface_status == "unsupported_by_skill_interface"
    assert record.preferred_route == "unsupported_boundary"
    assert record.gateway_commands == ()
    assert "not in the immutable reviewed topic allowlist" in record.safety.reason


def test_compact_capability_representation_is_stable_and_keeps_boundaries_visible() -> None:
    record = CapabilityCatalog().describe("2025.1", "ak.wwise.core.object.copy")

    compact = record.as_compact_dict()

    assert set(compact) == {
        "version",
        "uri",
        "item_type",
        "category",
        "risk",
        "schema_status",
        "interface_status",
        "preferred_route",
        "gateway_commands",
        "transaction_operations",
        "transaction_boundaries",
        "read_only",
    }
    assert compact["interface_status"] == "unsupported_by_skill_interface"
    assert compact["preferred_route"] == "unsupported_boundary"
    assert compact["transaction_operations"] == []
    assert compact["transaction_boundaries"][0]["operation"] == "object.copy"
    assert "returned copy GUID" in compact["transaction_boundaries"][0]["boundary"]


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_dump_objects_external_file_write_is_an_explicit_boundary(version: str) -> None:
    record = CapabilityCatalog().describe(version, "ak.wwise.cli.dumpObjects")

    assert record.safety.read_only is False
    assert record.safety.interface_status == "unsupported_by_skill_interface"
    assert record.preferred_route == "unsupported_boundary"
    assert record.gateway_commands == ()
    assert "output path" in record.safety.reason
    assert "external file" in record.safety.reason


def test_all_explicit_function_safety_boundaries_are_reflected_and_non_executable() -> None:
    catalog = CapabilityCatalog()
    reflected: dict[str, list[object]] = {uri: [] for uri in EXPLICIT_UNSUPPORTED_LIVE_URIS}
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for entry in catalog.entries(version):
            if entry.uri in reflected:
                reflected[entry.uri].append(entry)

    assert all(reflected.values())
    for uri, records in reflected.items():
        for record in records:
            assert record.safety.read_only is False
            assert record.safety.interface_status == "unsupported_by_skill_interface"
            assert record.preferred_route == "unsupported_boundary"
            assert record.gateway_commands == ()
            assert record.safety.reason == EXPLICIT_UNSUPPORTED_LIVE_URIS[uri]


def test_catalog_rejects_unknown_version_and_filter_type() -> None:
    catalog = CapabilityCatalog()

    with pytest.raises(CapabilityCatalogError, match="Unsupported Wwise version"):
        catalog.entries("2030.1")
    with pytest.raises(CapabilityCatalogError, match="item_type"):
        catalog.select("2022.1", item_type="event")
