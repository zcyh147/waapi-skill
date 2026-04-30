from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT
EVALS_JSON = SKILL_ROOT / "evals" / "evals.json"
REVIEW_WORKFLOW = SKILL_ROOT / "references" / "eval-review-workflow.md"
REQUIRED_CATEGORIES = {
    "safe object query",
    "WAQL query",
    "subscription wait",
    "destructive-call refusal",
    "missing Wwise diagnostic",
    "deferred API explanation",
    "semantic builder WAQL query",
    "semantic builder object create dry-run",
    "semantic builder setProperty fail-closed",
    "semantic builder audio import dry-run",
    "semantic builder SoundBank guarded preview",
    "semantic builder SwitchContainer preflight",
}
FORBIDDEN_LOCAL_MARKERS = (
    "/Users/",
    "/Applications/",
    "\\Users\\",
    "auth_info",
    "cookies",
    "Wwise.log",
)


def test_eval_metadata_has_required_review_shape() -> None:
    payload = _eval_payload()

    assert payload["skill_name"] == "wwise-waapi"
    assert payload["review_workflow"] == "references/eval-review-workflow.md"
    assert "not replace pytest" in payload["purpose"]
    assert len(payload["evals"]) >= 6
    assert {entry["category"] for entry in payload["evals"]} >= REQUIRED_CATEGORIES

    ids = [entry["id"] for entry in payload["evals"]]
    assert len(ids) == len(set(ids))
    for entry in payload["evals"]:
        assert entry["id"]
        assert entry["prompt"]
        assert entry["expected_output"]
        assert isinstance(entry["files"], list)
        assert entry["assertions"], entry["id"]
        for assertion in entry["assertions"]:
            assert assertion["name"]
            assert assertion["text"]
            assert _has_check_terms(assertion), assertion


def test_eval_metadata_covers_safety_and_gating_requirements() -> None:
    by_id = {entry["id"]: entry for entry in _eval_payload()["evals"]}

    destructive = by_id["destructive-call-refusal"]
    assert "Delete every Event" in destructive["prompt"]
    assert "refuses" in destructive["expected_output"] or "Refuses" in destructive["expected_output"]
    assert _entry_mentions(destructive, "allow_destructive=True")
    assert _entry_mentions(destructive, "WWISE_DESTRUCTIVE=1")
    assert _entry_mentions(destructive, "dry_run")

    waql = by_id["waql-query-gated"]
    assert "ak.wwise.core.object.get" in waql["expected_output"]
    assert _entry_mentions(waql, "waql-2022.1.md")
    assert _entry_mentions(waql, "source-grounded")
    assert any("invent" in assertion["text"] for assertion in waql["assertions"])

    subscription = by_id["subscription-wait-bounded"]
    assert _entry_mentions(subscription, "ak.wwise.core.object.created")
    assert _entry_mentions(subscription, "timeout")
    assert _entry_mentions(subscription, "cancel") or _entry_mentions(subscription, "unsubscribe")

    diagnostic = by_id["missing-wwise-diagnostic"]
    assert _entry_mentions(diagnostic, "stdout")
    assert _entry_mentions(diagnostic, "stderr")
    assert _entry_mentions(diagnostic, "auth state")

    deferred = by_id["deferred-api-explanation"]
    assert _entry_mentions(deferred, "ak.soundengine.executeActionOnEvent")
    assert _entry_mentions(deferred, "inventory")
    assert _entry_mentions(deferred, "behavioral coverage")
    assert _entry_mentions(deferred, "deferred")



def test_eval_metadata_covers_semantic_builder_safety_examples() -> None:
    by_id = {entry["id"]: entry for entry in _eval_payload()["evals"]}

    expected = {
        "semantic-builder-waql-query-preview": ("build_object_get_query", "SemanticPreview"),
        "semantic-builder-object-create-dry-run": ("ObjectMutationBuilder", "requires_destructive_gate"),
        "semantic-builder-setproperty-fail-closed": ("PropertyReferenceBuilder", "fail closed"),
        "semantic-builder-audio-import-dry-run": ("ImportBuilder", "requires_destructive_gate"),
        "semantic-builder-soundbank-guarded-preview": ("SoundBankBuilder", "generationDone"),
        "semantic-builder-switchcontainer-preflight": ("SwitchContainerAssignmentBuilder", "existing_assignments"),
    }
    for eval_id, terms in expected.items():
        assert eval_id in by_id
        for term in terms:
            assert _entry_mentions(by_id[eval_id], term)
        prompt_and_expected = f"{by_id[eval_id]['prompt']} {by_id[eval_id]['expected_output']}"
        assert "executed in Wwise" not in prompt_and_expected
        assert "created Wwise objects" not in prompt_and_expected

def test_review_workflow_documents_generate_review_static_fallback_and_pytest() -> None:
    text = REVIEW_WORKFLOW.read_text(encoding="utf-8")

    assert "eval-viewer/generate_review.py" in text
    assert "--static" in text
    assert "review.html" in text
    assert "feedback.json" in text
    assert "not release gates" in text
    assert "do not replace `pytest`" in text
    assert "python -m pytest tests/unit/test_eval_metadata.py -q" in text
    assert "python -m pytest -q" in text
    assert "Do not run full model benchmarking" in text


def test_eval_files_do_not_commit_local_runtime_state() -> None:
    eval_text = EVALS_JSON.read_text(encoding="utf-8")
    workflow_text = REVIEW_WORKFLOW.read_text(encoding="utf-8")

    for marker in FORBIDDEN_LOCAL_MARKERS:
        assert marker not in eval_text
        assert marker not in workflow_text


def _eval_payload() -> dict[str, Any]:
    return json.loads(EVALS_JSON.read_text(encoding="utf-8"))


def _has_check_terms(assertion: Mapping[str, Any]) -> bool:
    return any(
        key in assertion
        for key in (
            "required_terms",
            "required_terms_any",
            "required_terms_any_secondary",
            "forbidden_terms",
        )
    )


def _entry_mentions(entry: Mapping[str, Any], needle: str) -> bool:
    return needle in json.dumps(entry, sort_keys=True)
