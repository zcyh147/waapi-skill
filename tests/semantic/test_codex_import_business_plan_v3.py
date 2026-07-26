from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
from tests.semantic.support.codex_eval_protocol_v3 import StructuredRefusal, build_transaction_protocol
from tests.semantic.support.codex_import_assets_v3 import materialize_import_case
from tests.semantic.support.codex_import_business_plan_v3 import (
    ImportBusinessPlanError,
    compile_import_business_plan,
    _hash,
    _rules,
    parse_import_business_plan_sections,
    validate_import_archived_verification,
    validate_import_business_plan,
    validate_import_business_plan_archive,
)
from tests.semantic.support.codex_import_runtime_v3 import (
    FileProof,
    ImportAudioSourceState,
    ImportEventState,
    ImportObjectState,
    ImportRowState,
    ImportRuntimeSnapshot,
    build_import_runtime_plan,
)


ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"
IMPORT_APIS = {"ak.wwise.core.audio.import", "ak.wwise.core.audio.importTabDelimited"}


def _guid(number: int) -> str:
    return f"{{00000000-0000-0000-0000-{number:012X}}}"


def _case(tmp_path: Path, scenario_id: str):
    scenario = load_eval_bundle_v3(SUITE).scenario(scenario_id)
    project = tmp_path / "sandbox" / "SampleProject.wproj"
    project.parent.mkdir(parents=True)
    project.write_text("<WwiseDocument/>", encoding="utf-8")
    materialized = materialize_import_case(scenario, version="2022.1", asset_root=tmp_path / "assets")
    plan = build_import_runtime_plan(scenario, materialized, sandbox_project=project)
    before = _snapshot(plan, before=True)
    refusal = StructuredRefusal("INPUT_FILE_NOT_FOUND") if plan.expected_primary_dispatch_count == 0 else None
    protocol = build_transaction_protocol(plan.operation_requests, refusal=refusal)
    return scenario, materialized, plan, before, protocol


def _snapshot(plan, *, before: bool) -> ImportRuntimeSnapshot:
    rows = []
    originals: dict[str, FileProof] = {}
    target_numbers: dict[str, int] = {}
    for index, row in enumerate(plan.rows, start=1):
        exists = row.pre_state_existence == "existing" if before else row.guid_policy != "remain_absent_no_guid"
        if not exists:
            obj = None
        else:
            target_number = target_numbers.setdefault(row.target_path.casefold(), index)
            object_id = _guid(target_number if before or row.guid_policy != "replace_with_distinct_guid" else target_number + 1000)
            source = row.pre_state_file if before else row.source_file
            requested_parent = Path(row.originals_subfolder or "Imported")
            relative_parent = (
                Path("SFX") / requested_parent
                if row.language.casefold() == "sfx"
                else requested_parent
            )
            relative = relative_parent / source.path.name
            copied = plan.sandbox_root / "Originals" / relative
            proof = FileProof(
                str(copied),
                (Path("Originals") / relative).as_posix(),
                source.size or 0,
                source.sha256 or "0" * 64,
            )
            originals[str(copied)] = proof
            obj = ImportObjectState(
                id=object_id, name=row.target_path.rsplit("\\", 1)[1], type=row.object_type,
                path=row.target_path, parent_id=_guid(9000 + index),
                notes=row.pre_state_notes if before else row.notes,
                audio_source=ImportAudioSourceState(
                    _guid(2000 + index),
                    row.language,
                    row.audio_source_notes,
                    proof,
                    relative.as_posix(),
                ),
            )
        rows.append(ImportRowState(row.row_key, row.target_path, row.language, obj))
    events = []
    if not before:
        by_key = {item.row_key: item for item in rows}
        for row in plan.rows:
            if row.event_path is not None:
                target = by_key[row.row_key].object
                events.append(ImportEventState(row.event_path, _guid(5000), _guid(6000), 1, target.id if target else None, 1))
    inputs = []
    for item in (*plan.rows[0:0],):  # keep the generated snapshot free of accidental runtime aliases
        del item
    # Runtime snapshot persists the three materialized file categories as one tuple.
    for item in (*plan.operation_requests[0:0],):
        del item
    # The exact input tuple is supplied by the compiler from its materialized case;
    # use a stable empty pre/post value here to exercise equality binding.
    return ImportRuntimeSnapshot(
        plan.scenario_id,
        tuple(rows),
        tuple(events),
        (),
        tuple(sorted(originals.values(), key=lambda item: item.path)),
        tuple(),
        (),
    )


def _verification(sections, *, after: dict[str, Any], phase: str = "after_execution", error_code: str | None = None) -> dict[str, Any]:
    evidence = {"scenario_id": sections.static_expectation["scenario_id"], "phase": phase, "passed": True, "failures": [], "before": sections.live_binding["before_snapshot"], "after": after}
    if error_code is not None:
        evidence["error_code"] = error_code
    return evidence


def _after_value(plan) -> dict[str, Any]:
    return _plain(_snapshot(plan, before=False))


def _plain(value: Any) -> Any:
    from tests.semantic.support.codex_import_business_plan_v3 import _plain as impl
    return impl(value)


def test_plain_set_serialization_is_canonical() -> None:
    assert _plain(frozenset({"z", "a", "m"})) == ["a", "m", "z"]


def test_all_ten_real_scenarios_compile_recompute_and_archive(tmp_path: Path) -> None:
    scenarios = [item for item in load_eval_bundle_v3(SUITE).scenarios if item.api in IMPORT_APIS]
    assert [item.id for item in scenarios] == [
        "O22-AUDIO-IMPORT-01", "O22-AUDIO-IMPORT-02", "O22-AUDIO-IMPORT-03", "O22-AUDIO-IMPORT-04", "O22-AUDIO-IMPORT-05",
        "O22-AUDIO-TAB-01", "O22-AUDIO-TAB-02", "O22-AUDIO-TAB-03", "O22-AUDIO-TAB-04", "O22-AUDIO-TAB-05",
    ]
    for scenario in scenarios:
        root = tmp_path / scenario.id
        root.mkdir()
        current, materialized, plan, before, protocol = _case(root, scenario.id)
        sections = compile_import_business_plan(current, materialized, plan, before, protocol)
        validate_import_business_plan(sections, current, materialized, plan, before, protocol, verify_files=True)
        parsed = parse_import_business_plan_sections(sections.writer_kwargs())
        validate_import_business_plan_archive(parsed, scenario=current, protocol=protocol, verify_files=True)
        assert len(sections.payload_bindings["primary_steps"]) == current.primary_dispatch.count
        if current.primary_dispatch.count == 0:
            assert sections.payload_bindings["primary_steps"] == []
            assert all(step.startswith("tx01.") for step in sections.payload_bindings["verification_steps"])
        else:
            assert [request["operation"] for request in sections.static_expectation["operation_requests"]] == [
                "audio.import" if current.api.endswith(".import") else "audio.importTabDelimited"
            ] * len(materialized.operation_requests)


def test_archived_verification_enforces_guid_event_and_zero_dispatch_rules(tmp_path: Path) -> None:
    scenario, materialized, plan, before, protocol = _case(tmp_path / "normal", "O22-AUDIO-IMPORT-03")
    sections = compile_import_business_plan(scenario, materialized, plan, before, protocol)
    after = _after_value(plan)
    validate_import_archived_verification(sections, _verification(sections, after=after))
    validate_import_archived_verification(sections, {"contract": "waapi-skill.heavy-oracle/v2", "verification": _verification(sections, after=after)})
    wrong_guid = _plain(after)
    replaced = next(row for row in wrong_guid["rows"] if row["object"] is not None)
    replaced["object"]["id"] = "{wrong-guid}"
    with pytest.raises(ImportBusinessPlanError, match="GUID|event"):
        validate_import_archived_verification(sections, _verification(sections, after=wrong_guid))

    refusal, materialized, plan, before, protocol = _case(tmp_path / "refusal", "O22-AUDIO-TAB-01")
    zero = compile_import_business_plan(refusal, materialized, plan, before, protocol)
    raw_refusal = _verification(zero, after=zero.live_binding["before_snapshot"], phase="zero_dispatch")
    with pytest.raises(ImportBusinessPlanError, match="error"):
        validate_import_archived_verification(zero, raw_refusal)
    validate_import_archived_verification(zero, {"contract": "waapi-skill.heavy-oracle/v2", "refusal_error_code": "INPUT_FILE_NOT_FOUND", "verification": raw_refusal})
    validate_import_archived_verification(zero, raw_refusal, refusal_error_code="INPUT_FILE_NOT_FOUND")
    mutated = _plain(zero.live_binding["before_snapshot"]); mutated["events"] = [{"bad": True}]
    with pytest.raises(ImportBusinessPlanError, match="before equals after"):
        validate_import_archived_verification(zero, _verification(zero, after=mutated, phase="zero_dispatch", error_code="INPUT_FILE_NOT_FOUND"))


def test_archived_verification_binds_derived_originals_path_and_subfolder(
    tmp_path: Path,
) -> None:
    scenario, materialized, plan, before, protocol = _case(
        tmp_path,
        "O22-AUDIO-IMPORT-01",
    )
    sections = compile_import_business_plan(
        scenario,
        materialized,
        plan,
        before,
        protocol,
    )
    after = _after_value(plan)
    validate_import_archived_verification(
        sections,
        _verification(sections, after=after),
    )

    wrong_subfolder = _plain(after)
    row_plan = next(
        row for row in plan.rows if row.originals_subfolder is not None
    )
    source = next(
        row["object"]["audio_source"]
        for row in wrong_subfolder["rows"]
        if row.get("row_key") == row_plan.row_key
        and isinstance(row.get("object"), dict)
    )
    old_proof = dict(source["original_file"])
    filename = Path(source["original_relative_path"]).name
    source["original_relative_path"] = f"Wrong/Subfolder/{filename}"
    source["original_file"]["relative_path"] = (
        f"Originals/Wrong/Subfolder/{filename}"
    )
    source["original_file"]["path"] = str(
        plan.sandbox_root / "Originals" / "Wrong" / "Subfolder" / filename
    )
    tree_proof = next(
        item
        for item in wrong_subfolder["originals_files"]
        if item["path"] == old_proof["path"]
    )
    tree_proof.update(source["original_file"])
    with pytest.raises(ImportBusinessPlanError, match="subfolder"):
        validate_import_archived_verification(
            sections,
            _verification(sections, after=wrong_subfolder),
        )

    escaped = _plain(after)
    escaped_source = next(
        row["object"]["audio_source"]
        for row in escaped["rows"]
        if isinstance(row.get("object"), dict)
    )
    escaped_source["original_relative_path"] = "../escape.wav"
    with pytest.raises(ImportBusinessPlanError, match="canonical"):
        validate_import_archived_verification(
            sections,
            _verification(sections, after=escaped),
        )

    legacy = _plain(after)
    legacy_source = next(
        row["object"]["audio_source"]
        for row in legacy["rows"]
        if isinstance(row.get("object"), dict)
    )
    legacy_source["originalRelativeFilePath"] = legacy_source[
        "original_relative_path"
    ]
    with pytest.raises(ImportBusinessPlanError, match="Audio Source evidence"):
        validate_import_archived_verification(
            sections,
            _verification(sections, after=legacy),
        )


@pytest.mark.parametrize(
    "scenario_id",
    ("O22-AUDIO-IMPORT-01", "O22-AUDIO-IMPORT-02"),
)
def test_archived_verification_accepts_only_closed_sound_type_aliases(
    tmp_path: Path,
    scenario_id: str,
) -> None:
    scenario, materialized, plan, before, protocol = _case(
        tmp_path,
        scenario_id,
    )
    sections = compile_import_business_plan(
        scenario,
        materialized,
        plan,
        before,
        protocol,
    )
    after = _after_value(plan)
    semantic_types = {
        row["object"]["type"]
        for row in after["rows"]
        if isinstance(row.get("object"), dict)
    }
    assert semantic_types in ({"Sound Voice"}, {"Sound SFX"})
    for row in after["rows"]:
        if isinstance(row.get("object"), dict):
            row["object"]["type"] = "Sound"

    validate_import_archived_verification(
        sections,
        _verification(sections, after=after),
    )

    unrelated = _plain(after)
    target = next(
        row["object"]
        for row in unrelated["rows"]
        if isinstance(row.get("object"), dict)
    )
    target["type"] = "RandomSequenceContainer"
    with pytest.raises(ImportBusinessPlanError, match="target/type"):
        validate_import_archived_verification(
            sections,
            _verification(sections, after=unrelated),
        )


def test_localized_rows_must_share_one_target_guid(tmp_path: Path) -> None:
    scenario, materialized, plan, before, protocol = _case(tmp_path, "O22-AUDIO-TAB-02")
    sections = compile_import_business_plan(scenario, materialized, plan, before, protocol)
    after = _after_value(plan)
    by_path: dict[str, str] = {}
    for row in after["rows"]:
        if row["object"] is not None:
            row["object"]["id"] = by_path.setdefault(row["target_path"], row["object"]["id"])
    validate_import_archived_verification(sections, _verification(sections, after=after))
    duplicate = _plain(after)
    create_path = next(row.target_path for row in plan.rows if row.guid_policy == "create_once_then_preserve_shared_guid")
    same_target = [row for row in duplicate["rows"] if row["target_path"] == create_path]
    same_target[1]["object"]["id"] = _guid(999999)
    with pytest.raises(ImportBusinessPlanError, match="localized"):
        validate_import_archived_verification(sections, _verification(sections, after=duplicate))
    malformed = _plain(after)
    next(row for row in malformed["rows"] if row["target_path"] == create_path)["object"]["id"] = "not-a-guid"
    with pytest.raises(ImportBusinessPlanError, match="GUID"):
        validate_import_archived_verification(sections, _verification(sections, after=malformed))
    reused = _plain(after)
    created = [row for row in reused["rows"] if row["target_path"] == create_path]
    other_create_path = next(row.target_path for row in plan.rows if row.guid_policy == "create_once_then_preserve_shared_guid" and row.target_path != create_path)
    other = next(row for row in reused["rows"] if row["target_path"] == other_create_path)
    created[0]["object"]["id"] = other["object"]["id"]
    for row in created[1:]: row["object"]["id"] = other["object"]["id"]
    with pytest.raises(ImportBusinessPlanError, match="distinct"):
        validate_import_archived_verification(sections, _verification(sections, after=reused))


@pytest.mark.parametrize("attack", ["request", "row", "language", "hash", "guid", "guid_policy", "order", "partial", "cross_api", "assertions", "archive"])
def test_closed_plan_rejects_import_attack_variants(tmp_path: Path, attack: str) -> None:
    scenario, materialized, plan, before, protocol = _case(tmp_path, "O22-AUDIO-TAB-02")
    sections = compile_import_business_plan(scenario, materialized, plan, before, protocol)
    if attack == "request":
        bad = {**sections.static_expectation, "operation_requests_sha256": "0" * 64}
        candidate = replace(sections, static_expectation=MappingProxyType(bad))
        with pytest.raises(ImportBusinessPlanError): validate_import_business_plan_archive(candidate, scenario=scenario, protocol=protocol)
    elif attack == "row":
        bad = _plain(sections.static_expectation); bad["row_contracts"][0]["target_path"] += "_wrong"
        live = _plain(sections.live_binding)
        candidate = replace(sections, static_expectation=MappingProxyType(bad), delta_rules=tuple(MappingProxyType(rule) for rule in _rules(bad, live)), fixture_spec=MappingProxyType({"kind": "import_materialized_runtime_v1", "sha256": _hash({"static": bad, "live": live})}))
        with pytest.raises(ImportBusinessPlanError, match="fixture/request truth"): validate_import_business_plan_archive(candidate, scenario=scenario, protocol=protocol)
    elif attack == "language":
        bad = _plain(sections.live_binding); bad["before_snapshot"]["rows"][0]["language"] = "Wrong"
        bad["before_snapshot_sha256"] = __import__("hashlib").sha256(__import__("json").dumps(bad["before_snapshot"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with pytest.raises(ImportBusinessPlanError): validate_import_business_plan_archive(replace(sections, live_binding=MappingProxyType(bad)), scenario=scenario, protocol=protocol)
    elif attack == "hash":
        bad = _plain(sections.live_binding); bad["input_files"][0]["sha256"] = "0" * 64
        with pytest.raises(ImportBusinessPlanError): validate_import_business_plan_archive(replace(sections, live_binding=MappingProxyType(bad)), scenario=scenario, protocol=protocol)
    elif attack == "guid":
        after = _after_value(plan); after["rows"][0]["object"]["id"] = _guid(999999)
        with pytest.raises(ImportBusinessPlanError): validate_import_archived_verification(sections, _verification(sections, after=after))
    elif attack == "guid_policy":
        bad = _plain(sections.static_expectation); bad["row_contracts"][0]["guid_policy"] = "replace_with_distinct_guid"
        with pytest.raises(ImportBusinessPlanError): validate_import_business_plan(replace(sections, static_expectation=MappingProxyType(bad)), scenario, materialized, plan, before, protocol)
    elif attack == "order":
        swapped = build_transaction_protocol(tuple(reversed(plan.operation_requests)))
        with pytest.raises(ImportBusinessPlanError): validate_import_business_plan_archive(sections, scenario=scenario, protocol=swapped)
    elif attack == "partial":
        after = _after_value(plan); after["rows"] = after["rows"][:-1]
        with pytest.raises(ImportBusinessPlanError): validate_import_archived_verification(sections, _verification(sections, after=after))
    elif attack == "cross_api":
        other = load_eval_bundle_v3(SUITE).scenario("O22-AUDIO-IMPORT-01")
        with pytest.raises(ImportBusinessPlanError): validate_import_business_plan_archive(sections, scenario=other, protocol=protocol)
    elif attack == "assertions":
        with pytest.raises(ImportBusinessPlanError, match="assertion"):
            validate_import_business_plan_archive(replace(sections, assertion_ids=("import.request.exact",)), scenario=scenario, protocol=protocol)
    else:
        payload = sections.writer_kwargs(); payload["static_expectation"] = {**payload["static_expectation"], "extra": True}
        with pytest.raises(ImportBusinessPlanError): parse_import_business_plan_sections(payload)
