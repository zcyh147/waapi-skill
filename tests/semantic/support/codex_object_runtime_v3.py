"""Trusted live materializer and independent oracle for 15 object-heavy cases."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import wave
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from tests.semantic.support.codex_eval_bundle_v3 import OnlineScenario
from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    build_direct_protocol,
    build_transaction_protocol,
    query_object_step,
)
from tests.semantic.support.codex_object_heavy_v3 import (
    FixtureObject,
    MaterializedObject,
    MaterializedReference,
    ObjectHeavyRecipe,
    ObjectProperty,
    OperationRequestSpec,
    QueryObjectRequestSpec,
)
from tests.semantic.support.codex_version_layout_v3 import get_version_layout


OBJECT_RUNTIME_CONTRACT = "waapi-skill.codex-object-runtime/v3"
_CREATE_TYPES = frozenset({"ActorMixer", "Bus", "RandomSequenceContainer", "Sound"})
_GUID_FIELDS = ("id", "name", "type", "path", "parent", "notes", "childrenCount")
_READ_FIELDS = (
    *_GUID_FIELDS,
    "@Volume",
    "@Pitch",
    "OverrideOutput",
    "OutputBus",
    "activeSource",
    "audioSource:language",
    "isIncluded",
)
_READ_FIELDS_2021 = tuple(
    field for field in _READ_FIELDS if field not in {"activeSource", "isIncluded"}
)
_OUTPUT_BUS_OVERRIDE_TYPES = frozenset(
    {"ActorMixer", "PropertyContainer", "RandomSequenceContainer", "Sound"}
)
_FIXTURE_PLATFORM = "Windows"
_FIXTURE_LANGUAGES = frozenset({"SFX", "English(US)", "Japanese"})
_ACTIVE_SOURCE_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "parent",
    "audioSource:language",
)
_NUMBER_TOKEN_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w.])")
_ANSWER_CLAUSE_SPLIT_RE = re.compile(
    r"[，,、；;。.!！？?：:（）()\[\]\n]+|但(?:是)?|不过|然而|\bbut\b|\bhowever\b",
    re.IGNORECASE,
)
_GUID_TOKEN_RE = re.compile(
    r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}"
)


class ObjectRuntimeError(RuntimeError):
    """The closed object fixture or hidden oracle failed closed."""


DirectCall = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Any]


class ObjectRuntimeBackend(Protocol):
    def read_path(
        self,
        path: str,
        *,
        fields: Sequence[str] = _READ_FIELDS,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]: ...

    def read_id(
        self,
        object_id: str,
        *,
        fields: Sequence[str] = _READ_FIELDS,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]: ...

    def read_children(self, object_id: str, *, fields: Sequence[str] = _READ_FIELDS) -> tuple[Mapping[str, Any], ...]: ...

    def create(self, *, parent: str, object_type: str, name: str) -> str: ...

    def import_sound(
        self,
        *,
        parent: str,
        name: str,
        language: str,
        audio_file: Path,
    ) -> str: ...

    def set_notes(self, object_id: str, value: str) -> None: ...

    def set_property(self, object_id: str, name: str, value: Any) -> None: ...

    def set_reference(self, object_id: str, name: str, target_id: str) -> None: ...

    def set_inclusion(self, object_id: str, included: bool) -> None: ...

    def save(self) -> None: ...


class ClosedDirectObjectBackend:
    """Fixed direct-WAAPI calls for runner-owned setup/readback only."""

    def __init__(self, call: DirectCall) -> None:
        if not callable(call):
            raise TypeError("call must be callable")
        self._call = call

    def read_path(
        self,
        path: str,
        *,
        fields: Sequence[str] = _READ_FIELDS,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        result = self._call(
            "ak.wwise.core.object.get",
            {"from": {"path": [_path(path)]}},
            _read_options(fields, language),
        )
        return _rows(result, "object.get path")

    def read_id(
        self,
        object_id: str,
        *,
        fields: Sequence[str] = _READ_FIELDS,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        result = self._call(
            "ak.wwise.core.object.get",
            {"from": {"id": [_text(object_id, "object_id")]}},
            _read_options(fields, language),
        )
        return _rows(result, "object.get id")

    def read_children(self, object_id: str, *, fields: Sequence[str] = _READ_FIELDS) -> tuple[Mapping[str, Any], ...]:
        result = self._call(
            "ak.wwise.core.object.get",
            {"from": {"id": [_text(object_id, "object_id")]}, "transform": [{"select": ["children"]}]},
            {"return": list(_fields(fields)), "platform": _FIXTURE_PLATFORM},
        )
        return _rows(result, "object.get children")

    def create(self, *, parent: str, object_type: str, name: str) -> str:
        if object_type not in _CREATE_TYPES:
            raise ObjectRuntimeError(f"fixture create type is not closed: {object_type}")
        result = self._call(
            "ak.wwise.core.object.create",
            {
                "parent": _path(parent),
                "type": object_type,
                "name": _text(name, "name"),
                "onNameConflict": "fail",
            },
            {},
        )
        if not isinstance(result, Mapping):
            raise ObjectRuntimeError("object.create result must be an object")
        return _text(result.get("id"), "object.create id")

    def import_sound(
        self,
        *,
        parent: str,
        name: str,
        language: str,
        audio_file: Path,
    ) -> str:
        if language not in _FIXTURE_LANGUAGES:
            raise ObjectRuntimeError(f"fixture sound language is not closed: {language!r}")
        source = Path(audio_file).expanduser().resolve(strict=True)
        if source.is_symlink() or not source.is_file() or source.stat().st_size <= 44:
            raise ObjectRuntimeError("fixture audio source must be a non-symlink PCM WAV")
        object_type = "Sound SFX" if language == "SFX" else "Sound Voice"
        result = self._call(
            "ak.wwise.core.audio.import",
            {
                "importOperation": "useExisting",
                "imports": [
                    {
                        "audioFile": str(source),
                        "objectPath": f"{_path(parent)}\\<{object_type}>{_text(name, 'name')}",
                        "objectType": object_type,
                        "importLanguage": language,
                    }
                ],
                "autoAddToSourceControl": False,
            },
            {"return": ["id", "name", "type", "path", "audioSource:language"]},
        )
        rows = _rows(result, "audio.import fixture sound", key="objects")
        expected_path = f"{_path(parent)}\\{_text(name, 'name')}"
        matches = tuple(
            row
            for row in rows
            if row.get("path") == expected_path
            and isinstance(row.get("type"), str)
            and str(row["type"]).casefold() == "sound"
        )
        if len(matches) != 1:
            raise ObjectRuntimeError(
                f"audio.import did not return one fixture Sound at {expected_path}"
            )
        return _text(matches[0].get("id"), "audio.import Sound id")

    def set_notes(self, object_id: str, value: str) -> None:
        self._call(
            "ak.wwise.core.object.setNotes",
            {"object": _text(object_id, "object_id"), "value": str(value)},
            {},
        )

    def set_property(self, object_id: str, name: str, value: Any) -> None:
        self._call(
            "ak.wwise.core.object.setProperty",
            {"object": _text(object_id, "object_id"), "property": _text(name, "property"), "value": value},
            {},
        )

    def set_reference(self, object_id: str, name: str, target_id: str) -> None:
        if name != "OutputBus":
            raise ObjectRuntimeError(
                f"fixture reference is not closed: {name!r}; only OutputBus is supported"
            )
        object_id = _text(object_id, "object_id")
        target_id = _text(target_id, "target_id")
        # A Sound/Actor-Mixer object's explicit bus does not become effective
        # until its override is enabled.  Set the flag first, then bind the
        # reference; later snapshot readback remains the only success proof.
        self.set_property(object_id, "OverrideOutput", True)
        self._call(
            "ak.wwise.core.object.setReference",
            {
                "object": object_id,
                "reference": "OutputBus",
                "value": target_id,
            },
            {},
        )

    def set_inclusion(self, object_id: str, included: bool) -> None:
        if not isinstance(included, bool):
            raise ObjectRuntimeError("fixture Inclusion value must be boolean")
        self._call(
            "ak.wwise.core.object.setProperty",
            {
                "object": _text(object_id, "object_id"),
                "property": "Inclusion",
                "value": included,
                "platform": _FIXTURE_PLATFORM,
            },
            {},
        )

    def save(self) -> None:
        result = self._call("ak.wwise.core.project.save", {}, {})
        if result is not None and not isinstance(result, Mapping):
            raise ObjectRuntimeError("project.save result must be an object or null")


@dataclass(frozen=True, slots=True)
class ObjectRuntimeSnapshot:
    objects: tuple[MaterializedObject, ...]
    absent_paths: tuple[str, ...]
    sibling_prefix_rows: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...]
    digest: str
    override_output_rows: tuple[tuple[str, bool | None], ...] = ()

    def by_key(self) -> dict[str, MaterializedObject]:
        return {item.key: item for item in self.objects}

    def override_output_by_key(self) -> dict[str, bool | None]:
        return dict(self.override_output_rows)


@dataclass(frozen=True, slots=True)
class ObjectRuntimeVerification:
    phase: str
    passed: bool
    failures: tuple[str, ...]
    evidence: Mapping[str, Any]

    def assert_passed(self) -> None:
        if not self.passed:
            raise ObjectRuntimeError(f"{self.phase} failed: {'; '.join(self.failures)}")


class PreparedObjectRuntime:
    def __init__(
        self,
        *,
        scenario: OnlineScenario,
        recipe: ObjectHeavyRecipe,
        backend: ObjectRuntimeBackend,
        asset_root: Path | None = None,
    ) -> None:
        if scenario.id != recipe.scenario_id or scenario.api != recipe.api:
            raise ObjectRuntimeError("scenario and object recipe identity do not match")
        if recipe.version not in scenario.versions:
            raise ObjectRuntimeError("scenario and object recipe versions do not match")
        self.scenario = scenario
        self.recipe = recipe
        self.backend = backend
        self.asset_root = (
            Path(asset_root).expanduser().resolve(strict=False)
            if asset_root is not None
            else None
        )
        self.before: ObjectRuntimeSnapshot | None = None
        self._before_output_bus_overrides: dict[str, bool | None] | None = None
        self._last_snapshot_output_bus_overrides: dict[str, bool | None] = {}

    @property
    def _read_fields(self) -> tuple[str, ...]:
        return _READ_FIELDS_2021 if self.recipe.version == "2021.1" else _READ_FIELDS

    def _read_path(
        self,
        path: str,
        *,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        if language is None:
            return self.backend.read_path(path, fields=self._read_fields)
        return self.backend.read_path(
            path,
            fields=self._read_fields,
            language=language,
        )

    def render_prompt(self) -> str:
        return self.scenario.render_prompt({})

    def gateway_protocol(self) -> V3GatewayProtocol:
        request = self.recipe.request
        if isinstance(request, OperationRequestSpec):
            return build_transaction_protocol(
                [request.as_dict(version=self.recipe.version)]
            )
        if isinstance(request, QueryObjectRequestSpec):
            return build_direct_protocol(
                [
                    query_object_step("query-object", request.argv[3:]),
                ]
            )
        raise ObjectRuntimeError("unknown object recipe request type")

    def prepare(self) -> "PreparedObjectRuntime":
        if self.before is not None:
            raise ObjectRuntimeError("object runtime is single-use")
        materialized: dict[str, MaterializedObject] = {}
        ordered = sorted(self.recipe.fixture.objects, key=lambda item: (item.path.count("\\"), item.path))
        for item in ordered:
            language = self._fixture_language(item)
            existing = self._read_path(item.path, language=language)
            if item.role == "borrowed":
                if len(existing) != 1:
                    raise ObjectRuntimeError(f"borrowed fixture path must exist exactly once: {item.path}")
                materialized[item.key] = self._materialize_fixture(item, existing[0])
                continue
            if existing:
                raise ObjectRuntimeError(f"scenario-owned fixture path already exists: {item.path}")
            parent_path = item.parent_path
            if parent_path is None:
                raise ObjectRuntimeError(f"owned fixture object has no parent: {item.path}")
            if len(self.backend.read_path(parent_path, fields=_GUID_FIELDS)) != 1:
                raise ObjectRuntimeError(f"fixture parent does not exist exactly once: {parent_path}")
            if item.object_type == "Sound" and item.source_language is not None:
                audio_file = self._fixture_audio_file(item)
                object_id = self.backend.import_sound(
                    parent=parent_path,
                    name=item.name,
                    language=item.source_language,
                    audio_file=audio_file,
                )
            else:
                requested_type = get_version_layout(
                    self.recipe.version
                ).requested_type(item.object_type)
                object_id = self.backend.create(
                    parent=parent_path,
                    object_type=requested_type,
                    name=item.name,
                )
            rows = self._read_path(item.path, language=language)
            if len(rows) != 1 or str(rows[0].get("id")) != object_id:
                raise ObjectRuntimeError(f"created fixture object did not resolve exactly: {item.path}")
            materialized[item.key] = self._materialize_fixture(item, rows[0])

        for item in ordered:
            if item.role == "borrowed":
                continue
            object_id = materialized[item.key].id
            if item.notes is not None:
                self.backend.set_notes(object_id, item.notes)
            for prop in item.properties:
                self.backend.set_property(object_id, prop.name, prop.value)
            for reference in item.references:
                target = materialized.get(reference.target_key)
                if target is None:
                    raise ObjectRuntimeError(f"fixture reference target is missing: {reference.target_key}")
                self.backend.set_reference(object_id, reference.name, target.id)
            if item.is_included is not None:
                self.backend.set_inclusion(object_id, item.is_included)
        self.backend.save()
        self.before = self.snapshot()
        expected_keys = {item.key for item in self.recipe.fixture.objects}
        if set(self.before.by_key()) != expected_keys:
            raise ObjectRuntimeError("fixture snapshot did not close every symbolic key")
        if self.before.absent_paths != self.recipe.fixture.absent_paths:
            raise ObjectRuntimeError("fixture absence proof failed")
        return self

    def _fixture_audio_file(self, item: FixtureObject) -> Path:
        if self.asset_root is None:
            raise ObjectRuntimeError(
                f"{self.recipe.scenario_id} requires an asset_root for language-bound Sound fixtures"
            )
        audio_root = self.asset_root / "object-query-audio"
        audio_root.mkdir(parents=True, exist_ok=True)
        path = audio_root / f"{item.key}.wav"
        if path.exists() or path.is_symlink():
            raise ObjectRuntimeError(f"fixture audio path already exists: {path}")
        _write_pcm_wav(path, frequency_hz=220 + (sum(item.key.encode("utf-8")) % 401))
        return path

    def _materialize_fixture(
        self,
        item: FixtureObject,
        row: Mapping[str, Any],
    ) -> MaterializedObject:
        """Materialize a fixture row, resolving voice language through its active source.

        A Sound's displayed language is not a sufficient proof of the imported
        source language.  The fixture recipe is closed, so a language-bound
        Sound must expose one exact active AudioFileSource with the reviewed
        language and direct parent identity.
        """

        language_context = self._fixture_language(item)
        # Wwise may expose a Sound-level display/convenience value with a
        # different shape from the active source.  It is never evidence for a
        # language-bound fixture, so exclude it before generic materialization.
        materialized_row: Mapping[str, Any] = row
        if language_context is not None and "audioSource:language" in row:
            materialized_row = {
                key: value
                for key, value in row.items()
                if key != "audioSource:language"
            }
        materialized = _materialize(item.key, materialized_row)
        if materialized.type != item.object_type:
            raise ObjectRuntimeError(
                f"{item.key}: fixture type {materialized.type!r} "
                f"!= reviewed reflected type {item.object_type!r}"
            )
        if language_context is None:
            return materialized
        active_source_id = _reference_id(row.get("activeSource"))
        source_rows: tuple[Mapping[str, Any], ...] = ()
        if self.recipe.version == "2021.1":
            source_rows = tuple(
                source
                for source in self.backend.read_children(
                    materialized.id,
                    fields=_ACTIVE_SOURCE_FIELDS,
                )
                if str(source.get("type") or "").casefold() == "audiofilesource"
                and _reference_id(source.get("parent")) == materialized.id
            )
            if len(source_rows) == 1:
                active_source_id = _reference_id(source_rows[0].get("id"))
        if active_source_id is None:
            raise ObjectRuntimeError(
                f"{item.key}: language-bound Sound is missing activeSource identity"
            )
        if self.recipe.version != "2021.1":
            source_rows = self.backend.read_id(
                active_source_id,
                fields=_ACTIVE_SOURCE_FIELDS,
                language=language_context,
            )
        if len(source_rows) != 1:
            raise ObjectRuntimeError(
                f"{item.key}: activeSource must resolve exactly once"
            )
        source = source_rows[0]
        if _text(source.get("id"), "activeSource id") != active_source_id:
            raise ObjectRuntimeError(f"{item.key}: activeSource identity mismatch")
        if _text(source.get("type"), "activeSource type") != "AudioFileSource":
            raise ObjectRuntimeError(f"{item.key}: activeSource must be an AudioFileSource")
        if _reference_id(source.get("parent")) != materialized.id:
            raise ObjectRuntimeError(f"{item.key}: activeSource parent identity mismatch")
        source_name = _text(source.get("name"), "activeSource name")
        source_path = _path(source.get("path"))
        if source_name != item.key or source_path != f"{materialized.path}\\{source_name}":
            raise ObjectRuntimeError(
                f"{item.key}: activeSource name/path differs from the sealed fixture input"
            )
        language = _language_name(source.get("audioSource:language"))
        if language != language_context:
            raise ObjectRuntimeError(
                f"{item.key}: activeSource language {language!r} != fixture language {language_context!r}"
            )
        return MaterializedObject(
            key=materialized.key,
            id=materialized.id,
            name=materialized.name,
            type=materialized.type,
            path=materialized.path,
            parent_id=materialized.parent_id,
            notes=materialized.notes,
            properties=materialized.properties,
            references=materialized.references,
            source_language=language,
            is_included=materialized.is_included,
            children_count=materialized.children_count,
            active_source_id=active_source_id,
            active_source_name=source_name,
            active_source_path=source_path,
        )

    @staticmethod
    def _fixture_language(item: FixtureObject) -> str | None:
        language = item.source_language
        if language is not None and language not in _FIXTURE_LANGUAGES:
            raise ObjectRuntimeError(f"fixture sound language is not closed: {language!r}")
        return language

    def snapshot(self) -> ObjectRuntimeSnapshot:
        """Capture the strict fixture state used before execution and for reads."""

        return self._snapshot(allowed_present_paths=frozenset())

    def _snapshot(
        self,
        *,
        allowed_present_paths: frozenset[str],
    ) -> ObjectRuntimeSnapshot:
        """Capture state while preserving the reviewed pre/post absence split.

        ``fixture.absent_paths`` are preconditions.  A mutation may legitimately
        create only the subset that is also an oracle expected-object path; all
        other absent paths remain negative postconditions (for example, an
        unwanted automatically renamed sibling).
        """

        objects: list[MaterializedObject] = []
        output_bus_overrides: dict[str, bool | None] = {}
        absent: list[str] = []
        for item in self.recipe.fixture.objects:
            language = self._fixture_language(item)
            rows = self._read_path(item.path, language=language)
            if len(rows) > 1:
                raise ObjectRuntimeError(f"fixture path resolved more than once: {item.path}")
            if rows:
                output_bus_overrides[item.key] = _output_bus_override(rows[0])
                objects.append(self._materialize_fixture(item, rows[0]))
        for path in self.recipe.fixture.absent_paths:
            rows = self.backend.read_path(path, fields=_GUID_FIELDS)
            if path in allowed_present_paths:
                continue
            if rows:
                raise ObjectRuntimeError(f"path expected absent is present: {path}")
            absent.append(path)
        prefixes: list[tuple[str, tuple[tuple[str, str, str], ...]]] = []
        for parent_path, prefix in self.recipe.fixture.absent_sibling_prefixes:
            parents = self.backend.read_path(parent_path, fields=_GUID_FIELDS)
            if len(parents) != 1:
                raise ObjectRuntimeError(f"prefix parent must resolve once: {parent_path}")
            children = self.backend.read_children(str(parents[0]["id"]), fields=_GUID_FIELDS)
            rows = tuple(
                sorted(
                    (
                        str(row.get("id") or ""),
                        str(row.get("name") or ""),
                        str(row.get("path") or ""),
                    )
                    for row in children
                    if (
                        str(row.get("name") or "").startswith(prefix)
                        and str(row.get("name") or "") != prefix
                    )
                )
            )
            prefixes.append((f"{parent_path}|{prefix}", rows))
        payload = {
            "objects": [asdict(item) for item in objects],
            "absent_paths": absent,
            "sibling_prefix_rows": prefixes,
            "override_output_rows": [
                (item.key, output_bus_overrides[item.key])
                for item in self.recipe.fixture.objects
                if item.key in output_bus_overrides
            ],
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        self._last_snapshot_output_bus_overrides = dict(output_bus_overrides)
        if self.before is None and self._before_output_bus_overrides is None:
            self._before_output_bus_overrides = dict(output_bus_overrides)
        return ObjectRuntimeSnapshot(
            tuple(objects),
            tuple(absent),
            tuple(prefixes),
            digest,
            tuple(
                (item.key, output_bus_overrides[item.key])
                for item in self.recipe.fixture.objects
                if item.key in output_bus_overrides
            ),
        )

    def verify_preview_unchanged(self) -> ObjectRuntimeVerification:
        before = self._before()
        after = self.snapshot()
        failures = () if after.digest == before.digest else ("object fixture changed before confirmation",)
        return ObjectRuntimeVerification("preview", not failures, failures, {"before": before.digest, "after": after.digest})

    def verify_policy_read_only_unchanged(self) -> ObjectRuntimeVerification:
        """Prove the complete object fixture stayed equal to its sealed baseline."""

        before = self._before()
        after = self.snapshot()
        failures = (
            ()
            if after == before
            else ("read_only policy task changed the object fixture",)
        )
        return ObjectRuntimeVerification(
            "policy_read_only",
            not failures,
            failures,
            {"before": asdict(before), "after": asdict(after)},
        )

    def verify_after_execution(self) -> ObjectRuntimeVerification:
        before = self._before()
        before_by_key = before.by_key()
        resolved: dict[str, MaterializedObject] = {}
        removed_readback: dict[str, list[dict[str, Any]]] = {}
        protected_before: dict[str, dict[str, Any]] = {}
        protected_after: dict[str, dict[str, Any] | None] = {}
        protected_comparisons: dict[str, dict[str, Any]] = {}
        failures: list[str] = []
        all_before_ids = {item.id for item in before.objects}

        for expected in self.recipe.oracle.expected_objects:
            if expected.path is not None:
                rows = self._read_path(expected.path)
            else:
                parent = resolved.get(expected.parent_key or "") or before_by_key.get(expected.parent_key or "")
                if parent is None and expected.parent_path:
                    parent_rows = self.backend.read_path(expected.parent_path)
                    parent = _materialize(f"parent:{expected.key}", parent_rows[0]) if len(parent_rows) == 1 else None
                if parent is None:
                    failures.append(f"{expected.key}: dynamic parent is unresolved")
                    continue
                candidates = self.backend.read_children(
                    parent.id,
                    fields=self._read_fields,
                )
                rows = tuple(
                    row
                    for row in candidates
                    if str(row.get("type")) == expected.object_type
                    and (
                        str(row.get("name")) == expected.requested_name
                        or (
                            expected.identity_policy == "new_renamed"
                            and str(row.get("name", "")).startswith(expected.requested_name)
                        )
                    )
                    and str(row.get("id")) not in all_before_ids
                )
            if len(rows) != 1:
                failures.append(f"{expected.key}: expected exactly one after-state row, found {len(rows)}")
                continue
            actual = _materialize(expected.key, rows[0])
            resolved[expected.key] = actual
            if actual.type != expected.object_type:
                failures.append(f"{expected.key}: type {actual.type!r} != {expected.object_type!r}")
            previous = before_by_key.get(expected.key)
            if expected.identity_policy in {"preserve", "borrowed_snapshot"} and (previous is None or actual.id != previous.id):
                failures.append(f"{expected.key}: identity was not preserved")
            if expected.identity_policy in {"new", "new_renamed", "replace_with_new"} and actual.id in all_before_ids:
                failures.append(f"{expected.key}: expected a new identity")
            parent = resolved.get(expected.parent_key or "") or before_by_key.get(expected.parent_key or "")
            if parent is not None and actual.parent_id != parent.id:
                failures.append(f"{expected.key}: parent identity mismatch")

        for key in self.recipe.oracle.removed_keys:
            old = before_by_key.get(key)
            rows = self.backend.read_id(old.id, fields=_GUID_FIELDS) if old is not None else ()
            removed_readback[key] = [
                asdict(_materialize(key, row)) for row in rows
            ]
            if old is not None and rows:
                failures.append(f"{key}: removed identity still exists")
        for key in self.recipe.oracle.protected_snapshot_keys:
            old = before_by_key.get(key)
            if old is None:
                failures.append(f"{key}: protected before-state missing")
                continue
            protected_before[key] = asdict(old)
            rows = self._read_path(old.path)
            current = _materialize(key, rows[0]) if len(rows) == 1 else None
            protected_after[key] = asdict(current) if current is not None else None
            before_override = self._before_output_bus_override(key)
            after_override = (
                _output_bus_override(rows[0]) if len(rows) == 1 else None
            )
            override_required = old.type in _OUTPUT_BUS_OVERRIDE_TYPES
            ignored_derived_fields, inherited_mismatches = (
                _protected_inherited_effective_fields(
                    key,
                    before=old,
                    current=current,
                    before_by_key=before_by_key,
                    resolved=resolved,
                    recipe=self.recipe,
                    before_override=before_override,
                    after_override=after_override,
                )
                if current is not None
                else ((), ())
            )
            before_projection = _protected_intrinsic_projection(
                old,
                ignored_derived_fields=ignored_derived_fields,
            )
            after_projection = (
                _protected_intrinsic_projection(
                    current,
                    ignored_derived_fields=ignored_derived_fields,
                )
                if current is not None
                else None
            )
            comparison_passed = (
                current is not None
                and (not override_required or type(before_override) is bool)
                and (not override_required or type(after_override) is bool)
                and before_override == after_override
                and not inherited_mismatches
                and before_projection == after_projection
            )
            protected_comparisons[key] = {
                "override_output_before": before_override,
                "override_output_after": after_override,
                "ignored_derived_fields": list(ignored_derived_fields),
                "before_projection": before_projection,
                "after_projection": after_projection,
                "passed": comparison_passed,
            }
            if override_required and type(before_override) is not bool:
                failures.append(
                    f"{key}: protected before-state OverrideOutput is not explicit"
                )
            elif override_required and type(after_override) is not bool:
                failures.append(
                    f"{key}: protected after-state OverrideOutput is not explicit"
                )
            elif before_override != after_override:
                failures.append(f"{key}: protected OverrideOutput changed")
            elif inherited_mismatches:
                failures.append(
                    f"{key}: protected inherited effective fields differ from "
                    f"reviewed parent: {', '.join(inherited_mismatches)}"
                )
            elif before_projection != after_projection:
                failures.append(f"{key}: protected snapshot changed")

        for expected in self.recipe.oracle.expected_objects:
            actual = resolved.get(expected.key)
            if actual is None:
                continue
            for field in expected.fields:
                actual_value = _materialized_field(actual, field.name)
                if field.mode == "literal" and actual_value != field.value:
                    failures.append(f"{expected.key}.{field.name}: literal mismatch")
                elif field.mode == "object_key_id":
                    target = resolved.get(str(field.value)) or before_by_key.get(str(field.value))
                    if target is None or actual_value != target.id:
                        failures.append(f"{expected.key}.{field.name}: reference identity mismatch")
                elif field.mode == "derived_children_count" and actual.children_count != len(expected.children):
                    failures.append(f"{expected.key}.childrenCount: topology count mismatch")
                elif field.mode == "sealed_fixture_snapshot":
                    previous = before_by_key.get(expected.key)
                    if previous is None or actual_value != _materialized_field(previous, field.name):
                        failures.append(f"{expected.key}.{field.name}: sealed fixture field changed")
            if expected.children:
                children = self.backend.read_children(actual.id, fields=_GUID_FIELDS)
                child_ids = [str(row.get("id")) for row in children]
                expected_ids: list[str] = []
                for key in expected.children:
                    child = resolved.get(key) or before_by_key.get(key)
                    if child is None:
                        failures.append(
                            f"{expected.key}: expected child {key!r} is unresolved"
                        )
                        continue
                    expected_ids.append(child.id)
                if child_ids != expected_ids:
                    failures.append(
                        f"{expected.key}: direct child identity order mismatch"
                    )

        expected_present_paths = frozenset(
            expected.path
            for expected in self.recipe.oracle.expected_objects
            if expected.path is not None
        )
        after = self._snapshot(allowed_present_paths=expected_present_paths)
        return ObjectRuntimeVerification(
            "after",
            not failures,
            tuple(failures),
            {
                "before": asdict(before),
                "after": asdict(after),
                "resolved": {key: asdict(value) for key, value in resolved.items()},
                "expected_resolved_keys": [item.key for item in self.recipe.oracle.expected_objects],
                "removed_keys": list(self.recipe.oracle.removed_keys),
                "removed_readback": removed_readback,
                "protected_keys": list(self.recipe.oracle.protected_snapshot_keys),
                "protected_before": protected_before,
                "protected_after": protected_after,
                "protected_comparisons": protected_comparisons,
            },
        )

    def _before_output_bus_override(self, key: str) -> bool | None:
        if self.before is not None and self.before.override_output_rows:
            values = self.before.override_output_by_key()
            if key in values:
                return values[key]
        if (
            self._before_output_bus_overrides is not None
            and key in self._before_output_bus_overrides
        ):
            return self._before_output_bus_overrides[key]
        fixture = self.recipe.fixture.object(key)
        if fixture.role == "borrowed" or fixture.object_type not in _OUTPUT_BUS_OVERRIDE_TYPES:
            return None
        return any(reference.name == "OutputBus" for reference in fixture.references)

    def verify_query_result(
        self,
        payload: Mapping[str, Any],
        *,
        final_response: str,
    ) -> ObjectRuntimeVerification:
        request = self.recipe.request
        if not isinstance(request, QueryObjectRequestSpec):
            raise ObjectRuntimeError("query verification requires a query recipe")
        raw_rows = payload.get("objects")
        failures: list[str] = []
        if payload.get("contract") != "waapi-skill.gateway-result/v1" or payload.get("command") != "query-object":
            failures.append("query payload contract/command mismatch")
        if not isinstance(raw_rows, list) or not all(isinstance(row, Mapping) for row in raw_rows):
            failures.append("query payload objects are malformed")
            raw_rows = []
        before = self._before().by_key()
        id_to_key = {item.id: key for key, item in before.items()}
        observed_keys: list[str] = []
        primary_rows: list[Mapping[str, Any]] = []
        derived_rows: list[Mapping[str, Any]] = []
        for row in raw_rows:
            key = id_to_key.get(str(row.get("id")))
            if key is None:
                derived_rows.append(row)
            else:
                observed_keys.append(key)
                primary_rows.append(row)
        expected_payload = (
            request.bounded_superset_keys
            if request.result_strategy == "bounded_superset_final_answer_filter"
            else request.exact_expected_keys
        )
        failures.extend(
            _verify_query_primary_rows(
                request,
                before,
                primary_rows,
                observed_keys,
                expected_payload=expected_payload,
            )
        )
        raw_row_count = len(raw_rows)
        query_bound = payload.get("query_bound")
        bound_reached = raw_row_count == request.take
        if payload.get("count") != raw_row_count:
            failures.append("query payload count differs from raw rows")
        if query_bound != {"mode": "take", "value": request.take}:
            failures.append("query payload bound differs from reviewed take")
        bound_rule = next(
            (
                rule
                for rule in self.recipe.oracle.rules
                if rule.kind == "bound_reached_equal"
            ),
            None,
        )
        if bound_rule is not None:
            expected_bound = dict(bound_rule.expected)
            if (
                expected_bound != {"take": request.take, "reached": bound_reached}
            ):
                failures.append("query bound-reached state differs from hidden oracle")
        derived_proof, derived_failures = _verify_query_derived_rows(
            request,
            before,
            derived_rows,
        )
        failures.extend(derived_failures)
        (
            required_tokens,
            excluded_tokens,
            paired_rows,
            deduplicated_parent_rows,
            coverage_summary,
            answer_order,
            answer_failures,
        ) = _verify_query_final_answer(
            request,
            before,
            excluded_keys=self.recipe.oracle.excluded_keys,
            expected_order_keys=self.recipe.oracle.expected_order_keys,
            final_response=final_response,
        )
        failures.extend(answer_failures)
        after = self.snapshot()
        unchanged = after.digest == self._before().digest
        if not unchanged:
            failures.append("read-only object query changed fixture state")
        return ObjectRuntimeVerification(
            "query",
            not failures,
            tuple(failures),
            {
                "before": asdict(self._before()),
                "after": asdict(after),
                "observed_keys": observed_keys,
                "expected_payload_keys": expected_payload,
                "primary_row_policy": request.primary_row_policy,
                "raw_row_count": raw_row_count,
                "query_bound": query_bound,
                "bound_reached": bound_reached,
                "derived_row_policy": request.derived_row_policy,
                "derived_rows": derived_proof,
                "required_keys": request.exact_expected_keys,
                "excluded_keys": self.recipe.oracle.excluded_keys,
                "final_answer_policy": request.final_answer_policy,
                "required_identity_tokens": required_tokens,
                "excluded_identity_tokens": excluded_tokens,
                "paired_rows": paired_rows,
                "deduplicated_parent_rows": deduplicated_parent_rows,
                "coverage_summary": coverage_summary,
                "observed_answer_order": answer_order,
                "final_response_sha256": hashlib.sha256(
                    final_response.encode("utf-8")
                ).hexdigest(),
            },
        )

    def _before(self) -> ObjectRuntimeSnapshot:
        if self.before is None:
            raise ObjectRuntimeError("object runtime has not been prepared")
        return self.before


def _verify_query_primary_rows(
    request: QueryObjectRequestSpec,
    before: Mapping[str, MaterializedObject],
    rows: Sequence[Mapping[str, Any]],
    observed_keys: Sequence[str],
    *,
    expected_payload: Sequence[str],
) -> tuple[str, ...]:
    failures: list[str] = []
    if request.primary_row_policy == "unique_identity_rows":
        if (
            len(observed_keys) != len(expected_payload)
            or len(observed_keys) != len(set(observed_keys))
            or set(observed_keys) != set(expected_payload)
        ):
            failures.append(
                "query primary identities differ: "
                f"observed={tuple(observed_keys)} expected={tuple(expected_payload)}"
            )
        return tuple(failures)
    if request.primary_row_policy == "ancestor_identity_rows":
        if (
            len(observed_keys) != len(expected_payload)
            or len(observed_keys) != len(set(observed_keys))
            or set(observed_keys) != set(expected_payload)
        ):
            failures.append(
                "query ancestor identities differ: "
                f"observed={tuple(observed_keys)} expected={tuple(expected_payload)}"
            )
        if len(rows) != len(expected_payload):
            failures.append("query ordered ancestor row count differs")
            return tuple(failures)
        for index, (key, row) in enumerate(zip(observed_keys, rows, strict=True)):
            expected = before[key]
            for field_name in request.return_fields:
                if _query_row_field(row, field_name) != _materialized_field(
                    expected, field_name
                ):
                    failures.append(
                        f"query ancestor {key}[{index}].{field_name} "
                        "differs from sealed ancestor"
                    )
        return tuple(failures)
    if request.primary_row_policy != "parent_projection_per_source_row":
        raise ObjectRuntimeError(
            f"unknown query primary-row policy: {request.primary_row_policy}"
        )

    expected_set = set(expected_payload)
    observed_counts = Counter(observed_keys)
    if set(observed_counts) != expected_set:
        failures.append(
            "query parent-projection identity set differs: "
            f"observed={tuple(observed_keys)} expected={tuple(expected_payload)}"
        )
    if len(observed_keys) == len(set(observed_keys)):
        failures.append("query parent-projection rows were unexpectedly unique")
    if len(observed_keys) != request.take:
        failures.append(
            f"query parent-projection row count differs: observed={len(observed_keys)} "
            f"take={request.take}"
        )

    direct_sound_counts = {
        key: sum(
            item.type == "Sound" and item.parent_id == before[key].id
            for item in before.values()
        )
        for key in expected_payload
    }
    if sum(direct_sound_counts.values()) <= request.take:
        failures.append("query fixture does not prove a truncated parent projection")
    for key in expected_payload:
        observed_count = observed_counts.get(key, 0)
        if not 1 <= observed_count <= direct_sound_counts[key]:
            failures.append(
                f"query parent-projection multiplicity differs for {key}: "
                f"observed={observed_count} capacity={direct_sound_counts[key]}"
            )

    key_rows: dict[str, list[Mapping[str, Any]]] = {
        key: [] for key in expected_payload
    }
    for key, row in zip(observed_keys, rows, strict=True):
        if key in key_rows:
            key_rows[key].append(row)
    for key, repeated_rows in key_rows.items():
        expected = before[key]
        for index, row in enumerate(repeated_rows):
            for field_name in request.return_fields:
                actual_value = _query_row_field(row, field_name)
                expected_value = _materialized_field(expected, field_name)
                if actual_value != expected_value:
                    failures.append(
                        f"query parent-projection {key}[{index}].{field_name} "
                        "differs from sealed parent"
                    )
    return tuple(failures)


def _query_row_field(row: Mapping[str, Any], name: str) -> Any:
    properties = row.get("properties")
    references = row.get("references")
    if name == "@Volume" and isinstance(properties, Mapping):
        return properties.get("volume_db")
    if name == "OutputBus" and isinstance(references, Mapping):
        return _reference_id(references.get("output_bus"))
    if name == "isIncluded" and "included" in row:
        return row.get("included")
    if name == "parent":
        return _reference_id(row.get(name))
    if name == "audioSource:language":
        return _language_name(row.get(name))
    if name == "childrenCount":
        value = row.get(name)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else value
    if name.startswith("@") or name in {
        "id",
        "name",
        "type",
        "path",
        "notes",
        "isIncluded",
    }:
        return row.get(name)
    return _reference_id(row.get(name))


def _verify_query_derived_rows(
    request: QueryObjectRequestSpec,
    before: Mapping[str, MaterializedObject],
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Validate Wwise-owned descendants without widening fixture identities."""

    if request.derived_row_policy == "none":
        failures = (
            (f"query returned {len(rows)} unapproved derived rows",)
            if rows
            else ()
        )
        return [], failures
    if request.derived_row_policy != "active_audio_sources_for_sound_rows":
        raise ObjectRuntimeError(
            f"unknown query derived-row policy: {request.derived_row_policy}"
        )

    expected = tuple(
        _sealed_active_source_row(before[key])
        for key in request.bounded_superset_keys
        if before[key].type == "Sound" and before[key].source_language is not None
    )
    expected_by_id = {row["id"]: row for row in expected}
    failures: list[str] = []
    actual_by_id: dict[str, dict[str, Any]] = {}
    seen_ids: list[str] = []
    seen_parents: list[str | None] = []
    for index, row in enumerate(rows):
        object_id = row.get("id")
        source_id = str(object_id) if isinstance(object_id, str) else ""
        parent_id = _reference_id(row.get("parent"))
        seen_ids.append(source_id)
        seen_parents.append(parent_id)
        if not source_id or source_id not in expected_by_id:
            failures.append(f"derived row {index} has an unknown activeSource identity")
            continue
        try:
            language = _language_name(row.get("audioSource:language"))
        except ObjectRuntimeError as exc:
            failures.append(f"derived row {source_id} has invalid language: {exc}")
            language = None
        normalized = {
            "sound_key": expected_by_id[source_id]["sound_key"],
            "sound_id": expected_by_id[source_id]["sound_id"],
            "id": source_id,
            "name": row.get("name"),
            "type": row.get("type"),
            "path": row.get("path"),
            "parent_id": parent_id,
            "language": language,
        }
        if source_id in actual_by_id:
            failures.append(f"derived activeSource identity is duplicated: {source_id}")
        else:
            actual_by_id[source_id] = normalized
        expected_row = expected_by_id[source_id]
        for field in ("sound_key", "sound_id", "id", "name", "type", "path", "parent_id", "language"):
            if normalized[field] != expected_row[field]:
                failures.append(
                    f"derived {expected_row['sound_key']}.{field} differs from sealed activeSource"
                )
    if len(seen_ids) != len(set(seen_ids)):
        failures.append("derived activeSource identities are not unique")
    if len(seen_parents) != len(set(seen_parents)):
        failures.append("derived activeSource parent identities are not unique")
    if len(rows) != len(expected):
        failures.append(
            f"derived activeSource count differs: observed={len(rows)} expected={len(expected)}"
        )
    missing = [row["sound_key"] for row in expected if row["id"] not in actual_by_id]
    if missing:
        failures.append(f"derived activeSource rows are missing for {tuple(missing)}")
    proof = [actual_by_id[row["id"]] for row in expected if row["id"] in actual_by_id]
    return proof, tuple(failures)


def _sealed_active_source_row(item: MaterializedObject) -> dict[str, Any]:
    values = (item.active_source_id, item.active_source_name, item.active_source_path)
    if (
        item.type != "Sound"
        or item.source_language is None
        or any(not isinstance(value, str) or not value for value in values)
        or item.active_source_path
        != f"{item.path}\\{item.active_source_name}"
    ):
        raise ObjectRuntimeError(
            f"{item.key}: sealed activeSource binding is incomplete or inconsistent"
        )
    return {
        "sound_key": item.key,
        "sound_id": item.id,
        "id": item.active_source_id,
        "name": item.active_source_name,
        "type": "AudioFileSource",
        "path": item.active_source_path,
        "parent_id": item.id,
        "language": item.source_language,
    }


def _verify_query_final_answer(
    request: QueryObjectRequestSpec,
    before: Mapping[str, MaterializedObject],
    *,
    excluded_keys: Sequence[str],
    expected_order_keys: Sequence[str],
    final_response: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any] | None,
    list[str],
    tuple[str, ...],
]:
    if request.final_answer_policy == "name_and_id":
        folded = final_response.casefold()
        required: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        failures: list[str] = []
        for key in request.exact_expected_keys:
            item = before[key]
            row = {
                "key": key,
                "name": item.name,
                "id": item.id,
                "name_present": item.name.casefold() in folded,
                "id_present": item.id.casefold() in folded,
            }
            required.append(row)
            if not row["name_present"] or not row["id_present"]:
                failures.append(f"final answer omits expected identity {key}")
        for key in excluded_keys:
            item = before[key]
            row = {
                "key": key,
                "id": item.id,
                "id_present": item.id.casefold() in folded,
            }
            excluded.append(row)
            if row["id_present"]:
                failures.append(f"final answer includes excluded identity {key}")
        return required, excluded, [], [], None, [], tuple(failures)
    if request.final_answer_policy == "paired_path_rows":
        required, excluded, paired, order, failures = _paired_path_answer_proof(
            request,
            before,
            excluded_keys=excluded_keys,
            expected_order_keys=expected_order_keys,
            final_response=final_response,
        )
        return required, excluded, paired, [], None, order, failures
    if request.final_answer_policy == "deduplicated_parent_summary":
        return _deduplicated_parent_answer_proof(
            request,
            before,
            excluded_keys=excluded_keys,
            expected_order_keys=expected_order_keys,
            final_response=final_response,
        )
    if request.final_answer_policy == "ordered_ancestor_summary":
        return _ordered_ancestor_answer_proof(
            request,
            before,
            excluded_keys=excluded_keys,
            expected_order_keys=expected_order_keys,
            final_response=final_response,
        )
    raise ObjectRuntimeError(
        f"unknown query final-answer policy: {request.final_answer_policy}"
    )


def _paired_path_answer_proof(
    request: QueryObjectRequestSpec,
    before: Mapping[str, MaterializedObject],
    *,
    excluded_keys: Sequence[str],
    expected_order_keys: Sequence[str],
    final_response: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
    tuple[str, ...],
]:
    failures: list[str] = []
    lines = final_response.splitlines()
    required: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    id_to_key = {item.id: key for key, item in before.items()}
    exact = set(request.exact_expected_keys)
    expected_children = [
        key
        for key in expected_order_keys
        if before[key].type == "Sound"
        and before[key].parent_id is not None
        and id_to_key.get(before[key].parent_id) in exact
    ]
    paired_line_indexes = [
        index
        for child_key in expected_children
        for index, line in enumerate(lines)
        if (
            (parent_key := id_to_key.get(before[child_key].parent_id or ""))
            is not None
            and _path_token_offsets(line, before[child_key].path)
            and _path_token_offsets(line, before[parent_key].path)
        )
    ]
    result_start = min(paired_line_indexes) if paired_line_indexes else 0
    result_lines = lines[result_start:]
    for key in request.exact_expected_keys:
        item = before[key]
        matches = [
            (result_start + index, offset)
            for index, line in enumerate(result_lines)
            for offset in _path_token_offsets(line, item.path)
        ]
        required.append(
            {
                "key": key,
                "path": item.path,
                "occurrence_count": len(matches),
                "first_line": matches[0][0] if matches else None,
            }
        )
        if not matches:
            failures.append(f"final answer omits standalone path identity {key}")
    for key in excluded_keys:
        item = before[key]
        matches = [
            (result_start + index, offset)
            for index, line in enumerate(result_lines)
            for offset in _path_token_offsets(line, item.path)
        ]
        excluded.append(
            {
                "key": key,
                "path": item.path,
                "occurrence_count": len(matches),
            }
        )
        if matches:
            failures.append(f"final answer includes excluded standalone path {key}")

    all_languages = {
        item.source_language
        for item in before.values()
        if item.source_language is not None
    }
    all_notes = {
        item.notes.casefold()
        for item in before.values()
        if item.type == "Sound" and isinstance(item.notes, str) and item.notes
    }
    paired: list[dict[str, Any]] = []
    order_rows: list[tuple[int, str]] = []
    for child_key in expected_children:
        child = before[child_key]
        parent_key = id_to_key.get(child.parent_id or "")
        if parent_key is None or parent_key not in exact:
            raise ObjectRuntimeError(
                f"{child_key}: paired-answer parent is not an exact expected identity"
            )
        parent = before[parent_key]
        child_matches = [
            (index, offset)
            for index, line in enumerate(lines)
            for offset in _path_token_offsets(line, child.path)
            if _path_token_offsets(line, parent.path)
        ]
        line_index = child_matches[0][0] if child_matches else None
        line = lines[line_index] if line_index is not None else ""
        expected_volume = _one_volume(child)
        numeric_values = [float(value) for value in _NUMBER_TOKEN_RE.findall(line)]
        language_present = (
            isinstance(child.source_language, str)
            and child.source_language.casefold() in line.casefold()
        )
        unexpected_languages = sorted(
            language
            for language in all_languages
            if language != child.source_language
            and language.casefold() in line.casefold()
        )
        notes = child.notes if isinstance(child.notes, str) else ""
        notes_present = bool(notes) and notes.casefold() in line.casefold()
        unexpected_notes = sorted(
            value
            for value in all_notes
            if value != notes.casefold() and value in line.casefold()
        )
        row = {
            "child_key": child_key,
            "parent_key": parent_key,
            "parent_path": parent.path,
            "child_path": child.path,
            "language": child.source_language,
            "volume": expected_volume,
            "notes": notes,
            "line_index": line_index,
            "line_sha256": (
                hashlib.sha256(line.encode("utf-8")).hexdigest()
                if line_index is not None
                else None
            ),
            "parent_path_count": len(_path_token_offsets(line, parent.path)),
            "child_path_count": len(_path_token_offsets(line, child.path)),
            "language_present": language_present,
            "volume_values": numeric_values,
            "notes_present": notes_present,
            "unexpected_languages": unexpected_languages,
            "unexpected_notes": unexpected_notes,
        }
        paired.append(row)
        if len(child_matches) != 1:
            failures.append(
                f"final answer must contain one exact child path for {child_key}; "
                f"found {len(child_matches)}"
            )
        else:
            order_rows.append((child_matches[0][0], child_key))
        if row["parent_path_count"] != 1:
            failures.append(f"final answer does not pair {child_key} with its parent path")
        if row["child_path_count"] != 1:
            failures.append(f"final answer child path record is ambiguous for {child_key}")
        if not language_present or unexpected_languages:
            failures.append(f"final answer language differs for {child_key}")
        if numeric_values != [float(expected_volume)]:
            failures.append(f"final answer Volume differs for {child_key}")
        if not notes_present or unexpected_notes:
            failures.append(f"final answer notes differ for {child_key}")
    answer_order = [key for _, key in sorted(order_rows)]
    if len({line_index for line_index, _ in order_rows}) != len(order_rows):
        failures.append("final answer combines multiple child records on one line")
    if answer_order != expected_children:
        failures.append(
            f"final answer row order differs: observed={answer_order} expected={expected_children}"
        )
    return required, excluded, paired, answer_order, tuple(failures)


def _deduplicated_parent_answer_proof(
    request: QueryObjectRequestSpec,
    before: Mapping[str, MaterializedObject],
    *,
    excluded_keys: Sequence[str],
    expected_order_keys: Sequence[str],
    final_response: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    list[str],
    tuple[str, ...],
]:
    failures: list[str] = []
    lines = final_response.splitlines()
    folded = final_response.casefold()
    required: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    parent_rows: list[dict[str, Any]] = []
    order_rows: list[tuple[int, str]] = []
    by_id = {item.id: item for item in before.values()}

    for key in request.exact_expected_keys:
        item = before[key]
        path_matches = [
            (index, offset)
            for index, line in enumerate(lines)
            for offset in _path_token_offsets(line, item.path)
        ]
        required.append(
            {
                "key": key,
                "name": item.name,
                "id": item.id,
                "name_present": item.name.casefold() in folded,
                "id_present": item.id.casefold() in folded,
            }
        )
        line_index = path_matches[0][0] if len(path_matches) == 1 else None
        line = lines[line_index] if line_index is not None else ""
        output_bus_ids = [
            value.target_id
            for value in item.references
            if value.name == "OutputBus"
        ]
        if len(output_bus_ids) != 1 or output_bus_ids[0] not in by_id:
            raise ObjectRuntimeError(
                f"{key}: deduplicated parent lacks one sealed OutputBus"
            )
        output_bus = by_id[output_bus_ids[0]]
        numeric_source = line
        for token in (item.id, item.path, output_bus.id, output_bus.name):
            numeric_source = numeric_source.replace(token, "")
        numeric_values = [
            float(value) for value in _NUMBER_TOKEN_RE.findall(numeric_source)
        ]
        row = {
            "key": key,
            "name": item.name,
            "id": item.id,
            "path": item.path,
            "children_count": item.children_count,
            "notes": item.notes,
            "output_bus_id": output_bus.id,
            "output_bus_name": output_bus.name,
            "line_index": line_index,
            "line_sha256": (
                hashlib.sha256(line.encode("utf-8")).hexdigest()
                if line_index is not None
                else None
            ),
        }
        parent_rows.append(row)
        if len(path_matches) != 1:
            failures.append(
                f"final answer must contain one exact parent path for {key}; "
                f"found {len(path_matches)}"
            )
            continue
        order_rows.append((line_index, key))
        if item.id.casefold() not in line.casefold():
            failures.append(f"final answer parent row omits GUID for {key}")
        if item.name.casefold() not in line.casefold():
            failures.append(f"final answer parent row omits name for {key}")
        if not isinstance(item.notes, str) or item.notes.casefold() not in line.casefold():
            failures.append(f"final answer parent row notes differ for {key}")
        if output_bus.name.casefold() not in line.casefold():
            failures.append(f"final answer parent row OutputBus differs for {key}")
        if numeric_values != [float(item.children_count)]:
            failures.append(f"final answer parent row childrenCount differs for {key}")

    for key in excluded_keys:
        item = before[key]
        path_count = sum(
            len(_path_token_offsets(line, item.path)) for line in lines
        )
        id_present = item.id.casefold() in folded
        excluded.append({"key": key, "id": item.id, "id_present": id_present})
        if id_present or path_count:
            failures.append(f"final answer includes excluded parent identity {key}")

    answer_order = [key for _, key in sorted(order_rows)]
    if len({index for index, _ in order_rows}) != len(order_rows):
        failures.append("final answer combines multiple parent records on one line")
    if answer_order != list(expected_order_keys):
        failures.append(
            f"final answer parent order differs: observed={answer_order} "
            f"expected={list(expected_order_keys)}"
        )

    summary_line_index: int | None = None
    for index, line in enumerate(lines):
        lowered = line.casefold()
        numbers = {int(float(value)) for value in _NUMBER_TOKEN_RE.findall(line)}
        if (
            ("父" in line or "container" in lowered)
            and "sound" in lowered
            and len(request.exact_expected_keys) in numbers
            and request.take in numbers
        ):
            summary_line_index = index
            break
    bound_disclosed, incomplete_disclosed = bounded_result_disclosure(
        final_response,
        take=request.take,
    )
    claims_twelve_sounds = _claims_twelve_confirmed_sounds(final_response)
    direct_child_object_count = sum(
        before[key].children_count for key in request.exact_expected_keys
    )
    coverage_summary = {
        "unique_parent_count": len(request.exact_expected_keys),
        "confirmed_sound_count": request.take,
        "direct_child_object_count": direct_child_object_count,
        "summary_line_index": summary_line_index,
        "bound_disclosed": bound_disclosed,
        "incomplete_disclosed": incomplete_disclosed,
        "claims_twelve_sounds": claims_twelve_sounds,
    }
    if summary_line_index is None:
        failures.append("final answer omits the 3-parent/10-Sound summary")
    if not bound_disclosed or not incomplete_disclosed:
        failures.append("final answer omits the reached-bound/incomplete disclosure")
    if claims_twelve_sounds:
        failures.append("final answer overclaims 12 confirmed Sound edges")
    return required, excluded, [], parent_rows, coverage_summary, answer_order, tuple(failures)


def bounded_result_disclosure(value: str, *, take: int) -> tuple[bool, bool]:
    """Recognize a real reached-bound/incomplete disclosure, including paraphrases.

    Merely mentioning ``take`` or a limit is insufficient.  Conversely, a
    user-facing explanation such as "cannot prove there are no more" or "raise
    the limit to confirm the full set" is accepted without requiring one fixed
    phrase.  Explicit claims that the bound was not reached or that the result
    is complete remain fail-closed.
    """

    if not isinstance(value, str) or type(take) is not int or take <= 0:
        return False, False
    clauses = [
        clause.strip().casefold()
        for clause in _ANSWER_CLAUSE_SPLIT_RE.split(value)
        if clause.strip()
    ]
    business_collection_re = (
        r"(?:结果|集合|返回|列表|清单|汇总|记录集|"
        r"覆盖(?:数量|范围)?)"
    )
    raise_limit_re = re.compile(
        r"(?:需要|需|应该|应当|应|必须|须|可以|可).{0,10}"
        r"(?:提高|调高|增加|扩大).{0,8}(?:take|limit|上限|边界)"
        r"|(?:need|must|should|have\s+to|can).{0,14}"
        r"(?:increase|raise|expand).{0,10}(?:take|limit|bound)"
    )
    bound_reached_re = re.compile(
        r"(?:达到|已达|触及|命中|用满|占满|封顶|正好等于|等于).{0,12}"
        r"(?:take(?:\s*=\s*\d+)?|limit|上限|查询边界|返回边界|条数边界)"
        r"|(?:take(?:\s*=\s*\d+)?|limit|上限|查询边界|返回边界|条数边界)"
        r".{0,12}(?:达到|已达|触及|命中|用满|占满|封顶)"
        r"|(?:reach(?:ed)?|hit|touch(?:ed)?|cap(?:ped)?|equal(?:s|led)?)"
        r".{0,12}(?:take(?:\s*=\s*\d+)?|limit|bound)"
        r"|(?:take(?:\s*=\s*\d+)?|limit|bound).{0,12}"
        r"(?:reach(?:ed)?|hit|touch(?:ed)?|cap(?:ped)?)"
    )
    uncertainty_re = re.compile(
        r"(?:不能|无法|不足以|不可|不代表|并不表示|不能排除|不排除).{0,16}"
        r"(?:证明|确认|保证|排除)?.{0,8}(?:没有|不存在|还有|仍有|更多|其余|遗漏)"
        r"|(?:仍|还)?(?:可能|或许|也许).{0,10}(?:有)?(?:更多|其余|遗漏|未返回|剩余)"
        rf"|{business_collection_re}.{{0,16}}(?:可能)?"
        r"(?:不完整|并非完整|不是完整|有遗漏)"
        r"|(?:至少).{0,8}(?:条|个|rows?|results?)"
        r"|(?:cannot|can't|unable\s+to|does\s+not|doesn't).{0,18}"
        r"(?:prove|confirm|guarantee|exclude).{0,18}(?:no\s+more|more|remaining)"
        r"|(?:may|might|could).{0,12}(?:be\s+)?(?:more|remaining|incomplete)"
        r"|(?:not\s+exhaustive|partial|incomplete|truncat(?:ed|ion)?)"
    )
    bound_negation_re = re.compile(
        r"(?:未|没有|尚未|并未).{0,6}(?:达到|触及|命中|用满).{0,8}"
        r"(?:take|limit|上限|边界)"
        r"|(?:not|never|didn't|did\s+not).{0,8}"
        r"(?:reach|hit|touch).{0,8}(?:take|limit|bound)"
        r"|(?:below|under).{0,6}(?:take|limit|bound)"
    )
    complete_claim_re = re.compile(
        rf"{business_collection_re}.{{0,12}}"
        r"(?:是|已|已经|确认)?(?:完整|全部|无遗漏)"
        r"|(?:已|已经)(?:穷尽|返回全部|包含全部)"
        r"|(?:没有|不存在|不会有)(?:任何)?(?:更多|其余|遗漏)"
        r"|(?:results?|set).{0,8}(?:is|are|was|were).{0,5}"
        r"(?:complete|exhaustive)"
        r"|(?:there\s+(?:is|are)\s+no\s+more|no\s+more\s+results?)"
    )
    no_raise_re = re.compile(
        r"(?:无需|不用|不必).{0,8}(?:提高|调高|增加|扩大).{0,8}"
        r"(?:take|limit|上限|边界)"
        r"|(?:need\s+not|no\s+need\s+to|do(?:es)?\s+not\s+need\s+to)"
        r".{0,10}(?:increase|raise|expand).{0,8}(?:take|limit|bound)"
    )

    bound_positive = False
    incomplete_positive = False
    bound_contradicted = False
    incomplete_contradicted = False
    for clause in clauses:
        raised = bool(raise_limit_re.search(clause)) and not no_raise_re.search(
            clause
        )
        truncated = (
            ("截断" in clause and "未截断" not in clause and "没有截断" not in clause)
            or (
                "truncat" in clause
                and not re.search(r"(?:not|never|isn't|wasn't).{0,8}truncat", clause)
            )
        )
        uncertain = bool(uncertainty_re.search(clause))
        if raised or truncated or (
            bound_reached_re.search(clause)
            and not bound_negation_re.search(clause)
        ):
            bound_positive = True
        if raised or truncated or uncertain:
            incomplete_positive = True
        if bound_negation_re.search(clause):
            bound_contradicted = True
        if no_raise_re.search(clause):
            incomplete_contradicted = True
        if not uncertain and complete_claim_re.search(clause):
            incomplete_contradicted = True
    return (
        bound_positive and not bound_contradicted,
        incomplete_positive and not incomplete_contradicted,
    )


def _ordered_ancestor_answer_proof(
    request: QueryObjectRequestSpec,
    before: Mapping[str, MaterializedObject],
    *,
    excluded_keys: Sequence[str],
    expected_order_keys: Sequence[str],
    final_response: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    list[str],
    tuple[str, ...],
]:
    failures: list[str] = []
    lines = final_response.splitlines()
    folded = final_response.casefold()
    required: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    ancestor_rows: list[dict[str, Any]] = []
    order_rows: list[tuple[int, str]] = []

    chain = [before[key] for key in expected_order_keys]
    target = before.get("q5_target")
    if (
        target is None
        or not chain
        or target.parent_id != chain[0].id
        or any(child.parent_id != parent.id for child, parent in zip(chain, chain[1:]))
        or any(item.type == "Project" for item in chain)
    ):
        failures.append("sealed ancestor order is not the target's near-to-far parent chain")

    for ordinal, key in enumerate(request.exact_expected_keys, start=1):
        item = before[key]
        matches = [
            (index, offset)
            for index, line in enumerate(lines)
            for offset in _path_token_offsets(line, item.path)
        ]
        required.append(
            {
                "key": key,
                "name": item.name,
                "id": item.id,
                "name_present": item.name.casefold() in folded,
                "id_present": item.id.casefold() in folded,
            }
        )
        line_index = matches[0][0] if len(matches) == 1 else None
        line = lines[line_index] if line_index is not None else ""
        numbers = _ancestor_numeric_values(line, item)
        ordinal_present = numbers == [float(ordinal), float(item.children_count)]
        notes_present = _ancestor_notes_present(line, item.notes)
        row = {
            "key": key,
            "name": item.name,
            "id": item.id,
            "type": item.type,
            "path": item.path,
            "children_count": item.children_count,
            "notes": item.notes,
            "notes_present": notes_present,
            "ordinal": ordinal,
            "ordinal_present": ordinal_present,
            "numeric_values": numbers,
            "line_index": line_index,
            "line_sha256": (
                hashlib.sha256(line.encode("utf-8")).hexdigest()
                if line_index is not None
                else None
            ),
        }
        ancestor_rows.append(row)
        if len(matches) != 1:
            failures.append(
                f"final answer must contain one exact ancestor path for {key}; "
                f"found {len(matches)}"
            )
            continue
        order_rows.append((line_index, key))
        if item.id.casefold() not in line.casefold():
            failures.append(f"final answer ancestor row omits GUID for {key}")
        if item.name.casefold() not in line.casefold():
            failures.append(f"final answer ancestor row omits name for {key}")
        if item.type.casefold() not in line.casefold():
            failures.append(f"final answer ancestor row type differs for {key}")
        if numbers not in (
            [float(item.children_count)],
            [float(ordinal), float(item.children_count)],
        ):
            failures.append(
                f"final answer ancestor row ordinal/childrenCount differs for {key}"
            )
        if not notes_present:
            failures.append(f"final answer ancestor row notes differ for {key}")

    for key in excluded_keys:
        item = before[key]
        path_count = sum(
            len(_path_token_offsets(line, item.path)) for line in lines
        )
        id_present = item.id.casefold() in folded
        excluded.append({"key": key, "id": item.id, "id_present": id_present})
        if id_present or path_count:
            failures.append(f"final answer includes excluded ancestor identity {key}")

    expected_order = list(expected_order_keys)
    answer_order = [key for _, key in sorted(order_rows)]
    if len({index for index, _ in order_rows}) != len(order_rows):
        failures.append("final answer combines multiple ancestors on one line")
    if answer_order != expected_order:
        failures.append(
            f"final answer ancestor order differs: observed={answer_order} "
            f"expected={expected_order}"
        )
    expected_line_indexes = {
        index for index, _ in order_rows
    }
    if any(
        index not in expected_line_indexes
        and "project" in line.casefold()
        and (
            _GUID_TOKEN_RE.search(line)
            or (line.count("|") >= 3 and "\\" in line)
        )
        for index, line in enumerate(lines)
    ):
        failures.append("final answer includes a Project ancestor row")

    type_counts = {
        "RandomSequenceContainer": sum(
            before[key].type == "RandomSequenceContainer"
            for key in request.exact_expected_keys
        ),
        "ActorMixer": sum(
            before[key].type == "ActorMixer"
            for key in request.exact_expected_keys
        ),
        "WorkUnit": sum(
            before[key].type == "WorkUnit"
            for key in request.exact_expected_keys
        ),
    }
    summary_lines: set[int] = set()
    for label, count in type_counts.items():
        indexes = _summary_type_count_lines(
            lines,
            label,
            count,
            excluded_line_indexes=expected_line_indexes,
        )
        summary_lines.update(indexes)
        if not indexes:
            failures.append(f"final answer type summary differs for {label}")
    truncation_claimed = _claims_query_truncation(final_response)
    if truncation_claimed:
        failures.append("final answer incorrectly claims the ancestor query was truncated")
    default_work_unit_count = sum(
        before[key].name == "Default Work Unit"
        for key in request.exact_expected_keys
    )
    if default_work_unit_count != 1:
        failures.append("sealed ancestor chain lacks exactly one Default Work Unit")
    coverage_summary = {
        "random_sequence_container_count": type_counts[
            "RandomSequenceContainer"
        ],
        "actor_mixer_count": type_counts["ActorMixer"],
        "work_unit_count": type_counts["WorkUnit"],
        "default_work_unit_count": default_work_unit_count,
        "raw_row_count": len(request.exact_expected_keys),
        "take": request.take,
        "bound_reached": len(request.exact_expected_keys) == request.take,
        "summary_line_indexes": sorted(summary_lines),
        "truncation_claimed": truncation_claimed,
    }
    return required, excluded, [], ancestor_rows, coverage_summary, answer_order, tuple(failures)


def _ancestor_notes_present(line: str, notes: str | None) -> bool:
    cells = _markdown_row_cells(line)
    if cells is not None:
        note_cell = cells[-1].strip().strip("`").casefold()
        if isinstance(notes, str) and notes:
            return notes.casefold() in note_cell
        return note_cell in {
            "",
            "-",
            "—",
            "无",
            "无备注",
            "未设置",
            "none",
            "empty",
            "n/a",
            "null",
        }
    if isinstance(notes, str) and notes:
        return notes.casefold() in line.casefold()
    return re.search(
        r"(?:备注|notes?)\s*[:：]?\s*(?:无|无备注|未设置|none|empty|n/a|null|[-—])(?:\s|$)",
        line,
        re.IGNORECASE,
    ) is not None


def _markdown_row_cells(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if "|" not in stripped:
        return None
    cells = tuple(cell.strip() for cell in stripped.strip("|").split("|"))
    return cells if len(cells) >= 2 else None


def _ancestor_numeric_values(
    line: str,
    item: MaterializedObject,
) -> list[float]:
    numeric_source = line
    for token in (item.id, item.path, item.name, item.type, item.notes or ""):
        if token:
            numeric_source = numeric_source.replace(token, "")
    return [float(value) for value in _NUMBER_TOKEN_RE.findall(numeric_source)]


def _summary_type_count_lines(
    lines: Sequence[str],
    label: str,
    expected_count: int,
    *,
    excluded_line_indexes: set[int],
) -> tuple[int, ...]:
    indexes: list[int] = []
    aliases = {
        "RandomSequenceContainer": (
            "randomsequencecontainer",
            "random container",
        ),
        "ActorMixer": ("actormixer", "actor mixer"),
        "WorkUnit": ("workunit", "work unit"),
    }.get(label, (label.casefold(),))
    for index, line in enumerate(lines):
        if index in excluded_line_indexes:
            continue
        for clause in _ANSWER_CLAUSE_SPLIT_RE.split(line):
            folded_clause = clause.casefold()
            if label == "WorkUnit" and "default work unit" in folded_clause:
                continue
            if not any(alias in folded_clause for alias in aliases):
                continue
            numbers = {
                int(float(value)) for value in _NUMBER_TOKEN_RE.findall(clause)
            }
            if numbers and numbers != {expected_count}:
                return ()
            if numbers == {expected_count}:
                indexes.append(index)
                break
    return tuple(indexes)


def _claims_query_truncation(value: str) -> bool:
    negative = (
        "未截断",
        "没有截断",
        "并未截断",
        "未达到",
        "没有达到",
        "未触及",
        "not truncated",
        "did not reach",
        "not reach",
    )
    positive = (
        "截断",
        "触及上限",
        "达到上限",
        "上限已触及",
        "结果不完整",
        "truncated",
        "reached the limit",
        "incomplete",
    )
    for clause in _ANSWER_CLAUSE_SPLIT_RE.split(value):
        folded = clause.casefold()
        if any(token in folded for token in negative):
            continue
        if any(token in folded for token in positive):
            return True
    return False


def _claims_twelve_confirmed_sounds(value: str) -> bool:
    """Detect a positive 12-Sound coverage claim at clause granularity."""

    negated_confirmation = (
        "不等同于已确认",
        "不等于已确认",
        "不代表已确认",
        "不是已确认",
        "并非已确认",
        "不能视为已确认",
        "不能算作已确认",
        "not confirmed",
        "does not mean confirmed",
        "doesn't mean confirmed",
        "does not represent confirmed",
        "is not confirmed",
    )
    for clause in _ANSWER_CLAUSE_SPLIT_RE.split(value):
        folded = clause.casefold().strip()
        if not folded:
            continue
        numbers = {
            int(float(token)) for token in _NUMBER_TOKEN_RE.findall(clause)
        }
        if (
            12 not in numbers
            or "sound" not in folded
            or not any(
                token in folded
                for token in ("覆盖", "确认", "cover", "confirm")
            )
        ):
            continue
        if any(token in folded for token in negated_confirmation):
            continue
        return True
    return False


def _path_token_offsets(value: str, path: str) -> tuple[int, ...]:
    """Find exact Wwise object-path tokens, excluding descendant-prefix matches."""

    offsets: list[int] = []
    start = 0
    while True:
        index = value.find(path, start)
        if index < 0:
            break
        end = index + len(path)
        before = value[index - 1] if index else ""
        after = value[end] if end < len(value) else ""
        if before != "\\" and after != "\\":
            offsets.append(index)
        start = index + 1
    return tuple(offsets)


def _one_volume(item: MaterializedObject) -> float:
    values = [value.value for value in item.properties if value.name == "Volume"]
    if (
        len(values) != 1
        or isinstance(values[0], bool)
        or not isinstance(values[0], (int, float))
        or not math.isfinite(float(values[0]))
    ):
        raise ObjectRuntimeError(f"{item.key}: paired-answer Volume is not one finite number")
    return float(values[0])


def _output_bus_override(row: Mapping[str, Any]) -> bool | None:
    values = [
        row[field]
        for field in ("OverrideOutput", "@OverrideOutput")
        if field in row and row[field] is not None
    ]
    if not values:
        return None
    if any(type(value) is not bool for value in values):
        raise ObjectRuntimeError("OverrideOutput readback must be boolean or absent")
    if any(value != values[0] for value in values[1:]):
        raise ObjectRuntimeError("OverrideOutput readback aliases disagree")
    return values[0]


def _protected_intrinsic_projection(
    item: MaterializedObject,
    *,
    ignored_derived_fields: Sequence[str],
) -> dict[str, Any]:
    value = asdict(item)
    ignored = set(ignored_derived_fields)
    if ignored.intersection({"@Volume", "@Pitch"}):
        value["properties"] = [
            prop
            for prop in value["properties"]
            if f"@{prop.get('name')}" not in ignored
        ]
    if "OutputBus" in ignored:
        value["references"] = [
            reference
            for reference in value["references"]
            if reference.get("name") != "OutputBus"
        ]
    return value


def _protected_inherited_effective_fields(
    key: str,
    *,
    before: MaterializedObject,
    current: MaterializedObject,
    before_by_key: Mapping[str, MaterializedObject],
    resolved: Mapping[str, MaterializedObject],
    recipe: ObjectHeavyRecipe,
    before_override: bool | None,
    after_override: bool | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Bind only SET-03 effective readbacks to its reviewed direct parent.

    The protected child fixture has no local Volume/Pitch/OutputBus value.
    Wwise can nevertheless report those three effective values from the
    modified parent.  Excluding them is safe only when both sides match the
    exact sealed parent transition; every structural and other local field
    remains in the intrinsic projection.
    """

    if (
        recipe.scenario_id != "OBJ22-F-SET-03"
        or current.key != key
        or before.key != key
        or key not in recipe.oracle.protected_snapshot_keys
    ):
        return (), ()
    fixture_rows = [item for item in recipe.fixture.objects if item.key == key]
    if len(fixture_rows) != 1:
        raise ObjectRuntimeError(
            "inherited effective lookup requires one exact protected fixture"
        )
    fixture = fixture_rows[0]
    expected_by_key = {item.key: item for item in recipe.oracle.expected_objects}
    graph_by_id = {item.id: item for item in before_by_key.values()}
    graph_by_id.update({item.id: item for item in resolved.values()})
    parent = graph_by_id.get(current.parent_id or "")
    if (
        parent is None
        or before.parent_id != parent.id
        or fixture.parent_path != parent.path
    ):
        return (), ()
    expected = expected_by_key.get(parent.key)
    before_parent = before_by_key.get(parent.key)
    if expected is None or before_parent is None or before_parent.id != parent.id:
        return (), ()

    local_properties = {item.name for item in fixture.properties}
    local_references = {item.name for item in fixture.references}
    ignored: list[str] = []
    mismatches: list[str] = []
    for field_name, local_name in (
        ("@Volume", "Volume"),
        ("@Pitch", "Pitch"),
    ):
        fields = tuple(
            field
            for field in expected.fields
            if field.name == field_name and field.mode == "literal"
        )
        if len(fields) > 1:
            raise ObjectRuntimeError(
                f"{expected.key}: reviewed parent has duplicate {field_name} fields"
            )
        if not fields or local_name in local_properties:
            continue
        if (
            _materialized_field(before, field_name)
            == _materialized_field(before_parent, field_name)
            and _materialized_field(current, field_name) == fields[0].value
        ):
            ignored.append(field_name)
        # A non-matching readback is not proven to be inherited.  Keep it in
        # the intrinsic projection so an unchanged local/default value passes
        # while any actual child edit still fails the strict snapshot check.

    output_fields = tuple(
        field
        for field in expected.fields
        if field.name == "OutputBus" and field.mode == "object_key_id"
    )
    if len(output_fields) > 1:
        raise ObjectRuntimeError(
            f"{expected.key}: reviewed parent has duplicate OutputBus fields"
        )
    # Wwise 2022 may surface the parent's effective OverrideOutput value on a
    # child that the sealed fixture never authored locally.  Require the flag
    # itself to remain explicit and unchanged; the exact before/after bus must
    # still track the one reviewed parent transition below.
    if (
        output_fields
        and "OutputBus" not in local_references
        and type(before_override) is bool
        and after_override == before_override
    ):
        target_key = str(output_fields[0].value)
        target = resolved.get(target_key) or before_by_key.get(target_key)
        if target is None:
            raise ObjectRuntimeError(
                f"{expected.key}: reviewed inherited OutputBus target is unresolved"
            )
        if (
            _materialized_field(before, "OutputBus")
            != _materialized_field(before_parent, "OutputBus")
            or _materialized_field(current, "OutputBus") != target.id
        ):
            mismatches.append("OutputBus")
        else:
            ignored.append("OutputBus")
    return tuple(ignored), tuple(mismatches)


def _materialize(key: str, row: Mapping[str, Any]) -> MaterializedObject:
    object_id = _text(row.get("id"), "id")
    parent = row.get("parent")
    parent_id = _reference_id(parent)
    properties = tuple(
        ObjectProperty(name=name, value=row.get(f"@{name}"))
        for name in ("Volume", "Pitch")
        if f"@{name}" in row
    )
    references = tuple(
        [MaterializedReference("OutputBus", target)]
        if (target := _reference_id(row.get("OutputBus"))) is not None
        else []
    )
    return MaterializedObject(
        key=key,
        id=object_id,
        name=_text(row.get("name"), "name"),
        type=_text(row.get("type"), "type"),
        path=_path(row.get("path")),
        parent_id=parent_id,
        notes=str(row.get("notes")) if row.get("notes") is not None else None,
        properties=properties,
        references=references,
        source_language=_language_name(row.get("audioSource:language")),
        is_included=(bool(row.get("isIncluded")) if isinstance(row.get("isIncluded"), bool) else None),
        children_count=int(row.get("childrenCount") or 0),
    )


def _materialized_field(item: MaterializedObject, name: str) -> Any:
    if name in {"id", "name", "type", "path", "notes"}:
        return getattr(item, name)
    if name == "parent":
        return item.parent_id
    if name == "childrenCount":
        return item.children_count
    if name == "audioSource:language":
        return item.source_language
    if name == "isIncluded":
        return item.is_included
    if name.startswith("@"):
        lookup = {value.name: value.value for value in item.properties}
        return lookup.get(name[1:])
    lookup = {value.name: value.target_id for value in item.references}
    return lookup.get(name)


def _reference_id(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping):
        candidate = value.get("id")
        return str(candidate) if candidate else None
    return None


def _language_name(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value:
            return value
        raise ObjectRuntimeError("audio source language string must be non-empty")
    if not isinstance(value, Mapping):
        raise ObjectRuntimeError(
            "audio source language must be a string or reference object"
        )
    keys = ("name", "displayName", "shortName")
    candidates = [value[key] for key in keys if key in value]
    if not candidates or any(
        not isinstance(candidate, str) or not candidate
        for candidate in candidates
    ):
        raise ObjectRuntimeError(
            "audio source language reference must expose a non-empty name"
        )
    if len(set(candidates)) != 1:
        raise ObjectRuntimeError(
            "audio source language reference names are inconsistent"
        )
    return candidates[0]


def _rows(
    result: Any,
    context: str,
    *,
    key: str = "return",
) -> tuple[Mapping[str, Any], ...]:
    if key not in {"return", "objects"}:
        raise ObjectRuntimeError(f"{context} uses an unsupported result row key")
    if result is None:
        return ()
    if not isinstance(result, Mapping):
        raise ObjectRuntimeError(f"{context} result must be an object")
    rows = result.get(key)
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ObjectRuntimeError(f"{context} result.{key} must be an object array")
    if len(rows) > 256:
        raise ObjectRuntimeError(f"{context} exceeded the fixture row limit")
    return tuple(rows)


def _write_pcm_wav(path: Path, *, frequency_hz: int) -> None:
    """Write one small deterministic mono PCM fixture below the case asset root."""

    if not 100 <= frequency_hz <= 2_000:
        raise ObjectRuntimeError("fixture WAV frequency is outside the closed range")
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 48_000
    frame_count = sample_rate // 5
    amplitude = 8_000
    frames = bytearray()
    for index in range(frame_count):
        sample = int(amplitude * math.sin(2.0 * math.pi * frequency_hz * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    with path.open("xb") as raw:
        with wave.open(raw, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(bytes(frames))


def _fields(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(str(value) for value in values)
    if not result or len(result) != len(set(result)) or len(result) > 32:
        raise ObjectRuntimeError("object fixture return fields must be 1..32 unique values")
    return result


def _read_options(
    fields: Sequence[str],
    language: str | None,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "return": list(_fields(fields)),
        "platform": _FIXTURE_PLATFORM,
    }
    if language is not None:
        if language not in _FIXTURE_LANGUAGES:
            raise ObjectRuntimeError(f"fixture sound language is not closed: {language!r}")
        options["language"] = language
    return options


def _path(value: Any) -> str:
    text = _text(value, "path")
    if not text.startswith("\\") or "\\\\" in text:
        raise ObjectRuntimeError(f"invalid Wwise path: {text!r}")
    return text


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ObjectRuntimeError(f"{field} must be a non-empty string")
    return value


__all__ = [
    "OBJECT_RUNTIME_CONTRACT",
    "ClosedDirectObjectBackend",
    "ObjectRuntimeBackend",
    "ObjectRuntimeError",
    "ObjectRuntimeSnapshot",
    "ObjectRuntimeVerification",
    "PreparedObjectRuntime",
    "bounded_result_disclosure",
]
