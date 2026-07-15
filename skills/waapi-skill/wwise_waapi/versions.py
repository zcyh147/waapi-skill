"""Canonical Wwise version contracts used by generated resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


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
WWISE_2022_1_VERSION_KEY = "2022.1"
WWISE_2022_1_BUILD = "2022.1.19.8584"
WWISE_2022_1_CONTRACT = WwiseVersionContract(
    version_key=WWISE_2022_1_VERSION_KEY,
    build=WWISE_2022_1_BUILD,
)
SUPPORTED_WWISE_VERSION_KEYS = (
    WWISE_2021_1_VERSION_KEY,
    WWISE_2022_1_VERSION_KEY,
    WWISE_2023_1_VERSION_KEY,
    WWISE_2024_1_VERSION_KEY,
    WWISE_2025_1_VERSION_KEY,
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
    WWISE_2022_1_VERSION_KEY: WWISE_2022_1_CONTRACT,
    WWISE_2023_1_VERSION_KEY: WWISE_2023_1_CONTRACT,
    WWISE_2024_1_VERSION_KEY: WWISE_2024_1_CONTRACT,
    WWISE_2025_1_VERSION_KEY: WWISE_2025_1_CONTRACT,
}


def version_key_from_get_info(payload: Mapping[str, Any]) -> str:
    """Return the supported ``year.major`` key from ``ak.wwise.core.getInfo``."""

    version = payload.get("version")
    if not isinstance(version, Mapping):
        raise ValueError("getInfo response does not contain a version object")
    year = version.get("year")
    major = version.get("major")
    if not isinstance(year, int) or isinstance(year, bool):
        raise ValueError("getInfo version.year must be an integer")
    if not isinstance(major, int) or isinstance(major, bool):
        raise ValueError("getInfo version.major must be an integer")
    key = f"{year}.{major}"
    if key not in SUPPORTED_WWISE_VERSION_KEYS:
        raise ValueError(
            f"Connected Wwise version {key} is unsupported; supported versions: {', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
        )
    return key


def is_explicit_fail_closed_version(version: str) -> bool:
    """Return True for versions that must not use legacy resource fallbacks."""

    return version in EXPLICIT_FAIL_CLOSED_VERSION_KEYS
