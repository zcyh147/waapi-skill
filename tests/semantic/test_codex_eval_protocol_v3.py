from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.platform_filesystem import native_absolute_test_path
from tests.semantic.support.codex_eval_protocol_v3 import (
    CompoundUndoChildExpectation,
    StructuredRefusal,
    V3GatewayProtocol,
    V3ProtocolError,
    build_audio_import_composer_transaction_steps,
    build_compound_undo_business_transaction_steps,
    build_direct_protocol,
    build_exact_artifact_business_transaction_steps,
    build_metadata_transaction_protocol,
    build_object_lifecycle_business_transaction_steps,
    build_object_metadata_business_transaction_steps,
    build_switch_assignment_business_transaction_steps,
    build_object_set_composer_transaction_steps,
    build_schema_query_transaction_protocol,
    build_transaction_protocol,
    call_step,
    metadata_candidate_limit,
    query_object_step,
    typed_read_draft_steps,
    wait_topic_step,
)
from tests.semantic.support.codex_gateway_broker import (
    DraftActionQueryIdentityBinding,
    DraftActionResponseBinding,
    DraftTypedActionArgument,
    DraftTypedActionBatchArgument,
    DraftActionMetadataBinding,
    ExpectedGatewayStep,
    MetadataQueryArgument,
    MetadataTokenProjection,
    ResponseBinding,
    TypedRequestFactsArgument,
    validate_commutative_composer_setup_step_groups,
)
from tests.semantic.support.codex_object_heavy_v3 import (
    build_object_heavy_v3_recipe,
)
from tests.semantic.support.codex_typed_input_profile import (
    load_typed_input_profile,
)
from tests.semantic.support.typed_gateway_input import (
    _authoring_ui_command_suffix_matches,
    _authoring_ui_plan_suffix_matches,
    _soundbank_plan_suffix_matches,
)
from wwise_waapi.operation_composer import typed_action_cli_arguments
from wwise_waapi.builders.debug_lua import LUA_SOURCE_AUTHORITY
from wwise_waapi.platform_commands import encode_windows_powershell_argv


def _request(index: int = 1) -> dict[str, object]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "lua.executeCoreInline",
        "arguments": {
            "lua_code": f"return {index}\n",
            "io_root": native_absolute_test_path("lua-protocol-root"),
            "source_authority": LUA_SOURCE_AUTHORITY,
        },
    }


def test_authoring_ui_business_suffixes_match_only_closed_public_flags() -> None:
    assert _authoring_ui_plan_suffix_matches(
        "ui.commands.execute",
        ["--command-id", "SaveProject", "--value", "boolean", "true"],
    )
    assert _authoring_ui_plan_suffix_matches(
        "ui.commands.register",
        ["--command-count", "2"],
    )
    assert _authoring_ui_plan_suffix_matches(
        "ui.commands.unregister",
        ["--registered-command-key", "notify-selection"],
    )
    assert _authoring_ui_command_suffix_matches(
        [
            "--key",
            "notify-selection",
            "--display-name",
            "Notify",
            "--handler-kind",
            "notification",
        ]
    )


def test_authoring_ui_business_suffixes_reject_native_or_unsafe_inputs() -> None:
    assert not _authoring_ui_plan_suffix_matches(
        "ui.commands.register",
        ["--command-count", "1", "--source-authority", "user_supplied_verbatim"],
    )
    assert not _authoring_ui_command_suffix_matches(
        [
            "--key",
            "program",
            "--display-name",
            "Program",
            "--handler-kind",
            "program",
            "--handler-path",
            "/owned/tool",
            "--argument-token=--unsafe",
        ]
    )


def test_exact_artifact_business_steps_hide_lua_loader_fields(
    tmp_path: Path,
) -> None:
    request = _request()
    request["arguments"]["io_root"] = str(tmp_path)
    request["arguments"]["wa_args"] = {
        "name": "Weather",
        "enabled": True,
        "missing": None,
        "rows": [1, 2],
    }

    steps = build_exact_artifact_business_transaction_steps(
        request,
        label="tx01",
    )

    assert [step.subcommand for step in steps] == [
        "operation-schema",
        "draft-start",
        "draft-declare-artifact-plan",
        "draft-check",
        "preview-from-draft",
    ]
    declaration = steps[2]
    assert "--source-authority" not in declaration.arguments
    assert "--argument" in declaration.arguments
    lua_index = declaration.arguments.index("--lua-source")
    assert declaration.arguments[lua_index : lua_index + 4] == (
        "--lua-source",
        request["arguments"]["lua_code"],
        "--io-root",
        request["arguments"]["io_root"],
    )
    assert steps[-1].expected_operation_request == request


def test_exact_artifact_tab_steps_bind_location_and_translate_mode() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.importTabDelimited",
        "arguments": {
            "import_file": "/owned/import.tsv",
            "import_location": {
                "kind": "path",
                "value": r"\Actor-Mixer Hierarchy\Default Work Unit",
            },
            "import_language": "SFX",
            "import_operation": "useExisting",
            "auto_add_to_source_control": False,
        },
    }

    steps = build_exact_artifact_business_transaction_steps(
        request,
        label="tx01",
    )

    assert [step.subcommand for step in steps] == [
        "operation-schema",
        "draft-start",
        "draft-bind-object",
        "draft-declare-artifact-plan",
        "draft-check",
        "preview-from-draft",
    ]
    assert steps[2].arguments[-4:] == (
        "--object-path-segment",
        "Actor-Mixer Hierarchy",
        "--object-path-segment",
        "Default Work Unit",
    )
    declaration = steps[3]
    assert "--mode" in declaration.arguments
    assert declaration.arguments[declaration.arguments.index("--mode") + 1] == (
        "reimport"
    )
    assert "--no-add-to-source-control" in declaration.arguments
    assert steps[-1].expected_operation_request == request


def test_switch_assignment_business_steps_bind_three_paths_before_declaration() -> None:
    container = r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps"
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "switchContainer.removeAssignment",
        "arguments": {
            "switch_container": {"kind": "path", "value": container},
            "child": {"kind": "path", "value": container + r"\Mud"},
            "state_or_switch": {
                "kind": "path",
                "value": r"\Switches\Default Work Unit\Surface\Mud",
            },
        },
    }

    steps = build_switch_assignment_business_transaction_steps(
        request,
        label="tx01",
    )

    assert [step.subcommand for step in steps] == [
        "operation-schema",
        "draft-start",
        "draft-bind-object",
        "draft-bind-object",
        "draft-bind-object",
        "draft-declare-switch-assignment",
        "draft-check",
        "preview-from-draft",
    ]
    declare = steps[5]
    assert declare.arguments[-6:] == (
        "--switch-container-handle",
        ResponseBinding("tx01.bind-switch-container", "/bound_object/handle"),
        "--child-handle",
        ResponseBinding("tx01.bind-child", "/bound_object/handle"),
        "--state-or-switch-handle",
        ResponseBinding("tx01.bind-state-or-switch", "/bound_object/handle"),
    )
    assert steps[-1].expected_operation_request == request


def test_compound_undo_steps_check_children_before_one_parent_preview() -> None:
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\Rain"
    requests = (
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": "2022.1",
            "operation": "object.setNotes",
            "arguments": {
                "object": {"kind": "path", "value": object_path},
                "value": "Exterior rain loop",
            },
        },
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": "2022.1",
            "operation": "object.setName",
            "arguments": {
                "object": {"kind": "path", "value": object_path},
                "value": "Rain_Exterior",
            },
        },
    )
    children = tuple(
        CompoundUndoChildExpectation(
            request=request,
            selector={"kind": "path", "value": object_path},
        )
        for request in requests
    )
    steps = build_compound_undo_business_transaction_steps(
        children,
        display_name="Weather rain cleanup",
        label="tx03",
    )

    assert [step.subcommand for step in steps] == [
        "operations",
        "operation-schema",
        "draft-start",
        "operation-schema",
        "draft-start",
        "draft-bind-object",
        "draft-declare-object-change",
        "draft-check",
        "operation-schema",
        "draft-start",
        "draft-bind-object",
        "draft-declare-object-change",
        "draft-check",
        "draft-declare-undo-plan",
        "draft-check",
        "preview-from-draft",
    ]
    declaration = steps[-3]
    assert declaration.arguments[-6:] == (
        "--child-draft",
        ResponseBinding("tx01.draft-start", "/draft/draft_id"),
        ResponseBinding("tx01.draft-start", "/task_authority"),
        "--child-draft",
        ResponseBinding("tx02.draft-start", "/draft/draft_id"),
        ResponseBinding("tx02.draft-start", "/task_authority"),
    )
    assert steps[-1].expected_operation_request["operation"] == "waapi.undoGroup"
    assert [
        row["request"]["operation"]
        for row in steps[-1].expected_operation_request["arguments"]["calls"]
    ] == ["object.setNotes", "object.setName"]


def test_real_gateway_helper_reuses_soundbank_plan_cli_grammar() -> None:
    handle = "boh1-" + "1" * 32
    assert _soundbank_plan_suffix_matches(
        "soundbank.generate",
        (
            "--soundbank",
            handle,
            "nonlocalized",
            "--no-rebuild-soundbank",
            handle,
            "--platform",
            "Windows",
            "--no-rebuild-soundbanks",
            "--no-clear-audio-file-cache",
            "--no-rebuild-init-bank",
            "--io-root",
            r"C:\owned",
        ),
    )
    assert not _soundbank_plan_suffix_matches(
        "soundbank.generate",
        ("--native-request", "{}"),
    )


def _archive_test_object_create_top_level_facts_precede_dynamic_container_disclosure() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2021.1",
        "operation": "object.create",
        "arguments": {
            "parent": {
                "kind": "path",
                "value": r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\NPC",
            },
            "type": "ActorMixer",
            "name": "TypedRoot",
            "children": [
                {
                    "type": "Sound",
                    "name": "TypedChild",
                    "children": [
                        {
                            "type": "Sound",
                            "name": "TypedGrandchild",
                        }
                    ],
                }
            ],
        },
    }

    protocol = build_transaction_protocol([request])
    subcommands = tuple(step.subcommand for step in protocol.steps)

    first_disclosure = subcommands.index("request-array-item")
    assert any(
        step.subcommand == "draft-apply"
        for step in protocol.steps[2:first_disclosure]
    )
    disclosures = tuple(
        step
        for step in protocol.steps
        if step.subcommand in {"request-array-item", "request-map-container"}
    )
    assert any(
        "--schema-digest" in step.arguments
        and "--parent-schema-token" not in step.arguments
        for step in disclosures
    )
    assert any("--parent-schema-token" in step.arguments for step in disclosures)
    assert all(
        "--schema-digest" not in step.arguments
        for step in disclosures
        if "--parent-schema-token" in step.arguments
    )


def _archive_test_typed_profile_object_create_batches_fit_windows_command_transport() -> None:
    profile = load_typed_input_profile(
        Path(__file__).resolve().parent / "data" / "typed-input-v1" / "profile.json"
    )
    unit = next(
        row
        for row in profile.units
        if row.unit_id == "TYP21-DEDICATED-OBJECT-CREATE"
    )
    recipe = build_object_heavy_v3_recipe(unit.base_scenario_id, unit.version)
    protocol = build_transaction_protocol(
        (recipe.request.as_dict(version=unit.version),)
    )
    # Reserve a deliberately long runner path; the formal Windows campaign
    # additionally constrains its owned workspace/current-directory lengths.
    runner = "C:/" + ("owned/" * 28) + "run.py"
    encoded_lengths: list[int] = []
    for step in protocol.steps:
        if step.subcommand != "draft-apply":
            continue
        argv = ["python", runner, "gateway.py", "--version", unit.version]
        argv.append(step.subcommand)
        for argument in step.arguments:
            if isinstance(argument, ResponseBinding):
                if argument.pointer.endswith("/draft_id"):
                    argv.append("od1-" + ("0" * 32))
                elif argument.pointer.endswith("/task_authority"):
                    argv.append("da1-" + ("0" * 40))
                else:
                    argv.append("999")
            elif isinstance(argument, DraftTypedActionBatchArgument):
                for action in argument.actions:
                    argv.extend(typed_action_cli_arguments(action.expected))
            elif isinstance(argument, DraftTypedActionArgument):
                argv.extend(typed_action_cli_arguments(argument.expected))
            else:
                assert isinstance(argument, str)
                argv.append(argument)
        encoded_lengths.append(len(encode_windows_powershell_argv(argv)))

    assert encoded_lengths
    assert max(encoded_lengths) < 30_000


def _archive_test_typed_profile_object_create_applies_each_disclosed_node_before_the_next(
) -> None:
    profile = load_typed_input_profile(
        Path(__file__).resolve().parent / "data" / "typed-input-v1" / "profile.json"
    )
    unit = next(
        row
        for row in profile.units
        if row.unit_id == "TYP21-DEDICATED-OBJECT-CREATE"
    )
    recipe = build_object_heavy_v3_recipe(unit.base_scenario_id, unit.version)
    protocol = build_transaction_protocol(
        (recipe.request.as_dict(version=unit.version),)
    )
    construction = tuple(
        step
        for step in protocol.steps
        if ".action." in step.name or ".disclose." in step.name
    )

    assert [step.name for step in construction[:9]] == [
        "tx01.action.001",
        "tx01.disclose.001",
        "tx01.action.002",
        "tx01.disclose.002",
        "tx01.action.003",
        "tx01.disclose.003",
        "tx01.action.004",
        "tx01.disclose.004",
        "tx01.action.005",
    ]
    action_sizes = []
    for step in construction:
        if ".action." not in step.name:
            continue
        argument = step.arguments[-1]
        action_sizes.append(
            len(argument.actions)
            if isinstance(argument, DraftTypedActionBatchArgument)
            else 1
        )
    assert action_sizes == [6, 4, 1, 3, 3, 4, 1, 3, 3, 4, 1, 3, 3]


def _archive_test_typed_profile_object_create_uses_one_standard_disclosure_argv() -> None:
    profile = load_typed_input_profile(
        Path(__file__).resolve().parent / "data" / "typed-input-v1" / "profile.json"
    )
    unit = next(
        row
        for row in profile.units
        if row.unit_id == "TYP21-DEDICATED-OBJECT-CREATE"
    )
    recipe = build_object_heavy_v3_recipe(unit.base_scenario_id, unit.version)
    protocol = build_transaction_protocol(
        (recipe.request.as_dict(version=unit.version),)
    )
    disclosures = tuple(
        step
        for step in protocol.steps
        if step.subcommand in {"request-array-item", "request-map-container"}
    )

    assert all(
        "--no-dynamic-descendants" not in step.arguments
        for step in disclosures
    )


def _object_set_request(**options: object) -> dict[str, object]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            **options,
            "objects": [
                {
                    "object": {
                        "kind": "path",
                        "value": r"\Actor-Mixer Hierarchy\Target",
                    },
                    "properties": [{"name": "Volume", "value": -3.0}],
                }
            ],
        },
    }


def _audio_import_request() -> dict[str, object]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "import_operation": "createNew",
            "auto_add_to_source_control": False,
            "defaults": {
                "import_language": "SFX",
                "object_type": "Sound SFX",
                "properties": [{"name": "Volume", "value": -3.0}],
            },
            "imports": [
                {
                    "audio_file": native_absolute_test_path("音频", "rain.wav"),
                    "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
                    "event": {
                        "path": r"\Events\Default Work Unit\Play_Rain",
                        "action": "Play",
                    },
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {
                                "kind": "path",
                                "value": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus",
                            },
                        }
                    ],
                }
            ],
        },
    }


def _typed_draft_action_arguments(
    steps: tuple[ExpectedGatewayStep, ...],
) -> list[DraftTypedActionArgument]:
    actions: list[DraftTypedActionArgument] = []
    for step in steps:
        if step.subcommand != "draft-apply":
            continue
        argument = step.arguments[-1]
        if isinstance(argument, DraftTypedActionBatchArgument):
            actions.extend(argument.actions)
        else:
            assert isinstance(argument, DraftTypedActionArgument)
            actions.append(argument)
    return actions


def test_audio_import_protocol_emits_ordered_business_steps_without_native_rows() -> None:
    metadata = DraftActionMetadataBinding(
        step="tx01.metadata",
        object_type="Sound",
        required_tokens=("Volume", "OutputBus"),
    )
    steps = build_audio_import_composer_transaction_steps(
        _audio_import_request(),
        label="tx01",
        metadata_binding=metadata,
    )
    assert [step.subcommand for step in steps[:9]] == [
        "operation-schema",
        "draft-start",
        "draft-bind-object",
        "draft-bind-object",
        "draft-bind-object",
        "draft-business-configure",
        "draft-declare-import-batch",
        "draft-check",
        "preview-from-draft",
    ]
    declaration = next(
        step
        for step in steps
        if step.subcommand == "draft-declare-import-batch"
    )
    assert "--field" in declaration.arguments
    assert "volume_db" in declaration.arguments
    assert "output_bus" in declaration.arguments
    assert "--event" in declaration.arguments
    assert declaration.arguments.count("--row-order") == 1
    assert declaration.arguments[declaration.arguments.index(
        "--expected-declaration-count"
    ) + 1] == "1"
    assert all(step.subcommand != "draft-apply" for step in steps)
    assert next(step for step in steps if step.name == "tx01.preview").subcommand == (
        "preview-from-draft"
    )
    assert all(
        "--request-json" not in step.arguments
        for step in steps
    )


def test_audio_import_switch_assignment_is_part_of_the_business_declaration() -> None:
    request = _audio_import_request()
    switch_assignment = "Snow"
    request["arguments"]["imports"][0]["switch_assignment"] = switch_assignment  # type: ignore[index]

    declaration = next(
        step
        for step in build_audio_import_composer_transaction_steps(
            request, label="tx01"
        )
        if step.subcommand == "draft-declare-import-batch"
    )
    switch_index = declaration.arguments.index("--switch-value")
    assert declaration.arguments[switch_index + 1] == "row-001"
    assert declaration.arguments[switch_index + 2] == switch_assignment

    request["arguments"]["imports"][0].pop("switch_assignment")  # type: ignore[index]
    ordinary = next(
        step
        for step in build_audio_import_composer_transaction_steps(
            request, label="tx01"
        )
        if step.subcommand == "draft-declare-import-batch"
    )
    assert "--switch-value" not in ordinary.arguments


def test_audio_import_business_builder_rejects_unreviewed_request_fields() -> None:
    request = _audio_import_request()
    request["arguments"]["native_args"] = {}  # type: ignore[index]

    with pytest.raises(V3ProtocolError, match="fields are not supported"):
        build_audio_import_composer_transaction_steps(request, label="tx01")


def test_object_set_composer_lets_gateway_own_schema_defaults() -> None:
    steps = build_object_set_composer_transaction_steps(
        _object_set_request(
            list_mode="append",
            on_name_conflict="fail",
            auto_add_to_source_control=False,
        ),
        label="tx01",
    )
    actions = [argument.expected for argument in _typed_draft_action_arguments(steps)]

    assert actions == [
        {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": "add_target",
            "selector": {
                "kind": "path",
                "value": r"\Actor-Mixer Hierarchy\Target",
            },
            "properties": [{"name": "Volume", "value": -3.0}],
        }
    ]


def test_object_set_composer_keeps_nondefault_request_options_explicit() -> None:
    steps = build_object_set_composer_transaction_steps(
        _object_set_request(
            platform="Windows",
            list_mode="replaceAll",
            on_name_conflict="merge",
            auto_add_to_source_control=True,
        ),
        label="tx01",
    )
    actions = [argument.expected for argument in _typed_draft_action_arguments(steps)]

    assert actions[:4] == [
        {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": "set_request_option",
            "name": "platform",
            "value": "Windows",
        },
        {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": "set_request_option",
            "name": "list_mode",
            "value": "replaceAll",
        },
        {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": "set_request_option",
            "name": "on_name_conflict",
            "value": "merge",
        },
        {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": "set_request_option",
            "name": "auto_add_to_source_control",
            "value": True,
        },
    ]


def test_object_set_protocol_batches_sibling_children_after_parent_handle() -> None:
    request = _object_set_request()
    request["arguments"]["objects"][0]["children"] = [  # type: ignore[index]
        {"type": "Sound", "name": "Light"},
        {"type": "Sound", "name": "Heavy"},
    ]

    steps = build_object_set_composer_transaction_steps(request, label="tx01")
    action_steps = tuple(
        step for step in steps if step.subcommand == "draft-apply"
    )

    assert len(action_steps) == 2
    assert isinstance(action_steps[0].arguments[-1], DraftTypedActionArgument)
    child_batch = action_steps[1].arguments[-1]
    assert isinstance(child_batch, DraftTypedActionBatchArgument)
    assert [action.expected["action"] for action in child_batch.actions] == [
        "add_child",
        "add_child",
    ]
    assert [action.response_bindings for action in child_batch.actions] == [
        (
            DraftActionResponseBinding(
                "/parent_handle",
                "tx01.action.001",
                "/draft/action_result/created_handles/0",
            ),
        ),
        (
            DraftActionResponseBinding(
                "/parent_handle",
                "tx01.action.001",
                "/draft/action_result/created_handles/0",
            ),
        ),
    ]


def test_object_set_protocol_batches_independent_query_bound_targets() -> None:
    bus_path = r"\Master-Mixer Hierarchy\Default Work Unit\Weapons"
    request = _object_set_request()
    template = request["arguments"]["objects"][0]  # type: ignore[index]
    request["arguments"]["objects"] = [  # type: ignore[index]
        {
            **template,
            "object": {"kind": "path", "value": rf"\Root\Target{index}"},
            "references": [
                {
                    "name": "OutputBus",
                    "target": {"kind": "path", "value": bus_path},
                }
            ],
        }
        for index in range(3)
    ]

    steps = build_object_set_composer_transaction_steps(
        request,
        label="tx01",
        reference_identity_sources={bus_path: "relationship.output_bus"},
    )
    action_steps = tuple(
        step for step in steps if step.subcommand == "draft-apply"
    )

    assert len(action_steps) == 1
    batch = action_steps[0].arguments[-1]
    assert isinstance(batch, DraftTypedActionBatchArgument)
    assert len(batch.actions) == 3
    assert all(
        action.query_identity_bindings
        == (
            DraftActionQueryIdentityBinding(
                "/references/0/target",
                "relationship.output_bus",
            ),
        )
        for action in batch.actions
    )


def test_single_transaction_spans_two_turn_prefixes_with_response_bindings() -> None:
    protocol = build_transaction_protocol([_request()])

    assert protocol.turn_prefix_counts == (5, 9)
    assert tuple(step.subcommand for step in protocol.steps) == (
        "operation-schema",
        "draft-start",
        "draft-declare-artifact-plan",
        "draft-check",
        "preview-from-draft",
        "transaction-show",
        "confirm",
        "execute",
        "verify",
    )
    by_name = {step.name: step for step in protocol.steps}
    assert by_name["tx01.execute"].allowed_exit_codes == (0, 2)
    assert by_name["tx01.execute"].terminal_execute is False
    assert by_name["tx01.verify"].allowed_exit_codes == (0,)
    assert by_name["tx01.transaction-show"].arguments == (
        ResponseBinding("tx01.preview", "/transaction_id"),
        "--summary-only",
    )
    assert by_name["tx01.confirm"].arguments == (
        ResponseBinding("tx01.transaction-show", "/transaction_id"),
        "--confirmation-token",
        ResponseBinding("tx01.transaction-show", "/confirmation/token"),
    )
    assert by_name["tx01.execute"].arguments == (
        ResponseBinding("tx01.confirm", "/transaction_id"),
    )
    assert by_name["tx01.verify"].arguments == (
        ResponseBinding("tx01.execute", "/transaction_id"),
    )
    assert all("--request-json" not in step.arguments for step in protocol.steps)


def test_commutative_read_only_groups_are_adjacent_and_cannot_cross_turns() -> None:
    schema = ExpectedGatewayStep(
        "tx01.operation-schema",
        "operation-schema",
        ("object.set",),
    )
    metadata = ExpectedGatewayStep(
        "tx01.metadata",
        "metadata",
        (
            "discover",
            "--object-type",
            "Action",
            "--query",
            MetadataQueryArgument("fade time"),
            "--limit",
            "8",
        ),
    )
    preview = ExpectedGatewayStep("tx01.preview", "preview")

    protocol = V3GatewayProtocol(
        (schema, metadata, preview),
        (3,),
        commutative_read_only_step_groups=(
            ("tx01.operation-schema", "tx01.metadata"),
        ),
    )
    assert protocol.commutative_read_only_step_groups == (
        ("tx01.operation-schema", "tx01.metadata"),
    )

    with pytest.raises(ValueError, match="cannot cross a turn prefix"):
        V3GatewayProtocol(
            (schema, metadata, preview),
            (1, 3),
            commutative_read_only_step_groups=(
                ("tx01.operation-schema", "tx01.metadata"),
            ),
        )
    with pytest.raises(ValueError, match="limited to one"):
        V3GatewayProtocol(
            (schema, metadata, preview),
            (3,),
            commutative_read_only_step_groups=(
                ("tx01.metadata", "tx01.preview"),
            ),
        )


def test_commutative_composer_setup_groups_are_narrow_and_cannot_cross_turns() -> None:
    schema = ExpectedGatewayStep(
        "tx01.operation-schema",
        "operation-schema",
        ("audio.import",),
    )
    metadata = ExpectedGatewayStep(
        "tx01.metadata",
        "metadata",
        (
            "discover",
            "--object-type",
            "Sound",
            "--query",
            MetadataQueryArgument("volume"),
            "--limit",
            "8",
        ),
    )
    draft_start = ExpectedGatewayStep(
        "tx01.draft-start",
        "draft-start",
        ("audio.import",),
    )

    protocol = V3GatewayProtocol(
        (schema, metadata, draft_start),
        (3,),
        commutative_read_only_step_groups=(
            ("tx01.operation-schema", "tx01.metadata"),
        ),
        commutative_composer_setup_step_groups=(
            ("tx01.metadata", "tx01.draft-start"),
        ),
    )
    assert protocol.commutative_composer_setup_step_groups == (
        ("tx01.metadata", "tx01.draft-start"),
    )

    with pytest.raises(ValueError, match="cannot cross a turn prefix"):
        V3GatewayProtocol(
            (schema, metadata, draft_start),
            (2, 3),
            commutative_composer_setup_step_groups=(
                ("tx01.metadata", "tx01.draft-start"),
            ),
        )
    with pytest.raises(ValueError, match="limited to metadata"):
        V3GatewayProtocol(
            (schema, metadata, draft_start),
            (3,),
            commutative_composer_setup_step_groups=(
                ("tx01.operation-schema", "tx01.metadata"),
            ),
        )

    static_action = ExpectedGatewayStep(
        "tx01.action.001",
        "draft-apply",
        (
            DraftTypedActionArgument(
                {
                    "contract": "waapi-skill.operation-draft-action/v1",
                    "action": "set_import_option",
                    "name": "import_operation",
                    "value": "useExisting",
                },
                operation="audio.import",
            ),
        ),
    )
    assert validate_commutative_composer_setup_step_groups(
        (metadata, draft_start, static_action),
        (("tx01.metadata", "tx01.draft-start", "tx01.action.001"),),
    ) == (("tx01.metadata", "tx01.draft-start", "tx01.action.001"),)

    metadata_bound_action = ExpectedGatewayStep(
        "tx01.action.002",
        "draft-apply",
        (
            DraftTypedActionArgument(
                {
                    "contract": "waapi-skill.operation-draft-action/v1",
                    "action": "set_import_default",
                    "name": "properties",
                    "value": [{"name": "Volume", "value": -3.0}],
                },
                operation="audio.import",
                metadata_binding=DraftActionMetadataBinding(
                    step="tx01.metadata",
                    object_type="Sound",
                    required_tokens=("Volume",),
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="metadata-free typed actions"):
        validate_commutative_composer_setup_step_groups(
            (metadata, draft_start, metadata_bound_action),
            (("tx01.metadata", "tx01.draft-start", "tx01.action.002"),),
        )


def test_audio_import_transaction_request_uses_business_declaration_steps() -> None:
    protocol = build_transaction_protocol([_audio_import_request()])

    assert any(
        step.subcommand == "draft-declare-import-batch"
        for step in protocol.steps
    )
    assert any(step.subcommand == "draft-bind-object" for step in protocol.steps)
    assert all(step.subcommand != "draft-apply" for step in protocol.steps)
    assert all("--request-json" not in step.arguments for step in protocol.steps)


@pytest.mark.parametrize(
    ("operation", "arguments", "expected_flags"),
    [
        (
            "object.copy",
            {
                "object": {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Source"},
                "parent": {"kind": "id", "value": "{parent}"},
                "on_name_conflict": "rename",
                "auto_add_to_source_control": False,
                "auto_check_out_to_source_control": True,
            },
            {"--parent-handle", "--name-conflict", "--no-add-to-source-control", "--check-out-from-source-control"},
        ),
        (
            "object.delete",
            {
                "object": {"kind": "id", "value": "{object}"},
                "auto_check_out_to_source_control": False,
            },
            {"--no-check-out-from-source-control"},
        ),
        (
            "object.move",
            {
                "object": {"kind": "id", "value": "{object}"},
                "parent": {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Destination"},
                "on_name_conflict": "fail",
            },
            {"--parent-handle", "--name-conflict"},
        ),
        (
            "object.setName",
            {"object": {"kind": "id", "value": "{object}"}, "value": "Rain"},
            {"--new-name"},
        ),
        (
            "object.setNotes",
            {"object": {"kind": "id", "value": "{object}"}, "value": "Wet"},
            {"--notes"},
        ),
    ],
)
def test_object_lifecycle_protocol_uses_business_declarations(
    operation: str,
    arguments: dict[str, object],
    expected_flags: set[str],
) -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2024.1",
        "operation": operation,
        "arguments": arguments,
    }

    steps = build_object_lifecycle_business_transaction_steps(request, label="tx01")
    declaration = next(
        step for step in steps if step.subcommand == "draft-declare-object-change"
    )

    assert expected_flags.issubset(set(declaration.arguments))
    assert [step.subcommand for step in steps][-3:] == [
        "draft-declare-object-change",
        "draft-check",
        "preview-from-draft",
    ]
    assert all(step.subcommand != "draft-apply" for step in steps)
    assert all("--request-json" not in step.arguments for step in steps)
    preview = next(step for step in steps if step.name == "tx01.preview")
    assert preview.expected_operation_request == request


def test_transaction_protocol_routes_object_lifecycle_around_generic_typed_facts() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.setNotes",
        "arguments": {
            "object": {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Target"},
            "value": "Closed business notes",
        },
    }

    protocol = build_transaction_protocol((request,))

    assert any(
        step.subcommand == "draft-declare-object-change" for step in protocol.steps
    )
    assert all(step.subcommand != "draft-apply" for step in protocol.steps)


def test_object_lifecycle_business_builder_rejects_native_or_unknown_fields() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.setName",
        "arguments": {
            "object": {"kind": "id", "value": "{object}"},
            "value": "Rain",
            "native_args": {},
        },
    }

    with pytest.raises(V3ProtocolError, match="fields are not supported"):
        build_object_lifecycle_business_transaction_steps(request, label="tx01")


@pytest.mark.parametrize(
    ("operation", "arguments", "outcome_flag"),
    [
        (
            "object.setProperty",
            {
                "object": {"kind": "id", "value": "{object}"},
                "property": "Volume",
                "value": -4.0,
                "platform": "Windows",
            },
            "--business-value",
        ),
        (
            "object.setReference",
            {
                "object": {"kind": "id", "value": "{object}"},
                "reference": "OutputBus",
                "target": {"kind": "id", "value": "{target}"},
            },
            "--target-handle",
        ),
        (
            "object.setLinked",
            {
                "object": {"kind": "id", "value": "{object}"},
                "property": "Volume",
                "platform": "Windows",
                "linked": False,
            },
            "--link-state",
        ),
    ],
)
def test_object_metadata_protocol_uses_meaning_and_opaque_field_handle(
    operation: str,
    arguments: dict[str, object],
    outcome_flag: str,
) -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": operation,
        "arguments": arguments,
    }

    steps = build_object_metadata_business_transaction_steps(
        request,
        label="tx01",
    )

    discover = next(
        step for step in steps if step.subcommand == "draft-discover-fields"
    )
    declare = next(
        step for step in steps if step.subcommand == "draft-declare-field-change"
    )
    assert "--meaning" in discover.arguments
    assert "--token" not in discover.arguments
    assert outcome_flag in declare.arguments
    assert [step.subcommand for step in steps][-3:] == [
        "draft-declare-field-change",
        "draft-check",
        "preview-from-draft",
    ]
    assert all(step.subcommand != "draft-apply" for step in steps)
    assert next(step for step in steps if step.name == "tx01.preview").expected_operation_request == request


def test_transaction_protocol_routes_object_metadata_around_typed_ingress() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.setReference",
        "arguments": {
            "object": {"kind": "id", "value": "{object}"},
            "reference": "OutputBus",
            "target": None,
        },
    }

    protocol = build_transaction_protocol((request,))

    assert any(
        step.subcommand == "draft-discover-fields" for step in protocol.steps
    )
    assert any(
        step.subcommand == "draft-declare-field-change" for step in protocol.steps
    )
    assert all(step.subcommand != "typed-operation" for step in protocol.steps)


def test_soundbank_generate_transaction_uses_one_complete_business_plan() -> None:
    request = {
        **_request(),
        "operation": "soundbank.generate",
        "arguments": {
            "soundbanks": [
                {
                    "name": "Main_UI",
                    "artifact_expectation": "nonlocalized",
                    "rebuild": False,
                }
            ],
            "platforms": ["Windows"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": "/owned",
            "rebuild_soundbanks": False,
            "clear_audio_file_cache": False,
            "rebuild_init_bank": False,
        },
    }

    protocol = build_transaction_protocol([request])

    declare = next(
        step
        for step in protocol.steps
        if step.subcommand == "draft-declare-soundbank-plan"
    )

    assert "--soundbank" in declare.arguments
    assert "--platform" in declare.arguments
    assert "--no-rebuild-soundbanks" in declare.arguments
    assert "--no-clear-audio-file-cache" in declare.arguments
    assert "--no-rebuild-init-bank" in declare.arguments
    assert any(step.subcommand == "draft-bind-object" for step in protocol.steps)
    binding = next(
        step for step in protocol.steps if step.subcommand == "draft-bind-object"
    )
    assert binding.arguments[-5:] == (
        "--role",
        "soundbank",
        "--exact-type-name",
        "SoundBank",
        "Main_UI",
    )
    assert all(step.subcommand != "query-object" for step in protocol.steps)
    assert any(step.subcommand == "preview-from-draft" for step in protocol.steps)
    assert all(step.subcommand != "draft-apply" for step in protocol.steps)
    assert all(step.subcommand != "typed-operation" for step in protocol.steps)
    assert all("--request-json" not in step.arguments for step in protocol.steps)


def test_multi_bank_business_plan_binds_each_bank_once_before_one_declaration() -> None:
    request = {
        **_request(),
        "version": "2024.1",
        "operation": "soundbank.generate",
        "arguments": {
            "soundbanks": [
                {
                    "name": "Main_UI",
                    "artifact_expectation": "nonlocalized",
                    "rebuild": False,
                },
                {
                    "name": "Dialogue",
                    "artifact_expectation": "nonlocalized",
                    "rebuild": False,
                },
            ],
            "platforms": ["Windows"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": "/owned",
            "rebuild_soundbanks": False,
            "clear_audio_file_cache": False,
            "rebuild_init_bank": False,
        },
    }

    protocol = build_transaction_protocol([request])
    bindings = [
        step for step in protocol.steps if step.subcommand == "draft-bind-object"
    ]
    declarations = [
        step
        for step in protocol.steps
        if step.subcommand == "draft-declare-soundbank-plan"
    ]

    assert all(step.subcommand != "query-object" for step in protocol.steps)
    assert len(bindings) == 2
    assert [step.arguments[-5:] for step in bindings] == [
        ("--role", "soundbank", "--exact-type-name", "SoundBank", "Main_UI"),
        ("--role", "soundbank", "--exact-type-name", "SoundBank", "Dialogue"),
    ]
    assert len(declarations) == 1
    declare = declarations[0]
    assert declare.arguments.count("--soundbank") == 2
    assert declare.arguments.count("--no-rebuild-soundbank") == 2
    assert declare.arguments[4] == ResponseBinding(
        "tx01.bind-object.002",
        "/draft/revision",
    )


def test_set_inclusions_business_plan_binds_ids_without_typed_disclosure() -> None:
    request = {
        **_request(),
        "operation": "soundbank.setInclusions",
        "arguments": {
            "soundbank": {
                "kind": "id",
                "value": "{00000000-0000-0000-0000-000000000001}",
            },
            "mode": "replace",
            "inclusions": [
                {
                    "object": {
                        "kind": "id",
                        "value": "{00000000-0000-0000-0000-000000000002}",
                    },
                    "filters": ["events", "structures", "media"],
                }
            ],
        },
    }

    protocol = build_transaction_protocol([request])
    bindings = [
        step for step in protocol.steps if step.subcommand == "draft-bind-object"
    ]
    declare = next(
        step
        for step in protocol.steps
        if step.subcommand == "draft-declare-soundbank-plan"
    )

    assert len(bindings) == 2
    assert bindings[0].arguments[-2:] == (
        "--object-id",
        "{00000000-0000-0000-0000-000000000001}",
    )
    assert bindings[0].arguments[-4:-2] == ("--role", "soundbank")
    assert bindings[1].arguments[-2:] == (
        "--object-id",
        "{00000000-0000-0000-0000-000000000002}",
    )
    assert bindings[1].arguments[-4:-2] == ("--role", "inclusion_object")
    assert declare.arguments[-9:] == (
        "--mode",
        "replace",
        "--soundbank-handle",
        ResponseBinding("tx01.bind-object.001", "/bound_object/handle"),
        "--inclusion",
        ResponseBinding("tx01.bind-object.002", "/bound_object/handle"),
        "events",
        "structures",
        "media",
    )
    assert declare.arguments.count("--inclusion") == 1
    assert all(step.subcommand != "draft-apply" for step in protocol.steps)


def test_metadata_transaction_protocol_is_generic_and_binds_every_preview() -> None:
    first = _object_set_request()
    second = _object_set_request()
    second["arguments"]["objects"][0]["object"]["value"] = r"\Root\Two"  # type: ignore[index]

    protocol = build_metadata_transaction_protocol(
        (first, second),
        object_type="ActorMixer",
        metadata_queries=("output volume", "voice gain"),
        required_tokens=("Volume",),
        expected_required_token_projection=(
            MetadataTokenProjection("Volume", "property", "Real32"),
        ),
    )

    assert protocol.turn_prefix_counts == (6, 15, 19)
    assert protocol.steps[0].name == "metadata.discover"
    assert protocol.steps[0].subcommand == "metadata"
    assert protocol.steps[0].arguments[:3] == (
        "discover",
        "--object-type",
        "ActorMixer",
    )
    query_arguments = tuple(
        item
        for item in protocol.steps[0].arguments
        if isinstance(item, MetadataQueryArgument)
    )
    assert tuple(item.label for item in query_arguments) == (
        "output volume",
        "voice gain",
    )
    actions = tuple(
        step.arguments[-1]
        for step in protocol.steps
        if step.subcommand == "draft-apply"
    )
    assert len(actions) == 2
    for argument in actions:
        assert isinstance(argument, DraftTypedActionArgument)
        assert argument.metadata_binding is not None
        assert argument.metadata_binding.step == "metadata.discover"
        assert argument.metadata_binding.object_type == "ActorMixer"
        assert argument.metadata_binding.required_tokens == ("Volume",)
        assert argument.metadata_binding.expected_projection == (
            MetadataTokenProjection("Volume", "property", "Real32"),
        )


@pytest.mark.parametrize(
    ("query_count", "expected_limit"),
    ((1, 8), (2, 8), (3, 3), (4, 3), (5, 2), (8, 2)),
)
def test_metadata_transaction_protocol_uses_the_skill_query_count_budget(
    query_count: int,
    expected_limit: int,
) -> None:
    queries = tuple(f"setting {index}" for index in range(query_count))

    protocol = build_metadata_transaction_protocol(
        (_object_set_request(),),
        object_type="Sound",
        metadata_queries=queries,
        required_tokens=("Volume",),
    )

    assert metadata_candidate_limit(queries) == expected_limit
    assert protocol.steps[0].arguments[-2:] == (
        "--limit",
        str(expected_limit),
    )


@pytest.mark.parametrize("queries", ((), tuple("q" for _ in range(9)), "volume"))
def test_metadata_candidate_budget_rejects_non_protocol_query_counts(
    queries: object,
) -> None:
    with pytest.raises(V3ProtocolError, match="metadata candidate budget"):
        metadata_candidate_limit(queries)  # type: ignore[arg-type]


def test_schema_first_metadata_protocol_exposes_version_before_exact_scope() -> None:
    protocol = build_metadata_transaction_protocol(
        (_object_set_request(),),
        object_type="PropertyContainer",
        metadata_queries=("output volume",),
        required_tokens=("Volume",),
        expected_required_token_projection=(
            MetadataTokenProjection("Volume", "property", "Real32"),
        ),
        schema_first=True,
    )

    assert protocol.turn_prefix_counts == (6, 10)
    assert tuple(step.subcommand for step in protocol.steps[:3]) == (
        "operation-schema",
        "metadata",
        "draft-start",
    )
    assert protocol.steps[1].arguments[:3] == (
        "discover",
        "--object-type",
        "PropertyContainer",
    )
    argument = next(
        step.arguments[-1]
        for step in protocol.steps
        if step.subcommand == "draft-apply"
    )
    assert isinstance(argument, DraftTypedActionArgument)
    assert argument.metadata_binding is not None
    assert argument.metadata_binding.step == "metadata.discover"
    assert argument.metadata_binding.object_type == "PropertyContainer"


def test_schema_query_protocol_requires_one_exact_auditable_preflight_lookup() -> None:
    query = query_object_step(
        "object.merge-root",
        (
            "query-object",
            "--path",
            r"\Containers\Default Work Unit\SemanticLab\NPC\Robot_VO",
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

    protocol = build_schema_query_transaction_protocol(
        (_request(),),
        query_step=query,
    )

    assert protocol.turn_prefix_counts == (6, 10)
    assert tuple(step.subcommand for step in protocol.steps[:3]) == (
        "query-object",
        "operation-schema",
        "draft-start",
    )
    assert protocol.steps[0] == query


def test_metadata_transaction_protocol_selects_closed_audio_import_equivalence() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit\Target"
                    ),
                    "audio_file": native_absolute_test_path("audio", "source.wav"),
                    "object_type": "Sound SFX",
                    "import_language": "SFX",
                }
            ],
            "defaults": {
                "properties": [
                    {"name": "IsLoopingEnabled", "value": True}
                ]
            },
        },
    }

    protocol = build_metadata_transaction_protocol(
        (request,),
        object_type="Sound",
        metadata_queries=("looping enabled",),
        required_tokens=("IsLoopingEnabled",),
        equivalence="audio_import_v1",
    )
    assert protocol.turn_prefix_counts == (7, 11)
    assert tuple(step.subcommand for step in protocol.steps[:2]) == (
        "operation-schema",
        "draft-start",
    )
    assert any(step.subcommand == "draft-bind-field" for step in protocol.steps)
    assert any(
        step.subcommand == "draft-declare-import-batch"
        for step in protocol.steps
    )
    assert all(step.subcommand != "metadata" for step in protocol.steps)
    assert all(step.subcommand != "draft-apply" for step in protocol.steps)
    assert protocol.commutative_read_only_step_groups == ()
    assert "preview" not in {
        step.subcommand for step in protocol.steps
    }
    assert "preview-from-draft" in {
        step.subcommand for step in protocol.steps
    }


def test_audio_import_protocol_serializes_bound_existing_declarations() -> None:
    request = _audio_import_request()
    request["arguments"]["imports"] = [
        {
            "audio_file": native_absolute_test_path("audio", f"source-{index}.wav"),
            "object_path": rf"\Actor-Mixer Hierarchy\Default Work Unit\Target{index}",
            "object_type": "Sound SFX",
            "import_language": "SFX",
        }
        for index in range(5)
    ]
    request["arguments"].pop("defaults")
    request["arguments"].pop("auto_add_to_source_control")
    request["arguments"]["import_operation"] = "useExisting"

    steps = build_audio_import_composer_transaction_steps(request, label="tx01")
    assert sum(step.subcommand == "draft-bind-object" for step in steps) == 5
    declaration = next(
        step
        for step in steps
        if step.subcommand == "draft-declare-import-batch"
    )
    assert declaration.arguments.count("--existing-row") == 5
    assert declaration.arguments.count("--row-order") == 5
    assert declaration.arguments[
        declaration.arguments.index("--expected-declaration-count") + 1
    ] == "5"
    assert all(step.subcommand != "draft-apply" for step in steps)


def test_metadata_transaction_protocol_keeps_tab_import_on_business_preview() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "audio.importTabDelimited",
        "arguments": {
            "import_file": "/owned/import.tsv",
            "import_location": {
                "kind": "path",
                "value": r"\Actor-Mixer Hierarchy\Default Work Unit",
            },
            "import_language": "SFX",
        },
    }

    protocol = build_metadata_transaction_protocol(
        (request,),
        object_type="Sound",
        metadata_queries=("looping enabled",),
        required_tokens=("IsLoopingEnabled",),
        equivalence="audio_import_tab_v1",
    )
    preview = next(
        step for step in protocol.steps if step.subcommand == "preview-from-draft"
    )
    assert preview.metadata_binding is not None
    assert preview.metadata_binding.step == "metadata.discover"
    assert preview.metadata_binding.required_tokens == ("IsLoopingEnabled",)
    assert all(step.subcommand != "typed-operation" for step in protocol.steps)


def test_metadata_transaction_protocol_selects_closed_object_set_equivalence() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {
                        "kind": "path",
                        "value": r"\Actor-Mixer Hierarchy\Target",
                    },
                    "properties": [{"name": "Volume", "value": -3}],
                }
            ]
        },
    }

    protocol = build_metadata_transaction_protocol(
        (request,),
        object_type="ActorMixer",
        metadata_queries=("volume",),
        required_tokens=("Volume",),
        equivalence="object_set_v1",
    )
    argument = next(
        step.arguments[-1]
        for step in protocol.steps
        if step.subcommand == "draft-apply"
    )
    assert isinstance(argument, DraftTypedActionArgument)
    assert argument.metadata_binding is not None
    assert argument.metadata_binding.step == "metadata.discover"
    assert argument.metadata_binding.required_tokens == ("Volume",)


@pytest.mark.parametrize(
    "arguments,match",
    (
        (
            {
                "requests": (),
                "object_type": "Sound",
                "metadata_queries": ("looping",),
                "required_tokens": ("IsLoopingEnabled",),
            },
            "at least one",
        ),
        (
            {
                "requests": (_request(),),
                "object_type": " Sound ",
                "metadata_queries": ("looping",),
                "required_tokens": ("IsLoopingEnabled",),
            },
            "object type",
        ),
        (
            {
                "requests": (_request(),),
                "object_type": "Sound",
                "metadata_queries": ("looping", " LOOPING "),
                "required_tokens": ("IsLoopingEnabled",),
            },
            "query suggestions",
        ),
        (
            {
                "requests": (_request(),),
                "object_type": "Sound",
                "metadata_queries": ("looping",),
                "required_tokens": ("Volume", "volume"),
            },
            "live tokens",
        ),
        (
            {
                "requests": (_request(),),
                "object_type": "Sound",
                "metadata_queries": ("looping",),
                "required_tokens": ("Volume",),
                "expected_required_token_projection": (
                    MetadataTokenProjection("Pitch", "property", "Real32"),
                ),
            },
            "projection",
        ),
        (
            {
                "requests": (_request(),),
                "object_type": "Sound",
                "metadata_queries": ("looping",),
                "required_tokens": ("Volume",),
                "equivalence": "audio_import_v1",
            },
            "only for audio.import",
        ),
        (
            {
                "requests": (_request(),),
                "object_type": "Sound",
                "metadata_queries": ("looping",),
                "required_tokens": ("Volume",),
                "equivalence": "audio_import_tab_v1",
            },
            "only for audio.importTabDelimited",
        ),
        (
            {
                "requests": (_request(),),
                "object_type": "ActorMixer",
                "metadata_queries": ("volume",),
                "required_tokens": ("Volume",),
                "equivalence": "object_set_v1",
            },
            "only for object.set",
        ),
        (
            {
                "requests": (_request(),),
                "object_type": "Sound",
                "metadata_queries": ("looping",),
                "required_tokens": ("Volume",),
                "equivalence": "open",
            },
            "wire_exact",
        ),
        (
            {
                "requests": (_request(),),
                "object_type": "Sound",
                "metadata_queries": ("looping",),
                "required_tokens": ("Volume",),
                "schema_first": "yes",
            },
            "schema_first",
        ),
    ),
)
def test_metadata_transaction_protocol_rejects_open_scope_inputs(
    arguments: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(V3ProtocolError, match=match):
        build_metadata_transaction_protocol(**arguments)  # type: ignore[arg-type]


def test_audio_import_metadata_equivalence_rejects_duplicate_expected_names() -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit\Target"
                    ),
                    "audio_file": native_absolute_test_path("audio", "source.wav"),
                    "properties": [
                        {"name": "Volume", "value": -1},
                        {"name": "Volume", "value": -2},
                    ],
                }
            ]
        },
    }

    with pytest.raises(V3ProtocolError, match="valid audio.import"):
        build_metadata_transaction_protocol(
            (request,),
            object_type="Sound",
            metadata_queries=("volume",),
            required_tokens=("Volume",),
            equivalence="audio_import_v1",
        )


def test_three_transactions_preserve_four_natural_turn_boundaries() -> None:
    protocol = build_transaction_protocol([_request(1), _request(2), _request(3)])

    assert protocol.turn_prefix_counts == (5, 14, 23, 27)
    assert len(protocol.steps) == 27
    assert [step.name for step in protocol.steps if step.subcommand == "preview-from-draft"] == [
        "tx01.preview",
        "tx02.preview",
        "tx03.preview",
    ]
    for index in range(1, 4):
        label = f"tx{index:02d}"
        by_name = {step.name: step for step in protocol.steps}
        assert by_name[f"{label}.confirm"].arguments == (
            ResponseBinding(f"{label}.transaction-show", "/transaction_id"),
            "--confirmation-token",
            ResponseBinding(f"{label}.transaction-show", "/confirmation/token"),
        )
        assert by_name[f"{label}.execute"].arguments == (
            ResponseBinding(f"{label}.confirm", "/transaction_id"),
        )
        assert by_name[f"{label}.verify"].arguments == (
            ResponseBinding(f"{label}.execute", "/transaction_id"),
        )


def test_structured_refusal_is_one_turn_and_exact_exit_two() -> None:
    protocol = build_transaction_protocol(
        [_request()], refusal=StructuredRefusal("INPUT_FILE_NOT_FOUND")
    )

    assert protocol.turn_prefix_counts == (5,)
    assert protocol.steps[-1].allowed_exit_codes == (2,)
    assert protocol.steps[-1].expected_error_code == "INPUT_FILE_NOT_FOUND"
    assert protocol.steps[-1].expected_result_command == "preview"


def test_terminal_execute_transaction_ends_at_execute_without_verify() -> None:
    protocol = build_transaction_protocol([_request()], terminal_execute=True)

    assert protocol.turn_prefix_counts == (5, 8)
    assert tuple(step.subcommand for step in protocol.steps) == (
        "operation-schema",
        "draft-start",
        "draft-declare-artifact-plan",
        "draft-check",
        "preview-from-draft",
        "transaction-show",
        "confirm",
        "execute",
    )
    assert protocol.steps[-1].allowed_exit_codes == (0, 2)
    assert protocol.steps[-1].terminal_execute is True


def test_terminal_execute_rejects_multi_request_or_refusal_combinations() -> None:
    with pytest.raises(V3ProtocolError, match="exactly one"):
        build_transaction_protocol(
            [_request(1), _request(2)], terminal_execute=True
        )
    with pytest.raises(V3ProtocolError, match="mutually exclusive"):
        build_transaction_protocol(
            [_request()],
            refusal=StructuredRefusal("INPUT_FILE_NOT_FOUND"),
            terminal_execute=True,
        )


def test_direct_call_and_topic_protocols_are_single_turn() -> None:
    protocol = build_direct_protocol(
        [
            call_step(
                "fields",
                "ak.wwise.core.mediaPool.getFields",
                version="2025.1",
            ),
            wait_topic_step(
                "generated",
                "ak.wwise.core.soundbank.generated",
                version="2025.1",
                event_count=4,
                match={},
            ),
        ]
    )
    assert protocol.turn_prefix_counts == (2,)
    assert protocol.steps[0].subcommand == "typed-zero-call"
    assert protocol.steps[1].gateway_global_arguments == ("--timeout", "120")
    assert protocol.steps[1].allow_omitted_default_event_count_one is False


def test_wait_topic_allows_omitted_event_count_only_for_the_default_one() -> None:
    default_step = wait_topic_step(
        "one",
        "ak.wwise.core.soundbank.generated",
        version="2025.1",
        event_count=1,
    )
    multiple_step = wait_topic_step(
        "multiple",
        "ak.wwise.core.soundbank.generated",
        version="2025.1",
        event_count=2,
    )

    assert default_step.allow_omitted_default_event_count_one is True
    assert multiple_step.allow_omitted_default_event_count_one is False


def test_call_step_binds_typed_facts_to_exact_contract() -> None:
    step = call_step(
        "transport.state",
        "ak.wwise.core.transport.getState",
        version="2025.1",
        args={"transport": 42},
    )
    assert step.subcommand == "typed-call"
    assert step.arguments[:2] == (
        "ak.wwise.core.transport.getState",
        "--schema-digest",
    )
    argument = step.arguments[-1]
    assert isinstance(argument, TypedRequestFactsArgument)
    assert argument.contract.version == "2025.1"
    assert argument.expected_args == {"transport": 42}
    assert argument.expected_options == {}


def test_media_pool_read_draft_appends_typed_post_filter() -> None:
    steps = typed_read_draft_steps(
        "media.get",
        "ak.wwise.core.mediaPool.get",
        version="2025.1",
        args={"maxResults": 200},
        options={"return": ["Filename"]},
        post_filter={
            "field": "Filename",
            "operator": "containsCaseSensitive",
            "value": "footstep",
            "limit": 20,
        },
    )
    check = steps[-1]
    assert check.subcommand == "draft-check"
    assert check.arguments[-4:] == (
        "--post-filter-value",
        "footstep",
        "--post-filter-limit",
        "20",
    )
    assert all("--post-filter-json" not in step.arguments for step in steps)

    with pytest.raises(V3ProtocolError, match="outside its closed contract"):
        typed_read_draft_steps(
            "bad",
            "ak.wwise.core.mediaPool.get",
            version="2025.1",
            args={"maxResults": 200},
            options={"return": ["Filename"]},
            post_filter={},
        )


def test_media_pool_read_draft_keeps_dynamic_choice_and_value_in_one_batch() -> None:
    steps = typed_read_draft_steps(
        "media",
        "ak.wwise.core.mediaPool.get",
        version="2025.1",
        args={
            "databases": [r"\Databases\Project Originals"],
            "filters": [
                {
                    "type": "field",
                    "field": "Filename",
                    "operator": "contains",
                    "value": "footstep",
                },
                {
                    "type": "field",
                    "field": "WAV/Duration",
                    "operator": "lessThan",
                    "value": 0.8,
                },
            ],
            "maxResults": 200,
        },
        options={
            "return": [
                "Path",
                "FileId",
                "Db",
                "Filename",
                "WAV/Duration",
                "WAV/Sample Rate",
                "WAV/Channels",
            ]
        },
        post_filter={
            "field": "Filename",
            "operator": "containsCaseSensitive",
            "value": "footstep",
            "limit": 20,
        },
    )

    action_batches = []
    for step in steps:
        if step.subcommand != "draft-apply":
            continue
        argument = step.arguments[-1]
        actions = (
            argument.actions
            if isinstance(argument, DraftTypedActionBatchArgument)
            else (argument,)
        )
        action_batches.append(tuple(action.expected for action in actions))

    assert tuple(len(batch) for batch in action_batches) == (6, 3, 5, 4, 5, 4)
    assert all(batch[-1]["fact_action"] != "choose-dynamic" for batch in action_batches)
    for batch in action_batches:
        for index, action in enumerate(batch):
            if action["fact_action"] != "choose-dynamic":
                continue
            paired = batch[index + 1]
            assert paired["fact_action"] == "map-put"
            assert paired["field_handle"] == action["field_handle"]
            assert paired["key"] == action["key"]


def test_wait_topic_and_operation_requests_use_typed_inputs() -> None:
    topic_step = wait_topic_step(
        "generated",
        "ak.wwise.core.soundbank.generated",
        version="2025.1",
        event_count=2,
        match={},
        options={},
    )
    assert "--options-json" not in topic_step.arguments
    assert "--match-json" not in topic_step.arguments
    assert "--options-schema-digest" in topic_step.arguments
    assert "--match-schema-digest" in topic_step.arguments

    protocol = build_transaction_protocol((_request(),))
    assert all("--request-json" not in step.arguments for step in protocol.steps)
    assert any(
        step.subcommand == "draft-declare-artifact-plan"
        for step in protocol.steps
    )


@pytest.mark.parametrize(
    "invalid",
    (
        {1: "non-string-key"},
        {"value": object()},
        {"value": {"unordered"}},
        {"value": float("nan")},
        {"value": float("inf")},
    ),
    ids=("key", "object", "set", "nan", "infinity"),
)
def test_call_step_rejects_values_outside_closed_json(invalid) -> None:
    with pytest.raises(V3ProtocolError):
        call_step(
            "bad",
            "ak.wwise.core.transport.getState",
            version="2025.1",
            args=invalid,
        )


def test_protocol_entry_points_reject_wrong_container_types_and_cycles() -> None:
    with pytest.raises(V3ProtocolError, match="call args must be a mapping"):
        call_step(
            "bad",
            "ak.wwise.core.transport.getState",
            version="2025.1",
            args=[],  # type: ignore[arg-type]
        )

    with pytest.raises(V3ProtocolError, match="non-string object key"):
        wait_topic_step(
            "bad",
            "ak.wwise.core.object.created",
            version="2025.1",
            event_count=1,
            match={False: "not-json"},  # type: ignore[dict-item]
        )

    cyclic: list[object] = []
    cyclic.append(cyclic)
    request = _request()
    request["arguments"] = {"cycle": cyclic}
    with pytest.raises(V3ProtocolError, match="recursive array"):
        build_transaction_protocol((request,))


def test_rejects_open_or_empty_request() -> None:
    with pytest.raises(V3ProtocolError, match="closed v1 envelope"):
        build_transaction_protocol([{"operation": "object.create"}])
