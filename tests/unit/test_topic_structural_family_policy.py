from __future__ import annotations

import ast
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.topic_business import topic_business_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = (
    REPO_ROOT
    / "tests"
    / "destructive"
    / "support"
    / "resources"
    / "capabilities"
    / "topic-structural-family-policy.json"
)
REAL_EVIDENCE_VERSIONS = ("2022.1", "2025.1")
ALLOWED_DISPOSITIONS = {
    "active_live",
    "prerequisite_boundary",
    "prohibited_boundary",
}


def test_topic_structural_family_policy_closes_the_real_evidence_union() -> None:
    policy = _policy()
    families = policy["families"]

    assert policy["contract"] == "waapi-skill.topic-structural-family-policy/v1"
    assert policy["versions"] == list(REAL_EVIDENCE_VERSIONS)
    assert policy["family_count"] == 24
    assert len(families) == 24
    assert len({row["family"] for row in families}) == 24

    expected = {
        version: _structural_groups(version)
        for version in REAL_EVIDENCE_VERSIONS
    }
    for version in REAL_EVIDENCE_VERSIONS:
        covered = {
            tuple(sorted(row["topics_by_version"][version]))
            for row in families
            if version in row["topics_by_version"]
        }
        assert covered == set(expected[version].values())


def test_topic_structural_family_policy_never_promotes_a_boundary_to_real_pass() -> None:
    for row in _policy()["families"]:
        for version, topics in row["topics_by_version"].items():
            assert version in REAL_EVIDENCE_VERSIONS
            assert topics
            evidence = row["evidence_by_version"][version]
            disposition = evidence["disposition"]
            assert disposition in ALLOWED_DISPOSITIONS
            if disposition == "active_live":
                assert evidence["publisher"]
                assert evidence["evidence_test"].startswith("tests/")
                assert evidence["result_requirement"] == "matching_event_payload"
                assert evidence["counts_as_real_pass_only_after_execution"] is True
                assert "blocker" not in evidence
            else:
                assert evidence["blocker"]
                assert evidence["review_trigger"]
                assert evidence["counts_as_real_pass"] is False
                assert "publisher" not in evidence


def test_active_soundbank_and_transport_families_name_hard_event_proofs() -> None:
    families = {row["family"]: row for row in _policy()["families"]}
    for family in ("soundbank-generated", "soundbank-generation-done"):
        for evidence in families[family]["evidence_by_version"].values():
            assert evidence["evidence_test"] == (
                "tests/destructive/test_soundbank_audio_sandbox.py"
            )

    soundbank_test = (
        REPO_ROOT / "tests" / "destructive" / "test_soundbank_audio_sandbox.py"
    )
    module = ast.parse(soundbank_test.read_text(encoding="utf-8"))
    generate_test = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_soundbank_generate_write_to_disk_or_records_blocker"
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_require_soundbank_topic_events"
        for node in ast.walk(generate_test)
    )

    for evidence in families["transport-state"]["evidence_by_version"].values():
        assert evidence["evidence_test"] == (
            "tests/live/test_topic_transport_state_sandbox.py"
        )


def _policy() -> Mapping[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _structural_groups(version: str) -> dict[str, tuple[str, ...]]:
    manifest = json.loads(
        (
            REPO_ROOT
            / "skills"
            / "waapi-skill"
            / "resources"
            / "manifest"
            / version
            / "topics.json"
        ).read_text(encoding="utf-8")
    )
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for row in manifest["topics"]:
        topic = row["uri"]
        public = topic_business_contract(version, topic).as_dict()
        for key in ("version", "topic", "contract_digest"):
            public.pop(key, None)
        groups[canonical_sha256(public)].append(topic)
    return {
        digest: tuple(sorted(topics))
        for digest, topics in groups.items()
    }
