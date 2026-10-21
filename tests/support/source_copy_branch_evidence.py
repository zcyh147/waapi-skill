"""Closed portable Source-copy facts for the existing branch evidence reader.

The receipt remains byte-identical. Its old absolute paths are provenance keys,
never fallback locators. Only the selected proof roots (public replies, typed
metadata, model images and four native writes) are transported; unrelated native
reads remain in the original archive and grant no additional branch credit.
"""
from copy import deepcopy
import json
import math
import subprocess
import os
import tempfile
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



REVIEW_PATH = 'tests/fixtures/source-copy/branch-dependency-review.json'
REVIEW_SHA256 = 'aee3af054ccbb2ad109f9bb6a375c7ceab7d6e6468f3257ea3d14d581d79af5d'
CAPTURE = 'waapi-skill.source-copy-program-capture-context/v1'
PUBLIC_NODES = {
    '2021.1': 'tests/unit/test_source_copy_repeated_fixture.py::test_repeated_collector_gates_copy_on_actual_baseline_serialization',
    '2022.1': 'tests/unit/test_source_copy_modern_collector.py::test_modern_collector_preserves_original_graph_through_four_transactions[2022.1]',
    '2023.1': 'tests/unit/test_source_copy_modern_collector.py::test_modern_collector_preserves_original_graph_through_four_transactions[2023.1]',
    '2024.1': 'tests/unit/test_source_copy_modern_collector.py::test_modern_collector_preserves_original_graph_through_four_transactions[2024.1]',
    '2025.1': 'tests/unit/test_source_copy_modern_collector.py::test_modern_collector_2025_preserves_native_crlf_and_direct_rtpc_through_four_transactions',
}


def dependency_review():
    # Root approval pins exact historical540/current547 maps for all26 selected leaves.
    # An edited proposal cannot self-authorize new behavior or omit dependencies.
    raw = (audit.ROOT / REVIEW_PATH).read_bytes()
    if fixture.sha(raw) != REVIEW_SHA256:
        raise ValueError('Reviewed Source dependency maps changed')
    return json.loads(raw)


def source_seals(names):
    result = {}
    for name in sorted(names):
        identity = parse_archive_relative_path(name).canonical
        path = audit.ROOT / identity
        if path.is_symlink() or not path.resolve().is_relative_to(audit.ROOT.resolve()):
            raise ValueError('Source dependency escapes the repository')
        result[identity] = fixture.sha(path.read_bytes())
    return result


def relevant_sources():
    review = dependency_review()
    names = set(review['current_sources'])
    names.update(review['launcher_and_dependency_config_source_maps'][review['current_source_basis']])
    names.update(review['pinned_project_input_source_maps'][review['current_source_basis']])
    return source_seals(names)


def capture_sources(inventory_sources=()):
    # Current pytest fake producers/importer are separate from native 6d/411 bytes.
    names = [REVIEW_PATH, 'tests/support/source_copy_native_evidence.py',
        'tests/support/source_copy_branch_evidence.py', 'tests/support/platform_filesystem.py',
        'tests/support/gateway_config.py', 'tests/unit/test_source_copy_capture.py',
        'tests/unit/test_source_copy_branch_evidence.py', 'tests/unit/test_source_copy_modern_collector.py',
        'tests/unit/test_source_copy_repeated_fixture.py', 'tests/unit/test_workflow_source_guard.py',
        'tests/unit/test_source_copy_saved_continuation_gateway.py', 'tests/unit/test_legacy_source_copy_collector.py',
        'tests/unit/test_field_interface_closure_gateway.py', 'tests/unit/test_object_graph_owned_choices_gateway.py',
        'tests/unit/test_object_graph_business_gateway.py', 'tests/maintenance/__init__.py',
        'tests/maintenance/source_identity.py', 'tests/maintenance/branch_coverage_audit.py',
        'tests/maintenance/branch_audit_completion.py', 'tests/maintenance/branch_audit_mapping.py',
        'tests/support/media_id_branch_evidence.py', 'tests/maintenance/interface_depth_inventory.py',
        'docs/branch-coverage-current-business.json', 'docs/branch-coverage-business-baseline.json',
        'docs/interface-depth-review-policy.json',
        'docs/branch-coverage-ownership.json', 'docs/branch-coverage-condition-sources.json',
        'docs/branch-coverage-requirements.json']
    return source_seals(set(names) | set(inventory_sources))


def _git(*argv):
    return subprocess.check_output(['git', *argv], cwd=audit.ROOT, text=True).strip()


def business_fact_descriptor(version):
    rows = json.loads((audit.ROOT / 'docs/branch-coverage-current-business.json').read_bytes())['rows']
    matching = [row for row in rows if row['id'] == version + '|source-copy-synth-owned-graph']
    anchor = next(row for row in dependency_review()['native_anchors'] if row['version'] == version)
    if len(matching) != 1: raise ValueError('Exact Source #180 business row missing')
    row = matching[0]; native = row['native_evidence']
    if (row['public_operation'] != 'object.copy' or native['candidate'] != anchor['native_candidate']
            or native['receipt_sha256'] != anchor['receipt']['sha256'] or native['diagnostic_only'] is not True
            or native['business_effect_verified'] is not False or native['host'] != 'wwise-console'
            or native['build'] != native_route(version).split('|')[2]):
        raise ValueError('Source #180 business row provenance or scope differs')
    return deepcopy(row)


def source_capture_plan(root, *, inventory):
    """Describe all five existing producer nodes and their separate source seals."""
    return {'contract': CAPTURE, 'root': str(Path(root).resolve()),
        'git_candidate': _git('rev-parse', 'HEAD'),
        'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
        'relevant_sources': relevant_sources(), 'capture_sources': capture_sources(inventory['sources']),
        'inventory_source_names': sorted(inventory['sources']),
        'nodes': {node: {'version': version, 'branches': selected_branches(inventory, version),
            'public': next(row for row in inventory['routes'] if row['id'] == version + '|function|' + URI),
            'business_descriptor': business_fact_descriptor(version)}
            for version, node in PUBLIC_NODES.items()},
        'reference_edges': {row['id']: row for row in inventory['native_coverage']['obligations']
                            if row['kind'] == 'reference' and row['route'] in {native_route(version) for version in PUBLIC_NODES}}}


def prepare_source_capture(root):
    """Freeze a clean candidate without launching pytest, Wwise or Codex."""
    if _git('status', '--porcelain'):
        raise ValueError('Source product capture requires a clean committed candidate')
    root = Path(root)
    context = source_capture_plan(root, inventory=audit.build_inventory())
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / 'context.json', context)
    return root / 'context.json'


def load_source_capture(path, nodeid):
    context = json.loads(Path(path).read_bytes())
    if (context.get('contract') != CAPTURE or context.get('git_candidate') != _git('rev-parse', 'HEAD')
            or {node: item.get('version') for node, item in context.get('nodes', {}).items()} != {node: version for version, node in PUBLIC_NODES.items()}
            or nodeid not in context['nodes'] or context.get('relevant_sources') != relevant_sources()
            or context.get('capture_sources') != capture_sources(context.get('inventory_source_names', ()))):
        raise ValueError('Exact frozen Source capture node or dependencies changed')
    return {**context, **context['nodes'][nodeid], 'nodeid': nodeid}



def pointer_contract(version):
    if version not in PUBLIC_NODES:
        raise ValueError('Unsupported Source branch attachment version')
    extra = {} if version in {'2021.1', '2022.1'} else {
        '/argsSchema/properties/' + name + '/@boolean/false': ('/native_call/args/' + name, None)
        for name in ('autoAddToSourceControl', 'autoCheckOutToSourceControl')}
    return {**POINTERS, **extra}


def native_route(version):
    build = '2021.1.14.8108' if version == '2021.1' else fixture.MODERN_ORIGINALS[version][0]
    return f'{version}|wwise-console|{build}|function|{URI}'


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
        if set(proof) not in ({'contract', 'receipt', 'files'}, {'contract', 'receipt', 'files', 'inputs'}) or proof['contract'] != PROOF:
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
    inputs = {}
    if receipt['version'] == '2021.1':
        keep(receipt['prelaunch'])
        for name in ('tests/_org/2021.1/Actor-Mixer Hierarchy/MIDI.wwu',
                     'tests/fixtures/source-copy/2021-native-donor.json',
                     'tests/fixtures/source-copy/2021-native-donor.wwu'):
            path = audit.ROOT / name; raw = fixture.read_file(path)
            link = {'path': str(path), 'sha256': fixture.sha(raw), 'size': len(raw)}
            keep(link); inputs[name] = link
    else:
        keep(receipt['original_midi'])
    for link in receipt['model_images'].values():
        index = keep(link)
        for entry in index['files'].values(): keep(entry['artifact_proof'])
    native_index = keep(receipt['native_file_proofs'])
    native = {row['native_file_proof']['path']: row for row in native_index['files']}
    field_links = [receipt['fixture_acceptance'][key] for key in ('loaded_scalar_observation', 'scalar_observation')]
    if receipt['version'] != '2021.1':
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
    if inputs: proof['inputs'] = inputs
    return write_json(output / 'proof.json', proof)


def _source_facts(proof, base):
    """Recheck shared scalar/root/graph guards against transported public facts."""
    files = ProofFiles(proof, base)
    receipt = files.read(proof['receipt'])
    version = receipt['version']
    modern = version != '2021.1'
    expected_contract = 'waapi-skill.' + ('modern' if modern else 'repeated') + '-source-copy-save-children-collector/v1'
    expected_profile = fixture.MODERN_PROFILE if modern else fixture.PROFILE
    expected_build = fixture.MODERN_ORIGINALS.get(version, ('2021.1.14.8108',))[0]
    if (version not in PUBLIC_NODES or receipt['contract'] != expected_contract
            or receipt['fixture_profile'] != expected_profile
            or receipt['native_build'] != expected_build
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
            **({} if version in {'2021.1', '2022.1'} else {'autoAddToSourceControl': False, 'autoCheckOutToSourceControl': False})}
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
    if modern:
        original = files.raw(receipt['original_midi'])
        if fixture.sha(original) != fixture.MODERN_ORIGINALS[version][2]:
            raise ValueError('Source pinned original differs')
        loaded, relative = original, fixture.MODERN_ORIGINALS[version][1]
    else:
        original, loaded = _legacy_source_input(files, receipt)
        relative = fixture.MIDI.as_posix()
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
        unit = fixture.saved_midi(images[phase], index=view, relative=relative,
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
    if modern:
        fields += [files.read(receipt[key]) for key in ('copied_scalar_observation', 'retained_scalar_observation')]
    graph_version = version if modern else None
    graphs = [fixture.source_graph([loaded], fixture.SOURCE, fixture.SOURCE_OWNER, version=graph_version),
              fixture.source_graph(images['before'], fixture.SOURCE, fixture.SOURCE_OWNER, version=graph_version),
              fixture.source_graph(images['after'], dispatch['result']['id'], receipt['destination_id'], version=graph_version),
              fixture.source_graph(images['after'], fixture.SOURCE, fixture.SOURCE_OWNER, version=graph_version)]
    ranges = [(0, phases[0]['verify_call_index']),
              (phases[1]['verify_call_index'] + 1, receipt['fixture_acceptance']['accepted_at_call_index'] + 1),
              (calls.index(final_call) + 1, len(calls)), (calls.index(final_call) + 1, len(calls))]
    if not modern:
        _legacy_source_graph_facts(files, receipt, calls, replies, graphs, fields, ranges, images, dispatch)
        if files.used != set(proof['files']):
            raise ValueError('Source portable proof has unused/unresolved dependency roots')
        return {'gateway': {'argv': final_call['argv'], 'exit_code': final_call['exit_code'], 'payload': final},
                'native_call': dispatch, 'version': version, 'business_fact_id': version + '|source-copy-synth-owned-graph'}
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



def _legacy_source_input(files, receipt):
    inputs = files.proof.get('inputs', {})
    expected = {'tests/_org/2021.1/Actor-Mixer Hierarchy/MIDI.wwu': fixture.ORIGINAL_SHA,
        'tests/fixtures/source-copy/2021-native-donor.json': '19af411284e604926c637bb9b26710d07ae2c2cf87faed9c126aefcf78620978',
        'tests/fixtures/source-copy/2021-native-donor.wwu': fixture.DONOR_SHA}
    if set(inputs) != set(expected): raise ValueError('2021 Source input closure differs')
    raw = {name: files.raw(link) for name, link in inputs.items()}
    if any(fixture.sha(raw[name]) != seal for name, seal in expected.items()):
        raise ValueError('2021 Source pinned input differs')
    original = raw['tests/_org/2021.1/Actor-Mixer Hierarchy/MIDI.wwu']
    donor = raw['tests/fixtures/source-copy/2021-native-donor.wwu']
    provenance = json.loads(raw['tests/fixtures/source-copy/2021-native-donor.json'])
    prelaunch = files.read(receipt['prelaunch'])
    needle = b'<Property Name="Osc1Level" Type="Real32" Value="-5"/>'
    start = original.index(b'<SourcePlugin Name="Wwise Synth One" ID="' + fixture.SOURCE.encode() + b'"')
    end = original.index(b'</SourcePlugin>', start)
    if original[start:end].count(needle) != 1: raise ValueError('2021 Source splice target differs')
    offset = original.index(needle, start, end); group = donor[2239:3641]
    loaded = original[:offset] + needle[:-2] + b'>' + group + b'</Property>' + original[offset + len(needle):]
    if (len(donor) != 4016 or fixture.sha(group) != fixture.SPAN_SHA or prelaunch['donor'] != provenance
            or prelaunch['profile'] != fixture.PROFILE or prelaunch['native_acceptance'] is not False
            or prelaunch['coverage_credit'] != 'none' or prelaunch['input_sha256'] != fixture.ORIGINAL_SHA
            or prelaunch['output_sha256'] != fixture.sha(loaded) or prelaunch['splice_offset'] != offset
            or prelaunch['input_bytes'] != len(original) or prelaunch['output_bytes'] != len(loaded)
            or receipt['fixture_acceptance']['prelaunch_output_sha256'] != fixture.sha(loaded)):
        raise ValueError('2021 Source prelaunch provenance differs')
    return original, loaded


def _legacy_source_graph_facts(files, receipt, calls, replies, graphs, fields, ranges, images, dispatch):
    index = files.read(receipt['native_file_proofs'])
    indexed = {row['native_file_proof']['path']: row for row in index['files']}
    lives = []
    for ordinal, (nodes, (start, stop)) in enumerate(zip(graphs, ranges)):
        live = {}
        for role, node in nodes.items():
            identity = node.get('ID')
            selected = [(call, reply) for call, reply in zip(calls[start:stop], replies[start:stop])
                        if call['argv'][:3] == ['query-object', '--exact-id', identity]]
            frames = []
            for call, reply in selected:
                row, = reply['agent_result']
                frames.append({key: value for key, value in row.items()
                               if key in {'id', 'name', 'type', 'path', 'class_id', 'parent', 'owner', 'notes', 'short_id'}})
            if not frames or any(frame != frames[0] for frame in frames):
                raise ValueError('2021 Source exact live frame missing or changed')
            live[role] = frames[0]
            if ordinal >= 2: continue
            snapshot = fields[ordinal][role]
            inventories = [reply['agent_result'] for call, reply in zip(calls[start:stop], replies[start:stop])
                           if call['argv'][:4] == ['metadata', 'list', '--exact-id', identity]]
            values = {key: value for call, reply in selected if '--include-field' in call['argv']
                      for row in reply['agent_result'] for key, value in row.get('properties', {}).items()}
            expected_names = 18 if role == 'source' else 3 if role.endswith('.rtpc') else 10 if role.endswith('.control') else 1
            unavailable = snapshot['untyped_reference_metadata']
            if (len(inventories) != 1 or inventories[0].get('complete') is not True
                    or inventories[0]['total_count'] != expected_names
                    or [field['name'] for field in inventories[0]['fields']] != snapshot['names']
                    or len(snapshot['names']) != len(set(snapshot['names']))
                    or values != snapshot['values'] or set(values) != set(snapshot['metadata'])
                    or set(values) != set(snapshot['native_metadata_authority'])
                    or set(snapshot['names']) != set(values) | set(unavailable)):
                raise ValueError('2021 Source typed/untyped inventory differs')
            if role.endswith('.rtpc'):
                details = [reply['agent_result']['metadata'] for call, reply in zip(calls[start:stop], replies[start:stop])
                           if call['argv'][:4] == ['metadata', 'detail', '--exact-id', identity]]
                if (set(unavailable) != {'ControlInput'} or unavailable['ControlInput'].get('type') != ''
                        or unavailable['ControlInput'].get('restriction', {}).get('type') == 'reference'
                        or details != [unavailable['ControlInput']]):
                    raise ValueError('2021 ControlInput untyped boundary differs')
            elif unavailable:
                raise ValueError('2021 unexpected unavailable field')
            for name, authorities in snapshot['native_metadata_authority'].items():
                if not authorities: raise ValueError('2021 Source typed metadata authority missing')
                for authority in authorities:
                    row = indexed[authority['path']]
                    packet = files.read(row['archive'])
                    if (authority != row['native_file_proof'] or packet['api'] != 'ak.wwise.core.object.getPropertyInfo'
                            or packet['ok'] is not True or packet['version'] != '2021.1'
                            or packet['result'] != snapshot['metadata'][name]):
                        raise ValueError('2021 Source typed metadata packet differs')
        for prop in ('OutputLevel', 'Osc1Level'):
            expression = f'from object "{live[prop + ".rtpc"]["id"]}" select @ControlInput'
            hopped = [reply['agent_result'] for call, reply in zip(calls[start:stop], replies[start:stop])
                      if call['argv'][:5] == ['query-object', '--advanced-waql', expression, '--max-results', '2']]
            # Retained exact frames after copy are also required by public reads;
            # the original2021 collector's explicit hop is on loaded/baseline/copied roles.
            if ordinal != 3 and (len(hopped) != 1 or any(
                    {key: value for key, value in row.items() if key in live[prop + '.control']} != live[prop + '.control']
                    for row in hopped[0]) or len(hopped[0]) != 1):
                raise ValueError('2021 Source canonical ControlInput hop differs')
        fixture.validate_frames(nodes, live, fixture.SOURCE_OWNER if ordinal != 2 else receipt['destination_id'])
        if ordinal < 2: fixture.validate_scalars(nodes, fields[ordinal])
        lives.append(live)
    facts = lambda snapshot: {role: {key: value for key, value in row.items() if key != 'native_metadata_authority'} for role, row in snapshot.items()}
    if lives[0] != lives[1] or lives[1] != lives[3] or facts(fields[0]) != facts(fields[1]):
        raise ValueError('2021 original Source fields or frames changed')
    oracle = fixture.repeated_copy_oracle(images['before'], images['after'], source_id=fixture.SOURCE,
        copied_id=dispatch['result']['id'], original_owner_id=fixture.SOURCE_OWNER,
        destination_id=receipt['destination_id'], before_live=lives[1], copied_live=lives[2])
    if (any(receipt['oracle'].get(key) != value for key, value in oracle.items())
            or 'copied_native_fields_preserved' in receipt['oracle'] or 'original_native_fields_preserved' in receipt['oracle']):
        raise ValueError('2021 Source seven-role/four-point saved oracle differs')


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
            or binding['source_business_fact'] != facts['business_fact_id']
            or (record.get('scope_kind') == 'product' and record.get('observations', {}).get('source') != facts)):
        raise ValueError('Source attachment does not prove this exact branch/public invocation')


def write_source_program_bundle(output, receipt_path, *, inventory, nodeid, phase_reports, scope_kind, capture_context=None):
    """Controlled rehearsal; product capture uses the shared pytest finalizer."""
    if phase_reports != {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}:
        raise ValueError('Source proof requires complete successful phases')
    if scope_kind not in {'controlled', 'product'} or (scope_kind == 'product' and capture_context is None):
        raise ValueError('Source product publication requires its frozen capture context')
    output = Path(output)
    proof_desc = export_source_proof(output, receipt_path)
    facts = source_facts(completion.read_sealed_artifact(proof_desc, output), output)
    version = facts['version']
    if capture_context is None:
        branches = selected_branches(inventory, version)
        public = next(row for row in inventory['routes'] if row['id'] == version + '|function|' + URI)
        candidate = inventory['native_coverage']['candidate_sha256']
    else:
        if version != capture_context['version']: raise ValueError('Source capture receipt version differs')
        branches, public, candidate = (capture_context[key] for key in ('branches', 'public', 'candidate_sha256'))
    record = {'candidate_sha256': candidate, 'scope_kind': scope_kind, 'evidence_kind': 'injected_client_program',
        'invocation': {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': nodeid, 'outcome': 'PASS'}]},
        'gateway': facts['gateway'], 'native_call': facts['native_call'], 'branch_assertions': {}}
    if capture_context is not None:
        record.update(git_candidate=capture_context['git_candidate'], relevant_sources=capture_context['relevant_sources'],
            capture_sources=capture_context['capture_sources'], observations={'source': deepcopy(facts)})
    bindings = {}
    for branch in branches:
        pointer, edge = pointer_contract(version)[branch['pointer']]
        if capture_context is not None: pointer = '/observations/source' + pointer
        record['branch_assertions'][branch['id']] = {'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
            'checks': [{'pointer': pointer, 'equals': completion.pointer_value(record, pointer)},
                       {'pointer': '/gateway/payload/agent_result', 'equals': facts['gateway']['payload']['agent_result']}]}
        binding = {'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
            'public_route': public['id'], 'public_route_sha256': audit.digest(public),
            'input': {'gateway_argv': facts['gateway']['argv']},
            **{key: {'source': source, 'selector': branch['pointer']} for key, source in SYMBOLS.items()},
            'observation_pointer': pointer, 'native_hosts': ['wwise-console'], 'evidence': {}}
        if capture_context is not None:
            binding.update(dispatch_pointer='/observations/source/native_call',
                relevant_sources=list(capture_context['relevant_sources']))
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
    capture = write_json(output / 'capture.json', {'contract': 'waapi-skill.source-copy-program-' + ('rehearsal' if capture_context is None else 'capture') + '/v1',
        'scope_kind': scope_kind, 'candidate_sha256': candidate, 'phase_reports': phase_reports, 'native_credit': False,
        **({} if capture_context is None else {'git_candidate': capture_context['git_candidate'],
            'outcome': 'PASS', 'source_unchanged': True})})
    attachment = write_json(output / 'attachment.json', {'contract': ATTACHMENT,
        'branch_ids': list(bindings), 'business_fact_id': facts['business_fact_id'], 'proof': proof_desc,
        **({} if capture_context is None else {'business_descriptor': capture_context['business_descriptor']})})
    write_json(output / 'index.json', {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.',
        'entries': [{'id': 'source-' + version, 'bindings': bound, 'origin': {'bindings': bound, 'program': {k: program[k] for k in ('artifact', 'sha256')},
            'requirements': required, 'capture': capture}}], 'source_attachments': [attachment]})
    return output / 'index.json'


def finish_source_capture(context, phase_reports, receipt_path):
    """Publish once after the shared finalizer observes every pytest phase."""
    if phase_reports != {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}:
        raise ValueError('Source publication requires complete successful phases')
    if (context['git_candidate'] != _git('rev-parse', 'HEAD')
            or context['relevant_sources'] != relevant_sources() or context['capture_sources'] != capture_sources(context.get('inventory_source_names', ()))):
        raise ValueError('Frozen Source capture dependencies changed')
    root = Path(context['root']); root.mkdir(parents=True, exist_ok=True)
    target = root / context['version']
    if target.exists(): raise ValueError('Never replace an earlier Source capture')
    # Output names are relative and therefore survive this atomic publication.
    pending = Path(tempfile.mkdtemp(prefix='.' + context['version'] + '-pending-', dir=root))
    bundle = pending / 'bundle'
    index = write_source_program_bundle(bundle, receipt_path, inventory=None, nodeid=context['nodeid'],
        phase_reports=phase_reports, scope_kind='product', capture_context=context)
    requirements = json.loads((bundle / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, requirements)
    for branch in context['branches']:
        binding = document['bindings'][branch['id']]
        result = completion.evidence_result(binding['evidence']['program'], branch, context['candidate_sha256'],
            'program', 'product', base, binding, source_root=audit.ROOT, reference_edges=context['reference_edges'])
        if result != ('passed', None): raise ValueError('Source program reader rejected capture: ' + str(result))
    bundle.rename(target)
    pending.rmdir()
    return target / 'index.json'


def register_source_capture(item, receipt_path):
    """Optional instrumentation of the existing public collector fake tests."""
    path = os.environ.get('WAAPI_SOURCE_COPY_CAPTURE_CONTEXT')
    if path:
        from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
        context = load_source_capture(Path(path), item.nodeid)
        register_exact_evidence_finalizer(item,
            lambda reports: finish_source_capture(context, reports, receipt_path))


def portable_source_attachments(descriptors, bindings, read, base):
    if not isinstance(descriptors, list): raise ValueError('Closed Source attachment list required')
    attached, business = set(), []
    for descriptor in descriptors:
        attachment = read(descriptor)
        if set(attachment) not in ({'contract', 'branch_ids', 'business_fact_id', 'proof'},
                {'contract', 'branch_ids', 'business_fact_id', 'proof', 'business_descriptor'}) or attachment['contract'] != ATTACHMENT:
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
            program = completion.read_sealed_artifact(binding['evidence']['program'], base)
            if program.get('scope_kind') == 'product' and attachment.get('business_descriptor') != business_fact_descriptor(facts['version']):
                raise ValueError('Source scoped #180 business descriptor differs')
            attached.add(identity)
            binding['source_copy_proof'] = deepcopy(attachment['proof'])
            binding['source_business_fact'] = facts['business_fact_id']
        business.append(facts['business_fact_id'])
    return business
