from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.semantic.support.codex_integration_soundbank_runtime_v1 import (
    GENERATE_API,
    HARBOR_BUS_NAME,
    HARBOR_CONTROL_BANK,
    HARBOR_FILTERS,
    HARBOR_PLATFORMS,
    HARBOR_RELEASE_BANK,
    SET_INCLUSIONS_API,
    HarborIntegrationRuntimeError,
    _prepare_harbor_integration_runtime,
    _validated_generation_request,
    prepare_harbor_integration_runtime,
)
from tests.semantic.support.codex_integration_workflows_v1 import (
    IntegrationWorkflowCase,
    IntegrationWorkflowUnit,
    load_integration_workflows_profile,
)
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioRuntime
from tests.semantic.test_codex_soundbank_runtime_v3 import FakeSoundBankBackend


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "integration-workflows-v1"
    / "profile.json"
)


def _runtime(
    tmp_path: Path,
    *,
    scenario_id: str,
    version: str,
) -> ScenarioRuntime:
    root = tmp_path / scenario_id
    owned = root / "owned"
    project_root = owned / "project"
    project_root.mkdir(parents=True)
    project = project_root / "HarborIntegration.wproj"
    project.write_text("<WwiseDocument/>", encoding="utf-8")
    evidence = root / "evidence"
    assets = owned / "assets"
    io_root = owned / "io"
    for path in (evidence, assets, io_root):
        path.mkdir(parents=True)
    return ScenarioRuntime(
        scenario_id=scenario_id,
        version=version,
        scenario_root=root,
        evidence_root=evidence,
        owned_root=owned,
        asset_root=assets,
        io_root=io_root,
        sandbox=SimpleNamespace(
            sandbox_project=project,
            sandbox_path=project_root,
        ),
        lifecycle=SimpleNamespace(host="127.0.0.1", port=18080),
        runner_environment={},
        source_hash_before=SimpleNamespace(),
        source_mtime_before_ns=project.stat().st_mtime_ns,
    )


def _unit(version: str) -> IntegrationWorkflowUnit:
    profile = load_integration_workflows_profile(
        PROFILE_PATH,
        versions=(version,),
    )
    unit = next(
        row
        for row in profile.units
        if row.workflow_id == "harbor_soundbank_release"
    )
    return unit


def _prepare(
    tmp_path: Path,
    *,
    version: str = "2022.1",
) -> tuple[Any, FakeSoundBankBackend, IntegrationWorkflowCase]:
    unit = _unit(version)
    runtime = _runtime(
        tmp_path,
        scenario_id=unit.scenario.id,
        version=version,
    )
    holder: dict[str, FakeSoundBankBackend] = {}

    def backend_factory(blueprint: Any) -> FakeSoundBankBackend:
        backend = FakeSoundBankBackend(blueprint)
        holder["backend"] = backend
        return backend

    prepared = _prepare_harbor_integration_runtime(
        unit.workflow,
        unit.scenario,
        version=version,
        runtime=runtime,
        backend_factory=backend_factory,
    )
    return prepared, holder["backend"], unit.workflow


def _step(prepared: Any, name: str) -> Any:
    return next(row for row in prepared.protocol.steps if row.name == name)


def _apply_tx01(
    prepared: Any,
    backend: FakeSoundBankBackend,
    workflow: IntegrationWorkflowCase,
) -> None:
    target_id = next(
        identity
        for identity, row in backend.rows.items()
        if row["type"] == "SoundBank" and row["name"] == HARBOR_RELEASE_BANK
    )
    backend.set_inclusions(
        backend.rows[target_id]["id"],
        "replace",
        [
            (
                backend.by_path[path.casefold()],
                HARBOR_FILTERS,
            )
            for path in workflow.fixture.parameters["events"]
        ],
    )
    prepared.observe_payload(_step(prepared, "tx01.verify"), {"ok": True})


def _write_required_artifacts(
    prepared: Any,
    *,
    include_nonempty_init: bool = False,
) -> None:
    tx02 = prepared.oracle_requirements[1].expectation
    for row in tx02["artifacts"]:
        path = Path(row["path"])
        if row["required_change"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                f"HARBOR:{row['kind']}:{row['platform']}".encode("utf-8")
            )
        elif include_nonempty_init and row["kind"] == "init":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"HARBOR:INIT")


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_harbor_runtime_materializes_closed_dual_platform_workflow_and_cleans(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, backend, workflow = _prepare(tmp_path, version=version)

    assert prepared.protocol.turn_prefix_counts == (2, 8, 12)
    assert tuple(
        row.name for row in prepared.protocol.steps
    ) == (
        "tx01.operation-schema",
        "tx01.preview",
        "tx01.transaction-show",
        "tx01.confirm",
        "tx01.execute",
        "tx01.verify",
        "tx02.operation-schema",
        "tx02.preview",
        "tx02.transaction-show",
        "tx02.confirm",
        "tx02.execute",
        "tx02.verify",
    )
    previews = [
        row.arguments[2].expected
        for row in prepared.protocol.steps
        if row.subcommand == "preview"
    ]
    assert previews[0]["operation"] == "soundbank.setInclusions"
    assert previews[0]["arguments"]["mode"] == "replace"
    assert previews[0]["arguments"]["soundbank"] == {
        "kind": "exact-type-name",
        "type": "SoundBank",
        "name": "Harbor_Release",
    }
    assert previews[0]["arguments"]["inclusions"] == [
        {
            "object": {"kind": "path", "value": path},
            "filters": list(HARBOR_FILTERS),
        }
        for path in workflow.fixture.parameters["events"]
    ]
    assert previews[1]["operation"] == "soundbank.generate"
    assert previews[1]["arguments"]["platforms"] == list(HARBOR_PLATFORMS)
    assert previews[1]["arguments"]["soundbanks"] == [
        {
            "name": HARBOR_RELEASE_BANK,
            "artifact_expectation": "nonlocalized",
            "rebuild": False,
        }
    ]
    assert previews[1]["arguments"]["io_root"] == (
        prepared.visible_values["soundbank_io_root"]
    )
    assert previews[1]["arguments"]["io_root"] != (
        prepared.visible_values["soundbank_output_directory"]
    )
    assert prepared.visible_values["soundbank_io_root"] in prepared.prompt
    assert prepared.visible_values["soundbank_output_directory"] in prepared.prompt
    assert tuple(row.api for row in prepared.expected_dispatches) == (
        SET_INCLUSIONS_API,
        GENERATE_API,
    )
    assert tuple(row.transaction_id for row in prepared.oracle_requirements) == (
        "tx01",
        "tx02",
    )
    assert prepared.visible_values["harbor_bank_name"] == HARBOR_RELEASE_BANK
    assert set(HARBOR_PLATFORMS) == {
        row["platform"]
        for row in prepared.oracle_requirements[1].expectation["artifacts"]
        if row["kind"] == "bank"
    }

    initial = prepared.snapshot()
    release = next(
        row for row in initial.banks if row.name == HARBOR_RELEASE_BANK
    )
    debug_id = backend.by_path[
        (
            workflow.fixture.parameters["events"][0].rsplit("\\", 1)[0]
            + "\\Play_Harbor_Debug"
        ).casefold()
    ]
    assert release.inclusions == (
        (debug_id.casefold(), tuple(sorted(HARBOR_FILTERS))),
    )
    harbor_bus = next(
        row
        for row in backend.rows.values()
        if row["name"] == HARBOR_BUS_NAME
    )
    for event_path in workflow.fixture.parameters["events"]:
        graph = backend.event_graphs[event_path.casefold()]
        assert graph.action_types == (1,)
        assert len(graph.action_ids) == len(graph.target_ids) == 1
        sound = backend.rows[graph.target_ids[0].casefold()]
        assert sound["OutputBus"] == {"id": harbor_bus["id"]}

    _apply_tx01(prepared, backend, workflow)
    prepared.observe_payload(_step(prepared, "tx02.preview"), {"ok": True})
    _write_required_artifacts(prepared, include_nonempty_init=True)

    verification = prepared.verify_final(None, SimpleNamespace())
    verification.assert_passed()
    assert verification.evidence["required_artifact_count"] == 8
    deleted = prepared.cleanup()
    assert deleted
    assert not any(
        row.get("name") in {HARBOR_RELEASE_BANK, HARBOR_CONTROL_BANK}
        for row in backend.rows.values()
    )


def test_harbor_generation_preflight_rejects_output_directory_as_io_root(
    tmp_path: Path,
) -> None:
    prepared, _backend, _workflow = _prepare(tmp_path)
    request = next(
        row.arguments[2].expected
        for row in prepared.protocol.steps
        if row.name == "tx02.preview"
    )
    invalid = {
        **request,
        "arguments": {
            **request["arguments"],
            "io_root": prepared.visible_values["soundbank_output_directory"],
        },
    }

    with pytest.raises(
        HarborIntegrationRuntimeError,
        match="exact trusted I/O root",
    ):
        _validated_generation_request(
            invalid,
            io_root=Path(prepared.visible_values["soundbank_io_root"]),
            output_root=prepared.visible_values["soundbank_output_directory"],
            project_info=prepared.prompt_sources[
                "soundbank_generate_project_info"
            ],
        )


def test_tx01_verify_rejects_inexact_inclusions_and_preserves_quarantine_state(
    tmp_path: Path,
) -> None:
    prepared, backend, workflow = _prepare(tmp_path)
    target_id = next(
        identity
        for identity, row in backend.rows.items()
        if row["type"] == "SoundBank" and row["name"] == HARBOR_RELEASE_BANK
    )
    backend.set_inclusions(
        backend.rows[target_id]["id"],
        "replace",
        [
            (
                backend.by_path[path.casefold()],
                HARBOR_FILTERS,
            )
            for path in workflow.fixture.parameters["events"][:2]
        ],
    )

    with pytest.raises(
        HarborIntegrationRuntimeError,
        match="three exact formal",
    ):
        prepared.observe_payload(
            _step(prepared, "tx01.verify"),
            {"ok": True},
        )
    with pytest.raises(
        HarborIntegrationRuntimeError,
        match="lifecycle quarantine",
    ):
        prepared.cleanup()
    assert any(
        row.get("name") == HARBOR_RELEASE_BANK
        for row in backend.rows.values()
    )


def test_final_verification_requires_tx01_baseline_before_generation(
    tmp_path: Path,
) -> None:
    prepared, _backend, _workflow = _prepare(tmp_path)
    _write_required_artifacts(prepared)

    verification = prepared.verify_final(None, SimpleNamespace())

    assert not verification.passed
    assert any(
        "tx01.verify did not establish" in message
        for message in verification.failures
    )
    with pytest.raises(HarborIntegrationRuntimeError):
        prepared.cleanup()


def test_final_verification_rejects_control_or_debug_bank_outputs_and_object_drift(
    tmp_path: Path,
) -> None:
    prepared, backend, workflow = _prepare(tmp_path)
    _apply_tx01(prepared, backend, workflow)
    _write_required_artifacts(prepared)
    output_root = Path(prepared.visible_values["soundbank_output_directory"])
    for name in (f"{HARBOR_CONTROL_BANK}.bnk", "Harbor_Debug.bnk"):
        path = output_root / "Windows" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"FORBIDDEN")
    formal_event = workflow.fixture.parameters["events"][0]
    backend.rows[
        backend.by_path[formal_event.casefold()].casefold()
    ]["type"] = "Folder"

    verification = prepared.verify_final(None, SimpleNamespace())

    assert not verification.passed
    assert any(
        "changed sealed objects" in message
        for message in verification.failures
    )
    assert sum(
        "Debug/control SoundBank artifact" in message
        for message in verification.failures
    ) == 2


def test_optional_init_is_allowed_only_when_nonempty(tmp_path: Path) -> None:
    prepared, backend, workflow = _prepare(tmp_path)
    _apply_tx01(prepared, backend, workflow)
    _write_required_artifacts(prepared)
    init = next(
        row
        for row in prepared.oracle_requirements[1].expectation["artifacts"]
        if row["kind"] == "init"
    )
    path = Path(init["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")

    verification = prepared.verify_final(None, SimpleNamespace())

    assert not verification.passed
    assert any(
        "optional Init artifact is empty" in message
        for message in verification.failures
    )


def test_public_factory_rejects_non_callable_direct_before_live_setup(
    tmp_path: Path,
) -> None:
    unit = _unit("2022.1")
    runtime = _runtime(
        tmp_path,
        scenario_id=unit.scenario.id,
        version=unit.version,
    )

    with pytest.raises(TypeError, match="direct must be callable"):
        prepare_harbor_integration_runtime(
            unit.workflow,
            unit.scenario,
            version=unit.version,
            runtime=runtime,
            direct=None,  # type: ignore[arg-type]
        )
