from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import uuid
import wave
import xml.etree.ElementTree as ET
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
from tests.destructive.support.category_evidence import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    append_category_evidence,
    exact_git_candidate,
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
from tests.destructive.support.workflow_evidence import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    validate_audio_import_business_evidence,
    validate_soundbank_inclusions_business_evidence,
    validate_switch_assignment_business_evidence,
)
from tests.semantic.support.typed_gateway_input import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    create_object_lifecycle_business_preview,
    create_object_metadata_business_preview,
    create_typed_transaction_preview,
)
from tests.support.host_path_relatives import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    relative_host_path,
)
from tests.semantic.support.codex_project_prelaunch_v3 import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    ProjectPrelaunchRequest,
    WWISE_2025_SOUNDBANK_AURO_PROFILE,
    normalize_project_copy,
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
EVENTS_PARENT = r"\Events\Default Work Unit"
GAME_PARAMETERS_PARENT = r"\Game Parameters\Default Work Unit"
FIXTURE_SWITCH_GROUP_PATH = r"\Switches\SS_Impact\SS_FS_Type"
FIXTURE_SWITCH_PATH = FIXTURE_SWITCH_GROUP_PATH + r"\Crawl"
SWITCH_GROUP_REFERENCE = "SwitchGroupOrStateGroup"
SFX_BUS_ID = "{ED2BCAC8-D7B6-4448-8900-439B557894F4}"

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
    candidate: str
    category_results: list[dict[str, Any]]

    @property
    def port(self) -> int:
        assert self.lifecycle.port is not None
        return self.lifecycle.port

    def gateway(self, command: Sequence[str], *, live: bool) -> dict[str, Any]:
        exit_code, payload = self.raw_gateway(command)
        assert exit_code == 0, json.dumps(payload, ensure_ascii=False, sort_keys=True)
        assert payload["ok"] is True, payload
        if live:
            assert payload["endpoint"] == {
                "host": self.lifecycle.host,
                "port": self.port,
                "url": self.lifecycle.waapi_url,
            }
            assert payload["detected_version"] == self.version
        return payload

    def raw_gateway(
        self,
        command: Sequence[str],
    ) -> tuple[int, dict[str, Any]]:
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
        assert isinstance(payload, dict), payload
        return exit_code, payload

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


@dataclass(slots=True)
class _BusinessDraft:
    draft_id: str
    task_authority: str
    revision: int


def _start_business_draft(
    runtime: _WorkflowSandboxRuntime,
    operation: str,
) -> _BusinessDraft:
    started = runtime.gateway(["draft-start", operation], live=False)
    draft = started.get("draft")
    assert isinstance(draft, Mapping), started
    return _BusinessDraft(
        draft_id=_required_string(draft, "draft_id"),
        task_authority=_required_string(started, "task_authority"),
        revision=int(draft["revision"]),
    )


def _update_business_draft(
    runtime: _WorkflowSandboxRuntime,
    draft: _BusinessDraft,
    command: str,
    arguments: Sequence[str] = (),
    *,
    live: bool,
) -> dict[str, Any]:
    payload = runtime.gateway(
        [
            command,
            draft.draft_id,
            "--task-authority",
            draft.task_authority,
            "--expected-revision",
            str(draft.revision),
            *arguments,
        ],
        live=live,
    )
    projection = payload.get("draft")
    if isinstance(projection, Mapping):
        draft.revision = int(projection["revision"])
    return payload


def _complete_business_draft(
    runtime: _WorkflowSandboxRuntime,
    draft: _BusinessDraft,
) -> dict[str, Mapping[str, Any]]:
    _update_business_draft(runtime, draft, "draft-check", live=True)
    preview = _update_business_draft(
        runtime,
        draft,
        "preview-from-draft",
        live=True,
    )
    transaction_id = _required_string(preview, "transaction_id")
    shown = runtime.gateway(
        ["transaction-show", transaction_id, "--summary-only"],
        live=False,
    )
    confirmation = shown.get("confirmation")
    assert isinstance(confirmation, Mapping), shown
    token = _required_string(confirmation, "token")
    runtime.gateway(
        ["confirm", transaction_id, "--confirmation-token", token],
        live=False,
    )
    executed = runtime.gateway(["execute", transaction_id], live=True)
    verified = runtime.gateway(["verify", transaction_id], live=True)
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value, executed
    assert verified["state"] == TransactionState.VERIFIED.value, verified
    assert verified["verification"]["business_state_verified"] is True, verified
    return {"preview": preview, "execute": executed, "verify": verified}


def _complete_core_result_schema_draft(
    runtime: _WorkflowSandboxRuntime,
    draft: _BusinessDraft,
) -> dict[str, Mapping[str, Any]]:
    """Execute one Core business Draft and retain its explicit weak boundary."""

    _update_business_draft(runtime, draft, "draft-check", live=True)
    preview = _update_business_draft(
        runtime,
        draft,
        "preview-from-draft",
        live=True,
    )
    transaction_id = _required_string(preview, "transaction_id")
    shown = runtime.gateway(
        ["transaction-show", transaction_id, "--summary-only"],
        live=False,
    )
    confirmation = shown.get("confirmation")
    assert isinstance(confirmation, Mapping), shown
    runtime.gateway(
        [
            "confirm",
            transaction_id,
            "--confirmation-token",
            _required_string(confirmation, "token"),
        ],
        live=False,
    )
    executed = runtime.gateway(["execute", transaction_id], live=True)
    verified = runtime.gateway(["verify", transaction_id], live=True)
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value, executed
    assert verified["state"] == "result_schema_checked", verified
    verification = verified.get("verification")
    assert isinstance(verification, Mapping), verified
    assert verification["status"] == "result_schema_checked", verification
    assert verification["business_state_verified"] is False, verification
    return {"preview": preview, "execute": executed, "verify": verified}


def _checked_object_lifecycle_child(
    runtime: _WorkflowSandboxRuntime,
    *,
    operation: str,
    object_id: str,
    value: str,
) -> _BusinessDraft:
    assert operation in {"object.setName", "object.setNotes"}
    draft = _start_business_draft(runtime, operation)
    object_handle = _bind_business_object(
        runtime,
        draft,
        object_id=object_id,
    )
    flag = "--new-name" if operation == "object.setName" else "--notes"
    _update_business_draft(
        runtime,
        draft,
        "draft-declare-object-change",
        ["--object-handle", object_handle, flag, value],
        live=False,
    )
    _update_business_draft(runtime, draft, "draft-check", live=True)
    return draft


def _declare_compound_undo(
    runtime: _WorkflowSandboxRuntime,
    *,
    display_name: str,
    children: Sequence[_BusinessDraft],
) -> _BusinessDraft:
    parent = _start_business_draft(runtime, "waapi.undoGroup")
    child_arguments = [
        value
        for child in children
        for value in (
            "--child-draft",
            child.draft_id,
            child.task_authority,
        )
    ]
    _update_business_draft(
        runtime,
        parent,
        "draft-declare-undo-plan",
        ["--display-name", display_name, *child_arguments],
        live=True,
    )
    return parent


def _bind_business_object(
    runtime: _WorkflowSandboxRuntime,
    draft: _BusinessDraft,
    *,
    object_id: str | None = None,
    path_segments: Sequence[str] = (),
    role: str | None = None,
) -> str:
    assert (object_id is None) != (not path_segments)
    arguments = (
        ["--object-id", object_id]
        if object_id is not None
        else [
            item
            for segment in path_segments
            for item in ("--object-path-segment", segment)
        ]
    )
    payload = _update_business_draft(
        runtime,
        draft,
        "draft-bind-object",
        [*(() if role is None else ("--role", role)), *arguments],
        live=True,
    )
    bound = payload.get("bound_object")
    assert isinstance(bound, Mapping), payload
    return _required_string(bound, "handle")


def _declared_result_handle(payload: Mapping[str, Any], declaration_id: str) -> str:
    draft = payload.get("draft")
    assert isinstance(draft, Mapping), payload
    declarations = draft.get("declarations")
    assert isinstance(declarations, list), draft
    matches = [
        row
        for row in declarations
        if isinstance(row, Mapping) and row.get("declaration_id") == declaration_id
    ]
    assert len(matches) == 1, declarations
    return _required_string(matches[0], "result_handle")


def _discover_business_type(
    runtime: _WorkflowSandboxRuntime,
    draft: _BusinessDraft,
    *,
    meaning: str,
    role: str,
    expected_label: str,
) -> str:
    payload = _update_business_draft(
        runtime,
        draft,
        "draft-discover-types",
        ["--meaning", meaning, "--role", role],
        live=True,
    )
    candidates = payload.get("type_candidates")
    assert isinstance(candidates, list), payload
    matches = [
        row
        for row in candidates
        if isinstance(row, Mapping) and row.get("label") == expected_label
    ]
    assert len(matches) == 1, candidates
    return _required_string(matches[0], "handle")


def _discover_business_field(
    runtime: _WorkflowSandboxRuntime,
    draft: _BusinessDraft,
    *,
    object_handle: str,
    meaning: str,
    platform: str | None = None,
) -> str:
    arguments = ["--object-handle", object_handle, "--meaning", meaning]
    if platform is not None:
        arguments.extend(("--platform", platform))
    payload = _update_business_draft(
        runtime,
        draft,
        "draft-discover-fields",
        arguments,
        live=True,
    )
    candidates = payload.get("field_candidates")
    assert isinstance(candidates, list) and candidates, payload
    return _required_string(candidates[0], "handle")


def _query_exact_path_id(runtime: _WorkflowSandboxRuntime, path: str) -> str:
    payload = runtime.gateway(
        [
            "query-object",
            "--path",
            path,
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
    rows = payload.get("objects")
    assert payload.get("count") == 1 and isinstance(rows, list), payload
    assert len(rows) == 1 and isinstance(rows[0], Mapping), rows
    assert rows[0].get("path") == path, rows[0]
    return _required_string(rows[0], "id")


def _restart_workflow_host_after_transport_loss(
    runtime: _WorkflowSandboxRuntime,
) -> None:
    """Restore the module host without retrying the indeterminate operation."""

    port = runtime.port
    shutdown_sandboxed_wwise(runtime.lifecycle, runtime.sandbox)
    replacement = launch_sandboxed_wwise(
        runtime.sandbox,
        runtime.env,
        port=port,
    )
    assert replacement.port == port
    runtime.lifecycle = replacement


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
    source_hash_after: tuple[str, int, int] | None = None
    source_tree_after: tuple[str, int] | None = None
    deferred_error: BaseException | None = None
    runtime: _WorkflowSandboxRuntime | None = None
    task_root = tmp_path_factory.mktemp(f"gateway-workflows-{version.replace('.', '-')}")
    case_sandbox_root = lock.root / f"gateway-workflows-{uuid.uuid4().hex}"
    state_dir = task_root / "state"
    candidate = exact_git_candidate(REPO_ROOT)
    category_results: list[dict[str, Any]] = []

    lock.__enter__()
    try:
        sandbox = prepare_sample_project_sandbox(
            env,
            sandbox_root=case_sandbox_root,
            hash_strategy="bounded",
        )
        source_hash_before = _hash_mutation_bearing_project_files(sandbox.source_root)
        source_tree_before = _source_tree_inventory(sandbox.source_root)
        assert source_hash_before[1] > 0, "immutable SampleProject source has no .wproj/.wwu files to hash"
        if version == "2025.1":
            prelaunch_io_root = case_sandbox_root / "prelaunch-io"
            prelaunch_io_root.mkdir(parents=True, exist_ok=False)
            prelaunch = normalize_project_copy(
                sandbox.sandbox_project,
                io_root=prelaunch_io_root,
                owned_root=case_sandbox_root,
                request=ProjectPrelaunchRequest(
                    scenario_id="gateway-workflow-transaction-matrix",
                    auro_isolation_profile=WWISE_2025_SOUNDBANK_AURO_PROFILE,
                ),
            )
            assert prelaunch.auro_soundbank_isolation is not None
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
        runtime = _WorkflowSandboxRuntime(
            version=version,
            sandbox=sandbox,
            lifecycle=lifecycle,
            state_dir=state_dir,
            env=gateway_env,
            candidate=candidate,
            category_results=category_results,
        )
        yield runtime
    finally:
        active_lifecycle = runtime.lifecycle if runtime is not None else lifecycle
        if active_lifecycle is not None and sandbox is not None:
            try:
                shutdown_sandboxed_wwise(active_lifecycle, sandbox)
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

        if case_sandbox_root.exists():
            try:
                shutil.rmtree(case_sandbox_root)
            except BaseException as exc:  # noqa: BLE001 - lock release must still run
                deferred_error = deferred_error or exc

        if sandbox is not None and active_lifecycle is not None:
            if not any(item.get("category") == "authoring-ui" for item in category_results):
                category_results.append(
                    {
                        "category": "authoring-ui",
                        "status": "blocked",
                        "verifier_strength": "host_unavailable",
                        "reason": "configured matching host is WwiseConsole, not Wwise Authoring",
                    }
                )
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
    definition_event_id: str | None = None
    switch_container_id: str | None = None
    switch_group_id: str | None = None
    switch_id: str | None = None
    assignment_child_id: str | None = None

    try:
        runtime.packaged_status()
        if runtime.version == "2021.1":
            _save_sandbox_project(runtime)
        import_name = f"WAAPI_GATEWAY_AUDIO_{runtime.version.replace('.', '_')}_{unique_suffix}"
        audio_file = _write_fixture_wav(runtime.sandbox.sandbox_path / "GatewayWorkflowAudio", import_name)
        assert path_is_under(audio_file.resolve(strict=True), runtime.sandbox.sandbox_path.resolve(strict=True))
        requested_object_path = f"{object_parent}\\<Sound>{import_name}"
        import_notes = f"closed gateway audio import {import_name}"
        audio_import = _complete_transaction(
            runtime,
            operation="audio.import",
            arguments={
                "imports": [
                    {
                        "object_path": requested_object_path,
                        "audio_file": str(audio_file),
                        "object_type": "Sound",
                        "import_language": "SFX",
                        "notes": import_notes,
                    }
                ]
            },
        )
        imported_row = _imported_object(audio_import["execute"], requested_object_path)
        imported_id = _required_string(imported_row, "id")
        imported_path = _required_string(imported_row, "path")
        assert imported_path == _untyped_object_path(requested_object_path), imported_row
        validate_audio_import_business_evidence(
            execution=audio_import["execute"],
            verification=audio_import["verification_evidence"],
            version=runtime.version,
            expected_target_path=imported_path,
            expected_target_id=imported_id,
            expected_notes=import_notes,
            source_file=audio_file,
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
        validate_soundbank_inclusions_business_evidence(
            inclusions_add["verification_evidence"],
            soundbank_id=soundbank_id,
            expected=[
                {"object": included_id.casefold(), "filters": ["media", "structures"]}
            ],
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
        validate_soundbank_inclusions_business_evidence(
            inclusions_union["verification_evidence"],
            soundbank_id=soundbank_id,
            expected=[{"object": included_id.casefold(), "filters": ["events"]}],
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
        validate_soundbank_inclusions_business_evidence(
            inclusions_preserve["verification_evidence"],
            soundbank_id=soundbank_id,
            expected=[
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
        validate_soundbank_inclusions_business_evidence(
            inclusions_remove["verification_evidence"],
            soundbank_id=soundbank_id,
            expected=[
                {"object": included_second_id.casefold(), "filters": ["media"]}
            ],
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
        validate_soundbank_inclusions_business_evidence(
            inclusions_replace["verification_evidence"],
            soundbank_id=soundbank_id,
            expected=[
                {
                    "object": included_id.casefold(),
                    "filters": ["events", "structures"],
                }
            ],
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
        validate_soundbank_inclusions_business_evidence(
            inclusions_clear["verification_evidence"],
            soundbank_id=soundbank_id,
            expected=[],
        )

        _save_sandbox_project(runtime)
        # SoundBank file authority must own both the active sandbox project and
        # every exact input/output artifact.  The sandbox is already unique to
        # this test attempt, so it is the narrowest valid I/O root.
        soundbank_io_root = runtime.sandbox.sandbox_root
        soundbank_name = (
            f"WAAPI_GATEWAY_BANK_{runtime.version.replace('.', '_')}_{unique_suffix}"
        )
        _complete_transaction(
            runtime,
            operation="soundbank.generate",
            arguments={
                "soundbanks": [
                    {
                        "name": soundbank_name,
                        "artifact_expectation": "nonlocalized",
                        "rebuild": False,
                    }
                ],
                "platforms": ["Windows"],
                "skip_languages": True,
                "write_to_disk": True,
                "io_root": str(soundbank_io_root),
                "rebuild_soundbanks": False,
                "clear_audio_file_cache": False,
                "rebuild_init_bank": False,
            },
        )

        external_media_root = soundbank_io_root / "external-media"
        external_audio = _write_fixture_wav(
            external_media_root,
            f"WAAPI_GATEWAY_EXTERNAL_{unique_suffix}",
        )
        source_list = soundbank_io_root / "gateway-external.wsources"
        destination = f"Gateway/{unique_suffix}.wav"
        _write_external_sources_document(
            source_list,
            media_root=external_media_root,
            project_root=runtime.sandbox.sandbox_path,
            source_file=external_audio,
            destination=destination,
        )
        external_output = soundbank_io_root / "external-output"
        _complete_transaction(
            runtime,
            operation="soundbank.convertExternalSources",
            arguments={
                "sources": [
                    {
                        "input": str(source_list),
                        "platform": "Windows",
                        "output": str(external_output),
                    }
                ],
                "io_root": str(soundbank_io_root),
            },
        )

        definition_event_name = f"WAAPI_GATEWAY_EVENT_{unique_suffix}"
        definition_event_id = _create_object(
            runtime,
            parent=EVENTS_PARENT,
            object_type="Event",
            name=definition_event_name,
        )
        definition_file = soundbank_io_root / "gateway-banks.tsv"
        definition_identity = (
            definition_event_id
            if runtime.version == "2022.1"
            else f'"{definition_event_name}"'
        )
        definition_file.write_text(
            f"{soundbank_name}\t{definition_identity}\tEvent\tStructure\tMedia\n",
            encoding="utf-8",
            newline="\n",
        )
        _save_sandbox_project(runtime)
        _complete_transaction(
            runtime,
            operation="soundbank.processDefinitionFiles",
            arguments={
                "files": [str(definition_file)],
                "io_root": str(soundbank_io_root),
            },
        )

        switch_container_id = _create_object(
            runtime,
            parent=object_parent,
            object_type="SwitchContainer",
            name=f"WAAPI_GATEWAY_SC_{runtime.version.replace('.', '_')}_{unique_suffix}",
        )
        switch_group_id = _query_exact_path_id(
            runtime,
            FIXTURE_SWITCH_GROUP_PATH,
        )
        switch_id = _query_exact_path_id(runtime, FIXTURE_SWITCH_PATH)
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
        validate_switch_assignment_business_evidence(
            add_assignment["verification_evidence"],
            switch_container_id=switch_container_id,
            switch_group_id=switch_group_id,
            child_id=assignment_child_id,
            state_or_switch_id=switch_id,
            should_exist=True,
        )

        remove_assignment = _complete_transaction(
            runtime,
            operation="switchContainer.removeAssignment",
            arguments=assignment_arguments,
        )
        validate_switch_assignment_business_evidence(
            remove_assignment["verification_evidence"],
            switch_container_id=switch_container_id,
            switch_group_id=switch_group_id,
            child_id=assignment_child_id,
            state_or_switch_id=switch_id,
            should_exist=False,
        )
        runtime.category_results.extend(
            [
                {"category": "object-topology", "status": "PASS", "verifier_strength": "operation_specific_readback"},
                {"category": "scalar-reference-link", "status": "PASS", "verifier_strength": "operation_specific_readback"},
                {"category": "relationship", "status": "PASS", "verifier_strength": "operation_specific_readback"},
                {"category": "soundbank-file-artifact", "status": "PASS", "verifier_strength": "operation_specific_readback"},
            ]
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
            definition_event_id,
            assignment_child_id,
            switch_container_id,
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


@pytest.mark.live
@pytest.mark.destructive
def test_media_build_business_reads_across_selected_version(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    runtime = workflow_sandbox_runtime
    if runtime.version not in {"2022.1", "2025.1"}:
        pytest.skip("Media/build business evidence targets Wwise 2022.1 and 2025.1")
    object_parent = (
        CONTAINERS_PARENT if runtime.version == "2025.1" else ACTOR_MIXER_PARENT
    )
    suffix = uuid.uuid4().hex[:12]
    imported_id: str | None = None
    included_id: str | None = None
    soundbank_id: str | None = None
    try:
        runtime.packaged_status()
        import_name = f"WAAPI_MEDIA_BUILD_{runtime.version.replace('.', '_')}_{suffix}"
        audio_file = _write_fixture_wav(
            runtime.sandbox.sandbox_path / "MediaBuildAudio",
            import_name,
        )
        requested_object_path = f"{object_parent}\\<Sound>{import_name}"
        import_notes = f"media/build business read fixture {import_name}"
        audio_import = _complete_transaction(
            runtime,
            operation="audio.import",
            arguments={
                "imports": [
                    {
                        "object_path": requested_object_path,
                        "audio_file": str(audio_file),
                        "object_type": "Sound",
                        "import_language": "SFX",
                        "notes": import_notes,
                    }
                ]
            },
        )
        imported_row = _imported_object(audio_import["execute"], requested_object_path)
        imported_id = _required_string(imported_row, "id")
        imported_path = _required_string(imported_row, "path")
        validate_audio_import_business_evidence(
            execution=audio_import["execute"],
            verification=audio_import["verification_evidence"],
            version=runtime.version,
            expected_target_path=imported_path,
            expected_target_id=imported_id,
            expected_notes=import_notes,
            source_file=audio_file,
        )
        audio_source_id = _imported_audio_source_id(
            audio_import["verification_evidence"],
            expected_path=f"{imported_path}\\{audio_file.stem}",
        )

        for api, extra in (
            (
                "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInRegion",
                ["--start-seconds", "0", "--end-seconds", "0.1"],
            ),
            (
                "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInTrimmedRegion",
                [],
            ),
        ):
            peaks = runtime.gateway(
                [
                    "core-call",
                    api,
                    "--audio-source-id",
                    audio_source_id,
                    "--peak-pair-count",
                    "8",
                    "--channel-mode",
                    "cross-channel",
                    *extra,
                ],
                live=True,
            )
            assert peaks["agent_result"]["channel_count"] == 1
            assert peaks["agent_result"]["peak_pair_count"] == 8
            assert len(peaks["agent_result"]["channels"][0]["pairs_normalized"]) == 8

        if runtime.version == "2025.1":
            media_pool = runtime.gateway(
                [
                    "core-call",
                    "ak.wwise.core.mediaPool.get",
                    "--max-results",
                    "200",
                    "--include-field",
                    "filename",
                    "--include-field",
                    "duration-seconds",
                    "--exact-name-contains",
                    import_name,
                    "--final-limit",
                    "1",
                ],
                live=True,
            )
            assert media_pool["agent_result"]["complete"] is True
            assert media_pool["agent_result"]["returned_count"] == 1
            assert media_pool["agent_result"]["items"][0]["values"]["filename"] == (
                import_name
            )

        included_name = f"WAAPI_MEDIA_INCLUDED_{suffix}"
        included_id = _create_object(
            runtime,
            parent=object_parent,
            object_type="ActorMixer",
            name=included_name,
        )
        soundbank_id = _create_object(
            runtime,
            parent=SOUNDBANK_PARENT,
            object_type="SoundBank",
            name=f"WAAPI_MEDIA_BANK_{suffix}",
        )
        set_inclusions = _complete_transaction(
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
        validate_soundbank_inclusions_business_evidence(
            set_inclusions["verification_evidence"],
            soundbank_id=soundbank_id,
            expected=[
                {
                    "object": included_id.casefold(),
                    "filters": ["events", "structures"],
                }
            ],
        )
        inclusions = runtime.gateway(
            [
                "core-call",
                "ak.wwise.core.soundbank.getInclusions",
                "--soundbank-id",
                soundbank_id,
            ],
            live=True,
        )
        assert inclusions["agent_result"]["contract"] == (
            "waapi-skill.media-build-result/v1"
        )
        assert inclusions["agent_result"]["kind"] == "soundbank_inclusions"
        assert inclusions["agent_result"]["count"] == 1
        inclusion_row = inclusions["agent_result"]["inclusions"][0]
        assert {
            key: inclusion_row[key]
            for key in ("object_id", "name", "path", "includes")
        } == {
            "object_id": included_id.upper(),
            "name": included_name,
            "path": f"{object_parent}\\{included_name}",
            "includes": ["events", "structures"],
        }
        assert inclusion_row["type"] == (
            "PropertyContainer" if runtime.version == "2025.1" else "ActorMixer"
        )
        runtime.category_results.append(
            {
                "category": "media-build-business-read",
                "status": "PASS",
                "verifier_strength": (
                    "region_trimmed_peaks_soundbank_inclusions_and_media_pool"
                    if runtime.version == "2025.1"
                    else "region_trimmed_peaks_and_soundbank_inclusions"
                ),
            }
        )
    finally:
        active_error = sys.exc_info()[1]
        cleanup_errors: list[str] = []
        for object_id in (soundbank_id, included_id, imported_id):
            if object_id is None:
                continue
            try:
                _delete_if_present_via_transaction(runtime, object_id)
            except BaseException as exc:  # noqa: BLE001 - clean every owned object
                cleanup_errors.append(
                    f"{object_id}: {type(exc).__name__}: {exc}"
                )
        if cleanup_errors:
            message = "media/build workflow cleanup failures: " + "; ".join(
                cleanup_errors
            )
            if active_error is not None:
                active_error.add_note(message)
            else:
                raise AssertionError(message)


@pytest.mark.live
@pytest.mark.destructive
def test_remaining_core_business_effect_families_on_2025(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Prove one strong project-setting effect and one weak external effect."""

    runtime = workflow_sandbox_runtime
    if runtime.version != "2025.1":
        pytest.skip("Remaining Core real evidence targets Wwise 2025.1")
    game_parameter_id: str | None = None
    try:
        runtime.packaged_status()
        game_parameter_id = _create_object(
            runtime,
            parent=GAME_PARAMETERS_PARENT,
            object_type="GameParameter",
            name=f"WAAPI_RANGE_{uuid.uuid4().hex[:12]}",
        )
        range_draft = _start_business_draft(
            runtime,
            "ak.wwise.core.gameParameter.setRange",
        )
        game_parameter_handle = _bind_business_object(
            runtime,
            range_draft,
            object_id=game_parameter_id,
            role="game_parameter",
        )
        _update_business_draft(
            runtime,
            range_draft,
            "draft-declare-project-setting-plan",
            [
                "--game-parameter-handle",
                game_parameter_handle,
                "--minimum",
                "-10",
                "--maximum",
                "100",
                "--curve-update-outcome",
                "stretch",
            ],
            live=True,
        )
        range_result = _complete_business_draft(runtime, range_draft)
        range_verification = range_result["verify"]["verification"]
        assert range_verification["verification_strength"] == (
            "operation_specific_readback"
        )
        assert range_verification["business_state_verified"] is True

        source_files_draft = _start_business_draft(
            runtime,
            "ak.wwise.core.sourceControl.getSourceFiles",
        )
        _update_business_draft(
            runtime,
            source_files_draft,
            "draft-declare-source-control-plan",
            [
                "--usage-scope",
                "all",
                "--no-recursive",
                "--no-usage-objects",
                "--max-results",
                "5",
            ],
            live=True,
        )
        source_files_result = _complete_core_result_schema_draft(
            runtime,
            source_files_draft,
        )
        agent_result = source_files_result["verify"].get("agent_result")
        assert isinstance(agent_result, Mapping), source_files_result
        projected = agent_result.get("result")
        assert isinstance(projected, Mapping), agent_result
        assert projected["max_results"] == 5
        assert projected["returned_count"] <= 5
        assert projected["returned_count"] <= projected["total_count"]
        runtime.category_results.extend(
            (
                {
                    "category": "remaining-core-project-setting",
                    "status": "PASS",
                    "verifier_strength": "operation_specific_readback",
                },
                {
                    "category": "remaining-core-source-control",
                    "status": "PASS",
                    "verifier_strength": "result_schema_only",
                },
            )
        )
    finally:
        if game_parameter_id is not None:
            _delete_if_present_via_transaction(runtime, game_parameter_id)


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_inspection_business_profiler_and_transport_lifecycle(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Prove the public runtime seam without inventing a Remote target."""

    runtime = workflow_sandbox_runtime
    if runtime.version not in {"2022.1", "2025.1"}:
        pytest.skip("Runtime-inspection business evidence targets Wwise 2022.1 and 2025.1")
    runtime.packaged_status()
    cursor = runtime.gateway(
        [
            "core-call",
            "ak.wwise.core.profiler.getCursorTime",
            "--profiler-cursor",
            "user-cursor",
        ],
        live=True,
    )
    cursor_result = cursor.get("agent_result")
    assert isinstance(cursor_result, Mapping), cursor
    assert cursor_result["profiler_cursor"] == "user-cursor"
    assert isinstance(cursor_result["available"], bool)
    assert (
        isinstance(cursor_result["position_ms"], int)
        if cursor_result["available"]
        else cursor_result["position_ms"] is None
    )

    profiler_draft = _start_business_draft(
        runtime,
        "ak.wwise.core.profiler.enableProfilerData",
    )
    _update_business_draft(
        runtime,
        profiler_draft,
        "draft-declare-runtime-control-plan",
        ["--capture-data", "voices", "enable"],
        live=True,
    )
    profiler_result = _complete_core_result_schema_draft(
        runtime,
        profiler_draft,
    )
    assert profiler_result["verify"]["verification"]["business_state_verified"] is False

    authoring_only = ["ak.wwise.core.transport.create"]
    if runtime.version == "2022.1":
        authoring_only.append("ak.wwise.core.remote.connect")
    for operation in authoring_only:
        draft = _start_business_draft(runtime, operation)
        code, boundary = runtime.raw_gateway(
            [
                "draft-declare-runtime-control-plan",
                draft.draft_id,
                "--task-authority",
                draft.task_authority,
                "--expected-revision",
                str(draft.revision),
            ]
        )
        assert code == 2, boundary
        assert boundary["error_code"] == "AUTHORING_HOST_REQUIRED", boundary
        assert boundary["executed"] is False, boundary
        assert boundary["details"] == {
            "is_command_line": True,
            "required_host": "wwise-authoring",
        }

    runtime.category_results.extend(
        (
            {
                "category": "runtime-profiler-business",
                "status": "PASS",
                "verifier_strength": "bounded_read_and_result_schema",
            },
            {
                "category": "runtime-authoring-host-boundary",
                "status": "PASS",
                "verifier_strength": "pre_dispatch_explicit_boundary",
            },
        )
    )


@pytest.mark.live
@pytest.mark.destructive
def test_soundengine_business_draft_is_real_and_result_schema_bounded(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Exercise the public SoundEngine business Draft without overstating effect."""

    runtime = workflow_sandbox_runtime
    api = "ak.soundengine.postMsgMonitor"
    schema = runtime.gateway(["request-schema", api], live=False)
    assert schema["input_shape"] == "business_declaration", schema
    assert schema["business_adapter"]["legacy_typed_call_public"] is False, schema
    assert "fields" not in schema, schema
    message = f"waapi-skill result-schema probe {runtime.version}"
    draft = _start_business_draft(runtime, api)
    _update_business_draft(
        runtime,
        draft,
        "draft-declare-soundengine-plan",
        ["--monitor-message", message],
        live=True,
    )
    _update_business_draft(runtime, draft, "draft-check", live=True)
    preview = _update_business_draft(
        runtime,
        draft,
        "preview-from-draft",
        live=True,
    )
    transaction_id = _required_string(preview, "transaction_id")
    artifact = TransactionStore(runtime.state_dir).load_preview(
        transaction_id
    ).artifact
    assert artifact["request"]["arguments"] == {
        "api": api,
        "args": {"message": message},
        "options": {},
    }, artifact
    shown = runtime.gateway(
        ["transaction-show", transaction_id, "--summary-only"],
        live=False,
    )
    confirmation = shown.get("confirmation")
    assert isinstance(confirmation, Mapping), shown
    runtime.gateway(
        [
            "confirm",
            transaction_id,
            "--confirmation-token",
            _required_string(confirmation, "token"),
        ],
        live=False,
    )
    execute_code, executed = runtime.raw_gateway(["execute", transaction_id])
    if execute_code == 2:
        dispatch_result = executed.get("dispatch_result")
        assert isinstance(dispatch_result, Mapping), executed
        assert dispatch_result["waapi_error_uri"] == "ak.wwise.unavailable", executed
        assert executed["state"] == TransactionState.INDETERMINATE.value, executed
        assert executed["automatic_retry"] is False, executed
        runtime.category_results.append(
            {
                "category": "cli-soundengine",
                "status": "blocked",
                "verifier_strength": "business_draft_then_explicit_host_boundary",
                "reason": "WwiseConsole returned ak.wwise.unavailable",
            }
        )
        return
    assert execute_code == 0, json.dumps(executed, ensure_ascii=False, sort_keys=True)
    verified = runtime.gateway(["verify", transaction_id], live=True)
    assert verified["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verified["verified"] is False
    runtime.category_results.append(
        {
            "category": "cli-soundengine",
            "status": "PASS",
            "verifier_strength": "business_draft_and_result_schema_only",
        }
    )


@pytest.mark.live
@pytest.mark.destructive
def test_cli_console_business_build_and_project_verifier_shapes(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Exercise the deep CLI/Console seam across its distinct real oracles."""

    runtime = workflow_sandbox_runtime
    project_file = str(runtime.sandbox.sandbox_project)
    output_root = runtime.sandbox.sandbox_root / "cli-console-business-output"
    output_root.mkdir(parents=True, exist_ok=False)

    verify_api = "ak.wwise.cli.verify"
    verify_schema = runtime.gateway(["request-schema", verify_api], live=False)
    assert verify_schema["input_shape"] == "business_declaration", verify_schema
    assert verify_schema["native_request_fields_disclosed"] is False, verify_schema
    verify_draft = _start_business_draft(runtime, verify_api)
    _update_business_draft(
        runtime,
        verify_draft,
        "draft-declare-cli-console-plan",
        [
            "--value", "project_file", project_file,
            "--value", "verbosity", "quiet",
        ],
        live=True,
    )
    verify_result = _complete_core_result_schema_draft(runtime, verify_draft)
    assert verify_result["verify"]["verification"]["business_state_verified"] is False

    dump_file = output_root / f"objects-{runtime.version}.txt"
    dump_api = "ak.wwise.cli.dumpObjects"
    dump_draft = _start_business_draft(runtime, dump_api)
    _update_business_draft(
        runtime,
        dump_draft,
        "draft-declare-cli-console-plan",
        [
            "--value", "project_file", project_file,
            "--value", "output_file", str(dump_file),
            "--value", "content", "property_sets",
            "--toggle", "include_session_objects", "disable",
        ],
        live=True,
    )
    dump_result = _complete_core_result_schema_draft(runtime, dump_draft)
    assert dump_file.is_file(), dump_result
    assert dump_file.stat().st_size > 0

    generated_root = output_root / "generated"
    generated_banks = generated_root / "Windows"
    generated_root.mkdir()
    generate_api = "ak.wwise.cli.generateSoundbank"
    generate_draft = _start_business_draft(runtime, generate_api)
    _update_business_draft(
        runtime,
        generate_draft,
        "draft-declare-cli-console-plan",
        [
            "--value", "project_file", project_file,
            "--item", "platforms", "Windows",
            "--toggle", "skip_languages", "enable",
            "--value", "source_control", "disabled",
            "--value", "root_output_directory", str(generated_root),
            "--mapping", "soundbank_directories_by_platform", "Windows", str(generated_banks),
            "--value", "verbosity", "quiet",
        ],
        live=True,
    )
    generate_result = _complete_core_result_schema_draft(runtime, generate_draft)
    generated_files = tuple(generated_root.rglob("*.bnk"))
    assert generated_files, generate_result

    categories = [
        {
            "category": "cli-console-business-result-schema",
            "status": "PASS",
            "verifier_strength": "project_verify_plus_exact_file_and_soundbank_oracles",
        }
    ]
    if runtime.version in {"2023.1", "2024.1", "2025.1"}:
        open_api = "ak.wwise.console.project.open"
        open_draft = _start_business_draft(runtime, open_api)
        _update_business_draft(
            runtime,
            open_draft,
            "draft-declare-cli-console-plan",
            [
                "--value", "project_file", project_file,
                "--toggle", "auto_checkout", "disable",
                "--value", "migration_policy", "fail",
            ],
            live=True,
        )
        opened = _complete_business_draft(runtime, open_draft)
        assert opened["verify"]["verification"]["business_state_verified"] is True
        categories.append(
            {
                "category": "cli-console-project-transition",
                "status": "PASS",
                "verifier_strength": "result_schema_and_project_transition",
            }
        )
    runtime.category_results.extend(categories)


@pytest.mark.live
@pytest.mark.destructive
def test_exact_inline_lua_is_result_schema_only_or_explicitly_host_blocked(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Exercise the closed 2025 inline-code route without claiming its side effects."""

    runtime = workflow_sandbox_runtime
    if runtime.version != "2025.1":
        pytest.skip("lua.executeCoreInline is reflected only in Wwise 2025.1")
    _complete_result_schema_operation(
        runtime,
        operation="lua.executeCoreInline",
        arguments={
            "lua_code": "return { waapi_skill_probe = 'ok' }\n",
            "io_root": str(runtime.sandbox.sandbox_path),
            "source_authority": "user_supplied_verbatim",
        },
        category="lua-inline-code",
    )


@pytest.mark.live
@pytest.mark.destructive
def test_exact_lua_file_business_drafts_preserve_source_and_loader_boundary(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Exercise both file loaders through their sole exact-artifact ingress."""

    runtime = workflow_sandbox_runtime
    if runtime.version not in {"2023.1", "2025.1"}:
        pytest.skip("representative Lua file shapes use Wwise 2023.1 and 2025.1")
    root = runtime.sandbox.sandbox_path / "GatewayExactLua"
    root.mkdir()
    scripts = {
        "lua.executeCoreFile": root / "core-exact.lua",
        "lua.executeCliFile": root / "cli-exact.lua",
    }
    scripts["lua.executeCoreFile"].write_bytes(
        b"return { profile = 'core-file', count = wa_args.count }\n"
    )
    scripts["lua.executeCliFile"].write_bytes(
        b"return { profile = 'cli-file', count = wa_args.count }\n"
    )
    before = {
        operation: hashlib.sha256(path.read_bytes()).hexdigest()
        for operation, path in scripts.items()
    }
    for operation, script in scripts.items():
        arguments: dict[str, Any] = {
            "script_file": str(script),
            "io_root": str(root),
            "source_authority": "user_supplied_verbatim",
            "wa_args": {"count": 3},
        }
        if operation == "lua.executeCliFile" and runtime.version == "2025.1":
            arguments["watchdog_seconds"] = 30
        _complete_result_schema_operation(
            runtime,
            operation=operation,
            arguments=arguments,
            category=operation,
        )
    assert {
        operation: hashlib.sha256(path.read_bytes()).hexdigest()
        for operation, path in scripts.items()
    } == before


@pytest.mark.live
@pytest.mark.destructive
def test_exact_tab_import_business_draft_binds_location_and_preserves_table(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Exercise the sole tabular-import business seam on a disposable row."""

    runtime = workflow_sandbox_runtime
    object_parent = (
        CONTAINERS_PARENT if runtime.version == "2025.1" else ACTOR_MIXER_PARENT
    )
    suffix = uuid.uuid4().hex[:12]
    name = f"WAAPI_TAB_BUSINESS_{suffix}"
    root = runtime.sandbox.sandbox_path / "GatewayExactTab"
    audio_file = _write_fixture_wav(root, name)
    table_file = root / "exact-import.tsv"
    requested_path = f"{object_parent}\\<Sound SFX>{name}"
    table_file.write_text(
        "Audio File\tObject Path\tObject Type\n"
        f"{audio_file}\t{requested_path}\tSound SFX\n",
        encoding="utf-8",
        newline="\n",
    )
    table_sha256 = hashlib.sha256(table_file.read_bytes()).hexdigest()
    imported_id: str | None = None
    try:
        location_id = _query_exact_path_id(runtime, object_parent)
        result = _complete_transaction(
            runtime,
            operation="audio.importTabDelimited",
            arguments={
                "import_file": str(table_file),
                "import_location": {"kind": "id", "value": location_id},
                "import_language": "SFX",
                "import_operation": "createNew",
            },
        )
        imported = _imported_object(result["execute"], requested_path)
        imported_id = _required_string(imported, "id")
        assert _required_string(imported, "path") == _untyped_object_path(
            requested_path
        )
        assert hashlib.sha256(table_file.read_bytes()).hexdigest() == table_sha256
    finally:
        if imported_id is not None:
            _delete_if_present_via_transaction(runtime, imported_id)
    runtime.category_results.append(
        {
            "category": "audio-import-tab-delimited",
            "status": "PASS",
            "verifier_strength": "exact_guid_path_and_cleanup",
        }
    )


def _complete_result_schema_operation(
    runtime: _WorkflowSandboxRuntime,
    *,
    operation: str,
    arguments: Mapping[str, Any],
    category: str,
) -> None:
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": runtime.version,
        "operation": operation,
        "arguments": dict(arguments),
    }
    preview = create_typed_transaction_preview(
        lambda command: runtime.gateway(
            command,
            live=command[0] in {"draft-check", "preview-from-draft"},
        ),
        request,
    )
    transaction_id = preview.get("transaction_id")
    assert isinstance(transaction_id, str) and transaction_id, preview
    shown = runtime.gateway(
        ["transaction-show", transaction_id, "--summary-only"],
        live=False,
    )
    confirmation = shown.get("confirmation")
    assert isinstance(confirmation, Mapping), shown
    token = confirmation.get("token")
    assert isinstance(token, str) and token, shown
    runtime.gateway(
        ["confirm", transaction_id, "--confirmation-token", token],
        live=False,
    )
    execute_argv = [
        "--host",
        runtime.lifecycle.host,
        "--port",
        str(runtime.port),
        "--version",
        runtime.version,
        "--timeout",
        "30",
        "--state-dir",
        str(runtime.state_dir),
        "execute",
        transaction_id,
    ]
    execute_code, executed = waapi_gateway.execute_gateway(
        execute_argv,
        env=runtime.env,
    )
    if execute_code == 2:
        dispatch_result = executed.get("dispatch_result")
        assert isinstance(dispatch_result, Mapping), executed
        assert executed["state"] == TransactionState.INDETERMINATE.value, executed
        assert executed["automatic_retry"] is False, executed
        unavailable = dispatch_result.get("waapi_error_uri") == "ak.wwise.unavailable"
        if not unavailable:
            assert operation == "lua.executeCliFile", executed
        runtime.category_results.append(
            {
                "category": category,
                "status": "blocked",
                "verifier_strength": "host_unavailable",
                "reason": (
                    "matching WwiseConsole returned ak.wwise.unavailable"
                    if unavailable
                    else "CLI Lua transport ended with one non-retry indeterminate result"
                ),
            }
        )
        if not unavailable:
            _restart_workflow_host_after_transport_loss(runtime)
        return
    assert execute_code == 0, json.dumps(executed, ensure_ascii=False, sort_keys=True)
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value, executed
    verified = runtime.gateway(["verify", transaction_id], live=True)
    assert verified["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value, verified
    assert verified["verified"] is False, verified
    verification = verified.get("verification")
    assert isinstance(verification, Mapping), verified
    assert verification["business_state_verified"] is False, verification
    assert verification["verification_strength"] in {
        "result_schema_only",
        "complete_reflected_schema",
        "partial_reflected_schema",
    }, verification
    runtime.category_results.append(
        {
            "category": category,
            "status": "PASS",
            "verifier_strength": "result_schema_only",
        }
    )


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
    if operation in {
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
    }:
        preview = _create_switch_assignment_business_preview(
            runtime,
            operation=operation,
            arguments=arguments,
        )
    else:
        preview = create_typed_transaction_preview(
            lambda command: runtime.gateway(
                command,
                live=command[0]
                in {
                    "draft-check",
                    "preview-from-draft",
                    "typed-call",
                    "typed-operation",
                },
            ),
            request,
        )
    assert preview["status"] == TransactionState.AWAITING_CONFIRMATION.value
    assert preview["state"] == TransactionState.AWAITING_CONFIRMATION.value
    preview_request = preview["preview_summary"]["request"]
    if operation == "audio.import":
        canonical_imports = []
        for row in request["arguments"]["imports"]:
            canonical_row = dict(row)
            canonical_row["object_path"] = canonical_row["object_path"].replace(
                r"\<Sound>",
                r"\<Sound SFX>",
            )
            canonical_row["object_type"] = "Sound SFX"
            canonical_imports.append(canonical_row)
        assert preview_request == {
            **request,
            "arguments": {
                "imports": canonical_imports,
            },
        }
    else:
        assert preview_request == request
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
    stdout_verification = verified.get("verification")
    assert isinstance(stdout_verification, Mapping), verified
    assert stdout_verification["operation"] == operation
    assert stdout_verification["status"] == TransactionState.VERIFIED.value
    assert stdout_verification["ok"] is True
    assert stdout_verification["business_state_verified"] is True

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


def _create_switch_assignment_business_preview(
    runtime: _WorkflowSandboxRuntime,
    *,
    operation: str,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    identities: dict[str, str] = {}
    for role in ("switch_container", "child", "state_or_switch"):
        identity = arguments.get(role)
        assert isinstance(identity, Mapping), arguments
        assert identity.get("kind") == "id", arguments
        object_id = identity.get("value")
        assert isinstance(object_id, str) and object_id, arguments
        identities[role] = object_id

    draft = _start_business_draft(runtime, operation)
    handles = {
        role: _bind_business_object(
            runtime,
            draft,
            object_id=object_id,
            role=role,
        )
        for role, object_id in identities.items()
    }
    _update_business_draft(
        runtime,
        draft,
        "draft-declare-switch-assignment",
        [
            "--switch-container-handle",
            handles["switch_container"],
            "--child-handle",
            handles["child"],
            "--state-or-switch-handle",
            handles["state_or_switch"],
        ],
        live=False,
    )
    _update_business_draft(runtime, draft, "draft-check", live=True)
    return _update_business_draft(
        runtime,
        draft,
        "preview-from-draft",
        live=True,
    )


def _complete_object_lifecycle_business_transaction(
    runtime: _WorkflowSandboxRuntime,
    *,
    operation: str,
    object_id: str,
    parent_id: str | None = None,
    new_name: str | None = None,
    notes: str | None = None,
    name_conflict: str | None = None,
) -> dict[str, Mapping[str, Any]]:
    preview = create_object_lifecycle_business_preview(
        lambda command: runtime.gateway(
            command,
            live=command[0]
            in {"draft-bind-object", "draft-check", "preview-from-draft"},
        ),
        version=runtime.version,
        operation=operation,
        object_id=object_id,
        parent_id=parent_id,
        new_name=new_name,
        notes=notes,
        name_conflict=name_conflict,
    )
    transaction_id = preview["transaction_id"]
    shown = runtime.gateway(
        ["transaction-show", transaction_id, "--summary-only"],
        live=False,
    )
    token = shown["confirmation"]["token"]
    runtime.gateway(
        ["confirm", transaction_id, "--confirmation-token", token],
        live=False,
    )
    executed = runtime.gateway(["execute", transaction_id], live=True)
    verified = runtime.gateway(["verify", transaction_id], live=True)
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value, executed
    assert verified["state"] == TransactionState.VERIFIED.value, verified
    assert verified["verification"]["operation"] == operation, verified
    assert verified["verification"]["business_state_verified"] is True, verified
    return {"preview": preview, "execute": executed, "verify": verified}


def _complete_object_metadata_business_transaction(
    runtime: _WorkflowSandboxRuntime,
    *,
    operation: str,
    object_id: str,
    field_name: str,
    value: Any = None,
    target_id: str | None = None,
    clear_reference: bool = False,
    platform: str | None = None,
    linked: bool | None = None,
) -> dict[str, Mapping[str, Any]]:
    preview = create_object_metadata_business_preview(
        lambda command: runtime.gateway(
            command,
            live=command[0]
            in {
                "draft-bind-object",
                "draft-discover-fields",
                "draft-check",
                "preview-from-draft",
            },
        ),
        version=runtime.version,
        operation=operation,
        object_id=object_id,
        field_name=field_name,
        value=value,
        target_id=target_id,
        clear_reference=clear_reference,
        platform=platform,
        linked=linked,
    )
    transaction_id = preview["transaction_id"]
    shown = runtime.gateway(
        ["transaction-show", transaction_id, "--summary-only"],
        live=False,
    )
    token = shown["confirmation"]["token"]
    runtime.gateway(
        ["confirm", transaction_id, "--confirmation-token", token],
        live=False,
    )
    executed = runtime.gateway(["execute", transaction_id], live=True)
    verified = runtime.gateway(["verify", transaction_id], live=True)
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value, executed
    assert verified["state"] == TransactionState.VERIFIED.value, verified
    assert verified["verification"]["operation"] == operation, verified
    assert verified["verification"]["business_state_verified"] is True, verified
    return {"preview": preview, "execute": executed, "verify": verified}


@pytest.mark.live
@pytest.mark.destructive
def test_object_lifecycle_business_draft_executes_all_five_verifiers(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    runtime = workflow_sandbox_runtime
    parent_root = CONTAINERS_PARENT if runtime.version == "2025.1" else ACTOR_MIXER_PARENT
    suffix = uuid.uuid4().hex[:12]
    source_parent: str | None = None
    destination_parent: str | None = None
    source_id: str | None = None
    copied_id: str | None = None
    try:
        source_parent = _create_object(
            runtime,
            parent=parent_root,
            object_type="ActorMixer",
            name=f"WAAPI_BUSINESS_SOURCE_PARENT_{suffix}",
        )
        destination_parent = _create_object(
            runtime,
            parent=parent_root,
            object_type="ActorMixer",
            name=f"WAAPI_BUSINESS_DEST_PARENT_{suffix}",
        )
        source_id = _create_object(
            runtime,
            parent=source_parent,
            object_type="ActorMixer",
            name=f"WAAPI_BUSINESS_SOURCE_{suffix}",
        )
        renamed = f"WAAPI_BUSINESS_RENAMED_{suffix}"
        notes = f"business Draft notes {runtime.version} {suffix}"
        _complete_object_lifecycle_business_transaction(
            runtime,
            operation="object.setName",
            object_id=source_id,
            new_name=renamed,
        )
        _complete_object_lifecycle_business_transaction(
            runtime,
            operation="object.setNotes",
            object_id=source_id,
            notes=notes,
        )
        copied = _complete_object_lifecycle_business_transaction(
            runtime,
            operation="object.copy",
            object_id=source_id,
            parent_id=destination_parent,
            name_conflict="rename",
        )
        copied_id = _created_object_id(copied["execute"])
        _complete_object_lifecycle_business_transaction(
            runtime,
            operation="object.move",
            object_id=source_id,
            parent_id=destination_parent,
            name_conflict="rename",
        )
        _complete_object_lifecycle_business_transaction(
            runtime,
            operation="object.delete",
            object_id=copied_id,
        )
        copied_id = None
        runtime.category_results.append(
            {
                "category": "object-lifecycle-business",
                "status": "PASS",
                "verifier_strength": "five_operation_business_draft_full_chain",
            }
        )
    finally:
        for object_id in (
            copied_id,
            source_id,
            destination_parent,
            source_parent,
        ):
            if object_id is not None:
                _delete_if_present_via_transaction(runtime, object_id)


@pytest.mark.live
@pytest.mark.destructive
def test_compound_undo_business_draft_executes_and_cancels_without_retry(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    runtime = workflow_sandbox_runtime
    if runtime.version not in {"2022.1", "2025.1"}:
        pytest.skip("compound Undo evidence targets Wwise 2022.1 and 2025.1")
    parent_root = (
        CONTAINERS_PARENT if runtime.version == "2025.1" else ACTOR_MIXER_PARENT
    )
    suffix = uuid.uuid4().hex[:12]
    success_id: str | None = None
    failure_id: str | None = None
    conflict_id: str | None = None
    try:
        success_original_name = f"WAAPI_UNDO_SUCCESS_{suffix}"
        success_final_name = f"WAAPI_UNDO_RENAMED_{suffix}"
        success_notes = f"compound success {runtime.version} {suffix}"
        success_id = _create_object(
            runtime,
            parent=parent_root,
            object_type="ActorMixer",
            name=success_original_name,
        )
        notes_child = _checked_object_lifecycle_child(
            runtime,
            operation="object.setNotes",
            object_id=success_id,
            value=success_notes,
        )
        rename_child = _checked_object_lifecycle_child(
            runtime,
            operation="object.setName",
            object_id=success_id,
            value=success_final_name,
        )
        success_parent = _declare_compound_undo(
            runtime,
            display_name=f"Compound success {suffix}",
            children=(notes_child, rename_child),
        )
        success = _complete_business_draft(runtime, success_parent)
        assert success["verify"]["verification"]["verification_strength"] == (
            "compound_child_readback"
        )
        success_readback = runtime.gateway(
            [
                "query-object",
                "--exact-id",
                success_id,
                "--include",
                "notes",
            ],
            live=True,
        )
        assert success_readback["count"] == 1, success_readback
        assert success_readback["objects"][0]["name"] == success_final_name
        assert success_readback["objects"][0]["notes"] == success_notes

        failure_name = f"WAAPI_UNDO_CANCEL_{suffix}"
        conflict_name = f"WAAPI_UNDO_CONFLICT_{suffix}"
        failure_notes = f"before cancelled child {runtime.version} {suffix}"
        failure_id = _create_object(
            runtime,
            parent=parent_root,
            object_type="ActorMixer",
            name=failure_name,
        )
        conflict_id = _create_object(
            runtime,
            parent=parent_root,
            object_type="ActorMixer",
            name=conflict_name,
        )
        first_child = _checked_object_lifecycle_child(
            runtime,
            operation="object.setNotes",
            object_id=failure_id,
            value=failure_notes,
        )
        rejected_child = _checked_object_lifecycle_child(
            runtime,
            operation="object.setName",
            object_id=failure_id,
            value=conflict_name,
        )
        failure_parent = _declare_compound_undo(
            runtime,
            display_name=f"Compound cancel {suffix}",
            children=(first_child, rejected_child),
        )
        _update_business_draft(
            runtime,
            failure_parent,
            "draft-check",
            live=True,
        )
        preview = _update_business_draft(
            runtime,
            failure_parent,
            "preview-from-draft",
            live=True,
        )
        transaction_id = _required_string(preview, "transaction_id")
        shown = runtime.gateway(
            ["transaction-show", transaction_id, "--summary-only"],
            live=False,
        )
        runtime.gateway(
            [
                "confirm",
                transaction_id,
                "--confirmation-token",
                _required_string(shown["confirmation"], "token"),
            ],
            live=False,
        )
        failure_code, failure = runtime.raw_gateway(
            ["execute", transaction_id]
        )
        assert failure_code == 2, failure
        assert failure["state"] == TransactionState.EXECUTION_CANCELLED.value
        assert failure["automatic_retry"] is False
        assert failure["rollback_verified"] is False
        assert failure["compound_execution"]["failed_phase"]["uri"] == (
            "ak.wwise.core.object.setName"
        )
        retry_code, retry = runtime.raw_gateway(["execute", transaction_id])
        assert retry_code == 2, retry
        assert retry["error_code"] == "InvalidTransition"
        runtime.category_results.append(
            {
                "category": "compound-undo-business",
                "status": "PASS",
                "verifier_strength": (
                    "named_child_readbacks_plus_real_cancel_no_retry"
                ),
            }
        )
    finally:
        for object_id in (conflict_id, failure_id, success_id):
            if object_id is not None:
                _delete_if_present_via_transaction(runtime, object_id)


@pytest.mark.live
@pytest.mark.destructive
def test_object_metadata_business_draft_executes_field_verifiers(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    runtime = workflow_sandbox_runtime
    if runtime.version not in {"2022.1", "2025.1"}:
        pytest.skip("object metadata business evidence targets 2022.1 and 2025.1")
    suffix = uuid.uuid4().hex[:12]
    source_id: str | None = None
    target_bus_id: str | None = None
    try:
        source_id = _create_object(
            runtime,
            parent=(
                CONTAINERS_PARENT
                if runtime.version == "2025.1"
                else ACTOR_MIXER_PARENT
            ),
            object_type="ActorMixer",
            name=f"WAAPI_METADATA_SOURCE_{suffix}",
        )
        target_bus_id = SFX_BUS_ID
        _complete_object_metadata_business_transaction(
            runtime,
            operation="object.setProperty",
            object_id=source_id,
            field_name="Volume",
            value=-3.25,
            platform="Windows",
        )
        _complete_object_metadata_business_transaction(
            runtime,
            operation="object.setReference",
            object_id=source_id,
            field_name="OutputBus",
            target_id=target_bus_id,
            platform="Windows",
        )
        if runtime.version == "2025.1":
            _complete_object_metadata_business_transaction(
                runtime,
                operation="object.setLinked",
                object_id=source_id,
                field_name="Volume",
                platform="Windows",
                linked=False,
            )
        runtime.category_results.append(
            {
                "category": "object-metadata-business",
                "status": "PASS",
                "verifier_strength": (
                    "property_reference_and_platform_link_business_full_chain"
                    if runtime.version == "2025.1"
                    else "property_and_reference_business_full_chain"
                ),
            }
        )
    finally:
        if source_id is not None:
            _delete_if_present_via_transaction(runtime, source_id)


@pytest.mark.live
@pytest.mark.destructive
def test_core_business_public_read_and_result_schema_mutation(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    runtime = workflow_sandbox_runtime
    if runtime.version not in {"2022.1", "2025.1"}:
        pytest.skip("Core business evidence targets Wwise 2022.1 and 2025.1")
    parent = CONTAINERS_PARENT if runtime.version == "2025.1" else ACTOR_MIXER_PARENT
    suffix = uuid.uuid4().hex[:12]
    source_id: str | None = None
    target_id: str | None = None
    try:
        source_id = _create_object(
            runtime,
            parent=parent,
            object_type="ActorMixer",
            name=f"WAAPI_CORE_SOURCE_{suffix}",
        )
        target_id = _create_object(
            runtime,
            parent=parent,
            object_type="ActorMixer",
            name=f"WAAPI_CORE_TARGET_{suffix}",
        )
        volume_db = -7.25
        _complete_object_metadata_business_transaction(
            runtime,
            operation="object.setProperty",
            object_id=source_id,
            field_name="Volume",
            value=volume_db,
            platform="Windows",
        )

        diff = runtime.gateway(
            [
                "core-call",
                "ak.wwise.core.object.diff",
                "--source-id",
                source_id,
                "--target-id",
                target_id,
            ],
            live=True,
        )
        assert isinstance(diff.get("agent_result"), Mapping), diff
        assert diff["api_attempted"] == "ak.wwise.core.object.diff", diff
        assert diff["business_request"]["roles"] == {
            "source": source_id,
            "target": target_id,
        }

        draft = _start_business_draft(
            runtime,
            "ak.wwise.core.object.pasteProperties",
        )
        source_handle = _bind_business_object(
            runtime,
            draft,
            object_id=source_id,
            role="source",
        )
        volume_field = _discover_business_field(
            runtime,
            draft,
            object_handle=source_handle,
            meaning="volume",
            platform="Windows",
        )
        target_handle = _bind_business_object(
            runtime,
            draft,
            object_id=target_id,
            role="target",
        )
        _update_business_draft(
            runtime,
            draft,
            "draft-declare-core-plan",
            [
                "--role",
                "source_handle",
                source_handle,
                "--role",
                "target_handles",
                target_handle,
                "--field",
                "include_field_handles",
                volume_field,
                "--value",
                "list_mode",
                "merge-replace",
            ],
            live=True,
        )
        completed = _complete_core_result_schema_draft(runtime, draft)
        assert completed["verify"]["verification"]["operation"] == (
            "waapi.call"
        )
        readback = runtime.gateway(
            [
                "query-object",
                "--exact-id",
                target_id,
                "--include",
                "volume-db",
            ],
            live=True,
        )
        assert readback["count"] == 1, readback
        assert float(readback["objects"][0]["volume_db"]) == volume_db, readback
        runtime.category_results.append(
            {
                "category": "core-business-public-seam",
                "status": "PASS",
                "verifier_strength": (
                    "bounded_read_plus_result_schema_and_manual_state_readback"
                ),
            }
        )
    finally:
        for object_id in (target_id, source_id):
            if object_id is not None:
                _delete_if_present_via_transaction(runtime, object_id)


@pytest.mark.live
@pytest.mark.destructive
def test_object_graph_business_draft_executes_weather_graph_plugin_bulk_set_and_rtpc(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    runtime = workflow_sandbox_runtime
    if runtime.version not in {"2022.1", "2025.1"}:
        pytest.skip("object graph business evidence targets 2022.1 and 2025.1")

    suffix = uuid.uuid4().hex[:12]
    weather_name = f"WAAPI_BUSINESS_WEATHER_{suffix}"
    rain_name = f"Rain_{suffix}"
    wind_name = f"Wind_{suffix}"
    root_segments = (
        ("Containers", "Default Work Unit")
        if runtime.version == "2025.1"
        else ("Actor-Mixer Hierarchy", "Default Work Unit")
    )
    root_path = "\\" + "\\".join((*root_segments, weather_name))
    weather_id: str | None = None
    try:
        create = _start_business_draft(runtime, "object.create")
        parent_handle = _bind_business_object(
            runtime,
            create,
            path_segments=root_segments,
        )
        declared_root = _update_business_draft(
            runtime,
            create,
            "draft-declare-new",
            [
                "--declaration-id",
                "weather",
                "--parent-handle",
                parent_handle,
                "--name",
                weather_name,
                "--kind",
                "actor-mixer",
            ],
            live=False,
        )
        weather_handle = _declared_result_handle(declared_root, "weather")
        for declaration_id, name, volume in (
            ("rain", rain_name, "-4"),
            ("wind", wind_name, "-6"),
        ):
            _update_business_draft(
                runtime,
                create,
                "draft-declare-new",
                [
                    "--declaration-id",
                    declaration_id,
                    "--parent-handle",
                    weather_handle,
                    "--name",
                    name,
                    "--kind",
                    "sound-sfx",
                    "--field",
                    "loop",
                    "infinite",
                    "--field",
                    "volume_db",
                    volume,
                ],
                live=False,
            )
        created = _complete_business_draft(runtime, create)
        weather_id = _created_object_id(created["execute"])

        rain_id = _query_exact_path_id(runtime, f"{root_path}\\{rain_name}")
        wind_id = _query_exact_path_id(runtime, f"{root_path}\\{wind_name}")

        plugin = _start_business_draft(runtime, "object.createPlugin")
        rain_plugin_handle = _bind_business_object(
            runtime,
            plugin,
            object_id=rain_id,
        )
        plugin_type_handle = _discover_business_type(
            runtime,
            plugin,
            meaning="Wwise Tone Generator",
            role="source",
            expected_label="Wwise Tone Generator",
        )
        _update_business_draft(
            runtime,
            plugin,
            "draft-declare-existing",
            [
                "--declaration-id",
                "weather-tone",
                "--object-handle",
                rain_plugin_handle,
                "--field",
                "plugin_role",
                "source",
                "--field",
                "plugin_name",
                f"Weather_Tone_{suffix}",
                "--field",
                "plugin_type_handle",
                plugin_type_handle,
            ],
            live=False,
        )
        _complete_business_draft(runtime, plugin)

        bulk_set = _start_business_draft(runtime, "object.set")
        rain_set_handle = _bind_business_object(
            runtime,
            bulk_set,
            object_id=rain_id,
        )
        wind_set_handle = _bind_business_object(
            runtime,
            bulk_set,
            object_id=wind_id,
        )
        rain_volume = _discover_business_field(
            runtime,
            bulk_set,
            object_handle=rain_set_handle,
            meaning="volume",
        )
        wind_volume = _discover_business_field(
            runtime,
            bulk_set,
            object_handle=wind_set_handle,
            meaning="volume",
        )
        for declaration_id, object_handle, field_handle, volume in (
            ("rain", rain_set_handle, rain_volume, "-5"),
            ("wind", wind_set_handle, wind_volume, "-7"),
        ):
            _update_business_draft(
                runtime,
                bulk_set,
                "draft-declare-existing",
                [
                    "--declaration-id",
                    declaration_id,
                    "--object-handle",
                    object_handle,
                    "--field-value",
                    field_handle,
                    volume,
                ],
                live=False,
            )
        _complete_business_draft(runtime, bulk_set)

        rtpc = _start_business_draft(runtime, "object.setRTPC")
        rain_rtpc_handle = _bind_business_object(
            runtime,
            rtpc,
            object_id=rain_id,
        )
        volume_handle = _discover_business_field(
            runtime,
            rtpc,
            object_handle=rain_rtpc_handle,
            meaning="volume",
        )
        control_handle = _bind_business_object(
            runtime,
            rtpc,
            path_segments=("Game Parameters", "Ambience", "Rain_Intensity"),
        )
        _update_business_draft(
            runtime,
            rtpc,
            "draft-declare-rtpc",
            [
                "--object-handle",
                rain_rtpc_handle,
                "--field-handle",
                volume_handle,
                "--control-input-handle",
                control_handle,
                "--point",
                "0",
                "-12",
                "SCurve",
                "--point",
                "100",
                "0",
                "SCurve",
                "--notes",
                f"Weather business RTPC {suffix}",
            ],
            live=False,
        )
        _complete_business_draft(runtime, rtpc)

        runtime.category_results.append(
            {
                "category": "object-graph-business",
                "status": "PASS",
                "verifier_strength": (
                    "recursive_create_plugin_bulk_set_rtpc_business_full_chain"
                ),
            }
        )
    finally:
        if weather_id is not None:
            _delete_if_present_via_transaction(runtime, weather_id)


def _save_sandbox_project(runtime: _WorkflowSandboxRuntime) -> None:
    """Persist prior sandbox mutations before a file-authority operation."""

    api = "ak.wwise.core.project.save"
    schema = runtime.gateway(["request-schema", api], live=False)
    continuation = schema.get("continuation")
    assert isinstance(continuation, Mapping), schema
    argv = continuation.get("gateway_argv")
    if argv is None:
        argv = continuation.get("gateway_argv_prefix")
    assert (
        isinstance(argv, list)
        and argv
        and all(isinstance(item, str) and item for item in argv)
    ), continuation
    preview = runtime.gateway(argv, live=True)
    transaction_id = preview.get("transaction_id")
    assert isinstance(transaction_id, str) and transaction_id, preview
    shown = runtime.gateway(
        ["transaction-show", transaction_id, "--summary-only"],
        live=False,
    )
    confirmation = shown.get("confirmation")
    assert isinstance(confirmation, Mapping), shown
    token = confirmation.get("token")
    assert isinstance(token, str) and token, shown
    runtime.gateway(
        ["confirm", transaction_id, "--confirmation-token", token],
        live=False,
    )
    executed = runtime.gateway(["execute", transaction_id], live=True)
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value, executed
    verified = runtime.gateway(["verify", transaction_id], live=True)
    assert verified["state"] in {
        TransactionState.VERIFIED.value,
        TransactionState.RESULT_SCHEMA_CHECKED.value,
    }, verified


def _create_object(
    runtime: _WorkflowSandboxRuntime,
    *,
    parent: str,
    object_type: str,
    name: str,
) -> str:
    draft = _start_business_draft(runtime, "object.create")
    parent_handle = (
        _bind_business_object(
            runtime,
            draft,
            path_segments=tuple(
                segment for segment in parent.split("\\") if segment
            ),
        )
        if parent.startswith("\\")
        else _bind_business_object(runtime, draft, object_id=parent)
    )
    semantic_kinds = {
        "ActorMixer": "actor-mixer",
        "Sound": "sound-sfx",
        "SwitchContainer": "switch-container",
    }
    kind = semantic_kinds.get(object_type)
    if kind is None:
        kind = _discover_business_type(
            runtime,
            draft,
            meaning=object_type,
            role="object",
            expected_label=object_type,
        )
    _update_business_draft(
        runtime,
        draft,
        "draft-declare-new",
        [
            "--declaration-id",
            "created-object",
            "--parent-handle",
            parent_handle,
            "--name",
            name,
            "--kind",
            kind,
        ],
        live=False,
    )
    transaction = _complete_business_draft(runtime, draft)
    return _created_object_id(transaction["execute"])


def _delete_if_present_via_transaction(runtime: _WorkflowSandboxRuntime, object_id: str) -> None:
    before = runtime.gateway(
        ["query-object", "--exact-id", object_id],
        live=True,
    )
    if before["count"] == 0:
        return
    assert before["count"] == 1, before
    _complete_object_lifecycle_business_transaction(
        runtime,
        operation="object.delete",
        object_id=object_id,
    )
    after = runtime.gateway(
        ["query-object", "--exact-id", object_id],
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


def _imported_audio_source_id(
    verification: Mapping[str, Any],
    *,
    expected_path: str,
) -> str:
    readbacks = verification.get("readbacks")
    assert isinstance(readbacks, list), verification
    matches: list[Mapping[str, Any]] = []
    for readback in readbacks:
        if not isinstance(readback, Mapping) or readback.get("uri") != (
            "ak.wwise.core.object.get"
        ):
            continue
        result = readback.get("result")
        rows = result.get("return") if isinstance(result, Mapping) else None
        if not isinstance(rows, list):
            continue
        matches.extend(
            row
            for row in rows
            if isinstance(row, Mapping)
            and row.get("type") == "AudioFileSource"
            and row.get("path") == expected_path
        )
    assert len(matches) == 1, {"expected_path": expected_path, "matches": matches}
    return _required_string(matches[0], "id")


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


def _write_external_sources_document(
    path: Path,
    *,
    media_root: Path,
    project_root: Path,
    source_file: Path,
    destination: str,
) -> Path:
    assert not path.exists()
    source_relative = source_file.resolve(strict=True).relative_to(
        media_root.resolve(strict=True)
    ).as_posix()
    root_value = relative_host_path(
        media_root.resolve(strict=True),
        project_root.resolve(strict=True),
    ).as_posix()
    root = ET.Element(
        "ExternalSourcesList",
        {"SchemaVersion": "1", "Root": root_value},
    )
    ET.SubElement(
        root,
        "Source",
        {"Path": source_relative, "Destination": destination},
    )
    ET.indent(root, space="  ")
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
    assert b"<!DOCTYPE" not in data and b"<!ENTITY" not in data and b"\x00" not in data
    path.write_bytes(data)
    return path.resolve(strict=True)


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
