from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import wave

import pytest

from wwise_waapi.console_project_operations import CLI_PROJECT_FILE_URIS

from tests.support.public_route_probes import (
    ProgramCallClient,
    ProgramTopicClient,
    PROBE_IO_ROOT,
    request_and_result_from_schema,
    synthesize_schema_value,
)
from tests.support.compound_undo import compound_undo_request
from wwise_waapi.builders.schema import (
    validate_semantic_event,
    validate_semantic_payload,
    validate_semantic_result,
)
from wwise_waapi.capabilities import CapabilityCatalog, CapabilityRecord
from wwise_waapi.dispatcher import WwiseDispatcher
from wwise_waapi.execution_contracts import ExecutionContractRegistry
from wwise_waapi.operation_registry import (
    OPERATION_REQUEST_CONTRACT,
    UNDO_GROUP_INNER_URIS_BY_VERSION,
    OperationContractError,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
    verify_prepared_operation,
)
from wwise_waapi.soundengine_business_contracts import (
    soundengine_control_business_operations,
)
from wwise_waapi.typed_operations import compound_child_request_contract
from wwise_waapi.typed_requests import TypedRequestFact, materialize_typed_request
from wwise_waapi.transaction_cleanup import CLEANUP_SPEC_CONTRACT
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


CATALOG = CapabilityCatalog()
PROGRAM_ROWS = tuple(
    entry
    for version in SUPPORTED_WWISE_VERSION_KEYS
    for entry in CATALOG.entries(version)
    if entry.execution_contract.get("executable") is True
)
BUSINESS_STATE_VERIFIED_APIS = frozenset(
    {
        "ak.wwise.core.remote.connect",
        "ak.wwise.core.remote.disconnect",
        "ak.wwise.core.transport.create",
        "ak.wwise.core.transport.destroy",
        "ak.wwise.core.sound.setActiveSource",
        "ak.wwise.core.gameParameter.setRange",
    }
)
SOUNDENGINE_BUSINESS_APIS = frozenset(soundengine_control_business_operations())


def _row_id(entry: CapabilityRecord) -> str:
    return f"{entry.version}:{entry.item_type}:{entry.uri}"


@pytest.mark.parametrize("entry", PROGRAM_ROWS, ids=_row_id)
def test_every_public_route_executes_through_packaged_program_code(entry: CapabilityRecord, tmp_path: Path) -> None:
    contract = entry.execution_contract
    assert contract["program_case"]
    assert contract["gateway_commands"]
    assert entry.preferred_route != "unsupported_boundary"

    if entry.item_type == "topic":
        publish_schema = entry.schema.get("publishSchema")
        event_payload: Any = synthesize_schema_value(
            publish_schema if isinstance(publish_schema, Mapping) else {},
            field_name="event",
        )
        client = ProgramTopicClient(event_payload)
        result = WwiseDispatcher(client=client).dispatch(
            entry.uri,
            version=entry.version,
            timeout=1.0,
            result_limit_bytes=int(contract["result_limit_bytes"]),
        )

        assert result["ok"] is True, result
        assert client.subscriptions == [entry.uri]
        assert client.handler.unsubscribe_count == 1
        assert result["result"]["topic"] == entry.uri
        event_validation = validate_semantic_event(
            entry.uri,
            result["result"]["payload"],
            version=entry.version,
        )
        assert event_validation.section == "event"
        return

    if entry.uri == "ak.wwise.core.sourceControl.setProvider":
        # The closed route requires a private-profile proof. Synthesized native
        # arguments cannot replace that public binding or bypass confidentiality.
        from tests.unit.test_remaining_core_business_gateway import (
            _provider_profile_case,
            _authorize_provider_preview,
            _assert_no_provider_secret_artifacts,
        )
        client, run, preview, state, evidence, _profile, _credential, secret = (
            _provider_profile_case(tmp_path, version=entry.version)
        )
        assert contract["gateway_commands"] == ["request-schema"]
        assert client.calls == []
        _authorize_provider_preview(run, preview)
        code, executed = run("execute", preview["transaction_id"])
        assert code == 0 and executed["executed"] is True, executed
        assert len(client.calls) == 1
        assert client.calls[0][0]["provider"] == "Perforce"
        assert client.calls[0][0]["password"] == secret
        code, verified = run("verify", preview["transaction_id"])
        assert code == 0 and verified["verified"] is False, verified
        assert verified["result_schema_checked"] is True
        observation = verified["agent_result"]["result"]
        assert observation["protected_native_result"] is True
        assert observation["native_result_schema_valid"] is True
        assert observation["native_text_disclosed"] is False
        assert observation["provider_identity_verified"] is False
        assert observation["provider_effects_verified"] is False
        _assert_no_provider_secret_artifacts(state, evidence, secret, preview, executed, verified)
        code, replay = run("execute", preview["transaction_id"])
        assert code != 0 and len(client.calls) == 1, replay
        return

    if entry.uri in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"}:
        # History now requires an owned scoped expectation through the public
        # business Draft; empty schema arguments cannot establish that proof.
        from tests.unit.test_compound_undo_business_gateway import _owned_notes_history_case
        client, _state, _source, preview, _shown, run = _owned_notes_history_case(
            tmp_path, version=entry.version, direction=entry.uri.rsplit(".", 1)[-1])
        assert not any(call[0] == entry.uri for call in client.calls)
        code, executed = run("execute", preview["transaction_id"])
        assert code == 0 and executed["executed"] is True, executed
        assert [call[1:] for call in client.calls if call[0] == entry.uri] == [({}, {})]
        code, verified = run("verify", preview["transaction_id"])
        assert code == 0 and verified["verified"] is True, verified
        assert verified["verification_strength"] == "scoped_history_effect_readback"
        assert verified["agent_result"]["result"] == {}
        assert list(verified)[-1] == "agent_result"
        code, replay = run("execute", preview["transaction_id"])
        assert code != 0 and len([call for call in client.calls if call[0] == entry.uri]) == 1, replay
        return

    args, options, expected_result = request_and_result_from_schema(entry.schema)
    earlier_void = (entry.version in {"2021.1", "2022.1", "2023.1"} and entry.uri in {
        "ak.wwise.cli.moveMediaIdsToSingleFile", "ak.wwise.cli.moveMediaIdsToWorkUnits",
        "ak.wwise.cli.updateMediaIdsInSingleFile"})
    if entry.uri in CLI_PROJECT_FILE_URIS:
        # Independent documented successful process outcome; this proves no
        # project/file effect. Older media-ID routes disclose no outcome field.
        expected_result = {} if earlier_void else {"result": 0}
    if entry.uri == "ak.wwise.core.sound.setActiveSource":
        # This Registry/dispatcher matrix uses explicit file-source state, not
        # native Source-plugin acceptance or a synthesized shared role GUID.
        args, options = {"sound": "{11111111-1111-1111-1111-111111111111}",
                         "source": "{22222222-2222-2222-2222-222222222222}"}, {}
    if entry.uri == "ak.wwise.core.transport.create":
        # The reflected field is optional, but the business verifier requires
        # a real uint32 ID. Wwise 2022.1 may assign zero to the first transport.
        expected_result = {"transport": 0}
    if (
        entry.version in {"2024.1", "2025.1"}
        and entry.uri == "ak.wwise.core.audio.convert"
    ):
        # The reflected schema allows empty arrays and leaves external item
        # references unresolved.  Exercise the narrower reviewed product
        # contract with one canonical value in each required ordered array.
        args = {
            "objects": [
                r"\Actor-Mixer Hierarchy\Default Work Unit\Program Probe"
            ],
            "platforms": ["Mac"],
            "languages": ["SFX"],
        }
    io_root = PROBE_IO_ROOT
    prepared_before_dispatch = None
    role_validation_before_dispatch = None
    artifact_effect = None
    if entry.uri == "ak.wwise.debug.generateToneWAV":
        # This row exercises the Registry/dispatcher seam, not full public or
        # native acceptance. Keep actual filesystem protections and artifact
        # verification active: the fake dispatch alone creates a known WAV.
        io_root = (tmp_path / "isolated-tone-output").resolve()
        io_root.mkdir()
        output = io_root / "tone.wav"
        args, options = {"path": str(output)}, {}
        tone_request = parse_operation_request({
            "contract": OPERATION_REQUEST_CONTRACT, "version": entry.version,
            "operation": "waapi.call", "arguments": {
                "api": entry.uri, "args": args, "options": options, "io_root": str(io_root)}})
        prepared_before_dispatch = prepare_operation(tone_request,
            read_call=lambda uri, call_args, call_options: {})
        role_validation_before_dispatch = validate_prepared_roles(prepared_before_dispatch.as_dict(),
            read_call=lambda uri, call_args, call_options: {})
        assert role_validation_before_dispatch["ok"] is True
        assert prepared_before_dispatch.as_dict()["verification_plan"]["before"]["file"] is None
        assert not output.exists()

        def artifact_effect(uri, call_args, call_options):
            assert (uri, call_args, call_options) == (entry.uri, {"path": str(output)}, {})
            assert not output.exists()
            # Literal source-default fixture: mono PCM16, 48000Hz, one second
            # of digital silence. No request-derived writer or verifier mock.
            with wave.open(str(output), "wb") as stream:
                stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                stream.writeframes(b"\x00\x00" * 48000)
    elif entry.uri in {"ak.wwise.console.project.create", "ak.wwise.ui.project.create"}:
        io_root = (tmp_path / "ProgramProbe").resolve()
        io_root.mkdir()
        output = io_root / "ProgramProbe.wproj"
        args, options = {"path": str(output)}, {}
        project_request = parse_operation_request({
            "contract": OPERATION_REQUEST_CONTRACT, "version": entry.version,
            "operation": "waapi.call", "arguments": {
                "api": entry.uri, "args": args, "options": options, "io_root": str(io_root)}})
        prepared_before_dispatch = prepare_operation(project_request,
            read_call=lambda uri, call_args, call_options: {})
        role_validation_before_dispatch = validate_prepared_roles(prepared_before_dispatch.as_dict(),
            read_call=lambda uri, call_args, call_options: {})
        assert role_validation_before_dispatch["ok"] is True
        assert prepared_before_dispatch.as_dict()["verification_plan"]["before"]["exists"] is False
        assert not output.exists()
        # Literal independently specified default project, using the matching
        # pinned SDK sample schema versions. The writer does not inspect args.
        header = {
            "2023.1": '<WwiseDocument Type="Project" SchemaVersion="119" WwiseVersion="v2023.1.0">',
            "2024.1": '<WwiseDocument Type="Project" SchemaVersion="123" WwiseVersion="v2024.1.0">',
            "2025.1": '<WwiseDocument Type="Project" SchemaVersion="133" WwiseVersion="v2025.1.0">',
        }[entry.version]
        project_xml = header + '''<ProjectInfo><Project Name="ProgramProbe" ID="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}">
<Platforms><Platform Name="Windows" ReferencePlatform="Windows" ID="{CCCCCCCC-CCCC-CCCC-CCCC-000000000001}" /></Platforms>
<LanguageList><Language Name="SFX" ID="{DDDDDDDD-DDDD-DDDD-DDDD-000000000001}" />
<Language Name="English(US)" ID="{DDDDDDDD-DDDD-DDDD-DDDD-000000000002}" /></LanguageList>
<PropertyList><Property Name="DefaultLanguage" Type="string" Value="English(US)" /></PropertyList>
</Project></ProjectInfo></WwiseDocument>'''

        def artifact_effect(uri, call_args, call_options):
            assert (uri, call_args, call_options) == (entry.uri, {"path": str(output)}, {})
            assert not output.exists()
            output.write_text(project_xml, encoding="utf-8")

    elif entry.uri == "ak.wwise.console.project.open":
        # Open seals the actual saved input before dispatch. This Registry-only
        # matrix does not observe a live transition and cannot grant effect credit.
        io_root = (tmp_path / "console-open-input").resolve()
        io_root.mkdir()
        project = io_root / "ProgramProbe.wproj"
        project.write_text('''<WwiseDocument Type="Project"><ProjectInfo>
<Project Name="ProgramProbe" ID="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}" />
</ProjectInfo></WwiseDocument>''', encoding="utf-8")
        args, options = {"path": str(project)}, {}
        project_request = parse_operation_request({
            "contract": OPERATION_REQUEST_CONTRACT, "version": entry.version,
            "operation": "waapi.call", "arguments": {
                "api": entry.uri, "args": args, "options": options, "io_root": str(io_root)}})
        prepared_before_dispatch = prepare_operation(project_request,
            read_call=lambda uri, call_args, call_options: {})
        role_validation_before_dispatch = validate_prepared_roles(prepared_before_dispatch.as_dict(),
            read_call=lambda uri, call_args, call_options: {})
        assert role_validation_before_dispatch["ok"] is True
        plan = prepared_before_dispatch.as_dict()["verification_plan"]
        assert plan["project"] == {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", "name": "ProgramProbe"}
        assert plan["path"] == str(project)
        assert plan["file_proof"]["size"] == len(project.read_bytes())

    elif entry.uri in CLI_PROJECT_FILE_URIS:
        # These matrix rows deliberately supply only a successful process result,
        # with no filesystem effect. Freeze real isolated inputs so the current
        # independent observer can reject missing effects or retain its explicit
        # partial boundary, rather than failing at an invented path prerequisite.
        io_root = (tmp_path / "cli-project-effect").resolve()
        io_root.mkdir()
        project = io_root / "ProgramProbe.wproj"
        args, options = {"project": str(project)}, {}
        if entry.uri == "ak.wwise.cli.createNewProject":
            args["platform"] = ["Windows"]
        else:
            schema_version = {"2021.1": "103", "2022.1": "110", "2023.1": "119",
                              "2024.1": "123", "2025.1": "133"}[entry.version]
            project.write_text(
                f'<WwiseDocument Type="Project" SchemaVersion="{schema_version}" WwiseVersion="v{entry.version}.0">'
                + '''<ProjectInfo><Project Name="ProgramProbe" ID="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}">
<Platforms><Platform Name="Windows" ReferencePlatform="Windows" ID="{CCCCCCCC-CCCC-CCCC-CCCC-000000000001}" /></Platforms>
<LanguageList><Language Name="SFX" ID="{DDDDDDDD-DDDD-DDDD-DDDD-000000000001}" />
<Language Name="English(US)" ID="{DDDDDDDD-DDDD-DDDD-DDDD-000000000002}" /></LanguageList>
<PropertyList><Property Name="DefaultLanguage" Type="string" Value="English(US)" /></PropertyList>
</Project></ProjectInfo></WwiseDocument>''', encoding="utf-8")
        if entry.uri == "ak.wwise.cli.addNewPlatform":
            args.update({"new-platform-name": "Studio", "new-platform-base": "Windows"})
        elif entry.uri == "ak.wwise.cli.dumpObjects":
            args["output"] = str(io_root / "objects.json")
        cli_request = parse_operation_request({
            "contract": OPERATION_REQUEST_CONTRACT, "version": entry.version,
            "operation": "waapi.call", "arguments": {
                "api": entry.uri, "args": args, "options": options, "io_root": str(io_root)}})
        prepared_before_dispatch = prepare_operation(cli_request,
            read_call=lambda uri, call_args, call_options: {})
        role_validation_before_dispatch = validate_prepared_roles(prepared_before_dispatch.as_dict(),
            read_call=lambda uri, call_args, call_options: {})
        assert role_validation_before_dispatch["ok"] is True
        if entry.uri == "ak.wwise.cli.verify":
            # Verify reports a documented process outcome; it does not request
            # a project write or claim independently observed filesystem effects.
            assert "cli_project_effect" not in prepared_before_dispatch.as_dict()["pre_state"]
        else:
            assert prepared_before_dispatch.as_dict()["pre_state"]["cli_project_effect"]["uri"] == entry.uri

    request_validation = validate_semantic_payload(
        entry.uri,
        args,
        options,
        version=entry.version,
    )
    client = ProgramCallClient(expected_result, on_call=artifact_effect)
    result = WwiseDispatcher(client=client).dispatch(
        entry.uri,
        version=entry.version,
        args=args,
        options=options,
        timeout=1.0,
        allow_destructive=True,
        result_limit_bytes=int(contract["result_limit_bytes"]),
    )

    assert request_validation.uri == entry.uri
    assert result["ok"] is True, result
    assert result["result"] == expected_result
    assert client.calls == [(entry.uri, args, options)]
    result_validation = validate_semantic_result(
        entry.uri,
        result["result"],
        version=entry.version,
    )
    assert result_validation.section == "result"

    if entry.uri in SOUNDENGINE_BUSINESS_APIS:
        # This matrix still proves the reflected native bottom call above.  The
        # public route is now the closed business Draft/read contract exercised
        # in test_soundengine_business_gateway; feeding synthesized native args
        # into Registry preparation would test the retired caller boundary.
        assert contract["gateway_commands"] == ["request-schema"]
        assert entry.preferred_route in {"transaction_operation", "manifest_dispatch"}
        return

    if contract["route"] == "compound_transaction_member":
        assert entry.transaction_operations == ("waapi.undoGroup",)
        with pytest.raises(OperationContractError, match="waapi.undoGroup"):
            parse_operation_request(
                {
                    "contract": OPERATION_REQUEST_CONTRACT,
                    "version": entry.version,
                    "operation": "waapi.call",
                    "arguments": {"api": entry.uri, "args": args, "options": options},
                }
            )
        inner_operation = "ak.wwise.core.object.setRandomizer"
        inner_uri = inner_operation
        inner_capability = CATALOG.describe(entry.version, inner_uri)
        _inner_args, _inner_options, inner_result = request_and_result_from_schema(
            inner_capability.schema
        )
        child_contract = compound_child_request_contract(
            inner_operation, entry.version
        )
        # The reflected anyOf route is easiest to exercise with explicit
        # object/property/enabled facts and its disclosed object branch.
        object_field = next(
            field for field in child_contract.fields
            if field.path == ("object",) and field.shape == "scalar"
            and any(variant.get("pattern") == r"^\\" for variant in field.variants)
        )
        child_facts = [
            TypedRequestFact("choose", object_field.parent_handle, "branch", object_field.handle),
            TypedRequestFact("set", object_field.handle, "string", r"\ProgramObject"),
            TypedRequestFact("set", next(field.handle for field in child_contract.fields if field.path == ("property",) and field.shape == "scalar"), "string", "Volume"),
            TypedRequestFact("set", next(field.handle for field in child_contract.fields if field.path == ("enabled",)), "boolean", "true"),
        ]
        materialized = materialize_typed_request(
            child_contract,
            schema_digest=child_contract.schema_digest,
            facts=child_facts,
        )
        child_request = {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": entry.version,
            "operation": "waapi.call",
            "arguments": {
                "api": inner_operation,
                "args": dict(materialized.args),
                "options": dict(materialized.options),
            },
        }
        undo_request = parse_operation_request(
            compound_undo_request(
                version=entry.version,
                child_requests=[child_request],
                display_name="Program probe",
            )
        )
        undo_prepared = prepare_operation(
            undo_request,
            read_call=lambda uri, call_args, call_options: {},
        ).as_dict()
        assert validate_prepared_roles(
            undo_prepared,
            read_call=lambda uri, call_args, call_options: {},
        )["ok"] is True
        phases = []
        for phase_uri, phase_result in (
            ("ak.wwise.core.undo.beginGroup", {}),
            (inner_uri, inner_result),
            ("ak.wwise.core.undo.endGroup", {}),
        ):
            phases.append(
                {
                    "uri": phase_uri,
                    "dispatch_result": {
                        "ok": True,
                        "api": phase_uri,
                        "version": entry.version,
                        "result": phase_result,
                    },
                }
            )
        undo_verification = verify_prepared_operation(
            undo_prepared,
            execution_result={"result": {"same_connection": True, "phases": phases}},
            read_call=lambda uri, call_args, call_options: {},
        )
        assert undo_verification.status == "result_schema_checked"
        assert undo_verification.business_state_verified is False
        return

    if contract["route"] not in {
        "transaction",
        "managed_transaction",
        "isolated_transaction",
    }:
        return

    if "waapi.call" not in entry.transaction_operations:
        assert entry.transaction_operations
        with pytest.raises(OperationContractError) as dedicated:
            parse_operation_request(
                {
                    "contract": OPERATION_REQUEST_CONTRACT,
                    "version": entry.version,
                    "operation": "waapi.call",
                    "arguments": {"api": entry.uri, "args": args, "options": options},
                },
                expected_version=entry.version,
            )
        assert dedicated.value.error_code == "DEDICATED_OPERATION_REQUIRED"
        assert dedicated.value.details["required_operations"] == list(entry.transaction_operations)
        return

    arguments: dict[str, Any] = {"api": entry.uri, "args": args, "options": options}
    if contract["route"] == "isolated_transaction":
        arguments["io_root"] = str(io_root)
    operation_request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": entry.version,
            "operation": "waapi.call",
            "arguments": arguments,
        },
        expected_version=entry.version,
    )
    def preparation_readback(uri, call_args, call_options):
        if entry.uri == "ak.wwise.core.sound.setActiveSource" and uri == "ak.wwise.core.object.get":
            objects = {
                "{11111111-1111-1111-1111-111111111111}": {
                    "id": "{11111111-1111-1111-1111-111111111111}", "name": "Program Sound", "type": "Sound",
                    "classId": 65552, "path": r"\Program Sound"},
                "{22222222-2222-2222-2222-222222222222}": {
                    "id": "{22222222-2222-2222-2222-222222222222}", "name": "Program Source", "type": "AudioFileSource",
                    "classId": 16, "path": r"\Program Sound\Program Source",
                    "parent": {"id": "{11111111-1111-1111-1111-111111111111}"}},
            }
            return {"return": [{key: row[key] for key in call_options["return"] if key in row}
                for identity in call_args["from"]["id"] if (row := objects.get(identity)) is not None]}
        if uri == "ak.wwise.core.remote.getConnectionStatus":
            return {"isConnected": False, "status": "Not connected"}
        return {}
    prepared = prepared_before_dispatch or prepare_operation(
        operation_request, read_call=preparation_readback)
    prepared_payload = prepared.as_dict()
    role_validation = role_validation_before_dispatch or validate_prepared_roles(
        prepared_payload,
        read_call=preparation_readback,
    )
    def readback(uri: str, call_args: Mapping[str, Any], call_options: Mapping[str, Any]) -> Mapping[str, Any]:
        if uri == "ak.wwise.core.object.get":
            if entry.uri == "ak.wwise.core.sound.setActiveSource":
                assert call_args == {"from": {"id": [args["sound"]]}}
                return {
                    "return": [
                        {
                            "id": args["sound"],
                            "name": "Program Sound",
                            "type": "Sound",
                            "path": r"\Program Sound",
                            "activeSource": {"id": args["source"]},
                        }
                    ]
                }
            if entry.uri == "ak.wwise.core.gameParameter.setRange":
                assert call_args == {"from": {"id": [args["object"]]}}
                return {
                    "return": [
                        {
                            "id": args["object"],
                            "name": "Program Game Parameter",
                            "type": "GameParameter",
                            "path": r"\Game Parameters\Program Game Parameter",
                            "@Min": args["min"],
                            "@Max": args["max"],
                        }
                    ]
                }
        assert call_options == {}
        if uri == "ak.wwise.core.remote.getConnectionStatus":
            return {
                "isConnected": entry.uri == "ak.wwise.core.remote.connect",
                "status": "program fixture",
                **({"console": {"host": args["host"], "appName": args.get("appName", "Program Game"),
                    "name": "Program Console", "platform": "Windows", "customPlatform": "Windows"}}
                   if entry.uri == "ak.wwise.core.remote.connect" else {}),
            }
        if uri == "ak.wwise.core.remote.getAvailableConsoles":
            return {"consoles": [{"host": args["host"], "appName": args.get("appName", "Program Game"),
                "name": "Program Console", "platform": "Windows", "customPlatform": "Windows",
                "commandPort": args.get("commandPort", 0),
                **({"notificationPort": args.get("notificationPort", 0)} if entry.version == "2021.1" else {})}]}
        if uri == "ak.wwise.core.transport.getList":
            if entry.uri == "ak.wwise.core.transport.create":
                # Model the created association as well as its native ID;
                # public mismatch controls exercise incorrect associations.
                return {"list": [{"transport": 0, "object": args["object"],
                    **({"gameObject": args["gameObject"]} if "gameObject" in args else {})}]}
            if entry.uri == "ak.wwise.core.transport.destroy":
                return {"list": []}
        if uri == "ak.wwise.core.transport.getState":
            assert call_args == {"transport": 0}
            return {"state": "stopped"}
        raise AssertionError(f"unexpected program verification readback: {uri}")

    verification = verify_prepared_operation(
        prepared_payload,
        execution_result=result,
        read_call=(
            readback
            if entry.uri in BUSINESS_STATE_VERIFIED_APIS
            else lambda uri, call_args, call_options: {}
        ),
    )

    assert prepared_payload["dispatch"] == {"uri": entry.uri, "args": args, "options": options}
    prepared_contract = prepared_payload["semantic_preview"]["envelope"]["metadata"]["execution_contract"]
    if contract["route"] == "isolated_transaction":
        assert prepared_contract["io_audit"]["ok"] is True
        assert prepared_contract["io_audit"]["confinement_scope"] == "explicit_write_paths_only"
        assert prepared_contract["io_audit"]["io_root"] == str(io_root)
    if contract["companion_uris"]:
        cleanup = prepared_payload["cleanup"]
        assert cleanup["contract"] == CLEANUP_SPEC_CONTRACT
        assert cleanup["api"] == entry.uri
        assert cleanup["lifecycle_action"] == "opener"
        assert cleanup["lifecycle_strategy"] == contract["lifecycle_strategy"]
        assert cleanup["companion_request"]["api"] == contract["companion_uris"][0]
        assert cleanup["automatic_cleanup"] is False
        assert cleanup["automatic_retry"] is False
        assert len(cleanup["spec_sha256"]) == 64
    assert role_validation["ok"] is True
    missing_cli_effect = entry.uri in {
        "ak.wwise.cli.createNewProject", "ak.wwise.cli.addNewPlatform", "ak.wwise.cli.dumpObjects",
    }
    assert verification.ok is (not missing_cli_effect), verification.as_dict()
    if entry.uri == "ak.wwise.debug.generateToneWAV":
        assert verification.status == "verified"
        assert verification.business_state_verified is True
        assert verification.verification_strength == "tone_wav_artifact"
        observed = verification.readbacks[0]
        assert observed["created"] is True
        assert observed["changed"] is True
        assert observed["unresolved"] == []
        assert observed["wav"]["channels"] == 1
        assert observed["wav"]["sample_rate"] == 48000
        assert observed["wav"]["sample_format"] == "int16"
        assert observed["wav"]["frames"] == 48000
        assert observed["wav"]["nonzero_samples_by_channel"] == [0]
        assert len(observed["artifact"]["file"]["sha256"]) == 64
    elif entry.uri in {"ak.wwise.console.project.create", "ak.wwise.ui.project.create"}:
        assert verification.status == "verified"
        assert verification.business_state_verified is True
        assert verification.verification_strength == "saved_project_artifact"
        observed = verification.readbacks[0]
        assert observed["project"] == {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", "name": "ProgramProbe"}
        assert observed["platforms_match"] is True
        assert observed["languages_match"] is True
        assert observed["default_language"] == "English(US)"
        assert observed["unresolved"] == []
        assert len(observed["file_proof"]["sha256"]) == 64
    elif entry.uri == "ak.wwise.console.project.open":
        assert verification.status == "result_schema_checked"
        assert verification.business_state_verified is False
        assert verification.verification_strength == "saved_project_input_identity"
        assert verification.readbacks[0]["project"] == {
            "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", "name": "ProgramProbe"}
        assert verification.readbacks[0]["file_proof"] == prepared_payload["verification_plan"]["file_proof"]
    elif entry.uri in CLI_PROJECT_FILE_URIS:
        observed = verification.readbacks[0]
        # Process success remains a separate fact from the unchanged/missing
        # project artifacts. No fake native response can grant business credit.
        assert observed["business_effect_proven"] is False
        assert observed["outcome"] == ("not_reported" if earlier_void else "success")
        assert ("exit_code" not in observed) if earlier_void else observed["exit_code"] == 0
        assert verification.business_state_verified is False
        if entry.uri == "ak.wwise.cli.verify":
            assert verification.status == "result_schema_checked"
            assert verification.verification_strength == "documented_cli_process_outcome"
            assert verification.readbacks == (observed,)
        elif entry.uri in {
            "ak.wwise.cli.createNewProject", "ak.wwise.cli.addNewPlatform", "ak.wwise.cli.dumpObjects",
        }:
            assert verification.status == "verification_failed"
            assert any(not row["passed"] for row in verification.assertions)
        else:
            assert verification.status == "result_schema_checked"
            assert verification.verification_strength == "independent_console_project_file_artifact"
            expected_boundary = (
                "migration_save_has_no_observed_write" if entry.uri == "ak.wwise.cli.migrate"
                else "central_media_id_mapping_representation"
            )
            if entry.uri == "ak.wwise.cli.migrate":
                effect = verification.readbacks[-1]
            else:
                effects = [row for row in verification.readbacks if row.get("kind") == "cli-media-id-artifacts"]
                assert len(effects) == 1, verification.readbacks
                effect = effects[0]
            assert effect["unresolved"] == [expected_boundary]
    elif entry.uri in BUSINESS_STATE_VERIFIED_APIS:
        assert verification.status == "verified"
        assert verification.business_state_verified is True
        assert verification.verification_strength == "operation_specific_readback"
        assert verification.readbacks
        assert verification.message == (
            "The WAAPI result schema and operation-specific business-state readbacks passed."
        )
    else:
        assert verification.status == "result_schema_checked"
        assert verification.business_state_verified is False
        assert verification.verification_strength == (
            "partial_reflected_schema"
            if result_validation.unresolved_refs
            else "complete_reflected_schema"
        )
        assert verification.message == (
            "The returned WAAPI payload matches the packaged reflected result schema."
        )


def test_program_matrix_is_the_exact_808_row_contract() -> None:
    expected = {
        (entry.version, entry.item_type, entry.uri)
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for entry in ExecutionContractRegistry().executable_entries(version)
    }
    actual = {(entry.version, entry.item_type, entry.uri) for entry in PROGRAM_ROWS}

    assert actual == expected
    assert len(actual) == 808
