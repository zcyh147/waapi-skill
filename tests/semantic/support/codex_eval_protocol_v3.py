"""Closed broker protocols for one executable V3 heavy scenario.

The scenario adapters own business requests.  This module only translates
those already-closed requests into exact, ordered packaged-gateway steps and
turn-boundary prefix counts for a single fresh Codex task.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_gateway_broker import (
    DraftActionJsonArgument,
    DraftActionResponseBinding,
    ExpectedGatewayStep,
    MetadataBoundJsonArgument,
    MetadataQueryArgument,
    MetadataTokenProjection,
    OBJECT_SET_SCHEMA_DEFAULTS,
    ResponseBinding,
    SemanticJsonArgument,
    validate_commutative_read_only_step_groups,
    validate_operation_draft_protocol_steps,
)


OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
OPERATION_DRAFT_ACTION_CONTRACT = "waapi-skill.operation-draft-action/v1"


class V3ProtocolError(ValueError):
    """A materialized scenario cannot form an exact broker allow-list."""


def build_object_set_composer_transaction_steps(
    request: Mapping[str, Any],
    *,
    label: str,
) -> tuple[ExpectedGatewayStep, ...]:
    """Translate one reviewed flat object.set request into one typed Draft flow."""

    normalized = _validate_operation_request(request)
    if normalized["operation"] != "object.set":
        raise V3ProtocolError("Composer transaction builder requires object.set")
    if not isinstance(label, str) or not re.fullmatch(r"tx[0-9]{2}", label):
        raise V3ProtocolError("Composer transaction label must be txNN")
    arguments = normalized["arguments"]
    objects = arguments.get("objects")
    if not isinstance(objects, list) or not objects:
        raise V3ProtocolError("object.set Composer request requires objects")

    action_specs: list[
        tuple[Mapping[str, Any], DraftActionResponseBinding | None]
    ] = []
    for option_name in (
        "platform",
        "list_mode",
        "on_name_conflict",
        "auto_add_to_source_control",
    ):
        if option_name in arguments:
            default = OBJECT_SET_SCHEMA_DEFAULTS.get(option_name)
            if (
                option_name in OBJECT_SET_SCHEMA_DEFAULTS
                and type(arguments[option_name]) is type(default)
                and arguments[option_name] == default
            ):
                continue
            action_specs.append(
                (
                    {
                        "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                        "action": "set_request_option",
                        "name": option_name,
                        "value": arguments[option_name],
                    },
                    None,
                )
            )
    allowed_request_fields = {
        "objects",
        "platform",
        "list_mode",
        "on_name_conflict",
        "auto_add_to_source_control",
    }
    if set(arguments) - allowed_request_fields:
        raise V3ProtocolError("object.set Composer request fields are not supported")

    action_index = len(action_specs)
    for target_index, raw_target in enumerate(objects):
        if not isinstance(raw_target, Mapping) or not isinstance(
            raw_target.get("object"), Mapping
        ):
            raise V3ProtocolError("object.set Composer target is invalid")
        action_index += 1
        target_step_name = f"{label}.action.{action_index:03d}"
        action_specs.append(
            (
                {
                    "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                    "action": "add_target",
                    "selector": dict(raw_target["object"]),
                },
                None,
            )
        )
        handle_binding = DraftActionResponseBinding(
            pointer="/target_handle",
            step=target_step_name,
            response_pointer=f"/draft/current_facts/{target_index}/handle",
        )
        reference_binding = DraftActionResponseBinding(
            pointer="/owner_handle",
            step=target_step_name,
            response_pointer=f"/draft/current_facts/{target_index}/handle",
        )
        for field_name in (
            "name",
            "notes",
            "platform",
            "list_mode",
            "on_name_conflict",
        ):
            if field_name in raw_target:
                action_specs.append(
                    (
                        {
                            "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                            "action": "set_target_field",
                            "name": field_name,
                            "value": raw_target[field_name],
                        },
                        handle_binding,
                    )
                )
        properties = raw_target.get("properties", [])
        references = raw_target.get("references", [])
        unsupported = set(raw_target) - {
            "object",
            "name",
            "notes",
            "platform",
            "list_mode",
            "on_name_conflict",
            "properties",
            "references",
        }
        if (
            unsupported
            or not isinstance(properties, list)
            or not isinstance(references, list)
        ):
            raise V3ProtocolError("object.set Composer target fields are not supported")
        for row in properties:
            if not isinstance(row, Mapping) or set(row) != {"name", "value"}:
                raise V3ProtocolError("object.set Composer property is invalid")
            action_specs.append(
                (
                    {
                        "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                        "action": "set_property",
                        "name": row["name"],
                        "value": row["value"],
                    },
                    handle_binding,
                )
            )
        for row in references:
            if not isinstance(row, Mapping) or set(row) != {"name", "target"}:
                raise V3ProtocolError("object.set Composer reference is invalid")
            action_specs.append(
                (
                    {
                        "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                        "action": "set_reference",
                        "name": row["name"],
                        "target": row["target"],
                    },
                    reference_binding,
                )
            )
        action_index = len(action_specs)

    steps: list[ExpectedGatewayStep] = [
        ExpectedGatewayStep(
            name=f"{label}.operation-schema",
            subcommand="operation-schema",
            arguments=("object.set",),
        ),
        ExpectedGatewayStep(
            name=f"{label}.draft-start",
            subcommand="draft-start",
            arguments=("object.set",),
        ),
    ]
    latest_revision_step = f"{label}.draft-start"
    for index, (action, handle_binding) in enumerate(action_specs, start=1):
        action_name = f"{label}.action.{index:03d}"
        steps.append(
            ExpectedGatewayStep(
                name=action_name,
                subcommand="draft-apply",
                arguments=(
                    ResponseBinding(f"{label}.draft-start", "/draft/draft_id"),
                    "--task-authority",
                    ResponseBinding(f"{label}.draft-start", "/task_authority"),
                    "--expected-revision",
                    ResponseBinding(latest_revision_step, "/draft/revision"),
                    "--action-json",
                    DraftActionJsonArgument(
                        expected=action,
                        response_bindings=(
                            (handle_binding,) if handle_binding is not None else ()
                        ),
                    ),
                ),
            )
        )
        latest_revision_step = action_name
    check_name = f"{label}.check"
    preview_name = f"{label}.preview"
    show_name = f"{label}.transaction-show"
    confirm_name = f"{label}.confirm"
    execute_name = f"{label}.execute"
    steps.extend(
        (
            ExpectedGatewayStep(
                name=check_name,
                subcommand="draft-check",
                arguments=(
                    ResponseBinding(f"{label}.draft-start", "/draft/draft_id"),
                    "--task-authority",
                    ResponseBinding(f"{label}.draft-start", "/task_authority"),
                    "--expected-revision",
                    ResponseBinding(latest_revision_step, "/draft/revision"),
                ),
            ),
            ExpectedGatewayStep(
                name=preview_name,
                subcommand="preview-from-draft",
                arguments=(
                    ResponseBinding(f"{label}.draft-start", "/draft/draft_id"),
                    "--task-authority",
                    ResponseBinding(f"{label}.draft-start", "/task_authority"),
                    "--expected-revision",
                    ResponseBinding(check_name, "/draft/revision"),
                    "--apply",
                ),
            ),
            ExpectedGatewayStep(
                name=show_name,
                subcommand="transaction-show",
                arguments=(ResponseBinding(preview_name, "/transaction_id"), "--summary-only"),
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
                allowed_exit_codes=(0, 2),
            ),
            ExpectedGatewayStep(
                name=f"{label}.verify",
                subcommand="verify",
                arguments=(ResponseBinding(execute_name, "/transaction_id"),),
            ),
        )
    )
    return tuple(steps)


def metadata_candidate_limit(queries: Sequence[str]) -> int:
    """Return the deterministic per-query candidate budget from the Skill."""

    if isinstance(queries, (str, bytes)):
        raise V3ProtocolError(
            "metadata candidate budget requires a query sequence"
        )
    count = len(tuple(queries))
    if not 1 <= count <= 8:
        raise V3ProtocolError(
            "metadata candidate budget requires 1..8 query phrases"
        )
    return 8 if count <= 2 else 3 if count <= 4 else 2


def operation_request_equivalence(operation: str) -> str:
    """Return the one reviewed JSON equivalence for an operation request."""

    if operation in {"object.create", "object.set"}:
        return "object_operation_v1"
    if operation == "soundbank.generate":
        return "soundbank_generate_v1"
    if operation == "switchContainer.removeAssignment":
        return "switch_container_remove_assignment_v1"
    return "wire_exact"


@dataclass(frozen=True, slots=True)
class V3GatewayProtocol:
    steps: tuple[ExpectedGatewayStep, ...]
    turn_prefix_counts: tuple[int, ...]
    allowed_turn_prefix_counts: tuple[tuple[int, ...], ...] = ()
    terminal_prefix_counts: tuple[int, ...] = ()
    commutative_read_only_step_groups: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("V3GatewayProtocol.steps must be non-empty")
        if not self.turn_prefix_counts:
            raise ValueError("V3GatewayProtocol.turn_prefix_counts must be non-empty")
        if tuple(sorted(self.turn_prefix_counts)) != self.turn_prefix_counts:
            raise ValueError("turn prefix counts must be ordered")
        if (
            not self.allowed_turn_prefix_counts
            and len(set(self.turn_prefix_counts)) != len(self.turn_prefix_counts)
        ):
            raise ValueError("turn prefix counts must be unique")
        if self.turn_prefix_counts[-1] != len(self.steps):
            raise ValueError("final turn prefix must consume the complete protocol")
        if self.allowed_turn_prefix_counts:
            if len(self.allowed_turn_prefix_counts) != len(self.turn_prefix_counts):
                raise ValueError(
                    "allowed turn prefixes must match the turn-boundary count"
                )
            for index, (maximum, allowed) in enumerate(
                zip(
                    self.turn_prefix_counts,
                    self.allowed_turn_prefix_counts,
                    strict=True,
                ),
                start=1,
            ):
                if (
                    not allowed
                    or tuple(sorted(set(allowed))) != allowed
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or not 1 <= value <= maximum
                        for value in allowed
                    )
                    or maximum not in allowed
                ):
                    raise ValueError(
                        f"allowed prefix choices for turn {index} are invalid"
                    )
            terminal = self.terminal_prefix_counts
            if (
                not terminal
                or tuple(sorted(set(terminal))) != terminal
                or any(
                    value not in self.allowed_turn_prefix_counts[-1]
                    for value in terminal
                )
            ):
                raise ValueError(
                    "terminal prefixes must be unique final-turn allowed choices"
                )
        elif self.terminal_prefix_counts:
            raise ValueError(
                "terminal prefixes require explicit allowed turn prefixes"
            )
        names = tuple(step.name for step in self.steps)
        if len(names) != len(set(names)):
            raise ValueError("V3 gateway step names must be unique")
        validate_operation_draft_protocol_steps(self.steps)
        groups = validate_commutative_read_only_step_groups(
            self.steps,
            self.commutative_read_only_step_groups,
        )
        if groups != self.commutative_read_only_step_groups:
            raise ValueError(
                "commutative read-only step groups must use canonical tuples"
            )
        checkpoint_counts = set(self.turn_prefix_counts)
        for allowed in self.allowed_turn_prefix_counts:
            checkpoint_counts.update(allowed)
        indexes = {name: index for index, name in enumerate(names)}
        for first, _second in groups:
            if indexes[first] + 1 in checkpoint_counts:
                raise ValueError(
                    "a commutative read-only group cannot cross a turn prefix"
                )

    def allowed_prefixes_for_turn(self, index: int) -> tuple[int, ...]:
        if not 1 <= index <= len(self.turn_prefix_counts):
            raise IndexError("turn index is outside the protocol")
        if self.allowed_turn_prefix_counts:
            return self.allowed_turn_prefix_counts[index - 1]
        return (self.turn_prefix_counts[index - 1],)

    @property
    def accepted_terminal_prefixes(self) -> tuple[int, ...]:
        if self.terminal_prefix_counts:
            return self.terminal_prefix_counts
        return (len(self.steps),)


@dataclass(frozen=True, slots=True)
class StructuredRefusal:
    error_code: str
    result_command: str = "preview"

    def __post_init__(self) -> None:
        if not self.error_code or not self.error_code.strip():
            raise ValueError("structured refusal error_code must be non-empty")
        if not self.result_command or not self.result_command.strip():
            raise ValueError("structured refusal result_command must be non-empty")


def build_transaction_protocol(
    requests: Sequence[Mapping[str, Any]],
    *,
    refusal: StructuredRefusal | None = None,
    terminal_execute: bool = False,
    request_equivalences: Sequence[str] | None = None,
) -> V3GatewayProtocol:
    """Build one or more separately confirmed immutable transactions.

    A multi-transaction scenario previews the first request on turn one.  Each
    confirmation turn completes only the currently visible transaction and,
    except for the final confirmation, obtains a new schema and preview for the
    next request.  The transaction-show call starts from the exact preview
    transaction id.  Confirmation then binds both its transaction id and its
    short state-scoped token to that show response; execute and verify each bind
    to the immediately preceding response.  No continuation value is guessed
    or injected into the prompt.
    """

    normalized = tuple(_validate_operation_request(request) for request in requests)
    if not normalized:
        raise V3ProtocolError("transaction protocol requires at least one request")
    if refusal is not None and len(normalized) != 1:
        raise V3ProtocolError("a structured refusal supports exactly one preview request")
    if terminal_execute and len(normalized) != 1:
        raise V3ProtocolError(
            "a terminal-execute transaction supports exactly one request"
        )
    if terminal_execute and refusal is not None:
        raise V3ProtocolError(
            "terminal execute and structured preview refusal are mutually exclusive"
        )
    if request_equivalences is None:
        equivalences = tuple(
            operation_request_equivalence(str(request["operation"]))
            for request in normalized
        )
    else:
        equivalences = tuple(request_equivalences)
        if len(equivalences) != len(normalized):
            raise V3ProtocolError(
                "request equivalences must match the transaction request count"
            )
        for request, equivalence in zip(normalized, equivalences, strict=True):
            operation = str(request["operation"])
            default = operation_request_equivalence(operation)
            if equivalence != default and not (
                operation == "audio.import"
                and equivalence == "audio_import_default_operation_v1"
            ):
                raise V3ProtocolError(
                    "request equivalence is not reviewed for the operation"
                )

    steps: list[ExpectedGatewayStep] = []
    prefixes: list[int] = []
    for index, (request, request_equivalence) in enumerate(
        zip(normalized, equivalences, strict=True),
        start=1,
    ):
        label = f"tx{index:02d}"
        operation = str(request["operation"])
        steps.append(
            ExpectedGatewayStep(
                name=f"{label}.operation-schema",
                subcommand="operation-schema",
                arguments=(operation,),
            )
        )
        preview_name = f"{label}.preview"
        steps.append(
            ExpectedGatewayStep(
                name=preview_name,
                subcommand="preview",
                arguments=(
                    "--apply",
                    "--request-json",
                    SemanticJsonArgument(
                        request,
                        equivalence=request_equivalence,
                    ),
                ),
                allowed_exit_codes=(2,) if refusal is not None else (0,),
                expected_error_code=refusal.error_code if refusal is not None else "",
                expected_result_command=(
                    refusal.result_command if refusal is not None else ""
                ),
            )
        )
        if index == 1:
            prefixes.append(len(steps))
        if refusal is not None:
            continue

        preview_transaction_id = ResponseBinding(
            preview_name,
            "/transaction_id",
        )
        show_name = f"{label}.transaction-show"
        confirm_name = f"{label}.confirm"
        execute_name = f"{label}.execute"
        steps.extend(
            (
                ExpectedGatewayStep(
                    name=show_name,
                    subcommand="transaction-show",
                    arguments=(preview_transaction_id, "--summary-only"),
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
                    # Ordinary mutations have two closed outcomes: success
                    # continues to verify, while one exact non-retryable
                    # indeterminate result terminates at execute.  Migration's
                    # terminal_execute flag additionally makes successful
                    # execute terminal because its oracle is caller-owned.
                    allowed_exit_codes=(0, 2),
                    terminal_execute=terminal_execute,
                ),
            )
        )
        if not terminal_execute:
            steps.append(
                ExpectedGatewayStep(
                    name=f"{label}.verify",
                    subcommand="verify",
                    arguments=(ResponseBinding(execute_name, "/transaction_id"),),
                )
            )
        if index == len(normalized):
            prefixes.append(len(steps))
        else:
            # The next loop appends its schema/preview into this same
            # confirmation turn.  Its prefix is recorded after that append.
            continue

    if refusal is not None:
        prefixes = [len(steps)]
    elif terminal_execute:
        prefixes = [2, 5]
    elif len(normalized) > 1:
        # Reconstruct the exact cumulative boundary after every confirmation:
        # initial schema+preview, then four continuation steps plus the next
        # schema+preview, with the final turn ending after four steps.
        prefixes = [2]
        consumed = 2
        for index in range(len(normalized)):
            consumed += 4
            if index + 1 < len(normalized):
                consumed += 2
            prefixes.append(consumed)
    return V3GatewayProtocol(tuple(steps), tuple(prefixes))


def build_metadata_transaction_protocol(
    requests: Sequence[Mapping[str, Any]],
    *,
    object_type: str,
    metadata_queries: Sequence[str],
    required_tokens: Sequence[str],
    expected_required_token_projection: (
        Sequence[MetadataTokenProjection] | None
    ) = None,
    equivalence: str = "wire_exact",
    schema_first: bool = False,
) -> V3GatewayProtocol:
    """Add one live object-type discovery to immutable transactions.

    Suggested query phrases define the fixed number of bounded query slots,
    while the broker accepts natural rephrasing.  Every dynamic token must
    occur in that exact brokered discovery payload.  Requests remain wire-exact
    unless the caller selects one explicitly reviewed metadata-bound
    equivalence.  The default keeps discovery first.  ``schema_first`` is the
    closed object-mutation variant: it exposes the configured adapter version
    before the exact reflected object-type scope must be selected.
    """

    if not requests:
        raise V3ProtocolError(
            "metadata-bound transaction protocol requires at least one operation request"
        )
    if not isinstance(schema_first, bool):
        raise V3ProtocolError("schema_first must be a Boolean")
    if equivalence not in {
        "wire_exact",
        "audio_import_v1",
        "audio_import_tab_v1",
        "object_set_v1",
        "object_set_rtpc_v1",
    }:
        raise V3ProtocolError(
            "metadata-bound equivalence must be wire_exact, "
            "audio_import_v1, audio_import_tab_v1, object_set_v1, "
            "or object_set_rtpc_v1"
        )
    if equivalence == "audio_import_v1" and any(
        request.get("operation") != "audio.import"
        for request in requests
    ):
        raise V3ProtocolError(
            "audio_import_v1 is valid only for audio.import requests"
        )
    if equivalence == "audio_import_tab_v1" and any(
        request.get("operation") != "audio.importTabDelimited"
        for request in requests
    ):
        raise V3ProtocolError(
            "audio_import_tab_v1 is valid only for "
            "audio.importTabDelimited requests"
        )
    if equivalence == "object_set_v1" and any(
        request.get("operation") != "object.set"
        for request in requests
    ):
        raise V3ProtocolError(
            "object_set_v1 is valid only for object.set requests"
        )
    if equivalence == "object_set_rtpc_v1" and any(
        request.get("operation") != "object.setRTPC"
        for request in requests
    ):
        raise V3ProtocolError(
            "object_set_rtpc_v1 is valid only for object.setRTPC requests"
        )
    if (
        not isinstance(object_type, str)
        or not object_type
        or object_type != object_type.strip()
        or len(object_type) > 256
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in object_type
        )
    ):
        raise V3ProtocolError(
            "metadata-bound transaction protocol requires one bounded exact object type"
        )
    if isinstance(metadata_queries, (str, bytes)):
        queries: tuple[Any, ...] = ()
    else:
        queries = tuple(metadata_queries)
    if (
        not 1 <= len(queries) <= 8
        or any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 160
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in value
            )
            for value in queries
        )
        or len({" ".join(value.split()).casefold() for value in queries})
        != len(queries)
        or sum(len(value) for value in queries) > 640
    ):
        raise V3ProtocolError(
            "metadata-bound transaction requires 1..8 distinct bounded query suggestions"
        )
    if isinstance(required_tokens, (str, bytes)):
        tokens: tuple[Any, ...] = ()
    else:
        tokens = tuple(required_tokens)
    if (
        not tokens
        or any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or value.startswith("@")
            or len(value) > 256
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in value
            )
            for value in tokens
        )
        or len(tokens) != len({value.casefold() for value in tokens})
    ):
        raise V3ProtocolError(
            "metadata-bound transaction requires unique exact live tokens"
        )
    projection = (
        None
        if expected_required_token_projection is None
        else tuple(expected_required_token_projection)
    )
    if projection is not None and (
        any(
            not isinstance(item, MetadataTokenProjection)
            for item in projection
        )
        or tuple(item.name for item in projection) != tokens
    ):
        raise V3ProtocolError(
            "expected required-token projection must match required_tokens in order"
        )

    base = build_transaction_protocol(requests)
    metadata_step_name = "metadata.discover"
    metadata_arguments: list[Any] = [
        "discover",
        "--object-type",
        object_type,
    ]
    for query in queries:
        metadata_arguments.extend(
            (
                "--query",
                MetadataQueryArgument(query),
            )
        )
    metadata_arguments.extend(
        ("--limit", str(metadata_candidate_limit(queries)))
    )
    metadata_step = ExpectedGatewayStep(
        name=metadata_step_name,
        subcommand="metadata",
        arguments=tuple(metadata_arguments),
    )
    if schema_first:
        if (
            len(base.steps) < 2
            or base.steps[0].subcommand != "operation-schema"
            or base.steps[1].subcommand != "preview"
        ):
            raise V3ProtocolError(
                "schema-first metadata requires one ordinary transaction prefix"
            )
        steps = [base.steps[0], metadata_step, *base.steps[1:]]
    else:
        steps = [metadata_step, *base.steps]
    for index, step in enumerate(steps):
        if step.subcommand != "preview":
            continue
        if (
            len(step.arguments) != 3
            or step.arguments[:2] != ("--apply", "--request-json")
            or not isinstance(step.arguments[2], SemanticJsonArgument)
        ):
            raise V3ProtocolError(
                "base transaction preview differs from the reviewed shape"
            )
        try:
            bound_argument = MetadataBoundJsonArgument(
                expected=step.arguments[2].expected,
                metadata_step=metadata_step_name,
                object_type=object_type,
                required_tokens=tokens,
                expected_required_token_projection=projection,
                equivalence=equivalence,
            )
        except (TypeError, ValueError) as exc:
            raise V3ProtocolError(
                f"metadata-bound request equivalence is invalid: {exc}"
            ) from exc
        steps[index] = replace(
            step,
            arguments=(
                "--apply",
                "--request-json",
                bound_argument,
            ),
        )
    return V3GatewayProtocol(
        steps=tuple(steps),
        turn_prefix_counts=tuple(value + 1 for value in base.turn_prefix_counts),
    )


def build_schema_query_transaction_protocol(
    requests: Sequence[Mapping[str, Any]],
    *,
    query_step: ExpectedGatewayStep,
) -> V3GatewayProtocol:
    """Require one exact object lookup between schema and preview.

    This narrow form is for a same-name merge whose natural request does not
    state the existing root's exact Wwise type.  The lookup remains a required,
    auditable broker step; it is not an optional discovery allowance.
    """

    if len(requests) != 1:
        raise V3ProtocolError(
            "schema-query transaction requires exactly one operation request"
        )
    if (
        not isinstance(query_step, ExpectedGatewayStep)
        or query_step.subcommand != "query-object"
        or not query_step.name
    ):
        raise V3ProtocolError(
            "schema-query transaction requires one exact query-object step"
        )
    base = build_transaction_protocol(requests)
    if (
        len(base.steps) < 2
        or base.steps[0].subcommand != "operation-schema"
        or base.steps[1].subcommand != "preview"
    ):
        raise V3ProtocolError(
            "schema-query transaction requires one ordinary transaction prefix"
        )
    return V3GatewayProtocol(
        steps=(base.steps[0], query_step, *base.steps[1:]),
        turn_prefix_counts=tuple(value + 1 for value in base.turn_prefix_counts),
    )


def build_direct_protocol(
    steps: Sequence[ExpectedGatewayStep],
) -> V3GatewayProtocol:
    """Build a single-turn exact read/topic protocol supplied by an adapter."""

    values = tuple(steps)
    if not values:
        raise V3ProtocolError("direct protocol requires at least one gateway step")
    return V3GatewayProtocol(values, (len(values),))


def build_modification_policy_protocol(
    base: V3GatewayProtocol,
    *,
    policy: str,
) -> V3GatewayProtocol:
    """Derive one closed mutation protocol for a canonical project policy.

    The input is the already materialized, independently reviewed one-request
    ask-before-changes transaction protocol.  This function changes only the
    policy mechanics: read-only stops after schema without attempting an executable preview,
    ask-before-changes retains the later confirmation turn, and allow-changes
    executes directly from the policy-authorized preview in the same turn.
    """

    if policy not in {"read_only", "ask_before_changes", "allow_changes"}:
        raise V3ProtocolError(
            "modification policy must be read_only, ask_before_changes, or allow_changes"
        )
    if base.turn_prefix_counts != (2, 6) or len(base.steps) != 6:
        raise V3ProtocolError(
            "modification-policy evaluation requires one ordinary transaction"
        )
    (
        operation_schema,
        preview,
        transaction_show,
        confirm,
        execute,
        verify,
    ) = base.steps
    if (
        operation_schema.subcommand != "operation-schema"
        or preview.subcommand != "preview"
        or transaction_show.subcommand != "transaction-show"
        or confirm.subcommand != "confirm"
        or execute.subcommand != "execute"
        or verify.subcommand != "verify"
        or preview.allowed_exit_codes != (0,)
        or len(preview.arguments) != 3
        or preview.arguments[:2] != ("--apply", "--request-json")
        or not isinstance(preview.arguments[2], SemanticJsonArgument)
    ):
        raise V3ProtocolError(
            "base transaction protocol differs from the reviewed six-step shape"
        )
    if policy == "read_only":
        return V3GatewayProtocol(
            steps=(operation_schema,),
            turn_prefix_counts=(1, 1),
            allowed_turn_prefix_counts=((1,), (1,)),
            terminal_prefix_counts=(1,),
        )
    if policy == "ask_before_changes":
        return base

    direct_execute = replace(
        execute,
        arguments=(ResponseBinding(preview.name, "/transaction_id"),),
    )
    direct_verify = replace(
        verify,
        arguments=(ResponseBinding(direct_execute.name, "/transaction_id"),),
    )
    return V3GatewayProtocol(
        steps=(
            operation_schema,
            preview,
            direct_execute,
            direct_verify,
        ),
        turn_prefix_counts=(4,),
    )


def call_step(
    name: str,
    api: str,
    *,
    args: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    post_filter: Mapping[str, Any] | None = None,
) -> ExpectedGatewayStep:
    argument_values = _normalize_json_object(
        {} if args is None else args,
        field="call args",
    )
    option_values = _normalize_json_object(
        {} if options is None else options,
        field="call options",
    )
    gateway_arguments: tuple[Any, ...] = (
        api,
        "--args-json",
        SemanticJsonArgument(argument_values),
        "--options-json",
        SemanticJsonArgument(option_values),
    )
    if post_filter is not None:
        post_filter_value = _normalize_json_object(
            post_filter,
            field="call post filter",
        )
        if not post_filter_value:
            raise V3ProtocolError("call post filter must not be empty")
        gateway_arguments = (
            *gateway_arguments,
            "--post-filter-json",
            SemanticJsonArgument(post_filter_value),
        )
    return ExpectedGatewayStep(
        name=name,
        subcommand="call",
        arguments=gateway_arguments,
        allow_omitted_empty_json_objects=(
            not argument_values and not option_values and post_filter is None
        ),
    )


def query_object_step(name: str, arguments: Sequence[str]) -> ExpectedGatewayStep:
    if not arguments or arguments[0] != "query-object":
        raise V3ProtocolError("query-object arguments must start with the subcommand")
    return ExpectedGatewayStep(
        name=name,
        subcommand="query-object",
        arguments=tuple(arguments[1:]),
    )


def wait_topic_step(
    name: str,
    topic: str,
    *,
    event_count: int,
    match: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    timeout_seconds: float = 120.0,
) -> ExpectedGatewayStep:
    if not isinstance(event_count, int) or isinstance(event_count, bool) or not 1 <= event_count <= 64:
        raise V3ProtocolError("wait-topic event_count must be an integer from 1 through 64")
    if timeout_seconds <= 0:
        raise V3ProtocolError("wait-topic timeout must be positive")
    arguments: list[Any] = [topic]
    if options is not None:
        arguments.extend(
            (
                "--options-json",
                SemanticJsonArgument(
                    _normalize_json_object(options, field="wait-topic options")
                ),
            )
        )
    arguments.extend(("--event-count", str(event_count)))
    if match is not None:
        arguments.extend(
            (
                "--match-json",
                SemanticJsonArgument(
                    _normalize_json_object(match, field="wait-topic match")
                ),
            )
        )
    return ExpectedGatewayStep(
        name=name,
        subcommand="wait-topic",
        gateway_global_arguments=("--timeout", _format_timeout(timeout_seconds)),
        arguments=tuple(arguments),
        allow_omitted_default_event_count_one=event_count == 1,
    )


def _validate_operation_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise V3ProtocolError("operation request must be a mapping")
    result = _normalize_json_object(request, field="operation request")
    if set(result) != {"contract", "version", "operation", "arguments"}:
        raise V3ProtocolError("operation request must use the closed v1 envelope")
    if result["contract"] != OPERATION_REQUEST_CONTRACT:
        raise V3ProtocolError("operation request contract is invalid")
    if not isinstance(result["version"], str) or not result["version"]:
        raise V3ProtocolError("operation request version must be non-empty")
    if not isinstance(result["operation"], str) or not result["operation"]:
        raise V3ProtocolError("operation request operation must be non-empty")
    if not isinstance(result["arguments"], Mapping) or not result["arguments"]:
        raise V3ProtocolError("operation request arguments must be a non-empty mapping")
    return result


def _normalize_json_object(value: Any, *, field: str) -> dict[str, Any]:
    """Copy one protocol-owned object into strict, recursively plain JSON.

    Reviewed V3 builders freeze data with mapping proxies and tuples.  Broker
    allow-list values must instead be directly serializable by the broker's
    unchanged canonical JSON encoder.  Reject unknown values and malformed
    object keys here, at protocol construction, rather than during a live
    model command.
    """

    if not isinstance(value, Mapping):
        raise V3ProtocolError(f"{field} must be a mapping")
    try:
        normalized = _normalize_json_value(value, field=field, active=set())
        if not isinstance(normalized, dict):  # defensive for runtime callers
            raise V3ProtocolError(f"{field} must normalize to a JSON object")
        json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except V3ProtocolError:
        raise
    except Exception as exc:  # noqa: BLE001 - input mappings must fail as protocol data
        raise V3ProtocolError(f"{field} is not canonical JSON: {exc}") from exc
    return normalized


def _normalize_json_value(
    value: Any,
    *,
    field: str,
    active: set[int],
) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise V3ProtocolError(f"{field} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise V3ProtocolError(f"{field} contains a recursive object")
        active.add(identity)
        try:
            result: dict[str, Any] = {}
            for key, nested in value.items():
                if type(key) is not str:
                    raise V3ProtocolError(
                        f"{field} contains a non-string object key"
                    )
                if key in result:
                    raise V3ProtocolError(
                        f"{field} contains a duplicate object key {key!r}"
                    )
                result[key] = _normalize_json_value(
                    nested,
                    field=f"{field}[{key!r}]",
                    active=active,
                )
            return result
        finally:
            active.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            raise V3ProtocolError(f"{field} contains a recursive array")
        active.add(identity)
        try:
            return [
                _normalize_json_value(
                    nested,
                    field=f"{field}[{index}]",
                    active=active,
                )
                for index, nested in enumerate(value)
            ]
        finally:
            active.remove(identity)
    raise V3ProtocolError(
        f"{field} contains non-JSON value {type(value).__name__}"
    )


def _format_timeout(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


__all__ = [
    "StructuredRefusal",
    "V3GatewayProtocol",
    "V3ProtocolError",
    "build_direct_protocol",
    "build_object_set_composer_transaction_steps",
    "build_modification_policy_protocol",
    "build_metadata_transaction_protocol",
    "build_schema_query_transaction_protocol",
    "build_transaction_protocol",
    "call_step",
    "metadata_candidate_limit",
    "operation_request_equivalence",
    "query_object_step",
    "wait_topic_step",
]
