from __future__ import annotations

import hashlib
import json
import os
import struct
import uuid
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Mapping

import pytest

from tests.support.platform_filesystem import create_symlink_or_skip
from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic.support import codex_heavy_project_runner_v3 as heavy_runner
from tests.semantic.support.codex_audio_media_business_plan_v3 import (
    AudioMediaBusinessPlanError,
    _expected_media_protocol,
    compile_media_pool_business_plan,
    validate_media_pool_business_plan,
)
from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
from tests.semantic.support.codex_media_pool_runtime_v3 import (
    CUSTOM_DATABASE_CLEANUP_CONTRACT,
    MEDIA_POOL_CASE_IDS,
    MEDIA_POOL_CANONICAL_RETURN_FIELDS,
    REFERENCE_MATCH_RESULT_CONTRACT,
    OBJECT_DELETE_URI,
    OBJECT_GET_URI,
    OBJECT_SET_URI,
    STANDARD_FIELDS,
    SUPPORTED_BUILD,
    USER_DATABASES_PATH,
    WINE_C_DRIVE_TARGET,
    WINE_Z_DRIVE_TARGET,
    BoundMediaPoolRequest,
    CustomDatabaseCleanupProof,
    CustomDatabaseIsolation,
    CustomDatabaseRoundTripProof,
    MacOSWineCustomDatabaseHost,
    NativeWindowsCustomDatabaseHost,
    MediaPoolRuntimeError,
    apply_media_pool_post_filter,
    bind_media_pool_fields,
    bind_media_pool_request,
    build_custom_database_delete_calls,
    build_index_probe_calls,
    build_reference_fixture_call,
    build_reference_match_gateway_argv,
    build_reference_read_call,
    custom_database_payload_shape_sha256,
    custom_database_round_trip_evidence,
    expected_macos_wine_prefix,
    fingerprint_tree,
    host_directory_to_wine_z_path,
    materialize_media_pool_case,
    media_pool_preflight,
    parse_custom_database_create_results,
    parse_pcm_ixml_wav,
    resolve_macos_wine_y_drive_root,
    reference_match_paths,
    seal_media_pool_index,
    stage_media_pool_case,
    validate_macos_wine_prefix,
    verify_custom_database_cleanup,
    verify_media_pool_result,
    verify_media_pool_read_unchanged,
    verify_media_pool_candidate_result,
    verify_reference_associations,
    verify_reference_match_result,
    verify_semantic_report,
    _compile_native_windows_owned_directory,
    _parse_native_windows_absolute_path,
    _typed_audio_import_path,
)


def _plain(value):
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_V3 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"
QUERY_REFERENCE = REPO_ROOT / "skills" / "waapi-skill" / "references" / "waapi-query.md"


def _scenarios():
    bundle = load_eval_bundle_v3(SUITE_V3)
    return [bundle.scenario(case_id) for case_id in MEDIA_POOL_CASE_IDS]


def _materialize_all(tmp_path: Path):
    return {
        scenario.id: materialize_media_pool_case(
            scenario,
            asset_root=tmp_path / scenario.id,
        )
        for scenario in _scenarios()
    }


def _stage(case, tmp_path: Path):
    owned = case.asset_root.parents[1]
    project_root = owned / "sandbox" / "SampleProject"
    project_root.mkdir(parents=True, exist_ok=True)
    project = project_root / "SampleProject.wproj"
    project.write_text("<Project/>\n", encoding="utf-8")
    source = tmp_path / "immutable-source"
    source.mkdir(parents=True)
    (source / "SampleProject.wproj").write_text("<Project/>\n", encoding="utf-8")
    return stage_media_pool_case(
        case,
        sandbox_project=project,
        immutable_source_root=source,
        owned_root=owned,
    )


def _fields(*, ixml: bool = False) -> list[str]:
    result = list(STANDARD_FIELDS.values())
    if ixml:
        result.extend(["BWFXML/USER/SCENE", "BWFXML/USER/TAKE"])
    return result


def _public_request(tmp_path: Path, index: int, *, ixml: bool = False):
    scenario = _scenarios()[index]
    case = materialize_media_pool_case(
        scenario,
        asset_root=tmp_path / f"case-{index}",
    )
    request = bind_media_pool_request(
        case,
        bind_media_pool_fields(case, _fields(ixml=ixml)),
    )
    return (
        scenario,
        _plain(request.args),
        _plain(request.options),
        (
            None
            if request.post_filter is None
            else _plain(request.post_filter)
        ),
    )


def _assert_public_media_mapping_is_documented() -> None:
    text = " ".join(QUERY_REFERENCE.read_text(encoding="utf-8").split())
    for required in (
        "Do not run `describe` or `capabilities`",
        '`{"type":"field","field":<bound field>,"operator":<operator>,"value":<value>}`',
        "Preserve database and predicate order",
        "add `--post-filter-json`",
        "Between/from A to B",
        "Path`, `FileId`, `Db`, `Filename`, `WAV/Duration`, `WAV/Sample Rate`, `WAV/Bit Depth`, `WAV/Channels",
        "query-object --type AudioFileSource --take 1000",
    ):
        assert required in text


def _guid(namespace: str, key: str) -> str:
    return "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}:{key}")).upper() + "}"


def _observed_rows(staged, request: BoundMediaPoolRequest):
    rows = []
    binding = request.binding
    for item in staged.assets:
        asset = item.asset
        database = staged.materialized.database(asset.database_key)
        row = {
            "Path": str(item.indexed_host_path),
            "FileId": _guid("file", asset.key),
            "Db": {
                "id": _guid("db", database.key),
                "name": database.name,
            },
            binding.exact("name"): item.indexed_host_path.stem,
            binding.exact("duration"): asset.parsed.duration_seconds,
            binding.exact("sample_rate"): asset.parsed.sample_rate,
            binding.exact("channels"): asset.parsed.channels,
            binding.exact("bit_depth"): asset.parsed.bit_depth,
        }
        if "scene" in binding.by_concept:
            row[binding.exact("scene")] = asset.parsed.ixml[
                "BWFXML/USER/SCENE"
            ]
            row[binding.exact("take")] = asset.parsed.ixml[
                "BWFXML/USER/TAKE"
            ]
        rows.append(row)
    return rows


def _exact_result(oracle):
    return {
        "return": [
            {
                field: oracle.row(key).values[field]
                for field in oracle.request.options["return"]
            }
            for key in reversed(oracle.expected_keys)
        ]
    }


def _result_for_keys(oracle, keys):
    return {
        "return": [
            {
                field: oracle.row(key).values[field]
                for field in oracle.request.options["return"]
            }
            for key in keys
        ]
    }


def _grouped_media_report(
    oracle,
    *,
    heading_style: str = "natural",
    groups=None,
    path_overrides=None,
    database_overrides=None,
) -> str:
    lines: list[str] = (
        [
            "| Scene | Take | File | Database | Path |",
            "|---|---|---|---|---|",
        ]
        if heading_style == "table"
        else (
            [
                "| Scene + Take | Database | Path | Duration |",
                "|---|---|---|---|",
            ]
            if heading_style == "combined_table"
            else []
        )
    )
    selected_groups = groups or oracle.semantic_answer.expected_groups
    path_overrides = path_overrides or {}
    database_overrides = database_overrides or {}
    for group, keys in selected_groups.items():
        scene, take = group.split("|")
        if heading_style in {"natural", "path_only"}:
            lines.append(f"- `{scene}` / Take `{take}`")
        elif heading_style == "plus":
            lines.append(f"- `{scene}` + Take `{take}`")
        elif heading_style == "explicit":
            lines.append(f"- Scene: `{scene}`, Take: `{take}`")
        elif heading_style == "pipe":
            lines.append(f"- `{scene}|{take}`")
        elif heading_style in {"table", "combined_table"}:
            pass
        else:  # pragma: no cover - test helper misuse
            raise AssertionError(f"unknown heading style: {heading_style}")
        for key in keys:
            row = oracle.row(key)
            database = database_overrides.get(key, row.db["name"])
            path = path_overrides.get(key, row.path)
            filename = Path(row.host_path).name
            if heading_style == "table":
                lines.append(
                    f"| {scene} | {take} | {filename} | {database} | {path} |"
                )
            elif heading_style == "combined_table":
                lines.append(
                    f"| `{scene}` + `{take}` | {database} | `{path}` | 1.0 s |"
                )
            elif heading_style == "path_only":
                lines.append(f"  - {database} — 1.0 s")
                lines.append(f"    `{path}`")
            else:
                lines.append(f"  - {database}: `{filename}`")
                lines.append(f"    `{path}`")
    return "\n".join(lines)


def _sealed_case03(tmp_path: Path):
    scenario = _scenarios()[2]
    case = materialize_media_pool_case(
        scenario,
        asset_root=tmp_path / "owned" / "assets" / "case",
    )
    staged = _stage(case, tmp_path / "stage")
    binding = bind_media_pool_fields(case, _fields(ixml=True))
    request = bind_media_pool_request(case, binding)
    oracle = seal_media_pool_index(
        staged,
        request,
        _observed_rows(staged, request),
    )
    runtime = SimpleNamespace(
        evidence_root=tmp_path / "evidence",
        sandbox=SimpleNamespace(sandbox_path=staged.sandbox_project.parent),
    )
    return runtime, staged, oracle


def _sealed_case01(tmp_path: Path):
    scenario = _scenarios()[0]
    case = materialize_media_pool_case(
        scenario,
        asset_root=tmp_path / "owned" / "assets" / "case",
    )
    staged = _stage(case, tmp_path / "stage")
    binding = bind_media_pool_fields(case, _fields())
    request = bind_media_pool_request(case, binding)
    oracle = seal_media_pool_index(
        staged,
        request,
        _observed_rows(staged, request),
    )
    runtime = SimpleNamespace(
        evidence_root=tmp_path / "evidence",
        sandbox=SimpleNamespace(sandbox_path=staged.sandbox_project.parent),
    )
    return runtime, staged, oracle


def _round_trip_isolation(
    case,
    tmp_path: Path,
    *,
    real_home: Path | None = None,
) -> CustomDatabaseIsolation:
    owned = case.asset_root.parents[1]
    real_home = real_home or (tmp_path / "real-account-home")
    if os.name == "nt":
        profile = owned / "wwise-user-profile"
        appdata = owned / "wwise-appdata"
        local_appdata = owned / "wwise-localappdata"
        for path in (profile, appdata, local_appdata):
            path.mkdir()
        host = NativeWindowsCustomDatabaseHost(
            user_profile=profile,
            appdata=appdata,
            local_appdata=local_appdata,
        )
        global_state = real_home / "AppData" / "Roaming" / "Audiokinetic" / "Wwise"
    else:
        launch_home = owned / "wwise-home"
        launch_home.mkdir()
        wine_prefix = expected_macos_wine_prefix(launch_home)
        dosdevices = wine_prefix / "dosdevices"
        dosdevices.mkdir(parents=True)
        (wine_prefix / "drive_c").mkdir()
        create_symlink_or_skip(
            dosdevices / "z:",
            WINE_Z_DRIVE_TARGET,
            target_is_directory=True,
        )
        create_symlink_or_skip(
            dosdevices / "c:",
            WINE_C_DRIVE_TARGET,
            target_is_directory=True,
        )
        create_symlink_or_skip(
            dosdevices / "y:",
            launch_home,
            target_is_directory=True,
        )
        host = MacOSWineCustomDatabaseHost(
            launch_home=launch_home,
            wine_prefix=wine_prefix,
        )
        global_state = (
            real_home
            / "Library"
            / "Application Support"
            / "Audiokinetic"
            / "Wwise"
        )
    global_state.mkdir(parents=True)
    (global_state / "Wwise.wsettings").write_text("baseline\n", encoding="utf-8")
    evidence = owned / "evidence" / "custom-db-roundtrip.json"
    evidence.parent.mkdir(parents=True)
    payload = custom_database_round_trip_evidence(host)
    evidence.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    proof = CustomDatabaseRoundTripProof(
        wwise_build=SUPPORTED_BUILD,
        evidence_path=evidence,
        evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
        payload_shape_sha256=custom_database_payload_shape_sha256(),
        host_mode=(
            "macos_wine"
            if isinstance(host, MacOSWineCustomDatabaseHost)
            else "native_windows"
        ),
    )
    return CustomDatabaseIsolation(
        owned_root=owned,
        host=host,
        real_account_state_root=global_state,
        global_user_state_before=fingerprint_tree(global_state),
        round_trip_proof=proof,
    )


def test_all_five_media_pool_cases_materialize_deterministic_wav_and_ixml(
    tmp_path: Path,
) -> None:
    cases = _materialize_all(tmp_path)

    assert list(cases) == list(MEDIA_POOL_CASE_IDS)
    assert [len(cases[case_id].assets) for case_id in MEDIA_POOL_CASE_IDS] == [
        5,
        6,
        8,
        7,
        8,
    ]
    assert [case.requires_custom_database for case in cases.values()] == [
        False,
        True,
        True,
        False,
        False,
    ]
    hashes_by_case = {}
    for case in cases.values():
        assert case.source_fingerprint.file_count == len(case.assets)
        assert case.source_fingerprint.byte_count > 0
        case_hashes = []
        for asset in case.assets:
            reparsed = parse_pcm_ixml_wav(asset.source_path)
            assert reparsed == asset.parsed
            assert reparsed.frame_count == round(
                reparsed.sample_rate * reparsed.duration_seconds
            )
            assert reparsed.bit_depth in {16, 24}
            case_hashes.append(reparsed.sha256)
        assert len(case_hashes) == len(set(case_hashes))
        hashes_by_case[case.scenario_id] = tuple(case_hashes)

    repeated = _materialize_all(tmp_path / "repeat")
    assert {
        case_id: tuple(asset.parsed.sha256 for asset in case.assets)
        for case_id, case in repeated.items()
    } == hashes_by_case

    ixml_case = cases["VS25-F-MEDIAPOOL-GET-03"]
    for asset in ixml_case.assets:
        payload = asset.source_path.read_bytes()
        offset = payload.index(b"iXML")
        chunk_size = struct.unpack_from("<I", payload, offset + 4)[0]
        chunk = payload[offset + 8 : offset + 8 + chunk_size]
        assert chunk_size % 2 == 0
        assert chunk.startswith(
            b'<?xml version="1.0" encoding="UTF-8"?>\r<BWFXML>'
        )
    assert {
        (
            asset.parsed.ixml["BWFXML/USER/SCENE"],
            asset.parsed.ixml["BWFXML/USER/TAKE"],
        )
        for asset in ixml_case.assets
    } >= {("DUP_BATTLE", "01"), ("DUP_CITY", "03")}
    assert {
        asset.parsed.ixml["BWFXML/PROJECT"] for asset in ixml_case.assets
    } == {"waapi-skill-v3"}


def test_materializer_refuses_case_root_reuse(tmp_path: Path) -> None:
    scenario = _scenarios()[0]
    root = tmp_path / "case"
    materialize_media_pool_case(scenario, asset_root=root)
    with pytest.raises(MediaPoolRuntimeError, match="cannot be reused"):
        materialize_media_pool_case(scenario, asset_root=root)


def test_getfields_binding_is_exact_case_and_fails_closed_for_ixml(
    tmp_path: Path,
) -> None:
    case = materialize_media_pool_case(
        _scenarios()[2], asset_root=tmp_path / "case"
    )
    binding = bind_media_pool_fields(case, _fields(ixml=True))
    request = bind_media_pool_request(case, binding)

    assert binding.exact("name") == "Filename"
    assert binding.exact("scene") == "BWFXML/USER/SCENE"
    assert binding.exact("take") == "BWFXML/USER/TAKE"
    assert request.args["filters"][0]["field"] == "BWFXML/USER/SCENE"
    assert request.options["return"][-2:] == (
        "BWFXML/USER/SCENE",
        "BWFXML/USER/TAKE",
    )
    assert "{media_pool_fields." not in repr((request.args, request.options))

    with pytest.raises(MediaPoolRuntimeError, match="not unique"):
        bind_media_pool_fields(
            case,
            [*_fields(), "BWFXML/SCENE"],
        )
    with pytest.raises(MediaPoolRuntimeError, match="required exact"):
        bind_media_pool_fields(
            case,
            [field for field in _fields(ixml=True) if field != "WAV/Sample Rate"],
        )


def test_case_01_public_prompt_reaches_exact_short_footstep_request(
    tmp_path: Path,
) -> None:
    scenario, args, options, post_filter = _public_request(tmp_path, 0)

    assert all(
        token in scenario.prompt
        for token in (r"\Databases\Project Originals", "小写 `footstep`", "0.8", "20")
    )
    assert args == {
        "databases": [r"\Databases\Project Originals"],
        "filters": [
            {
                "type": "field",
                "field": "Filename",
                "operator": "contains",
                "value": "footstep",
            },
            {
                "type": "field",
                "field": "WAV/Duration",
                "operator": "lessThan",
                "value": 0.8,
            },
        ],
        "maxResults": 200,
    }
    assert options == {"return": list(MEDIA_POOL_CANONICAL_RETURN_FIELDS)}
    assert post_filter == {
        "field": "Filename",
        "operator": "containsCaseSensitive",
        "value": "footstep",
        "limit": 20,
    }
    _assert_public_media_mapping_is_documented()


def test_case_01_seals_complete_raw_candidates_and_exact_business_result(
    tmp_path: Path,
) -> None:
    _runtime, _staged, oracle = _sealed_case01(tmp_path)

    assert oracle.candidate_keys == (
        "footstep_gravel_short",
        "footstep_wood_short",
        "uppercase_name_decoy",
    )
    assert oracle.expected_keys == (
        "footstep_gravel_short",
        "footstep_wood_short",
    )
    raw = _result_for_keys(oracle, oracle.candidate_keys)
    assert verify_media_pool_candidate_result(oracle, raw).ok
    assert not verify_media_pool_result(oracle, raw).ok

    business = apply_media_pool_post_filter(oracle.request, raw)

    assert verify_media_pool_result(oracle, business).ok
    assert [row["Filename"] for row in business["return"]] == [
        "footstep_gravel_short",
        "footstep_wood_short",
    ]
    missing_candidate = _result_for_keys(oracle, oracle.candidate_keys[:-1])
    assert not verify_media_pool_candidate_result(oracle, missing_candidate).ok


def test_case_02_public_prompt_reaches_exact_voice_format_request(
    tmp_path: Path,
) -> None:
    scenario, args, options, post_filter = _public_request(tmp_path, 1)

    assert all(
        token in scenario.prompt
        for token in (r"\Databases\Project Originals", "`VO_` 开头", "48 kHz", "单声道", "50")
    )
    assert args == {
        "databases": [r"\Databases\Project Originals"],
        "filters": [
            {
                "type": "field",
                "field": "Filename",
                "operator": "startsWith",
                "value": "VO_",
            },
            {
                "type": "field",
                "field": "WAV/Sample Rate",
                "operator": "equals",
                "value": 48000,
            },
            {
                "type": "field",
                "field": "WAV/Channels",
                "operator": "equals",
                "value": 1,
            },
        ],
        "maxResults": 50,
    }
    assert options == {"return": list(MEDIA_POOL_CANONICAL_RETURN_FIELDS)}
    assert post_filter is None
    _assert_public_media_mapping_is_documented()


def test_case_03_public_prompt_reaches_exact_cross_database_ixml_request(
    tmp_path: Path,
) -> None:
    scenario, args, options, post_filter = _public_request(tmp_path, 2, ixml=True)

    assert all(
        token in scenario.prompt
        for token in (
            r"\Databases\Project Originals",
            r"\Databases\User Databases\SemanticLab Editorial",
            "Scene 以 `DUP_` 开头",
            "48 kHz",
            "0.4 到 8 秒之间",
            "Scene+Take",
            "40",
        )
    )
    assert args == {
        "databases": [
            r"\Databases\Project Originals",
            r"\Databases\User Databases\SemanticLab Editorial",
        ],
        "filters": [
            {
                "type": "field",
                "field": "BWFXML/USER/SCENE",
                "operator": "startsWith",
                "value": "DUP_",
            },
            {
                "type": "field",
                "field": "WAV/Sample Rate",
                "operator": "equals",
                "value": 48000,
            },
            {
                "type": "field",
                "field": "WAV/Duration",
                "operator": "greaterThanOrEqual",
                "value": 0.4,
            },
            {
                "type": "field",
                "field": "WAV/Duration",
                "operator": "lessThanOrEqual",
                "value": 8.0,
            },
        ],
        "maxResults": 40,
    }
    assert type(args["filters"][3]["value"]) is float
    assert options == {
        "return": [
            *MEDIA_POOL_CANONICAL_RETURN_FIELDS,
            "BWFXML/USER/SCENE",
            "BWFXML/USER/TAKE",
        ]
    }
    assert post_filter is None
    _assert_public_media_mapping_is_documented()


def test_case_04_public_prompt_reaches_exact_unreferenced_audit_requests(
    tmp_path: Path,
) -> None:
    scenario, args, options, post_filter = _public_request(tmp_path, 3)

    assert all(
        token in scenario.prompt
        for token in (
            r"\Databases\Project Originals",
            "`SemanticLab_UnusedAudit`",
            "48 kHz",
            "单声道",
            "Audio Source",
            "完全未引用",
        )
    )
    assert args == {
        "databases": [r"\Databases\Project Originals"],
        "filters": [
            {
                "type": "field",
                "field": "Filename",
                "operator": "contains",
                "value": "SemanticLab_UnusedAudit",
            },
            {
                "type": "field",
                "field": "WAV/Sample Rate",
                "operator": "equals",
                "value": 48000,
            },
            {
                "type": "field",
                "field": "WAV/Channels",
                "operator": "equals",
                "value": 1,
            },
        ],
        "maxResults": 100,
    }
    assert options == {"return": list(MEDIA_POOL_CANONICAL_RETURN_FIELDS)}
    assert post_filter is None

    case = materialize_media_pool_case(
        scenario,
        asset_root=tmp_path / "association-owned" / "assets" / "case",
    )
    supporting = build_reference_read_call(
        _stage(case, tmp_path / "association-stage")
    )
    assert supporting is not None
    assert supporting.as_dict() == {
        "uri": "ak.wwise.core.object.get",
        "args": {"waql": "$ from type AudioFileSource"},
        "options": {"return": ["id", "path", "originalFilePath"]},
    }
    _assert_public_media_mapping_is_documented()


def test_case_05_public_prompt_reaches_exact_quality_gate_request(
    tmp_path: Path,
) -> None:
    scenario, args, options, post_filter = _public_request(tmp_path, 4)

    assert all(
        token in scenario.prompt
        for token in (
            r"\Databases\Project Originals",
            r"`^(Impact|Explosion)_[A-Za-z0-9_]+$`",
            "48 kHz",
            "24 bit",
            "大于 0.15 秒",
            "不超过 3.5 秒",
            "25",
        )
    )
    assert args == {
        "databases": [r"\Databases\Project Originals"],
        "filters": [
            {
                "type": "field",
                "field": "Filename",
                "operator": "matchesRegex",
                "value": r"^(Impact|Explosion)_[A-Za-z0-9_]+$",
            },
            {
                "type": "field",
                "field": "WAV/Sample Rate",
                "operator": "equals",
                "value": 48000,
            },
            {
                "type": "field",
                "field": "WAV/Bit Depth",
                "operator": "equals",
                "value": 24,
            },
            {
                "type": "field",
                "field": "WAV/Duration",
                "operator": "greaterThan",
                "value": 0.15,
            },
            {
                "type": "field",
                "field": "WAV/Duration",
                "operator": "lessThanOrEqual",
                "value": 3.5,
            },
        ],
        "maxResults": 25,
    }
    assert options == {"return": list(MEDIA_POOL_CANONICAL_RETURN_FIELDS)}
    assert post_filter is None
    _assert_public_media_mapping_is_documented()


def test_project_originals_stage_only_into_owned_sandbox_and_preserve_sources(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    case = materialize_media_pool_case(
        _scenarios()[0], asset_root=owned / "assets" / "case"
    )
    before = case.source_fingerprint
    staged = _stage(case, tmp_path)

    assert all(item.indexed_host_path.is_relative_to(staged.owned_root) for item in staged.assets)
    assert all("Originals/SFX" in item.indexed_host_path.as_posix() for item in staged.assets)
    assert fingerprint_tree(case.asset_root / "database-inputs") == before
    assert staged.staged_fingerprint.file_count >= len(case.assets)


def test_custom_databases_are_blocked_without_roundtrip_and_use_documented_shape(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    case = materialize_media_pool_case(
        _scenarios()[1], asset_root=owned / "assets" / "case"
    )

    blocked = media_pool_preflight(case)
    assert blocked.status == "BLOCKED"
    assert blocked.code == "CUSTOM_DATABASE_ROUNDTRIP_UNPROVEN"
    assert blocked.create_calls == ()

    isolation = _round_trip_isolation(case, tmp_path)
    ready = media_pool_preflight(case, isolation=isolation)
    assert ready.status == "READY"
    assert len(ready.create_calls) == 1
    call = ready.create_calls[0]
    assert call.uri == OBJECT_SET_URI
    parent = call.args["objects"][0]
    child = parent["children"][0]
    path_row = child["@Paths"][0]
    assert parent["object"] == USER_DATABASES_PATH
    assert child["type"] == "MediaPoolDatabase"
    assert child["name"] == "SemanticLab Other"
    if isinstance(isolation.host, MacOSWineCustomDatabaseHost):
        expected_path = host_directory_to_wine_z_path(
            case.database("semanticlab_other").source_root,
            owned_root=isolation.owned_root,
            launch_home=isolation.host.launch_home,
            wine_prefix=isolation.host.wine_prefix,
        )
        assert expected_path.startswith("Z:\\")
        assert "/" not in expected_path
    else:
        expected_path = str(
            case.database("semanticlab_other").source_root.resolve(strict=True)
        )
        assert PureWindowsPath(expected_path).is_absolute()
        assert PureWindowsPath(expected_path).drive
    assert path_row == {
        "type": "MediaPoolDatabasePath",
        "name": "",
        "@Path": expected_path,
    }

    database_id = _guid("created-db", "semanticlab_other")
    created = parse_custom_database_create_results(
        case,
        [
            {
                "objects": [
                    {
                        "id": "{8452BD49-9264-4A56-A3BB-047FA7F119BE}",
                        "children": [
                            {
                                "id": database_id,
                                "name": "SemanticLab Other",
                                "@Paths": [
                                    {
                                        "id": _guid("created-path", "semanticlab_other"),
                                        "name": "",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ],
    )
    assert created == {"semanticlab_other": database_id}
    delete_calls = build_custom_database_delete_calls(
        case, created
    )
    assert [item.uri for item in delete_calls] == [OBJECT_DELETE_URI]
    assert delete_calls[0].args == {"object": database_id}

    isolation.round_trip_proof.evidence_path.unlink()
    invalid = media_pool_preflight(case, isolation=isolation)
    assert invalid.status == "BLOCKED"
    assert invalid.code == "CUSTOM_DATABASE_ISOLATION_INVALID"


def test_custom_database_wine_path_boundary_is_exact_and_fail_closed(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    case = materialize_media_pool_case(
        _scenarios()[1], asset_root=owned / "assets" / "case"
    )
    isolation = _round_trip_isolation(case, tmp_path)
    source = owned / "Custom Media" / "Source Set"
    source.mkdir(parents=True)

    if isinstance(isolation.host, NativeWindowsCustomDatabaseHost):
        ready = media_pool_preflight(case, isolation=isolation)
        assert ready.ready
        wire_path = ready.create_calls[0].args["objects"][0]["children"][0][
            "@Paths"
        ][0]["@Path"]
        assert wire_path == str(
            case.database("semanticlab_other").source_root.resolve(strict=True)
        )
        assert PureWindowsPath(wire_path).is_absolute()
        return

    assert validate_macos_wine_prefix(
        owned_root=owned,
        launch_home=isolation.host.launch_home,
        wine_prefix=isolation.host.wine_prefix,
    ) == isolation.host.wine_prefix
    assert resolve_macos_wine_y_drive_root(
        isolation.host.launch_home
    ) == isolation.host.launch_home
    mapped = host_directory_to_wine_z_path(
        source,
        owned_root=owned,
        launch_home=isolation.host.launch_home,
        wine_prefix=isolation.host.wine_prefix,
    )
    wire_path = PureWindowsPath(mapped)
    assert wire_path.drive == "Z:"
    assert wire_path.parts[1:] == source.parts[1:]
    localized = Path(source.anchor).joinpath(*wire_path.parts[1:]).resolve()
    assert localized == source.resolve()

    alias = owned / "source-alias"
    create_symlink_or_skip(alias, source, target_is_directory=True)
    with pytest.raises(MediaPoolRuntimeError, match="link or reparse"):
        host_directory_to_wine_z_path(
            alias,
            owned_root=owned,
            launch_home=isolation.host.launch_home,
            wine_prefix=isolation.host.wine_prefix,
        )

    z_drive = isolation.host.wine_prefix / "dosdevices" / "z:"
    z_drive.unlink()
    create_symlink_or_skip(z_drive, "/tmp", target_is_directory=True)
    with pytest.raises(MediaPoolRuntimeError, match="unexpected target"):
        validate_macos_wine_prefix(
            owned_root=owned,
            launch_home=isolation.host.launch_home,
            wine_prefix=isolation.host.wine_prefix,
        )

    with pytest.raises(MediaPoolRuntimeError, match="exact Wwise 2025 bottle"):
        validate_macos_wine_prefix(
            owned_root=owned,
            launch_home=isolation.host.launch_home,
            wine_prefix=owned / "another-prefix",
        )


def test_native_windows_custom_database_path_compiler_is_closed_and_portable() -> None:
    owned = r"C:\Campaign Root\owned"
    source = r"c:\Campaign Root\owned\assets\素材 & review"

    assert _compile_native_windows_owned_directory(
        source,
        owned_root=owned,
    ) == str(PureWindowsPath(source))

    for rejected in (
        r"D:\Campaign Root\owned\assets",
        r"C:\Campaign Root\outside",
        r"\\server\share\owned\assets",
        r"C:relative\assets",
        r"C:\Campaign Root\owned\..\outside",
    ):
        with pytest.raises(MediaPoolRuntimeError):
            _compile_native_windows_owned_directory(
                rejected,
                owned_root=owned,
            )


def test_custom_database_allows_case_owned_home_below_real_account_home(
    tmp_path: Path,
) -> None:
    real_home = tmp_path / "real-account-home"
    owned = real_home / "Documents" / "campaign" / "owned"
    case = materialize_media_pool_case(
        _scenarios()[1], asset_root=owned / "assets" / "case"
    )
    isolation = _round_trip_isolation(case, tmp_path, real_home=real_home)

    ready = media_pool_preflight(case, isolation=isolation)

    assert ready.status == "READY"
    isolated_root = (
        isolation.host.launch_home
        if isinstance(isolation.host, MacOSWineCustomDatabaseHost)
        else isolation.host.user_profile
    )
    assert isolated_root.is_relative_to(real_home)


def test_custom_database_rejects_noncanonical_or_overlapping_global_state(
    tmp_path: Path,
) -> None:
    real_home = tmp_path / "real-account-home"
    owned = real_home / "Documents" / "campaign" / "owned"
    case = materialize_media_pool_case(
        _scenarios()[1], asset_root=owned / "assets" / "case"
    )
    isolation = _round_trip_isolation(case, tmp_path, real_home=real_home)

    invalid_isolation = CustomDatabaseIsolation(
        owned_root=isolation.owned_root,
        host=isolation.host,
        real_account_state_root=isolation.real_account_state_root,
        global_user_state_before=fingerprint_tree(real_home / "other-state"),
        round_trip_proof=isolation.round_trip_proof,
    )
    noncanonical = media_pool_preflight(case, isolation=invalid_isolation)

    assert noncanonical.status == "BLOCKED"
    assert noncanonical.code == "CUSTOM_DATABASE_ISOLATION_INVALID"
    assert "exact real-account Wwise state" in noncanonical.reason


def test_bound_probe_index_and_business_oracle_are_exact(tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    case = materialize_media_pool_case(
        _scenarios()[4], asset_root=owned / "assets" / "case"
    )
    staged = _stage(case, tmp_path)
    binding = bind_media_pool_fields(case, _fields())
    request = bind_media_pool_request(case, binding)
    probes = build_index_probe_calls(staged, binding)

    assert len(probes) == 8
    assert all(call.args["maxResults"] == 8 for call in probes)
    assert all(call.args["filters"][0]["operator"] == "equals" for call in probes)
    assert tuple(
        call.args["filters"][0]["value"] for call in probes
    ) == tuple(item.indexed_host_path.stem for item in staged.assets)
    observed = _observed_rows(staged, request)
    assert all(
        row["Filename"] == item.indexed_host_path.stem
        and row["Path"].endswith(".wav")
        for row, item in zip(observed, staged.assets, strict=True)
    )
    oracle = seal_media_pool_index(
        staged,
        request,
        observed,
    )

    result = _exact_result(oracle)
    verified = verify_media_pool_result(oracle, result)
    assert verified.ok is True
    assert verify_media_pool_read_unchanged(staged, oracle).ok
    assert verified.details["row_count"] == 4
    assert oracle.semantic_answer.ordered_keys == (
        "explosion_large",
        "explosion_small",
        "impact_wood",
        "impact_metal",
    )
    assert verify_semantic_report(
        oracle,
        ordered_keys=oracle.semantic_answer.ordered_keys,
    ).ok

    bad = {"return": [*result["return"], _observed_rows(staged, request)[4]]}
    assert not verify_media_pool_result(oracle, bad).ok
    assert not verify_semantic_report(
        oracle,
        ordered_keys=tuple(reversed(oracle.semantic_answer.ordered_keys)),
    ).ok

    narrowed_args = _plain(request.args)
    narrowed_args["filters"][-1]["value"] = 1.5
    narrowed = BoundMediaPoolRequest(
        scenario_id=request.scenario_id,
        args=narrowed_args,
        options=request.options,
        binding=request.binding,
    )
    with pytest.raises(
        MediaPoolRuntimeError,
        match="expected_candidate_file_keys differ",
    ):
        seal_media_pool_index(
            staged,
            narrowed,
            _observed_rows(staged, narrowed),
        )

    changed_path = staged.assets[0].indexed_host_path
    changed_path.write_bytes(changed_path.read_bytes() + b"drift")
    assert not verify_media_pool_read_unchanged(staged, oracle).ok


def test_index_seal_accepts_only_bound_y_and_database_relative_paths(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    case = materialize_media_pool_case(
        _scenarios()[0], asset_root=owned / "assets" / "case"
    )
    staged = _stage(case, tmp_path)
    binding = bind_media_pool_fields(case, _fields())
    request = bind_media_pool_request(case, binding)
    observed = _observed_rows(staged, request)
    y_root = staged.owned_root
    y_rows = []
    relative_rows = []
    originals_root = staged.sandbox_project.parent / "Originals"
    for row, item in zip(observed, staged.assets, strict=True):
        y_row = dict(row)
        y_row["Path"] = str(
            PureWindowsPath(
                "Y:/",
                *item.indexed_host_path.relative_to(y_root).parts,
            )
        )
        y_rows.append(y_row)
        relative_row = dict(row)
        relative_row["Path"] = str(
            PureWindowsPath(
                *item.indexed_host_path.relative_to(originals_root).parts
            )
        )
        relative_rows.append(relative_row)

    with pytest.raises(MediaPoolRuntimeError, match="did not uniquely resolve"):
        seal_media_pool_index(staged, request, y_rows)
    assert seal_media_pool_index(
        staged,
        request,
        y_rows,
        waapi_y_drive_root=y_root,
    ).expected_keys == tuple(case.expected_file_keys)
    assert seal_media_pool_index(
        staged,
        request,
        relative_rows,
    ).expected_keys == tuple(case.expected_file_keys)

    wrong_y_root = owned / "wrong-y-root"
    wrong_y_root.mkdir()
    with pytest.raises(MediaPoolRuntimeError, match="did not uniquely resolve"):
        seal_media_pool_index(
            staged,
            request,
            y_rows,
            waapi_y_drive_root=wrong_y_root,
        )
    escaping_rows = [dict(row) for row in relative_rows]
    escaping_rows[0]["Path"] = r"..\footstep_gravel_short.wav"
    with pytest.raises(MediaPoolRuntimeError, match="did not uniquely resolve"):
        seal_media_pool_index(staged, request, escaping_rows)


@pytest.mark.parametrize("index", range(5))
def test_all_five_full_fixture_oracles_compile_typed_business_plan(
    index: int,
    tmp_path: Path,
) -> None:
    scenario = _scenarios()[index]
    owned = tmp_path / "owned"
    case = materialize_media_pool_case(
        scenario,
        asset_root=owned / "assets" / "case",
    )
    staged = _stage(case, tmp_path)
    binding = bind_media_pool_fields(case, _fields(ixml=index == 2))
    request = bind_media_pool_request(case, binding)
    oracle = seal_media_pool_index(
        staged,
        request,
        _observed_rows(staged, request),
    )
    sections = compile_media_pool_business_plan(
        case,
        staged,
        oracle,
        _expected_media_protocol(case, oracle),
        project_digest="a" * 64,
        reviewed_scenario_fixture=scenario.fixture,
    )
    if index == 2:
        unrelated = owned / "wwise-user-home"
        unrelated.mkdir()
        target = tmp_path / "cxbottle-target.conf"
        target.write_text("private Wine state\n", encoding="utf-8")
        create_symlink_or_skip(unrelated / "cxbottle.conf", target)
    validate_media_pool_business_plan(
        sections,
        case,
        staged,
        oracle,
        _expected_media_protocol(case, oracle),
        project_digest="a" * 64,
        reviewed_scenario_fixture=scenario.fixture,
        verify_files=True,
    )

    assert len(sections.live_binding["sealed_rows"]) == len(case.assets)
    assert sections.live_binding["semantic_answer"]["ordered_keys"] == list(
        oracle.semantic_answer.ordered_keys
    )
    archived_oracle = campaign._heavy_v3_plan_json_value(oracle)
    assert campaign._validate_media_pool_sealed_oracle(
        archived_oracle,
        scenario_id=case.scenario_id,
        label="full fixture Media Pool oracle",
    ) == archived_oracle

    with pytest.raises(AudioMediaBusinessPlanError, match="all fixture asset keys"):
        compile_media_pool_business_plan(
            case,
            staged,
            replace(oracle, rows=oracle.rows[:-1]),
            _expected_media_protocol(case, oracle),
            project_digest="a" * 64,
            reviewed_scenario_fixture=scenario.fixture,
        )

    reversed_answer = replace(
        oracle.semantic_answer,
        ordered_keys=tuple(reversed(oracle.semantic_answer.ordered_keys)),
    )
    with pytest.raises(AudioMediaBusinessPlanError, match="canonical fixture plan"):
        compile_media_pool_business_plan(
            case,
            staged,
            replace(oracle, semantic_answer=reversed_answer),
            _expected_media_protocol(case, oracle),
            project_digest="a" * 64,
            reviewed_scenario_fixture=scenario.fixture,
        )

    if index == 2:
        reversed_groups = {
            group: tuple(reversed(keys))
            for group, keys in reversed(
                tuple(oracle.semantic_answer.expected_groups.items())
            )
        }
        response = _grouped_media_report(oracle, groups=reversed_groups)
        assert heavy_runner._media_final_response_failures(
            oracle,
            staged,
            response,
        ) == ()
        campaign._validate_media_final_response(
            response,
            oracle=archived_oracle,
            label="unordered grouped Media Pool response",
        )


def test_grouped_final_report_accepts_natural_formats_but_closes_members(
    tmp_path: Path,
) -> None:
    _runtime, staged, oracle = _sealed_case03(tmp_path)
    archived_oracle = campaign._heavy_v3_plan_json_value(oracle)

    def assert_accepts(response: str) -> None:
        assert heavy_runner._media_final_response_failures(
            oracle,
            staged,
            response,
        ) == ()
        campaign._validate_media_final_response(
            response,
            oracle=archived_oracle,
            label="grouped Media Pool response",
        )

    def assert_rejects(response: str, expected: str) -> None:
        assert any(
            expected in failure
            for failure in heavy_runner._media_final_response_failures(
                oracle,
                staged,
                response,
            )
        )
        with pytest.raises(campaign.CampaignEvidenceError, match=expected):
            campaign._validate_media_final_response(
                response,
                oracle=archived_oracle,
                label="grouped Media Pool response",
            )

    for style in (
        "natural",
        "plus",
        "explicit",
        "pipe",
        "table",
        "combined_table",
        "path_only",
    ):
        assert_accepts(_grouped_media_report(oracle, heading_style=style))

    first_group, second_group = tuple(oracle.semantic_answer.expected_groups)
    first_keys = oracle.semantic_answer.expected_groups[first_group]
    second_keys = oracle.semantic_answer.expected_groups[second_group]
    assert_rejects(
        _grouped_media_report(
            oracle,
            groups={first_group: second_keys, second_group: first_keys},
        ),
        "does not bind its exact members",
    )

    first_key = first_keys[0]
    assert_rejects(
        _grouped_media_report(
            oracle,
            path_overrides={first_key: r"Z:\...\Battle_Project.wav"},
        ),
        "databases, and full paths",
    )
    assert_rejects(
        _grouped_media_report(
            oracle,
            database_overrides={first_key: "SemanticLab Editorial"},
        ),
        "databases, and full paths",
    )
    assert_rejects(
        _grouped_media_report(
            oracle,
            database_overrides={first_key: ""},
        ),
        "databases, and full paths",
    )
    assert_rejects(
        _grouped_media_report(
            oracle,
            path_overrides={first_key: oracle.row(first_keys[1]).path},
        ),
        "databases, and full paths",
    )

    wrong_take = _grouped_media_report(oracle).replace("Take `01`", "Take `03`", 1)
    assert_rejects(wrong_take, "closed Scene/Take heading")
    split_take = _grouped_media_report(oracle).replace(
        "`DUP_BATTLE` / Take `01`",
        "`DUP_BATTLE`\nTake `01`",
        1,
    )
    assert_rejects(split_take, "closed Scene/Take heading")
    substring_scene = _grouped_media_report(oracle).replace(
        "`DUP_BATTLE` / Take `01`",
        "`DUP_BATTLE_ALT` / Take `01`",
        1,
    )
    assert_rejects(substring_scene, "closed Scene/Take heading")

    decoy_key = oracle.semantic_answer.excluded_keys[0]
    decoy = oracle.row(decoy_key)
    decoy_filename = Path(decoy.host_path).name
    valid = _grouped_media_report(oracle)
    assert_accepts(f"已排除 `{decoy_filename}` 对照项。\n{valid}")
    complete_decoy = (
        f"{decoy.db['name']}: {decoy_filename}\n{decoy.path}\n{valid}"
    )
    assert_rejects(complete_decoy, "complete excluded Media Pool row")


def test_all_five_requests_match_independently_parsed_fixture_predicates(
    tmp_path: Path,
) -> None:
    for index, scenario in enumerate(_scenarios()):
        owned = tmp_path / f"owned-{index}"
        case = materialize_media_pool_case(
            scenario,
            asset_root=owned / "assets" / "case",
        )
        staged = _stage(case, tmp_path / f"stage-{index}")
        binding = bind_media_pool_fields(
            case,
            _fields(ixml=case.scenario_id.endswith("-03")),
        )
        request = bind_media_pool_request(case, binding)
        oracle = seal_media_pool_index(
            staged,
            request,
            _observed_rows(staged, request),
        )

        assert oracle.expected_keys == case.expected_file_keys
        assert verify_media_pool_result(oracle, _exact_result(oracle)).ok


def test_full_request_preflight_records_case03_float_integer_wire_difference(
    tmp_path: Path,
) -> None:
    runtime, staged, oracle = _sealed_case03(tmp_path)
    exact = _exact_result(oracle)
    calls: list[dict] = []

    def direct(uri, args, options):
        plain_args = heavy_runner._json_value(args)
        plain_options = heavy_runner._json_value(options)
        upper = plain_args["filters"][-1]["value"]
        calls.append({"uri": uri, "args": plain_args, "options": plain_options})
        return exact if type(upper) is float else {"return": []}

    proof = heavy_runner._run_media_pool_full_request_preflight(
        runtime=runtime,
        direct=direct,
        staged=staged,
        oracle=oracle,
    )

    assert proof["passed"] is True
    assert len(calls) == 2
    canonical_args = calls[0]["args"]
    integer_args = calls[1]["args"]
    assert canonical_args["filters"][-1]["value"] == 8.0
    assert type(canonical_args["filters"][-1]["value"]) is float
    assert integer_args["filters"][-1]["value"] == 8
    assert type(integer_args["filters"][-1]["value"]) is int
    changed = json.loads(json.dumps(canonical_args))
    changed["filters"][-1]["value"] = 8
    assert changed == integer_args

    evidence = json.loads(
        (runtime.evidence_root / "media-pool-full-request-preflight.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["contract"] == heavy_runner.MEDIA_POOL_FULL_REQUEST_PREFLIGHT_CONTRACT
    assert evidence["canonical_request"]["status"] == "verified_exact"
    assert evidence["canonical_request"]["duration_upper"] == {
        "filter_index": 3,
        "json_number_kind": "number",
        "value": 8.0,
    }
    assert evidence["canonical_request"]["result"]["row_count"] == 4
    assert evidence["canonical_request"]["result"]["file_ids_complete"] is True
    assert evidence["integer_wire_probe"]["performed"] is True
    assert evidence["integer_wire_probe"]["diagnostic_only"] is True
    assert evidence["integer_wire_probe"]["duration_upper"] == {
        "filter_index": 3,
        "json_number_kind": "integer",
        "value": 8,
    }
    assert evidence["integer_wire_probe"]["result"]["row_count"] == 0
    assert evidence["integer_wire_probe"]["verification"]["ok"] is False
    assert evidence["integer_wire_probe"]["matches_canonical_result_sha256"] is False
    assert (
        evidence["canonical_request"]["request_sha256"]
        != evidence["integer_wire_probe"]["request_sha256"]
    )


def test_full_request_preflight_seals_case01_candidate_and_business_layers(
    tmp_path: Path,
) -> None:
    runtime, staged, oracle = _sealed_case01(tmp_path)
    raw = _result_for_keys(oracle, oracle.candidate_keys)

    proof = heavy_runner._run_media_pool_full_request_preflight(
        runtime=runtime,
        direct=lambda _uri, _args, _options: raw,
        staged=staged,
        oracle=oracle,
    )

    canonical = proof["canonical_request"]
    assert proof["passed"] is True
    assert canonical["post_filter"] == {
        "field": "Filename",
        "operator": "containsCaseSensitive",
        "value": "footstep",
        "limit": 20,
    }
    assert canonical["result"]["row_count"] == 3
    assert canonical["candidate_verification"]["ok"] is True
    assert canonical["raw_count_below_max_results"] is True
    assert canonical["business_result"]["row_count"] == 2
    assert canonical["verification"]["ok"] is True


def test_full_request_preflight_rejects_candidate_ceiling_saturation(
    tmp_path: Path,
) -> None:
    runtime, staged, oracle = _sealed_case01(tmp_path)
    raw = _result_for_keys(oracle, oracle.candidate_keys)
    saturated_args = dict(oracle.request.args)
    saturated_args["maxResults"] = len(oracle.candidate_keys)
    saturated = replace(
        oracle,
        request=replace(oracle.request, args=saturated_args),
    )

    with pytest.raises(
        heavy_runner._HeavyProjectInfrastructureError,
        match="sealed candidate and business oracles",
    ):
        heavy_runner._run_media_pool_full_request_preflight(
            runtime=runtime,
            direct=lambda _uri, _args, _options: raw,
            staged=staged,
            oracle=saturated,
        )

    evidence = json.loads(
        (runtime.evidence_root / "media-pool-full-request-preflight.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["canonical_request"]["candidate_verification"]["ok"] is True
    assert evidence["canonical_request"]["raw_count_below_max_results"] is False
    assert evidence["canonical_request"]["verification"] is None


def test_full_request_preflight_does_not_require_case03_integer_probe_to_fail(
    tmp_path: Path,
) -> None:
    runtime, staged, oracle = _sealed_case03(tmp_path)
    exact = _exact_result(oracle)
    calls: list[object] = []

    def direct(_uri, args, _options):
        calls.append(args)
        return exact

    proof = heavy_runner._run_media_pool_full_request_preflight(
        runtime=runtime,
        direct=direct,
        staged=staged,
        oracle=oracle,
    )

    assert proof["passed"] is True
    assert len(calls) == 2
    assert proof["integer_wire_probe"]["status"] == "observed"
    assert proof["integer_wire_probe"]["verification"]["ok"] is True
    assert proof["integer_wire_probe"]["matches_canonical_result_sha256"] is True


def test_full_request_preflight_does_not_block_on_diagnostic_probe_error(
    tmp_path: Path,
) -> None:
    runtime, staged, oracle = _sealed_case03(tmp_path)
    exact = _exact_result(oracle)
    call_count = 0

    def direct(_uri, _args, _options):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return exact
        raise RuntimeError("integer wire representation rejected")

    proof = heavy_runner._run_media_pool_full_request_preflight(
        runtime=runtime,
        direct=direct,
        staged=staged,
        oracle=oracle,
    )

    assert proof["passed"] is True
    assert proof["integer_wire_probe"]["status"] == "call_failed"
    assert "integer wire representation rejected" in proof["integer_wire_probe"]["error"]
    assert proof["integer_wire_probe"]["result"] is None
    assert proof["integer_wire_probe"]["verification"] is None


def test_full_request_preflight_blocks_before_agent_when_canonical_query_misses(
    tmp_path: Path,
) -> None:
    runtime, staged, oracle = _sealed_case03(tmp_path)
    calls: list[object] = []

    def direct(_uri, args, _options):
        calls.append(args)
        return {"return": []}

    with pytest.raises(
        heavy_runner._HeavyProjectInfrastructureError,
        match="did not reproduce the sealed candidate and business oracles",
    ):
        heavy_runner._run_media_pool_full_request_preflight(
            runtime=runtime,
            direct=direct,
            staged=staged,
            oracle=oracle,
        )

    assert len(calls) == 1
    evidence = json.loads(
        (runtime.evidence_root / "media-pool-full-request-preflight.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["passed"] is False
    assert evidence["canonical_request"]["status"] == "verification_failed"
    assert evidence["canonical_request"]["candidate_verification"]["ok"] is False
    assert evidence["canonical_request"]["verification"] is None
    assert evidence["integer_wire_probe"] == {
        "diagnostic_only": True,
        "performed": False,
        "reason": "canonical_request_not_verified",
    }


def test_ixml_groups_and_reference_associations_feed_semantic_grader(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    scenarios = _scenarios()

    ixml_case = materialize_media_pool_case(
        scenarios[2], asset_root=owned / "assets" / "ixml"
    )
    ixml_staged = _stage(ixml_case, tmp_path / "ixml-run")
    ixml_binding = bind_media_pool_fields(ixml_case, _fields(ixml=True))
    ixml_request = bind_media_pool_request(ixml_case, ixml_binding)
    ixml_oracle = seal_media_pool_index(
        ixml_staged,
        ixml_request,
        _observed_rows(ixml_staged, ixml_request),
    )
    assert verify_semantic_report(
        ixml_oracle,
        ordered_keys=ixml_oracle.semantic_answer.ordered_keys,
        groups=ixml_oracle.semantic_answer.expected_groups,
    ).ok

    association_case = materialize_media_pool_case(
        scenarios[3], asset_root=owned / "assets" / "associations"
    )
    association_staged = _stage(association_case, tmp_path / "association-run")
    fixture_call = build_reference_fixture_call(association_staged)
    assert fixture_call is not None
    assert fixture_call.uri == "ak.wwise.core.audio.import"
    assert fixture_call.args["importOperation"] == "useExisting"
    assert len(fixture_call.args["imports"]) == 3
    assert all(
        item["objectPath"].startswith(r"\Containers\Default Work Unit")
        and "<Sequence Container>" in item["objectPath"]
        and "<Sound SFX>" in item["objectPath"]
        for item in fixture_call.args["imports"]
    )
    with pytest.raises(MediaPoolRuntimeError, match="escaped the Default Work Unit"):
        _typed_audio_import_path(
            r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\UnusedAuditRefs\Dialogue_Used"
        )
    read_call = build_reference_read_call(association_staged)
    assert read_call is not None
    assert read_call.uri == OBJECT_GET_URI
    assert read_call.args == {"waql": "$ from type AudioFileSource"}
    reference_rows = [
        {
            "id": _guid("source", f"{item.asset.key}:{object_path}"),
            "path": object_path + r"\AudioFileSource",
            "originalFilePath": str(item.indexed_host_path),
        }
        for item in association_staged.assets
        for object_path in item.asset.referenced_by
    ]
    reference_result = verify_reference_associations(
        association_staged,
        {"return": reference_rows},
    )
    assert reference_result.ok
    assert reference_result.details["fixture_audio_source_count"] == 3
    assert not verify_reference_associations(
        association_staged,
        {"return": reference_rows[:-1]},
    ).ok
    association_binding = bind_media_pool_fields(association_case, _fields())
    association_request = bind_media_pool_request(association_case, association_binding)
    association_oracle = seal_media_pool_index(
        association_staged,
        association_request,
        _observed_rows(association_staged, association_request),
    )
    match_paths = reference_match_paths(association_oracle)
    match_argv = build_reference_match_gateway_argv(match_paths)
    assert match_argv[:5] == (
        "query-object",
        "--type",
        "AudioFileSource",
        "--take",
        "1000",
    )
    assert match_argv[5:] == tuple(
        token
        for path in match_paths
        for token in ("--match-original-file-path", path)
    )
    assert "--return-field" not in match_argv
    assert len(match_paths) == 4

    key_by_path = {
        association_oracle.row(key).path: key
        for key in association_oracle.expected_keys
    }
    compact_candidates = []
    for path in match_paths:
        item = association_staged.staged_asset(key_by_path[path])
        references = [
            {
                "id": _guid("compact-source", f"{item.asset.key}:{parent}"),
                "path": parent + r"\AudioFileSource",
            }
            for parent in item.asset.referenced_by
        ]
        compact_candidates.append(
            {
                "originalFilePath": path,
                "classification": "referenced" if references else "unreferenced",
                "reference_count": len(references),
                "references": references,
                "references_truncated": False,
            }
        )
    compact_result = {
        "contract": REFERENCE_MATCH_RESULT_CONTRACT,
        "scanned_audio_source_count": 3,
        "scan_limit": 1000,
        "scan_complete": True,
        "candidates": compact_candidates,
    }
    compact_verification = verify_reference_match_result(
        association_staged,
        association_oracle,
        compact_result,
    )
    assert compact_verification.ok, compact_verification.details
    assert compact_verification.details["candidate_count"] == 4
    assert compact_verification.details["returned_reference_count"] == 2

    truncated = json.loads(json.dumps(compact_result))
    truncated["candidates"][0]["references_truncated"] = True
    assert not verify_reference_match_result(
        association_staged,
        association_oracle,
        truncated,
    ).ok
    broad_shape = {"objects": reference_rows}
    assert not verify_reference_match_result(
        association_staged,
        association_oracle,
        broad_shape,
    ).ok
    assert verify_semantic_report(
        association_oracle,
        ordered_keys=association_oracle.semantic_answer.ordered_keys,
        referenced_keys=("used_dialogue", "used_foley"),
        unreferenced_keys=("unused_roomtone", "unused_alt"),
    ).ok


def test_reference_associations_close_posix_z_and_relative_original_paths(
    tmp_path: Path,
) -> None:
    case = materialize_media_pool_case(
        _scenarios()[3],
        asset_root=tmp_path / "owned" / "assets" / "associations",
    )
    staged = _stage(case, tmp_path / "association-run")
    originals_root = staged.sandbox_project.parent / "Originals"

    def rows(path_for):
        return [
            {
                "id": _guid("source", f"{item.asset.key}:{object_path}"),
                "path": object_path + r"\AudioFileSource",
                "originalFilePath": path_for(item.indexed_host_path),
            }
            for item in staged.assets
            for object_path in item.asset.referenced_by
        ]

    posix_rows = rows(str)
    z_rows = rows(
        lambda path: (
            str(path.resolve(strict=True))
            if os.name == "nt"
            else str(
                PureWindowsPath(
                    "Z:/", *path.resolve(strict=True).parts[1:]
                )
            )
        )
    )
    relative_rows = rows(
        lambda path: path.relative_to(originals_root).as_posix()
    )
    y_root = staged.owned_root
    y_rows = rows(
        lambda path: str(
            PureWindowsPath(
                "Y:/",
                *path.resolve(strict=True).relative_to(y_root).parts,
            )
        )
    )

    for accepted in (posix_rows, z_rows, relative_rows):
        result = verify_reference_associations(staged, {"return": accepted})
        assert result.ok, result.details

    assert not verify_reference_associations(staged, {"return": y_rows}).ok
    bound_y_result = verify_reference_associations(
        staged,
        {"return": y_rows},
        waapi_y_drive_root=y_root,
    )
    assert bound_y_result.ok, bound_y_result.details
    wrong_y_root = tmp_path / "wrong-y-root"
    wrong_y_root.mkdir()
    assert not verify_reference_associations(
        staged,
        {"return": y_rows},
        waapi_y_drive_root=wrong_y_root,
    ).ok

    rejected_paths = (
        r"Y:\Users\runner\fixture.wav",
        r"C:\fixture.wav",
        r"\\server\share\fixture.wav",
        "../Originals/SFX/fixture.wav",
        relative_rows[0]["originalFilePath"].replace("/", "/./", 1),
    )
    for rejected in rejected_paths:
        tampered = [dict(row) for row in relative_rows]
        tampered[0]["originalFilePath"] = rejected
        result = verify_reference_associations(staged, {"return": tampered})
        assert not result.ok, rejected

    first_path = next(
        item.indexed_host_path
        for item in staged.assets
        if item.asset.referenced_by
    )
    alias = first_path.with_name("reference-alias.wav")
    create_symlink_or_skip(alias, first_path)
    tampered = [dict(row) for row in relative_rows]
    tampered[0]["originalFilePath"] = alias.relative_to(originals_root).as_posix()
    assert not verify_reference_associations(staged, {"return": tampered}).ok


def test_native_windows_path_parser_accepts_local_drives_only() -> None:
    assert _parse_native_windows_absolute_path(
        r"C:\Users\runner\Project\Originals\SFX\fixture.wav"
    ) == (
        "C",
        ("Users", "runner", "Project", "Originals", "SFX", "fixture.wav"),
    )
    assert _parse_native_windows_absolute_path(
        "d:/Audio/Originals/fixture.wav"
    ) == ("D", ("Audio", "Originals", "fixture.wav"))

    for rejected in (
        r"\\server\share\fixture.wav",
        r"C:relative\fixture.wav",
        r"\rooted-without-drive\fixture.wav",
        r"C:\Project\.\fixture.wav",
        r"C:\Project\..\fixture.wav",
    ):
        with pytest.raises(MediaPoolRuntimeError):
            _parse_native_windows_absolute_path(rejected)


def test_custom_database_cleanup_requires_exact_baseline_and_global_state(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    case = materialize_media_pool_case(
        _scenarios()[1], asset_root=owned / "assets" / "case"
    )
    isolation = _round_trip_isolation(case, tmp_path)
    preflight = media_pool_preflight(case, isolation=isolation)
    baseline = (_guid("baseline", "existing"),)
    created = {"semanticlab_other": _guid("created", "semanticlab_other")}
    proof = CustomDatabaseCleanupProof(
        contract=CUSTOM_DATABASE_CLEANUP_CONTRACT,
        scenario_id=case.scenario_id,
        baseline_user_database_ids=baseline,
        created_database_ids=created,
        final_user_database_ids=baseline,
        global_user_state_after=isolation.global_user_state_before,
        wwise_process_stopped=True,
    )
    assert verify_custom_database_cleanup(case, preflight, proof).ok

    residual = CustomDatabaseCleanupProof(
        contract=CUSTOM_DATABASE_CLEANUP_CONTRACT,
        scenario_id=case.scenario_id,
        baseline_user_database_ids=baseline,
        created_database_ids=created,
        final_user_database_ids=(*baseline, created["semanticlab_other"]),
        global_user_state_after=isolation.global_user_state_before,
        wwise_process_stopped=True,
    )
    result = verify_custom_database_cleanup(case, preflight, residual)
    assert not result.ok
    assert result.code == "CUSTOM_DATABASE_CLEANUP_BLOCKED"
