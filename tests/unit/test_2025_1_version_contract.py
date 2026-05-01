from __future__ import annotations

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION, DispatcherRequest, WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.versions import (  # pyright: ignore[reportMissingImports]
    WWISE_2025_1_CONTRACT,
    WWISE_VERSION_CONTRACTS,
    is_explicit_fail_closed_version,
)


def test_2025_1_contract_is_canonical_without_changing_default_dispatcher_version() -> None:
    contract = WWISE_VERSION_CONTRACTS["2025.1"]

    assert contract is WWISE_2025_1_CONTRACT
    assert contract.version_key == "2025.1"
    assert contract.build == "2025.1.7.9143"
    assert DEFAULT_WWISE_VERSION == "2022.1"
    assert DispatcherRequest(api="ak.wwise.core.getInfo").version == "2022.1"


def test_2025_is_not_an_alias_for_2025_1() -> None:
    assert "2025" not in WWISE_VERSION_CONTRACTS
    assert not is_explicit_fail_closed_version("2025")
    assert is_explicit_fail_closed_version("2025.1")


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


def test_explicit_2025_1_dispatcher_request_uses_2025_1_manifest_without_default_change() -> None:
    seen_versions: list[str] = []

    class Store:
        def load(self, version: str) -> dict[str, object]:
            seen_versions.append(version)
            return {"functions": [], "topics": []}

    request = DispatcherRequest(api="ak.wwise.core.getInfo", version="2025.1")
    result = WwiseDispatcher(manifest_store=Store()).dispatch(request)  # type: ignore[arg-type]

    assert DEFAULT_WWISE_VERSION == "2022.1"
    assert seen_versions == ["2025.1"]
    assert "2025" not in seen_versions
    assert result["version"] == "2025.1"
    assert result["error_code"] == "API_NOT_FOUND"
