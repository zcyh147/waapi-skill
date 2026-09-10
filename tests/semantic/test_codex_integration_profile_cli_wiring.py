from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_campaign import sha256_file, stable_tree_sha256
from tests.semantic.support.codex_integration_workflows import (
    LEGACY_UNIT_ID_BY_PUBLIC_ID,
)


DATA_ROOT = Path(__file__).resolve().parent / "data"


def _dependency_args(tmp_path: Path) -> list[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    codex = tmp_path / "codex.exe"
    auth = tmp_path / "auth.json"
    live = tmp_path / "live-environment.json"
    codex.write_text("not invoked\n", encoding="utf-8")
    codex.chmod(0o755)
    auth.write_text("{}\n", encoding="utf-8")
    live.write_text("{}\n", encoding="utf-8")
    return [
        "--codex-binary",
        str(codex),
        "--auth-json",
        str(auth),
        "--live-config",
        str(live),
    ]


def _matrix_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--profile",
        matrix.INTEGRATION_PROFILE_ID,
        *_dependency_args(tmp_path),
        *extra,
    ]


def _campaign_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--campaign-root",
        str(tmp_path / "campaign"),
        "--profile",
        campaign.INTEGRATION_PROFILE_ID,
        *_dependency_args(tmp_path),
        *extra,
    ]


def _copy_suite(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    for name in (
        "integration",
        "integration-workflows-v1",
        "integration-workflows-v2",
    ):
        shutil.copytree(DATA_ROOT / name, target / name)
    return target / "integration" / "profile.json"


def test_public_cli_defaults_are_locked_and_legacy_defaults_are_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda value: Path(str(value)).resolve(),
    )
    matrix_options = matrix.parse_args(_matrix_args(tmp_path / "matrix"))
    campaign_options = campaign.parse_args(_campaign_args(tmp_path / "campaign"))

    assert matrix_options.profile == campaign_options.profile == "integration"
    assert matrix.SEMANTIC_BOOTSTRAP_PROFILE_IDS == (
        campaign.SEMANTIC_BOOTSTRAP_PROFILE_IDS
    ) == frozenset(
        {
            matrix.TYPED_INPUT_PROFILE_ID,
            matrix.DEEP_BUSINESS_ACCEPTANCE_PROFILE_ID,
            matrix.INTEGRATION_PROFILE_ID,
        }
    )
    assert matrix_options.suite_path == matrix.DEFAULT_INTEGRATION_SUITE.resolve()
    assert campaign_options.suite_path == matrix.DEFAULT_INTEGRATION_SUITE.resolve()
    assert matrix_options.iteration_root == (
        matrix.DEFAULT_INTEGRATION_ITERATION_ROOT.resolve()
    )
    assert (
        matrix_options.model,
        matrix_options.reasoning_effort,
        matrix_options.service_tier,
    ) == ("gpt-5.6-terra", "medium", "default")
    assert (
        campaign_options.model,
        campaign_options.reasoning_effort,
        campaign_options.service_tier,
    ) == ("gpt-5.6-terra", "medium", "default")
    assert matrix_options.timeout_seconds == 360.0
    assert campaign_options.timeout_seconds == 360.0

    for profile_id, suite_path, iteration_root in (
        (
            matrix.INTEGRATION_WORKFLOWS_V1_PROFILE_ID,
            matrix.DEFAULT_INTEGRATION_WORKFLOWS_V1_SUITE,
            matrix.DEFAULT_INTEGRATION_WORKFLOWS_V1_ITERATION_ROOT,
        ),
        (
            matrix.INTEGRATION_WORKFLOWS_V2_PROFILE_ID,
            matrix.DEFAULT_INTEGRATION_WORKFLOWS_V2_SUITE,
            matrix.DEFAULT_INTEGRATION_WORKFLOWS_V2_ITERATION_ROOT,
        ),
    ):
        legacy = matrix.parse_args(
            [
                "--profile",
                profile_id,
                *_dependency_args(tmp_path / profile_id),
            ]
        )
        assert legacy.suite_path == suite_path.resolve()
        assert legacy.iteration_root == iteration_root.resolve()
        assert legacy.timeout_seconds == 240.0


@pytest.mark.parametrize("surface", ("matrix", "campaign"))
def test_public_integration_explicit_timeout_override_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda value: Path(str(value)).resolve(),
    )
    argv = (
        _matrix_args(tmp_path / "matrix", "--timeout", "275.5")
        if surface == "matrix"
        else _campaign_args(tmp_path / "campaign", "--timeout", "275.5")
    )

    options = (matrix.parse_args if surface == "matrix" else campaign.parse_args)(
        argv
    )

    assert options.timeout_seconds == 275.5


@pytest.mark.parametrize("surface", ("matrix", "campaign"))
def test_public_help_names_integration_without_advertising_legacy_profiles(
    capsys: pytest.CaptureFixture[str],
    surface: str,
) -> None:
    parser = matrix.parse_args if surface == "matrix" else campaign.parse_args

    with pytest.raises(SystemExit) as captured:
        parser(["--help"])

    assert captured.value.code == 0
    help_text = capsys.readouterr().out
    assert "integration" in help_text
    assert matrix.INTEGRATION_WORKFLOWS_V1_PROFILE_ID not in help_text
    assert matrix.INTEGRATION_WORKFLOWS_V2_PROFILE_ID not in help_text


@pytest.mark.parametrize("surface", ("matrix", "campaign"))
def test_invalid_profile_error_lists_only_public_profiles(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    surface: str,
) -> None:
    parser = matrix.parse_args if surface == "matrix" else campaign.parse_args
    argv = ["--profile", "not-a-profile"]
    if surface == "campaign":
        argv[:0] = ["--campaign-root", str(tmp_path / "campaign")]

    with pytest.raises(SystemExit):
        parser(argv)

    error_text = capsys.readouterr().err
    assert "integration" in error_text
    assert matrix.INTEGRATION_WORKFLOWS_V1_PROFILE_ID not in error_text
    assert matrix.INTEGRATION_WORKFLOWS_V2_PROFILE_ID not in error_text


@pytest.mark.parametrize(
    "profile_id",
    (
        matrix.INTEGRATION_WORKFLOWS_V1_PROFILE_ID,
        matrix.INTEGRATION_WORKFLOWS_V2_PROFILE_ID,
    ),
)
@pytest.mark.parametrize("surface", ("matrix", "campaign"))
def test_exact_legacy_profile_ids_remain_parseable_for_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile_id: str,
    surface: str,
) -> None:
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda value: Path(str(value)).resolve(),
    )
    argv = ["--profile", profile_id, *_dependency_args(tmp_path / surface)]
    if surface == "campaign":
        argv[:0] = ["--campaign-root", str(tmp_path / "campaign")]

    parsed = (matrix.parse_args if surface == "matrix" else campaign.parse_args)(
        argv
    )

    assert parsed.profile == profile_id


@pytest.mark.parametrize(
    "override",
    (
        ("--model", "gpt-5.6-sol"),
        ("--reasoning-effort", "high"),
        ("--service-tier", "priority"),
        ("--version", "2024.1"),
    ),
)
def test_public_profile_rejects_model_or_version_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    override: tuple[str, str],
) -> None:
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda value: Path(str(value)).resolve(),
    )

    with pytest.raises(SystemExit):
        matrix.parse_args(_matrix_args(tmp_path, *override))


def test_matrix_loader_accepts_public_and_legacy_case_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda value: Path(str(value)).resolve(),
    )
    options = matrix.parse_args(_matrix_args(tmp_path))
    public_id = "INT25-RIFLE"
    legacy_id = LEGACY_UNIT_ID_BY_PUBLIC_ID[public_id]

    complete = matrix.load_heavy_v3_units(options)
    public = matrix.load_heavy_v3_units(
        replace(options, case_ids=(public_id,), versions=("2025.1",))
    )
    legacy = matrix.load_heavy_v3_units(
        replace(options, case_ids=(legacy_id,), versions=("2025.1",))
    )

    assert len(complete) == 12
    assert [unit.unit_id for unit in complete[:6]] == [
        "INT22-WEATHER",
        "INT22-ALARM",
        "INT22-HARBOR",
        "INT22-RIFLE",
        "INT22-FOOTSTEPS",
        "INT22-WEAPONS",
    ]
    assert [unit.unit_id for unit in public] == [public_id]
    assert [unit.unit_id for unit in legacy] == [public_id]


@pytest.mark.parametrize("surface", ("matrix", "campaign"))
def test_public_profile_rejects_unknown_or_duplicate_alias_case_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda value: Path(str(value)).resolve(),
    )
    public_id = "INT22-WEATHER"
    legacy_id = LEGACY_UNIT_ID_BY_PUBLIC_ID[public_id]
    parser = matrix.parse_args if surface == "matrix" else campaign.parse_args
    base = (
        _matrix_args(tmp_path / "duplicate")
        if surface == "matrix"
        else _campaign_args(tmp_path / "duplicate")
    )

    with pytest.raises(SystemExit):
        parser(
            [
                *base,
                "--case-id",
                public_id,
                "--case-id",
                legacy_id,
            ]
        )
    unknown_base = (
        _matrix_args(tmp_path / "unknown")
        if surface == "matrix"
        else _campaign_args(tmp_path / "unknown")
    )
    with pytest.raises(SystemExit):
        parser([*unknown_base, "--case-id", "INT22-NOT-A-WORKFLOW"])


def test_public_and_legacy_case_spellings_seal_the_same_public_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda value: Path(str(value)).resolve(),
    )
    public_id = "INT25-RIFLE"
    legacy_id = LEGACY_UNIT_ID_BY_PUBLIC_ID[public_id]
    matrix_base = _matrix_args(tmp_path / "matrix-options")
    public_matrix_options = matrix.parse_args(
        [*matrix_base, "--case-id", public_id]
    )
    legacy_matrix_options = matrix.parse_args(
        [*matrix_base, "--case-id", legacy_id]
    )
    assert public_matrix_options == legacy_matrix_options
    assert public_matrix_options.case_ids == (public_id,)

    base = _campaign_args(tmp_path)
    public_options = campaign.parse_args([*base, "--case-id", public_id])
    legacy_options = campaign.parse_args([*base, "--case-id", legacy_id])

    assert public_options == legacy_options
    assert public_options.case_ids == legacy_options.case_ids == (public_id,)
    assert campaign.heavy_v3_immutable_options(public_options)["case_ids"] == [
        public_id
    ]
    units = campaign.load_heavy_v3_campaign_units(legacy_options)
    argv = campaign.build_heavy_v3_child_argv(
        legacy_options,
        units=units,
        matrix_root=tmp_path / "matrix",
    )
    assert [
        argv[index + 1]
        for index, value in enumerate(argv)
        if value == "--case-id"
    ] == [public_id]

    monkeypatch.setattr(
        campaign,
        "_codex_version_fingerprint",
        lambda _binary, *, windows_powershell_core_host=None: "codex-cli synthetic",
    )
    monkeypatch.setattr(campaign.importlib.metadata, "distributions", lambda: ())
    monkeypatch.setattr(campaign, "_codex_runtime_fingerprints", lambda _binary: [])
    monkeypatch.setattr(
        campaign,
        "_heavy_v3_live_input_fingerprints",
        lambda _options, *, unit_rows: {"synthetic_units": len(unit_rows)},
    )
    effective = campaign.build_heavy_v3_effective_config(
        legacy_options,
        units=units,
        required_units={public_id: (campaign.HEAVY_V3_PHASE,)},
    )
    assert effective["selection"]["case_ids"] == [public_id]
    assert effective["options"]["case_ids"] == [public_id]


def test_child_argv_uses_public_profile_and_public_unit_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda value: Path(str(value)).resolve(),
    )
    options = campaign.parse_args(_campaign_args(tmp_path))
    units = campaign.load_heavy_v3_campaign_units(options)

    argv = campaign.build_heavy_v3_child_argv(
        options,
        units=(units[0], units[-1]),
        matrix_root=tmp_path / "matrix",
    )

    assert argv[argv.index("--profile") + 1] == "integration"
    assert [
        argv[index + 1]
        for index, value in enumerate(argv)
        if value == "--case-id"
    ] == ["INT22-WEATHER", "INT25-WEAPONS"]
    assert argv[argv.index("--suite") + 1] == str(
        matrix.DEFAULT_INTEGRATION_SUITE.resolve()
    )


def test_legacy_suite_fingerprint_shape_is_unchanged(
    tmp_path: Path,
) -> None:
    options = campaign.CampaignOptions(
        campaign_root=tmp_path / "campaign",
        resume=False,
        verify_only=False,
        profile=campaign.INTEGRATION_WORKFLOWS_V1_PROFILE_ID,
        suite_path=matrix.DEFAULT_INTEGRATION_WORKFLOWS_V1_SUITE.resolve(),
        skill_source=matrix.SKILL_ROOT.resolve(),
        codex_binary=tmp_path / "codex",
        auth_json=tmp_path / "auth.json",
        live_config=tmp_path / "live.json",
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        service_tier="default",
        timeout_seconds=240.0,
        case_ids=(),
        versions=(),
        pair_ids=(),
        offline_only=False,
        lock_timeout_seconds=10.0,
        max_pre_action_retries=1,
    )
    dependency_root = options.suite_path.parent

    assert campaign.build_heavy_v3_suite_fingerprint(options) == {
        "path": str(options.suite_path),
        "sha256": sha256_file(options.suite_path),
        "dependency_root": str(dependency_root),
        "dependency_tree_sha256": stable_tree_sha256(
            dependency_root,
            exclude_names=campaign._SUITE_TREE_EXCLUDE_NAMES,
        ),
    }


def test_effective_config_fingerprints_both_components_and_replay_detects_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite_path = _copy_suite(tmp_path)
    dependency_args = _dependency_args(tmp_path / "dependencies")
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda value: Path(str(value)).resolve(),
    )
    options = campaign.parse_args(
        [
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--profile",
            "integration",
            "--suite",
            str(suite_path),
            *dependency_args,
        ]
    )
    units = campaign.load_heavy_v3_campaign_units(options)
    monkeypatch.setattr(
        campaign,
        "_codex_version_fingerprint",
        lambda _binary, *, windows_powershell_core_host=None: "codex-cli synthetic",
    )
    monkeypatch.setattr(campaign.importlib.metadata, "distributions", lambda: ())
    monkeypatch.setattr(campaign, "_codex_runtime_fingerprints", lambda _binary: [])
    monkeypatch.setattr(
        campaign,
        "_heavy_v3_live_input_fingerprints",
        lambda _options, *, unit_rows: {"synthetic_units": len(unit_rows)},
    )

    effective = campaign.build_heavy_v3_effective_config(
        options,
        units=units,
        required_units={
            unit.unit_id: (campaign.HEAVY_V3_PHASE,)
            for unit in units
        },
    )
    composition = effective["suite"]["composition"]

    assert len(composition["components"]) == 2
    assert [
        Path(row["profile_path"]).parent.name
        for row in composition["components"]
    ] == ["integration-workflows-v1", "integration-workflows-v2"]
    assert all(row["definition_sha256"] for row in composition["components"])
    assert [
        source["relative_path"]
        for source in composition["components"][1]["files"]
    ] == [
        "profile.json",
        "workflows.json",
        "baseline-2022.1.json",
        "baseline-2025.1.json",
    ]
    assert composition["source_digests"][-2:][0][0].endswith(
        "baseline-2022.1.json"
    )
    assert composition["source_digests"][-1][0].endswith(
        "baseline-2025.1.json"
    )

    monkeypatch.setattr(campaign, "assert_effective_inputs_frozen", lambda *_args, **_kwargs: None)
    component = suite_path.parent.parent / "integration-workflows-v1" / "workflows.json"
    component.write_bytes(component.read_bytes() + b"\n")
    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="transitive suite inputs drifted",
    ):
        campaign.assert_heavy_v3_effective_inputs_frozen(
            options,
            effective=effective,
        )
