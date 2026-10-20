from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import math
import os
import shutil
import stat
import struct
import subprocess
import sys
import time
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
    EVIDENCE_ROOT,
    current_evidence_platform,
    exact_git_candidate,
)
from tests.destructive.support.console_file_observation import observe_console_file, ConsoleModelImageIndex  # noqa: E402
from tests.destructive.support.exact_real_evidence import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    finalize_exact_real_evidence,
)
from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    DEFAULT_SANDBOX_ROOT,
    LiveSandboxLock,
    SandboxFixtureError,
    SandboxProject,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
    wait_for_port_release,
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
    declared_business_object_handle,
    discovered_business_field_handle,
)
from tests.support.host_path_relatives import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    relative_host_path,
)
from tests.semantic.support.codex_filesystem_security import (  # noqa: E402
    binary_file_open_flags,
    path_is_link_or_reparse,
    read_bounded_exclusive_regular_file,
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
from wwise_waapi.host_paths import localize_waapi_host_path  # noqa: E402
from wwise_waapi.operation_soundbank import prove_artifact_path  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = REPO_ROOT / "skills" / "waapi-skill" / "scripts" / "gateway.py"
ACTOR_MIXER_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
CONTAINERS_PARENT = r"\Containers\Default Work Unit"
ACTOR_MIXER_PARENT_SEGMENTS = ("Actor-Mixer Hierarchy", "Default Work Unit")
CONTAINERS_PARENT_SEGMENTS = ("Containers", "Default Work Unit")
SOUNDBANK_PARENT = r"\SoundBanks\Default Work Unit"
EVENTS_PARENT = r"\Events\Default Work Unit"
GAME_PARAMETERS_PARENT = r"\Game Parameters\Default Work Unit"
FIXTURE_SWITCH_GROUP_PATH = r"\Switches\SS_Impact\SS_FS_Type"
FIXTURE_SWITCH_PATH = FIXTURE_SWITCH_GROUP_PATH + r"\Crawl"
FIXTURE_SWITCH_GROUP_SEGMENTS = ("Switches", "SS_Impact", "SS_FS_Type")
FIXTURE_SWITCH_SEGMENTS = (*FIXTURE_SWITCH_GROUP_SEGMENTS, "Crawl")
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


@dataclass(frozen=True, slots=True)
class _PcmWaveHeader:
    channels: int
    sample_width_bytes: int
    sample_rate_hz: int
    frame_count: int


def _read_pcm_wave_header(path: Path) -> _PcmWaveHeader:
    """Read classic PCM or WAVE_FORMAT_EXTENSIBLE without codec libraries."""

    payload = path.read_bytes()
    assert len(payload) >= 44
    assert payload[:4] == b"RIFF"
    assert payload[8:12] == b"WAVE"
    cursor = 12
    format_chunk: bytes | None = None
    data_size: int | None = None
    while cursor + 8 <= len(payload):
        chunk_id = payload[cursor : cursor + 4]
        chunk_size = struct.unpack_from("<I", payload, cursor + 4)[0]
        chunk_start = cursor + 8
        chunk_end = chunk_start + chunk_size
        assert chunk_end <= len(payload)
        if chunk_id == b"fmt ":
            format_chunk = payload[chunk_start:chunk_end]
        elif chunk_id == b"data":
            data_size = chunk_size
        cursor = chunk_end + (chunk_size & 1)
    assert format_chunk is not None and len(format_chunk) >= 16
    assert data_size is not None
    format_tag, channels, sample_rate, _, block_align, bits_per_sample = (
        struct.unpack_from("<HHIIHH", format_chunk)
    )
    if format_tag == 0xFFFE:
        assert len(format_chunk) >= 40
        assert struct.unpack_from("<H", format_chunk, 16)[0] >= 22
        assert struct.unpack_from("<H", format_chunk, 18)[0] in {
            0,
            bits_per_sample,
        }
        assert format_chunk[24:40] == bytes.fromhex(
            "0100000000001000800000aa00389b71"
        )
    else:
        assert format_tag == 1
    sample_width = (bits_per_sample + 7) // 8
    assert block_align == channels * sample_width
    assert data_size % block_align == 0
    return _PcmWaveHeader(
        channels=channels,
        sample_width_bytes=sample_width,
        sample_rate_hz=sample_rate,
        frame_count=data_size // block_align,
    )


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
    *,
    inspect_preview=None,
) -> dict[str, Mapping[str, Any]]:
    _update_business_draft(runtime, draft, "draft-check", live=True)
    preview = _update_business_draft(
        runtime,
        draft,
        "preview-from-draft",
        live=True,
    )
    transaction_id = _required_string(preview, "transaction_id")
    if inspect_preview is not None:
        inspect_preview(preview)
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
    *,
    allow_verified_setup: bool = False,
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
    if allow_verified_setup and verified["state"] == TransactionState.VERIFIED.value:
        assert verified["verification"]["business_state_verified"] is True, verified
        return {"preview": preview, "execute": executed, "verify": verified}
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
    _bind_business_object(
        runtime,
        draft,
        object_id=object_id,
    )
    flag = "--new-name" if operation == "object.setName" else "--notes"
    _update_business_draft(
        runtime,
        draft,
        "draft-declare-object-change",
        [flag, value],
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
    return discovered_business_field_handle(payload, meaning)


def _query_exact_path_id(
    runtime: _WorkflowSandboxRuntime,
    *,
    path_segments: Sequence[str],
    expected_path: str,
) -> str:
    payload = runtime.gateway(
        [
            "query-object",
            *(
                item
                for segment in path_segments
                for item in ("--path-segment", segment)
            ),
        ],
        live=True,
    )
    rows = payload.get("objects")
    assert payload.get("count") == 1 and isinstance(rows, list), payload
    assert len(rows) == 1 and isinstance(rows[0], Mapping), rows
    assert rows[0].get("path") == expected_path, rows[0]
    return _required_string(rows[0], "id")


INLINE_WAV_BASE64 = "UklGRigAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAAAAAAA"
INLINE_WAV_SHA256 = "0588c6a627c6603830a9e5d87ab258d4977c02876b9bac8f9598fccef098c1cf"


def _inline_wav_current_binding() -> dict[str, Any]:
    """Bind current acceptance without borrowing the separate historical pin."""
    from tests.semantic.support.codex_harness import (
        WORKSPACE_SKILL_EXCLUDED_NAMES, workspace_skill_tree_sha256,
    )
    return {
        "current_skill_sha256": workspace_skill_tree_sha256(
            REPO_ROOT / "skills/waapi-skill", exclude_names=WORKSPACE_SKILL_EXCLUDED_NAMES,
        ),
        "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def _persist_inline_wav_receipt(runtime: _WorkflowSandboxRuntime, receipt: dict[str, Any]) -> None:
    target = runtime.state_dir.parent / "inline-wav-probe.json"
    encoded = json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8")
    assert len(encoded) <= 2 * 1024 * 1024, "inline diagnostic evidence bound exceeded"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(target)


class _InlineWavReceiptGateway:
    """Retain every public response before the ordinary Draft helpers assert."""

    def __init__(self, runtime: _WorkflowSandboxRuntime, receipt: dict[str, Any]):
        self.runtime, self.receipt = runtime, receipt

    def raw_gateway(self, command: Sequence[str]) -> tuple[int, dict[str, Any]]:
        row: dict[str, Any] = {"argv": list(command)}
        self.receipt["calls"].append(row)
        try:
            code, payload = self.runtime.raw_gateway(command)
            row.update(exit_code=code, payload=payload)
            return code, payload
        except Exception as exc:
            row["exception"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            _persist_inline_wav_receipt(self.runtime, self.receipt)

    def gateway(self, command: Sequence[str], *, live: bool) -> dict[str, Any]:
        code, payload = self.raw_gateway(command)
        assert code == 0 and payload.get("ok") is True, payload
        return payload


def _run_inline_wav_probe(
    runtime: _WorkflowSandboxRuntime,
    parent_id: str,
    sound_name: str,
    receipt: dict[str, Any],
) -> None:
    """One public object.set execution; failures never authorize another write."""
    gateway = _InlineWavReceiptGateway(runtime, receipt)
    receipt.update(native_outcome="not_executed", media_effect="not_observed")
    inline_wav = sound_name + ".wav|" + INLINE_WAV_BASE64
    receipt["source"] = {"inline_wav": inline_wav, "bytes": 48, "sha256": INLINE_WAV_SHA256}
    try:
        empty_parent = gateway.gateway([
            "query-object", "--exact-id", parent_id, "--relationship", "children", "--max-results", "2",
        ], live=True)
        assert empty_parent["count"] == 0 and empty_parent["objects"] == [], empty_parent
        expected_original = runtime.sandbox.sandbox_path / "Originals" / "SFX" / (sound_name + ".wav")
        prove_artifact_path(expected_original, io_root=runtime.sandbox.sandbox_path, field="new inline Originals WAV", expect_directory=False)
        assert not expected_original.exists(), expected_original
        receipt["original_absent_before"] = str(expected_original)
        draft = _start_business_draft(gateway, "object.set")
        parent_handle = _bind_business_object(gateway, draft, object_id=parent_id)
        _update_business_draft(gateway, draft, "draft-declare-new", [
            "--declaration-id", "inline-sound", "--parent-handle", parent_handle,
            "--name", sound_name, "--kind", "sound-sfx",
        ], live=False)
        _update_business_draft(gateway, draft, "draft-add-media", [
            "--declaration-id", "inline-sound", "--inline-wav", inline_wav,
            "--kind", "sound-sfx", "--language", "SFX",
        ], live=False)
        _update_business_draft(gateway, draft, "draft-check", live=True)
        preview = _update_business_draft(gateway, draft, "preview-from-draft", live=True)
        transaction_id = _required_string(preview, "transaction_id")
        receipt.update(transaction_id=transaction_id, preview_hash=preview["artifact_hash"])
        if "lifecycle_final_reference" in receipt:
            receipt["lifecycle_final_reference"]["transaction_id"] = transaction_id
        shown = gateway.gateway(["transaction-show", transaction_id], live=False)
        native = shown["artifact"]["prepared_operation"]["dispatch"]
        receipt["compiled_native_request"] = native
        # Check an exact leaf without manufacturing the native request.
        files = native["args"]["objects"][0]["children"][0]["import"]["files"]
        assert len(files) == 1 and files[0]["audioFileBase64"] == inline_wav, native
        assert native["uri"] == "ak.wwise.core.object.set", native
        _persist_inline_wav_receipt(runtime, receipt)
        gateway.gateway(["confirm", transaction_id, "--confirmation-token", shown["confirmation"]["token"]], live=False)
        receipt["native_outcome"] = "indeterminate"
        code, executed = gateway.raw_gateway(["execute", transaction_id])
        receipt["gateway_terminal_state"] = executed.get("state")
        receipt["native_response"] = executed.get("dispatch_result")
        if code != 0 or executed.get("ok") is not True:
            receipt["native_outcome"] = (
                "rejected" if executed.get("state") == "execution_failed" else "indeterminate"
            )
            return
        assert executed.get("state") == "executed_unverified", executed
        dispatch_result = executed.get("dispatch_result")
        assert isinstance(dispatch_result, Mapping) and dispatch_result.get("ok") is True, executed
        receipt.update(native_outcome="accepted", media_effect="incomplete")
        # Even a failed verifier cannot erase acceptance or justify replay.
        verify_code, verified = gateway.raw_gateway(["verify", transaction_id])
        receipt["gateway_verification"] = {
            "exit_code": verify_code, "ok": verified.get("ok"), "state": verified.get("state"),
            "business_state_verified": verified.get("verification", {}).get("business_state_verified"),
        }
        children = gateway.gateway([
            "query-object", "--exact-id", parent_id, "--relationship", "children", "--max-results", "2",
        ], live=True)
        rows = children["objects"]
        assert children["count"] == 1 and len(rows) == 1, children
        sound = rows[0]
        assert sound["type"] == "Sound" and sound["name"] == sound_name, sound
        sound_id = _required_string(sound, "id")
        exact_sound = gateway.gateway([
            "query-object", "--exact-id", sound_id, "--include", "active-source", "--max-results", "1",
        ], live=True)
        assert exact_sound["count"] == 1 and len(exact_sound["objects"]) == 1, exact_sound
        sound_row = exact_sound["objects"][0]
        assert all(sound_row.get(key) == sound.get(key) for key in ("id", "name", "type", "path")), exact_sound
        source_id = _required_string(sound_row["active_source"], "id")
        sources = gateway.gateway([
            "query-object", "--exact-id", sound_id, "--relationship", "children", "--max-results", "2",
        ], live=True)
        assert sources["count"] == 1 and len(sources["objects"]) == 1, sources
        assert sources["objects"][0]["id"] == source_id and sources["objects"][0]["type"] == "AudioFileSource", sources
        exact_source = gateway.gateway([
            "query-object", "--exact-id", source_id, "--include", "parent",
            "--include", "original-file-path", "--include", "source-language", "--max-results", "1",
        ], live=True)
        assert exact_source["count"] == 1 and len(exact_source["objects"]) == 1, exact_source
        source = exact_source["objects"][0]
        assert source["id"] == source_id and source["type"] == "AudioFileSource", source
        assert source["parent"]["id"] == sound_id, source
        language = source["source_language"]
        assert isinstance(language, Mapping) and language.get("name") == "SFX", source
        assert uuid.UUID(_required_string(language, "id")).int != 0, source
        assert source["path"] == sound_row["path"] + "\\" + sound_name, source
        original = Path(localize_waapi_host_path(source["original_file_path"]))
        originals = runtime.sandbox.sandbox_path / "Originals"
        # Refuse converted/cache media and any path outside this private project.
        prove_artifact_path(original, io_root=originals, field="inline imported Originals WAV", must_exist=True, expect_directory=False)
        assert original == expected_original, original
        snapshot = read_bounded_exclusive_regular_file(original, max_bytes=48, require_private_posix_mode=False)
        receipt["original_wav"] = {
            "path": str(original), "size": len(snapshot.raw), "sha256": hashlib.sha256(snapshot.raw).hexdigest(),
            "hex": snapshot.raw.hex(), "sound_id": sound_id, "source_id": source_id,
        }
        assert receipt["original_wav"]["sha256"] == INLINE_WAV_SHA256, receipt["original_wav"]
        with wave.open(io.BytesIO(snapshot.raw), "rb") as wav:
            pcm = {"channels": wav.getnchannels(), "sample_width_bytes": wav.getsampwidth(),
                   "sample_rate_hz": wav.getframerate(), "frame_count": wav.getnframes()}
        receipt["original_wav"]["pcm"] = pcm
        assert pcm == {"channels": 1, "sample_width_bytes": 2, "sample_rate_hz": 44100, "frame_count": 2}, pcm
        receipt["media_effect"] = "proven"
    except Exception as exc:
        receipt["diagnostic_error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        _persist_inline_wav_receipt(runtime, receipt)


@pytest.mark.live
@pytest.mark.destructive
def test_object_set_canonical_unpadded_inline_wav_acceptance(workflow_sandbox_runtime) -> None:
    """Require current Gateway verification and independent exact Originals proof."""
    runtime = workflow_sandbox_runtime
    if runtime.version not in {"2023.1", "2024.1", "2025.1"}:
        pytest.skip("object.set inline WAV compatibility applies to 2023.1–2025.1")
    configured_evidence = runtime.env.get("WWISE_CATEGORY_EVIDENCE_PATH")
    if configured_evidence is None and sys.platform == "darwin":
        configured_evidence = runtime.env.get("WWISE_MACOS_CATEGORY_EVIDENCE_PATH")
    lifecycle_path = (Path(configured_evidence).expanduser().resolve(strict=False)
                      if configured_evidence else
                      REPO_ROOT / EVIDENCE_ROOT / (current_evidence_platform() + "-category-evidence.jsonl"))
    receipt: dict[str, Any] = {
        "category": "object-set-unpadded-inline-wav-acceptance", "status": "FAIL",
        "verifier_strength": "gateway_verified_plus_independent_sound_source_originals_bytes",
        "candidate": runtime.candidate, **_inline_wav_current_binding(),
        "version": runtime.version, "calls": [],
        "config_sha256": hashlib.sha256(Path(runtime.env["WAAPI_SKILL_CONFIG_PATH"]).read_bytes()).hexdigest(),
        "endpoint": {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url},
        "build": runtime.sandbox.metadata.get_info_version,
        "receipt_path": str(runtime.state_dir.parent / "inline-wav-probe.json"),
        "lifecycle_final_reference": {
            "path": str(lifecycle_path), "contract": "waapi-skill.host-category-evidence/v3",
            "phase": "final", "candidate": runtime.candidate,
            "category": "object-set-unpadded-inline-wav-acceptance", "transaction_id": None,
            "cleanup_status": "unresolved_until_final_row",
        },
        "lifecycle_acceptance": "Requires the final host-category-evidence/v3 row with this candidate, transaction_id and category; prepared/PENDING is not cleanup success. That final row binds source before/after hash/mtime and residual process cleanup.",
    }
    runtime.category_results.append(receipt)
    _persist_inline_wav_receipt(runtime, receipt)
    root_segments = CONTAINERS_PARENT_SEGMENTS if runtime.version == "2025.1" else ACTOR_MIXER_PARENT_SEGMENTS
    suffix = uuid.uuid4().hex[:12]
    try:
        parent_id = _create_object(runtime, parent="\\" + "\\".join(root_segments), object_type="ActorMixer", name="WAAPI_INLINE_PARENT_" + suffix)
        receipt["owned_parent_id"] = parent_id
        _run_inline_wav_probe(runtime, parent_id, "WAAPI_INLINE_" + suffix, receipt)
        assert receipt["native_outcome"] == "accepted" and receipt["media_effect"] == "proven", receipt
        assert receipt["gateway_verification"] == {
            "exit_code": 0, "ok": True, "state": "verified", "business_state_verified": True,
        }, receipt
        receipt["status"] = "PASS"
    finally:
        _persist_inline_wav_receipt(runtime, receipt)


@pytest.mark.live
@pytest.mark.destructive
def test_music_import_structure_media_owner_probe(workflow_sandbox_runtime) -> None:
    from wwise_waapi.headless import default_waapi_client_factory

    runtime = workflow_sandbox_runtime
    client = default_waapi_client_factory(runtime.lifecycle.waapi_url)
    try:
        name = "WAAPI_MUSIC_" + uuid.uuid4().hex[:12]
        audio = _write_fixture_wav(runtime.sandbox.sandbox_path / "GatewayWorkflowAudio", name)
        root = (r"\Containers\Default Work Unit" if runtime.version == "2025.1"
                else r"\Interactive Music Hierarchy\Default Work Unit")
        track = f"{root}\\<MusicSegment>{name}\\<MusicTrack>Music"
        result = client.call(
            "ak.wwise.core.audio.import",
            {"importOperation": "useExisting", "imports": [
                {"objectPath": track, "@Volume": -6.0},
                {"objectPath": track + f"\\<AudioFileSource>{audio.stem}",
                 "audioFile": str(audio), "importLanguage": "SFX"},
            ]},
            options={"return": ["id", "name", "type", "path", "parent"]},
        )
        rows = client.call(
            "ak.wwise.core.object.get",
            {"from": {"path": [f"{root}\\{name}\\Music"]}},
            options={"return": ["id", "name", "type", "path", "@Volume", "@Sequences"]},
        )
        source_ids = [row["id"] for row in result["objects"] if row["type"] == "AudioFileSource"]
        media_field = "originalWavFilePath" if runtime.version == "2021.1" else "originalFilePath"
        sources = client.call(
            "ak.wwise.core.object.get", {"from": {"id": source_ids}},
            options={"return": ["id", "type", "path", "parent", media_field, "audioSource:language"]},
        )
        sequence_ids = [item["id"] for item in rows["return"][0].get("@Sequences", [])]
        sequences = client.call(
            "ak.wwise.core.object.get", {"from": {"id": sequence_ids}},
            options={"return": ["id", "type", "@Clips"]},
        )
        clip_ids = [clip["id"] for seq in sequences["return"] for clip in seq.get("@Clips", [])]
        clips = client.call(
            "ak.wwise.core.object.get", {"from": {"id": clip_ids}},
            options={"return": ["id", "type", media_field, "@Volume"]},
        ) if clip_ids else {"return": []}
        evidence = {"category": "music-import-topology-probe", "status": "FAIL",
                    "verifier_strength": "native_diagnostic_not_gateway_acceptance", "result": result,
                    "track": rows, "sources": sources, "sequences": sequences, "clips": clips}
        runtime.category_results.append(evidence)
        assert rows["return"][0]["@Volume"] == -6, evidence
        assert len(sources["return"]) == 1, evidence
        assert len(clips["return"]) == 1, evidence
        assert clips["return"][0][media_field] == sources["return"][0][media_field], evidence
        evidence["status"] = "PASS"
    finally:
        client.disconnect()


@pytest.mark.live
@pytest.mark.destructive
@pytest.mark.parametrize("set_volume", [False, True])
def test_closed_music_import_media_and_track_volume(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime, set_volume: bool,
) -> None:
    """Public business declaration through Preview, execution and music verification."""
    runtime = workflow_sandbox_runtime
    name = "Music_Closed_" + uuid.uuid4().hex[:12]
    audio = _write_fixture_wav(runtime.sandbox.sandbox_path / "GatewayWorkflowAudio", name)
    if runtime.version == "2021.1":
        _save_sandbox_project(runtime)
    draft = _start_business_draft(runtime, "audio.import")
    root = "Containers" if runtime.version == "2025.1" else "Interactive Music Hierarchy"
    parent = _bind_business_object(runtime, draft, path_segments=(root, "Default Work Unit"))
    arguments = [
        "--row-order", "segment", "track",
        "--new-row", "segment", parent, name, "music-segment",
        "--new-row", "track", "segment", "Music", "music-track",
        "--media-directory", str(audio.parent), "--media-file", "track", audio.name,
    ]
    if set_volume:
        arguments.extend(["--field", "track", "volume_db", "-6"])
    _update_business_draft(runtime, draft, "draft-declare-import-batch", arguments, live=False)
    result = _complete_business_draft(runtime, draft)
    runtime.category_results.append({
        "category": "music-import-business-with-volume" if set_volume else "music-import-business-media-only",
        "status": "PASS", "verifier_strength": "gateway_music_source_clip_media_and_track_property",
        "transaction_id": result["verify"]["transaction_id"],
    })


@pytest.mark.live
@pytest.mark.destructive
@pytest.mark.parametrize("workflow_sandbox_runtime", [("Japanese",)], indirect=True)
def test_voice_languages_reimport_preserves_other_language_and_sound_identity(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Two real voice languages share a Sound, not each other's media slot."""
    runtime = workflow_sandbox_runtime
    name = "Voice_Localized_" + uuid.uuid4().hex[:10]
    media_name = name + "_Media"
    root = "Containers" if runtime.version == "2025.1" else "Actor-Mixer Hierarchy"
    media_root = runtime.sandbox.sandbox_path / "GatewayVoiceAudio"
    voice_id: str | None = None
    snapshots: list[dict[str, Mapping[str, Any]]] = []
    for index, language in enumerate(("English(US)", "Japanese", "English(US)", "Japanese")):
        media = _write_fixture_wav(media_root / str(index), media_name, frequency=330 + index * 110)
        if runtime.version == "2021.1":
            _save_sandbox_project(runtime)
        draft = _start_business_draft(runtime, "audio.import")
        target = _bind_business_object(
            runtime, draft, **({"object_id": voice_id} if voice_id else {
                "path_segments": (root, "Default Work Unit"),
            }),
        )
        row = (["--existing-row", "line", target] if voice_id else
               ["--new-row", "line", target, name, "sound-voice"])
        _update_business_draft(runtime, draft, "draft-declare-import-batch", [
            "--row-order", "line", *row,
            "--media-directory", str(media.parent), "--media-file", "line", media.name,
            "--field", "line", "language", language,
        ], live=False)
        result = _complete_business_draft(runtime, draft)
        voice = runtime.gateway([
            "query-object", "--path-segment", root, "--path-segment", "Default Work Unit",
            "--path-segment", name,
        ], live=True)
        assert voice["count"] == 1, voice
        current_id = voice["objects"][0]["id"]
        assert voice_id is None or current_id == voice_id
        voice_id = current_id
        sources = runtime.gateway([
            "query-object", "--exact-id", voice_id, "--relationship", "children",
            "--include", "source-language", "--max-results", "4",
        ], live=True)
        rows = sources["objects"]
        assert all(row["type"] == "AudioFileSource" for row in rows), rows
        assert all(isinstance(row["source_language"], Mapping) for row in rows), rows
        by_language = {row["source_language"]["name"]: row for row in rows}
        assert len(by_language) == len(rows), rows
        assert set(by_language) == ({"English(US)"} if index == 0 else {"English(US)", "Japanese"})
        snapshots.append(by_language)
        runtime.category_results.append({
            "category": "voice-language-reimport", "status": "PASS",
            "language": language, "step": index,
            "transaction_id": result["verify"]["transaction_id"],
            "verifier_strength": "voice_language_media_hash_and_source_identity",
        })
    assert snapshots[0]["English(US)"]["id"] == snapshots[2]["English(US)"]["id"]
    assert snapshots[1]["Japanese"] == snapshots[2]["Japanese"]
    assert snapshots[1]["Japanese"]["id"] == snapshots[3]["Japanese"]["id"]
    assert snapshots[2]["English(US)"] == snapshots[3]["English(US)"]
    # Independent byte checks on the test-owned Originals prove that the second
    # language was not replaced by the final English re-import.
    originals = runtime.sandbox.sandbox_path / "Originals" / "Voices"
    for language, source_index in (("English(US)", 2), ("Japanese", 3)):
        matches = list((originals / language).rglob(media_name + ".wav"))
        assert len(matches) == 1, matches
        assert hashlib.sha256(matches[0].read_bytes()).digest() == hashlib.sha256(
            (media_root / str(source_index) / (media_name + ".wav")).read_bytes()
        ).digest()


@pytest.mark.live
@pytest.mark.destructive
def test_music_playlist_canonical_query_create_and_import_parent(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Prove canonical type routing, not playlist order or playback behavior."""
    runtime = workflow_sandbox_runtime
    queried = runtime.gateway(["query-object", "--kind", "music-playlist-container", "--max-results", "2"], live=True)
    assert queried["ok"] is True
    root = "Containers" if runtime.version == "2025.1" else "Interactive Music Hierarchy"
    draft = _start_business_draft(runtime, "object.create")
    parent = _bind_business_object(runtime, draft, path_segments=(root, "Default Work Unit"))
    name = "Playlist_Type_" + uuid.uuid4().hex[:12]
    _update_business_draft(runtime, draft, "draft-declare-new", [
        "--declaration-id", "playlist", "--parent-handle", parent,
        "--name", name, "--kind", "music-playlist-container",
    ], live=False)
    created = _complete_business_draft(runtime, draft)
    playlist_id = _created_object_id(created["execute"])
    draft = _start_business_draft(runtime, "audio.import")
    parent = _bind_business_object(runtime, draft, object_id=playlist_id)
    _update_business_draft(runtime, draft, "draft-declare-import-batch", [
        "--row-order", "segment", "--new-row", "segment", parent, "Segment", "music-segment",
    ], live=False)
    imported = _complete_business_draft(runtime, draft)
    runtime.category_results.append({
        "category": "music-playlist-canonical-type", "status": "PASS",
        "verifier_strength": "closed_query_create_and_import_parent_not_playlist_playback",
        "transaction_ids": [created["verify"]["transaction_id"], imported["verify"]["transaction_id"]],
    })


def _restart_workflow_host_after_transport_loss(
    runtime: _WorkflowSandboxRuntime,
) -> None:
    """Restore the module host without retrying the indeterminate operation."""

    port = runtime.port
    shutdown_sandboxed_wwise(runtime.lifecycle, runtime.sandbox)
    wait_for_port_release(runtime.lifecycle.host, port)
    replacement = launch_sandboxed_wwise(
        runtime.sandbox,
        runtime.env,
        port=port,
    )
    assert replacement.port == port
    runtime.lifecycle = replacement


def _capture_workflow_pre_teardown_process(lifecycle: HeadlessLifecycle, state_dir: Path, *, version: str, candidate: str) -> None:
    """Snapshot only the owned launch handle before cleanup can change its state."""
    record = {"contract": "waapi-skill.workflow-pre-teardown-process/v1", "phase": "before_owned_shutdown",
        "captured_at_unix_ns": time.time_ns(), "candidate": candidate, "version": version,
        "owned_launch_pid": None, "observed_exit_code": None, "process_state": "unobserved",
        "capture_errors": []}
    def error(stage, exc):
        record["capture_errors"].append({"stage": stage, "type": type(exc).__name__,
            "message": str(exc).encode("utf-8", errors="replace")[:512].decode("utf-8", errors="ignore")})
    try:
        process = lifecycle.process
        if process is None:
            record["process_state"] = "not-started"
        else:
            pid = process.pid
            if type(pid) is not int or pid <= 0:
                raise ValueError("Owned launch PID must be a positive integer")
            record["owned_launch_pid"] = pid
            code = process.poll()  # No probe, process inventory, wait, signal or retry.
            if code is not None and type(code) is not int:
                raise ValueError("Owned poll result must be an exit integer or None")
            record.update(observed_exit_code=code, process_state="running" if code is None else "exited")
    except Exception as exc:
        error("owned_process_poll", exc)
    for stream in ("stdout", "stderr"):
        try:
            tail = lifecycle.output.tail(stream, max_lines=20)
            if not isinstance(tail, str):
                raise ValueError("Owned process output tail must be text")
            encoded = tail.encode("utf-8", errors="replace")
            record[stream + "_tail"] = encoded[-4096:].decode("utf-8", errors="ignore")
            record[stream + "_truncated"] = len(encoded) > 4096
        except Exception as exc:
            error(stream + "_tail", exc)
    record["capture_status"] = "partial" if record["capture_errors"] else "complete"
    state_dir.mkdir(parents=True, exist_ok=True)
    output = state_dir / "workflow-pre-teardown-process.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)


@pytest.fixture(scope="module")
def workflow_sandbox_runtime(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[_WorkflowSandboxRuntime]:
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
    source_mtime_before_ns: int | None = None
    source_mtime_after_ns: int | None = None
    deferred_error: BaseException | None = None
    runtime: _WorkflowSandboxRuntime | None = None
    task_root = tmp_path_factory.mktemp(f"gateway-workflows-{version.replace('.', '-')}")
    case_sandbox_root = lock.root / f"gateway-workflows-{uuid.uuid4().hex}"
    state_dir = task_root / "state"
    candidate = exact_git_candidate(REPO_ROOT)
    category_results: list[dict[str, Any]] = []
    started_at_unix_ns = time.time_ns()

    lock.__enter__()
    try:
        sandbox = prepare_sample_project_sandbox(
            env,
            sandbox_root=case_sandbox_root,
            hash_strategy="bounded",
        )
        source_hash_before = _hash_mutation_bearing_project_files(sandbox.source_root)
        source_tree_before = _source_tree_inventory(sandbox.source_root)
        source_mtime_before_ns = sandbox.source_project.stat().st_mtime_ns
        assert source_hash_before[1] > 0, "immutable SampleProject source has no regular files to hash"
        extra_languages = getattr(request, "param", ())
        if extra_languages:
            # Fixture setup only, before Wwise starts, on the disposable copy.
            # No user/source project or live WAAPI operation uses this path.
            assert path_is_under(sandbox.sandbox_project, case_sandbox_root)
            tree = ET.parse(sandbox.sandbox_project)
            languages = tree.find(".//LanguageList")
            assert languages is not None
            for language in extra_languages:
                assert language == "Japanese"
                assert not any(row.get("Name") == language for row in languages)
                ET.SubElement(languages, "Language", {
                    "Name": language, "ID": "{" + str(uuid.uuid4()).upper() + "}",
                })
            tree.write(sandbox.sandbox_project, encoding="utf-8", xml_declaration=True)
        if version in {"2022.1", "2025.1"}:
            prelaunch_io_root = case_sandbox_root / "prelaunch-io"
            prelaunch_io_root.mkdir(parents=True, exist_ok=False)
            prelaunch = normalize_project_copy(
                sandbox.sandbox_project,
                io_root=prelaunch_io_root,
                owned_root=case_sandbox_root,
                request=ProjectPrelaunchRequest(
                    scenario_id="gateway-workflow-transaction-matrix",
                    isolate_optional_sample_plugins=version == "2022.1",
                    auro_isolation_profile=(
                        WWISE_2025_SOUNDBANK_AURO_PROFILE
                        if version == "2025.1"
                        else None
                    ),
                ),
            )
            if version == "2022.1":
                assert prelaunch.optional_plugin_isolation is not None
                assert (
                    prelaunch.optional_plugin_isolation.remaining_optional_plugin_instances
                    == 0
                )
            else:
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
        active_error = sys.exc_info()[1]
        active_lifecycle = runtime.lifecycle if runtime is not None else lifecycle
        if active_lifecycle is not None and sandbox is not None:
            try:
                _capture_workflow_pre_teardown_process(active_lifecycle, state_dir, version=version, candidate=candidate)
            except BaseException as exc:  # diagnostics must not replace the verdict or skip cleanup
                try:
                    message = str(exc).encode("utf-8", errors="replace")[:512].decode("utf-8", errors="ignore")
                    print(f"pre-teardown process diagnostic capture failed: {type(exc).__name__}: {message}", file=sys.stderr)
                except BaseException:
                    pass
            try:
                shutdown_sandboxed_wwise(active_lifecycle, sandbox)
            except BaseException as exc:  # noqa: BLE001 - every teardown guard must still run
                deferred_error = deferred_error or exc

        if sandbox is not None and source_hash_before is not None:
            try:
                source_hash_after = _hash_mutation_bearing_project_files(sandbox.source_root)
                source_mtime_after_ns = sandbox.source_project.stat().st_mtime_ns
                if source_tree_before is not None:
                    source_tree_after = _source_tree_inventory(sandbox.source_root)
                if source_hash_after != source_hash_before:
                    raise AssertionError(
                        "immutable SampleProject source hash changed during gateway workflow test: "
                        f"before={source_hash_before[0]} after={source_hash_after[0]}"
                    )
                if source_mtime_after_ns != source_mtime_before_ns:
                    raise AssertionError(
                        "immutable SampleProject project mtime changed during gateway workflow test: "
                        f"before={source_mtime_before_ns} after={source_mtime_after_ns}"
                    )
                if source_tree_before is not None:
                    if source_tree_after != source_tree_before:
                        raise AssertionError(
                            "immutable SampleProject source tree metadata changed during gateway workflow test: "
                            f"before={source_tree_before} after={source_tree_after}"
                        )
            except BaseException as exc:  # noqa: BLE001 - sandbox cleanup still has to run
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
            deferred_error = finalize_exact_real_evidence(
                repo_root=REPO_ROOT,
                candidate=candidate,
                version=version,
                request=request,
                module_file=Path(request.module.__file__),
                started_at_unix_ns=started_at_unix_ns,
                active_error=active_error,
                deferred_error=deferred_error,
                sandbox=sandbox,
                lock=lock,
                state_dir=state_dir,
                host={
                    "display_name": sandbox.metadata.get_info_display_name,
                    "is_command_line": True,
                    "version": sandbox.metadata.get_info_version,
                },
                categories=category_results,
                source={
                    "project": str(sandbox.source_project),
                    "hash_scope": "all-source-regular-file-content",
                    "hash_algorithm": "sha256",
                    "hash_before": source_hash_before[0] if source_hash_before else None,
                    "hash_after": source_hash_after[0] if source_hash_after else None,
                    "file_count_before": source_hash_before[1] if source_hash_before else None,
                    "file_count_after": source_hash_after[1] if source_hash_after else None,
                    "bytes_hashed_before": source_hash_before[2] if source_hash_before else None,
                    "bytes_hashed_after": source_hash_after[2] if source_hash_after else None,
                    "mtime_before_ns": source_mtime_before_ns,
                    "mtime_after_ns": source_mtime_after_ns,
                    "tree_metadata_before": source_tree_before[0] if source_tree_before else None,
                    "tree_metadata_after": source_tree_after[0] if source_tree_after else None,
                },
                case_cleanup_root=case_sandbox_root,
            )
        else:
            try:
                lock.__exit__(None, None, None)
            except BaseException as exc:  # noqa: BLE001
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

    imported_ids: list[str] = []
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
        import_rows: list[dict[str, str]] = []
        for ordinal in ("FIRST", "SECOND"):
            import_name = (
                f"WAAPI_GATEWAY_AUDIO_{ordinal}_"
                f"{runtime.version.replace('.', '_')}_{unique_suffix}"
            )
            audio_file = _write_fixture_wav(
                runtime.sandbox.sandbox_path / "GatewayWorkflowAudio",
                import_name,
            )
            assert path_is_under(
                audio_file.resolve(strict=True),
                runtime.sandbox.sandbox_path.resolve(strict=True),
            )
            import_rows.append(
                {
                    "object_path": f"{object_parent}\\<Sound>{import_name}",
                    "audio_file": str(audio_file),
                    "object_type": "Sound",
                    "import_language": "SFX",
                    "notes": f"closed gateway audio import {ordinal.lower()} {import_name}",
                }
            )
        audio_import = _complete_transaction(
            runtime,
            operation="audio.import",
            arguments={"imports": import_rows},
        )
        for expected in import_rows:
            imported_row = _imported_object(
                audio_import["execute"],
                expected["object_path"],
            )
            imported_id = _required_string(imported_row, "id")
            imported_ids.append(imported_id)
            imported_path = _required_string(imported_row, "path")
            assert imported_path == _untyped_object_path(
                expected["object_path"]
            ), imported_row
            validate_audio_import_business_evidence(
                execution=audio_import["execute"],
                verification=audio_import["verification_evidence"],
                version=runtime.version,
                expected_target_path=imported_path,
                expected_target_id=imported_id,
                expected_notes=expected["notes"],
                source_file=expected["audio_file"],
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
            path_segments=FIXTURE_SWITCH_GROUP_SEGMENTS,
            expected_path=FIXTURE_SWITCH_GROUP_PATH,
        )
        switch_id = _query_exact_path_id(
            runtime,
            path_segments=FIXTURE_SWITCH_SEGMENTS,
            expected_path=FIXTURE_SWITCH_PATH,
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
            *imported_ids,
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
def test_cli_console_business_project_verify(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Verify one project through the deep CLI declaration and weak oracle."""

    runtime = workflow_sandbox_runtime
    api = "ak.wwise.cli.verify"
    schema = runtime.gateway(["request-schema", api], live=False)
    assert schema["input_shape"] == "business_declaration", schema
    assert schema["native_request_fields_disclosed"] is False, schema
    draft = _start_business_draft(runtime, api)
    _update_business_draft(
        runtime,
        draft,
        "draft-declare-cli-console-plan",
        [
            "--value", "project_file", str(runtime.sandbox.sandbox_project),
            "--value", "verbosity", "quiet",
        ],
        live=True,
    )
    result = _complete_core_result_schema_draft(runtime, draft)
    assert result["verify"]["verification"]["business_state_verified"] is False
    runtime.category_results.append(
        {
            "category": "cli-console-project-verify",
            "status": "PASS",
            "verifier_strength": "result_schema_and_external_harness_completion",
        }
    )


@pytest.mark.live
@pytest.mark.destructive
def test_cli_console_business_object_dump(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Write and inspect one exact object-dump artifact."""

    runtime = workflow_sandbox_runtime
    output_root = runtime.sandbox.sandbox_root / "cli-console-object-dump"
    output_root.mkdir(parents=True, exist_ok=False)
    dump_file = output_root / f"objects-{runtime.version}.txt"
    draft = _start_business_draft(runtime, "ak.wwise.cli.dumpObjects")
    _update_business_draft(
        runtime,
        draft,
        "draft-declare-cli-console-plan",
        [
            "--value", "project_file", str(runtime.sandbox.sandbox_project),
            "--value", "output_file", str(dump_file),
            "--value", "content", "property_sets",
            "--toggle", "include_session_objects", "disable",
        ],
        live=True,
    )
    result = _complete_core_result_schema_draft(runtime, draft)
    assert dump_file.is_file(), result
    assert dump_file.stat().st_size > 0
    runtime.category_results.append(
        {
            "category": "cli-console-object-dump",
            "status": "PASS",
            "verifier_strength": "result_schema_plus_exact_file_oracle",
            "requested_content": "property_sets",
            "include_session_objects": False,
            "artifact_observation": observe_console_file(dump_file, io_root=runtime.sandbox.sandbox_root),
        }
    )


@pytest.mark.live
@pytest.mark.destructive
def test_cli_console_media_id_file_observation(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    _check_cli_media_id_storage(workflow_sandbox_runtime, migrate_before_capture=False)


@pytest.mark.live
@pytest.mark.destructive
def test_cli_console_media_id_migrated_project_acceptance(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    _check_cli_media_id_storage(workflow_sandbox_runtime, migrate_before_capture=True)


def _check_cli_media_id_storage(runtime: _WorkflowSandboxRuntime, *, migrate_before_capture: bool) -> None:
    """Verify central storage against the saved private sandbox's media rows.

    Run this terminal CLI node in its own lifecycle. The setup save establishes
    the baseline after normal fixture normalization and Wwise serialization;
    it grants no coverage credit to the media operation.
    """
    project = runtime.sandbox.sandbox_project
    mapping = project.with_suffix(".mediaid")
    observation = {
        "category": ("cli-media-id-migrated-project" if migrate_before_capture
                     else "cli-media-id-file-format-observation"), "status": "FAIL",
        "verifier_strength": "gateway_exact_mapping_and_independent_saved_media_pairs",
        "baseline_setup": ("public_gateway_save_then_migrate_then_reopen_then_save_before_capture" if migrate_before_capture
                           else "public_gateway_project_save_before_capture"),
    }
    runtime.category_results.append(observation)
    if migrate_before_capture and runtime.version not in {"2023.1", "2024.1", "2025.1"}:
        observation.update(status="blocked", reason="The selected console.project.open route is absent from this pinned lane; migrated-media preparation needs owned lifecycle fixture work",
            selected_reopen_uri="ak.wwise.console.project.open",
            unassessed_alternative="ak.wwise.ui.project.open is reflected; its Console host eligibility and effect semantics need separate assessment",
            boundary="legacy_migrated_project_reopen_fixture", media_effect="not_executed")
        raise AssertionError({"setup_boundary": observation["boundary"], "category": observation})
    _save_sandbox_project(runtime)
    if migrate_before_capture:
        setup_stage = "setup_migration"
        try:
            observation[setup_stage] = {"status": "preparing", "coverage_credit": "none; baseline preparation only"}
            setup = _start_business_draft(runtime, "ak.wwise.cli.migrate")
            observation[setup_stage]["draft_id"] = setup.draft_id
            _update_business_draft(runtime, setup, "draft-declare-cli-console-plan",
                ["--value", "project_file", str(project)], live=True)
            migration = _complete_core_result_schema_draft(runtime, setup, allow_verified_setup=True)
            observation[setup_stage].update(status="complete", transaction_id=migration["verify"]["transaction_id"],
                state=migration["verify"]["state"],
                business_state_verified=migration["verify"]["verification"]["business_state_verified"], responses=migration)
            # Native migrate closes the project without ending this Console
            # instance. Reopen through a separately authorized public operation;
            # neither restart nor schema-only setup can certify the live identity.
            setup_stage = "setup_reopen"
            observation[setup_stage] = {"status": "preparing", "project_file": str(project),
                "coverage_credit": "none; baseline preparation only"}
            reopen = _start_business_draft(runtime, "ak.wwise.console.project.open")
            observation[setup_stage]["draft_id"] = reopen.draft_id
            _update_business_draft(runtime, reopen, "draft-declare-cli-console-plan",
                ["--value", "project_file", str(project)], live=True)
            reopened = _complete_business_draft(runtime, reopen)
            observation[setup_stage].update(status="complete", transaction_id=reopened["verify"]["transaction_id"],
                state=reopened["verify"]["state"], business_state_verified=reopened["verify"]["verification"]["business_state_verified"],
                verification=reopened["verify"]["verification"], responses=reopened)
            # Reopening can materialize newly loaded in-memory objects. Save that
            # loaded state before any disk-authority baseline or media Preview.
            setup_stage = "setup_reopen_save"
            observation[setup_stage] = {"status": "preparing",
                "coverage_credit": "none; baseline preparation only"}
            saved = _save_sandbox_project(runtime)
            observation[setup_stage].update(status="complete", transaction_id=saved["verify"]["transaction_id"],
                state=saved["verify"]["state"],
                business_state_verified=saved["verify"]["verification"]["business_state_verified"], responses=saved)
        except AssertionError as exc:
            observation[setup_stage]["status"] = "FAIL"
            observation[setup_stage]["failure"] = (exc.args[0] if exc.args and isinstance(exc.args[0], Mapping) else str(exc))
            raise
    assert not mapping.exists(), "This case requires the original Work Unit storage fixture"
    image_root = runtime.state_dir.parent / ("cli-media-id-images-" + uuid.uuid4().hex)
    image_root.mkdir(parents=True, exist_ok=False)
    images = observation["model_images"] = {"root": str(image_root), "before": {}, "after": {},
        "business_effect_verified": False}
    before = ConsoleModelImageIndex(root=image_root, project=project, phase="before", link=images["before"])
    sample = sample_observation = None
    expected, work_units = [], []
    path = project
    try:
        before.save(project, observe_console_file(project, io_root=project.parent))
        for path in project.parent.rglob("*"):
            if not path.name.casefold().endswith(".wwu"):
                continue
            work_units.append(path)
            assert len(work_units) <= before.MAX_WORK_UNITS, "Console model Work Unit count exceeded"
        work_units.sort()
        for path in work_units:
            candidate = observe_console_file(path, io_root=project.parent)
            raw = before.save(path, candidate)
            for owner in ET.fromstring(raw).iter():
                for media in owner.findall("./MediaIDList/MediaID"):
                    assert owner.get("ID") and media.get("ID")
                    expected.append([owner.attrib["ID"].upper(), media.attrib["ID"]])
                    assert len(expected) <= 100000
                    if sample is None:
                        sample, sample_observation = path, candidate
        assert sample is not None, "A media-ID-free project cannot establish migration effects"
        before.finish()
    except Exception as exc:
        before.error(path, exc)
        try:
            before.finish()
        except Exception as retention_error:
            images["before"].update(complete=False, finalization_error=str(retention_error)[:2048])
        raise
    observation.update(source_work_unit=sample_observation, baseline_media_pairs=sorted(expected))
    try:
        draft = _start_business_draft(runtime, "ak.wwise.cli.moveMediaIdsToSingleFile")
        _update_business_draft(runtime, draft, "draft-declare-cli-console-plan",
            ["--value", "project_file", str(project)], live=True)
        def bind_retained_baseline(preview):
            transaction_id = _required_string(preview, "transaction_id")
            stored = TransactionStore(runtime.state_dir).load_preview(transaction_id)
            prepared = stored.artifact["prepared_operation"]
            effect = prepared["pre_state"]["cli_project_effect"]
            files = {Path(relative).as_posix(): row for relative, row in effect["model_before"]["files"].items()}
            observation["transaction_id"] = transaction_id
            images["preview_binding"] = {"transaction_id": transaction_id,
                "artifact_hash": stored.artifact_hash, "matches_before_images": False}
            assert (prepared["dispatch"]["uri"] == "ak.wwise.cli.moveMediaIdsToSingleFile"
                and images["before"]["complete"] and set(files) == set(before.files)
                and all(row["status"] == "captured" and row["file_proof"] == files[relative]["proof"]
                    for relative, row in before.files.items())), "MEDIA_BASELINE_PREVIEW_MISMATCH"
            images["preview_binding"]["matches_before_images"] = True
        result = _complete_business_draft(runtime, draft, inspect_preview=bind_retained_baseline)
        observation["transaction_id"] = result["verify"]["transaction_id"]
        captured = observe_console_file(mapping, io_root=project.parent)
        document = ET.fromstring(base64.b64decode(captured["content_base64"], validate=True))
        actual = [[owner.attrib["ID"].upper(), media.attrib["ID"]]
            for owner in document.findall("./MediaIDInfo/MediaIDs/Language/File/WObject")
            for media in owner.findall("MediaID")]
        assert sorted(actual) == sorted(expected), "Saved source/media multiset differs from central mapping"
        observation["status"] = "PASS"
    finally:
        capture_errors = []
        after = None
        try:
            after = ConsoleModelImageIndex(root=image_root, project=project, phase="after", link=images["after"])
            after_paths = set(work_units)
            try:
                for path in project.parent.rglob("*"):
                    if not path.name.casefold().endswith(".wwu"):
                        continue
                    after_paths.add(path)
                    assert len(after_paths) <= after.MAX_WORK_UNITS, "Console after-image path count exceeded"
            except Exception as exc:
                after.error(None, exc)
                capture_errors.append("after_enumeration")
            for path in [project, *sorted(after_paths)[:after.MAX_WORK_UNITS]]:
                try:
                    candidate = observe_console_file(path, io_root=project.parent)
                    raw = after.save(path, candidate)
                    if path != project and ET.fromstring(raw).findall(".//MediaIDList/MediaID"):
                        capture_errors.append("work_unit_media_ids_remain:" + path.relative_to(project.parent).as_posix())
                except Exception as exc:
                    after.error(path, exc)
                    capture_errors.append("after_capture:" + path.relative_to(project.parent).as_posix())
            after.finish()
        except Exception as exc:
            if after is not None:
                after.error(None, exc)
            images["after"].update(complete=False, finalization_error=str(exc)[:2048])
            capture_errors.append("after_finalization")
        if capture_errors:
            observation["status"] = "FAIL"
        # Preserve diagnostic bytes even when Gateway verification rejects the
        # result. This is local artifact capture, never another native attempt.
        for key, path in (("mapping_file", mapping), ("source_work_unit_after", sample)):
            try:
                observation[key] = observe_console_file(path, io_root=project.parent)
            except Exception as exc:
                observation[key] = {"capture_error": str(exc)}
                capture_errors.append(key)
                observation["status"] = "FAIL"
    assert not capture_errors, capture_errors


@pytest.mark.live
@pytest.mark.destructive
def test_cli_console_business_soundbank_generate(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Generate real SoundBanks through Gateway-owned platform mapping."""

    runtime = workflow_sandbox_runtime
    generated_root = runtime.sandbox.sandbox_root / "cli-console-generated"
    generated_banks = generated_root / "Windows"
    generated_banks.mkdir(parents=True, exist_ok=False)
    api = "ak.wwise.cli.generateSoundbank"
    schema = runtime.gateway(["request-schema", api], live=False)
    assert schema["input_shape"] == "business_declaration", schema
    draft = _start_business_draft(runtime, api)
    _update_business_draft(
        runtime,
        draft,
        "draft-declare-cli-console-plan",
        [
            "--value", "project_file", str(runtime.sandbox.sandbox_project),
            "--item", "platforms", "Windows",
            "--toggle", "skip_languages", "enable",
            "--value", "source_control", "disabled",
            "--value", "root_output_directory", str(generated_root),
            "--mapping", "soundbank_directories_by_platform", "Windows", str(generated_banks),
            "--value", "verbosity", "quiet",
        ],
        live=True,
    )
    result = _complete_core_result_schema_draft(runtime, draft)
    generated_files = tuple(generated_root.rglob("*.bnk"))
    assert generated_files, result
    runtime.category_results.append(
        {
            "category": "cli-console-soundbank-generate",
            "status": "PASS",
            "verifier_strength": "result_schema_plus_soundbank_file_oracle",
        }
    )


@pytest.mark.live
@pytest.mark.destructive
def test_host_ui_debug_business_schema_read(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Read one real reflected schema through the bounded business route."""

    runtime = workflow_sandbox_runtime
    target = "ak.wwise.core.object.get"
    command = ["waapi-schema", target]
    if runtime.version in {"2024.1", "2025.1"}:
        command.append("--include-examples")
    schema = runtime.gateway(command, live=True)
    assert schema["schema_target"] == target
    assert schema["call"]["api"] == "ak.wwise.waapi.getSchema"
    assert schema["call"]["ok"] is True
    request_validation = schema["schema_validation"]["request"]
    result_validation = schema["schema_validation"]["result"]
    assert request_validation["uri"] == "ak.wwise.waapi.getSchema"
    assert request_validation["section"] == "request"
    assert request_validation["validated_nodes"] > 0
    assert result_validation["uri"] == "ak.wwise.waapi.getSchema"
    assert result_validation["section"] == "result"
    assert result_validation["validated_nodes"] > 0
    agent_result = schema["agent_result"]
    assert isinstance(agent_result, Mapping)
    assert agent_result
    runtime.category_results.append(
        {
            "category": "host-ui-debug-waapi-schema",
            "status": "PASS",
            "verifier_strength": "real_result_schema_and_bounded_projection",
        }
    )


def _collect_stationary_tone_characterization(runtime: _WorkflowSandboxRuntime) -> dict[str, Any]:
    """Retain four exact native observations; do not certify a signal algorithm."""
    from wwise_waapi.operation_soundbank import capture_file_proof
    from wwise_waapi.native_catalog import load_native_catalog
    assert runtime.version in {'2023.1', '2024.1', '2025.1'}, 'Tone is absent from the pinned older routes'
    catalog = load_native_catalog(runtime.version, 'wwise-console')
    assert 'ak.wwise.debug.generateToneWAV' in catalog['functions']
    assert 'ak.wwise.debug.generateToneWAV' in catalog['schemas']
    catalog_identity = {'host': 'wwise-console', 'version': runtime.version,
        'build': catalog['provenance']['build'], 'content_sha256': catalog['content_sha256']}
    output = runtime.state_dir / 'tone-stationary-characterization.json'
    assert not output.exists(), 'Never overwrite an original Tone characterization'
    runtime.state_dir.mkdir(parents=True, exist_ok=True)
    artifacts = runtime.state_dir / 'tone-stationary-artifacts'; artifacts.mkdir(exist_ok=False)
    native_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    prior_native = set(native_root.glob('*.json'))
    tone_root = runtime.sandbox.sandbox_root / 'tone-stationary-output'; tone_root.mkdir(exist_ok=False)
    config = Path(runtime.env['WAAPI_SKILL_CONFIG_PATH'])
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    lifecycle_path = runtime.env.get('WWISE_CATEGORY_EVIDENCE_PATH')
    if lifecycle_path is None and sys.platform == 'darwin':
        lifecycle_path = runtime.env.get('WWISE_MACOS_CATEGORY_EVIDENCE_PATH')
    lifecycle_path = Path(lifecycle_path).expanduser().resolve(strict=False) if lifecycle_path else (
        REPO_ROOT / EVIDENCE_ROOT / (current_evidence_platform() + '-category-evidence.jsonl'))
    category = {'category': 'tone-stationary-characterization', 'status': 'FAIL',
        'diagnostic_only': True, 'business_effect_verified': False, 'coverage_credit': 'none; characterization only',
        'verifier_strength': 'exact_native_file_bytes_and_public_receipts_only; signal_oracle_unimplemented',
        'observation_path': str(output), 'reason': 'collection incomplete'}
    runtime.category_results.append(category)
    receipt: dict[str, Any] = {'contract': 'waapi-skill.tone-stationary-characterization/v1',
        'candidate': runtime.candidate, 'version': runtime.version, 'native_catalog': catalog_identity, 'calls': [], 'phases': [],
        'native_evidence': [], 'collection_complete': False, 'business_effect_verified': False,
        'coverage_credit': 'none; characterization only', 'config_sha256': config_hash,
        'source_project': str(runtime.sandbox.source_project),
        'endpoint': {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url},
        'lifecycle_final_reference': {'path': str(lifecycle_path), 'contract': 'waapi-skill.host-category-evidence/v3',
            'phase': 'final', 'candidate': runtime.candidate, 'category': category['category'],
            'transaction_ids': [], 'cleanup_status': 'unresolved_until_final_row'},
        'lifecycle_acceptance': 'Requires the matching final category row with all four transaction IDs, source before/after hash/mtime/tree and residual process cleanup; prepared/PENDING is not cleanup success.',
        'limits': {'calls': 48, 'reply_bytes': 256 * 1024, 'total_reply_bytes': 8 * 1024 * 1024,
            'wav_files': 4, 'file_bytes': 8 * 1024 * 1024, 'native_files': 512,
            'native_bytes': 32 * 1024 * 1024, 'archive_bytes': 72 * 1024 * 1024,
            'receipt_bytes': 256 * 1024}, 'archive_bytes': 0, 'total_reply_bytes': 0}
    attempted: set[str] = set()
    def persist():
        raw = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(raw) <= receipt['limits']['receipt_bytes'], 'Tone receipt exceeds its bound'
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(raw); temporary.replace(output)
        category['observation_sha256'] = hashlib.sha256(raw).hexdigest()
    def archive(name, raw):
        assert len(raw) <= receipt['limits']['file_bytes'], 'Tone archived file exceeds its bound'
        assert receipt['archive_bytes'] + len(raw) <= receipt['limits']['archive_bytes'], 'Tone archive exceeds its bound'
        path = artifacts / name
        prove_artifact_path(path, io_root=artifacts, field='Tone archive', expect_directory=False)
        descriptor = os.open(path, binary_file_open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        proof = capture_file_proof(path, field='Tone archive', max_bytes=receipt['limits']['file_bytes'], io_root=artifacts)
        assert proof['sha256'] == hashlib.sha256(raw).hexdigest() and proof['size'] == len(raw), proof
        receipt['archive_bytes'] += len(raw)
        return {'path': str(path), 'sha256': proof['sha256'], 'size': len(raw), 'proof': proof}
    class Gateway:
        def call(self, argv, *, live, allow_failure=False):
            assert len(receipt['calls']) < receipt['limits']['calls'], 'Tone public call bound exceeded'
            if argv[0] == 'execute':
                assert argv[1] not in attempted, 'Never retry a Tone execution'
                attempted.add(argv[1])
            row: dict[str, Any] = {'argv': list(argv)}; receipt['calls'].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                assert len(raw) <= receipt['limits']['reply_bytes'], 'Tone reply exceeds its bound'
                receipt['total_reply_bytes'] += len(raw)
                assert receipt['total_reply_bytes'] <= receipt['limits']['total_reply_bytes'], 'Tone replies exceed their bound'
                row.update(exit_code=code, reply=archive('reply-' + str(len(receipt['calls'])) + '.json', raw))
                if not allow_failure: assert code == 0 and payload.get('ok') is True, payload
                if live:
                    assert payload.get('detected_version') == runtime.version, payload
                    assert payload.get('endpoint') == receipt['endpoint'], payload
                return code, payload
            except Exception as exc:
                row['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
                raise
            finally:
                persist()
        def gateway(self, argv, *, live):
            return self.call(argv, live=live)[1]
    gateway = Gateway()
    def capture_wave(phase):
        if 'wav' in phase: return
        observed = observe_console_file(Path(phase['output_path']), io_root=tone_root)
        raw = base64.b64decode(observed['content_base64'], validate=True)
        copied = archive(phase['name'] + '.wav', raw)
        phase['wav'] = {'archive_path': copied['path'], 'archive_proof': copied['proof'],
            'native_file_proof': observed['file_proof'], 'representation': 'uninterpreted_native_file_bytes'}
        persist()
    persist()
    try:
        status = gateway.gateway(['status'], live=True)
        info_call = next(row for row in status['calls'] if row['api'] == 'ak.wwise.core.getInfo')
        info_observed = observe_console_file(Path(info_call['evidence_path']), io_root=native_root)
        info_evidence = json.loads(base64.b64decode(info_observed['content_base64'], validate=True))
        receipt['get_info'] = info_evidence['result']
        assert receipt['get_info']['isCommandLine'] is True, 'Characterization requires WwiseConsole'
        version = receipt['get_info']['version']
        assert tuple(version[k] for k in ('year', 'major', 'minor', 'build')) == tuple(
            int(part) for part in catalog_identity['build'].split('.')), version
        gateway.gateway(['request-schema', 'ak.wwise.debug.generateToneWAV'], live=False)
        for depth, level in [('int16', 0), ('int16', -6), ('float32', 0), ('float32', -6)]:
            phase = {'name': depth + '-' + str(abs(level)) + 'db', 'bit_depth': depth, 'sustain_db': level,
                'output_path': str(tone_root / (depth + '-' + str(abs(level)) + 'db.wav')),
                'execution_attempted': False, 'signal_verified': False}
            receipt['phases'].append(phase); persist()
            try:
                draft = _start_business_draft(gateway, 'ak.wwise.debug.generateToneWAV')
                _update_business_draft(gateway, draft, 'draft-declare-host-plan', [
                    '--value', 'output_file', phase['output_path'], '--value', 'waveform', 'sine',
                    '--value', 'frequency_hz', '440', '--value', 'channel_layout', '1.0',
                    '--value', 'bit_depth', depth, '--value', 'sample_rate_hz', '48000',
                    '--value', 'attack_seconds', '0', '--value', 'sustain_seconds', '0.25',
                    '--value', 'release_seconds', '0', '--value', 'sustain_db', str(level)], live=True)
                _update_business_draft(gateway, draft, 'draft-check', live=True)
                preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
                tx = phase['transaction_id'] = preview['transaction_id']
                ids = receipt['lifecycle_final_reference']['transaction_ids']
                assert tx not in ids; ids.append(tx)
                shown = gateway.gateway(['transaction-show', tx], live=False)
                phase['preview_transaction'] = receipt['calls'][-1]['reply']
                gateway.gateway(['confirm', tx, '--confirmation-token', shown['confirmation']['token']], live=False)
                phase['execution_attempted'] = True; persist()
                executed = gateway.gateway(['execute', tx], live=True)
                phase['execute_state'] = executed.get('state')
                assert executed.get('state') == 'executed_unverified', executed
                capture_wave(phase)  # Retain bytes before a partial/failed verifier can stop the collector.
                code, verified = gateway.call(['verify', tx], live=True, allow_failure=True)
                phase['verification'] = {'exit_code': code, 'state': verified.get('state'),
                    'business_state_verified': verified.get('verification', {}).get('business_state_verified'),
                    'verification_strength': verified.get('verification_strength')}
            finally:
                if phase['execution_attempted'] and 'wav' not in phase and Path(phase['output_path']).exists():
                    capture_wave(phase)
                if phase.get('transaction_id'):
                    gateway.gateway(['transaction-show', phase['transaction_id']], live=False)
                    phase['transaction'] = receipt['calls'][-1]['reply']
                persist()
        final_status = gateway.gateway(['status'], live=True)
        assert final_status['wwise'] == status['wwise'], 'Tone host context changed during characterization'
        assert hashlib.sha256(config.read_bytes()).hexdigest() == config_hash, 'Tone diagnostic configuration changed'
    except Exception as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
        raise
    finally:
        try:
            paths = sorted(set(native_root.glob('*.json')) - prior_native)
            assert len(paths) <= receipt['limits']['native_files'], 'Tone native evidence count bound exceeded'
            total = 0
            for index, path in enumerate(paths):
                observed = observe_console_file(path, io_root=native_root)
                raw = base64.b64decode(observed['content_base64'], validate=True)
                total += len(raw); assert total <= receipt['limits']['native_bytes'], 'Tone native evidence byte bound exceeded'
                receipt['native_evidence'].append({'native_path': str(path), **archive('native-' + str(index) + '.json', raw)})
        except Exception as exc:
            receipt['archive_failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
            category.update(status='FAIL', reason='native evidence archive incomplete')
            raise
        finally:
            persist()
    receipt['collection_complete'] = True
    category.update(status='blocked', reason='four native files collected; signal/level oracle and other host/version evidence remain unfinished')
    persist()
    return category


@pytest.mark.live
@pytest.mark.destructive
def test_stationary_tone_console_characterization(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    category = _collect_stationary_tone_characterization(workflow_sandbox_runtime)
    assert category['status'] == 'blocked' and category['diagnostic_only'] is True, category


@pytest.mark.live
@pytest.mark.destructive
def test_host_ui_debug_business_generates_exact_tone_wav(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Generate one real WAV from business audio units and inspect the artifact."""

    runtime = workflow_sandbox_runtime
    if runtime.version not in {"2023.1", "2024.1", "2025.1"}:
        pytest.skip("generateToneWAV is reflected only in Wwise 2023.1+")
    output_root = runtime.sandbox.sandbox_root / "host-ui-debug-tone"
    output_root.mkdir(parents=True, exist_ok=False)
    output_file = output_root / f"tone-{runtime.version}.wav"
    operation = "ak.wwise.debug.generateToneWAV"
    schema = runtime.gateway(["request-schema", operation], live=False)
    assert schema["input_shape"] == "business_declaration", schema
    draft = _start_business_draft(runtime, operation)
    _update_business_draft(
        runtime,
        draft,
        "draft-declare-host-plan",
        [
            "--value", "output_file", str(output_file),
            "--value", "waveform", "sine",
            "--value", "frequency_hz", "440",
            "--value", "channel_layout", "2.0",
            "--value", "bit_depth", "int16",
            "--value", "sample_rate_hz", "48000",
            "--value", "attack_seconds", "0.05",
            "--value", "sustain_seconds", "1",
            "--value", "release_seconds", "0.1",
            "--value", "sustain_db", "-6",
            "--toggle", "anonymous_channels", "enable",
            "--item", "waveform_channels", "0",
            "--item", "waveform_channels", "1",
        ],
        live=True,
    )
    result = _complete_core_result_schema_draft(runtime, draft)
    assert output_file.is_file(), result
    assert output_file.stat().st_size > 44
    generated = _read_pcm_wave_header(output_file)
    assert generated.channels == 2
    assert generated.sample_width_bytes == 2
    assert generated.sample_rate_hz == 48000
    assert generated.frame_count == pytest.approx(55200, abs=4)
    runtime.category_results.append(
        {
            "category": "host-ui-debug-tone-wav",
            "status": "PASS",
            "verifier_strength": "result_schema_plus_exact_wav_header_oracle",
        }
    )


@pytest.mark.live
@pytest.mark.destructive
def test_cli_console_business_project_open_transition(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Open the same sandbox through the project-transition verifier."""

    runtime = workflow_sandbox_runtime
    if runtime.version not in {"2023.1", "2024.1", "2025.1"}:
        pytest.skip("Console project.open is reflected only in Wwise 2023.1+")
    draft = _start_business_draft(runtime, "ak.wwise.console.project.open")
    _update_business_draft(
        runtime,
        draft,
        "draft-declare-cli-console-plan",
        [
            "--value", "project_file", str(runtime.sandbox.sandbox_project),
            "--toggle", "auto_checkout", "disable",
            "--value", "migration_policy", "fail",
        ],
        live=True,
    )
    opened = _complete_business_draft(runtime, draft)
    assert opened["verify"]["verification"]["business_state_verified"] is True
    runtime.category_results.append(
        {
            "category": "cli-console-project-transition",
            "status": "PASS",
            "verifier_strength": "result_schema_and_project_transition",
        }
    )


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
        location_id = _query_exact_path_id(
            runtime,
            path_segments=(
                CONTAINERS_PARENT_SEGMENTS
                if runtime.version == "2025.1"
                else ACTOR_MIXER_PARENT_SEGMENTS
            ),
            expected_path=object_parent,
        )
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
    draft = _start_business_draft(runtime, operation)
    owner = _bind_business_object(runtime, draft, object_id=object_id)
    discovered = _update_business_draft(
        runtime, draft, "draft-discover-fields",
        ["--object-handle", owner, "--meaning", field_name,
         *([] if platform is None else ["--platform", platform])], live=True,
    )
    candidates = discovered["field_candidates"]
    assert len(candidates) == 1, discovered
    field = candidates[0]["handle"]
    if operation == "object.setReference":
        outcome = ["--clear-reference"] if clear_reference else [
            "--target-handle", _bind_business_object(
                runtime, draft, object_id=target_id,
            ),
        ]
    elif operation == "object.setLinked":
        outcome = ["--link-state", "linked" if linked else "unlinked"]
    else:
        outcome = ["--business-value", json.dumps(value)]
    _update_business_draft(runtime, draft, "draft-declare-field-change", [
        "--object-handle", owner, "--field-handle", field, *outcome,
    ], live=False)
    _update_business_draft(runtime, draft, "draft-check", live=True)
    preview = _update_business_draft(runtime, draft, "preview-from-draft", live=True)
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
        _complete_object_metadata_business_transaction(
            runtime,
            operation="object.setReference",
            object_id=source_id,
            field_name="Attenuation",
            clear_reference=True,
            platform="Windows",
        )
        if runtime.version in {"2023.1", "2024.1", "2025.1"}:
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
        weather_handle = declared_business_object_handle(declared_root, "weather")
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

        rain_path = f"{root_path}\\{rain_name}"
        wind_path = f"{root_path}\\{wind_name}"
        rain_id = _query_exact_path_id(
            runtime,
            path_segments=(*root_segments, weather_name, rain_name),
            expected_path=rain_path,
        )
        wind_id = _query_exact_path_id(
            runtime,
            path_segments=(*root_segments, weather_name, wind_name),
            expected_path=wind_path,
        )

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


@pytest.mark.live
@pytest.mark.destructive
def test_rtpc_empty_create_update_delete_recreate_across_selected_version(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Exercise the real list lifecycle, not a pre-populated Weather fixture."""
    runtime = workflow_sandbox_runtime
    if runtime.version == "2021.1":
        code, payload = runtime.raw_gateway(["draft-start", "object.setRTPC"])
        assert code != 0 and payload["ok"] is False
        assert payload["error_code"] == "UNAVAILABLE_IN_VERSION"
        runtime.category_results.append({"category": "rtpc-list-lifecycle", "status": "PASS", "verifier_strength": "explicit_2021_unsupported_boundary"})
        return

    suffix = uuid.uuid4().hex[:10]
    sound_id: str | None = None
    control_id: str | None = None
    try:
        sound_id = _create_object(runtime, parent=CONTAINERS_PARENT if runtime.version == "2025.1" else ACTOR_MIXER_PARENT, object_type="Sound", name=f"RTPC_Empty_{suffix}")
        control_id = _create_object(runtime, parent=GAME_PARAMETERS_PARENT, object_type="GameParameter", name=f"RTPC_Input_{suffix}")
        original_rtpc_id: str | None = None
        for mode, middle_y in (("add-only", "-12"), ("add-or-update", "-6"), ("add-only", "-9")):
            draft = _start_business_draft(runtime, "object.setRTPC")
            owner = _bind_business_object(runtime, draft, object_id=sound_id)
            field = _discover_business_field(runtime, draft, object_handle=owner, meaning="volume")
            control = _bind_business_object(runtime, draft, object_id=control_id)
            _update_business_draft(runtime, draft, "draft-declare-rtpc", [
                "--object-handle", owner, "--field-handle", field,
                "--control-input-handle", control, "--mode", mode,
                "--point", "0", "-48", "Linear", "--point", "50", middle_y, "Linear",
                "--point", "100", "0", "Linear",
            ], live=False)
            result = _complete_business_draft(runtime, draft)
            transaction_id = str(result["preview"]["transaction_id"])
            events = TransactionStore(runtime.state_dir).read_events(transaction_id)
            verifications = [event["details"]["verification"] for event in events if event.get("event_type") == "verification_recorded"]
            assert len(verifications) == 1
            assert waapi_gateway.canonical_sha256(verifications[0]) == result["verify"]["stdout_projection"]["verification_canonical_sha256"]
            readbacks = verifications[0]["readbacks"]
            rtpc_rows = [row for entry in readbacks for row in entry.get("result", {}).get("return", []) if row.get("type") == "RTPC"]
            assert len(rtpc_rows) == 1, readbacks
            rtpc_id = str(rtpc_rows[0]["id"])
            assert rtpc_rows[0]["@Curve"]["points"][1]["y"] == float(middle_y)
            if mode == "add-or-update":
                assert rtpc_id == original_rtpc_id, "update must preserve RTPC identity"
                delete = _start_business_draft(runtime, "object.delete")
                _bind_business_object(runtime, delete, object_id=rtpc_id, role="object")
                _update_business_draft(runtime, delete, "draft-declare-object-change", live=False)
                code, rejected = runtime.raw_gateway([
                    "draft-check", delete.draft_id, "--task-authority", delete.task_authority,
                    "--expected-revision", str(delete.revision),
                ])
                assert code != 0 and rejected["error_code"] == "EMBEDDED_OBJECT_DELETE_BOUNDARY", rejected
                # Delete/recreate the disposable owner, not an unsupported
                # RTPC deletion. This is fixture lifecycle, never a fallback.
                _delete_if_present_via_transaction(runtime, sound_id)
                sound_id = None
                sound_id = _create_object(runtime, parent=CONTAINERS_PARENT if runtime.version == "2025.1" else ACTOR_MIXER_PARENT, object_type="Sound", name=f"RTPC_Empty_{suffix}")
            elif original_rtpc_id is None:
                original_rtpc_id = rtpc_id
            else:
                assert rtpc_id != original_rtpc_id, "recreate must follow a proven empty list"
        runtime.category_results.append({"category": "rtpc-list-lifecycle", "status": "PASS", "verifier_strength": "empty_create_update_rtpc_delete_boundary_owner_delete_recreate"})
        for index in range(2):
            plugin = _start_business_draft(runtime, "object.createPlugin")
            owner = _bind_business_object(runtime, plugin, object_id=sound_id)
            plugin_type = _discover_business_type(
                runtime, plugin, meaning="Wwise Gain", role="effect",
                expected_label="Wwise Gain",
            )
            _update_business_draft(runtime, plugin, "draft-declare-existing", [
                "--declaration-id", f"effect-{index}", "--object-handle", owner,
                "--field", "plugin_role", "effect",
                "--field", "plugin_name", f"Gain_{index}",
                "--field", "plugin_type_handle", plugin_type,
            ], live=False)
            _complete_business_draft(runtime, plugin)
        runtime.category_results.append({"category": "effect-list-lifecycle", "status": "PASS", "verifier_strength": "first_effect_create_and_append_preserves_existing"})
    finally:
        if sound_id is not None:
            _delete_if_present_via_transaction(runtime, sound_id)
        if control_id is not None:
            _delete_if_present_via_transaction(runtime, control_id)


def _save_sandbox_project(runtime: _WorkflowSandboxRuntime) -> dict[str, Mapping[str, Any]]:
    """Persist prior sandbox mutations before a file-authority operation."""

    api = "ak.wwise.core.project.save"
    schema = runtime.gateway(["request-schema", api], live=False)
    if schema.get("input_shape") == "business_declaration":
        continuation = schema.get("continuation")
        assert continuation == {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", api],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        }, continuation
        draft = _start_business_draft(runtime, api)
        _update_business_draft(
            runtime,
            draft,
            "draft-declare-core-plan",
            ["--value", "auto_check_out", "false"],
            live=True,
        )
        saved = _complete_core_result_schema_draft(runtime, draft)
        assert saved["verify"]["state"] == (
            TransactionState.RESULT_SCHEMA_CHECKED.value
        ), saved
        return saved

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

    return {"preview": preview, "execute": executed, "verify": verified}


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


def _write_fixture_wav(root: Path, name: str, *, frequency: int = 440) -> Path:
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
            value = int(amplitude * math.sin(2 * math.pi * frequency * index / sample_rate))
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


SOURCE_HASH_MAX_FILES = 20_000
SOURCE_HASH_MAX_ENTRIES = 40_000
SOURCE_HASH_MAX_BYTES = 512 * 1024 * 1024
SOURCE_HASH_MAX_DEPTH = 64
SOURCE_HASH_CHUNK_BYTES = 1024 * 1024


def _hash_mutation_bearing_project_files(root: Path) -> tuple[str, int, int]:
    """Hash every regular source file, including media; retain the legacy helper name.

    Framing matches hash_project(..., preferred_strategy="full"): sorted paths,
    relative UTF-8 path, NUL, complete file bytes, NUL. Preflight the entire tree
    before reading content, and reject links/reparse points and bound violations.
    No large-source fallback may silently narrow this source-protection proof.
    """

    root_info = root.lstat()
    if path_is_link_or_reparse(root, metadata=root_info) or not stat.S_ISDIR(root_info.st_mode):
        raise SandboxFixtureError("source hash root must be a directory, not a link or reparse point")
    pending = [(root, 0)]
    files = []
    entries_seen = total_bytes = 0
    while pending:
        directory, depth = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                entries_seen += 1
                if entries_seen > SOURCE_HASH_MAX_ENTRIES:
                    raise SandboxFixtureError("source hash tree-entry bound exceeded")
                path = Path(entry.path)
                # Windows DirEntry.stat may omit the device/file identity.
                # Use the same path API as the subsequent race checks.
                info = path.lstat()
                if path_is_link_or_reparse(path, metadata=info):
                    raise SandboxFixtureError("source hash rejects links and reparse points")
                if stat.S_ISDIR(info.st_mode):
                    if depth + 1 > SOURCE_HASH_MAX_DEPTH:
                        raise SandboxFixtureError("source hash directory-depth bound exceeded")
                    pending.append((path, depth + 1))
                elif stat.S_ISREG(info.st_mode):
                    files.append((path, info))
                    total_bytes += info.st_size
                    if len(files) > SOURCE_HASH_MAX_FILES or total_bytes > SOURCE_HASH_MAX_BYTES:
                        raise SandboxFixtureError("source hash file-count or byte bound exceeded")
                else:
                    raise SandboxFixtureError("source hash requires regular files and directories")

    def snapshot(info, *, handle_comparison=False):
        # Windows fstat and lstat can expose different ctime semantics. Keep
        # ctime for path-to-path checks, and all other fields for handle checks.
        ctime = None if os.name == "nt" and handle_comparison else info.st_ctime_ns
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, ctime)

    digest = hashlib.sha256()
    bytes_hashed = 0
    for path, info in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        current = path.lstat()
        if path_is_link_or_reparse(path, metadata=current) or snapshot(current) != snapshot(info):
            raise SandboxFixtureError("source file changed during hash preflight")
        descriptor = os.open(path, binary_file_open_flags(os.O_RDONLY, getattr(os, "O_NOFOLLOW", 0)))
        try:
            if snapshot(os.fstat(descriptor), handle_comparison=True) != snapshot(info, handle_comparison=True):
                raise SandboxFixtureError("source file changed before hashing")
            file_bytes = 0
            while chunk := os.read(descriptor, SOURCE_HASH_CHUNK_BYTES):
                file_bytes += len(chunk)
                bytes_hashed += len(chunk)
                if file_bytes > info.st_size or bytes_hashed > SOURCE_HASH_MAX_BYTES:
                    raise SandboxFixtureError("source hash streaming byte bound exceeded")
                digest.update(chunk)
            final = path.lstat()
            if (file_bytes != info.st_size
                    or snapshot(os.fstat(descriptor), handle_comparison=True) != snapshot(info, handle_comparison=True)
                    or path_is_link_or_reparse(path, metadata=final)
                    or snapshot(final) != snapshot(info)):
                raise SandboxFixtureError("source file changed during hashing")
        finally:
            os.close(descriptor)
        digest.update(b"\0")
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


def _collect_rtpc_curve_metadata_probe(runtime: _WorkflowSandboxRuntime) -> dict[str, Any]:
    """Observe existing RTPC.Curve through public bounded reads; never create one."""
    from wwise_waapi.object_query_outputs import available_query_outputs

    points_available = "curve-points" in available_query_outputs(runtime.version)
    output = runtime.state_dir / "rtpc-curve-metadata-observation.json"
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    previous_evidence = set(evidence_root.glob("*.json"))
    observation: dict[str, Any] = {
        "contract": "waapi-skill.rtpc-curve-metadata-observation/v1",
        "candidate": runtime.candidate, "version": runtime.version,
        "endpoint": {"host": runtime.lifecycle.host, "port": runtime.port,
                     "url": runtime.lifecycle.waapi_url},
        "config_path": runtime.env["WAAPI_SKILL_CONFIG_PATH"],
        "config_sha256": hashlib.sha256(Path(runtime.env["WAAPI_SKILL_CONFIG_PATH"]).read_bytes()).hexdigest(),
        "dispatcher_evidence_directory": str(evidence_root),
        "calls": [], "native_evidence": [], "boundaries": [],
        "mutation_authority": False, "business_effect_verified": False,
    }
    category: dict[str, Any] = {
        "category": "rtpc-curve-native-metadata-observation", "status": "FAIL",
        "verifier_strength": "read_only_metadata_and_reference_observation_only",
        "observation_path": str(output), "reason": "observation incomplete",
    }
    runtime.category_results.append(category)

    def retain() -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 2 * 1024 * 1024, "Curve observation exceeded retained byte bound"
        output.write_bytes(body)
        category["observation_sha256"] = hashlib.sha256(body).hexdigest()

    def read(stage: str, argv: Sequence[str]) -> dict[str, Any]:
        assert len(observation["calls"]) < 64, "Curve observation exceeded public call bound"
        code, payload = runtime.raw_gateway(argv)
        observation["calls"].append({"stage": stage, "gateway_argv": list(argv),
                                     "exit_code": code, "payload": payload})
        retain()
        if code == 0 and payload.get("ok") is True and argv[0] not in {"config-show", "query-schema"}:
            assert payload.get("endpoint") == observation["endpoint"], payload
            assert payload.get("detected_version") == runtime.version, payload
        if code != 0 or payload.get("ok") is not True:
            observation["boundaries"].append({"stage": stage, "reason": "public_read_rejected",
                                               "error_code": payload.get("error_code")})
        return payload

    def pages(stage: str, argv: Sequence[str], field: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        command = list(argv)
        for _ in range(8):
            payload = read(stage, command)
            if payload.get("ok") is not True:
                return rows
            result = payload["agent_result"]
            rows.extend(result.get(field, []))
            if result.get("complete") is True:
                return rows
            next_command = result.get("next_command", {}).get("gateway_argv")
            assert isinstance(next_command, list) and next_command[0] == "metadata", payload
            command = next_command
        observation["boundaries"].append({"stage": stage, "reason": "eight_page_bound_reached"})
        return rows

    def curve_metadata(stage: str, scope: Sequence[str]) -> None:
        fields = pages(stage + "-names", ["metadata", "list", *scope, "--page-size", "64"], "fields")
        matches = [row for row in fields if row.get("name") == "Curve"]
        if len(matches) != 1:
            observation["boundaries"].append({"stage": stage, "reason": "Curve_not_uniquely_listed",
                                               "matching_count": len(matches)})
            return
        command = ["metadata", "detail", *scope, "--selection", matches[0]["selection"]]
        for _ in range(8):
            payload = read(stage + "-detail", command)
            if payload.get("ok") is not True or payload["agent_result"].get("complete") is True:
                return
            command = payload["agent_result"]["next_command"]["gateway_argv"]
            assert command[0] == "metadata", payload
        observation["boundaries"].append({"stage": stage, "reason": "eight_detail_page_bound_reached"})

    try:
        if not points_available:
            observation["boundaries"].append({"stage": "Curve-points-contract",
                "reason": "curve_points_output_unavailable_in_public_version",
                "native_availability": "not_inferred"})
        read("configuration", ["config-show"])
        read("host-and-project", ["status"])
        types = pages("live-types", ["metadata", "types", "--meaning", "RTPC",
                                     "--meaning", "Curve", "--page-size", "64"], "types")
        selected = {name: [row for row in types if row.get("name") == name]
                    for name in ("RTPC", "Curve")}
        observation["selected_types"] = selected
        if any(len(rows) != 1 for rows in selected.values()):
            observation["boundaries"].append({"stage": "live-types", "reason": "type_not_uniquely_observed"})
        if len(selected["RTPC"]) == 1:
            rtpc_selection = selected["RTPC"][0]["selection"]
            curve_metadata("RTPC-class-Curve", ["--type-selection", rtpc_selection])
            candidates = read("existing-RTPCs", ["query-object", "--type-selection", rtpc_selection,
                                                 "--max-results", "2"])
            owners = candidates.get("objects", []) if candidates.get("ok") is True else []
            assert isinstance(owners, list) and len(owners) <= 2, candidates
            observation["selected_RTPCs"] = owners
            if not owners:
                observation["boundaries"].append({"stage": "existing-RTPCs", "reason": "no_existing_RTPC_observed"})
            else:
                read("advanced-read-contract", ["query-schema", "--advanced"])
            for index, owner in enumerate(owners):
                owner_id = _required_string(owner, "id")
                assert owner.get("type") == "RTPC", owner
                assert owner_id.casefold() == ("{" + str(uuid.UUID(owner_id)) + "}").casefold(), owner
                curve_metadata(f"RTPC-{index}-Curve", ["--exact-id", owner_id])
                # The business relationship list has no outward reference hop.
                # The existing advanced read contract owns URI/projection/take.
                curve = read(f"RTPC-{index}-Curve-value", [
                    "query-object", "--advanced-waql", f'from object "{owner_id}" select @Curve',
                    "--max-results", "1", "--include", "class-id",
                    *(["--include", "curve-points"] if points_available else []),
                ])
                rows = curve.get("objects", []) if curve.get("ok") is True else []
                assert isinstance(rows, list) and len(rows) <= 1, curve
                for row in rows:
                    curve_id = _required_string(row, "id")
                    assert curve_id.casefold() == ("{" + str(uuid.UUID(curve_id)) + "}").casefold(), row
                    exact = read(f"RTPC-{index}-Curve-exact-ID", [
                        "query-object", "--exact-id", curve_id, "--include", "class-id",
                        *(["--include", "curve-points"] if points_available else []),
                    ])
                    exact_rows = exact.get("objects", []) if exact.get("ok") is True else []
                    if len(exact_rows) != 1 or exact_rows[0].get("id") != curve_id or exact_rows[0].get("type") != "Curve":
                        observation["boundaries"].append({"stage": f"RTPC-{index}-Curve-exact-ID",
                                                           "reason": "Curve_exact_identity_type_not_observed"})
                if not rows or any(row.get("type") != "Curve" or points_available and "curve_points" not in row for row in rows):
                    observation["boundaries"].append({"stage": f"RTPC-{index}-Curve-value",
                                                       "reason": "typed_Curve_points_not_observed"})
        category["status"] = "blocked" if observation["boundaries"] else "PASS"
        category["reason"] = ("bounded observation has explicit gaps" if observation["boundaries"]
                              else "native metadata and points observed; eligibility requires separate review")
        return category
    finally:
        completed_status = category["status"]
        completed_reason = category["reason"]
        category.update(status="FAIL", reason="observation evidence retention incomplete")
        new_evidence = sorted(set(evidence_root.glob("*.json")) - previous_evidence)
        assert len(new_evidence) <= 512, "Curve dispatcher evidence exceeded file bound"
        total_bytes = 0
        for path in new_evidence:
            body = path.read_bytes()
            total_bytes += len(body)
            assert total_bytes <= 32 * 1024 * 1024, "Curve dispatcher evidence exceeded byte bound"
            observation["native_evidence"].append({"path": str(path), "bytes": len(body),
                                                    "sha256": hashlib.sha256(body).hexdigest()})
        retain()
        category.update(status=completed_status, reason=completed_reason)


@pytest.mark.live
@pytest.mark.destructive
def test_read_only_rtpc_curve_native_metadata_observation(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime,
) -> None:
    """Read existing sample RTPC/Curve facts on the selected one of five versions."""
    category = _collect_rtpc_curve_metadata_probe(workflow_sandbox_runtime)
    if category["status"] == "blocked":
        pytest.skip(f"RTPC.Curve observation incomplete; retained exact evidence: {category}")
    assert category["status"] == "PASS", category


def _collect_owned_list_metadata_probe(runtime: _WorkflowSandboxRuntime) -> dict[str, Any]:
    """Observe a tiny existing graph through public reads, without mutation credit."""
    sdk_build = {"2021.1": "2021.1.14.8108", "2022.1": "2022.1.19.8584",
                 "2023.1": "2023.1.19.8928", "2024.1": "2024.1.13.9056",
                 "2025.1": "2025.1.7.9143"}[runtime.version]
    sdk_members = ["wwiseobject_sound.html", "waql_reference.html"]
    if runtime.version >= "2022.1":
        sdk_members.append("ak_wwise_core_object_get_example_gets_the_rtpc_ids_from_a_sound_s_rtpc_list.html")
    if runtime.version >= "2023.1":
        sdk_members.append("wwiseobject_musicswitchcontainer.html")
    if runtime.version == "2025.1":
        sdk_members.append("wwiseobject_musicargumentsslot.html")
    output = runtime.state_dir / "owned-list-metadata-observation.json"
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    previous = set(evidence_root.glob("*.json"))
    config = Path(runtime.env["WAAPI_SKILL_CONFIG_PATH"])
    observation: dict[str, Any] = {
        "contract": "waapi-skill.owned-list-metadata-observation/v1",
        "candidate": runtime.candidate, "version": runtime.version,
        "endpoint": {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url},
        "config_path": str(config), "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "source_evidence": {"research": "/tmp/full-coverage-180-owned-discovery-research.md",
            "installed_source_report": "/tmp/full-coverage-180-installed-owned-sources.md",
            "sdk_archive": f"/Applications/Audiokinetic/Wwise{sdk_build}/SDK/Help/WwiseSDK-Windows.chm",
            "sdk_members": sdk_members,
            "scope": "matching version; 2021 RTPC is an observation candidate, not a documented List-type claim"},
        "bounds": {"calls": 96, "pages_per_metadata_read": 8, "rows": 2048,
                   "members_per_hop": 4, "owner_rows": 16, "observation_bytes": 8 * 1024 * 1024},
        "calls": [], "boundaries": [], "native_evidence": [], "relationships": [], "owner_comparisons": [],
        "complete_owned_list_discovery_proven": False, "field_cardinality_permission_proven": False,
        "mutation_authority": False, "business_effect_verified": False,
    }
    category = {"category": "owned-list-native-metadata-observation", "status": "FAIL",
                "verifier_strength": "bounded_sample_metadata_list_and_owner_observation_only",
                "observation_path": str(output), "reason": "observation incomplete",
                "business_effect_verified": False, "complete_owned_list_discovery_proven": False}
    runtime.category_results.append(category)
    total_rows = 0

    def retain() -> None:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= observation["bounds"]["observation_bytes"], "Owned-list observation byte bound exceeded"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category["observation_sha256"] = hashlib.sha256(body).hexdigest()

    def boundary(stage: str, reason: str, **facts: Any) -> None:
        observation["boundaries"].append({"stage": stage, "reason": reason, **facts})

    def read(stage: str, argv: Sequence[str]) -> dict[str, Any]:
        assert len(observation["calls"]) < 96, "Owned-list public call bound exceeded"
        code, payload = runtime.raw_gateway(argv)
        observation["calls"].append({"stage": stage, "gateway_argv": list(argv), "exit_code": code, "payload": payload})
        retain()
        if code != 0 or payload.get("ok") is not True:
            boundary(stage, "public_read_rejected", error_code=payload.get("error_code"))
        elif argv[0] not in {"config-show", "query-schema"}:
            assert payload.get("endpoint") == observation["endpoint"], payload
            assert payload.get("detected_version") == runtime.version, payload
        return payload

    def count(rows: list[Any]) -> None:
        nonlocal total_rows
        total_rows += len(rows)
        assert total_rows <= 2048, "Owned-list cumulative row bound exceeded"

    def pages(stage: str, argv: Sequence[str], field: str | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        command = list(argv)
        for _ in range(8):
            payload = read(stage, command)
            if payload.get("ok") is not True:
                return []
            result = payload["agent_result"]
            if field:
                batch = result.get(field)
                assert isinstance(batch, list) and len(batch) <= 64, payload
                count(batch)
                rows.extend(batch)
            if result.get("complete") is True:
                return rows
            command = result.get("next_command", {}).get("gateway_argv")
            assert isinstance(command, list) and command[0] == "metadata", payload
        boundary(stage, "metadata_page_bound_reached")
        return []

    def canonical(value: Any) -> str:
        assert isinstance(value, str) and value.casefold() == ("{" + str(uuid.UUID(value)) + "}").casefold(), value
        return value

    def query(stage: str, source: Sequence[str], *, maximum: int = 5, sample: bool = False) -> list[dict[str, Any]]:
        payload = read(stage, ["query-object", *source, "--max-results", str(maximum),
                               "--include", "parent", "--include", "owner", "--include", "class-id"])
        if payload.get("ok") is not True:
            return []
        if payload.get("projection_complete") is False or payload.get("status") == "partial":
            boundary(stage, "query_projection_incomplete")
            return []
        rows = payload.get("objects", payload.get("agent_result"))
        assert isinstance(rows, list) and len(rows) <= maximum, payload
        count(rows)
        if not sample and (len(rows) == maximum or payload.get("limit_reached") is True):
            boundary(stage, "query_row_bound_reached", maximum=maximum)
            return []
        for row in rows:
            canonical(row.get("id"))
            assert isinstance(row.get("type"), str) and row["type"], row
            if "class_id" not in row:
                boundary(stage, "class_id_output_missing", object_id=row["id"])
            elif not isinstance(row["class_id"], int) or isinstance(row["class_id"], bool):
                boundary(stage, "class_id_output_not_integer", object_id=row["id"], value=row["class_id"])
            for key in ("parent", "owner"):
                if key not in row:
                    boundary(stage, "relationship_output_missing", field=key, object_id=row["id"])
                elif row[key] is not None:
                    assert isinstance(row[key], Mapping), row
                    canonical(row[key].get("id"))
        if len({row["id"].casefold() for row in rows}) != len(rows):
            boundary(stage, "duplicate_query_identity")
            return []
        return rows

    def metadata(owner: str, fields: Sequence[str]) -> None:
        listed = pages(owner + "-names", ["metadata", "list", "--exact-id", owner, "--page-size", "64"], "fields")
        for field in fields:
            selected = [row for row in listed if row.get("name") == field]
            if len(selected) != 1:
                boundary(owner + "." + field, "field_not_uniquely_listed_gateway_discovery_boundary", matching_count=len(selected))
                continue
            pages(owner + "." + field + "-detail", ["metadata", "detail", "--exact-id", owner,
                                                       "--selection", selected[0]["selection"]])

    def hop(owner: str, field: str) -> list[dict[str, Any]]:
        rows = query(owner + "." + field, ["--advanced-waql", f'from object "{owner}" select @{field}'])
        observation["relationships"].append({"owner_id": owner, "field": field, "members": rows})
        for row in rows:
            exact = query(row["id"] + "-exact", ["--exact-id", row["id"]], maximum=2)
            if len(exact) != 1 or any(exact[0].get(key) != row.get(key) for key in ("id", "type", "class_id", "parent", "owner")):
                boundary(row["id"], "exact_readback_relationship_changed")
        return rows

    def compare(owner: str, known: Sequence[Mapping[str, Any]]) -> None:
        actual = query(owner + "-from-project-owner", ["--advanced-waql", f'from project where owner.id = "{owner}"'], maximum=17)
        expected = {row["id"] for row in known if isinstance(row.get("owner"), Mapping)
                    and row["owner"].get("id", "").casefold() == owner.casefold()}
        actual_ids = {row["id"] for row in actual}
        missing = sorted(expected - actual_ids)
        observation["owner_comparisons"].append({"owner_id": owner, "owner_rows": actual,
            "known_owned_ids": sorted(expected), "missing_known_owned_ids": missing,
            "additional_owner_ids": sorted(actual_ids - expected), "scope": "this sample only; no list labels/order or exhaustive discovery proof"})
        if missing:
            boundary(owner, "owner_query_missed_known_owned_members", missing_ids=missing)
        if any(not isinstance(row.get("owner"), Mapping) or row["owner"].get("id", "").casefold() != owner.casefold() for row in actual):
            boundary(owner, "owner_filter_readback_mismatch")

    try:
        read("configuration", ["config-show"])
        read("host-and-project", ["status"])
        read("advanced-read-contract", ["query-schema", "--advanced"])
        kinds = ("Sound", "RTPC", *(["MusicSwitchContainer"] if runtime.version >= "2023.1" else []))
        types = pages("live-types", ["metadata", "types", *[token for kind in kinds for token in ("--meaning", kind)], "--page-size", "64"], "types")
        selected = {kind: [row for row in types if row.get("name") == kind] for kind in kinds}
        observation["selected_types"] = selected
        for kind in kinds:
            if len(selected[kind]) != 1:
                boundary("live-types", "type_not_uniquely_observed", name=kind)
        sounds = query("sample-Sound-with-RTPC", ["--advanced-waql", 'from type RTPC select owner where type = "Sound"'], maximum=1, sample=True) if len(selected["RTPC"]) == 1 else []
        if not sounds and len(selected["Sound"]) == 1:
            sounds = query("sample-Sound", ["--type-selection", selected["Sound"][0]["selection"]], maximum=1, sample=True)
        if sounds:
            sound = sounds[0]
            assert sound["type"] == "Sound", sound
            owner = sound["id"]
            fields = ("OutputBus", "RTPC", "Effect0" if runtime.version < "2023.1" else "Effects")
            metadata(owner, fields)
            related = [row for field in fields for row in hop(owner, field)]
            if not any(row["type"] == "RTPC" for row in related):
                boundary(owner, "no_populated_RTPC_list_observed")
            compare(owner, related)
        else:
            boundary("sample-Sound", "no_existing_Sound_observed")
        if runtime.version >= "2023.1" and len(selected["MusicSwitchContainer"]) == 1:
            music = query("sample-MusicSwitchContainer", ["--type-selection", selected["MusicSwitchContainer"][0]["selection"]], maximum=1, sample=True)
            if not music:
                boundary("sample-MusicSwitchContainer", "no_existing_MusicSwitchContainer_observed")
            else:
                owner = music[0]["id"]
                assert music[0]["type"] == "MusicSwitchContainer", music[0]
                metadata(owner, ("Arguments",))
                arguments = hop(owner, "Arguments")
                if not arguments:
                    boundary(owner, "no_populated_Arguments_list_observed")
                expected = {"MusicArgumentsSlot"} if runtime.version == "2025.1" else {"SwitchGroup", "StateGroup"}
                if any(row["type"] not in expected for row in arguments):
                    boundary(owner, "Arguments_member_type_differs_from_matching_source")
                if runtime.version == "2025.1":
                    for slot in arguments:
                        if slot["type"] == "MusicArgumentsSlot":
                            metadata(slot["id"], ("Argument",))
                            targets = hop(slot["id"], "Argument")
                            if len(targets) != 1 or targets[0]["type"] not in {"SwitchGroup", "StateGroup"}:
                                boundary(slot["id"], "slot_Argument_scalar_target_not_observed")
                compare(owner, arguments)
        category.update(status="blocked" if observation["boundaries"] else "PASS",
                        reason="observation has explicit gaps" if observation["boundaries"] else "bounded sample observed; discovery/cardinality completeness requires separate review")
        return category
    finally:
        status, reason = category["status"], category["reason"]
        category.update(status="FAIL", reason="observation retention incomplete")
        assert hashlib.sha256(config.read_bytes()).hexdigest() == observation["config_sha256"], "Probe config changed"
        new_evidence = sorted(set(evidence_root.glob("*.json")) - previous)
        assert len(new_evidence) <= 512, "Owned-list dispatcher file bound exceeded"
        total = 0
        for path in new_evidence:
            body = path.read_bytes()
            total += len(body)
            assert total <= 32 * 1024 * 1024, "Owned-list dispatcher byte bound exceeded"
            observation["native_evidence"].append({"path": str(path), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
        retain()
        category.update(status=status, reason=reason)


def _collect_new_result_scalar_reference_acceptance(
    runtime: _WorkflowSandboxRuntime, *, root_name: str, compound_exact_rename_history: bool = False,
) -> dict[str, Any]:
    """One public graph write; source scalar value must equal a new target's actual GUID."""
    operation = "object.create" if runtime.version == "2021.1" or compound_exact_rename_history else "object.set"
    if compound_exact_rename_history:
        assert runtime.version == '2025.1', 'Compound exact-rename characterization is Console2025-only'
    observation_path = runtime.state_dir / ('compound-exact-rename-history-acceptance.json' if compound_exact_rename_history
        else 'new-result-scalar-reference-acceptance.json')
    category = {"category": "compound-exact-rename-history" if compound_exact_rename_history else "same-graph-new-result-scalar-reference", "status": "FAIL",
        "verifier_strength": "gateway_verified_plus_independent_exact_guid_class_parent_and_scalar_reference",
        "observation_path": str(observation_path), "operation": operation}
    runtime.category_results.append(category)
    receipt: dict[str, Any] = {"candidate": runtime.candidate, "version": runtime.version,
        "operation": operation, "calls": [], "native_outcome": "not_executed",
        "reference_effect": "not_observed", "business_effect_verified": False,
        "lifecycle_acceptance": "Requires this node's final host-category-evidence/v3 PASS; prepared/PENDING grants no cleanup or source-integrity credit."}

    endpoint = {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url} if compound_exact_rename_history else None
    native_root = Path(runtime.env['WWISE_EVIDENCE_DIR']) if compound_exact_rename_history else None
    native_before = set(native_root.glob('*.json')) if native_root is not None else set()
    if compound_exact_rename_history:
        category['verifier_strength'] = 'compound_source_receipt_plus_independent_exact_rename_graph_notes_undo_redo'
        receipt.update(transactions=[], native_evidence=[], complete=False, setup_coverage_credit=False,
            stack_head_observed=False, outside_scope_preservation_observed=False,
            scope='one2025_exact_existing_rename_dependent_ordinary_graph_and_receipt_bound_undo_redo', endpoint=endpoint)

    def persist():
        encoded = json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(encoded) <= (16 if compound_exact_rename_history else 2) * 1024 * 1024, "graph scalar-reference receipt bound exceeded"
        observation_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = observation_path.with_suffix(".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(observation_path)

    class ReceiptGateway:
        def raw_gateway(self, command):
            assert len(receipt["calls"]) < (128 if compound_exact_rename_history else 32), "graph scalar-reference public call bound exceeded"
            row = {"argv": list(command)}
            receipt["calls"].append(row)
            try:
                code, payload = runtime.raw_gateway(command)
                row.update(exit_code=code, payload=payload)
                return code, payload
            except Exception as exc:
                row["exception"] = {"type": type(exc).__name__, "message": str(exc)}
                raise
            finally:
                persist()

        def gateway(self, command, *, live):
            code, payload = self.raw_gateway(command)
            assert code == 0 and payload.get("ok") is True, payload
            if live and compound_exact_rename_history:
                assert payload.get('endpoint') == endpoint and payload.get('detected_version') == runtime.version, payload
            return payload

    gateway = ReceiptGateway()

    def exact_row(command):
        payload = gateway.gateway(command, live=True)
        rows = payload.get("objects")
        assert payload.get("count") == 1 and isinstance(rows, list) and len(rows) == 1, payload
        assert isinstance(rows[0], Mapping), payload
        if compound_exact_rename_history:
            assert payload.get('status') != 'partial' and payload.get('projection_complete') is not False, payload
            assert payload.get('limit_reached') is not True, payload
        uuid_value = uuid.UUID(_required_string(rows[0], "id"))
        assert uuid_value.int != 0, rows[0]
        return rows[0]

    segments = ("Busses" if runtime.version == "2025.1" else "Master-Mixer Hierarchy", "Default Work Unit")
    projection = ['--include', 'class-id', '--include', 'parent', '--include', 'notes']
    def query(selector):
        payload = gateway.gateway(['query-object', *selector, *projection], live=True)
        rows = payload.get('objects')
        assert isinstance(rows, list) and payload.get('count') == len(rows), payload
        assert payload.get('status') != 'partial' and payload.get('projection_complete') is not False, payload
        assert payload.get('limit_reached') is not True, payload
        assert len(rows) < 65 and len({uuid.UUID(row['id']) for row in rows}) == len(rows), payload
        return sorted(rows, key=lambda row: uuid.UUID(row['id']))
    def exact_identity(identity):
        rows = query(['--exact-id', identity]); assert len(rows) == 1 and rows[0]['id'] == identity, rows
        assert type(rows[0].get('class_id')) is int and isinstance(rows[0].get('notes'), str), rows
        return rows[0]
    def children(identity):
        return query(['--exact-id', identity, '--relationship', 'children', '--max-results', '65'])
    def path(components):
        return query([value for segment in components for value in ('--path-segment', segment)])
    def complete(draft, role):
        phase = {'role': role, 'native_outcome': 'not_executed'}; receipt['transactions'].append(phase)
        _update_business_draft(gateway, draft, 'draft-check', live=True)
        preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
        tx = _required_string(preview, 'transaction_id')
        shown = gateway.gateway(['transaction-show', tx], live=False)
        phase.update(transaction_id=tx, artifact_hash=preview['artifact_hash'], immutable_preview=shown['artifact'])
        gateway.gateway(['confirm', tx, '--confirmation-token', shown['confirmation']['token']], live=False)
        phase['native_outcome'] = 'indeterminate'
        code, executed = gateway.raw_gateway(['execute', tx]); phase['execute'] = executed
        if code != 0 or executed.get('ok') is not True:
            phase['native_outcome'] = 'rejected' if executed.get('state') == 'execution_failed' else 'indeterminate'
        assert code == 0 and executed.get('ok') is True, executed
        assert executed.get('automatic_retry') is False and executed.get('state') == 'executed_unverified', executed
        phase['native_outcome'] = 'accepted'
        verified = gateway.gateway(['verify', tx], live=True); phase['verify'] = verified
        assert verified.get('verified') is True and verified.get('verification', {}).get('business_state_verified') is True, verified
        if role in {'undo', 'redo'}: assert verified.get('verification_strength') == 'scoped_history_effect_readback', verified
        phase['transaction'] = gateway.gateway(['transaction-show', tx], live=False)
        assert phase['transaction']['artifact'] == phase['immutable_preview'], 'Transaction mutated its original Preview'
        return phase
    def owned_child(parent, operation):
        started = _update_business_draft(gateway, parent, 'draft-start-undo-child', ['--operation', operation], live=False)
        row = started['draft']
        return _BusinessDraft(row['draft_id'], started['task_authority'], int(row['revision']))
    def history(source_id, direction):
        draft = _start_business_draft(gateway, 'ak.wwise.core.undo.' + direction)
        _update_business_draft(gateway, draft, 'draft-declare-core-plan', ['--value', 'history_scope', 'latest_project_history',
            '--value', 'expectation_receipt', source_id], live=True)
        return draft
    try:
        if compound_exact_rename_history:
            status = gateway.gateway(['status'], live=True)
            assert status.get('wwise', {}).get('isCommandLine') is True, status
            receipt['host_and_project'] = status
            placement, = path(segments)
            assert exact_identity(placement['id']) == placement and placement['type'] == 'WorkUnit', placement
            setup_ids = {}
            for role, name in (('setup-owner', root_name + '_Original'), ('setup-sibling', root_name + '_Preserved')):
                setup = _start_business_draft(gateway, 'object.create')
                parent = _bind_business_object(gateway, setup, object_id=placement['id'])
                kind = _discover_business_type(gateway, setup, meaning='Bus', role='object', expected_label='Bus')
                _update_business_draft(gateway, setup, 'draft-declare-new', ['--declaration-id', 'setup', '--parent-handle', parent,
                    '--kind', kind, '--name', name], live=False)
                setup_ids[role] = _created_object_id(complete(setup, role)['execute'])
            owner_id, sibling_id = setup_ids['setup-owner'], setup_ids['setup-sibling']
            before = receipt['before'] = {'owner': exact_identity(owner_id), 'sibling': exact_identity(sibling_id), 'parent': exact_identity(placement['id']),
                'owner_children': children(owner_id), 'placement_children': children(placement['id'])}
            assert before['owner']['type'] == before['sibling']['type'] == 'Bus' and owner_id != sibling_id, before
            assert before['owner']['name'] == root_name + '_Original' and before['sibling']['name'] == root_name + '_Preserved', before
            for role in ('owner', 'sibling'):
                assert before[role]['class_id'] == 1376272 and before[role]['path'] == '\\' + '\\'.join((*segments, before[role]['name'])), before
            assert before['owner_children'] == [] and before['owner']['parent']['id'] == before['sibling']['parent']['id'] == placement['id'], before
            requested_name = receipt['requested_name'] = root_name + '_Renamed'
            assert path((*segments, requested_name)) == [], 'Exact requested rename path is already occupied'
            parent_draft = _start_business_draft(gateway, 'waapi.undoGroup')
            notes_child = owned_child(parent_draft, 'object.setNotes')
            _bind_business_object(gateway, notes_child, object_id=owner_id)
            requested_notes = receipt['requested_notes'] = 'Prior declared compound notes ' + root_name
            _update_business_draft(gateway, notes_child, 'draft-declare-object-change', ['--notes', requested_notes], live=False)
            _update_business_draft(gateway, notes_child, 'draft-check', live=True)
            rename_child = owned_child(parent_draft, 'object.set')
            owner = _bind_business_object(gateway, rename_child, object_id=owner_id)
            _update_business_draft(gateway, rename_child, 'draft-declare-existing', ['--declaration-id', 'rename', '--object-handle', owner,
                '--field', 'new_name', requested_name], live=False)
            _update_business_draft(gateway, rename_child, 'draft-check', live=True)
            draft = owned_child(parent_draft, operation)
            parent_handle = _bind_business_object(gateway, draft, object_id=owner_id)
        else:
            draft = _start_business_draft(gateway, operation)
            parent_handle = _bind_business_object(gateway, draft, path_segments=segments)
        types = {name: _discover_business_type(gateway, draft, meaning=name, role="object", expected_label=name)
            for name in ("Bus", "AuxBus")}
        # Browse names before binding: the human display meaning also matches HPF/LPF fields.
        page = None
        seen_pages = set()
        selected_field = None
        for _ in range(4):
            listed = _update_business_draft(gateway, draft, "draft-discover-fields",
                ["--type-handle", types["AuxBus"], "--list", "--page-size", "64",
                    *(["--page", page] if page is not None else [])], live=True)
            listing = listed["agent_result"]
            matches = [field for field in listing["fields"] if field.get("name") == "UserAuxSend0"]
            assert len(matches) <= 1, listing
            if matches:
                selected_field = matches[0]
                break
            if listing.get("complete") is True:
                break
            # --page is the public opaque continuation; never derive its contents or offset.
            page = _required_string(listing, "next_page")
            assert page not in seen_pages, "repeated field-list page"
            seen_pages.add(page)
        assert selected_field is not None, "UserAuxSend0 was not disclosed within four field-list pages"
        field_name = _required_string(selected_field, "name")
        discovered = _update_business_draft(gateway, draft, "draft-discover-fields",
            ["--type-handle", types["AuxBus"], "--selection", _required_string(selected_field, "selection")], live=True)
        field_handle = discovered_business_field_handle(discovered, field_name)
        root = _update_business_draft(gateway, draft, "draft-declare-new", ["--declaration-id", "root",
            "--parent-handle", parent_handle, "--name", root_name, "--kind", types["Bus"]], live=False)
        root_handle = declared_business_object_handle(root, "root")
        target = _update_business_draft(gateway, draft, "draft-declare-new", ["--declaration-id", "target",
            "--parent-handle", root_handle, "--name", "Destination", "--kind", types["AuxBus"]], live=False)
        target_handle = declared_business_object_handle(target, "target")
        _update_business_draft(gateway, draft, "draft-declare-new", ["--declaration-id", "source",
            "--parent-handle", root_handle, "--name", "Sender", "--kind", types["AuxBus"],
            "--field-value", field_handle, target_handle], live=False)
        if compound_exact_rename_history:
            _update_business_draft(gateway, draft, 'draft-check', live=True)
            child_args = [value for child in (notes_child, rename_child, draft)
                for value in ('--child-draft', child.draft_id, child.task_authority)]
            _update_business_draft(gateway, parent_draft, 'draft-declare-undo-plan',
                ['--display-name', 'Exact rename dependent graph ' + root_name, *child_args], live=False)
            source_phase = complete(parent_draft, 'source')
            transaction_id = source_phase['transaction_id']
            executed, verified = source_phase['execute'], source_phase['verify']
            verify_code = 0
            actual_owner = exact_identity(owner_id)
            assert actual_owner['id'] == owner_id and actual_owner['name'] == requested_name, actual_owner
            assert actual_owner['notes'] == requested_notes, actual_owner
            assert actual_owner['path'] == before['owner']['path'].rsplit('\\', 1)[0] + '\\' + actual_owner['name'], actual_owner
            graph_segments = (*segments, actual_owner['name'], root_name)
            category['transaction_id'] = transaction_id
            receipt.update(transaction_id=transaction_id, native_outcome='accepted', gateway_verification=verified)
        else:
            _update_business_draft(gateway, draft, "draft-check", live=True)
            preview = _update_business_draft(gateway, draft, "preview-from-draft", live=True)
            transaction_id = _required_string(preview, "transaction_id")
            category["transaction_id"] = receipt["transaction_id"] = transaction_id
            receipt["artifact_hash"] = preview["artifact_hash"]
            shown = gateway.gateway(["transaction-show", transaction_id], live=False)
            receipt["compiled_native_request"] = shown["artifact"]["prepared_operation"]["dispatch"]
            gateway.gateway(["confirm", transaction_id, "--confirmation-token", shown["confirmation"]["token"]], live=False)
            receipt["native_outcome"] = "indeterminate"
            execute_code, executed = gateway.raw_gateway(["execute", transaction_id])
            receipt["native_response"] = executed
            if execute_code != 0 or executed.get("ok") is not True:
                receipt["native_outcome"] = "rejected" if executed.get("state") == "execution_failed" else "indeterminate"
                return category
            assert executed.get("state") == "executed_unverified" and executed.get("automatic_retry") is False, executed
            receipt["native_outcome"] = "accepted"
            verify_code, verified = gateway.raw_gateway(["verify", transaction_id])
            receipt["gateway_verification"] = {"exit_code": verify_code, "payload": verified}
            receipt["reference_effect"] = "incomplete"
            graph_segments = (*segments, root_name)
        # Select by closed fixture names, then independently re-read every exact GUID.
        independently_found = {}
        for name, child_segments in (("root", ()), ("target", ("Destination",)), ("source", ("Sender",))):
            path_segments = (*graph_segments, *child_segments)
            found = exact_row(["query-object", *(value for segment in path_segments for value in ("--path-segment", segment))])
            exact = exact_row(["query-object", "--exact-id", found["id"], "--include", "class-id", "--include", "parent",
                *(["--include-field", field_name] if name == "source" else []),
                *(['--include', 'notes'] if compound_exact_rename_history else [])])
            assert all(found.get(key) == exact.get(key) for key in ("id", "name", "type", "path")), (found, exact)
            receipt["independent_" + name] = exact
            independently_found[name] = exact
        root_row, target_row, source_row = (independently_found[name] for name in ("root", "target", "source"))
        assert len({row["id"] for row in (root_row, target_row, source_row)}) == 3, independently_found
        for row, expected_class, expected_type in ((root_row, 1376272, "Bus"), (target_row, 3997712, "AuxBus"), (source_row, 3997712, "AuxBus")):
            assert type(row.get("class_id")) is int and row["class_id"] == expected_class and row["type"] == expected_type, row
        assert target_row.get("parent", {}).get("id") == root_row["id"], target_row
        assert source_row.get("parent", {}).get("id") == root_row["id"], source_row
        reference = source_row.get("references", {}).get("UserAuxSend0")
        actual_target_id = reference.get("id") if isinstance(reference, Mapping) else reference
        assert actual_target_id == target_row["id"], {"source_reference": reference, "independent_target": target_row}
        assert verify_code == 0 and verified.get("state") == "verified" and verified.get("verified") is True, verified
        assert verified.get("verification", {}).get("business_state_verified") is True, verified
        if compound_exact_rename_history:
            assert root_row['parent']['id'] == owner_id, root_row
            def observed_state():
                rows = {role: exact_identity(identity) for role, identity in (('owner', owner_id), ('sibling', sibling_id), ('parent', placement['id']))}
                assert rows['sibling'] == before['sibling'] and rows['parent'] == before['parent'], rows
                assert {key: value for key, value in rows['owner'].items() if key not in {'name', 'path', 'notes'}} == {
                    key: value for key, value in before['owner'].items() if key not in {'name', 'path', 'notes'}}, rows
                rows['owner_children'] = children(owner_id)
                rows['placement_children'] = children(placement['id'])
                expected_siblings = [rows['owner'] if row['id'] == owner_id else row for row in before['placement_children']]
                assert rows['placement_children'] == expected_siblings, rows
                rows['graph'] = {name: exact_row(['query-object', '--exact-id', row['id'], *projection,
                    *(['--include-field', field_name] if name == 'source' else [])]) for name, row in independently_found.items()}
                rows['graph_children'] = children(root_row['id'])
                assert rows['owner_children'] == [rows['graph']['root']], rows
                assert rows['graph_children'] == sorted([rows['graph']['target'],
                    {key: value for key, value in rows['graph']['source'].items() if key != 'references'}], key=lambda row: uuid.UUID(row['id'])), rows
                return rows
            source_state = receipt['source_state'] = observed_state()
            assert source_state['graph'] == independently_found, source_state
            assert path((*segments, before['owner']['name'])) == [], 'Original owner path survived rename'
            assert path((*segments, requested_name)) == [source_state['owner']], 'Exact requested rename path differs'
            complete(history(transaction_id, 'undo'), 'undo')
            undo_state = receipt['undo_state'] = {'owner': exact_identity(owner_id), 'sibling': exact_identity(sibling_id), 'parent': exact_identity(placement['id']),
                'owner_children': children(owner_id), 'placement_children': children(placement['id'])}
            assert undo_state == before, undo_state
            for row in independently_found.values(): assert query(['--exact-id', row['id']]) == [], row
            assert path(graph_segments) == path((*segments, before['owner']['name'], root_name)) == [], 'Created graph path survived undo'
            complete(history(transaction_id, 'redo'), 'redo')
            receipt['redo_state'] = observed_state()
            assert receipt['redo_state'] == source_state, (source_state, receipt['redo_state'])
            assert path((*segments, before['owner']['name'])) == []
            receipt.update(complete=True, source_receipt=transaction_id)
        receipt.update(reference_effect="proven", business_effect_verified=True)
        category["status"] = "PASS"
        return category
    except Exception as exc:
        receipt["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if native_root is not None:
            status = category['status']; category['status'] = 'FAIL'
            archive = runtime.state_dir / 'compound-exact-rename-native-archive'; archive.mkdir(parents=True, exist_ok=True)
            paths = sorted(set(native_root.glob('*.json')) - native_before)
            assert len(paths) <= 512, 'Compound exact-rename native evidence file bound exceeded'
            total = 0
            for index, native in enumerate(paths):
                body = read_bounded_exclusive_regular_file(native, max_bytes=32 * 1024 * 1024 - total,
                    require_private_posix_mode=False).raw
                total += len(body)
                assert total <= 32 * 1024 * 1024, 'Compound exact-rename native evidence byte bound exceeded'
                target = archive / f'{index:04d}-{native.name}'; target.write_bytes(body)
                receipt['native_evidence'].append({'native_path': str(native), 'archive_path': str(target),
                    'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
            persist()
            category['observation_sha256'] = hashlib.sha256(observation_path.read_bytes()).hexdigest()
            category['status'] = status
        else:
            persist()


def _collect_existing_bus_send_acceptance(
    runtime: _WorkflowSandboxRuntime, *, root_name: str, root_sources: bool = False,
) -> dict[str, Any]:
    """Existing-source writes in one owned lifecycle, with independent effect reads."""
    output = runtime.state_dir / ("old-root-bus-send-acceptance.json" if root_sources else "existing-bus-send-acceptance.json")
    category = {"category": "old-root-bus-user-send" if root_sources else "existing-bus-user-send", "status": "FAIL",
        "verifier_strength": "gateway_verified_plus_independent_exact_identity_parent_reference_scalar_and_notes",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    receipt: dict[str, Any] = {"candidate": runtime.candidate, "version": runtime.version,
        "calls": [], "transactions": [], "business_effect_verified": False,
        "setup_coverage_credit": False,
        "lifecycle_acceptance": "Requires this node's final host-category-evidence/v3 PASS; no cleanup or source-integrity credit before finalization."}

    def persist():
        body = json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024, "existing user-send receipt byte bound exceeded"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp")
        temporary.write_bytes(body)
        temporary.replace(output)

    class ReceiptGateway:
        def raw_gateway(self, command):
            assert len(receipt["calls"]) < 192, "existing user-send public call bound exceeded"
            row = {"argv": list(command)}
            receipt["calls"].append(row)
            try:
                code, payload = runtime.raw_gateway(command)
                row.update(exit_code=code, payload=payload)
                return code, payload
            except Exception as exc:
                row["exception"] = {"type": type(exc).__name__, "message": str(exc)}
                raise
            finally:
                persist()

        def gateway(self, command, *, live):
            code, payload = self.raw_gateway(command)
            assert code == 0 and payload.get("ok") is True, payload
            return payload

    gateway = ReceiptGateway()
    segments = ("Busses" if runtime.version == "2025.1" else "Master-Mixer Hierarchy", "Default Work Unit")
    names = {"root": root_name, "target": "Destination",
        "source": root_name + "_Sender" if root_sources else "Sender",
        "batch_source": root_name + "_BatchSender" if root_sources else "BatchSender"}
    receipt["placement"] = "old_root_bus_sources" if root_sources else "aux_bus_children"

    def exact(command):
        payload = gateway.gateway(command, live=True)
        rows = payload.get("objects")
        assert payload.get("count") == 1 and isinstance(rows, list) and len(rows) == 1, payload
        row = rows[0]
        assert isinstance(row, Mapping) and uuid.UUID(_required_string(row, "id")).int != 0, payload
        return row

    def read(identity, role):
        row = exact(["query-object", "--exact-id", identity, "--include", "class-id", "--include", "parent",
            "--include", "notes", *(["--include-field", "UserAuxSend0", "--include-field", "UserAuxSendVolume0"]
                if role in {"source", "batch_source"} else [])])
        kind, class_id = (("WorkUnit", 1638416) if role == "placement_parent" else
            ("Bus", 1376272) if role == "root" or (root_sources and role in {"source", "batch_source"}) else
            ("AuxBus", 3997712))
        assert type(row.get("class_id")) is int and row["class_id"] == class_id, row
        assert row["type"] == kind, row
        assert isinstance(row.get("notes"), str), row
        if role in {"source", "batch_source"}:
            assert "UserAuxSend0" in row.get("references", {}), row
            value = row.get("properties", {}).get("UserAuxSendVolume0")
            assert type(value) in {int, float} and math.isfinite(value), row
        return row

    def reference_id(row):
        value = row["references"]["UserAuxSend0"]
        return value.get("id") if isinstance(value, Mapping) else value

    def select(draft, owner, token, *, kind=None):
        page = None
        seen = set()
        scope = ["--type-handle", kind] if kind is not None else ["--object-handle", owner]
        for _ in range(4):
            listed = _update_business_draft(gateway, draft, "draft-discover-fields",
                [*scope, "--list", "--page-size", "64",
                    *(["--page", page] if page is not None else [])], live=True)["agent_result"]
            matches = [row for row in listed["fields"] if row.get("name") == token]
            assert len(matches) <= 1, listed
            if matches:
                selected = _update_business_draft(gateway, draft, "draft-discover-fields",
                    [*scope, "--selection", _required_string(matches[0], "selection")], live=True)
                return discovered_business_field_handle(selected, token)
            if listed.get("complete") is True:
                break
            page = _required_string(listed, "next_page")
            assert page not in seen, "repeated field-list page"
            seen.add(page)
        raise AssertionError(f"{token} not disclosed within four exact field-list pages")

    def complete(draft, label, *, existing_merge=None):
        phase: dict[str, Any] = {"phase": label, "native_outcome": "not_executed", "effect_verified": False}
        receipt["transactions"].append(phase)
        _update_business_draft(gateway, draft, "draft-check", live=True)
        preview = _update_business_draft(gateway, draft, "preview-from-draft", live=True)
        identity = _required_string(preview, "transaction_id")
        phase.update(transaction_id=identity, artifact_hash=preview["artifact_hash"])
        shown = gateway.gateway(["transaction-show", identity], live=False)
        prepared = shown["artifact"]["prepared_operation"]
        phase["compiled_native_request"] = prepared["dispatch"]
        if existing_merge is not None:
            phase["expected_existing_merge"] = existing_merge
            nodes = prepared["verification_plan"]["nodes"]
            assert len(nodes) == 1 and nodes[0]["preexisting_id"] == existing_merge["id"], nodes
            node = nodes[0]
            assert node["class_id"] == existing_merge["class_id"] and node["canonical_type"] == existing_merge["type"], node
            assert all(node["pre_state"].get(field) == existing_merge.get(field)
                for field in ("id", "name", "type", "path", "parent", "notes")), (node, existing_merge)
            assert node["pre_state"]["classId"] == existing_merge["class_id"], node
            before = node["pre_state"]
            for token in ("UserAuxSend0", "UserAuxSendVolume0"):
                assert token in before or "@" + token in before, node
                value = before.get(token, before.get("@" + token))
                assert ((value.get("id") if isinstance(value, Mapping) else value) == reference_id(existing_merge)
                    if token == "UserAuxSend0" else value == existing_merge["properties"][token]), (node, existing_merge)
            args = prepared["dispatch"]["args"]
            assert args["parent"] == existing_merge["parent"]["id"] and args["name"] == existing_merge["name"], args
            assert args["type"] == existing_merge["type"] and args["onNameConflict"] == "merge", args
        gateway.gateway(["confirm", identity, "--confirmation-token", shown["confirmation"]["token"]], live=False)
        phase["native_outcome"] = "indeterminate"
        code, executed = gateway.raw_gateway(["execute", identity])
        phase["execute"] = {"exit_code": code, "payload": executed}
        if code != 0 or executed.get("ok") is not True:
            phase["native_outcome"] = "rejected" if executed.get("state") == "execution_failed" else "indeterminate"
            raise AssertionError(f"{label} failed; no verification or retry: {executed}")
        assert executed.get("state") == "executed_unverified" and executed.get("automatic_retry") is False, executed
        phase["native_outcome"] = "accepted"
        code, verified = gateway.raw_gateway(["verify", identity])
        phase["verify"] = {"exit_code": code, "payload": verified}
        assert code == 0 and verified.get("state") == "verified" and verified.get("verified") is True, verified
        assert verified.get("verification", {}).get("business_state_verified") is True, verified
        return phase

    try:
        assert not root_sources or runtime.version in {"2021.1", "2022.1", "2023.1"}, (
            "Root-Bus witness is limited to the pinned 2021–2023 class-source scope; "
            "2024–2025 retain their explicit non-master placement boundary.")
        placement_parent = None
        if root_sources:
            found = exact(["query-object", *(arg for segment in segments for arg in ("--path-segment", segment))])
            placement_parent = read(found["id"], "placement_parent")
            assert all(found.get(key) == placement_parent.get(key) for key in ("id", "name", "type", "path")), (found, placement_parent)
            assert placement_parent["name"] == segments[-1] and placement_parent["path"] == "\\" + "\\".join(segments), placement_parent
            receipt["placement_parent"] = placement_parent
        setup = _start_business_draft(gateway, "object.create")
        parent = _bind_business_object(gateway, setup, **({"object_id": placement_parent["id"]}
            if placement_parent is not None else {"path_segments": segments}))
        types = {name: _discover_business_type(gateway, setup, meaning=name, role="object", expected_label=name)
            for name in ("Bus", "AuxBus")}
        root = _update_business_draft(gateway, setup, "draft-declare-new", ["--declaration-id", "root",
            "--parent-handle", parent, "--name", root_name, "--kind", types["Bus"], "--field", "notes", "Keep routing"], live=False)
        root_handle = declared_business_object_handle(root, "root")
        for role in (("target",) if root_sources else ("target", "source", "batch_source")):
            _update_business_draft(gateway, setup, "draft-declare-new", ["--declaration-id", role,
                "--parent-handle", root_handle, "--name", names[role], "--kind", types["AuxBus"],
                "--field", "notes", "Keep " + names[role]], live=False)
        setup_phases = [complete(setup, "setup_no_coverage_credit")]
        if root_sources:
            # 2021 permits one create root. Keep the sibling root Busses in separate
            # closed Previews; none of these setup effects grants user-send credit.
            for role in ("source", "batch_source"):
                setup = _start_business_draft(gateway, "object.create")
                parent = _bind_business_object(gateway, setup, object_id=placement_parent["id"])
                kind = _discover_business_type(gateway, setup, meaning="Bus", role="object", expected_label="Bus")
                _update_business_draft(gateway, setup, "draft-declare-new", ["--declaration-id", role,
                    "--parent-handle", parent, "--name", names[role], "--kind", kind,
                    "--field", "notes", "Keep " + names[role]], live=False)
                setup_phases.append(complete(setup, "setup_" + role + "_no_coverage_credit"))
        baseline = {}
        for role, name in names.items():
            path = (*segments, name) if root_sources and role in {"source", "batch_source"} else (
                *segments, root_name, *([] if role == "root" else [name]))
            found = exact(["query-object", *(arg for segment in path for arg in ("--path-segment", segment))])
            row = read(found["id"], role)
            assert all(found.get(key) == row.get(key) for key in ("id", "name", "type", "path")), (found, row)
            assert row["name"] == name and row["path"] == "\\" + "\\".join(path), row
            assert row["notes"] == ("Keep routing" if role == "root" else "Keep " + name), row
            baseline[role] = row
        assert len({row["id"] for row in baseline.values()}) == 4, baseline
        for role in (("root", "source", "batch_source") if root_sources else ()):
            assert baseline[role].get("parent", {}).get("id") == placement_parent["id"], baseline
        for role in (("target",) if root_sources else ("target", "source", "batch_source")):
            assert baseline[role].get("parent", {}).get("id") == baseline["root"]["id"], baseline
            assert baseline[role]["path"] == baseline["root"]["path"] + "\\" + names[role], baseline
        for role in ("source", "batch_source"):
            assert reference_id(baseline[role]) is None, baseline[role]
        receipt["baseline"] = baseline
        for phase in setup_phases:
            phase["effect_verified"] = True
        expected = json.loads(json.dumps(baseline))
        phases = [("standalone_reference", "object.setReference", "source", {"UserAuxSend0": "target"}),
            ("standalone_scalar", "object.setProperty", "source", {"UserAuxSendVolume0": -9}),
            ("samebatch_reference_scalar", "object.create" if runtime.version == "2021.1" else "object.set",
                "batch_source", {"UserAuxSend0": "target", "UserAuxSendVolume0": -12})]
        for label, operation, role, values in phases:
            draft = _start_business_draft(gateway, operation)
            owner = _bind_business_object(gateway, draft, object_id=baseline[role]["id"])
            kind = None
            if operation == "object.create":
                kind = _discover_business_type(gateway, draft, meaning=baseline[role]["type"],
                    role="object", expected_label=baseline[role]["type"])
                parent = _bind_business_object(gateway, draft, object_id=baseline[role]["parent"]["id"])
                _update_business_draft(gateway, draft, "draft-business-configure", ["--name-conflict", "merge"], live=False)
            fields = []
            for token, value in values.items():
                field = select(draft, owner, token, kind=kind)
                bound = _bind_business_object(gateway, draft, object_id=baseline["target"]["id"]) if token == "UserAuxSend0" else str(value)
                if operation in {"object.set", "object.create"}:
                    fields.extend(("--field-value", field, bound))
                else:
                    _update_business_draft(gateway, draft, "draft-declare-field-change", ["--object-handle", owner,
                        "--field-handle", field, "--target-handle" if token == "UserAuxSend0" else "--business-value", bound], live=False)
            if operation == "object.set":
                _update_business_draft(gateway, draft, "draft-declare-existing", ["--declaration-id", "source",
                    "--object-handle", owner, *fields], live=False)
            elif operation == "object.create":
                _update_business_draft(gateway, draft, "draft-declare-new", ["--declaration-id", "source",
                    "--parent-handle", parent, "--name", baseline[role]["name"], "--kind", kind, *fields], live=False)
            phase = complete(draft, label, existing_merge=baseline[role] if operation == "object.create" else None)
            for token, value in values.items():
                expected[role]["references" if token == "UserAuxSend0" else "properties"][token] = (
                    {"id": baseline["target"]["id"]} if token == "UserAuxSend0" else value)
            observed = {key: read(row["id"], key) for key, row in baseline.items()}
            phase["independent_effect"] = observed
            if placement_parent is not None:
                actual_parent = read(placement_parent["id"], "placement_parent")
                phase["independent_placement_parent"] = actual_parent
                assert actual_parent == placement_parent, (label, placement_parent, actual_parent)
            for key, row in observed.items():
                for field in ("id", "name", "type", "path", "class_id", "parent", "notes"):
                    assert row.get(field) == expected[key].get(field), (label, key, field, expected[key], row)
                if key in {"source", "batch_source"}:
                    assert reference_id(row) == reference_id(expected[key]), (label, key, row, expected[key])
                    assert row["properties"]["UserAuxSendVolume0"] == expected[key]["properties"]["UserAuxSendVolume0"], (label, key, row, expected[key])
            phase["effect_verified"] = True
        receipt["completed_mutation_phases"] = [phase[0] for phase in phases]
        receipt["business_effect_verified"] = True
        category["status"] = "PASS"
        return category
    except Exception as exc:
        receipt["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        persist()


@pytest.mark.live
@pytest.mark.destructive
def test_existing_bus_send_reference_scalar_acceptance(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    """One lifecycle; each legal phase independently previewed and executed once."""
    category = _collect_existing_bus_send_acceptance(workflow_sandbox_runtime,
        root_name="WAAPI_EXISTING_SEND_" + uuid.uuid4().hex[:12])
    assert category["status"] == "PASS", category


@pytest.mark.live
@pytest.mark.destructive
def test_old_root_bus_send_reference_scalar_acceptance(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    """2021–2023 root sources route to an AuxBus below a different root Bus."""
    if workflow_sandbox_runtime.version not in {"2021.1", "2022.1", "2023.1"}:
        pytest.skip("Old root-Bus witness only; 2024–2025 require their non-master placement proof")
    category = _collect_existing_bus_send_acceptance(workflow_sandbox_runtime,
        root_name="WAAPI_ROOT_SEND_" + uuid.uuid4().hex[:12], root_sources=True)
    assert category["status"] == "PASS", category


@pytest.mark.live
@pytest.mark.destructive
def test_same_graph_new_result_scalar_reference_acceptance(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    """2021 create and 2022–2025 set share one isolated lifecycle, never a retry."""
    category = _collect_new_result_scalar_reference_acceptance(workflow_sandbox_runtime,
        root_name="WAAPI_RESULT_REFERENCE_" + uuid.uuid4().hex[:12])
    assert category["status"] == "PASS", category


@pytest.mark.live
@pytest.mark.destructive
def test_compound_exact_rename_graph_history_acceptance(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    if workflow_sandbox_runtime.version != '2025.1':
        pytest.skip('One2025 exact-rename graph/history case; other lanes remain separate')
    category = _collect_new_result_scalar_reference_acceptance(workflow_sandbox_runtime,
        root_name='WAAPI_EXACT_GRAPH_' + uuid.uuid4().hex[:10], compound_exact_rename_history=True)
    assert category['status'] == 'PASS', category


@pytest.mark.live
@pytest.mark.destructive
def test_read_only_owned_list_native_metadata_observation(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    """Observe existing members and owner-query correspondence in the module sandbox."""
    category = _collect_owned_list_metadata_probe(workflow_sandbox_runtime)
    if category["status"] == "blocked":
        pytest.skip(f"Owned-list observation incomplete; retained exact evidence: {category}")
    assert category["status"] == "PASS", category


def _collect_short_id_native_probe(runtime: _WorkflowSandboxRuntime, *, diagnostic: bool = False) -> dict[str, Any]:
    """Reuse the original read body inside this module's already-owned sandbox."""
    from tests.support.short_id_native_observation import collect_short_id_typed_read_observations, collect_short_id_diagnostic_observations

    output = runtime.state_dir / ("short-id-native-diagnostic.json" if diagnostic else "short-id-native-observations.json")
    config = Path(runtime.env["WAAPI_SKILL_CONFIG_PATH"])
    config_sha256 = hashlib.sha256(config.read_bytes()).hexdigest()
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    previous = set(evidence_root.glob("*.json"))
    endpoint = {"host": runtime.lifecycle.host, "port": runtime.port,
                "url": runtime.lifecycle.waapi_url}
    evidence: dict[str, Any] = {
        "agent_started": False, "project_mutation_count": 0, "version": runtime.version,
        "scope": ("read-only Short ID hypotheses; collection success is not resolver or Definition acceptance" if diagnostic else
                  "typed Short ID read observations only; no Definition mutation acceptance"),
        "candidate": runtime.candidate, "endpoint": endpoint,
        "config_path": str(config), "config_sha256": config_sha256,
        "receipts": [], "observations": [], "native_evidence": [],
        "mutation_authority": False, "business_effect_verified": False,
    }
    category = {"category": "short-id-native-diagnostic" if diagnostic else "short-id-native-read-observation", "status": "FAIL",
                "verifier_strength": "diagnostic_collection_no_functional_acceptance" if diagnostic else "bounded_typed_short_id_read_and_exact_guid_observation_only",
                "observation_path": str(output), "reason": "observation incomplete"}
    runtime.category_results.append(category)

    def read(command: Sequence[str]) -> dict[str, Any]:
        assert command[0] in ({"status", "query-object", "query-schema"} if diagnostic else {"status", "query-object"}), command
        assert len(evidence["receipts"]) < (10 if diagnostic else 7), "Short ID observation public call bound exceeded"
        code, payload = runtime.raw_gateway(command)
        evidence["receipts"].append({"argv": list(command), "exit_code": code, "payload": payload})
        if diagnostic and "--advanced-waql" in command and code == 2:
            return payload  # Retain the complete bounded rejection; never retry it.
        assert code == 0 and payload.get("ok") is True, payload
        if diagnostic and command == ["query-schema", "--advanced"]:
            return payload  # Offline disclosure has no live endpoint.
        assert payload.get("endpoint") == endpoint, payload
        assert payload.get("detected_version") == runtime.version, payload
        return payload

    status, reason = "FAIL", "Short ID native observation did not finish"
    try:
        collector = collect_short_id_diagnostic_observations if diagnostic else collect_short_id_typed_read_observations
        collector(read, evidence=evidence)
        status, reason = "PASS", ("bounded read-only diagnostic collection complete; no functional acceptance" if diagnostic else
                                  "public bounded typed Short ID reads and exact-ID readbacks succeeded")
        return category
    except BaseException as exc:
        reason = f"{type(exc).__name__}: {exc}"
        evidence["error"] = reason
        raise
    finally:
        assert hashlib.sha256(config.read_bytes()).hexdigest() == config_sha256, "Short ID observation changed config"
        paths = sorted(set(evidence_root.glob("*.json")) - previous)
        assert len(paths) <= 512, "Short ID dispatcher evidence exceeded file bound"
        total_bytes = 0
        for path in paths:
            body = path.read_bytes()
            total_bytes += len(body)
            assert total_bytes <= 32 * 1024 * 1024, "Short ID dispatcher evidence exceeded byte bound"
            evidence["native_evidence"].append({"path": str(path), "bytes": len(body),
                                                 "sha256": hashlib.sha256(body).hexdigest()})
        body = json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024, "Short ID retained observation byte bound exceeded"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(status=status, reason=reason,
                        observation_sha256=hashlib.sha256(body).hexdigest())


@pytest.mark.live
@pytest.mark.destructive
def test_read_only_short_id_native_observation(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    """Observe Event/DialogueEvent Short IDs without a second lifecycle or config write."""
    category = _collect_short_id_native_probe(workflow_sandbox_runtime)
    assert category["status"] == "PASS", category


@pytest.mark.live
@pytest.mark.destructive
def test_read_only_short_id_native_diagnostic(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    """Explicitly selected hypothesis probes within the existing owned lifecycle."""
    category = _collect_short_id_native_probe(workflow_sandbox_runtime, diagnostic=True)
    assert category["status"] == "PASS", category


def _collect_prospective_group_default_native_acceptance(
    runtime: _WorkflowSandboxRuntime, family: str,
) -> dict[str, Any]:
    """One closed create plus independent reads inside the existing sandbox owner."""
    import gzip
    from types import SimpleNamespace

    assert family in {"Switch", "State"}
    output = runtime.state_dir / f"prospective-group-default-{family}.json"
    config = Path(runtime.env["WAAPI_SKILL_CONFIG_PATH"])
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    dispatcher = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    previous = set(dispatcher.glob("*.json"))
    endpoint = {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url}
    category = {"category": "prospective-group-default-" + family, "status": "FAIL",
        "verifier_strength": "gateway_verified_create_plus_independent_exact_identity_and_two_references",
        "observation_path": str(output), "reason": "acceptance incomplete", "transaction_id": None}
    runtime.category_results.append(category)
    evidence: dict[str, Any] = {"candidate": runtime.candidate, "version": runtime.version,
        "build": runtime.sandbox.metadata.get_info_version, "family": family, "endpoint": endpoint,
        "config_path": str(config), "config_sha256": config_hash, "receipts": [], "native_evidence": [],
        "lifecycle_final_reference": {"contract": "waapi-skill.host-category-evidence/v3", "phase": "final",
            "candidate": runtime.candidate, "category": category["category"], "transaction_id": None,
            "cleanup_status": "unresolved_until_final_row"},
        "lifecycle_acceptance": "Requires the final host-category-evidence/v3 row for this candidate, category and transaction; the existing workflow lifecycle seals source hashes/mtime and process cleanup. Collector completion alone is not cleanup success."}

    def call(command: Sequence[str], *, live: bool) -> dict[str, Any]:
        assert len(evidence["receipts"]) < 32, "Prospective reference public call bound exceeded"
        code, payload = runtime.raw_gateway(command)
        evidence["receipts"].append({"argv": list(command), "exit_code": code, "payload": payload})
        if command[0] == "preview-from-draft" and payload.get("transaction_id"):
            category["transaction_id"] = payload["transaction_id"]
            evidence["lifecycle_final_reference"]["transaction_id"] = payload["transaction_id"]
        assert code == 0 and payload.get("ok") is True, payload
        if live:
            assert payload.get("endpoint") == endpoint, payload
            assert payload.get("detected_version") == runtime.version, payload
        return payload

    # Reuse the existing business-Draft helpers; this view only records their
    # public commands and has no client, configuration or lifecycle of its own.
    commands = SimpleNamespace(gateway=call)

    def one(source: Sequence[str], *outputs: str) -> dict[str, Any]:
        payload = call(["query-object", *source, "--max-results", "1", *outputs], live=True)
        assert payload.get("projection_complete") is not False and payload.get("status") != "partial", payload
        rows = payload.get("objects", payload.get("agent_result"))
        assert isinstance(rows, list) and len(rows) == 1, payload
        row = rows[0]
        assert all(isinstance(row.get(key), str) and row[key] for key in ("id", "name", "type", "path")), row
        canonical(row["id"])
        return row

    def canonical(value: Any) -> str:
        identity = value.get("id") if isinstance(value, Mapping) else value
        assert isinstance(identity, str) and identity.casefold() == ("{" + str(uuid.UUID(identity)) + "}").casefold(), value
        assert uuid.UUID(identity).int != 0, value
        return identity.casefold()

    try:
        source_path = REPO_ROOT / "tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz"
        sources = json.loads(gzip.decompress(source_path.read_bytes()))["files"]
        matches = [(key, document) for key, document in sources.items()
                   if key.startswith(runtime.version + ".") and key.endswith("|condition|WObjects/WObjects.xml")]
        assert len(matches) == 1, [key for key, _ in matches]
        key, document = matches[0]
        raw = base64.b64decode(document["bytes_base64"])
        assert hashlib.sha256(raw).hexdigest() == document["sha256"]
        definition = ET.fromstring(raw).find('./WwiseObject[@Name="SwitchContainer"]/Properties/Reference[@Name="DefaultSwitchOrState"]')
        assert definition is not None
        assert definition.find('./Restrictions/IsChildOfReferenceRestriction/Reference').attrib == {"Name": SWITCH_GROUP_REFERENCE}
        assert definition.find('./Dependencies/ReferenceDependency').attrib == {"Name": SWITCH_GROUP_REFERENCE, "Action": "Enable"}
        assert definition.find('./Dependencies/ReferenceDependency/Condition/ReferenceIsSet').attrib == {"Value": "true"}
        evidence["source_rule"] = {"version": runtime.version, "key": key, "sha256": document["sha256"],
            "fixture": str(source_path), "field_xml": ET.tostring(definition, encoding="unicode")}
        sample = one(["--custom-kind", family], "--include", "parent")
        assert sample["type"] == family, sample
        target = one(["--exact-id", sample["id"]], "--include", "parent")
        assert target == sample, {"sample": sample, "exact": target}
        group_id = canonical(target["parent"])
        group = one(["--exact-id", group_id])
        assert group["type"] == family + "Group", group
        evidence.update(selected_target=target, selected_group=group)
        draft = _start_business_draft(commands, "object.create")
        segments = CONTAINERS_PARENT_SEGMENTS if runtime.version == "2025.1" else ACTOR_MIXER_PARENT_SEGMENTS
        parent_row = one([token for segment in segments for token in ("--path-segment", segment)])
        parent = _bind_business_object(commands, draft, object_id=parent_row["id"])
        target_handle = _bind_business_object(commands, draft, object_id=target["id"])
        group_handle = _bind_business_object(commands, draft, object_id=group["id"])
        kind = _discover_business_type(commands, draft, meaning="SwitchContainer", role="object", expected_label="SwitchContainer")
        fields = []
        # Deliberately declare the dependent first: the same-create condition
        # must resolve against the complete field set, not argument order.
        for meaning, handle in (("DefaultSwitchOrState", target_handle), (SWITCH_GROUP_REFERENCE, group_handle)):
            found = _update_business_draft(commands, draft, "draft-discover-fields",
                ["--type-handle", kind, "--meaning", meaning], live=True)
            fields.extend(["--field-value", discovered_business_field_handle(found, meaning), handle])
        name = "WAAPI_PROSPECTIVE_" + family + "_" + uuid.uuid4().hex[:12]
        _update_business_draft(commands, draft, "draft-declare-new",
            ["--declaration-id", "container", "--parent-handle", parent, "--name", name, "--kind", kind, *fields], live=False)
        completed = _complete_business_draft(commands, draft)
        created = _created_object_id(completed["execute"])
        row = one(["--exact-id", created], "--include", "parent",
                  "--include-field", SWITCH_GROUP_REFERENCE, "--include-field", "DefaultSwitchOrState")
        assert row["name"] == name and row["type"] == "SwitchContainer", row
        assert row["path"] == "\\" + "\\".join((*segments, name)), row
        assert canonical(row["id"]) == canonical(created)
        assert canonical(row["parent"]) == canonical(parent_row["id"]), row
        references = row["references"]
        assert canonical(references[SWITCH_GROUP_REFERENCE]) == canonical(group["id"]), row
        assert canonical(references["DefaultSwitchOrState"]) == canonical(target["id"]), row
        assert one(["--exact-id", target["id"]], "--include", "parent") == target
        assert one(["--exact-id", group["id"]]) == group
        evidence["independent_readback"] = row
        category.update(status="PASS", reason="one public create verified; independent identity, group/default references and original target/group preserved")
        return category
    except BaseException as exc:
        category["reason"] = f"{type(exc).__name__}: {exc}"
        evidence["error"] = category["reason"]
        raise
    finally:
        assert hashlib.sha256(config.read_bytes()).hexdigest() == config_hash, "Prospective reference acceptance changed config"
        paths = sorted(set(dispatcher.glob("*.json")) - previous)
        assert len(paths) <= 512
        total_bytes = 0
        for path in paths:
            body = path.read_bytes()
            total_bytes += len(body)
            assert total_bytes <= 32 * 1024 * 1024
            evidence["native_evidence"].append({"path": str(path), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
        body = json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category["observation_sha256"] = hashlib.sha256(body).hexdigest()


@pytest.mark.live
@pytest.mark.destructive
@pytest.mark.parametrize("family", ("Switch", "State"))
def test_prospective_group_default_native_acceptance(
    workflow_sandbox_runtime: _WorkflowSandboxRuntime, family: str,
) -> None:
    """Create one container with explicit group/default in the existing sandbox."""
    category = _collect_prospective_group_default_native_acceptance(workflow_sandbox_runtime, family)
    assert category["status"] == "PASS", category


def _collect_reference_enabled_metadata_probe(runtime: _WorkflowSandboxRuntime) -> dict[str, Any]:
    """Observe one existing non-master AuxBus reference; never infer a new-object default."""
    from wwise_waapi.documented_list_fields import load_catalog
    output = runtime.state_dir / 'reference-enabled-metadata-observation.json'
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    prior_evidence = set(evidence_root.glob('*.json'))
    category = {'category': 'reference-enabled-metadata-observation', 'status': 'FAIL',
        'observation_path': str(output), 'verifier_strength': 'read_only_exact_existing_object_field_state'}
    runtime.category_results.append(category)
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'calls': [],
        'endpoint': {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url},
        'config_path': runtime.env['WAAPI_SKILL_CONFIG_PATH'],
        'config_sha256': hashlib.sha256(Path(runtime.env['WAAPI_SKILL_CONFIG_PATH']).read_bytes()).hexdigest(),
        'native_evidence': [], 'mutation_authority': False, 'prospective_authority': False,
        'business_effect_verified': False, 'outcome': 'incomplete'}

    def retain():
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 2 * 1024 * 1024, 'Reference observer receipt bound exceeded'
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.tmp')
        temporary.write_bytes(body)
        temporary.replace(output)

    def raw(command):
        assert len(observation['calls']) < 64
        row = {'argv': list(command)}
        observation['calls'].append(row)
        try:
            code, payload = runtime.raw_gateway(command)
            row.update(exit_code=code, payload=payload)
            return code, payload
        finally:
            retain()

    def read(command):
        code, payload = raw(command)
        assert code == 0 and payload.get('ok') is True, payload
        return payload

    def exact(identity):
        result = read(['query-object', '--exact-id', identity, '--include', 'class-id', '--include', 'parent'])
        assert result.get('count') == 1 and len(result.get('objects', [])) == 1, result
        row = result['objects'][0]
        assert row['id'].upper() == identity.upper(), row
        return row

    def field_inventory(scope):
        rows, page, pages = [], None, set()
        for _ in range(4):
            result = read(['metadata', 'list', *scope, '--page-size', '64', *(['--page', page] if page else [])])['agent_result']
            rows.extend(result['fields'])
            if result.get('complete') is True:
                return rows
            page = _required_string(result, 'next_page')
            assert page not in pages
            pages.add(page)
        raise AssertionError('Exact field inventory not complete within four disclosed pages; no absence claim')

    try:
        types = read(['metadata', 'types', '--meaning', 'Bus', '--meaning', 'Platform', '--page-size', '64'])['agent_result']
        assert types.get('complete') is True, 'Filtered type inventory incomplete'
        aux_rows = [row for row in types['types'] if row.get('name') == 'AuxBus']
        platform_rows = [row for row in types['types'] if row.get('name') == 'Platform']
        assert len(aux_rows) == len(platform_rows) == 1
        source = load_catalog(runtime.version)
        classes = {row['name']: row for row in source['classes'] if row['name'] in {'AuxBus', 'Bus'}}
        aux = aux_rows[0]
        assert type(aux.get('classId')) is int and aux['classId'] == classes['AuxBus']['class_id']
        observation['source_class'] = {'catalog_sha256': source['catalog_sha256'],
            'class': {key: classes['AuxBus'][key] for key in ('name', 'class_id', 'source_member', 'source_sha256')}}
        candidates = read(['query-object', '--type-selection', aux['selection'], '--max-results', '20',
            '--include', 'class-id', '--include', 'parent'])
        chosen = None
        for candidate in candidates.get('objects') or []:
            if candidate.get('type') != 'AuxBus' or candidate.get('class_id') != aux['classId']:
                continue
            parent_id = (candidate.get('parent') or {}).get('id')
            if not isinstance(parent_id, str):
                continue
            parent = exact(parent_id)
            if parent.get('type') in classes and parent.get('class_id') == classes[parent['type']]['class_id']:
                chosen = exact(candidate['id'])
                assert all(chosen.get(key) == candidate.get(key) for key in ('id', 'name', 'type', 'path', 'class_id', 'parent')), (chosen, candidate)
                observation['parent'] = parent
                break
        if chosen is None:
            category.update(status='blocked', reason='No source/class/parent-proven non-master AuxBus in first 20 candidates')
            return category
        observation['object'] = chosen
        platforms = read(['query-object', '--type-selection', platform_rows[0]['selection'], '--max-results', '20'])
        assert platforms.get('objects'), 'No explicit project platform available'
        platform = platforms['objects'][0]
        assert platform['type'] == 'Platform' and platform.get('name')
        platform_exact = read(['query-object', '--exact-id', platform['id']])
        assert platform_exact.get('count') == 1 and platform_exact['objects'] == [platform], platform_exact
        observation['platform'] = platform
        object_scope = ['--exact-id', chosen['id']]
        class_scope = ['--type-selection', aux['selection']]
        object_names, class_names = field_inventory(object_scope), field_inventory(class_scope)
        observation['controller_name_absence'] = {
            'object': not any(row['name'] == 'OverrideUserAuxSends' for row in object_names),
            'class': not any(row['name'] == 'OverrideUserAuxSends' for row in class_names),
            'object_complete_names': [row['name'] for row in object_names], 'class_complete_names': [row['name'] for row in class_names]}
        selections = []
        for label, scope, names in [('object', object_scope, object_names), ('class', class_scope, class_names)]:
            selected, = [row for row in names if row['name'] == 'UserAuxSend0']
            detail = read(['metadata', 'detail', *scope, '--selection', selected['selection']])['agent_result']
            observation[label + '_field'] = detail
            assert detail.get('metadata', {}).get('name') == 'UserAuxSend0', detail
            selections.append(selected['selection'])
        code, result = raw(['metadata', 'property-state', *object_scope, '--selection', selections[0], '--platform', platform['id']])
        observation['enabled_response'] = {'exit_code': code, 'payload': result}
        if code != 0 or result.get('ok') is not True:
            observation['outcome'] = 'native_or_observation_failure'
            return category
        state = result['agent_result']
        assert state['field'] == 'UserAuxSend0' and state['kind'] == 'reference' and type(state['enabled']) is bool, state
        assert state['mutation_authority'] is False
        observation.update(outcome='observed_existing_reference_state', observed_enabled=state['enabled'])
        category['status'] = 'PASS'
        return category
    except Exception as exc:
        observation['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        paths = sorted(set(evidence_root.glob('*.json')) - prior_evidence)
        assert len(paths) <= 512
        total = 0
        for path in paths:
            body = path.read_bytes()
            total += len(body)
            assert total <= 32 * 1024 * 1024
            observation['native_evidence'].append({'path': str(path), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
        retain()


@pytest.mark.live
@pytest.mark.destructive
def test_read_only_reference_enabled_native_metadata_observation(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    category = _collect_reference_enabled_metadata_probe(workflow_sandbox_runtime)
    if category['status'] == 'blocked':
        pytest.skip(f'Existing reference observation blocked; receipt retained: {category}')
    assert category['status'] == 'PASS', category


def _collect_2021_rtpc_representation_diagnostic(runtime: _WorkflowSandboxRuntime) -> dict[str, Any]:
    """Inspect two source-pinned identities; no RTPC construction or effect claim."""
    assert runtime.version == '2021.1', 'This diagnostic is pinned to the2021 sample and catalog'
    output = runtime.state_dir / 'rtpc-2021-representation-diagnostic.json'
    assert not output.exists(), 'An earlier diagnostic must never be overwritten'
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    prior_evidence = set(evidence_root.glob('*.json'))
    config = Path(runtime.env['WAAPI_SKILL_CONFIG_PATH'])
    report: dict[str, Any] = {
        'contract': 'waapi-skill.rtpc-2021-representation-diagnostic/v1',
        'candidate': runtime.candidate, 'version': runtime.version,
        'endpoint': {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url},
        'config_path': str(config), 'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
        'source': {'sdk_build': '2021.1.14.8108',
            'authority_report': '/tmp/full-coverage-180-rtpc-2021-authority.md',
            'sdk_archive': '/Applications/Audiokinetic/Wwise2021.1.14.8108/SDK/Help/WwiseSDK-Windows.chm',
            'sdk_members': ['ak_wwise_core_object_create.html', 'wwiseobject_curve.html'],
            'saved_model': 'tests/_org/2021.1/Actor-Mixer Hierarchy/Car Engine.wwu',
            'saved_model_sha256': '499654bb8ab436ae52ef74067d14beb7fe4335009b1ff2cea380aabfada9d214',
            'scope': 'saved identities only; no live class/list/field token inferred from saved XML'},
        'bounds': {'calls': 32, 'name_pages_per_object': 4, 'names_per_page': 64,
            'detail_fields': 6, 'detail_pages_per_field': 2, 'relationship_reads': 2,
            'reply_bytes': 256 * 1024, 'total_reply_bytes': 2 * 1024 * 1024,
            'receipt_bytes': 4 * 1024 * 1024, 'native_evidence_files': 512,
            'native_evidence_bytes': 32 * 1024 * 1024},
        'calls': [], 'objects': [], 'field_details': [], 'relationship_reads': [],
        'boundaries': [], 'native_evidence': [], 'collection_complete': False,
        'mutation_authority': False, 'business_effect_verified': False, 'native_absence_proven': False,
    }
    category = {'category': 'rtpc-2021-representation-diagnostic', 'status': 'FAIL',
        'diagnostic_only': True, 'business_effect_verified': False, 'observation_path': str(output),
        'verifier_strength': 'read_only_source_guid_identity_and_disclosed_metadata_observation',
        'reason': 'diagnostic collection incomplete'}
    runtime.category_results.append(category)
    total_bytes = 0

    def retain() -> None:
        body = json.dumps(report, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        assert len(body) <= report['bounds']['receipt_bytes'], 'RTPC diagnostic receipt byte bound exceeded'
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.tmp')
        temporary.write_bytes(body)
        temporary.replace(output)
        category['observation_sha256'] = hashlib.sha256(body).hexdigest()

    def boundary(stage: str, reason: str, **facts: Any) -> None:
        report['boundaries'].append({'stage': stage, 'reason': reason, **facts})

    def read(stage: str, command: Sequence[str]) -> dict[str, Any] | None:
        nonlocal total_bytes
        assert len(report['calls']) < report['bounds']['calls'], 'RTPC diagnostic public call bound exceeded'
        entry = {'stage': stage, 'gateway_argv': list(command)}
        report['calls'].append(entry)
        try:
            code, payload = runtime.raw_gateway(command)
            entry.update(exit_code=code, payload=payload)
            size = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
            total_bytes += size
            assert size <= report['bounds']['reply_bytes'] and total_bytes <= report['bounds']['total_reply_bytes'], 'RTPC diagnostic reply byte bound exceeded'
            if code != 0 or payload.get('ok') is not True:
                boundary(stage, 'public_read_rejected', error_code=payload.get('error_code'))
                return None
            if command[0] not in {'config-show', 'query-schema'}:
                assert payload.get('endpoint') == report['endpoint'], 'RTPC diagnostic endpoint changed'
                assert payload.get('detected_version') == runtime.version, 'RTPC diagnostic version changed'
            return payload
        except Exception as exc:
            entry['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
            raise
        finally:
            retain()

    def query(stage: str, source: Sequence[str]) -> list[dict[str, Any]]:
        payload = read(stage, ['query-object', *source, '--max-results', '2',
            '--include', 'class-id', '--include', 'parent', '--include', 'owner'])
        if payload is None:
            return []
        rows = payload.get('objects')
        assert isinstance(rows, list) and len(rows) <= 1, 'Exact diagnostic query returned ambiguous rows'
        assert payload.get('projection_complete') is not False and payload.get('status') != 'partial', 'RTPC diagnostic projection is incomplete'
        return rows

    def canonical(value: Any) -> bool:
        try:
            return isinstance(value, str) and value.casefold() == ('{' + str(uuid.UUID(value)) + '}').casefold()
        except ValueError:
            return False

    def names(item: dict[str, Any]) -> list[dict[str, Any]]:
        fields, seen_pages, page = [], set(), None
        for _ in range(report['bounds']['name_pages_per_object']):
            command = ['metadata', 'list', '--exact-id', item['requested_id'], '--page-size', '64']
            if page is not None:
                command += ['--page', page]
            payload = read(item['role'] + '-names', command)
            if payload is None:
                return []
            result = payload['agent_result']
            batch = result.get('fields')
            assert isinstance(batch, list) and len(batch) <= 64, 'RTPC diagnostic name row bound exceeded'
            for field in batch:
                name = field.get('name')
                assert isinstance(name, str) and name and name not in item['field_names'], 'Malformed or duplicate disclosed field name'
                item['field_names'].append(name)
                assert isinstance(field.get('selection'), str) and field['selection'], 'Disclosed field lacks scoped selection'
                fields.append(field)
            page = result.get('next_page')
            if page is None:
                assert result.get('complete') is True and result.get('total_count') == len(fields), 'Incomplete RTPC diagnostic name inventory'
                item['names_complete'] = True
                return fields
            assert isinstance(page, str) and page and page not in seen_pages, 'Repeated or malformed metadata page'
            seen_pages.add(page)
        raise AssertionError('RTPC diagnostic metadata exceeds four pages; no complete inventory or absence claim')

    def detail(item: dict[str, Any], field: Mapping[str, Any]) -> dict[str, Any] | None:
        record = {'object_id': item['requested_id'], 'disclosed_field': field['name'], 'pages': []}
        report['field_details'].append(record)
        command = ['metadata', 'detail', '--exact-id', item['requested_id'], '--selection', field['selection']]
        for _ in range(report['bounds']['detail_pages_per_field']):
            payload = read(item['role'] + '-' + field['name'] + '-detail', command)
            if payload is None:
                return None
            result = payload['agent_result']
            record['pages'].append(result)
            if result.get('complete') is True:
                return result.get('metadata') if len(record['pages']) == 1 else None
            command = result.get('next_command', {}).get('gateway_argv')
            assert isinstance(command, list) and command[:2] == ['metadata', 'detail'], 'Metadata detail continuation unavailable'
        boundary(item['role'], 'detail_page_bound_reached', disclosed_field=field['name'])
        return None

    def follow(stage: str, identity: Any, *, source: Sequence[str] | None = None) -> None:
        assert len(report['relationship_reads']) < 2, 'RTPC diagnostic relationship bound exceeded'
        if source is None and not canonical(identity):
            boundary(stage, 'disclosed_relationship_identity_missing_or_malformed', value=identity)
            return
        rows = query(stage, source or ['--exact-id', identity])
        report['relationship_reads'].append({'stage': stage, 'source_id': identity, 'identity_rows': rows})
        if rows and source is not None:
            returned = rows[0].get('id')
            if not canonical(returned):
                boundary(stage, 'returned_relationship_identity_missing_or_malformed', value=returned)
                return
            exact = query(stage + '-exact-id', ['--exact-id', returned])
            report['relationship_reads'][-1]['exact_identity_rows'] = exact
            if exact != rows:
                boundary(stage, 'relationship_exact_readback_changed')
        elif rows and rows[0].get('id', '').casefold() != identity.casefold():
            boundary(stage, 'exact_relationship_identity_mismatch')

    try:
        read('configuration', ['config-show'])
        status = read('host-and-project', ['status'])
        assert status is not None, 'Exact2021 host/project status unavailable'
        report['runtime_version_observed'] = status.get('wwise', {}).get('version')
        observed = report['runtime_version_observed']
        assert (isinstance(observed, Mapping)
            and all(type(observed.get(key)) is int for key in ('year', 'major', 'minor', 'build'))
            and [observed[key] for key in ('year', 'major', 'minor', 'build')] == [2021, 1, 14, 8108]), 'Exact2021.1.14.8108 source/SDK build differs from observed host'
        read('disclosed-read-contract', ['query-schema', '--advanced'])
        for role, identity in [('Sound', '{9EEFCC8E-7FC2-4CDC-8BE9-C682F2CA77CC}'),
                               ('saved-internal-RTPC', '{A809A571-6012-42BE-A00D-D8E7C89D1248}')]:
            item = {'role': role, 'requested_id': identity, 'identity_rows': [], 'field_names': [], 'names_complete': False}
            report['objects'].append(item)
            item['identity_rows'] = query(role + '-exact-id', ['--exact-id', identity])
            if not item['identity_rows']:
                boundary(role, 'exact_internal_identity_not_observed', requested_id=identity,
                    meaning='zero/error observation only; no native absence or construction conclusion')
                continue
            row = item['identity_rows'][0]
            if not canonical(row.get('id')) or row['id'].casefold() != identity.casefold():
                boundary(role, 'exact_identity_mismatch')
                continue
            for key in ('name', 'type', 'path', 'class_id', 'parent', 'owner'):
                if key not in row:
                    boundary(role, 'identity_output_omitted', field=key)
            fields = names(item)
            for field in fields:
                if not any(word in field['name'].casefold() for word in ('rtpc', 'curve', 'controlinput', 'property', 'owner')):
                    continue
                if len(report['field_details']) == 6:
                    report['detail_limit_reached'] = True
                    break
                metadata = detail(item, field)
                restriction = metadata.get('restriction', {}) if isinstance(metadata, Mapping) else {}
                if (role == 'saved-internal-RTPC' and field['name'] == 'Curve'
                        and isinstance(restriction, Mapping) and restriction.get('type') == 'reference'):
                    follow('disclosed-RTPC-Curve', identity,
                        source=['--advanced-waql', f'from object "{identity}" select @{field["name"]}'])
            if role == 'saved-internal-RTPC' and isinstance(row.get('owner'), Mapping):
                follow('returned-RTPC-owner', row['owner'].get('id'))
        report['collection_complete'] = True
        category.update(status='blocked', reason='Read-only diagnostic only; no construction, mutation, absence or business effect credit')
        return category
    except Exception as exc:
        report['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
        raise
    finally:
        completed_status, completed_reason = category['status'], category['reason']
        category.update(status='FAIL', reason='Diagnostic evidence retention incomplete')
        try:
            paths = sorted(set(evidence_root.glob('*.json')) - prior_evidence)
            assert len(paths) <= 512, 'RTPC diagnostic dispatcher evidence file bound exceeded'
            total = 0
            for path in paths:
                assert path.stat().st_size <= 32 * 1024 * 1024 - total, 'RTPC diagnostic dispatcher evidence byte bound exceeded'
                body = path.read_bytes()
                total += len(body)
                assert total <= 32 * 1024 * 1024, 'RTPC diagnostic dispatcher evidence byte bound exceeded'
                report['native_evidence'].append({'path': str(path), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
        except Exception as exc:
            report['retention_failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
            retain()
            raise
        retain()
        category.update(status=completed_status, reason=completed_reason)


@pytest.mark.live
@pytest.mark.destructive
def test_gateway_2021_rtpc_representation_diagnostic(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    """Developer-only collection can complete; its category never grants effect credit."""
    category = _collect_2021_rtpc_representation_diagnostic(workflow_sandbox_runtime)
    assert category['status'] == 'blocked' and category['diagnostic_only'] is True, category


def _collect_existing_effect_slot_exact_member_acceptance(runtime: _WorkflowSandboxRuntime, *, sound_name: str) -> dict[str, Any]:
    """Exact-ID anonymous-member edits; never inline List name-merge acceptance."""
    output = runtime.state_dir / "existing-effect-slot-exact-member-acceptance.json"
    category = {"category": "existing-effect-slot-exact-member", "status": "FAIL",
        "verifier_strength": "gateway_verified_plus_independent_ordered_membership_class_owner_reference_and_scalar_reads",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    receipt = {"candidate": runtime.candidate, "version": runtime.version, "calls": [], "transactions": [],
        "setup_coverage_credit": False, "business_effect_verified": False, "inline_list_merge_verified": False,
        "inline_list_boundary": "Anonymous List construction and ambiguous empty-name collision merging remain separate unfinished branches",
        "lifecycle_acceptance": "Requires the existing host-category-evidence/v3 finalizer; no source/cleanup acceptance before teardown"}
    def persist():
        body = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 8 * 1024 * 1024, 'EffectSlot receipt byte bound exceeded'
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(body); temporary.replace(output)
    class ReceiptGateway:
        def raw_gateway(self, argv):
            assert len(receipt['calls']) < 192, 'EffectSlot public call bound exceeded'
            row = {'argv': list(argv)}; receipt['calls'].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                row.update(exit_code=code, payload=payload)
                return code, payload
            except Exception as exc:
                row['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
                raise
            finally:
                persist()
        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            return payload
    gateway = ReceiptGateway()
    def query(argv, *, count=None):
        result = gateway.gateway(['query-object', *argv], live=True)
        rows = result.get('objects')
        assert isinstance(rows, list) and result.get('projection_complete') is not False, result
        assert result.get('limit_reached') is not True and result.get('status') != 'partial', result
        if count is not None:
            assert result.get('count') == len(rows) == count, result
        assert len(rows) <= 3 and len({row['id'] for row in rows}) == len(rows), rows
        for row in rows:
            assert uuid.UUID(row['id']).int != 0 and isinstance(row.get('path'), str), row
        return rows
    projection = ['--include', 'class-id', '--include', 'owner', '--include', 'parent', '--include', 'notes']
    def exact(identity, fields=()):
        row = query(['--exact-id', identity, *projection,
            *(arg for field in fields for arg in ('--include-field', field))], count=1)[0]
        assert row['id'] == identity and type(row.get('class_id')) is int, row
        return row
    def members(owner, *, count):
        return query(['--advanced-waql', f'from object "{owner}" select @Effects', '--max-results', '3', *projection], count=count)
    def field_names(identity, required=()):
        page, names, selected = None, [], []
        for _ in range(4):
            result = gateway.gateway(['metadata', 'list', '--exact-id', identity, '--page-size', '64',
                *(['--page', page] if page is not None else [])], live=True)['agent_result']
            for field in result['fields']:
                name = field.get('name')
                assert isinstance(name, str) and name not in names, result
                names.append(name)
                if not required or name in required:
                    selected.append((name, field['selection']))
            if result['complete'] is True:
                assert len(names) == result['total_count'], result
                break
            next_page = _required_string(result, 'next_page')
            assert next_page != page, result
            page = next_page
        else:
            raise AssertionError('EffectSlot metadata exceeds four pages')
        assert set(required).issubset(names), (identity, required, names)
        assert len(selected) <= 8, 'Private effect metadata exceeds eight-field preservation bound'
        details = []
        for name, selection in selected:
            result = gateway.gateway(['metadata', 'detail', '--exact-id', identity, '--selection', selection], live=True)['agent_result']
            assert result.get('complete') is True, result
            details.append({'name': name, 'detail': result})
        receipt.setdefault('metadata', {})[identity] = {'names': names, 'details': details}
        return [name for name, _ in selected]
    def reference(row):
        value = row.get('references', {}).get('Effect')
        identity = value.get('id') if isinstance(value, Mapping) else value
        assert isinstance(identity, str) and uuid.UUID(identity).int != 0, row
        return identity
    def snapshot(owner, known, effect_fields):
        sound = exact(owner)
        assert sound['type'] == 'Sound' and sound['class_id'] == 65552, sound
        rows = members(owner, count=2)
        assert [row['id'] for row in rows] == known, (known, rows)
        slots, effects = [], []
        for listed in rows:
            row = exact(listed['id'], ('Effect', 'Bypass', 'Render'))
            assert all((key in row) == (key in listed) and row.get(key) == listed.get(key)
                for key in ('id', 'name', 'type', 'path', 'class_id', 'parent', 'owner', 'notes')), (listed, row)
            assert row['name'] == '' and row['class_id'] == 5505040, row
            assert row.get('owner', {}).get('id') == owner, row
            if 'parent' in row:
                assert isinstance(row['parent'], Mapping) and row['parent'].get('id') == owner, row
                assert 'parent' not in row.get('unavailable_fields', []), row
            else:
                assert 'parent' in row.get('unavailable_fields', []), row
            assert all(type(row.get('properties', {}).get(token)) is bool for token in ('Bypass', 'Render')), row
            identity = reference(row)
            effect = exact(identity, effect_fields[identity])
            assert effect['type'] == 'Effect', effect
            # Match the existing plugin verifier's observed representation, not
            # an invented hierarchy. Embedded Effects have immediate slot owner
            # with no parent; a present hierarchy parent is retained explicitly.
            if 'parent' in effect:
                assert isinstance(effect['parent'], Mapping) and effect['parent'].get('id') == row['id'], effect
                assert 'parent' not in effect.get('unavailable_fields', []), effect
                expected_effect_owner = owner
            else:
                assert 'parent' in effect.get('unavailable_fields', []), effect
                expected_effect_owner = row['id']
            assert effect.get('owner', {}).get('id') == expected_effect_owner, effect
            slots.append(row); effects.append(effect)
        assert len({row['id'] for row in [sound, *slots, *effects]}) == 5, (slots, effects)
        return {'owner': sound, 'slots': slots, 'effects': effects}
    def complete(draft, label, *, before=None, known=None, effect_fields=None, value=None, renamed=None):
        phase = {'phase': label, 'native_outcome': 'not_executed', 'effect_verified': False}
        receipt['transactions'].append(phase)
        _update_business_draft(gateway, draft, 'draft-check', live=True)
        preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
        identity = _required_string(preview, 'transaction_id')
        shown = gateway.gateway(['transaction-show', identity], live=False)
        prepared = shown['artifact']['prepared_operation']
        phase.update(transaction_id=identity, artifact_hash=preview['artifact_hash'], compiled_native_request=prepared['dispatch'])
        if before is not None:
            selected = before['slots'][0]
            nodes = prepared['verification_plan']['nodes']
            node = next(row for row in nodes if row.get('target_id') == selected['id'])
            assert node['existing_target'] is True and node['pre_state']['id'] == selected['id'], node
            assert node['pre_state']['name'] == '' and node['pre_state']['path'] == selected['path'], node
            assert any(row.get('name') == 'Effect' and row.get('condition_guard') is True
                and row.get('target_id') == reference(selected) for row in node['references']), node
            args = prepared['dispatch']['args']
            assert prepared['dispatch']['uri'] == 'ak.wwise.core.object.set', prepared
            expected = [{'object': selected['id'], '@Bypass': value}]
            if renamed is not None:
                expected.insert(0, {'object': before['owner']['id'], 'name': renamed})
            assert args['objects'] == expected, args
            assert '@Effects' not in json.dumps(args) and '@Effect"' not in json.dumps(args), args
            # Collector-owned independent prestate, not an invented durable
            # membership seal inside the generic exact-ID transaction artifact.
            phase['collector_prestate'] = snapshot(before['owner']['id'], known, effect_fields)
            assert phase['collector_prestate'] == before, (before, phase['collector_prestate'])
        gateway.gateway(['confirm', identity, '--confirmation-token', shown['confirmation']['token']], live=False)
        phase['native_outcome'] = 'indeterminate'
        code, executed = gateway.raw_gateway(['execute', identity]); phase['execute'] = {'exit_code': code, 'payload': executed}
        assert code == 0 and executed.get('ok') is True, executed
        assert executed.get('state') == 'executed_unverified' and executed.get('automatic_retry') is False, executed
        phase['native_outcome'] = 'accepted'
        code, verified = gateway.raw_gateway(['verify', identity]); phase['verify'] = {'exit_code': code, 'payload': verified}
        assert code == 0 and verified.get('verified') is True and verified.get('state') == 'verified', verified
        assert verified.get('verification', {}).get('business_state_verified') is True, verified
        return phase
    try:
        assert runtime.version in {'2023.1', '2024.1', '2025.1'}, 'Modern anonymous-slot witness excludes no legacy scalar outcome'
        gateway.gateway(['query-schema', '--advanced'], live=False)
        types = gateway.gateway(['metadata', 'types', '--meaning', 'Sound', '--meaning', 'EffectSlot', '--meaning', 'Wwise Gain', '--page-size', '64'], live=True)['agent_result']
        assert types.get('complete') is True, types
        classes = {}
        for name in ('Sound', 'EffectSlot', 'Wwise Gain'):
            matches = [row for row in types['types'] if row.get('name') == name]
            assert len(matches) == 1 and type(matches[0].get('classId')) is int, matches
            classes[name] = matches[0]['classId']
        assert classes['Sound'] == 65552 and classes['EffectSlot'] == 5505040, classes
        receipt['live_classes'] = classes
        segments = ('Containers' if runtime.version == '2025.1' else 'Actor-Mixer Hierarchy', 'Default Work Unit')
        setup = _start_business_draft(gateway, 'object.create')
        parent = _bind_business_object(gateway, setup, path_segments=segments)
        kind = _discover_business_type(gateway, setup, meaning='Sound', role='object', expected_label='Sound')
        _update_business_draft(gateway, setup, 'draft-declare-new', ['--declaration-id', 'sound', '--parent-handle', parent,
            '--name', sound_name, '--kind', kind, '--field', 'notes', 'Keep sound'], live=False)
        complete(setup, 'setup_sound_no_credit')
        found = query([*(arg for segment in (*segments, sound_name) for arg in ('--path-segment', segment))], count=1)[0]
        owner = found['id']
        assert members(owner, count=0) == []
        known = []
        for index in range(2):
            setup = _start_business_draft(gateway, 'object.createPlugin')
            target = _bind_business_object(gateway, setup, object_id=owner)
            plugin = _discover_business_type(gateway, setup, meaning='Wwise Gain', role='effect', expected_label='Wwise Gain')
            _update_business_draft(gateway, setup, 'draft-declare-existing', ['--declaration-id', 'gain', '--object-handle', target,
                '--field', 'plugin_role', 'effect', '--field', 'plugin_placement', 'owner',
                '--field', 'plugin_name', f'Gain{index}', '--field', 'plugin_type_handle', plugin,
                '--field', 'notes', f'Keep effect{index}'], live=False)
            complete(setup, f'setup_effect_{index}_no_credit')
            rows = members(owner, count=index + 1)
            assert [row['id'] for row in rows[:index]] == known, rows
            added = set(row['id'] for row in rows) - set(known)
            assert len(added) == 1, rows
            known.append(added.pop())
        effect_fields = {}
        for identity in known:
            field_names(identity, ('Effect', 'Bypass', 'Render'))
            slot = exact(identity, ('Effect', 'Bypass', 'Render'))
            effect_id = reference(slot)
            effect_fields[effect_id] = field_names(effect_id)
        before = snapshot(owner, known, effect_fields)
        receipt['baseline'] = before
        assert all(row['properties']['Bypass'] is False for row in before['slots']), before
        assert all(row['class_id'] == classes['Wwise Gain'] for row in before['effects']), before
        for label, value, renamed in [('exact_member_bypass', True, None),
                ('owner_rename_and_exact_member_bypass', False, sound_name + '_Renamed')]:
            # Always rebind the second phase to a fresh post-first observation.
            fresh = snapshot(owner, known, effect_fields)
            assert fresh == before, (before, fresh)
            draft = _start_business_draft(gateway, 'object.set')
            if renamed is not None:
                target = _bind_business_object(gateway, draft, object_id=owner)
                _update_business_draft(gateway, draft, 'draft-declare-existing', ['--declaration-id', 'owner',
                    '--object-handle', target, '--field', 'new_name', renamed], live=False)
            target = _bind_business_object(gateway, draft, object_id=known[0])
            listed = _update_business_draft(gateway, draft, 'draft-discover-fields', ['--object-handle', target, '--list'], live=True)['agent_result']
            selected = [row for row in listed['fields'] if row.get('name') == 'Bypass']
            assert len(selected) == 1, listed
            field = _update_business_draft(gateway, draft, 'draft-discover-fields', ['--object-handle', target,
                '--selection', selected[0]['selection']], live=True)
            handle = discovered_business_field_handle(field, 'Bypass')
            _update_business_draft(gateway, draft, 'draft-declare-existing', ['--declaration-id', 'slot',
                '--object-handle', target, '--field-value', handle, 'true' if value else 'false'], live=False)
            phase = complete(draft, label, before=fresh, known=known, effect_fields=effect_fields, value=value, renamed=renamed)
            expected = json.loads(json.dumps(fresh))
            if renamed is not None:
                old_path = fresh['owner']['path']; new_path = old_path.rsplit('\\', 1)[0] + '\\' + renamed
                def renamed_observation(item):
                    if isinstance(item, dict):
                        result = {key: renamed_observation(child) for key, child in item.items()}
                        if item.get('id') == owner and 'name' in item: result['name'] = renamed
                        if isinstance(item.get('path'), str) and (item['path'] == old_path or item['path'].startswith(old_path + '\\')):
                            result['path'] = new_path + item['path'][len(old_path):]
                        return result
                    return [renamed_observation(child) for child in item] if isinstance(item, list) else item
                expected = renamed_observation(expected)
            expected['slots'][0]['properties']['Bypass'] = value
            observed = snapshot(owner, known, effect_fields)
            phase['independent_effect'] = observed
            assert observed == expected, (label, expected, observed)
            phase['effect_verified'] = True
            before = observed
        receipt['business_effect_verified'] = True
        category['status'] = 'PASS'
        return category
    except Exception as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        persist()


@pytest.mark.live
@pytest.mark.destructive
def test_existing_effect_slot_exact_member_acceptance(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    """Shared setup, two exact-ID edits; no anonymous inline List merge credit."""
    if workflow_sandbox_runtime.version not in {'2023.1', '2024.1', '2025.1'}:
        pytest.skip('2021–2022 scalar EffectN fields remain a separate witness')
    category = _collect_existing_effect_slot_exact_member_acceptance(workflow_sandbox_runtime,
        sound_name='WAAPI_SLOT_' + uuid.uuid4().hex[:12])
    assert category['status'] == 'PASS', category


def _collect_rtpc_graph_acceptance(runtime: _WorkflowSandboxRuntime, *, name: str) -> dict[str, Any]:
    """Five graph effects with independent complete pair/Curve observations."""
    import math
    from copy import deepcopy
    output = runtime.state_dir / 'rtpc-graph-acceptance.json'
    category = {'category': 'rtpc-graph-acceptance', 'status': 'FAIL', 'observation_path': str(output),
        'verifier_strength': 'gateway_verified_plus_independent_complete_ordered_pairs_and_exact_curve_points'}
    runtime.category_results.append(category)
    receipt = {'candidate': runtime.candidate, 'version': runtime.version, 'calls': [], 'effects': [],
        'setup_coverage_credit': False, 'business_effect_verified': False, 'complete': False, 'metadata': {},
        'exclusive': {'status': 'pending', 'reason': 'No legal active source-backed Exclusive field proved'},
        'lifecycle_acceptance': 'Existing host-category-evidence/v3 finalizer owns source, host and cleanup proof'}
    def persist():
        body = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 16 * 1024 * 1024, 'RTPC graph receipt byte bound exceeded'
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(body); temporary.replace(output)
        category['observation_sha256'] = hashlib.sha256(body).hexdigest()
    class Gateway:
        def raw_gateway(self, argv):
            assert len(receipt['calls']) < 384, 'RTPC graph public call bound exceeded'
            row = {'argv': list(argv)}; receipt['calls'].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                row.update(exit_code=code, payload=payload)
                return code, payload
            except Exception as exc:
                row['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
                raise
            finally:
                persist()
        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            return payload
    gateway = Gateway()
    projection = ['--include', 'class-id', '--include', 'owner', '--include', 'parent', '--include', 'notes']
    def query(argv, *, count=None):
        payload = gateway.gateway(['query-object', *argv], live=True)
        rows = payload.get('objects')
        assert isinstance(rows, list) and len(rows) <= 8, payload
        assert payload.get('limit_reached') is not True and payload.get('projection_complete') is not False, payload
        assert payload.get('status') != 'partial' and len({row['id'] for row in rows}) == len(rows), payload
        if count is not None: assert payload.get('count') == len(rows) == count, payload
        for row in rows:
            assert uuid.UUID(row['id']).int != 0 and isinstance(row.get('path'), str), row
        return rows
    def exact(identity, fields=(), *, curve=False):
        rows = query(['--exact-id', identity, *projection,
            *(arg for field in fields for arg in ('--include-field', field)),
            *(['--include', 'curve-points'] if curve else [])], count=1)
        assert rows[0]['id'] == identity and type(rows[0].get('class_id')) is int, rows
        return rows[0]
    def inventory(identity, wanted):
        names, choices, page = [], {}, None
        for _ in range(4):
            result = gateway.gateway(['metadata', 'list', '--exact-id', identity, '--page-size', '64',
                *(['--page', page] if page else [])], live=True)['agent_result']
            for field in result['fields']:
                assert isinstance(field.get('name'), str) and field['name'] not in names, result
                names.append(field['name'])
                if field['name'] in wanted: choices[field['name']] = field['selection']
            if result.get('complete') is True:
                assert len(names) == result['total_count'], result
                break
            page = _required_string(result, 'next_page')
        else: raise AssertionError('RTPC graph names exceed four complete pages')
        details = {}
        for token, selection in choices.items():
            result = gateway.gateway(['metadata', 'detail', '--exact-id', identity, '--selection', selection], live=True)['agent_result']
            assert result.get('complete') is True, result
            details[token] = {'selection': selection, 'metadata': result['metadata']}
        receipt['metadata'][identity] = {'names': names, 'details': details}
        return details
    def ref(row, token):
        value = row.get('references', {}).get(token)
        identity = value.get('id') if isinstance(value, Mapping) else value
        assert isinstance(identity, str) and uuid.UUID(identity).int != 0, (token, row)
        return identity
    def membership(owner):
        return query(['--advanced-waql', f'from object "{owner}" select @RTPC', '--max-results', '8', *projection])
    def snapshot(owner):
        if owner not in receipt['metadata']:
            inventory(owner, tuple(field_details))
        selected = tuple(receipt['metadata'][owner]['details'])
        sound = exact(owner, selected)
        assert set(sound.get('properties', {})) == set(selected), sound
        assert sound['type'] == 'Sound' and sound['class_id'] == classes['Sound'], sound
        listed = membership(owner)
        members = []
        for candidate in listed:
            if candidate['id'] not in receipt['metadata']:
                details = inventory(candidate['id'], ('PropertyName', 'ControlInput', 'Curve'))
                assert set(details) == {'PropertyName', 'ControlInput', 'Curve'}, details
            row = exact(candidate['id'], ('PropertyName', 'ControlInput', 'Curve'))
            assert {key: row[key] for key in candidate} == candidate, (candidate, row)
            assert row['type'] == 'RTPC' and row['name'] == '' and row['class_id'] == classes['RTPC'], row
            assert row.get('owner', {}).get('id') == owner, row
            assert isinstance(row.get('properties', {}).get('PropertyName'), str), row
            control = ref(row, 'ControlInput')
            assert control in controls_by_id, row
            assert exact(control, ('Min', 'Max')) == controls_by_id[control]['object'], row
            curve_id = ref(row, 'Curve')
            hopped = query(['--advanced-waql', f'from object "{row["id"]}" select @Curve', '--max-results', '2',
                *projection, '--include', 'curve-points'], count=1)[0]
            curve = exact(curve_id, curve=True)
            assert hopped == curve and curve['id'] == curve_id and curve['type'] == 'Curve', (hopped, curve)
            # The canonical Curve hop proves the reference, not an invented
            # immediate owner/parent hierarchy. Preserve actual optional facts.
            assert curve['class_id'] == classes['Curve'], curve
            points = curve.get('curve_points')
            assert isinstance(points, list) and 1 <= len(points) <= 256, curve
            assert all(set(point) == {'x', 'y', 'shape'} and all(type(point[key]) in (int, float)
                and math.isfinite(point[key]) for key in ('x', 'y')) for point in points), curve
            members.append({'object': row, 'curve': curve, 'pair': [row['properties']['PropertyName'], control]})
        assert len({tuple(row['pair']) for row in members}) == len(members), members
        return {'owner': sound, 'members': members}
    def selected_field(draft, token, *, owner=None, kind=None):
        scope = ['--object-handle', owner] if owner else ['--type-handle', kind]
        # The token came from the complete source-backed metadata inventory;
        # do not assume it lies on the first Draft list page.
        result = _update_business_draft(gateway, draft, 'draft-discover-fields', [*scope, '--meaning', token], live=True)
        return discovered_business_field_handle(result, token)
    def declare(draft, owner_handle, token, control_id, points, declaration, *, kind=None):
        control = _bind_business_object(gateway, draft, object_id=control_id)
        field = selected_field(draft, token, owner=owner_handle if kind is None else None, kind=kind)
        _update_business_draft(gateway, draft, 'draft-declare-rtpc', ['--declaration-id', declaration,
            '--object-handle', owner_handle, '--field-handle', field, '--control-input-handle', control,
            '--notes', 'Keep ' + declaration,
            *(arg for point in points for arg in ('--point', str(point['x']), str(point['y']), point['shape']))], live=False)
    def points(token, control_id, offset):
        bounds = controls_by_id[control_id]['source_range']
        restriction = field_details[token]['metadata']['restriction']
        low, high = restriction.get('min'), restriction.get('max')
        assert all(type(value) in (int, float) and math.isfinite(value) for value in (low, high)) and low < high, restriction
        return [{'x': bounds['minimum'], 'y': low + (high - low) * offset, 'shape': 'Linear'},
            {'x': bounds['maximum'], 'y': low + (high - low) * (offset + 0.25), 'shape': 'Linear'}]
    def complete(draft, label, *, effect=True):
        phase = {'phase': label, 'effect_verified': False, 'native_outcome': 'not_executed'}
        (receipt['effects'] if effect else receipt.setdefault('setup', [])).append(phase)
        phase_category = {'category': 'rtpc-graph-' + label, 'status': 'FAIL', 'observation_path': str(output),
            'setup_coverage_credit': False,
            'verifier_strength': ('gateway_verified_plus_independent_complete_ordered_pairs_and_exact_curve_points'
                if effect else 'gateway_verified_setup_only_no_effect_coverage_credit')}
        runtime.category_results.append(phase_category)
        _update_business_draft(gateway, draft, 'draft-check', live=True)
        preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
        identity = _required_string(preview, 'transaction_id')
        shown = gateway.gateway(['transaction-show', identity], live=False)
        assert shown['artifact']['prepared_operation']['dispatch']['uri'] == 'ak.wwise.core.object.set', shown
        phase.update(transaction_id=identity, artifact_hash=preview['artifact_hash'],
            compiled_native_request=shown['artifact']['prepared_operation']['dispatch'])
        gateway.gateway(['confirm', identity, '--confirmation-token', shown['confirmation']['token']], live=False)
        phase['native_outcome'] = 'indeterminate'
        code, executed = gateway.raw_gateway(['execute', identity]); phase['execute'] = {'exit_code': code, 'payload': executed}
        assert code == 0 and executed.get('state') == 'executed_unverified' and executed.get('automatic_retry') is False, executed
        phase['native_outcome'] = 'accepted'
        code, verified = gateway.raw_gateway(['verify', identity]); phase['verify'] = {'exit_code': code, 'payload': verified}
        assert code == 0 and verified.get('verified') is True and verified.get('verification', {}).get('business_state_verified') is True, verified
        return phase, phase_category
    def admit(phase, phase_category, observed):
        phase['independent_effect'] = observed
        phase['effect_verified'] = True
        phase_category['status'] = 'PASS'
    def check_pairs(observed, expected):
        assert [row['pair'] for row in observed['members']] == [row['pair'] for row in expected], (expected, observed)
        for actual, wanted in zip(observed['members'], expected, strict=True):
            assert actual['curve']['curve_points'] == wanted['points'], (wanted, actual)
            assert actual['object']['notes'] == wanted['notes'], (wanted, actual)
    try:
        assert runtime.version in {'2022.1', '2023.1', '2024.1', '2025.1'}, 'No fabricated 2021 RTPC graph construction'
        schema = gateway.gateway(['query-schema', '--output', 'curve-points'], live=False)
        assert 'curve-points' in json.dumps(schema) and 'points' in json.dumps(schema), schema
        gateway.gateway(['query-schema', '--advanced'], live=False)
        reflected = gateway.gateway(['metadata', 'types', '--meaning', 'Sound', '--meaning', 'GameParameter',
            '--meaning', 'RTPC', '--meaning', 'Curve', '--page-size', '64'], live=True)['agent_result']
        assert reflected.get('complete') is True, reflected
        classes = {}
        for token in ('Sound', 'GameParameter', 'RTPC', 'Curve'):
            match, = [row for row in reflected['types'] if row.get('name') == token]
            assert type(match.get('classId')) is int, match
            classes[token] = match['classId']
        receipt['live_classes'] = classes
        actor_segments = ('Containers' if runtime.version == '2025.1' else 'Actor-Mixer Hierarchy', 'Default Work Unit')
        input_segments = ('Game Parameters', 'Default Work Unit')
        setup = _start_business_draft(gateway, 'object.set')
        actor = _bind_business_object(gateway, setup, path_segments=actor_segments)
        parameters = _bind_business_object(gateway, setup, path_segments=input_segments)
        sound_kind = _discover_business_type(gateway, setup, meaning='Sound', role='object', expected_label='Sound')
        input_kind = _discover_business_type(gateway, setup, meaning='GameParameter', role='object', expected_label='GameParameter')
        for declaration, parent, label, kind in [('owner', actor, name, sound_kind),
                ('input-a', parameters, name + '_A', input_kind), ('input-b', parameters, name + '_B', input_kind)]:
            _update_business_draft(gateway, setup, 'draft-declare-new', ['--declaration-id', declaration,
                '--parent-handle', parent, '--name', label, '--kind', kind, '--field', 'notes', 'Keep ' + declaration], live=False)
        setup_phase, setup_category = complete(setup, 'setup_no_credit', effect=False)
        def by_path(segments):
            row, = query([*(arg for segment in segments for arg in ('--path-segment', segment)), *projection], count=1)
            certified = exact(row['id'])
            assert certified == row, (row, certified)
            return certified
        owner = by_path((*actor_segments, name))['id']
        controls_by_id = {}
        for suffix in ('_A', '_B'):
            identity = by_path((*input_segments, name + suffix))['id']
            details = inventory(identity, ('Min', 'Max'))
            assert set(details) == {'Min', 'Max'}, details
            row = exact(identity, ('Min', 'Max'))
            minimum, maximum = row['properties']['Min'], row['properties']['Max']
            assert all(type(value) in (int, float) and math.isfinite(value) for value in (minimum, maximum)) and minimum < maximum, row
            assert row['type'] == 'GameParameter' and row['class_id'] == classes['GameParameter'], row
            controls_by_id[identity] = {'object': row, 'source_range': {'minimum': minimum, 'maximum': maximum}}
        receipt['controls'] = list(controls_by_id.values())
        a, b = controls_by_id
        field_details = inventory(owner, ('Volume', 'Pitch', 'CenterPercentage'))
        assert {'Volume', 'Pitch'}.issubset(field_details), field_details
        assert field_details['Volume']['metadata'].get('supports', {}).get('rtpc') in {'Additive', 'Multiplicative'}, field_details
        status = gateway.gateway(['status'], live=True)
        receipt['host_and_project'] = {'wwise': status.get('wwise'), 'project': status.get('project'), 'endpoint': status.get('endpoint')}
        platform = status.get('project', {}).get('currentPlatformId')
        assert isinstance(platform, str) and uuid.UUID(platform).int != 0, status
        def enabled(token, *, require_observation=False):
            code, payload = gateway.raw_gateway(['metadata', 'property-state', '--exact-id', owner,
                '--selection', field_details[token]['selection'], '--platform', platform])
            receipt.setdefault('enabled_observations', []).append({'field': token, 'exit_code': code, 'payload': payload})
            observed = payload.get('agent_result', {}).get('enabled')
            if require_observation:
                assert code == 0 and type(observed) is bool, payload
            return code == 0 and observed is True
        assert enabled('Volume'), 'Selected Volume is not observed enabled on the actual current platform'
        active = {token: enabled(token) for token in ('Pitch', 'CenterPercentage') if token in field_details
            and field_details[token]['metadata'].get('supports', {}).get('rtpc') in {'Additive', 'Multiplicative', 'Exclusive'}}
        candidates = [token for token in ('Pitch', 'CenterPercentage') if active.get(token)]
        assert candidates, 'No second legal source-backed RTPC field observed'
        second = next((token for token in candidates if field_details[token]['metadata']['supports']['rtpc'] == 'Exclusive'), candidates[0])
        exclusive_selected = field_details[second]['metadata']['supports']['rtpc'] == 'Exclusive'
        if exclusive_selected:
            receipt['exclusive'].update(status='active_selected', field=second, platform=platform,
                reason='Actual initially enabled Exclusive field selected; later scalar state is observation only',
                metadata=field_details[second]['metadata'])
        draft = _start_business_draft(gateway, 'object.set')
        target = _bind_business_object(gateway, draft, object_id=owner)
        lists = _update_business_draft(gateway, draft, 'draft-discover-fields', ['--object-handle', target,
            '--field-source', 'documented-lists', '--list'], live=True)['agent_result']
        selected_list, = [row for row in lists['items'] if row.get('name') == 'RTPC']
        assert selected_list.get('field_kind') == 'list' and selected_list.get('element_classes') == [
            {'name': 'RTPC', 'class_id': classes['RTPC']}], selected_list
        disclosed = _update_business_draft(gateway, draft, 'draft-discover-fields', ['--object-handle', target,
            '--field-source', 'documented-lists', '--selection', selected_list['selection']], live=True)
        receipt['documented_list'] = disclosed['meaning_results'][0]['candidates'][0]
        assert receipt['documented_list']['evidence']['kind'] == 'documented-list', disclosed
        initial = snapshot(owner)
        assert initial['members'] == [], initial
        setup_phase['independent_effect'] = {'owner': initial, 'controls': receipt['controls']}
        setup_category['status'] = 'PASS'
        wanted = [{'pair': ['Volume', a], 'points': points('Volume', a, 0.25), 'notes': 'Keep volume-a'},
            {'pair': [second, a], 'points': points(second, a, 0.25), 'notes': 'Keep second-a'}]
        for token, control, declaration in [('Volume', a, 'volume-a'), (second, a, 'second-a')]:
            declare(draft, target, token, control, points(token, control, 0.25), declaration)
        phase, phase_category = complete(draft, 'two_new_pairs')
        first = snapshot(owner); check_pairs(first, wanted)
        assert first['owner'] == initial['owner'], (initial, first)
        admit(phase, phase_category, first)
        draft = _start_business_draft(gateway, 'object.set')
        target = _bind_business_object(gateway, draft, object_id=owner)
        declare(draft, target, second, a, points(second, a, 0.5), 'second-a')
        declare(draft, target, 'Volume', b, points('Volume', b, 0.25), 'volume-b')
        if exclusive_selected:
            current = gateway.gateway(['status'], live=True)
            assert current.get('project', {}).get('currentPlatformId') == platform, current
            # isPropertyEnabled describes the base scalar's dependency state.
            # Updating this already observed RTPC's Curve is a distinct operation;
            # its metadata, pair, capacity and execution guards remain Gateway-owned.
            receipt['exclusive']['base_property_enabled_before_curve_update'] = enabled(
                second, require_observation=True)
        phase, phase_category = complete(draft, 'exact_update_and_append')
        expected_update = first['members'][1]['object']['id']
        native = phase['compiled_native_request']['args']['objects']
        assert any(row.get('object') == expected_update and '@Curve' in row for row in native), native
        wanted[1]['points'] = points(second, a, 0.5)
        wanted.append({'pair': ['Volume', b], 'points': points('Volume', b, 0.25), 'notes': 'Keep volume-b'})
        after = snapshot(owner); check_pairs(after, wanted)
        assert after['owner'] == first['owner'] and after['members'][0] == first['members'][0], (first, after)
        assert after['members'][1]['object']['id'] == expected_update, after
        admit(phase, phase_category, after)
        if exclusive_selected:
            rejected = _start_business_draft(gateway, 'object.set')
            target = _bind_business_object(gateway, rejected, object_id=owner)
            declare(rejected, target, second, b, points(second, b, 0.25), 'exclusive-conflict')
            code, payload = gateway.raw_gateway(['draft-check', rejected.draft_id, '--task-authority', rejected.task_authority,
                '--expected-revision', str(rejected.revision)])
            receipt['exclusive']['rejection'] = {'exit_code': code, 'payload': payload}
            assert code != 0 and payload.get('error_code') == 'RTPC_EXCLUSIVE_CONFLICT', payload
            assert snapshot(owner) == after
            receipt['exclusive']['status'] = 'observed_and_conflict_rejected'
        else:
            runtime.category_results.append({'category': 'rtpc-graph-exclusive-cardinality', 'status': 'blocked',
                'reason': receipt['exclusive']['reason'], 'observation_path': str(output),
                'verifier_strength': 'unobserved_exclusive_property_no_effect_credit'})
        nested_name = name + '_Nested'
        def planned(*, merge, value):
            draft = _start_business_draft(gateway, 'object.set')
            parent = _bind_business_object(gateway, draft, path_segments=actor_segments)
            kind = _discover_business_type(gateway, draft, meaning='Sound', role='object', expected_label='Sound')
            if merge: _update_business_draft(gateway, draft, 'draft-business-configure', ['--name-conflict', 'merge'], live=False)
            declared = _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', 'nested',
                '--parent-handle', parent, '--name', nested_name, '--kind', kind, '--field', 'notes', 'Keep nested'], live=False)
            target = declared['draft']['declared_object']['result_handle']
            declare(draft, target, 'Volume', a, points('Volume', a, value), 'nested-volume', kind=kind)
            return draft
        phase, phase_category = complete(planned(merge=False, value=0.25), 'planned_owner')
        assert phase['compiled_native_request']['args']['onNameConflict'] == 'fail', phase
        nested_id = by_path((*actor_segments, nested_name))['id']
        nested = snapshot(nested_id)
        check_pairs(nested, [{'pair': ['Volume', a], 'points': points('Volume', a, 0.25), 'notes': 'Keep nested-volume'}])
        admit(phase, phase_category, nested)
        phase, phase_category = complete(planned(merge=True, value=0.5), 'merged_planned_owner')
        assert phase['compiled_native_request']['args']['onNameConflict'] == 'merge', phase
        merged = snapshot(nested_id)
        check_pairs(merged, [{'pair': ['Volume', a], 'points': points('Volume', a, 0.5), 'notes': 'Keep nested-volume'}])
        assert merged['owner'] == nested['owner'] and merged['members'][0]['object']['id'] == nested['members'][0]['object']['id'], (nested, merged)
        assert any(row.get('object') == nested['members'][0]['object']['id'] for row in phase['compiled_native_request']['args']['objects']), phase
        admit(phase, phase_category, merged)
        assert snapshot(owner) == after
        draft = _start_business_draft(gateway, 'object.set')
        target = _bind_business_object(gateway, draft, object_id=owner)
        _update_business_draft(gateway, draft, 'draft-business-configure', ['--list-behavior', 'replace-all'], live=False)
        declare(draft, target, 'Volume', b, points('Volume', b, 0.5), 'replacement')
        declare(draft, target, second, a, points(second, a, 0.25), 'replacement-second')
        phase, phase_category = complete(draft, 'replace_all')
        assert phase['compiled_native_request']['args']['listMode'] == 'replaceAll', phase
        replaced = snapshot(owner)
        check_pairs(replaced, [{'pair': ['Volume', b], 'points': points('Volume', b, 0.5), 'notes': 'Keep replacement'},
            {'pair': [second, a], 'points': points(second, a, 0.25), 'notes': 'Keep replacement-second'}])
        assert replaced['owner'] == after['owner'] and snapshot(nested_id) == merged, (after, replaced)
        old_ids = [row['object']['id'] for row in after['members']]
        assert not set(row['object']['id'] for row in replaced['members']).intersection(old_ids), replaced
        for identity in old_ids: assert query(['--exact-id', identity], count=0) == []
        phase['removed_member_ids'] = old_ids
        admit(phase, phase_category, replaced)
        receipt['business_effect_verified'] = True
        receipt['complete'] = True
        category['status'] = 'PASS'
        return category
    except Exception as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        completed_status = category['status']
        category['status'] = 'FAIL'
        persist()
        category['status'] = completed_status


@pytest.mark.live
@pytest.mark.destructive
def test_rtpc_graph_acceptance_across_selected_version(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    if workflow_sandbox_runtime.version == '2021.1':
        pytest.skip('2021 RTPC construction remains separate; no modern object.set is fabricated')
    category = _collect_rtpc_graph_acceptance(workflow_sandbox_runtime, name='WAAPI_RTPC_' + uuid.uuid4().hex[:12])
    assert category['status'] == 'PASS', category


def _collect_anonymous_effect_slot_construction_acceptance(runtime: _WorkflowSandboxRuntime, *, prefix: str,
        render_suffix_diagnostic: bool = False) -> dict[str, Any]:
    """Three modern new-List effects inside the existing owned workflow lifecycle."""
    output = runtime.state_dir / ('effect-render-suffix-observation.json' if render_suffix_diagnostic else 'anonymous-effect-slot-construction-acceptance.json')
    category = {'category': 'effect-render-suffix-observation' if render_suffix_diagnostic else 'anonymous-effect-slot-construction', 'status': 'FAIL',
        'verifier_strength': 'gateway_verified_plus_independent_complete_ordered_membership_exact_guid_class_owner_reference_fields_and_preservation',
        'observation_path': str(output)}
    if render_suffix_diagnostic:
        category.update(diagnostic_only=True, business_effect_verified=False,
            verifier_strength='diagnostic_stored_Render_suffix_and_complete_preservation_observation_no_business_credit')
    runtime.category_results.append(category)
    receipt = {'candidate': runtime.candidate, 'version': runtime.version, 'calls': [], 'transactions': [],
        'setup_coverage_credit': False, 'business_effect_verified': False,
        'scope': 'stored_Render_suffix_observation_not_business_acceptance' if render_suffix_diagnostic else 'new_anonymous_EffectSlot_construction_not_existing_member_name_merge',
        'lifecycle_acceptance': 'existing host-category-evidence/v3 finalizer owns source/cleanup acceptance'}
    if render_suffix_diagnostic: receipt.update(diagnostic_complete=False, classification='not_observed')
    def persist():
        body = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 8 * 1024 * 1024, 'Anonymous EffectSlot receipt byte bound exceeded'
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(body); temporary.replace(output)
        if render_suffix_diagnostic: category['observation_sha256'] = hashlib.sha256(body).hexdigest()
    class ReceiptGateway:
        def raw_gateway(self, argv):
            assert len(receipt['calls']) < 256, 'Anonymous EffectSlot public call bound exceeded'
            row = {'argv': list(argv)}; receipt['calls'].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                row.update(exit_code=code, payload=payload)
                return code, payload
            except Exception as exc:
                row['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
                raise
            finally:
                persist()
        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            if live:
                assert payload.get('endpoint') == {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url}, payload
                assert payload.get('detected_version') == runtime.version, payload
            return payload
    gateway = ReceiptGateway()
    projection = ['--include', 'class-id', '--include', 'owner', '--include', 'parent', '--include', 'notes']
    def query(argv, *, count=None):
        result = gateway.gateway(['query-object', *argv, *projection], live=True)
        rows = result.get('objects')
        assert isinstance(rows, list) and len(rows) <= 8, result
        assert result.get('projection_complete') is not False and result.get('limit_reached') is not True and result.get('status') != 'partial', result
        assert result.get('count') == len(rows) and len({row['id'] for row in rows}) == len(rows), result
        if count is not None: assert len(rows) == count, result
        for row in rows:
            assert uuid.UUID(row['id']).int != 0 and isinstance(row.get('path'), str), row
        return rows
    def exact(identity, fields=()):
        row = query(['--exact-id', identity, *(arg for name in fields for arg in ('--include-field', name))], count=1)[0]
        assert row['id'] == identity and type(row.get('class_id')) is int, row
        return row
    def at(segments):
        return query([*(arg for segment in segments for arg in ('--path-segment', segment))], count=1)[0]
    def members(owner):
        return query(['--advanced-waql', f'from object "{owner}" select @Effects', '--max-results', '8'])
    def children(owner):
        return query(['--advanced-waql', f'from object "{owner}" select children', '--max-results', '8'])
    def guid(value, *, nullable=False):
        identity = value.get('id') if isinstance(value, Mapping) else value
        if nullable and (identity is None or (isinstance(identity, str) and uuid.UUID(identity).int == 0)):
            return None
        assert isinstance(identity, str) and uuid.UUID(identity).int != 0, value
        return identity
    def gain_fields(identity):
        names, page = [], None
        for _ in range(4):
            result = gateway.gateway(['metadata', 'list', '--exact-id', identity, '--page-size', '64',
                *(['--page', page] if page is not None else [])], live=True)['agent_result']
            for field in result['fields']:
                name = field['name']
                assert isinstance(name, str) and name not in names, result
                names.append(name)
            if result['complete'] is True:
                assert len(names) == result['total_count'] and len(names) <= 8, result
                return names
            next_page = _required_string(result, 'next_page')
            assert next_page != page, result
            page = next_page
        raise AssertionError('Gain metadata exceeds four pages')
    def gain(identity, *, parent=None, owner=None):
        names = gain_fields(identity)
        row = exact(identity, names)
        assert row['type'] == 'Effect' and row['class_id'] == classes['Wwise Gain'], row
        if parent is not None:
            assert guid(row.get('parent')) == parent, row
            if 'owner' in row: assert guid(row['owner'], nullable=True) is None, row
            else: assert 'owner' in row.get('unavailable_fields', []), row
        else:
            assert guid(row.get('owner')) == owner, row
            assert 'parent' not in row and 'parent' in row.get('unavailable_fields', []), row
        return row
    def selected_fields(draft, kind):
        listed = _update_business_draft(gateway, draft, 'draft-discover-fields', ['--type-handle', kind, '--list'], live=True)['agent_result']
        selected = {}
        for name in ('Effect', 'Bypass', 'Render'):
            rows = [row for row in listed['fields'] if row.get('name') == name]
            assert len(rows) == 1, (name, listed)
            result = _update_business_draft(gateway, draft, 'draft-discover-fields',
                ['--type-handle', kind, '--selection', rows[0]['selection']], live=True)
            selected[name] = discovered_business_field_handle(result, name)
        return selected
    def list_field(draft, owner, *, planned=False):
        scope = ['--type-handle' if planned else '--object-handle', owner]
        listed = _update_business_draft(gateway, draft, 'draft-discover-fields',
            [*scope, '--field-source', 'documented-lists', '--list'], live=True)['agent_result']
        matches = [row for row in listed['items'] if row['name'] == 'Effects']
        assert len(matches) == 1, listed
        result = _update_business_draft(gateway, draft, 'draft-discover-fields',
            [*scope, '--field-source', 'documented-lists', '--selection', matches[0]['selection']], live=True)
        return result['meaning_results'][0]['candidates'][0]['handle']
    def declare_slots(draft, owner, effects, kind, fields, targets):
        handles = []
        for index, target in enumerate(targets):
            values = ['--field-value', fields['Bypass'], 'false' if render_suffix_diagnostic or index == 0 else 'true',
                '--field-value', fields['Render'], 'true' if render_suffix_diagnostic or index == 0 else 'false']
            if target is not None: values += ['--field-value', fields['Effect'], target]
            declared = _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', f'slot{index}',
                '--parent-handle', owner, '--kind', kind, '--field', 'object_list', effects, *values], live=False)
            handles.append(_required_string(declared['draft']['declared_object'], 'result_handle'))
        return handles
    def complete(draft, label, *, setup=False):
        phase = {'phase': label, 'setup_no_credit': setup, 'native_outcome': 'not_executed', 'effect_verified': False}
        receipt['transactions'].append(phase)
        _update_business_draft(gateway, draft, 'draft-check', live=True)
        preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
        identity = _required_string(preview, 'transaction_id')
        shown = gateway.gateway(['transaction-show', identity], live=False)
        phase.update(transaction_id=identity, artifact_hash=preview['artifact_hash'],
            compiled_native_request=shown['artifact']['prepared_operation']['dispatch'])
        gateway.gateway(['confirm', identity, '--confirmation-token', shown['confirmation']['token']], live=False)
        phase['native_outcome'] = 'indeterminate'
        code, executed = gateway.raw_gateway(['execute', identity]); phase['execute'] = {'exit_code': code, 'payload': executed}
        assert code == 0 and executed.get('state') == 'executed_unverified' and executed.get('automatic_retry') is False, executed
        phase['native_outcome'] = 'accepted'
        code, verified = gateway.raw_gateway(['verify', identity]); phase['verify'] = {'exit_code': code, 'payload': verified}
        assert code == 0 and verified.get('verified') is True and verified.get('state') == 'verified', verified
        assert verified.get('verification', {}).get('business_state_verified') is True, verified
        return phase
    def slot_snapshot(owner, expected_targets, *, old=(), observing_suffix=False, field_names=None):
        sound = exact(owner)
        assert sound['type'] == 'Sound' and sound['class_id'] == classes['Sound'], sound
        listed = members(owner)
        assert len(listed) == len(old) + len(expected_targets), listed
        assert [row['id'] for row in listed[:len(old)]] == list(old), listed
        fresh = listed[len(old):]
        assert not set(row['id'] for row in fresh).intersection(old), listed
        slots = []
        for index, candidate in enumerate(fresh):
            names = field_names[candidate['id']] if field_names is not None else ('Effect', 'Bypass', 'Render')
            row = exact(candidate['id'], names)
            if field_names is not None:
                observed = set(row.get('properties', {})) | set(row.get('references', {}))
                assert set(names) <= observed, (names, row)
            assert row['name'] == '' and row['type'] == 'EffectSlot' and row['class_id'] == classes['EffectSlot'], row
            assert guid(row.get('owner')) == owner, row
            assert 'parent' not in row and 'parent' in row.get('unavailable_fields', []), row
            assert guid(row.get('references', {}).get('Effect')) == expected_targets[index], row
            assert row.get('properties', {}).get('Bypass') is (index != 0 and not render_suffix_diagnostic), row
            assert type(row.get('properties', {}).get('Render')) is bool, row
            if not observing_suffix:
                assert row['properties']['Render'] is (render_suffix_diagnostic or index == 0), row
            slots.append(row)
        return {'owner': sound, 'slots': slots, 'ordered_ids': [row['id'] for row in listed]}
    def preserved(*, new_child=None):
        actual = {'folder': exact(folder['id']), 'targets': [gain(row['id'], parent=folder['id']) for row in targets],
            'owner': exact(sound['id']), 'parents': {key: exact(row['id']) for key, row in parents.items()}}
        assert actual == preserved_before, (preserved_before, actual)
        actual_children = children(folder['id'])
        by_id = {row['id']: row for row in actual_children}
        assert all(by_id.get(row['id']) == row for row in before_children), (before_children, actual_children)
        assert set(by_id) - {row['id'] for row in before_children} == ({new_child} if new_child else set()), actual_children
        return {**actual, 'children': actual_children}
    def suffix_metadata(identity):
        names, selected, page = [], [], None
        for _ in range(4):
            result = gateway.gateway(['metadata', 'list', '--exact-id', identity, '--page-size', '64',
                *(['--page', page] if page else [])], live=True)['agent_result']
            for field in result['fields']:
                name = field.get('name')
                assert isinstance(name, str) and name not in names, result
                names.append(name)
                selected.append((name, field['selection']))
            if result.get('complete') is True:
                assert len(names) == result['total_count'] and len(names) <= 8, result
                break
            next_page = _required_string(result, 'next_page'); assert next_page != page, result
            page = next_page
        else: raise AssertionError('Suffix metadata exceeds four pages')
        assert {'Effect', 'Bypass', 'Render'} <= set(names), names
        details = {}
        for name, selection in selected:
            result = gateway.gateway(['metadata', 'detail', '--exact-id', identity, '--selection', selection], live=True)['agent_result']
            assert result.get('complete') is True, result
            facts = result.get('metadata', result.get('entries'))
            assert isinstance(facts, (dict, list)), result
            details[name] = facts
        return {'names': names, 'details': details}
    def observe_suffix():
        assert runtime.version in {'2023.1', '2024.1', '2025.1'}, 'Modern suffix diagnostic excludes legacy EffectN lanes'
        target_ids = [row['id'] for row in targets]
        listed = members(sound['id'])
        assert len(listed) == 2 and len({row['id'] for row in listed}) == 2, listed
        metadata = {row['id']: suffix_metadata(row['id']) for row in listed}
        receipt['suffix_metadata_before'] = metadata
        field_names = {identity: proof['names'] for identity, proof in metadata.items()}
        before = slot_snapshot(sound['id'], target_ids, field_names=field_names)
        assert before['ordered_ids'] == [row['id'] for row in listed], (listed, before)
        receipt['suffix_before'] = before
        draft = _start_business_draft(gateway, 'object.setProperty')
        first_id = before['ordered_ids'][0]
        bound = _bind_business_object(gateway, draft, object_id=first_id)
        listed = _update_business_draft(gateway, draft, 'draft-discover-fields',
            ['--object-handle', bound, '--list'], live=True)['agent_result']
        selected = [row for row in listed['fields'] if row.get('name') == 'Render']
        assert len(selected) == 1, listed
        field = _update_business_draft(gateway, draft, 'draft-discover-fields',
            ['--object-handle', bound, '--selection', selected[0]['selection']], live=True)
        receipt['clear_selected_field'] = field
        handle = discovered_business_field_handle(field, 'Render')
        _update_business_draft(gateway, draft, 'draft-declare-field-change',
            ['--object-handle', bound, '--field-handle', handle, '--business-value', 'false'], live=False)
        _update_business_draft(gateway, draft, 'draft-check', live=True)
        preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
        identity = _required_string(preview, 'transaction_id')
        shown = gateway.gateway(['transaction-show', identity], live=False)
        phase = {'phase': 'observe_clear_first_Render_once', 'diagnostic_only': True,
            'transaction_id': identity, 'artifact_hash': preview['artifact_hash'],
            'compiled_native_request': shown['artifact']['prepared_operation']['dispatch'],
            'native_outcome': 'not_executed', 'effect_verified': False}
        receipt['transactions'].append(phase)
        assert phase['compiled_native_request']['uri'] == 'ak.wwise.core.object.setProperty'
        assert phase['compiled_native_request']['args'] == {'object': first_id, 'property': 'Render', 'value': False}
        gateway.gateway(['confirm', identity, '--confirmation-token', shown['confirmation']['token']], live=False)
        phase['native_outcome'] = 'indeterminate'
        code, executed = gateway.raw_gateway(['execute', identity]); phase['execute'] = {'exit_code': code, 'payload': executed}
        if code != 0 or executed.get('ok') is not True:
            phase['native_outcome'] = 'rejected' if executed.get('state') == 'execution_failed' else 'indeterminate'
            phase['original_durable_state'] = executed.get('state')
            native = executed.get('dispatch_result', {})
            explicit_error_response = (isinstance(native, Mapping) and native.get('api') == 'ak.wwise.core.object.setProperty'
                and native.get('version') == runtime.version and native.get('ok') is False
                and native.get('waapi_error_uri') == 'ak.wwise.invalid_arguments')
            # An explicit native error response is an observed fact even though
            # e2 conservatively journals a failed named write as indeterminate.
            # Neither classification establishes a no-mutation/effect outcome.
            phase['native_response_class'] = 'explicit_invalid_arguments' if explicit_error_response else 'unresolved_failure'
            receipt['classification'] = 'native_error_response' if explicit_error_response else 'indeterminate'
            receipt['diagnostic_complete'] = explicit_error_response
            phase['effects_unknown'] = receipt['effects_unknown'] = True
            phase['native_error_code'] = native.get('waapi_error_uri', native.get('error_code'))
            category.update(status='blocked' if receipt['diagnostic_complete'] else 'FAIL',
                classification=receipt['classification'], diagnostic_complete=receipt['diagnostic_complete'],
                reason='Original execution failure retained; no verify, read-after or retry; no business credit')
            return category
        assert executed.get('state') == 'executed_unverified' and executed.get('automatic_retry') is False, executed
        phase['native_outcome'] = 'accepted'
        code, verified = gateway.raw_gateway(['verify', identity]); phase['verify'] = {'exit_code': code, 'payload': verified}
        assert code == 0 and verified.get('state') == 'verified' and verified.get('verified') is True, verified
        # The e2 single-field verifier says nothing about the later flag. Its
        # original result is retained, while this independent oracle checks it.
        after = slot_snapshot(sound['id'], target_ids, observing_suffix=True, field_names=field_names)
        receipt['suffix_after'] = after
        assert after['ordered_ids'] == before['ordered_ids'] and after['owner'] == before['owner'], (before, after)
        assert after['slots'][0]['properties']['Render'] is False, after
        for old, actual in zip(before['slots'], after['slots'], strict=True):
            expected = json.loads(json.dumps(old))
            expected['properties']['Render'] = actual['properties']['Render']
            assert actual == expected, (old, actual)  # only the two Render booleans may differ
        actual_metadata = {row['id']: suffix_metadata(row['id']) for row in after['slots']}
        receipt['suffix_metadata_after'] = actual_metadata
        assert actual_metadata == metadata, (metadata, actual_metadata)
        receipt['preserved_after'] = preserved()
        receipt['classification'] = 'retained' if after['slots'][1]['properties']['Render'] else 'cleared'
        receipt['diagnostic_complete'] = True
        category.update(status='blocked', diagnostic_complete=True, classification=receipt['classification'],
            reason='Complete stored suffix diagnostic only; test PASS grants no business/route/native-absence credit')
        return category
    try:
        assert runtime.version in {'2023.1', '2024.1', '2025.1'}, 'Anonymous modern List witness gives no2021/22 credit'
        gateway.gateway(['query-schema', '--advanced'], live=False)
        result = gateway.gateway(['metadata', 'types', '--meaning', 'Sound', '--meaning', 'Folder', '--meaning', 'WorkUnit',
            '--meaning', 'EffectSlot', '--meaning', 'Wwise Gain', '--page-size', '64'], live=True)['agent_result']
        assert result.get('complete') is True, result
        classes = {}
        for name in ('Sound', 'Folder', 'WorkUnit', 'EffectSlot', 'Wwise Gain'):
            matches = [row for row in result['types'] if row.get('name') == name]
            assert len(matches) == 1 and type(matches[0].get('classId')) is int, (name, result)
            classes[name] = matches[0]['classId']
        receipt['live_classes'] = classes
        sound_segments = ('Containers' if runtime.version == '2025.1' else 'Actor-Mixer Hierarchy', 'Default Work Unit')
        effect_segments = ('Effects', 'Default Work Unit')
        parents = {'effects': at(effect_segments), 'sound': at(sound_segments)}
        assert all(row['type'] == 'WorkUnit' and row['class_id'] == classes['WorkUnit'] for row in parents.values()), parents
        # Already-supported multi-root graph; Folder and Sound are independent
        # setup only, and each actual identity/class/parent is reread below.
        draft = _start_business_draft(gateway, 'object.set')
        for label, segments, name, kind_name in [('folder', effect_segments, prefix + '_Folder', 'Folder'),
                ('sound', sound_segments, prefix + '_Sound', 'Sound')]:
            parent = _bind_business_object(gateway, draft, path_segments=segments)
            kind = _discover_business_type(gateway, draft, meaning=kind_name, role='object', expected_label=kind_name)
            _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', label, '--parent-handle', parent,
                '--name', name, '--kind', kind, '--field', 'notes', 'Keep ' + label], live=False)
        complete(draft, 'setup_folder_and_sound_no_credit', setup=True)
        folder = at((*effect_segments, prefix + '_Folder')); sound = at((*sound_segments, prefix + '_Sound'))
        folder = exact(folder['id']); sound = exact(sound['id'])
        assert folder['type'] == 'Folder' and folder['class_id'] == classes['Folder'] and guid(folder.get('parent')) == parents['effects']['id'], folder
        assert sound['type'] == 'Sound' and sound['class_id'] == classes['Sound'] and guid(sound.get('parent')) == parents['sound']['id'], sound
        assert members(sound['id']) == []
        targets = []
        for index in range(2):
            draft = _start_business_draft(gateway, 'object.createPlugin')
            parent = _bind_business_object(gateway, draft, object_id=folder['id'])
            plugin = _discover_business_type(gateway, draft, meaning='Wwise Gain', role='effect', expected_label='Wwise Gain')
            _update_business_draft(gateway, draft, 'draft-declare-existing', ['--declaration-id', 'gain', '--object-handle', parent,
                '--field', 'plugin_role', 'effect', '--field', 'plugin_placement', 'shareset', '--field', 'plugin_name', prefix + f'_Gain{index}',
                '--field', 'plugin_type_handle', plugin, '--field', 'notes', 'Keep target' + str(index)], live=False)
            complete(draft, f'setup_shareset_{index}_no_credit', setup=True)
            target = at((*effect_segments, prefix + '_Folder', prefix + f'_Gain{index}'))
            targets.append(gain(target['id'], parent=folder['id']))
        preserved_before = {'folder': folder, 'targets': targets, 'owner': sound, 'parents': parents}
        before_children = children(folder['id'])
        assert {row['id'] for row in before_children} == {row['id'] for row in targets}, before_children
        receipt['baseline'] = {**preserved_before, 'children': before_children}
        previous = []
        for mode, target_order in [('append', targets), ('replace-all', list(reversed(targets)))]:
            draft = _start_business_draft(gateway, 'object.set')
            owner = _bind_business_object(gateway, draft, object_id=sound['id'])
            kind = _discover_business_type(gateway, draft, meaning='EffectSlot', role='object', expected_label='EffectSlot')
            fields = selected_fields(draft, kind); effects = list_field(draft, owner)
            handles = [_bind_business_object(gateway, draft, object_id=row['id']) for row in target_order]
            declare_slots(draft, owner, effects, kind, fields, handles)
            if mode == 'replace-all': _update_business_draft(gateway, draft, 'draft-business-configure', ['--list-behavior', mode], live=False)
            phase = complete(draft, 'setup_rendered_chain_no_credit' if render_suffix_diagnostic else 'append_existing_sharesets' if mode == 'append' else 'replace_all_population',
                setup=render_suffix_diagnostic)
            if render_suffix_diagnostic:
                return observe_suffix()
            observed = slot_snapshot(sound['id'], [row['id'] for row in target_order])
            assert observed['owner'] == sound, (sound, observed)
            assert not set(observed['ordered_ids']).intersection(previous), observed
            for removed in previous: assert query(['--exact-id', removed], count=0) == []
            phase['independent_effect'] = {'members': observed, 'preserved': preserved()}
            phase['effect_verified'] = True
            previous = observed['ordered_ids']
            last_snapshot = observed
        draft = _start_business_draft(gateway, 'object.set')
        folder_handle = _bind_business_object(gateway, draft, object_id=folder['id'])
        plugin = _discover_business_type(gateway, draft, meaning='Wwise Gain', role='effect', expected_label='Wwise Gain')
        declared = _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', 'new-share', '--parent-handle', folder_handle,
            '--name', prefix + '_NewShare', '--kind', plugin, '--field', 'plugin_placement', 'shareset', '--field', 'notes', 'Keep new ShareSet'], live=False)
        shared = _required_string(declared['draft']['declared_object'], 'result_handle')
        parent = _bind_business_object(gateway, draft, path_segments=sound_segments)
        sound_kind = _discover_business_type(gateway, draft, meaning='Sound', role='object', expected_label='Sound')
        declared = _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', 'new-sound', '--parent-handle', parent,
            '--name', prefix + '_PlannedSound', '--kind', sound_kind, '--field', 'notes', 'Keep planned Sound'], live=False)
        planned_owner = _required_string(declared['draft']['declared_object'], 'result_handle')
        kind = _discover_business_type(gateway, draft, meaning='EffectSlot', role='object', expected_label='EffectSlot')
        handles = declare_slots(draft, planned_owner, list_field(draft, sound_kind, planned=True), kind,
            selected_fields(draft, kind), [shared, None])
        _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', 'local', '--parent-handle', handles[1],
            '--name', prefix + '_LocalGain', '--kind', plugin, '--field', 'plugin_placement', 'owner', '--field', 'notes', 'Keep local Effect'], live=False)
        phase = complete(draft, 'planned_owner_shareset_and_inline_effect')
        planned = at((*sound_segments, prefix + '_PlannedSound'))
        new_share = gain(at((*effect_segments, prefix + '_Folder', prefix + '_NewShare'))['id'], parent=folder['id'])
        listed = members(planned['id']); assert len(listed) == 2, listed
        # Slot GUIDs come only from ordered membership; the owning relationship
        # independently identifies the inline Effect, never matching postvalues.
        local_slot = exact(listed[1]['id'], ('Effect',))
        local = gain(guid(local_slot.get('references', {}).get('Effect')), owner=local_slot['id'])
        observed = slot_snapshot(planned['id'], [new_share['id'], local['id']])
        assert observed['owner']['name'] == prefix + '_PlannedSound' and observed['owner']['notes'] == 'Keep planned Sound', observed
        assert guid(observed['owner'].get('parent')) == parents['sound']['id'], observed
        assert new_share['notes'] == 'Keep new ShareSet' and local['notes'] == 'Keep local Effect', (new_share, local)
        assert len({row['id'] for row in [planned, new_share, local, *observed['slots']]}) == 5, observed
        retained = slot_snapshot(sound['id'], [row['id'] for row in reversed(targets)])
        assert retained == last_snapshot, (last_snapshot, retained)
        phase['independent_effect'] = {'members': observed, 'new_share': new_share, 'local_effect': local,
            'preserved': preserved(new_child=new_share['id']), 'retained_previous_owner': retained}
        phase['effect_verified'] = True
        receipt['business_effect_verified'] = True; category['status'] = 'PASS'
        return category
    except Exception as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        persist()


@pytest.mark.live
@pytest.mark.destructive
def test_anonymous_effect_slot_construction_acceptance(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    if workflow_sandbox_runtime.version not in {'2023.1', '2024.1', '2025.1'}:
        pytest.skip('Modern anonymous Effects List constructor witness excludes legacy EffectN lanes')
    category = _collect_anonymous_effect_slot_construction_acceptance(workflow_sandbox_runtime,
        prefix='WAAPI_ANON_' + uuid.uuid4().hex[:10])
    assert category['status'] == 'PASS', category


def _collect_voice_creation_acceptance(runtime: _WorkflowSandboxRuntime, *, prefix: str) -> dict[str, Any]:
    """Empty Voice identity effects in the existing owned host lifecycle."""
    output = runtime.state_dir / 'voice-creation-acceptance.json'
    category = {'category': 'sound-voice-creation', 'status': 'FAIL',
        'verifier_strength': 'gateway_verified_plus_independent_exact_guid_class_parent_name_notes_volume_and_actual_boolean_voice',
        'observation_path': str(output)}
    runtime.category_results.append(category)
    receipt = {'candidate': runtime.candidate, 'version': runtime.version, 'calls': [], 'transactions': [],
        'business_effect_verified': False, 'scope': 'empty_Voice_containers_no_localized_media_or_Source_effect_claim',
        'applicable_effects': ['ordinary_root_voice', 'ordinary_nested_voice',
            *(['graph_empty_voice'] if runtime.version != '2021.1' else [])],
        'lifecycle_acceptance': 'Requires final host-category-evidence/v3 source-integrity and cleanup acceptance'}
    def persist():
        body = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 4 * 1024 * 1024, 'Voice receipt byte bound exceeded'
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(body); temporary.replace(output)
        category['observation_sha256'] = hashlib.sha256(body).hexdigest()
    class ReceiptGateway:
        def raw_gateway(self, argv):
            assert len(receipt['calls']) < 96, 'Voice public call bound exceeded'
            row = {'argv': list(argv)}; receipt['calls'].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                row.update(exit_code=code, payload=payload)
                return code, payload
            except Exception as exc:
                row['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
                raise
            finally:
                persist()
        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            if live:
                assert payload.get('endpoint') == {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url}, payload
                assert payload.get('detected_version') == runtime.version, payload
            return payload
    gateway = ReceiptGateway()
    projection = ['--include', 'class-id', '--include', 'parent', '--include', 'notes']
    def one(argv):
        payload = gateway.gateway(['query-object', *argv, *projection], live=True)
        rows = payload.get('objects')
        assert payload.get('count') == 1 and isinstance(rows, list) and len(rows) == 1, payload
        assert payload.get('projection_complete') is not False and payload.get('limit_reached') is not True and payload.get('status') != 'partial', payload
        row = rows[0]
        assert uuid.UUID(_required_string(row, 'id')).int != 0 and type(row.get('class_id')) is int, row
        return row
    def exact(identity, *, voice=False):
        row = one(['--exact-id', identity, *(['--include-field', 'IsVoice', '--include-field', 'Volume'] if voice else [])])
        assert row['id'] == identity, row
        return row
    def at(segments, *, voice=False):
        found = one([*(arg for segment in segments for arg in ('--path-segment', segment))])
        row = exact(found['id'], voice=voice)
        assert all(row.get(key) == found.get(key) for key in ('id', 'name', 'type', 'path')), (found, row)
        return row
    def parent_id(row):
        reference = row.get('parent')
        assert isinstance(reference, Mapping) and uuid.UUID(_required_string(reference, 'id')).int != 0, row
        return reference['id']
    def complete(draft, phase):
        _update_business_draft(gateway, draft, 'draft-check', live=True)
        preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
        identity = _required_string(preview, 'transaction_id')
        shown = gateway.gateway(['transaction-show', identity], live=False)
        phase.update(transaction_id=identity, artifact_hash=preview['artifact_hash'],
            compiled_native_request=shown['artifact']['prepared_operation']['dispatch'])
        gateway.gateway(['confirm', identity, '--confirmation-token', shown['confirmation']['token']], live=False)
        phase['native_outcome'] = 'indeterminate'
        code, executed = gateway.raw_gateway(['execute', identity]); phase['execute'] = {'exit_code': code, 'payload': executed}
        assert code == 0 and executed.get('state') == 'executed_unverified' and executed.get('automatic_retry') is False, executed
        phase['native_outcome'] = 'accepted'
        code, verified = gateway.raw_gateway(['verify', identity]); phase['verify'] = {'exit_code': code, 'payload': verified}
        assert code == 0 and verified.get('state') == 'verified' and verified.get('verified') is True, verified
        assert verified.get('verification', {}).get('business_state_verified') is True, verified
    try:
        container_type = 'PropertyContainer' if runtime.version == '2025.1' else 'ActorMixer'
        disclosed = gateway.gateway(['metadata', 'types', '--meaning', 'Sound', '--meaning', container_type,
            '--meaning', 'WorkUnit', '--page-size', '64'], live=True)['agent_result']
        assert disclosed.get('complete') is True, disclosed
        classes = {}
        for name in ('Sound', container_type, 'WorkUnit'):
            matches = [row for row in disclosed['types'] if row.get('name') == name and row.get('type') == 'WObject']
            assert len(matches) == 1 and type(matches[0].get('classId')) is int, (name, disclosed)
            classes[name] = matches[0]['classId']
        assert classes['Sound'] == 65552, classes  # All five pinned Sound class pages.
        receipt['live_classes'] = classes
        segments = ('Containers' if runtime.version == '2025.1' else 'Actor-Mixer Hierarchy', 'Default Work Unit')
        parent = at(segments)
        assert parent['type'] == 'WorkUnit' and parent['class_id'] == classes['WorkUnit'], parent
        receipt['parent_before'] = parent
        observed_ids = set()
        for index, label in enumerate(receipt['applicable_effects']):
            nested = label == 'ordinary_nested_voice'
            operation = 'object.set' if label == 'graph_empty_voice' else 'object.create'
            name = 'NestedVoice' if nested else prefix + ('_GraphVoice' if operation == 'object.set' else '_RootVoice')
            volume, notes = -6 - index, 'Keep ' + label
            expected = {'name': name, 'volume': volume, 'notes': notes, 'parent_id': parent['id']}
            phase = {'phase': label, 'operation': operation, 'expected': expected,
                'native_outcome': 'not_executed', 'effect_verified': False}
            receipt['transactions'].append(phase)
            draft = _start_business_draft(gateway, operation)
            handle = _bind_business_object(gateway, draft, object_id=parent['id'])
            voice_segments = segments
            if nested:
                declared = _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', 'container',
                    '--parent-handle', handle, '--kind', 'actor-mixer', '--name', prefix + '_Container',
                    '--field', 'notes', 'Keep Voice container'], live=False)
                handle = declared_business_object_handle(declared, 'container')
                voice_segments = (*segments, prefix + '_Container')
            _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', 'voice', '--parent-handle', handle,
                '--kind', 'sound-voice', '--name', name, '--field', 'notes', notes, '--field', 'volume_db', str(volume)], live=False)
            complete(draft, phase)
            if nested:
                container = at(voice_segments)
                phase['independent_container'] = container
                assert container['type'] == container_type and container['class_id'] == classes[container_type], container
                assert parent_id(container) == parent['id'] and container['notes'] == 'Keep Voice container', container
                assert container['id'] not in observed_ids and container['id'] != parent['id'], container
                observed_ids.add(container['id']); expected['parent_id'] = container['id']
            voice = at((*voice_segments, name), voice=True)
            phase['independent_voice'] = voice
            assert voice['type'] == 'Sound' and voice['class_id'] == classes['Sound'], voice
            assert voice['id'] not in observed_ids and voice['id'] != parent['id'], voice
            assert parent_id(voice) == expected['parent_id'] and voice['name'] == name and voice['notes'] == notes, voice
            assert voice.get('properties', {}).get('IsVoice') is True, voice
            actual_volume = voice.get('properties', {}).get('Volume')
            assert type(actual_volume) in (int, float) and actual_volume == volume, voice
            observed_ids.add(voice['id'])
            assert exact(parent['id']) == parent, parent
            phase['effect_verified'] = True
        receipt['business_effect_verified'] = True; category['status'] = 'PASS'
        return category
    except Exception as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        persist()


@pytest.mark.live
@pytest.mark.destructive
def test_sound_voice_creation_acceptance(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    category = _collect_voice_creation_acceptance(workflow_sandbox_runtime, prefix='WAAPI_VOICE_' + uuid.uuid4().hex[:10])
    assert category['status'] == 'PASS', category



def _collect_planned_source_characterization(runtime: _WorkflowSandboxRuntime, *, prefix: str,
        staged_voice_source_language: bool = False) -> dict[str, Any]:
    """Atomic creation cases or one explicitly selected staged diagnostic."""
    from wwise_waapi.native_catalog import load_native_catalog
    assert runtime.version in {'2022.1', '2023.1', '2024.1', '2025.1'}
    catalog = load_native_catalog(runtime.version, 'wwise-console')
    endpoint = {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url}
    output = runtime.state_dir / ('staged-voice-source-language.json' if staged_voice_source_language else 'planned-source-characterization.json')
    assert not output.exists(), 'Never overwrite original Source evidence'
    output.parent.mkdir(parents=True, exist_ok=True)
    artifacts = runtime.state_dir / ('staged-voice-source-artifacts' if staged_voice_source_language else 'planned-source-artifacts'); artifacts.mkdir(exist_ok=False)
    native_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    previous_native = set(native_root.glob('*.json'))
    config = Path(runtime.env['WAAPI_SKILL_CONFIG_PATH'])
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    transactions: list[str] = []
    category = {'category': 'planned-source-construction', 'status': 'FAIL', 'transaction_ids': transactions,
        'observation_path': str(output), 'scope': 'three_exact_creation_cases_on_matching_Console_version',
        'verifier_strength': 'Gateway_verification_plus_exact_GUID_class_parent_fields_language_childset_and_retained_state'}
    if staged_voice_source_language:
        category.update(category='staged-voice-source-language', scope='staged_existing_Voice_Source_language',
            diagnostic_only=True, atomic_Source_language_unresolved=True)
    runtime.category_results.append(category)
    receipt: dict[str, Any] = {'contract': 'waapi-skill.planned-source-characterization/v1',
        'candidate': runtime.candidate, 'version': runtime.version, 'calls': [], 'phases': [], 'native_evidence': [],
        'collection_complete': False, 'business_effect_verified': False, 'config_sha256': config_hash,
        'native_catalog': {'build': catalog['provenance']['build'], 'content_sha256': catalog['content_sha256']},
        'source_project': str(runtime.sandbox.source_project), 'endpoint': endpoint,
        'lifecycle_final_reference': {'contract': 'waapi-skill.host-category-evidence/v3', 'phase': 'final',
            'candidate': runtime.candidate, 'category': category['category'], 'transaction_ids': transactions,
            'path': runtime.env.get('WWISE_CATEGORY_EVIDENCE_PATH') or runtime.env.get('WWISE_MACOS_CATEGORY_EVIDENCE_PATH'),
            'cleanup_status': 'unresolved_until_final_row'},
        'lifecycle_acceptance': 'Requires exact final category row source hash/mtime/tree and owned-process/sandbox cleanup; body completion alone is not final acceptance.',
        'scope_exclusions': ['other_versions', '2021_alternative', 'Source_language_inheritance', 'activeSource_switch', 'Tone_audio_effect'],
        'limits': {'calls': 74, 'receipt_bytes': 8 * 1024 * 1024, 'reply_bytes': 1024 * 1024,
            'native_files': 1024, 'native_bytes': 128 * 1024 * 1024}}
    if staged_voice_source_language:
        receipt.update(scope=category['scope'], diagnostic_only=True, atomic_Source_language_unresolved=True)
        receipt['scope_exclusions'].append('atomic_Voice_Source_language')
    attempted: set[str] = set()
    def persist():
        raw = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(raw) <= receipt['limits']['receipt_bytes'], 'Source receipt exceeds bound'
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(raw); temporary.replace(output)
        category['observation_sha256'] = hashlib.sha256(raw).hexdigest()
    class Gateway:
        def raw_gateway(self, argv):
            assert len(receipt['calls']) < receipt['limits']['calls'], 'Source public call bound exceeded'
            if argv[0] == 'execute':
                assert argv[1] not in attempted, 'Never retry a Source transaction'
                attempted.add(argv[1])
            row: dict[str, Any] = {'argv': list(argv)}; receipt['calls'].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                assert len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) <= receipt['limits']['reply_bytes']
                row.update(exit_code=code, payload=payload)
                return code, payload
            except Exception as exc:
                row['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
                raise
            finally:
                persist()
        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            if live:
                assert payload.get('endpoint') == endpoint and payload.get('detected_version') == runtime.version, payload
            return payload
    gateway = Gateway()
    def query(argv, *, source=False, voice=False, language=None, source_field=None):
        projection = ['--include', 'class-id', '--include', 'parent', '--include', 'notes']
        if source:
            assert source_field == 'StartFreq', 'Source observation must retain the selected real field'
            projection += ['--include', 'owner', '--include', 'source-language', '--include-field', source_field]
        if voice: projection += ['--include-field', 'IsVoice', '--include', 'active-source']
        payload = gateway.gateway(['query-object', *argv, *projection,
            *(['--language', language] if language is not None else []), '--max-results', '8'], live=True)
        assert payload.get('projection_complete') is not False and payload.get('limit_reached') is not True and payload.get('status') != 'partial', payload
        assert isinstance(payload.get('objects'), list) and payload.get('count') == len(payload['objects']), payload
        return payload['objects']
    def exact(identity, **view):
        rows = query(['--exact-id', identity], **view)
        assert len(rows) == 1 and uuid.UUID(rows[0]['id']) == uuid.UUID(identity), rows
        return rows[0]
    retained: list[dict[str, Any]] = []
    def retained_rows():
        return [{'owner': exact(row['owner']['id'], voice=True),
            'source': exact(row['source']['id'], source=True, language=row['language'], source_field=row['field']),
            'children': query(['--exact-id', row['owner']['id'], '--relationship', 'children'], language=row['language'])} for row in retained]
    def complete_staged(draft, phase, inspect_preview):
        _update_business_draft(gateway, draft, 'draft-check', live=True)
        preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
        tx = phase['transaction_id'] = preview['transaction_id']
        assert tx not in transactions; transactions.append(tx)
        try:
            shown = gateway.gateway(['transaction-show', tx], live=False)
            phase['immutable_preview'] = shown['artifact']
            inspect_preview(shown['artifact']['prepared_operation'])
            gateway.gateway(['confirm', tx, '--confirmation-token', shown['confirmation']['token']], live=False)
            phase['execution_attempted'] = True; persist()
            code, executed = gateway.raw_gateway(['execute', tx]); phase['execute'] = {'exit_code': code, 'payload': executed}
            assert code == 0 and executed.get('state') == 'executed_unverified', executed
            code, verified = gateway.raw_gateway(['verify', tx]); phase['verify'] = {'exit_code': code, 'payload': verified}
            assert code == 0 and verified.get('state') == 'verified' and verified.get('verification', {}).get('business_state_verified') is True, verified
            return executed
        finally:
            phase['final_transaction'] = gateway.gateway(['transaction-show', tx], live=False)
            persist()
    persist()
    try:
        status = gateway.gateway(['status'], live=True)
        info_call = next(row for row in status['calls'] if row['api'] == 'ak.wwise.core.getInfo')
        observed = observe_console_file(Path(info_call['evidence_path']), io_root=native_root)
        receipt['get_info'] = json.loads(base64.b64decode(observed['content_base64'], validate=True))['result']
        assert receipt['get_info']['isCommandLine'] is True
        version = receipt['get_info']['version']
        assert tuple(version[key] for key in ('year', 'major', 'minor', 'build')) == tuple(
            int(part) for part in catalog['provenance']['build'].split('.')), version
        project_call, = [row for row in status['calls'] if row['api'] == 'ak.wwise.core.getProjectInfo']
        project_observation = observe_console_file(Path(project_call['evidence_path']), io_root=native_root)
        project_info = json.loads(base64.b64decode(project_observation['content_base64'], validate=True))['result']
        project_languages = project_info['languages']
        assert isinstance(project_languages, list) and 0 < len(project_languages) <= 64, project_languages
        project_language_keys = {(uuid.UUID(row['id']), row['name']) for row in project_languages}
        assert len(project_language_keys) == len(project_languages) and all(isinstance(name, str) and name for _, name in project_language_keys), project_languages
        receipt['project_language_authority'] = {'project_id': project_info['id'], 'languages': project_languages,
            'native_evidence_path': project_call['evidence_path'], 'file_proof': project_observation['file_proof']}
        listed = gateway.gateway(['metadata', 'types', '--meaning', 'Language', '--page-size', '64'], live=True)['agent_result']
        language_type, = [row for row in listed['types'] if row.get('name') == 'Language']
        languages = gateway.gateway(language_type['query_command']['gateway_argv'], live=True)
        assert languages.get('status') != 'partial' and languages.get('limit_reached') is not True, languages
        choices = sorted((row for row in languages['objects'] if row.get('type') == 'Language'
            and (uuid.UUID(row['id']), row.get('name')) in project_language_keys), key=lambda row: row['name'])
        assert len(choices) == len(project_languages) and len({uuid.UUID(row['id']) for row in choices}) == len(choices), choices
        receipt['language_choices'] = choices
        construction_language = choices[0]['name']
        source_language = choices[1 if not staged_voice_source_language and len(choices) > 1 else 0]['name']
        receipt['distinct_language_disambiguation'] = not staged_voice_source_language and len(choices) > 1
        receipt['distinct_language_prerequisite'] = ('not_exercised_staged_no_construction_context' if staged_voice_source_language
            else 'established' if len(choices) > 1 else 'second_existing_language_absent_no_cross_language_credit')
        root_segments = ('Containers' if runtime.version == '2025.1' else 'Actor-Mixer Hierarchy', 'Default Work Unit')
        parent_rows = query([value for segment in root_segments for value in ('--path-segment', segment)])
        assert len(parent_rows) == 1, parent_rows
        parent = parent_rows[0]
        seen = {uuid.UUID(parent['id'])}
        if staged_voice_source_language:
            name = prefix + '_existing-voice'
            empty_phase = {'case': 'empty-voice', 'execution_attempted': False, 'effect_verified': False,
                'construction_language': None, 'source_language': None}
            receipt['phases'].append(empty_phase); persist()
            draft = _start_business_draft(gateway, 'object.set')
            owner_parent = _bind_business_object(gateway, draft, object_id=parent['id'])
            _update_business_draft(gateway, draft, 'draft-declare-new', [
                '--declaration-id', 'owner', '--parent-handle', owner_parent, '--name', name,
                '--kind', 'sound-voice', '--field', 'notes', 'Keep staged Voice'], live=False)
            def inspect_empty(prepared):
                native, = prepared['dispatch']['args']['objects'][0]['children']
                assert native['type'] == 'Sound' and native['@IsVoice'] is True, native
                assert 'language' not in native and not native.get('children'), native
                owner_spec, = [row for row in prepared['pre_state']['object_set_nodes'] if row['requested_name'] == name]
                empty_phase['owner_class_id'] = owner_spec['class_id']
            executed = complete_staged(draft, empty_phase, inspect_empty)
            root_result, = executed['dispatch_result']['result']['objects']
            owner_result, = root_result['children']
            owner_id = owner_result['id']
            assert uuid.UUID(owner_id) not in seen and not owner_result.get('children'), owner_result
            actual_owner = empty_phase['independent_owner'] = exact(owner_id, voice=True)
            assert actual_owner['name'] == name and actual_owner['type'] == 'Sound' and actual_owner['class_id'] == empty_phase['owner_class_id'], actual_owner
            assert actual_owner['parent']['id'] == parent['id'] and actual_owner['notes'] == 'Keep staged Voice', actual_owner
            assert type(actual_owner['properties']['IsVoice']) is bool and actual_owner['properties']['IsVoice'] is True, actual_owner
            empty_phase['independent_children'] = query(['--exact-id', owner_id, '--relationship', 'children'])
            assert empty_phase['independent_children'] == [], 'Staged Source requires an independently empty existing Voice'
            empty_phase['effect_verified'] = True; persist()
            phase = {'case': 'existing-voice-explicit-source', 'execution_attempted': False, 'effect_verified': False,
                'source_language': source_language, 'owner_before': actual_owner, 'construction_language': None}
            receipt['phases'].append(phase); persist()
            draft = _start_business_draft(gateway, 'object.createPlugin')
            owner_handle = _bind_business_object(gateway, draft, object_id=owner_id)
            kind = _discover_business_type(gateway, draft, meaning='Wwise Tone Generator', role='source', expected_label='Wwise Tone Generator')
            fields = _update_business_draft(gateway, draft, 'draft-discover-fields', ['--type-handle', kind, '--meaning', 'Frequency'], live=True)
            meaning, = fields['meaning_results']
            assert meaning['meaning'] == 'Frequency' and fields['candidate_count'] == len(meaning['candidates']), fields
            selected = [row for row in meaning['candidates'] if row.get('label') == 'Start Frequency'
                and row.get('field_kind') == 'property' and row.get('value_type') == 'number'
                and row.get('metadata', {}).get('name') == 'StartFreq' and row['metadata'].get('type') == 'Real32'
                and row['metadata'].get('display', {}).get('name') == 'Start Frequency']
            assert len(selected) == 1, 'Start Frequency must have one exact disclosed metadata candidate'
            field = phase['frequency_field'] = selected[0]
            _update_business_draft(gateway, draft, 'draft-declare-existing', [
                '--declaration-id', 'source', '--object-handle', owner_handle,
                '--field', 'plugin_role', 'source', '--field', 'plugin_type_handle', kind,
                '--field', 'plugin_name', 'Tone', '--field', 'plugin_placement', 'owner',
                '--field', 'language', source_language, '--field', 'notes', 'Keep staged Source',
                '--field-value', field['handle'], '440'], live=False)
            def inspect_source(prepared):
                native, = prepared['dispatch']['args']['objects']
                assert native['object'] == owner_id and 'language' not in native and '@IsVoice' not in native, native
                source, = native['children']
                assert source['type'] == 'Source' and source['classId'] == 6684674, source
                assert source['language'] == source_language and source['@' + field['metadata']['name']] == 440, source
                phase['source_class_id'] = source['classId']
            executed = complete_staged(draft, phase, inspect_source)
            root_result, = executed['dispatch_result']['result']['objects']
            assert uuid.UUID(root_result['id']) == uuid.UUID(owner_id), root_result
            source_result, = root_result['children']
            source_id = source_result['id']
            assert uuid.UUID(source_id) not in {*seen, uuid.UUID(owner_id)}, source_result
            source = phase['independent_source'] = exact(source_id, source=True, language=source_language, source_field=field['metadata']['name'])
            assert source['name'] == 'Tone' and source['type'] in {'Source', 'SourcePlugin'} and source['class_id'] == phase['source_class_id'], source
            assert source['parent']['id'] == owner_id and source['path'] == actual_owner['path'] + '\\Tone', source
            assert source.get('owner') is None or source['owner'].get('id') == owner_id, source
            assert source['notes'] == 'Keep staged Source' and source['properties'][field['metadata']['name']] == 440, source
            assert source['source_language']['name'] == source_language, source
            phase['independent_owner'] = exact(owner_id, voice=True)
            assert all(phase['independent_owner'].get(key) == actual_owner.get(key)
                for key in ('id', 'name', 'type', 'path', 'class_id', 'parent', 'notes', 'properties')), 'Separate Source creation changed the proven Voice'
            children = phase['independent_children'] = query(['--exact-id', owner_id, '--relationship', 'children'], language=source_language)
            assert len(children) == 1 and all(children[0].get(key) == source.get(key)
                for key in ('id', 'name', 'type', 'path', 'class_id', 'parent', 'notes')), children
            assert exact(parent['id']) == parent, 'Separate Source creation changed the bound parent'
            phase['effect_verified'] = True; persist()
            assert len(transactions) == 2
        for case in (() if staged_voice_source_language else ('sfx', 'voice-explicit-source', 'voice-default-source')):
            phase: dict[str, Any] = {'case': case, 'construction_language': None if case == 'sfx' else construction_language,
                'source_language': source_language if case == 'voice-explicit-source' else None,
                'source_language_effect': 'explicit_exact_name' if case == 'voice-explicit-source' else 'observed_default_only_no_inheritance_claim',
                'retained_before': retained_rows(), 'execution_attempted': False}
            receipt['phases'].append(phase); persist()
            assert phase['retained_before'] == [{'owner': row['owner'], 'source': row['source'], 'children': row['children']} for row in retained]
            draft = _start_business_draft(gateway, 'object.set')
            owner_parent = _bind_business_object(gateway, draft, object_id=parent['id'])
            name = prefix + '_' + case
            owner = _update_business_draft(gateway, draft, 'draft-declare-new', [
                '--declaration-id', 'owner', '--parent-handle', owner_parent, '--name', name,
                '--kind', 'sound-sfx' if case == 'sfx' else 'sound-voice', '--field', 'notes', 'Keep ' + case,
                *(['--field', 'language', construction_language] if case != 'sfx' else [])], live=False)
            owner_handle = declared_business_object_handle(owner, 'owner')
            kind = _discover_business_type(gateway, draft, meaning='Wwise Tone Generator', role='source', expected_label='Wwise Tone Generator')
            fields = _update_business_draft(gateway, draft, 'draft-discover-fields', ['--type-handle', kind, '--meaning', 'Frequency'], live=True)
            meaning, = fields['meaning_results']
            assert meaning['meaning'] == 'Frequency' and fields['candidate_count'] == len(meaning['candidates']), fields
            selected = [row for row in meaning['candidates'] if row.get('label') == 'Start Frequency'
                and row.get('field_kind') == 'property' and row.get('value_type') == 'number'
                and row.get('metadata', {}).get('name') == 'StartFreq' and row['metadata'].get('type') == 'Real32'
                and row['metadata'].get('display', {}).get('name') == 'Start Frequency']
            assert len(selected) == 1, 'Start Frequency must have one exact disclosed metadata candidate'
            field = phase['frequency_field'] = selected[0]
            frequency = field['handle']
            _update_business_draft(gateway, draft, 'draft-declare-new', [
                '--declaration-id', 'source', '--parent-handle', owner_handle, '--name', 'Tone', '--kind', kind,
                '--field', 'plugin_placement', 'owner', '--field', 'notes', 'Keep Source ' + case,
                '--field-value', frequency, '440',
                *(['--field', 'language', source_language] if case == 'voice-explicit-source' else [])], live=False)
            _update_business_draft(gateway, draft, 'draft-check', live=True)
            preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
            tx = phase['transaction_id'] = preview['transaction_id']; assert tx not in transactions; transactions.append(tx)
            try:
                shown = gateway.gateway(['transaction-show', tx], live=False)
                phase['immutable_preview'] = shown['artifact']
                prepared = shown['artifact']['prepared_operation']
                specs = prepared['pre_state']['object_set_nodes']
                owner_spec, = [row for row in specs if row['requested_name'] == name]
                source_spec, = [row for row in specs if 'source_plugin' in row]
                assert source_spec['structural_class_id'] == source_spec['source_plugin']['descriptor']['class_id'] == 6684674, 'Selected field must belong to the observed Wwise Tone Generator class'
                assert any(prop['name'] == field['metadata']['name'] and prop['value'] == 440 for prop in source_spec['properties']), source_spec
                phase['preexisting_source_ids'] = source_spec['source_plugin']['preexisting_plugin_ids']
                assert phase['preexisting_source_ids'] == [], 'All three cases construct new owners, not merged owners'
                gateway.gateway(['confirm', tx, '--confirmation-token', shown['confirmation']['token']], live=False)
                phase['execution_attempted'] = True; persist()
                code, executed = gateway.raw_gateway(['execute', tx]); phase['execute'] = {'exit_code': code, 'payload': executed}
                assert code == 0 and executed.get('state') == 'executed_unverified', executed
                code, verified = gateway.raw_gateway(['verify', tx]); phase['verify'] = {'exit_code': code, 'payload': verified}
                assert code == 0 and verified.get('state') == 'verified' and verified.get('verification', {}).get('business_state_verified') is True, verified
                root_result, = executed['dispatch_result']['result']['objects']
                owner_result, = root_result['children']; source_result, = owner_result['children']
                owner_id, source_id = owner_result['id'], source_result['id']
                assert uuid.UUID(owner_id) not in seen and uuid.UUID(source_id) not in seen and uuid.UUID(owner_id) != uuid.UUID(source_id), 'New constructor returned a retained GUID'
                actual_owner = phase['independent_owner'] = exact(owner_id, voice=True)
                actual_source = phase['independent_source'] = exact(source_id, source=True, language=phase['source_language'], source_field=field['metadata']['name'])
                assert actual_owner['name'] == name and actual_owner['type'] == 'Sound' and actual_owner['class_id'] == owner_spec['class_id'], actual_owner
                assert actual_owner['parent']['id'] == parent['id'] and actual_owner['notes'] == 'Keep ' + case, actual_owner
                assert type(actual_owner['properties']['IsVoice']) is bool and actual_owner['properties']['IsVoice'] is (case != 'sfx'), actual_owner
                assert actual_source['name'] == 'Tone' and actual_source['type'] in {'Source', 'SourcePlugin'} and actual_source['class_id'] == source_spec['structural_class_id'], actual_source
                assert actual_source['parent']['id'] == owner_id and actual_source['path'] == actual_owner['path'] + '\\Tone', actual_source
                assert actual_source.get('owner') is None or actual_source['owner'].get('id') == owner_id, actual_source
                assert actual_source['notes'] == 'Keep Source ' + case and actual_source['properties'][field['metadata']['name']] == 440, actual_source
                if phase['source_language'] is not None:
                    assert actual_source['source_language']['name'] == phase['source_language'], actual_source
                children = phase['independent_children'] = query(['--exact-id', owner_id, '--relationship', 'children'], language=phase['source_language'])
                assert len(children) == 1 and all(children[0].get(key) == actual_source.get(key)
                    for key in ('id', 'name', 'type', 'path', 'class_id', 'parent', 'notes')), children
                phase['retained_after'] = retained_rows()
                assert phase['retained_after'] == phase['retained_before'], 'A later construction changed the original owner/Source'
                assert exact(parent['id']) == parent, 'Construction changed the bound parent'
                seen.update((uuid.UUID(owner_id), uuid.UUID(source_id)))
                retained.append({'owner': actual_owner, 'source': actual_source, 'children': children, 'language': phase['source_language'], 'field': field['metadata']['name']})
                phase['effect_verified'] = True
            finally:
                phase['final_transaction'] = gateway.gateway(['transaction-show', tx], live=False)
                persist()
        assert hashlib.sha256(config.read_bytes()).hexdigest() == config_hash, 'Source configuration changed'
        final = gateway.gateway(['status'], live=True)
        assert final['wwise'] == status['wwise'], 'Source host context changed'
        receipt.update(collection_complete=True, business_effect_verified=True)
        category['status'] = 'PASS'
        return category
    except Exception as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
        raise
    finally:
        try:
            paths = sorted(set(native_root.glob('*.json')) - previous_native)
            assert len(paths) <= receipt['limits']['native_files']
            total = 0
            for index, path in enumerate(paths):
                observed = observe_console_file(path, io_root=native_root)
                raw = base64.b64decode(observed['content_base64'], validate=True)
                total += len(raw); assert total <= receipt['limits']['native_bytes'] and len(raw) <= 4 * 1024 * 1024
                target = artifacts / ('native-' + str(index) + '.json')
                prove_artifact_path(target, io_root=artifacts, field='Source archive', expect_directory=False)
                descriptor = os.open(target, binary_file_open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL) | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                assert target.read_bytes() == raw
                receipt['native_evidence'].append({'native_path': str(path), 'archive_path': str(target),
                    'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'native_file_proof': observed['file_proof']})
        except Exception as exc:
            receipt.update(collection_complete=False, business_effect_verified=False,
                archive_failure={'type': type(exc).__name__, 'message': str(exc)[:2048]})
            category['status'] = 'FAIL'
            raise
        finally:
            persist()


@pytest.mark.live
@pytest.mark.destructive
def test_planned_source_console_characterization(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    if workflow_sandbox_runtime.version != '2025.1':
        pytest.skip('Initial atomic Source characterization is Console2025-only; other lanes remain unproven')
    category = _collect_planned_source_characterization(workflow_sandbox_runtime, prefix='WAAPI_SOURCE_' + uuid.uuid4().hex[:10])
    assert category['status'] == 'PASS', category


@pytest.mark.live
@pytest.mark.destructive
def test_staged_voice_source_language_console_characterization(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    if workflow_sandbox_runtime.version != '2025.1':
        pytest.skip('Staged Voice Source-language observation is Console2025-only')
    category = _collect_planned_source_characterization(workflow_sandbox_runtime,
        prefix='WAAPI_STAGED_SOURCE_' + uuid.uuid4().hex[:10], staged_voice_source_language=True)
    assert category['status'] == 'PASS', category


def _collect_created_leaf_fields_history_acceptance(runtime: _WorkflowSandboxRuntime, *, name: str,
        null_source_only_diagnostic: bool = False) -> dict[str, Any]:
    """Ordinary created fields, then latest-project undo/redo with the owned receipt."""
    assert runtime.version in {'2022.1', '2023.1', '2024.1', '2025.1'}, 'No pinned native history route in 2021.1'
    endpoint = {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url}
    if null_source_only_diagnostic:
        assert runtime.version == '2022.1', 'Null-only minimization is pinned2022; other native lanes remain independent'
    output = runtime.state_dir / ('created-null-source-diagnostic.json' if null_source_only_diagnostic else 'created-fields-history-acceptance.json')
    category = {'category': 'created-null-source-diagnostic' if null_source_only_diagnostic else 'created-fields-history-acceptance', 'status': 'FAIL',
        'observation_path': str(output), 'verifier_strength': 'owned_source_receipt_plus_independent_created_fields_absence_and_restoration'}
    runtime.category_results.append(category)
    receipt = {'candidate': runtime.candidate, 'version': runtime.version, 'endpoint': endpoint, 'calls': [], 'setup': [], 'effects': [],
        'setup_coverage_credit': False, 'business_effect_verified': False, 'complete': False,
        'stack_head_observed': False, 'outside_scope_preservation_observed': False,
        'preserved_target_scope': 'exact_identity_class_parent_and_notes',
        'lifecycle_acceptance': 'Existing host-category-evidence/v3 finalizer owns source, host and cleanup proof'}
    if null_source_only_diagnostic:
        receipt.update(diagnostic_only=True, history_acceptance_credit=False,
            scope='fresh_setup_then_full_null_source_creation_without_undo_or_redo')
        category.update(diagnostic_only=True, history_acceptance_credit=False,
            verifier_strength='diagnostic_full_null_source_stored_fields_without_history_acceptance_credit')
    def persist():
        body = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 16 * 1024 * 1024, 'Created history receipt byte bound exceeded'
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(body); temporary.replace(output)
        category['observation_sha256'] = hashlib.sha256(body).hexdigest()
    class Gateway:
        def raw_gateway(self, argv):
            assert len(receipt['calls']) < 256, 'Created history public call bound exceeded'
            row = {'argv': list(argv)}; receipt['calls'].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                row.update(exit_code=code, payload=payload)
                return code, payload
            except Exception as exc:
                row['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
                raise
            finally:
                persist()
        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            if live:
                assert payload.get('endpoint') == endpoint, payload
                assert payload.get('detected_version') == runtime.version, payload
            return payload
    gateway = Gateway()
    projection = ['--include', 'class-id', '--include', 'parent', '--include', 'notes']
    required_fields = ('IsLoopingEnabled', 'IsLoopingInfinite', 'Volume', 'Attenuation')
    fields = required_fields
    def query(selector, *, sound=False):
        payload = gateway.gateway(['query-object', *selector, *projection, *(['--platform', platform] if sound else []),
            *(arg for field in (fields if sound else ()) for arg in ('--include-field', field))], live=True)
        rows = payload.get('objects')
        assert isinstance(rows, list) and payload.get('count') == len(rows) <= 1, payload
        assert payload.get('limit_reached') is not True and payload.get('projection_complete') is not False, payload
        assert payload.get('status') != 'partial', payload
        return rows
    def exact(identity, *, sound=False):
        rows = query(['--exact-id', identity], sound=sound)
        assert len(rows) == 1 and rows[0]['id'] == identity and type(rows[0].get('class_id')) is int, rows
        return rows[0]
    def by_path(segments, *, sound=False):
        return query([arg for segment in segments for arg in ('--path-segment', segment)], sound=sound)
    def complete(draft, label, *, setup=False, expected_root=None, expected_fields=None):
        phase = {'phase': label, 'effect_verified': False, 'native_outcome': 'not_executed'}
        receipt['setup' if setup else 'effects'].append(phase)
        phase_category = {'category': 'created-fields-history-' + label, 'status': 'FAIL',
            'observation_path': str(output), 'setup_coverage_credit': False,
            'verifier_strength': 'verified_setup_no_created_history_effect_credit' if setup else 'scoped_history_and_independent_state_readback'}
        if null_source_only_diagnostic:
            phase_category.update(diagnostic_only=True, history_acceptance_credit=False)
        runtime.category_results.append(phase_category)
        _update_business_draft(gateway, draft, 'draft-check', live=True)
        preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
        identity = _required_string(preview, 'transaction_id')
        shown = gateway.gateway(['transaction-show', identity], live=False)
        phase.update(transaction_id=identity, artifact_hash=preview['artifact_hash'], immutable_preview=shown['artifact'])
        if expected_root is not None:
            binding = shown['artifact']['prepared_operation']['pre_state']['history_binding']
            observed_fields = [row for row in binding['observations'] if row.get('kind') == 'creation_field']
            assert len(observed_fields) == len(expected_fields) and {row['field'] for row in observed_fields} == set(expected_fields), binding
            assert {row['object_id'] for row in observed_fields} == {expected_root}, binding
            assert all(isinstance(row['field_info'].get('raw'), Mapping) for row in observed_fields), binding
            root, = [row for row in binding['observations'] if row['kind'] == 'creation_presence']
            assert root['object']['id'] == expected_root and root['platform'] == platform, binding
        gateway.gateway(['confirm', identity, '--confirmation-token', shown['confirmation']['token']], live=False)
        phase['native_outcome'] = 'indeterminate'
        executed = gateway.gateway(['execute', identity], live=True)
        phase['execute'] = executed; phase['native_outcome'] = 'accepted'
        verified = gateway.gateway(['verify', identity], live=True); phase['verify'] = verified
        assert executed.get('automatic_retry') is False and verified.get('verified') is True, (executed, verified)
        assert verified.get('verification', {}).get('business_state_verified') is True, verified
        if not setup and label.endswith(('-undo', '-redo')):
            assert verified['verification_strength'] == 'scoped_history_effect_readback', verified
        return phase, phase_category
    def admit(phase, phase_category, observation):
        phase['independent_effect'] = observation; phase['effect_verified'] = True; phase_category['status'] = 'PASS'
    def history(source_id, direction):
        draft = _start_business_draft(gateway, 'ak.wwise.core.undo.' + direction)
        _update_business_draft(gateway, draft, 'draft-declare-core-plan', ['--value', 'history_scope', 'latest_project_history',
            '--value', 'expectation_receipt', source_id], live=True)
        return draft
    try:
        status = gateway.gateway(['status'], live=True)
        assert status.get('wwise', {}).get('isCommandLine') is True, status
        platform = status.get('project', {}).get('currentPlatformId')
        assert isinstance(platform, str) and uuid.UUID(platform).int != 0, status
        receipt['host_and_project'] = status
        actor_segments = CONTAINERS_PARENT_SEGMENTS if runtime.version == '2025.1' else ACTOR_MIXER_PARENT_SEGMENTS
        parent_rows = by_path(actor_segments)
        assert len(parent_rows) == 1 and exact(parent_rows[0]['id']) == parent_rows[0], parent_rows
        parent = parent_rows[0]
        setup = _start_business_draft(gateway, 'object.create')
        attenuation_parent = _bind_business_object(gateway, setup, path_segments=('Attenuations', 'Default Work Unit'))
        attenuation_type = _discover_business_type(gateway, setup, meaning='Attenuation', role='object', expected_label='Attenuation')
        _update_business_draft(gateway, setup, 'draft-declare-new', ['--declaration-id', 'target', '--parent-handle', attenuation_parent,
            '--kind', attenuation_type, '--name', name + '_Target', '--field', 'notes', 'Preserve history reference target'], live=False)
        phase, setup_category = complete(setup, 'setup-target', setup=True)
        target_id = _created_object_id(phase['execute'])
        target = exact(target_id)
        assert target['type'] == 'Attenuation' and target['name'] == name + '_Target', target
        phase['independent_setup'] = target; setup_category['status'] = 'PASS'
        for case in (('null',) if null_source_only_diagnostic else ('existing', 'null')):
            source_name = name + '_' + case
            source_segments = (*actor_segments, source_name)
            draft = _start_business_draft(gateway, 'object.create')
            parent_handle = _bind_business_object(gateway, draft, object_id=parent['id'])
            target_handle = _bind_business_object(gateway, draft, object_id=target_id)
            _update_business_draft(gateway, draft, 'draft-business-configure', ['--platform', platform], live=False)
            handles = {}
            for token in ('Volume', 'Attenuation'):
                disclosed = _update_business_draft(gateway, draft, 'draft-discover-fields',
                    ['--semantic-kind', 'sound-sfx', '--meaning', token], live=True)
                handles[token] = discovered_business_field_handle(disclosed, token)
            _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', 'source', '--parent-handle', parent_handle,
                '--kind', 'sound-sfx', '--name', source_name, '--field', 'notes', 'Created history ' + case,
                '--field', 'loop', 'infinite', '--field-value', handles['Volume'], '-6.0',
                '--field-value', handles['Attenuation'], target_handle if case == 'existing' else 'null'], live=False)
            phase, phase_category = complete(draft, case + '-source')
            source_id, created_id = phase['transaction_id'], _created_object_id(phase['execute'])
            node, = phase['immutable_preview']['prepared_operation']['pre_state']['object_create_nodes']
            materialized_properties = {row['name']: row['value'] for row in node['properties']}
            materialized_references = {row['name']: row['target_id'] for row in node['references']}
            fields = (*materialized_properties, *materialized_references)
            assert len(set(fields)) == len(fields) and set(required_fields) <= set(fields), node
            original = exact(created_id, sound=True)
            for token, expected in materialized_properties.items():
                actual = original.get('properties', {}).get(token)
                assert (type(actual) is bool and actual is expected) if type(expected) is bool else (
                    type(actual) in (int, float) and actual == expected), (token, expected, original)
            props = original.get('properties', {})
            assert original['type'] == 'Sound' and original['name'] == source_name, original
            assert original['path'] == '\\' + '\\'.join(source_segments), original
            assert original.get('notes') == 'Created history ' + case and original.get('parent', {}).get('id') == parent['id'], original
            assert original['class_id'] == phase['immutable_preview']['prepared_operation']['pre_state']['object_create_nodes'][0]['class_id'], original
            assert props.get('IsLoopingEnabled') is True and props.get('IsLoopingInfinite') is True, original
            assert type(props.get('Volume')) in (int, float) and props['Volume'] == -6.0, original
            assert 'Attenuation' in original.get('references', {}), original
            reference = original['references']['Attenuation']
            reference_id = reference.get('id') if isinstance(reference, Mapping) else reference
            if isinstance(reference, Mapping):
                assert 'id' in reference and not set(reference) - {'id', 'name', 'type', 'path'}, original
                assert all(isinstance(value, str) for value in reference.values()), original
            explicit_null = reference is None or (isinstance(reference_id, str)
                and reference_id == '{00000000-0000-0000-0000-000000000000}')
            assert (explicit_null if case == 'null' else isinstance(reference_id, str)
                and uuid.UUID(reference_id) == uuid.UUID(target_id)), original
            assert exact(target_id) == target and exact(parent['id']) == parent, 'Source changed its target or parent'
            admit(phase, phase_category, original)
            if null_source_only_diagnostic:
                phase_category['status'] = 'blocked'
                receipt.update(complete=True, classification='created_and_independently_observed')
                category.update(status='blocked', classification=receipt['classification'],
                    reason='Diagnostic null creation only; no undo/redo performed and no full history acceptance credit')
                return category
            phase, phase_category = complete(history(source_id, 'undo'), case + '-undo', expected_root=created_id, expected_fields=fields)
            absence = {'id': query(['--exact-id', created_id]), 'path': by_path(source_segments), 'target': exact(target_id)}
            assert absence['id'] == absence['path'] == [] and absence['target'] == target, absence
            admit(phase, phase_category, absence)
            if runtime.version != '2022.1':
                phase, phase_category = complete(history(source_id, 'redo'), case + '-redo', expected_root=created_id, expected_fields=fields)
                restored = exact(created_id, sound=True)
                assert json.dumps(restored, sort_keys=True) == json.dumps(original, sort_keys=True), (original, restored)
                assert by_path(source_segments, sound=True) == [restored] and exact(target_id) == target, restored
                assert exact(parent['id']) == parent, 'History changed its original parent'
                admit(phase, phase_category, restored)
        receipt.update(complete=True, business_effect_verified=True)
        category['status'] = 'PASS'
        return category
    except Exception as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        persist()


@pytest.mark.live
@pytest.mark.destructive
def test_created_leaf_fields_history_receipt_native_acceptance(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    """2022 undo; 2023–25 undo/redo; no GUI or native stack-entry ID claim."""
    assert workflow_sandbox_runtime.version != '2021.1', '2021.1 has no pinned standalone undo/redo route'
    category = _collect_created_leaf_fields_history_acceptance(workflow_sandbox_runtime,
        name='WAAPI_HISTORY_' + uuid.uuid4().hex[:12])
    assert category['status'] == 'PASS', category


@pytest.mark.live
@pytest.mark.destructive
def test_created_null_source_only_diagnostic(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    """One fresh setup and the full null source request; never precede it with undo."""
    if workflow_sandbox_runtime.version != '2022.1':
        pytest.skip('Null-source-only crash minimization is pinned2022; no other-version acceptance inference')
    category = _collect_created_leaf_fields_history_acceptance(workflow_sandbox_runtime,
        name='WAAPI_NULL_ONLY_' + uuid.uuid4().hex[:12], null_source_only_diagnostic=True)
    assert category.get('classification') == 'created_and_independently_observed', category
    assert category['status'] == 'blocked' and category['history_acceptance_credit'] is False, category


def _collect_effect_render_suffix_observation(runtime: _WorkflowSandboxRuntime, *, prefix: str) -> dict[str, Any]:
    return _collect_anonymous_effect_slot_construction_acceptance(runtime, prefix=prefix, render_suffix_diagnostic=True)


@pytest.mark.live
@pytest.mark.destructive
def test_effect_render_suffix_observation(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    if workflow_sandbox_runtime.version not in {'2023.1', '2024.1', '2025.1'}:
        pytest.skip('Stored suffix observation excludes legacy EffectN lanes; each modern version requires its own observation')
    category = _collect_effect_render_suffix_observation(workflow_sandbox_runtime, prefix='WAAPI_SUFFIX_' + uuid.uuid4().hex[:10])
    assert category.get('diagnostic_complete') is True, category
    # A diagnosed native error response remains a failed attempt with a retained
    # sandbox under the existing finalizer, never a business acceptance PASS.
    assert category.get('classification') in {'cleared', 'retained'}, category


def _collect_legacy_import_render_acceptance(runtime: _WorkflowSandboxRuntime, *, prefix: str) -> dict[str, Any]:
    """Legacy owner Render with media/immutable structure, in the existing lifecycle."""
    assert runtime.version in {'2021.1', '2022.1'}, runtime.version
    output = runtime.state_dir / 'legacy-import-render-acceptance.json'
    view_scope = ('current_default_view_only_unobserved_platform_identity' if runtime.version == '2021.1'
        else 'actual_preview_read_view_certificate_no_cross_platform_claim')
    category = {'category': 'legacy-import-render', 'status': 'FAIL', 'read_view_scope': view_scope,
        'verifier_strength': 'gateway_verified_plus_independent_full_owner_chain_actual_identity_source_ownership_media_hash_and_effect_preservation',
        'observation_path': str(output)}
    runtime.category_results.append(category)
    receipt = {'candidate': runtime.candidate, 'version': runtime.version, 'calls': [], 'transactions': [],
        'setup_coverage_credit': False, 'shareset_construction_verified': False, 'business_effect_verified': False,
        'read_view_scope': view_scope, 'tsv_media_verified': False,
        'lifecycle_acceptance': 'Requires existing host-category-evidence/v3 source-integrity and cleanup finalizer'}
    def persist():
        body = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 8 * 1024 * 1024, 'Legacy import receipt byte bound exceeded'
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(body); temporary.replace(output)
        category['observation_sha256'] = hashlib.sha256(body).hexdigest()
    class ReceiptGateway:
        def raw_gateway(self, argv):
            assert len(receipt['calls']) < 256, 'Legacy import public call bound exceeded'
            row = {'argv': list(argv)}; receipt['calls'].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                row.update(exit_code=code, payload=payload)
                return code, payload
            except Exception as exc:
                row['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
                raise
            finally:
                persist()
        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            if live:
                assert payload.get('detected_version') == runtime.version, payload
                assert payload.get('endpoint') == {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url}, payload
            return payload
    gateway = ReceiptGateway()
    projection = ['--include', 'class-id', '--include', 'parent', '--include', 'owner', '--include', 'notes']
    chain = ['OverrideEffect', *[name for i in range(4) for name in (f'Effect{i}', f'RenderEffect{i}', f'BypassEffect{i}')]]
    def one(argv, fields=()):
        result = gateway.gateway(['query-object', *argv, *projection,
            *(arg for field in fields for arg in ('--include-field', field))], live=True)
        rows = result.get('objects')
        assert result.get('count') == 1 and isinstance(rows, list) and len(rows) == 1, result
        assert result.get('projection_complete') is not False and result.get('limit_reached') is not True and result.get('status') != 'partial', result
        row = rows[0]
        assert uuid.UUID(_required_string(row, 'id')).int != 0 and type(row.get('class_id')) is int, row
        return row
    def exact(identity, fields=()):
        row = one(['--exact-id', identity], fields[:8])
        assert row['id'] == identity, row
        for start in range(8, len(fields), 8):
            extra = one(['--exact-id', identity], fields[start:start + 8])
            for key in ('id', 'name', 'type', 'path', 'class_id', 'parent', 'owner', 'notes'):
                assert (key in extra) == (key in row) and extra.get(key) == row.get(key), (row, extra)
            for kind in ('properties', 'references'):
                if kind in extra: row.setdefault(kind, {}).update(extra[kind])
        return row
    def at(segments, fields=()):
        found = one([*(arg for segment in segments for arg in ('--path-segment', segment))])
        row = exact(found['id'], fields)
        assert all(row.get(key) == found.get(key) for key in ('id', 'name', 'type', 'path', 'class_id', 'parent', 'owner')), (found, row)
        return row
    def guid(value):
        identity = value.get('id') if isinstance(value, Mapping) else value
        assert isinstance(identity, str) and uuid.UUID(identity).int != 0, value
        return identity
    def metadata(identity, *, detail=False):
        names, page = [], None
        for _ in range(4):
            result = gateway.gateway(['metadata', 'list', '--exact-id', identity, '--page-size', '64',
                *(['--page', page] if page is not None else [])], live=True)['agent_result']
            for field in result['fields']:
                assert isinstance(field.get('name'), str) and field['name'] not in names, result
                names.append(field['name'])
                assert len(names) <= 64, 'Legacy Effect metadata field cap exceeded'
                if detail:
                    info = gateway.gateway(['metadata', 'detail', '--exact-id', identity, '--selection', field['selection']], live=True)['agent_result']
                    assert info.get('complete') is True, info
                    receipt.setdefault('target_metadata', {}).setdefault(identity, []).append(info)
            if result.get('complete') is True:
                assert result['total_count'] == len(names), result
                return names
            next_page = _required_string(result, 'next_page'); assert next_page != page, result
            page = next_page
        raise AssertionError('Legacy Effect metadata exceeds four pages')
    def target_snapshot(identity, fields):
        assert metadata(identity) == fields, identity
        result = exact(identity)
        for start in range(0, len(fields), 16):
            row = exact(identity, fields[start:start + 16])
            for key in ('id', 'name', 'type', 'path', 'class_id', 'parent', 'owner', 'notes'):
                assert (key in row) == (key in result) and row.get(key) == result.get(key), (result, row)
            for kind in ('properties', 'references'):
                if kind in row: result.setdefault(kind, {}).update(row[kind])
        return result
    def field_handles(draft, required):
        names, selections, page = [], {}, None
        for _ in range(4):
            listed = _update_business_draft(gateway, draft, 'draft-discover-fields',
                ['--semantic-kind', 'sound-sfx', '--list', '--page-size', '64', *(['--page', page] if page else [])], live=True)['agent_result']
            for item in listed['fields']:
                assert item['name'] not in names, listed
                names.append(item['name'])
                if item['name'] in required: selections[item['name']] = item['selection']
            if listed.get('complete') is True:
                assert len(names) == listed['total_count'], listed
                break
            next_page = _required_string(listed, 'next_page'); assert next_page != page, listed
            page = next_page
        else: raise AssertionError('Legacy Sound discovery exceeds four pages')
        assert set(required) == set(selections), (required, names)
        handles = {}
        for name, selection in selections.items():
            selected = _update_business_draft(gateway, draft, 'draft-discover-fields',
                ['--semantic-kind', 'sound-sfx', '--selection', selection], live=True)
            candidates = selected['meaning_results'][0]['candidates']
            assert len(candidates) == 1 and candidates[0].get('metadata', {}).get('name') == name, selected
            handles[name] = discovered_business_field_handle(selected, name)
        return handles
    def complete(draft, phase):
        _update_business_draft(gateway, draft, 'draft-check', live=True)
        preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
        identity = _required_string(preview, 'transaction_id')
        shown = gateway.gateway(['transaction-show', identity], live=False)
        artifact = shown['artifact']; view = artifact['prepared_operation']['pre_state'].get('field_read_platform')
        phase.update(transaction_id=identity, artifact_hash=preview['artifact_hash'],
            compiled_native_request=artifact['prepared_operation']['dispatch'], read_view=view)
        if not phase['setup']:
            assert isinstance(view, Mapping) and view.get('status') in {'certified', 'unobserved'}, view
            if runtime.version == '2021.1': assert view['status'] == 'unobserved', view
        gateway.gateway(['confirm', identity, '--confirmation-token', shown['confirmation']['token']], live=False)
        phase['native_outcome'] = 'indeterminate'
        code, executed = gateway.raw_gateway(['execute', identity]); phase['execute'] = {'exit_code': code, 'payload': executed}
        assert code == 0 and executed.get('state') == 'executed_unverified' and executed.get('automatic_retry') is False, executed
        phase['native_outcome'] = 'accepted'
        code, verified = gateway.raw_gateway(['verify', identity]); phase['verify'] = {'exit_code': code, 'payload': verified}
        assert code == 0 and verified.get('verified') is True and verified.get('state') == 'verified', verified
        assert verified.get('verification', {}).get('business_state_verified') is True, verified
    try:
        # Pinned2021 SDK calls class16 AudioSource; actual object.get still
        # returns AudioFileSource. Keep catalog and object projection distinct.
        source_class_name = 'AudioSource' if runtime.version == '2021.1' else 'AudioFileSource'
        disclosed = gateway.gateway(['metadata', 'types', '--meaning', 'Sound', '--meaning', 'WorkUnit',
            '--meaning', 'Folder', '--meaning', 'Wwise Delay', '--meaning', source_class_name, '--page-size', '64'], live=True)['agent_result']
        assert disclosed.get('complete') is True, disclosed
        classes = {}
        for name in ('Sound', 'WorkUnit', 'Folder', 'Wwise Delay', 'AudioFileSource'):
            native_name = source_class_name if name == 'AudioFileSource' else name
            matches = [row for row in disclosed['types'] if row.get('name') == native_name]
            assert len(matches) == 1 and type(matches[0].get('classId')) is int, (name, disclosed)
            classes[name] = matches[0]['classId']
        assert classes['Sound'] == 65552, classes
        if runtime.version == '2021.1':
            assert classes['AudioFileSource'] == 16, classes  # Exact2021 AudioSource SDK class authority.
        receipt['source_class_discovery'] = {'name': source_class_name, 'class_id': classes['AudioFileSource']}

        receipt['live_classes'] = classes
        segments = ('Actor-Mixer Hierarchy', 'Default Work Unit')
        parent = at(segments)
        assert parent['type'] == 'WorkUnit' and parent['class_id'] == classes['WorkUnit'], parent
        effects_parent = at(('Effects', 'Factory Effects'))
        folder = at(('Effects', 'Factory Effects', 'Delay'))
        assert effects_parent['type'] == 'WorkUnit' and effects_parent['class_id'] == classes['WorkUnit'], effects_parent
        assert folder['type'] == 'Folder' and folder['class_id'] == classes['Folder'] and guid(folder.get('parent')) == effects_parent['id'], folder
        targets, target_fields = [], {}
        for name in ('Echo', 'The_Slap'):
            target = at(('Effects', 'Factory Effects', 'Delay', name))
            assert target['type'] == 'Effect' and target['class_id'] == classes['Wwise Delay'] and guid(target.get('parent')) == folder['id'], target
            assert 'owner' not in target or target['owner'] is None, target  # Not a ShareSet certificate; ordinary Gateway target validation still applies.
            fields = metadata(target['id'], detail=True); target_fields[target['id']] = fields
            targets.append(target_snapshot(target['id'], fields))
        assert targets[0]['id'] != targets[1]['id'], targets
        receipt['baseline'] = {'parent': parent, 'effects_parent': effects_parent, 'folder': folder, 'targets': targets}
        def preserved():
            observed = {'parent': exact(parent['id']), 'effects_parent': exact(effects_parent['id']),
                'folder': exact(folder['id']), 'targets': [target_snapshot(row['id'], target_fields[row['id']]) for row in targets]}
            assert observed == receipt['baseline'], observed
            return observed
        def owner_at(name, *, rendered):
            row = at((*segments, name), [*chain, 'Volume', 'IsVoice'])
            assert row['type'] == 'Sound' and row['class_id'] == classes['Sound'] and guid(row.get('parent')) == parent['id'], row
            assert row['notes'] == 'Keep legacy ' + name and row['properties']['IsVoice'] is False, row
            assert row['properties']['Volume'] == -9, row
            assert row['properties']['OverrideEffect'] is True, row
            for i in range(4):
                assert row['properties'][f'RenderEffect{i}'] is (rendered and i < 2), row
                assert row['properties'][f'BypassEffect{i}'] is False, row
                value = row['references'][f'Effect{i}']
                if i < 2: assert guid(value) == targets[i]['id'], row
                else: assert value is None or isinstance(value, Mapping) and uuid.UUID(value['id']).int == 0, row
            return row
        def selected_source(owner):
            children = None
            if runtime.version == '2021.1':
                result = gateway.gateway(['query-object', '--exact-id', owner['id'], '--relationship', 'children',
                    '--max-results', '100', '--language', 'SFX', *projection], live=True)
                children = result.get('objects')
                assert isinstance(children, list) and result.get('count') == len(children) < 100, result
                assert result.get('projection_complete') is not False and result.get('limit_reached') is not True and result.get('status') != 'partial', {'reason': 'source_child_page_incomplete', 'result': result}
                assert len({row['id'] for row in children}) == len(children), children
                for child in children:
                    assert isinstance(child.get('type'), str) and type(child.get('class_id')) is int and guid(child.get('parent')) == owner['id'], child
                    assert (child['type'] == 'AudioFileSource') == (child['class_id'] == classes['AudioFileSource']), child
                candidates = [child for child in children if child['type'] == 'AudioFileSource']
                assert len(candidates) == 1, {'reason': 'source_child_cardinality', 'children': children}
                selected = candidates[0]
                source_id = selected['id']
            else:
                selected = one(['--exact-id', owner['id'], '--include', 'active-source'])
                source_id = guid(selected.get('active_source'))
            source = one(['--exact-id', source_id, '--include', 'original-file-path', '--include', 'source-language',
                *(['--language', 'SFX'] if runtime.version == '2021.1' else [])])
            assert source['type'] == 'AudioFileSource' and source['class_id'] == classes['AudioFileSource'] and guid(source.get('parent')) == owner['id'], source
            assert isinstance(source.get('source_language'), Mapping) and source['source_language'].get('name') == 'SFX', source
            selection = {'selected': selected}
            if children is not None:
                selection.update(children=children, scope='complete_unique_source_child_and_matching_sound_wav',
                    generic_active_source_mapping=False)
            if runtime.version == '2021.1':
                for key in ('id', 'name', 'type', 'path', 'class_id', 'parent', 'owner', 'notes'):
                    assert (key in selected) == (key in source) and selected.get(key) == source.get(key), (selected, source)
                sound_file = one(['--exact-id', owner['id'], '--include', 'original-file-path', '--language', 'SFX'])
                assert sound_file['id'] == owner['id'] and sound_file['type'] == 'Sound', sound_file
                assert isinstance(source.get('original_file_path'), str) and source['original_file_path'] == sound_file.get('original_file_path'), (sound_file, source)
                selection['sound_file'] = sound_file
            return source, selection
        existing_name = prefix + '_Existing'
        completed_media = []
        for index, phase_name in enumerate(('setup_existing_sound_no_credit', 'existing_media_render', 'new_media_refs_render', 'immutable_tsv_structure_render')):
            setup, tsv = index == 0, index == 3
            if runtime.version == '2021.1' and not setup:
                # The 2021 LanguageList authority is the clean saved project.
                prerequisite = {'before_phase': phase_name, 'coverage_credit': False}
                receipt.setdefault('prerequisites', []).append(prerequisite)
                prerequisite['save'] = _save_sandbox_project(gateway)
                persist()
            existing = index == 1
            name = existing_name if index < 2 else prefix + ('_TSV' if tsv else '_New')
            phase = {'phase': phase_name, 'setup': setup, 'native_outcome': 'not_executed', 'effect_verified': False}
            receipt['transactions'].append(phase)
            operation = 'audio.importTabDelimited' if tsv else 'audio.import'
            draft = _start_business_draft(gateway, operation)
            if tsv:
                location = _bind_business_object(gateway, draft, role='import_location', object_id=parent['id'])
                table = runtime.sandbox.sandbox_path / (prefix + '.tsv')
                table.write_text('Object Path\tObject Type\tNotes\tProperty[Volume]\tProperty[OverrideEffect]\tReference[Effect0]\tReference[Effect1]\tProperty[RenderEffect1]\n'
                    + '<Sound SFX>' + name + '\tSound SFX\tKeep legacy ' + name + '\t-9\ttrue\t'
                    + targets[0]['id'] + '\t' + targets[1]['id'] + '\ttrue\n', encoding='utf-8', newline='\n')
                table_before = table.read_bytes(); phase['table'] = {'path': str(table), 'sha256': hashlib.sha256(table_before).hexdigest()}
                _update_business_draft(gateway, draft, 'draft-declare-artifact-plan',
                    ['--table-file', str(table), '--location-handle', location, '--language', 'SFX'], live=False)
            else:
                bound = _bind_business_object(gateway, draft, object_id=existing_owner['id'] if existing else parent['id'])
                required = ['RenderEffect1'] if existing else ['OverrideEffect', 'Effect0', 'Effect1', 'RenderEffect1']
                fields = field_handles(draft, required)
                values = {'RenderEffect1': 'false' if setup else 'true'}
                if not existing:
                    values.update(OverrideEffect='true', **{f'Effect{i}': _bind_business_object(gateway, draft, object_id=row['id']) for i, row in enumerate(targets)})
                args = ['--object-handle', bound] if existing else ['--parent-handle', bound, '--name', name, '--kind', 'sound-sfx']
                args += ['--field', 'notes', 'Keep legacy ' + name, '--field', 'volume_db', '-9']
                if not setup:
                    audio = _write_fixture_wav(runtime.sandbox.sandbox_path / 'GatewayLegacyImportAudio', name, frequency=440 + index * 110)
                    args += ['--field', 'media_file', str(audio)]
                    phase['media'] = {'input': str(audio), 'input_size': audio.stat().st_size,
                        'input_sha256': hashlib.sha256(audio.read_bytes()).hexdigest()}
                args += [arg for field, value in values.items() for arg in ('--field-value', fields[field], value)]
                _update_business_draft(gateway, draft, 'draft-declare-existing' if existing else 'draft-declare-new',
                    ['--declaration-id', 'sound', *args], live=False)
            complete(draft, phase)
            owner = owner_at(name, rendered=not setup); phase['independent_owner'] = owner
            result = _imported_object(phase['execute']['payload'], '\\' + '\\'.join((*segments, name)))
            assert result['id'] == owner['id'], (result, owner)
            if setup: existing_owner = owner
            if existing: assert owner['id'] == existing_owner['id'], owner
            if not setup and not existing: assert owner['id'] != existing_owner['id'], owner
            if index in (1, 2):
                source, selection = selected_source(owner)
                source_id = source['id']
                phase['independent_source'] = source
                phase['source_selection'] = selection
                source_result = _imported_object(phase['execute']['payload'], '\\' + '\\'.join((*segments, name, audio.stem)))
                assert source_result['id'] == source_id and guid(source_result.get('parent')) == owner['id'], source_result
                copied_path = Path(localize_waapi_host_path(_required_string(source, 'original_file_path')))
                assert not path_is_link_or_reparse(copied_path), copied_path
                copied = copied_path.resolve(strict=True)
                assert copied.is_file() and not copied.is_symlink() and path_is_under(copied, runtime.sandbox.sandbox_path.resolve()), copied
                assert copied.stat().st_size == phase['media']['input_size'] <= 16 * 1024, copied
                assert audio.stat().st_size == phase['media']['input_size'] and hashlib.sha256(audio.read_bytes()).hexdigest() == phase['media']['input_sha256'], audio
                phase['media'].update(copied=str(copied), copied_sha256=hashlib.sha256(copied.read_bytes()).hexdigest())
                assert phase['media']['copied_sha256'] == phase['media']['input_sha256'], phase['media']
            if tsv: assert table.read_bytes() == table_before, phase['table']
            phase['preserved_media'] = []
            for previous in completed_media:
                previous_owner = owner_at(previous['owner']['name'], rendered=True)
                assert previous_owner == previous['owner'], (previous, previous_owner)
                prior_source, prior_selection = selected_source(previous_owner)
                assert prior_source == previous['source'], (previous, prior_source)
                assert prior_selection == previous['selection'], (previous, prior_selection)
                prior_path = Path(localize_waapi_host_path(_required_string(prior_source, 'original_file_path')))
                assert not path_is_link_or_reparse(prior_path), prior_path
                assert prior_path.resolve(strict=True) == Path(previous['media']['copied']), prior_source
                assert prior_path.stat().st_size == previous['media']['input_size'] <= 16 * 1024, previous
                assert hashlib.sha256(prior_path.read_bytes()).hexdigest() == previous['media']['copied_sha256'], previous
                input_path = Path(previous['media']['input'])
                assert input_path.stat().st_size == previous['media']['input_size'] and hashlib.sha256(input_path.read_bytes()).hexdigest() == previous['media']['input_sha256'], previous
                phase['preserved_media'].append(previous)
            if index in (1, 2): completed_media.append({'owner': owner, 'source': source, 'selection': selection, 'media': phase['media']})
            phase['preserved'] = preserved()
            phase['effect_verified'] = not setup
        receipt['business_effect_verified'] = True; category['status'] = 'PASS'
        category['read_views'] = [row['read_view'] for row in receipt['transactions'] if not row['setup']]
        return category
    except Exception as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        persist()


@pytest.mark.live
@pytest.mark.destructive
def test_legacy_import_render_acceptance(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    assert workflow_sandbox_runtime.version in {'2021.1', '2022.1'}, 'Legacy owner Render applies only to 2021/2022'
    category = _collect_legacy_import_render_acceptance(workflow_sandbox_runtime, prefix='WAAPI_LEGACY_IMPORT_' + uuid.uuid4().hex[:10])
    assert category['status'] == 'PASS', category


def _multisource_saved_xml_oracle(raw: bytes, cases: Sequence[Mapping[str, Any]], *, work_unit_id: str,
                                  platform_choices=None) -> dict[str, Any]:
    """Independent saved-model expectation, never a public/runtime active-source resolver."""
    assert len(raw) <= 8 * 1024 * 1024 and b'<!DOCTYPE' not in raw.upper(), 'Unsafe saved XML'
    root = ET.fromstring(raw)
    pending, count = [(root, 0)], 0
    while pending:
        node, depth = pending.pop(); count += 1
        assert count <= 32768 and depth <= 64, 'Saved XML node/depth bound exceeded'
        pending.extend((child, depth + 1) for child in node)
    def guid(value):
        if isinstance(value, Mapping): value = value.get('id')
        assert isinstance(value, str) and uuid.UUID(value).int != 0, value
        return '{' + str(uuid.UUID(value)).upper() + '}'
    units = [node for node in root.iter('WorkUnit') if guid(node.get('ID')) == guid(work_unit_id)]
    assert len(units) == 1, 'Saved Work Unit identity missing or duplicated'
    direct = units[0].find('ChildrenList')
    assert direct is not None, 'Saved Work Unit has no ChildrenList'
    result = {}
    for case in cases:
        owner, children, language = case['owner'], case['children'], case['language']
        matches = [node for node in root.iter('Sound') if guid(node.get('ID')) == guid(owner['id'])]
        assert len(matches) == 1 and matches[0] in list(direct), 'Saved Sound is missing, duplicated or reparented'
        sound = matches[0]
        assert sound.get('Name') == owner['name'], 'Saved Sound name differs from exact public identity'
        sources = sound.find('ChildrenList')
        assert sources is not None and len(sources) == 2 and all(node.tag == 'AudioFileSource' for node in sources), 'Saved two-source cardinality missing'
        by_id = {guid(row['id']): row for row in children}
        assert len(by_id) == 2 and {guid(node.get('ID')) for node in sources} == set(by_id), 'Saved/public source GUID sets differ'
        for node in sources:
            actual = by_id[guid(node.get('ID'))]
            assert actual['type'] == 'AudioFileSource' and actual['class_id'] == 16, 'Unproven public source class'
            assert guid(actual['parent']) == guid(owner['id']), 'Public source parent differs'
            assert actual['path'] == owner['path'] + '\\' + node.get('Name', ''), 'Saved/public source paths differ'
            assert node.get('Name') == actual['name'] and node.findtext('Language') == language, 'Saved source name/language differs'
            assert actual['source_language']['name'] == language, 'Public source language differs'
            assert node.findtext('AudioFile') == Path(localize_waapi_host_path(actual['original_file_path'])).name, 'Saved/public original filename differs'
        active = sound.find('ActiveSourceList')
        if platform_choices is not None:
            assert active is not None and 1 <= len(active) <= 3, 'Saved platform choices missing or unbounded'
            entries = [dict(node.attrib) for node in active]
            assert all(node.tag == 'ActiveSource' and guid(node.get('ID')) in by_id and
                node.get('Name') == by_id[guid(node.get('ID'))]['name'] for node in active), 'Saved platform choice identity differs'
            assert len({entry.get('Platform') for entry in entries}) == len(entries), 'Duplicated saved platform choices'
            known_keys = {'Linked', *(choice[key] for choice in platform_choices for key in ('name', 'id'))}
            assert all(entry.get('Platform') in known_keys for entry in entries), 'Unreviewed saved platform key'
            selected = {}
            for choice in platform_choices:
                specific = [entry for entry in entries if entry.get('Platform') in {choice['id'], choice['name']}]
                candidates = specific or [entry for entry in entries if entry.get('Platform') == 'Linked']
                assert len(candidates) == 1 and guid(candidates[0]['ID']) == guid(choice['source_id']), 'Saved platform active choice differs'
                selected[choice['name']] = guid(candidates[0]['ID'])
            assert len(set(selected.values())) == 2, 'Platform choices did not diverge'
            result[case['label']] = {'active_ids': selected, 'active_source_entries': entries,
                'document_attributes': dict(root.attrib), 'sound_attributes': dict(sound.attrib)}
            continue
        assert active is not None and len(active) == 1, 'Saved active-source oracle is missing or ambiguous'
        selected = active[0]
        assert selected.tag == 'ActiveSource' and selected.get('Platform') == 'Linked', 'Unreviewed saved active platform representation'
        active_id = guid(selected.get('ID'))
        assert active_id in by_id and selected.get('Name') == by_id[active_id]['name'], 'Saved active GUID/name is not one of the two observed sources'
        public_order = [guid(row['id']) for row in children]
        xml_order = [guid(node.get('ID')) for node in sources]
        result[case['label']] = {'active_id': active_id, 'public_order': public_order, 'xml_order': xml_order,
            'public_active_index': public_order.index(active_id), 'xml_active_index': xml_order.index(active_id),
            'platform': 'Linked', 'language': language, 'class_authority': 'live AudioSource class16 plus saved AudioFileSource tag'}
    if platform_choices is not None:
        return {'cases': result, 'platform_choices_diverge': True}
    sfx = [result[label] for label in ('sfx_reverse_1', 'sfx_reverse_2')]
    ordering = {kind: len({row[kind + '_active_index'] for row in sfx}) == 2 for kind in ('public', 'xml')}
    return {'cases': result, 'ordering_counterexample': ordering, 'ordering_discrimination': any(ordering.values())}


def _collect_2021_multisource_active_selection_diagnostic(runtime: _WorkflowSandboxRuntime, *, prefix: str) -> dict[str, Any]:
    return _collect_multisource_active_selection_diagnostic(runtime, prefix=prefix)


def _collect_multisource_active_selection_diagnostic(runtime: _WorkflowSandboxRuntime, *, prefix: str,
                                                    platform_characterization: bool = False) -> dict[str, Any]:
    """Prepare only through public transactions; compare three two-source fixtures with saved XML."""
    from wwise_waapi.operation_soundbank import capture_file_proof
    assert runtime.version == ('2022.1' if platform_characterization else '2021.1'), runtime.version
    output = runtime.state_dir / ('platform-active-source-characterization.json' if platform_characterization else 'multisource-active-selection-diagnostic.json')
    # Direct business helpers: Save9, import(1start+1bind+6rows+6completion),
    # copy(1start+2bind+1declare+6completion), delete(2queries+1start+1bind+1declare+6completion).
    budgets = {'readiness': 5, 'save_initial': 9, 'import_setup': 14, 'initial_sources': 24,
        'copy_setup': 3 * 10, 'cardinality': 3 * 4, 'save_final': 9, 'saved_oracle': 1,
        'observations': 3 * 6, 'cleanup': 6 * 11}
    if platform_characterization:
        budgets = {'readiness': 6, 'save_initial': 9, 'import_setup': 10, 'initial_sources': 8,
            'copy_setup': 10, 'cardinality': 4, 'select_active': 20, 'save_final': 9, 'saved_oracle': 1,
            'observations': 12, 'cleanup': 22}
    category = {'category': '2021-multisource-active-selection-diagnostic', 'status': 'FAIL',
        'coverage_credit': 'none', 'business_effect_verified': False, 'observation_path': str(output),
        'verifier_strength': 'public_setup_plus_saved_xml_active_guid_diagnostic_only'}
    if platform_characterization:
        category['category'] = '2022-platform-active-source-serialization-characterization'
    runtime.category_results.append(category)
    receipt = {'candidate': runtime.candidate, 'version': runtime.version, 'calls': [], 'transactions': [],
        'outcome': 'pending', 'stage': 'readiness', 'collection_complete': False,
        'generic_active_source_mapping': False, 'native_absence_proven': False, 'business_effect_verified': False,
        'setup_coverage_credit': False, 'model_images': {}, 'call_counts': {key: 0 for key in budgets},
        'limits': {'public_calls': sum(budgets.values()), 'phase_calls': budgets, 'reply_bytes': 1024 * 1024,
            'total_reply_bytes': 8 * 1024 * 1024, 'receipt_bytes': 8 * 1024 * 1024,
            'input_files': 2 if platform_characterization else 6, 'input_bytes_each': 16 * 1024, 'xml_files': 1, 'xml_bytes': 8 * 1024 * 1024,
            'xml_nodes': 32768, 'xml_depth': 64},
        'lifecycle_acceptance': 'Requires existing host-category-evidence/v3 full source hash/mtime/tree and cleanup finalizer'}
    reply_bytes = 0
    active_phase = None
    root_ids, input_proofs = [], []
    def persist():
        raw = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(raw) <= receipt['limits']['receipt_bytes'], 'Diagnostic receipt byte bound exceeded'
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(raw); temporary.replace(output)
        category['observation_sha256'] = hashlib.sha256(raw).hexdigest()
    def stop(outcome, message):
        receipt['outcome'] = outcome
        raise RuntimeError(message)
    def stage(name):
        receipt['stage'] = name
    def guid(value):
        if isinstance(value, Mapping): value = value.get('id')
        assert isinstance(value, str) and uuid.UUID(value).int != 0, value
        return '{' + str(uuid.UUID(value)).upper() + '}'
    class Gateway:
        def raw_gateway(self, argv):
            nonlocal reply_bytes
            key = receipt['stage']
            assert receipt['call_counts'][key] < budgets[key], ('Public phase call bound exceeded', key)
            receipt['call_counts'][key] += 1
            row = {'stage': key, 'argv': list(argv)}; receipt['calls'].append(row)
            if argv[0] == 'execute' and active_phase is not None:
                active_phase['native_outcome'] = 'indeterminate'
            try:
                code, payload = runtime.raw_gateway(argv)
                row.update(exit_code=code, payload=payload)
                size = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
                reply_bytes += size
                assert size <= receipt['limits']['reply_bytes'] and reply_bytes <= receipt['limits']['total_reply_bytes'], 'Public result byte bound exceeded'
                return code, payload
            except Exception as exc:
                row['exception'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
                if argv[0] == 'execute': receipt['outcome'] = 'execution_indeterminate'
                raise
            finally:
                persist()
        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            if code or payload.get('ok') is not True:
                if argv[0] == 'execute':
                    dispatch = payload.get('dispatch_result')
                    recovery = payload.get('recovery') or {}
                    if payload.get('native_dispatch_attempted') is False or (
                            not isinstance(dispatch, Mapping) and recovery.get('project_write_outcome') == 'no_project_write_in_this_invocation'):
                        outcome = 'skill_preparation_rejected'
                    elif isinstance(dispatch, Mapping) and dispatch.get('waapi_error_uri') == 'ak.wwise.invalid_arguments':
                        # Report the native rejection, retaining Gateway's possibly indeterminate delivery/effects state.
                        outcome = 'native_copy_rejection_reported' if active_phase and active_phase['operation'] == 'object.copy' else 'native_rejection_reported'
                    else:
                        outcome = 'execution_indeterminate'
                else:
                    outcome = 'skill_preparation_rejected' if receipt['stage'] in {'import_setup', 'copy_setup', 'select_active'} and argv[0] != 'verify' else 'observation_or_verification_blocked'
                stop(outcome, json.dumps(payload, ensure_ascii=False)[:2048])
            if live and (payload.get('detected_version') != runtime.version or payload.get('endpoint') != {
                    'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url}):
                stop('execution_indeterminate' if argv[0] == 'execute' else 'observation_or_setup_blocked', 'Public endpoint/version binding differs')
            return payload
    gateway = Gateway()
    projection = ['--include', 'class-id', '--include', 'parent', '--include', 'notes']
    def rows(argv, *, language=None, source=False, sound=False, extra=(), platform=None):
        view = ['--platform', platform or receipt['platform']['id']] if 'platform' in receipt else []
        if language is not None: view += ['--language', language]
        outputs = ['--include', 'original-file-path', '--include', 'source-language'] if source else []
        if sound: outputs += ['--include', 'original-file-path', '--include', 'work-unit', '--include-field', 'IsVoice']
        result = gateway.gateway(['query-object', *argv, *projection, *view, *outputs, *extra], live=True)
        found = result.get('objects')
        assert isinstance(found, list) and result.get('count') == len(found), 'Malformed public object page'
        assert result.get('projection_complete') is not False and result.get('limit_reached') is not True and result.get('status') != 'partial', 'Incomplete public object page'
        assert len({guid(row['id']) for row in found}) == len(found), 'Duplicated public identities'
        return found
    def one(argv, **kwargs):
        found = rows(argv, **kwargs)
        assert len(found) == 1, ('Expected one exact public identity', found)
        return found[0]
    def exact(identity, **kwargs):
        found = one(['--exact-id', identity], **kwargs)
        assert guid(found['id']) == guid(identity), ('Exact identity changed', found)
        return found
    def source_children(owner, language, expected, *, platform=None):
        found = rows(['--exact-id', owner['id'], '--relationship', 'children', '--max-results', '3'], language=language, source=True, platform=platform)
        if len(found) != expected:
            stop('setup_cardinality_blocked', 'Required exact direct-source cardinality not established')
        for row in found:
            assert row['type'] == 'AudioFileSource' and row['class_id'] == 16 and guid(row['parent']) == guid(owner['id']), row
            assert row['source_language']['name'] == language, row
        return found
    def media_proof(path):
        return capture_file_proof(path, field='Diagnostic WAV', max_bytes=16 * 1024, io_root=runtime.sandbox.sandbox_path)
    def complete(draft, phase):
        nonlocal active_phase
        active_phase = phase
        receipt['transactions'].append(phase)
        _update_business_draft(gateway, draft, 'draft-check', live=True)
        preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
        phase.update(transaction_id=preview['transaction_id'], artifact_hash=preview['artifact_hash'])
        shown = gateway.gateway(['transaction-show', preview['transaction_id']], live=False)
        gateway.gateway(['confirm', preview['transaction_id'], '--confirmation-token', shown['confirmation']['token']], live=False)
        executed = gateway.gateway(['execute', preview['transaction_id']], live=True)
        if executed.get('state') != 'executed_unverified' or executed.get('automatic_retry') is not False:
            stop('execution_indeterminate', 'Execution acknowledgement or non-retry binding is incomplete')
        phase['native_outcome'] = 'accepted'
        verified = gateway.gateway(['verify', preview['transaction_id']], live=True)
        assert verified.get('state') == 'verified' and verified.get('verification', {}).get('business_state_verified') is True, verified
        phase['verified'] = True
        active_phase = None
        return executed
    def lifecycle(operation, identity, *, parent=None):
        nonlocal active_phase
        phase = {'operation': operation, 'object_id': identity, 'parent_id': parent, 'native_outcome': 'not_executed'}
        active_phase = phase
        draft = _start_business_draft(gateway, operation)
        _bind_business_object(gateway, draft, role='object', object_id=identity)
        if parent is not None: _bind_business_object(gateway, draft, role='parent', object_id=parent)
        _update_business_draft(gateway, draft, 'draft-declare-object-change', ['--name-conflict', 'fail'] if parent is not None else [], live=False)
        return complete(draft, phase)
    try:
        source_kind = 'AudioFileSource' if platform_characterization else 'AudioSource'
        types = gateway.gateway(['metadata', 'types', '--meaning', 'Sound', '--meaning', source_kind, '--meaning', 'WorkUnit', '--meaning', 'Platform', '--page-size', '64'], live=True)['agent_result']
        assert types.get('complete') is True, 'Class discovery incomplete'
        classes = {}
        for name in ('Sound', source_kind, 'WorkUnit', 'Platform'):
            candidates = [row for row in types['types'] if row['name'] == name and row['type'] == 'WObject']
            assert len(candidates) == 1 and type(candidates[0]['classId']) is int, name
            classes[name] = candidates[0]
        assert classes['Sound']['classId'] == 65552 and classes[source_kind]['classId'] == 16
        platforms = rows(['--type-selection', classes['Platform']['selection'], '--max-results', '20'])
        platform_candidates = [row for row in platforms if row['name'] == 'Mac' and row['type'] == 'Platform']
        assert len(platform_candidates) == 1, 'Exact Mac platform unavailable'
        receipt['platform'] = exact(platform_candidates[0]['id'])
        if platform_characterization:
            windows = [row for row in platforms if row['name'] == 'Windows' and row['type'] == 'Platform']
            assert len(windows) == 1, 'Exact Windows platform unavailable'
            receipt['other_platform'] = exact(windows[0]['id'])
        parent = one([arg for segment in ACTOR_MIXER_PARENT_SEGMENTS for arg in ('--path-segment', segment)])
        parent = exact(parent['id'])
        assert parent['type'] == 'WorkUnit' and parent['class_id'] == classes['WorkUnit']['classId']
        receipt['parent_before'] = parent
        stage('save_initial'); receipt['initial_save'] = _save_sandbox_project(gateway)
        stage('import_setup')
        draft = _start_business_draft(gateway, 'audio.import')
        bound = _bind_business_object(gateway, draft, object_id=parent['id'])
        cases = []
        fixtures = (('platform_pair', 'SFX', ('Original_A', 'Copied_B')),) if platform_characterization else (
            ('sfx_reverse_1', 'SFX', ('Zeta_1', 'Alpha_1')), ('sfx_reverse_2', 'SFX', ('Alpha_2', 'Zeta_2')),
            ('voice', 'English(US)', ('Voice_A', 'Voice_B')))
        for index, (label, language, stems) in enumerate(fixtures):
            case = {'label': label, 'language': language, 'sounds': []}; cases.append(case)
            for offset, stem in enumerate(stems):
                name = prefix + '_' + label + ('_Target' if offset == 0 else '_Donor')
                path = _write_fixture_wav(runtime.sandbox.sandbox_path / (prefix + '_Audio'), stem, frequency=330 + index * 220 + offset * 110)
                proof = media_proof(path); input_proofs.append(proof)
                case['sounds'].append({'name': name, 'input': proof})
                _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', label + str(offset),
                    '--parent-handle', bound, '--name', name, '--kind', 'sound-sfx' if language == 'SFX' else 'sound-voice',
                    '--field', 'media_file', str(path), '--field', 'language', language], live=False)
        receipt['fixtures'] = cases
        complete(draft, {'operation': 'audio.import', 'native_outcome': 'not_executed'})
        stage('initial_sources')
        for case in cases:
            for sound in case['sounds']:
                owner = one([arg for segment in (*ACTOR_MIXER_PARENT_SEGMENTS, sound['name']) for arg in ('--path-segment', segment)], language=case['language'], sound=True)
                owner = exact(owner['id'], language=case['language'], sound=True)
                root_ids.append(owner['id']); sound['owner'] = owner
                assert owner['type'] == 'Sound' and owner['class_id'] == 65552 and guid(owner['parent']) == guid(parent['id'])
                assert owner['properties']['IsVoice'] is (case['language'] != 'SFX')
                child = source_children(owner, case['language'], 1)[0]
                source = exact(child['id'], language=case['language'], source=True)
                assert source == child, 'Initial source changed during exact readback'
                sound['source'] = source
                proof = media_proof(Path(localize_waapi_host_path(source['original_file_path'])))
                assert (proof['size'], proof['sha256']) == (sound['input']['size'], sound['input']['sha256'])
                sound['original'] = proof
        for case in cases:
            target, donor = case['sounds']
            stage('copy_setup'); lifecycle('object.copy', donor['source']['id'], parent=target['owner']['id'])
            stage('cardinality')
            children = source_children(target['owner'], case['language'], 2)
            actual = [exact(row['id'], language=case['language'], source=True) for row in children]
            assert actual == children, 'Two-source readback drifted'
            assert guid(target['source']['id']) in {guid(row['id']) for row in children} and guid(donor['source']['id']) not in {guid(row['id']) for row in children}, 'Copy did not preserve/freshen source identity'
            preserved = [row for row in children if guid(row['id']) == guid(target['source']['id'])]
            assert preserved == [target['source']], 'Copy changed the existing target source'
            assert exact(donor['source']['id'], language=case['language'], source=True) == donor['source'], 'Donor source changed'
            paths = [row['original_file_path'] for row in children]
            assert len(set(paths)) == 2, 'Two-source original paths are not distinct'
            proofs = [media_proof(Path(localize_waapi_host_path(path))) for path in paths]
            assert len({proof['sha256'] for proof in proofs}) == 2, 'Two-source bytes are not distinct'
            assert {(p['size'], p['sha256']) for p in proofs} == {(s['original']['size'], s['original']['sha256']) for s in case['sounds']}
            case.update(owner=target['owner'], children=children, copied_media=proofs)
        if platform_characterization:
            target = cases[0]
            original_id = guid(target['sounds'][0]['source']['id'])
            copied = [row for row in target['children'] if guid(row['id']) != original_id]
            assert len(copied) == 1, 'Copied source identity is not unique'
            receipt['platform_choices'] = [
                {'name': receipt['platform']['name'], 'id': receipt['platform']['id'], 'source_id': copied[0]['id']},
                {'name': receipt['other_platform']['name'], 'id': receipt['other_platform']['id'], 'source_id': original_id}]
            stage('select_active')
            for choice in receipt['platform_choices']:
                operation = 'ak.wwise.core.sound.setActiveSource'
                draft = _start_business_draft(gateway, operation)
                owner_handle = _bind_business_object(gateway, draft, object_id=target['owner']['id'], role='sound')
                source_handle = _bind_business_object(gateway, draft, object_id=choice['source_id'], role='source')
                _update_business_draft(gateway, draft, 'draft-declare-project-setting-plan',
                    ['--sound-handle', owner_handle, '--source-handle', source_handle, '--platform-name', choice['name']], live=False)
                complete(draft, {'operation': operation, 'platform': choice, 'native_outcome': 'not_executed'})
        stage('save_final'); receipt['final_save'] = _save_sandbox_project(gateway)
        stage('saved_oracle')
        unit = exact(parent['id'], extra=['--include', 'file-path'])
        path = Path(localize_waapi_host_path(unit['file_path']))
        assert path.suffix.casefold() == '.wwu' and path_is_under(path, runtime.sandbox.sandbox_path) and not path_is_link_or_reparse(path), 'Unowned saved Work Unit'
        image_root = runtime.state_dir / 'multisource-model'; image_root.mkdir(exist_ok=False)
        image = ConsoleModelImageIndex(root=image_root, project=runtime.sandbox.sandbox_project, phase='after', link=receipt['model_images'].setdefault('after', {}))
        observed = observe_console_file(path, io_root=runtime.sandbox.sandbox_path)
        raw = image.save(path, observed); image.finish()
        receipt['oracle'] = _multisource_saved_xml_oracle(raw, cases, work_unit_id=parent['id'],
            platform_choices=receipt.get('platform_choices'))
        stage('observations')
        observations = [(case, choice) for case in cases for choice in receipt['platform_choices']] if platform_characterization else [(case, None) for case in cases]
        for case, choice in observations:
            platform_id = choice['id'] if choice else None
            owner = exact(case['owner']['id'], language=case['language'], sound=True, platform=platform_id,
                extra=['--include', 'active-source'] if choice else ())
            assert guid(owner['work_unit']) == guid(parent['id']), 'Sound owning Work Unit differs'
            for key in ('id', 'name', 'type', 'path', 'class_id', 'notes', 'properties'):
                assert owner.get(key) == case['owner'].get(key), ('Copy changed target Sound', key)
            assert guid(owner['parent']) == guid(case['owner']['parent']), 'Copy reparented the target Sound'
            children = source_children(owner, case['language'], 2, platform=platform_id)
            assert {guid(row['id']): row for row in children} == {guid(row['id']): row for row in case['children']}, 'Source collection changed after Save'
            for child in children: assert exact(child['id'], language=case['language'], source=True, platform=platform_id) == child
            matches = ['{' + str(uuid.UUID(row['id'])).upper() + '}' for row in children
                if row['original_file_path'] == owner.get('original_file_path')]
            expected = receipt['oracle']['cases'][case['label']]['active_ids'][choice['name']] if choice else receipt['oracle']['cases'][case['label']]['active_id']
            comparison = {'sound_file': owner.get('original_file_path'), 'field_present': 'original_file_path' in owner,
                'matching_source_ids': matches, 'saved_active_guid': expected}
            if choice:
                comparison['platform'] = choice
                assert guid(owner.get('active_source')) == expected, 'Native active edge differs from saved platform oracle'
                case.setdefault('platform_path_comparisons', []).append(comparison)
            else:
                case['path_comparison'] = comparison
            assert matches == [expected], 'Sound WAV path does not uniquely match the saved active GUID'
            assert exact(owner['id'], language=case['language'], sound=True, platform=platform_id,
                extra=['--include', 'active-source'] if choice else ()) == owner, 'Sound observation drifted'
            assert {guid(row['id']): row for row in source_children(owner, case['language'], 2, platform=platform_id)} == {guid(row['id']): row for row in children}, 'Source collection drifted'
        assert observe_console_file(path, io_root=runtime.sandbox.sandbox_path)['file_proof'] == observed['file_proof'], 'Saved XML changed during public observations'
        receipt['input_after'] = [media_proof(Path(proof['path'])) for proof in input_proofs]
        assert receipt['input_after'] == input_proofs, 'Diagnostic inputs changed'
        receipt['path_join_matches_saved_oracle'] = True
        if not platform_characterization and not receipt['oracle']['ordering_discrimination']:
            stop('ordering_counterexample_unproven', 'No opposite actual active-source child positions observed; no order inference or replay')
        stage('cleanup')
        for identity in reversed(root_ids):
            assert exact(identity)['id'] == identity
            lifecycle('object.delete', identity)
            assert rows(['--exact-id', identity]) == [], 'Created Sound cleanup incomplete'
        receipt.update(outcome='diagnostic_complete', collection_complete=True, object_cleanup='verified')
        category['status'] = 'PASS'
    except Exception as exc:
        if receipt['outcome'] == 'pending':
            receipt['outcome'] = ('saved_oracle_blocked' if receipt['stage'] == 'saved_oracle' else
                'setup_cardinality_blocked' if receipt['stage'] == 'cardinality' else
                'cleanup_failed' if receipt['stage'] == 'cleanup' else 'observation_or_setup_blocked')
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
        receipt.setdefault('object_cleanup', 'not_attempted_or_incomplete_preserve_failed_sandbox')
        category.update(status='blocked', reason=receipt['outcome'])
    finally:
        persist()
    return category


@pytest.mark.live
@pytest.mark.destructive
def test_2021_multisource_active_selection_diagnostic(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    if workflow_sandbox_runtime.version != '2021.1':
        pytest.skip('The source-bound active-selection diagnostic is2021-only')
    category = _collect_2021_multisource_active_selection_diagnostic(workflow_sandbox_runtime,
        prefix='WAAPI_MULTI_' + uuid.uuid4().hex[:10])
    assert category['status'] == 'PASS', category


@pytest.mark.live
@pytest.mark.destructive
def test_platform_active_source_serialization_characterization(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    if workflow_sandbox_runtime.version != '2022.1':
        pytest.skip('The platform serialization characterization is2022-only')
    category = _collect_multisource_active_selection_diagnostic(workflow_sandbox_runtime,
        prefix='WAAPI_PLATFORM_' + uuid.uuid4().hex[:10], platform_characterization=True)
    assert category['status'] == 'PASS', category


def _collect_soundcaster_dump_observation(runtime: _WorkflowSandboxRuntime) -> dict[str, Any]:
    """Observe one closed dump; token occurrences never certify session values."""
    from wwise_waapi.operation_soundbank import capture_file_proof
    from wwise_waapi.console_project_operations import inspect_object_dump_artifact, MAX_OBJECT_DUMP_JSON_DEPTH
    assert runtime.version == '2024.1', 'This source-bound diagnostic is only for the retained 2024 fixture'
    sessions = [('MIDI', '{9C02096E-8E29-4029-9D49-778F85015C87}'),
        ('Minigun', '{1C5BA931-9550-4DC8-B1C7-13689B8AE813}'),
        ('Music', '{F4B8069C-3C15-4157-B570-8A41AB2463C2}')]
    project = runtime.sandbox.sandbox_project
    output = runtime.state_dir / 'soundcaster-dump-observation.json'
    artifacts = runtime.state_dir / 'soundcaster-dump-artifacts'
    artifacts.mkdir(parents=True, exist_ok=False)
    model_root = artifacts / 'model'; model_root.mkdir()
    dump_root = project.parent / ('soundcaster-dump-' + uuid.uuid4().hex)
    dump_root.mkdir(exist_ok=False)
    dump_file = dump_root / 'objects.json'
    category = {'category': 'soundcaster-dump-diagnostic', 'status': 'FAIL',
        'verifier_strength': 'diagnostic_artifact_and_exact_guid_occurrences_only_no_session_value_or_business_credit',
        'coverage_credit': 'none', 'observation_path': str(output)}
    runtime.category_results.append(category)
    receipt = {'contract': 'waapi-skill.soundcaster-dump-diagnostic/v1', 'candidate': runtime.candidate,
        'version': runtime.version, 'calls': [], 'collection_complete': False, 'transaction': {},
        'business_preservation_verified': False, 'session_values_observed': False, 'semantic_absence_proven': False,
        'media_operation_executed': False, 'saved_model_preserved': None, 'model_images': {},
        'limits': {'public_calls': 12, 'reply_bytes': 256 * 1024, 'total_reply_bytes': 2 * 1024 * 1024,
            'report_bytes': 128 * 1024, 'dump_bytes': 8 * 1024 * 1024,
            'json_work': 'linear_in_bounded_artifact_bytes',
            'json_depth': MAX_OBJECT_DUMP_JSON_DEPTH, 'source_bindings': 128, 'session_occurrence_paths': 32}}
    def persist():
        body = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= receipt['limits']['report_bytes'], 'Dump diagnostic report byte bound exceeded'
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(body); temporary.replace(output)
        category['observation_sha256'] = hashlib.sha256(body).hexdigest()
    def archive(path, raw):
        prove_artifact_path(path, io_root=artifacts, field='dump diagnostic archive', must_exist=False, expect_directory=False)
        descriptor = os.open(path, binary_file_open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL) | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        proof = capture_file_proof(path, field='dump diagnostic archive', max_bytes=8 * 1024 * 1024, io_root=artifacts)
        assert proof['sha256'] == hashlib.sha256(raw).hexdigest() and proof['size'] == len(raw), proof
        return proof
    class Gateway:
        def gateway(self, argv, *, live):
            assert len(receipt['calls']) < 12, 'Dump diagnostic public call bound exceeded'
            row = {'argv': list(argv)}; receipt['calls'].append(row)
            if argv[0] == 'execute': receipt['transaction']['execution_attempted'] = True
            try:
                code, payload = runtime.raw_gateway(argv)
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                assert len(body) <= 256 * 1024, 'Dump diagnostic reply byte bound exceeded'
                receipt['total_reply_bytes'] = receipt.get('total_reply_bytes', 0) + len(body)
                assert receipt['total_reply_bytes'] <= 2 * 1024 * 1024, 'Dump diagnostic total reply bound exceeded'
                path = artifacts / ('reply-' + str(len(receipt['calls'])) + '.json')
                proof = archive(path, body)
                row.update(exit_code=code, reply_path=str(path), reply_sha256=proof['sha256'], reply_bytes=len(body))
                if payload.get('transaction_id'): receipt['transaction']['id'] = payload['transaction_id']
                assert code == 0 and payload.get('ok') is True, payload
                if live:
                    assert payload.get('detected_version') == runtime.version, payload
                    assert payload.get('endpoint') == {'host': runtime.lifecycle.host, 'port': runtime.port,
                        'url': runtime.lifecycle.waapi_url}, payload
                return payload
            except Exception as exc:
                row['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
                raise
            finally:
                persist()
    gateway = Gateway()
    def guid(value):
        assert isinstance(value, str) and len(value) in (36, 38), value
        parsed = uuid.UUID(value)
        assert parsed.int != 0, value
        return '{' + str(parsed).upper() + '}'
    def model(phase, *, parse=False):
        link = receipt['model_images'][phase] = {}
        index = ConsoleModelImageIndex(root=model_root, project=project, phase=phase, link=link)
        paths, pending, entries = [project], [(project.parent, 0)], 0
        definitions, selected = {}, {}
        try:
            while pending:
                directory, depth = pending.pop()
                assert depth <= 64, 'Saved model directory depth bound exceeded'
                with os.scandir(directory) as children:
                    for entry in children:
                        entries += 1
                        assert entries <= 4096, 'Saved model directory entry bound exceeded'
                        path = Path(entry.path)
                        assert not path_is_link_or_reparse(path), path
                        if entry.is_dir(follow_symlinks=False): pending.append((path, depth + 1))
                        elif path.name.casefold().endswith('.wwu'):
                            paths.append(path)
                            assert len(paths) <= 513, 'Saved model Work Unit bound exceeded'
            for path in sorted(paths):
                raw = index.save(path, observe_console_file(path, io_root=project.parent))
                if not parse: continue
                assert b'<!DOCTYPE' not in raw.upper(), 'Unexpected XML document type'
                tree = ET.fromstring(raw)
                stack, count = [(tree, None, 0)], 0
                while stack:
                    node, group, depth = stack.pop(); count += 1
                    assert count <= 32768 and depth <= 64, 'Saved XML node/depth bound exceeded'
                    if node.tag in {'StateGroup', 'SwitchGroup'}: group = (node.tag, guid(node.get('ID')))
                    if node.tag in {'GameParameter', 'State', 'Switch', 'StateGroup', 'SwitchGroup'}:
                        identity = guid(node.get('ID'))
                        assert identity not in definitions, ('Duplicate source definition', identity)
                        definitions[identity] = {'type': node.tag, 'name': node.get('Name'),
                            'group_id': group[1] if group and node.tag in {'State', 'Switch'} else None}
                    if node.tag == 'SoundcasterSession' and node.get('ID', '').upper() in dict(sessions).values():
                        identity = guid(node.get('ID'))
                        assert identity not in selected, ('Duplicate source session', identity)
                        selected[identity] = (node, path.relative_to(project.parent).as_posix())
                    stack.extend((child, group, depth + 1) for child in reversed(list(node)))
            index.finish()
            return index, definitions, selected
        except Exception as exc:
            index.error(None, exc)
            raise
    def source_oracle(definitions, selected):
        assert set(selected) == {identity for _, identity in sessions}, 'Source session identities missing or ambiguous'
        result, binding_count = [], 0
        for name, identity in sessions:
            node, relative = selected[identity]
            assert node.get('Name') == name, (name, node.attrib)
            row = {'id': identity, 'name': name, 'source_file': relative, 'rtpc': [], 'states': [], 'switches': [], 'show_all': {}}
            for tag, field, member, reference, kind in (
                ('RTPCValueList', 'rtpc', 'RTPCValue', 'GameParameterRef', 'GameParameter'),
                ('CurrentStateList', 'states', 'CurrentStateRef', None, 'State'),
                ('CurrentSwitchList', 'switches', 'CurrentSwitchRef', None, 'Switch')):
                lists = node.findall(tag)
                assert len(lists) == 1 and lists[0].get('ShowAll') in {'true', 'false'}, (identity, tag)
                row['show_all'][field] = lists[0].get('ShowAll')
                seen = set()
                for item in lists[0]:
                    assert item.tag == member, item.tag
                    target = item.find(reference) if reference else item
                    target_id = guid(target.get('ID'))
                    assert target_id not in seen, ('Duplicate saved selection', target_id)
                    seen.add(target_id)
                    definition = definitions[target_id]
                    assert definition['type'] == kind and definition['name'] == target.get('Name'), (target.attrib, definition)
                    value = {'target_id': target_id, 'target_name': definition['name']}
                    if reference:
                        values = item.findall('Value')
                        assert len(values) == 1 and len(values[0].text or '') <= 64, item.attrib
                        value['value_text'] = values[0].text
                        assert math.isfinite(float(value['value_text'])), value
                    else:
                        group_id = definition['group_id']
                        assert group_id in definitions and definitions[group_id]['type'] == kind + 'Group', definition
                        value['group_id'] = group_id
                    row[field].append(value); binding_count += 1
                    assert binding_count <= 128, 'Source saved-value binding bound exceeded'
            result.append(row)
        assert binding_count > 0, 'Fixture must contain real stored selections'
        receipt['source_binding_count'] = binding_count
        return result
    def retain_dump():
        captured = observe_console_file(dump_file, io_root=dump_root)
        raw = base64.b64decode(captured['content_base64'], validate=True)
        archived = artifacts / 'native-objects.json'
        proof = archive(archived, raw)
        receipt['dump_artifact'] = {'native_path': str(dump_file), 'native_file_proof': captured['file_proof'],
            'archive_path': str(archived), 'archive_proof': proof, 'semantic_schema': 'unobserved'}
        return raw
    try:
        before, definitions, selected = model('before', parse=True)
        receipt['source_sessions'] = source_oracle(definitions, selected)
        persist()
        draft = _start_business_draft(gateway, 'ak.wwise.cli.dumpObjects')
        _update_business_draft(gateway, draft, 'draft-declare-cli-console-plan', [
            '--value', 'project_file', str(project), '--value', 'output_file', str(dump_file),
            '--value', 'content', 'property_sets', '--toggle', 'include_session_objects', 'enable'], live=True)
        transaction = _complete_core_result_schema_draft(gateway, draft)
        receipt['transaction'].update(id=transaction['preview']['transaction_id'],
            execute_state=transaction['execute']['state'], verify_state=transaction['verify']['state'],
            business_state_verified=transaction['verify']['verification']['business_state_verified'])
        raw = retain_dump()
        dumped, json_observation = inspect_object_dump_artifact(raw)
        targets = {identity for _, identity in sessions}
        for row in receipt['source_sessions']:
            for field in ('rtpc', 'states', 'switches'):
                for binding in row[field]:
                    targets.add(binding['target_id'])
                    if 'group_id' in binding: targets.add(binding['group_id'])
        counts = receipt['guid_occurrence_counts'] = {identity: 0 for identity in sorted(targets)}
        occurrences = receipt['session_guid_occurrences'] = []
        receipt['occurrence_paths_complete'] = True
        session_ids = {identity for _, identity in sessions}
        stack = [(iter(((None, dumped),)), [], False)]
        def observe(value, path, location):
            if type(value) is not str or len(value) not in (36, 38): return
            try: identity = guid(value)
            except (ValueError, AssertionError): return
            if identity not in counts: return
            counts[identity] += 1
            if identity in session_ids:
                if len(occurrences) < 32 and len(json.dumps(path).encode('utf-8')) <= 2048:
                    occurrences.append({'id': identity, 'json_path_segments': path, 'match_in': location,
                        'interpretation': 'token_occurrence_only_not_session_or_value_binding'})
                else: receipt['occurrence_paths_complete'] = False
        while stack:
            children, parent_path, mapping = stack[-1]
            try:
                key, item = next(children)
            except StopIteration:
                stack.pop()
                continue
            path = parent_path if key is None else [*parent_path, key]
            if mapping: observe(key, path, 'key')
            if isinstance(item, dict):
                stack.append((iter(item.items()), path, True))
            elif isinstance(item, list):
                stack.append((enumerate(item), path, False))
            else: observe(item, path, 'value')
        receipt['dump_json_nodes'] = json_observation['json_nodes']
        receipt['dump_json_depth'] = json_observation['json_depth']
        receipt['missing_session_guid_tokens'] = [identity for _, identity in sessions if not counts[identity]]
        after, _, _ = model('after')
        receipt['saved_model_preserved'] = (set(before.files) == set(after.files) and all(
            row['file_proof'] == after.files[name]['file_proof'] for name, row in before.files.items()))
        assert receipt['saved_model_preserved'], 'Dump changed saved project/Work Unit identities or bytes'
        receipt['collection_complete'] = True
        category['status'] = 'blocked'
        category['reason'] = 'Diagnostic only; native session/value representation requires independent review'
        return category
    except Exception as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
        raise
    finally:
        try:
            if dump_file.exists() and 'dump_artifact' not in receipt: retain_dump()
            if receipt['model_images'].get('before', {}).get('complete') and 'after' not in receipt['model_images']:
                model('after')
        except Exception as exc:
            receipt['finalization_error'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
        persist()


@pytest.mark.live
@pytest.mark.destructive
def test_soundcaster_dump_metadata_observation(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    category = _collect_soundcaster_dump_observation(workflow_sandbox_runtime)
    assert category['status'] == 'blocked', category
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert receipt['collection_complete'] and receipt['saved_model_preserved'], receipt
    assert receipt['session_values_observed'] is receipt['business_preservation_verified'] is False


def _collect_source_plugin_selection_acceptance(runtime: _WorkflowSandboxRuntime, *, prefix: str) -> dict[str, Any]:
    """Prove one observed A→B Source-plugin selection, never a sole-source no-op."""
    from wwise_waapi.native_catalog import load_native_catalog
    assert runtime.version in {'2022.1', '2023.1', '2024.1', '2025.1'}
    catalog = load_native_catalog(runtime.version, 'wwise-console')
    endpoint = {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url}
    output = runtime.state_dir / 'source-plugin-selection.json'
    assert not output.exists(), 'Never overwrite original Source selection evidence'
    output.parent.mkdir(parents=True, exist_ok=True)
    artifacts = runtime.state_dir / 'source-plugin-selection-artifacts'; artifacts.mkdir(exist_ok=False)
    native_root = Path(runtime.env['WWISE_EVIDENCE_DIR']); previous_native = set(native_root.glob('*.json'))
    config = Path(runtime.env['WAAPI_SKILL_CONFIG_PATH']); config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    transactions: list[str] = []
    category = {'category': 'source-plugin-active-selection', 'status': 'FAIL', 'transaction_ids': transactions,
        'observation_path': str(output), 'scope': 'one_actual_SourcePlugin_A_to_B_on_matching_Console_current_view',
        'verifier_strength': 'Gateway_verification_plus_independent_GUID_change_class_parent_fields_complete_childset_and_preservation'}
    runtime.category_results.append(category)
    receipt: dict[str, Any] = {'contract': 'waapi-skill.source-plugin-selection/v1', 'candidate': runtime.candidate,
        'version': runtime.version, 'endpoint': endpoint, 'transaction_ids': transactions, 'phases': [], 'calls': [],
        'native_evidence': [], 'collection_complete': False, 'business_effect_verified': False,
        'config_sha256': config_hash, 'source_project': str(runtime.sandbox.source_project),
        'native_catalog': {'build': catalog['provenance']['build'], 'content_sha256': catalog['content_sha256']},
        'scope_exclusions': ['other_versions_and_hosts', 'Voice_or_language_semantics', 'platform_isolation_or_unlink', 'Tone_audio_effect'],
        'limits': {'calls': 70, 'receipt_bytes': 8 * 1024 * 1024, 'reply_bytes': 1024 * 1024,
                   'native_files': 1024, 'native_bytes': 128 * 1024 * 1024},
        'lifecycle_final_reference': {'contract': 'waapi-skill.host-category-evidence/v3', 'phase': 'final',
            'candidate': runtime.candidate, 'category': category['category'], 'transaction_ids': transactions,
            'path': runtime.env.get('WWISE_CATEGORY_EVIDENCE_PATH') or runtime.env.get('WWISE_MACOS_CATEGORY_EVIDENCE_PATH'),
            'cleanup_status': 'unresolved_until_final_row'},
        'lifecycle_acceptance': 'Body completion requires matching final v3 category source/hash/mtime/tree and owned-process/sandbox cleanup.'}
    attempted: set[str] = set()
    def persist():
        raw = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(raw) <= receipt['limits']['receipt_bytes'], 'Selection receipt exceeds bound'
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(raw); temporary.replace(output)
        category['observation_sha256'] = hashlib.sha256(raw).hexdigest()
    class Gateway:
        def raw_gateway(self, argv):
            assert len(receipt['calls']) < receipt['limits']['calls'], 'Source selection public call bound exceeded'
            if argv[0] == 'execute':
                assert argv[1] not in attempted, 'Never retry Source selection or setup'
                attempted.add(argv[1])
            row: dict[str, Any] = {'argv': list(argv)}; receipt['calls'].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                assert len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) <= receipt['limits']['reply_bytes']
                row.update(exit_code=code, payload=payload)
                return code, payload
            except Exception as exc:
                row['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
                raise
            finally:
                persist()
        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            if live:
                assert payload.get('endpoint') == endpoint and payload.get('detected_version') == runtime.version, payload
            return payload
    gateway = Gateway()
    def query(argv, *, source=False, sound=False):
        projection = ['--include', 'class-id', '--include', 'parent', '--include', 'notes']
        if source:
            projection += [item for token in ('StartFreq', 'WaveType') for item in ('--include-field', token)]
        if sound: projection += ['--include-field', 'IsVoice', '--include', 'active-source']
        payload = gateway.gateway(['query-object', *argv, *projection, '--max-results', '8'], live=True)
        assert payload.get('projection_complete') is not False and payload.get('limit_reached') is not True and payload.get('status') != 'partial', payload
        rows = payload.get('objects'); assert isinstance(rows, list) and payload.get('count') == len(rows), payload
        ids = [uuid.UUID(row['id']) for row in rows]; assert len(set(ids)) == len(ids), rows
        return rows
    def exact(identity, **view):
        rows = query(['--exact-id', identity], **view); assert len(rows) == 1, rows
        assert uuid.UUID(rows[0]['id']) == uuid.UUID(identity), rows
        return rows[0]
    def children(identity):
        return sorted(query(['--exact-id', identity, '--relationship', 'children']), key=lambda row: uuid.UUID(row['id']))
    def active(row):
        value = row.get('active_source'); assert isinstance(value, Mapping) and isinstance(value.get('id'), str), row
        return str(uuid.UUID(value['id']))
    def preserved_sound(row):
        result = {key: value for key, value in row.items() if key != 'active_source'}
        if 'unavailable_fields' in result:
            fields = [field for field in result['unavailable_fields'] if field != 'active_source']
            if fields:
                result['unavailable_fields'] = fields
            else:
                del result['unavailable_fields']
        return result
    def complete(draft, label):
        phase: dict[str, Any] = {'phase': label, 'execution_attempted': False}; receipt['phases'].append(phase)
        _update_business_draft(gateway, draft, 'draft-check', live=True)
        preview = _update_business_draft(gateway, draft, 'preview-from-draft', live=True)
        tx = phase['transaction_id'] = preview['transaction_id']; assert tx not in transactions; transactions.append(tx)
        try:
            shown = gateway.gateway(['transaction-show', tx], live=False); phase['immutable_preview'] = shown['artifact']
            gateway.gateway(['confirm', tx, '--confirmation-token', shown['confirmation']['token']], live=False)
            phase['execution_attempted'] = True; persist()
            code, executed = gateway.raw_gateway(['execute', tx]); phase['execute'] = {'exit_code': code, 'payload': executed}
            assert code == 0 and executed.get('state') == 'executed_unverified', executed
            code, verified = gateway.raw_gateway(['verify', tx]); phase['verify'] = {'exit_code': code, 'payload': verified}
            assert code == 0 and verified.get('state') == 'verified' and verified.get('verification', {}).get('business_state_verified') is True, verified
            return phase
        finally:
            phase['final_transaction'] = gateway.gateway(['transaction-show', tx], live=False); persist()
    def field(payload, label, token):
        rows = payload.get('field_candidates')
        if rows is None:
            rows = [candidate for result in payload.get('meaning_results', []) for candidate in result.get('candidates', [])]
        matches = {row['handle']: row for row in rows if row.get('label') == label and row.get('metadata', {}).get('name') == token}
        assert len(matches) == 1, {'label': label, 'token': token, 'candidates': rows}
        return next(iter(matches.values()))
    persist()
    try:
        status = gateway.gateway(['status'], live=True)
        info_call = next(row for row in status['calls'] if row['api'] == 'ak.wwise.core.getInfo')
        observed = observe_console_file(Path(info_call['evidence_path']), io_root=native_root)
        receipt['get_info'] = json.loads(base64.b64decode(observed['content_base64'], validate=True))['result']
        assert receipt['get_info']['isCommandLine'] is True
        version = receipt['get_info']['version']
        assert tuple(version[key] for key in ('year', 'major', 'minor', 'build')) == tuple(int(p) for p in catalog['provenance']['build'].split('.')), version
        segments = ('Containers' if runtime.version == '2025.1' else 'Actor-Mixer Hierarchy', 'Default Work Unit')
        rows = query([item for segment in segments for item in ('--path-segment', segment)])
        parent, = rows; receipt['parent_before'] = parent
        draft = _start_business_draft(gateway, 'object.set')
        parent_handle = _bind_business_object(gateway, draft, object_id=parent['id'])
        for label in ('target', 'sentinel'):
            _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', label,
                '--parent-handle', parent_handle, '--name', prefix + '_' + label, '--kind', 'sound-sfx',
                '--field', 'notes', 'Keep ' + label], live=False)
        setup = complete(draft, 'empty_sounds')
        root, = setup['execute']['payload']['dispatch_result']['result']['objects']
        created = root['children']; assert len(created) == 2 and len({uuid.UUID(row['id']) for row in created}) == 2, created
        target_id, = [row['id'] for row in created if row['name'] == prefix + '_target']
        sentinel_id, = [row['id'] for row in created if row['name'] == prefix + '_sentinel']
        target, sentinel = exact(target_id, sound=True), exact(sentinel_id, sound=True)
        specs = setup['immutable_preview']['prepared_operation']['pre_state']['object_set_nodes']
        for label, row in (('target', target), ('sentinel', sentinel)):
            spec, = [s for s in specs if s['requested_name'] == prefix + '_' + label]
            assert row['type'] == 'Sound' and row['class_id'] == spec['class_id'] and row['parent']['id'] == parent['id'], row
            assert row['notes'] == 'Keep ' + label and row['properties']['IsVoice'] is False and row.get('active_source') is None, row
            assert children(row['id']) == [], row
        sources = []
        for index, frequency in enumerate((440, 660), 1):
            draft = _start_business_draft(gateway, 'object.createPlugin')
            owner = _bind_business_object(gateway, draft, object_id=target_id)
            kind = _discover_business_type(gateway, draft, meaning='Wwise Tone Generator', role='source', expected_label='Wwise Tone Generator')
            fields = _update_business_draft(gateway, draft, 'draft-discover-fields',
                ['--type-handle', kind, '--meaning', 'Start Frequency', '--meaning', 'Waveform'], live=True)
            start, wave = field(fields, 'Start Frequency', 'StartFreq'), field(fields, 'Waveform', 'WaveType')
            sine, = [row['value'] for row in wave['metadata']['restriction']['values'] if row['displayName'] == 'Sine']
            assert type(sine) is int and 20 <= frequency <= 20000
            receipt['metadata_selection'] = {'frequency': start, 'waveform': wave, 'sine_value': sine}
            _update_business_draft(gateway, draft, 'draft-declare-existing', ['--declaration-id', 'source', '--object-handle', owner,
                '--field', 'plugin_role', 'source', '--field', 'plugin_placement', 'owner', '--field', 'plugin_name', 'Tone' + str(index),
                '--field', 'plugin_type_handle', kind, '--field', 'notes', 'Keep Source ' + str(index),
                '--field-value', start['handle'], str(frequency), '--field-value', wave['handle'], str(sine)], live=False)
            phase = complete(draft, 'source_' + str(index))
            owner_result, = phase['execute']['payload']['dispatch_result']['result']['objects']
            source_result, = owner_result['children']; assert uuid.UUID(owner_result['id']) == uuid.UUID(target_id)
            source = exact(source_result['id'], source=True)
            descriptor = phase['immutable_preview']['prepared_operation']['verification_plan']['descriptor']
            assert source['type'] in {'Source', 'SourcePlugin'} and source['class_id'] == descriptor['class_id'], source
            assert source['parent']['id'] == target_id and source['path'] == target['path'] + '\\Tone' + str(index), source
            assert source['notes'] == 'Keep Source ' + str(index) and source['properties'] == {'StartFreq': frequency, 'WaveType': sine}, source
            assert uuid.UUID(source['id']) not in {uuid.UUID(row['id']) for row in (parent, target, sentinel, *sources)}, 'Source returned a retained GUID'
            for retained in sources: assert exact(retained['id'], source=True) == retained, 'Source setup changed a retained Source'
            sources.append(source); phase['independent_source'] = source
        def preservation():
            current_target = exact(target_id, sound=True)
            return {'sound': preserved_sound(current_target),
                'sources': [exact(row['id'], source=True) for row in sources], 'children': children(target_id),
                'sentinel': exact(sentinel_id, sound=True), 'sentinel_children': children(sentinel_id), 'parent': exact(parent['id'])}, current_target
        before, owner = preservation()
        assert before['sources'] == sources and before['sentinel'] == sentinel and before['parent'] == parent
        assert before['sound'] == preserved_sound(target), 'Source setup changed the original Sound fields'
        assert before['sentinel_children'] == [], 'Source setup changed the unrelated Sound child set'
        assert len(before['children']) == 2 and {uuid.UUID(row['id']) for row in before['children']} == {uuid.UUID(row['id']) for row in sources}, before
        initial = active(owner); assert initial in {str(uuid.UUID(row['id'])) for row in sources}, owner
        selected, = [row for row in sources if str(uuid.UUID(row['id'])) != initial]
        receipt['selection'] = {'before_active_id': initial, 'requested_active_id': str(uuid.UUID(selected['id'])),
            'preserved_before': before, 'platform_scope': 'current_default_view_existing_linkage_no_isolation_claim'}
        draft = _start_business_draft(gateway, 'ak.wwise.core.sound.setActiveSource')
        sound_handle = _bind_business_object(gateway, draft, object_id=target_id, role='sound')
        source_handle = _bind_business_object(gateway, draft, object_id=selected['id'], role='source')
        _update_business_draft(gateway, draft, 'draft-declare-project-setting-plan',
            ['--sound-handle', sound_handle, '--source-handle', source_handle], live=True)
        selection = complete(draft, 'select_other_source')
        args = selection['immutable_preview']['prepared_operation']['dispatch']['args']
        assert args == {'sound': target_id, 'source': selected['id']}, args
        after, owner = preservation(); receipt['selection'].update(preserved_after=after, after_active_id=active(owner))
        assert receipt['selection']['after_active_id'] == receipt['selection']['requested_active_id'] != initial, receipt['selection']
        assert after == before, 'Selection changed preserved Source/owner/sentinel fields or child membership'
        assert hashlib.sha256(config.read_bytes()).hexdigest() == config_hash, 'Source selection configuration changed'
        final = gateway.gateway(['status'], live=True); assert final['wwise'] == status['wwise'], 'Source selection host context changed'
        receipt.update(collection_complete=True, business_effect_verified=True); category['status'] = 'PASS'
        return category
    except Exception as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
        raise
    finally:
        try:
            paths = sorted(set(native_root.glob('*.json')) - previous_native); assert len(paths) <= receipt['limits']['native_files']
            total = 0
            for index, path in enumerate(paths):
                observed = observe_console_file(path, io_root=native_root); raw = base64.b64decode(observed['content_base64'], validate=True)
                total += len(raw); assert total <= receipt['limits']['native_bytes'] and len(raw) <= 4 * 1024 * 1024
                target = artifacts / ('native-' + str(index) + '.json')
                prove_artifact_path(target, io_root=artifacts, field='Source selection archive', expect_directory=False)
                fd = os.open(target, binary_file_open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL) | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                with os.fdopen(fd, 'wb') as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                assert target.read_bytes() == raw
                receipt['native_evidence'].append({'native_path': str(path), 'archive_path': str(target),
                    'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'native_file_proof': observed['file_proof']})
        except Exception as exc:
            receipt.update(collection_complete=False, business_effect_verified=False,
                archive_failure={'type': type(exc).__name__, 'message': str(exc)[:2048]}); category['status'] = 'FAIL'
            raise
        finally:
            persist()


@pytest.mark.live
@pytest.mark.destructive
def test_source_plugin_active_selection_acceptance(workflow_sandbox_runtime: _WorkflowSandboxRuntime) -> None:
    if workflow_sandbox_runtime.version != '2025.1':
        pytest.skip('Initial SourcePlugin A-to-B acceptance is Console2025-only; other setter lanes remain unproven')
    category = _collect_source_plugin_selection_acceptance(workflow_sandbox_runtime, prefix='WAAPI_SRC_SELECT_' + uuid.uuid4().hex[:10])
    assert category['status'] == 'PASS', category
