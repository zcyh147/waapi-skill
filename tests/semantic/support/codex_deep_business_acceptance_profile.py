"""Closed composition of one representative Fresh task per migrated family."""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


PROFILE_CONTRACT = "waapi-skill.deep-business-acceptance-profile/v1"
PROFILE_ID = "deep_business_cross_version_19"
SUPPORTED_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
REQUIRED_FAMILIES = (
    "audio-import-mvp",
    "named-object-lifecycle",
    "named-object-metadata-fields",
    "named-object-creation-graph",
    "named-switch-assignments",
    "named-soundbank-planning",
    "named-exact-artifact-code",
    "named-authoring-ui-registration",
    "named-dangerous-debug-controls",
    "named-compound-undo",
    "fixed-query-metadata-selection-profiler-debug",
    "generic-core-authoring",
    "generic-media-soundbank-read",
    "generic-project-setting-source-control",
    "generic-runtime-remote-transport",
    "generic-soundengine",
    "generic-cli-console",
    "generic-host-ui-debug-waapi",
    "generic-topics",
)
MODEL = {
    "name": "gpt-5.6-terra",
    "reasoning_effort": "medium",
    "service_tier": "default",
    "memory": "disabled",
}
PROFILE_TASK_COUNT = len(REQUIRED_FAMILIES)
_ROOT_KEYS = {
    "contract",
    "profile_id",
    "versions",
    "required_families",
    "model",
    "totals",
    "tasks",
}
_TASK_KEYS = {
    "family",
    "component_profile",
    "component_suite",
    "unit_id",
    "version",
}
_COMPONENTS = {
    "audio_import_business_8": (
        "tests/semantic/data/audio-import-business/profile.json",
        "tests.semantic.support.codex_import_business_profile",
        "load_import_business_profile",
    ),
    "typed_input_cross_version_25": (
        "tests/semantic/data/typed-input-v1/profile.json",
        "tests.semantic.support.codex_typed_input_profile",
        "load_typed_input_profile",
    ),
    "object_lifecycle_business_3": (
        "tests/semantic/data/object-lifecycle-business/profile.json",
        "tests.semantic.support.codex_object_lifecycle_business_profile",
        "load_object_lifecycle_business_profile",
    ),
    "object_metadata_business_1": (
        "tests/semantic/data/object-metadata-business/profile.json",
        "tests.semantic.support.codex_object_metadata_business_profile",
        "load_object_metadata_business_profile",
    ),
    "object_graph_business_1": (
        "tests/semantic/data/object-graph-business/profile.json",
        "tests.semantic.support.codex_object_graph_business_profile",
        "load_object_graph_business_profile",
    ),
    "switch_assignment_business_1": (
        "tests/semantic/data/switch-assignment-business/profile.json",
        "tests.semantic.support.codex_switch_assignment_business_profile",
        "load_switch_assignment_business_profile",
    ),
    "authoring_ui_business_2": (
        "tests/semantic/data/authoring-ui-business/profile.json",
        "tests.semantic.support.codex_authoring_ui_business_profile",
        "load_authoring_ui_business_profile",
    ),
    "debug_control_business_1": (
        "tests/semantic/data/debug-control-business/profile.json",
        "tests.semantic.support.codex_debug_control_business_profile",
        "load_debug_control_business_profile",
    ),
    "compound_undo_business_1": (
        "tests/semantic/data/compound-undo-business/profile.json",
        "tests.semantic.support.codex_compound_undo_business_profile",
        "load_compound_undo_business_profile",
    ),
    "core_business_1": (
        "tests/semantic/data/core-business/profile.json",
        "tests.semantic.support.codex_core_business_profile",
        "load_core_business_profile",
    ),
    "project_setting_business_1": (
        "tests/semantic/data/project-setting-business/profile.json",
        "tests.semantic.support.codex_project_setting_business_profile",
        "load_project_setting_business_profile",
    ),
    "runtime_control_business_1": (
        "tests/semantic/data/runtime-control-business/profile.json",
        "tests.semantic.support.codex_runtime_control_business_profile",
        "load_runtime_control_business_profile",
    ),
    "soundengine_business_4": (
        "tests/semantic/data/soundengine-business/profile.json",
        "tests.semantic.support.codex_soundengine_business_profile",
        "load_soundengine_business_profile",
    ),
    "cli_console_business_1": (
        "tests/semantic/data/cli-console-business/profile.json",
        "tests.semantic.support.codex_cli_console_business_profile",
        "load_cli_console_business_profile",
    ),
    "host_ui_debug_business_1": (
        "tests/semantic/data/host-ui-debug-business/profile.json",
        "tests.semantic.support.codex_host_ui_debug_business_profile",
        "load_host_ui_debug_business_profile",
    ),
}


class DeepBusinessAcceptanceProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DeepBusinessAcceptanceUnit:
    family: str
    component_profile_id: str
    component_suite_path: Path
    component_unit: Any

    @property
    def unit_id(self) -> str:
        return str(self.component_unit.unit_id)

    @property
    def version(self) -> str:
        return str(self.component_unit.version)

    @property
    def scenario(self) -> Any:
        return self.component_unit.scenario

    @property
    def runner_lane(self) -> str:
        return str(getattr(self.component_unit, "runner_lane", "project"))

    @property
    def user_turn_count(self) -> int:
        return int(getattr(self.component_unit, "user_turn_count", 1))

    @property
    def transaction_count(self) -> int:
        value = getattr(self.component_unit, "transaction_count", None)
        if value is not None:
            return int(value)
        commands = getattr(self.component_unit, "commands", ())
        return sum(
            isinstance(command, tuple)
            and bool(command)
            and command[0] == "mvp-preview"
            for command in commands
        )

    @property
    def base_scenario_id(self) -> str | None:
        value = getattr(self.component_unit, "base_scenario_id", None)
        return None if value is None else str(value)


@dataclass(frozen=True, slots=True)
class DeepBusinessAcceptanceProfile:
    path: Path
    definition_sha256: str
    units: tuple[DeepBusinessAcceptanceUnit, ...]


def load_deep_business_acceptance_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> DeepBusinessAcceptanceProfile:
    profile_path = Path(path).expanduser().resolve(strict=True)
    root = _load_json(profile_path)
    if set(root) != _ROOT_KEYS:
        raise DeepBusinessAcceptanceProfileError(
            "deep-business acceptance profile schema is not closed"
        )
    if (
        root.get("contract") != PROFILE_CONTRACT
        or root.get("profile_id") != PROFILE_ID
        or tuple(root.get("versions", ())) != SUPPORTED_VERSIONS
        or tuple(root.get("required_families", ())) != REQUIRED_FAMILIES
        or root.get("model") != MODEL
        or root.get("totals") != {"task_count": PROFILE_TASK_COUNT}
    ):
        raise DeepBusinessAcceptanceProfileError(
            "deep-business acceptance profile identity drifted"
        )
    raw_tasks = root.get("tasks")
    if not isinstance(raw_tasks, list) or len(raw_tasks) != PROFILE_TASK_COUNT:
        raise DeepBusinessAcceptanceProfileError(
            f"deep-business acceptance task count must be {PROFILE_TASK_COUNT}"
        )
    repo_root = Path(__file__).resolve().parents[3]
    complete = tuple(
        _load_task(value, index=index, repo_root=repo_root)
        for index, value in enumerate(raw_tasks)
    )
    _validate_complete(complete)

    selected_ids = _unique_strings(unit_ids, "unit ids")
    selected_versions = _unique_strings(versions, "versions")
    known_ids = {unit.unit_id for unit in complete}
    unknown_ids = sorted(set(selected_ids) - known_ids)
    if unknown_ids:
        raise DeepBusinessAcceptanceProfileError(
            "unknown deep-business acceptance unit ids: " + ", ".join(unknown_ids)
        )
    unknown_versions = sorted(set(selected_versions) - set(SUPPORTED_VERSIONS))
    if unknown_versions:
        raise DeepBusinessAcceptanceProfileError(
            "unknown deep-business acceptance versions: "
            + ", ".join(unknown_versions)
        )
    selected = tuple(
        unit
        for unit in complete
        if (not selected_ids or unit.unit_id in selected_ids)
        and (not selected_versions or unit.version in selected_versions)
    )
    if not selected:
        raise DeepBusinessAcceptanceProfileError(
            "no deep-business acceptance units matched the filters"
        )
    return DeepBusinessAcceptanceProfile(
        path=profile_path,
        definition_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        units=selected,
    )


def _load_task(
    value: Any,
    *,
    index: int,
    repo_root: Path,
) -> DeepBusinessAcceptanceUnit:
    path = f"tasks[{index}]"
    if not isinstance(value, Mapping) or set(value) != _TASK_KEYS:
        raise DeepBusinessAcceptanceProfileError(f"{path} schema is not closed")
    family = _text(value.get("family"), f"{path}.family")
    component_profile = _text(
        value.get("component_profile"), f"{path}.component_profile"
    )
    component_suite = _text(
        value.get("component_suite"), f"{path}.component_suite"
    )
    unit_id = _text(value.get("unit_id"), f"{path}.unit_id")
    version = _text(value.get("version"), f"{path}.version")
    descriptor = _COMPONENTS.get(component_profile)
    if descriptor is None or descriptor[0] != component_suite:
        raise DeepBusinessAcceptanceProfileError(
            f"{path} component profile/suite is not reviewed"
        )
    suite_path = (repo_root / component_suite).resolve(strict=True)
    module = importlib.import_module(descriptor[1])
    loader = getattr(module, descriptor[2])
    try:
        component = loader(
            suite_path,
            unit_ids=(unit_id,),
            versions=(version,),
        )
    except (OSError, TypeError, ValueError) as exc:
        raise DeepBusinessAcceptanceProfileError(
            f"{path} component unit is invalid: {exc}"
        ) from exc
    if len(component.units) != 1:
        raise DeepBusinessAcceptanceProfileError(
            f"{path} component filter did not select exactly one unit"
        )
    return DeepBusinessAcceptanceUnit(
        family=family,
        component_profile_id=component_profile,
        component_suite_path=suite_path,
        component_unit=component.units[0],
    )


def _validate_complete(units: Sequence[DeepBusinessAcceptanceUnit]) -> None:
    ids = tuple(unit.unit_id for unit in units)
    if len(ids) != len(set(ids)):
        raise DeepBusinessAcceptanceProfileError(
            "deep-business acceptance unit ids must be unique"
        )
    families = tuple(unit.family for unit in units)
    if len(families) != len(set(families)) or set(families) != set(REQUIRED_FAMILIES):
        raise DeepBusinessAcceptanceProfileError(
            "deep-business acceptance family coverage drifted"
        )
    if {unit.version for unit in units} != set(SUPPORTED_VERSIONS):
        raise DeepBusinessAcceptanceProfileError(
            "deep-business acceptance version coverage drifted"
        )


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeepBusinessAcceptanceProfileError(
            f"deep-business acceptance profile is invalid: {exc}"
        ) from exc
    if not isinstance(value, Mapping):
        raise DeepBusinessAcceptanceProfileError(
            "deep-business acceptance profile root must be an object"
        )
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise DeepBusinessAcceptanceProfileError(f"{path} must be non-empty text")
    return value


def _unique_strings(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(str(value) for value in values)
    if len(normalized) != len(set(normalized)):
        raise DeepBusinessAcceptanceProfileError(f"duplicate {label} are not allowed")
    return normalized


__all__ = [
    "DeepBusinessAcceptanceProfile",
    "DeepBusinessAcceptanceProfileError",
    "DeepBusinessAcceptanceUnit",
    "MODEL",
    "PROFILE_CONTRACT",
    "PROFILE_ID",
    "PROFILE_TASK_COUNT",
    "REQUIRED_FAMILIES",
    "SUPPORTED_VERSIONS",
    "load_deep_business_acceptance_profile",
]
