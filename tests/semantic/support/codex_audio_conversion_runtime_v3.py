"""Trusted fixture and independent oracle for the five 2024 audio.convert cases.

The evaluated model receives only the natural reviewed prompt.  This module
owns deterministic WAVs, copied-project Conversion ShareSets, hidden object and
audio-source identities, baseline cache artifacts, and post-dispatch proofs.
It never starts Codex or Wwise; the outer V3 lifecycle supplies one fresh
already-running copied project and a closed direct-WAAPI call seam.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat as stat_module
import struct
import uuid
import wave
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from tests.destructive.support.sandbox_fixture import SandboxProject
from tests.semantic.support.codex_eval_bundle_v3 import OnlineScenario
from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_project_prelaunch_v3 import (
    ProjectPrelaunchRequest,
    normalize_project_copy,
)

try:  # ``pwd`` is unavailable on native Windows, where Wine mapping is unused.
    import pwd
except ImportError:  # pragma: no cover - native Windows skips Wine mapping
    pwd = None  # type: ignore[assignment]


AUDIO_CONVERT_URI = "ak.wwise.core.audio.convert"
AUDIO_CONVERSION_FIXTURE_CONTRACT = "waapi-skill.audio-conversion-fixture/v1"
AUDIO_CONVERSION_RUNTIME_CONTRACT = "waapi-skill.codex-audio-conversion-runtime/v3"
SUPPORTED_VERSION = "2024.1"
ACTOR_DWU = r"\Actor-Mixer Hierarchy\Default Work Unit"
CONVERSION_DWU = r"\Conversion Settings\Default Work Unit"
OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
_GUID_NAMESPACE = uuid.UUID("1a291d27-cc37-43cb-91d7-0b1311a385c1")
_PLUGINS = {
    "PCM": ("1", None),
    "ADPCM": ("2", None),
    "Vorbis": ("4", ("QualityFactor", "Real32", "3")),
}
_SUPPORTED_PLATFORMS = frozenset({"Windows", "Mac", "Android"})
_SUPPORTED_LANGUAGES = frozenset({"SFX", "English(US)", "Chinese(PRC)"})
_SUPPORTED_SAMPLE_RATES = frozenset({24_000, 44_100, 48_000})
_VOLATILE_CACHE_RELATIVE_PATHS = (
    "cache/CacheVersion",
    "cache/LMDB/data.mdb",
    "cache/LMDB/lock.mdb",
)
_MAX_VOLATILE_CACHE_FILE_BYTES = 16 * 1024 * 1024 * 1024
_SOUND_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "activeSource",
    "sound:convertedWemFilePath",
    "sound:originalWavFilePath",
    "Conversion",
)
_SOURCE_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "parent",
    "audioSource:language",
    "convertedFilePath",
    "originalFilePath",
    "originalRelativeFilePath",
)


class AudioConversionRuntimeError(RuntimeError):
    """The copied-project fixture or independent conversion oracle failed."""


DirectCall = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class ConversionPreset:
    """One reviewed platform-local component inside a Conversion ShareSet."""

    key: str
    name: str
    codec: str
    sample_rate: int
    channels: int


@dataclass(frozen=True, slots=True)
class ConversionProfile:
    """One real Wwise Conversion ShareSet with closed per-platform components."""

    key: str
    name: str
    components_by_platform: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ConversionBinding:
    path: str
    source_keys_by_language: tuple[tuple[str, str], ...]
    settings_by_platform: tuple[tuple[str, str], ...]
    control: bool

    def source_key(self, language: str) -> str:
        values = dict(self.source_keys_by_language)
        try:
            return values[language]
        except KeyError as exc:
            raise AudioConversionRuntimeError(
                f"{self.path} has no source binding for {language}"
            ) from exc


@dataclass(frozen=True, slots=True)
class SourceDelta:
    path: str
    source_key: str
    before_seed: str
    after_seed: str


@dataclass(frozen=True, slots=True)
class SettingDelta:
    path: str
    before_by_platform: tuple[tuple[str, str], ...]
    after_by_platform: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class AudioConversionPlan:
    scenario_id: str
    sandbox_project: Path
    sandbox_root: Path
    asset_root: Path
    io_root: Path
    objects: tuple[str, ...]
    platforms: tuple[str, ...]
    languages: tuple[str, ...]
    presets: tuple[ConversionPreset, ...]
    profiles: tuple[ConversionProfile, ...]
    bindings: tuple[ConversionBinding, ...]
    wav_filename_pattern: str
    source_seeds_by_key: tuple[tuple[str, str], ...]
    initial_settings_by_path: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    source_delta: SourceDelta | None
    setting_delta: SettingDelta | None
    missing_cache_paths: tuple[str, ...]
    operation_request: Mapping[str, Any]
    expected_output_count: int

    def source_seed(self, source_key: str) -> str:
        try:
            return dict(self.source_seeds_by_key)[source_key]
        except KeyError as exc:
            raise AudioConversionRuntimeError(
                f"no deterministic WAV seed is registered for {source_key!r}"
            ) from exc

    def initial_settings(self, path: str) -> tuple[tuple[str, str], ...]:
        try:
            return dict(self.initial_settings_by_path)[path]
        except KeyError as exc:
            raise AudioConversionRuntimeError(
                f"no baseline Conversion assignment is registered for {path}"
            ) from exc

    def profile_for_settings(
        self,
        settings_by_platform: Sequence[tuple[str, str]],
    ) -> ConversionProfile:
        normalized = tuple(settings_by_platform)
        matches = tuple(
            profile
            for profile in self.profiles
            if profile.components_by_platform == normalized
        )
        if len(matches) != 1:
            raise AudioConversionRuntimeError(
                "effective component map does not resolve to exactly one Conversion profile"
            )
        return matches[0]


@dataclass(frozen=True, slots=True)
class FileState:
    path: str
    present: bool
    size: int | None
    sha256: str | None
    mtime_ns: int | None


@dataclass(frozen=True, slots=True)
class VolatileFileState:
    """Bounded metadata for exact Wwise cache-infrastructure files.

    LMDB may mutate while it is being observed, so these records deliberately
    contain neither content hashes nor timestamps and are excluded from the
    immutable preview digest.
    """

    path: str
    present: bool
    size: int | None


@dataclass(frozen=True, slots=True)
class ConvertedArtifact:
    object_path: str
    object_id: str
    source_id: str
    source_key: str
    platform: str
    language: str
    conversion_id: str
    conversion_name: str
    original_path: str
    original_file: FileState
    converted_path: str
    file: FileState
    codec: str | None
    sample_rate: int | None

    @property
    def slot(self) -> tuple[str, str, str]:
        return (self.object_path, self.platform, self.language)


@dataclass(frozen=True, slots=True)
class AudioConversionSnapshot:
    artifacts: tuple[ConvertedArtifact, ...]
    baseline_artifacts: tuple[ConvertedArtifact, ...]
    input_files: tuple[FileState, ...]
    originals_files: tuple[FileState, ...]
    authoring_files: tuple[FileState, ...]
    conversion_xml: FileState
    output_tree: tuple[FileState, ...]
    baseline_artifact_paths: tuple[str, ...]
    volatile_cache_files: tuple[VolatileFileState, ...]
    digest: str

    def by_slot(self) -> dict[tuple[str, str, str], ConvertedArtifact]:
        return {item.slot: item for item in self.artifacts}


@dataclass(frozen=True, slots=True)
class AudioConversionVerification:
    phase: str
    passed: bool
    failures: tuple[str, ...]
    evidence: Mapping[str, Any]

    def assert_passed(self) -> None:
        if not self.passed:
            raise AudioConversionRuntimeError(
                f"{self.phase} failed: {'; '.join(self.failures)}"
            )


class AudioConversionBackend(Protocol):
    def read_path(
        self,
        path: str,
        *,
        fields: Sequence[str],
        platform: str | None = None,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]: ...

    def read_id(
        self,
        object_id: str,
        *,
        fields: Sequence[str],
        platform: str | None = None,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]: ...

    def create_parent(self, *, parent: str, name: str) -> str: ...

    def import_sound(
        self,
        *,
        parent: str,
        name: str,
        language: str,
        audio_file: Path,
        originals_subfolder: str,
    ) -> None: ...

    def set_property(
        self,
        object_id: str,
        name: str,
        value: Any,
        *,
        platform: str | None = None,
    ) -> None: ...

    def set_reference(
        self,
        object_id: str,
        name: str,
        target_id: str,
    ) -> None: ...

    def convert(
        self,
        *,
        objects: Sequence[str],
        platforms: Sequence[str],
        languages: Sequence[str],
    ) -> Mapping[str, Any]: ...

    def save(self) -> None: ...


class ClosedAudioConversionBackend:
    """Closed direct-WAAPI setup/readback seam; no generic method is public."""

    def __init__(self, call: DirectCall) -> None:
        if not callable(call):
            raise TypeError("call must be callable")
        self._call = call

    def read_path(
        self,
        path: str,
        *,
        fields: Sequence[str],
        platform: str | None = None,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {"path": [_wwise_path(path)]},
            fields=fields,
            platform=platform,
            language=language,
        )

    def read_id(
        self,
        object_id: str,
        *,
        fields: Sequence[str],
        platform: str | None = None,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {"id": [_text(object_id, "object_id")]},
            fields=fields,
            platform=platform,
            language=language,
        )

    def _read(
        self,
        source: Mapping[str, Any],
        *,
        fields: Sequence[str],
        platform: str | None,
        language: str | None,
    ) -> tuple[Mapping[str, Any], ...]:
        options: dict[str, Any] = {"return": list(_fields(fields))}
        if platform is not None:
            options["platform"] = _text(platform, "platform")
        if language is not None:
            options["language"] = _text(language, "language")
        result = self._call("ak.wwise.core.object.get", {"from": dict(source)}, options)
        return _rows(result, "object.get")

    def create_parent(self, *, parent: str, name: str) -> str:
        result = self._call(
            "ak.wwise.core.object.create",
            {
                "parent": _wwise_path(parent),
                "type": "ActorMixer",
                "name": _text(name, "name"),
                "onNameConflict": "fail",
            },
            {},
        )
        if not isinstance(result, Mapping):
            raise AudioConversionRuntimeError("object.create result must be an object")
        return _text(result.get("id"), "created parent id")

    def import_sound(
        self,
        *,
        parent: str,
        name: str,
        language: str,
        audio_file: Path,
        originals_subfolder: str,
    ) -> None:
        source = _file_state(audio_file)
        if not source.present or source.size is None or source.size <= 44:
            raise AudioConversionRuntimeError("conversion source WAV is invalid")
        object_type = "Sound SFX" if language == "SFX" else "Sound Voice"
        result = self._call(
            "ak.wwise.core.audio.import",
            {
                "importOperation": "useExisting",
                "imports": [
                    {
                        "audioFile": source.path,
                        "objectPath": f"{_wwise_path(parent)}\\<{object_type}>{_text(name, 'name')}",
                        "objectType": object_type,
                        "importLanguage": _text(language, "language"),
                        "originalsSubFolder": _safe_originals_subfolder(
                            originals_subfolder
                        ),
                    }
                ],
                "autoAddToSourceControl": False,
                "autoCheckOutToSourceControl": False,
            },
            {"return": ["id", "path", "activeSource", "audioSource:language"]},
        )
        if not isinstance(result, Mapping):
            raise AudioConversionRuntimeError("audio.import setup result must be an object")

    def set_property(
        self,
        object_id: str,
        name: str,
        value: Any,
        *,
        platform: str | None = None,
    ) -> None:
        args: dict[str, Any] = {
            "object": _text(object_id, "object_id"),
            "property": _text(name, "property"),
            "value": value,
        }
        if platform is not None:
            args["platform"] = _text(platform, "platform")
        _assert_empty_result(
            self._call("ak.wwise.core.object.setProperty", args, {}),
            "object.setProperty",
        )

    def set_reference(
        self,
        object_id: str,
        name: str,
        target_id: str,
    ) -> None:
        _assert_empty_result(
            self._call(
                "ak.wwise.core.object.setReference",
                {
                    "object": _text(object_id, "object_id"),
                    "reference": _text(name, "reference"),
                    "value": _text(target_id, "target_id"),
                },
                {},
            ),
            "object.setReference",
        )

    def convert(
        self,
        *,
        objects: Sequence[str],
        platforms: Sequence[str],
        languages: Sequence[str],
    ) -> Mapping[str, Any]:
        result = self._call(
            AUDIO_CONVERT_URI,
            {
                "objects": [_wwise_path(value) for value in objects],
                "platforms": [_text(value, "platform") for value in platforms],
                "languages": [_text(value, "language") for value in languages],
            },
            {},
        )
        if not isinstance(result, Mapping):
            raise AudioConversionRuntimeError("audio.convert result must be an object")
        _assert_no_conversion_errors(result, context="fixture baseline")
        return dict(result)

    def save(self) -> None:
        result = self._call("ak.wwise.core.project.save", {}, {})
        _assert_empty_result(result, "project.save")


class PreparedAudioConversionRuntime:
    """One single-use materialized 2024 conversion scenario."""

    def __init__(
        self,
        *,
        scenario: OnlineScenario,
        plan: AudioConversionPlan,
        backend: AudioConversionBackend,
    ) -> None:
        if scenario.id != plan.scenario_id or scenario.api != AUDIO_CONVERT_URI:
            raise AudioConversionRuntimeError("scenario and conversion plan do not match")
        self.scenario = scenario
        self.plan = plan
        self.backend = backend
        self.before: AudioConversionSnapshot | None = None
        self._baseline: dict[tuple[str, str, str], ConvertedArtifact] = {}
        self._profile_ids: dict[str, str] = {}

    def render_prompt(self) -> str:
        return self.scenario.render_prompt({"io_root": str(self.plan.io_root)})

    def gateway_protocol(self) -> V3GatewayProtocol:
        return build_transaction_protocol([self.plan.operation_request])

    def prepare(self) -> "PreparedAudioConversionRuntime":
        if self.before is not None:
            raise AudioConversionRuntimeError("audio conversion runtime is single-use")
        if len(self.backend.read_path(ACTOR_DWU, fields=("id", "path"))) != 1:
            raise AudioConversionRuntimeError("Actor-Mixer Default Work Unit is unavailable")
        profile_ids = self._resolve_profiles()
        self._profile_ids = dict(profile_ids)
        bindings = {item.path: item for item in self.plan.bindings}

        for path in sorted(bindings, key=lambda value: (value.count("\\"), value)):
            self._ensure_parents(path.rsplit("\\", 1)[0])
            binding = bindings[path]
            for language, source_key in binding.source_keys_by_language:
                source = _source_asset_path(self.plan, language, source_key)
                _write_pcm_wav(source, seed=self.plan.source_seed(source_key))
                self.backend.import_sound(
                    parent=path.rsplit("\\", 1)[0],
                    name=path.rsplit("\\", 1)[1],
                    language=language,
                    audio_file=source,
                    originals_subfolder=_source_originals_subfolder(
                        self.plan, source_key
                    ),
                )
            sound_rows = self.backend.read_path(path, fields=("id", "path", "type"))
            if len(sound_rows) != 1:
                raise AudioConversionRuntimeError(f"fixture Sound did not resolve once: {path}")
            sound_id = _text(sound_rows[0].get("id"), "Sound id")
            self.backend.set_property(sound_id, "OverrideConversion", True)
            settings = dict(self.plan.initial_settings(path))
            if set(settings) != set(self.plan.platforms):
                raise AudioConversionRuntimeError(
                    f"{path} lacks a closed effective setting map"
                )
            profile = self.plan.profile_for_settings(tuple(settings.items()))
            self.backend.set_reference(
                sound_id,
                "Conversion",
                profile_ids[profile.key],
            )

        self.backend.save()
        baseline_objects = tuple(item.path for item in self.plan.bindings)
        self.backend.convert(
            objects=baseline_objects,
            platforms=self.plan.platforms,
            languages=self.plan.languages,
        )
        baseline = self._collect_artifacts(require_files=True)
        # Validate the complete physical cache matrix before applying any stale
        # or missing-cache delta.  In particular, do not partially delete a
        # shared alias and discover the platform-linking error on the second
        # slot: that leaves a misleading half-materialized fixture.
        _assert_identity_matrix(baseline, self.plan, initial=True)
        _assert_effective_setting_matrix(
            baseline,
            self.plan,
            profile_ids,
            initial=True,
            require_matching_file_format=True,
        )
        self._baseline = {item.slot: item for item in baseline}

        if self.plan.scenario_id == "VS24-F-AUDIO-CONVERT-04":
            self._apply_case04_deltas(profile_ids)
        else:
            target_paths = {
                artifact.converted_path
                for artifact in baseline
                if not bindings[artifact.object_path].control
            }
            for path in sorted(target_paths):
                _unlink_owned_file(Path(path), self.plan.io_root)

        before = self.snapshot()
        target_slots = {
            (path, platform, language)
            for path in self.plan.objects
            for platform in self.plan.platforms
            for language in self.plan.languages
        }
        if len(target_slots) != self.plan.expected_output_count:
            raise AudioConversionRuntimeError("target slot count differs from reviewed output count")
        before_slots = before.by_slot()
        if set(before_slots) != {
            (binding.path, platform, language)
            for binding in self.plan.bindings
            for platform in self.plan.platforms
            for language, _source in binding.source_keys_by_language
            if language in self.plan.languages
        }:
            raise AudioConversionRuntimeError("before snapshot did not close every artifact slot")
        self._validate_before_matrix(before, target_slots)
        self.before = before
        return self

    def snapshot(self) -> AudioConversionSnapshot:
        artifacts = self._collect_artifacts(require_files=False)
        baseline_artifacts = tuple(
            sorted(self._baseline.values(), key=lambda item: item.slot)
        )
        input_files = _tree_files(self.plan.asset_root / "sources")
        originals = _tree_files(self.plan.sandbox_root, predicate=_is_originals_file)
        authoring_files = _tree_files(
            self.plan.sandbox_root,
            predicate=_is_authoring_project_file,
        )
        conversion_xml = _file_state(_conversion_workunit(self.plan.sandbox_project))
        volatile_paths = set(audio_conversion_volatile_cache_paths(self.plan.io_root))
        output_tree = _tree_files(
            self.plan.io_root,
            predicate=lambda path: str(path.resolve(strict=False))
            not in volatile_paths,
        )
        volatile_cache_files = tuple(
            _volatile_file_state(Path(path), root=self.plan.io_root)
            for path in sorted(volatile_paths)
        )
        baseline_artifact_paths = tuple(
            sorted({item.converted_path for item in self._baseline.values()})
        )
        payload = {
            "artifacts": [asdict(item) for item in artifacts],
            "baseline_artifacts": [asdict(item) for item in baseline_artifacts],
            "inputs": [asdict(item) for item in input_files],
            "originals": [asdict(item) for item in originals],
            "authoring_files": [asdict(item) for item in authoring_files],
            "conversion_xml": asdict(conversion_xml),
            "output_tree": [asdict(item) for item in output_tree],
            "baseline_artifact_paths": list(baseline_artifact_paths),
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        return AudioConversionSnapshot(
            artifacts=artifacts,
            baseline_artifacts=baseline_artifacts,
            input_files=input_files,
            originals_files=originals,
            authoring_files=authoring_files,
            conversion_xml=conversion_xml,
            output_tree=output_tree,
            baseline_artifact_paths=baseline_artifact_paths,
            volatile_cache_files=volatile_cache_files,
            digest=digest,
        )

    def verify_preview_unchanged(self) -> AudioConversionVerification:
        before = self._before()
        after = self.snapshot()
        failures = () if before.digest == after.digest else ("conversion fixture changed before confirmation",)
        return AudioConversionVerification(
            "preview",
            not failures,
            failures,
            {"before": before.digest, "after": after.digest},
        )

    def verify_after_execution(
        self,
        *,
        verify_payload: Mapping[str, Any] | None = None,
    ) -> AudioConversionVerification:
        before = self._before()
        after = self.snapshot()
        failures: list[str] = []
        before_slots = before.by_slot()
        after_slots = after.by_slot()
        target_slots = {
            (path, platform, language)
            for path in self.plan.objects
            for platform in self.plan.platforms
            for language in self.plan.languages
        }
        if len(target_slots) != self.plan.expected_output_count:
            failures.append("reviewed target slot count drifted")
        if set(before_slots) != set(after_slots):
            failures.append("artifact slot matrix changed during tested dispatch")
        expected_baseline_paths = tuple(
            sorted({item.converted_path for item in self._baseline.values()})
        )
        expected_baseline_artifacts = tuple(
            sorted(self._baseline.values(), key=lambda item: item.slot)
        )
        if (
            before.baseline_artifact_paths != expected_baseline_paths
            or after.baseline_artifact_paths != expected_baseline_paths
            or before.baseline_artifacts != expected_baseline_artifacts
            or after.baseline_artifacts != expected_baseline_artifacts
        ):
            failures.append("sealed baseline artifact evidence changed during tested dispatch")
        for label, snapshot in (("before", before), ("after", after)):
            try:
                _assert_volatile_cache_layer(snapshot, self.plan)
            except AudioConversionRuntimeError as exc:
                failures.append(f"{label} {exc}")
        try:
            _assert_identity_matrix(after.artifacts, self.plan, initial=False)
        except AudioConversionRuntimeError as exc:
            failures.append(str(exc))
        preset_by_key = {item.key: item for item in self.plan.presets}
        binding_by_path = {item.path: item for item in self.plan.bindings}
        replacement_paths = {
            row.path
            for row in (self.plan.source_delta, self.plan.setting_delta)
            if row is not None
        }
        observed_paths: dict[str, tuple[str, str, str]] = {}
        observed_hashes: set[str] = set()
        for slot in sorted(target_slots):
            current = after_slots.get(slot)
            previous = before_slots.get(slot)
            baseline = self._baseline.get(slot)
            if current is None or previous is None or baseline is None:
                failures.append(f"target slot is unresolved: {slot}")
                continue
            if (current.object_id, current.source_id) != (previous.object_id, previous.source_id):
                failures.append(f"target identity changed: {slot}")
            if (
                current.original_path,
                current.original_file,
            ) != (
                previous.original_path,
                previous.original_file,
            ):
                failures.append(f"target Original WAV binding changed: {slot}")
            if current.file.path != current.converted_path:
                failures.append(f"target converted path/file binding differs: {slot}")
            try:
                normalized_converted_path = _owned_file_path(
                    Path(current.converted_path),
                    self.plan.io_root,
                    field="converted target readback",
                    require_exists=False,
                )
                if str(normalized_converted_path) != current.converted_path:
                    failures.append(f"target converted path is not normalized: {slot}")
            except AudioConversionRuntimeError as exc:
                failures.append(f"target converted path is outside the owned I/O root: {slot}: {exc}")
            if not current.file.present or not current.file.size or not current.file.sha256:
                failures.append(f"target converted file is absent or empty: {slot}")
                continue
            previous_slot = observed_paths.get(current.converted_path)
            if previous_slot is not None and _cache_alias_is_forbidden(
                self.plan,
                previous_slot,
                slot,
                initial=False,
            ):
                failures.append(
                    "converted path is reused across target slots whose reviewed "
                    f"effective formats differ: {current.converted_path}"
                )
            observed_paths.setdefault(current.converted_path, slot)
            if self.plan.scenario_id == "VS24-F-AUDIO-CONVERT-05":
                if current.file.sha256 in observed_hashes:
                    failures.append(f"same-basename target hash was reused: {slot}")
                observed_hashes.add(current.file.sha256)
            if (
                baseline.file.mtime_ns is None
                or current.file.mtime_ns is None
            ):
                failures.append(f"target freshness timestamps are unavailable: {slot}")
            elif current.file.mtime_ns <= baseline.file.mtime_ns:
                failures.append(f"target was not freshly converted after preview: {slot}")
            if (
                slot[0] in replacement_paths
                and baseline.file.present
                and current.file.sha256 == baseline.file.sha256
            ):
                failures.append(
                    f"target bytes equal the sealed pre-delta baseline: {slot}"
                )
            setting_key = dict(binding_by_path[slot[0]].settings_by_platform)[slot[1]]
            expected_setting = preset_by_key[setting_key]
            expected_profile = self.plan.profile_for_settings(
                binding_by_path[slot[0]].settings_by_platform
            )
            if current.conversion_name != expected_profile.name:
                failures.append(f"effective Conversion reference differs: {slot}")
            expected_conversion_id = self._profile_ids.get(expected_profile.key)
            if not expected_conversion_id or current.conversion_id != expected_conversion_id:
                failures.append(f"effective Conversion identity differs: {slot}")
            if current.codec != expected_setting.codec:
                failures.append(
                    f"codec mismatch for {slot}: {current.codec!r} != {expected_setting.codec!r}"
                )
            if current.sample_rate != expected_setting.sample_rate:
                failures.append(
                    f"sample-rate mismatch for {slot}: {current.sample_rate!r} != {expected_setting.sample_rate!r}"
                )

        for slot, previous in before_slots.items():
            if slot in target_slots:
                continue
            current = after_slots.get(slot)
            if current != previous:
                failures.append(f"non-requested control artifact changed: {slot}")
        if before.input_files != after.input_files:
            failures.append("runner-owned source WAV inputs changed during tested dispatch")
        if before.originals_files != after.originals_files:
            failures.append("project Originals changed during tested dispatch")
        if before.authoring_files != after.authoring_files:
            failures.append("project authoring files changed during tested dispatch")
        if before.conversion_xml != after.conversion_xml:
            failures.append("conversion-setting Work Unit changed during tested dispatch")
        before_target_paths = {
            artifact.converted_path
            for slot, artifact in before_slots.items()
            if slot in target_slots
        }
        after_target_paths = {
            artifact.converted_path
            for slot, artifact in after_slots.items()
            if slot in target_slots
        }
        before_non_target_paths = {
            item.path for item in before.output_tree
            if item.path not in before_target_paths
        }
        if (after_target_paths - before_target_paths) & before_non_target_paths:
            failures.append(
                "new target converted path collides with pre-existing non-target output"
            )
        target_paths = before_target_paths | after_target_paths
        if _without_file_paths(before.output_tree, target_paths) != _without_file_paths(
            after.output_tree, target_paths
        ):
            failures.append("non-requested conversion output tree changed")
        before_volatile_by_path = {
            item.path: item for item in before.volatile_cache_files
        }
        after_volatile_by_path = {
            item.path: item for item in after.volatile_cache_files
        }
        volatile_changed_paths = [
            path
            for path in sorted(
                set(before_volatile_by_path) | set(after_volatile_by_path)
            )
            if before_volatile_by_path.get(path) != after_volatile_by_path.get(path)
        ]
        if verify_payload is None:
            failures.append("tested transaction verify payload was not supplied")
            verify_request: Any = None
        else:
            try:
                conversion_result = _tested_conversion_result(
                    verify_payload,
                    expected_request=self.plan.operation_request,
                )
                agent_result = verify_payload.get("agent_result")
                verify_request = (
                    agent_result.get("request")
                    if isinstance(agent_result, Mapping)
                    else None
                )
                _assert_no_conversion_errors(
                    conversion_result,
                    context="tested transaction",
                )
            except AudioConversionRuntimeError as exc:
                failures.append(str(exc))
                verify_request = None
        return AudioConversionVerification(
            "after",
            not failures,
            tuple(failures),
            {
                "before": asdict(before),
                "after": asdict(after),
                "target_slots": len(target_slots),
                "observed_target_paths": sorted(observed_paths),
                "after_digest": after.digest,
                "volatile_cache_files_before": [
                    asdict(item) for item in before.volatile_cache_files
                ],
                "volatile_cache_files_after": [
                    asdict(item) for item in after.volatile_cache_files
                ],
                "volatile_cache_changed_paths": volatile_changed_paths,
                "byte_change_required_paths": sorted(replacement_paths),
                "operation_request": _json_clone(self.plan.operation_request),
                "operation_request_sha256": _json_sha256(
                    self.plan.operation_request
                ),
                "verify_request_sha256": (
                    _json_sha256(verify_request)
                    if verify_request is not None
                    else ""
                ),
                "verify_payload_sha256": (
                    _json_sha256(verify_payload)
                    if verify_payload is not None
                    else ""
                ),
            },
        )

    def _resolve_profiles(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for profile in self.plan.profiles:
            path = f"{CONVERSION_DWU}\\{profile.name}"
            rows = self.backend.read_path(path, fields=("id", "name", "type", "path"))
            if len(rows) != 1 or rows[0].get("type") != "Conversion":
                raise AudioConversionRuntimeError(f"conversion profile did not load exactly: {path}")
            result[profile.key] = _text(rows[0].get("id"), "Conversion id")
        return result

    def _ensure_parents(self, parent_path: str) -> None:
        if parent_path == ACTOR_DWU:
            return
        current = ACTOR_DWU
        relative = parent_path[len(ACTOR_DWU) :].strip("\\")
        if not relative or not parent_path.startswith(ACTOR_DWU + "\\"):
            raise AudioConversionRuntimeError(f"fixture parent escapes Default Work Unit: {parent_path}")
        for name in relative.split("\\"):
            candidate = f"{current}\\{name}"
            rows = self.backend.read_path(candidate, fields=("id", "type", "path"))
            if not rows:
                self.backend.create_parent(parent=current, name=name)
                rows = self.backend.read_path(candidate, fields=("id", "type", "path"))
            if len(rows) != 1 or rows[0].get("type") != "ActorMixer":
                raise AudioConversionRuntimeError(f"fixture parent is not one ActorMixer: {candidate}")
            current = candidate

    def _collect_artifacts(self, *, require_files: bool) -> tuple[ConvertedArtifact, ...]:
        profiles_by_name = {item.name: item for item in self.plan.profiles}
        rows: list[ConvertedArtifact] = []
        for binding in self.plan.bindings:
            for language, source_key in binding.source_keys_by_language:
                if language not in self.plan.languages:
                    continue
                for platform in self.plan.platforms:
                    sound_rows = self.backend.read_path(
                        binding.path,
                        fields=_SOUND_FIELDS,
                        platform=platform,
                        language=language,
                    )
                    if len(sound_rows) != 1:
                        raise AudioConversionRuntimeError(
                            f"Sound slot did not resolve once: {(binding.path, platform, language)}"
                        )
                    sound = sound_rows[0]
                    source_id = _reference_id(sound.get("activeSource"))
                    conversion_id = _reference_id(sound.get("Conversion"))
                    conversion_name = _reference_name(sound.get("Conversion"))
                    if source_id is None or conversion_id is None or conversion_name is None:
                        raise AudioConversionRuntimeError(
                            f"Sound slot lacks source/conversion identity: {(binding.path, platform, language)}"
                        )
                    source_rows = self.backend.read_id(
                        source_id,
                        fields=_SOURCE_FIELDS,
                        platform=platform,
                        language=language,
                    )
                    if len(source_rows) != 1:
                        raise AudioConversionRuntimeError(f"Audio Source did not resolve once: {source_id}")
                    source = source_rows[0]
                    reflected_language = _reference_name(source.get("audioSource:language")) or source.get(
                        "audioSource:language"
                    )
                    if str(reflected_language) != language:
                        raise AudioConversionRuntimeError(
                            f"Audio Source language differs: {reflected_language!r} != {language!r}"
                        )
                    original = source.get("originalFilePath") or sound.get(
                        "sound:originalWavFilePath"
                    )
                    if not isinstance(original, str) or not original:
                        raise AudioConversionRuntimeError(
                            f"original path is unavailable for {(binding.path, language)}"
                        )
                    original_relative = source.get("originalRelativeFilePath")
                    if not isinstance(original_relative, str) or not original_relative:
                        raise AudioConversionRuntimeError(
                            "originalRelativeFilePath is unavailable for "
                            f"{(binding.path, language)}"
                        )
                    original_path = _resolve_project_original_path(
                        self.plan,
                        language=language,
                        source_key=source_key,
                        original_file_path=original,
                        original_relative_file_path=original_relative,
                    )
                    original_state = _file_state(original_path)
                    staged_state = _file_state(
                        _source_asset_path(self.plan, language, source_key)
                    )
                    if (
                        not staged_state.present
                        or original_state.sha256 != staged_state.sha256
                    ):
                        raise AudioConversionRuntimeError(
                            f"project Original does not match staged source {source_key!r}"
                        )
                    converted = source.get("convertedFilePath") or sound.get(
                        "sound:convertedWemFilePath"
                    )
                    if not isinstance(converted, str) or not converted:
                        baseline = self._baseline.get((binding.path, platform, language))
                        converted = baseline.converted_path if baseline is not None else ""
                    if not converted:
                        raise AudioConversionRuntimeError(
                            f"converted path is unavailable for {(binding.path, platform, language)}"
                        )
                    converted_path = _owned_waapi_host_file_path(
                        converted,
                        self.plan.io_root,
                        field="converted media",
                        require_exists=False,
                    )
                    file_state = _file_state(converted_path)
                    if require_files and (not file_state.present or not file_state.size):
                        raise AudioConversionRuntimeError(f"baseline conversion artifact is missing: {converted}")
                    codec, sample_rate = (
                        _parse_wem(converted_path) if file_state.present else (None, None)
                    )
                    if conversion_name not in profiles_by_name:
                        raise AudioConversionRuntimeError(
                            f"slot references an unreviewed Conversion profile: {conversion_name}"
                        )
                    rows.append(
                        ConvertedArtifact(
                            object_path=binding.path,
                            object_id=_text(sound.get("id"), "Sound id"),
                            source_id=source_id,
                            source_key=source_key,
                            platform=platform,
                            language=language,
                            conversion_id=conversion_id,
                            conversion_name=conversion_name,
                            original_path=str(original_path),
                            original_file=original_state,
                            converted_path=str(converted_path),
                            file=file_state,
                            codec=codec,
                            sample_rate=sample_rate,
                        )
                    )
        result = tuple(sorted(rows, key=lambda item: item.slot))
        if len({item.slot for item in result}) != len(result):
            raise AudioConversionRuntimeError("conversion snapshot contains duplicate slots")
        return result

    def _apply_case04_deltas(self, profile_ids: Mapping[str, str]) -> None:
        source_delta = self.plan.source_delta
        setting_delta = self.plan.setting_delta
        if source_delta is None or setting_delta is None or not self.plan.missing_cache_paths:
            raise AudioConversionRuntimeError("case04 lacks its closed reviewed delta plan")
        changed_source = next(
            item for item in self.plan.bindings if item.path == source_delta.path
        )
        language, source_key = changed_source.source_keys_by_language[0]
        if source_key != source_delta.source_key:
            raise AudioConversionRuntimeError("source-delta binding drifted after planning")
        replacement = _source_asset_path(self.plan, language, source_key)
        _replace_pcm_wav_owned(
            replacement,
            root=self.plan.asset_root,
            seed=source_delta.after_seed,
        )
        self.backend.import_sound(
            parent=changed_source.path.rsplit("\\", 1)[0],
            name=changed_source.path.rsplit("\\", 1)[1],
            language=language,
            audio_file=replacement,
            originals_subfolder=_source_originals_subfolder(
                self.plan, source_key
            ),
        )
        changed_setting = next(
            item for item in self.plan.bindings if item.path == setting_delta.path
        )
        sound_rows = self.backend.read_path(changed_setting.path, fields=("id", "path"))
        if len(sound_rows) != 1:
            raise AudioConversionRuntimeError("Changed_Setting Sound disappeared during delta setup")
        sound_id = _text(sound_rows[0].get("id"), "Changed_Setting id")
        profile = self.plan.profile_for_settings(setting_delta.after_by_platform)
        self.backend.set_reference(
            sound_id,
            "Conversion",
            profile_ids[profile.key],
        )
        self.backend.save()
        missing_paths = {
            artifact.converted_path
            for slot, artifact in self._baseline.items()
            if slot[0] in self.plan.missing_cache_paths
        }
        for path in sorted(missing_paths):
            _unlink_owned_file(Path(path), self.plan.io_root)

    def _validate_before_matrix(
        self,
        before: AudioConversionSnapshot,
        target_slots: set[tuple[str, str, str]],
    ) -> None:
        _assert_volatile_cache_layer(before, self.plan)
        baseline = tuple(sorted(self._baseline.values(), key=lambda item: item.slot))
        expected_baseline_paths = tuple(
            sorted({item.converted_path for item in baseline})
        )
        if before.baseline_artifacts != baseline:
            raise AudioConversionRuntimeError(
                "before snapshot baseline artifact evidence drifted"
            )
        if before.baseline_artifact_paths != expected_baseline_paths:
            raise AudioConversionRuntimeError(
                "before snapshot baseline artifact path seal drifted"
            )
        baseline_files = {item.converted_path: item.file for item in baseline}
        if len(baseline_files) != len(expected_baseline_paths):
            raise AudioConversionRuntimeError(
                "baseline artifact paths alias distinct conversion slots"
            )
        output_files = {item.path: item for item in before.output_tree}
        if len(output_files) != len(before.output_tree):
            raise AudioConversionRuntimeError(
                "before snapshot stable output paths are duplicated"
            )
        if not set(output_files) <= set(expected_baseline_paths):
            raise AudioConversionRuntimeError(
                "before snapshot contains stable output not explained by baseline artifact readback"
            )
        if any(output_files[path] != baseline_files[path] for path in output_files):
            raise AudioConversionRuntimeError(
                "before snapshot changed a retained baseline artifact"
            )
        retained_objects = {item.path for item in self.plan.bindings if item.control}
        if self.plan.source_delta is not None:
            retained_objects.add(self.plan.source_delta.path)
        if self.plan.setting_delta is not None:
            retained_objects.add(self.plan.setting_delta.path)
        expected_retained = {
            item.converted_path
            for item in baseline
            if item.object_path in retained_objects
        }
        if set(output_files) != expected_retained:
            raise AudioConversionRuntimeError(
                "before snapshot retained baseline artifact set differs from the reviewed delta"
            )
        slots = before.by_slot()
        _assert_identity_matrix(before.artifacts, self.plan, initial=False)
        _assert_effective_setting_matrix(
            before.artifacts,
            self.plan,
            self._profile_ids,
            initial=False,
            require_matching_file_format=False,
        )
        source_files = tuple(item for item in before.input_files if item.present)
        expected_source_count = len({
            (language, source_key)
            for binding in self.plan.bindings
            for language, source_key in binding.source_keys_by_language
        })
        if len(source_files) != expected_source_count:
            raise AudioConversionRuntimeError(
                "before snapshot does not contain exactly one runner WAV per source binding"
            )
        source_hashes = [item.sha256 for item in source_files]
        if None in source_hashes or len(source_hashes) != len(set(source_hashes)):
            raise AudioConversionRuntimeError("deterministic source WAV proofs are not distinct")
        # Wwise 2024 invalidates the current converted-path identity both when
        # ``audio.import(useExisting)`` replaces source bytes and when a Sound
        # changes Conversion ShareSet.  The old physical WEMs remain sealed in
        # ``baseline_artifacts``/``output_tree``; every requested current slot
        # is therefore absent until the evaluated conversion creates it.
        for slot, artifact in slots.items():
            if slot not in target_slots:
                if not artifact.file.present:
                    raise AudioConversionRuntimeError(
                        f"control artifact is absent before preview: {slot}"
                    )
                continue
            if artifact.file.present:
                raise AudioConversionRuntimeError(
                    f"target artifact must be absent before preview: {slot}"
                )
            baseline_artifact = self._baseline.get(slot)
            if baseline_artifact is None:
                raise AudioConversionRuntimeError(
                    f"target slot lacks sealed baseline evidence: {slot}"
                )
            if (
                self.plan.scenario_id == "VS24-F-AUDIO-CONVERT-04"
                and slot[0]
                in {
                    self.plan.source_delta.path if self.plan.source_delta else "",
                    self.plan.setting_delta.path if self.plan.setting_delta else "",
                }
                and artifact.converted_path == baseline_artifact.converted_path
            ):
                raise AudioConversionRuntimeError(
                    f"changed target did not receive a new current cache identity: {slot}"
                )

    def _before(self) -> AudioConversionSnapshot:
        if self.before is None:
            raise AudioConversionRuntimeError("audio conversion runtime is not prepared")
        return self.before


def build_audio_conversion_plan(
    scenario: OnlineScenario,
    *,
    sandbox_project: Path,
    sandbox_root: Path,
    asset_root: Path,
    io_root: Path,
) -> AudioConversionPlan:
    if (
        scenario.api != AUDIO_CONVERT_URI
        or scenario.versions != (SUPPORTED_VERSION,)
        or scenario.protocol != "preview_confirm"
        or scenario.primary_dispatch.count != 1
    ):
        raise AudioConversionRuntimeError("audio conversion plan requires one 2024.1 case")
    spec = scenario.fixture.get("asset_spec")
    if not isinstance(spec, Mapping) or spec.get("contract") != AUDIO_CONVERSION_FIXTURE_CONTRACT:
        raise AudioConversionRuntimeError(f"{scenario.id} lacks the reviewed conversion asset spec")
    request = _mapping(spec.get("request"), "request")
    objects = _strings(request.get("objects"), "request.objects")
    platforms = _strings(request.get("platforms"), "request.platforms")
    languages = _strings(request.get("languages"), "request.languages")
    if not set(platforms) <= _SUPPORTED_PLATFORMS:
        raise AudioConversionRuntimeError("conversion request contains an unsupported platform")
    if not set(languages) <= _SUPPORTED_LANGUAGES:
        raise AudioConversionRuntimeError("conversion request contains an unsupported language")
    wav_spec = _mapping(spec.get("wav"), "wav")
    if wav_spec.get("format") != "pcm_s16le_mono_48000hz":
        raise AudioConversionRuntimeError("conversion WAV format is not the closed PCM fixture")
    filename_pattern = _safe_wav_pattern(wav_spec.get("filename_pattern"))
    presets = tuple(
        ConversionPreset(
            key=_text(row.get("key"), "conversion key"),
            name=_text(row.get("name"), "conversion name"),
            codec=_codec(row.get("codec")),
            sample_rate=_positive_int(row.get("sample_rate"), "sample_rate"),
            channels=_positive_int(row.get("channels"), "channels"),
        )
        for row in _mappings(spec.get("conversion_settings"), "conversion_settings")
    )
    if len({item.key for item in presets}) != len(presets) or len(
        {item.name for item in presets}
    ) != len(presets):
        raise AudioConversionRuntimeError("conversion preset keys/names must be unique")
    if any(item.channels != 1 for item in presets):
        raise AudioConversionRuntimeError("the reviewed conversion fixtures support mono only")
    if any(item.sample_rate not in _SUPPORTED_SAMPLE_RATES for item in presets):
        raise AudioConversionRuntimeError("conversion fixture sample rate is not reviewed")
    preset_keys = {item.key for item in presets}

    bindings: list[ConversionBinding] = []
    for control, field in ((False, "object_bindings"), (True, "control_bindings")):
        for row in _mappings(spec.get(field, []), field):
            path = _wwise_path(row.get("path"))
            if "source_keys_by_language" in row:
                source_map = _mapping(
                    row.get("source_keys_by_language"), "source_keys_by_language"
                )
                if set(source_map) != set(languages):
                    raise AudioConversionRuntimeError(
                        f"{path} localized source map differs from requested languages"
                    )
                source_keys = tuple(
                    (language, _text(source_map.get(language), "source key"))
                    for language in languages
                )
            else:
                key = _text(row.get("source_key"), "source key")
                if languages != ("SFX",):
                    raise AudioConversionRuntimeError(
                        f"{path} requires explicit localized source bindings"
                    )
                source_keys = (("SFX", key),)
            if set(dict(source_keys)) != set(languages) or len(source_keys) != len(
                dict(source_keys)
            ):
                raise AudioConversionRuntimeError(
                    f"{path} does not bind exactly one source for each requested language"
                )
            setting_map = _mapping(row.get("effective_settings"), "effective_settings")
            if set(setting_map) != set(platforms):
                raise AudioConversionRuntimeError(
                    f"{path} effective settings differ from requested platforms"
                )
            settings = tuple(
                (platform, _text(setting_map.get(platform), "setting key"))
                for platform in platforms
            )
            if set(dict(settings)) != set(platforms) or not set(dict(settings).values()) <= preset_keys:
                raise AudioConversionRuntimeError(f"{path} effective settings are not closed")
            bindings.append(ConversionBinding(path, source_keys, settings, control))
    if not bindings or len({item.path for item in bindings}) != len(bindings):
        raise AudioConversionRuntimeError("conversion binding paths must be non-empty and unique")
    if set(objects) != {item.path for item in bindings if not item.control}:
        raise AudioConversionRuntimeError("request objects differ from non-control bindings")
    if tuple(objects) != tuple(item.path for item in bindings if not item.control):
        raise AudioConversionRuntimeError("request object order differs from reviewed bindings")
    controls = _strings_allow_empty(spec.get("control_objects"), "control_objects")
    if tuple(controls) != tuple(item.path for item in bindings if item.control):
        raise AudioConversionRuntimeError("control objects differ from reviewed control bindings")
    source_pairs = tuple(
        (language, source_key)
        for binding in bindings
        for language, source_key in binding.source_keys_by_language
    )
    if len(source_pairs) != len(set(source_pairs)):
        raise AudioConversionRuntimeError("source language/key bindings must be globally unique")
    if len({source_key for _language, source_key in source_pairs}) != len(source_pairs):
        raise AudioConversionRuntimeError("source keys must be unique across the fixture")
    if _positive_int(wav_spec.get("count"), "wav.count") != len(source_pairs):
        raise AudioConversionRuntimeError("reviewed WAV count differs from source bindings")
    relative_sources = tuple(
        _materialize_wav_relative(filename_pattern, source_key)
        for _language, source_key in source_pairs
    )
    if len(relative_sources) != len(set(relative_sources)):
        raise AudioConversionRuntimeError("WAV pattern aliases distinct source bindings")

    source_seeds = {
        source_key: f"{scenario.id}:{source_key}:v1"
        for _language, source_key in source_pairs
    }
    initial_settings = {
        binding.path: binding.settings_by_platform for binding in bindings
    }
    source_delta: SourceDelta | None = None
    setting_delta: SettingDelta | None = None
    missing_cache_paths: tuple[str, ...] = ()
    delta_rows = _mappings(spec.get("delta_plan", []), "delta_plan")
    if scenario.id == "VS24-F-AUDIO-CONVERT-04":
        source_delta, setting_delta, missing_cache_paths = _parse_case04_deltas(
            delta_rows,
            bindings=tuple(bindings),
            platforms=platforms,
            preset_keys=preset_keys,
        )
        source_seeds[source_delta.source_key] = source_delta.before_seed
        initial_settings[setting_delta.path] = setting_delta.before_by_platform
    elif delta_rows:
        raise AudioConversionRuntimeError("only case04 may declare conversion deltas")
    profile_settings = [binding.settings_by_platform for binding in bindings]
    profile_settings.extend(
        settings
        for path, settings in initial_settings.items()
        if settings != next(
            binding.settings_by_platform
            for binding in bindings
            if binding.path == path
        )
    )
    profiles = derive_conversion_profiles(
        scenario_id=scenario.id,
        platforms=platforms,
        presets=presets,
        settings_maps=profile_settings,
    )
    expected = _mapping(spec.get("expected_outputs"), "expected_outputs")
    expected_count = _positive_int(expected.get("count"), "expected_outputs.count")
    if expected_count != len(objects) * len(platforms) * len(languages):
        raise AudioConversionRuntimeError("reviewed output count differs from request matrix")
    project, sandbox, assets, io = _validate_runtime_roots(
        sandbox_project=sandbox_project,
        sandbox_root=sandbox_root,
        asset_root=asset_root,
        io_root=io_root,
    )
    operation_request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": SUPPORTED_VERSION,
        "operation": "waapi.call",
        "arguments": {
            "api": AUDIO_CONVERT_URI,
            "args": {
                "objects": list(objects),
                "platforms": list(platforms),
                "languages": list(languages),
            },
            "options": {},
            "io_root": str(io),
        },
    }
    return AudioConversionPlan(
        scenario_id=scenario.id,
        sandbox_project=project,
        sandbox_root=sandbox,
        asset_root=assets,
        io_root=io,
        objects=objects,
        platforms=platforms,
        languages=languages,
        presets=presets,
        profiles=profiles,
        bindings=tuple(bindings),
        wav_filename_pattern=filename_pattern,
        source_seeds_by_key=tuple(source_seeds.items()),
        initial_settings_by_path=tuple(initial_settings.items()),
        source_delta=source_delta,
        setting_delta=setting_delta,
        missing_cache_paths=missing_cache_paths,
        operation_request=operation_request,
        expected_output_count=expected_count,
    )


def derive_conversion_profiles(
    *,
    scenario_id: str,
    platforms: Sequence[str],
    presets: Sequence[ConversionPreset],
    settings_maps: Sequence[Sequence[tuple[str, str]]],
) -> tuple[ConversionProfile, ...]:
    """Normalize platform components into deterministic real ShareSet profiles."""

    identity = _text(scenario_id, "scenario_id")
    closed_platforms = tuple(_text(item, "platform") for item in platforms)
    if (
        not closed_platforms
        or len(closed_platforms) != len(set(closed_platforms))
        or not set(closed_platforms) <= _SUPPORTED_PLATFORMS
    ):
        raise AudioConversionRuntimeError(
            "conversion profile platforms are not closed"
        )
    components = {item.key: item for item in presets}
    if (
        not components
        or len(components) != len(tuple(presets))
        or len({item.name for item in presets}) != len(tuple(presets))
    ):
        raise AudioConversionRuntimeError(
            "conversion profile component keys/names are missing or duplicated"
        )
    if any(
        item.codec not in _PLUGINS
        or item.sample_rate not in _SUPPORTED_SAMPLE_RATES
        or item.channels != 1
        for item in presets
    ):
        raise AudioConversionRuntimeError(
            "conversion profile component format is outside the reviewed set"
        )
    signatures: list[tuple[tuple[str, str], ...]] = []
    for raw in settings_maps:
        values = tuple(raw)
        if (
            tuple(platform for platform, _key in values) != closed_platforms
            or len(values) != len(dict(values))
            or not set(dict(values).values()) <= set(components)
        ):
            raise AudioConversionRuntimeError(
                "conversion profile component map is not closed"
            )
        if values not in signatures:
            signatures.append(values)
    if not signatures:
        raise AudioConversionRuntimeError("conversion fixture has no ShareSet profile")

    safe_identity = re.sub(r"[^A-Za-z0-9_]+", "_", identity).strip("_")
    profiles: list[ConversionProfile] = []
    for signature in signatures:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "scenario_id": identity,
                    "components_by_platform": [
                        {
                            "platform": platform,
                            "component": asdict(components[key]),
                        }
                        for platform, key in signature
                    ],
                },
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        profiles.append(
            ConversionProfile(
                key=f"profile-{digest[:16]}",
                name=f"SemanticLab_{safe_identity}_ShareSet_{digest[:12]}",
                components_by_platform=signature,
            )
        )
    if len({item.key for item in profiles}) != len(profiles) or len(
        {item.name for item in profiles}
    ) != len(profiles):
        raise AudioConversionRuntimeError("derived Conversion profiles collided")
    return tuple(profiles)


def _profile_settings_from_spec(
    *,
    scenario_id: str,
    spec: Mapping[str, Any],
    platforms: tuple[str, ...],
) -> tuple[tuple[tuple[str, str], ...], ...]:
    component_keys = {
        _text(row.get("key"), "conversion key")
        for row in _mappings(spec.get("conversion_settings"), "conversion_settings")
    }
    rows: list[tuple[tuple[str, str], ...]] = []
    for field in ("object_bindings", "control_bindings"):
        for binding in _mappings(spec.get(field, []), field):
            rows.append(
                _closed_platform_settings(
                    binding.get("effective_settings"),
                    field=f"{field}.effective_settings",
                    platforms=platforms,
                    preset_keys=component_keys,
                    ignored_keys=set(),
                )
            )
    deltas = _mappings(spec.get("delta_plan", []), "delta_plan")
    if scenario_id == "VS24-F-AUDIO-CONVERT-04":
        setting_rows = tuple(
            row
            for row in deltas
            if row.get("kind") == "replace_effective_settings"
        )
        if len(setting_rows) != 1:
            raise AudioConversionRuntimeError(
                "case04 prelaunch lacks one setting profile delta"
            )
        rows.append(
            _closed_platform_settings(
                setting_rows[0].get("before"),
                field="setting delta.before",
                platforms=platforms,
                preset_keys=component_keys,
                ignored_keys={"artifacts"},
            )
        )
    elif deltas:
        raise AudioConversionRuntimeError(
            "only case04 may declare prelaunch conversion deltas"
        )
    return tuple(rows)


def make_audio_conversion_prelaunch_hook(scenario: OnlineScenario):
    """Normalize the copied project and install exact case-owned ShareSets."""

    if (
        scenario.api != AUDIO_CONVERT_URI
        or scenario.versions != (SUPPORTED_VERSION,)
        or scenario.protocol != "preview_confirm"
        or scenario.primary_dispatch.count != 1
    ):
        raise AudioConversionRuntimeError("audio conversion hook requires one 2024.1 case")
    spec = _mapping(scenario.fixture.get("asset_spec"), "asset_spec")
    if spec.get("contract") != AUDIO_CONVERSION_FIXTURE_CONTRACT:
        raise AudioConversionRuntimeError("audio conversion hook received an unknown asset contract")
    request = _mapping(spec.get("request"), "request")
    platforms = _strings(request.get("platforms"), "request.platforms")
    languages = _strings(request.get("languages"), "request.languages")
    if not set(platforms) <= _SUPPORTED_PLATFORMS or not set(languages) <= _SUPPORTED_LANGUAGES:
        raise AudioConversionRuntimeError("audio conversion hook contains an unsupported lane")
    component_rows = _mappings(
        spec.get("conversion_settings"), "conversion_settings"
    )
    presets = tuple(
        ConversionPreset(
            key=_text(row.get("key"), "conversion key"),
            name=_text(row.get("name"), "conversion name"),
            codec=_codec(row.get("codec")),
            sample_rate=_positive_int(row.get("sample_rate"), "sample_rate"),
            channels=_positive_int(row.get("channels"), "channels"),
        )
        for row in component_rows
    )
    profiles = derive_conversion_profiles(
        scenario_id=scenario.id,
        platforms=platforms,
        presets=presets,
        settings_maps=_profile_settings_from_spec(
            scenario_id=scenario.id,
            spec=spec,
            platforms=platforms,
        ),
    )

    def hook(sandbox: SandboxProject, _asset_root: Path, io_root: Path) -> None:
        normalize_project_copy(
            sandbox.sandbox_project,
            io_root=io_root,
            owned_root=io_root.parent,
            request=ProjectPrelaunchRequest(
                scenario_id=scenario.id,
                languages=languages,
                platforms=platforms,
            ),
        )
        _install_conversion_profiles(
            sandbox.sandbox_project,
            scenario_id=scenario.id,
            platforms=platforms,
            presets=presets,
            profiles=profiles,
        )

    return hook


def _install_conversion_profiles(
    project: Path,
    *,
    scenario_id: str,
    platforms: Sequence[str],
    presets: Sequence[ConversionPreset],
    profiles: Sequence[ConversionProfile],
) -> None:
    if not platforms or len(platforms) != len(set(platforms)) or not set(
        platforms
    ) <= _SUPPORTED_PLATFORMS:
        raise AudioConversionRuntimeError("conversion profile platforms are not closed")
    path = _conversion_workunit(project)
    tree = ET.parse(path)
    root = tree.getroot()
    children_rows = root.findall("./Conversions/WorkUnit/ChildrenList")
    if len(children_rows) != 1:
        raise AudioConversionRuntimeError("conversion Work Unit has no unique ChildrenList")
    children = children_rows[0]
    existing_rows = children.findall("./Conversion")
    templates = {row.get("Name"): row for row in existing_rows}
    if len(templates) != len(existing_rows):
        raise AudioConversionRuntimeError("conversion Work Unit has duplicate ShareSet names")
    if "PCM" not in templates or "Voice" not in templates:
        raise AudioConversionRuntimeError("copied project lacks PCM/Voice conversion templates")
    existing_names = set(templates)
    component_by_key = {item.key: item for item in presets}
    if not component_by_key or len(component_by_key) != len(tuple(presets)):
        raise AudioConversionRuntimeError("conversion profile components are not unique")
    for profile in profiles:
        name = profile.name
        components = tuple(
            (platform, component_by_key[key])
            for platform, key in profile.components_by_platform
        )
        if tuple(platform for platform, _component in components) != tuple(platforms):
            raise AudioConversionRuntimeError("conversion profile platform order drifted")
        if any(
            component.sample_rate not in _SUPPORTED_SAMPLE_RATES
            or component.channels != 1
            for _platform, component in components
        ):
            raise AudioConversionRuntimeError("conversion profile format is outside the reviewed set")
        if name in existing_names:
            raise AudioConversionRuntimeError(f"conversion fixture name already exists: {name}")
        node = copy.deepcopy(
            templates[
                "PCM"
                if all(
                    component.codec in {"PCM", "ADPCM"}
                    for _platform, component in components
                )
                else "Voice"
            ]
        )
        node.set("Name", name)
        _replace_nested_ids(node, scenario_id=scenario_id, name=name)
        _configure_conversion_properties(
            node,
            components=components,
        )
        _configure_conversion_plugins(
            node,
            scenario_id=scenario_id,
            name=name,
            components=components,
        )
        children.append(node)
        existing_names.add(name)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.conversion.tmp")
    if temporary.exists():
        raise AudioConversionRuntimeError(f"conversion temporary file already exists: {temporary}")
    tree.write(temporary, encoding="utf-8", xml_declaration=True)
    os.replace(temporary, path)


def _configure_conversion_properties(
    node: ET.Element,
    *,
    components: Sequence[tuple[str, ConversionPreset]],
) -> None:
    if not components or any(component.channels != 1 for _platform, component in components):
        raise AudioConversionRuntimeError("only the reviewed mono channel enum is supported")
    # Wwise's conversion-setting enum uses 0 for a forced mono output and 4
    # for "As Input" (the value present in the copied templates).
    values_by_platform = {
        platform: {
            "Channels": "0",
            "LRMix": "0",
            "MaxSampleRate": str(component.sample_rate),
            "MinSampleRate": "0",
            "SampleRate": str(component.sample_rate),
        }
        for platform, component in components
    }
    properties = {row.get("Name"): row for row in node.findall("./PropertyList/Property")}
    for name in ("Channels", "LRMix", "MaxSampleRate", "MinSampleRate", "SampleRate"):
        prop = properties.get(name)
        if prop is None:
            raise AudioConversionRuntimeError(f"conversion template lacks property {name}")
        value_list = prop.find("./ValueList")
        if value_list is None:
            raise AudioConversionRuntimeError(f"conversion property {name} lacks ValueList")
        for child in list(value_list):
            value_list.remove(child)
        if name == "SampleRate":
            # Preserve Wwise 2024's neutral unscoped value; every reviewed
            # platform receives its explicit effective value below.
            ET.SubElement(value_list, "Value").text = "0"
        for platform, _component in components:
            ET.SubElement(value_list, "Value", {"Platform": platform}).text = (
                values_by_platform[platform][name]
            )


def _configure_conversion_plugins(
    node: ET.Element,
    *,
    scenario_id: str,
    name: str,
    components: Sequence[tuple[str, ConversionPreset]],
) -> None:
    lists = node.findall("./ConversionPluginInfoList")
    if len(lists) != 1:
        raise AudioConversionRuntimeError("conversion template lacks one plugin list")
    parent = lists[0]
    for child in list(parent):
        parent.remove(child)
    for platform, component in components:
        codec = component.codec
        plugin_id, plugin_property = _PLUGINS[codec]
        info = ET.SubElement(parent, "ConversionPluginInfo", {"Platform": platform})
        plugin = ET.SubElement(
            info,
            "ConversionPlugin",
            {
                "Name": "",
                "ID": _stable_guid(scenario_id, name, "plugin", platform),
                "PluginName": codec,
                "CompanyID": "0",
                "PluginID": plugin_id,
            },
        )
        if plugin_property is not None:
            property_name, property_type, property_value = plugin_property
            property_list = ET.SubElement(plugin, "PropertyList")
            ET.SubElement(
                property_list,
                "Property",
                {"Name": property_name, "Type": property_type, "Value": property_value},
            )


def _replace_nested_ids(node: ET.Element, *, scenario_id: str, name: str) -> None:
    for index, row in enumerate(node.iter()):
        if "ID" in row.attrib:
            row.set("ID", _stable_guid(scenario_id, name, row.tag, str(index)))


def _stable_guid(*parts: str) -> str:
    value = uuid.uuid5(_GUID_NAMESPACE, ":".join(parts))
    return "{" + str(value).upper() + "}"


def _conversion_workunit(project: Path) -> Path:
    project_path = _real_existing_path(project, field="sandbox project", kind="file")
    path_input = project_path.parent / "Conversion Settings" / "Default Work Unit.wwu"
    path = _real_existing_path(path_input, field="conversion Work Unit", kind="file")
    if path.is_symlink() or not path.is_file():
        raise AudioConversionRuntimeError(f"conversion Work Unit is unavailable: {path}")
    return path


def _write_pcm_wav(path: Path, *, seed: str) -> None:
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise AudioConversionRuntimeError("conversion source path must be absolute")
    if target.exists() or target.is_symlink():
        raise AudioConversionRuntimeError(f"conversion source already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_symlink_components(target.parent)
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    frequency = 180 + int.from_bytes(digest[:2], "little") % 1200
    duration_ms = 220 + int.from_bytes(digest[2:4], "little") % 420
    sample_rate = 48_000
    frames = bytearray()
    for index in range(sample_rate * duration_ms // 1000):
        sample = int(8_000 * math.sin(2.0 * math.pi * frequency * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    with target.open("xb") as raw:
        with wave.open(raw, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(bytes(frames))


def _replace_pcm_wav_owned(path: Path, *, root: Path, seed: str) -> None:
    target = _owned_file_path(path, root, field="source WAV", require_exists=True)
    target.unlink()
    if target.exists() or target.is_symlink():
        raise AudioConversionRuntimeError(f"source WAV replacement did not remove {target}")
    _write_pcm_wav(target, seed=seed)


def _parse_wem(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    if len(data) < 44 or data[:4] not in {b"RIFF", b"RIFX"} or data[8:12] != b"WAVE":
        raise AudioConversionRuntimeError(f"converted media is not a RIFF/WAVE file: {path}")
    endian = ">" if data[:4] == b"RIFX" else "<"
    offset = 12
    format_tag: int | None = None
    sample_rate: int | None = None
    while offset + 8 <= len(data):
        chunk = data[offset : offset + 4]
        size = struct.unpack(endian + "I", data[offset + 4 : offset + 8])[0]
        body = data[offset + 8 : offset + 8 + size]
        if chunk == b"fmt " and len(body) >= 8:
            format_tag = struct.unpack(endian + "H", body[:2])[0]
            sample_rate = struct.unpack(endian + "I", body[4:8])[0]
            break
        offset += 8 + size + (size & 1)
    if format_tag is None or sample_rate is None:
        raise AudioConversionRuntimeError(f"converted media lacks a valid fmt chunk: {path}")
    if format_tag == 1:
        codec = "PCM"
    elif format_tag in {2, 0x8311}:
        # Wwise 2024 emits its ADPCM cache artifacts with the private 0x8311
        # tag, while the synthetic program-test fixture uses the conventional
        # WAVE_FORMAT_ADPCM value (0x0002).  Both shapes are produced only
        # after the closed Conversion ShareSet/plugin binding is independently
        # verified, so they represent the same reviewed ADPCM codec here.
        codec = "ADPCM"
    elif format_tag == 0xFFFE:
        # Wwise 2024 writes its PCM cache artifacts with the extensible tag
        # (and a small Wwise-specific extension) rather than WAVE_FORMAT_PCM.
        # Treating every extensible WEM as Vorbis made the real header oracle
        # reject valid PCM output even though Wwise's Vorbis tag is 0xFFFF.
        codec = "PCM"
    elif b"vorb" in data or format_tag == 0xFFFF:
        codec = "Vorbis"
    else:
        codec = f"unknown:{format_tag}"
    return codec, sample_rate


def _file_state(path: Path) -> FileState:
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raise AudioConversionRuntimeError(f"fixture file path must be absolute: {raw}")
    _assert_no_symlink_components(raw)
    value = raw.resolve(strict=False)
    if not raw.exists():
        return FileState(str(value), False, None, None, None)
    if not value.is_file():
        raise AudioConversionRuntimeError(f"fixture path is not a regular file: {value}")
    stat = value.stat()
    digest = hashlib.sha256(value.read_bytes()).hexdigest()
    return FileState(str(value), True, stat.st_size, digest, stat.st_mtime_ns)


def audio_conversion_volatile_cache_paths(io_root: Path | str) -> tuple[str, ...]:
    """Derive the only Wwise cache-infrastructure paths allowed to vary.

    This helper is intentionally pure: archived business evidence can derive
    the same paths from its sealed ``io_root`` without trusting a persisted
    allowlist or requiring that the disposable sandbox still exists.
    """

    raw = Path(io_root).expanduser()
    if not raw.is_absolute():
        raise AudioConversionRuntimeError("audio conversion I/O root must be absolute")
    root = raw.resolve(strict=False)
    return tuple(
        sorted(
            str(root.joinpath(*PurePosixPath(relative).parts))
            for relative in _VOLATILE_CACHE_RELATIVE_PATHS
        )
    )


def _volatile_file_state(path: Path, *, root: Path) -> VolatileFileState:
    owner = _real_existing_path(root, field="volatile cache root", kind="directory")
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raise AudioConversionRuntimeError("volatile cache path must be absolute")
    try:
        relative = raw.relative_to(owner)
    except ValueError as exc:
        raise AudioConversionRuntimeError(
            f"volatile cache path escapes its owned root: {raw}"
        ) from exc
    current = owner
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise AudioConversionRuntimeError(
                f"volatile cache path must not use a symlink: {current}"
            )
    normalized = raw.resolve(strict=False)
    if normalized == owner or owner not in normalized.parents:
        raise AudioConversionRuntimeError(
            f"volatile cache path escapes its owned root: {normalized}"
        )
    try:
        metadata = raw.lstat()
    except FileNotFoundError:
        return VolatileFileState(str(normalized), False, None)
    if not stat_module.S_ISREG(metadata.st_mode):
        raise AudioConversionRuntimeError(
            f"volatile cache path is not a regular file: {normalized}"
        )
    if not 0 <= metadata.st_size <= _MAX_VOLATILE_CACHE_FILE_BYTES:
        raise AudioConversionRuntimeError(
            f"volatile cache file exceeds its bounded size: {normalized}"
        )
    return VolatileFileState(str(normalized), True, metadata.st_size)


def _assert_volatile_cache_layer(
    snapshot: AudioConversionSnapshot,
    plan: AudioConversionPlan,
) -> None:
    expected = audio_conversion_volatile_cache_paths(plan.io_root)
    observed = tuple(item.path for item in snapshot.volatile_cache_files)
    if observed != expected or len(set(observed)) != len(observed):
        raise AudioConversionRuntimeError(
            "volatile cache metadata differs from the exact infrastructure allowlist"
        )
    stable_paths = {item.path for item in snapshot.output_tree}
    artifact_paths = {item.converted_path for item in snapshot.artifacts}
    if stable_paths & set(expected) or artifact_paths & set(expected):
        raise AudioConversionRuntimeError(
            "volatile cache infrastructure overlaps business conversion output"
        )
    for item in snapshot.volatile_cache_files:
        if (
            type(item.present) is not bool
            or (item.present and (type(item.size) is not int or not 0 <= item.size <= _MAX_VOLATILE_CACHE_FILE_BYTES))
            or (not item.present and item.size is not None)
        ):
            raise AudioConversionRuntimeError(
                "volatile cache metadata is malformed or unbounded"
            )


def _tree_files(
    root: Path,
    *,
    predicate: Callable[[Path], bool] | None = None,
) -> tuple[FileState, ...]:
    value = _real_existing_path(root, field="fixture tree", kind="directory")
    rows = [
        _file_state(path)
        for path in sorted(value.rglob("*"))
        if path.is_file() and not path.is_symlink() and (predicate is None or predicate(path))
    ]
    if len(rows) > 4096:
        raise AudioConversionRuntimeError("conversion fixture file inventory exceeded 4096")
    return tuple(rows)


def _is_originals_file(path: Path) -> bool:
    return "Originals" in path.parts and path.suffix.casefold() == ".wav"


def _is_authoring_project_file(path: Path) -> bool:
    return path.suffix.casefold() in {".wproj", ".wwu"}


def _unlink_owned_file(path: Path, io_root: Path) -> None:
    target = _owned_file_path(
        path,
        io_root,
        field="conversion artifact",
        require_exists=True,
    )
    target.unlink()
    if target.exists():
        raise AudioConversionRuntimeError(f"conversion artifact removal did not persist: {target}")


def _source_asset_path(
    plan: AudioConversionPlan,
    language: str,
    source_key: str,
) -> Path:
    if (language, source_key) not in {
        pair
        for binding in plan.bindings
        for pair in binding.source_keys_by_language
    }:
        raise AudioConversionRuntimeError("source asset request is outside the planned bindings")
    relative = _materialize_wav_relative(plan.wav_filename_pattern, source_key)
    root = plan.asset_root / "sources" / language
    target = (root / relative).resolve(strict=False)
    if target == plan.asset_root or plan.asset_root not in target.parents:
        raise AudioConversionRuntimeError("materialized source WAV escapes asset_root")
    return target


def _source_originals_subfolder(plan: AudioConversionPlan, source_key: str) -> str:
    key = _text(source_key, "source key")
    if key not in dict(plan.source_seeds_by_key):
        raise AudioConversionRuntimeError("originals subfolder source is outside the plan")
    return _safe_originals_subfolder(f"SemanticLab/{plan.scenario_id}/{key}")


def _resolve_project_original_path(
    plan: AudioConversionPlan,
    *,
    language: str,
    source_key: str,
    original_file_path: str,
    original_relative_file_path: str,
) -> Path:
    """Bind both reflected Wwise path fields to one plan-owned Original WAV.

    Wwise 2024 can reflect ``originalFilePath`` as the relative ``AudioFile``
    spelling stored in the WWU while ``originalRelativeFilePath`` includes the
    SFX or Voices prefix.  Neither value is ever resolved against the process
    working directory.  Instead, the reviewed import destination is derived
    from the immutable plan and each reflected spelling must independently
    identify that exact file.
    """

    expected, allowed_relative = _planned_project_original(
        plan,
        language=language,
        source_key=source_key,
    )
    _assert_project_original_representation(
        original_file_path,
        expected=expected,
        allowed_relative=allowed_relative,
        root=plan.sandbox_root,
        field="originalFilePath",
    )
    _assert_project_original_representation(
        original_relative_file_path,
        expected=expected,
        allowed_relative=allowed_relative,
        root=plan.sandbox_root,
        field="originalRelativeFilePath",
    )
    return expected


def _planned_project_original(
    plan: AudioConversionPlan,
    *,
    language: str,
    source_key: str,
) -> tuple[Path, frozenset[tuple[str, ...]]]:
    source = _source_asset_path(plan, language, source_key)
    subfolder = PurePosixPath(_source_originals_subfolder(plan, source_key))
    if language == "SFX":
        language_parts = ("SFX",)
    elif language in _SUPPORTED_LANGUAGES:
        language_parts = ("Voices", language)
    else:
        raise AudioConversionRuntimeError(
            f"project Original uses an unsupported language: {language!r}"
        )
    content_parts = (*subfolder.parts, source.name)
    originals_parts = (*language_parts, *content_parts)
    expected = _owned_file_path(
        plan.sandbox_project.parent.joinpath("Originals", *originals_parts),
        plan.sandbox_root,
        field="planned project Original",
        require_exists=True,
    )
    return expected, frozenset(
        {
            ("Originals", *originals_parts),
            originals_parts,
            content_parts,
        }
    )


def _assert_project_original_representation(
    value: str,
    *,
    expected: Path,
    allowed_relative: frozenset[tuple[str, ...]],
    root: Path,
    field: str,
) -> None:
    normalized = _validated_waapi_path_text(value, field=field)
    if normalized.startswith("/") or re.fullmatch(
        r"[A-Za-z]:/.*", normalized
    ):
        observed = _owned_waapi_host_file_path(
            normalized,
            root,
            field=field,
            require_exists=True,
        )
        if observed != expected:
            raise AudioConversionRuntimeError(
                f"{field} does not identify the planned project Original"
            )
        return
    parts = _safe_waapi_relative_path_parts(normalized, field=field)
    if parts not in allowed_relative:
        raise AudioConversionRuntimeError(
            f"{field} does not identify the planned project Original"
        )


def _safe_waapi_relative_path_parts(value: str, *, field: str) -> tuple[str, ...]:
    parts = value.split("/")
    if (
        len(parts) > 32
        or any(part in {"", ".", ".."} for part in parts)
        or any(part != part.strip() or ":" in part for part in parts)
    ):
        raise AudioConversionRuntimeError(f"{field} is not a safe relative path")
    pure = PurePosixPath(*parts)
    if pure.is_absolute() or tuple(pure.parts) != tuple(parts):
        raise AudioConversionRuntimeError(f"{field} is not a safe relative path")
    return tuple(parts)


def _validated_waapi_path_text(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise AudioConversionRuntimeError(f"{field} must be a non-empty path string")
    return value.replace("\\", "/")


def _safe_originals_subfolder(value: Any) -> str:
    text = _text(value, "originalsSubFolder").replace("\\", "/")
    parts = text.split("/")
    if (
        text.startswith("/")
        or len(parts) > 16
        or any(part in {"", ".", ".."} for part in parts)
        or any("\x00" in part or ":" in part for part in parts)
    ):
        raise AudioConversionRuntimeError("originalsSubFolder must be a safe relative path")
    return "/".join(parts)


def _safe_wav_pattern(value: Any) -> str:
    pattern = _text(value, "wav.filename_pattern")
    if "\\" in pattern or "\x00" in pattern:
        raise AudioConversionRuntimeError("wav.filename_pattern must use safe POSIX separators")
    if pattern.count("{source_key}") != 1:
        raise AudioConversionRuntimeError(
            "wav.filename_pattern must contain exactly one {source_key} placeholder"
        )
    if "{" in pattern.replace("{source_key}", "") or "}" in pattern.replace(
        "{source_key}", ""
    ):
        raise AudioConversionRuntimeError("wav.filename_pattern has an unknown placeholder")
    _materialize_wav_relative(pattern, "probe")
    return pattern


def _materialize_wav_relative(pattern: str, source_key: str) -> Path:
    key = _text(source_key, "source key")
    if any(value in key for value in ("/", "\\", "..", "\x00")):
        raise AudioConversionRuntimeError(f"unsafe source key: {key!r}")
    relative = Path(pattern.replace("{source_key}", key))
    if (
        relative.is_absolute()
        or relative.suffix.casefold() != ".wav"
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise AudioConversionRuntimeError(f"unsafe WAV filename pattern result: {relative}")
    return relative


def _parse_case04_deltas(
    rows: Sequence[Mapping[str, Any]],
    *,
    bindings: tuple[ConversionBinding, ...],
    platforms: tuple[str, ...],
    preset_keys: set[str],
) -> tuple[SourceDelta, SettingDelta, tuple[str, ...]]:
    if len(rows) != 3:
        raise AudioConversionRuntimeError("case04 requires exactly three reviewed deltas")
    binding_by_path = {item.path: item for item in bindings if not item.control}
    by_kind: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        kind = _text(row.get("kind"), "delta kind")
        if kind in by_kind:
            raise AudioConversionRuntimeError(f"duplicate case04 delta kind: {kind}")
        path = _wwise_path(row.get("path"))
        if path not in binding_by_path:
            raise AudioConversionRuntimeError("case04 delta targets a non-requested object")
        by_kind[kind] = row
    expected_kinds = {
        "replace_source_bytes",
        "replace_effective_settings",
        "delete_converted_artifacts",
    }
    if set(by_kind) != expected_kinds:
        raise AudioConversionRuntimeError("case04 delta kinds differ from the reviewed plan")

    source_row = by_kind["replace_source_bytes"]
    source_path = _wwise_path(source_row.get("path"))
    source_binding = binding_by_path[source_path]
    if len(source_binding.source_keys_by_language) != 1:
        raise AudioConversionRuntimeError("case04 source delta must target one SFX binding")
    _language, source_key = source_binding.source_keys_by_language[0]
    before_source = _mapping(source_row.get("before"), "source delta.before")
    after_source = _mapping(source_row.get("after"), "source delta.after")
    if (
        before_source.get("source_key") != source_key
        or after_source.get("source_key") != source_key
    ):
        raise AudioConversionRuntimeError("case04 source delta key differs from its binding")
    before_seed = _text(before_source.get("signal_seed"), "source delta before seed")
    after_seed = _text(after_source.get("signal_seed"), "source delta after seed")
    if before_seed == after_seed:
        raise AudioConversionRuntimeError("case04 source replacement seeds must differ")
    source_delta = SourceDelta(source_path, source_key, before_seed, after_seed)

    setting_row = by_kind["replace_effective_settings"]
    setting_path = _wwise_path(setting_row.get("path"))
    setting_binding = binding_by_path[setting_path]
    before_settings = _closed_platform_settings(
        setting_row.get("before"),
        field="setting delta.before",
        platforms=platforms,
        preset_keys=preset_keys,
        ignored_keys={"artifacts"},
    )
    after_settings = _closed_platform_settings(
        setting_row.get("after"),
        field="setting delta.after",
        platforms=platforms,
        preset_keys=preset_keys,
        ignored_keys={"artifacts"},
    )
    if after_settings != setting_binding.settings_by_platform:
        raise AudioConversionRuntimeError("case04 setting delta does not end at reviewed settings")
    if before_settings == after_settings:
        raise AudioConversionRuntimeError("case04 setting delta has no effective change")
    setting_delta = SettingDelta(setting_path, before_settings, after_settings)

    missing_row = by_kind["delete_converted_artifacts"]
    missing_path = _wwise_path(missing_row.get("path"))
    for phase in ("before", "after"):
        values = _mapping(missing_row.get(phase), f"missing delta.{phase}")
        if set(values) != set(platforms):
            raise AudioConversionRuntimeError("case04 missing-cache delta platform set drifted")
    paths = {source_path, setting_path, missing_path}
    if len(paths) != 3 or paths != set(binding_by_path):
        raise AudioConversionRuntimeError("case04 deltas do not cover exactly the three targets")
    return source_delta, setting_delta, (missing_path,)


def _closed_platform_settings(
    value: Any,
    *,
    field: str,
    platforms: tuple[str, ...],
    preset_keys: set[str],
    ignored_keys: set[str],
) -> tuple[tuple[str, str], ...]:
    payload = _mapping(value, field)
    if set(payload) != set(platforms) | ignored_keys:
        raise AudioConversionRuntimeError(f"{field} does not have the exact reviewed keys")
    result = tuple((platform, _text(payload.get(platform), field)) for platform in platforms)
    if not set(dict(result).values()) <= preset_keys:
        raise AudioConversionRuntimeError(f"{field} references an unknown conversion preset")
    return result


def _validate_runtime_roots(
    *,
    sandbox_project: Path,
    sandbox_root: Path,
    asset_root: Path,
    io_root: Path,
) -> tuple[Path, Path, Path, Path]:
    project = _real_existing_path(sandbox_project, field="sandbox project", kind="file")
    sandbox = _real_existing_path(sandbox_root, field="sandbox root", kind="directory")
    assets = _real_existing_path(asset_root, field="asset root", kind="directory")
    io = _real_existing_path(io_root, field="I/O root", kind="directory")
    if project.suffix.casefold() != ".wproj" or sandbox not in project.parents:
        raise AudioConversionRuntimeError("sandbox project is not owned by sandbox_root")
    owned_root = assets.parent
    if assets == io or io.parent != owned_root or owned_root not in sandbox.parents:
        raise AudioConversionRuntimeError(
            "asset, I/O, and project-copy roots do not share the scenario-owned root"
        )
    if sandbox in assets.parents or sandbox in io.parents or assets in sandbox.parents or io in sandbox.parents:
        raise AudioConversionRuntimeError("asset or I/O roots must not be nested in the project copy")
    return project, sandbox, assets, io


def _real_existing_path(path: Path, *, field: str, kind: str) -> Path:
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raw = raw.absolute()
    _assert_no_symlink_components(raw)
    try:
        value = raw.resolve(strict=True)
    except OSError as exc:
        raise AudioConversionRuntimeError(f"{field} is unavailable: {raw}") from exc
    if kind == "file" and not value.is_file():
        raise AudioConversionRuntimeError(f"{field} must be a regular file: {value}")
    if kind == "directory" and not value.is_dir():
        raise AudioConversionRuntimeError(f"{field} must be a directory: {value}")
    return value


def _assert_no_symlink_components(path: Path) -> None:
    raw = Path(path).expanduser()
    current = raw if raw.is_absolute() else raw.absolute()
    # Check the caller-controlled leaf before ``resolve``.  macOS exposes
    # ordinary temporary paths through system-owned ``/var`` and ``/tmp``
    # symlinks, so rejecting every ancestor would make an otherwise private
    # pytest/lifecycle root unusable.  The resolved containment checks below
    # still reject an intermediate link that escapes the scenario-owned root.
    if current.is_symlink():
        raise AudioConversionRuntimeError(f"fixture path must not be a symlink: {current}")


def _owned_waapi_host_file_path(
    value: Any,
    root: Path,
    *,
    field: str,
    require_exists: bool,
) -> Path:
    return _owned_file_path(
        _localize_waapi_host_path(value, field=field),
        root,
        field=field,
        require_exists=require_exists,
    )


def _localize_waapi_host_path(value: Any, *, field: str) -> Path:
    """Map only real host-absolute or the two reviewed Wine drive spellings."""

    normalized = _validated_waapi_path_text(value, field=field)
    drive_match = re.fullmatch(r"([A-Za-z]):/(.*)", normalized)
    if drive_match is not None:
        suffix = drive_match.group(2)
    elif normalized.startswith("/"):
        suffix = normalized[1:]
    else:
        raise AudioConversionRuntimeError(f"{field} must be an absolute host path")
    suffix_parts = suffix.split("/")
    if (
        len(suffix_parts) > 128
        or any(part in {"", ".", ".."} for part in suffix_parts)
        or any("\x00" in part for part in suffix_parts)
    ):
        raise AudioConversionRuntimeError(
            f"{field} contains an unsafe host path component"
        )

    if os.name != "nt" and drive_match is not None:
        drive = drive_match.group(1).upper()
        if drive == "Z":
            path = Path("/").joinpath(*suffix_parts)
        elif drive == "Y":
            if pwd is None:  # pragma: no cover - native Windows skips this branch
                raise AudioConversionRuntimeError(
                    f"{field} uses Wine Y: but the host account home is unavailable"
                )
            try:
                home = Path(pwd.getpwuid(os.getuid()).pw_dir)
            except (KeyError, OSError) as exc:
                raise AudioConversionRuntimeError(
                    f"{field} Wine Y: could not be mapped to the host account home"
                ) from exc
            path = home.joinpath(*suffix_parts)
        else:
            raise AudioConversionRuntimeError(
                f"{field} uses an unmappable Wine drive {drive}:"
            )
    else:
        path = Path(normalized)
    if not path.is_absolute():
        raise AudioConversionRuntimeError(f"{field} must be an absolute host path")
    return path


def _owned_file_path(
    path: Path,
    root: Path,
    *,
    field: str,
    require_exists: bool,
) -> Path:
    owner = _real_existing_path(root, field=f"{field} root", kind="directory")
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raise AudioConversionRuntimeError(f"{field} path must be absolute")
    _assert_no_symlink_components(raw)
    candidate = raw.resolve(strict=False)
    if candidate == owner or owner not in candidate.parents:
        raise AudioConversionRuntimeError(f"{field} escapes its owned root: {candidate}")
    if require_exists:
        if not raw.is_file():
            raise AudioConversionRuntimeError(f"{field} must be a regular file: {candidate}")
        target = raw.resolve(strict=True)
        if target == owner or owner not in target.parents:
            raise AudioConversionRuntimeError(f"{field} escapes its owned root: {target}")
    else:
        target = candidate
    return target


def _assert_identity_matrix(
    artifacts: Sequence[ConvertedArtifact],
    plan: AudioConversionPlan,
    *,
    initial: bool,
) -> None:
    object_ids: dict[str, str] = {}
    source_ids: dict[tuple[str, str], str] = {}
    original_paths: dict[tuple[str, str], str] = {}
    original_hashes: dict[tuple[str, str], str | None] = {}
    converted_paths: dict[str, tuple[str, str, str]] = {}
    conversion_profiles: dict[str, tuple[str, str]] = {}
    for artifact in artifacts:
        old_object = object_ids.setdefault(artifact.object_path, artifact.object_id)
        if old_object != artifact.object_id:
            raise AudioConversionRuntimeError("object GUID varies across conversion slots")
        source_slot = (artifact.object_path, artifact.language)
        old_source = source_ids.setdefault(source_slot, artifact.source_id)
        if old_source != artifact.source_id:
            raise AudioConversionRuntimeError("media/source ID varies across platform slots")
        old_original = original_paths.setdefault(source_slot, artifact.original_path)
        old_original_hash = original_hashes.setdefault(
            source_slot, artifact.original_file.sha256
        )
        if (
            old_original != artifact.original_path
            or old_original_hash != artifact.original_file.sha256
        ):
            raise AudioConversionRuntimeError("Original WAV proof varies across platform slots")
        previous_slot = converted_paths.get(artifact.converted_path)
        if previous_slot is not None and _cache_alias_is_forbidden(
            plan,
            previous_slot,
            artifact.slot,
            initial=initial,
        ):
            raise AudioConversionRuntimeError(
                "converted output path is reused across artifact slots whose "
                "reviewed effective formats differ"
            )
        converted_paths.setdefault(artifact.converted_path, artifact.slot)
        old_profile = conversion_profiles.setdefault(
            artifact.object_path,
            (artifact.conversion_id, artifact.conversion_name),
        )
        if old_profile != (artifact.conversion_id, artifact.conversion_name):
            raise AudioConversionRuntimeError(
                "one Sound resolves different Conversion ShareSets across platform slots"
            )
    if len(set(object_ids.values())) != len(object_ids):
        raise AudioConversionRuntimeError("distinct object paths reuse one object GUID")
    if len(set(source_ids.values())) != len(source_ids):
        raise AudioConversionRuntimeError("distinct object-language slots reuse one media/source ID")
    if len(set(original_paths.values())) != len(original_paths):
        raise AudioConversionRuntimeError("distinct source bindings reuse one Original WAV path")
    if None in original_hashes.values() or len(set(original_hashes.values())) != len(
        original_hashes
    ):
        raise AudioConversionRuntimeError("distinct source bindings reuse Original WAV bytes")
    expected_source_slots = {
        (binding.path, language)
        for binding in plan.bindings
        for language, _source_key in binding.source_keys_by_language
    }
    if set(source_ids) != expected_source_slots:
        raise AudioConversionRuntimeError("artifact source identity matrix is incomplete")


def _cache_alias_is_forbidden(
    plan: AudioConversionPlan,
    left: tuple[str, str, str],
    right: tuple[str, str, str],
    *,
    initial: bool,
) -> bool:
    """Reject aliases across sources or across distinct reviewed platform formats.

    Wwise may legitimately reuse one cache artifact for two platforms when the
    effective ShareSet component is byte-equivalent.  These reviewed fixtures
    deliberately use distinct codec/rate pairs per platform, so their aliases
    remain a materialization failure without turning that into a global Wwise
    rule.
    """

    if (left[0], left[2]) != (right[0], right[2]):
        return True
    if left[1] == right[1]:
        return False
    binding_by_path = {item.path: item for item in plan.bindings}
    preset_by_key = {item.key: item for item in plan.presets}
    binding = binding_by_path[left[0]]
    settings = dict(
        plan.initial_settings(binding.path)
        if initial
        else binding.settings_by_platform
    )
    left_component = preset_by_key[settings[left[1]]]
    right_component = preset_by_key[settings[right[1]]]
    return (
        left_component.codec,
        left_component.sample_rate,
        left_component.channels,
    ) != (
        right_component.codec,
        right_component.sample_rate,
        right_component.channels,
    )


def _assert_effective_setting_matrix(
    artifacts: Sequence[ConvertedArtifact],
    plan: AudioConversionPlan,
    profile_ids: Mapping[str, str],
    *,
    initial: bool,
    require_matching_file_format: bool,
) -> None:
    """Bind every platform slot to its reviewed Conversion reference.

    The baseline additionally proves the physical WEM header.  The post-delta
    pre-preview snapshot deliberately does not require a matching header: the
    setting-changed target still contains its sealed stale bytes until the
    evaluated ``audio.convert`` call replaces them.
    """

    preset_by_key = {item.key: item for item in plan.presets}
    binding_by_path = {item.path: item for item in plan.bindings}
    for artifact in artifacts:
        binding = binding_by_path.get(artifact.object_path)
        if binding is None:
            raise AudioConversionRuntimeError(
                f"artifact references an unplanned object: {artifact.object_path}"
            )
        settings = dict(
            plan.initial_settings(binding.path)
            if initial
            else binding.settings_by_platform
        )
        setting_key = settings.get(artifact.platform)
        expected_component = preset_by_key.get(setting_key or "")
        profile = plan.profile_for_settings(tuple(settings.items()))
        expected_id = profile_ids.get(profile.key)
        if expected_component is None or expected_id is None:
            raise AudioConversionRuntimeError(
                f"artifact slot has no closed effective setting: {artifact.slot}"
            )
        if (
            artifact.conversion_id != expected_id
            or artifact.conversion_name != profile.name
        ):
            raise AudioConversionRuntimeError(
                f"effective Conversion reference differs before evaluation: {artifact.slot}"
            )
        if require_matching_file_format and (
            artifact.codec != expected_component.codec
            or artifact.sample_rate != expected_component.sample_rate
        ):
            raise AudioConversionRuntimeError(
                f"baseline converted format differs for {artifact.slot}: "
                f"{(artifact.codec, artifact.sample_rate)!r} != "
                f"{(expected_component.codec, expected_component.sample_rate)!r}"
            )


def _without_file_paths(
    rows: Sequence[FileState],
    ignored_paths: set[str],
) -> tuple[FileState, ...]:
    return tuple(row for row in rows if row.path not in ignored_paths)


def _assert_no_conversion_errors(payload: Mapping[str, Any], *, context: str) -> None:
    rows: list[Mapping[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            if "errors" in value:
                errors = value["errors"]
                if not isinstance(errors, list) or not all(
                    isinstance(item, Mapping) for item in errors
                ):
                    raise AudioConversionRuntimeError(
                        f"{context} returned a malformed errors array"
                    )
                rows.extend(errors)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    bad = tuple(
        row
        for row in rows
        if str(row.get("severity", "")).casefold()
        in {"error", "fatal", "fatal error", "3", "4"}
    )
    if bad:
        raise AudioConversionRuntimeError(f"{context} returned conversion errors: {bad}")


def _tested_conversion_result(
    payload: Mapping[str, Any],
    *,
    expected_request: Mapping[str, Any],
) -> Mapping[str, Any]:
    if (
        payload.get("ok") is not True
        or payload.get("status") != "result_schema_checked"
        or payload.get("state") != "result_schema_checked"
        or payload.get("result_schema_checked") is not True
    ):
        raise AudioConversionRuntimeError(
            "tested transaction did not reach packaged result-schema verification"
        )
    agent_result = payload.get("agent_result")
    if not isinstance(agent_result, Mapping):
        raise AudioConversionRuntimeError(
            "tested transaction lacks the exact gateway agent_result"
        )
    if (
        agent_result.get("operation") != "waapi.call"
        or agent_result.get("executed") is not True
        or agent_result.get("request") != expected_request
    ):
        raise AudioConversionRuntimeError(
            "tested transaction agent_result is not bound to the reviewed request"
        )
    result = agent_result.get("result")
    if not isinstance(result, Mapping):
        raise AudioConversionRuntimeError(
            "tested transaction agent_result.result must be an object"
        )
    return result


def _json_clone(value: Any) -> Any:
    return json.loads(
        json.dumps(
            _json_compatible(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_compatible(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _json_compatible(value: Any) -> Any:
    """Materialize immutable JSON containers before archival serialization."""

    if isinstance(value, Mapping):
        return {key: _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value


def _assert_empty_result(value: Any, context: str) -> None:
    if value is not None and not isinstance(value, Mapping):
        raise AudioConversionRuntimeError(f"{context} result must be an object or null")


def _reference_id(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping) and value.get("id"):
        return str(value["id"])
    return None


def _reference_name(value: Any) -> str | None:
    if isinstance(value, Mapping) and value.get("name"):
        return str(value["name"])
    return None


def _rows(value: Any, context: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Mapping) or not isinstance(value.get("return"), list):
        raise AudioConversionRuntimeError(f"{context} result.return must be an array")
    rows = value["return"]
    if len(rows) > 256 or not all(isinstance(row, Mapping) for row in rows):
        raise AudioConversionRuntimeError(f"{context} returned malformed or excessive rows")
    return tuple(rows)


def _fields(values: Sequence[str]) -> tuple[str, ...]:
    rows = tuple(_text(value, "return field") for value in values)
    if not rows or len(rows) != len(set(rows)) or len(rows) > 32:
        raise AudioConversionRuntimeError("return fields must be 1..32 unique strings")
    return rows


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AudioConversionRuntimeError(f"{field} must be an object")
    return value


def _mappings(value: Any, field: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        raise AudioConversionRuntimeError(f"{field} must be an object array")
    return tuple(value)


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AudioConversionRuntimeError(f"{field} must be a string array")
    result = tuple(_text(row, field) for row in value)
    if not result or len(result) != len(set(result)):
        raise AudioConversionRuntimeError(f"{field} must be non-empty and unique")
    return result


def _strings_allow_empty(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AudioConversionRuntimeError(f"{field} must be a string array")
    result = tuple(_text(row, field) for row in value)
    if len(result) != len(set(result)):
        raise AudioConversionRuntimeError(f"{field} must contain unique strings")
    return result


def _codec(value: Any) -> str:
    result = _text(value, "codec")
    if result not in _PLUGINS:
        raise AudioConversionRuntimeError(f"unsupported fixture codec: {result}")
    return result


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AudioConversionRuntimeError(f"{field} must be a positive integer")
    return value


def _wwise_path(value: Any) -> str:
    result = _text(value, "Wwise path")
    if not result.startswith("\\") or "\\\\" in result:
        raise AudioConversionRuntimeError(f"invalid Wwise path: {result!r}")
    return result


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AudioConversionRuntimeError(f"{field} must be a non-empty string")
    return value


__all__ = [
    "AUDIO_CONVERSION_RUNTIME_CONTRACT",
    "AUDIO_CONVERT_URI",
    "AudioConversionBackend",
    "AudioConversionPlan",
    "AudioConversionRuntimeError",
    "AudioConversionSnapshot",
    "AudioConversionVerification",
    "ClosedAudioConversionBackend",
    "ConversionBinding",
    "ConversionPreset",
    "ConversionProfile",
    "ConvertedArtifact",
    "FileState",
    "PreparedAudioConversionRuntime",
    "VolatileFileState",
    "audio_conversion_volatile_cache_paths",
    "build_audio_conversion_plan",
    "derive_conversion_profiles",
    "make_audio_conversion_prelaunch_hook",
]
