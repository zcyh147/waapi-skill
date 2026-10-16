from pathlib import Path
import pytest
from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix


def options(tmp_path, monkeypatch, surface, *extra):
    for name in ("codex", "auth.json", "live.json"):
        (tmp_path / name).write_text("{}")
    monkeypatch.setattr(matrix, "resolve_codex_binary", lambda value: Path(value).resolve())
    args = ["--profile", "waapi_v11_repairs_4", "--codex-binary", str(tmp_path / "codex"),
            "--auth-json", str(tmp_path / "auth.json"), "--live-config", str(tmp_path / "live.json")]
    args += ["--campaign-root" if surface == "campaign" else "--iteration-root", str(tmp_path / "root")]
    return (campaign.parse_args if surface == "campaign" else matrix.parse_args)([*args, *extra])


@pytest.mark.parametrize("surface", ["campaign", "matrix"])
def test_repair_uses_formal_entrypoints_with_exact_approved_budget(tmp_path, monkeypatch, surface):
    selected = options(tmp_path, monkeypatch, surface)
    assert (selected.model, selected.reasoning_effort, selected.service_tier, selected.timeout_seconds) == ("gpt-5.6-terra", "medium", "default", 600)
    units = (campaign.load_heavy_v3_campaign_units if surface == "campaign" else matrix.load_heavy_v3_units)(selected)
    assert [unit.unit_id for unit in units] == ["REPAIR25-F1", "REPAIR25-F2", "REPAIR25-F3", "REPAIR25-F4"]
    assert all(len(unit.scenario.prompt_sha256) == 64 for unit in units)
    if surface == "campaign":
        assert selected.max_pre_action_retries == 0


@pytest.mark.parametrize("surface", ["campaign", "matrix"])
@pytest.mark.parametrize("extra", [("--model", "gpt-6-luna"), ("--version", "2022.1"),
                                    ("--case-id", "F1"), ("--timeout", "601")])
def test_repair_rejects_unapproved_selection_and_cost(tmp_path, monkeypatch, surface, extra):
    with pytest.raises(SystemExit):
        options(tmp_path, monkeypatch, surface, *extra)


def test_campaign_child_reaches_repair_executor_through_matrix_main(tmp_path, monkeypatch):
    from dataclasses import replace
    from tests.semantic.support import codex_expansion_runtime as runtime

    selected = replace(options(tmp_path, monkeypatch, "campaign"), campaign_inputs_sha256="a" * 64)
    units = campaign.load_heavy_v3_campaign_units(selected)
    argv = campaign.build_heavy_v3_child_argv(selected, units=units, matrix_root=tmp_path / "waapi-skill-workspace" / "matrix")
    assert argv[argv.index("--suite") + 1] == str(matrix.DEFAULT_REPAIR_SUITE)
    assert "--version" not in argv
    assert [argv[i + 1] for i, value in enumerate(argv) if value == "--case-id"] == [
        "REPAIR25-F1", "REPAIR25-F2", "REPAIR25-F3", "REPAIR25-F4"]
    monkeypatch.setattr(matrix, "SKILL_ROOT", tmp_path / "skill")
    reached = []

    def fake_executor(unit, *, scenario_root, options):
        reached.append((unit.unit_id, options.campaign_inputs_sha256, options.model))
        raise RuntimeError("fake executor stops before external work")

    monkeypatch.setattr(runtime, "run_expansion_unit", fake_executor)
    monkeypatch.setattr(matrix, "require_live_runner_dependencies", lambda **kwargs: {"ok": True})
    assert matrix.main(argv[2:]) == 1
    assert reached == [("REPAIR25-F1", "a" * 64, "gpt-5.6-terra")]


@pytest.mark.parametrize("digest", ["", "a" * 63, "G" * 64, "a" * 65])
def test_repair_child_rejects_malformed_sealed_digest(tmp_path, monkeypatch, digest):
    with pytest.raises(SystemExit) as exc:
        options(tmp_path, monkeypatch, "matrix", "--sealed-campaign-inputs-sha256", digest)
    assert exc.value.code == 2


def test_unrelated_profile_cannot_accept_sealed_campaign_digest(tmp_path, monkeypatch):
    with pytest.raises(SystemExit) as exc:
        options(tmp_path, monkeypatch, "matrix", "--profile", "screening",
                "--sealed-campaign-inputs-sha256", "a" * 64)
    assert exc.value.code == 2


def test_campaign_child_rejects_partial_repair_selection(tmp_path, monkeypatch):
    from dataclasses import replace
    selected = replace(options(tmp_path, monkeypatch, "campaign"), campaign_inputs_sha256="a" * 64)
    units = campaign.load_heavy_v3_campaign_units(selected)
    argv = campaign.build_heavy_v3_child_argv(selected, units=units[:1], matrix_root=tmp_path / "matrix")
    with pytest.raises(SystemExit) as exc:
        matrix.main(argv[2:])
    assert exc.value.code == 2
