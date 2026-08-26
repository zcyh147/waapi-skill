"""Compile high-level SoundBank plans into closed operation requests."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import (
    BoundObjectHandle,
    bound_object_identity_for_handle,
    business_repair,
)
from .soundbank_business_contracts import soundbank_business_contract_data


_NATIVE_FIELDS = frozenset(
    {
        "batch_layout",
        "identity_selector",
        "native_request",
        "native_rows",
        "object_path",
        "request_fragment",
        "skip_languages",
        "waapi_args",
        "waapi_options",
        "wire_type",
        "write_to_disk",
    }
)
_FILTERS = ("events", "structures", "media")
_GENERATE_FILTERS = {
    "events": "event",
    "structures": "structure",
    "media": "media",
}


def _error(code: str, field: str, action: str, **details: Any) -> None:
    raise business_repair(
        code,
        field=field,
        action=action,
        **details,
    )


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _error(
            "BUSINESS_PLAN_INVALID",
            field,
            "submit one complete disclosed SoundBank plan",
        )
    return dict(value)


def _sequence(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        _error(
            "BUSINESS_PLAN_INVALID",
            field,
            "submit one bounded list in the disclosed business shape",
        )
    return list(value)


def _bounded_sequence(
    value: Any,
    *,
    field: str,
    maximum: int,
    allow_empty: bool = False,
) -> list[Any]:
    rows = _sequence(value, field=field)
    if not rows and not allow_empty:
        _error(
            "BUSINESS_VALUE_INVALID",
            field,
            "provide at least one value in the disclosed business list",
        )
    if len(rows) > maximum:
        _error(
            "BUSINESS_VALUE_LIMIT_EXCEEDED",
            field,
            "split the request into bounded business plans",
            count=len(rows),
            limit=maximum,
        )
    return rows


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _error(
            "BUSINESS_VALUE_INVALID",
            field,
            "provide one non-empty exact business value",
        )
    return value


def _exact_fields(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    field: str,
) -> dict[str, Any]:
    row = dict(value)
    native = sorted(set(row) & _NATIVE_FIELDS)
    if native:
        _error(
            "NATIVE_FIELD_FORBIDDEN",
            native[0],
            "provide business meaning and let the Gateway derive native planning",
        )
    missing = sorted(required - set(row))
    unexpected = sorted(set(row) - required - optional)
    if missing:
        _error(
            "REQUIRED_FIELD_MISSING",
            missing[0],
            "submit one complete disclosed SoundBank plan",
            missing=missing,
        )
    if unexpected:
        _error(
            "BUSINESS_FIELD_UNAVAILABLE",
            unexpected[0],
            "use only fields disclosed by operation-schema",
            unexpected=unexpected,
        )
    return row


def _bound(
    session: BusinessDeclarationSession,
    handle: Any,
    *,
    field: str,
    object_types: set[str] | None = None,
    role: str | None = None,
) -> BoundObjectHandle:
    if not isinstance(handle, str):
        _error(
            "OBJECT_HANDLE_NOT_AVAILABLE",
            field,
            "bind the exact live object and copy its returned handle",
        )
    bound = session.handles.resolve_object(handle)
    if object_types is not None and bound.object_type.casefold() not in {
        item.casefold() for item in object_types
    }:
        _error(
            "BOUND_OBJECT_TYPE_MISMATCH",
            field,
            "bind one live object of the disclosed business type",
            expected_types=sorted(object_types),
            actual_type=bound.object_type,
        )
    if role is not None and bound.role != role:
        _error(
            "BOUND_OBJECT_ROLE_MISMATCH",
            field,
            "bind the object through the matching Gateway-owned role route",
            expected_role=role,
            actual_role=bound.role,
        )
    return bound


def _filters(value: Any, *, field: str) -> list[str]:
    rows = [
        _text(item, field=field)
        for item in _bounded_sequence(value, field=field, maximum=3)
    ]
    if not rows or len(rows) != len(set(rows)) or any(
        item not in _FILTERS for item in rows
    ):
        _error(
            "BUSINESS_VALUE_INVALID",
            field,
            "choose one or more unique events, structures, and media values",
            choices=list(_FILTERS),
        )
    return rows


def _materialize_generate(
    session: BusinessDeclarationSession,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    source = _exact_fields(
        plan,
        required={"soundbanks", "platforms", "io_root"},
        optional={
            "languages",
            "rebuild_soundbanks",
            "clear_audio_file_cache",
            "rebuild_init_bank",
        },
        field="soundbank_plan",
    )
    banks: list[dict[str, Any]] = []
    for index, raw in enumerate(
        _bounded_sequence(
            source["soundbanks"],
            field="soundbanks",
            maximum=64,
        )
    ):
        bank = _exact_fields(
            _mapping(raw, field=f"soundbanks[{index}]"),
            required={"soundbank_handle", "artifact_expectation"},
            optional={
                "rebuild",
                "event_handles",
                "aux_bus_handles",
                "inclusions",
            },
            field=f"soundbanks[{index}]",
        )
        bound_bank = _bound(
            session,
            bank["soundbank_handle"],
            field=f"soundbanks[{index}].soundbank_handle",
            object_types={"SoundBank"},
            role="soundbank",
        )
        expectation = _text(
            bank["artifact_expectation"],
            field=f"soundbanks[{index}].artifact_expectation",
        )
        if expectation not in {"nonlocalized", "localized", "mixed"}:
            _error(
                "BUSINESS_VALUE_INVALID",
                f"soundbanks[{index}].artifact_expectation",
                "choose nonlocalized, localized, or mixed",
            )
        row: dict[str, Any] = {
            "name": bound_bank.name,
            "artifact_expectation": expectation,
        }
        if "rebuild" in bank:
            if not isinstance(bank["rebuild"], bool):
                _error(
                    "BUSINESS_VALUE_INVALID",
                    f"soundbanks[{index}].rebuild",
                    "provide true or false",
                )
            row["rebuild"] = bank["rebuild"]
        for public, output, object_type, role in (
            ("event_handles", "events", "Event", "event"),
            ("aux_bus_handles", "aux_busses", "AuxBus", "aux_bus"),
        ):
            if public not in bank:
                continue
            handles = _bounded_sequence(
                bank[public],
                field=f"soundbanks[{index}].{public}",
                maximum=256,
            )
            row[output] = [
                bound_object_identity_for_handle(
                    session.handles,
                    _bound(
                        session,
                        handle,
                        field=f"soundbanks[{index}].{public}[{handle_index}]",
                        object_types={object_type},
                        role=role,
                    ).handle,
                    field=f"soundbanks[{index}].{public}[{handle_index}]",
                    action="bind the exact live object and copy its returned handle",
                )
                for handle_index, handle in enumerate(handles)
            ]
        if "inclusions" in bank:
            row["inclusions"] = [
                _GENERATE_FILTERS[item]
                for item in _filters(
                    bank["inclusions"],
                    field=f"soundbanks[{index}].inclusions",
                )
            ]
        banks.append(row)
    platforms = [
        _text(value, field="platforms")
        for value in _bounded_sequence(
            source["platforms"],
            field="platforms",
            maximum=16,
        )
    ]
    language_dependent = any(
        row["artifact_expectation"] in {"localized", "mixed"}
        for row in banks
    )
    arguments: dict[str, Any] = {
        "soundbanks": banks,
        "platforms": platforms,
        "skip_languages": not language_dependent,
        "write_to_disk": True,
        "io_root": _text(source["io_root"], field="io_root"),
    }
    if language_dependent:
        languages = [
            _text(value, field="languages")
            for value in _bounded_sequence(
                source.get("languages"),
                field="languages",
                maximum=64,
            )
        ]
        arguments["languages"] = languages
    elif "languages" in source:
        _error(
            "BUSINESS_FIELD_UNAVAILABLE",
            "languages",
            "omit languages when every requested SoundBank is nonlocalized",
        )
    for name in (
        "rebuild_soundbanks",
        "clear_audio_file_cache",
        "rebuild_init_bank",
    ):
        if name in source:
            if not isinstance(source[name], bool):
                _error(
                    "BUSINESS_VALUE_INVALID",
                    name,
                    "provide true or false",
                )
            arguments[name] = source[name]
    return arguments


def _materialize_inclusions(
    session: BusinessDeclarationSession,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    source = _exact_fields(
        plan,
        required={"soundbank_handle", "mode", "inclusions"},
        field="soundbank_plan",
    )
    mode = _text(source["mode"], field="mode")
    if mode not in {"add", "remove", "replace"}:
        _error(
            "BUSINESS_VALUE_INVALID",
            "mode",
            "choose add, remove, or replace",
        )
    bound_bank = _bound(
        session,
        source["soundbank_handle"],
        field="soundbank_handle",
        object_types={"SoundBank"},
        role="soundbank",
    )
    inclusions: list[dict[str, Any]] = []
    for index, raw in enumerate(
        _bounded_sequence(
            source["inclusions"],
            field="inclusions",
            maximum=128,
            allow_empty=True,
        )
    ):
        row = _exact_fields(
            _mapping(raw, field=f"inclusions[{index}]"),
            required={"object_handle", "filters"},
            field=f"inclusions[{index}]",
        )
        bound_object = _bound(
            session,
            row["object_handle"],
            field=f"inclusions[{index}].object_handle",
            role="inclusion_object",
        )
        inclusions.append(
            {
                "object": bound_object_identity_for_handle(
                    session.handles,
                    bound_object.handle,
                    field=f"inclusions[{index}].object_handle",
                    action="bind the exact live inclusion object and copy its handle",
                ),
                "filters": _filters(
                    row["filters"],
                    field=f"inclusions[{index}].filters",
                ),
            }
        )
    if mode != "replace" and not inclusions:
        _error(
            "BUSINESS_VALUE_INVALID",
            "inclusions",
            "add and remove require at least one inclusion row",
        )
    return {
        "soundbank": bound_object_identity_for_handle(
            session.handles,
            bound_bank.handle,
            field="soundbank_handle",
            action="bind the exact live SoundBank and copy its returned handle",
        ),
        "mode": mode,
        "inclusions": inclusions,
    }


def _materialize_external_sources(plan: Mapping[str, Any]) -> dict[str, Any]:
    source = _exact_fields(
        plan,
        required={"sources", "io_root"},
        field="soundbank_plan",
    )
    rows: list[dict[str, str]] = []
    for index, raw in enumerate(
        _bounded_sequence(source["sources"], field="sources", maximum=32)
    ):
        row = _exact_fields(
            _mapping(raw, field=f"sources[{index}]"),
            required={"input", "platform", "output"},
            field=f"sources[{index}]",
        )
        rows.append(
            {
                name: _text(row[name], field=f"sources[{index}].{name}")
                for name in ("input", "platform", "output")
            }
        )
    return {
        "sources": rows,
        "io_root": _text(source["io_root"], field="io_root"),
    }


def _materialize_definition_files(plan: Mapping[str, Any]) -> dict[str, Any]:
    source = _exact_fields(
        plan,
        required={"files", "io_root"},
        field="soundbank_plan",
    )
    files = [
        _text(value, field="files")
        for value in _bounded_sequence(
            source["files"],
            field="files",
            maximum=32,
        )
    ]
    return {
        "files": files,
        "io_root": _text(source["io_root"], field="io_root"),
    }


def materialize_soundbank_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    """Compile one complete SoundBank business plan without native ingress."""

    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    version = session.context.wwise_version
    soundbank_business_contract_data(operation, version)
    if session.declarations:
        _error(
            "DECLARATION_FORM_INVALID",
            "declarations",
            "submit the complete target-free SoundBank plan once",
        )
    settings = _exact_fields(
        session.settings,
        required={"soundbank_plan"},
        field="settings",
    )
    plan = _mapping(settings["soundbank_plan"], field="soundbank_plan")
    if operation == "soundbank.generate":
        arguments = _materialize_generate(session, plan)
    elif operation == "soundbank.setInclusions":
        arguments = _materialize_inclusions(session, plan)
    elif operation == "soundbank.convertExternalSources":
        arguments = _materialize_external_sources(plan)
    elif operation == "soundbank.processDefinitionFiles":
        arguments = _materialize_definition_files(plan)
    else:  # pragma: no cover - contract validates operation
        raise AssertionError("unsupported SoundBank business operation")

    from .operation_registry import parse_operation_request

    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": version,
            "operation": operation,
            "arguments": arguments,
        },
        expected_version=version,
    ).as_dict()


__all__ = ["materialize_soundbank_business_request"]
