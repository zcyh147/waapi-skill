from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.semantic.support.codex_compound_heavy_v1 import (
    API_URIS,
    BASE_SUITE_REPO_RELATIVE,
    CASE_FILE_CONTRACT,
    DATA_FILE_NAMES,
    EXPECTED_API_BY_CASE_ID,
    EXPECTED_CASE_IDS_BY_FILE,
    LOGICAL_CASE_COUNT,
    PROFILE_CONTRACT,
    PROFILE_ID,
    TASK_COUNT,
    TRANSACTION_COUNT,
    USER_TURN_COUNT,
    VERSIONS,
    CompoundHeavyProfileError,
    load_compound_heavy_profile,
)
from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_SUITE_PATH = REPO_ROOT / BASE_SUITE_REPO_RELATIVE
COMMITTED_PROFILE_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "compound-heavy-v1"
    / "profile.json"
)


def _profile_document() -> dict[str, Any]:
    return {
        "contract": PROFILE_CONTRACT,
        "profile_id": PROFILE_ID,
        "base_suite": BASE_SUITE_REPO_RELATIVE,
        "data_files": list(DATA_FILE_NAMES),
        "versions": list(VERSIONS),
        "apis": list(API_URIS),
        "totals": {
            "logical_case_count": LOGICAL_CASE_COUNT,
            "task_count": TASK_COUNT,
            "user_turn_count": USER_TURN_COUNT,
            "transaction_count": TRANSACTION_COUNT,
        },
    }


def _case_document(base_scenario_id: str) -> dict[str, Any]:
    return {
        "base_scenario_id": base_scenario_id,
        "api": EXPECTED_API_BY_CASE_ID[base_scenario_id],
        "versions": list(VERSIONS),
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_valid_profile(
    tmp_path: Path,
    *,
    mutate_profile: Callable[[dict[str, Any]], None] | None = None,
    mutate_case: (
        Callable[[str, int, dict[str, Any]], None] | None
    ) = None,
) -> Path:
    root = tmp_path / "compound-heavy-v1"
    root.mkdir()
    profile = _profile_document()
    if mutate_profile is not None:
        mutate_profile(profile)
    profile_path = root / "profile.json"
    _write_json(profile_path, profile)

    bundle = load_eval_bundle_v3(BASE_SUITE_PATH)
    for file_name in DATA_FILE_NAMES:
        rows = [
            _case_document(base_scenario_id)
            for base_scenario_id in EXPECTED_CASE_IDS_BY_FILE[file_name]
        ]
        for index, row in enumerate(rows):
            if mutate_case is not None:
                mutate_case(file_name, index, row)
        if file_name == "object-create-set.json":
            scenario = bundle.scenario("OBJ22-F-CREATE-02")
            rows[0]["prompt"] = (
                scenario.prompt
                + " 完成后请同时核对新对象的层级和初始属性是否正确。"
            )
            rows[0]["confirmation_prompt"] = (
                "这个预览符合我的需求，请执行并核对最终结果。"
            )
            rows[0]["fixture_patch"] = {
                "asset_spec": {
                    "compound_profile_marker": {
                        "enabled": True,
                        "revision": 1,
                    }
                }
            }
        _write_json(
            root / file_name,
            {
                "contract": CASE_FILE_CONTRACT,
                "cases": rows,
            },
        )
    return profile_path


def _rewrite_json(
    path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    _write_json(path, value)


def test_committed_profile_declares_only_the_closed_data_source_shape() -> None:
    root = json.loads(COMMITTED_PROFILE_PATH.read_text(encoding="utf-8"))

    assert root == _profile_document()
    assert all(Path(name).parts == (name,) for name in root["data_files"])


def test_loader_expands_twelve_cases_into_twenty_four_unique_two_turn_units(
    tmp_path: Path,
) -> None:
    profile = load_compound_heavy_profile(_write_valid_profile(tmp_path))

    assert len(profile.cases) == LOGICAL_CASE_COUNT == 12
    assert len(profile.units) == TASK_COUNT == 24
    assert sum(unit.user_turn_count for unit in profile.units) == (
        USER_TURN_COUNT
    ) == 48
    assert sum(unit.transaction_count for unit in profile.units) == (
        TRANSACTION_COUNT
    ) == 24
    assert len({unit.unit_id for unit in profile.units}) == TASK_COUNT
    assert [unit.version for unit in profile.units[:12]] == ["2022.1"] * 12
    assert [unit.version for unit in profile.units[12:]] == ["2025.1"] * 12
    assert [unit.unit_id for unit in profile.units[:2]] == [
        "CMP22-O22-AUDIO-IMPORT-02",
        "CMP22-O22-AUDIO-IMPORT-03",
    ]
    assert all(unit.scenario.id == unit.base_scenario_id for unit in profile.units)
    assert all(unit.scenario.versions == (unit.version,) for unit in profile.units)
    assert all(
        tuple(turn.kind for turn in unit.turns)
        == ("request", "confirmation")
        for unit in profile.units
    )
    assert all(
        unit.turns[1].transaction_index == 1
        and not unit.turns[1].expects_next_preview
        for unit in profile.units
    )


def test_loader_clones_prompt_confirmation_and_fixture_without_mutating_base(
    tmp_path: Path,
) -> None:
    base_bundle = load_eval_bundle_v3(BASE_SUITE_PATH)
    base = base_bundle.scenario("OBJ22-F-CREATE-02")
    base_fixture = copy.deepcopy(dict(base.fixture))
    profile = load_compound_heavy_profile(_write_valid_profile(tmp_path))
    clones = [
        unit
        for unit in profile.units
        if unit.base_scenario_id == "OBJ22-F-CREATE-02"
    ]

    assert {unit.version for unit in clones} == set(VERSIONS)
    assert all(unit.scenario is not base for unit in clones)
    assert all(
        "同时核对新对象的层级" in unit.scenario.prompt
        for unit in clones
    )
    assert all(
        unit.scenario.confirmation_prompt
        == "这个预览符合我的需求，请执行并核对最终结果。"
        for unit in clones
    )
    assert all(
        unit.scenario.fixture["asset_spec"]["compound_profile_marker"]
        == {"enabled": True, "revision": 1}
        for unit in clones
    )
    assert dict(base.fixture) == base_fixture
    assert "asset_spec" not in base.fixture


def test_loader_filters_only_after_validating_the_complete_profile(
    tmp_path: Path,
) -> None:
    profile_path = _write_valid_profile(tmp_path)
    selected = load_compound_heavy_profile(
        profile_path,
        unit_ids=("CMP25-O22-SB-GENERATE-03",),
        versions=("2025.1",),
    )

    assert [unit.unit_id for unit in selected.units] == [
        "CMP25-O22-SB-GENERATE-03"
    ]
    assert len(selected.cases) == LOGICAL_CASE_COUNT

    with pytest.raises(CompoundHeavyProfileError, match="unknown"):
        load_compound_heavy_profile(profile_path, unit_ids=("UNKNOWN",))
    with pytest.raises(CompoundHeavyProfileError, match="no units for versions"):
        load_compound_heavy_profile(profile_path, versions=("2024.1",))
    with pytest.raises(CompoundHeavyProfileError, match="duplicate"):
        load_compound_heavy_profile(
            profile_path,
            versions=("2025.1", "2025.1"),
        )
    with pytest.raises(CompoundHeavyProfileError, match="no compound-heavy units"):
        load_compound_heavy_profile(
            profile_path,
            unit_ids=("CMP22-O22-AUDIO-IMPORT-02",),
            versions=("2025.1",),
        )


def test_definition_digest_covers_profile_and_each_data_file(
    tmp_path: Path,
) -> None:
    profile_path = _write_valid_profile(tmp_path)
    first = load_compound_heavy_profile(profile_path)
    audio_path = profile_path.parent / "audio-import.json"
    audio_path.write_text(
        audio_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    second = load_compound_heavy_profile(profile_path)

    assert [name for name, _ in first.source_digests] == [
        "profile.json",
        *DATA_FILE_NAMES,
    ]
    assert len(first.definition_sha256) == 64
    assert first.definition_sha256 != second.definition_sha256


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda root: root.__setitem__("unexpected", True),
            "schema is not closed",
        ),
        (
            lambda root: root["totals"].__setitem__("task_count", 25),
            "totals drifted",
        ),
        (
            lambda root: root["data_files"].__setitem__(
                0,
                "../audio-import.json",
            ),
            "sibling JSON filenames",
        ),
    ],
)
def test_profile_document_fails_closed(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    profile_path = _write_valid_profile(tmp_path, mutate_profile=mutate)

    with pytest.raises(CompoundHeavyProfileError, match=message):
        load_compound_heavy_profile(profile_path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda _file, index, row: (
                row.__setitem__("unexpected", True) if index == 0 else None
            ),
            "schema is not closed",
        ),
        (
            lambda _file, index, row: (
                row.__setitem__("api", "ak.wwise.core.object.get")
                if index == 0
                else None
            ),
            "does not match",
        ),
        (
            lambda _file, index, row: (
                row.__setitem__(
                    "fixture_patch",
                    {"adapter": "unreviewed_callback"},
                )
                if index == 0
                else None
            ),
            "may patch only asset_spec or prerequisites",
        ),
    ],
)
def test_case_document_fails_closed(
    tmp_path: Path,
    mutate: Callable[[str, int, dict[str, Any]], None],
    message: str,
) -> None:
    profile_path = _write_valid_profile(tmp_path, mutate_case=mutate)

    with pytest.raises(CompoundHeavyProfileError, match=message):
        load_compound_heavy_profile(profile_path)


def test_prompt_override_must_preserve_visible_input_closure(
    tmp_path: Path,
) -> None:
    profile_path = _write_valid_profile(tmp_path)
    audio_path = profile_path.parent / "audio-import.json"

    def remove_inputs(root: dict[str, Any]) -> None:
        root["cases"][0]["prompt"] = (
            "请把准备好的环境音批量导入到指定层级，并完整核对导入后的结构。"
        )

    _rewrite_json(audio_path, remove_inputs)
    with pytest.raises(
        CompoundHeavyProfileError,
        match="visible-input closure mismatch",
    ):
        load_compound_heavy_profile(profile_path)


def test_duplicate_json_keys_are_rejected_before_schema_validation(
    tmp_path: Path,
) -> None:
    profile_path = _write_valid_profile(tmp_path)
    profile_path.write_text(
        '{"contract":"a","contract":"b"}\n',
        encoding="utf-8",
    )

    with pytest.raises(CompoundHeavyProfileError, match="duplicate JSON"):
        load_compound_heavy_profile(profile_path)
