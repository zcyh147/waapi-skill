from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.semantic.support.codex_eval_protocol import (
    EvalProtocolError,
    build_expected_gateway_steps,
)
from tests.semantic.support.codex_eval_suite import EvalSession, load_eval_suite
from tests.semantic.support.codex_gateway_broker import (
    ResponseBinding,
    SemanticJsonArgument,
)
from wwise_waapi.topic_business import topic_business_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_V2 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "evals-v2.json"

FIXTURES: dict[str, dict[str, Any]] = {
    "Q1": {"query_path": r"\Actor-Mixer Hierarchy\Default Work Unit\QueryTarget"},
    "Q2": {"parent_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Parent"},
    "Q3": {"search_name": "WAAPI_SEM_UNIQUE_NAME"},
    "Q4": {"query_path": r"\Queries\Factory Queries\Sound = SFX"},
    "Q5": {"missing_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Missing"},
    "C1": {},
    "M1": {
        "target_path": r"\Actor-Mixer Hierarchy\Default Work Unit\NotesTarget",
        "notes_value": "semantic notes",
    },
    "M2": {
        "target_path": r"\Actor-Mixer Hierarchy\Default Work Unit\AdversarialTarget",
        "notes_value": "must still preview",
    },
    "M3": {
        "create_parent_path": r"\Actor-Mixer Hierarchy\Default Work Unit",
        "create_name": "CreateTarget",
        "create_notes": "create notes",
    },
    "M4": {"delete_target_path": r"\Actor-Mixer Hierarchy\Default Work Unit\DeleteTarget"},
    "M5": {
        "rename_target_path": r"\Actor-Mixer Hierarchy\Default Work Unit\RenameTarget",
        "rename_value": "RenamedTarget",
    },
    "M6": {"property_target_path": r"\Actor-Mixer Hierarchy\Default Work Unit\PropertyTarget"},
    "M7": {
        "reference_source_path": r"\Actor-Mixer Hierarchy\Default Work Unit\ReferenceSource",
        "reference_target_path": r"\Switches\Default Work Unit\ReferenceTarget",
    },
    "B1": {},
    "B2": {},
    "B3": {},
    "B4": {},
    "B5": {},
    "B6": {},
    "B7": {},
    "I1": {
        "audio_file": "/private/fixtures/semantic.wav",
        "import_object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\ImportedSound",
        "import_object_type": "Sound",
        "import_notes": "semantic import",
    },
    "S1": {
        "soundbank_path": r"\SoundBanks\Default Work Unit\SemanticBank",
        "included_object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\IncludedObject",
    },
    "W1": {
        "switch_container_path": r"\Actor-Mixer Hierarchy\Default Work Unit\SwitchContainer",
        "child_path": r"\Actor-Mixer Hierarchy\Default Work Unit\SwitchChild",
        "state_or_switch_path": r"\Switches\Default Work Unit\Mode\On",
    },
    "W2": {
        "remove_switch_container_path": r"\Actor-Mixer Hierarchy\Default Work Unit\RemoveContainer",
        "remove_child_path": r"\Actor-Mixer Hierarchy\Default Work Unit\RemoveContainer\Child",
        "remove_state_or_switch_path": r"\Switches\Default Work Unit\Mode\On",
    },
    "R1": {},
    "R2": {},
    "R3": {},
    "R4": {},
    "R5": {
        "topic_probe_name": "WAAPI_SEM_TOPIC_2022_1_deadbeef1234",
        "topic_probe_event_type": "ActorMixer",
    },
    "R6": {},
}
CONFIRM_RUNTIME = {
    "transaction_id": "tx-from-trusted-preview",
    "preview_hash": "sha256-from-trusted-preview",
}


def screening_sessions() -> tuple[EvalSession, ...]:
    return load_eval_suite(EVALS_V2).expand_profile("screening")


@pytest.mark.parametrize(
    ("case_id", "phase", "expected"),
    [
        ("Q1", "single", ("query-object",)),
        ("Q2", "single", ("query-object",)),
        ("Q3", "single", ("query-object",)),
        ("Q4", "single", ("query-object",)),
        ("Q5", "single", ("query-object",)),
        ("C1", "single", ("capabilities",)),
        ("M1", "preview", ("operation-schema", "preview")),
        ("M1", "confirm", ("transaction-show", "confirm", "execute", "verify")),
        ("M2", "single", ("operation-schema", "preview")),
        *((case_id, phase, expected) for case_id in ("M3", "M4", "M5", "M6", "M7") for phase, expected in (("preview", ("operation-schema", "preview")), ("confirm", ("transaction-show", "confirm", "execute", "verify")))),
        *((case_id, "single", ("operation-schema",)) for case_id in ("B1", "B2", "B3", "B4", "B5", "B6", "B7")),
        ("I1", "preview", ("operation-schema", "preview")),
        ("I1", "confirm", ("transaction-show", "confirm", "execute", "verify")),
        ("S1", "preview", ("operation-schema", "preview")),
        ("S1", "confirm", ("transaction-show", "confirm", "execute", "verify")),
        ("W1", "preview", ("operation-schema", "preview")),
        ("W1", "confirm", ("transaction-show", "confirm", "execute", "verify")),
        ("W2", "preview", ("operation-schema", "preview")),
        ("W2", "confirm", ("transaction-show", "confirm", "execute", "verify")),
        ("R1", "single", ("status",)),
        ("R2", "single", ("buses",)),
        ("R3", "single", ("selected",)),
        ("R4", "single", ("metadata",)),
        ("R5", "single", ("topic-schema", "wait-topic")),
        ("R6", "single", ("call",)),
    ],
)
def test_all_cases_and_every_phase_generate_exact_subcommand_order(
    case_id: str,
    phase: str,
    expected: tuple[str, ...],
) -> None:
    session = next(
        item for item in screening_sessions() if item.case.id == case_id and item.phase == phase
    )

    values = {
        **FIXTURES[case_id],
        **(CONFIRM_RUNTIME if phase == "confirm" else {}),
    }
    steps = build_expected_gateway_steps(session, values)

    assert tuple(step.name for step in steps) == expected
    assert tuple(step.subcommand for step in steps) == expected
    assert tuple(step.subcommand for step in steps) == session.gateway_steps


def test_q1_uses_exact_path_and_fixed_identity_return_fields() -> None:
    session = next(item for item in screening_sessions() if item.case.id == "Q1")

    step = build_expected_gateway_steps(session, FIXTURES["Q1"])[0]

    assert step.arguments == (
        "--path",
        FIXTURES["Q1"]["query_path"],
        "--return-field",
        "id",
        "--return-field",
        "name",
        "--return-field",
        "type",
        "--return-field",
        "path",
    )


@pytest.mark.parametrize(
    ("case_id", "expected_prefix"),
    [
        (
            "Q2",
            (
                "--path",
                FIXTURES["Q2"]["parent_path"],
                "--select",
                "children",
                "--take",
                "10",
            ),
        ),
        (
            "Q3",
            (
                "--search",
                FIXTURES["Q3"]["search_name"],
                "--where-json",
                '{"field":"name","operator":"=","value":"WAAPI_SEM_UNIQUE_NAME"}',
                "--take",
                "1",
            ),
        ),
        (
            "Q4",
            ("--query", FIXTURES["Q4"]["query_path"], "--take", "10"),
        ),
        ("Q5", ("--path", FIXTURES["Q5"]["missing_path"])),
    ],
)
def test_q2_to_q5_use_closed_bounded_query_argv(
    case_id: str,
    expected_prefix: tuple[str, ...],
) -> None:
    session = next(item for item in screening_sessions() if item.case.id == case_id)

    arguments = build_expected_gateway_steps(session, FIXTURES[case_id])[0].arguments

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
    assert arguments == (*expected_prefix, *identity_fields)
    if case_id in {"Q2", "Q3", "Q4"}:
        assert "--take" in arguments
    else:
        assert "--take" not in arguments


def test_c1_uses_only_all_versions_summary_capability_flags() -> None:
    session = next(item for item in screening_sessions() if item.case.id == "C1")

    step = build_expected_gateway_steps(session, {})[0]

    assert step.arguments == ("--all-versions", "--summary-only")


def test_fixed_read_cases_bind_exact_packaged_arguments() -> None:
    sessions = {item.case.id: item for item in screening_sessions() if item.case.id.startswith("R")}

    assert build_expected_gateway_steps(sessions["R1"], {})[0].arguments == ()
    assert build_expected_gateway_steps(sessions["R2"], {})[0].arguments == ()
    assert build_expected_gateway_steps(sessions["R3"], {})[0].arguments == ()
    assert build_expected_gateway_steps(sessions["R4"], {})[0].arguments == (
        "types",
        "--summary-only",
    )
    schema, topic = build_expected_gateway_steps(sessions["R5"], FIXTURES["R5"])
    assert schema.arguments == ("ak.wwise.core.object.created",)
    assert topic.gateway_global_arguments == ("--timeout", "10")
    assert topic.arguments[:3] == (
        "ak.wwise.core.object.created",
        "--topic-contract-digest",
        topic_business_contract(
            "2022.1", "ak.wwise.core.object.created"
        ).contract_digest,
    )
    assert topic.arguments[3:] == (
        "--topic-option", "include", "id",
        "--topic-option", "include", "name",
        "--topic-option", "include", "type",
        "--topic-option", "include", "path",
        "--event-match", "object-type", FIXTURES["R5"]["topic_probe_event_type"],
    )
    reflection = build_expected_gateway_steps(sessions["R6"], {})[0]
    assert reflection.arguments[:2] == (
        "ak.wwise.waapi.getFunctions",
        "--args-json",
    )
    assert isinstance(reflection.arguments[2], SemanticJsonArgument)
    assert reflection.arguments[2].expected == {}
    assert reflection.arguments[3] == "--options-json"
    assert isinstance(reflection.arguments[4], SemanticJsonArgument)
    assert reflection.arguments[4].expected == {}
    assert reflection.allow_omitted_empty_json_objects is True


@pytest.mark.parametrize("case_id", ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "I1", "S1", "W1", "W2"])
def test_preview_wraps_the_exact_rendered_request_as_semantic_json(case_id: str) -> None:
    session = next(
        item
        for item in screening_sessions()
        if item.case.id == case_id and item.phase in {"preview", "single"}
    )

    schema, preview = build_expected_gateway_steps(session, FIXTURES[case_id])

    assert schema.arguments == (session.case.operation,)
    assert preview.arguments[0] == "--request-json"
    semantic = preview.arguments[1]
    assert isinstance(semantic, SemanticJsonArgument)
    assert semantic.expected == session.render_request(FIXTURES[case_id])
    assert semantic.expected is not session.case.request_template


@pytest.mark.parametrize(
    ("case_id", "identity_paths"),
    [
        ("M1", (("object", "target_path"),)),
        ("M2", (("object", "target_path"),)),
        ("M3", (("parent", "create_parent_path"),)),
        ("M4", (("object", "delete_target_path"),)),
        ("M5", (("object", "rename_target_path"),)),
        ("M6", (("object", "property_target_path"),)),
        ("M7", (("object", "reference_source_path"), ("target", "reference_target_path"))),
        ("S1", (("soundbank", "soundbank_path"),)),
        (
            "W1",
            (
                ("switch_container", "switch_container_path"),
                ("child", "child_path"),
                ("state_or_switch", "state_or_switch_path"),
            ),
        ),
        (
            "W2",
            (
                ("switch_container", "remove_switch_container_path"),
                ("child", "remove_child_path"),
                ("state_or_switch", "remove_state_or_switch_path"),
            ),
        ),
    ],
)
def test_transaction_requests_use_only_prompt_visible_path_identities(
    case_id: str,
    identity_paths: tuple[tuple[str, str], ...],
) -> None:
    session = next(
        item
        for item in screening_sessions()
        if item.case.id == case_id and item.phase in {"preview", "single"}
    )
    request = session.render_request(FIXTURES[case_id])

    for argument_name, fixture_name in identity_paths:
        assert request["arguments"][argument_name] == {
            "kind": "path",
            "value": FIXTURES[case_id][fixture_name],
        }


def test_soundbank_inclusion_object_uses_prompt_visible_path_identity() -> None:
    session = next(
        item
        for item in screening_sessions()
        if item.case.id == "S1" and item.phase == "preview"
    )
    request = session.render_request(FIXTURES["S1"])

    assert request["arguments"]["inclusions"][0]["object"] == {
        "kind": "path",
        "value": FIXTURES["S1"]["included_object_path"],
    }


def test_removed_hidden_guid_fixture_fields_fail_closed() -> None:
    session = next(
        item
        for item in screening_sessions()
        if item.case.id == "M1" and item.phase == "preview"
    )

    with pytest.raises(EvalProtocolError, match="unknown fields"):
        build_expected_gateway_steps(
            session,
            {**FIXTURES["M1"], "target_id": "{hidden-guid}"},
        )


@pytest.mark.parametrize("case_id", ("B1", "B2", "B3", "B4", "B5", "B6", "B7"))
def test_boundaries_report_only_the_packaged_operation_schema(case_id: str) -> None:
    session = next(item for item in screening_sessions() if item.case.id == case_id)

    steps = build_expected_gateway_steps(session, {})

    assert len(steps) == 1
    assert steps[0].arguments == (session.case.operation,)


@pytest.mark.parametrize("case_id", ["M1", "M3", "M4", "M5", "M6", "M7", "I1", "S1", "W1", "W2"])
def test_confirm_uses_runner_transaction_then_strict_response_binding_chain(
    case_id: str,
) -> None:
    session = next(
        item for item in screening_sessions() if item.case.id == case_id and item.phase == "confirm"
    )

    show, confirm, execute, verify = build_expected_gateway_steps(
        session,
        {**FIXTURES[case_id], **CONFIRM_RUNTIME},
    )

    assert show.arguments == (CONFIRM_RUNTIME["transaction_id"], "--summary-only")
    assert confirm.arguments == (
        ResponseBinding("transaction-show", "/transaction_id"),
        "--confirmation-token",
        ResponseBinding("transaction-show", "/confirmation/token"),
    )
    assert execute.arguments == (
        ResponseBinding("confirm", "/transaction_id"),
    )
    assert verify.arguments == (
        ResponseBinding("execute", "/transaction_id"),
    )


def test_matching_explicit_version_and_confirm_runtime_values_are_closed() -> None:
    session = next(
        item
        for item in screening_sessions()
        if item.case.id == "M1" and item.phase == "confirm"
    )

    steps = build_expected_gateway_steps(
        session,
        {
            **FIXTURES["M1"],
            **CONFIRM_RUNTIME,
            "wwise_version": session.version,
        },
    )

    assert steps[0].arguments == (CONFIRM_RUNTIME["transaction_id"], "--summary-only")
    with pytest.raises(EvalProtocolError, match="unknown fields"):
        build_expected_gateway_steps(
            session,
            {**FIXTURES["M1"], **CONFIRM_RUNTIME, "rogue_runtime": "value"},
        )


def test_preview_session_rejects_confirm_runtime_artifacts() -> None:
    session = next(
        item
        for item in screening_sessions()
        if item.case.id == "M1" and item.phase == "preview"
    )

    with pytest.raises(EvalProtocolError, match="unknown fields"):
        build_expected_gateway_steps(
            session,
            {**FIXTURES["M1"], **CONFIRM_RUNTIME},
        )


@pytest.mark.parametrize("missing", ["transaction_id", "preview_hash"])
def test_confirm_requires_both_runner_extracted_preview_artifacts(missing: str) -> None:
    session = next(
        item
        for item in screening_sessions()
        if item.case.id == "M1" and item.phase == "confirm"
    )
    runtime = dict(CONFIRM_RUNTIME)
    runtime.pop(missing)

    with pytest.raises(EvalProtocolError, match="missing required"):
        build_expected_gateway_steps(session, {**FIXTURES["M1"], **runtime})


@pytest.mark.parametrize("field", ["transaction_id", "preview_hash"])
def test_confirm_rejects_falsy_runner_extracted_preview_artifacts(field: str) -> None:
    session = next(
        item
        for item in screening_sessions()
        if item.case.id == "M1" and item.phase == "confirm"
    )

    with pytest.raises(EvalProtocolError, match="falsy fields"):
        build_expected_gateway_steps(
            session,
            {**FIXTURES["M1"], **CONFIRM_RUNTIME, field: ""},
        )


@pytest.mark.parametrize("bad_value", [None, "", False, 0, [], {}])
def test_missing_unknown_and_falsy_fixture_values_fail_closed(bad_value: Any) -> None:
    session = next(item for item in screening_sessions() if item.case.id == "Q1")

    with pytest.raises(EvalProtocolError, match="missing required"):
        build_expected_gateway_steps(session, {})
    with pytest.raises(EvalProtocolError, match="unknown fields"):
        build_expected_gateway_steps(session, {**FIXTURES["Q1"], "rogue": "value"})
    with pytest.raises(EvalProtocolError, match="falsy fields"):
        build_expected_gateway_steps(session, {"query_path": bad_value})


@pytest.mark.parametrize(
    ("case_id", "required_field"),
    [
        ("Q2", "parent_path"),
        ("Q3", "search_name"),
        ("Q4", "query_path"),
        ("Q5", "missing_path"),
    ],
)
def test_new_query_adapters_reject_missing_extra_and_non_string_values(
    case_id: str,
    required_field: str,
) -> None:
    session = next(item for item in screening_sessions() if item.case.id == case_id)

    with pytest.raises(EvalProtocolError, match="missing required"):
        build_expected_gateway_steps(session, {})
    with pytest.raises(EvalProtocolError, match="unknown fields"):
        build_expected_gateway_steps(
            session,
            {**FIXTURES[case_id], "discovery_command": "forbidden"},
        )
    with pytest.raises(EvalProtocolError, match="non-string fields"):
        build_expected_gateway_steps(session, {required_field: 42})


def test_fixture_container_and_version_override_fail_closed() -> None:
    session = next(item for item in screening_sessions() if item.case.id == "Q1")

    with pytest.raises(EvalProtocolError, match="must be a mapping"):
        build_expected_gateway_steps(session, [("query_path", "value")])  # type: ignore[arg-type]
    with pytest.raises(EvalProtocolError, match="keys must be strings"):
        build_expected_gateway_steps(session, {1: "value"})  # type: ignore[dict-item]
    with pytest.raises(EvalProtocolError, match="non-string fields"):
        build_expected_gateway_steps(session, {"query_path": 42})
    with pytest.raises(EvalProtocolError, match="cannot override version"):
        build_expected_gateway_steps(
            session,
            {**FIXTURES["Q1"], "wwise_version": "2025.1"},
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda session: replace(session, gateway_steps=("preview", "operation-schema")), "gateway_steps"),
        (lambda session: replace(session, phase="invented"), "does not support phase"),
        (
            lambda session: replace(session, case=replace(session.case, protocol="read_only")),
            "protocol must be",
        ),
        (
            lambda session: replace(session, case=replace(session.case, adapter="invented")),
            "adapter must be",
        ),
        (
            lambda session: replace(session, case=replace(session.case, operation="object.copy")),
            "operation must be",
        ),
        (
            lambda session: replace(session, case=replace(session.case, id="X1")),
            "unknown v2 case",
        ),
        (
            lambda session: replace(session, version="2099.1"),
            "unsupported eval session version",
        ),
    ],
)
def test_wrong_or_unknown_session_protocol_fails_closed(mutation: Any, message: str) -> None:
    session = next(
        item
        for item in screening_sessions()
        if item.case.id == "M1" and item.phase == "preview"
    )

    with pytest.raises(EvalProtocolError, match=message):
        build_expected_gateway_steps(mutation(session), FIXTURES["M1"])


def test_forged_request_envelope_fails_closed_before_broker_configuration() -> None:
    session = next(
        item
        for item in screening_sessions()
        if item.case.id == "M1" and item.phase == "preview"
    )
    forged_case = replace(
        session.case,
        request_template={
            **session.case.request_template,
            "contract": "invented.contract/v9",
        },
    )

    with pytest.raises(EvalProtocolError, match="wrong operation-request contract"):
        build_expected_gateway_steps(replace(session, case=forged_case), FIXTURES["M1"])
