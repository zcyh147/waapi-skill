from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticErrorCode,
    SemanticValidationError,
    SourceNoteCheck,
)
from wwise_waapi.builders.identity import ObjectIdentity  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.soundbank import (  # pyright: ignore[reportMissingImports]
    CONVERT_EXTERNAL_SOURCES_URI,
    GENERATED_TOPIC_URI,
    GENERATION_DONE_TOPIC_URI,
    GENERATE_URI,
    GET_INCLUSIONS_URI,
    PROCESS_DEFINITION_FILES_URI,
    SET_INCLUSIONS_URI,
    ExternalSourceConversion,
    SoundBankBuilder,
    SoundBankGenerateRequest,
    SoundBankInclusion,
    build_generate_preview,
    build_generation_done_expectation,
)


SOUNDBANK_ID = "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"
SOUND_ID = "{11111111-1111-1111-1111-111111111111}"
EVENT_ID = "{22222222-2222-2222-2222-222222222222}"


class FakeSourceNoteChecker:
    def __init__(self, status: SourceNoteCheck | None = None) -> None:
        self.status = status or SourceNoteCheck(True, BuilderFamily.SOUNDBANK.value, cited_fields=("soundbank",))
        self.calls: list[tuple[str, str]] = []

    def check(self, family: str, version: str = "2022.1") -> SourceNoteCheck:
        self.calls.append((family, version))
        return self.status


def builder(checker: FakeSourceNoteChecker | None = None) -> SoundBankBuilder:
    return SoundBankBuilder(source_note_checker=checker or FakeSourceNoteChecker())


def test_get_inclusions_preview_uses_soundbank_family_identity_and_schema() -> None:
    checker = FakeSourceNoteChecker()

    preview = SoundBankBuilder(source_note_checker=checker).get_inclusions(soundbank=ObjectIdentity(id=SOUNDBANK_ID))

    assert preview.dispatch_payload() == {"uri": GET_INCLUSIONS_URI, "args": {"soundbank": SOUNDBANK_ID}, "options": {}}
    assert preview.source_note_family == BuilderFamily.SOUNDBANK.value
    assert preview.requires_destructive_gate is False
    assert preview.raw_dispatch_allowed is False
    assert preview.envelope.metadata["builder_family"] == "soundbank"
    assert preview.envelope.metadata["schema_validation"]["uri"] == GET_INCLUSIONS_URI
    assert preview.envelope.metadata["return_expectation"]["required_fields"] == ["inclusions[].object", "inclusions[].filter"]
    assert preview.readback_plan[0].uri == GET_INCLUSIONS_URI
    assert checker.calls == [("soundbank", "2022.1")]


def test_set_inclusions_validates_operation_filters_and_emits_preflight_readback() -> None:
    preview = builder().set_inclusions(
        soundbank=SOUNDBANK_ID,
        operation="replace",
        inclusions=[SoundBankInclusion(object=SOUND_ID, filter=("structures", "media"))],
    )

    assert preview.dispatch_payload() == {
        "uri": SET_INCLUSIONS_URI,
        "args": {
            "soundbank": SOUNDBANK_ID,
            "operation": "replace",
            "inclusions": [{"object": SOUND_ID, "filter": ["structures", "media"]}],
        },
        "options": {},
    }
    assert preview.requires_destructive_gate is True
    assert preview.envelope.metadata["validated_operation"] == "replace"
    assert preview.envelope.metadata["validated_filters"] == ["media", "structures"]
    assert preview.envelope.metadata["destructive_gate"]["allow_source_mutation"] is False
    assert [plan.uri for plan in preview.readback_plan] == [GET_INCLUSIONS_URI, GET_INCLUSIONS_URI]
    assert preview.evidence_plan[2] == {"kind": "preflight", "uri": GET_INCLUSIONS_URI, "must_execute_before": SET_INCLUSIONS_URI}
    assert preview.to_dispatcher_request().dry_run is True


def test_set_inclusions_rejects_bad_operation_filter_duplicates_and_ambiguous_identity() -> None:
    with pytest.raises(SemanticValidationError) as bad_operation:
        builder().set_inclusions(soundbank=SOUNDBANK_ID, operation="clear", inclusions=[{"object": SOUND_ID, "filter": ["media"]}])
    assert bad_operation.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert bad_operation.value.details["supported"] == ["add", "remove", "replace"]

    with pytest.raises(SemanticValidationError) as bad_filter:
        builder().set_inclusions(soundbank=SOUNDBANK_ID, operation="add", inclusions=[{"object": SOUND_ID, "filter": ["structure"]}])
    assert bad_filter.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert bad_filter.value.details["supported"] == ["events", "structures", "media"]

    with pytest.raises(SemanticValidationError) as duplicate_filter:
        builder().set_inclusions(soundbank=SOUNDBANK_ID, operation="add", inclusions=[{"object": SOUND_ID, "filter": ["media", "media"]}])
    assert duplicate_filter.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH

    with pytest.raises(SemanticValidationError) as ambiguous:
        builder().set_inclusions(soundbank=ObjectIdentity(waql="from type SoundBank"), operation="add", inclusions=[{"object": SOUND_ID, "filter": ["media"]}])
    assert ambiguous.value.error_code == SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY


def test_generate_preview_records_artifact_evidence_plan_without_outputs(tmp_path: Path) -> None:
    preview = builder().generate(
        soundbanks=[SoundBankGenerateRequest(name="UnitBank", events=(EVENT_ID,), inclusions=("event", "media"), rebuild=True)],
        platforms=("Mac",),
        languages=("English(US)",),
        write_to_disk=True,
        rebuild_sound_banks=True,
        skip_languages=False,
        output_root_hint=tmp_path / "GeneratedSoundBanks",
    )

    assert preview.dispatch_payload()["uri"] == GENERATE_URI
    assert preview.dispatch_payload()["args"] == {
        "soundbanks": [{"name": "UnitBank", "events": [EVENT_ID], "inclusions": ["event", "media"], "rebuild": True}],
        "platforms": ["Mac"],
        "languages": ["English(US)"],
        "skipLanguages": False,
        "rebuildSoundBanks": True,
        "writeToDisk": True,
    }
    artifact_plan = preview.envelope.metadata["artifact_evidence_plan"]
    assert artifact_plan["write_to_disk_requested"] is True
    assert artifact_plan["writes_files_by_preview"] is False
    assert artifact_plan["completion_claim"] == "not-claimed"
    assert f"{tmp_path / 'GeneratedSoundBanks'}/Mac/English(US)/UnitBank.bnk" in artifact_plan["expected_output_artifact_paths"]
    assert not any(tmp_path.rglob("*.bnk"))
    assert preview.evidence_plan[3]["hidden_subscription"] is False


def test_generate_rejects_set_inclusion_filter_spelling_and_module_helper_accepts_checker() -> None:
    with pytest.raises(SemanticValidationError) as bad_inclusion:
        builder().generate(soundbanks=[{"name": "UnitBank", "inclusions": ["structures"]}])
    assert bad_inclusion.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert bad_inclusion.value.details["supported"] == ["event", "structure", "media"]

    preview = build_generate_preview(source_note_checker=FakeSourceNoteChecker(), soundbanks=[{"name": "HelperBank"}])
    assert preview.dispatch_payload()["uri"] == GENERATE_URI


def test_convert_external_sources_preview_is_destructive_gated_and_schema_validated() -> None:
    preview = builder().convert_external_sources([ExternalSourceConversion(input="/tmp/unit.wsources", platform="Mac", output="/tmp/out")])

    assert preview.dispatch_payload() == {
        "uri": CONVERT_EXTERNAL_SOURCES_URI,
        "args": {"sources": [{"input": "/tmp/unit.wsources", "platform": "Mac", "output": "/tmp/out"}]},
        "options": {},
    }
    assert preview.requires_destructive_gate is True
    assert preview.envelope.metadata["schema_validation"]["uri"] == CONVERT_EXTERNAL_SOURCES_URI
    assert preview.envelope.metadata["artifact_evidence_plan"]["writes_files_by_preview"] is False

    with pytest.raises(SemanticValidationError) as empty:
        builder().convert_external_sources([])
    assert empty.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_process_definition_files_is_high_risk_and_rejects_bad_proof_claims() -> None:
    preview = builder().process_definition_files(files=("/sandbox/Task8SoundBankDefinitions/Unit.xml",), expected_soundbank_names=("UnitBank",))

    assert preview.dispatch_payload() == {"uri": PROCESS_DEFINITION_FILES_URI, "args": {"files": ["/sandbox/Task8SoundBankDefinitions/Unit.xml"]}, "options": {}}
    assert preview.requires_destructive_gate is True
    assert preview.envelope.metadata["destructive_gate"]["high_risk"] is True
    assert "empty mapping" in preview.envelope.metadata["proof_policy"]
    assert preview.evidence_plan[2]["rejects"] == ["empty-mapping", "ak.wwise.file_error", "call-success-only"]

    for proof in ({}, {"uri": "ak.wwise.file_error"}, {"call": "success"}):
        with pytest.raises(SemanticValidationError) as exc:
            builder().process_definition_files(files=("/sandbox/Unit.xml",), process_result_proof=proof)
        assert exc.value.error_code == SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED

    with pytest.raises(SemanticValidationError) as no_files:
        builder().process_definition_files(files=())
    assert no_files.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_topic_expectations_are_evidence_only_and_do_not_subscribe_or_claim_completion() -> None:
    generated = builder().generated_expectation(soundbank=SOUNDBANK_ID, platform="Mac", language="English(US)", return_fields=("id", "name"))
    done = builder().generation_done_expectation()
    alias = build_generation_done_expectation(source_note_checker=FakeSourceNoteChecker())

    assert generated.as_dict() == {
        "uri": GENERATED_TOPIC_URI,
        "options": {"return": ["id", "name"]},
        "payload_identity": {"soundbank": SOUNDBANK_ID, "platform": "Mac", "language": "English(US)"},
        "evidence_only": True,
        "hidden_subscription": False,
        "completion_claim": "not-claimed",
        "metadata": generated.as_dict()["metadata"],
    }
    assert generated.as_dict()["metadata"]["schema_validation"]["uri"] == GENERATED_TOPIC_URI
    assert done.uri == GENERATION_DONE_TOPIC_URI
    assert done.options == {}
    assert done.as_dict()["completion_claim"] == "not-claimed"
    assert alias.as_dict()["hidden_subscription"] is False

    with pytest.raises(SemanticValidationError) as bad_return:
        builder().topic_expectation(GENERATION_DONE_TOPIC_URI, return_fields=("id",))
    assert bad_return.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH

    with pytest.raises(SemanticValidationError) as unsupported:
        builder().topic_expectation("ak.wwise.core.soundbank.unrelated")
    assert unsupported.value.error_code == SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED


def test_source_note_gate_runs_before_envelope_generation() -> None:
    checker = FakeSourceNoteChecker(SourceNoteCheck(False, BuilderFamily.SOUNDBANK.value, missing_fields=("return_shape",), reason="incomplete note"))

    with pytest.raises(SemanticValidationError) as exc:
        SoundBankBuilder(source_note_checker=checker).get_inclusions(soundbank=SOUNDBANK_ID)

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
    assert checker.calls == [("soundbank", "2022.1")]
