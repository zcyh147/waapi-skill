from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic import test_run_codex_skill_campaign_heavy_v3 as fixture
from tests.semantic.support.codex_campaign import CampaignEvidenceError
from tests.semantic.support.codex_harness import (
    prepare_workspace_skill_install,
    workspace_skill_install_path,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    PromptProvenanceEvidence,
)


def _set_owner_only_mode_on_posix(path: Path) -> None:
    if os.name == "posix":
        path.chmod(0o600)


def _passing_case(
    tmp_path: Path,
    *,
    unit: Any | None = None,
) -> tuple[campaign.CampaignOptions, Any, Path, Path, Path]:
    options = fixture._options(tmp_path)
    selected = unit or fixture._unit(1)
    root = tmp_path / "matrix"
    scenario_root = root / "scenarios" / f"001-{selected.unit_id}"
    visible: dict[str, Mapping[str, str]] = {}
    if selected.scenario.api == "ak.wwise.core.audio.convert":
        visible[selected.unit_id] = {
            "io_root": str(scenario_root / "owned" / "io")
        }
    fixture._write_matrix_evidence(
        root,
        options=options,
        units=(selected,),
        statuses=("PASS",),
        visible_values_by_id=visible,
    )
    task_root = scenario_root / "evidence" / "codex-task"
    return options, selected, root, scenario_root, task_root


def _validate(
    options: campaign.CampaignOptions,
    unit: Any,
    root: Path,
) -> None:
    validation = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=(unit,),
        options=options,
        returncode=0,
    )
    _raise_untrusted_case(validation)


def _nonpassing_case(
    tmp_path: Path,
    *,
    status: str,
) -> tuple[campaign.CampaignOptions, Any, Path, Path, Path]:
    options = fixture._options(tmp_path)
    unit = fixture._unit(1)
    root = tmp_path / "matrix"
    blocking = status in {"BLOCKED", "INDETERMINATE"}
    fixture._write_matrix_evidence(
        root,
        options=options,
        units=(unit,),
        statuses=(status,),
        stop_reason=(f"{status.lower()}:{unit.unit_id}" if blocking else ""),
        run_errors=((f"[heavy-unit:{unit.unit_id}] {status}: synthetic",) if blocking else ()),
    )
    scenario_root = root / "scenarios" / f"001-{unit.unit_id}"
    task_root = scenario_root / "evidence" / "codex-task"
    return options, unit, root, scenario_root, task_root


def _validate_nonpassing(
    options: campaign.CampaignOptions,
    unit: Any,
    root: Path,
) -> None:
    validation = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=(unit,),
        options=options,
        returncode=1,
    )
    _raise_untrusted_case(validation)


def _raise_untrusted_case(validation: campaign.ChildValidation) -> None:
    # Production preserves independently valid sibling cases and records a
    # tampered case as BLOCKED.  These single-case security tests retain their
    # precise ``pytest.raises`` assertions by surfacing only an evidence-
    # validation block through the historical helper contract.  A genuine
    # intact matrix BLOCKED/INDETERMINATE result remains an ordinary verdict.
    for verdict in validation.phase_verdicts:
        if verdict.status == "BLOCKED" and verdict.reason.startswith(
            "untrusted heavy "
        ):
            raise CampaignEvidenceError(verdict.reason)


def _campaign_prompt_asset_read_fixture(
    tmp_path: Path,
    *,
    asset_read_count: int = 1,
    asset_output: str | None = None,
    sealed_digest: str | None = None,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    campaign.CampaignOptions,
    Any,
    Path,
    Path,
    PromptProvenanceEvidence,
]:
    options = fixture._options(tmp_path)
    unit = fixture._unit(1)
    scenario_root = tmp_path / "scenario"
    task_root = scenario_root / "evidence" / "codex-task"
    turn_root = task_root / "turns" / "turn-01"
    turn_root.mkdir(parents=True)
    workspace = task_root / "agent-workspace"
    workspace.mkdir()
    skill_install = prepare_workspace_skill_install(
        workspace,
        options.skill_source,
        platform_name=(
            "nt" if options.windows_powershell_core_host is not None else "posix"
        ),
    )
    asset = scenario_root / "owned" / "inputs" / "import.tsv"
    asset.parent.mkdir(parents=True)
    content = "Object Path\t@Volume\n<Sound>City_A\t-3\n"
    asset.write_text(content, encoding="utf-8")
    encoded = content.encode("utf-8")
    protocol = fixture._synthetic_protocol(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    broker_records = fixture._synthetic_gateway_records(
        options=options,
        task_root=task_root,
        protocol=protocol,
        version=unit.version,
        invocation_skill_source=skill_install,
    )
    prompt = f"请使用输入表 {asset} 完成这个任务。"
    events_text = fixture._synthetic_events(
        thread_id="thread-prompt-asset",
        records=broker_records,
        final_response="waapi-skill 已加载，操作完成。",
        read_paths=(
            *fixture._synthetic_first_turn_reads(
                options,
                unit,
                skill_source=fixture._synthetic_runtime_skill_read_source(
                    options,
                    skill_install,
                ),
            ),
            *((asset,) * asset_read_count),
        ),
        windows_skill_read_source=(
            skill_install
            if options.windows_powershell_core_host is not None
            else None
        ),
        windows_powershell_core_host=options.windows_powershell_core_host,
    )
    if asset_output is not None:
        event_rows = [json.loads(line) for line in events_text.splitlines()]
        asset_command = fixture._synthetic_command(
            ("cat", str(asset.resolve())),
            windows_powershell_core_host=options.windows_powershell_core_host,
        )
        for row in event_rows:
            item = row.get("item")
            if (
                isinstance(item, dict)
                and item.get("type") == "command_execution"
                and item.get("command") == asset_command
            ):
                item["aggregated_output"] = asset_output
        events_text = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in event_rows
        )
    matrix.write_text(turn_root / "events.jsonl", events_text)
    facts = fixture._synthetic_codex_facts(
        options=options,
        task_root=task_root,
        turn_root=turn_root,
        turn_index=1,
        prompt=prompt,
        thread_id="thread-prompt-asset",
        events_text=events_text,
        protocol=protocol,
        version=unit.version,
    )
    facts = json.loads(json.dumps(facts, ensure_ascii=False))
    provenance = PromptProvenanceEvidence(
        path=scenario_root / "evidence" / "prompt-provenance.json",
        sha256="a" * 64,
        payload={
            "scenario_root": str(scenario_root),
            "owned_root": str(scenario_root / "owned"),
            "request": {
                "rendered_prompt": prompt,
                "inputs": [
                    {
                        "name": "tab_file",
                        "kind": "absolute_file_path",
                        "value": str(asset),
                        "leaf_bindings": [
                            {
                                "pointer": "",
                                "origin_kind": "owned_path",
                                "path_kind": "file",
                                "owned_relative_path": "inputs/import.tsv",
                                "size": len(encoded),
                                "sha256": (
                                    sealed_digest
                                    or hashlib.sha256(encoded).hexdigest()
                                ),
                                "mtime_ns": 1,
                            }
                        ],
                    }
                ],
            },
        },
        prompts=(prompt,),
        visible_values={"tab_file": str(asset)},
        protocol=protocol,
    )
    return (
        facts,
        {key: True for key in campaign._HEAVY_V3_REQUIRED_COMMON_GATES},
        options,
        unit,
        task_root,
        turn_root,
        provenance,
    )


def _validate_campaign_prompt_asset_read(
    fixture_value: tuple[
        dict[str, Any],
        dict[str, Any],
        campaign.CampaignOptions,
        Any,
        Path,
        Path,
        PromptProvenanceEvidence,
    ],
) -> tuple[Mapping[str, Any], ...]:
    (
        facts,
        archived_gates,
        options,
        unit,
        task_root,
        turn_root,
        provenance,
    ) = fixture_value
    return campaign._validate_heavy_v3_codex_facts(
        facts,
        turn_index=1,
        expected_prompt=provenance.prompts[0],
        expected_thread_id="thread-prompt-asset",
        turn_root=turn_root,
        task_root=task_root,
        options=options,
        expected_steps=provenance.protocol.steps,
        version=unit.version,
        expected_skill_reads=(
            "SKILL.md",
            fixture._synthetic_required_reference(unit),
        ),
        archived_common_gates=archived_gates,
        prompt_provenance=provenance,
    )


def test_campaign_revalidates_one_sealed_prompt_asset_cat_from_archive(
    tmp_path: Path,
) -> None:
    fixture_value = _campaign_prompt_asset_read_fixture(tmp_path)

    gateway_records = _validate_campaign_prompt_asset_read(fixture_value)

    assert len(gateway_records) == len(fixture_value[-1].protocol.steps)


@pytest.mark.parametrize(
    "tamper",
    ("output", "sealed_digest", "duplicate"),
)
def test_campaign_rejects_prompt_asset_cat_archive_tamper(
    tmp_path: Path,
    tamper: str,
) -> None:
    fixture_value = _campaign_prompt_asset_read_fixture(
        tmp_path,
        asset_output=("tampered\n" if tamper == "output" else None),
        sealed_digest=("0" * 64 if tamper == "sealed_digest" else None),
        asset_read_count=(2 if tamper == "duplicate" else 1),
    )

    with pytest.raises(
        CampaignEvidenceError,
        match="common gates cannot be recomputed",
    ):
        _validate_campaign_prompt_asset_read(fixture_value)


def _replace_config(command: list[str], prefix: str, replacement: str) -> None:
    index = next(index for index, value in enumerate(command) if value.startswith(prefix))
    command[index] = replacement


def _compact_media_reference_archive_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    oracle = {
        "expected_keys": ["referenced", "unreferenced"],
        "rows": [
            {
                "key": "referenced",
                "path": "/sealed/A_referenced.wav",
                "host_path": "/owned/Originals/SFX/A_referenced.wav",
            },
            {
                "key": "unreferenced",
                "path": "/sealed/B_unreferenced.wav",
                "host_path": "/owned/Originals/SFX/B_unreferenced.wav",
            },
            {
                "key": "decoy",
                "path": "/sealed/C_decoy.wav",
                "host_path": "/owned/Originals/SFX/C_decoy.wav",
            },
        ],
        "semantic_answer": {
            "referenced_keys": ["referenced"],
            "unreferenced_keys": ["unreferenced"],
        },
    }
    baseline = {
        "return": [
            {
                "id": "{00000000-0000-0000-0000-000000000001}",
                "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Reviewed\AudioFileSource",
                "originalFilePath": r"Y:\owned\Originals\SFX\A_referenced.wav",
            },
            {
                "id": "{00000000-0000-0000-0000-000000000002}",
                "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Decoy\AudioFileSource",
                "originalFilePath": r"Y:\owned\Originals\SFX\C_decoy.wav",
            },
        ]
    }
    compact = {
        "contract": campaign.REFERENCE_MATCH_RESULT_CONTRACT,
        "scanned_audio_source_count": 2,
        "scan_limit": campaign.REFERENCE_MATCH_SCAN_LIMIT,
        "scan_complete": True,
        "candidates": [
            {
                "originalFilePath": "/sealed/A_referenced.wav",
                "classification": "referenced",
                "reference_count": 1,
                "references": [
                    {
                        "id": "{00000000-0000-0000-0000-000000000001}",
                        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Reviewed\AudioFileSource",
                    }
                ],
                "references_truncated": False,
            },
            {
                "originalFilePath": "/sealed/B_unreferenced.wav",
                "classification": "unreferenced",
                "reference_count": 0,
                "references": [],
                "references_truncated": False,
            },
        ],
    }
    return oracle, baseline, compact


def test_compact_media_reference_archive_joins_candidate_subset_to_full_baseline() -> None:
    oracle, baseline, compact = _compact_media_reference_archive_fixture()

    campaign._validate_compact_media_reference_archive(
        compact,
        reference_baseline=baseline,
        oracle=oracle,
        label="synthetic compact Media Pool reference archive",
    )


def test_media_archive_uses_producer_path_flavor_for_basenames() -> None:
    oracle, baseline, compact = _compact_media_reference_archive_fixture()
    oracle["rows"][0]["host_path"] = (
        r"\\StudioNas\Audio Share\Originals\SFX\A_REFERENCED.WAV"
    )
    baseline["return"][0]["originalFilePath"] = (
        r"\\studionas\audio share\originals\sfx\a_referenced.wav"
    )

    campaign._validate_compact_media_reference_archive(
        compact,
        reference_baseline=baseline,
        oracle=oracle,
        label="cross-host compact Media Pool reference archive",
    )

    aliases = campaign._serialized_media_response_filenames(
        {"request": {"binding": {"by_concept": {"name": "Filename"}}}},
        {
            "values": {"Filename": "A_referenced.wav"},
            "host_path": r"C:\Fixture Inputs\A_REFERENCED.WAV",
        },
        label="cross-host Media Pool row",
    )
    assert aliases == ("a_referenced.wav",)


@pytest.mark.parametrize(
    "path",
    (
        r"Y:\owned\\Originals\SFX\A_referenced.wav",
        r"Y:\owned\Originals\..\A_referenced.wav",
        r"Y:\owned/Originals\SFX\A_referenced.wav",
    ),
)
def test_compact_media_reference_archive_rejects_normalizing_windows_paths(
    path: str,
) -> None:
    oracle, baseline, compact = _compact_media_reference_archive_fixture()
    baseline["return"][0]["originalFilePath"] = path

    with pytest.raises(CampaignEvidenceError, match="baseline path"):
        campaign._validate_compact_media_reference_archive(
            compact,
            reference_baseline=baseline,
            oracle=oracle,
            label="malformed cross-host compact archive",
        )


def test_campaign_file_proofs_use_archive_path_semantics() -> None:
    proof = {
        "path": r"C:\Campaign\Originals\SFX\Thunder.WAV",
        "relative_path": "Originals/SFX/thunder.wav",
        "size": 12,
        "sha256": "a" * 64,
    }
    campaign._validate_file_proof(
        proof,
        label="Windows file proof",
        relative_optional=False,
        has_mtime=False,
    )

    posix_case_attack = dict(proof)
    posix_case_attack["path"] = "/campaign/Originals/SFX/Thunder.WAV"
    with pytest.raises(CampaignEvidenceError, match="file proof"):
        campaign._validate_file_proof(
            posix_case_attack,
            label="POSIX file proof",
            relative_optional=False,
            has_mtime=False,
        )

    for relative_path in (
        "Originals//SFX/Thunder.WAV",
        "Originals/../SFX/Thunder.WAV",
        r"Originals\SFX/Thunder.WAV",
    ):
        malformed = dict(proof)
        malformed["relative_path"] = relative_path
        with pytest.raises(CampaignEvidenceError, match="file proof"):
            campaign._validate_file_proof(
                malformed,
                label="malformed file proof",
                relative_optional=False,
                has_mtime=False,
            )


def test_compact_media_reference_archive_rejects_contract_and_equivalence_tampering() -> None:
    oracle, baseline, compact = _compact_media_reference_archive_fixture()
    tampered_values: list[tuple[str, Any, Any]] = []

    old_broad = {"return": []}
    tampered_values.append(("old broad result", old_broad, baseline))

    bad_contract = copy.deepcopy(compact)
    bad_contract["contract"] = "forged"
    tampered_values.append(("contract", bad_contract, baseline))

    incomplete = copy.deepcopy(compact)
    incomplete["scan_complete"] = False
    tampered_values.append(("incomplete scan", incomplete, baseline))

    wrong_scan_count = copy.deepcopy(compact)
    wrong_scan_count["scanned_audio_source_count"] = 1
    tampered_values.append(("scan count", wrong_scan_count, baseline))

    wrong_limit = copy.deepcopy(compact)
    wrong_limit["scan_limit"] = 999
    tampered_values.append(("scan limit", wrong_limit, baseline))

    wrong_order = copy.deepcopy(compact)
    wrong_order["candidates"].reverse()
    tampered_values.append(("candidate order", wrong_order, baseline))

    wrong_classification = copy.deepcopy(compact)
    wrong_classification["candidates"][1]["classification"] = "referenced"
    tampered_values.append(("classification", wrong_classification, baseline))

    truncated = copy.deepcopy(compact)
    truncated["candidates"][0]["references_truncated"] = True
    tampered_values.append(("truncated references", truncated, baseline))

    wrong_reference = copy.deepcopy(compact)
    wrong_reference["candidates"][0]["references"][0]["path"] += "_forged"
    tampered_values.append(("reference equivalence", wrong_reference, baseline))

    extra_field = copy.deepcopy(compact)
    extra_field["candidates"][0]["unexpected"] = True
    tampered_values.append(("closed candidate", extra_field, baseline))

    forged_baseline = copy.deepcopy(baseline)
    forged_baseline["return"][0]["id"] = "{00000000-0000-0000-0000-000000000099}"
    tampered_values.append(("trusted subset", compact, forged_baseline))

    for name, candidate_value, baseline_value in tampered_values:
        with pytest.raises(CampaignEvidenceError) as caught:
            campaign._validate_compact_media_reference_archive(
                candidate_value,
                reference_baseline=baseline_value,
                oracle=oracle,
                label=f"tampered {name}",
            )
        assert name in str(caught.value)


def _topic_ack_validator_case(
    tmp_path: Path,
    *,
    publisher_count: int = 3,
    write_broker_record: bool = True,
) -> tuple[
    dict[str, Any],
    Path,
    campaign.HeavyV3PromptEvidence,
    dict[str, Any],
]:
    evidence_directory = tmp_path / "broker" / "evidence"
    evidence_directory.mkdir(parents=True)
    ack_path = evidence_directory / "subscription-ack-synthetic.json"
    payload = {
        "contract": campaign.TOPIC_ACK_CONTRACT,
        "step_name": "soundbank.generated.wait",
        "topic": campaign.SOUNDBANK_TOPIC,
        "nonce": "n" * 43,
        "runner_parent_process_id": 123,
        "gateway_process_id": 124,
        "subscribed_at_unix_ns": 1_700_000_000_100_000_000,
        "subscribed_at_monotonic_ns": 100,
    }
    raw = campaign.canonical_json_bytes(payload) + b"\n"
    ack_path.write_bytes(raw)
    _set_owner_only_mode_on_posix(ack_path)
    requirement = {
        "contract": campaign.TOPIC_ACK_REQUIREMENT_CONTRACT,
        "ack_contract": campaign.TOPIC_ACK_CONTRACT,
        "step_name": "soundbank.generated.wait",
        "topic": campaign.SOUNDBANK_TOPIC,
        "fresh_exclusive_path_required": True,
        "publisher_requires_valid_ack": True,
    }
    typed_sections = campaign.SoundBankBusinessPlanSections(
        fixture_spec={},
        payload_bindings={},
        assertion_ids=(),
        static_expectation={},
        live_binding={
            "topic": {
                "subscription_ack_requirement": requirement,
                "publisher_requests": [
                    {
                        "schema_version": "waapi-skill.operation-request/v1",
                        "operation": "soundbank.generate",
                        "version": "2022.1",
                        "request": {"synthetic_index": index},
                    }
                    for index in range(1, publisher_count + 1)
                ],
            }
        },
        delta_rules=(),
    )
    prompt_evidence = campaign.HeavyV3PromptEvidence(
        prompts=(),
        provenance=None,  # type: ignore[arg-type]
        business_oracle_plan=campaign.BusinessOraclePlanEvidence(
            path=tmp_path / "business-oracle-plan.json",
            sha256="a" * 64,
            payload={},
        ),
        typed_sections=typed_sections,
    )
    proof = {
        "contract": campaign.TOPIC_ACK_PROOF_CONTRACT,
        "business_oracle_plan_sha256": "a" * 64,
        "requirement": copy.deepcopy(requirement),
        "ack_path": str(ack_path.resolve()),
        "ack_file_sha256": hashlib.sha256(raw).hexdigest(),
        "ack_payload": copy.deepcopy(payload),
        "ack_observed_at_monotonic_ns": 101,
        "publisher_started_at_monotonic_ns": 102,
        "publisher_call_started_at_monotonic_ns": list(
            range(103, 103 + publisher_count)
        ),
        "ack_before_publish": True,
    }
    broker_ack = {
        "contract": campaign.VALIDATED_SUBSCRIPTION_ACK_CONTRACT,
        "ack_contract": campaign.TOPIC_ACK_CONTRACT,
        "step_name": "soundbank.generated.wait",
        "topic": campaign.SOUNDBANK_TOPIC,
        "ack_path": str(ack_path.resolve()),
        "ack_file_sha256": hashlib.sha256(raw).hexdigest(),
        "nonce_sha256": hashlib.sha256(("n" * 43).encode("utf-8")).hexdigest(),
        "runner_parent_process_id": 123,
        "gateway_process_id": 124,
        "subscribed_at_unix_ns": payload["subscribed_at_unix_ns"],
        "subscribed_at_monotonic_ns": payload["subscribed_at_monotonic_ns"],
        "step_started_at_unix_ns": 1_700_000_000_000_000_000,
        "validated_at_unix_ns": 1_700_000_000_200_000_000,
        "step_finished_at_unix_ns": 1_700_000_000_300_000_000,
    }
    broker_record = {
        "step_name": "soundbank.generated.wait",
        "authenticated": True,
        "accepted": True,
        "succeeded": True,
        "payload_error": "",
        "started_at_unix_ns": broker_ack["step_started_at_unix_ns"],
        "finished_at_unix_ns": broker_ack["step_finished_at_unix_ns"],
        "subscription_ack": broker_ack,
    }
    if write_broker_record:
        matrix.write_json(
            tmp_path / "task-result.json",
            {"broker": {"records": [broker_record]}},
        )
    return proof, ack_path, prompt_evidence, broker_record


def _topic_publisher_diagnostics_case(
    proof: Mapping[str, Any],
    prompt_evidence: campaign.HeavyV3PromptEvidence,
) -> dict[str, Any]:
    topic = prompt_evidence.typed_sections.live_binding["topic"]
    requests = topic["publisher_requests"]
    call_times = proof["publisher_call_started_at_monotonic_ns"]
    calls: list[dict[str, Any]] = []
    for index, (request, started) in enumerate(
        zip(requests, call_times, strict=True),
        start=1,
    ):
        result_value = {"logs": []}
        result_raw = campaign.canonical_json_bytes(result_value)
        calls.append(
            {
                "index": index,
                "request_sha256": hashlib.sha256(
                    campaign.canonical_json_bytes(request)
                ).hexdigest(),
                "status": "succeeded",
                "uri": "ak.wwise.core.soundbank.generate",
                "args_sha256": str(index) * 64,
                "options_sha256": str(index + 3) * 64,
                "started_at_monotonic_ns": started,
                "finished_at_monotonic_ns": started + 1,
                "result": {
                    "sha256": hashlib.sha256(result_raw).hexdigest(),
                    "size_bytes": len(result_raw),
                    "included": True,
                    "value": result_value,
                },
            }
        )
    ack_payload = proof["ack_payload"]
    return {
        "contract": campaign.HEAVY_V3_TOPIC_PUBLISHER_DIAGNOSTICS_CONTRACT,
        "diagnostic_only": True,
        "abort_requested": False,
        "execution_mode": "spawn_process",
        "ack": {
            "contract": campaign.TOPIC_ACK_CONTRACT,
            "step_name": "soundbank.generated.wait",
            "topic": campaign.SOUNDBANK_TOPIC,
            "path": proof["ack_path"],
            "nonce_sha256": hashlib.sha256(
                ack_payload["nonce"].encode("utf-8")
            ).hexdigest(),
            "observed": True,
            "file_sha256": proof["ack_file_sha256"],
            "observed_at_monotonic_ns": proof["ack_observed_at_monotonic_ns"],
            "payload": {
                key: value for key, value in ack_payload.items() if key != "nonce"
            },
        },
        "publisher_started_at_monotonic_ns": proof[
            "publisher_started_at_monotonic_ns"
        ],
        "publisher_finished_at_monotonic_ns": max(call_times) + 2,
        "publisher_call_evidence": calls,
        "result_count": len(requests),
        "direct_call_count": len(requests) * 2,
        "client_opened": True,
        "client_closed": True,
        "child_process": {
            "start_method": "spawn",
            "coordinator_process_id": 126,
            "pid": 125,
            "parent_pid": 126,
            "exit_code": 0,
            "reaped": True,
            "terminate_requested": False,
            "kill_requested": False,
            "canonical_result_received": True,
            "child_started_at_monotonic_ns": proof[
                "publisher_started_at_monotonic_ns"
            ],
            "child_finished_at_monotonic_ns": max(call_times) + 1,
            "cleanup_error": None,
        },
        "error": None,
    }


def test_topic_ack_campaign_validator_accepts_closed_plan_bound_timeline(
    tmp_path: Path,
) -> None:
    proof, _ack_path, prompt_evidence, _record = _topic_ack_validator_case(tmp_path)

    campaign._validate_heavy_v3_topic_subscription_ack(
        proof,
        api=campaign.SOUNDBANK_TOPIC,
        publisher_count=3,
        task_root=tmp_path,
        prompt_evidence=prompt_evidence,
    )


def test_topic_publisher_campaign_validator_accepts_one_clean_spawn_child(
    tmp_path: Path,
) -> None:
    proof, _ack_path, prompt_evidence, _record = _topic_ack_validator_case(tmp_path)
    diagnostics = _topic_publisher_diagnostics_case(proof, prompt_evidence)

    campaign._validate_heavy_v3_topic_publisher_process(
        diagnostics,
        api=campaign.SOUNDBANK_TOPIC,
        publisher_count=3,
        ack_proof=proof,
        prompt_evidence=prompt_evidence,
    )


def test_topic_publisher_count_is_independent_from_resulting_event_matrix(
    tmp_path: Path,
) -> None:
    # The reviewed 2-bank x 2-platform case emits four events from one
    # soundbank.generate publisher request.  The two counts must never be
    # conflated by the passing validator.
    proof, _ack_path, prompt_evidence, _record = _topic_ack_validator_case(
        tmp_path,
        publisher_count=1,
    )
    diagnostics = _topic_publisher_diagnostics_case(proof, prompt_evidence)

    assert campaign._heavy_v3_topic_publisher_request_count(prompt_evidence) == 1
    campaign._validate_heavy_v3_topic_subscription_ack(
        proof,
        api=campaign.SOUNDBANK_TOPIC,
        publisher_count=1,
        task_root=tmp_path,
        prompt_evidence=prompt_evidence,
    )
    campaign._validate_heavy_v3_topic_publisher_process(
        diagnostics,
        api=campaign.SOUNDBANK_TOPIC,
        publisher_count=1,
        ack_proof=proof,
        prompt_evidence=prompt_evidence,
    )


@pytest.mark.parametrize(
    ("tamper", "message"),
    (
        ("execution_mode", "complete spawn execution"),
        ("abort", "complete spawn execution"),
        ("top_error", "complete spawn execution"),
        ("ack_path", "sealed ACK proof"),
        ("start_method", "spawned child process"),
        ("child_pid", "spawned child process"),
        ("parent_pid", "spawned child process"),
        ("coordinator_pid", "spawned child process"),
        ("exit_code", "spawned child process"),
        ("not_reaped", "spawned child process"),
        ("terminated", "spawned child process"),
        ("killed", "spawned child process"),
        ("no_canonical_result", "spawned child process"),
        ("child_timeline", "spawned child process"),
        ("cleanup_error", "spawned child process"),
        ("request_digest", "reviewed request"),
        ("call_status", "reviewed request"),
        ("call_timeline", "reviewed request"),
        ("result_digest", "reviewed request"),
    ),
)
def test_topic_publisher_campaign_validator_rejects_tampered_process_evidence(
    tmp_path: Path,
    tamper: str,
    message: str,
) -> None:
    proof, _ack_path, prompt_evidence, _record = _topic_ack_validator_case(tmp_path)
    diagnostics = _topic_publisher_diagnostics_case(proof, prompt_evidence)
    child = diagnostics["child_process"]
    first_call = diagnostics["publisher_call_evidence"][0]
    if tamper == "execution_mode":
        diagnostics["execution_mode"] = "injected_thread"
    elif tamper == "abort":
        diagnostics["abort_requested"] = True
    elif tamper == "top_error":
        diagnostics["error"] = "synthetic"
    elif tamper == "ack_path":
        diagnostics["ack"]["path"] = "/tmp/other-ack.json"
    elif tamper == "start_method":
        child["start_method"] = "fork"
    elif tamper == "child_pid":
        child["pid"] = child["parent_pid"]
    elif tamper == "parent_pid":
        child["parent_pid"] += 1
    elif tamper == "coordinator_pid":
        child["coordinator_process_id"] = proof["ack_payload"][
            "runner_parent_process_id"
        ]
    elif tamper == "exit_code":
        child["exit_code"] = 1
    elif tamper == "not_reaped":
        child["reaped"] = False
    elif tamper == "terminated":
        child["terminate_requested"] = True
    elif tamper == "killed":
        child["kill_requested"] = True
    elif tamper == "no_canonical_result":
        child["canonical_result_received"] = False
    elif tamper == "child_timeline":
        child["child_finished_at_monotonic_ns"] = 1
    elif tamper == "cleanup_error":
        child["cleanup_error"] = "synthetic cleanup failure"
    elif tamper == "request_digest":
        first_call["request_sha256"] = "f" * 64
    elif tamper == "call_status":
        first_call["status"] = "failed"
    elif tamper == "call_timeline":
        first_call["finished_at_monotonic_ns"] = 1
    elif tamper == "result_digest":
        first_call["result"]["sha256"] = "f" * 64
    else:  # pragma: no cover - the parameter set is closed
        raise AssertionError(tamper)

    with pytest.raises(CampaignEvidenceError, match=message):
        campaign._validate_heavy_v3_topic_publisher_process(
            diagnostics,
            api=campaign.SOUNDBANK_TOPIC,
            publisher_count=3,
            ack_proof=proof,
            prompt_evidence=prompt_evidence,
        )


def test_topic_ack_campaign_validator_rejects_runner_self_proof_without_broker_record(
    tmp_path: Path,
) -> None:
    proof, _ack_path, prompt_evidence, _record = _topic_ack_validator_case(
        tmp_path,
        write_broker_record=False,
    )

    with pytest.raises(CampaignEvidenceError, match="broker record"):
        campaign._validate_heavy_v3_topic_subscription_ack(
            proof,
            api=campaign.SOUNDBANK_TOPIC,
            publisher_count=3,
            task_root=tmp_path,
            prompt_evidence=prompt_evidence,
        )


@pytest.mark.parametrize(
    ("tamper", "message"),
    (
        ("file_hash", "file proof drifted"),
        ("wrong_topic_consistent", "payload identity"),
        ("requirement", "typed business plan"),
        ("timeline", "timeline"),
        ("duplicate_link", "private exclusive"),
        ("outside_broker_evidence", "private exclusive"),
        ("noncanonical", "canonical form"),
        ("broker_hash", "validated broker hash, PID, and time"),
        ("broker_pid", "validated broker hash, PID, and time"),
        ("broker_time", "validated broker hash, PID, and time"),
    ),
)
def test_topic_ack_campaign_validator_rejects_tampered_evidence(
    tmp_path: Path,
    tamper: str,
    message: str,
) -> None:
    proof, ack_path, prompt_evidence, broker_record = _topic_ack_validator_case(
        tmp_path
    )
    if tamper == "file_hash":
        proof["ack_file_sha256"] = "f" * 64
    elif tamper == "wrong_topic_consistent":
        payload = copy.deepcopy(proof["ack_payload"])
        payload["topic"] = "ak.wwise.core.soundbank.other"
        raw = campaign.canonical_json_bytes(payload) + b"\n"
        ack_path.write_bytes(raw)
        _set_owner_only_mode_on_posix(ack_path)
        proof["ack_payload"] = payload
        proof["ack_file_sha256"] = hashlib.sha256(raw).hexdigest()
    elif tamper == "requirement":
        proof["requirement"]["topic"] = "ak.wwise.core.soundbank.other"
    elif tamper == "timeline":
        proof["ack_observed_at_monotonic_ns"] = 104
    elif tamper == "duplicate_link":
        (ack_path.parent / "subscription-ack-duplicate.json").hardlink_to(ack_path)
    elif tamper == "outside_broker_evidence":
        outside = tmp_path / "subscription-ack-outside.json"
        outside.write_bytes(ack_path.read_bytes())
        _set_owner_only_mode_on_posix(outside)
        proof["ack_path"] = str(outside.resolve())
    elif tamper == "noncanonical":
        payload = proof["ack_payload"]
        raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        ack_path.write_bytes(raw)
        _set_owner_only_mode_on_posix(ack_path)
        proof["ack_file_sha256"] = hashlib.sha256(raw).hexdigest()
    elif tamper == "broker_hash":
        broker_record["subscription_ack"]["ack_file_sha256"] = "f" * 64
        matrix.write_json(
            tmp_path / "task-result.json",
            {"broker": {"records": [broker_record]}},
        )
    elif tamper == "broker_pid":
        broker_record["subscription_ack"]["gateway_process_id"] = 999
        matrix.write_json(
            tmp_path / "task-result.json",
            {"broker": {"records": [broker_record]}},
        )
    elif tamper == "broker_time":
        broker_record["subscription_ack"]["subscribed_at_unix_ns"] += 1
        matrix.write_json(
            tmp_path / "task-result.json",
            {"broker": {"records": [broker_record]}},
        )
    else:  # pragma: no cover - the parameter set is closed
        raise AssertionError(tamper)

    with pytest.raises(CampaignEvidenceError, match=message):
        campaign._validate_heavy_v3_topic_subscription_ack(
            proof,
            api=campaign.SOUNDBANK_TOPIC,
            publisher_count=3,
            task_root=tmp_path,
            prompt_evidence=prompt_evidence,
        )


@pytest.mark.parametrize(
    "drift",
    ("model", "reasoning", "service", "approval", "memory", "cwd", "prompt"),
)
def test_success_rejects_initial_codex_argv_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    options, unit, root, _scenario_root, task_root = _passing_case(tmp_path)
    facts_path = task_root / "turns" / "turn-01" / "codex-facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    command = facts["command"]
    if drift == "model":
        command[command.index("--model") + 1] = "gpt-tampered"
    elif drift == "reasoning":
        _replace_config(command, "model_reasoning_effort=", 'model_reasoning_effort="low"')
    elif drift == "service":
        _replace_config(command, "service_tier=", 'service_tier="priority"')
    elif drift == "approval":
        _replace_config(command, "approval_policy=", 'approval_policy="on-request"')
    elif drift == "memory":
        command[command.index("memories")] = "not-memories"
    elif drift == "cwd":
        command[command.index("-C") + 1] = "/tmp/tampered-workspace"
    else:
        command[-1] = "tampered user prompt"
    matrix.write_json(facts_path, facts)

    with pytest.raises(CampaignEvidenceError, match="exact no-memory initial/resume argv"):
        _validate(options, unit, root)


@pytest.mark.parametrize("drift", ("thread", "last", "prompt"))
def test_success_rejects_resume_codex_argv_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    unit = fixture._multi_turn_unit(1)
    options, unit, root, _scenario_root, task_root = _passing_case(
        tmp_path,
        unit=unit,
    )
    facts_path = task_root / "turns" / "turn-02" / "codex-facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    command = facts["command"]
    resume = command.index("resume")
    if drift == "thread":
        command[resume + 1] = "thread-other"
    elif drift == "last":
        command[resume + 1] = "--last"
    else:
        command[-1] = "tampered confirmation"
    matrix.write_json(facts_path, facts)

    with pytest.raises(CampaignEvidenceError, match="exact no-memory initial/resume argv"):
        _validate(options, unit, root)


def test_success_rejects_gateway_commands_redistributed_across_turns(
    tmp_path: Path,
) -> None:
    unit = fixture._multi_turn_unit(1)
    options, unit, root, scenario_root, task_root = _passing_case(
        tmp_path,
        unit=unit,
    )
    task_result = json.loads((task_root / "task-result.json").read_text(encoding="utf-8"))
    records = task_result["broker"]["records"]
    protocol = fixture._synthetic_protocol(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    skill_install = workspace_skill_install_path(task_root / "agent-workspace")
    for index, allocated in ((1, records), (2, [])):
        turn_root = task_root / "turns" / f"turn-{index:02d}"
        final = (turn_root / "final.txt").read_text(encoding="utf-8")[:-1]
        events = fixture._synthetic_events(
            thread_id="thread-1",
            records=allocated,
            final_response=final,
            read_paths=(
                fixture._synthetic_first_turn_reads(
                    options,
                    unit,
                    skill_source=fixture._synthetic_runtime_skill_read_source(
                        options,
                        skill_install,
                    ),
                )
                if index == 1
                else ()
            ),
            windows_skill_read_source=(
                skill_install
                if options.windows_powershell_core_host is not None
                else None
            ),
            windows_powershell_core_host=options.windows_powershell_core_host,
        )
        matrix.write_text(turn_root / "events.jsonl", events)
        facts = fixture._synthetic_codex_facts(
            options=options,
            task_root=task_root,
            turn_root=turn_root,
            turn_index=index,
            prompt=unit.turns[index - 1].prompt,
            thread_id="thread-1",
            events_text=events,
            protocol=protocol,
            version=unit.version,
        )
        matrix.write_json(turn_root / "codex-facts.json", facts)

    with pytest.raises(
        CampaignEvidenceError,
        match="common gates|sealed prefix delta|command facts",
    ):
        _validate(options, unit, root)


def test_success_rejects_events_and_facts_drift(tmp_path: Path) -> None:
    options, unit, root, _scenario_root, task_root = _passing_case(tmp_path)
    events_path = task_root / "turns" / "turn-01" / "events.jsonl"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    message = next(
        row["item"]
        for row in rows
        if row.get("type") == "item.completed"
        and row.get("item", {}).get("type") == "agent_message"
    )
    message["text"] += " tampered"
    matrix.write_text(
        events_path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
    )

    with pytest.raises(CampaignEvidenceError, match="reconstructed from events"):
        _validate(options, unit, root)


@pytest.mark.parametrize("tamper", ("duplicate", "mispaired"))
def test_success_rejects_duplicate_or_mispaired_command_item_ids(
    tmp_path: Path,
    tamper: str,
) -> None:
    options, unit, root, scenario_root, task_root = _passing_case(tmp_path)
    turn_root = task_root / "turns" / "turn-01"
    rows = [
        json.loads(line)
        for line in (turn_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for row in rows:
        item = row.get("item")
        if not isinstance(item, Mapping) or item.get("id") != "gateway-1":
            continue
        if tamper == "duplicate" or row.get("type") == "item.completed":
            item["id"] = "read-2"
    events = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    )
    matrix.write_text(turn_root / "events.jsonl", events)
    protocol = fixture._synthetic_protocol(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    facts = fixture._synthetic_codex_facts(
        options=options,
        task_root=task_root,
        turn_root=turn_root,
        turn_index=1,
        prompt=unit.turns[0].prompt,
        thread_id="thread-1",
        events_text=events,
        protocol=protocol,
        version=unit.version,
    )
    matrix.write_json(turn_root / "codex-facts.json", facts)

    with pytest.raises(CampaignEvidenceError, match="duplicated or mispaired"):
        _validate(options, unit, root)


def _broker_tamper(name: str, broker: dict[str, Any]) -> None:
    records = broker["records"]
    if name == "delete":
        records.pop()
    elif name == "reorder":
        records.reverse()
    elif name == "duplicate":
        records.append(copy.deepcopy(records[0]))
    elif name == "missing_field":
        records[0].pop("semantic_argv_sha256")
    elif name == "extra_field":
        records[0]["extra"] = True
    elif name in {
        "raw_argv_sha256",
        "argv_sha256",
        "semantic_argv_sha256",
        "payload_sha256",
        "runner_command_sha256",
    }:
        records[0][name] = "0" * 64
    elif name == "model_argv":
        records[0]["model_argv"][0] = "/tmp/python"
    elif name == "runner_path":
        broker["runner_path"] = "/tmp/run.py"
    elif name == "state_directory":
        broker["state_directory"] = "/tmp/state"
    elif name == "evidence_directory":
        broker["evidence_directory"] = "/tmp/evidence"
    else:  # pragma: no cover - parameter list is closed
        raise AssertionError(name)


@pytest.mark.parametrize(
    "tamper",
    (
        "delete",
        "reorder",
        "duplicate",
        "missing_field",
        "extra_field",
        "raw_argv_sha256",
        "argv_sha256",
        "semantic_argv_sha256",
        "payload_sha256",
        "runner_command_sha256",
        "model_argv",
        "runner_path",
        "state_directory",
        "evidence_directory",
    ),
)
def test_success_rejects_broker_record_or_path_tamper(
    tmp_path: Path,
    tamper: str,
) -> None:
    unit = fixture._multi_turn_unit(1)
    options, unit, root, _scenario_root, task_root = _passing_case(
        tmp_path,
        unit=unit,
    )
    result_path = task_root / "task-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    _broker_tamper(tamper, result["broker"])
    matrix.write_json(result_path, result)

    with pytest.raises(CampaignEvidenceError):
        _validate(options, unit, root)


def _broker_alignment_fixture(
    tmp_path: Path,
) -> tuple[
    campaign.CampaignOptions,
    Any,
    Path,
    Any,
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    options, unit, _root, scenario_root, task_root = _passing_case(tmp_path)
    task_result = json.loads(
        (task_root / "task-result.json").read_text(encoding="utf-8")
    )
    facts = json.loads(
        (task_root / "turns" / "turn-01" / "codex-facts.json").read_text(
            encoding="utf-8"
        )
    )
    command_facts = facts["command_facts"]
    gateway_commands = set(command_facts["gateway_attempt_commands"])
    command_records = [
        copy.deepcopy(record)
        for record in command_facts["command_records"]
        if record["command"] in gateway_commands
    ]
    protocol = fixture._synthetic_protocol(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    return (
        options,
        unit,
        task_root,
        protocol,
        task_result["broker"]["records"],
        command_records,
    )


def test_broker_alignment_accepts_bare_event_python_for_absolute_path_shim(
    tmp_path: Path,
) -> None:
    options, unit, task_root, protocol, broker_records, command_records = (
        _broker_alignment_fixture(tmp_path)
    )
    assert Path(broker_records[0]["model_argv"][0]).is_absolute()
    command_records[0]["argv"][0] = "python"

    campaign._validate_heavy_v3_broker_records(
        broker_records,
        task_root=task_root,
        steps=protocol.steps,
        command_records=command_records,
        options=options,
        version=unit.version,
        label="synthetic normalized",
    )


def test_broker_alignment_rejects_empty_codex_command_output(tmp_path: Path) -> None:
    options, unit, task_root, protocol, broker_records, command_records = (
        _broker_alignment_fixture(tmp_path)
    )
    command_records[0]["aggregated_output"] = ""

    with pytest.raises(
        CampaignEvidenceError,
        match="Codex command output is not the broker JSON payload",
    ):
        campaign._validate_heavy_v3_broker_records(
            broker_records,
            task_root=task_root,
            steps=protocol.steps,
            command_records=command_records,
            options=options,
            version=unit.version,
            label="synthetic empty output",
        )


@pytest.mark.parametrize(
    "tamper",
    (
        "interpreter_identity",
        "outside_shim",
        "runner_path",
        "gateway_argument",
        "exit_code",
        "status",
        "shell_operator",
        "parse_error",
    ),
)
def test_broker_alignment_rejects_normalized_or_completion_tamper(
    tmp_path: Path,
    tamper: str,
) -> None:
    options, unit, task_root, protocol, broker_records, command_records = (
        _broker_alignment_fixture(tmp_path)
    )
    record = command_records[0]
    record["argv"][0] = "python"
    if tamper == "interpreter_identity":
        record["argv"][0] = "python3"
    elif tamper == "outside_shim":
        record["argv"][0] = "/tmp/python"
    elif tamper == "runner_path":
        record["argv"][1] = "/tmp/run.py"
    elif tamper == "gateway_argument":
        record["argv"][-1] = "tampered"
    elif tamper == "exit_code":
        record["exit_code"] = 9
    elif tamper == "status":
        record["status"] = "failed"
    elif tamper == "shell_operator":
        record["has_shell_operators"] = True
    elif tamper == "parse_error":
        record["parse_error"] = "synthetic parse failure"
    else:  # pragma: no cover - parameter list is closed
        raise AssertionError(tamper)

    with pytest.raises(CampaignEvidenceError):
        campaign._validate_heavy_v3_broker_records(
            broker_records,
            task_root=task_root,
            steps=protocol.steps,
            command_records=command_records,
            options=options,
            version=unit.version,
            label="synthetic normalized",
        )


def _persist_outcome(scenario_root: Path, outcome: Mapping[str, Any]) -> None:
    fixture._persist_runner_outcome(scenario_root, outcome)


@pytest.mark.parametrize(
    "tamper",
    ("generic", "api", "scenario_id", "version", "runner", "object_missing_after"),
)
def test_success_rejects_generic_or_cross_bound_object_oracle(
    tmp_path: Path,
    tamper: str,
) -> None:
    options, unit, root, scenario_root, _task_root = _passing_case(tmp_path)
    outcome_path = scenario_root / "outcome.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    oracle = outcome["checks"]["business_verification"]
    if tamper == "generic":
        oracle["verification"] = {"passed": True}
    elif tamper == "object_missing_after":
        oracle["verification"]["evidence"].pop("after")
    else:
        oracle[tamper] = {
            "api": "ak.wwise.core.object.set",
            "scenario_id": "OTHER",
            "version": "2025.1",
            "runner": "cli",
        }[tamper]
    _persist_outcome(scenario_root, outcome)

    with pytest.raises(CampaignEvidenceError):
        _validate(options, unit, root)


def test_success_rejects_audio_before_equals_after(tmp_path: Path) -> None:
    unit = fixture._visible_request_unit(1)
    options, unit, root, scenario_root, _task_root = _passing_case(
        tmp_path,
        unit=unit,
    )
    outcome_path = scenario_root / "outcome.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    evidence = outcome["checks"]["business_verification"]["verification"]["evidence"]
    evidence["before"] = copy.deepcopy(evidence["after"])
    _persist_outcome(scenario_root, outcome)

    with pytest.raises(CampaignEvidenceError):
        _validate(options, unit, root)


def test_synthetic_tamper_baseline_passes(tmp_path: Path) -> None:
    options, unit, root, _scenario_root, _task_root = _passing_case(tmp_path)
    _validate(options, unit, root)


@pytest.mark.parametrize(
    "tamper",
    (
        "plan_missing",
        "plan_rewritten",
        "receipt_plan_path",
        "receipt_plan_sha256",
        "plan_cross_scenario",
        "oracle_plan_sha256",
    ),
)
def test_success_rejects_business_oracle_plan_or_binding_tamper(
    tmp_path: Path,
    tamper: str,
) -> None:
    options, unit, root, scenario_root, task_root = _passing_case(tmp_path)
    plan_path = scenario_root / "evidence" / "business-oracle-plan.json"
    receipt_path = task_root / campaign.HEAVY_V3_PROMPT_MATERIALIZATION_FILE
    task_result_path = task_root / "task-result.json"
    outcome_path = scenario_root / "outcome.json"

    if tamper == "plan_missing":
        plan_path.unlink()
    elif tamper in {"plan_rewritten", "plan_cross_scenario"}:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if tamper == "plan_rewritten":
            plan["assertion_ids"] = ["common.tampered-after-codex"]
        else:
            plan["scenario_id"] = "CROSS-SCENARIO"
        matrix.write_text(
            plan_path,
            json.dumps(
                plan,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )
        if tamper == "plan_cross_scenario":
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["business_oracle_plan_sha256"] = hashlib.sha256(
                plan_path.read_bytes()
            ).hexdigest()
            matrix.write_json(receipt_path, receipt)
            task_result = json.loads(task_result_path.read_text(encoding="utf-8"))
            task_result["prompt_materialization_sha256"] = hashlib.sha256(
                receipt_path.read_bytes()
            ).hexdigest()
            matrix.write_json(task_result_path, task_result)
    elif tamper in {"receipt_plan_path", "receipt_plan_sha256"}:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if tamper == "receipt_plan_path":
            receipt["business_oracle_plan_path"] = "/tmp/cross-bound-plan.json"
        else:
            receipt["business_oracle_plan_sha256"] = "0" * 64
        matrix.write_json(receipt_path, receipt)
        task_result = json.loads(task_result_path.read_text(encoding="utf-8"))
        task_result["prompt_materialization_sha256"] = hashlib.sha256(
            receipt_path.read_bytes()
        ).hexdigest()
        matrix.write_json(task_result_path, task_result)
    elif tamper == "oracle_plan_sha256":
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        outcome["checks"]["business_verification"][
            "business_oracle_plan_sha256"
        ] = "0" * 64
        _persist_outcome(scenario_root, outcome)
    else:  # pragma: no cover - parameter list is closed
        raise AssertionError(tamper)

    with pytest.raises(CampaignEvidenceError):
        _validate(options, unit, root)


@pytest.mark.parametrize("status", ("FAIL", "BLOCKED", "INDETERMINATE"))
@pytest.mark.parametrize(
    "tamper",
    ("provenance_missing", "plan_missing", "typed_plan_consistently_rehashed"),
)
def test_nonpassing_case_rejects_prompt_or_business_plan_tamper(
    tmp_path: Path,
    status: str,
    tamper: str,
) -> None:
    options, unit, root, scenario_root, task_root = _nonpassing_case(
        tmp_path,
        status=status,
    )
    evidence_root = scenario_root / "evidence"
    plan_path = evidence_root / "business-oracle-plan.json"
    if tamper == "provenance_missing":
        (evidence_root / campaign.HEAVY_V3_PROMPT_PROVENANCE_FILE).unlink()
    elif tamper == "plan_missing":
        plan_path.unlink()
    else:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["static_expectation"]["scenario_id"] = "CROSS-SCENARIO"
        plan["fixture_spec"]["sha256"] = campaign._canonical_sha256(
            {
                "static": plan["static_expectation"],
                "live": plan["live_binding"],
            }
        )
        matrix.write_json(plan_path, plan)
        receipt_path = task_root / campaign.HEAVY_V3_PROMPT_MATERIALIZATION_FILE
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["business_oracle_plan_sha256"] = hashlib.sha256(
            plan_path.read_bytes()
        ).hexdigest()
        matrix.write_json(receipt_path, receipt)

    with pytest.raises(CampaignEvidenceError, match="prompt provenance|business-oracle|typed"):
        _validate_nonpassing(options, unit, root)


@pytest.mark.parametrize(
    ("status", "observed"),
    (("FAIL", "FAIL"), ("BLOCKED", "BLOCKED"), ("INDETERMINATE", "BLOCKED")),
)
def test_nonpassing_case_accepts_one_intact_frozen_plan(
    tmp_path: Path,
    status: str,
    observed: str,
) -> None:
    options, unit, root, _scenario_root, _task_root = _nonpassing_case(
        tmp_path,
        status=status,
    )

    result = campaign.validate_heavy_v3_child_run(
        root,
        expected_units=(unit,),
        options=options,
        returncode=1,
    )

    assert [row["status"] for row in result.observations] == [observed]


def test_pre_materialization_block_rejects_residual_business_plan(
    tmp_path: Path,
) -> None:
    options = fixture._options(tmp_path)
    unit = fixture._unit(1)
    root = tmp_path / "matrix"
    fixture._write_matrix_evidence(
        root,
        options=options,
        units=(unit,),
        statuses=("BLOCKED",),
        stop_reason=f"blocked:{unit.unit_id}",
        run_errors=(f"[heavy-unit:{unit.unit_id}] BLOCKED: fixture failed",),
    )
    scenario_root = root / "scenarios" / f"001-{unit.unit_id}"
    plan_path = scenario_root / "evidence" / campaign.BUSINESS_ORACLE_PLAN_FILE
    plan_bytes = plan_path.read_bytes()
    fixture._mark_pre_materialization_block(
        root,
        unit=unit,
        sequence=1,
    )
    plan_path.write_bytes(plan_bytes)

    with pytest.raises(
        CampaignEvidenceError,
        match="pre-materialization heavy block contradicts prompt or plan evidence",
    ):
        _validate_nonpassing(options, unit, root)


def _reseal_business_plan_chain(
    scenario_root: Path,
    task_root: Path,
    plan: dict,
) -> None:
    plan_path = scenario_root / "evidence" / "business-oracle-plan.json"
    matrix.write_text(
        plan_path,
        json.dumps(
            plan,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    receipt_path = task_root / campaign.HEAVY_V3_PROMPT_MATERIALIZATION_FILE
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["business_oracle_plan_sha256"] = plan_sha256
    matrix.write_json(receipt_path, receipt)
    task_result_path = task_root / "task-result.json"
    task_result = json.loads(task_result_path.read_text(encoding="utf-8"))
    task_result["prompt_materialization_sha256"] = hashlib.sha256(
        receipt_path.read_bytes()
    ).hexdigest()
    matrix.write_json(task_result_path, task_result)
    outcome = json.loads(
        (scenario_root / "outcome.json").read_text(encoding="utf-8")
    )
    outcome["checks"]["business_verification"][
        "business_oracle_plan_sha256"
    ] = plan_sha256
    fixture._persist_runner_outcome(scenario_root, outcome)


def test_success_rejects_consistently_rehashed_typed_object_fixture(
    tmp_path: Path,
) -> None:
    options, unit, root, scenario_root, task_root = _passing_case(tmp_path)
    plan_path = scenario_root / "evidence" / "business-oracle-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    before = plan["live_binding"]["before_snapshot"]
    before["objects"][0]["name"] = "CrossBoundFixtureName"
    before_payload = {
        "objects": before["objects"],
        "absent_paths": before["absent_paths"],
        "sibling_prefix_rows": before["sibling_prefix_rows"],
    }
    before["digest"] = campaign._canonical_sha256(before_payload)
    plan["live_binding"]["before_snapshot_sha256"] = before["digest"]
    plan["live_binding"]["key_bindings"] = before["objects"]
    plan["delta_rules"][0]["before_snapshot_sha256"] = before["digest"]
    plan["fixture_spec"]["sha256"] = campaign._canonical_sha256(
        {
            "static": plan["static_expectation"],
            "live": plan["live_binding"],
        }
    )
    _reseal_business_plan_chain(scenario_root, task_root, plan)

    with pytest.raises(CampaignEvidenceError, match="typed|before|name"):
        _validate(options, unit, root)


def test_success_rejects_cross_scenario_typed_sections_with_resealed_chain(
    tmp_path: Path,
) -> None:
    target_root = tmp_path / "target"
    other_root = tmp_path / "other"
    target_root.mkdir()
    other_root.mkdir()
    options, unit, root, scenario_root, task_root = _passing_case(target_root)
    _other_options, _other_unit, _other_root, other_scenario_root, _other_task = (
        _passing_case(other_root, unit=fixture._unit(2))
    )
    plan_path = scenario_root / "evidence" / "business-oracle-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    other = json.loads(
        (other_scenario_root / "evidence" / "business-oracle-plan.json").read_text(
            encoding="utf-8"
        )
    )
    for key in (
        "fixture_spec",
        "payload_bindings",
        "assertion_ids",
        "static_expectation",
        "live_binding",
        "delta_rules",
    ):
        plan[key] = copy.deepcopy(other[key])
    _reseal_business_plan_chain(scenario_root, task_root, plan)

    with pytest.raises(
        CampaignEvidenceError,
        match="identity|misbound|static expectation",
    ):
        _validate(options, unit, root)


def _direct_typed_archive(
    unit: Any,
    root: Path,
) -> tuple[Any, Any]:
    root.mkdir(parents=True)
    (root / "owned").mkdir()
    protocol, sections = fixture._synthetic_protocol_and_typed_sections(
        unit,
        scenario_root=root,
        visible_values={},
    )
    provenance = fixture._direct_typed_provenance(
        unit.scenario,
        version=unit.version,
        scenario_root=root,
        protocol=protocol,
        visible_values={},
    )
    return sections, provenance


def test_soundbank_typed_archive_rejects_consistent_rehash(
    tmp_path: Path,
) -> None:
    unit = fixture._soundbank_unit(
        "O22-SB-CONVERT-EXT-01",
        "ak.wwise.core.soundbank.convertExternalSources",
        primary_count=1,
    )
    sections, provenance = _direct_typed_archive(unit, tmp_path / "soundbank")
    forged = copy.deepcopy(sections.writer_kwargs())
    forged["static_expectation"]["scenario_fixture_sha256"] = "f" * 64
    forged["fixture_spec"]["sha256"] = campaign._canonical_sha256(
        {
            "static": forged["static_expectation"],
            "live": forged["live_binding"],
        }
    )

    with pytest.raises(campaign.SoundBankBusinessPlanError, match="SoundBank|identity"):
        campaign._validate_heavy_v3_typed_business_plan(
            forged,
            expected_unit=unit,
            provenance=provenance,
        )


def test_soundbank_typed_archive_rejects_cross_scenario_bind(
    tmp_path: Path,
) -> None:
    target = fixture._soundbank_unit(
        "O22-SB-CONVERT-EXT-01",
        "ak.wwise.core.soundbank.convertExternalSources",
        primary_count=1,
    )
    other = fixture._soundbank_unit(
        "O22-SB-CONVERT-EXT-02",
        "ak.wwise.core.soundbank.convertExternalSources",
        primary_count=1,
    )
    _target_sections, provenance = _direct_typed_archive(
        target, tmp_path / "target"
    )
    other_sections, _other_provenance = _direct_typed_archive(
        other, tmp_path / "other"
    )

    with pytest.raises(campaign.SoundBankBusinessPlanError, match="SoundBank|identity"):
        campaign._validate_heavy_v3_typed_business_plan(
            other_sections.writer_kwargs(),
            expected_unit=target,
            provenance=provenance,
        )


def test_soundbank_typed_archive_io_root_is_bound_to_scenario_owned_root(
    tmp_path: Path,
) -> None:
    unit = fixture._soundbank_unit(
        "O22-SB-SET-INCLUSIONS-01",
        "ak.wwise.core.soundbank.setInclusions",
        primary_count=1,
    )
    sections, provenance = _direct_typed_archive(unit, tmp_path / "soundbank")
    forged = copy.deepcopy(sections.writer_kwargs())
    old_root = Path(forged["static_expectation"]["io_root"])
    new_root = (tmp_path / "relocated-owned").resolve(strict=False)
    forged["static_expectation"]["io_root"] = str(new_root)
    relocated_artifacts = []
    for artifact in forged["static_expectation"]["expected_artifacts"]:
        relocated = copy.deepcopy(artifact)
        relative = Path(relocated["path"]).resolve(strict=False).relative_to(
            old_root
        )
        relocated["path"] = str(new_root / relative)
        relocated_artifacts.append(relocated)
    forged["static_expectation"]["expected_artifacts"] = relocated_artifacts
    forged["delta_rules"][0]["expected_artifacts"] = copy.deepcopy(
        relocated_artifacts
    )
    forged["fixture_spec"]["sha256"] = campaign._canonical_sha256(
        {
            "static": forged["static_expectation"],
            "live": forged["live_binding"],
        }
    )

    with pytest.raises(CampaignEvidenceError, match="scenario-owned authority"):
        campaign._validate_heavy_v3_typed_business_plan(
            forged,
            expected_unit=unit,
            provenance=provenance,
        )


def test_cli_typed_archive_rejects_consistent_rehash(tmp_path: Path) -> None:
    unit = fixture._cli_api_unit("ak.wwise.cli.convertExternalSource", 1)
    sections, provenance = _direct_typed_archive(unit, tmp_path / "cli")
    forged = copy.deepcopy(sections.writer_kwargs())
    forged["static_expectation"]["asset_spec"]["operation"] = "migrate"
    forged["static_expectation"]["asset_spec_sha256"] = (
        campaign._canonical_sha256(forged["static_expectation"]["asset_spec"])
    )
    forged["fixture_spec"]["sha256"] = campaign._canonical_sha256(
        {
            "static": forged["static_expectation"],
            "live": forged["live_binding"],
        }
    )

    with pytest.raises(campaign.CliBusinessPlanError, match="CLI|asset"):
        campaign._validate_heavy_v3_typed_business_plan(
            forged,
            expected_unit=unit,
            provenance=provenance,
        )


def test_cli_typed_archive_rejects_scalar_output_substitution_with_rehash(
    tmp_path: Path,
) -> None:
    unit = fixture._cli_api_unit("ak.wwise.cli.convertExternalSource", 1)
    sections, provenance = _direct_typed_archive(unit, tmp_path / "cli")
    forged = copy.deepcopy(sections.writer_kwargs())
    request = forged["static_expectation"]["operation_request"]
    output_pair = request["arguments"]["args"]["output"]
    assert output_pair[0] == "Windows"
    request["arguments"]["args"]["output"] = output_pair[1]
    forged["static_expectation"]["operation_request_sha256"] = (
        campaign._canonical_sha256(request)
    )
    forged["fixture_spec"]["sha256"] = campaign._canonical_sha256(
        {
            "static": forged["static_expectation"],
            "live": forged["live_binding"],
        }
    )

    with pytest.raises(campaign.CliBusinessPlanError, match="protocol topology"):
        campaign._validate_heavy_v3_typed_business_plan(
            forged,
            expected_unit=unit,
            provenance=provenance,
        )


def test_cli_typed_archive_rejects_cross_scenario_bind(tmp_path: Path) -> None:
    target = fixture._cli_api_unit("ak.wwise.cli.convertExternalSource", 1)
    other = fixture._cli_api_unit("ak.wwise.cli.convertExternalSource", 2)
    _target_sections, provenance = _direct_typed_archive(
        target, tmp_path / "target"
    )
    other_sections, _other_provenance = _direct_typed_archive(
        other, tmp_path / "other"
    )

    with pytest.raises(campaign.CliBusinessPlanError, match="CLI|identity"):
        campaign._validate_heavy_v3_typed_business_plan(
            other_sections.writer_kwargs(),
            expected_unit=target,
            provenance=provenance,
        )


def test_success_recomputes_common_gates_from_real_command_facts(tmp_path: Path) -> None:
    options, unit, root, scenario_root, task_root = _passing_case(tmp_path)
    turn_root = task_root / "turns" / "turn-01"
    event_rows = [
        json.loads(line)
        for line in (turn_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    event_rows = [
        row
        for row in event_rows
        if not (
            isinstance(row.get("item"), Mapping)
            and row["item"].get("id") == "read-2"
        )
    ]
    events = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in event_rows
    )
    matrix.write_text(turn_root / "events.jsonl", events)
    protocol = fixture._synthetic_protocol(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    facts = fixture._synthetic_codex_facts(
        options=options,
        task_root=task_root,
        turn_root=turn_root,
        turn_index=1,
        prompt=unit.turns[0].prompt,
        thread_id="thread-1",
        events_text=events,
        protocol=protocol,
        version=unit.version,
    )
    matrix.write_json(turn_root / "codex-facts.json", facts)

    with pytest.raises(CampaignEvidenceError, match="common gates"):
        _validate(options, unit, root)


def test_audio_oracle_requires_execute_and_verify_bound_protocol(tmp_path: Path) -> None:
    """A preview-only protocol cannot attest a completed audio conversion."""

    unit = fixture._visible_preview_only_request_unit(1)
    options, unit, root, _scenario_root, _task_root = _passing_case(
        tmp_path,
        unit=unit,
    )
    with pytest.raises(CampaignEvidenceError, match="protocol drifted"):
        _validate(options, unit, root)


def test_object_get_recomputes_identity_presence_from_final_text(tmp_path: Path) -> None:
    options, unit, root, scenario_root, task_root = _passing_case(tmp_path)
    turn_root = task_root / "turns" / "turn-01"
    skill_install = workspace_skill_install_path(task_root / "agent-workspace")
    task_result = json.loads((task_root / "task-result.json").read_text(encoding="utf-8"))
    records = task_result["broker"]["records"]
    response = "waapi-skill 已加载。"
    events = fixture._synthetic_events(
        thread_id="thread-1",
        records=records,
        final_response=response,
        read_paths=fixture._synthetic_first_turn_reads(
            options,
            unit,
            skill_source=fixture._synthetic_runtime_skill_read_source(
                options,
                skill_install,
            ),
        ),
        windows_skill_read_source=(
            skill_install
            if options.windows_powershell_core_host is not None
            else None
        ),
        windows_powershell_core_host=options.windows_powershell_core_host,
    )
    matrix.write_text(turn_root / "events.jsonl", events)
    matrix.write_text(turn_root / "final.txt", response + "\n")
    protocol = fixture._synthetic_protocol(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    facts = fixture._synthetic_codex_facts(
        options=options,
        task_root=task_root,
        turn_root=turn_root,
        turn_index=1,
        prompt=unit.turns[0].prompt,
        thread_id="thread-1",
        events_text=events,
        protocol=protocol,
        version=unit.version,
    )
    matrix.write_json(turn_root / "codex-facts.json", facts)
    outcome = json.loads((scenario_root / "outcome.json").read_text(encoding="utf-8"))
    proof = outcome["checks"]["business_verification"]["verification"]["evidence"]
    proof["final_response_sha256"] = fixture.hashlib.sha256(
        response.encode("utf-8")
    ).hexdigest()
    fixture._persist_runner_outcome(scenario_root, outcome)

    with pytest.raises(CampaignEvidenceError, match="identity token"):
        _validate(options, unit, root)


def test_get02_campaign_rechecks_paired_path_boundaries_from_final_text(
    tmp_path: Path,
) -> None:
    unit = fixture._unit(2)
    options, unit, root, scenario_root, task_root = _passing_case(
        tmp_path,
        unit=unit,
    )
    _validate(options, unit, root)
    turn_root = task_root / "turns" / "turn-01"
    skill_install = workspace_skill_install_path(task_root / "agent-workspace")
    original = (turn_root / "final.txt").read_text(encoding="utf-8").rstrip("\n")
    outcome = json.loads((scenario_root / "outcome.json").read_text(encoding="utf-8"))
    proof = outcome["checks"]["business_verification"]["verification"]["evidence"]
    parent_path = proof["paired_rows"][0]["parent_path"]
    response = original.replace(f"`{parent_path}` | ", "", 1)
    assert response != original
    task_result = json.loads((task_root / "task-result.json").read_text(encoding="utf-8"))
    records = task_result["broker"]["records"]
    events = fixture._synthetic_events(
        thread_id="thread-1",
        records=records,
        final_response=response,
        read_paths=fixture._synthetic_first_turn_reads(
            options,
            unit,
            skill_source=fixture._synthetic_runtime_skill_read_source(
                options,
                skill_install,
            ),
        ),
        windows_skill_read_source=(
            skill_install
            if options.windows_powershell_core_host is not None
            else None
        ),
        windows_powershell_core_host=options.windows_powershell_core_host,
    )
    matrix.write_text(turn_root / "events.jsonl", events)
    matrix.write_text(turn_root / "final.txt", response + "\n")
    protocol = fixture._synthetic_protocol(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    facts = fixture._synthetic_codex_facts(
        options=options,
        task_root=task_root,
        turn_root=turn_root,
        turn_index=1,
        prompt=unit.turns[0].prompt,
        thread_id="thread-1",
        events_text=events,
        protocol=protocol,
        version=unit.version,
    )
    matrix.write_json(turn_root / "codex-facts.json", facts)
    proof["final_response_sha256"] = hashlib.sha256(
        response.encode("utf-8")
    ).hexdigest()
    fixture._persist_runner_outcome(scenario_root, outcome)

    with pytest.raises(CampaignEvidenceError, match="standalone path|paired path"):
        _validate(options, unit, root)


def test_get02_campaign_recomputes_unexpected_language_from_final_text(
    tmp_path: Path,
) -> None:
    unit = fixture._unit(2)
    options, unit, root, scenario_root, task_root = _passing_case(
        tmp_path,
        unit=unit,
    )
    _validate(options, unit, root)
    turn_root = task_root / "turns" / "turn-01"
    skill_install = workspace_skill_install_path(task_root / "agent-workspace")
    original = (turn_root / "final.txt").read_text(encoding="utf-8").rstrip("\n")
    outcome = json.loads((scenario_root / "outcome.json").read_text(encoding="utf-8"))
    proof = outcome["checks"]["business_verification"]["verification"]["evidence"]
    first_pair = proof["paired_rows"][0]
    expected_language = first_pair["language"]
    other_language = next(
        row["language"]
        for row in proof["paired_rows"]
        if row["language"] != expected_language
    )
    response = original.replace(
        f"| {expected_language} |",
        f"| {expected_language} / {other_language} |",
        1,
    )
    assert response != original
    task_result = json.loads((task_root / "task-result.json").read_text(encoding="utf-8"))
    records = task_result["broker"]["records"]
    events = fixture._synthetic_events(
        thread_id="thread-1",
        records=records,
        final_response=response,
        read_paths=fixture._synthetic_first_turn_reads(
            options,
            unit,
            skill_source=fixture._synthetic_runtime_skill_read_source(
                options,
                skill_install,
            ),
        ),
        windows_skill_read_source=(
            skill_install
            if options.windows_powershell_core_host is not None
            else None
        ),
        windows_powershell_core_host=options.windows_powershell_core_host,
    )
    matrix.write_text(turn_root / "events.jsonl", events)
    matrix.write_text(turn_root / "final.txt", response + "\n")
    protocol = fixture._synthetic_protocol(
        unit,
        scenario_root=scenario_root,
        visible_values={},
    )
    facts = fixture._synthetic_codex_facts(
        options=options,
        task_root=task_root,
        turn_root=turn_root,
        turn_index=1,
        prompt=unit.turns[0].prompt,
        thread_id="thread-1",
        events_text=events,
        protocol=protocol,
        version=unit.version,
    )
    matrix.write_json(turn_root / "codex-facts.json", facts)
    proof["final_response_sha256"] = hashlib.sha256(
        response.encode("utf-8")
    ).hexdigest()
    fixture._persist_runner_outcome(scenario_root, outcome)

    with pytest.raises(CampaignEvidenceError, match="paired path proof"):
        _validate(options, unit, root)


def test_get02_campaign_rejects_derived_source_evidence_tamper(
    tmp_path: Path,
) -> None:
    unit = fixture._unit(2)
    options, unit, root, scenario_root, _task_root = _passing_case(
        tmp_path,
        unit=unit,
    )
    outcome = json.loads((scenario_root / "outcome.json").read_text(encoding="utf-8"))
    proof = outcome["checks"]["business_verification"]["verification"]["evidence"]
    assert len(proof["derived_rows"]) == 8
    proof["derived_rows"][0]["id"] = "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}"
    fixture._persist_runner_outcome(scenario_root, outcome)

    with pytest.raises(CampaignEvidenceError, match="typed plan/evidence"):
        _validate(options, unit, root)


def test_object_mutation_rejects_before_equals_after_even_with_resolved_rows(
    tmp_path: Path,
) -> None:
    unit = fixture._multi_turn_unit(1)
    options, unit, root, scenario_root, _task_root = _passing_case(
        tmp_path,
        unit=unit,
    )
    outcome = json.loads((scenario_root / "outcome.json").read_text(encoding="utf-8"))
    proof = outcome["checks"]["business_verification"]["verification"]["evidence"]
    proof["before"] = copy.deepcopy(proof["after"])
    fixture._persist_runner_outcome(scenario_root, outcome)

    with pytest.raises(CampaignEvidenceError, match="before snapshot"):
        _validate(options, unit, root)
