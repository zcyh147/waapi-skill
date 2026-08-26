from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from tests.semantic.support import codex_soundbank_runtime_v3 as soundbank_runtime
from tests.semantic.support.codex_campaign import load_verified_json
from tests.semantic.support.codex_integration_soundbank_runtime_v1 import (
    GENERATE_API,
    HARBOR_BUS_NAME,
    HARBOR_CONTROL_BANK,
    HARBOR_FILTERS,
    HARBOR_PLATFORMS,
    HARBOR_PROJECT_INFO_MAX_PLATFORM_ROWS,
    HARBOR_PROJECT_INFO_PATH_EVIDENCE_CONTRACT,
    HARBOR_PROJECT_INFO_PATH_EVIDENCE_FILE,
    HARBOR_PROJECT_INFO_RAW_PATH_MAX_BYTES,
    HARBOR_RELEASE_BANK,
    SET_INCLUSIONS_API,
    HarborIntegrationRuntimeError,
    _HarborProjectInfoPathEvidenceRecorder,
    _prepare_harbor_integration_runtime,
    _validated_generation_request,
    prepare_harbor_integration_runtime,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    materialize_typed_transaction_protocol_requests,
)
from tests.semantic.support.codex_integration_workflows_v1 import (
    IntegrationWorkflowCase,
    IntegrationWorkflowUnit,
    load_integration_workflows_profile,
)
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioRuntime
from tests.semantic.support.codex_soundbank_runtime_v3 import SoundBankRuntimeError
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
    project_info_mutator: Callable[[dict[str, Any]], None] | None = None,
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
        if project_info_mutator is not None:
            project_info_mutator(backend.project_info)
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


def _append_native_directory_separators(project_info: dict[str, Any]) -> None:
    directories = project_info["directories"]
    for field in ("root", "cache", "soundBankOutputRoot"):
        directories[field] += os.sep
    for platform in project_info["platforms"]:
        for field in ("soundBankPath", "copiedMediaPath"):
            platform[field] += os.sep


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

    previews = [
        request
        for _pointer, request in materialize_typed_transaction_protocol_requests(
            prepared.protocol,
            version=version,
        )
    ]
    preview_indexes = tuple(
        index + 1
        for index, row in enumerate(prepared.protocol.steps)
        if row.subcommand == "preview-from-draft"
    )
    assert prepared.protocol.turn_prefix_counts == (
        preview_indexes[0],
        preview_indexes[1],
        len(prepared.protocol.steps),
    )
    for transaction_id in ("tx01", "tx02"):
        names = tuple(
            row.name
            for row in prepared.protocol.steps
            if row.name.startswith(f"{transaction_id}.")
        )
        assert names[0] == f"{transaction_id}.operation-schema"
        draft_start_index = names.index(f"{transaction_id}.draft-start")
        assert draft_start_index >= 1
        assert all(
            name.startswith(f"{transaction_id}.query-object.")
            for name in names[1:draft_start_index]
        )
        assert all(
            not name.startswith(f"{transaction_id}.query-object.")
            for name in names[draft_start_index + 1 :]
        )
        assert names[-5:] == (
            f"{transaction_id}.preview",
            f"{transaction_id}.transaction-show",
            f"{transaction_id}.confirm",
            f"{transaction_id}.execute",
            f"{transaction_id}.verify",
        )
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
    assert "逐项使用我给出的三个完整 Event 路径作为对象身份" in prepared.prompt
    assert "不要改成按同名对象查找" in prepared.prompt
    assert "Event 或 Aux Bus" not in prepared.prompt
    assert "清单明确为空" not in prepared.prompt
    assert (
        "Harbor_Release 这一行的 "
        "rebuild 明确设为 false，跳过语言变体，"
        "不要重建全部 SoundBank，不要清空音频缓存，也不要重建 Init Bank"
        in prepared.prompt
    )
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


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_harbor_runtime_accepts_native_directory_trailing_separators_and_seals_raw_evidence(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, _backend, _workflow = _prepare(
        tmp_path,
        version=version,
        project_info_mutator=_append_native_directory_separators,
    )

    evidence = load_verified_json(prepared.host_path_evidence_path)

    assert evidence["contract"] == HARBOR_PROJECT_INFO_PATH_EVIDENCE_CONTRACT
    assert evidence["scenario_id"] == _unit(version).scenario.id
    assert evidence["version"] == version
    assert evidence["model_visible"] is False
    assert evidence["normalization_applied"] is False
    assert evidence["observation_count"] == 1
    observation = evidence["observations"][0]
    assert observation["platform_row_count"] == 2
    assert observation["omitted_platform_rows"] == 0
    paths = observation["paths"]
    assert len(paths) == 8
    project_path = paths[0]
    assert project_path["field"] == "project_info.path"
    assert project_path["trailing_separator"] is False
    assert project_path["raw_omitted"] is False
    assert project_path["raw_utf8_limit"] == HARBOR_PROJECT_INFO_RAW_PATH_MAX_BYTES
    assert project_path["raw_sha256"] == hashlib.sha256(
        project_path["raw_value"].encode("utf-8")
    ).hexdigest()
    directory_paths = paths[1:]
    assert all(row["trailing_separator"] is True for row in directory_paths)
    assert all(row["raw_omitted"] is False for row in directory_paths)
    assert all(row["raw_value"].endswith(os.sep) for row in directory_paths)
    assert all(
        row["raw_sha256"]
        == hashlib.sha256(row["raw_value"].encode("utf-8")).hexdigest()
        for row in directory_paths
    )
    projection = prepared.prompt_sources["soundbank_generate_project_info"]
    assert not projection["directories"]["cache"].endswith(os.sep)
    assert all(
        not row[field].endswith(os.sep)
        for row in projection["platforms"]
        for field in ("soundBankPath", "copiedMediaPath")
    )


def test_harbor_unsafe_project_info_path_is_archived_before_fail_closed(
    tmp_path: Path,
) -> None:
    unit = _unit("2022.1")
    runtime = _runtime(
        tmp_path,
        scenario_id=unit.scenario.id,
        version=unit.version,
    )

    def backend_factory(blueprint: Any) -> FakeSoundBankBackend:
        backend = FakeSoundBankBackend(blueprint)
        backend.project_info["directories"]["root"] = (
            "\\\\server\\share\\Harbor\\"
        )
        return backend

    with pytest.raises(SoundBankRuntimeError, match="directories.root"):
        _prepare_harbor_integration_runtime(
            unit.workflow,
            unit.scenario,
            version=unit.version,
            runtime=runtime,
            backend_factory=backend_factory,
        )

    evidence_path = runtime.evidence_root / HARBOR_PROJECT_INFO_PATH_EVIDENCE_FILE
    evidence = load_verified_json(evidence_path)
    root_row = next(
        row
        for row in evidence["observations"][0]["paths"]
        if row["field"] == "project_info.directories.root"
    )
    assert root_row == {
        "field": "project_info.directories.root",
        "raw_value": "\\\\server\\share\\Harbor\\",
        "raw_type": "str",
        "utf8_bytes": len("\\\\server\\share\\Harbor\\".encode("utf-8")),
        "raw_utf8_limit": HARBOR_PROJECT_INFO_RAW_PATH_MAX_BYTES,
        "raw_omitted": False,
        "raw_sha256": hashlib.sha256(
            "\\\\server\\share\\Harbor\\".encode("utf-8")
        ).hexdigest(),
        "lexical_flavor": "unc",
        "trailing_separator": True,
    }


def test_harbor_overlimit_raw_path_evidence_is_hashed_but_omitted(
    tmp_path: Path,
) -> None:
    unit = _unit("2022.1")
    runtime = _runtime(
        tmp_path,
        scenario_id=unit.scenario.id,
        version=unit.version,
    )
    overlimit = (
        "\\\\server\\share\\"
        + "路" * (HARBOR_PROJECT_INFO_RAW_PATH_MAX_BYTES // 2)
        + "\\"
    )
    encoded = overlimit.encode("utf-8")
    assert len(encoded) > HARBOR_PROJECT_INFO_RAW_PATH_MAX_BYTES

    def backend_factory(blueprint: Any) -> FakeSoundBankBackend:
        backend = FakeSoundBankBackend(blueprint)
        backend.project_info["directories"]["root"] = overlimit
        return backend

    with pytest.raises(SoundBankRuntimeError, match="directories.root"):
        _prepare_harbor_integration_runtime(
            unit.workflow,
            unit.scenario,
            version=unit.version,
            runtime=runtime,
            backend_factory=backend_factory,
        )

    evidence_path = runtime.evidence_root / HARBOR_PROJECT_INFO_PATH_EVIDENCE_FILE
    evidence = load_verified_json(evidence_path)
    root_row = next(
        row
        for row in evidence["observations"][0]["paths"]
        if row["field"] == "project_info.directories.root"
    )
    assert root_row["raw_value"] is None
    assert root_row["raw_omitted"] is True
    assert root_row["raw_utf8_limit"] == HARBOR_PROJECT_INFO_RAW_PATH_MAX_BYTES
    assert root_row["utf8_bytes"] == len(encoded)
    assert root_row["raw_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert root_row["lexical_flavor"] == "unc"
    assert root_row["trailing_separator"] is True
    assert evidence_path.stat().st_size < HARBOR_PROJECT_INFO_RAW_PATH_MAX_BYTES


def test_harbor_path_evidence_caps_platform_rows_and_observation_count(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / HARBOR_PROJECT_INFO_PATH_EVIDENCE_FILE
    recorder = _HarborProjectInfoPathEvidenceRecorder(
        evidence_path,
        scenario_id="INT22-HARBOR-SOUNDBANK-RELEASE",
        version="2022.1",
    )
    platform_row_count = HARBOR_PROJECT_INFO_MAX_PLATFORM_ROWS + 3
    project_info = {
        "path": "/owned/Harbor.wproj",
        "directories": {
            "root": "/owned/",
            "cache": "/owned/cache/",
            "soundBankOutputRoot": "/owned/soundbanks/",
        },
        "platforms": [
            {
                "name": f"Platform {index}",
                "soundBankPath": f"/owned/soundbanks/Platform {index}/",
                "copiedMediaPath": f"/owned/soundbanks/Platform {index}/Media/",
            }
            for index in range(platform_row_count)
        ],
    }

    projection = soundbank_runtime._project_info_observer_projection(project_info)
    recorder.observe(projection)
    recorder.observe(projection)
    with pytest.raises(
        HarborIntegrationRuntimeError,
        match="exceeded two observations",
    ):
        recorder.observe(projection)

    evidence = load_verified_json(evidence_path)
    assert evidence["observation_count"] == 2
    for observation in evidence["observations"]:
        assert observation["platform_row_count"] == platform_row_count
        assert observation["omitted_platform_rows"] == 3
        assert len(observation["paths"]) == (
            4 + 2 * HARBOR_PROJECT_INFO_MAX_PLATFORM_ROWS
        )
        assert observation["paths"][-1]["field"] == (
            "project_info.platforms[31].copiedMediaPath"
        )
        assert not any(
            "platforms[32]" in row["field"]
            for row in observation["paths"]
        )


def test_harbor_generation_preflight_rejects_output_directory_as_io_root(
    tmp_path: Path,
) -> None:
    prepared, _backend, _workflow = _prepare(tmp_path)
    request = next(
        request
        for pointer, request in materialize_typed_transaction_protocol_requests(
            prepared.protocol,
            version="2022.1",
        )
        if pointer == "/composer/tx02.preview"
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
