"""Closed data loader for the 24-unit compound-heavy semantic profile.

This module only loads reviewed data, clones existing v3 scenarios, and builds
their fixed two-turn topology.  It does not register a campaign profile,
materialize fixtures, start Codex, connect to Wwise, or execute an adapter.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import string
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_eval_bundle_v3 import (
    EvalBundleV3Error,
    OnlineScenario,
    load_eval_bundle_v3,
)
from tests.semantic.support.codex_eval_execution_v3 import ScenarioTurn


PROFILE_CONTRACT = "waapi-skill.codex-compound-heavy-profile/v1"
CASE_FILE_CONTRACT = "waapi-skill.codex-compound-heavy-cases/v1"
PROFILE_ID = "compound_heavy_cross_version_24"
BASE_SUITE_REPO_RELATIVE = "skills/waapi-skill/evals/suite-v3.json"
DATA_FILE_NAMES = (
    "audio-import.json",
    "object-create-set.json",
    "soundbank.json",
)
VERSIONS = ("2022.1", "2025.1")
API_URIS = (
    "ak.wwise.core.audio.import",
    "ak.wwise.core.audio.importTabDelimited",
    "ak.wwise.core.object.create",
    "ak.wwise.core.object.set",
    "ak.wwise.core.soundbank.generate",
    "ak.wwise.core.soundbank.setInclusions",
)
EXPECTED_CASE_IDS_BY_FILE = {
    "audio-import.json": (
        "O22-AUDIO-IMPORT-02",
        "O22-AUDIO-IMPORT-03",
        "O22-AUDIO-TAB-03",
        "O22-AUDIO-TAB-04",
    ),
    "object-create-set.json": (
        "OBJ22-F-CREATE-02",
        "OBJ22-F-CREATE-03",
        "OBJ22-F-SET-01",
        "OBJ22-F-SET-02",
    ),
    "soundbank.json": (
        "O22-SB-GENERATE-01",
        "O22-SB-GENERATE-03",
        "O22-SB-SET-INCLUSIONS-01",
        "O22-SB-SET-INCLUSIONS-05",
    ),
}
EXPECTED_API_BY_CASE_ID = {
    "O22-AUDIO-IMPORT-02": "ak.wwise.core.audio.import",
    "O22-AUDIO-IMPORT-03": "ak.wwise.core.audio.import",
    "O22-AUDIO-TAB-03": "ak.wwise.core.audio.importTabDelimited",
    "O22-AUDIO-TAB-04": "ak.wwise.core.audio.importTabDelimited",
    "OBJ22-F-CREATE-02": "ak.wwise.core.object.create",
    "OBJ22-F-CREATE-03": "ak.wwise.core.object.create",
    "OBJ22-F-SET-01": "ak.wwise.core.object.set",
    "OBJ22-F-SET-02": "ak.wwise.core.object.set",
    "O22-SB-GENERATE-01": "ak.wwise.core.soundbank.generate",
    "O22-SB-GENERATE-03": "ak.wwise.core.soundbank.generate",
    "O22-SB-SET-INCLUSIONS-01": "ak.wwise.core.soundbank.setInclusions",
    "O22-SB-SET-INCLUSIONS-05": "ak.wwise.core.soundbank.setInclusions",
}
LOGICAL_CASE_COUNT = 12
TASK_COUNT = 24
USER_TURN_COUNT = 48
TRANSACTION_COUNT = 24
_EXPECTED_TOTALS = {
    "logical_case_count": LOGICAL_CASE_COUNT,
    "task_count": TASK_COUNT,
    "user_turn_count": USER_TURN_COUNT,
    "transaction_count": TRANSACTION_COUNT,
}
_PROFILE_KEYS = {
    "contract",
    "profile_id",
    "base_suite",
    "data_files",
    "versions",
    "apis",
    "totals",
}
_CASE_REQUIRED_KEYS = {"base_scenario_id", "api", "versions"}
_CASE_OPTIONAL_KEYS = {
    "prompt",
    "confirmation_prompt",
    "fixture_patch",
}
_UNIT_ID_RE = re.compile(r"^CMP(?:22|25)-[A-Z0-9][A-Z0-9._-]*$")
_VISIBLE_INPUT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PROMPT_FORBIDDEN = (
    re.compile(r"gateway", re.IGNORECASE),
    re.compile(r"operation-schema", re.IGNORECASE),
    re.compile(r"WAAPI_RESULT_JSON", re.IGNORECASE),
    re.compile(r"\bak\.(?:wwise|soundengine)\.", re.IGNORECASE),
    re.compile(r"\b(?:runner|fixture|sandbox|oracle|harness)\b", re.IGNORECASE),
    re.compile(r"沙箱"),
    re.compile(r"必须遵守.{0,16}(?:skill|边界)", re.IGNORECASE),
    re.compile(r"run\.py", re.IGNORECASE),
)


class CompoundHeavyProfileError(EvalBundleV3Error):
    """The compound-heavy profile or one of its data files is invalid."""


@dataclass(frozen=True, slots=True)
class CompoundHeavyCase:
    """One logical business case before its two-version expansion."""

    base_scenario_id: str
    api: str
    versions: tuple[str, ...]
    source_file: str
    prompt: str | None
    confirmation_prompt: str | None
    fixture_patch: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CompoundHeavyUnit:
    """One version-pinned, memory-isolated two-turn semantic task."""

    unit_id: str
    base_scenario_id: str
    scenario: OnlineScenario
    version: str
    turns: tuple[ScenarioTurn, ...]

    @property
    def transaction_count(self) -> int:
        return 1

    @property
    def user_turn_count(self) -> int:
        return len(self.turns)


@dataclass(frozen=True, slots=True)
class CompoundHeavyProfile:
    """A fully validated profile, optionally narrowed after validation."""

    path: Path
    base_suite_path: Path
    data_paths: tuple[Path, ...]
    source_digests: tuple[tuple[str, str], ...]
    definition_sha256: str
    cases: tuple[CompoundHeavyCase, ...]
    units: tuple[CompoundHeavyUnit, ...]


def load_compound_heavy_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> CompoundHeavyProfile:
    """Load and fully validate all 12 logical cases before optional filtering."""

    profile_path = _resolve_regular_file(path, "compound-heavy profile")
    root, profile_digest = _load_json(profile_path, "compound-heavy profile")
    if set(root) != _PROFILE_KEYS:
        raise CompoundHeavyProfileError("compound-heavy profile schema is not closed")
    if (
        root.get("contract") != PROFILE_CONTRACT
        or root.get("profile_id") != PROFILE_ID
        or root.get("base_suite") != BASE_SUITE_REPO_RELATIVE
    ):
        raise CompoundHeavyProfileError("compound-heavy profile identity drifted")
    if _string_tuple(root.get("versions"), "profile.versions") != VERSIONS:
        raise CompoundHeavyProfileError("compound-heavy profile versions drifted")
    if _string_tuple(root.get("apis"), "profile.apis") != API_URIS:
        raise CompoundHeavyProfileError("compound-heavy profile API order drifted")
    _validate_totals(root.get("totals"))

    data_file_names = _string_tuple(root.get("data_files"), "profile.data_files")
    for name in data_file_names:
        _validate_sibling_json_name(name)
    if data_file_names != DATA_FILE_NAMES:
        raise CompoundHeavyProfileError(
            "compound-heavy profile data_files order or identity drifted"
        )
    data_paths = tuple(
        _resolve_sibling_json(profile_path, name) for name in data_file_names
    )

    repo_root = Path(__file__).resolve().parents[3]
    base_suite_path = _resolve_regular_file(
        repo_root / BASE_SUITE_REPO_RELATIVE,
        "compound-heavy base suite",
    )
    bundle = load_eval_bundle_v3(base_suite_path)

    cases: list[CompoundHeavyCase] = []
    source_digests: list[tuple[str, str]] = [
        (profile_path.name, profile_digest)
    ]
    for name, data_path in zip(data_file_names, data_paths, strict=True):
        data_root, data_digest = _load_json(
            data_path,
            f"compound-heavy data file {name}",
        )
        source_digests.append((name, data_digest))
        if set(data_root) != {"contract", "cases"}:
            raise CompoundHeavyProfileError(
                f"{name} data-file schema is not closed"
            )
        if data_root.get("contract") != CASE_FILE_CONTRACT:
            raise CompoundHeavyProfileError(f"{name} contract drifted")
        raw_cases = data_root.get("cases")
        if not isinstance(raw_cases, list):
            raise CompoundHeavyProfileError(f"{name}.cases must be a JSON array")
        parsed = tuple(
            _parse_case(raw, source_file=name, index=index, bundle=bundle)
            for index, raw in enumerate(raw_cases)
        )
        expected_ids = EXPECTED_CASE_IDS_BY_FILE[name]
        if tuple(item.base_scenario_id for item in parsed) != expected_ids:
            raise CompoundHeavyProfileError(
                f"{name} case order or identity drifted"
            )
        cases.extend(parsed)

    complete_cases = tuple(cases)
    _validate_complete_cases(complete_cases)
    complete_units = tuple(
        _build_unit(case, bundle.scenario(case.base_scenario_id), version)
        for version in VERSIONS
        for case in complete_cases
    )
    _validate_complete_units(complete_units)

    requested_ids = _unique_strings(unit_ids, "unit ids")
    requested_versions = _unique_strings(versions, "versions")
    known_ids = {unit.unit_id for unit in complete_units}
    unknown_ids = sorted(set(requested_ids) - known_ids)
    if unknown_ids:
        raise CompoundHeavyProfileError(
            "unknown compound-heavy unit ids: " + ", ".join(unknown_ids)
        )
    unknown_versions = sorted(set(requested_versions) - set(VERSIONS))
    if unknown_versions:
        raise CompoundHeavyProfileError(
            "compound-heavy profile has no units for versions: "
            + ", ".join(unknown_versions)
        )
    selected = tuple(
        unit
        for unit in complete_units
        if (not requested_ids or unit.unit_id in requested_ids)
        and (not requested_versions or unit.version in requested_versions)
    )
    if not selected:
        raise CompoundHeavyProfileError(
            "no compound-heavy units matched the requested filters"
        )

    frozen_digests = tuple(source_digests)
    definition_sha256 = hashlib.sha256(
        "\n".join(
            f"{name}\0{digest}" for name, digest in frozen_digests
        ).encode("utf-8")
    ).hexdigest()
    return CompoundHeavyProfile(
        path=profile_path,
        base_suite_path=base_suite_path,
        data_paths=data_paths,
        source_digests=frozen_digests,
        definition_sha256=definition_sha256,
        cases=complete_cases,
        units=selected,
    )


def _parse_case(
    value: Any,
    *,
    source_file: str,
    index: int,
    bundle: Any,
) -> CompoundHeavyCase:
    path = f"{source_file}.cases[{index}]"
    if not isinstance(value, dict):
        raise CompoundHeavyProfileError(f"{path} must be a JSON object")
    keys = set(value)
    if (
        not _CASE_REQUIRED_KEYS.issubset(keys)
        or not keys.issubset(_CASE_REQUIRED_KEYS | _CASE_OPTIONAL_KEYS)
    ):
        raise CompoundHeavyProfileError(f"{path} schema is not closed")

    base_scenario_id = _nonempty_string(
        value.get("base_scenario_id"),
        f"{path}.base_scenario_id",
    )
    expected_api = EXPECTED_API_BY_CASE_ID.get(base_scenario_id)
    if expected_api is None:
        raise CompoundHeavyProfileError(
            f"{path}.base_scenario_id is not in the reviewed compound profile"
        )
    api = _nonempty_string(value.get("api"), f"{path}.api")
    if api != expected_api:
        raise CompoundHeavyProfileError(
            f"{path}.api does not match {base_scenario_id}"
        )
    case_versions = _string_tuple(value.get("versions"), f"{path}.versions")
    if case_versions != VERSIONS:
        raise CompoundHeavyProfileError(
            f"{path}.versions must be exactly {list(VERSIONS)}"
        )

    scenario = bundle.scenario(base_scenario_id)
    blockers = bundle.scenario_mapping_blockers(base_scenario_id)
    if blockers:
        raise CompoundHeavyProfileError(
            f"{base_scenario_id} retains unresolved request mappings: "
            + ", ".join(item.id for item in blockers)
        )
    if (
        scenario.api != api
        or scenario.versions != ("2022.1",)
        or scenario.protocol != "preview_confirm"
        or scenario.primary_dispatch.count != 1
        or not scenario.confirmation_prompt
    ):
        raise CompoundHeavyProfileError(
            f"{base_scenario_id} no longer has the approved one-transaction shape"
        )

    prompt = (
        _nonempty_string(value["prompt"], f"{path}.prompt")
        if "prompt" in value
        else None
    )
    if prompt is not None:
        _validate_prompt_override(prompt, scenario, f"{path}.prompt")
    confirmation_prompt = (
        _nonempty_string(
            value["confirmation_prompt"],
            f"{path}.confirmation_prompt",
        )
        if "confirmation_prompt" in value
        else None
    )
    if confirmation_prompt is not None:
        _lint_natural_prompt(
            confirmation_prompt,
            f"{path}.confirmation_prompt",
            minimum_length=6,
        )

    fixture_patch_value = value.get("fixture_patch", {})
    if not isinstance(fixture_patch_value, dict):
        raise CompoundHeavyProfileError(
            f"{path}.fixture_patch must be a JSON object"
        )
    if set(fixture_patch_value) - {"asset_spec", "prerequisites"}:
        raise CompoundHeavyProfileError(
            f"{path}.fixture_patch may patch only asset_spec or prerequisites"
        )
    if "fixture_patch" in value and not fixture_patch_value:
        raise CompoundHeavyProfileError(
            f"{path}.fixture_patch must not be empty when present"
        )

    return CompoundHeavyCase(
        base_scenario_id=base_scenario_id,
        api=api,
        versions=case_versions,
        source_file=source_file,
        prompt=prompt,
        confirmation_prompt=confirmation_prompt,
        fixture_patch=copy.deepcopy(fixture_patch_value),
    )


def _build_unit(
    case: CompoundHeavyCase,
    base_scenario: OnlineScenario,
    version: str,
) -> CompoundHeavyUnit:
    fixture = _deep_merge(dict(base_scenario.fixture), case.fixture_patch)
    scenario = replace(
        base_scenario,
        versions=(version,),
        prompt=case.prompt if case.prompt is not None else base_scenario.prompt,
        confirmation_prompt=(
            case.confirmation_prompt
            if case.confirmation_prompt is not None
            else base_scenario.confirmation_prompt
        ),
        fixture=fixture,
    )
    if scenario.confirmation_prompt is None:
        raise CompoundHeavyProfileError(
            f"{case.base_scenario_id} lost its confirmation prompt"
        )
    turns = (
        ScenarioTurn(
            index=1,
            kind="request",
            prompt=scenario.prompt,
            transaction_index=None,
            expects_next_preview=False,
        ),
        ScenarioTurn(
            index=2,
            kind="confirmation",
            prompt=scenario.confirmation_prompt,
            transaction_index=1,
            expects_next_preview=False,
        ),
    )
    unit_id = (
        f"CMP{version.split('.', maxsplit=1)[0][-2:]}-"
        f"{case.base_scenario_id}"
    )
    if _UNIT_ID_RE.fullmatch(unit_id) is None:
        raise CompoundHeavyProfileError(
            f"generated compound-heavy unit id is invalid: {unit_id}"
        )
    return CompoundHeavyUnit(
        unit_id=unit_id,
        base_scenario_id=case.base_scenario_id,
        scenario=scenario,
        version=version,
        turns=turns,
    )


def _validate_complete_cases(cases: Sequence[CompoundHeavyCase]) -> None:
    if len(cases) != LOGICAL_CASE_COUNT:
        raise CompoundHeavyProfileError(
            f"compound-heavy profile requires {LOGICAL_CASE_COUNT} logical cases"
        )
    ids = tuple(case.base_scenario_id for case in cases)
    if len(ids) != len(set(ids)):
        raise CompoundHeavyProfileError(
            "compound-heavy logical case ids must be unique"
        )
    api_counts = {api: 0 for api in API_URIS}
    for case in cases:
        api_counts[case.api] += 1
    if any(count != 2 for count in api_counts.values()):
        raise CompoundHeavyProfileError(
            f"compound-heavy profile requires two cases per API: {api_counts}"
        )


def _validate_complete_units(units: Sequence[CompoundHeavyUnit]) -> None:
    if len(units) != TASK_COUNT:
        raise CompoundHeavyProfileError(
            f"compound-heavy profile requires {TASK_COUNT} units"
        )
    unit_ids = tuple(unit.unit_id for unit in units)
    if len(unit_ids) != len(set(unit_ids)):
        raise CompoundHeavyProfileError(
            "compound-heavy unit ids must be unique"
        )
    version_counts = {
        version: sum(unit.version == version for unit in units)
        for version in VERSIONS
    }
    if version_counts != {version: LOGICAL_CASE_COUNT for version in VERSIONS}:
        raise CompoundHeavyProfileError(
            f"compound-heavy version distribution drifted: {version_counts}"
        )
    if (
        sum(unit.user_turn_count for unit in units) != USER_TURN_COUNT
        or sum(unit.transaction_count for unit in units) != TRANSACTION_COUNT
    ):
        raise CompoundHeavyProfileError(
            "compound-heavy turn or transaction totals drifted"
        )
    for unit in units:
        if (
            unit.scenario.id != unit.base_scenario_id
            or unit.scenario.versions != (unit.version,)
            or unit.scenario.primary_dispatch.count != 1
            or tuple(turn.kind for turn in unit.turns)
            != ("request", "confirmation")
        ):
            raise CompoundHeavyProfileError(
                f"{unit.unit_id} lost the fixed cloned-scenario topology"
            )


def _validate_totals(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != set(_EXPECTED_TOTALS):
        raise CompoundHeavyProfileError(
            "profile.totals schema is not closed"
        )
    if value != _EXPECTED_TOTALS:
        raise CompoundHeavyProfileError("compound-heavy profile totals drifted")


def _validate_prompt_override(
    prompt: str,
    scenario: OnlineScenario,
    path: str,
) -> None:
    _lint_natural_prompt(prompt, path)
    fields: list[str] = []
    try:
        parsed = tuple(string.Formatter().parse(prompt))
    except ValueError as exc:
        raise CompoundHeavyProfileError(
            f"{path} has invalid prompt-template braces"
        ) from exc
    for _, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if _VISIBLE_INPUT_RE.fullmatch(field_name) is None:
            raise CompoundHeavyProfileError(
                f"{path} uses an invalid visible-input placeholder"
            )
        if format_spec or conversion:
            raise CompoundHeavyProfileError(
                f"{path} placeholders cannot use formatting or conversion"
            )
        fields.append(field_name)
    declared = {item.name for item in scenario.visible_inputs}
    referenced = set(fields)
    if declared != referenced:
        raise CompoundHeavyProfileError(
            f"{path} visible-input closure mismatch; "
            f"missing={sorted(referenced - declared)}, "
            f"unused={sorted(declared - referenced)}"
        )


def _lint_natural_prompt(
    value: str,
    path: str,
    *,
    minimum_length: int = 24,
) -> None:
    if len(value.strip()) < minimum_length:
        raise CompoundHeavyProfileError(
            f"{path} is too short to represent a substantive user scenario"
        )
    for pattern in _PROMPT_FORBIDDEN:
        if pattern.search(value):
            raise CompoundHeavyProfileError(
                f"{path} contains test-harness coaching forbidden from "
                f"natural user prompts: {pattern.pattern!r}"
            )


def _deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(base))
    for key, patch_value in patch.items():
        base_value = result.get(key)
        if isinstance(base_value, Mapping) and isinstance(patch_value, Mapping):
            result[key] = _deep_merge(base_value, patch_value)
        else:
            result[key] = copy.deepcopy(patch_value)
    return result


def _resolve_sibling_json(profile_path: Path, value: str) -> Path:
    _validate_sibling_json_name(value)
    relative = Path(value)
    path = _resolve_regular_file(
        profile_path.parent / relative,
        f"compound-heavy data file {value}",
    )
    if path.parent != profile_path.parent:
        raise CompoundHeavyProfileError(
            f"profile.data_files entry escapes its directory: {value}"
        )
    return path


def _validate_sibling_json_name(value: str) -> None:
    relative = Path(value)
    if (
        relative.is_absolute()
        or relative.parts != (value,)
        or relative.suffix != ".json"
    ):
        raise CompoundHeavyProfileError(
            "profile.data_files entries must be sibling JSON filenames"
        )


def _resolve_regular_file(value: str | Path, label: str) -> Path:
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CompoundHeavyProfileError(
            f"cannot resolve {label}: {value}"
        ) from exc
    if not path.is_file():
        raise CompoundHeavyProfileError(f"{label} must be a regular file")
    return path


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_number,
        )
    except CompoundHeavyProfileError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompoundHeavyProfileError(
            f"cannot load {label} {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise CompoundHeavyProfileError(f"{label} must be a JSON object")
    return value, hashlib.sha256(payload).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CompoundHeavyProfileError(
                f"duplicate JSON object key is forbidden: {key}"
            )
        result[key] = value
    return result


def _reject_nonfinite_number(value: str) -> None:
    raise CompoundHeavyProfileError(
        f"non-finite JSON number is forbidden: {value}"
    )


def _string_tuple(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CompoundHeavyProfileError(
            f"{path} must be a non-empty JSON string array"
        )
    result = tuple(_nonempty_string(item, f"{path}[]") for item in value)
    if len(result) != len(set(result)):
        raise CompoundHeavyProfileError(f"{path} contains duplicate values")
    return result


def _nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CompoundHeavyProfileError(f"{path} must be a non-empty string")
    return value


def _unique_strings(values: Sequence[str], label: str) -> tuple[str, ...]:
    result = tuple(_nonempty_string(value, label) for value in values)
    if len(result) != len(set(result)):
        raise CompoundHeavyProfileError(f"duplicate {label} are not allowed")
    return result


__all__ = [
    "API_URIS",
    "BASE_SUITE_REPO_RELATIVE",
    "CASE_FILE_CONTRACT",
    "DATA_FILE_NAMES",
    "EXPECTED_API_BY_CASE_ID",
    "EXPECTED_CASE_IDS_BY_FILE",
    "LOGICAL_CASE_COUNT",
    "PROFILE_CONTRACT",
    "PROFILE_ID",
    "TASK_COUNT",
    "TRANSACTION_COUNT",
    "USER_TURN_COUNT",
    "VERSIONS",
    "CompoundHeavyCase",
    "CompoundHeavyProfile",
    "CompoundHeavyProfileError",
    "CompoundHeavyUnit",
    "load_compound_heavy_profile",
]
