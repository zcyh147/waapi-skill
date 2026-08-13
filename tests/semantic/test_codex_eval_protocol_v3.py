from __future__ import annotations

import pytest

from tests.support.platform_filesystem import native_absolute_test_path
from tests.semantic.support.codex_eval_protocol_v3 import (
    _materialize_audio_import_composer_actions,
    StructuredRefusal,
    V3GatewayProtocol,
    V3ProtocolError,
    build_audio_import_composer_transaction_steps,
    build_direct_protocol,
    build_metadata_transaction_protocol,
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
    DraftTypedActionArgument,
    DraftActionMetadataBinding,
    ExpectedGatewayStep,
    MetadataQueryArgument,
    MetadataTokenProjection,
    ResponseBinding,
    TypedRequestFactsArgument,
    validate_commutative_composer_setup_step_groups,
)


def _request(index: int = 1) -> dict[str, object]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.create",
        "arguments": {"parent": {"kind": "path", "value": "\\Root"}, "name": f"N{index}", "type": "Sound"},
    }


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


def test_audio_import_composer_emits_ordered_typed_actions_without_full_json() -> None:
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
    action_arguments = [
        step.arguments[-1]
        for step in steps
        if step.subcommand == "draft-apply"
    ]

    assert all(isinstance(value, DraftTypedActionArgument) for value in action_arguments)
    assert [value.operation for value in action_arguments] == ["audio.import"] * 5
    assert [value.expected["action"] for value in action_arguments] == [
        "set_import_option",
        "set_import_default",
        "set_import_default",
        "set_import_default",
        "add_import_row",
    ]
    assert action_arguments[3].metadata_binding == metadata
    assert action_arguments[4].metadata_binding == metadata
    assert action_arguments[4].expected["assignment"] == {"mode": "none"}
    assert next(step for step in steps if step.name == "tx01.preview").subcommand == (
        "preview-from-draft"
    )
    assert all(
        "--request-json" not in step.arguments
        for step in steps
    )


def test_audio_import_switch_assignment_is_part_of_the_initial_row_action() -> None:
    request = _audio_import_request()
    switch_assignment = "Snow"
    request["arguments"]["imports"][0]["switch_assignment"] = switch_assignment  # type: ignore[index]

    action_arguments = [
        step.arguments[-1]
        for step in build_audio_import_composer_transaction_steps(
            request,
            label="tx01",
        )
        if step.subcommand == "draft-apply"
    ]

    row = action_arguments[-1]
    assert row.expected["action"] == "add_import_row"
    assert row.expected["assignment"] == {
        "mode": "switch",
        "value": switch_assignment,
    }
    assert row.response_bindings == ()

    request["arguments"]["imports"][0].pop("switch_assignment")  # type: ignore[index]
    ordinary_row = [
        step.arguments[-1]
        for step in build_audio_import_composer_transaction_steps(
            request,
            label="tx01",
        )
        if step.subcommand == "draft-apply"
    ][-1]
    assert ordinary_row.expected["action"] == "add_import_row"
    assert ordinary_row.expected["assignment"] == {"mode": "none"}
    assert ordinary_row.response_bindings == ()


def test_audio_import_archive_replay_preserves_the_removed_assigned_row_action() -> None:
    materialized = _materialize_audio_import_composer_actions(
        (
            {
                "contract": "waapi-skill.operation-draft-action/v1",
                "action": "add_switch_assigned_import_row",
                "object_path": (
                    r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps\Snow"
                ),
                "object_type": "RandomSequenceContainer",
                "assignment": {"mode": "switch", "value": "Snow"},
            },
        ),
        version="2022.1",
    )

    assert materialized["arguments"]["imports"] == [
        {
            "object_path": (
                r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps\Snow"
            ),
            "object_type": "RandomSequenceContainer",
            "switch_assignment": "Snow",
        }
    ]


def test_audio_import_composer_rejects_unreviewed_request_fields() -> None:
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
    actions = [
        step.arguments[-1].expected
        for step in steps
        if step.subcommand == "draft-apply"
    ]

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
    actions = [
        step.arguments[-1].expected
        for step in steps
        if step.subcommand == "draft-apply"
    ]

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


def test_single_transaction_spans_two_turn_prefixes_with_response_bindings() -> None:
    protocol = build_transaction_protocol([_request()])

    assert protocol.turn_prefix_counts == (9, 13)
    assert tuple(step.subcommand for step in protocol.steps) == (
        "operation-schema",
        "draft-start",
        "draft-apply",
        "draft-apply",
        "draft-apply",
        "draft-apply",
        "draft-apply",
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


def test_non_object_transaction_request_uses_typed_composer_actions() -> None:
    protocol = build_transaction_protocol([_audio_import_request()])

    actions = tuple(
        step.arguments[-1]
        for step in protocol.steps
        if step.subcommand == "draft-apply"
    )
    assert actions
    assert all(isinstance(value, DraftTypedActionArgument) for value in actions)
    assert all(value.operation == "audio.import" for value in actions)
    assert all("--request-json" not in step.arguments for step in protocol.steps)


def test_soundbank_generate_transaction_uses_typed_draft_facts() -> None:
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

    actions = tuple(
        step.arguments[-1]
        for step in protocol.steps
        if step.subcommand == "draft-apply"
    )
    assert actions
    assert all(isinstance(value, DraftTypedActionArgument) for value in actions)
    assert all(value.operation == "soundbank.generate" for value in actions)
    assert any(step.subcommand == "preview-from-draft" for step in protocol.steps)
    assert all("--request-json" not in step.arguments for step in protocol.steps)


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


def test_schema_query_protocol_requires_one_exact_auditable_object_lookup() -> None:
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

    assert protocol.turn_prefix_counts == (10, 14)
    assert tuple(step.subcommand for step in protocol.steps[:3]) == (
        "operation-schema",
        "query-object",
        "draft-start",
    )
    assert protocol.steps[1] == query


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
    action_arguments = [
        step.arguments[-1]
        for step in protocol.steps
        if step.subcommand == "draft-apply"
    ]

    assert protocol.turn_prefix_counts == (7, 11)
    assert tuple(step.subcommand for step in protocol.steps[:2]) == (
        "operation-schema",
        "metadata",
    )
    assert [argument.expected["action"] for argument in action_arguments] == [
        "set_import_default",
        "add_import_row",
    ]
    assert all(
        isinstance(argument, DraftTypedActionArgument)
        and argument.operation == "audio.import"
        for argument in action_arguments
    )
    assert action_arguments[0].metadata_binding is not None
    assert action_arguments[1].metadata_binding is None
    assert sum(step.subcommand == "metadata" for step in protocol.steps) == 1
    assert protocol.commutative_read_only_step_groups == (
        ("tx01.operation-schema", "metadata.discover"),
    )
    assert "preview" not in {
        step.subcommand for step in protocol.steps
    }
    assert "preview-from-draft" in {
        step.subcommand for step in protocol.steps
    }


def test_metadata_transaction_protocol_selects_closed_tab_import_equivalence() -> None:
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
    typed_operation = next(
        step for step in protocol.steps if step.subcommand == "typed-operation"
    )
    assert typed_operation.metadata_binding is not None
    assert typed_operation.metadata_binding.step == "metadata.discover"
    assert typed_operation.metadata_binding.required_tokens == ("IsLoopingEnabled",)


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

    assert protocol.turn_prefix_counts == (9, 22, 35, 39)
    assert len(protocol.steps) == 39
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

    assert protocol.turn_prefix_counts == (9,)
    assert protocol.steps[-1].allowed_exit_codes == (2,)
    assert protocol.steps[-1].expected_error_code == "INPUT_FILE_NOT_FOUND"
    assert protocol.steps[-1].expected_result_command == "preview"


def test_terminal_execute_transaction_ends_at_execute_without_verify() -> None:
    protocol = build_transaction_protocol([_request()], terminal_execute=True)

    assert protocol.turn_prefix_counts == (9, 12)
    assert tuple(step.subcommand for step in protocol.steps) == (
        "operation-schema",
        "draft-start",
        "draft-apply",
        "draft-apply",
        "draft-apply",
        "draft-apply",
        "draft-apply",
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
    assert any(step.subcommand == "draft-apply" for step in protocol.steps)


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
