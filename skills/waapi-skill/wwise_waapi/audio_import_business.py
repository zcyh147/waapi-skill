"""Deep ``audio.import`` Adapter from Business Declarations to canonical WAAPI."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .business_declaration_state import (
    BusinessDeclaration,
    BusinessDeclarationSession,
)
from .business_declarations import (
    BusinessDeclarationError,
    ExistingObjectTarget,
    NewDescendantTarget,
    business_repair,
    repair_at_draft_revision,
    resolve_semantic_kind,
)
from .business_planning import (
    BuildContinuation,
    BusinessBatch,
    BusinessEffect,
    BusinessFileEvidence,
    BusinessPlanningDeadline,
    CompiledBusinessPlan,
    compile_business_plan,
    plan_business_request,
)
from .audio_import_business_contracts import (
    AUDIO_IMPORT_BUSINESS_DECLARATION_FIELDS,
    AUDIO_IMPORT_BUSINESS_MODES,
    AUDIO_IMPORT_BUSINESS_SETTING_FIELDS,
    AUDIO_IMPORT_EVENT_ACTIONS,
)
from .operation_import import (
    ImportContractError,
    canonical_import_target,
    normalize_inline_audio_file,
    normalize_originals_subfolder,
)


_SETTING_FIELDS = frozenset(AUDIO_IMPORT_BUSINESS_SETTING_FIELDS)
_DECLARATION_FIELDS = frozenset(AUDIO_IMPORT_BUSINESS_DECLARATION_FIELDS)
_MODE_TO_NATIVE = AUDIO_IMPORT_BUSINESS_MODES
_EVENT_ACTIONS = frozenset(AUDIO_IMPORT_EVENT_ACTIONS)


@dataclass(frozen=True, slots=True)
class _ObjectIdentity:
    path: str
    name: str
    object_type: str
    object_id: str | None
    declaration_id: str | None = None


def compile_audio_import_business(
    session: BusinessDeclarationSession,
    *,
    build_continuation: BuildContinuation,
    clock: Callable[[], float] = time.monotonic,
) -> CompiledBusinessPlan:
    """Compile one complete business revision into canonical ``audio.import``."""

    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    effects, materialize, file_evidence = _audio_import_plan_inputs(
        session,
        collect_file_evidence=True,
    )
    return compile_business_plan(
        session,
        operation="audio.import",
        effects=effects,
        materialize=materialize,
        build_continuation=build_continuation,
        file_evidence=file_evidence,
        clock=clock,
    )


def _audio_import_plan_inputs(
    session: BusinessDeclarationSession,
    *,
    collect_file_evidence: bool,
) -> tuple[
    tuple[BusinessEffect, ...],
    Callable[[Sequence[BusinessBatch], BusinessPlanningDeadline], Mapping[str, Any]],
    tuple[BusinessFileEvidence, ...],
]:
    settings = _normalize_settings(session)
    mode = _resolve_mode(session, settings.get("mode"))
    default_fields = settings.get("defaults", {})
    assert isinstance(default_fields, Mapping)
    effects: list[BusinessEffect] = []
    file_evidence: list[BusinessFileEvidence] = []
    planned = {
        row.result_handle: row
        for row in session.declarations
        if isinstance(row.target, NewDescendantTarget)
    }
    identity_cache: dict[str, _ObjectIdentity] = {}
    for declaration in session.declarations:
        effect, evidence = _compile_declaration(
            session,
            declaration,
            default_fields=default_fields,
            planned=planned,
            identity_cache=identity_cache,
            collect_file_evidence=collect_file_evidence,
        )
        effects.append(effect)
        if evidence is not None:
            file_evidence.append(evidence)

    request_options: dict[str, Any] = {}
    native_mode = _MODE_TO_NATIVE[mode]
    if native_mode != "createNew":
        request_options["import_operation"] = native_mode
    if settings.get("add_to_source_control") is True:
        request_options["auto_add_to_source_control"] = True
    if "check_out_from_source_control" in settings:
        if session.context.wwise_version not in {"2023.1", "2024.1", "2025.1"}:
            raise _repair(
                session,
                "VERSION_BEHAVIOR_BOUNDARY",
                field="check_out_from_source_control",
                choices=("2023.1", "2024.1", "2025.1"),
                action="omit this setting on Wwise 2021.1 and 2022.1",
            )
        request_options["auto_check_out_to_source_control"] = settings[
            "check_out_from_source_control"
        ]

    def materialize(
        batches: Sequence[BusinessBatch],
        deadline: BusinessPlanningDeadline,
    ) -> Mapping[str, Any]:
        deadline.checkpoint()
        rows = [
            dict(fragment)
            for batch in batches
            for fragment in batch.native_fragments
        ]
        deadline.checkpoint()
        return {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "audio.import",
            "arguments": {"imports": rows, **request_options},
        }

    return tuple(effects), materialize, tuple(file_evidence)


def materialize_audio_import_business_request(
    session: BusinessDeclarationSession,
    *,
    allow_cleaned_file_evidence: bool = False,
) -> Mapping[str, Any]:
    """Return the canonical request without inventing a public continuation."""

    if not isinstance(allow_cleaned_file_evidence, bool):
        raise TypeError("allow_cleaned_file_evidence must be a boolean")
    effects, materialize, file_evidence = _audio_import_plan_inputs(
        session,
        collect_file_evidence=not allow_cleaned_file_evidence,
    )
    return plan_business_request(
        session,
        operation="audio.import",
        effects=effects,
        materialize=materialize,
        file_evidence=file_evidence,
        verify_file_evidence=not allow_cleaned_file_evidence,
    ).request


def validate_audio_import_replacement_scope(
    session: BusinessDeclarationSession,
    compiled: CompiledBusinessPlan,
    prepared: Mapping[str, Any],
) -> None:
    """Bind replace permission to declared existing targets, never new collisions.

    The successful Draft check seals this exact prepared snapshot; Preview and
    execution retain their existing digest and prewrite drift checks.
    """

    if compiled.request["arguments"].get("import_operation") != "replaceExisting":
        return
    targets = prepared.get("verification_plan", {}).get("targets", [])
    by_path = {row["canonical_target_path"].casefold(): row for row in targets}
    declarations = {f"import:{row.declaration_id}": row for row in session.declarations}
    if len(by_path) != len(targets) or len(targets) != len(declarations):
        raise _repair(session, "AUDIO_IMPORT_SCOPE_INVALID", field="targets",
            action="prepare every declared import target exactly once")
    for effect_id, expectation in zip(compiled.ordered_effect_ids, compiled.verifier_expectations, strict=True):
        declaration = declarations[effect_id]
        path = canonical_import_target(expectation["object_path"], version=session.context.wwise_version)["canonical_target_path"]
        target = by_path.pop(path.casefold(), None)
        if target is None:
            raise _repair(session, "AUDIO_IMPORT_SCOPE_INVALID", field="targets",
                action="prepare the exact declared import targets")
        if isinstance(declaration.target, NewDescendantTarget):
            if target.get("pre_state_rows") or target.get("preexisting_id") is not None:
                raise _repair(session, "NEW_IMPORT_TARGET_EXISTS", field="target", path=path,
                    action="keep the new target absent or bind it explicitly before requesting replacement")
        else:
            expected_id = session.handles.resolve_object(declaration.target.object_handle).object_id
            if str(target.get("preexisting_id")).upper() != expected_id.upper():
                raise _repair(session, "EXISTING_IMPORT_TARGET_CHANGED", field="target", path=path,
                    action="bind the exact existing replacement target again before preparing a new Preview")


def _normalize_settings(session: BusinessDeclarationSession) -> dict[str, Any]:
    unknown = sorted(set(session.settings) - _SETTING_FIELDS)
    if unknown:
        raise _repair(
            session,
            "AUDIO_IMPORT_SETTING_UNAVAILABLE",
            field="settings",
            choices=sorted(_SETTING_FIELDS),
            action="use one disclosed audio import batch setting",
        )
    settings = dict(session.settings)
    mode = settings.get("mode")
    if mode is not None and mode not in _MODE_TO_NATIVE:
        raise _repair(
            session,
            "AUDIO_IMPORT_MODE_UNAVAILABLE",
            field="mode",
            choices=sorted(_MODE_TO_NATIVE),
            action="choose create, reimport, or explicit replace",
        )
    for name in ("add_to_source_control", "check_out_from_source_control"):
        if name in settings and type(settings[name]) is not bool:
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field=name,
                expected_type="boolean",
                action="provide a JSON boolean or omit the setting",
            )
    defaults = settings.get("defaults", {})
    if not isinstance(defaults, Mapping):
        raise _repair(
            session,
            "AUDIO_IMPORT_DEFAULTS_INVALID",
            field="defaults",
            action="provide one object of explicit batch-wide business values",
        )
    unknown_defaults = sorted(set(defaults) - _DECLARATION_FIELDS)
    if unknown_defaults:
        raise _repair(
            session,
            "AUDIO_IMPORT_FIELD_UNAVAILABLE",
            field="defaults",
            choices=sorted(_DECLARATION_FIELDS),
            action="use disclosed business fields or live Field Handles",
        )
    settings["defaults"] = dict(defaults)
    return settings


def _resolve_mode(
    session: BusinessDeclarationSession,
    explicit_mode: Any,
) -> str:
    if not session.declarations:
        raise _repair(
            session,
            "BUSINESS_DECLARATION_INCOMPLETE",
            field="declarations",
            missing_fields=("audio_import_declaration",),
            action="declare at least one import target before Preview",
        )
    forms = {
        "new" if isinstance(row.target, NewDescendantTarget) else "existing"
        for row in session.declarations
    }
    if explicit_mode is None:
        if forms == {"new"}:
            return "create"
        if forms in ({"existing"}, {"new", "existing"}):
            return "reimport"
        raise _repair(
            session,
            "AUDIO_IMPORT_MODE_AMBIGUOUS",
            field="mode",
            choices=("create", "reimport", "replace"),
            action="state the one intended batch mode for mixed target forms",
        )
    assert isinstance(explicit_mode, str)
    if explicit_mode == "create" and forms != {"new"}:
        raise _mode_target_mismatch(session, explicit_mode, forms)
    return explicit_mode


def _mode_target_mismatch(
    session: BusinessDeclarationSession,
    mode: str,
    forms: set[str],
) -> BusinessDeclarationError:
    return _repair(
        session,
        "AUDIO_IMPORT_MODE_TARGET_MISMATCH",
        field="mode",
        target_forms=sorted(forms),
        action=f"use target forms compatible with explicit {mode} mode",
    )


def _compile_declaration(
    session: BusinessDeclarationSession,
    declaration: BusinessDeclaration,
    *,
    default_fields: Mapping[str, Any],
    planned: Mapping[str, BusinessDeclaration],
    identity_cache: dict[str, _ObjectIdentity],
    collect_file_evidence: bool,
) -> tuple[BusinessEffect, BusinessFileEvidence | None]:
    fields = {**dict(default_fields), **dict(declaration.fields)}
    default_values = default_fields.get("field_values")
    row_values = declaration.fields.get("field_values")
    if isinstance(default_values, Mapping) and isinstance(row_values, Mapping):
        # Rediscovery can issue another handle for the exact same bound field.
        # Only identical scope/metadata bindings share native-default precedence.
        row_bindings = {
            session.handles.bound_field(handle).binding_digest for handle in row_values
        }
        fields["field_values"] = {
            **{
                handle: value for handle, value in default_values.items()
                if session.handles.bound_field(handle).binding_digest not in row_bindings
            },
            **row_values,
        }
    unknown = sorted(set(fields) - _DECLARATION_FIELDS)
    if unknown:
        raise _repair(
            session,
            "AUDIO_IMPORT_FIELD_UNAVAILABLE",
            field="fields",
            choices=sorted(_DECLARATION_FIELDS),
            action="use disclosed business fields or live Field Handles",
        )
    target = declaration.target
    dependencies: tuple[str, ...] = ()
    semantic_kind_name: str | None = None
    if isinstance(target, NewDescendantTarget):
        parent = _resolve_identity(
            session,
            target.parent_handle,
            planned=planned,
            identity_cache=identity_cache,
        )
        if parent.declaration_id is not None:
            dependencies = (f"import:{parent.declaration_id}",)
        kind = resolve_semantic_kind(
            target.kind,
            version=session.context.wwise_version,
        )
        semantic_kind_name = kind.name
        object_path = f"{parent.path}\\<{kind.path_segment_type}>{target.name}"
        object_type = kind.native_object_type
        object_name = target.name
        identity_cache[declaration.result_handle] = _ObjectIdentity(
            path=object_path,
            name=object_name,
            object_type=object_type,
            object_id=None,
            declaration_id=declaration.declaration_id,
        )
    elif isinstance(target, ExistingObjectTarget):
        existing = _resolve_object(session, target.object_handle)
        language = fields.get("language")
        object_path = existing.path
        object_name = existing.name
        if _type_token(existing.object_type) in {"sound", "soundsfx", "soundvoice"}:
            live_kind = existing.semantic_kind
            if live_kind is None:
                live_kind = {
                    "soundsfx": "sound-sfx",
                    "soundvoice": "sound-voice",
                }.get(_type_token(existing.object_type))
            declared_kind = (
                None
                if not isinstance(language, str)
                else ("sound-sfx" if language.casefold() == "sfx" else "sound-voice")
            )
            if live_kind is not None and declared_kind not in {None, live_kind}:
                raise _repair(
                    session,
                    "EXISTING_SOUND_KIND_MISMATCH",
                    field="language",
                    choices=("SFX",) if live_kind == "sound-sfx" else ("project language",),
                    action="use a language that matches the exact bound Sound kind",
                )
            kind_name = live_kind or declared_kind
            semantic_kind_name = kind_name
            if kind_name is None:
                object_type = existing.object_type
                metadata_type = "Sound"
                readable_type = "Sound (exact existing kind unresolved)"
            else:
                kind = resolve_semantic_kind(
                    kind_name,
                    version=session.context.wwise_version,
                )
                object_type = kind.native_object_type
                metadata_type = kind.metadata_object_type
                readable_type = kind.path_segment_type
        else:
            object_type = existing.object_type
            metadata_type = existing.object_type
            readable_type = existing.object_type
    else:  # pragma: no cover - closed dataclass union
        raise RuntimeError("unsupported business target")

    row: dict[str, Any] = {
        "object_path": object_path,
        "object_type": object_type,
    }
    media_file = fields.get("media_file")
    inline_wav = fields.get("inline_wav")
    if media_file is not None and inline_wav is not None:
        raise _repair(
            session,
            "AUDIO_IMPORT_MEDIA_CONFLICT",
            field="media",
            action="provide one regular file or one inline WAV, never both",
        )
    evidence: BusinessFileEvidence | None = None
    if media_file is not None:
        if not isinstance(media_file, str):
            raise _field_type_repair(session, "media_file", "absolute regular file")
        if collect_file_evidence:
            try:
                evidence = BusinessFileEvidence.from_path(media_file)
            except (ImportContractError, OSError, ValueError) as exc:
                raise _repair(
                    session,
                    "MEDIA_FILE_UNAVAILABLE",
                    field="media_file",
                    action="provide one available absolute regular media file",
                ) from exc
            row["audio_file"] = evidence.path
        else:
            row["audio_file"] = media_file
    elif inline_wav is not None:
        try:
            normalized_inline, _proof = normalize_inline_audio_file(
                inline_wav,
                field="inline_wav",
            )
        except ImportContractError as exc:
            raise _repair(
                session,
                exc.error_code,
                field="inline_wav",
                action="provide one complete bounded canonical inline WAV artifact",
            ) from exc
        row["audio_file_base64"] = normalized_inline

    has_media = media_file is not None or inline_wav is not None
    language = fields.get("language")
    if has_media:
        if language is None and (
            semantic_kind_name == "sound-sfx"
            or _type_token(object_type) == "musictrack"
        ):
            language = "SFX"
        if not isinstance(language, str) or not language.strip():
            raise _repair(
                session,
                "REQUIRED_FIELD_MISSING",
                field="language",
                missing_fields=("language",),
                action="provide the exact Project language or SFX",
            )
        row["import_language"] = language.strip()
    elif language is not None:
        raise _repair(
            session,
            "AUDIO_IMPORT_LANGUAGE_WITHOUT_MEDIA",
            field="language",
            action="omit language on a structure-only declaration",
        )

    for business_name, native_name in (
        ("notes", "notes"),
        ("audio_source_notes", "audio_source_notes"),
        ("switch_value", "switch_assignment"),
    ):
        value = fields.get(business_name)
        if value is not None:
            allows_empty = business_name in {"notes", "audio_source_notes"}
            if not isinstance(value, str) or (not value and not allows_empty):
                raise _field_type_repair(
                    session, business_name, "string" if allows_empty else "non-empty string"
                )
            row[native_name] = value
    if "originals_subfolder" in fields:
        try:
            row["originals_subfolder"] = normalize_originals_subfolder(
                fields["originals_subfolder"],
                field="originals_subfolder",
            )
        except ImportContractError as exc:
            raise _repair(
                session,
                exc.error_code,
                field="originals_subfolder",
                action="provide one safe relative Originals subfolder",
            ) from exc

    properties: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    if fields.get("loop") is not None:
        if fields["loop"] != "infinite":
            raise _repair(
                session,
                "FIELD_VALUE_UNAVAILABLE",
                field="loop",
                choices=("infinite",),
                action="choose infinite or omit looping",
            )
        properties.extend(
            (
                {"name": "IsLoopingEnabled", "value": True},
                {"name": "IsLoopingInfinite", "value": True},
            )
        )
    if "volume_db" in fields:
        volume = fields["volume_db"]
        if (
            isinstance(volume, bool)
            or not isinstance(volume, (int, float))
            or not -200.0 <= float(volume) <= 200.0
        ):
            raise _repair(
                session,
                "FIELD_VALUE_OUT_OF_RANGE",
                field="volume_db",
                valid_range={"minimum": -200.0, "maximum": 200.0},
                action="provide a finite value in decibels",
            )
        properties.append({"name": "Volume", "value": float(volume)})
    if "max_instances" in fields:
        maximum = fields["max_instances"]
        if (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or not 1 <= maximum <= 1_000_000
        ):
            raise _repair(
                session,
                "FIELD_VALUE_OUT_OF_RANGE",
                field="max_instances",
                valid_range={"minimum": 1, "maximum": 1_000_000},
                action="provide a positive bounded instance count",
            )
        properties.extend(
            (
                {"name": "UseMaxSoundPerInstance", "value": True},
                {"name": "MaxSoundPerInstance", "value": maximum},
            )
        )
    if "ignore_parent_instance_limit" in fields:
        override_parent = fields["ignore_parent_instance_limit"]
        if type(override_parent) is not bool:
            raise _field_type_repair(
                session,
                "ignore_parent_instance_limit",
                "boolean",
            )
        properties.append(
            {"name": "IgnoreParentMaxSoundInstance", "value": override_parent}
        )
    if "output_bus" in fields:
        bus = _resolve_object(session, fields["output_bus"])
        if _type_token(bus.object_type) not in {"bus", "audiobus", "auxbus", "auxiliarybus"}:
            raise _repair(
                session,
                "REFERENCE_TARGET_TYPE_MISMATCH",
                field="output_bus",
                allowed_target_types=("Bus", "AuxBus"),
                action="choose an exact bound output bus",
            )
        references.append(
            {
                "name": "OutputBus",
                "target": {"kind": "id", "value": bus.object_id},
            }
        )
    _append_dynamic_fields(
        session,
        fields.get("field_values"),
        metadata_type=(
            kind.metadata_object_type
            if isinstance(target, NewDescendantTarget)
            else metadata_type
        ),
        target_object_id=(
            None
            if isinstance(target, NewDescendantTarget)
            else existing.object_id
        ),
        properties=properties,
        references=references,
    )
    if properties:
        row["properties"] = properties
    if references:
        row["references"] = references
    if "event" in fields:
        row["event"] = _compile_event(session, fields["event"])

    if "dialogue_event" in fields:
        row["dialogue_event"] = _compile_dialogue_event(session, fields["dialogue_event"])

    readable = [
        f"对象：{object_name}",
        f"类型：{kind.path_segment_type if isinstance(target, NewDescendantTarget) else readable_type}",
    ]
    if "volume_db" in fields:
        readable.append(f"音量：{float(fields['volume_db']):g} dB")
    if fields.get("loop") == "infinite":
        readable.append("循环方式：Infinite")
    if fields.get("ignore_parent_instance_limit") is True:
        readable.append("实例上限来源：此对象（忽略父级）")
    if "output_bus" in fields:
        readable.append(f"输出总线：{_resolve_object(session, fields['output_bus']).name}")
    if has_media:
        readable.append(f"语言：{row['import_language']}")
    return (
        BusinessEffect.create(
            effect_id=f"import:{declaration.declaration_id}",
            declaration_id=declaration.declaration_id,
            depends_on=dependencies,
            batch_key="audio.import",
            native_fragment=row,
            verifier_expectation={
                "object_path": object_path,
                "object_type": object_type,
                "business_fields": sorted(fields),
            },
            readable_lines=tuple(readable),
        ),
        evidence,
    )


def _append_dynamic_fields(
    session: BusinessDeclarationSession,
    value: Any,
    *,
    metadata_type: str,
    target_object_id: str | None,
    properties: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise _field_type_repair(session, "field_values", "field-handle object")
    used_tokens = {row["name"] for row in (*properties, *references)}
    for handle, raw_value in value.items():
        if not isinstance(handle, str):
            raise _field_type_repair(session, "field_values", "field-handle object")
        try:
            field = session.handles.bound_field(handle)
            normalized_value = session.handles.validate_field_value(field, raw_value)
        except BusinessDeclarationError as exc:
            raise repair_at_draft_revision(exc, draft_revision=session.revision) from exc
        class_scope_mismatch = (
            field.scope_kind == "class"
            and isinstance(field.scope_value, str)
            and _type_token(field.scope_value) != _type_token(metadata_type)
        )
        object_scope_mismatch = field.scope_kind == "object" and (
            target_object_id is None
            or str(field.scope_value).upper() != target_object_id.upper()
        )
        if class_scope_mismatch or object_scope_mismatch:
            raise _repair(
                session,
                "FIELD_HANDLE_SCOPE_MISMATCH",
                field="field_values",
                action="discover the field for the declared semantic kind",
            )
        if field.token in used_tokens:
            raise _repair(
                session,
                "AUDIO_IMPORT_FIELD_CONFLICT",
                field=field.token,
                action="provide each business field exactly once",
            )
        used_tokens.add(field.token)
        if field.field_kind == "property":
            properties.append({"name": field.token, "value": normalized_value})
        else:
            target = _resolve_object(session, normalized_value)
            references.append(
                {
                    "name": field.token,
                    "target": {"kind": "id", "value": target.object_id},
                }
            )


def _compile_dialogue_event(session: BusinessDeclarationSession, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"parent_handle", "name", "conditions", "probability", "weight"} or not {"parent_handle", "name"} <= set(value):
        raise _field_type_repair(session, "dialogue_event", "parent_handle and exact child name object")
    parent = _resolve_object(session, value["parent_handle"])
    name = value["name"]
    if (parent.object_type not in {"WorkUnit", "Folder"} or not parent.path.startswith("\\Dynamic Dialogue\\")
            or not isinstance(name, str) or not name or name != name.strip() or len(name) > 255
            or any(c in name for c in "\\/<>:@|\r\n\t\x00")):
        raise _repair(session, "AUDIO_IMPORT_DIALOGUE_EVENT_INVALID", field="dialogue_event",
            action="provide an exact Dynamic Dialogue folder/Work Unit handle and one child name without directive grammar")
    result = {"path": f"{parent.path}\\{name}"}
    if "conditions" in value:
        conditions = value["conditions"]
        if not isinstance(conditions, list) or not 1 <= len(conditions) <= 32:
            raise _field_type_repair(session, "dialogue_event", "one to 32 ordered group/value conditions")
        result["conditions"] = []
        for condition in conditions:
            if not isinstance(condition, Mapping) or set(condition) != {"group_handle", "value_handle"}:
                raise _field_type_repair(session, "dialogue_event", "group_handle/value_handle conditions")
            group = _resolve_object(session, condition["group_handle"])
            selected = condition["value_handle"]
            result["conditions"].append({"group": {"kind":"id", "value":group.object_id},
                "value": "*" if selected == "*" else {"kind":"id", "value":_resolve_object(session, selected).object_id}})
    for key in ("probability", "weight"):
        if key in value: result[key] = value[key]
    return result


def _compile_event(
    session: BusinessDeclarationSession,
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {
        "parent_handle",
        "name",
        "action",
    }:
        raise _field_type_repair(
            session,
            "event",
            "parent_handle, name, and optional action object",
        )
    parent_handle = value.get("parent_handle")
    name = value.get("name")
    action = value.get("action", "Play")
    parent = _resolve_object(session, parent_handle)
    if (
        not isinstance(name, str)
        or not name
        or any(character in name for character in "\\<>")
        or action not in _EVENT_ACTIONS
        or not parent.path.startswith("\\Events\\")
    ):
        raise _repair(
            session,
            "AUDIO_IMPORT_EVENT_INVALID",
            field="event",
            choices=sorted(_EVENT_ACTIONS),
            action="provide an Event parent handle, child name, and valid action",
        )
    return {"path": f"{parent.path}\\{name}", "action": action}


def _resolve_object(session: BusinessDeclarationSession, handle: Any):
    try:
        return session.handles.resolve_object(handle)
    except BusinessDeclarationError as exc:
        raise repair_at_draft_revision(exc, draft_revision=session.revision) from exc


def _resolve_identity(
    session: BusinessDeclarationSession,
    handle: Any,
    *,
    planned: Mapping[str, BusinessDeclaration],
    identity_cache: dict[str, _ObjectIdentity],
) -> _ObjectIdentity:
    if isinstance(handle, str) and handle in identity_cache:
        return identity_cache[handle]
    if isinstance(handle, str) and handle in planned:
        declaration = planned[handle]
        target = declaration.target
        assert isinstance(target, NewDescendantTarget)
        parent = _resolve_identity(
            session,
            target.parent_handle,
            planned=planned,
            identity_cache=identity_cache,
        )
        kind = resolve_semantic_kind(
            target.kind,
            version=session.context.wwise_version,
        )
        identity = _ObjectIdentity(
            path=f"{parent.path}\\<{kind.path_segment_type}>{target.name}",
            name=target.name,
            object_type=kind.native_object_type,
            object_id=None,
            declaration_id=declaration.declaration_id,
        )
        identity_cache[handle] = identity
        return identity
    bound = _resolve_object(session, handle)
    return _ObjectIdentity(
        path=bound.path,
        name=bound.name,
        object_type=bound.object_type,
        object_id=bound.object_id,
    )


def _field_type_repair(
    session: BusinessDeclarationSession,
    field: str,
    expected: str,
) -> BusinessDeclarationError:
    return _repair(
        session,
        "FIELD_VALUE_TYPE_MISMATCH",
        field=field,
        expected_type=expected,
        action="provide the disclosed business value type",
    )


def _repair(
    session: BusinessDeclarationSession,
    error_code: str,
    *,
    field: str,
    action: str,
    **details: Any,
) -> BusinessDeclarationError:
    return business_repair(
        error_code,
        field=field,
        draft_revision=session.revision,
        action=action,
        **details,
    )


def _type_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


__all__ = [
    "compile_audio_import_business",
    "materialize_audio_import_business_request",
    "validate_audio_import_replacement_scope",
]
