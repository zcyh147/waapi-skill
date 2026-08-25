"""Select one operation-local Business Declaration Adapter at one seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .audio_import_business_contracts import audio_import_business_contract_data
from .business_declaration_state import BusinessDeclarationSession
from .object_lifecycle_business_contracts import (
    object_lifecycle_business_contract_data,
)
from .object_metadata_business_contracts import (
    object_metadata_business_contract_data,
)
from .object_graph_business_contracts import object_graph_business_contract_data


ContractBuilder = Callable[[str, str], dict[str, Any]]
Materializer = Callable[
    [str, BusinessDeclarationSession],
    Mapping[str, Any],
]
PreviewCompiler = Callable[
    [BusinessDeclarationSession, Callable[..., Mapping[str, Any]]],
    Any,
]


def _audio_import_contract(operation: str, version: str) -> dict[str, Any]:
    if operation != "audio.import":  # pragma: no cover - registry invariant
        raise ValueError("audio-import Adapter received the wrong operation")
    return audio_import_business_contract_data(version)


def _object_lifecycle_contract(operation: str, version: str) -> dict[str, Any]:
    return object_lifecycle_business_contract_data(operation, version)


def _object_metadata_contract(operation: str, version: str) -> dict[str, Any]:
    return object_metadata_business_contract_data(operation, version)


def _object_graph_contract(operation: str, version: str) -> dict[str, Any]:
    return object_graph_business_contract_data(operation, version)


def _materialize_audio_import(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    if operation != "audio.import":  # pragma: no cover - registry invariant
        raise ValueError("audio-import Adapter received the wrong operation")
    from .audio_import_business import materialize_audio_import_business_request

    return materialize_audio_import_business_request(
        session,
        allow_cleaned_file_evidence=False,
    )


def _materialize_audio_import_with_cleaned_file_evidence(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    if operation != "audio.import":  # pragma: no cover - registry invariant
        raise ValueError("audio-import Adapter received the wrong operation")
    from .audio_import_business import materialize_audio_import_business_request

    return materialize_audio_import_business_request(
        session,
        allow_cleaned_file_evidence=True,
    )


def _materialize_object_lifecycle(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .object_lifecycle_business import (
        materialize_object_lifecycle_business_request,
    )

    return materialize_object_lifecycle_business_request(operation, session)


def _materialize_object_metadata(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .object_metadata_business import (
        materialize_object_metadata_business_request,
    )

    return materialize_object_metadata_business_request(operation, session)


def _materialize_object_graph(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .object_graph_business import materialize_object_graph_business_request

    return materialize_object_graph_business_request(operation, session)


def _compile_audio_import_preview(
    session: BusinessDeclarationSession,
    build_continuation: Callable[..., Mapping[str, Any]],
) -> Any:
    from .audio_import_business import compile_audio_import_business

    return compile_audio_import_business(
        session,
        build_continuation=build_continuation,
    )


@dataclass(frozen=True, slots=True)
class BusinessAdapter:
    """Operation-bound Adapter interface shared by Registry, Draft, and Gateway."""

    operation: str
    family: str
    _contract_builder: ContractBuilder
    _materializer: Materializer
    update_commands: frozenset[str]
    initial_projection_actions: tuple[str, ...]
    active_projection_actions: tuple[str, ...]
    _cleaned_file_evidence_materializer: Materializer | None = None
    _preview_compiler: PreviewCompiler | None = None
    requires_sound_subtype: bool = False
    supports_field_binding: bool = False
    supports_field_discovery: bool = False
    supports_type_discovery: bool = False
    auto_apply_preview: bool = False
    records_business_preview: bool = False
    requires_wwise_path_discipline: bool = False

    def contract(self, version: str) -> dict[str, Any]:
        return self._contract_builder(self.operation, version)

    def materialize(
        self,
        session: BusinessDeclarationSession,
        *,
        allow_cleaned_file_evidence: bool = False,
    ) -> Mapping[str, Any]:
        if allow_cleaned_file_evidence:
            if self._cleaned_file_evidence_materializer is None:
                raise ValueError(
                    f"{self.operation} does not accept cleaned file evidence"
                )
            return self._cleaned_file_evidence_materializer(self.operation, session)
        return self._materializer(self.operation, session)

    def accepts_update_command(self, command: str) -> bool:
        return command in self.update_commands

    def projection_actions(self, *, session_bound: bool) -> list[str]:
        return list(
            self.active_projection_actions
            if session_bound
            else self.initial_projection_actions
        )

    def compile_preview(
        self,
        session: BusinessDeclarationSession,
        *,
        build_continuation: Callable[..., Mapping[str, Any]],
    ) -> Any | None:
        if self._preview_compiler is None:
            return None
        return self._preview_compiler(session, build_continuation)


_AUDIO_IMPORT_DEFINITION = {
    "family": "audio-import",
    "contract_builder": _audio_import_contract,
    "materializer": _materialize_audio_import,
    "cleaned_file_evidence_materializer": (
        _materialize_audio_import_with_cleaned_file_evidence
    ),
    "update_commands": frozenset(
        {
            "draft-business-configure",
            "draft-declare-existing",
            "draft-declare-new",
            "draft-remove-declaration",
            "draft-revise-declaration",
        }
    ),
    "initial_projection_actions": (
        "bind-object",
        "bind-field",
        "configure",
        "declare-new",
        "declare-existing",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "bind-object",
        "bind-field",
        "configure",
        "declare-new",
        "declare-existing",
        "revise-declaration",
        "remove-declaration",
        "check",
        "inspect",
        "cancel",
    ),
    "preview_compiler": _compile_audio_import_preview,
    "requires_sound_subtype": True,
    "supports_field_binding": True,
    "auto_apply_preview": True,
    "records_business_preview": True,
    "requires_wwise_path_discipline": True,
}

_OBJECT_LIFECYCLE_DEFINITION = {
    "family": "object-lifecycle",
    "contract_builder": _object_lifecycle_contract,
    "materializer": _materialize_object_lifecycle,
    "update_commands": frozenset({"draft-declare-object-change"}),
    "initial_projection_actions": ("bind-object", "inspect", "cancel"),
    "active_projection_actions": (
        "bind-object",
        "declare-object-change",
        "check",
        "inspect",
        "cancel",
    ),
    "requires_sound_subtype": False,
    "supports_field_binding": False,
    "auto_apply_preview": True,
}

_OBJECT_METADATA_DEFINITION = {
    "family": "object-metadata-fields",
    "contract_builder": _object_metadata_contract,
    "materializer": _materialize_object_metadata,
    "update_commands": frozenset({"draft-declare-field-change"}),
    "initial_projection_actions": ("bind-object", "inspect", "cancel"),
    "active_projection_actions": (
        "bind-object",
        "discover-fields",
        "declare-field-change",
        "check",
        "inspect",
        "cancel",
    ),
    "requires_sound_subtype": False,
    "supports_field_binding": False,
    "supports_field_discovery": True,
    "auto_apply_preview": True,
}

_OBJECT_GRAPH_DEFINITION = {
    "family": "object-creation-graph",
    "contract_builder": _object_graph_contract,
    "materializer": _materialize_object_graph,
    "update_commands": frozenset(
        {
            "draft-business-configure",
            "draft-declare-new",
            "draft-declare-existing",
            "draft-remove-declaration",
            "draft-revise-declaration",
        }
    ),
    "initial_projection_actions": (
        "bind-object",
        "configure",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "bind-object",
        "configure",
        "declare-new",
        "declare-existing",
        "revise-declaration",
        "remove-declaration",
        "check",
        "inspect",
        "cancel",
    ),
    "requires_sound_subtype": False,
    "supports_field_binding": True,
    "supports_field_discovery": True,
    "supports_type_discovery": True,
    "auto_apply_preview": True,
    "requires_wwise_path_discipline": True,
}

_OBJECT_RTPC_DEFINITION = {
    "family": "object-creation-graph",
    "contract_builder": _object_graph_contract,
    "materializer": _materialize_object_graph,
    "update_commands": frozenset({"draft-declare-rtpc"}),
    "initial_projection_actions": ("bind-object", "inspect", "cancel"),
    "active_projection_actions": (
        "bind-object",
        "discover-fields",
        "declare-rtpc",
        "check",
        "inspect",
        "cancel",
    ),
    "supports_field_discovery": True,
    "auto_apply_preview": True,
}

_OBJECT_SET_BUSINESS_DEFINITION = {
    "family": "object-creation-graph",
    "contract_builder": _object_graph_contract,
    "materializer": _materialize_object_graph,
    "update_commands": frozenset(
        {
            "draft-add-media",
            "draft-business-configure",
            "draft-declare-existing",
            "draft-declare-new",
            "draft-remove-declaration",
            "draft-revise-declaration",
        }
    ),
    "initial_projection_actions": ("bind-object", "inspect", "cancel"),
    "active_projection_actions": (
        "add-media",
        "bind-object",
        "discover-fields",
        "discover-types",
        "declare-existing",
        "declare-new",
        "revise-declaration",
        "remove-declaration",
        "check",
        "inspect",
        "cancel",
    ),
    "supports_field_discovery": True,
    "supports_type_discovery": True,
    "auto_apply_preview": True,
}


def _bind_adapter(operation: str, definition: Mapping[str, Any]) -> BusinessAdapter:
    values = dict(definition)
    values["_contract_builder"] = values.pop("contract_builder")
    values["_materializer"] = values.pop("materializer")
    values["_cleaned_file_evidence_materializer"] = values.pop(
        "cleaned_file_evidence_materializer",
        None,
    )
    values["_preview_compiler"] = values.pop("preview_compiler", None)
    return BusinessAdapter(operation=operation, **values)


_BUSINESS_ADAPTERS = {
    "audio.import": _bind_adapter("audio.import", _AUDIO_IMPORT_DEFINITION),
    "object.create": _bind_adapter("object.create", _OBJECT_GRAPH_DEFINITION),
    "object.createPlugin": _bind_adapter(
        "object.createPlugin", _OBJECT_GRAPH_DEFINITION
    ),
    "object.setRTPC": _bind_adapter(
        "object.setRTPC", _OBJECT_RTPC_DEFINITION
    ),
    "object.set": _bind_adapter("object.set", _OBJECT_SET_BUSINESS_DEFINITION),
    **{
        operation: _bind_adapter(operation, _OBJECT_LIFECYCLE_DEFINITION)
        for operation in (
            "object.copy",
            "object.delete",
            "object.move",
            "object.setName",
            "object.setNotes",
        )
    },
    **{
        operation: _bind_adapter(operation, _OBJECT_METADATA_DEFINITION)
        for operation in (
            "object.setLinked",
            "object.setProperty",
            "object.setReference",
        )
    },
}


def business_adapter(operation: str) -> BusinessAdapter:
    """Return the sole reviewed Business Declaration Adapter for an operation."""

    return _BUSINESS_ADAPTERS[operation]


def business_adapter_operations() -> frozenset[str]:
    return frozenset(_BUSINESS_ADAPTERS)


__all__ = [
    "BusinessAdapter",
    "business_adapter",
    "business_adapter_operations",
]
