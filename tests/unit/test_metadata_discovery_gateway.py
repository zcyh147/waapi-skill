from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.metadata_discovery import metadata_typed_value_type


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
IS_PROPERTY_ENABLED_URI = "ak.wwise.core.object.isPropertyEnabled"
GET_ATTENUATION_CURVE_URI = "ak.wwise.core.object.getAttenuationCurve"
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
        "supports": {
            "unlink": True,
            "rtpc": "Exclusive",
            "randomizer": False,
        },
        "display": {"name": name},
        "restriction": {"min": -96.3, "max": 12.0},
        "dependencies": [],
        "ui": {
            "value": {
                "min": -96.3,
                "max": 12.0,
                "decimals": 1,
                "step": 0.1,
            }
        },
        "audioEngineId": 42,
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


def test_metadata_discover_exposes_business_scope_and_meaning_not_native_tokens() -> None:
    parser = waapi_gateway.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if "metadata" in (getattr(action, "choices", None) or {})
    )
    metadata = subparsers.choices["metadata"]
    options = {
        option
        for action in metadata._actions
        for option in action.option_strings
    }

    assert {"--path-segment", "--type-name", "--exact-id", "--meaning"} <= options
    assert not {
        "--object",
        "--class-id",
        "--object-type",
        "--property",
        "--query",
        "--limit",
        "--detail",
    } & options


def test_metadata_discover_resolves_exact_type_from_business_meaning(
    tmp_path: Path,
) -> None:
    client = FakeClient(_metadata_responses(tmp_path))

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "discover",
            "--type-name",
            "Sound",
            "--meaning",
            "Volume",
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"]["candidates"][0]["name"] == "Volume"
    assert [call[0] for call in client.calls][-3:] == [
        GET_TYPES_URI,
        GET_NAMES_URI,
        GET_PROPERTY_INFO_URI,
    ]


def test_metadata_property_state_resolves_meaning_before_exact_native_read(
    tmp_path: Path,
) -> None:
    responses = _metadata_responses(tmp_path)
    responses[IS_PROPERTY_ENABLED_URI] = {"return": True}
    client = FakeClient(responses)

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "property-state",
            "--path-segment",
            "Actor-Mixer Hierarchy",
            "--path-segment",
            "Default Work Unit",
            "--path-segment",
            "Rain",
            "--meaning",
            "Volume",
            "--platform",
            "Windows",
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {
        "meaning": "Volume",
        "platform": "Windows",
        "enabled": True,
    }
    assert client.calls[-1] == (
        IS_PROPERTY_ENABLED_URI,
        {
            "object": (
                r"\Actor-Mixer Hierarchy\Default Work Unit\Rain"
            ),
            "platform": "Windows",
            "property": "Volume",
        },
        {},
    )


def test_metadata_attenuation_compiles_business_curve_role(
    tmp_path: Path,
) -> None:
    responses = _metadata_responses(tmp_path)
    responses[GET_ATTENUATION_CURVE_URI] = {
        "curveType": "VolumeDryUsage",
        "use": "Custom",
        "points": [],
    }
    client = FakeClient(responses)

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "attenuation",
            "--path-segment",
            "Attenuations",
            "--path-segment",
            "Default Work Unit",
            "--path-segment",
            "Outdoor",
            "--curve-role",
            "volume-dry",
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {
        "curve_role": "volume-dry",
        "use": "Custom",
        "points": [],
    }
    assert client.calls[-1] == (
        GET_ATTENUATION_CURVE_URI,
        {
            "object": r"\Attenuations\Default Work Unit\Outdoor",
            "curveType": "VolumeDryUsage",
        },
        {},
    )


@pytest.mark.parametrize(
    ("argv", "message_fragment"),
    (
        (
            ["metadata", "discover", "--meaning", "Volume"],
            "requires exactly one --path-segment, --type-name, or --exact-id scope",
        ),
        (
            ["metadata", "discover", "--type-name", "Sound"],
            "requires 1..8 --meaning values",
        ),
        (
            [
                "metadata",
                "discover",
                "--type-name",
                " ",
                "--meaning",
                "Volume",
            ],
            "--type-name must be non-empty",
        ),
        (
            [
                "metadata",
                "discover",
                "--type-name",
                "Sound",
                "--meaning",
                "Volume",
                "--meaning",
                "volume",
            ],
            "--meaning values must be distinct",
        ),
        (
            [
                "metadata",
                "discover",
                "--type-name",
                "Sound",
                *sum(
                    (["--meaning", f"query-{index}"] for index in range(9)),
                    [],
                ),
            ],
            "requires 1..8 --meaning values",
        ),
        (
            [
                "metadata",
                "types",
                "--type-name",
                "Sound",
            ],
            "metadata types accepts no business input",
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
            "--type-name",
            "Sound",
            "--meaning",
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
    "version",
    ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
)
def test_metadata_discover_dispatches_only_closed_reads_for_all_versions(
    tmp_path: Path,
    version: str,
) -> None:
    client = FakeClient(_metadata_responses(tmp_path, version=version))

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "discover",
            "--type-name",
            "Sound",
            "--meaning",
            "Volume",
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
        "waapi-skill.metadata-discovery/v2"
    )
    assert payload["agent_result"]["authority"] == "live-waapi"
    assert payload["agent_result"]["result_detail"] == "compact"
    assert payload["agent_result"]["candidates"][0]["name"] == "Volume"
    assert payload["agent_result"]["candidates"][0]["metadata"]["name"] == "Volume"
    assert payload["agent_result"]["candidates"][0]["metadata"][
        "typed_value_type"
    ] == "number"
    assert "supports" not in payload["agent_result"]["candidates"][0]["metadata"]
    assert "match_evidence" not in payload["agent_result"]["candidates"][0]

    call_uris = [call[0] for call in client.calls]
    expected_uris = {
        GET_INFO_URI,
        OBJECT_GET_URI,
        GET_NAMES_URI,
        GET_PROPERTY_INFO_URI,
    }
    expected_uris.add(GET_TYPES_URI)
    assert set(call_uris) == expected_uris
    assert call_uris.count(GET_INFO_URI) == 1
    assert call_uris.count(OBJECT_GET_URI) == 1
    assert call_uris.count(GET_NAMES_URI) == 1
    assert call_uris.count(GET_PROPERTY_INFO_URI) == 1
    assert call_uris.count(GET_TYPES_URI) == 1

    names_call = next(call for call in client.calls if call[0] == GET_NAMES_URI)
    info_call = next(
        call for call in client.calls if call[0] == GET_PROPERTY_INFO_URI
    )
    assert names_call[1] == {"classId": SOUND_CLASS_ID}
    assert info_call[1] == {"classId": SOUND_CLASS_ID, "property": "Volume"}
    assert client.disconnected is True


@pytest.mark.parametrize(
    ("metadata_type", "typed_value_type"),
    (
        ("bool", "boolean"),
        ("Boolean", "boolean"),
        ("int16", "integer"),
        ("UInt64", "integer"),
        ("Real32", "number"),
        ("real64", "number"),
        ("String", "string"),
        ("Object", None),
    ),
)
def test_live_metadata_type_discloses_canonical_typed_action_scalar(
    metadata_type: str,
    typed_value_type: str | None,
) -> None:
    assert metadata_typed_value_type(metadata_type) == typed_value_type



def _compact_five_query_gateway_payload(
    tmp_path: Path,
) -> dict[str, Any]:
    queries = ("loop", "limit", "output", "pitch", "stream")
    names = tuple(
        f"{query.title()}Setting{index}"
        for query in queries
        for index in range(4)
    )
    gate_by_query = {
        query: f"ActivationGate{index}"
        for index, query in enumerate(queries)
    }
    all_names = (*names, *gate_by_query.values())
    responses = _metadata_responses(tmp_path, names=all_names)

    def property_info(
        args: Mapping[str, Any] | None,
        _options: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        assert isinstance(args, Mapping)
        name = args.get("property")
        assert isinstance(name, str)
        if name in gate_by_query.values():
            return {
                "name": name,
                "type": "bool",
                "default": False,
                "display": {
                    "name": name,
                    "index": 1700,
                    "group": "Audio/Advanced Settings/Activation",
                },
                "restriction": {},
                "dependencies": [],
                "ui": {"value": {"min": 0.0, "max": 0.0}},
                "audioEngineId": 0xFFFFFFFF,
            }
        query = next(
            item for item in queries if name.startswith(item.title())
        )
        index = int(name[-1])
        return {
            **_property_info(name),
            "display": {
                "name": f"{query.title()} setting {index}",
                "index": 1500 + index,
                "group": (
                    "Audio/Advanced Settings/Compound Metadata "
                    f"Resolution/{query.title()}"
                ),
            },
            "restriction": {
                "type": "range",
                "min": -200.0,
                "max": 200.0,
            },
            "dependencies": (
                [
                    {
                        "type": "override",
                        "action": "Enable",
                        "context": "Self",
                        "property": gate_by_query[query],
                    }
                ]
                if index == 0
                else []
            ),
        }

    responses[GET_PROPERTY_INFO_URI] = property_info
    client = FakeClient(responses)
    query_argv = [
        item
        for query in queries
        for item in ("--meaning", query)
    ]

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "discover",
            "--type-name",
            "Sound",
            *query_argv,
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    return payload


def test_compact_five_query_complete_gateway_stdout_stays_below_32_kib(
    tmp_path: Path,
) -> None:
    payload = _compact_five_query_gateway_payload(tmp_path)

    assert payload["agent_result"]["candidate_count"] == 20
    assert payload["agent_result"]["mutation_authoring_policy"] == {
        "action_field_selection": "explicit_user_settings_only",
        "dependency_candidates": {
            "required_by_only": "omit_from_action",
            "matched_queries_nonempty": (
                "still_requires_explicit_user_selection_but_may_copy_name_and_type"
            ),
            "independently_requested_exact_token": "may_copy_name_and_type",
            "activation_owner": "gateway_draft_check_and_preview",
        },
    }
    assert len(payload["agent_result"]["dependency_candidates"]) == 5
    assert (
        waapi_gateway.gateway_json_document_size(payload["agent_result"])
        <= 28 * 1024
    )
    assert (
        waapi_gateway.gateway_json_document_size(payload)
        <= waapi_gateway.MAX_METADATA_DISCOVERY_GATEWAY_RESULT_BYTES
    )


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
        "--type-name",
        "Sound",
        "--meaning",
        "Volume",
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


def test_exact_id_discovery_cache_is_reused_by_next_preview_process(
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
            "--exact-id",
            object_guid_lower,
            "--meaning",
            "Volume",
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
            "--type-name",
            "Sound",
            "--meaning",
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
            "--type-name",
            "Sound",
            "--meaning",
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
