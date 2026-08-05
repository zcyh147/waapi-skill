from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_compound_heavy_v1 import PROFILE_ID


def _required_path_args(tmp_path: Path) -> list[str]:
    codex = tmp_path / "codex.exe"
    auth = tmp_path / "auth.json"
    live = tmp_path / "live-environment.json"
    for path in (codex, auth, live):
        path.write_text("{}\n", encoding="utf-8")
    codex.chmod(0o755)
    return [
        "--codex-binary",
        str(codex),
        "--auth-json",
        str(auth),
        "--live-config",
        str(live),
    ]


def _matrix_args(tmp_path: Path, extra: Sequence[str] = ()) -> list[str]:
    return [
        "--profile",
        PROFILE_ID,
        "--iteration-root",
        str(tmp_path / "matrix"),
        *_required_path_args(tmp_path),
        *extra,
    ]


def _campaign_args(tmp_path: Path, extra: Sequence[str] = ()) -> list[str]:
    return [
        "--campaign-root",
        str(tmp_path / "campaign"),
        "--profile",
        PROFILE_ID,
        *_required_path_args(tmp_path),
        *extra,
    ]


def test_profile_is_executable_in_both_entry_points() -> None:
    assert PROFILE_ID == matrix.COMPOUND_HEAVY_V1_PROFILE_ID
    assert PROFILE_ID == campaign.COMPOUND_HEAVY_V1_PROFILE_ID
    assert PROFILE_ID in matrix.EXECUTABLE_V3_PROFILE_IDS
    assert PROFILE_ID in campaign.EXECUTABLE_V3_PROFILE_IDS


def test_matrix_and_campaign_default_to_the_closed_terra_profile(
    tmp_path: Path,
) -> None:
    matrix_options = matrix.parse_args(_matrix_args(tmp_path))
    campaign_options = campaign.parse_args(_campaign_args(tmp_path))

    for options in (matrix_options, campaign_options):
        assert options.profile == PROFILE_ID
        assert (
            options.suite_path
            == matrix.DEFAULT_COMPOUND_HEAVY_V1_SUITE.resolve()
        )
        assert options.model == "gpt-5.6-terra"
        assert options.reasoning_effort == "medium"
        assert options.service_tier == "default"


@pytest.mark.parametrize(
    "build_args",
    [_matrix_args, _campaign_args],
)
@pytest.mark.parametrize(
    "extra",
    [
        ("--model", "gpt-5.6-sol"),
        ("--reasoning-effort", "high"),
        ("--service-tier", "priority"),
        ("--version", "2023.1"),
        ("--version", "2024.1"),
    ],
)
def test_entry_points_reject_unpinned_model_settings_and_versions(
    tmp_path: Path,
    build_args: Callable[[Path, Sequence[str]], list[str]],
    extra: Sequence[str],
) -> None:
    parser = (
        campaign.parse_args
        if build_args is _campaign_args
        else matrix.parse_args
    )

    with pytest.raises(SystemExit):
        parser(build_args(tmp_path, extra))


def test_matrix_loader_filters_by_compound_unit_id_and_version(
    tmp_path: Path,
) -> None:
    selected_options = matrix.parse_args(
        _matrix_args(
            tmp_path,
            (
                "--case-id",
                "CMP25-O22-SB-GENERATE-03",
                "--version",
                "2025.1",
            ),
        )
    )
    selected = matrix.load_heavy_v3_units(selected_options)
    version_options = matrix.parse_args(
        _matrix_args(
            tmp_path,
            ("--version", "2022.1"),
        )
    )
    version_units = matrix.load_heavy_v3_units(version_options)

    assert [unit.unit_id for unit in selected] == [
        "CMP25-O22-SB-GENERATE-03"
    ]
    assert selected[0].base_scenario_id == "O22-SB-GENERATE-03"
    assert selected[0].scenario.id == "O22-SB-GENERATE-03"
    assert len(version_units) == 12
    assert {unit.version for unit in version_units} == {"2022.1"}


def test_matrix_and_campaign_unit_rows_preserve_base_scenario_identity(
    tmp_path: Path,
) -> None:
    options = matrix.parse_args(
        _matrix_args(
            tmp_path,
            (
                "--case-id",
                "CMP25-O22-AUDIO-IMPORT-02",
                "--version",
                "2025.1",
            ),
        )
    )
    unit = matrix.load_heavy_v3_units(options)[0]
    matrix_row = matrix._heavy_v3_unit_row(unit, sequence=1)
    campaign_row = campaign.heavy_v3_unit_row(unit, sequence=1)

    for row in (matrix_row, campaign_row):
        assert row["scenario_id"] == "CMP25-O22-AUDIO-IMPORT-02"
        assert row["base_scenario_id"] == "O22-AUDIO-IMPORT-02"
        assert row["version"] == "2025.1"
        assert row["api"] == "ak.wwise.core.audio.import"
