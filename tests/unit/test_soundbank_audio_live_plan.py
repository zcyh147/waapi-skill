from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_ROOT = REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities"
PLAN_PATH = CAPABILITY_ROOT / "2022.1" / "task-8-soundbank-audio-sandbox-plan.json"
EVIDENCE_ROOT = ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/"
REQUIRED_AUDIO_URIS = {
    "ak.wwise.core.audio.import",
    "ak.wwise.core.audio.importTabDelimited",
    "ak.wwise.core.audio.imported",
}
REQUIRED_SOUNDBANK_URIS = {
    "ak.wwise.core.soundbank.generate",
    "ak.wwise.core.soundbank.generated",
    "ak.wwise.core.soundbank.generationDone",
    "ak.wwise.core.soundbank.getInclusions",
    "ak.wwise.core.soundbank.processDefinitionFiles",
    "ak.wwise.core.soundbank.setInclusions",
}


def test_task_8_plan_covers_audio_and_soundbank_candidates() -> None:
    plan = _plan()
    audio_cases = plan["audio_cases"]
    soundbank_cases = plan["soundbank_cases"]

    assert {case["group"] for case in audio_cases} == {"core.audio"}
    assert {case["group"] for case in soundbank_cases} == {"core.soundbank"}
    assert REQUIRED_AUDIO_URIS <= _covered_uris(audio_cases)
    assert REQUIRED_SOUNDBANK_URIS <= _covered_uris(soundbank_cases)


def test_every_case_is_live_destructive_gated_and_sandbox_only() -> None:
    for case in _cases():
        assert case["temporary_name_prefix"].startswith("WAAPI_TASK8_SANDBOX_"), case["id"]
        assert case["setup"], case["id"]
        assert case["action"], case["id"]
        assert case["assertions"], case["id"]
        assert case["cleanup"], case["id"]
        assert case["gate"] == {
            "env": {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1"},
            "allow_source_mutation": False,
        }
        assert "sandbox" in json.dumps(case["setup"]).lower(), case["id"]
        assert case["allowlist"]["refuse_source_outputs"] is True, case["id"]
        assert _all_output_roots_are_safe(case["allowlist"]["output_roots"]), case["id"]
        assert case["evidence_path"].startswith(EVIDENCE_ROOT), case["id"]


def test_import_generate_and_process_flows_are_never_default_tier() -> None:
    mutating_uris = {
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.setInclusions",
    }

    for case in _cases():
        if mutating_uris & set(case["uris"]):
            assert case["gate"]["env"] == {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1"}
            assert case["status"] in {"sandbox-mutating-tested-or-blocked", "still-deferred-with-evidence"}


def test_assertions_require_readback_generated_file_or_blocker_evidence() -> None:
    for case in _cases():
        assertion_text = "\n".join(case["assertions"]).lower()
        assert any(token in assertion_text for token in ("readback", "generated files", "payload", "blocker")), case["id"]
        assert "no-exception" not in assertion_text
        assert "no exception" not in assertion_text
        assert "source project" in assertion_text, case["id"]


def test_infeasible_topics_and_settings_have_explicit_blocker_schema() -> None:
    blocked_case_ids = {
        "audio_import_tab_delimited_generated_wav_readback_cleanup",
        "audio_imported_topic_bounded_wait_or_blocker",
        "soundbank_generate_write_to_disk_or_records_blocker",
        "soundbank_process_definition_file_or_records_blocker",
    }

    for case_id in blocked_case_ids:
        case = _case(case_id)
        blockers = case.get("blockers")
        assert isinstance(blockers, list) and blockers, case_id
        for blocker in blockers:
            assert blocker["uri"] in case["uris"], case_id
            assert "without claiming" in blocker["reason"] or "unless a matching payload is observed" in blocker["reason"] or "depends on local platform" in blocker["reason"]


def test_evidence_contract_names_required_task_files_and_commands() -> None:
    metadata = _plan()["metadata"]

    assert metadata["unit_command"] == "python -m pytest tests/unit/test_soundbank_audio_live_plan.py -q"
    assert metadata["destructive_command"].endswith("python -m pytest tests/destructive/test_soundbank_audio_sandbox.py -q")
    assert "WWISE_LIVE=1" in metadata["destructive_command"]
    assert "WWISE_DESTRUCTIVE=1" in metadata["destructive_command"]
    assert {Path(case["evidence_path"]).name for case in _cases()} == {"task-8-audio.md", "task-8-soundbank.md"}


def _case(case_id: str) -> Mapping[str, Any]:
    for case in _cases():
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing Task 8 case {case_id}")


def _cases() -> list[Mapping[str, Any]]:
    plan = _plan()
    return list(plan["audio_cases"]) + list(plan["soundbank_cases"])


def _covered_uris(cases: list[Mapping[str, Any]]) -> set[str]:
    return {uri for case in cases for uri in case["uris"]}


def _all_output_roots_are_safe(output_roots: list[str]) -> bool:
    return all(root.startswith("sandbox_path") or root.startswith(EVIDENCE_ROOT) for root in output_roots)


def _plan() -> Mapping[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
