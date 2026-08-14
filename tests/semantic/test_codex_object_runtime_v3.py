from __future__ import annotations

import copy
import json
import wave
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic.support import codex_heavy_project_runner_v3 as project_runner
from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
from tests.semantic.support.codex_object_heavy_v3 import (
    MaterializedObject,
    MaterializedReference,
    ObjectProperty,
    OperationRequestSpec,
    QueryObjectRequestSpec,
    all_object_heavy_v3_recipes,
    build_object_heavy_v3_recipe,
)
from tests.semantic.support.codex_object_runtime_v3 import (
    ClosedDirectObjectBackend,
    ObjectRuntimeError,
    ObjectRuntimeSnapshot,
    PreparedObjectRuntime,
    _language_name,
    bounded_result_disclosure,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    materialize_typed_transaction_protocol_requests,
)


SUITE_V3 = "skills/waapi-skill/evals/suite-v3.json"
REPLACE_CASE_ID = "OBJ22-F-CREATE-05"


def _guid(index: int) -> str:
    return f"{{{index:08X}-0000-0000-0000-{index:012X}}}"


def _row(item: MaterializedObject, *, path: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "id": item.id,
        "name": item.name,
        "type": item.type,
        "path": path or item.path,
        "parent": {"id": item.parent_id} if item.parent_id is not None else None,
        "notes": item.notes,
        "childrenCount": item.children_count,
    }
    for prop in item.properties:
        result[f"@{prop.name}"] = prop.value
    for reference in item.references:
        result[reference.name] = {"id": reference.target_id}
    if item.type in {
        "ActorMixer",
        "PropertyContainer",
        "RandomSequenceContainer",
        "Sound",
    }:
        result["OverrideOutput"] = any(
            reference.name == "OutputBus" for reference in item.references
        )
    if item.source_language is not None:
        result["audioSource:language"] = item.source_language
    if item.active_source_id is not None:
        result["activeSource"] = {"id": item.active_source_id}
    if item.is_included is not None:
        result["isIncluded"] = item.is_included
    return result


@pytest.mark.parametrize(
    ("version", "expected_properties", "expected_required"),
    (
        ("2021.1", {"objects"}, set()),
        ("2022.1", {"objects"}, set()),
        ("2023.1", {"files", "log", "objects"}, {"files", "log", "objects"}),
        ("2024.1", {"files", "log", "objects"}, {"files", "log", "objects"}),
        ("2025.1", {"files", "log", "objects"}, {"files", "log", "objects"}),
    ),
)
def test_object_fixture_audio_import_result_contract_is_versioned(
    version: str,
    expected_properties: set[str],
    expected_required: set[str],
) -> None:
    manifest = json.loads(
        Path(
            f"skills/waapi-skill/resources/manifest/{version}/schemas.json"
        ).read_text(encoding="utf-8")
    )
    row = next(
        item
        for item in manifest["schemas"]
        if item["uri"] == "ak.wwise.core.audio.import"
    )
    result_schema = row["schema"]["resultSchema"]

    assert set(result_schema["properties"]) == expected_properties
    assert result_schema["properties"]["objects"]["type"] == "array"
    assert set(result_schema.get("required", [])) == expected_required


def _fixture_objects(
    case_id: str,
    version: str = "2022.1",
) -> tuple[MaterializedObject, ...]:
    recipe = build_object_heavy_v3_recipe(case_id, version)
    ordered_fixture = sorted(
        recipe.fixture.objects,
        key=lambda item: (item.path.count("\\"), item.path),
    )
    ids = {
        item.key: _guid(index)
        for index, item in enumerate(recipe.fixture.objects, start=1)
    }
    keys_by_path = {item.path: item.key for item in recipe.fixture.objects}
    child_counts = {
        item.key: sum(
            candidate.parent_path == item.path
            for candidate in recipe.fixture.objects
        )
        for item in recipe.fixture.objects
    }
    return tuple(
        MaterializedObject(
            key=item.key,
            id=ids[item.key],
            name=item.name,
            type=item.object_type,
            path=item.path,
            parent_id=(
                ids[keys_by_path[item.parent_path]]
                if item.parent_path in keys_by_path
                else None
            ),
            notes=item.notes or "",
            properties=item.properties,
            references=tuple(
                MaterializedReference(row.name, ids[row.target_key])
                for row in item.references
            ),
            source_language=item.source_language,
            is_included=item.is_included,
            children_count=child_counts[item.key],
            active_source_id=(
                _guid(10_000 + index)
                if item.source_language is not None
                else None
            ),
            active_source_name=(
                item.key if item.source_language is not None else None
            ),
            active_source_path=(
                f"{item.path}\\{item.key}"
                if item.source_language is not None
                else None
            ),
        )
        for index, item in enumerate(ordered_fixture, start=1)
    )


def _replace_before_objects() -> tuple[MaterializedObject, ...]:
    return _fixture_objects(REPLACE_CASE_ID)


class _ReplaceAfterBackend:
    def __init__(self, before: tuple[MaterializedObject, ...]) -> None:
        recipe = build_object_heavy_v3_recipe(REPLACE_CASE_ID)
        before_by_key = {item.key: item for item in before}
        new_ids = {
            item.key: _guid(index)
            for index, item in enumerate(recipe.oracle.expected_objects, start=101)
        }
        after: dict[str, MaterializedObject] = {}
        for expected in recipe.oracle.expected_objects:
            parent = after.get(expected.parent_key or "") or before_by_key.get(
                expected.parent_key or ""
            )
            assert expected.path is not None
            after[expected.key] = MaterializedObject(
                key=expected.key,
                id=new_ids[expected.key],
                name=expected.requested_name,
                type=expected.object_type,
                path=expected.path,
                parent_id=parent.id if parent is not None else None,
                notes="新脚步原型" if expected.key == "new_proto" else "",
                properties=(),
                references=(),
                source_language=None,
                is_included=None,
                children_count=len(expected.children),
            )

        visible = {
            **after,
            **{
                key: before_by_key[key]
                for key in recipe.oracle.protected_snapshot_keys
            },
        }
        self.rows_by_path = {
            item.path: _row(item)
            for item in visible.values()
        }
        self.rows_by_id = {
            item.id: _row(item)
            for item in visible.values()
        }
        self.children_by_id = {
            after[expected.key].id: tuple(
                _row(visible[child_key])
                for child_key in expected.children
            )
            for expected in recipe.oracle.expected_objects
            if expected.children
        }
        self.read_id_calls: list[str] = []

    def read_path(self, path, *, fields=()):
        row = self.rows_by_path.get(path)
        return (row,) if row is not None else ()

    def read_id(self, object_id, *, fields=()):
        self.read_id_calls.append(object_id)
        row = self.rows_by_id.get(object_id)
        return (row,) if row is not None else ()

    def read_children(self, object_id, *, fields=()):
        return self.children_by_id.get(object_id, ())


def _replace_runtime():
    bundle = load_eval_bundle_v3(SUITE_V3)
    scenario = next(case for case in bundle.scenarios if case.id == REPLACE_CASE_ID)
    recipe = build_object_heavy_v3_recipe(REPLACE_CASE_ID)
    before = _replace_before_objects()
    backend = _ReplaceAfterBackend(before)
    runtime = PreparedObjectRuntime(
        scenario=scenario,
        recipe=recipe,
        backend=backend,
    )
    runtime.before = ObjectRuntimeSnapshot(before, (), (), "sealed-before")
    return runtime, backend, {item.key: item for item in before}


class _StateBackend:
    """Small mutable object-graph backend for snapshot/oracle regressions."""

    def __init__(self, objects: tuple[MaterializedObject, ...]) -> None:
        self.set_objects(objects)

    def set_objects(self, objects: tuple[MaterializedObject, ...]) -> None:
        self.objects = objects
        self.read_path_calls: list[tuple[str, str | None]] = []
        self.read_id_calls: list[tuple[str, str | None]] = []
        self.rows_by_path = {item.path: _row(item) for item in objects}
        self.rows_by_id = {item.id: _row(item) for item in objects}
        self.active_source_ids: dict[str, str] = {}
        for index, item in enumerate(objects, start=10_000):
            if item.source_language is None:
                continue
            active_source_id = item.active_source_id or _guid(index)
            active_source_name = item.active_source_name or item.key
            active_source_path = item.active_source_path or f"{item.path}\\{active_source_name}"
            self.active_source_ids[item.id] = active_source_id
            self.rows_by_path[item.path]["activeSource"] = {"id": active_source_id}
            self.rows_by_id[item.id]["activeSource"] = {"id": active_source_id}
            self.rows_by_id[active_source_id] = {
                "id": active_source_id,
                "name": active_source_name,
                "type": "AudioFileSource",
                "path": active_source_path,
                "parent": {"id": item.id},
                "audioSource:language": item.source_language,
            }
        self.children_by_id: dict[str, tuple[dict[str, object], ...]] = {}
        for parent in objects:
            self.children_by_id[parent.id] = tuple(
                _row(child) for child in objects if child.parent_id == parent.id
            )

    def read_path(self, path, *, fields=(), language=None):
        self.read_path_calls.append((path, language))
        row = self.rows_by_path.get(path)
        return (row,) if row is not None else ()

    def read_id(self, object_id, *, fields=(), language=None):
        self.read_id_calls.append((object_id, language))
        row = self.rows_by_id.get(object_id)
        return (row,) if row is not None else ()

    def read_children(self, object_id, *, fields=()):
        return self.children_by_id.get(object_id, ())


def _scenario(case_id: str):
    bundle = load_eval_bundle_v3(SUITE_V3)
    return next(case for case in bundle.scenarios if case.id == case_id)


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        (None, None),
        ("SFX", "SFX"),
        ({"name": "SFX"}, "SFX"),
        ({"id": "{LANG}", "type": "Language", "name": "English(US)"}, "English(US)"),
        (
            {
                "name": "Japanese",
                "displayName": "Japanese",
                "shortName": "Japanese",
            },
            "Japanese",
        ),
    ),
)
def test_language_name_normalizes_closed_waapi_reference_shapes(raw, expected) -> None:
    assert _language_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    (
        "",
        {},
        {"name": ""},
        {"displayName": 7},
        {"name": "SFX", "displayName": "Japanese"},
        [],
        True,
    ),
)
def test_language_name_rejects_missing_or_conflicting_reference_shapes(raw) -> None:
    with pytest.raises(ObjectRuntimeError, match="audio source language"):
        _language_name(raw)


def test_get01_snapshot_canonicalizes_language_reference_objects() -> None:
    case_id = "OBJ22-F-GET-01"
    objects = _fixture_objects(case_id)
    backend = _StateBackend(objects)
    expected_languages = {
        item.key: item.source_language
        for item in objects
        if item.source_language is not None
    }
    for item in objects:
        if item.source_language is None:
            continue
        language = {
            "id": f"{{LANG-{item.key}}}",
            "type": "Language",
            "name": item.source_language,
        }
        active_source_id = backend.active_source_ids[item.id]
        backend.rows_by_id[active_source_id]["audioSource:language"] = language
        # The Sound-level display value is deliberately malformed: the snapshot
        # must use the active AudioFileSource, not this convenience field.
        backend.rows_by_path[item.path]["audioSource:language"] = {}
        backend.rows_by_id[item.id]["audioSource:language"] = {}

    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=build_object_heavy_v3_recipe(case_id),
        backend=backend,
    )
    snapshot = runtime.snapshot()

    assert {
        item.key: item.source_language
        for item in snapshot.objects
        if item.source_language is not None
    } == expected_languages


@pytest.mark.parametrize(
    "active_source_shape",
    (
        lambda source_id: source_id,
        lambda source_id: {"id": source_id},
    ),
    ids=("string-id", "reference-object"),
)
def test_get01_snapshot_accepts_closed_active_source_identity_shapes(
    active_source_shape,
) -> None:
    case_id = "OBJ22-F-GET-01"
    recipe = build_object_heavy_v3_recipe(case_id)
    objects = _fixture_objects(case_id)
    backend = _StateBackend(objects)
    sound = next(item for item in objects if item.source_language is not None)
    source_id = backend.active_source_ids[sound.id]
    backend.rows_by_path[sound.path]["activeSource"] = active_source_shape(source_id)
    backend.rows_by_id[sound.id]["activeSource"] = active_source_shape(source_id)

    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id), recipe=recipe, backend=backend
    )

    snapshot = runtime.snapshot()

    assert snapshot.by_key()[sound.key].source_language == sound.source_language


def test_get01_2021_snapshot_resolves_audio_source_without_active_source_accessor() -> None:
    case_id = "OBJ22-F-GET-01"
    recipe = build_object_heavy_v3_recipe(case_id, "2021.1")
    objects = _fixture_objects(case_id, "2021.1")

    class _LegacyBackend(_StateBackend):
        def read_path(self, path, *, fields=(), language=None):
            unsupported = {"activeSource", "isIncluded"}.intersection(fields)
            if not fields or unsupported:
                raise ObjectRuntimeError(
                    f"Unknown accessor {sorted(unsupported)[0]}"
                )
            return super().read_path(path, fields=fields, language=language)

        def read_children(self, object_id, *, fields=()):
            if not fields or "activeSource" in fields:
                raise ObjectRuntimeError("Unknown accessor activeSource")
            rows = list(super().read_children(object_id, fields=fields))
            source_id = self.active_source_ids.get(object_id)
            if source_id is not None:
                rows.append(self.rows_by_id[source_id])
            return tuple(rows)

    backend = _LegacyBackend(objects)
    scenario = replace(_scenario(case_id), versions=("2021.1",))
    runtime = PreparedObjectRuntime(
        scenario=scenario,
        recipe=recipe,
        backend=backend,
    )

    snapshot = runtime.snapshot()

    expected = {
        item.key: item.source_language
        for item in objects
        if item.source_language is not None
    }
    assert {
        item.key: item.source_language
        for item in snapshot.objects
        if item.source_language is not None
    } == expected


def test_2021_snapshot_projection_excludes_unreflected_accessors() -> None:
    definitions = json.loads(
        Path(
            "skills/waapi-skill/resources/manifest/2021.1/definitions.json"
        ).read_text(encoding="utf-8")
    )
    return_expression = definitions["documents"]["waapi_definitions.json"][
        "definitions"
    ]["returnExpression"]
    reflected = set(return_expression["items"]["anyOf"][0]["enum"])

    assert "activeSource" not in reflected
    assert "isIncluded" not in reflected
    assert "audioSource:language" in reflected


def test_get01_2021_snapshot_rejects_a_second_direct_audio_source() -> None:
    case_id = "OBJ22-F-GET-01"
    recipe = build_object_heavy_v3_recipe(case_id, "2021.1")
    objects = _fixture_objects(case_id, "2021.1")

    class _AmbiguousLegacyBackend(_StateBackend):
        def read_path(self, path, *, fields=(), language=None):
            if not fields or "activeSource" in fields:
                raise ObjectRuntimeError("Unknown accessor activeSource")
            return super().read_path(path, fields=fields, language=language)

        def read_children(self, object_id, *, fields=()):
            rows = list(super().read_children(object_id, fields=fields))
            source_id = self.active_source_ids.get(object_id)
            if source_id is not None:
                rows.extend(
                    (
                        self.rows_by_id[source_id],
                        {
                            "id": _guid(99_998),
                            "name": "Unexpected_Source",
                            "type": "AudioFileSource",
                            "path": next(
                                item.path
                                for item in self.objects
                                if item.id == object_id
                            )
                            + r"\Unexpected_Source",
                            "parent": {"id": object_id},
                            "audioSource:language": "SFX",
                        },
                    )
                )
            return tuple(rows)

    backend = _AmbiguousLegacyBackend(objects)
    runtime = PreparedObjectRuntime(
        scenario=replace(_scenario(case_id), versions=("2021.1",)),
        recipe=recipe,
        backend=backend,
    )

    with pytest.raises(ObjectRuntimeError, match="resolve exactly once"):
        runtime.snapshot()


def test_read_only_object_protocol_uses_the_existing_simple_typed_flags(
    tmp_path: Path,
) -> None:
    scenario = replace(_scenario("OBJ22-F-GET-01"), versions=("2021.1",))
    recipe = build_object_heavy_v3_recipe(scenario.id, version="2021.1")
    runtime = PreparedObjectRuntime(
        scenario=scenario,
        recipe=recipe,
        backend=_StateBackend(_fixture_objects(scenario.id, "2021.1")),
        asset_root=tmp_path,
    )

    protocol = runtime.gateway_protocol()

    assert tuple(step.subcommand for step in protocol.steps) == ("query-object",)
    assert "--where-json" not in protocol.steps[0].arguments
    assert protocol.steps[0].arguments[protocol.steps[0].arguments.index("--where") :] == (
        "--where",
        "type",
        "=",
        "string",
        "Sound",
        "--take",
        "24",
        "--return-field",
        "id",
        "--return-field",
        "name",
        "--return-field",
        "type",
        "--return-field",
        "path",
        "--return-field",
        "@Volume",
        "--return-field",
        "notes",
        "--return-field",
        "OutputBus",
    )


@pytest.mark.parametrize(
    "mutation, match",
    (
        (
            lambda backend, sound: (
                backend.rows_by_path[sound.path].pop("activeSource"),
                backend.rows_by_id[sound.id].pop("activeSource"),
            ),
            "missing activeSource identity",
        ),
        (
            lambda backend, sound: (
                backend.rows_by_path[sound.path].__setitem__("activeSource", {}),
                backend.rows_by_id[sound.id].__setitem__("activeSource", {}),
            ),
            "missing activeSource identity",
        ),
        (
            lambda backend, sound: backend.rows_by_id[
                backend.active_source_ids[sound.id]
            ].__setitem__("type", "Sound"),
            "must be an AudioFileSource",
        ),
        (
            lambda backend, sound: backend.rows_by_id[
                backend.active_source_ids[sound.id]
            ].__setitem__("parent", {"id": _guid(99_999)}),
            "parent identity mismatch",
        ),
        (
            lambda backend, sound: backend.rows_by_id[
                backend.active_source_ids[sound.id]
            ].__setitem__("audioSource:language", "Japanese"),
            "activeSource language",
        ),
        (
            lambda backend, sound: backend.rows_by_id[
                backend.active_source_ids[sound.id]
            ].__setitem__("audioSource:language", {}),
            "audio source language reference",
        ),
    ),
    ids=("missing", "malformed-reference", "wrong-type", "wrong-parent", "wrong-language", "malformed-source-language"),
)
def test_get01_snapshot_rejects_missing_or_mismatched_active_source(
    mutation,
    match,
) -> None:
    case_id = "OBJ22-F-GET-01"
    recipe = build_object_heavy_v3_recipe(case_id)
    objects = _fixture_objects(case_id)
    backend = _StateBackend(objects)
    sound = next(item for item in objects if item.source_language is not None)
    # Preserve the old Sound-level field so this proves there is no fallback.
    backend.rows_by_path[sound.path]["audioSource:language"] = sound.source_language
    backend.rows_by_id[sound.id]["audioSource:language"] = sound.source_language
    mutation(backend, sound)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id), recipe=recipe, backend=backend
    )

    with pytest.raises(ObjectRuntimeError, match=match):
        runtime.snapshot()


def test_get02_snapshot_reads_sound_and_active_source_in_same_language_context() -> None:
    case_id = "OBJ22-F-GET-02"
    recipe = build_object_heavy_v3_recipe(case_id)
    objects = _fixture_objects(case_id)
    backend = _StateBackend(objects)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id), recipe=recipe, backend=backend
    )

    snapshot = runtime.snapshot()

    japanese = next(item for item in objects if item.source_language == "Japanese")
    source_id = backend.active_source_ids[japanese.id]
    assert snapshot.by_key()[japanese.key].source_language == "Japanese"
    assert (japanese.path, "Japanese") in backend.read_path_calls
    assert (source_id, "Japanese") in backend.read_id_calls


def _get02_query_runtime():
    case_id = "OBJ22-F-GET-02"
    objects = _fixture_objects(case_id)
    backend = _StateBackend(objects)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=build_object_heavy_v3_recipe(case_id),
        backend=backend,
    )
    runtime.before = runtime.snapshot()
    before = runtime.before.by_key()
    request = runtime.recipe.request
    assert isinstance(request, QueryObjectRequestSpec)
    primary = [_row(before[key]) for key in request.bounded_superset_keys]
    derived = [
        copy.deepcopy(backend.rows_by_id[before[key].active_source_id])
        for key in request.bounded_superset_keys
        if before[key].type == "Sound"
    ]
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "query-object",
        "objects": [*primary, *derived],
    }
    payload["count"] = len(payload["objects"])
    payload["query_bound"] = {"mode": "take", "value": request.take}
    return runtime, payload, _get02_valid_answer(before)


def _get02_valid_answer(before: dict[str, MaterializedObject]) -> str:
    rows = []
    for child_key in ("hero_damage", "hero_greeting", "npc_alert", "npc_idle"):
        child = before[child_key]
        parent = next(item for item in before.values() if item.id == child.parent_id)
        volume = next(value.value for value in child.properties if value.name == "Volume")
        rows.append(
            f"| `{parent.path}` | `{child.path}` | {child.source_language} | "
            f"{float(volume):.1f} dB | {child.notes} |"
        )
    return "\n".join(
        (
            "| Parent | Sound | Language | Volume | Notes |",
            "|---|---|---|---:|---|",
            *rows,
        )
    )


def test_get02_query_oracle_accepts_exact_active_sources_and_paired_paths() -> None:
    runtime, payload, answer = _get02_query_runtime()

    verification = runtime.verify_query_result(payload, final_response=answer)

    assert verification.passed, verification.failures
    assert len(verification.evidence["observed_keys"]) == 14
    assert len(verification.evidence["derived_rows"]) == 8
    assert verification.evidence["observed_answer_order"] == [
        "hero_damage",
        "hero_greeting",
        "npc_alert",
        "npc_idle",
    ]


@pytest.mark.parametrize(
    ("mutation", "failure"),
    (
        (lambda rows: rows.pop(), "count differs"),
        (
            lambda rows: rows.append(
                {
                    "id": _guid(999_001),
                    "name": "unknown",
                    "type": "AudioFileSource",
                    "path": r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\unknown",
                    "parent": {"id": _guid(999_002)},
                    "audioSource:language": "SFX",
                }
            ),
            "unknown activeSource identity",
        ),
        (lambda rows: rows.append(copy.deepcopy(rows[0])), "duplicated"),
        (
            lambda rows: rows[0].__setitem__("id", _guid(999_003)),
            "unknown activeSource identity",
        ),
        (
            lambda rows: rows[0].__setitem__("audioSource:language", "SFX"),
            ".language differs",
        ),
        (
            lambda rows: rows[0].__setitem__("parent", {"id": _guid(999_004)}),
            ".parent_id differs",
        ),
        (
            lambda rows: rows[0].__setitem__("name", "wrong_source"),
            ".name differs",
        ),
        (
            lambda rows: rows[0].__setitem__("path", str(rows[0]["path"]) + "_wrong"),
            ".path differs",
        ),
        (
            lambda rows: rows[0].__setitem__("type", "Sound"),
            ".type differs",
        ),
    ),
    ids=(
        "missing",
        "extra",
        "duplicate",
        "wrong-active-id",
        "wrong-language",
        "wrong-parent",
        "wrong-name",
        "wrong-path",
        "wrong-type",
    ),
)
def test_get02_query_oracle_rejects_invalid_derived_sources(
    mutation,
    failure: str,
) -> None:
    runtime, payload, answer = _get02_query_runtime()
    rows = payload["objects"]
    assert isinstance(rows, list)
    derived = rows[14:]
    mutation(derived)
    payload["objects"] = [*rows[:14], *derived]

    verification = runtime.verify_query_result(payload, final_response=answer)

    assert not verification.passed
    assert any(failure in item for item in verification.failures)


@pytest.mark.parametrize(
    ("mutation", "failure"),
    (
        (
            lambda answer, before: answer.replace(
                f"`{before['vo_hero'].path}` | ",
                "",
            ),
            "standalone path identity vo_hero",
        ),
        (
            lambda answer, before: answer.replace("Japanese | -4.0", "English(US) | -4.0", 1),
            "language differs for hero_damage",
        ),
        (
            lambda answer, before: answer.replace("-4.0 dB", "-9.0 dB", 1),
            "Volume differs for hero_damage",
        ),
        (
            lambda answer, before: answer.replace("hero damage |", "wrong note |", 1),
            "notes differ for hero_damage",
        ),
        (
            lambda answer, before: answer.replace(
                f"`{before['vo_hero'].path}` | `{before['hero_damage'].path}`",
                f"`{before['vo_npc'].path}` | `{before['hero_damage'].path}`",
                1,
            ),
            "pair hero_damage",
        ),
        (
            lambda answer, before: "\n".join(
                [*answer.splitlines()[:2], answer.splitlines()[3], answer.splitlines()[2], *answer.splitlines()[4:]]
            ),
            "row order differs",
        ),
        (
            lambda answer, before: answer + f"\nExcluded: `{before['hero_nested'].path}`",
            "excluded standalone path hero_nested",
        ),
    ),
    ids=("prefix-only-parent", "wrong-language", "wrong-volume", "wrong-notes", "wrong-pair", "wrong-order", "excluded"),
)
def test_get02_query_oracle_rejects_wrong_paired_answer(
    mutation,
    failure: str,
) -> None:
    runtime, payload, answer = _get02_query_runtime()
    before = runtime.before.by_key()

    verification = runtime.verify_query_result(
        payload,
        final_response=mutation(answer, before),
    )

    assert not verification.passed
    assert any(failure in item for item in verification.failures)


def _get04_query_runtime():
    case_id = "OBJ22-F-GET-04"
    objects = _fixture_objects(case_id)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=build_object_heavy_v3_recipe(case_id),
        backend=_StateBackend(objects),
    )
    runtime.before = runtime.snapshot()
    before = runtime.before.by_key()
    request = runtime.recipe.request
    assert isinstance(request, QueryObjectRequestSpec)
    raw_keys = [
        *("q4_pistol",) * 3,
        *("q4_rifle",) * 4,
        *("q4_shotgun",) * 3,
    ]
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "query-object",
        "count": 10,
        "query_bound": {"mode": "take", "value": 10},
        "objects": [_row(before[key]) for key in raw_keys],
    }
    by_id = {item.id: item for item in before.values()}
    rows = []
    for key in request.exact_expected_keys:
        parent = before[key]
        bus_id = next(
            item.target_id for item in parent.references if item.name == "OutputBus"
        )
        bus = by_id[bus_id]
        rows.append(
            f"| {parent.name} | {parent.id} | `{parent.path}` | "
            f"{parent.children_count} | {parent.notes} | {bus.name} |"
        )
    answer = "\n".join(
        (
            "| 名称 | GUID | 路径 | 直接子对象数 | 备注 | Output Bus |",
            "|---|---|---|---:|---|---|",
            *rows,
            "汇总：命中 3 个父容器，确认覆盖 10 个直接子 Sound；10 条上限已触及，结果可能不完整。",
        )
    )
    return runtime, payload, answer


def test_get04_query_oracle_accepts_duplicate_parent_rows_and_bounded_summary() -> None:
    runtime, payload, answer = _get04_query_runtime()

    verification = runtime.verify_query_result(payload, final_response=answer)

    assert verification.passed, verification.failures
    assert verification.evidence["observed_keys"] == [
        *("q4_pistol",) * 3,
        *("q4_rifle",) * 4,
        *("q4_shotgun",) * 3,
    ]
    assert verification.evidence["bound_reached"] is True
    assert verification.evidence["coverage_summary"] == {
        "unique_parent_count": 3,
        "confirmed_sound_count": 10,
        "direct_child_object_count": 12,
        "summary_line_index": 5,
        "bound_disclosed": True,
        "incomplete_disclosed": True,
        "claims_twelve_sounds": False,
    }


@pytest.mark.parametrize(
    "disclosure",
    (
        "本次返回 10 条，达到 take=10 上限，不能证明没有更多结果。",
        "当前 10 条正好等于查询边界；若要确认完整集合，需要提高上限继续查询。",
        "The query returned 10 rows, hit take=10; this cannot prove there are no more.",
        "若要确认全部结果，需提高 take 上限后继续查询。",
        "查询已达到 `take=10` 上限，因此父容器列表及覆盖数量可能不完整。",
    ),
)
def test_get04_query_oracle_accepts_equivalent_bound_disclosures(
    disclosure: str,
) -> None:
    runtime, payload, answer = _get04_query_runtime()
    response = answer.replace(
        "10 条上限已触及，结果可能不完整。",
        disclosure,
    )

    verification = runtime.verify_query_result(payload, final_response=response)

    assert verification.passed, verification.failures
    assert verification.evidence["coverage_summary"]["bound_disclosed"] is True
    assert (
        verification.evidence["coverage_summary"]["incomplete_disclosed"]
        is True
    )


@pytest.mark.parametrize(
    "disclosure",
    (
        "查询使用 take=10。",
        "本次未达到 10 条上限，结果完整，没有更多。",
        "本次返回 10 条。",
        "10 条上限已触及，结果完整。",
    ),
)
def test_get04_query_oracle_rejects_missing_or_negated_bound_disclosure(
    disclosure: str,
) -> None:
    runtime, payload, answer = _get04_query_runtime()
    response = answer.replace(
        "10 条上限已触及，结果可能不完整。",
        disclosure,
    )

    verification = runtime.verify_query_result(payload, final_response=response)

    assert not verification.passed
    assert "reached-bound/incomplete disclosure" in " ".join(
        verification.failures
    )


def test_bound_disclosure_parser_does_not_treat_take_mention_as_disclosure() -> None:
    assert bounded_result_disclosure("查询使用 take=10。", take=10) == (
        False,
        False,
    )
    assert bounded_result_disclosure(
        "本次未达到 10 条上限，结果完整，没有更多。",
        take=10,
    ) == (False, False)


@pytest.mark.parametrize(
    ("disclosure", "expected"),
    (
        (
            "查询已达到 `take=10` 上限，因此父容器列表及覆盖数量可能不完整。",
            (True, True),
        ),
        (
            "查询使用 take=10，因此父容器列表及覆盖数量可能不完整。",
            (False, True),
        ),
        (
            "查询未达到 take=10 上限，因此父容器列表及覆盖数量可能不完整。",
            (False, True),
        ),
        (
            "查询已达到 take=10 上限，父容器列表及覆盖数量完整。",
            (True, False),
        ),
    ),
)
def test_bound_disclosure_parser_handles_explicit_business_collection_subjects(
    disclosure: str,
    expected: tuple[bool, bool],
) -> None:
    assert bounded_result_disclosure(disclosure, take=10) == expected


def test_get04_query_oracle_accepts_r62_negated_twelve_object_clarification() -> None:
    runtime, payload, answer = _get04_query_runtime()
    response = (
        answer
        + "\n直接子对象总数为 12（此数包含所有子对象，不等同于已确认的 Sound 数）。"
    )

    verification = runtime.verify_query_result(payload, final_response=response)

    assert verification.passed, verification.failures
    assert verification.evidence["coverage_summary"][
        "claims_twelve_sounds"
    ] is False


def test_get04_query_oracle_rejects_positive_claim_before_unrelated_negation() -> None:
    runtime, payload, answer = _get04_query_runtime()
    response = answer + "\n确认覆盖 12 个 Sound，但这不是最终完整结果。"

    verification = runtime.verify_query_result(payload, final_response=response)

    assert not verification.passed
    assert "overclaims 12 confirmed Sound edges" in " ".join(
        verification.failures
    )


@pytest.mark.parametrize(
    ("mutation", "failure"),
    (
        (
            lambda payload, answer: (
                payload["objects"][0].__setitem__("childrenCount", 99),
                answer,
            )[1],
            "childrenCount differs from sealed parent",
        ),
        (
            lambda payload, answer: answer.replace(
                "确认覆盖 10 个直接子 Sound", "确认覆盖 12 个直接子 Sound"
            ),
            "overclaims 12 confirmed Sound edges",
        ),
        (
            lambda payload, answer: answer.replace("结果可能不完整", "结果完整"),
            "incomplete disclosure",
        ),
        (
            lambda payload, answer: answer.replace(" | 5 | parent-review Shotgun", " | 4 | parent-review Shotgun"),
            "childrenCount differs for q4_shotgun",
        ),
    ),
    ids=("raw-field", "overclaim-12", "no-incomplete-caveat", "final-child-count"),
)
def test_get04_query_oracle_rejects_tampered_duplicate_or_summary(
    mutation,
    failure: str,
) -> None:
    runtime, payload, answer = _get04_query_runtime()

    verification = runtime.verify_query_result(
        payload,
        final_response=mutation(payload, answer),
    )

    assert not verification.passed
    assert any(failure in item for item in verification.failures)


def _get05_query_runtime():
    case_id = "OBJ22-F-GET-05"
    objects = _fixture_objects(case_id)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=build_object_heavy_v3_recipe(case_id),
        backend=_StateBackend(objects),
    )
    runtime.before = runtime.snapshot()
    before = runtime.before.by_key()
    request = runtime.recipe.request
    assert isinstance(request, QueryObjectRequestSpec)
    raw_keys = [
        "q5_root",
        "actor_root",
        "q5_movement",
        "actor_dwu",
        "q5_player",
    ]
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "query-object",
        "count": 5,
        "query_bound": {"mode": "take", "value": 8},
        "objects": [_row(before[key]) for key in raw_keys],
    }
    rows = []
    for ordinal, key in enumerate(request.exact_expected_keys, start=1):
        ancestor = before[key]
        rows.append(
            f"| {ordinal} | {ancestor.name} | {ancestor.id} | {ancestor.type} | "
            f"`{ancestor.path}` | {ancestor.children_count} | "
            f"{ancestor.notes or '无'} |"
        )
    answer = "\n".join(
        (
            "归属链（离目标由近到远，已排除 Project）：",
            "| 层级 | 名称 | GUID | 类型 | 完整路径 | 直接子对象数 | 备注 |",
            "|---:|---|---|---|---|---:|---|",
            *rows,
            "核对结果：符合。链中恰有：",
            "- 1 个 Random Container：Movement（具体类型为 RandomSequenceContainer）",
            "- 2 个 Actor Mixer：Player、SemanticLab_Query05",
            "- 1 个 Default Work Unit",
            "按类型汇总：RandomSequenceContainer 1 层，ActorMixer 2 层，WorkUnit 2 层（其中 1 层为 Default Work Unit）。",
        )
    )
    return runtime, payload, answer


def test_get05_query_oracle_accepts_unordered_raw_rows_and_ordered_answer() -> None:
    runtime, payload, answer = _get05_query_runtime()

    verification = runtime.verify_query_result(payload, final_response=answer)

    assert verification.passed, verification.failures
    assert verification.evidence["observed_keys"] == [
        "q5_root",
        "actor_root",
        "q5_movement",
        "actor_dwu",
        "q5_player",
    ]
    assert verification.evidence["observed_answer_order"] == [
        "q5_movement",
        "q5_player",
        "q5_root",
        "actor_dwu",
        "actor_root",
    ]
    assert verification.evidence["coverage_summary"] == {
        "random_sequence_container_count": 1,
        "actor_mixer_count": 2,
        "work_unit_count": 2,
        "default_work_unit_count": 1,
        "raw_row_count": 5,
        "take": 8,
        "bound_reached": False,
        "summary_line_indexes": [9, 10, 12],
        "truncation_claimed": False,
    }


def test_get05_query_oracle_accepts_r62_dwu_as_exact_table_row_only() -> None:
    runtime, payload, answer = _get05_query_runtime()
    response = (
        answer.replace("- 1 个 Default Work Unit", "并且经过 Default Work Unit")
        .replace("（其中 1 层为 Default Work Unit）", "")
        + "\n共 5 层，未触及 8 层上限。"
    )

    verification = runtime.verify_query_result(payload, final_response=response)

    assert verification.passed, verification.failures
    assert verification.evidence["coverage_summary"][
        "default_work_unit_count"
    ] == 1


@pytest.mark.parametrize(
    ("mutation", "failure"),
    (
        (
            lambda payload, answer, before: (
                payload["objects"][0].__setitem__("type", "Sound"),
                answer,
            )[1],
            "type differs from sealed ancestor",
        ),
        (
            lambda payload, answer, before: (
                payload["objects"].__setitem__(
                    1, copy.deepcopy(payload["objects"][0])
                ),
                answer,
            )[1],
            "ancestor identities differ",
        ),
        (
            lambda payload, answer, before: "\n".join(
                [
                    *answer.splitlines()[:2],
                    answer.splitlines()[2],
                    answer.splitlines()[4],
                    answer.splitlines()[3],
                    *answer.splitlines()[5:],
                ]
            ),
            "ancestor order differs",
        ),
        (
            lambda payload, answer, before: answer.replace(
                "RandomSequenceContainer", "Sound", 1
            ),
            "row type differs",
        ),
        (
            lambda payload, answer, before: answer.replace(
                "| 2 | query05 root |", "| 99 | query05 root |"
            ),
            "ordinal/childrenCount differs",
        ),
        (
            lambda payload, answer, before: answer.replace(
                "| 1 | Movement |", "| 9 | Movement |", 1
            ),
            "ordinal/childrenCount differs",
        ),
        (
            lambda payload, answer, before: answer.replace(
                "movement owner", "wrong notes", 1
            ),
            "row notes differ",
        ),
        (
            lambda payload, answer, before: answer.replace(
                f"`{before['q5_movement'].path}`",
                f"`{before['q5_decoy_movement'].path}`",
                1,
            ),
            "exact ancestor path",
        ),
        (
            lambda payload, answer, before: "\n".join(
                line
                for line in answer.splitlines()
                if before["actor_dwu"].id not in line
            ),
            "exact ancestor path",
        ),
        (
            lambda payload, answer, before: answer
            + "\n"
            + next(
                line
                for line in answer.splitlines()
                if before["actor_dwu"].id in line
            ),
            "exact ancestor path",
        ),
        (
            lambda payload, answer, before: answer
            + f"\n| decoy | {before['q5_decoy_player'].id} | ActorMixer | "
            + f"`{before['q5_decoy_player'].path}` | 1 | same-name player |",
            "excluded ancestor identity",
        ),
        (
            lambda payload, answer, before: answer.replace(
                "2 个 Actor Mixer", "3 个 Actor Mixer"
            ),
            "type summary differs for ActorMixer",
        ),
        (
            lambda payload, answer, before: answer.replace(
                "1 个 Random Container", "1 个 Random Group"
            ).replace(
                "按类型汇总：RandomSequenceContainer 1 层",
                "按类型汇总：RandomGroup 1 层",
            ),
            "type summary differs for RandomSequenceContainer",
        ),
        (
            lambda payload, answer, before: answer + "\n结果已截断。",
            "incorrectly claims",
        ),
    ),
    ids=(
        "raw-type",
        "raw-duplicate",
        "final-order",
        "final-type",
        "final-children-count-query05-token",
        "final-wrong-ordinal",
        "final-notes",
        "final-path-decoy",
        "missing-default-work-unit-row",
        "duplicate-default-work-unit-row",
        "same-name-decoy",
        "wrong-natural-type-count",
        "unknown-type-alias",
        "false-truncation",
    ),
)
def test_get05_query_oracle_rejects_row_summary_and_decoy_tampering(
    mutation,
    failure: str,
) -> None:
    runtime, payload, answer = _get05_query_runtime()
    before = runtime.before.by_key()

    verification = runtime.verify_query_result(
        payload,
        final_response=mutation(payload, answer, before),
    )

    assert not verification.passed
    assert any(failure in item for item in verification.failures), verification.failures


def test_get01_rejects_any_unapproved_derived_row() -> None:
    case_id = "OBJ22-F-GET-01"
    objects = _fixture_objects(case_id)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=build_object_heavy_v3_recipe(case_id),
        backend=_StateBackend(objects),
    )
    runtime.before = runtime.snapshot()
    request = runtime.recipe.request
    assert isinstance(request, QueryObjectRequestSpec)
    before = runtime.before.by_key()
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "query-object",
        "objects": [
            *[_row(before[key]) for key in request.bounded_superset_keys],
            {
                "id": before[request.bounded_superset_keys[0]].active_source_id,
                "type": "AudioFileSource",
            },
        ],
    }
    answer = "\n".join(
        f"{before[key].name} {before[key].id}" for key in request.exact_expected_keys
    )

    verification = runtime.verify_query_result(payload, final_response=answer)

    assert not verification.passed
    assert "unapproved derived rows" in " ".join(verification.failures)


def _expected_after_objects(
    case_id: str,
    before: tuple[MaterializedObject, ...],
) -> tuple[MaterializedObject, ...]:
    """Materialize the closed static/dynamic oracle graph for fake after-state tests."""

    recipe = build_object_heavy_v3_recipe(case_id)
    before_by_key = {item.key: item for item in before}
    visible = {
        key: item
        for key, item in before_by_key.items()
        if key not in recipe.oracle.removed_keys
    }
    next_id = 500
    for expected in recipe.oracle.expected_objects:
        previous = before_by_key.get(expected.key)
        parent = visible.get(expected.parent_key or "") or before_by_key.get(
            expected.parent_key or ""
        )
        name = (
            expected.requested_name + "_01"
            if expected.identity_policy == "new_renamed"
            else expected.requested_name
        )
        path = expected.path
        if path is None:
            assert parent is not None
            path = parent.path + "\\" + name
        object_id = (
            previous.id
            if previous is not None
            and expected.identity_policy in {"preserve", "borrowed_snapshot"}
            else _guid(next_id)
        )
        if object_id == _guid(next_id):
            next_id += 1

        notes = previous.notes if previous is not None else None
        properties = {
            item.name: item.value for item in (previous.properties if previous else ())
        }
        references = {
            item.name: item.target_id
            for item in (previous.references if previous else ())
        }
        source_language = previous.source_language if previous is not None else None
        is_included = previous.is_included if previous is not None else None
        for field in expected.fields:
            if field.mode == "literal":
                if field.name == "notes":
                    notes = field.value
                elif field.name.startswith("@"):
                    properties[field.name[1:]] = field.value
                elif field.name == "audioSource:language":
                    source_language = field.value
                elif field.name == "isIncluded":
                    is_included = field.value
            elif field.mode == "object_key_id":
                target = visible.get(str(field.value)) or before_by_key.get(
                    str(field.value)
                )
                assert target is not None
                if field.name == "OutputBus":
                    references[field.name] = target.id

        visible[expected.key] = MaterializedObject(
            key=expected.key,
            id=object_id,
            name=name,
            type=expected.object_type,
            path=path,
            parent_id=parent.id if parent is not None else None,
            notes=notes,
            properties=tuple(
                ObjectProperty(prop_name, value)
                for prop_name, value in properties.items()
            ),
            references=tuple(
                MaterializedReference(reference_name, target_id)
                for reference_name, target_id in references.items()
            ),
            source_language=source_language,
            is_included=is_included,
            children_count=len(expected.children),
        )
    return tuple(visible.values())


def _set_row_inherited_effective_fields(
    backend: _StateBackend,
    item: MaterializedObject,
    bus_id: str,
    *,
    override_output: bool,
    volume: float,
    pitch: float,
) -> None:
    for row in (backend.rows_by_path[item.path], backend.rows_by_id[item.id]):
        row["OutputBus"] = {"id": bus_id}
        row["OverrideOutput"] = override_output
        row["@Volume"] = volume
        row["@Pitch"] = pitch


def _set03_effective_bus_runtime(
    *,
    child_override_output: bool = False,
    child_reports_inherited_volume_pitch: bool = True,
) -> tuple[
    PreparedObjectRuntime,
    _StateBackend,
    dict[str, MaterializedObject],
]:
    case_id = "OBJ22-F-SET-03"
    before_objects = _fixture_objects(case_id)
    before_by_key = {item.key: item for item in before_objects}
    before_backend = _StateBackend(before_objects)
    before_buses = {
        "day_child": before_by_key["weather_bus"].id,
        "night_child": before_by_key["weather_bus"].id,
        "storm_child": before_by_key["ambience_bus"].id,
    }
    for key, bus_id in before_buses.items():
        parent = before_by_key[key.removesuffix("_child")]
        _set_row_inherited_effective_fields(
            before_backend,
            before_by_key[key],
            bus_id,
            override_output=child_override_output,
            volume=(
                float(
                    dict((row.name, row.value) for row in parent.properties)[
                        "Volume"
                    ]
                )
                if child_reports_inherited_volume_pitch
                else 0.0
            ),
            pitch=(
                float(
                    dict((row.name, row.value) for row in parent.properties)[
                        "Pitch"
                    ]
                )
                if child_reports_inherited_volume_pitch
                else 0.0
            ),
        )

    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=build_object_heavy_v3_recipe(case_id),
        backend=before_backend,
    )
    runtime.before = runtime.snapshot()

    after_objects = _expected_after_objects(case_id, before_objects)
    after_by_key = {item.key: item for item in after_objects}
    after_backend = _StateBackend(after_objects)
    after_buses = {
        "day_child": after_by_key["ambience_bus"].id,
        "night_child": after_by_key["ambience_bus"].id,
        "storm_child": after_by_key["weather_bus"].id,
    }
    for key, bus_id in after_buses.items():
        parent = after_by_key[key.removesuffix("_child")]
        _set_row_inherited_effective_fields(
            after_backend,
            after_by_key[key],
            bus_id,
            override_output=child_override_output,
            volume=(
                float(
                    dict((row.name, row.value) for row in parent.properties)[
                        "Volume"
                    ]
                )
                if child_reports_inherited_volume_pitch
                else 0.0
            ),
            pitch=(
                float(
                    dict((row.name, row.value) for row in parent.properties)[
                        "Pitch"
                    ]
                )
                if child_reports_inherited_volume_pitch
                else 0.0
            ),
        )
    runtime.backend = after_backend
    return runtime, after_backend, after_by_key


def test_all_object_recipes_build_exact_single_or_two_turn_protocols() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    scenarios = {case.id: case for case in bundle.scenarios}
    for recipe in all_object_heavy_v3_recipes():
        runtime = PreparedObjectRuntime(
            scenario=scenarios[recipe.scenario_id],
            recipe=recipe,
            backend=object(),  # Protocol is not used while building data-only protocol.
        )
        protocol = runtime.gateway_protocol()
        if isinstance(recipe.request, OperationRequestSpec):
            preview_index = next(
                index
                for index, step in enumerate(protocol.steps)
                if step.subcommand in {"typed-operation", "preview-from-draft"}
            )
            assert protocol.turn_prefix_counts == (
                preview_index + 1,
                len(protocol.steps),
            )
            assert tuple(step.subcommand for step in protocol.steps[-4:]) == (
                "transaction-show",
                "confirm",
                "execute",
                "verify",
            )
        else:
            assert isinstance(recipe.request, QueryObjectRequestSpec)
            assert protocol.turn_prefix_counts == (1,)
            assert tuple(step.subcommand for step in protocol.steps) == (
                "query-object",
            )


@pytest.mark.parametrize(
    "case_id",
    (
        "OBJ22-F-CREATE-02",
        "OBJ22-F-CREATE-03",
        "OBJ22-F-SET-01",
        "OBJ22-F-SET-02",
    ),
)
def test_compound_object_runtime_binds_2025_request_and_reflected_types(
    case_id: str,
) -> None:
    recipe = build_object_heavy_v3_recipe(case_id, "2025.1")
    scenario = SimpleNamespace(
        id=case_id,
        api=recipe.api,
        versions=("2022.1", "2025.1"),
    )
    objects = _fixture_objects(case_id, "2025.1")
    runtime = PreparedObjectRuntime(
        scenario=scenario,
        recipe=recipe,
        backend=_StateBackend(objects),
    )

    snapshot = runtime.snapshot()
    protocol = runtime.gateway_protocol()
    preview_request = materialize_typed_transaction_protocol_requests(
        protocol,
        version="2025.1",
    )[0][1]

    assert {item.type for item in snapshot.objects} >= {
        "PropertyContainer",
        "Sound",
    }
    assert preview_request["version"] == "2025.1"
    assert r"\\Containers\\Default Work Unit\\SemanticLab" in json.dumps(
        preview_request,
        ensure_ascii=False,
    )


def test_object_runtime_rejects_a_cross_version_scenario_mismatch() -> None:
    recipe = build_object_heavy_v3_recipe("OBJ22-F-CREATE-02", "2025.1")
    scenario = SimpleNamespace(
        id=recipe.scenario_id,
        api=recipe.api,
        versions=("2022.1",),
    )

    with pytest.raises(ObjectRuntimeError, match="versions do not match"):
        PreparedObjectRuntime(
            scenario=scenario,
            recipe=recipe,
            backend=object(),
        )


def test_object_prompts_render_without_hidden_fixture_values() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    scenarios = {case.id: case for case in bundle.scenarios}
    for recipe in all_object_heavy_v3_recipes():
        runtime = PreparedObjectRuntime(
            scenario=scenarios[recipe.scenario_id], recipe=recipe, backend=object()
        )
        prompt = runtime.render_prompt()
        assert "{" not in prompt
        assert all(literal in prompt for literal in recipe.prompt_literals)


@pytest.mark.parametrize(
    "response_extras",
    ({}, {"files": [], "log": []}),
    ids=("2021-2022-shape", "2023-2025-shape"),
)
def test_closed_backend_imports_language_sound_and_sets_platform_inclusion(
    tmp_path,
    response_extras,
) -> None:
    source = tmp_path / "voice.wav"
    with wave.open(str(source), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48_000)
        handle.writeframes(b"\0\0" * 4_800)

    calls = []

    def call(uri, args, options):
        calls.append((uri, args, options))
        if uri == "ak.wwise.core.audio.import":
            return {
                **response_extras,
                "objects": [
                    {
                        "id": "{00000000-0000-0000-0000-000000000001}",
                        "name": "Greeting",
                        "type": "AudioFileSource",
                        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Greeting",
                        "audioSource:language": "Japanese",
                    },
                    {
                        "id": "{11111111-1111-1111-1111-111111111111}",
                        "name": "Greeting",
                        "type": "Sound",
                        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Greeting",
                        "audioSource:language": "Japanese",
                    }
                ]
            }
        return {}

    backend = ClosedDirectObjectBackend(call)
    result = backend.import_sound(
        parent=r"\Actor-Mixer Hierarchy\Default Work Unit",
        name="Greeting",
        language="Japanese",
        audio_file=source,
    )
    backend.set_inclusion(result, False)

    assert result == "{11111111-1111-1111-1111-111111111111}"
    assert calls[0][0] == "ak.wwise.core.audio.import"
    assert calls[0][1]["imports"][0]["objectPath"].endswith(
        r"\<Sound Voice>Greeting"
    )
    assert calls[0][1]["imports"][0]["importLanguage"] == "Japanese"
    assert calls[1] == (
        "ak.wwise.core.object.setProperty",
        {
            "object": result,
            "property": "Inclusion",
            "value": False,
            "platform": "Windows",
        },
        {},
    )


@pytest.mark.parametrize(
    "malformed_result",
    (
        {"return": []},
        {"objects": "not-an-array"},
        {"objects": [None]},
    ),
    ids=("legacy-return-alias", "non-array", "non-object-row"),
)
def test_closed_backend_import_rejects_noncanonical_object_rows(
    tmp_path,
    malformed_result,
) -> None:
    source = tmp_path / "fixture.wav"
    with wave.open(str(source), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48_000)
        handle.writeframes(b"\0\0" * 4_800)

    backend = ClosedDirectObjectBackend(
        lambda uri, args, options: malformed_result
    )

    with pytest.raises(
        ObjectRuntimeError,
        match=r"audio\.import fixture sound result\.objects must be an object array",
    ):
        backend.import_sound(
            parent=r"\Actor-Mixer Hierarchy\Default Work Unit",
            name="Fixture",
            language="SFX",
            audio_file=source,
        )


def test_closed_backend_reads_one_exact_identity_with_bounded_fields() -> None:
    calls = []

    def call(uri, args, options):
        calls.append((uri, args, options))
        return {"return": []}

    object_id = _guid(1)
    backend = ClosedDirectObjectBackend(call)

    assert backend.read_id(object_id, fields=("id", "path")) == ()
    assert calls == [
        (
            "ak.wwise.core.object.get",
            {"from": {"id": [object_id]}},
            {"return": ["id", "path"], "platform": "Windows"},
        )
    ]


def test_closed_backend_reads_language_bound_sound_and_source_with_same_options() -> None:
    calls = []

    def call(uri, args, options):
        calls.append((uri, args, options))
        return {"return": []}

    backend = ClosedDirectObjectBackend(call)
    sound_path = r"\Actor-Mixer Hierarchy\Default Work Unit\JapaneseGreeting"
    source_id = _guid(2)

    assert backend.read_path(sound_path, language="Japanese") == ()
    assert backend.read_id(source_id, language="Japanese") == ()

    assert [call[2] for call in calls] == [
        {"return": [
                "id", "name", "type", "path", "parent", "notes", "childrenCount",
                "@Volume", "@Pitch", "OverrideOutput", "OutputBus", "activeSource", "audioSource:language", "isIncluded",
            ], "platform": "Windows", "language": "Japanese"},
            {"return": [
                "id", "name", "type", "path", "parent", "notes", "childrenCount",
                "@Volume", "@Pitch", "OverrideOutput", "OutputBus", "activeSource", "audioSource:language", "isIncluded",
            ], "platform": "Windows", "language": "Japanese"},
    ]


def test_closed_backend_rejects_unreviewed_language_context() -> None:
    backend = ClosedDirectObjectBackend(lambda uri, args, options: {"return": []})

    with pytest.raises(ObjectRuntimeError, match="fixture sound language is not closed"):
        backend.read_path(r"\Actor-Mixer Hierarchy\Default Work Unit", language="French")


def test_closed_backend_sets_effective_output_bus_with_fixed_two_call_sequence() -> None:
    calls = []
    overrides: dict[str, bool] = {}

    def call(uri, args, options):
        calls.append((uri, args, options))
        if uri == "ak.wwise.core.object.setProperty":
            assert args["property"] == "OverrideOutput"
            assert args["value"] is True
            overrides[args["object"]] = True
        elif uri == "ak.wwise.core.object.setReference":
            # The fake only treats a bus as effective after the preceding
            # override write, matching the real fixture setup requirement.
            assert overrides.get(args["object"]) is True
        return {}

    backend = ClosedDirectObjectBackend(call)
    sound_id = _guid(31)
    bus_id = _guid(32)

    backend.set_reference(sound_id, "OutputBus", bus_id)

    assert calls == [
        (
            "ak.wwise.core.object.setProperty",
            {"object": sound_id, "property": "OverrideOutput", "value": True},
            {},
        ),
        (
            "ak.wwise.core.object.setReference",
            {"object": sound_id, "reference": "OutputBus", "value": bus_id},
            {},
        ),
    ]


def test_closed_backend_rejects_fixture_references_other_than_output_bus() -> None:
    calls = []
    backend = ClosedDirectObjectBackend(
        lambda uri, args, options: calls.append((uri, args, options))
    )

    with pytest.raises(ObjectRuntimeError, match="only OutputBus is supported"):
        backend.set_reference(_guid(41), "AuxBus", _guid(42))

    assert calls == []


def test_replace_oracle_accepts_reused_path_when_old_guid_is_absent() -> None:
    runtime, backend, before = _replace_runtime()
    old_proto = before["old_proto"]

    replacement = backend.read_path(old_proto.path)
    assert len(replacement) == 1
    assert replacement[0]["id"] != old_proto.id

    verification = runtime.verify_after_execution()

    assert verification.passed, verification.failures
    assert backend.read_id_calls == [
        before[key].id
        for key in runtime.recipe.oracle.removed_keys
    ]


def test_replace_oracle_rejects_old_guid_that_still_resolves() -> None:
    runtime, backend, before = _replace_runtime()
    old_proto = before["old_proto"]
    backend.rows_by_id[old_proto.id] = _row(
        old_proto,
        path=old_proto.path + "_Relocated",
    )

    verification = runtime.verify_after_execution()

    assert not verification.passed
    assert verification.failures == ("old_proto: removed identity still exists",)


def test_merge_after_snapshot_allows_only_reviewed_new_paths() -> None:
    case_id = "OBJ22-F-CREATE-02"
    recipe = build_object_heavy_v3_recipe(case_id)
    before_objects = _fixture_objects(case_id)
    before_backend = _StateBackend(before_objects)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=recipe,
        backend=before_backend,
    )
    runtime.before = runtime.snapshot()

    after_backend = _StateBackend(_expected_after_objects(case_id, before_objects))
    runtime.backend = after_backend
    verification = runtime.verify_after_execution()

    assert verification.passed, verification.failures
    assert verification.evidence["after"]["absent_paths"] == (
        recipe.fixture.absent_paths[-1],
    )

    unwanted_path = recipe.fixture.absent_paths[-1]
    npc = next(item for item in before_objects if item.key == "npc")
    unwanted = MaterializedObject(
        key="unwanted_rename",
        id=_guid(900),
        name="Robot_VO_01",
        type="ActorMixer",
        path=unwanted_path,
        parent_id=npc.id,
        notes=None,
        properties=(),
        references=(),
        source_language=None,
        is_included=None,
        children_count=0,
    )
    after_backend.set_objects((*after_backend.objects, unwanted))
    with pytest.raises(ObjectRuntimeError, match="path expected absent is present"):
        runtime.verify_after_execution()


@pytest.mark.parametrize(
    "case_id",
    (
        "OBJ22-F-SET-01",
        "OBJ22-F-SET-02",
        "OBJ22-F-SET-03",
        "OBJ22-F-SET-04",
        "OBJ22-F-SET-05",
    ),
)
def test_object_set_oracle_resolves_preserved_and_new_direct_children(
    case_id: str,
) -> None:
    if case_id == "OBJ22-F-SET-03":
        runtime, _backend, _after = _set03_effective_bus_runtime()
        verification = runtime.verify_after_execution()
        assert verification.passed, verification.failures
        return
    before_objects = _fixture_objects(case_id)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=build_object_heavy_v3_recipe(case_id),
        backend=_StateBackend(before_objects),
    )
    runtime.before = runtime.snapshot()
    runtime.backend = _StateBackend(
        _expected_after_objects(case_id, before_objects)
    )

    verification = runtime.verify_after_execution()

    assert verification.passed, verification.failures


def test_set03_oracle_accepts_only_reviewed_inherited_effective_changes() -> None:
    runtime, _backend, _after = _set03_effective_bus_runtime()

    verification = runtime.verify_after_execution()

    assert verification.passed, verification.failures
    comparisons = verification.evidence["protected_comparisons"]
    for key in ("day_child", "night_child", "storm_child"):
        assert comparisons[key]["override_output_before"] is False
        assert comparisons[key]["override_output_after"] is False
        assert comparisons[key]["ignored_derived_fields"] == [
            "@Volume",
            "@Pitch",
            "OutputBus",
        ]
        assert comparisons[key]["before_projection"] == comparisons[key][
            "after_projection"
        ]
        assert comparisons[key]["passed"] is True


def test_set03_oracle_keeps_stable_noninherited_volume_pitch_strict() -> None:
    runtime, _backend, _after = _set03_effective_bus_runtime(
        child_reports_inherited_volume_pitch=False
    )

    verification = runtime.verify_after_execution()

    assert verification.passed, verification.failures
    comparisons = verification.evidence["protected_comparisons"]
    for key in ("day_child", "night_child", "storm_child"):
        assert comparisons[key]["ignored_derived_fields"] == ["OutputBus"]
        assert comparisons[key]["before_projection"] == comparisons[key][
            "after_projection"
        ]
        assert comparisons[key]["passed"] is True


def test_preview_oracle_rejects_override_output_only_change() -> None:
    case_id = "OBJ22-F-SET-03"
    objects = _fixture_objects(case_id)
    backend = _StateBackend(objects)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=build_object_heavy_v3_recipe(case_id),
        backend=backend,
    )
    runtime.before = runtime.snapshot()
    child = next(item for item in objects if item.key == "day_child")
    backend.rows_by_path[child.path]["OverrideOutput"] = True
    backend.rows_by_id[child.id]["OverrideOutput"] = True

    verification = runtime.verify_preview_unchanged()

    assert not verification.passed
    assert verification.failures == ("object fixture changed before confirmation",)


def test_get_oracle_rejects_override_output_only_change() -> None:
    runtime, payload, answer = _get02_query_runtime()
    backend = runtime.backend
    target = next(
        item
        for item in backend.objects
        if item.type in {"ActorMixer", "RandomSequenceContainer", "Sound"}
    )
    backend.rows_by_path[target.path]["OverrideOutput"] = not backend.rows_by_path[
        target.path
    ]["OverrideOutput"]
    backend.rows_by_id[target.id]["OverrideOutput"] = backend.rows_by_path[
        target.path
    ]["OverrideOutput"]

    verification = runtime.verify_query_result(payload, final_response=answer)

    assert not verification.passed
    assert "read-only object query changed fixture state" in verification.failures


def test_set03_oracle_keeps_bus_output_reference_strict_even_with_false_flag() -> None:
    case_id = "OBJ22-F-SET-03"
    before_objects = _fixture_objects(case_id)
    before_backend = _StateBackend(before_objects)
    bus = next(item for item in before_objects if item.key == "ambience_bus")
    for row in (
        before_backend.rows_by_path[bus.path],
        before_backend.rows_by_id[bus.id],
    ):
        row["OverrideOutput"] = False
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=build_object_heavy_v3_recipe(case_id),
        backend=before_backend,
    )
    runtime.before = runtime.snapshot()
    after_objects = _expected_after_objects(case_id, before_objects)
    after_backend = _StateBackend(after_objects)
    after_bus = next(item for item in after_objects if item.key == "ambience_bus")
    for row in (
        after_backend.rows_by_path[after_bus.path],
        after_backend.rows_by_id[after_bus.id],
    ):
        row["OverrideOutput"] = False
        row["OutputBus"] = {"id": _guid(999_999)}
    runtime.backend = after_backend

    verification = runtime.verify_after_execution()

    assert not verification.passed
    assert "ambience_bus: protected snapshot changed" in verification.failures
    assert verification.evidence["protected_comparisons"]["ambience_bus"][
        "ignored_derived_fields"
    ] == []


def test_other_set_descendant_without_reviewed_bus_change_remains_strict() -> None:
    case_id = "OBJ22-F-SET-01"
    before_objects = _fixture_objects(case_id)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=build_object_heavy_v3_recipe(case_id),
        backend=_StateBackend(before_objects),
    )
    runtime.before = runtime.snapshot()
    after_objects = _expected_after_objects(case_id, before_objects)
    after_backend = _StateBackend(after_objects)
    child = next(item for item in after_objects if item.key == "ranged_a")
    for row in (
        after_backend.rows_by_path[child.path],
        after_backend.rows_by_id[child.id],
    ):
        row["OverrideOutput"] = False
        row["OutputBus"] = {"id": _guid(999_998)}
    runtime.backend = after_backend

    verification = runtime.verify_after_execution()

    assert not verification.passed
    assert "ranged_a: protected snapshot changed" in verification.failures
    assert verification.evidence["protected_comparisons"]["ranged_a"][
        "ignored_derived_fields"
    ] == []


@pytest.mark.parametrize(
    ("field", "value", "failure"),
    (
        ("id", _guid(991), "protected snapshot changed"),
        ("name", "Day_Changed", "protected snapshot changed"),
        ("path", r"\Actor-Mixer Hierarchy\Changed", "protected snapshot changed"),
        ("parent", {"id": _guid(992)}, "protected snapshot changed"),
        ("notes", "changed child", "protected snapshot changed"),
        ("@Volume", -7.0, "protected snapshot changed"),
        ("@Pitch", 300, "protected snapshot changed"),
        ("OverrideOutput", True, "protected OverrideOutput changed"),
    ),
)
def test_set03_oracle_rejects_protected_child_intrinsic_changes(
    field: str,
    value: object,
    failure: str,
) -> None:
    runtime, backend, after = _set03_effective_bus_runtime()
    child = after["day_child"]
    backend.rows_by_path[child.path][field] = value

    verification = runtime.verify_after_execution()

    assert not verification.passed
    assert any(failure in item for item in verification.failures)


def test_set03_oracle_requires_explicit_protected_override_readback() -> None:
    runtime, backend, after = _set03_effective_bus_runtime()
    child = after["day_child"]
    backend.rows_by_path[child.path].pop("OverrideOutput")

    verification = runtime.verify_after_execution()

    assert not verification.passed
    assert (
        "day_child: protected after-state OverrideOutput is not explicit"
        in verification.failures
    )


def test_set03_oracle_accepts_stable_effective_true_override_readback() -> None:
    runtime, _backend, _after = _set03_effective_bus_runtime(
        child_override_output=True,
        child_reports_inherited_volume_pitch=False,
    )

    verification = runtime.verify_after_execution()

    assert verification.passed, verification.failures
    for key in ("day_child", "night_child", "storm_child"):
        comparison = verification.evidence["protected_comparisons"][key]
        assert comparison["override_output_before"] is True
        assert comparison["override_output_after"] is True
        assert comparison["ignored_derived_fields"] == ["OutputBus"]
        assert comparison["before_projection"] == comparison["after_projection"]


def test_set03_oracle_keeps_protected_bus_snapshot_strict() -> None:
    runtime, backend, after = _set03_effective_bus_runtime()
    bus = after["ambience_bus"]
    backend.rows_by_path[bus.path]["notes"] = "changed bus"

    verification = runtime.verify_after_execution()

    assert not verification.passed
    assert "ambience_bus: protected snapshot changed" in verification.failures


def test_set03_oracle_rejects_missing_direct_child_identity() -> None:
    runtime, backend, after = _set03_effective_bus_runtime()
    backend.children_by_id[after["day"].id] = ()

    verification = runtime.verify_after_execution()

    assert not verification.passed
    assert "day: direct child identity order mismatch" in verification.failures


def test_set03_project_runner_verify_observer_accepts_intrinsic_projection(
    tmp_path: Path,
) -> None:
    runtime, _backend, _after = _set03_effective_bus_runtime()
    protocol = runtime.gateway_protocol()
    prepared = project_runner._PreparedCase(
        prompt=runtime.render_prompt(),
        visible_values={},
        protocol=protocol,
        required_reference="references/waapi-operate.md",
        snapshot=runtime.snapshot,
        verify_final=lambda _payload, _result: runtime.verify_after_execution(),
    )
    observer = project_runner._CaseObservers(
        scenario=runtime.scenario,
        prepared=prepared,
        direct=SimpleNamespace(),
        endpoint="127.0.0.1:49152",
        version="2022.1",
        business_oracle_plan_sha256="f" * 64,
    )
    verify_step = protocol.steps[-1]

    observer.after_gateway_step(
        verify_step,
        {"ok": True, "command": "verify", "status": "verified"},
        tmp_path / "state",
        tmp_path / "evidence",
    )

    verification = observer.checks["business_verification"]["verification"]
    assert verification["passed"] is True
    assert verification["failures"] == []


@pytest.mark.parametrize(
    ("case_id", "parent_key"),
    (
        ("OBJ22-F-SET-01", "combat"),
        ("OBJ22-F-SET-01", "melee"),
        ("OBJ22-F-SET-04", "player"),
        ("OBJ22-F-SET-04", "player_footsteps"),
        ("OBJ22-F-SET-04", "player_cloth"),
    ),
)
def test_object_oracle_accepts_declared_direct_child_order(
    case_id: str,
    parent_key: str,
) -> None:
    recipe = build_object_heavy_v3_recipe(case_id)
    before_objects = _fixture_objects(case_id)
    after_objects = _expected_after_objects(case_id, before_objects)
    backend = _StateBackend(after_objects)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=recipe,
        backend=_StateBackend(before_objects),
    )
    runtime.before = runtime.snapshot()
    runtime.backend = backend

    expected = next(
        item for item in recipe.oracle.expected_objects if item.key == parent_key
    )
    after_by_key = {item.key: item for item in after_objects}
    parent = after_by_key[parent_key]
    observed_ids = [str(row["id"]) for row in backend.children_by_id[parent.id]]
    expected_ids = [after_by_key[key].id for key in expected.children]

    assert observed_ids == expected_ids
    verification = runtime.verify_after_execution()
    assert verification.passed, verification.failures


@pytest.mark.parametrize(
    ("case_id", "parent_key"),
    (
        ("OBJ22-F-SET-01", "combat"),
        ("OBJ22-F-SET-01", "melee"),
        ("OBJ22-F-SET-04", "player"),
        ("OBJ22-F-SET-04", "player_footsteps"),
        ("OBJ22-F-SET-04", "player_cloth"),
    ),
)
def test_object_oracle_rejects_same_direct_child_set_in_different_order(
    case_id: str,
    parent_key: str,
) -> None:
    before_objects = _fixture_objects(case_id)
    after_objects = _expected_after_objects(case_id, before_objects)
    backend = _StateBackend(after_objects)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=build_object_heavy_v3_recipe(case_id),
        backend=_StateBackend(before_objects),
    )
    runtime.before = runtime.snapshot()
    runtime.backend = backend

    parent = next(item for item in after_objects if item.key == parent_key)
    original = backend.children_by_id[parent.id]
    assert len(original) >= 2
    reordered = (original[1], original[0], *original[2:])
    assert {str(row["id"]) for row in reordered} == {
        str(row["id"]) for row in original
    }
    assert [str(row["id"]) for row in reordered] != [
        str(row["id"]) for row in original
    ]
    backend.children_by_id[parent.id] = reordered

    verification = runtime.verify_after_execution()

    assert not verification.passed
    assert (
        f"{parent_key}: direct child identity order mismatch"
        in verification.failures
    )


def test_merge_missing_reviewed_new_path_is_an_oracle_failure() -> None:
    case_id = "OBJ22-F-CREATE-02"
    recipe = build_object_heavy_v3_recipe(case_id)
    before_objects = _fixture_objects(case_id)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=recipe,
        backend=_StateBackend(before_objects),
    )
    runtime.before = runtime.snapshot()
    after_objects = tuple(
        item
        for item in _expected_after_objects(case_id, before_objects)
        if item.key != "alert"
    )
    runtime.backend = _StateBackend(after_objects)

    verification = runtime.verify_after_execution()

    assert not verification.passed
    assert "alert: expected exactly one after-state row, found 0" in verification.failures


def test_preview_snapshot_keeps_all_precondition_absence_strict() -> None:
    case_id = "OBJ22-F-CREATE-02"
    recipe = build_object_heavy_v3_recipe(case_id)
    before_objects = _fixture_objects(case_id)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=recipe,
        backend=_StateBackend(before_objects),
    )
    runtime.before = runtime.snapshot()
    runtime.backend = _StateBackend(_expected_after_objects(case_id, before_objects))

    with pytest.raises(ObjectRuntimeError, match="path expected absent is present"):
        runtime.verify_preview_unchanged()


@pytest.mark.parametrize(
    ("case_id", "parent_key", "prefix", "candidate_name"),
    (
        ("OBJ22-F-CREATE-03", "weapons", "Impact_Library", "Impact_Library_01"),
        ("OBJ22-F-SET-05", "confirm", "Feedback_Layer", "Feedback_Layer_candidate"),
        ("OBJ22-F-SET-05", "error", "Feedback_Layer", "Feedback_Layer_candidate"),
    ),
)
def test_prefix_absence_excludes_exact_collision_but_detects_other_candidates(
    case_id: str,
    parent_key: str,
    prefix: str,
    candidate_name: str,
) -> None:
    recipe = build_object_heavy_v3_recipe(case_id)
    before_objects = _fixture_objects(case_id)
    backend = _StateBackend(before_objects)
    runtime = PreparedObjectRuntime(
        scenario=_scenario(case_id),
        recipe=recipe,
        backend=backend,
    )

    baseline = runtime.snapshot()
    row_key = next(
        key
        for key, _ in baseline.sibling_prefix_rows
        if key.startswith(next(item.path for item in before_objects if item.key == parent_key))
    )
    assert dict(baseline.sibling_prefix_rows)[row_key] == ()

    parent = next(item for item in before_objects if item.key == parent_key)
    candidate = MaterializedObject(
        key="unexpected_prefix_candidate",
        id=_guid(950),
        name=candidate_name,
        type="RandomSequenceContainer",
        path=parent.path + "\\" + candidate_name,
        parent_id=parent.id,
        notes=None,
        properties=(),
        references=(),
        source_language=None,
        is_included=None,
        children_count=0,
    )
    backend.set_objects((*before_objects, candidate))

    observed = runtime.snapshot()
    assert dict(observed.sibling_prefix_rows)[row_key] == (
        (candidate.id, candidate.name, candidate.path),
    )
