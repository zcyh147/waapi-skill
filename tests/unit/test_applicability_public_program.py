"""A few actual Gateway flows support shared applicability source mappings."""
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

from tests.support.applicability_program import program_sources
from tests.support.applicability_completion_mapping import PREVIOUS_PROOF
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit import test_new_object_conditions_gateway as hierarchy
from tests.unit import test_legacy_owned_list_gateway as legacy_lists
from tests.unit import test_object_graph_owned_choices_gateway as lists
from tests.unit import test_plugin_shareset_gateway as effects
from tests.unit import test_plugin_kind_placements_gateway as kinds
from tests.unit import test_conversion_plugin_gateway as conversion
from tests.unit import test_object_metadata_business_gateway as existing
from tests.unit import test_audio_import_named_sources as media
from tests.unit import test_owned_rtpc_control_input_gateway as rtpc
from tests.unit import test_core_business_gateway as core
from tests.unit import test_metadata_local_plugin_gateway as local_metadata

ROOT = Path(__file__).parents[2]


def source_plugin_flow(path, version):
    class SourceClient(kinds.KindClient):
        def __init__(self, version):
            kinds.ShareSetClient.__init__(self, version, target_type='Sound',
                target_path=r'\Actor-Mixer Hierarchy\Default Work Unit\Sound')
            self.kind, self.class_id, self.plugin_label, self.native_type = 'source', 6684674, 'Wwise Tone Generator', 'Source'
            self.drop_existing, self.mix = False, 1
    client = SourceClient(version)
    code, declared, step, env = kinds.declare(path, version, client, placement='owner')
    assert code == 0, declared
    tx = kinds.confirmed_preview(step, env)
    code, executed = kinds.gateway.execute_gateway(['execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    code, verified = kinds.gateway.execute_gateway(['verify', tx], env=env, client_factory=lambda _: client)
    assert code == 0 and verified['verified'] is True, verified
    assert sum(u.endswith('object.set') for u, _, _ in client.calls) == 1


def test_representative_applicability_public_mechanisms(tmp_path, monkeypatch, request):
    before = program_sources(ROOT)
    traces, active = {}, []
    script = ROOT / 'skills/waapi-skill/scripts/gateway.py'
    for module in list(sys.modules.values()):
        if getattr(module, '__file__', None) and Path(module.__file__).resolve() == script.resolve():
            original = module.execute_gateway
            def observe(argv, *args, _original=original, **kwargs):
                code, payload = _original(argv, *args, **kwargs)
                if active:
                    trace = traces[active[0]]
                    assert len(trace) < 128
                    row = {'command': payload.get('command'), 'exit_code': code,
                        **{k: deepcopy(payload[k]) for k in ('state', 'verified') if k in payload}}
                    prepared = payload.get('artifact', {}).get('prepared_operation', {})
                    if prepared:
                        row['dispatch'] = deepcopy(prepared['dispatch'])
                    trace.append(row)
                return code, payload
            monkeypatch.setattr(module, 'execute_gateway', observe)
    def run(key, fn, *args):
        path = tmp_path / key; path.mkdir()
        traces[key] = []; active[:] = [key]
        fn(path, *args)
        active.clear()
        assert traces[key], key
    for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'):
        run('hierarchy-' + version, hierarchy.test_class_default_or_explicit_prerequisite_reaches_verified_creation,
            version, 'ModulatorTime', 50)
    run('list-2021', legacy_lists.test_legacy_source_list_create_verifies_actual_class_owner_and_membership,
        'MusicSegment', 'MusicCue', 'Cues')
    run('list-2025', lists.test_documented_list_handle_places_created_root_and_verifies_native_class_owner_and_preservation,
        'fail', None)
    run('existing-fields', existing.test_property_draft_discovers_opaque_field_and_materializes_business_value, 'meaning')
    for version in ('2022.1', '2025.1'):
        run('effect-shareset-' + version, effects.test_shareset_executes_once_and_verifies_its_own_identity, version)
        run('effect-owner-' + version, effects.test_owner_effect_preview_retains_its_versioned_slot_topology, version)
        for kind in ('sink', 'metadata'):
            run(kind + '-' + version, kinds.test_independent_plugin_kind_uses_exact_live_class_and_hierarchy, version, kind)
        run('source-' + version, source_plugin_flow, version)
    run('local-metadata-2022', local_metadata.test_older_metadata_appends_direct_selected_class_and_discloses_ownership_observation, '2022.1')
    run('local-metadata-2025', local_metadata.test_local_metadata_appends_one_owned_custom_plugin_and_preserves_ordered_slots)
    for version in ('2024.1', '2025.1'):
        run('codec-' + version, conversion.test_conversion_type_handle_invokes_setter_without_claiming_codec_or_platform_effect, version)
    for version in ('2021.1', '2022.1', '2023.1'):
        run('codec-boundary-' + version, conversion.test_conversion_setter_retains_older_version_boundary, version)
    run('plugin-factory-boundary-2021', effects.test_2021_plugin_creation_is_explicitly_unavailable)
    for version in ('2021.1', '2025.1'):
        run('media-' + version, media.test_sdk_two_named_sources_share_one_sound_and_preserve_existing_owner, version)
    run('rtpc', rtpc.test_public_time_input_creates_owned_reference_and_verifies_once)
    run('randomizer', core.test_randomizer_core_plan_discovers_field_by_meaning_then_closes_values)
    def finalized(reports):
        assert reports == {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}
        assert before == program_sources(ROOT)
        record = {'contract': 'waapi-skill.applicability-public-program/v1', 'scope_kind': 'product',
            'evidence_kind': 'injected_client_program', 'reports': reports, 'sources': before,
            'predecessor': PREVIOUS_PROOF,
            'traces': traces, 'native_effect': 'not_observed', 'per_class_execution': False,
            'owner_effect_strength': 'public_preview_only; exact versioned dispatch construction, not a new execution',
            'codec_strength': 'result_schema_checked; platform association unproved'}
        destination = Path(os.environ.get('WAAPI_APPLICABILITY_CAPTURE', str(tmp_path / 'program.json.gz')))
        assert not destination.exists(), 'Evidence publication is immutable'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(gzip.compress(json.dumps(record, sort_keys=True).encode(), mtime=0))
    register_exact_evidence_finalizer(request.node, finalized)
