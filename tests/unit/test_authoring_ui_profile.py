from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from wwise_waapi.authoring_ui_commands_manifest import (
    AUTHORING_HOST_SURFACE,
    AUTHORING_UI_COMMAND_URIS,
)
from wwise_waapi.builders.common import (
    ManifestSchemaLoader,
    SemanticErrorCode,
    SemanticValidationError,
)
from wwise_waapi.capabilities import (
    CapabilityCatalog,
    CapabilityNotFoundError,
)
from wwise_waapi.execution_contracts import (
    AUTHORING_UI_DEDICATED_OPERATIONS,
    AUTHORING_UI_EXECUTION_PROFILE,
    CONSOLE_EXECUTION_PROFILE,
    EXPECTED_AUTHORING_UI_VERSION_COUNTS,
    EXPECTED_AUTHORING_UI_VERSION_INVENTORY_SHA256,
    ExecutionContractError,
    ExecutionContractRegistry,
    PACKAGED_AUTHORING_UI_INVENTORY_SHA256,
    PACKAGED_INVENTORY_SHA256,
    validate_packaged_authoring_ui_execution_contracts,
    validate_packaged_execution_contracts,
)
from wwise_waapi.manifest import ManifestStore
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOT = (
    REPO_ROOT / "skills" / "waapi-skill" / "resources" / "manifest"
)


def test_authoring_profile_has_fixed_five_version_counts_and_digests() -> None:
    registry = ExecutionContractRegistry()
    summary = validate_packaged_authoring_ui_execution_contracts(registry)

    assert summary == {
        "contract": "waapi-skill.public-execution-contract/v1",
        "execution_profile": AUTHORING_UI_EXECUTION_PROFILE,
        "manifest_rows": 824,
        "executable_rows": 824,
        "excluded_rows": 0,
        "unique_public_uris": 200,
        "inventory_sha256": PACKAGED_AUTHORING_UI_INVENTORY_SHA256,
        "by_version": {
            version: {
                "manifest": EXPECTED_AUTHORING_UI_VERSION_COUNTS[version][
                    "public_total"
                ],
                "executable": EXPECTED_AUTHORING_UI_VERSION_COUNTS[version][
                    "public_total"
                ],
            }
            for version in SUPPORTED_WWISE_VERSION_KEYS
        },
    }
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        entries = registry.authoring_ui_entries(version)
        inventory = "".join(
            sorted(
                f"{entry.version}\t{entry.item_type}\t{entry.uri}\n"
                for entry in entries
            )
        )
        assert (
            hashlib.sha256(inventory.encode("utf-8")).hexdigest()
            == EXPECTED_AUTHORING_UI_VERSION_INVENTORY_SHA256[version]
        )


def test_default_console_profile_remains_isolated_and_unchanged() -> None:
    registry = ExecutionContractRegistry()
    summary = validate_packaged_execution_contracts(registry)

    assert summary["manifest_rows"] == 814
    assert summary["executable_rows"] == 808
    assert summary["unique_public_uris"] == 198
    assert summary["inventory_sha256"] == PACKAGED_INVENTORY_SHA256
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        assert registry.entries(version) == registry.entries_for_profile(
            version,
            profile=CONSOLE_EXECUTION_PROFILE,
        )
    for version in ("2021.1", "2022.1", "2023.1"):
        assert (
            registry.describe(
                version,
                "ak.wwise.ui.commands.execute",
            ).route
            == "excluded"
        )
        assert (
            registry.describe(
                version,
                "ak.wwise.ui.commands.register",
            ).route
            == "excluded"
        )
    for version in ("2024.1", "2025.1"):
        with pytest.raises(ExecutionContractError, match="not reflected"):
            registry.describe(version, "ak.wwise.ui.commands.execute")


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_authoring_profile_assigns_exact_ui_command_routes(
    version: str,
) -> None:
    registry = ExecutionContractRegistry()
    records = {
        entry.uri: entry
        for entry in registry.authoring_ui_entries(version)
        if entry.uri in AUTHORING_UI_COMMAND_URIS
    }

    assert set(records) == AUTHORING_UI_COMMAND_URIS
    assert records["ak.wwise.ui.commands.getCommands"].route == "bounded_call"
    assert records["ak.wwise.ui.commands.getCommands"].effect == "read"
    assert (
        records["ak.wwise.ui.commands.executed"].route
        == "bounded_topic_wait"
    )
    assert (
        records["ak.wwise.ui.commands.executed"].effect == "observation"
    )
    for uri in AUTHORING_UI_DEDICATED_OPERATIONS:
        record = records[uri]
        assert record.route == "managed_transaction"
        assert record.effect == "runtime_mutation"
        assert record.requires_confirmation is True
        assert record.gateway_commands == (
            "preview",
            "confirm",
            "execute",
            "verify",
        )
        assert AUTHORING_UI_DEDICATED_OPERATIONS[uri] in record.program_case
    assert records[
        "ak.wwise.ui.commands.register"
    ].companion_uris == ("ak.wwise.ui.commands.unregister",)


class _SameCountReplacementStore(ManifestStore):
    def load_with_authoring_ui_commands(
        self,
        version: str,
    ) -> dict[str, object]:
        manifest = deepcopy(super().load_with_authoring_ui_commands(version))
        functions = manifest["functions"]
        assert isinstance(functions, list)
        functions[0]["uri"] = "ak.wwise.unreviewed.sameCountReplacement"
        return manifest


def test_authoring_profile_same_count_uri_substitution_fails_closed() -> None:
    registry = ExecutionContractRegistry(
        manifest_store=_SameCountReplacementStore(root=MANIFEST_ROOT)
    )

    with pytest.raises(
        ExecutionContractError,
        match="Authoring UI inventory changed",
    ):
        registry.authoring_ui_entries("2024.1")


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
def test_authoring_schema_loader_resolves_gui_only_rows(
    version: str,
) -> None:
    loader = ManifestSchemaLoader(
        ManifestStore(root=MANIFEST_ROOT)
    )

    with pytest.raises(
        SemanticValidationError,
        match="No usable schema",
    ) as default_error:
        loader.schema_for("ak.wwise.ui.commands.execute", version)
    assert (
        default_error.value.error_code
        == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    )

    for uri in AUTHORING_UI_COMMAND_URIS:
        schema = loader.authoring_ui_schema_for(uri, version)
        assert isinstance(schema, dict)
        assert schema.get("description")
    execute_properties = loader.authoring_ui_schema_for(
        "ak.wwise.ui.commands.execute",
        version,
    )["argsSchema"]["properties"]
    assert ("files" in execute_properties) is (version == "2025.1")


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_authoring_capabilities_expose_correct_safety_route_and_evidence(
    version: str,
) -> None:
    catalog = CapabilityCatalog()
    records = {
        uri: catalog.authoring_ui_describe(version, uri)
        for uri in AUTHORING_UI_COMMAND_URIS
    }

    for uri, record in records.items():
        assert record.host_surface == AUTHORING_HOST_SURFACE
        assert record.full_authoring_inventory_reflected is False
        assert (
            record.manifest_runtime_profile
            == "console-with-authoring-ui-commands"
        )
        assert (
            record.authoring_ui_profile
            == "fixed-five-uri-reflection-supplement"
        )
        assert (
            record.authoring_ui_commands_supplement_evidence[
                "surface_scope"
            ]
            == "ak.wwise.ui.commands"
        )
        assert len(
            record.authoring_ui_commands_supplement_evidence[
                "supplement_inventory_sha256"
            ]
        ) == 64
        serialized = record.as_dict()
        assert (
            serialized["interface"]["host_surface"]
            == AUTHORING_HOST_SURFACE
        )
        assert (
            serialized["interface"]["full_authoring_inventory_reflected"]
            is False
        )

    for uri, operation in AUTHORING_UI_DEDICATED_OPERATIONS.items():
        record = records[uri]
        assert record.preferred_route == "transaction_operation"
        assert record.transaction_operations == (operation,)
        assert record.safety.read_only is False
        assert record.safety.requires_destructive_gate is True
        assert record.safety.requires_confirmation is True
        assert record.safety.interface_status == "available_via_transaction"
    read = records["ak.wwise.ui.commands.getCommands"]
    assert read.preferred_route == "manifest_dispatch"
    assert read.gateway_commands == ("call",)
    assert read.safety.read_only is True
    assert read.safety.requires_confirmation is False
    topic = records["ak.wwise.ui.commands.executed"]
    assert topic.preferred_route == "bounded_topic_wait"
    assert topic.gateway_commands == ("wait-topic",)
    assert topic.safety.read_only is True


def test_capability_default_methods_do_not_select_authoring_profile() -> None:
    catalog = CapabilityCatalog()

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        assert catalog.entries(version) == catalog.entries_for_profile(
            version,
            profile=CONSOLE_EXECUTION_PROFILE,
        )
    for version in ("2024.1", "2025.1"):
        with pytest.raises(CapabilityNotFoundError, match="not reflected"):
            catalog.describe(version, "ak.wwise.ui.commands.execute")
        assert catalog.authoring_ui_describe(
            version,
            "ak.wwise.ui.commands.execute",
        ).host_surface == AUTHORING_HOST_SURFACE
