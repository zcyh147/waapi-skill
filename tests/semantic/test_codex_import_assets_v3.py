from __future__ import annotations

import json
import wave
from copy import deepcopy
from pathlib import Path

import pytest

from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
from tests.semantic.support.codex_import_assets_v3 import (
    ImportAssetMaterializationError,
    materialize_import_case,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_V3 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"
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
