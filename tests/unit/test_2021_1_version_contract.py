from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION, DispatcherRequest, WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestResourceMissingError, ManifestStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.versions import (  # pyright: ignore[reportMissingImports]
    WWISE_2021_1_CONTRACT,
    WWISE_VERSION_CONTRACTS,
    is_explicit_fail_closed_version,
)


def test_2021_1_contract_is_canonical_without_changing_default_dispatcher_version() -> None:
    contract = WWISE_VERSION_CONTRACTS["2021.1"]

    assert contract is WWISE_2021_1_CONTRACT
    assert contract.version_key == "2021.1"
    assert contract.build == "2021.1.14.8108"
    assert DEFAULT_WWISE_VERSION == "2022.1"
    assert DispatcherRequest(api="ak.wwise.core.getInfo").version == "2022.1"


def test_2021_is_not_an_alias_for_2021_1() -> None:
    assert "2021" not in WWISE_VERSION_CONTRACTS
    assert not is_explicit_fail_closed_version("2021")
    assert is_explicit_fail_closed_version("2021.1")


def test_default_dispatcher_call_still_targets_2022_1_manifest() -> None:
    seen_versions: list[str] = []

    class Store:
        def load(self, version: str) -> dict[str, object]:
            seen_versions.append(version)
            return {"functions": [], "topics": []}

    result = WwiseDispatcher(manifest_store=Store()).dispatch("ak.wwise.core.getInfo")  # type: ignore[arg-type]

    assert seen_versions == ["2022.1"]
    assert result["version"] == "2022.1"
    assert result["error_code"] == "API_NOT_FOUND"


def test_explicit_2021_1_dispatcher_request_uses_2021_1_manifest_without_default_change() -> None:
    seen_versions: list[str] = []

    class Store:
        def load(self, version: str) -> dict[str, object]:
            seen_versions.append(version)
            return {"functions": [], "topics": []}

    request = DispatcherRequest(api="ak.wwise.core.getInfo", version="2021.1")
    result = WwiseDispatcher(manifest_store=Store()).dispatch(request)  # type: ignore[arg-type]

    assert DEFAULT_WWISE_VERSION == "2022.1"
    assert seen_versions == ["2021.1"]
    assert "2021" not in seen_versions
    assert result["version"] == "2021.1"
    assert result["error_code"] == "API_NOT_FOUND"


def test_2021_1_manifest_missing_resources_fail_closed_even_when_2022_1_exists(tmp_path: Path) -> None:
    manifest_root = tmp_path / "resources" / "manifest"
    (manifest_root / "2022.1").mkdir(parents=True)
    (manifest_root / "2022.1" / "manifest.json").write_text("{}\n", encoding="utf-8")

    store = ManifestStore(root=manifest_root)

    with pytest.raises(ManifestResourceMissingError) as exc_info:
        store.load("2021.1")

    assert exc_info.value.version == "2021.1"
    assert exc_info.value.path == manifest_root / "2021.1" / "manifest.json"
