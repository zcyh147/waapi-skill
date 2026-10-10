"""Public attenuation declarations disclose the same closed values they accept."""

from __future__ import annotations

import json

import pytest

from tests.unit.test_core_business_gateway import (
    FakeClient, SOURCE_ID, _env, _info, _project, gateway,
)

URI = "ak.wwise.core.object.setAttenuationCurve"
VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
BASE_KINDS = {"volume-dry", "volume-wet-game", "volume-wet-user", "low-pass-filter",
              "high-pass-filter", "spread", "focus"}
SHAPES = ["constant", "exp-1", "exp-2", "exp-3", "inverted-s-curve",
          "linear", "log-1", "log-2", "log-3", "s-curve"]


@pytest.mark.parametrize("version", VERSIONS)
def test_public_curve_schema_discloses_versioned_choices_and_point_constraints(tmp_path, version):
    code, result = gateway.execute_gateway(
        ["--version", version, "request-schema", URI], env=_env(tmp_path),
        client_factory=lambda _: pytest.fail("offline schema connected"))
    assert code == 0, result
    domains = result["business_adapter"]["declaration"]["value_domains"]
    kinds = domains["curve_kind"]["choices"]
    assert BASE_KINDS <= set(kinds)
    assert len(kinds) == {"2021.1": 7, "2022.1": 19, "2023.1": 19, "2024.1": 19, "2025.1": 24}[version]
    assert ("high-shelf" in kinds) is (version == "2025.1")
    assert domains["curve_source"]["choices"] == (["custom", "none", "volume-dry"]
        if version == "2021.1" else ["custom", "none", "project", "volume-dry"])
    assert domains["points"] == {
        "maximum_items": 64, "custom_minimum_items": 1, "non_custom_items": 0,
        "item_fields": ["x", "y", "shape"], "coordinates": "finite_numbers",
        "shape_choices": SHAPES, "order": "preserve_supplied_order",
    }
    assert "VolumeDryUsage" not in json.dumps(domains)


def _bound_curve(tmp_path, version):
    env = _env(tmp_path)
    env.update(WWISE_VERSION=version, WWISE_WAAPI_HOST="127.0.0.1", WWISE_WAAPI_PORT="31337")
    prefix = ["--version", version, "--state-dir", str(tmp_path / "state")]
    code, started = gateway.execute_gateway([*prefix, "draft-start", URI], env=env,
        client_factory=lambda _: pytest.fail("offline start connected"))
    assert code == 0, started
    info = _info()
    info["version"].update(year=int(version[:4]), displayName=f"v{version}.0.1")
    project = _project(tmp_path)
    identity = {"id": SOURCE_ID, "name": "Distance", "type": "Attenuation",
                "path": r"\Attenuations\Default Work Unit\Distance"}
    reads = ([{"return": [{**project, "type": "Project"}]}] if version == "2021.1" else [])
    reads.append({"return": [identity]})
    client = FakeClient({"ak.wwise.core.getInfo": [info],
        "ak.wwise.core.getProjectInfo": [project], "ak.wwise.core.object.get": reads})
    binding = [started["draft"]["draft_id"], "--task-authority", started["task_authority"]]
    code, bound = gateway.execute_gateway([*prefix, "draft-bind-object", *binding,
        "--expected-revision", "1", "--role", "attenuation", "--object-id", SOURCE_ID],
        env=env, client_factory=lambda _: client)
    assert code == 0, bound
    return env, prefix, binding, bound, info


@pytest.mark.parametrize("version", VERSIONS)
def test_bound_curve_continuation_keeps_public_domains_and_accepts_disclosed_linear(tmp_path, version):
    env, prefix, binding, bound, info = _bound_curve(tmp_path, version)
    continuation = bound["draft"]["next_action_binding"]["declaration"]
    assert continuation["append_fields"]["value_domains"]["points"]["shape_choices"] == SHAPES
    assert bound["draft"]["response_integrity"]["complete"] is True
    project = _project(tmp_path)
    client = FakeClient({"ak.wwise.core.getInfo": [info],
        "ak.wwise.core.getProjectInfo": [project],
        "ak.wwise.core.object.get": [{"return": [{**project, "type": "Project"}]}]})
    code, declared = gateway.execute_gateway([*prefix, "draft-declare-core-plan", *binding,
        "--expected-revision", "2", "--role", "attenuation_handle", bound["bound_object"]["handle"],
        "--value", "curve_kind", "volume-dry", "--value", "curve_source", "custom",
        "--curve-point", "0", "0", "linear", "--curve-point", "50", "-6", "linear"],
        env=env, client_factory=lambda _: client)
    assert code == 0, json.dumps(declared, ensure_ascii=False)
    assert declared["draft"]["response_integrity"]["complete"] is True
    assert not any(uri == URI for uri, _, _ in client.calls)


@pytest.mark.parametrize("version", VERSIONS)
def test_every_disclosed_curve_choice_materializes_through_public_declaration(tmp_path, version):
    env, prefix, binding, bound, info = _bound_curve(tmp_path, version)
    domains = bound["draft"]["next_action_binding"]["declaration"]["append_fields"]["value_domains"]
    cases = [(kind, "custom", "linear") for kind in domains["curve_kind"]["choices"]]
    cases += [("volume-dry", source, "linear") for source in domains["curve_source"]["choices"]]
    cases += [("volume-dry", "custom", shape) for shape in SHAPES]
    revision = 2
    for kind, source, shape in cases:
        project = _project(tmp_path)
        client = FakeClient({"ak.wwise.core.getInfo": [info],
            "ak.wwise.core.getProjectInfo": [project],
            "ak.wwise.core.object.get": [{"return": [{**project, "type": "Project"}]}]})
        points = ["--curve-point", "0", "0", shape] if source == "custom" else []
        code, result = gateway.execute_gateway([*prefix, "draft-declare-core-plan", *binding,
            "--expected-revision", str(revision), "--role", "attenuation_handle", bound["bound_object"]["handle"],
            "--value", "curve_kind", kind, "--value", "curve_source", source, *points],
            env=env, client_factory=lambda _: client)
        assert code == 0, (kind, source, shape, result)
        revision = result["draft"]["revision"]
        assert not any(uri == URI for uri, _, _ in client.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("source", ["none", "volume-dry", "project", "custom"])
def test_zero_point_transport_accepts_only_version_eligible_non_custom_sources(tmp_path, version, source):
    env, prefix, binding, bound, info = _bound_curve(tmp_path, version)
    project = _project(tmp_path)
    client = FakeClient({"ak.wwise.core.getInfo": [info],
        "ak.wwise.core.getProjectInfo": [project],
        "ak.wwise.core.object.get": [{"return": [{**project, "type": "Project"}]}]})
    code, result = gateway.execute_gateway([*prefix, "draft-declare-core-plan", *binding,
        "--expected-revision", "2", "--role", "attenuation_handle", bound["bound_object"]["handle"],
        "--value", "curve_kind", "volume-dry", "--value", "curve_source", source],
        env=env, client_factory=lambda _: client)
    if source == "custom":
        assert code == 2, result
        assert result["details"]["repair"]["error_code"] == "BUSINESS_FIELDS_CONFLICT"
    elif source == "project" and version == "2021.1":
        assert code == 2, result
        assert result["details"]["repair"]["error_code"] == "BUSINESS_ENUM_INVALID"
        assert "project" not in result["details"]["repair"]["choices"]
    else:
        assert code == 0, json.dumps(result)
    assert not any(uri == URI for uri, _, _ in client.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("field,value", [
    ("curve_kind", "VolumeDryUsage"), ("curve_kind", "dryVolume"),
    pytest.param("curve_kind", "unknown" * 1000, id="oversized-unknown"), ("curve_source", "Custom"),
    ("shape", "Linear"),
])
def test_invalid_curve_tokens_return_bounded_disclosed_choices_without_mutation(tmp_path, version, field, value):
    env, prefix, binding, bound, info = _bound_curve(tmp_path, version)
    project = _project(tmp_path)
    client = FakeClient({"ak.wwise.core.getInfo": [info],
        "ak.wwise.core.getProjectInfo": [project],
        "ak.wwise.core.object.get": [{"return": [{**project, "type": "Project"}]}]})
    code, result = gateway.execute_gateway([*prefix, "draft-declare-core-plan", *binding,
        "--expected-revision", "2", "--role", "attenuation_handle", bound["bound_object"]["handle"],
        "--value", "curve_kind", value if field == "curve_kind" else "volume-dry",
        "--value", "curve_source", value if field == "curve_source" else "custom",
        "--curve-point", "0", "0", value if field == "shape" else "linear"],
        env=env, client_factory=lambda _: client)
    assert code == 2, result
    repair = result["details"]["repair"]
    assert repair["error_code"] == "BUSINESS_ENUM_INVALID"
    assert repair["field"] == ("points[0].shape" if field == "shape" else field)
    domains = bound["draft"]["next_action_binding"]["declaration"]["append_fields"]["value_domains"]
    assert repair["choices"] == (SHAPES if field == "shape" else domains[field]["choices"])
    assert repair["draft_changed"] is False
    assert len(json.dumps(result).encode()) < 16 * 1024
    assert not any(uri == URI for uri, _, _ in client.calls)
