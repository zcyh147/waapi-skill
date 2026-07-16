from __future__ import annotations

import math
import os
import json
import time
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1" or os.getenv("WWISE_DESTRUCTIVE") != "1":
    pytest.skip(
        "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required for 2023.1 destructive sandbox tests",
        allow_module_level=True,
    )
if os.getenv("WWISE_VERSION") != "2023.1":
    pytest.skip("WWISE_VERSION=2023.1 is required for 2023.1 destructive sandbox tests", allow_module_level=True)

from tests.destructive.support.destructive_2023_sandbox import (  # pyright: ignore[reportMissingImports]
    Destructive2023SandboxRuntime,
    DestructiveSandboxUnavailable,
    unique_2023_name,
)
from tests.support.active_gate_failures import skip_or_fail_unavailable  # pyright: ignore[reportMissingImports]

ACTOR_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
READBACK_FIELDS = ["id", "name", "type", "path", "notes"]
REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / ".waapi-skill-state" / "evidence" / "wwise-2023-test-parity" / "destructive"


@contextmanager
def _destructive_sandbox(*, track_generated_outputs: bool = False) -> Iterator[Destructive2023SandboxRuntime]:
    try:
        with Destructive2023SandboxRuntime(track_generated_outputs=track_generated_outputs) as runtime:
            yield runtime
    except DestructiveSandboxUnavailable as exc:
        skip_or_fail_unavailable(exc)


def _create_object(client: Any, parent: str, object_type: str, name: str) -> str:
    result = client.call(
        "ak.wwise.core.object.create",
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
    result = client.call("ak.wwise.core.object.get", {"from": {"id": [object_id]}}, options={"return": READBACK_FIELDS})
    if result is None:
        return []
    assert isinstance(result, Mapping), f"object.get must return a mapping: {result!r}"
    rows = result.get("return")
    assert isinstance(rows, list), f"object.get must return an array: {result!r}"
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


def _delete_if_present(client: Any, object_id: str) -> None:
    if _read_rows(client, object_id):
        client.call("ak.wwise.core.object.delete", {"object": object_id}, options={})
        assert _read_rows(client, object_id) == []


SOUNDBANK_PARENT = r"\SoundBanks\Default Work Unit"


@pytest.mark.live
@pytest.mark.destructive
def test_2023_audio_import_generated_wav_readback_cleanup() -> None:
    with _destructive_sandbox(track_generated_outputs=True) as runtime:
        sandbox = runtime.require_sandbox()
        assert runtime.destructive_contract is not None
        assert runtime.destructive_contract.active_destructive_project == sandbox.sandbox_project.resolve(strict=False)
        client = runtime.require_client()
        sound_id: str | None = None
        try:
            name = unique_2023_name("WAAPI_2023_AUDIO_", "import")
            audio_file = _write_fixture_wav(runtime.require_sandbox().sandbox_path / "Task2023GeneratedAudio", name)
            assert _path_is_under(audio_file, runtime.require_sandbox().sandbox_path)
            result = client.call(
                "ak.wwise.core.audio.import",
                {
                    "importOperation": "createNew",
                    "imports": [
                        {
                            "audioFile": str(audio_file),
                            "objectPath": f"{ACTOR_PARENT}\\<Sound>{name}",
                            "objectType": "Sound",
                            "notes": f"2023.1 generated audio import {name}",
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
            _write_destructive_evidence(
                "audio_import_generated_wav_readback_cleanup",
                ["ak.wwise.core.audio.import"],
                {
                    "imported_name": name,
                    "sound_id": sound_id,
                    "readback": readback,
                    "audio_file": _relative_to_sandbox(audio_file, sandbox.sandbox_path),
                    "active_destructive_project": str(runtime.destructive_contract.active_destructive_project),
                    "sandbox_project": str(sandbox.sandbox_project),
                    "source_immutability_guard": "Destructive2023SandboxRuntime.assert_source_unchanged runs on exit",
                },
            )
        finally:
            if sound_id is not None:
                _delete_if_present(client, sound_id)


@pytest.mark.live
@pytest.mark.destructive
def test_2023_soundbank_inclusions_replace_read_remove_cleanup() -> None:
    with _destructive_sandbox(track_generated_outputs=True) as runtime:
        sandbox = runtime.require_sandbox()
        assert runtime.destructive_contract is not None
        assert runtime.destructive_contract.active_destructive_project == sandbox.sandbox_project.resolve(strict=False)
        client = runtime.require_client()
        soundbank_id: str | None = None
        sound_id: str | None = None
        try:
            soundbank_id = _create_object(client, SOUNDBANK_PARENT, "SoundBank", unique_2023_name("WAAPI_2023_BANK_", "bank"))
            sound_id = _create_object(client, ACTOR_PARENT, "Sound", unique_2023_name("WAAPI_2023_BANK_", "sound"))
            _replace_soundbank_inclusion(client, soundbank_id, sound_id)
            inclusions = _soundbank_inclusions(client, soundbank_id)
            assert any(row.get("object") == sound_id for row in inclusions), inclusions

            _remove_inclusion_if_possible(client, soundbank_id, sound_id)
            inclusions_after_remove = _soundbank_inclusions(client, soundbank_id)
            assert not any(row.get("object") == sound_id for row in inclusions_after_remove)
            _write_destructive_evidence(
                "soundbank_inclusions_replace_read_remove_cleanup",
                [
                    "ak.wwise.core.soundbank.setInclusions",
                    "ak.wwise.core.soundbank.getInclusions",
                ],
                {
                    "soundbank_id": soundbank_id,
                    "sound_id": sound_id,
                    "inclusions_after_replace": inclusions,
                    "inclusions_after_remove": inclusions_after_remove,
                    "active_destructive_project": str(runtime.destructive_contract.active_destructive_project),
                    "sandbox_project": str(sandbox.sandbox_project),
                    "source_immutability_guard": "Destructive2023SandboxRuntime.assert_source_unchanged runs on exit",
                },
            )
        finally:
            if soundbank_id is not None and sound_id is not None:
                _remove_inclusion_if_possible(client, soundbank_id, sound_id)
            for object_id in (soundbank_id, sound_id):
                if object_id is not None:
                    _delete_if_present(client, object_id)


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


def _replace_soundbank_inclusion(client: Any, soundbank_id: str, sound_id: str) -> None:
    client.call(
        "ak.wwise.core.soundbank.setInclusions",
        {
            "soundbank": soundbank_id,
            "operation": "replace",
            "inclusions": [{"object": sound_id, "filter": ["structures", "media"]}],
        },
        options={},
    )


def _remove_inclusion_if_possible(client: Any, soundbank_id: str, sound_id: str) -> None:
    try:
        client.call(
            "ak.wwise.core.soundbank.setInclusions",
            {
                "soundbank": soundbank_id,
                "operation": "remove",
                "inclusions": [{"object": sound_id, "filter": ["structures", "media"]}],
            },
            options={},
        )
    except BaseException:
        return


def _soundbank_inclusions(client: Any, soundbank_id: str) -> list[Mapping[str, Any]]:
    result = client.call("ak.wwise.core.soundbank.getInclusions", {"soundbank": soundbank_id}, options={})
    assert isinstance(result, Mapping), f"getInclusions must return a mapping: {result!r}"
    rows = result.get("inclusions")
    assert isinstance(rows, list), f"getInclusions must return inclusions: {result!r}"
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


def _path_is_under(path: Path, root: Path) -> bool:
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _relative_to_sandbox(path: Path, sandbox_path: Path) -> str:
    return path.resolve(strict=False).relative_to(sandbox_path.resolve(strict=False)).as_posix()


def _write_destructive_evidence(case_id: str, uris: list[str], details: Mapping[str, Any]) -> None:
    path = EVIDENCE_ROOT / f"{case_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "case_id": case_id,
                "status": "passed",
                "uris": uris,
                "details": _json_safe(details),
                "cleanup": "objects are removed and read back absent before test exit",
                "source_project_mutation_allowed": False,
                "sandbox_required": True,
                "recorded_at_unix": int(time.time()),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))
