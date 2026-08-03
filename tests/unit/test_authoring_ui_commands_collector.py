from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from tests.maintenance.collect_authoring_ui_commands import (
    COMMAND_INVENTORY_FILENAME,
    GET_COMMANDS_URI,
    GET_INFO_URI,
    GET_SCHEMA_URI,
    MAX_COMMAND_COUNT,
    MAX_COMMAND_ID_CHARS,
    AuthoringUiCommandsCollectionError,
    build_command_inventory,
    collect_authoring_ui_commands,
    execute_maintenance,
)
from wwise_waapi.authoring_ui_commands_manifest import (  # pyright: ignore[reportMissingImports]
    AUTHORING_UI_COMMAND_URIS,
    AUTHORING_UI_COMMANDS_SUPPLEMENT_FILENAME,
)
from wwise_waapi.canonical import canonical_sha256  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import (  # pyright: ignore[reportMissingImports]
    DeterministicJsonWriter,
)


VERSION = "2024.1"
BUILD = "2024.1.13.9056"
BASE_URI = "ak.wwise.core.getInfo"
COMMANDS = [
    "ak.fixture.ProjectCommand",
    "ak.fixture.PluginCommand",
    "ak.fixture.Command",
]


class FakeCaller:
    def __init__(
        self,
        *,
        info: Mapping[str, Any] | None = None,
        commands: list[str] | None = None,
        schema_value: Any | None = None,
    ) -> None:
        self.info = deepcopy(dict(info or _authoring_info()))
        self.commands = list(commands or COMMANDS)
        self.schema_value = (
            schema_value
            if schema_value is not None
            else {
                "argsSchema": {"type": "object"},
                "fixturePath": (
                    "/Applications/Audiokinetic/Wwise2024.1/"
                    "SampleProject/SampleProject.wproj"
                ),
            }
        )
        self.calls: list[
            tuple[str, tuple[Any, ...], dict[str, Any]]
        ] = []
        self.disconnected = False

    def call(self, uri: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((uri, args, kwargs))
        if uri == GET_INFO_URI:
            return deepcopy(self.info)
        if uri == GET_SCHEMA_URI:
            assert len(args) == 1
            assert args[0]["uri"] in AUTHORING_UI_COMMAND_URIS
            return deepcopy(self.schema_value)
        if uri == GET_COMMANDS_URI:
            return {"commands": list(self.commands)}
        raise AssertionError(f"unexpected WAAPI call: {uri}")

    def disconnect(self) -> None:
        self.disconnected = True


def _authoring_info() -> dict[str, Any]:
    return {
        "displayName": "Wwise",
        "isCommandLine": False,
        "version": {
            "build": 9056,
            "displayName": BUILD,
            "major": 1,
            "minor": 13,
            "year": 2024,
        },
    }


def _function(uri: str) -> dict[str, Any]:
    return {
        "reflection": {"uri": uri},
        "type": "function",
        "uri": uri,
    }


def _schema(uri: str) -> dict[str, Any]:
    return {
        "schema": {"fixture": True},
        "status": "ok",
        "uri": uri,
    }


def test_deterministic_json_writer_persists_exact_utf8_lf_bytes(tmp_path: Path) -> None:
    writer = DeterministicJsonWriter()
    payload = {"z": "音频", "a": [1, 2]}
    path = tmp_path / "nested" / "resource.json"

    writer.write(path, payload)

    assert path.read_bytes() == writer.dumps(payload).encode("utf-8")
    assert path.read_bytes().endswith(b"\n")
    assert b"\r\n" not in path.read_bytes()


def _write_console_manifest(root: Path) -> None:
    version_dir = root / VERSION
    writer = DeterministicJsonWriter()
    metadata = {
        "host_surface": "wwise-console",
        "wwise_build": BUILD,
        "wwise_version_target": VERSION,
    }
    writer.write(
        version_dir / "manifest.json",
        {
            "audit": {
                "manifest_function_count": 1,
                "manifest_topic_count": 0,
                "reflected_function_count": 1,
                "reflected_topic_count": 0,
                "schema_count": 1,
                "schema_failure_count": 0,
            },
            "metadata": metadata,
        },
    )
    writer.write(
        version_dir / "functions.json",
        {"functions": [_function(BASE_URI)], "metadata": metadata},
    )
    writer.write(
        version_dir / "topics.json",
        {"metadata": metadata, "topics": []},
    )
    writer.write(
        version_dir / "schemas.json",
        {"metadata": metadata, "schemas": [_schema(BASE_URI)]},
    )


def _expected_call_plan() -> list[
    tuple[str, tuple[Any, ...], dict[str, Any]]
]:
    return [
        (GET_INFO_URI, (), {}),
        *[
            (GET_SCHEMA_URI, ({"uri": uri},), {})
            for uri in sorted(AUTHORING_UI_COMMAND_URIS)
        ],
        (GET_COMMANDS_URI, (), {}),
    ]


def test_collector_uses_only_the_fixed_seven_call_plan(tmp_path: Path) -> None:
    _write_console_manifest(tmp_path)
    caller = FakeCaller()

    artifacts = collect_authoring_ui_commands(
        caller,
        version=VERSION,
        manifest_root=tmp_path,
    )

    assert caller.calls == _expected_call_plan()
    assert "ak.wwise.waapi.getFunctions" not in {
        uri for uri, _args, _kwargs in caller.calls
    }
    assert "ak.wwise.waapi.getTopics" not in {
        uri for uri, _args, _kwargs in caller.calls
    }
    assert artifacts.supplement.audit.added_function_count == 4
    assert artifacts.supplement.audit.added_topic_count == 1
    assert artifacts.supplement.audit.added_schema_count == 5
    assert artifacts.command_inventory["commands"] == sorted(COMMANDS)
    assert artifacts.command_inventory["audit"]["command_count"] == 3
    assert (
        artifacts.command_inventory["metadata"][
            "absolute_cross_machine_inventory"
        ]
        is False
    )
    assert (
        artifacts.command_inventory["metadata"][
            "observed_current_project_and_plugins"
        ]
        is True
    )
    assert all(
        row["schema"]["fixturePath"] == "<path>"
        for row in artifacts.supplement.schemas
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda info: info.update({"isCommandLine": True}),
            "isCommandLine=false",
        ),
        (
            lambda info: info["version"].update({"year": 2025}),
            "version is 2025.1",
        ),
        (
            lambda info: info["version"].update({"build": 9999}),
            "build is 2024.1.13.9999",
        ),
    ],
)
def test_host_version_and_build_fail_before_schema_calls(
    tmp_path: Path,
    mutate: Any,
    message: str,
) -> None:
    _write_console_manifest(tmp_path)
    info = _authoring_info()
    mutate(info)
    caller = FakeCaller(info=info)

    with pytest.raises(
        AuthoringUiCommandsCollectionError,
        match=re_escape(message),
    ):
        collect_authoring_ui_commands(
            caller,
            version=VERSION,
            manifest_root=tmp_path,
        )

    assert caller.calls == [(GET_INFO_URI, (), {})]


def test_command_inventory_has_count_digest_and_closed_bounds() -> None:
    payload = build_command_inventory(
        {"commands": ["z.command", "a.command"]},
        version=VERSION,
        wwise_build=BUILD,
    )
    unsigned = {
        "commands": payload["commands"],
        "contract": payload["contract"],
        "metadata": payload["metadata"],
    }

    assert payload["commands"] == ["a.command", "z.command"]
    assert payload["audit"] == {
        "command_count": 2,
        "inventory_sha256": canonical_sha256(unsigned),
    }
    assert payload["metadata"]["inventory_scope"] == (
        "observed-current-authoring-session"
    )
    assert "current_project" in payload["metadata"]["variation_factors"]
    assert "installed_plugins" in payload["metadata"]["variation_factors"]

    with pytest.raises(
        AuthoringUiCommandsCollectionError,
        match="duplicate command IDs",
    ):
        build_command_inventory(
            {"commands": ["same", "same"]},
            version=VERSION,
            wwise_build=BUILD,
        )
    with pytest.raises(
        AuthoringUiCommandsCollectionError,
        match="item ceiling",
    ):
        build_command_inventory(
            {"commands": [f"command.{index}" for index in range(MAX_COMMAND_COUNT + 1)]},
            version=VERSION,
            wwise_build=BUILD,
        )
    with pytest.raises(
        AuthoringUiCommandsCollectionError,
        match="characters",
    ):
        build_command_inventory(
            {"commands": ["x" * (MAX_COMMAND_ID_CHARS + 1)]},
            version=VERSION,
            wwise_build=BUILD,
        )
    with pytest.raises(
        AuthoringUiCommandsCollectionError,
        match="only 'commands'",
    ):
        build_command_inventory(
            {"commands": [], "unexpected": True},
            version=VERSION,
            wwise_build=BUILD,
        )


def test_non_finite_schema_fails_before_get_commands(tmp_path: Path) -> None:
    _write_console_manifest(tmp_path)
    caller = FakeCaller(schema_value={"invalid": float("nan")})

    with pytest.raises(
        AuthoringUiCommandsCollectionError,
        match="finite JSON",
    ):
        collect_authoring_ui_commands(
            caller,
            version=VERSION,
            manifest_root=tmp_path,
        )

    assert caller.calls == [
        (GET_INFO_URI, (), {}),
        (
            GET_SCHEMA_URI,
            ({"uri": sorted(AUTHORING_UI_COMMAND_URIS)[0]},),
            {},
        ),
    ]


def test_cli_defaults_to_preview_then_writes_deterministic_resources(
    tmp_path: Path,
) -> None:
    _write_console_manifest(tmp_path)
    created: list[FakeCaller] = []

    def factory(_url: str) -> FakeCaller:
        caller = FakeCaller()
        created.append(caller)
        return caller

    common_args = [
        "--version",
        VERSION,
        "--manifest-root",
        str(tmp_path),
    ]
    preview = execute_maintenance(common_args, caller_factory=factory)
    supplement_path = (
        tmp_path
        / VERSION
        / AUTHORING_UI_COMMANDS_SUPPLEMENT_FILENAME
    )
    inventory_path = tmp_path / VERSION / COMMAND_INVENTORY_FILENAME

    assert preview["mode"] == "preview"
    assert preview["repository_write_performed"] is False
    assert not supplement_path.exists()
    assert not inventory_path.exists()
    assert created[-1].disconnected is True
    assert created[-1].calls == _expected_call_plan()

    written = execute_maintenance(
        [*common_args, "--write"],
        caller_factory=factory,
    )
    assert written["mode"] == "write"
    assert written["repository_write_performed"] is True
    assert supplement_path.is_file()
    assert inventory_path.is_file()
    first_supplement = supplement_path.read_bytes()
    first_inventory = inventory_path.read_bytes()
    artifact_by_kind = {
        row["kind"]: row for row in written["artifacts"]
    }
    assert artifact_by_kind["authoring_ui_commands_supplement"][
        "sha256"
    ] == hashlib.sha256(first_supplement).hexdigest()
    assert artifact_by_kind["authoring_ui_command_inventory"][
        "sha256"
    ] == hashlib.sha256(first_inventory).hexdigest()

    repeated = execute_maintenance(
        [*common_args, "--write"],
        caller_factory=factory,
    )
    assert supplement_path.read_bytes() == first_supplement
    assert inventory_path.read_bytes() == first_inventory
    assert repeated["artifacts"] == written["artifacts"]
    assert all(caller.disconnected for caller in created)
    assert json.loads(first_inventory)["audit"]["command_count"] == 3


def re_escape(value: str) -> str:
    """Keep parametrized error assertions readable without importing regex."""

    return value.replace(".", r"\.")
