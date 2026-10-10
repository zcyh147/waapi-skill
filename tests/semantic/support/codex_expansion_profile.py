"""Static selection for the separately versioned integration expansion."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from tests.semantic.support.codex_expansion_policy import POLICY_CONTRACT, canonical_digest


PROFILE_ID = "integration_expansion_v1"
PROFILE_CONTRACT = "waapi-skill.integration-expansion-profile/v1"
CASE_IDS = ("C01", "C03", "C06", "C08", "C09", "M01", "M05")
VERSIONS = ("2022.1", "2025.1")
_APIS = {
    "C01": "ak.wwise.core.audio.import", "C03": "ak.wwise.core.audio.import",
    "C06": "ak.wwise.core.object.set", "C08": "ak.wwise.core.object.setAttenuationCurve",
    "C09": "ak.wwise.core.object.create", "M01": "ak.wwise.core.audio.import",
    "M05": "ak.wwise.core.object.setReference",
}
MODEL_CONFIGURATIONS = frozenset({("gpt-6-luna", "high", "default"),
                                  ("gpt-6.1-sol", "medium", "default"),
                                  ("gpt-6.1-sol", "high", "default"),
                                  ("gpt-6-luna", "medium", "default")})


@dataclass(frozen=True)
class ExpansionScenario:
    id: str
    api: str
    versions: tuple[str, ...]

    @property
    def prompt_sha256(self) -> str:
        # The rendered prompt is separately frozen after trusted preparation.
        return canonical_digest({"case": self.id, "api": self.api, "versions": self.versions})


@dataclass(frozen=True)
class ExpansionUnit:
    case_id: str
    unit_id: str
    version: str
    policy: str
    scenario: ExpansionScenario
    runner_lane: str = "project"

    @property
    def evidence_kind(self) -> str:
        return "capability_boundary" if (self.case_id, self.version) == ("M05", "2022.1") else "agent_acceptance"

    @property
    def user_turn_count(self) -> int:
        if self.evidence_kind == "capability_boundary":
            return 0
        return 2 if self.policy == "ask_before_changes" else 1

    @property
    def transaction_count(self) -> int:
        return 0 if self.evidence_kind == "capability_boundary" else 1


@dataclass(frozen=True)
class ExpansionProfile:
    path: Path
    definition_sha256: str
    units: tuple[ExpansionUnit, ...]
    capability_boundaries: tuple[ExpansionUnit, ...]


def validate_model_configuration(model: str, reasoning_effort: str, service_tier: str) -> None:
    if (model, reasoning_effort, service_tier) not in MODEL_CONFIGURATIONS:
        raise ValueError("expansion requires an explicitly reviewed model/reasoning/service configuration")


def load_expansion_profile(path: Path, *, unit_ids: Sequence[str] = (),
                           versions: Sequence[str] = ()) -> ExpansionProfile:
    path = Path(path).resolve(strict=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"contract", "profile_id", "versions", "cases", "ask_cases", "capability_boundaries",
                "agent_budget", "model_configurations", "pilot_cases", "outcome_policy"}
    models = data.get("model_configurations", []) if isinstance(data, dict) else []
    if (not isinstance(data, dict) or set(data) != required or data["contract"] != PROFILE_CONTRACT
            or data["profile_id"] != PROFILE_ID or tuple(data["versions"]) != VERSIONS
            or tuple(data["cases"]) != CASE_IDS or data["ask_cases"] != ["C01", "C03"]
            or data["capability_boundaries"] != [{"case_id": "M05", "version": "2022.1"}]
            or data["agent_budget"] != {"hard_seconds": 600, "slow_seconds": 420}
            or data["pilot_cases"] != ["C01", "M01", "C06"] or data["outcome_policy"] != POLICY_CONTRACT
            or len(models) != len(MODEL_CONFIGURATIONS)
            or any(not isinstance(row, dict) or set(row) != {"model", "reasoning_effort", "service_tier"} for row in models)
            or {(row["model"], row["reasoning_effort"], row["service_tier"]) for row in models} != MODEL_CONFIGURATIONS):
        raise ValueError("expansion profile differs from its reviewed closed contract")
    if len(set(versions)) != len(versions) or set(versions) - set(VERSIONS):
        raise ValueError("expansion version selection is unavailable or duplicated")
    all_units = tuple(ExpansionUnit(
        case, f"EXP{version[2:4]}-{case}", version,
        "ask_before_changes" if case in {"C01", "C03"} else "allow_changes",
        ExpansionScenario(f"EXP{version[2:4]}-{case}", _APIS[case], (version,)),
    ) for version in VERSIONS for case in CASE_IDS)
    accepted_ids = set(CASE_IDS) | {unit.unit_id for unit in all_units}
    if len(set(unit_ids)) != len(unit_ids) or set(unit_ids) - accepted_ids:
        raise ValueError("expansion case selection is unavailable or duplicated")
    selected = tuple(unit for unit in all_units
                     if (not versions or unit.version in versions)
                     and (not unit_ids or unit.case_id in unit_ids or unit.unit_id in unit_ids))
    if any(sum(unit.case_id == selector or unit.unit_id == selector for selector in unit_ids) > 1
           for unit in selected):
        raise ValueError("expansion selectors overlap the same unit")
    if any(not any(unit.case_id == selector or unit.unit_id == selector for unit in selected)
           for selector in unit_ids):
        raise ValueError("expansion selector does not match the requested versions")
    if not selected:
        raise ValueError("no expansion units match the selection")
    boundaries = tuple(unit for unit in selected if (unit.case_id, unit.version) == ("M05", "2022.1"))
    return ExpansionProfile(path, canonical_digest(data),
                            tuple(unit for unit in selected if unit not in boundaries), boundaries)
