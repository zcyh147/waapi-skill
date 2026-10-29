"""Narrow original Source category ownership; diagnostic verdicts stay immutable."""
from pathlib import Path

from tests.maintenance import branch_audit_completion as completion
from tests.support.source_copy_branch_evidence import dependency_review



SUCCESSOR_REVIEW_PATH = 'tests/fixtures/source-copy/branch-successor-review-195.json'
SUCCESSOR_REVIEW_SHA256 = '4cd9a81b3d413f46d7ecca6eec191984e338c5b3657b0d4e6955a167dac09a9b'
ACCOUNTING_REVIEW_PATH = 'tests/fixtures/source-copy/branch-accounting-review-195-publication.json'
ACCOUNTING_REVIEW_SHA256 = 'd8015509c0994ece40a458399fbacd2bdf8864fcd9c16831e2ae42e2c9e8c4fc'
ACCOUNTING_READER = 'tests/support/source_copy_native_evidence.py'
REQUIREMENTS_SOURCE = 'docs/branch-coverage-requirements.json'
ACCOUNTING_DEPENDENCIES = (
    'tests/support/new_condition_completion.py',
    'tests/unit/test_new_condition_completion_reader.py',
    'tests/support/condition_completion_mapping.py',
    'tests/fixtures/metadata-conditions/new-condition-current-program-r3.json.gz',
)


def accounting_source_seals(names, *, requirements_document=None, mapping_bindings=None):
    """Seal live sources with the explicit requirements and single-pin projections."""
    import ast
    import hashlib
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.source_copy_branch_evidence import source_seals
    names = set(names)
    result = source_seals(names)
    if REQUIREMENTS_SOURCE in names:
        from tests.maintenance.branch_audit_mapping import requirements_identity_projection
        document = (audit.load(audit.ROOT / REQUIREMENTS_SOURCE)
                    if requirements_document is None else requirements_document)
        result[REQUIREMENTS_SOURCE] = audit.digest(requirements_identity_projection(
            document, mapping_bindings, root=audit.ROOT))
    if ACCOUNTING_READER not in names:
        raise ValueError('Source accounting closure omits its reader')
    raw = (audit.ROOT / ACCOUNTING_READER).read_bytes()
    tree = ast.parse(raw)
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
                   and isinstance(node.ctx, ast.Store) and node.id == 'ACCOUNTING_REVIEW_SHA256']
    matches = [node for node in tree.body if isinstance(node, ast.Assign)
               and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
               and node.targets[0].id == 'ACCOUNTING_REVIEW_SHA256']
    if (len(assignments) != 1 or len(matches) != 1
            or not isinstance(matches[0].value, ast.Constant)
            or not isinstance(matches[0].value.value, str)
            or matches[0].value.value != ACCOUNTING_REVIEW_SHA256
            or len(ACCOUNTING_REVIEW_SHA256) != 64
            or any(char not in '0123456789abcdef' for char in ACCOUNTING_REVIEW_SHA256)):
        raise ValueError('Source accounting pin requires exactly one digest literal assignment')
    literal = matches[0].value
    lines = raw.splitlines(keepends=True)
    if literal.lineno != literal.end_lineno:
        raise ValueError('Source accounting pin requires one single-line literal')
    line = lines[literal.lineno - 1]
    token = line[literal.col_offset:literal.end_col_offset]
    if token not in {b"'" + ACCOUNTING_REVIEW_SHA256.encode() + b"'",
                     b'"' + ACCOUNTING_REVIEW_SHA256.encode() + b'"'}:
        raise ValueError('Source accounting pin requires one plain digest literal')
    lines[literal.lineno - 1] = (line[:literal.col_offset + 1] + b'0' * 64
                                + line[literal.end_col_offset - 1:])
    result[ACCOUNTING_READER] = hashlib.sha256(b''.join(lines)).hexdigest()
    return result


def accounting_dependency_review():
    """An exact reviewed accounting delta; execution sources never get an exemption."""
    import hashlib
    import json
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.source_copy_branch_evidence import source_seals
    raw = (audit.ROOT / ACCOUNTING_REVIEW_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ACCOUNTING_REVIEW_SHA256:
        raise ValueError('Reviewed Source accounting delta changed')
    review = json.loads(raw)
    fields = {'contract', 'scope', 'captured_git_candidate', 'captured_candidate_sha256',
              'relevant_sources', 'captured_capture_sources', 'current_accounting_sources',
              'source_changes', 'additional_sources', 'pin_normalization', 'packets', 'causal_review',
              'current_execution_sources', 'execution_source_changes'}
    if (set(review) != fields or review['contract'] != 'waapi-skill.source-copy-accounting-review/v1'
            or review['scope'] != 'retained-source-program-and-native-accounting-only'
            or review['captured_git_candidate'] != '88a6cbbeccee1b8f5934f61f7b75503e2a084073'
            or review['captured_candidate_sha256'] != '0383d01b4b400a52c94b1f3924a9234915e32a06583c89cd9aaaf8cb628ebdc3'
            or review['relevant_sources'] != successor_dependency_review()['current_sources']
            or set(review['additional_sources']) != set(ACCOUNTING_DEPENDENCIES)
            or len(review['additional_sources']) != len(ACCOUNTING_DEPENDENCIES)
            or review['pin_normalization'] != accounting_normalization()
            or not review['causal_review']
            or not isinstance(review['packets'], list) or len(review['packets']) != 5):
        raise ValueError('Complete reviewed Source accounting closure differs')
    captured = review['captured_capture_sources']
    current = review['current_accounting_sources']
    if set(current) != set(captured) | set(ACCOUNTING_DEPENDENCIES):
        raise ValueError('Complete reviewed Source accounting dependency set differs')
    expected = {name: {'captured_sha256': captured.get(name), 'current_sha256': seal}
                for name, seal in current.items() if captured.get(name) != seal}
    changes = review['source_changes']
    if (set(changes) != set(expected) or any(not isinstance(changes[name], dict)
            or set(changes[name]) != {'captured_sha256', 'current_sha256', 'reason'}
            or not changes[name]['reason']
            or any(changes[name][key] != value for key, value in row.items())
            for name, row in expected.items())):
        raise ValueError('Source accounting delta is not exact and complete')
    execution = review['current_execution_sources']
    before = review['relevant_sources']
    if not isinstance(execution, dict) or set(execution) != set(before):
        raise ValueError('Source accounting current execution source set differs')
    expected_execution = {name: {'captured_sha256': before[name], 'current_sha256': seal}
                          for name, seal in execution.items() if before[name] != seal}
    transition = review['execution_source_changes']
    if (not isinstance(transition, dict) or set(transition) != set(expected_execution)
            or any(not isinstance(transition[name], dict)
                or set(transition[name]) != {'captured_sha256', 'current_sha256', 'reason'}
                or not isinstance(transition[name]['reason'], str) or not transition[name]['reason'].strip()
                or any(transition[name][key] != value for key, value in row.items())
                for name, row in expected_execution.items())):
        raise ValueError('Source accounting execution transition is not exact and explained')
    if (accounting_source_seals(current) != current
            or source_seals(execution) != execution):
        raise ValueError('Source accounting current dependency changed')
    return review


def accounting_normalization():
    from tests.maintenance.branch_audit_mapping import REQUIREMENTS_IDENTITY_KIND
    return {'path': ACCOUNTING_READER, 'assignment': 'ACCOUNTING_REVIEW_SHA256', 'normalized_value': '0' * 64,
            'requirements_source': {'path': REQUIREMENTS_SOURCE, 'semantic_kind': REQUIREMENTS_IDENTITY_KIND}}


def _accounting_context(context, base, candidate):
    """Resolve the old execution context separately from its new admission target."""
    fields = {'contract', 'review', 'previous_index', 'current_candidate_sha256'}
    if (set(context) != fields or not isinstance(context['current_candidate_sha256'], str)
            or len(context['current_candidate_sha256']) != 64
            or candidate is not None and context['current_candidate_sha256'] != candidate):
        raise ValueError('Source accounting admitted candidate differs')
    review = accounting_dependency_review()
    if (context['review'].get('sha256') != ACCOUNTING_REVIEW_SHA256
            or _portable_source_document(context['review'], base) != review
            or context['previous_index'] not in review['packets']):
        raise ValueError('Source accounting reviewed predecessor differs')
    index = _portable_source_document(context['previous_index'], base)
    if len(index['entries']) != 1 or len(index['source_native_attachments']) != 1:
        raise ValueError('Source accounting requires one complete original packet')
    origin = index['entries'][0]['origin']
    program = _portable_source_document(origin['program'], base)
    if (program.get('candidate_sha256') != review['captured_candidate_sha256']
            or program.get('git_candidate') != review['captured_git_candidate']
            or program.get('relevant_sources') != review['relevant_sources']
            or program.get('capture_sources') != review['captured_capture_sources']):
        raise ValueError('Source accounting retained program sources or candidate differ')
    previous = _portable_source_document(index['source_native_attachments'][0], base)
    if previous.get('contract') != 'waapi-skill.source-copy-native-attachment/v2':
        raise ValueError('Source accounting requires its preserved v2 attachment')
    # Only this exact accounting packet qualifies an old context as history.
    # Direct v1/v2 validation below continues to require live source equality.
    old = _portable_source_document(previous['successor_context'], base)
    historical = successor_dependency_review()
    fields = {'contract', 'review', 'predecessor', 'original_source_context',
              'current_candidate_sha256', 'current_sources'}
    if (set(old) != fields or old['contract'] != 'waapi-skill.source-copy-successor-context/v1'
            or old['current_candidate_sha256'] != review['captured_candidate_sha256']
            or old['current_sources'] != review['relevant_sources']
            or not isinstance(old['review'], dict)
            or old['review'].get('sha256') != SUCCESSOR_REVIEW_SHA256
            or _portable_source_document(old['review'], base) != historical
            or old['predecessor'] not in historical['predecessor_attachments']
            or old['predecessor'] != previous['predecessor']):
        raise ValueError('Source accounting historical context/review differs')
    predecessor = _portable_source_document(old['predecessor'], base)
    if (set(predecessor) != {'contract', 'branch_ids', 'business_fact_id', 'proof', 'evidence',
                            'equivalence', 'native_equivalence'}
            or predecessor['contract'] != 'waapi-skill.source-copy-native-attachment/v1'):
        raise ValueError('Source accounting original predecessor differs')
    native = _portable_source_document({key: predecessor['evidence'][key] for key in ('artifact', 'sha256')}, base)
    original = _portable_source_document(old['original_source_context'], base)
    if (old['original_source_context'] != native['source_context']
            or original['current_sources'] != historical['historical_current_sources']):
        raise ValueError('Source accounting original source context differs')
    if any(previous[name] != predecessor[name] for name in ('proof', 'evidence', 'branch_ids', 'business_fact_id')):
        raise ValueError('Source accounting original native attribution differs')
    return {**old, 'current_candidate_sha256': context['current_candidate_sha256'],
        'captured_candidate_sha256': review['captured_candidate_sha256'], 'accounting_origin': origin,
        'current_execution_sources': review['current_execution_sources'], 'accounting_attachment': previous}, predecessor


def successor_dependency_review():
    """Read the separately approved successor; never rewrite the v1 review."""
    import hashlib
    import json
    from tests.maintenance import branch_coverage_audit as audit
    raw = (audit.ROOT / SUCCESSOR_REVIEW_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SUCCESSOR_REVIEW_SHA256:
        raise ValueError('Reviewed Source successor changed')
    review = json.loads(raw)
    old = dependency_review()
    historical = {**old['current_sources'],
        **old['launcher_and_dependency_config_source_maps'][old['current_source_basis']],
        **old['pinned_project_input_source_maps'][old['current_source_basis']]}
    from tests.support.source_copy_branch_evidence import REVIEW_SHA256
    if (review['contract'] != 'waapi-skill.source-copy-successor-review/v1'
            or review['predecessor_review_sha256'] != REVIEW_SHA256
            or review['predecessor_source_basis'] != old['current_source_basis']
            or review['historical_current_sources'] != historical
            or not set(historical) <= set(review['current_sources'])
            or review['selected_native_shapes'] != old['selected_native_shapes']
            or set(review['added_dependencies']) != set(review['current_sources']) - set(historical)
            or any(row['historical'] is not None or row['current_sha256'] != review['current_sources'][name]
                   for name, row in review['added_dependencies'].items())):
        raise ValueError('Complete reviewed Source successor closure differs')
    return review


def _portable_source_document(descriptor, base):
    from tests.semantic.support.codex_archive_paths import parse_archive_relative_path
    if not isinstance(descriptor, dict) or set(descriptor) != {'artifact', 'sha256'}:
        raise ValueError('Closed Source successor descriptor required')
    relative = parse_archive_relative_path(descriptor['artifact']).canonical
    boundary = Path(base).resolve(strict=True)
    path = boundary / relative
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(boundary):
        raise ValueError('Source successor descriptor escapes its bundle')
    return completion.read_sealed_artifact(descriptor, boundary)


def validate_successor_context(descriptor, base, *, candidate=None):
    """Bind a new current closure to the exact untouched original attachment."""
    context = _portable_source_document(descriptor, base)
    if context.get('contract') == 'waapi-skill.source-copy-successor-context/v2':
        return _accounting_context(context, base, candidate)
    fields = {'contract', 'review', 'predecessor', 'original_source_context',
              'current_candidate_sha256', 'current_sources'}
    if (not isinstance(context, dict) or set(context) != fields or context['contract'] != 'waapi-skill.source-copy-successor-context/v1'
            or not isinstance(context['current_candidate_sha256'], str)
            or len(context['current_candidate_sha256']) != 64
            or candidate is not None and context['current_candidate_sha256'] != candidate):
        raise ValueError('Source successor current candidate differs')
    reviewed = successor_dependency_review()
    if not isinstance(context['review'], dict):
        raise ValueError('Closed Source successor descriptor required')
    if (context['review'].get('sha256') != SUCCESSOR_REVIEW_SHA256
            or _portable_source_document(context['review'], base) != reviewed
            or context['current_sources'] != reviewed['current_sources']):
        raise ValueError('Complete reviewed Source successor context differs')
    from tests.support.source_copy_branch_evidence import source_seals
    if source_seals(reviewed['current_sources']) != reviewed['current_sources']:
        raise ValueError('Source successor current dependency changed')
    if context['predecessor'] not in reviewed['predecessor_attachments']:
        raise ValueError('Source successor original predecessor differs')
    predecessor = _portable_source_document(context['predecessor'], base)
    if (set(predecessor) != {'contract', 'branch_ids', 'business_fact_id', 'proof', 'evidence',
                            'equivalence', 'native_equivalence'}
            or predecessor['contract'] != 'waapi-skill.source-copy-native-attachment/v1'):
        raise ValueError('Source successor requires an original v1 attachment')
    native = completion.read_sealed_artifact(predecessor['evidence'], base)
    original = _portable_source_document(context['original_source_context'], base)
    if (context['original_source_context'] != native['source_context']
            or original['current_sources'] != reviewed['historical_current_sources']):
        raise ValueError('Source successor original context differs')
    return context, predecessor


def source_evidence_binding(binding, branch, candidate, base):
    """Restore only the trusted captured mapping for Source category checks."""
    from tests.maintenance.branch_audit_mapping import MAPPING_FIELDS
    context, predecessor = validate_successor_context(binding['source_copy_successor_context'], base, candidate=candidate)
    origin = context.get('accounting_origin')
    if origin is None:
        raise ValueError('Unbound Source accounting evidence mapping')
    document = _portable_source_document(origin['bindings'], base)
    original = document.get('bindings', {}).get(branch['id'])
    if (document.get('contract') != 'waapi-skill.branch-bindings/v1' or original is None
            or original.get('branch_id') != branch['id']
            or original.get('native_shape_sha256') != branch['shape_sha256']
            or binding.get('branch_id') != branch['id']
            or binding.get('native_shape_sha256') != branch['shape_sha256']
            or original.get('public_route') != '|'.join(branch['route'].split('|')[i] for i in (0, 3, 4))
            or binding.get('source_copy_native_proof') != predecessor['proof']):
        raise ValueError('Source accounting original mapping/branch differs')
    evidence_binding = {key: value for key, value in binding.items() if key not in MAPPING_FIELDS}
    evidence_binding.update({key: value for key, value in original.items() if key in MAPPING_FIELDS})
    # Protected decoration is still part of the existing whole-binding seal.
    proof = _portable_source_document(binding['source_copy_program_equivalence'], base)
    from tests.maintenance.branch_coverage_audit import digest
    if proof.get('binding_semantics_sha256') != digest(completion.binding_semantics(evidence_binding)):
        raise ValueError('Source accounting original evidence mapping equivalence differs')
    return evidence_binding


def source_program_equivalence(binding, descriptor, record, candidate, base):
    """A separate generic program bridge is owned by the validated accounting context."""
    context, predecessor = validate_successor_context(binding['source_copy_successor_context'], base, candidate=candidate)
    origin = context.get('accounting_origin')
    if (origin is None or {key: descriptor[key] for key in ('artifact', 'sha256')} != origin['program']
            or record != _portable_source_document(origin['program'], base)
            or binding.get('source_copy_native_proof') != predecessor['proof']
            or record['candidate_sha256'] != context['captured_candidate_sha256']):
        raise ValueError('Unbound Source accounting program equivalence')
    return binding['source_copy_program_equivalence']


def read_source_native_run(category, receipt, config, base):
    """Require the five reviewed native nodes, not a family or read-probe PASS."""
    context = completion.read_category_run(category, base)
    review = dependency_review()
    anchors = {row['version']: row for row in review['native_anchors']}
    anchor = anchors.get(context['version'])
    record = context['record']
    if (anchor is None or set(category) != {'artifact', 'sha256', 'record_index', 'nodeid'}
            or category['nodeid'] != anchor['selected_nodes'][0]
            or record['invocation']['selected_test_nodeids'] != anchor['selected_nodes']
            or record['invocation']['node_outcomes'] != [{'nodeid': category['nodeid'], 'outcome': 'PASS'}]
            or category['record_index'] != anchor['category']['record_index']
            or category['sha256'] != anchor['category']['sha256']
            or context['candidate'] != anchor['native_candidate']
            or receipt['sha256'] != anchor['receipt']['sha256']):
        raise ValueError('An exact original Source finalized node and receipt are required')
    categories = [row for row in record['categories']
                  if row.get('category') == ('repeated' if context['version'] == '2021.1' else 'modern') + '-source-copy-save-children-oracle']
    if (len(categories) != 1 or categories[0].get('status') != 'PASS'
            or categories[0].get('diagnostic_only') is not True
            or categories[0].get('business_effect_verified') is not False
            or categories[0].get('observation_sha256') != receipt['sha256']
            or categories[0].get('observation_path') != receipt['path']
            or record['source'] != anchor['preserved_source_tree']
            or config['sha256'] != anchor['public_config']['sha256']):
        raise ValueError('Exact original Source category ownership or preservation differs')
    configured = completion.read_sealed_artifact(config, base)
    if (set(configured) != {'wwise_version', 'waapi_host', 'waapi_port', 'project_modification_policy'}
            or configured['wwise_version'] != context['version']
            or configured['waapi_host'] != '127.0.0.1'
            or configured['project_modification_policy'] != 'ask_before_changes'):
        raise ValueError('Exact original Source isolated configuration differs')
    return {**context, 'anchor': anchor, 'category': categories[0], 'configuration': configured}


def validate_source_equivalence(proof, branch, binding, root, *, evidence_base):
    """Only the pinned five-version Source leaf bridge may cross changed bytes."""
    from tests.support.source_copy_branch_evidence import pointer_contract, native_route, REVIEW_SHA256
    import hashlib
    if binding.get('source_copy_program_equivalence'):
        binding = source_evidence_binding(binding, branch, proof['to_candidate'], evidence_base)
    review = dependency_review()
    from tests.support.source_copy_branch_evidence import PUBLIC_NODES
    versions = [version for version in PUBLIC_NODES if branch['route'] == native_route(version)]
    if len(versions) != 1:
        raise ValueError('Exact reviewed Source route required')
    version = versions[0]
    original = review['original_native_candidate'] if version == '2021.1' else review['modern_native_candidate']
    sources = native_source_maps(original)
    current = {**review['current_sources'],
        **review['launcher_and_dependency_config_source_maps'][review['current_source_basis']],
        **review['pinned_project_input_source_maps'][review['current_source_basis']]}
    successor = binding.get('source_copy_successor_context')
    if successor is not None:
        if proof.get('source_copy_successor_context') != successor:
            raise ValueError('Source successor equivalence context differs')
        context, _ = validate_successor_context(successor, evidence_base, candidate=proof['to_candidate'])
        current = context.get('current_execution_sources', context['current_sources'])
    elif proof.get('source_copy_successor_context') is not None:
        raise ValueError('Unbound Source successor equivalence')
    review_link = proof.get('source_copy_review', {})
    from tests.semantic.support.codex_archive_paths import parse_archive_relative_path
    if set(review_link) != {'artifact', 'sha256'}:
        raise ValueError('Closed portable Source review descriptor required')
    relative = parse_archive_relative_path(review_link['artifact']).canonical
    evidence_root = Path(evidence_base).resolve(strict=True)
    review_path = evidence_root / relative
    if review_path.is_symlink() or not review_path.resolve().is_relative_to(evidence_root):
        raise ValueError('Source review descriptor escapes its evidence bundle')
    if (branch['pointer'] not in pointer_contract(version)
            or branch['id'] != native_route(version) + '|' + branch['pointer']
            or review['selected_native_shapes'].get(branch['id']) != branch['shape_sha256']
            or proof.get('source_native_candidate') != original
            or review_link.get('sha256') != REVIEW_SHA256
            or completion.read_sealed_artifact(review_link, evidence_root) != review
            or proof['sources'] != sources or set(binding['relevant_sources']) != set(current)
            or not binding.get('source_copy_native_proof')
            or any(hashlib.sha256((root / name).read_bytes()).hexdigest() != seal for name, seal in current.items())):
        raise ValueError('Complete reviewed Source dependency bridge differs')


def native_source_maps(candidate):
    review = dependency_review()
    if candidate == review['original_native_candidate']:
        sources = review['original_sources']
    elif candidate == review['modern_native_candidate']:
        sources = review['modern_sources']
    else:
        raise ValueError('Unreviewed original Source candidate')
    return {**sources, **review['launcher_and_dependency_config_source_maps'][candidate],
            **review['pinned_project_input_source_maps'][candidate]}


def validate_source_native(record, binding, branch, base):
    """Recheck original category→receipt→selected files, not declared SHA lists."""
    from tests.support.source_copy_branch_evidence import source_facts, ProofFiles, native_route, pointer_contract, relevant_sources
    proof = completion.read_sealed_artifact(binding['source_copy_native_proof'], base)
    files = ProofFiles(proof, base)
    receipt = files.read(proof['receipt'])
    observations = record['observation_artifacts']
    if set(observations) != {'source', 'category', 'config'}:
        raise ValueError('Closed original Source observations required')
    context = read_source_native_run(observations['category'], proof['receipt'], observations['config'], base)
    facts = source_facts(proof, base)
    source_context = completion.read_sealed_artifact(record['source_context'], base)
    expected_current_sources = relevant_sources()
    successor = binding.get('source_copy_successor_context')
    if successor is not None:
        successor_context, predecessor = validate_successor_context(successor, base)
        if (predecessor['proof'] != binding['source_copy_native_proof']
                or predecessor['evidence'] != binding['evidence']['native']
                or successor_context['original_source_context'] != record['source_context']):
            raise ValueError('Source successor does not retain its original native proof')
        expected_current_sources = successor_dependency_review()['historical_current_sources']
    expected_ids = {native_route(facts['version']) + '|' + pointer for pointer in pointer_contract(facts['version'])}
    transactions = {row['transaction_id']: row for row in context['record']['transactions']}
    if (record.get('source_copy_proof') != binding['source_copy_native_proof']
            or branch['id'] not in expected_ids or record['observations']['source'] != facts
            or record.get('git_candidate') != context['candidate']
            or source_context['original_git_candidate'] != context['candidate']
            or source_context['original_candidate_sha256'] != record['candidate_sha256']
            or source_context['original_sources'] != native_source_maps(context['candidate'])
            or source_context['current_sources'] != expected_current_sources
            or record.get('relevant_sources') != native_source_maps(context['candidate'])
            or context['category']['transaction_ids'] != receipt['transaction_ids']
            or set(transactions) != set(receipt['transaction_ids'])
            or receipt['endpoint']['host'] != context['configuration']['waapi_host']
            or receipt['endpoint']['port'] != context['configuration']['waapi_port']
            or receipt['config_sha256'] != observations['config']['sha256']):
        raise ValueError('Original Source proof/context/public configuration differs')
    for phase in receipt['phases']:
        row = transactions[phase['transaction_id']]
        if (row['artifact_hash'] != phase['authority_receipt']['artifact_hash']
                or row['state'] != ('verified' if phase['name'] in {'create_empty_destination', 'copy_source_only'} else 'result_schema_checked')):
            raise ValueError('Original Source four-transaction category binding differs')


def portable_source_native_attachments(descriptors, bindings, read, base, *, capture_origins=None, origin_descriptors=None):
    """Attach only reviewed Source native records to existing program bindings."""
    from copy import deepcopy
    from tests.support.source_copy_branch_evidence import source_facts, native_route, pointer_contract, PUBLIC_NODES
    if not isinstance(descriptors, list): raise ValueError('Closed Source native attachment list required')
    attached = set()
    for descriptor in descriptors:
        attachment = read(descriptor)
        fields = {'contract', 'branch_ids', 'business_fact_id', 'proof', 'evidence', 'equivalence', 'native_equivalence'}
        accounting = attachment.get('contract') == 'waapi-skill.source-copy-native-attachment/v3'
        successor = accounting or attachment.get('contract') == 'waapi-skill.source-copy-native-attachment/v2'
        if successor:
            fields |= {'predecessor', 'successor_context'}
        if accounting:
            fields.add('program_equivalence')
        if set(attachment) != fields or attachment['contract'] not in {
                'waapi-skill.source-copy-native-attachment/v1', 'waapi-skill.source-copy-native-attachment/v2',
                'waapi-skill.source-copy-native-attachment/v3'}:
            raise ValueError('Closed Source native attachment required')
        if successor:
            successor_context, predecessor = validate_successor_context(attachment['successor_context'], base)
            if (accounting != ('accounting_origin' in successor_context)
                    or successor_context['predecessor'] != attachment['predecessor']
                    or any(attachment[name] != predecessor[name]
                           for name in ('branch_ids', 'business_fact_id', 'proof', 'evidence'))):
                raise ValueError('Source successor changed original native attribution')
        facts = source_facts(read(attachment['proof']), base)
        ids = attachment['branch_ids']
        expected = {native_route(facts['version']) + '|' + pointer for pointer in pointer_contract(facts['version'])}
        if (not isinstance(ids, list) or len(ids) != len(set(ids)) or set(ids) != expected
                or attachment['business_fact_id'] != facts['business_fact_id']
                or set(attachment['equivalence']) != expected or set(attachment['native_equivalence']) != expected
                or accounting and set(attachment['program_equivalence']) != expected):
            raise ValueError('Source native exact leaf or scoped business set differs')
        for identity in ids:
            if identity in attached or identity not in bindings: raise ValueError('Conflicting Source native attachment')
            attached.add(identity)
            binding = bindings[identity]
            program = completion.read_sealed_artifact(binding['evidence']['program'], base)
            if successor:
                captured_candidate = successor_context.get('captured_candidate_sha256', successor_context['current_candidate_sha256'])
                if (program.get('candidate_sha256') != captured_candidate
                        or program.get('relevant_sources') != successor_context['current_sources']
                        or program.get('invocation', {}).get('outcome') != 'PASS'):
                    raise ValueError('Source successor requires its current complete product program')
                # The generic importer already read this sealed origin receipt.
                # Only v2 reuse requires the complete Source product finalizer.
                capture = (capture_origins or {}).get(identity)
                origin = successor_context.get('accounting_origin')
                if origin is not None:
                    if (origin_descriptors or {}).get(identity) != origin:
                        raise ValueError('Source accounting changed retained origin descriptors')
                    if ({key: binding['evidence']['program'][key] for key in ('artifact', 'sha256')} != origin['program']
                            or any(attachment[name] != successor_context['accounting_attachment'][name]
                                   for name in ('branch_ids', 'business_fact_id', 'proof', 'evidence', 'predecessor'))):
                        raise ValueError('Source accounting changed retained program/capture/native descriptors')
                node = PUBLIC_NODES[facts['version']]
                if (not isinstance(capture, dict)
                        or set(capture) != {'contract', 'candidate_sha256', 'git_candidate', 'native_credit',
                            'outcome', 'phase_reports', 'scope_kind', 'source_unchanged'}
                        or capture['contract'] != 'waapi-skill.source-copy-program-capture/v1'
                        or capture['candidate_sha256'] != program['candidate_sha256']
                        or capture['git_candidate'] != program.get('git_candidate')
                        or capture['native_credit'] is not False
                        or capture['outcome'] != 'PASS' or capture['scope_kind'] != 'product'
                        or capture['source_unchanged'] is not True
                        or capture['phase_reports'] != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
                        or program.get('invocation') != {'phase': 'final', 'outcome': 'PASS',
                            'node_outcomes': [{'nodeid': node, 'outcome': 'PASS'}]}):
                    raise ValueError('Source successor requires complete successful capture phases')
                binding['source_copy_successor_context'] = deepcopy(attachment['successor_context'])
                if accounting:
                    binding['source_copy_program_equivalence'] = deepcopy(attachment['program_equivalence'][identity])
            if (set(binding['evidence']) != {'program'} or program.get('scope_kind') != 'product'
                    or binding.get('source_business_fact') != facts['business_fact_id']
                    or binding.get('dispatch_pointer') != '/observations/source/native_call'
                    or binding.get('observation_pointer') != '/observations/source' + pointer_contract(facts['version'])[identity.rsplit('|', 1)[1]][0]):
                raise ValueError('Source native attachment needs its current exact product program binding')
            binding.update(source_copy_native_proof=deepcopy(attachment['proof']),
                equivalence=deepcopy(attachment['equivalence'][identity]),
                native_equivalence=deepcopy(attachment['native_equivalence'][identity]))
            native = read({key: attachment['evidence'][key] for key in ('artifact', 'sha256')})
            binding['native_observations_sha256'] = {key: value['sha256'] for key, value in native['observation_artifacts'].items()}
            binding['evidence']['native'] = deepcopy(attachment['evidence'])
            # Early ownership check also prevents locator-only projections from
            # admitting a caller-created wrapper before evidence_result runs.
            loaded = deepcopy(native)
            loaded['observations'] = {key: completion.read_sealed_artifact(value, base)
                                      for key, value in native['observation_artifacts'].items()}
            validate_source_native(loaded, binding, {'id': identity}, base)


def write_source_dependency_review(output):
    """Use the native producer's fixed portable descriptor and exact review bytes."""
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.source_copy_branch_evidence import fixture, REVIEW_PATH, REVIEW_SHA256
    raw = fixture.read_file(audit.ROOT / REVIEW_PATH)
    if fixture.sha(raw) != REVIEW_SHA256: raise ValueError('Reviewed Source bridge changed')
    (Path(output) / 'dependency-review.json').write_bytes(raw)
    return {'artifact': 'native/dependency-review.json', 'sha256': REVIEW_SHA256}


def attach_original_source_native(program_index, *, category, receipt_path, config_path, inventory):
    """Produce one portable original wrapper; never launch or replay native work."""
    from copy import deepcopy
    import json
    import tempfile
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.media_id_branch_evidence import _original_source_context
    from tests.support.source_copy_branch_evidence import (
        export_source_proof, source_facts, write_json, fixture, REVIEW_PATH, REVIEW_SHA256, relevant_sources)
    receipt_raw = fixture.read_file(Path(receipt_path))
    receipt_link = {'path': str(Path(receipt_path).resolve()), 'sha256': fixture.sha(receipt_raw)}
    config_link = {'artifact': str(Path(config_path).resolve()), 'sha256': fixture.sha(fixture.read_file(Path(config_path)))}
    # Fail before publishing any wrapper for an unowned or substituted run.
    read_source_native_run(category, receipt_link, config_link, Path(program_index).parent)
    program_index = Path(program_index); base = program_index.parent
    requirements = json.loads((base / 'requirements.json').read_bytes())
    document, _, _ = audit.portable_binding_inputs(program_index, requirements)
    if len(document['bindings']) not in {4, 6}: raise ValueError('Select one exact Source version program')
    output = base / 'native'
    output.mkdir(exist_ok=False)
    def copied(name, path):
        raw = fixture.read_file(Path(path), maximum=16 * 1024 * 1024)
        (output / name).write_bytes(raw)
        return {'artifact': 'native/' + name, 'sha256': fixture.sha(raw)}
    raw_category = copied('category.jsonl', category['artifact'])
    native_category = {**raw_category, 'record_index': category['record_index'], 'nodeid': category['nodeid']}
    config = copied('config.json', config_path)
    export_source_proof(output / 'proof', Path(receipt_path).resolve())
    proof_path = output / 'proof/proof.json'
    proof = json.loads(proof_path.read_bytes())
    for item in proof['files'].values(): item['artifact'] = 'native/proof/' + item['artifact']
    proof_descriptor = write_json(proof_path, proof); proof_descriptor['artifact'] = 'native/proof/proof.json'
    context = read_source_native_run(native_category, proof['receipt'], config, base)
    facts = source_facts(proof, base)
    ids = list(document['bindings'])
    if {identity.split('|', 1)[0] for identity in ids} != {facts['version']}:
        raise ValueError('Source program/native version differs')
    observed = {'source': {**write_json(output / 'facts.json', facts), 'artifact': 'native/facts.json'},
                'category': native_category, 'config': config}
    sources = native_source_maps(context['candidate'])
    # Only immutable Git source bytes are used to compute historical audit
    # identity. This temporary source view grants no execution or native credit.
    with tempfile.TemporaryDirectory(prefix='source-audit-identity-') as temporary:
        original_candidate, _ = _original_source_context(Path(temporary) / 'source',
            context['candidate'], inventory, list(sources))
    current_candidate = inventory['native_coverage']['candidate_sha256']
    original_context = {'original_git_candidate': context['candidate'], 'original_candidate_sha256': original_candidate,
        'current_candidate_sha256': current_candidate, 'original_sources': sources,
        'current_sources': relevant_sources(),
        'native_catalogs': inventory['native_coverage']['catalogs']}
    source_context = {**write_json(output / 'source-context.json', original_context), 'artifact': 'native/source-context.json'}
    record = {'candidate_sha256': original_candidate, 'git_candidate': context['candidate'],
        'scope_kind': 'product', 'evidence_kind': 'native_execution', 'relevant_sources': sources,
        'source_copy_proof': proof_descriptor, 'source_context': source_context, 'invocation': context['record']['invocation'],
        'native_runs': [{**native_category, 'observation_sha256': sorted({item['sha256'] for item in observed.values()})}],
        'observation_artifacts': observed, 'branch_assertions': {}}
    for identity, binding in document['bindings'].items():
        pointer = binding['observation_pointer']
        branch = next(row for row in inventory['native_coverage']['obligations'] if row['id'] == identity)
        record['branch_assertions'][identity] = {'native_shape_sha256': branch['shape_sha256'],
            'native_route': branch['route'], 'checks': [{'pointer': pointer,
                'equals': completion.pointer_value({'observations': {'source': facts}}, pointer)}]}
    evidence = {**write_json(output / 'native.json', record), 'artifact': 'native/native.json', 'nodeid': native_category['nodeid']}
    review = write_source_dependency_review(output)
    attachment = {'contract': 'waapi-skill.source-copy-native-attachment/v1', 'branch_ids': ids,
        'business_fact_id': facts['business_fact_id'], 'proof': proof_descriptor, 'evidence': evidence,
        'equivalence': {}, 'native_equivalence': {}}
    for ordinal, (identity, binding) in enumerate(document['bindings'].items()):
        binding.update(source_copy_native_proof=proof_descriptor,
            native_observations_sha256={key: item['sha256'] for key, item in observed.items()})
        branch = next(row for row in inventory['native_coverage']['obligations'] if row['id'] == identity)
        for kind, origin, digest in [('equivalence', original_candidate, evidence['sha256']),
                                     ('native_equivalence', context['candidate'], native_category['sha256'])]:
            proof_record = {'contract': 'waapi-skill.branch-evidence-equivalence/v1', 'from_candidate': origin,
                'to_candidate': current_candidate, 'branch_id': identity, 'native_shape_sha256': branch['shape_sha256'],
                'native_route': branch['route'], 'evidence_sha256': digest,
                'binding_semantics_sha256': audit.digest(completion.binding_semantics(binding)), 'sources': sources,
                'reviewed_reason': 'Exact original Source/Synth selected leaves plus scoped #180 graph; raw diagnostic flags unchanged; no history credit.'}
            proof_record.update(source_native_candidate=context['candidate'], source_copy_review=review)
            name = kind + '-' + str(ordinal) + '.json'
            attachment[kind][identity] = {**write_json(output / name, proof_record), 'artifact': 'native/' + name}
    attachment_descriptor = {**write_json(output / 'attachment.json', attachment), 'artifact': 'native/attachment.json'}
    index = json.loads(program_index.read_bytes())
    if index.get('source_native_attachments'): raise ValueError('Never replace an earlier Source native attachment')
    index['source_native_attachments'] = [attachment_descriptor]
    temporary_index = base / '.source-native-index.json'
    write_json(temporary_index, index)
    merged, _, _ = audit.portable_binding_inputs(temporary_index, requirements)
    for identity, binding in merged['bindings'].items():
        branch = next(row for row in inventory['native_coverage']['obligations'] if row['id'] == identity)
        result = completion.evidence_result(binding['evidence']['native'], branch, current_candidate, 'native',
            'product', base, binding, source_root=audit.ROOT)
        if result != ('passed', None): raise ValueError('Source original native reader rejected attachment: ' + str(result))
    temporary_index.replace(program_index)
    return attachment_descriptor


def publish_source_native_successor(program_index, *, predecessor, inventory, product_base, destination, accounting=False):
    """Transport a new program bundle; reference original native bytes in place."""
    from copy import deepcopy
    import hashlib
    import json
    import os
    import shutil
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.source_copy_branch_evidence import write_json
    product_base = Path(product_base).resolve(strict=True)
    program_index = Path(program_index).resolve(strict=True)
    destination = Path(destination)
    if (destination.exists() or not destination.resolve().is_relative_to(product_base)
            or any(parent.is_symlink() for parent in destination.parents)):
        raise ValueError('Source successor needs a new owned product destination')
    if accounting:
        return _publish_source_accounting_successor(program_index, predecessor, inventory, product_base, destination)
    requirements = json.loads((program_index.parent / 'requirements.json').read_bytes())
    program_bindings, _, _ = audit.portable_binding_inputs(program_index, requirements)
    candidate = inventory['native_coverage']['candidate_sha256']
    branches = {row['id']: row for row in inventory['native_coverage']['obligations']}
    references = {key: row for key, row in branches.items() if row['kind'] == 'reference'}
    for identity, binding in program_bindings['bindings'].items():
        result = completion.evidence_result(binding['evidence']['program'], branches[identity],
            candidate, 'program', 'product', program_index.parent, binding,
            source_root=audit.ROOT, reference_edges=references)
        if result != ('passed', None):
            raise ValueError('Current Source program cannot authorize successor: ' + str(result))
    reviewed = successor_dependency_review()
    if predecessor not in reviewed['predecessor_attachments']:
        raise ValueError('Source successor original predecessor differs')
    original_native = _portable_source_document(predecessor, product_base)
    if set(program_bindings['bindings']) != set(original_native['branch_ids']):
        raise ValueError('Source successor current and original version/branches differ')
    destination.mkdir(parents=True, exist_ok=False)
    original = destination / 'original'
    # These are newly captured injected-client program artifacts, not a native
    # archive. Every preserved v1 native descriptor remains unchanged.
    shutil.copytree(program_index.parent, original)
    portable = destination / 'portable'; portable.mkdir()
    def original_descriptor(name):
        path = original / name
        return {'artifact': path.relative_to(product_base).as_posix(),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    def emit(name, value):
        path = portable / name
        return {**write_json(path, value), 'artifact': path.relative_to(product_base).as_posix()}
    projected = json.loads((original / 'bindings.json').read_bytes())
    for binding in projected['bindings'].values():
        binding['evidence']['program']['artifact'] = original_descriptor('program.json')['artifact']
    projection = emit('bindings.json', projected)
    proof = json.loads((original / 'proof.json').read_bytes())
    for descriptor in proof['files'].values():
        descriptor['artifact'] = (original / descriptor['artifact']).relative_to(product_base).as_posix()
    program_attachment = json.loads((original / 'attachment.json').read_bytes())
    program_attachment['proof'] = emit('program-proof.json', proof)
    program_attachment_descriptor = emit('program-attachment.json', program_attachment)
    raw_review = (audit.ROOT / SUCCESSOR_REVIEW_PATH).read_bytes()
    review_path = portable / 'successor-review.json'; review_path.write_bytes(raw_review)
    review_descriptor = {'artifact': review_path.relative_to(product_base).as_posix(),
                         'sha256': hashlib.sha256(raw_review).hexdigest()}
    native_record = completion.read_sealed_artifact(original_native['evidence'], product_base)
    context_descriptor = emit('successor-context.json', {
        'contract': 'waapi-skill.source-copy-successor-context/v1',
        'review': review_descriptor, 'predecessor': predecessor,
        'original_source_context': native_record['source_context'],
        'current_candidate_sha256': candidate, 'current_sources': reviewed['current_sources']})
    successor = {**deepcopy(original_native), 'contract': 'waapi-skill.source-copy-native-attachment/v2',
        'predecessor': predecessor, 'successor_context': context_descriptor,
        'equivalence': {}, 'native_equivalence': {}}
    for ordinal, (identity, binding) in enumerate(projected['bindings'].items()):
        binding = deepcopy(binding)
        binding.update(source_copy_proof=program_attachment['proof'],
            source_business_fact=program_attachment['business_fact_id'],
            source_copy_native_proof=original_native['proof'], source_copy_successor_context=context_descriptor,
            native_observations_sha256={key: value['sha256']
                for key, value in native_record['observation_artifacts'].items()})
        for kind in ('equivalence', 'native_equivalence'):
            equivalence = completion.read_sealed_artifact(original_native[kind][identity], product_base)
            equivalence = {**equivalence, 'to_candidate': candidate,
                'binding_semantics_sha256': audit.digest(completion.binding_semantics(binding)),
                'source_copy_successor_context': context_descriptor}
            successor[kind][identity] = emit(kind + '-' + str(ordinal) + '.json', equivalence)
    native_descriptor = emit('native-successor.json', successor)
    entry = {'id': destination.name, 'bindings': projection,
        'origin': {key: original_descriptor(name) for key, name in {
            'bindings': 'bindings.json', 'program': 'program.json',
            'requirements': 'requirements.json', 'capture': 'capture.json'}.items()}}
    index = {'contract': 'waapi-skill.branch-evidence-index/v1',
        'base': os.path.relpath(product_base, portable), 'entries': [entry],
        'source_attachments': [program_attachment_descriptor],
        'source_native_attachments': [native_descriptor]}
    index_path = portable / 'index.json'; write_json(index_path, index)
    imported, _, _ = audit.portable_binding_inputs(index_path, requirements)
    for identity, binding in imported['bindings'].items():
        for category in ('program', 'native'):
            result = completion.evidence_result(binding['evidence'][category], branches[identity], candidate,
                category, 'product', product_base, binding, source_root=audit.ROOT, reference_edges=references)
            if result != ('passed', None):
                raise ValueError('Source successor reader rejected published evidence: ' + str(result))
    return index_path


def _publish_source_accounting_successor(program_index, predecessor, inventory, product_base, destination):
    """Write only reviewed admission sidecars; never copy or restamp captured facts."""
    from copy import deepcopy
    import hashlib
    import os
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.source_copy_branch_evidence import write_json
    review = accounting_dependency_review()
    previous_index = {'artifact': program_index.relative_to(product_base).as_posix(),
                      'sha256': hashlib.sha256(program_index.read_bytes()).hexdigest()}
    if previous_index not in review['packets']:
        raise ValueError('Source accounting requires its exact reviewed packet')
    old_index = _portable_source_document(previous_index, product_base)
    old_native = _portable_source_document(old_index['source_native_attachments'][0], product_base)
    if predecessor != old_native['predecessor']:
        raise ValueError('Source accounting original predecessor differs')
    requirements = _portable_source_document(old_index['entries'][0]['origin']['requirements'], product_base)
    candidate = inventory['native_coverage']['candidate_sha256']
    branches = {row['id']: row for row in inventory['native_coverage']['obligations']}
    portable = destination / 'portable'
    portable.mkdir(parents=True, exist_ok=False)
    def emit(name, value):
        path = portable / name
        return {**write_json(path, value), 'artifact': path.relative_to(product_base).as_posix()}
    review_descriptor = emit('accounting-review.json', review)
    if review_descriptor['sha256'] != ACCOUNTING_REVIEW_SHA256:
        raise ValueError('Source accounting review transport changed bytes')
    context_descriptor = emit('accounting-context.json', {
        'contract': 'waapi-skill.source-copy-successor-context/v2',
        'review': review_descriptor, 'previous_index': previous_index,
        'current_candidate_sha256': candidate})
    # Validate the qualified historical packet before transporting its native
    # metadata. Import its ordinary program projection without asking the
    # unrelated direct-current v2 path to certify historical execution bytes.
    validate_successor_context(context_descriptor, product_base, candidate=candidate)
    bootstrap = {**deepcopy(old_index), 'base': os.path.relpath(product_base, portable)}
    bootstrap.pop('source_native_attachments')
    bootstrap_path = portable / 'retained-program-index.json'
    write_json(bootstrap_path, bootstrap)
    old_bindings, base, _ = audit.portable_binding_inputs(bootstrap_path, requirements)
    if base != product_base:
        raise ValueError('Source accounting original product boundary differs')
    native_record = _portable_source_document({key: old_native['evidence'][key] for key in ('artifact', 'sha256')}, product_base)
    successor = {**deepcopy(old_native), 'contract': 'waapi-skill.source-copy-native-attachment/v3',
        'successor_context': context_descriptor, 'equivalence': {}, 'native_equivalence': {}, 'program_equivalence': {}}
    for ordinal, (identity, old_binding) in enumerate(old_bindings['bindings'].items()):
        binding = deepcopy(old_binding)
        binding.update(source_copy_successor_context=context_descriptor,
            source_copy_native_proof=deepcopy(old_native['proof']),
            equivalence=deepcopy(old_native['equivalence'][identity]),
            native_equivalence=deepcopy(old_native['native_equivalence'][identity]),
            native_observations_sha256={key: value['sha256'] for key, value in native_record['observation_artifacts'].items()})
        semantics = audit.digest(completion.binding_semantics(binding))
        program = _portable_source_document({key: binding['evidence']['program'][key]
                                            for key in ('artifact', 'sha256')}, product_base)
        branch = branches[identity]
        successor['program_equivalence'][identity] = emit('program-equivalence-' + str(ordinal) + '.json', {
            'contract': 'waapi-skill.branch-evidence-equivalence/v1',
            'from_candidate': program['candidate_sha256'], 'to_candidate': candidate,
            'branch_id': identity, 'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
            'evidence_sha256': binding['evidence']['program']['sha256'], 'binding_semantics_sha256': semantics,
            'sources': program['relevant_sources'],
            'reviewed_reason': 'Retained 88a6 program; original execution sources stay historical, with an exact separately reviewed current execution/accounting transition.'})
        for kind in ('equivalence', 'native_equivalence'):
            proof = _portable_source_document(old_native[kind][identity], product_base)
            successor[kind][identity] = emit(kind + '-' + str(ordinal) + '.json', {
                **proof, 'to_candidate': candidate, 'binding_semantics_sha256': semantics,
                'source_copy_successor_context': context_descriptor})
    native_descriptor = emit('native-successor.json', successor)
    index = {**deepcopy(old_index), 'base': os.path.relpath(product_base, portable),
             'source_native_attachments': [native_descriptor]}
    index['entries'][0]['id'] = destination.name
    index_path = portable / 'index.json'
    write_json(index_path, index)
    imported, _, _ = audit.portable_binding_inputs(index_path, requirements)
    references = {key: row for key, row in branches.items() if row['kind'] == 'reference'}
    for identity, binding in imported['bindings'].items():
        for category in ('program', 'native'):
            result = completion.evidence_result(binding['evidence'][category], branches[identity], candidate,
                category, 'product', product_base, binding, source_root=audit.ROOT, reference_edges=references)
            if result != ('passed', None):
                raise ValueError('Source accounting reader rejected published evidence: ' + str(result))
    return index_path
