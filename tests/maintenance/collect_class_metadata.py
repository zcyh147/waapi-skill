#!/usr/bin/env python3
"""Closed class metadata schedule on the existing ScenarioLifecycle collector.

Promoted from the retained condition driver (79519eea464a89d165d8cc8bee6370deed24fa0e048adfaf0e7f3375a2b99136).
Same owned lifecycle/public subprocess/receipt flow; no agent or mutation lane.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[2]
BUILDS = {'2021.1': '2021.1.14.8108', '2022.1': '2022.1.19.8584',
          '2023.1': '2023.1.19.8928', '2024.1': '2024.1.13.9056', '2025.1': '2025.1.7.9143'}
# Each scope/field comes from matching retained actual metadata. These are
# collection expectations, never evidence or inherited cross-version results.
SCHEDULE = {
    '2021.1': {'ModulatorTime': {'EnvelopeStopPlayback': True}},
    '2022.1': {'Wwise Delay': {'DelayTime': 0.5, 'FeedbackEnabled': True},
               'Sound': {'BypassEffect0': False, 'Effect0': None}},
    '2023.1': {'Action': {'Scope': 0}, 'EffectSlot': {'Bypass': False, 'Effect': None}},
    '2024.1': {'Sound': {'AttenuationDistanceScaling': 1.0}, 'EffectSlot': {'Bypass': False, 'Effect': None}},
    '2025.1': {'Sound': {'Weight': 50.0}, 'EffectSlot': {'Bypass': False, 'Effect': None},
               'ModulatorTime': {'EnvelopeStopPlayback': True}, 'MediaPoolFilter': {'FieldName': ''}},
}
COMPLETION_SCHEDULE = {v:{'MusicStinger':{'CustomCueMatchName':''}, **({'ModulatorTime':{'EnvelopeStopPlayback':True}}
    if v in ('2023.1','2024.1') else {})} for v in ('2021.1','2022.1','2023.1','2024.1')}
# Matching installed primary declarations select reads, never replace native proof.
COMPLETION_PRIMARY_XML_SHA256 = {
    '2021.1':'6538b45e18ba6575b9172af100b18b876923ee2614ada38d80cff44e090b478d',
    '2022.1':'018ddcb9e0b50c4cdc2f0849d0cc8a95d5568c169f0c888ca6f07c3f0e3266b6',
    '2023.1':'bae4d5fdd821fef226f1939d34ba1810e08bf79578fb8edc4ae3bdc3c66bd468',
    '2024.1':'28c19c59fe681a9cb81e11cec8f80caea006274ea670dc1388966239d4ee8e7f'}
CLASS_IDS = {'MusicStinger':2490384, 'Sound':65552, 'Wwise Delay':6946819, 'Action':327696, 'EffectSlot':5505040,
             'ModulatorTime':5111824, 'MediaPoolFilter':5767184}
SELECTION_ORIGINS = {
    '2021.1':['condition-metadata-2021-r1:014 (ModulatorTime true)'],
    '2022.1':['r45-render-history-027ac095-2022-r1:body calls10/12/64/68'],
    '2023.1':['condition-metadata-2023-r1:007 (Action number)',
               'effect-slot-exact-4fac9727-2023-r1:body calls37/38 (unanchored selection only)'],
    '2024.1':['condition-metadata-2024-r1:006 (Sound number)',
               'effect-slot-exact-4fac9727-2024-r1:body calls37/38 (unanchored selection only)'],
    '2025.1':['condition-metadata-2025-r1:010/014/042 (number/true/empty string)',
               'effect-slot-exact-4fac9727-2025-r1:body calls37/38 (unanchored selection only)'],
}
MAX_CALLS, MAX_PAGES, PAGE_SIZE, MAX_BYTES = 48, 8, 64, 1_048_576
MAX_NATIVE_FILES, MAX_NATIVE_BYTES = 128, 32 * 1024 * 1024
MAX_SEALED_FILES, MAX_SEALED_BYTES = 512, 128 * 1024 * 1024
COLLECTION_SOURCE_SCOPES = ('skills/waapi-skill','tests/semantic/support','tests/support','tests/destructive/support')
STALE = {'METADATA_SELECTION_SCOPE_CHANGED', 'METADATA_SELECTION_EXPIRED'}
UNRESOLVED = {'METADATA_DETAIL_TOO_LARGE', 'LIVE_METADATA_LIMIT_EXCEEDED', 'DISCOVERY_RESULT_LIMIT_EXCEEDED'}

class HostFailure(ValueError):
    pass


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_build(info):
    version = info.get('version', {})
    return '.'.join(str(version.get(key)) for key in ('year','major','minor','build'))


def native_archive_entries(root):
    native=Path(root)/'dispatcher-evidence'
    if native.is_symlink() or native.exists() and not native.is_dir():
        raise HostFailure('Native dispatcher archive directory changed')
    paths=sorted(native.glob('*.json')) if native.exists() else []
    if (len(paths)>MAX_NATIVE_FILES or any(path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES for path in paths)
            or sum(path.stat().st_size for path in paths)>MAX_NATIVE_BYTES):
        raise HostFailure('Native dispatcher archive count/byte bound exceeded')
    return [{'path':path.relative_to(root).as_posix(),'sha256':sha(path),'bytes':path.stat().st_size} for path in paths]


def write_final_seal(root, scenario):
    """Publish only a complete archive within the portable reader's bounds."""
    paths=[path for path in sorted(root.rglob('*')) if path.is_file()
        and path.name not in {'gateway-config.json','evidence-seal.json'}
        and not path.is_relative_to(scenario) and not path.is_relative_to(root/'gateway-state')]
    if (len(paths)>MAX_SEALED_FILES or any(path.is_symlink() or path.stat().st_size>MAX_BYTES for path in paths)
            or sum(path.stat().st_size for path in paths)>MAX_SEALED_BYTES):
        raise HostFailure('Final sealed archive bound exceeded')
    files=[{'path':path.relative_to(root).as_posix(),'sha256':sha(path),'bytes':path.stat().st_size} for path in paths]
    (root/'evidence-seal.json').write_text(json.dumps(
        {'contract':'waapi-skill.class-metadata-seal/v1','files':files},ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def collection_plan(version, *, cohort='r54'):
    schedule = SCHEDULE if cohort == 'r54' else COMPLETION_SCHEDULE if cohort == 'r55' else {}
    if version not in schedule:
        raise ValueError('Unreviewed class metadata version')
    types = json.loads((REPO/'skills/waapi-skill/resources/metadata'/version/'object-types.json').read_bytes())
    expected = schedule[version]
    for scope in expected:
        rows = [row for row in types['types'] if row['name'] == scope]
        if len(rows) != 1 or rows[0]['classId'] != CLASS_IDS[scope]:
            raise ValueError('Pinned class identity changed')
    definition = '/resultSchema/@definition/'+('common_definitions.json' if version in ('2024.1','2025.1') else 'waapi_definitions.json')+'/definitions/propertyValue'
    pointers = ['/resultSchema/properties/default/@presence/present','/resultSchema/properties/default',
                '/resultSchema/properties/default/$ref',definition]
    values = [value for fields in expected.values() for value in fields.values()]
    if any(value is None for value in values):pointers += [definition+'/anyOf/0',definition+'/anyOf/0/@nullable']
    if any(type(value) in (int,float) for value in values):pointers += [definition+'/anyOf/2']
    if any(type(value) is bool for value in values):pointers += [definition+'/anyOf/3']
    for value in (False,True):
        if any(type(item) is bool and item is value for item in values):pointers += [definition+'/anyOf/3/@boolean/'+str(value).lower()]
    if any(type(value) is str for value in values):pointers += [definition+'/anyOf/1',definition+'/anyOf/1/@empty/string']
    if version == '2021.1':pointers = [definition+'/anyOf/3/@boolean/true'] # Nine other observed leaves already retained.
    if cohort == 'r55':
        pointers = [definition+'/anyOf/1',definition+'/anyOf/1/@empty/string']
        if version in ('2023.1','2024.1'):pointers += [definition+'/anyOf/3/@boolean/true']
    prefix = version+'|wwise-console|'+BUILDS[version]+'|function|ak.wwise.core.object.getPropertyInfo|'
    identities = sorted(prefix+pointer for pointer in pointers)
    requirements = json.loads((REPO/'docs/branch-coverage-requirements.json').read_bytes())['branches']
    if any(requirements.get(identity,{}).get('categories') != ['program','live_metadata'] for identity in identities):
        raise ValueError('Exact default requirement assignment changed')
    return {**({'cohort':'r55'} if cohort == 'r55' else {}),'kind':'class_metadata_only','agent_started':False,'project_mutation_commands':0,
        'version':version,'host':'wwise-console','build':BUILDS[version],
        'collector_nodeid':'tests/maintenance/collect_class_metadata.py::class_metadata'+('_completion' if cohort == 'r55' else '')+'['+version+']',
        'selection_origins_not_evidence':SELECTION_ORIGINS[version] if cohort == 'r54' else [
            'Matching primary WObjects.xml SHA256 '+COMPLETION_PRIMARY_XML_SHA256[version]+
            ': MusicStinger.CustomCueMatchName Type=string/empty DefaultValue'+
            ('; ModulatorTime.EnvelopeStopPlayback Type=bool/DefaultValue=true' if version in ('2023.1','2024.1') else '')],
        'targets':{scope:list(fields) for scope,fields in expected.items()},'expected_defaults':expected,
        'class_ids':{scope:CLASS_IDS[scope] for scope in expected},'eligible_branch_ids':identities,
        'limits':{'gateway_invocations':MAX_CALLS,'pages_per_scope':MAX_PAGES,'page_size':PAGE_SIZE,
                  'bytes_per_stream':MAX_BYTES,'gateway_seconds':30,'subprocess_seconds':45,
                  'native_files':MAX_NATIVE_FILES,'native_bytes':MAX_NATIVE_BYTES,
                  'sealed_files':MAX_SEALED_FILES,'sealed_bytes':MAX_SEALED_BYTES,'bytes_per_sealed_file':MAX_BYTES}}


def metadata_descriptors(root):
    root = Path(root)
    plan = json.loads((root/'plan.json').read_bytes())
    targets = json.loads((root/'targets.json').read_bytes())
    initial = json.loads((root/'initial-status.json').read_bytes())['receipt']
    seal = {'artifact':str(root/'evidence-seal.json'),'sha256':sha(root/'evidence-seal.json')}
    return {plan['version']+'|'+row['scope']+'|'+row['field']:
        {'contract':'waapi-skill.class-metadata-read/v1','root':str(root),'seal':dict(seal),
         'status_receipt':initial,'receipt':row['detail_receipt'],'target_index':index}
        for index,row in enumerate(targets) if row['status'] == 'captured'}


def source_links(version, targets):
    from tests.support.metadata_replay_branch_evidence import source_seals
    sources = source_seals()
    # One deduplicated exact closure for both capture and admission. Preserve
    # the original tracked scopes and the lifecycle's destructive support imports.
    tracked=subprocess.check_output(['git','ls-files','-z','--',*COLLECTION_SOURCE_SCOPES],cwd=REPO)
    for name in tracked.decode('utf-8').split('\0'):
        if name and name not in sources and (REPO/name).is_file():
            sources[name]=sha(REPO/name)
    for name in ('tests/maintenance/collect_class_metadata.py','tests/unit/test_class_metadata_collection.py'):
        sources[name] = sha(REPO/name)
    return [], [{'path':str(REPO/name),'sha256':value} for name,value in sorted(sources.items())]


def validate_native_detail(root, payload, version, scope, field, *, cohort='r54'):
    """Exact current public/native bytes; never manufacture a native response."""
    result = payload['agent_result']
    resolved = result['scope']
    if (result.get('complete') is not True or resolved.get('kind') != 'object_type'
            or resolved.get('requested') != scope or resolved['resolved'].get('name') != scope
            or resolved['resolved'].get('classId') != CLASS_IDS[scope]):
        raise HostFailure('Exact public class identity changed')
    dispatch, = [row for row in payload['calls'] if row['api'] == 'ak.wwise.core.object.getPropertyInfo']
    path = Path(dispatch['evidence_path'])
    boundary = (root/'dispatcher-evidence').resolve()
    if (path.is_symlink() or not path.resolve().is_relative_to(boundary)
            or not path.is_file() or path.stat().st_size > MAX_BYTES):
        raise HostFailure('Native dispatcher path/byte bound changed')
    raw = path.read_bytes()
    native = json.loads(raw,parse_constant=lambda value:(_ for _ in ()).throw(ValueError(value)))
    validate_native_pair(payload,native,version,scope,field,cohort=cohort)
    return {'native_receipt':path.relative_to(root).as_posix(),'native_path':str(path),'native_sha256':hashlib.sha256(raw).hexdigest(),
        'native_bytes':len(raw),'default_present':'default' in native['result'],
        **({'observed_default':native['result']['default']} if 'default' in native['result'] else {})}



def validate_native_pair(payload,native,version,scope,field,*,cohort='r54'):
    if field not in collection_plan(version,cohort=cohort)['targets'].get(scope,[]):
        raise HostFailure('Unreviewed native metadata scope/field')
    result = payload['agent_result']
    resolved = result['scope']
    if (result.get('complete') is not True or resolved.get('kind') != 'object_type'
            or resolved.get('requested') != scope or resolved['resolved'].get('name') != scope
            or resolved['resolved'].get('classId') != CLASS_IDS[scope]):
        raise HostFailure('Exact public class identity changed')
    dispatch, = [row for row in payload['calls'] if row['api'] == 'ak.wwise.core.object.getPropertyInfo']
    metadata = result['metadata']
    if (native['api'] != dispatch['api'] or native.get('ok') is not True or native.get('dry_run') is not False
            or native['version'] != version or native['result']['name'] != field
            or any(native.get(key) != value for key,value in dispatch.items())
            or json.dumps(native['result'],sort_keys=True,allow_nan=False) != json.dumps(
                {key:metadata[key] for key in native['result']},sort_keys=True,allow_nan=False)):
        raise HostFailure('Exact native/public metadata packet mismatch')

def collect_scope(gateway, version, scope, fields, root, status_check, *, cohort='r54'):
    if fields != collection_plan(version,cohort=cohort)['targets'].get(scope):
        raise HostFailure('Unreviewed class/field schedule')
    pages_used = 0
    # One explicit restart for a stale locator, never a blind write replay.
    for attempt in range(2):
        cursor = None
        seen_pages = set()
        seen_names = set()
        found = {}
        snapshot = None
        total = None
        scope_value = None
        expected_offset = 0
        unresolved_reason = None
        restart = False
        for page_number in range(MAX_PAGES):
            if pages_used >= MAX_PAGES:
                unresolved_reason = 'page_bound_reached'
                break
            pages_used += 1
            arguments = ['metadata','list','--custom-kind',scope,'--page-size',str(PAGE_SIZE)]
            if cursor is not None: arguments += ['--page',cursor]
            payload, receipt = gateway(arguments)
            if payload.get('error_code') in STALE:
                restart = True
                break
            if payload.get('ok') is not True:
                unresolved_reason = payload.get('error_code')
                break
            if payload.get('status') == 'needs_clarification':
                unresolved_reason = 'class_missing_or_ambiguous'
                break
            page = payload.get('agent_result')
            if not isinstance(page, dict) or page.get('mutation_authority') is not False:
                raise HostFailure('malformed/non-read-only metadata page')
            current = (page.get('snapshot'), page.get('scope'), page.get('total_count'))
            if page_number == 0:
                snapshot, scope_value, total = current
                if not isinstance(snapshot, str) or not snapshot or type(total) is not int or total < 0:
                    raise HostFailure('invalid metadata inventory identity')
            if current != (snapshot, scope_value, total) or page.get('offset') != expected_offset:
                raise HostFailure('metadata page scope/snapshot/count/offset drift')
            entries = page.get('fields')
            if not isinstance(entries, list) or len(entries) > PAGE_SIZE:
                raise HostFailure('invalid metadata fields')
            for item in entries:
                name, selection = item.get('name'), item.get('selection')
                if not isinstance(name, str) or not isinstance(selection, str) or not selection or name in seen_names:
                    raise HostFailure('malformed or duplicate listed field')
                seen_names.add(name)
                if name in fields: found[name] = (selection, receipt)
            expected_offset += len(entries)
            cursor = page.get('next_page')
            if type(page.get('complete')) is not bool or page.get('remaining_count') != total-expected_offset:
                raise HostFailure('metadata page completeness mismatch')
            if not cursor:
                if page['complete'] is not True or expected_offset != total:
                    raise HostFailure('metadata inventory terminated without completeness')
                break
            if page['complete'] or not isinstance(cursor,str) or cursor in seen_pages or not entries:
                raise HostFailure('invalid repeated metadata cursor')
            seen_pages.add(cursor)
            if len(found) == len(fields): break  # Targeted collection, not a whole-inventory claim.
        else:
            unresolved_reason = 'page_bound_reached'
        if restart:
            if attempt == 0:
                status_check()
                continue
            unresolved_reason = 'stale_locator_after_one_relist'
        pending = []
        for field in fields:
            if field not in found or unresolved_reason:
                pending.append({'scope':scope,'field':field,'status':'unresolved',
                    'reason':unresolved_reason or 'not_in_complete_live_class_inventory'})
                continue
            selection, list_receipt = found[field]
            payload, receipt = gateway(['metadata','detail','--custom-kind',scope,'--selection',selection])
            if payload.get('error_code') in STALE:
                restart = True
                break
            if payload.get('ok') is not True or payload.get('status') == 'needs_clarification':
                pending.append({'scope':scope,'field':field,'status':'unresolved',
                    'reason':payload.get('error_code') or 'class_missing_or_ambiguous','receipt':receipt})
                continue
            detail = payload.get('agent_result')
            if (not isinstance(detail,dict) or detail.get('mutation_authority') is not False
                    or detail.get('scope') != scope_value or detail.get('selection') != selection
                    or not isinstance(detail.get('metadata'),dict) or detail['metadata'].get('name') != field):
                raise HostFailure('exact metadata selection scope/name mismatch')
            pending.append({'scope':scope,'field':field,'status':'captured',
                'list_receipt':list_receipt,'detail_receipt':receipt,'whole_inventory_complete':cursor is None,
                'detail_agent_result_sha256':sha(root/(receipt+'.agent-result.json')),
                **validate_native_detail(root,payload,version,scope,field,cohort=cohort)})
        if restart and attempt == 0:
            status_check()
            continue
        if restart:
            return [{'scope':scope,'field':field,'status':'unresolved','reason':'stale_locator_after_one_relist'} for field in fields]
        return pending
    raise HostFailure('unreachable collection retry state')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-reviewed-collection', action='store_true', required=True)
    parser.add_argument('--version', choices=BUILDS, required=True)
    parser.add_argument('--cohort',choices=('r54','r55'),default='r54')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--repo', type=Path, default=REPO)
    parser.add_argument('--gateway-root', type=Path, default=REPO)
    parser.add_argument('--live-config', type=Path, default=REPO/'tests/fixtures/local/live-environment.json')
    parser.add_argument('--readiness-seconds', type=float, default=180)
    parser.add_argument('--total-seconds', type=float, default=600)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('this reviewed private-HOME lifecycle supports macOS Console only')
    if any(not math.isfinite(n) or not 0 < n <= 3600 for n in (args.readiness_seconds, args.total_seconds)):
        parser.error('deadlines must be finite, positive and at most 3600 seconds')
    repo = args.repo.resolve(strict=True)
    gateway_root = args.gateway_root.resolve(strict=True)
    live_config = args.live_config.resolve(strict=True)
    skill = gateway_root/'skills/waapi-skill'
    # Keep lexical venv interpreter identity; do not resolve its executable symlink.
    runtime_python = skill/'.venv/bin/python'
    runner = skill/'scripts/run.py'
    if not runtime_python.is_file() or not runner.is_file():
        parser.error('frozen Skill-local interpreter and packaged runner must exist')
    root = args.root.expanduser()
    if not root.is_absolute() or os.path.lexists(root) or root.parent.resolve(strict=True) != root.parent:
        parser.error('--root must be a new absolute path below a canonical existing parent')
    if repo != REPO.resolve() or gateway_root != repo:
        parser.error('Closed collector uses its own immutable repository/Skill only')
    sys.path[:0]=[str(repo),str(repo/'skills/waapi-skill')]
    selected_plan = collection_plan(args.version,cohort=args.cohort)
    targets = selected_plan['targets']
    links, sources = source_links(args.version, targets)
    # Only read repository identity. Refuse dirty candidates rather than seal a moving source.
    identities = []
    for checkout in dict.fromkeys((repo, gateway_root)):
        status = subprocess.run(['git','status','--porcelain'], cwd=checkout, capture_output=True, text=True, check=True)
        if status.stdout:
            parser.error('candidate checkout must be clean before launch: ' + str(checkout))
        commit = subprocess.run(['git','rev-parse','HEAD'], cwd=checkout, capture_output=True, text=True, check=True).stdout.strip()
        identities.append({'checkout': str(checkout), 'commit': commit})
    sys.path[:0] = [str(repo), str(repo/'skills/waapi-skill')]
    from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle
    root.mkdir(mode=0o700)
    scenario = root/'scenario'
    private_home = scenario/'owned/wwise-user-home'
    prefix = private_home/'Library/Application Support/Wwise2019/Bottles/Wwise2019x64'
    config = root/'gateway-config.json'
    env = dict(os.environ)
    for name in ('WWISE_CONSOLE','WWISECONSOLE','WWISEROOT','WWISE_SAMPLE_PROJECT_PATH','WWISE_FIXTURE_PROJECT',
                 'WWISE_SANDBOX_ROOT','WWISE_WAAPI_PORT','WINEPREFIX','CX_ENV','WINEDLLOVERRIDES'):
        env.pop(name, None)
    env.update(WWISE_TEST_CONFIG=str(live_config), WWISE_VERSION=args.version,
               WWISE_READINESS_TIMEOUT=str(args.readiness_seconds), PYTHONDONTWRITEBYTECODE='1')
    def write(name, value):
        (root/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str)+'\n', encoding='utf-8')
    write('plan.json', {**selected_plan, 'observation_origin':'native_scenario_lifecycle',
        'source_links':links, 'source_seals':sources, 'repositories':identities,
        'actual_deadlines':{'readiness_seconds':args.readiness_seconds,'total_seconds':args.total_seconds}})
    def empty_home(_sandbox, _assets, _io):
        if not private_home.is_dir() or any(private_home.iterdir()) or os.path.lexists(prefix):
            raise HostFailure('expected empty owned HOME and nonexistent Wine prefix')
    owner = ScenarioLifecycle(scenario_id='CLASS-METADATA-'+args.version, version=args.version,
        scenario_root=scenario, live_environment=env, prelaunch_hook=empty_home,
        launch_environment_overrides={'HOME': str(private_home)}, owned_wine_prefix=prefix,
        lock_root=repo/'.waapi-skill-state/runtime/wwise-live-lifecycle-lock')
    active = None
    failure = None
    results = []
    count = 0
    archived = []
    final_lifecycle = None
    requested = 'BLOCKED'
    session = None
    project_id = None
    deadline = time.monotonic() + args.total_seconds

    def gateway(arguments):
        nonlocal count
        # Closed dispatcher: no typed/native calls, Draft, Preview or execution route.
        if not (arguments[0] in {'config-set','config-show','status'}
                or arguments[:2] in (['metadata','list'], ['metadata','detail'])):
            raise HostFailure('unreviewed command requested')
        if count >= MAX_CALLS or time.monotonic() >= deadline:
            raise HostFailure('collection invocation/time bound exhausted')
        count += 1
        stem = f'{count:03d}'
        argv = [str(runtime_python), str(runner), 'gateway.py', '--state-dir', str(root/'gateway-state'),
                '--timeout', '30', '--evidence-dir', str(root/'dispatcher-evidence'), *arguments]
        child_env = dict(active.runner_environment)
        child_env.update(WAAPI_SKILL_CONFIG_PATH=str(config), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8:strict')
        child_env.pop('PYTHONPATH', None)
        began = time.time()
        start = time.monotonic()
        write(stem+'.command.json', {'argv': argv, 'gateway_arguments': arguments, 'started_at_unix': began})
        code = None
        error = None
        child = None
        with (root/(stem+'.stdout')).open('wb') as out, (root/(stem+'.stderr')).open('wb') as err:
            try:
                child = subprocess.Popen(argv, cwd=repo, env=child_env, stdout=out, stderr=err, start_new_session=True)
                code = child.wait(timeout=min(45, max(.01, deadline-time.monotonic())))
            except BaseException as exc:
                error = f'{type(exc).__name__}: {exc}'
                if child is not None and child.poll() is None:
                    try: os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError: pass
                    try: child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        try: os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        child.wait(timeout=10)
                raise
            finally:
                write(stem+'.exit.json', {'exit_code': child.poll() if child is not None else None,
                    'started_at_unix': began, 'finished_at_unix': time.time(), 'elapsed_seconds': time.monotonic()-start,
                    'error': error, 'launched': child is not None,
                    'child_reaped': child is None or child.poll() is not None})
        paths = [root/(stem+'.stdout'), root/(stem+'.stderr')]
        native_archive_entries(root)
        if any(path.stat().st_size > MAX_BYTES for path in paths):
            raise HostFailure('bounded Gateway stream exceeded byte limit; raw bytes retained')
        try:
            payload = json.loads(paths[0].read_text(encoding='utf-8'),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, UnicodeError) as exc:
            raise HostFailure('non-JSON Gateway output; raw bytes retained') from exc
        if not isinstance(payload, dict):
            raise HostFailure('Gateway output is not an object')
        if 'agent_result' in payload:
            # No reconstruction/summary of the Gateway-owned object. Raw stdout is also preserved.
            write(stem+'.agent-result.json', payload['agent_result'])
        if arguments[0] not in {'config-set','config-show'}:
            ep = payload.get('endpoint') or {}
            if (ep.get('host'), ep.get('port')) != (active.host, active.port):
                raise HostFailure('Gateway endpoint mismatch')
            if payload.get('detected_version') != args.version:
                raise HostFailure('Gateway release mismatch')
            if payload.get('is_command_line') is not True:
                raise HostFailure('Gateway host mismatch')
            if (payload.get('session_context') or {}).get('project_modification_policy') != 'read_only':
                raise HostFailure('Gateway modification policy drift')
        if code != 0 or payload.get('ok') is not True:
            if arguments[0] == 'metadata' and code == 2 and payload.get('error_code') in UNRESOLVED | STALE:
                return payload, stem
            raise HostFailure('Gateway/host call failed: '+stem+' code='+str(code)+' error='+str(payload.get('error_code')))
        return payload, stem

    def status_check():
        nonlocal session, project_id
        payload, stem = gateway(['status'])
        info = payload.get('wwise') or {}
        ready = active.lifecycle.ready_result
        identity = (info.get('sessionId'), info.get('processId'))
        if exact_build(info) != BUILDS[args.version] or info.get('isCommandLine') is not True:
            raise HostFailure('status exact build/host mismatch')
        if not all(value is not None for value in identity) or identity != (ready.get('sessionId'), ready.get('processId')):
            raise HostFailure('status is not the owned ready session/process')
        current_project = (payload.get('project') or {}).get('id')
        if not current_project or session is not None and (session != identity or project_id != current_project):
            raise HostFailure('session/project changed during collection')
        session, project_id = identity, current_project
        return stem

    def interrupt(signum, _frame):
        raise HostFailure('driver interrupted by signal '+str(signum))
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM): signal.signal(sig, interrupt)
    signal.setitimer(signal.ITIMER_REAL,args.total_seconds)
    try:
        active = owner.start()
        info = active.lifecycle.ready_result
        if exact_build(info) != BUILDS[args.version] or info.get('isCommandLine') is not True:
            raise HostFailure('lifecycle ready exact build/host mismatch')
        if (active.runner_environment.get('HOME') != str(private_home)
                or active.runner_environment.get('WINEPREFIX') != str(prefix)
                or active.sandbox.metadata.wine_prefix_path != str(prefix)):
            raise HostFailure('effective private HOME/prefix differs from cleanup owner')
        write('ready.json', {'get_info':info,'host':active.host,'port':active.port,
            'home':str(private_home),'prefix':str(prefix),'sandbox':str(active.sandbox.sandbox_project),
            'source_hash_before':asdict(active.source_hash_before),'source_mtime_before_ns':active.source_mtime_before_ns})
        gateway(['config-set','--wwise-version',args.version,'--waapi-host',active.host,'--waapi-port',str(active.port),
                 '--project-modification-policy','read_only'])
        gateway(['config-show'])
        write('initial-status.json',{'receipt':status_check()})
        for scope, fields in targets.items():
            status_check()
            results.extend(collect_scope(gateway,args.version,scope,fields,root,status_check,cohort=args.cohort))
            write('targets.json', results)
        status_check()
        requested = 'PASS' if all(row['status']=='captured' for row in results) else 'BLOCKED'
    except BaseException as exc:
        failure = f'{type(exc).__name__}: {exc}'
        requested = 'BLOCKED'
        write('failure.json', {'error':failure,'start_failure':exc.as_dict() if hasattr(exc,'as_dict') else None})
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,signal.SIG_IGN)
        completed = {(row['scope'],row['field']) for row in results}
        for scope, fields in targets.items():
            for field in fields:
                if (scope,field) not in completed:
                    results.append({'scope':scope,'field':field,'status':'not_attempted','reason':'host_or_driver_failure'})
        try:
            write('targets.json',results)
            archived.extend(native_archive_entries(root))
            for path in sorted(root.iterdir()):
                if path.is_file() and path.name != 'gateway-config.json':
                    archived.append({'path':path.name,'sha256':sha(path),'bytes':path.stat().st_size})
            write('capture-archive.json', {'scope':'native class metadata only; no business/Fresh credit','files':archived})
        except BaseException as exc:
            failure = (failure+'; ' if failure else '')+f'archive: {type(exc).__name__}: {exc}'
            requested = 'BLOCKED'
        def verify_capture(_runtime):
            for item in archived:
                if sha(root/item['path']) != item['sha256']: raise HostFailure('durable receipt changed')
            for item in sources:
                if sha(Path(item['path'])) != item['sha256']: raise HostFailure('candidate/corpus/native XML source drift')
            for identity in identities:
                current=subprocess.check_output(['git','rev-parse','HEAD'],cwd=identity['checkout'],text=True).strip()
                status=subprocess.check_output(['git','status','--porcelain'],cwd=identity['checkout'],text=True)
                if current != identity['commit'] or status.strip():
                    raise HostFailure('Exact clean source candidate changed during collection')
        if active is not None:
            try:
                final_lifecycle = owner.finish(requested, reason=failure or ('unresolved metadata targets' if requested=='BLOCKED' else ''),
                                               post_shutdown_hook=verify_capture)
                write('cleanup.json',asdict(active.lifecycle.cleanup_report) if active.lifecycle.cleanup_report else None)
                write('console-output.json',{'stdout':active.lifecycle.output.stdout,'stderr':active.lifecycle.output.stderr})
            except BaseException as exc:
                failure = (failure+'; ' if failure else '')+f'finish: {type(exc).__name__}: {exc}'
        summary = {'status':final_lifecycle.final_status if final_lifecycle and not failure else 'BLOCKED',
            'host_failure':failure,'targets':results,'gateway_invocations':count,
            'lifecycle':final_lifecycle.as_dict() if final_lifecycle else None,
            'agent_started':False,'project_mutation_commands':0,
            'scope':'Console class metadata reconciliation only; not implementation or business coverage',
            'evidence_root':str(root)}
        summary['invocation']={'phase':'final','outcome':summary['status'],'node_outcomes':[
            {'nodeid':selected_plan['collector_nodeid'],'outcome':summary['status']}]}
        write('summary.json',summary)
        try:
            write_final_seal(root,scenario)
        except HostFailure as exc:
            summary['status']='BLOCKED'
            summary['host_failure']=(summary['host_failure']+'; ' if summary['host_failure'] else '')+str(exc)
            summary['invocation']['outcome']='BLOCKED'
            summary['invocation']['node_outcomes'][0]['outcome']='BLOCKED'
            write('summary.json',summary)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if summary['status']=='PASS' else 1



def write_branch_attachments(root, inventory, *, scope_kind='product'):
    """After one finalized capture: exact additive category receipts, no index edit."""
    from tests.maintenance import branch_audit_completion as reader
    from tests.support.metadata_read_branch_evidence import _witness
    root=Path(root)
    descriptors=metadata_descriptors(root)
    plan=json.loads((root/'plan.json').read_bytes())
    allowed=set(collection_plan(plan['version'],cohort=plan.get('cohort','r54'))['eligible_branch_ids'])
    branches=[row for row in inventory['native_coverage']['obligations'] if row['id'] in allowed]
    if {row['id'] for row in branches} != allowed:raise ValueError('Exact class default obligations changed')
    edges={row['id']:row for row in inventory['native_coverage']['obligations'] if row['kind']=='reference'}
    output=root/'branch-attachments';output.mkdir(exist_ok=False)
    used=set();attachments=[]
    def write(name,value):
        path=output/name;path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n')
        return {'artifact':root.name+'/branch-attachments/'+name,'sha256':sha(path)}
    for index,(case,descriptor) in enumerate(descriptors.items()):
        context=reader.read_metadata_run(descriptor,root.parent)
        if scope_kind == 'product':
            if context['observation_origin'] != 'native_scenario_lifecycle':
                raise ValueError('Controlled metadata origin cannot grant product native credit')
            from tests.support.metadata_replay_branch_evidence import git_source_seals
            if git_source_seals(context['candidate'],context['relevant_sources']) != context['relevant_sources']:
                raise ValueError('Native class source pin does not own its full original closure')
        native_input={'native':context['gateway']['argv']}
        transport=dict(descriptor,root=root.name,seal={**descriptor['seal'],'artifact':root.name+'/evidence-seal.json'})
        record={'candidate_sha256':inventory['native_coverage']['candidate_sha256'],'scope_kind':scope_kind,
            'evidence_kind':'current_public_class_metadata','metadata_run':transport,
            'invocation':context['invocation'],'category_inputs':native_input,
            'source_context':{'native_candidate':context['candidate'],'relevant_sources':context['relevant_sources']},
            'branch_assertions':{}}
        owned=[]
        for branch in branches:
            if branch['id'] in used:continue
            witness=_witness(branch,context['native_result'],edges)
            if witness is None:continue
            pointer=witness['observation_pointer'].replace('/native_call/result','/gateway/payload/agent_result/metadata',1)
            record['branch_assertions'][branch['id']]={'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],
                'checks':[{**witness['check'],'pointer':pointer},
                    {'pointer':'/gateway/payload/agent_result','equals':context['gateway']['payload']['agent_result']}]}
            owned.append(branch);used.add(branch['id'])
        if not owned:continue
        evidence=write('read-'+str(index)+'.json',record);evidence['nodeid']=plan['collector_nodeid']
        for branch in owned:
            attachments.append(write('attachment-'+str(len(attachments))+'.json',
                {'contract':'waapi-skill.class-metadata-attachment/v1','branch_id':branch['id'],
                 'native_shape_sha256':branch['shape_sha256'],'category_inputs':native_input,'evidence':evidence}))
    write('attachments.json',{'metadata_attachments':attachments,'observed_branch_ids':sorted(used),
        'assigned_unobserved_branch_ids':sorted(allowed-used),'attribution':'current_native_public_metadata_not_fresh'})
    return attachments


if __name__ == '__main__':
    raise SystemExit(main())
