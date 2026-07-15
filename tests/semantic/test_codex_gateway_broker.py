from __future__ import annotations

import json
import os
import shlex
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from .support import codex_gateway_broker as broker_module  # pyright: ignore[reportMissingImports]
from .support.codex_gateway_broker import (  # pyright: ignore[reportMissingImports]
    BASH_ENV_NAME,
    BROKER_TOKEN_ENV,
    CodexGatewayBroker,
    ExpectedGatewayStep,
    GATEWAY_REQUIRED_ENV,
    GatewayBrokerError,
    GatewayInvocationError,
    ResponseBinding,
    SemanticJsonArgument,
    reconcile_gateway_commands,
    resolve_gateway_invocation,
)


FAKE_RUNNER = r'''from __future__ import annotations
import json
import os
import sys
from pathlib import Path

state = Path(os.environ["WAAPI_SKILL_STATE_DIR"])
state.mkdir(parents=True, exist_ok=True)
calls = state / "fake-runner-calls.jsonl"
with calls.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")

arguments = sys.argv[1:]
assert arguments[0] == "gateway.py"
global_options_with_values = {
    "--host", "--port", "--version", "--wwise-version", "--timeout",
    "--evidence-dir", "--state-dir",
}
command_index = 1
while command_index < len(arguments):
    value = arguments[command_index]
    if any(value.startswith(option + "=") for option in global_options_with_values):
        command_index += 1
        continue
    if value in global_options_with_values:
        command_index += 2
        continue
    break
command = arguments[command_index]
command_arguments = arguments[command_index + 1:]
mode = os.environ.get("FAKE_GATEWAY_MODE", "")
if mode == "hang-ignore-term":
    import signal
    import time

    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    (state / "fake-runner-pid").write_text(str(os.getpid()), encoding="utf-8")
    while True:
        time.sleep(1)
payload = {
    "contract": "waapi-skill.gateway-result/v1",
    "ok": True,
    "status": "ok",
    "command": command,
    "runner_python": sys.executable,
    "state_dir": os.environ.get("WAAPI_SKILL_STATE_DIR"),
    "evidence_dir": os.environ.get("WWISE_EVIDENCE_DIR"),
    "config_path": os.environ.get("WAAPI_SKILL_CONFIG_PATH"),
    "broker_token_visible": "WAAPI_CODEX_GATEWAY_BROKER_TOKEN" in os.environ,
    "bash_env_visible": "BASH_ENV" in os.environ,
    "gateway_required_visible": "WAAPI_CODEX_GATEWAY_REQUIRED" in os.environ,
}
if command == "preview":
    (state / "preview-marker.json").write_text(
        json.dumps({"transaction_id": "tx-dynamic-123", "artifact_hash": "sha256-dynamic-456"}),
        encoding="utf-8",
    )
    payload.update({
        "status": "awaiting_confirmation",
        "transaction_id": "tx-dynamic-123",
        "artifact_hash": "sha256-dynamic-456",
        "request": json.loads(command_arguments[1]),
    })
elif command == "confirm":
    assert (state / "preview-marker.json").is_file()
    payload.update({
        "status": "confirmed",
        "transaction_id": command_arguments[0],
        "artifact_hash": command_arguments[2],
    })
elif command == "transaction-show":
    marker = json.loads((state / "preview-marker.json").read_text(encoding="utf-8"))
    payload.update(marker)
elif command == "execute":
    (state / "mutation-executed").write_text("yes", encoding="utf-8")
if mode == "bad-ok":
    payload["ok"] = False
elif mode == "bad-command":
    payload["command"] = "buses"
elif mode == "bad-contract":
    payload["contract"] = "forged/v1"
print("fake setup log before payload")
print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
if mode == "bad-exit":
    raise SystemExit(7)
'''


def make_fake_skill(tmp_path: Path) -> Path:
    skill = tmp_path / "waapi-skill"
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text(FAKE_RUNNER, encoding="utf-8")
    return skill


def run_model_command(
    broker: CodexGatewayBroker,
    arguments: list[str],
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = environment or broker.model_environment(os.environ)
    return subprocess.run(
        ["python", str(broker.runner_path), "gateway.py", *arguments],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "transport",
    ["tcp", pytest.param("unix", marks=pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="no AF_UNIX"))],
)
def test_broker_executes_exact_order_with_semantic_json_and_response_bindings(
    tmp_path: Path,
    transport: str,
) -> None:
    skill = make_fake_skill(tmp_path)
    request = {
        "operation": "ak.wwise.core.object.setNotes",
        "target": {"path": r"\Actor-Mixer Hierarchy\Default Work Unit\Sound"},
        "value": "broker test",
    }
    steps = (
        ExpectedGatewayStep("schema", "operation-schema", ("ak.wwise.core.object.setNotes",)),
        ExpectedGatewayStep(
            "preview",
            "preview",
            ("--request-json", SemanticJsonArgument(request)),
        ),
        ExpectedGatewayStep(
            "confirm",
            "confirm",
            (
                ResponseBinding("preview", "/transaction_id"),
                "--artifact-hash",
                ResponseBinding("preview", "/artifact_hash"),
            ),
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=steps,
        transport=transport,
        runner_environment={
            "PATH": os.environ.get("PATH", os.defpath),
            "BROKER_TEST": "1",
            "WAAPI_SKILL_CONFIG_PATH": str(tmp_path / "caller-controlled-config.json"),
        },
    ) as broker:
        observed = [
            ["python", str(broker.runner_path), "gateway.py", "operation-schema", "ak.wwise.core.object.setNotes"],
            [
                "python",
                str(broker.runner_path),
                "gateway.py",
                "preview",
                "--request-json",
                json.dumps(request, ensure_ascii=False, sort_keys=False, indent=1),
            ],
            [
                "python",
                str(broker.runner_path),
                "gateway.py",
                "confirm",
                "tx-dynamic-123",
                "--artifact-hash",
                "sha256-dynamic-456",
            ],
        ]
        results = [run_model_command(broker, command[3:]) for command in observed]

        assert [result.returncode for result in results] == [0, 0, 0]
        preview = json.loads(results[1].stdout[results[1].stdout.index("{") :])
        assert preview["request"] == request
        assert preview["broker_token_visible"] is False
        assert preview["bash_env_visible"] is False
        assert preview["state_dir"] == str(broker.state_directory)
        assert preview["evidence_dir"] == str(broker.evidence_directory)
        assert preview["config_path"] == str(broker.config_path)
        assert broker.config_path.is_file()

        evidence = broker.evidence()
        assert evidence.passed is True
        assert evidence.complete is True
        assert evidence.consumed_step_names == ("schema", "preview", "confirm")
        assert len(evidence.records) == 3
        assert all(record.accepted and record.succeeded for record in evidence.records)
        assert all(record.argv_sha256 and record.payload_sha256 for record in evidence.records)
        assert all(record.runner_command_sha256 for record in evidence.records)
        assert all(record.duration_seconds >= 0 for record in evidence.records)
        assert evidence.records[1].payload == preview
        assert broker.reconcile(observed).passed is True

        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(calls) == 3


@pytest.mark.parametrize(
    "selector",
    ((), ("--version", "2022.1"), ("--wwise-version=2022.1",)),
)
def test_broker_accepts_canonical_step_global_timeout_before_wait_topic(
    tmp_path: Path,
    selector: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    topic = "ak.wwise.core.object.created"
    step = ExpectedGatewayStep(
        "wait-topic",
        "wait-topic",
        (
            topic,
            "--options-json",
            SemanticJsonArgument({"return": ["id", "name", "type", "path"]}),
            "--match-json",
            SemanticJsonArgument({"object": {"type": "ActorMixer"}}),
        ),
        gateway_global_arguments=("--timeout", "10"),
    )
    arguments = [
        *selector,
        "--timeout",
        "10",
        "wait-topic",
        topic,
        "--options-json",
        '{"return":["id","name","type","path"]}',
        "--match-json",
        '{"object":{"type":"ActorMixer"}}',
    ]

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        expected_wwise_version="2022.1",
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, arguments)
        assert result.returncode == 0, result.stderr

        evidence = broker.evidence()
        assert evidence.passed is True
        assert evidence.records[0].gateway_arguments == tuple(arguments)
        observed = [
            "python",
            str(broker.runner_path),
            "gateway.py",
            *arguments,
        ]
        resolved = resolve_gateway_invocation(observed, skill_source=skill)
        assert resolved.subcommand == "wait-topic"
        assert resolved.normalized_model_argv == tuple(observed)
        assert broker.reconcile((observed,)).passed is True

        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        assert json.loads(calls[0]) == ["gateway.py", *arguments[len(selector) :]]


@pytest.mark.parametrize(
    "arguments",
    (
        ("wait-topic", "ak.wwise.core.object.created"),
        ("--timeout", "9", "wait-topic", "ak.wwise.core.object.created"),
        ("--timeout=10", "wait-topic", "ak.wwise.core.object.created"),
        ("wait-topic", "--timeout", "10", "ak.wwise.core.object.created"),
    ),
)
def test_broker_rejects_noncanonical_wait_topic_timeout_prefix(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    step = ExpectedGatewayStep(
        "wait-topic",
        "wait-topic",
        ("ak.wwise.core.object.created",),
        gateway_global_arguments=("--timeout", "10"),
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, list(arguments))

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def test_empty_call_json_objects_accept_omission_and_explicit_pair_as_one_semantics(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    uri = "ak.wwise.waapi.getFunctions"
    variants = (
        (uri,),
        (uri, "--args-json", "{}", "--options-json", "{}"),
        (uri, "--args-json", "{ }", "--options-json", "{\n}"),
    )
    semantic_hashes: list[str] = []

    for index, arguments in enumerate(variants):
        step = ExpectedGatewayStep(
            "call",
            "call",
            (
                uri,
                "--args-json",
                SemanticJsonArgument({}),
                "--options-json",
                SemanticJsonArgument({}),
            ),
            allow_omitted_empty_json_objects=True,
        )
        with CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(step,),
            working_root=tmp_path / f"broker-{index}",
            transport="tcp",
        ) as broker:
            result = run_model_command(broker, ["call", *arguments])
            assert result.returncode == 0, result.stderr

            evidence = broker.evidence()
            assert evidence.passed is True
            semantic_hashes.append(evidence.records[0].semantic_argv_sha256)
            observed = [
                "python",
                str(broker.runner_path),
                "gateway.py",
                "call",
                *arguments,
            ]
            assert broker.reconcile((observed,)).passed is True

    assert len(set(semantic_hashes)) == 1


@pytest.mark.parametrize(
    "arguments",
    (
        (
            "ak.wwise.waapi.getFunctions",
            "--args-json",
            '{"unexpected":true}',
            "--options-json",
            "{}",
        ),
        (
            "ak.wwise.waapi.getFunctions",
            "--args-json",
            "{}",
            "--options-json",
            '{"return":["uri"]}',
        ),
        ("ak.wwise.waapi.getFunctions", "--args-json", "{}"),
        ("ak.wwise.waapi.getFunctions", "--options-json", "{}"),
        (
            "ak.wwise.waapi.getFunctions",
            "--options-json",
            "{}",
            "--args-json",
            "{}",
        ),
        (
            "ak.wwise.waapi.getFunctions",
            "--args-json={}",
            "--options-json={}",
        ),
        (
            "ak.wwise.waapi.getFunctions",
            "--args-json",
            "[]",
            "--options-json",
            "{}",
        ),
    ),
)
def test_empty_call_json_equivalence_rejects_partial_reordered_or_nonempty_forms(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    step = ExpectedGatewayStep(
        "call",
        "call",
        (
            "ak.wwise.waapi.getFunctions",
            "--args-json",
            SemanticJsonArgument({}),
            "--options-json",
            SemanticJsonArgument({}),
        ),
        allow_omitted_empty_json_objects=True,
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(step,),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["call", *arguments])

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def test_authenticated_rejection_is_terminal_and_never_executes_later_command(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    steps = (ExpectedGatewayStep("status", "status"),)

    with CodexGatewayBroker(skill_source=skill, expected_steps=steps, transport="tcp") as broker:
        wrong = run_model_command(broker, ["buses"])
        assert wrong.returncode == 126
        assert "expected step" in wrong.stderr
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()

        blocked = run_model_command(broker, ["status"])
        assert blocked.returncode == 126
        assert "terminal FAILED" in blocked.stderr
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()

        evidence = broker.evidence()
        assert evidence.terminal_state == "FAILED"
        assert evidence.complete is False
        assert evidence.passed is False
        assert [record.accepted for record in evidence.records] == [False, False]


@pytest.mark.parametrize(
    "selector",
    (
        ("--version", "2022.1"),
        ("--version=2022.1",),
        ("--wwise-version", "2022.1"),
        ("--wwise-version=2022.1",),
        (),
    ),
)
def test_matching_optional_model_version_selector_is_sanitized_before_runner(
    tmp_path: Path,
    selector: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        expected_wwise_version="2022.1",
        runner_environment={**os.environ, "WWISE_VERSION": "2022.1"},
        transport="tcp",
    ) as broker:
        arguments = [*selector, "status"]
        result = run_model_command(broker, arguments)

        assert result.returncode == 0, result.stderr
        evidence = broker.evidence()
        assert evidence.passed is True
        assert evidence.records[0].gateway_arguments == tuple(arguments)
        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text(encoding="utf-8").splitlines()
        assert json.loads(calls[0]) == ["gateway.py", "status"]
        observed = [["python", str(broker.runner_path), "gateway.py", *arguments]]
        assert broker.reconcile(observed).passed is True


@pytest.mark.parametrize(
    "selector",
    (
        ("--version", "2022.1"),
        ("--version=2022.1",),
        ("--wwise-version", "2022.1"),
        ("--wwise-version=2022.1",),
    ),
)
def test_runner_level_version_selector_is_canonicalized_and_sanitized(
    tmp_path: Path,
    selector: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        expected_wwise_version="2022.1",
        runner_environment={**os.environ, "WWISE_VERSION": "2022.1"},
        transport="tcp",
    ) as broker:
        raw = ["python", str(broker.runner_path), *selector, "gateway.py", "status"]
        result = subprocess.run(
            raw,
            env=broker.model_environment(os.environ),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        evidence = broker.evidence()
        assert evidence.passed is True
        record = evidence.records[0]
        assert record.model_argv[1:] == tuple(raw[1:])
        canonical = ("python", str(broker.runner_path), "gateway.py", *selector, "status")
        assert record.normalized_model_argv == canonical
        assert record.gateway_arguments == (*selector, "status")
        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text(encoding="utf-8").splitlines()
        assert json.loads(calls[0]) == ["gateway.py", "status"]
        assert broker.reconcile((raw,)).passed is True


@pytest.mark.parametrize(
    "runner_tail",
    (
        ("--version", "2023.1", "gateway.py", "status"),
        ("--version=", "gateway.py", "status"),
        ("--wwise-version", "2022.1", "other.py", "status"),
        ("--version", "2022.1", "--version", "2022.1", "gateway.py", "status"),
        ("--state-dir", "/tmp/forbidden", "gateway.py", "status"),
    ),
)
def test_invalid_runner_level_selector_forms_fail_terminal_without_execution(
    tmp_path: Path,
    runner_tail: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        expected_wwise_version="2022.1",
        transport="tcp",
    ) as broker:
        result = subprocess.run(
            ["python", str(broker.runner_path), *runner_tail],
            env=broker.model_environment(os.environ),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert broker.evidence().passed is False
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


@pytest.mark.parametrize(
    "arguments",
    (
        ("--version", "2023.1", "status"),
        ("--wwise-version=2023.1", "status"),
        ("--version=", "status"),
        ("--wwise-version", "", "status"),
        ("--version", "2022.1", "--version", "2022.1", "status"),
        ("status", "--version", "2022.1"),
    ),
)
def test_invalid_or_duplicate_model_version_selector_fails_terminal(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        expected_wwise_version="2022.1",
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, list(arguments))

        assert result.returncode == 126
        assert broker.evidence().terminal_state == "FAILED"
        assert broker.evidence().passed is False
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()


def test_trusted_step_observer_runs_in_order_after_validated_steps(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    observed: list[tuple[str, str, Path, Path]] = []

    def observer(step, payload, state_directory, evidence_directory) -> None:
        observed.append(
            (step.name, payload["command"], state_directory, evidence_directory)
        )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep("first", "status"),
            ExpectedGatewayStep("second", "buses"),
        ),
        trusted_step_observer=observer,
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, ["status"]).returncode == 0
        assert run_model_command(broker, ["buses"]).returncode == 0

        assert observed == [
            ("first", "status", broker.state_directory, broker.evidence_directory),
            ("second", "buses", broker.state_directory, broker.evidence_directory),
        ]
        assert broker.evidence().passed is True


def test_trusted_pre_observer_runs_after_argv_validation_before_gateway_process(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    events: list[str] = []

    def before(step, state_directory, evidence_directory) -> None:
        assert step.name == "status"
        assert state_directory.is_dir()
        assert evidence_directory.is_dir()
        assert not (state_directory / "fake-runner-calls.jsonl").exists()
        events.append("before")

    def after(step, payload, state_directory, evidence_directory) -> None:
        del step, payload, evidence_directory
        assert (state_directory / "fake-runner-calls.jsonl").is_file()
        events.append("after")

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        trusted_step_pre_observer=before,
        trusted_step_observer=after,
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, ["status"]).returncode == 0
        assert events == ["before", "after"]
        assert broker.evidence().passed is True


def test_trusted_step_observer_failure_is_terminal_and_prevents_progression(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    observed: list[str] = []

    def reject_seal(step, payload, state_directory, evidence_directory) -> None:
        observed.append(step.name)
        assert payload["command"] == "status"
        assert state_directory.is_dir()
        assert evidence_directory.is_dir()
        raise RuntimeError("transaction seal mismatch")

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep("status", "status"),
            ExpectedGatewayStep("execute", "execute", ("tx-dynamic-123",)),
        ),
        trusted_step_observer=reject_seal,
        transport="tcp",
    ) as broker:
        failed = run_model_command(broker, ["status"])
        assert failed.returncode == 125
        assert "trusted step observer failed" in failed.stderr
        assert "transaction seal mismatch" in failed.stderr

        evidence = broker.evidence()
        record = evidence.records[0]
        assert observed == ["status"]
        assert "trusted step observer failed: RuntimeError" in record.payload_error
        assert "transaction seal mismatch" in record.payload_error
        assert record.runner_exit_code == 0
        assert record.exit_code == 125
        assert record.succeeded is False
        assert evidence.consumed_step_names == ()
        assert evidence.terminal_state == "FAILED"

        blocked = run_model_command(broker, ["execute", "tx-dynamic-123"])
        assert blocked.returncode == 126
        assert "terminal FAILED" in blocked.stderr
        assert observed == ["status"]
        assert len((broker.state_directory / "fake-runner-calls.jsonl").read_text().splitlines()) == 1
        assert not (broker.state_directory / "mutation-executed").exists()


def test_extra_command_after_completion_invalidates_terminal_evidence(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, ["status"]).returncode == 0
        assert broker.evidence().passed is True

        extra = run_model_command(broker, ["status"])
        assert extra.returncode == 126
        assert "terminal COMPLETE" in extra.stderr
        assert len((broker.state_directory / "fake-runner-calls.jsonl").read_text().splitlines()) == 1
        assert broker.evidence().terminal_state == "FAILED"
        assert broker.evidence().passed is False


def test_broker_rejects_wrong_preview_json_and_bad_dynamic_binding(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    expected_request = {"operation": "ak.wwise.core.object.setNotes", "value": "expected"}
    steps = (
        ExpectedGatewayStep(
            "preview",
            "preview",
            ("--request-json", SemanticJsonArgument(expected_request)),
        ),
        ExpectedGatewayStep(
            "confirm",
            "confirm",
            (
                ResponseBinding("preview", "/transaction_id"),
                "--artifact-hash",
                ResponseBinding("preview", "/artifact_hash"),
            ),
        ),
    )
    with CodexGatewayBroker(skill_source=skill, expected_steps=steps, transport="tcp") as broker:
        wrong_json = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps({**expected_request, "value": "wrong"})],
        )
        assert wrong_json.returncode == 126
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()

        blocked = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(expected_request, separators=(",", ":"))],
        )
        assert blocked.returncode == 126
        assert "terminal FAILED" in blocked.stderr
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()

    mutation_steps = (*steps, ExpectedGatewayStep("execute", "execute", ("tx-dynamic-123",)))
    with CodexGatewayBroker(skill_source=skill, expected_steps=mutation_steps, transport="tcp") as broker:
        preview = run_model_command(
            broker,
            ["preview", "--request-json", json.dumps(expected_request, separators=(",", ":"))],
        )
        assert preview.returncode == 0
        wrong_binding = run_model_command(
            broker,
            ["confirm", "tx-invented", "--artifact-hash", "sha256-dynamic-456"],
        )
        assert wrong_binding.returncode == 126
        assert "does not match" in wrong_binding.stderr
        assert len((broker.state_directory / "fake-runner-calls.jsonl").read_text().splitlines()) == 1

        blocked_mutation = run_model_command(
            broker,
            ["execute", "tx-dynamic-123"],
        )
        assert blocked_mutation.returncode == 126
        assert "terminal FAILED" in blocked_mutation.stderr
        assert len((broker.state_directory / "fake-runner-calls.jsonl").read_text().splitlines()) == 1
        assert not (broker.state_directory / "mutation-executed").exists()


def test_broker_token_authentication_fails_before_runner(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        bad_environment = broker.model_environment(os.environ)
        bad_environment[BROKER_TOKEN_ENV] = "not-the-token"
        rejected = run_model_command(broker, ["status"], environment=bad_environment)

        assert rejected.returncode == 126
        assert "authentication failed" in rejected.stderr
        assert not (broker.state_directory / "fake-runner-calls.jsonl").exists()
        assert broker.evidence().records[0].rejection == "broker authentication failed"


def test_broker_installs_both_shims_and_exposes_small_harness_overlay(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        assert (broker.shim_directory / "python").is_file()
        assert (broker.shim_directory / "python3").is_file()
        overlay = broker.model_environment_overrides("/trusted/bin")
        assert "HOME" not in overlay
        assert "CODEX_HOME" not in overlay
        assert overlay["PATH"] == f"{broker.shim_directory}{os.pathsep}/trusted/bin"
        assert overlay[BASH_ENV_NAME] == str(broker.bash_env_path)
        assert overlay[GATEWAY_REQUIRED_ENV] == "1"

        result = subprocess.run(
            [
                "/bin/bash",
                "-lc",
                " ".join(
                    (
                        "python3",
                        shlex.quote(str(broker.runner_path)),
                        "gateway.py",
                        "status",
                    )
                ),
            ],
            env={**os.environ, **overlay},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        record = broker.evidence().records[0]
        assert record.normalized_model_argv[0] == "python3"
        assert record.payload is not None
        assert record.payload["gateway_required_visible"] is False


def test_broker_fails_closed_and_records_invalid_runner_evidence(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    (skill / "scripts" / "run.py").write_text(
        'print("not a gateway JSON payload")\n',
        encoding="utf-8",
    )
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        result = run_model_command(broker, ["status"])
        assert result.returncode == 125
        record = broker.evidence().records[0]
        assert record.accepted is True
        assert record.runner_exit_code == 0
        assert record.exit_code == 125
        assert record.payload is None
        assert "JSON" in record.payload_error
        assert record.succeeded is False
        assert broker.evidence().terminal_state == "FAILED"
        assert run_model_command(broker, ["status"]).returncode == 126
        assert len(broker.evidence().accepted_records) == 1


@pytest.mark.parametrize(
    ("mode", "error_text"),
    [
        ("bad-ok", "ok must be exactly true"),
        ("bad-command", "payload command must be exactly"),
        ("bad-contract", "payload contract must be"),
        ("bad-exit", "runner exit 7"),
    ],
)
def test_bad_runner_payload_or_exit_is_terminal(
    tmp_path: Path,
    mode: str,
    error_text: str,
) -> None:
    skill = make_fake_skill(tmp_path)
    observer_calls: list[str] = []
    runner_environment = {**os.environ, "FAKE_GATEWAY_MODE": mode}
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep("status", "status"),
            ExpectedGatewayStep("execute", "execute", ("tx-dynamic-123",)),
        ),
        runner_environment=runner_environment,
        trusted_step_observer=lambda step, *_: observer_calls.append(step.name),
        transport="tcp",
    ) as broker:
        failed = run_model_command(broker, ["status"])
        assert failed.returncode == 125
        record = broker.evidence().records[0]
        assert error_text in record.payload_error
        assert record.succeeded is False
        assert observer_calls == []
        assert broker.evidence().consumed_step_names == ()
        assert broker.evidence().terminal_state == "FAILED"

        blocked = run_model_command(broker, ["execute", "tx-dynamic-123"])
        assert blocked.returncode == 126
        calls = (broker.state_directory / "fake-runner-calls.jsonl").read_text().splitlines()
        assert len(calls) == 1
        assert not (broker.state_directory / "mutation-executed").exists()


def test_subprocess_oserror_is_recorded_and_terminal(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        # The shim already has a trusted shebang.  Changing only the broker's
        # runner interpreter forces subprocess.run to raise FileNotFoundError.
        broker.trusted_python = tmp_path / "missing-python"
        failed = run_model_command(broker, ["status"])
        assert failed.returncode == 125
        record = broker.evidence().records[0]
        assert record.accepted is True
        assert record.runner_exit_code is None
        assert "FileNotFoundError" in record.payload_error
        assert broker.evidence().terminal_state == "FAILED"
        assert broker.evidence().complete is False
        reconciliation = broker.reconcile(
            [["python", str(broker.runner_path), "gateway.py", "status"]]
        )
        assert reconciliation.passed is False
        assert any("did not succeed" in error for error in reconciliation.errors)


@pytest.mark.skipif(os.name != "posix", reason="process-group timeout contract is POSIX-specific")
def test_runner_timeout_kills_reaps_and_records_terminal_failure(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": "hang-ignore-term"},
        transport="tcp",
        runner_timeout_seconds=0.05,
    ) as broker:
        started = time.monotonic()
        failed = run_model_command(broker, ["status"])
        elapsed = time.monotonic() - started

        assert elapsed < 2.0
        assert failed.returncode == 125
        record = broker.evidence().records[0]
        assert record.accepted is True
        assert record.runner_exit_code == 124
        assert record.succeeded is False
        assert "packaged gateway runner timed out" in record.payload_error
        assert broker.evidence().terminal_state == "FAILED"
        assert broker._active_process is None
        assert broker._active_process_done.is_set()

        runner_pid = int(
            (broker.state_directory / "fake-runner-pid").read_text(encoding="utf-8")
        )
        with pytest.raises(ProcessLookupError):
            os.kill(runner_pid, 0)


@pytest.mark.skipif(os.name != "posix", reason="process-group lifecycle contract is POSIX-specific")
def test_close_terminates_kills_and_reaps_active_runner_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = make_fake_skill(tmp_path)
    root = tmp_path / "broker-root"
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        runner_environment={**os.environ, "FAKE_GATEWAY_MODE": "hang-ignore-term"},
        working_root=root,
        transport="tcp",
        runner_timeout_seconds=30,
    ).start()
    results: list[subprocess.CompletedProcess[str]] = []
    command_thread = threading.Thread(
        target=lambda: results.append(run_model_command(broker, ["status"])),
        name="test-model-command",
    )
    command_thread.start()

    pid_path = broker.state_directory / "fake-runner-pid"
    deadline = time.monotonic() + 5
    while not pid_path.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pid_path.is_file(), "fake packaged runner did not enter its blocking state"
    runner_pid = int(pid_path.read_text(encoding="utf-8"))

    delivered_signals: list[int] = []
    real_killpg = os.killpg

    def recording_killpg(process_group: int, signum: int) -> None:
        if process_group == runner_pid:
            delivered_signals.append(signum)
        real_killpg(process_group, signum)

    monkeypatch.setattr(broker_module.os, "killpg", recording_killpg)
    started = time.monotonic()
    broker.close()
    elapsed = time.monotonic() - started
    command_thread.join(timeout=2)

    assert elapsed < 3
    assert command_thread.is_alive() is False
    assert [signal.SIGTERM, signal.SIGKILL] == delivered_signals
    assert broker._thread is not None and broker._thread.is_alive() is False
    assert broker._active_process is None
    assert broker._active_process_done.is_set()
    with pytest.raises(ProcessLookupError):
        os.kill(runner_pid, 0)
    assert len(results) == 1
    assert results[0].returncode == 125
    record = broker.evidence().records[0]
    assert record.runner_exit_code == -signal.SIGKILL
    assert "runner exit" in record.payload_error


@pytest.mark.parametrize("failure_stage", ["bind", "shims", "thread"])
def test_start_failure_rolls_back_all_owned_resources_and_remains_one_shot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    class StartFailure(RuntimeError):
        pass

    skill = make_fake_skill(tmp_path)
    root = tmp_path / "owned"
    root.mkdir()
    sentinel = root / "keep.txt"
    sentinel.write_text("user-owned", encoding="utf-8")
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        working_root=root,
        transport="tcp",
    )
    failure = StartFailure(failure_stage)

    if failure_stage == "bind":
        real_bind = broker._bind_socket

        def bind_then_fail(path: Path) -> None:
            real_bind(path)
            raise failure

        monkeypatch.setattr(broker, "_bind_socket", bind_then_fail)
    elif failure_stage == "shims":
        real_write_shims = broker._write_shims

        def write_then_fail() -> None:
            real_write_shims()
            raise failure

        monkeypatch.setattr(broker, "_write_shims", write_then_fail)
    else:
        real_thread_start = broker_module.threading.Thread.start

        def thread_start_then_fail(thread: threading.Thread) -> None:
            real_thread_start(thread)
            raise failure

        monkeypatch.setattr(broker_module.threading.Thread, "start", thread_start_then_fail)

    with pytest.raises(StartFailure) as caught:
        broker.start()
    assert caught.value is failure
    assert sorted(path.name for path in root.iterdir()) == [sentinel.name]
    assert broker._socket is None
    assert broker._socket_path is None
    assert broker._thread is None
    assert broker._started is False
    assert broker._created_directories == []
    with pytest.raises(GatewayBrokerError, match="has not started"):
        _ = broker.shim_directory
    with pytest.raises(GatewayBrokerError, match="cannot be restarted"):
        broker.start()


def test_failed_start_removes_implicit_temporary_root_and_preserves_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = make_fake_skill(tmp_path)
    broker = CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    )
    failure = RuntimeError("shim write failed")
    captured_roots: list[Path] = []
    real_write_shims = broker._write_shims

    def write_then_fail() -> None:
        assert broker._working_root is not None
        captured_roots.append(broker._working_root)
        real_write_shims()
        raise failure

    monkeypatch.setattr(broker, "_write_shims", write_then_fail)
    with pytest.raises(RuntimeError) as caught:
        broker.start()

    assert caught.value is failure
    assert len(captured_roots) == 1
    assert captured_roots[0].exists() is False
    assert broker._temporary_directory is None
    assert broker._working_root is None
    with pytest.raises(GatewayBrokerError, match="cannot be restarted"):
        broker.start()


def test_constructor_rejects_empty_steps_and_runner_owned_global_overrides(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    with pytest.raises(ValueError, match="at least one"):
        CodexGatewayBroker(skill_source=skill, expected_steps=())
    with pytest.raises(ValueError, match="exactly"):
        ExpectedGatewayStep("status", "status", allowed_exit_codes=(0, 2))
    with pytest.raises(ValueError, match="runner-owned"):
        ExpectedGatewayStep(
            "status",
            "status",
            gateway_global_arguments=("--state-dir", "/tmp/model-state"),
        )
    with pytest.raises(ValueError, match="canonical"):
        ExpectedGatewayStep(
            "call",
            "call",
            ("ak.wwise.waapi.getFunctions",),
            allow_omitted_empty_json_objects=True,
        )
    with pytest.raises(TypeError, match="callable or None"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(ExpectedGatewayStep("status", "status"),),
            trusted_step_observer="not-callable",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="expected_wwise_version"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=(ExpectedGatewayStep("status", "status"),),
            expected_wwise_version="2030.1",
        )
    for arguments in (
        ("--state-dir", "/tmp/model-state"),
        ("--state-dir=/tmp/model-state",),
        ("--evidence-dir", "/tmp/model-evidence"),
        ("--evidence-dir=/tmp/model-evidence",),
    ):
        with pytest.raises(ValueError, match="runner-owned"):
            CodexGatewayBroker(
                skill_source=skill,
                expected_steps=(ExpectedGatewayStep("status", "status"),),
                gateway_global_arguments=arguments,
            )


def test_new_broker_attaches_existing_a_phase_state_with_new_token_and_evidence(
    tmp_path: Path,
) -> None:
    skill = make_fake_skill(tmp_path)
    request = {"operation": "ak.wwise.core.object.setNotes", "value": "phase-a"}
    a_root = tmp_path / "phase-a-owned"
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep(
                "preview",
                "preview",
                ("--request-json", SemanticJsonArgument(request)),
            ),
        ),
        working_root=a_root,
        transport="tcp",
    ) as phase_a:
        a_environment = phase_a.model_environment(os.environ)
        old_token = a_environment[BROKER_TOKEN_ENV]
        assert run_model_command(
            phase_a,
            ["preview", "--request-json", json.dumps(request)],
            environment=a_environment,
        ).returncode == 0
        shared_state = phase_a.state_directory
        a_evidence = phase_a.evidence_directory
        assert phase_a.evidence().passed is True

    b_root = tmp_path / "phase-b-owned"
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(
            ExpectedGatewayStep("show", "transaction-show", ("tx-dynamic-123",)),
        ),
        existing_state_directory=shared_state,
        working_root=b_root,
        transport="tcp",
    ) as phase_b:
        assert phase_b.state_directory == shared_state
        assert phase_b.evidence_directory != a_evidence
        b_environment = phase_b.model_environment(os.environ)
        assert b_environment[BROKER_TOKEN_ENV] != old_token

        stale_environment = dict(b_environment)
        stale_environment[BROKER_TOKEN_ENV] = old_token
        stale = run_model_command(
            phase_b,
            ["transaction-show", "tx-dynamic-123"],
            environment=stale_environment,
        )
        assert stale.returncode == 126
        assert "authentication failed" in stale.stderr
        assert len((shared_state / "fake-runner-calls.jsonl").read_text().splitlines()) == 1

        attached = run_model_command(
            phase_b,
            ["transaction-show", "tx-dynamic-123"],
            environment=b_environment,
        )
        assert attached.returncode == 0
        payload = json.loads(attached.stdout[attached.stdout.index("{") :])
        assert payload["transaction_id"] == "tx-dynamic-123"
        assert payload["state_dir"] == str(shared_state)
        assert len((shared_state / "fake-runner-calls.jsonl").read_text().splitlines()) == 2
        # The stale-token attempt is audited but does not poison the new
        # authenticated broker state.
        assert phase_b.evidence().terminal_state == "COMPLETE"
        assert phase_b.evidence().complete is False
        assert phase_b.evidence().passed is False


def test_existing_state_directory_must_exist_and_not_be_symlink(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    step = (ExpectedGatewayStep("status", "status"),)
    with pytest.raises(ValueError, match="existing directory"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=step,
            existing_state_directory=tmp_path / "missing",
        )

    real = tmp_path / "real-state"
    real.mkdir()
    linked = tmp_path / "linked-state"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        CodexGatewayBroker(
            skill_source=skill,
            expected_steps=step,
            existing_state_directory=linked,
        )


@pytest.mark.parametrize(
    "selector",
    (
        ("--version", "2022.1"),
        ("--version=2022.1",),
        ("--wwise-version", "2022.1"),
        ("--wwise-version=2022.1",),
    ),
)
def test_resolver_canonicalizes_runner_and_gateway_level_version_selectors(
    tmp_path: Path,
    selector: tuple[str, ...],
) -> None:
    skill = make_fake_skill(tmp_path)
    runner = str(skill / "scripts" / "run.py")
    runner_level = ["python", runner, *selector, "gateway.py", "status"]
    gateway_level = ["python", runner, "gateway.py", *selector, "status"]

    before = resolve_gateway_invocation(runner_level, skill_source=skill)
    after = resolve_gateway_invocation(gateway_level, skill_source=skill)

    assert before.raw_model_argv != after.raw_model_argv
    assert before.normalized_model_argv == after.normalized_model_argv
    assert before.gateway_arguments == after.gateway_arguments
    assert before.argv_sha256 == after.argv_sha256


def test_resolver_and_reconciliation_fail_closed(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    correct = ["python3", str(skill / "scripts" / "run.py"), "gateway.py", "status"]
    resolved = resolve_gateway_invocation(correct, skill_source=skill)
    assert resolved.subcommand == "status"
    assert resolved.normalized_model_argv[0] == "python3"

    with pytest.raises(GatewayInvocationError, match="exactly"):
        resolve_gateway_invocation(
            ["python", str(skill.resolve() / "scripts" / "../scripts" / "run.py"), "gateway.py", "status"],
            skill_source=skill,
        )
    with pytest.raises(GatewayInvocationError, match="gateway.py"):
        resolve_gateway_invocation(
            ["python", str(skill / "scripts" / "run.py"), "other.py", "status"],
            skill_source=skill,
        )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, ["status"]).returncode == 0
        evidence = broker.evidence()
        mismatch = reconcile_gateway_commands(
            [["python", str(skill / "scripts" / "run.py"), "gateway.py", "buses"]],
            evidence,
            skill_source=skill,
        )
        assert mismatch.passed is False
        assert any("differs" in error for error in mismatch.errors)


def test_broker_accepts_empty_explicit_working_root_and_preserves_evidence(tmp_path: Path) -> None:
    skill = make_fake_skill(tmp_path)
    root = tmp_path / "owned"
    root.mkdir()
    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        working_root=root,
        transport="tcp",
    ) as broker:
        assert run_model_command(broker, ["status"]).returncode == 0
        state_directory = broker.state_directory
        assert (state_directory / "fake-runner-calls.jsonl").is_file()
    assert (state_directory / "fake-runner-calls.jsonl").is_file()
