from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.metadata_discovery import metadata_typed_value_type
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


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
                "wwise_version": version,
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    env = {
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
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

    assert {
        "--path-segment",
        "--kind",
        "--custom-kind",
        "--exact-id",
        "--meaning",
    } <= options
    assert "--type-name" not in options
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
            "--kind",
            "all-sounds",
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


def test_metadata_discover_custom_kind_is_live_bound_before_field_scope(
    tmp_path: Path,
) -> None:
    client = FakeClient(_metadata_responses(tmp_path))

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "discover",
            "--custom-kind",
            "Sound",
            "--meaning",
            "Volume",
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"]["scope"]["requested"] == "Sound"
    assert [call[0] for call in client.calls].count(GET_TYPES_URI) == 2


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_metadata_property_state_resolves_meaning_before_exact_native_read(
    tmp_path: Path,
    version: str,
) -> None:
    responses = _metadata_responses(tmp_path, version=version)
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
        env=_gateway_env(tmp_path, version=version),
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


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("exact_id_scope", (False, True))
@pytest.mark.parametrize(
    ("curve_role", "native_curve_type"),
    (
        ("volume-dry", "VolumeDryUsage"),
        ("game-defined-aux-send-volume", "VolumeWetGameUsage"),
        ("user-defined-aux-send-volume", "VolumeWetUserUsage"),
        ("low-pass-filter", "LowPassFilterUsage"),
        ("high-pass-filter", "HighPassFilterUsage"),
        ("spread", "SpreadUsage"),
        ("focus", "FocusUsage"),
    ),
)
def test_metadata_attenuation_compiles_business_curve_role(
    tmp_path: Path,
    version: str,
    exact_id_scope: bool,
    curve_role: str,
    native_curve_type: str,
) -> None:
    schema_exit, schema = waapi_gateway.execute_gateway(
        ["request-schema", GET_ATTENUATION_CURVE_URI],
        env=_gateway_env(tmp_path, version=version),
        client_factory=lambda _url: pytest.fail("schema discovery must be offline"),
    )
    assert schema_exit == 0, schema
    forms = schema["continuation"]["input_forms"]
    assert curve_role in forms["curve_role"]["choices"]
    responses = _metadata_responses(tmp_path, version=version)
    responses[GET_ATTENUATION_CURVE_URI] = {
        "curveType": native_curve_type,
        "use": "Custom",
        "points": [],
    }
    client = FakeClient(responses)
    scope_argv = (
        [forms["object"]["exact_id"]["arguments"][0], OBJECT_GUID]
        if exact_id_scope
        else [
            *[token for name in ("Attenuations", "Default Work Unit", "Outdoor")
              for token in (forms["object"]["path_segments"]["arguments"][0], name)],
            forms["platform"]["arguments"][0], "Windows",
        ]
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "attenuation",
            *scope_argv,
            forms["curve_role"]["arguments"][0],
            curve_role,
        ],
        env=_gateway_env(tmp_path, version=version),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {
        "curve_role": curve_role,
        "use": "Custom",
        "points": [],
    }
    assert client.calls[-1] == (
        GET_ATTENUATION_CURVE_URI,
        {
            "object": (
                OBJECT_GUID
                if exact_id_scope
                else r"\Attenuations\Default Work Unit\Outdoor"
            ),
            "curveType": native_curve_type,
            **({} if exact_id_scope else {"platform": "Windows"}),
        },
        {},
    )


@pytest.mark.parametrize(
    ("operation_argv", "invalid_platform"),
    (
        (("property-state", "--meaning", "Volume"), " Windows "),
        (("property-state", "--meaning", "Volume"), "Windows\x00"),
        (("attenuation", "--curve-role", "volume-dry"), "\nWindows"),
        (("attenuation", "--curve-role", "volume-dry"), "W" * 257),
    ),
)
def test_metadata_business_platform_rejects_hostile_text_before_connecting(
    tmp_path: Path,
    operation_argv: tuple[str, ...],
    invalid_platform: str,
) -> None:
    connected = False

    def client_factory(_url: str) -> FakeClient:
        nonlocal connected
        connected = True
        raise AssertionError("invalid business platform must fail before WAAPI")

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            operation_argv[0],
            "--path-segment",
            "Actor-Mixer Hierarchy",
            "--path-segment",
            "Default Work Unit",
            "--path-segment",
            "Rain",
            *operation_argv[1:],
            "--platform",
            invalid_platform,
        ],
        env=_gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert connected is False
    assert payload["error_code"] == "GatewayInputError"
    assert "bounded, trimmed, control-free --platform" in payload["message"]


def test_metadata_property_state_never_dispatches_a_reference_as_property(
    tmp_path: Path,
) -> None:
    responses = _metadata_responses(tmp_path, names=("OutputBus",))
    responses[GET_PROPERTY_INFO_URI] = {
        "name": "OutputBus",
        "type": "ObjectReference",
        "default": None,
        "supports": {},
        "display": {"name": "Output Bus"},
        "restriction": {"type": "reference"},
        "dependencies": [],
    }
    client = FakeClient(responses)

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "property-state",
            "--exact-id",
            OBJECT_GUID,
            "--meaning",
            "Output Bus",
            "--platform",
            "Windows",
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["status"] == "needs_clarification"
    assert payload["agent_result"]["candidates"] == [
        {"field": "OutputBus", "kind": "reference"}
    ]
    assert all(call[0] != IS_PROPERTY_ENABLED_URI for call in client.calls)


@pytest.mark.parametrize(
    "invalid_id",
    (
        "Sound",
        r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
        "{NOT-A-GUID}",
        "  {22222222-2222-2222-2222-222222222222}",
    ),
)
def test_metadata_exact_id_rejects_noncanonical_identity_before_connecting(
    tmp_path: Path,
    invalid_id: str,
) -> None:
    connected = False

    def client_factory(_url: str) -> FakeClient:
        nonlocal connected
        connected = True
        raise AssertionError("invalid metadata identity must fail before WAAPI")

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "metadata",
            "attenuation",
            "--exact-id",
            invalid_id,
            "--curve-role",
            "volume-dry",
        ],
        env=_gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert connected is False
    assert payload["error_code"] == "GatewayInputError"
    assert "canonical GUID" in payload["message"]


@pytest.mark.parametrize(
    ("argv", "message_fragment"),
    (
        (
            ["metadata", "discover", "--meaning", "Volume"],
            "requires exactly one --path-segment, --kind, --custom-kind, or --exact-id scope",
        ),
        (
            ["metadata", "discover", "--kind", "all-sounds"],
            "requires 1..8 --meaning values",
        ),
        (
            [
                "metadata",
                "discover",
                "--custom-kind",
                " ",
                "--meaning",
                "Volume",
            ],
            "--custom-kind must be one bounded",
        ),
        (
            [
                "metadata",
                "discover",
                "--kind",
                "all-sounds",
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
                "--kind",
                "all-sounds",
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
                "--kind",
                "all-sounds",
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
            "--kind",
            "all-sounds",
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


def test_draft_field_discovery_uses_the_live_metadata_deadline(
    tmp_path: Path,
) -> None:
    args = waapi_gateway.build_parser().parse_args(
        [
            "draft-discover-fields",
            "od1-" + ("0" * 32),
            "--task-authority",
            "da1-" + ("0" * 40),
            "--expected-revision",
            "1",
            "--semantic-kind",
            "sound-sfx",
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
    "command_args",
    (
        (
            "draft-discover-fields",
            "--semantic-kind",
            "sound-sfx",
            "--meaning",
            "Volume",
        ),
        (
            "draft-discover-types",
            "--meaning",
            "source plugin",
            "--role",
            "source",
        ),
    ),
)
def test_other_draft_metadata_commands_share_the_discovery_deadline(
    tmp_path: Path,
    command_args: tuple[str, ...],
) -> None:
    args = waapi_gateway.build_parser().parse_args(
        [
            command_args[0],
            "od1-" + ("0" * 32),
            "--task-authority",
            "da1-" + ("0" * 40),
            "--expected-revision",
            "1",
            *command_args[1:],
        ]
    )

    connection = waapi_gateway.resolve_connection(
        args,
        env=_gateway_env(tmp_path),
    )

    assert connection.timeout == 30.0
    assert connection.deadline.timeout == 30.0


def test_explicit_draft_field_discovery_deadline_takes_precedence(
    tmp_path: Path,
) -> None:
    args = waapi_gateway.build_parser().parse_args(
        [
            "--timeout",
            "5",
            "draft-discover-fields",
            "od1-" + ("0" * 32),
            "--task-authority",
            "da1-" + ("0" * 40),
            "--expected-revision",
            "1",
            "--semantic-kind",
            "sound-sfx",
            "--meaning",
            "Volume",
        ]
    )

    connection = waapi_gateway.resolve_connection(
        args,
        env=_gateway_env(tmp_path),
    )

    assert connection.timeout == 5.0
    assert connection.deadline.timeout == 5.0


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
            "--kind",
            "all-sounds",
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
            "--kind",
            "all-sounds",
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
        "--kind",
        "all-sounds",
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
            "--kind",
            "all-sounds",
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
            "--kind",
            "all-sounds",
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


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_attenuation_read_schema_discloses_complete_business_inputs(
    tmp_path: Path, version: str,
) -> None:
    exit_code, schema = waapi_gateway.execute_gateway(
        ["request-schema", GET_ATTENUATION_CURVE_URI], env=_gateway_env(tmp_path, version=version),
        client_factory=lambda _url: pytest.fail("request schema must be offline"),
    )
    assert exit_code == 0, schema
    command = schema["continuation"]
    assert command == schema["commands"][0]
    assert command["subcommand"] == "metadata" and command["arguments"] == ["attenuation"]
    assert command["required_inputs"] == ["object", "curve_role"]
    forms = command["input_forms"]
    assert forms["object"]["exactly_one_of"] == ["exact_id", "path_segments"]
    assert forms["object"]["exact_id"]["arguments"] == ["--exact-id", "<canonical-object-guid>"]
    assert forms["object"]["exact_id"]["format"] == "canonical GUID with braces from a bounded object read"
    assert forms["object"]["path_segments"]["arguments"] == ["--path-segment", "<literal-hierarchy-name>"]
    assert forms["object"]["path_segments"]["repeat"] is True
    assert forms["object"]["path_segments"]["minimum_items"] == 1
    assert forms["object"]["path_segments"]["maximum_items"] == 64
    assert forms["object"]["path_segments"]["maximum_item_utf8_bytes"] == 512
    assert forms["object"]["path_segments"]["maximum_path_utf8_bytes"] == 8192
    assert forms["curve_role"] == {"arguments": ["--curve-role", "<curve-role>"], "choices": [
        "volume-dry", "game-defined-aux-send-volume", "user-defined-aux-send-volume",
        "low-pass-filter", "high-pass-filter", "spread", "focus",
    ]}
    assert command["optional_inputs"] == ["platform"]
    assert forms["platform"]["arguments"] == ["--platform", "<exact-platform-name>"]
    assert forms["platform"]["maximum_characters"] == 256
    assert forms["platform"]["trimmed"] is True and forms["platform"]["control_free"] is True
    assert command["command_templates"] == [
        ["metadata", "attenuation", "--exact-id", "<canonical-object-guid>", "--curve-role", "<curve-role>"],
        ["metadata", "attenuation", "--path-segment", "<literal-hierarchy-name>", "--curve-role", "<curve-role>"],
    ]
    assert command["template_instruction"].startswith("Static input templates")
    assert schema["native_request_fields_disclosed"] is False
    assert "curveType" not in json.dumps(schema) and "VolumeDryUsage" not in json.dumps(schema)


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("inputs", [
    ["--curve-role", "volume-dry"],
    ["--exact-id", OBJECT_GUID],
    ["--exact-id", OBJECT_GUID.strip("{}"), "--curve-role", "volume-dry"],
    ["--exact-id", OBJECT_GUID, "--curve-role", "volume-dry", "--platform", ""],
    ["--exact-id", OBJECT_GUID, "--curve-role", "volume-dry", "--platform", " Windows "],
    ["--exact-id", OBJECT_GUID, "--curve-role", "volume-dry", "--platform", "Windows\n"],
    ["--exact-id", OBJECT_GUID, "--curve-role", "volume-dry", "--platform", "W" * 257],
    ["--path-segment", r"Attenuations\Outdoor", "--curve-role", "volume-dry"],
    ["--path-segment", " Outdoor ", "--curve-role", "volume-dry"],
    ["--path-segment", "N" * 513, "--curve-role", "volume-dry"],
    [*[token for _ in range(65) for token in ("--path-segment", "Level")], "--curve-role", "volume-dry"],
    [*[token for _ in range(17) for token in ("--path-segment", "N" * 512)], "--curve-role", "volume-dry"],
])
def test_disclosed_attenuation_inputs_fail_closed_before_connecting(
    tmp_path: Path, version: str, inputs: list[str],
) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["metadata", "attenuation", *inputs], env=_gateway_env(tmp_path, version=version),
        client_factory=lambda _url: pytest.fail("invalid disclosed input must not connect"),
    )
    assert exit_code == 2, payload
    assert payload["ok"] is False


@pytest.mark.parametrize("version", ["2020.1", "2026.1"])
def test_attenuation_read_schema_rejects_unavailable_version_without_connecting(
    tmp_path: Path, version: str,
) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["request-schema", GET_ATTENUATION_CURVE_URI], env=_gateway_env(tmp_path, version=version),
        client_factory=lambda _url: pytest.fail("unsupported version must not connect"),
    )
    assert exit_code == 2, payload
    assert payload["ok"] is False
    assert "continuation" not in payload


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("inputs", [
    ["--exact-id", OBJECT_GUID, "--path-segment", "Outdoor", "--curve-role", "volume-dry"],
    ["--exact-id", OBJECT_GUID, "--curve-role", "arbitrary-curve"],
    ["--exact-id", OBJECT_GUID, "--curve-role", "volume-dry", "--curve-type", "VolumeDryUsage"],
])
def test_attenuation_cli_parser_rejects_ambiguous_unknown_and_native_inputs(
    tmp_path: Path, version: str, inputs: list[str],
) -> None:
    with pytest.raises(SystemExit) as rejected:
        waapi_gateway.execute_gateway(
            ["metadata", "attenuation", *inputs], env=_gateway_env(tmp_path, version=version),
            client_factory=lambda _url: pytest.fail("parser rejection must precede connection"),
        )
    assert rejected.value.code == 2

@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("scope", [("--exact-id", OBJECT_GUID), ("--kind", "sound")])
def test_metadata_lists_all_fields_then_reads_exact_selection(tmp_path: Path, version: str, scope: tuple[str, str]) -> None:
    names = tuple(f"Parameter{i:03}" for i in range(45))
    env = _gateway_env(tmp_path, version=version)
    def run(*argv: str):
        client = FakeClient(_metadata_responses(tmp_path, version=version, names=names))
        return waapi_gateway.execute_gateway(
            ["metadata", *argv, *scope], env=env,
            client_factory=lambda _url: client,
        )
    code, first = run("list", "--page-size", "20")
    assert code == 0, first
    page = first["agent_result"]
    assert page["total_count"] == 45
    assert page["remaining_count"] == 25
    rows = list(page["fields"])
    while page["next_page"]:
        code, result = run("list", "--page-size", "20", "--page", page["next_page"])
        assert code == 0, result
        page = result["agent_result"]
        rows.extend(page["fields"])
    assert [row["name"] for row in rows] == list(names)
    assert page["complete"] is True
    code, detail = run("detail", "--selection", rows[0]["selection"])
    assert code == 0, detail
    assert detail["agent_result"]["metadata"]["name"] == "Parameter000"
    assert detail["agent_result"]["metadata"]["unit"] == {"status": "unknown", "value": None}

@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_exact_metadata_meaning_ignores_bulky_near_matches(tmp_path: Path, version: str) -> None:
    responses = _metadata_responses(tmp_path, version=version, names=("Volume", "VolumeExtra"))
    responses[GET_PROPERTY_INFO_URI] = lambda args, options: (
        {"name": args["property"], "type": "Real32", "display": {"name": "x" * 39720}}
        if args["property"] == "VolumeExtra" else _property_info("Volume")
    )
    client = FakeClient(responses)
    code, payload = waapi_gateway.execute_gateway(
        ["metadata", "discover", "--exact-id", OBJECT_GUID, "--meaning", "Volume"],
        env=_gateway_env(tmp_path, version=version), client_factory=lambda _url: client,
    )
    assert code == 0, payload
    assert [row["name"] for row in payload["agent_result"]["candidates"]] == ["Volume"]
