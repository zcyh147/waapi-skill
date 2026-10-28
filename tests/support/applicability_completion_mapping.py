"""Exact installed class/mode correspondence for the existing completion reader.

These rows investigate applicability. A selected class is not evidence of an
independent constructor, and a shared code witness is not native execution.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import base64
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from tests.maintenance.branch_coverage_audit import digest, load
from tests.maintenance.branch_audit_completion import installed_obligations

VERSIONS = ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')
PROOF_PATH = 'tests/fixtures/metadata-conditions/applicability-current-program-r4.json.gz'
PROOF_SHA256 = '4bbd106619b52f5dc916d4b64617d8286f1fe9911ab2ef62ffdd8ff888d39bcd'
PREVIOUS_PROOF = {'path': 'tests/fixtures/metadata-conditions/applicability-current-program-r3.json.gz',
    'sha256': 'c64be70da744547e538f3faccac069ce04e4d4ea7c2239c6baf43f9cb508dec7'}
SNAPSHOT = 'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz'
SDK_PATH = 'tests/fixtures/metadata-conditions/applicability-sdk-sources.json.gz'
SDK_SHA256 = '646336b2e4cb7324831d6a8b5c4be5b00417764eaf044adeccb6719ddd2a771b'
ENTRYPOINT = 'skills/waapi-skill/scripts/run.py gateway.py'
# Named hierarchy objects with ordinary public create routes. This is not the
# complete getTypes roster: embedded/tool/media classes are classified below.
HIERARCHY = frozenset(('AcousticTexture Action ActorMixer Attenuation AuxBus BlendContainer Bus '
    'Conversion DialogueEvent Event Folder GameParameter MixingSession ModulatorEnvelope '
    'ModulatorLfo ModulatorTime MusicPlaylistContainer MusicSegment MusicSwitchContainer MusicTrack '
    'PropertyContainer RandomSequenceContainer Sound SoundBank SoundcasterSession State StateGroup '
    'Switch SwitchContainer SwitchGroup Trigger').split())
PLUGIN_TYPES = {'Effect', 'Source', 'AudioDevice', 'Conversion', 'Metadata'}
PLACEMENTS = {'Effect': ['owner-local-effect', 'shareset'], 'Source': ['sound-owned-source'],
    'AudioDevice': ['shareset'], 'Metadata': ['shareset', 'owner-local-metadata'],
    'Conversion': ['conversion-settings']}


def _sources(root):
    """Preserve original installed XML, including owned list declarations."""
    snapshot = json.loads(gzip.decompress((root / SNAPSHOT).read_bytes()))
    trees = {}
    for key, value in snapshot['files'].items():
        raw = base64.b64decode(value['bytes_base64'], validate=True)
        if hashlib.sha256(raw).hexdigest() != value['sha256']:
            raise ValueError('Installed applicability original XML seal differs')
        if '|condition|' in key:
            version = '.'.join(key.split('|')[0].split('.')[:2])
            trees[version] = (key, value['sha256'], ET.fromstring(raw))
    if set(trees) != set(VERSIONS):
        raise ValueError('Installed applicability XML version missing')
    return trees


def _authority(root, heading):
    path = 'docs/plans/full-waapi-coverage/SPEC.md'
    text = (root / path).read_text(encoding='utf-8')
    marker = heading + '\n'
    if text.count(marker) != 1:
        raise ValueError('Exact installed applicability approval missing')
    section = marker + text.split(marker, 1)[1].split('\n## ', 1)[0].strip() + '\n'
    return {'path': path, 'heading': heading, 'section_sha256': hashlib.sha256(section.encode()).hexdigest(),
        'native_absence_claim': False, 'execution_credit': False}


def _plugin_correspondence(version, category, mode):
    if mode == 'existing-object':
        return 'exact_existing_object_fields', ['object.setProperty', 'object.setReference'], 'source_definition_verified', None
    if version == '2021.1' and category in {'AudioDevice', 'Metadata'}:
        return 'accepted_2021_selected_plugin_donor_free_boundary', ['object.copy'], 'approved_exclusion', None
    if category == 'Conversion':
        if version in {'2024.1', '2025.1'}:
            return 'conversion_settings_setter', ['audio.setConversionPlugin'], 'source_definition_verified', None
        return 'source_proven_2024_codec_setter_introduction', ['object.copy'], 'source_definition_verified', None
    if version == '2021.1':
        return 'source_proven_2022_selected_plugin_factory_introduction', ['object.copy'], 'source_definition_verified', None
    return 'selected_plugin_placement', ['object.createPlugin'], 'source_definition_verified', None


def sdk_sources(root):
    raw = (root / SDK_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SDK_SHA256:
        raise ValueError('Exact installed applicability SDK source archive differs')
    record = json.loads(gzip.decompress(raw))
    for source in record['sources']:
        content = base64.b64decode(source['bytes_base64'], validate=True)
        if hashlib.sha256(content).hexdigest() != source['sha256'] or any(
                fact.encode() not in content for fact in source['facts']):
            raise ValueError('Exact installed applicability primary source/member differs')
    return record


def definition_mapping(root):
    """Keep every independent ID/shape and join only source-supported paths."""
    root = Path(root)
    from wwise_waapi.documented_list_fields import field_evidence, load_catalog
    from wwise_waapi.object_graph_business_contracts import object_graph_business_contract_data
    from wwise_waapi.operation_plugin import PLUGIN_TYPE_CATEGORIES, PLUGIN_SHARESET_HIERARCHIES
    trees = _sources(root)
    sdk = sdk_sources(root)
    manifest = load(root / 'docs/branch-coverage-condition-sources.json')
    plugin_sources = defaultdict(list)
    for corpus in manifest['corpora']:
        for lane in corpus['lanes']:
            version = '.'.join(lane['build'].split('.')[:2])
            for source in lane['files']:
                for cls in source.get('classes', []):
                    plugin_sources[version, cls['Name']].append({'file': source['path'],
                        'sha256': source['sha256'], 'declaration': cls})
    rows, contracts = [], {}
    for version in VERSIONS:
        # Read the selected root rather than module-global resources, so a
        # copied/changed candidate cannot borrow the process's imported catalog.
        catalog = load_catalog(version, catalog_root=root / 'skills/waapi-skill/resources/metadata')
        from wwise_waapi.canonical import canonical_sha256
        if (catalog['version'] != version or catalog['catalog_sha256'] != canonical_sha256(
                {k: v for k, v in catalog.items() if k != 'catalog_sha256'})):
            raise ValueError('Installed applicability List source/version differs')
        contracts[version] = {op: digest(object_graph_business_contract_data(op, version))
            for op in (('object.create',) if version == '2021.1' else ('object.create', 'object.set', 'object.createPlugin'))}
        key, source_sha, tree = trees[version]
        reflected = load(root / f'skills/waapi-skill/resources/metadata/{version}/object-types.json')['types']
        source_lists = defaultdict(list)
        for owner in tree:
            for field in owner.findall('./ObjectLists/ObjectList'):
                for element in field.findall('./Restrictions/TypeEnumerationRestriction/Type'):
                    source_lists[element.attrib['Name']].append({'owner_source_kind': owner.tag,
                        'owner': owner.attrib['Name'], 'list': field.attrib['Name'], 'source': key,
                        'source_sha256': source_sha, 'declaration_xml': ET.tostring(field, encoding='unicode')})
        published_lists = defaultdict(list)
        for owner in catalog['classes']:
            for field in owner['lists']:
                source = field_evidence(catalog, owner, {'scope_kind': 'class',
                    'scope_value': owner['class_id'], 'class_id': owner['class_id']}, field)
                for element in field['element_classes']:
                    published_lists[element['class_id']].append({'owner': owner['name'], 'owner_class_id': owner['class_id'],
                        'list': field['name'], 'source_member': source['source_member'], 'source_sha256': source['source_sha256'],
                        'catalog_sha256': catalog['catalog_sha256'], 'element_class': element})
        branches = [b for b in installed_obligations(root, digest=digest, load=load)
            if b['kind'] in {'target_applicability', 'plugin_topology'} and b['version'] == version]
        for branch in branches:
            d = branch['business_dimensions']; name = d['class_name']; mode = d['operation_mode']
            row = {k: deepcopy(branch[k]) for k in ('id', 'kind', 'version', 'build', 'shape_sha256',
                'source_file_sha256', 'source_evidence_kind', 'owner_issue')}
            row.update(class_name=name, operation_mode=mode, source_dimensions=deepcopy(d),
                native_effect='not_claimed', direct_recipient_execution='not_observed',
                state='source_definition_verified', dependencies=[])
            declarations = [n for n in tree.iter() if n.tag in {'WwiseObject', 'InnerType'} and n.get('Name') == name]
            row['class_source'] = {'registered_classes': [t for t in reflected if t['name'] == name],
                'installed_xml_source': key, 'installed_xml_sha256': source_sha,
                'declarations': [ET.tostring(n, encoding='unicode') for n in declarations],
                'plugin_declarations': plugin_sources[version, name]}
            category = (next((PLUGIN_TYPE_CATEGORIES[role] for role, native in
                {'effect': 'EffectPlugin', 'source': 'SourcePlugin', 'sink': 'SinkPlugin',
                 'metadata': 'MetadataPlugin', 'conversion': 'ConversionPlugin'}.items()
                 if native == d['class'].get('kind')), None) if branch['kind'] == 'plugin_topology' else d['native_type'])
            # A WObject named Conversion/Effect/etc. is the settings/template
            # object, not an independently selected plug-in class.
            template = branch['kind'] == 'target_applicability' and category == 'WObject' and name in {'Effect', 'SourcePlugin', 'AudioDevice', 'Metadata'}
            if template:
                category = 'Source' if name == 'SourcePlugin' else name
            is_plugin = branch['kind'] == 'plugin_topology' or category in PLUGIN_TYPES
            if is_plugin:
                path, operations, state, dependency = _plugin_correspondence(version, category, mode)
                row['state'] = state
                if dependency: row['dependencies'] = [dependency]
                row['correspondence'] = {'path': path, 'operations': operations,
                    'placements': PLACEMENTS[category], 'class_source': plugin_sources[version, name],
                    'selected_kind': category, 'type_roles': PLUGIN_TYPE_CATEGORIES,
                    'shareset_hierarchies': PLUGIN_SHARESET_HIERARCHIES,
                    'admission': 'fresh selected exact live class and compatible owner/Work Unit; no catalog row proves installed availability or native effect',
                    'verification': ('invocation_result_only; independent platform-to-codec association unproved'
                        if category == 'Conversion' and mode == 'new-object' else 'exact GUID/class/owner and requested fields; existing disclosed placement strength retained')}
                if path.startswith('source_proven_'):
                    introduction = 'WG-71956' if category == 'Conversion' else 'WG-39514'
                    source, = [s for s in sdk['sources'] if any(introduction in f for f in s['facts'])]
                    row['correspondence']['version_boundary'] = {'source': SDK_PATH, 'member': source['member'],
                        'source_sha256': source['sha256'], 'fact': source['facts'][0],
                        'scope': ('named audio.setConversionPlugin setter only' if category == 'Conversion'
                            else 'class-selected Source/Effect object.set factory only'),
                        'other_paths': 'exact selected existing donor copy/configuration remains separate; no arbitrary-class donor availability or universal native impossibility inferred'}
                if state == 'approved_exclusion':
                    row['approved_exclusion'] = _authority(root, '## User-approved plugin and migration boundaries — 2026-10-27')
                    row['approved_exclusion']['scope'] = '2021.1 donor-free new selected AudioDevice/Metadata class only; donor copy and existing configuration remain separate'
                    if template:
                        # The WObject template is not an independently selected
                        # plugin class. Its role is mapped; only concrete selected
                        # donor-free factory requests receive the approved limit.
                        row['state'] = 'source_definition_verified'
                        row['correspondence']['selected_class_boundary'] = row.pop('approved_exclusion')
                if template:
                    row['correspondence']['class_role'] = 'WObject template for selected plugin kinds; independent exact-template-class construction is not claimed'
            elif name == 'BatchRenameSettings':
                row['state'] = 'approved_exclusion'
                row['approved_exclusion'] = _authority(root, '## User-approved Batch Rename window boundary — 2026-10-28')
                row['correspondence'] = {'path': 'accepted_batch_rename_window_settings_boundary', 'operations': [],
                    'admission': 'exact Inner BatchRenameSettings only; ordinary object renaming retained'}
            elif mode == 'existing-object':
                row['correspondence'] = {'path': 'exact_existing_object_fields',
                    'operations': ['object.setProperty', 'object.setReference'],
                    'admission': 'read candidates, select exact identity, bind exact GUID, discover object-scoped fields; missing identities/fields/hidden controllers remain explicit boundaries, never invented',
                    'independent_constructibility': 'not_claimed'}
            elif name in HIERARCHY:
                row['correspondence'] = {'path': 'ordinary_selected_hierarchy_constructor', 'operations': ['object.create'],
                    'admission': 'fresh Type Handle, compatible selected parent, class prerequisites, exact identity/class/parent verification; no arbitrary hierarchy placement'}
            elif published_lists.get(d.get('class_id')):
                row['correspondence'] = {'path': 'owned_list_constructor', 'operations': ['object.create', *([] if version == '2021.1' else ['object.set'])],
                    'owners': published_lists[d['class_id']],
                    'admission': 'exact existing owner and scoped List Field Handle, allowed element class, explicit constructor fields and actual owner/membership verification; no arbitrary hierarchy or nested planned-owner construction inferred'}
            elif name in {'AudioSource', 'AudioFileSource', 'MidiFileSource'}:
                row['correspondence'] = {'path': 'media_import_created_source', 'operations': ['audio.import'],
                    'admission': 'closed import destination and owned media; selected language/owner identity and exact source verification, not an ordinary empty hierarchy constructor'}
            elif name == 'ObjectSettingAssoc':
                row['correspondence'] = {'path': 'switch_assignment_owned_context',
                    'operations': ['switchContainer.addAssignment', 'object.setProperty'],
                    'admission': 'exact owner/child assignment and draft-bind-switch-child-context; association is not an independently constructible hierarchy object'}
            elif name == 'Modifier':
                row['correspondence'] = {'path': 'property_owned_randomizer', 'operations': ['ak.wwise.core.object.setRandomizer'],
                    'admission': 'live selected property and explicit randomizer outcome; embedded Modifier is not a hierarchy constructor'}
            elif name in {'RTPC', 'ParamControl', 'Curve'} and version != '2021.1':
                row['correspondence'] = {'path': 'property_bound_rtpc_and_curve', 'operations': ['object.setRTPC'],
                    'admission': 'live property/control-input handles, bounded curve points and exact owned RTPC/Curve class/owner verification; no independent hierarchy constructor'}
            elif name == 'Project':
                row['correspondence'] = {'path': 'owned_project_creation', 'operations': ['ak.wwise.cli.createNewProject'],
                    'admission': 'closed owned file destination, explicit project/platform/language settings and disclosed project verification; never object.create under another object'}
            elif name == 'Platform':
                row['correspondence'] = {'path': 'project_platform_creation', 'operations': ['ak.wwise.cli.addNewPlatform'],
                    'admission': 'closed project path and discovered supported platform; file/create side effects retain the existing CLI boundary'}
            elif name in {'Query', 'SearchCriteria'} and version in {'2021.1', '2022.1'}:
                source, = [s for s in sdk['sources'] if s['build'].startswith(version + '.') and s['member'] == 'waapi_import.html']
                row['correspondence'] = {'path': 'source_proven_query_constructor_boundary', 'operations': [],
                    'boundary': {'member': source['member'], 'sha256': source['sha256'], 'facts': source['facts'],
                        'scope': 'object.create' if version == '2021.1' else 'object.create and object.set',
                        'native_absence_claim': False},
                    'admission': 'exact native documented construction boundary; existing Query reads/configuration remain in scope'}
                row['state'] = 'implementation_dependency'
                row['dependencies'] = [{'owner_issue': 178, 'class': name, 'version': version,
                    'implementation_issue': 205,
                    'missing': 'Expose this primary-source-proven Query construction boundary before Preview; current generic class resolver has no exact version gate',
                    'source': {'member': source['member'], 'sha256': source['sha256']},
                    'native_absence_probe_required': False}]
            else:
                row['state'] = 'implementation_dependency'
                owned = source_lists.get(name, [])
                row['correspondence'] = {'path': ('owned_list_source_without_public_placement' if owned else 'source_constructor_applicability_unresolved'),
                    'operations': [], 'owned_source': owned,
                    'admission': 'retain source class investigation; no native absence and no discovery-to-constructor promotion'}
                row['dependencies'] = [{'owner_issue': 178, 'missing': ('Public source-owned List placement for exact owner/list/class'
                    if owned else 'Exact constructor/owner or source-supported tool/internal lifecycle classification'),
                    'class': name, 'version': version,
                    'desired_user_operation': 'create/configure this class through its source-owned role, without assuming independent hierarchy construction',
                    'next_evidence': 'matching constructor/ownership source or retained existing mechanism receipt; no per-class native execution requirement'}]
                if name == 'WorkUnit':
                    row['dependencies'][0].update(implementation_issue=205,
                        missing='Closed WorkUnit creation wrapper with source-declared side effects',
                        required_side_effects=['clear undo/redo history', 'clear clipboard', 'save newly created WWU'],
                        allowed_conflicts=['fail', 'merge', 'rename'], forbidden_conflict='replace',
                        existing_hooks=['object_graph_business._compile_create_fields', 'operation_registry._prepare_object_create',
                            'operation_registry._resolve_object_type', 'transaction owned file and authorization guards'])
                if name in {'Query', 'SearchCriteria'}:
                    source, = [s for s in sdk['sources'] if s['build'].startswith(version + '.') and s['member'] == 'waapi_import.html']
                    row['dependencies'][0].update(implementation_issue=205,
                        missing='Closed source-derived Query/SearchCriteria constructor choices',
                        source={'member': source['member'], 'sha256': source['sha256']},
                        required='criteria names must encode the documented SearchOperationID GUID from validated WWU/source; no model-authored IDs',
                        existing_hooks=['object_graph_business new declarations', 'planned_references result naming', 'operation_registry exact class/parent/field verification'])
            row['correspondence']['entrypoint'] = ENTRYPOINT
            rows.append(row)
    rows.sort(key=lambda r: r['id'])
    return {'contract': 'waapi-skill.installed-applicability-mapping/v1', 'owner_issue': 195,
        'denominator': dict(Counter(r['kind'] for r in rows)), 'rows': rows,
        'roster_sha256': digest([(r['id'], r['shape_sha256']) for r in rows]),
        'public_contracts': contracts, 'native_runs': 0,
        'scope': 'installed source/class/mode investigation; no per-class execution or independent constructibility inferred'}


def validate_mapping(mapping, root):
    if mapping != definition_mapping(root):
        raise ValueError('Exact installed applicability source/member/version/mode/route correspondence differs')
    return mapping


def program_review(root):
    from tests.support.applicability_program import program_sources
    if hashlib.sha256((root / PREVIOUS_PROOF['path']).read_bytes()).hexdigest() != PREVIOUS_PROOF['sha256']:
        raise ValueError('Original installed applicability proof changed')
    raw = (root / PROOF_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROOF_SHA256:
        raise ValueError('Exact installed applicability public program proof differs')
    proof = json.loads(gzip.decompress(raw))
    expected = {'existing-fields', 'list-2021', 'list-2025', 'list-set-2022', 'list-set-2025', 'rtpc', 'randomizer', 'plugin-factory-boundary-2021',
        'source-2022.1', 'source-2025.1', 'local-metadata-2022', 'local-metadata-2025',
        *['hierarchy-' + v for v in VERSIONS], *['media-' + v for v in ('2021.1', '2025.1')],
        *[kind + '-' + v for kind in ('effect-shareset', 'effect-owner', 'sink', 'metadata') for v in ('2022.1', '2025.1')],
        *['codec-' + v for v in ('2024.1', '2025.1')],
        *['codec-boundary-' + v for v in ('2021.1', '2022.1', '2023.1')]}
    if (proof.get('contract') != 'waapi-skill.applicability-public-program/v1'
            or proof.get('scope_kind') != 'product' or proof.get('evidence_kind') != 'injected_client_program'
            or proof.get('reports') != {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}
            or proof.get('native_effect') != 'not_observed' or proof.get('per_class_execution') is not False
            or proof.get('sources') != program_sources(root) or set(proof.get('traces', {})) != expected
            or proof.get('predecessor') != PREVIOUS_PROOF):
        raise ValueError('Exact installed applicability public program scope/source closure differs')
    for name, trace in proof['traces'].items():
        if not isinstance(trace, list) or not 1 <= len(trace) <= 128:
            raise ValueError('Bounded public applicability trace required')
        if name.startswith(('hierarchy-', 'list-', 'effect-shareset-', 'sink-', 'metadata-', 'media-', 'source-')) or name in {'rtpc', 'local-metadata-2025'}:
            if not any(row.get('verified') is True for row in trace):
                raise ValueError('Selected public applicability witness has no verified result: ' + name)
        if name.startswith('codec-') and not name.startswith('codec-boundary-'):
            if not any(row.get('state') == 'result_schema_checked' and row.get('verified') is False for row in trace):
                raise ValueError('Codec applicability must retain its unproved business association')
        if 'boundary-' in name and not any(row['exit_code'] == 2 for row in trace):
            raise ValueError('Selected public version boundary missing')
    return {'review_id': 'installed-class-mode-applicability-r1', 'program_proof': {'path': PROOF_PATH, 'sha256': PROOF_SHA256},
        'current_sources': proof['sources'], 'strength': 'source_definition_and_representative_public_code_mechanism',
        'native_effect': 'not_observed', 'per_class_execution': False,
        'classification_validation': 'current definition_mapping and portable reader validation; not executed by the historical public-runtime producer',
        'predecessor': PREVIOUS_PROOF,
        'owner_effect_strength': proof['owner_effect_strength'], 'codec_strength': proof['codec_strength']}


def _binding(row, attachment):
    return {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
        'installed_applicability_attachment': attachment,
        'correspondence_sha256': digest(row['correspondence']),
        'evidence': {} if row['state'] == 'approved_exclusion' else {'program': attachment}}


def _policy(row):
    return {'native_shape_sha256': row['shape_sha256'], 'categories': [] if row['state'] == 'approved_exclusion' else ['program'],
        'definition_scope': 'installed_class_mode_applicability', 'reason': row['correspondence']['admission'],
        'implementation_dependencies': row['dependencies'],
        **({'approved_exclusion': row['approved_exclusion']} if 'approved_exclusion' in row else {})}


def validate_attachment(descriptor, base, root, *, selected_mapping=None):
    from tests.support.condition_mechanism_reuse import _read
    attachment = _read(descriptor, base)
    if (not isinstance(attachment, dict) or set(attachment) != {'contract', 'review', 'mapping'}
            or attachment['contract'] != 'waapi-skill.installed-applicability-attachment/v1'):
        raise ValueError('Closed installed applicability attachment required')
    review = program_review(root)
    if _read(attachment['review'], base) != review:
        raise ValueError('Exact installed applicability program review differs')
    mapping = _read(attachment['mapping'], base) if selected_mapping is None else selected_mapping
    validate_mapping(mapping, root)
    branches = {b['id']: b for b in installed_obligations(root, digest=digest, load=load)
        if b['kind'] in {'target_applicability', 'plugin_topology'}}
    return {'review': review, 'mapping': mapping, 'members': {r['id']: r for r in mapping['rows']}, 'branches': branches}


def mapping_evidence_result(descriptor, branch, category, scope_kind, base, binding, root, *, context=None):
    try:
        attachment = binding['installed_applicability_attachment']
        context = context or validate_attachment(attachment, base, root)
        row = context['members'][branch['id']]
        expected = context['branches'][branch['id']]
        if (scope_kind != 'product' or descriptor != attachment or binding != _binding(row, attachment)
                or any(branch.get(k) != v for k, v in expected.items() if k != 'state')):
            raise ValueError('Exact installed applicability branch/source/version/mode/binding differs')
        if category != 'program' or row['state'] == 'approved_exclusion':
            return 'missing', 'Installed class mapping supplies no native execution or recipient metadata evidence'
        if row['dependencies']:
            return 'implementation_dependency', json.dumps(row['dependencies'], sort_keys=True)
        return 'reviewed_source_definition_and_public_mechanism', json.dumps({
            'path': row['correspondence']['path'], 'native_effect': 'not_observed',
            'per_class_execution': False, 'independent_constructibility': 'not_inferred_from_discovery'}, sort_keys=True)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return 'missing', str(exc)


def evaluate_binding(branch, binding, policy, scope_kind, base, root, context):
    row = context['members'][branch['id']]
    outcome, reason = mapping_evidence_result(binding['installed_applicability_attachment'], branch,
        'program', scope_kind, base, binding, root, context=context)
    if policy != _policy(row):
        branch.update(state='unresolved', reasons=['Exact installed applicability policy differs'])
        return
    branch.update(requirements=policy['categories'][:], metadata_scope='installed_source_applicability',
        direct_recipient_class_metadata='not_observed', direct_recipient_instance_metadata='not_observed',
        direct_recipient_native_effect='not_observed', applicability_correspondence=deepcopy(row['correspondence']))
    if row['state'] == 'approved_exclusion':
        expected = context['branches'][branch['id']]
        if (scope_kind != 'product' or binding != _binding(row, binding['installed_applicability_attachment'])
                or any(branch.get(k) != v for k, v in expected.items() if k != 'state')):
            branch.update(state='unresolved', reasons=['Exact bounded applicability exclusion differs'])
        else:
            branch.update(state='approved_exclusion', exclusion=deepcopy(row['approved_exclusion']), evidence_results={})
        return
    branch['evidence_results'] = {'program': {'outcome': outcome, 'reason': reason}}
    branch['state'] = ('source_definition_verified' if outcome == 'reviewed_source_definition_and_public_mechanism'
        else 'implementation_dependency' if outcome == 'implementation_dependency' else 'implemented_unverified')
    if row['dependencies']:
        branch['implementation_dependencies'] = deepcopy(row['dependencies'])


def attach_mappings(descriptors, bindings, base, root):
    if not isinstance(descriptors, list) or len(descriptors) != 1:
        raise ValueError('One exact complete installed applicability attachment required')
    context = validate_attachment(descriptors[0], base, root)
    pending = {r['id']: _binding(r, descriptors[0]) for r in context['mapping']['rows']}
    if pending.keys() & bindings.keys():
        raise ValueError('Conflicting installed applicability bindings; original evidence must remain separate')
    bindings.update(pending)
    return {'review_id': context['review']['review_id'], 'exact_source_members': len(pending),
        'native_runs': 0, 'scope': 'installed class/mode applicability only'}


def export_mapping(root, destination):
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    review, mapping = program_review(root), definition_mapping(root)
    def write(name, value):
        path = destination / name
        if path.exists():
            raise ValueError('Installed applicability publication is immutable')
        path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        return {'artifact': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    attachment = write('applicability-attachment.json', {'contract': 'waapi-skill.installed-applicability-attachment/v1',
        'review': write('applicability-review.json', review), 'mapping': write('applicability-mapping.json', mapping)})
    bindings = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {r['id']: _binding(r, attachment) for r in mapping['rows']}}
    requirements = deepcopy(load(root / 'docs/branch-coverage-requirements.json'))
    requirements['branches'].update({r['id']: _policy(r) for r in mapping['rows']})
    write('bindings.json', bindings); write('requirements.json', requirements)
    write('evidence-index.json', {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': [],
        'installed_applicability_attachments': [attachment]})
    branches = [b for b in installed_obligations(root, digest=digest, load=load)
        if b['kind'] in {'target_applicability', 'plugin_topology'}]
    return {'attachment': attachment, 'mapping': mapping, 'bindings': bindings,
        'requirements': requirements, 'branches': branches}
