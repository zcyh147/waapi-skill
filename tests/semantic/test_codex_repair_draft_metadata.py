"""Real public Gateway receipts cross the authenticated metadata Broker seam."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from tests.unit.test_field_interface_closure_gateway import FieldTask, FIRST, gateway
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker, ExpectedGatewayStep, ResponseBinding
from tests.semantic.support.codex_repair_cases import metadata_chain_proven


def producer_chain(tmp_path, monkeypatch):
    rows = []
    original = FieldTask.run
    def capture(self, *argv):
        code, payload = original(self, *argv)
        assert code == 0, payload
        rows.append((list(argv), deepcopy(payload)))
        return code, payload
    monkeypatch.setattr(FieldTask, "run", capture)
    task = FieldTask(tmp_path, "2025.1", "object.setProperty")
    task.metadata = {"Other": {"name": "Other", "type": "Real32", "default": 0},
        "PreDelay": {"name": "PreDelay", "type": "Real32", "default": 25,
                     "restriction": {"type": "range", "min": 0, "max": 1000}}}
    handle = task.bind(FIRST)
    _, page = task.step("draft-discover-fields", "--object-handle", handle, "--list", "--page-size", "1")
    _, page = task.step("draft-discover-fields", "--object-handle", handle, "--list", "--page-size", "1",
                        "--page", page["agent_result"]["next_page"])
    selection = page["agent_result"]["fields"][0]["selection"]
    task.step("draft-discover-fields", "--object-handle", handle, "--selection", selection)
    assert [payload["draft"]["revision"] for _, payload in rows] == [1, 2, 2, 2, 3]
    return rows


@pytest.mark.parametrize("fault", [None, "list_increment", "selection_unchanged"])
@pytest.mark.parametrize("dynamic", [False, True])
def test_real_draft_browse_and_selection_revisions_cross_authenticated_broker(tmp_path, monkeypatch, fault, dynamic):
    monkeypatch.setattr(gateway, "GATEWAY_RUNNER_PATH", tmp_path / "transport/scripts/run.py")
    rows = producer_chain(tmp_path, monkeypatch)
    if fault == "list_increment":
        rows[2][1]["draft"]["revision"] = 3
    elif fault == "selection_unchanged":
        rows[4][1]["draft"]["revision"] = 2
    skill = tmp_path / "transport"
    (skill / "scripts").mkdir(parents=True)
    (skill / "replies.json").write_text(json.dumps(rows))
    (skill / "scripts/run.py").write_text(
        "import json,sys,pathlib\n"
        "rows=json.loads((pathlib.Path(__file__).parents[1]/'replies.json').read_text())\n"
        "args=sys.argv[2:]\n"
        "print(json.dumps(next(payload for argv,payload in rows if argv==args)))\n")
    steps = []
    for i, (argv, _) in enumerate(rows):
        args = list(argv[1:])
        if i:
            args[0] = ResponseBinding("draft.0", "/draft/draft_id")
            args[args.index("--task-authority") + 1] = ResponseBinding("draft.0", "/task_authority")
            args[args.index("--expected-revision") + 1] = ResponseBinding(f"draft.{i-1}", "/draft/revision")
        steps.append(ExpectedGatewayStep(f"draft.{i}", argv[0], tuple(args)))
    from tests.semantic.support.codex_expansion_cases import PreparedExpansionCase
    from tests.semantic.support.codex_repair_broker_policy import RepairBrokerPolicy
    prepared = PreparedExpansionCase(prompt="Set PreDelay to 24", operation="object.setProperty", policy="allow_changes",
        before={}, read_object_ids=frozenset({FIRST}), relationship_sources=frozenset(), read_includes=frozenset(),
        required_assertions=frozenset({"metadata_list_page_detail"}), approve_preview=lambda _: False,
        snapshot=lambda: {}, verify=lambda *_: {})
    policy = RepairBrokerPolicy(prepared=prepared, version="2025.1", skill_source=Path(__file__).parents[2] / "skills/waapi-skill", scoped_paths={FIRST: "fixture"})
    policy.begin_turn(1)
    with CodexGatewayBroker(skill_source=skill, expected_steps=() if dynamic else steps, transport="tcp",
                            expansion_outcome_policy=policy if dynamic else None) as broker:
        exits = []
        for argv, _ in rows:
            reply = broker._handle_request({"token": broker._token, "interpreter": "python",
                "argv": [str(broker.runner_path), "gateway.py", *argv]})
            exits.append(reply["exit_code"])
            if reply["exit_code"]:
                break
        assert (exits == [0] * 5) is (fault is None), (exits, reply["stderr"])
        if fault is None:
            if dynamic:
                assert metadata_chain_proven(policy.read_receipts)
            else:
                assert broker.evidence().complete
            assert metadata_chain_proven([{"command": argv[0], "arguments": argv[1:], "payload": payload}
                                          for argv,payload in rows])
        else:
            assert broker.evidence().terminal_state == "FAILED"


@pytest.mark.parametrize("fault", [None, "other_draft", "other_scope", "stale_page", "failed_selection", "unknown_selection", "wrong_metadata"])
def test_draft_metadata_credit_requires_one_bound_successful_chain(tmp_path, monkeypatch, fault):
    rows = producer_chain(tmp_path, monkeypatch)
    if fault == "other_draft":
        rows[-1][0][1] = "od1-other"
    elif fault == "other_scope":
        args = rows[-1][0]; args[args.index("--object-handle") + 1] = "other-handle"
    elif fault == "stale_page":
        args = rows[-2][0]; args[args.index("--page") + 1] = "stale-page"
    elif fault == "failed_selection":
        rows[-1][1]["ok"] = False
    elif fault == "unknown_selection":
        args = rows[-1][0]; args[args.index("--selection") + 1] = "unseen-selection"
    elif fault == "wrong_metadata":
        rows[-1][1]["field_candidates"][0]["metadata"]["name"] = "Other"
    assert metadata_chain_proven([{"command": argv[0], "arguments": argv[1:], "payload": payload}
                                  for argv, payload in rows]) is (fault is None)


@pytest.mark.parametrize("fault", [None, "missing_notice", "unauthenticated", "other_scope", "stale_page", "failed_selection", "selection_unchanged"])
def test_real_metadata_receipts_replay_through_notice_and_archive(tmp_path, monkeypatch, fault):
    from tests.semantic.test_codex_expansion_archive import _sealed_c08, _write, INPUTS
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    producer = tmp_path / "producer"
    producer.mkdir()
    rows = producer_chain(producer, monkeypatch)
    if fault == "other_scope":
        args = rows[-1][0]; args[args.index("--object-handle") + 1] = "other-handle"
    elif fault == "stale_page":
        args = rows[-2][0]; args[args.index("--page") + 1] = "stale-page"
    elif fault == "failed_selection":
        rows[-1][1]["ok"] = False
    if fault == "selection_unchanged":
        rows[-1][1]["draft"]["revision"] = 2
    root = tmp_path / "archive"
    _sealed_c08(root, repair_metadata=rows, notice_fault="missing_effect" if fault == "missing_notice" else None)
    if fault == "unauthenticated":
        path = root / "expansion-broker.json"
        broker = json.loads(path.read_text()); broker["records"][2]["authenticated"] = False
        _write(path, broker)
    from tests.semantic.run_codex_skill_matrix import expansion_case_isolated
    record = {"scenario_id": "REPAIR25-F1", "version": "2025.1", "status": "PASS", "scenario_root": str(tmp_path),
        "runner_outcome": {"task_root": str(root), "inputs_sha256": INPUTS, "checks": {"trusted_oracle_closed": True},
            "lifecycle": {"scenario_id": "REPAIR25-F1", "version": "2025.1", "source_hash_before": {"sha256": "source"},
                "source_hash_after": {"sha256": "source"}, "source_mtime_before_ns": 1, "source_mtime_after_ns": 1, "errors": []}}}
    # The formal scheduler stops on invalid provenance even when cleanup is proved.
    assert expansion_case_isolated(record) is (fault is None)
    if fault:
        with pytest.raises(ExpansionArchiveError):
            verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F1", expected_version="2025.1", expected_inputs_sha256=INPUTS)
    else:
        replay = verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F1", expected_version="2025.1", expected_inputs_sha256=INPUTS)
        assert replay["business_pass"] is True
