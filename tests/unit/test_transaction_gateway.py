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
from tests.support.canonical_preview import bind_canonical_preview_fixture
from tests.support.compound_undo import compound_undo_request

from wwise_waapi.builders.schema import validate_semantic_payload  # pyright: ignore[reportMissingImports]
from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.execution_contracts import (  # pyright: ignore[reportMissingImports]
    PROJECT_GUARD_TRANSITION_TO_NONE,
    PROJECT_GUARD_TRANSITION_TO_PATH,
    ExecutionContractRegistry,
)
from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    INTERNAL_CANONICAL_INPUT_MODE,
    OPERATION_REQUEST_CONTRACT,
    OPERATION_SPECS,
    UNDO_GROUP_INNER_URIS_BY_VERSION,
    operation_input_mode,
    parse_operation_request,
)
from wwise_waapi.platform_commands import (  # pyright: ignore[reportMissingImports]
    PlatformCommandError,
    WINDOWS_MODEL_COMMAND_FAMILY,
    WINDOWS_POWERSHELL_ENCODED_FAMILY,
    decode_windows_model_argv,
    decode_windows_powershell_argv,
    encode_windows_model_argv,
    encode_windows_powershell_argv,
)
from wwise_waapi.typed_requests import (  # pyright: ignore[reportMissingImports]
    expand_gateway_field_table,
    request_contract,
)
from wwise_waapi.transactions import TransactionState, TransactionStore
from wwise_waapi.runtime_transport_handles import (
    RuntimeTransportContext,
    RuntimeTransportHandleError,
    RuntimeTransportHandleStore,
)


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_transaction_gateway_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)
waapi_gateway.execute_gateway = bind_canonical_preview_fixture(waapi_gateway)


PARENT_GUID = "{22222222-2222-2222-2222-222222222222}"
OBJECT_GUID = "{33333333-3333-3333-3333-333333333333}"
SOUND_BANK_GUID = "{55555555-5555-5555-5555-555555555555}"


def _composer_fields(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    composer = payload["composer"]
    fields = composer.get("typed_request_fields")
    if isinstance(fields, list):
        return fields
    return expand_gateway_field_table(composer["typed_request_field_table"])
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
    state_dir: Path | None = None,
    requires_explicit_user_confirmation: bool = False,
    requires_later_user_message: bool = False,
) -> dict[str, Any]:
    normalized = [str(value) for value in gateway_argv]
    full_argv = [
        "python",
        str(SCRIPT_PATH.with_name("run.py")),
        "gateway.py",
    ]
    if state_dir is not None:
        full_argv.extend(["--state-dir", str(state_dir.resolve())])
    full_argv.extend(normalized)
    expected: dict[str, Any] = {
        "contract": "waapi-skill.gateway-next-command/v2",
        "command": command,
        "gateway_argv": normalized,
        "full_argv": full_argv,
        "copy_exactly": True,
        "shell_tool_timeout_ms": 30_000,
    }
    if requires_explicit_user_confirmation:
        expected["requires_explicit_user_confirmation"] = True
    if requires_later_user_message:
        expected["requires_later_user_message"] = True
    if os.name == "nt":
        expected["shell_family"] = WINDOWS_POWERSHELL_ENCODED_FAMILY
        shell_command = encode_windows_powershell_argv(full_argv)
        try:
            model_command = encode_windows_model_argv(full_argv)
        except PlatformCommandError:
            model_command = None
    else:
        expected["shell_family"] = "posix-sh"
        shell_command = shlex.join(full_argv)
        model_command = None
    if model_command is not None:
        expected["shell_command"] = shell_command
        expected["model_shell_family"] = WINDOWS_MODEL_COMMAND_FAMILY
    expected["copy_instruction"] = {
        "contract": "waapi-skill.gateway-command-copy-instruction/v2",
        "source_field": (
            "model_command" if model_command is not None else "shell_command"
        ),
        "action": "execute_verbatim_as_one_shell_tool_call",
        "forbidden_transformations": [
            "reconstruct",
            "shorten",
            "normalize",
            "substitute_path_segments",
            "select_another_field",
        ],
    }
    if model_command is not None:
        expected["model_command"] = model_command
    else:
        expected["shell_command"] = shell_command
    return expected


def test_transaction_next_command_preserves_explicit_state_dir_in_copy_envelope(
    tmp_path: Path,
) -> None:
    state_dir = (tmp_path / "isolated state").resolve()

    continuation = waapi_gateway.transaction_next_command(
        "confirm",
        ["confirm", "tx1-example", "--confirmation-token", "ct1-example"],
        state_dir=state_dir,
        requires_explicit_user_confirmation=True,
    )

    assert continuation["gateway_argv"] == [
        "confirm",
        "tx1-example",
        "--confirmation-token",
        "ct1-example",
    ]
    assert continuation["full_argv"][:5] == [
        "python",
        str(SCRIPT_PATH.with_name("run.py")),
        "gateway.py",
        "--state-dir",
        str(state_dir),
    ]
    source_field = continuation["copy_instruction"]["source_field"]
    if source_field == "model_command":
        assert decode_windows_model_argv(continuation[source_field]) == tuple(
            continuation["full_argv"]
        )
    elif os.name == "nt":
        assert decode_windows_powershell_argv(continuation[source_field]) == tuple(
            continuation["full_argv"]
        )
    else:
        assert shlex.split(continuation[source_field]) == continuation["full_argv"]


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
    for entry in ExecutionContractRegistry().authoring_ui_entries(version)
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


def live_info(
    *,
    year: int = 2022,
    major: int = 1,
    is_command_line: bool = True,
) -> dict[str, Any]:
    return {
        "displayName": "Wwise",
        "isCommandLine": is_command_line,
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


def sound_bank_row() -> dict[str, Any]:
    return {
        "id": SOUND_BANK_GUID,
        "name": "Main",
        "type": "SoundBank",
        "path": r"\SoundBanks\Default Work Unit\Main",
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
    child_request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "object.setNotes",
        "arguments": {
            "object": {"kind": "id", "value": OBJECT_GUID},
            "value": "after",
        },
    }
    return compound_undo_request(
        version=version,
        child_requests=[child_request],
    )


def preview_and_confirm_undo_group(*, tmp_path: Path, state_dir: Path) -> dict[str, Any]:
    transaction = preview(
        undo_group_request(),
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2023)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.object.get": [{"return": [object_row()]}],
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
    # These registry-preparation fixtures author full canonical requests.  The
    # Composer normal surfaces reject canonical JSON; these reviewed Registry
    # fixtures therefore exercise the explicit compatibility adapter.
    operation = str(request.get("operation"))
    version = str(request.get("version", "2022.1"))
    # These Registry-preparation fixtures intentionally submit a complete
    # canonical request.  Once an operation has a typed normal entry, the only
    # test-only compatibility seam for that representation is legacy-preview.
    command = (
        "preview"
        if operation_input_mode(operation, version) == INTERNAL_CANONICAL_INPUT_MODE
        else "legacy-preview"
    )
    arguments = [command]
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
        version=version,
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
            state_dir=state_dir,
        )
    else:
        assert payload["next_command"] == expected_transaction_next_command(
            "transaction-show",
            ["transaction-show", payload["transaction_id"], "--summary-only"],
            state_dir=state_dir,
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
        state_dir=state_dir,
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
        "arguments": {},
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
    assert payload["terminal_journal"] == {
        "classification": "dispatch_accepted_effect_unverified",
        "effect_verified": False,
        "durable_state": TransactionState.INDETERMINATE.value,
        "retry_allowed": False,
    }
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
        "arguments": {},
    }

    exit_code, payload = execute(
        [
            "legacy-preview",
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

    assert exit_code == 0, json.dumps(payload, indent=2)
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
        state_dir=state_dir,
        requires_later_user_message=True,
    )
    assert [
        event["event_type"]
        for event in TransactionStore(state_dir).read_events(
            payload["transaction_id"]
        )
    ] == ["preview_created", "confirmation_requested"]


@pytest.mark.parametrize(
    "version,api,operation",
    (
        ("2023.1", "ak.wwise.debug.restartWaapiServers", "debug.restartWaapiServers"),
        ("2021.1", "ak.wwise.debug.testAssert", "debug.testAssert"),
        ("2021.1", "ak.wwise.debug.testCrash", "debug.testCrash"),
    ),
)
def test_zero_input_debug_native_route_is_rejected_in_favor_of_named_operation(
    tmp_path: Path,
    version: str,
    api: str,
    operation: str,
) -> None:
    state_dir = tmp_path / "state"
    schema_exit, schema = execute(
        ["request-schema", api],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version=version,
    )
    assert schema_exit == 2
    assert f"operation-schema {operation}" in schema["message"]

    reflected = request_contract(version, api)

    exit_code, payload = execute(
        [
            "typed-zero-call", api,
            "--schema-digest", reflected.schema_digest,
            "--apply",
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version=version,
        policy="allow_changes",
    )
    assert exit_code == 2
    assert f"operation-schema {operation}" in payload["message"]


def test_zero_input_generic_mutation_enters_existing_preview_lifecycle(
    tmp_path: Path,
) -> None:
    version = "2025.1"
    api = "ak.wwise.core.profiler.startCapture"
    state_dir = tmp_path / "state"
    schema_exit, schema = execute(
        ["request-schema", api],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version=version,
    )
    assert schema_exit == 0
    assert schema["fields"] == []

    exit_code, payload = execute(
        [
            "typed-zero-call", api,
            "--schema-digest", schema["schema_digest"],
            "--apply",
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version=version,
        policy="ask_before_changes",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )

    assert exit_code == 0, json.dumps(payload, indent=2)
    assert payload["state"] == TransactionState.AWAITING_CONFIRMATION.value
    assert payload["typed_request"] == {
        "contract": "waapi-skill.typed-request/v1",
        "schema_digest": schema["schema_digest"],
        "business_values_required": False,
        "gateway_owned_acknowledgement": False,
    }
    artifact = TransactionStore(state_dir).load_preview(payload["transaction_id"]).artifact
    assert artifact["request"] == {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.call",
        "arguments": {"api": api, "args": {}, "options": {}},
    }
    assert artifact["prepared_operation"]["dispatch"] == {
        "uri": api,
        "args": {},
        "options": {},
    }


def test_soundengine_scalar_mutation_exposes_only_its_business_declaration(
    tmp_path: Path,
) -> None:
    version = "2021.1"
    api = "ak.soundengine.postMsgMonitor"
    schema_exit, schema = execute(
        ["request-schema", api],
        tmp_path=tmp_path,
        version=version,
    )
    assert schema_exit == 0
    assert schema["input_shape"] == "business_declaration"
    assert schema["native_request_fields_disclosed"] is False
    assert "fields" not in schema
    assert schema["business_adapter"]["declaration"] == {
        "subcommand": "draft-declare-soundengine-plan",
        "required_fields": ["monitor_message"],
        "optional_fields": [],
        "field_types": {"monitor_message": "bounded_exact_monitor_message"},
        "input_forms": {
            "monitor_message": {
                "flag": "--monitor-message",
                "repeatable": False,
            }
        },
    }
    assert schema["continuation"] == {
        "subcommand": "draft-start",
        "gateway_argv": ["draft-start", api],
        "copy_exactly": True,
        "append_arguments": "forbidden",
    }


def test_soundengine_listener_array_is_an_opaque_handle_business_set(
    tmp_path: Path,
) -> None:
    version = "2021.1"
    api = "ak.soundengine.setDefaultListeners"
    schema_exit, schema = execute(
        ["request-schema", api],
        tmp_path=tmp_path,
        version=version,
    )
    assert schema_exit == 0
    declaration = schema["business_adapter"]["declaration"]
    assert declaration["required_fields"] == []
    assert declaration["optional_fields"] == [
        "listener_handles",
        "clear_listeners",
    ]
    assert declaration["field_types"] == {
        "listener_handles": "gateway_runtime_game_object_handle_list",
        "clear_listeners": "explicit_boolean_intent",
    }
    assert declaration["input_forms"] == {
        "listener_handles": {
            "flag": "--listener-handle",
            "repeatable": True,
            "minimum_items": 1,
            "maximum_items": 64,
            "unique_items": True,
        },
        "clear_listeners": {
            "flag": "--clear-listeners",
            "repeatable": False,
        },
    }
    assert declaration["constraints"] == {
        "exactly_one_of": [["listener_handles", "clear_listeners"]]
    }
    assert "fields" not in schema


def test_zero_input_managed_read_dispatches_directly_with_its_route_contract(
    tmp_path: Path,
) -> None:
    version = "2022.1"
    api = "ak.wwise.core.transport.getList"
    schema_exit, schema = execute(
        ["request-schema", api],
        tmp_path=tmp_path,
        version=version,
    )
    assert schema_exit == 0
    assert "apply" not in schema["continuation"]

    exit_code, payload = execute(
        [
            "typed-zero-call", api,
            "--schema-digest", schema["schema_digest"],
        ],
        tmp_path=tmp_path,
        version=version,
        policy="read_only",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2022)],
                api: [{"list": []}],
            }
        ),
    )
    assert exit_code == 0, json.dumps(payload, indent=2)
    assert payload["agent_result"] == {"list": []}
    assert "transaction_id" not in payload


def test_compound_member_is_not_prematurely_exposed_by_request_schema(
    tmp_path: Path,
) -> None:
    version = "2025.1"
    api = "ak.wwise.core.undo.beginGroup"
    schema_exit, schema = execute(
        ["request-schema", api],
        tmp_path=tmp_path,
        version=version,
    )
    assert schema_exit == 2
    assert "compound Undo" in schema["message"]
    assert "waapi.undoGroup" in schema["message"]


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


def preview_and_confirm_soundengine_bank(
    operation: str,
    *,
    tmp_path: Path,
    state_dir: Path,
) -> dict[str, Any]:
    version = "2025.1"

    def live_client() -> FakeClient:
        return FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2025)],
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.object.get": [
                    {"return": [sound_bank_row()]},
                    {"return": [sound_bank_row()]},
                    {"return": [sound_bank_row()]},
                ],
            }
        )

    code, started = execute(
        ["draft-start", operation],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version=version,
    )
    assert code == 0, started
    draft = started["draft"]
    code, bound = execute(
        [
            "draft-bind-object",
            draft["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(draft["revision"]),
            "--role",
            "sound_bank",
            "--object-id",
            SOUND_BANK_GUID,
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=live_client(),
        version=version,
    )
    assert code == 0, bound
    code, declared = execute(
        [
            "draft-declare-soundengine-plan",
            draft["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(bound["draft"]["revision"]),
            "--sound-bank-handle",
            bound["bound_object"]["handle"],
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=live_client(),
        version=version,
    )
    assert code == 0, declared
    code, checked = execute(
        [
            "draft-check",
            draft["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=live_client(),
        version=version,
    )
    assert code == 0, checked
    code, transaction = execute(
        [
            "preview-from-draft",
            draft["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(checked["draft"]["revision"]),
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=live_client(),
        version=version,
    )
    assert code == 0, transaction
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
    assert payload["agent_control"]["required_outcome_before_reply"] == (
        "verified_or_structured_verification_failure"
    )
    assert payload["next_command"]["gateway_argv"][-2:] == [
        "verify",
        transaction["transaction_id"],
    ]
    return transaction, request, preview_client, execute_client


def test_operations_and_operation_schema_are_offline_closed_contracts(tmp_path: Path) -> None:
    exit_code, catalog = execute(["operations"], tmp_path=tmp_path)

    assert exit_code == 0
    assert catalog["ok"] is True
    assert catalog["offline"] is True
    operations = {item["name"]: item for item in catalog["operations"]}
    assert set(operations["object.create"]) == {"name", "summary", "next_command"}
    assert operations["object.create"]["next_command"] == [
        "operation-schema",
        "object.create",
    ]
    assert operations["object.copy"]["next_command"] == [
        "operation-schema",
        "object.copy",
    ]
    assert catalog["request_schema_routes"]
    assert catalog["detail_available"] is True
    assert catalog["request_schema_command_template"] == [
        "request-schema",
        "<api>",
    ]
    assert catalog["request_schema_route_count"] == len(catalog["request_schema_routes"])
    encoded_size = waapi_gateway.gateway_json_document_size(catalog)
    assert encoded_size < 48 * 1024
    assert "\n" not in waapi_gateway.gateway_stdout_json_encoder(catalog).encode(catalog)

    exit_code, detail_catalog = execute(["operations", "--detail"], tmp_path=tmp_path)

    assert exit_code == 0
    detailed = {item["name"]: item for item in detail_catalog["operations"]}
    request_schema_routes = {
        item["api"]: item for item in detail_catalog["request_schema_routes"]
    }
    project_save = request_schema_routes["ak.wwise.core.project.save"]
    assert "save the current Wwise project" in project_save["intent"]
    assert all(row["next_command"] for row in request_schema_routes.values())
    assert detail_catalog["request_schema_route_count"] == len(request_schema_routes)
    assert "ak.wwise.cli.generateSoundbank" in request_schema_routes
    assert "ak.wwise.console.project.open" in request_schema_routes
    assert "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInRegion" in request_schema_routes
    assert "ak.wwise.core.mediaPool.get" in request_schema_routes
    assert "ak.wwise.core.sound.setActiveSource" in request_schema_routes
    assert "ak.wwise.core.sourceControl.commit" in request_schema_routes
    assert set(detailed["object.create"]["input_modes_by_version"].values()) == {
        "business_declaration"
    }
    assert "argument_contract" not in detailed["object.create"]
    assert "constraints" not in detailed["object.create"]
    assert "identity_contract" not in detailed["object.create"]
    assert "business_contracts_by_version" in detailed["object.create"]
    assert "composer_contracts_by_version" not in detailed["object.create"]

    exit_code, schema = execute(["operation-schema", "object.setNotes"], tmp_path=tmp_path)

    assert exit_code == 0
    assert schema["ok"] is True
    assert schema["offline"] is True
    assert schema["operation"]["name"] == "object.setNotes"
    assert schema["operation"]["input_mode"] == "business_declaration"
    assert "required_arguments" not in schema["operation"]
    assert "argument_contract" not in schema["operation"]
    assert "identity_contract" not in schema["operation"]
    assert schema["operation"]["selection_guidance"]["use_when"] == [
        "Exactly one existing object receives only a notes change."
    ]
    assert schema["operation"]["selection_guidance"]["preferred_over"] == [
        {
            "target": "object.set",
            "when": "the request is only one isolated notes edit",
        }
    ]
    assert "request_envelope" not in schema
    assert "request_envelope_policy" not in schema
    assert "typed_operation" not in schema
    assert schema["business_adapter"]["operation"] == "object.setNotes"
    assert schema["business_adapter"]["declaration"]["required_fields"] == [
        "notes",
    ]

    for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"):
        exit_code, versioned = execute(
            ["operation-schema", "object.setNotes"],
            tmp_path=tmp_path,
            version=version,
        )
        assert exit_code == 0
        assert "request_envelope" not in versioned
        assert versioned["business_adapter"]["version"] == version

    exit_code, raw_call = execute(
        ["operation-schema", "waapi.call"],
        tmp_path=tmp_path,
        version="2022.1",
    )
    assert exit_code == 2
    assert raw_call["error_code"] == "INTERNAL_CANONICAL_OPERATION"

    exit_code, unsupported = execute(
        ["operation-schema", "object.set"],
        tmp_path=tmp_path,
        version="2021.1",
    )
    assert exit_code == 0
    assert "request_envelope" not in unsupported
    assert "request_envelope_policy" not in unsupported


def test_operation_schema_exposes_tab_import_business_progression(
    tmp_path: Path,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "audio.importTabDelimited"],
        tmp_path=tmp_path,
        version="2025.1",
    )

    assert exit_code == 0
    assert payload["offline"] is True
    assert "request_envelope" not in payload
    adapter = payload["business_adapter"]
    assert adapter["start"]["next_command"]["gateway_argv"] == (
        ["draft-start", "audio.importTabDelimited"]
    )
    assert adapter["binding"]["roles"] == ["import_location"]
    assert adapter["declaration"]["subcommand"] == (
        "draft-declare-artifact-plan"
    )
    assert adapter["declaration"]["required_fields"] == [
        "table_file",
        "location_handle",
        "language",
    ]
    assert adapter["legacy_inline_typed_public"] is False
    assert "typed_operation" not in payload


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
    adapter = payload["business_adapter"]
    declaration = adapter["declaration"]
    schema = declaration["schema"]
    assert declaration["subcommand"] == "draft-declare-soundbank-plan"
    assert declaration["submit_once"] is True
    assert schema["properties"]["mode"]["enum"] == ["add", "remove", "replace"]
    assert schema["properties"]["inclusions"]["emptyAllowedWhen"] == {
        "mode": "replace"
    }
    assert schema["properties"]["inclusions"]["maxItems"] == 128
    assert "composer" not in payload


@pytest.mark.parametrize("version", tuple(UNDO_GROUP_INNER_URIS_BY_VERSION))
def test_operation_schema_discloses_checked_child_business_contract_offline(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "waapi.undoGroup"],
        tmp_path=tmp_path,
        version=version,
    )

    assert exit_code == 0
    adapter = payload["business_adapter"]
    assert adapter["operation"] == "waapi.undoGroup"
    assert adapter["input_mode"] == "business_declaration"
    assert adapter["declaration"]["subcommand"] == "draft-declare-undo-plan"
    assert adapter["declaration"]["child_input"] == (
        "ordered_parent_owned_checked_closed_draft_snapshot"
    )
    assert adapter["legacy_composer_public"] is False
    assert adapter["legacy_child_schema_public"] is False
    assert "composer" not in payload
    assert all(
        not operation.startswith("ak.wwise.core.object.setNotes")
        for operation in adapter["declaration"][
            "prohibited_generic_child_operations"
        ]
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
    item = OPERATION_SPECS[operation].argument_contract["properties"]["commands"]["items"]
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


@pytest.mark.parametrize("version", EXPECTED_IMPORT_HIERARCHY_ROOTS)
def test_audio_import_operation_schema_keeps_native_hierarchy_mechanics_gateway_owned(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "audio.import"],
        tmp_path=tmp_path,
        version=version,
    )

    assert exit_code == 0
    assert payload["offline"] is True
    assert "request_envelope" not in payload
    assert "composer" not in payload
    adapter = payload["business_adapter"]
    assert adapter["version"] == version
    assert adapter["input_mode"] == "business_declaration"
    assert {"random-container", "sound-sfx", "sound-voice"} <= set(
        adapter["semantic_kinds"]
    )
    assert {"canonical_object_path", "native_object_type", "target_parent_handle"} <= set(
        adapter["gateway_derivations"]
    )
    assert "object_path" not in adapter["declaration_fields"]
    assert "object_type" not in adapter["declaration_fields"]
    assert adapter["legacy_shallow_composer_public"] is False

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
def test_object_create_operation_schema_discloses_versioned_business_graph_contract(
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
    assert payload["operation"]["input_mode"] == "business_declaration"
    adapter = payload["business_adapter"]
    assert adapter["operation"] == "object.create"
    assert adapter["version"] == version
    assert adapter["settings"]["name_conflict"] == [
        "fail",
        "rename",
        "merge",
        "replace",
    ]
    assert "native_object_type" in adapter["gateway_derivations"]
    assert "recursive_object_tree" in adapter["gateway_derivations"]
    assert adapter["legacy_shallow_composer_public"] is False
    assert "composer" not in payload
    assert "constraints" not in payload["operation"]
    assert default_work_unit_path
    assert actor_mixer_type


@pytest.mark.parametrize(
    ("version", "default_work_unit_path", "actor_mixer_type"),
    (
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
def test_object_set_operation_schema_owns_target_and_metadata_scope(
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
    assert payload["operation"]["input_mode"] == "business_declaration"
    adapter = payload["business_adapter"]
    assert adapter["version"] == version
    assert adapter["binding"] == {
        "existing_targets": "bound_object_handles",
        "new_descendants": "bound_or_planned_parent_handles",
        "fields": "live_discovered_field_handles",
        "long_tail_types": "live_discovered_type_handles",
    }
    assert adapter["settings"]["name_conflict"] == ["fail", "rename", "merge"]
    assert adapter["legacy_shallow_composer_public"] is False
    assert "composer" not in payload
    assert default_work_unit_path
    assert actor_mixer_type

@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_object_set_schema_keeps_metadata_tokens_gateway_owned(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = execute(
        ["operation-schema", "object.set"],
        tmp_path=tmp_path,
        version=version,
    )

    assert exit_code == 0
    adapter = payload["business_adapter"]
    assert adapter["binding"]["fields"] == "live_discovered_field_handles"
    assert "metadata_tokens" in adapter["gateway_derivations"]
    encoded = json.dumps(payload)
    assert "live_query_accessor_mapping" not in encoded
    assert "scalar_property" not in encoded
    assert "registry_fragments" not in encoded

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
    adapter = payload["business_adapter"]
    declaration = adapter["declaration"]
    fields = declaration["schema"]["properties"]
    assert fields["soundbanks"]["maxItems"] == 64
    assert fields["platforms"]["maxItems"] == 16
    assert fields["languages"]["maxItems"] == 64
    assert "skip_languages" not in fields
    assert "write_to_disk" not in fields
    bank_fields = fields["soundbanks"]["items"]["properties"]
    assert bank_fields["artifact_expectation"]["enum"] == [
        "nonlocalized",
        "localized",
        "mixed",
    ]
    assert bank_fields["rebuild"] == {"type": "boolean"}
    assert fields["rebuild_soundbanks"] == {"type": "boolean"}
    assert "language_skip_and_artifact_plan" in adapter["gateway_derivations"]
    assert "request_envelope" not in payload
    assert "composer" not in payload
    assert adapter["start"]["subcommand"] == "draft-start"
    assert declaration["subcommand"] == "draft-declare-soundbank-plan"


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_request_schema_owns_exact_audio_convert_business_route_contract(
    tmp_path: Path,
    version: str,
) -> None:
    factory_calls: list[str] = []

    def fail_if_connected(url: str) -> FakeClient:
        factory_calls.append(url)
        raise AssertionError(f"offline operation-schema connected to {url}")

    env = gateway_env(tmp_path, version=version)
    exit_code, payload = waapi_gateway.execute_gateway(
        ["request-schema", "ak.wwise.core.audio.convert"],
        env=env,
        client_factory=fail_if_connected,
    )

    assert exit_code == 0
    assert factory_calls == []
    assert payload["uri"] == "ak.wwise.core.audio.convert"
    assert payload["input_shape"] == "business_declaration"
    assert payload["continuation"]["subcommand"] == "draft-start"
    assert payload["continuation"]["gateway_argv"] == [
        "draft-start",
        "ak.wwise.core.audio.convert",
    ]
    declaration = payload["business_adapter"]["declaration"]
    assert declaration["required_fields"] == [
        "audio_object_handles",
        "platform_names",
        "languages",
        "io_root",
    ]
    assert declaration["field_types"]["io_root"] == "exact_user_io_root"
    assert payload["business_adapter"]["legacy_typed_call_public"] is False
    second_exit_code, second_payload = waapi_gateway.execute_gateway(
        ["request-schema", "ak.wwise.core.audio.convert"],
        env=env,
        client_factory=fail_if_connected,
    )
    assert second_exit_code == 0
    assert second_payload == payload
    assert factory_calls == []


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
        state_dir=state_dir,
        requires_explicit_user_confirmation=True,
    )
    assert list(payload).index("confirmation") > list(payload).index("events")
    assert list(payload).index("next_command") > list(payload).index("events")
    assert "session_context" not in payload
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
        state_dir=state_dir,
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
        state_dir=state_dir,
        requires_explicit_user_confirmation=True,
    )
    assert list(payload).index("next_command") > list(payload).index("events")
    assert "session_context" not in payload
    assert list(payload)[-1] == "next_command"
    assert waapi_gateway.gateway_json_document_size(payload) < 5_500
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
    assert payload["shell_tool_timeout_ms"] == 30_000
    assert payload["copy_instruction"]["source_field"] == "shell_command"
    assert payload["copy_instruction"]["contract"] == (
        "waapi-skill.gateway-command-copy-instruction/v2"
    )
    assert "select_another_field" in payload["copy_instruction"][
        "forbidden_transformations"
    ]
    assert "model_command" not in payload
    assert "model_shell_family" not in payload
    assert tuple(payload)[-2:] == ("copy_instruction", "shell_command")


def test_transaction_next_command_uses_short_task_local_posix_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = (
        tmp_path / ".agents" / "skills" / "waapi-skill" / "scripts" / "run.py"
    )
    monkeypatch.setattr(waapi_gateway, "os", type("PosixOS", (), {"name": "posix"})())
    monkeypatch.setattr(waapi_gateway, "GATEWAY_RUNNER_PATH", runner)

    payload = waapi_gateway.transaction_next_command(
        "execute",
        ["execute", "tx1-task-local"],
    )

    assert payload["full_argv"][1] == str(runner)
    assert payload["shell_command"] == (
        "python .agents/skills/waapi-skill/scripts/run.py "
        "gateway.py execute tx1-task-local"
    )
    selected = shlex.split(payload["shell_command"])
    assert (tmp_path / selected[1]).resolve() == runner.resolve()
    assert payload["copy_instruction"]["source_field"] == "shell_command"


def test_transaction_next_command_adds_one_short_copy_source_on_windows(
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
    assert payload["shell_command"] == encode_windows_powershell_argv(
        payload["full_argv"]
    )
    assert decode_windows_powershell_argv(payload["shell_command"]) == tuple(
        payload["full_argv"]
    )
    assert payload["model_shell_family"] == WINDOWS_MODEL_COMMAND_FAMILY
    assert payload["model_command"] == (
        "python 'C:\\WAAPI Skill\\scripts\\run.py' 'gateway.py' "
        "'execute' 'tx1-windows'"
    )
    assert decode_windows_model_argv(payload["model_command"]) == tuple(
        payload["full_argv"]
    )
    assert payload["copy_instruction"] == {
        "contract": "waapi-skill.gateway-command-copy-instruction/v2",
        "source_field": "model_command",
        "action": "execute_verbatim_as_one_shell_tool_call",
        "forbidden_transformations": [
            "reconstruct",
            "shorten",
            "normalize",
            "substitute_path_segments",
            "select_another_field",
        ],
    }
    assert tuple(payload)[-4:] == (
        "shell_command",
        "model_shell_family",
        "copy_instruction",
        "model_command",
    )

    serialized = json.dumps(payload, ensure_ascii=False)
    assert r"C:\\WAAPI Skill\\scripts\\run.py" in serialized
    decoded_payload = json.loads(serialized)
    assert decode_windows_model_argv(decoded_payload["model_command"]) == tuple(
        decoded_payload["full_argv"]
    )


@pytest.mark.parametrize(
    "runner_path",
    (
        PureWindowsPath("C:/Unsafe\u2018Skill/scripts/run.py"),
        PureWindowsPath("C:/" + "x" * 1100 + "/run.py"),
    ),
)
def test_transaction_next_command_falls_back_to_legacy_source_when_short_form_is_unsafe(
    runner_path: PureWindowsPath,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(waapi_gateway, "os", type("WindowsOS", (), {"name": "nt"})())
    monkeypatch.setattr(waapi_gateway, "GATEWAY_RUNNER_PATH", runner_path)

    payload = waapi_gateway.transaction_next_command(
        "execute",
        ["execute", "tx1-windows"],
    )

    assert payload["contract"] == "waapi-skill.gateway-next-command/v2"
    assert decode_windows_powershell_argv(payload["shell_command"]) == tuple(
        payload["full_argv"]
    )
    assert payload["copy_instruction"]["source_field"] == "shell_command"
    assert "select_another_field" in payload["copy_instruction"][
        "forbidden_transformations"
    ]
    assert "model_command" not in payload
    assert "model_shell_family" not in payload
    assert tuple(payload)[-2:] == ("copy_instruction", "shell_command")


@pytest.mark.parametrize(
    "command,gateway_argv",
    (
        (
            "transaction-show",
            ["transaction-show", "tx1-phase", "--summary-only"],
        ),
        (
            "confirm",
            [
                "confirm",
                "tx1-phase",
                "--confirmation-token",
                f"ct1-{'0' * 24}",
            ],
        ),
        ("execute", ["execute", "tx1-phase"]),
        ("verify", ["verify", "tx1-phase"]),
    ),
)
def test_transaction_next_command_uses_the_v2_windows_shape_for_every_phase(
    command: str,
    gateway_argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(waapi_gateway, "os", type("WindowsOS", (), {"name": "nt"})())
    monkeypatch.setattr(
        waapi_gateway,
        "GATEWAY_RUNNER_PATH",
        PureWindowsPath(r"C:\WAAPI Skill\scripts\run.py"),
    )

    payload = waapi_gateway.transaction_next_command(command, gateway_argv)

    assert payload["contract"] == "waapi-skill.gateway-next-command/v2"
    assert payload["command"] == command
    assert payload["gateway_argv"] == gateway_argv
    assert payload["shell_tool_timeout_ms"] == 30_000
    assert decode_windows_powershell_argv(payload["shell_command"]) == tuple(
        payload["full_argv"]
    )
    assert decode_windows_model_argv(payload["model_command"]) == tuple(
        payload["full_argv"]
    )
    assert payload["copy_instruction"]["source_field"] == "model_command"
    assert tuple(payload)[-4:] == (
        "shell_command",
        "model_shell_family",
        "copy_instruction",
        "model_command",
    )


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
        "build_transaction_preview_artifact",
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
                    "gateway_commands": ["request-schema"],
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
    token = store.load_snapshot("tx-confirm").confirmation_token
    assert token is not None

    exit_code, payload = execute(
        ["confirm", "tx-confirm", "--confirmation-token", token],
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
        state_dir=state_dir,
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
            "legacy-preview",
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
        state_dir=state_dir,
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
        state_dir=state_dir,
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
            "legacy-preview",
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
        state_dir=state_dir,
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
        state_dir=state_dir,
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
        state_dir=state_dir,
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
        state_dir=state_dir,
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


def test_confirm_rejects_tampered_token_and_preserves_awaiting_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = TransactionStore(state_dir)
    store.create_preview("tx-hash", {"operation": "object.setNotes"})
    store.submit_for_confirmation("tx-hash")

    exit_code, payload = execute(
        ["confirm", "tx-hash", "--confirmation-token", "0" * 64],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error_code"] == "ConfirmationTokenMismatch"
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


def test_public_gateway_legacy_json_preview_preserves_canonical_ingress_evidence(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "legacy-parity-state"
    raw_request = set_notes_request()
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
        }
    )

    payload = preview(
        raw_request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=client,
    )

    artifact = TransactionStore(state_dir).load_preview(
        payload["transaction_id"]
    ).artifact
    prepared = artifact["prepared_operation"]
    assert artifact["request"] == raw_request
    assert prepared["request"] == raw_request
    assert {
        name: waapi_gateway.canonical_sha256(prepared[name])
        for name in (
            "semantic_preview",
            "dispatch",
            "resolved_roles",
            "pre_state",
            "verification_plan",
            "cleanup",
        )
    } == {
        "semantic_preview": "eceab7e87eca5a77bf7ae1ee9bc178427b68097b967a1535f7f93c8363c980ea",
        "dispatch": "b8ccc42b55168a479fe6a14b7719f315138794c7b56bec2e27de6f336305c4c4",
        "resolved_roles": "47338924af9577e18c63efd4be0b0cdaa61e641c06e201ad86f749225e1ede16",
        "pre_state": "f0a2bc467715f31ed8a368bc47571331166ee6137dac1c6fb9730b7cfdf656f5",
        "verification_plan": "1d3f23aafa5c99092c9454e85545de2333365ea7f89d710bd5753117a043fe21",
        "cleanup": "f934bcfbbee2f0e6c1914e74b14b4b4277a16b493db78d23c2f0dcaee133cb66",
    }
    assert artifact["project_guard"] == waapi_gateway.build_project_guard(
        endpoint=payload["endpoint"],
        version="2022.1",
        live_info=live_info(),
        project=project(),
    )
    assert payload["preview_summary"] == {
        "contract": artifact["contract"],
        "request": raw_request,
        "dispatch": prepared["dispatch"],
        "resolved_roles": prepared["resolved_roles"],
        "pre_state": prepared["pre_state"],
        "verification_plan": prepared["verification_plan"],
        "cleanup": waapi_gateway.transaction_cleanup_payload(
            prepared,
            phase="preview",
        ),
        "project_guard_fingerprint": artifact["project_guard"]["fingerprint"],
        "runtime_guard_fingerprint": artifact["runtime_guard"]["fingerprint"],
        "expires_at": artifact["expires_at"],
    }
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.core.object.get",
    ]


@pytest.mark.parametrize(
    "bypass",
    (
        pytest.param(
            parse_operation_request(set_notes_request(), expected_version="2022.1"),
            id="preparsed-operation-request",
        ),
        pytest.param(
            {
                "contract": "waapi-skill.prepared-operation/v1",
                "request": set_notes_request(),
                "prepared_operation": {"dispatch": {"uri": "untrusted"}},
            },
            id="pseudo-prepared-operation",
        ),
    ),
)
def test_direct_transaction_preview_ingress_rejects_prevalidated_bypasses_before_io(
    bypass: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ForbiddenDependency:
        def __getattribute__(self, name: str) -> Any:
            raise AssertionError(f"preview bypass reached dependency {name}")

    monkeypatch.setattr(
        waapi_gateway,
        "TransactionStore",
        lambda *args, **kwargs: pytest.fail("preview bypass reached the store"),
    )

    with pytest.raises(
        waapi_gateway.GatewayInputError,
        match="raw canonical operation-request JSON object",
    ):
        waapi_gateway.create_transaction_preview(
            bypass,  # type: ignore[arg-type]
            args=ForbiddenDependency(),
            env=ForbiddenDependency(),
            connection=ForbiddenDependency(),
            detected_version="2022.1",
            live_info=ForbiddenDependency(),
            dispatcher=ForbiddenDependency(),
            common=ForbiddenDependency(),
        )


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
        ["legacy-preview", "--request-json", json.dumps(create_request())],
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
        ["legacy-preview", "--request-json", json.dumps(create_request())],
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
        ["legacy-preview", "--request-json", json.dumps(request)],
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
    assert execute_payload["agent_control"] == {
        "terminal": False,
        "required_outcome_before_reply": (
            "verified_or_structured_verification_failure"
        ),
        "next": "execute next_command.copy_instruction.source_field in same turn",
        "reply_before_next_command": "invalid",
    }
    assert execute_payload["next_command"] == expected_transaction_next_command(
        "verify",
        ["verify", transaction["transaction_id"]],
        state_dir=state_dir,
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
                "ak.wwise.core.getProjectInfo": [
                    {
                        **project(),
                        "directories": {"cache": "x" * 13_000},
                    }
                ],
                "ak.wwise.core.object.get": [{"return": [created_row()]}],
            }
        ),
    )

    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.VERIFIED.value
    assert verify_payload["agent_result"]["transaction_id"] == transaction[
        "transaction_id"
    ]
    assert verify_payload["stdout_projection"]["detail_level"] == (
        "digest-verification-evidence"
    )
    assert verify_payload["stdout_projection"][
        "full_verification_evidence_in_stdout"
    ] is False
    assert "result" not in verify_payload["project_call"]
    assert waapi_gateway.gateway_json_document_size(verify_payload) < 12_000
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
    transaction = preview_and_confirm_soundengine_bank(
        "ak.soundengine.loadBank",
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
        "args": {"soundBank": SOUND_BANK_GUID},
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
        "args": {"soundBank": SOUND_BANK_GUID},
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
                "ak.wwise.core.object.get": [{"return": [sound_bank_row()]}],
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
    transaction = preview_and_confirm_soundengine_bank(
        "ak.soundengine.loadBank",
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
            "ak.wwise.core.object.get": [{"return": [sound_bank_row()]}],
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
        "args": {"soundBank": SOUND_BANK_GUID},
        "options": {},
    }
    assert execute_payload["cleanup"]["spec"]["companion_request"]["args"] == {
        "soundBank": SOUND_BANK_GUID
    }
    assert not any(call[0] == "ak.soundengine.loadBank" for call in execute_client.calls)
    stored_spec = TransactionStore(state_dir).load_preview(
        transaction["transaction_id"]
    ).artifact["prepared_operation"]["cleanup"]
    assert stored_spec == transaction["cleanup"]["spec"]
    assert stored_spec["companion_request"]["args"] == {"soundBank": SOUND_BANK_GUID}


def test_concurrent_transaction_command_cannot_poison_active_execution(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "concurrent-execution-state"
    transport_id = 73
    transaction = preview_and_confirm_public_call(
        generic_public_call_request(
            "ak.wwise.core.transport.create",
            {"object": OBJECT_GUID},
        ),
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    dispatch_started = threading.Event()
    release_dispatch = threading.Event()

    class BlockingTransportClient(FakeClient):
        def call(
            self,
            uri: str,
            args: Mapping[str, Any] | None = None,
            options: Mapping[str, Any] | None = None,
        ) -> Any:
            if uri == "ak.wwise.core.transport.create":
                dispatch_started.set()
                if not release_dispatch.wait(timeout=10):
                    raise TimeoutError(
                        "test did not release the blocked WAAPI dispatch"
                    )
            return super().call(uri, args, options)

    active_client = BlockingTransportClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2025)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.transport.create": [{"transport": transport_id}],
        }
    )
    active_result: list[tuple[int, dict[str, Any]]] = []

    def run_active_execution() -> None:
        active_result.append(
            execute(
                ["execute", transaction["transaction_id"]],
                tmp_path=tmp_path,
                state_dir=state_dir,
                version="2025.1",
                client=active_client,
            )
        )

    active_thread = threading.Thread(target=run_active_execution)
    active_thread.start()
    assert dispatch_started.wait(timeout=10)
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is (
        TransactionState.EXECUTING
    )

    contender_exit, contender_payload = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=FakeClient(
            {"ak.wwise.core.getInfo": [live_info(year=2025)]}
        ),
    )

    assert contender_exit == 2
    assert contender_payload["status"] == "execution_in_progress"
    assert contender_payload["error_code"] == "TRANSACTION_EXECUTION_IN_PROGRESS"
    assert contender_payload["state"] == TransactionState.EXECUTING.value
    assert contender_payload["automatic_retry"] is False
    assert TransactionStore(state_dir).load(transaction["transaction_id"]).state is (
        TransactionState.EXECUTING
    )

    release_dispatch.set()
    active_thread.join(timeout=10)
    assert not active_thread.is_alive()
    assert len(active_result) == 1
    active_exit, active_payload = active_result[0]
    assert active_exit == 0, active_payload
    assert active_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert [call[0] for call in active_client.calls].count(
        "ak.wwise.core.transport.create"
    ) == 1

    replay_client = FakeClient(
        {"ak.wwise.core.getInfo": [live_info(year=2025)]}
    )
    replay_exit, replay_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=replay_client,
    )
    assert replay_exit == 2
    assert "must be explicitly confirmed" in replay_payload["message"]
    assert not any(
        call[0] == "ak.wwise.core.transport.create" for call in replay_client.calls
    )


def test_stale_executing_transaction_recovers_without_replaying_dispatch(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "stale-execution-state"
    transaction = preview_and_confirm_public_call(
        generic_public_call_request(
            "ak.wwise.core.transport.create",
            {"object": OBJECT_GUID},
        ),
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    store = TransactionStore(state_dir)
    store.begin_execution(
        transaction["transaction_id"],
        expected_authorization=TransactionState.CONFIRMED,
    )
    stale_client = FakeClient(
        {"ak.wwise.core.getInfo": [live_info(year=2025)]}
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=stale_client,
    )

    assert exit_code == 2
    assert payload["status"] == "indeterminate"
    assert payload["state"] == TransactionState.INDETERMINATE.value
    assert payload["automatic_retry"] is False
    assert not any(
        call[0] == "ak.wwise.core.transport.create" for call in stale_client.calls
    )
    assert store.load(transaction["transaction_id"]).state is (
        TransactionState.INDETERMINATE
    )
    event_types = [
        event["event_type"]
        for event in store.read_events(transaction["transaction_id"])
    ]
    assert event_types[-2:] == ["execution_started", "execution_indeterminate"]


def test_transport_create_materializes_destroy_request_in_execute_verify_and_agent_result(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "transport-state"
    # Wwise 2022.1 Authoring proves that zero is a live uint32 transport ID.
    transport_id = 0
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
                {"list": [{"transport": transport_id, "object": OBJECT_GUID, "gameObject": 1}]},
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
    business_result = verify_payload["agent_result"]["business_result"]
    assert business_result["contract"] == "waapi-skill.runtime-control-result/v1"
    transport_handle = business_result["transport_handle"]
    assert re.fullmatch(r"trh1-[0-9a-f]{32}", transport_handle)
    issued = RuntimeTransportHandleStore(state_dir).resolve(
        transport_handle,
        context=RuntimeTransportContext(
            endpoint_url="ws://127.0.0.1:31337/waapi",
            project_id=PROJECT_GUID,
            project_path=project()["path"],
            wwise_version="2025.1",
            wwise_build="v2025.1.19",
        ),
    )
    assert issued.transport_id == transport_id
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


def test_verified_transport_destroy_retires_every_gateway_handle_for_reused_id(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "transport-retire-state"
    transport_id = 73
    context = RuntimeTransportContext(
        endpoint_url="ws://127.0.0.1:31337/waapi",
        project_id=PROJECT_GUID,
        project_path=project()["path"],
        wwise_version="2025.1",
        wwise_build="v2025.1.19",
    )
    handle_store = RuntimeTransportHandleStore(state_dir)
    live_transport_row = {
        "transport": transport_id,
        "object": OBJECT_GUID,
        "gameObject": 1,
    }
    issued = handle_store.issue(
        transport_id=transport_id,
        context=context,
        source_transaction_id="tx1-testtransportretire00",
        source_artifact_hash="f" * 64,
        transport_row_sha256=canonical_sha256(live_transport_row),
    )
    request = generic_public_call_request(
        "ak.wwise.core.transport.destroy",
        {"transport": transport_id},
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
                "ak.wwise.core.transport.getList": [
                    {"list": [live_transport_row]}
                ],
                "ak.wwise.core.transport.destroy": [{}],
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
                "ak.wwise.core.getProjectInfo": [project()],
                "ak.wwise.core.transport.getList": [{"list": []}],
            }
        ),
    )

    assert verify_exit == 0, verify_payload
    assert verify_payload["agent_result"]["business_result"] == {
        "contract": "waapi-skill.runtime-control-result/v1",
        "retired_transport_handle_count": 1,
    }
    with pytest.raises(RuntimeTransportHandleError) as caught:
        handle_store.resolve(issued.handle, context=context)
    assert caught.value.error_code == "TRANSPORT_HANDLE_RETIRED"


def test_transport_execution_rejects_same_numeric_id_reused_for_another_row(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "transport-reuse-state"
    transport_id = 73
    context = RuntimeTransportContext(
        endpoint_url="ws://127.0.0.1:31337/waapi",
        project_id=PROJECT_GUID,
        project_path=project()["path"],
        wwise_version="2025.1",
        wwise_build="v2025.1.19",
    )
    original_row = {
        "transport": transport_id,
        "object": OBJECT_GUID,
        "gameObject": 1,
    }
    RuntimeTransportHandleStore(state_dir).issue(
        transport_id=transport_id,
        context=context,
        source_transaction_id="tx1-testtransportreuse000",
        source_artifact_hash="f" * 64,
        transport_row_sha256=canonical_sha256(original_row),
    )
    transaction = preview_and_confirm_public_call(
        generic_public_call_request(
            "ak.wwise.core.transport.destroy",
            {"transport": transport_id},
        ),
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    reused_row = {
        "transport": transport_id,
        "object": "{99999999-9999-9999-9999-999999999999}",
        "gameObject": 2,
    }
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2025)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.transport.getList": [{"list": [reused_row]}],
        }
    )

    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version="2025.1",
        client=client,
    )

    assert execute_exit == 2
    assert execute_payload["status"] == "repreview_required"
    assert execute_payload["error_code"] == "TRANSPORT_HANDLE_STALE"
    assert execute_payload["executed"] is False
    assert all(call[0] != "ak.wwise.core.transport.destroy" for call in client.calls)


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
    transaction = preview_and_confirm_soundengine_bank(
        "ak.soundengine.loadBank",
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
                "ak.wwise.core.object.get": [{"return": [sound_bank_row()]}],
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
    transaction = preview_and_confirm_soundengine_bank(
        "ak.soundengine.unloadBank",
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
                "ak.wwise.core.object.get": [{"return": [sound_bank_row()]}],
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
    preview_command = (
        "legacy-preview"
        if operation
        in {
            "audio.import",
            "audio.importTabDelimited",
            "object.set",
            "soundbank.convertExternalSources",
            "soundbank.generate",
            "soundbank.processDefinitionFiles",
            "soundbank.setInclusions",
        }
        else "preview"
    )

    exit_code, payload = execute(
        [
            "--host",
            "192.0.2.10",
            preview_command,
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
        "build_transaction_preview_artifact",
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


def test_remote_named_capture_screen_still_requires_authoring(
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
            "legacy-preview",
            "--request-json",
            json.dumps(request),
        ],
        tmp_path=tmp_path,
        state_dir=tmp_path / "remote-capture",
        client=client,
    )

    assert exit_code == 2, payload
    assert payload["error_code"] == "AUTHORING_HOST_REQUIRED"
    assert [call[0] for call in client.calls] == ["ak.wwise.core.getInfo"]


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


def test_console_project_open_selects_the_sealed_isolated_io_audit() -> None:
    target = Path("/tmp/case/TargetProject.wproj")
    audit = {
        "contract": "waapi-skill.io-audit/v1",
        "uri": "ak.wwise.console.project.open",
        "paths": [
            {
                "section": "args",
                "json_path": "$.args.path",
                "raw_path": str(target),
                "resolved_path": str(target),
            }
        ],
    }
    prepared = {
        "pre_state": {
            "execution_contract": {
                "io_audit": audit,
            }
        }
    }

    selected = waapi_gateway.prepared_wire_path_io_audit(
        operation="waapi.call",
        call_uri="ak.wwise.console.project.open",
        prepared=prepared,
    )

    assert selected == audit


@pytest.mark.skipif(
    os.name == "nt",
    reason="Wine host path translation is POSIX-only",
)
def test_local_wine_authoring_project_open_translates_target_after_close(
    tmp_path: Path,
) -> None:
    version = "2022.1"
    api = "ak.wwise.ui.project.open"
    state_dir = tmp_path / "wine-authoring-project-state"
    target = (tmp_path / "target" / "TargetProject.wproj").resolve()
    target.parent.mkdir()
    target.write_text("<Project/>", encoding="utf-8")
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": api,
            "args": {"path": str(target)},
            "options": {},
            "io_root": str(target.parent),
        },
    }
    authoring_info = wine_live_info()
    authoring_info["isCommandLine"] = False
    authoring_info["processPath"] = (
        r"c:\Program Files\Audiokinetic\Wwise\Wwise.exe"
    )
    no_project = {"ak.wwise.core.object.get": [{"return": []}]}
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [authoring_info],
                **no_project,
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [authoring_info],
            "ak.wwise.core.object.get": [{"return": []}],
            api: [{}],
        }
    )

    exit_code, payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version=version,
    )

    assert exit_code == 0, json.dumps(payload, indent=2)
    assert next(call for call in execute_client.calls if call[0] == api) == (
        api,
        {"path": z_wire_path(target)},
        {},
    )
    assert payload["wire_path_adaptation"]["mapping"]["anchor_source"] == (
        "transition_target"
    )


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

    # Both conversion and migration must follow the returned verify continuation.
    # That context/runtime-only verification never probes an Authoring project
    # that the CLI process may already have unloaded.
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
    ("version", "api", "guard_mode", "outcome"),
    [(*row, "completed") for row in PROJECT_TRANSITION_ROWS]
    + [
        (*row, outcome)
        for row in PROJECT_TRANSITION_ROWS
        if row[0] in {"2024.1", "2025.1"}
        and row[1] in {"ak.wwise.ui.project.open", "ak.wwise.ui.project.close"}
        for outcome in ("cancelled", "timeout")
    ],
    ids=lambda value: str(value),
)
def test_every_project_transition_row_runs_one_complete_program_chain(
    tmp_path: Path,
    version: str,
    api: str,
    guard_mode: str,
    outcome: str,
) -> None:
    year = int(version.split(".", 1)[0])
    is_command_line = not api.startswith("ak.wwise.ui.")
    state_dir = tmp_path / "state"
    io_root = (tmp_path / "io-root").resolve()
    target_path = io_root / "TargetProject.wproj"
    current_path = (tmp_path / "current-project" / "CurrentProject.wproj").resolve()
    contract = ExecutionContractRegistry().authoring_ui_describe(version, api)
    call_args: dict[str, Any] = {}
    arguments: dict[str, Any] = {"api": api, "args": call_args, "options": {}}
    if guard_mode == PROJECT_GUARD_TRANSITION_TO_PATH:
        call_args["path"] = str(target_path)
    if api in {"ak.wwise.ui.project.open", "ak.wwise.ui.project.close"}:
        call_args["bypassSave"] = False
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
            "ak.wwise.core.getInfo": [
                live_info(year=year, is_command_line=is_command_line)
            ],
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

    result = (
        {"hadProjectOpen": True}
        if api.endswith(".close") and version in {"2021.1", "2022.1", "2023.1"}
        else {}
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [
                live_info(year=year, is_command_line=is_command_line)
            ],
            "ak.wwise.core.object.get": [{"return": before_rows}],
            api: [result],
        },
        errors={api: [TimeoutError("save prompt still pending")]} if outcome == "timeout" else None,
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version=version,
    )
    if outcome == "timeout":
        assert execute_exit != 0, execute_payload
        assert execute_payload["state"] == TransactionState.INDETERMINATE.value
        replay_client = FakeClient({
            "ak.wwise.core.getInfo": [live_info(year=year, is_command_line=is_command_line)],
            "ak.wwise.core.object.get": [{"return": before_rows}],
        })
        replay_exit, _ = execute(
            ["execute", transaction["transaction_id"]], tmp_path=tmp_path,
            state_dir=state_dir, client=replay_client, version=version,
        )
        assert replay_exit != 0
        assert all(call[0] != api for call in replay_client.calls)
        assert [call[0] for call in execute_client.calls].count(api) == 1
        return
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
    if outcome == "cancelled":
        after_rows = before_rows
    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [
                live_info(year=year, is_command_line=is_command_line)
            ],
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
    if outcome == "cancelled":
        assert verify_exit != 0, verify_payload
        assert verify_payload["state"] == TransactionState.EXECUTED_UNVERIFIED.value
        assert verify_payload.get("verified") is not True
        assert verify_payload["ok"] is False
        assert [call[0] for call in execute_client.calls].count(api) == 1
        assert all(call[0] != api for call in verify_client.calls)
        return
    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.VERIFIED.value
    assert verify_payload["verified"] is True
    assert verify_payload["result_schema_checked"] is False
    assert verify_payload["verification"]["business_state_verified"] is True
    assert verify_payload["verification"]["readbacks"][-1]["kind"] == "project-transition-observation"
    assert verify_payload["guard_validation"]["project_transition"]["matched"] is True
    assert verify_payload["agent_result"]["verified"] is True


def test_project_transition_verify_waits_through_transient_authoring_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = "2022.1"
    api = "ak.wwise.ui.project.close"
    state_dir = tmp_path / "state"
    current_path = (tmp_path / "current" / "CurrentProject.wproj").resolve()
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "waapi.call",
        "arguments": {"api": api, "args": {}, "options": {}},
    }
    before = [{**project(path=str(current_path)), "type": "Project"}]
    transaction = preview(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(is_command_line=False)],
                "ak.wwise.core.object.get": [{"return": before}],
            }
        ),
    )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_exit, execute_payload = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(is_command_line=False)],
                "ak.wwise.core.object.get": [{"return": before}],
                api: [{"hadProjectOpen": True}],
            }
        ),
        version=version,
    )
    assert execute_exit == 0, execute_payload
    monkeypatch.setattr(waapi_gateway.time, "sleep", lambda _seconds: None)
    locked = WaapiRequestFailed(
        "ak.wwise.locked",
        {
            "message": "Cannot execute call because Wwise has an exclusive lock.",
            "details": {"reasons": ["Closing project in progress"]},
        },
    )
    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(is_command_line=False)],
            "ak.wwise.core.object.get": [{"return": []}],
        },
        errors={"ak.wwise.core.getInfo": [locked]},
    )

    verify_exit, verified = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
        version=version,
    )

    assert verify_exit == 0, verified
    assert verified["state"] == TransactionState.VERIFIED.value
    assert verified["guard_validation"]["project_transition"]["matched"] is True
    assert [call[0] for call in verify_client.calls].count(
        "ak.wwise.core.getInfo"
    ) == 2


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_authoring_project_open_draft_allows_no_current_project(
    tmp_path: Path,
    version: str,
) -> None:
    operation = "ak.wwise.ui.project.open"
    state_dir = tmp_path / "state"
    target = (tmp_path / "target" / "TargetProject.wproj").resolve()
    target.parent.mkdir()
    target.write_text("fixture", encoding="utf-8")
    code, started = execute(
        ["draft-start", operation],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version=version,
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    def no_project_client() -> FakeClient:
        return FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=int(version[:4]), is_command_line=False)],
                "ak.wwise.core.object.get": [{"return": []}],
            },
            errors={
                "ak.wwise.core.getProjectInfo": [
                    WaapiRequestFailed(
                        "ak.wwise.unavailable",
                        {"message": "No project is loaded"},
                    )
                ]
            },
        )

    code, declared = execute(
        [
            "draft-declare-host-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "1",
            "--value",
            "project_file",
            str(target),
            "--value",
            "upgrade_policy",
            "fail",
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=no_project_client(),
        version=version,
    )
    assert code == 0, declared
    code, checked = execute(
        [
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=no_project_client(),
        version=version,
    )
    assert code == 0, checked
    code, previewed = execute(
        [
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked["draft"]["revision"]),
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=no_project_client(),
        version=version,
    )

    assert code == 0, previewed
    assert previewed["state"] == TransactionState.AWAITING_CONFIRMATION.value
    artifact = TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact
    assert artifact["request"]["arguments"]["args"]["bypassSave"] is False
    guard = artifact["project_guard"]
    assert guard["project_guard_mode"] == PROJECT_GUARD_TRANSITION_TO_PATH
    assert guard["project"]["state"] == "none"


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
                "ak.wwise.core.getInfo": [live_info(is_command_line=False)],
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
                "ak.wwise.core.getInfo": [live_info(is_command_line=False)],
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
                "ak.wwise.core.getInfo": [live_info(is_command_line=False)],
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


def test_undo_group_success_uses_one_client_and_aggregates_child_verification(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    transaction = preview_and_confirm_undo_group(tmp_path=tmp_path, state_dir=state_dir)
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2023)],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
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
                "ak.wwise.core.object.get": [
                    {"return": [object_row(notes="after")]}
                ],
            }
        ),
        version="2023.1",
    )

    assert verify_exit == 0, verify_payload
    assert verify_payload["state"] == TransactionState.VERIFIED.value
    assert verify_payload["verified"] is True
    assert verify_payload["verification"]["business_state_verified"] is True
    assert verify_payload["verification"]["verification_strength"] == (
        "compound_child_readback"
    )
    assert any(
        assertion["name"].startswith("Undo Group child[0]")
        for assertion in verify_payload["verification"]["assertions"]
    )


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
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
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
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
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
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
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
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
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
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
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
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
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
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
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
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
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
