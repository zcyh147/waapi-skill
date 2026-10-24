"""Native denominator and evidence evaluation for branch_coverage_audit.

This is part of the existing maintainer audit, never a runtime execution route.
Native sources are enumerated before any public implementation is joined.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import sys


def native_coverage(root, inventory, *, digest, schema_branches, load):
    sys.path.insert(0, str(root / 'skills/waapi-skill'))
    from wwise_waapi.native_catalog import load_native_catalog, NATIVE_HOSTS
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference

    owners = load(root / 'docs/branch-coverage-ownership.json')['routes']
    public = {row['id']: row for row in inventory['routes']}
    catalogs, routes, obligations = {}, [], []
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for host in NATIVE_HOSTS:
            catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
            build = catalog['provenance']['build']
            definitions = catalog['definitions']
            graph = DefinitionGraph(**{key: definitions[key] for key in ('contract', 'version', 'wwise_build', 'source_file_names', 'documents', 'inventory_sha256')})
            catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
            for kind, key in (('function', 'functions'), ('topic', 'topics')):
                for uri in catalog[key]:
                    native_id = '|'.join((version, host, build, kind, uri))
                    public_id = '|'.join((version, kind, uri))
                    row = {'id': native_id, 'version': version, 'host': host, 'build': build,
                           'kind': kind, 'uri': uri, 'native_schema_sha256': digest(catalog['schemas'][uri]),
                           'public_route': public_id if public_id in public else None}
                    routes.append(row)
                    owner = owners.get(kind + '|' + uri, {}).get('owner_issue')
                    for section in ('argsSchema', 'optionsSchema', 'resultSchema', 'publishSchema'):
                        if section not in catalog['schemas'][uri]:
                            continue
                        root_schema = catalog['schemas'][uri][section]
                        visited = set()

                        def visit(schema, pointer, context_root, document, active):
                            for branch in schema_branches(schema, pointer):
                                record = {'id': native_id + '|' + branch['pointer'], 'route': native_id,
                                    'pointer': branch['pointer'], 'kind': branch['kind'], 'shape_sha256': digest(branch['value']),
                                    'owner_issue': owner, 'parent_issue': 174, 'blocks_issue': 195,
                                    'state': 'missing_implementation' if row['public_route'] is None else 'unresolved'}
                                if branch['kind'] != 'schema':
                                    record['value'] = branch['value']
                                obligations.append(record)
                                if branch['kind'] != 'reference':
                                    continue
                                resolved = resolve_schema_reference(branch['value'], root_schema=context_root, graph=graph)
                                target_document = document if resolved.document_name == '<schema>' else resolved.document_name
                                identity = (target_document, resolved.pointer)
                                target_pointer = '/' + section + '/@definition/' + target_document + resolved.pointer
                                record['reference'] = {'target': native_id + '|' + target_pointer,
                                    'recursive': identity in active, 'document': target_document,
                                    'target_sha256': digest(resolved.target)}
                                if identity in visited:
                                    continue
                                visited.add(identity)
                                target_root = context_root if resolved.document_name == '<schema>' else graph.documents[target_document]
                                visit(resolved.target, target_pointer, target_root, target_document, active | {identity})

                        visit(root_schema, '/' + section, root_schema, '<schema>', set())
    obligations.extend(installed_obligations(root, digest=digest, load=load))
    if len({r['id'] for r in obligations}) != len(obligations):
        raise ValueError('duplicate native obligation identity')
    states = dict(sorted(Counter(r['state'] for r in obligations).items()))
    return {'candidate_sha256': candidate_identity(root, inventory, catalogs, digest=digest), 'catalogs': catalogs, 'routes': routes, 'obligations': obligations,
            'completion': {'complete': bool(obligations) and all(r['state'] == 'verified' for r in obligations),
                           'states': states}}


def installed_obligations(root, *, digest, load):
    """Source occurrences are investigation obligations, not native applicability."""
    import xml.etree.ElementTree as ET
    data = load(root / 'docs/branch-coverage-condition-sources.json')
    records = []
    for corpus in data['corpora']:
        for lane in corpus['lanes']:
            build = lane['build']
            version = '.'.join(build.split('.')[:2])
            files = {row['path']: row for row in lane['files']}
            for index, occurrence in enumerate(lane['rows']):
                xml = ET.fromstring(occurrence['xml'])
                alternatives = [('condition', occurrence['xml'])]
                for n, child in enumerate(xml.iter()):
                    if child.tag in ('Enumeration', 'Range', 'ReferenceIsSet'):
                        alternatives.append((f'{child.tag}/{n}', {'attributes': child.attrib,
                            'values': [v.text for v in child if v.tag == 'Value'], 'text': child.text}))
                        if child.tag == 'Enumeration':
                            alternatives.extend((f'Enumeration/{n}/value/{i}', v.text) for i, v in enumerate(child) if v.tag == 'Value')
                for mode, owner in (('existing-object', 177), ('new-object', 178)):
                    for alternative, value in alternatives:
                        pointer = occurrence['file'] + '|' + occurrence['path'] + f'/{index}/{alternative}'
                        identity = f'{version}|installed|{build}|{corpus["name"]}|{mode}|{pointer}'
                        records.append({'id': identity, 'route': None, 'version': version, 'build': build,
                            'pointer': pointer, 'kind': 'metadata_condition', 'shape_sha256': digest(value),
                            'source_file_sha256': files[occurrence['file']]['sha256'],
                            'source_evidence_kind': 'installed_definition_only',
                            'business_dimensions': {'operation_mode': mode, 'condition': occurrence['attributes'],
                                'alternative': alternative, 'class': occurrence.get('class'),
                                'host_applicability': 'unverified', 'condition_value': value if alternative != 'condition' else None},
                            # Existing-instance edits do not require every
                            # plug-in creation or placement mode to be ready.
                            'owner_issue': owner, 'dependencies': ([177] + ([179] if corpus['name'] == 'plugin-condition' else []) if mode == 'new-object' else []),
                            'parent_issue': 174, 'blocks_issue': 195, 'state': 'unresolved'})
            for source in lane['files']:
                for plugin in source.get('classes', []):
                    placements = {'EffectPlugin': ('owner-local-effect', 'independent-shareset'),
                                  'SourcePlugin': ('sound-owned-source',), 'SinkPlugin': ('audio-device',),
                                  'ConversionPlugin': ('conversion-settings',),
                                  'MetadataPlugin': ('placement-unresolved',)}.get(plugin['kind'])
                    if placements is None:
                        raise ValueError('unassigned plugin topology: ' + plugin['kind'])
                    for placement in placements:
                        for mode in ('existing-object', 'new-object'):
                            dimensions = {'class_name': plugin['Name'], 'class': plugin, 'placement': placement,
                                          'operation_mode': mode, 'host_applicability': 'unverified'}
                            records.append({'id': f'{version}|installed|{build}|plugin|{source["path"]}|{digest(dimensions)}',
                                'route': None, 'version': version, 'build': build, 'pointer': source['path'],
                                'kind': 'plugin_topology', 'shape_sha256': digest(dimensions),
                                'source_file_sha256': source['sha256'], 'source_evidence_kind': 'installed_definition_only',
                                'business_dimensions': dimensions, 'owner_issue': 179, 'dependencies': [177, 178],
                                'parent_issue': 174, 'blocks_issue': 195, 'state': 'unresolved'})
    for path in sorted((root / 'skills/waapi-skill/resources/metadata').glob('*/object-types.json')):
        catalog = load(path)
        metadata = catalog['metadata']
        version, build = metadata['wwise_version_target'], metadata['wwise_build']
        for target in catalog['types']:
            for mode in ('new-object', 'existing-object'):
                owner = 179 if target['type'] in ('Effect', 'Source', 'AudioDevice', 'Conversion', 'Metadata') else 178 if mode == 'new-object' else 180
                dimensions = {'class_name': target['name'], 'class_id': target['classId'], 'native_type': target['type'],
                              'operation_mode': mode, 'placement': 'applicability-unresolved'}
                records.append({'id': f'{version}|metadata|{build}|target|{target["classId"]}|{mode}',
                    'route': None, 'version': version, 'build': build, 'pointer': '/types/' + str(target['classId']),
                    'kind': 'target_applicability', 'shape_sha256': digest(target),
                    'source_file_sha256': digest(catalog), 'source_evidence_kind': 'type_discovery_only',
                    'business_dimensions': dimensions, 'owner_issue': owner, 'dependencies': [177, 181],
                    'parent_issue': 174, 'blocks_issue': 195, 'state': 'unresolved'})
    return records


def candidate_identity(root, inventory, catalogs, *, digest):
    """Relevant source identity, independent of Git timestamps and local state."""
    import hashlib
    sources = dict(inventory['sources'])
    skill = root / 'skills/waapi-skill'
    for directory in ('scripts', 'wwise_waapi', 'resources', 'references'):
        for path in sorted((skill / directory).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py', '.json', '.md'):
                sources[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    sources['skills/waapi-skill/SKILL.md'] = digest((skill / 'SKILL.md').read_text(encoding='utf-8'))
    for name in ('branch_coverage_audit.py', 'branch_audit_completion.py'):
        path = 'tests/maintenance/' + name
        sources[path] = digest((root / path).read_text(encoding='utf-8'))
    for name in ('branch-coverage-ownership.json', 'branch-coverage-condition-sources.json', 'branch-coverage-requirements.json'):
        path = 'docs/' + name
        sources[path] = digest((root / path).read_text(encoding='utf-8'))
    for path in sorted((root / 'skills/waapi-skill/resources/metadata').glob('*/object-types.json')):
        sources[str(path.relative_to(root))] = digest(path.read_text(encoding='utf-8'))
    # Source attachment producer/finalizer bytes are part of the current
    # program candidate. Historical trees without this adapter retain their
    # original source context; missing/changed current files change identity.
    for name in ('tests/support/source_copy_branch_evidence.py', 'tests/support/exact_evidence_finalization.py',
                 'tests/unit/test_source_copy_branch_evidence.py', 'tests/support/source_copy_native_evidence.py',
                 'tests/unit/test_source_copy_capture.py',
                 'tests/support/runtime_observation_evidence.py',
                 'tests/unit/test_runtime_observation_branch_evidence.py',
                 'tests/unit/test_rtpc_field_branch_evidence.py',
                 'tests/support/condition_mechanism_reuse.py', 'tests/support/condition_source_resolution.py',
                 'tests/maintenance/reconcile_condition_sources.py',
                 'tests/fixtures/metadata-conditions/lfo-eq-mechanism-review.json',
                 'tests/fixtures/metadata-conditions/lfo-eq-originals.json.gz',
                 'tests/unit/test_condition_mechanism_reuse.py', 'tests/unit/test_condition_source_resolution.py',
                 'tests/support/condition_completion_mapping.py', 'tests/maintenance/map_condition_completion.py',
                 'tests/unit/test_condition_completion_mapping.py', 'tests/unit/test_condition_completion_reader.py',
                 'tests/fixtures/metadata-conditions/condition-completion-review.json',
                 'tests/fixtures/metadata-conditions/condition-completion-proof-inputs.json.gz'):
        path = root / name
        if path.is_file():
            sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest({'sources': sources, 'native_catalogs': catalogs})


def pointer_value(document, pointer):
    if pointer == '':
        return document
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('invalid evidence pointer')
    for token in pointer[1:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document


def read_sealed_artifact(descriptor, base):
    import hashlib
    from pathlib import Path
    import json
    path = Path(descriptor['artifact'])
    if not path.is_absolute():
        path = base / path
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != descriptor['sha256']:
        raise ValueError('artifact digest mismatch')
    if 'record_index' in descriptor:
        index = descriptor['record_index']
        if type(index) is not int or index < 0:
            raise ValueError('invalid preserved JSONL record index')
        return json.loads(raw.splitlines()[index])
    return json.loads(raw)


def proves_alternative(check, branch):
    """The same field assertion must establish the claimed alternative."""
    kind, value = branch['kind'], branch.get('value')
    if kind == 'optional_presence':
        return check.get('absent') is True if value == 'absent' else 'equals' in check or 'cardinality' in check
    if kind == 'collection_cardinality':
        return check.get('cardinality') == value
    if kind in ('enum_value', 'boolean_value', 'nullable', 'empty_string', 'empty_object', 'default'):
        return 'equals' in check and type(check['equals']) is type(value) and check['equals'] == value
    if kind == 'type_variant':
        observed = check.get('equals')
        types = {'null': (type(None),), 'boolean': (bool,), 'integer': (int,), 'number': (int, float),
                 'string': (str,), 'array': (list,), 'object': (dict,)}
        return 'equals' in check and type(observed) in types.get(value, ())
    return 'equals' in check or 'cardinality' in check


def native_host_context(info, command_line_key):
    version = info['version']
    if type(info.get(command_line_key)) is not bool:
        raise ValueError('native host identity missing')
    build = '.'.join(str(version[k]) for k in ('year', 'major', 'minor', 'build'))
    return {'version': '.'.join(build.split('.')[:2]), 'build': build,
            'host': 'wwise-console' if info[command_line_key] else 'wwise-authoring'}


def read_category_run(descriptor, base):
    """Read the existing host-category v3 producer, without granting family credit."""
    run = read_sealed_artifact(descriptor, base)
    invocation = run['invocation']
    if (run.get('contract') != 'waapi-skill.host-category-evidence/v3'
            or invocation.get('phase') != 'final' or invocation.get('outcome') != 'PASS'
            or not any(r == {'nodeid': descriptor['nodeid'], 'outcome': 'PASS'} for r in invocation['node_outcomes'])):
        raise ValueError('native exact node has no finalized PASS')
    context = native_host_context(run['host'], 'is_command_line')
    source, residual = run['source'], run['residual_state']
    if (context['version'] != run['version'] or len(run['candidate']) != 40 or any(c not in '0123456789abcdef' for c in run['candidate'])
            or not source.get('hash_before') or source['hash_before'] != source.get('hash_after')
            or source.get('mtime_before_ns') is None or source['mtime_before_ns'] != source.get('mtime_after_ns')
            or residual.get('sandbox') != 'deleted' or residual.get('residual_processes') != []
            or residual.get('process_cleanup') != 'cleaned'):
        raise ValueError('native source preservation/cleanup/candidate mismatch')
    if any(row.get('category') == 'authoring-layout' for row in run['categories']):
        validate_authoring_batch_finalization(run, base)
    return dict(context, candidate=run['candidate'], record=run)


def validate_authoring_batch_finalization(run, base, *, read_bytes=None):
    """New shared Authoring rows need the whole completed batch publication."""
    import hashlib
    import json
    from pathlib import Path, PurePosixPath
    def load(descriptor):
        if read_bytes is None:
            return read_sealed_artifact(descriptor, base)
        raw = read_bytes(descriptor['artifact'])
        if hashlib.sha256(raw).hexdigest() != descriptor['sha256']:
            raise ValueError('original finalization artifact digest differs')
        return json.loads(raw)
    try:
        categories = run['categories']
        descriptors = [row['batch_finalization'] for row in categories]
        if not descriptors or any(row != descriptors[0] for row in descriptors):
            raise ValueError('node finalization links differ')
        seal = load(descriptors[0])
        invocation = run['invocation']
        lifecycle = seal['lifecycle']
        if (seal['contract'] != 'waapi-skill.authoring-batch-finalization/v1' or seal['outcome'] != 'PASS'
                or any(seal[key] != run[key] for key in ('candidate', 'version', 'host', 'transactions'))
                or any(seal[key] != invocation[key] for key in ('selected_test_nodeids', 'node_outcomes', 'started_at_unix_ns'))
                or any(row['outcome'] != 'PASS' for row in seal['node_outcomes'])
                or len(set(seal['selected_test_nodeids'])) != len(seal['selected_test_nodeids'])
                or len(seal['node_outcomes']) != len(seal['selected_test_nodeids'])
                or {row['nodeid'] for row in seal['node_outcomes']} != set(seal['selected_test_nodeids'])
                or {row['nodeid'] for row in categories} != set(seal['selected_test_nodeids'])
                or len({(row['nodeid'], row['category']) for row in categories}) != len(categories)
                or lifecycle['final_status'] != 'PASS' or lifecycle['sandbox_retained'] is not False or lifecycle['errors']
                or lifecycle['source_hash_after']['digest'] != run['source']['hash_after']
                or lifecycle['source_mtime_after_ns'] != run['source']['mtime_after_ns']
                or seal['resources'].get('residual_processes') != []
                or seal['resources']['cleanup_report']['process_exited'] is not True
                or seal['resources']['cleanup_report']['residual_processes'] != []
                or seal['resources']['cleanup_report']['wine_prefix'] != seal['resources']['owned_prefix']
                or seal['resources']['fresh_inspection']['row_count'] < 1
                or seal['resources']['port']['released'] is not True
                or seal['source_context']['candidate'] != run['candidate']):
            raise ValueError('batch context or final proof differs')
        for category in categories:
            nodeid = category['nodeid']
            observation = category['observation_artifact']
            if observation != seal['observations'][nodeid]:
                raise ValueError('node observation links differ')
            raw = (read_bytes(observation['path']) if read_bytes else Path(observation['path']).read_bytes())
            if len(raw) != observation['bytes'] or hashlib.sha256(raw).hexdigest() != observation['sha256']:
                raise ValueError('node original observation seal differs')
            original = json.loads(raw)
            if (original['nodeid'] != nodeid or original['candidate'] != run['candidate']
                    or original['source_context'] != seal['source_context']):
                raise ValueError('node original context differs')
            profiler_report = None
            for artifact_name, artifact in original['artifacts'].items():
                root = PurePosixPath(artifact['path']) if read_bytes else Path(artifact['path'])
                for entry in artifact['files']:
                    path = root / entry['path']
                    if read_bytes is None:
                        path = path.resolve()
                    if '..' in path.parts or not path.is_relative_to(root if read_bytes else root.resolve()):
                        raise ValueError('node artifact escaped its archive')
                    content = read_bytes(str(path)) if read_bytes else path.read_bytes()
                    if len(content) != entry['bytes'] or hashlib.sha256(content).hexdigest() != entry['sha256']:
                        raise ValueError('node archived evidence differs')
                    if artifact_name == 'native-evidence' and entry['path'] == 'profiler-capture.json':
                        profiler_report = json.loads(content)
            claimed = {row['category']: row for row in categories if row['nodeid'] == nodeid}
            if profiler_report is None:
                # Historical layout nodes predate the outcome report. Their
                # closed producer shape is one layout category per passed node.
                if set(claimed) != {'authoring-layout'} or claimed['authoring-layout']['status'] != 'PASS':
                    raise ValueError('archived category roster or status differs')
            else:
                # The archived report owns its historical outcome roster. Never
                # import today's collector roster to reinterpret that evidence.
                outcomes = profiler_report.get('outcomes')
                if (profiler_report.get('contract') != 'waapi-skill.owned-profiler-capture/v1'
                        or profiler_report.get('candidate') != run['candidate']
                        or profiler_report.get('version') != run['version']
                        or not isinstance(outcomes, dict) or not outcomes or set(claimed) != set(outcomes)):
                    raise ValueError('archived category roster or status differs')
                for name, observed in outcomes.items():
                    business = observed.get('outcome')
                    expected_status = {'PASS': 'PASS', 'FAIL': 'FAIL', 'BLOCKED': 'blocked'}.get(business)
                    if (expected_status is None or claimed[name]['status'] != expected_status
                            or claimed[name].get('business_outcome') != business):
                        raise ValueError('archived category roster or status differs')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'Authoring batch finalization is incomplete: {exc}') from exc


def read_r51_metadata_run(descriptor, base):
    """One sealed read-only protocol; its blocked copy category stays blocked."""
    import json
    fields = {'contract', 'category', 'observation', 'status', 'identity', 'reply', 'native', 'call_index'}
    if set(descriptor) != fields or type(descriptor['call_index']) is not int:
        raise ValueError('closed R51 metadata archive descriptor required')
    for name in ('observation', 'status', 'identity', 'reply', 'native'):
        if set(descriptor[name]) != {'artifact', 'sha256'}:
            raise ValueError('closed R51 original artifact descriptor required')
    category = descriptor['category']
    node = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::test_legacy_original_source_owned_read_console_diagnostic'
    if set(category) != {'artifact', 'sha256', 'record_index', 'nodeid'} or category['nodeid'] != node:
        raise ValueError('exact R51 original read node required')
    context = read_category_run(category, base)
    if (context['candidate'] != '90c1089b77e9a9d5695224d312bff9a3ab8b5c18'
            or (context['host'], context['build']) != ('wwise-console', '2021.1.14.8108')
            or context['record']['transactions'] != []):
        raise ValueError('original R51 host/build/source mismatch')
    original = next(row for row in context['record']['categories'] if row['category'] == 'legacy-original-source-owned-read')
    if original.get('status') != 'blocked' or original.get('diagnostic_only') is not True or original.get('business_effect_verified') is not False:
        raise ValueError('original blocked business status must remain blocked')
    if descriptor['observation']['sha256'] != original['observation_sha256']:
        raise ValueError('original R51 observation link changed')
    body = read_sealed_artifact(descriptor['observation'], base)
    if (body['candidate'] != context['candidate'] or body['read_only'] is not True
            or body['diagnostic_only'] is not True or body['collection_complete'] is not True
            or body['business_effect_verified'] is not False or body['transaction_ids'] != []):
        raise ValueError('R51 metadata read protocol incomplete or promoted to business proof')
    status_call, call = body['calls'][0], body['calls'][descriptor['call_index']]
    for name, link in (('status', status_call['reply']), ('identity', body['calls'][3]['reply']), ('reply', call['reply'])):
        if descriptor[name]['sha256'] != link['sha256']:
            raise ValueError('original R51 public reply link changed')
    status = read_sealed_artifact(descriptor['status'], base)
    payload = read_sealed_artifact(descriptor['reply'], base)
    result = payload['agent_result']
    field = result['metadata']['name']
    object_id = '{CE99046D-D354-422D-A7BB-F1305FF00B2F}'
    if (status_call['argv'] != ['status'] or status_call['exit_code'] != 0 or status.get('ok') is not True
            or native_host_context(status['wwise'], 'isCommandLine') != {k: context[k] for k in ('version','build','host')}
            or call['exit_code'] != 0 or payload.get('ok') is not True or payload.get('is_command_line') is not True
            or payload.get('detected_version') != context['version'] or result.get('complete') is not True
            or field not in ('Color', 'ControlInput', 'OverrideColor')
            or result['scope'] != {'kind': 'object', 'object': object_id}
            or call['argv'] != ['metadata','detail','--exact-id',object_id,'--selection',result['selection']]):
        raise ValueError('exact R51 original public metadata input/result mismatch')
    identity_reply = read_sealed_artifact(descriptor['identity'], base)
    for reply in (status,identity_reply,payload):
        if (reply['endpoint'] != status['endpoint'] or reply['session_context']['endpoint'] != status['endpoint']
                or reply['detected_version'] != context['version'] or reply['is_command_line'] is not True
                or reply['session_context']['available'] is not True
                or reply['session_context']['adapter_version'] != context['version']):
            raise ValueError('Original R51 public endpoint/host/version identity differs')
    identity, = identity_reply['agent_result']
    if (body['calls'][3]['exit_code'] != 0 or body['calls'][3]['argv'][:3] != ['query-object','--exact-id',object_id]
            or identity_reply.get('ok') is not True or identity['id'] != object_id
            or identity['class_id'] != 1441808 or identity['type'] != 'RTPC'
            or body['owned_observation']['rtpc_id'] != object_id):
        raise ValueError('Original R51 exact object/class metadata scope changed')
    uri = 'ak.wwise.core.object.getPropertyInfo'
    dispatch, = [row for row in payload['calls'] if row['api'] == uri]
    native_link, = [row for row in body['native_evidence'] if row['native_path'] == dispatch['evidence_path']]
    if descriptor['native']['sha256'] != native_link['sha256']:
        raise ValueError('original R51 native archive link changed')
    native = read_sealed_artifact(descriptor['native'], base)
    if (native['api'] != uri or native['version'] != context['version'] or native.get('ok') is not True
            or native.get('dry_run') is not False or native['result']['name'] != field
            or json.dumps(native['result'], sort_keys=True, allow_nan=False) != json.dumps(
                {name: result['metadata'][name] for name in native['result']}, sort_keys=True, allow_nan=False)):
        raise ValueError('original R51 exact native/public metadata mismatch')
    return {**context, 'format': descriptor['contract'], 'business_category_status': original['status'],
        'native_result': native['result'], 'native_sha256': descriptor['native']['sha256'],
        'gateway': {'argv': call['argv'], 'exit_code': call['exit_code'], 'payload': payload},
        'receipt_sha256': descriptor['reply']['sha256']}


def read_metadata_run(descriptor, base, *, historical_class=False):
    """Read sealed ScenarioLifecycle/v3 captures and their original public receipts."""
    import hashlib
    import json
    from pathlib import Path
    if descriptor.get('contract') == 'waapi-skill.r51-metadata-read/v1':
        return read_r51_metadata_run(descriptor, base)
    class_read = descriptor.get('contract') == 'waapi-skill.class-metadata-read/v1'
    if class_read and (set(descriptor) != {'contract','root','seal','status_receipt','receipt','target_index'}
            or set(descriptor['seal']) != {'artifact','sha256'}
            or type(descriptor['target_index']) is not int or descriptor['target_index'] < 0):
        raise ValueError('Closed class metadata original descriptor required')
    seal = read_sealed_artifact(descriptor['seal'], base)
    root = Path(descriptor['root'])
    if not root.is_absolute():
        root = base / root
    files = {r['path']: r for r in seal['files']}
    if class_read and (seal.get('contract') != 'waapi-skill.class-metadata-seal/v1'
            or len(files) != len(seal['files']) or len(files) > 512
            or any(set(entry) != {'path','bytes','sha256'} for entry in seal['files'])):
        raise ValueError('Closed bounded class metadata archive required')
    def read(name):
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('metadata seal path outside capture')
        raw = path.read_bytes()
        entry = files[name]
        if hashlib.sha256(raw).hexdigest() != entry['sha256'] or len(raw) != entry['bytes']:
            raise ValueError('metadata external seal mismatch')
        return json.loads(raw)
    summary, ready, plan, cleanup = (read(n + '.json') for n in ('summary', 'ready', 'plan', 'cleanup'))
    lifecycle = summary['lifecycle']
    if (summary['status'] != 'PASS' or lifecycle['contract'] != 'waapi-skill.codex-semantic-scenario-lifecycle/v3'
            or lifecycle['final_status'] != 'PASS' or lifecycle['sandbox_retained'] is not False or lifecycle['errors']
            or not lifecycle['source_hash_before'].get('digest') or lifecycle['source_hash_before'].get('strategy') != 'full'
            or lifecycle['source_hash_before'] != lifecycle['source_hash_after']
            or lifecycle['source_mtime_before_ns'] != lifecycle['source_mtime_after_ns']
            or ready['source_hash_before'] != lifecycle['source_hash_before']
            or ready['source_mtime_before_ns'] != lifecycle['source_mtime_before_ns']
            or cleanup['process_exited'] is not True or cleanup['residual_processes'] != []):
        raise ValueError('metadata lifecycle/source preservation/cleanup incomplete')
    context = native_host_context(ready['get_info'], 'isCommandLine')
    status_prefix, prefix = descriptor['status_receipt'], descriptor['receipt']
    status = read(status_prefix + '.stdout')
    status_exit = read(status_prefix + '.exit.json')
    status_command = read(status_prefix + '.command.json')
    payload, command, result = (read(prefix + suffix) for suffix in ('.stdout', '.command.json', '.exit.json'))
    exact = read(prefix + '.agent-result.json')
    if (native_host_context(status['wwise'], 'isCommandLine') != context or status.get('ok') is not True
            or status_command['gateway_arguments'] != ['status'] or status_exit['exit_code'] != 0
            or plan['build'] != context['build'] or plan['host'] != context['host']
            or lifecycle['version'] != context['version']
            or payload.get('ok') is not True or payload.get('agent_result') != exact
            or result['exit_code'] != 0 or result['launched'] is not True or result['child_reaped'] is not True
            or command['gateway_arguments'][:2] != ['metadata', 'detail']):
        raise ValueError('metadata public receipt/host/build mismatch')
    repositories = plan['repositories']
    if len(repositories) != 1 or len(repositories[0]['commit']) != 40:
        raise ValueError('metadata exact source candidate missing')
    repository = repositories[0]
    from tests.maintenance.collect_class_metadata import collection_source_map
    sources = collection_source_map(plan['source_seals'],repository['checkout'])
    if class_read:
        import math
        from tests.maintenance import collect_class_metadata as collector
        targets = read('targets.json')
        target = targets[descriptor['target_index']]
        selected = collector.collection_plan(context['version'],cohort=plan.get('cohort','r54'))
        expected_fields = {(scope,field) for scope,fields in selected['targets'].items() for field in fields}
        if (any(plan[key] != value for key,value in selected.items())
                or plan.get('observation_origin') not in {'native_scenario_lifecycle','controlled_public_gateway'}
                or any(character not in '0123456789abcdef' for character in repository['commit'])
                or set(plan['actual_deadlines']) != {'readiness_seconds','total_seconds'}
                or any(type(value) not in (int,float) or not math.isfinite(value) or not 0 < value <= 3600
                    for value in plan['actual_deadlines'].values())
                or len(targets) != len(expected_fields)
                or {(row['scope'],row['field']) for row in targets} != expected_fields
                or any(row['status'] != 'captured' for row in targets)
                or summary['project_mutation_commands'] != 0 or summary['agent_started'] is not False
                or target['status'] != 'captured' or target['detail_receipt'] != prefix
                or target['field'] not in selected['targets'].get(target['scope'],[])
                or command['gateway_arguments'] != ['metadata','detail','--custom-kind',target['scope'],'--selection',exact['selection']]
                or payload['endpoint'] != status['endpoint']
                or payload['session_context']['endpoint'] != status['endpoint']
                or payload['session_context']['project_modification_policy'] != 'read_only'
                or status['session_context']['project_modification_policy'] != 'read_only'
                or type(status['wwise'].get('processId')) is not int or status['wwise']['processId'] <= 0
                or not isinstance(status['wwise'].get('sessionId'),str) or not status['wwise']['sessionId']
                or status['endpoint']['host'] != ready['host'] or status['endpoint']['port'] != ready['port']
                or any(status['wwise'].get(key) != ready['get_info'].get(key) for key in ('processId','sessionId'))
                or files[target['native_receipt']]['sha256'] != target['native_sha256']
                or files[target['native_receipt']]['bytes'] != target['native_bytes']):
            raise ValueError('Exact class metadata schedule/input/native link changed')
        native = read(target['native_receipt'])
        if native['evidence_path'] != target['native_path']:
            raise ValueError('Original class native/public path identity changed')
        collector.validate_native_pair(payload,native,context['version'],target['scope'],target['field'],cohort=plan.get('cohort','r54'))
        if (target['default_present'] is not ('default' in native['result'])
                or ('default' in native['result'] and json.dumps(target['observed_default'],allow_nan=False)
                    != json.dumps(native['result']['default'],allow_nan=False))):
            raise ValueError('Original typed class default witness changed')
        listed = read(target['list_receipt']+'.stdout')['agent_result']
        if (listed['scope'] != exact['scope'] or not any(row['name'] == target['field'] and row['selection'] == exact['selection']
                for row in listed['fields'])):
            raise ValueError('Original class selection did not come from its own live inventory')
        # Capture and reader use the same complete deduplicated collection map,
        # including lifecycle imports. Omitted extras and source drift stay missing.
        if historical_class:
            from tests.support.metadata_replay_branch_evidence import validate_class_original_sources,R55_ORIGINAL_SEALS
            if plan['observation_origin']!='native_scenario_lifecycle':
                raise ValueError('Original class native origin changed')
            validate_class_original_sources(repository['commit'],sources,plan.get('cohort','r54'))
            if plan.get('cohort','r54')=='r55' and descriptor['seal']['sha256']!=R55_ORIGINAL_SEALS.get(context['version']):
                raise ValueError('Original accepted R55 seal anchor changed')
            required=sources
        else:
            required = collection_source_map(collector.source_links(context['version'],selected['targets'])[1],collector.REPO)
        if (not sources or len(sources) != len(plan['source_seals'])
                or any(Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name for name in sources)
                or sources != required):
            raise ValueError('Full class metadata source closure changed')
        return dict(context,candidate=repository['commit'],relevant_sources=sources,
            gateway={'argv':command['gateway_arguments'],'exit_code':result['exit_code'],'payload':payload},
            receipt_sha256=files[prefix+'.stdout']['sha256'],format=descriptor['contract'],
            native_result=native['result'],native_sha256=target['native_sha256'],class_name=target['scope'],
            class_id=selected['class_ids'][target['scope']],field=target['field'],invocation=summary['invocation'],
            observation_origin=plan['observation_origin'],cohort=plan.get('cohort','r54'))
    return dict(context, candidate=repository['commit'], relevant_sources=sources,
                gateway={'argv': command['gateway_arguments'], 'exit_code': result['exit_code'], 'payload': payload},
                receipt_sha256=files[prefix + '.stdout']['sha256'])


def validate_r51_metadata_replay(record, branch, candidate, binding, context, base, root, scope_kind, reference_edges):
    """Historical native facts and current program replay, never current native."""
    import json
    from tests.support import metadata_replay_branch_evidence as producer
    prefix = '2021.1|wwise-console|2021.1.14.8108|function|ak.wwise.core.object.getPropertyInfo|'
    definition = '/resultSchema/@definition/waapi_definitions.json/definitions/propertyValue'
    pointers = {'/resultSchema/properties/default/@presence/present', '/resultSchema/properties/default',
        '/resultSchema/properties/default/$ref', definition, definition+'/anyOf/0', definition+'/anyOf/0/@nullable',
        definition+'/anyOf/2', definition+'/anyOf/3', definition+'/anyOf/3/@boolean/false'}
    if branch['id'] != prefix+branch['pointer'] or branch['pointer'] not in pointers:
        raise ValueError('R51 attachment is limited to nine observed Console default leaves')
    if record.get('evidence_kind') != 'historical_metadata_current_program_replay':
        raise ValueError('Historical/native and current/program attribution required')
    bridge = record['source_bridge']
    if (set(bridge) != {'contract','attribution','historical_candidate','historical_sources','current_sources','changed_files'}
            or bridge['contract'] != 'waapi-skill.r51-metadata-leaf-replay/v1'
            or bridge['attribution'] != 'historical_native_current_program_not_current_native'
            or bridge['historical_candidate'] != context['candidate']):
        raise ValueError('Closed exact metadata replay bridge required')
    before, after = bridge['historical_sources'], bridge['current_sources']
    if before != producer.historical_sources() or after != producer.source_seals():
        raise ValueError('Full original/current metadata source closure changed')
    changes = producer.source_changes(before, after)
    allowed = {'tests/maintenance/branch_audit_completion.py','tests/maintenance/branch_coverage_audit.py',
        'tests/unit/test_metadata_discovery_gateway.py','tests/unit/test_metadata_replay_attachments.py',
        'tests/support/metadata_replay_cases.json','tests/support/metadata_replay_branch_evidence.py',
        'docs/branch-coverage-requirements.json','tests/unit/test_metadata_default_branch_evidence.py',
        'tests/support/media_pool_branch_evidence.py'}
    # Root-reviewed R59 exact runtime/policy pairs. Full historical/current maps
    # remain mandatory, including explicit absent-before dependencies. Changed
    # producer hashes are separate from original native ownership; no future
    # runtime, resource or partially combined source is admitted.
    reviewed_runtime = {'docs/branch-coverage-requirements.json': {'after': '99ad508b7fca40ea0db30542115ce90e421e46ed276200d5fbb63a8e39cada3a',
                                            'before': None},
 'skills/waapi-skill/resources/metadata/2022.1/owned-control-input-construction.json': {'after': 'f6ef893344a4b11099962f57178d3484d61df8d01d0b6a07b898d890c8c76454',
                                                                                        'before': None},
 'skills/waapi-skill/resources/metadata/2023.1/owned-control-input-construction.json': {'after': '9d2fc5b8477b840edf4d2b9c8322514b45157761ac3fb898b90d2554fbd8f7c8',
                                                                                        'before': None},
 'skills/waapi-skill/resources/metadata/2024.1/owned-control-input-construction.json': {'after': '46a0180db2c083081c4ab3a410dffc8618603d83f7059dac2e748639ea1cdf21',
                                                                                        'before': None},
 'skills/waapi-skill/resources/metadata/2025.1/owned-control-input-construction.json': {'after': '55a2005e667d122f46c5ecb75c57a666161f3f8c4c789b44f2515d992b609237',
                                                                                        'before': None},
 'skills/waapi-skill/resources/semantic/2025.1/structure-changed-notes-compatibility.json': {'after': '27e7af945c75fc3dab663700837c9779d794b69958394c5c2f778e2288057efa',
                                                                                             'before': None},
 'skills/waapi-skill/scripts/gateway.py': {'after': '837ee2edee8e40d5cc9cad87cba1ff1c536ccb61eb9a5c1119581f0f0de30ab4',
                                           'before': '1da3c6bcbc09c1a426defe958de142c549af6c27cbd5a1ff6ea70b2b182b49ca'},
 'skills/waapi-skill/wwise_waapi/builders/schema.py': {'after': '4a1ac5146edc65eb8e58defd689051f79a198bafb2d5d2134d912bd9a862fd6d',
                                                       'before': '6fa74484ef6ce67964f6f1841ba87df3c4b8735134549083c21ee9fd9373b210'},
 'skills/waapi-skill/wwise_waapi/business_adapters.py': {'after': '1e4d5ecf0a16de4459543bde1297b7a237f9b1e02363f4ed0ff9eb2489e6acf7',
                                                         'before': '501f76379fbd13861091fb71748e7971287e677038205b022124b18dd9db98e2'},
 'skills/waapi-skill/wwise_waapi/core_business.py': {'after': '62e361dd638a53af8b62455ec5c414bff7e5e9a9fdf6a2a419edb44a6f970bb6',
                                                     'before': '2cbf4c4aa6aeca19af2bad665f36d1b0f3bbbcdc148e7da360973574ae0a2f46'},
 'skills/waapi-skill/wwise_waapi/core_business_contracts.py': {'after': 'f9fe51a42199b137420dc906e3ceea57a64e6f3d302940887747d7616f61d61a',
                                                               'before': 'c0a66082248ef5c1a23020dafc90f1a9eb08ac3dfe5073bc6e9f75f2171fa65f'},
 'skills/waapi-skill/wwise_waapi/host_ui_debug_business.py': {'after': 'a392d1a2bc4665dd1ac64a83d88bb89561c2cd8570e3ebd7ab6355c5d62300ba',
                                                              'before': '55b42f82e7ac3574d815f8729fbd98821dea7d870e80a351a4c875fa025da177'},
 'skills/waapi-skill/wwise_waapi/host_ui_debug_business_contracts.py': {'after': 'ce27359dbfb4414bcc9b96e51c271036206f773e78ee22dc8b3b52fcec56da33',
                                                                        'before': '40f292ddb8b34c97a8596a0ae5476947cfbec0f9a675bd43307ac4ccafdadef6'},
 'skills/waapi-skill/wwise_waapi/object_graph_business.py': {'after': '17d96c6f8a663cd4d8bdf3c34717b958ae16ebc36c88ceb59c3f18937389dcb7',
                                                             'before': 'e720da23c5157494caaa5cbee35da02ab9bfb4b08d0dd8db979532d636333f2e'},
 'skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py': {'after': '487422db65a32cedb157a4e5d3cd5865688a4e5dff3b529a6e95d8250792882f',
                                                                       'before': 'a8477164bc13fe66ed6322eea4fbbe0902eba9f86373294f9aa774361a17e916'},
 'skills/waapi-skill/wwise_waapi/object_lifecycle_graph.py': {'after': '8f2df48a3089554996730ad1a074db35bea444316408d0c2f366686a646e226f',
                                                              'before': '97c3eef5097e66d34c5ecc87b56c787969c7bfe10c88d7a7f2ba3b2eef983c72'},
 'skills/waapi-skill/wwise_waapi/object_metadata_business_contracts.py': {'after': '8d6ad65d41bc98cb39f5f73e29d600f3d73be6fba0fa4ad631e1641764b3be18',
                                                                          'before': 'c5585ae67ea0e8c9e5834f5416b03d152f5279059954d045fafb9f628aa5f2da'},
 'skills/waapi-skill/wwise_waapi/operation_composer.py': {'after': '2423437b35cba5cd5ebb801c6ba4ccf23f642e33fa6e10a159fab337c8ca8b5d',
                                                          'before': 'f56b8fd67de519c2b391ce8399bee9c031e6f8b5d7804afa48ddf8b3326168f5'},
 'skills/waapi-skill/wwise_waapi/operation_drafts.py': {'after': 'ff2d8064ee56a2ed00cdb7565aff503b3d6604e0d677e5a85b0904f992e1ae45',
                                                        'before': 'dc6a828ae864c0d7ac1f4845c616bb1b1a49d2aad9ca5e503f754fd4a4922c98'},
 'skills/waapi-skill/wwise_waapi/operation_object.py': {'after': '606efc27030d81559adba6f5bf0aa827aed4ff3c4ef6c5aa666f4529a15db29e',
                                                        'before': '2dfa0ab081b65de6b724b7410a80328f8f7fb1252d60833d05351a1d6d5d9b6e'},
 'skills/waapi-skill/wwise_waapi/operation_registry.py': {'after': '3d619275df7106ac14bf75f6a6f221ff5ca01e2417850d4509fea13698a4718b',
                                                          'before': '20be86428b6e1ae9fb6cab954ee7ada6b8092406bf33b8bc148b869853539b14'},
 'skills/waapi-skill/wwise_waapi/operation_tone.py': {'after': '231521ce3931ed2f1cbde931ef21e8db4c582af2718f38f4765a239c5e908550',
                                                      'before': '34572c49b6c3c9b3b71ad891fdfe8bd35ef22fd104ace8fb7d75a73362cd6912'},
 'skills/waapi-skill/wwise_waapi/owned_control_inputs.py': {'after': '3f0e642025564ccd501cc3e07909b80372eaa36ced2b1c3aab46a215282b162b',
                                                            'before': None},
 'skills/waapi-skill/wwise_waapi/planned_references.py': {'after': '6455105f7c25923c360b68f5883e64d5b8927dd904b621597e8d7150bf1c9401',
                                                          'before': '700eb1fc7b550e834e6762cbf386af1fb06db8af9733b6c4b30cc4f036ecf15b'},
 'skills/waapi-skill/wwise_waapi/source_copy_observations.py': {'after': '78759d095e860f22b0c0ca85b98c3bb7913feb47b6cbc503940a9f62ea287b3e',
                                                                'before': None},
 'skills/waapi-skill/wwise_waapi/source_copy_proof.py': {'after': 'cc17c8e5562c350cb9b793a46fe0660ffc21c79a3cbb0f61c1f2b2fea4f5ec45',
                                                         'before': None},
 'skills/waapi-skill/wwise_waapi/topic_compatibility.py': {'after': '4fff012e3ed9b602e84369f07413c7a113dfbd268a386b64764e9730f3bf81ed',
                                                           'before': None},
 'skills/waapi-skill/wwise_waapi/transaction_runtime.py': {'after': 'eca18101c572eb89c6af494235e7957602a4851073db4c99430f6086a7727baf',
                                                           'before': '327ba44d7947e2beb7933d98b57b7bfdd9011926c1844487660230c6eb14f7e7'},
 'skills/waapi-skill/wwise_waapi/typed_topics.py': {'after': 'ac796300e486ac98565e67d111c4161e0d526c28ef3c4b7de471434f56c2885f',
                                                    'before': 'f00fc3cc016f2fbcff9869c94b789993d2faa61badc517064a435e09ec3ab0bf'},
 'tests/support/metadata_read_branch_evidence.py': {'after': 'a69d316e6137bf0f1bb024816c111ea099180d1c435002fab8affea21ee73935',
                                                    'before': '865806725017e2bd1d616faba010beaa775b7661ac3bd319fe31f42906034c99'},
 'tests/unit/test_branch_coverage_completion_cli.py': {'after': 'b6fcec39b5994eae73205ac9616b03a02e2c8475340e8036b1092485bd516ead',
                                                       'before': 'f95abee0bba5b8e6184c57e806f8a16f112ba22b9cd63e49317b5338becddecb'}}
    if set(changes) & set(reviewed_runtime):
        if any(changes.get(name) != expected for name,expected in reviewed_runtime.items()):
            raise ValueError('Exact reviewed metadata changed-file proof missing; runtime drift is not equivalent')
        allowed.update(reviewed_runtime)
    if bridge['changed_files'] != changes or not set(changes) <= allowed:
        raise ValueError('Exact reviewed metadata changed-file proof missing; runtime drift is not equivalent')
    replay = read_sealed_artifact(record['replay'], base)
    if replay['relevant_sources'] != after or record['invocation'] != replay['invocation']:
        raise ValueError('Current replay source/node receipt differs')
    if scope_kind == 'product':
        # Product replay must come from its actual clean committed source pin.
        # Controlled fixtures remain explicitly controlled and cannot grant it.
        if producer.git_source_seals(replay['git_candidate'], after) != after:
            raise ValueError('Product replay does not match its original committed source')
    field = producer.branch_case(branch)
    inputs = binding.get('category_inputs', {}).get('live_metadata')
    if (not isinstance(inputs, dict) or set(inputs) != {'historical','replay'}
            or inputs != record['category_inputs'] or inputs['historical'] != context['gateway']['argv']
            or inputs['replay'] != replay['gateway']['argv']
            or context['native_result']['name'] != field
            or record['replay']['nodeid'] != producer.NODE+'['+producer.CASES[field]+']'):
        raise ValueError('Each metadata category input must match its own original receipt')
    if (replay['native_call']['args'] != {'object':producer.OBJECT,'property':field}
            or replay['native_call']['options'] != {} or replay['client_disconnected'] is not True
            or replay['replayed_original_native_sha256'] != context['native_sha256']
            or json.dumps(replay['native_call']['result'],sort_keys=True,allow_nan=False)
                != json.dumps(context['native_result'],sort_keys=True,allow_nan=False)):
        raise ValueError('Current replay changed the exact original class/field/native response')
    public = replay['gateway']['payload']
    if (public.get('is_command_line') is not True or public.get('detected_version') != context['version']
            or public['agent_result']['scope'] != context['gateway']['payload']['agent_result']['scope']
            or json.dumps({name:public['agent_result']['metadata'][name] for name in context['native_result']},
                sort_keys=True,allow_nan=False) != json.dumps(context['native_result'],sort_keys=True,allow_nan=False)):
        raise ValueError('Current public replay changed the original host/scope/metadata projection')
    if (replay['discovery']['argv'] != ['metadata','list','--exact-id',producer.OBJECT,'--page-size','64']
            or replay['discovery']['payload']['agent_result']['complete'] is not True
            or inputs['replay'] != ['metadata','detail','--exact-id',producer.OBJECT,'--selection',
                replay['gateway']['payload']['agent_result']['selection']]
            or not any(row['name'] == field and row['selection'] == inputs['replay'][-1]
                for row in replay['discovery']['payload']['agent_result']['fields'])):
        raise ValueError('Current replay lost its exact public discovered field selection')
    for receipt in (record, replay):
        if not any(check['pointer'] == '/gateway/payload/agent_result' and 'equals' in check
                for check in receipt['branch_assertions'][branch['id']]['checks']):
            raise ValueError('Exact whole original/current public result proof missing')
    result = evidence_result(record['replay'],branch,candidate,'program',scope_kind,base,
        record['replay_bindings'][branch['id']],source_root=root,reference_edges=reference_edges)
    if result != ('passed',None):
        raise ValueError('Current public replay did not prove this exact leaf: '+str(result))


def validate_current_class_metadata(record,branch,binding,context,scope_kind):
    """Current-source native metadata only; independent program evidence stays required."""
    from tests.maintenance import collect_class_metadata as collector
    from tests.support.metadata_replay_branch_evidence import git_source_seals
    plan=collector.collection_plan(context['version'],cohort=context.get('cohort','r54'))
    expected={'native_candidate':context['candidate'],'relevant_sources':context['relevant_sources']}
    if (branch['id'] not in plan['eligible_branch_ids']
            or record.get('evidence_kind') != 'current_public_class_metadata'
            or record.get('source_context') != expected
            or record['invocation'] != context['invocation']
            or context['invocation'] != {'phase':'final','outcome':'PASS','node_outcomes':[
                {'nodeid':plan['collector_nodeid'],'outcome':'PASS'}]}
            or record['category_inputs'] != {'native':context['gateway']['argv']}
            or binding.get('category_inputs',{}).get('live_metadata') != record['category_inputs']
            or not any(check['pointer']=='/gateway/payload/agent_result' and 'equals' in check
                for check in record['branch_assertions'][branch['id']]['checks'])):
        raise ValueError('Exact current native class input/source/final result proof missing')
    # The reader has checked every archived source against current bytes and
    # requires its complete metadata/collector closure. Product also proves the
    # original native source pin owns those exact bytes; controls cannot grant it.
    if scope_kind == 'product' and context['observation_origin'] != 'native_scenario_lifecycle':
        raise ValueError('Controlled metadata origin cannot grant product native credit')
    if scope_kind == 'product' and git_source_seals(context['candidate'],context['relevant_sources']) != context['relevant_sources']:
        raise ValueError('Current native class source pin differs from its full sealed closure')


def validate_r54_metadata_replay(record,branch,candidate,binding,context,base,root,scope_kind,reference_edges):
    """Original8a native facts plus exact current public replay, never current native."""
    import json
    from tests.support import metadata_replay_branch_evidence as producer
    from tests.maintenance.collect_class_metadata import collection_plan
    cohort=context['cohort'];profile=producer.class_original_profile(cohort)
    if branch['id'] not in collection_plan(context['version'],cohort=cohort)['eligible_branch_ids']:
        raise ValueError('Historical class replay is limited to its exact original default leaves')
    bridge=record['source_bridge'];before=context['relevant_sources'];after=producer.r54_current_sources()
    producer.validate_class_original_sources(context['candidate'],before,cohort)
    allowed={'tests/maintenance/collect_class_metadata.py','tests/maintenance/branch_audit_completion.py',
        'tests/maintenance/branch_coverage_audit.py','tests/support/metadata_replay_branch_evidence.py',
        'tests/unit/test_class_metadata_collection.py','tests/unit/test_metadata_replay_attachments.py',
        'tests/unit/test_metadata_discovery_gateway.py','tests/unit/test_metadata_default_branch_evidence.py',
        'tests/support/media_pool_branch_evidence.py'}
    changes=producer.source_changes(before,after)
    # Root-reviewed R59 current runtime; independent original R54/R55 before
    # values remain exact. These pairs do not grant current-native credit.
    reviewed_runtime = {'docs/branch-coverage-requirements.json': {'after': '99ad508b7fca40ea0db30542115ce90e421e46ed276200d5fbb63a8e39cada3a',
                                            'before': '282bbc63583b56e7b13e65790b817795d9d8cfacaae54350dda549b8491b6c65'},
 'skills/waapi-skill/resources/metadata/2022.1/owned-control-input-construction.json': {'after': 'f6ef893344a4b11099962f57178d3484d61df8d01d0b6a07b898d890c8c76454',
                                                                                        'before': None},
 'skills/waapi-skill/resources/metadata/2023.1/owned-control-input-construction.json': {'after': '9d2fc5b8477b840edf4d2b9c8322514b45157761ac3fb898b90d2554fbd8f7c8',
                                                                                        'before': None},
 'skills/waapi-skill/resources/metadata/2024.1/owned-control-input-construction.json': {'after': '46a0180db2c083081c4ab3a410dffc8618603d83f7059dac2e748639ea1cdf21',
                                                                                        'before': None},
 'skills/waapi-skill/resources/metadata/2025.1/owned-control-input-construction.json': {'after': '55a2005e667d122f46c5ecb75c57a666161f3f8c4c789b44f2515d992b609237',
                                                                                        'before': None},
 'skills/waapi-skill/resources/semantic/2025.1/structure-changed-notes-compatibility.json': {'after': '27e7af945c75fc3dab663700837c9779d794b69958394c5c2f778e2288057efa',
                                                                                             'before': None},
 'skills/waapi-skill/scripts/gateway.py': {'after': '837ee2edee8e40d5cc9cad87cba1ff1c536ccb61eb9a5c1119581f0f0de30ab4',
                                           'before': '9fead77024b8646db90fa6d80a16933c5bbe05c3f83f10c6d40ef8b8f7b86ebe'},
 'skills/waapi-skill/wwise_waapi/builders/schema.py': {'after': '4a1ac5146edc65eb8e58defd689051f79a198bafb2d5d2134d912bd9a862fd6d',
                                                       'before': '6fa74484ef6ce67964f6f1841ba87df3c4b8735134549083c21ee9fd9373b210'},
 'skills/waapi-skill/wwise_waapi/business_adapters.py': {'after': '1e4d5ecf0a16de4459543bde1297b7a237f9b1e02363f4ed0ff9eb2489e6acf7',
                                                         'before': '501f76379fbd13861091fb71748e7971287e677038205b022124b18dd9db98e2'},
 'skills/waapi-skill/wwise_waapi/host_ui_debug_business_contracts.py': {'after': 'ce27359dbfb4414bcc9b96e51c271036206f773e78ee22dc8b3b52fcec56da33',
                                                                        'before': 'daab229af125377b55e75f3ec84d9f017fa1ed1c36b774851fad316e5e45b749'},
 'skills/waapi-skill/wwise_waapi/object_graph_business.py': {'after': '17d96c6f8a663cd4d8bdf3c34717b958ae16ebc36c88ceb59c3f18937389dcb7',
                                                             'before': 'e720da23c5157494caaa5cbee35da02ab9bfb4b08d0dd8db979532d636333f2e'},
 'skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py': {'after': '487422db65a32cedb157a4e5d3cd5865688a4e5dff3b529a6e95d8250792882f',
                                                                       'before': 'a8477164bc13fe66ed6322eea4fbbe0902eba9f86373294f9aa774361a17e916'},
 'skills/waapi-skill/wwise_waapi/object_metadata_business_contracts.py': {'after': '8d6ad65d41bc98cb39f5f73e29d600f3d73be6fba0fa4ad631e1641764b3be18',
                                                                          'before': 'c5585ae67ea0e8c9e5834f5416b03d152f5279059954d045fafb9f628aa5f2da'},
 'skills/waapi-skill/wwise_waapi/operation_composer.py': {'after': '2423437b35cba5cd5ebb801c6ba4ccf23f642e33fa6e10a159fab337c8ca8b5d',
                                                          'before': 'f56b8fd67de519c2b391ce8399bee9c031e6f8b5d7804afa48ddf8b3326168f5'},
 'skills/waapi-skill/wwise_waapi/operation_drafts.py': {'after': 'ff2d8064ee56a2ed00cdb7565aff503b3d6604e0d677e5a85b0904f992e1ae45',
                                                        'before': 'dc6a828ae864c0d7ac1f4845c616bb1b1a49d2aad9ca5e503f754fd4a4922c98'},
 'skills/waapi-skill/wwise_waapi/operation_object.py': {'after': '606efc27030d81559adba6f5bf0aa827aed4ff3c4ef6c5aa666f4529a15db29e',
                                                        'before': '2dfa0ab081b65de6b724b7410a80328f8f7fb1252d60833d05351a1d6d5d9b6e'},
 'skills/waapi-skill/wwise_waapi/operation_registry.py': {'after': '3d619275df7106ac14bf75f6a6f221ff5ca01e2417850d4509fea13698a4718b',
                                                          'before': 'ae7d8430d03548ce8b42601d99dbc303ed2f99210a0d1d6e090b7fd7b1b3aade'},
 'skills/waapi-skill/wwise_waapi/operation_tone.py': {'after': '231521ce3931ed2f1cbde931ef21e8db4c582af2718f38f4765a239c5e908550',
                                                      'before': '73785ee94380e3c43b30f44754af299aefb68ffc654b3c86870d7b8c7a1f9c7f'},
 'skills/waapi-skill/wwise_waapi/owned_control_inputs.py': {'after': '3f0e642025564ccd501cc3e07909b80372eaa36ced2b1c3aab46a215282b162b',
                                                            'before': None},
 'skills/waapi-skill/wwise_waapi/planned_references.py': {'after': '6455105f7c25923c360b68f5883e64d5b8927dd904b621597e8d7150bf1c9401',
                                                          'before': '700eb1fc7b550e834e6762cbf386af1fb06db8af9733b6c4b30cc4f036ecf15b'},
 'skills/waapi-skill/wwise_waapi/source_copy_proof.py': {'after': 'cc17c8e5562c350cb9b793a46fe0660ffc21c79a3cbb0f61c1f2b2fea4f5ec45',
                                                         'before': None},
 'skills/waapi-skill/wwise_waapi/topic_compatibility.py': {'after': '4fff012e3ed9b602e84369f07413c7a113dfbd268a386b64764e9730f3bf81ed',
                                                           'before': None},
 'skills/waapi-skill/wwise_waapi/transaction_runtime.py': {'after': 'eca18101c572eb89c6af494235e7957602a4851073db4c99430f6086a7727baf',
                                                           'before': '327ba44d7947e2beb7933d98b57b7bfdd9011926c1844487660230c6eb14f7e7'},
 'skills/waapi-skill/wwise_waapi/typed_topics.py': {'after': 'ac796300e486ac98565e67d111c4161e0d526c28ef3c4b7de471434f56c2885f',
                                                    'before': 'f00fc3cc016f2fbcff9869c94b789993d2faa61badc517064a435e09ec3ab0bf'},
 'tests/support/metadata_read_branch_evidence.py': {'after': 'a69d316e6137bf0f1bb024816c111ea099180d1c435002fab8affea21ee73935',
                                                    'before': '865806725017e2bd1d616faba010beaa775b7661ac3bd319fe31f42906034c99'},
 'tests/unit/test_branch_coverage_completion_cli.py': {'after': 'b6fcec39b5994eae73205ac9616b03a02e2c8475340e8036b1092485bd516ead',
                                                       'before': 'f95abee0bba5b8e6184c57e806f8a16f112ba22b9cd63e49317b5338becddecb'}}
    if cohort=='r55':
        # Original860 owns the earlier runtime. Exact Source411 and Triangle
        # pairs advance it; native860 remains historical, never current-native.
        reviewed_runtime = {'docs/branch-coverage-requirements.json': {'after': '99ad508b7fca40ea0db30542115ce90e421e46ed276200d5fbb63a8e39cada3a',
                                            'before': '282bbc63583b56e7b13e65790b817795d9d8cfacaae54350dda549b8491b6c65'},
 'skills/waapi-skill/resources/metadata/2022.1/owned-control-input-construction.json': {'after': 'f6ef893344a4b11099962f57178d3484d61df8d01d0b6a07b898d890c8c76454',
                                                                                        'before': None},
 'skills/waapi-skill/resources/metadata/2023.1/owned-control-input-construction.json': {'after': '9d2fc5b8477b840edf4d2b9c8322514b45157761ac3fb898b90d2554fbd8f7c8',
                                                                                        'before': None},
 'skills/waapi-skill/resources/metadata/2024.1/owned-control-input-construction.json': {'after': '46a0180db2c083081c4ab3a410dffc8618603d83f7059dac2e748639ea1cdf21',
                                                                                        'before': None},
 'skills/waapi-skill/resources/metadata/2025.1/owned-control-input-construction.json': {'after': '55a2005e667d122f46c5ecb75c57a666161f3f8c4c789b44f2515d992b609237',
                                                                                        'before': None},
 'skills/waapi-skill/resources/semantic/2025.1/structure-changed-notes-compatibility.json': {'after': '27e7af945c75fc3dab663700837c9779d794b69958394c5c2f778e2288057efa',
                                                                                             'before': None},
 'skills/waapi-skill/scripts/gateway.py': {'after': '837ee2edee8e40d5cc9cad87cba1ff1c536ccb61eb9a5c1119581f0f0de30ab4',
                                           'before': 'f86e1102b99d7d552dd1fabebbda7ea4a3020f21b796233bdfc69186123c711c'},
 'skills/waapi-skill/wwise_waapi/builders/schema.py': {'after': '4a1ac5146edc65eb8e58defd689051f79a198bafb2d5d2134d912bd9a862fd6d',
                                                       'before': '6fa74484ef6ce67964f6f1841ba87df3c4b8735134549083c21ee9fd9373b210'},
 'skills/waapi-skill/wwise_waapi/business_adapters.py': {'after': '1e4d5ecf0a16de4459543bde1297b7a237f9b1e02363f4ed0ff9eb2489e6acf7',
                                                         'before': '501f76379fbd13861091fb71748e7971287e677038205b022124b18dd9db98e2'},
 'skills/waapi-skill/wwise_waapi/host_ui_debug_business_contracts.py': {'after': 'ce27359dbfb4414bcc9b96e51c271036206f773e78ee22dc8b3b52fcec56da33',
                                                                        'before': '4e231f2b1556d38b61534ab98889b309a136f7bdfd2631ceb5a20d80fefc979e'},
 'skills/waapi-skill/wwise_waapi/object_graph_business.py': {'after': '17d96c6f8a663cd4d8bdf3c34717b958ae16ebc36c88ceb59c3f18937389dcb7',
                                                             'before': 'e720da23c5157494caaa5cbee35da02ab9bfb4b08d0dd8db979532d636333f2e'},
 'skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py': {'after': '487422db65a32cedb157a4e5d3cd5865688a4e5dff3b529a6e95d8250792882f',
                                                                       'before': 'a8477164bc13fe66ed6322eea4fbbe0902eba9f86373294f9aa774361a17e916'},
 'skills/waapi-skill/wwise_waapi/object_metadata_business_contracts.py': {'after': '8d6ad65d41bc98cb39f5f73e29d600f3d73be6fba0fa4ad631e1641764b3be18',
                                                                          'before': 'c5585ae67ea0e8c9e5834f5416b03d152f5279059954d045fafb9f628aa5f2da'},
 'skills/waapi-skill/wwise_waapi/operation_composer.py': {'after': '2423437b35cba5cd5ebb801c6ba4ccf23f642e33fa6e10a159fab337c8ca8b5d',
                                                          'before': '456440f1b0502c3e1299943b07a21f88224f65ccbd0f475d6235e176ea52eb12'},
 'skills/waapi-skill/wwise_waapi/operation_drafts.py': {'after': 'ff2d8064ee56a2ed00cdb7565aff503b3d6604e0d677e5a85b0904f992e1ae45',
                                                        'before': '528e50ab6e1432415bfb4eedd34ce10eaa507a39e84a8590c9f5a048f70bfe01'},
 'skills/waapi-skill/wwise_waapi/operation_object.py': {'after': '606efc27030d81559adba6f5bf0aa827aed4ff3c4ef6c5aa666f4529a15db29e',
                                                        'before': '2dfa0ab081b65de6b724b7410a80328f8f7fb1252d60833d05351a1d6d5d9b6e'},
 'skills/waapi-skill/wwise_waapi/operation_registry.py': {'after': '3d619275df7106ac14bf75f6a6f221ff5ca01e2417850d4509fea13698a4718b',
                                                          'before': '5d351a80e7ceca94df76b9b97740a63b91f67b97d74038908e0242a669590045'},
 'skills/waapi-skill/wwise_waapi/operation_tone.py': {'after': '231521ce3931ed2f1cbde931ef21e8db4c582af2718f38f4765a239c5e908550',
                                                      'before': 'db783ace35413ca1d126ea6a100bef0e2c813008502306dc6e4e3c4d03155fa8'},
 'skills/waapi-skill/wwise_waapi/owned_control_inputs.py': {'after': '3f0e642025564ccd501cc3e07909b80372eaa36ced2b1c3aab46a215282b162b',
                                                            'before': None},
 'skills/waapi-skill/wwise_waapi/planned_references.py': {'after': '6455105f7c25923c360b68f5883e64d5b8927dd904b621597e8d7150bf1c9401',
                                                          'before': '700eb1fc7b550e834e6762cbf386af1fb06db8af9733b6c4b30cc4f036ecf15b'},
 'skills/waapi-skill/wwise_waapi/source_copy_proof.py': {'after': 'cc17c8e5562c350cb9b793a46fe0660ffc21c79a3cbb0f61c1f2b2fea4f5ec45',
                                                         'before': '71a1d2ae8c7d5e1b390733cd69cc20606465a475f10581eafaa77f55c757bb79'},
 'skills/waapi-skill/wwise_waapi/topic_compatibility.py': {'after': '4fff012e3ed9b602e84369f07413c7a113dfbd268a386b64764e9730f3bf81ed',
                                                           'before': None},
 'skills/waapi-skill/wwise_waapi/typed_topics.py': {'after': 'ac796300e486ac98565e67d111c4161e0d526c28ef3c4b7de471434f56c2885f',
                                                    'before': 'f00fc3cc016f2fbcff9869c94b789993d2faa61badc517064a435e09ec3ab0bf'},
 'tests/support/metadata_read_branch_evidence.py': {'after': 'a69d316e6137bf0f1bb024816c111ea099180d1c435002fab8affea21ee73935',
                                                    'before': '865806725017e2bd1d616faba010beaa775b7661ac3bd319fe31f42906034c99'},
 'tests/unit/test_branch_coverage_completion_cli.py': {'after': 'b6fcec39b5994eae73205ac9616b03a02e2c8475340e8036b1092485bd516ead',
                                                       'before': 'f95abee0bba5b8e6184c57e806f8a16f112ba22b9cd63e49317b5338becddecb'}}
    if any(changes.get(name)!=expected for name,expected in reviewed_runtime.items()):
        raise ValueError('Exact R54 reviewed runtime blob proof missing; unreviewed runtime drift')
    allowed.update(reviewed_runtime)
    if any(changes.get(name)!=expected for name,expected in producer.CLASS_AUXILIARY_CHANGES.items()):
        raise ValueError('Exact reviewed class auxiliary blob proof missing; unreviewed runtime drift')
    allowed.update(producer.CLASS_AUXILIARY_CHANGES)
    if (set(bridge)!={'contract','attribution','historical_candidate','historical_sources','current_sources','changed_files'}
            or bridge['contract']!=profile['bridge_contract']
            or bridge['attribution']!='historical_native_current_program_not_current_native'
            or bridge['historical_candidate']!=profile['candidate'] or bridge['historical_sources']!=before
            or bridge['current_sources']!=after or bridge['changed_files']!=changes or not set(changes)<=allowed):
        raise ValueError('Exact full R54/current source delta missing; unreviewed runtime drift')
    replay=read_sealed_artifact(record['replay'],base)
    case='|'.join((context['version'],context['class_name'],context['field']))
    nodeid=profile['node']+'['+case+']'
    if (record.get('evidence_kind')!='historical_class_metadata_current_program_replay'
            or record['invocation']!=replay['invocation']
            or record['invocation']!={'phase':'final','outcome':'PASS','node_outcomes':[{'nodeid':nodeid,'outcome':'PASS'}]}
            or record['replay']['nodeid']!=nodeid or replay['relevant_sources']!=after
            or context['observation_origin']!='native_scenario_lifecycle' or replay['original_case']!=case):
        raise ValueError('Original R54 origin/current replay final node changed')
    if scope_kind=='product' and producer.git_source_seals(replay['git_candidate'],after)!=after:
        raise ValueError('Current R54 replay Git/source ownership changed')
    inputs={'historical':context['gateway']['argv'],'replay':replay['gateway']['argv']}
    if record['category_inputs']!=inputs or binding.get('category_inputs',{}).get('live_metadata')!=inputs:
        raise ValueError('R54 native and current inputs must bind their own receipts')
    def same(a,b):return json.dumps(a,sort_keys=True,allow_nan=False)==json.dumps(b,sort_keys=True,allow_nan=False)
    native=replay['native_call'];public=replay['gateway']['payload'];original=context['gateway']['payload']['agent_result']
    if (native['uri']!=producer.URI or native['args']!={'classId':context['class_id'],'property':context['field']}
            or native['options']!={} or not same(native['result'],context['native_result'])
            or replay['replayed_original_native_sha256']!=context['native_sha256']
            or replay['replayed_original_packets_sha256']!=producer.r54_replay_case(case,record['metadata_run'],base=base,cohort=cohort)['packet_sha256s']
            or replay['client_disconnected'] is not True or public.get('detected_version')!=context['version']
            or public.get('is_command_line') is not True or public['agent_result']['scope']!=original['scope']
            or public['agent_result']['complete'] is not True
            or not same({k:public['agent_result']['metadata'][k] for k in native['result']},context['native_result'])):
        raise ValueError('Exact original R54 class/field/raw/native/public replay changed')
    pages=replay['discovery_pages'];prefix=['metadata','list','--custom-kind',context['class_name'],'--page-size','64']
    if not 1<=len(pages)<=8:raise ValueError('Bounded R54 current selection pages required')
    for i,page in enumerate(pages):
        expected=prefix+(['--page',pages[i-1]['payload']['agent_result']['next_page']] if i else [])
        if (page['argv']!=expected or page['payload'].get('ok') is not True
                or page['payload']['agent_result']['scope']!=original['scope']
                or page['payload']['agent_result']['snapshot']!=pages[0]['payload']['agent_result']['snapshot']):
            raise ValueError('Exact current R54 class selection page changed')
    if (replay['gateway']['argv']!=['metadata','detail','--custom-kind',context['class_name'],'--selection',public['agent_result']['selection']]
            or not any(row['name']==context['field'] and row['selection']==public['agent_result']['selection']
                for page in pages for row in page['payload']['agent_result']['fields'])):
        raise ValueError('Current R54 field selection not independently discovered')
    for receipt in (record,replay):
        if not any(c['pointer']=='/gateway/payload/agent_result' and 'equals' in c
                for c in receipt['branch_assertions'][branch['id']]['checks']):
            raise ValueError('Whole original/current R54 result proof missing')
    result=evidence_result(record['replay'],branch,candidate,'program',scope_kind,base,
        record['replay_bindings'][branch['id']],source_root=root,reference_edges=reference_edges)
    if result!=('passed',None):raise ValueError('Current R54 public replay did not prove leaf: '+str(result))


def binding_semantics(binding):
    return {k: v for k, v in binding.items() if k not in ('evidence', 'equivalence', 'native_equivalence')}


def validate_equivalence(proof_descriptor, descriptor, record, branch, candidate, binding, base, root):
    """A reviewed exact source/behavior bridge, never a family PASS inheritance."""
    import hashlib
    import json
    proof = read_sealed_artifact(proof_descriptor, base)
    semantic_digest = hashlib.sha256(json.dumps(binding_semantics(binding), ensure_ascii=False, sort_keys=True,
                                               separators=(',', ':')).encode()).hexdigest()
    expected = {'contract': 'waapi-skill.branch-evidence-equivalence/v1',
        'from_candidate': record['candidate_sha256'], 'to_candidate': candidate,
        'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
        'evidence_sha256': descriptor['sha256'], 'binding_semantics_sha256': semantic_digest}
    if any(proof.get(k) != v for k, v in expected.items()) or not proof.get('reviewed_reason'):
        raise ValueError('stale or nonexact reviewed equivalence')
    sources = proof.get('sources', {})
    required = {binding[k]['source'].split('#')[0] for k in ('construction', 'validation', 'verifier')}
    required |= {'skills/waapi-skill/scripts/run.py', 'skills/waapi-skill/scripts/gateway.py'}
    if (not sources or (not proof.get('source_copy_review')
                        and set(sources) != set(binding.get('relevant_sources', [])))
            or not required <= set(sources) or sources != record.get('relevant_sources')):
        raise ValueError('equivalence omits original relevant source/behavior dependencies')
    if proof.get('source_copy_review'):
        from tests.support.source_copy_native_evidence import validate_source_equivalence
        validate_source_equivalence(proof, branch, binding, root, evidence_base=base)
        return
    if proof.get('runtime_read_review'):
        from tests.support.runtime_observation_evidence import validate_runtime_source_review, RTPC_ORIGINAL_CANDIDATE
        if proof['from_candidate'] != RTPC_ORIGINAL_CANDIDATE or not binding.get('runtime_observation_attachment'):
            raise ValueError('RTPC guard review requires its exact original runtime producer')
        validate_runtime_source_review(proof['runtime_read_review'], sources, branch, root, base)
        return
    for name, seal in sources.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != seal:
            raise ValueError('equivalence relevant source changed')


def validate_native_source(context, descriptor, branch, candidate, binding, base, root, historical_sources=None):
    """Bridge an original producer's Git identity to the reviewed branch candidate."""
    import hashlib
    import subprocess
    if binding.get('source_copy_native_proof'):
        # Only the exact reviewed Source reader separates original540 from
        # current547. validate_equivalence rechecks version/route/pointer,
        # selected shape, original maps and the full pinned current closure.
        from tests.support.source_copy_native_evidence import native_source_maps
        sources = native_source_maps(context['candidate'])
    else:
        sources = context.get('relevant_sources')
        selected = binding.get('relevant_sources', [])
        if sources is None:
            key = (str(root.resolve()), context['candidate'], tuple(sorted(selected)))
            if historical_sources is not None and key in historical_sources:
                sources = dict(historical_sources[key])
            else:
                sources = {}
                for name in selected:
                    completed = subprocess.run(['git', 'show', context['candidate'] + ':' + name], cwd=root,
                                               check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if completed.returncode:
                        raise ValueError('original native source candidate unavailable')
                    sources[name] = hashlib.sha256(completed.stdout).hexdigest()
                if historical_sources is not None:
                    historical_sources[key] = tuple(sorted(sources.items()))
        else:
            sources = {name: sources[name] for name in selected}
    proof = binding.get('native_equivalence', {})
    if 'artifact' not in proof:
        proof = proof.get(descriptor['sha256'], {})
    validate_equivalence(proof, descriptor,
        {'candidate_sha256': context['candidate'], 'relevant_sources': sources}, branch, candidate, binding, base, root)


def native_observation_pattern(pointer):
    """Translate structural schema paths; array positions remain exact witnesses."""
    parts, result, index = pointer.strip('/').split('/'), [], 0
    while index < len(parts):
        token = parts[index]
        if token == 'properties' and index + 1 < len(parts):
            result.append(parts[index + 1]); index += 2
        elif token == 'patternProperties' and index + 1 < len(parts):
            result.append(('pattern', parts[index + 1].replace('~1', '/').replace('~0', '~'))); index += 2
        elif token == 'items':
            if index + 1 < len(parts) and parts[index + 1].isdigit():
                result.append(parts[index + 1]); index += 2
            else:
                result.append('*'); index += 1
        elif token in ('oneOf', 'OneOf', 'anyOf', 'allOf'):
            index += 2
        elif token == '@definition':
            raise ValueError('definition observation requires exact reference-chain context')
        else:
            index += 1
    return result


def exact_observation_pointer(branch, binding, dispatch, section, reference_edges):
    pointer = branch['pointer']
    if '/@definition/' in pointer:
        chain = binding.get('reference_chain', [])
        if not chain or len(chain) > 64:
            raise ValueError('definition requires a bounded exact reference chain')
        pattern, previous = [], None
        for identity in chain:
            edge = reference_edges[identity]
            if edge['route'] != branch['route']:
                raise ValueError('reference chain changes native route')
            source = edge['pointer']
            if previous is not None:
                if not source.startswith(previous + '/'):
                    raise ValueError('reference chain is not reachable from previous target')
                source = source[len(previous):]
            pattern += native_observation_pattern(source)
            previous = edge['reference']['target'].split('|', 5)[5]
        if pointer != previous and not pointer.startswith(previous + '/'):
            raise ValueError('reference chain does not reach exact branch')
        pattern += native_observation_pattern(pointer[len(previous):])
    else:
        pattern = native_observation_pattern(pointer)
    import re
    base = dispatch + '/' + section
    expected_tokens = base.split('/') + pattern
    if 'observation_pointer' in binding:
        observed = binding['observation_pointer']
    elif any(isinstance(token, tuple) or token == '*' for token in pattern):
        raise ValueError('collection/pattern context requires an exact observation mapping')
    else:
        observed = '/'.join(expected_tokens)
    tokens = observed.split('/')
    def matches(actual, expected):
        if isinstance(expected, tuple):
            return re.search(expected[1], actual.replace('~1', '/').replace('~0', '~')) is not None
        return actual.isdigit() if expected == '*' else actual == expected
    if len(tokens) != len(expected_tokens) or not all(matches(a,b) for a,b in zip(tokens,expected_tokens)):
        raise ValueError('explicit observation changes native field or array/reference context')
    return observed


def validate_native_alternative(root, branch, value):
    """Resolve native child semantics and reuse the existing bounded validator."""
    import hashlib
    import json
    from wwise_waapi.native_catalog import load_native_catalog
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    from wwise_waapi.builders.schema import _SchemaWalker
    from wwise_waapi.builders.common import SemanticValidationError
    version, host, build, _, uri = branch['route'].split('|')
    catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
    if catalog['provenance']['build'] != build:
        raise ValueError('alternative native build changed')
    definitions = catalog['definitions']
    graph = DefinitionGraph(**{k: definitions[k] for k in ('contract','version','wwise_build','source_file_names','documents','inventory_sha256')})
    if '/@definition/' in branch['pointer']:
        section, rest = branch['pointer'].split('/@definition/', 1)
        name, separator, suffix = rest.partition('/')
        context = graph.documents[name]
        schema = pointer_value(context, '/' + suffix if separator else '')
    else:
        context = catalog['schemas'][uri][branch['pointer'].split('/')[1]]
        schema = pointer_value(catalog['schemas'][uri], branch['pointer'])
    digest = hashlib.sha256(json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != branch['shape_sha256']:
        raise ValueError('selected native alternative shape changed')
    class NativeWalker(_SchemaWalker):
        def validate(self, schema, value, *, path, depth=0):
            if depth > 32:
                raise ValueError('alternative reference budget exceeded')
            if not isinstance(schema, dict):
                raise ValueError('unrecognized alternative schema')
            reference = schema.get('$ref', schema.get('#ref'))
            if reference is not None:
                resolved = resolve_schema_reference(reference, root_schema=self.context, graph=graph)
                old = self.context
                self.context = old if resolved.document_name == '<schema>' else graph.documents[resolved.document_name]
                try:
                    self.validate(resolved.target, value, path=path, depth=depth+1)
                finally:
                    self.context = old
                schema = {k:v for k,v in schema.items() if k not in ('$ref','#ref')}
            known = {'type','properties','patternProperties','additionalProperties','required','items','minItems','maxItems','uniqueItems',
                'enum','const','oneOf','anyOf','allOf','minLength','maxLength','pattern','minimum','maximum','exclusiveMinimum','exclusiveMaximum',
                'multipleOf','minProperties','maxProperties','description','descriptions','title','default','examples','definitions','localDefinitions','synopsis'}
            if set(schema) - known:
                raise ValueError('unrecognized native alternative semantics remain unverified')
            super().validate(schema, value, path=path, depth=depth)
    walker = NativeWalker(uri=uri, version=version)
    walker.context = context
    try:
        walker.validate(schema, value, path='exact-native-alternative')
    except SemanticValidationError as exc:
        raise ValueError('observation does not satisfy selected native alternative') from exc
    if walker.unresolved_refs:
        raise ValueError('unresolved native alternative reference')


def approved_boundary(root, branch, binding, route, public, digest):
    """Only existing exact host policy or intentionally-blocked selectors qualify."""
    import json
    boundary = binding.get('boundary', {})
    if route is None:
        return None
    if boundary.get('kind') == 'wrong_host':
        required = public.get('correct_host')
        if required in ('wwise-console', 'wwise-authoring') and route['host'] != required and boundary.get('required_host') == required:
            return {'kind':'wrong_host','required_host':required,'error_code':'AUTHORING_HOST_REQUIRED' if required == 'wwise-authoring' else 'CONSOLE_HOST_REQUIRED'}
        return None
    if boundary.get('kind') != 'prohibited_field':
        return None
    policy = json.loads((root / 'skills/waapi-skill/resources/native_surface_policy.json').read_text())
    if boundary.get('policy_sha256') != digest(policy):
        return None
    pointer = boundary.get('policy_pointer', '')
    try:
        parts = pointer.strip('/').split('/')
        rule = policy['rules'][int(parts[1])]
        authority = pointer_value(policy, pointer)
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if rule['uri'] != route['uri'] or route['version'] not in rule['versions']:
        return None
    # Legacy intentionally_blocked includes unfinished ordinary capabilities.
    # Only the exact external command hooks retained by approved ticket #184
    # have dangerous-field authority here; semantic-boundary labels do not.
    hooks = {
        'ak.wwise.cli.generateSoundbank': {'custom-global-closing-cmd','custom-global-opening-cmd','custom-post-gen-cmd','custom-pre-gen-cmd'},
        'ak.wwise.cli.tabDelimitedImport': {'custom-global-closing-cmd','custom-global-opening-cmd'},
    }
    if (not isinstance(authority, str) or authority not in hooks.get(route['uri'], set())
            or len(parts) != 7 or parts[2] != 'scopes' or parts[4:6] != ['classifications','intentionally_blocked']):
        return None
    scope = rule['scopes'][int(parts[3])]
    expected = scope['pointer'] + '/properties/' + authority.replace('~','~0').replace('/','~1')
    if branch['pointer'] != expected and not branch['pointer'].startswith(expected + '/'):
        return None
    if branch['kind'] == 'optional_presence' and branch.get('value') == 'absent':
        return None
    approved_sources = ['docs/plans/full-waapi-coverage/SPEC.md',
        'docs/plans/full-waapi-coverage/tickets/10-complete-console-project-and-file-operation-alternatives.md']
    return {'kind':'prohibited_field', 'native_field':authority, 'native_pointer':expected, 'policy_pointer':pointer, 'policy_sha256':digest(policy),
        'approval_sources': {name:digest((root / name).read_text()) for name in approved_sources}}


def validate_boundary_receipt(record, branch, binding, checks):
    boundary, gateway = branch['approved_boundary'], record['gateway']
    payload, calls = gateway['payload'], record.get('native_calls')
    uri = branch['route'].split('|')[4]
    if (gateway['argv'] != binding['input']['gateway_argv'] or gateway['exit_code'] != 2 or payload.get('ok') is not False
            or not isinstance(calls, list) or any(c['uri'] == uri for c in calls)
            or not any(c['pointer'] == '/gateway/payload/error_code' and c.get('equals') == payload.get('error_code') for c in checks)):
        raise ValueError('exact rejected public input and no-target-dispatch proof missing')
    if boundary['kind'] == 'wrong_host':
        infos = [c['result'] for c in calls if c['uri'] == 'ak.wwise.core.getInfo']
        version, host, build = branch['route'].split('|')[:3]
        if (len(infos) != 1 or native_host_context(infos[0], 'isCommandLine') != {'version':version,'host':host,'build':build}
                or payload.get('error_code') != boundary['error_code'] or payload.get('api') != uri
                or payload.get('executed') is not False or payload.get('details', {}).get('required_host') != boundary['required_host']):
            raise ValueError('wrong-host boundary context mismatch')
    else:
        declared = binding['boundary']
        rejection_checks = declared.get('rejected_input_checks', [])
        error_pointer = declared.get('error_pointer', '')
        import re
        hook, argv = boundary['native_field'], gateway['argv']
        positions = [i for i,token in enumerate(argv) if (token == '--' + hook or (token == hook and i > 0 and argv[i-1] == '--value')) and i+1 < len(argv)]
        supplied = any({'pointer':f'/gateway/argv/{i}','equals':argv[i]} in rejection_checks
                       and {'pointer':f'/gateway/argv/{i+1}','equals':argv[i+1]} in rejection_checks for i in positions)
        rejection = pointer_value(record, error_pointer)
        specific = isinstance(rejection, str) and re.search(r'(?<![A-Za-z0-9_-])(?:--)?' + re.escape(hook) + r'(?![A-Za-z0-9_.:-])', rejection)
        if (not supplied or not specific or not rejection_checks or not all(c in checks and c['pointer'].startswith('/gateway/argv/') for c in rejection_checks)
                or not error_pointer.startswith('/gateway/payload/') or not any(c['pointer'] == error_pointer for c in checks)
                or payload.get('error_code') not in {'TypedOperationInputError','SemanticValidationError','GatewayInputError','GatewayArgumentError','DraftOperationError','OperationValidationError'}):
            raise ValueError('exact prohibited-input rejection proof missing')


def validate_native_absence_observations(record, binding, checks, hosts):
    """An absence label cannot override a present or unobserved host field."""
    pointers = binding.get('absence_observation_pointers', {})
    if set(pointers) != hosts or set(record['observations']) != hosts:
        raise ValueError('native absence needs exact observations for each host')
    for host, pointer in pointers.items():
        if not pointer.startswith('/observations/' + host + '/') or {'pointer':pointer,'absent':True} not in checks:
            raise ValueError('native absence cannot borrow another host observation')
        try:
            pointer_value(record, pointer)
        except (KeyError, IndexError):
            continue
        raise ValueError('native absence observation is present')


def validate_created_topic_program(record, branch, binding, checks, root, reference_edges):
    """Only Console object.created fixed primitive publish leaves, four callbacks.

    Generic streams have no agent_result. Preserve their actual ordered sink
    records and independently observed callbacks; never accept an arbitrary
    public pointer, args/options proof, or an omission without its parent.
    """
    import hashlib
    import json
    import math
    import re
    from wwise_waapi.native_catalog import canonical_digest
    from wwise_waapi.topic_business import topic_business_contract

    uri = 'ak.wwise.core.object.created'
    version, host, build, kind, actual_uri = branch['route'].split('|')
    definition = '/publishSchema/@definition/waapi_definitions.json/definitions/objectReturn/properties/'
    if (host != 'wwise-console' or kind != 'topic' or actual_uri != uri
            or not branch['pointer'].startswith(definition)
            or branch['kind'] not in ('schema', 'optional_presence', 'empty_string', 'boolean_value', 'enum_value')
            or branch['id'] != branch['route'] + '|' + branch['pointer']):
        raise ValueError('created stream proof requires the exact Console publishSchema scalar branch')
    # Cache only by exact immutable bytes, not a path/mtime. Every read still
    # verifies the current file against the original native catalog index.
    catalog_root = root / 'skills/waapi-skill/resources/native-catalog'
    name = version + '/' + host + '.json'
    raw = (catalog_root / name).read_bytes()
    seal = hashlib.sha256(raw).hexdigest()
    if json.loads((catalog_root / 'index.json').read_text())[name] != seal:
        raise ValueError('created stream native catalog seal changed')
    catalog = _created_topic_catalog(str(catalog_root), version, seal)
    if catalog['provenance']['build'] != build:
        raise ValueError('created stream native build changed')
    definitions = catalog['definitions']['documents']['waapi_definitions.json']['definitions']
    object_schema = definitions['objectReturn']
    builtins = definitions['returnExpression']['items']['anyOf'][0]['enum']
    properties = object_schema['properties']
    fields = sorted(name for name, schema in properties.items() if name in builtins
        and schema.get('type') in ('string', 'number', 'integer', 'boolean')
        and set(schema) <= {'type', 'enum', 'description'})
    field, _, suffix = branch['pointer'][len(definition):].partition('/')
    if field not in fields:
        raise ValueError('created stream field is not a fixed primitive include')
    schema = properties[field]
    expected_suffix = {'schema': '', 'optional_presence': '@presence/' + str(branch.get('value')),
        'empty_string': '@empty/string', 'boolean_value': '@boolean/' + str(branch.get('value')).lower()}.get(branch['kind'])
    if branch['kind'] == 'enum_value':
        if not re.fullmatch(r'enum/[0-9]+', suffix):
            raise ValueError('created stream enum occurrence changed')
        expected_value = schema['enum'][int(suffix.split('/')[1])]
        if type(expected_value) is not type(branch.get('value')) or expected_value != branch.get('value'):
            raise ValueError('created stream enum alternative changed')
        expected_suffix = suffix
    if suffix != expected_suffix or branch['shape_sha256'] != canonical_digest(schema if branch['kind'] == 'schema' else branch.get('value')):
        raise ValueError('created stream exact alternative shape changed')
    edge_id = branch['route'] + '|/publishSchema/properties/object/$ref'
    edge = reference_edges[edge_id]
    if (binding.get('reference_chain') != [edge_id]
            or edge['value'] != catalog['schemas'][uri]['publishSchema']['properties']['object']['$ref']
            or edge['reference']['target'] != branch['route'] + '|' + definition.rsplit('/properties/', 1)[0]
            or edge['reference']['target_sha256'] != canonical_digest(object_schema)):
        raise ValueError('created stream exact native reference occurrence changed')
    match = re.fullmatch(r'/observations/callbacks/([0-3])', binding.get('dispatch_pointer', ''))
    if not match:
        raise ValueError('created stream needs an exact callback index')
    index = int(match[1])
    native_pointer = f'/observations/callbacks/{index}/event/object/{field}'
    public_pointer = f'/stream_records/{index + 1}/event/object/{field}'
    if binding.get('observation_pointer') != native_pointer or binding.get('gateway_observation_pointer') != public_pointer:
        raise ValueError('created stream callback/public occurrence or field differs')
    exact_observation_pointer(branch, {**binding, 'observation_pointer': public_pointer},
                              f'/stream_records/{index + 1}', 'event', reference_edges)
    digest = topic_business_contract(version, uri).contract_digest
    argv = ['--timeout', '1.0', 'stream-topic', uri, '--topic-contract-digest', digest, '--event-count', '4',
            *[token for name in fields for token in ('--topic-option', 'include', name)]]
    if record['gateway']['argv'] != argv or binding.get('input', {}).get('gateway_argv') != argv:
        raise ValueError('created stream exact public argv differs')
    options = {'return': fields}
    if record.get('subscriptions') != [{'uri': uri, 'options': options}]:
        raise ValueError('created stream exact subscription/options missing')
    callbacks, records = record['observations']['callbacks'], record['stream_records']
    if len(callbacks) != 4 or len(records) != 5:
        raise ValueError('created stream requires four exact ordered callback/sink records')
    contract = 'waapi-skill.topic-stream/v1'
    started, terminal = records[0], record['gateway']['payload']
    for envelope in (started, terminal):
        if (envelope.get('contract') != contract or envelope.get('command') != 'stream-topic'
                or envelope.get('topic') != uri or envelope.get('detected_version') != version
                or envelope.get('is_command_line') is not True or envelope.get('topic_contract_digest') != digest
                or envelope.get('match') is not None
                or envelope.get('subscription_timeout') != {'mode': 'finite', 'seconds': 1.0, 'source': 'explicit'}):
            raise ValueError('created stream original public envelope missing')
    if (started.get('record_type') != 'started' or started.get('ok') is not True
            or started.get('status') != 'streaming' or type(started.get('event_count_limit')) is not int
            or started['event_count_limit'] != 4):
        raise ValueError('created stream original started record missing')
    for sequence, (callback, event_record) in enumerate(zip(callbacks, records[1:]), 1):
        validation = event_record['event_validation']
        if (callback['uri'] != uri or callback['options'] != options
                or event_record.get('contract') != contract or event_record.get('record_type') != 'event'
                or event_record.get('topic') != uri or type(event_record.get('sequence')) is not int
                or event_record['sequence'] != sequence
                or canonical_digest(callback['event']) != canonical_digest(event_record['event'])
                or validation.get('uri') != uri or validation.get('version') != version
                or validation.get('section') != 'event' or validation.get('required_fields') != ['object']
                or validation.get('unresolved_refs') != [] or type(validation.get('validated_nodes')) is not int
                or validation['validated_nodes'] <= 0):
            raise ValueError('created stream ordered callback/validated sink record differs')
        for event in (callback['event'], event_record['event']):
            if not isinstance(event, dict) or not isinstance(event.get('object'), dict):
                raise ValueError('created stream omission requires an existing object parent')
            if set(event) != {'object'} or set(event['object']) - set(fields):
                raise ValueError('created stream packet leaves the reviewed primitive fields')
            for name, value in event['object'].items():
                field_schema = properties[name]
                allowed = {'string': (str,), 'boolean': (bool,), 'number': (int, float), 'integer': (int,)}[field_schema['type']]
                if type(value) not in allowed or ('enum' in field_schema and value not in field_schema['enum']):
                    raise ValueError('created stream scalar type/enum differs from pinned reflection')
                if type(value) is float and not math.isfinite(value):
                    raise ValueError('created stream nonfinite numeric value is not strict JSON')
    if (terminal.get('record_type') != 'terminal' or terminal.get('ok') is not True
            or terminal.get('status') != 'completed' or terminal.get('cleanup') != 'unsubscribed'
            or terminal.get('completion_reason') != 'event_count_reached'
            or type(terminal.get('event_count')) is not int or terminal['event_count'] != 4
            or type(terminal.get('requested_event_count')) is not int or terminal['requested_event_count'] != 4
            or terminal.get('event_count_reached') is not True
            or canonical_digest(terminal.get('monitoring_outcome')) != canonical_digest({
                'subscription_established': True, 'requested_event_count': 4, 'event_count': 4,
                'target_completed': True, 'termination': 'event_count_reached'})
            or canonical_digest(record.get('lifecycle')) != canonical_digest({'unsubscribe_count': 1, 'disconnected': True})):
        raise ValueError('created stream completed count and final cleanup required')
    info_calls = record.get('info_calls', [])
    if len(info_calls) != 1 or info_calls[0]['uri'] != 'ak.wwise.core.getInfo':
        raise ValueError('created stream original host detection missing')
    info = info_calls[0]['result']
    if info.get('isCommandLine') is not True or '.'.join(str(info['version'][key]) for key in ('year', 'major', 'minor', 'build')) != build:
        raise ValueError('created stream injected host/build context differs')
    for pointer in (f'/stream_records/{index + 1}/event', '/gateway/payload', '/subscriptions', '/lifecycle'):
        if not any(check['pointer'] == pointer and 'equals' in check for check in checks):
            raise ValueError('created stream exact whole event/terminal/subscription/cleanup proof missing')
    public_checks = [check for check in checks if check['pointer'] == public_pointer]
    if not any(proves_alternative(check, branch) for check in public_checks):
        raise ValueError('created stream exact public scalar alternative proof missing')


@lru_cache(maxsize=10)
def _created_topic_catalog(catalog_root, version, seal):
    from pathlib import Path
    from wwise_waapi.native_catalog import load_native_catalog
    # seal is the verified exact-byte cache key; load retains the original
    # index, content, complete reflection and reference validation checks.
    return load_native_catalog(version, 'wwise-console', root=Path(catalog_root))


def evidence_result(descriptor, branch, candidate, category, scope_kind, base, binding=None, source_root=None, reference_edges=None, historical_sources=None):
    """Read preserved run records. A declaration/test filename has no PASS credit."""
    from pathlib import Path
    root = source_root or Path(__file__).resolve().parents[2]
    try:
        if (binding or {}).get('condition_source_mapping_attachment'):
            from tests.support.condition_completion_mapping import mapping_evidence_result
            return mapping_evidence_result(descriptor, branch, category, scope_kind, base, binding, root)
        if category == 'native' and (binding or {}).get('condition_mechanism_attachment'):
            from tests.support.condition_mechanism_reuse import condition_mechanism_result
            return condition_mechanism_result(descriptor, branch, candidate, scope_kind, base, binding, root, reference_edges or {})
        if category == 'live_metadata' and (binding or {}).get('condition_metadata_mechanism_attachment'):
            from tests.support.condition_mechanism_reuse import condition_mechanism_result
            return condition_mechanism_result(descriptor, branch, candidate, scope_kind, base, binding, root, reference_edges or {}, category=category)
        record = read_sealed_artifact(descriptor, base)
        rtpc_normalized = None
        if category == 'program':
            from wwise_waapi.runtime_inspection_business_contracts import PROFILER_GET_RTPS_URI
            # The source-owned exact read route determines capture eligibility;
            # caller-removable evidence markers cannot disable this contract.
            if ((branch.get('route') or '').endswith('|function|' + PROFILER_GET_RTPS_URI)
                    and not (binding or {}).get('runtime_observation_attachment')):
                from tests.support.runtime_observation_evidence import validate_rtpc_program
                rtpc_normalized = validate_rtpc_program(record, binding or {}, branch, root, reference_edges)
            if ((branch.get('route') or '').endswith('|function|ak.wwise.core.profiler.getVoiceContributions')
                    and not (binding or {}).get('runtime_observation_attachment')):
                from tests.support.runtime_observation_evidence import validate_contribution_program
                validate_contribution_program(record, binding or {}, branch, root)
        if (binding or {}).get('runtime_observation_attachment'):
            from tests.support.runtime_observation_evidence import validate_runtime_evidence
            validate_runtime_evidence(record, binding, branch, category, base, root, reference_edges)
        if record.get('candidate_sha256') != candidate:
            validate_equivalence((binding or {}).get('equivalence', {}), descriptor, record, branch, candidate, binding or {}, base, root)
        if record.get('scope_kind', 'product') != scope_kind:
            raise ValueError('controlled evidence cannot grant product credit')
        binding = binding or {}
        metadata_context = None
        metadata_pointer = None
        metadata_replay = False
        if category == 'live_metadata':
            metadata_context = read_metadata_run(record['metadata_run'], base,
                historical_class=record.get('evidence_kind')=='historical_class_metadata_current_program_replay')
            record['gateway'] = metadata_context['gateway']
            if (branch.get('route') or '').endswith('|function|ak.wwise.core.object.getPropertyInfo'):
                if not branch['pointer'].startswith('/resultSchema/') and branch['pointer'] != '/resultSchema':
                    raise ValueError('live metadata projection requires a reflected resultSchema branch')
                # The same binding retains the program's exact native occurrence.
                # A real metadata receipt observes its corresponding public leaf.
                exact_observation_pointer(branch, binding, binding.get('dispatch_pointer', '/native_call'),
                                          'result', reference_edges or {})
                metadata_pointer = binding.get('gateway_observation_pointer', '')
                exact_observation_pointer(branch, {**binding, 'observation_pointer': metadata_pointer},
                                          '/gateway/payload/agent_result', 'metadata', reference_edges or {})
                if (branch['pointer'] == '/resultSchema/properties/default/@presence/absent'
                        and not isinstance(pointer_value(record, '/gateway/payload/agent_result/metadata'), dict)):
                    raise ValueError('absent metadata default requires an existing metadata object')
            else:
                metadata_pointer = binding.get('observation_pointer', '')
            if metadata_pointer.startswith('/gateway/payload/agent_result/') is False:
                raise ValueError('live metadata requires an exact original public result field')
        if category in ('native', 'native_absence'):
            observations = record.get('observation_artifacts', {})
            if not observations:
                raise ValueError('native branch needs original sealed observation artifacts')
            if binding.get('native_observations_sha256') != {name: item['sha256'] for name, item in observations.items()}:
                raise ValueError('reviewed native observation artifact mapping missing')
            record['observations'] = {name: read_sealed_artifact(item, base) for name, item in observations.items()}
            if category == 'native' and not binding.get('observation_pointer', '').startswith('/observations/'):
                raise ValueError('native branch assertion must observe an original artifact')
        invocation = record['invocation']
        if invocation['phase'] != 'final':
            raise ValueError('nonfinal evidence')
        nodes = {r['nodeid']: r['outcome'] for r in invocation['node_outcomes']}
        nodeid = descriptor['nodeid']
        if not nodeid or nodeid not in nodes:
            raise ValueError('exact executed test node missing')
        assertion = record['branch_assertions'][branch['id']]
        if assertion['native_shape_sha256'] != branch['shape_sha256'] or assertion['native_route'] != branch['route']:
            raise ValueError('native shape/context mismatch')
        if invocation['outcome'] == 'BLOCKED' and nodes[nodeid] == 'BLOCKED' and record.get('environment_blocker'):
            return 'blocked', record['environment_blocker']
        if invocation['outcome'] != 'PASS' or nodes[nodeid] != 'PASS':
            raise ValueError('executed node did not pass')
        checks = assertion['checks']
        if not checks or not all(isinstance(check, dict) and set(check) in ({'pointer', 'equals'}, {'pointer', 'absent'}, {'pointer', 'cardinality'}) for check in checks):
            raise ValueError('exact branch assertions missing')
        binding = binding or {}
        dispatch_pointer = binding.get('dispatch_pointer', '/native_call')
        section = branch['pointer'].split('/')[1]
        native_section = {'argsSchema': 'args', 'optionsSchema': 'options', 'resultSchema': 'result', 'publishSchema': 'event'}.get(section)
        prefix = metadata_pointer if category == 'live_metadata' else binding.get('observation_pointer')
        boundary = branch.get('approved_boundary')
        if boundary is None and category != 'native_absence':
            if rtpc_normalized is not None:
                prefix = rtpc_normalized['observation_pointer']
            elif native_section is not None and category == 'program':
                program_binding = ({**binding, 'observation_pointer': binding['program_observation_pointer']}
                    if binding.get('runtime_observation_attachment') else binding)
                prefix = exact_observation_pointer(branch, program_binding, dispatch_pointer, native_section, reference_edges or {})
            relevant = [c for c in checks if c['pointer'] == prefix]
            if not relevant or not any('equals' in c if rtpc_normalized is not None else proves_alternative(c, branch) for c in relevant):
                raise ValueError('same exact observation must prove the declared native branch semantics')
            import re
            if rtpc_normalized is None and branch['kind'] == 'schema' and re.search(r'/(oneOf|OneOf|anyOf|allOf)/[0-9]+$', branch['pointer']):
                validate_native_alternative(root, branch, pointer_value(record, prefix))
            if branch['kind'] == 'default' and not any(c['pointer'] == binding.get('default_omission_pointer') and c.get('absent') is True for c in checks):
                raise ValueError('default needs exact omitted public input as well as observed default value')
        for check in checks:
            if 'absent' in check:
                if check['absent'] is not True:
                    raise ValueError('absence assertion must be explicit')
                try:
                    pointer_value(record, check['pointer'])
                except (KeyError, IndexError):
                    continue
                raise ValueError('asserted omission is present')
            observed = pointer_value(record, check['pointer'])
            if 'cardinality' in check:
                if not isinstance(observed, list) or check['cardinality'] != ('empty' if not observed else 'single' if len(observed) == 1 else 'multiple'):
                    raise ValueError('collection cardinality assertion failed')
            elif type(observed) is not type(check['equals']) or observed != check['equals']:
                raise ValueError('branch assertion does not match preserved artifact')
        for artifact in record.get('artifacts', []):
            read_sealed_artifact(artifact, base)
        if boundary is not None:
            validate_boundary_receipt(record, branch, binding, checks)
        if category == 'native' and binding.get('source_copy_native_proof'):
            from tests.support.source_copy_native_evidence import validate_source_native
            validate_source_native(record, binding, branch, base)
        if category == 'program' and binding.get('source_copy_proof'):
            from tests.support.source_copy_branch_evidence import validate_source_program
            validate_source_program(record, binding, branch, base)
        if category == 'program' and boundary is None:
            gateway = record['gateway']
            if binding is None or gateway['argv'] != binding.get('input', {}).get('gateway_argv'):
                raise ValueError('public input differs from executed Gateway continuation')
            native_call = pointer_value(record, dispatch_pointer)
            if branch['route'] is not None and native_call['uri'] != branch['route'].split('|')[4]:
                raise ValueError('mapped native dispatch URI mismatch')
            public_pointer = binding.get('gateway_observation_pointer', '/gateway/payload/agent_result')
            public_equals = any(c['pointer'] == public_pointer and 'equals' in c for c in checks)
            if (not public_equals and (branch.get('route') or '').endswith('|function|' + PROFILER_GET_RTPS_URI)
                    and branch['kind'] == 'optional_presence' and branch.get('value') == 'absent'
                    and public_pointer.startswith('/gateway/payload/agent_result/return/')
                    and {'pointer': public_pointer, 'absent': True} in checks
                    and isinstance(pointer_value(record, public_pointer.rsplit('/', 1)[0]), dict)
                    and any(c['pointer'] == public_pointer.rsplit('/', 1)[0]
                        and isinstance(c.get('equals'), dict) for c in checks)):
                # validate_rtpc_program already requires the same absent field
                # within existing native/public rows and complete array equality.
                public_equals = True
            if (not public_equals and branch['route'] is not None
                    and branch['route'].endswith('|function|ak.wwise.core.object.getPropertyInfo')
                    and branch['pointer'] == '/resultSchema/properties/default/@presence/absent'
                    and branch['kind'] == 'optional_presence' and branch.get('value') == 'absent'
                    and public_pointer == '/gateway/payload/agent_result/metadata/default'
                    and {'pointer': public_pointer, 'absent': True} in checks
                    and isinstance(pointer_value(record, '/gateway/payload/agent_result/metadata'), dict)
                    and any(c['pointer'] == '/gateway/payload/agent_result' and 'equals' in c for c in checks)):
                public_equals = True
            if public_pointer.startswith('/stream_records/'):
                validate_created_topic_program(record, branch, binding, checks, root, reference_edges or {})
            elif (not public_pointer.startswith('/gateway/payload/agent_result')
                    or not public_equals):
                raise ValueError('exact public Gateway result assertion missing')
            if gateway['exit_code'] != 0 or gateway['payload'].get('ok') is not True or not gateway['argv']:
                raise ValueError('successful public Gateway receipt missing')
        if category in ('native', 'live_metadata', 'native_absence'):
            expected_version = branch['route'].split('|')[0] if branch['route'] else branch['version']
            expected_build = branch['route'].split('|')[2] if branch['route'] else branch['build']
            required_hosts = {branch['route'].split('|')[1]} if branch['route'] else set(binding.get('native_hosts', []))
            if category == 'native_absence' and branch['route'] is None:
                required_hosts = {'wwise-console', 'wwise-authoring'}
            if not required_hosts or not required_hosts <= {'wwise-console', 'wwise-authoring'}:
                raise ValueError('exact reviewed native host requirements missing')
            observed_hosts = set()
            if category == 'live_metadata':
                contexts = [(metadata_context, {'sha256': metadata_context['receipt_sha256']})]
                if metadata_context.get('format') == 'waapi-skill.r51-metadata-read/v1':
                    validate_r51_metadata_replay(record,branch,candidate,binding,metadata_context,base,root,scope_kind,reference_edges or {})
                    metadata_replay = True
                elif metadata_context.get('format') == 'waapi-skill.class-metadata-read/v1':
                    if record.get('evidence_kind')=='historical_class_metadata_current_program_replay':
                        validate_r54_metadata_replay(record,branch,candidate,binding,metadata_context,base,root,scope_kind,reference_edges or {})
                    else:validate_current_class_metadata(record,branch,binding,metadata_context,scope_kind)
                    metadata_replay = True
                elif record['gateway']['argv'] != binding.get('input', {}).get('gateway_argv'):
                    raise ValueError('metadata public input mismatch')
            else:
                if record.get('evidence_kind') != 'native_execution' or not record.get('native_runs'):
                    raise ValueError('existing native run required; injected clients/reflection are insufficient')
                contexts = [(read_category_run(item, base), item) for item in record['native_runs']]
                # A family PASS is insufficient: the exact node must own the sealed
                # original observations explicitly mapped to this branch.
                for context, item in contexts:
                    linked = item.get('observation_sha256', [])
                    expected_links = ({record['observation_artifacts'][context['host']]['sha256']} if category == 'native_absence'
                                      else {v['sha256'] for v in record['observation_artifacts'].values()})
                    if set(linked) != expected_links:
                        raise ValueError('native exact node observation links missing')
            for context, item in contexts:
                if context['version'] != expected_version or context['build'] != expected_build:
                    raise ValueError('native version/build mismatch')
                observed_hosts.add(context['host'])
                if not metadata_replay:
                    validate_native_source(context, item, branch, candidate, binding, base, root, historical_sources)
            if observed_hosts != required_hosts:
                raise ValueError('native host context evidence mismatch')
        if category == 'native_absence':
            validate_native_absence_observations(record, binding, checks, required_hosts)
            if record.get('native_status') != 'absent' or not record.get('alternatives_considered'):
                raise ValueError('native absence needs exact observation and alternative analysis')
        if category == 'fresh':
            raise ValueError('formal Fresh archive bridge requires #194; labels alone grant no credit')
        return 'passed', None
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return 'missing', str(exc)


def evaluate_coverage(root, inventory, bindings_document, *, digest, scope=None, evidence_base=None, requirements_document=None):
    """Evaluate exact obligations; structural reproducibility remains separate."""
    import ast
    from copy import deepcopy
    from pathlib import Path
    source = inventory['native_coverage']
    native = {key: deepcopy(value) for key, value in source.items() if key != 'obligations'}
    selected_ids = set(scope.get('route_ids', [])) if scope is not None else None
    native['obligations'] = [deepcopy(row) for row in source['obligations'] if selected_ids is None or row['route'] in selected_ids]
    scope_kind = 'controlled' if scope is not None else 'product'
    if scope is not None:
        if (scope.get('contract') != 'waapi-skill.controlled-branch-scope/v1'
                or scope.get('credit') != 'controlled_program_only' or not scope.get('id')
                or scope.get('requirements') != ['program'] or scope.get('native_catalogs') != native['catalogs']):
            raise ValueError('invalid or stale controlled scope')
        selected = scope.get('route_ids', [])
        if not selected or len(set(selected)) != len(selected):
            raise ValueError('empty/duplicate controlled scope')
        native['routes'] = [r for r in native['routes'] if r['id'] in selected]
        if {r['id'] for r in native['routes']} != set(selected):
            raise ValueError('scope contains unknown native route')
        native['obligations'] = [r for r in native['obligations'] if r['route'] in selected]
        ids = scope.get('obligation_ids', [])
        if not ids or len(set(ids)) != len(ids) or set(ids) != {r['id'] for r in native['obligations']}:
            raise ValueError('controlled scope omits native branch')
    if bindings_document.get('contract') != 'waapi-skill.branch-bindings/v1':
        raise ValueError('invalid branch binding contract')
    bindings = bindings_document['bindings']
    if not isinstance(bindings, dict):
        raise ValueError('bindings must be an exact ID map')
    ids = {r['id'] for r in native['obligations']}
    if set(bindings) - ids:
        raise ValueError('binding is not an exact in-scope branch')
    if requirements_document is None:
        requirements_document = ({'contract': 'waapi-skill.branch-evidence-requirements/v1',
            'branches': {r['id']: {'native_shape_sha256': r['shape_sha256'], 'categories': scope['requirements'],
                         'reason': 'Explicit sealed controlled program scope'} for r in native['obligations']}}
            if scope is not None else __import__('json').loads((root / 'docs/branch-coverage-requirements.json').read_text()))
    if requirements_document.get('contract') != 'waapi-skill.branch-evidence-requirements/v1':
        raise ValueError('invalid evidence requirements contract')
    policies = requirements_document['branches']
    if not isinstance(policies, dict) or set(policies) - ids:
        raise ValueError('requirements must name exact in-scope branches')
    public = {r['id']: r for r in inventory['routes']}
    routes = {r['id']: r for r in native['routes']}
    symbols = {}
    reference_edges = {r['id']: r for r in source['obligations'] if r['kind'] == 'reference'} if any(b.get('reference_chain') for b in bindings.values()) else {}

    def exact_source(binding):
        source, separator, symbol = binding.get('source', '').partition('#')
        if not separator or not symbol or not binding.get('selector'):
            return False
        path = (root / source).resolve()
        if not path.is_relative_to((root / 'skills/waapi-skill').resolve()) or path.suffix != '.py':
            return False
        if source not in symbols:
            try:
                symbols[source] = {n.name for n in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
                                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
            except (OSError, SyntaxError):
                return False
        return symbol in symbols[source]

    condition_reuse_reviews, condition_reuse_runs = set(), set()
    definition_contexts, definition_proofs = {}, {}
    historical_sources = {}  # Immutable Git objects only; never shared across evaluations.
    for branch in native['obligations']:
        branch['requirements'] = []
        route = routes.get(branch['route'])
        binding = bindings.get(branch['id'])
        branch['reasons'] = []
        branch['evidence_results'] = {}
        if branch.get('owner_issue') not in range(177, 194):
            branch['state'] = 'unresolved'
            branch['reasons'] = ['functional ownership requires bounded same-parent implementation child; #195 is acceptance only']
            continue
        if route and route['uri'] in {'ak.wwise.ui.cli.executeLuaScript', 'ak.wwise.ui.cli.launch'} and route['host'] == 'wwise-authoring':
            branch['state'] = 'approved_exclusion'
            branch['exclusion'] = {'authority': 'docs/plans/full-waapi-coverage/SPEC.md',
                'authority_sha256': digest((root / 'docs/plans/full-waapi-coverage/SPEC.md').read_text(encoding='utf-8')),
                'exact_uri': route['uri'], 'execution_credit': False}
            continue
        if route and route['public_route'] is None:
            branch['state'] = 'missing_implementation'
            branch['reasons'] = ['native route has no public implementation']
            continue
        if binding is None:
            branch['state'] = 'unresolved'
            branch['reasons'] = ['exact input/construction/validation/verifier mapping missing; parent/family source attribution is not proof']
            continue
        if binding.get('condition_source_mapping_attachment'):
            from tests.support.condition_completion_mapping import (validate_mapping_attachment,
                evaluate_definition_binding, witness_references)
            descriptor = binding['condition_source_mapping_attachment']
            key = digest(descriptor)
            if key not in definition_contexts:
                definition_contexts[key] = validate_mapping_attachment(descriptor, evidence_base or root, root)
            context = definition_contexts[key]
            evaluate_definition_binding(branch, binding, policies.get(branch['id'], {}), scope_kind,
                evidence_base or root, root, context)
            if branch['state'] == 'source_definition_verified':
                for proof in witness_references(context['members'][branch['id']], context):
                    definition_proofs[proof['original_proof_id']] = proof
            continue
        if binding.get('disposition') == 'native_absence':
            if route is not None or not binding.get('alternatives_considered'):
                branch['state'] = 'unresolved'
                branch['reasons'] = ['present native schema or missing Skill implementation cannot become native absence']
                continue
            result, reason = evidence_result(binding.get('evidence', {}).get('native_absence', {}), branch,
                native['candidate_sha256'], 'native_absence', scope_kind, evidence_base or root, binding, root,
                historical_sources=historical_sources)
            branch['state'] = 'proven_native_absence' if result == 'passed' else 'unresolved'
            branch['reasons'] = [] if reason is None else [reason]
            continue
        valid = (binding.get('branch_id') == branch['id'] and binding.get('native_shape_sha256') == branch['shape_sha256']
                 and binding.get('public_route') in public and isinstance(binding.get('input'), dict)
                 and binding['input'].get('gateway_argv') and binding['input'].get('selector')
                 and binding.get('public_route_sha256') == digest(public[binding['public_route']])
                 and (route is None or binding['public_route'] == route['public_route'])
                 and all(exact_source(binding.get(key, {})) and binding[key]['selector'] == branch['pointer'] for key in ('construction', 'validation', 'verifier'))
                 and binding.get('disposition', 'implemented') in ('implemented', 'approved_boundary'))
        if valid and binding.get('disposition') == 'approved_boundary':
            boundary = approved_boundary(root, branch, binding, route, public[binding['public_route']], digest)
            valid = boundary is not None
            if valid:
                branch['approved_boundary'] = boundary
        if not valid:
            branch['state'] = 'missing_implementation'
            branch['reasons'] = ['exact public input/construction/validation/verifier binding missing or stale']
            continue
        policy = policies.get(branch['id'], {})
        categories = policy.get('categories')
        if (policy.get('native_shape_sha256') != branch['shape_sha256'] or not policy.get('reason')
                or not isinstance(categories, list) or not categories or 'program' not in categories
                or len(categories) != len(set(categories))
                or any(c not in ('program', 'native', 'live_metadata', 'fresh') for c in categories)):
            branch['state'] = 'unresolved'
            branch['reasons'] = ['reviewed exact branch evidence requirements missing or stale']
            continue
        branch['requirements'] = categories[:]
        branch['requirements_sha256'] = digest(policy)
        branch['binding_sha256'] = digest(binding)
        extra = binding.get('additional_requirements', [])
        if not isinstance(extra, list) or any(r not in ('program', 'native', 'live_metadata', 'fresh') for r in extra):
            raise ValueError('unknown required evidence category')
        branch['requirements'] = sorted(set(branch['requirements'] + extra))
        for required in branch['requirements']:
            outcome, reason = evidence_result(binding.get('evidence', {}).get(required, {}), branch,
                native['candidate_sha256'], required, scope_kind, evidence_base or root, binding, root, reference_edges,
                historical_sources=historical_sources)
            branch['evidence_results'][required] = {'outcome': outcome, 'reason': reason}
        outcomes = {r['outcome'] for r in branch['evidence_results'].values()}
        if branch['evidence_results'].get('native', {}).get('outcome') == 'reviewed_mechanism_reuse':
            from tests.support.condition_mechanism_reuse import load_review
            review = load_review(root)
            condition_reuse_reviews.add(review['review_id'])
            condition_reuse_runs.add(review['witness']['run_id'])
            branch['direct_recipient_native_effect'] = 'not_observed'
        if branch['evidence_results'].get('live_metadata', {}).get('outcome') == 'reviewed_class_metadata_and_object_scope_mechanism':
            branch['metadata_scope'] = 'object_type'
            branch['direct_recipient_instance_metadata'] = 'not_observed'
        branch['state'] = 'verified' if outcomes <= {'passed', 'reviewed_mechanism_reuse', 'reviewed_class_metadata_and_object_scope_mechanism'} else 'environment_blocked' if 'blocked' in outcomes else 'implemented_unverified'
    complete_states = {'verified', 'source_definition_verified', 'proven_native_absence', 'approved_exclusion'}
    counts = dict(sorted(Counter(r['state'] for r in native['obligations']).items()))
    if condition_reuse_reviews:
        native['condition_mechanism_reuse'] = {'original_witness_run_ids': sorted(condition_reuse_runs),
            'review_ids': sorted(condition_reuse_reviews), 'new_native_runs': 0}
    if definition_contexts:
        from tests.support.condition_completion_mapping import _review
        _review(root)  # Source immutability also holds at the end of this batch.
        native['condition_source_definition_reuse'] = {
            'original_native_witness_proofs': [definition_proofs[k] for k in sorted(definition_proofs)],
            'original_run_count': 'not_summed_from_member_bindings; original identities retained inside exact proofs',
            'new_native_runs': 0, 'direct_recipient_instance_metadata': 'not_observed'}
    native['scope_kind'] = scope_kind
    native['scope_sha256'] = digest(scope) if scope is not None else None
    native['bindings_sha256'] = digest(bindings_document)
    native['requirements_sha256'] = digest(requirements_document)
    native['completion'] = {'complete': bool(native['obligations']) and all(r['state'] in complete_states for r in native['obligations']),
        'obligations': len(native['obligations']), 'routes': len(native['routes']), 'states': counts, 'by_owner': {str(owner): dict(sorted(Counter(r['state'] for r in native['obligations'] if r['owner_issue'] == owner).items()))
                                     for owner in sorted({r['owner_issue'] for r in native['obligations']}, key=str)}}
    return native
