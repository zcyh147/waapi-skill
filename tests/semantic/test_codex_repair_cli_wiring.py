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
    if surface == "campaign":
        assert selected.max_pre_action_retries == 0


@pytest.mark.parametrize("surface", ["campaign", "matrix"])
@pytest.mark.parametrize("extra", [("--model", "gpt-6-luna"), ("--version", "2022.1"),
                                    ("--case-id", "F1"), ("--timeout", "601")])
def test_repair_rejects_unapproved_selection_and_cost(tmp_path, monkeypatch, surface, extra):
    with pytest.raises(SystemExit):
        options(tmp_path, monkeypatch, surface, *extra)
