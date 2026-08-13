"""Closed business-plan sections for exact direct and weak-result tasks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_archive_paths import (
    ArchiveRelativePathError,
    archive_absolute_names_equal,
    parse_archive_absolute_path,
    parse_archive_relative_path,
)
from wwise_waapi.host_paths import HostPathError, localize_waapi_host_path


DIRECT_BUSINESS_PLAN_SCHEMA = "waapi-skill.direct-business-plan/v1"
DIRECT_FIXTURE_KIND = "direct_typed_protocol_v1"
DIRECT_ASSERTION_IDS = (
    "direct.identity.exact",
    "direct.protocol.complete",
    "direct.live_binding.sealed",
    "direct.verification.truthful",
)
VERIFICATION_BOUNDARIES = frozenset(
    {"exact_host_identity", "result_schema_only"}
)
DIRECT_APIS = frozenset(
    {"ak.wwise.core.getInfo", "ak.wwise.core.executeLuaScript"}
)
_STEP_KEYS = frozenset({"name", "subcommand"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class DirectBusinessPlanError(ValueError):
    """One direct typed business plan is malformed or drifted."""


@dataclass(frozen=True, slots=True)
class DirectBusinessPlanSections:
    fixture_spec: Mapping[str, Any]
    payload_bindings: Mapping[str, Any]
    assertion_ids: tuple[str, ...]
    static_expectation: Mapping[str, Any]
    live_binding: Mapping[str, Any]
    delta_rules: tuple[Mapping[str, Any], ...]

    def writer_kwargs(self) -> dict[str, Any]:
        return {
            "fixture_spec": dict(self.fixture_spec),
            "payload_bindings": dict(self.payload_bindings),
            "assertion_ids": list(self.assertion_ids),
            "static_expectation": _plain(self.static_expectation),
            "live_binding": _plain(self.live_binding),
            "delta_rules": [_plain(value) for value in self.delta_rules],
        }


def compile_direct_business_plan(
    *,
    scenario_id: str,
    api: str,
    protocol_steps: Sequence[Mapping[str, Any]],
    live_bindings: Mapping[str, Any],
    verification_boundary: str,
) -> DirectBusinessPlanSections:
    _identifier(scenario_id, "scenario_id")
    if not isinstance(api, str) or not api.startswith(("ak.wwise.", "ak.soundengine.")):
        raise DirectBusinessPlanError("direct plan API is invalid")
    if verification_boundary not in VERIFICATION_BOUNDARIES:
        raise DirectBusinessPlanError("direct plan verification boundary is invalid")
    steps = tuple(_step(value, index=index) for index, value in enumerate(protocol_steps))
    if not steps:
        raise DirectBusinessPlanError("direct plan protocol must be nonempty")
    bindings = _json_object(live_bindings, "live_bindings")
    static = {
        "family_schema_version": DIRECT_BUSINESS_PLAN_SCHEMA,
        "scenario_id": scenario_id,
        "api": api,
        "protocol_steps": list(steps),
        "verification_boundary": verification_boundary,
    }
    live = {
        "family_schema_version": DIRECT_BUSINESS_PLAN_SCHEMA,
        "scenario_id": scenario_id,
        "bindings": bindings,
        "bindings_sha256": _sha256(bindings),
    }
    fixture = {
        "kind": DIRECT_FIXTURE_KIND,
        "sha256": _sha256({"static": static, "live": live}),
    }
    return DirectBusinessPlanSections(
        fixture_spec=MappingProxyType(fixture),
        payload_bindings=MappingProxyType(
            {
                "primary_steps": [
                    next(
                        (
                            step["name"]
                            for step in steps
                            if step["name"].endswith(".execute")
                        ),
                        steps[-1]["name"],
                    )
                ],
                "verification_steps": [steps[-1]["name"]],
            }
        ),
        assertion_ids=DIRECT_ASSERTION_IDS,
        static_expectation=MappingProxyType(static),
        live_binding=MappingProxyType(live),
        delta_rules=(),
    )


def validate_direct_business_plan(
    sections: DirectBusinessPlanSections,
    **inputs: Any,
) -> DirectBusinessPlanSections:
    if not isinstance(sections, DirectBusinessPlanSections):
        raise DirectBusinessPlanError("direct plan sections have the wrong type")
    expected = compile_direct_business_plan(**inputs)
    if sections.writer_kwargs() != expected.writer_kwargs():
        raise DirectBusinessPlanError("direct plan differs from reviewed inputs")
    return sections


def parse_direct_business_plan_sections(
    payload: Mapping[str, Any],
) -> DirectBusinessPlanSections:
    """Parse one persisted direct plan without trusting its sealed digest."""

    required = {
        "fixture_spec",
        "payload_bindings",
        "assertion_ids",
        "static_expectation",
        "live_binding",
        "delta_rules",
    }
    if not isinstance(payload, Mapping) or not required.issubset(payload):
        raise DirectBusinessPlanError(
            "persisted direct business plan lacks required sections"
        )
    if any(
        not isinstance(payload[name], Mapping)
        for name in (
            "fixture_spec",
            "payload_bindings",
            "static_expectation",
            "live_binding",
        )
    ):
        raise DirectBusinessPlanError(
            "persisted direct business plan mapping is invalid"
        )
    if not isinstance(payload["assertion_ids"], (list, tuple)) or not isinstance(
        payload["delta_rules"], (list, tuple)
    ):
        raise DirectBusinessPlanError(
            "persisted direct business plan sequence is invalid"
        )
    sections = DirectBusinessPlanSections(
        fixture_spec=MappingProxyType(_json_object(payload["fixture_spec"], "fixture_spec")),
        payload_bindings=MappingProxyType(
            _json_object(payload["payload_bindings"], "payload_bindings")
        ),
        assertion_ids=tuple(_plain(payload["assertion_ids"])),
        static_expectation=MappingProxyType(
            _json_object(payload["static_expectation"], "static_expectation")
        ),
        live_binding=MappingProxyType(
            _json_object(payload["live_binding"], "live_binding")
        ),
        delta_rules=tuple(
            MappingProxyType(_json_object(item, "delta_rules item"))
            for item in payload["delta_rules"]
        ),
    )
    _validate_archived_shape(sections)
    return sections


def validate_direct_business_plan_archive(
    sections: DirectBusinessPlanSections,
    *,
    scenario_id: str,
    api: str,
    version: str,
    protocol_steps: Sequence[Mapping[str, Any]],
    status_payload: Mapping[str, Any] | None = None,
    sandbox_project: str | None = None,
) -> DirectBusinessPlanSections:
    """Independently bind a persisted direct plan to reviewed protocol truth."""

    _validate_archived_shape(sections)
    expected_boundary = (
        "exact_host_identity"
        if api == "ak.wwise.core.getInfo"
        else "result_schema_only"
        if api == "ak.wwise.core.executeLuaScript"
        else None
    )
    if expected_boundary is None or api not in DIRECT_APIS:
        raise DirectBusinessPlanError("direct archive API is unsupported")
    static = sections.static_expectation
    if static != {
        "family_schema_version": DIRECT_BUSINESS_PLAN_SCHEMA,
        "scenario_id": scenario_id,
        "api": api,
        "protocol_steps": [
            _step(item, index=index)
            for index, item in enumerate(protocol_steps)
        ],
        "verification_boundary": expected_boundary,
    }:
        raise DirectBusinessPlanError(
            "direct archive differs from reviewed identity or protocol"
        )
    bindings = sections.live_binding.get("bindings")
    if not isinstance(bindings, Mapping) or bindings.get("version") != version:
        raise DirectBusinessPlanError("direct archive version binding is invalid")
    _validate_live_bindings(api, bindings, version=version)
    if api == "ak.wwise.core.getInfo" and (
        status_payload is not None or sandbox_project is not None
    ):
        validate_direct_status_archive_binding(
            sections,
            status_payload=status_payload,
            sandbox_project=sandbox_project,
        )
    expected = compile_direct_business_plan(
        scenario_id=scenario_id,
        api=api,
        protocol_steps=protocol_steps,
        live_bindings=bindings,
        verification_boundary=expected_boundary,
    )
    if sections.writer_kwargs() != expected.writer_kwargs():
        raise DirectBusinessPlanError(
            "direct archive digest or derived bindings are invalid"
        )
    return sections


def validate_direct_status_archive_binding(
    sections: DirectBusinessPlanSections,
    *,
    status_payload: Mapping[str, Any] | None,
    sandbox_project: str | None,
) -> None:
    """Join archived getInfo identity to broker status and lifecycle start.

    Modern project paths are persisted only as the portable project filename;
    the broker and lifecycle may retain host-absolute POSIX, Wine-drive, or
    native-Windows spellings.  Their basenames must agree under the owning path
    flavor while the canonical project GUID/name/type remain exact.
    """

    static = sections.static_expectation
    bindings = sections.live_binding.get("bindings")
    if static.get("api") != "ak.wwise.core.getInfo" or not isinstance(
        bindings, Mapping
    ):
        raise DirectBusinessPlanError("status archive binding requires getInfo")
    expected = bindings.get("status")
    if (
        not isinstance(expected, Mapping)
        or not isinstance(status_payload, Mapping)
        or not isinstance(sandbox_project, str)
        or not sandbox_project
    ):
        raise DirectBusinessPlanError(
            "getInfo archive lacks broker status or lifecycle project evidence"
        )
    wwise = status_payload.get("wwise")
    project = status_payload.get("project")
    if not isinstance(wwise, Mapping) or not isinstance(project, Mapping):
        raise DirectBusinessPlanError("broker status identity is incomplete")
    build = _wwise_build(wwise)
    projected = {key: project.get(key) for key in ("id", "name", "type", "path")}
    version = bindings.get("version")
    if version == "2021.1":
        try:
            start_path = parse_archive_absolute_path(sandbox_project)
        except ArchiveRelativePathError as exc:
            raise DirectBusinessPlanError(
                "lifecycle project path identity is invalid"
            ) from exc
        if (
            project.get("path") != "\\"
            or not _archive_name_matches(
                start_path,
                f"{expected.get('project', {}).get('name')}.wproj",
            )
        ):
            raise DirectBusinessPlanError("legacy broker project path is invalid")
    else:
        try:
            status_path = parse_archive_absolute_path(str(project.get("path")))
            start_path = parse_archive_absolute_path(sandbox_project)
            expected_name = str(expected.get("project", {}).get("path"))
            portable = parse_archive_relative_path(expected_name)
            localized_status = Path(
                localize_waapi_host_path(str(project.get("path")))
            )
            native_start = Path(sandbox_project)
            if (
                portable.canonical != expected_name
                or len(portable.parts) != 1
                or not _archive_name_matches(start_path, expected_name)
                or not _archive_name_matches(status_path, expected_name)
                or not archive_absolute_names_equal(
                    str(project.get("path")), sandbox_project
                )
                or localized_status.parent != native_start.parent
            ):
                raise DirectBusinessPlanError(
                    "broker status project differs from lifecycle sandbox"
                )
            projected["path"] = expected_name
        except (ArchiveRelativePathError, HostPathError) as exc:
            raise DirectBusinessPlanError(
                "broker/lifecycle project path identity is invalid"
            ) from exc
    if (
        build != bindings.get("build")
        or wwise.get("processId") != bindings.get("process_id")
        or projected != expected.get("project")
        or expected.get("wwise_build") != build
        or expected.get("process_id") != wwise.get("processId")
    ):
        raise DirectBusinessPlanError(
            "broker status differs from the archived getInfo identity"
        )


def _wwise_build(value: Mapping[str, Any]) -> str:
    version = value.get("version")
    if not isinstance(version, Mapping):
        raise DirectBusinessPlanError("broker status lacks Wwise version")
    fields = tuple(version.get(key) for key in ("year", "major", "minor", "build"))
    if not all(type(item) is int and item >= 0 for item in fields):
        raise DirectBusinessPlanError("broker status Wwise version is incomplete")
    return ".".join(str(item) for item in fields)


def validate_direct_archived_verification(
    sections: DirectBusinessPlanSections,
    verification: Mapping[str, Any],
    *,
    weak_report: bool = False,
) -> None:
    """Bind persisted PASS evidence to the direct plan's exact live values."""

    if not isinstance(verification, Mapping):
        raise DirectBusinessPlanError("direct verification is not an object")
    api = sections.static_expectation.get("api")
    bindings = sections.live_binding.get("bindings")
    if not isinstance(bindings, Mapping):
        raise DirectBusinessPlanError("direct verification lacks live bindings")
    if verification.get("passed") is not True or verification.get("failures") != []:
        raise DirectBusinessPlanError("direct verification is not a clean PASS")
    evidence = verification.get("evidence")
    if not isinstance(evidence, Mapping):
        raise DirectBusinessPlanError("direct verification evidence is invalid")
    if api == "ak.wwise.core.getInfo" and not weak_report:
        expected = {
            "expected_build": bindings["build"],
            "expected_process_id": bindings["process_id"],
            "expected_result_sha256": bindings["result_sha256"],
            "actual_result_sha256": bindings["result_sha256"],
        }
    elif api == "ak.wwise.core.executeLuaScript" and weak_report:
        expected = {"turn_index": 2, "weak_boundary_reported": True}
    elif api == "ak.wwise.core.executeLuaScript":
        expected = {
            "expected_return": bindings["expected_return"],
            "actual_return": bindings["expected_return"],
            "business_state_verified": False,
            "script_sha256": bindings["script_sha256"],
        }
    else:
        raise DirectBusinessPlanError(
            "direct verification is cross-bound to its API or phase"
        )
    if dict(evidence) != expected:
        raise DirectBusinessPlanError(
            "direct verification differs from its sealed live binding"
        )


def _validate_archived_shape(sections: DirectBusinessPlanSections) -> None:
    if sections.assertion_ids != DIRECT_ASSERTION_IDS or sections.delta_rules != ():
        raise DirectBusinessPlanError("direct archive assertion vocabulary is invalid")
    if set(sections.fixture_spec) != {"kind", "sha256"} or sections.fixture_spec.get(
        "kind"
    ) != DIRECT_FIXTURE_KIND:
        raise DirectBusinessPlanError("direct archive fixture identity is invalid")
    if set(sections.payload_bindings) != {
        "primary_steps",
        "verification_steps",
    }:
        raise DirectBusinessPlanError("direct archive payload bindings are invalid")
    if set(sections.live_binding) != {
        "family_schema_version",
        "scenario_id",
        "bindings",
        "bindings_sha256",
    }:
        raise DirectBusinessPlanError("direct archive live envelope is invalid")


def _validate_live_bindings(
    api: str,
    bindings: Mapping[str, Any],
    *,
    version: str,
) -> None:
    sha_fields = {"result_sha256", "project_digest"}
    if api == "ak.wwise.core.getInfo":
        if set(bindings) != {
            "version",
            "build",
            "process_id",
            "launch_process_id",
            "session_id",
            "result_sha256",
            "project_digest",
            "status",
        }:
            raise DirectBusinessPlanError("getInfo live binding is not closed")
        if (
            not isinstance(bindings.get("build"), str)
            or not bindings["build"].startswith(version + ".")
            or type(bindings.get("process_id")) is not int
            or bindings["process_id"] <= 0
            or type(bindings.get("launch_process_id")) is not int
            or bindings["launch_process_id"] <= 0
            or not isinstance(bindings.get("session_id"), str)
            or not _valid_status_binding(
                bindings.get("status"),
                version=version,
                build=bindings.get("build"),
                process_id=bindings.get("process_id"),
            )
        ):
            raise DirectBusinessPlanError("getInfo live identity is invalid")
    else:
        sha_fields = {"script_sha256", "project_digest"}
        if set(bindings) != {
            "version",
            "script_file",
            "script_sha256",
            "dispatch",
            "project_digest",
            "expected_return",
        }:
            raise DirectBusinessPlanError("Lua live binding is not closed")
        dispatch = bindings.get("dispatch")
        if (
            not isinstance(bindings.get("script_file"), str)
            or not bindings["script_file"]
            or bindings.get("expected_return")
            != {"profile": "typed_input", "count": 3}
            or not isinstance(dispatch, Mapping)
            or dispatch.get("uri") != "ak.wwise.core.executeLuaScript"
        ):
            raise DirectBusinessPlanError("Lua live identity is invalid")
    if any(
        not isinstance(bindings.get(field), str)
        or re.fullmatch(r"[0-9a-f]{64}", bindings[field]) is None
        for field in sha_fields
    ):
        raise DirectBusinessPlanError("direct live digest is invalid")


def _valid_status_binding(
    value: Any,
    *,
    version: str,
    build: Any,
    process_id: Any,
) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "wwise_build",
        "process_id",
        "project",
    }:
        return False
    project = value.get("project")
    return bool(
        value.get("wwise_build") == build
        and value.get("process_id") == process_id
        and isinstance(project, Mapping)
        and set(project) == {"id", "name", "type", "path"}
        and isinstance(project.get("id"), str)
        and re.fullmatch(
            r"\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\}",
            project["id"],
        )
        is not None
        and isinstance(project.get("name"), str)
        and bool(project["name"])
        and project.get("type") == "Project"
        and isinstance(project.get("path"), str)
        and bool(project["path"])
        and (
            project["path"] == "\\"
            if version == "2021.1"
            else _valid_portable_project_name(project["path"])
        )
    )


def _valid_portable_project_name(value: Any) -> bool:
    try:
        parsed = parse_archive_relative_path(value)
    except ArchiveRelativePathError:
        return False
    return (
        parsed.canonical == value
        and len(parsed.parts) == 1
        and parsed.parts[0].casefold().endswith(".wproj")
    )


def _archive_name_matches(path: Any, expected_name: str) -> bool:
    if path.source_flavor == "windows":
        return path.name.casefold() == expected_name.casefold()
    return path.name == expected_name


def _step(value: Mapping[str, Any], *, index: int) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _STEP_KEYS:
        raise DirectBusinessPlanError(f"protocol_steps[{index}] is not closed")
    name = value.get("name")
    subcommand = value.get("subcommand")
    _identifier(name, f"protocol_steps[{index}].name")
    _identifier(subcommand, f"protocol_steps[{index}].subcommand")
    return {"name": str(name), "subcommand": str(subcommand)}


def _identifier(value: Any, field: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise DirectBusinessPlanError(f"{field} is invalid")


def _json_object(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DirectBusinessPlanError(f"{field} must be an object")
    normalized = _plain(value)
    if not isinstance(normalized, dict):
        raise DirectBusinessPlanError(f"{field} must be an object")
    return normalized


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        value = {str(key): _plain(item) for key, item in value.items()}
    elif isinstance(value, (list, tuple)):
        value = [_plain(item) for item in value]
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise DirectBusinessPlanError("direct plan values must be strict JSON") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "DIRECT_BUSINESS_PLAN_SCHEMA",
    "DIRECT_FIXTURE_KIND",
    "DirectBusinessPlanError",
    "DirectBusinessPlanSections",
    "compile_direct_business_plan",
    "parse_direct_business_plan_sections",
    "validate_direct_archived_verification",
    "validate_direct_business_plan",
    "validate_direct_business_plan_archive",
    "validate_direct_status_archive_binding",
]
