"""Public RTPC reads reject malformed native rows before retaining a snapshot."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env, gateway


URI = "ak.wwise.core.profiler.getRTPCs"
VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
ROW = {
    "id": "{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}",
    "name": "RPM",
    "gameObjectId": 18446744073709551614,
    "value": 1000.0,
}


def _read(tmp_path, version, rows, *, max_results=64):
    tmp_path.mkdir()

    class Client(_RuntimeControlDraftClient):
        def call(self, uri, args=None, options=None):
            if uri == URI:
                assert args == {"time": 23637}
                assert options == {}
                return {"return": deepcopy(rows)}
            return super().call(uri, args, options)

    client = Client(tmp_path, version=version)
    code, payload = gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), "core-call", URI,
         "--profiler-position", "23637", "--max-results", str(max_results)],
        env=_env(tmp_path, version=version), client_factory=lambda _: client,
    )
    return code, payload


def _assert_rejected(tmp_path, code, payload):
    assert code == 2, payload
    assert payload["ok"] is False
    assert len(json.dumps(payload, ensure_ascii=False).encode()) <= gateway.MAX_GATEWAY_RESULT_JSON_BYTES
    assert not list((tmp_path / "state" / "runtime-inspection-observations-v1").glob("*.json"))


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("invalid", [7, "63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4", "{not-a-guid}"])
def test_rtpc_read_rejects_invalid_id_before_retaining_any_rows(tmp_path, version, invalid):
    code, payload = _read(tmp_path / "baseline", version, [ROW])
    assert code == 0, payload
    assert payload["agent_result"]["return"] == [ROW]

    malformed = {**ROW, "id": invalid}
    # The invalid row is outside the first displayed range: retained rows must
    # all be checked, including rows a caller would reach only by continuation.
    code, payload = _read(tmp_path / "invalid", version, [malformed, ROW], max_results=1)
    _assert_rejected(tmp_path / "invalid", code, payload)
    assert payload["error_code"] == "RUNTIME_INSPECTION_RESULT_INVALID"
    assert "id" in payload["message"]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("invalid", [True, -1, 18446744073709551616, 1.5, "1", None])
def test_rtpc_read_rejects_invalid_game_object_before_retaining_any_rows(tmp_path, version, invalid):
    code, payload = _read(tmp_path / "baseline", version, [ROW])
    assert code == 0, payload
    assert payload["agent_result"]["return"] == [ROW]

    code, payload = _read(tmp_path / "invalid", version, [{**ROW, "gameObjectId": invalid}, ROW], max_results=1)
    _assert_rejected(tmp_path / "invalid", code, payload)
    assert payload["error_code"] == "RUNTIME_INSPECTION_RESULT_INVALID"
    assert "gameObjectId" in payload["message"]


@pytest.mark.parametrize("version", VERSIONS[:-1])
@pytest.mark.parametrize("invalid", [False, 7, None, {}, []])
def test_rtpc_read_rejects_nonstring_legacy_name_before_retaining_any_rows(tmp_path, version, invalid):
    code, payload = _read(tmp_path / "baseline", version, [ROW])
    assert code == 0, payload
    assert payload["agent_result"]["return"] == [ROW]

    code, payload = _read(tmp_path / "invalid", version, [{**ROW, "name": invalid}, ROW], max_results=1)
    _assert_rejected(tmp_path / "invalid", code, payload)
    assert payload["error_code"] == "RUNTIME_INSPECTION_RESULT_INVALID"
    assert "name" in payload["message"]


@pytest.mark.parametrize("version", VERSIONS)
def test_rtpc_read_preserves_guid_spelling_uint64_boundaries_and_values(tmp_path, version):
    rows = [
        {**ROW, "id": "{63d15b0f-16e7-4b8a-b9ca-7bf10ad315b4}", "gameObjectId": 0, "value": -0.25},
        {**ROW, "gameObjectId": 18446744073709551615, "value": 0},
    ]
    code, payload = _read(tmp_path / "read", version, rows)
    assert code == 0, payload
    assert payload["agent_result"]["return"] == rows
    assert payload["agent_result"]["complete"] is True
    assert list(payload)[-1] == "agent_result"


@pytest.mark.parametrize("version", VERSIONS[:2])
def test_rtpc_read_preserves_optional_field_absence_in_older_versions(tmp_path, version):
    rows = [{}, *({field: value} for field, value in ROW.items())]
    code, payload = _read(tmp_path / "read", version, rows)
    assert code == 0, payload
    assert payload["agent_result"]["return"] == rows
    assert payload["agent_result"]["complete"] is True


@pytest.mark.parametrize("version", VERSIONS[2:])
@pytest.mark.parametrize("field", ROW)
def test_rtpc_read_requires_each_field_in_newer_versions(tmp_path, version, field):
    row = {key: value for key, value in ROW.items() if key != field}
    code, payload = _read(tmp_path / "invalid", version, [row])
    _assert_rejected(tmp_path / "invalid", code, payload)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("invalid", [True, "1000", None, float("inf"), float("-inf"), float("nan")])
def test_rtpc_read_keeps_inline_value_and_finiteness_validation(tmp_path, version, invalid):
    code, payload = _read(tmp_path / "invalid", version, [{**ROW, "value": invalid}])
    _assert_rejected(tmp_path / "invalid", code, payload)


def test_rtpc_read_preserves_exact_original_2022_array_including_midi_names(tmp_path):
    fixture = Path(__file__).resolve().parents[1] / "fixtures/runtime/rtpc-2022-native-rows.json"
    rows = json.loads(fixture.read_text(encoding="utf-8"))["return"]
    assert len(rows) == 17
    assert rows[12]["name"] == "CC #1: Modulation"
    assert rows[14]["name"] == "MIDI note velocity"
    code, payload = _read(tmp_path / "read", "2022.1", rows)
    assert code == 0, payload
    assert payload["agent_result"]["return"] == rows
    assert payload["agent_result"]["complete"] is True


def test_rtpc_read_preserves_empty_2025_name(tmp_path):
    row = {**ROW, "name": ""}
    code, payload = _read(tmp_path / "read", "2025.1", [row])
    assert code == 0, payload
    assert payload["agent_result"]["return"] == [row]


@pytest.mark.parametrize("invalid", [False, 7, None, {}, []])
def test_rtpc_read_keeps_2025_inline_name_type_validation(tmp_path, invalid):
    code, payload = _read(tmp_path / "invalid", "2025.1", [{**ROW, "name": invalid}])
    _assert_rejected(tmp_path / "invalid", code, payload)
