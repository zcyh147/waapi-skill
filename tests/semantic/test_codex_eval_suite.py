from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from tests.semantic.support.codex_eval_suite import (
    ADAPTER_IDS,
    CASE_IDS,
    GATEWAY_RESULT_CONTRACT,
    OPERATION_REQUEST_CONTRACT,
    PROFILE_SESSION_COUNTS,
    REPRESENTATIVE_VERSION,
    SUITE_CONTRACT,
    SUPPORTED_VERSIONS,
    EvalSuiteError,
    load_eval_suite,
    parse_eval_suite,
    render_json_template,
    render_text_template,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_V2 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "evals-v2.json"


@pytest.fixture
def payload() -> dict[str, Any]:
    return json.loads(EVALS_V2.read_text(encoding="utf-8"))


def test_loads_closed_v2_suite_and_fixed_case_routing() -> None:
    suite = load_eval_suite(EVALS_V2)

    assert suite.contract == SUITE_CONTRACT
    assert suite.skill_name == "waapi-skill"
    assert suite.versions == SUPPORTED_VERSIONS
    assert suite.representative_version == REPRESENTATIVE_VERSION
    assert suite.adapters == ADAPTER_IDS
    assert suite.gateway_result_contract == GATEWAY_RESULT_CONTRACT
    assert suite.operation_request_contract == OPERATION_REQUEST_CONTRACT
    assert tuple(case.id for case in suite.cases) == CASE_IDS
    assert [(case.id, case.adapter, case.protocol) for case in suite.cases] == [
        ("Q1", "exact_path_query", "read_only"),
        ("Q2", "direct_children_query", "read_only"),
        ("Q3", "name_search_query", "read_only"),
        ("Q4", "query_editor_query", "read_only"),
        ("Q5", "exact_missing_path_query", "read_only"),
        ("C1", "offline_catalog", "offline_catalog"),
        ("M1", "object_set_notes", "preview_confirm"),
        ("M2", "object_set_notes", "adversarial_preview"),
        ("M3", "object_create", "preview_confirm"),
        ("M4", "object_delete", "preview_confirm"),
        ("M5", "object_set_name", "preview_confirm"),
        ("M6", "object_set_property", "preview_confirm"),
        ("M7", "object_set_reference", "preview_confirm"),
        *((case_id, "operation_boundary", "unsupported_boundary") for case_id in ("B1", "B2", "B3", "B4", "B5", "B6", "B7")),
        ("I1", "audio_import", "preview_confirm"),
        ("S1", "soundbank_inclusions", "preview_confirm"),
        ("W1", "switch_assignment", "preview_confirm"),
        ("W2", "switch_assignment_remove", "preview_confirm"),
        ("R1", "status_read", "status_read_only"),
        ("R2", "buses_read", "buses_read_only"),
        ("R3", "selected_read", "selected_read_only"),
        ("R4", "metadata_types_read", "metadata_types_read_only"),
        ("R5", "object_created_topic_read", "object_created_topic_read_only"),
        ("R6", "reflection_functions_read", "reflection_functions_read_only"),
    ]


def test_profiles_expand_to_exact_40_98_168_session_counts() -> None:
    suite = load_eval_suite(EVALS_V2)

    assert {
        profile.id: len(suite.expand_profile(profile.id)) for profile in suite.profiles
    } == PROFILE_SESSION_COUNTS
    for profile in suite.profiles:
        sessions = suite.expand_profile(profile.id)
        assert len({session.session_id for session in sessions}) == len(sessions)
        assert sessions[0].profile_id == profile.id


def test_screening_schedules_every_case_once_and_all_ten_ab_pairs() -> None:
    suite = load_eval_suite(EVALS_V2)
    sessions = suite.expand_profile("screening")

    assert {session.case.id for session in sessions} == set(CASE_IDS)
    assert {session.version for session in sessions} == {REPRESENTATIVE_VERSION}
    assert len(sessions) == 40
    assert tuple(dict.fromkeys(session.case.id for session in sessions)) == CASE_IDS
    for case_id in ("M1", "M3", "M4", "M5", "M6", "M7", "I1", "S1", "W1", "W2"):
        pair = [session for session in sessions if session.case.id == case_id]
        assert [session.phase for session in pair] == ["preview", "confirm"]
        assert pair[0].pair_id == pair[1].pair_id
        assert pair[0].session_id != pair[1].session_id


def test_formal_profile_preserves_version_order_and_repetitions() -> None:
    suite = load_eval_suite(EVALS_V2)
    sessions = suite.expand_profile("formal_98")

    q1 = [session for session in sessions if session.case.id == "Q1"]
    assert tuple(session.version for session in q1) == SUPPORTED_VERSIONS
    for query_case in ("Q2", "Q3", "Q4", "Q5"):
        query_sessions = [session for session in sessions if session.case.id == query_case]
        assert [(session.version, session.phase) for session in query_sessions] == [
            (REPRESENTATIVE_VERSION, "single")
        ]
    m1 = [session for session in sessions if session.case.id == "M1"]
    assert [(session.version, session.phase) for session in m1] == [
        (version, phase) for version in SUPPORTED_VERSIONS for phase in ("preview", "confirm")
    ]
    for repeated_case in ("C1", "M2", "B1", "B2", "B3", "B4", "B5", "B6", "B7"):
        repeated = [session for session in sessions if session.case.id == repeated_case]
        assert [session.repetition for session in repeated] == [1, 2, 3]
    i1 = [session for session in sessions if session.case.id == "I1"]
    assert [(session.version, session.phase) for session in i1] == [
        *((version, "preview") for version in SUPPORTED_VERSIONS),
        (REPRESENTATIVE_VERSION, "confirm"),
    ]
    for case_id in ("M3", "M4", "M5", "M6", "M7", "W2"):
        workflow = [session for session in sessions if session.case.id == case_id]
        assert [(session.version, session.phase) for session in workflow] == [
            *((version, "preview") for version in SUPPORTED_VERSIONS),
            (REPRESENTATIVE_VERSION, "confirm"),
        ]
    for case_id in ("R1", "R2", "R3", "R4", "R5", "R6"):
        fixed_reads = [session for session in sessions if session.case.id == case_id]
        assert [(session.version, session.phase) for session in fixed_reads] == [
            (REPRESENTATIVE_VERSION, "single")
        ]


def test_full_profile_crosses_workflow_ab_sessions_over_all_versions() -> None:
    suite = load_eval_suite(EVALS_V2)
    sessions = suite.expand_profile("full_cross_version_168")

    for query_case in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        query_sessions = [session for session in sessions if session.case.id == query_case]
        assert tuple(session.version for session in query_sessions) == SUPPORTED_VERSIONS

    for read_case in ("R1", "R2", "R3", "R4", "R5", "R6"):
        read_sessions = [session for session in sessions if session.case.id == read_case]
        assert tuple(session.version for session in read_sessions) == SUPPORTED_VERSIONS

    for case_id in ("M1", "M3", "M4", "M5", "M6", "M7", "I1", "S1", "W1", "W2"):
        workflow = [session for session in sessions if session.case.id == case_id]
        assert [(session.version, session.phase) for session in workflow] == [
            (version, phase) for version in SUPPORTED_VERSIONS for phase in ("preview", "confirm")
        ]


def test_mutation_cases_bind_closed_request_templates_and_uris() -> None:
    suite = load_eval_suite(EVALS_V2)
    expected = {
        "M1": ("object.setNotes", "ak.wwise.core.object.setNotes"),
        "M2": ("object.setNotes", "ak.wwise.core.object.setNotes"),
        "M3": ("object.create", "ak.wwise.core.object.create"),
        "M4": ("object.delete", "ak.wwise.core.object.delete"),
        "M5": ("object.setName", "ak.wwise.core.object.setName"),
        "M6": ("object.setProperty", "ak.wwise.core.object.setProperty"),
        "M7": ("object.setReference", "ak.wwise.core.object.setReference"),
        "I1": ("audio.import", "ak.wwise.core.audio.import"),
        "S1": ("soundbank.setInclusions", "ak.wwise.core.soundbank.setInclusions"),
        "W1": (
            "switchContainer.addAssignment",
            "ak.wwise.core.switchContainer.addAssignment",
        ),
        "W2": (
            "switchContainer.removeAssignment",
            "ak.wwise.core.switchContainer.removeAssignment",
        ),
    }

    for case_id, (operation, uri) in expected.items():
        case = suite.case(case_id)
        assert case.operation == operation
        assert case.mutation_uri == uri
        assert case.request_template is not None
        assert case.request_template["contract"] == OPERATION_REQUEST_CONTRACT
        assert case.request_template["operation"] == operation
    assert suite.case("Q1").request_template is None
    assert all(suite.case(case_id).request_template is None for case_id in ("Q2", "Q3", "Q4", "Q5"))
    assert suite.case("C1").mutation_uri is None
    for case_id in ("B1", "B2", "B3", "B4", "B5", "B6", "B7"):
        assert suite.case(case_id).request_template is None


def test_preview_and_confirm_prompts_render_in_fresh_linked_sessions() -> None:
    suite = load_eval_suite(EVALS_V2)
    sessions = [session for session in suite.expand_profile("screening") if session.case.id == "M1"]
    values = {
        "target_path": r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticTarget",
        "notes_value": "semantic-v2",
    }

    preview = sessions[0].render_prompt(values)
    assert "2022.1" in preview
    assert "先给我一个可核对的预览" in preview
    assert "transaction id" not in preview

    confirm_values = {**values, "transaction_id": "tx-fixed", "preview_hash": "abc123"}
    confirm = sessions[1].render_prompt(confirm_values)
    assert "tx-fixed" in confirm
    assert "abc123" in confirm
    assert "不要另建预览" in confirm
    assert sessions[0].pair_id == sessions[1].pair_id

    request = sessions[0].render_request(values)
    assert request == {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.setNotes",
        "arguments": {
            "object": {"kind": "path", "value": values["target_path"]},
            "value": "semantic-v2",
        },
    }


def test_query_prompts_render_closed_one_line_result_protocol() -> None:
    suite = load_eval_suite(EVALS_V2)
    sessions = {
        session.case.id: session
        for session in suite.expand_profile("screening")
        if session.case.id in {"Q1", "Q2", "Q3", "Q4", "Q5"}
    }
    values = {
        "Q1": {"query_path": r"\Actor-Mixer Hierarchy\Target"},
        "Q2": {"parent_path": r"\Actor-Mixer Hierarchy\Parent"},
        "Q3": {"search_name": "SemanticTarget"},
        "Q4": {"query_path": r"\Queries\SemanticQuery"},
    }

    for case_id in ("Q1", "Q2", "Q3", "Q4"):
        prompt = sessions[case_id].render_prompt(values[case_id])
        assert "最终回答必须且只能是一行 WAAPI_RESULT_JSON=<json>" in prompt
        assert "JSON 顶层键必须严格为 count 和 objects" in prompt
        assert "objects 每项的键必须严格为 id、name、type、path" in prompt
        assert "不要 Markdown、解释或任何其他文字" in prompt

    missing_path = r"\Actor-Mixer Hierarchy\Default Work Unit\ProvenMissing"
    missing_prompt = sessions["Q5"].render_prompt({"missing_path": missing_path})
    assert "最终回答必须且只能是一行 WAAPI_RESULT_JSON=<json>" in missing_prompt
    assert "JSON 顶层键必须严格为 count、objects、not_found" in missing_prompt
    assert "count 必须是整数 0" in missing_prompt
    assert "objects 必须是空数组" in missing_prompt
    assert f"not_found 必须逐字等于精确路径 {missing_path}" in missing_prompt
    assert "不要 Markdown、解释或任何其他文字" in missing_prompt


def test_r4_uses_terminal_summary_agent_result_protocol() -> None:
    suite = load_eval_suite(EVALS_V2)
    session = next(
        item
        for item in suite.expand_profile("screening")
        if item.case.id == "R4"
    )

    prompt = session.render_prompt({})

    assert "metadata types --summary-only" in prompt
    assert "将 agent_result 紧凑序列化后逐字接在 WAAPI_RESULT_JSON= 后面" in prompt
    assert "不得从 normalized 重算" in prompt
    assert "再运行命令" in prompt


def test_rendering_fails_closed_on_missing_unknown_or_version_override() -> None:
    suite = load_eval_suite(EVALS_V2)
    confirm = next(
        session
        for session in suite.expand_profile("screening")
        if session.case.id == "M1" and session.phase == "confirm"
    )
    base = {
        "target_path": r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticTarget",
        "notes_value": "semantic-v2",
        "transaction_id": "tx-fixed",
    }

    with pytest.raises(EvalSuiteError, match="missing template values"):
        confirm.render_prompt(base)
    with pytest.raises(EvalSuiteError, match="unknown template values"):
        confirm.render_prompt({**base, "preview_hash": "abc", "rogue": "value"})
    with pytest.raises(EvalSuiteError, match="cannot override version"):
        confirm.render_prompt({**base, "preview_hash": "abc", "wwise_version": "2025.1"})
    with pytest.raises(EvalSuiteError, match="must be strings"):
        confirm.render_prompt({**base, "preview_hash": 123})


@pytest.mark.parametrize(
    "template",
    ("{value.attr}", "{value[0]}", "{value!r}", "{value:>10}"),
)
def test_template_renderer_rejects_attribute_index_conversion_and_format_specs(template: str) -> None:
    with pytest.raises(EvalSuiteError):
        render_text_template(template, {"value": "x"}, allowed_variables={"value"})


def test_json_renderer_preserves_exact_placeholder_types_without_eval() -> None:
    rendered = render_json_template(
        {"count": "{count}", "label": "prefix-{label}"},
        {"count": 3, "label": "safe"},
        allowed_variables={"count", "label"},
    )

    assert rendered == {"count": 3, "label": "prefix-safe"}
    with pytest.raises(EvalSuiteError, match="strict JSON"):
        render_json_template("{value}", {"value": {1, 2}}, allowed_variables={"value"})


def test_m6_request_keeps_volume_as_exact_json_float(payload: dict[str, Any]) -> None:
    suite = load_eval_suite(EVALS_V2)
    session = next(
        item
        for item in suite.expand_profile("screening")
        if item.case.id == "M6" and item.phase == "preview"
    )
    request = session.render_request(
        {"property_target_path": r"\Actor-Mixer Hierarchy\Default Work Unit\PropertyTarget"}
    )
    assert type(request["arguments"]["value"]) is float
    assert request["arguments"]["value"] == -3.0

    m6 = next(case for case in payload["cases"] if case["id"] == "M6")
    m6["request_template"]["arguments"]["value"] = -3
    with pytest.raises(EvalSuiteError, match="JSON number -3.0"):
        parse_eval_suite(payload)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.__setitem__("evaluator", "python"), "unknown"),
        (lambda value: value["protocols"][0].__setitem__("command", "anything"), "unknown"),
        (lambda value: value["protocols"][0]["phases"][0].__setitem__("shell", "anything"), "unknown"),
        (lambda value: value["cases"][0].__setitem__("python", "anything"), "unknown"),
        (lambda value: value["profiles"][0].__setitem__("commands", []), "unknown"),
        (lambda value: value["profiles"][0]["entries"][0].__setitem__("argv", []), "unknown"),
        (
            lambda value: value["cases"][6]["request_template"]["arguments"].__setitem__(
                "raw_waapi_args", {}
            ),
            "unknown",
        ),
    ],
)
def test_unknown_fields_and_executable_hooks_fail_closed(
    payload: dict[str, Any], mutate: Any, message: str
) -> None:
    mutate(payload)

    with pytest.raises(EvalSuiteError, match=message):
        parse_eval_suite(payload)


@pytest.mark.parametrize("collection", ("protocols", "cases", "profiles"))
def test_duplicate_ids_fail_closed_before_routing(payload: dict[str, Any], collection: str) -> None:
    payload[collection][1]["id"] = payload[collection][0]["id"]

    with pytest.raises(EvalSuiteError, match="duplicate ids"):
        parse_eval_suite(payload)


def test_unknown_prompt_and_request_template_variables_fail_closed(payload: dict[str, Any]) -> None:
    prompt_payload = copy.deepcopy(payload)
    prompt_payload["cases"][0]["prompts"]["single"] += " {not_from_adapter}"
    with pytest.raises(EvalSuiteError, match="unknown template variables"):
        parse_eval_suite(prompt_payload)

    request_payload = copy.deepcopy(payload)
    request_payload["cases"][6]["request_template"]["arguments"]["value"] = "{not_from_adapter}"
    with pytest.raises(EvalSuiteError, match="unknown template variables"):
        parse_eval_suite(request_payload)


def test_confirm_prompt_must_bind_both_transaction_artifacts(payload: dict[str, Any]) -> None:
    payload["cases"][6]["prompts"]["confirm"] = payload["cases"][6]["prompts"]["confirm"].replace(
        " 和 preview hash {preview_hash}", ""
    )

    with pytest.raises(EvalSuiteError, match="transaction_id and preview_hash"):
        parse_eval_suite(payload)


def test_missing_or_reordered_hard_gate_fails_closed(payload: dict[str, Any]) -> None:
    missing = copy.deepcopy(payload)
    missing["protocols"][2]["phases"][0]["hard_gates"].remove("target_unchanged")
    with pytest.raises(EvalSuiteError, match="hard_gates mismatch"):
        parse_eval_suite(missing)

    reordered = copy.deepcopy(payload)
    gates = reordered["protocols"][0]["phases"][0]["hard_gates"]
    gates[0], gates[1] = gates[1], gates[0]
    with pytest.raises(EvalSuiteError, match="hard_gates mismatch"):
        parse_eval_suite(reordered)


def test_adapter_gateway_steps_and_protocols_are_fixed_enums(payload: dict[str, Any]) -> None:
    adapter = copy.deepcopy(payload)
    adapter["adapters"].append("python_fixture")
    with pytest.raises(EvalSuiteError, match="fixed adapter enum"):
        parse_eval_suite(adapter)

    step = copy.deepcopy(payload)
    step["protocols"][0]["phases"][0]["gateway_steps"] = ["arbitrary-shell-command"]
    with pytest.raises(EvalSuiteError, match="unknown fixed steps"):
        parse_eval_suite(step)


def test_root_and_profile_version_order_is_fixed(payload: dict[str, Any]) -> None:
    root = copy.deepcopy(payload)
    root["versions"][0], root["versions"][1] = root["versions"][1], root["versions"][0]
    with pytest.raises(EvalSuiteError, match="preserve exact order"):
        parse_eval_suite(root)

    profile = copy.deepcopy(payload)
    versions = profile["profiles"][1]["entries"][0]["versions"]
    versions[0], versions[1] = versions[1], versions[0]
    with pytest.raises(EvalSuiteError, match="supported subsequence"):
        parse_eval_suite(profile)


def test_profile_count_repetition_and_confirm_pairing_fail_closed(payload: dict[str, Any]) -> None:
    declared = copy.deepcopy(payload)
    declared["profiles"][0]["expected_sessions"] = 13
    with pytest.raises(EvalSuiteError, match="fixed at 40"):
        parse_eval_suite(declared)

    zero_repetition = copy.deepcopy(payload)
    zero_repetition["profiles"][0]["entries"][0]["repetitions"] = 0
    with pytest.raises(EvalSuiteError, match="positive integer"):
        parse_eval_suite(zero_repetition)

    wrong_repetition = copy.deepcopy(payload)
    wrong_repetition["profiles"][1]["entries"][5]["repetitions"] = 2
    with pytest.raises(EvalSuiteError, match="must be 3 for formal_98/C1"):
        parse_eval_suite(wrong_repetition)

    no_preview = copy.deepcopy(payload)
    confirm_entry = next(
        entry
        for entry in no_preview["profiles"][1]["entries"]
        if entry["case_id"] == "M3" and entry["phases"] == ["confirm"]
    )
    confirm_entry["versions"] = [
        "2021.1",
        "2023.1",
        "2024.1",
        "2025.1",
    ]
    no_preview["profiles"][1]["expected_sessions"] = 95
    with pytest.raises(EvalSuiteError):
        parse_eval_suite(no_preview)


def test_json_contains_no_free_python_evaluator_or_command_fields(payload: dict[str, Any]) -> None:
    forbidden = {"python", "evaluator", "command", "commands", "shell", "argv"}
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            found.update(forbidden & set(value))
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    assert found == set()
