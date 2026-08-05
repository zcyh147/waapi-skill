from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support.platform_filesystem import create_symlink_or_skip
from . import run_codex_skill_matrix as matrix
from .support.codex_eval_fixtures import (
    AudioOracleSnapshot,
    MissingPathOracleSnapshot,
    ObjectOracle,
    ObjectRowsOracleSnapshot,
    OracleSnapshot,
    PathOracleSnapshot,
)
from .support.codex_eval_suite import EvalSession, load_eval_suite
from .support.codex_harness import CodexInfrastructureError, CodexInfrastructureFailure


GATEWAY_SPEC = importlib.util.spec_from_file_location(
    "waapi_gateway_semantic_matrix_test",
    matrix.SKILL_ROOT / "scripts" / "gateway.py",
)
assert GATEWAY_SPEC is not None and GATEWAY_SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(GATEWAY_SPEC)
sys.modules[GATEWAY_SPEC.name] = waapi_gateway
GATEWAY_SPEC.loader.exec_module(waapi_gateway)


def _suite():
    return load_eval_suite(matrix.DEFAULT_SUITE)


def _session(case_id: str, phase: str, *, version: str = "2022.1") -> EvalSession:
    matches = [
        session
        for session in _suite().expand_profile("full_cross_version_168")
        if session.case.id == case_id
        and session.phase == phase
        and session.version == version
        and session.repetition == 1
    ]
    assert len(matches) == 1
    return matches[0]


def _record(step_name: str, payload: object, **overrides: object) -> SimpleNamespace:
    values = {
        "step_name": step_name,
        "payload": payload,
        "authenticated": True,
        "accepted": True,
        "succeeded": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _evidence(*records: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(records=tuple(records))


def _runner_options(iteration_root: Path) -> matrix.RunnerOptions:
    return matrix.RunnerOptions(
        profile="screening",
        iteration_root=iteration_root,
        suite_path=matrix.DEFAULT_SUITE,
        skill_source=matrix.SKILL_ROOT,
        codex_binary=Path("/not-used/codex"),
        auth_json=Path("/not-used/auth.json"),
        live_config=matrix.DEFAULT_LIVE_CONFIG,
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        timeout_seconds=10.0,
        case_ids=(),
        versions=(),
        pair_ids=(),
        offline_only=False,
        overwrite=False,
    )


def _fake_codex_result() -> SimpleNamespace:
    return SimpleNamespace(
        command_facts=SimpleNamespace(command_records=()),
        stdout='{"type":"thread.started"}\n',
        stderr="raw stderr\n",
        final_response="raw final",
        duration_seconds=0.25,
        facts_dict=lambda: {"raw": "facts"},
    )


class _FakeGrade:
    passed = True
    failed_gate_ids: tuple[str, ...] = ()

    @staticmethod
    def as_dict() -> dict[str, object]:
        return {"passed": True, "failed_gate_ids": []}


class _FakeBrokerEvidence:
    def __init__(self, records: tuple[SimpleNamespace, ...]) -> None:
        self.records = records

    def as_dict(self, *, include_output: bool = False) -> dict[str, object]:
        return {
            "records": [
                {"step_name": record.step_name, "payload": record.payload}
                for record in self.records
            ],
            "include_output": include_output,
        }


def _write_dispatch_record(path: Path, *, api: str, ok: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": ok,
        "api": api,
        "evidence_path": str(path),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _waapi_result(payload: object) -> str:
    return matrix.WAAPI_RESULT_PREFIX + json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _query_rows_snapshot() -> tuple[OracleSnapshot, dict[str, object]]:
    first = ObjectOracle(
        id="{11111111-1111-1111-1111-111111111111}",
        name="DirectChild",
        type="Sound",
        path=r"\Actor-Mixer Hierarchy\Parent\DirectChild",
        notes=None,
    )
    second = ObjectOracle(
        id="{22222222-2222-2222-2222-222222222222}",
        name="OtherChild",
        type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Parent\OtherChild",
        notes=None,
    )
    return (
        OracleSnapshot("Q2", ObjectRowsOracleSnapshot((first, second))),
        {
            "count": 2,
            "objects": [
                {
                    "id": second.id.lower(),
                    "name": second.name,
                    "type": second.type,
                    "path": second.path,
                },
                {
                    "id": first.id.lower(),
                    "name": first.name,
                    "type": first.type,
                    "path": first.path,
                },
            ],
        },
    )


def _q5_absence_evidence() -> tuple[dict[str, object], dict[str, object]]:
    dispatch = {
        "ok": False,
        "api": matrix.OBJECT_GET_URI,
        "error_code": "WaapiRequestFailed",
        "result": None,
        "waapi_error_uri": "ak.wwise.query.invalid_query",
        "waapi_error_details": {"message": "Object not found"},
        "message": "WAAPI request failed",
        "evidence_path": "/trusted/evidence/0001.json",
    }
    original = {
        field: dispatch[field]
        for field in (
            "error_code",
            "waapi_error_uri",
            "waapi_error_details",
            "message",
            "evidence_path",
        )
    }
    gateway = {
        "ok": True,
        "status": "ok",
        "command": "query-object",
        "query_bound": {"mode": "exact-object"},
        "count": 0,
        "objects": [],
        "call": {
            "ok": True,
            "api": matrix.OBJECT_GET_URI,
            "result": {"return": []},
            "normalization": {
                "kind": "exact-object-absence",
                "source": "ak.wwise.query.invalid_query:object-not-found",
                "original": original,
            },
        },
    }
    return gateway, dispatch


def test_parse_args_uses_closed_defaults_and_resolves_explicit_live_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovered_codex = tmp_path / "discovered-codex"
    discovered_codex.write_text("not invoked\n", encoding="utf-8")
    discovered_codex.chmod(0o755)
    discovery_values: list[str | None] = []

    def resolve_codex(value: str | None) -> Path:
        discovery_values.append(value)
        return discovered_codex.resolve(strict=True)

    monkeypatch.setattr(matrix, "resolve_codex_binary", resolve_codex)
    unconfigured_live_config = tmp_path / "missing-local-live-environment.json"
    monkeypatch.setattr(matrix, "DEFAULT_LIVE_CONFIG", unconfigured_live_config)
    defaults = matrix.parse_args([])

    assert defaults.profile == "screening"
    assert defaults.codex_binary == discovered_codex.resolve(strict=True)
    assert defaults.live_config == unconfigured_live_config.resolve(strict=False)
    assert defaults.suite_path == matrix.DEFAULT_SUITE.resolve(strict=True)
    assert defaults.skill_source == matrix.SKILL_ROOT.resolve(strict=True)
    assert defaults.model == "gpt-5.6-sol"
    assert defaults.reasoning_effort == "medium"
    assert defaults.service_tier == "priority"
    assert defaults.timeout_seconds == 240.0
    assert defaults.case_ids == ()
    assert defaults.versions == ()
    assert defaults.pair_ids == ()
    assert defaults.offline_only is False
    assert defaults.overwrite is False

    live_config = tmp_path / "live-environment.json"
    live_config.write_text("{}\n", encoding="utf-8")
    explicit = matrix.parse_args(
        [
            "--live-config",
            str(live_config),
            "--case-id",
            "Q1",
            "--version",
            "2025.1",
            "--pair-id",
            "custom-profile:Q1:2025.1:r1",
            "--offline-only",
            "--overwrite",
        ]
    )

    assert explicit.live_config == live_config.resolve(strict=True)
    assert explicit.case_ids == ("Q1",)
    assert explicit.versions == ("2025.1",)
    assert explicit.pair_ids == ("custom-profile:Q1:2025.1:r1",)
    assert explicit.offline_only is True
    assert explicit.overwrite is True
    assert discovery_values == [None, None]


def test_parse_args_gives_explicit_codex_binary_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit_codex = tmp_path / "codex.exe"
    explicit_codex.write_text("not invoked\n", encoding="utf-8")
    explicit_codex.chmod(0o755)
    observed: list[str | None] = []

    def resolve_codex(value: str | None) -> Path:
        observed.append(value)
        assert value == str(explicit_codex)
        return explicit_codex.resolve(strict=True)

    monkeypatch.setattr(matrix, "resolve_codex_binary", resolve_codex)

    parsed = matrix.parse_args(["--codex-binary", str(explicit_codex)])

    assert parsed.codex_binary == explicit_codex.resolve(strict=True)
    assert observed == [str(explicit_codex)]


def test_parse_args_fails_closed_when_codex_discovery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(_value: str | None) -> Path:
        raise matrix.CodexHarnessError("Codex CLI was not found on PATH")

    monkeypatch.setattr(matrix, "resolve_codex_binary", reject)

    with pytest.raises(SystemExit):
        matrix.parse_args([])


def test_parse_args_rejects_non_positive_timeout() -> None:
    with pytest.raises(SystemExit):
        matrix.parse_args(["--timeout", "0"])


def test_parse_args_rejects_unknown_and_duplicate_versions() -> None:
    with pytest.raises(SystemExit):
        matrix.parse_args(["--version", "2099.1"])
    with pytest.raises(SystemExit):
        matrix.parse_args(["--version", "2022.1", "--version", "2022.1"])


def test_parse_args_rejects_duplicate_pair_ids_without_using_closed_choices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda _value: tmp_path / "synthetic-codex",
    )
    pair_id = "custom-profile:Q1:2022.1:r37"
    parsed = matrix.parse_args(["--pair-id", pair_id])
    assert parsed.pair_ids == (pair_id,)

    with pytest.raises(SystemExit):
        matrix.parse_args(["--pair-id", pair_id, "--pair-id", pair_id])


def test_live_dependency_preflight_reports_closed_success_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = SimpleNamespace(WaapiClient=object(), WaapiRequestFailed=object())
    monkeypatch.setattr(matrix.importlib, "import_module", lambda name: module if name == "waapi" else None)

    result = matrix.require_live_runner_dependencies()

    assert result == {
        "contract": matrix.LIVE_DEPENDENCY_PREFLIGHT_CONTRACT,
        "ok": True,
        "dependency": "waapi-client",
        "module": "waapi",
        "required_symbols": ["WaapiClient", "WaapiRequestFailed"],
        "current_interpreter": str(Path(matrix.sys.executable).resolve(strict=False)),
        "automatic_install_attempted": False,
    }


def test_live_dependency_preflight_reports_skill_venv_without_installing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_root = tmp_path / "skills" / "waapi-skill"
    skill_root.mkdir(parents=True)
    monkeypatch.setattr(matrix, "SKILL_ROOT", skill_root)

    def missing(_name: str) -> object:
        raise ModuleNotFoundError("No module named 'waapi'")

    monkeypatch.setattr(matrix.importlib, "import_module", missing)

    with pytest.raises(matrix.LiveDependencyPreflightError) as raised:
        matrix.require_live_runner_dependencies()

    payload = raised.value.as_dict()
    expected_python = matrix.skill_venv_python()
    assert payload["contract"] == matrix.LIVE_DEPENDENCY_PREFLIGHT_CONTRACT
    assert payload["ok"] is False
    assert payload["current_interpreter"] == str(Path(matrix.sys.executable).resolve(strict=False))
    assert payload["recommended_interpreter"] == str(expected_python)
    assert payload["recommended_interpreter_exists"] is False
    assert payload["automatic_install_attempted"] is False
    assert payload["error"] == {
        "type": "ModuleNotFoundError",
        "message": "No module named 'waapi'",
    }
    assert str(expected_python) in str(raised.value)
    assert "Do not install into the global interpreter" in str(raised.value)


def test_session_filters_preserve_source_order_and_exact_accounting() -> None:
    sessions = _suite().expand_profile("full_cross_version_168")

    assert matrix.select_sessions(sessions, case_ids=(), versions=()) == sessions
    selected = matrix.select_sessions(
        sessions,
        case_ids=("M1", "Q1"),
        versions=("2021.1",),
    )

    assert [(item.case.id, item.version, item.phase) for item in selected] == [
        ("Q1", "2021.1", "single"),
        ("M1", "2021.1", "preview"),
        ("M1", "2021.1", "confirm"),
    ]
    assert len({item.session_id for item in selected}) == len(selected) == 3


def test_default_selection_preserves_legacy_preview_only_formal_profile() -> None:
    sessions = _suite().expand_profile("formal_98")

    selected = matrix.select_sessions(sessions, case_ids=(), versions=())

    assert selected == sessions
    assert any(
        session.phase == "preview"
        and not any(
            candidate.pair_id == session.pair_id and candidate.phase == "confirm"
            for candidate in sessions
        )
        for session in sessions
    )


def test_pair_id_filter_selects_one_complete_single_phase_unit() -> None:
    sessions = _suite().expand_profile("screening")
    target = next(session for session in sessions if session.case.id == "Q1")

    selected = matrix.select_sessions(
        sessions,
        case_ids=(),
        versions=(),
        pair_ids=(target.pair_id,),
    )

    assert selected == (target,)
    assert selected[0].phase == "single"


def test_pair_id_filter_selects_complete_preview_confirm_unit_in_source_order() -> None:
    sessions = _suite().expand_profile("screening")
    target_pair = next(session.pair_id for session in sessions if session.case.id == "M1")

    selected = matrix.select_sessions(
        sessions,
        case_ids=(),
        versions=(),
        pair_ids=(target_pair,),
    )

    assert [session.phase for session in selected] == ["preview", "confirm"]
    assert {session.pair_id for session in selected} == {target_pair}


def test_pair_id_filter_selects_profile_defined_preview_only_unit() -> None:
    sessions = _suite().expand_profile("formal_98")
    preview = next(
        session
        for session in sessions
        if session.phase == "preview"
        and not any(
            candidate.pair_id == session.pair_id and candidate.phase == "confirm"
            for candidate in sessions
        )
    )

    selected = matrix.select_sessions(
        sessions,
        case_ids=(),
        versions=(),
        pair_ids=(preview.pair_id,),
    )

    assert selected == (preview,)


def test_pair_id_filter_fails_closed_for_unknown_pair() -> None:
    sessions = _suite().expand_profile("screening")

    with pytest.raises(SystemExit, match="do not exist in the expanded profile"):
        matrix.select_sessions(
            sessions,
            case_ids=(),
            versions=(),
            pair_ids=("screening:UNKNOWN:2022.1:r1",),
        )


@pytest.mark.parametrize(
    ("case_ids", "versions", "offline_only"),
    [
        (("Q2",), (), False),
        ((), ("2021.1",), False),
        ((), (), True),
    ],
)
def test_pair_id_filter_fails_closed_when_other_filters_exclude_requested_pair(
    case_ids: tuple[str, ...],
    versions: tuple[str, ...],
    offline_only: bool,
) -> None:
    sessions = _suite().expand_profile("screening")
    target_pair = next(session.pair_id for session in sessions if session.case.id == "Q1")

    with pytest.raises(SystemExit, match="excluded by the case/version/offline filters"):
        matrix.select_sessions(
            sessions,
            case_ids=case_ids,
            versions=versions,
            pair_ids=(target_pair,),
            offline_only=offline_only,
        )


def test_pair_selection_rejects_confirm_only_transaction_phase() -> None:
    sessions = _suite().expand_profile("screening")
    orphan = next(
        session
        for session in sessions
        if session.case.id == "M1" and session.phase == "confirm"
    )

    with pytest.raises(SystemExit, match="incomplete or malformed"):
        matrix.select_sessions(
            (orphan,),
            case_ids=(),
            versions=(),
            pair_ids=(orphan.pair_id,),
        )


def test_pair_selection_rejects_reversed_preview_confirm_order() -> None:
    sessions = _suite().expand_profile("screening")
    pair = tuple(session for session in sessions if session.case.id == "M1")
    assert [session.phase for session in pair] == ["preview", "confirm"]

    with pytest.raises(SystemExit, match="incomplete or malformed"):
        matrix.select_sessions(
            tuple(reversed(pair)),
            case_ids=(),
            versions=(),
            pair_ids=(pair[0].pair_id,),
        )


def test_gateway_candidate_accounting_includes_direct_interpreter_bypass() -> None:
    runner = matrix.SKILL_ROOT / "scripts" / "run.py"
    records = (
        SimpleNamespace(argv=("python", str(runner), "gateway.py", "status")),
        SimpleNamespace(argv=("/usr/bin/python3", str(runner), "gateway.py", "capabilities")),
        SimpleNamespace(argv=("python", str(runner.with_name("other.py")), "gateway.py", "status")),
        SimpleNamespace(argv=("python", str(runner), "not-gateway.py", "status")),
        SimpleNamespace(argv=("python", str(runner), "gateway.py")),
    )
    result = SimpleNamespace(command_facts=SimpleNamespace(command_records=records))

    assert matrix.gateway_candidate_argvs(result, skill_source=matrix.SKILL_ROOT) == (
        records[0].argv,
        records[1].argv,
    )


def test_gateway_candidate_accounting_normalizes_only_matching_version_prefix() -> None:
    runner = matrix.SKILL_ROOT / "scripts" / "run.py"
    accepted = SimpleNamespace(
        argv=("WWISE_VERSION=2022.1", "python", str(runner), "gateway.py", "operation-schema", "object.copy")
    )
    env_accepted = SimpleNamespace(
        argv=("env", "WWISE_VERSION=2022.1", "python", str(runner), "gateway.py", "operation-schema", "object.copy")
    )
    runner_level = SimpleNamespace(
        argv=(
            "python",
            str(runner),
            "--version",
            "2022.1",
            "gateway.py",
            "operation-schema",
            "object.copy",
        )
    )
    wrong = SimpleNamespace(
        argv=("WWISE_VERSION=2023.1", "python", str(runner), "gateway.py", "operation-schema", "object.copy")
    )
    arbitrary = SimpleNamespace(
        argv=("PYTHONPATH=/tmp", "python", str(runner), "gateway.py", "operation-schema", "object.copy")
    )
    result = SimpleNamespace(
        command_facts=SimpleNamespace(
            command_records=(accepted, env_accepted, runner_level, wrong, arbitrary)
        )
    )

    assert matrix.gateway_candidate_argvs(
        result,
        skill_source=matrix.SKILL_ROOT,
        expected_wwise_version="2022.1",
    ) == (
        ("python", str(runner), "gateway.py", "operation-schema", "object.copy"),
        ("python", str(runner), "gateway.py", "operation-schema", "object.copy"),
        (
            "python",
            str(runner),
            "gateway.py",
            "--version",
            "2022.1",
            "operation-schema",
            "object.copy",
        ),
    )


def test_gateway_candidate_accounting_accepts_windows_copy_and_candidate_runners(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "workspace-copy"
    candidate = tmp_path / "candidate"
    copied_runner = copied / "scripts" / "run.py"
    candidate_runner = candidate / "scripts" / "run.py"
    records = (
        SimpleNamespace(argv=("python", str(copied_runner), "gateway.py", "preview")),
        SimpleNamespace(argv=("python", str(candidate_runner), "gateway.py", "execute", "tx-1")),
    )
    result = SimpleNamespace(command_facts=SimpleNamespace(command_records=records))

    assert matrix.gateway_candidate_argvs(
        result,
        skill_source=copied,
        alternate_skill_sources=(candidate,),
    ) == tuple(record.argv for record in records)


def test_offline_fixture_and_oracle_helpers_are_closed_to_offline_cases() -> None:
    catalog = _session("C1", "single")
    boundary = _session("B1", "single")
    live = _session("Q1", "single")

    assert matrix.offline_fixture_values(catalog) == {}
    boundary_values = matrix.offline_fixture_values(boundary)
    assert boundary_values == {}
    assert matrix.offline_oracle(catalog) == {"offline_no_wwise": True}
    assert matrix.offline_oracle(boundary) == {
        "offline_no_wwise": True,
        "mutation_uri_count": 0,
    }
    with pytest.raises(ValueError, match="not an offline semantic case"):
        matrix.offline_fixture_values(live)
    with pytest.raises(ValueError, match="not an offline semantic case"):
        matrix.offline_oracle(live)


def test_broker_payload_requires_one_named_mapping() -> None:
    payload = {"ok": True, "command": "preview"}

    assert matrix.broker_payload(_evidence(_record("preview", payload)), "preview") == payload
    assert matrix.broker_payload(_evidence(), "preview") == {}
    assert matrix.broker_payload(_evidence(_record("preview", "not-json-object")), "preview") == {}
    assert (
        matrix.broker_payload(
            _evidence(_record("preview", payload), _record("preview", payload)),
            "preview",
        )
        == {}
    )


def test_preview_binding_accepts_only_canonical_unexecuted_awaiting_preview() -> None:
    payload = {
        "transaction_id": "tx-123",
        "artifact_hash": "a" * 64,
        "state": matrix.TransactionState.AWAITING_CONFIRMATION.value,
        "executed": False,
        "verified": False,
    }

    assert matrix.preview_binding(_evidence(_record("preview", payload))) == (
        "tx-123",
        "a" * 64,
    )

    invalid_payloads = (
        {**payload, "transaction_id": ""},
        {**payload, "artifact_hash": "A" * 64},
        {**payload, "artifact_hash": "sha256:" + "a" * 64},
        {**payload, "state": matrix.TransactionState.CONFIRMED.value},
        {**payload, "executed": True},
        {**payload, "verified": True},
    )
    for invalid in invalid_payloads:
        with pytest.raises(matrix.FixtureContractError):
            matrix.preview_binding(_evidence(_record("preview", invalid)))

    with pytest.raises(matrix.FixtureContractError):
        matrix.preview_binding(_evidence(_record("preview", payload), _record("preview", payload)))


def test_dispatch_evidence_is_path_bound_sorted_and_counted_exactly(tmp_path: Path) -> None:
    mutation_uri = "ak.wwise.core.object.setNotes"
    second = tmp_path / "002.json"
    first = tmp_path / "001.json"
    expected_first = _write_dispatch_record(first, api=mutation_uri)
    expected_second = _write_dispatch_record(second, api="ak.wwise.core.object.get")

    assert matrix.read_dispatch_evidence(tmp_path) == [expected_first, expected_second]
    assert matrix.count_dispatch_api(tmp_path, mutation_uri) == 1
    assert matrix.count_dispatch_api(tmp_path, "ak.wwise.core.object.get") == 1

    duplicate = tmp_path / "003.json"
    _write_dispatch_record(duplicate, api=mutation_uri)
    assert matrix.count_dispatch_api(tmp_path, mutation_uri) == 2


def test_dispatch_evidence_rejects_path_mismatch_and_invalid_uri(tmp_path: Path) -> None:
    record = tmp_path / "record.json"
    record.write_text(
        json.dumps(
            {
                "ok": True,
                "api": "ak.wwise.core.object.get",
                "evidence_path": str(tmp_path / "other.json"),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(matrix.FixtureContractError, match="path binding mismatch"):
        matrix.read_dispatch_evidence(tmp_path)
    with pytest.raises(matrix.FixtureContractError, match="no closed mutation URI"):
        matrix.count_dispatch_api(tmp_path, "")


def test_dispatch_evidence_rejects_symlinked_record(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    _write_dispatch_record(outside, api="ak.wwise.core.object.get")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    create_symlink_or_skip(evidence / "linked.json", outside)

    with pytest.raises(matrix.FixtureContractError, match="regular file"):
        matrix.read_dispatch_evidence(evidence)


@pytest.mark.parametrize(
    ("case_id", "version", "apis", "row_ok", "status"),
    [
        ("R1", "2021.1", ("ak.wwise.core.getInfo", matrix.OBJECT_GET_URI), (True, True), "ok"),
        ("R1", "2022.1", ("ak.wwise.core.getInfo", "ak.wwise.core.getProjectInfo"), (True, True), "ok"),
        ("R2", "2022.1", (matrix.OBJECT_GET_URI,), (True,), "ok"),
        ("R3", "2022.1", ("ak.wwise.ui.getSelectedObjects",), (False,), "unsupported_boundary"),
        ("R4", "2022.1", ("ak.wwise.core.object.getTypes",), (True,), "ok"),
        ("R5", "2022.1", ("ak.wwise.core.object.created",), (True,), "ok"),
        ("R6", "2022.1", ("ak.wwise.waapi.getFunctions",), (True,), "ok"),
    ],
)
def test_fixed_read_dispatch_evidence_requires_exact_read_only_sequence(
    case_id: str,
    version: str,
    apis: tuple[str, ...],
    row_ok: tuple[bool, ...],
    status: str,
) -> None:
    payload = {"ok": True, "status": status}
    rows = tuple({"api": api, "ok": ok} for api, ok in zip(apis, row_ok))

    assert matrix.fixed_read_dispatch_evidence_matches(
        case_id=case_id,
        version=version,
        gateway_payload=payload,
        dispatch_rows=rows,
    )
    assert not matrix.fixed_read_dispatch_evidence_matches(
        case_id=case_id,
        version=version,
        gateway_payload=payload,
        dispatch_rows=(*rows, {"api": "ak.wwise.core.object.setNotes", "ok": True}),
    )


def test_fixed_read_payload_and_final_result_contracts_are_exact() -> None:
    version = "2022.1"
    probe_name = "WAAPI_SEM_TOPIC_2022_1_deadbeef1234"
    r4_dispatch_rows = (
        {
            "ok": True,
            "api": "ak.wwise.core.object.getTypes",
            "result": {
                "return": [
                    {"classId": 1, "name": "ActorMixer", "type": "ActorMixer"},
                ]
            },
        },
    )
    cases = {
        "R1": (
            {
                "ok": True,
                "status": "ok",
                "detected_version": version,
                "project": {"id": "{project}", "name": "SampleProject", "path": "/tmp/SampleProject.wproj"},
                "wwise": {"isCommandLine": True},
            },
            {
                "detected_version": version,
                "project": {"id": "{project}", "name": "SampleProject", "path": "/tmp/SampleProject.wproj"},
            },
            {},
            None,
        ),
        "R2": (
            {
                "ok": True,
                "detected_version": version,
                "count": 1,
                "buses": [{"id": "{bus}", "name": "Master Audio Bus", "type": "Bus", "path": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"}],
            },
            {
                "count": 1,
                "buses": [{"id": "{bus}", "name": "Master Audio Bus", "type": "Bus", "path": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"}],
            },
            {},
            None,
        ),
        "R3": (
            {
                "ok": True,
                "detected_version": version,
                "status": "unsupported_boundary",
                "is_command_line": True,
                "count": None,
                "objects": None,
            },
            {"status": "unsupported_boundary", "count": None, "objects": None},
            {},
            None,
        ),
        "R4": (
            {
                "ok": True,
                "status": "ok",
                "detected_version": version,
                "operation": "types",
                "summary_only": True,
                "agent_result": {"count": 1, "contains_actor_mixer": True},
            },
            {"count": 1, "contains_actor_mixer": True},
            {},
            None,
        ),
        "R5": (
            {
                "ok": True,
                "detected_version": version,
                "topic": "ak.wwise.core.object.created",
                "match": {"object": {"type": "ActorMixer"}},
                "cleanup": "unsubscribed",
                "event": {"object": {"id": "{topic-probe}", "type": "ActorMixer"}},
            },
            {"topic": "ak.wwise.core.object.created", "event_object_id": "{topic-probe}", "cleanup": "unsubscribed"},
            {"topic_probe_name": probe_name, "topic_probe_event_type": "ActorMixer"},
            {"name": probe_name, "object_id": "{TOPIC-PROBE}", "created": True, "deleted": True},
        ),
        "R6": (
            {
                "ok": True,
                "detected_version": version,
                "inventory": {
                    "kind": "function",
                    "count": 2,
                    "uris": ["ak.a", "ak.b"],
                    "packaged_manifest": {"matches": True},
                },
            },
            {"kind": "function", "count": 2, "matches_packaged": True},
            {},
            None,
        ),
    }

    for case_id, (payload, final, values, publisher) in cases.items():
        dispatch_rows = r4_dispatch_rows if case_id == "R4" else ()
        assert matrix.fixed_read_payload_is_valid(
            case_id=case_id,
            version=version,
            gateway_payload=payload,
            dispatch_rows=dispatch_rows,
            values=values,
            publisher=publisher,
        )
        assert matrix.final_fixed_read_response_matches(
            _waapi_result(final),
            case_id=case_id,
            gateway_payload=payload,
            dispatch_rows=dispatch_rows,
            values=values,
        )
        assert not matrix.final_fixed_read_response_matches(
            _waapi_result({**final, "extra": True}),
            case_id=case_id,
            gateway_payload=payload,
            dispatch_rows=dispatch_rows,
            values=values,
        )


def test_r4_summary_oracle_is_independent_from_gateway_projection() -> None:
    dispatch_rows = (
        {
            "ok": True,
            "api": "ak.wwise.core.object.getTypes",
            "result": {
                "return": [
                    {"classId": 7, "name": "Sound", "type": "Sound"},
                    {"classId": 8, "name": "ActorMixer", "type": "WObject"},
                ]
            },
        },
    )
    expected = {"count": 2, "contains_actor_mixer": True}
    payload = {
        "ok": True,
        "status": "ok",
        "detected_version": "2023.1",
        "operation": "types",
        "summary_only": True,
        "agent_result": expected,
    }

    assert matrix.fixed_read_r4_dispatch_summary(dispatch_rows) == expected
    assert matrix.fixed_read_payload_is_valid(
        case_id="R4",
        version="2023.1",
        gateway_payload=payload,
        dispatch_rows=dispatch_rows,
        values={},
        publisher=None,
    )
    assert matrix.final_fixed_read_response_matches(
        _waapi_result(expected),
        case_id="R4",
        gateway_payload=payload,
        dispatch_rows=dispatch_rows,
        values={},
    )

    tampered = {**payload, "agent_result": {"count": 1, "contains_actor_mixer": True}}
    assert not matrix.fixed_read_payload_is_valid(
        case_id="R4",
        version="2023.1",
        gateway_payload=tampered,
        dispatch_rows=dispatch_rows,
        values={},
        publisher=None,
    )
    assert not matrix.final_fixed_read_response_matches(
        _waapi_result(tampered["agent_result"]),
        case_id="R4",
        gateway_payload=tampered,
        dispatch_rows=dispatch_rows,
        values={},
    )

    leaked = {**payload, "normalized": []}
    assert not matrix.fixed_read_payload_is_valid(
        case_id="R4",
        version="2023.1",
        gateway_payload=leaked,
        dispatch_rows=dispatch_rows,
        values={},
        publisher=None,
    )


def test_r4_summary_oracle_rejects_malformed_dispatch_rows() -> None:
    malformed = (
        {
            "ok": True,
            "api": "ak.wwise.core.object.getTypes",
            "result": {
                "return": [
                    {"classId": True, "name": "ActorMixer", "type": "ActorMixer"},
                ]
            },
        },
    )

    assert matrix.fixed_read_r4_dispatch_summary(malformed) is None


def test_query_payload_matches_exact_path_oracle_with_case_insensitive_guid() -> None:
    expected = ObjectOracle(
        id="{01234567-89AB-CDEF-0123-456789ABCDEF}",
        name="SemanticQueryTarget",
        type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticQueryTarget",
        notes="fixture",
    )
    snapshot = OracleSnapshot("Q1", PathOracleSnapshot(expected))
    payload = {
        "count": 1,
        "objects": [
            {
                "id": expected.id.lower(),
                "name": expected.name,
                "type": expected.type,
                "path": expected.path,
            }
        ],
    }

    assert matrix.query_payload_matches_fixture(payload, snapshot) is True
    assert matrix.query_payload_matches_fixture({**payload, "count": 2}, snapshot) is False
    assert matrix.query_payload_matches_fixture({**payload, "objects": []}, snapshot) is False
    wrong_path = {**payload, "objects": [{**payload["objects"][0], "path": r"\wrong"}]}
    assert matrix.query_payload_matches_fixture(wrong_path, snapshot) is False

    audio_snapshot = OracleSnapshot(
        "I1",
        AudioOracleSnapshot(object=None, wav_sha256="b" * 64),
    )
    assert matrix.query_payload_matches_fixture(payload, audio_snapshot) is False


def test_query_payload_and_final_response_cover_rows_and_explicit_missing_path() -> None:
    rows_snapshot, payload = _query_rows_snapshot()

    assert matrix.query_payload_matches_fixture(payload, rows_snapshot) is True
    assert matrix.final_query_response_matches(_waapi_result(payload), rows_snapshot) is True
    assert matrix.query_payload_matches_fixture(
        {**payload, "objects": [payload["objects"][0], payload["objects"][0]]},
        rows_snapshot,
    ) is False

    missing_path = r"\Actor-Mixer Hierarchy\Default Work Unit\ProvenMissing"
    missing_snapshot = OracleSnapshot("Q5", MissingPathOracleSnapshot(missing_path))
    assert matrix.query_payload_matches_fixture(
        {"count": 0, "objects": []}, missing_snapshot
    ) is True
    assert matrix.final_query_response_matches(
        _waapi_result({"count": 0, "objects": [], "not_found": missing_path}),
        missing_snapshot,
    ) is True
    assert matrix.final_query_response_matches(
        _waapi_result({"count": 0, "objects": [], "not_found": r"\wrong"}),
        missing_snapshot,
    ) is False


@pytest.mark.parametrize(
    "build_text",
    [
        lambda valid, payload: f"结果如下：{valid}",
        lambda valid, payload: f"{valid}。查询完成",
        lambda valid, payload: f"{valid}\n",
        lambda valid, payload: f"```json\n{valid}\n```",
        lambda valid, payload: _waapi_result({**payload, "explanation": "extra"}),
        lambda valid, payload: _waapi_result({"count": payload["count"]}),
        lambda valid, payload: _waapi_result(
            {
                **payload,
                "objects": [
                    {**payload["objects"][0], "notes": "fabricated"},
                    payload["objects"][1],
                ],
            }
        ),
        lambda valid, payload: _waapi_result(
            {
                **payload,
                "objects": [
                    {
                        key: value
                        for key, value in payload["objects"][0].items()
                        if key != "path"
                    },
                    payload["objects"][1],
                ],
            }
        ),
        lambda valid, payload: _waapi_result(
            {**payload, "objects": [*payload["objects"], payload["objects"][0]]}
        ),
        lambda valid, payload: _waapi_result(
            {
                "count": 3,
                "objects": [
                    *payload["objects"],
                    {
                        "id": "{33333333-3333-3333-3333-333333333333}",
                        "name": "Fabricated",
                        "type": "Sound",
                        "path": r"\Fabricated",
                    },
                ],
            }
        ),
        lambda valid, payload: _waapi_result({**payload, "count": True}),
        lambda valid, payload: valid.replace('"count":2', '"count":2,"count":2', 1),
        lambda valid, payload: valid.replace('"name":"OtherChild"', '"name":"OtherChild","name":"OtherChild"', 1),
        lambda valid, payload: valid.replace('"count":2', '"count":NaN', 1),
        lambda valid, payload: (
            "这些值并不正确："
            + " ".join(
                str(value)
                for row in payload["objects"]
                for value in row.values()
            )
        ),
    ],
    ids=(
        "leading-prose",
        "trailing-prose",
        "trailing-newline",
        "markdown-fence",
        "extra-top-level-key",
        "missing-top-level-key",
        "extra-object-key",
        "missing-object-key",
        "duplicate-object",
        "fabricated-object",
        "boolean-count",
        "duplicate-top-level-key",
        "duplicate-object-key",
        "non-finite-json",
        "negated-prose-with-all-values",
    ),
)
def test_final_query_response_fails_closed_on_adversarial_q1_q4_text(build_text: object) -> None:
    snapshot, payload = _query_rows_snapshot()
    valid = _waapi_result(payload)

    assert callable(build_text)
    assert matrix.final_query_response_matches(build_text(valid, payload), snapshot) is False


@pytest.mark.parametrize(
    "payload",
    [
        {"count": 0, "objects": []},
        {"count": 0, "objects": [], "not_found": r"\wrong"},
        {"count": 0, "objects": [], "not_found": "", "extra": True},
        {
            "count": 1,
            "objects": [
                {
                    "id": "{33333333-3333-3333-3333-333333333333}",
                    "name": "Fabricated",
                    "type": "Sound",
                    "path": r"\Fabricated",
                }
            ],
            "not_found": r"\Actor-Mixer Hierarchy\Default Work Unit\ProvenMissing",
        },
        {
            "count": False,
            "objects": [],
            "not_found": r"\Actor-Mixer Hierarchy\Default Work Unit\ProvenMissing",
        },
    ],
    ids=(
        "missing-not-found",
        "wrong-path",
        "extra-key",
        "fabricated-object",
        "boolean-count",
    ),
)
def test_final_missing_path_response_requires_exact_closed_payload(payload: dict[str, object]) -> None:
    path = r"\Actor-Mixer Hierarchy\Default Work Unit\ProvenMissing"
    snapshot = OracleSnapshot("Q5", MissingPathOracleSnapshot(path))

    assert matrix.final_query_response_matches(_waapi_result(payload), snapshot) is False


def test_final_missing_path_response_rejects_duplicate_keys_and_contradictory_prose() -> None:
    path = r"\Actor-Mixer Hierarchy\Default Work Unit\ProvenMissing"
    snapshot = OracleSnapshot("Q5", MissingPathOracleSnapshot(path))
    valid = _waapi_result({"count": 0, "objects": [], "not_found": path})

    duplicate = valid.replace('"count":0', '"count":0,"count":0', 1)
    assert matrix.final_query_response_matches(duplicate, snapshot) is False
    assert matrix.final_query_response_matches(
        f"{path} 并非不存在；它其实存在。",
        snapshot,
    ) is False
    assert matrix.final_query_response_matches(
        f"{valid} 但它其实存在。",
        snapshot,
    ) is False


def test_query_dispatch_evidence_requires_exactly_one_business_object_get() -> None:
    successful = {"api": matrix.OBJECT_GET_URI, "ok": True}
    auxiliaries = [
        {"api": "ak.wwise.core.getInfo", "ok": True},
        {"api": "ak.wwise.core.getProjectInfo", "ok": True},
    ]

    assert matrix.query_dispatch_evidence_matches(
        case_id="Q1",
        gateway_payload={"ok": True},
        dispatch_rows=[successful],
    ) is True
    assert matrix.query_dispatch_evidence_matches(
        case_id="Q1",
        gateway_payload={"ok": True},
        dispatch_rows=[*auxiliaries, successful],
    ) is True
    assert matrix.query_dispatch_evidence_matches(
        case_id="Q1",
        gateway_payload={"ok": True},
        dispatch_rows=auxiliaries,
    ) is False
    assert matrix.query_dispatch_evidence_matches(
        case_id="Q1",
        gateway_payload={"ok": True},
        dispatch_rows=[successful, dict(successful)],
    ) is False


@pytest.mark.parametrize(
    "rows",
    [
        [{"api": matrix.OBJECT_GET_URI, "ok": False}],
        [
            {"api": matrix.OBJECT_GET_URI, "ok": True},
            {"api": "ak.wwise.core.getInfo", "ok": False},
        ],
        [
            {"api": matrix.OBJECT_GET_URI, "ok": True},
            {"api": "ak.wwise.core.object.set", "ok": True},
        ],
    ],
    ids=("failed-business", "failed-auxiliary", "mutation-api"),
)
def test_query_dispatch_evidence_rejects_failed_or_non_read_only_rows(
    rows: list[dict[str, object]],
) -> None:
    assert matrix.query_dispatch_evidence_matches(
        case_id="Q1",
        gateway_payload={"ok": True},
        dispatch_rows=rows,
    ) is False


def test_query_dispatch_evidence_accepts_only_bound_q5_absence_normalization() -> None:
    gateway, dispatch = _q5_absence_evidence()

    assert matrix.query_dispatch_evidence_matches(
        case_id="Q5",
        gateway_payload=gateway,
        dispatch_rows=[dispatch],
    ) is True

    wrong_source = json.loads(json.dumps(gateway))
    wrong_source["call"]["normalization"]["source"] = "ak.wwise.query.invalid_query"
    assert matrix.query_dispatch_evidence_matches(
        case_id="Q5",
        gateway_payload=wrong_source,
        dispatch_rows=[dispatch],
    ) is False

    wrong_original = json.loads(json.dumps(gateway))
    wrong_original["call"]["normalization"]["original"]["message"] = "different"
    assert matrix.query_dispatch_evidence_matches(
        case_id="Q5",
        gateway_payload=wrong_original,
        dispatch_rows=[dispatch],
    ) is False

    wrong_dispatch = dict(dispatch, waapi_error_uri="ak.wwise.query.unknown_object")
    assert matrix.query_dispatch_evidence_matches(
        case_id="Q5",
        gateway_payload=gateway,
        dispatch_rows=[wrong_dispatch],
    ) is False


def test_q5_compact_and_detail_projections_preserve_absence_proof_for_matcher() -> None:
    gateway, dispatch = _q5_absence_evidence()
    missing_path = r"\Actor-Mixer Hierarchy\Default Work Unit\ProvenMissing"
    step = matrix.build_expected_gateway_steps(
        _session("Q5", "single"),
        {"wwise_version": "2022.1", "missing_path": missing_path},
    )[0]

    assert "--detail" not in step.arguments
    compact = waapi_gateway.project_successful_query_object_payload(
        gateway,
        detail="--detail" in step.arguments,
    )

    assert "call" not in compact
    assert matrix.query_dispatch_evidence_matches(
        case_id="Q5",
        gateway_payload=compact,
        dispatch_rows=[dispatch],
    ) is True
    detail = waapi_gateway.project_successful_query_object_payload(
        gateway,
        detail=True,
    )
    assert detail["call"]["normalization"]["kind"] == "exact-object-absence"
    assert matrix.query_dispatch_evidence_matches(
        case_id="Q5",
        gateway_payload=detail,
        dispatch_rows=[dispatch],
    ) is True


@pytest.mark.parametrize(
    "change",
    [
        lambda payload: payload.update(call={}),
        lambda payload: payload.update(call=None),
        lambda payload: payload.update(status="error"),
        lambda payload: payload.update(command="selected"),
        lambda payload: payload.update(query_bound={"mode": "take", "value": 1}),
        lambda payload: payload.update(count=False),
        lambda payload: payload.update(objects=[{"id": "fabricated"}]),
    ],
    ids=(
        "partial-call",
        "null-call",
        "wrong-status",
        "wrong-command",
        "wrong-bound",
        "boolean-count",
        "nonempty-objects",
    ),
)
def test_q5_compact_absence_rejects_incomplete_call_or_invalid_business_shape(
    change: object,
) -> None:
    gateway, dispatch = _q5_absence_evidence()
    compact = waapi_gateway.project_successful_query_object_payload(gateway, detail=False)
    assert callable(change)
    change(compact)

    assert matrix.query_dispatch_evidence_matches(
        case_id="Q5",
        gateway_payload=compact,
        dispatch_rows=[dispatch],
    ) is False


@pytest.mark.parametrize(
    "dispatch_change",
    [
        {"result": {}},
        {"error_code": "OtherError"},
        {
            "waapi_error_uri": "ak.wwise.query.invalid_query",
            "waapi_error_details": {},
        },
        {
            "waapi_error_uri": "ak.wwise.query.invalid_query",
            "waapi_error_details": {"message": "syntax error"},
        },
        {"evidence_path": ""},
        {"message": ""},
    ],
    ids=(
        "non-null-result",
        "wrong-error-code",
        "missing-error-message",
        "wrong-error-message",
        "missing-evidence-path",
        "missing-dispatch-message",
    ),
)
def test_q5_compact_absence_requires_exact_trusted_dispatch_error(
    dispatch_change: dict[str, object],
) -> None:
    gateway, dispatch = _q5_absence_evidence()
    compact = waapi_gateway.project_successful_query_object_payload(gateway, detail=False)
    dispatch.update(dispatch_change)

    assert matrix.query_dispatch_evidence_matches(
        case_id="Q5",
        gateway_payload=compact,
        dispatch_rows=[dispatch],
    ) is False


def test_q5_compact_absence_accepts_unknown_object_dispatch_variant() -> None:
    gateway, dispatch = _q5_absence_evidence()
    compact = waapi_gateway.project_successful_query_object_payload(gateway, detail=False)
    dispatch.update(
        waapi_error_uri="ak.wwise.query.unknown_object",
        waapi_error_details={"message": "Unknown object"},
    )

    assert matrix.query_dispatch_evidence_matches(
        case_id="Q5",
        gateway_payload=compact,
        dispatch_rows=[dispatch],
    ) is True


def test_transaction_final_response_contract_is_exact_strict_json_with_request_echo() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.setProperty",
        "arguments": {
            "object": {
                "kind": "path",
                "value": '\\Actor-Mixer Hierarchy\\中文“弦乐”\\object "quoted"',
            },
            "property": "Volume",
            "value": -3.0,
        },
    }
    transaction_id = "tx-final-contract"
    artifact_hash = "a" * 64
    preview = {
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "preview_summary": {"request": request},
        "agent_result": {
            "operation": "object.setProperty",
            "transaction_id": transaction_id,
            "artifact_hash": artifact_hash,
            "state": "awaiting_confirmation",
            "executed": False,
            "request": request,
        },
    }
    preview_final = _waapi_result(
        {
            "operation": "object.setProperty",
            "transaction_id": transaction_id,
            "artifact_hash": artifact_hash,
            "state": "awaiting_confirmation",
            "executed": False,
            "request": request,
        }
    )
    confirm_final = _waapi_result(
        {
            "operation": "object.setProperty",
            "transaction_id": transaction_id,
            "artifact_hash": artifact_hash,
            "state": "verified",
            "executed": True,
            "verified": True,
            "request": request,
        }
    )
    verify = {
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "state": "verified",
        "executed": True,
        "verified": True,
        "agent_result": json.loads(confirm_final.split("=", 1)[1]),
    }

    assert matrix.final_preview_response_matches(
        preview_final, preview, "object.setProperty", request
    )
    assert matrix.final_confirm_response_matches(
        confirm_final, verify, transaction_id, artifact_hash, "object.setProperty", request
    )
    assert type(json.loads(preview_final.split("=", 1)[1])["request"]["arguments"]["value"]) is float

    tampered_preview = json.loads(json.dumps(preview, ensure_ascii=False))
    tampered_preview["agent_result"]["request"]["arguments"]["property"] = "Pitch"
    assert not matrix.final_preview_response_matches(
        preview_final,
        tampered_preview,
        "object.setProperty",
        request,
    )
    tampered_verify = json.loads(json.dumps(verify, ensure_ascii=False))
    tampered_verify["agent_result"]["artifact_hash"] = "f" * 64
    assert not matrix.final_confirm_response_matches(
        confirm_final,
        tampered_verify,
        transaction_id,
        artifact_hash,
        "object.setProperty",
        request,
    )

    for invalid in (
        "prefix " + preview_final,
        preview_final + "\nextra",
        preview_final.replace('"executed":false', '"executed":"false"'),
        preview_final[:-1] + ',"extra":true}',
        preview_final.replace('"value":-3.0', '"value":"-3.0"'),
        preview_final.replace('"value":-3.0', '"value":-3'),
        preview_final[:-1],
    ):
        assert not matrix.final_preview_response_matches(
            invalid, preview, "object.setProperty", request
        )


def test_transaction_final_response_rejects_wrong_binding_and_duplicate_json_keys() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.delete",
        "arguments": {"object": {"kind": "path", "value": r"\DeleteTarget"}},
    }
    transaction_id = "tx-delete"
    artifact_hash = "b" * 64
    valid = _waapi_result(
        {
            "operation": "object.delete",
            "transaction_id": transaction_id,
            "artifact_hash": artifact_hash,
            "state": "verified",
            "executed": True,
            "verified": True,
            "request": request,
        }
    )
    verify = {
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "state": "verified",
        "executed": True,
        "verified": True,
        "agent_result": json.loads(valid.split("=", 1)[1]),
    }
    assert matrix.final_confirm_response_matches(
        valid, verify, transaction_id, artifact_hash, "object.delete", request
    )
    assert not matrix.final_confirm_response_matches(
        valid, verify, transaction_id, "c" * 64, "object.delete", request
    )
    duplicate = (
        'WAAPI_RESULT_JSON={"operation":"object.delete","operation":"object.create",'
        f'"transaction_id":"{transaction_id}","artifact_hash":"{artifact_hash}",'
        '"state":"verified","executed":true,"verified":true,"request":'
        + json.dumps(request, separators=(",", ":"))
        + "}"
    )
    assert not matrix.final_confirm_response_matches(
        duplicate, verify, transaction_id, artifact_hash, "object.delete", request
    )


def test_transaction_journal_counts_only_successful_matching_execution(tmp_path: Path) -> None:
    transaction_id = "tx-123"
    mutation_uri = "ak.wwise.core.object.setNotes"
    journal = tmp_path / "transactions" / transaction_id / "events.jsonl"
    journal.parent.mkdir(parents=True)
    rows = (
        {"event_type": "transaction_created", "details": {}},
        {
            "event_type": "execution_completed",
            "details": {"dispatch_result": {"ok": False, "api": mutation_uri}},
        },
        {
            "event_type": "execution_completed",
            "details": {"dispatch_result": {"ok": True, "api": "ak.wwise.core.object.get"}},
        },
        {
            "event_type": "execution_completed",
            "details": {"dispatch_result": {"ok": True, "api": mutation_uri}},
        },
    )
    journal.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    assert matrix.count_journal_mutation(tmp_path, transaction_id, mutation_uri) == 1


def test_transaction_journal_rejects_missing_or_malformed_evidence(tmp_path: Path) -> None:
    with pytest.raises(matrix.FixtureContractError, match="not a regular file"):
        matrix.count_journal_mutation(tmp_path, "missing", "ak.wwise.core.object.setNotes")

    journal = tmp_path / "transactions" / "tx" / "events.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(matrix.FixtureContractError, match="invalid transaction journal line 1"):
        matrix.count_journal_mutation(tmp_path, "tx", "ak.wwise.core.object.setNotes")


def test_trusted_gateway_environment_removes_only_ambient_waapi_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WWISE_VERSION", "ambient-version")
    monkeypatch.setenv("WAAPI_SKILL_STATE_DIR", "/ambient/state")
    monkeypatch.setenv("BASH_ENV", "/ambient/bash-env")
    monkeypatch.setenv("SEMANTIC_MATRIX_KEEP", "preserved")

    environment = matrix.trusted_gateway_environment()

    assert "WWISE_VERSION" not in environment
    assert "WAAPI_SKILL_STATE_DIR" not in environment
    assert "BASH_ENV" not in environment
    assert environment["SEMANTIC_MATRIX_KEEP"] == "preserved"
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"

    trusted = matrix.trusted_gateway_environment(
        {"WWISE_VERSION": "2025.1", "WWISE_WAAPI_PORT": 12345}
    )
    assert trusted["WWISE_VERSION"] == "2025.1"
    assert trusted["WWISE_WAAPI_PORT"] == "12345"


def test_prepare_agent_workspace_uses_detached_copy_on_native_windows(tmp_path: Path) -> None:
    source = tmp_path / "waapi-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
    (source / ".venv").mkdir()
    (source / ".venv" / "python.exe").write_bytes(b"excluded runtime")
    workspace = tmp_path / "workspace"

    install = matrix.prepare_agent_workspace(
        workspace,
        source,
        platform_name="nt",
    )

    assert install.is_dir() and not install.is_symlink()
    assert (install / "SKILL.md").read_text(encoding="utf-8") == "skill\n"
    assert not (install / ".venv").exists()
    assert not os.path.samefile(source / "SKILL.md", install / "SKILL.md")


@pytest.mark.parametrize(
    ("runner_oracle", "oracle_factory"),
    [
        (None, None),
        ({"offline_no_wwise": True}, lambda _observation: {"offline_no_wwise": True}),
    ],
)
def test_run_fresh_phase_requires_exactly_one_oracle_source_before_side_effects(
    runner_oracle: object,
    oracle_factory: object,
) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        matrix.run_fresh_phase(
            _session("C1", "single"),
            values={},
            runner_oracle=runner_oracle,  # type: ignore[arg-type]
            oracle_factory=oracle_factory,  # type: ignore[arg-type]
            options=object(),  # type: ignore[arg-type]
            runner_environment={},
        )


@pytest.mark.parametrize(
    ("failure_point", "expected_stage"),
    [
        ("harness", "harness-run"),
        ("broker", "broker-reconciliation"),
        ("oracle", "runner-oracle"),
        ("grader", "grader"),
    ],
)
def test_run_fresh_phase_archives_raw_evidence_for_each_failure_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
    expected_stage: str,
) -> None:
    result = _fake_codex_result()

    class FakeHarness:
        def __init__(self, _config: object) -> None:
            pass

        def run(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            if failure_point == "harness":
                raise RuntimeError("synthetic harness failure")
            return result

    monkeypatch.setattr(matrix, "CodexCliHarness", FakeHarness)
    if failure_point == "broker":
        monkeypatch.setattr(
            matrix.CodexGatewayBroker,
            "reconcile",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic broker failure")),
        )
    if failure_point == "grader":
        monkeypatch.setattr(
            matrix,
            "grade_eval_session",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic grader failure")),
        )

    def oracle_factory(_observation: object) -> dict[str, bool]:
        if failure_point == "oracle":
            raise RuntimeError("synthetic oracle failure")
        return {"offline_no_wwise": True}

    session = _session("C1", "single")
    options = _runner_options(tmp_path / "iteration")
    with pytest.raises(RuntimeError, match=f"synthetic {failure_point} failure"):
        matrix.run_fresh_phase(
            session,
            values={},
            oracle_factory=oracle_factory,
            options=options,
            runner_environment={},
        )

    output_dir = options.iteration_root / "sessions" / matrix.safe_session_name(session.session_id) / "outputs"
    phase_error = json.loads((output_dir / "phase-error.json").read_text(encoding="utf-8"))
    phase = json.loads((output_dir / "phase.json").read_text(encoding="utf-8"))
    snapshots = json.loads((output_dir / "private-directory-snapshots.json").read_text(encoding="utf-8"))

    assert phase_error["stage"] == expected_stage
    assert phase_error["exception_type"] == "RuntimeError"
    assert phase["passed"] is False
    assert phase["grade_passed"] is False
    assert (output_dir / "prompt.txt").read_text(encoding="utf-8").strip()
    assert (output_dir / "broker-evidence-raw.json").is_file()
    assert snapshots["state"]["available"] is True
    assert snapshots["evidence"]["available"] is True
    if failure_point == "harness":
        assert phase_error["harness_result_available"] is False
        assert not (output_dir / "harness-result-raw.json").exists()
    else:
        assert phase_error["harness_result_available"] is True
        assert (output_dir / "harness-result-raw.json").is_file()
    if failure_point in {"oracle", "grader"}:
        assert phase_error["reconciliation_available"] is True
        assert (output_dir / "broker-reconciliation.json").is_file()


def test_pre_action_codex_infrastructure_failure_skips_grading_and_archives_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _fake_codex_result()
    failure = CodexInfrastructureFailure(
        category="quota_or_rate_limit",
        message="You've hit your usage limit.",
        turn_failed=True,
        timed_out=False,
        agent_item_event_count=0,
    )

    class FakeHarness:
        def __init__(self, _config: object) -> None:
            pass

        def run(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            raise CodexInfrastructureError(failure, result)  # type: ignore[arg-type]

    monkeypatch.setattr(matrix, "CodexCliHarness", FakeHarness)
    monkeypatch.setattr(
        matrix,
        "grade_eval_session",
        lambda *_args, **_kwargs: pytest.fail("infrastructure failures must not enter Skill grading"),
    )
    session = _session("C1", "single")
    options = _runner_options(tmp_path / "iteration")

    with pytest.raises(CodexInfrastructureError, match="usage limit"):
        matrix.run_fresh_phase(
            session,
            values={},
            runner_oracle={"offline_no_wwise": True},
            options=options,
            runner_environment={},
        )

    output_dir = options.iteration_root / "sessions" / matrix.safe_session_name(session.session_id) / "outputs"
    phase_error = json.loads((output_dir / "phase-error.json").read_text(encoding="utf-8"))
    phase = json.loads((output_dir / "phase.json").read_text(encoding="utf-8"))

    assert phase_error["stage"] == "codex-cli-infrastructure"
    assert phase_error["failure_class"] == "infrastructure"
    assert phase_error["infrastructure_failure"] == {
        "agent_item_event_count": 0,
        "category": "quota_or_rate_limit",
        "message": "You've hit your usage limit.",
        "timed_out": False,
        "turn_failed": True,
    }
    assert phase_error["harness_result_available"] is True
    assert phase["failure_class"] == "infrastructure"
    assert (output_dir / "harness-result-raw.json").is_file()
    assert not (output_dir / "grading.json").exists()


def test_r5_publisher_aborts_before_transaction_on_runner_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session("R5", "single")
    publish_called = threading.Event()
    probe_name = "WAAPI_SEM_TOPIC_2022_1_abortbeforestart"
    bundle = SimpleNamespace(
        prompt_values=lambda *_args, **_kwargs: {"topic_probe_name": probe_name},
        publish_object_created_probe=lambda _name: publish_called.set(),
    )

    def fail_after_publisher_hook(*_args: object, **kwargs: object) -> object:
        hook = kwargs["trusted_step_pre_observer"]
        assert callable(hook)
        hook(
            matrix.ExpectedGatewayStep("wait-topic", "topic-wait"),
            tmp_path / "state",
            tmp_path / "evidence",
        )
        raise TimeoutError("synthetic Codex runner timeout")

    monkeypatch.setattr(matrix, "TOPIC_SUBSCRIPTION_SETTLE_SECONDS", 30.0)
    monkeypatch.setattr(matrix, "TOPIC_PUBLISHER_JOIN_SECONDS", 1.0)
    monkeypatch.setattr(matrix, "run_fresh_phase", fail_after_publisher_hook)

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="synthetic Codex runner timeout"):
        matrix.run_live_fixed_read_phase(
            session,
            bundle=bundle,  # type: ignore[arg-type]
            options=_runner_options(tmp_path / "iteration"),
            runner_environment={},
        )

    assert time.monotonic() - started < 1.0
    assert publish_called.is_set() is False


def test_r5_publisher_deadline_failure_drains_in_flight_transaction_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session("R5", "single")
    transaction_started = threading.Event()
    release_transaction = threading.Event()
    transaction_finished = threading.Event()
    probe_name = "WAAPI_SEM_TOPIC_2022_1_draininflight"

    def publish_probe(_name: str) -> dict[str, object]:
        transaction_started.set()
        assert release_transaction.wait(timeout=2.0)
        transaction_finished.set()
        return {"created": True, "deleted": True}

    bundle = SimpleNamespace(
        prompt_values=lambda *_args, **_kwargs: {"topic_probe_name": probe_name},
        publish_object_created_probe=publish_probe,
    )

    def fail_with_active_publisher(*_args: object, **kwargs: object) -> object:
        hook = kwargs["trusted_step_pre_observer"]
        assert callable(hook)
        hook(
            matrix.ExpectedGatewayStep("wait-topic", "topic-wait"),
            tmp_path / "state",
            tmp_path / "evidence",
        )
        assert transaction_started.wait(timeout=1.0)
        raise RuntimeError("synthetic runner failure")

    monkeypatch.setattr(matrix, "TOPIC_SUBSCRIPTION_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(matrix, "TOPIC_PUBLISHER_JOIN_SECONDS", 0.01)
    monkeypatch.setattr(matrix, "run_fresh_phase", fail_with_active_publisher)
    release_timer = threading.Timer(0.08, release_transaction.set)
    release_timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="synthetic runner failure") as raised:
            matrix.run_live_fixed_read_phase(
                session,
                bundle=bundle,  # type: ignore[arg-type]
                options=_runner_options(tmp_path / "iteration"),
                runner_environment={},
            )
    finally:
        release_transaction.set()
        release_timer.join(timeout=1.0)

    assert time.monotonic() - started >= 0.05
    assert transaction_finished.is_set() is True
    notes = getattr(raised.value, "__notes__", ())
    assert any("drained before version teardown" in note for note in notes)


def test_r5_unobserved_publisher_failure_is_attached_after_safe_join(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session("R5", "single")
    publisher_finished = threading.Event()
    probe_name = "WAAPI_SEM_TOPIC_2022_1_publishfailure"

    def fail_publisher(_name: str) -> object:
        try:
            raise ValueError("synthetic publisher failure")
        finally:
            publisher_finished.set()

    bundle = SimpleNamespace(
        prompt_values=lambda *_args, **_kwargs: {"topic_probe_name": probe_name},
        publish_object_created_probe=fail_publisher,
    )

    def fail_after_publisher(*_args: object, **kwargs: object) -> object:
        hook = kwargs["trusted_step_pre_observer"]
        assert callable(hook)
        hook(
            matrix.ExpectedGatewayStep("wait-topic", "topic-wait"),
            tmp_path / "state",
            tmp_path / "evidence",
        )
        assert publisher_finished.wait(timeout=1.0)
        raise TimeoutError("synthetic runner timeout")

    monkeypatch.setattr(matrix, "TOPIC_SUBSCRIPTION_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(matrix, "TOPIC_PUBLISHER_JOIN_SECONDS", 1.0)
    monkeypatch.setattr(matrix, "run_fresh_phase", fail_after_publisher)

    with pytest.raises(TimeoutError, match="synthetic runner timeout") as raised:
        matrix.run_live_fixed_read_phase(
            session,
            bundle=bundle,  # type: ignore[arg-type]
            options=_runner_options(tmp_path / "iteration"),
            runner_environment={},
        )

    notes = getattr(raised.value, "__notes__", ())
    assert any(
        "R5 topic publisher failed: ValueError: synthetic publisher failure" in note
        for note in notes
    )


@pytest.mark.parametrize(
    ("failure_point", "expected_stage"),
    [
        ("binding", "preview-binding"),
        ("request", "preview-request-binding"),
        ("seal", "preview-seal-create"),
    ],
)
def test_preview_pair_postprocessing_failure_overrides_pass_and_is_archived(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
    expected_stage: str,
) -> None:
    session = _session("M1", "preview")
    values = {
        "wwise_version": session.version,
        "target_path": r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticNotesTarget",
        "notes_value": "semantic-notes-value",
    }
    payload: dict[str, object] = {
        "transaction_id": "tx-preview-123",
        "artifact_hash": "a" * 64,
        "state": matrix.TransactionState.AWAITING_CONFIRMATION.value,
        "executed": False,
        "verified": False,
        "preview_summary": {"request": session.render_request(values)},
    }
    if failure_point == "binding":
        payload = {}
    elif failure_point == "request":
        payload["preview_summary"] = {"request": {"wrong": True}}

    phase_root = tmp_path / "iteration" / "sessions" / matrix.safe_session_name(session.session_id)
    (phase_root / "outputs").mkdir(parents=True)
    state_directory = phase_root / "broker" / "state"
    evidence_directory = phase_root / "broker" / "evidence"
    state_directory.mkdir(parents=True)
    evidence_directory.mkdir(parents=True)
    evidence = _FakeBrokerEvidence((_record("preview", payload),))
    execution = matrix.PhaseExecution(
        session=session,
        values=values,
        result=_fake_codex_result(),  # type: ignore[arg-type]
        broker_evidence=evidence,  # type: ignore[arg-type]
        reconciliation=matrix.GatewayBrokerReconciliation(
            passed=True,
            observed_command_count=1,
            accepted_record_count=1,
            errors=(),
        ),
        runner_oracle={"transaction_state": matrix.TransactionState.AWAITING_CONFIRMATION.value},
        grade=_FakeGrade(),  # type: ignore[arg-type]
        phase_root=phase_root,
        state_directory=state_directory,
        evidence_directory=evidence_directory,
    )
    monkeypatch.setattr(matrix, "run_fresh_phase", lambda *_args, **_kwargs: execution)
    if failure_point == "seal":
        monkeypatch.setattr(
            matrix,
            "create_preview_seal",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic seal failure")),
        )
    bundle = SimpleNamespace(
        prompt_values=lambda *_args, **_kwargs: values,
        snapshot=lambda *_args, **_kwargs: object(),
    )

    failed, pair = matrix.run_live_preview_phase(
        session,
        bundle=bundle,  # type: ignore[arg-type]
        options=_runner_options(tmp_path / "iteration"),
        runner_environment={},
        needs_confirm=True,
    )

    assert pair is None
    assert failed.grade.passed is True
    assert failed.passed is False
    assert f"[{expected_stage}]" in failed.error
    phase = json.loads((phase_root / "outputs" / "phase.json").read_text(encoding="utf-8"))
    phase_error = json.loads((phase_root / "outputs" / "phase-error.json").read_text(encoding="utf-8"))
    assert phase["passed"] is False
    assert phase["grade_passed"] is True
    assert phase_error["stage"] == expected_stage


def test_main_writes_failed_summary_when_offline_phase_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_skill_root = tmp_path / "skills" / "waapi-skill"
    fake_skill_root.mkdir(parents=True)
    iteration_root = fake_skill_root.parent / "waapi-skill-workspace" / "offline-failure"
    session = _session("C1", "single")
    options = replace(_runner_options(iteration_root), pair_ids=(session.pair_id,))
    suite = SimpleNamespace(expand_profile=lambda _profile: (session,))
    monkeypatch.setattr(matrix, "SKILL_ROOT", fake_skill_root)
    monkeypatch.setattr(matrix, "parse_args", lambda _argv=None: options)
    monkeypatch.setattr(matrix, "load_eval_suite", lambda _path: suite)
    monkeypatch.setattr(
        matrix,
        "require_live_runner_dependencies",
        lambda: pytest.fail("pure offline selections must not import the live WAAPI dependency"),
    )
    monkeypatch.setattr(
        matrix,
        "run_fresh_phase",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline exploded")),
    )

    assert matrix.main([]) == 1
    run_config = json.loads((iteration_root / "run-config.json").read_text(encoding="utf-8"))
    summary = json.loads((iteration_root / "summary.json").read_text(encoding="utf-8"))
    assert run_config["pair_ids"] == [session.pair_id]
    assert summary["executed_session_count"] == 1
    assert summary["executed_session_ids"] == [session.session_id]
    assert summary["failed_session_ids"] == [session.session_id]
    assert summary["pending_session_ids"] == []
    assert summary["all_selected_passed"] is False
    assert "offline exploded" in summary["run_errors"][0]


def test_main_live_preflight_fails_before_offline_codex_or_wwise_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_skill_root = tmp_path / "skills" / "waapi-skill"
    fake_skill_root.mkdir(parents=True)
    iteration_root = fake_skill_root.parent / "waapi-skill-workspace" / "preflight-failure"
    options = _runner_options(iteration_root)
    offline_session = _session("C1", "single")
    live_session = _session("Q1", "single")
    suite = SimpleNamespace(expand_profile=lambda _profile: (offline_session, live_session))
    monkeypatch.setattr(matrix, "SKILL_ROOT", fake_skill_root)
    monkeypatch.setattr(matrix, "parse_args", lambda _argv=None: options)
    monkeypatch.setattr(matrix, "load_eval_suite", lambda _path: suite)

    def fail_preflight() -> dict[str, object]:
        raise matrix.LiveDependencyPreflightError(
            exception_type="ModuleNotFoundError",
            exception_message="No module named 'waapi'",
        )

    monkeypatch.setattr(matrix, "require_live_runner_dependencies", fail_preflight)
    monkeypatch.setattr(
        matrix,
        "run_fresh_phase",
        lambda *_args, **_kwargs: pytest.fail("offline Codex must not run after live preflight failure"),
    )
    monkeypatch.setattr(
        matrix,
        "run_live_version_sessions",
        lambda *_args, **_kwargs: pytest.fail("Wwise lifecycle must not start after live preflight failure"),
    )

    assert matrix.main([]) == 1

    summary = json.loads((iteration_root / "summary.json").read_text(encoding="utf-8"))
    preflight = json.loads((iteration_root / "live-preflight.json").read_text(encoding="utf-8"))
    assert summary["executed_session_count"] == 0
    assert summary["failed_session_ids"] == []
    assert summary["pending_session_ids"] == [offline_session.session_id, live_session.session_id]
    assert "live-dependency-preflight" in summary["run_errors"][0]
    assert preflight["contract"] == matrix.LIVE_DEPENDENCY_PREFLIGHT_CONTRACT
    assert preflight["ok"] is False
    assert preflight["automatic_install_attempted"] is False
    assert str(matrix.skill_venv_python()) in capsys.readouterr().out


def test_main_accounts_live_postprocess_failure_as_executed_failed_not_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_skill_root = tmp_path / "skills" / "waapi-skill"
    fake_skill_root.mkdir(parents=True)
    iteration_root = fake_skill_root.parent / "waapi-skill-workspace" / "live-postprocess-failure"
    options = _runner_options(iteration_root)
    session = _session("M1", "preview")
    confirm_session = _session("M1", "confirm")
    phase_root = tmp_path / "synthetic-phase"
    state_directory = phase_root / "broker" / "state"
    evidence_directory = phase_root / "broker" / "evidence"
    state_directory.mkdir(parents=True)
    evidence_directory.mkdir(parents=True)
    failed_execution = matrix.PhaseExecution(
        session=session,
        values={},
        result=_fake_codex_result(),  # type: ignore[arg-type]
        broker_evidence=_FakeBrokerEvidence(()),  # type: ignore[arg-type]
        reconciliation=matrix.GatewayBrokerReconciliation(False, 0, 0, ("postprocess",)),
        runner_oracle={},
        grade=_FakeGrade(),  # type: ignore[arg-type]
        phase_root=phase_root,
        state_directory=state_directory,
        evidence_directory=evidence_directory,
        error="[preview-seal-create] synthetic postprocess failure",
    )
    outcome = matrix.VersionRunOutcome(
        executions=(failed_execution,),
        attempted_session_ids=(session.session_id,),
        failed_session_ids=(session.session_id,),
        error=failed_execution.error,
    )
    suite = SimpleNamespace(expand_profile=lambda _profile: (session, confirm_session))
    monkeypatch.setattr(matrix, "SKILL_ROOT", fake_skill_root)
    monkeypatch.setattr(matrix, "parse_args", lambda _argv=None: options)
    monkeypatch.setattr(matrix, "load_eval_suite", lambda _path: suite)
    monkeypatch.setattr(
        matrix,
        "require_live_runner_dependencies",
        lambda: {"contract": matrix.LIVE_DEPENDENCY_PREFLIGHT_CONTRACT, "ok": True},
    )
    monkeypatch.setattr(matrix, "run_live_version_sessions", lambda *_args, **_kwargs: outcome)

    assert matrix.main([]) == 1
    summary = json.loads((iteration_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["executed_session_count"] == 1
    assert summary["executed_session_ids"] == [session.session_id]
    assert summary["failed_session_ids"] == [session.session_id]
    assert summary["pending_session_ids"] == [confirm_session.session_id]
    assert summary["passed_session_count"] == 0
    assert summary["run_errors"] == [failed_execution.error]


def test_prepare_iteration_root_never_deletes_workspace_root_and_requires_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_skill_root = tmp_path / "skills" / "waapi-skill"
    fake_skill_root.mkdir(parents=True)
    workspace_root = fake_skill_root.parent / "waapi-skill-workspace"
    workspace_root.mkdir()
    sentinel = workspace_root / "keep.txt"
    sentinel.write_text("do not delete", encoding="utf-8")
    monkeypatch.setattr(matrix, "SKILL_ROOT", fake_skill_root)

    with pytest.raises(SystemExit, match="workspace root itself"):
        matrix.prepare_iteration_root(workspace_root, overwrite=True)
    assert sentinel.read_text(encoding="utf-8") == "do not delete"

    unmarked = workspace_root / "unmarked"
    unmarked.mkdir()
    with pytest.raises(SystemExit, match="unmarked directory"):
        matrix.prepare_iteration_root(unmarked, overwrite=True)
    assert unmarked.is_dir()

    marked = workspace_root / "marked-run"
    matrix.prepare_iteration_root(marked, overwrite=False)
    assert matrix.valid_iteration_marker(
        marked / matrix.ITERATION_MARKER_FILE,
        expected_root=marked,
    )
    (marked / "replace-me.txt").write_text("old", encoding="utf-8")
    matrix.prepare_iteration_root(marked, overwrite=True)
    assert not (marked / "replace-me.txt").exists()
    assert matrix.valid_iteration_marker(
        marked / matrix.ITERATION_MARKER_FILE,
        expected_root=marked,
    )


def test_live_version_uses_global_lock_but_iteration_private_sandbox_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session("Q1", "single")
    options = _runner_options(tmp_path / "iteration")
    options.iteration_root.mkdir()
    observed: dict[str, Path] = {}

    class FakeLock:
        def __init__(self, root: Path) -> None:
            observed["lock_root"] = root
            self.root = root
            self.path = root / ".wwise-live-sandbox.lock"

        def __enter__(self) -> "FakeLock":
            return self

        def __exit__(self, *_args: object) -> None:
            pass

    monkeypatch.setattr(matrix, "LiveSandboxLock", FakeLock)
    monkeypatch.setattr(
        matrix,
        "require_live_environment",
        lambda _env: SimpleNamespace(version=session.version, sample_project_source=Path("/sample/project.wproj")),
    )

    def fail_after_capturing_root(
        _env: object,
        *,
        sandbox_root: Path,
        hash_strategy: str,
    ) -> object:
        observed["sandbox_root"] = sandbox_root
        assert hash_strategy == "full"
        raise RuntimeError("stop before real Wwise launch")

    monkeypatch.setattr(matrix, "prepare_sample_project_sandbox", fail_after_capturing_root)

    outcome = matrix.run_live_version_sessions((session,), options=options)

    assert observed["lock_root"] == matrix.GLOBAL_LIVE_LIFECYCLE_LOCK_ROOT
    assert observed["sandbox_root"] == options.iteration_root / "versions" / session.version / "sandbox-root"
    assert observed["lock_root"] != observed["sandbox_root"]
    assert "stop before real Wwise launch" in outcome.error


def test_live_version_binds_fixture_gateway_to_evaluated_skill_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session("Q1", "single")
    skill_source = tmp_path / "evaluated-skill"
    runner = skill_source / "scripts" / "run.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# evaluated runner\n", encoding="utf-8")
    options = replace(
        _runner_options(tmp_path / "iteration"),
        skill_source=skill_source.resolve(),
    )
    options.iteration_root.mkdir()
    source_project = tmp_path / "source" / "SampleProject.wproj"
    source_project.parent.mkdir()
    source_project.write_text("source\n", encoding="utf-8")
    sandbox_path = tmp_path / "sandbox"
    sandbox_path.mkdir()
    sandbox_project = sandbox_path / "SampleProject.wproj"
    sandbox_project.write_text("sandbox\n", encoding="utf-8")
    metadata = SimpleNamespace(keep_decision="pending")
    sandbox = SimpleNamespace(
        source_root=source_project.parent,
        source_project=source_project,
        sandbox_root=sandbox_path.parent,
        sandbox_path=sandbox_path,
        sandbox_project=sandbox_project,
        env={},
        metadata=metadata,
        write_metadata=lambda: None,
    )
    lifecycle = SimpleNamespace(
        host="127.0.0.1",
        port=8122,
        command=[str(sandbox_project)],
    )
    project_hash = matrix.ProjectHash("sha256", "full", "0" * 64, 1, 7)
    captured: dict[str, object] = {}

    class FakeLock:
        def __init__(self, root: Path) -> None:
            self.path = root / ".wwise-live-sandbox.lock"

        def __enter__(self) -> "FakeLock":
            return self

        def __exit__(self, *_args: object) -> None:
            pass

    monkeypatch.setattr(matrix, "LiveSandboxLock", FakeLock)
    monkeypatch.setattr(matrix, "live_version_environment", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        matrix,
        "require_live_environment",
        lambda _env: SimpleNamespace(version=session.version, sample_project_source=source_project),
    )
    monkeypatch.setattr(matrix, "prepare_sample_project_sandbox", lambda *_args, **_kwargs: sandbox)
    monkeypatch.setattr(matrix, "hash_project", lambda *_args, **_kwargs: project_hash)
    monkeypatch.setattr(matrix, "launch_sandboxed_wwise", lambda *_args, **_kwargs: lifecycle)
    monkeypatch.setattr(matrix, "shutdown_sandboxed_wwise", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(matrix, "asdict", lambda value: {"type": type(value).__name__})

    def capture_fixture_binding(**kwargs: object) -> object:
        captured.update(kwargs)
        raise RuntimeError("stop after fixture binding")

    monkeypatch.setattr(matrix, "create_shared_fixture_bundle", capture_fixture_binding)

    outcome = matrix.run_live_version_sessions((session,), options=options)

    binding = captured["packaged_gateway_binding"]
    assert isinstance(binding, matrix.PackagedGatewayBinding)
    assert binding.skill_root == skill_source.resolve()
    assert binding.runner_path == runner.resolve()
    assert "stop after fixture binding" in outcome.error


@pytest.mark.parametrize(
    "runner_error",
    [
        RuntimeError("synthetic runner failure"),
        TimeoutError("synthetic runner timeout"),
    ],
    ids=("failure", "timeout"),
)
def test_live_version_runner_failure_teardown_order_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_error: BaseException,
) -> None:
    session = _session("Q1", "single")
    options = _runner_options(tmp_path / "iteration")
    options.iteration_root.mkdir()
    events: list[str] = []

    source_project = tmp_path / "source" / "SampleProject.wproj"
    source_project.parent.mkdir()
    source_project.write_text("immutable source\n", encoding="utf-8")
    sandbox_path = tmp_path / "sandbox"
    sandbox_path.mkdir()
    sandbox_project = sandbox_path / "SampleProject.wproj"
    sandbox_project.write_text("sandbox\n", encoding="utf-8")
    metadata = SimpleNamespace(keep_decision="pending")

    def retain_sandbox() -> None:
        events.append("sandbox-retention")

    sandbox = SimpleNamespace(
        source_root=source_project.parent,
        source_project=source_project,
        sandbox_root=sandbox_path.parent,
        sandbox_path=sandbox_path,
        sandbox_project=sandbox_project,
        env={},
        metadata=metadata,
        write_metadata=retain_sandbox,
    )
    lifecycle = SimpleNamespace(
        host="127.0.0.1",
        port=8122,
        command=[str(sandbox_project)],
    )
    project_hash = matrix.ProjectHash("sha256", "full", "0" * 64, 1, 7)
    hash_calls = 0

    def record_hash(*_args: object, **_kwargs: object) -> matrix.ProjectHash:
        nonlocal hash_calls
        hash_calls += 1
        if hash_calls == 2:
            events.append("source-proof")
        return project_hash

    class FakeLock:
        def __init__(self, root: Path) -> None:
            self.path = root / ".wwise-live-sandbox.lock"

        def __enter__(self) -> "FakeLock":
            events.append("lock-acquire")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append("lock-release")

    class FakeBundle:
        transactions: tuple[object, ...] = ()

        @staticmethod
        def cleanup() -> None:
            events.append("fixture-cleanup")

    monkeypatch.setattr(matrix, "LiveSandboxLock", FakeLock)
    monkeypatch.setattr(matrix, "live_version_environment", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        matrix,
        "require_live_environment",
        lambda _env: SimpleNamespace(version=session.version, sample_project_source=source_project),
    )
    monkeypatch.setattr(matrix, "prepare_sample_project_sandbox", lambda *_args, **_kwargs: sandbox)
    monkeypatch.setattr(matrix, "hash_project", record_hash)
    monkeypatch.setattr(matrix, "launch_sandboxed_wwise", lambda *_args, **_kwargs: lifecycle)
    monkeypatch.setattr(matrix, "create_shared_fixture_bundle", lambda **_kwargs: FakeBundle())
    monkeypatch.setattr(
        matrix,
        "run_live_query_phase",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(runner_error),
    )
    monkeypatch.setattr(
        matrix,
        "shutdown_sandboxed_wwise",
        lambda *_args, **_kwargs: events.append("wwise-shutdown"),
    )
    monkeypatch.setattr(
        matrix,
        "cleanup_sandbox",
        lambda *_args, **_kwargs: pytest.fail("failed versions must retain their sandbox"),
    )
    original_asdict = matrix.asdict
    monkeypatch.setattr(
        matrix,
        "asdict",
        lambda value: (
            {"keep_decision": value.keep_decision}
            if value is metadata
            else original_asdict(value)
        ),
    )

    outcome = matrix.run_live_version_sessions((session,), options=options)

    assert events[-5:] == [
        "fixture-cleanup",
        "wwise-shutdown",
        "source-proof",
        "sandbox-retention",
        "lock-release",
    ]
    assert outcome.failed_session_ids == (session.session_id,)
    assert str(runner_error) in outcome.error
    runtime = json.loads(
        (options.iteration_root / "versions" / session.version / "runtime.json").read_text(
            encoding="utf-8"
        )
    )
    assert runtime["sandbox_retained"] is True
    assert runtime["sandbox_metadata"]["keep_decision"] == (
        "retained-in-iteration-root-for-semantic-failure"
    )
    assert str(runner_error) in "\n".join(runtime["errors"])


def test_live_version_group_rejects_mixed_versions_before_creating_runtime() -> None:
    sessions = (
        _session("Q1", "single", version="2021.1"),
        _session("Q1", "single", version="2022.1"),
    )

    with pytest.raises(ValueError, match="one supported version"):
        matrix.run_live_version_sessions(sessions, options=object())  # type: ignore[arg-type]


def test_live_version_group_rejects_offline_case_before_creating_runtime() -> None:
    with pytest.raises(ValueError, match="offline semantic cases"):
        matrix.run_live_version_sessions(
            (_session("B1", "single"),),
            options=object(),  # type: ignore[arg-type]
        )


def test_full_profile_groups_versions_sequentially_and_keeps_pair_phase_order() -> None:
    sessions = _suite().expand_profile("full_cross_version_168")
    live = tuple(session for session in sessions if session.case.id not in matrix.OFFLINE_CASE_IDS)
    groups = tuple(
        tuple(session for session in live if session.version == version)
        for version in matrix.SUPPORTED_VERSIONS
    )

    assert len(sessions) == 168
    assert [group[0].version for group in groups] == list(matrix.SUPPORTED_VERSIONS)
    assert all(group and {session.version for session in group} == {group[0].version} for group in groups)

    for group in groups:
        indexes = {session.session_id: index for index, session in enumerate(group)}
        for preview in (session for session in group if session.phase == "preview"):
            confirms = [
                session
                for session in group
                if session.pair_id == preview.pair_id and session.phase == "confirm"
            ]
            if confirms:
                assert len(confirms) == 1
                assert indexes[preview.session_id] < indexes[confirms[0].session_id]
