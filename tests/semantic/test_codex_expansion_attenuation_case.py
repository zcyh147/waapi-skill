from copy import deepcopy

import pytest
from pathlib import Path

from tests.semantic.support.codex_expansion_attenuation_case import (
    C08_ASSERTIONS, C08_CURVE_ROLES, approve_c08_preview, prepare_c08, verify_c08,
)
from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError
from tests.unit.test_object_graph_business_gateway import gateway as public_gateway


def _baseline():
    return {
        "attenuation": {"id": "attenuation", "name": "Owned"},
        "curves": {
            "volume-dry": {"use": "Custom", "points": [{"x": 0.0, "y": -3.0, "shape": "Linear"}]},
            "low-pass-filter": {"use": "Custom", "points": [{"x": 0.0, "y": 0.0, "shape": "Linear"}]},
        },
        "users": {"sound": {"id": "sound", "references": {"Attenuation": {"id": "attenuation"}}}},
        "source": {"id": "original", "curves": {"preserved": True}},
    }


def test_attenuation_oracle_accepts_only_requested_curve_and_preserves_other_state():
    before = _baseline()
    points = [{"x": 0.0, "y": 0.0, "shape": "Linear"},
              {"x": 100.0, "y": -48.0, "shape": "Linear"}]
    after = deepcopy(before)
    after["curves"]["volume-dry"] = {"use": "Custom", "points": points}
    result = verify_c08(before, after, expected_points=points)
    assert set(result) == C08_ASSERTIONS
    assert all(result.values())
    after["curves"]["low-pass-filter"]["points"][0]["y"] = 20
    assert verify_c08(before, after, expected_points=points)["other_curves_unchanged"] is False


@pytest.mark.parametrize("damage", ("missing_curve", "missing_user", "source", "identity", "point_order"))
def test_attenuation_oracle_rejects_missing_or_collateral_changes(damage):
    before = _baseline()
    points = [{"x": 0.0, "y": 0.0, "shape": "Linear"},
              {"x": 100.0, "y": -48.0, "shape": "Linear"}]
    after = deepcopy(before)
    after["curves"]["volume-dry"] = {"use": "Custom", "points": deepcopy(points)}
    if damage == "missing_curve":
        del after["curves"]["low-pass-filter"]
    elif damage == "missing_user":
        after["users"] = {}
    elif damage == "source":
        after["source"]["curves"] = {}
    elif damage == "identity":
        after["attenuation"]["id"] = "replacement"
    else:
        after["curves"]["volume-dry"]["points"].reverse()
    assert not all(verify_c08(before, after, expected_points=points).values())


def test_attenuation_preview_closes_api_target_curve_options_and_points():
    points = [{"x": 0.0, "y": 0.0, "shape": "Linear"}]
    artifact = {"request": {"operation": "waapi.call", "version": "2025.1", "arguments": {
        "api": "ak.wwise.core.object.setAttenuationCurve", "options": {},
        "args": {"object": "target", "curveType": "VolumeDryUsage", "use": "Custom", "points": points},
    }}}
    assert approve_c08_preview(artifact, version="2025.1", object_id="target", expected_points=points)
    for key, value in (("object", "another"), ("curveType", "SpreadUsage"), ("platform", "Windows")):
        changed = deepcopy(artifact)
        changed["request"]["arguments"]["args"][key] = value
        assert not approve_c08_preview(changed, version="2025.1", object_id="target", expected_points=points)


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_attenuation_setup_cli_parses_and_snapshot_checks_independent_curves(version, tmp_path: Path):
    """Parse real CLI argv; fake replies exercise orchestration, not live setup."""
    source_id = "{D7B7A627-3D4A-4921-842E-0A38A2DB2492}"
    copied_id = "{11111111-1111-1111-1111-111111111111}"
    sound_id = "{22222222-2222-2222-2222-222222222222}"
    curves = {role: {"use": "None", "points": []} for role in C08_CURVE_ROLES}
    curves["volume-dry"] = {"use": "Custom", "points": [
        {"x": 0.0, "y": 0.0, "shape": "Linear"}, {"x": 100.0, "y": -96.3, "shape": "Linear"},
    ]}
    curves["spread"] = {"use": "Custom", "points": [{"x": 0.0, "y": 60.0, "shape": "Linear"}]}
    target_curves = deepcopy(curves)
    starts, calls = [], []
    parser = public_gateway.build_parser()
    def gateway(argv):
        parser.parse_args(argv)
        calls.append(tuple(argv))
        command = argv[0]
        if command == "metadata":
            role = argv[argv.index("--curve-role") + 1]
            identifier = argv[argv.index("--exact-id") + 1]
            curve = (curves if identifier == source_id else target_curves)[role]
            return {"ok": True, "status": "ok", "agent_result": {"curve_role": role, **deepcopy(curve)}}
        if command == "query-object":
            identifier = argv[argv.index("--exact-id") + 1] if "--exact-id" in argv else sound_id
            row = {"id": identifier, "name": "Fixture", "path": rf"\Fixture\{identifier}",
                   "type": "Sound" if identifier == sound_id else "Attenuation", "notes": "", "parent": {"id": "parent"}}
            if identifier == sound_id:
                row.update(volume_db=-3, output_bus={"id": "bus"}, references={"Attenuation": {"id": copied_id}})
            return {"ok": True, "status": "ok", "objects": [row], "count": 1, "query_bound": {"mode": "take", "value": 2}}
        if command == "draft-start":
            starts.append(argv[1])
            return {"draft": {"draft_id": str(len(starts)), "revision": 1}, "task_authority": "authority"}
        if command == "draft-bind-object":
            if starts[-1] == "object.setReference":
                assert "--role" not in argv, "metadata-owned object bindings have no business role"
            return {"bound_object": {"handle": "handle"}, "draft": {"revision": 2}}
        if command == "draft-discover-fields":
            return {"meaning_results": [{"candidates": [{"handle": "attenuation-field"}]}], "draft": {"revision": 3}}
        if command == "preview-from-draft":
            return {"transaction_id": "tx"}
        if command == "transaction-show":
            return {"confirmation": {"token": "shown-token"}}
        if command == "execute":
            return {"state": "executed_unverified", "dispatch_result": {"result": {"id": copied_id}}}
        if command == "verify":
            return {"state": "verified", "verification": {"business_state_verified": True}}
        assert command in {"draft-declare-object-change", "draft-declare-new", "draft-declare-field-change", "draft-check", "confirm"}, argv
        return {"draft": {"revision": 4}}
    ctx = ExpansionCaseContext(version, "C08", tmp_path / "Fixture.wproj", tmp_path / "assets", gateway)
    case = prepare_c08(ctx)
    assert starts == ["object.copy", "object.setName", "object.create", "object.setReference"]
    assert case.policy == "allow_changes" and case.operation == "waapi.call"
    assert case.accepted_verification_states == {"result_schema_checked"}
    assert case.request_schema_uri == "ak.wwise.core.object.setAttenuationCurve"
    assert case.read_curve_roles == set(C08_CURVE_ROLES)
    assert len([call for call in calls if call[0] == "confirm"]) == 4
    reference_start = next(index for index, call in enumerate(calls)
                           if call[:2] == ("draft-start", "object.setReference"))
    reference_bindings = [call for call in calls[reference_start:]
                          if call[0] == "draft-bind-object"]
    assert len(reference_bindings) == 2
    assert [call[call.index("--object-id") + 1] for call in reference_bindings] == [sound_id, copied_id]
    target_curves["volume-dry"] = {"use": "Custom", "points": [
        {"x": 0.0, "y": 0.0, "shape": "Linear"}, {"x": 50.0, "y": -12.0, "shape": "Linear"},
        {"x": 100.0, "y": -48.0, "shape": "Linear"},
    ]}
    assert all(case.verify(case.before, case.snapshot()).values())
    target_curves["spread"]["points"] = None
    with pytest.raises(CaseBoundaryError, match="every bounded"):
        case.snapshot()
