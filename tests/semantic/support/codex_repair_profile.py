"""Closed first-batch schedule for the four v1.1 repair workflows.

Loading this definition cannot start Wwise, Codex, or a network connection.
The profile is separate from all previously sealed integration contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import load_closed_business_profile_source

PROFILE_ID = "waapi_v11_repairs_4"
PROFILE_CONTRACT = "waapi-skill.repair-profile/v1"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
REMAINING_SUFFIX = ("REPAIR25-F2", "REPAIR25-F3", "REPAIR25-F4")
FINAL_PAIR = ("REPAIR25-F3", "REPAIR25-F4")
FINAL_SINGLETON = ("REPAIR25-F4",)
OPTIONAL_F2_RETRY = ("REPAIR25-F2",)
OPTIONAL_F2_F3_RETRY = ("REPAIR25-F2", "REPAIR25-F3")
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
_FIXTURES = {'F1': {'plugin_name': 'Repair_Metadata_Room',
        'plugin_type': 'Wwise RoomVerb',
        'parent_path': '\\Effects\\Default Work Unit',
        'pre_delay': 24,
        'parent_segments': ['Effects', 'Default Work Unit']},
 'F2': {'name': 'Repair_WindVelocity',
        'missing_name': 'Repair_WindSpeed',
        'type': 'GameParameter',
        'parent_path': '\\Game Parameters\\Default Work Unit',
        'min': -12,
        'max': 36,
        'default': 7,
        'parent_segments': ['Game Parameters', 'Default Work Unit']},
 'F3': {'name': 'Repair_WindRange',
        'type': 'GameParameter',
        'parent_path': '\\Game Parameters\\Default Work Unit',
        'min': -12,
        'max': 36,
        'default': 7,
        'parent_segments': ['Game Parameters', 'Default Work Unit']},
 'F4': {'name': 'Repair_Independent_Room',
        'plugin_type': 'Wwise RoomVerb',
        'parent_path': '\\Effects\\Default Work Unit',
        'parent_segments': ['Effects', 'Default Work Unit']}}
_FORBIDDEN = ("gateway.py", "draft-", "config-set", "query-object", "ak.wwise.",
              "--request", "transaction_id", "field_handle", "waapiclient")


@dataclass(frozen=True)
class RepairScenario:
    id: str
    api: str
    prompt_sha256: str
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
    def parent_segments(self) -> tuple[str, ...]:
        return tuple(self.fixture["parent_segments"])

    @property
    def unit_id(self) -> str:
        return "REPAIR25-" + self.case_id

    @property
    def scenario(self) -> RepairScenario:
        api = ("ak.wwise.core.object.set" if self.case_id == "F4" else
               self.operation if self.operation.startswith("ak.") else "ak.wwise.core." + self.operation)
        return RepairScenario(self.unit_id, api, hashlib.sha256(self.prompt.encode("utf-8")).hexdigest())

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
        return {**BUDGET, "fresh_tasks": len(self.units), "user_turns": sum(unit.user_turn_count for unit in self.units),
                "model_calls": len(self.units), "transactions": sum(unit.transaction_count for unit in self.units),
                "hard_seconds_total": len(self.units) * BUDGET["hard_seconds_per_task"]}


def load_repair_profile(path: Path, *, unit_ids: Sequence[str] = (),
                        versions: Sequence[str] = ()) -> RepairProfile:
    # Selection support does not authorize a launch; retries require new user approval.
    if tuple(unit_ids) not in {(), ("REPAIR25-F1", "REPAIR25-F2", "REPAIR25-F3", "REPAIR25-F4"), REMAINING_SUFFIX, FINAL_PAIR, FINAL_SINGLETON, OPTIONAL_F2_RETRY, OPTIONAL_F2_F3_RETRY} or tuple(versions) not in {(), ("2025.1",)}:
        raise ValueError("repair selection requires all four workflows or the ordered F2-F4 / F3-F4 / F4 continuations or explicit F2 / F2-F3 retries on 2025.1")
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
    selected = tuple(unit for unit in units if not unit_ids or unit.unit_id in unit_ids)
    return RepairProfile(source.path, source.definition_sha256, selected)
