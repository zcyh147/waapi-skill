from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from tests.semantic.support.codex_eval_protocol_v3 import (
    StructuredRefusal,
    V3ProtocolError,
    build_direct_protocol,
    build_transaction_protocol,
    call_step,
    wait_topic_step,
)
from tests.semantic.support.codex_gateway_broker import (
    CodexGatewayBroker,
    ResponseBinding,
    SemanticJsonArgument,
    resolve_gateway_invocation,
)


def _request(index: int = 1) -> dict[str, object]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.create",
        "arguments": {"parent": {"kind": "path", "value": "\\Root"}, "name": f"N{index}", "type": "Sound"},
    }


def test_single_transaction_spans_two_turn_prefixes_with_response_bindings() -> None:
    protocol = build_transaction_protocol([_request()])

    assert protocol.turn_prefix_counts == (2, 6)
    assert tuple(step.subcommand for step in protocol.steps) == (
        "operation-schema",
        "preview",
        "transaction-show",
        "confirm",
        "execute",
        "verify",
    )
    assert protocol.steps[4].allowed_exit_codes == (0, 2)
    assert protocol.steps[4].terminal_execute is False
    assert protocol.steps[5].allowed_exit_codes == (0,)
    assert protocol.steps[2].arguments == (
        ResponseBinding("tx01.preview", "/transaction_id"),
        "--summary-only",
    )
    assert protocol.steps[3].arguments == (
        ResponseBinding("tx01.transaction-show", "/transaction_id"),
        "--confirmation-token",
        ResponseBinding("tx01.transaction-show", "/confirmation/token"),
    )
    assert protocol.steps[4].arguments == (
        ResponseBinding("tx01.confirm", "/transaction_id"),
    )
    assert protocol.steps[5].arguments == (
        ResponseBinding("tx01.execute", "/transaction_id"),
    )
    assert protocol.steps[1].arguments[:2] == ("--apply", "--request-json")
    request_argument = protocol.steps[1].arguments[2]
    assert isinstance(request_argument, SemanticJsonArgument)
    assert request_argument.equivalence == "object_operation_v1"


def test_non_object_transaction_request_keeps_wire_exact_json() -> None:
    request = {
        **_request(),
        "operation": "audio.import",
        "arguments": {"imports": []},
    }

    protocol = build_transaction_protocol([request])

    assert protocol.steps[1].arguments[:2] == ("--apply", "--request-json")
    request_argument = protocol.steps[1].arguments[2]
    assert isinstance(request_argument, SemanticJsonArgument)
    assert request_argument.equivalence == "wire_exact"


def test_three_transactions_preserve_four_natural_turn_boundaries() -> None:
    protocol = build_transaction_protocol([_request(1), _request(2), _request(3)])

    assert protocol.turn_prefix_counts == (2, 8, 14, 18)
    assert len(protocol.steps) == 18
    assert [step.name for step in protocol.steps if step.subcommand == "preview"] == [
        "tx01.preview",
        "tx02.preview",
        "tx03.preview",
    ]
    for index in range(1, 4):
        label = f"tx{index:02d}"
        by_name = {step.name: step for step in protocol.steps}
        assert by_name[f"{label}.confirm"].arguments == (
            ResponseBinding(f"{label}.transaction-show", "/transaction_id"),
            "--confirmation-token",
            ResponseBinding(f"{label}.transaction-show", "/confirmation/token"),
        )
        assert by_name[f"{label}.execute"].arguments == (
            ResponseBinding(f"{label}.confirm", "/transaction_id"),
        )
        assert by_name[f"{label}.verify"].arguments == (
            ResponseBinding(f"{label}.execute", "/transaction_id"),
        )


def test_structured_refusal_is_one_turn_and_exact_exit_two() -> None:
    protocol = build_transaction_protocol(
        [_request()], refusal=StructuredRefusal("INPUT_FILE_NOT_FOUND")
    )

    assert protocol.turn_prefix_counts == (2,)
    assert protocol.steps[-1].allowed_exit_codes == (2,)
    assert protocol.steps[-1].expected_error_code == "INPUT_FILE_NOT_FOUND"
    assert protocol.steps[-1].expected_result_command == "preview"


def test_terminal_execute_transaction_ends_at_execute_without_verify() -> None:
    protocol = build_transaction_protocol([_request()], terminal_execute=True)

    assert protocol.turn_prefix_counts == (2, 5)
    assert tuple(step.subcommand for step in protocol.steps) == (
        "operation-schema",
        "preview",
        "transaction-show",
        "confirm",
        "execute",
    )
    assert protocol.steps[-1].allowed_exit_codes == (0, 2)
    assert protocol.steps[-1].terminal_execute is True


def test_terminal_execute_rejects_multi_request_or_refusal_combinations() -> None:
    with pytest.raises(V3ProtocolError, match="exactly one"):
        build_transaction_protocol(
            [_request(1), _request(2)], terminal_execute=True
        )
    with pytest.raises(V3ProtocolError, match="mutually exclusive"):
        build_transaction_protocol(
            [_request()],
            refusal=StructuredRefusal("INPUT_FILE_NOT_FOUND"),
            terminal_execute=True,
        )


def test_direct_call_and_topic_protocols_are_single_turn() -> None:
    protocol = build_direct_protocol(
        [
            call_step("fields", "ak.wwise.core.mediaPool.getFields"),
            wait_topic_step(
                "generated",
                "ak.wwise.core.soundbank.generated",
                event_count=4,
                match={"platform": "Windows"},
            ),
        ]
    )
    assert protocol.turn_prefix_counts == (2,)
    assert protocol.steps[0].allow_omitted_empty_json_objects is True
    assert protocol.steps[1].gateway_global_arguments == ("--timeout", "120")
    assert protocol.steps[1].allow_omitted_default_event_count_one is False


def test_wait_topic_allows_omitted_event_count_only_for_the_default_one() -> None:
    default_step = wait_topic_step(
        "one",
        "ak.wwise.core.soundbank.generated",
        event_count=1,
    )
    multiple_step = wait_topic_step(
        "multiple",
        "ak.wwise.core.soundbank.generated",
        event_count=2,
    )

    assert default_step.allow_omitted_default_event_count_one is True
    assert multiple_step.allow_omitted_default_event_count_one is False


def test_call_step_deeply_normalizes_frozen_json_for_broker_validation(
    tmp_path: Path,
) -> None:
    args = MappingProxyType(
        {
            "from": MappingProxyType(
                {"path": ("\\Interactive Music Hierarchy", "\\Events")}
            ),
            "filters": (
                MappingProxyType({"field": "type", "values": ("MusicSegment",)}),
            ),
        }
    )
    options = MappingProxyType({"return": ("id", "name", "path")})

    step = call_step(
        "object.get",
        "ak.wwise.core.object.get",
        args=args,
        options=options,
    )
    expected_args = step.arguments[2]
    expected_options = step.arguments[4]
    assert isinstance(expected_args, SemanticJsonArgument)
    assert isinstance(expected_options, SemanticJsonArgument)
    assert type(expected_args.expected) is dict
    assert type(expected_args.expected["from"]) is dict
    assert type(expected_args.expected["from"]["path"]) is list
    assert type(expected_args.expected["filters"]) is list
    assert type(expected_args.expected["filters"][0]) is dict
    assert type(expected_args.expected["filters"][0]["values"]) is list
    assert type(expected_options.expected["return"]) is list
    json.dumps(expected_args.expected, allow_nan=False, sort_keys=True)
    json.dumps(expected_options.expected, allow_nan=False, sort_keys=True)

    skill_source = tmp_path / "waapi-skill"
    broker = CodexGatewayBroker(
        skill_source=skill_source,
        expected_steps=(step,),
    )
    gateway_arguments = (
        "call",
        "ak.wwise.core.object.get",
        "--args-json",
        json.dumps(expected_args.expected, separators=(",", ":")),
        "--options-json",
        json.dumps(expected_options.expected, separators=(",", ":")),
    )
    resolved = resolve_gateway_invocation(
        (
            "python",
            str(skill_source.resolve() / "scripts" / "run.py"),
            "gateway.py",
            *gateway_arguments,
        ),
        skill_source=skill_source,
    )

    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        step,
        resolved.gateway_arguments,
    )
    assert len(semantic_hash) == 64
    assert execution_arguments == gateway_arguments


def test_call_step_appends_closed_post_filter_json_for_media_pool(
    tmp_path: Path,
) -> None:
    step = call_step(
        "media.get",
        "ak.wwise.core.mediaPool.get",
        args={"maxResults": 200},
        options={"return": ["Filename"]},
        post_filter=MappingProxyType(
            {
                "field": "Filename",
                "operator": "containsCaseSensitive",
                "value": "footstep",
                "limit": 20,
            }
        ),
    )

    assert step.arguments[-2] == "--post-filter-json"
    assert isinstance(step.arguments[-1], SemanticJsonArgument)
    assert step.arguments[-1].expected == {
        "field": "Filename",
        "operator": "containsCaseSensitive",
        "value": "footstep",
        "limit": 20,
    }
    assert step.allow_omitted_empty_json_objects is False

    skill_source = tmp_path / "waapi-skill"
    broker = CodexGatewayBroker(
        skill_source=skill_source,
        expected_steps=(step,),
    )
    gateway_arguments = (
        "call",
        "ak.wwise.core.mediaPool.get",
        "--args-json",
        '{"maxResults":200}',
        "--options-json",
        '{"return":["Filename"]}',
        "--post-filter-json",
        json.dumps(step.arguments[-1].expected, separators=(",", ":")),
    )
    resolved = resolve_gateway_invocation(
        (
            "python",
            str(skill_source.resolve() / "scripts" / "run.py"),
            "gateway.py",
            *gateway_arguments,
        ),
        skill_source=skill_source,
    )
    _semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        step,
        resolved.gateway_arguments,
    )
    assert execution_arguments == gateway_arguments

    with pytest.raises(V3ProtocolError, match="must not be empty"):
        call_step(
            "bad",
            "ak.wwise.core.mediaPool.get",
            post_filter={},
        )


def test_wait_topic_and_operation_requests_deeply_normalize_frozen_json() -> None:
    topic_step = wait_topic_step(
        "generated",
        "ak.wwise.core.soundbank.generated",
        event_count=2,
        match=MappingProxyType(
            {"platform": MappingProxyType({"name": ("Windows", "Mac")})}
        ),
        options=MappingProxyType({"return": ("id", "path")}),
    )
    topic_options = topic_step.arguments[2]
    topic_match = topic_step.arguments[6]
    assert isinstance(topic_options, SemanticJsonArgument)
    assert isinstance(topic_match, SemanticJsonArgument)
    assert topic_options.expected == {"return": ["id", "path"]}
    assert topic_match.expected == {
        "platform": {"name": ["Windows", "Mac"]}
    }

    request = MappingProxyType(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": "2022.1",
            "operation": "object.create",
            "arguments": MappingProxyType(
                {
                    "objects": (
                        MappingProxyType(
                            {"name": "Music_A", "type": "MusicSegment"}
                        ),
                        MappingProxyType(
                            {"name": "Music_B", "type": "MusicSegment"}
                        ),
                    )
                }
            ),
        }
    )
    protocol = build_transaction_protocol((request,))
    assert protocol.steps[1].arguments[:2] == ("--apply", "--request-json")
    preview_request = protocol.steps[1].arguments[2]
    assert isinstance(preview_request, SemanticJsonArgument)
    assert type(preview_request.expected) is dict
    assert type(preview_request.expected["arguments"]) is dict
    assert type(preview_request.expected["arguments"]["objects"]) is list
    assert all(
        type(item) is dict
        for item in preview_request.expected["arguments"]["objects"]
    )
    json.dumps(preview_request.expected, allow_nan=False, sort_keys=True)


@pytest.mark.parametrize(
    "invalid",
    (
        {1: "non-string-key"},
        {"value": object()},
        {"value": {"unordered"}},
        {"value": float("nan")},
        {"value": float("inf")},
    ),
    ids=("key", "object", "set", "nan", "infinity"),
)
def test_call_step_rejects_values_outside_closed_json(invalid) -> None:
    with pytest.raises(V3ProtocolError):
        call_step("bad", "ak.wwise.core.object.get", args=invalid)


def test_protocol_entry_points_reject_wrong_container_types_and_cycles() -> None:
    with pytest.raises(V3ProtocolError, match="call args must be a mapping"):
        call_step("bad", "ak.wwise.core.object.get", args=[])  # type: ignore[arg-type]

    with pytest.raises(V3ProtocolError, match="non-string object key"):
        wait_topic_step(
            "bad",
            "ak.wwise.core.object.created",
            event_count=1,
            match={False: "not-json"},  # type: ignore[dict-item]
        )

    cyclic: list[object] = []
    cyclic.append(cyclic)
    request = _request()
    request["arguments"] = {"cycle": cyclic}
    with pytest.raises(V3ProtocolError, match="recursive array"):
        build_transaction_protocol((request,))


def test_rejects_open_or_empty_request() -> None:
    with pytest.raises(V3ProtocolError, match="closed v1 envelope"):
        build_transaction_protocol([{"operation": "object.create"}])
