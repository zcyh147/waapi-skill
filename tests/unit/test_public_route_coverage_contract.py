from __future__ import annotations

import json
import shutil

import pytest

from wwise_waapi.capabilities import CapabilityCatalog
from wwise_waapi.execution_contracts import (
    APPROVED_EXCLUSIONS,
    EXPECTED_PUBLIC_UNIQUE_URIS,
    EXPECTED_PUBLIC_VERSION_ROWS,
    EXPECTED_VERSION_COUNTS,
    ExecutionContractError,
    ExecutionContractRegistry,
    validate_packaged_execution_contracts,
)
from wwise_waapi.manifest import ManifestStore
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


# Deliberately independent of production routing code: changing production
# exclusions cannot silently lower the acceptance target.
APPROVED_EXCLUSION_URIS = {
    "ak.wwise.cli.executeLuaScript",
    "ak.wwise.core.executeLuaScript",
    "ak.wwise.debug.enableAsserts",
    "ak.wwise.debug.enableAutomationMode",
    "ak.wwise.debug.getWalTree",
    "ak.wwise.debug.restartWaapiServers",
    "ak.wwise.debug.testAssert",
    "ak.wwise.debug.testCrash",
    "ak.wwise.debug.validateCall",
    "ak.wwise.debug.assertFailed",
    "ak.wwise.ui.commands.register",
    "ak.wwise.ui.commands.execute",
}


def test_five_version_public_route_contract_is_exactly_769_rows() -> None:
    summary = validate_packaged_execution_contracts()

    assert summary["manifest_rows"] == 814
    assert summary["executable_rows"] == EXPECTED_PUBLIC_VERSION_ROWS == 769
    assert summary["excluded_rows"] == 45
    assert summary["unique_public_uris"] == EXPECTED_PUBLIC_UNIQUE_URIS == 188
    assert set(APPROVED_EXCLUSIONS) == APPROVED_EXCLUSION_URIS


def test_each_version_manifest_minus_approved_exclusions_equals_executable_routes() -> None:
    registry = ExecutionContractRegistry()
    manifest_store = ManifestStore(root=registry.manifest_store.root)

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        manifest = manifest_store.load(version)
        reflected = {
            (item_type, str(row["uri"]))
            for item_type, section in (("function", "functions"), ("topic", "topics"))
            for row in manifest[section]
        }
        expected = {row for row in reflected if row[1] not in APPROVED_EXCLUSION_URIS}
        actual = {(entry.item_type, entry.uri) for entry in registry.executable_entries(version)}

        assert actual == expected
        assert len(actual) == EXPECTED_VERSION_COUNTS[version]["public_total"]


def test_capability_catalog_counts_only_real_execution_contracts() -> None:
    catalog = CapabilityCatalog()
    rows = [entry for version in SUPPORTED_WWISE_VERSION_KEYS for entry in catalog.entries(version)]
    executable = [
        entry
        for entry in rows
        if entry.safety.interface_status != "unsupported_by_skill_interface"
        and entry.preferred_route != "unsupported_boundary"
        and entry.gateway_commands
        and entry.execution_contract.get("executable") is True
    ]

    assert len(executable) == 769
    assert {entry.uri for entry in executable} == {
        entry.uri
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for entry in ExecutionContractRegistry().executable_entries(version)
    }
    assert all(entry.execution_contract.get("program_case") for entry in executable)


def test_same_count_manifest_uri_change_fails_closed(tmp_path) -> None:
    packaged = ExecutionContractRegistry().manifest_store.root
    assert packaged is not None
    shutil.copytree(packaged, tmp_path, dirs_exist_ok=True)
    functions_path = tmp_path / "2022.1" / "functions.json"
    payload = json.loads(functions_path.read_text(encoding="utf-8"))
    payload["functions"][0]["uri"] = "ak.wwise.unreviewed.sameCountReplacement"
    functions_path.write_text(json.dumps(payload), encoding="utf-8")

    registry = ExecutionContractRegistry(manifest_store=ManifestStore(root=tmp_path))
    with pytest.raises(ExecutionContractError, match="inventory changed"):
        registry.entries("2022.1")
