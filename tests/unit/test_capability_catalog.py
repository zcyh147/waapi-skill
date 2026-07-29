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
)
from wwise_waapi.safety import (
    BOUNDED_CALL_CANDIDATES,
    EXPLICIT_UNSUPPORTED_LIVE_URIS,
    EXPLICIT_UNSUPPORTED_TOPIC_URIS,
    IMMEDIATE_UNSUPPORTED_CALL_URIS,
    REVIEWED_FIXED_FUNCTION_URIS,
    REVIEWED_PUBLIC_CALL_URIS,
    REVIEWED_TOPIC_URIS,
)
from wwise_waapi.selection_guidance import CAPABILITY_SELECTION_GUIDANCE
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
    assert closed_mutation.gateway_commands == ("preview", "confirm", "execute", "verify")
    assert closed_mutation.safety.interface_status == "available_via_transaction"
    assert mutation.semantic_family == "soundbank"
    assert mutation.safety.requires_destructive_gate is True
    assert mutation.safety.requires_authorization is True
    assert mutation.preferred_route == "transaction_operation"
    assert mutation.transaction_operations == ("soundbank.generate",)
    assert mutation.safety.interface_status == "available_via_transaction"
    assert assignment.safety.requires_destructive_gate is True
    assert assignment.transaction_operations == ("switchContainer.addAssignment",)
    assert unsafe.preferred_route == "transaction_operation"
    assert unsafe.transaction_operations == ("debug.testCrash",)
    assert unsafe.safety.interface_status == "available_via_transaction"
    assert read.evidence["registry_status"] in {"deferred", "not_listed_in_packaged_deferred_registry"}


def test_describe_exposes_selection_guidance_for_ambiguous_native_routes() -> None:
    catalog = CapabilityCatalog()

    set_range = catalog.describe(
        "2025.1",
        "ak.wwise.core.gameParameter.setRange",
    )
    set_range_guidance = set_range.as_dict()["interface"]["selection_guidance"]
    assert set_range_guidance["domain"] == "authoring_project_model"
    assert {
        item["target"] for item in set_range_guidance["preferred_over"]
    } == {"object.setProperty", "object.set"}

    runtime_rtpc = catalog.describe("2025.1", "ak.soundengine.setRTPCValue")
    runtime_guidance = runtime_rtpc.as_dict()["interface"]["selection_guidance"]
    assert runtime_guidance["domain"] == "runtime_soundengine"
    assert runtime_guidance["choose_instead"][0]["target"] == "object.setRTPC"

    transport = catalog.describe("2025.1", "ak.wwise.core.transport.create")
    assert (
        transport.as_dict()["interface"]["selection_guidance"]["domain"]
        == "authoring_audition"
    )

    generated = catalog.describe(
        "2025.1",
        "ak.wwise.core.soundbank.generated",
    ).as_dict()["interface"]["selection_guidance"]
    generation_done = catalog.describe(
        "2025.1",
        "ak.wwise.core.soundbank.generationDone",
    ).as_dict()["interface"]["selection_guidance"]
    assert generated["choose_instead"][0]["target"].endswith("generationDone")
    assert any("proof" in item for item in generation_done["avoid_when"])

    source_control = catalog.describe(
        "2025.1",
        "ak.wwise.core.sourceControl.add",
    ).as_dict()["interface"]["selection_guidance"]
    assert source_control["domain"] == "authoring_source_control"
    assert "auto_add_to_source_control" in source_control["choose_instead"][0]["target"]

    set_cursor = catalog.describe(
        "2025.1",
        "ak.wwise.core.profiler.setCursorTime",
    ).as_dict()["interface"]["selection_guidance"]
    assert set_cursor["choose_instead"][0]["target"].endswith("moveCursor")

    ordinary_read = catalog.describe("2025.1", "ak.wwise.core.object.get")
    assert "selection_guidance" not in ordinary_read.as_dict()["interface"]
    assert "selection_guidance" not in set_range.as_compact_dict()


def test_every_reflected_soundengine_route_exposes_runtime_domain_guidance() -> None:
    catalog = CapabilityCatalog()

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        soundengine_uris = {
            entry.uri
            for entry in catalog.entries(version)
            if entry.uri.startswith("ak.soundengine.")
        }
        assert soundengine_uris
        for uri in soundengine_uris:
            guidance = catalog.describe(version, uri).as_dict()["interface"][
                "selection_guidance"
            ]
            assert guidance["domain"] == "runtime_soundengine", (version, uri)
            assert guidance["use_when"], (version, uri)
            assert guidance["avoid_when"], (version, uri)

    generic = catalog.describe(
        "2025.1",
        "ak.soundengine.setPosition",
    ).as_dict()["interface"]["selection_guidance"]
    assert generic["choose_instead"][0]["target"].endswith("ak.wwise.core.* route")

    exact = catalog.describe(
        "2025.1",
        "ak.soundengine.setRTPCValue",
    ).as_dict()["interface"]["selection_guidance"]
    assert exact["choose_instead"][0]["target"] == "object.setRTPC"


def test_selection_guidance_registry_contains_only_reflected_bounded_records() -> None:
    catalog = CapabilityCatalog()
    reflected_uris = {
        entry.uri
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for entry in catalog.entries(version)
    }

    assert set(CAPABILITY_SELECTION_GUIDANCE) <= reflected_uris
    assert len(CAPABILITY_SELECTION_GUIDANCE) >= 38
    for uri, guidance in CAPABILITY_SELECTION_GUIDANCE.items():
        assert set(guidance) == {
            "principle",
            "domain",
            "use_when",
            "avoid_when",
            "preferred_over",
            "choose_instead",
        }
        assert guidance["domain"]
        assert guidance["use_when"]
        for relation in ("preferred_over", "choose_instead"):
            assert all(
                set(item) == {"target", "when"}
                for item in guidance[relation]
            ), uri


def test_2025_media_pool_reads_use_the_bounded_direct_route() -> None:
    catalog = CapabilityCatalog()

    for uri in (
        "ak.wwise.core.mediaPool.get",
        "ak.wwise.core.mediaPool.getFields",
    ):
        capability = catalog.describe("2025.1", uri)
        assert capability.preferred_route == "manifest_dispatch"
        assert capability.gateway_commands == ("call",)
        assert capability.safety.read_only is True
        assert capability.safety.requires_authorization is False


def test_catalog_keeps_specific_builder_boundaries_and_hides_generic_bypass() -> None:
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
    assert batch.transaction_operations == (
        "object.createPlugin",
        "object.set",
        "object.setRTPC",
    )
    assert batch.transaction_boundaries == ()
    assert copy.transaction_boundaries[0]["operation"] == "object.copy"
    assert copy.transaction_operations == ("waapi.call",)
    assert audio_import.transaction_operations == ("audio.import",)
    assert audio_import.preferred_route == "transaction_operation"
    assert tab_import.transaction_operations == ("audio.importTabDelimited",)
    assert tab_import.transaction_boundaries == ()
    for generic in (batch, copy, tab_import):
        assert generic.preferred_route == "transaction_operation"
        assert generic.gateway_commands == ("preview", "confirm", "execute", "verify")
        assert generic.safety.interface_status == "available_via_transaction"
        assert generic.safety.requires_authorization is True


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_all_topics_expose_a_bounded_wait_route(version: str) -> None:
    topics = CapabilityCatalog().select(version, item_type="topic")
    reviewed = [entry for entry in topics if entry.uri in REVIEWED_TOPIC_URIS]
    unsupported = [entry for entry in topics if entry.uri not in REVIEWED_TOPIC_URIS]

    assert topics
    assert {entry.execution_mode for entry in topics} == {"bounded_topic_wait"}
    assert reviewed
    assert all(entry.preferred_route == "bounded_topic_wait" for entry in reviewed)
    assert all(
        entry.gateway_commands == ("wait-topic", "stream-topic")
        for entry in reviewed
    )
    assert all(entry.safety.read_only for entry in reviewed)
    assert all(not entry.safety.requires_destructive_gate for entry in reviewed)
    assert unsupported == []


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_soundbank_generated_has_the_reviewed_long_running_timeout(version: str) -> None:
    catalog = CapabilityCatalog()

    generated = catalog.describe(version, "ak.wwise.core.soundbank.generated")
    ordinary = catalog.describe(version, "ak.wwise.core.object.created")

    assert generated.execution_contract["timeout_seconds"] == 120.0
    assert ordinary.execution_contract["timeout_seconds"] == 10.0


def test_semantic_inventory_is_version_aware_and_bounded_reads_are_public() -> None:
    catalog = CapabilityCatalog()

    with pytest.raises(CapabilityNotFoundError, match="not reflected"):
        catalog.describe("2021.1", "ak.wwise.core.object.set")
    linked = catalog.describe("2025.1", "ak.wwise.core.object.isLinked")
    assert linked.semantic_family == "property-reference"
    assert linked.safety.read_only is True
    assert linked.safety.interface_status == "available"
    assert linked.preferred_route == "manifest_dispatch"
    assert linked.gateway_commands == ("call",)
    assert linked.execution_contract["timeout_seconds"] == 10.0
    assert linked.execution_contract["result_limit_bytes"] == 256 * 1024


def test_catalog_summary_reconciles_all_five_version_totals() -> None:
    summary = CapabilityCatalog().summary(SUPPORTED_WWISE_VERSION_KEYS)

    assert summary["totals"]["functions"] == 662
    assert summary["totals"]["topics"] == 152
    assert summary["totals"]["total"] == 814
    assert summary["totals"]["schema_status"] == {"ok": 814}
    assert summary["totals"]["interface_status"] == {
        "available": 268,
        "available_via_transaction": 540,
        "unsupported_by_skill_interface": 6,
    }
    assert summary["totals"]["preferred_routes"] == {
        "bounded_topic_wait": 152,
        "fixed_command": 56,
        "manifest_dispatch": 60,
        "transaction_operation": 540,
        "unsupported_boundary": 6,
    }
    assert "semantic_builder" not in summary["totals"]["preferred_routes"]
    for version, (functions, topics) in EXPECTED_COUNTS.items():
        assert summary["by_version"][version]["functions"] == functions
        assert summary["by_version"][version]["topics"] == topics


def test_all_semantic_read_records_resolve_to_public_gateway_routes() -> None:
    catalog = CapabilityCatalog()
    entries = [entry for version in SUPPORTED_WWISE_VERSION_KEYS for entry in catalog.entries(version)]
    semantic_reads = [entry for entry in entries if entry.semantic_family is not None and entry.safety.read_only]

    assert len(semantic_reads) == 71
    assert sum(entry.preferred_route == "fixed_command" for entry in semantic_reads) == 30
    assert sum(entry.preferred_route == "bounded_topic_wait" for entry in semantic_reads) == 25
    assert sum(entry.preferred_route == "manifest_dispatch" for entry in semantic_reads) == 6
    assert sum(entry.preferred_route == "transaction_operation" for entry in semantic_reads) == 10
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
    assert property_info.gateway_commands == (
        "metadata property-info",
        "metadata discover",
    )
    assert imported.gateway_commands == ("wait-topic", "stream-topic")
    assert inclusions.gateway_commands == ("preview", "confirm", "execute", "verify")
    assert inclusions.preferred_route == "transaction_operation"
    assert inclusions.transaction_operations == ("waapi.call",)
    assert inclusions.safety.read_only is True
    assert inclusions.safety.requires_authorization is True

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
            "ak.soundengine.getState",
            "ak.soundengine.getSwitch",
            "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInRegion",
            "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInTrimmedRegion",
            "ak.wwise.core.mediaPool.get",
            "ak.wwise.core.mediaPool.getFields",
            "ak.wwise.core.object.diff",
            "ak.wwise.core.object.isLinked",
            "ak.wwise.core.ping",
            "ak.wwise.core.profiler.getCursorTime",
            "ak.wwise.core.remote.getConnectionStatus",
            "ak.wwise.core.transport.getState",
            "ak.wwise.ui.commands.getCommands",
            "ak.wwise.waapi.getFunctions",
            "ak.wwise.waapi.getSchema",
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


def test_exact_exclusion_registry_is_disjoint_and_accounts_for_all_6_rows() -> None:
    expected_function_exclusions = {
        "ak.wwise.ui.commands.register",
        "ak.wwise.ui.commands.execute",
    }
    expected_topic_exclusions: set[str] = set()

    assert BOUNDED_CALL_CANDIDATES == {}
    assert set(EXPLICIT_UNSUPPORTED_LIVE_URIS) == expected_function_exclusions
    assert IMMEDIATE_UNSUPPORTED_CALL_URIS == expected_function_exclusions
    assert set(EXPLICIT_UNSUPPORTED_TOPIC_URIS) == expected_topic_exclusions
    assert not (REVIEWED_PUBLIC_CALL_URIS & expected_function_exclusions)
    assert not (REVIEWED_TOPIC_URIS & expected_topic_exclusions)

    entries = [
        entry
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for entry in CapabilityCatalog().entries(version)
    ]
    excluded = [
        entry
        for entry in entries
        if entry.safety.interface_status == "unsupported_by_skill_interface"
    ]
    assert len(excluded) == 6
    assert {entry.uri for entry in excluded} == expected_function_exclusions | expected_topic_exclusions
    assert all(entry.preferred_route == "unsupported_boundary" for entry in excluded)
    assert all(entry.execution_mode == "excluded" for entry in excluded)
    assert all(entry.gateway_commands == () for entry in excluded)
    assert all(entry.execution_contract["executable"] is False for entry in excluded)


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

    with pytest.raises(CapabilityCatalogError, match="execution-contract counts changed"):
        CapabilityCatalog(manifest_root=manifest_root).describe("2022.1", uri)


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

    with pytest.raises(CapabilityCatalogError, match="execution-contract counts changed"):
        CapabilityCatalog(manifest_root=manifest_root).describe("2022.1", uri)


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
        "execution_contract",
    }
    assert compact["interface_status"] == "available_via_transaction"
    assert compact["preferred_route"] == "transaction_operation"
    assert compact["transaction_operations"] == ["waapi.call"]
    assert compact["transaction_boundaries"][0]["operation"] == "object.copy"
    assert "returned copy GUID" in compact["transaction_boundaries"][0]["boundary"]
    assert compact["execution_contract"]["contract"] == "waapi-skill.public-execution-contract/v2"
    assert compact["execution_contract"]["route"] == "transaction"
    assert compact["execution_contract"]["executable"] is True
    assert compact["execution_contract"]["requires_authorization"] is True
    assert compact["execution_contract"]["accepted_authorization_modes"] == [
        "explicit_confirmation",
        "policy_authorization",
    ]


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_dump_objects_external_file_write_is_an_isolated_authorized_transaction(version: str) -> None:
    record = CapabilityCatalog().describe(version, "ak.wwise.cli.dumpObjects")

    assert record.safety.read_only is False
    assert record.safety.interface_status == "available_via_transaction"
    assert record.safety.requires_authorization is True
    assert record.preferred_route == "transaction_operation"
    assert record.execution_mode == "isolated_transaction"
    assert record.gateway_commands == ("preview", "confirm", "execute", "verify")
    assert record.transaction_operations == ("waapi.call",)
    assert record.execution_contract["timeout_seconds"] == 120.0
    assert record.execution_contract["result_limit_bytes"] == 1024 * 1024


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
