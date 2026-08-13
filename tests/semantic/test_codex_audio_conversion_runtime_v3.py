from __future__ import annotations

import copy
import hashlib
import os
import shutil
import struct
import wave
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping

import pytest

from tests.semantic.support.codex_audio_conversion_runtime_v3 import (
    AUDIO_CONVERT_URI,
    AudioConversionRuntimeError,
    AudioConversionSnapshot,
    ClosedAudioConversionBackend,
    ConvertedArtifact,
    FileState,
    PreparedAudioConversionRuntime,
    VolatileFileState,
    _cache_alias_is_forbidden,
    _replace_pcm_wav_owned,
    _parse_wem,
    _source_asset_path,
    _write_pcm_wav,
    audio_conversion_volatile_cache_paths,
    build_audio_conversion_plan,
    make_audio_conversion_prelaunch_hook,
)
from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
from wwise_waapi.operation_registry import parse_operation_request


REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_V3 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"
SOURCE_2024 = REPO_ROOT / "tests" / "_org" / "2024.1"
CONVERT_IDS = tuple(f"VS24-F-AUDIO-CONVERT-{index:02d}" for index in range(1, 6))


def _scenario(scenario_id: str):
    return load_eval_bundle_v3(SUITE_V3).scenario(scenario_id)


def _roots(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    owned = tmp_path / "owned"
    sandbox = owned / "sandbox-root" / "project-copy"
    assets = owned / "assets"
    io = owned / "io"
    shutil.copytree(SOURCE_2024, sandbox)
    assets.mkdir(parents=True)
    io.mkdir()
    return sandbox / "SampleProject.wproj", sandbox, assets, io


def _plan(tmp_path: Path, scenario_id: str):
    project, sandbox, assets, io = _roots(tmp_path)
    return build_audio_conversion_plan(
        _scenario(scenario_id),
        sandbox_project=project,
        sandbox_root=sandbox,
        asset_root=assets,
        io_root=io,
    )


def test_all_five_cases_build_closed_waapi_call_protocols(tmp_path: Path) -> None:
    project, sandbox, assets, io = _roots(tmp_path)
    plans = [
        build_audio_conversion_plan(
            _scenario(scenario_id),
            sandbox_project=project,
            sandbox_root=sandbox,
            asset_root=assets,
            io_root=io,
        )
        for scenario_id in CONVERT_IDS
    ]

    assert [plan.expected_output_count for plan in plans] == [6, 4, 12, 6, 8]
    assert [plan.platforms for plan in plans] == [
        ("Windows", "Mac"),
        ("Windows",),
        ("Windows", "Mac", "Android"),
        ("Windows", "Mac"),
        ("Windows", "Mac"),
    ]
    for plan in plans:
        parsed = parse_operation_request(plan.operation_request, expected_version="2024.1")
        assert parsed.operation == "waapi.call"
        assert parsed.arguments["api"] == AUDIO_CONVERT_URI
        assert parsed.arguments["args"] == {
            "objects": list(plan.objects),
            "platforms": list(plan.platforms),
            "languages": list(plan.languages),
        }
        assert parsed.arguments["options"] == {}
        assert parsed.arguments["io_root"] == str(io.resolve())

        runtime = PreparedAudioConversionRuntime(
            scenario=_scenario(plan.scenario_id),
            plan=plan,
            backend=object(),
        )
        protocol = runtime.gateway_protocol()
        assert protocol.turn_prefix_counts == (2, 6)
        assert [step.subcommand for step in protocol.steps] == [
            "request-schema",
            "typed-call",
            "transaction-show",
            "confirm",
            "execute",
            "verify",
        ]
        typed_request = protocol.steps[1].arguments[-1]
        assert typed_request.expected_args == plan.operation_request["arguments"]["args"]
        assert typed_request.expected_options == {}
        assert typed_request.io_root == str(io.resolve())
        assert runtime.render_prompt() == _scenario(plan.scenario_id).render_prompt(
            {"io_root": str(io.resolve())}
        )


def test_case04_preserves_the_reviewed_baseline_and_delta_semantics(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "VS24-F-AUDIO-CONVERT-04")

    assert plan.source_delta is not None
    assert plan.source_delta.before_seed == "changed_source_baseline_v1"
    assert plan.source_delta.after_seed == "changed_source_replacement_v2"
    assert plan.source_delta.before_seed != plan.source_delta.after_seed
    assert plan.setting_delta is not None
    assert dict(plan.setting_delta.before_by_platform) == {
        "Windows": "windows_vorbis_24k_baseline",
        "Mac": "mac_pcm_44k_baseline",
    }
    assert dict(plan.setting_delta.after_by_platform) == {
        "Windows": "windows_pcm_48k",
        "Mac": "mac_vorbis_48k",
    }
    assert plan.initial_settings(plan.setting_delta.path) == plan.setting_delta.before_by_platform
    assert plan.missing_cache_paths == (
        r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\ConversionAudit\Missing_Cache",
    )
    controls = tuple(binding.path for binding in plan.bindings if binding.control)
    assert controls == (
        r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\ConversionAudit\Current_Control",
        r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\ConversionAudit\Untouched_Decoy",
    )


def test_case05_materializes_distinct_sources_with_the_same_leaf_name(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "VS24-F-AUDIO-CONVERT-05")
    paths = [
        _source_asset_path(plan, language, source_key)
        for binding in plan.bindings
        for language, source_key in binding.source_keys_by_language
    ]

    assert len(paths) == 4
    assert len(set(paths)) == 4
    assert {path.name for path in paths} == {"Hit.wav"}
    assert len({path.parent.name for path in paths}) == 4
    assert all(plan.asset_root in path.parents for path in paths)


def test_profile_model_allows_equal_platform_formats_without_global_alias_rule(
    tmp_path: Path,
) -> None:
    scenario = _scenario("VS24-F-AUDIO-CONVERT-01")
    fixture = copy.deepcopy(scenario.fixture)
    bindings = fixture["asset_spec"]["object_bindings"]
    for binding in bindings:
        binding["effective_settings"]["Mac"] = binding["effective_settings"][
            "Windows"
        ]
    mutated = replace(scenario, fixture=fixture)
    project, sandbox, assets, io = _roots(tmp_path)

    plan = build_audio_conversion_plan(
        mutated,
        sandbox_project=project,
        sandbox_root=sandbox,
        asset_root=assets,
        io_root=io,
    )

    assert all(
        len(set(dict(binding.settings_by_platform).values())) == 1
        for binding in plan.bindings
    )
    assert all(
        profile.components_by_platform[0][1]
        == profile.components_by_platform[1][1]
        for profile in plan.profiles
    )
    binding = plan.bindings[0]
    left = (binding.path, "Windows", "SFX")
    right = (binding.path, "Mac", "SFX")
    assert not _cache_alias_is_forbidden(plan, left, right, initial=False)

    reviewed = _plan(tmp_path / "reviewed", "VS24-F-AUDIO-CONVERT-01")
    reviewed_binding = reviewed.bindings[0]
    assert _cache_alias_is_forbidden(
        reviewed,
        (reviewed_binding.path, "Windows", "SFX"),
        (reviewed_binding.path, "Mac", "SFX"),
        initial=False,
    )


def test_plan_rejects_an_io_root_outside_the_scenario_owned_root(tmp_path: Path) -> None:
    project, sandbox, assets, _io = _roots(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(AudioConversionRuntimeError, match="scenario-owned root"):
        build_audio_conversion_plan(
            _scenario(CONVERT_IDS[0]),
            sandbox_project=project,
            sandbox_root=sandbox,
            asset_root=assets,
            io_root=outside,
        )


def test_every_case_builds_and_runs_its_prelaunch_hook_on_a_fresh_copy(
    tmp_path: Path,
) -> None:
    for scenario_id in CONVERT_IDS:
        scenario = _scenario(scenario_id)
        project, sandbox, assets, io = _roots(tmp_path / scenario_id)
        plan = build_audio_conversion_plan(
            scenario,
            sandbox_project=project,
            sandbox_root=sandbox,
            asset_root=assets,
            io_root=io,
        )
        before_conversion_names = {
            row.get("Name")
            for row in ET.parse(
                sandbox / "Conversion Settings" / "Default Work Unit.wwu"
            ).getroot().findall(
                "./Conversions/WorkUnit/ChildrenList/Conversion"
            )
        }
        make_audio_conversion_prelaunch_hook(scenario)(
            SimpleNamespace(sandbox_project=project), assets, io
        )
        project_xml = ET.parse(project).getroot()
        assert set(scenario.fixture["asset_spec"]["request"]["platforms"]) <= {
            row.get("Name")
            for row in project_xml.findall("./ProjectInfo/Project/Platforms/Platform")
        }
        assert set(scenario.fixture["asset_spec"]["request"]["languages"]) <= {
            row.get("Name")
            for row in project_xml.findall("./ProjectInfo/Project/LanguageList/Language")
        }
        conversion_xml = ET.parse(
            sandbox / "Conversion Settings" / "Default Work Unit.wwu"
        ).getroot()
        names = {
            row.get("Name")
            for row in conversion_xml.findall(
                "./Conversions/WorkUnit/ChildrenList/Conversion"
            )
        }
        assert names - before_conversion_names == {
            profile.name for profile in plan.profiles
        }
        assert {
            component.name for component in plan.presets
        }.isdisjoint(names - before_conversion_names)


@pytest.mark.parametrize(
    "scenario_id",
    [
        "VS24-F-AUDIO-CONVERT-03",
        "VS24-F-AUDIO-CONVERT-05",
    ],
)
def test_prelaunch_hook_injects_closed_conversion_xml(
    tmp_path: Path,
    scenario_id: str,
) -> None:
    project, sandbox, assets, io = _roots(tmp_path)
    scenario = _scenario(scenario_id)
    plan = build_audio_conversion_plan(
        scenario,
        sandbox_project=project,
        sandbox_root=sandbox,
        asset_root=assets,
        io_root=io,
    )
    hook = make_audio_conversion_prelaunch_hook(scenario)
    hook(SimpleNamespace(sandbox_project=project), assets, io)

    project_tree = ET.parse(project).getroot()
    project_platforms = {
        row.get("Name") for row in project_tree.findall("./ProjectInfo/Project/Platforms/Platform")
    }
    assert set(_scenario(scenario_id).fixture["asset_spec"]["request"]["platforms"]) <= project_platforms
    cache = project_tree.findall("./ProjectInfo/Project/MiscSettings/MiscSettingEntry[@Name='Cache']")
    assert len(cache) == 1
    assert cache[0].text == r"..\..\io\cache"
    localized_cache = project.parent.joinpath(
        *cache[0].text.replace("\\", "/").split("/")
    ).resolve()
    assert localized_cache == (io / "cache").resolve()

    root = ET.parse(sandbox / "Conversion Settings" / "Default Work Unit.wwu").getroot()
    rows = {row.get("Name"): row for row in root.findall("./Conversions/WorkUnit/ChildrenList/Conversion")}
    requested_platforms = plan.platforms
    components = {item.key: item for item in plan.presets}
    assert {profile.name for profile in plan.profiles} <= set(rows)
    for profile in plan.profiles:
        row = rows[profile.name]
        plugin_rows = row.findall("./ConversionPluginInfoList/ConversionPluginInfo")
        assert [item.get("Platform") for item in plugin_rows] == list(requested_platforms)
        for info in plugin_rows:
            platform = info.get("Platform")
            component = components[dict(profile.components_by_platform)[platform]]
            plugin = info.find("./ConversionPlugin")
            assert plugin is not None
            assert plugin.get("PluginName") == component.codec
            assert plugin.get("PluginID") == {
                "PCM": "1",
                "ADPCM": "2",
                "Vorbis": "4",
            }[component.codec]
            if component.codec == "Vorbis":
                quality = plugin.find("./PropertyList/Property[@Name='QualityFactor']")
                assert quality is not None and quality.get("Value") == "3"
        properties = {
            item.get("Name"): item for item in row.findall("./PropertyList/Property")
        }
        assert {
            item.get("Platform"): item.text
            for item in properties["Channels"].findall("./ValueList/Value")
        } == {platform: "0" for platform in requested_platforms}
        sample_values = {
            item.get("Platform"): item.text
            for item in properties["SampleRate"].findall("./ValueList/Value")
            if item.get("Platform") is not None
        }
        unscoped_sample_values = [
            item.text
            for item in properties["SampleRate"].findall("./ValueList/Value")
            if item.get("Platform") is None
        ]
        assert unscoped_sample_values == ["0"]
        assert sample_values == {
            platform: str(
                components[dict(profile.components_by_platform)[platform]].sample_rate
            )
            for platform in requested_platforms
        }

    with pytest.raises(AudioConversionRuntimeError, match="already exists"):
        hook(SimpleNamespace(sandbox_project=project), assets, io)


def test_pcm_wavs_are_deterministic_distinct_and_replaced_in_place(tmp_path: Path) -> None:
    root = tmp_path.resolve() / "assets"
    root.mkdir()
    first = root / "first.wav"
    same = root / "same.wav"
    other = root / "other.wav"
    _write_pcm_wav(first, seed="stable-seed")
    _write_pcm_wav(same, seed="stable-seed")
    _write_pcm_wav(other, seed="other-seed")

    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest(first) == digest(same)
    assert digest(first) != digest(other)
    with wave.open(str(first), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 48_000
        assert handle.getnframes() > 0

    old = digest(first)
    _replace_pcm_wav_owned(first, root=root, seed="replacement-seed")
    assert first.exists() and digest(first) != old
    with pytest.raises(AudioConversionRuntimeError, match="escapes"):
        _replace_pcm_wav_owned(tmp_path / "outside.wav", root=root, seed="bad")


def test_wem_parser_distinguishes_wwise_extensible_pcm_from_vorbis(
    tmp_path: Path,
) -> None:
    pcm = tmp_path / "wwise-extensible-pcm.wem"
    # This is the 24-byte Wwise PCM fmt shape observed in the 2024.1 cache:
    # 0xFFFE, mono, 44.1 kHz, 16-bit, followed by its six-byte extension.
    fmt = struct.pack("<HHIIHHH", 0xFFFE, 1, 44_100, 88_200, 2, 16, 6)
    fmt += b"\x00\x00\x01\x41\x00\x00"
    data = b"\x00\x00" * 8
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(data)) + data
    pcm.write_bytes(
        b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks
    )

    assert _parse_wem(pcm) == ("PCM", 44_100)


def test_wem_parser_recognizes_wwise_2024_private_adpcm_tag(
    tmp_path: Path,
) -> None:
    adpcm = tmp_path / "wwise-2024-adpcm.wem"
    # This is the 28-byte Wwise ADPCM fmt shape observed in the 2024.1 cache:
    # private format tag 0x8311, mono, 48 kHz, followed by its ten-byte
    # extension.  The parser needs only the codec tag and sample rate.
    fmt = struct.pack("<HHIIHHH", 0x8311, 1, 48_000, 27_000, 36, 4, 10)
    fmt += b"\x00\x00\x01\x41\x00\x00\x10\x56\x00\x00"
    data = b"\x00" * 16
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(data)) + data
    adpcm.write_bytes(
        b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks
    )

    assert _parse_wem(adpcm) == ("ADPCM", 48_000)


class _DirectCallRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
        self.overrides: dict[str, Any] = {}

    def __call__(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]):
        self.calls.append((uri, args, options))
        if uri in self.overrides:
            return self.overrides[uri]
        if uri == "ak.wwise.core.object.get":
            return {"return": [{"id": "{ROW}"}]}
        if uri == "ak.wwise.core.object.create":
            return {"id": "{CREATED}"}
        if uri == "ak.wwise.core.audio.import":
            return {"objects": []}
        if uri == AUDIO_CONVERT_URI:
            return {"errors": []}
        return {}


def test_closed_backend_emits_only_exact_reviewed_waapi_shapes(tmp_path: Path) -> None:
    recorder = _DirectCallRecorder()
    backend = ClosedAudioConversionBackend(recorder)
    source = tmp_path.resolve() / "source.wav"
    _write_pcm_wav(source, seed="closed-backend")

    assert backend.read_path(
        r"\Actor-Mixer Hierarchy\Default Work Unit",
        fields=("id", "path"),
        platform="Windows",
        language="SFX",
    ) == ({"id": "{ROW}"},)
    assert backend.read_id("{ROW}", fields=("id",)) == ({"id": "{ROW}"},)
    assert backend.create_parent(
        parent=r"\Actor-Mixer Hierarchy\Default Work Unit", name="SemanticLab"
    ) == "{CREATED}"
    backend.import_sound(
        parent=r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab",
        name="Hit",
        language="SFX",
        audio_file=source,
        originals_subfolder="SemanticLab/CASE/source",
    )
    backend.set_property("{SOUND}", "OverrideConversion", True)
    backend.set_reference("{SOUND}", "Conversion", "{CONVERSION}")
    assert backend.convert(
        objects=(r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Hit",),
        platforms=("Windows", "Mac"),
        languages=("SFX",),
    ) == {"errors": []}
    backend.save()

    read_path = recorder.calls[0]
    assert read_path == (
        "ak.wwise.core.object.get",
        {"from": {"path": [r"\Actor-Mixer Hierarchy\Default Work Unit"]}},
        {"return": ["id", "path"], "platform": "Windows", "language": "SFX"},
    )
    imported = next(row for row in recorder.calls if row[0] == "ak.wwise.core.audio.import")
    assert imported[1]["importOperation"] == "useExisting"
    assert imported[1]["autoAddToSourceControl"] is False
    assert imported[1]["autoCheckOutToSourceControl"] is False
    assert imported[1]["imports"] == [
        {
            "audioFile": str(source),
            "objectPath": (
                r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\<Sound SFX>Hit"
            ),
            "objectType": "Sound SFX",
            "importLanguage": "SFX",
            "originalsSubFolder": "SemanticLab/CASE/source",
        }
    ]
    converted = next(row for row in recorder.calls if row[0] == AUDIO_CONVERT_URI)
    assert converted[1] == {
        "objects": [r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Hit"],
        "platforms": ["Windows", "Mac"],
        "languages": ["SFX"],
    }
    assert converted[2] == {}
    reference = next(
        row for row in recorder.calls if row[0] == "ak.wwise.core.object.setReference"
    )
    assert reference == (
        "ak.wwise.core.object.setReference",
        {
            "object": "{SOUND}",
            "reference": "Conversion",
            "value": "{CONVERSION}",
        },
        {},
    )
def test_closed_backend_rejects_fatal_error_and_malformed_empty_result() -> None:
    recorder = _DirectCallRecorder()
    backend = ClosedAudioConversionBackend(recorder)
    recorder.overrides[AUDIO_CONVERT_URI] = {
        "errors": [{"severity": "Fatal Error", "message": "converter failed"}]
    }
    with pytest.raises(AudioConversionRuntimeError, match="conversion errors"):
        backend.convert(objects=(r"\A",), platforms=("Windows",), languages=("SFX",))

    recorder.overrides["ak.wwise.core.object.setProperty"] = "not-an-object"
    with pytest.raises(AudioConversionRuntimeError, match="object or null"):
        backend.set_property("{SOUND}", "OverrideConversion", True)

class _FakeConversionBackend:
    def __init__(self, plan) -> None:
        self.plan = plan
        self.sequence = 1
        self.parents = {
            r"\Actor-Mixer Hierarchy\Default Work Unit": ("{ACTOR-DWU}", "WorkUnit")
        }
        self.sounds: dict[str, dict[str, Any]] = {}
        self.sources: dict[str, dict[str, Any]] = {}
        self.component_by_key = {preset.key: preset for preset in plan.presets}
        self.profile_by_id = {
            "{" + profile.key + "}": profile for profile in plan.profiles
        }
        self.profile_id_by_name = {
            profile.name: "{" + profile.key + "}" for profile in plan.profiles
        }
        self.reference_calls: list[tuple[str, str]] = []
        self.clock_ns = 1_800_000_000_000_000_000

    def _id(self, kind: str) -> str:
        self.sequence += 1
        return f"{{{kind}-{self.sequence}}}"

    def read_path(
        self,
        path: str,
        *,
        fields,
        platform: str | None = None,
        language: str | None = None,
    ):
        if path in self.parents:
            object_id, object_type = self.parents[path]
            return ({"id": object_id, "path": path, "type": object_type},)
        prefix = "\\Conversion Settings\\Default Work Unit\\"
        if path.startswith(prefix):
            name = path[len(prefix) :]
            profile_id = self.profile_id_by_name.get(name)
            if profile_id is None:
                return ()
            return ({"id": profile_id, "name": name, "type": "Conversion", "path": path},)
        sound = self.sounds.get(path)
        if sound is None:
            return ()
        row: dict[str, Any] = {
            "id": sound["id"],
            "name": path.rsplit("\\", 1)[1],
            "type": "Sound",
            "path": path,
        }
        if language is not None:
            source_id = sound["sources"][language]
            row["activeSource"] = {"id": source_id}
        if platform is not None and sound.get("profile") is not None:
            conversion_id = sound["profile"]
            row["Conversion"] = {
                "id": conversion_id,
                "name": self.profile_by_id[conversion_id].name,
            }
        return (row,)

    def read_id(
        self,
        object_id: str,
        *,
        fields,
        platform: str | None = None,
        language: str | None = None,
    ):
        source = self.sources.get(object_id)
        if source is None:
            return ()
        row: dict[str, Any] = {
            "id": object_id,
            "name": Path(source["original"]).stem,
            "type": "AudioFileSource",
            "path": source["path"],
            "parent": {"id": source["parent"]},
            "audioSource:language": {"name": source["language"]},
            # Wwise 2024 reflects the WWU AudioFile spelling here rather than
            # necessarily returning an absolute host path.
            "originalFilePath": source.get(
                "reported_original",
                str(source["content_relative"]).replace("/", "\\"),
            ),
            "originalRelativeFilePath": source.get(
                "reported_relative",
                str(source["relative"]).replace("/", "\\"),
            ),
        }
        if platform is not None and platform in source["converted"]:
            row["convertedFilePath"] = source.get("reported_converted", {}).get(
                platform,
                str(source["converted"][platform]),
            )
        return (row,)

    def create_parent(self, *, parent: str, name: str) -> str:
        assert parent in self.parents
        path = parent + "\\" + name
        object_id = self._id("PARENT")
        self.parents[path] = (object_id, "ActorMixer")
        return object_id

    def import_sound(
        self,
        *,
        parent: str,
        name: str,
        language: str,
        audio_file: Path,
        originals_subfolder: str,
    ) -> None:
        assert parent in self.parents
        path = parent + "\\" + name
        sound = self.sounds.setdefault(
            path,
            {
                "id": self._id("SOUND"),
                "sources": {},
                "profile": None,
            },
        )
        source_id = sound["sources"].get(language)
        if source_id is None:
            source_id = self._id("SOURCE")
            sound["sources"][language] = source_id
        content_relative = Path(originals_subfolder) / audio_file.name
        language_root = (
            Path("SFX")
            if language == "SFX"
            else Path("Voices") / language
        )
        relative = language_root / content_relative
        destination = self.plan.sandbox_root / "Originals" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(audio_file, destination)
        prior_source = self.sources.get(source_id, {})
        converted = prior_source.get("converted", {})
        reported_converted = dict(prior_source.get("reported_converted", {}))
        if converted:
            replacement_digest = hashlib.sha256(audio_file.read_bytes()).hexdigest()[:16]
            reported_converted = {
                platform: str(
                    (
                        self.plan.io_root
                        / "cache"
                        / "reimported"
                        / platform
                        / language
                        / f"{source_id.strip('{}')}-{replacement_digest}.wem"
                    ).resolve()
                )
                for platform in self.plan.platforms
            }
        self.sources[source_id] = {
            "path": path + "\\" + source_id,
            "parent": sound["id"],
            "language": language,
            "original": destination.resolve(),
            "relative": relative,
            "content_relative": content_relative,
            "converted": converted,
            "reported_converted": reported_converted,
        }

    def set_property(
        self,
        object_id: str,
        name: str,
        value: Any,
        *,
        platform: str | None = None,
    ) -> None:
        assert name == "OverrideConversion" and value is True and platform is None
        assert any(sound["id"] == object_id for sound in self.sounds.values())

    def set_reference(
        self,
        object_id: str,
        name: str,
        target_id: str,
    ) -> None:
        assert name == "Conversion" and target_id in self.profile_by_id
        sound = next(row for row in self.sounds.values() if row["id"] == object_id)
        sound["profile"] = target_id
        # A post-baseline ShareSet switch changes Wwise's reflected cache
        # identity before a new file exists.  Model that distinction instead
        # of continuing to expose the old generated path.
        for source_id in sound["sources"].values():
            source = self.sources[source_id]
            if not source["converted"]:
                continue
            source["reported_converted"] = {
                platform: str(
                    (
                        self.plan.io_root
                        / platform
                        / source["language"]
                        / f"{source_id.strip('{}')}-{target_id.strip('{}')}.wem"
                    ).resolve()
                )
                for platform in self.plan.platforms
            }
        self.reference_calls.append((object_id, target_id))

    def convert(self, *, objects, platforms, languages):
        for object_path in objects:
            sound = self.sounds[object_path]
            for language in languages:
                source_id = sound["sources"][language]
                source = self.sources[source_id]
                source_digest = hashlib.sha256(Path(source["original"]).read_bytes()).digest()
                for platform in platforms:
                    profile = self.profile_by_id[sound["profile"]]
                    component_key = dict(profile.components_by_platform)[platform]
                    preset = self.component_by_key[component_key]
                    reported = source.get("reported_converted", {}).get(platform)
                    path = (
                        Path(reported)
                        if reported is not None
                        else (
                            self.plan.io_root
                            / platform
                            / language
                            / f"{source_id.strip('{}')}.wem"
                        )
                    )
                    _write_fake_wem(
                        path,
                        codec=preset.codec,
                        sample_rate=preset.sample_rate,
                        payload=source_digest,
                    )
                    self.clock_ns += 10_000
                    os.utime(path, ns=(self.clock_ns, self.clock_ns))
                    source["converted"][platform] = path.resolve()
                    source.get("reported_converted", {}).pop(platform, None)
        return {"errors": []}

    def save(self) -> None:
        return None


def _write_fake_wem(
    path: Path,
    *,
    codec: str,
    sample_rate: int,
    payload: bytes,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    format_tag = {"PCM": 1, "ADPCM": 2, "Vorbis": 0xFFFF}[codec]
    fmt = struct.pack("<HHIIHH", format_tag, 1, sample_rate, sample_rate * 2, 2, 16)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(payload)) + payload
    path.write_bytes(b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks)


def _gateway_verify_payload(runtime, result: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "ok": True,
        "status": "result_schema_checked",
        "state": "result_schema_checked",
        "result_schema_checked": True,
        "agent_result": {
            "operation": "waapi.call",
            "executed": True,
            "request": runtime.plan.operation_request,
            "result": dict(result),
        },
    }


@pytest.mark.parametrize("scenario_id", CONVERT_IDS)
def test_fake_backend_prepares_and_verifies_every_conversion_case(
    tmp_path: Path, scenario_id: str
) -> None:
    plan = _plan(tmp_path / scenario_id, scenario_id)
    backend = _FakeConversionBackend(plan)
    runtime = PreparedAudioConversionRuntime(
        scenario=_scenario(scenario_id), plan=plan, backend=backend
    ).prepare()

    runtime.verify_preview_unchanged().assert_passed()
    result_payload = backend.convert(
        objects=plan.objects,
        platforms=plan.platforms,
        languages=plan.languages,
    )
    runtime.verify_after_execution(
        verify_payload=_gateway_verify_payload(runtime, result_payload)
    ).assert_passed()
    for source_id, source in backend.sources.items():
        reflected = backend.read_id(source_id, fields=())[0]
        assert reflected["originalFilePath"] == str(
            source["content_relative"]
        ).replace("/", "\\")
        assert reflected["originalRelativeFilePath"] == str(
            source["relative"]
        ).replace("/", "\\")
        assert not Path(reflected["originalFilePath"]).is_absolute()


def test_after_oracle_archives_an_immutable_gateway_verify_payload(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "VS24-F-AUDIO-CONVERT-02")
    backend = _FakeConversionBackend(plan)
    runtime = PreparedAudioConversionRuntime(
        scenario=_scenario(plan.scenario_id), plan=plan, backend=backend
    ).prepare()
    runtime.verify_preview_unchanged().assert_passed()
    result_payload = backend.convert(
        objects=plan.objects,
        platforms=plan.platforms,
        languages=plan.languages,
    )
    verify_payload = _gateway_verify_payload(runtime, result_payload)

    verification = runtime.verify_after_execution(
        verify_payload=MappingProxyType(dict(verify_payload))
    )

    verification.assert_passed()
    assert len(verification.evidence["verify_payload_sha256"]) == 64


def test_exact_wwise_cache_infrastructure_is_volatile_but_recorded(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "VS24-F-AUDIO-CONVERT-01")
    volatile_paths = tuple(
        Path(path) for path in audio_conversion_volatile_cache_paths(plan.io_root)
    )
    for index, path in enumerate(volatile_paths, start=1):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"before" * index)
    backend = _FakeConversionBackend(plan)
    runtime = PreparedAudioConversionRuntime(
        scenario=_scenario(plan.scenario_id), plan=plan, backend=backend
    ).prepare()

    before = runtime.before
    assert before is not None
    assert tuple(item.path for item in before.volatile_cache_files) == tuple(
        str(path) for path in volatile_paths
    )
    assert all(item.present for item in before.volatile_cache_files)
    assert not {str(path) for path in volatile_paths} & {
        item.path for item in before.output_tree
    }
    for index, path in enumerate(volatile_paths, start=1):
        path.write_bytes(b"after-infrastructure-update" * index)

    runtime.verify_preview_unchanged().assert_passed()
    result_payload = backend.convert(
        objects=plan.objects,
        platforms=plan.platforms,
        languages=plan.languages,
    )
    result = runtime.verify_after_execution(
        verify_payload=_gateway_verify_payload(runtime, result_payload)
    )
    result.assert_passed()
    assert result.evidence["volatile_cache_changed_paths"] == [
        str(path) for path in volatile_paths
    ]


@pytest.mark.parametrize(
    "relative_path",
    (
        Path("Windows") / "SFX" / "preexisting-unbound.wem",
        Path("cache") / "LMDB" / "unexpected.mdb",
    ),
)
def test_prepare_rejects_preexisting_stable_output_not_bound_to_baseline(
    tmp_path: Path,
    relative_path: Path,
) -> None:
    plan = _plan(tmp_path / relative_path.stem, "VS24-F-AUDIO-CONVERT-01")
    unknown = plan.io_root / relative_path
    unknown.parent.mkdir(parents=True, exist_ok=True)
    unknown.write_bytes(b"unexplained setup output")
    backend = _FakeConversionBackend(plan)

    with pytest.raises(
        AudioConversionRuntimeError,
        match="not explained by baseline artifact readback",
    ):
        PreparedAudioConversionRuntime(
            scenario=_scenario(plan.scenario_id), plan=plan, backend=backend
        ).prepare()


def test_after_oracle_accepts_a_new_owned_target_cache_path(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "VS24-F-AUDIO-CONVERT-01")
    backend = _FakeConversionBackend(plan)
    runtime = PreparedAudioConversionRuntime(
        scenario=_scenario(plan.scenario_id), plan=plan, backend=backend
    ).prepare()
    before = runtime.before
    assert before is not None
    before_paths = {
        item.slot: item.converted_path
        for item in before.artifacts
        if item.object_path in plan.objects
    }
    normal_convert = backend.convert

    def convert_to_new_owned_paths(*, objects, platforms, languages):
        result = normal_convert(
            objects=objects,
            platforms=platforms,
            languages=languages,
        )
        for object_path in objects:
            sound = backend.sounds[object_path]
            for language in languages:
                source_id = sound["sources"][language]
                source = backend.sources[source_id]
                for platform in platforms:
                    old_path = Path(source["converted"][platform])
                    new_path = (
                        plan.io_root
                        / "relocated"
                        / platform
                        / language
                        / f"new-{source_id.strip('{}')}.wem"
                    )
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(old_path, new_path)
                    source["converted"][platform] = new_path.resolve()
        return result

    backend.convert = convert_to_new_owned_paths  # type: ignore[method-assign]
    result_payload = backend.convert(
        objects=plan.objects,
        platforms=plan.platforms,
        languages=plan.languages,
    )
    verification = runtime.verify_after_execution(
        verify_payload=_gateway_verify_payload(runtime, result_payload)
    )

    verification.assert_passed()
    after = verification.evidence["after"]
    assert all(
        row["converted_path"] != before_paths[
            (row["object_path"], row["platform"], row["language"])
        ]
        for row in after["artifacts"]
        if row["object_path"] in plan.objects
    )


def test_after_oracle_rejects_new_target_path_that_was_preexisting_non_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, before, after = _oracle_runtime(tmp_path)
    target_index = next(
        index
        for index, item in enumerate(after.artifacts)
        if item.object_path == runtime.plan.source_delta.path
    )
    current = after.artifacts[target_index]
    collision_path = str((runtime.plan.io_root / "preexisting-unbound.wem").resolve())
    preexisting = FileState(collision_path, True, 32, "preexisting", 75)
    before = replace(before, output_tree=(*before.output_tree, preexisting))
    runtime.before = before
    relocated = replace(
        current,
        converted_path=collision_path,
        file=replace(current.file, path=collision_path),
    )
    rows = list(after.artifacts)
    rows[target_index] = relocated
    after = replace(
        after,
        artifacts=tuple(rows),
        output_tree=tuple(item.file for item in rows if item.file.present),
    )
    monkeypatch.setattr(runtime, "snapshot", lambda: after)

    result = runtime.verify_after_execution(
        verify_payload=_gateway_verify_payload(runtime, {"errors": []})
    )

    assert not result.passed
    assert (
        "new target converted path collides with pre-existing non-target output"
        in result.failures
    )


@pytest.mark.parametrize(
    "relative_path",
    (
        Path("Windows") / "SFX" / "unbound-extra.wem",
        Path("cache") / "LMDB" / "unexpected.mdb",
    ),
)
def test_after_oracle_rejects_unbound_stable_output_files(
    tmp_path: Path,
    relative_path: Path,
) -> None:
    plan = _plan(tmp_path / relative_path.stem, "VS24-F-AUDIO-CONVERT-01")
    backend = _FakeConversionBackend(plan)
    runtime = PreparedAudioConversionRuntime(
        scenario=_scenario(plan.scenario_id), plan=plan, backend=backend
    ).prepare()
    result_payload = backend.convert(
        objects=plan.objects,
        platforms=plan.platforms,
        languages=plan.languages,
    )
    _write_fake_wem(
        plan.io_root / relative_path,
        codec="PCM",
        sample_rate=48_000,
        payload=b"unbound",
    )

    verification = runtime.verify_after_execution(
        verify_payload=_gateway_verify_payload(runtime, result_payload)
    )

    assert not verification.passed
    assert "non-requested conversion output tree changed" in verification.failures


def test_prepare_assigns_one_global_conversion_shareset_per_sound(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "VS24-F-AUDIO-CONVERT-04")
    backend = _FakeConversionBackend(plan)

    runtime = PreparedAudioConversionRuntime(
        scenario=_scenario(plan.scenario_id), plan=plan, backend=backend
    ).prepare()

    expected_calls = len(plan.bindings) + 1  # case04 changes one baseline ShareSet once
    assert len(backend.reference_calls) == expected_calls
    assert all(sound["profile"] in backend.profile_by_id for sound in backend.sounds.values())
    for binding in plan.bindings:
        sound = backend.sounds[binding.path]
        expected_profile = plan.profile_for_settings(binding.settings_by_platform)
        assert sound["profile"] == "{" + expected_profile.key + "}"
    assert runtime.before is not None
    before_slots = runtime.before.by_slot()
    assert runtime.before.baseline_artifacts == tuple(
        sorted(runtime._baseline.values(), key=lambda item: item.slot)
    )
    assert {
        row.object_path for row in runtime.before.baseline_artifacts
    } == {binding.path for binding in plan.bindings}
    assert plan.setting_delta is not None
    assert plan.source_delta is not None
    for changed_path in (plan.source_delta.path, plan.setting_delta.path):
        for platform in plan.platforms:
            slot = (changed_path, platform, "SFX")
            assert before_slots[slot].file.present is False
            assert before_slots[slot].converted_path != runtime._baseline[slot].converted_path


def test_case04_reimport_invalidates_current_paths_but_retains_sealed_baseline_files(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "VS24-F-AUDIO-CONVERT-04")
    backend = _FakeConversionBackend(plan)
    runtime = PreparedAudioConversionRuntime(
        scenario=_scenario(plan.scenario_id), plan=plan, backend=backend
    ).prepare()

    before = runtime.before
    assert before is not None
    before_slots = before.by_slot()
    baseline_slots = {row.slot: row for row in before.baseline_artifacts}
    assert set(before_slots) == set(baseline_slots)
    assert all(row.file.present and row.file.sha256 for row in baseline_slots.values())
    assert all(not before_slots[slot].file.present for slot in {
        (path, platform, language)
        for path in plan.objects
        for platform in plan.platforms
        for language in plan.languages
    })
    retained_paths = {row.path for row in before.output_tree}
    changed_paths = {
        plan.source_delta.path if plan.source_delta else "",
        plan.setting_delta.path if plan.setting_delta else "",
    }
    expected_retained = {
        row.converted_path
        for row in before.baseline_artifacts
        if row.object_path in changed_paths
        or next(item for item in plan.bindings if item.path == row.object_path).control
    }
    assert retained_paths == expected_retained
    assert all(
        next(item for item in before.output_tree if item.path == row.converted_path)
        == row.file
        for row in before.baseline_artifacts
        if row.converted_path in retained_paths
    )


def test_prepare_rejects_a_shared_platform_cache_alias_before_applying_deltas(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "VS24-F-AUDIO-CONVERT-04")
    backend = _FakeConversionBackend(plan)
    normal_convert = backend.convert

    def convert_with_shared_alias(*, objects, platforms, languages):
        result = normal_convert(
            objects=objects,
            platforms=platforms,
            languages=languages,
        )
        for source in backend.sources.values():
            first = source["converted"][platforms[0]]
            source["converted"] = {platform: first for platform in platforms}
        return result

    backend.convert = convert_with_shared_alias  # type: ignore[method-assign]

    with pytest.raises(
        AudioConversionRuntimeError,
        match="reviewed effective formats differ",
    ):
        PreparedAudioConversionRuntime(
            scenario=_scenario(plan.scenario_id), plan=plan, backend=backend
        ).prepare()

    # The shared alias is rejected before Missing_Cache deletion starts.
    missing_sound = backend.sounds[plan.missing_cache_paths[0]]
    missing_source = backend.sources[missing_sound["sources"]["SFX"]]
    assert Path(missing_source["converted"][plan.platforms[0]]).is_file()


@pytest.mark.skipif(os.name == "nt", reason="Wine drive mapping is POSIX-only")
def test_snapshot_accepts_exact_relative_absolute_and_wine_host_representations(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "VS24-F-AUDIO-CONVERT-01")
    backend = _FakeConversionBackend(plan)
    runtime = PreparedAudioConversionRuntime(
        scenario=_scenario(plan.scenario_id), plan=plan, backend=backend
    ).prepare()
    sources = list(backend.sources.values())

    sources[0]["reported_original"] = "Z:" + str(
        sources[0]["original"]
    ).replace("/", "\\")
    sources[0]["reported_converted"] = {
        platform: "Z:" + str(path).replace("/", "\\")
        for platform, path in sources[0]["converted"].items()
    }
    sources[1]["reported_original"] = str(sources[1]["original"])
    sources[2]["reported_original"] = (
        "Originals\\" + str(sources[2]["relative"]).replace("/", "\\")
    )

    snapshot = runtime.snapshot()
    by_source = {row.source_id: row for row in snapshot.artifacts}
    assert set(by_source) == set(backend.sources)
    assert all(Path(row.original_path).is_absolute() for row in snapshot.artifacts)
    assert all(Path(row.converted_path).is_absolute() for row in snapshot.artifacts)


@pytest.mark.parametrize(
    "failure",
    (
        "traversal",
        "unmapped-drive",
        "absolute-escape",
        "original-mismatch",
        "relative-mismatch",
        "missing-relative-evidence",
    ),
)
def test_snapshot_rejects_unbound_or_unsafe_original_path_evidence(
    tmp_path: Path,
    failure: str,
) -> None:
    plan = _plan(tmp_path / failure, "VS24-F-AUDIO-CONVERT-01")
    backend = _FakeConversionBackend(plan)
    runtime = PreparedAudioConversionRuntime(
        scenario=_scenario(plan.scenario_id), plan=plan, backend=backend
    ).prepare()
    source = next(iter(backend.sources.values()))
    content = str(source["content_relative"]).replace("/", "\\")

    if failure == "traversal":
        source["reported_original"] = "temporary\\..\\" + content
    elif failure == "unmapped-drive":
        source["reported_original"] = r"Q:\SemanticLab\unreviewed.wav"
    elif failure == "absolute-escape":
        outside = plan.sandbox_root.parent / "escaped-original.wav"
        shutil.copyfile(source["original"], outside)
        source["reported_original"] = str(outside.resolve())
    elif failure == "original-mismatch":
        source["reported_original"] = str(
            Path(source["content_relative"]).with_name("wrong.wav")
        ).replace("/", "\\")
    elif failure == "relative-mismatch":
        source["reported_relative"] = str(
            Path(source["relative"]).with_name("wrong.wav")
        ).replace("/", "\\")
    else:
        source["reported_relative"] = ""

    with pytest.raises(AudioConversionRuntimeError):
        runtime.snapshot()


@pytest.mark.parametrize(
    "reported",
    (
        r"relative\cache.wem",
        r"Q:\unreviewed\cache.wem",
        r"Z:\temporary\..\cache.wem",
    ),
)
def test_snapshot_rejects_relative_unmapped_or_traversing_converted_paths(
    tmp_path: Path,
    reported: str,
) -> None:
    plan = _plan(tmp_path, "VS24-F-AUDIO-CONVERT-01")
    backend = _FakeConversionBackend(plan)
    runtime = PreparedAudioConversionRuntime(
        scenario=_scenario(plan.scenario_id), plan=plan, backend=backend
    ).prepare()
    source = next(iter(backend.sources.values()))
    platform = next(iter(source["converted"]))
    source["reported_converted"] = {platform: reported}

    with pytest.raises(AudioConversionRuntimeError):
        runtime.snapshot()


def _preset_for(
    plan, binding, platform: str, *, initial: bool
) -> tuple[str, str, str, str, int]:
    settings = dict(plan.initial_settings(binding.path) if initial else binding.settings_by_platform)
    key = settings[platform]
    preset = next(item for item in plan.presets if item.key == key)
    profile = plan.profile_for_settings(tuple(settings.items()))
    return (
        "{" + profile.key + "}",
        profile.name,
        key,
        preset.codec,
        preset.sample_rate,
    )


def _artifact_matrix(plan, *, phase: str) -> tuple[ConvertedArtifact, ...]:
    rows: list[ConvertedArtifact] = []
    for object_index, binding in enumerate(plan.bindings, start=1):
        for language_index, (language, source_key) in enumerate(
            binding.source_keys_by_language, start=1
        ):
            for platform_index, platform in enumerate(plan.platforms, start=1):
                slot = (binding.path, platform, language)
                conversion_id, conversion_name, key, codec, sample_rate = _preset_for(
                    plan, binding, platform, initial=phase == "baseline"
                )
                baseline_path = (
                    plan.io_root
                    / platform
                    / language
                    / f"{object_index}-{language_index}.wem"
                )
                changed_paths = {
                    item.path
                    for item in (plan.source_delta, plan.setting_delta)
                    if item is not None
                }
                path = (
                    plan.io_root
                    / "current"
                    / platform
                    / language
                    / f"{object_index}-{language_index}.wem"
                    if phase != "baseline" and binding.path in changed_paths
                    else baseline_path
                )
                baseline_hash = f"baseline-{object_index}-{language_index}-{platform_index}"
                present = True
                mtime = 100
                digest = baseline_hash
                if phase == "before":
                    present = binding.control
                    mtime = 100 if present else None
                    digest = baseline_hash if present else None
                elif phase == "after" and not binding.control:
                    mtime = 200
                    if binding.path in {
                        row.path
                        for row in (plan.source_delta, plan.setting_delta)
                        if row is not None
                    }:
                        digest = "replaced-" + baseline_hash
                rows.append(
                    ConvertedArtifact(
                        object_path=binding.path,
                        object_id=f"{{OBJECT-{object_index}}}",
                        source_id=f"{{SOURCE-{object_index}-{language_index}}}",
                        source_key=source_key,
                        platform=platform,
                        language=language,
                        conversion_id=conversion_id,
                        conversion_name=conversion_name,
                        original_path=str(
                            (
                                plan.sandbox_root
                                / "Originals"
                                / language
                                / f"{source_key}.wav"
                            ).resolve()
                        ),
                        original_file=FileState(
                            str(
                                (
                                    plan.sandbox_root
                                    / "Originals"
                                    / language
                                    / f"{source_key}.wav"
                                ).resolve()
                            ),
                            True,
                            256,
                            (
                                f"source-baseline-{object_index}-{language_index}"
                                if phase == "baseline"
                                and plan.source_delta is not None
                                and binding.path == plan.source_delta.path
                                else f"source-{object_index}-{language_index}"
                            ),
                            50,
                        ),
                        converted_path=str(path.resolve()),
                        file=FileState(
                            str(path.resolve()),
                            present,
                            128 if present else None,
                            digest,
                            mtime,
                        ),
                        codec=codec if present else None,
                        sample_rate=sample_rate if present else None,
                    )
                )
    return tuple(sorted(rows, key=lambda row: row.slot))


def _snapshot(plan, phase: str) -> AudioConversionSnapshot:
    artifacts = _artifact_matrix(plan, phase=phase)
    baseline_artifacts = _artifact_matrix(plan, phase="baseline")
    source_files = tuple(
        FileState(
            str(_source_asset_path(plan, language, key)),
            True,
            256,
            f"source-{index}",
            50,
        )
        for index, (language, key) in enumerate(
            (
                pair
                for binding in plan.bindings
                for pair in binding.source_keys_by_language
            ),
            start=1,
        )
    )
    original = FileState(str(plan.sandbox_root / "Originals" / "proof.wav"), True, 64, "original", 50)
    authoring = FileState(str(plan.sandbox_project), True, 64, "project", 50)
    conversion = FileState(
        str(plan.sandbox_root / "Conversion Settings" / "Default Work Unit.wwu"),
        True,
        64,
        "conversion-xml",
        50,
    )
    retained_objects = {item.path for item in plan.bindings if item.control}
    if plan.source_delta is not None:
        retained_objects.add(plan.source_delta.path)
    if plan.setting_delta is not None:
        retained_objects.add(plan.setting_delta.path)
    output_by_path = {
        row.converted_path: row.file
        for row in baseline_artifacts
        if phase == "baseline" or row.object_path in retained_objects
    }
    if phase == "after":
        output_by_path.update(
            {
                row.converted_path: row.file
                for row in artifacts
                if row.file.present
            }
        )
    output = tuple(output_by_path[path] for path in sorted(output_by_path))
    return AudioConversionSnapshot(
        artifacts=artifacts,
        baseline_artifacts=baseline_artifacts,
        input_files=source_files,
        originals_files=(original,),
        authoring_files=(authoring, conversion),
        conversion_xml=conversion,
        output_tree=output,
        baseline_artifact_paths=tuple(
            sorted({item.converted_path for item in baseline_artifacts})
        ),
        volatile_cache_files=tuple(
            VolatileFileState(path, False, None)
            for path in audio_conversion_volatile_cache_paths(plan.io_root)
        ),
        digest=phase,
    )


def _oracle_runtime(tmp_path: Path):
    plan = _plan(tmp_path, "VS24-F-AUDIO-CONVERT-04")
    runtime = PreparedAudioConversionRuntime(
        scenario=_scenario(plan.scenario_id), plan=plan, backend=object()
    )
    baseline = _snapshot(plan, "baseline")
    before = _snapshot(plan, "before")
    after = _snapshot(plan, "after")
    runtime._baseline = baseline.by_slot()
    runtime._profile_ids = {
        profile.key: "{" + profile.key + "}" for profile in plan.profiles
    }
    runtime.before = before
    return runtime, before, after


def test_preview_and_after_oracles_accept_the_complete_case04_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, before, after = _oracle_runtime(tmp_path)
    target_slots = {
        (path, platform, language)
        for path in runtime.plan.objects
        for platform in runtime.plan.platforms
        for language in runtime.plan.languages
    }
    runtime._validate_before_matrix(before, target_slots)

    monkeypatch.setattr(runtime, "snapshot", lambda: before)
    runtime.verify_preview_unchanged().assert_passed()
    monkeypatch.setattr(runtime, "snapshot", lambda: after)
    result = runtime.verify_after_execution(
        verify_payload=_gateway_verify_payload(runtime, {"errors": []})
    )
    result.assert_passed()
    assert result.evidence["target_slots"] == 6
    assert len(result.evidence["observed_target_paths"]) == 6


def test_preview_oracle_detects_any_snapshot_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, before, _after = _oracle_runtime(tmp_path)
    monkeypatch.setattr(runtime, "snapshot", lambda: replace(before, digest="changed"))
    result = runtime.verify_preview_unchanged()
    assert not result.passed
    assert result.failures == ("conversion fixture changed before confirmation",)


def test_after_oracle_reports_freshness_identity_control_and_result_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _before, after = _oracle_runtime(tmp_path)
    rows = list(after.artifacts)
    target_index = next(
        index
        for index, row in enumerate(rows)
        if row.object_path == runtime.plan.source_delta.path
    )
    baseline = runtime._baseline[rows[target_index].slot]
    rows[target_index] = replace(
        rows[target_index],
        conversion_id="{WRONG-CONVERSION}",
        file=replace(
            rows[target_index].file,
            sha256=baseline.file.sha256,
            mtime_ns=baseline.file.mtime_ns,
        ),
    )
    control_index = next(
        index for index, row in enumerate(rows) if row.object_path.endswith("Current_Control")
    )
    rows[control_index] = replace(
        rows[control_index], file=replace(rows[control_index].file, sha256="changed-control")
    )
    bad = replace(
        after,
        artifacts=tuple(rows),
        output_tree=tuple(row.file for row in rows if row.file.present),
    )
    monkeypatch.setattr(runtime, "snapshot", lambda: bad)
    result = runtime.verify_after_execution(
        verify_payload=_gateway_verify_payload(
            runtime,
            {"errors": [{"severity": "Fatal Error", "message": "failed"}]},
        )
    )

    assert not result.passed
    details = "\n".join(result.failures)
    assert "not freshly converted" in details
    assert "target bytes equal the sealed pre-delta baseline" in details
    assert "effective Conversion identity differs" in details
    assert "non-requested control artifact changed" in details
    assert "non-requested conversion output tree changed" in details
    assert "returned conversion errors" in details


def test_after_oracle_requires_the_gateway_verify_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _before, after = _oracle_runtime(tmp_path)
    monkeypatch.setattr(runtime, "snapshot", lambda: after)
    result = runtime.verify_after_execution()
    assert not result.passed
    assert "tested transaction verify payload was not supplied" in result.failures


def test_after_oracle_rejects_a_verify_payload_bound_to_another_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _before, after = _oracle_runtime(tmp_path)
    monkeypatch.setattr(runtime, "snapshot", lambda: after)
    payload = dict(_gateway_verify_payload(runtime, {"errors": []}))
    payload["agent_result"] = {
        **payload["agent_result"],
        "request": {"operation": "not-the-reviewed-request"},
    }
    result = runtime.verify_after_execution(verify_payload=payload)
    assert not result.passed
    assert any("not bound to the reviewed request" in row for row in result.failures)


def test_before_oracle_rejects_a_missing_control_artifact(tmp_path: Path) -> None:
    runtime, before, _after = _oracle_runtime(tmp_path)
    rows = list(before.artifacts)
    index = next(
        index for index, row in enumerate(rows) if row.object_path.endswith("Current_Control")
    )
    rows[index] = replace(
        rows[index],
        file=FileState(rows[index].converted_path, False, None, None, None),
        codec=None,
        sample_rate=None,
    )
    bad = replace(before, artifacts=tuple(rows))
    target_slots = {
        (path, platform, language)
        for path in runtime.plan.objects
        for platform in runtime.plan.platforms
        for language in runtime.plan.languages
    }
    with pytest.raises(AudioConversionRuntimeError, match="control artifact is absent"):
        runtime._validate_before_matrix(bad, target_slots)


@pytest.mark.parametrize("failure", ["source-id", "converted-path"])
def test_before_oracle_rejects_media_identity_or_output_path_reuse(
    tmp_path: Path, failure: str
) -> None:
    runtime, before, _after = _oracle_runtime(tmp_path)
    rows = list(before.artifacts)
    first_path = rows[0].object_path
    second_path = next(row.object_path for row in rows if row.object_path != first_path)
    first_source_id = rows[0].source_id
    first_converted_path = rows[0].converted_path
    for index, row in enumerate(rows):
        if row.object_path != second_path:
            continue
        if failure == "source-id":
            rows[index] = replace(row, source_id=first_source_id)
        elif row.platform == rows[0].platform and row.language == rows[0].language:
            rows[index] = replace(row, converted_path=first_converted_path)
            break
    bad = replace(before, artifacts=tuple(rows))
    target_slots = {
        (path, platform, language)
        for path in runtime.plan.objects
        for platform in runtime.plan.platforms
        for language in runtime.plan.languages
    }
    expected = (
        "reuse one media/source ID"
        if failure == "source-id"
        else "converted output path is reused"
    )
    with pytest.raises(AudioConversionRuntimeError, match=expected):
        runtime._validate_before_matrix(bad, target_slots)
