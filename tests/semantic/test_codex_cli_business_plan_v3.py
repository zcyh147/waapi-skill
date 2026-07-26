from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from tests.semantic.support.codex_cli_business_plan_v3 import (
    CliBusinessPlanError, compile_cli_business_plan, parse_cli_business_plan_sections,
    validate_cli_archived_verification, validate_cli_business_plan,
    validate_cli_business_plan_archive, _hash, _plain, _rules,
)
from tests.semantic.test_codex_cli_runtime_v3 import (
    _apply_success, _build, _dispatch, _make_console, _phase_evidence, _seal,
    _suite_cli_cases, _write_sealed_convert_side_effects,
)


def _prepared(tmp_path: Path, case):
    _plan, runtime, backend = _build(case, tmp_path)
    lifecycle = _seal(runtime, backend, _make_console(tmp_path), 31100)
    return runtime, backend, lifecycle


def _rehash_tree(tree: dict) -> None:
    tree["files"].sort(key=lambda row: str(row["relative_path"]))
    digest = hashlib.sha256()
    for row in tree["files"]:
        digest.update(str(row["relative_path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["size"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\0")
    tree["sha256"] = digest.hexdigest()


def _sealed_convert_archive(tmp_path: Path):
    case = next(
        item for item in _suite_cli_cases()
        if item.id == "O22-CLI-CONVERT-EXTERNAL-01"
    )
    runtime, backend, lifecycle = _prepared(tmp_path, case)
    sections = compile_cli_business_plan(runtime, runtime.gateway_protocol())
    _apply_success(runtime, backend)
    _write_sealed_convert_side_effects(runtime)
    archived = _plain(runtime.verify_after(
        dispatch=_dispatch(case), lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    ))
    assert archived["passed"] is True
    return sections, archived


@pytest.mark.parametrize("case", _suite_cli_cases(), ids=lambda x: x.id)
def test_all_twenty_cli_cases_compile_recompute_and_archive(tmp_path: Path, case) -> None:
    runtime, _backend, _lifecycle = _prepared(tmp_path, case)
    protocol = runtime.gateway_protocol()
    sections = compile_cli_business_plan(runtime, protocol)
    validate_cli_business_plan(sections, runtime, protocol, verify_files=True)
    parsed = parse_cli_business_plan_sections(sections.writer_kwargs())
    validate_cli_business_plan_archive(parsed, scenario=case, version="2022.1", protocol=protocol, verify_files=True)
    assert sections.payload_bindings["primary_steps"] == ["tx01.execute"]
    if runtime.plan.operation == "migrate":
        assert sections.static_expectation["terminal_execute"] is True
        assert "tx01.verify" not in sections.payload_bindings["verification_steps"]
    else:
        assert "tx01.verify" in sections.payload_bindings["verification_steps"]


@pytest.mark.parametrize("api", [
    "ak.wwise.cli.convertExternalSource", "ak.wwise.cli.generateSoundbank",
    "ak.wwise.cli.tabDelimitedImport",
    "ak.wwise.cli.migrate",
])
def test_archived_verification_accepts_one_exact_success_per_family(tmp_path: Path, api: str) -> None:
    case = next(x for x in _suite_cli_cases() if x.id == "O22-CLI-TAB-IMPORT-05") if api == "ak.wwise.cli.tabDelimitedImport" else next(x for x in _suite_cli_cases() if x.api == api)
    runtime, backend, lifecycle = _prepared(tmp_path, case)
    protocol = runtime.gateway_protocol(); sections = compile_cli_business_plan(runtime, protocol)
    oracle = _apply_success(runtime, backend)
    kwargs = {}
    if runtime.plan.requires_oracle:
        assert lifecycle.oracle is not None and oracle is not None
        kwargs = {"oracle_backend": oracle, "oracle_evidence": _phase_evidence(lifecycle.oracle)}
    verification = runtime.verify_after(dispatch=_dispatch(case, disconnect=runtime.plan.operation == "migrate"), lifecycle=lifecycle, business_evidence=_phase_evidence(lifecycle.business, natural_exit_before_shutdown=runtime.plan.operation == "migrate"), **kwargs)
    verification.assert_passed()
    validate_cli_archived_verification(sections, _plain(verification))


@pytest.mark.parametrize("case_id", [
    "O22-CLI-TAB-IMPORT-02", "O22-CLI-TAB-IMPORT-03",
    "O22-CLI-TAB-IMPORT-04", "O22-CLI-TAB-IMPORT-05",
])
def test_tab02_to_tab05_raw_runtime_evidence_closes_archive_oracle(
    tmp_path: Path, case_id: str,
) -> None:
    case = next(x for x in _suite_cli_cases() if x.id == case_id)
    runtime, backend, lifecycle = _prepared(tmp_path, case)
    sections = compile_cli_business_plan(runtime, runtime.gateway_protocol())
    oracle = _apply_success(runtime, backend)
    assert lifecycle.oracle is not None and oracle is not None
    verification = runtime.verify_after(
        dispatch=_dispatch(case), lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
        oracle_backend=oracle, oracle_evidence=_phase_evidence(lifecycle.oracle),
    )
    verification.assert_passed()
    archived = _plain(verification)
    validate_cli_archived_verification(sections, archived)

    expected = sections.static_expectation["asset_spec"]["expected"]["objects"][0]
    current = next(x for x in archived["after"]["objects"] if x["path"] == expected["path"])
    prestate_sha = next(
        x["sha256"] for x in sections.live_binding["input_proofs"]
        if x["relative_path"] == f"prestate/{expected['source_key']}.wav"
    )
    for field, value in (
        ("source_sha256", "0" * 64),
        ("source_sha256", prestate_sha),
        ("object_type", "Music Track"),
    ):
        tampered = copy.deepcopy(archived)
        row = next(x for x in tampered["after"]["objects"] if x["path"] == current["path"])
        row[field] = value
        with pytest.raises(CliBusinessPlanError):
            validate_cli_archived_verification(sections, tampered)


def test_tab05_archive_rejects_event_target_and_control_event_drift(tmp_path: Path) -> None:
    case = next(x for x in _suite_cli_cases() if x.id == "O22-CLI-TAB-IMPORT-05")
    runtime, backend, lifecycle = _prepared(tmp_path, case)
    sections = compile_cli_business_plan(runtime, runtime.gateway_protocol())
    oracle = _apply_success(runtime, backend)
    assert lifecycle.oracle is not None and oracle is not None
    archived = _plain(runtime.verify_after(
        dispatch=_dispatch(case), lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
        oracle_backend=oracle, oracle_evidence=_phase_evidence(lifecycle.oracle),
    ))
    validate_cli_archived_verification(sections, archived)

    wrong_target = copy.deepcopy(archived)
    generated = next(
        x for x in wrong_target["after"]["events"]
        if x["path"] != "\\Events\\Default Work Unit\\UI\\Menu_Control"
    )
    generated["target_ids"] = ["{00000000-0000-0000-0000-000000000099}"]
    with pytest.raises(CliBusinessPlanError, match="Event/Play Action"):
        validate_cli_archived_verification(sections, wrong_target)

    control_drift = copy.deepcopy(archived)
    control = next(
        x for x in control_drift["after"]["events"]
        if x["path"] == "\\Events\\Default Work Unit\\UI\\Menu_Control"
    )
    control["target_ids"] = ["{00000000-0000-0000-0000-000000000098}"]
    with pytest.raises(CliBusinessPlanError, match="control Event"):
        validate_cli_archived_verification(sections, control_drift)


def test_generate04_archive_proves_stale_cache_bank_and_header_replaced(tmp_path: Path) -> None:
    case = next(x for x in _suite_cli_cases() if x.id == "O22-CLI-GENERATE-BANK-04")
    runtime, backend, lifecycle = _prepared(tmp_path, case)
    sections = compile_cli_business_plan(runtime, runtime.gateway_protocol())
    _apply_success(runtime, backend)
    archived = _plain(runtime.verify_after(
        dispatch=_dispatch(case), lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    ))
    validate_cli_archived_verification(sections, archived)
    before_by_path = {x["path"]: x for x in archived["before"]["output_tree"]["files"]}

    cache_restored = copy.deepcopy(archived)
    cache_proof = next(
        copy.deepcopy(x) for x in archived["before"]["output_tree"]["files"]
        if x["relative_path"].endswith("Windows/SFX/stale-audio-cache.wem")
    )
    cache_restored["after"]["output_tree"]["files"].append(cache_proof)
    with pytest.raises(CliBusinessPlanError, match="cache"):
        validate_cli_archived_verification(sections, cache_restored)

    for suffix in ("Wwise_IDs.h", "Windows/Weapons_Core.bnk"):
        stale = copy.deepcopy(archived)
        row = next(x for x in stale["after"]["output_tree"]["files"] if x["relative_path"].endswith(suffix))
        row["sha256"] = before_by_path[row["path"]]["sha256"]
        with pytest.raises(CliBusinessPlanError):
            validate_cli_archived_verification(sections, stale)


def test_convert_archive_accepts_only_the_sealed_relational_side_effects(
    tmp_path: Path,
) -> None:
    sections, archived = _sealed_convert_archive(tmp_path)
    validate_cli_archived_verification(sections, archived)


@pytest.mark.parametrize(
    "attack",
    ["unbound_akd", "changed_wav", "extra_file", "bad_cache", "bad_settings"],
)
def test_convert_archive_rejects_relational_side_effect_tampering(
    tmp_path: Path,
    attack: str,
) -> None:
    sections, archived = _sealed_convert_archive(tmp_path)
    tampered = copy.deepcopy(archived)
    before_assets = {
        row["relative_path"]: row
        for row in tampered["before"]["asset_tree"]["files"]
    }
    after_assets = tampered["after"]["asset_tree"]
    after_project = tampered["after"]["project_tree"]

    if attack == "unbound_akd":
        row = next(
            row for row in after_assets["files"]
            if row["relative_path"] not in before_assets
        )
        row["relative_path"] = "wav/unbound.akd"
        row["path"] = str(Path(after_assets["root"]) / "wav/unbound.akd")
        _rehash_tree(after_assets)
    elif attack == "changed_wav":
        row = next(
            row for row in after_assets["files"]
            if row["relative_path"].casefold().endswith(".wav")
        )
        row["sha256"] = "f" * 64 if row["sha256"] != "f" * 64 else "e" * 64
        _rehash_tree(after_assets)
    elif attack == "extra_file":
        payload = b"extra"
        after_assets["files"].append({
            "path": str(Path(after_assets["root"]) / "wav/extra.tmp"),
            "relative_path": "wav/extra.tmp",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "mtime_ns": 1,
        })
        _rehash_tree(after_assets)
    elif attack == "bad_cache":
        row = next(
            row for row in after_project["files"]
            if row["relative_path"] == ".cache/CacheVersion"
        )
        row["sha256"] = hashlib.sha256(b"FAIL").hexdigest()
        _rehash_tree(after_project)
    else:
        row = next(
            row for row in after_project["files"]
            if row["relative_path"].endswith(".crossover.wsettings")
        )
        row["size"] = 0
        row["sha256"] = hashlib.sha256(b"").hexdigest()
        _rehash_tree(after_project)

    with pytest.raises(CliBusinessPlanError, match="convert"):
        validate_cli_archived_verification(sections, tampered)


@pytest.mark.parametrize("attack", ["rehash", "cross", "output", "control", "guid", "version", "terminal"])
def test_cli_business_plan_rejects_consistent_tampering(tmp_path: Path, attack: str) -> None:
    cases = _suite_cli_cases()
    case = next(x for x in cases if x.api == "ak.wwise.cli.tabDelimitedImport")
    runtime, backend, lifecycle = _prepared(tmp_path, case)
    protocol = runtime.gateway_protocol(); sections = compile_cli_business_plan(runtime, protocol)
    if attack == "rehash":
        static = _plain(sections.static_expectation); static["asset_spec"]["operation"] = "migrate"
        live = _plain(sections.live_binding)
        forged = replace(sections, static_expectation=MappingProxyType(static), delta_rules=tuple(MappingProxyType(x) for x in _rules(static, live)), fixture_spec=MappingProxyType({"kind": "cli_prepared_runtime_v1", "sha256": _hash({"static": static, "live": live})}))
        with pytest.raises(CliBusinessPlanError, match="asset specification"):
            validate_cli_business_plan_archive(forged, scenario=case, version="2022.1", protocol=protocol)
    elif attack == "cross":
        other = next(x for x in cases if x.api == "ak.wwise.cli.convertExternalSource")
        with pytest.raises(CliBusinessPlanError, match="identity"):
            validate_cli_business_plan_archive(sections, scenario=other, version="2022.1", protocol=protocol)
    elif attack == "terminal":
        migrate = next(x for x in cases if x.api == "ak.wwise.cli.migrate")
        mr, _mb, _ml = _prepared(tmp_path / "migrate", migrate)
        msections = compile_cli_business_plan(mr, mr.gateway_protocol())
        wrong = mr.gateway_protocol().steps[:-1]
        from tests.semantic.support.codex_eval_protocol_v3 import V3GatewayProtocol
        bad = V3GatewayProtocol(wrong, (2, len(wrong)))
        with pytest.raises(CliBusinessPlanError, match="protocol"):
            validate_cli_business_plan_archive(msections, scenario=migrate, version="2022.1", protocol=bad)
    else:
        oracle = _apply_success(runtime, backend); assert lifecycle.oracle is not None and oracle is not None
        verification = _plain(runtime.verify_after(dispatch=_dispatch(case), lifecycle=lifecycle, business_evidence=_phase_evidence(lifecycle.business), oracle_backend=oracle, oracle_evidence=_phase_evidence(lifecycle.oracle)))
        if attack == "output":
            verification["after"]["asset_tree"] = {"wrong": True}
        elif attack == "control":
            verification["after"]["source_template_tree"] = {"wrong": True}
        elif attack == "guid":
            verification["after"]["objects"][0]["object_id"] = "bad-guid"
        else:
            migrate = next(x for x in cases if x.api == "ak.wwise.cli.migrate")
            mr, mb, ml = _prepared(tmp_path / "version", migrate); ms = compile_cli_business_plan(mr, mr.gateway_protocol()); mo = _apply_success(mr, mb); assert ml.oracle and mo
            verification = _plain(mr.verify_after(dispatch=_dispatch(migrate, disconnect=True), lifecycle=ml, business_evidence=_phase_evidence(ml.business, natural_exit_before_shutdown=True), oracle_backend=mo, oracle_evidence=_phase_evidence(ml.oracle)))
            verification["after"]["project_version"] = "v2021.1.0"
            sections = ms
        with pytest.raises(CliBusinessPlanError):
            validate_cli_archived_verification(sections, verification)
