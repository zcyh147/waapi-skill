"""Inline curve outcomes use exact field/type evidence through public Gateway."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_field_interface_closure_gateway import FIRST, VERSIONS
from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask


CURVE = "{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}"
POINTS = [{"x": 0, "y": -48, "shape": "Linear"}, {"x": 50, "y": -6, "shape": "Linear"},
          {"x": 100, "y": 0, "shape": "Linear"}]


class InlineCurveTask(OwnedGraphTask):
    def __init__(self, path: Path, version: str) -> None:
        super().__init__(path, version, "object.set")
        self.objects[FIRST].update({"type": "RTPC", "name": "", "notes": "Keep relation",
            "path": self.objects[FIRST]["path"] + r"\[RTPC: Voice Volume, Rain_Intensity]",
            "@Curve": {"id": CURVE, "points": deepcopy(POINTS), "@Flags": 3}})
        self.objects[FIRST]["@Curve"]["points"][1]["y"] = -12
        self.objects[CURVE] = {"id": CURVE, "name": "", "type": "Curve", "parent": None,
            "owner": {"id": FIRST}, "path": self.objects[FIRST]["path"] + r"\[Curve]", "notes": ""}
        self.types.extend([{"classId": 917520, "name": "Curve", "type": "WObject"}])
        self.metadata["Curve"] = {"name": "Curve", "type": "Reference", "display": {"name": "Response curve"},
            "restriction": {"type": "reference", "restrictions": [{"type": ["Curve"]}]}}
        self.curve_failure: str | None = None

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        result = super().call(uri, args, options)
        if uri.endswith("object.set"):
            for item in args["objects"]:
                if "@Curve" in item:
                    points = deepcopy(item["@Curve"]["points"])
                    self.objects[item["object"]]["@Curve"] = {"id": CURVE, "points": points, "@Flags": 3}
            for row in list(self.objects.values()):
                curve = row.get("@Curve")
                if isinstance(curve, dict) and curve.get("type") == "Curve":
                    curve_id = "{CDCDCDCD-CDCD-CDCD-CDCD-CDCDCDCDCDCD}"
                    row["@Curve"] = {"id": curve_id, "points": deepcopy(curve["points"])}
                    self.objects[curve_id] = {"id": curve_id, "name": "", "type": "Curve", "notes": "",
                        "path": row["path"] + r"\[Curve]", "parent": None, "owner": {"id": row["id"]}}
            if self.curve_failure == "wrong-points":
                self.objects[FIRST]["@Curve"]["points"][1]["y"] = -99
            elif self.curve_failure == "boolean-point":
                self.objects[FIRST]["@Curve"]["points"][-1]["y"] = False
            elif self.curve_failure == "missing-points":
                del self.objects[FIRST]["@Curve"]["points"]
            elif self.curve_failure == "wrong-class":
                self.objects[CURVE]["type"] = "Sound"
            elif self.curve_failure == "missing-class-identity":
                del self.objects[FIRST]["@Curve"]["id"]
            elif self.curve_failure == "metadata-drift":
                self.metadata["Curve"]["restriction"] = {"type": "reference", "restrictions": [{"type": ["Bus"]}]}
        return result


def declare_curve(task: InlineCurveTask) -> tuple[int, dict[str, Any]]:
    owner = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--object-handle", owner, "--meaning", "Response curve")
    assert code == 0, discovered
    candidate = discovered["meaning_results"][0]["candidates"][0]
    eligible = task.metadata["Curve"]["restriction"] == {"type": "reference", "restrictions": [{"type": ["Curve"]}]}
    assert ("json_curve_points" in candidate["value_input"]["accepted_forms"]) is eligible
    field = candidate["handle"]
    return task.step("draft-declare-existing", "--declaration-id", "response", "--object-handle", owner,
                     "--field-value", field, json.dumps({"curve_points": POINTS}))


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_inline_curve_points_reach_preview_native_dispatch_and_independent_point_readback(
    tmp_path: Path, version: str,
) -> None:
    task = InlineCurveTask(tmp_path, version)
    code, declared = declare_curve(task)
    assert code == 0, declared
    tx, shown = task.preview()
    args = shown["artifact"]["prepared_operation"]["dispatch"]["args"]
    assert args["objects"] == [{"object": FIRST, "@Curve": {"type": "Curve", "points": POINTS}}]
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)
    assert task.objects[FIRST]["notes"] == "Keep relation"
    assert len([uri for uri, _, _ in task.calls if uri.endswith("object.set")]) == 1


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("failure", ("wrong-points", "boolean-point", "missing-points", "wrong-class", "missing-class-identity", "metadata-drift"))
def test_inline_curve_never_certifies_malformed_or_unrelated_native_effects(
    tmp_path: Path, version: str, failure: str,
) -> None:
    task = InlineCurveTask(tmp_path, version)
    code, declared = declare_curve(task)
    assert code == 0, declared
    tx, shown = task.preview()
    task.curve_failure = failure
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified["verified"] is False, verified
    code, replay = task.run("execute", tx)
    assert code == 2, replay
    assert len([uri for uri, _, _ in task.calls if uri.endswith("object.set")]) == 1


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("drift", ("metadata", "omission-provenance", "class", "field-membership"))
def test_inline_curve_revalidates_exact_metadata_and_class_before_the_one_write(
    tmp_path: Path, version: str, drift: str,
) -> None:
    task = InlineCurveTask(tmp_path, version)
    if drift == "omission-provenance":
        task.metadata["Curve"].pop("name")
        task.metadata["Curve"].pop("type")
    code, declared = declare_curve(task)
    assert code == 0, declared
    tx, shown = task.preview()
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if drift == "metadata":
        task.metadata["Curve"]["restriction"] = {"type": "reference", "restrictions": [{"type": ["Bus"]}]}
    elif drift == "omission-provenance":
        task.metadata["Curve"]["name"] = "Curve"
        task.metadata["Curve"]["type"] = "Reference"
    elif drift == "class":
        task.types[-1]["classId"] += 1
    else:
        del task.metadata["Curve"]
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("restriction", (
    {},
    {"type": "reference", "restrictions": [{"type": ["Bus"]}]},
    {"type": "reference", "restrictions": [{"type": ["Curve"], "sharedOnlyTypes": ["Curve"]}]},
    {"type": "reference", "restrictions": [{"type": ["Curve"]}, {"childOfReference": "Owner"}]},
))
def test_inline_curve_requires_proven_custom_curve_field_applicability(
    tmp_path: Path, version: str, restriction: dict[str, Any],
) -> None:
    task = InlineCurveTask(tmp_path, version)
    task.metadata["Curve"]["restriction"] = restriction
    code, declared = declare_curve(task)
    if code == 0:
        code, declared = task.step("draft-check")
    assert code == 2, declared
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("value", (
    {"type": "Curve", "points": POINTS},
    {"curve_points": [{"x": True, "y": 0, "shape": "Linear"}]},
    {"curve_points": [{"x": 0, "y": 0, "shape": "Unknown"}]},
    {"curve_points": [{"x": 0, "y": 0, "shape": "Linear", "id": CURVE}]},
    {"curve_points": [POINTS[0]] * 257},
    {"curve_points": None},
))
def test_inline_curve_business_input_is_closed_and_bounded_without_draft_changes(
    tmp_path: Path, version: str, value: dict[str, Any],
) -> None:
    task = InlineCurveTask(tmp_path, version)
    owner = task.bind(FIRST)
    field = task.discover(owner, "Response curve")
    code, before = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0, before
    code, rejected = task.step("draft-declare-existing", "--declaration-id", "response", "--object-handle", owner,
                               "--field-value", field, json.dumps(value))
    assert code == 2, rejected
    code, after = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0 and after["draft"] == before["draft"], after


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_inline_curve_class_scoped_field_reaches_a_new_recursive_set_node(tmp_path: Path, version: str) -> None:
    task = InlineCurveTask(tmp_path, version)
    task.objects[FIRST].update({"name": "Weather", "type": "PropertyContainer" if version == "2025.1" else "ActorMixer",
                                "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather"})
    owner = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--semantic-kind", "sound-sfx", "--meaning", "Response curve")
    assert code == 0, discovered
    field = discovered["meaning_results"][0]["candidates"][0]["handle"]
    code, declared = task.step("draft-declare-new", "--declaration-id", "rain", "--parent-handle", owner,
        "--name", "Rain", "--kind", "sound-sfx", "--field-value", field, json.dumps({"curve_points": POINTS}))
    assert code == 0, declared
    tx, shown = task.preview()
    prepared = shown["artifact"]["prepared_operation"]
    assert prepared["dispatch"]["args"]["objects"][0]["children"][0]["@Curve"] == {"type": "Curve", "points": POINTS}
    assert prepared["pre_state"]["inline_curve_guards"][0]["scope"] == {"classId": 2}
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("points", ([], list(reversed(POINTS))))
def test_inline_curve_uses_generic_native_point_union_without_rtpc_specific_minimum_or_sorting(
    tmp_path: Path, version: str, points: list[dict[str, Any]],
) -> None:
    task = InlineCurveTask(tmp_path, version)
    owner = task.bind(FIRST)
    field = task.discover(owner, "Response curve")
    code, declared = task.step("draft-declare-existing", "--declaration-id", "response", "--object-handle", owner,
                               "--field-value", field, json.dumps({"curve_points": points}))
    assert code == 0, declared
    tx, shown = task.preview()
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"]["objects"][0]["@Curve"]["points"] == points
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_inline_curve_omitted_metadata_identity_keeps_exact_binding_provenance(tmp_path: Path, version: str) -> None:
    task = InlineCurveTask(tmp_path, version)
    task.metadata["Curve"].pop("name")
    task.metadata["Curve"].pop("type")
    code, declared = declare_curve(task)
    assert code == 0, declared
    tx, shown = task.preview()
    proof = shown["artifact"]["prepared_operation"]["pre_state"]["inline_curve_guards"][0]
    assert proof["metadata"]["raw"] == task.metadata["Curve"]
    assert proof["metadata"]["field_binding"] == {"source": "exact_scoped_getPropertyAndReferenceNames", "token": "Curve"}
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified


@pytest.mark.parametrize("version", VERSIONS)
def test_create_discovery_and_declaration_do_not_admit_set_only_inline_curve_values(tmp_path: Path, version: str) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.create")
    task.metadata["Curve"] = {"name": "Curve", "type": "Reference", "display": {"name": "Response curve"},
        "restriction": {"type": "reference", "restrictions": [{"type": ["Curve"]}]}}
    owner = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--semantic-kind", "actor-mixer", "--meaning", "Response curve")
    assert code == 0, discovered
    candidate = discovered["meaning_results"][0]["candidates"][0]
    assert "json_curve_points" not in candidate["value_input"]["accepted_forms"]
    code, rejected = task.step("draft-declare-new", "--declaration-id", "weather", "--parent-handle", owner,
        "--name", "Layers", "--kind", "actor-mixer", "--field-value", candidate["handle"], json.dumps({"curve_points": POINTS}))
    assert code == 2 and rejected["error_code"] == "NATIVE_VALUE_UNION_UNAVAILABLE", rejected
    assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)


def test_2021_set_catalog_boundary_does_not_disclose_an_unavailable_curve_lane(tmp_path: Path) -> None:
    from tests.unit.test_object_graph_business_gateway import _offline
    code, rejected = _offline(tmp_path, "draft-start", "object.set", version="2021.1")
    assert code == 2 and rejected["error_code"] == "UNAVAILABLE_IN_VERSION", rejected
