from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic.support.codex_business_oracle_plan_v3 import (
    write_business_oracle_plan,
)
from tests.semantic.support import codex_task_runner_v3 as task_runner
from tests.semantic.support.codex_eval_protocol_v3 import V3GatewayProtocol
from tests.semantic.support.codex_gateway_broker import (
    ExpectedGatewayStep,
    GatewayBrokerReconciliation,
)
from tests.semantic.support.codex_harness import (
    CodexInfrastructureError,
    CodexInfrastructureFailure,
)
from tests.semantic.support.codex_task_runner_v3 import _grade_common_turn
from tests.semantic.support.codex_prompt_provenance_v3 import write_prompt_provenance


def _result(*, turn: int, gateway_count: int):
    reads = ("SKILL.md", "references/waapi-operate.md") if turn == 1 else ()
    read_commands = tuple(f"cat {name}" for name in reads)
    command_records = tuple(SimpleNamespace(command=value) for value in read_commands) + tuple(
        SimpleNamespace(command=f"gateway {index}") for index in range(gateway_count)
    )
    return SimpleNamespace(
        isolation_audit=SimpleNamespace(passed=True),
        prompt_audit=SimpleNamespace(has_memory=False, passed=True),
        exit_status=0,
        timed_out=False,
        session_audit=SimpleNamespace(passed=True),
        file_change_count=0,
        collab_call_count=0,
        created_files=(),
        modified_files=(),
        deleted_files=(),
        created_source_files=(),
        modified_source_files=(),
        deleted_source_files=(),
        skill_tree_unchanged=True,
        command_facts=SimpleNamespace(
            allowed_read_commands=read_commands,
            skill_read_files=reads,
            command_records=command_records,
            gateway_attempt_commands=tuple(range(gateway_count)),
            discovery_commands=(),
            direct_waapi_client_commands=(),
            write_like_commands=(),
            unexpected_commands=(),
            non_gateway_unexpected_commands=(),
        ),
    )


def test_common_grade_accepts_first_and_resumed_turn_shapes() -> None:
    for turn, count in ((1, 2), (2, 4)):
        errors, gates = _grade_common_turn(
            _result(turn=turn, gateway_count=count),
            turn_index=turn,
            required_reference="references/waapi-operate.md",
            expected_gateway_count=count,
        )
        assert errors == ()
        assert all(gates.values())


def test_common_grade_rejects_reference_reread_on_resume() -> None:
    result = _result(turn=1, gateway_count=4)
    errors, _ = _grade_common_turn(
        result,
        turn_index=2,
        required_reference="references/waapi-operate.md",
        expected_gateway_count=4,
    )
    assert "skill_reads_exact" in errors


def test_common_grade_allows_one_broker_proven_terminal_execute_exit_two() -> None:
    result = _result(turn=2, gateway_count=3)
    terminal_command = "gateway execute tx-1"
    result.command_facts.gateway_attempt_commands = (
        "gateway show tx-1",
        "gateway confirm tx-1",
        terminal_command,
    )
    result.command_facts.unexpected_commands = (terminal_command,)

    errors, gates = _grade_common_turn(
        result,
        turn_index=2,
        required_reference="references/waapi-operate.md",
        expected_gateway_count=3,
        expected_terminal_execute_exit2_count=1,
    )

    assert errors == ()
    assert gates["no_unexpected_commands"] is True


def test_common_grade_rejects_r4_migration_commands_with_suppressed_cli_json() -> None:
    result = _result(turn=2, gateway_count=3)
    show = "gateway transaction-show tx-1 --summary-only"
    confirm = (
        "gateway confirm tx-1 --confirmation-token "
        "ct1-0123456789abcdefghjkmnpq"
    )
    execute = "gateway execute tx-1"
    result.command_facts.gateway_attempt_commands = (show, confirm, execute)
    # This reproduces the r4 evidence shape: the broker accepted the exact
    # protocol, but the model-side command events exposed no JSON for show and
    # confirm, so the ordinary CLI classifier could not authenticate them.
    result.command_facts.unexpected_commands = (show, confirm)

    errors, gates = _grade_common_turn(
        result,
        turn_index=2,
        required_reference="references/waapi-operate.md",
        expected_gateway_count=3,
        expected_terminal_execute_exit2_count=0,
    )

    assert "no_unexpected_commands" in errors
    assert gates["no_unexpected_commands"] is False


def test_common_grade_does_not_hide_unproven_or_non_gateway_unexpected_commands() -> None:
    result = _result(turn=2, gateway_count=3)
    result.command_facts.gateway_attempt_commands = (
        "gateway show tx-1",
        "gateway confirm tx-1",
        "gateway execute tx-1",
    )
    result.command_facts.unexpected_commands = ("python scratch.py",)
    result.command_facts.non_gateway_unexpected_commands = ("python scratch.py",)

    errors, _ = _grade_common_turn(
        result,
        turn_index=2,
        required_reference="references/waapi-operate.md",
        expected_gateway_count=3,
        expected_terminal_execute_exit2_count=1,
    )

    assert "no_unexpected_commands" in errors


class _FakeBrokerEvidence:
    def __init__(
        self,
        *,
        expected_names: tuple[str, ...],
        consumed_count: int,
        terminal_indeterminate: bool = False,
    ) -> None:
        self.expected_step_names = expected_names
        self.consumed_step_names = expected_names[:consumed_count]
        self.records = tuple(
            SimpleNamespace(
                sequence=index,
                step_name=name,
                succeeded=True,
                runner_exit_code=(
                    2
                    if terminal_indeterminate and index == consumed_count
                    else 0
                ),
            )
            for index, name in enumerate(self.consumed_step_names, start=1)
        )
        self.passed = consumed_count == len(expected_names)
        self.complete = False
        self.terminal_state = (
            "INDETERMINATE" if terminal_indeterminate else "RUNNING"
        )
        self.terminal_indeterminate = terminal_indeterminate

    def as_dict(self, *, include_output: bool = False) -> dict[str, object]:
        records: list[dict[str, object]] = [
            {"sequence": record.sequence, "step_name": record.step_name}
            for record in self.records
        ]
        if include_output:
            for record in records:
                record.update(
                    {"stdout": "must-be-filtered", "stderr": "must-be-filtered"}
                )
        return {
            "expected_step_names": list(self.expected_step_names),
            "consumed_step_names": list(self.consumed_step_names),
            "records": records,
            "passed": self.passed,
        }


def _task_result(
    *,
    thread_id: str,
    label: str,
    has_command: bool = False,
) -> SimpleNamespace:
    command = "python scratch.py"
    result = SimpleNamespace(
        thread_id=thread_id,
        stdout=f'{{"type":"{label}"}}\n',
        stderr=f"{label}-stderr\n",
        final_response=f"{label}-final",
        timed_out=False,
        collab_call_count=0,
        file_change_count=0,
        created_files=(),
        modified_files=(),
        deleted_files=(),
        created_source_files=(),
        modified_source_files=(),
        deleted_source_files=(),
        skill_tree_sha256_before="a" * 64,
        skill_tree_sha256_after="a" * 64,
        skill_tree_unchanged=True,
        prompt_audit=SimpleNamespace(passed=True, has_memory=False),
        isolation_audit=SimpleNamespace(passed=True),
        session_audit=SimpleNamespace(
            collab_call_count=0,
            file_change_count=0,
            command_started_count=1 if has_command else 0,
            command_completed_count=1 if has_command else 0,
            incomplete_command_count=0,
            unexpected_item_types=(),
            invalid_json_line_count=0,
        ),
        command_facts=SimpleNamespace(
            commands=(command,) if has_command else (),
            inline_python_commands=(command,) if has_command else (),
            direct_waapi_client_commands=(),
            write_like_commands=(command,) if has_command else (),
            gateway_commands=(),
            discovery_commands=(),
            skill_read=False,
            gateway_before_discovery=False,
            command_records=(SimpleNamespace(command=command),) if has_command else (),
            gateway_attempt_commands=(),
            gateway_subcommands=(),
            gateway_results=(),
            gateway_evidence_apis=(),
            allowed_read_commands=(),
            skill_read_files=(),
            unexpected_commands=(command,) if has_command else (),
            non_gateway_unexpected_commands=(command,) if has_command else (),
        ),
    )
    result.facts_dict = lambda: {
        "thread_id": thread_id,
        "label": label,
        "stdout_archived_separately": True,
    }
    return result


def _install_task_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failure_turn: int,
    failed_result_has_command: bool = False,
    broker_action_on_failure: bool = False,
    broker_close_failure: bool = False,
) -> tuple[CodexInfrastructureError, list[object]]:
    instances: list[object] = []
    expected_names = ("first", "second")
    secret_message = "SECRET-QUOTA-MESSAGE-MUST-NOT-ENTER-SIDECAR"
    failure = CodexInfrastructureFailure(
        category="quota_or_rate_limit",
        message=secret_message,
        turn_failed=True,
        timed_out=False,
        agent_item_event_count=0,
    )
    infrastructure_result = _task_result(
        thread_id="",
        label="infrastructure-failure",
        has_command=failed_result_has_command,
    )
    infrastructure_result.final_response = ""
    infrastructure_error = CodexInfrastructureError(failure, infrastructure_result)  # type: ignore[arg-type]

    class FakeBroker:
        def __init__(self, **_: object) -> None:
            self.active = False
            self.consumed_count = 0
            self.evidence_calls_while_active: list[int] = []
            instances.append(self)

        def __enter__(self) -> "FakeBroker":
            self.active = True
            return self

        def __exit__(self, *_: object) -> None:
            self.active = False
            if broker_close_failure:
                raise RuntimeError("synthetic broker close failed")

        def model_environment_overrides(self) -> dict[str, str]:
            return {}

        def evidence(self) -> _FakeBrokerEvidence:
            assert self.active is True
            self.evidence_calls_while_active.append(self.consumed_count)
            return _FakeBrokerEvidence(
                expected_names=expected_names,
                consumed_count=self.consumed_count,
            )

        def reconcile_prefix(
            self,
            _: object,
            *,
            expected_step_count: int,
        ) -> GatewayBrokerReconciliation:
            assert expected_step_count == self.consumed_count
            return GatewayBrokerReconciliation(
                passed=True,
                observed_command_count=expected_step_count,
                accepted_record_count=expected_step_count,
                errors=(),
            )

    class FakeTask:
        def __init__(self, config: object, *_: object, **__: object) -> None:
            self.broker = instances[-1]
            workspace = Path(getattr(config, "workspace"))
            receipt_path = workspace.parent / task_runner.PROMPT_MATERIALIZATION_FILE
            assert receipt_path.is_file()
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            plan_path = Path(receipt["business_oracle_plan_path"])
            assert plan_path == workspace.parents[1] / "business-oracle-plan.json"
            assert receipt["business_oracle_plan_sha256"] == hashlib.sha256(
                plan_path.read_bytes()
            ).hexdigest()

        def __enter__(self) -> "FakeTask":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def run_initial(self, _: str, *, output_dir: Path) -> SimpleNamespace:
            del output_dir
            if failure_turn == 1:
                if broker_action_on_failure:
                    self.broker.consumed_count = 1  # type: ignore[attr-defined]
                raise infrastructure_error
            self.broker.consumed_count = 1  # type: ignore[attr-defined]
            return _task_result(thread_id="thread-prior", label="turn-one")

        def run_followup(self, _: str, *, output_dir: Path) -> SimpleNamespace:
            del output_dir
            if failure_turn == 2:
                if broker_action_on_failure:
                    self.broker.consumed_count = 2  # type: ignore[attr-defined]
                raise infrastructure_error
            raise AssertionError("unexpected successful follow-up")

    monkeypatch.setattr(task_runner, "CodexGatewayBroker", FakeBroker)
    monkeypatch.setattr(task_runner, "CodexCliTask", FakeTask)
    monkeypatch.setattr(
        task_runner,
        "_gateway_candidate_argvs",
        lambda *_args, **_kwargs: (("accepted-gateway-command",),),
    )
    monkeypatch.setattr(
        task_runner,
        "_grade_common_turn",
        lambda *_args, **_kwargs: ((), {"focused_test_gate": True}),
    )
    return infrastructure_error, instances


def _install_terminal_indeterminate_task_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> list[int]:
    expected_names = ("tx01.execute", "tx01.verify")
    graded_gateway_counts: list[int] = []

    class FakeBroker:
        def __init__(self, **_: object) -> None:
            self.active = False
            self.consumed_count = 0

        def __enter__(self) -> "FakeBroker":
            self.active = True
            return self

        def __exit__(self, *_: object) -> None:
            self.active = False

        def model_environment_overrides(self) -> dict[str, str]:
            return {}

        def evidence(self) -> _FakeBrokerEvidence:
            assert self.active is True
            return _FakeBrokerEvidence(
                expected_names=expected_names,
                consumed_count=self.consumed_count,
                terminal_indeterminate=self.consumed_count == 1,
            )

        def reconcile_prefix(
            self,
            _: object,
            *,
            expected_step_count: int,
        ) -> GatewayBrokerReconciliation:
            assert expected_step_count == 1
            return GatewayBrokerReconciliation(
                passed=True,
                observed_command_count=1,
                accepted_record_count=1,
                errors=(),
            )

    class FakeTask:
        def __init__(self, _config: object, *_: object, **__: object) -> None:
            return None

        def __enter__(self) -> "FakeTask":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def run_initial(self, _: str, *, output_dir: Path) -> SimpleNamespace:
            del output_dir
            broker.consumed_count = 1
            return _task_result(thread_id="thread-indeterminate", label="turn-one")

        def run_followup(self, _: str, *, output_dir: Path) -> SimpleNamespace:
            del output_dir
            raise AssertionError("verify follow-up must not run after indeterminate execute")

    broker = FakeBroker()
    monkeypatch.setattr(task_runner, "CodexGatewayBroker", lambda **_: broker)
    monkeypatch.setattr(task_runner, "CodexCliTask", FakeTask)
    monkeypatch.setattr(
        task_runner,
        "_gateway_candidate_argvs",
        lambda *_args, **_kwargs: (("gateway", "execute"),),
    )

    def grade(*_args: object, **kwargs: object) -> tuple[tuple[str, ...], dict[str, bool]]:
        graded_gateway_counts.append(int(kwargs["expected_gateway_count"]))
        return (), {"focused_test_gate": True}

    monkeypatch.setattr(task_runner, "_grade_common_turn", grade)
    return graded_gateway_counts


def _run_infrastructure_task(
    tmp_path: Path,
    *,
    prompts: tuple[str, ...],
    plan_tamper: str | None = None,
    protocol: V3GatewayProtocol | None = None,
) -> Path:
    skill_source = tmp_path / "skill"
    skill_source.mkdir()
    scenario_root = tmp_path / "scenario"
    (scenario_root / "evidence").mkdir(parents=True)
    (scenario_root / "owned").mkdir()
    task_root = scenario_root / "evidence" / "codex-task"
    if protocol is None:
        protocol = V3GatewayProtocol(
            steps=(
                ExpectedGatewayStep(name="first", subcommand="call"),
                ExpectedGatewayStep(name="second", subcommand="call"),
            ),
            turn_prefix_counts=(1, 2),
        )
    scenario = SimpleNamespace(
        id="SCENARIO-INFRA-01",
        api="ak.wwise.core.object.create",
        versions=("2022.1",),
        prompt=prompts[0],
        prompt_sha256=hashlib.sha256(prompts[0].encode("utf-8")).hexdigest(),
        visible_inputs=(),
        fixture={},
        primary_dispatch=SimpleNamespace(count=1),
        confirmation_turn_count=max(0, len(prompts) - 1),
        confirmation_prompt=prompts[1] if len(prompts) > 1 else None,
        render_prompt=lambda values: prompts[0] if not values else "",
    )
    provenance = write_prompt_provenance(
        scenario=scenario,
        version="2022.1",
        scenario_root=scenario_root,
        prompts=prompts,
        visible_values={},
        protocol=protocol,
    )
    business_oracle_plan = write_business_oracle_plan(
        scenario_id=scenario.id,
        version="2022.1",
        api=scenario.api,
        runner="project",
        family="object",
        scenario_root=scenario_root,
        fixture_spec={
            "kind": "scenario_fixture",
            "sha256": hashlib.sha256(b"{}").hexdigest(),
        },
        protocol_sha256=provenance.payload["protocol"]["sha256"],
        provenance_sha256=provenance.sha256,
        primary_dispatch_count=1,
        payload_bindings={
            "primary_steps": ["first", "second"],
            "verification_steps": [],
        },
        assertion_ids=("common.task-receipt",),
        static_expectation={},
        live_binding={},
        delta_rules=(),
    )
    if plan_tamper == "missing":
        business_oracle_plan.path.unlink()
    elif plan_tamper == "rewrite":
        rewritten = dict(business_oracle_plan.payload)
        rewritten["assertion_ids"] = ["common.rewritten-after-seal"]
        business_oracle_plan.path.write_text(
            json.dumps(
                rewritten,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    elif plan_tamper == "evidence_sha":
        business_oracle_plan = replace(
            business_oracle_plan,
            sha256="f" * 64,
        )
    elif plan_tamper is not None:
        raise AssertionError(f"unknown plan tamper: {plan_tamper}")
    task_runner.run_v3_codex_task(
        scenario_id="SCENARIO-INFRA-01",
        version="2022.1",
        scenario=scenario,
        prompts=prompts,
        protocol=protocol,
        task_root=task_root,
        skill_source=skill_source,
        codex_binary=tmp_path / "codex",
        auth_json=tmp_path / "auth.json",
        model="gpt-test",
        reasoning_effort="medium",
        service_tier="default",
        timeout_seconds=10.0,
        runner_environment={},
        required_reference="references/waapi-operate.md",
        business_oracle_plan=business_oracle_plan,
    )
    return task_root


def test_task_runner_stops_at_exact_indeterminate_execute_without_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graded_gateway_counts = _install_terminal_indeterminate_task_fakes(monkeypatch)
    protocol = V3GatewayProtocol(
        steps=(
            ExpectedGatewayStep(
                name="tx01.execute",
                subcommand="execute",
                allowed_exit_codes=(0, 2),
            ),
            ExpectedGatewayStep(name="tx01.verify", subcommand="verify"),
        ),
        turn_prefix_counts=(2,),
    )

    task_root = _run_infrastructure_task(
        tmp_path,
        prompts=("请执行已经确认的修改。",),
        protocol=protocol,
    )

    payload = json.loads((task_root / "task-result.json").read_text(encoding="utf-8"))
    assert payload["turn_count"] == 1
    assert payload["passed"] is False
    assert payload["broker"]["consumed_step_names"] == ["tx01.execute"]
    assert graded_gateway_counts == [1]
    assert not (task_root / "turns" / "turn-02").exists()


@pytest.mark.parametrize("plan_tamper", ("missing", "rewrite", "evidence_sha"))
def test_business_plan_failure_prevents_first_codex_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plan_tamper: str,
) -> None:
    def forbidden_constructor(*_: object, **__: object) -> object:
        raise AssertionError("Codex or broker was constructed before plan validation")

    monkeypatch.setattr(task_runner, "CodexGatewayBroker", forbidden_constructor)
    monkeypatch.setattr(task_runner, "CodexCliTask", forbidden_constructor)

    with pytest.raises(task_runner.V3TaskRunnerError, match="business-oracle plan"):
        _run_infrastructure_task(
            tmp_path,
            prompts=("first natural prompt", "second natural prompt"),
            plan_tamper=plan_tamper,
        )

    task_root = tmp_path / "scenario" / "evidence" / "codex-task"
    assert not (task_root / task_runner.PROMPT_MATERIALIZATION_FILE).exists()
    assert not (task_root / "agent-workspace").exists()


@pytest.mark.parametrize(
    ("failure_turn", "expected_prior_count", "expected_previous_prefix", "prior_thread_id"),
    (
        (1, 0, 0, None),
        (2, 1, 1, "thread-prior"),
    ),
)
def test_codex_infrastructure_failure_archives_closed_fixed_path_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_turn: int,
    expected_prior_count: int,
    expected_previous_prefix: int,
    prior_thread_id: str | None,
) -> None:
    prompts = ("first natural prompt", "second natural prompt")
    infrastructure_error, broker_instances = _install_task_fakes(
        monkeypatch,
        failure_turn=failure_turn,
    )

    with pytest.raises(CodexInfrastructureError) as caught:
        _run_infrastructure_task(tmp_path, prompts=prompts)

    assert caught.value is infrastructure_error
    task_root = tmp_path / "scenario" / "evidence" / "codex-task"
    failed_turn_root = task_root / "turns" / f"turn-{failure_turn:02d}"
    sidecar_path = task_root / "infrastructure-failure.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert set(sidecar) == {
        "contract",
        "scenario_id",
        "version",
        "failed_turn_index",
        "expected_turn_count",
        "prior_completed_turn_count",
        "previous_broker_prefix",
        "expected_failed_turn_prefix",
        "prior_thread_id",
        "prompt_sha256",
        "failure",
        "artifact_sha256",
    }
    assert sidecar["contract"] == task_runner.TASK_INFRASTRUCTURE_FAILURE_CONTRACT
    assert sidecar["scenario_id"] == "SCENARIO-INFRA-01"
    assert sidecar["version"] == "2022.1"
    assert sidecar["failed_turn_index"] == failure_turn
    assert sidecar["expected_turn_count"] == 2
    assert sidecar["prior_completed_turn_count"] == expected_prior_count
    assert sidecar["previous_broker_prefix"] == expected_previous_prefix
    assert sidecar["expected_failed_turn_prefix"] == failure_turn
    assert sidecar["prior_thread_id"] == prior_thread_id
    assert sidecar["prompt_sha256"] == hashlib.sha256(
        prompts[failure_turn - 1].encode("utf-8")
    ).hexdigest()
    assert sidecar["failure"] == {
        "category": "quota_or_rate_limit",
        "turn_failed": True,
        "timed_out": False,
        "agent_item_event_count": 0,
    }
    assert "SECRET-QUOTA-MESSAGE-MUST-NOT-ENTER-SIDECAR" not in sidecar_path.read_text(
        encoding="utf-8"
    )

    expected_artifact_paths = {
        task_runner.PROMPT_MATERIALIZATION_FILE,
        f"turns/turn-{failure_turn:02d}/prompt.txt",
        f"turns/turn-{failure_turn:02d}/events.jsonl",
        f"turns/turn-{failure_turn:02d}/stderr.txt",
        f"turns/turn-{failure_turn:02d}/final.txt",
        f"turns/turn-{failure_turn:02d}/codex-facts.json",
        "broker-evidence.json",
    }
    assert set(sidecar["artifact_sha256"]) == expected_artifact_paths
    for relative_path, digest in sidecar["artifact_sha256"].items():
        assert digest == hashlib.sha256((task_root / relative_path).read_bytes()).hexdigest()

    broker_payload = json.loads((task_root / "broker-evidence.json").read_text(encoding="utf-8"))
    assert broker_payload["consumed_step_names"] == ["first"][:expected_prior_count]
    assert len(broker_payload["records"]) == expected_prior_count
    assert [record["step_name"] for record in broker_payload["records"]] == (
        ["first"][:expected_prior_count]
    )
    assert "stdout" not in json.dumps(broker_payload)
    assert "stderr" not in json.dumps(broker_payload)
    assert broker_instances[0].evidence_calls_while_active[-1] == expected_prior_count
    assert not (task_root / "agent-workspace").exists()
    assert not (task_root / "task-result.json").exists()
    if failure_turn == 2:
        prior_turn_root = task_root / "turns" / "turn-01"
        assert (prior_turn_root / "turn-grade.json").is_file()
        assert (prior_turn_root / "prompt.txt").read_text(encoding="utf-8") == (
            prompts[0] + "\n"
        )
    assert (failed_turn_root / "prompt.txt").read_text(encoding="utf-8") == (
        prompts[failure_turn - 1] + "\n"
    )


def test_codex_infrastructure_archive_failure_masks_retryable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, broker_instances = _install_task_fakes(monkeypatch, failure_turn=1)

    def fail_archive(*_: object, **__: object) -> None:
        raise OSError("archive write failed")

    monkeypatch.setattr(task_runner, "_archive_infrastructure_failure", fail_archive)

    with pytest.raises(OSError, match="archive write failed"):
        _run_infrastructure_task(
            tmp_path,
            prompts=("first natural prompt", "second natural prompt"),
        )

    assert broker_instances[0].evidence_calls_while_active == [0]
    assert not (
        tmp_path / "scenario" / "evidence" / "codex-task" / "infrastructure-failure.json"
    ).exists()


def test_broker_close_failure_replaces_retryable_infrastructure_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, broker_instances = _install_task_fakes(
        monkeypatch,
        failure_turn=1,
        broker_close_failure=True,
    )

    with pytest.raises(RuntimeError, match="synthetic broker close failed"):
        _run_infrastructure_task(
            tmp_path,
            prompts=("first natural prompt", "second natural prompt"),
        )

    assert broker_instances[0].evidence_calls_while_active == [0]
    assert (
        tmp_path / "scenario" / "evidence" / "codex-task" / "infrastructure-failure.json"
    ).is_file()


@pytest.mark.parametrize(
    ("failure_turn", "fake_options", "expected_gate", "expected_last_prefix"),
    (
        (1, {"failed_result_has_command": True}, "command_facts_empty", 0),
        (2, {"broker_action_on_failure": True}, "broker_prefix_exact", 2),
    ),
)
def test_contradictory_infrastructure_failure_is_not_archived_as_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_turn: int,
    fake_options: dict[str, bool],
    expected_gate: str,
    expected_last_prefix: int,
) -> None:
    infrastructure_error, broker_instances = _install_task_fakes(
        monkeypatch,
        failure_turn=failure_turn,
        **fake_options,
    )

    with pytest.raises(task_runner.V3TaskRunnerError, match=expected_gate) as caught:
        _run_infrastructure_task(
            tmp_path,
            prompts=("first natural prompt", "second natural prompt"),
        )

    assert caught.value is not infrastructure_error
    assert broker_instances[0].evidence_calls_while_active[-1] == expected_last_prefix
    task_root = tmp_path / "scenario" / "evidence" / "codex-task"
    assert not (task_root / "infrastructure-failure.json").exists()
    assert not (task_root / "broker-evidence.json").exists()
    if failure_turn == 2:
        assert (task_root / "turns" / "turn-01" / "turn-grade.json").is_file()


def test_incomplete_codex_command_lifecycle_is_archived_as_non_retryable_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = (
        "python /skill/scripts/run.py gateway.py --timeout 120 wait-topic "
        "ak.wwise.core.soundbank.generated --event-count 4"
    )
    events = (
        {"type": "thread.started", "thread_id": "thread-orphaned"},
        {"type": "turn.started"},
        {
            "type": "item.started",
            "item": {
                "id": "item_gateway",
                "type": "command_execution",
                "command": command,
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "item_final",
                "type": "agent_message",
                "text": "未收到完整结果。",
            },
        },
        {"type": "turn.completed"},
    )
    result = _task_result(
        thread_id="thread-orphaned",
        label="orphaned-command",
    )
    result.stdout = "\n".join(
        json.dumps(event, ensure_ascii=False) for event in events
    ) + "\n"
    result.stderr = (
        "codex_core::session: failed to record rollout items: "
        "thread thread-orphaned not found\n"
    )
    result.final_response = "未收到完整结果。"
    result.session_audit = SimpleNamespace(
        passed=False,
        collab_call_count=0,
        file_change_count=0,
        command_started_count=1,
        command_completed_count=0,
        incomplete_command_count=1,
        unexpected_item_types=(),
        invalid_json_line_count=0,
    )
    result.facts_dict = lambda: {
        "thread_id": "thread-orphaned",
        "session_audit": {
            "command_started_count": 1,
            "command_completed_count": 0,
            "incomplete_command_count": 1,
            "passed": False,
        },
    }

    class FakeBroker:
        def __init__(self, **_: object) -> None:
            self.evidence_value = _FakeBrokerEvidence(
                expected_names=("first", "second"),
                consumed_count=0,
            )

        def __enter__(self) -> "FakeBroker":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def model_environment_overrides(self) -> dict[str, str]:
            return {}

        def evidence(self) -> _FakeBrokerEvidence:
            return self.evidence_value

        def reconcile_prefix(
            self,
            _commands: object,
            *,
            expected_step_count: int,
        ) -> GatewayBrokerReconciliation:
            assert expected_step_count == 1
            return GatewayBrokerReconciliation(
                passed=False,
                observed_command_count=0,
                accepted_record_count=0,
                errors=("missing completed command",),
            )

    class FakeTask:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def __enter__(self) -> "FakeTask":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def run_initial(self, _prompt: str, *, output_dir: Path) -> SimpleNamespace:
            del output_dir
            return result

        def run_followup(self, _prompt: str, *, output_dir: Path) -> SimpleNamespace:
            del output_dir
            raise AssertionError("blocked task must not reach a follow-up turn")

    monkeypatch.setattr(task_runner, "CodexGatewayBroker", FakeBroker)
    monkeypatch.setattr(task_runner, "CodexCliTask", FakeTask)
    monkeypatch.setattr(
        task_runner,
        "_gateway_candidate_argvs",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        task_runner,
        "_grade_common_turn",
        lambda *_args, **_kwargs: (
            ("one_completed_turn", "gateway_count_exact"),
            {"one_completed_turn": False, "gateway_count_exact": False},
        ),
    )

    with pytest.raises(task_runner.V3CommandLifecycleError, match="fresh sandbox"):
        _run_infrastructure_task(
            tmp_path,
            prompts=("first natural prompt", "second natural prompt"),
        )

    task_root = tmp_path / "scenario" / "evidence" / "codex-task"
    sidecar_path = task_root / "command-lifecycle-failure.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["contract"] == task_runner.TASK_COMMAND_LIFECYCLE_FAILURE_CONTRACT
    assert sidecar["non_retryable"] is True
    assert sidecar["fresh_sandbox_required"] is True
    assert sidecar["incomplete_command_count"] == 1
    assert sidecar["anomalies"] == [
        {
            "event_index": None,
            "phase": "started_without_completed",
            "item_id": "item_gateway",
            "command": command,
            "status": "in_progress",
        }
    ]
    assert (task_root / "command-lifecycle-broker-evidence.json").is_file()
    assert not (task_root / "infrastructure-failure.json").exists()
    assert not (task_root / "task-result.json").exists()
