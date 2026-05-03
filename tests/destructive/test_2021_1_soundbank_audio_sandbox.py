from __future__ import annotations

import json
import math
import os
import time
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1" or os.getenv("WWISE_DESTRUCTIVE") != "1":
    pytest.skip(
        "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required for 2021.1 destructive sandbox tests",
        allow_module_level=True,
    )
if os.getenv("WWISE_VERSION") != "2021.1":
    pytest.skip("WWISE_VERSION=2021.1 is required for 2021.1 destructive sandbox tests", allow_module_level=True)

from wwise_waapi.destructive_2021_sandbox import (  # pyright: ignore[reportMissingImports]
    Destructive2021SandboxRuntime,
    DestructiveSandboxUnavailable,
    hash_mutation_bearing_project_files,
    unique_2021_name,
)
from wwise_waapi.live_environment import path_is_under  # pyright: ignore[reportMissingImports]
from tests.support.active_gate_failures import skip_or_fail_unavailable  # pyright: ignore[reportMissingImports]

AUDIO_IMPORT_URI = "ak.wwise.core.audio.import"
OBJECT_CREATE_URI = "ak.wwise.core.object.create"
OBJECT_DELETE_URI = "ak.wwise.core.object.delete"
OBJECT_GET_URI = "ak.wwise.core.object.get"
OBJECT_GET_TYPES_URI = "ak.wwise.core.object.getTypes"
SOUNDBANK_GET_INCLUSIONS_URI = "ak.wwise.core.soundbank.getInclusions"
SOUNDBANK_SET_INCLUSIONS_URI = "ak.wwise.core.soundbank.setInclusions"

ACTOR_MIXER_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
SOUNDBANK_PARENT = r"\SoundBanks\Default Work Unit"
READBACK_FIELDS = ["id", "name", "type", "path", "notes"]
PARENT_FIELDS = ["id", "name", "type", "path"]
REFLECTED_URI_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "resources" / "manifest" / "2021.1" / "functions.json"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "resources" / "manifest" / "2021.1" / "schemas.json"
REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence" / "wwise-2021-waapi-integration-coverage"
DESTRUCTIVE_EVIDENCE_ROOT = EVIDENCE_ROOT / "destructive"
TASK_EVIDENCE_PATH = EVIDENCE_ROOT / "task-11-soundbank-audio.json"
EXACT_DESTRUCTIVE_COMMAND = (
    'WWISE_VERSION=2021.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh" '
    'WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj" '
    "WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2021.1 WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 "
    "python -m pytest tests/destructive/test_2021_1_soundbank_audio_sandbox.py -q"
)


@contextmanager
def _destructive_sandbox() -> Iterator[Destructive2021SandboxRuntime]:
    try:
        with Destructive2021SandboxRuntime(track_generated_outputs=True) as runtime:
            yield runtime
    except DestructiveSandboxUnavailable as exc:
        skip_or_fail_unavailable(exc)


@pytest.mark.live
@pytest.mark.destructive
def test_2021_audio_import_generated_wav_readback_cleanup_against_copied_sandbox() -> None:
    reflected_uris = _reflected_uris()
    _require_reflected(reflected_uris, [AUDIO_IMPORT_URI, OBJECT_DELETE_URI, OBJECT_GET_URI, OBJECT_GET_TYPES_URI])
    runtime: Destructive2021SandboxRuntime | None = None
    source_before: Mapping[str, Any] | None = None
    case_details: dict[str, Any] = {}

    with _destructive_sandbox() as active_runtime:
        runtime = active_runtime
        assert runtime is not None
        sandbox = runtime.require_sandbox()
        assert runtime.destructive_contract is not None
        assert runtime.destructive_contract.active_destructive_project == sandbox.sandbox_project.resolve(strict=False)

        source_before = _source_state(runtime)
        client = runtime.require_client()
        target = _preflight_audio_import_target(client, reflected_uris)
        sound_id: str | None = None
        try:
            name = unique_2021_name("WAAPI_2021_AUDIO_", "import")
            audio_file = _write_fixture_wav(sandbox.sandbox_path / "Task2021GeneratedAudio", name)
            assert path_is_under(audio_file.resolve(strict=False), sandbox.sandbox_path.resolve(strict=False))
            result = client.call(
                AUDIO_IMPORT_URI,
                {
                    "importOperation": "createNew",
                    "imports": [
                        {
                            "audioFile": str(audio_file),
                            "objectPath": f"{target.parent_path}\\<Sound>{name}",
                            "objectType": "Sound",
                            "notes": f"2021.1 generated audio import behavior {name}",
                        }
                    ],
                },
                options={"return": READBACK_FIELDS},
            )
            sound = _first_row_of_type(_object_rows_from_import(result), "Sound")
            sound_id = _row_id(sound)
            readback = _read_one(client, sound_id)
            assert readback["name"] == name
            assert readback["type"] == "Sound"
            assert str(readback["path"]).endswith(f"\\{name}")
            assert audio_file.exists()

            case_details = {
                "imported_name": name,
                "sound_id": sound_id,
                "readback": readback,
                "audio_file": _relative_to_sandbox(audio_file, sandbox.sandbox_path),
                "preflight": target.as_dict(),
                "active_destructive_project": str(runtime.destructive_contract.active_destructive_project),
                "sandbox_project": str(sandbox.sandbox_project),
                "source_before": source_before,
                "source_after_before_runtime_exit": _source_state(runtime),
                "source_immutability_guard": "Destructive2021SandboxRuntime.assert_source_unchanged runs on exit and verifies source .wproj/.wwu checksum plus mtime and generated-output snapshot",
            }
        finally:
            if sound_id is not None:
                _delete_if_present(client, sound_id)
                case_details["read_after_cleanup_delete"] = _read_rows(client, sound_id)

    assert runtime is not None and source_before is not None
    source_after = _source_state(runtime)
    assert source_after == source_before
    case_details["source_after_runtime_exit"] = source_after
    _write_case_evidence("audio_import_generated_wav_readback_cleanup", [AUDIO_IMPORT_URI], case_details)


@pytest.mark.live
@pytest.mark.destructive
def test_2021_soundbank_inclusions_replace_read_remove_cleanup_against_copied_sandbox() -> None:
    reflected_uris = _reflected_uris()
    _require_reflected(
        reflected_uris,
        [
            OBJECT_CREATE_URI,
            OBJECT_DELETE_URI,
            OBJECT_GET_URI,
            OBJECT_GET_TYPES_URI,
            SOUNDBANK_GET_INCLUSIONS_URI,
            SOUNDBANK_SET_INCLUSIONS_URI,
        ],
    )
    runtime: Destructive2021SandboxRuntime | None = None
    source_before: Mapping[str, Any] | None = None
    case_details: dict[str, Any] = {}

    with _destructive_sandbox() as active_runtime:
        runtime = active_runtime
        assert runtime is not None
        sandbox = runtime.require_sandbox()
        assert runtime.destructive_contract is not None
        assert runtime.destructive_contract.active_destructive_project == sandbox.sandbox_project.resolve(strict=False)

        source_before = _source_state(runtime)
        client = runtime.require_client()
        target = _preflight_soundbank_inclusion_target(client, reflected_uris)
        soundbank_id: str | None = None
        included_id: str | None = None
        try:
            soundbank_id = _create_object(client, target.soundbank_parent_path, "SoundBank", unique_2021_name("WAAPI_2021_BANK_", "bank"))
            included_id = _create_object(client, target.inclusion_parent_path, "ActorMixer", unique_2021_name("WAAPI_2021_BANK_", "actor"))

            inclusions_before = _soundbank_inclusions(client, soundbank_id)
            _replace_soundbank_inclusion(client, soundbank_id, included_id)
            inclusions_after_replace = _soundbank_inclusions(client, soundbank_id)
            assert any(_matches_inclusion(row, included_id, "structures") for row in inclusions_after_replace), inclusions_after_replace

            _remove_inclusion_if_possible(client, soundbank_id, included_id)
            inclusions_after_remove = _soundbank_inclusions(client, soundbank_id)
            assert not any(row.get("object") == included_id for row in inclusions_after_remove)

            case_details = {
                "soundbank_id": soundbank_id,
                "included_actor_mixer_id": included_id,
                "inclusions_before": inclusions_before,
                "inclusions_after_replace": inclusions_after_replace,
                "inclusions_after_remove": inclusions_after_remove,
                "readback_helper_uri": SOUNDBANK_GET_INCLUSIONS_URI,
                "preflight": target.as_dict(),
                "active_destructive_project": str(runtime.destructive_contract.active_destructive_project),
                "sandbox_project": str(sandbox.sandbox_project),
                "source_before": source_before,
                "source_after_before_runtime_exit": _source_state(runtime),
                "source_immutability_guard": "Destructive2021SandboxRuntime.assert_source_unchanged runs on exit and verifies source .wproj/.wwu checksum plus mtime and generated-output snapshot",
            }
        finally:
            if soundbank_id is not None and included_id is not None:
                _remove_inclusion_if_possible(client, soundbank_id, included_id)
                case_details["inclusions_after_final_cleanup"] = _soundbank_inclusions(client, soundbank_id)
            for object_id in (soundbank_id, included_id):
                if object_id is not None:
                    _delete_if_present(client, object_id)
                    case_details.setdefault("read_after_object_cleanup_delete", {})[object_id] = _read_rows(client, object_id)

    assert runtime is not None and source_before is not None
    source_after = _source_state(runtime)
    assert source_after == source_before
    case_details["source_after_runtime_exit"] = source_after
    _write_case_evidence(
        "soundbank_inclusions_replace_read_remove_cleanup",
        [SOUNDBANK_SET_INCLUSIONS_URI],
        case_details,
    )


class AudioImportTarget:
    def __init__(self, *, parent_path: str, parent_row: Mapping[str, Any], sound_type_row: Mapping[str, Any], schema_preflight: Mapping[str, Any]) -> None:
        self.parent_path = parent_path
        self.parent_row = dict(parent_row)
        self.sound_type_row = dict(sound_type_row)
        self.schema_preflight = dict(schema_preflight)

    def as_dict(self) -> dict[str, Any]:
        return {
            "parent_path": self.parent_path,
            "parent_row": self.parent_row,
            "sound_type_row": self.sound_type_row,
            "schema_preflight": self.schema_preflight,
            "readback_uri": OBJECT_GET_URI,
            "source": "live 2021.1 copied-sandbox preflight before audio.import mutation",
        }


class SoundBankInclusionTarget:
    def __init__(
        self,
        *,
        soundbank_parent_path: str,
        soundbank_parent_row: Mapping[str, Any],
        inclusion_parent_path: str,
        inclusion_parent_row: Mapping[str, Any],
        soundbank_type_row: Mapping[str, Any],
        inclusion_type_row: Mapping[str, Any],
        schema_preflight: Mapping[str, Any],
    ) -> None:
        self.soundbank_parent_path = soundbank_parent_path
        self.soundbank_parent_row = dict(soundbank_parent_row)
        self.inclusion_parent_path = inclusion_parent_path
        self.inclusion_parent_row = dict(inclusion_parent_row)
        self.soundbank_type_row = dict(soundbank_type_row)
        self.inclusion_type_row = dict(inclusion_type_row)
        self.schema_preflight = dict(schema_preflight)

    def as_dict(self) -> dict[str, Any]:
        return {
            "soundbank_parent_path": self.soundbank_parent_path,
            "soundbank_parent_row": self.soundbank_parent_row,
            "inclusion_parent_path": self.inclusion_parent_path,
            "inclusion_parent_row": self.inclusion_parent_row,
            "soundbank_type_row": self.soundbank_type_row,
            "inclusion_type_row": self.inclusion_type_row,
            "schema_preflight": self.schema_preflight,
            "readback_uri": SOUNDBANK_GET_INCLUSIONS_URI,
            "source": "live 2021.1 copied-sandbox preflight before soundbank.setInclusions mutation",
        }


def _preflight_audio_import_target(client: Any, reflected_uris: set[str]) -> AudioImportTarget:
    _require_reflected(reflected_uris, [AUDIO_IMPORT_URI, OBJECT_GET_URI, OBJECT_GET_TYPES_URI])
    schema_preflight = _schema_preflight(AUDIO_IMPORT_URI)
    parent_rows = _read_by_path(client, ACTOR_MIXER_PARENT, PARENT_FIELDS)
    if len(parent_rows) != 1:
        _write_deferred_case_evidence(
            "missing_audio_import_parent",
            [AUDIO_IMPORT_URI],
            {"reason": "2021.1 copied sandbox did not expose exactly one Actor-Mixer default work unit import parent", "parent_path": ACTOR_MIXER_PARENT, "rows": parent_rows},
        )
        pytest.skip(f"2021.1 copied sandbox audio import parent was unavailable: {ACTOR_MIXER_PARENT}")
    sound_rows = _type_rows(client, "Sound")
    if not sound_rows:
        _write_deferred_case_evidence(
            "missing_audio_import_sound_type",
            [AUDIO_IMPORT_URI],
            {"reason": "2021.1 copied sandbox object.getTypes did not report Sound before audio.import", "object_type": "Sound"},
        )
        pytest.skip("2021.1 copied sandbox did not report Sound as an importable object type")
    return AudioImportTarget(parent_path=ACTOR_MIXER_PARENT, parent_row=parent_rows[0], sound_type_row=sound_rows[0], schema_preflight=schema_preflight)


def _preflight_soundbank_inclusion_target(client: Any, reflected_uris: set[str]) -> SoundBankInclusionTarget:
    _require_reflected(reflected_uris, [SOUNDBANK_GET_INCLUSIONS_URI, SOUNDBANK_SET_INCLUSIONS_URI, OBJECT_GET_URI, OBJECT_GET_TYPES_URI])
    schema_preflight = _schema_preflight(SOUNDBANK_SET_INCLUSIONS_URI)
    soundbank_parent_rows = _read_by_path(client, SOUNDBANK_PARENT, PARENT_FIELDS)
    inclusion_parent_rows = _read_by_path(client, ACTOR_MIXER_PARENT, PARENT_FIELDS)
    if len(soundbank_parent_rows) != 1:
        _write_deferred_case_evidence(
            "missing_soundbank_parent",
            [SOUNDBANK_SET_INCLUSIONS_URI],
            {"reason": "2021.1 copied sandbox did not expose exactly one SoundBanks default work unit parent", "parent_path": SOUNDBANK_PARENT, "rows": soundbank_parent_rows},
        )
        pytest.skip(f"2021.1 copied sandbox SoundBank parent was unavailable: {SOUNDBANK_PARENT}")
    if len(inclusion_parent_rows) != 1:
        _write_deferred_case_evidence(
            "missing_soundbank_inclusion_parent",
            [SOUNDBANK_SET_INCLUSIONS_URI],
            {"reason": "2021.1 copied sandbox did not expose exactly one Actor-Mixer inclusion parent", "parent_path": ACTOR_MIXER_PARENT, "rows": inclusion_parent_rows},
        )
        pytest.skip(f"2021.1 copied sandbox inclusion parent was unavailable: {ACTOR_MIXER_PARENT}")
    soundbank_rows = _type_rows(client, "SoundBank")
    actor_mixer_rows = _type_rows(client, "ActorMixer")
    if not soundbank_rows or not actor_mixer_rows:
        _write_deferred_case_evidence(
            "missing_soundbank_inclusion_types",
            [SOUNDBANK_SET_INCLUSIONS_URI],
            {
                "reason": "2021.1 copied sandbox object.getTypes did not report SoundBank and ActorMixer before setInclusions",
                "has_soundbank": bool(soundbank_rows),
                "has_actor_mixer": bool(actor_mixer_rows),
            },
        )
        pytest.skip("2021.1 copied sandbox did not report SoundBank and ActorMixer creatable types")
    return SoundBankInclusionTarget(
        soundbank_parent_path=SOUNDBANK_PARENT,
        soundbank_parent_row=soundbank_parent_rows[0],
        inclusion_parent_path=ACTOR_MIXER_PARENT,
        inclusion_parent_row=inclusion_parent_rows[0],
        soundbank_type_row=soundbank_rows[0],
        inclusion_type_row=actor_mixer_rows[0],
        schema_preflight=schema_preflight,
    )


def _schema_preflight(uri: str) -> dict[str, Any]:
    schema = _schema_for(uri)
    args = schema.get("argsSchema", {})
    assert isinstance(args, Mapping), f"{uri} args schema must be a mapping: {schema!r}"
    required = args.get("required", [])
    properties = args.get("properties", {})
    assert isinstance(required, list), f"{uri} required args must be a list: {schema!r}"
    assert isinstance(properties, Mapping), f"{uri} properties must be a mapping: {schema!r}"
    if uri == AUDIO_IMPORT_URI:
        assert "imports" in required
        assert "imports" in properties
        assert "importOperation" in properties
    elif uri == SOUNDBANK_SET_INCLUSIONS_URI:
        assert {"soundbank", "inclusions", "operation"} <= set(required)
        assert {"soundbank", "inclusions", "operation"} <= set(properties)
    return {"uri": uri, "required_args": required, "properties": sorted(properties)}


def _schema_for(uri: str) -> Mapping[str, Any]:
    payload = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for entry in payload["schemas"]:
        if entry.get("uri") == uri:
            schema = entry.get("schema")
            assert isinstance(schema, Mapping), f"{uri} schema must be a mapping: {entry!r}"
            return schema
    raise AssertionError(f"missing 2021.1 schema for {uri}")


def _type_rows(client: Any, object_type: str) -> list[Mapping[str, Any]]:
    return [row for row in _object_types(client) if row.get("name") == object_type or row.get("type") == object_type]


def _create_object(client: Any, parent: str, object_type: str, name: str) -> str:
    result = client.call(
        OBJECT_CREATE_URI,
        {"parent": parent, "type": object_type, "name": name, "onNameConflict": "fail"},
        options={},
    )
    assert isinstance(result, Mapping), f"object.create must return a mapping: {result!r}"
    object_id = result.get("id")
    assert isinstance(object_id, str) and object_id, f"object.create did not return an id: {result!r}"
    return object_id


def _read_one(client: Any, object_id: str) -> Mapping[str, Any]:
    rows = _read_rows(client, object_id)
    assert len(rows) == 1, f"expected one object for {object_id}, got {rows!r}"
    return rows[0]


def _read_rows(client: Any, object_id: str) -> list[Mapping[str, Any]]:
    result = client.call(OBJECT_GET_URI, {"from": {"id": [object_id]}}, options={"return": READBACK_FIELDS})
    if result is None:
        return []
    return _rows(result)


def _read_by_path(client: Any, path: str, fields: list[str]) -> list[Mapping[str, Any]]:
    result = client.call(OBJECT_GET_URI, {"from": {"path": [path]}}, options={"return": fields})
    if result is None:
        return []
    return _rows(result)


def _object_types(client: Any) -> list[Mapping[str, Any]]:
    result = client.call(OBJECT_GET_TYPES_URI, {}, options={})
    if result is None:
        return []
    return _rows(result)


def _rows(result: Any) -> list[Mapping[str, Any]]:
    assert isinstance(result, Mapping), f"WAAPI result must be a mapping: {result!r}"
    rows = result.get("return")
    assert isinstance(rows, list), f"WAAPI result must contain a return array: {result!r}"
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


def _delete_if_present(client: Any, object_id: str) -> None:
    if _read_rows(client, object_id):
        client.call(OBJECT_DELETE_URI, {"object": object_id}, options={})
        assert _read_rows(client, object_id) == []


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
    return path


def _object_rows_from_import(result: Any) -> list[Mapping[str, Any]]:
    assert isinstance(result, Mapping), f"import must return a mapping: {result!r}"
    rows = result.get("objects")
    assert isinstance(rows, list) and rows, f"import must return objects: {result!r}"
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


def _first_row_of_type(rows: list[Mapping[str, Any]], object_type: str) -> Mapping[str, Any]:
    for row in rows:
        if row.get("type") == object_type:
            return row
    raise AssertionError(f"missing imported {object_type} row: {rows!r}")


def _row_id(row: Mapping[str, Any]) -> str:
    object_id = row.get("id")
    assert isinstance(object_id, str) and object_id, row
    return object_id


def _replace_soundbank_inclusion(client: Any, soundbank_id: str, included_id: str) -> None:
    client.call(
        SOUNDBANK_SET_INCLUSIONS_URI,
        {
            "soundbank": soundbank_id,
            "operation": "replace",
            "inclusions": [{"object": included_id, "filter": ["structures"]}],
        },
        options={},
    )


def _remove_inclusion_if_possible(client: Any, soundbank_id: str, included_id: str) -> None:
    try:
        client.call(
            SOUNDBANK_SET_INCLUSIONS_URI,
            {
                "soundbank": soundbank_id,
                "operation": "remove",
                "inclusions": [{"object": included_id, "filter": ["structures"]}],
            },
            options={},
        )
    except BaseException:
        return


def _soundbank_inclusions(client: Any, soundbank_id: str) -> list[Mapping[str, Any]]:
    result = client.call(SOUNDBANK_GET_INCLUSIONS_URI, {"soundbank": soundbank_id}, options={})
    assert isinstance(result, Mapping), f"getInclusions must return a mapping: {result!r}"
    rows = result.get("inclusions")
    assert isinstance(rows, list), f"getInclusions must return inclusions: {result!r}"
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


def _matches_inclusion(row: Mapping[str, Any], object_id: str, filter_name: str) -> bool:
    filters = row.get("filter")
    return row.get("object") == object_id and isinstance(filters, list) and filter_name in filters


def _reflected_uris() -> set[str]:
    payload = json.loads(REFLECTED_URI_PATH.read_text(encoding="utf-8"))
    return {str(entry["uri"]) for entry in payload["functions"]}


def _require_reflected(reflected_uris: set[str], uris: list[str]) -> None:
    missing = sorted(uri for uri in uris if uri not in reflected_uris)
    if missing:
        _write_deferred_case_evidence(
            "missing_reflected_uri",
            missing,
            {"reason": "Required 2021.1 URI was not reflected; destructive substitution is forbidden", "missing": missing},
        )
        pytest.skip(f"2021.1 reflected URI(s) unavailable: {', '.join(missing)}")


def _source_state(runtime: Destructive2021SandboxRuntime) -> dict[str, Any]:
    sandbox = runtime.require_sandbox()
    digest, file_count, byte_count = hash_mutation_bearing_project_files(sandbox.source_root)
    return {
        "source_project": str(sandbox.source_project),
        "mtime": sandbox.source_project.stat().st_mtime,
        "project_files_sha256": digest,
        "project_file_count": file_count,
        "project_file_bytes": byte_count,
    }


def _relative_to_sandbox(path: Path, sandbox_path: Path) -> str:
    return path.resolve(strict=False).relative_to(sandbox_path.resolve(strict=False)).as_posix()


def _write_case_evidence(case_id: str, uris: list[str], details: Mapping[str, Any]) -> None:
    payload = _evidence_payload(case_id, "passed", uris, details)
    path = _case_evidence_path(case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_task_evidence(case_id, payload)


def _write_deferred_case_evidence(case_id: str, uris: list[str], details: Mapping[str, Any]) -> None:
    payload = _evidence_payload(case_id, "deferred", uris, details)
    path = _case_evidence_path(case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_task_evidence(case_id, payload)


def _evidence_payload(case_id: str, status: str, uris: list[str], details: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": status,
        "version": "2021.1",
        "uris": uris,
        "details": _json_safe(details),
        "copied_sandbox_only": True,
        "cleanup": "created objects are deleted and read back absent before test exit when mutation occurs",
        "exact_destructive_command": EXACT_DESTRUCTIVE_COMMAND,
        "source_project_mutation_allowed": False,
        "sandbox_required": True,
        "recorded_at_unix": int(time.time()),
    }


def _case_evidence_path(case_id: str) -> Path:
    path = (DESTRUCTIVE_EVIDENCE_ROOT / f"{case_id}.json").resolve(strict=False)
    root = DESTRUCTIVE_EVIDENCE_ROOT.resolve(strict=False)
    if not path_is_under(path, root):
        raise AssertionError(f"evidence path must stay under {DESTRUCTIVE_EVIDENCE_ROOT}: {path}")
    return path


def _write_task_evidence(case_id: str, payload: Mapping[str, Any]) -> None:
    TASK_EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TASK_EVIDENCE_PATH.is_file():
        current = json.loads(TASK_EVIDENCE_PATH.read_text(encoding="utf-8"))
    else:
        current = {
            "task": "11. Prove 2021.1 import and soundbank behavior in copied destructive sandbox",
            "version": "2021.1",
            "exact_destructive_command": EXACT_DESTRUCTIVE_COMMAND,
            "source_project_mutation_allowed": False,
            "sandbox_required": True,
            "cases": {},
        }
    cases = current.setdefault("cases", {})
    cases[case_id] = _json_safe(payload)
    current["case_count"] = len(cases)
    current["passed_cases"] = sorted(case for case, item in cases.items() if item.get("status") == "passed")
    current["deferred_cases"] = sorted(case for case, item in cases.items() if item.get("status") == "deferred")
    current["recorded_at_unix"] = int(time.time())
    TASK_EVIDENCE_PATH.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))
