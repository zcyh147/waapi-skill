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


def validate_authoring_batch_finalization(run, base):
    """New shared Authoring rows need the whole completed batch publication."""
    import hashlib
    import json
    from pathlib import Path
    try:
        categories = run['categories']
        descriptors = [row['batch_finalization'] for row in categories]
        if not descriptors or any(row != descriptors[0] for row in descriptors):
            raise ValueError('node finalization links differ')
        seal = read_sealed_artifact(descriptors[0], base)
        invocation = run['invocation']
        lifecycle = seal['lifecycle']
        if (seal['contract'] != 'waapi-skill.authoring-batch-finalization/v1' or seal['outcome'] != 'PASS'
                or any(seal[key] != run[key] for key in ('candidate', 'version', 'host', 'transactions'))
                or any(seal[key] != invocation[key] for key in ('selected_test_nodeids', 'node_outcomes', 'started_at_unix_ns'))
                or any(row['outcome'] != 'PASS' for row in seal['node_outcomes'])
                or {row['nodeid'] for row in categories} != set(seal['selected_test_nodeids'])
                or len(categories) != len(seal['selected_test_nodeids'])
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
            raw = Path(observation['path']).read_bytes()
            if len(raw) != observation['bytes'] or hashlib.sha256(raw).hexdigest() != observation['sha256']:
                raise ValueError('node original observation seal differs')
            original = json.loads(raw)
            if (original['nodeid'] != nodeid or original['candidate'] != run['candidate']
                    or original['source_context'] != seal['source_context']):
                raise ValueError('node original context differs')
            for artifact in original['artifacts'].values():
                root = Path(artifact['path'])
                for entry in artifact['files']:
                    path = (root / entry['path']).resolve()
                    if not path.is_relative_to(root.resolve()):
                        raise ValueError('node artifact escaped its archive')
                    content = path.read_bytes()
                    if len(content) != entry['bytes'] or hashlib.sha256(content).hexdigest() != entry['sha256']:
                        raise ValueError('node archived evidence differs')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'Authoring batch finalization is incomplete: {exc}') from exc


def read_metadata_run(descriptor, base):
    """Read sealed ScenarioLifecycle/v3 captures and their original public receipts."""
    import hashlib
    import json
    from pathlib import Path
    seal = read_sealed_artifact(descriptor['seal'], base)
    root = Path(descriptor['root'])
    if not root.is_absolute():
        root = base / root
    files = {r['path']: r for r in seal['files']}
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
    sources = {r['path'][len(repository['checkout']) + 1:]: r['sha256'] for r in plan['source_seals']
               if r['path'].startswith(repository['checkout'] + '/')}
    return dict(context, candidate=repository['commit'], relevant_sources=sources,
                gateway={'argv': command['gateway_arguments'], 'exit_code': result['exit_code'], 'payload': payload},
                receipt_sha256=files[prefix + '.stdout']['sha256'])


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
    if (not sources or set(sources) != set(binding.get('relevant_sources', [])) or not required <= set(sources)
            or sources != record.get('relevant_sources')):
        raise ValueError('equivalence omits original relevant source/behavior dependencies')
    for name, seal in sources.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != seal:
            raise ValueError('equivalence relevant source changed')


def validate_native_source(context, descriptor, branch, candidate, binding, base, root):
    """Bridge an original producer's Git identity to the reviewed branch candidate."""
    import hashlib
    import subprocess
    sources = context.get('relevant_sources')
    selected = binding.get('relevant_sources', [])
    if sources is None:
        sources = {}
        for name in selected:
            completed = subprocess.run(['git', 'show', context['candidate'] + ':' + name], cwd=root,
                                       check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if completed.returncode:
                raise ValueError('original native source candidate unavailable')
            sources[name] = hashlib.sha256(completed.stdout).hexdigest()
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


def evidence_result(descriptor, branch, candidate, category, scope_kind, base, binding=None, source_root=None, reference_edges=None):
    """Read preserved run records. A declaration/test filename has no PASS credit."""
    from pathlib import Path
    root = source_root or Path(__file__).resolve().parents[2]
    try:
        record = read_sealed_artifact(descriptor, base)
        if record.get('candidate_sha256') != candidate:
            validate_equivalence((binding or {}).get('equivalence', {}), descriptor, record, branch, candidate, binding or {}, base, root)
        if record.get('scope_kind', 'product') != scope_kind:
            raise ValueError('controlled evidence cannot grant product credit')
        binding = binding or {}
        metadata_context = None
        metadata_pointer = None
        if category == 'live_metadata':
            metadata_context = read_metadata_run(record['metadata_run'], base)
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
            if native_section is not None and category == 'program':
                prefix = exact_observation_pointer(branch, binding, dispatch_pointer, native_section, reference_edges or {})
            relevant = [c for c in checks if c['pointer'] == prefix]
            if not relevant or not any(proves_alternative(c, branch) for c in relevant):
                raise ValueError('same exact observation must prove the declared native branch semantics')
            import re
            if branch['kind'] == 'schema' and re.search(r'/(oneOf|OneOf|anyOf|allOf)/[0-9]+$', branch['pointer']):
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
        if category == 'program' and boundary is None:
            gateway = record['gateway']
            if binding is None or gateway['argv'] != binding.get('input', {}).get('gateway_argv'):
                raise ValueError('public input differs from executed Gateway continuation')
            native_call = pointer_value(record, dispatch_pointer)
            if branch['route'] is not None and native_call['uri'] != branch['route'].split('|')[4]:
                raise ValueError('mapped native dispatch URI mismatch')
            public_pointer = binding.get('gateway_observation_pointer', '/gateway/payload/agent_result')
            public_equals = any(c['pointer'] == public_pointer and 'equals' in c for c in checks)
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
                if record['gateway']['argv'] != binding.get('input', {}).get('gateway_argv'):
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
                validate_native_source(context, item, branch, candidate, binding, base, root)
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
        if binding.get('disposition') == 'native_absence':
            if route is not None or not binding.get('alternatives_considered'):
                branch['state'] = 'unresolved'
                branch['reasons'] = ['present native schema or missing Skill implementation cannot become native absence']
                continue
            result, reason = evidence_result(binding.get('evidence', {}).get('native_absence', {}), branch,
                native['candidate_sha256'], 'native_absence', scope_kind, evidence_base or root, binding, root)
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
                native['candidate_sha256'], required, scope_kind, evidence_base or root, binding, root, reference_edges)
            branch['evidence_results'][required] = {'outcome': outcome, 'reason': reason}
        outcomes = {r['outcome'] for r in branch['evidence_results'].values()}
        branch['state'] = 'verified' if outcomes == {'passed'} else 'environment_blocked' if 'blocked' in outcomes else 'implemented_unverified'
    complete_states = {'verified', 'proven_native_absence', 'approved_exclusion'}
    counts = dict(sorted(Counter(r['state'] for r in native['obligations']).items()))
    native['scope_kind'] = scope_kind
    native['scope_sha256'] = digest(scope) if scope is not None else None
    native['bindings_sha256'] = digest(bindings_document)
    native['requirements_sha256'] = digest(requirements_document)
    native['completion'] = {'complete': bool(native['obligations']) and all(r['state'] in complete_states for r in native['obligations']),
        'obligations': len(native['obligations']), 'routes': len(native['routes']), 'states': counts, 'by_owner': {str(owner): dict(sorted(Counter(r['state'] for r in native['obligations'] if r['owner_issue'] == owner).items()))
                                     for owner in sorted({r['owner_issue'] for r in native['obligations']}, key=str)}}
    return native
