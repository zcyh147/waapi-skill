from __future__ import annotations

from pathlib import Path

from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_audio_import_composer_transaction_steps,
)
from tests.semantic.support.codex_import_business_profile import (
    UNIT_IDS,
    load_import_business_profile,
)
from tests.semantic.support.codex_import_business_agent_runner import (
    build_preview_only_business_steps,
    prepare_import_business_runtime,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "tests/semantic/data/audio-import-business/profile.json"


def test_production_audio_import_profile_has_four_independent_paraphrase_pairs() -> None:
    profile = load_import_business_profile(PROFILE)

    assert tuple(unit.unit_id for unit in profile.units) == UNIT_IDS
    assert len({unit.scenario.id for unit in profile.units}) == 8
    assert [unit.family for unit in profile.units] == [
        "weather", "weather", "rifle", "rifle",
        "footsteps", "footsteps", "weapons", "weapons",
    ]
    assert all(unit.scenario.api == "ak.wwise.core.audio.import" for unit in profile.units)


def test_every_profile_transaction_compiles_to_the_production_business_draft() -> None:
    profile = load_import_business_profile(PROFILE)

    for unit in profile.units[::2]:
        for index, transaction in enumerate(unit.transactions, start=1):
            request = {
                "contract": "waapi-skill.operation-request/v1",
                "version": unit.version,
                "operation": "audio.import",
                "arguments": transaction["arguments"],
            }
            steps = build_audio_import_composer_transaction_steps(
                request,
                label=f"tx{index:02d}",
            )
            subcommands = tuple(step.subcommand for step in steps)
            assert "draft-start" in subcommands
            assert "draft-declare-new" in subcommands or "draft-declare-existing" in subcommands
            assert "draft-check" in subcommands
            assert "preview-from-draft" in subcommands
            assert "draft-apply" not in subcommands


def test_protocol_accepts_the_normal_wwise_actor_mixer_path_token() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit"
                        r"\<Actor-Mixer>Weather"
                    ),
                    "object_type": "ActorMixer",
                }
            ]
        },
    }

    steps = build_audio_import_composer_transaction_steps(request, label="tx01")

    declaration = next(
        step for step in steps if step.subcommand == "draft-declare-new"
    )
    assert "actor-mixer" in declaration.arguments


def test_implicit_create_uses_the_planned_parent_instead_of_live_binding_it() -> None:
    unit = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB22-WEATHER-A",),
    ).units[0]
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": unit.version,
        "operation": "audio.import",
        "arguments": unit.transactions[0]["arguments"],
    }

    steps = build_audio_import_composer_transaction_steps(request, label="tx01")

    bound_paths = {
        step.arguments[-1]
        for step in steps
        if step.subcommand == "draft-bind-object"
        and step.arguments[-2] == "--object-path"
    }
    assert (
        r"\Actor-Mixer Hierarchy\Default Work Unit"
        r"\BusinessImportRoot\<Actor-Mixer>Weather"
    ) not in bound_paths


def test_profile_filters_preserve_independent_unit_identity() -> None:
    selected = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB22-WEATHER-B", "AIB25-WEAPONS-A"),
    )

    assert tuple(unit.unit_id for unit in selected.units) == (
        "AIB22-WEATHER-B",
        "AIB25-WEAPONS-A",
    )


def test_runtime_resolves_media_and_stops_every_transaction_at_preview(tmp_path: Path) -> None:
    unit = load_import_business_profile(
        PROFILE,
        unit_ids=("AIB22-RIFLE-A",),
    ).units[0]

    runtime = prepare_import_business_runtime(unit, tmp_path / "runtime")
    steps = build_preview_only_business_steps(runtime.requests)

    assert len(runtime.requests) == 2
    assert all(path.is_file() for path in runtime.media_paths)
    assert "media://" not in runtime.prompt
    assert sum(step.subcommand == "preview-from-draft" for step in steps) == 2
    assert all(step.subcommand not in {"confirm", "execute", "verify"} for step in steps)


def test_matrix_wires_the_profile_to_the_packaged_skill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex = tmp_path / "codex"
    auth = tmp_path / "auth.json"
    codex.write_text("fixture", encoding="utf-8")
    auth.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(matrix, "resolve_codex_binary", lambda _value: codex)

    options = matrix.parse_args(
        [
            "--profile",
            "audio_import_business_8",
            "--case-id",
            "AIB25-WEAPONS-B",
            "--auth-json",
            str(auth),
            "--model",
            "gpt-5.6-terra",
            "--reasoning-effort",
            "medium",
            "--service-tier",
            "default",
        ]
    )

    assert options.suite_path == PROFILE
    assert options.skill_source == matrix.SKILL_ROOT
    assert options.iteration_root.name == "audio-import-business-8"
    assert [unit.unit_id for unit in matrix.load_heavy_v3_units(options)] == [
        "AIB25-WEAPONS-B"
    ]


def test_campaign_wires_the_same_suite_and_forbids_same_root_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex = tmp_path / "codex"
    auth = tmp_path / "auth.json"
    live = tmp_path / "live-environment.json"
    for path, content in ((codex, "fixture"), (auth, "{}"), (live, "{}")):
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(matrix, "resolve_codex_binary", lambda _value: codex)

    options = campaign.parse_args(
        [
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--profile",
            "audio_import_business_8",
            "--auth-json",
            str(auth),
            "--live-config",
            str(live),
            "--model",
            "gpt-5.6-terra",
            "--reasoning-effort",
            "medium",
            "--service-tier",
            "default",
        ]
    )

    assert options.suite_path == PROFILE
    assert options.max_pre_action_retries == 0
