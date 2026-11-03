"""One developer-owned 2025 fade-birth discriminator, using existing lifecycle/CLI.

This is neither a constructor nor a semantic harness. Saved XML is role evidence;
exact-ID identity readback alone never establishes a public role resolver.
"""
from dataclasses import asdict
from hashlib import sha256
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import uuid
import xml.etree.ElementTree as ET

from tests.semantic.support.codex_expansion_case_helpers import BusinessDraft, CaseBoundaryError
from tests.semantic.support.codex_expansion_policy import canonical_digest
from tests.semantic.support.codex_filesystem_security import read_bounded_exclusive_regular_file
from tests.semantic.support.codex_music_transition_goal import _save_owned
from tests.destructive.support.owned_role_survey import GET, FIELDS, VERSION, source_roster, _rows

OWNER = '{492A2BCA-08ED-4ED9-BDA3-B4D876D2D830}'
ROOT = '{2069AEE0-7C62-4F57-B7AA-D7325D150A39}'
RULE = '{B24173D4-7534-4C19-ACE0-F1F1B0EBD535}'
FIELD = 'EnableSourceFadeOut'
MEANING = 'Enable Source Fade-out'
WWU = Path('Containers/Music/Music.wwu')
EVIDENCE_FILE = 'music-fade-lifecycle.json'
LIMITS = {'gateway_calls': 96, 'native_calls': 4, 'reply_bytes': 1024 * 1024,
    'evidence_bytes': 8 * 1024 * 1024, 'raw_gateway_receipt_bytes': 2 * 1024 * 1024,
    'xml_bytes': 8 * 1024 * 1024}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')


def xml_role(path):
    raw = read_bounded_exclusive_regular_file(path, max_bytes=LIMITS['xml_bytes'],
        require_private_posix_mode=False).raw
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise CaseBoundaryError('Owned music XML must be entity-free')
    document = ET.fromstring(raw)
    owners = [node for node in document.iter('MusicPlaylistContainer') if node.get('ID') == OWNER]
    roots = [] if len(owners) != 1 else owners[0].findall(
        "./ReferenceList/Reference[@Name='TransitionRoot']/Custom/MusicTransition")
    if len(roots) != 1 or roots[0].get('ID') != ROOT:
        raise CaseBoundaryError('Pinned Playlist does not own the exact saved transition root')
    rules = roots[0].findall('./ChildrenList/MusicTransition')
    if len(rules) != 1 or rules[0].get('ID') != RULE:
        raise CaseBoundaryError('Pinned root does not own exactly the selected single rule')
    infos = rules[0].findall('./TransitionInfo')
    if len(infos) != 1:
        raise CaseBoundaryError('Pinned rule has no unique TransitionInfo')
    fades = infos[0].findall('./SourceFadeOut/MusicFade')
    if len(fades) > 1:
        raise CaseBoundaryError('Saved source fade role is ambiguous')
    role = None
    if fades:
        identity = fades[0].get('ID')
        if str(uuid.UUID(identity)).upper() != identity.strip('{}') or uuid.UUID(identity).int == 0:
            raise CaseBoundaryError('Saved source fade has a malformed identity')
        name = fades[0].get('Name')
        if not isinstance(name, str) or len(name.encode('utf-8')) > 256:
            raise CaseBoundaryError('Saved fade name is absent or exceeds its bound')
        role = {'id': identity, 'name': name, 'type': 'MusicFade'}
    return {'wwu_sha256': sha256(raw).hexdigest(), 'source_fade': role,
        'transition_info_xml': ET.tostring(infos[0], encoding='unicode')}


def _exact(gateway, identity, *, fields=()):
    payload = gateway(['query-object', '--exact-id', identity, '--include', 'class-id',
        '--include', 'owner', '--include', 'parent',
        *(arg for name in fields for arg in ('--include-field', name))])
    rows = payload.get('objects')
    if (payload.get('status') != 'ok' or payload.get('query_bound') != {'mode': 'exact-object'}
            or payload.get('limit_reached') is True or payload.get('projection_complete') is False
            or payload.get('count') != 1 or not isinstance(rows, list) or len(rows) != 1
            or rows[0].get('id') != identity):
        raise CaseBoundaryError('Public exact identity read is incomplete')
    return rows[0]


def _metadata(gateway, identity):
    fields, page = [], None
    for _ in range(4):
        result = gateway(['metadata', 'list', '--exact-id', identity, '--page-size', '64',
            *(['--page', page] if page else [])])['agent_result']
        fields.extend(result['fields'])
        if result['complete'] is True:
            if len(fields) != result['total_count'] or len({row['name'] for row in fields}) != len(fields):
                raise CaseBoundaryError('Live metadata inventory is incomplete')
            return fields
        page = result['next_page']
    raise CaseBoundaryError('Live metadata inventory exceeds four bounded pages')


def discriminate(ctx, actor, evidence):
    """Fixed conditional schedule; no write is retried, including save."""
    def independent(ids):
        assert len(evidence['native_calls']) < LIMITS['native_calls']
        call = {'uri': GET, 'args': {'from': {'id': ids}}, 'options': {'return': FIELDS}}
        evidence['native_calls'].append(call)
        try:
            result = actor(GET, call['args'], call['options'])
            assert len(encoded(result)) <= LIMITS['reply_bytes']
            call['result'] = result
            rows = _rows(result, maximum=len(ids))
            assert len(rows) == len(ids)
            assert {row['id'] for row in rows} == set(ids)
            return {row['id']: row for row in rows}
        except BaseException as exc:
            call['error'] = {'type': type(exc).__name__, 'message': str(exc)[:4096]}
            raise

    status = ctx.gateway(['status', '--detail'])
    evidence['status_read'] = status
    native = status['wwise']['version']
    assert '.'.join(str(native[key]) for key in ('year', 'major', 'minor', 'build')) == source_roster()['build']
    from wwise_waapi.host_paths import localize_waapi_host_path
    assert Path(localize_waapi_host_path(status['agent_result']['project']['path'])).resolve() == ctx.project_path.resolve()
    assert status['wwise']['isCommandLine'] is True
    identities = independent([OWNER, ROOT, RULE])
    assert identities[OWNER]['type'] == 'MusicPlaylistContainer'
    assert identities[ROOT]['type'] == identities[RULE]['type'] == 'MusicTransition'
    classes = {row['name']: row['classId'] for row in source_roster()['classes']}
    assert identities[ROOT]['classId'] == identities[RULE]['classId'] == classes['MusicTransition']
    assert identities[RULE]['parent']['id'] == ROOT
    evidence['identities_before'] = identities
    owner_fields = _metadata(ctx.gateway, OWNER)
    assert 'TransitionRoot' in {row['name'] for row in owner_fields}
    owner = _exact(ctx.gateway, OWNER, fields=('TransitionRoot',))
    assert owner['references']['TransitionRoot']['id'] == ROOT
    rule_fields = _metadata(ctx.gateway, RULE)
    evidence['rule_metadata_inventory'] = rule_fields
    assert FIELD in {row['name'] for row in rule_fields}
    # Every inspected spelling came from the actual live name inventory.
    details = {}
    for row in rule_fields:
        if 'fade' in row['name'].casefold():
            details[row['name']] = ctx.gateway(['metadata', 'detail', '--exact-id', RULE,
                '--selection', row['selection']])['agent_result']
    evidence['fade_metadata'] = details
    before = _exact(ctx.gateway, RULE, fields=(FIELD,))
    assert before['type'] == 'MusicTransition' and before['parent']['id'] == ROOT
    assert type(before['properties'][FIELD]) is bool
    evidence['boolean_before'] = before['properties'][FIELD]
    path = ctx.project_path.parent / WWU
    evidence['immutable_source_xml'] = xml_role(ctx.source_project.parent / WWU)
    assert evidence['immutable_source_xml']['source_fade'] is None, 'Fixture is not the pinned no-fade baseline'
    evidence['loaded_saved_xml'] = xml_role(path)
    baseline_tx = _save_owned(ctx)
    evidence['transaction_ids'].append(baseline_tx)
    baseline = xml_role(path)
    evidence['baseline_after_save'] = baseline
    role = baseline['source_fade']
    if role:
        evidence['outcome'] = 'default-materialized-role'
    else:
        assert _exact(ctx.gateway, RULE, fields=(FIELD,))['properties'][FIELD] is False, 'No attested false-to-true change'
        draft = BusinessDraft(ctx, 'object.setProperty')
        target = draft.bind(object_id=RULE)
        discovered = draft.step('draft-discover-fields', '--object-handle', target, '--meaning', MEANING)
        groups = discovered.get('meaning_results', [])
        candidates = groups[0].get('candidates', []) if len(groups) == 1 else []
        assert len(candidates) == 1 and candidates[0].get('field_kind') == 'property' and candidates[0].get('value_type') == 'boolean'
        draft.step('draft-declare-field-change', '--object-handle', target, '--field-handle', candidates[0]['handle'], '--business-value', 'true')
        draft.step('draft-check')
        tx = draft.step('preview-from-draft')['transaction_id']
        evidence['transaction_ids'].append(tx)
        shown = ctx.gateway(['transaction-show', tx])
        artifact = shown['artifact']
        assert shown['state'] == 'awaiting_confirmation' and shown['artifact_hash'] == canonical_digest(artifact)
        request = artifact['request']
        assert request['version'] == VERSION and request['operation'] == 'object.setProperty'
        assert request['arguments'] == {
            'object': {'kind': 'id', 'value': RULE}, 'property': FIELD, 'value': True}
        assert _exact(ctx.gateway, RULE, fields=(FIELD,))['properties'][FIELD] is False
        assert xml_role(path) == baseline, 'Owned baseline changed before execution'
        assert ctx.gateway(['confirm', tx, '--confirmation-token', shown['confirmation']['token']])['state'] == 'confirmed'
        evidence['outcome'] = 'indeterminate-dispatch-or-save'
        assert ctx.gateway(['execute', tx])['state'] == 'executed_unverified'
        verified = ctx.gateway(['verify', tx])
        assert verified['state'] == 'verified' and verified['verification']['business_state_verified'] is True
        assert _exact(ctx.gateway, RULE, fields=(FIELD,))['properties'][FIELD] is True
        saved = _save_owned(ctx)
        assert saved not in evidence['transaction_ids']
        evidence['transaction_ids'].append(saved)
        after = xml_role(path)
        evidence['after_flag_save'] = after
        role = after['source_fade']
        evidence['outcome'] = 'flag-created-role' if role else 'no-saved-role'
    if role:
        live = independent([role['id']])[role['id']]
        assert live['type'] == 'MusicFade' and live['name'] == role['name']
        assert live['classId'] == classes['MusicFade']
        assert live.get('owner', {}).get('id') == RULE, 'Fade owner must be rule; parent is not the ownership seam'
        evidence['independent_fade_identity'] = live
        exact = _exact(ctx.gateway, role['id'])
        assert exact['type'] == 'MusicFade' and exact.get('owner', {}).get('id') == RULE
        assert all(exact.get(key) == live.get(key) for key in ('id', 'name', 'type', 'path'))
        # Actual public advanced contract permits this fixed read-only type/owner/name predicate.
        ctx.gateway(['query-schema', '--advanced'])
        expression = f'from type MusicFade where owner.id = "{RULE}" and name = {json.dumps(role["name"])}'
        evidence['public_role_resolver'] = {'status': 'unresolved', 'expression': expression,
            'role_name_source': 'exact_owned_saved_TransitionInfo/SourceFadeOut/MusicFade@Name'}
        try:
            result = ctx.gateway(['query-object', '--advanced-waql', expression, '--max-results', '2', '--include', 'owner'])
        except CaseBoundaryError as exc:
            evidence['public_role_resolver'].update(status='public-query-rejected', error=str(exc)[:4096])
        else:
            rows = result.get('objects', [])
            resolved = (result.get('status') == 'ok' and result.get('query_bound') == {'mode': 'gateway-appended-take', 'value': 2}
                and result.get('count') == len(rows) == 1 and result.get('limit_reached') is not True
                and rows[0].get('id') == role['id'] and rows[0].get('type') == 'MusicFade'
                and rows[0].get('owner', {}).get('id') == RULE and rows[0].get('name') == role['name'])
            evidence['public_role_resolver'].update(status='resolved' if resolved else 'not-unique-or-missing', result=result)
    else:
        evidence['public_role_resolver'] = {'status': 'no-saved-role-to-resolve'}
    evidence['discriminator_completed'] = True


def run_probe(lifecycle, *, actor_factory=None, gateway_factory=None):
    """Use the established actor, public CLI and lifecycle finalizers unchanged."""
    if actor_factory is None:
        from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall
        actor_factory = OwnedDirectWaapiCall
    if gateway_factory is None:
        from tests.semantic.support.codex_expansion_runtime import fixture_gateway
        gateway_factory = fixture_gateway
    evidence = {'contract': 'waapi-skill.music-fade-lifecycle-discriminator/v1', 'version': VERSION,
        'limits': LIMITS, 'native_calls': [], 'gateway_receipts': [], 'transaction_ids': [],
        'outcome': 'indeterminate-dispatch-or-save', 'discriminator_completed': False,
        'agent_semantic_pass': False, 'complete_fade_configuration_delivered': False}
    runtime, actor, closed = None, None, True
    pending = set()
    status, reason = 'FAIL', ''
    try:
        runtime = lifecycle.start()
        evidence['owned_scope'] = {'sandbox_project': str(runtime.sandbox.sandbox_project),
            'source_project': str(runtime.sandbox.source_project), 'host': runtime.host, 'port': runtime.port,
            'source_hash_before': asdict(runtime.source_hash_before), 'source_mtime_before_ns': runtime.source_mtime_before_ns}
        actor = actor_factory(host=runtime.host, port=runtime.port)
        gateway = gateway_factory(skill_source=Path(__file__).resolve().parents[3] / 'skills/waapi-skill',
            runtime=runtime, version=VERSION, receipts=evidence['gateway_receipts'])
        attempted = set()
        def bounded(argv):
            assert len(evidence['gateway_receipts']) < LIMITS['gateway_calls']
            if argv[0] == 'execute':
                assert argv[1] not in attempted, 'Never retry mutation or save'
                attempted.add(argv[1])
                pending.add(argv[1])
            receipt_index = len(evidence['gateway_receipts'])
            try:
                result = gateway(argv)
            except BaseException as exc:
                if isinstance(exc, subprocess.TimeoutExpired) and len(evidence['gateway_receipts']) > receipt_index:
                    last = evidence['gateway_receipts'][-1]
                    for label, value in (('timeout_stdout', exc.stdout), ('timeout_stderr', exc.stderr)):
                        if value is not None:
                            raw = value if isinstance(value, bytes) else str(value).encode('utf-8')
                            last[label] = {'bytes': len(raw), 'excerpt': raw[:8192].decode('utf-8', 'replace')}
                if argv[0] in {'execute', 'verify'} and argv[1] in pending:
                    evidence['unresolved_write_transaction'] = argv[1]
                raise
            finally:
                # The existing factory owns raw transport diagnostics. Archive each
                # bounded receipt before compacting the aggregate, including failures.
                for index in range(receipt_index, len(evidence['gateway_receipts'])):
                    row = evidence['gateway_receipts'][index]
                    raw_receipt = encoded(row)
                    assert len(raw_receipt) <= LIMITS['raw_gateway_receipt_bytes']
                    relative = f'gateway-receipts/{index:03d}.json'
                    destination = runtime.evidence_root / relative
                    destination.parent.mkdir(exist_ok=True)
                    try:
                        destination.write_bytes(raw_receipt)
                    except BaseException as exc:
                        evidence['receipt_seal_error'] = str(exc)[:4096]
                        raise
                    evidence['gateway_receipts'][index] = {'argv': row['argv'],
                        'raw_receipt': relative, 'sha256': sha256(raw_receipt).hexdigest(),
                        'bytes': len(raw_receipt), **({'exit_code': row['exit_code']} if 'exit_code' in row else {}),
                        **({'error': row['error']} if 'error' in row else {})}
            if argv[0] == 'verify' and result.get('state') in {'verified', 'result_schema_checked'}:
                pending.discard(argv[1])
            return result
        bounded(['config-set', '--wwise-version', VERSION, '--waapi-host', runtime.host,
            '--waapi-port', str(runtime.port), '--project-modification-policy', 'ask_before_changes'])
        ctx = SimpleNamespace(version=VERSION, gateway=bounded, project_path=runtime.sandbox.sandbox_project,
            source_project=runtime.sandbox.source_project)
        discriminate(ctx, actor, evidence)
        status = 'PASS'
    except BaseException as exc:
        if evidence.get('receipt_seal_error'):
            status = 'BLOCKED'
        elif evidence.get('unresolved_write_transaction') or pending:
            evidence['unresolved_write_transactions'] = sorted(pending)
            status = 'INDETERMINATE'
        reason = str(exc)[:4096]
        evidence['error'] = {'type': type(exc).__name__, 'message': reason}
        raise
    finally:
        if actor is not None:
            try:
                closed = actor.close() and actor.fully_closed
            except BaseException as exc:
                closed = False
                evidence['actor_close_error'] = str(exc)[:4096]
            if not closed:
                status, reason = 'BLOCKED', 'Owned actor did not close'
        evidence['collection_status'] = status
        evidence['status'] = 'PENDING'
        evidence['final_outcome'] = {'path': 'lifecycle.json', 'field': 'final_status'}
        if runtime is not None:
            try:
                raw = encoded(evidence)
                assert len(raw) <= LIMITS['evidence_bytes'], 'Discriminator evidence ceiling exceeded'
                (runtime.evidence_root / EVIDENCE_FILE).write_bytes(raw)
            except BaseException:
                status, reason = 'BLOCKED', 'Discriminator evidence could not be sealed'
                raise
            finally:
                finished = lifecycle.finish(status, reason=reason)
                assert finished.final_status == status, finished
        if 'error' not in evidence:
            assert closed, reason
    return evidence
