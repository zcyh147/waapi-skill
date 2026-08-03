from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.schema import validate_semantic_payload  # pyright: ignore[reportMissingImports]
from wwise_waapi.execution_contracts import (  # pyright: ignore[reportMissingImports]
    PROJECT_GUARD_TRANSITION_TO_NONE,
    PROJECT_GUARD_TRANSITION_TO_PATH,
    ExecutionContractRegistry,
)
from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    UNDO_GROUP_INNER_URIS_BY_VERSION,
    parse_operation_request,
)
from wwise_waapi.platform_commands import (  # pyright: ignore[reportMissingImports]
    WINDOWS_POWERSHELL_ENCODED_FAMILY,
    decode_windows_powershell_argv,
    encode_windows_powershell_argv,
)
from wwise_waapi.transactions import TransactionState, TransactionStore


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_transaction_gateway_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


PARENT_GUID = "{22222222-2222-2222-2222-222222222222}"
OBJECT_GUID = "{33333333-3333-3333-3333-333333333333}"
CREATED_GUID = "{44444444-4444-4444-4444-444444444444}"
PROJECT_GUID = "{11111111-1111-1111-1111-111111111111}"
PARENT_PATH = r"\Actor-Mixer Hierarchy\Default Work Unit\WAAPI Sandbox"
OBJECT_PATH = PARENT_PATH + r"\Existing"
COMPACT_TRANSACTION_ID_RE = re.compile(
    r"^tx1-[0123456789abcdefghjkmnpqrstvwxyz]{20}$"
)
CONFIRMATION_TOKEN_RE = re.compile(
    r"^ct1-[0123456789abcdefghjkmnpqrstvwxyz]{24}$"
)
EXPECTED_IMPORT_HIERARCHY_ROOTS = {
    "2021.1": ["Actor-Mixer Hierarchy", "Interactive Music Hierarchy"],
    "2022.1": ["Actor-Mixer Hierarchy", "Interactive Music Hierarchy"],
    "2023.1": ["Actor-Mixer Hierarchy", "Interactive Music Hierarchy"],
    "2024.1": ["Actor-Mixer Hierarchy", "Interactive Music Hierarchy"],
    "2025.1": ["Containers", "Interactive Music Hierarchy"],
}


def expected_transaction_next_command(
    command: str,
    gateway_argv: Sequence[str],
    *,
    requires_explicit_user_confirmation: bool = False,
    requires_later_user_message: bool = False,
) -> dict[str, Any]:
    normalized = [str(value) for value in gateway_argv]
    full_argv = [
        "python",
        str(SCRIPT_PATH.with_name("run.py")),
        "gateway.py",
        *normalized,
    ]
    expected: dict[str, Any] = {
        "contract": "waapi-skill.gateway-next-command/v1",
        "command": command,
        "gateway_argv": normalized,
        "full_argv": full_argv,
        "copy_exactly": True,
    }
    if requires_explicit_user_confirmation:
        expected["requires_explicit_user_confirmation"] = True
    if requires_later_user_message:
        expected["requires_later_user_message"] = True
    if os.name == "nt":
        expected["shell_family"] = WINDOWS_POWERSHELL_ENCODED_FAMILY
        shell_command = encode_windows_powershell_argv(full_argv)
    else:
        expected["shell_family"] = "posix-sh"
        shell_command = shlex.join(full_argv)
    expected["copy_instruction"] = {
        "contract": "waapi-skill.gateway-command-copy-instruction/v1",
        "source_field": "shell_command",
        "action": "execute_verbatim_as_one_shell_tool_call",
        "forbidden_transformations": [
            "reconstruct",
            "shorten",
            "normalize",
            "substitute_path_segments",
        ],
    }
    expected["shell_command"] = shell_command
    return expected


def assert_confirmation_binding(
    payload: Mapping[str, Any],
    *,
    transaction_id: str,
    artifact_hash: str,
    event_sequence: int,
    last_event_hash: str,
) -> str:
    confirmation = payload["confirmation"]
    assert confirmation["contract"] == "waapi-skill.confirmation-binding/v1"
    token = confirmation["token"]
    assert isinstance(token, str)
    assert CONFIRMATION_TOKEN_RE.fullmatch(token)
    assert confirmation["binding"] == {
        "material_contract": "waapi-skill.confirmation-token-material/v1",
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "state": TransactionState.AWAITING_CONFIRMATION.value,
        "event_sequence": event_sequence,
        "last_event_hash": last_event_hash,
    }
    return token


PROJECT_TRANSITION_ROWS = tuple(
    (entry.version, entry.uri, entry.project_guard_mode)
    for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
    for entry in ExecutionContractRegistry().entries(version)
    if entry.uri.startswith(("ak.wwise.ui.project.", "ak.wwise.console.project."))
)


class FakeClient:
    """A thread-safe-enough scripted client for the gateway owner thread."""

    def __init__(
        self,
        responses: Mapping[str, Sequence[Any]],
        *,
        errors: Mapping[str, Sequence[BaseException]] | None = None,
    ) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}
        self.errors = {uri: deque(values) for uri, values in (errors or {}).items()}
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []
        self.call_thread_idents: list[int] = []
        self.disconnected = False

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        self.call_thread_idents.append(threading.get_ident())
        failures = self.errors.get(uri)
        if failures:
            raise failures.popleft()
        values = self.responses.get(uri)
        if not values:
            raise AssertionError(f"Unexpected or exhausted WAAPI call: {uri} args={args!r} options={options!r}")
        return values.popleft()

    def disconnect(self) -> None:
        self.disconnected = True


class WaapiRequestFailed(Exception):
    def __init__(self, uri: str, kwargs: Mapping[str, Any] | None = None) -> None:
        super().__init__("untrusted rendered application error")
        self.uri = uri
        self.kwargs = kwargs


def live_info(*, year: int = 2022, major: int = 1) -> dict[str, Any]:
    return {
        "displayName": "Wwise",
        "isCommandLine": True,
        "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        "processId": 4242,
        "processPath": "/Applications/Audiokinetic/Wwise.app/Contents/MacOS/Wwise",
        "apiVersion": 1,
        "platform": "macosx",
        "configuration": "release",
        "version": {
            "year": year,
            "major": major,
            "minor": 19,
            "build": 8584,
            "displayName": f"v{year}.{major}.19",
        },
    }


def wine_live_info(*, year: int = 2022, major: int = 1) -> dict[str, Any]:
    info = live_info(year=year, major=major)
    info["processPath"] = r"c:\Program Files\Audiokinetic\Wwise\WwiseConsole.exe"
    info["platform"] = "x64"
    return info


def project(
    *,
    project_id: str = PROJECT_GUID,
    name: str = "SampleProject",
    path: str = r"Y:\sandbox\SampleProject.wproj",
) -> dict[str, Any]:
    return {"id": project_id, "name": name, "path": path}


def local_project(tmp_path: Path) -> dict[str, Any]:
    project_path = (tmp_path / "business-host" / "SampleProject.wproj").resolve()
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("<Project/>", encoding="utf-8")
    return project(path=str(project_path))


def z_wire_path(path: Path) -> str:
    resolved = path.resolve()
    return "Z:\\" + "\\".join(resolved.parts[1:])


def test_runtime_state_uses_native_project_containment(tmp_path: Path) -> None:
    project_row = local_project(tmp_path)
    project_root = Path(project_row["path"]).parent

    waapi_gateway.require_runtime_directory_outside_project(
        tmp_path / "transaction-state",
        project=project_row,
    )

    with pytest.raises(
        waapi_gateway.GatewayInputError,
        match="outside the live Wwise project",
    ):
        waapi_gateway.require_runtime_directory_outside_project(
            project_root / ".waapi-skill-state",
            project=project_row,
        )


@pytest.mark.skipif(os.name == "nt", reason="Wine Z: mapping is POSIX-only")
def test_runtime_state_rejects_wine_project_containment(tmp_path: Path) -> None:
    project_root = (tmp_path / "SampleProject").resolve()
    project_root.mkdir()
    project_file = project_root / "SampleProject.wproj"
    project_file.write_text("<Project/>", encoding="utf-8")

    with pytest.raises(
        waapi_gateway.GatewayInputError,
        match="outside the live Wwise project",
    ):
        waapi_gateway.require_runtime_directory_outside_project(
            project_root / ".waapi-skill-state",
            project={"path": "\\", "filePath": z_wire_path(project_file)},
        )


def test_2021_current_project_requests_filesystem_path(tmp_path: Path) -> None:
    project_row = {
        "id": PROJECT_GUID,
        "name": "SampleProject",
        "type": "Project",
        "path": "\\",
        "filePath": r"Y:\sandbox\SampleProject.wproj",
    }
    client = FakeClient(
        {"ak.wwise.core.object.get": [{"return": [project_row]}]}
    )
    dispatcher = waapi_gateway.WwiseDispatcher(client=client)

    observed, _call = waapi_gateway.current_project(
        dispatcher,
        connection=waapi_gateway.GatewayConnection(
            host="127.0.0.1",
            port=8080,
            version_hint="2021.1",
            evidence_dir=tmp_path / "evidence",
            timeout=10.0,
            deadline=waapi_gateway.GatewayDeadline.start(10.0),
        ),
        version="2021.1",
    )

    assert observed == project_row
    assert client.calls == [
        (
            "ak.wwise.core.object.get",
            {"waql": "from type Project take 1"},
            {"return": ["id", "name", "type", "path", "filePath"]},
        )
    ]


def parent_row() -> dict[str, Any]:
    return {
        "id": PARENT_GUID,
        "name": "WAAPI Sandbox",
        "type": "WorkUnit",
        "path": PARENT_PATH,
        "parent": {"id": "{actor-mixer-hierarchy}"},
        "notes": "",
    }


def object_row(*, path: str = OBJECT_PATH, notes: str = "before") -> dict[str, Any]:
    return {
        "id": OBJECT_GUID,
        "name": path.rsplit("\\", 1)[-1],
        "type": "Sound",
        "path": path,
        "parent": {"id": PARENT_GUID},
        "notes": notes,
    }


def created_row() -> dict[str, Any]:
    return {
        "id": CREATED_GUID,
        "name": "CreatedByGateway",
        "type": "PropertyContainer",
        "path": PARENT_PATH + r"\CreatedByGateway",
        "parent": {"id": PARENT_GUID},
        "notes": "created in transaction test",
    }


def create_type_catalog() -> dict[str, Any]:
    return {"return": [{"classId": 1, "name": "ActorMixer", "type": "ActorMixer"}]}


def create_preview_object_reads() -> list[dict[str, Any]]:
    return [
        {"return": [parent_row()]},
        {"return": []},
        {"return": []},
    ]


def create_request() -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.create",
        "arguments": {
            "parent": {"kind": "id", "value": PARENT_GUID},
            "type": "ActorMixer",
            "name": "CreatedByGateway",
            "notes": "created in transaction test",
        },
    }


def set_notes_request() -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.setNotes",
        "arguments": {
            "object": {"kind": "id", "value": OBJECT_GUID},
            "value": "after",
        },
    }


def generic_manifest_call_request() -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.core.project.save",
            "args": {},
            "options": {},
        },
    }


def generic_read_transaction_call_request() -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.core.remote.getAvailableConsoles",
            "args": {},
            "options": {},
        },
    }


def generic_public_call_request(
    api: str,
    args: Mapping[str, Any],
    *,
    version: str = "2025.1",
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": api,
            "args": dict(args),
            "options": {},
        },
    }


def generic_isolated_call_request(io_root: Path) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2023.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.debug.generateToneWAV",
            "args": {"path": str(io_root / "tone.wav")},
            "options": {},
            "io_root": str(io_root),
        },
    }


def convert_external_source_call_request(io_root: Path) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.cli.convertExternalSource",
            "args": {
                "project": str(io_root / "project" / "SampleProject.wproj"),
                "platform": ["Windows"],
                "source-file": str(io_root / "assets" / "delivery.wsources"),
                "output": str(io_root / "output"),
            },
            "options": {},
            "io_root": str(io_root),
        },
    }


def soundbank_convert_external_sources_request(io_root: Path) -> dict[str, Any]:
    project_root = io_root / "project"
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "soundbank.convertExternalSources",
        "arguments": {
            "sources": [
                {
                    "input": str(project_root / "external.wsources"),
                    "platform": "Mac",
                    "output": str(io_root / "external-output"),
                }
            ],
            "io_root": str(io_root),
        },
    }


def soundbank_project_info(io_root: Path, *, wine_paths: bool) -> dict[str, Any]:
    project_root = io_root / "project"

    def wire(path: Path) -> str:
        return z_wire_path(path) if wine_paths else str(path)

    return {
        "name": "SampleProject",
        "displayTitle": "SampleProject - Wwise",
        "path": wire(project_root / "SampleProject.wproj"),
        "id": PROJECT_GUID,
        "isDirty": False,
        "currentLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
        "referenceLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
        "languages": [
            {
                "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "name": "English(US)",
                "shortId": 1,
            }
        ],
        "currentPlatformId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        "platforms": [
            {
                "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "name": "Mac",
                "baseName": "Mac",
                "baseDisplayName": "Mac",
                "soundBankPath": wire(io_root / "soundbanks" / "Mac"),
                "copiedMediaPath": wire(io_root / "soundbanks" / "Mac" / "Media"),
            }
        ],
        "defaultConversion": {
            "id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}",
            "name": "PCM",
        },
        "directories": {
            "root": wire(project_root),
            "cache": wire(io_root / "cache"),
            "originals": wire(project_root / "Originals"),
            "soundBankOutputRoot": wire(io_root / "soundbanks"),
            "commands": wire(project_root / "Add-ons" / "Commands"),
            "properties": wire(project_root / "Add-ons" / "Properties"),
        },
    }


def generate_soundbank_call_request(io_root: Path) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.cli.generateSoundbank",
            "args": {
                "project": str(io_root / "SampleProject.wproj"),
                "bank": "Main",
                "platform": ["Windows"],
                "soundbank-path": ["Windows", str(io_root / "GeneratedSoundBanks")],
                "cache": str(io_root / ".cache"),
                "root-output-path": str(io_root),
            },
            "options": {},
            "io_root": str(io_root),
        },
    }


def tab_delimited_import_call_request(io_root: Path) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.cli.tabDelimitedImport",
            "args": {
                "project": str(io_root / "SampleProject.wproj"),
                "tab-delimited-import-file": str(io_root / "dialogue.tsv"),
                "tab-delimited-operation": "useExisting",
                "import-language": "Japanese",
            },
            "options": {},
            "io_root": str(io_root),
        },
    }


def migrate_call_request(io_root: Path) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.cli.migrate",
            "args": {"project": str(io_root / "SampleProject.wproj")},
            "options": {},
            "io_root": str(io_root),
        },
    }


def undo_group_request(*, version: str = "2023.1") -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.undoGroup",
        "arguments": {
            "display_name": "Program Undo Group",
            "calls": [
                {
                    "api": "ak.wwise.core.object.setNotes",
                    "args": {"object": OBJECT_GUID, "value": "after"},
                    "options": {},
                }
            ],
        },
    }


def preview_and_confirm_undo_group(*, tmp_path: Path, state_dir: Path) -> dict[str, Any]:
    transaction = preview(
        undo_group_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2023)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    return transaction


def gateway_env(
    tmp_path: Path,
    *,
    state_dir: Path | None = None,
    version: str = "2022.1",
    port: int = 31337,
    policy: str = "ask_before_changes",
) -> dict[str, str]:
    config_path = tmp_path / "config" / "config.json"
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "wwise_version": None,
                    "waapi_host": "127.0.0.1",
                    "waapi_port": None,
                    "project_modification_policy": policy,
                }
            ),
            encoding="utf-8",
        )
    result = {
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": str(port),
        "WWISE_VERSION": version,
        "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence"),
    }
    if state_dir is not None:
        result["WAAPI_SKILL_STATE_DIR"] = str(state_dir)
    return result


def write_gateway_policy(tmp_path: Path, policy: str) -> None:
    config_path = Path(gateway_env(tmp_path)["WAAPI_SKILL_CONFIG_PATH"])
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["project_modification_policy"] = policy
    config_path.write_text(json.dumps(payload), encoding="utf-8")


def execute(
    argv: Sequence[str],
    *,
    tmp_path: Path,
    state_dir: Path | None = None,
    env_state_dir: bool = False,
    client: FakeClient | None = None,
    version: str = "2022.1",
    port: int = 31337,
    policy: str = "ask_before_changes",
) -> tuple[int, dict[str, Any]]:
    arguments = list(argv)
    if state_dir is not None and not env_state_dir:
        arguments = ["--state-dir", str(state_dir), *arguments]
    env = gateway_env(
        tmp_path,
        state_dir=state_dir if env_state_dir else None,
        version=version,
        port=port,
        policy=policy,
    )

    def factory(url: str) -> FakeClient:
        if client is None:
            raise AssertionError(f"Offline transaction command unexpectedly connected to {url}")
        return client

    return waapi_gateway.execute_gateway(arguments, env=env, client_factory=factory)


def preview(
    request: Mapping[str, Any],
    *,
    tmp_path: Path,
    state_dir: Path,
    client: FakeClient,
    ttl: int = 300,
    apply: bool = False,
    policy: str = "ask_before_changes",
) -> dict[str, Any]:
    arguments = ["preview"]
    if apply:
        arguments.append("--apply")
    arguments.extend(
        ["--request-json", json.dumps(request), "--ttl", str(ttl)]
    )
    exit_code, payload = execute(
        arguments,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
        version=str(request.get("version", "2022.1")),
        policy=policy,
    )
    assert exit_code == 0, payload
    assert payload["ok"] is True
    policy_authorized = apply and policy == "allow_changes"
    expected_state = (
        TransactionState.POLICY_AUTHORIZED
        if policy_authorized
        else TransactionState.AWAITING_CONFIRMATION
    )
    assert payload["state"] == expected_state.value
    assert payload["change_requested"] is apply
    assert isinstance(payload["transaction_id"], str) and payload["transaction_id"]
    assert COMPACT_TRANSACTION_ID_RE.fullmatch(payload["transaction_id"])
    assert isinstance(payload["artifact_hash"], str) and len(payload["artifact_hash"]) == 64
    assert isinstance(payload["preview_summary"], Mapping)
    if policy_authorized:
        assert payload["next_command"] == expected_transaction_next_command(
            "execute",
            ["execute", payload["transaction_id"]],
        )
    else:
        assert payload["next_command"] == expected_transaction_next_command(
            "transaction-show",
            ["transaction-show", payload["transaction_id"], "--summary-only"],
            requires_later_user_message=True,
        )
    assert list(payload).index("session_context") < list(payload).index("next_command")
    assert list(payload).index("next_command") < list(payload).index("agent_result")
    assert payload["agent_result"]["next_command"] == payload["next_command"]
    assert list(payload["agent_result"])[-1] == "next_command"
    return payload


def confirm(
    transaction_id: str,
    artifact_hash: str,
    *,
    tmp_path: Path,
    state_dir: Path,
) -> dict[str, Any]:
    exit_code, payload = execute(
        ["confirm", transaction_id, "--artifact-hash", artifact_hash],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    assert exit_code == 0, payload
    assert payload["state"] == TransactionState.CONFIRMED.value
    assert payload["next_command"] == expected_transaction_next_command(
        "execute",
        ["execute", transaction_id],
    )
    assert list(payload)[-1] == "next_command"
    return payload


def test_debug_test_crash_is_confirmed_dispatched_once_and_terminal_indeterminate(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "debug.testCrash",
        "arguments": {"acknowledge": "crash_wwise_process"},
    }
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.debug.testCrash": [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["status"] == "expected_disconnect_indeterminate"
    assert payload["state"] == TransactionState.INDETERMINATE.value
    assert payload["expected_disconnect"] is True
    assert payload["dispatch_delivery"] == "waapi_result_returned"
    assert payload["dispatch_accepted"] is True
    assert payload["process_lifecycle"] == {
        "expected": "wwise_process_termination",
        "observed": "not_observed_by_gateway",
        "gateway_process_action": "none",
        "reconnect_attempted": False,
    }
    assert payload["automatic_retry"] is False
    assert payload["reconnect_attempted"] is False
    assert payload["generic_verify_allowed"] is False
    assert "next_command" not in payload
    assert [call[0] for call in client.calls].count(
        "ak.wwise.debug.testCrash"
    ) == 1


def test_allow_changes_keeps_dangerous_host_control_on_confirmation_path(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "debug.testCrash",
        "arguments": {"acknowledge": "crash_wwise_process"},
    }

    exit_code, payload = execute(
        [
            "preview",
            "--apply",
            "--request-json",
            json.dumps(request),
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
        policy="allow_changes",
    )

    assert exit_code == 0, payload
    assert payload["state"] == TransactionState.AWAITING_CONFIRMATION.value
    assert payload["authorization"] == {
        "mode": "explicit_confirmation",
        "policy": "allow_changes",
        "explicit_confirmation": False,
        "notice_required": True,
        "requires_later_user_message": True,
        "reason": "dangerous_host_control_requires_confirmation",
    }
    assert payload["next_command"] == expected_transaction_next_command(
        "transaction-show",
        [
            "transaction-show",
            payload["transaction_id"],
            "--summary-only",
        ],
        requires_later_user_message=True,
    )
    assert [
        event["event_type"]
        for event in TransactionStore(state_dir).read_events(
            payload["transaction_id"]
        )
    ] == ["preview_created", "confirmation_requested"]


def preview_and_confirm_public_call(
    request: Mapping[str, Any],
    *,
    tmp_path: Path,
    state_dir: Path,
) -> dict[str, Any]:
    version = str(request["version"])
    year = int(version.split(".", 1)[0])
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=year)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    return transaction


def execute_set_notes_successfully(*, tmp_path: Path, state_dir: Path) -> dict[str, Any]:
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
        }
    )
    transaction = preview(set_notes_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    confirm(transaction["transaction_id"], transaction["artifact_hash"], tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
            "ak.wwise.core.object.setNotes": [{}],
        }
    )
    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )
    assert exit_code == 0, payload
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    return transaction


def execute_generate_soundbank_successfully(
    *,
    tmp_path: Path,
    state_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], FakeClient, FakeClient]:
    io_root = (tmp_path / "soundbank-io").resolve()
    request = generate_soundbank_call_request(io_root)
    active_project = local_project(tmp_path)
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [active_project],
        }
    )
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [active_project],
            "ak.wwise.cli.generateSoundbank": [{"result": 0}],
        }
    )
    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )
    assert exit_code == 0, payload
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    return transaction, request, preview_client, execute_client


def execute_tab_delimited_import_successfully(
    *,
    tmp_path: Path,
    state_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], FakeClient, FakeClient]:
    io_root = (tmp_path / "tab-import-io").resolve()
    io_root.mkdir()
    (io_root / "dialogue.tsv").write_text(
        "Audio File\tObject Path\n",
        encoding="utf-8",
    )
    request = tab_delimited_import_call_request(io_root)
    active_project = local_project(tmp_path)
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [active_project],
        }
    )
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [active_project],
            "ak.wwise.cli.tabDelimitedImport": [{"result": 2}],
        }
    )
    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )
    assert exit_code == 0, payload
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    return transaction, request, preview_client, execute_client


def execute_convert_external_source_successfully(
    *,
    tmp_path: Path,
    state_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], FakeClient, FakeClient]:
    io_root = (tmp_path / "convert-external-source-io").resolve()
    target_project = io_root / "project" / "SampleProject.wproj"
    target_project.parent.mkdir(parents=True)
    target_project.write_text("<Project/>", encoding="utf-8")
    manifest = io_root / "assets" / "delivery.wsources"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("<ExternalSourcesList/>", encoding="utf-8")
    (io_root / "output").mkdir(parents=True)
    request = convert_external_source_call_request(io_root)
    active_project = local_project(tmp_path)
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [active_project],
        }
    )
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [active_project],
            "ak.wwise.cli.convertExternalSource": [{"result": 2}],
        }
    )
    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )
    assert exit_code == 0, payload
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    return transaction, request, preview_client, execute_client


def execute_migrate_successfully(
    *,
    tmp_path: Path,
    state_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], FakeClient, FakeClient]:
    io_root = (tmp_path / "migrate-io").resolve()
    io_root.mkdir()
    (io_root / "SampleProject.wproj").write_text("<Project/>", encoding="utf-8")
    request = migrate_call_request(io_root)
    active_project = local_project(tmp_path)
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [active_project],
        }
    )
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [active_project],
            "ak.wwise.cli.migrate": [{"result": 0}],
        }
    )
    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )
    assert exit_code == 0, payload
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert "next_command" not in payload
    return transaction, request, preview_client, execute_client


def test_operations_and_operation_schema_are_offline_closed_contracts(tmp_path: Path) -> None:
    exit_code, catalog = execute(["operations"], tmp_path=tmp_path)

    assert exit_code == 0
    assert catalog["ok"] is True
    assert catalog["offline"] is True
    operations = {item["name"]: item for item in catalog["operations"]}
    assert set(operations["object.create"]) == {
        "name",
        "uri",
        "family",
        "summary",
        "implemented",
        "boundary",
        "supported_versions",
        "required_arguments",
        "optional_arguments",
    }
    assert operations["object.create"]["implemented"] is True
    assert operations["object.copy"]["implemented"] is False
    assert "returned copy GUID" in operations["object.copy"]["boundary"]
    assert "argument_contract" not in operations["object.create"]
    assert operations["ui.commands.execute"]["implemented"] is True
    assert operations["ui.commands.register"]["implemented"] is True
    assert operations["ui.commands.unregister"]["implemented"] is True
    compact_json = json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    assert len(compact_json) < 24_000

    exit_code, detail_catalog = execute(["operations", "--detail"], tmp_path=tmp_path)

    assert exit_code == 0
    detailed = {item["name"]: item for item in detail_catalog["operations"]}
    assert detailed["object.create"]["additional_properties"] is False
    assert "argument_contract" in detailed["object.create"]
    assert "constraints" in detailed["object.create"]
    assert "identity_contract" in detailed["object.create"]

    exit_code, schema = execute(["operation-schema", "object.setNotes"], tmp_path=tmp_path)

    assert exit_code == 0
    assert schema["ok"] is True
    assert schema["offline"] is True
    assert schema["operation"]["name"] == "object.setNotes"
    assert schema["operation"]["required_arguments"] == ["object", "value"]
    assert schema["operation"]["additional_properties"] is False
    assert "argument_contract" in schema["operation"]
    assert "identity_contract" in schema["operation"]
    assert schema["operation"]["selection_guidance"]["use_when"] == [
        "Exactly one existing object receives only a notes change."
    ]
    assert schema["operation"]["selection_guidance"]["preferred_over"] == [
        {
            "target": "object.set",
            "when": "the request is only one isolated notes edit",
        }
    ]
    assert schema["request_envelope"] == {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.setNotes",
        "arguments": {},
    }
    assert schema["request_envelope_policy"] == {
        "status": "ready",
        "required_top_level_keys": [
            "contract",
            "version",
            "operation",
            "arguments",
        ],
        "copy_top_level_exactly": True,
        "replace_only": "arguments",
        "argument_container_path": "$.arguments",
        "argument_paths": {
            "object": "$.arguments.object",
            "value": "$.arguments.value",
        },
        "shell_transport": {
            "outer_quoting": "single_quote_entire_compact_json",
            "json_string_serialization": "exactly_once",
            "decoded_value_rules": {
                "embedded_quotes": (
                    "ordinary quotation marks with no preceding backslash"
                ),
                "wwise_path_separator": "one backslash",
            },
            "forbidden": [
                "double_escape_json_string_contents",
                "leave_json_escape_backslashes_in_decoded_values",
                "repair_or_retry_invalid_json_in_the_same_turn",
            ],
        },
        "preview_invocation": {
            "intended_change": {
                "subcommand": "preview",
                "required_flag": "--apply",
                "effect": (
                    "required even when the user asks to see only a preview; "
                    "creates a durable confirmation-bound preview and does not "
                    "execute the change"
                ),
                "includes_later_ordered_transactions": True,
            },
            "omit_apply_only_when": [
                "hypothetical",
                "design_only",
                "explicitly_non_executable",
            ],
        },
    }

    for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"):
        exit_code, versioned = execute(
            ["operation-schema", "object.setNotes"],
            tmp_path=tmp_path,
            version=version,
        )
        assert exit_code == 0
        assert versioned["request_envelope"]["version"] == version

    exit_code, raw_call = execute(
        ["operation-schema", "waapi.call"],
        tmp_path=tmp_path,
        version="2022.1",
    )
    assert exit_code == 0
    assert raw_call["request_envelope_policy"]["argument_paths"] == {
        "api": "$.arguments.api",
        "args": "$.arguments.args",
        "options": "$.arguments.options",
        "io_root": "$.arguments.io_root",
    }
    raw_properties = raw_call["operation"]["argument_contract"]["properties"]
    assert "never place io_root" in raw_properties["args"]["description"]
    assert "must never be nested inside args" in raw_properties["io_root"]["description"]

    exit_code, unsupported = execute(
        ["operation-schema", "object.set"],
        tmp_path=tmp_path,
        version="2021.1",
    )
    assert exit_code == 0
    assert unsupported["request_envelope"] is None
    assert unsupported["request_envelope_policy"]["status"] == "unsupported_version"


def test_operation_schema_exposes_tab_import_path_only_progression(
    tmp_path: Path,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "audio.importTabDelimited"],
        tmp_path=tmp_path,
        version="2025.1",
    )

    assert exit_code == 0
    assert payload["offline"] is True
    assert payload["request_envelope"] == {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2025.1",
        "operation": "audio.importTabDelimited",
        "arguments": {},
    }
    operation = payload["operation"]
    assert operation["file_read_policy"] == "pass_path_without_reading"
    assert operation["next_step"] == "preview"
    assert operation["preview_owns"] == [
        "tsv_parsing",
        "tsv_hash_validation",
        "inline_base64_validation",
        "media_validation",
        "exact_path_conflict_validation",
    ]


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_soundbank_inclusion_schema_exposes_one_scoped_replace_for_complete_post_state(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "soundbank.setInclusions"],
        tmp_path=tmp_path,
        version=version,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    operation = payload["operation"]
    assert operation["constraints"][0] == (
        "replace is one transaction scoped only to the selected SoundBank: "
        "submit its complete desired post-state; omitted existing rows are "
        "removed without naming them, every other SoundBank is unaffected, "
        "and the list may be empty"
    )
    assert operation["selection_guidance"]["use_when"][1] == (
        "The user gives one SoundBank's complete desired final inclusion set "
        "and asks to remove Debug or any other omitted rows; use one replace "
        "transaction and never split that final-state request into add and "
        "remove transactions."
    )


@pytest.mark.parametrize("version", tuple(UNDO_GROUP_INNER_URIS_BY_VERSION))
def test_operation_schema_discloses_exact_undo_inner_contracts_offline(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "waapi.undoGroup"],
        tmp_path=tmp_path,
        version=version,
    )

    assert exit_code == 0
    api_schema = payload["operation"]["argument_contract"]["properties"][
        "calls"
    ]["items"]["properties"]["api"]
    expected = sorted(UNDO_GROUP_INNER_URIS_BY_VERSION[version])
    assert api_schema["enum"] == expected
    assert [row["const"] for row in api_schema["value_contracts"]] == expected
    assert all(
        row["schema_pointer"]["gateway_argv"]
        == ["--version", version, "describe", row["const"], "--full-schema"]
        for row in api_schema["value_contracts"]
    )


@pytest.mark.parametrize(
    "operation",
    ("ui.commands.register", "ui.commands.unregister"),
)
def test_operation_schema_exposes_closed_ui_command_items(
    tmp_path: Path,
    operation: str,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", operation],
        tmp_path=tmp_path,
        version="2024.1",
    )

    assert exit_code == 0
    item = payload["operation"]["argument_contract"]["properties"]["commands"][
        "items"
    ]
    assert item["additionalProperties"] is False
    assert item["required"] == ["id", "display_name", "handler"]
    handlers = {
        branch["properties"]["kind"]["const"]: branch
        for branch in item["properties"]["handler"]["oneOf"]
    }
    assert set(handlers) == {"notification", "program", "lua_script"}
    assert all(
        branch["additionalProperties"] is False
        for branch in handlers.values()
    )
    assert item["properties"]["context_menu"]["required"] == []
    assert item["properties"]["context_menu"]["optional"] == [
        "base_path",
        "enabled_for",
        "visible_for",
    ]
    assert item["properties"]["main_menu"]["required"] == ["base_path"]


@pytest.mark.parametrize(
    ("version", "expected_roots"),
    EXPECTED_IMPORT_HIERARCHY_ROOTS.items(),
)
def test_audio_import_operation_schema_discloses_versioned_hierarchy_roots(
    tmp_path: Path,
    version: str,
    expected_roots: list[str],
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "audio.import"],
        tmp_path=tmp_path,
        version=version,
    )

    assert exit_code == 0
    assert payload["offline"] is True
    assert payload["request_envelope"]["version"] == version
    properties = payload["operation"]["argument_contract"]["properties"]
    row_path_contract = properties["imports"]["items"]["properties"][
        "object_path"
    ]["path_contract"]
    default_path_contract = properties["defaults"]["properties"]["object_path"][
        "path_contract"
    ]
    row_object_type = properties["imports"]["items"]["properties"][
        "object_type"
    ]
    default_object_type = properties["defaults"]["properties"]["object_type"]
    row_switch_assignment = properties["imports"]["items"]["properties"][
        "switch_assignment"
    ]
    default_switch_assignment = properties["defaults"]["properties"][
        "switch_assignment"
    ]
    assert row_path_contract["contract"] == (
        "waapi-skill.audio-import-object-path/v1"
    )
    assert row_path_contract["resolved_target"] == {
        "minimum_segments": 3,
        "hierarchy_root_case_sensitive": True,
        "wwise_version": version,
        "allowed_hierarchy_roots": expected_roots,
    }
    assert row_path_contract["import_location_selection"] == {
        "wire_significant": True,
        "absolute_object_path": {
            "ordinary_action": "omit",
            "infer_from_common_parent": False,
            "include_only_when_user_explicitly_requests_native_field": True,
        },
        "relative_object_path": {
            "requires_effective_import_location": True,
            "effective_sources": [
                "$.arguments.imports[].import_location",
                "$.arguments.defaults.import_location",
            ],
        },
    }
    assert default_path_contract == row_path_contract
    assert row_object_type == default_object_type
    assert "Random Container / 随机容器 -> RandomSequenceContainer" in (
        row_object_type["description"]
    )
    assert "never RandomContainer" in row_object_type["description"]
    assert "Sound SFX / SFX 声音 -> Sound SFX" in row_object_type["description"]
    assert row_switch_assignment == default_switch_assignment
    assert "native Wwise Switch Assignation import directive" in (
        row_switch_assignment["description"]
    )
    assert "exact Switch/State value name" in row_switch_assignment["description"]
    assert "for example, Snow" in row_switch_assignment["description"]
    assert "do not pass the value object's path" in (
        row_switch_assignment["description"]
    )
    inline_audio = properties["imports"]["items"]["properties"][
        "audio_file_base64"
    ]
    assert inline_audio["verbatim_contract"]["contract"] == (
        "waapi-skill.audio-file-base64-verbatim/v1"
    )
    assert inline_audio["verbatim_contract"][
        "caller_provided_complete_value"
    ] == "copy_character_for_character"
    assert inline_audio["verbatim_contract"][
        "on_unreliable_preservation"
    ] == "stop_before_preview"
    import_operation = properties["import_operation"]
    assert import_operation["default"] == "createNew"
    assert "$.arguments.import_operation" in import_operation["description"]
    assert "Never place it inside an imports[] row" in import_operation["description"]


@pytest.mark.parametrize(
    ("version", "default_work_unit_path", "actor_mixer_type"),
    (
        (
            "2021.1",
            r"\Actor-Mixer Hierarchy\Default Work Unit",
            "ActorMixer",
        ),
        (
            "2022.1",
            r"\Actor-Mixer Hierarchy\Default Work Unit",
            "ActorMixer",
        ),
        (
            "2023.1",
            r"\Actor-Mixer Hierarchy\Default Work Unit",
            "ActorMixer",
        ),
        (
            "2024.1",
            r"\Actor-Mixer Hierarchy\Default Work Unit",
            "ActorMixer",
        ),
        ("2025.1", r"\Containers\Default Work Unit", "PropertyContainer"),
    ),
)
def test_object_create_operation_schema_discloses_versioned_parent_and_merge_contracts(
    tmp_path: Path,
    version: str,
    default_work_unit_path: str,
    actor_mixer_type: str,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "object.create"],
        tmp_path=tmp_path,
        version=version,
    )

    assert exit_code == 0
    contract = payload["operation"]["argument_contract"][
        "same_name_merge_path_contract"
    ]
    assert contract["resolved_target"] == {
        "wwise_version": version,
        "default_container_work_unit_path": default_work_unit_path,
    }
    assert contract["identity_query"] == {
        "route": "query-object",
        "must_follow_operation_schema_directly": True,
        "path_mode": "exact",
        "return_fields": ["id", "name", "type", "path"],
        "path_argument_contract": {
            "contract": "waapi-skill.shell-single-quoted-wwise-path/v1",
            "source_value": "decoded_gateway_json_string",
            "shell_quoting": "single_quotes",
            "literal_backslashes_per_path_separator": 1,
            "json_serialized_backslashes_per_path_separator": 2,
            "copy_json_escape_backslashes_as_literal_characters": False,
        },
    }
    assert contract["forbidden_intermediate_routes"] == [
        "project-default-work-units"
    ]
    parent_contract = payload["operation"]["argument_contract"][
        "default_container_parent_contract"
    ]
    assert parent_contract["resolved_target"] == {
        "wwise_version": version,
        "default_container_work_unit_path": default_work_unit_path,
    }
    assert parent_contract["dynamic_actor_mixer_metadata_scope"] == {
        "kind": "object_type",
        "one_discovery_for_same_type_targets": True,
        "object_scope_is_for_one_existing_target_only": True,
        "wwise_version": version,
        "actor_mixer_object_type": actor_mixer_type,
    }
    assert parent_contract["required_sequence"] == [
        "operation-schema object.create",
        "one metadata discover when a dynamic field token is unknown",
        "preview",
    ]
    assert parent_contract["forbidden_intermediate_routes"] == [
        "project-default-work-units"
    ]


@pytest.mark.parametrize(
    ("version", "default_work_unit_path", "actor_mixer_type"),
    (
        (
            "2021.1",
            r"\Actor-Mixer Hierarchy\Default Work Unit",
            "ActorMixer",
        ),
        (
            "2022.1",
            r"\Actor-Mixer Hierarchy\Default Work Unit",
            "ActorMixer",
        ),
        (
            "2023.1",
            r"\Actor-Mixer Hierarchy\Default Work Unit",
            "ActorMixer",
        ),
        (
            "2024.1",
            r"\Actor-Mixer Hierarchy\Default Work Unit",
            "ActorMixer",
        ),
        ("2025.1", r"\Containers\Default Work Unit", "PropertyContainer"),
    ),
)
def test_object_set_operation_schema_discloses_versioned_target_and_metadata_scope(
    tmp_path: Path,
    version: str,
    default_work_unit_path: str,
    actor_mixer_type: str,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "object.set"],
        tmp_path=tmp_path,
        version=version,
    )

    assert exit_code == 0
    contract = payload["operation"]["argument_contract"][
        "default_container_target_contract"
    ]
    assert contract["resolved_target"] == {
        "wwise_version": version,
        "default_container_work_unit_path": default_work_unit_path,
    }
    assert contract["dynamic_actor_mixer_metadata_scope"][
        "actor_mixer_object_type"
    ] == actor_mixer_type
    assert contract["dynamic_actor_mixer_metadata_scope"]["kind"] == "object_type"
    assert contract["forbidden_intermediate_routes"] == [
        "project-default-work-units"
    ]
    on_name_conflict = payload["operation"]["argument_contract"]["properties"][
        "on_name_conflict"
    ]
    assert on_name_conflict["default"] == "fail"
    assert "Omission defaults to fail" in on_name_conflict["description"]


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_object_set_schema_maps_live_query_accessors_to_canonical_mutation_tokens(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "object.set"],
        tmp_path=tmp_path,
        version=version,
    )

    assert exit_code == 0
    fields = payload["operation"]["argument_contract"]["properties"][
        "objects"
    ]["items"]["properties"]
    property_name = fields["properties"]["items"]["properties"]["name"]
    reference_name = fields["references"]["items"]["properties"]["name"]

    assert property_name["pattern"] == r"^[:_a-zA-Z0-9]+$"
    assert property_name["live_query_accessor_mapping"] == {
        "source": "successful_live_query_in_this_conversation",
        "query": "@Foo",
        "mutation": "Foo",
        "transform": "remove_exactly_one_leading_at",
        "guessing": False,
    }
    assert "submit Foo by removing exactly one leading @" in property_name["description"]
    assert reference_name["live_query_accessor_mapping"] == {
        "source": "successful_live_query_in_this_conversation",
        "query": "OutputBus",
        "mutation": "OutputBus",
        "transform": "copy_exactly",
        "guessing": False,
    }
    assert "OutputBus remains OutputBus" in reference_name["description"]


@pytest.mark.parametrize(
    "version",
    ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"],
)
def test_soundbank_generate_operation_schema_closes_batch_language_scope(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "soundbank.generate"],
        tmp_path=tmp_path,
        version=version,
    )

    assert exit_code == 0
    properties = payload["operation"]["argument_contract"]["properties"]
    row_expectation = properties["soundbanks"]["items"]["properties"][
        "artifact_expectation"
    ]
    row_rebuild = properties["soundbanks"]["items"]["properties"]["rebuild"]
    batch_rebuild = properties["rebuild_soundbanks"]

    assert "batch-level rule" in row_expectation["description"]
    assert "Omit when every SoundBank" in properties["languages"]["description"]
    assert "SFX is not a localized language" in properties["languages"][
        "description"
    ]
    assert "true exactly when every SoundBank is nonlocalized" in properties[
        "skip_languages"
    ]["description"]
    assert row_rebuild["default"] is False
    assert batch_rebuild["default"] is False
    assert properties["clear_audio_file_cache"]["default"] is False
    assert properties["rebuild_init_bank"]["default"] is False
    assert "Per-SoundBank rebuild control" in row_rebuild["description"]
    assert "separate batch-level control" in row_rebuild["description"]
    assert "independent from soundbanks[].rebuild" in batch_rebuild[
        "description"
    ]
    assert any(
        "batch-level rebuild_soundbanks and per-Bank soundbanks[].rebuild are independent"
        in constraint
        for constraint in payload["operation"]["constraints"]
    )
    assert any(
        "language selection is batch-wide" in constraint
        and "never SFX" in constraint
        for constraint in payload["operation"]["constraints"]
    )
    assert payload["request_envelope_policy"]["preview_invocation"] == {
        "intended_change": {
            "subcommand": "preview",
            "required_flag": "--apply",
            "effect": (
                "required even when the user asks to see only a preview; "
                "creates a durable confirmation-bound preview and does not "
                "execute the change"
            ),
            "includes_later_ordered_transactions": True,
        },
        "omit_apply_only_when": [
            "hypothetical",
            "design_only",
            "explicitly_non_executable",
        ],
    }


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_operation_schema_owns_exact_audio_convert_fast_route_contract(
    tmp_path: Path,
    version: str,
) -> None:
    factory_calls: list[str] = []

    def fail_if_connected(url: str) -> FakeClient:
        factory_calls.append(url)
        raise AssertionError(f"offline operation-schema connected to {url}")

    env = gateway_env(tmp_path, version=version)
    exit_code, payload = waapi_gateway.execute_gateway(
        ["operation-schema", "waapi.call"],
        env=env,
        client_factory=fail_if_connected,
    )

    assert exit_code == 0
    assert factory_calls == []
    assert payload["offline"] is True
    assert payload["direct_fast_route_contract"] == {
        "contract": "waapi-skill.operation-schema-direct-fast-route/v1",
        "scope": {
            "operation": "waapi.call",
            "version": version,
            "exact_api": "ak.wwise.core.audio.convert",
            "activation": "exact_api_intent_only",
            "applies_to_other_waapi_call_uris": False,
        },
        "canonical_request_template": {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": version,
            "operation": "waapi.call",
            "arguments": {
                "api": "ak.wwise.core.audio.convert",
                "args": {
                    "objects": ["<exact-wwise-object-path>"],
                    "platforms": ["<platform>"],
                    "languages": ["SFX"],
                },
                "options": {},
                "io_root": "<absolute-allowed-conversion-root>",
            },
        },
        "template_policy": {
            "copy_outer_shape_exactly": True,
            "replace_only": [
                "$.arguments.args.objects",
                "$.arguments.args.platforms",
                "$.arguments.args.languages",
                "$.arguments.io_root",
            ],
            "array_replacement": {
                "paths": [
                    "$.arguments.args.objects",
                    "$.arguments.args.platforms",
                    "$.arguments.args.languages",
                ],
                "replace_entire_array": True,
                "non_empty": True,
                "preserve_user_order": True,
            },
            "placeholders_must_all_be_replaced": True,
            "missing_or_ambiguous_input": "ask_before_preview",
        },
        "rules": {
            "required_ordered_string_arrays": {
                "paths": [
                    "$.arguments.args.objects",
                    "$.arguments.args.platforms",
                    "$.arguments.args.languages",
                ],
                "min_items": 1,
                "preserve_user_order": True,
                "scalar_form_allowed": False,
                "object_record_items_allowed": False,
            },
            "language_mapping": {
                "natural_sfx_target_without_explicit_localized_languages": [
                    "SFX"
                ],
                "explicit_localized_languages": (
                    "replace SFX with the stated non-empty ordered string array"
                ),
                "languages_must_never_be_omitted": True,
            },
            "options": {
                "path": "$.arguments.options",
                "exact_value": {},
            },
            "io_root": {
                "path": "$.arguments.io_root",
                "type": "string",
                "shape": "scalar",
                "absolute": True,
            },
        },
    }
    keys = list(payload)
    assert (
        keys.index("request_envelope_policy")
        < keys.index("direct_fast_route_contract")
        < keys.index("session_context")
    )
    assert waapi_gateway.gateway_json_document_size(payload) < 8 * 1024

    materialized = json.loads(
        json.dumps(
            payload["direct_fast_route_contract"]["canonical_request_template"]
        )
    )
    materialized["arguments"]["args"] = {
        "objects": [
            r"\Actor-Mixer Hierarchy\Default Work Unit\WAAPI Sandbox\SFX_A",
            r"\Actor-Mixer Hierarchy\Default Work Unit\WAAPI Sandbox\SFX_B",
        ],
        "platforms": ["Mac", "Windows"],
        "languages": ["SFX"],
    }
    materialized["arguments"]["io_root"] = str(tmp_path.resolve())
    parsed = parse_operation_request(materialized, expected_version=version)
    assert parsed.arguments == materialized["arguments"]
    validation = validate_semantic_payload(
        materialized["arguments"]["api"],
        materialized["arguments"]["args"],
        materialized["arguments"]["options"],
        version=version,
    )
    assert validation.required_fields == ("objects", "platforms", "languages")

    second_exit_code, second_payload = waapi_gateway.execute_gateway(
        ["operation-schema", "waapi.call"],
        env=env,
        client_factory=fail_if_connected,
    )
    assert second_exit_code == 0
    assert second_payload == payload
    assert factory_calls == []

    for other_version in ("2021.1", "2022.1", "2023.1"):
        other_exit_code, other = execute(
            ["operation-schema", "waapi.call"],
            tmp_path=tmp_path,
            version=other_version,
        )
        assert other_exit_code == 0
        assert "direct_fast_route_contract" not in other

    operation_exit_code, other_operation = execute(
        ["operation-schema", "object.setNotes"],
        tmp_path=tmp_path,
        version=version,
    )
    assert operation_exit_code == 0
    assert "direct_fast_route_contract" not in other_operation


def test_transaction_show_reads_immutable_artifact_and_journal_without_wwise(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    artifact = {"contract": "test-preview/v1", "prepared_operation": {"operation": "object.setNotes"}}
    created = store.create_preview("tx-show", artifact)
    store.submit_for_confirmation("tx-show")

    exit_code, payload = execute(
        ["transaction-show", "tx-show"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 0
    assert payload["transaction_id"] == "tx-show"
    assert payload["state"] == TransactionState.AWAITING_CONFIRMATION.value
    assert payload["artifact_hash"] == created.artifact_hash
    token = assert_confirmation_binding(
        payload,
        transaction_id="tx-show",
        artifact_hash=created.artifact_hash,
        event_sequence=2,
        last_event_hash=payload["events"][-1]["event_hash"],
    )
    assert payload["next_command"] == expected_transaction_next_command(
        "confirm",
        ["confirm", "tx-show", "--confirmation-token", token],
        requires_explicit_user_confirmation=True,
    )
    assert list(payload).index("confirmation") > list(payload).index("events")
    assert list(payload).index("next_command") > list(payload).index("events")
    assert list(payload).index("next_command") > list(payload).index("session_context")
    assert list(payload)[-1] == "next_command"
    assert payload["artifact"] == artifact
    assert [event["event_type"] for event in payload["events"]] == [
        "preview_created",
        "confirmation_requested",
    ]


def test_transaction_show_advertises_exact_confirm_argv_only_while_awaiting(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    created = store.create_preview(
        "tx-next-command",
        {
            "contract": "test-preview/v1",
            "prepared_operation": {"operation": "object.setNotes"},
        },
    )

    exit_code, draft = execute(
        ["transaction-show", "tx-next-command", "--summary-only"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    assert exit_code == 0
    assert draft["state"] == TransactionState.DRAFT.value
    assert "confirmation" not in draft
    assert "next_command" not in draft

    store.submit_for_confirmation("tx-next-command")
    exit_code, awaiting = execute(
        ["transaction-show", "tx-next-command", "--summary-only"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    assert exit_code == 0
    awaiting_token = assert_confirmation_binding(
        awaiting,
        transaction_id="tx-next-command",
        artifact_hash=created.artifact_hash,
        event_sequence=2,
        last_event_hash=awaiting["events"][-1]["event_hash"],
    )
    assert awaiting["next_command"] == expected_transaction_next_command(
        "confirm",
        [
            "confirm",
            "tx-next-command",
            "--confirmation-token",
            awaiting_token,
        ],
        requires_explicit_user_confirmation=True,
    )
    assert list(awaiting)[-1] == "next_command"

    store.confirm("tx-next-command", artifact_hash=created.artifact_hash)
    exit_code, confirmed = execute(
        ["transaction-show", "tx-next-command", "--summary-only"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    assert exit_code == 0
    assert confirmed["state"] == TransactionState.CONFIRMED.value
    assert "confirmation" not in confirmed
    assert "next_command" not in confirmed


def test_transaction_show_summary_omits_raw_artifact_bulk_but_keeps_review_evidence(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    artifact = {
        "contract": "waapi-skill.transaction-preview/v2",
        "request": {"operation": "object.setNotes"},
        "prepared_operation": {
            "dispatch": {"uri": "ak.wwise.core.object.setNotes"},
            "resolved_roles": {"object": {"id": "fixture"}},
            "pre_state": {"notes": "before"},
            "verification_plan": [{"read": "notes"}],
            "cleanup": {"required": False},
        },
        "project_guard": {"fingerprint": "project-fingerprint", "large": "x" * 4096},
        "runtime_guard": {"fingerprint": "runtime-fingerprint", "files": {"large": "y" * 4096}},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    created = store.create_preview("tx-summary", artifact)
    store.submit_for_confirmation("tx-summary")

    exit_code, payload = execute(
        ["transaction-show", "tx-summary", "--summary-only"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 0
    assert payload["artifact_hash"] == created.artifact_hash
    token = assert_confirmation_binding(
        payload,
        transaction_id="tx-summary",
        artifact_hash=created.artifact_hash,
        event_sequence=2,
        last_event_hash=payload["events"][-1]["event_hash"],
    )
    assert payload["next_command"] == expected_transaction_next_command(
        "confirm",
        ["confirm", "tx-summary", "--confirmation-token", token],
        requires_explicit_user_confirmation=True,
    )
    assert list(payload).index("next_command") > list(payload).index("events")
    assert list(payload).index("next_command") > list(payload).index("session_context")
    assert list(payload)[-1] == "next_command"
    assert payload["summary_only"] is True
    assert "artifact" not in payload
    assert payload["preview_summary"]["contract"] == artifact["contract"]
    assert payload["preview_summary"]["request"] == {"operation": "object.setNotes"}
    assert payload["preview_summary"]["dispatch"] == artifact["prepared_operation"]["dispatch"]
    assert payload["preview_summary"]["resolved_roles"] == artifact["prepared_operation"][
        "resolved_roles"
    ]
    assert payload["preview_summary"]["pre_state"] == artifact["prepared_operation"][
        "pre_state"
    ]
    assert payload["preview_summary"]["verification_plan"] == artifact[
        "prepared_operation"
    ]["verification_plan"]
    assert "summary_contract" not in payload["preview_summary"]
    assert payload["preview_summary"]["project_guard_fingerprint"] == "project-fingerprint"
    assert payload["preview_summary"]["runtime_guard_fingerprint"] == "runtime-fingerprint"
    assert [event["event_type"] for event in payload["events"]] == [
        "preview_created",
        "confirmation_requested",
    ]


def test_transaction_next_command_quotes_posix_shell_arguments_without_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(waapi_gateway, "os", type("PosixOS", (), {"name": "posix"})())
    monkeypatch.setattr(
        waapi_gateway,
        "GATEWAY_RUNNER_PATH",
        PurePosixPath("/tmp/WAAPI Skill/scripts/run.py"),
    )

    payload = waapi_gateway.transaction_next_command(
        "confirm",
        [
            "confirm",
            "tx with space",
            "--confirmation-token",
            f"ct1-{'0' * 24}",
        ],
        requires_explicit_user_confirmation=True,
    )

    assert payload["shell_family"] == "posix-sh"
    assert payload["shell_command"] == (
        "python '/tmp/WAAPI Skill/scripts/run.py' gateway.py confirm "
        f"'tx with space' --confirmation-token ct1-{'0' * 24}"
    )
    assert shlex.split(payload["shell_command"]) == payload["full_argv"]
    assert payload["copy_instruction"]["source_field"] == "shell_command"
    assert tuple(payload)[-2:] == ("copy_instruction", "shell_command")


def test_transaction_next_command_keeps_one_copy_source_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(waapi_gateway, "os", type("WindowsOS", (), {"name": "nt"})())
    monkeypatch.setattr(
        waapi_gateway,
        "GATEWAY_RUNNER_PATH",
        PureWindowsPath(r"C:\WAAPI Skill\scripts\run.py"),
    )

    payload = waapi_gateway.transaction_next_command(
        "execute",
        ["execute", "tx1-windows"],
    )

    assert payload["shell_family"] == WINDOWS_POWERSHELL_ENCODED_FAMILY
    assert decode_windows_powershell_argv(payload["shell_command"]) == tuple(
        payload["full_argv"]
    )
    assert payload["copy_instruction"] == {
        "contract": "waapi-skill.gateway-command-copy-instruction/v1",
        "source_field": "shell_command",
        "action": "execute_verbatim_as_one_shell_tool_call",
        "forbidden_transformations": [
            "reconstruct",
            "shorten",
            "normalize",
            "substitute_path_segments",
        ],
    }
    assert tuple(payload)[-2:] == ("copy_instruction", "shell_command")


def test_transaction_show_summary_compacts_large_graph_without_losing_exact_request() -> None:
    nodes = [
        {
            "type": "Sound",
            "name": f"Footstep_{index:03d}",
            "notes": "review evidence " * 4,
        }
        for index in range(60)
    ]
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "operation": "object.create",
        "version": "2022.1",
        "arguments": {
            "parent": {"path": r"\Actor-Mixer Hierarchy\Default Work Unit\Generated"},
            "type": "ActorMixer",
            "name": "Prototype_Footsteps",
            "children": nodes,
            "on_name_conflict": "replace",
        },
    }
    dispatch = {
        "uri": "ak.wwise.core.object.create",
        "args": {
            "parent": r"\Actor-Mixer Hierarchy\Default Work Unit\Generated",
            "type": "ActorMixer",
            "name": "Prototype_Footsteps",
            "children": nodes,
            "onNameConflict": "replace",
        },
        "options": {"return": ["id", "name", "path", "type"]},
    }
    resolved_roles = {
        "parent": {
            "object": PARENT_GUID,
            "resolution": "live-path",
            "row": parent_row(),
        },
        "replace_collision": {
            "object": OBJECT_GUID,
            "resolution": "live-exact-create-root-collision",
            "row": {
                "id": OBJECT_GUID,
                "name": "Prototype_Footsteps",
                "path": PARENT_PATH + r"\Prototype_Footsteps",
                "type": "ActorMixer",
            },
        },
    }
    pre_state = {
        "object_create_nodes": nodes,
        "object_graph_guard": {"rows": nodes, "digest_source": nodes},
        "parent": parent_row(),
    }
    verification_plan = {
        "kind": "object-create-graph",
        "version": "2022.1",
        "on_name_conflict": "replace",
        "parent_id": PARENT_GUID,
        "nodes": nodes,
        "preexisting_root_rows": [resolved_roles["replace_collision"]["row"]],
        "replaced_subtree_rows": [
            {"id": OBJECT_GUID, "path": PARENT_PATH + r"\Prototype_Footsteps"}
        ],
    }
    cleanup = {"kind": "none", "automatic_cleanup": False, "warnings": []}
    artifact = {
        "contract": "waapi-skill.transaction-preview/v2",
        "request": request,
        "prepared_operation": {
            "dispatch": dispatch,
            "resolved_roles": resolved_roles,
            "pre_state": pre_state,
            "verification_plan": verification_plan,
            "cleanup": cleanup,
        },
        "project_guard": {"fingerprint": "project-fingerprint"},
        "runtime_guard": {"fingerprint": "runtime-fingerprint"},
        "expires_at": "2030-01-01T00:00:00Z",
    }

    result = waapi_gateway.transaction_show_summary(artifact, [])
    preview_summary = result["preview_summary"]

    assert preview_summary["request"] == request
    assert preview_summary["request"] is request
    assert preview_summary["detail_level"] in {"compact-dispatch", "digest"}
    assert preview_summary["dispatch"]["payload_included"] is False
    assert preview_summary["dispatch"]["uri"] == dispatch["uri"]
    assert preview_summary["dispatch"]["canonical_sha256"] == waapi_gateway.canonical_sha256(
        dispatch
    )
    assert preview_summary["verification_plan"]["nodes_count"] == len(nodes)
    assert preview_summary["fixed_projection_bytes"] <= 6 * 1024

    fixed_preview = {
        key: value for key, value in preview_summary.items() if key != "request"
    }
    fixed_result = {
        "summary_only": result["summary_only"],
        "preview_summary": fixed_preview,
        "event_count": result["event_count"],
        "events": result["events"],
    }
    assert (
        waapi_gateway.gateway_json_document_size(fixed_result)
        == preview_summary["fixed_projection_bytes"]
    )

    legacy = {
        "summary_only": True,
        "preview_summary": {
            "contract": artifact["contract"],
            "request": request,
            "dispatch": dispatch,
            "resolved_roles": resolved_roles,
            "pre_state": pre_state,
            "verification_plan": verification_plan,
            "cleanup": waapi_gateway.transaction_cleanup_payload(
                artifact["prepared_operation"], phase="preview"
            ),
            "project_guard_fingerprint": "project-fingerprint",
            "runtime_guard_fingerprint": "runtime-fingerprint",
            "expires_at": artifact["expires_at"],
        },
        "event_count": 0,
        "events": [],
    }
    assert waapi_gateway.gateway_json_document_size(result) < (
        waapi_gateway.gateway_json_document_size(legacy) // 2
    )


def test_preview_uses_bounded_review_for_set04_scale_artifact_without_losing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    foley = r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Foley"
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "path", "value": foley + r"\Player"},
                    "notes": "玩家 Foley",
                    "properties": [{"name": "Volume", "value": -1}],
                    "children": [
                        {
                            "type": "RandomSequenceContainer",
                            "name": "Cloth",
                            "children": [
                                {"type": "Sound", "name": "Cloth_Light"},
                                {"type": "Sound", "name": "Cloth_Heavy"},
                            ],
                        }
                    ],
                },
                {
                    "object": {
                        "kind": "path",
                        "value": foley + r"\Player\Footsteps",
                    },
                    "children": [{"type": "Sound", "name": "Walk_B"}],
                },
                {
                    "object": {"kind": "path", "value": foley + r"\NPC"},
                    "notes": "NPC Foley",
                    "properties": [{"name": "Volume", "value": -3}],
                    "children": [
                        {
                            "type": "RandomSequenceContainer",
                            "name": "Armor",
                            "children": [
                                {"type": "Sound", "name": "Armor_Light"},
                                {"type": "Sound", "name": "Armor_Heavy"},
                            ],
                        }
                    ],
                },
                {
                    "object": {
                        "kind": "path",
                        "value": foley + r"\NPC\Footsteps",
                    },
                    "children": [{"type": "Sound", "name": "Walk_B"}],
                },
            ],
            "on_name_conflict": "fail",
        },
    }
    large_nodes = [
        {
            "request_path": f"$.objects[{index % 4}].children[{index}]",
            "parent_request_path": f"$.objects[{index % 4}]",
            "existing_target": index % 3 == 0,
            "target_id": f"{{40000000-0000-0000-0000-{index:012d}}}",
            "requested_name": f"SET04_Node_{index:03d}",
            "requested_type": "Sound",
            "expected_path": foley + rf"\SET04_Node_{index:03d}",
            "pre_state": {
                "notes": f"preserved SET-04 pre-state {index:03d} " + ("x" * 192),
                "children": [f"Preserved_{index:03d}_A", f"Preserved_{index:03d}_B"],
            },
        }
        for index in range(96)
    ]
    artifact = {
        "contract": "waapi-skill.transaction-preview/v2",
        "request": request,
        "prepared_operation": {
            "contract": "waapi-skill.prepared-operation/v1",
            "operation": "object.set",
            "version": "2022.1",
            "dispatch": {
                "uri": "ak.wwise.core.object.set",
                "args": request["arguments"],
                "options": {"return": ["id", "name", "path", "type", "children"]},
            },
            "resolved_roles": {
                f"target_{index}": {
                    "resolution": "live-path",
                    "row": {
                        "id": f"{{50000000-0000-0000-0000-{index:012d}}}",
                        "name": name,
                        "type": "ActorMixer",
                        "path": foley + "\\" + name,
                    },
                }
                for index, name in enumerate(
                    ("Player", "Player\\Footsteps", "NPC", "NPC\\Footsteps")
                )
            },
            "pre_state": {"object_set_nodes": large_nodes},
            "verification_plan": {
                "kind": "object-set-batch",
                "version": "2022.1",
                "on_name_conflict": "fail",
                "nodes": large_nodes,
            },
            "cleanup": {
                "kind": "discard-owned-sandbox-or-restore-captured-fields",
                "automatic": False,
                "automatic_retry": False,
                "partial_success_possible": True,
            },
        },
        "project_guard": {"fingerprint": "set04-project-fingerprint"},
        "runtime_guard": {"fingerprint": "set04-runtime-fingerprint"},
        "created_at": "2030-01-01T00:00:00Z",
        "expires_at": "2030-01-01T00:05:00Z",
    }

    class StubArtifact:
        def as_dict(self) -> dict[str, Any]:
            return json.loads(json.dumps(artifact))

    monkeypatch.setattr(
        waapi_gateway,
        "build_transaction_artifact",
        lambda *args, **kwargs: StubArtifact(),
    )
    payload = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )

    stored = TransactionStore(state_dir).load_preview(payload["transaction_id"])
    assert stored.artifact == artifact
    assert (
        stored.artifact["prepared_operation"]["pre_state"]["object_set_nodes"][-1]
        == large_nodes[-1]
    )
    assert stored.artifact["prepared_operation"]["verification_plan"]["nodes"] == large_nodes
    assert waapi_gateway.gateway_json_document_size(stored.artifact) > 64 * 1024

    summary = payload["preview_summary"]
    assert payload["summary_only"] is True
    assert payload["event_count"] == 2
    assert [event["event_type"] for event in payload["events"]] == [
        "preview_created",
        "confirmation_requested",
    ]
    assert summary["summary_contract"] == "waapi-skill.transaction-show-summary/v1"
    assert summary["detail_level"] in {"compact-dispatch", "digest"}
    assert summary["request"] == request
    assert summary["verification_plan"]["nodes_count"] == len(large_nodes)
    assert summary["fixed_projection_bytes"] <= summary["fixed_projection_limit_bytes"]
    assert payload["project_call"]["api"] == "ak.wwise.core.getProjectInfo"
    assert "result" not in payload["project_call"]
    assert waapi_gateway.gateway_json_document_size(payload) < 24 * 1024
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload

    assert payload["agent_result"] == {
        "operation": "object.set",
        "transaction_id": payload["transaction_id"],
        "artifact_hash": payload["artifact_hash"],
        "state": TransactionState.AWAITING_CONFIRMATION.value,
        "executed": False,
        "request": request,
        "authorization": payload["authorization"],
        "cleanup": payload["cleanup"],
        "next_command": payload["next_command"],
    }
    assert list(payload)[-1] == "agent_result"

    show_exit, show_payload = execute(
        ["transaction-show", payload["transaction_id"], "--summary-only"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert show_exit == 0, show_payload
    assert show_payload["artifact_hash"] == payload["artifact_hash"]
    assert show_payload["preview_summary"]["request"] == request
    assert show_payload["preview_summary"]["cleanup"] == payload["cleanup"]
    assert show_payload["preview_summary"]["project_guard_fingerprint"] == (
        artifact["project_guard"]["fingerprint"]
    )
    assert show_payload["preview_summary"]["runtime_guard_fingerprint"] == (
        artifact["runtime_guard"]["fingerprint"]
    )
    assert show_payload["preview_summary"]["expires_at"] == artifact["expires_at"]
    assert show_payload["preview_summary"]["detail_level"] in {
        "compact-dispatch",
        "digest",
    }
    assert show_payload["preview_summary"]["dispatch"]["payload_included"] is False
    assert "artifact" not in show_payload
    assert "preserved SET-04 pre-state" not in json.dumps(
        show_payload,
        ensure_ascii=False,
    )
    assert waapi_gateway.gateway_json_document_size(show_payload) < 24 * 1024
    continued = TransactionStore(state_dir).load_preview(payload["transaction_id"])
    assert continued.artifact_hash == payload["artifact_hash"]
    assert continued.artifact == artifact


def test_transaction_dispatch_summary_digest_is_canonical_and_value_sensitive() -> None:
    first = {
        "uri": "ak.wwise.core.object.create",
        "args": {"b": 2, "a": {"second": 2, "first": 1}},
        "options": {"return": ["id", "path"]},
    }
    reordered = {
        "options": {"return": ["id", "path"]},
        "args": {"a": {"first": 1, "second": 2}, "b": 2},
        "uri": "ak.wwise.core.object.create",
    }
    changed = {
        **reordered,
        "args": {"a": {"first": 1, "second": 3}, "b": 2},
    }

    first_summary = waapi_gateway.transaction_dispatch_summary(first, include_payload=False)
    reordered_summary = waapi_gateway.transaction_dispatch_summary(
        reordered, include_payload=False
    )
    changed_summary = waapi_gateway.transaction_dispatch_summary(changed, include_payload=False)

    assert first_summary["canonical_sha256"] == reordered_summary["canonical_sha256"]
    assert first_summary["args_canonical_sha256"] == reordered_summary["args_canonical_sha256"]
    assert first_summary["canonical_sha256"] != changed_summary["canonical_sha256"]
    assert first_summary["args_canonical_sha256"] != changed_summary["args_canonical_sha256"]
    assert first_summary["argument_keys"] == ["a", "b"]
    assert "args" not in first_summary
    assert "options" not in first_summary


def test_transaction_show_digest_size_is_independent_of_role_and_pre_state_key_counts() -> None:
    roles = {
        f"target_{index:04d}": {
            "object": f"{{{index:08X}-0000-0000-0000-000000000000}}",
            "resolution": "live-id",
            "row": {
                "id": f"{{{index:08X}-0000-0000-0000-000000000000}}",
                "name": f"Object_{index:04d}",
                "path": rf"\Actor-Mixer Hierarchy\Objects\Object_{index:04d}",
                "type": "Sound",
            },
        }
        for index in range(500)
    }
    pre_state = {
        f"field_{index:04d}": {"value": index, "notes": "captured"}
        for index in range(500)
    }
    artifact = {
        "contract": "waapi-skill.transaction-preview/v2",
        "request": {
            "contract": "waapi-skill.operation-request/v1",
            "operation": "object.setNotes",
            "version": "2022.1",
            "arguments": {"object": {"id": OBJECT_GUID}, "notes": "updated"},
        },
        "prepared_operation": {
            "dispatch": {
                "uri": "ak.wwise.core.object.setNotes",
                "args": {"object": OBJECT_GUID, "value": "updated"},
                "options": {},
            },
            "resolved_roles": roles,
            "pre_state": pre_state,
            "verification_plan": {
                "kind": "readback",
                "assertions": [{"role": role} for role in roles],
            },
            "cleanup": {"kind": "none"},
        },
    }

    result = waapi_gateway.transaction_show_summary(artifact, [])
    preview_summary = result["preview_summary"]

    assert preview_summary["detail_level"] == "digest"
    assert preview_summary["resolved_roles"]["role_count"] == 500
    assert preview_summary["resolved_roles"]["role_names_included"] is False
    assert "role_names" not in preview_summary["resolved_roles"]
    assert preview_summary["pre_state"]["key_count"] == 500
    assert preview_summary["pre_state"]["key_names_included"] is False
    assert "keys" not in preview_summary["pre_state"]
    assert preview_summary["verification_plan"]["assertions_count"] == 500
    assert preview_summary["fixed_projection_bytes"] <= 4 * 1024


def test_transaction_show_long_migrate_review_is_materially_smaller_than_legacy_shape() -> None:
    project_path = "/sandbox/" + ("deep-segment/" * 100) + "SampleProject.wproj"
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "operation": "waapi.call",
        "version": "2022.1",
        "arguments": {
            "api": "ak.wwise.cli.migrate",
            "args": {"project": project_path},
            "options": {},
            "io_root": str(Path(project_path).parent),
        },
    }
    dispatch = {
        "uri": "ak.wwise.cli.migrate",
        "args": {"project": project_path},
        "options": {},
    }
    cleanup = {
        "contract": "waapi-skill.transaction-cleanup-spec/v1",
        "api": "ak.wwise.cli.migrate",
        "kind": "none",
        "binding": {"kind": "none", "materialized": True},
        "cleanup_requirement": "not_required",
        "companion_request": None,
        "automatic_cleanup": False,
        "automatic_retry": False,
        "warnings": [],
        "spec_sha256": "a" * 64,
    }
    artifact = {
        "contract": "waapi-skill.transaction-preview/v2",
        "request": request,
        "prepared_operation": {
            "dispatch": dispatch,
            "resolved_roles": {},
            "pre_state": {
                "execution_contract": {
                    "contract": "waapi-skill.public-execution-contract/v2",
                    "effect": "external",
                    "gateway_commands": ["preview", "confirm", "execute", "verify"],
                    "io_audit": {
                        "contract": "waapi-skill.isolated-io-audit/v1",
                        "io_root": str(Path(project_path).parent),
                        "paths": [
                            {
                                "field": "project",
                                "raw_path": project_path,
                                "resolved_path": project_path,
                                "within_io_root": True,
                            }
                        ],
                    },
                    "request_validation_strength": "partial_reflected_schema",
                    "requires_authorization": True,
                    "accepted_authorization_modes": [
                        "explicit_confirmation",
                        "policy_authorization",
                    ],
                    "route": "isolated_transaction",
                    "timeout_seconds": 120.0,
                    "uri": "ak.wwise.cli.migrate",
                    "verification_strategy": "result_schema",
                    "version": "2022.1",
                }
            },
            "verification_plan": {
                "kind": "result-schema",
                "strategy": "result_schema",
                "uri": "ak.wwise.cli.migrate",
                "version": "2022.1",
            },
            "cleanup": cleanup,
        },
        "project_guard": {"fingerprint": "project-fingerprint"},
        "runtime_guard": {"fingerprint": "runtime-fingerprint"},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    events = [
        {
            "sequence": 1,
            "event_type": "preview_created",
            "from_state": None,
            "to_state": "draft",
            "event_hash": "b" * 64,
        },
        {
            "sequence": 2,
            "event_type": "confirmation_requested",
            "from_state": "draft",
            "to_state": "awaiting_confirmation",
            "event_hash": "c" * 64,
        },
    ]

    result = waapi_gateway.transaction_show_summary(artifact, events)
    preview_summary = result["preview_summary"]

    assert preview_summary["detail_level"] == "digest"
    assert preview_summary["request"] == request
    assert preview_summary["cleanup"]["spec"] == cleanup
    assert preview_summary["dispatch"]["payload_included"] is False
    assert preview_summary["fixed_projection_bytes"] <= 4 * 1024
    legacy = {
        "summary_only": True,
        "preview_summary": {
            "contract": artifact["contract"],
            "request": request,
            "dispatch": dispatch,
            "resolved_roles": {},
            "pre_state": artifact["prepared_operation"]["pre_state"],
            "verification_plan": artifact["prepared_operation"]["verification_plan"],
            "cleanup": waapi_gateway.transaction_cleanup_payload(
                artifact["prepared_operation"], phase="preview"
            ),
            "project_guard_fingerprint": "project-fingerprint",
            "runtime_guard_fingerprint": "runtime-fingerprint",
            "expires_at": artifact["expires_at"],
        },
        "event_count": len(events),
        "events": events,
    }
    assert waapi_gateway.gateway_json_document_size(result) * 10 < (
        waapi_gateway.gateway_json_document_size(legacy) * 7
    )


def test_transaction_show_summary_budget_failure_is_structured_and_never_truncated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    artifact = {
        "contract": "waapi-skill.transaction-preview/v2",
        "request": {"operation": "object.setNotes"},
        "prepared_operation": {
            "dispatch": {"uri": "ak.wwise.core.object.setNotes", "args": {}, "options": {}},
            "resolved_roles": {},
            "pre_state": {},
            "verification_plan": {"kind": "readback"},
            "cleanup": {"kind": "none"},
        },
    }
    store.create_preview("tx-summary-budget", artifact)
    store.submit_for_confirmation("tx-summary-budget")
    monkeypatch.setattr(waapi_gateway, "TRANSACTION_SHOW_SUMMARY_FIXED_BUDGET_BYTES", 32)

    exit_code, payload = execute(
        ["transaction-show", "tx-summary-budget", "--summary-only"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error_code"] == "SUMMARY_BUDGET_EXCEEDED"
    assert payload["details"]["limit_bytes"] == 32
    assert payload["details"]["truncated"] is False
    assert payload["details"]["request_bytes_excluded_from_limit"] > 0
    assert payload["transaction_id"] == "tx-summary-budget"
    assert payload["state"] == TransactionState.AWAITING_CONFIRMATION.value
    assert payload["artifact_hash"] == store.load_preview(
        "tx-summary-budget"
    ).artifact_hash
    assert payload["details"]["transaction_id"] == payload["transaction_id"]
    assert payload["details"]["state"] == payload["state"]
    assert payload["details"]["artifact_hash"] == payload["artifact_hash"]
    assert set(payload["details"]["observed_fixed_projection_bytes"]) == {
        "review",
        "compact-dispatch",
        "digest",
    }
    assert "preview_summary" not in payload


def test_confirm_uses_environment_state_dir_and_never_connects_to_wwise(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    created = store.create_preview("tx-confirm", {"operation": "object.setNotes"})
    store.submit_for_confirmation("tx-confirm")

    exit_code, payload = execute(
        ["confirm", "tx-confirm", "--artifact-hash", created.artifact_hash],
        tmp_path=tmp_path,
        state_dir=state_dir,
        env_state_dir=True,
    )

    assert exit_code == 0
    assert payload["contract"] == "waapi-skill.gateway-result/v1"
    assert payload["ok"] is True
    assert payload["offline"] is True
    assert payload["command"] == "confirm"
    assert payload["transaction_id"] == "tx-confirm"
    assert payload["state"] == TransactionState.CONFIRMED.value
    assert payload["artifact_hash"] == created.artifact_hash
    assert store.load("tx-confirm").state is TransactionState.CONFIRMED


def test_confirm_accepts_state_scoped_confirmation_token_without_connecting(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    created = store.create_preview(
        "tx-confirm-token",
        {"operation": "object.setNotes"},
    )
    store.submit_for_confirmation("tx-confirm-token")
    confirmation_token = store.load_snapshot(
        "tx-confirm-token"
    ).confirmation_token
    assert confirmation_token is not None

    exit_code, payload = execute(
        [
            "confirm",
            "tx-confirm-token",
            "--confirmation-token",
            confirmation_token,
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 0
    assert payload["state"] == TransactionState.CONFIRMED.value
    assert payload["artifact_hash"] == created.artifact_hash
    assert payload["next_command"] == expected_transaction_next_command(
        "execute",
        ["execute", "tx-confirm-token"],
    )
    assert store.load("tx-confirm-token").state is TransactionState.CONFIRMED


def test_confirm_token_mismatch_is_structured_without_echoing_correct_token(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    store.create_preview("tx-token-mismatch", {"operation": "object.setNotes"})
    store.submit_for_confirmation("tx-token-mismatch")
    correct_token = store.load_snapshot("tx-token-mismatch").confirmation_token
    assert correct_token is not None
    wrong_character = "0" if correct_token[-1] != "0" else "1"
    wrong_token = f"{correct_token[:-1]}{wrong_character}"

    exit_code, payload = execute(
        [
            "confirm",
            "tx-token-mismatch",
            "--confirmation-token",
            wrong_token,
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error_code"] == "ConfirmationTokenMismatch"
    encoded = json.dumps(payload, ensure_ascii=False)
    assert correct_token not in encoded
    assert wrong_token not in encoded
    assert (
        store.load("tx-token-mismatch").state
        is TransactionState.AWAITING_CONFIRMATION
    )
    assert len(store.read_events("tx-token-mismatch")) == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["confirm", "tx-parser"],
        [
            "confirm",
            "tx-parser",
            "--confirmation-token",
            f"ct1-{'0' * 24}",
            "--artifact-hash",
            "a" * 64,
        ],
    ],
)
def test_confirm_parser_requires_exactly_one_binding_argument(
    argv: list[str],
) -> None:
    with pytest.raises(SystemExit):
        waapi_gateway.build_parser().parse_args(argv)


def test_execute_rechecks_external_never_policy_after_prior_confirmation(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    created = store.create_preview("tx-policy-drift", {"operation": "object.setNotes"})
    store.submit_for_confirmation("tx-policy-drift")

    confirm_code, confirmed = execute(
        ["confirm", "tx-policy-drift", "--artifact-hash", created.artifact_hash],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    assert confirm_code == 0
    assert confirmed["state"] == TransactionState.CONFIRMED.value

    config_path = tmp_path / "config" / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
                "project_modification_policy": "never",
            }
        ),
        encoding="utf-8",
    )
    exit_code, payload = execute(
        ["execute", "tx-policy-drift"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 2
    assert payload["message"] == (
        "project_modification_policy=read_only blocks transaction execution"
    )
    assert store.load("tx-policy-drift").state is TransactionState.CONFIRMED


def test_preview_apply_read_only_blocks_before_connection_or_state_write(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"

    exit_code, payload = execute(
        [
            "preview",
            "--apply",
            "--request-json",
            json.dumps(create_request()),
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        policy="read_only",
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["message"] == (
        "project_modification_policy=read_only blocks transaction "
        "requested project change"
    )
    assert payload["session_context"]["project_modification_policy"] == "read_only"
    assert not state_dir.exists()


def test_preview_apply_rejects_transaction_read_without_persisting_a_transaction(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )

    exit_code, payload = execute(
        [
            "preview",
            "--apply",
            "--request-json",
            json.dumps(generic_read_transaction_call_request()),
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
        policy="allow_changes",
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["message"] == (
        "preview --apply is reserved for project or process changes; "
        "omit --apply for this read transaction."
    )
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    assert list((state_dir / "transactions").iterdir()) == []


def test_read_only_allows_explicitly_confirmed_sealed_read_transaction(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "read-state"
    transaction = preview(
        generic_read_transaction_call_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
        policy="read_only",
    )
    assert transaction["authorization"] == {
        "mode": "explicit_confirmation",
        "policy": "read_only",
        "explicit_confirmation": False,
        "notice_required": True,
        "requires_later_user_message": True,
    }
    artifact = TransactionStore(state_dir).load_preview(
        transaction["transaction_id"]
    ).artifact
    assert artifact["execution_policy"]["accepted_authorization_modes"] == [
        "explicit_confirmation"
    ]

    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.remote.getAvailableConsoles": [{"consoles": []}],
        }
    )
    execute_exit, executed = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        policy="read_only",
    )

    assert execute_exit == 0, executed
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert [
        call[0] for call in execute_client.calls
    ].count("ak.wwise.core.remote.getAvailableConsoles") == 1

    verify_exit, verified = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
        policy="read_only",
    )
    assert verify_exit == 0, verified
    assert verified["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verified["result_schema_checked"] is True


def test_preview_apply_ask_before_changes_still_requires_show_token_and_confirm(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview(
        create_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.object.get": create_preview_object_reads(),
                "ak.wwise.core.object.getTypes": [create_type_catalog()],
            }
        ),
        apply=True,
        policy="ask_before_changes",
    )

    transaction_id = transaction["transaction_id"]
    store = TransactionStore(state_dir)
    awaiting = store.load_snapshot(transaction_id)
    assert awaiting.record.state is TransactionState.AWAITING_CONFIRMATION
    assert transaction["authorization"] == {
        "mode": "explicit_confirmation",
        "policy": "ask_before_changes",
        "explicit_confirmation": False,
        "notice_required": True,
        "requires_later_user_message": True,
    }
    assert [event["event_type"] for event in awaiting.events] == [
        "preview_created",
        "confirmation_requested",
    ]

    show_exit, shown = execute(
        ["transaction-show", transaction_id, "--summary-only"],
        tmp_path=tmp_path,
        state_dir=state_dir,
        policy="ask_before_changes",
    )
    assert show_exit == 0, shown
    token = assert_confirmation_binding(
        shown,
        transaction_id=transaction_id,
        artifact_hash=transaction["artifact_hash"],
        event_sequence=awaiting.record.event_sequence,
        last_event_hash=awaiting.record.last_event_hash,
    )
    assert shown["next_command"] == expected_transaction_next_command(
        "confirm",
        ["confirm", transaction_id, "--confirmation-token", token],
        requires_explicit_user_confirmation=True,
    )

    confirm_exit, confirmed = execute(
        ["confirm", transaction_id, "--confirmation-token", token],
        tmp_path=tmp_path,
        state_dir=state_dir,
        policy="ask_before_changes",
    )
    assert confirm_exit == 0, confirmed
    assert confirmed["state"] == TransactionState.CONFIRMED.value
    assert confirmed["next_command"] == expected_transaction_next_command(
        "execute",
        ["execute", transaction_id],
    )


def test_ask_before_changes_uses_same_home_state_store_without_broker_injection(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    state_dir = home / ".local" / "state" / "waapi-skill"
    env = gateway_env(tmp_path, policy="ask_before_changes")
    env["HOME"] = str(home)
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": create_preview_object_reads(),
            "ak.wwise.core.object.getTypes": [create_type_catalog()],
        }
    )

    preview_exit, transaction = waapi_gateway.execute_gateway(
        [
            "preview",
            "--apply",
            "--request-json",
            json.dumps(create_request()),
        ],
        env=env,
        client_factory=lambda url: preview_client,
    )

    assert preview_exit == 0, transaction
    assert transaction["state"] == TransactionState.AWAITING_CONFIRMATION.value
    transaction_id = transaction["transaction_id"]
    assert (state_dir / "transactions" / transaction_id).is_dir()

    offline_factory = lambda url: (_ for _ in ()).throw(AssertionError(url))
    show_exit, shown = waapi_gateway.execute_gateway(
        ["transaction-show", transaction_id, "--summary-only"],
        env=env,
        client_factory=offline_factory,
    )
    assert show_exit == 0, shown
    snapshot = TransactionStore(state_dir).load_snapshot(transaction_id)
    token = assert_confirmation_binding(
        shown,
        transaction_id=transaction_id,
        artifact_hash=transaction["artifact_hash"],
        event_sequence=snapshot.record.event_sequence,
        last_event_hash=snapshot.record.last_event_hash,
    )
    assert shown["next_command"] == expected_transaction_next_command(
        "confirm",
        ["confirm", transaction_id, "--confirmation-token", token],
        requires_explicit_user_confirmation=True,
    )

    confirm_exit, confirmed = waapi_gateway.execute_gateway(
        ["confirm", transaction_id, "--confirmation-token", token],
        env=env,
        client_factory=offline_factory,
    )

    assert confirm_exit == 0, confirmed
    assert confirmed["state"] == TransactionState.CONFIRMED.value
    assert TransactionStore(state_dir).load(transaction_id).state is TransactionState.CONFIRMED


def test_preview_apply_allow_changes_records_policy_authority_without_confirmation(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": create_preview_object_reads(),
            "ak.wwise.core.object.getTypes": [create_type_catalog()],
        }
    )
    transaction = preview(
        create_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
        apply=True,
        policy="allow_changes",
    )

    transaction_id = transaction["transaction_id"]
    expected_authorization = {
        "mode": "policy_authorization",
        "policy": "allow_changes",
        "authority": waapi_gateway.POLICY_AUTHORIZATION_AUTHORITY,
        "explicit_confirmation": False,
        "notice_required": True,
    }
    assert transaction["status"] == TransactionState.POLICY_AUTHORIZED.value
    assert transaction["authorization"] == expected_authorization
    assert transaction["agent_result"]["authorization"] == expected_authorization
    assert "confirmation" not in transaction
    assert "requires_later_user_message" not in transaction["next_command"]
    assert transaction["next_command"] == expected_transaction_next_command(
        "execute",
        ["execute", transaction_id],
    )

    store = TransactionStore(state_dir)
    snapshot = store.load_snapshot(transaction_id)
    assert snapshot.record.state is TransactionState.POLICY_AUTHORIZED
    assert snapshot.confirmation_token is None
    assert [event["event_type"] for event in snapshot.events] == [
        "preview_created",
        "policy_authorized",
    ]
    assert snapshot.events[-1]["details"] == {
        "policy": "allow_changes",
        "authority": waapi_gateway.POLICY_AUTHORIZATION_AUTHORITY,
        "explicit_confirmation": False,
    }

    show_exit, shown = execute(
        ["transaction-show", transaction_id, "--summary-only"],
        tmp_path=tmp_path,
        state_dir=state_dir,
        policy="allow_changes",
    )
    assert show_exit == 0, shown
    assert "confirmation" not in shown
    assert shown["authorization"] == {
        **expected_authorization,
        "current_policy": "allow_changes",
    }
    assert shown["next_command"] == expected_transaction_next_command(
        "execute",
        ["execute", transaction_id],
    )
    assert "requires_later_user_message" not in shown["next_command"]
    assert not any(
        call[0] == "ak.wwise.core.object.create" for call in preview_client.calls
    )


def test_policy_authorized_allow_changes_executes_once_and_can_verify(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview(
        create_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.object.get": create_preview_object_reads(),
                "ak.wwise.core.object.getTypes": [create_type_catalog()],
            }
        ),
        apply=True,
        policy="allow_changes",
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [
                {"return": [parent_row()]},
                {"return": []},
                {"return": []},
            ],
            "ak.wwise.core.object.create": [
                {"id": CREATED_GUID, "name": "CreatedByGateway"}
            ],
        }
    )

    execute_exit, executed = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        policy="allow_changes",
    )

    assert execute_exit == 0, executed
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert executed["executed"] is True
    assert [
        call[0] for call in execute_client.calls
    ].count("ak.wwise.core.object.create") == 1
    assert executed["next_command"] == expected_transaction_next_command(
        "verify",
        ["verify", transaction["transaction_id"]],
    )

    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [created_row()]}],
        }
    )
    verify_exit, verified = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
        policy="allow_changes",
    )

    assert verify_exit == 0, verified
    assert verified["state"] == TransactionState.VERIFIED.value
    assert verified["verified"] is True
    assert not any(
        call[0] == "ak.wwise.core.object.create" for call in verify_client.calls
    )
    events = TransactionStore(state_dir).read_events(transaction["transaction_id"])
    assert [event["event_type"] for event in events] == [
        "preview_created",
        "policy_authorized",
        "execution_started",
        "execution_completed",
        "verification_recorded",
    ]


def test_policy_authorized_allow_to_ask_drift_requires_repreview_without_business_dispatch(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview(
        create_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.object.get": create_preview_object_reads(),
                "ak.wwise.core.object.getTypes": [create_type_catalog()],
            }
        ),
        apply=True,
        policy="allow_changes",
    )
    write_gateway_policy(tmp_path, "ask_before_changes")
    execute_client = FakeClient(
        {"ak.wwise.core.getInfo": [live_info()]}
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        policy="ask_before_changes",
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["status"] == "repreview_required"
    assert payload["state"] == TransactionState.REPREVIEW_REQUIRED.value
    assert payload["error_code"] == "PROJECT_MODIFICATION_POLICY_CHANGED"
    assert payload["executed"] is False
    assert payload["authorization"]["current_policy"] == "ask_before_changes"
    assert [call[0] for call in execute_client.calls] == [
        "ak.wwise.core.getInfo"
    ]
    assert TransactionStore(state_dir).load(
        transaction["transaction_id"]
    ).state is TransactionState.REPREVIEW_REQUIRED


def test_policy_authorized_allow_to_read_only_drift_blocks_before_connection(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview(
        create_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.object.get": create_preview_object_reads(),
                "ak.wwise.core.object.getTypes": [create_type_catalog()],
            }
        ),
        apply=True,
        policy="allow_changes",
    )
    write_gateway_policy(tmp_path, "read_only")
    store = TransactionStore(state_dir)
    events_before = store.read_events(transaction["transaction_id"])

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        policy="read_only",
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["message"] == (
        "project_modification_policy=read_only blocks transaction execution"
    )
    assert payload["session_context"]["project_modification_policy"] == "read_only"
    assert store.load(
        transaction["transaction_id"]
    ).state is TransactionState.POLICY_AUTHORIZED
    assert store.read_events(transaction["transaction_id"]) == events_before


def test_preview_without_apply_stays_review_only_under_allow_changes(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview(
        create_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.object.get": create_preview_object_reads(),
                "ak.wwise.core.object.getTypes": [create_type_catalog()],
            }
        ),
        policy="allow_changes",
    )

    assert transaction["status"] == TransactionState.AWAITING_CONFIRMATION.value
    assert transaction["change_requested"] is False
    assert transaction["authorization"] == {
        "mode": "explicit_confirmation",
        "policy": "allow_changes",
        "explicit_confirmation": False,
        "notice_required": True,
        "requires_later_user_message": True,
    }
    assert transaction["next_command"] == expected_transaction_next_command(
        "transaction-show",
        [
            "transaction-show",
            transaction["transaction_id"],
            "--summary-only",
        ],
        requires_later_user_message=True,
    )
    snapshot = TransactionStore(state_dir).load_snapshot(
        transaction["transaction_id"]
    )
    assert snapshot.record.state is TransactionState.AWAITING_CONFIRMATION
    assert snapshot.confirmation_token is not None
    assert [event["event_type"] for event in snapshot.events] == [
        "preview_created",
        "confirmation_requested",
    ]


def test_confirm_rejects_tampered_hash_and_preserves_awaiting_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    store.create_preview("tx-hash", {"operation": "object.setNotes"})
    store.submit_for_confirmation("tx-hash")

    exit_code, payload = execute(
        ["confirm", "tx-hash", "--artifact-hash", "0" * 64],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error_code"] == "ArtifactIntegrityError"
    assert store.load("tx-hash").state is TransactionState.AWAITING_CONFIRMATION


def test_reject_persists_reason_and_is_an_offline_terminal_transition(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    created = store.create_preview("tx-reject", {"operation": "object.delete"})
    store.submit_for_confirmation("tx-reject")

    exit_code, payload = execute(
        ["reject", "tx-reject", "--reason", "target is outside the sandbox"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 0
    assert payload["transaction_id"] == "tx-reject"
    assert payload["state"] == TransactionState.REJECTED.value
    assert payload["artifact_hash"] == created.artifact_hash
    events = store.read_events("tx-reject")
    assert events[-1]["event_type"] == "rejected"
    assert events[-1]["details"] == {"reason": "target is outside the sandbox"}


def test_preview_live_resolves_and_persists_immutable_awaiting_artifact_with_ttl(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": create_preview_object_reads(),
            "ak.wwise.core.object.getTypes": [create_type_catalog()],
        }
    )

    payload = preview(create_request(), tmp_path=tmp_path, state_dir=state_dir, client=client, ttl=90)

    store = TransactionStore(state_dir)
    stored = store.load_preview(payload["transaction_id"])
    record = store.load(payload["transaction_id"])
    assert record.state is TransactionState.AWAITING_CONFIRMATION
    assert stored.artifact_hash == payload["artifact_hash"]
    assert stored.artifact["request"] == create_request()
    assert payload["agent_result"] == {
        "operation": "object.create",
        "transaction_id": payload["transaction_id"],
        "artifact_hash": payload["artifact_hash"],
        "state": TransactionState.AWAITING_CONFIRMATION.value,
        "executed": False,
        "request": stored.artifact["request"],
        "authorization": payload["authorization"],
        "cleanup": payload["cleanup"],
        "next_command": payload["next_command"],
    }
    assert stored.artifact["prepared_operation"]["dispatch"]["uri"] == "ak.wwise.core.object.create"
    created_at = datetime.fromisoformat(stored.artifact["created_at"].replace("Z", "+00:00"))
    expires_at = datetime.fromisoformat(stored.artifact["expires_at"].replace("Z", "+00:00"))
    assert (expires_at - created_at).total_seconds() == 90
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.getTypes",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.get",
    ]
    assert not any(call[0] == "ak.wwise.core.object.create" for call in client.calls)


def test_preview_agent_result_preserves_quotes_backslashes_and_unicode_from_artifact(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    request = set_notes_request()
    request["arguments"]["value"] = '中文“引号” / JSON "quote" / path \\尾部'
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
        }
    )

    payload = preview(request, tmp_path=tmp_path, state_dir=state_dir, client=client)
    stored_request = TransactionStore(state_dir).load_preview(payload["transaction_id"]).artifact["request"]

    assert payload["agent_result"] == {
        "operation": "object.setNotes",
        "transaction_id": payload["transaction_id"],
        "artifact_hash": payload["artifact_hash"],
        "state": TransactionState.AWAITING_CONFIRMATION.value,
        "executed": False,
        "request": stored_request,
        "authorization": payload["authorization"],
        "cleanup": payload["cleanup"],
        "next_command": payload["next_command"],
    }
    encoded = json.dumps(payload["agent_result"], ensure_ascii=False, separators=(",", ":"))
    assert json.loads(encoded) == payload["agent_result"]
    assert payload["agent_result"]["request"]["arguments"]["value"] == request["arguments"]["value"]


def test_preview_rejects_transaction_state_inside_live_project_before_state_write(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "live-project"
    project_root.mkdir()
    state_dir = project_root / ".waapi-state"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [
                project(path=str(project_root / "SampleProject.wproj"))
            ],
        }
    )

    exit_code, payload = execute(
        ["preview", "--request-json", json.dumps(create_request())],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "outside the live Wwise project" in payload["message"]
    assert not state_dir.exists()
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]


@pytest.mark.parametrize(
    "invalid_project",
    (
        {},
        {"id": "", "name": "SampleProject", "path": r"Y:\sandbox\SampleProject.wproj"},
        {"id": "{project}", "name": "SampleProject", "path": r"Y:\sandbox\SampleProject.wproj"},
        {"id": PROJECT_GUID, "name": "", "path": r"Y:\sandbox\SampleProject.wproj"},
        {"id": PROJECT_GUID, "name": "SampleProject", "path": ""},
    ),
)
def test_preview_rejects_project_without_stable_id_name_path_guard(
    tmp_path: Path,
    invalid_project: Mapping[str, Any],
) -> None:
    state_dir = tmp_path / "state"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [invalid_project],
        }
    )

    exit_code, payload = execute(
        ["preview", "--request-json", json.dumps(create_request())],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_PROJECT_RESULT"
    assert payload["details"]["invalid_fields"]
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    assert not any(path.is_file() for path in state_dir.rglob("*"))


@pytest.mark.parametrize(
    "project_rows",
    (
        [{}],
        [{"id": "{project}", "name": "SampleProject", "type": "Project", "path": "\\"}],
        [
            {"id": PROJECT_GUID, "name": "One", "type": "Project", "path": "\\"},
            {"id": "{55555555-5555-5555-5555-555555555555}", "name": "Two", "type": "Project", "path": "\\"},
        ],
    ),
)
def test_2021_preview_rejects_malformed_or_multiple_project_rows(
    tmp_path: Path,
    project_rows: list[Mapping[str, Any]],
) -> None:
    state_dir = tmp_path / "state"
    request = dict(create_request())
    request["version"] = "2021.1"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2021, major=1)],
            "ak.wwise.core.object.get": [{"return": project_rows}],
        }
    )

    exit_code, payload = execute(
        ["preview", "--request-json", json.dumps(request)],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
        version="2021.1",
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_PROJECT_RESULT"
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.object.get",
    ]
    assert not any(path.is_file() for path in state_dir.rglob("*"))


def test_execute_is_blocked_before_mutation_without_confirmation(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": create_preview_object_reads(),
            "ak.wwise.core.object.getTypes": [create_type_catalog()],
        }
    )
    transaction = preview(create_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert not any(call[0] == "ak.wwise.core.object.create" for call in execute_client.calls)
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.AWAITING_CONFIRMATION


def test_execute_project_drift_requires_repreview_without_role_read_or_mutation(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": create_preview_object_reads(),
            "ak.wwise.core.object.getTypes": [create_type_catalog()],
        }
    )
    transaction = preview(create_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    confirm(transaction["transaction_id"], transaction["artifact_hash"], tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project(name="OtherProject", path=r"Y:\other\OtherProject.wproj")],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.REPREVIEW_REQUIRED.value
    assert "agent_result" not in payload
    assert payload["guard_validation"]["error_code"] == "PROJECT_GUARD_MISMATCH"
    assert [call[0] for call in execute_client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.REPREVIEW_REQUIRED


def test_execute_role_drift_requires_repreview_before_mutation(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
        }
    )
    transaction = preview(set_notes_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    confirm(transaction["transaction_id"], transaction["artifact_hash"], tmp_path=tmp_path, state_dir=state_dir)
    moved_path = PARENT_PATH + r"\MovedElsewhere"
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row(path=moved_path)]}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.REPREVIEW_REQUIRED.value
    assert "agent_result" not in payload
    assert payload["role_validation"]["status"] == "repreview_required"
    assert not any(call[0] == "ak.wwise.core.object.setNotes" for call in execute_client.calls)
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.REPREVIEW_REQUIRED


def test_create_execute_persists_result_and_verify_reads_back_returned_guid(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": create_preview_object_reads(),
            "ak.wwise.core.object.getTypes": [create_type_catalog()],
        }
    )
    transaction = preview(create_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    confirm(transaction["transaction_id"], transaction["artifact_hash"], tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [
                {"return": [parent_row()]},
                {"return": []},
                {"return": []},
            ],
            "ak.wwise.core.object.create": [
                {"id": CREATED_GUID, "name": "CreatedByGateway"}
            ],
        }
    )

    exit_code, executed = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )

    assert exit_code == 0, executed
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert executed["dispatch_result"]["result"] == {
        "id": CREATED_GUID,
        "name": "CreatedByGateway",
    }
    mutation_calls = [call for call in execute_client.calls if call[0] == "ak.wwise.core.object.create"]
    assert len(mutation_calls) == 1
    assert mutation_calls[0][1] == {
        "parent": PARENT_GUID,
        "type": "ActorMixer",
        "name": "CreatedByGateway",
        "onNameConflict": "fail",
        "notes": "created in transaction test",
        "autoAddToSourceControl": False,
    }

    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [created_row()]}],
        }
    )
    exit_code, verified = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert exit_code == 0, verified
    assert verified["state"] == TransactionState.VERIFIED.value
    assert verified["verification"]["status"] == "verified"
    assert verified["agent_result"] == {
        "operation": "object.create",
        "transaction_id": transaction["transaction_id"],
        "artifact_hash": transaction["artifact_hash"],
        "state": TransactionState.VERIFIED.value,
        "executed": True,
        "verified": True,
        "request": create_request(),
        "cleanup": verified["cleanup"],
    }
    readback = next(call for call in verify_client.calls if call[0] == "ak.wwise.core.object.get")
    assert readback[1] == {"from": {"id": [CREATED_GUID]}}
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.VERIFIED


def test_large_successful_execute_is_bounded_but_journal_and_verify_stay_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "large-execute-success-state"
    transaction = preview(
        create_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.object.get": create_preview_object_reads(),
                "ak.wwise.core.object.getTypes": [create_type_catalog()],
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    real_validate_roles = waapi_gateway.validate_prepared_roles

    def large_successful_role_validation(
        prepared: Mapping[str, Any],
        *,
        read_call: Any,
    ) -> dict[str, Any]:
        result = dict(real_validate_roles(prepared, read_call=read_call))
        assert result["ok"] is True
        assertions = list(result.get("assertions", []))
        readbacks = list(result.get("readbacks", []))
        assertions.extend(
            {
                "name": f"large import role assertion {index}",
                "passed": True,
                "evidence": {"sealed": "x" * 256, "index": index},
            }
            for index in range(180)
        )
        readbacks.extend(
            {"role": f"import row {index}", "row": {"path": "\\" + "y" * 256}}
            for index in range(120)
        )
        result["assertions"] = assertions
        result["readbacks"] = readbacks
        return result

    monkeypatch.setattr(
        waapi_gateway,
        "validate_prepared_roles",
        large_successful_role_validation,
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.object.get": [
                    {"return": [parent_row()]},
                    {"return": []},
                    {"return": []},
                ],
                "ak.wwise.core.object.create": [
                    {"id": CREATED_GUID, "name": "CreatedByGateway"}
                ],
            }
        ),
    )

    assert execute_exit == 0, execute_payload
    assert execute_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert execute_payload["executed"] is True
    assert execute_payload["verified"] is False
    assert execute_payload["automatic_retry"] is False
    assert execute_payload["next_command"] == expected_transaction_next_command(
        "verify",
        ["verify", transaction["transaction_id"]],
    )
    assert list(execute_payload)[-1] == "next_command"
    assert execute_payload["dispatch_result"]["result"] == {
        "id": CREATED_GUID,
        "name": "CreatedByGateway",
    }
    projection = execute_payload["stdout_projection"]
    assert projection["contract"] == (
        "waapi-skill.transaction-execute-success-summary/v1"
    )
    assert projection["full_role_validation_in_stdout"] is False
    assert projection["full_execution_evidence_persisted"] is True
    assert projection["truncated"] is False
    assert execute_payload["role_validation"]["summary_contract"] == (
        "waapi-skill.transaction-role-validation-summary/v1"
    )
    assert execute_payload["role_validation"]["assertion_count"] >= 180
    assert execute_payload["role_validation"]["readback_count"] >= 120
    assert "assertions" not in execute_payload["role_validation"]
    assert "readbacks" not in execute_payload["role_validation"]
    assert waapi_gateway.gateway_json_document_size(execute_payload) <= (
        waapi_gateway.TRANSACTION_EXECUTE_SUCCESS_STDOUT_BUDGET_BYTES
    )
    assert "agent_result" not in execute_payload

    completion = next(
        event
        for event in TransactionStore(state_dir).read_events(
            transaction["transaction_id"]
        )
        if event["event_type"] == "execution_completed"
    )
    assert len(completion["details"]["role_validation"]["assertions"]) >= 180
    assert len(completion["details"]["role_validation"]["readbacks"]) >= 120
    assert completion["details"]["dispatch_result"]["result"] == {
        "id": CREATED_GUID,
        "name": "CreatedByGateway",
    }

    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.object.get": [{"return": [created_row()]}],
            }
        ),
    )

    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.VERIFIED.value
    assert verify_payload["agent_result"]["transaction_id"] == transaction[
        "transaction_id"
    ]
    assert list(verify_payload)[-1] == "agent_result"


def test_large_successful_verify_is_digest_bounded_and_journal_stays_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "large-verify-success-state"
    transaction = execute_set_notes_successfully(
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    assertions = tuple(
        {
            "name": f"complex postcondition {index}",
            "passed": True,
            "evidence": {
                "index": index,
                "business_state": "x" * 512,
            },
        }
        for index in range(180)
    )
    readbacks = tuple(
        {
            "kind": "complex-object-readback",
            "index": index,
            "row": {
                "id": OBJECT_GUID,
                "path": OBJECT_PATH,
                "payload": "y" * 512,
            },
        }
        for index in range(120)
    )
    full_verification = waapi_gateway.VerificationResult(
        operation="object.setNotes",
        status=TransactionState.VERIFIED.value,
        assertions=assertions,
        readbacks=readbacks,
        message="All complex postconditions matched.",
        verification_strength="operation_specific_readback",
        business_state_verified=True,
    ).as_dict()
    monkeypatch.setattr(
        waapi_gateway,
        "verify_prepared_operation",
        lambda *args, **kwargs: waapi_gateway.VerificationResult(
            operation="object.setNotes",
            status=TransactionState.VERIFIED.value,
            assertions=assertions,
            readbacks=readbacks,
            message="All complex postconditions matched.",
            verification_strength="operation_specific_readback",
            business_state_verified=True,
        ),
    )

    exit_code, payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )

    assert exit_code == 0, payload
    assert payload["status"] == TransactionState.VERIFIED.value
    assert payload["state"] == TransactionState.VERIFIED.value
    assert payload["verified"] is True
    assert payload["executed"] is True
    assert payload["automatic_retry"] is False
    assert payload["verification"] == {
        "summary_contract": (
            "waapi-skill.transaction-verification-result-summary/v1"
        ),
        "contract": full_verification["contract"],
        "operation": "object.setNotes",
        "status": TransactionState.VERIFIED.value,
        "ok": True,
        "verification_strength": "operation_specific_readback",
        "business_state_verified": True,
        "assertion_count": len(assertions),
        "passed_assertion_count": len(assertions),
        "failed_assertion_count": 0,
        "assertions_canonical_sha256": waapi_gateway.canonical_sha256(
            list(assertions)
        ),
        "readback_count": len(readbacks),
        "readbacks_canonical_sha256": waapi_gateway.canonical_sha256(
            list(readbacks)
        ),
        "canonical_sha256": waapi_gateway.canonical_sha256(full_verification),
        "full_evidence_in_stdout": False,
    }
    projection = payload["stdout_projection"]
    assert projection["contract"] == (
        "waapi-skill.transaction-verify-success-summary/v1"
    )
    assert projection["detail_level"] == "digest-verification-evidence"
    assert projection["verification_canonical_sha256"] == (
        waapi_gateway.canonical_sha256(full_verification)
    )
    assert projection["assertion_count"] == len(assertions)
    assert projection["passed_assertion_count"] == len(assertions)
    assert projection["readback_count"] == len(readbacks)
    assert projection["full_verification_evidence_in_stdout"] is False
    assert projection["full_verification_evidence_persisted"] is True
    assert projection["journal_event"] == "verification_recorded"
    assert projection["agent_result_exact"] is True
    assert projection["cleanup_exact"] is True
    assert projection["truncated"] is False
    assert waapi_gateway.gateway_json_document_size(payload) <= (
        waapi_gateway.TRANSACTION_VERIFY_SUCCESS_STDOUT_BUDGET_BYTES
    )
    assert payload["agent_result"] == {
        "operation": "object.setNotes",
        "transaction_id": transaction["transaction_id"],
        "artifact_hash": transaction["artifact_hash"],
        "state": TransactionState.VERIFIED.value,
        "executed": True,
        "request": set_notes_request(),
        "verified": True,
        "cleanup": payload["cleanup"],
    }
    assert list(payload)[-1] == "agent_result"

    verification_event = next(
        event
        for event in TransactionStore(state_dir).read_events(
            transaction["transaction_id"]
        )
        if event["event_type"] == "verification_recorded"
    )
    journal_verification = verification_event["details"]["verification"]
    assert journal_verification == full_verification
    assert len(journal_verification["assertions"]) == len(assertions)
    assert len(journal_verification["readbacks"]) == len(readbacks)
    assert waapi_gateway.canonical_sha256(journal_verification) == (
        projection["verification_canonical_sha256"]
    )


@pytest.mark.parametrize(
    "tamper",
    (
        "top-level-status",
        "top-level-state",
        "top-level-verified",
        "top-level-result-schema-checked",
        "verification-status",
        "verification-business-state",
        "failed-assertion",
        "verification-strength",
        "agent-result-state",
        "agent-result-verified",
        "agent-result-operation",
        "agent-result-cleanup",
    ),
)
def test_successful_verify_projection_rejects_tampered_success(
    tamper: str,
) -> None:
    cleanup = {
        "status": "not_required",
        "projection": {"status": "not_required"},
    }
    verification = waapi_gateway.VerificationResult(
        operation="object.setNotes",
        status=TransactionState.VERIFIED.value,
        assertions=({"name": "notes match", "passed": True},),
        readbacks=({"kind": "object-readback", "id": OBJECT_GUID},),
        business_state_verified=True,
    ).as_dict()
    payload: dict[str, Any] = {
        "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
        "command": "verify",
        "ok": True,
        "status": TransactionState.VERIFIED.value,
        "transaction_id": "tx-verified",
        "artifact_hash": "a" * 64,
        "state": TransactionState.VERIFIED.value,
        "verification": verification,
        "guard_validation": {"ok": True},
        "project_call": {"ok": True},
        "executed": True,
        "verified": True,
        "result_schema_checked": False,
        "verification_strength": "operation_specific_readback",
        "cleanup": cleanup,
        "automatic_retry": False,
        "agent_result": {
            "operation": "object.setNotes",
            "transaction_id": "tx-verified",
            "artifact_hash": "a" * 64,
            "state": TransactionState.VERIFIED.value,
            "executed": True,
            "request": set_notes_request(),
            "verified": True,
            "cleanup": cleanup,
        },
    }
    if tamper == "top-level-status":
        payload["status"] = TransactionState.RESULT_SCHEMA_CHECKED.value
    elif tamper == "top-level-state":
        payload["state"] = TransactionState.EXECUTED_UNVERIFIED.value
    elif tamper == "top-level-verified":
        payload["verified"] = False
    elif tamper == "top-level-result-schema-checked":
        payload["result_schema_checked"] = True
    elif tamper == "verification-status":
        payload["verification"]["status"] = "verification_failed"
    elif tamper == "verification-business-state":
        payload["verification"]["business_state_verified"] = False
    elif tamper == "failed-assertion":
        payload["verification"]["assertions"][0]["passed"] = False
    elif tamper == "verification-strength":
        payload["verification_strength"] = "result_schema"
    elif tamper == "agent-result-state":
        payload["agent_result"]["state"] = TransactionState.EXECUTED_UNVERIFIED.value
    elif tamper == "agent-result-verified":
        payload["agent_result"]["verified"] = False
    elif tamper == "agent-result-operation":
        payload["agent_result"]["operation"] = "object.create"
    elif tamper == "agent-result-cleanup":
        payload["agent_result"]["cleanup"] = {"status": "pending"}

    with pytest.raises(waapi_gateway.GatewayResultShapeError) as caught:
        waapi_gateway.project_successful_transaction_verify_payload(payload)

    assert caught.value.error_code == "INVALID_VERIFY_SUCCESS_PROJECTION"
    assert caught.value.details["reasons"]


def test_native_directive_boundary_records_bounded_weak_success_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "native-directive-boundary-state"
    transaction = execute_set_notes_successfully(
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    assertions = tuple(
        {
            "name": f"bounded native directive assertion {index}",
            "passed": True,
            "evidence": {
                "index": index,
                "bounded_readback": "x" * 512,
            },
        }
        for index in range(180)
    )
    readbacks = tuple(
        {
            "kind": "native-directive-target-readback",
            "index": index,
            "row": {
                "id": OBJECT_GUID,
                "path": OBJECT_PATH,
                "payload": "y" * 512,
            },
        }
        for index in range(120)
    )
    weak_verification = waapi_gateway.VerificationResult(
        operation="object.setNotes",
        status=TransactionState.RESULT_SCHEMA_CHECKED.value,
        assertions=assertions,
        readbacks=readbacks,
        message=(
            "Target readbacks passed; the native directive remains an explicit "
            "business-state boundary."
        ),
        verification_strength=(
            "operation_specific_readback_with_explicit_native_directive_boundary"
        ),
        business_state_verified=False,
    )
    full_verification = weak_verification.as_dict()
    monkeypatch.setattr(
        waapi_gateway,
        "verify_prepared_operation",
        lambda *args, **kwargs: weak_verification,
    )

    exit_code, payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )

    assert exit_code == 0, payload
    assert payload["ok"] is True
    assert payload["status"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert payload["verified"] is False
    assert payload["result_schema_checked"] is True
    assert payload["verification"] == {
        "summary_contract": (
            "waapi-skill.transaction-verification-result-summary/v1"
        ),
        "contract": full_verification["contract"],
        "operation": "object.setNotes",
        "status": TransactionState.RESULT_SCHEMA_CHECKED.value,
        "ok": True,
        "verification_strength": (
            "operation_specific_readback_with_explicit_native_directive_boundary"
        ),
        "business_state_verified": False,
        "assertion_count": len(assertions),
        "passed_assertion_count": len(assertions),
        "failed_assertion_count": 0,
        "assertions_canonical_sha256": waapi_gateway.canonical_sha256(
            list(assertions)
        ),
        "readback_count": len(readbacks),
        "readbacks_canonical_sha256": waapi_gateway.canonical_sha256(
            list(readbacks)
        ),
        "canonical_sha256": waapi_gateway.canonical_sha256(full_verification),
        "full_evidence_in_stdout": False,
    }
    assert payload["verification_strength"] == (
        "operation_specific_readback_with_explicit_native_directive_boundary"
    )
    projection = payload["stdout_projection"]
    assert projection["detail_level"] == "digest-verification-evidence"
    assert projection["verification_canonical_sha256"] == (
        waapi_gateway.canonical_sha256(full_verification)
    )
    assert projection["assertion_count"] == len(assertions)
    assert projection["passed_assertion_count"] == len(assertions)
    assert projection["readback_count"] == len(readbacks)
    assert projection["full_verification_evidence_in_stdout"] is False
    assert projection["full_verification_evidence_persisted"] is True
    assert projection["journal_event"] == "verification_recorded"
    assert projection["agent_result_exact"] is True
    assert projection["cleanup_exact"] is True
    assert projection["truncated"] is False
    assert waapi_gateway.gateway_json_document_size(payload) <= (
        waapi_gateway.TRANSACTION_VERIFY_SUCCESS_STDOUT_BUDGET_BYTES
    )
    assert payload["agent_result"] == {
        "operation": "object.setNotes",
        "transaction_id": transaction["transaction_id"],
        "artifact_hash": transaction["artifact_hash"],
        "state": TransactionState.RESULT_SCHEMA_CHECKED.value,
        "executed": True,
        "request": set_notes_request(),
        "verified": False,
        "cleanup": payload["cleanup"],
    }
    assert list(payload)[-1] == "agent_result"

    verification_event = next(
        event
        for event in TransactionStore(state_dir).read_events(
            transaction["transaction_id"]
        )
        if event["event_type"] == "verification_recorded"
    )
    journal_verification = verification_event["details"]["verification"]
    assert journal_verification == full_verification
    assert len(journal_verification["assertions"]) == len(assertions)
    assert len(journal_verification["readbacks"]) == len(readbacks)
    assert waapi_gateway.canonical_sha256(journal_verification) == (
        projection["verification_canonical_sha256"]
    )


@pytest.mark.parametrize(
    "tamper",
    (
        "top-level-status",
        "top-level-state",
        "top-level-verified",
        "top-level-result-schema-checked",
        "verification-status",
        "verification-business-state",
        "failed-assertion",
        "verification-strength",
        "agent-result-state",
        "agent-result-verified",
    ),
)
def test_weak_verify_projection_rejects_tampered_success(tamper: str) -> None:
    cleanup = {
        "status": "not_required",
        "projection": {"status": "not_required"},
    }
    verification = waapi_gateway.VerificationResult(
        operation="object.setNotes",
        status=TransactionState.RESULT_SCHEMA_CHECKED.value,
        assertions=({"name": "bounded readback passed", "passed": True},),
        readbacks=({"kind": "object-readback", "id": OBJECT_GUID},),
        verification_strength=(
            "operation_specific_readback_with_explicit_native_directive_boundary"
        ),
        business_state_verified=False,
    ).as_dict()
    payload: dict[str, Any] = {
        "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
        "command": "verify",
        "ok": True,
        "status": TransactionState.RESULT_SCHEMA_CHECKED.value,
        "transaction_id": "tx-result-schema-checked",
        "artifact_hash": "e" * 64,
        "state": TransactionState.RESULT_SCHEMA_CHECKED.value,
        "verification": verification,
        "guard_validation": {"ok": True},
        "project_call": {"ok": True},
        "executed": True,
        "verified": False,
        "result_schema_checked": True,
        "verification_strength": (
            "operation_specific_readback_with_explicit_native_directive_boundary"
        ),
        "cleanup": cleanup,
        "automatic_retry": False,
        "agent_result": {
            "operation": "object.setNotes",
            "transaction_id": "tx-result-schema-checked",
            "artifact_hash": "e" * 64,
            "state": TransactionState.RESULT_SCHEMA_CHECKED.value,
            "executed": True,
            "request": set_notes_request(),
            "verified": False,
            "cleanup": cleanup,
        },
    }
    if tamper == "top-level-status":
        payload["status"] = TransactionState.VERIFIED.value
    elif tamper == "top-level-state":
        payload["state"] = TransactionState.VERIFIED.value
    elif tamper == "top-level-verified":
        payload["verified"] = True
    elif tamper == "top-level-result-schema-checked":
        payload["result_schema_checked"] = False
    elif tamper == "verification-status":
        payload["verification"]["status"] = TransactionState.VERIFIED.value
    elif tamper == "verification-business-state":
        payload["verification"]["business_state_verified"] = True
    elif tamper == "failed-assertion":
        payload["verification"]["assertions"][0]["passed"] = False
    elif tamper == "verification-strength":
        payload["verification_strength"] = "operation_specific_readback"
    elif tamper == "agent-result-state":
        payload["agent_result"]["state"] = TransactionState.VERIFIED.value
    elif tamper == "agent-result-verified":
        payload["agent_result"]["verified"] = True

    with pytest.raises(waapi_gateway.GatewayResultShapeError) as caught:
        waapi_gateway.project_successful_transaction_verify_payload(payload)

    assert caught.value.error_code == "INVALID_VERIFY_SUCCESS_PROJECTION"
    assert caught.value.details["reasons"]


def test_verify_transport_cleanup_failure_keeps_full_unprojected_success_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DisconnectFailureClient(FakeClient):
        def disconnect(self) -> None:
            raise RuntimeError("disconnect failed after verification completed")

    cleanup = {
        "status": "not_required",
        "projection": {"status": "not_required"},
    }
    verification = waapi_gateway.VerificationResult(
        operation="object.setNotes",
        status=TransactionState.VERIFIED.value,
        assertions=(
            {
                "name": "large successful assertion",
                "passed": True,
                "evidence": "x" * 40_000,
            },
        ),
        readbacks=(),
        business_state_verified=True,
    ).as_dict()
    business_result = {
        "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
        "command": "verify",
        "ok": True,
        "status": TransactionState.VERIFIED.value,
        "transaction_id": "tx-cleanup-boundary",
        "artifact_hash": "b" * 64,
        "state": TransactionState.VERIFIED.value,
        "verification": verification,
        "guard_validation": {"ok": True},
        "project_call": {"ok": True},
        "executed": True,
        "verified": True,
        "result_schema_checked": False,
        "verification_strength": "operation_specific_readback",
        "cleanup": cleanup,
        "automatic_retry": False,
        "agent_result": {
            "operation": "object.setNotes",
            "transaction_id": "tx-cleanup-boundary",
            "artifact_hash": "b" * 64,
            "state": TransactionState.VERIFIED.value,
            "executed": True,
            "request": set_notes_request(),
            "verified": True,
            "cleanup": cleanup,
        },
    }
    monkeypatch.setattr(
        waapi_gateway,
        "dispatch_command",
        lambda *args, **kwargs: business_result,
    )
    client = DisconnectFailureClient(
        {"ak.wwise.core.getInfo": [live_info()]}
    )

    exit_code, payload = execute(
        ["verify", "tx-cleanup-boundary"],
        tmp_path=tmp_path,
        state_dir=tmp_path / "state",
        client=client,
    )

    assert exit_code == 2
    assert payload["ok"] is True
    assert payload["status"] == TransactionState.VERIFIED.value
    assert payload["verification"] == verification
    assert "stdout_projection" not in payload
    assert payload["details"]["cleanup_failure"] == {
        "error_code": "RuntimeError",
        "message": "disconnect failed after verification completed",
    }
    assert list(payload)[-1] == "agent_result"


@pytest.mark.parametrize(
    (
        "status",
        "state",
        "ok",
        "verified",
        "result_schema_checked",
        "cleanup_status",
        "expected_projection",
    ),
    (
        (
            "verification_failed",
            TransactionState.VERIFICATION_FAILED.value,
            False,
            False,
            False,
            "not_required",
            False,
        ),
        (
            "indeterminate",
            TransactionState.INDETERMINATE.value,
            False,
            False,
            False,
            "unknown",
            False,
        ),
        (
            "result_schema_checked",
            TransactionState.RESULT_SCHEMA_CHECKED.value,
            True,
            False,
            True,
            "not_required",
            True,
        ),
        (
            "verified",
            TransactionState.VERIFIED.value,
            True,
            True,
            False,
            "unknown",
            False,
        ),
    ),
)
def test_verify_projects_only_safe_terminal_success_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    state: str,
    ok: bool,
    verified: bool,
    result_schema_checked: bool,
    cleanup_status: str,
    expected_projection: bool,
) -> None:
    verification = {
        "operation": "object.setNotes",
        "status": status,
        "ok": ok,
        "assertions": [
            {
                "name": "boundary evidence remains complete",
                "passed": ok,
                "evidence": "x" * 8_000,
            }
        ],
        "readbacks": [],
        "verification_strength": (
            "operation_specific_readback"
            if status != "result_schema_checked"
            else "complete_reflected_schema"
        ),
        "business_state_verified": verified,
    }
    cleanup = {
        "status": cleanup_status,
        "projection": {"status": cleanup_status},
    }
    business_result: dict[str, Any] = {
        "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
        "command": "verify",
        "ok": ok,
        "status": status,
        "transaction_id": f"tx-{status}-{cleanup_status}",
        "artifact_hash": "c" * 64,
        "state": state,
        "verification": verification,
        "guard_validation": {"ok": True},
        "project_call": {"ok": True},
        "executed": True,
        "verified": verified,
        "result_schema_checked": result_schema_checked,
        "verification_strength": verification["verification_strength"],
        "cleanup": cleanup,
        "automatic_retry": False,
    }
    if ok:
        business_result["agent_result"] = {
            "operation": "object.setNotes",
            "transaction_id": business_result["transaction_id"],
            "artifact_hash": business_result["artifact_hash"],
            "state": state,
            "executed": True,
            "request": set_notes_request(),
            "verified": verified,
            "cleanup": cleanup,
        }
    monkeypatch.setattr(
        waapi_gateway,
        "dispatch_command",
        lambda *args, **kwargs: business_result,
    )

    exit_code, payload = execute(
        ["verify", business_result["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=tmp_path / f"state-{status}-{cleanup_status}",
        client=FakeClient({"ak.wwise.core.getInfo": [live_info()]}),
    )

    assert exit_code == (0 if ok else 2)
    assert payload["status"] == status
    assert payload["state"] == state
    assert payload["verification"] == verification
    assert ("stdout_projection" in payload) is expected_projection


@pytest.mark.parametrize(
    ("ok", "status"),
    [
        (False, "executed_unverified"),
        (True, "indeterminate"),
    ],
)
def test_successful_execute_projection_rejects_non_success_states(
    ok: bool,
    status: str,
) -> None:
    with pytest.raises(waapi_gateway.GatewayResultShapeError) as caught:
        waapi_gateway.project_successful_transaction_execute_payload(
            {
                "ok": ok,
                "status": status,
                "role_validation": {"ok": True},
            }
        )
    assert caught.value.error_code == "INVALID_EXECUTE_SUCCESS_PROJECTION"


def test_minimal_execute_projection_keeps_the_exact_verify_continuation() -> None:
    next_command = expected_transaction_next_command(
        "verify",
        ["verify", "tx-minimal-projection"],
    )
    payload = waapi_gateway.project_successful_transaction_execute_payload(
        {
            "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
            "command": "execute",
            "ok": True,
            "status": "executed_unverified",
            "transaction_id": "tx-minimal-projection",
            "state": TransactionState.EXECUTED_UNVERIFIED.value,
            "artifact_hash": "d" * 64,
            "dispatch_result": {
                "ok": True,
                "status": "ok",
                "result": {"bulk": "x" * 40_000},
            },
            "role_validation": {"ok": True, "assertions": [], "readbacks": []},
            "executed": True,
            "verified": False,
            "automatic_retry": False,
            "next_command": next_command,
            "unknown_bulk_component": "y" * 40_000,
        }
    )

    assert payload["stdout_projection"]["detail_level"] == "minimal-allowlist-digest"
    assert payload["next_command"] == next_command
    assert "unknown_bulk_component" not in payload


def test_verify_failed_postcondition_becomes_terminal_verification_failed(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    transaction = execute_set_notes_successfully(tmp_path=tmp_path, state_dir=state_dir)
    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row(notes="not the requested value")]}],
        }
    )

    exit_code, payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.VERIFICATION_FAILED.value
    assert payload["verification"]["status"] == "verification_failed"
    assert "stdout_projection" not in payload
    assert "agent_result" not in payload
    assert any(
        assertion["name"] == "notes match exactly" and assertion["passed"] is False
        for assertion in payload["verification"]["assertions"]
    )
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.VERIFICATION_FAILED


def test_verify_readback_exception_is_deferred_for_explicit_manual_retry(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    transaction = execute_set_notes_successfully(tmp_path=tmp_path, state_dir=state_dir)
    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [],
        },
        errors={"ak.wwise.core.object.get": [RuntimeError("readback connection failed")]},
    )

    exit_code, payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert payload["status"] == "verification_deferred"
    assert "agent_result" not in payload
    assert payload["automatic_retry"] is False
    assert payload["manual_verification_retry_allowed"] is True
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.EXECUTED_UNVERIFIED


def test_execute_exception_is_indeterminate_and_a_second_execute_never_retries(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
        }
    )
    transaction = preview(set_notes_request(), tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    confirm(transaction["transaction_id"], transaction["artifact_hash"], tmp_path=tmp_path, state_dir=state_dir)
    first_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
            "ak.wwise.core.object.setNotes": [],
        },
        errors={"ak.wwise.core.object.setNotes": [RuntimeError("connection lost after dispatch")]},
    )

    first_exit, first_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=first_client,
    )

    assert first_exit == 2
    assert first_payload["state"] == TransactionState.INDETERMINATE.value
    assert "stdout_projection" not in first_payload
    assert "agent_result" not in first_payload
    assert len([call for call in first_client.calls if call[0] == "ak.wwise.core.object.setNotes"]) == 1
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.INDETERMINATE

    second_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    second_exit, second_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=second_client,
    )

    assert second_exit == 2
    assert second_payload["ok"] is False
    assert "stdout_projection" not in second_payload
    assert "agent_result" not in second_payload
    assert not any(call[0] == "ak.wwise.core.object.setNotes" for call in second_client.calls)
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is TransactionState.INDETERMINATE


def test_generic_manifest_call_runs_full_preview_confirm_execute_verify_chain(tmp_path: Path) -> None:
    state_dir = tmp_path / "generic-state"
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    transaction = preview(
        generic_manifest_call_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
    )
    stored = TransactionStore(state_dir).load_preview(transaction["transaction_id"])
    assert stored.artifact["prepared_operation"]["dispatch"] == {
        "uri": "ak.wwise.core.project.save",
        "args": {},
        "options": {},
    }
    assert transaction["preview_summary"]["dispatch"] == {
        "uri": "ak.wwise.core.project.save",
        "args": {},
        "options": {},
    }
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.project.save": [{}],
        }
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert [call[0] for call in execute_client.calls].count("ak.wwise.core.project.save") == 1

    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["verified"] is False
    assert verify_payload["result_schema_checked"] is True
    assert verify_payload["verification_strength"] == "complete_reflected_schema"
    assert verify_payload["stdout_projection"]["contract"] == (
        "waapi-skill.transaction-verify-success-summary/v1"
    )
    assert verify_payload["stdout_projection"]["agent_result_exact"] is True
    assert verify_payload["stdout_projection"]["cleanup_exact"] is True
    assert verify_payload["agent_result"]["result"] == {}
    assert verify_payload["agent_result"]["verified"] is False
    assert verify_payload["agent_result"]["request"] == generic_manifest_call_request()
    assert list(verify_payload)[-1] == "agent_result"


def test_object_create_plugin_runs_full_preview_confirm_execute_verify_chain(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "create-plugin-state"
    create_plugin_request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.createPlugin",
        "arguments": {
            "target": {"kind": "id", "value": OBJECT_GUID},
            "plugin": {
                "kind": "source",
                "name": "Generated Tone",
                "class_id": 123_456,
            },
        },
    }
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [
                {"return": [object_row()]},
                {"return": []},
            ],
        }
    )
    transaction = preview(
        create_plugin_request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
    )
    stored = TransactionStore(state_dir).load_preview(
        transaction["transaction_id"]
    )
    assert stored.artifact["prepared_operation"]["dispatch"] == {
        "uri": "ak.wwise.core.object.set",
        "args": {
            "objects": [
                {
                    "object": OBJECT_GUID,
                    "onNameConflict": "fail",
                    "children": [
                        {
                            "type": "Source",
                            "name": "Generated Tone",
                            "classId": 123_456,
                        }
                    ],
                }
            ],
            "autoAddToSourceControl": False,
        },
        "options": {},
    }
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    execution_result = {
        "objects": [
            {
                "id": OBJECT_GUID,
                "children": [
                    {
                        "id": CREATED_GUID,
                        "name": "Generated Tone",
                        "type": "Source",
                    }
                ],
            }
        ]
    }
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [
                {"return": [object_row()]},
                {"return": []},
            ],
            "ak.wwise.core.object.set": [execution_result],
        }
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert [call[0] for call in execute_client.calls].count(
        "ak.wwise.core.object.set"
    ) == 1

    plugin_row = {
        "id": CREATED_GUID,
        "name": "Generated Tone",
        "type": "Source",
        "classId": 123_456,
        "parent": {"id": OBJECT_GUID},
        "owner": {"id": OBJECT_GUID},
    }
    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [plugin_row]}],
        }
    )
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.VERIFIED.value
    assert verify_payload["verified"] is True
    assert verify_payload["verification"]["business_state_verified"] is True
    assert verify_payload["verification"]["verification_strength"] == (
        "operation_specific_readback"
    )
    assert verify_payload["agent_result"]["request"] == create_plugin_request
    assert verify_payload["agent_result"]["verified"] is True


def test_lifecycle_opener_cleanup_spec_survives_the_full_gateway_chain(tmp_path: Path) -> None:
    state_dir = tmp_path / "load-bank-state"
    sound_bank = {"name": "Main", "ids": [1, 2]}
    request = generic_public_call_request(
        "ak.soundengine.loadBank",
        {"soundBank": sound_bank},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    preview_cleanup = transaction["cleanup"]

    assert transaction["preview_summary"]["cleanup"] == preview_cleanup
    assert transaction["agent_result"]["cleanup"] == preview_cleanup
    assert preview_cleanup["status"] == "not_started"
    assert preview_cleanup["projection"]["status"] == "not_started"
    assert preview_cleanup["spec"]["companion_request"] == {
        "api": "ak.soundengine.unloadBank",
        "args": {"soundBank": sound_bank},
        "options": {},
    }
    show_exit, show_payload = execute(
        ["transaction-show", transaction["transaction_id"], "--summary-only"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    assert show_exit == 0, show_payload
    assert show_payload["preview_summary"]["cleanup"] == preview_cleanup
    assert show_payload["preview_summary"]["cleanup"]["spec"] == preview_cleanup["spec"]
    assert show_payload["preview_summary"]["cleanup"]["spec"]["companion_request"] == {
        "api": "ak.soundengine.unloadBank",
        "args": {"soundBank": sound_bank},
        "options": {},
    }

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.soundengine.loadBank": [{}],
            }
        ),
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["cleanup"]["status"] == "pending"
    assert execute_payload["cleanup"]["projection"]["status"] == "pending"

    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["cleanup"]["status"] == "pending"
    assert verify_payload["cleanup"]["projection"]["status"] == "pending"
    assert verify_payload["agent_result"]["cleanup"] == verify_payload["cleanup"]

    cleanup_payloads = (
        preview_cleanup,
        transaction["preview_summary"]["cleanup"],
        transaction["agent_result"]["cleanup"],
        execute_payload["cleanup"],
        verify_payload["cleanup"],
        verify_payload["agent_result"]["cleanup"],
    )
    expected_spec = preview_cleanup["spec"]
    expected_digest = expected_spec["spec_sha256"]
    assert len(expected_digest) == 64
    assert all(cleanup["spec"] == expected_spec for cleanup in cleanup_payloads)
    assert all(
        cleanup["projection"]["cleanup_spec_sha256"] == expected_digest
        for cleanup in cleanup_payloads
    )
    stored_spec = TransactionStore(state_dir).load_preview(
        transaction["transaction_id"]
    ).artifact["prepared_operation"]["cleanup"]
    assert stored_spec == expected_spec


def test_load_bank_cleanup_binding_cannot_be_overridden_by_execution_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "load-bank-result-override-state"
    confirmed_sound_bank = {"name": "Confirmed", "ids": [7, 8]}
    request = generic_public_call_request(
        "ak.soundengine.loadBank",
        {"soundBank": confirmed_sound_bank},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    real_dispatch = waapi_gateway.dispatch

    def injected_dispatch(
        dispatcher: Any,
        api: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if api == "ak.soundengine.loadBank":
            return {
                "ok": True,
                "api": api,
                "version": "2025.1",
                "result": {
                    "soundBank": {"name": "Injected", "ids": [99]},
                    "transport": 73,
                },
                "error_code": None,
                "message": "program-injected result",
            }
        return real_dispatch(dispatcher, api, **kwargs)

    monkeypatch.setattr(waapi_gateway, "dispatch", injected_dispatch)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2025)],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=execute_client,
    )

    assert execute_exit == 0, execute_payload
    assert execute_payload["dispatch_result"]["result"]["soundBank"]["name"] == "Injected"
    assert execute_payload["cleanup"]["projection"]["companion_request"] == {
        "api": "ak.soundengine.unloadBank",
        "args": {"soundBank": confirmed_sound_bank},
        "options": {},
    }
    assert execute_payload["cleanup"]["spec"]["companion_request"]["args"] == {
        "soundBank": confirmed_sound_bank
    }
    assert not any(call[0] == "ak.soundengine.loadBank" for call in execute_client.calls)
    stored_spec = TransactionStore(state_dir).load_preview(
        transaction["transaction_id"]
    ).artifact["prepared_operation"]["cleanup"]
    assert stored_spec == transaction["cleanup"]["spec"]
    assert stored_spec["companion_request"]["args"] == {"soundBank": confirmed_sound_bank}


def test_transport_create_materializes_destroy_request_in_execute_verify_and_agent_result(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "transport-state"
    transport_id = 73
    request = generic_public_call_request(
        "ak.wwise.core.transport.create",
        {"object": OBJECT_GUID},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    immutable_spec = transaction["cleanup"]["spec"]

    assert transaction["cleanup"]["status"] == "not_started"
    assert immutable_spec["binding"]["materialized"] is False
    assert transaction["cleanup"]["projection"]["companion_request"]["args"] == {}

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.transport.create": [{"transport": transport_id}],
            }
        ),
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["cleanup"]["status"] == "pending"
    assert execute_payload["cleanup"]["spec"] == immutable_spec
    assert execute_payload["cleanup"]["spec"]["binding"]["materialized"] is False
    assert execute_payload["cleanup"]["projection"]["binding"]["materialized"] is True
    assert execute_payload["cleanup"]["projection"]["companion_request"] == {
        "api": "ak.wwise.core.transport.destroy",
        "args": {"transport": transport_id},
        "options": {},
    }

    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2025)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.transport.getList": [
                {"list": [{"transport": transport_id, "object": OBJECT_GUID, "gameObject": 1}]}
            ],
            "ak.wwise.core.transport.getState": [{"state": "stopped"}],
        }
    )
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=verify_client,
    )

    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.VERIFIED.value
    assert verify_payload["cleanup"]["spec"] == immutable_spec
    assert verify_payload["cleanup"]["projection"]["companion_request"]["args"] == {
        "transport": transport_id
    }
    assert verify_payload["agent_result"]["cleanup"] == verify_payload["cleanup"]
    assert verify_payload["agent_result"]["cleanup"]["projection"]["binding"]["materialized"] is True
    assert (
        verify_payload["cleanup"]["projection"]["cleanup_spec_sha256"]
        == immutable_spec["spec_sha256"]
    )
    assert (
        TransactionStore(state_dir)
        .load_preview(transaction["transaction_id"])
        .artifact["prepared_operation"]["cleanup"]
        == immutable_spec
    )
    assert (
        "ak.wwise.core.transport.getState",
        {"transport": transport_id},
        {},
    ) in verify_client.calls


def test_transport_verify_guard_failure_keeps_result_bound_destroy_request(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "transport-guard-failure-state"
    transport_id = 73
    transaction = preview_and_confirm_public_call(
        generic_public_call_request(
            "ak.wwise.core.transport.create",
            {"object": OBJECT_GUID},
        ),
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.transport.create": [{"transport": transport_id}],
            }
        ),
    )
    assert execute_exit == 0, execute_payload

    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [
                    project(
                        project_id="{99999999-9999-9999-9999-999999999999}",
                        name="DifferentProject",
                        path=r"Y:\other\DifferentProject.wproj",
                    )
                ],
            }
        ),
    )

    assert verify_exit == 2
    assert verify_payload["status"] == "verification_deferred"
    assert verify_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert verify_payload["automatic_retry"] is False
    assert verify_payload["manual_verification_retry_allowed"] is True
    assert verify_payload["cleanup"]["status"] == "pending"
    assert verify_payload["cleanup"]["projection"]["binding"]["materialized"] is True
    assert verify_payload["cleanup"]["projection"]["companion_request"] == {
        "api": "ak.wwise.core.transport.destroy",
        "args": {"transport": transport_id},
        "options": {},
    }


def test_successful_mutation_with_journal_failure_keeps_execution_and_cleanup_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "post-success-journal-failure-state"
    transport_id = 73
    transaction = preview_and_confirm_public_call(
        generic_public_call_request(
            "ak.wwise.core.transport.create",
            {"object": OBJECT_GUID},
        ),
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    def fail_after_waapi_success(
        _store: TransactionStore,
        _transaction_id: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> Any:
        assert details is not None
        assert details["dispatch_result"]["result"] == {"transport": transport_id}
        raise OSError("disk full after WAAPI success")

    monkeypatch.setattr(
        waapi_gateway.TransactionStore,
        "mark_executed_unverified",
        fail_after_waapi_success,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2025)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.transport.create": [{"transport": transport_id}],
        }
    )

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=execute_client,
    )

    assert execute_exit == 2
    assert execute_payload["ok"] is False
    assert execute_payload["status"] == "execution_succeeded_persistence_failed"
    assert execute_payload["error_code"] == "TRANSACTION_PERSISTENCE_FAILED"
    assert execute_payload["state"] == TransactionState.EXECUTING.value
    assert execute_payload["executed"] is True
    assert execute_payload["verified"] is False
    assert execute_payload["automatic_retry"] is False
    assert execute_payload["dispatch_result"]["result"] == {"transport": transport_id}
    assert execute_payload["details"]["attempted_transition"] == (
        TransactionState.EXECUTED_UNVERIFIED.value
    )
    assert execute_payload["details"]["observed_durable_state"] == (
        TransactionState.EXECUTING.value
    )
    assert execute_payload["cleanup"]["status"] == "pending"
    assert execute_payload["cleanup"]["projection"]["companion_request"] == {
        "api": "ak.wwise.core.transport.destroy",
        "args": {"transport": transport_id},
        "options": {},
    }
    assert [call[0] for call in execute_client.calls].count(
        "ak.wwise.core.transport.create"
    ) == 1
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is (
        TransactionState.EXECUTING
    )


def test_transaction_readback_rejects_an_unreviewed_uri_before_dispatch(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.project.save": [{}]})
    dispatcher = waapi_gateway.WwiseDispatcher(client=client)
    connection = waapi_gateway.GatewayConnection(
        host="127.0.0.1",
        port=31337,
        version_hint="2025.1",
        evidence_dir=tmp_path / "evidence",
        timeout=10.0,
        deadline=waapi_gateway.GatewayDeadline.start(10.0),
    )
    read_call = waapi_gateway.transaction_read_call(
        dispatcher,
        connection=connection,
        version="2025.1",
    )

    with pytest.raises(waapi_gateway.OperationContractError) as caught:
        read_call("ak.wwise.core.project.save", {}, {})

    assert caught.value.error_code == "UNREVIEWED_READBACK_URI"
    assert caught.value.details == {"uri": "ak.wwise.core.project.save"}
    assert client.calls == []


def test_transaction_readback_normalizes_only_single_exact_unknown_object(
    tmp_path: Path,
) -> None:
    missing_id = "{4AB57FDF-0640-4806-98BE-A3E0C5FB1B91}"
    client = FakeClient(
        {},
        errors={
            "ak.wwise.core.object.get": [
                WaapiRequestFailed(
                    "ak.wwise.query.unknown_object",
                    {
                        "message": "from id object is unknown",
                        "details": {"procedureUri": "ak.wwise.core.object.get"},
                    },
                ),
                WaapiRequestFailed("ak.wwise.transport.closed"),
            ]
        },
    )
    dispatcher = waapi_gateway.WwiseDispatcher(client=client)
    connection = waapi_gateway.GatewayConnection(
        host="127.0.0.1",
        port=31337,
        version_hint="2022.1",
        evidence_dir=tmp_path / "evidence",
        timeout=10.0,
        deadline=waapi_gateway.GatewayDeadline.start(10.0),
    )
    read_call = waapi_gateway.transaction_read_call(
        dispatcher,
        connection=connection,
        version="2022.1",
    )

    assert read_call(
        "ak.wwise.core.object.get",
        {"from": {"id": [missing_id]}},
        {"return": ["id", "path"]},
    ) == {"return": []}

    with pytest.raises(waapi_gateway.OperationContractError) as caught:
        read_call(
            "ak.wwise.core.object.get",
            {"from": {"id": [missing_id]}},
            {"return": ["id", "path"]},
        )

    assert caught.value.error_code == "READBACK_FAILED"
    assert caught.value.details["call"]["waapi_error_uri"] == "ak.wwise.transport.closed"


def test_lifecycle_opener_execution_exception_reports_unknown_cleanup(tmp_path: Path) -> None:
    state_dir = tmp_path / "indeterminate-cleanup-state"
    request = generic_public_call_request(
        "ak.soundengine.loadBank",
        {"soundBank": "Main"},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.soundengine.loadBank": [],
            },
            errors={
                "ak.soundengine.loadBank": [RuntimeError("connection lost after dispatch")]
            },
        ),
    )

    assert execute_exit == 2
    assert execute_payload["state"] == TransactionState.INDETERMINATE.value
    assert execute_payload["cleanup"]["status"] == "unknown"
    assert execute_payload["cleanup"]["projection"]["phase"] == "indeterminate"
    assert execute_payload["cleanup"]["projection"]["status"] == "unknown"
    assert execute_payload["cleanup"]["spec"] == transaction["cleanup"]["spec"]
    assert "agent_result" not in execute_payload


def test_work_unit_load_is_available_reversal_through_the_full_gateway_chain(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "work-unit-load-state"
    request = generic_public_call_request(
        "ak.wwise.core.workUnit.load",
        {"object": OBJECT_GUID},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert transaction["cleanup"]["status"] == "available_reversal"
    assert transaction["cleanup"]["spec"]["cleanup_requirement"] == "available_reversal"
    assert transaction["cleanup"]["spec"]["lifecycle_strategy"] == "reversible_state_change"
    assert transaction["agent_result"]["cleanup"] == transaction["cleanup"]

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.workUnit.load": [{}],
            }
        ),
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["cleanup"]["status"] == "available_reversal"
    assert execute_payload["cleanup"]["status"] not in {"pending", "required"}

    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["cleanup"]["status"] == "available_reversal"
    assert verify_payload["agent_result"]["cleanup"] == verify_payload["cleanup"]


def test_lifecycle_closer_is_not_reported_as_needing_more_cleanup(tmp_path: Path) -> None:
    state_dir = tmp_path / "unload-bank-state"
    request = generic_public_call_request(
        "ak.soundengine.unloadBank",
        {"soundBank": "Main"},
    )
    transaction = preview_and_confirm_public_call(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert transaction["cleanup"]["status"] == "not_required"
    assert transaction["cleanup"]["spec"]["lifecycle_action"] == "closer"
    assert transaction["cleanup"]["spec"]["companion_request"] is None

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.soundengine.unloadBank": [{}],
            }
        ),
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["cleanup"]["status"] == "not_required"

    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["cleanup"]["status"] == "not_required"
    assert verify_payload["agent_result"]["cleanup"] == verify_payload["cleanup"]


def test_generic_isolated_call_runs_full_chain_with_bound_io_audit(tmp_path: Path) -> None:
    state_dir = tmp_path / "isolated-state"
    io_root = (tmp_path / "io-sandbox").resolve()
    request = generic_isolated_call_request(io_root)
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
    )
    stored = TransactionStore(state_dir).load_preview(transaction["transaction_id"])
    io_audit = stored.artifact["prepared_operation"]["pre_state"]["execution_contract"]["io_audit"]
    assert io_audit["io_root"] == str(io_root)
    assert io_audit["explicit_write_confinement_proven"] is True
    assert io_audit["paths"][0]["resolved_path"] == str((io_root / "tone.wav").resolve())
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.debug.generateToneWAV": [{}],
        }
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )
    assert execute_exit == 0, execute_payload
    assert [call[0] for call in execute_client.calls].count("ak.wwise.debug.generateToneWAV") == 1

    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
        version="2023.1",
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["verified"] is False
    assert verify_payload["result_schema_checked"] is True
    assert verify_payload["verification_strength"] == "complete_reflected_schema"
    assert verify_payload["agent_result"]["result"] == {}
    assert verify_payload["agent_result"]["verified"] is False
    assert verify_payload["agent_result"]["request"] == request


@pytest.mark.parametrize(
    ("version", "operation", "arguments", "expected_roles"),
    (
        (
            "2022.1",
            "audio.import",
            {
                "imports": [
                    {
                        "object_path": (
                            r"\Actor-Mixer Hierarchy\Default Work Unit"
                            r"\RemoteImport"
                        ),
                        "audio_file": "/remote-only/source.wav",
                    }
                ]
            },
            (
                "arguments.imports[].audio_file",
                "live_project_files",
            ),
        ),
        (
            "2022.1",
            "audio.importTabDelimited",
            {
                "import_file": "/remote-only/import.tsv",
                "import_location": {
                    "kind": "path",
                    "value": r"\Actor-Mixer Hierarchy\Default Work Unit",
                },
                "import_language": "SFX",
            },
            (
                "arguments.import_file",
                "tab_file_audio_sources",
                "live_project_files",
            ),
        ),
        (
            "2023.1",
            "object.set",
            {
                "objects": [
                    {
                        "object": {"kind": "id", "value": "{TARGET}"},
                        "import": {
                            "files": [
                                {"audio_file": "/remote-only/source.wav"}
                            ]
                        },
                    }
                ]
            },
            (
                "arguments.objects[].recursive.import",
                "live_project_files",
            ),
        ),
        (
            "2022.1",
            "soundbank.generate",
            {
                "soundbanks": [
                    {
                        "name": "RemoteBank",
                        "artifact_expectation": "nonlocalized",
                    }
                ],
                "platforms": ["Mac"],
                "skip_languages": True,
                "write_to_disk": True,
                "io_root": "/remote-only/output",
            },
            (
                "arguments.io_root",
                "generated_artifacts",
                "live_project_path",
            ),
        ),
        (
            "2022.1",
            "soundbank.convertExternalSources",
            {
                "sources": [
                    {
                        "input": "/remote-only/external.wsources",
                        "platform": "Mac",
                        "output": "/remote-only/wem",
                    }
                ],
                "io_root": "/remote-only",
            },
            (
                "arguments.io_root",
                "arguments.sources[].input",
                "arguments.sources[].output",
            ),
        ),
        (
            "2022.1",
            "soundbank.processDefinitionFiles",
            {
                "files": ["/remote-only/banks.tsv"],
                "io_root": "/remote-only",
            },
            (
                "arguments.files[]",
                "arguments.io_root",
                "live_project_path",
            ),
        ),
        (
            "2022.1",
            "waapi.call",
            {
                "api": "ak.wwise.cli.migrate",
                "args": {"project": "/remote-only/SampleProject.wproj"},
                "options": {},
                "io_root": "/remote-only",
            },
            ("execution_contract.isolated_transaction",),
        ),
        (
            "2024.1",
            "waapi.call",
            {
                "api": "ak.wwise.core.sourceControl.getStatus",
                "args": {"files": ["/remote-only/Project.wwu"]},
                "options": {},
            },
            ("execution_contract.isolated_transaction",),
        ),
        (
            "2024.1",
            "waapi.call",
            {
                "api": "ak.wwise.core.audio.convert",
                "args": {},
                "options": {},
                "io_root": "/remote-only",
            },
            ("execution_contract.isolated_transaction",),
        ),
    ),
)
def test_remote_local_filesystem_previews_fail_before_project_or_path_proof(
    tmp_path: Path,
    version: str,
    operation: str,
    arguments: Mapping[str, Any],
    expected_roles: tuple[str, ...],
) -> None:
    year = int(version.split(".", 1)[0])
    client = FakeClient(
        {"ak.wwise.core.getInfo": [live_info(year=year)]}
    )
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": dict(arguments),
    }

    exit_code, payload = execute(
        [
            "--host",
            "192.0.2.10",
            "preview",
            "--request-json",
            json.dumps(request),
        ],
        tmp_path=tmp_path,
        state_dir=tmp_path / f"remote-{operation.replace('.', '-')}",
        client=client,
        version=version,
    )

    assert exit_code == 2
    assert payload["error_code"] == "LOCAL_WAAPI_HOST_REQUIRED"
    assert payload["details"]["path_roles"] == list(expected_roles)
    assert payload["details"]["boundary_basis"] == (
        "gateway_local_filesystem_or_isolated_transaction"
    )
    assert payload["executed"] is False
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo"
    ]


def test_confirmed_generic_isolated_transaction_stays_confirmed_on_remote_execute(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "remote-isolated-execute"
    io_root = (tmp_path / "isolated-io").resolve()
    request = generic_isolated_call_request(io_root)
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2023)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    before = TransactionStore(state_dir).load(transaction["transaction_id"])
    assert before.state is TransactionState.CONFIRMED
    remote_client = FakeClient(
        {"ak.wwise.core.getInfo": [live_info(year=2023)]}
    )

    exit_code, payload = execute(
        [
            "--host",
            "192.0.2.10",
            "execute",
            transaction["transaction_id"],
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=remote_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["error_code"] == "LOCAL_WAAPI_HOST_REQUIRED"
    assert payload["command"] == "execute"
    assert payload["executed"] is False
    assert TransactionStore(state_dir).load(
        transaction["transaction_id"]
    ).state is TransactionState.CONFIRMED
    assert [call[0] for call in remote_client.calls] == [
        "ak.wwise.core.getInfo"
    ]


def test_confirmed_named_soundbank_transaction_stays_confirmed_on_remote_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "remote-named-soundbank-execute"
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "soundbank.generate",
        "arguments": {
            "soundbanks": [
                {
                    "name": "LocalBank",
                    "artifact_expectation": "nonlocalized",
                }
            ],
            "platforms": ["Mac"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": str((tmp_path / "soundbank-io").resolve()),
        },
    }
    artifact = {
        "contract": "waapi-skill.transaction-preview/v2",
        "request": request,
        "prepared_operation": {
            "contract": "waapi-skill.prepared-operation/v1",
            "operation": "soundbank.generate",
            "version": "2022.1",
            "dispatch": {
                "uri": "ak.wwise.core.soundbank.generate",
                "args": {},
                "options": {},
            },
            "resolved_roles": {},
            "pre_state": {},
            "verification_plan": {},
            "cleanup": {"kind": "discard-case-owned-project-copy"},
        },
        "project_guard": {"fingerprint": "project-fingerprint"},
        "runtime_guard": {"fingerprint": "runtime-fingerprint"},
        "created_at": "2099-01-01T00:00:00Z",
        "expires_at": "2099-01-01T00:05:00Z",
    }

    class StubArtifact:
        def as_dict(self) -> dict[str, Any]:
            return json.loads(json.dumps(artifact))

    monkeypatch.setattr(
        waapi_gateway,
        "build_transaction_artifact",
        lambda *args, **kwargs: StubArtifact(),
    )
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    remote_client = FakeClient(
        {"ak.wwise.core.getInfo": [live_info()]}
    )

    exit_code, payload = execute(
        [
            "--host",
            "192.0.2.10",
            "execute",
            transaction["transaction_id"],
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=remote_client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "LOCAL_WAAPI_HOST_REQUIRED"
    assert payload["details"]["path_roles"] == [
        "arguments.io_root",
        "generated_artifacts",
        "live_project_path",
    ]
    assert payload["executed"] is False
    assert TransactionStore(state_dir).load(
        transaction["transaction_id"]
    ).state is TransactionState.CONFIRMED
    assert [call[0] for call in remote_client.calls] == [
        "ak.wwise.core.getInfo"
    ]


def test_remote_named_capture_screen_is_not_a_locality_transaction(
    tmp_path: Path,
) -> None:
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "ui.captureScreen",
        "arguments": {},
    }
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )

    exit_code, payload = execute(
        [
            "--host",
            "192.0.2.10",
            "preview",
            "--request-json",
            json.dumps(request),
        ],
        tmp_path=tmp_path,
        state_dir=tmp_path / "remote-capture",
        client=client,
    )

    assert exit_code == 0, payload
    assert payload["status"] == "awaiting_confirmation"
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]


@pytest.mark.skipif(
    os.name == "nt",
    reason="Wine host path translation is POSIX-only",
)
def test_local_wine_cli_execute_translates_only_the_transient_dispatch_paths(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "wine-cli-state"
    io_root = (tmp_path / "wine-cli-case").resolve()
    target_project = io_root / "project" / "SampleProject.wproj"
    manifest = io_root / "assets" / "delivery.wsources"
    output = io_root / "output"
    target_project.parent.mkdir(parents=True)
    target_project.write_text("<Project/>", encoding="utf-8")
    manifest.parent.mkdir(parents=True)
    manifest.write_text("<ExternalSourcesList/>", encoding="utf-8")
    output.mkdir(parents=True)
    active_project = local_project(tmp_path)
    wine_project = project(path=z_wire_path(Path(str(active_project["path"]))))
    request = convert_external_source_call_request(io_root)
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [wine_live_info()],
            "ak.wwise.core.getProjectInfo": [wine_project],
        }
    )
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
    )
    stored = TransactionStore(state_dir).load_preview(transaction["transaction_id"])
    prepared = stored.artifact["prepared_operation"]
    host_args = request["arguments"]["args"]

    assert prepared["dispatch"]["args"] == host_args
    assert {
        row["raw_path"]
        for row in prepared["pre_state"]["execution_contract"]["io_audit"]["paths"]
    } == {str(target_project), str(manifest), str(output)}

    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [wine_live_info()],
            "ak.wwise.core.getProjectInfo": [wine_project],
            "ak.wwise.cli.convertExternalSource": [{"result": 0}],
        }
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )

    assert execute_exit == 0, execute_payload
    cli_calls = [
        call for call in execute_client.calls
        if call[0] == "ak.wwise.cli.convertExternalSource"
    ]
    assert cli_calls == [
        (
            "ak.wwise.cli.convertExternalSource",
            {
                "project": z_wire_path(target_project),
                "platform": ["Windows"],
                "source-file": z_wire_path(manifest),
                "output": z_wire_path(output),
            },
            {},
        )
    ]
    proof = execute_payload["wire_path_adaptation"]
    assert proof["mode"] == "local_posix_wine"
    assert proof["applied"] is True
    assert proof["translated_path_count"] == 3
    assert proof["mapping"]["anchor_drive"] == "Z"
    assert proof["project_guard_fingerprint"] == proof["current_project_guard_fingerprint"]
    assert prepared["dispatch"]["args"] == host_args

    events = TransactionStore(state_dir).read_events(transaction["transaction_id"])
    completion = next(event for event in events if event["event_type"] == "execution_completed")
    assert completion["details"]["wire_path_adaptation"] == proof


@pytest.mark.skipif(
    os.name == "nt",
    reason="Wine host path translation is POSIX-only",
)
def test_local_wine_soundbank_execute_translates_sealed_host_paths_transiently(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "wine-soundbank-state"
    io_root = (tmp_path / "wine-soundbank-case").resolve()
    project_root = io_root / "project"
    project_root.mkdir(parents=True)
    (project_root / "SampleProject.wproj").write_text(
        "<Project/>",
        encoding="utf-8",
    )
    (project_root / "external.wav").write_bytes(b"RIFF" + b"\x00" * 64)
    source_list = project_root / "external.wsources"
    source_list.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ExternalSourcesList SchemaVersion="1" Root=".">\n'
        '  <Source Path="external.wav" Destination="external.wav" />\n'
        '</ExternalSourcesList>\n',
        encoding="utf-8",
    )
    for directory in (
        io_root / "cache",
        io_root / "soundbanks" / "Mac" / "Media",
        project_root / "Originals",
        project_root / "Add-ons" / "Commands",
        project_root / "Add-ons" / "Properties",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    request = soundbank_convert_external_sources_request(io_root)
    live_project = soundbank_project_info(io_root, wine_paths=True)
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [wine_live_info()],
            "ak.wwise.core.getProjectInfo": [live_project, live_project],
        }
    )
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=preview_client,
    )
    stored = TransactionStore(state_dir).load_preview(transaction["transaction_id"])
    prepared = stored.artifact["prepared_operation"]
    host_args = prepared["dispatch"]["args"]
    io_audit = prepared["pre_state"]["soundbank_guard"]["io_audit"]
    assert {
        row["json_path"] for row in io_audit["paths"]
    } == {"$.args.sources[0].input", "$.args.sources[0].output"}
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [wine_live_info()],
            "ak.wwise.core.getProjectInfo": [live_project, live_project],
            "ak.wwise.core.soundbank.convertExternalSources": [{}],
        }
    )

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )

    assert execute_exit == 0, execute_payload
    converted_calls = [
        call
        for call in execute_client.calls
        if call[0] == "ak.wwise.core.soundbank.convertExternalSources"
    ]
    assert converted_calls == [
        (
            "ak.wwise.core.soundbank.convertExternalSources",
            {
                "sources": [
                    {
                        "input": z_wire_path(source_list),
                        "platform": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                        "output": z_wire_path(io_root / "external-output"),
                    }
                ]
            },
            {},
        )
    ]
    assert execute_payload["wire_path_adaptation"]["mode"] == "local_posix_wine"
    assert execute_payload["wire_path_adaptation"]["translated_path_count"] == 2
    assert prepared["dispatch"]["args"] == host_args


def test_soundbank_wire_path_selection_fails_closed_without_exact_sealed_audit() -> None:
    uri = "ak.wwise.core.soundbank.convertExternalSources"
    with pytest.raises(waapi_gateway.WwiseWirePathError) as missing:
        waapi_gateway.prepared_wire_path_io_audit(
            operation="soundbank.convertExternalSources",
            call_uri=uri,
            prepared={"pre_state": {"soundbank_guard": {}}},
        )
    assert missing.value.error_code == "WIRE_PATH_AUDIT_MISSING"

    with pytest.raises(waapi_gateway.WwiseWirePathError) as mismatched:
        waapi_gateway.prepared_wire_path_io_audit(
            operation="soundbank.processDefinitionFiles",
            call_uri=uri,
            prepared={
                "pre_state": {
                    "soundbank_guard": {
                        "io_audit": {"uri": uri, "paths": []},
                    }
                }
            },
        )
    assert mismatched.value.error_code == "WIRE_PATH_OPERATION_MISMATCH"


def _prepared_tab_import_wire_path_fixture(import_file: Path) -> dict[str, Any]:
    uri = "ak.wwise.core.audio.importTabDelimited"
    canonical_import_file = str(import_file.resolve())
    audit = {
        "contract": waapi_gateway.WWISE_WIRE_PATH_INPUT_AUDIT_CONTRACT,
        "uri": uri,
        "scope": "transient_dispatch_read_paths_only",
        "paths": [
            {
                "section": "args",
                "json_path": "$.args.importFile",
                "field": "importFile",
                "role": "read",
                "raw_path": canonical_import_file,
                "resolved_path": canonical_import_file,
            }
        ],
    }
    return {
        "dispatch": {
            "uri": uri,
            "args": {"importFile": canonical_import_file},
            "options": {},
        },
        "pre_state": {
            "import_guard": {
                "source_operation": "audio.importTabDelimited",
                "file_proofs": [
                    {
                        "field": "import_file",
                        "proof": {"path": canonical_import_file},
                    },
                    {
                        "field": "source_file_proofs[1]",
                        "proof": {"path": str(import_file.with_suffix(".wav").resolve())},
                    },
                ],
                "wire_path_input_audit": audit,
            }
        },
    }


def test_tab_import_wire_path_selection_accepts_one_import_file_among_source_proofs(
    tmp_path: Path,
) -> None:
    import_file = tmp_path / "compound.tsv"
    prepared = _prepared_tab_import_wire_path_fixture(import_file)

    audit = waapi_gateway.prepared_wire_path_io_audit(
        operation="audio.importTabDelimited",
        call_uri="ak.wwise.core.audio.importTabDelimited",
        prepared=prepared,
    )

    assert audit == prepared["pre_state"]["import_guard"]["wire_path_input_audit"]
    assert audit["paths"][0]["json_path"] == "$.args.importFile"


def test_tab_import_wire_path_selection_rejects_missing_or_duplicate_import_file_proof(
    tmp_path: Path,
) -> None:
    import_file = tmp_path / "compound.tsv"
    missing = _prepared_tab_import_wire_path_fixture(import_file)
    del missing["pre_state"]["import_guard"]["wire_path_input_audit"]
    with pytest.raises(waapi_gateway.WwiseWirePathError) as missing_error:
        waapi_gateway.prepared_wire_path_io_audit(
            operation="audio.importTabDelimited",
            call_uri="ak.wwise.core.audio.importTabDelimited",
            prepared=missing,
        )
    assert missing_error.value.error_code == "WIRE_PATH_AUDIT_MISSING"

    duplicate = _prepared_tab_import_wire_path_fixture(import_file)
    duplicate["pre_state"]["import_guard"]["file_proofs"].append(
        {
            "field": "import_file",
            "proof": {"path": str(import_file.resolve())},
        }
    )
    with pytest.raises(waapi_gateway.WwiseWirePathError) as duplicate_error:
        waapi_gateway.prepared_wire_path_io_audit(
            operation="audio.importTabDelimited",
            call_uri="ak.wwise.core.audio.importTabDelimited",
            prepared=duplicate,
        )
    assert duplicate_error.value.error_code == "WIRE_PATH_AUDIT_MISMATCH"


@pytest.mark.parametrize(
    ("tamper_target", "tamper_value"),
    [
        ("contract", "waapi-skill.wwise-wire-path-input-audit/v0"),
        ("scope", "all_dispatch_paths"),
        ("raw_path", "/different/compound.tsv"),
        ("resolved_path", "/different/compound.tsv"),
        ("dispatch_uri", "ak.wwise.core.audio.import"),
    ],
)
def test_tab_import_wire_path_selection_rejects_audit_or_dispatch_drift(
    tamper_target: str,
    tamper_value: str,
    tmp_path: Path,
) -> None:
    prepared = _prepared_tab_import_wire_path_fixture(tmp_path / "compound.tsv")
    if tamper_target in {"contract", "scope"}:
        prepared["pre_state"]["import_guard"]["wire_path_input_audit"][
            tamper_target
        ] = tamper_value
    elif tamper_target == "dispatch_uri":
        prepared["dispatch"]["uri"] = tamper_value
    else:
        prepared["pre_state"]["import_guard"]["wire_path_input_audit"]["paths"][
            0
        ][tamper_target] = tamper_value

    with pytest.raises(waapi_gateway.WwiseWirePathError) as error:
        waapi_gateway.prepared_wire_path_io_audit(
            operation="audio.importTabDelimited",
            call_uri="ak.wwise.core.audio.importTabDelimited",
            prepared=prepared,
        )

    assert error.value.error_code == "WIRE_PATH_AUDIT_MISMATCH"


@pytest.mark.skipif(
    os.name == "nt",
    reason="Wine host path translation is POSIX-only",
)
def test_local_wine_unmappable_project_path_blocks_preview_before_state_write(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "wine-cli-failure-state"
    io_root = (tmp_path / "wine-cli-failure-case").resolve()
    (io_root / "project").mkdir(parents=True)
    (io_root / "project" / "SampleProject.wproj").write_text(
        "<Project/>",
        encoding="utf-8",
    )
    (io_root / "assets").mkdir(parents=True)
    (io_root / "assets" / "delivery.wsources").write_text(
        "<ExternalSourcesList/>",
        encoding="utf-8",
    )
    (io_root / "output").mkdir(parents=True)
    unsupported_project = project(path=r"C:\Projects\SampleProject.wproj")
    request = convert_external_source_call_request(io_root)
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [wine_live_info()],
            "ak.wwise.core.getProjectInfo": [unsupported_project],
        }
    )

    exit_code, payload = execute(
        ["preview", "--request-json", json.dumps(request)],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "cannot be localized safely" in payload["message"]
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    assert not state_dir.exists()


def test_generate_soundbank_verify_uses_sealed_result_context_and_runtime_without_project_probe(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "generate-soundbank-state"
    transaction, request, preview_client, execute_client = (
        execute_generate_soundbank_successfully(
            tmp_path=tmp_path,
            state_dir=state_dir,
        )
    )
    artifact = TransactionStore(state_dir).load_preview(
        transaction["transaction_id"]
    ).artifact
    sealed_contract = artifact["prepared_operation"]["pre_state"]["execution_contract"]

    assert sealed_contract["post_execution_project_guard_policy"] == "context_runtime_only"
    assert sealed_contract["project_guard_mode"] == "invariant"
    assert artifact["prepared_operation"]["verification_plan"] == {
        "kind": "result-schema",
        "uri": "ak.wwise.cli.generateSoundbank",
        "version": "2022.1",
        "strategy": "result_schema",
    }
    assert artifact["execution_policy"]["revalidate_project_guard"] is True
    assert [call[0] for call in preview_client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    assert [call[0] for call in execute_client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.cli.generateSoundbank",
    ]

    verify_client = FakeClient({"ak.wwise.core.getInfo": [live_info()]})
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert verify_exit == 0, verify_payload
    assert [call[0] for call in verify_client.calls] == ["ak.wwise.core.getInfo"]
    assert verify_payload["project_call"] is None
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["result_schema_checked"] is True
    assert verify_payload["verified"] is False
    assert verify_payload["verification"]["business_state_verified"] is False
    assert verify_payload["agent_result"]["verified"] is False
    assert verify_payload["agent_result"]["request"] == request
    assert verify_payload["guard_validation"]["project_probe_performed"] is False
    assert verify_payload["guard_validation"]["project_identity_revalidated"] is False
    assert verify_payload["guard_validation"]["context_guard_validated"] is True
    assert verify_payload["guard_validation"]["runtime_guard_validated"] is True


def test_tab_delimited_import_verify_uses_sealed_result_context_and_runtime_without_project_probe(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "tab-import-state"
    transaction, request, preview_client, execute_client = (
        execute_tab_delimited_import_successfully(
            tmp_path=tmp_path,
            state_dir=state_dir,
        )
    )
    artifact = TransactionStore(state_dir).load_preview(
        transaction["transaction_id"]
    ).artifact
    sealed_contract = artifact["prepared_operation"]["pre_state"]["execution_contract"]

    assert sealed_contract["post_execution_project_guard_policy"] == "context_runtime_only"
    assert sealed_contract["project_guard_mode"] == "invariant"
    assert artifact["prepared_operation"]["verification_plan"] == {
        "kind": "result-schema",
        "uri": "ak.wwise.cli.tabDelimitedImport",
        "version": "2022.1",
        "strategy": "result_schema",
    }
    assert [call[0] for call in preview_client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    assert [call[0] for call in execute_client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.cli.tabDelimitedImport",
    ]

    verify_client = FakeClient({"ak.wwise.core.getInfo": [live_info()]})
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert verify_exit == 0, verify_payload
    assert [call[0] for call in verify_client.calls] == ["ak.wwise.core.getInfo"]
    assert verify_payload["project_call"] is None
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["result_schema_checked"] is True
    assert verify_payload["verified"] is False
    assert verify_payload["verification"]["business_state_verified"] is False
    assert verify_payload["agent_result"]["result"] == {"result": 2}
    assert verify_payload["agent_result"]["verified"] is False
    assert verify_payload["agent_result"]["request"] == request
    assert verify_payload["guard_validation"]["project_probe_performed"] is False
    assert verify_payload["guard_validation"]["project_identity_revalidated"] is False
    assert verify_payload["guard_validation"]["context_guard_validated"] is True
    assert verify_payload["guard_validation"]["runtime_guard_validated"] is True


@pytest.mark.parametrize(
    ("api", "execute_successfully", "expected_result"),
    (
        (
            "ak.wwise.cli.convertExternalSource",
            execute_convert_external_source_successfully,
            {"result": 2},
        ),
        (
            "ak.wwise.cli.migrate",
            execute_migrate_successfully,
            {"result": 0},
        ),
    ),
)
def test_additional_reviewed_explicit_project_cli_calls_verify_without_project_probe(
    tmp_path: Path,
    api: str,
    execute_successfully: Any,
    expected_result: Mapping[str, Any],
) -> None:
    state_dir = tmp_path / f"{api.rsplit('.', 1)[-1]}-state"
    transaction, request, preview_client, execute_client = execute_successfully(
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    artifact = TransactionStore(state_dir).load_preview(
        transaction["transaction_id"]
    ).artifact
    sealed_contract = artifact["prepared_operation"]["pre_state"]["execution_contract"]

    assert sealed_contract["post_execution_project_guard_policy"] == "context_runtime_only"
    assert sealed_contract["route"] == "isolated_transaction"
    assert sealed_contract["project_guard_mode"] == "invariant"
    assert sealed_contract["verification_strategy"] == "result_schema"
    assert artifact["prepared_operation"]["verification_plan"] == {
        "kind": "result-schema",
        "uri": api,
        "version": "2022.1",
        "strategy": "result_schema",
    }
    assert [call[0] for call in preview_client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    assert [call[0] for call in execute_client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        api,
    ]

    # Conversion uses this verification path directly. Migration remains
    # terminal after execute in the agent-facing protocol, but its lower-level
    # durable contract must likewise never probe an Authoring project that the
    # CLI process may already have unloaded.
    verify_client = FakeClient({"ak.wwise.core.getInfo": [live_info()]})
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert verify_exit == 0, verify_payload
    assert [call[0] for call in verify_client.calls] == ["ak.wwise.core.getInfo"]
    assert verify_payload["project_call"] is None
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["result_schema_checked"] is True
    assert verify_payload["verified"] is False
    assert verify_payload["verification"]["business_state_verified"] is False
    assert verify_payload["agent_result"]["result"] == expected_result
    assert verify_payload["agent_result"]["verified"] is False
    assert verify_payload["agent_result"]["request"] == request
    assert verify_payload["guard_validation"]["project_probe_performed"] is False
    assert verify_payload["guard_validation"]["project_identity_revalidated"] is False
    assert verify_payload["guard_validation"]["context_guard_validated"] is True
    assert verify_payload["guard_validation"]["runtime_guard_validated"] is True


def test_generate_soundbank_preview_requires_strong_get_info_process_identity(
    tmp_path: Path,
) -> None:
    weak_info = live_info()
    del weak_info["processPath"]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [weak_info],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    request = generate_soundbank_call_request((tmp_path / "soundbank-io").resolve())

    exit_code, payload = execute(
        ["preview", "--request-json", json.dumps(request)],
        tmp_path=tmp_path,
        state_dir=tmp_path / "state",
        client=client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "RUNTIME_CONTEXT_IDENTITY_MISSING"
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]


def test_generate_soundbank_verify_rejects_same_version_process_identity_drift_without_project_probe(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "generate-soundbank-state"
    transaction, _, _, _ = execute_generate_soundbank_successfully(
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    changed_info = live_info()
    changed_info["sessionId"] = "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"
    changed_info["processId"] = 5252
    verify_client = FakeClient({"ak.wwise.core.getInfo": [changed_info]})

    verify_exit, payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert verify_exit == 2
    assert payload["status"] == "verification_deferred"
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert payload["error_code"] == "PROJECT_GUARD_MISMATCH"
    assert payload["project_call"] is None
    assert [call[0] for call in verify_client.calls] == ["ak.wwise.core.getInfo"]


def test_generate_soundbank_verify_rejects_endpoint_drift_without_project_probe(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "generate-soundbank-state"
    transaction, _, _, _ = execute_generate_soundbank_successfully(
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    verify_client = FakeClient({"ak.wwise.core.getInfo": [live_info()]})

    verify_exit, payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
        port=31338,
    )

    assert verify_exit == 2
    assert payload["status"] == "verification_deferred"
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert payload["error_code"] == "PROJECT_GUARD_MISMATCH"
    assert payload["project_call"] is None
    assert [call[0] for call in verify_client.calls] == ["ak.wwise.core.getInfo"]


def test_generate_soundbank_verify_rejects_runtime_drift_without_project_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "generate-soundbank-state"
    transaction, _, _, _ = execute_generate_soundbank_successfully(
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    artifact = TransactionStore(state_dir).load_preview(
        transaction["transaction_id"]
    ).artifact
    copied_skill = tmp_path / "copied-skill"
    source_skill = Path(waapi_gateway.SKILL_ROOT)
    for relative in artifact["runtime_guard"]["files"]:
        source = source_skill / relative
        target = copied_skill / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    changed_runtime = copied_skill / "wwise_waapi" / "canonical.py"
    changed_runtime.write_text(
        changed_runtime.read_text(encoding="utf-8") + "\n# runtime drift\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(waapi_gateway, "SKILL_ROOT", copied_skill)
    verify_client = FakeClient({"ak.wwise.core.getInfo": [live_info()]})

    verify_exit, payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert verify_exit == 2
    assert payload["status"] == "verification_deferred"
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert payload["error_code"] == "RUNTIME_GUARD_MISMATCH"
    assert payload["project_call"] is None
    assert [call[0] for call in verify_client.calls] == ["ak.wwise.core.getInfo"]


@pytest.mark.parametrize(
    ("version", "api", "guard_mode"),
    PROJECT_TRANSITION_ROWS,
    ids=lambda value: str(value),
)
def test_every_project_transition_row_runs_one_complete_program_chain(
    tmp_path: Path,
    version: str,
    api: str,
    guard_mode: str,
) -> None:
    year = int(version.split(".", 1)[0])
    state_dir = tmp_path / "state"
    io_root = (tmp_path / "io-root").resolve()
    target_path = io_root / "TargetProject.wproj"
    current_path = (tmp_path / "current-project" / "CurrentProject.wproj").resolve()
    contract = ExecutionContractRegistry().describe(version, api)
    call_args: dict[str, Any] = {}
    arguments: dict[str, Any] = {"api": api, "args": call_args, "options": {}}
    if guard_mode == PROJECT_GUARD_TRANSITION_TO_PATH:
        call_args["path"] = str(target_path)
    if contract.route == "isolated_transaction":
        arguments["io_root"] = str(io_root)
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.call",
        "arguments": arguments,
    }
    before_rows = (
        []
        if guard_mode == PROJECT_GUARD_TRANSITION_TO_PATH
        else [
            {
                **project(path=str(current_path)),
                "type": "Project",
            }
        ]
    )
    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=year)],
            "ak.wwise.core.object.get": [{"return": before_rows}],
        }
    )
    transaction = preview(request, tmp_path=tmp_path, state_dir=state_dir, client=preview_client)
    stored_guard = TransactionStore(state_dir).load_preview(transaction["transaction_id"]).artifact[
        "project_guard"
    ]
    assert stored_guard["project_guard_mode"] == guard_mode
    assert stored_guard["project"]["state"] == ("none" if not before_rows else "open")
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    result = {"hadProjectOpen": True} if api.endswith(".close") else {}
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=year)],
            "ak.wwise.core.object.get": [{"return": before_rows}],
            api: [result],
        }
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version=version,
    )
    assert execute_exit == 0, execute_payload
    assert execute_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert [call[0] for call in execute_client.calls].count(api) == 1

    after_rows = (
        [
            {
                **project(name="TargetProject", path=str(target_path)),
                "type": "Project",
            }
        ]
        if guard_mode == PROJECT_GUARD_TRANSITION_TO_PATH
        else []
    )
    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=year)],
            "ak.wwise.core.object.get": [{"return": after_rows}],
        }
    )
    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
        version=version,
    )
    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.VERIFIED.value
    assert verify_payload["verified"] is True
    assert verify_payload["result_schema_checked"] is False
    assert verify_payload["verification"]["business_state_verified"] is True
    assert verify_payload["verification"]["readbacks"][-1]["kind"] == "project-transition-observation"
    assert verify_payload["guard_validation"]["project_transition"]["matched"] is True
    assert verify_payload["agent_result"]["verified"] is True


def test_project_transition_mismatch_stays_executed_unverified_for_manual_verify(
    tmp_path: Path,
) -> None:
    version = "2022.1"
    api = "ak.wwise.ui.project.open"
    state_dir = tmp_path / "state"
    io_root = (tmp_path / "io-root").resolve()
    target_path = io_root / "TargetProject.wproj"
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": api,
            "args": {"path": str(target_path)},
            "options": {},
            "io_root": str(io_root),
        },
    }
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.object.get": [{"return": []}],
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_exit, _ = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.object.get": [{"return": []}],
                api: [{}],
            }
        ),
        version=version,
    )
    assert execute_exit == 0

    wrong_path = (io_root / "OtherProject.wproj").resolve()
    verify_exit, payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.object.get": [
                    {
                        "return": [
                            {
                                **project(name="OtherProject", path=str(wrong_path)),
                                "type": "Project",
                            }
                        ]
                    }
                ],
            }
        ),
        version=version,
    )
    assert verify_exit == 2
    assert payload["status"] == "verification_deferred"
    assert payload["error_code"] == "PROJECT_TRANSITION_MISMATCH"
    assert payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert "agent_result" not in payload


def test_undo_group_success_uses_one_client_and_verifies_only_result_schemas(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [{}],
            "ak.wwise.core.undo.endGroup": [{}],
        }
    )

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert execute_exit == 0, execute_payload
    assert execute_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert execute_payload["same_connection"] is True
    assert execute_payload["compound_execution"] == {
        "status": "completed",
        "same_connection": True,
        "automatic_retry": False,
        "phase_count": 3,
        "authoritative_phases": "dispatch_result.result.phases",
    }
    assert json.dumps(execute_payload, ensure_ascii=False).count('"phases"') == 1
    compound_calls = [
        call
        for call in execute_client.calls
        if call[0].startswith("ak.wwise.core.undo.")
        or call[0] == "ak.wwise.core.object.setNotes"
    ]
    assert compound_calls == [
        ("ak.wwise.core.undo.beginGroup", {}, {}),
        (
            "ak.wwise.core.object.setNotes",
            {"object": OBJECT_GUID, "value": "after"},
            {},
        ),
        ("ak.wwise.core.undo.endGroup", {"displayName": "Program Undo Group"}, {}),
    ]
    assert len({execute_client.call_thread_idents[execute_client.calls.index(call)] for call in compound_calls}) == 1

    verify_exit, verify_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2023)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
        version="2023.1",
    )

    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verify_payload["verified"] is False
    assert verify_payload["result_schema_checked"] is True
    assert verify_payload["verification"]["business_state_verified"] is False
    assert verify_payload["agent_result"]["verified"] is False


def test_undo_group_success_keeps_one_phase_copy_below_the_final_gateway_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)

    class AcceptedResultValidation:
        unresolved_refs: tuple[str, ...] = ()

        def as_dict(self) -> dict[str, Any]:
            return {"section": "result", "unresolved_refs": []}

    monkeypatch.setattr(
        waapi_gateway,
        "validate_semantic_result",
        lambda *args, **kwargs: AcceptedResultValidation(),
    )
    # This ceiling is deliberately below the old three-copy response size but
    # comfortably above the new single authoritative phase document.
    monkeypatch.setattr(waapi_gateway, "MAX_GATEWAY_RESULT_JSON_BYTES", 250 * 1024)
    large_inner_result = {"program_payload": "x" * 100_000}
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [large_inner_result],
            "ak.wwise.core.undo.endGroup": [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 0, payload
    assert payload["status"] == "executed_unverified"
    assert payload.get("error_code") != "RESULT_TOO_LARGE"
    assert payload["dispatch_result"]["result"]["phases"][1]["dispatch_result"]["result"] == (
        large_inner_result
    )
    assert "phases" not in payload["compound_execution"]
    assert "dispatch_result" not in payload["compound_execution"]
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    assert len(encoded) < waapi_gateway.MAX_GATEWAY_RESULT_JSON_BYTES
    assert encoded.count(b'"phases"') == 1


def test_undo_group_success_with_journal_failure_is_not_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "undo-post-success-journal-failure-state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)

    def fail_after_same_connection_success(
        _store: TransactionStore,
        _transaction_id: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> Any:
        assert details is not None
        assert details["dispatch_result"]["result"]["same_connection"] is True
        raise OSError("disk full after same-connection success")

    monkeypatch.setattr(
        waapi_gateway.TransactionStore,
        "mark_executed_unverified",
        fail_after_same_connection_success,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [{}],
            "ak.wwise.core.undo.endGroup": [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["status"] == "execution_succeeded_persistence_failed"
    assert payload["error_code"] == "TRANSACTION_PERSISTENCE_FAILED"
    assert payload["state"] == TransactionState.EXECUTING.value
    assert payload["executed"] is True
    assert payload["automatic_retry"] is False
    assert payload["same_connection"] is True
    assert payload["compound_execution"]["authoritative_phases"] == (
        "dispatch_result.result.phases"
    )
    assert json.dumps(payload, ensure_ascii=False).count('"phases"') == 1
    assert [call[0] for call in execute_client.calls][-3:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.endGroup",
    ]


def test_undo_group_inner_timeout_reserves_budget_cancels_and_never_retries(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.undo.cancelGroup": [{}],
        },
        errors={"ak.wwise.core.object.setNotes": [TimeoutError("program timeout")]},
    )

    execute_exit, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert execute_exit == 2
    assert payload["state"] == TransactionState.EXECUTION_CANCELLED.value
    assert payload["rollback_verified"] is False
    assert payload["automatic_retry"] is False
    assert [call[0] for call in execute_client.calls][-3:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.cancelGroup",
    ]
    assert execute_client.calls[-1][1] == {"undo": True}
    inner_phase = payload["compound_execution"]["failed_phase"]
    assert inner_phase["dispatch_result"]["error_code"] == "TIMEOUT"
    assert inner_phase["cancel_reserve_seconds"] >= 2.0

    retry_client = FakeClient({"ak.wwise.core.getInfo": [live_info(year=2023)]})
    retry_exit, retry_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=retry_client,
        version="2023.1",
    )
    assert retry_exit == 2
    assert retry_payload["error_code"] == "InvalidTransition"
    assert [call[0] for call in retry_client.calls] == ["ak.wwise.core.getInfo"]


def test_undo_group_cancel_failure_is_terminal_indeterminate(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
        },
        errors={
            "ak.wwise.core.object.setNotes": [RuntimeError("inner failed")],
            "ak.wwise.core.undo.cancelGroup": [RuntimeError("cancel failed")],
        },
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.INDETERMINATE.value
    assert payload["automatic_retry"] is False
    assert [call[0] for call in execute_client.calls][-3:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.cancelGroup",
    ]
    assert "ak.wwise.core.undo.endGroup" not in [call[0] for call in execute_client.calls]


def test_undo_group_malformed_begin_result_best_effort_cancels_but_stays_indeterminate(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{"unexpected": True}],
            "ak.wwise.core.undo.cancelGroup": [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.INDETERMINATE.value
    assert payload["compound_execution"]["cancel_succeeded"] is True
    assert [call[0] for call in execute_client.calls][-2:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.undo.cancelGroup",
    ]
    assert "ak.wwise.core.object.setNotes" not in [call[0] for call in execute_client.calls]


def test_undo_group_malformed_end_result_best_effort_cancels_but_stays_indeterminate(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [{}],
            "ak.wwise.core.undo.endGroup": [{"unexpected": True}],
            "ak.wwise.core.undo.cancelGroup": [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.INDETERMINATE.value
    assert payload["compound_execution"]["cancel_succeeded"] is True
    assert [call[0] for call in execute_client.calls][-4:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.endGroup",
        "ak.wwise.core.undo.cancelGroup",
    ]


@pytest.mark.parametrize(
    "failing_uri",
    [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.endGroup",
    ],
)
def test_undo_group_phase_exception_best_effort_cancels_and_remains_indeterminate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_uri: str,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [{}],
            "ak.wwise.core.undo.endGroup": [{}],
            "ak.wwise.core.undo.cancelGroup": [{}],
        }
    )
    original_dispatch = waapi_gateway.dispatch
    raised = False

    def dispatch_then_raise(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal raised
        result = original_dispatch(*args, **kwargs)
        api = args[1] if len(args) > 1 else kwargs.get("api")
        if api == failing_uri and not raised:
            raised = True
            raise RuntimeError("program post-dispatch exception")
        return result

    monkeypatch.setattr(waapi_gateway, "dispatch", dispatch_then_raise)
    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.INDETERMINATE.value
    assert payload["automatic_retry"] is False
    assert payload["compound_execution"]["cancel_succeeded"] is True
    assert [call[0] for call in execute_client.calls][-1] == "ak.wwise.core.undo.cancelGroup"


def test_undo_group_accumulated_result_limit_stops_inner_and_attempts_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    monkeypatch.setattr(waapi_gateway, "UNDO_GROUP_MAX_ACCUMULATED_RESULT_BYTES", 8 * 1024)

    class AcceptedResultValidation:
        unresolved_refs: tuple[str, ...] = ()

        def as_dict(self) -> dict[str, Any]:
            return {"section": "result", "unresolved_refs": []}

    monkeypatch.setattr(
        waapi_gateway,
        "validate_semantic_result",
        lambda *args, **kwargs: AcceptedResultValidation(),
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.undo.beginGroup": [{}],
            "ak.wwise.core.object.setNotes": [{"program_payload": "x" * 32_000}],
            "ak.wwise.core.undo.cancelGroup": [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2023.1",
    )

    assert exit_code == 2
    assert payload["state"] == TransactionState.EXECUTION_CANCELLED.value
    assert payload["status"] == "execution_cancelled"
    assert payload.get("error_code") != "RESULT_TOO_LARGE"
    assert payload["compound_execution"]["failed_phase"]["failure"]["kind"] == (
        "compound_result_limit_exceeded"
    )
    assert payload["compound_execution"]["cancel_phase"]["dispatch_result"]["ok"] is True
    assert [call[0] for call in execute_client.calls][-3:] == [
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.undo.cancelGroup",
    ]
    assert "ak.wwise.core.undo.endGroup" not in [call[0] for call in execute_client.calls]
