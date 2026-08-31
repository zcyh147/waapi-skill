from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from tests.support.platform_filesystem import create_symlink_or_skip
from tests.destructive.support.sandbox_fixture import (
    ProjectHash,
    SandboxMetadata,
    SandboxProject,
)
from tests.semantic.support import codex_heavy_project_runner_v3 as runner
from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle_v3
from tests.semantic.support.codex_compound_heavy_v1 import (
    load_compound_heavy_profile,
)
from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_direct_protocol,
    build_transaction_protocol,
    call_step,
    query_object_step,
    wait_topic_step,
)
from tests.semantic.support.codex_harness import (
    CodexHarnessError,
    CodexInfrastructureError,
    CodexInfrastructureFailure,
)
from tests.semantic.support.codex_media_pool_runtime_v3 import (
    WINE_C_DRIVE_TARGET,
    WINE_Z_DRIVE_TARGET,
)
from tests.semantic.support.codex_gateway_broker import (
    DraftTypedActionBatchArgument,
    ExpectedGatewayStep,
    MetadataTokenProjection,
)
from tests.semantic.support.codex_object_heavy_v3 import (
    business_query_path_arguments,
    build_object_heavy_v3_recipe,
)


class _Verification:
    passed = True
    failures: tuple[str, ...] = ()


def test_weak_verifier_oracle_accepts_clear_chinese_boundary() -> None:
    response = (
        "profile：`typed_input`\ncount：`3`\n\n"
        "弱验证：仅已验证脚本返回结果符合结构；未验证、也不声称已验证"
        "脚本的全部业务副作用。"
    )

    assert runner.final_response_reports_weak_verifier_boundary(response)
    assert runner.final_response_reports_weak_verifier_boundary(
        "profile: typed_input; count: 3; "
        "已验证返回结果符合反射结果结构；未验证、也不能声称已验证"
        "该 Lua 脚本的全部业务副作用。"
    )
    assert not runner.final_response_reports_weak_verifier_boundary(
        "profile: typed_input; count: 3; 已验证全部业务副作用"
    )


def _successful_spawn_topic_publisher(
    _host,
    _port,
    version,
    request_values,
    send_connection,
) -> None:
    started = time.monotonic_ns()
    call_started = [time.monotonic_ns() for _value in request_values]
    call_finished = [time.monotonic_ns() for _value in request_values]
    payload = {
        "contract": runner._TOPIC_CHILD_RESULT_CONTRACT,
        "process_id": os.getpid(),
        "parent_process_id": os.getppid(),
        "version": version,
        "request_count": len(request_values),
        "started_at_monotonic_ns": started,
        "finished_at_monotonic_ns": time.monotonic_ns(),
        "client_opened": True,
        "client_closed": True,
        "direct_call_count": len(request_values),
        "result_count": len(request_values),
        "publisher_call_started_at_monotonic_ns": call_started,
        "publisher_call_evidence": [
            {
                "index": index,
                "request_sha256": runner._json_sha256(request_value),
                "status": "succeeded",
                "uri": "ak.test.publish",
                "args_sha256": runner._json_sha256({}),
                "options_sha256": runner._json_sha256({}),
                "started_at_monotonic_ns": call_started[index - 1],
                "finished_at_monotonic_ns": call_finished[index - 1],
                "result": runner._bounded_json_evidence({"ok": True}),
            }
            for index, request_value in enumerate(request_values, start=1)
        ],
        "error": None,
    }
    try:
        runner._send_topic_publisher_child_result(send_connection, payload)
    finally:
        send_connection.close()


def _hanging_spawn_topic_publisher(
    _host,
    _port,
    _version,
    _request_values,
    _send_connection,
) -> None:
    while True:
        time.sleep(1.0)


def _oversized_spawn_topic_publisher(
    _host,
    _port,
    _version,
    _request_values,
    send_connection,
) -> None:
    try:
        send_connection.send_bytes(
            b"x" * (runner._TOPIC_CHILD_RESULT_CEILING_BYTES + 1)
        )
    except (BrokenPipeError, OSError):
        pass
    while True:
        time.sleep(1.0)


def _scenario(
    api: str = "ak.wwise.core.object.get",
    *,
    scenario_id: str = "OBJ22-F-GET-01",
    protocol: str = "single",
    item_type: str = "function",
    count: int = 1,
    fixture: dict | None = None,
    version: str = "2022.1",
):
    prompt = "请读取这个 Wwise 工程并总结结果。"
    return SimpleNamespace(
        id=scenario_id,
        api=api,
        versions=(version,),
        protocol=protocol,
        item_type=item_type,
        fixture=fixture or {},
        prompt=prompt,
        visible_inputs=(),
        confirmation_turn_count=0 if protocol == "single" else count,
        confirmation_prompt="确认执行这个预览。" if protocol != "single" else None,
        primary_dispatch=SimpleNamespace(count=count),
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        render_prompt=lambda values: prompt,
    )


def _unit(scenario=None, *, turns: int = 1):
    value = scenario or _scenario()
    return SimpleNamespace(
        scenario=value,
        unit_id=value.id,
        version="2022.1",
        turns=tuple(
            SimpleNamespace(
                prompt=(
                    value.prompt
                    if index == 1
                    else value.confirmation_prompt
                )
            )
            for index in range(1, turns + 1)
        ),
    )


def _options(tmp_path: Path) -> runner.HeavyProjectRunnerOptions:
    return runner.HeavyProjectRunnerOptions(
        skill_source=tmp_path / "skill",
        codex_binary=tmp_path / "codex",
        auth_json=tmp_path / "auth.json",
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        service_tier="default",
        timeout_seconds=30.0,
        live_environment=MappingProxyType({"WWISE_TEST_CONFIG": "unused"}),
    )


def _prepared(
    *,
    cleanup=None,
    cleanup_before_shutdown=None,
    post_shutdown=None,
    turn_reference_schedule=None,
) -> runner._PreparedCase:
    typed_sections = SimpleNamespace(
        writer_kwargs=lambda: {
            "fixture_spec": {"kind": "synthetic_typed", "sha256": "f" * 64},
            "payload_bindings": {
                "primary_steps": ["object.get"],
                "verification_steps": ["object.get"],
            },
            "assertion_ids": ["synthetic.typed"],
            "static_expectation": {"synthetic": True},
            "live_binding": {"synthetic": True},
            "delta_rules": [],
        }
    )
    return runner._PreparedCase(
        prompt="请读取这个 Wwise 工程并总结结果。",
        visible_values={},
        protocol=build_direct_protocol(
            [query_object_step("object.get", ("query-object", "--from", "project", "--take", "1"))]
        ),
        required_reference="references/waapi-query.md",
        snapshot=lambda: ("sealed",),
        verify_final=lambda _payload, _result: _Verification(),
        turn_reference_schedule=turn_reference_schedule,
        typed_sections=typed_sections,
        cleanup_success=cleanup,
        cleanup_before_shutdown=cleanup_before_shutdown,
        post_shutdown=post_shutdown,
    )


class _FakeDirect:
    instances: list["_FakeDirect"] = []

    def __init__(self, *, host: str = "127.0.0.1", port: int = 49152) -> None:
        self.host = host
        self.port = port
        self.calls: list[dict] = []
        self.closed = False
        self.created_thread = threading.get_ident()
        type(self).instances.append(self)

    def __call__(self, uri, args, options):
        self.calls.append({"uri": uri, "args": dict(args), "options": dict(options)})
        return {"ok": True}

    def open_peer(self):
        return type(self)(host=self.host, port=self.port)

    def close(self) -> None:
        self.closed = True


def test_owned_direct_actor_bounds_hung_disconnect_and_reaps_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_disconnect = threading.Event()
    disconnect_started = threading.Event()
    actor_threads: list[tuple[str, int, bool]] = []

    class FakeRequestFailed(Exception):
        pass

    class FakeWaapiClient:
        def __init__(self, *, url, allow_exception) -> None:
            assert url == "ws://127.0.0.1:49152/waapi"
            assert allow_exception is True
            actor_threads.append(
                ("construct", threading.get_ident(), threading.current_thread().daemon)
            )
            self._client_thread = SimpleNamespace(
                daemon=threading.current_thread().daemon
            )

        def call(self, uri, args, *, options):
            actor_threads.append(
                ("call", threading.get_ident(), threading.current_thread().daemon)
            )
            return {"uri": uri, "args": args, "options": options}

        def disconnect(self):
            actor_threads.append(
                ("disconnect", threading.get_ident(), threading.current_thread().daemon)
            )
            disconnect_started.set()
            release_disconnect.wait()

    monkeypatch.setitem(
        sys.modules,
        "waapi",
        SimpleNamespace(
            WaapiClient=FakeWaapiClient,
            WaapiRequestFailed=FakeRequestFailed,
        ),
    )
    direct = runner.OwnedDirectWaapiCall(host="127.0.0.1", port=49152)
    result = direct("ak.test.echo", {"value": 1}, {"return": ["id"]})
    assert result["uri"] == "ak.test.echo"
    assert direct.owner_thread_daemon is True
    assert direct.client_thread_daemon is True

    started = time.monotonic()
    assert direct.close(wait_seconds=0.01) is False
    assert time.monotonic() - started < 0.5
    assert disconnect_started.is_set()
    assert direct.fully_closed is False

    release_disconnect.set()
    assert direct.finish_close(wait_seconds=1.0) is True
    assert direct.fully_closed is True
    assert {value[0] for value in actor_threads} == {
        "construct",
        "call",
        "disconnect",
    }
    assert len({value[1] for value in actor_threads}) == 1
    assert all(value[2] is True for value in actor_threads)


def test_owned_direct_actor_converts_frozen_requests_to_strict_plain_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[object, object]] = []

    class FakeRequestFailed(Exception):
        pass

    class FakeWaapiClient:
        def __init__(self, **_kwargs) -> None:
            self._client_thread = SimpleNamespace(
                daemon=threading.current_thread().daemon
            )

        def call(self, _uri, args, *, options):
            observed.append((args, options))
            json.dumps(
                {"args": args, "options": options},
                allow_nan=False,
            )
            return {"return": []}

        def disconnect(self):
            return True

    monkeypatch.setitem(
        sys.modules,
        "waapi",
        SimpleNamespace(
            WaapiClient=FakeWaapiClient,
            WaapiRequestFailed=FakeRequestFailed,
        ),
    )
    direct = runner.OwnedDirectWaapiCall(host="127.0.0.1", port=49152)
    args = MappingProxyType(
        {
            "objects": (
                MappingProxyType(
                    {
                        "children": (
                            MappingProxyType({"name": "Custom DB"}),
                        )
                    }
                ),
            )
        }
    )

    direct(
        "ak.wwise.core.object.set",
        args,
        MappingProxyType({"return": ("id", "name")}),
    )

    sent_args, sent_options = observed[0]
    assert sent_args == {"objects": [{"children": [{"name": "Custom DB"}]}]}
    assert sent_options == {"return": ["id", "name"]}
    assert type(sent_args) is dict
    assert type(sent_args["objects"]) is list
    assert type(sent_args["objects"][0]) is dict
    assert direct.calls[0]["args"] == sent_args

    invalid_values = (
        {1: "non-string key"},
        {"path": Path("/tmp/not-json")},
        {"items": {"unordered"}},
        {"number": float("nan")},
        {"number": float("inf")},
    )
    for invalid in invalid_values:
        with pytest.raises(runner.HeavyProjectRunnerError, match="trusted direct WAAPI"):
            direct("ak.test.invalid", invalid, {})
    assert len(observed) == 1
    assert direct.close(wait_seconds=1.0) is True


def test_owned_direct_call_timeout_poisons_handle_until_bounded_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_call = threading.Event()

    class FakeRequestFailed(Exception):
        pass

    class BlockingWaapiClient:
        def __init__(self, **_kwargs) -> None:
            self._client_thread = SimpleNamespace(
                daemon=threading.current_thread().daemon
            )

        def call(self, _uri, _args, *, options):
            assert options == {}
            release_call.wait()
            return {"late": True}

        def disconnect(self):
            return True

    monkeypatch.setitem(
        sys.modules,
        "waapi",
        SimpleNamespace(
            WaapiClient=BlockingWaapiClient,
            WaapiRequestFailed=FakeRequestFailed,
        ),
    )
    monkeypatch.setattr(runner, "_DIRECT_CALL_WAIT_SECONDS", 0.01)
    direct = runner.OwnedDirectWaapiCall(host="127.0.0.1", port=49152)

    with pytest.raises(
        runner._HeavyProjectInfrastructureError,
        match="call timed out",
    ):
        direct("ak.test.block", {}, {})
    with pytest.raises(runner.HeavyProjectRunnerError, match="closed"):
        direct("ak.test.second", {}, {})

    release_call.set()
    assert direct.finish_close(wait_seconds=1.0) is True


class _FakeLifecycle:
    instances: list["_FakeLifecycle"] = []

    def __init__(self, *, scenario_id, version, scenario_root, **_kwargs) -> None:
        self.scenario_id = scenario_id
        self.version = version
        self.scenario_root = Path(scenario_root)
        self.finished_status = None
        type(self).instances.append(self)

    def start(self):
        evidence = self.scenario_root / "evidence"
        owned = self.scenario_root / "owned"
        evidence.mkdir(parents=True)
        owned.mkdir()
        return SimpleNamespace(
            scenario_id=self.scenario_id,
            version=self.version,
            host="127.0.0.1",
            port=49152,
            evidence_root=evidence,
            owned_root=owned,
            asset_root=owned / "assets",
            io_root=owned / "io",
            runner_environment={},
        )

    def finish(self, status, *, reason="", post_shutdown_hook=None):
        self.finished_status = status
        if post_shutdown_hook is not None:
            post_shutdown_hook(SimpleNamespace())
        return SimpleNamespace(
            final_status=status,
            errors=(f"scenario:{reason}",) if reason else (),
            as_dict=lambda: {"final_status": status},
        )


def _fake_task(task_root: Path, *, passed: bool = True, archive_turn: bool = True):
    task_root.mkdir(parents=True, exist_ok=False)
    if archive_turn:
        turn = task_root / "turns" / "turn-01"
        turn.mkdir(parents=True)
        (turn / "turn-grade.json").write_text("{}\n", encoding="utf-8")
    return SimpleNamespace(
        scenario_id="OBJ22-F-GET-01",
        version="2022.1",
        task_root=task_root,
        thread_id="thread-1",
        turns=(SimpleNamespace(),),
        turn_grades=(SimpleNamespace(),),
        broker_evidence=SimpleNamespace(),
        passed=passed,
    )


_GATEWAY_COMMAND = (
    "python /skill/scripts/run.py gateway.py operation-schema object.create"
)


def _first_turn_result(
    *,
    before_gateway: str = "准备读取工程。",
    after_gateway: tuple[str, ...],
) -> SimpleNamespace:
    events = [
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": before_gateway},
        },
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": _GATEWAY_COMMAND},
        },
        *(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": text},
            }
            for text in after_gateway
        ),
    ]
    return SimpleNamespace(
        stdout="\n".join(json.dumps(event) for event in events),
        final_response=after_gateway[-1],
        command_facts=SimpleNamespace(gateway_commands=(_GATEWAY_COMMAND,)),
    )


def _install_orchestration_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    prepared: runner._PreparedCase,
) -> None:
    _FakeLifecycle.instances.clear()
    _FakeDirect.instances.clear()
    monkeypatch.setattr(runner, "ScenarioLifecycle", _FakeLifecycle)
    monkeypatch.setattr(runner, "OwnedDirectWaapiCall", _FakeDirect)
    monkeypatch.setattr(runner, "_prepare_case", lambda *_args, **_kwargs: prepared)
    monkeypatch.setattr(
        runner,
        "_audit_primary_dispatch",
        lambda *_args, **_kwargs: {"dispatch_count": 1},
    )


def test_project_runner_forwards_prepared_reference_schedule(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    schedule = (("references/waapi-query.md",),)
    _install_orchestration_fakes(
        monkeypatch,
        prepared=_prepared(turn_reference_schedule=schedule),
    )
    captured: dict[str, object] = {}

    def run_task(**kwargs):
        captured["turn_reference_schedule"] = kwargs[
            "turn_reference_schedule"
        ]
        captured["developer_instructions"] = kwargs[
            "developer_instructions"
        ]
        return _fake_task(kwargs["task_root"])

    monkeypatch.setattr(runner, "run_v3_codex_task", run_task)

    options = replace(
        _options(tmp_path),
        developer_instructions="sealed bootstrap instructions",
    )
    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=tmp_path / "case",
        options=options,
    )

    assert outcome.status == "PASS"
    assert captured["turn_reference_schedule"] == schedule
    assert captured["developer_instructions"] == (
        "sealed bootstrap instructions"
    )


def test_project_runner_api_union_is_exact_and_excludes_only_cli() -> None:
    assert runner.PROJECT_RUNNER_APIS == frozenset(
        {
            *runner.OBJECT_APIS,
            *runner.INTEGRATION_PRIMARY_APIS,
            *runner.IMPORT_APIS,
                *runner.SOUNDBANK_RUNTIME_APIS,
                runner.AUDIO_CONVERT_URI,
                runner.MEDIA_POOL_GET_URI,
                runner.GET_INFO_URI,
                runner.CORE_LUA_URI,
            }
        )
    assert runner.AUDIO_CONVERT_URI in runner.PROJECT_RUNNER_APIS
    assert not any(".cli." in api for api in runner.PROJECT_RUNNER_APIS)
    assert runner.PROJECT_RUNNER_MODEL_RESOLVED_REQUEST_FIELDS == {
        "ak.wwise.core.soundbank.convertExternalSources": frozenset({"io_root"})
    }


def test_dispatch_audit_accepts_only_the_sealed_topic_ack_as_auxiliary_evidence(
    tmp_path: Path,
) -> None:
    evidence = (tmp_path / "evidence").resolve()
    evidence.mkdir()
    dispatch_path = evidence / "100-call-ak_wwise_core_soundbank_generated.json"
    dispatch_payload = {
        "evidence_path": str(dispatch_path),
        "api": runner.SOUNDBANK_TOPIC,
    }
    dispatch_path.write_bytes(runner._canonical_json_bytes(dispatch_payload) + b"\n")
    ack_path = evidence / "subscription-ack-reviewed.json"
    ack_payload = {
        "contract": runner.SUBSCRIPTION_ACK_CONTRACT,
        "step_name": "soundbank.generated.wait",
        "topic": runner.SOUNDBANK_TOPIC,
    }
    ack_raw = runner._canonical_json_bytes(ack_payload) + b"\n"
    ack_path.write_bytes(ack_raw)
    proof = {
        "ack_path": str(ack_path),
        "ack_payload": ack_payload,
        "ack_file_sha256": hashlib.sha256(ack_raw).hexdigest(),
    }

    rows = runner._read_dispatch_evidence(
        evidence,
        topic_subscription_ack=proof,
    )

    assert [row["api"] for row in rows] == [runner.SOUNDBANK_TOPIC]


def test_primary_dispatch_audit_accepts_stream_lifecycle_without_wait_call(
    tmp_path: Path,
) -> None:
    evidence = (tmp_path / "evidence").resolve()
    evidence.mkdir()
    ack_path = evidence / "subscription-ack-stream.json"
    ack_payload = {
        "contract": runner.SUBSCRIPTION_ACK_CONTRACT,
        "step_name": "soundbank.generated.stream",
        "topic": runner.SOUNDBANK_TOPIC,
    }
    ack_raw = runner._canonical_json_bytes(ack_payload) + b"\n"
    ack_path.write_bytes(ack_raw)
    proof = {
        "ack_path": str(ack_path),
        "ack_payload": ack_payload,
        "ack_file_sha256": hashlib.sha256(ack_raw).hexdigest(),
    }
    task = SimpleNamespace(
        broker_evidence=SimpleNamespace(evidence_directory=str(evidence))
    )
    events = [
        {"soundbank": {"name": "Weapons_Core"}, "platform": {"name": "Mac"}},
        {"soundbank": {"name": "Weapons_Core"}, "platform": {"name": "Windows"}},
    ]

    audit = runner._audit_primary_dispatch(
        _scenario(
            runner.SOUNDBANK_TOPIC,
            scenario_id="O22-SB-GENERATED-03",
            item_type="topic",
            count=2,
        ),
        task=task,
        topic_payload={
            "contract": "waapi-skill.topic-stream/v1",
            "command": "stream-topic",
            "record_type": "terminal",
            "status": "completed",
            "completion_reason": "duration_elapsed",
            "event_count": 2,
            "events": events,
            "cleanup": "unsubscribed",
        },
        topic_subscription_ack=proof,
    )

    assert audit == {
        "api": runner.SOUNDBANK_TOPIC,
        "gateway_dispatch_calls": 0,
        "topic_lifecycle": "stream-topic",
        "event_count": 2,
    }


@pytest.mark.parametrize("tamper", ("hash", "payload", "outside", "extra_ack"))
def test_dispatch_audit_rejects_unsealed_or_ambiguous_topic_ack_evidence(
    tmp_path: Path,
    tamper: str,
) -> None:
    evidence = (tmp_path / "evidence").resolve()
    evidence.mkdir()
    dispatch_path = evidence / "100-call.json"
    dispatch_path.write_bytes(
        runner._canonical_json_bytes(
            {"evidence_path": str(dispatch_path), "api": runner.SOUNDBANK_TOPIC}
        )
        + b"\n"
    )
    ack_path = evidence / "subscription-ack-reviewed.json"
    ack_payload = {
        "contract": runner.SUBSCRIPTION_ACK_CONTRACT,
        "step_name": "soundbank.generated.wait",
        "topic": runner.SOUNDBANK_TOPIC,
    }
    ack_raw = runner._canonical_json_bytes(ack_payload) + b"\n"
    ack_path.write_bytes(ack_raw)
    proof = {
        "ack_path": str(ack_path),
        "ack_payload": dict(ack_payload),
        "ack_file_sha256": hashlib.sha256(ack_raw).hexdigest(),
    }
    if tamper == "hash":
        proof["ack_file_sha256"] = "f" * 64
    elif tamper == "payload":
        proof["ack_payload"]["topic"] = "ak.wwise.core.soundbank.other"
    elif tamper == "outside":
        outside = tmp_path / "subscription-ack-outside.json"
        outside.write_bytes(ack_raw)
        proof["ack_path"] = str(outside.resolve())
    elif tamper == "extra_ack":
        extra = evidence / "subscription-ack-extra.json"
        extra.write_bytes(ack_raw)
    else:  # pragma: no cover - the parameter set is closed
        raise AssertionError(tamper)

    with pytest.raises(runner._HeavyProjectSemanticError):
        runner._read_dispatch_evidence(
            evidence,
            topic_subscription_ack=proof,
        )


@pytest.mark.parametrize("spoof", ("contract", "filename", "contract_and_filename"))
def test_dispatch_audit_rejects_ack_spoof_that_has_dispatcher_path_and_api(
    tmp_path: Path,
    spoof: str,
) -> None:
    evidence = (tmp_path / "evidence").resolve()
    evidence.mkdir()
    dispatch_path = evidence / "100-call.json"
    dispatch_path.write_bytes(
        runner._canonical_json_bytes(
            {"evidence_path": str(dispatch_path), "api": runner.SOUNDBANK_TOPIC}
        )
        + b"\n"
    )
    ack_path = evidence / "subscription-ack-reviewed.json"
    ack_payload = {
        "contract": runner.SUBSCRIPTION_ACK_CONTRACT,
        "step_name": "soundbank.generated.wait",
        "topic": runner.SOUNDBANK_TOPIC,
    }
    ack_raw = runner._canonical_json_bytes(ack_payload) + b"\n"
    ack_path.write_bytes(ack_raw)
    proof = {
        "ack_path": str(ack_path),
        "ack_payload": ack_payload,
        "ack_file_sha256": hashlib.sha256(ack_raw).hexdigest(),
    }
    spoof_path = evidence / (
        "subscription-ack-extra.json"
        if spoof in {"filename", "contract_and_filename"}
        else "extra-auxiliary.json"
    )
    spoof_payload = {
        "evidence_path": str(spoof_path),
        "api": "ak.wwise.core.object.get",
    }
    if spoof in {"contract", "contract_and_filename"}:
        spoof_payload["contract"] = runner.SUBSCRIPTION_ACK_CONTRACT
    spoof_path.write_bytes(runner._canonical_json_bytes(spoof_payload) + b"\n")

    with pytest.raises(
        runner._HeavyProjectSemanticError,
        match="unsealed topic subscription ACK",
    ):
        runner._read_dispatch_evidence(
            evidence,
            topic_subscription_ack=proof,
        )


@pytest.mark.parametrize("violation", ("invalid_json", "path", "api"))
def test_dispatch_content_violations_are_semantic_failures(
    tmp_path: Path,
    violation: str,
) -> None:
    evidence = (tmp_path / "evidence").resolve()
    evidence.mkdir()
    dispatch_path = evidence / "100-call.json"
    if violation == "invalid_json":
        dispatch_path.write_bytes(b"{not-json\n")
    else:
        payload: dict[str, object] = {
            "evidence_path": str(dispatch_path),
            "api": runner.SOUNDBANK_TOPIC,
        }
        if violation == "path":
            payload["evidence_path"] = str(evidence / "other.json")
        elif violation == "api":
            payload["api"] = 42
        else:  # pragma: no cover - the parameter set is closed
            raise AssertionError(violation)
        dispatch_path.write_bytes(runner._canonical_json_bytes(payload) + b"\n")

    with pytest.raises(runner._HeavyProjectSemanticError) as caught:
        runner._read_dispatch_evidence(evidence)

    assert runner._failure_status(caught.value, runtime=None) == "FAIL"


def test_dispatch_read_error_is_infrastructure_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence = (tmp_path / "evidence").resolve()
    evidence.mkdir()
    dispatch_path = evidence / "100-call.json"
    dispatch_path.write_bytes(
        runner._canonical_json_bytes(
            {"evidence_path": str(dispatch_path), "api": runner.SOUNDBANK_TOPIC}
        )
        + b"\n"
    )
    original_read_bytes = Path.read_bytes

    def fail_read(path: Path) -> bytes:
        if path == dispatch_path:
            raise OSError("synthetic read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    with pytest.raises(runner._HeavyProjectInfrastructureError) as caught:
        runner._read_dispatch_evidence(evidence)

    assert runner._failure_status(caught.value, runtime=None) == "BLOCKED"


def test_common_plan_writer_requires_and_forwards_typed_sections_exactly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario = _scenario()
    protocol = build_direct_protocol(
        [query_object_step("object.get", ("query-object", "--from", "project", "--take", "1"))]
    )
    provenance = SimpleNamespace(
        sha256="b" * 64,
        payload={"protocol": {"sha256": "a" * 64}},
    )
    with pytest.raises(runner.HeavyProjectRunnerError, match="without typed"):
        runner._write_common_business_oracle_plan(
            scenario=scenario,
            version="2022.1",
            scenario_root=tmp_path,
            protocol=protocol,
            provenance=provenance,
            runner="project",
            typed_sections=None,
        )

    family_kwargs = {
        "fixture_spec": {"kind": "typed", "sha256": "c" * 64},
        "payload_bindings": {
            "primary_steps": ["object.get"],
            "verification_steps": [],
        },
        "assertion_ids": ["typed.exact"],
        "static_expectation": {"sealed": "static"},
        "live_binding": {"sealed": "live"},
        "delta_rules": [{"kind": "typed"}],
    }
    captured: dict[str, object] = {}

    def write(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(path=tmp_path / "plan.json", sha256="d" * 64)

    monkeypatch.setattr(runner, "write_business_oracle_plan", write)
    sections = SimpleNamespace(writer_kwargs=lambda: family_kwargs)
    runner._write_common_business_oracle_plan(
        scenario=scenario,
        version="2022.1",
        scenario_root=tmp_path,
        protocol=protocol,
        provenance=provenance,
        runner="project",
        typed_sections=sections,
    )

    for key, value in family_kwargs.items():
        assert captured[key] == value


@pytest.mark.parametrize("api", sorted(runner.PROJECT_RUNNER_APIS))
def test_common_plan_writer_fails_closed_for_every_project_api_without_typed_sections(
    api: str,
    tmp_path: Path,
) -> None:
    scenario = _scenario(api, scenario_id="O22-SB-PROJECT-TYPED-01")
    with pytest.raises(runner.HeavyProjectRunnerError, match="without typed"):
        runner._write_common_business_oracle_plan(
            scenario=scenario,
            version="2022.1",
            scenario_root=tmp_path,
            protocol=build_direct_protocol([
                query_object_step("query", ("query-object", "--from", "project", "--take", "1"))
            ]),
            provenance=SimpleNamespace(sha256="b" * 64, payload={"protocol": {"sha256": "a" * 64}}),
            runner="project",
            typed_sections=None,
        )


def test_prepare_case_fails_closed_instead_of_falling_through_to_soundbank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "prepare_soundbank_runtime",
        lambda *_args, **_kwargs: pytest.fail("unknown API reached SoundBank runtime"),
    )
    with pytest.raises(runner.HeavyProjectRunnerError, match="no prepared-case branch"):
        runner._prepare_case(
            _scenario("ak.wwise.core.unknown"),
            runtime=SimpleNamespace(),
            direct=SimpleNamespace(),
            media_holder={},
        )


def test_prepare_get_info_case_binds_exact_live_process_and_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = {
        "displayName": "Wwise",
        "isCommandLine": True,
        "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        "processId": 4242,
        "processPath": "/Applications/WwiseConsole",
        "apiVersion": 1,
        "platform": "macosx",
        "configuration": "release",
        "version": {
            "year": 2021,
            "major": 1,
            "minor": 14,
            "build": 8108,
            "displayName": "v2021.1.14",
        },
    }
    status_wwise = {
        key: baseline[key]
        for key in (
            "apiVersion",
            "displayName",
            "isCommandLine",
            "processId",
            "processPath",
            "sessionId",
            "version",
        )
    }
    calls: list[tuple[str, dict, dict]] = []

    def direct(api, args, options):
        calls.append((api, args, options))
        return baseline

    monkeypatch.setattr(runner, "_project_document_digest", lambda _path: "d" * 64)
    scenario = _scenario(
        runner.GET_INFO_URI,
        scenario_id="O22-GET-INFO-01",
    )
    scenario.prompt = "确认当前连接的 Wwise 实例与进程身份。"
    project = tmp_path / "SampleProject.wproj"
    project.write_text(
        '<?xml version="1.0"?><WwiseDocument><ProjectInfo>'
        '<Project Name="SampleProject" '
        'ID="{16164796-C6E6-491A-8799-C42A33110A84}"/>'
        '</ProjectInfo></WwiseDocument>',
        encoding="utf-8",
    )
    prepared = runner._prepare_case(
        scenario,
        runtime=SimpleNamespace(
            version="2021.1",
            lifecycle=SimpleNamespace(
                process=SimpleNamespace(pid=4200),
                ready_result=baseline,
            ),
            sandbox=SimpleNamespace(
                sandbox_path=tmp_path,
                sandbox_project=project,
            ),
        ),
        direct=direct,
        media_holder={},
        unit=SimpleNamespace(unit_id="TYP21-ZERO-GET-INFO"),
    )

    assert calls == [(runner.GET_INFO_URI, {}, {})]
    assert [step.subcommand for step in prepared.protocol.steps] == ["status"]
    assert prepared.required_reference is None
    assert prepared.turn_reference_schedule is None
    assert prepared.typed_sections.static_expectation["verification_boundary"] == (
        "exact_host_identity"
    )
    omitted_status = prepared.verify_final(
        {"wwise": status_wwise},
        SimpleNamespace(final_response="Wwise 2021.1.14.8108，进程 4242。"),
    )
    assert omitted_status.passed is False
    assert "Gateway status identity was not observed" in omitted_status.failures
    prepared.observe_payload(
        prepared.protocol.steps[0],
        {
            "wwise": status_wwise,
            "project": {
                "id": "{16164796-C6E6-491A-8799-C42A33110A84}",
                "name": "SampleProject",
                "type": "Project",
                "path": "\\",
                "displayTitle": "SampleProject",
                "isDirty": False,
                "currentLanguageId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "currentPlatformId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
            },
        },
    )
    verification = prepared.verify_final(
        {"wwise": status_wwise},
        SimpleNamespace(final_response="Wwise 2021.1.14.8108，进程 4242。"),
    )
    assert verification.passed is True
    split_build = prepared.verify_final(
        {"wwise": status_wwise},
        SimpleNamespace(
            final_response="Wwise v2021.1.14，build 8108，进程 4242。"
        ),
    )
    assert split_build.passed is True
    incomplete = prepared.verify_final(
        {"wwise": status_wwise},
        SimpleNamespace(final_response="Wwise 2021.1，进程 4242。"),
    )
    assert incomplete.passed is False
    wrong_split_build = prepared.verify_final(
        {"wwise": status_wwise},
        SimpleNamespace(
            final_response="Wwise v2021.1.14，build 8109，进程 4242。"
        ),
    )
    assert wrong_split_build.passed is False
    negated_split_build = prepared.verify_final(
        {"wwise": status_wwise},
        SimpleNamespace(
            final_response="Wwise 不是 v2021.1.14，build 8108，进程 4242。"
        ),
    )
    assert negated_split_build.passed is False


@pytest.mark.parametrize(
    ("version", "status_project_api"),
    (
        ("2021.1", "ak.wwise.core.object.get"),
        ("2025.1", "ak.wwise.core.getProjectInfo"),
    ),
)
def test_get_info_dispatch_audit_binds_the_single_status_route(
    tmp_path: Path,
    version: str,
    status_project_api: str,
) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()

    def write_evidence(name: str, api: str) -> Path:
        path = evidence_root / name
        path.write_text(
            json.dumps({"api": api, "evidence_path": str(path)}),
            encoding="utf-8",
        )
        return path

    status_get_info = write_evidence("01-get-info.json", runner.GET_INFO_URI)
    status_project = write_evidence("02-project.json", status_project_api)
    task = SimpleNamespace(
        broker_evidence=SimpleNamespace(
            evidence_directory=str(evidence_root),
            records=(
                SimpleNamespace(
                    step_name="host.status",
                    payload={
                        "calls": [
                            {
                                "api": runner.GET_INFO_URI,
                                "evidence_path": str(status_get_info),
                            },
                            {
                                "api": status_project_api,
                                "evidence_path": str(status_project),
                            },
                        ]
                    },
                ),
            ),
        )
    )

    audit = runner._audit_primary_dispatch(
        _scenario(
            runner.GET_INFO_URI,
            scenario_id="O22-GET-INFO-01",
            version=version,
        ),
        task=task,
        topic_payload=None,
        expected_count=1,
    )

    assert audit == {
        "api": runner.GET_INFO_URI,
        "dispatch_count": 1,
        "status_preflight_dispatch_count": 0,
    }

    task.broker_evidence.records[0].payload["calls"][1]["api"] = (
        "ak.wwise.core.getProjectInfo"
        if status_project_api == "ak.wwise.core.object.get"
        else "ak.wwise.core.object.get"
    )
    with pytest.raises(
        runner.HeavyProjectRunnerError,
        match="status dispatch partition is invalid",
    ):
        runner._audit_primary_dispatch(
            _scenario(
                runner.GET_INFO_URI,
                scenario_id="O22-GET-INFO-01",
                version=version,
            ),
            task=task,
            topic_payload=None,
            expected_count=1,
        )
    task.broker_evidence.records[0].payload["calls"][1]["api"] = (
        status_project_api
    )

    task.broker_evidence.records[0].payload["calls"][0]["evidence_path"] = []
    with pytest.raises(
        runner.HeavyProjectRunnerError,
        match="evidence paths are invalid",
    ):
        runner._audit_primary_dispatch(
            _scenario(
                runner.GET_INFO_URI,
                scenario_id="O22-GET-INFO-01",
                version=version,
            ),
            task=task,
            topic_payload=None,
            expected_count=1,
        )

    task.broker_evidence.records[0].payload["calls"][0]["evidence_path"] = str(
        status_get_info
    )
    task.broker_evidence.records[0].payload["calls"][1]["evidence_path"] = []
    with pytest.raises(
        runner.HeavyProjectRunnerError,
        match="evidence paths are invalid",
    ):
        runner._audit_primary_dispatch(
            _scenario(
                runner.GET_INFO_URI,
                scenario_id="O22-GET-INFO-01",
                version=version,
            ),
            task=task,
            topic_payload=None,
            expected_count=1,
        )

    task.broker_evidence.records[0].payload["calls"][1]["evidence_path"] = str(
        status_project
    )
    task.broker_evidence.records[0].payload["calls"][0]["evidence_path"] = str(
        status_project
    )
    task.broker_evidence.records[0].payload["calls"][1]["evidence_path"] = str(
        status_get_info
    )
    with pytest.raises(
        runner.HeavyProjectRunnerError,
        match="not bound to its ordered status result",
    ):
        runner._audit_primary_dispatch(
            _scenario(
                runner.GET_INFO_URI,
                scenario_id="O22-GET-INFO-01",
                version=version,
            ),
            task=task,
            topic_payload=None,
            expected_count=1,
        )


def test_prepare_get_info_rejects_status_for_a_different_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = {
        "processId": 4242,
        "sessionId": "session",
        "version": {"year": 2025, "major": 1, "minor": 0, "build": 9000},
    }
    monkeypatch.setattr(runner, "_project_document_digest", lambda _path: "d" * 64)
    scenario = _scenario(runner.GET_INFO_URI, scenario_id="O22-GET-INFO-01")
    scenario.prompt = "确认当前连接的 Wwise 实例与进程身份。"
    project = tmp_path / "SampleProject.wproj"
    project.write_text(
        '<?xml version="1.0"?><WwiseDocument><ProjectInfo>'
        '<Project Name="SampleProject" '
        'ID="{16164796-C6E6-491A-8799-C42A33110A84}"/>'
        '</ProjectInfo></WwiseDocument>',
        encoding="utf-8",
    )
    prepared = runner._prepare_case(
        scenario,
        runtime=SimpleNamespace(
            version="2025.1",
            lifecycle=SimpleNamespace(
                process=SimpleNamespace(pid=4200),
                ready_result=baseline,
            ),
            sandbox=SimpleNamespace(
                sandbox_path=tmp_path,
                sandbox_project=project,
            ),
        ),
        direct=lambda *_args: baseline,
        media_holder={},
        unit=SimpleNamespace(unit_id="TYP25-ZERO-GET-INFO"),
    )

    prepared.observe_payload(
        prepared.protocol.steps[0],
        {
            "wwise": baseline,
            "project": {
                "id": "{16164796-C6E6-491A-8799-C42A33110A84}",
                "name": "SampleProject",
                "path": str(project),
                "displayTitle": "SampleProject",
                "isDirty": False,
                "currentLanguageId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "currentPlatformId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
            },
        },
    )

    with pytest.raises(runner.HeavyProjectRunnerError, match="sealed Wwise/project"):
        prepared.observe_payload(
            prepared.protocol.steps[0],
            {
                "wwise": baseline,
                "project": {
                    "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                    "name": "OtherProject",
                    "type": "Project",
                    "path": str(tmp_path / "OtherProject.wproj"),
                },
            },
        )


def test_typed_profile_set03_requires_exact_live_property_metadata() -> None:
    scenario = _scenario(
        "ak.wwise.core.object.set",
        scenario_id="OBJ22-F-SET-03",
        version="2022.1",
    )

    assert runner._compound_object_metadata_binding(
        scenario,
        version="2022.1",
        profile_unit_id="TYP22-METADATA-OBJECT-SET",
    ) == (
        "ActorMixer",
        ("volume", "pitch", "notes", "output bus"),
        ("Volume", "Pitch", "OutputBus"),
    )
    with pytest.raises(
        runner.HeavyProjectRunnerError,
        match="outside its reviewed lane",
    ):
        runner._compound_object_metadata_binding(
            scenario,
            version="2023.1",
            profile_unit_id="TYP22-METADATA-OBJECT-SET",
        )
    assert runner._compound_object_metadata_binding(
        scenario,
        version="2022.1",
    ) is None


@pytest.mark.parametrize(
    ("unit_id", "scenario_id", "api", "version"),
    (
        (
            "TYP24-METADATA-OBJECT-SET",
            "OBJ22-F-SET-01",
            "ak.wwise.core.object.set",
            "2024.1",
        ),
        (
            "TYP25-METADATA-OBJECT-SET",
            "OBJ22-F-SET-02",
            "ak.wwise.core.object.set",
            "2025.1",
        ),
    ),
)
def test_other_typed_profile_object_metadata_lanes_are_exact(
    unit_id: str,
    scenario_id: str,
    api: str,
    version: str,
) -> None:
    scenario = _scenario(api, scenario_id=scenario_id, version=version)
    assert runner._compound_object_metadata_binding(
        scenario,
        version=version,
        profile_unit_id=unit_id,
    ) == (
        runner.get_codex_version_layout_v3(version).reflected_type("ActorMixer"),
        ("volume",),
        ("Volume",),
    )


def test_typed_profile_set03_uses_business_draft_field_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario(
        "ak.wwise.core.object.set",
        scenario_id="OBJ22-F-SET-03",
        version="2022.1",
    )
    recipe = build_object_heavy_v3_recipe("OBJ22-F-SET-03", "2022.1")
    monkeypatch.setattr(
        runner,
        "discover_metadata",
        lambda **_kwargs: pytest.fail("retired outer metadata discovery ran"),
    )

    protocol = runner._build_compound_object_metadata_protocol(
        scenario,
        recipe=recipe,
        direct=SimpleNamespace(),
        version="2022.1",
        profile_unit_id="TYP22-METADATA-OBJECT-SET",
    )

    assert protocol is not None
    assert [step.subcommand for step in protocol.steps[:2]] == [
        "operation-schema",
        "draft-start",
    ]
    assert any(
        step.subcommand == "draft-discover-fields" for step in protocol.steps
    )
    assert any(
        step.subcommand == "draft-declare-existing" for step in protocol.steps
    )
    assert all(step.subcommand != "metadata" for step in protocol.steps)


def test_prepare_get_info_rejects_process_drift_from_readiness_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready = {
        "processId": 4242,
        "sessionId": "ready-session",
        "version": {"year": 2021, "major": 1, "minor": 14, "build": 8108},
    }
    drifted = {**ready, "processId": 4243}
    monkeypatch.setattr(runner, "_project_document_digest", lambda _path: "d" * 64)
    scenario = _scenario(runner.GET_INFO_URI, scenario_id="O22-GET-INFO-01")
    scenario.prompt = "确认当前连接的 Wwise 实例与进程身份。"
    project = tmp_path / "SampleProject.wproj"
    project.write_text(
        '<?xml version="1.0"?><WwiseDocument><ProjectInfo>'
        '<Project Name="SampleProject" '
        'ID="{16164796-C6E6-491A-8799-C42A33110A84}"/>'
        '</ProjectInfo></WwiseDocument>',
        encoding="utf-8",
    )

    with pytest.raises(runner.HeavyProjectRunnerError, match="readiness proof"):
        runner._prepare_case(
            scenario,
            runtime=SimpleNamespace(
                version="2021.1",
                lifecycle=SimpleNamespace(
                    process=SimpleNamespace(pid=4200),
                    ready_result=ready,
                ),
                sandbox=SimpleNamespace(
                    sandbox_path=tmp_path,
                    sandbox_project=project,
                ),
            ),
            direct=lambda *_args: drifted,
            media_holder={},
            unit=SimpleNamespace(unit_id="TYP21-ZERO-GET-INFO"),
        )


def test_prepare_lua_case_seals_source_and_preserves_result_schema_only_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runner, "_project_document_digest", lambda _path: "e" * 64)

    def no_read(*_args, **_kwargs):
        raise AssertionError("Lua preparation must not perform a live read")

    scenario = _scenario(
        runner.CORE_LUA_URI,
        scenario_id="LUA23-CORE-FILE-02",
        protocol="preview_confirm",
    )
    scenario.prompt = (
        "执行现成文件 {script_file}，隔离目录 {io_root}，并报告弱验证边界。"
    )
    prepared = runner._prepare_case(
        scenario,
        runtime=SimpleNamespace(
            version="2025.1",
            asset_root=tmp_path / "assets",
            sandbox=SimpleNamespace(sandbox_path=tmp_path),
        ),
        direct=no_read,
        media_holder={},
        unit=SimpleNamespace(unit_id="TYP25-CODE-LUA-FILE"),
    )

    assert prepared.typed_sections.static_expectation["verification_boundary"] == (
        "result_schema_only"
    )
    assert prepared.visible_values["script_file"].endswith("user-script.lua")
    execute_step = next(
        step for step in prepared.protocol.steps if step.name.endswith(".execute")
    )
    prepared.observe_payload(
        execute_step,
        {
            "dispatch_result": {
                "result": {"return": {"profile": "typed_input", "count": 3}}
            }
        },
    )
    terminal = prepared.verify_final(
        {
            "status": "result_schema_checked",
            "result_schema_checked": True,
            "verified": False,
            "verification_strength": "complete_reflected_schema",
            "verification": {"business_state_verified": False},
        },
        SimpleNamespace(final_response="unused"),
    )
    assert terminal.passed is True
    response = prepared.verify_turn(
        2,
        SimpleNamespace(
            final_response=(
                "脚本返回 profile=typed_input、count=3；验证仅限返回结果结构。"
            )
        ),
    )
    assert response.passed is True

    equivalent_boundary = prepared.verify_turn(
        2,
        SimpleNamespace(
            final_response=(
                "脚本已执行，返回 profile=typed_input、count=3。"
                "验证仅确认返回结果符合预期结构；未验证、也不能据此声称"
                "已验证脚本的全部业务副作用。"
            )
        ),
    )
    assert equivalent_boundary.passed is True

    observed_natural_boundary = prepared.verify_turn(
        2,
        SimpleNamespace(
            final_response=(
                "profile=typed_input，count=3；验证仅限脚本返回结果的结构；"
                "不能声称已验证脚本的全部业务副作用。"
            )
        ),
    )
    assert observed_natural_boundary.passed is True

    macos_observed_boundary = prepared.verify_turn(
        2,
        SimpleNamespace(
            final_response=(
                "profile：typed_input；count：3。"
                "仅验证了脚本返回结果的结构；"
                "不能声称已验证脚本的全部业务副作用。"
            )
        ),
    )
    assert macos_observed_boundary.passed is True

    windows_observed_boundary = prepared.verify_turn(
        2,
        SimpleNamespace(
            final_response=(
                "profile：typed_input；count：3。"
                "弱验证：仅确认脚本返回结果符合预期结构；"
                "不能据此声称已验证脚本的全部业务副作用。"
            )
        ),
    )
    assert windows_observed_boundary.passed is True

    reflected_result_boundary = prepared.verify_turn(
        2,
        SimpleNamespace(
            final_response=(
                "profile：typed_input；count：3。"
                "弱验证已完成：仅确认返回结果符合反射的结果结构。"
                "不能据此声称已验证脚本的全部业务副作用。"
            )
        ),
    )
    assert reflected_result_boundary.passed is True

    equivalent_not_representative_boundary = prepared.verify_turn(
        2,
        SimpleNamespace(
            final_response=(
                "profile：typed_input；count：3。"
                "验证仅限脚本返回结果的结构；"
                "不代表已验证脚本的全部业务副作用。"
            )
        ),
    )
    assert equivalent_not_representative_boundary.passed is True

    broader_overclaim = prepared.verify_turn(
        2,
        SimpleNamespace(
            final_response=(
                "profile=typed_input，count=3；验证仅限返回结果结构；"
                "另外已经确认所有业务状态正确。"
            )
        ),
    )
    assert broader_overclaim.passed is False

    overclaim = prepared.verify_turn(
        2,
        SimpleNamespace(
            final_response=(
                "profile=typed_input，count=3；验证不仅限于结果结构，"
                "已经验证全部业务副作用。"
            )
        ),
    )
    assert overclaim.passed is False


def _archive_test_prepare_case_binds_2025_object_recipe_to_active_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile_path = (
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in load_compound_heavy_profile(profile_path).units
        if row.unit_id == "CMP25-OBJ22-F-CREATE-02"
    )
    protocol = build_transaction_protocol(
        (
            {
                "contract": "waapi-skill.operation-request/v1",
                "version": "2025.1",
                "operation": "object.create",
                "arguments": {
                    "parent": {
                        "kind": "path",
                        "value": r"\Containers\Default Work Unit",
                    },
                    "type": "ActorMixer",
                    "name": "Robot_VO",
                    "on_name_conflict": "merge",
                },
            },
        )
    )
    object_runtime = SimpleNamespace(
        before=SimpleNamespace(snapshot="sealed-before"),
        gateway_protocol=lambda: protocol,
        render_prompt=lambda: "sealed 2025 object prompt",
        snapshot=lambda: ("sealed",),
        verify_after_execution=lambda: _Verification(),
    )
    object_runtime.prepare = lambda: object_runtime
    captured: dict[str, object] = {}

    def prepared_runtime(*, scenario, recipe, backend, asset_root):
        captured.update(
            scenario=scenario,
            recipe=recipe,
            backend=backend,
            asset_root=asset_root,
        )
        return object_runtime

    sections = SimpleNamespace(writer_kwargs=lambda: {})
    monkeypatch.setattr(runner, "PreparedObjectRuntime", prepared_runtime)
    monkeypatch.setattr(
        runner,
        "ClosedDirectObjectBackend",
        lambda direct: SimpleNamespace(direct=direct),
    )
    monkeypatch.setattr(
        runner,
        "seal_object_input_file_manifest",
        lambda _paths: MappingProxyType({}),
    )
    monkeypatch.setattr(
        runner,
        "compile_object_business_plan",
        lambda *_args, **_kwargs: sections,
    )
    monkeypatch.setattr(
        runner,
        "validate_object_business_plan",
        lambda *_args, **_kwargs: None,
    )

    prepared = runner._prepare_case(
        unit.scenario,
        runtime=SimpleNamespace(
            version=unit.version,
            sandbox=SimpleNamespace(
                sandbox_project=tmp_path / "SampleProject.wproj",
            ),
            asset_root=tmp_path / "assets",
        ),
        direct=SimpleNamespace(),
        media_holder={},
    )

    recipe = captured["recipe"]
    assert recipe.version == "2025.1"
    assert recipe.fixture.objects[0].path.startswith(r"\Containers")
    assert prepared.typed_sections is sections


@pytest.mark.parametrize(
    ("unit_id", "object_type"),
    (
        ("CMP22-OBJ22-F-CREATE-03", "ActorMixer"),
        ("CMP25-OBJ22-F-CREATE-03", "PropertyContainer"),
        ("CMP22-OBJ22-F-SET-01", "ActorMixer"),
        ("CMP25-OBJ22-F-SET-02", "PropertyContainer"),
    ),
)
def _archive_test_compound_object_protocol_binds_volume_to_trusted_live_metadata(
    monkeypatch: pytest.MonkeyPatch,
    unit_id: str,
    object_type: str,
) -> None:
    profile_path = (
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in load_compound_heavy_profile(profile_path).units
        if row.unit_id == unit_id
    )
    observed: dict[str, object] = {}
    payload = {
        "contract": "waapi-skill.metadata-discovery/v2",
        "authority": "live-waapi",
        "result_detail": "compact",
        "selection_required": True,
        "exact_live_name_required_for_mutation": True,
        "dependency_closure_complete": True,
        "unresolved_dependencies": [],
        "scope": {
            "kind": "object_type",
            "requested": object_type,
            "resolved": {"name": object_type},
        },
        "candidates": [
            {
                "name": "Volume",
                "kind": "property",
                "metadata": {"type": "Real32"},
            }
        ],
        "dependency_candidates": [],
    }

    def discover(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(as_dict=lambda: payload)

    monkeypatch.setattr(runner, "discover_metadata", discover)
    recipe = build_object_heavy_v3_recipe(unit.base_scenario_id, unit.version)
    protocol = runner._build_compound_object_metadata_protocol(
        unit.scenario,
        recipe=recipe,
        direct=SimpleNamespace(),
        version=unit.version,
    )

    assert protocol is not None
    preview_index = next(
        index
        for index, step in enumerate(protocol.steps)
        if step.subcommand == "preview-from-draft"
    )
    assert protocol.turn_prefix_counts == (
        preview_index + 1,
        len(protocol.steps),
    )
    assert tuple(step.subcommand for step in protocol.steps[:2]) == (
        "operation-schema",
        "metadata",
    )
    assert observed["object_type"] == object_type
    assert observed["queries"] == ("volume",)
    assert observed["limit"] == 8
    metadata_binding = next(
        (
            step.metadata_binding
            for step in protocol.steps
            if step.metadata_binding is not None
        ),
        None,
    )
    if metadata_binding is None:
        metadata_binding = next(
            candidate
            for step in protocol.steps
            for argument in step.arguments
            for candidate in (
                tuple(action.metadata_binding for action in argument.actions)
                if isinstance(argument, DraftTypedActionBatchArgument)
                else (getattr(argument, "metadata_binding", None),)
            )
            if candidate is not None
        )
    assert metadata_binding.object_type == object_type
    assert metadata_binding.required_tokens == ("Volume",)
    assert metadata_binding.expected_projection == (
        MetadataTokenProjection("Volume", "property", "Real32"),
    )


def test_compound_object_without_dynamic_property_keeps_original_protocol() -> None:
    profile_path = (
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in load_compound_heavy_profile(profile_path).units
        if row.unit_id == "CMP25-OBJ22-F-CREATE-02"
    )
    recipe = build_object_heavy_v3_recipe(unit.base_scenario_id, unit.version)

    assert (
        runner._build_compound_object_metadata_protocol(
            unit.scenario,
            recipe=recipe,
            direct=SimpleNamespace(),
            version=unit.version,
        )
        is None
    )


@pytest.mark.parametrize(
    ("unit_id", "expected_path"),
    (
        (
            "CMP22-OBJ22-F-CREATE-02",
            (
                r"\Actor-Mixer Hierarchy\Default Work Unit"
                r"\SemanticLab\NPC\Robot_VO"
            ),
        ),
        (
            "CMP25-OBJ22-F-CREATE-02",
            r"\Containers\Default Work Unit\SemanticLab\NPC\Robot_VO",
        ),
    ),
)
def _archive_test_compound_merge_requires_exact_existing_root_type_query(
    unit_id: str,
    expected_path: str,
) -> None:
    profile_path = (
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in load_compound_heavy_profile(profile_path).units
        if row.unit_id == unit_id
    )
    recipe = build_object_heavy_v3_recipe(
        unit.base_scenario_id,
        unit.version,
    )

    protocol = runner.build_object_merge_query_protocol(
        unit.scenario,
        recipe,
    )

    assert protocol is not None
    preview_index = next(
        index
        for index, step in enumerate(protocol.steps)
        if step.subcommand == "preview-from-draft"
    )
    assert protocol.turn_prefix_counts == (
        preview_index + 1,
        len(protocol.steps),
    )
    assert tuple(step.subcommand for step in protocol.steps[:2]) == (
        "query-object",
        "operation-schema",
    )
    assert protocol.steps[0].arguments == business_query_path_arguments(
        expected_path
    )


def test_prepare_compound_import_uses_two_stage_reference_and_metadata_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile_path = (
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in load_compound_heavy_profile(profile_path).units
        if row.unit_id == "CMP25-O22-AUDIO-IMPORT-02"
    )
    calls: list[str] = []
    staged = SimpleNamespace(requires_metadata_binding=True)
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": r"\Containers\Default Work Unit\Bound",
                    "object_type": "Sound",
                    "properties": [
                        {"name": "IsLoopingEnabled", "value": True}
                    ],
                }
            ]
        },
    }
    bound = SimpleNamespace(
        operation_requests=(request,),
        metadata_queries=("looping",),
        visible_values=MappingProxyType(
            {
                "import_rows": json.dumps(
                    [{"audio_file": "/tmp/input.wav"}],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            }
        ),
    )
    handle = SimpleNamespace(
        reference_targets=MappingProxyType(
            {
                "output_bus": MappingProxyType(
                    {
                        "kind": "id",
                        "value": "{00000000-0000-0000-0000-000000000123}",
                    }
                )
            }
        ),
        request_reference_targets=MappingProxyType(
            {
                "output_bus": MappingProxyType(
                    {
                        "kind": "path",
                        "value": r"\Busses\Default Work Unit\Codex_Output_Bus",
                    }
                )
            }
        ),
        adopted=False,
        cleanup_emergency=lambda: calls.append("emergency-cleanup"),
    )
    backend_sentinel = SimpleNamespace()
    before = SimpleNamespace(snapshot="sealed")
    import_runtime = SimpleNamespace(
        hidden_before=before,
        plan=SimpleNamespace(metadata_binding={"bound": True}),
        render_prompt=lambda: "sealed compound import prompt",
        snapshot=lambda: ("sealed",),
        verify_after_execution=lambda: _Verification(),
        verify_zero_dispatch_unchanged=lambda: _Verification(),
        cleanup_success=lambda: (),
    )
    sections = SimpleNamespace(writer_kwargs=lambda: {})

    monkeypatch.setattr(
        runner,
        "materialize_import_case",
        lambda *_args, **_kwargs: staged,
    )
    monkeypatch.setattr(
        runner,
        "ClosedDirectWaapiBackend",
        lambda _direct, **_kwargs: backend_sentinel,
    )

    def prepare_references(scenario, materialized, *, version, backend):
        calls.append("references")
        assert scenario is unit.scenario
        assert materialized is staged
        assert version == "2025.1"
        assert backend is backend_sentinel
        return handle

    monkeypatch.setattr(
        runner,
        "prepare_import_reference_fixtures",
        prepare_references,
    )

    def bind(materialized, *, version, direct, reference_targets):
        calls.append("metadata-bind")
        assert materialized is staged
        assert version == "2025.1"
        assert reference_targets is handle.request_reference_targets
        assert reference_targets["output_bus"]["kind"] == "path"
        assert handle.reference_targets["output_bus"]["kind"] == "id"
        assert (
            reference_targets["output_bus"]["value"]
            != handle.reference_targets["output_bus"]["value"]
        )
        return bound, MappingProxyType({"trusted": True})

    monkeypatch.setattr(runner, "_bind_compound_import_metadata", bind)

    def prepare_runtime(
        scenario,
        materialized,
        *,
        sandbox_project,
        backend,
        reference_fixtures,
    ):
        calls.append("runtime")
        assert scenario is unit.scenario
        assert materialized is bound
        assert backend is backend_sentinel
        assert reference_fixtures is handle
        assert sandbox_project == tmp_path / "SampleProject.wproj"
        handle.adopted = True
        return import_runtime

    monkeypatch.setattr(runner, "prepare_import_runtime", prepare_runtime)
    monkeypatch.setattr(
        runner,
        "bound_import_metadata_tokens",
        lambda materialized: (
            ("IsLoopingEnabled",)
            if materialized is bound
            else pytest.fail("wrong bound import")
        ),
    )
    monkeypatch.setattr(
        runner,
        "project_required_metadata_tokens",
        lambda *_args, **_kwargs: (
            MetadataTokenProjection(
                "IsLoopingEnabled",
                "property",
                "Boolean",
            ),
        ),
    )
    monkeypatch.setattr(
        runner,
        "compile_import_business_plan",
        lambda *_args, **_kwargs: sections,
    )
    monkeypatch.setattr(
        runner,
        "validate_import_business_plan",
        lambda *_args, **_kwargs: None,
    )

    prepared = runner._prepare_case(
        unit.scenario,
        runtime=SimpleNamespace(
            version=unit.version,
            sandbox=SimpleNamespace(
                sandbox_project=tmp_path / "SampleProject.wproj",
            ),
            asset_root=tmp_path / "assets",
        ),
        direct=SimpleNamespace(),
        media_holder={},
    )

    assert calls == ["references", "metadata-bind", "runtime"]
    assert prepared.protocol.turn_prefix_counts == (7, 11)
    assert sum(
        step.subcommand == "metadata" for step in prepared.protocol.steps
    ) == 0
    assert next(
        step for step in prepared.protocol.steps if step.name == "tx01.preview"
    ).subcommand == "preview-from-draft"
    assert prepared.prompt == "sealed compound import prompt"
    assert prepared.cleanup_success is import_runtime.cleanup_success
    assert prepared.prompt_sources == {
        "compound_import_visible_rows": [
            {"audio_file": "/tmp/input.wav"}
        ]
    }


def test_prepare_compound_import_cleans_unadopted_bus_after_binding_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile_path = (
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in load_compound_heavy_profile(profile_path).units
        if row.unit_id == "CMP22-O22-AUDIO-IMPORT-03"
    )
    staged = SimpleNamespace(requires_metadata_binding=True)
    cleanup_calls: list[str] = []
    handle = SimpleNamespace(
        reference_targets=MappingProxyType({}),
        request_reference_targets=MappingProxyType({}),
        adopted=False,
        cleanup_emergency=lambda: cleanup_calls.append("cleaned"),
    )
    monkeypatch.setattr(
        runner,
        "materialize_import_case",
        lambda *_args, **_kwargs: staged,
    )
    monkeypatch.setattr(
        runner,
        "ClosedDirectWaapiBackend",
        lambda _direct, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        runner,
        "prepare_import_reference_fixtures",
        lambda *_args, **_kwargs: handle,
    )
    monkeypatch.setattr(
        runner,
        "_bind_compound_import_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("metadata binding failed")
        ),
    )
    monkeypatch.setattr(
        runner,
        "prepare_import_runtime",
        lambda *_args, **_kwargs: pytest.fail(
            "runtime must not start after metadata binding failure"
        ),
    )

    with pytest.raises(RuntimeError, match="metadata binding failed"):
        runner._prepare_case(
            unit.scenario,
            runtime=SimpleNamespace(
                version=unit.version,
                sandbox=SimpleNamespace(
                    sandbox_project=tmp_path / "SampleProject.wproj",
                ),
                asset_root=tmp_path / "assets",
            ),
            direct=SimpleNamespace(),
            media_holder={},
        )

    assert cleanup_calls == ["cleaned"]


def _soundbank_request(api: str) -> dict:
    operation_arguments = {
        "ak.wwise.core.soundbank.generate": {
            "operation": "soundbank.generate",
            "arguments": {
                "soundbanks": [
                    {
                        "name": "Bank",
                        "artifact_expectation": "nonlocalized",
                    }
                ],
                "platforms": ["Windows"],
                "skip_languages": True,
                "write_to_disk": True,
                "io_root": "/owned",
            },
        },
        "ak.wwise.core.soundbank.processDefinitionFiles": {
            "operation": "soundbank.processDefinitionFiles",
            "arguments": {
                "files": ["/owned/Bank.tsv"],
                "io_root": "/owned",
            },
        },
        "ak.wwise.core.soundbank.convertExternalSources": {
            "operation": "soundbank.convertExternalSources",
            "arguments": {
                "sources": [
                    {
                        "input": "/owned/input.wsources",
                        "platform": "Windows",
                        "output": "/owned/output",
                    }
                ],
                "io_root": "/owned",
            },
        },
        "ak.wwise.core.soundbank.setInclusions": {
            "operation": "soundbank.setInclusions",
            "arguments": {
                "soundbank": {"kind": "path", "value": r"\SoundBanks\Bank"},
                "mode": "replace",
                "inclusions": [],
            },
        },
    }
    entry = operation_arguments[api]
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        **entry,
    }


def _prepare_soundbank_case(
    monkeypatch: pytest.MonkeyPatch,
    scenario,
):
    materialized = SimpleNamespace(
        visible_values=MappingProxyType({"soundbank": "Bank"}),
        prompt_sources=MappingProxyType({"fixture": "sealed"}),
    )
    before = SimpleNamespace(snapshot="sealed-before")
    topic = None
    requests = ()
    if scenario.api == runner.SOUNDBANK_TOPIC:
        events = tuple(SimpleNamespace(index=index) for index in range(scenario.primary_dispatch.count))
        topic = SimpleNamespace(
            topic=runner.SOUNDBANK_TOPIC,
            event_count=scenario.primary_dispatch.count,
            match={},
            options={},
            publishers=tuple(
                SimpleNamespace(operation_request={"runner_owned": index})
                for index in range(scenario.primary_dispatch.count)
            ),
        )
    else:
        requests = (_soundbank_request(scenario.api),)
    runtime = SimpleNamespace(
        materialized=materialized,
        hidden_before=before,
        topic_plan=topic,
        operation_requests=requests,
        render_prompt=lambda: "sealed SoundBank prompt",
        snapshot=lambda: ("sealed",),
        cleanup_success=lambda: (),
        verify_after_execution=lambda: _Verification(),
        verify_zero_dispatch=lambda _payload: _Verification(),
        verify_topic=lambda _events: (_Verification(), _Verification()),
    )
    observed: dict[str, object] = {}
    sections = SimpleNamespace(writer_kwargs=lambda: {})

    def compile_plan(actual_materialized, actual_before, protocol):
        observed["compile"] = (actual_materialized, actual_before, protocol)
        return sections

    def validate_plan(actual_sections, actual_materialized, actual_before, protocol, *, verify_files):
        observed["validate"] = (
            actual_sections,
            actual_materialized,
            actual_before,
            protocol,
            verify_files,
        )

    monkeypatch.setattr(runner, "prepare_soundbank_runtime", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(
        runner,
        "ClosedDirectWaapiSoundBankBackend",
        lambda _direct, *, version: SimpleNamespace(version=version),
    )
    monkeypatch.setattr(runner, "compile_soundbank_business_plan", compile_plan)
    monkeypatch.setattr(runner, "validate_soundbank_business_plan", validate_plan)
    prepared = runner._prepare_case(
        scenario,
        runtime=SimpleNamespace(version="2022.1", sandbox=SimpleNamespace(sandbox_project=Path("/sandbox/project.wproj")), owned_root=Path("/sandbox/owned"), asset_root=Path("/sandbox/assets")),
        direct=SimpleNamespace(),
        media_holder={},
    )
    return prepared, observed, sections


@pytest.mark.parametrize(
    "api,scenario_id",
    (
        ("ak.wwise.core.soundbank.generate", "O22-SB-GENERATE-01"),
        ("ak.wwise.core.soundbank.processDefinitionFiles", "O22-SB-PROCESS-DEF-01"),
        ("ak.wwise.core.soundbank.convertExternalSources", "O22-SB-CONVERT-EXT-01"),
        ("ak.wwise.core.soundbank.setInclusions", "O22-SB-SET-INCLUSIONS-01"),
        (runner.SOUNDBANK_TOPIC, "O22-SB-GENERATED-01"),
    ),
)
def test_prepare_case_compiles_and_validates_typed_soundbank_sections_for_all_apis(
    monkeypatch: pytest.MonkeyPatch,
    api: str,
    scenario_id: str,
) -> None:
    topic = api == runner.SOUNDBANK_TOPIC
    scenario = _scenario(api, scenario_id=scenario_id, item_type="topic" if topic else "function", count=3 if topic else 1)
    prepared, observed, sections = _prepare_soundbank_case(monkeypatch, scenario)
    compiled = observed["compile"]
    validated = observed["validate"]
    assert compiled[0].visible_values == {"soundbank": "Bank"}
    assert compiled[1].snapshot == "sealed-before"
    assert validated[0] is sections
    assert validated[-1] is True
    assert prepared.typed_sections is sections
    if topic:
        assert [step.name for step in prepared.protocol.steps] == [
            "soundbank.generated.schema",
            "soundbank.generated.schema.language.entry",
            "soundbank.generated.schema.platform.entry",
            "soundbank.generated.schema.soundbank.match-group",
            "soundbank.generated.schema.soundbank.entry",
            "soundbank.generated.wait",
        ]
        assert len(prepared.topic_publishers) == 3
        assert all("publisher" not in step.name for step in prepared.protocol.steps)
    else:
        assert [step.name for step in prepared.protocol.steps if step.subcommand == "execute"] == ["tx01.execute"]


def test_prepare_case_soundbank_refusal_has_empty_primary_dispatch_and_typed_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario(
        "ak.wwise.core.soundbank.processDefinitionFiles",
        scenario_id=runner.PROCESS_REFUSAL_ID,
        count=0,
    )
    prepared, observed, sections = _prepare_soundbank_case(monkeypatch, scenario)
    protocol = observed["compile"][2]
    assert prepared.typed_sections is sections
    assert prepared.verify_refusal is not None
    assert not [step for step in protocol.steps if step.subcommand == "execute"]
    preview = next(step for step in protocol.steps if step.name == "tx01.preview")
    assert preview.allowed_exit_codes == (2,)
    assert preview.expected_error_code == runner.PROCESS_REFUSAL_ERROR_CODE


def test_audio_convert_prelaunch_uses_its_closed_conversion_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario(
        runner.AUDIO_CONVERT_URI,
        scenario_id="VS24-F-AUDIO-CONVERT-01",
        protocol="preview_confirm",
    )
    sentinel = object()
    received: list[object] = []
    monkeypatch.setattr(
        runner,
        "make_audio_conversion_prelaunch_hook",
        lambda value: received.append(value) or sentinel,
    )
    monkeypatch.setattr(
        runner,
        "make_project_prelaunch_hook",
        lambda _request: pytest.fail(
            "audio.convert must not use the generic project prelaunch hook"
        ),
    )

    hook = runner._prelaunch_hook(scenario, media_holder={})

    assert hook is sentinel
    assert received == [scenario]


def test_object_prelaunch_uses_closed_recipe_languages_not_fixture_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario(
        "ak.wwise.core.object.get",
        scenario_id="OBJ22-F-GET-02",
        fixture={
            "prerequisites": [
                "create direct and nested Sound descendants with deterministic language"
            ]
        },
    )
    sentinel = object()
    received: list[object] = []
    monkeypatch.setattr(
        runner,
        "make_project_prelaunch_hook",
        lambda request: received.append(request) or sentinel,
    )

    hook = runner._prelaunch_hook(scenario, media_holder={})

    assert hook is sentinel
    assert len(received) == 1
    request = received[0]
    assert request.scenario_id == "OBJ22-F-GET-02"
    assert request.languages == ("SFX", "English(US)", "Japanese")
    assert request.platforms == ("Windows",)


def test_import_prelaunch_canonicalizes_reviewed_fixture_language_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario(
        "ak.wwise.core.audio.importTabDelimited",
        scenario_id="O22-AUDIO-TAB-02",
        fixture={
            "asset_spec": {
                "rows": [
                    {"language": "Chinese"},
                    {"language": "English"},
                    {"language": "Japanese"},
                ],
                "tsv": [
                    {"language": "Chinese"},
                    {"language": "English"},
                    {"language": "Japanese"},
                ],
            }
        },
    )
    sentinel = object()
    received: list[object] = []
    monkeypatch.setattr(
        runner,
        "make_project_prelaunch_hook",
        lambda request: received.append(request) or sentinel,
    )

    hook = runner._prelaunch_hook(scenario, media_holder={})

    assert hook is sentinel
    assert len(received) == 1
    request = received[0]
    assert request.languages == (
        "SFX",
        "English(US)",
        "Chinese(PRC)",
        "Japanese",
    )
    assert request.platforms == ("Windows",)


@pytest.mark.parametrize(
    "scenario_id",
    ("O22-SB-GENERATE-02", "O22-SB-GENERATED-02"),
)
def test_soundbank_prelaunch_canonicalizes_reviewed_media_language_aliases(
    monkeypatch: pytest.MonkeyPatch,
    scenario_id: str,
) -> None:
    suite = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "waapi-skill"
        / "evals"
        / "suite-v3.json"
    )
    scenario = load_eval_bundle_v3(suite).scenario(scenario_id)
    sentinel = object()
    received: list[object] = []
    monkeypatch.setattr(
        runner,
        "make_project_prelaunch_hook",
        lambda request: received.append(request) or sentinel,
    )

    hook = runner._prelaunch_hook(scenario, media_holder={})

    assert hook is sentinel
    assert len(received) == 1
    request = received[0]
    assert request.languages == (
        "English(US)",
        "Chinese(PRC)",
        "Japanese",
    )
    assert request.platforms == ("Windows",)


@pytest.mark.parametrize(
    "version,scenario_id,expected_profile",
    (
        (
            "2025.1",
            "O22-SB-GENERATE-01",
            runner.WWISE_2025_SOUNDBANK_AURO_PROFILE,
        ),
        ("2022.1", "O22-SB-GENERATE-01", None),
        ("2025.1", "O22-SB-SET-INCLUSIONS-01", None),
        ("2025.1", "O22-SB-GENERATED-01", None),
    ),
)
def test_2025_auro_prelaunch_profile_is_scoped_only_to_soundbank_generate(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    scenario_id: str,
    expected_profile: str | None,
) -> None:
    suite = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "waapi-skill"
        / "evals"
        / "suite-v3.json"
    )
    scenario = load_eval_bundle_v3(suite).scenario(scenario_id)
    sentinel = object()
    received: list[object] = []
    monkeypatch.setattr(
        runner,
        "make_project_prelaunch_hook",
        lambda request: received.append(request) or sentinel,
    )

    hook = runner._prelaunch_hook(
        scenario,
        version=version,
        media_holder={},
    )

    assert hook is sentinel
    assert len(received) == 1
    assert received[0].auro_isolation_profile == expected_profile


def test_object_prelaunch_rejects_unknown_closed_recipe_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario(
        "ak.wwise.core.object.get",
        scenario_id="OBJ22-F-GET-02",
    )
    monkeypatch.setattr(
        runner,
        "build_object_heavy_v3_recipe",
        lambda _scenario_id, *, version: SimpleNamespace(
            version=version,
            fixture=SimpleNamespace(
                objects=(SimpleNamespace(source_language="Unreviewed"),)
            )
        ),
    )
    monkeypatch.setattr(
        runner,
        "make_project_prelaunch_hook",
        lambda _request: pytest.fail(
            "unsupported object languages must fail before building the hook"
        ),
    )

    with pytest.raises(
        runner.HeavyProjectRunnerError,
        match="unsupported prelaunch languages.*Unreviewed",
    ):
        runner._prelaunch_hook(scenario, media_holder={})


def test_prepare_audio_convert_binds_one_exact_io_root_and_full_verify_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario = _scenario(
        runner.AUDIO_CONVERT_URI,
        scenario_id="VS24-F-AUDIO-CONVERT-04",
        protocol="preview_confirm",
    )
    sandbox_root = tmp_path / "owned" / "sandbox-root" / "copy"
    sandbox_project = sandbox_root / "SampleProject.wproj"
    asset_root = tmp_path / "owned" / "assets"
    io_root = tmp_path / "owned" / "io"
    runtime = SimpleNamespace(
        sandbox=SimpleNamespace(
            sandbox_project=sandbox_project,
            sandbox_path=sandbox_root,
        ),
        asset_root=asset_root,
        io_root=io_root,
    )
    direct = _FakeDirect()
    observed: dict[str, object] = {}

    def build_plan(value, **kwargs):
        observed["plan_scenario"] = value
        observed["plan_kwargs"] = dict(kwargs)
        return SimpleNamespace(io_root=kwargs["io_root"])

    class FakeBackend:
        def __init__(self, value) -> None:
            observed["backend_direct"] = value

    class FakeAudioRuntime:
        def __init__(self, *, scenario, plan, backend) -> None:
            observed["runtime_scenario"] = scenario
            observed["runtime_plan"] = plan
            observed["runtime_backend"] = backend
            self.plan = plan
            self.before = SimpleNamespace(digest="sealed-before")

        def prepare(self):
            observed["prepared"] = True
            return self

        def render_prompt(self):
            return f"所有文件读写只允许落在 {self.plan.io_root} 以内。"

        def gateway_protocol(self):
            return build_direct_protocol(
                [
                    call_step(
                        "tx01.verify",
                        runner.AUDIO_CONVERT_URI,
                        version="2024.1",
                        args={
                            "objects": [r"\Actor-Mixer Hierarchy\SemanticLab"],
                            "platforms": ["Windows"],
                            "languages": ["SFX"],
                        },
                    )
                ]
            )

        def snapshot(self):
            return ("wwise-and-files", str(self.plan.io_root))

        def verify_preview_unchanged(self):
            observed["preview_verified"] = True
            return _Verification()

        def verify_after_execution(self, *, verify_payload):
            observed["verify_payload"] = verify_payload
            return _Verification()

    monkeypatch.setattr(runner, "build_audio_conversion_plan", build_plan)
    monkeypatch.setattr(runner, "ClosedAudioConversionBackend", FakeBackend)
    monkeypatch.setattr(runner, "PreparedAudioConversionRuntime", FakeAudioRuntime)
    typed_sections = SimpleNamespace(writer_kwargs=lambda: {})

    def compile_plan(plan, before, protocol, *, reviewed_scenario_fixture):
        observed["compiled"] = (
            plan,
            before,
            protocol,
            reviewed_scenario_fixture,
        )
        return typed_sections

    def validate_plan(
        sections,
        plan,
        before,
        protocol,
        *,
        reviewed_scenario_fixture,
        verify_files,
    ):
        observed["validated"] = (
            sections,
            plan,
            before,
            protocol,
            reviewed_scenario_fixture,
            verify_files,
        )

    monkeypatch.setattr(runner, "compile_audio_conversion_business_plan", compile_plan)
    monkeypatch.setattr(runner, "validate_audio_conversion_business_plan", validate_plan)

    prepared = runner._prepare_case(
        scenario,
        runtime=runtime,
        direct=direct,
        media_holder={},
    )

    assert observed["plan_scenario"] is scenario
    assert observed["plan_kwargs"] == {
        "sandbox_project": sandbox_project,
        "sandbox_root": sandbox_root,
        "asset_root": asset_root,
        "io_root": io_root,
    }
    assert observed["backend_direct"] is direct
    assert observed["runtime_scenario"] is scenario
    assert observed["prepared"] is True
    assert observed["compiled"][0] is observed["runtime_plan"]
    assert observed["compiled"][1].digest == "sealed-before"
    assert observed["compiled"][3] is scenario.fixture
    assert observed["validated"][-2] is scenario.fixture
    assert observed["validated"][-1] is True
    assert prepared.typed_sections is typed_sections
    assert prepared.prompt == f"所有文件读写只允许落在 {io_root} 以内。"
    assert prepared.required_reference == "references/waapi-operate.md"
    preview_payload = {"state": "awaiting_confirmation"}
    assert prepared.verify_preview is not None
    assert prepared.verify_preview(preview_payload).passed
    assert observed["preview_verified"] is True
    verify_payload = {
        "ok": True,
        "status": "result_schema_checked",
        "agent_result": {"result": {"errors": []}},
    }
    assert prepared.verify_final(verify_payload, SimpleNamespace()).passed
    assert observed["verify_payload"] is verify_payload

    with pytest.raises(runner.HeavyProjectRunnerError, match="payload is missing"):
        prepared.verify_final(None, SimpleNamespace())


def test_existing_scenario_root_is_rejected_without_overwriting_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    sentinel = root / "outcome.json"
    sentinel.write_text("user evidence\n", encoding="utf-8")
    with pytest.raises(runner.HeavyProjectRunnerError, match="already exists"):
        runner.run_heavy_project_unit(
            _unit(),
            scenario_root=root,
            options=_options(tmp_path),
        )
    assert sentinel.read_text(encoding="utf-8") == "user evidence\n"


def test_pre_codex_fixture_failure_does_not_claim_a_task_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_orchestration_fakes(monkeypatch, prepared=_prepared())

    def fail_prepare(*_args, **_kwargs):
        raise RuntimeError("fixture preparation failed")

    monkeypatch.setattr(runner, "_prepare_case", fail_prepare)
    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=tmp_path / "case",
        options=_options(tmp_path),
    )

    assert outcome.status == "BLOCKED"
    assert outcome.task_root is None
    assert outcome.thread_id is None


def test_deferred_direct_close_is_reaped_only_after_lifecycle_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class DeferredCloseDirect(_FakeDirect):
        def close(self):
            events.append("initial-close-timeout")
            self.closed = True
            return False

        def finish_close(self):
            events.append("post-shutdown-reap")
            return True

    class OrderedLifecycle(_FakeLifecycle):
        def finish(self, status, *, reason="", post_shutdown_hook=None):
            events.append("wwise-shutdown")
            return super().finish(
                status,
                reason=reason,
                post_shutdown_hook=post_shutdown_hook,
            )

    monkeypatch.setattr(runner, "ScenarioLifecycle", OrderedLifecycle)
    monkeypatch.setattr(runner, "OwnedDirectWaapiCall", DeferredCloseDirect)
    monkeypatch.setattr(runner, "_prepare_case", lambda *_args, **_kwargs: _prepared())
    monkeypatch.setattr(
        runner,
        "_audit_primary_dispatch",
        lambda *_args, **_kwargs: {"dispatch_count": 1},
    )
    monkeypatch.setattr(
        runner,
        "run_v3_codex_task",
        lambda **kwargs: _fake_task(kwargs["task_root"]),
    )

    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=tmp_path / "case",
        options=_options(tmp_path),
    )

    assert outcome.status == "PASS"
    assert events == [
        "initial-close-timeout",
        "wwise-shutdown",
        "post-shutdown-reap",
    ]
    assert outcome.checks["direct_client_close_deferred"] is True
    assert outcome.checks["direct_client_close_reaped_after_shutdown"] is True
    assert outcome.checks["direct_client_closed"] is True


def test_nonpassing_task_is_semantic_fail_and_never_runs_success_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cleanup_calls: list[str] = []
    _install_orchestration_fakes(
        monkeypatch,
        prepared=_prepared(cleanup=lambda: cleanup_calls.append("cleanup")),
    )
    monkeypatch.setattr(
        runner,
        "run_v3_codex_task",
        lambda **kwargs: _fake_task(kwargs["task_root"], passed=False),
    )

    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=tmp_path / "case",
        options=_options(tmp_path),
    )

    assert outcome.status == "FAIL"
    assert outcome.checks["task_passed"] is False
    assert cleanup_calls == []
    assert _FakeLifecycle.instances[-1].finished_status == "FAIL"
    assert _FakeDirect.instances[0].closed


def test_nonpassing_media_task_runs_pre_shutdown_cleanup_and_seals_final_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    success_cleanup_calls: list[str] = []
    adapter_holder: dict[str, runner._PreparedMediaPoolAdapter] = {}
    sealed_case = object()

    class OrderedDirect(_FakeDirect):
        def close(self):
            events.append("direct-close")
            return super().close()

    class OrderedLifecycle(_FakeLifecycle):
        def finish(self, status, *, reason="", post_shutdown_hook=None):
            events.append("wwise-shutdown")
            return super().finish(
                status,
                reason=reason,
                post_shutdown_hook=post_shutdown_hook,
            )

    def prepare(_scenario_value, *, runtime, direct, **_kwargs):
        base = _prepared(
            cleanup=lambda: success_cleanup_calls.append("success-only")
        )
        adapter = runner._PreparedMediaPoolAdapter(
            scenario=_scenario(
                runner.MEDIA_POOL_GET_URI,
                scenario_id="VS25-F-MEDIAPOOL-GET-03",
            ),
            runtime=runtime,
            direct=direct,
            staged=SimpleNamespace(materialized=sealed_case),
            preflight=SimpleNamespace(isolation=None),
            oracle=SimpleNamespace(),
            fields=(),
            protocol=base.protocol,
            reference_baseline=None,
            project_digest="a" * 64,
                custom_baseline_ids=("{BASELINE}",),
                custom_created_ids=MappingProxyType({"owned": "{CREATED}"}),
                waapi_y_drive_root=None,
            )
        adapter_holder["adapter"] = adapter

        def post_shutdown(_runtime):
            events.append("post-shutdown")
            assert adapter.cleanup_final_ids == ("{BASELINE}",)

        return _prepared(
            cleanup=lambda: success_cleanup_calls.append("success-only"),
            cleanup_before_shutdown=adapter.cleanup_before_shutdown,
            post_shutdown=post_shutdown,
        )

    _FakeLifecycle.instances.clear()
    _FakeDirect.instances.clear()
    monkeypatch.setattr(runner, "ScenarioLifecycle", OrderedLifecycle)
    monkeypatch.setattr(runner, "OwnedDirectWaapiCall", OrderedDirect)
    monkeypatch.setattr(runner, "_prepare_case", prepare)
    monkeypatch.setattr(
        runner,
        "_audit_primary_dispatch",
        lambda *_args, **_kwargs: {"dispatch_count": 1},
    )
    monkeypatch.setattr(
        runner,
        "build_custom_database_delete_calls",
        lambda materialized, created: (
            events.append("build-delete")
            or (
                {"materialized": materialized, "created": dict(created)},
            )
        ),
    )

    def execute_closed_call(direct, call):
        assert direct is _FakeDirect.instances[0]
        assert call == {
            "materialized": sealed_case,
            "created": {"owned": "{CREATED}"},
        }
        events.append("delete-custom-database")
        return {}

    monkeypatch.setattr(runner, "_execute_closed_call", execute_closed_call)
    monkeypatch.setattr(
        runner,
        "_read_user_database_ids",
        lambda direct: (
            events.append("read-final-ids")
            or ("{BASELINE}",)
        ),
    )
    def nonpassing_media_task(**kwargs):
        task = _fake_task(kwargs["task_root"], passed=False)
        task.scenario_id = "VS25-F-MEDIAPOOL-GET-03"
        return task

    monkeypatch.setattr(runner, "run_v3_codex_task", nonpassing_media_task)

    scenario = _scenario(
        runner.MEDIA_POOL_GET_URI,
        scenario_id="VS25-F-MEDIAPOOL-GET-03",
    )
    outcome = runner.run_heavy_project_unit(
        _unit(scenario),
        scenario_root=tmp_path / "case",
        options=_options(tmp_path),
    )

    assert outcome.status == "FAIL"
    assert success_cleanup_calls == []
    assert adapter_holder["adapter"].cleanup_final_ids == ("{BASELINE}",)
    assert outcome.checks["pre_shutdown_cleanup"] == {
        "custom_databases": 1,
        "baseline_restored": True,
    }
    assert events == [
        "build-delete",
        "delete-custom-database",
        "read-final-ids",
        "direct-close",
        "wwise-shutdown",
        "post-shutdown",
    ]


def test_success_runs_pre_shutdown_cleanup_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cleanup_calls: list[str] = []
    _install_orchestration_fakes(
        monkeypatch,
        prepared=_prepared(
            cleanup_before_shutdown=lambda: (
                cleanup_calls.append("cleanup") or {"restored": True}
            )
        ),
    )
    monkeypatch.setattr(
        runner,
        "run_v3_codex_task",
        lambda **kwargs: _fake_task(kwargs["task_root"]),
    )

    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=tmp_path / "case",
        options=_options(tmp_path),
    )

    assert outcome.status == "PASS"
    assert cleanup_calls == ["cleanup"]
    assert outcome.checks["pre_shutdown_cleanup"] == {"restored": True}


def test_pre_shutdown_cleanup_fault_blocks_but_still_closes_and_stops_wwise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    def cleanup():
        events.append("cleanup")
        raise RuntimeError("cannot delete custom database")

    class OrderedDirect(_FakeDirect):
        def close(self):
            events.append("direct-close")
            return super().close()

    class OrderedLifecycle(_FakeLifecycle):
        def finish(self, status, *, reason="", post_shutdown_hook=None):
            events.append("wwise-shutdown")
            return super().finish(
                status,
                reason=reason,
                post_shutdown_hook=post_shutdown_hook,
            )

    prepared = _prepared(
        cleanup_before_shutdown=cleanup,
        post_shutdown=lambda _runtime: events.append("post-shutdown"),
    )
    _FakeLifecycle.instances.clear()
    _FakeDirect.instances.clear()
    monkeypatch.setattr(runner, "ScenarioLifecycle", OrderedLifecycle)
    monkeypatch.setattr(runner, "OwnedDirectWaapiCall", OrderedDirect)
    monkeypatch.setattr(runner, "_prepare_case", lambda *_args, **_kwargs: prepared)
    monkeypatch.setattr(
        runner,
        "_audit_primary_dispatch",
        lambda *_args, **_kwargs: {"dispatch_count": 1},
    )
    monkeypatch.setattr(
        runner,
        "run_v3_codex_task",
        lambda **kwargs: _fake_task(kwargs["task_root"]),
    )

    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=tmp_path / "case",
        options=_options(tmp_path),
    )

    assert outcome.status == "BLOCKED"
    assert "pre-shutdown cleanup failed" in outcome.reason
    assert events == [
        "cleanup",
        "direct-close",
        "wwise-shutdown",
        "post-shutdown",
    ]
    assert _FakeDirect.instances[0].closed
    assert _FakeLifecycle.instances[-1].finished_status == "BLOCKED"


@pytest.mark.parametrize(
    ("archive_turn", "expected"),
    [(False, "BLOCKED"), (True, "FAIL")],
)
def test_task_exception_classification_requires_archived_real_turn_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    archive_turn: bool,
    expected: str,
) -> None:
    _install_orchestration_fakes(monkeypatch, prepared=_prepared())

    def fail(**kwargs):
        _fake_task(kwargs["task_root"], archive_turn=archive_turn)
        raise RuntimeError("task adapter failed")

    monkeypatch.setattr(runner, "run_v3_codex_task", fail)
    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=tmp_path / "case",
        options=_options(tmp_path),
    )
    assert outcome.status == expected
    assert outcome.checks["failure_classification"] == expected
    assert "codex_infrastructure_failure" not in outcome.checks


def test_task_gate_failure_publishes_its_raw_thread_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_orchestration_fakes(monkeypatch, prepared=_prepared())

    def fail(**kwargs):
        _fake_task(kwargs["task_root"], archive_turn=True)
        raise runner.V3TaskRunnerError(
            "synthetic task gate failure",
            thread_id="thread-gate-failure",
        )

    monkeypatch.setattr(runner, "run_v3_codex_task", fail)
    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=tmp_path / "case",
        options=_options(tmp_path),
    )

    assert outcome.status == "FAIL"
    assert outcome.thread_id == "thread-gate-failure"


def test_turn_observer_failure_publishes_its_raw_thread_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_orchestration_fakes(monkeypatch, prepared=_prepared())
    monkeypatch.setattr(
        runner._CaseObservers,
        "after_turn",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            runner.HeavyProjectRunnerError("synthetic natural-response failure")
        ),
    )

    def fail(**kwargs):
        _fake_task(kwargs["task_root"], archive_turn=True)
        kwargs["turn_observer"](
            1,
            SimpleNamespace(thread_id="thread-observer-failure"),
            SimpleNamespace(),
        )
        raise AssertionError("observer failure did not propagate")

    monkeypatch.setattr(runner, "run_v3_codex_task", fail)
    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=tmp_path / "case",
        options=_options(tmp_path),
    )

    assert outcome.status == "FAIL"
    assert outcome.thread_id == "thread-observer-failure"


@pytest.mark.parametrize(
    ("category", "turn_failed", "timed_out"),
    [
        ("quota_or_rate_limit", True, False),
        ("authentication", False, False),
    ],
)
def test_pre_agent_codex_infrastructure_failure_archives_closed_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    category: str,
    turn_failed: bool,
    timed_out: bool,
) -> None:
    _install_orchestration_fakes(monkeypatch, prepared=_prepared())
    failure = CodexInfrastructureFailure(
        category=category,
        message="runner-visible diagnostic that is not part of closed checks",
        turn_failed=turn_failed,
        timed_out=timed_out,
        agent_item_event_count=0,
    )

    def fail(**_kwargs):
        raise CodexInfrastructureError(failure, SimpleNamespace())  # type: ignore[arg-type]

    monkeypatch.setattr(runner, "run_v3_codex_task", fail)
    root = tmp_path / "case"
    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=root,
        options=_options(tmp_path),
    )
    expected = {
        "category": category,
        "turn_failed": turn_failed,
        "timed_out": timed_out,
        "agent_item_event_count": 0,
    }

    assert outcome.status == "BLOCKED"
    assert outcome.checks["codex_infrastructure_failure"] == expected
    assert set(outcome.checks["codex_infrastructure_failure"]) == set(expected)
    persisted = json.loads((root / "outcome.json").read_text(encoding="utf-8"))
    assert persisted["checks"]["codex_infrastructure_failure"] == expected


def test_codex_harness_fault_is_blocked_even_if_a_turn_directory_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_orchestration_fakes(monkeypatch, prepared=_prepared())

    def fail(**kwargs):
        _fake_task(kwargs["task_root"], archive_turn=True)
        raise CodexHarnessError("isolated CLI prerequisite failed")

    monkeypatch.setattr(runner, "run_v3_codex_task", fail)
    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=tmp_path / "case",
        options=_options(tmp_path),
    )
    assert outcome.status == "BLOCKED"
    assert "codex_infrastructure_failure" not in outcome.checks


def test_success_cleanup_fault_is_infrastructure_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def cleanup():
        raise RuntimeError("cannot restore owned objects")

    _install_orchestration_fakes(monkeypatch, prepared=_prepared(cleanup=cleanup))
    monkeypatch.setattr(
        runner,
        "run_v3_codex_task",
        lambda **kwargs: _fake_task(kwargs["task_root"]),
    )
    outcome = runner.run_heavy_project_unit(
        _unit(),
        scenario_root=tmp_path / "case",
        options=_options(tmp_path),
    )
    assert outcome.status == "BLOCKED"
    assert "runtime cleanup failed" in outcome.reason


def test_media_response_classification_does_not_treat_unreferenced_as_referenced() -> None:
    text = "- ambience.wav — unreferenced and safe to remove"
    assert not runner._near_classification(text, "ambience.wav", referenced=True)
    assert runner._near_classification(text, "ambience.wav", referenced=False)
    positive = "- ambience.wav — referenced by two Audio Sources"
    assert runner._near_classification(positive, "ambience.wav", referenced=True)
    assert not runner._near_classification(positive, "ambience.wav", referenced=False)


def test_media_response_classification_uses_section_heading_not_filename_tokens() -> None:
    text = """符合条件的 48 kHz 单声道素材共 4 个；44.1 kHz 立体声同名对照已排除。

仍被 Sound 使用：

- `SemanticLab_UnusedAudit_Dialogue_Used.wav`
  Audio Source：`\\Containers\\Default Work Unit\\SemanticLab\\UnusedAuditRefs\\Dialogue_Used\\SemanticLab_UnusedAudit_Dialogue_Used`
- `SemanticLab_UnusedAudit_Foley_Used.wav`
  Audio Source：`\\Containers\\Default Work Unit\\SemanticLab\\UnusedAuditRefs\\Foley_Used\\SemanticLab_UnusedAudit_Foley_Used`

完全未引用：

- `SemanticLab_UnusedAudit_Alt_Free.wav`
- `SemanticLab_UnusedAudit_Roomtone_Free.wav`

“未引用”两项均已与工程内完整的 709 个 `AudioFileSource` 清单按 `originalFilePath` 关联核对，没有任何 Audio Source 指向它们。
""".casefold()
    for filename in (
        "semanticlab_unusedaudit_dialogue_used.wav",
        "semanticlab_unusedaudit_foley_used.wav",
    ):
        assert runner._near_classification(text, (filename,), referenced=True)
        assert not runner._near_classification(text, (filename,), referenced=False)
    for filename in (
        "semanticlab_unusedaudit_alt_free.wav",
        "semanticlab_unusedaudit_roomtone_free.wav",
    ):
        assert runner._near_classification(text, (filename,), referenced=False)
        assert not runner._near_classification(text, (filename,), referenced=True)


def test_preview_observer_proves_hidden_state_unchanged_and_checks_refusal() -> None:
    snapshots = iter((("before",), ("before",)))
    refusal_calls: list[dict] = []
    preview_calls: list[dict] = []
    prepared = runner._PreparedCase(
        prompt="请检查请求。",
        visible_values={},
        protocol=build_direct_protocol(
            [query_object_step("tx01.preview", ("query-object", "--from", "project", "--take", "1"))]
        ),
        required_reference="references/waapi-operate.md",
        snapshot=lambda: next(snapshots),
        verify_final=lambda _payload, _result: _Verification(),
        verify_preview=lambda payload: preview_calls.append(dict(payload))
        or _Verification(),
        verify_refusal=lambda payload: refusal_calls.append(dict(payload))
        or _Verification(),
    )
    direct = _FakeDirect()
    observer = runner._CaseObservers(
        scenario=_scenario(protocol="preview_confirm"),
        prepared=prepared,
        direct=direct,
        endpoint="127.0.0.1:49152",
        version="2022.1",
        business_oracle_plan_sha256="a" * 64,
    )
    step = prepared.protocol.steps[0]
    observer.before_gateway_step(step, Path(), Path())
    observer.after_gateway_step(step, {"ok": False}, Path(), Path())
    assert preview_calls == [{"ok": False}]
    assert refusal_calls == [{"ok": False}]
    assert observer.checks["tx01.preview.unchanged"] is True
    assert "tx01.preview.business_preview" in observer.checks


def test_preview_observer_rejects_hidden_business_state_drift() -> None:
    snapshots = iter((("before",), ("after",)))
    prepared = runner._PreparedCase(
        prompt="请预览。",
        visible_values={},
        protocol=build_direct_protocol(
            [query_object_step("tx01.preview", ("query-object", "--from", "project", "--take", "1"))]
        ),
        required_reference="references/waapi-operate.md",
        snapshot=lambda: next(snapshots),
        verify_final=lambda _payload, _result: _Verification(),
    )
    observer = runner._CaseObservers(
        scenario=_scenario(protocol="preview_confirm"),
        prepared=prepared,
        direct=_FakeDirect(),
        endpoint="127.0.0.1:49152",
        version="2022.1",
        business_oracle_plan_sha256="a" * 64,
    )
    step = prepared.protocol.steps[0]
    observer.before_gateway_step(step, Path(), Path())
    with pytest.raises(runner.HeavyProjectRunnerError, match="preview changed"):
        observer.after_gateway_step(step, {"ok": True}, Path(), Path())


def test_direct_turn_requires_natural_intro_and_runs_final_business_oracle() -> None:
    prepared = _prepared()
    observer = runner._CaseObservers(
        scenario=_scenario(),
        prepared=prepared,
        direct=_FakeDirect(),
        endpoint="127.0.0.1:49152",
        version="2022.1",
        business_oracle_plan_sha256="a" * 64,
    )
    observer.payloads[prepared.protocol.steps[-1].name] = {"objects": []}
    result = _first_turn_result(
        after_gateway=(
            "已加载 waapi-skill，当前 WAAPI 地址是 127.0.0.1:49152，"
            "适配层版本 2022.1，修改策略 ask_before_changes。"
            "如有需要可切换 read_only / ask_before_changes / allow_changes。",
            "已生成不可变预览，尚未执行任何改动。请确认事务 ID。",
        ),
    )
    observer.after_turn(1, result, SimpleNamespace())
    assert observer.checks["first_use_intro"] is True
    assert observer.checks["final_response_nonempty"] is True
    assert "business_verification" in observer.checks


def test_first_use_intro_rejects_later_agent_message_after_gateway() -> None:
    prepared = _prepared()
    observer = runner._CaseObservers(
        scenario=_scenario(),
        prepared=prepared,
        direct=_FakeDirect(),
        endpoint="127.0.0.1:49152",
        version="2022.1",
        business_oracle_plan_sha256="a" * 64,
    )
    observer.payloads[prepared.protocol.steps[-1].name] = {"objects": []}
    result = _first_turn_result(
        after_gateway=(
            "正在生成不可变预览。",
            "已加载 waapi-skill，当前 WAAPI 地址是 127.0.0.1:49152，"
            "适配层版本 2022.1，修改策略 ask_before_changes。"
            "如有需要可切换 read_only / ask_before_changes / allow_changes。",
        ),
    )

    with pytest.raises(
        runner.HeavyProjectRunnerError,
        match="lacks natural session context fields",
    ):
        observer.after_turn(1, result, SimpleNamespace())


def test_first_use_intro_rejects_skill_name_split_before_gateway() -> None:
    prepared = _prepared()
    observer = runner._CaseObservers(
        scenario=_scenario(),
        prepared=prepared,
        direct=_FakeDirect(),
        endpoint="127.0.0.1:49152",
        version="2022.1",
        business_oracle_plan_sha256="a" * 64,
    )
    observer.payloads[prepared.protocol.steps[-1].name] = {"objects": []}
    result = _first_turn_result(
        before_gateway="我已加载 waapi-skill，接下来会读取当前连接信息。",
        after_gateway=(
            "当前 WAAPI 地址是 127.0.0.1:49152，适配层版本 2022.1，"
            "修改策略 ask_before_changes。如有需要可切换 "
            "read_only / ask_before_changes / allow_changes。",
            "已生成不可变预览，尚未执行任何改动。请确认事务 ID。",
        ),
    )

    with pytest.raises(
        runner.HeavyProjectRunnerError,
        match="lacks natural session context fields: skill",
    ):
        observer.after_turn(1, result, SimpleNamespace())


def _topic_observer(
    main_direct: _FakeDirect,
    *,
    publisher_factory=None,
    publisher_process_target=None,
) -> runner._CaseObservers:
    step_name = "soundbank.generated.wait"
    requirement = {
        "contract": runner.TOPIC_ACK_REQUIREMENT_CONTRACT,
        "ack_contract": runner.SUBSCRIPTION_ACK_CONTRACT,
        "step_name": step_name,
        "topic": runner.SOUNDBANK_TOPIC,
        "fresh_exclusive_path_required": True,
        "publisher_requires_valid_ack": True,
    }
    typed_sections = runner.SoundBankBusinessPlanSections(
        fixture_spec=MappingProxyType({}),
        payload_bindings=MappingProxyType({}),
        assertion_ids=(),
        static_expectation=MappingProxyType({}),
        live_binding=MappingProxyType(
            {"topic": MappingProxyType({"subscription_ack_requirement": requirement})}
        ),
        delta_rules=(),
    )
    prepared = runner._PreparedCase(
        prompt="监听下一次 SoundBank 生成。",
        visible_values={},
        protocol=build_direct_protocol(
            [
                wait_topic_step(
                    step_name,
                    runner.SOUNDBANK_TOPIC,
                    version="2022.1",
                    event_count=1,
                )
            ]
        ),
        required_reference="references/waapi-query.md",
        snapshot=lambda: ("sealed",),
        verify_final=lambda _payload, _result: _Verification(),
        typed_sections=typed_sections,
        topic_publishers=({"closed": "request"},),
        topic_payload_step=step_name,
    )
    return runner._CaseObservers(
        scenario=_scenario(
            runner.SOUNDBANK_TOPIC,
            scenario_id="O22-SB-GENERATED-05",
            item_type="topic",
        ),
        prepared=prepared,
        direct=main_direct,
        endpoint="127.0.0.1:49152",
        version="2022.1",
        business_oracle_plan_sha256="a" * 64,
        publisher_client_factory=publisher_factory,
        publisher_process_target=publisher_process_target,
    )


def _topic_ack_expectation(tmp_path: Path):
    evidence = tmp_path / "broker" / "evidence"
    evidence.mkdir(parents=True)
    return runner.TrustedSubscriptionAckExpectation(
        contract=runner.SUBSCRIPTION_ACK_CONTRACT,
        step_name="soundbank.generated.wait",
        topic=runner.SOUNDBANK_TOPIC,
        path=evidence / "subscription-ack-test.json",
        nonce_sha256=hashlib.sha256(("n" * 43).encode("utf-8")).hexdigest(),
    )


def _write_topic_ack(expectation, *, nonce: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract": expectation.contract,
        "step_name": expectation.step_name,
        "topic": expectation.topic,
        "nonce": "n" * 43 if nonce is None else nonce,
        "runner_parent_process_id": 123,
        "gateway_process_id": 124,
        "subscribed_at_unix_ns": 1,
        "subscribed_at_monotonic_ns": runner.time.monotonic_ns(),
    }
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    temporary = expectation.path.with_name(f".{expectation.path.name}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, expectation.path, follow_symlinks=False)
    temporary.unlink()
    return payload


def test_topic_publisher_uses_client_created_called_and_closed_in_publisher_thread(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _FakeDirect.instances.clear()
    main = _FakeDirect()
    factory_threads: list[int] = []

    def factory():
        factory_threads.append(threading.get_ident())
        return _FakeDirect()

    monkeypatch.setattr(
        runner,
        "parse_operation_request",
        lambda value, *, expected_version: SimpleNamespace(value=value),
    )
    monkeypatch.setattr(
        runner,
        "prepare_operation",
        lambda _request, *, read_call: SimpleNamespace(
            semantic_preview=SimpleNamespace(
                envelope=SimpleNamespace(uri="ak.test.publish", args={}, options={})
            )
        ),
    )
    observer = _topic_observer(main, publisher_factory=factory)
    expectation = _topic_ack_expectation(tmp_path)

    observer.before_subscription_wait(expectation)
    ack_payload = _write_topic_ack(expectation)
    observer.topic_payload = {"events": []}
    observer.finish()

    peer = _FakeDirect.instances[-1]
    assert factory_threads and factory_threads[0] != threading.get_ident()
    assert peer.created_thread == factory_threads[0]
    assert len(peer.calls) == 1
    assert peer.closed
    assert main.calls == []
    assert not main.closed
    assert observer.checks["topic_publisher_client_opened"] is True
    assert observer.checks["topic_publisher_client_closed"] is True
    diagnostics = observer.checks["topic_publisher_diagnostics"]
    assert diagnostics["contract"] == "waapi-skill.topic-publisher-diagnostics/v1"
    assert diagnostics["diagnostic_only"] is True
    assert diagnostics["abort_requested"] is False
    assert diagnostics["ack"]["observed"] is True
    assert "nonce" not in diagnostics["ack"]["payload"]
    assert diagnostics["ack"]["nonce_sha256"] == expectation.nonce_sha256
    assert diagnostics["result_count"] == 1
    assert diagnostics["publisher_call_evidence"][0]["status"] == "succeeded"
    assert diagnostics["publisher_call_evidence"][0]["result"]["included"] is True
    assert diagnostics["publisher_call_evidence"][0]["result"]["value"] == {
        "ok": True
    }
    assert diagnostics["error"] is None
    proof = observer.checks["topic_subscription_ack"]
    assert proof["ack_payload"] == ack_payload
    assert proof["ack_before_publish"] is True
    assert (
        ack_payload["subscribed_at_monotonic_ns"]
        <= proof["ack_observed_at_monotonic_ns"]
        <= proof["publisher_started_at_monotonic_ns"]
        <= min(proof["publisher_call_started_at_monotonic_ns"])
    )


def test_topic_gateway_observer_returns_before_publisher_and_verifies_in_finish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    call_started = threading.Event()
    release_call = threading.Event()

    class BlockingPeer(_FakeDirect):
        def __call__(self, uri, args, options):
            call_started.set()
            assert release_call.wait(2.0)
            return super().__call__(uri, args, options)

    peer = BlockingPeer()
    monkeypatch.setattr(
        runner,
        "parse_operation_request",
        lambda value, *, expected_version: SimpleNamespace(value=value),
    )
    monkeypatch.setattr(
        runner,
        "prepare_operation",
        lambda _request, *, read_call: SimpleNamespace(
            semantic_preview=SimpleNamespace(
                envelope=SimpleNamespace(uri="ak.test.publish", args={}, options={})
            )
        ),
    )
    observer = _topic_observer(
        _FakeDirect(),
        publisher_factory=lambda: peer,
    )
    expectation = _topic_ack_expectation(tmp_path)
    observer.before_subscription_wait(expectation)
    _write_topic_ack(expectation)
    assert call_started.wait(1.0)

    step = observer.prepared.protocol.steps[0]
    started = time.monotonic()
    observer.after_gateway_step(step, {"events": [{}]}, Path(), Path())
    assert time.monotonic() - started < 0.25
    assert "topic_verification" not in observer.checks

    release_call.set()
    observer.finish()
    assert "topic_verification" in observer.checks
    assert peer.closed is True


def test_production_topic_publisher_uses_spawn_and_reaps_child(
    tmp_path: Path,
) -> None:
    observer = _topic_observer(
        _FakeDirect(),
        publisher_process_target=_successful_spawn_topic_publisher,
    )
    expectation = _topic_ack_expectation(tmp_path)
    observer.before_subscription_wait(expectation)
    _write_topic_ack(expectation)
    observer.topic_payload = {"events": []}
    observer.finish()

    diagnostics = observer.checks["topic_publisher_diagnostics"]
    child = diagnostics["child_process"]
    assert diagnostics["execution_mode"] == "spawn_process"
    assert child["start_method"] == "spawn"
    assert child["coordinator_process_id"] == os.getpid()
    assert child["pid"] != os.getpid()
    assert child["parent_pid"] == os.getpid()
    assert child["exit_code"] == 0
    assert child["reaped"] is True
    assert child["terminate_requested"] is False
    assert child["kill_requested"] is False
    assert child["canonical_result_received"] is True
    assert diagnostics["client_opened"] is True
    assert diagnostics["client_closed"] is True
    assert observer.checks["topic_publisher_call_count"] == 1


def test_topic_publisher_child_owns_exactly_one_client_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[object] = []

    class ChildDirect(_FakeDirect):
        def __init__(self, *, host, port) -> None:
            super().__init__(host=host, port=port)
            instances.append(self)

        def close(self):
            super().close()
            return True

    class CaptureConnection:
        def __init__(self) -> None:
            self.raw = b""
            self.closed = False

        def send_bytes(self, value):
            self.raw = bytes(value)

        def close(self):
            self.closed = True

    monkeypatch.setattr(runner, "OwnedDirectWaapiCall", ChildDirect)
    monkeypatch.setattr(
        runner,
        "parse_operation_request",
        lambda value, *, expected_version: SimpleNamespace(value=value),
    )
    monkeypatch.setattr(
        runner,
        "prepare_operation",
        lambda _request, *, read_call: SimpleNamespace(
            semantic_preview=SimpleNamespace(
                envelope=SimpleNamespace(uri="ak.test.publish", args={}, options={})
            )
        ),
    )
    connection = CaptureConnection()

    runner._topic_publisher_process_main(
        "127.0.0.1",
        49152,
        "2022.1",
        ({"closed": "request"},),
        connection,
    )

    assert len(instances) == 1
    direct = instances[0]
    assert isinstance(direct, ChildDirect)
    assert len(direct.calls) == 1
    assert direct.closed is True
    assert connection.closed is True
    payload = json.loads(connection.raw.decode("utf-8"))
    assert payload["contract"] == runner._TOPIC_CHILD_RESULT_CONTRACT
    assert payload["client_opened"] is True
    assert payload["client_closed"] is True
    assert payload["direct_call_count"] == 1
    assert payload["result_count"] == 1
    assert payload["error"] is None


def test_spawned_topic_publisher_timeout_terminates_and_reaps_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runner, "_TOPIC_PROCESS_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(runner, "_TOPIC_PROCESS_TERMINATE_SECONDS", 0.5)
    monkeypatch.setattr(runner, "_TOPIC_PROCESS_KILL_SECONDS", 0.5)
    monkeypatch.setattr(runner, "_TOPIC_JOIN_SECONDS", 2.0)
    observer = _topic_observer(
        _FakeDirect(),
        publisher_process_target=_hanging_spawn_topic_publisher,
    )
    expectation = _topic_ack_expectation(tmp_path)
    observer.before_subscription_wait(expectation)
    _write_topic_ack(expectation)

    with pytest.raises(
        runner._HeavyProjectInfrastructureError,
        match="publisher failed",
    ):
        observer.finish()

    diagnostics = observer.checks["topic_publisher_diagnostics"]
    child = diagnostics["child_process"]
    assert child["pid"] != os.getpid()
    assert child["terminate_requested"] is True
    assert child["reaped"] is True
    assert child["exit_code"] != 0
    assert child["canonical_result_received"] is False
    assert diagnostics["client_closed"] is False


def test_oversized_topic_child_ipc_still_terminates_and_reaps_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runner, "_TOPIC_PROCESS_WAIT_SECONDS", 1.0)
    monkeypatch.setattr(runner, "_TOPIC_PROCESS_TERMINATE_SECONDS", 0.5)
    monkeypatch.setattr(runner, "_TOPIC_PROCESS_KILL_SECONDS", 0.5)
    monkeypatch.setattr(runner, "_TOPIC_JOIN_SECONDS", 3.0)
    observer = _topic_observer(
        _FakeDirect(),
        publisher_process_target=_oversized_spawn_topic_publisher,
    )
    expectation = _topic_ack_expectation(tmp_path)
    observer.before_subscription_wait(expectation)
    _write_topic_ack(expectation)

    with pytest.raises(
        runner._HeavyProjectInfrastructureError,
        match="publisher failed",
    ):
        observer.finish()

    child = observer.checks["topic_publisher_diagnostics"]["child_process"]
    assert child["terminate_requested"] is True
    assert child["reaped"] is True
    assert child["exit_code"] != 0


def test_topic_finish_fails_when_gateway_payload_was_never_observed() -> None:
    observer = _topic_observer(
        _FakeDirect(),
        publisher_factory=lambda: _FakeDirect(),
    )
    with pytest.raises(
        runner._HeavyProjectInfrastructureError,
        match="without a payload",
    ):
        observer.finish()


def test_topic_publisher_retries_transitional_two_link_ack_then_requires_one_link(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    opened: list[bool] = []
    monkeypatch.setattr(
        runner,
        "parse_operation_request",
        lambda value, *, expected_version: SimpleNamespace(value=value),
    )
    monkeypatch.setattr(
        runner,
        "prepare_operation",
        lambda _request, *, read_call: SimpleNamespace(
            semantic_preview=SimpleNamespace(
                envelope=SimpleNamespace(uri="ak.test.publish", args={}, options={})
            )
        ),
    )
    expectation = _topic_ack_expectation(tmp_path)
    saw_two_links = threading.Event()
    original_lstat = Path.lstat

    def observing_lstat(path: Path, *args, **kwargs):
        metadata = original_lstat(path, *args, **kwargs)
        if path == expectation.path and metadata.st_nlink == 2:
            saw_two_links.set()
        return metadata

    monkeypatch.setattr(Path, "lstat", observing_lstat)
    observer = _topic_observer(
        _FakeDirect(),
        publisher_factory=lambda: opened.append(True) or _FakeDirect(),
    )
    observer.before_subscription_wait(expectation)
    payload = {
        "contract": expectation.contract,
        "step_name": expectation.step_name,
        "topic": expectation.topic,
        "nonce": "n" * 43,
        "runner_parent_process_id": 123,
        "gateway_process_id": 124,
        "subscribed_at_unix_ns": 1,
        "subscribed_at_monotonic_ns": runner.time.monotonic_ns(),
    }
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    temporary = expectation.path.with_name(f".{expectation.path.name}.held.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, expectation.path, follow_symlinks=False)

    assert saw_two_links.wait(1.0)
    assert opened == []
    temporary.unlink()
    observer.topic_payload = {"events": []}
    observer.finish()

    assert opened == [True]
    assert expectation.path.stat().st_nlink == 1
    assert observer.checks["topic_subscription_ack"]["ack_before_publish"] is True


def test_topic_abort_wakes_ack_wait_without_opening_a_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    main = _FakeDirect()
    opened: list[bool] = []
    observer = _topic_observer(
        main,
        publisher_factory=lambda: opened.append(True) or _FakeDirect(),
    )
    observer.before_subscription_wait(_topic_ack_expectation(tmp_path))
    observer.abort()
    assert opened == []
    assert observer.checks["topic_publisher_client_opened"] is False
    diagnostics = observer.checks["topic_publisher_diagnostics"]
    assert diagnostics["abort_requested"] is True
    assert diagnostics["ack"]["observed"] is False
    assert diagnostics["result_count"] == 0
    assert diagnostics["publisher_call_evidence"] == ()


def test_topic_abort_after_ack_does_not_launch_publisher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    opened: list[bool] = []
    observer = _topic_observer(
        _FakeDirect(),
        publisher_factory=lambda: opened.append(True) or _FakeDirect(),
    )

    def acknowledge_then_abort():
        observer._publisher_abort.set()
        return {"contract": runner.SUBSCRIPTION_ACK_CONTRACT}

    monkeypatch.setattr(observer, "_wait_for_subscription_ack", acknowledge_then_abort)
    observer.before_subscription_wait(_topic_ack_expectation(tmp_path))
    observer.abort()

    assert opened == []
    diagnostics = observer.checks["topic_publisher_diagnostics"]
    assert diagnostics["publisher_started_at_monotonic_ns"] is None
    assert diagnostics["client_opened"] is False


def test_topic_publisher_failure_still_closes_peer_and_is_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FailingPeer(_FakeDirect):
        def __call__(self, uri, args, options):
            self.calls.append({"uri": uri})
            raise RuntimeError("publisher call failed")

    main = _FakeDirect()
    peer = FailingPeer()
    monkeypatch.setattr(
        runner,
        "parse_operation_request",
        lambda value, *, expected_version: SimpleNamespace(value=value),
    )
    monkeypatch.setattr(
        runner,
        "prepare_operation",
        lambda _request, *, read_call: SimpleNamespace(
            semantic_preview=SimpleNamespace(
                envelope=SimpleNamespace(uri="ak.test.publish", args={}, options={})
            )
        ),
    )
    observer = _topic_observer(main, publisher_factory=lambda: peer)
    expectation = _topic_ack_expectation(tmp_path)
    observer.before_subscription_wait(expectation)
    _write_topic_ack(expectation)
    with pytest.raises(runner._HeavyProjectInfrastructureError, match="publisher failed"):
        observer.finish()
    assert peer.closed
    assert not main.closed
    diagnostics = observer.checks["topic_publisher_diagnostics"]
    assert diagnostics["abort_requested"] is False
    assert diagnostics["client_closed"] is True
    assert diagnostics["publisher_call_evidence"][0]["status"] == "failed"
    assert "RuntimeError: publisher call failed" in diagnostics["error"]


def test_topic_publisher_rejects_forged_ack_without_opening_peer(
    tmp_path: Path,
) -> None:
    main = _FakeDirect()
    opened: list[bool] = []
    observer = _topic_observer(
        main,
        publisher_factory=lambda: opened.append(True) or _FakeDirect(),
    )
    expectation = _topic_ack_expectation(tmp_path)
    observer.before_subscription_wait(expectation)
    _write_topic_ack(expectation, nonce="f" * 43)

    with pytest.raises(
        runner._HeavyProjectInfrastructureError,
        match="publisher failed",
    ):
        observer.finish()

    assert opened == []


def test_topic_publisher_missing_ack_times_out_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runner, "_TOPIC_ACK_WAIT_SECONDS", 0.01)
    observer = _topic_observer(_FakeDirect())
    observer.before_subscription_wait(_topic_ack_expectation(tmp_path))

    with pytest.raises(
        runner._HeavyProjectInfrastructureError,
        match="publisher failed",
    ):
        observer.finish()


def test_custom_media_prelaunch_proves_fresh_runner_owned_user_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(real_home))
    real_appdata = real_home / "AppData" / "Roaming"
    real_appdata.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(real_appdata))
    calls: list[str] = []
    monkeypatch.setattr(
        runner,
        "make_project_prelaunch_hook",
        lambda _request: lambda *_args: calls.append("normalize"),
    )
    monkeypatch.setattr(
        runner,
        "materialize_media_pool_case",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        runner,
        "stage_media_pool_case",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    sandbox_path = tmp_path / "copy"
    sandbox_path.mkdir()
    sandbox = SimpleNamespace(
        sandbox_path=sandbox_path,
        sandbox_project=sandbox_path / "SampleProject.wproj",
        source_root=tmp_path / "source",
    )
    scenario = _scenario(
        runner.MEDIA_POOL_GET_URI,
        scenario_id="VS25-F-MEDIAPOOL-GET-02",
        fixture={
            "asset_spec": {
                "databases": [{"path": r"\Databases\Custom Review"}]
            }
        },
    )
    holder: dict = {}
    hook = runner._prelaunch_hook(scenario, media_holder=holder)
    assert hook is not None
    asset_root = tmp_path / "owned" / "assets"
    io_root = tmp_path / "owned" / "io"
    asset_root.mkdir(parents=True)
    io_root.mkdir()
    owned = tmp_path / "owned"
    if os.name == "nt":
        native_roots = runner._native_windows_launch_roots(owned)
        for path in native_roots.values():
            path.mkdir()
    else:
        launch_home = owned / "wwise-user-home"
        launch_home.mkdir()

    hook(sandbox, asset_root, io_root)

    if os.name == "nt":
        assert holder["host_mode"] == "native_windows"
        assert holder["native_windows_roots"] == native_roots
        assert holder["global_user_state_before"].root.is_relative_to(
            real_appdata
        )
    else:
        expected_prefix = runner.expected_macos_wine_prefix(launch_home.resolve())
        assert not expected_prefix.exists()
        assert holder["host_mode"] == "macos_wine"
        assert holder["launch_home"] == launch_home.resolve()
        assert holder["owned_wine_prefix_expected"] == expected_prefix
        assert holder["global_user_state_before"].root.is_relative_to(real_home)
    assert calls == ["normalize"]


def test_custom_media_prelaunch_rejects_nonempty_private_user_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(real_home))
    real_appdata = real_home / "AppData" / "Roaming"
    real_appdata.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(real_appdata))
    monkeypatch.setattr(
        runner,
        "make_project_prelaunch_hook",
        lambda _request: lambda *_args: None,
    )
    sandbox_path = tmp_path / "copy"
    sandbox_path.mkdir()
    sandbox = SimpleNamespace(
        sandbox_path=sandbox_path,
        sandbox_project=sandbox_path / "SampleProject.wproj",
        source_root=tmp_path / "source",
    )
    scenario = _scenario(
        runner.MEDIA_POOL_GET_URI,
        scenario_id="VS25-F-MEDIAPOOL-GET-02",
        fixture={"asset_spec": {"databases": [{"path": "custom"}]}},
    )
    hook = runner._prelaunch_hook(scenario, media_holder={})
    owned = tmp_path / "owned"
    assets = owned / "assets"
    io = owned / "io"
    assets.mkdir(parents=True)
    io.mkdir()
    if os.name == "nt":
        native_roots = runner._native_windows_launch_roots(owned)
        for path in native_roots.values():
            path.mkdir()
        dirty_root = native_roots["APPDATA"]
    else:
        dirty_root = owned / "wwise-user-home"
        dirty_root.mkdir()
    (dirty_root / "unexpected-state").write_text("not fresh", encoding="utf-8")
    with pytest.raises(runner.HeavyProjectRunnerError, match="not empty"):
        hook(sandbox, assets, io)


def test_native_windows_private_user_state_proof_is_case_owned_and_fresh(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "case" / "owned"
    owned.mkdir(parents=True)
    roots = runner._native_windows_launch_roots(owned)
    for path in roots.values():
        path.mkdir()

    proven = runner._prove_fresh_native_windows_user_state(
        roots,
        owned_root=owned,
    )

    assert proven == roots
    (roots["APPDATA"] / "unexpected-state").write_text(
        "dirty",
        encoding="utf-8",
    )
    with pytest.raises(runner.HeavyProjectRunnerError, match="not empty"):
        runner._prove_fresh_native_windows_user_state(
            roots,
            owned_root=owned,
        )


def test_custom_database_host_selection_is_runner_owned(
    tmp_path: Path,
) -> None:
    scenario = _scenario(
        runner.MEDIA_POOL_GET_URI,
        scenario_id="VS25-F-MEDIAPOOL-GET-02",
        fixture={
            "asset_spec": {"databases": [{"path": "custom"}]},
            "host_mode": "caller-authored-value-is-ignored",
        },
    )

    overrides = runner._launch_environment_overrides(
        scenario,
        scenario_root=tmp_path / "case",
    )

    assert set(overrides) == (
        {"USERPROFILE", "APPDATA", "LOCALAPPDATA"}
        if os.name == "nt"
        else {"HOME"}
    )


def test_media_final_response_accepts_live_filename_or_full_path_basename(
    tmp_path: Path,
) -> None:
    from tests.semantic.test_codex_audio_media_business_plan_v3 import _media_case

    root = tmp_path / "media"
    root.mkdir()
    _case, staged, oracle = _media_case(1, root)
    live_filename = oracle.row("asset").values["Filename"]
    full_filename = staged.staged_asset("asset").indexed_host_path.name

    assert runner._media_final_response_failures(
        oracle,
        staged,
        f"all\n{live_filename}",
    ) == ()
    assert runner._media_final_response_failures(
        oracle,
        staged,
        f"all\n{full_filename}",
    ) == ()


def test_media_observer_accepts_only_closed_compact_reference_match_result(
    tmp_path: Path,
) -> None:
    from tests.semantic.support.codex_audio_media_business_plan_v3 import (
        _expected_media_protocol,
    )
    from tests.semantic.support.codex_media_pool_runtime_v3 import (
        REFERENCE_MATCH_RESULT_CONTRACT,
    )
    from tests.semantic.test_codex_audio_media_business_plan_v3 import _media_case

    root = tmp_path / "media-observer"
    root.mkdir()
    case, staged, oracle = _media_case(4, root, associations=True)
    protocol = _expected_media_protocol(case, oracle)
    adapter = runner._PreparedMediaPoolAdapter(
        scenario=SimpleNamespace(id=case.scenario_id),
        runtime=SimpleNamespace(),
        direct=SimpleNamespace(),
        staged=staged,
        preflight=SimpleNamespace(),
        oracle=oracle,
        fields=(),
        protocol=protocol,
        reference_baseline={"return": []},
        project_digest="a" * 64,
        custom_baseline_ids=(),
        custom_created_ids=MappingProxyType({}),
        waapi_y_drive_root=None,
    )
    compact_result = {
        "contract": REFERENCE_MATCH_RESULT_CONTRACT,
        "scanned_audio_source_count": 1,
        "scan_limit": 1000,
        "scan_complete": True,
        "candidates": [
            {
                "originalFilePath": oracle.row("asset").path,
                "classification": "referenced",
                "reference_count": 1,
                "references": [
                    {
                        "id": "{00000000-0000-0000-0000-000000000001}",
                        "path": r"object\AudioFileSource",
                    }
                ],
                "references_truncated": False,
            }
        ],
    }
    step = protocol.steps[-1]
    adapter.observe_payload(step, {"agent_result": compact_result})
    assert adapter.model_reference_result == compact_result

    with pytest.raises(
        runner.HeavyProjectRunnerError,
        match="exact agent_result",
    ):
        adapter.observe_payload(step, {"objects": []})

    tampered = json.loads(json.dumps(compact_result))
    tampered["scan_complete"] = False
    with pytest.raises(
        runner.HeavyProjectRunnerError,
        match="compact Audio Source association query",
    ):
        adapter.observe_payload(step, {"agent_result": tampered})


def test_media_verifier_restores_only_exact_reconciled_gateway_reads() -> None:
    adapter = object.__new__(runner._PreparedMediaPoolAdapter)
    adapter.protocol = SimpleNamespace(
        steps=(
            ExpectedGatewayStep("media.get-fields", "typed-zero-call"),
            ExpectedGatewayStep("media.get", "core-call"),
        )
    )
    observed: list[tuple[str, object]] = []
    adapter.observe_payload = lambda step, payload: observed.append(
        (step.name, payload["agent_result"])
    )
    get_fields = {
        "command": "typed-zero-call",
        "api_attempted": runner.MEDIA_POOL_GET_FIELDS_URI,
        "ok": True,
        "status": "ok",
        "agent_result": {"return": ["Filename"]},
    }
    media_get = {
        "command": "core-call",
        "api_attempted": runner.MEDIA_POOL_GET_URI,
        "ok": True,
        "status": "ok",
        "agent_result": {"return": []},
    }

    adapter._restore_model_reads_from_gateway_results(
        SimpleNamespace(
            command_facts=SimpleNamespace(
                gateway_results=(get_fields, {"command": "draft-start"}, media_get)
            )
        )
    )

    assert observed == [
        ("media.get-fields", get_fields["agent_result"]),
        ("media.get", media_get["agent_result"]),
    ]
    with pytest.raises(
        runner.HeavyProjectRunnerError,
        match="exactly one reconciled media.get gateway result",
    ):
        adapter._restore_model_reads_from_gateway_results(
            SimpleNamespace(
                command_facts=SimpleNamespace(
                    gateway_results=(get_fields, media_get, dict(media_get))
                )
            )
        )


def test_media_observer_records_the_sealed_media_get_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = object.__new__(runner._PreparedMediaPoolAdapter)
    adapter.oracle = object()
    adapter.staged = object()
    adapter.model_media_result = None
    monkeypatch.setattr(
        runner,
        "verify_media_pool_result",
        lambda _oracle, _raw: _Verification(),
    )
    monkeypatch.setattr(
        runner,
        "verify_media_pool_read_unchanged",
        lambda _staged, _oracle: _Verification(),
    )
    result = {"return": [{"id": "media-row"}]}

    adapter.observe_payload(
        ExpectedGatewayStep("media.get", "core-call"),
        {"agent_result": result},
    )

    assert adapter.model_media_result == result


def test_custom_database_roundtrip_uses_plain_json_and_runner_owned_host_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "waapi-skill"
        / "evals"
        / "suite-v3.json"
    )
    scenario = load_eval_bundle_v3(suite).scenario("VS25-F-MEDIAPOOL-GET-03")
    owned = (tmp_path / "owned").resolve()
    case = runner.materialize_media_pool_case(
        scenario,
        asset_root=owned / "assets" / "media-pool-case",
    )
    real_home = tmp_path / "real-home"
    if os.name == "nt":
        native_roots = runner._native_windows_launch_roots(owned)
        for path in native_roots.values():
            path.mkdir()
        runner_environment = {
            key: str(path) for key, path in native_roots.items()
        }
        metadata_prefix = None
        global_state = (
            real_home / "AppData" / "Roaming" / "Audiokinetic" / "Wwise"
        )
    else:
        launch_home = owned / "wwise-user-home"
        launch_home.mkdir()
        wine_prefix = runner.expected_macos_wine_prefix(launch_home)
        dosdevices = wine_prefix / "dosdevices"
        dosdevices.mkdir(parents=True)
        (wine_prefix / "drive_c").mkdir()
        create_symlink_or_skip(
            dosdevices / "z:",
            WINE_Z_DRIVE_TARGET,
            target_is_directory=True,
        )
        create_symlink_or_skip(
            dosdevices / "c:",
            WINE_C_DRIVE_TARGET,
            target_is_directory=True,
        )
        create_symlink_or_skip(
            dosdevices / "y:",
            launch_home,
            target_is_directory=True,
        )
        runner_environment = {
            "HOME": str(launch_home),
            "WINEPREFIX": str(wine_prefix),
        }
        metadata_prefix = str(wine_prefix)
        global_state = (
            real_home
            / "Library"
            / "Application Support"
            / "Audiokinetic"
            / "Wwise"
        )
    global_state.mkdir(parents=True)
    (global_state / "baseline.json").write_text("{}\n", encoding="utf-8")
    global_before = runner.fingerprint_tree(global_state)
    created_guid = "{11111111-2222-3333-4444-555555555555}"
    created_path_guid = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"
    current_ids: list[str] = []
    set_requests: list[dict] = []

    class FakeRequestFailed(Exception):
        pass

    class FakeWaapiClient:
        def __init__(self, **_kwargs) -> None:
            self._client_thread = SimpleNamespace(
                daemon=threading.current_thread().daemon
            )

        def call(self, uri, args, *, options):
            json.dumps({"args": args, "options": options}, allow_nan=False)
            if uri == "ak.wwise.core.object.get":
                return {
                    "return": [
                        {"id": object_id, "name": "case database"}
                        for object_id in current_ids
                    ]
                }
            if uri == "ak.wwise.core.object.set":
                set_requests.append(args)
                child = args["objects"][0]["children"][0]
                current_ids.append(created_guid)
                return {
                    "objects": [
                        {
                                "id": "{8452BD49-9264-4A56-A3BB-047FA7F119BE}",
                            "children": [
                                {
                                    "id": created_guid,
                                    "name": child["name"],
                                    "@Paths": [
                                        {"id": created_path_guid, "name": ""}
                                    ],
                                }
                            ],
                        }
                    ]
                }
            if uri == "ak.wwise.core.object.delete":
                assert args == {"object": created_guid}
                current_ids.remove(created_guid)
                return {}
            raise AssertionError(f"unexpected URI {uri}")

        def disconnect(self):
            return True

    monkeypatch.setitem(
        sys.modules,
        "waapi",
        SimpleNamespace(
            WaapiClient=FakeWaapiClient,
            WaapiRequestFailed=FakeRequestFailed,
        ),
    )
    direct = runner.OwnedDirectWaapiCall(host="127.0.0.1", port=49152)
    runtime = SimpleNamespace(
        lifecycle=SimpleNamespace(
            ready_result={
                "version": {"year": 2025, "major": 1, "minor": 7, "build": 9143}
            }
        ),
        runner_environment=runner_environment,
        owned_root=owned,
        sandbox=SimpleNamespace(
            metadata=SimpleNamespace(wine_prefix_path=metadata_prefix)
        ),
    )

    isolation, baseline_ids = runner._establish_custom_database_roundtrip(
        case,
        runtime=runtime,
        direct=direct,
        real_account_state_root=global_state,
        global_before=global_before,
    )

    assert baseline_ids == ()
    assert current_ids == []
    if os.name == "nt":
        assert isinstance(isolation.host, runner.NativeWindowsCustomDatabaseHost)
    else:
        assert isinstance(isolation.host, runner.MacOSWineCustomDatabaseHost)
        assert isolation.host.wine_prefix == wine_prefix
    assert len(set_requests) == 1
    sent_path = set_requests[0]["objects"][0]["children"][0]["@Paths"][0][
        "@Path"
    ]
    if os.name == "nt":
        assert sent_path == str(
            case.database("semanticlab_editorial").source_root.resolve(strict=True)
        )
    else:
        assert sent_path.startswith("Z:\\")
        assert str(case.database("semanticlab_editorial").source_root) not in sent_path
    assert type(set_requests[0]) is dict
    assert type(set_requests[0]["objects"]) is list
    assert type(set_requests[0]["objects"][0]["children"][0]) is dict
    assert direct.close(wait_seconds=1.0) is True


class _FakeLock:
    def __init__(self, _root: Path) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def _project_hash() -> ProjectHash:
    return ProjectHash(
        algorithm="sha256",
        strategy="full",
        digest="a" * 64,
        file_count=1,
        bytes_hashed=4,
    )


def test_lifecycle_start_shutdown_failure_is_sealed_and_marks_campaign_unsafe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_project = source_root / "SampleProject.wproj"
    source_project.write_text("source", encoding="utf-8")
    fixed_hash = _project_hash()

    def prepare(_env, *, sandbox_root: Path, hash_strategy: str):
        copy = sandbox_root / "copy"
        copy.mkdir(parents=True)
        project = copy / "SampleProject.wproj"
        project.write_text("copy", encoding="utf-8")
        metadata = SandboxMetadata(
            source_path=str(source_project),
            source_root=str(source_root),
            sandbox_path=str(copy),
            sandbox_project_path=str(project),
            wwise_version="2022.1",
            copy_duration_seconds=0.0,
            source_hash=fixed_hash,
            sandbox_hash=fixed_hash,
            source_mtime_before=source_project.stat().st_mtime,
        )
        return SandboxProject(
            source_project=source_project,
            source_root=source_root,
            sandbox_root=sandbox_root,
            sandbox_path=copy,
            sandbox_project=project,
            metadata=metadata,
        )

    monkeypatch.setattr(lifecycle_v3, "LiveSandboxLock", _FakeLock)
    monkeypatch.setattr(
        lifecycle_v3,
        "require_live_environment",
        lambda _env: SimpleNamespace(
            version="2022.1", sample_project_source=source_project
        ),
    )
    monkeypatch.setattr(lifecycle_v3, "prepare_sample_project_sandbox", prepare)
    monkeypatch.setattr(
        lifecycle_v3,
        "hash_project",
        lambda *_args, **_kwargs: fixed_hash,
    )
    monkeypatch.setattr(
        lifecycle_v3,
        "launch_sandboxed_wwise",
        lambda sandbox, _env: SimpleNamespace(
            host="127.0.0.1",
            port=49152,
            command=("WwiseConsole", str(sandbox.sandbox_project)),
        ),
    )
    monkeypatch.setattr(
        lifecycle_v3,
        "shutdown_sandboxed_wwise",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("residual process")
        ),
    )
    controller = lifecycle_v3.ScenarioLifecycle(
        scenario_id="OBJ22-F-GET-01",
        version="2022.1",
        scenario_root=tmp_path / "case",
        live_environment={"WWISE_TEST_CONFIG": "unused"},
        # Force a post-launch identity failure so start owns teardown.
        prelaunch_hook=lambda *_args: None,
        lock_root=tmp_path / "lock",
    )
    original_launch = lifecycle_v3.launch_sandboxed_wwise

    def launch_without_port(sandbox, env):
        value = original_launch(sandbox, env)
        value.port = None
        return value

    monkeypatch.setattr(lifecycle_v3, "launch_sandboxed_wwise", launch_without_port)

    with pytest.raises(lifecycle_v3.ScenarioLifecycleStartError) as caught:
        controller.start()

    assert caught.value.unsafe_to_continue
    assert any(
        error.startswith("wwise-start-cleanup:")
        for error in caught.value.errors
    )
    evidence = json.loads(caught.value.evidence_path.read_text(encoding="utf-8"))
    assert evidence["wwise_stop_status"] == "unproven"
    assert evidence["never_reuse"] is True
    assert evidence["source_hash_before"] == evidence["source_hash_after"]


def test_early_custom_media_start_failure_archives_real_account_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(real_home))
    real_appdata = real_home / "AppData" / "Roaming"
    real_appdata.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(real_appdata))
    scenario = _scenario(
        runner.MEDIA_POOL_GET_URI,
        scenario_id="VS25-F-MEDIAPOOL-GET-02",
        fixture={"asset_spec": {"databases": [{"path": "custom"}]}},
    )
    unit = _unit(scenario)
    monkeypatch.setattr(
        runner,
        "make_project_prelaunch_hook",
        lambda _request: lambda *_args: None,
    )
    monkeypatch.setattr(
        runner,
        "materialize_media_pool_case",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        runner,
        "stage_media_pool_case",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )

    class EarlyFailureLifecycle:
        def __init__(self, *, scenario_id, version, scenario_root, prelaunch_hook, **_kwargs):
            self.scenario_id = scenario_id
            self.version = version
            self.root = Path(scenario_root)
            self.prelaunch_hook = prelaunch_hook

        def start(self):
            evidence = self.root / "evidence"
            assets = self.root / "owned" / "assets"
            io_root = self.root / "owned" / "io"
            copy = self.root / "owned" / "sandbox-root" / "copy"
            roots = [evidence, assets, io_root, copy]
            if os.name == "nt":
                roots.extend(
                    runner._native_windows_launch_roots(
                        self.root / "owned"
                    ).values()
                )
            else:
                roots.append(self.root / "owned" / "wwise-user-home")
            for path in roots:
                path.mkdir(parents=True, exist_ok=True)
            sandbox = SimpleNamespace(
                sandbox_path=copy,
                sandbox_project=copy / "SampleProject.wproj",
                source_root=tmp_path / "source",
            )
            self.prelaunch_hook(sandbox, assets, io_root)
            start_evidence = evidence / "start-failure.json"
            start_evidence.write_text("{}\n", encoding="utf-8")
            raise lifecycle_v3.ScenarioLifecycleStartError(
                stage="wwise-launch",
                primary_error="RuntimeError: readiness failed",
                evidence_path=start_evidence,
                errors=("wwise-start-cleanup:RuntimeError: residual",),
                unsafe_to_continue=True,
            )

    monkeypatch.setattr(runner, "ScenarioLifecycle", EarlyFailureLifecycle)
    monkeypatch.setattr(
        runner,
        "OwnedDirectWaapiCall",
        lambda **_kwargs: pytest.fail("direct client must not open"),
    )

    root = tmp_path / "case"
    outcome = runner.run_heavy_project_unit(
        unit,
        scenario_root=root,
        options=_options(tmp_path),
    )

    assert outcome.status == "BLOCKED"
    assert outcome.checks["campaign_must_abort"] is True
    isolation = outcome.checks["early_media_isolation"]
    assert isolation["real_user_state_unchanged"] is True
    assert Path(isolation["evidence_path"]).is_file()
    assert json.loads((root / "outcome.json").read_text(encoding="utf-8"))[
        "status"
    ] == "BLOCKED"
