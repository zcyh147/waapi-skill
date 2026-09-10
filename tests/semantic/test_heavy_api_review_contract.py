from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from tests.semantic.render_v3_review import HEAVY_API_URIS, render_review
from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3


REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_V3 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"
OPERATE_REFERENCE = (
    REPO_ROOT / "skills" / "waapi-skill" / "references" / "waapi-operate.md"
)
SKILL_ENTRY = REPO_ROOT / "skills" / "waapi-skill" / "SKILL.md"

FILE_BACKED_HEAVY_APIS = frozenset(
    {
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
        "ak.wwise.core.audio.convert",
        "ak.wwise.core.mediaPool.get",
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.generated",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.migrate",
    }
)


def test_heavy_review_set_is_exactly_five_natural_cases_per_api() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    cases = [case for case in bundle.scenarios if case.api in HEAVY_API_URIS]

    assert len(HEAVY_API_URIS) == 16
    assert len(cases) == 80
    assert Counter(case.api for case in cases) == {
        api: 5 for api in HEAVY_API_URIS
    }
    for api in HEAVY_API_URIS:
        api_cases = [case for case in cases if case.api == api]
        assert [case.scenario_index for case in api_cases] == [1, 2, 3, 4, 5]
        assert len({case.scenario_family for case in api_cases}) == 5
        assert len({case.prompt_sha256 for case in api_cases}) == 5
        assert sum(case.primary_dispatch.count > 0 for case in api_cases) >= 4
        assert all(not bundle.scenario_mapping_blockers(case.id) for case in api_cases)


def test_every_heavy_case_has_a_fresh_clean_or_quarantined_scene() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    cases = [case for case in bundle.scenarios if case.api in HEAVY_API_URIS]

    for case in cases:
        assert case.fixture["sandbox"] in {"scenario_project_copy", "isolated_io_root"}
        postconditions = set(case.cleanup["postconditions"])
        assert "project_source_unchanged" in postconditions
        assert any(
            postcondition.startswith("successful_case_")
            and postcondition.endswith("removed")
            for postcondition in postconditions
        )
        assert (
            "failed_or_indeterminate_case_sandbox_sealed_and_never_reused"
            in postconditions
        )
        assert any(
            assertion.phase == "cleanup" and assertion.subject_api == case.api
            for assertion in case.oracle_assertions
        )


def test_file_backed_heavy_cases_declare_reviewable_assets_and_cleanup() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    cases = [case for case in bundle.scenarios if case.api in FILE_BACKED_HEAVY_APIS]

    assert {case.api for case in cases} == FILE_BACKED_HEAVY_APIS
    for case in cases:
        asset_spec = case.fixture.get("asset_spec")
        assert isinstance(asset_spec, Mapping)
        assert asset_spec
        cleanup_policy = asset_spec.get("cleanup_policy")
        assert isinstance(cleanup_policy, str)
        assert "case_owned" in cleanup_policy


def test_heavy_review_renderer_exposes_prompts_assets_oracles_and_cleanup() -> None:
    rendered = render_review(SUITE_V3, heavy_only=True)
    summary = render_review(SUITE_V3, heavy_only=True, summary_only=True)

    assert "Online scenarios: 80" in rendered
    assert "Covered APIs: 16" in rendered
    assert "Fixture asset specification:" in rendered
    assert "Expected model dispatches:" in rendered
    assert "Assertions:" in rendered
    assert "Cleanup postconditions:" in rendered
    assert "Online scenarios: 80" in summary
    assert "Covered APIs: 16" in summary


def test_audio_convert_request_is_reconstructible_from_prompt_and_progressive_schema() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    cases = tuple(
        case
        for case in bundle.scenarios
        if case.api == "ak.wwise.core.audio.convert"
    )
    reference = OPERATE_REFERENCE.read_text(encoding="utf-8")

    assert len(cases) == 5
    assert all({value.name for value in case.visible_inputs} == {"io_root"} for case in cases)
    assert all("{io_root}" in case.prompt for case in cases)
    for case in cases:
        request = case.fixture["asset_spec"]["request"]
        for object_path in request["objects"]:
            parent, child = object_path.rsplit("\\", 1)
            assert parent in case.prompt
            assert child in case.prompt
        for platform in request["platforms"]:
            assert platform in case.prompt
        for language in request["languages"]:
            assert language in case.prompt
    assert "### Authoring audio conversion" in reference
    assert "`ak.wwise.core.audio.convert`" in reference
    assert "`2024.1`/`2025.1`" in reference
    assert "`request-schema ak.wwise.core.audio.convert`" in reference
    for token in (
        "object identities",
        "platforms",
        "languages",
        "absolute `io_root`",
    ):
        assert token in reference


def test_zero_dispatch_tab_import_names_its_would_be_import_mode() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    case = bundle.scenario("O22-AUDIO-TAB-01")
    asset_spec = case.fixture["asset_spec"]

    assert case.primary_dispatch.count == 0
    assert "useExisting" in case.prompt
    assert asset_spec["tsv"][0]["import_operation"] == "useExisting"


def test_operate_reference_routes_playback_limits_through_stable_business_fields() -> None:
    reference = OPERATE_REFERENCE.read_text(encoding="utf-8")

    assert "maximum instances" in reference
    assert "parent instance-limit override" in reference
    assert "use stable business fields" in reference
    assert "bind only user-requested custom properties/references" in reference


def test_entry_skill_forbids_model_appended_apply_on_draft_preview() -> None:
    skill = SKILL_ENTRY.read_text(encoding="utf-8")

    assert "Never append `--apply` to `preview-from-draft`" in skill
    assert "copy the returned `preview-from-draft` continuation exactly" in skill


def test_entry_skill_does_not_force_complex_core_reads_back_to_core_call() -> None:
    skill = SKILL_ENTRY.read_text(encoding="utf-8")

    assert "`core-business/v1` reads use `core-call`" not in skill
    assert "the exact returned continuation owns the read shape" in skill
