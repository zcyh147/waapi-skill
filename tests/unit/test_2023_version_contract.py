from __future__ import annotations

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION, DispatcherRequest, WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.versions import WWISE_2023_1_CONTRACT, WWISE_VERSION_CONTRACTS  # pyright: ignore[reportMissingImports]


def test_2023_1_contract_is_canonical_without_changing_default_dispatcher_version() -> None:
    contract = WWISE_VERSION_CONTRACTS["2023.1"]

    assert contract is WWISE_2023_1_CONTRACT
    assert contract.version_key == "2023.1"
    assert contract.build == "2023.1.19.8928"
    assert DEFAULT_WWISE_VERSION == "2022.1"
    assert DispatcherRequest(api="ak.wwise.core.getInfo").version == "2022.1"


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
