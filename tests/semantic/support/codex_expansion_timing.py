"""Fixed, opt-in expansion phase evidence; deadlines are cooperative.

Oracle callbacks overlap preparation or Agent wall time. Phase totals use the
union of measured intervals, never the sum of nested callback/RPC durations.
Cleanup recovery is measured even after an allowance is exhausted.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Callable

CONTRACT = "waapi-skill.integration-expansion-phase-timing/v1"
PHASES = ("startup", "preparation", "oracle", "cleanup")


def phase_policy() -> dict[str, Any]:
    return {"contract": CONTRACT, "allowances_seconds": {
        "startup": None, "preparation": 600, "oracle": 600, "cleanup": 180},
        "enforcement": "cooperative; synchronous filesystem/CPU work is not preempted",
        "startup_scope": "launch through readiness; existing effective lifecycle component bounds",
        "oracle_overlap": "nested in preparation or Agent wall time; do not add or subtract",
        "cleanup_recovery": "continue shutdown, source proof and removal after exhaustion",
        "agent_seconds": 600, "agent_slow_seconds": 420, "reviewer_seconds": 120}


class ExpansionPhaseTimeout(TimeoutError):
    """Normal expansion work cannot start after its phase allowance expires."""


def _union_seconds(rows):
    intervals = sorted((row["started_seconds"], row["finished_seconds"]) for row in rows)
    total, end = 0.0, None
    for start, finish in intervals:
        total += max(0.0, finish - (start if end is None else max(start, end)))
        end = finish if end is None else max(end, finish)
    return total


class ExpansionPhaseTiming:
    """One case's four fixed phases, shared only by runner-owned callbacks."""

    def __init__(self, *, clock: Callable[[], float] | None = None):
        self.clock = clock or time.monotonic
        self.rows: list[dict[str, Any]] = []
        self.active: list[dict[str, Any]] = []
        self._sequence = 0

    @property
    def attribution(self):
        return self.active[-1]["phase"] if self.active else "agent"

    @property
    def recovering(self):
        return any(row["recovery"] for row in self.active)

    def remaining(self, phase):
        allowance = phase_policy()["allowances_seconds"][phase]
        if allowance is None:
            return None
        now = self.clock()
        rows = [row for row in self.rows if row["phase"] == phase]
        rows += [{**row, "finished_seconds": now} for row in self.active if row["phase"] == phase]
        return max(0.0, allowance - _union_seconds(rows))

    def bounded_wait(self, seconds, *, phase=None, recovery=False):
        phases = {row["phase"] for row in self.active} if phase is None else {phase}
        result = float(seconds)
        for name in phases:
            remaining = self.remaining(name)
            if remaining is not None:
                if remaining <= 0:
                    if recovery:
                        continue  # retain existing positive component waits for mandatory teardown
                    raise ExpansionPhaseTimeout(f"{name} allowance exhausted before dispatch")
                result = min(result, remaining)
        return result

    @contextmanager
    def measure(self, phase, scope, *, recovery=False, component_bounds=None):
        if phase not in PHASES:
            raise ValueError("unknown expansion timing phase")
        if not recovery:
            self.bounded_wait(1, phase=phase)
        self._sequence += 1
        row = {"sequence": self._sequence, "phase": phase, "scope": scope,
            "parent": self.active[-1]["sequence"] if self.active else None,
            "attribution": self.attribution if self.active or phase == "oracle" else phase, "recovery": recovery,
            "component_bounds_seconds": dict(component_bounds or {}),
            "started_seconds": self.clock(), "status": "completed", "error_type": None}
        self.active.append(row)
        try:
            yield row
        except BaseException as exc:
            row.update(status="error", error_type=type(exc).__name__)
            raise
        finally:
            row["finished_seconds"] = self.clock()
            row["elapsed_seconds"] = row["finished_seconds"] - row["started_seconds"]
            self.active.pop()
            self.rows.append(row)

    def evidence(self):
        if self.active:
            raise RuntimeError("expansion phase evidence has unfinished intervals")
        phases = {}
        for phase in PHASES:
            rows = [row for row in self.rows if row["phase"] == phase]
            elapsed = _union_seconds(rows)
            allowance = phase_policy()["allowances_seconds"][phase]
            phases[phase] = {"elapsed_seconds": elapsed, "measured": bool(rows),
                "exhausted": allowance is not None and elapsed >= allowance,
                "errors": sum(row["status"] == "error" for row in rows)}
        return {"contract": CONTRACT, "policy": phase_policy(), "phases": phases,
            "intervals": sorted(self.rows, key=lambda row: row["sequence"])}
