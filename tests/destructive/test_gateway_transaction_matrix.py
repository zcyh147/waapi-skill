from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]

from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    path_is_under,
    resolve_sample_project_source,
)
from tests.destructive.support.category_evidence import (  # pyright: ignore[reportMissingImports]
    append_category_evidence,
    exact_git_candidate,
)
from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    DEFAULT_SANDBOX_ROOT,
    LiveSandboxLock,
    SandboxFixtureError,
    SandboxProject,
    cleanup_sandbox,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from tests.semantic.support.typed_gateway_input import (  # pyright: ignore[reportMissingImports]
    create_object_lifecycle_business_preview,
    create_typed_transaction_preview,
    typed_wait_topic_command,
)
from tests.semantic.support.codex_harness import (  # pyright: ignore[reportMissingImports]
    force_kill_and_reap_process,
    subprocess_process_group_options,
    terminate_and_reap_process,
)
from tests.semantic.support.codex_gateway_broker import (  # pyright: ignore[reportMissingImports]
    _subscription_ack_process_binding_is_valid,
)
from wwise_waapi.headless import HeadlessLifecycle  # pyright: ignore[reportMissingImports]
from wwise_waapi.operation_registry import OPERATION_REQUEST_CONTRACT  # pyright: ignore[reportMissingImports]
from wwise_waapi.subscriptions import (  # pyright: ignore[reportMissingImports]
    SUBSCRIPTION_ACK_CONTRACT,
    SUBSCRIPTION_ACK_NONCE_ENV,
    SUBSCRIPTION_ACK_PATH_ENV,
    SUBSCRIPTION_ACK_STEP_ENV,
    SUBSCRIPTION_ACK_TOPIC_ENV,
)
from wwise_waapi.transactions import TransactionState, TransactionStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
GATEWAY_PATH = SKILL_ROOT / "scripts" / "gateway.py"
PACKAGED_RUNNER_PATH = SKILL_ROOT / "scripts" / "run.py"
ACTOR_MIXER_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
CONTAINERS_PARENT = r"\Containers\Default Work Unit"
PACKAGED_WAIT_TOPIC_TIMEOUT_SECONDS = 45.0
SUBSCRIPTION_ACK_WAIT_SECONDS = 15.0
SUBSCRIPTION_ACK_POLL_SECONDS = 0.02
SUBSCRIPTION_ACK_MAX_BYTES = 4096
PACKAGED_GATEWAY_MAX_STDOUT_BYTES = 1024 * 1024
PACKAGED_GATEWAY_DIAGNOSTIC_BYTES = 8192
PYTHON_IO_ENCODING_ENV = "PYTHONIOENCODING"
CODEX_GATEWAY_REQUIRED_ENV = "WAAPI_CODEX_GATEWAY_REQUIRED"

GATEWAY_SPEC = importlib.util.spec_from_file_location("waapi_destructive_transaction_gateway", GATEWAY_PATH)
assert GATEWAY_SPEC is not None and GATEWAY_SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(GATEWAY_SPEC)
sys.modules[GATEWAY_SPEC.name] = waapi_gateway
GATEWAY_SPEC.loader.exec_module(waapi_gateway)


@dataclass(slots=True)
class _GatewaySandboxRuntime:
    version: str
    sandbox: SandboxProject
    lifecycle: HeadlessLifecycle
    state_dir: Path
    env: dict[str, str]
    candidate: str
    category_results: list[dict[str, Any]]

    @property
    def port(self) -> int:
        assert self.lifecycle.port is not None
        return self.lifecycle.port

    def gateway(
        self,
        command: Sequence[str],
        *,
        live: bool,
    ) -> dict[str, Any]:
        exit_code, payload = waapi_gateway.execute_gateway(
            self.gateway_argv(command),
            env=self.env,
        )
        assert exit_code == 0, payload
        assert payload["ok"] is True, payload
        if live:
            self.assert_live_payload(payload)
        return payload

    def gateway_argv(self, command: Sequence[str]) -> list[str]:
        return [
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

    def assert_live_payload(self, payload: Mapping[str, Any]) -> None:
        assert payload["endpoint"] == {
            "host": self.lifecycle.host,
            "port": self.port,
            "url": self.lifecycle.waapi_url,
        }
        assert payload["detected_version"] == self.version


@dataclass(slots=True)
class _PackagedTopicWait:
    """One real packaged wait-topic child with a trusted subscription ACK."""

    process: subprocess.Popen[str]
    ack_path: Path
    ack_nonce: str
    ack_topic: str
    ack_step: str
    started_at_unix_ns: int

    def wait_until_subscribed(self) -> Mapping[str, Any]:
        deadline = time.monotonic() + SUBSCRIPTION_ACK_WAIT_SECONDS
        while True:
            try:
                metadata = self.ack_path.lstat()
            except FileNotFoundError:
                metadata = None
            except OSError as exc:
                self.close()
                raise AssertionError(
                    f"packaged wait-topic subscription ACK is unavailable: {exc}"
                ) from exc

            if metadata is not None:
                if self.ack_path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                    self.close()
                    raise AssertionError(
                        "packaged wait-topic subscription ACK is not a regular file"
                    )
                if metadata.st_nlink == 1:
                    return _read_subscription_ack(
                        self.ack_path,
                        nonce=self.ack_nonce,
                        topic=self.ack_topic,
                        step=self.ack_step,
                        started_at_unix_ns=self.started_at_unix_ns,
                        runner_parent_process_id=self.process.pid,
                    )
                if metadata.st_nlink != 2:
                    self.close()
                    raise AssertionError(
                        "packaged wait-topic subscription ACK has an invalid link count"
                    )

            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate()
                raise AssertionError(
                    "packaged wait-topic exited before publishing its subscription ACK: "
                    + _packaged_process_diagnostics(
                        returncode=self.process.returncode,
                        stdout=stdout,
                        stderr=stderr,
                    )
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()
                raise AssertionError(
                    "packaged wait-topic did not publish its subscription ACK "
                    f"within {SUBSCRIPTION_ACK_WAIT_SECONDS:g}s"
                )
            time.sleep(min(SUBSCRIPTION_ACK_POLL_SECONDS, remaining))

    def finish(self) -> dict[str, Any]:
        try:
            stdout, stderr = self.process.communicate(
                timeout=PACKAGED_WAIT_TOPIC_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = self._terminate_and_capture()
            raise AssertionError(
                "packaged wait-topic did not finish within its bounded timeout: "
                + _packaged_process_diagnostics(
                    returncode=self.process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                )
            ) from exc
        except BaseException:
            try:
                self._terminate_and_capture()
            except BaseException:
                pass
            raise
        return _parse_packaged_gateway_result(
            returncode=int(self.process.returncode),
            stdout=stdout,
            stderr=stderr,
        )

    def close(self) -> None:
        if self.process.poll() is not None:
            self.process.communicate()
            return
        self._terminate_and_capture()

    def _terminate_and_capture(self) -> tuple[str, str]:
        try:
            return terminate_and_reap_process(self.process)
        except BaseException as graceful_error:
            try:
                return force_kill_and_reap_process(self.process)
            except BaseException as force_error:
                if hasattr(force_error, "add_note"):
                    force_error.add_note(
                        "graceful packaged wait-topic cleanup also failed: "
                        f"{type(graceful_error).__name__}: {graceful_error}"
                    )
                raise


@pytest.fixture(scope="module")
def gateway_sandbox_runtime(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_GatewaySandboxRuntime]:
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
    source_hash_after: tuple[str, int, int] | None = None
    source_tree_after: tuple[str, int] | None = None
    deferred_error: BaseException | None = None
    task_root = tmp_path_factory.mktemp(f"gateway-transaction-{version.replace('.', '-')}")
    state_dir = task_root / "state"
    candidate = exact_git_candidate(REPO_ROOT)
    category_results: list[dict[str, Any]] = []

    lock.__enter__()
    try:
        sandbox = prepare_sample_project_sandbox(
            env,
            sandbox_root=lock.root,
            hash_strategy="bounded",
        )
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
        yield _GatewaySandboxRuntime(
            version=version,
            sandbox=sandbox,
            lifecycle=lifecycle,
            state_dir=state_dir,
            env=gateway_env,
            candidate=candidate,
            category_results=category_results,
        )
    finally:
        if lifecycle is not None and sandbox is not None:
            try:
                shutdown_sandboxed_wwise(lifecycle, sandbox)
            except BaseException as exc:  # noqa: BLE001 - teardown must continue through every guard
                deferred_error = deferred_error or exc

        if sandbox is not None and source_hash_before is not None:
            try:
                source_hash_after = _hash_mutation_bearing_project_files(sandbox.source_root)
                if source_hash_after != source_hash_before:
                    raise AssertionError(
                        "immutable SampleProject source hash changed during gateway transaction test: "
                        f"before={source_hash_before[0]} after={source_hash_after[0]}"
                    )
                if source_tree_before is not None:
                    source_tree_after = _source_tree_inventory(sandbox.source_root)
                    if source_tree_after != source_tree_before:
                        raise AssertionError(
                            "immutable SampleProject source tree metadata changed during "
                            f"gateway transaction test: before={source_tree_before} "
                            f"after={source_tree_after}"
                        )
            except BaseException as exc:  # noqa: BLE001 - sandbox cleanup still has to run
                deferred_error = deferred_error or exc

        if sandbox is not None:
            try:
                cleanup_sandbox(sandbox, keep=False, failed=False)
            except BaseException as exc:  # noqa: BLE001 - lock release must still run
                deferred_error = deferred_error or exc

        if sandbox is not None and lifecycle is not None:
            try:
                append_category_evidence(
                    repo_root=REPO_ROOT,
                    candidate=candidate,
                    version=version,
                    host={
                        "display_name": sandbox.metadata.get_info_display_name,
                        "is_command_line": True,
                        "version": sandbox.metadata.get_info_version,
                    },
                    categories=category_results,
                    source={
                        "project": str(sandbox.source_project),
                        "hash_before": source_hash_before[0] if source_hash_before else None,
                        "hash_after": source_hash_after[0] if source_hash_after else None,
                        "tree_metadata_before": source_tree_before[0] if source_tree_before else None,
                        "tree_metadata_after": source_tree_after[0] if source_tree_after else None,
                    },
                    residual_state={
                        "sandbox": "deleted" if not sandbox.sandbox_path.exists() else "retained",
                        "process_cleanup": sandbox.metadata.process_cleanup_result,
                        "residual_processes": (
                            sandbox.metadata.process_cleanup_details or {}
                        ).get("residual_processes", []),
                    },
                )
            except BaseException as exc:  # noqa: BLE001 - evidence is part of the gate
                deferred_error = deferred_error or exc

        try:
            lock.__exit__(None, None, None)
        except BaseException as exc:  # noqa: BLE001 - preserve the first teardown failure
            deferred_error = deferred_error or exc

        if deferred_error is not None:
            raise deferred_error


@pytest.mark.live
@pytest.mark.destructive
def test_gateway_transaction_object_lifecycle_across_selected_version(
    gateway_sandbox_runtime: _GatewaySandboxRuntime,
) -> None:
    runtime = gateway_sandbox_runtime
    unique_suffix = uuid.uuid4().hex[:12]
    object_name = f"WAAPI_GATEWAY_TX_{runtime.version.replace('.', '_')}_{unique_suffix}"
    renamed_object_name = f"{object_name}_RENAMED"
    initial_notes = f"gateway transaction create proof {object_name}"
    updated_notes = f"gateway transaction setNotes proof {renamed_object_name}"
    expected_volume = -6.0
    parent_path = (
        CONTAINERS_PARENT if runtime.version == "2025.1" else ACTOR_MIXER_PARENT
    )

    create = _complete_transaction(
        runtime,
        operation="object.create",
        arguments={
            "parent": {
                "kind": "path",
                "value": parent_path,
            },
            "type": "ActorMixer",
            "name": object_name,
            "notes": initial_notes,
        },
    )
    created_id = _created_object_id(create["execute"])

    try:
        created_row = _query_one_object_by_id(
            runtime,
            created_id,
            fields=("id", "name", "path", "notes"),
        )
        assert str(created_row["id"]).casefold() == created_id.casefold(), created_row
        assert created_row["name"] == object_name, created_row
        created_path = str(created_row["path"])
        assert created_path == f"{parent_path}\\{object_name}", created_row
        assert created_row["notes"] == initial_notes, created_row

        _complete_transaction(
            runtime,
            operation="object.setName",
            arguments={
                "object": {"kind": "id", "value": created_id},
                "value": renamed_object_name,
            },
        )
        renamed_row = _query_one_object_by_id(
            runtime,
            created_id,
            fields=("id", "name", "path"),
        )
        assert str(renamed_row["id"]).casefold() == created_id.casefold(), renamed_row
        assert renamed_row["name"] == renamed_object_name, renamed_row
        assert renamed_row["path"] == f"{parent_path}\\{renamed_object_name}", renamed_row
        _assert_query_object_absent(runtime, selector=("--path", created_path))

        _complete_transaction(
            runtime,
            operation="object.setNotes",
            arguments={
                "object": {"kind": "id", "value": created_id},
                "value": updated_notes,
            },
        )
        notes_row = _query_one_object_by_id(
            runtime,
            created_id,
            fields=("id", "notes"),
        )
        assert str(notes_row["id"]).casefold() == created_id.casefold(), notes_row
        assert notes_row["notes"] == updated_notes, notes_row

        _complete_transaction(
            runtime,
            operation="object.setProperty",
            arguments={
                "object": {"kind": "id", "value": created_id},
                "property": "Volume",
                "value": expected_volume,
            },
        )
        property_row = _query_one_object_by_id(
            runtime,
            created_id,
            fields=("id", "name", "path", "notes", "Volume"),
        )
        assert str(property_row["id"]).casefold() == created_id.casefold(), property_row
        assert property_row["name"] == renamed_object_name, property_row
        assert property_row["path"] == f"{parent_path}\\{renamed_object_name}", property_row
        assert property_row["notes"] == updated_notes, property_row
        assert float(property_row["Volume"]) == pytest.approx(expected_volume), property_row
    finally:
        _complete_transaction(
            runtime,
            operation="object.delete",
            arguments={"object": {"kind": "id", "value": created_id}},
        )
        _assert_query_object_absent(runtime, selector=("--object-id", created_id))


@pytest.mark.live
@pytest.mark.destructive
def test_gateway_wait_topic_matches_runner_owned_object_create_and_unsubscribes(
    gateway_sandbox_runtime: _GatewaySandboxRuntime,
) -> None:
    runtime = gateway_sandbox_runtime
    topic_uri = "ak.wwise.core.object.created"
    object_name = (
        f"WAAPI_GATEWAY_TOPIC_{runtime.version.replace('.', '_')}_{uuid.uuid4().hex[:12]}"
    )
    event_object_type = "PropertyContainer" if runtime.version == "2025.1" else "ActorMixer"
    created_id: str | None = None
    topic_wait = _start_packaged_topic_wait(
        runtime,
        typed_wait_topic_command(
            name="destructive.gateway.wait-topic",
            topic=topic_uri,
            version=runtime.version,
            event_count=1,
            options={"return": ["id", "name", "type", "path"]},
            match={"object": {"type": event_object_type}},
        ),
        topic=topic_uri,
    )
    try:
        ack = topic_wait.wait_until_subscribed()
        assert ack["topic"] == topic_uri
        created = _complete_transaction(
            runtime,
            operation="object.create",
            arguments={
                "parent": {
                    "kind": "path",
                    "value": (
                        CONTAINERS_PARENT
                        if runtime.version == "2025.1"
                        else ACTOR_MIXER_PARENT
                    ),
                },
                "type": "ActorMixer",
                "name": object_name,
                "notes": "runner-owned packaged wait-topic probe",
            },
        )
        created_id = _created_object_id(created["execute"])
        topic = topic_wait.finish()
        runtime.assert_live_payload(topic)

        assert topic["command"] == "wait-topic"
        assert topic["topic"] == topic_uri
        assert topic["match"] == {"object": {"type": event_object_type}}
        assert topic["cleanup"] == "unsubscribed"
        event = topic.get("event")
        assert isinstance(event, Mapping), topic
        event_object = event.get("object")
        assert isinstance(event_object, Mapping), event
        assert event_object.get("type") == event_object_type, event_object
        assert str(event_object.get("id", "")).casefold() == created_id.casefold(), event_object
        runtime.category_results.append(
            {"category": "topic", "status": "PASS", "verifier_strength": "exact_event_and_cleanup"}
        )
    finally:
        topic_wait.close()
        if created_id is not None:
            _complete_transaction(
                runtime,
                operation="object.delete",
                arguments={"object": {"kind": "id", "value": created_id}},
            )
            _assert_query_object_absent(
                runtime,
                selector=("--object-id", created_id),
            )


def _start_packaged_topic_wait(
    runtime: _GatewaySandboxRuntime,
    command: Sequence[str],
    *,
    topic: str,
) -> _PackagedTopicWait:
    evidence_directory = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    evidence_directory.mkdir(parents=True, exist_ok=True)
    ack_path = evidence_directory / f"subscription-ack-{secrets.token_hex(16)}.json"
    assert not ack_path.exists() and not ack_path.is_symlink()
    ack_nonce = secrets.token_urlsafe(32)
    ack_step = "destructive.gateway.wait-topic"
    runner_env = dict(runtime.env)
    runner_env.pop(CODEX_GATEWAY_REQUIRED_ENV, None)
    runner_env.update(
        {
            PYTHON_IO_ENCODING_ENV: "utf-8:strict",
            SUBSCRIPTION_ACK_PATH_ENV: str(ack_path),
            SUBSCRIPTION_ACK_NONCE_ENV: ack_nonce,
            SUBSCRIPTION_ACK_TOPIC_ENV: topic,
            SUBSCRIPTION_ACK_STEP_ENV: ack_step,
        }
    )
    started_at_unix_ns = time.time_ns()
    process = subprocess.Popen(
        [
            sys.executable,
            str(PACKAGED_RUNNER_PATH),
            "gateway.py",
            *runtime.gateway_argv(command),
        ],
        cwd=str(SKILL_ROOT),
        env=runner_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        **subprocess_process_group_options(),
    )
    return _PackagedTopicWait(
        process=process,
        ack_path=ack_path,
        ack_nonce=ack_nonce,
        ack_topic=topic,
        ack_step=ack_step,
        started_at_unix_ns=started_at_unix_ns,
    )


def _read_subscription_ack(
    path: Path,
    *,
    nonce: str,
    topic: str,
    step: str,
    started_at_unix_ns: int,
    runner_parent_process_id: int,
    platform_name: str | None = None,
) -> Mapping[str, Any]:
    raw = path.read_bytes()
    assert len(raw) <= SUBSCRIPTION_ACK_MAX_BYTES, (
        f"packaged wait-topic subscription ACK exceeded {SUBSCRIPTION_ACK_MAX_BYTES} bytes"
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssertionError(
            "packaged wait-topic subscription ACK is not strict UTF-8 JSON"
        ) from exc
    expected_keys = {
        "contract",
        "step_name",
        "topic",
        "nonce",
        "runner_parent_process_id",
        "gateway_process_id",
        "subscribed_at_unix_ns",
        "subscribed_at_monotonic_ns",
    }
    assert isinstance(payload, Mapping), payload
    assert set(payload) == expected_keys, payload
    canonical = (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    assert raw == canonical, payload
    assert payload["contract"] == SUBSCRIPTION_ACK_CONTRACT, payload
    assert payload["step_name"] == step, payload
    assert payload["topic"] == topic, payload
    assert type(payload["nonce"]) is str, payload
    assert secrets.compare_digest(payload["nonce"], nonce), payload
    assert type(payload["runner_parent_process_id"]) is int, payload
    assert type(payload["gateway_process_id"]) is int, payload
    assert _subscription_ack_process_binding_is_valid(
        platform_name=os.name if platform_name is None else platform_name,
        launched_process_id=runner_parent_process_id,
        reported_parent_process_id=int(payload["runner_parent_process_id"]),
        gateway_process_id=int(payload["gateway_process_id"]),
    ), payload
    assert type(payload["subscribed_at_unix_ns"]) is int, payload
    assert int(payload["subscribed_at_unix_ns"]) >= started_at_unix_ns, payload
    assert int(payload["subscribed_at_unix_ns"]) <= time.time_ns(), payload
    assert type(payload["subscribed_at_monotonic_ns"]) is int, payload
    assert int(payload["subscribed_at_monotonic_ns"]) > 0, payload
    return dict(payload)


def _parse_packaged_gateway_result(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    if len(stdout.encode("utf-8")) > PACKAGED_GATEWAY_MAX_STDOUT_BYTES:
        raise AssertionError(
            "packaged wait-topic stdout exceeded its bounded terminal result size"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            "packaged wait-topic did not emit exactly one terminal JSON value: "
            + _packaged_process_diagnostics(
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
            )
        ) from exc
    if not isinstance(payload, Mapping):
        raise AssertionError(
            "packaged wait-topic terminal JSON must be an object: "
            + _packaged_process_diagnostics(
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
            )
        )
    if returncode != 0 or payload.get("ok") is not True:
        raise AssertionError(
            "packaged wait-topic failed: "
            + _packaged_process_diagnostics(
                returncode=returncode,
                stdout=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                stderr=stderr,
            )
        )
    return dict(payload)


def _packaged_process_diagnostics(
    *,
    returncode: int | None,
    stdout: str,
    stderr: str,
) -> str:
    stdout_tail = stdout.encode("utf-8")[-PACKAGED_GATEWAY_DIAGNOSTIC_BYTES:].decode(
        "utf-8",
        errors="replace",
    )
    stderr_tail = stderr.encode("utf-8")[-PACKAGED_GATEWAY_DIAGNOSTIC_BYTES:].decode(
        "utf-8",
        errors="replace",
    )
    return (
        f"exit={returncode!r} stdout_tail={stdout_tail!r} "
        f"stderr_tail={stderr_tail!r}"
    )


def _complete_transaction(
    runtime: _GatewaySandboxRuntime,
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
    if operation in {"object.delete", "object.setName", "object.setNotes"}:
        object_identity = arguments.get("object")
        assert isinstance(object_identity, Mapping), arguments
        assert object_identity.get("kind") == "id", arguments
        object_id = object_identity.get("value")
        assert isinstance(object_id, str) and object_id, arguments
        scalar_value = arguments.get("value")
        if operation != "object.delete":
            assert isinstance(scalar_value, str), arguments
        preview = create_object_lifecycle_business_preview(
            lambda command: runtime.gateway(
                command,
                live=command[0]
                in {"draft-bind-object", "draft-check", "preview-from-draft"},
            ),
            version=runtime.version,
            operation=operation,
            object_id=object_id,
            new_name=scalar_value if operation == "object.setName" else None,
            notes=scalar_value if operation == "object.setNotes" else None,
        )
    else:
        preview = create_typed_transaction_preview(
            lambda command: runtime.gateway(
                command,
                live=command[0]
                in {"draft-check", "preview-from-draft", "typed-call", "typed-operation"},
            ),
            request,
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

    shown = runtime.gateway(
        ["transaction-show", transaction_id, "--summary-only"],
        live=False,
    )
    confirmation = shown.get("confirmation")
    assert isinstance(confirmation, Mapping), shown
    confirmation_token = confirmation.get("token")
    assert isinstance(confirmation_token, str) and confirmation_token, shown
    confirmed = runtime.gateway(
        ["confirm", transaction_id, "--confirmation-token", confirmation_token],
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
    verification = verified.get("verification")
    assert isinstance(verification, Mapping), verified
    assert verification["operation"] == operation
    assert verification["status"] == TransactionState.VERIFIED.value
    assert verification["ok"] is True
    assert verification["business_state_verified"] is True
    assert all(item["passed"] is True for item in verification["assertions"])

    store = TransactionStore(runtime.state_dir)
    assert store.load(transaction_id).state is TransactionState.VERIFIED
    assert store.load_preview(transaction_id).artifact_hash == artifact_hash
    return {"preview": preview, "execute": executed, "verify": verified}


def _created_object_id(executed: Mapping[str, Any]) -> str:
    dispatch_result = executed.get("dispatch_result")
    assert isinstance(dispatch_result, Mapping), executed
    result = dispatch_result.get("result")
    assert isinstance(result, Mapping), dispatch_result
    object_id = result.get("id")
    assert isinstance(object_id, str) and object_id, result
    return object_id


def _query_one_object_by_id(
    runtime: _GatewaySandboxRuntime,
    object_id: str,
    *,
    fields: Sequence[str],
) -> Mapping[str, Any]:
    command = ["query-object", "--object-id", object_id]
    for field in fields:
        command.extend(("--return-field", field))
    payload = runtime.gateway(command, live=True)
    objects = payload.get("objects")
    assert payload.get("count") == 1, payload
    assert isinstance(objects, list) and len(objects) == 1, payload
    row = objects[0]
    assert isinstance(row, Mapping), payload
    return row


def _assert_query_object_absent(
    runtime: _GatewaySandboxRuntime,
    *,
    selector: Sequence[str],
) -> None:
    assert len(selector) == 2 and selector[0] in {"--object-id", "--path"}, selector
    payload = runtime.gateway(
        [
            "query-object",
            *selector,
            "--return-field",
            "id",
            "--return-field",
            "name",
            "--return-field",
            "type",
            "--return-field",
            "path",
        ],
        live=True,
    )
    assert payload.get("count") == 0, payload
    assert payload.get("objects") == [], payload


def _safe_lock_root(env: Mapping[str, str]) -> Path:
    configured = env.get("WWISE_SANDBOX_ROOT")
    root = Path(configured).expanduser() if configured else REPO_ROOT / DEFAULT_SANDBOX_ROOT
    resolved = root.resolve(strict=False)
    source_project = resolve_sample_project_source(env)
    if source_project is not None:
        source_root = source_project.parent.resolve(strict=False)
        if (
            resolved == source_root
            or path_is_under(resolved, source_root)
            or path_is_under(source_root, resolved)
        ):
            raise SandboxFixtureError("gateway transaction sandbox root must not overlap the immutable SampleProject source")
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
        metadata = path.lstat()
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
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
