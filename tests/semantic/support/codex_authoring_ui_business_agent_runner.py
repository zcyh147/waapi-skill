"""Fresh Agent runner for Authoring UI capture and command Business Drafts."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_authoring_ui_business_profile import (
    AuthoringUiBusinessUnit,
)
from tests.semantic.support.codex_business_agent_runner import (
    BusinessAgentOptions,
    BusinessAgentRunSpec,
    run_business_agent_unit,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_authoring_ui_business_transaction_steps,
)
from wwise_waapi.operation_ui_commands import MAX_LIVE_COMMANDS


OUTCOME_CONTRACT = "waapi-skill.authoring-ui-business-agent-outcome/v1"
AuthoringUiBusinessAgentOptions = BusinessAgentOptions


@dataclass(frozen=True, slots=True)
class AuthoringUiBusinessRuntime:
    fixture_path: Path
    prompt: str
    request: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AuthoringUiBusinessAgentOutcome:
    scenario_id: str
    version: str
    status: str
    reason: str
    thread_id: str
    gates: Mapping[str, bool]
    command_count: int
    transaction_count: int
    production_gateway: bool
    wwise_started: bool
    final_response: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {"contract": OUTCOME_CONTRACT, **asdict(self)}


def prepare_authoring_ui_business_runtime(
    unit: AuthoringUiBusinessUnit,
    root: str | Path,
) -> AuthoringUiBusinessRuntime:
    runtime_root = Path(root).expanduser().resolve(strict=False)
    runtime_root.mkdir(parents=True, exist_ok=False)
    project_path = runtime_root / "project" / "SemanticProject.wproj"
    project_path.parent.mkdir()
    for name in ("Originals", "GeneratedSoundBanks", "Commands", ".cache"):
        (project_path.parent / name).mkdir()
    project_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n',
        encoding="utf-8",
    )
    fixture_path = runtime_root / "waapi-fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "version": unit.version,
                "platform": "windows" if os.name == "nt" else "macosx",
                "process_path": str(runtime_root / "WwiseAuthoring"),
                "project_path": str(project_path),
                "is_command_line": False,
                "objects": [],
                "fields": [],
                "command_ids": ["SaveProject"],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": unit.version,
        "operation": unit.operation,
        "arguments": dict(unit.request_arguments),
    }
    return AuthoringUiBusinessRuntime(
        fixture_path=fixture_path,
        prompt=unit.prompt,
        request=request,
    )


def _final_response_reports_preview(
    final_response: str,
    *,
    operation: str,
    markers: Sequence[str],
) -> bool:
    normalized = final_response.casefold()
    if all(marker.casefold() in normalized for marker in markers) and (
        "预览" in normalized or "preview" in normalized
    ):
        return True
    try:
        payload = json.loads(final_response)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    if isinstance(payload.get("agent_result"), Mapping):
        payload = payload["agent_result"]
    request = payload.get("request")
    return bool(
        payload.get("operation") == operation
        and payload.get("state") == "awaiting_confirmation"
        and payload.get("executed") is False
        and isinstance(request, Mapping)
        and request.get("operation") == operation
    )


def _preview_matches_request(records: Sequence[Any], request: Mapping[str, Any]) -> bool:
    previews = [record for record in records if record.step_name == "tx01.preview"]
    if len(previews) != 1 or not isinstance(previews[0].payload, Mapping):
        return False
    agent_result = previews[0].payload.get("agent_result")
    observed = agent_result.get("request") if isinstance(agent_result, Mapping) else None
    return observed == request


def _command_choice_came_from_inventory(
    unit: AuthoringUiBusinessUnit,
    records: Sequence[Any],
) -> bool:
    inventory = [
        record
        for record in records
        if record.step_name == "tx01.command-inventory"
    ]
    if unit.operation == "ui.captureScreen":
        return not inventory
    if len(inventory) != 1 or not isinstance(inventory[0].payload, Mapping):
        return False
    agent_result = inventory[0].payload.get("agent_result")
    commands = (
        agent_result.get("commands")
        if isinstance(agent_result, Mapping)
        else None
    )
    expected = unit.request_arguments.get("command")
    return bool(
        isinstance(commands, list)
        and 0 < len(commands) <= MAX_LIVE_COMMANDS
        and all(isinstance(command, str) and command for command in commands)
        and isinstance(expected, str)
        and expected in commands
    )


def run_authoring_ui_business_agent_unit(
    unit: AuthoringUiBusinessUnit,
    *,
    scenario_root: Path,
    options: AuthoringUiBusinessAgentOptions,
) -> AuthoringUiBusinessAgentOutcome:
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=BusinessAgentRunSpec(
            prepare_runtime=prepare_authoring_ui_business_runtime,
            build_steps=lambda runtime: build_authoring_ui_business_transaction_steps(
                runtime.request,
                label="tx01",
            ),
            transaction_count=lambda _runtime: 1,
            preview_gates=_authoring_ui_preview_gates,
            outcome_factory=AuthoringUiBusinessAgentOutcome,
            commutative_read_only_step_groups=(
                _authoring_ui_commutative_read_groups
            ),
        ),
    )


def _authoring_ui_commutative_read_groups(
    runtime: AuthoringUiBusinessRuntime,
) -> Sequence[Sequence[str]]:
    if runtime.request["operation"] != "ui.commands.execute":
        return ()
    return (
        (
            "tx01.operation-schema",
            "tx01.command-inventory-schema",
            "tx01.command-inventory",
        ),
    )


def _authoring_ui_preview_gates(
    unit: AuthoringUiBusinessUnit,
    runtime: AuthoringUiBusinessRuntime,
    result: Any,
    broker_evidence: Any,
) -> Mapping[str, bool]:
    return {
        "preview_reported": _final_response_reports_preview(
            result.final_response,
            operation=unit.operation,
            markers=unit.final_markers,
        ),
        "canonical_business_request": _preview_matches_request(
            broker_evidence.records,
            runtime.request,
        ),
        "fresh_command_choice": _command_choice_came_from_inventory(
            unit,
            broker_evidence.records,
        ),
    }


__all__ = [
    "AuthoringUiBusinessAgentOptions",
    "AuthoringUiBusinessAgentOutcome",
    "AuthoringUiBusinessRuntime",
    "prepare_authoring_ui_business_runtime",
    "run_authoring_ui_business_agent_unit",
]
