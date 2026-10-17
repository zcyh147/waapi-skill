"""Reusable read-only Short ID observation body; callers own all lifecycles."""
from __future__ import annotations

from typing import Any, Callable, Sequence


def collect_short_id_typed_read_observations(
    gateway: Callable[[Sequence[str]], dict[str, Any]],
    *,
    evidence: dict[str, Any],
) -> None:
    """Keep the original two-kind public read and exact-ID evidence unchanged."""
    observations = evidence["observations"]
    evidence["status"] = gateway(["status"])
    for kind, native_type, source in (("event", "Event", ["--custom-kind", "Event"]),
                                     ("dialogue-event", "DialogueEvent", ["--custom-kind", "DialogueEvent"])):
        discovered = gateway(["query-object", *source, "--include", "short-id", "--max-results", "1"])
        rows = discovered["agent_result"]
        assert isinstance(rows, list) and len(rows) == 1, f"{native_type} populated fixture prerequisite missing"
        chosen = rows[0]
        number = chosen.get("short_id")
        assert type(number) is int and 0 <= number <= 0xFFFFFFFF, chosen
        assert chosen["type"] == native_type
        result = gateway(["query-object", "--short-id", str(number), "--short-id-kind", kind,
            "--max-results", "64", "--include", "short-id", "--detail"])
        assert result["source_resolution"]["complete"] is True
        matches = [row for row in result["agent_result"] if row["id"] == chosen["id"]]
        assert len(matches) == 1 and matches[0]["type"] == native_type and matches[0]["short_id"] == number
        exact = gateway(["query-object", "--exact-id", chosen["id"], "--include", "short-id"])
        assert exact["agent_result"] == [chosen]
        observations.append({"kind": kind, "short_id": number, "canonical_id": chosen["id"],
            "outcome": "NATIVE_SUCCESS", "candidate_count": result["source_resolution"]["candidate_count"]})
