from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_gateway_debug_read_tests",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


class FakeClient:
    def __init__(
        self,
        responses: Mapping[str, Any],
        *,
        errors: Mapping[str, BaseException] | None = None,
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
        return self.responses[uri]

    def disconnect(self) -> None:
        self.disconnected = True


class WaapiRequestFailed(Exception):
    def __init__(self, uri: str, kwargs: Mapping[str, Any] | None = None) -> None:
        super().__init__("untrusted rendered application error")
        self.uri = uri
        self.kwargs = kwargs


def _live_info(version: str) -> dict[str, Any]:
    year, major = (int(item) for item in version.split("."))
    return {
        "displayName": "Wwise",
        "isCommandLine": False,
        "version": {
            "year": year,
            "major": major,
            "minor": 1,
            "build": 1,
            "displayName": f"v{version}.1",
        },
    }


def _gateway_env(tmp_path: Path, version: str) -> dict[str, str]:
    config_path = tmp_path / "config.json"
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
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": version,
        "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence"),
    }


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_debug_wal_tree_dispatches_one_closed_bounded_request(
    tmp_path: Path,
    version: str,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info(version),
            "ak.wwise.debug.getWalTree": {
                "return": {
                    "nodes": {
                        "z": {"id": 3, "name": "Z", "type": "Sound"},
                        "a": {"id": 1, "name": "A", "type": "Bus"},
                    }
                }
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["debug-wal-tree", "--max-nodes", "1"],
        env=_gateway_env(tmp_path, version),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    result = payload['agent_result']
    assert result['observation_complete'] is True
    assert json.loads(''.join(row['value'] for row in result['native_result_fragments'])) == client.responses['ak.wwise.debug.getWalTree']
    assert list(payload)[-1] == "agent_result"
    assert client.calls == [
        ("ak.wwise.core.getInfo", None, None),
        ("ak.wwise.debug.getWalTree", {}, {}),
    ]
    assert client.disconnected is True


def test_debug_parser_exposes_only_business_boundaries() -> None:
    parser = waapi_gateway.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if "debug-wal-tree" in (getattr(action, "choices", None) or {})
    )
    wal = subparsers.choices["debug-wal-tree"]
    validate = subparsers.choices["debug-validate-call"]
    wal_options = {
        option for action in wal._actions for option in action.option_strings
    }
    validate_options = {
        option for action in validate._actions for option in action.option_strings
    }

    assert "--max-nodes" in wal_options
    assert "--take" not in wal_options
    assert "--artifact-file" in validate_options
    assert not {
        "--schema-digest",
        "--set",
        "--map-put",
        "--args-json",
        "--options-json",
        "--result-json",
    } & validate_options


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
def test_debug_validate_call_validates_target_without_executing_it(
    tmp_path: Path,
    version: str,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info(version),
            "ak.wwise.debug.validateCall": {},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["debug-validate-call", "ak.wwise.core.getProjectInfo"],
        env=_gateway_env(tmp_path, version),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {
        "validated_api": "ak.wwise.core.getProjectInfo",
        "supplied_sections": [],
        "accepted_by_wwise": True,
    }
    assert client.calls == [
        ("ak.wwise.core.getInfo", None, None),
        (
            "ak.wwise.debug.validateCall",
            {"id": "ak.wwise.core.getProjectInfo"},
            {},
        ),
    ]


@pytest.mark.parametrize(
    ("version", "command", "uri"),
    (
        ("2023.1", ["debug-wal-tree", "--max-nodes", "1"], "ak.wwise.debug.getWalTree"),
        (
            "2025.1",
            ["debug-validate-call", "ak.wwise.core.getProjectInfo"],
            "ak.wwise.debug.validateCall",
        ),
    ),
)
def test_debug_reads_report_release_build_boundary(
    tmp_path: Path,
    version: str,
    command: list[str],
    uri: str,
) -> None:
    client = FakeClient(
        {"ak.wwise.core.getInfo": _live_info(version)},
        errors={
            uri: WaapiRequestFailed(
                "ak.wwise.invalid_procedure_uri",
                {
                    "details": {"procedureUri": uri},
                    "message": "The procedure URI is unknown.",
                },
            )
        },
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        command,
        env=_gateway_env(tmp_path, version),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["ok"] is True
    assert payload["status"] == "unsupported_boundary"
    assert payload["error_code"] == "DEBUG_BUILD_REQUIRED"
    assert payload["executed"] is False
    assert payload["call"]["waapi_error_uri"] == "ak.wwise.invalid_procedure_uri"
    assert payload["agent_result"] is None
    assert list(payload)[-1] == "agent_result"
    assert client.calls[-1][0] == uri
    assert client.disconnected is True


def test_debug_validate_call_preserves_user_owned_exact_artifact(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "call.json"
    artifact.write_text(
        json.dumps(
            {
                "args": {"from": {"id": ["{11111111-1111-1111-1111-111111111111}"]}},
                "options": {"return": ["id", "name"]},
                "result": {"return": []},
            }
        ),
        encoding="utf-8",
    )
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2025.1"),
            "ak.wwise.debug.validateCall": {},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "debug-validate-call",
            "ak.wwise.core.object.get",
            "--artifact-file",
            str(artifact),
        ],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["artifact"]["authority"] == "user_owned_exact_artifact"
    assert payload["agent_result"]["supplied_sections"] == [
        "args",
        "options",
        "result",
    ]
    assert client.calls[-1] == (
        "ak.wwise.debug.validateCall",
        {
            "id": "ak.wwise.core.object.get",
            "args": {"from": {"id": ["{11111111-1111-1111-1111-111111111111}"]}},
            "options": {"return": ["id", "name"]},
            "result": {"return": []},
        },
        {},
    )


def test_debug_validate_call_rejects_non_object_artifact_before_connect(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "call.json"
    artifact.write_text('{"args": []}', encoding="utf-8")
    connected = False

    def factory(url: str) -> FakeClient:
        nonlocal connected
        connected = True
        raise AssertionError("invalid exact artifact must fail before connect")

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "debug-validate-call",
            "ak.wwise.core.object.get",
            "--artifact-file",
            str(artifact),
        ],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert connected is False


@pytest.mark.parametrize('version', ('2023.1', '2024.1', '2025.1'))
@pytest.mark.parametrize('console', (False, True))
def test_wal_complete_map_above_old_limit_roundtrips_through_public_continuations(tmp_path: Path, version: str, console: bool) -> None:
    raw = {'return': {'nodes': {f'node-{i:04}': {'id': i, 'name': f'Node {i}', 'type': 'Sound',
            'extension': {'ordered': [2, 1], 'empty': {}}} for i in reversed(range(257))},
            'native_extension': 'preserved'}}
    info = {**_live_info(version), 'isCommandLine': console, 'sessionId': '{11111111-1111-1111-1111-111111111111}', 'processId': 42}
    env = _gateway_env(tmp_path, version)
    argv = ['debug-wal-tree', '--max-nodes', '1']
    fragments = []
    for _ in range(200):
        client = FakeClient({'ak.wwise.core.getInfo': info, 'ak.wwise.debug.getWalTree': raw})
        code, payload = waapi_gateway.execute_gateway(argv, env=env, client_factory=lambda url: client)
        assert code == 0, json.dumps(payload, ensure_ascii=False)
        result = payload['agent_result']
        assert list(payload)[-1] == 'agent_result'
        assert len(json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')) < 24 * 1024
        assert client.calls == [('ak.wwise.core.getInfo', None, None), ('ak.wwise.debug.getWalTree', {}, {})]
        fragments.extend(result['native_result_fragments'])
        if result['observation_complete']:
            break
        argv = result['next_command']['gateway_argv']
    else:
        pytest.fail('WAL continuation never completed')
    assert json.loads(''.join(row['value'] for row in fragments)) == raw
    assert [row['offset'] for row in fragments] == list(range(0, len(''.join(row['value'] for row in fragments)), 1024))


def _wal_read(tmp_path: Path, *, raw: Any, info: dict[str, Any] | None = None,
              argv: list[str] | None = None, version: str = '2025.1'):
    client = FakeClient({'ak.wwise.core.getInfo': info or _live_info(version),
                         'ak.wwise.debug.getWalTree': raw})
    code, payload = waapi_gateway.execute_gateway(argv or ['debug-wal-tree'],
        env=_gateway_env(tmp_path, version), client_factory=lambda url: client)
    return code, payload, client


def _large_wal() -> dict[str, Any]:
    return {'return': {'nodes': {'one': {'id': 1, 'name': 'n' * 20000, 'type': 'Sound'}}}}


@pytest.mark.parametrize('change', ('result', 'build', 'session_added', 'session_removed', 'session_null', 'session_null_removed', 'process', 'host', 'page_size'))
def test_wal_continuation_rejects_changed_whole_result_or_live_binding(tmp_path: Path, change: str) -> None:
    raw, info = _large_wal(), _live_info('2025.1')
    if change in {'session_removed', 'session_null_removed'}:
        info['sessionId'] = None if change == 'session_null_removed' else '{11111111-1111-1111-1111-111111111111}'
    code, first, _ = _wal_read(tmp_path, raw=raw, info=info, argv=['debug-wal-tree', '--max-nodes', '1'])
    assert code == 0, first
    argv = first['agent_result']['next_command']['gateway_argv']
    if change == 'result':
        raw['return']['nodes']['one']['name'] += 'changed outside first fragment'
    elif change == 'build':
        info['version']['build'] += 1
    elif change == 'session_added':
        info['sessionId'] = '{11111111-1111-1111-1111-111111111111}'
    elif change in {'session_removed', 'session_null_removed'}:
        del info['sessionId']
    elif change == 'session_null':
        info['sessionId'] = None
    elif change == 'process':
        info['processId'] = 22
    elif change == 'host':
        info['isCommandLine'] = True
    else:
        argv[argv.index('--max-nodes') + 1] = '2'
    code, failed, client = _wal_read(tmp_path, raw=raw, info=info, argv=argv)
    assert code == 2, failed
    assert failed['error_code'] == 'WAL_CONTINUATION_CHANGED'
    assert len(client.calls) == (2 if change == 'result' else 1)
    assert client.disconnected


def test_wal_identical_observation_without_optional_session_ids_continues_with_stable_order(tmp_path: Path) -> None:
    raw = _large_wal()
    raw['return']['nodes']['two'] = {'id': 1, 'name': 'same numeric ID is not a native uniqueness rule', 'type': 'Bus'}
    code, first, _ = _wal_read(tmp_path, raw=raw, argv=['debug-wal-tree', '--max-nodes', '1'])
    assert code == 0, first
    reordered = {'return': {'nodes': dict(reversed(list(raw['return']['nodes'].items())))}}
    code, second, _ = _wal_read(tmp_path, raw=reordered, argv=first['agent_result']['next_command']['gateway_argv'])
    assert code == 0, second
    assert second['agent_result']['page']['native_result_sha256'] == first['agent_result']['page']['native_result_sha256']
    assert second['agent_result']['page']['offset'] == 1


@pytest.mark.parametrize('version', ('2021.1', '2022.1'))
@pytest.mark.parametrize('console', (False, True))
def test_wal_unreflected_lanes_remain_explicit_without_native_dispatch(tmp_path: Path, version: str, console: bool) -> None:
    code, payload, client = _wal_read(tmp_path, raw={}, info={**_live_info(version), 'isCommandLine': console}, version=version)
    assert code == 2, payload
    assert payload['error_code'] == 'UNSUPPORTED_BY_SKILL_INTERFACE'
    assert [call[0] for call in client.calls] == ['ak.wwise.core.getInfo']


@pytest.mark.parametrize('node_id', (-1, 1.5, 1 << 32))
def test_wal_preserves_native_number_ids_without_invented_uint32_restriction(tmp_path: Path, node_id: int | float) -> None:
    raw = {'return': {'nodes': {'key': {'id': node_id, 'name': 'Native number', 'type': 'Sound'}}}}
    code, payload, _ = _wal_read(tmp_path, raw=raw)
    assert code == 0, payload
    assert payload['agent_result']['native_result'] == raw


@pytest.mark.parametrize('raw', ({'return': {'nodes': {'bad': {'id': True, 'name': 'Bad', 'type': 'Sound'}}}},
    {'return': {'nodes': {'bad': {'id': 1, 'name': 'No type'}}}}, {'return': {'nodes': []}}, {'return': {'nodes': None}}, {'return': []}))
def test_wal_malformed_native_nodes_fail_without_lossy_success(tmp_path: Path, raw: Any) -> None:
    code, payload, client = _wal_read(tmp_path, raw=raw)
    assert code == 2, payload
    assert payload.get('agent_result') is None
    assert len(client.calls) == 2


def test_wal_transport_limit_stays_explicit(tmp_path: Path) -> None:
    raw = _large_wal()
    raw['return']['nodes']['one']['name'] = 'x' * (256 * 1024)
    code, payload, _ = _wal_read(tmp_path, raw=raw)
    assert code == 2, payload
    assert payload['call']['error_code'] == 'RESULT_TOO_LARGE'
    assert payload.get('agent_result') is None


def test_wal_malformed_or_expired_page_rejected_before_connection(tmp_path: Path) -> None:
    import time
    from wwise_waapi.canonical import canonical_sha256
    unsigned = f'wal1.{int(time.time()) - 901}.1.' + '.'.join(['a' * 64] * 3)
    token = unsigned + '.' + canonical_sha256(unsigned)
    def no_connection(url):
        pytest.fail('expired/malformed WAL continuation must not connect')
    for page in ('wal1.invalid', token):
        code, payload = waapi_gateway.execute_gateway(['debug-wal-tree', '--wal-page', page],
            env=_gateway_env(tmp_path, '2025.1'), client_factory=no_connection)
        assert code == 2, payload


@pytest.mark.parametrize('case', ('hostile_native_keys', 'near_transport_ceiling'))
def test_wal_full_hostile_native_document_survives_actual_main_stdout_below_ordinary_cap(tmp_path: Path, monkeypatch, capsys, case: str) -> None:
    key = ('~/' + '溪\"\n') * 1600
    raw = {'return': {'nodes': {key: {'id': 1, 'name': 'n' * 40000, 'type': 'Sound',
        'native': [[], {}, {'escape': '\\"\t' * 3000}]}}, 'extension': {'empty': {}}}}
    if case == 'near_transport_ceiling':
        raw = {'return': {'nodes': {'one': {'id': 1, 'name': 'x' * 230000, 'type': 'Sound'}}}}
    env = _gateway_env(tmp_path, '2025.1')
    monkeypatch.setenv('WAAPI_SKILL_CONFIG_PATH', env['WAAPI_SKILL_CONFIG_PATH'])
    client = FakeClient({'ak.wwise.core.getInfo': _live_info('2025.1'), 'ak.wwise.debug.getWalTree': raw})
    monkeypatch.setattr(waapi_gateway, 'default_client_factory', lambda url: client)
    argv, values, positions = ['debug-wal-tree', '--max-nodes', '256'], [], []
    sizes = []
    for index in range(100):
        assert waapi_gateway.main(argv) == 0
        text = capsys.readouterr().out
        sizes.append(len(text.encode('utf-8')))
        (tmp_path / f'wal-page-{index:03}.json').write_text(text, encoding='utf-8')
        assert sizes[-1] < 24 * 1024
        payload = json.loads(text)
        assert list(payload)[-1] == 'agent_result'
        result = payload['agent_result']
        for fragment in result['native_result_fragments']:
            positions.append(fragment['offset'])
            values.append(fragment['value'])
        if result['observation_complete']:
            break
        argv = result['next_command']['gateway_argv']
    else:
        pytest.fail('hostile native JSON did not finish')
    assert json.loads(''.join(values)) == raw
    assert positions == list(range(0, len(''.join(values)), 1024))
    (tmp_path / 'stdout-evidence.json').write_text(json.dumps({'case': case, 'page_count': len(sizes),
        'utf8_bytes': sizes, 'maximum_utf8_bytes': max(sizes), 'exact_reconstruction': True}), encoding='utf-8')


def test_wal_optional_native_nodes_omission_is_preserved_distinct_from_empty_map(tmp_path: Path) -> None:
    for raw in ({'return': {}}, {'return': {'nodes': {}}}):
        code, payload, _ = _wal_read(tmp_path, raw=raw)
        assert code == 0, payload
        assert payload['agent_result']['native_result'] == raw
        assert payload['agent_result']['observation_complete'] is True


@pytest.mark.parametrize('change', ('endpoint', 'configuration_path'))
def test_wal_continuation_binds_selected_configuration_before_native_reread(tmp_path: Path, change: str) -> None:
    raw = _large_wal()
    code, first, _ = _wal_read(tmp_path, raw=raw, argv=['debug-wal-tree', '--max-nodes', '1'])
    assert code == 0, first
    env = _gateway_env(tmp_path, '2025.1')
    config = json.loads(Path(env['WAAPI_SKILL_CONFIG_PATH']).read_text())
    if change == 'endpoint':
        config['waapi_port'] += 1
    else:
        env['WAAPI_SKILL_CONFIG_PATH'] = str(tmp_path / 'different-config.json')
    Path(env['WAAPI_SKILL_CONFIG_PATH']).write_text(json.dumps(config))
    client = FakeClient({'ak.wwise.core.getInfo': _live_info('2025.1'), 'ak.wwise.debug.getWalTree': raw})
    code, payload = waapi_gateway.execute_gateway(first['agent_result']['next_command']['gateway_argv'],
        env=env, client_factory=lambda url: client)
    assert code == 2, payload
    assert payload['error_code'] == 'WAL_CONTINUATION_CHANGED'
    assert [call[0] for call in client.calls] == ['ak.wwise.core.getInfo']


def test_wal_offline_schema_discloses_closed_complete_delivery_contract(tmp_path: Path) -> None:
    def no_connection(url):
        pytest.fail('WAL contract discovery is offline')
    code, payload = waapi_gateway.execute_gateway(['request-schema', 'ak.wwise.debug.getWalTree'],
        env=_gateway_env(tmp_path, '2025.1'), client_factory=no_connection)
    assert code == 0, payload
    contract = payload['business_contract']
    assert contract['page_size']['arguments'] == ['--max-nodes', '<1..256>']
    assert contract['continuation']['source_field'] == 'agent_result.next_command'
    assert contract['delivery']['preserves_all_native_fields'] is True
    assert contract['delivery']['native_transport_limit_bytes'] == 256 * 1024
    assert contract['delivery']['mutation_authority'] is False
    assert payload['native_request_fields_disclosed'] is False
