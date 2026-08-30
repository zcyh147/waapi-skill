"""Select one operation-local Business Declaration Adapter at one seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .audio_import_business_contracts import audio_import_business_contract_data
from .authoring_ui_business_contracts import authoring_ui_business_contract_data
from .exact_artifact_business_contracts import (
    exact_artifact_business_contract_data,
)
from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import ExistingObjectTarget, business_repair
from .debug_business_contracts import debug_business_contract_data
from .compound_undo_business_contracts import (
    compound_undo_business_contract_data,
)
from .core_business_contracts import (
    core_business_contract_data,
    core_business_draft_operations,
)
from .cli_console_business_contracts import (
    CLI_CONSOLE_BUSINESS_OPERATIONS,
    cli_console_business_contract_data,
)
from .host_ui_debug_business_contracts import (
    HOST_UI_DEBUG_DRAFT_OPERATIONS,
    host_ui_debug_business_contract_data,
)
from .object_lifecycle_business_contracts import (
    object_lifecycle_business_contract_data,
)
from .object_metadata_business_contracts import (
    object_metadata_business_contract_data,
)
from .object_graph_business_contracts import object_graph_business_contract_data
from .project_setting_business_contracts import (
    project_setting_business_contract_data,
    project_setting_business_operations,
)
from .source_control_business_contracts import (
    source_control_business_contract_data,
    source_control_business_draft_operations,
)
from .runtime_inspection_business_contracts import (
    runtime_control_business_operations,
    runtime_inspection_business_contract_data,
)
from .soundengine_business_contracts import (
    soundengine_control_business_contract_data,
    soundengine_control_business_operations,
)
from .switch_assignment_business_contracts import (
    switch_assignment_business_contract_data,
)
from .soundbank_business_contracts import soundbank_business_contract_data


ContractBuilder = Callable[[str, str], dict[str, Any]]
Materializer = Callable[
    [str, BusinessDeclarationSession],
    Mapping[str, Any],
]
PreviewCompiler = Callable[
    [BusinessDeclarationSession, Callable[..., Mapping[str, Any]]],
    Any,
]
CompletenessCheck = Callable[[str, BusinessDeclarationSession], bool]


@dataclass(frozen=True, slots=True)
class BusinessRoleDeclaration:
    """Adapter-owned mapping for one closed bound-role declaration command."""

    command: str
    declaration_id: str
    target_field: str
    value_fields: tuple[str, ...]
    roles: tuple[str, ...]
    continuation_argv: tuple[str, ...]
    forbidden_inputs: tuple[str, ...] = ()

    @property
    def required_fields(self) -> tuple[str, ...]:
        return (self.target_field, *self.value_fields)

    def update(
        self,
        session: BusinessDeclarationSession,
        values: Mapping[str, str],
    ) -> BusinessDeclarationSession:
        if set(values) != set(self.required_fields):
            raise TypeError("role declaration values do not match its Adapter contract")
        for role, field in zip(self.roles, self.required_fields, strict=True):
            bound = session.handles.resolve_object(values[field])
            if bound.role != role:
                raise business_repair(
                    "BOUND_OBJECT_ROLE_MISMATCH",
                    field=field,
                    draft_revision=session.revision,
                    expected_role=role,
                    actual_role=bound.role,
                    action=(
                        "copy the handle returned by the matching Gateway-owned "
                        "role continuation"
                    ),
                )
        return session.with_existing_declaration(
            declaration_id=self.declaration_id,
            target=ExistingObjectTarget(values[self.target_field]),
            fields={name: values[name] for name in self.value_fields},
        )


def _audio_import_contract(operation: str, version: str) -> dict[str, Any]:
    if operation != "audio.import":  # pragma: no cover - registry invariant
        raise ValueError("audio-import Adapter received the wrong operation")
    return audio_import_business_contract_data(version)


def _authoring_ui_contract(operation: str, version: str) -> dict[str, Any]:
    return authoring_ui_business_contract_data(operation, version)


def _debug_contract(operation: str, version: str) -> dict[str, Any]:
    return debug_business_contract_data(operation, version)


def _compound_undo_contract(operation: str, version: str) -> dict[str, Any]:
    if operation != "waapi.undoGroup":  # pragma: no cover - registry invariant
        raise ValueError("compound Undo Adapter received the wrong operation")
    return compound_undo_business_contract_data(version)


def _core_business_contract(operation: str, version: str) -> dict[str, Any]:
    return core_business_contract_data(operation, version)


def _cli_console_contract(operation: str, version: str) -> dict[str, Any]:
    return cli_console_business_contract_data(operation, version)


def _host_ui_debug_contract(operation: str, version: str) -> dict[str, Any]:
    return host_ui_debug_business_contract_data(operation, version)


def _object_lifecycle_contract(operation: str, version: str) -> dict[str, Any]:
    return object_lifecycle_business_contract_data(operation, version)


def _object_metadata_contract(operation: str, version: str) -> dict[str, Any]:
    return object_metadata_business_contract_data(operation, version)


def _object_graph_contract(operation: str, version: str) -> dict[str, Any]:
    return object_graph_business_contract_data(operation, version)


def _project_setting_contract(operation: str, version: str) -> dict[str, Any]:
    return project_setting_business_contract_data(operation, version)


def _source_control_contract(operation: str, version: str) -> dict[str, Any]:
    return source_control_business_contract_data(operation, version)


def _runtime_control_contract(operation: str, version: str) -> dict[str, Any]:
    return runtime_inspection_business_contract_data(operation, version)


def _soundengine_control_contract(operation: str, version: str) -> dict[str, Any]:
    return soundengine_control_business_contract_data(operation, version)


def _switch_assignment_contract(
    operation: str,
    version: str,
) -> dict[str, Any]:
    return switch_assignment_business_contract_data(operation, version)


def _soundbank_contract(operation: str, version: str) -> dict[str, Any]:
    return soundbank_business_contract_data(operation, version)


def _exact_artifact_contract(operation: str, version: str) -> dict[str, Any]:
    return exact_artifact_business_contract_data(operation, version)


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


def _materialize_project_setting(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .project_setting_business import (
        materialize_project_setting_business_request,
    )

    return materialize_project_setting_business_request(operation, session)


def _materialize_source_control(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .source_control_business import (
        materialize_source_control_business_request,
    )

    return materialize_source_control_business_request(operation, session)


def _materialize_runtime_control(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .runtime_inspection_business import (
        materialize_runtime_control_business_request,
    )

    return materialize_runtime_control_business_request(operation, session)


def _materialize_soundengine_control(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .soundengine_business import (
        materialize_soundengine_control_business_request,
    )

    return materialize_soundengine_control_business_request(operation, session)


def _materialize_switch_assignment(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .switch_assignment_business import (
        materialize_switch_assignment_business_request,
    )

    return materialize_switch_assignment_business_request(operation, session)


def _materialize_soundbank(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .soundbank_business import materialize_soundbank_business_request

    return materialize_soundbank_business_request(operation, session)


def _materialize_exact_artifact(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .exact_artifact_business import (
        materialize_exact_artifact_business_request,
    )

    return materialize_exact_artifact_business_request(operation, session)


def _materialize_exact_artifact_with_cleaned_file_evidence(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .exact_artifact_business import (
        materialize_exact_artifact_business_request,
    )

    return materialize_exact_artifact_business_request(
        operation,
        session,
        allow_cleaned_file_evidence=True,
    )


def _materialize_authoring_ui(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .authoring_ui_business import materialize_authoring_ui_business_request

    return materialize_authoring_ui_business_request(operation, session)


def _materialize_debug(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .debug_business import materialize_debug_business_request

    return materialize_debug_business_request(operation, session)


def _materialize_compound_undo(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .compound_undo_business import materialize_compound_undo_business_request

    return materialize_compound_undo_business_request(operation, session)


def _materialize_core_business(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .core_business import materialize_core_business_request

    return materialize_core_business_request(operation, session)


def _materialize_cli_console(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .cli_console_business import materialize_cli_console_business_request

    return materialize_cli_console_business_request(operation, session)


def _materialize_host_ui_debug(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .host_ui_debug_business import materialize_host_ui_debug_business_request

    return materialize_host_ui_debug_business_request(operation, session)


def _authoring_ui_is_complete(
    operation: str,
    session: BusinessDeclarationSession,
) -> bool:
    from .authoring_ui_business import authoring_ui_business_is_complete

    return authoring_ui_business_is_complete(operation, session)


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
    _completeness_check: CompletenessCheck | None = None
    requires_sound_subtype: bool = False
    supports_field_binding: bool = False
    supports_field_discovery: bool = False
    supports_type_discovery: bool = False
    auto_apply_preview: bool = False
    records_business_preview: bool = False
    requires_wwise_path_discipline: bool = False
    role_declaration: BusinessRoleDeclaration | None = None
    settings_are_complete_declaration: bool = False

    @property
    def supports_cleaned_file_evidence(self) -> bool:
        """Whether archive replay may materialize after owned files are gone."""

        return self._cleaned_file_evidence_materializer is not None

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

    def is_complete(self, session: BusinessDeclarationSession) -> bool:
        if self._completeness_check is not None:
            return self._completeness_check(self.operation, session)
        return (
            bool(session.settings)
            if self.settings_are_complete_declaration
            else bool(session.declarations)
        )


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
            "draft-declare-import-batch",
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
        "declare-import-batch",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "bind-object",
        "bind-field",
        "configure",
        "declare-new",
        "declare-existing",
        "declare-import-batch",
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
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "bind-object",
        "configure",
        "discover-fields",
        "discover-types",
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

_OBJECT_PLUGIN_DEFINITION = {
    **_OBJECT_GRAPH_DEFINITION,
    "requires_sound_subtype": True,
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
            "draft-clear-object-list",
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
        "clear-object-list",
        "configure",
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

_SWITCH_ASSIGNMENT_DEFINITION = {
    "family": "switch-assignment",
    "contract_builder": _switch_assignment_contract,
    "materializer": _materialize_switch_assignment,
    "update_commands": frozenset({"draft-declare-switch-assignment"}),
    "initial_projection_actions": ("bind-object", "inspect", "cancel"),
    "active_projection_actions": (
        "bind-object",
        "declare-switch-assignment",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "role_declaration": BusinessRoleDeclaration(
        command="draft-declare-switch-assignment",
        declaration_id="assignment",
        target_field="switch_container_handle",
        value_fields=("child_handle", "state_or_switch_handle"),
        roles=("switch_container", "child", "state_or_switch"),
        continuation_argv=(
            "--switch-container-handle",
            "<bound-switch-container-handle>",
            "--child-handle",
            "<bound-child-handle>",
            "--state-or-switch-handle",
            "<bound-state-or-switch-handle>",
        ),
        forbidden_inputs=(
            "direct_child_selector",
            "scoped_name_selector",
            "relationship_request_fragment",
        ),
    ),
}

_SOUNDBANK_DEFINITION = {
    "family": "soundbank-planning",
    "contract_builder": _soundbank_contract,
    "materializer": _materialize_soundbank,
    "update_commands": frozenset({"draft-declare-soundbank-plan"}),
    "initial_projection_actions": (
        "bind-object",
        "declare-soundbank-plan",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "bind-object",
        "declare-soundbank-plan",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
}

_EXACT_ARTIFACT_DEFINITION = {
    "family": "exact-artifact-code",
    "contract_builder": _exact_artifact_contract,
    "materializer": _materialize_exact_artifact,
    "cleaned_file_evidence_materializer": (
        _materialize_exact_artifact_with_cleaned_file_evidence
    ),
    "update_commands": frozenset({"draft-declare-artifact-plan"}),
    "initial_projection_actions": (
        "bind-object",
        "declare-artifact-plan",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "bind-object",
        "declare-artifact-plan",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
}

_EXACT_ARTIFACT_CODE_DEFINITION = {
    **_EXACT_ARTIFACT_DEFINITION,
    "initial_projection_actions": (
        "declare-artifact-plan",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "declare-artifact-plan",
        "check",
        "inspect",
        "cancel",
    ),
}

_AUTHORING_UI_DEFINITION = {
    "family": "authoring-ui-business",
    "contract_builder": _authoring_ui_contract,
    "materializer": _materialize_authoring_ui,
    "completeness_check": _authoring_ui_is_complete,
    "update_commands": frozenset({"draft-declare-ui-plan"}),
    "initial_projection_actions": (
        "declare-ui-plan",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "declare-ui-plan",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
}

_AUTHORING_UI_REGISTER_DEFINITION = {
    **_AUTHORING_UI_DEFINITION,
    "update_commands": frozenset(
        {"draft-declare-ui-plan", "draft-add-ui-command"}
    ),
    "active_projection_actions": (
        "declare-ui-plan",
        "add-ui-command",
        "check",
        "inspect",
        "cancel",
    ),
}

_DEBUG_DEFINITION = {
    "family": "debug-host-control",
    "contract_builder": _debug_contract,
    "materializer": _materialize_debug,
    "update_commands": frozenset({"draft-declare-debug-intent"}),
    "initial_projection_actions": (
        "declare-debug-intent",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "declare-debug-intent",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
}

_COMPOUND_UNDO_DEFINITION = {
    "family": "compound-undo-business",
    "contract_builder": _compound_undo_contract,
    "materializer": _materialize_compound_undo,
    "update_commands": frozenset({"draft-declare-undo-plan"}),
    "initial_projection_actions": (
        "declare-undo-plan",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "declare-undo-plan",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
}

_CORE_BUSINESS_DEFINITION = {
    "family": "core-project-object",
    "contract_builder": _core_business_contract,
    "materializer": _materialize_core_business,
    "update_commands": frozenset({"draft-declare-core-plan"}),
    "initial_projection_actions": ("bind-object", "inspect", "cancel"),
    "active_projection_actions": (
        "bind-object",
        "declare-core-plan",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
    "supports_field_discovery": True,
}

_PROJECT_SETTING_DEFINITION = {
    "family": "project-setting-business",
    "contract_builder": _project_setting_contract,
    "materializer": _materialize_project_setting,
    "update_commands": frozenset({"draft-declare-project-setting-plan"}),
    "initial_projection_actions": ("bind-object", "inspect", "cancel"),
    "active_projection_actions": (
        "bind-object",
        "declare-project-setting-plan",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
}

_SOURCE_CONTROL_DEFINITION = {
    "family": "source-control-business",
    "contract_builder": _source_control_contract,
    "materializer": _materialize_source_control,
    "update_commands": frozenset({"draft-declare-source-control-plan"}),
    "initial_projection_actions": ("declare-source-control-plan", "inspect", "cancel"),
    "active_projection_actions": (
        "declare-source-control-plan",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
}

_RUNTIME_CONTROL_DEFINITION = {
    "family": "runtime-control-business",
    "contract_builder": _runtime_control_contract,
    "materializer": _materialize_runtime_control,
    "update_commands": frozenset({"draft-declare-runtime-control-plan"}),
    "initial_projection_actions": (
        "declare-runtime-control-plan",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "declare-runtime-control-plan",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
}

_SOUNDENGINE_CONTROL_DEFINITION = {
    "family": "soundengine-control-business",
    "contract_builder": _soundengine_control_contract,
    "materializer": _materialize_soundengine_control,
    "update_commands": frozenset({"draft-declare-soundengine-plan"}),
    "initial_projection_actions": (
        "declare-soundengine-plan",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "declare-soundengine-plan",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
}

_CLI_CONSOLE_DEFINITION = {
    "family": "cli-console-business",
    "contract_builder": _cli_console_contract,
    "materializer": _materialize_cli_console,
    "update_commands": frozenset({"draft-declare-cli-console-plan"}),
    "initial_projection_actions": (
        "declare-cli-console-plan",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "declare-cli-console-plan",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
}

_HOST_UI_DEBUG_DEFINITION = {
    "family": "host-ui-debug-business",
    "contract_builder": _host_ui_debug_contract,
    "materializer": _materialize_host_ui_debug,
    "update_commands": frozenset({"draft-declare-host-plan"}),
    "initial_projection_actions": (
        "declare-host-plan",
        "inspect",
        "cancel",
    ),
    "active_projection_actions": (
        "declare-host-plan",
        "check",
        "inspect",
        "cancel",
    ),
    "auto_apply_preview": True,
    "settings_are_complete_declaration": True,
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
    values["_completeness_check"] = values.pop("completeness_check", None)
    return BusinessAdapter(operation=operation, **values)


_BUSINESS_ADAPTERS = {
    **{
        operation: _bind_adapter(operation, _HOST_UI_DEBUG_DEFINITION)
        for operation in HOST_UI_DEBUG_DRAFT_OPERATIONS
    },
    **{
        operation: _bind_adapter(operation, _CLI_CONSOLE_DEFINITION)
        for operation in CLI_CONSOLE_BUSINESS_OPERATIONS
    },
    **{
        operation: _bind_adapter(operation, _CORE_BUSINESS_DEFINITION)
        for operation in core_business_draft_operations()
    },
    **{
        operation: _bind_adapter(operation, _PROJECT_SETTING_DEFINITION)
        for operation in project_setting_business_operations()
    },
    **{
        operation: _bind_adapter(operation, _SOURCE_CONTROL_DEFINITION)
        for operation in source_control_business_draft_operations()
    },
    **{
        operation: _bind_adapter(operation, _RUNTIME_CONTROL_DEFINITION)
        for operation in runtime_control_business_operations()
    },
    **{
        operation: _bind_adapter(operation, _SOUNDENGINE_CONTROL_DEFINITION)
        for operation in soundengine_control_business_operations()
    },
    "audio.import": _bind_adapter("audio.import", _AUDIO_IMPORT_DEFINITION),
    "audio.importTabDelimited": _bind_adapter(
        "audio.importTabDelimited",
        _EXACT_ARTIFACT_DEFINITION,
    ),
    **{
        operation: _bind_adapter(operation, _EXACT_ARTIFACT_CODE_DEFINITION)
        for operation in (
            "lua.executeCliFile",
            "lua.executeCoreFile",
            "lua.executeCoreInline",
        )
    },
    **{
        operation: _bind_adapter(operation, _AUTHORING_UI_DEFINITION)
        for operation in (
            "ui.captureScreen",
            "ui.commands.execute",
            "ui.commands.unregister",
        )
    },
    "ui.commands.register": _bind_adapter(
        "ui.commands.register",
        _AUTHORING_UI_REGISTER_DEFINITION,
    ),
    **{
        operation: _bind_adapter(operation, _DEBUG_DEFINITION)
        for operation in (
            "debug.restartWaapiServers",
            "debug.setAsserts",
            "debug.setAutomationMode",
            "debug.testAssert",
            "debug.testCrash",
        )
    },
    "waapi.undoGroup": _bind_adapter(
        "waapi.undoGroup",
        _COMPOUND_UNDO_DEFINITION,
    ),
    "object.create": _bind_adapter("object.create", _OBJECT_GRAPH_DEFINITION),
    "object.createPlugin": _bind_adapter(
        "object.createPlugin", _OBJECT_PLUGIN_DEFINITION
    ),
    "object.setRTPC": _bind_adapter(
        "object.setRTPC", _OBJECT_RTPC_DEFINITION
    ),
    "object.set": _bind_adapter("object.set", _OBJECT_SET_BUSINESS_DEFINITION),
    "switchContainer.addAssignment": _bind_adapter(
        "switchContainer.addAssignment",
        _SWITCH_ASSIGNMENT_DEFINITION,
    ),
    "switchContainer.removeAssignment": _bind_adapter(
        "switchContainer.removeAssignment",
        _SWITCH_ASSIGNMENT_DEFINITION,
    ),
    **{
        operation: _bind_adapter(operation, _SOUNDBANK_DEFINITION)
        for operation in (
            "soundbank.convertExternalSources",
            "soundbank.generate",
            "soundbank.processDefinitionFiles",
            "soundbank.setInclusions",
        )
    },
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
    "BusinessRoleDeclaration",
    "business_adapter",
    "business_adapter_operations",
]
