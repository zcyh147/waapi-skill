"""Non-public deep-interface MVP for ``audio.import``.

This module is deliberately test-only.  It proves the proposed ownership seam
without cutting over the packaged Skill: model-authored business declarations
enter here, while exact Wwise types, paths, metadata scopes, dynamic fields,
native row expansion, and the continuation remain compiler-owned.
"""

from __future__ import annotations

import hashlib
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.operation_import import build_audio_import_plan
from wwise_waapi.operation_registry import (
    ReadCall,
    _materialize_audio_import_dynamic_rows,
    parse_operation_request,
)
from wwise_waapi.platform_commands import (
    GATEWAY_SHELL_TOOL_TIMEOUT_MS,
    WINDOWS_MODEL_COMMAND_FAMILY,
    WINDOWS_POWERSHELL_ENCODED_FAMILY,
    encode_windows_model_argv,
    encode_windows_powershell_argv,
)
from wwise_waapi.transaction_runtime import (
    TransactionArtifact,
    build_transaction_preview_artifact,
)


MVP_CONTRACT = "waapi-skill.audio-import-business-mvp/v1"
_KIND_MAP: Mapping[str, Mapping[str, str]] = {
    "sound-sfx": {
        "path_type": "Sound SFX",
        "wire_type": "Sound SFX",
        "metadata_type": "Sound",
    },
    "sound-voice": {
        "path_type": "Sound Voice",
        "wire_type": "Sound Voice",
        "metadata_type": "Sound",
    },
    "actor-mixer": {
        "path_type": "Actor-Mixer",
        "wire_type": "ActorMixer",
        "metadata_type": "ActorMixer",
    },
    "random-container": {
        "path_type": "Random Container",
        "wire_type": "RandomSequenceContainer",
        "metadata_type": "RandomSequenceContainer",
    },
}
_MODEL_ASSET_FIELDS = (
    "parent",
    "name",
    "kind",
    "media_file",
    "language",
    "volume_db",
    "loop",
    "output_bus",
    "switch_value",
)


@dataclass(frozen=True, slots=True)
class BoundObject:
    handle: str
    object_id: str | None
    name: str
    object_type: str
    path: str


@dataclass(frozen=True, slots=True)
class BoundField:
    handle: str
    metadata_scope: str
    name: str
    field_kind: str
    value_type: str
    minimum: float | None
    maximum: float | None
    metadata_digest: str
    allowed_target_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssetDeclaration:
    parent: str | None
    target: str | None
    name: str
    kind: str
    media_file: str
    language: str
    volume_db: float | None
    loop: str | None
    output_bus: str | None
    switch_value: str | None
    fields: Mapping[str, Any]
    fields_supplied: bool
    import_operation: str


@dataclass(frozen=True, slots=True)
class StructureDeclaration:
    parent: str
    handle: str
    name: str
    kind: str


class MvpRepairError(ValueError):
    """A business declaration failed without changing the MVP Draft."""

    def __init__(self, repair: Mapping[str, Any]) -> None:
        self.repair = dict(repair)
        super().__init__(str(self.repair.get("error_code", "MVP_REPAIR")))


@dataclass(frozen=True, slots=True)
class DeclarationResult:
    draft: "ImportBusinessMvp"
    handle: str


@dataclass(frozen=True, slots=True)
class MvpCompilation:
    request: Mapping[str, Any]
    metadata_scopes: tuple[str, ...]
    native_rows: tuple[Mapping[str, Any], ...]
    native_row_mapping: tuple[Mapping[str, Any], ...]
    next_command: Mapping[str, Any]
    model_authored_fields: tuple[str, ...]
    native_call_count: int


@dataclass(slots=True)
class ImportBusinessMvp:
    version: str
    task_authority: str
    project_id: str
    _objects: dict[str, BoundObject] = field(default_factory=dict)
    _fields: dict[str, BoundField] = field(default_factory=dict)
    _structures: tuple[StructureDeclaration, ...] = ()
    _assets: tuple[AssetDeclaration, ...] = ()
    _revision: int = 0

    @classmethod
    def create(
        cls,
        *,
        version: str,
        task_authority: str,
        project_id: str,
    ) -> "ImportBusinessMvp":
        if version not in {"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"}:
            raise ValueError("unsupported MVP Wwise version")
        if not task_authority or not project_id:
            raise ValueError("MVP task and project authority are required")
        return cls(
            version=version,
            task_authority=task_authority,
            project_id=project_id,
        )

    def bind_object(
        self,
        *,
        object_id: str,
        name: str,
        object_type: str,
        path: str,
    ) -> str:
        if not object_id or not name or not object_type or not path.startswith("\\"):
            raise ValueError("bound MVP objects require exact live identity evidence")
        handle = _opaque_handle(
            "obj",
            self.task_authority,
            self.project_id,
            self.version,
            object_id,
            path,
        )
        self._objects[handle] = BoundObject(
            handle=handle,
            object_id=object_id,
            name=name,
            object_type=object_type,
            path=path.rstrip("\\"),
        )
        return handle

    def bind_field(
        self,
        *,
        metadata_scope: str,
        name: str,
        field_kind: str,
        value_type: str,
        metadata_digest: str,
        minimum: float | int | None = None,
        maximum: float | int | None = None,
        allowed_target_types: tuple[str, ...] = (),
    ) -> str:
        normalized_target_types = tuple(str(value) for value in allowed_target_types)
        if (
            not metadata_scope
            or not name
            or field_kind not in {"property", "reference"}
            or value_type not in {"number", "integer", "boolean", "string", "reference"}
            or not metadata_digest
            or (field_kind == "reference") != (value_type == "reference")
            or (field_kind == "reference" and not normalized_target_types)
            or (field_kind == "property" and normalized_target_types)
            or any(not value or value != value.strip() for value in normalized_target_types)
        ):
            raise ValueError("field binding requires complete live metadata")
        lower = _finite_number(minimum, field_name="minimum")
        upper = _finite_number(maximum, field_name="maximum")
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("field metadata range is inverted")
        handle = _opaque_handle(
            "field",
            self.task_authority,
            self.project_id,
            self.version,
            metadata_scope,
            name,
            field_kind,
            value_type,
            metadata_digest,
            *normalized_target_types,
        )
        self._fields[handle] = BoundField(
            handle=handle,
            metadata_scope=metadata_scope,
            name=name,
            field_kind=field_kind,
            value_type=value_type,
            minimum=lower,
            maximum=upper,
            metadata_digest=metadata_digest,
            allowed_target_types=normalized_target_types,
        )
        return handle

    def declare_structure(
        self,
        *,
        parent: str,
        name: str,
        kind: str,
    ) -> DeclarationResult:
        parent_object = self._objects.get(parent)
        if parent_object is None:
            raise self._repair(
                "PARENT_HANDLE_STALE_OR_OUT_OF_SCOPE",
                field="parent",
                rejected_handle=parent,
                action="resolve the parent in this task and resubmit its handle",
            )
        if kind not in {"actor-mixer", "random-container"}:
            raise self._repair(
                "STRUCTURE_KIND_UNAVAILABLE",
                field="kind",
                action="choose actor-mixer or random-container",
            )
        self._require_child_name(name)
        kind_mapping = _KIND_MAP[kind]
        path = f"{parent_object.path}\\<{kind_mapping['path_type']}>{name}"
        handle = _opaque_handle(
            "new",
            self.task_authority,
            self.project_id,
            self.version,
            str(self._revision + 1),
            path,
        )
        declaration = StructureDeclaration(
            parent=parent,
            handle=handle,
            name=name,
            kind=kind,
        )
        self._structures = (*self._structures, declaration)
        self._objects[handle] = BoundObject(
            handle=handle,
            object_id=None,
            name=name,
            object_type=kind_mapping["wire_type"],
            path=path,
        )
        self._revision += 1
        return DeclarationResult(draft=self, handle=handle)

    def declare_asset(
        self,
        *,
        parent: str,
        name: str,
        kind: str,
        media_file: str | Path,
        language: str,
        volume_db: float | int | None = None,
        loop: str | None = None,
        output_bus: str | None = None,
        switch_value: str | None = None,
        fields: Mapping[str, Any] | None = None,
    ) -> DeclarationResult:
        if parent not in self._objects:
            raise self._repair(
                "PARENT_HANDLE_STALE_OR_OUT_OF_SCOPE",
                field="parent",
                rejected_handle=parent,
                action="resolve the parent in this task and resubmit its handle",
            )
        if output_bus is not None and output_bus not in self._objects:
            raise self._repair(
                "OBJECT_HANDLE_STALE_OR_OUT_OF_SCOPE",
                field="output_bus",
                rejected_handle=output_bus,
                action="resolve the output bus in this task and resubmit its handle",
            )
        if kind not in _KIND_MAP:
            raise self._repair(
                "BUSINESS_KIND_UNAVAILABLE",
                field="kind",
                action="choose a disclosed business kind",
            )
        self._require_child_name(name)
        if fields is not None and not isinstance(fields, Mapping):
            raise self._repair(
                "FIELD_BINDINGS_INVALID",
                field="fields",
                action="resubmit field handles and values as one object",
            )
        normalized_fields: dict[str, Any] = {}
        for handle, value in dict(fields or {}).items():
            binding = self._fields.get(str(handle))
            if binding is None:
                raise self._repair(
                    "FIELD_HANDLE_STALE_OR_OUT_OF_SCOPE",
                    field="fields",
                    rejected_handle=str(handle),
                    action="discover the field in this task and resubmit its handle",
                )
            expected_scope = _KIND_MAP[kind]["metadata_type"]
            if binding.metadata_scope != expected_scope:
                raise self._repair(
                    "FIELD_HANDLE_SCOPE_MISMATCH",
                    field="fields",
                    rejected_handle=str(handle),
                    action="discover the field for the declared object kind",
                )
            normalized_fields[str(handle)] = self._validate_bound_field_value(
                binding,
                value,
            )
        source = self._require_media_file(media_file)
        try:
            normalized_volume = _finite_number(volume_db, field_name="volume_db")
        except ValueError as exc:
            raise self._repair(
                "FIELD_VALUE_TYPE_MISMATCH",
                field="volume_db",
                action="resubmit volume_db as a finite number of decibels",
            ) from exc
        if normalized_volume is not None and not -200.0 <= normalized_volume <= 200.0:
            raise self._repair(
                "FIELD_VALUE_OUT_OF_RANGE",
                field="volume_db",
                action="resubmit volume_db inside the supported -200..200 dB range",
            )
        normalized_loop = None if loop is None else str(loop).strip().casefold()
        if normalized_loop not in {None, "infinite"}:
            raise self._repair(
                "FIELD_VALUE_UNAVAILABLE",
                field="loop",
                action="use Infinite or omit the looping field",
            )
        if not isinstance(language, str) or not language.strip():
            raise self._repair(
                "REQUIRED_FIELD_MISSING",
                field="language",
                action="resubmit one explicit import language",
            )
        normalized_switch = None
        if switch_value is not None:
            if not isinstance(switch_value, str) or not switch_value.strip():
                raise self._repair(
                    "FIELD_VALUE_TYPE_MISMATCH",
                    field="switch_value",
                    action="resubmit one non-empty Switch or State value name",
                )
            normalized_switch = switch_value.strip()
        declaration = AssetDeclaration(
            parent=parent,
            target=None,
            name=name,
            kind=kind,
            media_file=str(source),
            language=language.strip(),
            volume_db=normalized_volume,
            loop=normalized_loop,
            output_bus=output_bus,
            switch_value=normalized_switch,
            fields=normalized_fields,
            fields_supplied=fields is not None,
            import_operation="createNew",
        )
        # Business declaration application is copy-on-write.  A rejected call
        # above cannot alter the existing declaration tuple.
        self._assets = (*self._assets, declaration)
        self._revision += 1
        handle = _opaque_handle(
            "new",
            self.task_authority,
            self.project_id,
            self.version,
            str(self._revision),
            name,
        )
        return DeclarationResult(draft=self, handle=handle)

    def declare_existing_asset(
        self,
        *,
        target: str,
        media_file: str | Path,
        language: str,
        replace: bool = False,
    ) -> DeclarationResult:
        bound = self._objects.get(target)
        if bound is None or bound.object_id is None:
            raise self._repair(
                "TARGET_HANDLE_STALE_OR_OUT_OF_SCOPE",
                field="target",
                rejected_handle=target,
                action="resolve the existing target in this task and resubmit its handle",
            )
        normalized_type = bound.object_type.casefold().replace(" ", "")
        if normalized_type not in {"sound", "soundsfx", "soundvoice"}:
            raise self._repair(
                "EXISTING_TARGET_KIND_UNSUPPORTED",
                field="target",
                rejected_handle=target,
                action="choose an existing Sound target",
            )
        if not isinstance(language, str) or not language.strip():
            raise self._repair(
                "REQUIRED_FIELD_MISSING",
                field="language",
                action="resubmit one explicit import language",
            )
        normalized_language = language.strip()
        kind = "sound-voice" if normalized_language.casefold() != "sfx" else "sound-sfx"
        source = self._require_media_file(media_file)
        declaration = AssetDeclaration(
            parent=None,
            target=target,
            name=bound.name,
            kind=kind,
            media_file=str(source),
            language=normalized_language,
            volume_db=None,
            loop=None,
            output_bus=None,
            switch_value=None,
            fields={},
            fields_supplied=False,
            import_operation="replaceExisting" if replace else "useExisting",
        )
        self._assets = (*self._assets, declaration)
        self._revision += 1
        handle = _opaque_handle(
            "existing",
            self.task_authority,
            self.project_id,
            self.version,
            str(self._revision),
            target,
        )
        return DeclarationResult(draft=self, handle=handle)

    def inspect(self) -> dict[str, Any]:
        return {
            "contract": MVP_CONTRACT,
            "revision": self._revision,
            "structure_count": len(self._structures),
            "asset_count": len(self._assets),
        }

    def compile(self) -> MvpCompilation:
        if not self._assets:
            raise self._repair(
                "INCOMPLETE_DECLARATION",
                field="assets",
                action="declare at least one complete audio asset before Preview",
            )
        modes = {asset.import_operation for asset in self._assets}
        if self._structures:
            modes.add("createNew")
        if len(modes) != 1:
            raise self._repair(
                "MIXED_IMPORT_MODES_REQUIRE_SEPARATE_PREVIEWS",
                field="target",
                action="submit create, re-import, and replacement batches separately",
            )
        import_operation = next(iter(modes))
        rows: list[dict[str, Any]] = []
        scopes: list[str] = []
        property_specs: list[list[dict[str, Any]]] = []
        reference_specs: list[list[dict[str, Any]]] = []
        for structure in self._structures:
            bound = self._objects[structure.handle]
            kind = _KIND_MAP[structure.kind]
            rows.append(
                {
                    "object_path": bound.path,
                    "object_type": kind["wire_type"],
                }
            )
            scopes.append(
                "PropertyContainer"
                if self.version == "2025.1" and structure.kind == "actor-mixer"
                else kind["metadata_type"]
            )
            property_specs.append([])
            reference_specs.append([])
        for asset in self._assets:
            kind = _KIND_MAP[asset.kind]
            metadata_type = (
                "PropertyContainer"
                if self.version == "2025.1" and asset.kind == "actor-mixer"
                else kind["metadata_type"]
            )
            scopes.append(metadata_type)
            properties: list[dict[str, Any]] = []
            if asset.loop == "infinite":
                properties.extend(
                    [
                        {"name": "IsLoopingEnabled", "value": True},
                        {"name": "IsLoopingInfinite", "value": True},
                    ]
                )
            if asset.volume_db is not None:
                properties.append({"name": "Volume", "value": asset.volume_db})
            references: list[dict[str, Any]] = []
            for handle, value in asset.fields.items():
                binding = self._fields[handle]
                if binding.field_kind == "property":
                    properties.append({"name": binding.name, "value": value})
                else:
                    target = self._objects[str(value)]
                    assert target.object_id is not None
                    references.append(
                        {
                            "name": binding.name,
                            "target": {"kind": "id", "value": target.object_id},
                        }
                    )
            if asset.output_bus is not None:
                bus = self._objects[asset.output_bus]
                assert bus.object_id is not None
                references.append(
                    {
                        "name": "OutputBus",
                        "target": {"kind": "id", "value": bus.object_id},
                    }
                )
            row: dict[str, Any] = {
                "object_path": (
                    self._objects[asset.target].path
                    if asset.target is not None
                    else f"{self._objects[str(asset.parent)].path}\\<{kind['path_type']}>{asset.name}"
                ),
                "object_type": kind["wire_type"],
                "audio_file": asset.media_file,
                "import_language": asset.language,
            }
            if properties:
                row["properties"] = properties
            if references:
                row["references"] = references
            if asset.switch_value is not None:
                row["switch_assignment"] = asset.switch_value
            rows.append(row)
            property_specs.append(properties)
            reference_specs.append(references)

        request_payload = {
            "contract": "waapi-skill.operation-request/v1",
            "version": self.version,
            "operation": "audio.import",
            "arguments": {
                "imports": rows,
                **(
                    {"import_operation": import_operation}
                    if import_operation != "createNew"
                    else {}
                ),
            },
        }
        request = parse_operation_request(
            request_payload,
            expected_version=self.version,
        )
        plan = build_audio_import_plan(
            rows,
            version=self.version,
            import_operation=import_operation,
        )
        targets = []
        declarations: list[StructureDeclaration | AssetDeclaration] = [
            *self._structures,
            *self._assets,
        ]
        for raw, declaration, properties, references in zip(
            plan["oracle"]["targets"],
            declarations,
            property_specs,
            reference_specs,
            strict=True,
        ):
            target = dict(raw)
            target["metadata_object_type"] = _KIND_MAP[declaration.kind][
                "metadata_type"
            ]
            target["requested_notes_destination"] = "target_object"
            target["validated_properties"] = [dict(value) for value in properties]
            target["validated_references"] = [
                {
                    "name": str(value["name"]),
                    "target_id": str(value["target"]["value"]),
                }
                for value in references
            ]
            targets.append(target)
        dispatch, mapping = _materialize_audio_import_dynamic_rows(
            dispatch_args=plan["dispatch_args"],
            targets=targets,
        )
        projected_rows: list[dict[str, Any]] = []
        for map_row in mapping:
            for native in map_row["native_rows"]:
                row = dict(dispatch["imports"][native["native_index"]])
                row["kind"] = native["kind"]
                projected_rows.append(row)
        next_command = _mvp_preview_next_command()
        return MvpCompilation(
            request=request.as_dict(),
            metadata_scopes=tuple(dict.fromkeys(scopes)),
            native_rows=tuple(projected_rows),
            native_row_mapping=tuple(dict(value) for value in mapping),
            next_command=next_command,
            model_authored_fields=(
                *_MODEL_ASSET_FIELDS,
                *(
                    ("fields",)
                    if any(asset.fields_supplied for asset in self._assets)
                    else ()
                ),
            ),
            native_call_count=1,
        )

    def build_preview_artifact(
        self,
        *,
        read_call: ReadCall,
        project_guard: Mapping[str, Any],
        skill_root: Path,
    ) -> TransactionArtifact:
        """Compile through the production immutable transaction boundary.

        The MVP owns only the high-level declaration seam.  The canonical
        request is reparsed and prepared by the existing transaction runtime;
        this method deliberately does not reuse the MVP's diagnostic native
        projection as execution authority.
        """

        compilation = self.compile()
        return build_transaction_preview_artifact(
            compilation.request,
            live_version=self.version,
            read_call=read_call,
            project_guard=project_guard,
            skill_root=skill_root,
        )

    def _repair(
        self,
        error_code: str,
        *,
        field: str,
        action: str,
        rejected_handle: str | None = None,
    ) -> MvpRepairError:
        payload: dict[str, Any] = {
            "contract": "waapi-skill.business-repair/v1",
            "error_code": error_code,
            "field": field,
        }
        if rejected_handle is not None:
            payload["rejected_handle"] = rejected_handle
        payload.update(
            {
                "draft_revision": self._revision,
                "draft_changed": False,
                "action": action,
            }
        )
        return MvpRepairError(payload)

    def _validate_bound_field_value(
        self,
        binding: BoundField,
        value: Any,
    ) -> Any:
        if binding.field_kind == "reference":
            if not isinstance(value, str) or value not in self._objects:
                raise self._repair(
                    "REFERENCE_TARGET_HANDLE_STALE_OR_OUT_OF_SCOPE",
                    field="fields",
                    rejected_handle=str(value),
                    action="resolve the reference target in this task",
                )
            target = self._objects[value]
            allowed = {
                item.casefold().replace(" ", "").replace("-", "")
                for item in binding.allowed_target_types
            }
            actual = target.object_type.casefold().replace(" ", "").replace("-", "")
            if actual not in allowed:
                raise self._repair(
                    "REFERENCE_TARGET_TYPE_MISMATCH",
                    field="fields",
                    rejected_handle=value,
                    action=(
                        "resolve a reference target whose live type is one of: "
                        + ", ".join(binding.allowed_target_types)
                    ),
                )
            return value
        if binding.value_type in {"number", "integer"}:
            try:
                normalized = _finite_number(value, field_name=binding.name)
            except ValueError as exc:
                raise self._repair(
                    "FIELD_VALUE_TYPE_MISMATCH",
                    field="fields",
                    rejected_handle=binding.handle,
                    action=f"resubmit a finite {binding.value_type} value",
                ) from exc
            assert normalized is not None
            if binding.value_type == "integer" and not normalized.is_integer():
                raise self._repair(
                    "FIELD_VALUE_TYPE_MISMATCH",
                    field="fields",
                    rejected_handle=binding.handle,
                    action="resubmit an integer value",
                )
            if (
                binding.minimum is not None
                and normalized < binding.minimum
            ) or (
                binding.maximum is not None
                and normalized > binding.maximum
            ):
                raise self._repair(
                    "FIELD_VALUE_OUT_OF_RANGE",
                    field="fields",
                    rejected_handle=binding.handle,
                    action="resubmit a value inside the live metadata range",
                )
            return int(normalized) if binding.value_type == "integer" else normalized
        if binding.value_type == "boolean" and type(value) is bool:
            return value
        if binding.value_type == "string" and isinstance(value, str):
            return value
        raise self._repair(
            "FIELD_VALUE_TYPE_MISMATCH",
            field="fields",
            rejected_handle=binding.handle,
            action=f"resubmit a {binding.value_type} value",
        )

    def _require_child_name(self, name: str) -> None:
        if (
            not isinstance(name, str)
            or not name
            or "\\" in name
            or "<" in name
            or ">" in name
        ):
            raise self._repair(
                "INVALID_CHILD_NAME",
                field="name",
                action="resubmit one non-empty Wwise child name without path syntax",
            )

    def _require_media_file(self, value: str | Path) -> Path:
        try:
            path = Path(value).expanduser().resolve(strict=True)
        except (OSError, TypeError, ValueError) as exc:
            raise self._repair(
                "MEDIA_FILE_UNAVAILABLE",
                field="media_file",
                action="resubmit one available absolute media file",
            ) from exc
        if not path.is_file():
            raise self._repair(
                "MEDIA_FILE_UNAVAILABLE",
                field="media_file",
                action="resubmit one available absolute media file",
            )
        return path


def _opaque_handle(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"mvp-{prefix}-{digest}"


def _finite_number(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    normalized = float(value)
    if normalized != normalized or normalized in {float("inf"), float("-inf")}:
        raise ValueError(f"{field_name} must be a finite number")
    return normalized


def _mvp_preview_next_command() -> dict[str, Any]:
    full_argv = (
        "python",
        ".agents/skills/waapi-skill/scripts/run.py",
        "gateway.py",
        "mvp-preview",
    )
    payload: dict[str, Any] = {
        "contract": "waapi-skill.transaction-next-command/v2",
        "command": "mvp-preview",
        "gateway_argv": ["mvp-preview"],
        "full_argv": list(full_argv),
        "copy_exactly": True,
        "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
    }
    if os.name == "nt":
        payload["shell_family"] = WINDOWS_POWERSHELL_ENCODED_FAMILY
        payload["shell_command"] = encode_windows_powershell_argv(full_argv)
        payload["model_shell_family"] = WINDOWS_MODEL_COMMAND_FAMILY
        payload["model_command"] = encode_windows_model_argv(full_argv)
        source_field = "model_command"
    else:
        payload["shell_family"] = "posix-sh"
        payload["shell_command"] = shlex.join(full_argv)
        source_field = "shell_command"
    payload["copy_instruction"] = {
        "contract": "waapi-skill.gateway-command-copy-instruction/v2",
        "source_field": source_field,
        "action": "execute_verbatim_as_one_shell_tool_call",
        "forbidden_transformations": [
            "reconstruct",
            "shorten",
            "normalize",
            "substitute_path_segments",
            "select_another_field",
        ],
    }
    return payload


__all__ = [
    "DeclarationResult",
    "ImportBusinessMvp",
    "MVP_CONTRACT",
    "MvpCompilation",
    "MvpRepairError",
]
