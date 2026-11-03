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


def collect_short_id_diagnostic_observations(
    gateway: Callable[[Sequence[str]], dict[str, Any]], *, evidence: dict[str, Any],
) -> None:
    """Observe hypotheses without changing the resolver or accepting a workaround.

    The discovered uint32 is never replaced by a convenient low ID. All native
    errors, empty/colliding candidates, and original public results are retained
    by the lifecycle owner. These advanced reads grant no mutation authority.
    """
    evidence["status"] = gateway(["status"])
    discovered = gateway(["query-object", "--custom-kind", "DialogueEvent", "--include", "short-id", "--max-results", "1"])
    rows = discovered["agent_result"]
    assert isinstance(rows, list) and len(rows) == 1, "DialogueEvent populated fixture prerequisite missing"
    chosen = rows[0]
    number = chosen.get("short_id")
    assert type(number) is int and 0 <= number <= 0xFFFFFFFF and chosen["type"] == "DialogueEvent", chosen
    exact = gateway(["query-object", "--exact-id", chosen["id"], "--include", "short-id"])
    assert exact["agent_result"] == [chosen], "Exact GUID identity changed before diagnosis"
    evidence["chosen"] = chosen
    original = gateway(["query-object", "--short-id", str(number), "--short-id-kind", "dialogue-event",
        "--max-results", "64", "--include", "short-id", "--detail"])
    assert original["source_resolution"]["complete"] is True
    evidence["baseline_contains_chosen_identity"] = original["agent_result"].count(chosen) == 1
    gateway(["query-schema", "--advanced"])
    signed = number - (1 << 32) if number >= (1 << 31) else number
    typed = "from type DialogueEvent"
    guid = f'from object "{chosen["id"]}"'
    variants = (
        ("typed-unsigned", f"{typed} where shortId = {number}",
         "If final projection or business-source handling causes the miss, an identical typed uint32 predicate through the advanced read will differ."),
        ("guid-unsigned", f"{guid} where shortId = {number}",
         "If typed-source enumeration causes the miss, the same unsigned predicate on the exact GUID will retain it."),
        ("typed-signed32", f"{typed} where shortId = {signed}",
         "If accessor/comparison signedness causes the miss, only its signed32 reinterpretation may retain the GUID; this is a hypothesis, not a public ID conversion."),
        ("typed-decimal", f"{typed} where shortId = {number}.0",
         "If integer-literal representation causes the miss, the numerically equivalent decimal literal may retain the GUID; decimal syntax/native acceptance is itself observed."),
        ("guid-no-predicate", guid,
         "If the advanced projection or exact source cannot read the known object, the no-predicate exact GUID control will also fail."),
    )
    evidence["variants"] = []
    for name, expression, hypothesis in variants:
        result = gateway(["query-object", "--advanced-waql", expression, "--include", "short-id",
            "--max-results", "65", "--detail"])
        candidates = result.get("agent_result")
        accepted = result.get("ok") is True and isinstance(candidates, list)
        evidence["variants"].append({"name": name, "expression": expression, "hypothesis": hypothesis,
            "status": "observed" if accepted else "query_failed", "candidate_count": len(candidates) if accepted else None,
            "exact_chosen_matches": candidates.count(chosen) if accepted else None,
            "mutation_authority": False, "functional_acceptance": False})
