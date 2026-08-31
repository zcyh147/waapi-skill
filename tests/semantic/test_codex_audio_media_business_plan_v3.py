from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from tests.semantic.support.codex_audio_conversion_runtime_v3 import (
    AUDIO_CONVERT_URI,
    AudioConversionPlan,
    AudioConversionSnapshot,
    ConvertedArtifact,
    ConversionBinding,
    ConversionPreset,
    ConversionProfile,
    FileState,
    SourceDelta,
    VolatileFileState,
    audio_conversion_volatile_cache_paths,
    derive_conversion_profiles,
)
from tests.semantic.support.codex_audio_media_business_plan_v3 import (
    AudioMediaBusinessPlanError,
    AudioMediaBusinessPlanSections,
    _audio_snapshot_digest,
    compile_audio_conversion_business_plan,
    compile_media_pool_business_plan,
    parse_audio_media_business_plan_sections,
    validate_audio_archived_verification,
    validate_audio_conversion_business_plan,
    validate_audio_media_business_plan_archive,
    validate_media_archived_verification,
    validate_media_pool_business_plan,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_direct_protocol,
    build_operations_discovery_protocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
from tests.semantic.support.codex_media_pool_runtime_v3 import (
    REFERENCE_MATCH_RESULT_CONTRACT,
    BoundMediaPoolRequest,
    MaterializedMediaPoolCase,
    MediaAsset,
    MediaDatabaseFixture,
    MediaPoolFieldBinding,
    ParsedWav,
    SealedMediaPoolOracle,
    SealedMediaRow,
    SemanticAnswerPlan,
    StagedMediaAsset,
    StagedMediaPoolCase,
    TreeFingerprint,
)


ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"


def _audio_case(index: int, root: Path) -> tuple[AudioConversionPlan, AudioConversionSnapshot]:
    source = root / f"source-{index}.wav"
    source.write_bytes(f"source-{index}".encode())
    converted = root / f"out-{index}.wem"
    converted.write_bytes(f"wem-{index}".encode())
    state = FileState(str(source), True, source.stat().st_size, _sha(source), source.stat().st_mtime_ns)
    converted_state = FileState(str(converted), True, converted.stat().st_size, _sha(converted), converted.stat().st_mtime_ns)
    original = FileState(str(source), True, source.stat().st_size, _sha(source), source.stat().st_mtime_ns)
    preset = ConversionPreset(
        f"preset-{index}", f"Preset{index}", "PCM", 48000, 1
    )
    settings = (("Windows", preset.key),)
    profile = derive_conversion_profiles(
        scenario_id=f"VS24-F-AUDIO-CONVERT-{index:02d}",
        platforms=("Windows",),
        presets=(preset,),
        settings_maps=(settings,),
    )[0]
    baseline_artifact = ConvertedArtifact(
        object_path=rf"\Actor-Mixer Hierarchy\Default Work Unit\Plan{index}", object_id=f"{{object-{index}}}",
        source_id=f"{{source-{index}}}", source_key=f"source-{index}", platform="Windows", language="SFX",
        conversion_id=f"{{profile-{index}}}", conversion_name=profile.name, original_path=str(source),
        original_file=original, converted_path=str(converted), file=converted_state, codec="PCM", sample_rate=48000,
    )
    request = {
        "contract": "waapi-skill.operation-request/v1", "version": "2024.1", "operation": "waapi.call",
        "arguments": {"api": AUDIO_CONVERT_URI, "args": {"objects": [baseline_artifact.object_path], "platforms": ["Windows"], "languages": ["SFX"]}, "options": {}, "io_root": str(root)},
    }
    plan = AudioConversionPlan(
        scenario_id=f"VS24-F-AUDIO-CONVERT-{index:02d}", sandbox_project=root / "project.wproj", sandbox_root=root,
        asset_root=root, io_root=root, objects=(baseline_artifact.object_path,), platforms=("Windows",), languages=("SFX",),
        presets=(preset,), profiles=(profile,),
        bindings=(ConversionBinding(baseline_artifact.object_path, (("SFX", baseline_artifact.source_key),), settings, False),),
        wav_filename_pattern="{key}.wav", source_seeds_by_key=((baseline_artifact.source_key, f"seed-{index}"),),
        initial_settings_by_path=((baseline_artifact.object_path, (("Windows", f"preset-{index}"),)),), source_delta=(SourceDelta(baseline_artifact.object_path, baseline_artifact.source_key, "before", "after") if index == 4 else None),
        setting_delta=None, missing_cache_paths=(), operation_request=MappingProxyType(request), expected_output_count=1,
    )
    current_path = (
        root / "current" / converted.name if index == 4 else converted
    ).resolve()
    artifact = replace(
        baseline_artifact,
        converted_path=str(current_path),
        file=FileState(str(current_path), False, None, None, None),
        codec=None,
        sample_rate=None,
    )
    empty = FileState(str(root / "ConversionSettings.wwu"), False, None, None, None)
    snapshot = AudioConversionSnapshot(
        artifacts=(artifact,),
        baseline_artifacts=(baseline_artifact,),
        input_files=(state,),
        originals_files=(original,),
        authoring_files=(),
        conversion_xml=empty,
        output_tree=((converted_state,) if index == 4 else ()),
        baseline_artifact_paths=(str(converted.resolve()),),
        volatile_cache_files=tuple(
            VolatileFileState(path, False, None)
            for path in audio_conversion_volatile_cache_paths(root)
        ),
        digest="",
    )
    return plan, replace(snapshot, digest=_audio_snapshot_digest(snapshot))


def _media_case(index: int, root: Path, *, associations: bool = False):
    source = root / f"media-{index}.wav"
    source.write_bytes(f"media-{index}".encode())
    parsed = ParsedWav(48000, 1, 16, 100, 0.1, 200, MappingProxyType({"scene": "A"}), source.stat().st_size, _sha(source))
    from tests.semantic.support.codex_media_pool_runtime_v3 import bind_media_pool_request, fingerprint_tree
    fingerprint = fingerprint_tree(root)
    database = MediaDatabaseFixture("db", r"\Databases\Project Originals", "Project Originals", "project_originals", root)
    asset = MediaAsset("asset", "db", Path(source.name), source, parsed, ("object",) if associations else ())
    case = MaterializedMediaPoolCase(
        "waapi-skill.media-pool-fixture/v1", f"VS25-F-MEDIAPOOL-GET-{index:02d}", "2025.1", root,
        (database,), (asset,), MappingProxyType({
            "args": {"databases": [r"\Databases\Project Originals"], "filters": [{"type": "field", "field": "{media_pool_fields.name}", "operator": "equals", "value": source.stem}], "maxResults": 10},
            "options": {"return": ["Path", "FileId", "Db", "{media_pool_fields.name}"]},
        }), ("asset",), ("asset",), MappingProxyType({"all": ("asset",)}),
        MappingProxyType({"referenced": ("asset",), "unreferenced": ()}) if associations else None, fingerprint,
    )
    staged = StagedMediaPoolCase(case, root / "project.wproj", root, (StagedMediaAsset(asset, source),), fingerprint_tree(root))
    binding = MediaPoolFieldBinding(("Filename", "WAV/Duration", "WAV/Sample Rate", "WAV/Bit Depth", "WAV/Channels"), MappingProxyType({"name": "Filename", "duration": "WAV/Duration", "sample_rate": "WAV/Sample Rate", "bit_depth": "WAV/Bit Depth", "channels": "WAV/Channels"}))
    request = bind_media_pool_request(case, binding)
    row = SealedMediaRow("asset", source.name, source, "42", MappingProxyType({"id": "db-id", "name": "Project Originals"}), MappingProxyType({"Filename": source.stem}))
    answer = SemanticAnswerPlan(("asset",), MappingProxyType({"all": ("asset",)}), ("asset",) if associations else (), (), (), 10)
    return case, staged, SealedMediaPoolOracle(
        case.scenario_id,
        request,
        (row,),
        ("asset",),
        answer,
        fingerprint,
        staged.staged_fingerprint,
        ("asset",),
    )


def _audio_reviewed_fixture(plan: AudioConversionPlan) -> Mapping[str, object]:
    scenario = load_eval_bundle_v3(SUITE).scenario(plan.scenario_id)
    assert scenario.api == AUDIO_CONVERT_URI
    return scenario.fixture


def _media_reviewed_fixture(case: MaterializedMediaPoolCase) -> Mapping[str, object]:
    scenario = load_eval_bundle_v3(SUITE).scenario(case.scenario_id)
    assert scenario.api == "ak.wwise.core.mediaPool.get"
    return scenario.fixture


def _archive_identity(
    scenario_id: str,
    api: str,
    version: str,
    reviewed_scenario_fixture: Mapping[str, object],
) -> dict[str, object]:
    return {
        "scenario_id": scenario_id,
        "api": api,
        "version": version,
        "reviewed_scenario_fixture": reviewed_scenario_fixture,
    }


@pytest.mark.parametrize("index", range(1, 6))
def test_audio_all_five_cases_compile_and_recompute(index: int, tmp_path: Path) -> None:
    plan, before = _audio_case(index, tmp_path)
    protocol = build_transaction_protocol([plan.operation_request])
    reviewed_fixture = _audio_reviewed_fixture(plan)
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    validate_audio_conversion_business_plan(
        sections,
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_fixture,
        verify_files=True,
    )
    assert sections.payload_bindings["primary_steps"] == ["tx01.execute"]
    assert sections.live_binding["before_snapshot_sha256"] == before.digest
    assert sections.static_expectation["presets"] == [
        {
            "key": plan.presets[0].key,
            "name": plan.presets[0].name,
            "codec": plan.presets[0].codec,
            "sample_rate": plan.presets[0].sample_rate,
            "channels": plan.presets[0].channels,
        }
    ]
    assert sections.static_expectation["profiles"] == [
        {
            "key": plan.profiles[0].key,
            "name": plan.profiles[0].name,
            "components_by_platform": [["Windows", plan.presets[0].key]],
        }
    ]


def test_audio_plan_accepts_optional_named_operation_discovery(
    tmp_path: Path,
) -> None:
    plan, before = _audio_case(3, tmp_path)
    protocol = build_operations_discovery_protocol(
        build_transaction_protocol([plan.operation_request])
    )
    reviewed_fixture = _audio_reviewed_fixture(plan)

    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    validate_audio_conversion_business_plan(
        sections,
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_fixture,
        verify_files=True,
    )
    validate_audio_media_business_plan_archive(
        sections,
        protocol,
        **_archive_identity(
            plan.scenario_id,
            AUDIO_CONVERT_URI,
            "2024.1",
            reviewed_fixture,
        ),
    )


@pytest.mark.parametrize("index", range(1, 6))
def test_media_all_five_cases_compile_and_recompute(index: int, tmp_path: Path) -> None:
    case, staged, oracle = _media_case(index, tmp_path, associations=index == 4)
    from tests.semantic.support.codex_audio_media_business_plan_v3 import _expected_media_protocol
    protocol = _expected_media_protocol(case, oracle)
    digest = "a" * 64
    reviewed_fixture = _media_reviewed_fixture(case)
    sections = compile_media_pool_business_plan(
        case,
        staged,
        oracle,
        protocol,
        project_digest=digest,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    validate_media_pool_business_plan(
        sections,
        case,
        staged,
        oracle,
        protocol,
        project_digest=digest,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    assert sections.payload_bindings["primary_steps"] == ["media.get"]
    assert "media.get-fields" in sections.payload_bindings["verification_steps"]
    if index == 4:
        reference_step = protocol.steps[-1]
        assert reference_step.name == "media.audio-sources"
        assert reference_step.arguments == (
            "--type",
            "AudioFileSource",
            "--take",
            "1000",
            "--match-original-file-path",
            oracle.row("asset").path,
        )
        assert "--return-field" not in reference_step.arguments


def test_audio_rejects_tampered_request_slot_source_before_and_delta(tmp_path: Path) -> None:
    plan, before = _audio_case(1, tmp_path)
    protocol = build_transaction_protocol([plan.operation_request])
    reviewed_fixture = _audio_reviewed_fixture(plan)
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    for field, value in (
        ("static_expectation", {**sections.static_expectation, "operation_request_sha256": "0" * 64}),
        ("live_binding", {**sections.live_binding, "target_slots": [["wrong", "Windows", "SFX"]]}),
        ("live_binding", {**sections.live_binding, "source_files": [{**sections.live_binding["source_files"][0], "sha256": "0" * 64}]}),
        ("live_binding", {**sections.live_binding, "before_snapshot_sha256": "0" * 64}),
        ("delta_rules", (MappingProxyType({"enum": "audio.preview_only"}),)),
    ):
        with pytest.raises(AudioMediaBusinessPlanError):
            validate_audio_conversion_business_plan(
                replace(sections, **{field: MappingProxyType(value) if isinstance(value, dict) else value}),
                plan,
                before,
                protocol,
                reviewed_scenario_fixture=reviewed_fixture,
            )


def test_audio_rejects_preview_only_protocol_and_noop_stale_output(tmp_path: Path) -> None:
    plan, before = _audio_case(4, tmp_path)
    reviewed_fixture = _audio_reviewed_fixture(plan)
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        build_transaction_protocol([plan.operation_request]),
        reviewed_scenario_fixture=reviewed_fixture,
    )
    complete = build_transaction_protocol([plan.operation_request])
    preview_only = build_direct_protocol([complete.steps[1]])
    with pytest.raises(AudioMediaBusinessPlanError, match="protocol"):
        validate_audio_conversion_business_plan(
            sections,
            plan,
            before,
            preview_only,
            reviewed_scenario_fixture=reviewed_fixture,
        )
    # A stale/missing-output case may not silently omit its byte-change delta.
    no_op = dict(sections.delta_rules[0]); no_op["required_sha_change_slots"] = []
    with pytest.raises(AudioMediaBusinessPlanError):
        validate_audio_conversion_business_plan(
            replace(sections, delta_rules=(MappingProxyType(no_op),)),
            plan,
            before,
            build_transaction_protocol([plan.operation_request]),
            reviewed_scenario_fixture=reviewed_fixture,
        )


def test_audio_compiler_binds_one_composite_profile_and_platform_components(
    tmp_path: Path,
) -> None:
    plan, before = _audio_case(1, tmp_path)
    mac_preset = ConversionPreset(
        "mac-preset", "MacPreset", "Vorbis", 48_000, 1
    )
    settings = (
        ("Windows", plan.presets[0].key),
        ("Mac", mac_preset.key),
    )
    profile = derive_conversion_profiles(
        scenario_id=plan.scenario_id,
        platforms=("Windows", "Mac"),
        presets=(*plan.presets, mac_preset),
        settings_maps=(settings,),
    )[0]
    first = replace(
        before.artifacts[0],
        conversion_id="{composite-profile}",
        conversion_name=profile.name,
    )
    baseline_first = replace(
        before.baseline_artifacts[0],
        conversion_id="{composite-profile}",
        conversion_name=profile.name,
    )
    mac_path = tmp_path / "mac.wem"
    mac_path.write_bytes(b"mac-vorbis-output")
    mac_state = FileState(
        str(mac_path),
        True,
        mac_path.stat().st_size,
        _sha(mac_path),
        mac_path.stat().st_mtime_ns,
    )
    mac = replace(
        first,
        platform="Mac",
        converted_path=str(mac_path),
        file=FileState(str(mac_path), False, None, None, None),
        codec=None,
        sample_rate=None,
    )
    baseline_mac = replace(
        baseline_first,
        platform="Mac",
        converted_path=str(mac_path),
        file=mac_state,
        codec=mac_preset.codec,
        sample_rate=mac_preset.sample_rate,
    )
    request = _json_clone(plan.operation_request)
    request["arguments"]["args"]["platforms"] = ["Windows", "Mac"]
    binding = replace(
        plan.bindings[0],
        settings_by_platform=settings,
    )
    plan = replace(
        plan,
        platforms=("Windows", "Mac"),
        presets=(*plan.presets, mac_preset),
        profiles=(profile,),
        bindings=(binding,),
        initial_settings_by_path=(
            (
                first.object_path,
                settings,
            ),
        ),
        operation_request=MappingProxyType(request),
        expected_output_count=2,
    )
    before = replace(
        before,
        artifacts=(first, mac),
        baseline_artifacts=(baseline_first, baseline_mac),
        output_tree=(),
        baseline_artifact_paths=tuple(
            sorted((*before.baseline_artifact_paths, str(mac_path.resolve())))
        ),
        digest="",
    )
    before = replace(before, digest=_audio_snapshot_digest(before))

    protocol = build_transaction_protocol([plan.operation_request])
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=_audio_reviewed_fixture(plan),
    )
    assert sections.static_expectation["profiles"] == [
        {
            "key": profile.key,
            "name": profile.name,
            "components_by_platform": [
                ["Windows", plan.presets[0].key],
                ["Mac", mac_preset.key],
            ],
        }
    ]

    shared_alias = replace(mac, converted_path=first.converted_path, file=first.file)
    wrong_profile = replace(mac, conversion_id="{different-profile}")
    for artifact, message in (
        (shared_alias, "reuses a converted cache alias"),
        (wrong_profile, "global Conversion ShareSet"),
    ):
        tampered = replace(before, artifacts=(first, artifact), digest="")
        tampered = replace(tampered, digest=_audio_snapshot_digest(tampered))
        with pytest.raises(AudioMediaBusinessPlanError, match=message):
            compile_audio_conversion_business_plan(
                plan,
                tampered,
                protocol,
                reviewed_scenario_fixture=_audio_reviewed_fixture(plan),
            )

    wrong_baseline_component = replace(baseline_mac, codec="PCM")
    tampered = replace(
        before,
        baseline_artifacts=(baseline_first, wrong_baseline_component),
        digest="",
    )
    tampered = replace(tampered, digest=_audio_snapshot_digest(tampered))
    with pytest.raises(AudioMediaBusinessPlanError, match="baseline artifact proof"):
        compile_audio_conversion_business_plan(
            plan,
            tampered,
            protocol,
            reviewed_scenario_fixture=_audio_reviewed_fixture(plan),
        )

    validate_audio_conversion_business_plan(
        sections,
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=_audio_reviewed_fixture(plan),
    )


def test_audio_compiler_rejects_profile_component_provenance_tamper(
    tmp_path: Path,
) -> None:
    plan, before = _audio_case(1, tmp_path)
    forged_profile = ConversionProfile(
        key=plan.profiles[0].key,
        name=plan.profiles[0].name,
        components_by_platform=(("Windows", "forged-component"),),
    )
    forged = replace(plan, profiles=(forged_profile,))
    with pytest.raises(AudioMediaBusinessPlanError, match="profile provenance"):
        compile_audio_conversion_business_plan(
            forged,
            before,
            build_transaction_protocol([forged.operation_request]),
            reviewed_scenario_fixture=_audio_reviewed_fixture(forged),
        )


def test_audio_compiler_and_archive_allow_same_sound_equal_format_platform_alias(
    tmp_path: Path,
) -> None:
    plan, before = _audio_case(1, tmp_path)
    mac_component = ConversionPreset(
        "mac-equal-pcm", "MacEqualPCM", "PCM", 48_000, 1
    )
    settings = (
        ("Windows", plan.presets[0].key),
        ("Mac", mac_component.key),
    )
    profile = derive_conversion_profiles(
        scenario_id=plan.scenario_id,
        platforms=("Windows", "Mac"),
        presets=(*plan.presets, mac_component),
        settings_maps=(settings,),
    )[0]
    first = replace(
        before.artifacts[0],
        conversion_id="{equal-format-profile}",
        conversion_name=profile.name,
    )
    mac = replace(first, platform="Mac")
    baseline_first = replace(
        before.baseline_artifacts[0],
        conversion_id="{equal-format-profile}",
        conversion_name=profile.name,
    )
    baseline_mac = replace(baseline_first, platform="Mac")
    request = _json_clone(plan.operation_request)
    request["arguments"]["args"]["platforms"] = ["Windows", "Mac"]
    plan = replace(
        plan,
        platforms=("Windows", "Mac"),
        presets=(*plan.presets, mac_component),
        profiles=(profile,),
        bindings=(replace(plan.bindings[0], settings_by_platform=settings),),
        initial_settings_by_path=((first.object_path, settings),),
        operation_request=MappingProxyType(request),
        expected_output_count=2,
    )
    before = replace(
        before,
        artifacts=(first, mac),
        baseline_artifacts=(baseline_first, baseline_mac),
        digest="",
    )
    before = replace(before, digest=_audio_snapshot_digest(before))
    protocol = build_transaction_protocol([plan.operation_request])
    reviewed_fixture = _audio_reviewed_fixture(plan)
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    validate_audio_conversion_business_plan(
        sections,
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    validate_audio_media_business_plan_archive(
        sections,
        protocol,
        **_archive_identity(
            plan.scenario_id,
            AUDIO_CONVERT_URI,
            "2024.1",
            reviewed_fixture,
        ),
    )


def test_media_rejects_wrong_field_request_empty_association_and_cross_api(tmp_path: Path) -> None:
    case, staged, oracle = _media_case(4, tmp_path, associations=True)
    from tests.semantic.support.codex_audio_media_business_plan_v3 import _expected_media_protocol
    protocol = _expected_media_protocol(case, oracle)
    digest = "a" * 64
    reviewed_fixture = _media_reviewed_fixture(case)
    sections = compile_media_pool_business_plan(
        case,
        staged,
        oracle,
        protocol,
        project_digest=digest,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    with pytest.raises(AudioMediaBusinessPlanError):
        validate_media_pool_business_plan(
            replace(sections, live_binding=MappingProxyType({**sections.live_binding, "request_sha256": "0" * 64})),
            case,
            staged,
            oracle,
            protocol,
            project_digest=digest,
            reviewed_scenario_fixture=reviewed_fixture,
        )
    empty_case = replace(case, association_expectations=MappingProxyType({}))
    with pytest.raises(AudioMediaBusinessPlanError, match="association"):
        compile_media_pool_business_plan(
            empty_case,
            replace(staged, materialized=empty_case),
            oracle,
            protocol,
            project_digest=digest,
            reviewed_scenario_fixture=_media_reviewed_fixture(empty_case),
        )
    (tmp_path / "audio").mkdir(exist_ok=True)
    audio_plan, audio_before = _audio_case(1, tmp_path / "audio")
    with pytest.raises(AudioMediaBusinessPlanError):
        validate_audio_conversion_business_plan(
            sections,
            audio_plan,
            audio_before,
            build_transaction_protocol([audio_plan.operation_request]),
            reviewed_scenario_fixture=_audio_reviewed_fixture(audio_plan),
        )


def test_persisted_sections_and_archived_verification_are_independently_bound(tmp_path: Path) -> None:
    plan, before = _audio_case(1, tmp_path)
    protocol = build_transaction_protocol([plan.operation_request])
    reviewed_fixture = _audio_reviewed_fixture(plan)
    identity = _archive_identity(
        plan.scenario_id,
        AUDIO_CONVERT_URI,
        "2024.1",
        reviewed_fixture,
    )
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    parsed = parse_audio_media_business_plan_sections(sections.writer_kwargs())
    validate_audio_media_business_plan_archive(parsed, protocol, **identity)
    before_value = parsed.live_binding["before_snapshot"]
    after_value = _materialize_audio_after(parsed)
    validate_audio_archived_verification(
        parsed,
        {
            "evidence": {
                "before": before_value,
                "after": after_value,
                "operation_request": parsed.static_expectation["operation_request"],
                "operation_request_sha256": parsed.static_expectation[
                    "operation_request_sha256"
                ],
                "target_slots": 1,
                "volatile_cache_files_before": before_value[
                    "volatile_cache_files"
                ],
                "volatile_cache_files_after": after_value[
                    "volatile_cache_files"
                ],
                "volatile_cache_changed_paths": [],
            }
        },
    )
    for field, value in (
        ("source_key", "forged-source-key"),
        ("original_path", str((tmp_path / "forged-original.wav").resolve())),
    ):
        tampered_after = _json_clone(after_value)
        tampered_after["artifacts"][0][field] = value
        _resign_archived_audio_snapshot(tampered_after)
        with pytest.raises(
            AudioMediaBusinessPlanError,
            match="identity/profile/original binding drifted",
        ):
            validate_audio_archived_verification(
                parsed,
                {
                    "evidence": _audio_verification_evidence(
                        parsed, tampered_after
                    )
                },
            )
    with pytest.raises(AudioMediaBusinessPlanError):
        parse_audio_media_business_plan_sections({**sections.writer_kwargs(), "static_expectation": {**sections.static_expectation, "extra": True}})
    with pytest.raises(AudioMediaBusinessPlanError, match="fixture kind"):
        validate_audio_media_business_plan_archive(
            replace(parsed, fixture_spec=MappingProxyType({**parsed.fixture_spec, "kind": "wrong"})),
            protocol,
            **identity,
        )
    with pytest.raises(AudioMediaBusinessPlanError, match="assertions"):
        validate_audio_media_business_plan_archive(
            replace(parsed, assertion_ids=("wrong",)),
            protocol,
            **identity,
        )
    bad_rule = dict(parsed.delta_rules[0]); bad_rule["required_refresh_slots"] = [["wrong", "Windows", "SFX"]]
    with pytest.raises(AudioMediaBusinessPlanError, match="delta"):
        validate_audio_media_business_plan_archive(
            replace(parsed, delta_rules=(MappingProxyType(bad_rule),)),
            protocol,
            **identity,
        )


def test_audio_archive_rejects_resigned_request_target_and_artifact_drift(
    tmp_path: Path,
) -> None:
    plan, before = _audio_case(1, tmp_path)
    protocol = build_transaction_protocol([plan.operation_request])
    reviewed_fixture = _audio_reviewed_fixture(plan)
    identity = _archive_identity(
        plan.scenario_id,
        AUDIO_CONVERT_URI,
        "2024.1",
        reviewed_fixture,
    )
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_fixture,
    )

    static = dict(sections.static_expectation)
    static["operation_request_sha256"] = "0" * 64
    attack = replace(
        sections,
        static_expectation=MappingProxyType(static),
        fixture_spec=MappingProxyType(
            {
                "kind": sections.fixture_spec["kind"],
                "sha256": _canonical_sha({"static": static, "live": sections.live_binding}),
            }
        ),
    )
    with pytest.raises(AudioMediaBusinessPlanError, match="operation request"):
        validate_audio_media_business_plan_archive(attack, protocol, **identity)

    static = _json_clone(sections.static_expectation)
    static["profiles"][0]["key"] = "profile-0000000000000000"
    attack = replace(
        sections,
        static_expectation=MappingProxyType(static),
        fixture_spec=MappingProxyType(
            {
                "kind": sections.fixture_spec["kind"],
                "sha256": _canonical_sha(
                    {"static": static, "live": sections.live_binding}
                ),
            }
        ),
    )
    with pytest.raises(AudioMediaBusinessPlanError, match="profile provenance"):
        validate_audio_media_business_plan_archive(attack, protocol, **identity)

    live = _json_clone(sections.live_binding)
    live["target_slots"] = [["wrong", "Windows", "SFX"]]
    attack = replace(
        sections,
        live_binding=MappingProxyType(live),
        fixture_spec=MappingProxyType(
            {
                "kind": sections.fixture_spec["kind"],
                "sha256": _canonical_sha({"static": sections.static_expectation, "live": live}),
            }
        ),
    )
    with pytest.raises(AudioMediaBusinessPlanError, match="target slots"):
        validate_audio_media_business_plan_archive(attack, protocol, **identity)

    live = _json_clone(sections.live_binding)
    live["artifact_fingerprints"][0]["object_id"] = "{WRONG}"
    attack = replace(
        sections,
        live_binding=MappingProxyType(live),
        fixture_spec=MappingProxyType(
            {
                "kind": sections.fixture_spec["kind"],
                "sha256": _canonical_sha({"static": sections.static_expectation, "live": live}),
            }
        ),
    )
    with pytest.raises(AudioMediaBusinessPlanError, match="artifact fingerprints"):
        validate_audio_media_business_plan_archive(attack, protocol, **identity)


def test_audio_archive_rejects_resigned_scenario_id_and_fixture_chain(
    tmp_path: Path,
) -> None:
    plan, before = _audio_case(2, tmp_path)
    protocol = build_transaction_protocol([plan.operation_request])
    reviewed_fixture = _audio_reviewed_fixture(plan)
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    forged_fixture = _json_clone(reviewed_fixture)
    forged_fixture["asset_spec"]["request"]["languages"] = ["SFX"]
    forged_static = _json_clone(sections.static_expectation)
    forged_static["scenario_id"] = f"{plan.scenario_id}-FORGED"
    forged_static["scenario_fixture_sha256"] = _canonical_sha(forged_fixture)
    forged = replace(
        sections,
        static_expectation=MappingProxyType(forged_static),
        fixture_spec=MappingProxyType(
            {
                "kind": sections.fixture_spec["kind"],
                "sha256": _canonical_sha(
                    {"static": forged_static, "live": sections.live_binding}
                ),
            }
        ),
    )

    with pytest.raises(AudioMediaBusinessPlanError, match="independently bound"):
        validate_audio_media_business_plan_archive(
            forged,
            protocol,
            **_archive_identity(
                plan.scenario_id,
                AUDIO_CONVERT_URI,
                "2024.1",
                reviewed_fixture,
            ),
        )


def test_audio_missing_cache_requires_refresh_but_allows_identical_bytes(
    tmp_path: Path,
) -> None:
    plan, before = _audio_case(1, tmp_path)
    plan = replace(
        plan,
        source_delta=None,
        missing_cache_paths=(plan.objects[0],),
    )
    protocol = build_transaction_protocol([plan.operation_request])
    reviewed_fixture = _audio_reviewed_fixture(plan)
    identity = _archive_identity(
        plan.scenario_id,
        AUDIO_CONVERT_URI,
        "2024.1",
        reviewed_fixture,
    )
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    assert sections.delta_rules[0]["required_sha_change_slots"] == []
    assert sections.delta_rules[0]["required_refresh_slots"] == [
        [plan.objects[0], "Windows", "SFX"]
    ]
    validate_audio_media_business_plan_archive(sections, protocol, **identity)

    unchanged_evidence = {
        "before": sections.live_binding["before_snapshot"],
        "after": sections.live_binding["before_snapshot"],
        "operation_request": sections.static_expectation["operation_request"],
        "operation_request_sha256": sections.static_expectation[
            "operation_request_sha256"
        ],
        "target_slots": sections.static_expectation["expected_output_count"],
    }
    with pytest.raises(AudioMediaBusinessPlanError, match="target output is absent"):
        validate_audio_archived_verification(sections, unchanged_evidence)


def test_audio_archive_accepts_owned_target_path_change_and_exact_volatile_delta(
    tmp_path: Path,
) -> None:
    plan, before = _audio_case(1, tmp_path)
    protocol = build_transaction_protocol([plan.operation_request])
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        protocol,
        reviewed_scenario_fixture=_audio_reviewed_fixture(plan),
    )
    after = _materialize_audio_after(sections)
    artifact = after["artifacts"][0]
    old_path = artifact["converted_path"]
    new_path = str((tmp_path / "relocated" / "converted.wem").resolve())
    artifact["converted_path"] = new_path
    artifact["file"] = {
        **artifact["file"],
        "path": new_path,
    }
    after["output_tree"] = [
        row for row in after["output_tree"] if row["path"] != old_path
    ] + [artifact["file"]]
    after["volatile_cache_files"][1] = {
        **after["volatile_cache_files"][1],
        "present": True,
        "size": 4096,
    }
    _resign_archived_audio_snapshot(after)

    validate_audio_archived_verification(
        sections,
        {"evidence": _audio_verification_evidence(sections, after)},
    )
    assert old_path != new_path


def test_audio_archive_rejects_target_path_that_was_preexisting_non_target(
    tmp_path: Path,
) -> None:
    plan, before = _audio_case(4, tmp_path)
    collision_path = before.baseline_artifacts[0].converted_path
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        build_transaction_protocol([plan.operation_request]),
        reviewed_scenario_fixture=_audio_reviewed_fixture(plan),
    )
    after = _materialize_audio_after(sections)
    artifact = after["artifacts"][0]
    old_current_path = artifact["converted_path"]
    artifact["converted_path"] = collision_path
    artifact["file"] = {
        "path": collision_path,
        "present": True,
        "size": 32,
        "sha256": "d" * 64,
        "mtime_ns": before.baseline_artifacts[0].file.mtime_ns + 1,
    }
    artifact["codec"] = "PCM"
    artifact["sample_rate"] = 48_000
    after["output_tree"] = [
        row for row in after["output_tree"] if row["path"] != old_current_path
    ]
    after["output_tree"] = [
        artifact["file"] if row["path"] == collision_path else row
        for row in after["output_tree"]
    ]
    _resign_archived_audio_snapshot(after)

    with pytest.raises(
        AudioMediaBusinessPlanError,
        match="baseline|collides with pre-existing non-target output",
    ):
        validate_audio_archived_verification(
            sections,
            {"evidence": _audio_verification_evidence(sections, after)},
        )


def test_audio_compiler_rejects_preexisting_unbound_stable_output(
    tmp_path: Path,
) -> None:
    plan, before = _audio_case(1, tmp_path)
    unbound = FileState(
        str((tmp_path / "cache" / "LMDB" / "unexpected.mdb").resolve()),
        True,
        16,
        "f" * 64,
        2,
    )
    before = replace(
        before,
        output_tree=(*before.output_tree, unbound),
        digest="",
    )
    before = replace(before, digest=_audio_snapshot_digest(before))

    with pytest.raises(
        AudioMediaBusinessPlanError,
        match="retained baseline tree",
    ):
        compile_audio_conversion_business_plan(
            plan,
            before,
            build_transaction_protocol([plan.operation_request]),
            reviewed_scenario_fixture=_audio_reviewed_fixture(plan),
        )


def test_audio_case05_archive_rejects_reused_same_basename_target_bytes(
    tmp_path: Path,
) -> None:
    plan, before = _audio_case(5, tmp_path)
    first = before.artifacts[0]
    second_path = first.object_path + "_Second"
    second_file_path = str((tmp_path / "out-5-second.wem").resolve())
    second_file = FileState(second_file_path, True, 32, "b" * 64, 10)
    second = replace(
        first,
        object_path=second_path,
        object_id="{object-5-second}",
        source_id="{source-5-second}",
        source_key="source-5-second",
        converted_path=second_file_path,
        file=FileState(second_file_path, False, None, None, None),
        codec=None,
        sample_rate=None,
    )
    baseline_second = replace(
        before.baseline_artifacts[0],
        object_path=second_path,
        object_id="{object-5-second}",
        source_id="{source-5-second}",
        source_key="source-5-second",
        converted_path=second_file_path,
        file=second_file,
    )
    request = _json_clone(plan.operation_request)
    request["arguments"]["args"]["objects"] = [first.object_path, second_path]
    plan = replace(
        plan,
        objects=(first.object_path, second_path),
        bindings=(
            *plan.bindings,
            ConversionBinding(
                second_path,
                (("SFX", second.source_key),),
                plan.bindings[0].settings_by_platform,
                False,
            ),
        ),
        initial_settings_by_path=(
            *plan.initial_settings_by_path,
            (second_path, plan.bindings[0].settings_by_platform),
        ),
        operation_request=MappingProxyType(request),
        expected_output_count=2,
    )
    before = replace(
        before,
        artifacts=(first, second),
        baseline_artifacts=(*before.baseline_artifacts, baseline_second),
        output_tree=(),
        baseline_artifact_paths=tuple(
            sorted((*before.baseline_artifact_paths, second_file_path))
        ),
        digest="",
    )
    before = replace(before, digest=_audio_snapshot_digest(before))
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        build_transaction_protocol([plan.operation_request]),
        reviewed_scenario_fixture=_audio_reviewed_fixture(plan),
    )
    after = _materialize_audio_after(sections)
    shared_hash = after["artifacts"][0]["file"]["sha256"]
    for artifact in after["artifacts"]:
        artifact["file"]["sha256"] = shared_hash
    after["output_tree"] = [artifact["file"] for artifact in after["artifacts"]]
    _resign_archived_audio_snapshot(after)

    with pytest.raises(
        AudioMediaBusinessPlanError,
        match="same-basename conversion targets reused output bytes",
    ):
        validate_audio_archived_verification(
            sections,
            {"evidence": _audio_verification_evidence(sections, after)},
        )


@pytest.mark.parametrize(
    "extra_relative",
    ("Windows/SFX/unbound-extra.wem", "cache/LMDB/unexpected.mdb"),
)
def test_audio_archive_rejects_unbound_stable_output_file(
    tmp_path: Path,
    extra_relative: str,
) -> None:
    plan, before = _audio_case(1, tmp_path)
    sections = compile_audio_conversion_business_plan(
        plan,
        before,
        build_transaction_protocol([plan.operation_request]),
        reviewed_scenario_fixture=_audio_reviewed_fixture(plan),
    )
    after = _materialize_audio_after(sections)
    after["output_tree"].append(
        {
            "path": str((tmp_path / extra_relative).resolve()),
            "present": True,
            "size": 16,
            "sha256": "f" * 64,
            "mtime_ns": 2,
        }
    )
    _resign_archived_audio_snapshot(after)

    with pytest.raises(
        AudioMediaBusinessPlanError,
        match="non-target output tree changed",
    ):
        validate_audio_archived_verification(
            sections,
            {"evidence": _audio_verification_evidence(sections, after)},
        )


def test_media_archived_verification_binds_rows_request_and_project_digest(tmp_path: Path) -> None:
    case, staged, oracle = _media_case(1, tmp_path)
    from tests.semantic.support.codex_audio_media_business_plan_v3 import _expected_media_protocol
    protocol = _expected_media_protocol(case, oracle)
    reviewed_fixture = _media_reviewed_fixture(case)
    identity = _archive_identity(
        case.scenario_id,
        "ak.wwise.core.mediaPool.get",
        "2025.1",
        reviewed_fixture,
    )
    sections = compile_media_pool_business_plan(
        case,
        staged,
        oracle,
        protocol,
        project_digest="a" * 64,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    validate_audio_media_business_plan_archive(sections, protocol, **identity)
    sealed = {
        "rows": sections.live_binding["sealed_rows"],
        "request": sections.live_binding["request"],
        "candidate_keys": sections.live_binding["candidate_keys"],
        "expected_keys": sections.live_binding["expected_keys"],
    }
    evidence = {"sealed_oracle": sealed, "project_digest_before": "a" * 64, "project_digest_after": "a" * 64, "source_fingerprint_after": sections.live_binding["source_fingerprint"]}
    validate_media_archived_verification(sections, evidence)
    with pytest.raises(AudioMediaBusinessPlanError):
        validate_media_archived_verification(sections, {**evidence, "project_digest_after": "b" * 64})
    bad_rule = dict(sections.delta_rules[0]); bad_rule["project_digest_before"] = "b" * 64
    with pytest.raises(AudioMediaBusinessPlanError, match="delta"):
        validate_audio_media_business_plan_archive(
            replace(sections, delta_rules=(MappingProxyType(bad_rule),)),
            protocol,
            **identity,
        )


def test_media_association_archive_binds_compact_reference_match_result(
    tmp_path: Path,
) -> None:
    case, staged, oracle = _media_case(4, tmp_path, associations=True)
    from tests.semantic.support.codex_audio_media_business_plan_v3 import _expected_media_protocol

    protocol = _expected_media_protocol(case, oracle)
    reviewed_fixture = _media_reviewed_fixture(case)
    sections = compile_media_pool_business_plan(
        case,
        staged,
        oracle,
        protocol,
        project_digest="a" * 64,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    validate_audio_media_business_plan_archive(
        sections,
        protocol,
        **_archive_identity(
            case.scenario_id,
            "ak.wwise.core.mediaPool.get",
            "2025.1",
            reviewed_fixture,
        ),
    )
    compact_result = {
        "contract": REFERENCE_MATCH_RESULT_CONTRACT,
        "scanned_audio_source_count": 1,
        "scan_limit": 1000,
        "scan_complete": True,
        "candidates": [
            {
                "originalFilePath": oracle.row("asset").path,
                "classification": "referenced",
                "reference_count": 1,
                "references": [
                    {
                        "id": "{00000000-0000-0000-0000-000000000001}",
                        "path": r"object\AudioFileSource",
                    }
                ],
                "references_truncated": False,
            }
        ],
    }
    sealed = {
        "rows": sections.live_binding["sealed_rows"],
        "request": sections.live_binding["request"],
        "candidate_keys": sections.live_binding["candidate_keys"],
        "expected_keys": sections.live_binding["expected_keys"],
    }
    evidence = {
        "sealed_oracle": sealed,
        "project_digest_before": "a" * 64,
        "project_digest_after": "a" * 64,
        "source_fingerprint_after": sections.live_binding["source_fingerprint"],
        "model_reference_result": compact_result,
        "supporting_association_read": True,
    }
    validate_media_archived_verification(sections, evidence)

    old_broad_shape = {**evidence, "model_reference_result": {"return": []}}
    with pytest.raises(
        AudioMediaBusinessPlanError,
        match="compact reference match result drifted",
    ):
        validate_media_archived_verification(sections, old_broad_shape)

    truncated_result = _json_clone(compact_result)
    truncated_result["candidates"][0]["references_truncated"] = True
    with pytest.raises(
        AudioMediaBusinessPlanError,
        match="compact reference match result drifted",
    ):
        validate_media_archived_verification(
            sections,
            {**evidence, "model_reference_result": truncated_result},
        )


def test_media_archive_rejects_resigned_scenario_id_and_fixture_chain(
    tmp_path: Path,
) -> None:
    case, staged, oracle = _media_case(3, tmp_path)
    from tests.semantic.support.codex_audio_media_business_plan_v3 import _expected_media_protocol
    protocol = _expected_media_protocol(case, oracle)
    reviewed_fixture = _media_reviewed_fixture(case)
    sections = compile_media_pool_business_plan(
        case,
        staged,
        oracle,
        protocol,
        project_digest="a" * 64,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    forged_fixture = _json_clone(reviewed_fixture)
    forged_fixture["asset_spec"]["expected_file_keys"] = ["forged"]
    forged_static = _json_clone(sections.static_expectation)
    forged_static["scenario_id"] = f"{case.scenario_id}-FORGED"
    forged_static["scenario_fixture_sha256"] = _canonical_sha(forged_fixture)
    forged = replace(
        sections,
        static_expectation=MappingProxyType(forged_static),
        fixture_spec=MappingProxyType(
            {
                "kind": sections.fixture_spec["kind"],
                "sha256": _canonical_sha(
                    {"static": forged_static, "live": sections.live_binding}
                ),
            }
        ),
    )

    with pytest.raises(AudioMediaBusinessPlanError, match="independently bound"):
        validate_audio_media_business_plan_archive(
            forged,
            protocol,
            **_archive_identity(
                case.scenario_id,
                "ak.wwise.core.mediaPool.get",
                "2025.1",
                reviewed_fixture,
            ),
        )


def test_media_archive_rejects_candidate_business_and_post_filter_tampering(
    tmp_path: Path,
) -> None:
    from tests.semantic.support.codex_audio_media_business_plan_v3 import (
        _expected_media_protocol,
    )
    from tests.semantic.test_codex_media_pool_runtime_v3 import _sealed_case01

    _runtime, staged, oracle = _sealed_case01(tmp_path / "case01")
    case = staged.materialized
    protocol = _expected_media_protocol(case, oracle)
    reviewed_fixture = _media_reviewed_fixture(case)
    identity = _archive_identity(
        case.scenario_id,
        "ak.wwise.core.mediaPool.get",
        "2025.1",
        reviewed_fixture,
    )
    sections = compile_media_pool_business_plan(
        case,
        staged,
        oracle,
        protocol,
        project_digest="a" * 64,
        reviewed_scenario_fixture=reviewed_fixture,
    )
    validate_audio_media_business_plan_archive(sections, protocol, **identity)

    candidates = _json_clone(sections.live_binding)
    candidates["candidate_keys"] = candidates["candidate_keys"][:-1]
    with pytest.raises(
        AudioMediaBusinessPlanError,
        match="candidate/business request binding drifted",
    ):
        validate_audio_media_business_plan_archive(
            replace(sections, live_binding=MappingProxyType(candidates)),
            protocol,
            **identity,
        )

    business = _json_clone(sections.live_binding)
    business["expected_keys"].append("uppercase_name_decoy")
    with pytest.raises(
        AudioMediaBusinessPlanError,
        match="candidate/business request binding drifted",
    ):
        validate_audio_media_business_plan_archive(
            replace(sections, live_binding=MappingProxyType(business)),
            protocol,
            **identity,
        )

    filtered = _json_clone(sections.live_binding)
    filtered["request"]["post_filter"]["value"] = "Footstep"
    filtered["request_sha256"] = _canonical_sha(
        {
            "args": filtered["request"]["args"],
            "options": filtered["request"]["options"],
            "post_filter": filtered["request"]["post_filter"],
        }
    )
    with pytest.raises(
        AudioMediaBusinessPlanError,
        match="candidate/business request binding drifted",
    ):
        validate_audio_media_business_plan_archive(
            replace(sections, live_binding=MappingProxyType(filtered)),
            protocol,
            **identity,
        )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resign_archived_audio_snapshot(snapshot: dict[str, object]) -> None:
    snapshot["digest"] = _canonical_sha(
        {
            "artifacts": snapshot["artifacts"],
            "baseline_artifacts": snapshot["baseline_artifacts"],
            "inputs": snapshot["input_files"],
            "originals": snapshot["originals_files"],
            "authoring_files": snapshot["authoring_files"],
            "conversion_xml": snapshot["conversion_xml"],
            "output_tree": snapshot["output_tree"],
            "baseline_artifact_paths": snapshot["baseline_artifact_paths"],
        }
    )


def _materialize_audio_after(
    sections: AudioMediaBusinessPlanSections,
) -> dict[str, object]:
    after = _json_clone(sections.live_binding["before_snapshot"])
    baseline_by_slot = {
        (row["object_path"], row["platform"], row["language"]): row
        for row in after["baseline_artifacts"]
    }
    output_by_path = {row["path"]: row for row in after["output_tree"]}
    target_slots = {tuple(row) for row in sections.delta_rules[0]["target_slots"]}
    for artifact in after["artifacts"]:
        slot = (
            artifact["object_path"],
            artifact["platform"],
            artifact["language"],
        )
        if slot not in target_slots:
            continue
        baseline = baseline_by_slot[slot]
        converted_path = artifact["converted_path"]
        file_state = {
            "path": converted_path,
            "present": True,
            "size": baseline["file"]["size"] + 1,
            "sha256": hashlib.sha256(
                ("after:" + "\0".join(slot)).encode("utf-8")
            ).hexdigest(),
            "mtime_ns": baseline["file"]["mtime_ns"] + 1,
        }
        artifact["file"] = file_state
        artifact["codec"] = baseline["codec"]
        artifact["sample_rate"] = baseline["sample_rate"]
        output_by_path[converted_path] = file_state
    after["output_tree"] = [output_by_path[path] for path in sorted(output_by_path)]
    _resign_archived_audio_snapshot(after)
    return after


def _audio_verification_evidence(
    sections: AudioMediaBusinessPlanSections,
    after: Mapping[str, object],
) -> dict[str, object]:
    before = sections.live_binding["before_snapshot"]
    before_volatile = before["volatile_cache_files"]
    after_volatile = after["volatile_cache_files"]
    return {
        "before": before,
        "after": after,
        "operation_request": sections.static_expectation["operation_request"],
        "operation_request_sha256": sections.static_expectation[
            "operation_request_sha256"
        ],
        "target_slots": sections.static_expectation["expected_output_count"],
        "volatile_cache_files_before": before_volatile,
        "volatile_cache_files_after": after_volatile,
        "volatile_cache_changed_paths": [
            current["path"]
            for previous, current in zip(
                before_volatile,
                after_volatile,
                strict=True,
            )
            if previous != current
        ],
    }


def _canonical_sha(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda item: dict(item) if isinstance(item, Mapping) else str(item),
        ).encode("utf-8")
    ).hexdigest()


def _json_clone(value):
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            default=lambda item: dict(item) if isinstance(item, Mapping) else str(item),
        )
    )
