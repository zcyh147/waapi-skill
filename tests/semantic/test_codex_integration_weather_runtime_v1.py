from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Mapping

import pytest

from tests.semantic.support.codex_gateway_broker import (
    DraftActionJsonArgument,
    GatewayDerivedReferenceActivationAllowance,
    MetadataBoundJsonArgument,
    MetadataTokenProjection,
    gateway_step_sequence_matches,
)
from tests.semantic.support.codex_integration_weather_runtime_v1 import (
    ACTION_METADATA_QUERIES,
    ACTION_TOKENS,
    RAIN_PARAMETER_PATH,
    RTPC_POINTS,
    SOUND_METADATA_QUERIES,
    SOUND_TOKENS,
    IntegrationWeatherRuntimeError,
    WeatherTarget,
    WorkflowVerification,
    _build_metadata_workflow_protocol,
    _copied_original_proof,
    _gateway_derived_reference_activation_allowances,
    _metadata_dependency_properties,
    _read_rtpcs,
    _weather_action_request,
    _weather_import_request,
    _weather_plan_transactions,
    _weather_rtpc_request,
    _workflow_plan_steps,
    prepare_weather_workflow,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    deserialize_protocol,
    serialize_protocol,
)
from tests.semantic.support.codex_workflow_business_plan_v3 import (
    compile_workflow_business_plan_sections,
)


def _targets(tmp_path: Path) -> tuple[WeatherTarget, ...]:
    rows = (
        ("Rain_Bed", r"Weather_Interactive\Rain\Rain_Bed", -4.0, 2, 0.25, 0.0),
        ("Wind_Bed", r"Weather_Interactive\Wind\Wind_Bed", -6.0, 2, 0.4, 0.1),
        ("Thunder_Near", r"Weather_Interactive\Thunder\Thunder_Near", -2.0, 1, 0.05, 0.0),
        ("Thunder_Mid", r"Weather_Interactive\Thunder\Thunder_Mid", -8.0, 1, 0.12, 0.08),
        ("Thunder_Far", r"Weather_Interactive\Thunder\Thunder_Far", -14.0, 1, 0.25, 0.16),
    )
    return tuple(
        WeatherTarget(
            key=name.casefold(),
            name=name,
            logical_path=rf"\Actor-Mixer Hierarchy\Default Work Unit\IntegrationLab\{relative}",
            event_path=rf"\Events\Default Work Unit\Integration_Weather\Play_{name}",
            source_path=tmp_path / f"{name}.wav",
            volume=volume,
            looping=True,
            instance_limit=limit,
            fade_time=fade,
            delay=delay,
        )
        for name, relative, volume, limit, fade, delay in rows
    )


def _projection(tokens: tuple[str, ...]) -> tuple[MetadataTokenProjection, ...]:
    return tuple(
        MetadataTokenProjection(
            token,
            "reference" if token == "OutputBus" else "property",
            "object" if token == "OutputBus" else "number",
        )
        for token in tokens
    )


def test_weather_runtime_accepts_profile_proxy_scenario_family(
    tmp_path: Path,
) -> None:
    scenario = SimpleNamespace(
        id="INT22-INTERACTIVE-WEATHER-BUILD",
        scenario_family="interactive_weather_build",
    )

    with pytest.raises(
        IntegrationWeatherRuntimeError,
        match="does not support Wwise 2024.1",
    ):
        prepare_weather_workflow(
            scenario,
            version="2024.1",
            scenario_root=tmp_path,
            owned_root=tmp_path,
            sandbox_project_root=tmp_path,
            direct=lambda *_args, **_kwargs: {},
        )


@pytest.mark.skipif(os.name == "nt", reason="Wine aliases are POSIX-host paths")
def test_weather_copied_original_proof_hashes_wine_y_inside_sandbox(
    tmp_path: Path,
) -> None:
    account_home = tmp_path / "account-home"
    sandbox_root = account_home / "campaign" / "sandbox"
    copied = sandbox_root / "Originals" / "SFX" / "~archive" / "Rain.wav"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(b"weather-copied-original\n")
    relative = copied.relative_to(account_home)
    wine_path = str(PureWindowsPath("Y:/").joinpath(*relative.parts))

    proof = _copied_original_proof(
        wine_path,
        sandbox_root=sandbox_root,
        account_home=account_home,
    )

    assert proof["path"] == str(copied)
    assert proof["sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest()


@pytest.mark.skipif(os.name == "nt", reason="Wine aliases are POSIX-host paths")
def test_weather_copied_original_proof_rejects_wine_y_outside_sandbox(
    tmp_path: Path,
) -> None:
    account_home = tmp_path / "account-home"
    sandbox_root = account_home / "campaign" / "sandbox"
    (sandbox_root / "Originals").mkdir(parents=True)
    outside = account_home / "other" / "Originals" / "Rain.wav"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"weather-copied-original\n")
    relative = outside.relative_to(account_home)
    wine_path = str(PureWindowsPath("Y:/").joinpath(*relative.parts))

    with pytest.raises(IntegrationWeatherRuntimeError, match="escapes the sandbox"):
        _copied_original_proof(
            wine_path,
            sandbox_root=sandbox_root,
            account_home=account_home,
        )


@pytest.mark.skipif(os.name != "nt", reason="native Windows path semantics required")
def test_weather_copied_original_proof_accepts_native_case_alias(
    tmp_path: Path,
) -> None:
    sandbox_root = tmp_path / "sandbox"
    copied = sandbox_root / "Originals" / "SFX" / "Rain.wav"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(b"weather-native-case-alias\n")
    case_alias = sandbox_root / "oRIGINALS" / "sfx" / "RAIN.WAV"

    proof = _copied_original_proof(
        str(case_alias),
        sandbox_root=sandbox_root,
    )

    assert PureWindowsPath(str(proof["path"])) == PureWindowsPath(str(copied))
    assert proof["sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest()


def test_weather_requests_close_five_sound_action_and_rtpc_requirements(
    tmp_path: Path,
) -> None:
    targets = _targets(tmp_path)
    bus = r"\Master-Mixer Hierarchy\Default Work Unit\Weather_Bus"

    import_request = _weather_import_request(
        "2022.1",
        targets=targets,
        weather_root=r"\Actor-Mixer Hierarchy\Default Work Unit\IntegrationLab",
        weather_bus=bus,
        dependency_properties=(
            {"name": "OverrideOutput_Live", "value": True},
        ),
    )
    rows = import_request["arguments"]["imports"]
    assert rows[:4] == [
        {
            "object_path": (
                r"\Actor-Mixer Hierarchy\Default Work Unit"
                r"\IntegrationLab\Weather_Interactive"
            ),
            "object_type": "ActorMixer",
        },
        {
            "object_path": (
                r"\Actor-Mixer Hierarchy\Default Work Unit"
                r"\IntegrationLab\Weather_Interactive\Rain"
            ),
            "object_type": "ActorMixer",
        },
        {
            "object_path": (
                r"\Actor-Mixer Hierarchy\Default Work Unit"
                r"\IntegrationLab\Weather_Interactive\Wind"
            ),
            "object_type": "ActorMixer",
        },
        {
            "object_path": (
                r"\Actor-Mixer Hierarchy\Default Work Unit"
                r"\IntegrationLab\Weather_Interactive\Thunder"
            ),
            "object_type": "RandomSequenceContainer",
        },
    ]
    media_rows = rows[4:]
    assert len(media_rows) == 5
    assert [row["event"]["path"] for row in media_rows] == [
        target.event_path for target in targets
    ]
    for row, target in zip(media_rows, targets, strict=True):
        properties = {
            item["name"]: item["value"] for item in row["properties"]
        }
        assert properties == {
            "IsLoopingEnabled": True,
            "IsLoopingInfinite": True,
            "IgnoreParentMaxSoundInstance": True,
            "UseMaxSoundPerInstance": True,
            "MaxSoundPerInstance": target.instance_limit,
            "Volume": target.volume,
            "OverrideOutput_Live": True,
        }
        assert row["references"] == [
            {
                "name": "OutputBus",
                "target": {"kind": "path", "value": bus},
            }
        ]

    action_request = _weather_action_request("2022.1", targets=targets)
    assert len(action_request["arguments"]["objects"]) == 5
    for row, target in zip(
        action_request["arguments"]["objects"],
        targets,
        strict=True,
    ):
        assert row["object"] == {
            "kind": "direct-child",
            "parent": {
                "kind": "path",
                "value": target.event_path,
            },
            "type": "Action",
        }
        assert {item["name"]: item["value"] for item in row["properties"]} == {
            "FadeTime": target.fade_time,
            "Delay": target.delay,
        }

    rtpc_request = _weather_rtpc_request(
        "2022.1",
        target=targets[0],
        control_input=RAIN_PARAMETER_PATH,
    )
    assert rtpc_request["arguments"] == {
        "object": {"kind": "path", "value": targets[0].logical_path},
        "property": "Volume",
        "control_input": {"kind": "path", "value": RAIN_PARAMETER_PATH},
        "points": [dict(point) for point in RTPC_POINTS],
        "mode": "add_or_replace",
    }


def test_weather_dependency_closure_uses_only_exact_live_names_and_values() -> None:
    result = {
        "dependency_closure_complete": True,
        "unresolved_dependencies": [],
        "candidates": [
            {
                "name": "OutputBus",
                "kind": "reference",
                "dependency_requirements": [
                    {
                        "type": "override",
                        "action": "Enable",
                        "context": "Self",
                        "property": "LiveOutputOverride",
                        "required_values": [True],
                    }
                ],
            },
            {
                "name": "Volume",
                "kind": "property",
                "dependency_requirements": [],
            },
        ],
        "dependency_candidates": [
            {
                "name": "LiveOutputOverride",
                "kind": "property",
                "dependency_requirements": [],
                "metadata": {"type": "Boolean"},
            }
        ],
    }

    assert _metadata_dependency_properties(
        result,
        selected_tokens=("Volume", "OutputBus"),
    ) == ({"name": "LiveOutputOverride", "value": True},)

    targets = _targets(Path("/owned"))
    request = _weather_import_request(
        "2022.1",
        targets=targets,
        weather_root=(
            r"\Actor-Mixer Hierarchy\Default Work Unit\IntegrationLab"
        ),
        weather_bus=(
            r"\Master-Mixer Hierarchy\Default Work Unit\Weather_Bus"
        ),
        dependency_properties=(
            {"name": "LiveOutputOverride", "value": True},
        ),
    )
    allowances = _gateway_derived_reference_activation_allowances(
        result,
        selected_tokens=("Volume", "OutputBus"),
        expected_request=request,
    )
    assert tuple(item.as_dict() for item in allowances) == tuple(
        {
            "row_index": row_index,
            "property_name": "LiveOutputOverride",
            "property_value": True,
            "reference_name": "OutputBus",
        }
        for row_index in range(4, 9)
    )

    result["candidates"][0]["dependency_requirements"][0]["action"] = "Disable"
    assert _gateway_derived_reference_activation_allowances(
        result,
        selected_tokens=("Volume", "OutputBus"),
        expected_request=request,
    ) == ()
    result["candidates"][0]["dependency_requirements"][0]["action"] = "Enable"
    result["candidates"][0]["dependency_requirements"][0]["required_values"] = []
    with pytest.raises(
        IntegrationWeatherRuntimeError,
        match="does not prove one exact property value",
    ):
        _metadata_dependency_properties(
            result,
            selected_tokens=("Volume", "OutputBus"),
        )


def test_weather_protocol_and_business_plan_cover_all_three_transactions(
    tmp_path: Path,
) -> None:
    targets = _targets(tmp_path)
    activation_allowances = tuple(
        GatewayDerivedReferenceActivationAllowance(
            row_index=row_index,
            property_name="LiveOutputOverride",
            property_value=True,
            reference_name="OutputBus",
        )
        for row_index in range(4, 9)
    )
    sound_tokens = (*SOUND_TOKENS, "LiveOutputOverride")
    sound_projection = (
        *_projection(SOUND_TOKENS),
        MetadataTokenProjection(
            "LiveOutputOverride",
            "property",
            "Boolean",
        ),
    )
    requests = (
        _weather_import_request(
            "2022.1",
            targets=targets,
            weather_root=(
                r"\Actor-Mixer Hierarchy\Default Work Unit\IntegrationLab"
            ),
            weather_bus=r"\Master-Mixer Hierarchy\Default Work Unit\Weather_Bus",
            dependency_properties=(
                {"name": "LiveOutputOverride", "value": True},
            ),
        ),
        _weather_action_request("2022.1", targets=targets),
        _weather_rtpc_request(
            "2022.1",
            target=targets[0],
            control_input=RAIN_PARAMETER_PATH,
        ),
    )
    protocol = _build_metadata_workflow_protocol(
        requests,
        metadata=(
            (
                "Sound",
                SOUND_METADATA_QUERIES,
                sound_tokens,
                sound_projection,
                "audio_import_v1",
            ),
            (
                "Action",
                ACTION_METADATA_QUERIES,
                ACTION_TOKENS,
                _projection(ACTION_TOKENS),
                "object_set_v1",
            ),
            None,
        ),
        gateway_derived_reference_activations=(
            activation_allowances,
            (),
            (),
        ),
    )
    assert len(protocol.turn_prefix_counts) == 4
    metadata_steps = [
        step for step in protocol.steps if step.subcommand == "metadata"
    ]
    assert [step.name for step in metadata_steps] == [
        "tx01.metadata",
        "tx02.metadata",
    ]
    assert [step.arguments[-2:] for step in metadata_steps] == [
        ("--limit", "2"),
        ("--limit", "8"),
    ]
    assert protocol.commutative_read_only_step_groups == (
        ("tx01.metadata", "tx01.operation-schema"),
        ("tx02.operation-schema", "tx02.metadata"),
    )
    assert [
        (step.name, step.subcommand)
        for step in protocol.steps
        if step.subcommand in {"metadata", "operation-schema"}
    ] == [
        ("tx01.metadata", "metadata"),
        ("tx01.operation-schema", "operation-schema"),
        ("tx02.operation-schema", "operation-schema"),
        ("tx02.metadata", "metadata"),
        ("tx03.operation-schema", "operation-schema"),
    ]
    assert [step.name for step in protocol.steps if step.subcommand == "execute"] == [
        "tx01.execute",
        "tx02.execute",
        "tx03.execute",
    ]
    groups = protocol.commutative_read_only_step_groups
    for canonical in (
        ("tx01.metadata", "tx01.operation-schema", "tx01.preview"),
    ):
        first, second, preview_name = canonical
        assert gateway_step_sequence_matches(canonical, canonical, groups)
        assert gateway_step_sequence_matches(
            canonical,
            (second, first, preview_name),
            groups,
        )
        assert not gateway_step_sequence_matches(
            canonical,
            (first, first, preview_name),
            groups,
        )
        assert not gateway_step_sequence_matches(
            canonical,
            (second, second, preview_name),
            groups,
        )
        assert not gateway_step_sequence_matches(
            canonical,
            (first, preview_name),
            groups,
        )
        assert not gateway_step_sequence_matches(
            canonical,
            (second, preview_name),
            groups,
        )
        assert not gateway_step_sequence_matches(
            canonical,
            (first, preview_name, second),
            groups,
        )
    import_preview = next(
        step for step in protocol.steps if step.name == "tx01.preview"
    )
    assert import_preview.subcommand == "preview-from-draft"
    assert "--request-json" not in import_preview.arguments
    import_actions = [
        step.arguments[-1]
        for step in protocol.steps
        if step.name.startswith("tx01.action.")
    ]
    assert import_actions
    assert all(
        isinstance(argument, DraftActionJsonArgument)
        and argument.operation == "audio.import"
        for argument in import_actions
    )
    metadata_bound_actions = [
        argument
        for argument in import_actions
        if argument.metadata_binding is not None
    ]
    assert metadata_bound_actions
    assert all(
        argument.metadata_binding.step == "tx01.metadata"
        and argument.metadata_binding.required_tokens == sound_tokens
        and argument.metadata_binding.expected_projection == sound_projection
        for argument in metadata_bound_actions
    )
    action_preview = next(
        step for step in protocol.steps if step.name == "tx02.preview"
    )
    assert action_preview.subcommand == "preview-from-draft"
    assert "--request-json" not in action_preview.arguments
    action_steps = [
        step
        for step in protocol.steps
        if step.name.startswith("tx02.action.")
    ]
    assert len(action_steps) == 5
    assert all(step.subcommand == "draft-apply" for step in action_steps)
    assert all(
        isinstance(step.arguments[-1], DraftActionJsonArgument)
        for step in action_steps
    )
    assert action_steps[0].arguments[-1].expected == {
        "contract": "waapi-skill.operation-draft-action/v1",
        "action": "add_target",
        "selector": {
            "kind": "direct-child",
            "parent": {
                "kind": "path",
                "value": targets[0].event_path,
            },
            "type": "Action",
        },
        "properties": [
            {"name": "FadeTime", "value": targets[0].fade_time},
            {"name": "Delay", "value": targets[0].delay},
        ],
    }
    add_targets = [
        step.arguments[-1].expected
        for step in action_steps
        if step.arguments[-1].expected["action"] == "add_target"
    ]
    assert [
        (row["selector"], row["properties"])
        for row in add_targets
    ] == [
        (
            {
                "kind": "direct-child",
                "parent": {
                    "kind": "path",
                    "value": target.event_path,
                },
                "type": "Action",
            },
            [
                {"name": "FadeTime", "value": target.fade_time},
                {"name": "Delay", "value": target.delay},
            ],
        )
        for target in targets
    ]
    assert not any(
        step.subcommand == "preview" and step.name.startswith("tx02.")
        for step in protocol.steps
    )
    rtpc_schema_index = next(
        index
        for index, step in enumerate(protocol.steps)
        if step.name == "tx03.operation-schema"
    )
    assert protocol.steps[rtpc_schema_index + 1].name == "tx03.preview"
    rtpc_preview = protocol.steps[rtpc_schema_index + 1]
    assert isinstance(rtpc_preview.arguments[2], MetadataBoundJsonArgument)
    assert rtpc_preview.arguments[2].metadata_step == "tx01.metadata"
    assert rtpc_preview.arguments[2].object_type == "Sound"
    assert rtpc_preview.arguments[2].required_tokens == ("Volume",)
    assert tuple(
        item.name
        for item in (
            rtpc_preview.arguments[2].expected_required_token_projection or ()
        )
    ) == ("Volume",)
    assert rtpc_preview.arguments[2].equivalence == "object_set_rtpc_v1"
    serialized = serialize_protocol(protocol)
    serialized_action_steps = [
        step
        for step in serialized["steps"]
        if step["name"].startswith("tx02.action.")
    ]
    assert all(
        step["arguments"][-1]["kind"] == "draft_action_json"
        for step in serialized_action_steps
    )
    assert deserialize_protocol(serialized) == protocol
    plan_steps = _workflow_plan_steps(
        protocol,
        transaction_phases=(
            "import_weather_assets",
            "configure_event_actions",
            "bind_rain_intensity_rtpc",
        ),
    )
    assert [row["name"] for row in plan_steps] == [
        *(step.name for step in protocol.steps),
        "cleanup.success",
    ]
    assert tuple(row["operation"] for row in _weather_plan_transactions()) == (
        "audio.import",
        "object.set",
        "object.setRTPC",
    )
    compiled = compile_workflow_business_plan_sections(
        workflow_id="interactive_weather_build",
        transactions=_weather_plan_transactions(),
        workflow_steps=plan_steps,
        diagnostic_evidence=(),
        live_bindings={"version": "2022.1", "visible_values": {}},
        transaction_expectations=tuple(
            {
                "transaction_id": f"tx{index:02d}",
                "expectation": {"checked": True},
            }
            for index in range(1, 4)
        ),
    )
    assert compiled.static_expectation["workflow_steps"]
    from tests.semantic import run_codex_skill_campaign as campaign

    campaign._validate_integration_workflow_business_plan(
        compiled,
        expected_unit=SimpleNamespace(
            workflow_id="interactive_weather_build",
            version="2022.1",
            transactions=tuple(
                SimpleNamespace(api=row["api"], operation=row["operation"])
                for row in _weather_plan_transactions()
            ),
        ),
        provenance=SimpleNamespace(protocol=protocol, visible_values={}),
    )


def test_weather_verification_fails_closed() -> None:
    passed = WorkflowVerification("interactive_weather_build", "phase", True, (), {})
    passed.assert_passed()

    failed = WorkflowVerification(
        "interactive_weather_build",
        "phase",
        False,
        ("mismatch",),
        {},
    )
    with pytest.raises(IntegrationWeatherRuntimeError, match="mismatch"):
        failed.assert_passed()


def test_weather_hidden_rtpc_observer_reads_owner_accessor_then_exact_ids() -> None:
    owner_id = "{11111111-1111-1111-1111-111111111111}"
    rtpc_id = "{22222222-2222-2222-2222-222222222222}"
    calls: list[tuple[str, dict[str, object], dict[str, object]]] = []
    responses = iter(
        (
            {
                "return": [
                    {
                        "id": owner_id,
                        "@RTPC": [{"id": rtpc_id}],
                    }
                ]
            },
            {
                "return": [
                    {
                        "id": rtpc_id,
                        "name": "",
                        "type": "RTPC",
                        "path": r"\Containers\Default Work Unit\Rain_Bed\[RTPC]",
                        "notes": "",
                        "@PropertyName": "Volume",
                        "@ControlInput": {
                            "id": "{33333333-3333-3333-3333-333333333333}"
                        },
                        "@Curve": {
                            "points": [
                                {"x": 0.0, "y": -48.0, "shape": "Linear"}
                            ]
                        },
                    }
                ]
            },
        )
    )

    def direct(
        uri: str,
        args: Mapping[str, object],
        options: Mapping[str, object],
    ) -> object:
        calls.append((uri, dict(args), dict(options)))
        return next(responses)

    rows = _read_rtpcs(direct, owner_id)

    assert [row["id"] for row in rows] == [rtpc_id]
    assert calls == [
        (
            "ak.wwise.core.object.get",
            {"from": {"id": [owner_id]}},
            {"return": ["id", "@RTPC"]},
        ),
        (
            "ak.wwise.core.object.get",
            {"from": {"id": [rtpc_id]}},
            {
                "return": [
                    "id",
                    "name",
                    "type",
                    "path",
                    "notes",
                    "@PropertyName",
                    "@ControlInput",
                    "@Curve",
                ]
            },
        ),
    ]


def test_weather_hidden_rtpc_observer_treats_omitted_accessor_as_empty() -> None:
    owner_id = "{11111111-1111-1111-1111-111111111111}"
    calls: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def direct(
        uri: str,
        args: Mapping[str, object],
        options: Mapping[str, object],
    ) -> object:
        calls.append((uri, dict(args), dict(options)))
        return {"return": [{"id": owner_id}]}

    assert _read_rtpcs(direct, owner_id) == ()
    assert calls == [
        (
            "ak.wwise.core.object.get",
            {"from": {"id": [owner_id]}},
            {"return": ["id", "@RTPC"]},
        )
    ]


@pytest.mark.parametrize("raw_references", (None, {}, "", ()))
def test_weather_hidden_rtpc_observer_rejects_present_non_array(
    raw_references: object,
) -> None:
    owner_id = "{11111111-1111-1111-1111-111111111111}"

    def direct(
        uri: str,
        args: Mapping[str, object],
        options: Mapping[str, object],
    ) -> object:
        return {"return": [{"id": owner_id, "@RTPC": raw_references}]}

    with pytest.raises(
        IntegrationWeatherRuntimeError,
        match="did not return an @RTPC array",
    ):
        _read_rtpcs(direct, owner_id)
