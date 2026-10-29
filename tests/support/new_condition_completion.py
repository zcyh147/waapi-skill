"""New-mode correspondence for the existing installed-condition reader.

Source grammar is reused verbatim. A public mechanism proves only its selected
recipient; every other constructor/owned/plugin applicability remains assigned.
"""
from copy import deepcopy
from functools import lru_cache
import gzip
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from tests.maintenance.branch_coverage_audit import digest, load
from tests.maintenance.branch_audit_completion import installed_obligations

PROOF_PATH = 'tests/fixtures/metadata-conditions/new-condition-current-program-r3.json.gz'
ORIGINAL_PROOF = {'path': 'tests/fixtures/metadata-conditions/new-condition-current-program.json.gz',
    'sha256': 'f19e45ba8e04a97d5ce8fdfb9f97d2e3567e75f11547d7baf5869149a9aa65cd'}
PREVIOUS_PROOF = {'path': 'tests/fixtures/metadata-conditions/new-condition-current-program-r2.json.gz',
    'sha256': '23f291cd2417075ef624866fafbd3edfccfd33476c2a005f2535e45688fba2d8'}
MEDIA_POOL_PRIMARY_SOURCE = ('skills/waapi-skill/references/semantic/2025.1/media-pool-database-sources/'
    'ak_wwise_core_object_set_example_creating_a_media_pool_database.html')
VERSIONS = ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')
LIB = 'skills/waapi-skill/wwise_waapi/'


def program_sources(root):
    """Seal the actual runtime and selected transitive public-fixture helpers."""
    import ast
    selected = {p.relative_to(root).as_posix() for directory in ('scripts', 'wwise_waapi')
        for p in (root / 'skills/waapi-skill' / directory).rglob('*.py') if '__pycache__' not in p.parts}
    selected.update({'tests/support/new_condition_completion.py',
        'tests/support/platform_filesystem.py', ORIGINAL_PROOF['path'], PREVIOUS_PROOF['path'],
        MEDIA_POOL_PRIMARY_SOURCE,
        'tests/support/condition_source_resolution.py', 'tests/support/condition_scalar_batch.py',
        'tests/support/condition_mechanism_reuse.py', 'tests/support/exact_evidence_finalization.py',
        'docs/branch-coverage-condition-sources.json',
        'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz',
        *['skills/waapi-skill/resources/metadata/' + v + '/' + name + '.json'
          for v in VERSIONS for name in ('object-types', 'documented-list-fields')],
        'skills/waapi-skill/resources/metadata/2025.1/override-applicability.json',
        'skills/waapi-skill/resources/metadata/reference-master-bus-applicability.json',
        'skills/waapi-skill/resources/metadata/reference-master-sink-capabilities.json'})
    pending = ['tests/unit/test_new_condition_completion_reader.py']
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        selected.add(name)
        tree = ast.parse((root / name).read_bytes())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('tests.unit.'):
                dependency = node.module.replace('.', '/') + '.py'
                if (root / dependency).is_file():
                    pending.append(dependency)
    sources = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(selected)}
    # Seal the reused parser and boundary functions, excluding this proof's own
    # digest constant. The original existing-object review stays immutable.
    path = 'tests/support/condition_completion_mapping.py'
    text = (root / path).read_text(encoding='utf-8')
    lines = text.splitlines(keepends=True)
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name in {'definition_mapping',
                '_map_fieldless_structure', '_map_batch_exclusions', '_map_music_limit'}:
            sources[path + '#' + node.name] = hashlib.sha256(''.join(lines[node.lineno - 1:node.end_lineno]).encode()).hexdigest()
    return sources


def _correspondence(row):
    tag = row['source_xml'].split('<', 1)[1].split()[0]
    context = row['source_attributes'].get('Context', 'Self')
    if context == 'AssocParent':
        path = 'switch_assignment_owned_configuration'
        operations = ['switchContainer.addAssignment', 'object.setProperty']
        note = 'ObjectSettingAssoc uses exact Switch owner/child context binding; new-context constructor applicability stays in the independent target obligations.'
    elif tag == 'IsMasterBusDependency' and row['source_attributes'].get('Value') == 'True':
        path = 'verified_object_scoped_master_reference_configuration'
        operations = ['object.setReference', 'object.set']
        note = 'Master-only visibility needs a verified identity and fresh object-scoped reference_applicability.prove ancestry/class proof; no prospective master-bus class-default proof exists. Constructor applicability remains separately assigned.'
    elif tag == 'IsMasterBusDependency' and row['source_attributes'].get('Value') == 'False':
        path = 'class_default_with_structural_bus_proof'
        operations = ['object.create', 'object.set']
        note = 'Gateway proves non-Bus class or child Bus/AuxBus placement; never infer master status from source alone.'
    else:
        path = 'class_defaults_or_verified_created_configuration'
        operations = ['object.create', *([] if row['version'] == '2021.1' else ['object.set', 'object.createPlugin']),
            'object.setProperty', 'object.setReference']
        note = 'Class-scoped Field Handles may supply defaults/explicit prerequisites at creation; otherwise a verified created identity must have an available exact object-scoped configuration path.'
    return {'path': path, 'entrypoint': 'skills/waapi-skill/scripts/run.py gateway.py',
        'operations': operations, 'new_fields': 'draft-discover-fields --type-handle; draft-declare-new --field-value',
        'configuration_binding': ('draft-bind-switch-child-context --owner-handle OWNER --child-handle VERIFIED_CHILD'
            if context == 'AssocParent' else 'draft-bind-object --verified-created-from CREATION_TRANSACTION'),
        'configuration_fields': 'draft-discover-fields --object-handle; draft-declare-field-change',
        **({'predicate': {'kind': 'isMasterBus', 'value': row['source_attributes']['Value'] == 'True'}}
            if tag == 'IsMasterBusDependency' else {}),
        'constructor': (None if path == 'verified_object_scoped_master_reference_configuration'
            else LIB + 'new_object_defaults.py#class_default_evidence'),
        **({'applicability_proof': LIB + 'reference_applicability.py#prove',
            'condition_validation': LIB + 'operation_registry.py#_apply_reference_activation_dependencies'}
            if path == 'verified_object_scoped_master_reference_configuration' else {}),
        'identity_binding': LIB + 'business_declarations.py#_dependent_new_object_workflow',
        'verification': LIB + 'operation_registry.py#verify_prepared_operation',
        'applicability': note, 'native_effect': 'not_claimed'}


def definition_mapping(root):
    from tests.support.condition_completion_mapping import definition_mapping as existing_mapping
    mapping = deepcopy(existing_mapping(root))
    branches = {b['id']: b for b in installed_obligations(root, digest=digest, load=load)
        if b['owner_issue'] == 178 and b['kind'] == 'metadata_condition'}
    applicability = [b for b in installed_obligations(root, digest=digest, load=load)
        if b['kind'] in {'target_applicability', 'plugin_topology'}]
    for row in mapping['occurrences']:
        xml = ET.fromstring(row['source_xml'])
        row['source_form'] = '|'.join((xml.tag, row['source_attributes'].get('Action', 'Enable'),
            row['source_attributes'].get('Context', 'Self'), ','.join(sorted({n.tag for n in xml.iter() if n is not xml}))))
        consumers = [c['catalog'] for c in row['consumers']]
        row['applicability_obligations'] = [{'id': b['id'], 'shape_sha256': b['shape_sha256']}
            for b in applicability if b['version'] == row['version'] and (
                b['kind'] == 'target_applicability' and b['business_dimensions']['class_id'] in {c['classId'] for c in consumers}
                or b['kind'] == 'plugin_topology' and b['business_dimensions']['class_name'] in {c['name'] for c in consumers})]
        targets = {b['business_dimensions']['class_id'] for b in applicability
            if b['version'] == row['version'] and b['kind'] == 'target_applicability'
            and b['id'] in {r['id'] for r in row['applicability_obligations']}}
        if targets != {c['classId'] for c in consumers}:
            raise ValueError('Every source consumer needs exact independent target applicability obligations')
        row['source_existing_occurrence_id'] = row['occurrence_id']
        row['occurrence_id'] = row['occurrence_id'].replace('|existing-object|', '|new-object|')
        row['operation_mode'] = 'new-object'
        for member in row['members']:
            member['id'] = member['id'].replace('|existing-object|', '|new-object|')
        row['construction_correspondence'] = _correspondence(row)
        row['condition_mechanism'] = row['source_form'] + (
            '|Value=' + xml.attrib['Value'] if xml.tag == 'IsMasterBusDependency' else '')
        row['constructor_applicability'] = 'unresolved; source grammar is not constructor admission'
        if 'approved_exclusion' in row or 'source_structure' in row:
            continue
        # Construction/placement applicability is a different independent
        # denominator. Sharing grammar is neither per-recipient execution nor
        # permission to remove those target/plugin obligations.
        row['representative_public_mechanism'] = row['condition_mechanism']
        row['dependencies'] = []
    pairs = [(m['id'], m['shape_sha256']) for r in mapping['occurrences'] for m in r['members']]
    if len(pairs) != len(branches) or dict(pairs) != {i: b['shape_sha256'] for i, b in branches.items()}:
        raise ValueError('Exact new-object installed condition ID/shape roster differs')
    mapping.update(owner_issue=178, operation_mode='new-object', members_sha256=digest(sorted(pairs)),
        source_forms=sorted({r['source_form'] for r in mapping['occurrences']}),
        condition_mechanisms=sorted({r['condition_mechanism'] for r in mapping['occurrences']}))
    return mapping


def review(root):
    from tests.support.condition_completion_mapping import (
        NEW_OBJECT_PROOF_SHA256 as PROOF_SHA256, _fieldless_review,
        _batch_exclusion_review, _music_limit_review)
    _fieldless_review(root)
    _batch_exclusion_review(root)
    _music_limit_review(root)
    for predecessor in (ORIGINAL_PROOF, PREVIOUS_PROOF):
        if hashlib.sha256((root / predecessor['path']).read_bytes()).hexdigest() != predecessor['sha256']:
            raise ValueError('Historical new-object public program proof changed')
    raw = (root / PROOF_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROOF_SHA256:
        raise ValueError('Exact new-object public program proof differs')
    proof = json.loads(gzip.decompress(raw))
    if (proof.get('contract') != 'waapi-skill.new-condition-current-public-mechanism/v1'
            or proof.get('evidence_kind') != 'injected_client_program' or proof.get('scope_kind') != 'product'
            or proof.get('reports') != {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}
            or proof.get('direct_recipient_native_effect') != 'not_observed'
            or proof.get('sources') != program_sources(root)
            or proof.get('predecessor') != PREVIOUS_PROOF
            or set(proof.get('observations', {})) != set(VERSIONS)):
        raise ValueError('Exact new-object public program scope/source closure differs')
    resources = proof.get('selected_resources')
    if not isinstance(resources, dict) or not resources or len(resources) > 1024:
        raise ValueError('Bounded selected resource read closure required')
    for name, sha in resources.items():
        if (not name.startswith('skills/waapi-skill/resources/') or '..' in Path(name).parts
                or hashlib.sha256((root / name).read_bytes()).hexdigest() != sha):
            raise ValueError('Selected resource source closure differs: ' + name)
    for version, flow in proof['observations'].items():
        if (flow['class'] != {'name': 'ModulatorTime', 'classId': 5111824}
                or flow['missing_default'] != {'exit_code': 2, 'mutation_dispatched': False}
                or any(flow.get(k) is not True for k in ('preserved_existing', 'creation_verified', 'configuration_verified', 'distinct_transactions'))
                or len(flow['writes']) != 2
                or flow['writes'][0]['uri'] != 'ak.wwise.core.object.create'
                or flow['writes'][0]['args'].get('@TimeModLoops') != 5
                or flow['writes'][0]['args'].get('@EnvelopeStopPlayback') is not False
                or flow['writes'][1]['uri'] != 'ak.wwise.core.object.setProperty'
                or flow['writes'][1]['args'].get('property') != 'EnvelopeStopPlayback'
                or flow['writes'][1]['args'].get('value') is not True
                or flow['created'].get('EnvelopeStopPlayback') is not True
                or flow['created'].get('TimeModLoops') != 5):
            raise ValueError('Exact new-object public creation/configuration flow differs: ' + version)
    required = {
        'IsMasterBusDependency|Enable|Self||Value=False',
        'IsMasterBusDependency|Enable|Self||Value=True', 'OverrideDependency|Enable|Self|',
        'PropertyDependency|Enable|AssocParent|Condition,Enumeration,Value',
        'PropertyDependency|Enable|Self|Condition,Enumeration,Value',
        'PropertyDependency|Enable|Self|Condition,Max,Min,Range',
        'PropertyDependency|Show|Parent|Condition,Enumeration,Value',
        'PropertyDependency|Show|Self|Condition,Enumeration,Value',
        'PropertyDependency|Show|Self|Condition,Max,Min,Range',
        'ReferenceDependency|Enable|Self|Condition,ReferenceIsSet'}
    if (set(proof.get('mechanism_observations', {})) != required
            or any(flow.get('verified') is not True or flow.get('native_effect') != 'not_observed'
                   for flow in proof['mechanism_observations'].values())):
        raise ValueError('Each exact source mechanism, including master predicate polarity, needs its shared public proof')
    master = proof['mechanism_observations']['IsMasterBusDependency|Enable|Self||Value=True']
    if (master.get('public_operation') != 'object.setReference'
            or master.get('predicate') != {'kind': 'isMasterBus', 'value': True}
            or set(master.get('versions', [])) != {'2024.1', '2025.1'}
            or master.get('proof_kind') != 'structural-reference-visibility'):
        raise ValueError('Master-only condition requires its object-scoped reference proof')
    return {'review_id': 'new-object-condition-correspondence-r3', 'operation_mode': 'new-object',
        'current_sources': {**proof['sources'], **resources}, 'predecessor': PREVIOUS_PROOF, 'program_proof': {'path': PROOF_PATH, 'sha256': PROOF_SHA256},
        'source_definition_policy': {'new_native_runs': 0}, 'recipe_public_proofs': {}}


@lru_cache(maxsize=2)
def expected(root_string):
    root = Path(root_string)
    mapping = definition_mapping(root)
    branches = {b['id']: b for b in installed_obligations(root, digest=digest, load=load)
        if b['owner_issue'] == 178 and b['kind'] == 'metadata_condition'}
    return mapping, branches


def validate_attachment(attachment, base, root, *, selected_mapping=None):
    from tests.support.condition_mechanism_reuse import _read
    current = review(root)
    if (set(attachment) != {'contract', 'operation_mode', 'review', 'mapping'}
            or attachment['contract'] != 'waapi-skill.condition-definition-attachment/v1'
            or attachment['operation_mode'] != 'new-object'
            or _read(attachment['review'], base) != current):
        raise ValueError('Closed exact new-object condition definition attachment required')
    proposed = _read(attachment['mapping'], base) if selected_mapping is None else selected_mapping
    mapping, branches = expected(str(root))
    if proposed != mapping:
        raise ValueError('The exact source definition/member/mode/constructor correspondence differs')
    return {'review': current, 'mapping': proposed, 'branches': branches, 'files': {},
        'members': {m['id']: r for r in proposed['occurrences'] for m in r['members']}}
