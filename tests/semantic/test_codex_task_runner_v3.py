from __future__ import annotations

import hashlib
import json
import os
import shlex
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.support.platform_filesystem import create_symlink_or_skip
from tests.semantic.support import codex_harness as codex_harness_module
from tests.semantic.support.codex_business_oracle_plan_v3 import (
    write_business_oracle_plan,
)
from tests.semantic.support import codex_task_runner_v3 as task_runner
from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    build_optional_query_schema_protocol,
    build_optional_query_repair_protocol,
    build_transaction_protocol,
    query_object_step,
)
from tests.semantic.support.codex_gateway_broker import (
    ExpectedGatewayStep,
    GatewayBrokerReconciliation,
)
from tests.semantic.support.codex_gateway_contracts import (
    TASK_LOCAL_RUNNER_POSIX,
    TASK_LOCAL_RUNNER_WINDOWS,
)
from tests.semantic.support.codex_filesystem_security import write_utf8_text_bytes
from tests.semantic.support.codex_harness import (
    CodexCommandRecord,
    CodexInfrastructureError,
    CodexInfrastructureFailure,
)
from tests.semantic.support.codex_task_runner_v3 import _grade_common_turn
from tests.semantic.support.codex_prompt_provenance_v3 import (
    PromptProvenanceEvidence,
    write_prompt_provenance,
)


def _result(
    *,
    turn: int,
    gateway_count: int,
    skill_reads: tuple[str, ...] | None = None,
):
    reads = (
        skill_reads
        if skill_reads is not None
        else (
            ("SKILL.md", "references/waapi-operate.md")
            if turn == 1
            else ()
        )
    )
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


@pytest.mark.parametrize(
    "selected_names",
    (("query",), ("query-schema", "query")),
)
def test_optional_query_schema_terminal_accepts_only_complete_selected_protocol(
    selected_names: tuple[str, ...],
) -> None:
    protocol = build_optional_query_schema_protocol(
        query_object_step(
            "query",
            ("query-object", "--kind", "all-sounds", "--max-results", "12"),
        )
    )
    evidence = SimpleNamespace(
        expected_step_names=selected_names,
        consumed_step_names=selected_names,
        records=tuple(
            SimpleNamespace(step_name=name, succeeded=True)
            for name in selected_names
        ),
        rejected_records=(),
        complete=True,
        passed=True,
        terminal_state="COMPLETE",
    )

    assert task_runner._broker_terminal_protocol_passed(protocol, evidence)

    evidence.complete = False
    assert not task_runner._broker_terminal_protocol_passed(protocol, evidence)


@pytest.mark.parametrize(
    "selected_names",
    (
        ("query",),
        ("query-schema", "query"),
        ("query-schema.advanced", "query"),
        ("query-schema", "query-schema.advanced", "query"),
    ),
)
def test_optional_query_disclosures_accept_only_the_selected_complete_lane(
    selected_names: tuple[str, ...],
) -> None:
    protocol = build_optional_query_schema_protocol(
        query_object_step(
            "query",
            ("query-object", "--kind", "all-sounds", "--max-results", "12"),
        ),
        allow_advanced=True,
    )
    evidence = SimpleNamespace(
        expected_step_names=selected_names,
        consumed_step_names=selected_names,
        records=tuple(
            SimpleNamespace(step_name=name, succeeded=True)
            for name in selected_names
        ),
        rejected_records=(),
        complete=True,
        passed=True,
        terminal_state="COMPLETE",
    )

    assert protocol.optional_query_schema_step_names == (
        "query-schema",
        "query-schema.advanced",
    )
    assert protocol.accepted_terminal_prefixes == (1, 2, 3)
    assert task_runner._broker_terminal_protocol_passed(protocol, evidence)


@pytest.mark.parametrize("include_schema", (False, True))
def test_optional_query_repair_protocol_accepts_one_sealed_repair_chain(
    include_schema: bool,
) -> None:
    protocol = build_optional_query_repair_protocol(
        query_object_step(
            "query",
            ("query-object", "--kind", "all-sounds", "--max-results", "12"),
        )
    )
    names = tuple(step.name for step in protocol.steps)
    selected_names = names if include_schema else names[1:]
    evidence = SimpleNamespace(
        expected_step_names=selected_names,
        consumed_step_names=selected_names,
        records=tuple(
            SimpleNamespace(step_name=name, succeeded=True)
            for name in selected_names
        ),
        rejected_records=(),
        complete=True,
        passed=True,
        terminal_state="COMPLETE",
    )

    assert protocol.optional_initial_query_schema is True
    assert protocol.accepted_terminal_prefixes == (3, 4)
    assert task_runner._broker_terminal_protocol_passed(protocol, evidence)


def test_declared_short_terminal_prefix_is_complete_not_running() -> None:
    steps = tuple(
        ExpectedGatewayStep(name, "operations")
        for name in ("one", "two", "optional-three")
    )
    protocol = V3GatewayProtocol(
        steps=steps,
        turn_prefix_counts=(3,),
        allowed_turn_prefix_counts=((2, 3),),
        terminal_prefix_counts=(2, 3),
    )
    selected = ("one", "two")
    evidence = SimpleNamespace(
        expected_step_names=selected,
        consumed_step_names=selected,
        records=tuple(
            SimpleNamespace(step_name=name, succeeded=True) for name in selected
        ),
        rejected_records=(),
        complete=True,
        passed=True,
        terminal_state="COMPLETE",
        commutative_read_only_step_groups=(),
        commutative_composer_setup_step_groups=(),
    )

    assert task_runner._broker_terminal_protocol_passed(protocol, evidence)


def test_common_grade_ignores_one_identical_windows_preprocess_failure() -> None:
    result = _result(turn=1, gateway_count=2)
    successful = result.command_facts.command_records[0]
    successful.status = "completed"
    successful.exit_code = 0
    successful.parse_error = ""
    successful.has_shell_operators = False
    successful.parser_kind = "windows-pwsh-command"
    successful.argv = ("Get-Content", "-Raw", "-Encoding", "UTF8", "SKILL.md")
    successful.aggregated_output = "skill"
    failed = SimpleNamespace(
        command=successful.command,
        status="failed",
        exit_code=-1,
        parse_error="",
        has_shell_operators=False,
        parser_kind="windows-pwsh-command",
        argv=successful.argv,
        aggregated_output=(
            "execution error: Io(windows sandbox: "
            "CreateProcessAsUserW failed: 267)"
        ),
    )
    result.command_facts.command_records = (
        failed,
        *result.command_facts.command_records,
    )

    errors, gates = _grade_common_turn(
        result,
        turn_index=1,
        required_reference="references/waapi-operate.md",
        expected_gateway_count=2,
    )

    assert errors == ()
    assert all(gates.values())


def test_task_reconciliation_rejects_equivalent_requoted_continuation() -> None:
    full_argv = (
        "python",
        "/tmp/Skill Path/scripts/run.py",
        "gateway.py",
        "confirm",
        "tx-1",
    )
    selected = shlex.join(full_argv)
    next_command = {
        "contract": "waapi-skill.gateway-next-command/v2",
        "command": "confirm",
        "gateway_argv": list(full_argv[3:]),
        "full_argv": list(full_argv),
        "copy_exactly": True,
        "shell_tool_timeout_ms": 30_000,
        "shell_family": "posix-sh",
        "copy_instruction": {
            "contract": "waapi-skill.gateway-command-copy-instruction/v2",
            "source_field": "shell_command",
            "action": "execute_verbatim_as_one_shell_tool_call",
            "forbidden_transformations": [
                "reconstruct",
                "shorten",
                "normalize",
                "substitute_path_segments",
                "select_another_field",
            ],
        },
        "shell_command": selected,
    }
    prior_payload = {"next_command": next_command}
    prior = CodexCommandRecord(
        command="/bin/bash -lc 'python initial.py'",
        exit_code=0,
        status="completed",
        aggregated_output=json.dumps(prior_payload),
        argv=("python", "initial.py"),
        has_shell_operators=False,
        parser_kind="posix-shell",
    )
    equivalent = (
        "python '/tmp/Skill Path/scripts/run.py' 'gateway.py' 'confirm' 'tx-1'"
    )
    assert tuple(shlex.split(equivalent)) == full_argv
    assert equivalent != selected
    current = CodexCommandRecord(
        command=shlex.join(("/bin/bash", "-lc", equivalent)),
        exit_code=0,
        status="completed",
        aggregated_output="{}",
        argv=full_argv,
        has_shell_operators=False,
        parser_kind="posix-shell",
    )
    evidence = SimpleNamespace(
        accepted_records=(
            SimpleNamespace(payload=prior_payload),
            SimpleNamespace(payload={}),
        )
    )
    raw = GatewayBrokerReconciliation(True, 2, 2, ())

    reconciliation = task_runner._bind_gateway_prefix_reconciliation(
        raw,
        command_records=(prior, current),
        broker_evidence=evidence,
        platform_name="posix",
    )

    assert reconciliation.passed is False
    assert reconciliation.observed_command_count == 2
    assert reconciliation.accepted_record_count == 2
    assert reconciliation.errors == (
        "command 2: Gateway continuation was not copied from its selected source field",
    )


def test_reference_schedule_preserves_default_and_allows_alarm_lane_transition() -> None:
    assert task_runner._normalize_turn_reference_schedule(
        prompt_count=3,
        required_reference="references/waapi-operate.md",
        turn_reference_schedule=None,
    ) == (
        ("SKILL.md", "references/waapi-operate.md"),
        (),
        (),
    )
    alarm_schedule = task_runner._normalize_turn_reference_schedule(
        prompt_count=3,
        required_reference="references/waapi-query.md",
        turn_reference_schedule=(
            ("references/waapi-query.md",),
            ("references/waapi-operate.md",),
            (),
        ),
    )

    assert alarm_schedule == (
        ("SKILL.md", "references/waapi-query.md"),
        ("references/waapi-operate.md",),
        (),
    )
    for turn_index, expected_reads in enumerate(alarm_schedule, start=1):
        errors, gates = _grade_common_turn(
            _result(
                turn=turn_index,
                gateway_count=1,
                skill_reads=expected_reads,
            ),
            turn_index=turn_index,
            required_reference="references/waapi-query.md",
            expected_skill_reads=expected_reads,
            expected_gateway_count=1,
        )
        assert errors == ()
        assert all(gates.values())


def test_reference_schedule_allows_reviewed_skill_only_first_turn() -> None:
    schedule = task_runner._normalize_turn_reference_schedule(
        prompt_count=1,
        required_reference=None,
        turn_reference_schedule=None,
    )

    assert schedule == (("SKILL.md",),)
    errors, gates = _grade_common_turn(
        _result(turn=1, gateway_count=3, skill_reads=schedule[0]),
        turn_index=1,
        required_reference=None,
        expected_skill_reads=schedule[0],
        expected_gateway_count=3,
    )
    assert errors == ()
    assert all(gates.values())
    with pytest.raises(
        task_runner.V3TaskRunnerError,
        match="SKILL-only task must not schedule lane references",
    ):
        task_runner._normalize_turn_reference_schedule(
            prompt_count=1,
            required_reference=None,
            turn_reference_schedule=(("references/waapi-query.md",),),
        )


@pytest.mark.parametrize(
    "schedule",
    (
        object(),
        (("references/waapi-query.md",),),
        ("references/waapi-query.md", (), ()),
        ((None,), (), ()),
        (
            (
                "references/waapi-query.md",
                "references/waapi-operate.md",
            ),
            (),
            (),
        ),
        (
            ("references/waapi-query.md",),
            ("references/waapi-query.md",),
            (),
        ),
        (
            ("references/waapi-query.md",),
            ("references/not-packaged.md",),
            (),
        ),
        (
            ("references/waapi-operate.md",),
            (),
            (),
        ),
    ),
)
def test_reference_schedule_rejects_unclosed_shapes(schedule: Any) -> None:
    with pytest.raises(task_runner.V3TaskRunnerError):
        task_runner._normalize_turn_reference_schedule(
            prompt_count=3,
            required_reference="references/waapi-query.md",
            turn_reference_schedule=schedule,
        )


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


def _sealed_asset_grade_fixture(
    tmp_path: Path,
) -> tuple[PromptProvenanceEvidence, CodexCommandRecord]:
    root = tmp_path / "scenario"
    owned = root / "owned"
    asset = owned / "assets" / "import.tsv"
    content = "Object Path\t@Volume\n<Sound>A\t-3\n"
    encoded = content.encode("utf-8")
    provenance = PromptProvenanceEvidence(
        path=root / "evidence" / "prompt-provenance.json",
        sha256="a" * 64,
        payload={
            "scenario_root": str(root),
            "owned_root": str(owned),
            "request": {
                "rendered_prompt": f"导入表是 {asset}",
                "inputs": [
                    {
                        "name": "import_file",
                        "kind": "absolute_file_path",
                        "value": str(asset),
                        "leaf_bindings": [
                            {
                                "pointer": "",
                                "origin_kind": "owned_path",
                                "path_kind": "file",
                                "owned_relative_path": "assets/import.tsv",
                                "size": len(encoded),
                                "sha256": hashlib.sha256(encoded).hexdigest(),
                                "mtime_ns": 1,
                            }
                        ],
                    }
                ],
            },
        },
        prompts=(f"导入表是 {asset}",),
        visible_values={"import_file": str(asset)},
        protocol=None,  # type: ignore[arg-type]
    )
    record = CodexCommandRecord(
        command=f"/bin/bash -lc 'cat {asset}'",
        exit_code=0,
        status="completed",
        aggregated_output=content,
        argv=("cat", str(asset)),
        has_shell_operators=False,
    )
    return provenance, record


def test_common_grade_allows_one_exact_sealed_prompt_asset_cat(
    tmp_path: Path,
) -> None:
    provenance, asset_read = _sealed_asset_grade_fixture(tmp_path)
    result = _result(turn=1, gateway_count=2)
    records = result.command_facts.command_records
    result.command_facts.command_records = (
        *records[:2],
        asset_read,
        *records[2:],
    )
    result.command_facts.unexpected_commands = (asset_read.command,)
    result.command_facts.non_gateway_unexpected_commands = (
        asset_read.command,
    )

    errors, gates = _grade_common_turn(
        result,
        turn_index=1,
        required_reference="references/waapi-operate.md",
        expected_gateway_count=2,
        prompt_provenance=provenance,
    )

    assert errors == ()
    assert gates["no_other_commands"] is True
    assert gates["no_unexpected_commands"] is True


def test_common_grade_keeps_tab_import_asset_cat_unexpected(
    tmp_path: Path,
) -> None:
    provenance, asset_read = _sealed_asset_grade_fixture(tmp_path)
    provenance = replace(
        provenance,
        protocol=build_transaction_protocol(
            (
                {
                    "contract": "waapi-skill.operation-request/v1",
                    "version": "2025.1",
                    "operation": "audio.importTabDelimited",
                    "arguments": {
                        "import_file": str(
                            provenance.payload["request"]["inputs"][0]["value"]
                        ),
                        "import_location": {
                            "kind": "path",
                            "value": r"\Containers\Default Work Unit",
                        },
                        "import_language": "SFX",
                        "import_operation": "createNew",
                    },
                },
            )
        ),
    )
    result = _result(turn=1, gateway_count=2)
    records = result.command_facts.command_records
    result.command_facts.command_records = (
        *records[:2],
        asset_read,
        *records[2:],
    )
    result.command_facts.unexpected_commands = (asset_read.command,)
    result.command_facts.non_gateway_unexpected_commands = (
        asset_read.command,
    )

    errors, gates = _grade_common_turn(
        result,
        turn_index=1,
        required_reference="references/waapi-operate.md",
        expected_gateway_count=2,
        prompt_provenance=provenance,
    )

    assert "no_other_commands" in errors
    assert "no_unexpected_commands" in errors
    assert gates["no_other_commands"] is False
    assert gates["no_unexpected_commands"] is False


@pytest.mark.parametrize("turn_index", (1, 2))
def test_common_grade_rejects_duplicate_or_later_prompt_asset_cat(
    tmp_path: Path,
    turn_index: int,
) -> None:
    provenance, asset_read = _sealed_asset_grade_fixture(tmp_path)
    result = _result(turn=turn_index, gateway_count=2)
    records = result.command_facts.command_records
    inserted = (
        (asset_read, asset_read)
        if turn_index == 1
        else (asset_read,)
    )
    result.command_facts.command_records = (
        *records[: len(result.command_facts.allowed_read_commands)],
        *inserted,
        *records[len(result.command_facts.allowed_read_commands) :],
    )
    result.command_facts.unexpected_commands = tuple(
        item.command for item in inserted
    )
    result.command_facts.non_gateway_unexpected_commands = tuple(
        item.command for item in inserted
    )

    errors, gates = _grade_common_turn(
        result,
        turn_index=turn_index,
        required_reference="references/waapi-operate.md",
        expected_gateway_count=2,
        prompt_provenance=provenance,
    )

    assert "no_other_commands" in errors
    assert "no_unexpected_commands" in errors
    assert gates["no_other_commands"] is False
    assert gates["no_unexpected_commands"] is False


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
        self.commutative_read_only_step_groups = ()
        self.commutative_composer_setup_step_groups = ()
        self.records = tuple(
            SimpleNamespace(
                sequence=index,
                step_name=name,
                succeeded=True,
                model_argv=("python", f"raw-{name}.py", "--value", "原始 值"),
                normalized_model_argv=(
                    "python",
                    f"normalized-{name}.py",
                    "--value",
                    "原始 值",
                ),
                raw_argv_sha256=hashlib.sha256(
                    json.dumps(
                        ["python", f"raw-{name}.py", "--value", "原始 值"],
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                argv_sha256=hashlib.sha256(
                    json.dumps(
                        [
                            "python",
                            f"normalized-{name}.py",
                            "--value",
                            "原始 值",
                        ],
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                semantic_argv_sha256=hashlib.sha256(
                    json.dumps(
                        ["semantic", name],
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                stdout=f"{name}-stdout",
                stderr=f"{name}-stderr",
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

    @property
    def accepted_records(self) -> tuple[SimpleNamespace, ...]:
        return self.records

    def as_dict(self, *, include_output: bool = False) -> dict[str, object]:
        records: list[dict[str, object]] = [
            {
                "sequence": record.sequence,
                "step_name": record.step_name,
                "model_argv": list(record.model_argv),
                "normalized_model_argv": list(record.normalized_model_argv),
                "raw_argv_sha256": record.raw_argv_sha256,
                "argv_sha256": record.argv_sha256,
                "semantic_argv_sha256": record.semantic_argv_sha256,
            }
            for record in self.records
        ]
        if include_output:
            for payload, record in zip(records, self.records, strict=True):
                payload.update(
                    {"stdout": record.stdout, "stderr": record.stderr}
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
    reconciliation_errors: tuple[str, ...] = (),
    captured_developer_instructions: list[str] | None = None,
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
                passed=not reconciliation_errors,
                observed_command_count=(
                    expected_step_count if not reconciliation_errors else 0
                ),
                accepted_record_count=expected_step_count,
                errors=reconciliation_errors,
            )

    class FakeTask:
        def __init__(self, config: object, *_: object, **__: object) -> None:
            if captured_developer_instructions is not None:
                captured_developer_instructions.append(
                    str(getattr(config, "developer_instructions"))
                )
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
    developer_instructions: str = "",
) -> Path:
    skill_source = tmp_path / "skill"
    skill_source.mkdir()
    skill_probe = tmp_path / "skill-symlink-probe"
    create_symlink_or_skip(
        skill_probe,
        skill_source,
        target_is_directory=True,
    )
    skill_probe.unlink()
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
        write_utf8_text_bytes(
            business_oracle_plan.path,
            json.dumps(
                rewritten,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
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
        developer_instructions=developer_instructions,
    )
    return task_root


def test_v3_workspace_injection_uses_detached_copy_on_native_windows(tmp_path: Path) -> None:
    source = tmp_path / "waapi-skill"
    (source / "references").mkdir(parents=True)
    (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
    (source / "references" / "waapi-operate.md").write_text("operate\n", encoding="utf-8")
    (source / ".venv").mkdir()
    workspace = tmp_path / "workspace"

    install = task_runner._prepare_agent_workspace(
        workspace,
        source,
        platform_name="nt",
    )

    assert install.is_dir() and not install.is_symlink()
    assert (install / "references" / "waapi-operate.md").is_file()
    assert not (install / ".venv").exists()
    assert not os.path.samefile(source / "SKILL.md", install / "SKILL.md")


def test_v3_gateway_accounting_accepts_copy_then_candidate_runner(tmp_path: Path) -> None:
    copied = tmp_path / "workspace-copy"
    candidate = tmp_path / "candidate"
    records = (
        SimpleNamespace(
            argv=("python", str(copied / "scripts" / "run.py"), "gateway.py", "preview")
        ),
        SimpleNamespace(
            argv=(
                "python",
                str(candidate / "scripts" / "run.py"),
                "gateway.py",
                "execute",
                "tx-1",
            )
        ),
    )
    result = SimpleNamespace(command_facts=SimpleNamespace(command_records=records))

    assert task_runner._gateway_candidate_argvs(
        result,
        skill_source=copied,
        alternate_skill_sources=(candidate,),
        expected_wwise_version="2022.1",
    ) == tuple(record.argv for record in records)


def test_v3_gateway_accounting_folds_one_identical_windows_267_retry(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "waapi-skill"
    argv = (
        "python",
        str(skill / "scripts" / "run.py"),
        "gateway.py",
        "request-schema",
        "ak.wwise.core.gameParameter.setRange",
    )
    command = "pwsh -Command project-setting-request-schema"
    failed = SimpleNamespace(
        argv=argv,
        command=command,
        status="failed",
        exit_code=-1,
        parse_error="",
        has_shell_operators=False,
        parser_kind="windows-pwsh-command",
        aggregated_output=(
            "execution error: Io(windows sandbox: "
            "CreateProcessAsUserW failed: 267)"
        ),
    )
    successful = SimpleNamespace(
        argv=argv,
        command=command,
        status="completed",
        exit_code=0,
        parse_error="",
        has_shell_operators=False,
        parser_kind="windows-pwsh-command",
        aggregated_output="{}",
    )
    result = SimpleNamespace(
        command_facts=SimpleNamespace(command_records=(failed, successful))
    )

    assert task_runner._gateway_candidate_argvs(
        result,
        skill_source=skill,
        expected_wwise_version="2025.1",
    ) == (argv,)
    assert task_runner._gateway_candidate_records(
        result,
        skill_source=skill,
        expected_wwise_version="2025.1",
    ) == (successful,)


def test_v3_gateway_accounting_canonicalizes_exact_task_local_runner(
    tmp_path: Path,
) -> None:
    installed = (
        tmp_path
        / "workspace"
        / ".agents"
        / "skills"
        / "waapi-skill"
    )
    candidate = tmp_path / "candidate" / "waapi-skill"
    relative_runner = (
        TASK_LOCAL_RUNNER_WINDOWS if os.name == "nt" else TASK_LOCAL_RUNNER_POSIX
    )
    record = SimpleNamespace(
        argv=(
            "python",
            relative_runner,
            "gateway.py",
            "status",
        )
    )
    result = SimpleNamespace(
        command_facts=SimpleNamespace(command_records=(record,))
    )

    assert task_runner._gateway_candidate_argvs(
        result,
        skill_source=installed,
        alternate_skill_sources=(candidate,),
        expected_wwise_version="2022.1",
    ) == (
        (
            "python",
            str(installed / "scripts" / "run.py"),
            "gateway.py",
            "status",
        ),
    )
    assert task_runner._gateway_candidate_records(
        result,
        skill_source=installed,
        alternate_skill_sources=(candidate,),
        expected_wwise_version="2022.1",
    ) == (record,)


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


def test_v3_task_seals_exact_task_local_skill_reads_and_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    _install_task_fakes(
        monkeypatch,
        failure_turn=1,
        captured_developer_instructions=captured,
    )
    candidate_runner = tmp_path / "skill" / "scripts" / "run.py"
    base = codex_harness_module.semantic_skill_bootstrap_developer_instructions(
        candidate_runner
    )

    with pytest.raises(CodexInfrastructureError):
        _run_infrastructure_task(
            tmp_path,
            prompts=("first natural prompt", "second natural prompt"),
            developer_instructions=base,
        )

    assert len(captured) == 1
    task_skill = (
        tmp_path
        / "scenario"
        / "evidence"
        / "codex-task"
        / "agent-workspace"
        / ".agents"
        / "skills"
        / "waapi-skill"
    )
    instructions = captured[0]
    if os.name == "nt":
        assert (
            "Get-Content -Raw -Encoding UTF8 "
            r"'.agents\skills\waapi-skill\SKILL.md'"
        ) in instructions
        assert (
            "Get-Content -Raw -Encoding UTF8 "
            r"'.agents\skills\waapi-skill\references\waapi-operate.md'"
        ) in instructions
        assert (
            "python '.agents\\skills\\waapi-skill\\scripts\\run.py' "
            "'gateway.py'"
        ) in instructions
    else:
        assert "cat '.agents/skills/waapi-skill/SKILL.md'" in instructions
        assert "cat '.agents/skills/waapi-skill/references/waapi-operate.md'" in (
            instructions
        )
        assert (
            "python .agents/skills/waapi-skill/scripts/run.py gateway.py"
            in instructions
        )
    assert str(candidate_runner) not in instructions
    assert str(task_skill) not in instructions


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


def test_task_gate_failure_archives_full_broker_and_turn_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_task_fakes(
        monkeypatch,
        failure_turn=2,
        reconciliation_errors=("normalized argv differs from broker record",),
    )

    with pytest.raises(
        task_runner.V3TaskRunnerError,
        match="failed task gates",
    ) as caught:
        _run_infrastructure_task(
            tmp_path,
            prompts=("first natural prompt", "second natural prompt"),
        )

    assert caught.value.thread_id == "thread-prior"
    task_root = tmp_path / "scenario" / "evidence" / "codex-task"
    manifest_path = task_root / "task-gate-failure.json"
    broker_path = task_root / "task-gate-broker-evidence.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    broker = json.loads(broker_path.read_text(encoding="utf-8"))

    assert manifest["contract"] == task_runner.TASK_GATE_FAILURE_CONTRACT
    assert manifest["scenario_id"] == "SCENARIO-INFRA-01"
    assert manifest["version"] == "2022.1"
    assert manifest["failed_turn_index"] == 1
    assert manifest["expected_turn_count"] == 2
    assert manifest["thread_id"] == "thread-prior"
    assert manifest["diagnostic_only"] is True
    assert manifest["failed_common_gates"] == []
    assert manifest["grade_errors"] == []
    assert manifest["reconciliation"] == {
        "passed": False,
        "observed_command_count": 0,
        "accepted_record_count": 1,
        "errors": ["normalized argv differs from broker record"],
    }

    record = broker["records"][0]
    assert record["model_argv"] == [
        "python",
        "raw-first.py",
        "--value",
        "原始 值",
    ]
    assert record["normalized_model_argv"] == [
        "python",
        "normalized-first.py",
        "--value",
        "原始 值",
    ]
    assert record["raw_argv_sha256"] == hashlib.sha256(
        json.dumps(
            record["model_argv"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert record["argv_sha256"] == hashlib.sha256(
        json.dumps(
            record["normalized_model_argv"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert record["semantic_argv_sha256"] == hashlib.sha256(
        json.dumps(
            ["semantic", "first"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert "stdout" not in record
    assert "stderr" not in record

    expected_artifacts = {
        task_runner.PROMPT_MATERIALIZATION_FILE,
        "turns/turn-01/prompt.txt",
        "turns/turn-01/events.jsonl",
        "turns/turn-01/stderr.txt",
        "turns/turn-01/final.txt",
        "turns/turn-01/codex-facts.json",
        "turns/turn-01/turn-grade.json",
        "task-gate-broker-evidence.json",
    }
    assert set(manifest["artifact_sha256"]) == expected_artifacts
    for relative_path, digest in manifest["artifact_sha256"].items():
        assert digest == hashlib.sha256(
            (task_root / relative_path).read_bytes()
        ).hexdigest()
    assert not (task_root / "task-result.json").exists()
    assert not (task_root / "agent-workspace").exists()


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
