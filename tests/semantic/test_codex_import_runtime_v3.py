from __future__ import annotations

import csv
import os
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import pytest

from tests.support.platform_filesystem import create_symlink_or_skip
from tests.semantic.support import codex_import_runtime_v3 as import_runtime_v3

from tests.semantic.support.codex_eval_bundle_v3 import (
    OnlineScenario,
    load_eval_bundle_v3,
)
from tests.semantic.support.codex_compound_heavy_v1 import (
    load_compound_heavy_profile,
)
from tests.semantic.support.codex_typed_input_profile import (
    load_typed_input_profile,
)
from tests.semantic.support.codex_import_assets_v3 import (
    MaterializedImportCase,
    bind_import_live_metadata,
    materialize_import_case,
)
from tests.semantic.support.codex_import_runtime_v3 import (
    ACTION_FIELDS,
    ACTOR_DWU,
    AUDIO_SOURCE_FIELDS,
    ClosedDirectWaapiBackend,
    EVENT_FIELDS,
    EVENTS_DWU,
    OBJECT_FIELDS,
    ImportRuntimeError,
    ImportRuntimePlan,
    ImportCompoundRuntimeSnapshot,
    SetupImport,
    _copied_original_evidence,
    _validated_native_windows_original_path,
    build_import_runtime_plan,
    prepare_import_reference_fixtures,
    prepare_import_runtime,
)
from tests.semantic.support.codex_version_layout_v3 import (
    get_codex_version_layout_v3,
)


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
TYPED_PROFILE = (
    REPO_ROOT / "tests" / "semantic" / "data" / "typed-input-v1" / "profile.json"
)
IMPORT_APIS = {
    "ak.wwise.core.audio.import",
    "ak.wwise.core.audio.importTabDelimited",
}


def test_ordinary_import_runtime_accepts_the_reviewed_2021_profile_lane(
    tmp_path: Path,
) -> None:
    version = "2021.1"
    profile = load_typed_input_profile(TYPED_PROFILE)
    unit = next(
        item
        for item in profile.units
        if item.unit_id == "TYP21-FILE-AUDIO-IMPORT"
    )
    scenario = unit.scenario
    materialized = materialize_import_case(
        scenario,
        version=version,
        asset_root=tmp_path / version,
    )
    project = tmp_path / "SampleProject.wproj"
    project.write_text("<WwiseDocument/>", encoding="utf-8")

    plan = build_import_runtime_plan(
        scenario,
        materialized,
        sandbox_project=project,
    )

    assert plan.version == version


def test_ordinary_import_runtime_resolves_2021_audio_source_without_active_source(
    tmp_path: Path,
) -> None:
    version = "2021.1"
    profile = load_typed_input_profile(TYPED_PROFILE)
    unit = next(
        item
        for item in profile.units
        if item.unit_id == "TYP21-FILE-AUDIO-IMPORT"
    )
    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    project = sandbox_root / "SampleProject.wproj"
    project.write_text("<WwiseDocument/>", encoding="utf-8")
    materialized = materialize_import_case(
        unit.scenario,
        version=version,
        asset_root=tmp_path / "assets",
    )
    class _LegacyBackend(_FakeImportBackend):
        def read_objects(self, **kwargs):
            unsupported = {"activeSource", "originalFilePath"}.intersection(
                kwargs.get("fields", ())
            )
            if unsupported:
                raise ImportRuntimeError(
                    "Unknown accessor " + sorted(unsupported)[0]
                )
            return super().read_objects(**kwargs)

    backend = _LegacyBackend(sandbox_root, version=version)

    runtime = prepare_import_runtime(
        unit.scenario,
        materialized,
        sandbox_project=project,
        backend=backend,
    )

    assert runtime.hidden_before is not None
    assert all(
        row.object is None or row.object.audio_source is not None
        for row in runtime.hidden_before.rows
    )


def test_ordinary_import_runtime_rejects_unreviewed_cross_version_scenario(
    tmp_path: Path,
) -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    scenario = replace(
        bundle.scenario("O22-AUDIO-IMPORT-01"),
        versions=("2024.1",),
    )
    materialized = materialize_import_case(
        scenario,
        version="2024.1",
        asset_root=tmp_path / "unreviewed",
    )
    project = tmp_path / "SampleProject.wproj"
    project.write_text("<WwiseDocument/>", encoding="utf-8")

    with pytest.raises(ImportRuntimeError, match="does not support Wwise 2024.1"):
        build_import_runtime_plan(
            scenario,
            materialized,
            sandbox_project=project,
        )


def _guid(number: int) -> str:
    return f"{{00000000-0000-0000-0000-{number:012X}}}"


@dataclass
class _FakeObject:
    id: str
    name: str
    type: str
    path: str
    parent_id: str | None
    notes: str | None = None
    sources: dict[str, str] = field(default_factory=dict)
    original_file: str | None = None
    original_relative: str | None = None
    language: str | None = None
    action_type: int | None = None
    target: Any = None
    dynamic: dict[str, Any] = field(default_factory=dict)


class _FakeImportBackend:
    def __init__(self, sandbox_root: Path, *, version: str = "2022.1") -> None:
        self.sandbox_root = sandbox_root
        self.version = version
        self.layout = get_codex_version_layout_v3(version)
        self.objects: dict[str, _FakeObject] = {}
        self.by_path: dict[str, str] = {}
        self.sequence = 1
        self.setup_imports: list[SetupImport] = []
        self.applied_languages: list[str] = []
        self.deleted_ids: list[str] = []
        self._add_root(self.layout.actor_default_work_unit)
        self._add_root(EVENTS_DWU)
        self._add_root(self.layout.busses_dwu)
        busses = self._get_path(self.layout.busses_dwu)
        assert busses is not None
        main_name = self.layout.main_bus.rsplit("\\", 1)[1]
        self._put(
            _FakeObject(
                self._next_guid(),
                main_name,
                "Bus",
                self.layout.main_bus,
                busses.id,
            )
        )

    def _next_guid(self) -> str:
        self.sequence += 1
        return _guid(self.sequence)

    def _add_root(self, path: str) -> None:
        parent_path, name = path.rsplit("\\", 1)
        parent_id = self.by_path.get(parent_path.casefold())
        object_id = self._next_guid()
        self._put(_FakeObject(object_id, name, "WorkUnit", path, parent_id))

    def _put(self, value: _FakeObject) -> None:
        self.objects[value.id.casefold()] = value
        self.by_path[value.path.casefold()] = value.id

    def _get_path(self, path: str) -> _FakeObject | None:
        object_id = self.by_path.get(path.casefold())
        return None if object_id is None else self.objects.get(object_id.casefold())

    def read_objects(
        self,
        *,
        path: str | None = None,
        object_id: str | None = None,
        fields: Sequence[str] = (),
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        if path is not None:
            value = self._get_path(path)
        else:
            value = self.objects.get(str(object_id).casefold())
        if value is None:
            return ()
        return (self._row(value, language=language),)

    def read_direct_children(
        self,
        object_id: str,
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        rows = [
            self._row(value, language=None)
            for value in self.objects.values()
            if value.parent_id is not None
            and value.parent_id.casefold() == object_id.casefold()
        ]
        return tuple(sorted(rows, key=lambda row: str(row["path"])))

    def _row(self, value: _FakeObject, *, language: str | None) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": value.id,
            "name": value.name,
            "type": value.type,
            "path": value.path,
            "parent": value.parent_id,
            "notes": value.notes,
        }
        source_id = value.sources.get(language or "")
        if source_id is not None:
            row["activeSource"] = source_id
        if value.original_file is not None:
            row.update(
                {
                    "originalFilePath": value.original_file,
                    "audioSource:language": value.language,
                }
            )
        if value.action_type is not None:
            row["ActionType"] = value.action_type
            row["Target"] = value.target
        row.update({f"@{name}": item for name, item in value.dynamic.items()})
        return row

    def setup_create_parent(
        self, *, parent_path: str, object_type: str, name: str
    ) -> str:
        parent = self._get_path(parent_path)
        assert parent is not None
        path = parent_path + "\\" + name
        assert self._get_path(path) is None
        object_id = self._next_guid()
        self._put(_FakeObject(object_id, name, object_type, path, parent.id))
        return object_id

    def setup_create_reference_bus(self, *, parent_path: str, name: str) -> str:
        parent = self._get_path(parent_path)
        assert parent is not None
        path = parent_path + "\\" + name
        assert self._get_path(path) is None
        object_id = self._next_guid()
        self._put(_FakeObject(object_id, name, "Bus", path, parent.id))
        return object_id

    def read_bound_values(
        self,
        *,
        path: str,
        names: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        value = self._get_path(path)
        if value is None:
            return ()
        return (
            {
                "id": value.id,
                "path": value.path,
                **{f"@{name}": value.dynamic.get(name) for name in names},
            },
        )

    def setup_import(self, request: SetupImport) -> None:
        self.setup_imports.append(request)
        target_path = _normalize_typed_path(request.object_path)
        self._import(
            target_path=target_path,
            object_type=request.object_type,
            language=request.language,
            source=request.audio_file,
            originals_subfolder=request.originals_subfolder,
            notes=request.notes,
            audio_source_notes=request.audio_source_notes,
            operation=request.import_operation,
        )

    def apply_case(
        self,
        scenario: OnlineScenario,
        plan: ImportRuntimePlan,
    ) -> None:
        spec = scenario.fixture["asset_spec"]
        tab_operations = {
            row["name"]: row["import_operation"] for row in spec["tsv"]
        }
        raw_by_key = {row["row_key"]: row for row in spec["rows"]}
        for row in plan.rows:
            raw = raw_by_key[row.row_key]
            operation = spec["audio_import_operation"]
            if operation is None:
                operation = tab_operations[raw["tsv_name"]]
                location = plan.operation_requests[0]["arguments"]["import_location"][
                    "value"
                ]
                self._ensure_tab_parents(
                    import_location=str(location),
                    object_path=str(raw["object_path"]),
                )
            self.applied_languages.append(row.language)
            target = self._import(
                target_path=row.target_path,
                object_type=row.object_type,
                language=row.language,
                source=row.source_file.path,
                originals_subfolder=row.originals_subfolder,
                notes=row.notes,
                audio_source_notes=row.audio_source_notes,
                operation=operation,
            )
            if row.event_path is not None:
                self._create_event(row.event_path, target)
            for expectation in row.expected_properties:
                target.dynamic[expectation.name] = expectation.value
            for expectation in row.expected_references:
                target.dynamic[expectation.name] = {
                    "id": expectation.target_id,
                }

    def _ensure_tab_parents(
        self,
        *,
        import_location: str,
        object_path: str,
    ) -> None:
        current = import_location
        for raw in object_path.split("\\")[:-1]:
            if raw.startswith("<") and ">" in raw:
                type_label, name = raw[1:].split(">", 1)
                object_type = import_runtime_v3._create_type(type_label)
            else:
                name = raw
                object_type = "Folder"
            path = current + "\\" + name
            if self._get_path(path) is None:
                parent = self._get_path(current)
                assert parent is not None
                self._put(
                    _FakeObject(
                        self._next_guid(),
                        name,
                        object_type,
                        path,
                        parent.id,
                    )
                )
            current = path

    def _import(
        self,
        *,
        target_path: str,
        object_type: str,
        language: str,
        source: Path,
        originals_subfolder: str | None,
        notes: str | None,
        audio_source_notes: str | None,
        operation: str,
    ) -> _FakeObject:
        target = self._get_path(target_path)
        existing_use_existing = operation == "useExisting" and target is not None
        if operation == "createNew" and target is not None:
            raise AssertionError(f"createNew fixture target already exists: {target_path}")
        if operation == "replaceExisting" and target is not None:
            self._delete_tree(target.id)
            target = None
        if target is None:
            parent_path, name = target_path.rsplit("\\", 1)
            parent = self._get_path(parent_path)
            assert parent is not None
            target = _FakeObject(
                self._next_guid(),
                name,
                "Sound",
                target_path,
                parent.id,
                notes=notes,
            )
            self._put(target)
        elif notes is not None and not existing_use_existing:
            target.notes = notes

        previous_source = target.sources.get(language)
        if previous_source is not None:
            self._remove_object(previous_source)
        requested_parent = Path(
            *(originals_subfolder or "Imported").replace("\\", "/").split("/")
        )
        relative_parent = (
            Path("SFX") / requested_parent
            if language.casefold() == "sfx"
            else requested_parent
        )
        destination = self.sandbox_root / "Originals" / relative_parent / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        source_id = self._next_guid()
        source_value = _FakeObject(
            source_id,
            source.stem,
            "AudioFileSource",
            target_path + f"\\AudioSource_{language}",
            target.id,
            notes=(
                notes
                if existing_use_existing and notes is not None
                else audio_source_notes
            ),
            original_file=str(destination.resolve()),
            original_relative=str(relative_parent / source.name),
            language=language,
        )
        self.objects[source_id.casefold()] = source_value
        target.sources[language] = source_id
        return target

    def _create_event(self, path: str, target: _FakeObject) -> None:
        assert self._get_path(path) is None
        parent_path, name = path.rsplit("\\", 1)
        parent = self._get_path(parent_path)
        assert parent is not None
        event = _FakeObject(self._next_guid(), name, "Event", path, parent.id)
        self._put(event)
        action = _FakeObject(
            self._next_guid(),
            "Play",
            "Action",
            path + "\\Play",
            event.id,
            action_type=1,
            target={"id": target.id, "path": target.path},
        )
        self._put(action)

    def save_project(self) -> None:
        document = ET.Element("WwiseDocument")
        objects = ET.SubElement(document, "Objects")
        for value in sorted(self.objects.values(), key=lambda item: item.id):
            element = ET.SubElement(
                objects,
                value.type,
                {"ID": value.id, "Name": value.name},
            )
            if value.notes is not None:
                property_element = ET.SubElement(element, "Property", {"Name": "Notes"})
                ET.SubElement(property_element, "Value").text = value.notes
            if value.language is not None:
                ET.SubElement(element, "Language").text = value.language
            if value.original_relative is not None:
                ET.SubElement(element, "OriginalFile").text = value.original_relative
        ET.ElementTree(document).write(
            self.sandbox_root / "Generated.wwu",
            encoding="utf-8",
            xml_declaration=True,
        )

    def cleanup_delete(self, object_id: str) -> None:
        self.deleted_ids.append(object_id)
        self._delete_tree(object_id)

    def _delete_tree(self, object_id: str) -> None:
        value = self.objects.get(object_id.casefold())
        if value is None:
            return
        descendant_ids = [
            child.id
            for child in list(self.objects.values())
            if child.parent_id is not None
            and child.parent_id.casefold() == object_id.casefold()
        ]
        for child_id in descendant_ids:
            self._delete_tree(child_id)
        self._remove_object(object_id)

    def _remove_object(self, object_id: str) -> None:
        value = self.objects.pop(object_id.casefold(), None)
        if value is not None:
            self.by_path.pop(value.path.casefold(), None)
            for parent in self.objects.values():
                for language, source_id in list(parent.sources.items()):
                    if source_id.casefold() == object_id.casefold():
                        del parent.sources[language]


def _normalize_typed_path(value: str) -> str:
    parts = []
    for part in value.split("\\")[1:]:
        if part.startswith("<"):
            part = part.split(">", 1)[1]
        parts.append(part)
    return "\\" + "\\".join(parts)


def _scenario(scenario_id: str) -> OnlineScenario:
    return load_eval_bundle_v3(SUITE_V3).scenario(scenario_id)


def _prepared(
    tmp_path: Path,
    scenario_id: str,
) -> tuple[OnlineScenario, MaterializedImportCase, _FakeImportBackend, Any]:
    scenario = _scenario(scenario_id)
    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    project = sandbox_root / "SampleProject.wproj"
    project.write_text("<WwiseDocument/>", encoding="utf-8")
    materialized = materialize_import_case(
        scenario,
        version="2022.1",
        asset_root=tmp_path / "assets" / scenario_id,
    )
    backend = _FakeImportBackend(sandbox_root)
    runtime = prepare_import_runtime(
        scenario,
        materialized,
        sandbox_project=project,
        backend=backend,
    )
    return scenario, materialized, backend, runtime


def _metadata_record(name: str, metadata_type: str) -> dict[str, object]:
    return {
        "name": name,
        "type": metadata_type,
        "default": False,
        "display": {},
        "restriction": {},
    }


def _sound_discovery() -> dict[str, object]:
    candidates = [
        {
            "name": name,
            "kind": kind,
            "matched_queries": [],
            "same_object_dependencies": dependencies,
            "dependency_requirements": [
                {
                    "type": "override",
                    "action": "Enable",
                    "context": "Self",
                    "property": dependency,
                    "required_values": [True],
                }
                for dependency in dependencies
            ],
            "metadata": _metadata_record(name, metadata_type),
        }
        for name, kind, metadata_type, dependencies in (
            ("IsLoopingEnabled", "property", "bool", []),
            ("IgnoreParentMaxSoundInstance", "property", "bool", []),
            ("UseMaxSoundPerInstance", "property", "bool", []),
            (
                "MaxSoundPerInstance",
                "property",
                "int16",
                ["UseMaxSoundPerInstance"],
            ),
            ("OutputBus", "reference", "", ["OverrideOutput"]),
        )
    ]
    return {
        "contract": "waapi-skill.metadata-discovery/v2",
        "authority": "live-waapi",
        "result_detail": "compact",
        "scope": {
            "kind": "object_type",
            "requested": "Sound",
            "resolved": {"classId": 65552, "name": "Sound", "type": "Sound"},
        },
        "queries": ["natural business phrases"],
        "available_name_count": 100,
        "candidate_count": len(candidates),
        "query_results": [],
        "candidates": candidates,
        "dependency_candidates": [
            {
                "name": "OverrideOutput",
                "kind": "property",
                "required_by": ["OutputBus"],
                "dependency_requirements": [],
                "metadata": _metadata_record("OverrideOutput", "bool"),
            }
        ],
        "dependency_closure_complete": True,
        "unresolved_dependencies": [],
        "fallback_detail_scan": {"status": "not_needed"},
        "selection_required": True,
        "exact_live_name_required_for_mutation": True,
    }


def _compound_prepared(
    tmp_path: Path,
    *,
    unit_id: str,
):
    unit = load_compound_heavy_profile(
        COMPOUND_PROFILE,
        unit_ids=(unit_id,),
    ).units[0]
    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    project = sandbox_root / "SampleProject.wproj"
    project.write_text("<WwiseDocument/>", encoding="utf-8")
    staged = materialize_import_case(
        unit.scenario,
        version=unit.version,
        asset_root=tmp_path / "assets" / unit_id,
    )
    backend = _FakeImportBackend(sandbox_root, version=unit.version)
    fixtures = prepare_import_reference_fixtures(
        unit.scenario,
        staged,
        version=unit.version,
        backend=backend,
    )
    bound = bind_import_live_metadata(
        staged,
        version=unit.version,
        discovery_payload={"agent_result": _sound_discovery()},
        reference_targets=fixtures.request_reference_targets,
    )
    runtime = prepare_import_runtime(
        unit.scenario,
        bound,
        sandbox_project=project,
        backend=backend,
        reference_fixtures=fixtures,
    )
    return unit, bound, backend, fixtures, runtime


@pytest.mark.parametrize(
    "unit_id",
    [
        f"CMP{year}-{scenario_id}"
        for year in ("22", "25")
        for scenario_id in (
            "O22-AUDIO-IMPORT-02",
            "O22-AUDIO-IMPORT-03",
            "O22-AUDIO-TAB-03",
            "O22-AUDIO-TAB-04",
        )
    ],
)
def test_compound_import_runtime_proves_dynamic_fields_and_reference_bus_guids(
    tmp_path: Path,
    unit_id: str,
) -> None:
    unit, materialized, backend, fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id=unit_id,
    )
    before = runtime.hidden_before

    assert isinstance(before, ImportCompoundRuntimeSnapshot)
    assert runtime.plan.version == unit.version
    assert runtime.plan.actor_dwu == get_codex_version_layout_v3(
        unit.version
    ).actor_default_work_unit
    assert fixtures.adopted
    assert len(fixtures.fixtures) == len(fixtures.reference_targets)
    assert set(fixtures.request_reference_targets) == set(
        fixtures.reference_targets
    )
    binding_targets = materialized.metadata_binding["reference_targets"]
    request_values: set[str] = set()

    def collect_request_values(value: Any) -> None:
        if isinstance(value, Mapping):
            for child in value.values():
                collect_request_values(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect_request_values(child)
        elif isinstance(value, str):
            request_values.add(value)

    collect_request_values(materialized.operation_requests)
    table_surface = "".join(
        item.path.read_text(encoding="utf-8") for item in materialized.tab_files
    )
    oracle_reference_ids = {
        reference.target_id
        for row in runtime.plan.rows
        for reference in row.expected_references
    }
    for item in fixtures.fixtures:
        request_target = fixtures.request_reference_targets[item.key]
        oracle_target = fixtures.reference_targets[item.key]
        assert request_target == {"kind": "path", "value": item.path}
        assert oracle_target == {"kind": "id", "value": item.id}
        assert binding_targets[item.key] == request_target
        assert item.path in request_values or item.path in table_surface
        assert item.id not in request_values
        assert item.id not in table_surface
        assert item.id in oracle_reference_ids
    assert all(
        item.id.casefold() != fixtures.main_bus.id.casefold()
        for item in fixtures.fixtures
    )
    assert runtime.verify_preview_unchanged().passed

    backend.apply_case(unit.scenario, runtime.plan)
    verification = runtime.verify_after_execution()

    assert verification.passed, verification.failures
    assert isinstance(verification.after, ImportCompoundRuntimeSnapshot)
    for row_plan in runtime.plan.rows:
        state = verification.after.row(row_plan.row_key)
        if (
            row_plan.preserve_property_tokens
            or row_plan.preserve_reference_tokens
        ):
            before_state = before.row(row_plan.row_key)
            assert tuple(item.name for item in state.properties) == (
                row_plan.preserve_property_tokens
            )
            assert tuple(item.name for item in state.references) == (
                row_plan.preserve_reference_tokens
            )
            assert state.properties == before_state.properties
            assert state.references == before_state.references
        else:
            assert {item.name: item.value for item in state.properties} == {
                item.name: item.value for item in row_plan.expected_properties
            }
            assert {
                item.name: item.target_id for item in state.references
            } == {
                item.name: item.target_id for item in row_plan.expected_references
            }
        assert all(
            item.target_id is None
            or item.target_id.casefold() != fixtures.main_bus.id.casefold()
            for item in state.references
        )

    cleanup = runtime.cleanup_success()
    assert cleanup.paths_absent
    assert cleanup.assets_removed
    assert fixtures.cleaned
    assert all(
        not backend.read_objects(path=path, fields=EVENT_FIELDS)
        for path in fixtures.paths
    )


def test_compound_use_existing_rows_may_omit_dynamic_expectations_but_not_half_bind(
    tmp_path: Path,
) -> None:
    unit, materialized, backend, fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id="CMP22-O22-AUDIO-TAB-04",
    )

    assert all(
        not row.expected_properties and not row.expected_references
        for row in runtime.plan.rows[:3]
    )
    expected_property_tokens = (
        "IsLoopingEnabled",
        "IgnoreParentMaxSoundInstance",
        "UseMaxSoundPerInstance",
        "MaxSoundPerInstance",
        "OverrideOutput",
    )
    assert all(
        row.preserve_property_tokens == expected_property_tokens
        and row.preserve_reference_tokens == ("OutputBus",)
        and row.pre_state_file is not None
        and row.pre_state_file.sha256 != row.source_file.sha256
        for row in runtime.plan.rows[:3]
    )
    assert all(
        row["compound_dynamic_mode"] == "preserve"
        for row in materialized.expected_rows[:3]
    )
    assert all(
        row.expected_properties and row.expected_references
        for row in runtime.plan.rows[3:]
    )
    assert all(
        row["compound_dynamic_mode"] == "mutate"
        for row in materialized.expected_rows[3:]
    )

    rows = [dict(row) for row in materialized.expected_rows]
    dynamic_index = next(
        index
        for index, row in enumerate(rows)
        if row["compound_effective_properties"]
        and row["compound_effective_references"]
    )
    rows[dynamic_index]["compound_effective_references"] = []
    malformed = replace(materialized, expected_rows=tuple(rows))

    with pytest.raises(
        ImportRuntimeError,
        match="property and reference expectations together or omit both",
    ):
        prepare_import_runtime(
            unit.scenario,
            malformed,
            sandbox_project=runtime.plan.sandbox_project,
            backend=backend,
            reference_fixtures=fixtures,
        )

    rows = [dict(row) for row in materialized.expected_rows]
    rows[dynamic_index]["compound_effective_properties"] = []
    rows[dynamic_index]["compound_effective_references"] = []
    missing_both = replace(materialized, expected_rows=tuple(rows))

    with pytest.raises(
        ImportRuntimeError,
        match="mutate row requires dynamic expectations",
    ):
        prepare_import_runtime(
            unit.scenario,
            missing_both,
            sandbox_project=runtime.plan.sandbox_project,
            backend=backend,
            reference_fixtures=fixtures,
        )

    rows = [dict(row) for row in materialized.expected_rows]
    rows[0]["compound_dynamic_mode"] = "mutate"
    relabeled_preserve = replace(materialized, expected_rows=tuple(rows))

    with pytest.raises(
        ImportRuntimeError,
        match="dynamic mode differs from the reviewed case spec",
    ):
        prepare_import_runtime(
            unit.scenario,
            relabeled_preserve,
            sandbox_project=runtime.plan.sandbox_project,
            backend=backend,
            reference_fixtures=fixtures,
        )


@pytest.mark.parametrize("drift_kind", ("property", "reference"))
def test_compound_preserve_row_rejects_any_dynamic_value_drift(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    unit, _materialized, backend, fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id="CMP22-O22-AUDIO-TAB-04",
    )
    preserve = runtime.plan.rows[0]
    backend.apply_case(unit.scenario, runtime.plan)
    target = backend._get_path(preserve.target_path)
    assert target is not None
    if drift_kind == "property":
        target.dynamic[preserve.preserve_property_tokens[0]] = True
    else:
        target.dynamic[preserve.preserve_reference_tokens[0]] = {
            "id": fixtures.fixtures[0].id,
        }

    verification = runtime.verify_after_execution()

    assert not verification.passed
    assert any(
        "changed during media replacement" in failure
        for failure in verification.failures
    )


def test_compound_preserve_oracle_does_not_change_mutate_row_semantics(
    tmp_path: Path,
) -> None:
    unit, _materialized, backend, _fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id="CMP25-O22-AUDIO-TAB-04",
    )
    mutate_rows = [
        row
        for row in runtime.plan.rows
        if row.expected_properties or row.expected_references
    ]
    assert mutate_rows
    assert all(
        not row.preserve_property_tokens and not row.preserve_reference_tokens
        for row in mutate_rows
    )

    backend.apply_case(unit.scenario, runtime.plan)
    verification = runtime.verify_after_execution()

    verification.assert_passed()
    assert isinstance(verification.after, ImportCompoundRuntimeSnapshot)
    for row in mutate_rows:
        state = verification.after.row(row.row_key)
        assert {item.name: item.value for item in state.properties} == {
            item.name: item.value for item in row.expected_properties
        }
        assert {
            item.name: item.target_id for item in state.references
        } == {
            item.name: item.target_id for item in row.expected_references
        }


def test_compound_preserve_mode_rejects_wrong_boundary_and_equal_media(
    tmp_path: Path,
) -> None:
    unit, materialized, _backend, fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id="CMP22-O22-AUDIO-TAB-04",
    )
    rows = [dict(row) for row in materialized.expected_rows]
    rows[0]["guid_policy"] = "preserve_shared_existing_guid"
    wrong_boundary = replace(materialized, expected_rows=tuple(rows))
    with pytest.raises(ImportRuntimeError, match="preserve mode is only valid"):
        build_import_runtime_plan(
            unit.scenario,
            wrong_boundary,
            sandbox_project=runtime.plan.sandbox_project,
            reference_fixtures=fixtures,
        )

    staged = materialize_import_case(
        unit.scenario,
        version=unit.version,
        asset_root=tmp_path / "equal-media-assets",
    )
    preserve_raw = staged.expected_rows[0]
    pre_key = preserve_raw["pre_state"]["media_sha256_key"]
    source_key = preserve_raw["source_key"]
    source_sha256 = next(
        item.sha256 for item in staged.source_files if item.key == source_key
    )
    pre_files = tuple(
        replace(item, sha256=source_sha256)
        if item.key == pre_key
        else item
        for item in staged.pre_state_files
    )
    equal_media = replace(staged, pre_state_files=pre_files)
    equal_sandbox = tmp_path / "equal-media-sandbox"
    equal_sandbox.mkdir()
    equal_project = equal_sandbox / "SampleProject.wproj"
    equal_project.write_text("<WwiseDocument/>", encoding="utf-8")
    equal_backend = _FakeImportBackend(equal_sandbox)
    equal_fixtures = prepare_import_reference_fixtures(
        unit.scenario,
        equal_media,
        version=unit.version,
        backend=equal_backend,
    )
    equal_media = bind_import_live_metadata(
        equal_media,
        version=unit.version,
        discovery_payload={"agent_result": _sound_discovery()},
        reference_targets=equal_fixtures.request_reference_targets,
    )
    with pytest.raises(ImportRuntimeError, match="media hashes are equal"):
        build_import_runtime_plan(
            unit.scenario,
            equal_media,
            sandbox_project=equal_project,
            reference_fixtures=equal_fixtures,
        )


def test_compound_reference_fixture_handle_emergency_cleanup_is_idempotent(
    tmp_path: Path,
) -> None:
    unit = load_compound_heavy_profile(
        COMPOUND_PROFILE,
        unit_ids=("CMP22-O22-AUDIO-IMPORT-02",),
    ).units[0]
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    staged = materialize_import_case(
        unit.scenario,
        version=unit.version,
        asset_root=tmp_path / "assets",
    )
    backend = _FakeImportBackend(sandbox)
    fixtures = prepare_import_reference_fixtures(
        unit.scenario,
        staged,
        version=unit.version,
        backend=backend,
    )

    first = fixtures.cleanup_emergency()
    second = fixtures.cleanup_emergency()

    assert first.paths_absent and not first.already_clean
    assert second.paths_absent and second.already_clean


def test_compound_prepare_failure_rolls_back_adopted_reference_fixtures(
    tmp_path: Path,
) -> None:
    unit = load_compound_heavy_profile(
        COMPOUND_PROFILE,
        unit_ids=("CMP22-O22-AUDIO-IMPORT-02",),
    ).units[0]
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    project = sandbox / "SampleProject.wproj"
    project.write_text("<WwiseDocument/>", encoding="utf-8")
    asset_root = tmp_path / "assets"
    staged = materialize_import_case(
        unit.scenario,
        version=unit.version,
        asset_root=asset_root,
    )
    backend = _FakeImportBackend(sandbox)
    fixtures = prepare_import_reference_fixtures(
        unit.scenario,
        staged,
        version=unit.version,
        backend=backend,
    )
    bound = bind_import_live_metadata(
        staged,
        version=unit.version,
        discovery_payload={"agent_result": _sound_discovery()},
        reference_targets=fixtures.request_reference_targets,
    )
    actor_root = backend._get_path(
        get_codex_version_layout_v3(unit.version).actor_default_work_unit
    )
    assert actor_root is not None
    backend.cleanup_delete(actor_root.id)

    with pytest.raises(
        ImportRuntimeError,
        match="required Wwise fixture root is unavailable",
    ):
        prepare_import_runtime(
            unit.scenario,
            bound,
            sandbox_project=project,
            backend=backend,
            reference_fixtures=fixtures,
        )

    assert fixtures.adopted and fixtures.cleaned
    assert not asset_root.exists()
    assert all(
        not backend.read_objects(path=path, fields=EVENT_FIELDS)
        for path in fixtures.paths
    )


def test_compound_runtime_rejects_reference_target_or_dynamic_readback_drift(
    tmp_path: Path,
) -> None:
    unit, _, backend, fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id="CMP25-O22-AUDIO-IMPORT-02",
    )
    backend.apply_case(unit.scenario, runtime.plan)
    first = runtime.plan.rows[0]
    target = backend._get_path(first.target_path)
    assert target is not None
    target.dynamic[first.expected_references[0].name] = {
        "id": fixtures.main_bus.id,
    }
    dependency = first.expected_references[0].activation_properties[0]
    target.dynamic[dependency.name] = False

    verification = runtime.verify_after_execution()

    assert not verification.passed
    assert any("target GUID mismatch" in item for item in verification.failures)
    assert any("local @" in item for item in verification.failures)


def test_all_ten_import_cases_build_and_prepare_with_hidden_live_state(tmp_path) -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    scenarios = [case for case in bundle.scenarios if case.api in IMPORT_APIS]
    assert len(scenarios) == 10

    for scenario in scenarios:
        root = tmp_path / scenario.id
        root.mkdir()
        current, _, backend, runtime = _prepared(root, scenario.id)
        assert runtime.plan.scenario_id == current.id
        assert len(runtime.plan.rows) == len(current.fixture["asset_spec"]["rows"])
        assert runtime.hidden_before is not None
        assert runtime.verify_preview_unchanged().passed
        assert "00000000-0000" not in runtime.render_prompt()
        cleanup = runtime.cleanup_success()
        assert cleanup.paths_absent
        assert cleanup.assets_removed
        assert backend.deleted_ids


def test_sfx_fixture_and_generated_tables_use_subfolders_relative_to_sfx_root(
    tmp_path: Path,
) -> None:
    scenarios = [
        case
        for case in load_eval_bundle_v3(SUITE_V3).scenarios
        if case.api in IMPORT_APIS
    ]
    reviewed_sfx_rows = 0
    generated_sfx_import_rows = 0
    generated_sfx_cells = 0
    for scenario in scenarios:
        root = tmp_path / scenario.id
        root.mkdir()
        materialized = materialize_import_case(
            scenario,
            version="2022.1",
            asset_root=root / "assets",
        )
        for row in materialized.expected_rows:
            subfolder = row.get("originals_subfolder")
            if row.get("language") != "SFX" or not isinstance(subfolder, str):
                continue
            reviewed_sfx_rows += 1
            assert re.split(r"[\\/]", subfolder, maxsplit=1)[0].casefold() != "sfx"

        for request in materialized.operation_requests:
            if request["operation"] != "audio.import":
                continue
            for row in request["arguments"]["imports"]:
                if row.get("import_language") != "SFX":
                    continue
                subfolder = row.get("originals_subfolder")
                assert isinstance(subfolder, str)
                generated_sfx_import_rows += 1
                assert (
                    re.split(r"[\\/]", subfolder, maxsplit=1)[0].casefold()
                    != "sfx"
                )

        table_specs = {
            row["name"]: row for row in scenario.fixture["asset_spec"]["tsv"]
        }
        for table in materialized.tab_files:
            if table_specs[table.key]["language"] != "SFX":
                continue
            with table.path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    subfolder = row.get("OriginalsSubFolder")
                    if not subfolder:
                        continue
                    generated_sfx_cells += 1
                    assert (
                        re.split(r"[\\/]", subfolder, maxsplit=1)[0].casefold()
                        != "sfx"
                    )

    assert reviewed_sfx_rows == 49
    assert generated_sfx_import_rows == 25
    assert generated_sfx_cells == 24


def test_import_runtime_rejects_sfx_prefixed_reviewed_subfolder_instead_of_stripping_it(
    tmp_path: Path,
) -> None:
    scenario, materialized, _, runtime = _prepared(
        tmp_path,
        "O22-AUDIO-IMPORT-02",
    )
    rows = [dict(row) for row in materialized.expected_rows]
    sfx_index = next(
        index
        for index, row in enumerate(rows)
        if row.get("language") == "SFX"
        and isinstance(row.get("originals_subfolder"), str)
    )
    rows[sfx_index]["originals_subfolder"] = (
        "SFX/" + rows[sfx_index]["originals_subfolder"]
    )
    malformed = replace(materialized, expected_rows=tuple(rows))

    with pytest.raises(ImportRuntimeError, match="automatic Originals/SFX base"):
        build_import_runtime_plan(
            scenario,
            malformed,
            sandbox_project=runtime.plan.sandbox_project,
        )


def test_sfx_runtime_oracle_models_wwise_automatic_originals_base(
    tmp_path: Path,
) -> None:
    scenario, _, backend, runtime = _prepared(tmp_path, "O22-AUDIO-TAB-05")

    backend.apply_case(scenario, runtime.plan)
    result = runtime.verify_after_execution()

    result.assert_passed()
    relative_paths = [
        row.object.audio_source.original_relative_path
        for row in result.after.rows
        if row.language == "SFX"
        and row.object is not None
        and row.object.audio_source is not None
    ]
    assert relative_paths
    assert all(path.startswith("SFX/") for path in relative_paths)
    assert all(not path.startswith("SFX/SFX/") for path in relative_paths)


def test_use_existing_preserves_hidden_guids_and_replaces_each_media_hash(tmp_path) -> None:
    scenario, _, backend, runtime = _prepared(tmp_path, "O22-AUDIO-IMPORT-01")
    before = runtime.hidden_before
    assert before is not None
    old_ids = {
        row.row_key: before.row(row.row_key).object.id
        for row in runtime.plan.rows
        if row.pre_state_existence == "existing"
        and before.row(row.row_key).object is not None
    }

    backend.apply_case(scenario, runtime.plan)
    result = runtime.verify_after_execution()
    result.assert_passed()
    for row_key, old_id in old_ids.items():
        current = result.after.row(row_key).object
        assert current is not None and current.id == old_id
        plan_row = next(row for row in runtime.plan.rows if row.row_key == row_key)
        assert current.audio_source is not None
        assert current.audio_source.original_file.sha256 == plan_row.source_file.sha256


def test_absent_audio_source_notes_accept_wwise_empty_string_readback(
    tmp_path: Path,
) -> None:
    scenario, _, backend, runtime = _prepared(
        tmp_path,
        "O22-AUDIO-IMPORT-01",
    )
    backend.apply_case(scenario, runtime.plan)
    row = next(
        item
        for item in runtime.plan.rows
        if item.notes is None and item.audio_source_notes is None
    )
    target = backend._get_path(row.target_path)
    assert target is not None
    source = backend.objects[target.sources[row.language].casefold()]
    source.notes = ""

    runtime.verify_after_execution().assert_passed()


def test_absent_object_notes_accept_wwise_empty_string_readback(
    tmp_path: Path,
) -> None:
    scenario, _, backend, runtime = _prepared(
        tmp_path,
        "O22-AUDIO-TAB-02",
    )
    backend.apply_case(scenario, runtime.plan)
    row = next(
        item
        for item in runtime.plan.rows
        if item.pre_state_existence == "absent" and item.notes is None
    )
    target = backend._get_path(row.target_path)
    assert target is not None
    target.notes = ""

    runtime.verify_after_execution().assert_passed()


def test_nonempty_object_notes_mismatch_remains_strict(
    tmp_path: Path,
) -> None:
    scenario, _, backend, runtime = _prepared(
        tmp_path,
        "O22-AUDIO-IMPORT-01",
    )
    backend.apply_case(scenario, runtime.plan)
    row = next(item for item in runtime.plan.rows if item.notes is not None)
    target = backend._get_path(row.target_path)
    assert target is not None
    target.notes = ""

    result = runtime.verify_after_execution()

    assert not result.passed
    assert f"{row.row_key} Notes mismatch" in result.failures


def test_nonempty_audio_source_notes_mismatch_remains_strict(
    tmp_path: Path,
) -> None:
    scenario, _, backend, runtime = _prepared(
        tmp_path,
        "O22-AUDIO-TAB-03",
    )
    backend.apply_case(scenario, runtime.plan)
    row = next(
        item for item in runtime.plan.rows if item.audio_source_notes is not None
    )
    target = backend._get_path(row.target_path)
    assert target is not None
    source = backend.objects[target.sources[row.language].casefold()]
    source.notes = ""

    result = runtime.verify_after_execution()

    assert not result.passed
    assert (
        f"{row.row_key} Audio Source Notes mismatch"
        in result.failures
    )


@pytest.mark.parametrize(
    "scenario_id",
    ["O22-AUDIO-IMPORT-04", "O22-AUDIO-TAB-05"],
)
def test_replace_existing_removes_every_old_guid_and_persists_new_ones(
    tmp_path, scenario_id: str
) -> None:
    scenario, _, backend, runtime = _prepared(tmp_path, scenario_id)
    before = runtime.hidden_before
    assert before is not None
    old_ids = [state.object.id for state in before.rows if state.object is not None]

    backend.apply_case(scenario, runtime.plan)
    result = runtime.verify_after_execution()
    result.assert_passed()
    new_ids = [state.object.id for state in result.after.rows if state.object is not None]
    assert set(old_ids).isdisjoint(new_ids)
    assert all(not backend.read_objects(object_id=old_id) for old_id in old_ids)


def test_tab02_keeps_three_transaction_language_order_and_shared_object_guids(tmp_path) -> None:
    scenario, materialized, backend, runtime = _prepared(
        tmp_path, "O22-AUDIO-TAB-02"
    )
    assert [
        request["arguments"]["import_language"]
        for request in materialized.operation_requests
    ] == ["Chinese(PRC)", "English(US)", "Japanese"]

    backend.apply_case(scenario, runtime.plan)
    result = runtime.verify_after_execution()
    result.assert_passed()
    assert backend.applied_languages == [
        "Chinese(PRC)",
        "Chinese(PRC)",
        "Chinese(PRC)",
        "Chinese(PRC)",
        "English(US)",
        "English(US)",
        "English(US)",
        "English(US)",
        "Japanese",
        "Japanese",
        "Japanese",
        "Japanese",
    ]
    by_path: dict[str, set[str]] = {}
    for row in result.after.rows:
        assert row.object is not None
        by_path.setdefault(row.target_path, set()).add(row.object.id)
    assert all(len(ids) == 1 for ids in by_path.values())
    assert len(by_path) == 4


def test_localized_baseline_creates_each_absent_voice_once_then_adds_languages(
    tmp_path: Path,
) -> None:
    _, _, backend, runtime = _prepared(tmp_path, "O22-AUDIO-TAB-02")

    by_target: dict[str, list[SetupImport]] = {}
    for request in backend.setup_imports:
        target = _normalize_typed_path(request.object_path).casefold()
        by_target.setdefault(target, []).append(request)

    assert len(by_target) == 2
    assert all(
        [request.import_operation for request in requests]
        == ["createNew", "useExisting", "useExisting"]
        for requests in by_target.values()
    )
    assert all(
        requests[0].notes is not None
        and requests[0].originals_subfolder is None
        and all(
            request.notes is None and request.originals_subfolder is None
            for request in requests[1:]
        )
        for requests in by_target.values()
    )
    assert all(
        [request.language for request in requests]
        == ["Chinese(PRC)", "English(US)", "Japanese"]
        for requests in by_target.values()
    )
    assert runtime.hidden_before is not None
    runtime.verify_preview_unchanged().assert_passed()


def test_unique_existing_baselines_are_created_with_create_new(tmp_path: Path) -> None:
    _, _, backend, _ = _prepared(tmp_path, "O22-AUDIO-IMPORT-01")

    assert len(backend.setup_imports) == 6
    assert {request.import_operation for request in backend.setup_imports} == {
        "createNew"
    }


def test_saved_xml_counts_audio_source_definitions_not_active_source_references(
    tmp_path: Path,
) -> None:
    _, _, _, runtime = _prepared(tmp_path, "O22-AUDIO-IMPORT-01")
    before = runtime.hidden_before
    assert before is not None
    first = before.rows[0].object
    assert first is not None and first.audio_source is not None
    source_id = first.audio_source.id
    active_reference = import_runtime_v3.XmlIdentityEvidence(
        guid=source_id,
        relative_file="Generated.wwu",
        element_tag="ActiveSource",
        name="active source reference",
    )
    with_reference = replace(
        before,
        xml_identities=(*before.xml_identities, active_reference),
    )

    failures = import_runtime_v3._validate_saved_xml(
        runtime.plan,
        with_reference,
        before=True,
    )
    assert not any("Audio Source GUID" in failure for failure in failures)

    duplicate_definition = replace(
        active_reference,
        element_tag="AudioFileSource",
        name="duplicate source definition",
    )
    with_duplicate_definition = replace(
        with_reference,
        xml_identities=(*with_reference.xml_identities, duplicate_definition),
    )
    failures = import_runtime_v3._validate_saved_xml(
        runtime.plan,
        with_duplicate_definition,
        before=True,
    )
    assert any("Audio Source GUID" in failure for failure in failures)


def test_saved_xml_counts_sound_definitions_not_event_object_references(
    tmp_path: Path,
) -> None:
    scenario, _, backend, runtime = _prepared(tmp_path, "O22-AUDIO-IMPORT-03")
    backend.apply_case(scenario, runtime.plan)
    after = runtime.snapshot(save=True)
    first = after.rows[0].object
    assert first is not None
    object_reference = import_runtime_v3.XmlIdentityEvidence(
        guid=first.id,
        relative_file="Events.wwu",
        element_tag="ObjectRef",
        name="Play target reference",
    )
    with_reference = replace(
        after,
        xml_identities=(*after.xml_identities, object_reference),
    )

    failures = import_runtime_v3._validate_saved_xml(
        runtime.plan,
        with_reference,
        before=False,
        old=runtime.hidden_before,
    )
    assert not any(
        f"{runtime.plan.rows[0].row_key} GUID" in failure
        for failure in failures
    )

    duplicate_definition = replace(
        object_reference,
        element_tag="Sound",
        name="duplicate Sound definition",
    )
    with_duplicate_definition = replace(
        with_reference,
        xml_identities=(*with_reference.xml_identities, duplicate_definition),
    )
    failures = import_runtime_v3._validate_saved_xml(
        runtime.plan,
        with_duplicate_definition,
        before=False,
        old=runtime.hidden_before,
    )
    assert any(
        f"{runtime.plan.rows[0].row_key} GUID" in failure
        for failure in failures
    )


def test_tab01_missing_media_refusal_proves_zero_project_side_effects(tmp_path) -> None:
    _, materialized, backend, runtime = _prepared(tmp_path, "O22-AUDIO-TAB-01")
    assert runtime.plan.expected_primary_dispatch_count == 0
    assert not backend.setup_imports
    missing = [item for item in materialized.source_files if not item.present]
    assert len(missing) == 1 and not missing[0].path.exists()
    runtime.verify_zero_dispatch_unchanged().assert_passed()


def test_audio_import_event_rows_persist_one_play_action_bound_to_each_sound(tmp_path) -> None:
    scenario, _, backend, runtime = _prepared(tmp_path, "O22-AUDIO-IMPORT-03")
    backend.apply_case(scenario, runtime.plan)
    result = runtime.verify_after_execution()
    result.assert_passed()
    assert len(result.after.events) == 4
    assert all(event.child_count == 1 for event in result.after.events)
    assert all(event.action_type == 1 for event in result.after.events)


def test_tab_create_new_leaves_table_owned_ancestors_for_primary_dispatch(
    tmp_path: Path,
) -> None:
    scenario, _, backend, runtime = _prepared(tmp_path, "O22-AUDIO-TAB-03")

    assert tuple(parent.path for parent in runtime.plan.parents) == (
        "\\Actor-Mixer Hierarchy\\Default Work Unit\\Ambience",
        "\\Actor-Mixer Hierarchy\\Default Work Unit\\Ambience\\City",
    )
    assert backend.read_objects(
        path="\\Actor-Mixer Hierarchy\\Default Work Unit\\Ambience\\City\\中央区"
    ) == ()

    backend.apply_case(scenario, runtime.plan)
    result = runtime.verify_after_execution()
    result.assert_passed()
    assert all(
        "_01" not in row.object.path
        for row in result.after.rows
        if row.object is not None
    )


def test_copied_original_relative_path_is_derived_with_and_without_requested_subfolder(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    nested = project_root / "Originals" / "SFX" / "Reviewed" / "nested.wav"
    defaulted = project_root / "Originals" / "Imported" / "default.wav"
    nested.parent.mkdir(parents=True)
    defaulted.parent.mkdir(parents=True)
    nested.write_bytes(b"RIFF-nested")
    defaulted.write_bytes(b"RIFF-default")

    nested_proof, nested_relative = _copied_original_evidence(
        nested,
        project_root=project_root,
    )
    default_proof, default_relative = _copied_original_evidence(
        defaulted,
        project_root=project_root,
    )

    assert nested_relative == "SFX/Reviewed/nested.wav"
    assert default_relative == "Imported/default.wav"
    assert nested_proof.relative_path == "Originals/SFX/Reviewed/nested.wav"
    assert default_proof.relative_path == "Originals/Imported/default.wav"


def test_copied_original_posix_z_and_y_paths_seal_identical_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login_home = tmp_path / "login-home"
    project_root = login_home / "case" / "project"
    copied = project_root / "Originals" / "Voices" / "English" / "line.wav"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(b"RIFF-equivalent-paths")
    monkeypatch.setattr(
        import_runtime_v3,
        "pwd",
        SimpleNamespace(
            getpwuid=lambda _uid: SimpleNamespace(pw_dir=str(login_home))
        ),
    )

    posix = str(copied)
    z_path = (
        str(copied)
        if os.name == "nt"
        else str(PureWindowsPath("Z:/", *copied.parts[1:]))
    )
    y_relative = copied.relative_to(login_home)
    y_path = str(PureWindowsPath("Y:/", *y_relative.parts))

    posix_result = _copied_original_evidence(posix, project_root=project_root)
    z_result = _copied_original_evidence(z_path, project_root=project_root)
    y_result = _copied_original_evidence(y_path, project_root=project_root)

    assert posix_result == z_result == y_result
    proof, relative = posix_result
    assert proof.relative_path == "Originals/Voices/English/line.wav"
    assert relative == "Voices/English/line.wav"


def test_native_windows_original_path_accepts_drive_absolute_without_wine_mapping() -> None:
    assert _validated_native_windows_original_path(
        r"C:\Project\Originals\Voices\line.wav"
    ) == PureWindowsPath(r"C:\Project\Originals\Voices\line.wav")
    assert _validated_native_windows_original_path(
        "d:/Project/Originals/SFX/hit.wav"
    ) == PureWindowsPath(r"D:\Project\Originals\SFX\hit.wav")


@pytest.mark.parametrize(
    "unsafe",
    (
        r"\\server\share\line.wav",
        r"Originals\line.wav",
        r"\Originals\line.wav",
        r"C:Originals\line.wav",
        r"C:\Originals\..\outside.wav",
        r"C:\Originals\.\line.wav",
        r"C:\Originals\\line.wav",
    ),
)
def test_native_windows_original_path_rejects_unc_relative_and_traversal(
    unsafe: str,
) -> None:
    with pytest.raises(ImportRuntimeError):
        _validated_native_windows_original_path(unsafe)


@pytest.mark.parametrize(
    "unsafe",
    (
        "",
        "relative/file.wav",
        "~/file.wav",
        "C:\\tmp\\file.wav",
        "\\\\server\\share\\file.wav",
        "/tmp//file.wav",
        "/tmp/./file.wav",
        "/tmp/../file.wav",
        "Y:",
        "Z:\\tmp\\..\\file.wav",
    ),
)
def test_copied_original_rejects_untrusted_path_spellings(
    tmp_path: Path,
    unsafe: str,
) -> None:
    project_root = tmp_path / "project"
    (project_root / "Originals").mkdir(parents=True)
    with pytest.raises(ImportRuntimeError):
        _copied_original_evidence(unsafe, project_root=project_root)


def test_import_without_requested_originals_subfolder_uses_derived_evidence(
    tmp_path: Path,
) -> None:
    scenario, _, backend, runtime = _prepared(tmp_path, "O22-AUDIO-IMPORT-01")
    first = runtime.plan.rows[0]
    runtime.plan = replace(
        runtime.plan,
        rows=(replace(first, originals_subfolder=None), *runtime.plan.rows[1:]),
    )

    backend.apply_case(scenario, runtime.plan)
    result = runtime.verify_after_execution()
    result.assert_passed()
    state = result.after.row(first.row_key).object
    assert state is not None and state.audio_source is not None
    assert state.audio_source.original_relative_path.startswith("Imported/")


def test_copied_original_evidence_rejects_escape_and_symlink_components(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    originals = project_root / "Originals"
    originals.mkdir(parents=True)
    escaped = tmp_path / "outside.wav"
    escaped.write_bytes(b"RIFF-outside")
    with pytest.raises(ImportRuntimeError, match="escapes"):
        _copied_original_evidence(escaped, project_root=project_root)

    real = originals / "real"
    real.mkdir()
    target = real / "target.wav"
    target.write_bytes(b"RIFF-target")
    link = originals / "linked"
    create_symlink_or_skip(link, real, target_is_directory=True)
    with pytest.raises(ImportRuntimeError, match="symlink"):
        _copied_original_evidence(link / target.name, project_root=project_root)


def test_wrong_copied_subfolder_cannot_be_masked_by_legacy_relative_accessor(
    tmp_path: Path,
) -> None:
    scenario, _, backend, runtime = _prepared(tmp_path, "O22-AUDIO-IMPORT-01")
    backend.apply_case(scenario, runtime.plan)
    row = next(
        item for item in runtime.plan.rows if item.originals_subfolder is not None
    )
    target = backend._get_path(row.target_path)
    assert target is not None
    source = backend.objects[target.sources[row.language].casefold()]
    wrong = runtime.plan.sandbox_root / "Originals" / "Wrong" / row.source_file.path.name
    wrong.parent.mkdir(parents=True)
    shutil.copyfile(row.source_file.path, wrong)
    source.original_file = str(wrong.resolve())
    source.original_relative = f"{row.originals_subfolder}/{wrong.name}"

    result = runtime.verify_after_execution()
    assert not result.passed
    assert any("Originals subfolder mismatch" in failure for failure in result.failures)


def test_legacy_relative_accessor_cannot_replace_absolute_copied_file_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, _, backend, runtime = _prepared(tmp_path, "O22-AUDIO-IMPORT-01")
    backend.apply_case(scenario, runtime.plan)
    original_read = backend.read_objects

    def legacy_only_read(**kwargs: Any) -> tuple[Mapping[str, Any], ...]:
        rows = [dict(row) for row in original_read(**kwargs)]
        for row in rows:
            if row.get("type") == "AudioFileSource":
                row.pop("originalFilePath", None)
                row["originalRelativeFilePath"] = "Voices/Chapter06/English/legacy.wav"
        return tuple(rows)

    monkeypatch.setattr(backend, "read_objects", legacy_only_read)
    with pytest.raises(ImportRuntimeError, match="absolute path"):
        runtime.snapshot(save=True)


def test_success_cleanup_removes_assets_and_all_scenario_owned_object_roots(tmp_path) -> None:
    scenario, _, backend, runtime = _prepared(tmp_path, "O22-AUDIO-TAB-04")
    backend.apply_case(scenario, runtime.plan)
    runtime.verify_after_execution().assert_passed()
    owned_paths = [parent.path for parent in runtime.plan.parents]
    result = runtime.cleanup_success()

    assert result.assets_removed and result.paths_absent
    assert not runtime.plan.asset_root.exists()
    assert all(not backend.read_objects(path=path) for path in owned_paths)


def test_closed_direct_backend_emits_only_reviewed_read_setup_save_cleanup_shapes(
    tmp_path,
) -> None:
    calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def call(
        uri: str, args: Mapping[str, Any], options: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        calls.append((uri, args, options))
        if uri == "ak.wwise.core.object.create":
            return {"id": _guid(88)}
        if uri == "ak.wwise.core.object.get":
            return {"return": []}
        return {}

    audio = tmp_path / "fixture.wav"
    audio.write_bytes(b"RIFF-closed-test")
    backend = ClosedDirectWaapiBackend(call)
    backend.read_objects(path=ACTOR_DWU, fields=OBJECT_FIELDS)
    backend.read_objects(object_id=_guid(2), fields=AUDIO_SOURCE_FIELDS)
    backend.read_direct_children(_guid(1), fields=ACTION_FIELDS)
    assert (
        backend.setup_create_parent(
            parent_path=ACTOR_DWU,
            object_type="Folder",
            name="ClosedFixture",
        )
        == _guid(88)
    )
    backend.setup_import(
        SetupImport(
            object_path=ACTOR_DWU + r"\ClosedFixture\<Sound SFX>Ping",
            object_type="Sound SFX",
            language="SFX",
            audio_file=audio,
            import_operation="createNew",
            originals_subfolder="SFX/Closed",
            notes="closed",
            audio_source_notes=None,
        )
    )
    backend.save_project()
    backend.cleanup_delete(_guid(88))

    assert [row[0] for row in calls] == [
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.create",
        "ak.wwise.core.audio.import",
        "ak.wwise.core.project.save",
        "ak.wwise.core.object.delete",
    ]
    import_call = next(row for row in calls if row[0] == "ak.wwise.core.audio.import")
    assert import_call[1]["importOperation"] == "createNew"
    assert import_call[1]["autoAddToSourceControl"] is False
    assert set(import_call[1]) == {
        "importOperation",
        "imports",
        "autoAddToSourceControl",
    }
    requested_returns = [
        options["return"]
        for _, _, options in calls
        if isinstance(options.get("return"), list)
    ]
    assert requested_returns
    assert all(
        "originalRelativeFilePath" not in fields for fields in requested_returns
    )
    assert next(row for row in calls if row[0] == "ak.wwise.core.project.save")[1:] == ({}, {})
    assert next(row for row in calls if row[0] == "ak.wwise.core.object.delete")[1] == {
        "object": _guid(88)
    }


def test_closed_direct_backend_localized_use_existing_wire_has_only_three_fields(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def call(
        uri: str, args: Mapping[str, Any], options: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        calls.append((uri, args, options))
        return {}

    audio = tmp_path / "japanese.wav"
    audio.write_bytes(b"RIFF-localized-existing")
    backend = ClosedDirectWaapiBackend(call)
    backend.setup_import(
        SetupImport(
            object_path=ACTOR_DWU + r"\Dialogue\<Sound Voice>Line01",
            object_type="Sound Voice",
            language="Japanese",
            audio_file=audio,
            import_operation="useExisting",
            originals_subfolder=None,
            notes=None,
            audio_source_notes=None,
        )
    )

    assert calls == [
        (
            "ak.wwise.core.audio.import",
            {
                "importOperation": "useExisting",
                "imports": [
                    {
                        "audioFile": str(audio.resolve()),
                        "objectPath": ACTOR_DWU
                        + r"\Dialogue\<Sound Voice>Line01",
                        "importLanguage": "Japanese",
                    }
                ],
                "autoAddToSourceControl": False,
            },
            {"return": list(OBJECT_FIELDS)},
        )
    ]


def test_closed_direct_backend_rejects_extra_localized_use_existing_setup_fields(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "japanese.wav"
    audio.write_bytes(b"RIFF-localized-existing")
    backend = ClosedDirectWaapiBackend(lambda *_args: {})

    with pytest.raises(ImportRuntimeError, match="only audioFile"):
        backend.setup_import(
            SetupImport(
                object_path=ACTOR_DWU + r"\Dialogue\<Sound Voice>Line01",
                object_type="Sound Voice",
                language="Japanese",
                audio_file=audio,
                import_operation="useExisting",
                originals_subfolder="Voices/Japanese",
                notes=None,
                audio_source_notes=None,
            )
        )
