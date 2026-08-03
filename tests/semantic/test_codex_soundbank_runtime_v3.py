from __future__ import annotations

import json
import shutil
import uuid
import wave
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import pytest

from tests.support.platform_filesystem import create_symlink_or_skip
from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
from tests.semantic.support.codex_compound_heavy_v1 import (
    load_compound_heavy_profile,
)
from tests.semantic.support.codex_soundbank_business_plan_v3 import (
    compile_soundbank_business_plan,
    validate_soundbank_business_plan,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    StructuredRefusal,
    build_transaction_protocol,
)
from tests.semantic.support import codex_soundbank_runtime_v3 as soundbank_runtime
from tests.semantic.support.codex_soundbank_runtime_v3 import (
    OBJECT_FIELDS,
    PROCESS_REFUSAL_ERROR_CODE,
    PROCESS_REFUSAL_ID,
    SOUNDBANK_APIS,
    SOUNDBANK_TOPIC,
    SOUNDBANK_TOPIC_RETURN_FIELDS,
    ClosedDirectWaapiSoundBankBackend,
    EFFECT_TEMPLATE_PATH,
    EventGraphState,
    EXPECTED_SCENARIO_COUNT,
    MaterializedSoundBankCase,
    MEDIA_OBJECT_FIELDS,
    MEDIA_SOURCE_FIELDS,
    MediaFixture,
    ObjectFixture,
    PreparedSoundBankRuntime,
    SoundBankBlueprint,
    SoundBankRuntimeError,
    TopicExpectedEvent,
    build_soundbank_blueprint,
    verify_topic_payloads,
)
from wwise_waapi.operation_registry import parse_operation_request
from wwise_waapi.operation_soundbank import parse_soundbank_definition_file


REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_V3 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"
COMPOUND_PROFILE = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "compound-heavy-v1"
    / "profile.json"
)
QUERY_REFERENCE = (
    REPO_ROOT / "skills" / "waapi-skill" / "references" / "waapi-query.md"
)


def _guid(label: str) -> str:
    return "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"waapi-v3:{label}")).upper() + "}"


class FakeSoundBankBackend:
    def __init__(self, blueprint: SoundBankBlueprint) -> None:
        self.blueprint = blueprint
        self.rows: dict[str, dict[str, Any]] = {}
        self.by_path: dict[str, str] = {}
        self.inclusions: dict[str, list[dict[str, Any]]] = {}
        self.event_graphs: dict[str, EventGraphState] = {}
        self.localized_sources: dict[tuple[str, str], str] = {}
        self.next_short = 1000
        self.next_media = 700_000
        self.omit_conversion_short_id = False
        self.omit_source_media_id = False
        self.omit_source_from_import_result = False
        self.add_second_source_to_import_result = False
        self.use_wrong_source_parent = False
        self.replace_sound_on_localized_reuse = False
        self.replace_action_on_localized_reuse = False
        self.wrong_source_language = False
        self.wrong_active_source = False
        self.corrupt_copied_wav = False
        self.escape_copied_path = False
        self.symlink_copied_path = False
        self.refuse_delete = False
        self.calls: list[tuple[str, Any]] = []
        self.project_info = _project_info(blueprint)
        for fixture in blueprint.object_fixtures:
            if not fixture.owned:
                self._insert(
                    fixture.path,
                    fixture.name,
                    soundbank_runtime.get_codex_version_layout_v3(
                        blueprint.version
                    ).reflected_type(fixture.object_type),
                )

    def _insert(self, path: str, name: str, object_type: str) -> str:
        if path.casefold() in self.by_path:
            return self.by_path[path.casefold()]
        object_id = _guid(path)
        self.next_short += 1
        self.rows[object_id.casefold()] = {
            "id": object_id,
            "name": name,
            "type": object_type,
            "path": path,
            "parent": None,
            "shortId": self.next_short,
            "notes": "",
        }
        self.by_path[path.casefold()] = object_id
        return object_id

    def get_project_info(self) -> Mapping[str, Any]:
        return self.project_info

    def read_objects(
        self,
        *,
        path: str | None = None,
        object_id: str | int | None = None,
        object_type: str | None = None,
        name: str | None = None,
        fields: Sequence[str] = OBJECT_FIELDS,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        if path is not None:
            identity = self.by_path.get(path.casefold())
            candidates = [] if identity is None else [self.rows[identity.casefold()]]
        elif object_id is not None:
            row = self.rows.get(str(object_id).casefold())
            candidates = [] if row is None else [row]
        else:
            candidates = [
                row
                for row in self.rows.values()
                if row["type"] == object_type and row["name"] == name
            ]
        requested_language = (
            soundbank_runtime._canonical_language(language)
            if language is not None
            else None
        )
        projected: list[Mapping[str, Any]] = []
        for raw_row in candidates:
            row = dict(raw_row)
            if requested_language is not None and str(row.get("type", "")).startswith(
                "Sound"
            ):
                source_id = self.localized_sources.get(
                    (str(row["path"]).casefold(), requested_language.casefold())
                )
                if source_id is None:
                    continue
                source = self.rows[source_id.casefold()]
                row["activeSource"] = {"id": source_id}
                row["audioSource:language"] = source["audioSource:language"]
                row["sound:originalWavFilePath"] = source["originalFilePath"]
            elif requested_language is not None and row.get("type") in {
                "AudioFileSource",
                "Audio Source",
            }:
                actual = row.get("audioSource:language")
                actual_name = actual.get("name") if isinstance(actual, Mapping) else actual
                # Keep a deliberately malformed/wrong-language row visible to
                # the oracle so it can report the exact binding mismatch.
                if not isinstance(actual_name, str):
                    pass
            projected.append({key: row.get(key) for key in fields})
        return tuple(projected)

    def create_object(self, fixture: ObjectFixture) -> str:
        if fixture.path.casefold() in self.by_path:
            raise AssertionError(f"duplicate fake fixture path {fixture.path}")
        object_id = self._insert(
            fixture.path,
            fixture.name,
            soundbank_runtime.get_codex_version_layout_v3(
                self.blueprint.version
            ).reflected_type(fixture.object_type),
        )
        if self.omit_conversion_short_id and fixture.object_type == "Conversion":
            self.rows[object_id.casefold()].pop("shortId")
        if fixture.object_type == "SoundBank":
            self.inclusions[object_id.casefold()] = []
        self.calls.append(("create", fixture.key))
        return object_id

    def import_media(self, fixture: Any) -> tuple[str, ...]:
        existing_sound_id = self.by_path.get(fixture.sound_path.casefold())
        existing_event_id = self.by_path.get(fixture.event_path.casefold())
        if fixture.import_operation == "createNew":
            assert existing_sound_id is None and existing_event_id is None
            assert fixture.create_event
            sound_id = self._insert(
                fixture.sound_path,
                fixture.sound_path.rsplit("\\", 1)[-1],
                "Sound Voice" if fixture.language != "SFX" else "Sound SFX",
            )
            event_id = self._insert(
                fixture.event_path,
                fixture.event_path.rsplit("\\", 1)[-1],
                "Event",
            )
            action_id = _guid(f"{fixture.event_path}@Play")
            self.event_graphs[fixture.event_path.casefold()] = EventGraphState(
                event_id,
                (action_id,),
                (sound_id,),
                (1,),
            )
        else:
            assert fixture.import_operation == "useExisting"
            assert not fixture.create_event
            assert existing_sound_id is not None and existing_event_id is not None
            sound_id = existing_sound_id
            event_id = existing_event_id
            if self.replace_sound_on_localized_reuse:
                old = self.rows.pop(sound_id.casefold())
                sound_id = _guid(f"replacement:{fixture.key}")
                self.rows[sound_id.casefold()] = {**old, "id": sound_id}
                self.by_path[fixture.sound_path.casefold()] = sound_id
            if self.replace_action_on_localized_reuse:
                previous = self.event_graphs[fixture.event_path.casefold()]
                self.event_graphs[fixture.event_path.casefold()] = EventGraphState(
                    previous.event_id,
                    (_guid(f"replacement-action:{fixture.key}"),),
                    previous.target_ids,
                    previous.action_types,
                )
        source_path = fixture.sound_path + "\\AudioFileSource_" + fixture.key
        source_id = self._insert(source_path, "AudioFileSource_" + fixture.key, "AudioFileSource")
        # The real 2022.1 .wwu shape has a MediaID for AudioFileSource and no
        # object ShortID.  Model this distinction so tests cannot pass by
        # accidentally reusing the parent Sound's short ID.
        self.next_media += 1
        source_row = self.rows[source_id.casefold()]
        source_row["parent"] = {
            "id": event_id if self.use_wrong_source_parent else sound_id
        }
        if self.omit_source_media_id:
            # Deliberately retain a plausible Short ID for the negative test:
            # the runtime must still reject it instead of treating it as a
            # generated-media identity.
            source_row["shortId"] = self.next_media
            source_row.pop("mediaId", None)
        else:
            source_row.pop("shortId")
            source_row["mediaId"] = self.next_media
        copied = (
            self.blueprint.sandbox_root
            / "Originals"
            / fixture.language
            / fixture.wav_path.name
        )
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture.wav_path, copied)
        if self.corrupt_copied_wav:
            copied.write_bytes(b"corrupt-localized-copy")
        source_row["audioSource:language"] = {
            "name": "Japanese" if self.wrong_source_language else fixture.language
        }
        if self.escape_copied_path:
            source_row["originalFilePath"] = str(fixture.wav_path)
        elif self.symlink_copied_path:
            alias = copied.with_name("alias-" + copied.name)
            create_symlink_or_skip(alias, copied)
            source_row["originalFilePath"] = str(alias)
        else:
            source_row["originalFilePath"] = str(copied)
        self.localized_sources[
            (fixture.sound_path.casefold(), fixture.language.casefold())
        ] = source_id
        if self.wrong_active_source:
            decoy_path = source_path + "_active_decoy"
            decoy_id = self._insert(
                decoy_path,
                "AudioFileSource_" + fixture.key + "_active_decoy",
                "AudioFileSource",
            )
            decoy = self.rows[decoy_id.casefold()]
            decoy.pop("shortId")
            decoy.update(
                {
                    "parent": {"id": sound_id},
                    "mediaId": self.next_media + 10_000,
                    "audioSource:language": {"name": fixture.language},
                    "originalFilePath": str(copied),
                }
            )
            self.localized_sources[
                (fixture.sound_path.casefold(), fixture.language.casefold())
            ] = decoy_id
        bus_id = self.by_path[fixture.output_bus_path.casefold()]
        if fixture.import_operation == "createNew":
            self.rows[sound_id.casefold()]["OutputBus"] = {"id": bus_id}
        else:
            assert self.rows[sound_id.casefold()]["OutputBus"] == {"id": bus_id}
        self.calls.append(("import", fixture))
        imported_ids = [sound_id, event_id] if fixture.import_operation == "createNew" else []
        if not self.omit_source_from_import_result:
            imported_ids.append(source_id)
        if self.add_second_source_to_import_result:
            duplicate_path = source_path + "_duplicate"
            duplicate_id = self._insert(
                duplicate_path,
                "AudioFileSource_" + fixture.key + "_duplicate",
                "AudioFileSource",
            )
            self.next_media += 1
            duplicate_row = self.rows[duplicate_id.casefold()]
            duplicate_row.pop("shortId")
            duplicate_row["mediaId"] = self.next_media
            duplicate_row["parent"] = {"id": sound_id}
            imported_ids.append(duplicate_id)
        return tuple(imported_ids)

    def read_event_graph(self, path: str) -> EventGraphState | None:
        return self.event_graphs.get(path.casefold())

    def set_inclusions(
        self,
        soundbank_id: str,
        mode: str,
        rows: Sequence[tuple[str, Sequence[str]]],
    ) -> None:
        key = soundbank_id.casefold()
        before = {
            str(row["object"]).casefold(): dict(row)
            for row in self.inclusions.get(key, [])
        }
        requested = {
            object_id.casefold(): {
                "object": object_id,
                "filter": list(filters),
            }
            for object_id, filters in rows
        }
        if mode == "replace":
            after = requested
        elif mode == "add":
            after = {**before, **requested}
        elif mode == "remove":
            after = {name: row for name, row in before.items() if name not in requested}
        else:  # pragma: no cover - backend protocol prevents this
            raise AssertionError(mode)
        self.inclusions[key] = list(after.values())
        self.calls.append(("setInclusions", mode))

    def read_inclusions(self, soundbank_id: str) -> tuple[Mapping[str, Any], ...]:
        return tuple(dict(row) for row in self.inclusions.get(soundbank_id.casefold(), []))

    def save_project(self) -> None:
        self.calls.append(("save", None))

    def generate_for_setup(self, args: Mapping[str, Any]) -> None:
        assert args["rebuildInitBank"] is True
        requested = args["soundbanks"]
        assert isinstance(requested, list)
        if requested:
            bank_names = [str(row["name"]) for row in requested]
        else:
            # Match the real 2022.1 behavior that exposed the fixture bug:
            # an empty SoundBank list generates every user SoundBank.
            bank_names = sorted(
                str(row["name"])
                for row in self.rows.values()
                if row.get("type") == "SoundBank" and row.get("name") != "Init"
            )
        for name in args["platforms"]:
            row = next(row for row in self.project_info["platforms"] if row["name"] == name)
            root = Path(row["soundBankPath"])
            root.mkdir(parents=True, exist_ok=True)
            (root / "Init.bnk").write_bytes(b"BKHD-INIT-SEALED")
            for bank_name in bank_names:
                (root / f"{bank_name}.bnk").write_bytes(
                    b"BKHD-CONTROL-SEALED:" + bank_name.encode("utf-8")
                )
        self.calls.append(("generateInit", dict(args)))

    def delete_object(self, object_id: str) -> None:
        if self.refuse_delete:
            return
        row = self.rows.pop(object_id.casefold(), None)
        if row is None:
            return
        path = str(row["path"])
        self.by_path.pop(path.casefold(), None)
        self.event_graphs.pop(path.casefold(), None)
        # Fake object deletion mirrors Wwise's recursive child cleanup.
        descendants = [
            identity
            for identity, child in self.rows.items()
            if str(child["path"]).casefold().startswith((path + "\\").casefold())
        ]
        for identity in descendants:
            child = self.rows.pop(identity)
            self.by_path.pop(str(child["path"]).casefold(), None)
        self.inclusions.pop(object_id.casefold(), None)

    def apply_business_effect(self, case: MaterializedSoundBankCase) -> None:
        if case.blueprint.api in {
            "ak.wwise.core.soundbank.generate",
            "ak.wwise.core.soundbank.convertExternalSources",
            SOUNDBANK_TOPIC,
        }:
            for artifact in case.expected_artifacts:
                if not artifact.required_change:
                    continue
                artifact.path.parent.mkdir(parents=True, exist_ok=True)
                artifact.path.write_bytes(
                    ("V3:" + case.scenario_id + ":" + artifact.kind).encode("utf-8")
                )
                if (
                    case.blueprint.api
                    == "ak.wwise.core.soundbank.convertExternalSources"
                    and artifact.kind == "external"
                ):
                    (artifact.path.parent / "Wwise.dat").write_bytes(
                        ("INDEX:" + case.scenario_id).encode("utf-8")
                    )
            return
        if case.blueprint.api == "ak.wwise.core.soundbank.setInclusions":
            spec = case.blueprint.asset_spec
            bank = next(row for row in case.blueprint.soundbanks if row.name == spec["soundbank"])
            bank_id = self.by_path[bank.path.casefold()]
            requested = []
            for row in spec["requested"]:
                fixture = next(
                    item
                    for item in case.blueprint.object_fixtures
                    if item.key == f"inclusion:{row['object']}"
                )
                requested.append((self.by_path[fixture.path.casefold()], row["filters"]))
            self.set_inclusions(bank_id, spec["mode"], requested)
            return
        if case.blueprint.api == "ak.wwise.core.soundbank.processDefinitionFiles":
            expected: dict[str, list[tuple[str, Sequence[str]]]] = {}
            filter_map = {"Event": "events", "Structure": "structures", "Media": "media"}
            for document in case.blueprint.definitions:
                for row in document.rows:
                    if row.resolution != "unique":
                        continue
                    expected.setdefault(row.soundbank, []).append(
                        (
                            case.object_ids[row.object_key],
                            [filter_map[value] for value in row.filters],
                        )
                    )
            for bank_name, rows in expected.items():
                bank = next(item for item in case.blueprint.soundbanks if item.name == bank_name)
                self.set_inclusions(self.by_path[bank.path.casefold()], "add", rows)


def _project_info(blueprint: SoundBankBlueprint) -> dict[str, Any]:
    root = blueprint.sandbox_root
    cache = root / ".cache"
    generated = root / "GeneratedSoundBanks"
    for path in (cache, generated):
        path.mkdir(parents=True, exist_ok=True)
    platforms = []
    for name in ("Windows", "Mac"):
        bank = generated / name
        copied = bank / "Media"
        bank.mkdir(parents=True, exist_ok=True)
        copied.mkdir(parents=True, exist_ok=True)
        platforms.append(
            {
                "id": _guid("platform:" + name),
                "name": name,
                "baseName": name,
                "soundBankPath": str(bank),
                "copiedMediaPath": str(copied),
            }
        )
    return {
        "id": _guid("project:" + blueprint.scenario_id),
        "name": blueprint.sandbox_project.stem,
        "path": str(blueprint.sandbox_project),
        "isDirty": False,
        "platforms": platforms,
        "languages": [
            {"id": _guid("language:Chinese(PRC)"), "name": "Chinese(PRC)"},
            {"id": _guid("language:English(US)"), "name": "English(US)"},
            {"id": _guid("language:Japanese"), "name": "Japanese"},
            {"id": _guid("language:SFX"), "name": "SFX"},
        ],
        "defaultConversion": {"id": _guid("conversion:Default"), "name": "Default"},
        "directories": {
            "root": str(root),
            "cache": str(cache),
            "soundBankOutputRoot": str(generated),
        },
    }


def _scenarios() -> list[Any]:
    bundle = load_eval_bundle_v3(SUITE_V3)
    return [scenario for scenario in bundle.scenarios if scenario.api in SOUNDBANK_APIS]


def _unprepared_runtime(
    tmp_path: Path,
    scenario: Any,
    *,
    version: str = "2022.1",
) -> tuple[PreparedSoundBankRuntime, FakeSoundBankBackend]:
    owned = tmp_path / "owned"
    project_root = owned / "sandbox" / "SampleProject"
    project_root.mkdir(parents=True)
    project = project_root / "SampleProject.wproj"
    project.write_text("<Project/>\n", encoding="utf-8")
    (project_root / "Default Work Unit.wwu").write_text("<WorkUnit/>\n", encoding="utf-8")
    blueprint = build_soundbank_blueprint(
        scenario,
        version=version,
        sandbox_project=project,
        io_root=owned,
        asset_root=owned / "assets" / scenario.id,
    )
    backend = FakeSoundBankBackend(blueprint)
    runtime = PreparedSoundBankRuntime(blueprint, backend)
    return runtime, backend


def _runtime(
    tmp_path: Path,
    scenario: Any,
    *,
    version: str = "2022.1",
) -> tuple[PreparedSoundBankRuntime, FakeSoundBankBackend]:
    runtime, backend = _unprepared_runtime(tmp_path, scenario, version=version)
    runtime.prepare()
    return runtime, backend


def _compound_scenario(base_scenario_id: str, version: str) -> Any:
    profile = load_compound_heavy_profile(COMPOUND_PROFILE)
    return next(
        row.scenario
        for row in profile.units
        if row.base_scenario_id == base_scenario_id and row.version == version
    )


def test_dirty_fixture_normalization_never_saves_a_different_live_project(
    tmp_path: Path,
) -> None:
    scenario = _compound_scenario("O22-SB-GENERATE-01", "2025.1")
    runtime, backend = _unprepared_runtime(tmp_path, scenario, version="2025.1")
    wrong_project = runtime.blueprint.io_root / "wrong-project" / "Other.wproj"
    wrong_project.parent.mkdir()
    wrong_project.write_text("<Project/>\n", encoding="utf-8")
    backend.project_info["path"] = str(wrong_project)
    backend.project_info["isDirty"] = True

    with pytest.raises(
        SoundBankRuntimeError,
        match="does not identify the scenario-owned project",
    ):
        soundbank_runtime._normalize_fixture_project_info(
            backend,
            blueprint=runtime.blueprint,
        )

    assert ("save", None) not in backend.calls


def test_dirty_private_fixture_is_saved_once_and_rechecked_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _compound_scenario("O22-SB-GENERATE-01", "2025.1")
    runtime, backend = _unprepared_runtime(tmp_path, scenario, version="2025.1")
    backend.project_info["isDirty"] = True
    reads: list[bool] = []

    def get_project_info() -> Mapping[str, Any]:
        reads.append(bool(backend.project_info["isDirty"]))
        return json.loads(json.dumps(backend.project_info))

    def save_project() -> None:
        backend.calls.append(("save", None))
        backend.project_info["isDirty"] = False

    monkeypatch.setattr(backend, "get_project_info", get_project_info)
    monkeypatch.setattr(backend, "save_project", save_project)

    normalized = soundbank_runtime._normalize_fixture_project_info(
        backend,
        blueprint=runtime.blueprint,
    )

    assert reads == [True, False]
    assert backend.calls == [("save", None)]
    assert normalized["path"] == str(runtime.blueprint.sandbox_project)
    assert normalized["isDirty"] is False


def test_dirty_private_fixture_fails_if_save_does_not_make_it_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _compound_scenario("O22-SB-GENERATE-01", "2025.1")
    runtime, backend = _unprepared_runtime(tmp_path, scenario, version="2025.1")
    backend.project_info["isDirty"] = True
    reads = 0
    original_get_project_info = backend.get_project_info

    def get_project_info() -> Mapping[str, Any]:
        nonlocal reads
        reads += 1
        return original_get_project_info()

    monkeypatch.setattr(backend, "get_project_info", get_project_info)

    with pytest.raises(
        SoundBankRuntimeError,
        match="fixture project must be saved and clean",
    ):
        soundbank_runtime._normalize_fixture_project_info(
            backend,
            blueprint=runtime.blueprint,
        )

    assert reads == 2
    assert backend.calls == [("save", None)]


@pytest.mark.parametrize(
    "base_scenario_id",
    (
        "O22-SB-GENERATE-01",
        "O22-SB-GENERATE-03",
        "O22-SB-SET-INCLUSIONS-01",
        "O22-SB-SET-INCLUSIONS-05",
    ),
)
def test_compound_soundbank_cases_materialize_on_2025_layout(
    tmp_path: Path,
    base_scenario_id: str,
) -> None:
    profile = load_compound_heavy_profile(COMPOUND_PROFILE)
    unit = next(
        row
        for row in profile.units
        if row.base_scenario_id == base_scenario_id and row.version == "2025.1"
    )

    runtime, backend = _unprepared_runtime(
        tmp_path / base_scenario_id,
        unit.scenario,
        version=unit.version,
    )
    if unit.scenario.api == "ak.wwise.core.soundbank.generate":
        cache_root = runtime.blueprint.io_root / "io" / "cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        backend.project_info["directories"]["cache"] = str(cache_root)
    runtime.prepare()
    case = runtime.materialized
    assert case is not None
    assert case.operation_requests[0]["version"] == "2025.1"
    before = runtime.hidden_before
    assert before is not None
    protocol = build_transaction_protocol(case.operation_requests)
    business_plan = compile_soundbank_business_plan(case, before, protocol)
    validate_soundbank_business_plan(
        business_plan,
        case,
        before,
        protocol,
        verify_files=True,
    )
    assert business_plan.static_expectation["version"] == "2025.1"
    assert all(
        not row.path.startswith(r"\Actor-Mixer Hierarchy")
        and not row.path.startswith(r"\Master-Mixer Hierarchy")
        for row in case.blueprint.object_fixtures
    )
    if unit.scenario.api == "ak.wwise.core.soundbank.generate":
        actor_root = next(
            row
            for row in case.blueprint.object_fixtures
            if row.key == "fixture.actor_root"
        )
        assert actor_root.parent_path == r"\Containers\Default Work Unit"
        live_actor = backend.read_objects(path=actor_root.path)
        assert len(live_actor) == 1
        assert live_actor[0]["type"] == "PropertyContainer"
    assert runtime.verify_preview_unchanged().passed


@pytest.mark.parametrize(
    ("scenario_id", "fixture_name"),
    (
        ("O22-SB-PROCESS-DEF-02", "Master_Music"),
        ("O22-SB-SET-INCLUSIONS-04", "Review_Aux"),
    ),
)
def test_aux_bus_fixtures_are_children_of_the_master_audio_bus(
    tmp_path: Path,
    scenario_id: str,
    fixture_name: str,
) -> None:
    scenario = next(row for row in _scenarios() if row.id == scenario_id)
    runtime, _backend = _unprepared_runtime(tmp_path / scenario_id, scenario)
    fixture = next(
        row
        for row in runtime.blueprint.object_fixtures
        if row.name == fixture_name
    )

    assert fixture.object_type == "AuxBus"
    assert fixture.parent_path == (
        r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"
    )
    assert fixture.path == f"{fixture.parent_path}\\{fixture_name}"


def test_topic_runtime_localizes_long_wine_project_info_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wine Y: paths must be localized before ``Path`` probes them on macOS."""

    scenario = next(row for row in _scenarios() if row.id == "O22-SB-GENERATED-04")
    home = tmp_path / "wine-account"
    owned = (
        home
        / "Documents"
        / "Git"
        / "waapi-skills"
        / ("campaign-" + "x" * 80)
        / ("attempt-" + "y" * 80)
        / ("scenario-" + "z" * 80)
        / "owned"
    )
    project_root = owned / "sandbox-root" / "sample-project"
    project_root.mkdir(parents=True)
    project = project_root / "SampleProject.wproj"
    project.write_text("<Project/>\n", encoding="utf-8")
    (project_root / "Default Work Unit.wwu").write_text("<WorkUnit/>\n", encoding="utf-8")
    blueprint = build_soundbank_blueprint(
        scenario,
        version="2022.1",
        sandbox_project=project,
        io_root=owned,
        asset_root=owned / "assets" / scenario.id,
    )
    backend = FakeSoundBankBackend(blueprint)
    case_io = owned / "io"
    cache = case_io / "cache"
    soundbanks = case_io / "soundbanks"
    cache.mkdir(parents=True)
    soundbanks.mkdir()
    backend.project_info["directories"].update(
        {
            "root": str(project_root),
            "cache": str(cache),
            "soundBankOutputRoot": str(soundbanks),
        }
    )
    for platform in backend.project_info["platforms"]:
        platform_root = soundbanks / str(platform["name"])
        platform["soundBankPath"] = str(platform_root)
        platform["copiedMediaPath"] = str(platform_root / "Media")

    def wine_path(path: Path) -> str:
        return "Y:\\" + "\\".join(path.relative_to(home).parts)

    raw_project_path = wine_path(blueprint.sandbox_project)
    assert len(raw_project_path) > 255
    wine_project_info = json.loads(json.dumps(backend.project_info))
    wine_project_info["path"] = raw_project_path
    directories = wine_project_info["directories"]
    for field, value in tuple(directories.items()):
        directories[field] = wine_path(Path(value))
    for platform in wine_project_info["platforms"]:
        for field in ("soundBankPath", "copiedMediaPath"):
            platform[field] = wine_path(Path(platform[field]))
    monkeypatch.setattr(
        soundbank_runtime,
        "pwd",
        SimpleNamespace(getpwuid=lambda _uid: SimpleNamespace(pw_dir=str(home))),
    )
    monkeypatch.setattr(backend, "get_project_info", lambda: wine_project_info)

    localized = soundbank_runtime._validate_project_info(
        wine_project_info,
        blueprint=blueprint,
    )
    assert localized["path"] == str(project)
    assert localized["directories"] == {
        "root": str(project_root),
        "cache": str(cache),
        "soundBankOutputRoot": str(soundbanks),
    }
    assert {
        row["name"]: (row["soundBankPath"], row["copiedMediaPath"])
        for row in localized["platforms"]
    } == {
        "Windows": (str(soundbanks / "Windows"), str(soundbanks / "Windows" / "Media")),
        "Mac": (str(soundbanks / "Mac"), str(soundbanks / "Mac" / "Media")),
    }

    materialized = PreparedSoundBankRuntime(blueprint, backend).prepare()

    assert materialized.topic_plan is not None
    assert materialized.topic_plan.publishers


def _topic_payload(row: TopicExpectedEvent) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "soundbank": {"id": row.soundbank_id, "name": row.soundbank_name},
        "platform": {"id": row.platform_id, "name": row.platform_name},
    }
    if row.language_name is not None:
        payload["language"] = {"id": row.language_id, "name": row.language_name}
    return payload


def test_all_25_soundbank_scenarios_materialize_and_verify(tmp_path: Path) -> None:
    scenarios = _scenarios()
    assert len(scenarios) == EXPECTED_SCENARIO_COUNT
    assert {scenario.api for scenario in scenarios} == SOUNDBANK_APIS
    assert Counter(scenario.api for scenario in scenarios) == {
        api: 5 for api in SOUNDBANK_APIS
    }

    for scenario in scenarios:
        runtime, backend = _runtime(tmp_path / scenario.id, scenario)
        case = runtime.materialized
        assert case is not None
        assert case.render_prompt()
        preview = runtime.verify_preview_unchanged()
        assert preview.passed
        assert all(Path(proof.path).is_file() and not Path(proof.path).is_symlink() for proof in case.input_files)
        assert all(len(proof.sha256) == 64 and proof.size > 0 for proof in case.input_files)

        if scenario.api == SOUNDBANK_TOPIC:
            assert case.topic_plan is not None
            assert case.topic_plan.event_count == scenario.primary_dispatch.count
            assert case.topic_plan.init_generated_before_subscribe
            assert case.topic_plan.subscribe_before_publish
            assert all(
                publisher.operation_request["arguments"]["rebuild_init_bank"] is False
                for publisher in case.topic_plan.publishers
            )
            setup_requests = [
                value for kind, value in backend.calls if kind == "generateInit"
            ]
            assert len(setup_requests) == 1
            setup_banks = setup_requests[0]["soundbanks"]
            control_names = [
                bank.name for bank in case.blueprint.soundbanks if bank.control
            ]
            target_names = {
                bank.name for bank in case.blueprint.soundbanks if not bank.control
            }
            assert setup_banks == [
                {"name": name, "rebuild": True} for name in control_names
            ]
            assert not target_names.intersection(
                str(row["name"]) for row in setup_banks
            )
            before_files = {
                row.relative_path: row for row in preview.before.output_files
            }
            for artifact in case.expected_artifacts:
                relative = artifact.path.resolve(strict=False).relative_to(
                    case.blueprint.io_root
                ).as_posix()
                if artifact.kind in {"control", "init"}:
                    assert relative in before_files
            backend.apply_business_effect(case)
            payloads = [_topic_payload(row) for row in case.topic_plan.expected_events]
            topic, artifacts = runtime.verify_topic(payloads)
            assert topic.passed, topic.failures
            assert artifacts.passed, artifacts.failures
        elif scenario.id == PROCESS_REFUSAL_ID:
            result = runtime.verify_zero_dispatch(
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": False,
                    "status": "error",
                    "command": "preview",
                    "error_code": PROCESS_REFUSAL_ERROR_CODE,
                }
            )
            assert result.passed, result.failures
        else:
            assert len(case.operation_requests) == 1
            backend.apply_business_effect(case)
            result = runtime.verify_after_execution()
            assert result.passed, result.failures

        runtime.cleanup_success()
        assert not case.blueprint.asset_root.exists()
        assert not case.blueprint.output_root.exists()


def test_external_source_conversion_does_not_require_a_conversion_shareset_short_id(
    tmp_path: Path,
) -> None:
    scenario = next(
        row for row in _scenarios() if row.id == "O22-SB-CONVERT-EXT-01"
    )
    runtime, backend = _unprepared_runtime(tmp_path, scenario)
    backend.omit_conversion_short_id = True

    materialized = runtime.prepare()

    conversion_keys = {
        fixture.key
        for fixture in materialized.blueprint.object_fixtures
        if fixture.object_type == "Conversion"
    }
    assert conversion_keys
    assert conversion_keys.issubset(materialized.object_ids)
    assert conversion_keys.isdisjoint(materialized.short_ids)
    assert materialized.operation_requests[0]["operation"] == (
        "soundbank.convertExternalSources"
    )


@pytest.mark.parametrize(
    "scenario_id",
    (
        "O22-SB-GENERATED-01",
        "O22-SB-GENERATED-02",
        "O22-SB-GENERATED-03",
        "O22-SB-GENERATED-04",
        "O22-SB-GENERATED-05",
    ),
)
def test_each_generated_topic_fixture_encodes_explicit_play_actions(
    tmp_path: Path,
    scenario_id: str,
) -> None:
    """Every generated-topic setup must use Wwise's ``path@Play`` syntax."""

    scenario = next(row for row in _scenarios() if row.id == scenario_id)
    runtime, _ = _runtime(tmp_path / scenario_id, scenario)
    case = runtime.materialized
    assert case is not None
    assert case.blueprint.media_fixtures
    assert {
        soundbank_runtime._setup_event_value(fixture.event_path)
        for fixture in case.blueprint.media_fixtures
    } == {
        f"{fixture.event_path}@Play" for fixture in case.blueprint.media_fixtures
    }


@pytest.mark.parametrize(
    ("object_type", "typed_leaf"),
    (
        ("Sound Voice", "<Sound Voice>Localized_Line"),
        ("Sound SFX", "<Sound SFX>Localized_Line"),
    ),
)
def test_use_existing_wire_path_types_only_the_final_sound_segment(
    object_type: str,
    typed_leaf: str,
) -> None:
    logical = (
        r"\Actor-Mixer Hierarchy\Default Work Unit"
        r"\Localized_Group\Localized_Line"
    )

    canonical, wire = soundbank_runtime._typed_existing_import_path(
        logical,
        object_type=object_type,
    )

    assert canonical == logical
    assert wire == (
        r"\Actor-Mixer Hierarchy\Default Work Unit\Localized_Group"
        + "\\"
        + typed_leaf
    )


@pytest.mark.parametrize(
    ("logical", "object_type", "expected_error"),
    (
        (
            r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound Voice>Line",
            "Sound Voice",
            "untyped canonical path",
        ),
        (
            r"\Actor-Mixer Hierarchy\\Line",
            "Sound Voice",
            "absolute Wwise object path",
        ),
        (r"\Line", "Sound Voice", "no creatable parent"),
        (
            r"\Actor-Mixer Hierarchy\Default Work Unit\Line",
            "Sound",
            "closed as Sound Voice or Sound SFX",
        ),
    ),
)
def test_use_existing_wire_path_rejects_typed_invalid_or_ambiguous_inputs(
    logical: str,
    object_type: str,
    expected_error: str,
) -> None:
    with pytest.raises(SoundBankRuntimeError, match=expected_error):
        soundbank_runtime._typed_existing_import_path(
            logical,
            object_type=object_type,
        )


@pytest.mark.parametrize(
    "scenario_id",
    ("O22-SB-GENERATE-02", "O22-SB-GENERATED-02"),
)
def test_localized_soundbank_fixture_reuses_two_logical_sounds_and_event_graphs(
    tmp_path: Path,
    scenario_id: str,
) -> None:
    scenario = next(row for row in _scenarios() if row.id == scenario_id)
    runtime, backend = _runtime(tmp_path / scenario_id, scenario)
    case = runtime.materialized
    assert case is not None

    by_path: dict[str, list[MediaFixture]] = {}
    for fixture in case.blueprint.media_fixtures:
        by_path.setdefault(fixture.sound_path, []).append(fixture)
    assert len(by_path) == 2
    for sound_path, fixtures in by_path.items():
        assert [fixture.language for fixture in fixtures] == [
            "Chinese(PRC)",
            "English(US)",
            "Japanese",
        ]
        assert [fixture.import_operation for fixture in fixtures] == [
            "createNew",
            "useExisting",
            "useExisting",
        ]
        assert [fixture.create_event for fixture in fixtures] == [True, False, False]
        sound_ids = {
            case.object_ids[f"media:{fixture.key}"] for fixture in fixtures
        }
        assert len(sound_ids) == 1
        event_paths = {fixture.event_path for fixture in fixtures}
        assert len(event_paths) == 1
        graph = backend.read_event_graph(next(iter(event_paths)))
        assert graph is not None
        assert graph.action_types == (1,)
        assert graph.target_ids == (next(iter(sound_ids)),)
        assert len(graph.action_ids) == 1
        assert sound_path.startswith(
            r"\Actor-Mixer Hierarchy\Default Work Unit" + "\\"
        )

    snapshot = runtime.hidden_before
    assert snapshot is not None
    action_rows = [row for row in snapshot.objects if row.key.startswith("event_action:")]
    target_rows = [row for row in snapshot.objects if row.key.startswith("event_target:")]
    assert len(action_rows) == len(target_rows) == 2
    assert {row.id for row in action_rows} == {
        backend.read_event_graph(event_path).action_ids[0]
        for event_path in {
            fixture.event_path for fixture in case.blueprint.media_fixtures
        }
    }
    source_rows = {
        row.key.removeprefix("localized_source:"): row
        for row in snapshot.objects
        if row.key.startswith("localized_source:")
    }
    assert set(source_rows) == {
        fixture.key for fixture in case.blueprint.media_fixtures
    }
    for fixture in case.blueprint.media_fixtures:
        localized = backend.read_objects(
            path=fixture.sound_path,
            fields=MEDIA_OBJECT_FIELDS,
            language=fixture.language,
        )
        assert len(localized) == 1
        source_id = localized[0]["activeSource"]["id"]
        assert source_id == case.object_ids[f"media_source:{fixture.key}"]
        source = backend.read_objects(
            object_id=source_id,
            fields=MEDIA_SOURCE_FIELDS,
            language=fixture.language,
        )
        assert len(source) == 1
        assert source[0]["audioSource:language"] == {"name": fixture.language}
        copied = Path(source[0]["originalFilePath"]).resolve(strict=True)
        originals = (case.blueprint.sandbox_root / "Originals").resolve(strict=True)
        assert originals in copied.parents
        assert soundbank_runtime._sha256_file(copied) == soundbank_runtime._sha256_file(
            fixture.wav_path
        )
        sealed = json.loads(source_rows[fixture.key].object_type or "{}")
        assert sealed == {
            "kind": "AudioFileSource",
            "sound_id": case.object_ids[f"media:{fixture.key}"],
            "media_id": case.media_ids[fixture.key],
            "language": fixture.language,
            "copied_relative_path": copied.relative_to(
                case.blueprint.sandbox_root
            ).as_posix(),
            "copied_size": copied.stat().st_size,
            "copied_sha256": soundbank_runtime._sha256_file(copied),
            "copied_mtime_ns": copied.stat().st_mtime_ns,
        }


@pytest.mark.parametrize(
    ("backend_flag", "expected_error"),
    (
        (
            "replace_sound_on_localized_reuse",
            "localized Sound GUID drifted across languages",
        ),
        (
            "replace_action_on_localized_reuse",
            "localized useExisting changed Event/Action/target GUIDs",
        ),
    ),
)
def test_localized_soundbank_fixture_rejects_guid_drift(
    tmp_path: Path,
    backend_flag: str,
    expected_error: str,
) -> None:
    scenario = next(row for row in _scenarios() if row.id == "O22-SB-GENERATE-02")
    runtime, backend = _unprepared_runtime(tmp_path / backend_flag, scenario)
    setattr(backend, backend_flag, True)

    with pytest.raises(SoundBankRuntimeError, match=expected_error):
        runtime.prepare()


@pytest.mark.parametrize(
    ("backend_flag", "expected_error"),
    (
        ("wrong_source_language", "AudioFileSource language mismatch"),
        ("wrong_active_source", "activeSource does not identify the imported source"),
        ("corrupt_copied_wav", "copied WAV bytes differ from the sealed input"),
        ("escape_copied_path", "copied WAV escapes the case-owned Originals root"),
        ("symlink_copied_path", "copied WAV path contains a symlink"),
    ),
)
def test_localized_soundbank_fixture_rejects_unproven_source_binding(
    tmp_path: Path,
    backend_flag: str,
    expected_error: str,
) -> None:
    scenario = next(row for row in _scenarios() if row.id == "O22-SB-GENERATE-02")
    runtime, backend = _unprepared_runtime(tmp_path / backend_flag, scenario)
    setattr(backend, backend_flag, True)

    with pytest.raises(SoundBankRuntimeError, match=expected_error):
        runtime.prepare()


def test_localized_event_action_target_are_part_of_the_hidden_snapshot_oracle(
    tmp_path: Path,
) -> None:
    scenario = next(row for row in _scenarios() if row.id == "O22-SB-GENERATED-02")
    runtime, backend = _runtime(tmp_path, scenario)
    case = runtime.materialized
    assert case is not None
    event_path = case.blueprint.media_fixtures[0].event_path
    graph = backend.read_event_graph(event_path)
    assert graph is not None
    backend.event_graphs[event_path.casefold()] = EventGraphState(
        graph.event_id,
        (_guid("post-setup-action-replacement"),),
        graph.target_ids,
        graph.action_types,
    )

    verification = runtime.verify_preview_unchanged()
    assert not verification.passed
    assert "preview changed hidden objects" in verification.failures


@pytest.mark.parametrize("tamper", ("language", "active_source", "copied_bytes"))
def test_localized_source_evidence_is_part_of_the_hidden_snapshot_oracle(
    tmp_path: Path,
    tamper: str,
) -> None:
    scenario = next(row for row in _scenarios() if row.id == "O22-SB-GENERATED-02")
    runtime, backend = _runtime(tmp_path / tamper, scenario)
    case = runtime.materialized
    assert case is not None
    fixture = case.blueprint.media_fixtures[0]
    source_id = case.object_ids[f"media_source:{fixture.key}"]
    source = backend.rows[source_id.casefold()]

    if tamper == "language":
        source["audioSource:language"] = {"name": "Japanese"}
    elif tamper == "active_source":
        replacement = next(
            row
            for row in case.blueprint.media_fixtures
            if row.sound_path == fixture.sound_path and row.language == "English(US)"
        )
        backend.localized_sources[
            (fixture.sound_path.casefold(), fixture.language.casefold())
        ] = case.object_ids[f"media_source:{replacement.key}"]
    else:
        Path(source["originalFilePath"]).write_bytes(b"tampered-copied-wav")

    verification = runtime.verify_preview_unchanged()
    assert not verification.passed
    assert "preview changed hidden objects" in verification.failures


def test_localized_source_oracle_rejects_post_baseline_originals_escape(
    tmp_path: Path,
) -> None:
    scenario = next(row for row in _scenarios() if row.id == "O22-SB-GENERATED-02")
    runtime, backend = _runtime(tmp_path, scenario)
    case = runtime.materialized
    assert case is not None
    fixture = case.blueprint.media_fixtures[0]
    source_id = case.object_ids[f"media_source:{fixture.key}"]
    backend.rows[source_id.casefold()]["originalFilePath"] = str(fixture.wav_path)

    with pytest.raises(
        SoundBankRuntimeError,
        match="copied WAV escapes the case-owned Originals root",
    ):
        runtime.snapshot()


def test_copied_original_path_parser_accepts_only_closed_absolute_mappings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = home / "case" / "project"
    copied = project / "Originals" / "Voices" / "line.wav"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(b"RIFF-copied-proof")
    monkeypatch.setattr(
        soundbank_runtime,
        "pwd",
        SimpleNamespace(getpwuid=lambda _uid: SimpleNamespace(pw_dir=str(home))),
    )

    posix = soundbank_runtime._copied_original_file_proof(
        str(copied),
        sandbox_root=project,
    )
    wine_y = soundbank_runtime._copied_original_file_proof(
        "Y:\\" + "\\".join(copied.relative_to(home).parts),
        sandbox_root=project,
    )
    wine_z = soundbank_runtime._copied_original_file_proof(
        "Z:\\" + "\\".join(copied.parts[1:]),
        sandbox_root=project,
    )
    assert posix == wine_y == wine_z

    unsafe = (
        "~/case/project/Originals/Voices/line.wav",
        str(copied).replace("/Voices/", "/./Voices/"),
        str(copied).replace("/Voices/", "/../Voices/"),
        "Y:\\case\\project\\Originals\\\\line.wav",
        "X:\\case\\project\\Originals\\line.wav",
        r"\\server\share\line.wav",
    )
    for value in unsafe:
        with pytest.raises(SoundBankRuntimeError):
            soundbank_runtime._copied_original_file_proof(
                value,
                sandbox_root=project,
            )


@pytest.mark.parametrize(
    "scenario_id",
    (
        "O22-SB-GENERATED-01",
        "O22-SB-GENERATED-02",
        "O22-SB-GENERATED-03",
        "O22-SB-GENERATED-04",
        "O22-SB-GENERATED-05",
    ),
)
def test_each_generated_topic_binds_live_media_id_for_exact_wem_oracle(
    tmp_path: Path,
    scenario_id: str,
) -> None:
    """Audio Source ``mediaId``—never ``shortId``—names expected .wem files."""

    scenario = next(row for row in _scenarios() if row.id == scenario_id)
    runtime, backend = _runtime(tmp_path / "valid" / scenario_id, scenario)
    case = runtime.materialized
    assert case is not None and case.topic_plan is not None

    expected_keys = {fixture.key for fixture in case.blueprint.media_fixtures}
    assert set(case.media_ids) == expected_keys
    assert not any(key.startswith("media_source:") for key in case.short_ids)
    assert {
        int(artifact.path.stem)
        for artifact in case.expected_artifacts
        if artifact.kind == "media"
    } == set(case.media_ids.values())

    for fixture in case.blueprint.media_fixtures:
        source_id = case.object_ids[f"media_source:{fixture.key}"]
        source = backend.rows[source_id.casefold()]
        assert source["type"] == "AudioFileSource"
        assert "shortId" not in source
        assert source["mediaId"] == case.media_ids[fixture.key]
        assert source["mediaId"] != case.short_ids[f"media:{fixture.key}"]
        assert source["parent"] == {"id": case.object_ids[f"media:{fixture.key}"]}

    # A source-shaped row with a plausible uint32 shortId but no mediaId must
    # fail closed.  This reproduces the r4 bug and proves there is no fallback
    # to either that value or the parent Sound's short ID.
    invalid_runtime, invalid_backend = _unprepared_runtime(
        tmp_path / "missing-media-id" / scenario_id,
        scenario,
    )
    invalid_backend.omit_source_media_id = True
    with pytest.raises(
        SoundBankRuntimeError,
        match=r"media source .* has no bounded uint32 mediaId",
    ):
        invalid_runtime.prepare()


@pytest.mark.parametrize(
    ("backend_flag", "expected_error"),
    (
        (
            "omit_source_from_import_result",
            r"must bind exactly one imported AudioFileSource; got 0",
        ),
        (
            "add_second_source_to_import_result",
            r"must bind exactly one imported AudioFileSource; got 2",
        ),
        (
            "use_wrong_source_parent",
            r"parent does not match imported Sound",
        ),
    ),
)
def test_generated_topic_rejects_non_unique_or_wrong_parent_media_source(
    tmp_path: Path,
    backend_flag: str,
    expected_error: str,
) -> None:
    """The shared setup path binds one source below the exact imported Sound."""

    scenario = next(row for row in _scenarios() if row.id == "O22-SB-GENERATED-04")
    runtime, backend = _unprepared_runtime(tmp_path / backend_flag, scenario)
    setattr(backend, backend_flag, True)

    with pytest.raises(SoundBankRuntimeError, match=expected_error):
        runtime.prepare()


@pytest.mark.parametrize(
    ("scenario_id", "expected_match"),
    (
        (
            "O22-SB-GENERATED-01",
            {"platform": {"name": "Windows"}},
        ),
        (
            "O22-SB-GENERATED-02",
            {
                "soundbank": {"name": "Dialogue_Chapter14"},
                "platform": {"name": "Windows"},
            },
        ),
        (
            "O22-SB-GENERATED-03",
            {"soundbank": {"name": "Weapons_Core"}},
        ),
        ("O22-SB-GENERATED-04", None),
        (
            "O22-SB-GENERATED-05",
            {
                "soundbank": {"name": "Cinematics_Intro"},
                "platform": {"name": "Windows"},
            },
        ),
    ),
)
def test_each_generated_topic_prompt_reaches_a_name_only_request_and_hidden_guid_oracle(
    tmp_path: Path,
    scenario_id: str,
    expected_match: Mapping[str, Any] | None,
) -> None:
    scenario = next(row for row in _scenarios() if row.id == scenario_id)
    runtime, _ = _runtime(tmp_path / scenario_id, scenario)
    case = runtime.materialized
    assert case is not None and case.topic_plan is not None
    plan = case.topic_plan
    prompt = case.render_prompt()

    assert plan.event_count == scenario.primary_dispatch.count
    assert plan.reject_n_plus_one
    assert (dict(plan.match) if plan.match is not None else None) == expected_match
    assert plan.options == {"return": list(SOUNDBANK_TOPIC_RETURN_FIELDS)}
    gateway_arguments = dict(plan.gateway_arguments())
    assert gateway_arguments == {
        "api": SOUNDBANK_TOPIC,
        "event_count": scenario.primary_dispatch.count,
        "options": {"return": list(SOUNDBANK_TOPIC_RETURN_FIELDS)},
        **({"match": expected_match} if expected_match is not None else {}),
    }

    if expected_match is not None:
        for identity in expected_match.values():
            assert identity["name"] in prompt
            assert set(identity) == {"name"}
    hidden_ids = {
        identity
        for row in plan.expected_events
        for identity in (row.soundbank_id, row.platform_id, row.language_id)
        if identity is not None
    }
    assert hidden_ids
    assert all(identity not in prompt for identity in hidden_ids)
    assert all(identity not in repr(plan.match) for identity in hidden_ids)

    valid = [_topic_payload(row) for row in plan.expected_events]
    verification = verify_topic_payloads(scenario_id, plan, valid)
    assert verification.passed, verification.failures
    assert len(verification.observed_keys) == scenario.primary_dispatch.count

    n_plus_one = verify_topic_payloads(scenario_id, plan, [*valid, valid[0]])
    assert not n_plus_one.passed
    assert any("cardinality mismatch" in failure for failure in n_plus_one.failures)

    wrong_guid = [dict(payload) for payload in valid]
    wrong_guid[0] = {
        **wrong_guid[0],
        "soundbank": {
            **dict(wrong_guid[0]["soundbank"]),
            "id": _guid(f"wrong:{scenario_id}"),
        },
    }
    assert not verify_topic_payloads(scenario_id, plan, wrong_guid).passed

    wrong_name = [dict(payload) for payload in valid]
    wrong_name[0] = {
        **wrong_name[0],
        "soundbank": {
            **dict(wrong_name[0]["soundbank"]),
            "name": "Prompt_Name_With_Wrong_Hidden_GUID_Binding",
        },
    }
    name_verification = verify_topic_payloads(scenario_id, plan, wrong_name)
    assert not name_verification.passed
    assert any(
        "name does not match its hidden GUID" in row
        for row in name_verification.failures
    )

    name_only = [dict(payload) for payload in valid]
    name_only[0] = {
        **name_only[0],
        "soundbank": {"name": plan.expected_events[0].soundbank_name},
    }
    name_only_verification = verify_topic_payloads(scenario_id, plan, name_only)
    assert not name_only_verification.passed
    assert any("is not a canonical GUID" in row for row in name_only_verification.failures)


def test_generated_topic_reference_closes_model_owned_request_fields() -> None:
    reference = " ".join(QUERY_REFERENCE.read_text(encoding="utf-8").split())
    assert '`{"return":["id","name","type","path"]}`' in reference
    assert "`soundbank.name`" in reference
    assert "`platform.name`" in reference
    assert "omit `--match-json` instead of passing an empty object" in reference
    assert "Never discover or inject a GUID" in reference


def test_all_25_cases_emit_registry_valid_closed_operation_requests(
    tmp_path: Path,
) -> None:
    for scenario in _scenarios():
        runtime, _ = _runtime(tmp_path / scenario.id, scenario)
        case = runtime.materialized
        assert case is not None
        requests = list(case.operation_requests)
        if case.topic_plan is not None:
            requests.extend(
                publisher.operation_request for publisher in case.topic_plan.publishers
            )
        assert requests
        for request in requests:
            parsed = parse_operation_request(request, expected_version="2022.1")
            assert parsed.operation == request["operation"]
        refusal = (
            StructuredRefusal(PROCESS_REFUSAL_ERROR_CODE)
            if scenario.id == PROCESS_REFUSAL_ID
            else None
        )
        protocol = build_transaction_protocol(requests, refusal=refusal)
        assert protocol.steps[-1].name.endswith(
            ".preview" if refusal is not None else ".verify"
        )


def test_external_assets_are_real_48k_wav_and_strict_wsources(tmp_path: Path) -> None:
    scenarios = [
        scenario
        for scenario in _scenarios()
        if scenario.api == "ak.wwise.core.soundbank.convertExternalSources"
    ]
    assert len(scenarios) == 5
    for scenario in scenarios:
        runtime, _ = _runtime(tmp_path / scenario.id, scenario)
        case = runtime.materialized
        assert case is not None
        for document in case.blueprint.external_documents:
            data = document.path.read_bytes()
            assert data.startswith(b"<?xml")
            assert b"<!DOCTYPE" not in data and b"<!ENTITY" not in data
            root = ET.fromstring(data)
            assert root.tag == "ExternalSourcesList"
            assert set(root.attrib) == {"SchemaVersion", "Root"}
            assert root.attrib["SchemaVersion"] == "1"
            source_root = (
                case.blueprint.sandbox_project.parent / root.attrib["Root"]
            ).resolve(strict=True)
            assert source_root == (case.blueprint.asset_root / "media").resolve()
            assert len(root) == len(document.rows)
            for element, row in zip(root, document.rows, strict=True):
                assert element.tag == "Source" and not list(element)
                assert set(element.attrib) <= {
                    "Path",
                    "Conversion",
                    "Destination",
                    "AnalysisTypes",
                }
                assert (source_root / element.attrib["Path"]).resolve() == row.source_path
                assert element.attrib["Destination"] == row.destination
                with wave.open(str(row.source_path), "rb") as handle:
                    assert handle.getframerate() == 48_000
                    assert handle.getnchannels() == 1
                    assert handle.getsampwidth() == 2


def test_wav_materialization_is_byte_deterministic_across_fresh_roots(
    tmp_path: Path,
) -> None:
    scenario = next(row for row in _scenarios() if row.id == "O22-SB-GENERATE-02")
    first, _ = _runtime(tmp_path / "first", scenario)
    second, _ = _runtime(tmp_path / "second", scenario)
    first_case = first.materialized
    second_case = second.materialized
    assert first_case is not None and second_case is not None
    first_bytes = {
        fixture.wav_path.name: fixture.wav_path.read_bytes()
        for fixture in first_case.blueprint.media_fixtures
    }
    second_bytes = {
        fixture.wav_path.name: fixture.wav_path.read_bytes()
        for fixture in second_case.blueprint.media_fixtures
    }
    assert first_bytes == second_bytes


def test_definition_files_are_lf_utf8_and_live_identity_bound(tmp_path: Path) -> None:
    scenarios = [
        scenario
        for scenario in _scenarios()
        if scenario.api == "ak.wwise.core.soundbank.processDefinitionFiles"
    ]
    assert len(scenarios) == 5
    for scenario in scenarios:
        runtime, _ = _runtime(tmp_path / scenario.id, scenario)
        case = runtime.materialized
        assert case is not None
        for document in case.blueprint.definitions:
            data = document.path.read_bytes()
            assert not data.startswith(b"\xef\xbb\xbf")
            assert b"\r" not in data and data.endswith(b"\n")
            assert b"\t" in data
            text = data.decode("utf-8")
            lines = text.splitlines()
            assert len(lines) == len(document.rows)
            for line, row in zip(lines, document.rows, strict=True):
                cells = line.split("\t")
                identity_column = 2 if row.directive.startswith("-") else 1
                serialized_identity = cells[identity_column]
                if row.identity_format == "name":
                    assert serialized_identity == f'"{row.object_name}"'
                else:
                    assert '"' not in serialized_identity
            parsed = parse_soundbank_definition_file(document.path)
            assert parsed["row_count"] == len(document.rows)
            if scenario.id == "O22-SB-PROCESS-DEF-03":
                assert "0x" in text
                assert any(value in text for value in case.object_ids.values())
                name_row = next(
                    row for row in document.rows if row.identity_format == "name"
                )
                decimal_row = next(
                    row
                    for row in document.rows
                    if row.identity_format == "decimal_short_id"
                )
                hexadecimal_row = next(
                    row
                    for row in document.rows
                    if row.identity_format == "hexadecimal_short_id"
                )
                assert f'"{name_row.object_name}"' in text
                assert (
                    f"\t{case.short_ids[decimal_row.object_key]}\t" in text
                )
                assert (
                    f"\t0x{case.short_ids[hexadecimal_row.object_key]:08X}\t"
                    in text
                )


def test_definition_processing_preserves_existing_inclusions_additively(
    tmp_path: Path,
) -> None:
    scenario = next(
        row for row in _scenarios() if row.id == "O22-SB-PROCESS-DEF-04"
    )
    runtime, backend = _runtime(tmp_path, scenario)
    case = runtime.materialized
    assert case is not None
    bank_id = case.object_ids["bank:Release_Core"]
    debug_id = case.object_ids["definition:debug-before"].casefold()

    backend.apply_business_effect(case)
    inclusions = backend.read_inclusions(bank_id)
    assert debug_id in {str(row["object"]).casefold() for row in inclusions}
    assert runtime.verify_after_execution().passed

    backend.inclusions[bank_id.casefold()] = [
        row for row in backend.inclusions[bank_id.casefold()]
        if str(row["object"]).casefold() != debug_id
    ]
    missing_preserved = runtime.verify_after_execution()
    assert not missing_preserved.passed
    assert any("inclusions mismatch" in row for row in missing_preserved.failures)


def test_topic_oracle_rejects_duplicate_n_plus_one_init_and_control(tmp_path: Path) -> None:
    scenario = next(row for row in _scenarios() if row.id == "O22-SB-GENERATED-04")
    runtime, backend = _runtime(tmp_path, scenario)
    case = runtime.materialized
    assert case is not None and case.topic_plan is not None
    valid = [_topic_payload(row) for row in case.topic_plan.expected_events]

    duplicate = [*valid[:-1], valid[0]]
    assert not verify_topic_payloads(case.scenario_id, case.topic_plan, duplicate).passed
    assert not verify_topic_payloads(case.scenario_id, case.topic_plan, [*valid, valid[0]]).passed
    init = [*valid[:-1], {"soundbank": {"name": "Init"}, "platform": valid[0]["platform"]}]
    assert not verify_topic_payloads(case.scenario_id, case.topic_plan, init).passed
    control = [
        *valid[:-1],
        {"soundbank": {"name": "Frontend"}, "platform": valid[0]["platform"]},
    ]
    assert not verify_topic_payloads(
        case.scenario_id,
        case.topic_plan,
        control,
        control_soundbanks=("Frontend",),
    ).passed

    backend.apply_business_effect(case)
    sealed_init = next(row for row in case.expected_artifacts if row.kind == "init")
    sealed_init.path.write_bytes(b"unexpected Init rebuild")
    valid_topic, changed_init = runtime.verify_topic(valid)
    assert valid_topic.passed
    assert not changed_init.passed
    assert any("init artifact changed" in row for row in changed_init.failures)


def test_preview_drift_missing_artifact_and_wrong_refusal_are_failures(tmp_path: Path) -> None:
    generate = next(row for row in _scenarios() if row.id == "O22-SB-GENERATE-01")
    runtime, backend = _runtime(tmp_path / "generate", generate)
    case = runtime.materialized
    assert case is not None
    input_path = Path(case.input_files[0].path)
    input_path.write_bytes(input_path.read_bytes() + b"drift")
    assert not runtime.verify_preview_unchanged().passed

    runtime2, backend2 = _runtime(tmp_path / "missing", generate)
    case2 = runtime2.materialized
    assert case2 is not None
    backend2.apply_business_effect(case2)
    required = next(row for row in case2.expected_artifacts if row.required_change)
    required.path.unlink()
    assert not runtime2.verify_after_execution().passed

    runtime_extra, backend_extra = _runtime(tmp_path / "extra", generate)
    case_extra = runtime_extra.materialized
    assert case_extra is not None
    backend_extra.apply_business_effect(case_extra)
    extra = case_extra.blueprint.output_root / "unexpected.wem"
    extra.write_bytes(b"N+1")
    extra_result = runtime_extra.verify_after_execution()
    assert not extra_result.passed
    assert any("unreviewed SoundBank artifact" in row for row in extra_result.failures)

    runtime_init, backend_init = _runtime(tmp_path / "automatic-init", generate)
    case_init = runtime_init.materialized
    assert case_init is not None
    backend_init.apply_business_effect(case_init)
    automatic_init = next(
        row for row in case_init.expected_artifacts if row.kind == "init"
    )
    automatic_init.path.parent.mkdir(parents=True, exist_ok=True)
    automatic_init.path.write_bytes(b"automatic non-empty Init")
    assert runtime_init.verify_after_execution().passed

    rebuild = next(row for row in _scenarios() if row.id == "O22-SB-GENERATE-04")
    runtime_cache, backend_cache = _runtime(tmp_path / "bounded-cache", rebuild)
    case_cache = runtime_cache.materialized
    assert case_cache is not None
    assert len(case_cache.allowed_dynamic_artifact_roots) == 1
    backend_cache.apply_business_effect(case_cache)
    cache_wem = case_cache.allowed_dynamic_artifact_roots[0] / "Windows" / "rebuilt.wem"
    cache_wem.parent.mkdir(parents=True, exist_ok=True)
    cache_wem.write_bytes(b"bounded rebuilt cache media")
    cache_index = cache_wem.parent / "Wwise.dat"
    cache_index.write_bytes(b"bounded cache index")
    assert runtime_cache.verify_after_execution().passed

    runtime_bad_cache, backend_bad_cache = _runtime(
        tmp_path / "bad-cache-type",
        rebuild,
    )
    case_bad_cache = runtime_bad_cache.materialized
    assert case_bad_cache is not None
    backend_bad_cache.apply_business_effect(case_bad_cache)
    cache_bnk = (
        case_bad_cache.allowed_dynamic_artifact_roots[0]
        / "Windows"
        / "unreviewed.bnk"
    )
    cache_bnk.parent.mkdir(parents=True, exist_ok=True)
    cache_bnk.write_bytes(b"not an allowed cache artifact")
    bad_cache_result = runtime_bad_cache.verify_after_execution()
    assert not bad_cache_result.passed
    assert any("type is not allowed" in row for row in bad_cache_result.failures)

    runtime_existing, backend_existing = _unprepared_runtime(
        tmp_path / "preexisting-cache",
        rebuild,
    )
    existing_cache = (
        Path(backend_existing.project_info["directories"]["cache"])
        / "Windows"
        / "existing.wem"
    )
    existing_cache.parent.mkdir(parents=True, exist_ok=True)
    existing_cache.write_bytes(b"sealed before cache")
    runtime_existing.prepare()
    case_existing = runtime_existing.materialized
    assert case_existing is not None
    backend_existing.apply_business_effect(case_existing)
    existing_cache.write_bytes(b"changed cache")
    existing_result = runtime_existing.verify_after_execution()
    assert not existing_result.passed
    assert any(
        "preexisting dynamic cache artifact changed" in row
        for row in existing_result.failures
    )

    refusal = next(row for row in _scenarios() if row.id == PROCESS_REFUSAL_ID)
    runtime3, _ = _runtime(tmp_path / "refusal", refusal)
    assert not runtime3.verify_zero_dispatch(
        {
            "contract": "waapi-skill.gateway-result/v1",
            "ok": False,
            "status": "error",
            "command": "preview",
            "error_code": "INVALID_ARGUMENT",
        }
    ).passed

    runtime4, backend4 = _runtime(tmp_path / "refusal-partial-create", refusal)
    backend4._insert(
        r"\SoundBanks\Default Work Unit\Retired_Content",
        "Retired_Content",
        "SoundBank",
    )
    partial = runtime4.verify_zero_dispatch(
        {
            "contract": "waapi-skill.gateway-result/v1",
            "ok": False,
            "status": "error",
            "command": "preview",
            "error_code": PROCESS_REFUSAL_ERROR_CODE,
        }
    )
    assert not partial.passed
    assert "preview changed hidden objects" in partial.failures


def test_root_reuse_escape_symlink_and_cleanup_residual_fail_closed(tmp_path: Path) -> None:
    scenario = next(row for row in _scenarios() if row.id == "O22-SB-GENERATE-01")
    runtime, backend = _runtime(tmp_path / "case", scenario)
    case = runtime.materialized
    assert case is not None
    with pytest.raises(SoundBankRuntimeError, match="cannot be reused"):
        build_soundbank_blueprint(
            scenario,
            version="2022.1",
            sandbox_project=case.blueprint.sandbox_project,
            io_root=case.blueprint.io_root,
            asset_root=case.blueprint.asset_root,
        )
    with pytest.raises(SoundBankRuntimeError, match="escapes"):
        build_soundbank_blueprint(
            scenario,
            version="2022.1",
            sandbox_project=case.blueprint.sandbox_project,
            io_root=case.blueprint.io_root,
            asset_root=tmp_path / "outside",
        )

    proof = case.input_files[0]
    original = Path(proof.path)
    target = original.with_suffix(".real")
    original.rename(target)
    create_symlink_or_skip(original, target)
    with pytest.raises(SoundBankRuntimeError, match="symlink"):
        runtime.snapshot()

    runtime2, backend2 = _runtime(tmp_path / "cleanup", scenario)
    backend2.refuse_delete = True
    with pytest.raises(SoundBankRuntimeError, match="cleanup left"):
        runtime2.cleanup_success()


def test_closed_direct_backend_emits_only_reviewed_setup_shapes(tmp_path: Path) -> None:
    calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    event_path = r"\Events\Default Work Unit\Play_X"
    sound_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Localized_X"
    bus_path = r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"
    bus_id = _guid("master-bus")
    sound_id = _guid("localized-sound")
    event_id = _guid("shared-event")
    action_id = _guid("shared-action")
    sound_exists = False
    event_exists = False
    output_override_enabled = False
    output_bus_bound = False
    import_index = 0

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        nonlocal sound_exists, event_exists, output_override_enabled
        nonlocal output_bus_bound, import_index
        calls.append((uri, dict(args), dict(options)))
        if uri == "ak.wwise.core.object.create":
            return {"id": _guid("created")}
        if uri == "ak.wwise.core.object.get":
            ids = args.get("from", {}).get("id", [])
            if ids == [event_id] and args.get("transform") == [{"select": ["children"]}]:
                return {
                    "return": [
                        {
                            "id": action_id,
                            "type": "Action",
                            "ActionType": 1,
                            "Target": {"id": sound_id},
                        }
                    ]
                }
            paths = args.get("from", {}).get("path", [])
            if event_exists and paths == [event_path]:
                return {
                    "return": [
                        {
                            "id": event_id,
                            "name": "Play_X",
                            "type": "Event",
                            "path": event_path,
                            "shortId": 201,
                        }
                    ]
                }
            if paths == [bus_path]:
                return {
                    "return": [
                        {
                            "id": bus_id,
                            "name": "Master Audio Bus",
                            "type": "Bus",
                            "path": bus_path,
                            "shortId": 42,
                        }
                    ]
                }
            if sound_exists and paths == [sound_path]:
                row = {
                    "id": sound_id,
                    "name": "Localized_X",
                    "type": "Sound",
                    "path": sound_path,
                    "shortId": 202,
                }
                if output_bus_bound:
                    row["OutputBus"] = {"id": bus_id}
                return {
                    "return": [row]
                }
            return {"return": []}
        if uri == "ak.wwise.core.audio.import":
            import_index += 1
            source_id = _guid(f"localized-source-{import_index}")
            if args["importOperation"] == "createNew":
                assert not sound_exists and not event_exists
                assert args["imports"][0]["event"] == f"{event_path}@Play"
                sound_exists = True
                event_exists = True
                return {
                    "objects": [
                        {"id": sound_id},
                        {"id": event_id},
                        {"id": source_id},
                    ]
                }
            assert args["importOperation"] == "useExisting"
            assert sound_exists and event_exists
            assert set(args["imports"][0]) == {
                "audioFile",
                "objectPath",
                "importLanguage",
            }
            return {"objects": [{"id": source_id}]}
        if uri == "ak.wwise.core.object.setProperty":
            assert args == {
                "object": sound_id,
                "property": "OverrideOutput",
                "value": True,
            }
            output_override_enabled = True
            return {}
        if uri == "ak.wwise.core.object.setReference":
            assert args == {
                "object": sound_id,
                "reference": "OutputBus",
                "value": bus_id,
            }
            assert output_override_enabled
            output_bus_bound = True
            return {}
        if uri == "ak.wwise.core.soundbank.getInclusions":
            return {"inclusions": []}
        if uri == "ak.wwise.core.soundbank.generate":
            return {"logs": []}
        return {}

    backend = ClosedDirectWaapiSoundBankBackend(call)
    fixture = ObjectFixture(
        "bank:x",
        "X",
        "SoundBank",
        r"\SoundBanks\Default Work Unit",
        r"\SoundBanks\Default Work Unit\X",
    )
    backend.create_object(fixture)
    backend.read_objects(path=fixture.path)
    wav = tmp_path / "fixture.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 64)
    backend.import_media(
        MediaFixture(
            "media:x",
            wav,
            sound_path,
            event_path,
            "Chinese(PRC)",
            100,
            440,
            ("X",),
            bus_path,
            "createNew",
            True,
        )
    )
    first_graph = backend.read_event_graph(event_path)
    wav_two = tmp_path / "fixture-two.wav"
    wav_two.write_bytes(b"RIFF" + b"\x01" * 64)
    backend.import_media(
        MediaFixture(
            "media:y",
            wav_two,
            sound_path,
            event_path,
            "English(US)",
            100,
            550,
            ("X",),
            bus_path,
            "useExisting",
            False,
        )
    )
    assert backend.read_event_graph(event_path) == first_graph == EventGraphState(
        event_id,
        (action_id,),
        (sound_id,),
        (1,),
    )
    backend.read_inclusions(_guid("created"))
    backend.save_project()
    backend.generate_for_setup(
        {
            "soundbanks": [],
            "platforms": ["Windows"],
            "skipLanguages": True,
            "writeToDisk": True,
            "rebuildSoundBanks": False,
            "clearAudioFileCache": False,
            "rebuildInitBank": True,
        }
    )
    backend.delete_object(_guid("created"))

    assert calls[0][1]["onNameConflict"] == "fail"
    imports = [row for row in calls if row[0] == "ak.wwise.core.audio.import"]
    assert len(imports) == 2
    assert imports[0][1]["importOperation"] == "createNew"
    assert imports[0][1]["imports"][0]["@IsStreamingEnabled"] is True
    assert imports[0][1]["imports"][0]["objectPath"] == sound_path
    assert imports[0][2] == {"return": list(MEDIA_SOURCE_FIELDS)}
    # 2022.1 accepts the reflected ``event`` string field, but a bare Event
    # path causes Wwise to parse an empty action and reject the import.  The
    # payload must use the same explicit path@Play encoding as operation_import.
    assert imports[0][1]["imports"][0]["event"] == f"{event_path}@Play"
    assert imports[1][1]["importOperation"] == "useExisting"
    assert imports[1][2] == {"return": list(MEDIA_SOURCE_FIELDS)}
    assert imports[1][1]["imports"][0] == {
        "audioFile": str(wav_two.resolve()),
        "objectPath": (
            r"\Actor-Mixer Hierarchy\Default Work Unit"
            r"\<Sound Voice>Localized_X"
        ),
        "importLanguage": "English(US)",
    }
    localized_sound_reads = [
        row
        for row in calls
        if row[0] == "ak.wwise.core.object.get"
        and row[1].get("from", {}).get("path") == [sound_path]
        and "language" in row[2]
    ]
    assert [row[2]["language"] for row in localized_sound_reads] == [
        "Chinese(PRC)",
        "English(US)",
    ]
    assert all(
        row[2]["return"] == list(MEDIA_OBJECT_FIELDS)
        for row in localized_sound_reads
    )
    assert all(
        "<Sound " not in str(path)
        for row in calls
        if row[0] == "ak.wwise.core.object.get"
        for path in row[1].get("from", {}).get("path", [])
    )
    references = [row for row in calls if row[0] == "ak.wwise.core.object.setReference"]
    overrides = [row for row in calls if row[0] == "ak.wwise.core.object.setProperty"]
    assert len(overrides) == 1
    assert overrides[0][1] == {
        "object": sound_id,
        "property": "OverrideOutput",
        "value": True,
    }
    assert len(references) == 1
    assert references[0][1] == {
        "object": sound_id,
        "reference": "OutputBus",
        "value": bus_id,
    }
    generate = next(row for row in calls if row[0] == "ak.wwise.core.soundbank.generate")
    assert generate[1]["rebuildInitBank"] is True


def test_closed_direct_effect_fixture_copies_reviewed_factory_template() -> None:
    calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    template_id = _guid("factory-effect")
    copied_id = _guid("copied-effect")

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        calls.append((uri, dict(args), dict(options)))
        if uri == "ak.wwise.core.object.get":
            return {
                "return": [
                    {
                        "id": template_id,
                        "name": "Radio_Squish",
                        "type": "Effect",
                        "path": EFFECT_TEMPLATE_PATH,
                    }
                ]
            }
        if uri == "ak.wwise.core.object.copy":
            return {"id": copied_id}
        if uri == "ak.wwise.core.object.setName":
            return {}
        raise AssertionError(uri)

    backend = ClosedDirectWaapiSoundBankBackend(call)
    result = backend.create_object(
        ObjectFixture(
            "definition:effect",
            "Radio_Filter",
            "Effect",
            r"\Effects\Default Work Unit",
            r"\Effects\Default Work Unit\Radio_Filter",
            template_path=EFFECT_TEMPLATE_PATH,
        )
    )

    assert result == copied_id
    assert [row[0] for row in calls] == [
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.copy",
        "ak.wwise.core.object.setName",
    ]
    assert calls[1][1] == {
        "object": template_id,
        "parent": r"\Effects\Default Work Unit",
        "onNameConflict": "fail",
    }
    assert calls[2][1] == {"object": copied_id, "value": "Radio_Filter"}
