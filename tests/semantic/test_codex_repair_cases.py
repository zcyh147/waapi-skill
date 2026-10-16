from copy import deepcopy
import pytest
from tests.semantic.support.codex_repair_cases import (
    attest_predelay, require_predelay_metadata, read_refinement_proven, metadata_chain_proven,
)
from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError

DETAIL = {"agent_result": {"selection": "field", "metadata": {"name": "PreDelay", "type": "Real32",
    "default": 0, "restriction": {"min": 0, "max": 1000}, "unit": {"status": "known", "value": "Milliseconds"}}}}


def test_preflight_uses_complete_paged_inventory_and_exact_detail_without_write():
    calls = []
    def gateway(args):
        calls.append(args)
        if args[1] == "detail":
            assert args[-2:] == ["--selection", "field"]
            return deepcopy(DETAIL)
        if "--page" in args:
            assert args[-1] == "next"
            return {"agent_result": {"fields": [{"name": "PreDelay", "selection": "field"}], "next_page": None, "total_count": 2}}
        return {"agent_result": {"fields": [{"name": "Other", "selection": "other"}], "next_page": "next", "total_count": 2}}
    evidence = attest_predelay(gateway)
    assert len(evidence["pages"]) == 2
    assert evidence["metadata"]["name"] == "PreDelay"
    assert all(args[:2] in (["metadata", "list"], ["metadata", "detail"]) for args in calls)


@pytest.mark.parametrize("fault", ["unknown_unit", "seconds", "range", "name", "default"])
def test_no_guessed_predelay_value_or_units(fault):
    detail = deepcopy(DETAIL)
    metadata = detail["agent_result"]["metadata"]
    if fault == "unknown_unit":
        metadata["unit"] = {"status": "unknown", "value": None}
    elif fault == "seconds":
        metadata["unit"]["value"] = "Seconds"
    elif fault == "range":
        metadata["restriction"]["max"] = 20
    elif fault == "name":
        metadata["name"] = "Other"
    else:
        del metadata["default"]
    with pytest.raises(CaseBoundaryError):
        require_predelay_metadata(detail)


def test_refinement_requires_ordered_complete_miss_and_unique_matching_result():
    empty = {"command": "query-object", "payload": {"ok": True, "objects": [], "count": 0, "query_bound": {"mode": "take", "value": 10}}}
    found = {"command": "query-object", "payload": {"ok": True, "objects": [{"id": "target"}], "count": 1, "query_bound": {"mode": "take", "value": 10}}}
    assert read_refinement_proven([empty, found], target_id="target")
    assert not read_refinement_proven([found, empty], target_id="target")
    assert not read_refinement_proven([empty, found], target_id="other")
    found["payload"]["limit_reached"] = True
    assert not read_refinement_proven([empty, found], target_id="target")
