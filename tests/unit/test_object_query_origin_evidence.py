"""Public query-plan storage keeps request and origin evidence budgets separate."""
import json
import time

import pytest

from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
from wwise_waapi.object_query_result_pages import (ObjectQueryPlanStore,
    QueryResultPageError, QueryResultProjectionLimitError, MAX_QUERY_REQUEST_BYTES,
    MAX_QUERY_BASE_RECORD_BYTES, MAX_QUERY_ORIGIN_EVIDENCE_BYTES)


def read_evidence():
    # Storage-shape fixture only; never executed or credited as a native packet.
    return {'api':'ak.wwise.core.object.get','args':{'waql':'from type Sound take 1'},
        'options':{'return':['id']},'result_sha256':canonical_sha256({'return':[]}),
        'call':{'evidence_path':'origin-packet.json'}}


def test_existing_argv_only_plan_remains_valid_and_origin_data_does_not_consume_argv_budget(tmp_path):
    store = ObjectQueryPlanStore(tmp_path)
    argv = ['query-object','--include','notes']
    original = store.issue(plan={'argv':argv}, context={'session':'test'}, issued=int(time.time()))
    assert store.resolve(original)['plan'] == {'argv':argv}
    evidence = read_evidence()
    evidence['call']['message'] = 'x' * (MAX_QUERY_REQUEST_BYTES + 1)
    plan = {'argv':argv,'origin_related_read_evidence':[evidence]}
    handle = store.issue(plan=plan,context={'session':'test'},issued=int(time.time()))
    assert store.resolve(handle)['plan'] == plan
    assert len(canonical_json_bytes(plan['origin_related_read_evidence'])) > MAX_QUERY_REQUEST_BYTES
    assert store.MAX_RECORD_BYTES == store.MAX_TOTAL_BYTES == 16 * 1024 * 1024


@pytest.mark.parametrize('part',['request','context','evidence'])
def test_query_plan_rejects_each_independent_capacity_without_truncating(tmp_path,part):
    store = ObjectQueryPlanStore(tmp_path)
    plan,context = {'argv':['query-object']},{'session':'test'}
    if part == 'request': plan['argv'].append('x' * MAX_QUERY_REQUEST_BYTES)
    elif part == 'context': context['large'] = 'x' * MAX_QUERY_BASE_RECORD_BYTES
    else:
        evidence = read_evidence()
        evidence['call']['message'] = 'x' * MAX_QUERY_ORIGIN_EVIDENCE_BYTES
        plan['origin_related_read_evidence'] = [evidence]
    with pytest.raises(QueryResultProjectionLimitError):
        store.issue(plan=plan,context=context,issued=int(time.time()))
    assert not list(tmp_path.rglob('oq1-*.json'))


def test_origin_evidence_uses_existing_total_store_quota(tmp_path):
    store = ObjectQueryPlanStore(tmp_path)
    evidence = read_evidence()
    evidence['call']['message'] = 'x' * (9 * 1024 * 1024)
    plan = {'argv':['query-object'],'origin_related_read_evidence':[evidence]}
    store.issue(plan=plan,context={},issued=int(time.time()))
    with pytest.raises(QueryResultProjectionLimitError):
        store.issue(plan=plan,context={},issued=int(time.time()))
    assert len(list(tmp_path.rglob('oq1-*.json'))) == 1


def test_resolve_enforces_original_base_context_budget_after_record_is_changed(tmp_path):
    store = ObjectQueryPlanStore(tmp_path)
    handle = store.issue(plan={'argv':['query-object']},context={},issued=int(time.time()))
    path = store.root/(handle+'.json')
    record = json.loads(path.read_text())
    record['context']['large'] = 'x' * MAX_QUERY_BASE_RECORD_BYTES
    record.pop('sha256')
    record['sha256'] = canonical_sha256(record)
    path.write_text(json.dumps(record))
    with pytest.raises(QueryResultPageError): store.resolve(handle)
