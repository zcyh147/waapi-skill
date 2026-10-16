"""Source-guided classic-create probe; not public Gateway or Fresh evidence.

2021.1 object.create accepts a type name from Wwise Objects Reference, but no
classId argument. The matching installed SDK's waapi_import.html does not list
Effect creation as prohibited. Test the exact live catalog name once, in the
existing owned lifecycle; never guess another encoding after rejection.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle
from wwise_waapi.builders.schema import SemanticSchemaValidator

pytestmark = [pytest.mark.live, pytest.mark.destructive]


def test_2021_classic_create_effect_shareset_feasibility():
    version = os.environ["WWISE_VERSION"]
    if version != "2021.1":
        pytest.skip("classic ShareSet feasibility is scoped to 2021.1")
    root_text = os.environ.get("WAAPI_SHARESET_2021_PROBE_ROOT")
    if not root_text:
        pytest.skip("requires a new explicit WAAPI_SHARESET_2021_PROBE_ROOT")
    root = Path(root_text)
    assert root.is_absolute()
    private_home = root / "owned" / "wwise-user-home" if sys.platform == "darwin" else None
    prefix = private_home / "Library/Application Support/Wwise2019/Bottles/Wwise2019x64" if private_home else None
    lifecycle = ScenarioLifecycle(
        scenario_id="shareset-classic-create-2021.1", version=version,
        scenario_root=root, live_environment=dict(os.environ),
        launch_environment_overrides={"HOME": str(private_home)} if private_home else None,
        owned_wine_prefix=prefix,
    )
    runtime = actor = None
    status, reason = "FAIL", "classic ShareSet create did not complete"
    evidence = {"kind": "native-classic-create-feasibility", "version": version,
                "public_gateway_pass": False, "agent_semantic_pass": False,
                "source_pages": ["Wwise SDK 2021.1.14/ak_wwise_core_object_create.html",
                                 "Wwise SDK 2021.1.14/waapi_import.html",
                                 "Wwise SDK 2021.1.14/wobjects_index.html"]}
    try:
        runtime = lifecycle.start()
        actor = OwnedDirectWaapiCall(host=runtime.host, port=runtime.port)
        catalog = actor("ak.wwise.core.object.getTypes", {}, {})["return"]
        matches = [row for row in catalog if row["name"] == "Wwise Gain" and row["type"] == "Effect"]
        assert len(matches) == 1, matches
        selected = matches[0]
        parents = actor("ak.wwise.core.object.get", {"from": {"path": [r"\Effects\Default Work Unit"]}},
                        {"return": ["id", "type", "path"]})["return"]
        assert len(parents) == 1 and parents[0]["type"] == "WorkUnit", parents
        parent = parents[0]
        arguments = {"parent": parent["id"], "type": selected["name"],
                     "name": "WAAPI_Classic_ShareSet_Probe", "onNameConflict": "fail"}
        validator = SemanticSchemaValidator(version=version)
        schema = validator.schema_for("ak.wwise.core.object.create")
        evidence.update(selected_live_type=selected, parent=parent, request=arguments,
                        reflected_schema_sha256=hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
                        schema_validation=validator.validate("ak.wwise.core.object.create", arguments, {}).as_dict())
        result = actor("ak.wwise.core.object.create", arguments, {})
        evidence["native_result"] = result
        rows = actor("ak.wwise.core.object.get", {"from": {"id": [result["id"]]}},
                     {"return": ["id", "name", "type", "classId", "parent", "path"]})["return"]
        evidence["independent_readback"] = rows
        assert len(rows) == 1 and rows[0]["id"] == result["id"]
        row = rows[0]
        actual_parent = row["parent"]
        assert (actual_parent["id"] if isinstance(actual_parent, dict) else actual_parent) == parent["id"]
        assert row["classId"] == selected["classId"]
        assert row["name"] == arguments["name"] and row["type"] in {"Effect", "EffectPlugin"}
        status, reason = "PASS", "classic create with exact live plugin name produced independently verified ShareSet"
    except BaseException as exc:
        reason = f"{type(exc).__name__}: {exc}"
        evidence["error"] = reason
        raise
    finally:
        actor_closed = True
        if actor is not None:
            evidence["native_calls"] = actor.calls
            try:
                actor_closed = actor.close() and actor.fully_closed
            except BaseException as exc:
                actor_closed = False
                evidence["actor_close_error"] = str(exc)
            if not actor_closed:
                status, reason = "BLOCKED", "owned native actor did not close"
        if runtime is not None:
            (runtime.evidence_root / "shareset-classic-create.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            finished = lifecycle.finish(status, reason="" if status == "PASS" else reason)
            assert finished.final_status == status and actor_closed, finished.as_dict()
