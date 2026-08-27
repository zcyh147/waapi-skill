"""Compile exact tabular and Lua artifacts into canonical operation requests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .builders.debug_lua import (
    CLI_LUA_RESERVED_FIELDS,
    CORE_LUA_RESERVED_FIELDS,
    DebugLuaContractError,
    LUA_SOURCE_AUTHORITY,
    normalize_lua_wa_args,
    seal_inline_lua_source,
    seal_isolated_lua_file,
)
from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .exact_artifact_business_contracts import (
    EXACT_ARTIFACT_BUSINESS_OPERATIONS,
    exact_artifact_business_contract_data,
)


_IMPORT_MODES = {
    "create": "createNew",
    "reimport": "useExisting",
    "replace": "replaceExisting",
}

EXACT_ARTIFACT_EVIDENCE_CONTRACT = (
    "waapi-skill.exact-artifact-evidence/v1"
)


def materialize_exact_artifact_business_request(
    operation: str,
    session: BusinessDeclarationSession,
    *,
    allow_cleaned_file_evidence: bool = False,
) -> Mapping[str, Any]:
    """Return one canonical request from one complete high-level declaration."""

    if operation not in EXACT_ARTIFACT_BUSINESS_OPERATIONS:
        raise ValueError("unsupported exact-artifact operation")
    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    setting_fields = set(session.settings)
    allowed_setting_fields = (
        ({"artifact_plan"},)
        if operation == "audio.importTabDelimited"
        else ({"artifact_plan"}, {"artifact_plan", "artifact_evidence"})
    )
    if setting_fields not in allowed_setting_fields:
        raise _repair(
            session,
            "BUSINESS_DECLARATION_INCOMPLETE",
            field="artifact_plan",
            action="submit one complete disclosed artifact plan",
        )
    raw = session.settings["artifact_plan"]
    if not isinstance(raw, Mapping):
        raise _repair(
            session,
            "INVALID_ARGUMENT",
            field="artifact_plan",
            action="submit one structured artifact plan",
        )
    plan = dict(raw)
    contract = exact_artifact_business_contract_data(
        operation,
        session.context.wwise_version,
    )
    declaration = contract["declaration"]
    allowed = set(declaration["public_fields"])
    required = set(declaration["required_fields"])
    missing = sorted(required - set(plan))
    unexpected = sorted(set(plan) - allowed)
    if missing or unexpected:
        raise _repair(
            session,
            "INVALID_ARGUMENT",
            field="artifact_plan",
            action="use exactly the disclosed high-level fields",
            missing_fields=missing,
            unexpected_fields=unexpected,
        )

    if operation == "audio.importTabDelimited":
        arguments = _materialize_tab_import(session, plan)
    else:
        arguments = _materialize_lua(
            session,
            operation,
            plan,
            evidence=session.settings.get("artifact_evidence"),
            allow_cleaned_file_evidence=allow_cleaned_file_evidence,
        )
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": session.context.wwise_version,
        "operation": operation,
        "arguments": arguments,
    }


def _materialize_tab_import(
    session: BusinessDeclarationSession,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    handle = plan.get("location_handle")
    if not isinstance(handle, str):
        raise _repair(
            session,
            "INVALID_ARGUMENT",
            field="location_handle",
            action="copy the handle returned by the import_location role",
        )
    try:
        location = session.handles.resolve_object(handle)
    except Exception as exc:
        raise _repair(
            session,
            "BOUND_OBJECT_UNAVAILABLE",
            field="location_handle",
            action="bind the exact import location again",
        ) from exc
    if location.role != "import_location":
        raise _repair(
            session,
            "BOUND_OBJECT_ROLE_MISMATCH",
            field="location_handle",
            action="copy the handle from the import_location role",
            expected_role="import_location",
            actual_role=location.role,
        )
    for field in ("table_file", "language"):
        value = plan.get(field)
        if not isinstance(value, str) or not value:
            raise _repair(
                session,
                "INVALID_ARGUMENT",
                field=field,
                action=f"provide one nonempty exact {field}",
            )
    mode = plan.get("mode", "create")
    if mode not in _IMPORT_MODES:
        raise _repair(
            session,
            "INVALID_ARGUMENT",
            field="mode",
            action="choose create, reimport, or replace",
            choices=sorted(_IMPORT_MODES),
        )
    arguments: dict[str, Any] = {
        "import_file": plan["table_file"],
        "import_location": {"kind": "id", "value": location.object_id},
        "import_language": plan["language"],
    }
    if "mode" in plan:
        arguments["import_operation"] = _IMPORT_MODES[str(mode)]
    for public, native in (
        ("add_to_source_control", "auto_add_to_source_control"),
        ("check_out_from_source_control", "auto_check_out_to_source_control"),
    ):
        if public not in plan:
            continue
        value = plan[public]
        if type(value) is not bool:
            raise _repair(
                session,
                "INVALID_ARGUMENT",
                field=public,
                action="provide a JSON boolean or omit the setting",
            )
        if (
            public == "check_out_from_source_control"
            and session.context.wwise_version in {"2021.1", "2022.1"}
        ):
            raise _repair(
                session,
                "VERSION_BEHAVIOR_BOUNDARY",
                field=public,
                action="omit this setting before Wwise 2023.1",
            )
        arguments[native] = value
    return arguments


def _materialize_lua(
    session: BusinessDeclarationSession,
    operation: str,
    plan: Mapping[str, Any],
    *,
    evidence: Any,
    allow_cleaned_file_evidence: bool,
) -> dict[str, Any]:
    reserved = (
        CLI_LUA_RESERVED_FIELDS
        if operation == "lua.executeCliFile"
        else CORE_LUA_RESERVED_FIELDS
    )
    try:
        wa_args = normalize_lua_wa_args(
            plan.get("arguments"),
            reserved_fields=reserved,
        )
        if operation.endswith("File"):
            script_file = plan.get("script_file")
            if not isinstance(script_file, str) or not script_file:
                raise DebugLuaContractError(
                    "INVALID_ARGUMENT",
                    "script_file must be one exact absolute file path.",
                )
            if allow_cleaned_file_evidence:
                io_root = _sealed_io_root(session, evidence)
            else:
                io_root = str(Path(script_file).parent)
                proof = seal_isolated_lua_file(
                    script_file,
                    io_root=io_root,
                    source_authority=LUA_SOURCE_AUTHORITY,
                )
                io_root = str(proof["io_root"])
                _require_matching_io_root(session, evidence, io_root)
            arguments: dict[str, Any] = {
                "script_file": script_file,
                "io_root": io_root,
                "source_authority": LUA_SOURCE_AUTHORITY,
            }
        else:
            source = plan.get("lua_source")
            io_root = plan.get("io_root")
            if allow_cleaned_file_evidence:
                io_root = _sealed_io_root(session, evidence)
            else:
                proof = seal_inline_lua_source(
                    source,
                    io_root=io_root,
                    source_authority=LUA_SOURCE_AUTHORITY,
                )
                io_root = proof["io_root"]
                _require_matching_io_root(session, evidence, io_root)
            arguments = {
                "lua_code": source,
                "io_root": io_root,
                "source_authority": LUA_SOURCE_AUTHORITY,
            }
    except DebugLuaContractError as exc:
        raise _repair(
            session,
            exc.error_code,
            field=str(exc.details.get("field", "artifact_plan")),
            action="correct the exact source or bounded argument map",
            **{
                key: value
                for key, value in exc.details.items()
                if key != "field"
            },
        ) from exc
    if wa_args:
        arguments["wa_args"] = wa_args
    if "watchdog_seconds" in plan:
        watchdog = plan["watchdog_seconds"]
        if (
            operation != "lua.executeCliFile"
            or session.context.wwise_version not in {"2024.1", "2025.1"}
            or isinstance(watchdog, bool)
            or not isinstance(watchdog, int)
            or watchdog < 0
        ):
            raise _repair(
                session,
                "VERSION_BEHAVIOR_BOUNDARY",
                field="watchdog_seconds",
                action="omit it or use a non-negative integer on CLI Wwise 2024.1+",
            )
        arguments["watchdog_seconds"] = watchdog
    return arguments


def exact_artifact_evidence_from_request(
    operation: str,
    request: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Persist the live-sealed root needed for file-free archive replay."""

    if operation == "audio.importTabDelimited":
        return None
    arguments = request.get("arguments")
    io_root = arguments.get("io_root") if isinstance(arguments, Mapping) else None
    if not isinstance(io_root, str) or not io_root:
        raise ValueError("exact-artifact request lacks its sealed io_root")
    return {
        "contract": EXACT_ARTIFACT_EVIDENCE_CONTRACT,
        "io_root": io_root,
    }


def _sealed_io_root(
    session: BusinessDeclarationSession,
    evidence: Any,
) -> str:
    if (
        not isinstance(evidence, Mapping)
        or set(evidence) != {"contract", "io_root"}
        or evidence.get("contract") != EXACT_ARTIFACT_EVIDENCE_CONTRACT
        or not isinstance(evidence.get("io_root"), str)
        or not evidence["io_root"]
    ):
        raise _repair(
            session,
            "ARCHIVE_EVIDENCE_REQUIRED",
            field="artifact_evidence",
            action="replay the durable Draft that recorded the live-sealed root",
        )
    return str(evidence["io_root"])


def _require_matching_io_root(
    session: BusinessDeclarationSession,
    evidence: Any,
    actual: str,
) -> None:
    if evidence is None:
        return
    expected = _sealed_io_root(session, evidence)
    if expected != actual:
        raise _repair(
            session,
            "ARTIFACT_EVIDENCE_DRIFT",
            field="artifact_evidence.io_root",
            action="declare the exact artifact again against the current filesystem",
            expected=expected,
            actual=actual,
        )


def _repair(
    session: BusinessDeclarationSession,
    error_code: str,
    *,
    field: str,
    action: str,
    **details: Any,
):
    return business_repair(
        error_code,
        field=field,
        action=action,
        draft_revision=session.revision,
        **details,
    )


__all__ = [
    "EXACT_ARTIFACT_EVIDENCE_CONTRACT",
    "exact_artifact_evidence_from_request",
    "materialize_exact_artifact_business_request",
]
