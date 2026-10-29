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
PROOF_PATH = 'tests/fixtures/metadata-conditions/applicability-current-program-r7.json.gz'
PROOF_SHA256 = '27bdc3109fe857d268a1a24c882acd0c1e192daf63661979e54d82c15f5e89c7'
PREVIOUS_PROOF = {'path': 'tests/fixtures/metadata-conditions/applicability-current-program-r5.json.gz',
    'sha256': 'd226a3866aa532aff7266967c8a8d545acb7c22a88edf68a35e6b7c154c8c39e'}
SNAPSHOT = 'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz'
SDK_PATH = 'tests/fixtures/metadata-conditions/applicability-sdk-sources.json.gz'
SDK_SHA256 = '646336b2e4cb7324831d6a8b5c4be5b00417764eaf044adeccb6719ddd2a771b'
SAVED_CONSTRUCTOR_SOURCE = 'skills/waapi-skill/resources/metadata/saved-object-constructor-sources.json'
ENTRYPOINT = 'skills/waapi-skill/scripts/run.py gateway.py'
# Named hierarchy objects with ordinary public create routes. This is not the
# complete getTypes roster: embedded/tool/media classes are classified below.
HIERARCHY = frozenset(('AcousticTexture Action ActorMixer Attenuation AuxBus BlendContainer Bus '
    'ControlSurfaceSession Conversion DialogueEvent Event Folder GameParameter MixingSession ModulatorEnvelope '
    'ModulatorLfo ModulatorTime MusicPlaylistContainer MusicSegment MusicSwitchContainer MusicTrack '
    'PropertyContainer RandomSequenceContainer Sound SoundBank SoundcasterSession State StateGroup '
    'SidechainMix Switch SwitchContainer SwitchGroup Trigger').split())
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


CREATION_LIMIT_HEADING = '## User-approved remaining creation limits — 2026-10-29'
_CREATION_LIMIT_BUILDS = dict(zip(VERSIONS, ('2021.1.14.8108', '2022.1.19.8584',
    '2023.1.19.8928', '2024.1.13.9056', '2025.1.7.9143')))
# Exact registered identities, not a type-name denylist. Only NEW applicability
# roles without a known public constructor receive this user scope decision.
_CREATION_LIMIT_CLASSES = {
    3342352: ('UserProjectSettings', VERSIONS),
    3538960: ('PluginDataSource', VERSIONS),
    3670032: ('ExternalSourceFile', VERSIONS),
    3735568: ('ExternalSource', VERSIONS),
    4128784: ('MidiParameter', VERSIONS),
    4915216: ('Language', VERSIONS),
    2555920: ('MusicFade', VERSIONS),
    2752528: ('Panner', VERSIONS),
    786448: ('Position', VERSIONS),
    1966096: ('BlendTrack', VERSIONS[:3]),
    2359312: ('MusicPlaylistItem', VERSIONS[:2]),
    2424848: ('MusicTransition', VERSIONS[:2]),
    5177360: ('CustomState', VERSIONS),
    5570576: ('StateGroupInfo', VERSIONS[-1:]),
    4980752: ('ActionException', VERSIONS),
    655360016: ('MultiSwitchEntry', VERSIONS[:2]),
    1441808: ('ParamControl', VERSIONS[:1]),
    917520: ('Curve', VERSIONS[:1]),
    5701648: ('MediaPoolQuery', VERSIONS[-1:]),
}


def _apply_approved_creation_limit(root, row):
    if row['kind'] != 'target_applicability' or row['operation_mode'] != 'new-object':
        return
    version = row['version']; name = row['class_name']
    class_id = row['source_dimensions']['class_id']
    expected_name, versions = (_CREATION_LIMIT_CLASSES.get(class_id, (None, ()))
        if class_id != 720912 else ('Path' if version == '2021.1' else 'Path2D', VERSIONS))
    if (row['kind'] != 'target_applicability' or row['operation_mode'] != 'new-object'
            or name != expected_name or version not in versions
            or row['build'] != _CREATION_LIMIT_BUILDS[version]
            or row['id'] != f"{version}|metadata|{row['build']}|target|{class_id}|new-object"):
        return
    if row['state'] != 'implementation_dependency':
        raise ValueError('Approved creation limit cannot replace an implemented public role')
    authority = _authority(root, CREATION_LIMIT_HEADING)
    authority.update(scope='only the unresolved NEW creation role for this exact version/build/class; existing query/edit/copy and known creation methods retained',
        version=version, build=row['build'], class_id=class_id, class_name=name,
        operation_mode='new-object', original_dependencies=deepcopy(row['dependencies']))
    correspondence = row['correspondence']
    # Keep the original source/owner investigation and any already implemented
    # partial role. Approval resolves scope; it does not rewrite source facts.
    correspondence['unresolved_constructor_path'] = correspondence['path']
    correspondence['path'] = 'accepted_current_skill_creation_limit'
    correspondence['admission'] = 'user-approved current Skill limit for the unresolved creation role; no native impossibility or execution credit; exact existing fields, donor copy and known public methods retained'
    known = correspondence.setdefault('partial_roles', [])
    if name == 'Curve':
        known.append({'role': 'attenuation_curve_setter',
            'operations': ['ak.wwise.core.object.setAttenuationCurve'],
            'admission': 'existing closed attenuation curve setter only; other Curve birth roles receive the approved limit'})
    if name in {'CustomState', 'StateGroupInfo'} and version in VERSIONS[2:]:
        known.append({'role': 'state_group_and_property_association',
            'operations': ['ak.wwise.core.object.setStateGroups', 'ak.wwise.core.object.setStateProperties'],
            'admission': 'existing closed association methods retained; no class birth or per-State GUID acquisition inferred'})
    if name == 'MultiSwitchEntry':
        authority['scope'] = 'older MusicSwitch entry construction only; existing Dialogue conditions-owned audio.import association retained'
        known[0]['other_roles'] = 'older MusicSwitch entry construction receives the approved current Skill limit; no native absence claimed'
    if name == 'Language':
        authority['scope'] = 'adding Language to an existing project only; initial languages in cli.createNewProject and existing Language configuration retained'
        correspondence['retained_methods'] = ['ak.wwise.cli.createNewProject initial languages', 'exact existing Language fields']
    if known:
        correspondence['operations'] = list(dict.fromkeys(op for role in known for op in role['operations']))
        correspondence['approved_creation_boundary'] = authority
        row['state'] = 'source_definition_verified'
    else:
        row['state'] = 'approved_exclusion'
        row['approved_exclusion'] = authority
    row['dependencies'] = []


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


def _saved_constructor_correspondence(root, sdk, version, name, class_id, build):
    """Join #205's exact source-backed public seam without upgrading its oracle."""
    from wwise_waapi.canonical import canonical_sha256
    source = load(root / SAVED_CONSTRUCTOR_SOURCE)
    lane = source['versions'][version]
    source_class = source[{'WorkUnit': 'workunit_class_id', 'Query': 'query_class_id',
        'SearchCriteria': 'criterion_class_id'}[name]]
    primary, = [s for s in sdk['sources'] if s['build'] == build and s['member'] == lane['sdk_member']]
    if (source['contract'] != 'waapi-skill.saved-object-constructor-sources/v1'
            or source['sha256'] != canonical_sha256({k: v for k, v in source.items() if k != 'sha256'})
            or lane['build'] != build or source_class != class_id or lane['sdk_sha256'] != primary['sha256']):
        raise ValueError('Exact installed applicability saved constructor source differs')
    mechanism_tests = ['test_saved_constructor_sources_and_criterion_choices_match_exact_version_artifacts',
        ('test_workunit_creation_discloses_saved_file_and_irreversible_history_effects' if name == 'WorkUnit'
            else 'test_saved_query_constructor_has_exact_version_gate'),
        *(['test_query_criterion_choice_owns_native_name_and_retains_live_field_validation']
            if name == 'SearchCriteria' and lane['query_constructible'] else [])]
    common = {'implementation_issue': 205,
        'mechanism_sources': {'runtime': ['skills/waapi-skill/wwise_waapi/saved_object_construction.py',
            'skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py',
            'skills/waapi-skill/wwise_waapi/operation_registry.py'],
            'test_nodes': ['tests/unit/test_workunit_query_constructor_gateway.py::' + node for node in mechanism_tests],
            'strength': 'existing shared public mechanism tests; no per-row or native execution inferred'},
        'source': {'path': SAVED_CONSTRUCTOR_SOURCE,
        'sha256': source['sha256'], 'build': build, 'class_id': source_class,
        'member': lane['sdk_member'], 'member_sha256': lane['sdk_sha256'], 'clauses': lane['sdk_clauses']}}
    if name != 'WorkUnit' and not lane['query_constructible']:
        return {**common, 'path': 'source_proven_query_constructor_boundary', 'operations': [],
            'boundary': {'member': primary['member'], 'sha256': primary['sha256'], 'facts': primary['facts'],
                'scope': 'object.create' if version == '2021.1' else 'object.create and object.set',
                'native_absence_claim': False},
            'admission': 'exact matching-SDK Query construction boundary exposed before Preview; existing Query reads/configuration remain separate'}
    operations = ['object.create', *([] if version == '2021.1' else ['object.set'])]
    if name == 'WorkUnit':
        return {**common, 'path': 'source_bound_workunit_constructor', 'operations': operations,
            'effects': ['undo_redo_history_cleared', 'clipboard_cleared', 'corresponding_WWU_saved_in_active_project'],
            'admission': 'fresh WorkUnit Type Handle and exact WorkUnit/Folder owner; connected existing owner and owning-WorkUnit file scopes bound inside active project; native-owned destination; fail/merge/rename only; overlapping owner renames need separate Preview; no UndoGroup',
            'verification': 'result_schema_checked with GUID/class/parent/name/requested-field readback; history/clipboard and saved WWU bytes/save completeness unobserved'}
    if name == 'SearchCriteria':
        common['source'].update(criteria=lane['criteria'], factory_member=lane['factory_member'], factory_sha256=lane['factory_sha256'])
    return {**common, 'path': 'source_bound_query_criterion_constructor' if name == 'SearchCriteria' else 'source_bound_saved_query_constructor',
        'operations': operations,
        'admission': ('fresh SearchCriteria Type Handle under exact bound/planned Query in Queries hierarchy; one disclosed criterion choice; Gateway owns native SearchOperationID name; live class Field Handles; fail-only creation'
            if name == 'SearchCriteria' else 'fresh Query Type Handle and exact WorkUnit/Folder owner in Queries hierarchy; selected live fields'),
        'verification': ('result_schema_checked with GUID/class/Query-parent and requested-field readback; SearchOperationID_and_query_matches_unobserved'
            if name == 'SearchCriteria' else 'ordinary GUID/class/name/parent and requested-field verification; Query evaluation not claimed')}


def _music_playlist_correspondence(root, version, class_id, build):
    """Join #206's owned constructor without native or playback-effect credit."""
    from wwise_waapi.music_playlist import ITEM_CLASS, authority, declaration_contract
    from wwise_waapi.object_graph_business_contracts import object_graph_business_contract_data
    resource = f'skills/waapi-skill/resources/metadata/{version}/music-playlist-construction.json'
    try:
        current = authority(version)
        raw = (root / resource).read_bytes()
        source = json.loads(raw)
        if (hashlib.sha256(raw).hexdigest() != current['resource_sha256']
                or source['version'] != version or source['build'] != build
                or current['build'] != build or source['item_class'] != class_id or class_id != ITEM_CLASS):
            raise ValueError('source/version/class/build differs')
        members = []
        for member in current['sources']:
            path = f"skills/waapi-skill/references/semantic/{version}/music-playlist-sources/{member['member']}"
            if hashlib.sha256((root / path).read_bytes()).hexdigest() != member['sha256']:
                raise ValueError('retained primary source differs')
            members.append({'path': path, **member})
        native_members = []
        observed_version = current['native_readback_observation']['version']
        for member, sha in current['native_source_sha256'].items():
            path = f'skills/waapi-skill/references/semantic/{observed_version}/music-playlist-sources/{member}'
            if hashlib.sha256((root / path).read_bytes()).hexdigest() != sha:
                raise ValueError('representative readback source differs')
            native_members.append({'path': path, 'sha256': sha})
        manifest = f'skills/waapi-skill/resources/manifest/{version}/schemas.json'
        if hashlib.sha256((root / manifest).read_bytes()).hexdigest() != source['manifest_sha256']:
            raise ValueError('reflected grammar differs')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('Exact installed applicability Music Playlist source differs: ' + str(exc)) from exc
    declaration = declaration_contract(version)
    return {'implementation_issue': 206, 'path': 'music_playlist_container_owned_ordered_tree',
        'operations': ['object.set'], 'public_contract_sha256': digest(object_graph_business_contract_data('object.set', version)),
        'source': {'path': resource, 'sha256': current['resource_sha256'], 'build': build,
            'class_id': class_id, 'members': members, 'manifest': manifest, 'manifest_sha256': source['manifest_sha256'],
            'supporting_readback_sources': native_members,
            'supporting_readback_scope': current['native_readback_observation']},
        'declaration': declaration,
        'mechanism_sources': {'runtime': ['skills/waapi-skill/wwise_waapi/music_playlist.py',
            'skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py',
            'skills/waapi-skill/wwise_waapi/operation_registry.py'],
            'test_nodes': ['tests/unit/test_music_playlist_gateway.py::' + node for node in (
                'test_existing_playlist_nested_repeated_occurrences_survive_persisted_transaction',
                'test_source_supported_versions_compile_the_same_closed_playlist_tree',
                'test_playlist_closed_declaration_rejects_wrong_roles_raw_fields_and_oversized_trees',
                'test_playlist_immutable_preview_blocks_drift_before_write',
                'test_playlist_source_version_drift_blocks_persisted_execution',
                'test_playlist_result_or_independent_state_fault_fails_verification_without_retry',
                'test_playlist_class_loop_discovery_uses_only_disclosed_controllers',
                'test_playlist_constructor_older_version_is_a_scoped_boundary')],
            'strength': 'existing shared public mechanism tests; no per-row or native execution inferred'},
        'admission': 'standalone object.set for one exact existing MusicPlaylistContainer, live MusicPlaylistItem Type and owner PlaylistRoot Field Handles; bounded anonymous root/groups and distinct ordered repeated Segment occurrences; complete replacement with old-tree/metadata/configuration drift checks, policy authorization and execute-once verification; no arbitrary hierarchy placement or native custom-reference JSON',
        'verification_scope': declaration['verification_scope'], 'ordered_readback': declaration['ordered_readback'],
        'hidden_loop_controller': declaration['hidden_loop_controller'],
        'other_roles': '2021.1/2022.1 birth applicability remains independently assigned; existing-item edits remain separate; no audio or playback effect claimed'}



def _media_pool_database_correspondence(root, version, class_id, build):
    """Join the exact 2025 factory, retaining configuration-only strength."""
    from wwise_waapi.media_pool_database import authority, DATABASE_CLASS, PATH_CLASS
    from wwise_waapi.object_graph_business_contracts import object_graph_business_contract_data
    proof = authority(version)
    if proof is None or proof['build'] != build or class_id not in {DATABASE_CLASS, PATH_CLASS}:
        raise ValueError('Exact installed applicability Media Pool database scope differs')
    source = f"skills/waapi-skill/references/semantic/{version}/media-pool-database-sources/{proof['sdk_member']}"
    if hashlib.sha256((root / source).read_bytes()).hexdigest() != proof['sdk_sha256']:
        raise ValueError('Exact installed applicability Media Pool database source differs')
    return {'implementation_issue': 207, 'path': 'media_pool_database_owned_directory_configuration',
        'operations': ['object.set'],
        'public_contract_sha256': digest(object_graph_business_contract_data('object.set', version)),
        'source': {'path': source, 'member': proof['sdk_member'], 'member_sha256': proof['sdk_sha256'],
            'build': build, 'class_id': class_id, 'owner_class_id': DATABASE_CLASS,
            'element_class_id': PATH_CLASS, 'list_source': proof['list_source']},
        'mechanism_sources': {'runtime': ['skills/waapi-skill/wwise_waapi/media_pool_database.py',
            'skills/waapi-skill/wwise_waapi/anonymous_list_construction.py',
            'skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py',
            'skills/waapi-skill/wwise_waapi/operation_registry.py'],
            'test_nodes': ['tests/unit/test_media_pool_database_gateway.py::' + node for node in (
                'test_database_directory_survives_persisted_preview_authorization_and_verification',
                'test_database_public_schema_discloses_source_scoped_directory_outcome',
                'test_database_verification_rejects_wrong_owned_directory_without_retry',
                'test_database_malformed_directory_fails_before_preview',
                'test_database_directory_constructor_rejects_unproved_roles',
                'test_database_directory_preview_rejects_drift_before_write',
                'test_database_directory_not_admitted_from_unproved_older_registration',
                'test_database_constructor_requires_matching_source_class_not_name_alone')],
            'strength': 'matching primary source and shared public program mechanism; no per-class native execution inferred'},
        'admission': '2025.1 selected live database and directory Type Handles; ordinary exact bound parent; source-scoped Paths List and Path Field Handles; Gateway-owned empty name; bounded absolute directory string; immutable Preview, authorization, metadata/identity/source drift checks and one execution',
        'example_parent': proof['example_parent'], 'directory': proof['directory'],
        'verification_scope': proof['verification'],
        'other_roles': 'older lane class registration is not assumed; MediaPoolQuery saved construction remains independently assigned; no arbitrary anonymous List or hierarchy placement'}

def _music_transition_correspondence(root, version, class_id, build):
    """Three source-backed modern roles; no native execution upgrade."""
    from wwise_waapi.music_transitions import CLASS, authority, declaration_contract
    from wwise_waapi.object_graph_business_contracts import object_graph_business_contract_data
    try:
        current = authority(version, root=root / 'skills/waapi-skill')
        if current['build'] != build or class_id != CLASS:
            raise ValueError('exact version/build/class differs')
        directory = f'skills/waapi-skill/references/semantic/{version}/music-transition-sources'
        members = [{'path': directory + '/' + member,
            'sha256': hashlib.sha256((root / directory / member).read_bytes()).hexdigest()}
            for member in ('source-contract.json', 'WObjects.xml.gz', 'ak_wwise_core_object_set.html.gz')]
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise ValueError('Exact installed applicability Music Transition source differs: ' + str(exc)) from exc
    declaration = declaration_contract(version)
    return {'implementation_issue': 195, 'parent_issue': 174,
        'path': 'music_owner_transition_root_and_rule_construction', 'operations': ['object.set'],
        'public_contract_sha256': digest(object_graph_business_contract_data('object.set', version)),
        'source': {'build': build, 'class_id': class_id, 'authority': current, 'members': members},
        'declaration': declaration,
        'mechanism_sources': {'runtime': ['skills/waapi-skill/wwise_waapi/music_transitions.py',
            'skills/waapi-skill/wwise_waapi/object_graph_business.py',
            'skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py',
            'skills/waapi-skill/wwise_waapi/operation_registry.py', 'skills/waapi-skill/scripts/gateway.py'],
            'test_nodes': ['tests/unit/test_music_transition_gateway.py::' + node for node in (
                'test_transition_root_replacement_is_reviewable_and_verified_once',
                'test_append_transition_rules_preserves_root_and_every_existing_rule',
                'test_rule_membership_and_field_verification_does_not_treat_result_order_as_priority',
                'test_transition_independent_result_faults_fail_without_retry',
                'test_transition_preview_rejects_drift_without_dispatch',
                'test_transition_declaration_rejects_unbound_or_uncontrolled_construction',
                'test_transition_schema_and_older_version_limit_do_not_claim_native_absence')],
            'strength': 'matching primary source plus representative persisted public Python mechanism; no per-class native execution inferred'},
        'admission': 'one exact existing MusicSwitchContainer, MusicPlaylistContainer or MusicTrack; live MusicTransition Type Handle and exact owner TransitionRoot Reference Field Handle; bounded class scalar/reference Field Handles; explicit append-rules preserving current root/rules or replace-entire-root disclosing full removal; Gateway owns structural IsFolder and role naming; immutable policy/configuration/source/identity/metadata drift checks and execute once',
        'verification_scope': declaration['verification_scope'],
        'other_roles': 'older 2021.1/2022.1 constructors remain separately assigned to #195/#174; fade lifecycle/resolver remains separate; unordered membership gives no priority proof; no arbitrary class/custom-reference framework'}


def _control_surface_correspondence(root, version, name, class_id, build):
    """Exactly ten NEW rows join the finite constructor; no hardware credit."""
    from wwise_waapi.control_surface_construction import authority, declaration_contract
    path = 'skills/waapi-skill/resources/metadata/control-surface-constructor-sources.json'
    current = authority(version)
    source = load(root / path)
    from wwise_waapi.canonical import canonical_sha256
    lane = source['versions'][version]
    if (source['sha256'] != canonical_sha256({key: value for key, value in source.items() if key != 'sha256'})
            or source['sha256'] != current['source_sha256'] or lane['build'] != build
            or lane['classes'].get(name) != class_id or lane != {key: value for key, value in current.items() if key not in {'version', 'source_sha256'}}):
        raise ValueError('Exact installed applicability Control Surface constructor source differs')
    return {'implementation_issue': 195, 'path': 'control_surface_role_guarded_named_children',
        'operations': ['object.create', *([] if version == '2021.1' else ['object.set'])],
        'source': {'path': path, **current}, 'declaration': declaration_contract(version),
        'mechanism_sources': {'runtime': ['skills/waapi-skill/wwise_waapi/control_surface_construction.py',
            'skills/waapi-skill/wwise_waapi/object_capabilities.py', 'skills/waapi-skill/wwise_waapi/operation_registry.py'],
            'test_nodes': ['tests/unit/test_control_surface_constructor_gateway.py::' + node for node in (
                'test_user_group_creation_preserves_selected_root_and_verifies_once',
                'test_user_group_with_binding_uses_live_fields_and_retains_unrequested_peers',
                'test_five_version_definitions_disclose_source_roles_and_precise_boundaries',
                'test_constructor_preview_binds_parent_role_class_metadata_source_and_config',
                'test_constructor_independent_state_and_result_faults_fail_without_retry')],
            'strength': 'matching five-version source and representative public persisted Python mechanism; no per-class native execution inferred'},
        'admission': 'explicit role2 user group under selected exact live role3 root; Binding under selected or planned exact role0/2/4 group; source class and live Field Handles; no default0 user group, reserved-role construction, arbitrary parent or invented hardware encoding',
        'verification': 'stored independent GUID/class/parent/membership/role/requested-field outcome; policy/configuration/source/metadata/role drift and one execution; hardware effect and reserved automatic birth not claimed',
        'other_roles': 'existing object fields stay separate; reserved group construction is a scoped interface boundary, not native absence or a new exclusion'}


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
            elif name in {'ControlSurfaceBindingGroup', 'ControlSurfaceBinding'}:
                row['correspondence'] = _control_surface_correspondence(root, version, name, d['class_id'], row['build'])
            elif name in {'WorkUnit', 'Query', 'SearchCriteria'}:
                row['correspondence'] = _saved_constructor_correspondence(root, sdk, version, name, d['class_id'], row['build'])
            elif name == 'MusicPlaylistItem' and version in {'2023.1', '2024.1', '2025.1'}:
                row['correspondence'] = _music_playlist_correspondence(root, version, d['class_id'], row['build'])
            elif name == 'MusicTransition' and version in {'2023.1', '2024.1', '2025.1'}:
                row['correspondence'] = _music_transition_correspondence(root, version, d['class_id'], row['build'])
            elif version == '2025.1' and name in {'MediaPoolDatabase', 'MediaPoolDatabasePath'}:
                row['correspondence'] = _media_pool_database_correspondence(root, version, d['class_id'], row['build'])
            elif name in HIERARCHY:
                row['correspondence'] = {'path': 'ordinary_selected_hierarchy_constructor', 'operations': ['object.create'],
                    'admission': 'fresh Type Handle, compatible selected parent, class prerequisites, exact identity/class/parent verification; no arbitrary hierarchy placement'}
            elif name == 'BlendTrack' and version in {'2024.1', '2025.1'}:
                from wwise_waapi.core_business_contracts import core_business_contract_data
                operation = 'ak.wwise.core.blendContainer.addTrack'
                schema_path = f'skills/waapi-skill/resources/manifest/{version}/schemas.json'
                schema, = [s for s in load(root / schema_path)['schemas'] if s['uri'] == operation]
                row['correspondence'] = {'path': 'blend_container_owned_track_factory', 'operations': [operation],
                    'public_contract_sha256': digest(core_business_contract_data(operation, version)),
                    'source': {'path': schema_path, 'schema': schema, 'schema_sha256': digest(schema)},
                    'admission': 'bound exact BlendContainer and one track name through request-schema; no arbitrary hierarchy placement or assignment creation',
                    'verification': 'result_schema_checked; no independent new-track identity, assignment edge or native business effect claimed'}
            elif name == 'Marker' and version in {'2021.1', '2022.1'}:
                from wwise_waapi.object_query_local_lists import MARKER_BOUNDARY_SHA256
                path = f'skills/waapi-skill/references/semantic/{version}/source-marker-object-model-boundary.json'
                raw = (root / path).read_bytes()
                boundary = json.loads(raw)
                if (hashlib.sha256(raw).hexdigest() != MARKER_BOUNDARY_SHA256[version]
                        or boundary['version'] != version or boundary['wwise_build'] != row['build']
                        or boundary['legacy_marker']['class_id'] != d['class_id']):
                    raise ValueError('Exact installed applicability source Marker model boundary differs')
                row['correspondence'] = {'path': 'source_proven_direct_marker_model_boundary', 'operations': [],
                    'source': {'path': path, 'sha256': MARKER_BOUNDARY_SHA256[version]}, 'boundary': boundary,
                    'admission': 'source-proven 2023 direct source Marker object/List introduction and public local-markers gate; legacy Inner registration is not modern Marker construction; file/imported/effective marker information remains separate'}
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
                if name == 'MusicTransition' and version in {'2021.1', '2022.1'}:
                    row['dependencies'] = [{'owner_issue': 195, 'parent_issue': 174,
                        'missing': 'Older source-owned MusicTransition root/rule constructor role remains separately assigned',
                        'class': name, 'version': version, 'native_absence_claim': False,
                        'existing_fields': 'exact existing GUID scalar/reference edits remain separate'}]
                if name == 'MultiSwitchEntry' and version in {'2021.1', '2022.1'}:
                    # One owned role is implemented. The class row also covers
                    # other roles, so it must retain its unresolved dependency.
                    row['correspondence']['partial_roles'] = [{
                        'role': 'Dialogue_conditions_owned_association', 'operations': ['audio.import'],
                        'admission': 'explicit Dialogue conditions; fresh live MultiSwitchEntry AudioNode admission; preserve nondefault WorkUnit import-group boundary and exact older Container/RandomSequenceContainer guard',
                        'verification': 'owner/referrers and requested numeric fields checked; decision-path order readback unobserved',
                        'other_roles': 'older MusicSwitch entry construction remains unresolved; no arbitrary hierarchy constructor'}]
            _apply_approved_creation_limit(root, row)
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
