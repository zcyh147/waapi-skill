"""Exact product-branch receipts for the existing condition Gateway test lane."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

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
                 "PluginModule/WwiseObject[ObjectSettingAssoc]/Properties/Property[ContinuePlay]/Dependencies/5/condition",
    "public_uri": "ak.wwise.core.object.setProperty",
    "selector": "exact_bound_ObjectSettingAssociation_ContinuePlay_Field_Handle_true_with_exact_SwitchContainer_owner_SwitchBehavior_1",
    "reason": "Exact AssocParent ContinuePlay condition. Retained2025 native read-only facts certify the observed relationship/value and source class metadata; owner typed metadata is explicitly an installed-definition model. Injected mutation verifies exact owner scope without owner writes. Native owner metadata, enabled applicability and mutation effects remain unverified; older native identities remain unresolved.",
    "scalar": {"controller": "SwitchBehavior", "controller_value": 1, "field": "ContinuePlay", "value": True},
}

for _version, _build, _index in (("2021.1", "2021.1.14.8108", 152), ("2022.1", "2022.1.19.8584", 156),
        ("2023.1", "2023.1.19.8928", 135), ("2024.1", "2024.1.13.9056", 141), ("2025.1", "2025.1.7.9143", 142)):
    _PROGRAM_CASES[f"slew-rate-show-{_version}"] = {
        **deepcopy(_PROGRAM_CASES["slew-rate-show"]),
        "branch_id": f"{_version}|installed|{_build}|condition|existing-object|WObjects/WObjects.xml|"
                     f"PluginModule/WwiseObject[GameParameter]/Properties/Property[SlewRateUp]/Dependencies/{_index}/condition",
    }

for _version, _build, _index in (("2021.1", "2021.1.14.8108", 160), ("2025.1", "2025.1.7.9143", 150)):
    _PROGRAM_CASES[f"time-modulator-range-{_version}"] = {
        "branch_id": f"{_version}|installed|{_build}|condition|existing-object|WObjects/WObjects.xml|"
                     f"PluginModule/WwiseObject[ModulatorTime]/Properties/Property[EnvelopeStopPlayback]/Dependencies/{_index}/condition",
        "public_uri": "ak.wwise.core.object.setProperty",
        "selector": "exact_bound_existing_modeled_ModulatorTime_EnvelopeStopPlayback_Field_Handle_false_with_TimeModLoops_50",
        "reason": "Exact installed range1..100 condition with sealed version-matching class metadata. Injected public workflow preserves50; endpoints, invalid0, explicit staged repair and available atomic repair are covered. Instance identity and controller metadata are explicitly modeled from installed definitions, not native observations. Native instance applicability, enabled behavior and mutation effects remain unverified.",
        "scalar": {"controller": "TimeModLoops", "controller_value": 50, "field": "EnvelopeStopPlayback", "value": False},
    }


def prepare_condition_capture(root: Path, nodeid: str, *, case_name: str = "slew-rate-show", create_output: bool = True,
                              inventory: dict | None = None) -> dict:
    """Freeze exact source and branch facts before the public workflow executes."""
    if create_output:
        root.mkdir(parents=True, exist_ok=False)
    inventory = audit.build_inventory() if inventory is None else inventory
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
        "tests/destructive/support/condition_finalization.py",
        "tests/destructive/support/sandbox_fixture.py",
        "tests/destructive/support/live_environment.py",
        "tests/semantic/support/codex_scenario_lifecycle_v3.py",
        "tests/semantic/support/codex_campaign.py",
        "tests/semantic/support/codex_filesystem_security.py",
        "tests/unit/test_condition_native_finalization.py",
        "tests/conftest.py", "tests/support/exact_evidence_finalization.py",
        "tests/maintenance/branch_audit_completion.py", "tests/maintenance/branch_coverage_audit.py",
        "docs/branch-coverage-condition-sources.json",
        "tests/unit/test_existing_plugin_conditions_gateway.py",
        "tests/fixtures/metadata-conditions/3d-audio-bed-mixer.json",
        "tests/unit/test_parent_show_conditions_gateway.py",
        "tests/fixtures/metadata-conditions/parent-weight-show.json",
        "tests/unit/test_association_condition_product_gateway.py",
        "tests/fixtures/metadata-conditions/association-continue-play-2025.json",
        "tests/unit/test_condition_native_evidence.py",
        "tests/unit/test_time_modulator_range_gateway.py",
        "tests/fixtures/metadata-conditions/time-modulator-range.json",
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


def prepare_condition_native_capture(root: Path, nodeid: str, version: str, relation: str) -> dict:
    """Freeze a new exact original producer; never create the lifecycle root."""
    if relation not in {"Self", "Parent"}:
        raise ValueError("unsupported original condition probe")
    expected_node = ("tests/destructive/test_condition_visibility_gateway.py::"
                     f"test_show_visibility_does_not_change_native_prerequisite[{relation}]")
    if nodeid != expected_node or root.exists():
        raise ValueError("native capture needs the exact original node and a fresh output")
    case = f"slew-rate-show-{version}" if relation == "Self" else f"parent-weight-show-{version}"
    capture = prepare_condition_capture(root, nodeid, case_name=case, create_output=False)
    # Native category receipts identify a Git object. Working bytes must be that
    # object, rather than an uncommitted approximation of the candidate.
    subprocess.run(["git", "ls-files", "--error-unmatch", "--", *capture["relevant_sources"]],
                   cwd=audit.ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", *capture["relevant_sources"]],
                   cwd=audit.ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {**capture, "relation": relation, "scope_kind": "product"}


def publish_condition_native_capture(capture: dict, category: dict, observation_path: Path) -> None:
    """Atomically publish one original finalized category and exact branch wrapper.

    Invoked only from the existing post-teardown producer. It does not consume
    historical category logs, approve source equivalence, or grant family credit.
    """
    root, branch, nodeid = capture["root"], capture["branch"], capture["nodeid"]
    invocation = category["invocation"]
    if (category.get("contract") != "waapi-skill.host-category-evidence/v3"
            or invocation.get("phase") != "final" or invocation.get("outcome") != "PASS"
            or invocation.get("selected_test_nodeids") != [nodeid]
            or invocation.get("node_outcomes") != [{"nodeid": nodeid, "outcome": "PASS"}]):
        raise ValueError("native wrapper requires the exact finalized PASS node")
    if category["candidate"] != capture["git_candidate"]:
        raise ValueError("native original candidate differs from frozen source")
    validate_condition_frozen_source(capture)
    observation_bytes = observation_path.read_bytes()
    observation = json.loads(observation_bytes)
    host = category["host"]
    native_version = host["version"]
    build = ".".join(str(native_version[key]) for key in ("year", "major", "minor", "build"))
    if (category["version"] != branch["version"] or build != branch["build"]
            or host["is_command_line"] is not True or observation["host"]["isCommandLine"] is not True
            or observation["host"]["version"] != native_version
            or observation["candidate"] != capture["git_candidate"] or observation["version"] != branch["version"]):
        raise ValueError("native exact host/build/candidate mismatch")
    descriptor = {"artifact": str(observation_path.resolve()), "sha256": hashlib.sha256(observation_bytes).hexdigest()}
    if (len(category["categories"]) != 1 or category["categories"][0].get("observation") != descriptor
            or category["categories"][0].get("status") != "PASS"):
        raise ValueError("native original observation link mismatch")
    scalar = capture["case"]["scalar"]
    field, controller = scalar["field"], scalar["controller"]
    if (observation["field"] != field or observation["prerequisite"] != controller
            or observation["relation"] != capture["relation"]):
        raise ValueError("native original field/context mismatch")
    metadata = observation["metadata"]
    dependencies = metadata["dependencies"]
    relevant = [(index, row) for index, row in enumerate(dependencies) if row.get("action") == "Show"
                and row.get("context") == capture["relation"] and row.get("property") == controller]
    if len(relevant) != 1:
        raise ValueError("native exact Show metadata occurrence missing")
    index, dependency = relevant[0]
    prefix = "/observations/wwise-console"
    observation_pointer = f"{prefix}/metadata/dependencies/{index}"
    checks = [{"pointer": observation_pointer, "equals": dependency}]
    if len(observation["observations"]) != 2:
        raise ValueError("native Show probe needs both original controller states")
    for index, row in enumerate(observation["observations"]):
        before, after = row["controller_before"], row["controller_after"]
        actual = row["after"][field]
        if (type(row["mode"]) is not int or row["mode"] != index
                or type(before[controller]) is not int or before[controller] != index or before != after
                or type(actual) not in {int, float} or actual != 37 + index
                or type(row["requested_value"]) is not int or row["requested_value"] != 37 + index
                or type(row["is_property_enabled"]["return"]) is not bool
                or row["metadata_before"] != metadata or row["metadata_after"] != metadata
                or {k: v for k, v in row["before"].items() if k != field} !=
                   {k: v for k, v in row["after"].items() if k != field}):
            raise ValueError("native exact readback/controller preservation mismatch")
        row_pointer = f"{prefix}/observations/{index}"
        checks.extend([
            {"pointer": f"{row_pointer}/after/{field}", "equals": actual},
            {"pointer": f"{row_pointer}/before", "equals": row["before"]},
            {"pointer": f"{row_pointer}/after", "equals": row["after"]},
            {"pointer": f"{row_pointer}/controller_before", "equals": before},
            {"pointer": f"{row_pointer}/controller_after", "equals": before},
            {"pointer": f"{row_pointer}/is_property_enabled", "equals": row["is_property_enabled"]},
            {"pointer": f"{row_pointer}/metadata_before", "equals": metadata},
            {"pointer": f"{row_pointer}/metadata_after", "equals": metadata},
        ])
    if root.exists():
        raise ValueError("native output already exists; original evidence is immutable")
    root.parent.mkdir(parents=True, exist_ok=True)
    # Stage sibling files so the category and wrapper become visible together.
    # Failed stages are retained for diagnosis and never have an accepted path.
    pending = Path(tempfile.mkdtemp(prefix=f".{root.name}-pending-", dir=root.parent))
    def write(name, value):
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        (pending / name).write_bytes(payload)
        return {"artifact": str((root / name).resolve()), "sha256": hashlib.sha256(payload).hexdigest()}
    category_descriptor = {**write("category.json", category), "nodeid": nodeid,
                           "observation_sha256": [descriptor["sha256"]]}
    source_descriptor = write("sources.json", {"contract": "waapi-skill.condition-native-source-capture/v1",
          "git_candidate": capture["git_candidate"], "candidate_sha256": capture["candidate_sha256"],
          "relevant_sources": capture["relevant_sources"], "source_unchanged": True,
          "native_host": host, "branch_id": branch["id"], "native_shape_sha256": branch["shape_sha256"]})
    record = {"candidate_sha256": capture["candidate_sha256"], "scope_kind": capture["scope_kind"],
              "evidence_kind": "native_execution", "git_candidate": capture["git_candidate"],
              "invocation": invocation, "native_runs": [category_descriptor], "artifacts": [source_descriptor],
              "observation_artifacts": {"wwise-console": descriptor},
              "branch_assertions": {branch["id"]: {"native_shape_sha256": branch["shape_sha256"],
                                                     "native_route": branch["route"], "checks": checks}}}
    native_descriptor = {**write("native.json", record), "nodeid": nodeid}
    write("native-link.json", {"branch_id": branch["id"], "native_shape_sha256": branch["shape_sha256"],
          "native_hosts": ["wwise-console"], "observation_pointer": observation_pointer,
          "native_observations_sha256": {"wwise-console": descriptor["sha256"]},
          "evidence": {"native": native_descriptor}, "native_equivalence": {},
          "relevant_sources": list(capture["relevant_sources"]), "source_capture": source_descriptor,
          "status": "original_native_only_source_equivalence_review_required"})
    if observation_path.read_bytes() != observation_bytes:
        raise ValueError("original native observation changed before publication")
    pending.rename(root)


def validate_condition_frozen_source(capture: dict) -> None:
    """Require the original source seal again before destructive cleanup."""
    if (not capture["relevant_sources"] or any(
            hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest() != seal
            for name, seal in capture["relevant_sources"].items())
            or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=audit.ROOT, text=True).strip() != capture["git_candidate"]):
        raise ValueError("native frozen source changed")
