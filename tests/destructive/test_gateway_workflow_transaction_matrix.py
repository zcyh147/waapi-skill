from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]


if os.getenv("WWISE_LIVE") != "1" or os.getenv("WWISE_DESTRUCTIVE") != "1":
    pytest.skip(
        "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required for gateway workflow transaction tests",
        allow_module_level=True,
    )


from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    path_is_under,
    resolve_sample_project_source,
)
from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    DEFAULT_SANDBOX_ROOT,
    LiveSandboxLock,
    SandboxFixtureError,
    SandboxProject,
    cleanup_sandbox,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from wwise_waapi.headless import HeadlessLifecycle  # pyright: ignore[reportMissingImports]  # noqa: E402
from wwise_waapi.operation_registry import OPERATION_REQUEST_CONTRACT  # pyright: ignore[reportMissingImports]  # noqa: E402
from wwise_waapi.transactions import TransactionState, TransactionStore  # pyright: ignore[reportMissingImports]  # noqa: E402
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS  # pyright: ignore[reportMissingImports]  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = REPO_ROOT / "skills" / "waapi-skill" / "scripts" / "gateway.py"
ACTOR_MIXER_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
CONTAINERS_PARENT = r"\Containers\Default Work Unit"
SOUNDBANK_PARENT = r"\SoundBanks\Default Work Unit"
SWITCH_PARENT = r"\Switches\Default Work Unit"
SWITCH_GROUP_REFERENCE = "SwitchGroupOrStateGroup"

GATEWAY_SPEC = importlib.util.spec_from_file_location("waapi_destructive_workflow_gateway", GATEWAY_PATH)
assert GATEWAY_SPEC is not None and GATEWAY_SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(GATEWAY_SPEC)
sys.modules[GATEWAY_SPEC.name] = waapi_gateway
GATEWAY_SPEC.loader.exec_module(waapi_gateway)


@dataclass(slots=True)
class _WorkflowSandboxRuntime:
    version: str
    sandbox: SandboxProject
    lifecycle: HeadlessLifecycle
    state_dir: Path
    env: dict[str, str]

    @property
    def port(self) -> int:
        assert self.lifecycle.port is not None
        return self.lifecycle.port

    def gateway(self, command: Sequence[str], *, live: bool) -> dict[str, Any]:
        argv = [
            "--host",
            self.lifecycle.host,
            "--port",
            str(self.port),
            "--version",
            self.version,
            "--timeout",
            "30",
            "--state-dir",
            str(self.state_dir),
            *command,
        ]
        exit_code, payload = waapi_gateway.execute_gateway(argv, env=self.env)
        assert exit_code == 0, payload
        assert payload["ok"] is True, payload
        if live:
            assert payload["endpoint"] == {
                "host": self.lifecycle.host,
                "port": self.port,
                "url": self.lifecycle.waapi_url,
            }
            assert payload["detected_version"] == self.version
        return payload

    def packaged_status(self) -> dict[str, Any]:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "skills" / "waapi-skill" / "scripts" / "run.py"),
                "gateway.py",
                "--host",
                self.lifecycle.host,
                "--port",
                str(self.port),
                "--version",
                self.version,
                "--timeout",
                "30",
                "status",
            ],
            cwd=REPO_ROOT / "skills" / "waapi-skill",
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, {
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "returncode": completed.returncode,
        }
        payload = json.loads(completed.stdout)
        assert payload["ok"] is True, payload
        assert payload["command"] == "status"
        assert payload["detected_version"] == self.version
        return payload


@pytest.fixture(scope="module")
def workflow_sandbox_runtime(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_WorkflowSandboxRuntime]:
    env = dict(os.environ)
    version = env.get("WWISE_VERSION", "")
    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise AssertionError(
            f"WWISE_VERSION must select one of {SUPPORTED_WWISE_VERSION_KEYS!r}; got {version!r}"
        )

    lock = LiveSandboxLock(_safe_lock_root(env))
    sandbox: SandboxProject | None = None
    lifecycle: HeadlessLifecycle | None = None
    source_hash_before: tuple[str, int, int] | None = None
    source_tree_before: tuple[str, int] | None = None
    deferred_error: BaseException | None = None
    task_root = tmp_path_factory.mktemp(f"gateway-workflows-{version.replace('.', '-')}")
    state_dir = task_root / "state"

    lock.__enter__()
    try:
        sandbox = prepare_sample_project_sandbox(env, sandbox_root=lock.root, hash_strategy="bounded")
        source_hash_before = _hash_mutation_bearing_project_files(sandbox.source_root)
        source_tree_before = _source_tree_inventory(sandbox.source_root)
        assert source_hash_before[1] > 0, "immutable SampleProject source has no .wproj/.wwu files to hash"
        lifecycle = launch_sandboxed_wwise(sandbox, env)
        assert lifecycle.port is not None
        assert sandbox.metadata.selected_port == lifecycle.port
        assert sandbox.metadata.launch_project_path == str(sandbox.sandbox_project)
        assert path_is_under(sandbox.sandbox_project, sandbox.sandbox_root)
        assert sandbox.sandbox_project.resolve(strict=True) != sandbox.source_project.resolve(strict=True)

        config_path = task_root / "config" / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "wwise_version": version,
                    "waapi_host": lifecycle.host,
                    "waapi_port": lifecycle.port,
                    "project_modification_policy": "ask_before_changes",
                }
            ),
            encoding="utf-8",
        )
        gateway_env = {
            **env,
            **sandbox.env,
            "WWISE_VERSION": version,
            "WWISE_WAAPI_HOST": lifecycle.host,
            "WWISE_WAAPI_PORT": str(lifecycle.port),
            "WWISE_EVIDENCE_DIR": str(task_root / "dispatcher-evidence"),
            "WAAPI_SKILL_STATE_DIR": str(state_dir),
            "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        }
        yield _WorkflowSandboxRuntime(
            version=version,
            sandbox=sandbox,
            lifecycle=lifecycle,
            state_dir=state_dir,
            env=gateway_env,
        )
    finally:
        if lifecycle is not None and sandbox is not None:
            try:
                shutdown_sandboxed_wwise(lifecycle, sandbox)
            except BaseException as exc:  # noqa: BLE001 - every teardown guard must still run
                deferred_error = deferred_error or exc

        if sandbox is not None and source_hash_before is not None:
            try:
                source_hash_after = _hash_mutation_bearing_project_files(sandbox.source_root)
                if source_hash_after != source_hash_before:
                    raise AssertionError(
                        "immutable SampleProject source hash changed during gateway workflow test: "
                        f"before={source_hash_before[0]} after={source_hash_after[0]}"
                    )
                if source_tree_before is not None:
                    source_tree_after = _source_tree_inventory(sandbox.source_root)
                    if source_tree_after != source_tree_before:
                        raise AssertionError(
                            "immutable SampleProject source tree metadata changed during gateway workflow test: "
                            f"before={source_tree_before} after={source_tree_after}"
                        )
            except BaseException as exc:  # noqa: BLE001 - sandbox cleanup still has to run
                deferred_error = deferred_error or exc

        if sandbox is not None:
            try:
                cleanup_sandbox(sandbox, keep=False, failed=False)
            except BaseException as exc:  # noqa: BLE001 - lock release must still run
                deferred_error = deferred_error or exc

        try:
            lock.__exit__(None, None, None)
        except BaseException as exc:  # noqa: BLE001 - preserve the first teardown failure
            deferred_error = deferred_error or exc

        if deferred_error is not None:
            raise deferred_error


@pytest.mark.live
@pytest.mark.destructive
def test_closed_gateway_workflows_across_selected_version(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    runtime = workflow_sandbox_runtime
    object_parent = CONTAINERS_PARENT if runtime.version == "2025.1" else ACTOR_MIXER_PARENT
    unique_suffix = uuid.uuid4().hex[:12]

    imported_id: str | None = None
    soundbank_id: str | None = None
    included_id: str | None = None
    included_second_id: str | None = None
    switch_container_id: str | None = None
    switch_group_id: str | None = None
    switch_id: str | None = None
    assignment_child_id: str | None = None

    try:
        runtime.packaged_status()
        import_name = f"WAAPI_GATEWAY_AUDIO_{runtime.version.replace('.', '_')}_{unique_suffix}"
        audio_file = _write_fixture_wav(runtime.sandbox.sandbox_path / "GatewayWorkflowAudio", import_name)
        assert path_is_under(audio_file.resolve(strict=True), runtime.sandbox.sandbox_path.resolve(strict=True))
        requested_object_path = f"{object_parent}\\<Sound>{import_name}"
        audio_import = _complete_transaction(
            runtime,
            operation="audio.import",
            arguments={
                "imports": [
                    {
                        "object_path": requested_object_path,
                        "audio_file": str(audio_file),
                        "object_type": "Sound",
                        "notes": f"closed gateway audio import {import_name}",
                    }
                ]
            },
        )
        imported_row = _imported_object(audio_import["execute"], requested_object_path)
        imported_id = _required_string(imported_row, "id")
        imported_path = _required_string(imported_row, "path")
        assert imported_path == _untyped_object_path(requested_object_path), imported_row
        _assert_verification_assertion(
            audio_import["verification_evidence"], "import result shape matches version"
        )
        _assert_verification_assertion(
            audio_import["verification_evidence"], "import target returned exactly once"
        )
        _assert_verification_assertion(
            audio_import["verification_evidence"], "imported GUID resolves exactly once"
        )
        _assert_verification_assertion(
            audio_import["verification_evidence"], "imported path matches returned target"
        )
        if runtime.version in {"2023.1", "2024.1", "2025.1"}:
            _assert_verification_assertion(
                audio_import["verification_evidence"], "audio import log has no errors"
            )

        included_id = _create_object(
            runtime,
            parent=object_parent,
            object_type="ActorMixer",
            name=f"WAAPI_GATEWAY_INCLUDED_{runtime.version.replace('.', '_')}_{unique_suffix}",
        )
        included_second_id = _create_object(
            runtime,
            parent=object_parent,
            object_type="ActorMixer",
            name=f"WAAPI_GATEWAY_INCLUDED_SECOND_{runtime.version.replace('.', '_')}_{unique_suffix}",
        )
        soundbank_id = _create_object(
            runtime,
            parent=SOUNDBANK_PARENT,
            object_type="SoundBank",
            name=f"WAAPI_GATEWAY_BANK_{runtime.version.replace('.', '_')}_{unique_suffix}",
        )
        inclusions_add = _complete_transaction(
            runtime,
            operation="soundbank.setInclusions",
            arguments={
                "soundbank": {"kind": "id", "value": soundbank_id},
                "mode": "add",
                "inclusions": [
                    {
                        "object": {"kind": "id", "value": included_id},
                        "filters": ["structures", "media"],
                    }
                ],
            },
        )
        _assert_verification_assertion(
            inclusions_add["verification_evidence"],
            "SoundBank inclusions match computed post-state",
        )
        _assert_soundbank_post_state(
            inclusions_add["verification_evidence"],
            [{"object": included_id.casefold(), "filters": ["media", "structures"]}],
        )

        inclusions_union = _complete_transaction(
            runtime,
            operation="soundbank.setInclusions",
            arguments={
                "soundbank": {"kind": "id", "value": soundbank_id},
                "mode": "add",
                "inclusions": [
                    {
                        "object": {"kind": "id", "value": included_id},
                        "filters": ["events"],
                    }
                ],
            },
        )
        _assert_soundbank_post_state(
            inclusions_union["verification_evidence"],
            [{"object": included_id.casefold(), "filters": ["events"]}],
        )

        inclusions_preserve = _complete_transaction(
            runtime,
            operation="soundbank.setInclusions",
            arguments={
                "soundbank": {"kind": "id", "value": soundbank_id},
                "mode": "add",
                "inclusions": [
                    {
                        "object": {"kind": "id", "value": included_second_id},
                        "filters": ["media"],
                    }
                ],
            },
        )
        _assert_soundbank_post_state(
            inclusions_preserve["verification_evidence"],
            [
                {"object": included_id.casefold(), "filters": ["events"]},
                {"object": included_second_id.casefold(), "filters": ["media"]},
            ],
        )

        inclusions_remove = _complete_transaction(
            runtime,
            operation="soundbank.setInclusions",
            arguments={
                "soundbank": {"kind": "id", "value": soundbank_id},
                "mode": "remove",
                "inclusions": [
                    {
                        "object": {"kind": "id", "value": included_id},
                        "filters": ["events"],
                    }
                ],
            },
        )
        _assert_soundbank_post_state(
            inclusions_remove["verification_evidence"],
            [{"object": included_second_id.casefold(), "filters": ["media"]}],
        )

        inclusions_replace = _complete_transaction(
            runtime,
            operation="soundbank.setInclusions",
            arguments={
                "soundbank": {"kind": "id", "value": soundbank_id},
                "mode": "replace",
                "inclusions": [
                    {
                        "object": {"kind": "id", "value": included_id},
                        "filters": ["events", "structures"],
                    }
                ],
            },
        )
        _assert_soundbank_post_state(
            inclusions_replace["verification_evidence"],
            [{"object": included_id.casefold(), "filters": ["events", "structures"]}],
        )

        inclusions_clear = _complete_transaction(
            runtime,
            operation="soundbank.setInclusions",
            arguments={
                "soundbank": {"kind": "id", "value": soundbank_id},
                "mode": "replace",
                "inclusions": [],
            },
        )
        _assert_soundbank_post_state(inclusions_clear["verification_evidence"], [])

        switch_container_id = _create_object(
            runtime,
            parent=object_parent,
            object_type="SwitchContainer",
            name=f"WAAPI_GATEWAY_SC_{runtime.version.replace('.', '_')}_{unique_suffix}",
        )
        switch_group_id = _create_object(
            runtime,
            parent=SWITCH_PARENT,
            object_type="SwitchGroup",
            name=f"WAAPI_GATEWAY_SG_{runtime.version.replace('.', '_')}_{unique_suffix}",
        )
        switch_id = _create_object(
            runtime,
            parent=switch_group_id,
            object_type="Switch",
            name=f"WAAPI_GATEWAY_SWITCH_{runtime.version.replace('.', '_')}_{unique_suffix}",
        )
        _complete_transaction(
            runtime,
            operation="object.setReference",
            arguments={
                "object": {"kind": "id", "value": switch_container_id},
                "reference": SWITCH_GROUP_REFERENCE,
                "target": {"kind": "id", "value": switch_group_id},
            },
        )
        assignment_child_id = _create_object(
            runtime,
            parent=switch_container_id,
            object_type="Sound",
            name=f"WAAPI_GATEWAY_CHILD_{runtime.version.replace('.', '_')}_{unique_suffix}",
        )

        assignment_arguments = {
            "switch_container": {"kind": "id", "value": switch_container_id},
            "child": {"kind": "id", "value": assignment_child_id},
            "state_or_switch": {"kind": "id", "value": switch_id},
        }
        add_assignment = _complete_transaction(
            runtime,
            operation="switchContainer.addAssignment",
            arguments=assignment_arguments,
        )
        _assert_verification_assertion(
            add_assignment["verification_evidence"], "assignment pair is present"
        )

        remove_assignment = _complete_transaction(
            runtime,
            operation="switchContainer.removeAssignment",
            arguments=assignment_arguments,
        )
        _assert_verification_assertion(
            remove_assignment["verification_evidence"], "assignment pair is absent"
        )
    finally:
        active_error = sys.exc_info()[1]
        cleanup_errors: list[str] = []
        # Delete leaves before their parents, and remove the SwitchContainer before its referenced group.
        cleanup_order = (
            imported_id,
            soundbank_id,
            included_id,
            included_second_id,
            assignment_child_id,
            switch_container_id,
            switch_id,
            switch_group_id,
        )
        for object_id in cleanup_order:
            if object_id is None:
                continue
            try:
                _delete_if_present_via_transaction(runtime, object_id)
            except BaseException as exc:  # noqa: BLE001 - continue through every disposable object
                cleanup_errors.append(f"{object_id}: {type(exc).__name__}: {exc}")
        if cleanup_errors:
            message = "gateway workflow cleanup failures: " + "; ".join(cleanup_errors)
            if active_error is not None:
                active_error.add_note(message)
            else:
                raise AssertionError(message)


def _complete_transaction(
    runtime: _WorkflowSandboxRuntime,
    *,
    operation: str,
    arguments: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": runtime.version,
        "operation": operation,
        "arguments": dict(arguments),
    }
    preview = runtime.gateway(
        ["preview", "--request-json", json.dumps(request, ensure_ascii=False), "--ttl", "900"],
        live=True,
    )
    assert preview["status"] == TransactionState.AWAITING_CONFIRMATION.value
    assert preview["state"] == TransactionState.AWAITING_CONFIRMATION.value
    assert preview["preview_summary"]["request"] == request
    assert preview["preview_summary"]["dispatch"]["uri"].startswith("ak.wwise.")
    assert preview["executed"] is False
    assert preview["verified"] is False

    transaction_id = preview["transaction_id"]
    artifact_hash = preview["artifact_hash"]
    assert isinstance(transaction_id, str) and transaction_id
    assert isinstance(artifact_hash, str) and len(artifact_hash) == 64

    confirmed = runtime.gateway(
        ["confirm", transaction_id, "--artifact-hash", artifact_hash],
        live=False,
    )
    assert confirmed["offline"] is True
    assert confirmed["state"] == TransactionState.CONFIRMED.value
    assert confirmed["artifact_hash"] == artifact_hash

    executed = runtime.gateway(["execute", transaction_id], live=True)
    assert executed["status"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert executed["artifact_hash"] == artifact_hash
    assert executed["executed"] is True
    assert executed["verified"] is False
    assert executed["automatic_retry"] is False

    verified = runtime.gateway(["verify", transaction_id], live=True)
    assert verified["status"] == TransactionState.VERIFIED.value
    assert verified["state"] == TransactionState.VERIFIED.value
    assert verified["artifact_hash"] == artifact_hash
    assert verified["executed"] is True
    assert verified["verified"] is True
    assert verified["automatic_retry"] is False
    assert verified["verification"]["operation"] == operation
    assert verified["verification"]["status"] == TransactionState.VERIFIED.value

    store = TransactionStore(runtime.state_dir)
    assert store.load(transaction_id).state is TransactionState.VERIFIED
    assert store.load_preview(transaction_id).artifact_hash == artifact_hash
    verification_events = [
        event
        for event in store.read_events(transaction_id)
        if event.get("event_type") == "verification_recorded"
    ]
    assert len(verification_events) == 1, verification_events
    verification_details = verification_events[0].get("details")
    assert isinstance(verification_details, Mapping), verification_events[0]
    verification_evidence = verification_details.get("verification")
    assert isinstance(verification_evidence, Mapping), verification_details
    assert verification_evidence["operation"] == operation
    assert verification_evidence["status"] == TransactionState.VERIFIED.value

    assertions = verification_evidence.get("assertions")
    readbacks = verification_evidence.get("readbacks")
    assert isinstance(assertions, list) and assertions, verification_evidence
    assert isinstance(readbacks, list), verification_evidence
    assert all(
        isinstance(item, Mapping) and item.get("passed") is True
        for item in assertions
    ), assertions

    stdout_projection = verified.get("stdout_projection")
    assert isinstance(stdout_projection, Mapping), verified
    assert stdout_projection["contract"] == (
        waapi_gateway.TRANSACTION_VERIFY_SUCCESS_SUMMARY_CONTRACT
    )
    assert stdout_projection["full_verification_evidence_persisted"] is True
    assert stdout_projection["journal_event"] == "verification_recorded"
    assert stdout_projection["assertion_count"] == len(assertions)
    assert stdout_projection["passed_assertion_count"] == len(assertions)
    assert stdout_projection["readback_count"] == len(readbacks)
    assert stdout_projection["verification_canonical_sha256"] == (
        waapi_gateway.canonical_sha256(verification_evidence)
    )

    stdout_verification = verified.get("verification")
    assert isinstance(stdout_verification, Mapping), verified
    if stdout_projection["full_verification_evidence_in_stdout"] is True:
        assert stdout_verification == verification_evidence
    else:
        assert stdout_verification["summary_contract"] == (
            waapi_gateway.TRANSACTION_VERIFICATION_RESULT_SUMMARY_CONTRACT
        )
        assert stdout_verification["assertion_count"] == len(assertions)
        assert stdout_verification["passed_assertion_count"] == len(assertions)
        assert stdout_verification["failed_assertion_count"] == 0
        assert stdout_verification["assertions_canonical_sha256"] == (
            waapi_gateway.canonical_sha256(assertions)
        )
        assert stdout_verification["readback_count"] == len(readbacks)
        assert stdout_verification["readbacks_canonical_sha256"] == (
            waapi_gateway.canonical_sha256(readbacks)
        )
        assert stdout_verification["canonical_sha256"] == (
            waapi_gateway.canonical_sha256(verification_evidence)
        )
        assert stdout_verification["full_evidence_in_stdout"] is False

    return {
        "preview": preview,
        "execute": executed,
        "verify": verified,
        "verification_evidence": verification_evidence,
    }


def _create_object(
    runtime: _WorkflowSandboxRuntime,
    *,
    parent: str,
    object_type: str,
    name: str,
) -> str:
    parent_identity = (
        {"kind": "path", "value": parent}
        if parent.startswith("\\")
        else {"kind": "id", "value": parent}
    )
    transaction = _complete_transaction(
        runtime,
        operation="object.create",
        arguments={"parent": parent_identity, "type": object_type, "name": name},
    )
    return _created_object_id(transaction["execute"])


def _delete_if_present_via_transaction(runtime: _WorkflowSandboxRuntime, object_id: str) -> None:
    before = runtime.gateway(
        ["query-object", "--object-id", object_id, "--return-field", "id", "--return-field", "path"],
        live=True,
    )
    if before["count"] == 0:
        return
    assert before["count"] == 1, before
    _complete_transaction(
        runtime,
        operation="object.delete",
        arguments={"object": {"kind": "id", "value": object_id}},
    )
    after = runtime.gateway(
        ["query-object", "--object-id", object_id, "--return-field", "id"],
        live=True,
    )
    assert after["count"] == 0
    assert after["objects"] == []


def _created_object_id(executed: Mapping[str, Any]) -> str:
    dispatch_result = executed.get("dispatch_result")
    assert isinstance(dispatch_result, Mapping), executed
    result = dispatch_result.get("result")
    assert isinstance(result, Mapping), dispatch_result
    return _required_string(result, "id")


def _imported_object(executed: Mapping[str, Any], requested_object_path: str) -> Mapping[str, Any]:
    dispatch_result = executed.get("dispatch_result")
    assert isinstance(dispatch_result, Mapping), executed
    result = dispatch_result.get("result")
    assert isinstance(result, Mapping), dispatch_result
    rows = result.get("objects")
    assert isinstance(rows, list) and rows, result
    assert all(isinstance(row, Mapping) for row in rows), rows
    expected_path = _untyped_object_path(requested_object_path)
    matches = [row for row in rows if row.get("path") == expected_path]
    assert len(matches) == 1, {"expected_path": expected_path, "objects": rows}
    _required_string(matches[0], "id")
    _required_string(matches[0], "path")
    return matches[0]


def _required_string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    assert isinstance(result, str) and result, {"field": field, "value": value}
    return result


def _untyped_object_path(object_path: str) -> str:
    parts: list[str] = []
    for part in object_path.split("\\"):
        if part.startswith("<") and ">" in part:
            part = part.split(">", 1)[1]
        parts.append(part)
    return "\\".join(parts)


def _assert_verification_assertion(verification: Mapping[str, Any], name: str) -> None:
    assertions = verification.get("assertions")
    assert isinstance(assertions, list), verification
    matches = [item for item in assertions if isinstance(item, Mapping) and item.get("name") == name]
    assert len(matches) == 1, {"expected_assertion": name, "assertions": assertions}
    assert matches[0].get("passed") is True, matches[0]


def _assert_soundbank_post_state(
    verification: Mapping[str, Any], expected: list[dict[str, Any]]
) -> None:
    assertions = verification.get("assertions")
    assert isinstance(assertions, list), verification
    matches = [
        item
        for item in assertions
        if isinstance(item, Mapping) and item.get("name") == "SoundBank inclusions match computed post-state"
    ]
    assert len(matches) == 1, matches
    evidence = matches[0].get("evidence")
    assert isinstance(evidence, Mapping), matches[0]
    normalized_expected = sorted(expected, key=lambda row: str(row["object"]))
    assert evidence.get("expected") == normalized_expected
    assert evidence.get("actual") == normalized_expected


def _write_fixture_wav(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.wav"
    sample_rate = 8000
    frame_count = sample_rate // 10
    amplitude = 6000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            value = int(amplitude * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(value.to_bytes(2, byteorder="little", signed=True))
        wav_file.writeframes(bytes(frames))
    assert path.is_file() and not path.is_symlink()
    return path.resolve(strict=True)


def _safe_lock_root(env: Mapping[str, str]) -> Path:
    configured = env.get("WWISE_SANDBOX_ROOT")
    root = Path(configured).expanduser() if configured else REPO_ROOT / DEFAULT_SANDBOX_ROOT
    resolved = root.resolve(strict=False)
    source_project = resolve_sample_project_source(env)
    if source_project is not None:
        source_root = source_project.parent.resolve(strict=False)
        if resolved == source_root or path_is_under(resolved, source_root) or path_is_under(source_root, resolved):
            raise SandboxFixtureError("gateway workflow sandbox root must not overlap the immutable SampleProject source")
    return resolved


def _hash_mutation_bearing_project_files(root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    bytes_hashed = 0
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in {".wproj", ".wwu"}
    ]
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        data = path.read_bytes()
        digest.update(data)
        digest.update(b"\0")
        bytes_hashed += len(data)
    return digest.hexdigest(), len(files), bytes_hashed


def _source_tree_inventory(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    paths = sorted(root.rglob("*"))
    for path in paths:
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(metadata.st_mode).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(metadata.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(metadata.st_mtime_ns).encode("ascii"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(os.readlink(path).encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest(), len(paths)
