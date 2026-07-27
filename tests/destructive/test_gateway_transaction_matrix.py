from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]

from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    path_is_under,
    resolve_sample_project_source,
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
from wwise_waapi.headless import HeadlessLifecycle  # pyright: ignore[reportMissingImports]
from wwise_waapi.operation_registry import OPERATION_REQUEST_CONTRACT  # pyright: ignore[reportMissingImports]
from wwise_waapi.transactions import TransactionState, TransactionStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = REPO_ROOT / "skills" / "waapi-skill" / "scripts" / "gateway.py"
ACTOR_MIXER_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
CONTAINERS_PARENT = r"\Containers\Default Work Unit"

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
    deferred_error: BaseException | None = None
    task_root = tmp_path_factory.mktemp(f"gateway-transaction-{version.replace('.', '-')}")
    state_dir = task_root / "state"

    lock.__enter__()
    try:
        sandbox = prepare_sample_project_sandbox(
            env,
            sandbox_root=lock.root,
            hash_strategy="bounded",
        )
        source_hash_before = _hash_mutation_bearing_project_files(sandbox.source_root)
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

    create = _complete_transaction(
        runtime,
        operation="object.create",
        arguments={
            "parent": {
                "kind": "path",
                "value": CONTAINERS_PARENT if runtime.version == "2025.1" else ACTOR_MIXER_PARENT,
            },
            "type": "ActorMixer",
            "name": object_name,
            "notes": initial_notes,
        },
    )
    created_id = _created_object_id(create["execute"])

    try:
        create_assertions = create["verify"]["verification"]["assertions"]
        assert all(item["passed"] is True for item in create_assertions), create_assertions

        set_name = _complete_transaction(
            runtime,
            operation="object.setName",
            arguments={
                "object": {"kind": "id", "value": created_id},
                "value": renamed_object_name,
            },
        )
        name_assertions = set_name["verify"]["verification"]["assertions"]
        kept_guid = _required_verifier(name_assertions, "renamed object keeps GUID")
        assert str(kept_guid["evidence"]).casefold() == created_id.casefold(), kept_guid
        new_name = _required_verifier(name_assertions, "new name matches")
        assert new_name["evidence"] == renamed_object_name, new_name
        new_path = _required_verifier(name_assertions, "new path ends with name")
        assert str(new_path["evidence"]).rstrip("\\").endswith("\\" + renamed_object_name), new_path
        _required_verifier(name_assertions, "old path no longer resolves to GUID")

        set_notes = _complete_transaction(
            runtime,
            operation="object.setNotes",
            arguments={
                "object": {"kind": "id", "value": created_id},
                "value": updated_notes,
            },
        )
        notes_assertions = set_notes["verify"]["verification"]["assertions"]
        notes_match = _required_verifier(notes_assertions, "notes match exactly")
        assert notes_match["evidence"] == updated_notes, notes_match

        set_property = _complete_transaction(
            runtime,
            operation="object.setProperty",
            arguments={
                "object": {"kind": "id", "value": created_id},
                "property": "Volume",
                "value": expected_volume,
            },
        )
        property_assertions = set_property["verify"]["verification"]["assertions"]
        _required_verifier(property_assertions, "property target resolves exactly once")
        property_match = _required_verifier(
            property_assertions,
            "property value matches metadata type",
        )
        property_evidence = property_match["evidence"]
        assert isinstance(property_evidence, Mapping), property_match
        assert float(property_evidence["actual"]) == pytest.approx(expected_volume), property_evidence
        assert float(property_evidence["expected"]) == pytest.approx(expected_volume), property_evidence

        post_mutation = runtime.gateway(
            [
                "query-object",
                "--object-id",
                created_id,
                "--return-field",
                "id",
                "--return-field",
                "name",
                "--return-field",
                "path",
                "--return-field",
                "notes",
                "--return-field",
                "Volume",
            ],
            live=True,
        )
        assert post_mutation["count"] == 1, post_mutation
        assert len(post_mutation["objects"]) == 1, post_mutation
        row = post_mutation["objects"][0]
        assert str(row["id"]).casefold() == created_id.casefold(), row
        assert row["name"] == renamed_object_name, row
        assert str(row["path"]).rstrip("\\").endswith("\\" + renamed_object_name), row
        assert row["notes"] == updated_notes, row
        assert float(row["Volume"]) == pytest.approx(expected_volume), row
    finally:
        delete = _complete_transaction(
            runtime,
            operation="object.delete",
            arguments={"object": {"kind": "id", "value": created_id}},
        )
        delete_assertions = delete["verify"]["verification"]["assertions"]
        deleted = _required_verifier(delete_assertions, "deleted GUID is absent")
        assert deleted["evidence"] == [], deleted

        final_readback = runtime.gateway(
            ["query-object", "--object-id", created_id, "--return-field", "id"],
            live=True,
        )
        assert final_readback["count"] == 0
        assert final_readback["objects"] == []


@pytest.mark.live
@pytest.mark.destructive
def test_gateway_wait_topic_matches_runner_owned_object_create_and_unsubscribes(
    gateway_sandbox_runtime: _GatewaySandboxRuntime,
) -> None:
    runtime = gateway_sandbox_runtime
    object_name = (
        f"WAAPI_GATEWAY_TOPIC_{runtime.version.replace('.', '_')}_{uuid.uuid4().hex[:12]}"
    )
    event_object_type = "PropertyContainer" if runtime.version == "2025.1" else "ActorMixer"
    created_id: str | None = None
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="waapi-wait-topic") as executor:
            waiting = executor.submit(
                runtime.gateway,
                [
                    "wait-topic",
                    "ak.wwise.core.object.created",
                    "--options-json",
                    '{"return":["id","name","type","path"]}',
                    "--match-json",
                    json.dumps({"object": {"type": event_object_type}}, separators=(",", ":")),
                ],
                live=True,
            )
            # The Wwise process is already ready; this delay gives the separate
            # packaged gateway connection time to establish its subscription.
            time.sleep(0.75)
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
            topic = waiting.result(timeout=45)

        assert topic["command"] == "wait-topic"
        assert topic["topic"] == "ak.wwise.core.object.created"
        assert topic["match"] == {"object": {"type": event_object_type}}
        assert topic["cleanup"] == "unsubscribed"
        event = topic.get("event")
        assert isinstance(event, Mapping), topic
        event_object = event.get("object")
        assert isinstance(event_object, Mapping), event
        assert event_object.get("type") == event_object_type, event_object
        assert str(event_object.get("id", "")).casefold() == created_id.casefold(), event_object
    finally:
        if created_id is not None:
            delete = _complete_transaction(
                runtime,
                operation="object.delete",
                arguments={"object": {"kind": "id", "value": created_id}},
            )
            deleted = _required_verifier(
                delete["verify"]["verification"]["assertions"],
                "deleted GUID is absent",
            )
            assert deleted["evidence"] == [], deleted


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
    assert all(item["passed"] is True for item in verified["verification"]["assertions"])

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


def _required_verifier(
    assertions: Sequence[Mapping[str, Any]],
    name: str,
) -> Mapping[str, Any]:
    matches = [item for item in assertions if item.get("name") == name]
    assert len(matches) == 1, {"name": name, "assertions": assertions}
    match = matches[0]
    assert match.get("passed") is True, match
    return match


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
