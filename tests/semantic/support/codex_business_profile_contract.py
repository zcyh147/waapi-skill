"""Shared closed-envelope mechanics for production Business Agent profiles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, TypeVar


_UnitT = TypeVar("_UnitT")


@dataclass(frozen=True, slots=True)
class ClosedBusinessProfileSource:
    path: Path
    definition_sha256: str
    units: tuple[Any, ...]


def load_closed_business_profile_source(
    path: str | Path,
    *,
    contract: str,
    profile_id: str,
    model: str,
    reasoning_effort: str,
    service_tier: str,
    expected_unit_count: int,
    error_type: type[ValueError],
    subject: str,
) -> ClosedBusinessProfileSource:
    """Load and seal the shared profile root before operation-specific parsing."""

    profile_path = Path(path).expanduser().resolve(strict=True)
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or set(raw) != {
        "contract",
        "profile_id",
        "model",
        "units",
    }:
        raise error_type(f"{subject} profile is not closed")
    if raw.get("contract") != contract or raw.get("profile_id") != profile_id:
        raise error_type(f"{subject} profile identity drifted")
    if raw.get("model") != {
        "name": model,
        "reasoning_effort": reasoning_effort,
        "service_tier": service_tier,
        "memory": "disabled",
    }:
        raise error_type(f"{subject} model settings drifted")
    units = raw.get("units")
    if not isinstance(units, list) or len(units) != expected_unit_count:
        raise error_type(
            f"{subject} profile requires exactly {expected_unit_count} source units"
        )
    return ClosedBusinessProfileSource(
        path=profile_path,
        definition_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        units=tuple(units),
    )


def select_closed_business_profile_units(
    units: Sequence[_UnitT],
    *,
    unit_ids: Sequence[str],
    versions: Sequence[str],
    known_unit_ids: Sequence[str],
    supported_versions: Sequence[str],
    error_type: type[ValueError],
    subject: str,
) -> tuple[_UnitT, ...]:
    """Apply the shared unique, known-ID, version, and non-empty filters."""

    requested_ids = tuple(str(value) for value in unit_ids)
    requested_versions = tuple(str(value) for value in versions)
    selected_ids = tuple(dict.fromkeys(requested_ids))
    selected_versions = tuple(dict.fromkeys(requested_versions))
    if len(selected_ids) != len(requested_ids) or len(selected_versions) != len(
        requested_versions
    ):
        raise error_type(f"{subject} filters must be unique")
    unknown = sorted(set(selected_ids) - set(known_unit_ids))
    if unknown:
        raise error_type(f"unknown {subject} units: " + ", ".join(unknown))
    unsupported = sorted(set(selected_versions) - set(supported_versions))
    if unsupported:
        raise error_type(
            f"{subject} profile does not support versions: "
            + ", ".join(unsupported)
        )
    selected = tuple(
        unit
        for unit in units
        if (not selected_ids or getattr(unit, "unit_id", None) in selected_ids)
        and (
            not selected_versions
            or getattr(unit, "version", None) in selected_versions
        )
    )
    if not selected:
        raise error_type(f"no {subject} units matched")
    return selected
