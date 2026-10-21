"""Closed portable Source-copy facts for the existing branch evidence reader.

The receipt remains byte-identical. Its old absolute paths are provenance keys,
never fallback locators. Only the selected proof roots (public replies, typed
metadata, model images and four native writes) are transported; unrelated native
reads remain in the original archive and grant no additional branch credit.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
from types import SimpleNamespace

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.semantic.support.codex_archive_paths import parse_archive_relative_path
from tests.destructive.support import source_copy_fixture as fixture

URI = 'ak.wwise.core.object.copy'
PROOF = 'waapi-skill.source-copy-portable-proof/v1'
ATTACHMENT = 'waapi-skill.source-copy-branch-attachment/v1'
POINTERS = {
    '/argsSchema/@definition/waapi_definitions.json/definitions/objectArg/anyOf/1':
        ('/native_call/args/object', '/argsSchema/properties/object/$ref'),
    '/argsSchema/properties/onNameConflict/enum/2': ('/native_call/args/onNameConflict', None),
    '/resultSchema/@definition/waapi_definitions.json/definitions/objectReturn/properties/id':
        ('/native_call/result/id', '/resultSchema/$ref'),
    '/resultSchema/@definition/waapi_definitions.json/definitions/objectReturn/properties/name':
        ('/native_call/result/name', '/resultSchema/$ref'),
}
SYMBOLS = {
    'construction': 'skills/waapi-skill/wwise_waapi/object_lifecycle_business.py#materialize_object_lifecycle_business_request',
    'validation': 'skills/waapi-skill/wwise_waapi/source_copy_proof.py#validate_baseline',
    'verifier': 'skills/waapi-skill/wwise_waapi/source_copy_proof.py#verify_saved',
}



def pointer_contract(version):
    if version not in fixture.MODERN_ORIGINALS:
        raise ValueError('Source branch attachment version is not yet admitted')
    extra = {} if version == '2022.1' else {
        '/argsSchema/properties/' + name + '/@boolean/false': ('/native_call/args/' + name, None)
        for name in ('autoAddToSourceControl', 'autoCheckOutToSourceControl')}
    return {**POINTERS, **extra}


def native_route(version):
    return f'{version}|wwise-console|{fixture.MODERN_ORIGINALS[version][0]}|function|{URI}'


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding='utf-8')
    return {'artifact': path.name, 'sha256': fixture.sha(path.read_bytes())}


def selected_branches(inventory, version):
    contract = pointer_contract(version)
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    return [rows[native_route(version) + '|' + pointer] for pointer in contract]


class ProofFiles:
    """Bounded byte reads, with an exact closed provenance-to-portable map."""
    def __init__(self, proof, base):
        if set(proof) != {'contract', 'receipt', 'files'} or proof['contract'] != PROOF:
            raise ValueError('Closed Source portable proof required')
        if not isinstance(proof['files'], dict) or not 1 <= len(proof['files']) <= 512:
            raise ValueError('Source portable proof file bound exceeded')
        self.proof, self.base, self.used, self.total = proof, Path(base).resolve(), set(), 0

    def raw(self, link):
        origin = link.get('path', link.get('index_path'))
        descriptor = self.proof['files'].get(origin)
        if descriptor is None:
            raise ValueError('Source proof has a missing transitive dependency')
        if set(descriptor) != {'artifact', 'sha256', 'size'}:
            raise ValueError('Closed Source dependency descriptor required')
        identity = parse_archive_relative_path(descriptor['artifact']).canonical
        path = self.base / identity
        if path.is_symlink() or not path.resolve().is_relative_to(self.base):
            raise ValueError('Source dependency escapes its portable bundle')
        raw = fixture.read_file(path)
        if (len(raw) != descriptor['size'] or descriptor['sha256'] != link['sha256']
                or fixture.sha(raw) != link['sha256']
                or ('size' in link and len(raw) != link['size'])):
            raise ValueError('Source dependency link digest/size mismatch')
        if origin not in self.used:
            self.used.add(origin); self.total += len(raw)
        if self.total > 16 * 1024 * 1024:
            raise ValueError('Source proof byte bound exceeded')
        return raw

    def read(self, link):
        return json.loads(self.raw(link))


def export_source_proof(output, receipt_path):
    """Copy selected original bytes once; never rewrite an original receipt."""
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    receipt_path = Path(receipt_path)
    receipt_raw = fixture.read_file(receipt_path)
    receipt = json.loads(receipt_raw)
    files = {}
    def keep(link):
        origin = link.get('path', link.get('index_path'))
        raw = fixture.read_file(Path(origin))
        if fixture.sha(raw) != link['sha256'] or ('size' in link and len(raw) != link['size']):
            raise ValueError('Original Source dependency link mismatch')
        name = 'facts/' + fixture.sha(raw)
        (output / 'facts').mkdir(exist_ok=True)
        path = output / name
        if not path.exists(): path.write_bytes(raw)
        descriptor = {'artifact': name, 'sha256': fixture.sha(raw), 'size': len(raw)}
        if origin in files and files[origin] != descriptor:
            raise ValueError('Conflicting Source provenance dependency')
        files[origin] = descriptor
        return json.loads(raw) if raw[:1] in (b'{', b'[') else raw
    receipt_link = {'path': str(receipt_path), 'sha256': fixture.sha(receipt_raw), 'size': len(receipt_raw)}
    keep(receipt_link)
    for call in receipt['calls']: keep(call['reply'])
    keep(receipt['original_midi'])
    for link in receipt['model_images'].values():
        index = keep(link)
        for entry in index['files'].values(): keep(entry['artifact_proof'])
    native_index = keep(receipt['native_file_proofs'])
    native = {row['native_file_proof']['path']: row for row in native_index['files']}
    field_links = [receipt['fixture_acceptance'][key] for key in ('loaded_scalar_observation', 'scalar_observation')]
    field_links += [receipt[key] for key in ('copied_scalar_observation', 'retained_scalar_observation')]
    needed = set()
    for link in field_links:
        snapshots = keep(link)
        for snapshot in snapshots.values():
            for packets in snapshot['native_metadata_authority'].values():
                for packet in packets:
                    row = native[packet['path']]
                    if row['native_file_proof'] != packet: raise ValueError('Metadata native proof link mismatch')
                    needed.add(packet['path'])
    for origin, row in native.items():
        # The native index is retained whole. Selection is a closed proof-root
        # rule, not arbitrary caller-supplied observations or a full archive copy.
        if origin.endswith(('-ak_wwise_core_object_create.json', '-ak_wwise_core_object_copy.json',
                            '-ak_wwise_core_project_save.json')):
            needed.add(origin)
    for origin in needed: keep(native[origin]['archive'])
    proof = {'contract': PROOF, 'receipt': receipt_link, 'files': files}
    return write_json(output / 'proof.json', proof)


def _source_facts(proof, base):
    """Recheck shared scalar/root/graph guards against transported public facts."""
    files = ProofFiles(proof, base)
    receipt = files.read(proof['receipt'])
    version = receipt['version']
    if (version not in fixture.MODERN_ORIGINALS or receipt['contract'] != 'waapi-skill.modern-source-copy-save-children-collector/v1'
            or receipt['fixture_profile'] != fixture.MODERN_PROFILE
            or receipt['native_build'] != fixture.MODERN_ORIGINALS[version][0]
            or receipt['diagnostic_only'] is not True or receipt['business_effect_verified'] is not False
            or receipt['saved_copy_verified'] is not True or receipt['collection_complete'] is not True):
        raise ValueError('Unaccepted Source receipt scope or original flags')
    calls = receipt['calls']
    if not 1 <= len(calls) <= 160 or any(call['exit_code'] != 0 for call in calls):
        raise ValueError('Source public call boundary failed')
    replies = [files.read(call['reply']) for call in calls]
    transactions = receipt['transaction_ids']
    phases = receipt['phases']
    if (len(transactions) != len(set(transactions)) or len(transactions) != 4
            or [phase['name'] for phase in phases] != ['create_empty_destination', 'save_baseline', 'copy_source_only', 'save_final']
            or [phase['transaction_id'] for phase in phases] != transactions):
        raise ValueError('Source requires exactly four ordered transactions')
    for phase, tx in zip(phases, transactions):
        executes = [i for i, call in enumerate(calls) if call['argv'] == ['execute', tx]]
        confirms = [i for i, call in enumerate(calls) if call['argv'][:2] == ['confirm', tx]]
        if len(executes) != 1 or len(confirms) != 1 or confirms[0] >= executes[0]:
            raise ValueError('Source transaction lacks separate authorization or execute-once')
        execute = replies[executes[0]]
        terminal = replies[phase['terminal_call_index']]
        authority = phase['authority_receipt']
        if (execute['artifact_hash'] != authority['artifact_hash'] or execute['transaction_id'] != tx
                or execute['ok'] is not True or execute['dispatch_result']['dry_run'] is not False
                or terminal['artifact_hash'] != authority['artifact_hash'] or terminal['state'] != {'create_empty_destination': 'verified', 'save_baseline': 'result_schema_checked',
                    'copy_source_only': 'executed_unverified', 'save_final': 'result_schema_checked'}[phase['name']]):
            raise ValueError('Source executed/terminal transaction binding differs')
    copy_tx = transactions[2]
    shown, = [reply for call, reply in zip(calls, replies) if call['argv'] == ['transaction-show', copy_tx]]
    artifact = shown['artifact']
    if audit.digest(artifact) != shown['artifact_hash'] or shown['artifact_hash'] != phases[2]['authority_receipt']['artifact_hash']:
        raise ValueError('Source immutable copy artifact hash differs')
    dispatch = deepcopy(artifact['prepared_operation']['dispatch'])
    execute, = [reply for call, reply in zip(calls, replies) if call['argv'] == ['execute', copy_tx]]
    dispatch['result'] = execute['dispatch_result']['result']
    finals = [(call, reply) for call, reply in zip(calls, replies)
              if call['argv'] == ['verify', copy_tx] and reply.get('verified') is True]
    (final_call, final), = finals
    if (dispatch['uri'] != URI or dispatch['args'] != {'object': fixture.SOURCE,
            'parent': receipt['destination_id'], 'onNameConflict': 'fail',
            **({} if version == '2022.1' else {'autoAddToSourceControl': False, 'autoCheckOutToSourceControl': False})}
            or final['verification']['verification_strength'] != 'saved_source_graph_and_live_roles'
            or final['verification']['verification_scope']['complete_copy_preservation'] is not True
            or final['verification']['verification_scope']['final_save_receipt'] != phases[3]['authority_receipt']
            or final['artifact_hash'] != shown['artifact_hash']):
        raise ValueError('Source copy dispatch/final Save lineage differs')
    native_index = files.read(receipt['native_file_proofs'])
    indexed = {row['native_file_proof']['path']: row for row in native_index['files']}
    if len(indexed) != native_index['count'] or native_index['count'] > 1280:
        raise ValueError('Source native index completeness differs')
    writes = []
    for origin, row in indexed.items():
        if origin.endswith(('-ak_wwise_core_object_create.json', '-ak_wwise_core_object_copy.json', '-ak_wwise_core_project_save.json')):
            packet = files.read(row['archive']); writes.append(packet['api'])
            if packet.get('ok') is not True or packet.get('dry_run') is not False or packet['version'] != version:
                raise ValueError('Source native write packet failed')
            if packet['api'] == URI and packet['result'] != dispatch['result']:
                raise ValueError('Source native/public copy result differs')
    if sorted(writes) != sorted(['ak.wwise.core.object.create', URI, 'ak.wwise.core.project.save', 'ak.wwise.core.project.save']):
        raise ValueError('Source native write set differs')
    original = files.raw(receipt['original_midi'])
    if fixture.sha(original) != fixture.MODERN_ORIGINALS[version][2]:
        raise ValueError('Source pinned original differs')
    images = {}
    for phase, link in receipt['model_images'].items():
        index = files.read(link)
        images[phase] = [files.raw(entry['artifact_proof']) for entry in index['files'].values()]
        local_index = files.base / proof['files'][link['index_path']]['artifact']
        view = SimpleNamespace(files=index['files'], link=link, errors=index['errors'], phase=phase, index_path=local_index)
        original_unit, = list(fixture.xml(original).iter('WorkUnit'))
        root_children = [{'id': node.get('ID'), 'name': node.get('Name'), 'type': node.tag}
                         for node in original_unit.find('ChildrenList')]
        destination = next(row for reply in replies for row in (reply.get('agent_result') or [])
                           if isinstance(row, dict) and row.get('id') == receipt['destination_id'])
        unit = fixture.saved_midi(images[phase], index=view, relative=fixture.MODERN_ORIGINALS[version][1],
            work_unit_id=original_unit.get('ID'), root_children=root_children + [destination])
        order = [(node.tag, dict(node.attrib)) for node in unit.find('ChildrenList')]
        if phase == 'before':
            baseline_order = order
            pinned = [(node.tag, dict(node.attrib)) for node in original_unit.find('ChildrenList')]
            if [(tag, attrs) for tag, attrs in order if attrs['ID'] != receipt['destination_id']] != pinned:
                raise ValueError('Source baseline Save changed pinned root order')
        elif order != baseline_order:
            raise ValueError('Source final root order differs')
    # Reuse the collector's scalar and saved-subtree oracles, with actual public
    # identity frames and canonical hop replies retained in the portable closure.
    fields = [files.read(receipt['fixture_acceptance'][key]) for key in ('loaded_scalar_observation', 'scalar_observation')]
    fields += [files.read(receipt[key]) for key in ('copied_scalar_observation', 'retained_scalar_observation')]
    graphs = [fixture.source_graph([original], fixture.SOURCE, fixture.SOURCE_OWNER, version=version),
              fixture.source_graph(images['before'], fixture.SOURCE, fixture.SOURCE_OWNER, version=version),
              fixture.source_graph(images['after'], dispatch['result']['id'], receipt['destination_id'], version=version),
              fixture.source_graph(images['after'], fixture.SOURCE, fixture.SOURCE_OWNER, version=version)]
    ranges = [(0, phases[0]['verify_call_index']),
              (phases[1]['verify_call_index'] + 1, receipt['fixture_acceptance']['accepted_at_call_index'] + 1),
              (calls.index(final_call) + 1, len(calls)), (calls.index(final_call) + 1, len(calls))]
    lives = []
    for nodes, snapshots, (start, stop) in zip(graphs, fields, ranges):
        live = {}
        for role, node in nodes.items():
            identity = node.get('ID'); snapshot = snapshots[role]
            values = {}
            for call, reply in zip(calls[start:stop], replies[start:stop]):
                argv = call['argv']
                if argv[:3] != ['query-object', '--exact-id', identity] or '--include-field' not in argv: continue
                row, = reply['agent_result']
                frame = {key: value for key, value in row.items() if key not in {'properties', 'references'}}
                if role in live and live[role] != frame: raise ValueError('Source public field identity drift')
                live[role] = frame
                values.update(row.get('properties', {})); values.update(row.get('references', {}))
            inventories = [reply['agent_result'] for call, reply in zip(calls[start:stop], replies[start:stop])
                           if call['argv'][:4] == ['metadata', 'list', '--exact-id', identity]]
            if (len(inventories) != 1 or inventories[0].get('complete') is not True
                    or inventories[0]['total_count'] != {'source': 18, 'rtpc': 5, 'control_input': 10, 'curve': 1}[role]
                    or [field['name'] for field in inventories[0]['fields']] != snapshot['names']
                    or len(snapshot['names']) != len(set(snapshot['names']))
                    or values != snapshot['values'] or set(snapshot['names']) != set(values)
                    or set(snapshot['native_metadata_authority']) != set(values)):
                raise ValueError('Source typed fields lack complete exact public page authority')
            for name, authorities in snapshot['native_metadata_authority'].items():
                if not authorities: raise ValueError('Source typed metadata authority missing')
                for authority in authorities:
                    row = indexed[authority['path']]
                    if authority != row['native_file_proof']: raise ValueError('Source typed metadata proof differs')
                    packet = files.read(row['archive'])
                    if (packet['api'] != 'ak.wwise.core.object.getPropertyInfo' or packet['ok'] is not True
                            or packet['version'] != version or packet['result'] != snapshot['metadata'][name]):
                        raise ValueError('Source typed metadata packet differs')
        for token, role, owner in (('RTPC', 'rtpc', 'source'), ('ControlInput', 'control_input', 'rtpc'), ('Curve', 'curve', 'rtpc')):
            expression = f'from object "{live[owner]["id"]}" select @{token}'
            hopped = [reply['agent_result'] for call, reply in zip(calls[start:stop], replies[start:stop])
                      if call['argv'][:3] == ['query-object', '--advanced-waql', expression]
                      and call['argv'][3:5] == ['--max-results', '2']]
            if hopped != [[live[role]]]: raise ValueError('Source canonical bounded owned hop differs')
        points = live['curve']['curve_points']
        saved_points = nodes['curve'].findall('PointList/Point')
        if (not isinstance(points, list) or len(points) != len(saved_points)
                or any(not isinstance(point, dict) or set(point) != {'x', 'y', 'shape'}
                       or point['shape'] != 'Linear' or any(type(point[axis]) not in (int, float)
                       or not math.isfinite(point[axis]) for axis in ('x', 'y')) for point in points)
                or [(point['x'], point['y']) for point in points] !=
                    [(float(node.findtext('XPos')), float(node.findtext('YPos'))) for node in saved_points]):
            raise ValueError('Source native/saved Curve points differ')
        if (snapshots['rtpc']['values']['ControlInput'] != {'id': live['control_input']['id'], 'name': live['control_input']['name']}
                or snapshots['rtpc']['values']['Curve'] != {'id': live['curve']['id'], 'points': points,
                                                         '@Flags': snapshots['curve']['values']['Flags']}):
            raise ValueError('Source typed canonical reference values differ')
        fixture.validate_frames(nodes, live, fixture.SOURCE_OWNER if nodes['source'].get('ID') == fixture.SOURCE else receipt['destination_id'], xml_notes_crlf=True)
        fixture.validate_scalars(nodes, snapshots, allow_references=True)
        lives.append(live)
    facts = lambda snapshots: {role: {key: value for key, value in row.items() if key != 'native_metadata_authority'} for role, row in snapshots.items()}
    if not lives[0] == lives[1] == lives[3] or not facts(fields[0]) == facts(fields[1]) == facts(fields[3]):
        raise ValueError('Source original live fields changed')
    expected = deepcopy(facts(fields[1]))
    mapping = receipt['oracle']['owned_guid_mapping']
    for row in expected.values():
        for name, value in row['values'].items():
            if row['metadata'][name].get('restriction', {}).get('type') == 'reference': value['id'] = mapping[value['id']]
    if facts(fields[2]) != expected: raise ValueError('Source copied typed fields differ')
    oracle = fixture.repeated_copy_oracle(images['before'], images['after'], source_id=fixture.SOURCE,
        copied_id=dispatch['result']['id'], original_owner_id=fixture.SOURCE_OWNER,
        destination_id=receipt['destination_id'], before_live=lives[1], copied_live=lives[2], version=version)
    if any(receipt['oracle'].get(key) != value for key, value in oracle.items()):
        raise ValueError('Source saved graph oracle differs')
    if files.used != set(proof['files']): raise ValueError('Source portable proof has unused/unresolved dependency roots')
    return {'gateway': {'argv': final_call['argv'], 'exit_code': final_call['exit_code'], 'payload': final},
            'native_call': dispatch, 'version': version, 'business_fact_id': version + '|source-copy-synth-owned-graph'}



def source_facts(proof, base):
    try:
        return _source_facts(proof, base)
    except AssertionError as exc:
        raise ValueError('Source independent fixture guard: ' + str(exc)) from exc


def validate_source_program(record, binding, branch, base):
    proof = completion.read_sealed_artifact(binding['source_copy_proof'], base)
    facts = source_facts(proof, base)
    if (branch['pointer'] not in pointer_contract(facts['version']) or branch['route'] != native_route(facts['version'])
            or record['gateway'] != facts['gateway'] or record['native_call'] != facts['native_call']
            or binding['source_business_fact'] != facts['business_fact_id']):
        raise ValueError('Source attachment does not prove this exact branch/public invocation')


def write_source_program_bundle(output, receipt_path, *, inventory, nodeid, phase_reports, scope_kind):
    """Controlled rehearsal; product capture uses the shared pytest finalizer."""
    if scope_kind != 'controlled' or phase_reports != {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}:
        raise ValueError('Source controlled rehearsal requires exact finalized phase outcomes')
    output = Path(output)
    proof_desc = export_source_proof(output, receipt_path)
    facts = source_facts(completion.read_sealed_artifact(proof_desc, output), output)
    version = facts['version']
    branches = selected_branches(inventory, version)
    public = next(row for row in inventory['routes'] if row['id'] == version + '|function|' + URI)
    candidate = inventory['native_coverage']['candidate_sha256']
    record = {'candidate_sha256': candidate, 'scope_kind': scope_kind, 'evidence_kind': 'injected_client_program',
        'invocation': {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': nodeid, 'outcome': 'PASS'}]},
        'gateway': facts['gateway'], 'native_call': facts['native_call'], 'branch_assertions': {}}
    bindings = {}
    for branch in branches:
        pointer, edge = pointer_contract(version)[branch['pointer']]
        record['branch_assertions'][branch['id']] = {'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
            'checks': [{'pointer': pointer, 'equals': completion.pointer_value(facts, pointer)},
                       {'pointer': '/gateway/payload/agent_result', 'equals': facts['gateway']['payload']['agent_result']}]}
        binding = {'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
            'public_route': public['id'], 'public_route_sha256': audit.digest(public),
            'input': {'gateway_argv': facts['gateway']['argv']},
            **{key: {'source': source, 'selector': branch['pointer']} for key, source in SYMBOLS.items()},
            'observation_pointer': pointer, 'native_hosts': ['wwise-console'], 'evidence': {}}
        if edge: binding['reference_chain'] = [branch['route'] + '|' + edge]
        bindings[branch['id']] = binding
    program = {**write_json(output / 'program.json', record), 'nodeid': nodeid}
    for binding in bindings.values(): binding['evidence']['program'] = program
    doc = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': bindings}
    bound = write_json(output / 'bindings.json', doc)
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {
        branch['id']: {'native_shape_sha256': branch['shape_sha256'], 'categories': ['program', 'native'],
                      'reason': 'Exact Source copy leaf and scoped #180 graph fact; separate native evidence required.'} for branch in branches}}
    required = write_json(output / 'requirements.json', requirements)
    capture = write_json(output / 'capture.json', {'contract': 'waapi-skill.source-copy-program-rehearsal/v1',
        'scope_kind': scope_kind, 'candidate_sha256': candidate, 'phase_reports': phase_reports, 'native_credit': False})
    attachment = write_json(output / 'attachment.json', {'contract': ATTACHMENT,
        'branch_ids': list(bindings), 'business_fact_id': facts['business_fact_id'], 'proof': proof_desc})
    write_json(output / 'index.json', {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.',
        'entries': [{'id': 'source-' + version, 'bindings': bound, 'origin': {'bindings': bound, 'program': {k: program[k] for k in ('artifact', 'sha256')},
            'requirements': required, 'capture': capture}}], 'source_attachments': [attachment]})
    return output / 'index.json'


def portable_source_attachments(descriptors, bindings, read, base):
    if not isinstance(descriptors, list): raise ValueError('Closed Source attachment list required')
    attached, business = set(), []
    for descriptor in descriptors:
        attachment = read(descriptor)
        if set(attachment) != {'contract', 'branch_ids', 'business_fact_id', 'proof'} or attachment['contract'] != ATTACHMENT:
            raise ValueError('Closed Source branch attachment required')
        proof = read(attachment['proof'])
        facts = source_facts(proof, base)
        ids = attachment['branch_ids']
        if (not isinstance(ids, list) or not ids or len(ids) != len(set(ids))
                or attachment['business_fact_id'] != facts['business_fact_id']):
            raise ValueError('Source attachment exact branch/business fact mismatch')
        for identity in ids:
            if identity not in bindings or not isinstance(identity, str) or '|' not in identity:
                raise ValueError('Duplicate or unsupported exact Source branch')
            binding = bindings[identity]
            route, pointer = identity.rsplit('|', 1)
            if identity in attached or pointer not in pointer_contract(facts['version']) or route != native_route(facts['version']):
                raise ValueError('Duplicate or unsupported exact Source branch')
            attached.add(identity)
            binding['source_copy_proof'] = deepcopy(attachment['proof'])
            binding['source_business_fact'] = facts['business_fact_id']
        business.append(facts['business_fact_id'])
    return business
