from __future__ import annotations

import json
import wave
from copy import deepcopy
from pathlib import Path

import pytest

from tests.semantic.support.codex_compound_heavy_v1 import (
    load_compound_heavy_profile,
)
from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_metadata_transaction_protocol,
)
from tests.semantic.support.codex_gateway_broker import (
    MetadataBoundJsonArgument,
    project_required_metadata_tokens,
)
from tests.semantic.support.codex_import_assets_v3 import (
    ImportAssetMaterializationError,
    bind_import_live_metadata,
    bound_import_metadata_tokens,
    materialize_import_case,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_V3 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"
COMPOUND_PROFILE = (
    REPO_ROOT / "tests" / "semantic" / "data" / "compound-heavy-v1" / "profile.json"
)
IMPORT_APIS = {
    "ak.wwise.core.audio.import",
    "ak.wwise.core.audio.importTabDelimited",
}


def test_all_ten_core_import_scenarios_materialize_closed_inputs(tmp_path) -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    scenarios = [case for case in bundle.scenarios if case.api in IMPORT_APIS]
    assert len(scenarios) == 10

    prepared = {
        scenario.id: materialize_import_case(
            scenario,
            version="2022.1",
            asset_root=tmp_path / scenario.id,
        )
        for scenario in scenarios
    }

    assert sum(len(case.operation_requests) for case in prepared.values()) == 12
    for scenario in scenarios:
        case = prepared[scenario.id]
        assert scenario.render_prompt(case.visible_values)
        assert case.expected_primary_dispatch_count == scenario.primary_dispatch.count
        assert all(request["contract"] == "waapi-skill.operation-request/v1" for request in case.operation_requests)
        assert all(request["version"] == "2022.1" for request in case.operation_requests)
        assert all(item.path.is_absolute() for item in case.source_files)
        assert all(item.path.is_absolute() for item in case.pre_state_files)
        for item in (*case.source_files, *case.pre_state_files):
            if not item.present:
                assert not item.path.exists()
                continue
            assert item.size and item.sha256
            with wave.open(str(item.path), "rb") as handle:
                assert handle.getframerate() == 48_000
                assert handle.getnchannels() == 1
                assert handle.getsampwidth() == 2
                assert handle.getnframes() > 0


def test_missing_media_case_materializes_one_real_preflight_failure(tmp_path) -> None:
    scenario = load_eval_bundle_v3(SUITE_V3).scenario("O22-AUDIO-TAB-01")
    case = materialize_import_case(
        scenario,
        version="2022.1",
        asset_root=tmp_path / "case",
    )

    assert case.expected_primary_dispatch_count == 0
    assert len(case.operation_requests) == 1
    missing = [item for item in case.source_files if not item.present]
    assert [item.key for item in missing] == ["city_night_missing"]
    table_text = case.tab_files[0].path.read_text(encoding="utf-8")
    assert str(missing[0].path) in table_text
    assert not missing[0].path.exists()


def test_three_language_case_uses_canonical_live_wwise_names_and_three_requests(tmp_path) -> None:
    scenario = load_eval_bundle_v3(SUITE_V3).scenario("O22-AUDIO-TAB-02")
    case = materialize_import_case(
        scenario,
        version="2022.1",
        asset_root=tmp_path / "case",
    )

    assert [
        request["arguments"]["import_language"] for request in case.operation_requests
    ] == ["Chinese(PRC)", "English(US)", "Japanese"]
    visible = json.loads(case.visible_values["language_import_files"])
    assert [row["language"] for row in visible] == [
        "Chinese(PRC)",
        "English(US)",
        "Japanese",
    ]
    assert len({row["file"] for row in visible}) == 3


def test_localized_use_existing_manifest_is_row_sensitive(tmp_path: Path) -> None:
    scenario = load_eval_bundle_v3(SUITE_V3).scenario("O22-AUDIO-IMPORT-01")
    case = materialize_import_case(
        scenario,
        version="2022.1",
        asset_root=tmp_path / "case",
    )

    assert len(case.operation_requests) == 1
    request = case.operation_requests[0]
    assert request["arguments"]["import_operation"] == "useExisting"
    rows = request["arguments"]["imports"]
    existing_rows = [row for row in rows if row["object_path"].endswith("Line01")]
    creation_rows = [row for row in rows if row["object_path"].endswith("Line02")]

    assert len(existing_rows) == 6
    assert len(creation_rows) == 6
    assert all(
        set(row) == {"audio_file", "object_path", "object_type", "import_language"}
        for row in existing_rows
    )
    assert all("notes" in row and "originals_subfolder" in row for row in creation_rows)
    assert {row["originals_subfolder"] for row in creation_rows} == {
        "Voices/Chapter06/English",
        "Voices/Chapter06/Japanese",
    }


def test_unicode_tab_file_uses_one_strict_physical_row_per_import(tmp_path) -> None:
    scenario = load_eval_bundle_v3(SUITE_V3).scenario("O22-AUDIO-TAB-03")
    case = materialize_import_case(
        scenario,
        version="2022.1",
        asset_root=tmp_path / "case",
    )
    path = case.tab_files[0].path
    data = path.read_bytes()

    assert not data.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in data
    lines = data.decode("utf-8").splitlines()
    assert len(lines) == 9
    assert all(len(line.split("\t")) == 6 for line in lines)
    headers = lines[0].split("\t")
    first = dict(zip(headers, lines[1].split("\t"), strict=True))
    assert first["Notes"] == "清晨·远景"
    assert first["Audio Source Notes"] == "录音机位 A"


def test_materializer_refuses_to_reuse_a_case_asset_root(tmp_path) -> None:
    scenario = load_eval_bundle_v3(SUITE_V3).scenario("O22-AUDIO-IMPORT-01")
    root = tmp_path / "case"
    materialize_import_case(scenario, version="2022.1", asset_root=root)
    with pytest.raises(ImportAssetMaterializationError, match="cannot be reused"):
        materialize_import_case(scenario, version="2022.1", asset_root=root)


def test_materializer_rejects_an_embedded_physical_tsv_separator(tmp_path) -> None:
    scenario = deepcopy(
        load_eval_bundle_v3(SUITE_V3).scenario("O22-AUDIO-TAB-03")
    )
    scenario.fixture["asset_spec"]["rows"][0]["notes"] += "\t远景"

    with pytest.raises(
        ImportAssetMaterializationError,
        match="physical row or column separators",
    ):
        materialize_import_case(
            scenario,
            version="2022.1",
            asset_root=tmp_path / "case",
        )


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


def _compound_unit(unit_id: str):
    profile = load_compound_heavy_profile(
        COMPOUND_PROFILE,
        unit_ids=(unit_id,),
    )
    return profile.units[0]


@pytest.mark.parametrize(
    "unit_id,root_prefix,bus_prefix",
    [
        (
            "CMP22-O22-AUDIO-IMPORT-02",
            r"\Actor-Mixer Hierarchy",
            r"\Master-Mixer Hierarchy",
        ),
        (
            "CMP25-O22-AUDIO-IMPORT-02",
            r"\Containers",
            r"\Busses",
        ),
        (
            "CMP22-O22-AUDIO-TAB-03",
            r"\Actor-Mixer Hierarchy",
            r"\Master-Mixer Hierarchy",
        ),
        (
            "CMP25-O22-AUDIO-TAB-03",
            r"\Containers",
            r"\Busses",
        ),
    ],
)
def test_compound_import_stages_files_without_an_executable_request(
    tmp_path: Path,
    unit_id: str,
    root_prefix: str,
    bus_prefix: str,
) -> None:
    unit = _compound_unit(unit_id)
    case = materialize_import_case(
        unit.scenario,
        version=unit.version,
        asset_root=tmp_path / unit_id,
    )

    assert case.requires_metadata_binding
    assert case.operation_requests == ()
    assert case.tab_files == ()
    assert len(case.metadata_queries) == 5
    assert all(
        str(row["target_path"]).startswith(root_prefix)
        for row in case.expected_rows
    )
    assert all(path.startswith(bus_prefix) for path in case.reference_fixture_paths.values())
    assert unit.scenario.render_prompt(case.visible_values)


def test_compound_direct_import_binds_defaults_row_overrides_and_inline_wav(
    tmp_path: Path,
) -> None:
    unit = _compound_unit("CMP22-O22-AUDIO-IMPORT-02")
    staged = materialize_import_case(
        unit.scenario,
        version=unit.version,
        asset_root=tmp_path / "weapons",
    )
    visible_weapon_rows = json.loads(staged.visible_values["import_rows"])
    assert all(
        Path(row["audio_file"]).is_absolute()
        and Path(row["audio_file"]).is_file()
        for row in visible_weapon_rows
    )
    bound = bind_import_live_metadata(
        staged,
        version=unit.version,
        discovery_payload={"agent_result": _sound_discovery()},
    )
    request = bound.operation_requests[0]
    arguments = request["arguments"]

    assert not bound.requires_metadata_binding
    assert request["operation"] == "audio.import"
    assert arguments["defaults"]["properties"] == [
        {"name": "IsLoopingEnabled", "value": True},
        {"name": "IgnoreParentMaxSoundInstance", "value": True},
        {"name": "UseMaxSoundPerInstance", "value": True},
        {"name": "MaxSoundPerInstance", "value": 5},
        {"name": "OverrideOutput", "value": True},
    ]
    assert arguments["defaults"]["references"][0]["name"] == "OutputBus"
    rifle_close = next(
        row for row in arguments["imports"] if row["object_path"].endswith("Rifle_Close")
    )
    assert rifle_close["properties"] == [
        {"name": "MaxSoundPerInstance", "value": 2}
    ]
    assert rifle_close["references"][0]["name"] == "OutputBus"
    effective = bound.expected_rows[0]
    assert {
        item["name"]: item["value"]
        for item in effective["compound_effective_properties"]
    }["OverrideOutput"] is True
    assert bound_import_metadata_tokens(bound) == (
        "IsLoopingEnabled",
        "IgnoreParentMaxSoundInstance",
        "UseMaxSoundPerInstance",
        "MaxSoundPerInstance",
        "OutputBus",
        "OverrideOutput",
    )
    protocol = build_metadata_transaction_protocol(
        bound.operation_requests,
        object_type="Sound",
        metadata_queries=bound.metadata_queries,
        required_tokens=bound_import_metadata_tokens(bound),
        expected_required_token_projection=project_required_metadata_tokens(
            _sound_discovery(),
            object_type="Sound",
            required_tokens=bound_import_metadata_tokens(bound),
        ),
        equivalence="audio_import_v1",
    )
    assert tuple(step.name for step in protocol.steps[:3]) == (
        "metadata.discover",
        "tx01.operation-schema",
        "tx01.preview",
    )
    preview_argument = protocol.steps[2].arguments[2]
    assert protocol.turn_prefix_counts == (3, 7)
    assert isinstance(preview_argument, MetadataBoundJsonArgument)
    assert preview_argument.expected == request
    assert preview_argument.object_type == "Sound"
    assert preview_argument.equivalence == "audio_import_v1"
    assert preview_argument.expected_required_token_projection is not None

    mission = _compound_unit("CMP22-O22-AUDIO-IMPORT-03")
    mission_staged = materialize_import_case(
        mission.scenario,
        version=mission.version,
        asset_root=tmp_path / "missions",
    )
    visible_mission_rows = json.loads(
        mission_staged.visible_values["import_rows"]
    )
    visible_inline = [
        row for row in visible_mission_rows if "audio_file_base64" in row
    ]
    assert len(visible_inline) == 2
    assert all("audio_file" not in row for row in visible_inline)
    assert all(
        row["audio_file_base64"].startswith("Missions/")
        and len(row["audio_file_base64"]) < 512
        for row in visible_inline
    )
    mission_bound = bind_import_live_metadata(
        mission_staged,
        version=mission.version,
        discovery_payload=_sound_discovery(),
    )
    inline = [
        row
        for row in mission_bound.operation_requests[0]["arguments"]["imports"]
        if "audio_file_base64" in row
    ]
    assert len(inline) == 2
    assert all("audio_file" not in row for row in inline)
    assert all("|UklGR" in row["audio_file_base64"] for row in inline)
    assert {
        row["audio_file_base64"] for row in inline
    } == {
        row["audio_file_base64"] for row in visible_inline
    }


def test_compound_tab_import_materializes_live_headers_dependency_and_base64(
    tmp_path: Path,
) -> None:
    unit = _compound_unit("CMP25-O22-AUDIO-TAB-03")
    staged = materialize_import_case(
        unit.scenario,
        version=unit.version,
        asset_root=tmp_path / "city",
    )
    bound = bind_import_live_metadata(
        staged,
        version=unit.version,
        discovery_payload=_sound_discovery(),
    )

    assert len(bound.tab_files) == 1
    lines = bound.tab_files[0].path.read_text(encoding="utf-8").splitlines()
    headers = lines[0].split("\t")
    assert "Audio File Base64" in headers
    assert "Property[IsLoopingEnabled]" in headers
    assert "Property[MaxSoundPerInstance]" in headers
    assert "Reference[OutputBus]" in headers
    assert "Property[OverrideOutput]" in headers
    rows = [dict(zip(headers, line.split("\t"), strict=True)) for line in lines[1:]]
    inline = [row for row in rows if row["Audio File Base64"]]
    assert len(inline) == 2
    assert all(not row["Audio File"] for row in inline)
    assert all(row["Property[OverrideOutput]"] == "true" for row in rows)
    assert all(row["Reference[OutputBus]"].startswith(r"\Busses") for row in rows)
    request = bound.operation_requests[0]
    assert request["version"] == "2025.1"
    assert request["arguments"]["import_location"]["value"].startswith(r"\Containers")


@pytest.mark.parametrize(
    "unit_id",
    (
        "CMP22-O22-AUDIO-TAB-04",
        "CMP25-O22-AUDIO-TAB-04",
    ),
)
def test_compound_use_existing_tab_seals_exact_dynamic_cell_matrix(
    tmp_path: Path,
    unit_id: str,
) -> None:
    unit = _compound_unit(unit_id)
    staged = materialize_import_case(
        unit.scenario,
        version=unit.version,
        asset_root=tmp_path / unit_id,
    )
    bound = bind_import_live_metadata(
        staged,
        version=unit.version,
        discovery_payload=_sound_discovery(),
    )

    lines = bound.tab_files[0].path.read_text(encoding="utf-8").splitlines()
    headers = lines[0].split("\t")
    rows = [dict(zip(headers, line.split("\t"), strict=True)) for line in lines[1:]]

    dynamic_headers = [
        "Property[IsLoopingEnabled]",
        "Property[IgnoreParentMaxSoundInstance]",
        "Property[UseMaxSoundPerInstance]",
        "Property[MaxSoundPerInstance]",
        "Reference[OutputBus]",
        "Property[OverrideOutput]",
    ]
    assert headers == [
        "Audio File",
        "Object Path",
        "Object Type",
        "OriginalsSubFolder",
        "Notes",
        *dynamic_headers,
    ]
    assert len(rows) == 6
    assert all(row["Object Type"] == "Sound SFX" for row in rows)
    bus_path = bound.metadata_binding["reference_targets"]["cockpit_bus"]["value"]
    blank = {header: "" for header in dynamic_headers}
    expected_created = [
        {
            "Property[IsLoopingEnabled]": "true",
            "Property[IgnoreParentMaxSoundInstance]": "true",
            "Property[UseMaxSoundPerInstance]": "true",
            "Property[MaxSoundPerInstance]": maximum,
            "Reference[OutputBus]": bus_path,
            "Property[OverrideOutput]": "true",
        }
        for maximum in ("2", "4", "2")
    ]
    assert [
        {header: row[header] for header in dynamic_headers}
        for row in rows
    ] == [blank, blank, blank, *expected_created]
    assert [
        row["compound_dynamic_mode"]
        for row in bound.expected_rows
    ] == ["preserve", "preserve", "preserve", "mutate", "mutate", "mutate"]
    protocol = build_metadata_transaction_protocol(
        bound.operation_requests,
        object_type="Sound",
        metadata_queries=bound.metadata_queries,
        required_tokens=bound_import_metadata_tokens(bound),
        expected_required_token_projection=project_required_metadata_tokens(
            _sound_discovery(),
            object_type="Sound",
            required_tokens=bound_import_metadata_tokens(bound),
        ),
        equivalence="audio_import_tab_v1",
    )
    assert tuple(step.name for step in protocol.steps[:3]) == (
        "metadata.discover",
        "tx01.operation-schema",
        "tx01.preview",
    )


def test_compound_tab_dynamic_header_rejects_unknown_row_key(
    tmp_path: Path,
) -> None:
    unit = _compound_unit("CMP22-O22-AUDIO-TAB-04")
    scenario = deepcopy(unit.scenario)
    headers = scenario.fixture["asset_spec"]["compound"]["tsv_dynamic_headers"]
    headers[0]["values"]["cockpit_typo"] = True

    with pytest.raises(
        ImportAssetMaterializationError,
        match="dynamic header values reference unknown rows",
    ):
        materialize_import_case(
            scenario,
            version=unit.version,
            asset_root=tmp_path / "unknown-row",
        )


def test_compound_import_refuses_ambiguous_or_rebound_metadata(
    tmp_path: Path,
) -> None:
    unit = _compound_unit("CMP22-O22-AUDIO-IMPORT-02")
    staged = materialize_import_case(
        unit.scenario,
        version=unit.version,
        asset_root=tmp_path / "case",
    )
    ambiguous = _sound_discovery()
    duplicate = deepcopy(ambiguous["candidates"][0])
    duplicate["name"] = "IsLoopingEnabledAlias"
    ambiguous["candidates"].append(duplicate)

    with pytest.raises(ImportAssetMaterializationError, match="resolved 2 candidates"):
        bind_import_live_metadata(
            staged,
            version=unit.version,
            discovery_payload=ambiguous,
        )

    bound = bind_import_live_metadata(
        staged,
        version=unit.version,
        discovery_payload=_sound_discovery(),
    )
    with pytest.raises(ImportAssetMaterializationError, match="immutable once bound"):
        bind_import_live_metadata(
            bound,
            version=unit.version,
            discovery_payload=_sound_discovery(),
        )
    with pytest.raises(
        ImportAssetMaterializationError,
        match="completed live binding",
    ):
        bound_import_metadata_tokens(staged)
