"""Exact product-branch receipts for the existing condition Gateway test lane."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

from tests.maintenance import branch_coverage_audit as audit


SHOW_BRANCH_ID = (
    "2025.1|installed|2025.1.7.9143|condition|existing-object|WObjects/WObjects.xml|"
    "PluginModule/WwiseObject[GameParameter]/Properties/Property[SlewRateUp]/Dependencies/142/condition"
)

_PROGRAM_CASES = {"slew-rate-show": {
    "branch_id": SHOW_BRANCH_ID, "public_uri": "ak.wwise.core.object.setProperty",
    "selector": "exact_bound_GameParameter_live_SlewRateUp_Field_Handle_value_37_with_RTPCRamping_0",
    "reason": "Exact installed existing-object Show condition: public mutation must preserve the controller and satisfy field readback.",
    "scalar": {"controller": "RTPCRamping", "controller_value": 0, "field": "SlewRateUp", "value": 37},
}}
for _version, _build, _index in (("2024.1", "2024.1.13.9056", 152), ("2025.1", "2025.1.7.9143", 164)):
    _PROGRAM_CASES[f"master-bus-device-{_version}"] = {
        "branch_id": f"{_version}|installed|{_build}|condition|existing-object|WObjects/WObjects.xml|"
                     f"PluginModule/WwiseObject[Bus]/Properties/Reference[AudioDevice]/Dependencies/{_index}/condition",
        "public_uri": "ak.wwise.core.object.setReference",
        "selector": "exact_bound_Bus_live_enabled_AudioDevice_Field_Handle_and_exact_chosen_AudioDevice_target",
        "reason": "Exact installed Bus.AudioDevice IsMasterBus=True occurrence: injected native-shaped Show metadata requires live enabled proof and a restricted exact AudioDevice target, without topology mutation. Native true-predicate metadata applicability remains unobserved.",
    }
for _version, _build in (("2022.1", "2022.1.19.8584"), ("2025.1", "2025.1.7.9143")):
    _PROGRAM_CASES[f"existing-bed-mixer-{_version}"] = {
        "branch_id": f"{_version}|installed|{_build}|plugin-condition|existing-object|Ak3DAudioBedMixer.xml|"
                     "PluginModule/EffectPlugin[Wwise 3D Audio Bed Mixer]/Properties/Property[SystemAudioObjectLimit]/Dependencies/0/condition",
        "public_uri": "ak.wwise.core.object.setProperty",
        "selector": "exact_bound_existing_Effect_live_Uint16_SystemAudioObjectLimit_Field_Handle_value_128_with_policy_1",
        "reason": "Exact installed existing-plugin condition, with sealed class-scoped metadata facts from this version: Uint16 SystemAudioObjectLimit requires SystemAudioObjectsPolicy in0/1. Injected existing-instance behavior preserves policy1. Native existing-instance/class applicability and effects remain unverified.",
        "scalar": {"controller": "SystemAudioObjectsPolicy", "controller_value": 1, "field": "SystemAudioObjectLimit", "value": 128},
    }
for _version, _build, _index in (("2021.1", "2021.1.14.8108", 4), ("2022.1", "2022.1.19.8584", 4),
        ("2023.1", "2023.1.19.8928", 4), ("2024.1", "2024.1.13.9056", 7), ("2025.1", "2025.1.7.9143", 7)):
    _PROGRAM_CASES[f"parent-weight-show-{_version}"] = {
        "branch_id": f"{_version}|installed|{_build}|condition|existing-object|WObjects/WObjects.xml|"
                     f"PluginModule/ObjectBase[Weight]/Properties/Property[Weight]/Dependencies/{_index}/condition",
        "public_uri": "ak.wwise.core.object.setProperty",
        "selector": "exact_bound_Sound_Weight_Field_Handle_value_37_with_parent_RandomOrSequence_0_unchanged",
        "reason": "Exact Parent Show occurrence: injected public mutation changes only Weight while parent RandomOrSequence remains0. Original exploratory native captures supply recorded metadata input facts only; they grant no final native category or Fresh acceptance credit.",
        "scalar": {"controller": "RandomOrSequence", "controller_value": 0, "field": "Weight", "value": 37},
    }
_PROGRAM_CASES["association-continue-play-2025.1"] = {
    "branch_id": "2025.1|installed|2025.1.7.9143|condition|existing-object|WObjects/WObjects.xml|"
                 "PluginModule/WwiseObject[ObjectSettingAssoc]/Properties/Property[ContinuePlay]/Dependencies/0/condition",
    "public_uri": "ak.wwise.core.object.setProperty",
    "selector": "exact_bound_ObjectSettingAssociation_ContinuePlay_Field_Handle_true_with_exact_SwitchContainer_owner_SwitchBehavior_1",
    "reason": "Exact AssocParent ContinuePlay condition. Retained2025 native read-only facts certify the observed relationship/value and source class metadata; owner typed metadata is explicitly an installed-definition model. Injected mutation verifies exact owner scope without owner writes. Native owner metadata, enabled applicability and mutation effects remain unverified; older native identities remain unresolved.",
    "scalar": {"controller": "SwitchBehavior", "controller_value": 1, "field": "ContinuePlay", "value": True},
}


def prepare_condition_capture(root: Path, nodeid: str, *, case_name: str = "slew-rate-show") -> dict:
    """Freeze exact source and branch facts before the public workflow executes."""
    root.mkdir(parents=True, exist_ok=False)
    inventory = audit.build_inventory()
    case = _PROGRAM_CASES[case_name]
    branch = next(row for row in inventory["native_coverage"]["obligations"] if row["id"] == case["branch_id"])
    assert branch["owner_issue"] == 177 and branch["business_dimensions"]["operation_mode"] == "existing-object"
    relevant = [
        str(path.relative_to(audit.ROOT))
        for directory in ("scripts", "wwise_waapi", "resources", "references")
        for path in sorted((audit.ROOT / "skills/waapi-skill" / directory).rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".json", ".md"}
    ]
    relevant.extend([
        "skills/waapi-skill/SKILL.md", "tests/support/condition_branch_evidence.py",
        "tests/unit/test_conditional_reference_gateway.py",
        "tests/destructive/test_condition_visibility_gateway.py",
        "tests/destructive/support/exact_real_evidence.py",
        "tests/destructive/support/category_evidence.py",
        "tests/conftest.py", "tests/support/exact_evidence_finalization.py",
        "tests/maintenance/branch_audit_completion.py", "tests/maintenance/branch_coverage_audit.py",
        "docs/branch-coverage-condition-sources.json",
        "tests/unit/test_existing_plugin_conditions_gateway.py",
        "tests/fixtures/metadata-conditions/3d-audio-bed-mixer.json",
        "tests/unit/test_parent_show_conditions_gateway.py",
        "tests/fixtures/metadata-conditions/parent-weight-show.json",
        "tests/unit/test_association_condition_product_gateway.py",
        "tests/fixtures/metadata-conditions/association-continue-play-2025.json",
    ])
    sources = {name: hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest() for name in sorted(set(relevant))}
    return {"root": root, "nodeid": nodeid, "branch": branch, "case": case,
            "public": next(row for row in inventory["routes"] if row["id"] == f'{branch["version"]}|function|{case["public_uri"]}'),
            "candidate_sha256": inventory["native_coverage"]["candidate_sha256"], "relevant_sources": sources,
            "git_candidate": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=audit.ROOT, text=True).strip()}


def finish_condition_capture(capture: dict, phase_reports: dict, observed: dict) -> None:
    """Write one original program result after pytest has reported its call."""
    root, branch = capture["root"], capture["branch"]
    unchanged = all(hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest() == seal
                    for name, seal in capture["relevant_sources"].items())
    unchanged = unchanged and subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=audit.ROOT, text=True).strip() == capture["git_candidate"]
    passed = all(phase_reports.get(phase) == "passed" for phase in ("setup", "call", "teardown")) and unchanged
    outcome = "PASS" if passed else "FAIL"
    case = capture.get("case", _PROGRAM_CASES["slew-rate-show"])
    binding = {"branch_id": branch["id"], "native_shape_sha256": branch["shape_sha256"],
        "public_route": capture["public"]["id"], "public_route_sha256": audit.digest(capture["public"]),
        "input": {"gateway_argv": observed.get("gateway", {}).get("argv", []),
                  "selector": case["selector"]},
        "construction": {"source": "skills/waapi-skill/wwise_waapi/operation_registry.py#_apply_reference_activation_dependencies", "selector": branch["pointer"]},
        "validation": {"source": "skills/waapi-skill/wwise_waapi/metadata_restrictions.py#condition_restriction", "selector": branch["pointer"]},
        "verifier": {"source": "skills/waapi-skill/wwise_waapi/operation_registry.py#verify_prepared_operation", "selector": branch["pointer"]},
        "native_hosts": ["wwise-console"],
        "observation_pointer": "/observations/wwise-console/metadata/dependencies/0",
        "gateway_observation_pointer": "/gateway/payload/agent_result",
        "relevant_sources": list(capture["relevant_sources"]), "evidence": {},
    }
    record = {"candidate_sha256": capture["candidate_sha256"], "scope_kind": "product",
        "evidence_kind": "injected_client_program", "git_candidate": capture["git_candidate"],
        "relevant_sources": capture["relevant_sources"],
        "invocation": {"phase": "final", "outcome": outcome,
                       "node_outcomes": [{"nodeid": capture["nodeid"], "outcome": outcome}]},
        **deepcopy(observed)}
    checks = [
        {"pointer": binding["observation_pointer"], "equals": observed.get("observations", {}).get("wwise-console", {}).get("metadata", {}).get("dependencies", [None])[0]},
        {"pointer": binding["gateway_observation_pointer"], "equals": observed.get("gateway", {}).get("payload", {}).get("agent_result")},
    ]
    if case["public_uri"].endswith("setReference"):
        snapshot = observed.get("observations", {}).get("wwise-console", {}).get("observations", [{}])[0]
        checks.extend([
            {"pointer": "/observations/wwise-console/observations/0/before/AudioDevice", "equals": None},
            {"pointer": "/observations/wwise-console/observations/0/after/AudioDevice/id", "equals": "{22222222-2222-2222-2222-222222222222}"},
            {"pointer": "/observations/wwise-console/observations/0/target_after", "equals": snapshot.get("target_before")},
            {"pointer": "/observations/wwise-console/observations/0/enabled_before", "equals": True},
            {"pointer": "/observations/wwise-console/observations/0/enabled_after", "equals": True},
        ])
    else:
        scalar = case["scalar"]
        checks.extend([
            {"pointer": "/observations/wwise-console/observations/0/controller_before/" + scalar["controller"], "equals": scalar["controller_value"]},
            {"pointer": "/observations/wwise-console/observations/0/controller_after/" + scalar["controller"], "equals": scalar["controller_value"]},
            {"pointer": "/observations/wwise-console/observations/0/after/" + scalar["field"], "equals": scalar["value"]},
        ])
    record["branch_assertions"] = {branch["id"]: {"native_shape_sha256": branch["shape_sha256"], "native_route": None, "checks": checks}}
    def write(name, value):
        path = root / name
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        return {"artifact": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    program_path = root / "program.json"
    program_bytes = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    descriptor = {"artifact": str(program_path), "sha256": hashlib.sha256(program_bytes).hexdigest()}
    binding["evidence"]["program"] = {**descriptor, "nodeid": capture["nodeid"]}
    write("bindings.json", {"contract": "waapi-skill.branch-bindings/v1", "bindings": {branch["id"]: binding}})
    write("requirements.json", {"contract": "waapi-skill.branch-evidence-requirements/v1", "branches": {
        branch["id"]: {"native_shape_sha256": branch["shape_sha256"], "categories": ["program", "native"],
            "reason": case["reason"] + " Console native effect requires a new finalized original node observation; injected program behavior grants no native or Authoring applicability credit."}}})
    write("capture.json", {"contract": "waapi-skill.condition-program-capture/v1", "branch_id": branch["id"],
                           "candidate_sha256": capture["candidate_sha256"], "git_candidate": capture["git_candidate"],
                           "source_unchanged": unchanged, "outcome": outcome, "nodeid": capture["nodeid"],
                           "functional_coverage": "program_only_native_missing", "obligations_in_scope": 1})
    pending = root / ".program.pending"
    pending.write_bytes(program_bytes)
    pending.replace(program_path)
