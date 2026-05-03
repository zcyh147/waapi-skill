"""Canonical Wwise version contracts used by generated resources."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WwiseVersionContract:
    """Stable key/build pair for a supported Wwise resource version."""

    version_key: str
    build: str


WWISE_2023_1_VERSION_KEY = "2023.1"
WWISE_2023_1_BUILD = "2023.1.19.8928"
WWISE_2023_1_CONTRACT = WwiseVersionContract(
    version_key=WWISE_2023_1_VERSION_KEY,
    build=WWISE_2023_1_BUILD,
)
WWISE_2021_1_VERSION_KEY = "2021.1"
WWISE_2021_1_BUILD = "2021.1.14.8108"
WWISE_2021_1_CONTRACT = WwiseVersionContract(
    version_key=WWISE_2021_1_VERSION_KEY,
    build=WWISE_2021_1_BUILD,
)
WWISE_2024_1_VERSION_KEY = "2024.1"
WWISE_2024_1_BUILD = "2024.1.13.9056"
WWISE_2024_1_CONTRACT = WwiseVersionContract(
    version_key=WWISE_2024_1_VERSION_KEY,
    build=WWISE_2024_1_BUILD,
)
WWISE_2025_1_VERSION_KEY = "2025.1"
WWISE_2025_1_BUILD = "2025.1.7.9143"
WWISE_2025_1_CONTRACT = WwiseVersionContract(
    version_key=WWISE_2025_1_VERSION_KEY,
    build=WWISE_2025_1_BUILD,
)
EXPLICIT_FAIL_CLOSED_VERSION_KEYS = frozenset(
    {
        WWISE_2021_1_VERSION_KEY,
        WWISE_2023_1_VERSION_KEY,
        WWISE_2024_1_VERSION_KEY,
        WWISE_2025_1_VERSION_KEY,
    }
)
WWISE_VERSION_CONTRACTS = {
    WWISE_2021_1_VERSION_KEY: WWISE_2021_1_CONTRACT,
    WWISE_2023_1_VERSION_KEY: WWISE_2023_1_CONTRACT,
    WWISE_2024_1_VERSION_KEY: WWISE_2024_1_CONTRACT,
    WWISE_2025_1_VERSION_KEY: WWISE_2025_1_CONTRACT,
}


def is_explicit_fail_closed_version(version: str) -> bool:
    """Return True for versions that must not use legacy resource fallbacks."""

    return version in EXPLICIT_FAIL_CLOSED_VERSION_KEYS
