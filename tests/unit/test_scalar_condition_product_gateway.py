"""Actual public Gateway workflows for predeclared exact source field models."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST
from tests.unit.test_time_modulator_range_gateway import finish


def run_scalar_public_workflow(path, group, *, before_values=None, capture_scope=False):
    path.mkdir()
    model = group["model"]
    task = ScalarPropertyTask(path, group["version"])
    if 'source_receiver' in model:
        task.objects[FIRST]['type'] = model['source_receiver']['native_type']
    task.metadata = deepcopy(model["metadata"])
    task.objects[FIRST].update(deepcopy(model["before"] if before_values is None else before_values))
    target = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--object-handle", target, "--meaning", group["field"])
    assert code == 0, discovered
    candidates = [row for row in discovered["meaning_results"][0]["candidates"]
                  if row["metadata"].get("name") == group["field"]]
    assert len(candidates) == 1, discovered
    candidate = candidates[0]
    assert candidate["metadata"] == model["metadata"][group["field"]]
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
        "--field-handle", candidate["handle"], "--business-value", _business_value(model["requested"]))
    assert code == 0, declared
    before = deepcopy(task.objects[FIRST])
    preview, code, verified, transaction = finish(task)
    assert not preview["preview_summary"].get("derived_changes"), preview
    after = deepcopy(task.objects[FIRST])
    assert after == {**before, group["field"]: model["requested"]}
    writes = [{"uri": uri, "args": args, "options": options} for uri, args, options in task.calls
              if uri.endswith(("setProperty", "setReference", "object.set"))]
    assert len(writes) == 1
    assert writes[0]["args"] == {"object": FIRST, "property": group["field"], "value": model["requested"]}
    result = {"gateway": {"argv": ["--state-dir", str(path / "state"), "verify", transaction],
                        "exit_code": code, "payload": verified},
            "native_call": writes[0], "observations": {"metadata": deepcopy(candidate["metadata"]),
                "before": before, "after": after}, "input_fact_provenance": deepcopy(model["provenance"])}
    if capture_scope:
        result['object_scope_call_trace'] = [{'uri': uri, 'args': deepcopy(args), 'options': deepcopy(options)}
                                             for uri, args, options in task.calls]
    return result


def _business_value(value):
    # The public string contract takes literal text; numeric/Boolean values use JSON.
    return value if isinstance(value, str) else json.dumps(value)


def run_scalar_public_group(path, group, *, observed=None, capture_scope=False):
    path.mkdir()
    if observed is None:
        observed = {"workflows": {}, "negative_controls": {}}
    for flow in group["workflows"]:
        options = {"before_values": flow["before"]}
        if capture_scope:
            options["capture_scope"] = True
        observed["workflows"][flow["id"]] = run_scalar_public_workflow(path / flow["id"], group, **options)
    for control in group["negative_controls"]:
        child = path / control["id"]
        child.mkdir()
        task = ScalarPropertyTask(child, group["version"])
        if 'source_receiver' in group['model']:
            task.objects[FIRST]['type'] = group['model']['source_receiver']['native_type']
        task.metadata = deepcopy(group["model"]["metadata"])
        task.objects[FIRST].update(deepcopy(control["before"]))
        before = deepcopy(task.objects)
        target = task.bind(FIRST)
        field = task.discover(target, group["field"])
        code, declared = task.step("draft-declare-field-change", "--object-handle", target,
            "--field-handle", field, "--business-value", _business_value(group["model"]["requested"]))
        assert code == 0, declared
        code, checked = task.step("draft-check")
        assert code == 2 and control["expected_error_code"] in json.dumps(checked), checked
        assert task.objects == before
        assert not any(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls)
        observed["negative_controls"][control["id"]] = {
            "gateway": {"argv": ["--state-dir", str(child / "state"), "draft-check", task.draft,
                "--task-authority", task.authority, "--expected-revision", str(task.revision)], "exit_code": code, "payload": checked},
            "before": before[FIRST], "after": deepcopy(task.objects[FIRST]), "mutation_calls": []}
    return observed


def run_original_scalar_groups(path, groups, identities, observed):
    """Keep independent failures and completed public observations in the original node."""
    failures = {}
    for identity in identities:
        observed[identity] = {"workflows": {}, "negative_controls": {}}
        try:
            run_scalar_public_group(path / identity, groups[identity], observed=observed[identity])
        except Exception as error:
            failure = {"error_type": type(error).__name__,
                "message": str(error).encode('utf-8')[:4096].decode('utf-8', errors='ignore')}
            failures[identity] = failure
            observed[identity]['failure'] = failure
    return failures


# Explicit standalone original producer. Ordinary Program never runs this batch
# implicitly: a new evidence root and frozen selection are developer inputs.
@pytest.fixture(scope='session')
def original_scalar_program_batch(request):
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.condition_scalar_batch import scalar_manifest, scalar_plan
    from tests.support.condition_scalar_requirements import load_program_review
    from tests.support.condition_scalar_program import prepare_program_batch
    destination = os.environ.get('WAAPI_SCALAR_PROGRAM_BATCH_ROOT')
    if not destination:
        pytest.skip('original scalar program batch requires an explicit new evidence root')
    selection_path = os.environ.get('WAAPI_SCALAR_PROGRAM_SELECTION')
    if not selection_path:
        pytest.fail('original scalar program collection requires an explicit frozen selection file')
    selection = json.loads(Path(selection_path).read_text())
    nodes = list(request.session.items)
    if (not nodes or any(getattr(item, 'originalname', None) != 'test_product_self_scalar_source_conditions'
            or Path(item.path).resolve() != Path(__file__).resolve() for item in nodes)):
        pytest.fail('original scalar program collection is standalone-only; unrelated collected nodes are prohibited')
    versions = [item.callspec.params.get('version') for item in nodes]
    if (len(versions) != len(set(versions)) or any(version not in {'2021.1', '2022.1', '2023.1', '2024.1', '2025.1'} for version in versions)
            or os.environ.get('WWISE_LIVE') == '1' or os.environ.get('WWISE_DESTRUCTIVE') == '1'):
        pytest.fail('original scalar program collection requires exact non-live version nodes')
    root = Path(__file__).parents[2]
    plan = scalar_plan(scalar_manifest(root))
    assert set(selection) == {'contract', 'source_plan_sha256', 'group_ids'}
    assert selection['contract'] == 'waapi-skill.condition-scalar-program-selection/v1'
    assert selection['source_plan_sha256'] == audit.digest(plan)
    assert isinstance(selection['group_ids'], list) and all(isinstance(identity, str) for identity in selection['group_ids'])
    assert len(selection['group_ids']) == len(set(selection['group_ids']))
    selected = set(selection['group_ids'])
    assert selected and selected <= {group['id'] for group in plan['groups']}
    roster = {item.nodeid: [group['id'] for group in plan['groups']
        if group['version'] == item.callspec.params['version'] and group['id'] in selected] for item in nodes}
    assert all(roster.values()), 'each original scalar node must own an explicit selected group'
    assert selected == {identity for identities in roster.values() for identity in identities}
    output = Path(destination)
    assert output.is_absolute()
    inventory = audit.build_inventory()  # Once per frozen original batch.
    capture = prepare_program_batch(output, list(roster), plan, inventory, scope_kind='product',
        reviewed_requirements=load_program_review(root), node_groups=roster)
    return capture, {group['id']: group for group in plan['groups']}


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_product_self_scalar_source_conditions(tmp_path, request, version, original_scalar_program_batch):
    from tests.support.condition_scalar_program import finish_program_node
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    capture, groups = original_scalar_program_batch
    observed = {}
    register_exact_evidence_finalizer(request.node,
        lambda reports: finish_program_node(capture, request.node.nodeid, reports, observed))
    failures = run_original_scalar_groups(tmp_path, groups, capture['node_groups'][request.node.nodeid], observed)
    if failures:
        pytest.fail(f'{len(failures)} independent original scalar groups failed; first IDs: {list(failures)[:20]}; '
            'bounded diagnostics and completed observations retained by the original node finalizer')
