from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic.support import codex_heavy_project_runner_v3 as project_runner
from tests.semantic.support import codex_integration_footsteps_runtime_v2 as footsteps
from tests.semantic.support import codex_integration_rifle_runtime_v2 as rifle
from tests.semantic.support import codex_integration_weapons_runtime_v2 as weapons
from tests.semantic.support.codex_eval_protocol_v3 import (
    OPERATION_REQUEST_CONTRACT,
    V3GatewayProtocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_gateway_broker import ExpectedGatewayStep
from tests.semantic.support.codex_integration_workflows_v2 import (
    EXPECTED_ASSERTION_IDS,
    BaselineManifest,
    IntegrationWorkflowV2Error,
    WorkflowUnit,
    _safe_relative,
    load_integration_workflows_v2_profile,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    read_prompt_provenance,
    write_prompt_provenance,
)


PROFILE_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "integration-workflows-v2"
    / "profile.json"
)
SHA_A = "a" * 64
SHA_B = "b" * 64
GUID_1 = "{11111111-1111-1111-1111-111111111111}"
GUID_2 = "{22222222-2222-2222-2222-222222222222}"
GUID_3 = "{33333333-3333-3333-3333-333333333333}"
GUID_4 = "{44444444-4444-4444-4444-444444444444}"
GUID_5 = "{55555555-5555-5555-5555-555555555555}"


def test_v2_profile_relative_paths_use_the_shared_archive_parser() -> None:
    assert _safe_relative(r"incoming\素材", "fixture.path") == "incoming/素材"

    for relative in (
        r"incoming\mixed/path",
        "incoming//file.wav",
        "incoming/../file.wav",
        "incoming/CON.wav",
    ):
        with pytest.raises(IntegrationWorkflowV2Error, match="safe relative path"):
            _safe_relative(relative, "fixture.path")


@pytest.mark.parametrize(
    ("runtime_module", "error_type"),
    (
        (rifle, rifle.RifleIntegrationRuntimeError),
        (footsteps, footsteps.FootstepsIntegrationRuntimeError),
    ),
)
def test_v2_owned_input_directories_use_archive_parts(
    tmp_path: Path,
    runtime_module: Any,
    error_type: type[Exception],
) -> None:
    root = tmp_path / runtime_module.__name__.rsplit(".", 1)[-1]
    root.mkdir()
    expected = root / "incoming" / "素材"

    assert runtime_module._fresh_owned_directory(root, r"incoming\素材") == expected

    for index, relative in enumerate(
        (r"mixed\separator/path", "nested//empty", "nested/../escape", "CON")
    ):
        separate_root = tmp_path / f"rejected-{runtime_module.__name__}-{index}"
        separate_root.mkdir()
        with pytest.raises(error_type, match="relative path is unsafe"):
            runtime_module._fresh_owned_directory(separate_root, relative)


def test_footsteps_original_archive_path_rejects_ambiguous_spelling() -> None:
    assert footsteps._safe_original_relative(r"Originals\SFX\Snow.wav")
    for relative in (
        r"Originals\SFX/Snow.wav",
        "Originals//Snow.wav",
        "Originals/../Snow.wav",
        "Originals/CON.wav",
    ):
        assert not footsteps._safe_original_relative(relative)


def _unit(workflow_id: str) -> WorkflowUnit:
    matches = [
        unit
        for unit in load_integration_workflows_v2_profile(PROFILE_PATH).units
        if unit.workflow_id == workflow_id and unit.version == "2022.1"
    ]
    assert len(matches) == 1
    return matches[0]


def _manifest(tmp_path: Path, *, version: str = "2022.1") -> BaselineManifest:
    path = (tmp_path / f"baseline-{version}.json").resolve()
    path.write_text("{}\n", encoding="utf-8")
    return BaselineManifest(
        path=path,
        version=version,
        digest=SHA_A,
        project_file_sha256=SHA_A,
        full_tree_sha256=SHA_B,
        objects=(MappingProxyType({"role": "sealed"}),),
        media=(MappingProxyType({"role": "sealed"}),),
    )


def _protocol(unit: WorkflowUnit) -> V3GatewayProtocol:
    def fixture_arguments(operation: str, index: int) -> dict[str, Any]:
        if operation == "audio.import":
            return {
                "imports": [
                    {
                        "object_path": (
                            rf"\Actor-Mixer Hierarchy\Default Work Unit\Fixture{index}"
                        ),
                        "object_type": "ActorMixer",
                    }
                ]
            }
        if operation == "object.set":
            return {
                "objects": [
                    {
                        "object": {
                            "kind": "path",
                            "value": (
                                rf"\Actor-Mixer Hierarchy\Default Work Unit\Fixture{index}"
                            ),
                        },
                        "notes": "integration harness fixture",
                    }
                ]
            }
        if operation != "switchContainer.removeAssignment":
            raise AssertionError(f"unreviewed integration fixture operation {operation}")
        switch_container = {
            "kind": "path",
            "value": r"\Actor-Mixer Hierarchy\Fixture\Player_Footsteps",
        }
        return {
            "switch_container": switch_container,
            "child": {
                "kind": "scoped-name",
                "name": "Mud",
                "type": "RandomSequenceContainer",
                "parent": switch_container,
            },
            "state_or_switch": {
                "kind": "scoped-name",
                "name": "Mud",
                "type": "Switch",
                "parent": {
                    "kind": "path",
                    "value": r"\Switches\Fixture\Surface",
                },
            },
        }

    requests = tuple(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": unit.version,
            "operation": transaction.operation,
            "arguments": fixture_arguments(
                transaction.operation,
                transaction.index,
            ),
        }
        for transaction in unit.transactions
    )
    transaction_protocol = build_transaction_protocol(requests)
    if unit.workflow_id != "weapons_query_guided_batch_cleanup":
        return transaction_protocol
    query = ExpectedGatewayStep(
        name="audit.scope",
        subcommand="query-object",
        arguments=("--path", r"\Actor-Mixer Hierarchy\Audit"),
    )
    output_bus_steps = tuple(
        ExpectedGatewayStep(
            name=f"relationship.output_bus.{index:02d}",
            subcommand="query-object",
            arguments=(
                "--object-id",
                object_id,
                "--return-field",
                "id",
                "--return-field",
                "name",
                "--return-field",
                "type",
                "--return-field",
                "path",
            ),
        )
        for index, object_id in enumerate((GUID_4, GUID_5), start=1)
    )
    identity_steps = tuple(
        ExpectedGatewayStep(
            name=f"identity.{role}",
            subcommand="query-object",
            arguments=(
                "--object-id",
                object_id,
                "--return-field",
                "id",
                "--return-field",
                "name",
                "--return-field",
                "type",
                "--return-field",
                "path",
            ),
        )
        for role, object_id in zip(
            ("audit_close", "audit_tail", "audit_mechanical"),
            (GUID_1, GUID_2, GUID_3),
            strict=True,
        )
    )
    return V3GatewayProtocol(
        (query, *output_bus_steps, *identity_steps, *transaction_protocol.steps),
        (
            1 + len(output_bus_steps),
            *(
                count + 1 + len(output_bus_steps) + len(identity_steps)
                for count in transaction_protocol.turn_prefix_counts
            ),
        ),
        commutative_read_only_step_groups=(
            tuple(step.name for step in output_bus_steps),
        ),
    )


def _visible_values(unit: WorkflowUnit, tmp_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in unit.scenario.visible_inputs:
        if item.kind == "absolute_directory_path":
            directory = (tmp_path / item.name).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            values[item.name] = str(directory)
        elif item.kind == "structured_array":
            directory = (tmp_path / item.name).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            files = []
            for spec in unit.workflow.fixture.source_files:
                path = directory / spec.file_name
                path.write_bytes(b"integration-source\n")
                files.append(str(path))
            values[item.name] = json.dumps(
                files,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        else:
            values[item.name] = rf"\Test\{item.name}"
    return values


@pytest.mark.parametrize(
    ("workflow_id", "module", "function_name", "required_reference"),
    (
        (
            "rifle_safe_reimport",
            rifle,
            "prepare_rifle_integration_runtime",
            "references/waapi-operate.md",
        ),
        (
            "footsteps_snow_assignment_maintenance",
            footsteps,
            "prepare_footsteps_integration_runtime",
            "references/waapi-operate.md",
        ),
        (
            "weapons_query_guided_batch_cleanup",
            weapons,
            "prepare_weapons_integration_runtime",
            "references/waapi-query.md",
        ),
    ),
)
def test_project_runner_wires_each_v2_runtime_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workflow_id: str,
    module: Any,
    function_name: str,
    required_reference: str,
) -> None:
    base = _unit(workflow_id)
    manifest = _manifest(tmp_path)
    unit = replace(base, baseline_manifest=manifest)
    protocol = _protocol(unit)
    visible = _visible_values(unit, tmp_path)
    dispatches: dict[str, int] = {}
    for transaction in unit.transactions:
        dispatches[transaction.api] = dispatches.get(transaction.api, 0) + 1
    captured: dict[str, Any] = {}

    def prepare(*args: Any, **kwargs: Any) -> Any:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            workflow_id=workflow_id,
            version=unit.version,
            visible_values=visible,
            protocol=protocol,
            snapshot=lambda: (workflow_id, "snapshot"),
            verify_turn=lambda _turn, _result: SimpleNamespace(
                passed=True, failures=()
            ),
            verify_final=lambda _payload, _result: SimpleNamespace(
                passed=True, failures=()
            ),
            cleanup=lambda: SimpleNamespace(passed=True, failures=()),
            observe_payload=lambda _step, _payload: None,
            expected_dispatches=tuple(dispatches.items()),
            oracle_requirements=(),
        )

    monkeypatch.setattr(module, function_name, prepare)
    runtime = SimpleNamespace(
        version=unit.version,
        scenario_root=(tmp_path / "scenario").resolve(),
        owned_root=(tmp_path / "scenario" / "owned").resolve(),
        asset_root=(tmp_path / "scenario" / "owned" / "assets").resolve(),
        io_root=(tmp_path / "scenario" / "owned" / "io").resolve(),
    )

    prepared = project_runner._prepare_integration_workflow_case(
        unit.scenario,
        runtime=runtime,
        direct=object(),
        unit=unit,
    )

    assert captured["args"] == (unit.workflow, unit.scenario)
    assert captured["kwargs"]["baseline_manifest"] is manifest
    assert captured["kwargs"]["version"] == unit.version
    assert prepared.required_reference == required_reference
    assert prepared.expected_dispatches == tuple(dispatches.items())
    assert prepared.typed_sections.live_binding["bindings"] == {
        "version": unit.version,
        "visible_values": visible,
        "baseline_manifest_sha256": manifest.digest,
    }
    if workflow_id == "weapons_query_guided_batch_cleanup":
        assert prepared.turn_reference_schedule == (
            ("references/waapi-query.md",),
            ("references/waapi-operate.md",),
            (),
        )
    else:
        assert prepared.turn_reference_schedule is None


def test_project_runner_rejects_v2_unit_without_bound_manifest(
    tmp_path: Path,
) -> None:
    unit = _unit("rifle_safe_reimport")
    runtime = SimpleNamespace(
        version=unit.version,
        scenario_root=tmp_path,
        owned_root=tmp_path / "owned",
        asset_root=tmp_path / "owned" / "assets",
        io_root=tmp_path / "owned" / "io",
    )

    with pytest.raises(
        project_runner.HeavyProjectRunnerError,
        match="sealed baseline manifest",
    ):
        project_runner._prepare_integration_workflow_case(
            unit.scenario,
            runtime=runtime,
            direct=object(),
            unit=unit,
        )


@pytest.mark.parametrize(
    ("workflow_id", "receipt_kinds", "skill_reads"),
    (
        (
            "rifle_safe_reimport",
            ("request", "confirmation"),
            (
                ("SKILL.md", "references/waapi-operate.md"),
                (),
            ),
        ),
        (
            "footsteps_snow_assignment_maintenance",
            ("request", "confirmation", "confirmation"),
            (
                ("SKILL.md", "references/waapi-operate.md"),
                (),
                (),
            ),
        ),
        (
            "weapons_query_guided_batch_cleanup",
            ("request", "confirmation", "confirmation"),
            (
                ("SKILL.md", "references/waapi-query.md"),
                ("references/waapi-operate.md",),
                (),
            ),
        ),
    ),
)
def test_campaign_preserves_v2_turn_and_reference_topology(
    workflow_id: str,
    receipt_kinds: tuple[str, ...],
    skill_reads: tuple[tuple[str, ...], ...],
) -> None:
    unit = _unit(workflow_id)

    assert tuple(
        campaign._heavy_v3_receipt_kind_for_reviewed_turn(
            unit,
            turn,
            index=index,
        )
        for index, turn in enumerate(unit.turns, start=1)
    ) == receipt_kinds
    assert campaign._heavy_v3_expected_skill_reads(unit) == skill_reads


@pytest.mark.parametrize(
    "workflow_id",
    (
        "rifle_safe_reimport",
        "footsteps_snow_assignment_maintenance",
        "weapons_query_guided_batch_cleanup",
    ),
)
def test_prompt_provenance_seals_v2_visible_inputs_and_round_trips(
    tmp_path: Path,
    workflow_id: str,
) -> None:
    unit = _unit(workflow_id)
    scenario_root = (tmp_path / workflow_id).resolve()
    (scenario_root / "owned").mkdir(parents=True)
    (scenario_root / "evidence").mkdir()
    visible = _visible_values(unit, scenario_root / "owned")
    protocol = _protocol(unit)
    rendered_values = {key: str(value) for key, value in visible.items()}
    prompts = tuple(
        turn.prompt.format_map(rendered_values) for turn in unit.turns
    )
    assert prompts[0] == unit.scenario.render_prompt(visible)
    assert all("{" not in prompt and "}" not in prompt for prompt in prompts)

    evidence = write_prompt_provenance(
        scenario=unit.scenario,
        version=unit.version,
        scenario_root=scenario_root,
        prompts=prompts,
        visible_values=visible,
        protocol=protocol,
        trusted_sources={"integration_visible_inputs": visible},
    )
    restored = read_prompt_provenance(
        evidence.path,
        scenario=unit.scenario,
        version=unit.version,
        scenario_root=scenario_root,
        expected_prompts=prompts,
        expected_protocol=protocol,
        require_paths=True,
    )

    assert restored.payload == evidence.payload
    assert restored.payload["trusted_sources"][
        "integration_visible_inputs"
    ]["workflow_id"] == workflow_id
    assert campaign._heavy_v3_reviewed_prompts(unit, restored) == prompts


def test_campaign_reviewed_v2_prompts_reject_incomplete_sealed_values(
    tmp_path: Path,
) -> None:
    unit = _unit("footsteps_snow_assignment_maintenance")
    scenario_root = (tmp_path / unit.workflow_id).resolve()
    (scenario_root / "owned").mkdir(parents=True)
    (scenario_root / "evidence").mkdir()
    visible = _visible_values(unit, scenario_root / "owned")
    protocol = _protocol(unit)
    prompts = tuple(
        turn.prompt.format_map(visible) for turn in unit.turns
    )
    evidence = write_prompt_provenance(
        scenario=unit.scenario,
        version=unit.version,
        scenario_root=scenario_root,
        prompts=prompts,
        visible_values=visible,
        protocol=protocol,
        trusted_sources={"integration_visible_inputs": visible},
    )
    damaged = replace(
        evidence,
        visible_values={
            key: value
            for key, value in evidence.visible_values.items()
            if key != "surface_group_path"
        },
    )

    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="inputs differ from sealed provenance",
    ):
        campaign._heavy_v3_reviewed_prompts(unit, damaged)


def test_campaign_rebinds_v2_business_plan_to_exact_manifest(
    tmp_path: Path,
) -> None:
    unit = replace(
        _unit("weapons_query_guided_batch_cleanup"),
        baseline_manifest=_manifest(tmp_path),
    )
    protocol = _protocol(unit)
    visible = _visible_values(unit, tmp_path)
    sections = project_runner._compile_integration_workflow_plan(
        unit=unit,
        protocol=protocol,
        visible_values=visible,
        oracle_requirements=(),
        baseline_manifest_digest=unit.baseline_manifest.digest,
    )

    parsed = campaign._validate_heavy_v3_typed_business_plan(
        sections.writer_kwargs(),
        expected_unit=unit,
        provenance=SimpleNamespace(protocol=protocol, visible_values=visible),
    )

    assert parsed.writer_kwargs() == sections.writer_kwargs()

    cross_bound = project_runner._compile_integration_workflow_plan(
        unit=unit,
        protocol=protocol,
        visible_values=visible,
        oracle_requirements=(),
        baseline_manifest_digest=SHA_B,
    )
    with pytest.raises(
        campaign.CampaignEvidenceError,
        match="sealed baseline manifest",
    ):
        campaign._validate_heavy_v3_typed_business_plan(
            cross_bound.writer_kwargs(),
            expected_unit=unit,
            provenance=SimpleNamespace(
                protocol=protocol,
                visible_values=visible,
            ),
        )


def _with_snapshot_digest(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["digest"] = campaign._canonical_sha256(value)
    return result


def _file_proof(root: Path, name: str) -> dict[str, Any]:
    relative = Path("Originals", "SFX", name)
    return {
        "path": str((root / relative).resolve()),
        "relative_path": relative.as_posix(),
        "size": 4,
        "sha256": SHA_A,
    }


def _snapshot(workflow_id: str, *, changed: bool, root: Path) -> dict[str, Any]:
    state = {"parent": GUID_2, "marker": 2 if changed else 1}
    common: dict[str, Any] = {
        "workflow_id": workflow_id,
        "version": "2022.1",
        "objects": [
            {
                "role": "sound",
                "id": GUID_1,
                "name": "Sound",
                "type": "Sound",
                "path": r"\Actor-Mixer Hierarchy\Sound",
                "state": state,
            }
        ],
        "media": [
            {
                "role": "sound",
                "sound_id": GUID_1,
                "active_source_id": GUID_3,
                "source_parent_id": GUID_1,
                "language": "SFX",
                "original": _file_proof(root, "sound.wav"),
            }
        ],
        "source_project": {
            "project_sha256": SHA_A,
            "tree_sha256": SHA_B,
            "project_mtime_ns": 1,
        },
    }
    if workflow_id == "rifle_safe_reimport":
        common.update(
            {
                "absent_roles": [],
                "container_children": [],
                "input_files": [
                    {"key": "rifle", **_file_proof(root, "rifle.wav")}
                ],
            }
        )
    elif workflow_id == "footsteps_snow_assignment_maintenance":
        common.update(
            {
                "absent_roles": [],
                "children": [],
                "assignments": [],
                "input_files": [
                    {"key": "snow", **_file_proof(root, "snow.wav")}
                ],
            }
        )
    return _with_snapshot_digest(common)


def _rifle_runtime_snapshot(*, changed: bool, root: Path) -> rifle.RifleSnapshot:
    relative = Path("Originals", "SFX", "sound.wav")
    original = rifle.RifleFileProof(
        str((root / relative).resolve()),
        relative.as_posix(),
        4,
        SHA_A,
    )
    source = rifle.RifleSourceProjectProof(SHA_A, SHA_B, 1)
    snapshot = rifle.RifleSnapshot(
        workflow_id="rifle_safe_reimport",
        version="2022.1",
        objects=(
            rifle.RifleObjectState(
                "sound",
                GUID_1,
                "Sound",
                "Sound",
                r"\Actor-Mixer Hierarchy\Sound",
                MappingProxyType({} if not changed else {"marker": 2}),
            ),
        ),
        absent_roles=(),
        media=(
            rifle.RifleMediaState(
                "sound",
                GUID_1,
                GUID_3,
                GUID_1,
                "SFX",
                original,
            ),
        ),
        container_children=(),
        input_files=(("rifle", original),),
        source_project=source,
        digest="",
    )
    serial = snapshot.as_dict()
    serial.pop("digest")
    return replace(snapshot, digest=campaign._canonical_sha256(serial))


def test_runner_archives_v2_runtime_as_dict_projection(tmp_path: Path) -> None:
    unit = _unit("rifle_safe_reimport")
    verification = rifle.RifleVerification(
        phase="after_import",
        passed=True,
        failures=(),
        assertions=MappingProxyType(
            {
                assertion: True
                for assertion in EXPECTED_ASSERTION_IDS[unit.workflow_id]
            }
        ),
        before=_rifle_runtime_snapshot(changed=False, root=tmp_path),
        after=_rifle_runtime_snapshot(changed=True, root=tmp_path),
    )

    evidence = project_runner._oracle_evidence(
        scenario=unit.scenario,
        version=unit.version,
        runner="project",
        business_oracle_plan_sha256=SHA_A,
        verification=verification,
    )

    archived = evidence["verification"]
    assert "id" in archived["before"]["objects"][0]
    assert "object_id" not in archived["before"]["objects"][0]
    campaign._validate_integration_v2_verification(
        archived,
        workflow_id=unit.workflow_id,
        version=unit.version,
        label=unit.workflow_id,
    )


@pytest.mark.parametrize(
    ("workflow_id", "phase"),
    (
        ("rifle_safe_reimport", "after_import"),
        (
            "footsteps_snow_assignment_maintenance",
            "after_mud_assignment_removal",
        ),
        ("weapons_query_guided_batch_cleanup", "after_batch"),
    ),
)
def test_campaign_accepts_only_closed_v2_runtime_verification_shape(
    workflow_id: str,
    phase: str,
    tmp_path: Path,
) -> None:
    verification = {
        "phase": phase,
        "passed": True,
        "failures": [],
        "assertions": {
            key: True for key in EXPECTED_ASSERTION_IDS[workflow_id]
        },
        "before": _snapshot(workflow_id, changed=False, root=tmp_path),
        "after": _snapshot(workflow_id, changed=True, root=tmp_path),
    }

    campaign._validate_integration_v2_verification(
        verification,
        workflow_id=workflow_id,
        version="2022.1",
        label=workflow_id,
    )

    verification["unexpected"] = True
    with pytest.raises(campaign.CampaignEvidenceError, match="not closed"):
        campaign._validate_integration_v2_verification(
            verification,
            workflow_id=workflow_id,
            version="2022.1",
            label=workflow_id,
        )


@pytest.mark.parametrize(
    "workflow_id",
    (
        "rifle_safe_reimport",
        "footsteps_snow_assignment_maintenance",
        "weapons_query_guided_batch_cleanup",
    ),
)
def test_campaign_accepts_exact_runtime_cleanup_as_dict(
    workflow_id: str,
    tmp_path: Path,
) -> None:
    if workflow_id == "rifle_safe_reimport":
        cleanup = rifle.RifleCleanupProof(
            True,
            False,
            str((tmp_path / "rifle-input").resolve()),
            True,
            True,
            (),
        ).as_dict()
    elif workflow_id == "footsteps_snow_assignment_maintenance":
        cleanup = footsteps.FootstepsCleanupProof(
            True,
            False,
            str((tmp_path / "footsteps-input").resolve()),
            True,
            True,
            (),
        ).as_dict()
    else:
        cleanup = weapons.WeaponsCleanupProof(
            True, False, True, True, ()
        ).as_dict()
    campaign._validate_integration_v2_cleanup(
        cleanup,
        workflow_id=workflow_id,
    )

    cleanup["unexpected"] = True
    with pytest.raises(campaign.CampaignEvidenceError, match="not closed"):
        campaign._validate_integration_v2_cleanup(
            cleanup,
            workflow_id=workflow_id,
        )
