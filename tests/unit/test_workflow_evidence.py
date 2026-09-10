from __future__ import annotations

import copy
from typing import Any

import pytest

from tests.destructive.support.workflow_evidence import (
    WorkflowEvidenceError,
    validate_audio_import_business_evidence,
    validate_soundbank_inclusions_business_evidence,
    validate_switch_assignment_business_evidence,
)


TARGET_ID = "{11111111-1111-1111-1111-111111111111}"
SOURCE_ID = "{22222222-2222-2222-2222-222222222222}"
BANK_ID = "{33333333-3333-3333-3333-333333333333}"
INCLUDED_ID = "{44444444-4444-4444-4444-444444444444}"
CONTAINER_ID = "{55555555-5555-5555-5555-555555555555}"
GROUP_ID = "{66666666-6666-6666-6666-666666666666}"
CHILD_ID = "{77777777-7777-7777-7777-777777777777}"
SWITCH_ID = "{88888888-8888-8888-8888-888888888888}"
OTHER_ID = "{99999999-9999-9999-9999-999999999999}"
TARGET_PATH = r"\Actor-Mixer Hierarchy\Default Work Unit\Imported"
SOURCE_PATH = TARGET_PATH + r"\source"
NOTES = "closed import notes"


def _verification(operation: str, readbacks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "operation": operation,
        "ok": True,
        "status": "verified",
        "business_state_verified": True,
        # Deliberately omit assertion names: the business oracle must consume
        # structured execution/readback evidence rather than display wording.
        "assertions": [{"passed": True, "evidence": {"structured": True}}],
        "readbacks": readbacks,
    }


def _audio_case(version: str = "2025.1") -> tuple[dict[str, Any], dict[str, Any]]:
    target = {
        "id": TARGET_ID,
        "name": "Imported",
        "type": "Sound",
        "path": TARGET_PATH,
        "notes": NOTES,
        "activeSource": {"id": SOURCE_ID},
    }
    source = {
        "id": SOURCE_ID,
        "name": "source",
        "type": "AudioFileSource",
        "path": SOURCE_PATH,
        "originalFilePath": r"C:\Project\Originals\SFX\source.wav",
    }
    result: dict[str, Any] = {"objects": [dict(target), dict(source)]}
    if version in {"2023.1", "2024.1", "2025.1"}:
        result = {
            "log": [],
            "files": [r"C:\Project\Originals\SFX\source.wav"],
            **result,
        }
    execution = {"dispatch_result": {"result": result}}
    verification = _verification(
        "audio.import",
        [
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"path": [TARGET_PATH]}},
                "options": {},
                "result": {"return": [target]},
            },
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"id": [SOURCE_ID]}},
                "options": {},
                "result": {"return": [source]},
            },
        ],
    )
    return execution, verification


@pytest.mark.parametrize(
    ("version", "source_file"),
    [("2022.1", "/fixtures/source.wav"), ("2025.1", r"C:\fixtures\source.wav")],
)
def test_audio_import_business_evidence_accepts_versioned_structural_proof(
    version: str,
    source_file: str,
) -> None:
    execution, verification = _audio_case(version)

    validate_audio_import_business_evidence(
        execution=execution,
        verification=verification,
        version=version,
        expected_target_path=TARGET_PATH,
        expected_target_id=TARGET_ID,
        expected_notes=NOTES,
        source_file=source_file,
    )


def test_2021_audio_import_uses_result_bound_source_when_accessor_is_absent() -> None:
    execution, verification = _audio_case("2021.1")
    execution["dispatch_result"]["result"]["objects"][0].pop("activeSource")
    verification["readbacks"][0]["result"]["return"][0].pop("activeSource")
    execution["dispatch_result"]["result"]["objects"][1]["parent"] = {
        "id": TARGET_ID
    }

    validate_audio_import_business_evidence(
        execution=execution,
        verification=verification,
        version="2021.1",
        expected_target_path=TARGET_PATH,
        expected_target_id=TARGET_ID,
        expected_notes=NOTES,
        source_file="/fixtures/source.wav",
    )


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        ("path", "path"),
        ("guid", "GUID"),
        ("type", "type"),
        ("log", "log"),
        ("active-source", "activeSource"),
    ],
)
def test_audio_import_business_evidence_rejects_targeted_tampering(
    tamper: str,
    message: str,
) -> None:
    execution, verification = _audio_case("2025.1")
    execution = copy.deepcopy(execution)
    verification = copy.deepcopy(verification)
    if tamper == "path":
        execution["dispatch_result"]["result"]["objects"][0]["path"] += "_drift"
    elif tamper == "guid":
        execution["dispatch_result"]["result"]["objects"][0]["id"] = OTHER_ID
    elif tamper == "type":
        verification["readbacks"][0]["result"]["return"][0]["type"] = "ActorMixer"
    elif tamper == "log":
        execution["dispatch_result"]["result"]["log"] = [
            {"severity": "Error", "message": "rejected", "index": 0}
        ]
    else:
        verification["readbacks"][0]["result"]["return"][0]["activeSource"] = {
            "id": OTHER_ID
        }

    with pytest.raises(WorkflowEvidenceError, match=message):
        validate_audio_import_business_evidence(
            execution=execution,
            verification=verification,
            version="2025.1",
            expected_target_path=TARGET_PATH,
            expected_target_id=TARGET_ID,
            expected_notes=NOTES,
            source_file=r"C:\fixtures\source.wav",
        )


def _soundbank_verification(filters: list[str]) -> dict[str, Any]:
    return _verification(
        "soundbank.setInclusions",
        [
            {
                "uri": "ak.wwise.core.soundbank.getInclusions",
                "args": {"soundbank": BANK_ID},
                "options": {},
                "result": {
                    "inclusions": [
                        {"object": {"id": INCLUDED_ID}, "filter": filters}
                    ]
                },
            }
        ],
    )


def test_soundbank_business_evidence_accepts_exact_object_filter_state() -> None:
    validate_soundbank_inclusions_business_evidence(
        _soundbank_verification(["structures", "media"]),
        soundbank_id=BANK_ID,
        expected=[
            {"object": INCLUDED_ID.casefold(), "filters": ["media", "structures"]}
        ],
    )


@pytest.mark.parametrize(
    ("tamper", "message"),
    [("filter", "filter"), ("object", "object")],
)
def test_soundbank_business_evidence_rejects_tampering(
    tamper: str,
    message: str,
) -> None:
    verification = _soundbank_verification(
        ["events"] if tamper == "filter" else ["structures", "media"]
    )
    if tamper == "object":
        verification["readbacks"][0]["result"]["inclusions"][0]["object"] = {
            "id": OTHER_ID
        }
    with pytest.raises(WorkflowEvidenceError, match=message):
        validate_soundbank_inclusions_business_evidence(
            verification,
            soundbank_id=BANK_ID,
            expected=[
                {
                    "object": INCLUDED_ID.casefold(),
                    "filters": ["media", "structures"],
                }
            ],
        )


def _switch_verification(*, should_exist: bool) -> dict[str, Any]:
    pairs = (
        [{"child": {"id": CHILD_ID}, "stateOrSwitch": {"id": SWITCH_ID}}]
        if should_exist
        else []
    )
    return _verification(
        (
            "switchContainer.addAssignment"
            if should_exist
            else "switchContainer.removeAssignment"
        ),
        [
            {
                "uri": "ak.wwise.core.switchContainer.getAssignments",
                "args": {"id": CONTAINER_ID},
                "options": {},
                "result": {"return": pairs},
            },
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"id": [CONTAINER_ID]}},
                "options": {},
                "result": {
                    "return": [
                        {
                            "id": CONTAINER_ID,
                            "type": "SwitchContainer",
                            "SwitchGroupOrStateGroup": {"id": GROUP_ID},
                        }
                    ]
                },
            },
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"id": [CHILD_ID]}},
                "options": {},
                "result": {
                    "return": [{"id": CHILD_ID, "type": "Sound", "parent": CONTAINER_ID}]
                },
            },
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"id": [GROUP_ID]}},
                "options": {},
                "result": {"return": [{"id": GROUP_ID, "type": "SwitchGroup"}]},
            },
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"id": [SWITCH_ID]}},
                "options": {},
                "result": {
                    "return": [{"id": SWITCH_ID, "type": "Switch", "parent": GROUP_ID}]
                },
            },
        ],
    )


@pytest.mark.parametrize("should_exist", [True, False])
def test_switch_assignment_business_evidence_accepts_exact_pair_state(
    should_exist: bool,
) -> None:
    validate_switch_assignment_business_evidence(
        _switch_verification(should_exist=should_exist),
        switch_container_id=CONTAINER_ID,
        switch_group_id=GROUP_ID,
        child_id=CHILD_ID,
        state_or_switch_id=SWITCH_ID,
        should_exist=should_exist,
    )


def test_switch_assignment_business_evidence_rejects_pair_tampering() -> None:
    verification = _switch_verification(should_exist=True)
    verification["readbacks"][0]["result"]["return"][0]["stateOrSwitch"] = {
        "id": OTHER_ID
    }

    with pytest.raises(WorkflowEvidenceError, match="pair"):
        validate_switch_assignment_business_evidence(
            verification,
            switch_container_id=CONTAINER_ID,
            switch_group_id=GROUP_ID,
            child_id=CHILD_ID,
            state_or_switch_id=SWITCH_ID,
            should_exist=True,
        )


def test_switch_assignment_business_evidence_rejects_relationship_tampering() -> None:
    verification = _switch_verification(should_exist=True)
    verification["readbacks"][2]["result"]["return"][0]["parent"] = OTHER_ID

    with pytest.raises(WorkflowEvidenceError, match="relationship"):
        validate_switch_assignment_business_evidence(
            verification,
            switch_container_id=CONTAINER_ID,
            switch_group_id=GROUP_ID,
            child_id=CHILD_ID,
            state_or_switch_id=SWITCH_ID,
            should_exist=True,
        )
