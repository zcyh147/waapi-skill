"""Immutable pre-Codex business-oracle plans for heavy V3 scenarios.

The runner writes one plan after it has sealed the fixture, prompt provenance,
and closed gateway protocol, but before Codex starts.  This module deliberately
validates only the common envelope.  Family-specific compilers and validators
own the exact request, live-readback, and delta-rule schemas.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


BUSINESS_ORACLE_PLAN_CONTRACT = "waapi-skill.business-oracle-plan/v1"
BUSINESS_ORACLE_PLAN_FILE = "business-oracle-plan.json"
MAX_BUSINESS_ORACLE_PLAN_BYTES = 8 * 1024 * 1024

SUPPORTED_VERSIONS = frozenset(
    {"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"}
)
BUSINESS_FAMILIES = frozenset(
    {
        "object",
        "audio_import",
        "audio_conversion",
        "media_pool",
        "soundbank",
        "soundbank_topic",
        "cli",
    }
)

_API_FAMILIES = {
    "ak.wwise.core.object.get": "object",
    "ak.wwise.core.object.create": "object",
    "ak.wwise.core.object.set": "object",
    "ak.wwise.core.object.setReference": "object",
    "ak.wwise.core.audio.import": "audio_import",
    "ak.wwise.core.audio.importTabDelimited": "audio_import",
    "ak.wwise.core.audio.convert": "audio_conversion",
    "ak.wwise.core.mediaPool.get": "media_pool",
    "ak.wwise.core.soundbank.generate": "soundbank",
    "ak.wwise.core.soundbank.processDefinitionFiles": "soundbank",
    "ak.wwise.core.soundbank.convertExternalSources": "soundbank",
    "ak.wwise.core.soundbank.setInclusions": "soundbank",
    "ak.wwise.core.soundbank.generated": "soundbank_topic",
    "ak.wwise.cli.generateSoundbank": "cli",
    "ak.wwise.cli.tabDelimitedImport": "cli",
    "ak.wwise.cli.convertExternalSource": "cli",
    "ak.wwise.cli.migrate": "cli",
}
_TOP_LEVEL_KEYS = frozenset(
    {
        "contract",
        "scenario_id",
        "version",
        "api",
        "runner",
        "family",
        "scenario_root",
        "fixture_spec",
        "protocol_sha256",
        "provenance_sha256",
        "primary_dispatch_count",
        "payload_bindings",
        "assertion_ids",
        "static_expectation",
        "live_binding",
        "delta_rules",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class BusinessOraclePlanError(RuntimeError):
    """A business-oracle plan is absent, mutable, or incorrectly bound."""


@dataclass(frozen=True, slots=True)
class BusinessOraclePlanEvidence:
    path: Path
    sha256: str
    payload: Mapping[str, Any]


def business_family_for_api(api: str) -> str:
    """Return the one closed heavy-V3 family for ``api``."""

    if type(api) is not str or api not in _API_FAMILIES:
        raise BusinessOraclePlanError(
            f"API is outside the closed business-oracle family registry: {api!r}"
        )
    return _API_FAMILIES[api]


def write_business_oracle_plan(
    *,
    scenario_id: str,
    version: str,
    api: str,
    runner: str,
    family: str,
    scenario_root: Path,
    fixture_spec: Mapping[str, Any],
    protocol_sha256: str,
    provenance_sha256: str,
    primary_dispatch_count: int,
    payload_bindings: Mapping[str, Any],
    assertion_ids: Sequence[str],
    static_expectation: Mapping[str, Any],
    live_binding: Mapping[str, Any],
    delta_rules: Sequence[Mapping[str, Any]],
) -> BusinessOraclePlanEvidence:
    """Write the one fixed, no-overwrite plan and read it back exactly."""

    root = _scenario_root(scenario_root)
    payload = _expected_payload(
        scenario_id=scenario_id,
        version=version,
        api=api,
        runner=runner,
        family=family,
        scenario_root=root,
        fixture_spec=fixture_spec,
        protocol_sha256=protocol_sha256,
        provenance_sha256=provenance_sha256,
        primary_dispatch_count=primary_dispatch_count,
        payload_bindings=payload_bindings,
        assertion_ids=assertion_ids,
        static_expectation=static_expectation,
        live_binding=live_binding,
        delta_rules=delta_rules,
    )
    path = root / "evidence" / BUSINESS_ORACLE_PLAN_FILE
    _write_exclusive_json(path, payload)
    return read_business_oracle_plan(
        path,
        scenario_id=scenario_id,
        version=version,
        api=api,
        runner=runner,
        family=family,
        scenario_root=root,
        fixture_spec=fixture_spec,
        protocol_sha256=protocol_sha256,
        provenance_sha256=provenance_sha256,
        primary_dispatch_count=primary_dispatch_count,
        payload_bindings=payload_bindings,
        assertion_ids=assertion_ids,
        static_expectation=static_expectation,
        live_binding=live_binding,
        delta_rules=delta_rules,
    )


def read_business_oracle_plan(
    path: Path,
    *,
    scenario_id: str,
    version: str,
    api: str,
    runner: str,
    family: str,
    scenario_root: Path,
    fixture_spec: Mapping[str, Any],
    protocol_sha256: str,
    provenance_sha256: str,
    primary_dispatch_count: int,
    payload_bindings: Mapping[str, Any],
    assertion_ids: Sequence[str],
    static_expectation: Mapping[str, Any],
    live_binding: Mapping[str, Any],
    delta_rules: Sequence[Mapping[str, Any]],
) -> BusinessOraclePlanEvidence:
    """Read the fixed plan and compare every field with runner-owned truth."""

    evidence = read_business_oracle_plan_envelope(
        path,
        scenario_id=scenario_id,
        version=version,
        api=api,
        runner=runner,
        family=family,
        scenario_root=scenario_root,
        fixture_spec=fixture_spec,
        protocol_sha256=protocol_sha256,
        provenance_sha256=provenance_sha256,
        primary_dispatch_count=primary_dispatch_count,
    )
    root = _scenario_root(scenario_root)
    expected = _expected_payload(
        scenario_id=scenario_id,
        version=version,
        api=api,
        runner=runner,
        family=family,
        scenario_root=root,
        fixture_spec=fixture_spec,
        protocol_sha256=protocol_sha256,
        provenance_sha256=provenance_sha256,
        primary_dispatch_count=primary_dispatch_count,
        payload_bindings=payload_bindings,
        assertion_ids=assertion_ids,
        static_expectation=static_expectation,
        live_binding=live_binding,
        delta_rules=delta_rules,
    )
    if evidence.payload != expected:
        raise BusinessOraclePlanError(
            "business-oracle plan differs from runner-owned expected values"
        )
    return evidence


def read_business_oracle_plan_envelope(
    path: Path,
    *,
    scenario_id: str,
    version: str,
    api: str,
    runner: str,
    family: str,
    scenario_root: Path,
    fixture_spec: Mapping[str, Any],
    protocol_sha256: str,
    provenance_sha256: str,
    primary_dispatch_count: int,
) -> BusinessOraclePlanEvidence:
    """Read and bind the common envelope before typed family validation.

    The returned evidence contains the full payload, but callers do not provide
    the family sections as trusted expected values here.  A closed family
    validator must inspect those sections before granting business coverage.
    """

    root = _scenario_root(scenario_root)
    expected_path = root / "evidence" / BUSINESS_ORACLE_PLAN_FILE
    candidate = _absolute_path(path)
    if candidate != expected_path:
        raise BusinessOraclePlanError(
            "business-oracle plan path is not the fixed scenario evidence path"
        )
    expected_common = _expected_common(
        scenario_id=scenario_id,
        version=version,
        api=api,
        runner=runner,
        family=family,
        scenario_root=root,
        fixture_spec=fixture_spec,
        protocol_sha256=protocol_sha256,
        provenance_sha256=provenance_sha256,
        primary_dispatch_count=primary_dispatch_count,
    )
    raw, payload = _read_one_json(candidate)
    _validate_payload(payload)
    if any(payload[name] != expected for name, expected in expected_common.items()):
        raise BusinessOraclePlanError(
            "business-oracle common envelope differs from runner-owned expected values"
        )
    if raw != _canonical_json_bytes(payload) + b"\n":
        raise BusinessOraclePlanError("business-oracle plan is not canonical JSON")
    return BusinessOraclePlanEvidence(
        path=candidate,
        sha256=hashlib.sha256(raw).hexdigest(),
        payload=payload,
    )


def _expected_common(
    *,
    scenario_id: str,
    version: str,
    api: str,
    runner: str,
    family: str,
    scenario_root: Path,
    fixture_spec: Mapping[str, Any],
    protocol_sha256: str,
    provenance_sha256: str,
    primary_dispatch_count: int,
) -> dict[str, Any]:
    common = {
        "contract": BUSINESS_ORACLE_PLAN_CONTRACT,
        "scenario_id": scenario_id,
        "version": version,
        "api": api,
        "runner": runner,
        "family": family,
        "scenario_root": str(scenario_root),
        "fixture_spec": _json_clone(fixture_spec, "fixture_spec"),
        "protocol_sha256": protocol_sha256,
        "provenance_sha256": provenance_sha256,
        "primary_dispatch_count": primary_dispatch_count,
    }
    # Reuse the common branch of the closed validator without relaxing the
    # persisted top-level schema.
    _validate_common(common)
    return common


def _expected_payload(
    *,
    scenario_id: str,
    version: str,
    api: str,
    runner: str,
    family: str,
    scenario_root: Path,
    fixture_spec: Mapping[str, Any],
    protocol_sha256: str,
    provenance_sha256: str,
    primary_dispatch_count: int,
    payload_bindings: Mapping[str, Any],
    assertion_ids: Sequence[str],
    static_expectation: Mapping[str, Any],
    live_binding: Mapping[str, Any],
    delta_rules: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = {
        **_expected_common(
            scenario_id=scenario_id,
            version=version,
            api=api,
            runner=runner,
            family=family,
            scenario_root=scenario_root,
            fixture_spec=fixture_spec,
            protocol_sha256=protocol_sha256,
            provenance_sha256=provenance_sha256,
            primary_dispatch_count=primary_dispatch_count,
        ),
        "payload_bindings": _json_clone(payload_bindings, "payload_bindings"),
        "assertion_ids": list(assertion_ids) if _is_sequence(assertion_ids) else assertion_ids,
        "static_expectation": _json_clone(static_expectation, "static_expectation"),
        "live_binding": _json_clone(live_binding, "live_binding"),
        "delta_rules": (
            [_json_clone(item, f"delta_rules[{index}]") for index, item in enumerate(delta_rules)]
            if _is_sequence(delta_rules)
            else delta_rules
        ),
    }
    _validate_payload(payload)
    return payload


def _validate_payload(value: Any) -> None:
    if type(value) is not dict or set(value) != _TOP_LEVEL_KEYS:
        raise BusinessOraclePlanError(
            "business-oracle plan top-level schema is not closed"
        )
    if value["contract"] != BUSINESS_ORACLE_PLAN_CONTRACT:
        raise BusinessOraclePlanError("business-oracle plan contract is invalid")

    _validate_common(value)

    bindings = value["payload_bindings"]
    if type(bindings) is not dict or set(bindings) != {
        "primary_steps",
        "verification_steps",
    }:
        raise BusinessOraclePlanError("payload_bindings schema is not closed")
    primary_steps = bindings["primary_steps"]
    _validate_unique_strings(
        primary_steps,
        "payload_bindings.primary_steps",
        allow_empty=True,
    )
    if (value["primary_dispatch_count"] == 0) != (primary_steps == []):
        raise BusinessOraclePlanError(
            "payload_bindings.primary_steps emptiness must match zero primary_dispatch_count"
        )
    _validate_unique_strings(
        bindings["verification_steps"],
        "payload_bindings.verification_steps",
        allow_empty=True,
    )
    _validate_unique_strings(value["assertion_ids"], "assertion_ids", allow_empty=False)

    for name in ("static_expectation", "live_binding"):
        if type(value[name]) is not dict:
            raise BusinessOraclePlanError(f"{name} must be a JSON object")
        _json_clone(value[name], name)
    rules = value["delta_rules"]
    if type(rules) is not list:
        raise BusinessOraclePlanError("delta_rules must be a JSON array")
    for index, rule in enumerate(rules):
        if type(rule) is not dict:
            raise BusinessOraclePlanError(f"delta_rules[{index}] must be a JSON object")
        _json_clone(rule, f"delta_rules[{index}]")


def _validate_common(value: Mapping[str, Any]) -> None:
    scenario_id = value["scenario_id"]
    if type(scenario_id) is not str or not _IDENTIFIER_RE.fullmatch(scenario_id):
        raise BusinessOraclePlanError("business-oracle scenario_id is invalid")
    version = value["version"]
    if type(version) is not str or version not in SUPPORTED_VERSIONS:
        raise BusinessOraclePlanError("business-oracle version is unsupported")

    api = value["api"]
    expected_family = business_family_for_api(api)
    family = value["family"]
    if (
        type(family) is not str
        or family not in BUSINESS_FAMILIES
        or family != expected_family
    ):
        raise BusinessOraclePlanError("business-oracle family is misbound to the API")
    expected_runner = "cli" if expected_family == "cli" else "project"
    runner = value["runner"]
    if (
        type(runner) is not str
        or runner not in {"project", "cli"}
        or runner != expected_runner
    ):
        raise BusinessOraclePlanError("business-oracle runner is misbound to the API")

    root = value["scenario_root"]
    if type(root) is not str or not os.path.isabs(root):
        raise BusinessOraclePlanError("business-oracle scenario_root is not absolute")

    fixture_spec = value["fixture_spec"]
    if type(fixture_spec) is not dict or set(fixture_spec) != {"kind", "sha256"}:
        raise BusinessOraclePlanError("fixture_spec schema is not closed")
    if (
        type(fixture_spec["kind"]) is not str
        or not _IDENTIFIER_RE.fullmatch(fixture_spec["kind"])
        or not _is_sha256(fixture_spec["sha256"])
    ):
        raise BusinessOraclePlanError("fixture_spec values are invalid")

    if not _is_sha256(value["protocol_sha256"]):
        raise BusinessOraclePlanError("protocol_sha256 is invalid")
    if not _is_sha256(value["provenance_sha256"]):
        raise BusinessOraclePlanError("provenance_sha256 is invalid")
    count = value["primary_dispatch_count"]
    if type(count) is not int or count < 0:
        raise BusinessOraclePlanError("primary_dispatch_count must be a plain nonnegative int")


def _validate_unique_strings(value: Any, name: str, *, allow_empty: bool) -> None:
    if type(value) is not list or (not allow_empty and not value):
        qualifier = "a JSON string array" if allow_empty else "a nonempty JSON string array"
        raise BusinessOraclePlanError(f"{name} must be {qualifier}")
    if any(type(item) is not str or not _IDENTIFIER_RE.fullmatch(item) for item in value):
        raise BusinessOraclePlanError(f"{name} contains an invalid identifier")
    if len(set(value)) != len(value):
        raise BusinessOraclePlanError(f"{name} contains duplicate identifiers")


def _scenario_root(path: Path) -> Path:
    root = _absolute_path(path)
    try:
        root_metadata = os.lstat(root)
    except OSError as exc:
        raise BusinessOraclePlanError(f"scenario root cannot be inspected: {exc}") from exc
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise BusinessOraclePlanError("scenario root must be a real directory")
    evidence = root / "evidence"
    try:
        evidence_metadata = os.lstat(evidence)
    except OSError as exc:
        raise BusinessOraclePlanError(
            f"scenario evidence root cannot be inspected: {exc}"
        ) from exc
    if stat.S_ISLNK(evidence_metadata.st_mode) or not stat.S_ISDIR(evidence_metadata.st_mode):
        raise BusinessOraclePlanError("scenario evidence root must be a real directory")
    return root


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _read_one_json(path: Path) -> tuple[bytes, Any]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BusinessOraclePlanError(f"cannot open business-oracle plan: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise BusinessOraclePlanError(
                "business-oracle plan is not one bounded regular file"
            )
        if before.st_size > MAX_BUSINESS_ORACLE_PLAN_BYTES:
            raise BusinessOraclePlanError("business-oracle plan exceeds its size ceiling")
        try:
            linked = os.lstat(path)
        except OSError as exc:
            raise BusinessOraclePlanError(
                f"business-oracle plan cannot be re-inspected: {exc}"
            ) from exc
        if stat.S_ISLNK(linked.st_mode) or (
            linked.st_dev,
            linked.st_ino,
        ) != (before.st_dev, before.st_ino):
            raise BusinessOraclePlanError("business-oracle plan path changed during open")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise BusinessOraclePlanError(
                    "business-oracle plan changed during its bounded read"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            or len(raw) != before.st_size
        ):
            raise BusinessOraclePlanError(
                "business-oracle plan changed during its single read"
            )
        try:
            final_linked = os.lstat(path)
        except OSError as exc:
            raise BusinessOraclePlanError(
                f"business-oracle plan path changed during read: {exc}"
            ) from exc
        if stat.S_ISLNK(final_linked.st_mode) or (
            final_linked.st_dev,
            final_linked.st_ino,
        ) != (after.st_dev, after.st_ino):
            raise BusinessOraclePlanError(
                "business-oracle plan path changed during read"
            )
    finally:
        os.close(descriptor)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BusinessOraclePlanError(f"business-oracle plan JSON is invalid: {exc}") from exc
    return raw, value


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    raw = _canonical_json_bytes(value) + b"\n"
    if len(raw) > MAX_BUSINESS_ORACLE_PLAN_BYTES:
        raise BusinessOraclePlanError("business-oracle plan exceeds its size ceiling")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise BusinessOraclePlanError(
            f"cannot exclusively create business-oracle plan: {exc}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise BusinessOraclePlanError("business-oracle plan target is not a regular file")
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise BusinessOraclePlanError("business-oracle plan write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _json_clone(value: Any, name: str) -> Any:
    try:
        raw = _canonical_json_bytes(value)
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_closed_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BusinessOraclePlanError(f"{name} is not closed JSON: {exc}") from exc


def _canonical_json_bytes(value: Any) -> bytes:
    _validate_json_value(value, "$")
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BusinessOraclePlanError(f"value is not canonical JSON: {exc}") from exc


def _validate_json_value(value: Any, path: str) -> None:
    if value is None or type(value) in {bool, str, int}:
        return
    if type(value) is float:
        if math.isfinite(value):
            return
        raise BusinessOraclePlanError(f"{path} contains a non-finite number")
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise BusinessOraclePlanError(f"{path} contains a non-string object key")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise BusinessOraclePlanError(f"{path} contains a non-JSON value: {type(value).__name__}")


def _closed_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON value: {value}")


def _is_sha256(value: Any) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
