from __future__ import annotations

from tests.support.gateway_config import set_gateway_config

import importlib.util
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.operation_drafts import OperationDraftStore
from wwise_waapi.operation_registry import operation_request_schema_digest
from wwise_waapi.transactions import TransactionStore


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_soundbank_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
BANK_ID = "{11111111-1111-1111-1111-111111111111}"
OBJECT_ID = "{22222222-2222-2222-2222-222222222222}"
OPERATIONS = {
    "soundbank.generate": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "soundbank.setInclusions": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "soundbank.convertExternalSources": ("2022.1", "2023.1", "2024.1", "2025.1"),
    "soundbank.processDefinitionFiles": ("2022.1", "2023.1", "2024.1", "2025.1"),
}


class FakeClient:
    def __init__(self, responses: Mapping[str, Sequence[Any]]) -> None:
        self.responses = {
            uri: deque(values) for uri, values in responses.items()
        }
        self.calls: list[tuple[str, Any, Any]] = []

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        self.calls.append((uri, args, options))
        values = self.responses.get(uri)
        if not values:
            raise AssertionError(f"Unexpected WAAPI call: {uri} {args!r} {options!r}")
        return values.popleft()

    def disconnect(self) -> None:
        return None


class InclusionCheckClient:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri == "ak.wwise.core.getInfo":
            return _info()
        if uri == "ak.wwise.core.getProjectInfo":
            return _project(self.tmp_path)
        if uri == "ak.wwise.core.object.get":
            requested_ids = (
                args.get("from", {}).get("id", [BANK_ID])
                if isinstance(args, Mapping)
                else [BANK_ID]
            )
            rows = []
            for requested_id in requested_ids:
                if str(requested_id).upper() == OBJECT_ID:
                    rows.append(
                        {
                            "id": OBJECT_ID,
                            "name": "Play_Harbor",
                            "type": "Event",
                            "path": r"\Events\Default Work Unit\Play_Harbor",
                            "parent": {
                                "id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}"
                            },
                            "notes": "",
                        }
                    )
                else:
                    rows.append(
                        {
                        "id": BANK_ID,
                        "name": "Harbor",
                        "type": "SoundBank",
                        "path": r"\SoundBanks\Default Work Unit\Harbor",
                        "parent": {
                            "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"
                        },
                        "notes": "",
                    }
                    )
            return {"return": rows}
        if uri == "ak.wwise.core.soundbank.getInclusions":
            return {"inclusions": []}
        raise AssertionError(f"Unexpected WAAPI call: {uri} {args!r} {options!r}")

    def disconnect(self) -> None:
        return None


def _env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": "2025.1",
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": "2025.1",
    }


def _info() -> dict[str, Any]:
    return {
        "displayName": "Wwise",
        "isCommandLine": True,
        "sessionId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        "processId": 4242,
        "processPath": "/Applications/Wwise/WwiseConsole",
        "apiVersion": 1,
        "platform": "macosx",
        "configuration": "release",
        "version": {
            "year": 2025,
            "major": 1,
            "minor": 0,
            "build": 1,
            "displayName": "v2025.1.0.1",
        },
    }


def _project(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / "project" / "SampleProject.wproj"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<Project />\n", encoding="utf-8")
    return {"id": PROJECT_ID, "name": "SampleProject", "path": str(path)}


def _offline(tmp_path: Path, *argv: str) -> tuple[int, dict[str, Any]]:
    return gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *argv],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline command connected to {url}"),
    )


def _declare_plan(
    tmp_path: Path,
    *argv: str,
) -> tuple[int, dict[str, Any]]:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        }
    )
    return gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *argv],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )


def _bind(
    tmp_path: Path,
    *,
    draft_id: str,
    authority: str,
    revision: int,
    object_id: str,
    name: str,
    object_type: str,
    path: str,
    role: str,
) -> dict[str, Any]:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": object_id,
                            "name": name,
                            "type": object_type,
                            "path": path,
                        }
                    ]
                }
            ],
        }
    )
    code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--object-id",
            object_id,
            "--role",
            role,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, payload
    return payload


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation, versions in OPERATIONS.items()
        for version in versions
    ],
)
def test_every_soundbank_schema_exposes_only_the_business_plan(
    tmp_path: Path,
    operation: str,
    version: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=set_gateway_config(_env(tmp_path), wwise_version=version),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )

    assert code == 0, payload
    assert payload["operation"]["input_mode"] == "business_declaration"
    assert payload["business_adapter"]["declaration"]["subcommand"] == (
        "draft-declare-soundbank-plan"
    )
    assert payload["business_adapter"]["legacy_composer_public"] is False
    assert payload["business_adapter"]["legacy_inline_typed_public"] is False
    assert "composer" not in payload
    assert "typed_operation" not in payload


def test_definition_2021_retains_the_actual_native_api_boundary(tmp_path: Path) -> None:
    """The documented query alternative does not emulate a missing function."""
    env = set_gateway_config(_env(tmp_path), wwise_version="2021.1")
    code, result = gateway.execute_gateway(["draft-start", "soundbank.processDefinitionFiles"], env=env,
        client_factory=lambda _: pytest.fail("unavailable Definition operation connected"))
    assert code == 2 and result["error_code"] == "UNAVAILABLE_IN_VERSION", result


@pytest.mark.parametrize(
    "operation",
    ("soundbank.generate", "soundbank.processDefinitionFiles"),
)
def test_shallow_soundbank_input_commands_are_rejected_without_state_change(
    tmp_path: Path,
    operation: str,
) -> None:
    code, started = _offline(tmp_path, "draft-start", operation)
    assert code == 0, started
    store = OperationDraftStore(tmp_path / "state")
    before = store.inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )

    if operation == "soundbank.generate":
        code, rejected = _offline(
            tmp_path,
            "draft-apply",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--facts",
            "--action",
            "add_typed_fact",
            "--fact-action",
            "present",
            "--field-handle",
            "trh1-" + "0" * 24,
        )
    else:
        with pytest.raises(SystemExit) as removed:
            gateway.execute_gateway(
                [
                    "typed-operation",
                    operation,
                    "--schema-digest",
                    operation_request_schema_digest(operation, "2025.1"),
                    "--apply",
                    "--file",
                    str(tmp_path / "Harbor.tsv"),
                    "--io-root",
                    str(tmp_path),
                ],
                env=_env(tmp_path),
                client_factory=lambda url: pytest.fail(
                    f"retired typed operation connected to {url}"
                ),
            )
        assert removed.value.code == 2
        code, rejected = 2, {"removed_from_parser": True}

    assert code == 2, rejected
    after = store.inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )
    assert after.revision == before.revision == 1
    assert after.composition == before.composition


def test_definition_file_plan_is_one_complete_offline_business_declaration(
    tmp_path: Path,
) -> None:
    definition = tmp_path / "Harbor.tsv"
    definition.write_text('Harbor\t"Play_Harbor"\tEvent\n', encoding="utf-8")
    io_root = tmp_path / "io"
    io_root.mkdir()
    code, started = _offline(
        tmp_path,
        "draft-start",
        "soundbank.processDefinitionFiles",
    )
    assert code == 0, started
    binding = started["draft"]["next_action_binding"]
    assert binding["required_next_phase"] == "declare_complete_soundbank_plan"
    assert "draft-declare-soundbank-plan" in binding["declaration"][
        "fixed_argv_prefix"
    ]
    assert binding["declaration"]["fixed_argv_prefix_copy_instruction"][
        "action"
    ] == "copy_verbatim_then_append_one_complete_soundbank_business_plan"

    code, declared = _declare_plan(
        tmp_path,
        "draft-declare-soundbank-plan",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--definition-file",
        str(definition),
        "--io-root",
        str(io_root),
    )
    assert code == 0, declared
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_business_declaration"
    )

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
        expected_revision=2,
        schema_digest=gateway.operation_draft_schema_digest(
            "soundbank.processDefinitionFiles",
            "2025.1",
        ),
        composer_digest=operation_composer_digest(
            "soundbank.processDefinitionFiles",
            "2025.1",
        ),
    )
    assert materialized.request["arguments"] == {
        "files": [str(definition)],
        "io_root": str(io_root),
    }


def test_set_inclusions_binds_objects_then_declares_only_business_rows(
    tmp_path: Path,
) -> None:
    code, started = _offline(
        tmp_path,
        "draft-start",
        "soundbank.setInclusions",
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    assert "composer" not in started
    assert "typed_operation" not in started

    bank = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=1,
        object_id=BANK_ID,
        name="Harbor",
        object_type="SoundBank",
        path=r"\SoundBanks\Default Work Unit\Harbor",
        role="soundbank",
    )
    inclusion = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=2,
        object_id=OBJECT_ID,
        name="Harbor_Ambience",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Harbor_Ambience",
        role="inclusion_object",
    )
    code, declared = _declare_plan(
        tmp_path,
        "draft-declare-soundbank-plan",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--mode",
        "replace",
        "--soundbank-handle",
        bank["bound_object"]["handle"],
        "--inclusion",
        inclusion["bound_object"]["handle"],
        "events",
        "media",
    )
    assert code == 0, declared

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=4,
        schema_digest=gateway.operation_draft_schema_digest(
            "soundbank.setInclusions",
            "2025.1",
        ),
        composer_digest=operation_composer_digest(
            "soundbank.setInclusions",
            "2025.1",
        ),
    )
    assert materialized.request["arguments"] == {
        "soundbank": {"kind": "id", "value": BANK_ID},
        "mode": "replace",
        "inclusions": [
            {
                "object": {"kind": "id", "value": OBJECT_ID},
                "filters": ["events", "media"],
            }
        ],
    }


def test_set_inclusions_rejects_handles_bound_for_the_wrong_business_roles(
    tmp_path: Path,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "soundbank.setInclusions")
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    bank = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=1,
        object_id=BANK_ID,
        name="Harbor",
        object_type="SoundBank",
        path=r"\SoundBanks\Default Work Unit\Harbor",
        role="inclusion_object",
    )
    inclusion = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=2,
        object_id=OBJECT_ID,
        name="Harbor_Ambience",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Harbor_Ambience",
        role="soundbank",
    )

    code, rejected = _declare_plan(
        tmp_path,
        "draft-declare-soundbank-plan",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--mode",
        "replace",
        "--soundbank-handle",
        bank["bound_object"]["handle"],
        "--inclusion",
        inclusion["bound_object"]["handle"],
        "events",
    )

    assert code == 2, rejected
    assert rejected["error_code"] == "BOUND_OBJECT_ROLE_MISMATCH"


def test_soundbank_draft_derives_type_for_one_exact_name_without_a_separate_query(
    tmp_path: Path,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "soundbank.generate")
    assert code == 0, started
    next_action = started["draft"]["next_action_binding"]
    assert next_action["declaration"]["optional_field_policy"] == {
        "append_only_when": "explicitly_present_in_user_request",
        "unspecified": "omit",
        "infer_defaults": False,
    }
    assert next_action["declaration"]["append"][-1] == (
        "--io-root <exact-caller-owned-authority-root-containing-project-cache-"
        "and-all-generated-output-not-the-final-output-directory>"
    )
    binding = next_action["object_binding"]
    assert binding["direct_query_before_binding"] == "forbidden"
    exact_name = binding["role_routes"]["soundbank"]["by_exact_name"]
    assert exact_name["fixed_argv_prefix"][-2:] == [
        "--exact-type-name",
        "SoundBank",
    ]
    assert exact_name["append"] == ["<exact-object-name>"]
    assert "<exact-wwise-type>" not in json.dumps(binding)
    assert binding["role_routes"]["soundbank"]["fixed_role"] == "soundbank"
    assert binding["role_routes"]["event"]["fixed_role"] == "event"
    assert binding["role_routes"]["aux_bus"]["fixed_role"] == "aux_bus"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": BANK_ID,
                            "name": "Harbor",
                            "type": "SoundBank",
                            "path": r"\SoundBanks\Default Work Unit\Harbor",
                        }
                    ]
                }
            ],
        }
    )
    code, bound = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-object",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--role",
            "soundbank",
            "--exact-type-name",
            "SoundBank",
            "Harbor",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, bound
    assert bound["bound_object"]["handle"].startswith("boh1-")
    assert bound["bound_object"]["business_kind"] == "soundbank"
    assert bound["bound_object"]["business_kind_resolution"] == {
        "status": "resolved",
        "candidates": [],
        "reflected_type": "SoundBank",
        "source": "closed_role_exact_type_selector",
    }
    object_calls = [
        call for call in client.calls if call[0] == "ak.wwise.core.object.get"
    ]
    assert object_calls == [
        (
            "ak.wwise.core.object.get",
            {"waql": 'from type SoundBank where name = "Harbor" take 2'},
            {"return": ["id", "name", "type", "path"]},
        )
    ]


def test_generate_plan_binds_business_objects_and_derives_native_switches(
    tmp_path: Path,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "soundbank.generate")
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    bank = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=1,
        object_id=BANK_ID,
        name="Harbor",
        object_type="SoundBank",
        path=r"\SoundBanks\Default Work Unit\Harbor",
        role="soundbank",
    )
    event = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=2,
        object_id=OBJECT_ID,
        name="Play_Harbor",
        object_type="Event",
        path=r"\Events\Default Work Unit\Play_Harbor",
        role="event",
    )
    aux_id = "{33333333-3333-3333-3333-333333333333}"
    aux = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=3,
        object_id=aux_id,
        name="Harbor_Reverb",
        object_type="AuxBus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Harbor_Reverb",
        role="aux_bus",
    )
    io_root = tmp_path / "io"
    io_root.mkdir()

    code, declared = _declare_plan(
        tmp_path,
        "draft-declare-soundbank-plan",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--soundbank",
        bank["bound_object"]["handle"],
        "localized",
        "--event",
        bank["bound_object"]["handle"],
        event["bound_object"]["handle"],
        "--aux-bus",
        bank["bound_object"]["handle"],
        aux["bound_object"]["handle"],
        "--generation-inclusion",
        bank["bound_object"]["handle"],
        "events",
        "media",
        "--soundbank-rebuild",
        bank["bound_object"]["handle"],
        "true",
        "--platform",
        "Windows",
        "--language",
        "English(US)",
        "--clear-audio-file-cache",
        "true",
        "--io-root",
        str(io_root),
    )
    assert code == 0, declared

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=5,
        schema_digest=gateway.operation_draft_schema_digest(
            "soundbank.generate",
            "2025.1",
        ),
        composer_digest=operation_composer_digest(
            "soundbank.generate",
            "2025.1",
        ),
    )
    assert materialized.request["arguments"] == {
        "soundbanks": [
            {
                "name": "Harbor",
                "artifact_expectation": "localized",
                "events": [{"kind": "id", "value": OBJECT_ID}],
                "aux_busses": [{"kind": "id", "value": aux_id}],
                "inclusions": ["event", "media"],
                "rebuild": True,
            }
        ],
        "platforms": ["Windows"],
        "languages": ["English(US)"],
        "skip_languages": False,
        "write_to_disk": True,
        "clear_audio_file_cache": True,
        "io_root": str(io_root),
    }


def test_external_source_plan_keeps_exact_artifacts_inside_business_envelope(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Harbor.wsources"
    source.write_text("<ExternalSourcesList SchemaVersion=\"1\" />\n", encoding="utf-8")
    io_root = tmp_path / "io"
    output = io_root / "Windows"
    output.mkdir(parents=True)
    code, started = _offline(
        tmp_path,
        "draft-start",
        "soundbank.convertExternalSources",
    )
    assert code == 0, started

    code, declared = _declare_plan(
        tmp_path,
        "draft-declare-soundbank-plan",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--source",
        str(source),
        "Windows",
        str(output),
        "--io-root",
        str(io_root),
    )
    assert code == 0, declared

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
        expected_revision=2,
        schema_digest=gateway.operation_draft_schema_digest(
            "soundbank.convertExternalSources",
            "2025.1",
        ),
        composer_digest=operation_composer_digest(
            "soundbank.convertExternalSources",
            "2025.1",
        ),
    )
    assert materialized.request["arguments"] == {
        "sources": [
            {
                "input": str(source),
                "platform": "Windows",
                "output": str(output),
            }
        ],
        "io_root": str(io_root),
    }


def test_invalid_complete_soundbank_plan_is_rejected_atomically(
    tmp_path: Path,
) -> None:
    code, started = _offline(
        tmp_path,
        "draft-start",
        "soundbank.convertExternalSources",
    )
    assert code == 0, started
    store = OperationDraftStore(tmp_path / "state")
    before = store.inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )

    code, rejected = _declare_plan(
        tmp_path,
        "draft-declare-soundbank-plan",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--source",
        str(tmp_path / "Harbor.wsources"),
        "Windows",
        str(tmp_path / "io"),
    )

    assert code == 2, rejected
    assert rejected["error_code"] == "BUSINESS_VALUE_INVALID"
    after = store.inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )
    assert after.revision == before.revision == 1
    assert after.composition == before.composition


def test_generate_plan_preserves_every_explicit_false_rebuild_choice(
    tmp_path: Path,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "soundbank.generate")
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    bank = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=1,
        object_id=BANK_ID,
        name="Harbor",
        object_type="SoundBank",
        path=r"\SoundBanks\Default Work Unit\Harbor",
        role="soundbank",
    )
    io_root = tmp_path / "io"
    io_root.mkdir()

    code, declared = _declare_plan(
        tmp_path,
        "draft-declare-soundbank-plan",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--soundbank",
        bank["bound_object"]["handle"],
        "nonlocalized",
        "--soundbank-rebuild",
        bank["bound_object"]["handle"],
        "false",
        "--platform",
        "Windows",
        "--rebuild-soundbanks",
        "false",
        "--clear-audio-file-cache",
        "false",
        "--rebuild-init-bank",
        "false",
        "--io-root",
        str(io_root),
    )
    assert code == 0, declared

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=3,
        schema_digest=gateway.operation_draft_schema_digest(
            "soundbank.generate",
            "2025.1",
        ),
        composer_digest=operation_composer_digest(
            "soundbank.generate",
            "2025.1",
        ),
    )
    assert materialized.request["arguments"] == {
        "soundbanks": [
            {
                "name": "Harbor",
                "artifact_expectation": "nonlocalized",
                "rebuild": False,
            }
        ],
        "platforms": ["Windows"],
        "skip_languages": True,
        "write_to_disk": True,
        "rebuild_soundbanks": False,
        "clear_audio_file_cache": False,
        "rebuild_init_bank": False,
        "io_root": str(io_root),
    }


@pytest.mark.parametrize(
    "legacy_flag",
    ("--rebuild-soundbank", "--no-rebuild-soundbank", "--no-rebuild-soundbanks"),
)
def test_removed_mutually_exclusive_rebuild_flags_are_not_public(
    legacy_flag: str,
) -> None:
    with pytest.raises(SystemExit):
        gateway.build_parser().parse_args(
            [
                "draft-declare-soundbank-plan",
                "od1-placeholder",
                legacy_flag,
                "boh1-placeholder",
            ]
        )


def test_business_inclusion_plan_checks_and_seals_one_immutable_preview(
    tmp_path: Path,
) -> None:
    code, started = _offline(
        tmp_path,
        "draft-start",
        "soundbank.setInclusions",
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    bank = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=1,
        object_id=BANK_ID,
        name="Harbor",
        object_type="SoundBank",
        path=r"\SoundBanks\Default Work Unit\Harbor",
        role="soundbank",
    )
    inclusion = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=2,
        object_id=OBJECT_ID,
        name="Play_Harbor",
        object_type="Event",
        path=r"\Events\Default Work Unit\Play_Harbor",
        role="inclusion_object",
    )
    assert inclusion["bound_object"]["business_kind"] == "event"
    assert inclusion["bound_object"]["business_kind_resolution"] == {
        "status": "resolved",
        "candidates": [],
        "reflected_type": "Event",
        "source": "stable_live_type",
    }
    code, declared = _declare_plan(
        tmp_path,
        "draft-declare-soundbank-plan",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--mode",
        "replace",
        "--soundbank-handle",
        bank["bound_object"]["handle"],
        "--inclusion",
        inclusion["bound_object"]["handle"],
        "events",
    )
    assert code == 0, declared
    expected = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=4,
        schema_digest=gateway.operation_draft_schema_digest(
            "soundbank.setInclusions",
            "2025.1",
        ),
        composer_digest=operation_composer_digest(
            "soundbank.setInclusions",
            "2025.1",
        ),
    ).request

    check_code, checked = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "4",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: InclusionCheckClient(tmp_path),
    )
    assert check_code == 0, checked

    preview_code, previewed = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked["draft"]["revision"]),
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: InclusionCheckClient(tmp_path),
    )
    assert preview_code == 0, previewed
    assert previewed["agent_result"]["request"] == expected
    stored = TransactionStore(tmp_path / "state").load_preview(
        previewed["transaction_id"]
    )
    assert stored.artifact["request"] == expected


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("object_type,directive,native_code", [("DialogueEvent", "-DialogueEvent\t", None),
    ("Event", "", 10), ("Effect", "-EffectShareset\t", 17), ("AuxBus", "-AuxBus\t", 20)])
@pytest.mark.parametrize("readback,error", [("unique", None), ("wrong-type", "INVALID_TARGET_TYPE"),
    ("wrong-short-id", "IDENTITY_MISMATCH"), ("bool", "IDENTITY_MISMATCH"), ("string", "IDENTITY_MISMATCH"),
    ("missing-short-id", "IDENTITY_MISMATCH"), ("malformed-guid", "IDENTITY_MISMATCH"),
    ("empty", "AMBIGUOUS_IDENTITY"), ("duplicate", "AMBIGUOUS_IDENTITY"), ("collision", "AMBIGUOUS_IDENTITY")])
def test_definition_short_id_draft_checks_and_seals_unique_guid(tmp_path: Path, version: str, object_type: str,
    directive: str, native_code: int | None, readback: str, error: str | None, number: int = 123) -> None:
    """The public Definition lifecycle admits documented DialogueEvent IDs."""
    project = _project(tmp_path)
    project_root = Path(project["path"]).parent
    language_id = "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"
    platform_id = "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}"
    project.update({"isDirty": False, "displayTitle": "SampleProject - Wwise",
        "currentLanguageId": language_id, "referenceLanguageId": language_id,
        "languages": [{"id": language_id, "name": "English(US)", "shortId": 1}],
        "currentPlatformId": platform_id, "platforms": [{"id": platform_id, "name": "Mac", "baseName": "Mac",
            "baseDisplayName": "Mac", "soundBankPath": str(project_root / "GeneratedSoundBanks/Mac"),
            "copiedMediaPath": str(project_root / "GeneratedSoundBanks/Mac/Media")}],
        "defaultConversion": {"id": "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}", "name": "PCM"},
        "directories": {"root": str(project_root),
        "cache": str(project_root / ".cache"), "originals": str(project_root / "Originals"),
        "soundBankOutputRoot": str(project_root / "GeneratedSoundBanks"),
        "commands": str(project_root / "Commands"), "properties": str(project_root)}})
    definition = project_root / "Dialogue.tsv"
    number = 1 if readback == "bool" else number
    filters = "Event\tMedia" if object_type in {"Event", "DialogueEvent"} else "Structure\tMedia"
    definition.write_text(f"Harbor\t{directive}{number}\t{filters}\n", encoding="utf-8")
    event = {"id": OBJECT_ID, "name": "Target", "type": object_type, "path": r"\Objects\Target", "shortId": number}
    if readback == "wrong-type":
        event["type"] = "Sound"
    elif readback in {"wrong-short-id", "bool", "string", "missing-short-id"}:
        event["shortId"] = {"wrong-short-id": number ^ 1, "bool": True, "string": str(number), "missing-short-id": None}[readback]
    elif readback == "malformed-guid":
        event["id"] = "unbound"
    rows = [] if readback == "empty" else [event]
    if readback in {"duplicate", "collision"}:
        rows.append({**event, "id": OBJECT_ID if readback == "duplicate" else BANK_ID})
    literal = f"{number}.0" if version in {"2022.1", "2023.1"} else str(number)
    lookup = ({"waql": f"from type {object_type} where shortId = {literal} take 2"} if native_code is None else
              {"from": {"id": [{"shortId": number, "type": native_code}]}, "transform": [{"range": [0, 2]}]})
    calls = []
    class Client:
        def call(self, uri, args=None, options=None):
            calls.append((uri, args, options))
            if uri == "ak.wwise.core.getInfo":
                info = _info()
                info["version"].update(year=int(version[:4]), displayName=f"v{version}.0.1")
                return info
            if uri == "ak.wwise.core.getProjectInfo":
                return project
            if uri == "ak.wwise.core.object.get":
                if args == lookup:
                    return {"return": rows}
                if args.get("from", {}).get("id") == [OBJECT_ID]:
                    return {"return": [event]}
                return {"return": []}
            raise AssertionError((uri, args, options))
        def disconnect(self):
            pass
    client = Client()
    env = set_gateway_config(_env(tmp_path), wwise_version=version)
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), *argv], env=env, client_factory=lambda _: client)
    code, started = run("draft-start", "soundbank.processDefinitionFiles")
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    code, declared = run("draft-declare-soundbank-plan", draft_id, "--task-authority", authority,
        "--expected-revision", "1", "--definition-file", str(definition), "--io-root", str(tmp_path))
    assert code == 0, declared
    code, checked = run("draft-check", draft_id, "--task-authority", authority, "--expected-revision", str(declared["draft"]["revision"]))
    assert ("ak.wwise.core.object.get", lookup,
            {"return": ["id", "name", "type", "path", "parent", "notes", "shortId"]}) in calls
    if error:
        assert code == 2 and checked["error_code"] == error, checked
        assert not any(uri == "ak.wwise.core.soundbank.processDefinitionFiles" for uri, _, _ in calls)
        assert not list((tmp_path / "state" / "transactions").glob("*.json"))
        return
    assert code == 0, checked
    code, previewed = run("preview-from-draft", draft_id, "--task-authority", authority,
        "--expected-revision", str(checked["draft"]["revision"]))
    assert code == 0, previewed
    stored = TransactionStore(tmp_path / "state").load_preview(previewed["transaction_id"])
    prepared = stored.artifact["prepared_operation"]
    role = prepared["resolved_roles"]["definition.bank[0].inclusion[0]"]
    assert role["object"] == OBJECT_ID and role["row"]["shortId"] == number and type(role["row"]["shortId"]) is int
    assert not any(uri == "ak.wwise.core.soundbank.processDefinitionFiles" for uri, _, _ in calls)


@pytest.mark.parametrize("version,number,readback,error", [
    (version, number, "unique", None) for version in ["2022.1", "2023.1", "2024.1", "2025.1"]
    for number in [0, 2147483647, 2147483648, 3970659059, 4294967295]
] + [("2023.1", 3970659059, readback, error) for readback, error in [
    ("wrong-type", "INVALID_TARGET_TYPE"), ("wrong-short-id", "IDENTITY_MISMATCH"),
    ("bool", "IDENTITY_MISMATCH"), ("string", "IDENTITY_MISMATCH"), ("missing-short-id", "IDENTITY_MISMATCH"),
    ("malformed-guid", "IDENTITY_MISMATCH"), ("empty", "AMBIGUOUS_IDENTITY"),
    ("duplicate", "AMBIGUOUS_IDENTITY"), ("collision", "AMBIGUOUS_IDENTITY")]])
def test_definition_dialogue_short_id_decimal_boundary_and_counterexamples(tmp_path: Path, version: str,
    number: int, readback: str, error: str | None) -> None:
    test_definition_short_id_draft_checks_and_seals_unique_guid(tmp_path, version, "DialogueEvent", "-DialogueEvent\t", None,
        readback, error, number=number)


def test_generate_temporary_bank_preserves_memory_and_language_choices(tmp_path: Path) -> None:
    code, started = _offline(tmp_path, "draft-start", "soundbank.generate")
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    event = _bind(tmp_path, draft_id=draft_id, authority=authority, revision=1,
        object_id=OBJECT_ID, name="Play_Harbor", object_type="Event",
        path=r"\Events\Default Work Unit\Play_Harbor", role="event")
    code, declared = _declare_plan(tmp_path, "draft-declare-soundbank-plan", draft_id,
        "--task-authority", authority, "--expected-revision", "2",
        "--temporary-soundbank", "Harbor_Temporary", "nonlocalized",
        "--event", "Harbor_Temporary", event["bound_object"]["handle"],
        "--platform", "Windows", "--write-to-disk", "false",
        "--skip-languages", "false", "--language", "English(US)",
        "--io-root", str(tmp_path))
    assert code == 0, declared
    request = OperationDraftStore(tmp_path / "state").materialize_request(draft_id,
        task_authority=authority, expected_revision=3,
        schema_digest=gateway.operation_draft_schema_digest("soundbank.generate", "2025.1"),
        composer_digest=operation_composer_digest("soundbank.generate", "2025.1")).request
    assert request["arguments"] == {"soundbanks": [{"name": "Harbor_Temporary",
        "artifact_expectation": "nonlocalized", "temporary": True, "events": [{"kind": "id", "value": OBJECT_ID}]}],
        "platforms": ["Windows"], "write_to_disk": False, "skip_languages": False,
        "languages": ["English(US)"], "io_root": str(tmp_path)}


@pytest.mark.parametrize("selection", ["all", "temporary"])
def test_generation_business_choice_reaches_immutable_preview_and_truthful_verifier(tmp_path: Path, selection: str) -> None:
    from tests.unit.test_operation_registry_soundbank import _project as generation_project, GenerateReader, _row
    from wwise_waapi.operation_registry import verify_prepared_operation
    io_root, project = generation_project(tmp_path)
    bank = _row(BANK_ID, "Harbor", "SoundBank", r"\SoundBanks\Default Work Unit\Harbor")
    class Client:
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info()
            if uri == "ak.wwise.core.object.get" and args.get("waql") == "from type SoundBank take 65":
                return {"return": [bank]}
            return GenerateReader(project)(uri, args, options)
        def disconnect(self):
            pass
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), *argv],
            env=_env(tmp_path), client_factory=lambda _url: Client())
    code, started = run("draft-start", "soundbank.generate")
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    choice = ["--all-user-soundbanks", "nonlocalized"] if selection == "all" else ["--temporary-soundbank", "New_Bank", "nonlocalized"]
    code, declared = run("draft-declare-soundbank-plan", draft_id, "--task-authority", authority,
        "--expected-revision", "1", *choice, "--platform", "Mac", "--io-root", str(io_root),
        "--write-to-disk", "native-default", "--skip-languages", "native-default")
    assert code == 0, declared
    code, checked = run("draft-check", draft_id, "--task-authority", authority, "--expected-revision", "2")
    assert code == 0, checked
    code, previewed = run("preview-from-draft", draft_id, "--task-authority", authority,
        "--expected-revision", str(checked["draft"]["revision"]))
    assert code == 0, previewed
    stored = TransactionStore(tmp_path / "state").load_preview(previewed["transaction_id"])
    prepared = stored.artifact["prepared_operation"]
    assert "business_state_requires_artifacts" in json.dumps(previewed)
    assert "writeToDisk" not in prepared["dispatch"]["args"]
    assert "skipLanguages" not in prepared["dispatch"]["args"]
    assert prepared["dispatch"]["args"]["soundbanks"] == ([] if selection == "all" else [{"name": "New_Bank"}])
    verified = verify_prepared_operation(prepared, execution_result={"result": {}}, read_call=Client().call)
    assert verified.ok and verified.business_state_verified is False
    assert verified.status == "result_schema_checked"


def test_generate_explicit_empty_definition_and_language_choices_remain_selectable(tmp_path: Path) -> None:
    code, started = _offline(tmp_path, "draft-start", "soundbank.generate")
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    code, declared = _declare_plan(tmp_path, "draft-declare-soundbank-plan", draft_id,
        "--task-authority", authority, "--expected-revision", "1",
        "--temporary-soundbank", "Empty_Bank", "nonlocalized",
        "--empty-events", "Empty_Bank", "--empty-aux-busses", "Empty_Bank",
        "--empty-generation-inclusions", "Empty_Bank", "--all-languages",
        "--skip-languages", "false", "--platform", "Windows", "--io-root", str(tmp_path))
    assert code == 0, declared
    request = OperationDraftStore(tmp_path / "state").materialize_request(draft_id,
        task_authority=authority, expected_revision=2,
        schema_digest=gateway.operation_draft_schema_digest("soundbank.generate", "2025.1"),
        composer_digest=operation_composer_digest("soundbank.generate", "2025.1")).request
    assert request["arguments"]["soundbanks"] == [{"name": "Empty_Bank", "temporary": True,
        "artifact_expectation": "nonlocalized", "events": [], "aux_busses": [], "inclusions": []}]
    assert request["arguments"]["languages"] == []
    assert request["arguments"]["write_to_disk"] is True


@pytest.mark.parametrize("foreign_bank", [False, True])
def test_all_user_generation_supports_bound_bank_layout_overrides(tmp_path: Path, foreign_bank: bool) -> None:
    from tests.unit.test_operation_registry_soundbank import _project as generation_project, GenerateReader, _row
    from wwise_waapi.operation_registry import verify_prepared_operation, validate_prepared_roles
    io_root, project = generation_project(tmp_path)
    root_bank = _row(BANK_ID, "Harbor", "SoundBank", r"\SoundBanks\Default Work Unit\Harbor")
    voice_bank = _row(OBJECT_ID, "Dialogue", "SoundBank", r"\SoundBanks\Default Work Unit\Dialogue")
    class Client:
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info()
            if uri == "ak.wwise.core.object.get":
                if args.get("waql") == "from type SoundBank take 65":
                    return {"return": [root_bank] if foreign_bank else [root_bank, voice_bank]}
                if args.get("from", {}).get("id") == [OBJECT_ID]:
                    return {"return": [voice_bank]}
            return GenerateReader(project)(uri, args, options)
        def disconnect(self):
            pass
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), *argv],
            env=_env(tmp_path), client_factory=lambda _url: Client())
    code, started = run("draft-start", "soundbank.generate")
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    code, bound = run("draft-bind-object", draft_id, "--task-authority", authority,
        "--expected-revision", "1", "--object-id", OBJECT_ID, "--role", "soundbank")
    assert code == 0, bound
    code, invalid = run("draft-declare-soundbank-plan", draft_id, "--task-authority", authority,
        "--expected-revision", "2", "--all-user-soundbanks", "nonlocalized",
        "--soundbank-rebuild", bound["bound_object"]["handle"], "true",
        "--platform", "Mac", "--io-root", str(io_root))
    assert code == 2, invalid
    code, declared = run("draft-declare-soundbank-plan", draft_id, "--task-authority", authority,
        "--expected-revision", "2", "--all-user-soundbanks", "nonlocalized",
        "--all-user-bank-expectation", bound["bound_object"]["handle"], "localized",
        "--platform", "Mac", "--io-root", str(io_root))
    assert code == 0, declared
    code, checked = run("draft-check", draft_id, "--task-authority", authority, "--expected-revision", "3")
    if foreign_bank:
        assert code == 2 and checked["error_code"] == "INVALID_SCOPE", checked
        return
    assert code == 0, checked
    code, previewed = run("preview-from-draft", draft_id, "--task-authority", authority,
        "--expected-revision", str(checked["draft"]["revision"]))
    assert code == 0, previewed
    prepared = TransactionStore(tmp_path / "state").load_preview(previewed["transaction_id"]).artifact["prepared_operation"]
    assert validate_prepared_roles(prepared, read_call=Client().call)["ok"] is True
    assert prepared["dispatch"]["args"]["soundbanks"] == []
    assert prepared["dispatch"]["args"]["skipLanguages"] is False
    assert "all_user_bank_expectations" not in prepared["dispatch"]["args"]
    assert prepared["verification_plan"]["plan"]["scope"]["artifact_expectations"] == [
        {"name": "Harbor", "mode": "nonlocalized"}, {"name": "Dialogue", "mode": "localized"}]
    output = Path(project["platforms"][0]["soundBankPath"])
    output.mkdir(parents=True)
    (output / "Harbor.bnk").write_bytes(b"BKHD-Harbor")
    assert not verify_prepared_operation(prepared, execution_result={"result": {}}, read_call=Client().call).ok
    (output / "English(US)").mkdir()
    (output / "English(US)" / "Dialogue.bnk").write_bytes(b"BKHD-Dialogue")
    assert verify_prepared_operation(prepared, execution_result={"result": {}}, read_call=Client().call).ok
@pytest.mark.parametrize("version,fault", [(v, None) for v in ("2022.1", "2023.1", "2024.1", "2025.1")] +
    [("2025.1", f) for f in ("outside-cache", "missing-cache", "unsafe-base", "cache-drift", "platform-drift", "source-drift", "missing-output", "extra-output")])
def test_external_source_omitted_output_uses_live_custom_cache_and_base_platform(tmp_path, version, fault):
    from tests.unit.test_operation_registry_soundbank import _project as project_fixture
    io_root, project = project_fixture(tmp_path)
    project_root = Path(project["directories"]["root"])
    project["directories"]["cache"] = str(io_root / "custom-cache")
    project["platforms"][0]["name"] = "StudioMac"
    source = project_root / "external.wav"
    source.write_bytes(b"RIFF" + b"0" * 64)
    source_list = project_root / "external.wsources"
    source_list.write_text('<ExternalSourcesList SchemaVersion="1"><Source Path="external.wav" /></ExternalSourcesList>', encoding="utf-8")
    output = io_root / "custom-cache" / "ExternalSources" / "Mac" / "external.wem"
    if fault == "outside-cache":
        project["directories"]["cache"] = str(tmp_path / "unowned-cache")
    elif fault == "missing-cache":
        del project["directories"]["cache"]
    elif fault == "unsafe-base":
        project["platforms"][0]["baseName"] = "../escape"
    calls = []
    class Client:
        def call(self, uri, args=None, options=None):
            calls.append((uri, args, options))
            if uri == "ak.wwise.core.getInfo":
                info = _info()
                info["version"].update(year=int(version[:4]), displayName=f"v{version}.0.1")
                return info
            if uri == "ak.wwise.core.getProjectInfo":
                return project
            if uri == "ak.wwise.core.soundbank.convertExternalSources":
                assert args == {"sources": [{"input": str(source_list), "platform": project["platforms"][0]["id"]}]}
                output.parent.mkdir(parents=True, exist_ok=True)
                if fault != "missing-output":
                    output.write_bytes(b"WEM!" + b"1" * 32)
                if fault == "extra-output":
                    (output.parent / "unplanned.tmp").write_bytes(b"unexpected")
                return {}
            raise AssertionError((uri, args, options))
        def disconnect(self):
            pass
    env = set_gateway_config(_env(tmp_path), wwise_version=version)
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), *argv], env=env, client_factory=lambda _: Client())
    code, started = run("draft-start", "soundbank.convertExternalSources")
    assert code == 0, started
    draft, authority = started["draft"]["draft_id"], started["task_authority"]
    code, declared = run("draft-declare-soundbank-plan", draft, "--task-authority", authority,
        "--expected-revision", "1", "--source", str(source_list), "StudioMac", "--io-root", str(io_root))
    assert code == 0, declared
    code, checked = run("draft-check", draft, "--task-authority", authority, "--expected-revision", str(declared["draft"]["revision"]))
    if fault in {"outside-cache", "missing-cache", "unsafe-base"}:
        assert code == 2, checked
        assert not any(uri.endswith("convertExternalSources") for uri, _, _ in calls)
        return
    assert code == 0, checked
    code, preview = run("preview-from-draft", draft, "--task-authority", authority, "--expected-revision", str(checked["draft"]["revision"]))
    assert code == 0, preview
    prepared = TransactionStore(tmp_path / "state").load_preview(preview["transaction_id"]).artifact["prepared_operation"]
    assert prepared["verification_plan"]["plan"]["requests"][0]["output_root"] == str(output.parent)
    tx = preview["transaction_id"]
    code, shown = run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if fault == "cache-drift":
        project["directories"]["cache"] = str(io_root / "changed-cache")
    elif fault == "platform-drift":
        project["platforms"][0]["baseName"] = "ChangedMac"
    elif fault == "source-drift":
        source.write_bytes(b"changed-source")
    code, executed = run("execute", tx)
    if fault in {"cache-drift", "platform-drift", "source-drift"}:
        assert code == 2 and executed["error_code"] == "ROLE_GUARD_MISMATCH", executed
        assert not any(uri.endswith("convertExternalSources") for uri, _, _ in calls)
        return
    assert code == 0, executed
    code, verified = run("verify", tx)
    if fault in {"missing-output", "extra-output"}:
        assert code == 2, verified
    else:
        assert code == 0, verified
        assert output.is_file()
        assert source.read_bytes() == b"RIFF" + b"0" * 64
    assert sum(uri.endswith("convertExternalSources") for uri, _, _ in calls) == 1
