from __future__ import annotations

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
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
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
        env={**_env(tmp_path), "WWISE_VERSION": version},
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
        "--rebuild-soundbank",
        bank["bound_object"]["handle"],
        "--platform",
        "Windows",
        "--language",
        "English(US)",
        "--clear-audio-file-cache",
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
        "--no-rebuild-soundbank",
        bank["bound_object"]["handle"],
        "--platform",
        "Windows",
        "--no-rebuild-soundbanks",
        "--no-clear-audio-file-cache",
        "--no-rebuild-init-bank",
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
