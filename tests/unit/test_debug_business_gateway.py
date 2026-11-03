from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_transaction_gateway import (
    FakeClient,
    execute,
    live_info,
    project,
)
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.operation_drafts import OperationDraftStore


GET_INFO_URI = "ak.wwise.core.getInfo"
GET_PROJECT_INFO_URI = "ak.wwise.core.getProjectInfo"
OBJECT_GET_URI = "ak.wwise.core.object.get"
LANES = {
    "debug.setAsserts": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "debug.setAutomationMode": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "debug.restartWaapiServers": ("2023.1", "2024.1", "2025.1"),
    "debug.testAssert": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "debug.testCrash": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
}


@pytest.mark.parametrize(
    ("operation", "version"),
    [(operation, version) for operation, versions in LANES.items() for version in versions],
)
def test_debug_business_declaration_is_one_live_bound_gateway_stage(
    tmp_path: Path,
    operation: str,
    version: str,
) -> None:
    state_dir = tmp_path / f"{operation}-{version}"
    code, started = execute(
        ["draft-start", operation],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version=version,
    )
    assert code == 0, started
    argv = [
        "draft-declare-debug-intent",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
    ]
    expected_intent: dict[str, object] = {}
    if operation in {"debug.setAsserts", "debug.setAutomationMode"}:
        argv.append("--disable")
        expected_intent = {"enabled": False}
    info = live_info(year=int(version[:4]))
    project_row = project()
    responses = {GET_INFO_URI: [info]}
    if version == "2021.1":
        responses[OBJECT_GET_URI] = [
            {
                "return": [
                    {
                        **project_row,
                        "type": "Project",
                        "filePath": project_row["path"],
                    }
                ]
            }
        ]
    else:
        responses[GET_PROJECT_INFO_URI] = [project_row]
    client = FakeClient(responses)

    code, declared = execute(
        argv,
        tmp_path=tmp_path,
        state_dir=state_dir,
        version=version,
        client=client,
    )

    assert code == 0, declared
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_debug_business_intent"
    )
    record = OperationDraftStore(state_dir).inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )
    session = BusinessDeclarationSession.from_dict(
        record.composition["business_session"]
    )
    assert session.settings == {"debug_intent": expected_intent}
    assert [row[0] for row in client.calls] == [
        GET_INFO_URI,
        OBJECT_GET_URI if version == "2021.1" else GET_PROJECT_INFO_URI,
    ]


def test_debug_business_cli_rejects_values_for_zero_value_intent(tmp_path: Path) -> None:
    state_dir = tmp_path / "zero-value"
    code, started = execute(
        ["draft-start", "debug.testCrash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2022.1",
    )
    assert code == 0, started
    code, payload = execute(
        [
            "draft-declare-debug-intent",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--enable",
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2022.1",
        client=FakeClient(
            {
                GET_INFO_URI: [live_info(year=2022)],
                GET_PROJECT_INFO_URI: [project()],
            }
        ),
    )

    assert code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "accepts no business values" in payload["message"]


@pytest.mark.parametrize("native_result,accepted,classification", [
    pytest.param(None, False, "expected_disconnect_delivery_indeterminate", id="missing-response"),
    pytest.param({}, True, "dispatch_accepted_effect_unverified", id="empty-acknowledgement"),
])
def test_expected_disconnect_keeps_missing_response_ambiguous(
    tmp_path: Path, native_result, accepted: bool, classification: str,
) -> None:
    state_dir = tmp_path / "disconnect"
    calls = []

    def run(*argv):
        client = FakeClient({GET_INFO_URI: [live_info(year=2022)],
            GET_PROJECT_INFO_URI: [project()], "ak.wwise.debug.testCrash": [native_result]})
        result = execute(list(argv), tmp_path=tmp_path, state_dir=state_dir,
            version="2022.1", client=client)
        calls.extend(client.calls)
        return result

    code, started = run("draft-start", "debug.testCrash")
    assert code == 0, started
    draft, authority = started["draft"]["draft_id"], started["task_authority"]
    phase = started
    for command in ("draft-declare-debug-intent", "draft-check", "preview-from-draft"):
        code, phase = run(command, draft, "--task-authority", authority,
            "--expected-revision", str(phase["draft"]["revision"]))
        assert code == 0, phase
    transaction = phase["transaction_id"]
    code, shown = run("transaction-show", transaction)
    assert code == 0, shown
    code, confirmed = run("confirm", transaction, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, failed = run("execute", transaction)
    assert code == 2 and failed["state"] == "indeterminate", failed
    assert failed["status"] == "expected_disconnect_indeterminate"
    assert failed["dispatch_accepted"] is accepted
    assert failed["dispatch_delivery"] == ("waapi_result_returned" if accepted else "indeterminate_after_dispatch_attempt")
    assert failed["terminal_journal"]["classification"] == classification
    assert failed["terminal_journal"]["effect_verified"] is False
    assert failed["automatic_retry"] is False and failed["reconnect_attempted"] is False
    assert failed["generic_verify_allowed"] is False
    if not accepted:
        code, retained = run("transaction-show", transaction)
        assert code == 0, retained
        event = next(row for row in retained["events"] if row["event_type"] == "execution_indeterminate")
        assert event["details"]["dispatch_result"]["failure_origin"] == "missing_response"
        assert event["details"]["dispatch_result"]["result"] is None
    code, replay = run("execute", transaction)
    assert code == 2 and replay.get("verified") is not True, replay
    assert len([row for row in calls if row[0] == "ak.wwise.debug.testCrash"]) == 1
