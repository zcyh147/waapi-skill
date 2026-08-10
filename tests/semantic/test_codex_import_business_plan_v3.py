from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any

import pytest

from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
from tests.semantic.support.codex_eval_protocol_v3 import (
    StructuredRefusal,
    build_audio_import_composer_protocol,
    build_metadata_transaction_protocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_gateway_broker import (
    project_required_metadata_tokens,
)
from tests.semantic.support.codex_import_assets_v3 import (
    bound_import_metadata_tokens,
    materialize_import_case,
)
from tests.semantic.support.codex_import_business_plan_v3 import (
    ImportBusinessPlanError,
    _validate_files,
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
from tests.semantic.test_codex_import_runtime_v3 import (
    _compound_prepared,
    _sound_discovery,
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
    protocol = (
        build_audio_import_composer_protocol(plan.operation_requests[0])
        if plan.api == "ak.wwise.core.audio.import"
        else build_transaction_protocol(plan.operation_requests, refusal=refusal)
    )
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


def test_import_file_verification_rejects_a_hard_linked_asset(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF-source")
    (tmp_path / "source-alias.wav").hardlink_to(source)
    files = [
        {
            "category": "wav",
            "key": "source",
            "path": str(source),
            "present": True,
            "size": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
    ]

    with pytest.raises(ImportBusinessPlanError, match="changed after sealing"):
        _validate_files(files, verify_files=True)


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


@pytest.mark.parametrize(
    "unit_id",
    [
        f"CMP{year}-{scenario_id}"
        for year in ("22", "25")
        for scenario_id in (
            "O22-AUDIO-IMPORT-02",
            "O22-AUDIO-IMPORT-03",
            "O22-AUDIO-TAB-03",
            "O22-AUDIO-TAB-04",
        )
    ],
)
def test_compound_import_plans_seal_dynamic_metadata_bus_and_cleanup_evidence(
    tmp_path: Path,
    unit_id: str,
) -> None:
    unit, materialized, backend, fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id=unit_id,
    )
    tokens = bound_import_metadata_tokens(materialized)
    projection = project_required_metadata_tokens(
        _sound_discovery(),
        object_type="Sound",
        required_tokens=tokens,
    )
    protocol = build_metadata_transaction_protocol(
        materialized.operation_requests,
        object_type="Sound",
        metadata_queries=materialized.metadata_queries,
        required_tokens=tokens,
        expected_required_token_projection=projection,
        equivalence=(
            "audio_import_v1"
            if unit.scenario.api == "ak.wwise.core.audio.import"
            else "audio_import_tab_v1"
        ),
    )
    before = runtime.hidden_before
    assert before is not None

    sections = compile_import_business_plan(
        unit.scenario,
        materialized,
        runtime.plan,
        before,
        protocol,
    )
    validate_import_business_plan(
        sections,
        unit.scenario,
        materialized,
        runtime.plan,
        before,
        protocol,
        verify_files=True,
    )
    parsed = parse_import_business_plan_sections(sections.writer_kwargs())
    validate_import_business_plan_archive(
        parsed,
        scenario=unit.scenario,
        protocol=protocol,
        verify_files=True,
    )
    canonical_archive = json.loads(
        json.dumps(
            sections.writer_kwargs(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
    )
    canonical_parsed = parse_import_business_plan_sections(canonical_archive)
    validate_import_business_plan_archive(
        canonical_parsed,
        scenario=unit.scenario,
        protocol=protocol,
        verify_files=True,
    )

    static = sections.static_expectation
    live = sections.live_binding
    assert static["family_schema_version"] == "waapi-skill.import-business-plan/v2"
    assert static["metadata_projection"] == [
        item.as_dict() for item in projection
    ]
    assert static["dynamic_tokens"] == list(tokens)
    assert all(
        bool(row["dynamic_properties"]) == bool(row["dynamic_references"])
        for row in static["row_contracts"]
    )
    modes = [row["dynamic_mode"] for row in static["row_contracts"]]
    if unit.base_scenario_id == "O22-AUDIO-TAB-04":
        assert modes == [
            "preserve",
            "preserve",
            "preserve",
            "mutate",
            "mutate",
            "mutate",
        ]
    else:
        assert modes and set(modes) == {"mutate"}
    assert all(
        bool(row["dynamic_properties"])
        == (row["dynamic_mode"] == "mutate")
        for row in static["row_contracts"]
    )
    assert live["reference_fixtures"]["targets"]
    request_targets = static["metadata_binding"]["reference_targets"]
    oracle_targets = {
        item["key"]: item for item in live["reference_fixtures"]["targets"]
    }
    assert set(request_targets) == set(oracle_targets)
    for key, request_target in request_targets.items():
        oracle_target = oracle_targets[key]
        assert request_target == {
            "kind": "path",
            "value": oracle_target["path"],
        }
        assert request_target["value"] != oracle_target["id"]
        assert any(
            reference["target_fixture"] == key
            and reference["target_id"] == oracle_target["id"]
            for row in static["row_contracts"]
            for reference in row["dynamic_references"]
        )
    assert live["cleanup_boundaries"]["order"] == [
        "import_roots",
        "reference_busses",
        "asset_root",
    ]

    backend.apply_case(unit.scenario, runtime.plan)
    verification = runtime.verify_after_execution()
    verification.assert_passed()
    validate_import_archived_verification(
        sections,
        _plain(verification),
    )

    cleanup = runtime.cleanup_success()
    assert cleanup.paths_absent and cleanup.assets_removed
    assert fixtures.cleaned


@pytest.mark.parametrize("token_drift", ("missing", "extra", "mismatched"))
def test_compound_import_archive_rejects_dynamic_token_set_drift(
    tmp_path: Path,
    token_drift: str,
) -> None:
    unit, materialized, _backend, _fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id="CMP25-O22-AUDIO-IMPORT-02",
    )
    tokens = bound_import_metadata_tokens(materialized)
    projection = project_required_metadata_tokens(
        _sound_discovery(),
        object_type="Sound",
        required_tokens=tokens,
    )
    protocol = build_metadata_transaction_protocol(
        materialized.operation_requests,
        object_type="Sound",
        metadata_queries=materialized.metadata_queries,
        required_tokens=tokens,
        expected_required_token_projection=projection,
        equivalence="audio_import_v1",
    )
    before = runtime.hidden_before
    assert before is not None
    sections = compile_import_business_plan(
        unit.scenario,
        materialized,
        runtime.plan,
        before,
        protocol,
    )
    static = _plain(sections.static_expectation)
    if token_drift == "missing":
        static["dynamic_tokens"].pop()
    elif token_drift == "extra":
        static["dynamic_tokens"].append("UnexpectedLiveToken")
    else:
        static["dynamic_tokens"][0] = static["dynamic_tokens"][0].swapcase()

    with pytest.raises(
        ImportBusinessPlanError,
        match="dynamic tokens differ from metadata binding",
    ):
        validate_import_business_plan_archive(
            replace(
                sections,
                static_expectation=MappingProxyType(static),
            ),
            scenario=unit.scenario,
            protocol=protocol,
        )


@pytest.mark.parametrize(
    "relabel_as_preserve,expected_error",
    (
        (False, "mutate row requires dynamic expectations"),
        (True, "closed useExisting tab-import boundary"),
    ),
)
def test_compound_import_archive_rejects_required_row_with_both_dynamic_lists_empty(
    tmp_path: Path,
    relabel_as_preserve: bool,
    expected_error: str,
) -> None:
    unit, materialized, _backend, _fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id="CMP25-O22-AUDIO-TAB-04",
    )
    tokens = bound_import_metadata_tokens(materialized)
    projection = project_required_metadata_tokens(
        _sound_discovery(),
        object_type="Sound",
        required_tokens=tokens,
    )
    protocol = build_metadata_transaction_protocol(
        materialized.operation_requests,
        object_type="Sound",
        metadata_queries=materialized.metadata_queries,
        required_tokens=tokens,
        expected_required_token_projection=projection,
        equivalence="audio_import_tab_v1",
    )
    before = runtime.hidden_before
    assert before is not None
    sections = compile_import_business_plan(
        unit.scenario,
        materialized,
        runtime.plan,
        before,
        protocol,
    )
    static = _plain(sections.static_expectation)
    target = next(
        row for row in static["row_contracts"]
        if row["dynamic_mode"] == "mutate"
    )
    target["dynamic_properties"] = []
    target["dynamic_references"] = []
    if relabel_as_preserve:
        target["dynamic_mode"] = "preserve"
    live = _plain(sections.live_binding)
    candidate = replace(
        sections,
        static_expectation=MappingProxyType(static),
        delta_rules=tuple(
            MappingProxyType(rule) for rule in _rules(static, live)
        ),
        fixture_spec=MappingProxyType(
            {
                "kind": "import_compound_materialized_runtime_v2",
                "sha256": _hash({"static": static, "live": live}),
            }
        ),
    )

    with pytest.raises(
        ImportBusinessPlanError,
        match=expected_error,
    ):
        validate_import_business_plan_archive(
            candidate,
            scenario=unit.scenario,
            protocol=protocol,
        )


def test_compound_import_archive_rejects_projection_cleanup_and_reference_drift(
    tmp_path: Path,
) -> None:
    unit, materialized, backend, fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id="CMP25-O22-AUDIO-IMPORT-02",
    )
    tokens = bound_import_metadata_tokens(materialized)
    projection = project_required_metadata_tokens(
        _sound_discovery(),
        object_type="Sound",
        required_tokens=tokens,
    )
    protocol = build_metadata_transaction_protocol(
        materialized.operation_requests,
        object_type="Sound",
        metadata_queries=materialized.metadata_queries,
        required_tokens=tokens,
        expected_required_token_projection=projection,
        equivalence=(
            "audio_import_v1"
            if unit.scenario.api == "ak.wwise.core.audio.import"
            else "audio_import_tab_v1"
        ),
    )
    before = runtime.hidden_before
    assert before is not None
    sections = compile_import_business_plan(
        unit.scenario,
        materialized,
        runtime.plan,
        before,
        protocol,
    )

    bad_static = _plain(sections.static_expectation)
    bad_static["metadata_projection"][0]["metadata_type"] = "String"
    with pytest.raises(ImportBusinessPlanError, match="projection"):
        validate_import_business_plan_archive(
            replace(
                sections,
                static_expectation=MappingProxyType(bad_static),
            ),
            scenario=unit.scenario,
            protocol=protocol,
        )

    bad_live = _plain(sections.live_binding)
    bad_live["cleanup_boundaries"]["reference_bus_paths"] = []
    bad_live["reference_fixtures_sha256"] = _hash(
        bad_live["reference_fixtures"]
    )
    with pytest.raises(ImportBusinessPlanError, match="cleanup"):
        validate_import_business_plan_archive(
            replace(
                sections,
                live_binding=MappingProxyType(bad_live),
            ),
            scenario=unit.scenario,
            protocol=protocol,
        )

    backend.apply_case(unit.scenario, runtime.plan)
    verification = _plain(runtime.verify_after_execution())
    verification["after"]["rows"][0]["references"][0]["target_id"] = (
        fixtures.main_bus.id
    )
    with pytest.raises(ImportBusinessPlanError, match="non-default Bus"):
        validate_import_archived_verification(sections, verification)


def test_compound_preserve_archive_rejects_token_and_value_tamper(
    tmp_path: Path,
) -> None:
    unit, materialized, backend, fixtures, runtime = _compound_prepared(
        tmp_path,
        unit_id="CMP22-O22-AUDIO-TAB-04",
    )
    tokens = bound_import_metadata_tokens(materialized)
    protocol = build_metadata_transaction_protocol(
        materialized.operation_requests,
        object_type="Sound",
        metadata_queries=materialized.metadata_queries,
        required_tokens=tokens,
        expected_required_token_projection=project_required_metadata_tokens(
            _sound_discovery(),
            object_type="Sound",
            required_tokens=tokens,
        ),
        equivalence="audio_import_tab_v1",
    )
    before = runtime.hidden_before
    assert before is not None
    sections = compile_import_business_plan(
        unit.scenario,
        materialized,
        runtime.plan,
        before,
        protocol,
    )
    preserve_key = next(
        row["row_key"]
        for row in sections.static_expectation["row_contracts"]
        if row["dynamic_mode"] == "preserve"
    )

    static = _plain(sections.static_expectation)
    static_row = next(
        row for row in static["row_contracts"] if row["row_key"] == preserve_key
    )
    static_row["preserve_property_tokens"][0] = "UnexpectedLiveToken"
    live = _plain(sections.live_binding)
    static_tamper = replace(
        sections,
        static_expectation=MappingProxyType(static),
        delta_rules=tuple(
            MappingProxyType(rule) for rule in _rules(static, live)
        ),
        fixture_spec=MappingProxyType(
            {
                "kind": "import_compound_materialized_runtime_v2",
                "sha256": _hash({"static": static, "live": live}),
            }
        ),
    )
    with pytest.raises(
        ImportBusinessPlanError,
        match="preservation tokens differ from live metadata",
    ):
        validate_import_business_plan_archive(
            static_tamper,
            scenario=unit.scenario,
            protocol=protocol,
        )

    live = _plain(sections.live_binding)
    before_row = next(
        row
        for row in live["before_snapshot"]["rows"]
        if row["row_key"] == preserve_key
    )
    before_row["properties"].pop()
    live["before_snapshot_sha256"] = _hash(live["before_snapshot"])
    static = _plain(sections.static_expectation)
    before_tamper = replace(
        sections,
        live_binding=MappingProxyType(live),
        delta_rules=tuple(
            MappingProxyType(rule) for rule in _rules(static, live)
        ),
        fixture_spec=MappingProxyType(
            {
                "kind": "import_compound_materialized_runtime_v2",
                "sha256": _hash({"static": static, "live": live}),
            }
        ),
    )
    with pytest.raises(
        ImportBusinessPlanError,
        match="preservation snapshot token set is incomplete",
    ):
        validate_import_business_plan_archive(
            before_tamper,
            scenario=unit.scenario,
            protocol=protocol,
        )

    backend.apply_case(unit.scenario, runtime.plan)
    verification = _plain(runtime.verify_after_execution())
    after_row = next(
        row
        for row in verification["after"]["rows"]
        if row["row_key"] == preserve_key
    )
    after_row["properties"][0]["value"] = True
    with pytest.raises(
        ImportBusinessPlanError,
        match="preserved property .* changed after import",
    ):
        validate_import_archived_verification(sections, verification)

    verification = _plain(runtime.verify_after_execution())
    after_row = next(
        row
        for row in verification["after"]["rows"]
        if row["row_key"] == preserve_key
    )
    after_row["references"][0]["target_id"] = fixtures.fixtures[0].id
    with pytest.raises(
        ImportBusinessPlanError,
        match="preserved reference .* changed after import",
    ):
        validate_import_archived_verification(sections, verification)


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


def test_archived_original_binding_uses_the_absolute_path_flavor(
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
    windows_after = _plain(_after_value(plan))
    source = next(
        row["object"]["audio_source"]
        for row in windows_after["rows"]
        if isinstance(row.get("object"), dict)
    )
    old_path = source["original_file"]["path"]
    relative = source["original_file"]["relative_path"]
    relative_parts = tuple(PurePosixPath(relative).parts)
    windows_path = str(
        PureWindowsPath(r"C:\Campaign").joinpath(
            *(part.swapcase() for part in relative_parts)
        )
    )
    source["original_file"]["path"] = windows_path
    tree_proof = next(
        item for item in windows_after["originals_files"] if item["path"] == old_path
    )
    tree_proof["path"] = windows_path

    validate_import_archived_verification(
        sections,
        _verification(sections, after=windows_after),
    )

    posix_case_drift = _plain(_after_value(plan))
    drift_source = next(
        row["object"]["audio_source"]
        for row in posix_case_drift["rows"]
        if isinstance(row.get("object"), dict)
    )
    old_drift_path = drift_source["original_file"]["path"]
    drift_relative = str(drift_source["original_file"]["relative_path"])
    posix_path = str(
        PurePosixPath("/campaign").joinpath(
            *PurePosixPath(drift_relative).parts
        )
    )
    drift_source["original_file"]["path"] = posix_path
    drift_source["original_file"]["relative_path"] = drift_relative.swapcase()
    drift_source["original_relative_path"] = str(
        drift_source["original_relative_path"]
    ).swapcase()
    drift_tree = next(
        item
        for item in posix_case_drift["originals_files"]
        if item["path"] == old_drift_path
    )
    drift_tree["path"] = posix_path
    drift_tree["relative_path"] = drift_source["original_file"]["relative_path"]
    with pytest.raises(
        ImportBusinessPlanError,
        match="absolute/relative paths are inconsistent",
    ):
        validate_import_archived_verification(
            sections,
            _verification(sections, after=posix_case_drift),
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
