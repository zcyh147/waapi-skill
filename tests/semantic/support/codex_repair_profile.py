"""Closed first-batch schedule for the four v1.1 repair workflows.

Loading this definition cannot start Wwise, Codex, or a network connection.
The profile is separate from all previously sealed integration contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import load_closed_business_profile_source

PROFILE_ID = "waapi_v11_repairs_4"
PROFILE_CONTRACT = "waapi-skill.repair-profile/v1"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
BUDGET = {"fresh_tasks": 4, "user_turns": 4, "model_calls": 4,
          "transactions": 3, "hard_seconds_per_task": 600,
          "hard_seconds_total": 2400, "gateway_calls_per_task": 96,
          "reviewer_model_calls": 0, "automatic_reruns": 0}
_SCHEDULE = (
    ("F1", "allow_changes", "object.setProperty", 1),
    ("F2", "read_only", "ak.wwise.core.object.get", 0),
    ("F3", "allow_changes", "object.create", 1),
    ("F4", "allow_changes", "object.createPlugin", 1),
)
_FIXTURES = {'F1': {'plugin_name': 'Repair_Metadata_Room', 'plugin_type': 'Wwise RoomVerb', 'parent_path': '\\Effects\\Default Work Unit', 'pre_delay': 24}, 'F2': {'name': 'Repair_WindVelocity', 'missing_name': 'Repair_WindSpeed', 'type': 'GameParameter', 'parent_path': '\\Game Parameters\\Default Work Unit', 'min': -12, 'max': 36, 'default': 7}, 'F3': {'name': 'Repair_WindRange', 'type': 'GameParameter', 'parent_path': '\\Game Parameters\\Default Work Unit', 'min': -12, 'max': 36, 'default': 7}, 'F4': {'name': 'Repair_Independent_Room', 'plugin_type': 'Wwise RoomVerb', 'parent_path': '\\Effects\\Default Work Unit'}}
_FORBIDDEN = ("gateway.py", "draft-", "config-set", "query-object", "ak.wwise.",
              "--request", "transaction_id", "field_handle", "waapiclient")


@dataclass(frozen=True)
class RepairScenario:
    id: str
    api: str
    versions: tuple[str, ...] = ("2025.1",)


@dataclass(frozen=True)
class RepairUnit:
    case_id: str
    policy: str
    operation: str
    transaction_count: int
    prompt: str
    fixture: Mapping[str, Any]
    version: str = "2025.1"
    runner_lane: str = "project"
    user_turn_count: int = 1

    @property
    def unit_id(self) -> str:
        return "REPAIR25-" + self.case_id

    @property
    def scenario(self) -> RepairScenario:
        api = ("ak.wwise.core.object.set" if self.case_id == "F4" else
               self.operation if self.operation.startswith("ak.") else "ak.wwise.core." + self.operation)
        return RepairScenario(self.unit_id, api)

    @property
    def evidence_kind(self) -> str:
        return "agent_acceptance"


@dataclass(frozen=True)
class RepairProfile:
    path: Path
    definition_sha256: str
    units: tuple[RepairUnit, ...]

    @property
    def budget(self) -> dict[str, int]:
        return dict(BUDGET)


def load_repair_profile(path: Path, *, unit_ids: Sequence[str] = (),
                        versions: Sequence[str] = ()) -> RepairProfile:
    # The approved first batch is one complete selection, with no automatic retries.
    if tuple(unit_ids) not in {(), ("REPAIR25-F1", "REPAIR25-F2", "REPAIR25-F3", "REPAIR25-F4")} or tuple(versions) not in {(), ("2025.1",)}:
        raise ValueError("repair first batch requires all four workflows once on 2025.1")
    source = load_closed_business_profile_source(path, contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID, model=MODEL, reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER, expected_unit_count=4, error_type=ValueError,
        subject="v1.1 repair")
    units = []
    for value, (case, policy, operation, transactions) in zip(source.units, _SCHEDULE, strict=True):
        if (not isinstance(value, dict) or set(value) != {"case_id", "policy", "operation", "version", "prompt", "fixture"}
                or (value["case_id"], value["policy"], value["operation"], value["version"])
                != (case, policy, operation, "2025.1")):
            raise ValueError("repair workflow identity or modification policy drifted")
        prompt = value["prompt"]
        if (not isinstance(prompt, str) or not prompt.strip()
                or any(token in prompt.casefold() for token in _FORBIDDEN)):
            raise ValueError("repair prompt must express business intent without command mechanics")
        fixture = value["fixture"]
        if fixture != _FIXTURES[case]:
            raise ValueError("repair workflow requires deterministic fixture data")
        units.append(RepairUnit(case, policy, operation, transactions, prompt, fixture))
    return RepairProfile(source.path, source.definition_sha256, tuple(units))
