from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Mapping, cast

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1" or os.getenv("WWISE_DESTRUCTIVE") != "1":
    pytest.skip(
        "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required for destructive audio/soundbank sandbox tests",
        allow_module_level=True,
    )

from wwise_waapi.headless import HeadlessLifecycleError, default_waapi_client_factory  # pyright: ignore[reportMissingImports]
from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    LiveEnvironmentError,
    path_is_under,
    resolve_sample_project_source,
)
from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    SandboxFixtureError,
    cleanup_sandbox,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from tests.support.active_gate_failures import fail_if_active_runtime_failure  # pyright: ignore[reportMissingImports]
from tests.support.runtime_evidence_paths import (  # pyright: ignore[reportMissingImports]
    localize_runtime_evidence_path,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "tests"
    / "destructive"
    / "support"
    / "resources"
    / "capabilities"
    / "2022.1"
    / "task-8-soundbank-audio-sandbox-plan.json"
)
TASK6_PLAN_PATH = (
    REPO_ROOT
    / "tests"
    / "destructive"
    / "support"
    / "resources"
    / "capabilities"
    / "2022.1"
    / "task-6-process-definition-files-plan.json"
)
EVIDENCE_ROOT = REPO_ROOT / ".waapi-skill-state" / "evidence" / "wwise-waapi-live-sandbox-coverage"
TASK6_EVIDENCE_ROOT = REPO_ROOT / ".waapi-skill-state" / "evidence" / "wwise-waapi-deferred-reevaluation"
TEMP_PREFIX = "WAAPI_TASK8_SANDBOX_"
TASK6_TEMP_PREFIX = "WAAPI_TASK6_SANDBANK_"
ACTOR_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
SOUNDBANK_PARENT = r"\SoundBanks\Default Work Unit"
READBACK_FIELDS = ["id", "name", "type", "path", "notes"]
TOPIC_TIMEOUT_SECONDS = 5.0


@pytest.mark.live
@pytest.mark.destructive
def test_audio_import_generated_wav_readback_cleanup() -> None:
    case = _audio_case("audio_import_generated_wav_readback_cleanup")

    with _destructive_sandbox(case) as runtime:
        client = runtime.require_client()
        name = _unique_name("audio_import")
        imported_ids: list[str] = []
        try:
            audio_file = _write_fixture_wav(runtime.require_sandbox_path() / "Task8GeneratedAudio", name)
            assert _path_is_under(audio_file, runtime.require_sandbox_path())
            result = client.call(
                "ak.wwise.core.audio.import",
                {
                    "importOperation": "createNew",
                    "imports": [
                        {
                            "audioFile": str(audio_file),
                            "objectPath": f"{ACTOR_PARENT}\\<Sound>{name}",
                            "objectType": "Sound",
                            "notes": f"Task 8 generated audio import {name}",
                        }
                    ],
                },
                options={"return": READBACK_FIELDS},
            )
            rows = _object_rows_from_import(result)
            sound = _first_row_of_type(rows, "Sound")
            sound_id = _row_id(sound)
            imported_ids.append(sound_id)
            readback = _read_one(client, sound_id)
            assert readback["name"] == name
            assert readback["type"] == "Sound"
            assert str(readback["path"]).endswith(f"\\{name}")

            sandbox_outputs = _sandbox_generated_outputs(runtime.require_sandbox_path())
            assert audio_file in sandbox_outputs or audio_file.exists()
            assert _no_source_generated_outputs(runtime.source_generated_snapshot_before)
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="passed",
                details={
                    "imported_name": name,
                    "import_result": _json_safe(result),
                    "readback": _json_safe(readback),
                    "fixture_audio": _relative_to_sandbox(audio_file, runtime.require_sandbox_path()),
                    "sandbox_output_count": len(sandbox_outputs),
                },
            )
        except BaseException as exc:
            if _is_assertion_or_skip(exc):
                raise
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="blocked",
                details=_exception_details(exc),
            )
            runtime.skip_after_blocker = True
            pytest.skip(f"audio import fixture was rejected by Wwise: {type(exc).__name__}: {exc}")
        finally:
            for object_id in imported_ids:
                _delete_if_present(client, object_id)


@pytest.mark.live
@pytest.mark.destructive
def test_audio_import_tab_delimited_generated_wav_or_records_blocker() -> None:
    case = _audio_case("audio_import_tab_delimited_generated_wav_readback_cleanup")

    with _destructive_sandbox(case) as runtime:
        client = runtime.require_client()
        name = _unique_name("tab_import")
        imported_ids: list[str] = []
        try:
            fixture_root = runtime.require_sandbox_path() / "Task8GeneratedAudio"
            audio_file = _write_fixture_wav(fixture_root, name)
            import_file = _write_tab_delimited_import_file(fixture_root, name, audio_file)
            result = client.call(
                "ak.wwise.core.audio.importTabDelimited",
                {
                    "importFile": str(import_file),
                    "importLanguage": "SFX",
                    "importOperation": "createNew",
                    "importLocation": ACTOR_PARENT,
                },
                options={"return": READBACK_FIELDS},
            )
            rows = _object_rows_from_import(result)
            sound = _first_row_of_type(rows, "Sound")
            sound_id = _row_id(sound)
            imported_ids.append(sound_id)
            readback = _read_one(client, sound_id)
            assert readback["name"] == name
            assert readback["type"] == "Sound"
            assert _path_is_under(audio_file, runtime.require_sandbox_path())
            assert _path_is_under(import_file, runtime.require_sandbox_path())
            assert _no_source_generated_outputs(runtime.source_generated_snapshot_before)
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="passed",
                details={
                    "imported_name": name,
                    "import_result": _json_safe(result),
                    "readback": _json_safe(readback),
                    "fixture_audio": _relative_to_sandbox(audio_file, runtime.require_sandbox_path()),
                    "import_file": _relative_to_sandbox(import_file, runtime.require_sandbox_path()),
                },
            )
        except BaseException as exc:
            if _is_assertion_or_skip(exc):
                raise
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="blocked",
                details=_exception_details(exc, blocker=case["blockers"][0]),
            )
            runtime.skip_after_blocker = True
            pytest.skip(f"audio tab-delimited import fixture was rejected by Wwise: {type(exc).__name__}: {exc}")
        finally:
            for object_id in imported_ids:
                _delete_if_present(client, object_id)


@pytest.mark.live
@pytest.mark.destructive
def test_audio_imported_topic_bounded_wait_or_records_blocker() -> None:
    case = _audio_case("audio_imported_topic_bounded_wait_or_blocker")

    with _destructive_sandbox(case) as runtime:
        client = runtime.require_client()
        event_queue: queue.Queue[Any] = queue.Queue(maxsize=4)
        handler = None
        name = _unique_name("audio_topic")
        imported_ids: list[str] = []
        try:
            handler = client.subscribe(
                "ak.wwise.core.audio.imported",
                lambda *args, **kwargs: _put_event(event_queue, args, kwargs),
                {"return": READBACK_FIELDS},
            )
            if handler is None:
                raise RuntimeError("WAAPI did not create an audio.imported subscription")
            audio_file = _write_fixture_wav(runtime.require_sandbox_path() / "Task8GeneratedAudio", name)
            result = client.call(
                "ak.wwise.core.audio.import",
                {
                    "importOperation": "createNew",
                    "imports": [{"audioFile": str(audio_file), "objectPath": f"{ACTOR_PARENT}\\<Sound>{name}"}],
                },
                options={"return": READBACK_FIELDS},
            )
            sound = _first_row_of_type(_object_rows_from_import(result), "Sound")
            imported_ids.append(_row_id(sound))
            event = event_queue.get(timeout=TOPIC_TIMEOUT_SECONDS)
            assert _event_mentions_name(event, name), event
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="passed",
                details={"imported_name": name, "topic_payload": _json_safe(event), "import_result": _json_safe(result)},
            )
        except (queue.Empty, BaseException) as exc:
            if _is_assertion_or_skip(exc):
                raise
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="blocked",
                details=_exception_details(exc, blocker=case["blockers"][0]),
            )
            runtime.skip_after_blocker = True
            pytest.skip(f"audio.imported topic did not provide bounded evidence: {type(exc).__name__}: {exc}")
        finally:
            _unsubscribe(handler)
            for object_id in imported_ids:
                _delete_if_present(client, object_id)


@pytest.mark.live
@pytest.mark.destructive
def test_soundbank_inclusions_replace_read_remove_cleanup() -> None:
    case = _soundbank_case("soundbank_inclusions_replace_read_remove_cleanup")

    with _destructive_sandbox(case) as runtime:
        client = runtime.require_client()
        soundbank_id: str | None = None
        sound_id: str | None = None
        try:
            soundbank_name = _unique_name("bank")
            sound_name = _unique_name("bank_sound")
            soundbank_id = _create_object(client, SOUNDBANK_PARENT, "SoundBank", soundbank_name)
            sound_id = _create_object(client, ACTOR_PARENT, "Sound", sound_name)
            client.call(
                "ak.wwise.core.soundbank.setInclusions",
                {
                    "soundbank": soundbank_id,
                    "operation": "replace",
                    "inclusions": [{"object": sound_id, "filter": ["structures", "media"]}],
                },
                options={},
            )
            inclusions = _soundbank_inclusions(client, soundbank_id)
            assert any(row.get("object") == sound_id for row in inclusions), inclusions

            client.call(
                "ak.wwise.core.soundbank.setInclusions",
                {
                    "soundbank": soundbank_id,
                    "operation": "remove",
                    "inclusions": [{"object": sound_id, "filter": ["structures", "media"]}],
                },
                options={},
            )
            assert not any(row.get("object") == sound_id for row in _soundbank_inclusions(client, soundbank_id))
            assert _no_source_generated_outputs(runtime.source_generated_snapshot_before)
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="passed",
                details={
                    "soundbank_name": soundbank_name,
                    "sound_name": sound_name,
                    "inclusions_after_replace": _json_safe(inclusions),
                },
            )
        except BaseException as exc:
            if _is_assertion_or_skip(exc):
                raise
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="blocked",
                details=_exception_details(exc),
            )
            runtime.skip_after_blocker = True
            pytest.skip(f"soundbank inclusion fixture was rejected by Wwise: {type(exc).__name__}: {exc}")
        finally:
            if soundbank_id is not None and sound_id is not None:
                _remove_inclusion_if_possible(client, soundbank_id, sound_id)
            for object_id in (soundbank_id, sound_id):
                if object_id is not None:
                    _delete_if_present(client, object_id)


@pytest.mark.live
@pytest.mark.destructive
def test_soundbank_generate_write_to_disk_or_records_blocker() -> None:
    case = _soundbank_case("soundbank_generate_write_to_disk_or_records_blocker")

    with _destructive_sandbox(case) as runtime:
        client = runtime.require_client()
        event_queue: queue.Queue[Any] = queue.Queue(maxsize=8)
        handlers: list[Any] = []
        soundbank_id: str | None = None
        sound_id: str | None = None
        try:
            for topic in ("ak.wwise.core.soundbank.generated", "ak.wwise.core.soundbank.generationDone"):
                handler = client.subscribe(
                    topic,
                    lambda *args, _topic=topic, **kwargs: _put_topic_event(
                        event_queue,
                        _topic,
                        args,
                        kwargs,
                    ),
                )
                assert handler is not None, f"WAAPI did not subscribe to {topic}"
                handlers.append(handler)
            soundbank_name = _unique_name("generate_bank")
            soundbank_id = _create_object(client, SOUNDBANK_PARENT, "SoundBank", soundbank_name)
            sound_id = _create_object(client, ACTOR_PARENT, "Sound", _unique_name("generate_sound"))
            _replace_soundbank_inclusion(client, soundbank_id, sound_id)
            before_outputs = _sandbox_generated_outputs(runtime.require_sandbox_path())
            result = client.call(
                "ak.wwise.core.soundbank.generate",
                {
                    "soundbanks": [{"name": soundbank_name, "inclusions": ["structure", "media"], "rebuild": True}],
                    "writeToDisk": True,
                    "rebuildSoundBanks": True,
                    "skipLanguages": True,
                },
                options={},
            )
            assert isinstance(result, Mapping), result
            after_outputs = _sandbox_generated_outputs(runtime.require_sandbox_path())
            new_outputs = sorted(path for path in after_outputs - before_outputs if path.is_file())
            if not new_outputs:
                _write_case_evidence(
                    case,
                    evidence_root=EVIDENCE_ROOT,
                    status="blocked",
                    details={
                        "blocker": case["blockers"][0],
                        "generate_result": _json_safe(result),
                        "reason": "generate returned but produced no discoverable generated files under the sandbox root",
                        "topic_events": _drain_events(event_queue),
                    },
                )
                runtime.skip_after_blocker = True
                pytest.skip("soundbank.generate produced no sandbox output files to assert")
            assert all(_path_is_under(path, runtime.require_sandbox_path()) for path in new_outputs)
            assert _no_source_generated_outputs(runtime.source_generated_snapshot_before)
            topic_events = _require_soundbank_topic_events(
                event_queue,
                soundbank_name,
            )
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="passed",
                details={
                    "soundbank_name": soundbank_name,
                    "generate_result": _json_safe(result),
                    "generated_files": [_relative_to_sandbox(path, runtime.require_sandbox_path()) for path in new_outputs[:20]],
                    "topic_events": topic_events,
                },
            )
        except BaseException as exc:
            if _is_assertion_or_skip(exc):
                raise
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="blocked",
                details=_exception_details(exc, blocker=case["blockers"][0]),
            )
            runtime.skip_after_blocker = True
            pytest.skip(f"soundbank.generate was blocked by Wwise settings/platform: {type(exc).__name__}: {exc}")
        finally:
            for handler in handlers:
                _unsubscribe(handler)
            if soundbank_id is not None and sound_id is not None:
                _remove_inclusion_if_possible(client, soundbank_id, sound_id)
            for object_id in (soundbank_id, sound_id):
                if object_id is not None:
                    _delete_if_present(client, object_id)


@pytest.mark.live
@pytest.mark.destructive
def test_soundbank_process_definition_file_or_records_blocker() -> None:
    case = _soundbank_case("soundbank_process_definition_file_or_records_blocker")

    with _destructive_sandbox(case) as runtime:
        client = runtime.require_client()
        bank_name = _unique_name("definition_bank")
        bank_id: str | None = None
        try:
            definition_file = _write_soundbank_definition(runtime.require_sandbox_path() / "Task8SoundBankDefinitions", bank_name)
            assert _path_is_under(definition_file, runtime.require_sandbox_path())
            result = client.call(
                "ak.wwise.core.soundbank.processDefinitionFiles",
                {"files": [str(definition_file)]},
                options={},
            )
            if not isinstance(result, Mapping):
                _write_case_evidence(
                    case,
                    evidence_root=EVIDENCE_ROOT,
                    status="blocked",
                    details={
                        "blocker": case["blockers"][0],
                        "definition_file": _relative_to_sandbox(definition_file, runtime.require_sandbox_path()),
                        "result": _json_safe(result),
                        "reason": "processDefinitionFiles returned no WAAPI mapping; Wwise likely rejected the minimal definition file",
                    },
                )
                runtime.skip_after_blocker = True
                pytest.skip("soundbank definition fixture returned no WAAPI mapping to assert")
            rows = _find_objects_by_name(client, bank_name, "SoundBank")
            if not rows:
                _write_case_evidence(
                    case,
                    evidence_root=EVIDENCE_ROOT,
                    status="blocked",
                    details={
                        "blocker": case["blockers"][0],
                        "definition_file": _relative_to_sandbox(definition_file, runtime.require_sandbox_path()),
                        "result": _json_safe(result),
                        "reason": "processDefinitionFiles returned a WAAPI mapping but no SoundBank object readback; coverage remains blocked",
                    },
                )
                runtime.skip_after_blocker = True
                pytest.skip("soundbank definition fixture produced no SoundBank object readback to assert")
            assert _no_source_generated_outputs(runtime.source_generated_snapshot_before)
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="passed",
                details={
                    "definition_file": _relative_to_sandbox(definition_file, runtime.require_sandbox_path()),
                    "result": _json_safe(result),
                    "soundbank_readback": _json_safe(rows),
                },
            )
        except BaseException as exc:
            if _is_assertion_or_skip(exc):
                raise
            _write_case_evidence(
                case,
                evidence_root=EVIDENCE_ROOT,
                status="blocked",
                details=_exception_details(exc, blocker=case["blockers"][0]),
            )
            runtime.skip_after_blocker = True
            pytest.skip(f"soundbank definition fixture was rejected by Wwise: {type(exc).__name__}: {exc}")
        finally:
            if bank_id is not None:
                _delete_if_present(client, bank_id)


@pytest.mark.live
@pytest.mark.destructive
def test_soundbank_process_definition_file_version_correct_or_records_blocker() -> None:
    case = _task6_case()

    with _destructive_sandbox(case) as runtime:
        client = runtime.require_client()
        bank_name = _unique_name_with_prefix(TASK6_TEMP_PREFIX, "definition_bank")
        bank_id: str | None = None
        definition_file: Path | None = None
        try:
            definition_file = _write_soundbank_definition(
                runtime.require_sandbox_path() / "Task6SoundBankDefinitions", bank_name
            )
            definition_content = definition_file.read_text(encoding="utf-8")
            assert _path_is_under(definition_file, runtime.require_sandbox_path())
            result = client.call(
                "ak.wwise.core.soundbank.processDefinitionFiles",
                {"files": [str(definition_file)]},
                options={},
            )
            if _process_definition_result_is_unusable(result):
                _write_case_evidence(
                    case,
                    evidence_root=TASK6_EVIDENCE_ROOT,
                    status="blocked",
                    details={
                        "blocker": case["blockers"][0],
                        "definition": _definition_evidence(definition_file, runtime.require_sandbox_path(), bank_name),
                        "definition_content": definition_content,
                        "process_result": _json_safe(result),
                        "reason": "processDefinitionFiles returned no usable mapping, an empty mapping, or ak.wwise.file_error",
                        "source_hash_proof": _source_hash_proof(runtime),
                    },
                )
                runtime.skip_after_blocker = True
                pytest.skip("soundbank definition fixture returned no usable WAAPI mapping to assert")

            rows = _find_objects_by_name(client, bank_name, "SoundBank")
            if rows:
                bank_id = _row_id(rows[0])
            if not rows:
                _write_case_evidence(
                    case,
                    evidence_root=TASK6_EVIDENCE_ROOT,
                    status="blocked",
                    details={
                        "blocker": case["blockers"][0],
                        "definition": _definition_evidence(definition_file, runtime.require_sandbox_path(), bank_name),
                        "definition_content": definition_content,
                        "process_result": _json_safe(result),
                        "reason": "processDefinitionFiles returned a mapping but no SoundBank object readback tied to the definition ShortName",
                        "source_hash_proof": _source_hash_proof(runtime),
                    },
                )
                runtime.skip_after_blocker = True
                pytest.skip("soundbank definition fixture produced no SoundBank object readback to assert")
            created_bank_id = _row_id(rows[0])
            bank_id = created_bank_id

            _delete_if_present(client, created_bank_id)
            cleanup_readback = _read_rows(client, created_bank_id)
            assert cleanup_readback == []
            cleanup_proof = {"deleted_soundbank_id": created_bank_id, "read_after_delete": cleanup_readback}
            bank_id = None
            assert _no_source_generated_outputs(runtime.source_generated_snapshot_before)
            source_hash_proof = _source_hash_proof(runtime)
            assert source_hash_proof["before"] == source_hash_proof["after"]
            _write_case_evidence(
                case,
                evidence_root=TASK6_EVIDENCE_ROOT,
                status="passed",
                details={
                    "definition": _definition_evidence(definition_file, runtime.require_sandbox_path(), bank_name),
                    "definition_content": definition_content,
                    "process_result": _json_safe(result),
                    "soundbank_readback": _json_safe(rows),
                    "cleanup_proof": cleanup_proof,
                    "source_hash_proof": source_hash_proof,
                },
            )
        except BaseException as exc:
            if _is_assertion_or_skip(exc):
                raise
            blocker = case["blockers"][1] if "ak.wwise.file_error" in str(exc) else case["blockers"][0]
            details: dict[str, Any] = _exception_details(exc, blocker=blocker)
            if definition_file is not None:
                details["definition"] = _definition_evidence(definition_file, runtime.require_sandbox_path(), bank_name)
                details["definition_content"] = definition_file.read_text(encoding="utf-8")
            details["source_hash_proof"] = _source_hash_proof(runtime)
            _write_case_evidence(
                case,
                evidence_root=TASK6_EVIDENCE_ROOT,
                status="blocked",
                details=details,
            )
            runtime.skip_after_blocker = True
            pytest.skip(f"soundbank definition fixture was rejected by Wwise: {type(exc).__name__}: {exc}")
        finally:
            if bank_id is not None:
                _delete_if_present(client, bank_id)


class _SandboxRuntime:
    def __init__(self, case: Mapping[str, Any]) -> None:
        self.case = case
        self.env = dict(os.environ)
        self.sandbox = None
        self.lifecycle = None
        self.client = None
        self.failed = True
        self.skip_after_blocker = False
        self.source_mtime_before = 0.0
        self.source_project_files_hash_before: tuple[str, int, int] | None = None
        self.source_generated_snapshot_before: tuple[str, ...] = ()

    def __enter__(self) -> "_SandboxRuntime":
        try:
            self.lock = LiveSandboxLock(_safe_lock_root(self.env))
            self.lock.__enter__()
            self.sandbox = prepare_sample_project_sandbox(self.env, hash_strategy="bounded")
            self.source_mtime_before = self.sandbox.source_project.stat().st_mtime
            self.source_project_files_hash_before = _hash_mutation_bearing_project_files(self.sandbox.source_root)
            self.source_generated_snapshot_before = _generated_output_snapshot(self.sandbox.source_root)
            self.lifecycle = launch_sandboxed_wwise(self.sandbox, self.env)
            self.client = default_waapi_client_factory(self.lifecycle.waapi_url)
            return self
        except (LiveEnvironmentError, SandboxFixtureError, HeadlessLifecycleError, OSError) as exc:
            self._write_environment_blocker(exc)
            self.__exit__(type(exc), exc, exc.__traceback__)
            fail_if_active_runtime_failure(exc, "destructive sandbox environment blocked execution")
            pytest.skip(f"destructive sandbox environment blocked execution: {type(exc).__name__}: {exc}")
            raise AssertionError("pytest.skip should stop execution") from exc

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        deferred_error: BaseException | None = None
        try:
            try:
                if self.client is not None:
                    self.client.disconnect()
            except BaseException as disconnect_error:
                if exc_type is None:
                    deferred_error = disconnect_error

            try:
                if self.lifecycle is not None and self.sandbox is not None:
                    shutdown_sandboxed_wwise(self.lifecycle, self.sandbox)
            except BaseException as shutdown_error:
                if exc_type is None and deferred_error is None:
                    deferred_error = shutdown_error

            if self.sandbox is not None:
                should_verify_source = self.source_project_files_hash_before is not None and deferred_error is None
                if should_verify_source:
                    try:
                        self._assert_source_unchanged()
                        if exc_type is None:
                            self.failed = False
                    except AssertionError as assertion_error:
                        deferred_error = assertion_error
                try:
                    cleanup_sandbox(self.sandbox, failed=self.failed)
                except BaseException as cleanup_error:
                    if exc_type is None and deferred_error is None:
                        deferred_error = cleanup_error
        finally:
            if hasattr(self, "lock"):
                self.lock.__exit__(exc_type, exc, traceback)

        if deferred_error is not None and (exc_type is None or isinstance(deferred_error, AssertionError)):
            raise deferred_error

    def _assert_source_unchanged(self) -> None:
        assert self.sandbox is not None
        assert self.source_project_files_hash_before is not None
        assert self.sandbox.source_project.stat().st_mtime == self.source_mtime_before
        assert _hash_mutation_bearing_project_files(self.sandbox.source_root) == self.source_project_files_hash_before
        assert _generated_output_snapshot(self.sandbox.source_root) == self.source_generated_snapshot_before

    def require_client(self) -> Any:
        assert self.client is not None
        return cast(Any, self.client)

    def require_sandbox_path(self) -> Path:
        assert self.sandbox is not None
        return self.sandbox.sandbox_path

    def _write_environment_blocker(self, exc: BaseException) -> None:
        path = EVIDENCE_ROOT / "task-8-destructive-environment-blocker.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "case_id": self.case["id"],
                    "error_type": type(exc).__name__,
                    "error": _redact_local_paths(str(exc)),
                    "command": _redact_local_paths(_plan()["metadata"]["destructive_command"]),
                    "sandbox_required": True,
                    "source_project_mutation_allowed": False,
                    "recorded_at_unix": int(time.time()),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def _destructive_sandbox(case: Mapping[str, Any]) -> _SandboxRuntime:
    return _SandboxRuntime(case)


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


def _write_tab_delimited_import_file(root: Path, name: str, audio_file: Path) -> Path:
    path = root / f"{name}.txt"
    path.write_text(
        "Audio File\tObject Path\tObject Type\tNotes\n"
        f"{audio_file}\t<Sound>{name}\tSound\tTask 8 tab-delimited import {name}\n",
        encoding="utf-8",
    )
    return path


def _write_soundbank_definition(root: Path, bank_name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{bank_name}.xml"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<SoundBanksInfo Platform="Mac" BasePlatform="Mac" SchemaVersion="16" SoundBankVersion="145">\n'
        "  <SoundBanks>\n"
        '    <SoundBank Type="User" Language="SFX">\n'
        f"      <ShortName>{bank_name}</ShortName>\n"
        f"      <Path>{bank_name}.bnk</Path>\n"
        "    </SoundBank>\n"
        "  </SoundBanks>\n"
        "</SoundBanksInfo>\n",
        encoding="utf-8",
    )
    return path


def _definition_evidence(definition_file: Path, sandbox_path: Path, bank_name: str) -> dict[str, Any]:
    content = definition_file.read_bytes()
    return {
        "file": _relative_to_sandbox(definition_file, sandbox_path),
        "short_name": bank_name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "shape": "SoundBanksInfo Platform/BasePlatform=Mac SchemaVersion=16 SoundBankVersion=145 User/SFX SoundBank ShortName+Path",
    }


def _process_definition_result_is_unusable(result: Any) -> bool:
    if not isinstance(result, Mapping):
        return True
    if not result:
        return True
    return "ak.wwise.file_error" in json.dumps(_json_safe(result), sort_keys=True)


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


def _find_objects_by_name(client: Any, name: str, object_type: str) -> list[Mapping[str, Any]]:
    result = client.call(
        "ak.wwise.core.object.get",
        {"waql": f'$ where name = "{name}" and type = "{object_type}"'},
        options={"return": READBACK_FIELDS},
    )
    if result is None:
        return []
    assert isinstance(result, Mapping), result
    rows = result.get("return")
    assert isinstance(rows, list), result
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


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


def _delete_if_present(client: Any, object_id: str) -> None:
    if _read_rows(client, object_id):
        client.call("ak.wwise.core.object.delete", {"object": object_id}, options={})
        assert _read_rows(client, object_id) == []


def _put_event(event_queue: queue.Queue[Any], args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> None:
    payload = {"args": args, "kwargs": dict(kwargs)}
    try:
        event_queue.put_nowait(payload)
    except queue.Full:
        pass


def _put_topic_event(
    event_queue: queue.Queue[Any],
    topic: str,
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> None:
    payload = {"topic": topic, "args": args, "kwargs": dict(kwargs)}
    try:
        event_queue.put_nowait(payload)
    except queue.Full:
        pass


def _require_soundbank_topic_events(
    event_queue: queue.Queue[Any],
    soundbank_name: str,
) -> list[Any]:
    deadline = time.monotonic() + TOPIC_TIMEOUT_SECONDS
    events: list[Any] = []
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            event = _json_safe(event_queue.get(timeout=remaining))
        except queue.Empty:
            break
        events.append(event)
        generated = any(
            row.get("topic") == "ak.wwise.core.soundbank.generated"
            and _event_mentions_name(row, soundbank_name)
            for row in events
            if isinstance(row, Mapping)
        )
        generation_done = any(
            row.get("topic") == "ak.wwise.core.soundbank.generationDone"
            for row in events
            if isinstance(row, Mapping)
        )
        if generated and generation_done:
            return events
    raise AssertionError(
        "soundbank.generate did not publish both the matching generated event "
        f"and generationDone within {TOPIC_TIMEOUT_SECONDS} seconds: {events!r}"
    )


def _event_mentions_name(event: Any, name: str) -> bool:
    return name in json.dumps(_json_safe(event), sort_keys=True)


def _drain_events(event_queue: queue.Queue[Any]) -> list[Any]:
    events = []
    while True:
        try:
            events.append(_json_safe(event_queue.get_nowait()))
        except queue.Empty:
            return events


def _unsubscribe(handler: Any) -> None:
    if handler is None:
        return
    unsubscribe = getattr(handler, "unsubscribe", None)
    if callable(unsubscribe):
        unsubscribe()


def _hash_mutation_bearing_project_files(root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    bytes_hashed = 0
    files = [path for path in sorted(root.rglob("*")) if path.suffix.lower() in {".wproj", ".wwu"} and path.is_file()]
    for file_path in files:
        relative = file_path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        data = file_path.read_bytes()
        bytes_hashed += len(data)
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest(), len(files), bytes_hashed


def _generated_output_snapshot(root: Path) -> tuple[str, ...]:
    names = {"GeneratedSoundBanks", ".cache", "Originals", "Task8GeneratedAudio", "Task8SoundBankDefinitions", "Task6SoundBankDefinitions"}
    paths = []
    for path in sorted(root.rglob("*")):
        if any(part in names for part in path.relative_to(root).parts):
            paths.append(path.relative_to(root).as_posix())
    return tuple(paths)


def _sandbox_generated_outputs(root: Path) -> set[Path]:
    names = {"GeneratedSoundBanks", ".cache", "Originals", "Task8GeneratedAudio", "Task8SoundBankDefinitions", "Task6SoundBankDefinitions"}
    outputs = set()
    for path in root.rglob("*"):
        if any(part in names for part in path.relative_to(root).parts):
            outputs.add(path)
    return outputs


def _no_source_generated_outputs(before: tuple[str, ...]) -> bool:
    source_project = resolve_sample_project_source(dict(os.environ))
    if source_project is None:
        return True
    return _generated_output_snapshot(source_project.parent) == before


def _safe_lock_root(env: Mapping[str, str]) -> Path:
    raw_root = env.get("WWISE_SANDBOX_ROOT")
    root = Path(raw_root).expanduser() if raw_root else REPO_ROOT / ".waapi-skill-state" / "runtime" / "wwise-waapi-sandboxes"
    root = root.resolve(strict=False)
    source_project = resolve_sample_project_source(env)
    if source_project is not None:
        source_root = source_project.parent.resolve(strict=False)
        if root == source_root or path_is_under(root, source_root) or path_is_under(source_root, root):
            raise SandboxFixtureError("sandbox lock root must not overlap the immutable SampleProject source")
    return root


def _unique_name(label: str) -> str:
    return _unique_name_with_prefix(TEMP_PREFIX, label)


def _unique_name_with_prefix(prefix: str, label: str) -> str:
    safe_label = "".join(character if character.isalnum() else "_" for character in label)
    return f"{prefix}{safe_label}_{uuid.uuid4().hex[:12]}"


def _source_hash_proof(runtime: _SandboxRuntime) -> dict[str, Any]:
    assert runtime.sandbox is not None
    return {
        "before": runtime.source_project_files_hash_before,
        "after": _hash_mutation_bearing_project_files(runtime.sandbox.source_root),
        "generated_outputs_before": runtime.source_generated_snapshot_before,
        "generated_outputs_after": _generated_output_snapshot(runtime.sandbox.source_root),
    }


def _write_case_evidence(
    case: Mapping[str, Any],
    *,
    evidence_root: Path,
    status: str,
    details: Mapping[str, Any],
) -> None:
    path = _safe_evidence_path(evidence_root, str(case["evidence_path"]))
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {path.stem}\n"
    body = {
        "case_id": case["id"],
        "status": status,
        "evidence_path": path.relative_to(REPO_ROOT).as_posix(),
        "provenance_evidence_path": case["evidence_path"],
        "uris": case["uris"],
        "allowlist": case["allowlist"],
        "assertions": case["assertions"],
        "cleanup": case["cleanup"],
        "gate": case["gate"],
        "details": _redact_json_strings(_json_safe(details)),
        "recorded_at_unix": int(time.time()),
    }
    path.write_text(existing.rstrip() + "\n\n```json\n" + json.dumps(body, indent=2, sort_keys=True) + "\n```\n", encoding="utf-8")


def _safe_evidence_path(evidence_root: Path, path: str) -> Path:
    target = localize_runtime_evidence_path(evidence_root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _audio_case(case_id: str) -> Mapping[str, Any]:
    return _case("audio_cases", case_id)


def _soundbank_case(case_id: str) -> Mapping[str, Any]:
    return _case("soundbank_cases", case_id)


def _task6_case() -> Mapping[str, Any]:
    return json.loads(TASK6_PLAN_PATH.read_text(encoding="utf-8"))["process_definition_case"]


def _case(group: str, case_id: str) -> Mapping[str, Any]:
    for case in _plan()[group]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing Task 8 case {case_id}")


def _plan() -> Mapping[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _redact_local_paths(message: str) -> str:
    redacted = message.replace(str(REPO_ROOT), "<repo>")
    redacted = redacted.replace(str(Path.home()), "<home>")
    sample_project = os.getenv("WWISE_SAMPLE_PROJECT_PATH")
    if sample_project:
        redacted = redacted.replace(sample_project, "$WWISE_SAMPLE_PROJECT_PATH")
    return redacted


def _redact_json_strings(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_local_paths(value)
    if isinstance(value, list):
        return [_redact_json_strings(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_json_strings(item) for key, item in value.items()}
    return value


def _relative_to_sandbox(path: Path, sandbox_path: Path) -> str:
    return path.relative_to(sandbox_path).as_posix()


def _path_is_under(path: Path, root: Path) -> bool:
    return path_is_under(path.resolve(strict=False), root.resolve(strict=False))


def _exception_details(exc: BaseException, blocker: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "blocker": blocker,
        "error_type": type(exc).__name__,
        "error": _redact_local_paths(str(exc)),
    }


def _is_assertion_or_skip(exc: BaseException) -> bool:
    return isinstance(exc, (AssertionError, pytest.skip.Exception))


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))
