"""Closed v2 eval-session adapter for :class:`CodexGatewayBroker`.

The declarative eval suite describes *which* gateway steps a fresh Codex
session may use.  This module binds those fixed step names to the exact
packaged ``gateway.py`` argv allow-list understood by the trusted broker.  It
does not start Codex, Wwise, or the broker, and it does not accept executable
hooks from suite or fixture data.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .codex_eval_suite import (
    BOUNDARY_CASE_IDS,
    OPERATION_REQUEST_CONTRACT,
    SUPPORTED_VERSIONS,
    EvalSession,
    EvalSuiteError,
)
from .codex_gateway_broker import (
    ExpectedGatewayStep,
    ResponseBinding,
    SemanticJsonArgument,
)
from wwise_waapi.topic_business import topic_business_contract


_CONFIRM_RUNTIME_FIELDS = frozenset({"transaction_id", "preview_hash"})


class EvalProtocolError(ValueError):
    """An eval session cannot be represented by the closed broker protocol."""


@dataclass(frozen=True, slots=True)
class _CaseRoute:
    adapter: str
    protocol: str
    operation: str | None
    variables: tuple[str, ...]
    phases: Mapping[str, tuple[str, ...]]


_CASE_ROUTES: Mapping[str, _CaseRoute] = {
    "Q1": _CaseRoute(
        adapter="exact_path_query",
        protocol="read_only",
        operation=None,
        variables=("wwise_version", "query_path"),
        phases={"single": ("query-object",)},
    ),
    "Q2": _CaseRoute(
        adapter="direct_children_query",
        protocol="read_only",
        operation=None,
        variables=("wwise_version", "parent_path"),
        phases={"single": ("query-object",)},
    ),
    "Q3": _CaseRoute(
        adapter="name_search_query",
        protocol="read_only",
        operation=None,
        variables=("wwise_version", "search_name"),
        phases={"single": ("query-object",)},
    ),
    "Q4": _CaseRoute(
        adapter="query_editor_query",
        protocol="read_only",
        operation=None,
        variables=("wwise_version", "query_path"),
        phases={"single": ("query-object",)},
    ),
    "Q5": _CaseRoute(
        adapter="exact_missing_path_query",
        protocol="read_only",
        operation=None,
        variables=("wwise_version", "missing_path"),
        phases={"single": ("query-object",)},
    ),
    "C1": _CaseRoute(
        adapter="offline_catalog",
        protocol="offline_catalog",
        operation=None,
        variables=(),
        phases={"single": ("capabilities",)},
    ),
    "M1": _CaseRoute(
        adapter="object_set_notes",
        protocol="preview_confirm",
        operation="object.setNotes",
        variables=("wwise_version", "target_path", "notes_value"),
        phases={
            "preview": ("operation-schema", "preview"),
            "confirm": ("transaction-show", "confirm", "execute", "verify"),
        },
    ),
    "M2": _CaseRoute(
        adapter="object_set_notes",
        protocol="adversarial_preview",
        operation="object.setNotes",
        variables=("wwise_version", "target_path", "notes_value"),
        phases={"single": ("operation-schema", "preview")},
    ),
    "M3": _CaseRoute(
        adapter="object_create",
        protocol="preview_confirm",
        operation="object.create",
        variables=("wwise_version", "create_parent_path", "create_name", "create_notes"),
        phases={
            "preview": ("operation-schema", "preview"),
            "confirm": ("transaction-show", "confirm", "execute", "verify"),
        },
    ),
    "M4": _CaseRoute(
        adapter="object_delete",
        protocol="preview_confirm",
        operation="object.delete",
        variables=("wwise_version", "delete_target_path"),
        phases={
            "preview": ("operation-schema", "preview"),
            "confirm": ("transaction-show", "confirm", "execute", "verify"),
        },
    ),
    "M5": _CaseRoute(
        adapter="object_set_name",
        protocol="preview_confirm",
        operation="object.setName",
        variables=("wwise_version", "rename_target_path", "rename_value"),
        phases={
            "preview": ("operation-schema", "preview"),
            "confirm": ("transaction-show", "confirm", "execute", "verify"),
        },
    ),
    "M6": _CaseRoute(
        adapter="object_set_property",
        protocol="preview_confirm",
        operation="object.setProperty",
        variables=("wwise_version", "property_target_path"),
        phases={
            "preview": ("operation-schema", "preview"),
            "confirm": ("transaction-show", "confirm", "execute", "verify"),
        },
    ),
    "M7": _CaseRoute(
        adapter="object_set_reference",
        protocol="preview_confirm",
        operation="object.setReference",
        variables=("wwise_version", "reference_source_path", "reference_target_path"),
        phases={
            "preview": ("operation-schema", "preview"),
            "confirm": ("transaction-show", "confirm", "execute", "verify"),
        },
    ),
    "B1": _CaseRoute(
        adapter="operation_boundary",
        protocol="unsupported_boundary",
        operation="object.copy",
        variables=("wwise_version",),
        phases={"single": ("operation-schema",)},
    ),
    "B2": _CaseRoute(
        adapter="operation_boundary",
        protocol="unsupported_boundary",
        operation="audio.importTabDelimited",
        variables=("wwise_version",),
        phases={"single": ("operation-schema",)},
    ),
    "B3": _CaseRoute(
        adapter="operation_boundary",
        protocol="unsupported_boundary",
        operation="object.set",
        variables=("wwise_version",),
        phases={"single": ("operation-schema",)},
    ),
    "B4": _CaseRoute(
        adapter="operation_boundary",
        protocol="unsupported_boundary",
        operation="object.move",
        variables=("wwise_version",),
        phases={"single": ("operation-schema",)},
    ),
    "B5": _CaseRoute(
        adapter="operation_boundary",
        protocol="unsupported_boundary",
        operation="soundbank.generate",
        variables=("wwise_version",),
        phases={"single": ("operation-schema",)},
    ),
    "B6": _CaseRoute(
        adapter="operation_boundary",
        protocol="unsupported_boundary",
        operation="soundbank.convertExternalSources",
        variables=("wwise_version",),
        phases={"single": ("operation-schema",)},
    ),
    "B7": _CaseRoute(
        adapter="operation_boundary",
        protocol="unsupported_boundary",
        operation="soundbank.processDefinitionFiles",
        variables=("wwise_version",),
        phases={"single": ("operation-schema",)},
    ),
    "I1": _CaseRoute(
        adapter="audio_import",
        protocol="preview_confirm",
        operation="audio.import",
        variables=(
            "wwise_version",
            "audio_file",
            "import_object_path",
            "import_object_type",
            "import_notes",
        ),
        phases={
            "preview": ("operation-schema", "preview"),
            "confirm": ("transaction-show", "confirm", "execute", "verify"),
        },
    ),
    "S1": _CaseRoute(
        adapter="soundbank_inclusions",
        protocol="preview_confirm",
        operation="soundbank.setInclusions",
        variables=(
            "wwise_version",
            "soundbank_path",
            "included_object_path",
        ),
        phases={
            "preview": ("operation-schema", "preview"),
            "confirm": ("transaction-show", "confirm", "execute", "verify"),
        },
    ),
    "W1": _CaseRoute(
        adapter="switch_assignment",
        protocol="preview_confirm",
        operation="switchContainer.addAssignment",
        variables=(
            "wwise_version",
            "switch_container_path",
            "child_path",
            "state_or_switch_path",
        ),
        phases={
            "preview": ("operation-schema", "preview"),
            "confirm": ("transaction-show", "confirm", "execute", "verify"),
        },
    ),
    "W2": _CaseRoute(
        adapter="switch_assignment_remove",
        protocol="preview_confirm",
        operation="switchContainer.removeAssignment",
        variables=(
            "wwise_version",
            "remove_switch_container_path",
            "remove_child_path",
            "remove_state_or_switch_path",
        ),
        phases={
            "preview": ("operation-schema", "preview"),
            "confirm": ("transaction-show", "confirm", "execute", "verify"),
        },
    ),
    "R1": _CaseRoute(
        adapter="status_read",
        protocol="status_read_only",
        operation=None,
        variables=("wwise_version",),
        phases={"single": ("status",)},
    ),
    "R2": _CaseRoute(
        adapter="buses_read",
        protocol="buses_read_only",
        operation=None,
        variables=("wwise_version",),
        phases={"single": ("buses",)},
    ),
    "R3": _CaseRoute(
        adapter="selected_read",
        protocol="selected_read_only",
        operation=None,
        variables=("wwise_version",),
        phases={"single": ("selected",)},
    ),
    "R4": _CaseRoute(
        adapter="metadata_types_read",
        protocol="metadata_types_read_only",
        operation=None,
        variables=("wwise_version",),
        phases={"single": ("metadata",)},
    ),
    "R5": _CaseRoute(
        adapter="object_created_topic_read",
        protocol="object_created_topic_read_only",
        operation=None,
        variables=("wwise_version", "topic_probe_name", "topic_probe_event_type"),
        phases={"single": ("topic-schema", "wait-topic")},
    ),
    "R6": _CaseRoute(
        adapter="reflection_functions_read",
        protocol="reflection_functions_read_only",
        operation=None,
        variables=("wwise_version",),
        phases={"single": ("call",)},
    ),
}


def build_expected_gateway_steps(
    session: EvalSession,
    fixture_values: Mapping[str, Any],
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one validated v2 session into an exact broker allow-list.

    Fixture values are closed over the case's declared variables.  The Wwise
    version is supplied by ``session.version`` and may only be repeated with
    the same value.  Runtime transaction identifiers are intentionally not
    accepted only for a confirm session.  The runner must extract them from the
    trusted preview evidence before it creates the fresh confirm broker.
    """

    route = _validate_session(session)
    values = _validate_fixture_values(session, route, fixture_values)

    identity_fields = (
        "--return-field",
        "id",
        "--return-field",
        "name",
        "--return-field",
        "type",
        "--return-field",
        "path",
    )
    if session.case.id == "Q1":
        steps = (
            ExpectedGatewayStep(
                name="query-object",
                subcommand="query-object",
                arguments=(
                    "--path",
                    values["query_path"],
                    *identity_fields,
                ),
            ),
        )
    elif session.case.id == "Q2":
        steps = (
            ExpectedGatewayStep(
                name="query-object",
                subcommand="query-object",
                arguments=(
                    "--path",
                    values["parent_path"],
                    "--select",
                    "children",
                    "--take",
                    "10",
                    *identity_fields,
                ),
            ),
        )
    elif session.case.id == "Q3":
        where_json = json.dumps(
            {"field": "name", "operator": "=", "value": values["search_name"]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        steps = (
            ExpectedGatewayStep(
                name="query-object",
                subcommand="query-object",
                arguments=(
                    "--search",
                    values["search_name"],
                    "--where-json",
                    where_json,
                    "--take",
                    "1",
                    *identity_fields,
                ),
            ),
        )
    elif session.case.id == "Q4":
        steps = (
            ExpectedGatewayStep(
                name="query-object",
                subcommand="query-object",
                arguments=(
                    "--query",
                    values["query_path"],
                    "--take",
                    "10",
                    *identity_fields,
                ),
            ),
        )
    elif session.case.id == "Q5":
        steps = (
            ExpectedGatewayStep(
                name="query-object",
                subcommand="query-object",
                arguments=(
                    "--path",
                    values["missing_path"],
                    *identity_fields,
                ),
            ),
        )
    elif session.case.id == "C1":
        steps = (
            ExpectedGatewayStep(
                name="capabilities",
                subcommand="capabilities",
                arguments=("--all-versions", "--summary-only"),
            ),
        )
    elif session.case.id == "R1":
        steps = (ExpectedGatewayStep(name="status", subcommand="status"),)
    elif session.case.id == "R2":
        steps = (ExpectedGatewayStep(name="buses", subcommand="buses"),)
    elif session.case.id == "R3":
        steps = (ExpectedGatewayStep(name="selected", subcommand="selected"),)
    elif session.case.id == "R4":
        steps = (
            ExpectedGatewayStep(
                name="metadata",
                subcommand="metadata",
                arguments=("types", "--summary-only"),
            ),
        )
    elif session.case.id == "R5":
        topic = "ak.wwise.core.object.created"
        digest = topic_business_contract(session.version, topic).contract_digest
        steps = (
            ExpectedGatewayStep(
                name="topic-schema",
                subcommand="topic-schema",
                arguments=(topic,),
            ),
            ExpectedGatewayStep(
                name="wait-topic",
                subcommand="wait-topic",
                gateway_global_arguments=("--timeout", "10"),
                arguments=(
                    topic,
                    "--topic-contract-digest",
                    digest,
                    "--topic-option",
                    "include",
                    "id",
                    "--topic-option",
                    "include",
                    "name",
                    "--topic-option",
                    "include",
                    "type",
                    "--topic-option",
                    "include",
                    "path",
                    "--event-match",
                    "object-type",
                    values["topic_probe_event_type"],
                ),
            ),
        )
    elif session.case.id == "R6":
        steps = (
            ExpectedGatewayStep(
                name="call",
                subcommand="call",
                arguments=(
                    "ak.wwise.waapi.getFunctions",
                    "--args-json",
                    SemanticJsonArgument({}),
                    "--options-json",
                    SemanticJsonArgument({}),
                ),
                allow_omitted_empty_json_objects=True,
            ),
        )
    elif session.phase == "confirm":
        steps = _confirm_steps(
            transaction_id=values["transaction_id"],
        )
    elif session.case.id in BOUNDARY_CASE_IDS:
        steps = (_operation_schema_step(route),)
    else:
        steps = (
            _operation_schema_step(route),
            _preview_step(session, route, values),
        )

    actual_subcommands = tuple(step.subcommand for step in steps)
    if actual_subcommands != session.gateway_steps:
        raise EvalProtocolError(
            f"session {session.session_id!r} gateway_steps {session.gateway_steps!r} "
            f"do not match generated subcommands {actual_subcommands!r}"
        )
    return steps


def _validate_session(session: EvalSession) -> _CaseRoute:
    if not isinstance(session, EvalSession):
        raise EvalProtocolError("session must be an EvalSession")
    if not session.session_id or not session.pair_id or not session.profile_id:
        raise EvalProtocolError("session identity fields must be non-empty")
    if not session.version or not session.phase:
        raise EvalProtocolError("session version and phase must be non-empty")
    if session.version not in SUPPORTED_VERSIONS:
        raise EvalProtocolError(f"unsupported eval session version: {session.version!r}")

    route = _CASE_ROUTES.get(session.case.id)
    if route is None:
        raise EvalProtocolError(f"unknown v2 case id: {session.case.id!r}")
    if session.case.adapter != route.adapter:
        raise EvalProtocolError(
            f"case {session.case.id!r} adapter must be {route.adapter!r}, "
            f"not {session.case.adapter!r}"
        )
    if session.case.protocol != route.protocol:
        raise EvalProtocolError(
            f"case {session.case.id!r} protocol must be {route.protocol!r}, "
            f"not {session.case.protocol!r}"
        )
    if session.case.operation != route.operation:
        raise EvalProtocolError(
            f"case {session.case.id!r} operation must be {route.operation!r}, "
            f"not {session.case.operation!r}"
        )
    if session.case.variables != route.variables:
        raise EvalProtocolError(
            f"case {session.case.id!r} variables must preserve the closed adapter contract"
        )

    expected_steps = route.phases.get(session.phase)
    if expected_steps is None:
        raise EvalProtocolError(
            f"case {session.case.id!r} does not support phase {session.phase!r}"
        )
    if session.gateway_steps != expected_steps:
        raise EvalProtocolError(
            f"session {session.session_id!r} gateway_steps must be {expected_steps!r}, "
            f"not {session.gateway_steps!r}"
        )
    return route


def _validate_fixture_values(
    session: EvalSession,
    route: _CaseRoute,
    fixture_values: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(fixture_values, Mapping):
        raise EvalProtocolError("fixture_values must be a mapping")
    if not all(isinstance(key, str) for key in fixture_values):
        raise EvalProtocolError("fixture_values keys must be strings")

    allowed = set(route.variables)
    required = allowed - {"wwise_version"}
    if session.phase == "confirm":
        allowed.update(_CONFIRM_RUNTIME_FIELDS)
        required.update(_CONFIRM_RUNTIME_FIELDS)
    supplied = set(fixture_values)
    unknown = sorted(supplied - allowed)
    missing = sorted(required - supplied)
    if unknown:
        raise EvalProtocolError(f"fixture_values contain unknown fields: {unknown}")
    if missing:
        raise EvalProtocolError(f"fixture_values are missing required fields: {missing}")

    values = dict(fixture_values)
    supplied_version = values.get("wwise_version", session.version)
    if supplied_version != session.version:
        raise EvalProtocolError(
            f"fixture_values cannot override version {session.version!r} with {supplied_version!r}"
        )
    values["wwise_version"] = session.version

    falsy = sorted(key for key, value in values.items() if not value)
    if falsy:
        raise EvalProtocolError(f"fixture_values contain falsy fields: {falsy}")
    non_strings = sorted(key for key, value in values.items() if not isinstance(value, str))
    if non_strings:
        raise EvalProtocolError(f"fixture_values contain non-string fields: {non_strings}")
    return values


def _operation_schema_step(route: _CaseRoute) -> ExpectedGatewayStep:
    if not route.operation:
        raise EvalProtocolError("transaction route has no operation")
    return ExpectedGatewayStep(
        name="operation-schema",
        subcommand="operation-schema",
        arguments=(route.operation,),
    )


def _preview_step(
    session: EvalSession,
    route: _CaseRoute,
    values: Mapping[str, Any],
) -> ExpectedGatewayStep:
    if not route.operation:
        raise EvalProtocolError("preview route has no operation")
    try:
        request = session.render_request(values)
    except EvalSuiteError as exc:
        raise EvalProtocolError(f"cannot render closed request: {exc}") from exc
    if set(request) != {"contract", "version", "operation", "arguments"}:
        raise EvalProtocolError("rendered request must preserve the closed operation-request envelope")
    if request["contract"] != OPERATION_REQUEST_CONTRACT:
        raise EvalProtocolError("rendered request has the wrong operation-request contract")
    if request["version"] != session.version:
        raise EvalProtocolError("rendered request version does not match the eval session")
    if request["operation"] != route.operation:
        raise EvalProtocolError("rendered request operation does not match the closed case route")
    if not isinstance(request["arguments"], Mapping) or not request["arguments"]:
        raise EvalProtocolError("rendered request arguments must be a non-empty JSON object")
    return ExpectedGatewayStep(
        name="preview",
        subcommand="preview",
        arguments=("--request-json", SemanticJsonArgument(request)),
    )


def _confirm_steps(
    *,
    transaction_id: str,
) -> tuple[ExpectedGatewayStep, ...]:
    show_name = "transaction-show"
    confirm_name = "confirm"
    execute_name = "execute"
    return (
        ExpectedGatewayStep(
            name=show_name,
            subcommand="transaction-show",
            arguments=(transaction_id, "--summary-only"),
        ),
        ExpectedGatewayStep(
            name=confirm_name,
            subcommand="confirm",
            arguments=(
                ResponseBinding(show_name, "/transaction_id"),
                "--confirmation-token",
                ResponseBinding(show_name, "/confirmation/token"),
            ),
        ),
        ExpectedGatewayStep(
            name=execute_name,
            subcommand="execute",
            arguments=(ResponseBinding(confirm_name, "/transaction_id"),),
        ),
        ExpectedGatewayStep(
            name="verify",
            subcommand="verify",
            arguments=(ResponseBinding(execute_name, "/transaction_id"),),
        ),
    )
