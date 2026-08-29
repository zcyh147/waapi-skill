from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from pathlib import Path
import pytest

from wwise_waapi.capabilities import CapabilityCatalog
from wwise_waapi.operation_composer import (
    OPERATION_DRAFT_ACTION_CONTRACT,
    apply_composer_action,
    materialize_operation_request,
    new_composition,
    operation_composer_contract,
    parse_typed_action_cli_argument_sequence,
)
from wwise_waapi.operation_registry import operation_uses_business_declaration
from wwise_waapi.platform_commands import encode_windows_model_argv
from wwise_waapi.typed_requests import request_contract


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_generic_typed_draft_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


URI = "ak.soundengine.setPosition"


def test_draft_completion_copy_command_uses_exact_native_shell_spelling() -> None:
    full_argv = [
        "python",
        r"C:\Agent Workspace\.agents\skills\waapi-skill\scripts\run.py",
        "gateway.py",
        "draft-check",
        "od1-0123456789abcdef0123456789abcdef",
        "--task-authority",
        "da1-0123456789abcdef0123456789abcdef01234567",
        "--expected-revision",
        "5",
    ]

    assert gateway.operation_draft_copy_command(
        full_argv,
        platform_name="posix",
    ) == shlex.join(full_argv)
    assert gateway.operation_draft_copy_command(
        full_argv,
        platform_name="nt",
    ) == encode_windows_model_argv(full_argv)


def _env(tmp_path: Path, version: str = "2022.1") -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": version,
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_VERSION": version,
    }


def _action(action: str, **facts: object) -> dict[str, object]:
    return {
        "contract": OPERATION_DRAFT_ACTION_CONTRACT,
        "action": action,
        **facts,
    }


def test_typed_action_batch_parser_preserves_option_looking_business_values() -> None:
    actions = parse_typed_action_cli_argument_sequence(
        [
            "--action",
            "add_typed_fact",
            "--fact-action",
            "set",
            "--field-handle",
            "trh1-000000000000000000000000",
            "--value-type",
            "string",
            "--fact-value",
            "--action",
            "--action",
            "add_typed_fact",
            "--fact-action",
            "set",
            "--field-handle",
            "trh1-111111111111111111111111",
            "--value-type",
            "string",
            "--fact-value",
            "next",
        ]
    )

    assert [action["value"] for action in actions] == ["--action", "next"]


def test_typed_action_batch_parser_accepts_exact_ceiling_and_rejects_next() -> None:
    action_argv = (
        "--action",
        "add_typed_fact",
        "--fact-action",
        "present",
        "--field-handle",
        "trh1-000000000000000000000000",
    )

    assert len(
        parse_typed_action_cli_argument_sequence(action_argv * 6)
    ) == 6
    with pytest.raises(Exception, match="batch|ceiling|invalid"):
        parse_typed_action_cli_argument_sequence(action_argv * 7)


def test_migrated_soundengine_schema_discloses_only_business_draft_entry(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        ["request-schema", URI],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("request-schema must be offline"),
    )

    assert code == 0
    assert payload["input_shape"] == "business_declaration"
    assert payload["continuation"]["subcommand"] == "draft-start"
    assert payload["continuation"]["gateway_argv"] == ["draft-start", URI]
    declaration = payload["business_adapter"]["declaration"]
    assert declaration["required_fields"] == [
        "game_object_handle",
        "position_frame",
    ]
    assert payload["business_adapter"]["legacy_typed_call_public"] is False
    encoded = json.dumps(payload)
    assert "request-json" not in encoded
    assert "action-json" not in encoded
    assert "add_typed_fact" not in encoded


def test_deep_attenuation_curve_rejects_retired_typed_draft_actions(
    tmp_path: Path,
) -> None:
    uri = "ak.wwise.core.object.setAttenuationCurve"
    version = "2025.1"
    state_dir = tmp_path / "state"
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", uri],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    assert start_code == 0
    assert started["draft"]["next_action_binding"]["business_contract"][
        "execution_shape"
    ] == "draft_mutation"

    apply_code, rejected = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir), "draft-apply", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", "1", "--facts",
            "--action", "add_typed_fact", "--fact-action", "present",
            "--field-handle", "retired-typed-handle",
        ],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )
    assert apply_code == 2
    assert "no longer accepts shallow draft-apply" in rejected["message"]


def test_migrated_soundengine_draft_rejects_retired_typed_action_batch(
    tmp_path: Path,
) -> None:
    contract = request_contract("2022.1", URI)
    handles = {".".join(field.path): field.handle for field in contract.fields}
    state_dir = tmp_path / "state"
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", URI],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    assert start_code == 0

    code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-apply",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--compact",
            "--facts",
            "--action",
            "add_typed_fact",
            "--fact-action",
            "set",
            "--field-handle",
            handles["gameObject"],
            "--value-type",
            "integer",
            "--fact-value",
            "7",
            "--action",
            "add_typed_fact",
            "--fact-action",
            "set",
            "--field-handle",
            handles["position.orientationFront.x"],
            "--value-type",
            "number",
            "--fact-value",
            "1",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )

    assert code == 2, payload
    assert payload["error_code"] == "GatewayInputError"
    assert "no longer accepts shallow draft-apply" in payload["message"]
    inspect_code, inspected = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-inspect",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("draft-inspect must be offline"),
    )
    assert inspect_code == 0
    assert inspected["draft"]["revision"] == 1
    assert "current_facts" not in inspected["draft"]


def test_retired_soundengine_typed_action_leaves_identical_draft_bytes(
    tmp_path: Path,
) -> None:
    contract = request_contract("2022.1", URI)
    game_object = next(
        field.handle for field in contract.fields if field.path == ("gameObject",)
    )
    state_dir = tmp_path / "state"
    _start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", URI],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    record_path = next(state_dir.rglob("*.json"))
    before = record_path.read_bytes()

    code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
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
            "set",
            "--field-handle",
            game_object,
            "--value-type",
            "integer",
            "--fact-value",
            "7",
            "--action",
            "add_typed_fact",
            "--fact-action",
            "set",
            "--field-handle",
            "trf1-000000000000000000000000",
            "--value-type",
            "integer",
            "--fact-value",
            "9",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )

    assert code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert record_path.read_bytes() == before


def test_migrated_soundengine_rejects_retired_dynamic_container_disclosure(
    tmp_path: Path,
) -> None:
    uri = "ak.soundengine.setMultiplePositions"
    contract = request_contract("2022.1", uri)
    positions = next(field for field in contract.fields if field.path == ("positions",))

    code, payload = gateway.execute_gateway(
        [
            "request-array-item", uri,
            "--schema-digest", contract.schema_digest,
            "--array-handle", positions.handle,
            "--index", "0",
            "--shape", "object",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("container disclosure must be offline"),
    )

    assert code == 2, payload
    assert payload["error_code"] == "GatewayInputError"
    assert "closed Core business declaration" in payload["message"]


def test_migrated_soundengine_cannot_materialize_shallow_composer_facts() -> None:
    composition = new_composition(URI, "2022.1")
    with pytest.raises(Exception, match="No shallow Operation Composer Adapter"):
        materialize_operation_request(URI, "2022.1", composition)


def test_migrated_soundengine_cannot_add_correct_or_remove_typed_facts() -> None:
    contract = request_contract("2022.1", URI)
    game_object = next(
        field.handle for field in contract.fields if field.path == ("gameObject",)
    )
    for action in (
        _action(
            "add_typed_fact",
            fact_action="set",
            field_handle=game_object,
            value_type="integer",
            value="7",
        ),
        _action("remove_typed_fact", fact_handle="tfh1-" + "0" * 32),
    ):
        with pytest.raises(Exception, match="No shallow Operation Composer Adapter"):
            apply_composer_action(
                URI,
                "2022.1",
                new_composition(URI, "2022.1"),
                action,
            )


def test_migrated_soundengine_has_no_shallow_composer_contract() -> None:
    with pytest.raises(Exception, match="No shallow Operation Composer Adapter"):
        operation_composer_contract(URI, "2025.1")


def test_every_permitted_complex_generic_lane_has_one_draft_adapter() -> None:
    lanes: list[tuple[str, str]] = []
    catalog = CapabilityCatalog()
    for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"):
        for capability in catalog.entries(version):
            if capability.item_type != "function":
                continue
            try:
                typed = request_contract(version, capability.uri)
            except Exception:
                continue
            if typed.as_gateway_payload()["input_shape"] != "draft":
                continue
            if operation_uses_business_declaration(capability.uri, version):
                continue
            lanes.append((version, capability.uri))
            composer = operation_composer_contract(capability.uri, version)
            assert composer["typed_request_schema_digest"] == typed.schema_digest
            assert composer["actions"] == [
                "add_typed_fact",
                "correct_typed_fact",
                "remove_typed_fact",
            ]

    assert lanes == [("2025.1", "ak.wwise.core.mediaPool.get")]


def test_migrated_soundengine_fact_fails_before_it_can_enter_durable_state() -> None:
    contract = request_contract("2022.1", URI)
    game_object = next(
        field.handle for field in contract.fields if field.path == ("gameObject",)
    )
    composition = new_composition(URI, "2022.1")

    with pytest.raises(Exception, match="No shallow Operation Composer Adapter"):
        apply_composer_action(
            URI,
            "2022.1",
            composition,
            _action(
                "add_typed_fact",
                fact_action="set",
                field_handle=game_object,
                value_type="string",
                value="not-an-integer",
            ),
        )

    assert composition == {"contract": "waapi-skill.operation-composition/v1"}


def test_complex_generic_rejects_direct_typed_call_before_connection(
    tmp_path: Path,
) -> None:
    contract = request_contract("2022.1", URI)
    game_object = next(
        field.handle for field in contract.fields if field.path == ("gameObject",)
    )
    code, payload = gateway.execute_gateway(
        [
            "typed-call", URI,
            "--schema-digest", contract.schema_digest,
            "--set", game_object, "integer", "7",
            "--apply",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("bypass must fail before connection"),
    )

    assert code == 2
    assert "closed Core business continuation" in payload["message"]


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
def test_fixed_complex_tracer_cannot_bypass_its_typed_call_with_a_draft(
    tmp_path: Path,
    version: str,
) -> None:
    uri = "ak.wwise.debug.validateCall"
    contract = request_contract(version, uri)
    assert contract.as_gateway_payload()["input_shape"] == "inline"

    code, payload = gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), "draft-start", uri],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("rejection must be offline"),
    )

    assert code == 2
    assert payload["error_code"] == "OPERATION_DRAFT_ADAPTER_UNAVAILABLE"
    assert not (tmp_path / "state" / "operation-drafts-v1").exists()

def test_migrated_soundengine_draft_cannot_seal_shallow_typed_preview(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    state_dir = tmp_path / "state"
    contract = request_contract("2022.1", URI)
    game_object = next(
        field.handle for field in contract.fields if field.path == ("gameObject",)
    )
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", URI],
        env=env,
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    assert start_code == 0
    apply_code, rejected = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
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
            "set",
            "--field-handle",
            game_object,
            "--value-type",
            "integer",
            "--fact-value",
            "7",
        ],
        env=env,
        client_factory=lambda _url: pytest.fail(
            "retired typed action must stay offline"
        ),
    )
    assert apply_code == 2, rejected
    assert "no longer accepts shallow draft-apply" in rejected["message"]
