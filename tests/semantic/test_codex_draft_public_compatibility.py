"""Public Gateway Draft receipts must remain replayable by the formal harness."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import argparse
import json
import os
import shlex
import shutil
from types import SimpleNamespace
from copy import deepcopy
from typing import Mapping

import pytest

from tests.semantic.support.codex_gateway_broker import (
    ExpectedGatewayStep,
    CodexGatewayBroker,
    ResponseBinding,
    validate_operation_draft_protocol_steps,
)
from tests.semantic.support.codex_typed_draft_evidence_v3 import TypedDraftEvidenceError, validate_typed_draft_evidence
from tests.support.gateway_config import set_gateway_config
from tests.unit.test_authoring_layout_mutation_gateway import LayoutClient, URI
from tests.unit.test_waapi_gateway import gateway_env, waapi_gateway as gateway
from tests.semantic.test_codex_gateway_broker import run_model_command
from tests.semantic.support.codex_business_agent_runner import FIXTURE_ENV, WAAPI_SHIM_ROOT
from tests.semantic.support.codex_transaction_seal import create_preview_seal, verify_preview_seal
from tests.semantic.support.codex_harness import prepare_workspace_skill_install
from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.transactions import TransactionStore


def _public_layout_receipts(tmp_path: Path, *, inspect_draft: bool = False):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version="2025.1")
    state = tmp_path / "state"
    client = LayoutClient(tmp_path)
    steps = []
    records = []
    payloads = {}

    def run(name, command, arguments):
        step = ExpectedGatewayStep(name, command, tuple(arguments))
        argv = [command]
        for argument in arguments:
            if isinstance(argument, ResponseBinding):
                value = payloads[argument.step]
                for token in argument.pointer.lstrip("/").split("/"):
                    value = value[token]
                argv.append(str(value))
            else:
                argv.append(argument)
        code, payload = gateway.execute_gateway(
            ["--state-dir", str(state), *argv], env=env, client_factory=lambda _: client
        )
        assert code == 0, payload
        steps.append(step)
        records.append({"step_name": name, "succeeded": True,
                        "gateway_arguments": argv, "payload": payload})
        payloads[name] = payload
        return payload

    schema = run("tx01.schema", "request-schema", (URI + "setLayout",))
    run("tx01.layout", "layout-inspect", ("--layout-name", "Designer"))
    start = "tx01.draft-start"
    assert schema["continuation"]["gateway_argv"] == ["draft-start", URI + "setLayout"]
    run(start, "draft-start", tuple(schema["continuation"]["gateway_argv"][1:]))

    def prefix(revision):
        return (ResponseBinding(start, "/draft/draft_id"), "--task-authority",
                ResponseBinding(start, "/task_authority"), "--expected-revision",
                ResponseBinding(revision, "/draft/revision"))

    run("tx01.declare", "draft-declare-layout-plan", (*prefix(start),
        "--layout-handle", ResponseBinding("tx01.layout", "/layout_handle"),
        "--new-layout-name", "Owned"))
    revision = "tx01.declare"
    if inspect_draft:
        revision = "tx01.inspect"
        run(revision, "draft-inspect", prefix(start)[:3])
    run("tx01.check", "draft-check", prefix(revision))
    run("tx01.preview", "preview-from-draft", prefix("tx01.check"))
    return tuple(steps), records, state


def test_public_layout_declaration_is_a_closed_formal_draft_protocol(tmp_path):
    steps, _records, _state = _public_layout_receipts(tmp_path)
    validate_operation_draft_protocol_steps(steps)


@pytest.mark.parametrize("index,value", [(0, "forged-draft"), (2, "forged-authority"), (4, "1")])
def test_public_layout_protocol_keeps_issued_identity_authority_revision(tmp_path, index, value):
    steps, _records, _state = _public_layout_receipts(tmp_path)
    declaration = steps[3]
    arguments = list(declaration.arguments)
    arguments[index] = value
    corrupt = (*steps[:3], replace(declaration, arguments=tuple(arguments)), *steps[4:])
    with pytest.raises(ValueError):
        validate_operation_draft_protocol_steps(corrupt)


def test_public_layout_original_draft_audit_replays(tmp_path):
    steps, records, state = _public_layout_receipts(tmp_path)
    evidence = validate_typed_draft_evidence(
        state_directory=state, steps=steps, broker_records=records
    )
    assert evidence["audit_types"] == ["started", "settings.revised", "checked", "seal_reserved", "sealed"]
    assert evidence["canonical_request"] == records[-1]["payload"]["agent_result"]["request"]


def test_public_layout_inspection_preserves_revision_without_an_audit_event(tmp_path):
    steps, records, state = _public_layout_receipts(tmp_path, inspect_draft=True)
    assert records[3]["payload"]["draft"]["revision"] == records[4]["payload"]["draft"]["revision"]
    evidence = validate_typed_draft_evidence(
        state_directory=state, steps=steps, broker_records=records
    )
    assert evidence["audit_types"] == ["started", "settings.revised", "checked", "seal_reserved", "sealed"]


@pytest.mark.parametrize("operation,command,fields", [
    ("debug.setAutomationMode", "draft-declare-debug-intent", ("--enable",)),
    ("ak.soundengine.postMsgMonitor", "draft-declare-soundengine-plan", ("--monitor-message", 'UTF8 界 "quoted" \\ value')),
    ("ak.wwise.cli.generateSoundbank", "draft-declare-cli-console-plan", None),
    ("ak.wwise.debug.generateToneWAV", "draft-declare-host-plan", None),
])
def test_public_plan_original_settings_event_replays(tmp_path, operation, command, fields):
    env = set_gateway_config(gateway_env(tmp_path), wwise_version="2025.1")
    state = tmp_path / "state"
    client = LayoutClient(tmp_path)
    if command == "draft-declare-cli-console-plan":
        client.responses["ak.wwise.core.getInfo"]["isCommandLine"] = True
        fields = ("--value", "project_file", str(tmp_path / "project/Sandbox.wproj"),
                  "--value", "soundbank_scope", "all", "--item", "platforms", "Windows")
    elif command == "draft-declare-host-plan":
        fields = ("--value", "output_file", str(tmp_path / "tone.wav"),
                  "--value", "waveform", "sine", "--value", "frequency_hz", "440",
                  "--value", "channel_layout", "2.0", "--value", "bit_depth", "int16",
                  "--value", "sample_rate_hz", "48000", "--value", "attack_seconds", "0.05",
                  "--value", "sustain_seconds", "1", "--value", "release_seconds", "0.1")
    steps = []
    records = []
    prior = None
    for name, subcommand, arguments in [
        ("tx01.draft-start", "draft-start", (operation,)),
        ("tx01.declare", command, fields),
        ("tx01.cancel", "draft-cancel", ()),
    ]:
        if prior is not None:
            arguments = (started["draft"]["draft_id"], "--task-authority", started["task_authority"],
                         "--expected-revision", str(prior["draft"]["revision"]), *arguments)
        code, payload = gateway.execute_gateway(["--state-dir", str(state), subcommand, *arguments],
            env=env, client_factory=lambda _: client)
        assert code == 0, payload
        if prior is None:
            started = payload
        prior = payload
        steps.append(ExpectedGatewayStep(name, subcommand, tuple(arguments)))
        records.append({"step_name": name, "succeeded": True, "gateway_arguments": [subcommand, *arguments], "payload": payload})
    evidence = validate_typed_draft_evidence(state_directory=state, steps=steps, broker_records=records)
    assert evidence["audit_types"] == ["started", "settings.revised", "cancelled"]
    assert evidence["canonical_request"] is not None


def test_actual_public_draft_parser_has_an_exact_formal_event_or_separate_lane_policy():
    from tests.semantic.support.codex_draft_commands import DRAFT_GATEWAY_SUBCOMMANDS
    from tests.semantic.support.codex_typed_draft_evidence_v3 import _BUSINESS_DRAFT_EVENT_OPTIONS
    parser = gateway.build_parser()
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    actual = {command for command in subparsers.choices if command.startswith("draft-")}
    assert actual <= DRAFT_GATEWAY_SUBCOMMANDS
    separate = {"draft-inspect", "draft-apply", "draft-start-undo-child"}
    assert DRAFT_GATEWAY_SUBCOMMANDS == set(_BUSINESS_DRAFT_EVENT_OPTIONS) | separate


def _layout_broker_steps(blueprint):
    start = "tx01.draft-start"
    def prefix(revision):
        return (ResponseBinding(start, "/draft/draft_id"), "--task-authority",
                ResponseBinding(start, "/task_authority"), "--expected-revision",
                ResponseBinding(revision, "/draft/revision"))
    tx = ResponseBinding("tx01.preview", "/transaction_id")
    return (
        ExpectedGatewayStep("tx01.schema", "request-schema", (URI + "setLayout",)),
        ExpectedGatewayStep("tx01.layout", "layout-inspect", ("--layout-name", "Designer")),
        ExpectedGatewayStep(start, "draft-start", (URI + "setLayout",)),
        ExpectedGatewayStep("tx01.declare", "draft-declare-layout-plan", (*prefix(start),
            "--layout-handle", ResponseBinding("tx01.layout", "/layout_handle"),
            "--new-layout-name", "Owned", "--blueprint", json.dumps(blueprint, ensure_ascii=False))),
        ExpectedGatewayStep("tx01.check", "draft-check", prefix("tx01.declare")),
        ExpectedGatewayStep("tx01.preview", "preview-from-draft", prefix("tx01.check")),
        ExpectedGatewayStep("tx01.show", "transaction-show", (tx, "--summary-only")),
        ExpectedGatewayStep("tx01.confirm", "confirm", (tx, "--confirmation-token", ResponseBinding("tx01.show", "/confirmation/token"))),
        ExpectedGatewayStep("tx01.execute", "execute", (tx,)),
        ExpectedGatewayStep("tx01.verify", "verify", (tx,)),
    )


@pytest.mark.parametrize("text", ["1" * 1695, "界" * 565, '"\\' * 423 + "abc"],
    ids=["ascii", "multibyte", "quoted-backslash"])
@pytest.mark.skipif(os.name == "nt", reason="POSIX TCP and archive proof; Windows projection has separate controls")
def test_near_capacity_public_layout_survives_authenticated_broker_and_archive(tmp_path, text, monkeypatch):
    """Production Gateway and TCP Broker proof; starts neither Codex nor Wwise."""
    root = Path(__file__).resolve().parents[2]
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    project = runtime / "Sandbox.wproj"
    project.write_text("<WwiseDocument/>", encoding="utf-8")
    layout_state = runtime / "layout-state.json"
    layout_state.write_text(json.dumps({"current": "Designer", "calls": [], "layouts": {
        "Designer": {"Layout": {"Name": "Designer", "StackPanel": {"Name": "StackPanel",
            "ID": "{11111111-1111-1111-1111-111111111111}", "Orientation": "Horizontal", "@Children": []}}}}}), encoding="utf-8")
    fixture = runtime / "fixture.json"
    fixture.write_text(json.dumps({"version": "2025.1", "platform": "macosx", "is_command_line": False,
        "session_id": '界"\\' * 500, "process_path": str(runtime / "Wwise"), "project_path": str(project),
        "layout_state_path": str(layout_state), "objects": [], "fields": []}, ensure_ascii=False), encoding="utf-8")
    blueprint = {"contract": "waapi-skill.layout-blueprint/v1", "root": "main", "nodes": [
        {"key": "main", "kind": "stack", "label": "Main", "orientation": "horizontal",
         "children": ["v" + str(index) for index in range(63)]},
        *[{"key": "v" + str(index), "kind": "view", "view_type": "ProjectExplorer",
           "selection_channel": "1", "width": text} for index in range(63)]]}
    steps = _layout_broker_steps(blueprint)
    payloads = {}
    observed_stdout = {}
    command_facts = []
    workspace = tmp_path / "agent-workspace"
    installed = prepare_workspace_skill_install(workspace, root / "skills/waapi-skill")
    monkeypatch.chdir(workspace)
    with CodexGatewayBroker(skill_source=root / "skills/waapi-skill", expected_steps=steps,
        invocation_skill_source=installed,
        expected_wwise_version="2025.1", project_modification_policy="ask_before_changes",
        runner_environment={**os.environ, "PYTHONPATH": os.pathsep.join((str(WAAPI_SHIM_ROOT), str(root), str(root / "skills/waapi-skill"))),
            FIXTURE_ENV: str(fixture), "WWISE_WAAPI_HOST": "127.0.0.1", "WWISE_WAAPI_PORT": "31337"},
        working_root=tmp_path / "broker", transport="tcp") as broker:
        for step in steps:
            argv = [step.subcommand]
            for argument in step.arguments:
                if isinstance(argument, ResponseBinding):
                    value = payloads[argument.step]
                    for token in argument.pointer.lstrip("/").split("/"):
                        assert isinstance(value, Mapping)
                        value = value[token]
                    argv.append(str(value))
                else:
                    argv.append(argument)
            runner_path = None
            if step.subcommand == "draft-check":
                selected = payloads["tx01.declare"]["draft"]["next_action_binding"]["check"]["fixed_argv_prefix_copy"]
                runner_path = Path(shlex.split(selected)[1])
            result = run_model_command(broker, argv, runner_path=runner_path)
            (tmp_path / f"{step.name}.stdout.txt").write_text(result.stdout, encoding="utf-8")
            (tmp_path / f"{step.name}.stderr.txt").write_text(result.stderr, encoding="utf-8")
            (tmp_path / "broker-evidence.json").write_text(json.dumps(broker.evidence().as_dict(include_output=True), ensure_ascii=False), encoding="utf-8")
            assert result.returncode == 0, (step.name, result.stdout, result.stderr)
            payloads[step.name] = json.loads(result.stdout[result.stdout.index("{"):])
            observed_stdout[step.name] = result.stdout
            command_facts.append({"argv": list(result.args), "command": shlex.join(result.args),
                "exit_code": result.returncode, "status": "completed", "has_shell_operators": False,
                "parse_error": "", "parser_kind": "posix-native", "aggregated_output": result.stdout})
            if step.subcommand == "preview-from-draft":
                seal = create_preview_seal(tmp_path / "broker/state", payloads[step.name]["transaction_id"])
        evidence = broker.evidence()
    assert evidence.passed, evidence
    records = evidence.as_dict(include_output=True)["records"]
    assert all(record["authenticated"] and record["accepted"] and record["succeeded"] for record in records)
    for record in records:
        assert record["stdout"] == observed_stdout[record["step_name"]]
        assert record["payload_sha256"] == canonical_sha256(record["payload"])
    final = payloads["tx01.verify"]
    stdout = observed_stdout["tx01.verify"]
    assert 24 * 1024 < len(stdout.encode("utf-8")) <= 280 * 1024
    assert list(final)[-1] == "agent_result"
    assert final["verified"] is True
    state = tmp_path / "broker/state"
    tx = final["transaction_id"]
    artifact = TransactionStore(state).load_preview(tx).artifact
    assert final["agent_result"]["request"] == artifact["request"]
    assert all("agent_result" not in payloads[f"tx01.{name}"]
               for name in ("show", "confirm", "execute"))
    native = artifact["prepared_operation"]["dispatch"]["args"]["layout"]
    assert 114000 < len(json.dumps(native, ensure_ascii=False, separators=(",", ":")).encode()) <= 114688
    assert [child["Width"] for child in native["Layout"]["StackPanel"]["@Children"]] == [text] * 63
    current = json.loads(layout_state.read_text(encoding="utf-8"))
    assert current["layouts"]["Owned"] == native
    assert sum(call["uri"] == URI + "setLayout" for call in current["calls"]) == 1
    sealed = verify_preview_seal(state, tx, seal, allowed_states=("verified",))
    assert sealed.request_canonical_sha256 == canonical_sha256(artifact["request"])
    replayed = validate_typed_draft_evidence(state_directory=state, steps=steps, broker_records=records)
    assert replayed["canonical_request"] == artifact["request"]
    from tests.semantic import run_codex_skill_campaign as campaign
    # Real developer subprocess observations feed the existing formal reader.
    # These are transport facts, never a Codex JSONL archive or a Fresh verdict.
    def replay_archive(receipts, facts):
        campaign._validate_heavy_v3_broker_records(receipts, task_root=tmp_path,
            steps=steps, command_records=facts,
            options=SimpleNamespace(skill_source=root / "skills/waapi-skill", windows_powershell_core_host=None),
            version="2025.1", label="developer authenticated layout transport",
            expected_project_modification_policy="ask_before_changes")
        validate_typed_draft_evidence(state_directory=state, steps=steps, broker_records=receipts)
    archive_records = json.loads(json.dumps(evidence.as_dict()))["records"]
    replay_archive(archive_records, command_facts)
    damaged_facts = deepcopy(command_facts)
    damaged_facts[-1]["aggregated_output"] = stdout[:-2]
    with pytest.raises(campaign.CampaignEvidenceError):
        replay_archive(archive_records, damaged_facts)
    for damage in ("wrong-policy", "stale-revision", "other-flow", "forged-compact", "missing-owed-context", "final-request", "missing-final-result", "non-mapping-final-result", "final-transaction", "final-artifact", "journal-summary", "payload-digest"):
        corrupt_records, corrupt_facts = deepcopy(archive_records), deepcopy(command_facts)
        index = next(i for i, row in enumerate(corrupt_records) if row["step_name"] == "tx01.declare")
        if damage == "missing-owed-context":
            index = 0
            corrupt_records[index]["payload"].pop("session_context")
        elif damage == "payload-digest":
            corrupt_records[-1]["payload_sha256"] = "0" * 64
        elif damage == "final-request":
            index = len(corrupt_records) - 1
            corrupt_records[index]["payload"]["agent_result"]["request"]["arguments"]["args"]["layout"]["Layout"]["StackPanel"]["@Children"][0]["Width"] = "changed"
        elif damage == "missing-final-result":
            index = len(corrupt_records) - 1
            corrupt_records[index]["payload"].pop("agent_result")
        elif damage == "non-mapping-final-result":
            index = len(corrupt_records) - 1
            corrupt_records[index]["payload"]["agent_result"] = []
        elif damage in {"final-transaction", "final-artifact"}:
            index = len(corrupt_records) - 1
            field = "transaction_id" if damage == "final-transaction" else "artifact_hash"
            corrupt_records[index]["payload"]["agent_result"][field] = "changed"
        elif damage == "journal-summary":
            index = len(corrupt_records) - 1
            corrupt_records[index]["payload"]["verification"]["canonical_sha256"] = "0" * 64
        elif damage == "wrong-policy":
            wrong = deepcopy(payloads["tx01.draft-start"]["session_context"])
            wrong["project_modification_policy"] = "allow_changes"
            wrong["one_time_introduction"]["facts"]["project_modification_policy"] = "allow_changes"
            corrupt_records[index]["payload"]["session_context"] = wrong
        elif damage == "stale-revision":
            corrupt_records[index]["payload"]["draft"]["revision"] = 1
        elif damage == "other-flow":
            corrupt_records[index]["payload"]["draft"]["draft_id"] = "od1-" + "0" * 32
        else:
            corrupt_records[index]["payload"].pop("draft")
        if damage != "payload-digest":
            corrupt_records[index]["payload_sha256"] = canonical_sha256(corrupt_records[index]["payload"])
            corrupt_facts[index]["aggregated_output"] = json.dumps(corrupt_records[index]["payload"], ensure_ascii=False)
        with pytest.raises((campaign.CampaignEvidenceError, TypedDraftEvidenceError)):
            replay_archive(corrupt_records, corrupt_facts)
    for damage in ("declaration-event", "canonical-request", "journal"):
        copied = tmp_path / ("corrupted-state-" + damage)
        shutil.copytree(state, copied)
        if damage == "declaration-event":
            path = next((copied / "operation-drafts-v1/records").glob("*.json"))
            content = json.loads(path.read_text(encoding="utf-8"))
            assert content["audit"][1]["event_type"] == "settings.revised"
            content["audit"].pop(1)
        elif damage == "canonical-request":
            path = copied / "transactions" / tx / "preview.json"
            content = json.loads(path.read_text(encoding="utf-8"))
            content["artifact"]["request"]["arguments"]["args"]["layout"]["Layout"]["StackPanel"]["@Children"][0]["Width"] = "changed"
        else:
            path = copied / "transactions" / tx / "events.jsonl"
            content = None
            rows = path.read_text(encoding="utf-8").splitlines()
            final_event = json.loads(rows[-1])
            final_event["event_hash"] = "0" * 64
            rows[-1] = json.dumps(final_event)
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        if content is not None:
            path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(TypedDraftEvidenceError):
            validate_typed_draft_evidence(state_directory=copied, steps=steps, broker_records=archive_records)
    replay = campaign._build_heavy_v3_broker_replay(skill_source=root / "skills/waapi-skill",
        invocation_skill_source=installed, canonical_steps=steps, execution_steps=steps,
        commutative_read_only_step_groups=(), commutative_composer_setup_step_groups=(),
        expected_wwise_version="2025.1", project_modification_policy="ask_before_changes", existing_state_directory=state)
    replay._payloads_by_step.update(payloads)
    for damage, match in (("saved-policy", "saved task policy"), ("other-flow-config", "durable binding")):
        copied_root = tmp_path / damage
        shutil.copytree(tmp_path / "broker", copied_root / "broker")
        config_path = copied_root / "broker/config/config.json"
        if damage == "saved-policy":
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["project_modification_policy"] = "allow_changes"
            config_path.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(campaign.CampaignEvidenceError, match=match):
            campaign._validate_heavy_v3_compact_policy_binding(payloads["tx01.declare"],
                step=next(step for step in steps if step.name == "tx01.declare"), replay=replay,
                task_root=copied_root, skill_source=root / "skills/waapi-skill", expected_policy="ask_before_changes")
    (tmp_path / "authenticated-broker-evidence.json").write_text(json.dumps(evidence.as_dict(include_output=True), ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("native", [
    {"contract": {"type": "object", "properties": {"contract": {"enum": ["界", '"\\']}}}},
    {"contract": ["native", {"contract": "waapi-skill.gateway-next-command/v2"}]},
    {"contract": "waapi-skill.operation-draft/v1", "next_command": {
        "contract": "waapi-skill.gateway-next-command/v2", "shell_command": "native text"}},
])
@pytest.mark.parametrize("platform", ["posix", "nt"])
def test_public_native_layout_contract_values_are_opaque_to_runner_projection(tmp_path, native, platform):
    from tests.semantic.support import codex_gateway_broker as broker_module
    env = set_gateway_config(gateway_env(tmp_path), wwise_version="2025.1")
    client = LayoutClient(tmp_path)
    client.layouts["Designer"]["Layout"]["native-data"] = native
    code, produced = gateway.execute_gateway(["layout-read", "contents", "--layout-name", "Designer"],
        env=env, client_factory=lambda _: client)
    assert code == 0, produced
    original = deepcopy(produced)
    projected = broker_module._project_model_visible_runner(produced,
        candidate_runner=Path(__file__).resolve().parents[2] / "skills/waapi-skill/scripts/run.py",
        invocation_runner=tmp_path / "task/.agents/skills/waapi-skill/scripts/run.py", platform_name=platform)
    assert projected["agent_result"] == original["agent_result"]
    assert projected["result"] == original["result"]
    assert list(projected)[-1] == "agent_result"
    assert produced == original


def test_public_business_field_browse_has_no_audit_event(tmp_path, monkeypatch):
    from tests.unit.test_field_interface_closure_gateway import FieldTask, FIRST
    steps, records = [], []
    original = FieldTask.run
    def capture(self, *argv):
        code, payload = original(self, *argv)
        assert code == 0, payload
        name = f"tx01.step{len(steps):02d}"
        if argv[0] == "draft-start":
            name = "tx01.draft-start"
        steps.append(ExpectedGatewayStep(name, argv[0], tuple(argv[1:])))
        records.append({"step_name": name, "succeeded": True, "gateway_arguments": list(argv), "payload": payload})
        return code, payload
    monkeypatch.setattr(FieldTask, "run", capture)
    task = FieldTask(tmp_path, "2025.1", "object.set")
    target = task.bind(FIRST)
    task.step("draft-discover-fields", "--object-handle", target, "--list")
    assert records[-1]["payload"]["draft"]["revision"] == records[-2]["payload"]["draft"]["revision"]
    task.step("draft-declare-existing", "--declaration-id", "owned", "--object-handle", target, "--field", "fade_time_ms", "250")
    task.step("draft-cancel")
    replayed = validate_typed_draft_evidence(state_directory=tmp_path / "state", steps=steps, broker_records=records)
    assert replayed["audit_types"] == ["started", "handles.bound", "declaration.added", "cancelled"]


@pytest.mark.parametrize("policy", ["read_only", "ask_before_changes", "allow_changes"])
def test_catalog_true_reads_remain_available_under_every_modification_policy(tmp_path, policy):
    from tests.semantic.test_codex_gateway_broker import _read_only_draft_evidence_fixture
    env = set_gateway_config(gateway_env(tmp_path), wwise_version="2025.1", project_modification_policy=policy)
    client = LayoutClient(tmp_path)
    code, payload = gateway.execute_gateway(["layout-read", "contents", "--layout-name", "Designer"],
        env=env, client_factory=lambda _: client)
    assert code == 0 and payload["ok"] is True
    assert payload["session_context"]["project_modification_policy"] == policy
    assert all(uri != URI + "setLayout" for uri, _args, _options in client.calls)
    fixture_root = tmp_path / "typed-read"
    fixture_root.mkdir()
    broker, steps, _records, _state = _read_only_draft_evidence_fixture(fixture_root)
    assert broker._operation_draft_step_is_read_only(steps[-1]) is True


def test_public_result_schema_success_keeps_exact_terminal_request_binding(tmp_path):
    """Schema-only success owes agent_result although it does not verify business state."""
    state = tmp_path / "state"
    env = set_gateway_config(gateway_env(tmp_path), wwise_version="2025.1")
    client = LayoutClient(tmp_path)
    client.responses["ak.wwise.debug.enableAutomationMode"] = {}
    records, steps = [], []

    def run(name, command, arguments):
        code, payload = gateway.execute_gateway(["--state-dir", str(state), command, *arguments],
            env=env, client_factory=lambda _: client)
        assert code == 0, payload
        steps.append(ExpectedGatewayStep("tx01." + name, command, tuple(arguments)))
        records.append({"step_name": "tx01." + name, "succeeded": True,
                        "gateway_arguments": [command, *arguments], "payload": payload})
        return payload

    start = run("draft-start", "draft-start", ("debug.setAutomationMode",))
    def prefix(prior):
        return (start["draft"]["draft_id"], "--task-authority", start["task_authority"],
                "--expected-revision", str(prior["draft"]["revision"]))
    declared = run("declare", "draft-declare-debug-intent", (*prefix(start), "--enable"))
    checked = run("check", "draft-check", prefix(declared))
    preview = run("preview", "preview-from-draft", prefix(checked))
    tx = preview["transaction_id"]
    shown = run("show", "transaction-show", (tx, "--summary-only"))
    confirmed = run("confirm", "confirm", (tx, "--confirmation-token", shown["confirmation"]["token"]))
    executed = run("execute", "execute", (tx,))
    terminal = run("verify", "verify", (tx,))
    assert terminal["status"] == terminal["state"] == "result_schema_checked"
    assert terminal["ok"] is True and terminal["verified"] is False
    assert terminal["result_schema_checked"] is True
    assert all("agent_result" not in item for item in (shown, confirmed, executed))
    assert list(terminal)[-1] == "agent_result"
    artifact = TransactionStore(state).load_preview(tx).artifact
    assert terminal["agent_result"]["request"] == artifact["request"]
    evidence = validate_typed_draft_evidence(state_directory=state, steps=steps, broker_records=records)
    assert evidence["preview_binding"]["transaction_final_state"] == "result_schema_checked"
    for damage in ("missing", "non-mapping", "request", "transaction_id", "artifact_hash"):
        corrupt = deepcopy(records)
        result = corrupt[-1]["payload"]
        if damage == "missing":
            result.pop("agent_result")
        elif damage == "non-mapping":
            result["agent_result"] = []
        elif damage == "request":
            result["agent_result"]["request"]["arguments"]["enable"] = False
        else:
            result["agent_result"][damage] = "changed"
        with pytest.raises(TypedDraftEvidenceError):
            validate_typed_draft_evidence(state_directory=state, steps=steps, broker_records=corrupt)


@pytest.mark.skipif(os.name == "nt", reason="POSIX copied-command transport proof")
def test_public_metadata_agent_result_commands_reach_authenticated_broker_unchanged(tmp_path, monkeypatch):
    """Opaque metadata commands retain the accepted canonical candidate runner."""
    root = Path(__file__).resolve().parents[2]
    project = tmp_path / "Sandbox.wproj"
    project.write_text("<WwiseDocument/>", encoding="utf-8")
    fixture = tmp_path / "fixture.json"
    native = {"classId": 1, "name": "Sound", "type": "Sound", "details": "界\"\\" * 6000,
              "native": {"contract": {"type": ["object", "array"]}}}
    fixture.write_text(json.dumps({"version": "2025.1", "platform": "macosx",
        "process_path": str(tmp_path / "WwiseConsole"), "project_path": str(project),
        "objects": [], "fields": [], "native_type_rows": [native]}, ensure_ascii=False), encoding="utf-8")
    selection = ResponseBinding("types", "/agent_result/types/0/selection")
    steps = (
        ExpectedGatewayStep("types", "metadata", ("types",)),
        ExpectedGatewayStep("fields", "metadata", ("list", "--type-selection", selection)),
        ExpectedGatewayStep("query", "query-object", ("--type-selection", selection, "--max-results", "20")),
        ExpectedGatewayStep("detail", "metadata", ("types", "--selection", selection)),
        ExpectedGatewayStep("detail-next", "metadata", ("types", "--selection", selection,
            "--detail-page", ResponseBinding("detail", "/agent_result/next_detail_page"))),
    )
    workspace = tmp_path / "agent-workspace"
    installed = prepare_workspace_skill_install(workspace, root / "skills/waapi-skill")
    monkeypatch.chdir(workspace)
    payloads = {}
    with CodexGatewayBroker(skill_source=root / "skills/waapi-skill", expected_steps=steps,
        invocation_skill_source=installed, expected_wwise_version="2025.1",
        runner_environment={**os.environ, "PYTHONPATH": os.pathsep.join((str(WAAPI_SHIM_ROOT), str(root), str(root / "skills/waapi-skill"))),
            FIXTURE_ENV: str(fixture), "WWISE_WAAPI_HOST": "127.0.0.1", "WWISE_WAAPI_PORT": "31337"},
        working_root=tmp_path / "broker", transport="tcp") as broker:
        first = run_model_command(broker, ["metadata", "types"])
        (tmp_path / "metadata-types.stdout.txt").write_text(first.stdout, encoding="utf-8")
        (tmp_path / "metadata-types.stderr.txt").write_text(first.stderr, encoding="utf-8")
        (tmp_path / "metadata-authenticated-evidence.json").write_text(
            json.dumps(broker.evidence().as_dict(include_output=True), ensure_ascii=False), encoding="utf-8")
        assert first.returncode == 0, (first.stdout, first.stderr)
        payloads["types"] = json.loads(first.stdout[first.stdout.index("{"):])
        candidate = payloads["types"]["agent_result"]["types"][0]
        assert candidate["details_complete"] is False
        for name, field in (("fields", "fields_command"), ("query", "query_command"),
                ("detail", "detail_command"), ("detail-next", "next_command")):
            owner = payloads["detail"]["agent_result"] if name == "detail-next" else candidate
            command = owner[field]
            selected = command[command["copy_instruction"]["source_field"]]
            argv = shlex.split(selected)
            assert argv == command["full_argv"]
            # No model-visible rewrite inside agent_result: the original
            # candidate runner remains an explicitly accepted Broker path.
            assert Path(argv[1]) == broker.runner_path
            result = run_model_command(broker, argv[3:], runner_path=Path(argv[1]))
            assert list(result.args) == argv
            (tmp_path / f"metadata-{name}.stdout.txt").write_text(result.stdout, encoding="utf-8")
            assert result.returncode == 0, (name, result.stdout, result.stderr)
            payloads[name] = json.loads(result.stdout[result.stdout.index("{"):])
            assert list(payloads[name])[-1] == "agent_result"
        evidence = broker.evidence()
    assert evidence.passed, evidence
    assert all(row.authenticated and row.accepted and row.succeeded for row in evidence.records)
    assert payloads["query"]["agent_result"] == []
    assert payloads["detail"]["agent_result"]["next_detail_page"] is not None
    (tmp_path / "metadata-authenticated-evidence.json").write_text(
        json.dumps(evidence.as_dict(include_output=True), ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("no_event_reads", [False, True], ids=["original", "inspect"])
@pytest.mark.skipif(os.name == "nt", reason="POSIX developer transport/archive proof")
def test_public_compound_undo_replays_each_original_child_record(tmp_path, no_event_reads, monkeypatch):
    from tests.semantic.support.codex_compound_undo_business_agent_runner import (
        build_preview_only_compound_undo_steps, prepare_compound_undo_business_runtime,
    )
    from tests.semantic.support.codex_compound_undo_business_profile import load_compound_undo_business_profile
    root = Path(__file__).resolve().parents[2]
    unit = load_compound_undo_business_profile(root / "tests/semantic/data/compound-undo-business/profile.json").units[0]
    runtime = prepare_compound_undo_business_runtime(unit, tmp_path / "runtime")
    steps = build_preview_only_compound_undo_steps(runtime)
    if no_event_reads:
        expanded = []
        for step in steps:
            if step.subcommand == "draft-declare-undo-plan":
                arguments = list(step.arguments)
                arguments[4] = ResponseBinding("tx03.inspect-after-tx02", "/draft/revision")
                step = replace(step, arguments=tuple(arguments))
            expanded.append(step)
            if step.subcommand == "draft-check" and step.name.startswith(("tx01.", "tx02.")):
                label = step.name.split(".", 1)[0]
                expanded.append(ExpectedGatewayStep(label + ".inspect", "draft-inspect", (
                    ResponseBinding(label + ".draft-start", "/draft/draft_id"), "--task-authority",
                    ResponseBinding(label + ".draft-start", "/task_authority"))))
                expanded.append(ExpectedGatewayStep("tx03.inspect-after-" + label, "draft-inspect", (
                    ResponseBinding("tx03.draft-start", "/draft/draft_id"), "--task-authority",
                    ResponseBinding("tx03.draft-start", "/task_authority"))))
        steps = tuple(expanded)
    payloads, command_facts = {}, []
    workspace = tmp_path / "agent-workspace"
    installed = prepare_workspace_skill_install(workspace, root / "skills/waapi-skill")
    monkeypatch.chdir(workspace)
    with CodexGatewayBroker(skill_source=root / "skills/waapi-skill", expected_steps=steps,
        invocation_skill_source=installed,
        expected_wwise_version=unit.version, runner_environment={**os.environ,
            "PYTHONPATH": os.pathsep.join((str(WAAPI_SHIM_ROOT), str(root), str(root / "skills/waapi-skill"))),
            FIXTURE_ENV: str(runtime.fixture_path), "WWISE_WAAPI_HOST": "127.0.0.1", "WWISE_WAAPI_PORT": "31337"},
        working_root=tmp_path / "broker", transport="tcp") as broker:
        for step in steps:
            argv = [step.subcommand]
            for argument in step.arguments:
                if isinstance(argument, ResponseBinding):
                    value = payloads[argument.step]
                    for token in argument.pointer.lstrip("/").split("/"):
                        value = value[token]
                    argv.append(str(value))
                else:
                    argv.append(argument)
            runner_path = None
            for previous in reversed(tuple(payloads.values())):
                binding = previous.get("draft", {}).get("next_action_binding", {})
                for field in ("declaration", "check"):
                    selected = binding.get(field, {}).get("fixed_argv_prefix_copy")
                    if not isinstance(selected, str):
                        continue
                    copied = shlex.split(selected)
                    if copied[3:] == argv[:len(copied) - 3]:
                        runner_path = Path(copied[1])
                        break
                if runner_path is not None:
                    break
            result = run_model_command(broker, argv, runner_path=runner_path)
            (tmp_path / "broker-evidence.json").write_text(json.dumps(broker.evidence().as_dict(include_output=True)), encoding="utf-8")
            assert result.returncode == 0, (step.name, result.stdout, result.stderr)
            payloads[step.name] = json.loads(result.stdout)
            command_facts.append({"argv": list(result.args), "command": shlex.join(result.args),
                "exit_code": result.returncode, "status": "completed", "has_shell_operators": False,
                "parse_error": "", "parser_kind": "posix-native", "aggregated_output": result.stdout})
        evidence = broker.evidence()
    assert evidence.passed
    records = json.loads(json.dumps(evidence.as_dict(include_output=True)))["records"]
    replayed = validate_typed_draft_evidence(state_directory=tmp_path / "broker/state", steps=steps, broker_records=records)
    assert replayed["flow_count"] == 3
    parent = next(flow for flow in replayed["flows"] if flow["operation"] == "waapi.undoGroup")
    assert parent["audit_types"] == ["started", "settings.revised", "checked", "seal_reserved", "sealed"]
    assert parent["canonical_request"] == payloads["tx03.preview"]["agent_result"]["request"]
    assert [flow["operation"] for flow in replayed["flows"]] == ["waapi.undoGroup", "object.setNotes", "object.setName"]
    assert all(flow["audit_types"] == ["started", "handles.bound", "declaration.added", "checked"]
               for flow in replayed["flows"][1:])
    from tests.semantic import run_codex_skill_campaign as campaign
    continuation_errors = campaign.gateway_continuation_binding_errors(command_facts,
        json.loads(json.dumps(evidence.as_dict()))["records"], platform_name="posix",
        allow_compound_checked_child_handoff=True)
    assert not continuation_errors, continuation_errors
    campaign._validate_heavy_v3_broker_records(json.loads(json.dumps(evidence.as_dict()))["records"],
        task_root=tmp_path, steps=steps, command_records=command_facts,
        options=SimpleNamespace(skill_source=root / "skills/waapi-skill", windows_powershell_core_host=None),
        version=unit.version, label="developer authenticated compound transport",
        expected_project_modification_policy="ask_before_changes")
    archive_records = json.loads(json.dumps(evidence.as_dict()))["records"]
    for damage in ("child-policy", "child-authority", "stale-inspection"):
        if damage == "stale-inspection" and not no_event_reads:
            continue
        corrupted, facts = deepcopy(archive_records), deepcopy(command_facts)
        name = "tx01.inspect" if damage == "stale-inspection" else "tx01.draft-start"
        index = next(index for index, row in enumerate(corrupted) if row["step_name"] == name)
        payload = corrupted[index]["payload"]
        if damage == "child-policy":
            wrong = deepcopy(payloads["tx03.draft-start"]["session_context"])
            wrong["project_modification_policy"] = "allow_changes"
            wrong["one_time_introduction"]["facts"]["project_modification_policy"] = "allow_changes"
            payload["session_context"] = wrong
        elif damage == "child-authority":
            payload["task_authority"] = "da1-" + "0" * 40
        else:
            payload["draft"]["revision"] += 1
        corrupted[index]["payload_sha256"] = canonical_sha256(payload)
        facts[index]["aggregated_output"] = json.dumps(payload, ensure_ascii=False)
        with pytest.raises(campaign.CampaignEvidenceError):
            campaign._validate_heavy_v3_broker_records(corrupted, task_root=tmp_path,
                steps=steps, command_records=facts,
                options=SimpleNamespace(skill_source=root / "skills/waapi-skill", windows_powershell_core_host=None),
                version=unit.version, label="corrupted developer compound transport",
                expected_project_modification_policy="ask_before_changes")
    (tmp_path / "compound-command-facts.json").write_text(json.dumps(command_facts, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "compound-original-archive-evidence.json").write_text(json.dumps(replayed, ensure_ascii=False), encoding="utf-8")
    for damage in ("authority", "revision", "parent-capability", "child-order", "final-request"):
        corrupt = deepcopy(records)
        by_name = {record["step_name"]: record for record in corrupt}
        if damage == "authority":
            by_name["tx01.draft-start"]["payload"]["task_authority"] = "da1-" + "0" * 40
        elif damage == "revision":
            by_name["tx01.check"]["payload"]["draft"]["revision"] -= 1
        elif damage == "parent-capability":
            by_name["tx01.draft-start"]["gateway_arguments"][3] = "da1-" + "0" * 40
        elif damage == "child-order":
            argv = by_name["tx03.declare-undo-plan"]["gateway_arguments"]
            index = argv.index("--child-draft")
            argv[index:index + 6] = argv[index + 3:index + 6] + argv[index:index + 3]
        else:
            by_name["tx03.preview"]["payload"]["agent_result"]["request"]["arguments"]["calls"][0]["request"]["arguments"]["value"] = "changed"
        with pytest.raises(TypedDraftEvidenceError):
            validate_typed_draft_evidence(state_directory=tmp_path / "broker/state", steps=steps, broker_records=corrupt)
    from wwise_waapi.operation_drafts import _record_digest
    for damage in ("parent-authority", "parent-revision", "snapshot-source", "snapshot-revision", "connection"):
        copied = tmp_path / ("corrupted-child-state-" + damage)
        shutil.copytree(tmp_path / "broker/state", copied)
        child_id = payloads["tx01.draft-start"]["draft"]["draft_id"]
        parent_id = payloads["tx03.draft-start"]["draft"]["draft_id"]
        target = parent_id if damage.startswith("snapshot-") else child_id
        path = copied / "operation-drafts-v1/records" / (target + ".json")
        content = json.loads(path.read_text(encoding="utf-8"))
        if damage == "parent-authority":
            content["composition"]["compound_parent"]["task_authority"] = "da1-" + "0" * 40
        elif damage == "parent-revision":
            content["composition"]["compound_parent"]["expected_revision"] += 1
        elif damage == "connection":
            content["connection_binding"]["configuration"]["waapi_port"] += 1
        else:
            snapshot = content["composition"]["business_session"]["settings"]["undo_plan"]["children"][0]
            if damage == "snapshot-source":
                snapshot["source_draft_id"] = "od1-" + "0" * 32
            else:
                snapshot["source_revision"] -= 1
        content.pop("record_digest")
        content["record_digest"] = _record_digest(content)
        path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(TypedDraftEvidenceError):
            validate_typed_draft_evidence(state_directory=copied, steps=steps, broker_records=records)


@pytest.mark.skipif(os.name == "nt", reason="POSIX developer transport/archive proof")
def test_public_owned_lua_input_cleanup_preserves_original_formal_archive(tmp_path, monkeypatch):
    """The fake WAAPI result runs no Lua; only the original owned input is released."""
    from tests.semantic.support.codex_eval_protocol_v3 import build_transaction_protocol
    from tests.semantic import run_codex_skill_campaign as campaign
    root = Path(__file__).resolve().parents[2]
    project = tmp_path / "project/Sandbox.wproj"
    project.parent.mkdir()
    project.write_text("<WwiseDocument/>", encoding="utf-8")
    owned = tmp_path / "owned-lua-input"
    owned.mkdir()
    script = owned / "user-script.lua"
    script.write_text("return wa_args.request_id\n", encoding="utf-8")
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"version": "2025.1", "platform": "macosx", "objects": [], "fields": [],
        "process_path": str(tmp_path / "WwiseConsole"), "project_path": str(project),
        "lua_cli_result": {"result": 0}}), encoding="utf-8")
    protocol = build_transaction_protocol(({
        "contract": "waapi-skill.operation-request/v1", "version": "2025.1", "operation": "lua.executeCliFile",
        "arguments": {"script_file": str(script), "io_root": str(owned), "source_authority": "user_supplied_verbatim",
                      "wa_args": {"request_id": 'owned 界 "\\ input'}}},))
    steps = protocol.steps
    payloads, command_facts = {}, []
    workspace = tmp_path / "agent-workspace"
    installed = prepare_workspace_skill_install(workspace, root / "skills/waapi-skill")
    monkeypatch.chdir(workspace)
    with CodexGatewayBroker(skill_source=root / "skills/waapi-skill", expected_steps=steps,
        invocation_skill_source=installed, expected_wwise_version="2025.1", runner_environment={**os.environ,
            "PYTHONPATH": os.pathsep.join((str(WAAPI_SHIM_ROOT), str(root), str(root / "skills/waapi-skill"))),
            FIXTURE_ENV: str(fixture), "WWISE_WAAPI_HOST": "127.0.0.1", "WWISE_WAAPI_PORT": "31337"},
        working_root=tmp_path / "broker", transport="tcp") as broker:
        for step in steps:
            argv = [step.subcommand]
            for argument in step.arguments:
                if isinstance(argument, ResponseBinding):
                    value = payloads[argument.step]
                    for token in argument.pointer.lstrip("/").split("/"):
                        value = value[token]
                    argv.append(str(value))
                else:
                    argv.append(argument)
            runner_path = None
            for previous in reversed(tuple(payloads.values())):
                copied = previous.get("draft", {}).get("next_action_binding", {}).get("check", {}).get("fixed_argv_prefix_copy")
                if isinstance(copied, str) and shlex.split(copied)[3:] == argv:
                    runner_path = Path(shlex.split(copied)[1])
                    break
            result = run_model_command(broker, argv, runner_path=runner_path)
            (tmp_path / f"{step.name}.stdout.txt").write_text(result.stdout, encoding="utf-8")
            (tmp_path / "lua-broker-evidence.json").write_text(json.dumps(broker.evidence().as_dict(include_output=True), ensure_ascii=False), encoding="utf-8")
            assert result.returncode == 0, (step.name, result.stdout, result.stderr)
            payloads[step.name] = json.loads(result.stdout)
            command_facts.append({"argv": list(result.args), "command": shlex.join(result.args),
                "exit_code": result.returncode, "status": "completed", "has_shell_operators": False,
                "parse_error": "", "parser_kind": "posix-native", "aggregated_output": result.stdout})
        evidence = broker.evidence()
    assert evidence.passed, evidence
    records = json.loads(json.dumps(evidence.as_dict()))["records"]
    state = tmp_path / "broker/state"
    def replay_original_archive():
        campaign._validate_heavy_v3_broker_records(records, task_root=tmp_path, steps=steps,
            command_records=command_facts, options=SimpleNamespace(skill_source=root / "skills/waapi-skill", windows_powershell_core_host=None),
            version="2025.1", label="developer original owned Lua archive",
            expected_project_modification_policy="ask_before_changes")
    replay_original_archive()
    before = validate_typed_draft_evidence(state_directory=state, steps=steps, broker_records=records)
    terminal = payloads["tx01.verify"]
    assert terminal["status"] == "result_schema_checked" and terminal["verified"] is False
    assert list(terminal)[-1] == "agent_result"
    tx = terminal["transaction_id"]
    assert [event["event_type"] for event in TransactionStore(state).read_events(tx)].count("execution_completed") == 1
    script.unlink()
    owned.rmdir()
    with pytest.raises(TypedDraftEvidenceError):
        validate_typed_draft_evidence(state_directory=state, steps=steps, broker_records=records)
    after = validate_typed_draft_evidence(state_directory=state, steps=steps, broker_records=records,
        allow_cleaned_file_evidence=True)
    assert after == before
    replay_original_archive()
    (tmp_path / "lua-command-facts.json").write_text(json.dumps(command_facts, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "lua-original-archive-evidence.json").write_text(json.dumps(after, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("mixed", [False, True], ids=["two-undo-groups", "ordinary-and-undo"])
@pytest.mark.skipif(os.name == "nt", reason="POSIX developer transport/archive proof")
def test_public_sequential_drafts_partition_by_original_parent_capabilities(tmp_path, mixed, monkeypatch):
    from tests.semantic.support.codex_compound_undo_business_agent_runner import prepare_compound_undo_business_runtime
    from tests.semantic.support.codex_compound_undo_business_profile import load_compound_undo_business_profile
    from tests.semantic.support.codex_eval_protocol_v3 import (
        build_compound_undo_business_transaction_steps, build_object_lifecycle_business_transaction_steps,
    )
    root = Path(__file__).resolve().parents[2]
    unit = load_compound_undo_business_profile(root / "tests/semantic/data/compound-undo-business/profile.json").units[0]
    runtime = prepare_compound_undo_business_runtime(unit, tmp_path / "runtime")
    def scoped(prefix, group):
        return tuple(replace(step, name=prefix + "." + step.name, arguments=tuple(
            replace(argument, step=prefix + "." + argument.step) if isinstance(argument, ResponseBinding) else argument
            for argument in step.arguments)) for step in group)
    first = (build_object_lifecycle_business_transaction_steps(runtime.children[0].request, label="tx00")
             if mixed else build_compound_undo_business_transaction_steps(runtime.children,
                display_name="First owned group", label="tx03"))
    second = build_compound_undo_business_transaction_steps(runtime.children,
        display_name="Second owned group", label="tx03")
    steps = (*scoped("first", first), *scoped("second", second))
    env = set_gateway_config(gateway_env(tmp_path), wwise_version=unit.version)
    state = tmp_path / "public-state"
    client = LayoutClient(tmp_path, version=unit.version)
    client.responses["ak.wwise.core.object.get"] = {"return": [dict(unit.object)]}
    payloads, records = {}, []
    for step in steps:
        argv = [step.subcommand]
        for argument in step.arguments:
            if isinstance(argument, ResponseBinding):
                value = payloads[argument.step]
                for token in argument.pointer.lstrip("/").split("/"):
                    value = value[token]
                argv.append(str(value))
            else:
                argv.append(argument)
        code, payload = gateway.execute_gateway(["--state-dir", str(state), *argv],
            env=env, client_factory=lambda _: client)
        assert code == 0, (step.name, payload)
        payloads[step.name] = payload
        records.append({"step_name": step.name, "succeeded": True,
                        "gateway_arguments": argv, "payload": payload})
        (tmp_path / "sequential-public-receipts.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    # This actual public producer sequence precedes the formal admission check.
    # It does not claim authenticated Broker evidence until that admission works.
    validate_operation_draft_protocol_steps(steps)
    evidence = validate_typed_draft_evidence(state_directory=state, steps=steps, broker_records=records)
    assert evidence["flow_count"] == (4 if mixed else 6)
    payloads, command_facts = {}, []
    workspace = tmp_path / "agent-workspace"
    installed = prepare_workspace_skill_install(workspace, root / "skills/waapi-skill")
    monkeypatch.chdir(workspace)
    with CodexGatewayBroker(skill_source=root / "skills/waapi-skill", expected_steps=steps,
        invocation_skill_source=installed, expected_wwise_version=unit.version,
        runner_environment={**os.environ, "PYTHONPATH": os.pathsep.join((str(WAAPI_SHIM_ROOT), str(root), str(root / "skills/waapi-skill"))),
            FIXTURE_ENV: str(runtime.fixture_path), "WWISE_WAAPI_HOST": "127.0.0.1", "WWISE_WAAPI_PORT": "31337"},
        working_root=tmp_path / "broker", transport="tcp") as broker:
        for step in steps:
            argv = [step.subcommand]
            for argument in step.arguments:
                if isinstance(argument, ResponseBinding):
                    value = payloads[argument.step]
                    for token in argument.pointer.lstrip("/").split("/"):
                        value = value[token]
                    argv.append(str(value))
                else:
                    argv.append(argument)
            runner_path = None
            for previous in reversed(tuple(payloads.values())):
                binding = previous.get("draft", {}).get("next_action_binding", {})
                for field in ("declaration", "check"):
                    selected = binding.get(field, {}).get("fixed_argv_prefix_copy")
                    if isinstance(selected, str):
                        copied = shlex.split(selected)
                        if copied[3:] == argv[:len(copied) - 3]:
                            runner_path = Path(copied[1])
                            break
                if runner_path is not None:
                    break
            result = run_model_command(broker, argv, runner_path=runner_path)
            (tmp_path / "sequential-broker-evidence.json").write_text(json.dumps(broker.evidence().as_dict(include_output=True), ensure_ascii=False), encoding="utf-8")
            assert result.returncode == 0, (step.name, result.stdout, result.stderr)
            payloads[step.name] = json.loads(result.stdout)
            command_facts.append({"argv": list(result.args), "command": shlex.join(result.args),
                "exit_code": result.returncode, "status": "completed", "has_shell_operators": False,
                "parse_error": "", "parser_kind": "posix-native", "aggregated_output": result.stdout})
        broker_evidence = broker.evidence()
    assert broker_evidence.passed, broker_evidence
    authenticated = json.loads(json.dumps(broker_evidence.as_dict()))["records"]
    replayed = validate_typed_draft_evidence(state_directory=tmp_path / "broker/state", steps=steps, broker_records=authenticated)
    assert replayed["root_count"] == 2 and replayed["flow_count"] == (4 if mixed else 6)
    from tests.semantic import run_codex_skill_campaign as campaign
    campaign._validate_heavy_v3_broker_records(authenticated, task_root=tmp_path, steps=steps,
        command_records=command_facts, options=SimpleNamespace(skill_source=root / "skills/waapi-skill", windows_powershell_core_host=None),
        version=unit.version, label="developer independent Draft root transport",
        expected_project_modification_policy="ask_before_changes")
    first_start = "first.tx00.draft-start" if mixed else "first.tx03.draft-start"
    child_index = next(index for index, step in enumerate(steps) if step.name == "second.tx01.draft-start")
    arguments = list(steps[child_index].arguments)
    for index, pointer in ((0, "/draft/draft_id"), (2, "/task_authority"), (4, "/draft/revision")):
        arguments[index] = ResponseBinding(first_start, pointer)
    corrupted_protocol = list(steps)
    corrupted_protocol[child_index] = replace(steps[child_index], arguments=tuple(arguments))
    with pytest.raises(ValueError):
        validate_operation_draft_protocol_steps(corrupted_protocol)
    from wwise_waapi.operation_drafts import _record_digest
    for damage in ("cross-parent-child", "cross-parent-snapshot"):
        copied = tmp_path / damage
        shutil.copytree(tmp_path / "broker/state", copied)
        target = payloads["second.tx01.draft-start" if damage == "cross-parent-child" else "second.tx03.draft-start"]["draft"]["draft_id"]
        path = copied / "operation-drafts-v1/records" / (target + ".json")
        content = json.loads(path.read_text(encoding="utf-8"))
        if damage == "cross-parent-child":
            content["composition"]["compound_parent"] = {
                "draft_id": payloads[first_start]["draft"]["draft_id"],
                "task_authority": payloads[first_start]["task_authority"], "expected_revision": 1}
        else:
            source = first_start if mixed else "first.tx01.draft-start"
            content["composition"]["business_session"]["settings"]["undo_plan"]["children"][0]["source_draft_id"] = payloads[source]["draft"]["draft_id"]
        content.pop("record_digest")
        content["record_digest"] = _record_digest(content)
        path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(TypedDraftEvidenceError):
            validate_typed_draft_evidence(state_directory=copied, steps=steps, broker_records=authenticated)
    (tmp_path / "sequential-command-facts.json").write_text(json.dumps(command_facts, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "sequential-original-archive-evidence.json").write_text(json.dumps(replayed, ensure_ascii=False), encoding="utf-8")
