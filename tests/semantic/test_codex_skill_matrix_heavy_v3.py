from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from tests.semantic import run_codex_skill_matrix as matrix


@dataclass(frozen=True, slots=True)
class _Scenario:
    api: str
    visible_inputs: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class _Unit:
    unit_id: str
    version: str
    scenario: _Scenario


@dataclass(frozen=True, slots=True)
class _Outcome:
    scenario_id: str
    version: str
    status: str
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": "synthetic-heavy-outcome/v1",
            "scenario_id": self.scenario_id,
            "version": self.version,
            "status": self.status,
            "reason": self.reason,
            "scenario_root": "synthetic",
            "task_root": None,
            "thread_id": None,
            "checks": {},
            "lifecycle": None,
        }


def _options(tmp_path: Path) -> matrix.RunnerOptions:
    return matrix.RunnerOptions(
        profile=matrix.HEAVY_V3_PROFILE_ID,
        iteration_root=tmp_path / "heavy-run",
        suite_path=matrix.DEFAULT_V3_SUITE.resolve(),
        skill_source=matrix.SKILL_ROOT.resolve(),
        codex_binary=tmp_path / "codex-not-invoked",
        auth_json=tmp_path / "auth-not-read.json",
        live_config=tmp_path / "live-not-read.json",
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        service_tier="default",
        timeout_seconds=90.0,
        case_ids=(),
        versions=(),
        pair_ids=(),
        offline_only=False,
        overwrite=False,
    )


def _install_nonlive_root(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, Mapping[str, Any]]]:
    writes: list[tuple[str, Mapping[str, Any]]] = []
    real_write_json = matrix.write_json

    def prepare(path: Path, *, overwrite: bool) -> None:
        assert overwrite is False
        path.mkdir(parents=True, exist_ok=False)

    def capture(path: Path, payload: Mapping[str, Any]) -> None:
        writes.append((path.name, json.loads(json.dumps(payload))))
        real_write_json(path, payload)

    monkeypatch.setattr(matrix, "prepare_iteration_root", prepare)
    monkeypatch.setattr(matrix, "write_json", capture)
    return writes


def test_parse_args_preserves_v2_defaults_and_selects_v3_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda _value: Path("/synthetic-host/codex"),
    )
    v2 = matrix.parse_args([])
    heavy = matrix.parse_args(
        [
            "--profile",
            matrix.HEAVY_V3_PROFILE_ID,
            "--case-id",
            "OBJ22-F-CREATE-01",
            "--version",
            "2022.1",
            "--model",
            "gpt-5.6-terra",
            "--service-tier",
            "default",
        ]
    )

    assert v2.suite_path == matrix.DEFAULT_SUITE.resolve()
    assert v2.iteration_root == matrix.DEFAULT_ITERATION_ROOT.resolve()
    assert heavy.suite_path == matrix.DEFAULT_V3_SUITE.resolve()
    assert heavy.iteration_root == matrix.DEFAULT_HEAVY_V3_ITERATION_ROOT.resolve()
    assert heavy.case_ids == ("OBJ22-F-CREATE-01",)
    assert heavy.versions == ("2022.1",)
    assert heavy.model == "gpt-5.6-terra"
    assert heavy.reasoning_effort == "medium"
    assert heavy.service_tier == "default"


def test_heavy_run_config_records_readiness_timeout(tmp_path: Path) -> None:
    options = replace(
        _options(tmp_path),
        wwise_readiness_timeout_seconds=180.0,
    )

    config = matrix._heavy_v3_run_config(
        options,
        unit_rows=(),
        records=(),
        run_errors=(),
        stop_reason="",
        preflight_state="passed",
        started_at="2026-08-26T00:00:00Z",
        completed_at="2026-08-26T00:00:01Z",
    )

    assert config["wwise_readiness_timeout_seconds"] == 180.0


def test_public_integration_delegates_first_use_prose_to_dedicated_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        matrix,
        "resolve_codex_binary",
        lambda _value: Path("/synthetic-host/codex"),
    )

    options = matrix.parse_args(
        [
            "--profile",
            matrix.INTEGRATION_PROFILE_ID,
            "--model",
            "gpt-5.6-terra",
            "--service-tier",
            "default",
        ]
    )

    assert options.require_first_use_intro is False


@pytest.mark.parametrize("forbidden", [("--offline-only",), ("--pair-id", "pair-1")])
def test_parse_args_rejects_v2_only_filters_for_heavy_profile(
    forbidden: tuple[str, ...],
) -> None:
    with pytest.raises(SystemExit):
        matrix.parse_args(
            ["--profile", matrix.HEAVY_V3_PROFILE_ID, *forbidden]
        )


def test_real_v3_loader_preserves_order_and_case_version_filters(tmp_path: Path) -> None:
    options = _options(tmp_path)
    options = replace(
        options,
        case_ids=("VS24-F-AUDIO-CONVERT-03",),
        versions=("2024.1",),
    )

    units = matrix.load_heavy_v3_units(options)

    assert [unit.unit_id for unit in units] == ["VS24-F-AUDIO-CONVERT-03"]
    assert [unit.version for unit in units] == ["2024.1"]


def test_heavy_matrix_continues_after_fail_and_writes_incremental_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    writes = _install_nonlive_root(monkeypatch)
    units = (
        _Unit("CASE-01", "2022.1", _Scenario("ak.wwise.core.object.get")),
        _Unit("CASE-02", "2022.1", _Scenario("ak.wwise.core.object.create")),
        _Unit("CASE-03", "2024.1", _Scenario("ak.wwise.core.audio.convert")),
    )
    statuses = {"CASE-01": "PASS", "CASE-02": "FAIL", "CASE-03": "PASS"}
    calls: list[tuple[str, Path, str, str]] = []

    def run(unit: _Unit, *, scenario_root: Path, options: matrix.RunnerOptions):
        calls.append(
            (unit.unit_id, scenario_root, options.model, options.reasoning_effort)
        )
        return _Outcome(
            unit.unit_id,
            unit.version,
            statuses[unit.unit_id],
            "semantic mismatch" if statuses[unit.unit_id] == "FAIL" else "",
        )

    result = matrix.run_heavy_v3_matrix(
        _options(tmp_path),
        unit_loader=lambda _options: units,
        unit_runner=run,
        dependency_preflight=lambda: {"ok": True, "contract": "fake-preflight"},
    )

    assert result == 1
    assert [item[0] for item in calls] == ["CASE-01", "CASE-02", "CASE-03"]
    assert all(item[2:] == ("gpt-5.6-terra", "medium") for item in calls)
    summary = json.loads(
        (_options(tmp_path).iteration_root / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["attempted_unit_ids"] == ["CASE-01", "CASE-02", "CASE-03"]
    assert summary["failed_unit_ids"] == ["CASE-02"]
    assert summary["pending_unit_ids"] == []
    assert summary["stopped_early"] is False
    assert summary["run_errors"] == []
    attempted_snapshots = [
        payload["attempted_unit_count"]
        for name, payload in writes
        if name == "summary.json"
    ]
    assert attempted_snapshots[0] == 0
    assert {1, 2, 3}.issubset(attempted_snapshots)
    assert attempted_snapshots[-1] == 3


def test_heavy_matrix_returns_success_only_after_every_unit_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_nonlive_root(monkeypatch)
    units = (
        _Unit("CASE-01", "2022.1", _Scenario("ak.wwise.core.object.get")),
        _Unit("CASE-02", "2025.1", _Scenario("ak.wwise.core.mediaPool.get")),
    )

    result = matrix.run_heavy_v3_matrix(
        _options(tmp_path),
        unit_loader=lambda _options: units,
        unit_runner=lambda unit, **_kwargs: _Outcome(
            unit.unit_id, unit.version, "PASS"
        ),
        dependency_preflight=lambda: {"ok": True},
    )

    assert result == 0
    summary = json.loads(
        (_options(tmp_path).iteration_root / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["all_selected_passed"] is True
    assert summary["status_counts"] == {
        "BLOCKED": 0,
        "FAIL": 0,
        "INDETERMINATE": 0,
        "PASS": 2,
    }


def test_heavy_matrix_preflight_fault_stops_before_any_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_nonlive_root(monkeypatch)
    units = (
        _Unit("CASE-01", "2022.1", _Scenario("ak.wwise.core.object.get")),
    )
    called = False

    def forbidden_runner(*_args: Any, **_kwargs: Any):
        nonlocal called
        called = True
        raise AssertionError("preflight-blocked runner must not execute")

    def blocked_preflight() -> Mapping[str, Any]:
        raise RuntimeError("waapi dependency unavailable")

    result = matrix.run_heavy_v3_matrix(
        _options(tmp_path),
        unit_loader=lambda _options: units,
        unit_runner=forbidden_runner,
        dependency_preflight=blocked_preflight,
    )

    assert result == 1
    assert called is False
    summary = json.loads(
        (_options(tmp_path).iteration_root / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["preflight"] == "blocked"
    assert summary["attempted_unit_ids"] == []
    assert summary["pending_unit_ids"] == ["CASE-01"]
    assert summary["stop_reason"] == "live-dependency-preflight"


@pytest.mark.parametrize("terminal_status", ["BLOCKED", "INDETERMINATE"])
def test_heavy_matrix_stops_on_untrustworthy_status_and_leaves_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    terminal_status: str,
) -> None:
    _install_nonlive_root(monkeypatch)
    units = tuple(
        _Unit(f"CASE-{index:02d}", "2022.1", _Scenario("ak.wwise.core.object.get"))
        for index in range(1, 4)
    )
    calls: list[str] = []

    def run(unit: _Unit, **_kwargs: Any) -> _Outcome:
        calls.append(unit.unit_id)
        status = "PASS" if unit.unit_id == "CASE-01" else terminal_status
        return _Outcome(unit.unit_id, unit.version, status, "evidence is not trustworthy")

    result = matrix.run_heavy_v3_matrix(
        _options(tmp_path),
        unit_loader=lambda _options: units,
        unit_runner=run,
        dependency_preflight=lambda: {"ok": True},
    )

    assert result == 1
    assert calls == ["CASE-01", "CASE-02"]
    summary = json.loads(
        (_options(tmp_path).iteration_root / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["attempted_unit_ids"] == ["CASE-01", "CASE-02"]
    assert summary["pending_unit_ids"] == ["CASE-03"]
    assert summary["stop_reason"] == f"{terminal_status.lower()}:CASE-02"
    assert summary["stopped_early"] is True


def test_cli_runner_import_is_lazy_and_missing_runner_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    unit = _Unit(
        "CLI-CASE",
        "2022.1",
        _Scenario("ak.wwise.cli.generateSoundbank"),
    )
    imported: list[str] = []

    def fake_import(name: str):
        imported.append(name)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(matrix.importlib, "import_module", fake_import)

    with pytest.raises(matrix.HeavyV3RunnerUnavailableError, match="CLI case runner"):
        matrix.run_heavy_v3_unit(
            unit,
            scenario_root=tmp_path / "case",
            options=options,
        )

    assert imported == ["tests.semantic.support.codex_heavy_cli_case_runner_v3"]


def test_project_dispatch_passes_closed_runtime_options_without_starting_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    unit = _Unit(
        "PROJECT-CASE",
        "2022.1",
        _Scenario("ak.wwise.core.object.get"),
    )
    observed: dict[str, Any] = {}

    @dataclass(frozen=True, slots=True)
    class FakeOptions:
        skill_source: Path
        codex_binary: Path
        auth_json: Path
        model: str
        reasoning_effort: str
        service_tier: str
        timeout_seconds: float
        live_environment: Mapping[str, str]
        windows_powershell_core_host: Any = None
        developer_instructions: str = ""
        require_first_use_intro: bool = True

    def fake_run(value: _Unit, *, scenario_root: Path, options: FakeOptions):
        observed.update(unit=value, root=scenario_root, options=options)
        return _Outcome(value.unit_id, value.version, "PASS")

    module = SimpleNamespace(
        PROJECT_RUNNER_APIS={"ak.wwise.core.object.get"},
        HeavyProjectRunnerOptions=FakeOptions,
        run_heavy_project_unit=fake_run,
    )
    monkeypatch.setattr(matrix.importlib, "import_module", lambda _name: module)

    outcome = matrix.run_heavy_v3_unit(
        unit,
        scenario_root=tmp_path / "case",
        options=options,
    )

    assert outcome.passed
    assert observed["unit"] is unit
    assert observed["root"] == tmp_path / "case"
    runtime_options = observed["options"]
    assert runtime_options.model == "gpt-5.6-terra"
    assert runtime_options.reasoning_effort == "medium"
    assert runtime_options.service_tier == "default"
    assert runtime_options.live_environment["WWISE_TEST_CONFIG"] == str(
        options.live_config
    )
    assert runtime_options.developer_instructions == ""
    assert runtime_options.require_first_use_intro is True


@pytest.mark.parametrize(
    "profile",
    [matrix.TYPED_INPUT_PROFILE_ID, matrix.INTEGRATION_PROFILE_ID],
)
def test_agent_facing_project_dispatch_seals_pre_action_developer_instructions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile: str,
) -> None:
    options = replace(_options(tmp_path), profile=profile)
    unit = _Unit(
        "TYP21-ZERO-GET-INFO",
        "2021.1",
        _Scenario("ak.wwise.core.getInfo"),
    )
    observed: dict[str, Any] = {}

    @dataclass(frozen=True, slots=True)
    class FakeOptions:
        skill_source: Path
        codex_binary: Path
        auth_json: Path
        model: str
        reasoning_effort: str
        service_tier: str
        timeout_seconds: float
        live_environment: Mapping[str, str]
        windows_powershell_core_host: Any = None
        developer_instructions: str = ""
        require_first_use_intro: bool = True

    def fake_run(value: _Unit, *, scenario_root: Path, options: FakeOptions):
        observed.update(options=options)
        return _Outcome(value.unit_id, value.version, "PASS")

    module = SimpleNamespace(
        PROJECT_RUNNER_APIS={"ak.wwise.core.getInfo"},
        PROJECT_RUNNER_MODEL_RESOLVED_REQUEST_FIELDS={},
        HeavyProjectRunnerOptions=FakeOptions,
        run_heavy_project_unit=fake_run,
    )
    monkeypatch.setattr(matrix.importlib, "import_module", lambda _name: module)

    outcome = matrix.run_heavy_v3_unit(
        unit,
        scenario_root=tmp_path / "case",
        options=options,
    )

    assert outcome.passed
    developer_instructions = observed["options"].developer_instructions
    assert developer_instructions.startswith(
        matrix.SEMANTIC_SKILL_BOOTSTRAP_DEVELOPER_INSTRUCTIONS
    )
    runner = options.skill_source / "scripts" / "run.py"
    expected_prefix = (
        f"python '{runner}' 'gateway.py'"
        if os.name == "nt"
        else f"python {runner} gateway.py"
    )
    assert expected_prefix in developer_instructions


def test_audio_convert_hidden_io_root_is_blocked_before_runner_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    unit = _Unit(
        "VS24-F-AUDIO-CONVERT-01",
        "2024.1",
        _Scenario("ak.wwise.core.audio.convert"),
    )

    def forbidden_run(*_args: Any, **_kwargs: Any):
        raise AssertionError("surface-blocked runner must not execute")

    module = SimpleNamespace(
        PROJECT_RUNNER_APIS={"ak.wwise.core.audio.convert"},
        HeavyProjectRunnerOptions=object,
        run_heavy_project_unit=forbidden_run,
    )
    monkeypatch.setattr(matrix.importlib, "import_module", lambda _name: module)

    with pytest.raises(
        matrix.HeavyV3RunnerUnavailableError,
        match="model-unresolvable fields: io_root",
    ):
        matrix.run_heavy_v3_unit(
            unit,
            scenario_root=tmp_path / "case",
            options=_options(tmp_path),
        )


@pytest.mark.parametrize(
    "api",
    (
        "ak.wwise.core.audio.convert",
        "ak.wwise.core.soundbank.processDefinitionFiles",
    ),
)
def test_natural_visible_io_root_closes_the_model_request_surface(api: str) -> None:
    unit = _Unit(
        "VISIBLE-IO-ROOT",
        "2022.1",
        _Scenario(api, (SimpleNamespace(name="io_root"),)),
    )

    matrix._require_heavy_v3_model_request_surface(unit, SimpleNamespace())


def test_reviewed_common_ancestor_rule_closes_convert_external_io_root() -> None:
    api = "ak.wwise.core.soundbank.convertExternalSources"
    unit = _Unit("RESOLVED-IO-ROOT", "2022.1", _Scenario(api))
    module = SimpleNamespace(
        PROJECT_RUNNER_MODEL_RESOLVED_REQUEST_FIELDS={api: frozenset({"io_root"})}
    )

    matrix._require_heavy_v3_model_request_surface(unit, module)
