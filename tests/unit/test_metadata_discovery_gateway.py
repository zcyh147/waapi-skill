from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest  # pyright: ignore[reportMissingImports]


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_gateway_metadata_discovery_tests",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


GET_INFO_URI = "ak.wwise.core.getInfo"
OBJECT_GET_URI = "ak.wwise.core.object.get"
GET_TYPES_URI = "ak.wwise.core.object.getTypes"
GET_NAMES_URI = "ak.wwise.core.object.getPropertyAndReferenceNames"
GET_PROPERTY_INFO_URI = "ak.wwise.core.object.getPropertyInfo"
PROJECT_GUID = "{11111111-1111-1111-1111-111111111111}"
OBJECT_GUID = "{22222222-2222-2222-2222-222222222222}"
SESSION_A = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
SESSION_B = "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"
SOUND_CLASS_ID = 65552

ResponseFactory = Callable[
    [Mapping[str, Any] | None, Mapping[str, Any] | None],
    Any,
]


class FakeClient:
    def __init__(
        self,
        responses: Mapping[str, Any | ResponseFactory],
        *,
        errors: Mapping[str, Exception] | None = None,
    ) -> None:
        self.responses = dict(responses)
        self.errors = dict(errors or {})
        self.calls: list[
            tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]
        ] = []
        self.disconnected = False

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        if uri in self.errors:
            raise self.errors[uri]
        response = self.responses[uri]
        if callable(response):
            return response(args, options)
        return response

    def disconnect(self) -> None:
        self.disconnected = True


def _gateway_env(
    tmp_path: Path,
    *,
    version: str = "2022.1",
    state_dir: Path | None = None,
) -> dict[str, str]:
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    env = {
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": version,
        "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence"),
    }
    if state_dir is not None:
        env["WAAPI_SKILL_STATE_DIR"] = str(state_dir)
    return env


def _live_info(
    version: str,
    *,
    session_id: str = SESSION_A,
    process_id: int = 4242,
) -> dict[str, Any]:
    year, major = (int(part) for part in version.split("."))
    build = {
        "2021.1": 8108,
        "2022.1": 8584,
        "2023.1": 8928,
        "2024.1": 9056,
        "2025.1": 9143,
    }[version]
    return {
        "displayName": "Wwise",
        "isCommandLine": True,
        "processId": process_id,
        "sessionId": session_id,
        "version": {
            "year": year,
            "major": major,
            "minor": 19,
            "build": build,
            "schema": 110 + (year - 2021),
            "displayName": f"v{version}.19",
        },
    }


def _project_row(tmp_path: Path) -> dict[str, Any]:
    return {
        "id": PROJECT_GUID,
        "name": "SampleProject",
        "type": "Project",
        "path": str(tmp_path / "project" / "SampleProject.wproj"),
    }


def _property_info(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "type": "Real32",
        "default": 0.0,
        "display": {"name": name},
        "restriction": {"min": -96.3, "max": 12.0},
        "dependencies": [],
    }


def _metadata_responses(
    tmp_path: Path,
    *,
    version: str = "2022.1",
    session_id: str = SESSION_A,
    names: tuple[str, ...] = ("Volume",),
    project_result: Mapping[str, Any] | None = None,
) -> dict[str, Any | ResponseFactory]:
    def property_info(
        args: Mapping[str, Any] | None,
        _options: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        assert isinstance(args, Mapping)
        name = args.get("property")
        assert isinstance(name, str)
        assert name in names
        return _property_info(name)

    return {
        GET_INFO_URI: _live_info(version, session_id=session_id),
        OBJECT_GET_URI: (
            {"return": [_project_row(tmp_path)]}
            if project_result is None
            else dict(project_result)
        ),
        GET_TYPES_URI: {
            "return": [
                {
                    "classId": SOUND_CLASS_ID,
                    "name": "Sound",
                    "type": "WObject",
                }
            ]
        },
        GET_NAMES_URI: {"return": list(names)},
        GET_PROPERTY_INFO_URI: property_info,
    }


@pytest.mark.parametrize(
    ("argv", "message_fragment"),
    (
        (
            ["metadata", "discover", "--query", "Volume"],
            "requires exactly one",
        ),
        (
            [
                "metadata",
                "discover",
                "--class-id",
                str(SOUND_CLASS_ID),
                "--object",
                OBJECT_GUID,
                "--query",
                "Volume",
            ],
            "requires exactly one",
        ),
        (
            ["metadata", "discover", "--class-id", str(SOUND_CLASS_ID)],
            "requires 1..8 --query values",
        ),
        (
            [
                "metadata",
                "discover",
                "--class-id",
                "-1",
                "--query",
                "Volume",
            ],
            "--class-id must be a uint32 integer",
        ),
        (
            [
                "metadata",
                "discover",
                "--object-type",
                " ",
                "--query",
                "Volume",
            ],
            "--object-type must be non-empty",
        ),
        (
            [
                "metadata",
                "discover",
                "--class-id",
                str(SOUND_CLASS_ID),
                "--query",
                "Volume",
                "--query",
                "volume",
            ],
            "--query values must be distinct",
        ),
        (
            [
                "metadata",
                "discover",
                "--class-id",
                str(SOUND_CLASS_ID),
                *sum(
                    (["--query", f"query-{index}"] for index in range(9)),
                    [],
                ),
            ],
            "requires 1..8 --query values",
        ),
        (
            [
                "metadata",
                "discover",
                "--class-id",
                str(SOUND_CLASS_ID),
                "--query",
                "Volume",
                "--limit",
                "0",
            ],
            "--limit must be between 1 and 8",
        ),
        (
            [
                "metadata",
                "discover",
                "--class-id",
                str(SOUND_CLASS_ID),
                "--query",
                "Volume",
                "--limit",
                "9",
            ],
            "--limit must be between 1 and 8",
        ),
    ),
)
def test_metadata_discover_preflight_rejects_before_client_creation(
    tmp_path: Path,
    argv: list[str],
    message_fragment: str,
) -> None:
    client_created = False

    def forbidden_factory(_url: str) -> FakeClient:
        nonlocal client_created
        client_created = True
        raise AssertionError("metadata discovery preflight opened a transport")

    exit_code, payload = waapi_gateway.execute_gateway(
        argv,
        env=_gateway_env(tmp_path),
        client_factory=forbidden_factory,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error_code"] == "GatewayInputError"
    assert message_fragment in payload["message"]
    assert client_created is False


def test_metadata_discover_has_a_bounded_thirty_second_default_deadline(
    tmp_path: Path,
) -> None:
    args = waapi_gateway.build_parser().parse_args(
        [
            "metadata",
            "discover",
            "--class-id",
            str(SOUND_CLASS_ID),
            "--query",
            "Volume",
        ]
    )

    connection = waapi_gateway.resolve_connection(
        args,
        env=_gateway_env(tmp_path),
    )

    assert connection.timeout == 30.0
    assert connection.deadline.timeout == 30.0


@pytest.mark.parametrize(
    ("version", "scope_argv", "expected_scope_args", "uses_get_types"),
    (
        (
            "2021.1",
            ["--object-type", "Sound"],
            {"classId": SOUND_CLASS_ID},
            True,
        ),
        (
            "2022.1",
            ["--class-id", str(SOUND_CLASS_ID)],
            {"classId": SOUND_CLASS_ID},
            False,
        ),
        (
            "2023.1",
            ["--object", OBJECT_GUID],
            {"object": OBJECT_GUID},
            False,
        ),
        (
            "2024.1",
            ["--object-type", "Sound"],
            {"classId": SOUND_CLASS_ID},
            True,
        ),
        (
            "2025.1",
            ["--class-id", str(SOUND_CLASS_ID)],
            {"classId": SOUND_CLASS_ID},
            False,
        ),
    ),
)
def test_metadata_discover_dispatches_only_closed_reads_for_all_versions(
    tmp_path: Path,
    version: str,
    scope_argv: list[str],
    expected_scope_args: Mapping[str, Any],
    uses_get_types: bool,
) -> None:
    client = FakeClient(_metadata_responses(tmp_path, version=version))

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "discover",
            *scope_argv,
            "--query",
            "Volume",
            "--limit",
            "1",
        ],
        env=_gateway_env(tmp_path, version=version),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["ok"] is True
    assert payload["detected_version"] == version
    assert payload["operation"] == "discover"
    assert payload["metadata_authority"] == "live-waapi"
    assert list(payload)[-1] == "agent_result"
    assert payload["agent_result"]["contract"] == (
        "waapi-skill.metadata-discovery/v1"
    )
    assert payload["agent_result"]["authority"] == "live-waapi"
    assert payload["agent_result"]["candidates"][0]["name"] == "Volume"
    assert payload["agent_result"]["candidates"][0]["metadata"]["name"] == "Volume"

    call_uris = [call[0] for call in client.calls]
    expected_uris = {
        GET_INFO_URI,
        OBJECT_GET_URI,
        GET_NAMES_URI,
        GET_PROPERTY_INFO_URI,
    }
    if uses_get_types:
        expected_uris.add(GET_TYPES_URI)
    assert set(call_uris) == expected_uris
    assert call_uris.count(GET_INFO_URI) == 1
    assert call_uris.count(OBJECT_GET_URI) == 1
    assert call_uris.count(GET_NAMES_URI) == 1
    assert call_uris.count(GET_PROPERTY_INFO_URI) == 1
    assert call_uris.count(GET_TYPES_URI) == int(uses_get_types)

    names_call = next(call for call in client.calls if call[0] == GET_NAMES_URI)
    info_call = next(
        call for call in client.calls if call[0] == GET_PROPERTY_INFO_URI
    )
    assert names_call[1] == expected_scope_args
    assert info_call[1] == {**expected_scope_args, "property": "Volume"}
    assert client.disconnected is True


def test_metadata_discover_persists_and_reuses_exact_live_session_cache(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "external-state" / "waapi-skill"
    env = _gateway_env(tmp_path, state_dir=state_dir)
    first_client = FakeClient(_metadata_responses(tmp_path))
    waapi_gateway._METADATA_SESSION_CACHE.clear()

    argv = [
        "metadata",
        "discover",
        "--object-type",
        "Sound",
        "--query",
        "Volume",
        "--limit",
        "1",
    ]
    first_exit, first_payload = waapi_gateway.execute_gateway(
        argv,
        env=env,
        client_factory=lambda _url: first_client,
    )

    assert first_exit == 0, first_payload
    assert state_dir.is_dir()
    assert stat.S_IMODE(state_dir.stat().st_mode) & 0o700 == 0o700
    with pytest.raises(ValueError):
        state_dir.resolve().relative_to(waapi_gateway.SKILL_ROOT.resolve())
    durable_files = sorted((state_dir / "metadata-cache-v1").glob("*.json"))
    assert len(durable_files) == 3

    # The transaction-preview metadata wrapper must be able to reuse entries
    # seeded by the discovery command, proving both paths share one cache.
    waapi_gateway._METADATA_SESSION_CACHE.clear()
    preview_live_reads: list[
        tuple[str, Mapping[str, Any], Mapping[str, Any]]
    ] = []

    def forbidden_preview_read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        preview_live_reads.append((uri, args, options))
        raise AssertionError("preview repeated a durable discovery metadata read")

    preview_read = waapi_gateway.metadata_cached_read_call(
        forbidden_preview_read,
        connection=waapi_gateway.GatewayConnection(
            host="127.0.0.1",
            port=31337,
            version_hint="2022.1",
            evidence_dir=None,
            timeout=10.0,
            deadline=waapi_gateway.GatewayDeadline.start(10.0),
        ),
        version="2022.1",
        live_info=_live_info("2022.1"),
        project=_project_row(tmp_path),
        state_dir=state_dir,
    )
    assert preview_read(
        GET_PROPERTY_INFO_URI,
        {"classId": SOUND_CLASS_ID, "property": "Volume"},
        {},
    )["name"] == "Volume"
    assert preview_live_reads == []

    # Clear the process-global layer again so this second CLI invocation can
    # succeed only by reading all three class-scoped entries from disk.
    waapi_gateway._METADATA_SESSION_CACHE.clear()
    warm_client = FakeClient(
        {
            GET_INFO_URI: _live_info("2022.1"),
            OBJECT_GET_URI: {"return": [_project_row(tmp_path)]},
        }
    )
    warm_exit, warm_payload = waapi_gateway.execute_gateway(
        argv,
        env=env,
        client_factory=lambda _url: warm_client,
    )

    assert warm_exit == 0, warm_payload
    assert warm_payload["agent_result"] == first_payload["agent_result"]
    assert [call[0] for call in warm_client.calls] == [
        GET_INFO_URI,
        OBJECT_GET_URI,
    ]

    # Changing one exact identity fact makes every durable entry a miss.
    waapi_gateway._METADATA_SESSION_CACHE.clear()
    changed_client = FakeClient(
        _metadata_responses(tmp_path, session_id=SESSION_B)
    )
    changed_exit, changed_payload = waapi_gateway.execute_gateway(
        argv,
        env=env,
        client_factory=lambda _url: changed_client,
    )

    assert changed_exit == 0, changed_payload
    assert GET_TYPES_URI in [call[0] for call in changed_client.calls]
    assert GET_NAMES_URI in [call[0] for call in changed_client.calls]
    assert GET_PROPERTY_INFO_URI in [call[0] for call in changed_client.calls]
    waapi_gateway._METADATA_SESSION_CACHE.clear()


def test_canonical_guid_discovery_cache_is_reused_by_next_preview_process(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "guid-state"
    env = _gateway_env(tmp_path, state_dir=state_dir)
    client = FakeClient(_metadata_responses(tmp_path))
    object_guid_lower = "{abcdefab-cdef-abcd-efab-cdefabcdefab}"
    waapi_gateway._METADATA_SESSION_CACHE.clear()

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "discover",
            "--object",
            object_guid_lower,
            "--query",
            "Volume",
            "--limit",
            "1",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert len(list((state_dir / "metadata-cache-v1").glob("*.json"))) == 2
    waapi_gateway._METADATA_SESSION_CACHE.clear()
    live_reads: list[str] = []

    def forbidden_read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del args, options
        live_reads.append(uri)
        raise AssertionError("preview repeated canonical-GUID metadata")

    preview_read = waapi_gateway.metadata_cached_read_call(
        forbidden_read,
        connection=waapi_gateway.GatewayConnection(
            host="127.0.0.1",
            port=31337,
            version_hint="2022.1",
            evidence_dir=None,
            timeout=10.0,
            deadline=waapi_gateway.GatewayDeadline.start(10.0),
        ),
        version="2022.1",
        live_info=_live_info("2022.1"),
        project=_project_row(tmp_path),
        state_dir=state_dir,
    )
    assert preview_read(
        GET_PROPERTY_INFO_URI,
        {"object": object_guid_lower.upper(), "property": "Volume"},
        {},
    )["name"] == "Volume"
    assert live_reads == []
    waapi_gateway._METADATA_SESSION_CACHE.clear()


@pytest.mark.parametrize("probe_mode", ("no-project", "failed-probe"))
def test_metadata_discover_falls_back_to_uncached_live_when_project_unavailable(
    tmp_path: Path,
    probe_mode: str,
) -> None:
    state_dir = tmp_path / "must-not-be-created"
    project_result = {"return": []}
    errors: dict[str, Exception] = {}
    if probe_mode == "failed-probe":
        errors[OBJECT_GET_URI] = RuntimeError("untrusted project probe failure")
    client = FakeClient(
        _metadata_responses(tmp_path, project_result=project_result),
        errors=errors,
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "discover",
            "--class-id",
            str(SOUND_CLASS_ID),
            "--query",
            "Volume",
        ],
        env=_gateway_env(tmp_path, state_dir=state_dir),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"]["candidates"][0]["name"] == "Volume"
    assert GET_NAMES_URI in [call[0] for call in client.calls]
    assert GET_PROPERTY_INFO_URI in [call[0] for call in client.calls]
    assert not state_dir.exists()


def test_metadata_discover_never_invents_rejected_property_name(
    tmp_path: Path,
) -> None:
    live_names = (
        "IgnoreParentMaxSoundInstance",
        "MaxSoundPerInstance",
        "UseMaxSoundPerInstance",
    )
    client = FakeClient(
        _metadata_responses(tmp_path, names=live_names)
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "discover",
            "--class-id",
            str(SOUND_CLASS_ID),
            "--query",
            "OverrideMaxSoundPerInstance",
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    result = payload["agent_result"]
    surfaced_names = {
        row["name"]
        for row in result["candidates"]
    }
    surfaced_names.update(
        row["metadata"]["name"]
        for row in result["candidates"]
    )
    surfaced_names.update(
        name
        for query_result in result["query_results"]
        for name in query_result["candidate_names"]
    )
    surfaced_names.update(
        row["name"]
        for row in result["dependency_candidates"]
    )

    assert surfaced_names <= set(live_names)
    assert "OverrideMaxSoundPerInstance" not in surfaced_names
