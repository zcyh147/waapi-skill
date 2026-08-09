"""Closed composition loader for the public ``integration`` profile.

The public profile combines the two frozen six-unit workflow definitions
without copying their prompts, fixtures, or baseline manifests.  Historical
unit identifiers remain accepted only as selection aliases so sealed campaign
roots can still be replayed; newly scheduled units expose the shorter public
identifiers defined here.
"""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_integration_workflows_v1 import (
    IntegrationWorkflowProfile,
    IntegrationWorkflowProfileError,
    load_integration_workflows_profile,
)
from tests.semantic.support.codex_integration_workflows_v2 import (
    IntegrationWorkflowV2Error,
    WorkflowProfile,
    load_integration_workflows_v2_profile,
)


PROFILE_CONTRACT = "waapi-skill.codex-integration-profile/v1"
PROFILE_ID = "integration"
COMPONENT_PROFILE_PATHS = (
    "../integration-workflows-v1/profile.json",
    "../integration-workflows-v2/profile.json",
)
VERSIONS = ("2022.1", "2025.1")
WORKFLOW_ORDER = (
    "weather",
    "alarm",
    "harbor",
    "rifle",
    "footsteps",
    "weapons",
)
LOGICAL_WORKFLOW_COUNT = 6
TASK_COUNT = 12
TRANSACTION_COUNT = 20
USER_TURN_COUNT = 36

_EXPECTED_TOTALS = {
    "logical_workflow_count": LOGICAL_WORKFLOW_COUNT,
    "task_count": TASK_COUNT,
    "transaction_count": TRANSACTION_COUNT,
    "user_turn_count": USER_TURN_COUNT,
}
_PROFILE_KEYS = {
    "contract",
    "profile_id",
    "component_profiles",
    "versions",
    "workflow_order",
    "totals",
}
_WORKFLOW_SPECS = (
    ("weather", 0, "interactive_weather_build"),
    ("alarm", 0, "alarm_diagnose_and_repair"),
    ("harbor", 0, "harbor_soundbank_release"),
    ("rifle", 1, "rifle_safe_reimport"),
    ("footsteps", 1, "footsteps_snow_assignment_maintenance"),
    ("weapons", 1, "weapons_query_guided_batch_cleanup"),
)
_COMPONENT_SOURCE_FILES = (
    ("profile.json", "workflows.json"),
    (
        "profile.json",
        "workflows.json",
        "baseline-2022.1.json",
        "baseline-2025.1.json",
    ),
)
_V2_COMPONENT_REPO_PARTS = (
    "tests",
    "semantic",
    "data",
    "integration-workflows-v2",
)
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# This is intentionally explicit rather than derived from the component
# naming algorithms.  A historical loader rename therefore cannot silently
# change the aliases accepted by the public profile.
LEGACY_UNIT_ID_BY_PUBLIC_ID: Mapping[str, str] = MappingProxyType(
    {
        "INT22-WEATHER": "INT22-INTERACTIVE-WEATHER-BUILD",
        "INT22-ALARM": "INT22-ALARM-DIAGNOSE-AND-REPAIR",
        "INT22-HARBOR": "INT22-HARBOR-SOUNDBANK-RELEASE",
        "INT22-RIFLE": "INT22-V2-RIFLE-SAFE-REIMPORT",
        "INT22-FOOTSTEPS": (
            "INT22-V2-FOOTSTEPS-SNOW-ASSIGNMENT-MAINTENANCE"
        ),
        "INT22-WEAPONS": "INT22-V2-WEAPONS-QUERY-GUIDED-BATCH-CLEANUP",
        "INT25-WEATHER": "INT25-INTERACTIVE-WEATHER-BUILD",
        "INT25-ALARM": "INT25-ALARM-DIAGNOSE-AND-REPAIR",
        "INT25-HARBOR": "INT25-HARBOR-SOUNDBANK-RELEASE",
        "INT25-RIFLE": "INT25-V2-RIFLE-SAFE-REIMPORT",
        "INT25-FOOTSTEPS": (
            "INT25-V2-FOOTSTEPS-SNOW-ASSIGNMENT-MAINTENANCE"
        ),
        "INT25-WEAPONS": "INT25-V2-WEAPONS-QUERY-GUIDED-BATCH-CLEANUP",
    }
)
PUBLIC_UNIT_ID_BY_LEGACY_ID: Mapping[str, str] = MappingProxyType(
    {
        legacy_id: public_id
        for public_id, legacy_id in LEGACY_UNIT_ID_BY_PUBLIC_ID.items()
    }
)


class IntegrationProfileError(ValueError):
    """The unified integration profile or one of its dependencies is invalid."""


@dataclass(frozen=True, slots=True)
class IntegrationWorkflowUnit:
    """One public unit retaining the complete component runtime contract."""

    unit_id: str
    legacy_unit_id: str
    workflow_name: str
    component_index: int
    workflow: Any
    version: str
    scenario: Any
    baseline_manifest: Any | None

    @property
    def workflow_id(self) -> str:
        return str(self.workflow.id)

    @property
    def turns(self) -> tuple[Any, ...]:
        return self.workflow.turns

    @property
    def transactions(self) -> tuple[Any, ...]:
        return self.workflow.transactions

    @property
    def transaction_count(self) -> int:
        return len(self.transactions)

    @property
    def user_turn_count(self) -> int:
        return len(self.turns)


@dataclass(frozen=True, slots=True)
class IntegrationProfile:
    path: Path
    component_paths: tuple[Path, ...]
    source_digests: tuple[tuple[str, str], ...]
    definition_sha256: str
    component_profiles: tuple[IntegrationWorkflowProfile, WorkflowProfile]
    workflows: tuple[Any, ...]
    units: tuple[IntegrationWorkflowUnit, ...]
    legacy_unit_ids: Mapping[str, str]

    @property
    def committed_baselines_ready(self) -> bool:
        return self.component_profiles[1].committed_baselines_ready

    @property
    def baseline_layouts(self) -> Mapping[str, Any]:
        return self.component_profiles[1].baseline_layouts

    @property
    def baseline_manifests(self) -> Mapping[str, Any]:
        return self.component_profiles[1].baseline_manifests


def load_integration_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
    repo_root: str | Path | None = None,
) -> IntegrationProfile:
    """Load the complete public profile, then apply optional unit filters.

    The fixed-baseline component is always loaded with committed-baseline
    verification enabled.  There is deliberately no caller option to weaken
    that acceptance boundary.
    """

    profile_path = _resolve_regular_file(path, "integration profile")
    root, profile_digest = _load_json(profile_path, "integration profile")
    if set(root) != _PROFILE_KEYS:
        raise IntegrationProfileError("integration profile schema is not closed")
    if root.get("contract") != PROFILE_CONTRACT or root.get("profile_id") != PROFILE_ID:
        raise IntegrationProfileError("integration profile identity drifted")
    if _strings(root.get("versions"), "profile.versions") != VERSIONS:
        raise IntegrationProfileError("integration profile versions drifted")
    if _strings(root.get("workflow_order"), "profile.workflow_order") != WORKFLOW_ORDER:
        raise IntegrationProfileError("integration workflow order drifted")
    _validate_totals(root.get("totals"))

    component_values = _strings(
        root.get("component_profiles"),
        "profile.component_profiles",
    )
    if component_values != COMPONENT_PROFILE_PATHS:
        raise IntegrationProfileError(
            "integration component profile order or identity drifted"
        )
    component_paths = _resolve_component_paths(profile_path, component_values)
    repository = _preflight_component_sources(
        component_paths,
        repo_root=repo_root,
    )

    try:
        first = load_integration_workflows_profile(component_paths[0])
    except IntegrationWorkflowProfileError as exc:
        raise IntegrationProfileError("integration component-01 is invalid") from exc
    try:
        second = load_integration_workflows_v2_profile(
            component_paths[1],
            require_committed_baselines=True,
            repo_root=repository,
        )
    except IntegrationWorkflowV2Error as exc:
        raise IntegrationProfileError("integration component-02 is invalid") from exc
    components = (first, second)

    complete_units, workflows = _compose_units(components)
    requested_ids = canonicalize_integration_unit_ids(unit_ids)
    requested_versions = _unique_strings(versions, "versions")
    unknown_versions = sorted(set(requested_versions) - set(VERSIONS))
    if unknown_versions:
        raise IntegrationProfileError(
            "integration profile has no units for versions: "
            + ", ".join(unknown_versions)
        )
    selected = tuple(
        unit
        for unit in complete_units
        if (not requested_ids or unit.unit_id in requested_ids)
        and (not requested_versions or unit.version in requested_versions)
    )
    if not selected:
        raise IntegrationProfileError(
            "no integration units matched the requested filters"
        )

    source_digests: list[tuple[str, str]] = [
        ("integration/profile.json", profile_digest)
    ]
    for index, component in enumerate(components, start=1):
        namespace = f"component-{index:02d}"
        source_digests.extend(
            (f"{namespace}/{name}", digest)
            for name, digest in component.source_digests
        )
    frozen_digests = tuple(source_digests)
    if len({name for name, _ in frozen_digests}) != len(frozen_digests):
        raise IntegrationProfileError(
            "integration source digest namespaces collided"
        )
    definition_sha256 = hashlib.sha256(
        "\n".join(
            f"{name}\0{digest}" for name, digest in frozen_digests
        ).encode("utf-8")
    ).hexdigest()
    return IntegrationProfile(
        path=profile_path,
        component_paths=component_paths,
        source_digests=frozen_digests,
        definition_sha256=definition_sha256,
        component_profiles=components,
        workflows=workflows,
        units=selected,
        legacy_unit_ids=LEGACY_UNIT_ID_BY_PUBLIC_ID,
    )


def _compose_units(
    components: tuple[IntegrationWorkflowProfile, WorkflowProfile],
) -> tuple[tuple[IntegrationWorkflowUnit, ...], tuple[Any, ...]]:
    component_workflows = tuple(
        {
            str(workflow.id): workflow
            for workflow in component.workflows
        }
        for component in components
    )
    workflows: list[Any] = []
    for _, component_index, workflow_id in _WORKFLOW_SPECS:
        workflow = component_workflows[component_index].get(workflow_id)
        if workflow is None:
            raise IntegrationProfileError(
                f"integration component lost workflow {workflow_id}"
            )
        workflows.append(workflow)

    raw_units = tuple(
        {
            (str(unit.version), str(unit.workflow_id)): unit
            for unit in component.units
        }
        for component in components
    )
    units: list[IntegrationWorkflowUnit] = []
    for version in VERSIONS:
        version_token = version.split(".", maxsplit=1)[0][-2:]
        for scenario_index, (
            workflow_name,
            component_index,
            workflow_id,
        ) in enumerate(_WORKFLOW_SPECS, start=1):
            public_id = f"INT{version_token}-{workflow_name.upper()}"
            legacy_id = LEGACY_UNIT_ID_BY_PUBLIC_ID.get(public_id)
            raw_unit = raw_units[component_index].get((version, workflow_id))
            if legacy_id is None or raw_unit is None:
                raise IntegrationProfileError(
                    f"integration unit mapping is incomplete for {public_id}"
                )
            if str(raw_unit.unit_id) != legacy_id:
                raise IntegrationProfileError(
                    f"integration legacy unit identity drifted for {public_id}"
                )
            baseline_manifest = getattr(raw_unit, "baseline_manifest", None)
            if component_index == 1 and baseline_manifest is None:
                raise IntegrationProfileError(
                    f"integration committed baseline is absent for {public_id}"
                )
            scenario = replace(
                raw_unit.scenario,
                id=public_id,
                scenario_index=scenario_index,
            )
            units.append(
                IntegrationWorkflowUnit(
                    unit_id=public_id,
                    legacy_unit_id=legacy_id,
                    workflow_name=workflow_name,
                    component_index=component_index,
                    workflow=raw_unit.workflow,
                    version=version,
                    scenario=scenario,
                    baseline_manifest=baseline_manifest,
                )
            )

    frozen_units = tuple(units)
    if (
        len(frozen_units) != TASK_COUNT
        or sum(unit.transaction_count for unit in frozen_units)
        != TRANSACTION_COUNT
        or sum(unit.user_turn_count for unit in frozen_units) != USER_TURN_COUNT
        or tuple(unit.workflow_name for unit in frozen_units[:6])
        != WORKFLOW_ORDER
        or tuple(unit.workflow_name for unit in frozen_units[6:])
        != WORKFLOW_ORDER
    ):
        raise IntegrationProfileError("integration expanded topology drifted")
    if tuple(unit.unit_id for unit in frozen_units) != tuple(
        LEGACY_UNIT_ID_BY_PUBLIC_ID
    ):
        raise IntegrationProfileError("integration public unit order drifted")
    if any(
        unit.scenario.id != unit.unit_id
        or unit.scenario.versions != (unit.version,)
        or unit.workflow.id != unit.workflow_id
        for unit in frozen_units
    ):
        raise IntegrationProfileError("integration runtime unit binding drifted")
    return frozen_units, tuple(workflows)


def canonicalize_integration_unit_ids(
    values: Sequence[str],
) -> tuple[str, ...]:
    """Return public unit IDs while accepting the closed historical aliases."""

    requested = _unique_strings(values, "unit ids")
    known = set(LEGACY_UNIT_ID_BY_PUBLIC_ID)
    normalized: list[str] = []
    unknown: list[str] = []
    for value in requested:
        public_id = PUBLIC_UNIT_ID_BY_LEGACY_ID.get(value, value)
        if public_id not in known:
            unknown.append(value)
        else:
            normalized.append(public_id)
    if unknown:
        raise IntegrationProfileError(
            "unknown integration unit ids: " + ", ".join(sorted(unknown))
        )
    if len(normalized) != len(set(normalized)):
        raise IntegrationProfileError(
            "unit ids select the same integration unit more than once"
        )
    return tuple(normalized)


def _preflight_component_sources(
    component_paths: tuple[Path, ...],
    *,
    repo_root: str | Path | None,
) -> Path:
    """Reject linked or displaced component inputs before legacy loaders run."""

    repository = _resolve_repository_root(component_paths[1], repo_root)
    baseline_root = repository.joinpath(*_V2_COMPONENT_REPO_PARTS)
    try:
        baseline_root_stat = baseline_root.lstat()
    except OSError as exc:
        raise IntegrationProfileError(
            "cannot inspect integration component-02 repository root"
        ) from exc
    if _is_link_or_reparse(baseline_root, baseline_root_stat):
        raise IntegrationProfileError(
            "integration component-02 repository root may not be a link"
        )
    if not stat.S_ISDIR(baseline_root_stat.st_mode):
        raise IntegrationProfileError(
            "integration component-02 repository root must be a directory"
        )
    try:
        resolved_baseline_root = baseline_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise IntegrationProfileError(
            "cannot resolve integration component-02 repository root"
        ) from exc
    if not resolved_baseline_root.is_relative_to(repository):
        raise IntegrationProfileError(
            "integration component-02 baseline root escapes its repository"
        )

    source_groups = (
        (1, component_paths[0].parent, _COMPONENT_SOURCE_FILES[0]),
        (2, component_paths[1].parent, _COMPONENT_SOURCE_FILES[1][:2]),
        (2, resolved_baseline_root, _COMPONENT_SOURCE_FILES[1][2:]),
    )
    for component_index, root, names in source_groups:
        for name in names:
            _preflight_component_source(
                root,
                name,
                component_index=component_index,
            )
    return repository


def _preflight_component_source(
    root: Path,
    name: str,
    *,
    component_index: int,
) -> None:
    label = f"integration component-{component_index:02d}/{name}"
    lexical = root / name
    try:
        file_stat = lexical.lstat()
    except OSError as exc:
        raise IntegrationProfileError(f"cannot inspect {label}") from exc
    if _is_link_or_reparse(lexical, file_stat):
        raise IntegrationProfileError(f"{label} may not be a link")
    if not stat.S_ISREG(file_stat.st_mode):
        raise IntegrationProfileError(f"{label} must be a regular file")
    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise IntegrationProfileError(f"cannot resolve {label}") from exc
    if resolved != lexical or resolved.parent != root:
        raise IntegrationProfileError(f"{label} escapes its component root")


def _resolve_repository_root(
    component_profile: Path,
    value: str | Path | None,
) -> Path:
    if value is None:
        for parent in component_profile.parents:
            if (parent / ".git").exists() and (parent / "tests").is_dir():
                return parent.resolve()
        raise IntegrationProfileError(
            "cannot discover repository root for integration baselines"
        )
    try:
        lexical = Path(value).expanduser()
        root_stat = lexical.lstat()
        if _is_link_or_reparse(lexical, root_stat):
            raise IntegrationProfileError(
                "integration repository root may not be a link"
            )
        if not stat.S_ISDIR(root_stat.st_mode):
            raise IntegrationProfileError(
                "integration repository root must be a directory"
            )
        root = lexical.resolve(strict=True)
    except IntegrationProfileError:
        raise
    except (OSError, RuntimeError) as exc:
        raise IntegrationProfileError(
            f"cannot resolve integration repository root: {value}"
        ) from exc
    if not root.is_dir():
        raise IntegrationProfileError(
            "integration repository root must be a directory"
        )
    return root


def _is_reparse_point(value: Any) -> bool:
    return bool(
        getattr(value, "st_file_attributes", 0)
        & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _is_link_or_reparse(path: Path, value: Any) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return bool(
        path.is_symlink()
        or (callable(is_junction) and is_junction())
        or _is_reparse_point(value)
    )


def _resolve_component_paths(
    profile_path: Path,
    values: Sequence[str],
) -> tuple[Path, ...]:
    data_root = profile_path.parent.parent.resolve(strict=True)
    paths: list[Path] = []
    for index, value in enumerate(values, start=1):
        expected_directory = f"integration-workflows-v{index}"
        lexical = data_root / expected_directory / "profile.json"
        try:
            directory_stat = lexical.parent.lstat()
            profile_stat = lexical.lstat()
        except OSError as exc:
            raise IntegrationProfileError(
                f"cannot inspect integration component-{index:02d}: {value}"
            ) from exc
        if _is_link_or_reparse(
            lexical.parent,
            directory_stat,
        ) or _is_link_or_reparse(lexical, profile_stat):
            raise IntegrationProfileError(
                f"integration component-{index:02d} may not be a symlink "
                "or reparse point"
            )
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise IntegrationProfileError(
                f"integration component-{index:02d} root must be a directory"
            )
        if not stat.S_ISREG(profile_stat.st_mode):
            raise IntegrationProfileError(
                f"integration component-{index:02d} profile must be a regular file"
            )
        try:
            resolved = lexical.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise IntegrationProfileError(
                f"cannot resolve integration component-{index:02d}: {value}"
            ) from exc
        if not resolved.is_file() or not resolved.is_relative_to(data_root):
            raise IntegrationProfileError(
                f"integration component-{index:02d} escapes its data root"
            )
        candidate = (profile_path.parent / value).resolve(strict=True)
        if candidate != resolved:
            raise IntegrationProfileError(
                f"integration component-{index:02d} path drifted"
            )
        paths.append(resolved)
    return tuple(paths)


def _resolve_regular_file(value: str | Path, label: str) -> Path:
    try:
        source = Path(value).expanduser()
        source_stat = source.lstat()
        if _is_link_or_reparse(source, source_stat):
            raise IntegrationProfileError(
                f"{label} may not be a symlink or reparse point"
            )
        if not stat.S_ISREG(source_stat.st_mode):
            raise IntegrationProfileError(f"{label} must be a regular file")
        path = source.resolve(strict=True)
    except IntegrationProfileError:
        raise
    except (OSError, RuntimeError) as exc:
        raise IntegrationProfileError(f"cannot resolve {label}: {value}") from exc
    if not path.is_file():
        raise IntegrationProfileError(f"{label} must be a regular file")
    return path


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except IntegrationProfileError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrationProfileError(f"cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise IntegrationProfileError(f"{label} must be a JSON object")
    return value, hashlib.sha256(payload).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntegrationProfileError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise IntegrationProfileError(f"non-finite JSON number: {value}")


def _strings(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise IntegrationProfileError(f"{path} must be a non-empty string array")
    result = tuple(_string(item, f"{path}[]") for item in value)
    if len(result) != len(set(result)):
        raise IntegrationProfileError(f"{path} contains duplicate values")
    return result


def _unique_strings(value: Sequence[str], path: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise IntegrationProfileError(f"{path} must be a sequence of strings")
    result = tuple(_string(item, f"{path}[]") for item in value)
    if len(result) != len(set(result)):
        raise IntegrationProfileError(f"{path} contains duplicate values")
    return result


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise IntegrationProfileError(f"{path} must be a trimmed non-empty string")
    return value


def _validate_totals(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != set(_EXPECTED_TOTALS):
        raise IntegrationProfileError("profile.totals schema is not closed")
    if any(
        not isinstance(item, int) or isinstance(item, bool)
        for item in value.values()
    ):
        raise IntegrationProfileError("profile.totals values must be integers")
    if value != _EXPECTED_TOTALS:
        raise IntegrationProfileError("integration profile totals drifted")


__all__ = [
    "COMPONENT_PROFILE_PATHS",
    "LEGACY_UNIT_ID_BY_PUBLIC_ID",
    "LOGICAL_WORKFLOW_COUNT",
    "PROFILE_CONTRACT",
    "PROFILE_ID",
    "PUBLIC_UNIT_ID_BY_LEGACY_ID",
    "TASK_COUNT",
    "TRANSACTION_COUNT",
    "USER_TURN_COUNT",
    "VERSIONS",
    "WORKFLOW_ORDER",
    "IntegrationProfile",
    "IntegrationProfileError",
    "IntegrationWorkflowUnit",
    "canonicalize_integration_unit_ids",
    "load_integration_profile",
]
