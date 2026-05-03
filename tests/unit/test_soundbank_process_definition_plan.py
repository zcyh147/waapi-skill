from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "capabilities" / "2022.1" / "task-6-process-definition-files-plan.json"
TASK6_EVIDENCE_PATH = ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/task-6-process-definition-files.md"
VALIDATOR_EVIDENCE_PATH = ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/task-6-definition-validator.md"
SOURCE_FIXTURE = "tests/_org/2022.1/SampleProject.wproj"
URI = "ak.wwise.core.soundbank.processDefinitionFiles"


class ProcessDefinitionEvidenceError(AssertionError):
    pass


def test_task_6_plan_locks_process_definition_fixture_and_commands() -> None:
    plan = _plan()
    case = plan["process_definition_case"]

    assert case["uri"] == URI
    assert case["temporary_name_prefix"] == "WAAPI_TASK6_SANDBANK_"
    assert case["evidence_path"] == TASK6_EVIDENCE_PATH
    assert plan["metadata"]["source_fixture"] == SOURCE_FIXTURE
    assert SOURCE_FIXTURE in plan["metadata"]["destructive_command"]
    assert plan["metadata"]["unit_command"] == "python -m pytest tests/unit/test_soundbank_process_definition_plan.py -q"
    assert set(plan["metadata"]["evidence_paths"]) == {TASK6_EVIDENCE_PATH, VALIDATOR_EVIDENCE_PATH}


def test_definition_fixture_is_version_correct_and_sandbox_only() -> None:
    fixture = _plan()["definition_fixture"]
    template = fixture["template"]

    assert fixture["output_root"] == "sandbox_path/Task6SoundBankDefinitions"
    assert "SchemaVersion=\"16\"" in template
    assert "SoundBankVersion=\"145\"" in template
    assert "Platform=\"Mac\"" in template
    assert "<ShortName>{bank_name}</ShortName>" in template
    assert "<Path>{bank_name}.bnk</Path>" in template
    assert "Name=\"{bank_name}\"" not in template
    assert "source project" in fixture["source_reference_hash_policy"].lower()


def test_promotion_policy_rejects_call_success_empty_mapping_and_file_error() -> None:
    policy = _plan()["metadata"]["promotion_policy"].lower()

    assert "call success" in policy
    assert "empty mapping" in policy
    assert "ak.wwise.file_error" in policy
    assert "soundbank readback" in policy


def test_case_requires_definition_tied_readback_cleanup_and_source_hash_proof() -> None:
    case = _plan()["process_definition_case"]
    assertions = "\n".join(case["assertions"]).lower()
    cleanup = "\n".join(case["cleanup"]).lower()
    blockers = json.dumps(case["blockers"]).lower()

    assert "definition shortname" in assertions
    assert "soundbank" in assertions and "object.get" in assertions
    assert "empty mapping" in assertions and "call success" in assertions and "file_error" in assertions
    assert "source .wproj mtime" in assertions
    assert "hash" in assertions and "generated-output snapshot" in assertions
    assert "delete created soundbank" in cleanup
    assert "empty array" in cleanup
    assert "file_error" in blockers


def test_task_6_case_matches_shared_destructive_evidence_writer_shape() -> None:
    case = _plan()["process_definition_case"]

    assert case["uris"] == [case["uri"]]
    assert case["allowlist"]["refuse_source_outputs"] is True
    assert "sandbox_path/Task6SoundBankDefinitions" in case["allowlist"]["output_roots"]
    assert case["evidence_path"].startswith(".sisyphus/evidence/wwise-waapi-deferred-reevaluation/")
    for key in ("id", "status", "uris", "allowlist", "assertions", "cleanup", "gate", "evidence_path"):
        assert key in case


def test_definition_evidence_validator_accepts_only_waapi_visible_soundbank_readback() -> None:
    valid = {
        "status": "passed",
        "uri": URI,
        "definition": {"short_name": "WAAPI_TASK6_SANDBANK_definition_bank_abc123", "sha256": "a" * 64},
        "process_result": {"imported": [{"name": "WAAPI_TASK6_SANDBANK_definition_bank_abc123"}]},
        "soundbank_readback": [
            {
                "id": "{11111111-1111-1111-1111-111111111111}",
                "name": "WAAPI_TASK6_SANDBANK_definition_bank_abc123",
                "path": "\\SoundBanks\\Default Work Unit\\WAAPI_TASK6_SANDBANK_definition_bank_abc123",
                "type": "SoundBank",
            }
        ],
        "cleanup_proof": {"deleted_soundbank_id": "{11111111-1111-1111-1111-111111111111}", "read_after_delete": []},
        "source_hash_proof": {"before": ["hash", 4, 100], "after": ["hash", 4, 100]},
    }

    validate_process_definition_evidence(valid)

    call_success_only = dict(valid, process_result={"call": "success"}, soundbank_readback=[])
    with pytest.raises(ProcessDefinitionEvidenceError, match="SoundBank object readback"):
        validate_process_definition_evidence(call_success_only)

    empty_mapping = dict(valid, process_result={}, soundbank_readback=valid["soundbank_readback"])
    with pytest.raises(ProcessDefinitionEvidenceError, match="empty processDefinitionFiles mapping"):
        validate_process_definition_evidence(empty_mapping)

    file_error_only = dict(valid, process_result={"uri": "ak.wwise.file_error"})
    with pytest.raises(ProcessDefinitionEvidenceError, match="ak.wwise.file_error"):
        validate_process_definition_evidence(file_error_only)

    unrelated_readback = json.loads(json.dumps(valid))
    unrelated_readback["soundbank_readback"][0]["name"] = "DifferentBank"
    with pytest.raises(ProcessDefinitionEvidenceError, match="definition ShortName"):
        validate_process_definition_evidence(unrelated_readback)

    no_cleanup = dict(valid, cleanup_proof={"deleted_soundbank_id": "{11111111-1111-1111-1111-111111111111}", "read_after_delete": [{"id": "still-here"}]})
    with pytest.raises(ProcessDefinitionEvidenceError, match="cleanup"):
        validate_process_definition_evidence(no_cleanup)


def validate_process_definition_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("status") != "passed":
        raise ProcessDefinitionEvidenceError("only passed processDefinitionFiles evidence is promotable")
    if evidence.get("uri") != URI:
        raise ProcessDefinitionEvidenceError("evidence URI does not match processDefinitionFiles")

    definition = evidence.get("definition")
    if not isinstance(definition, Mapping):
        raise ProcessDefinitionEvidenceError("definition metadata is required")
    short_name = definition.get("short_name")
    if not isinstance(short_name, str) or not short_name.startswith("WAAPI_TASK6_SANDBANK_"):
        raise ProcessDefinitionEvidenceError("definition ShortName must use the Task 6 prefix")

    result = evidence.get("process_result")
    if not isinstance(result, Mapping):
        raise ProcessDefinitionEvidenceError("processDefinitionFiles must return a mapping")
    if not result:
        raise ProcessDefinitionEvidenceError("empty processDefinitionFiles mapping is not proof")
    if "ak.wwise.file_error" in json.dumps(result):
        raise ProcessDefinitionEvidenceError("ak.wwise.file_error is blocker evidence, not proof")

    rows = evidence.get("soundbank_readback")
    if not isinstance(rows, list) or not rows:
        raise ProcessDefinitionEvidenceError("SoundBank object readback is required")
    matching_rows = [row for row in rows if isinstance(row, Mapping) and row.get("type") == "SoundBank" and row.get("name") == short_name]
    if not matching_rows:
        raise ProcessDefinitionEvidenceError("SoundBank readback must match the definition ShortName")

    cleanup = evidence.get("cleanup_proof")
    if not isinstance(cleanup, Mapping) or cleanup.get("read_after_delete") != []:
        raise ProcessDefinitionEvidenceError("cleanup proof must show empty read_after_delete")
    source_hash = evidence.get("source_hash_proof")
    if not isinstance(source_hash, Mapping) or source_hash.get("before") != source_hash.get("after"):
        raise ProcessDefinitionEvidenceError("source hash proof must show before/after equality")


def _plan() -> Mapping[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
