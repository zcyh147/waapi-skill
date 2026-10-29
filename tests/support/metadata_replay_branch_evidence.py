"""Current public replays of closed original R51/R54/R55 metadata observations.

Original native execution and current injected replay retain separate identities.
The existing shared finalizer publishes current product evidence only at teardown.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tests.maintenance import branch_coverage_audit as audit
from tests.support.metadata_read_branch_evidence import source_seals as metadata_source_seals
from tests.support.media_pool_branch_evidence import public_read_observation

REQUIREMENTS_SOURCE = 'docs/branch-coverage-requirements.json'
CURRENT_REQUIREMENTS_IDENTITY = 'waapi-skill.requirements-publication-identity/v1'


def current_requirements_source_seal(document=None, mapping_bindings=None):
    """Current policy identity only; historical source maps remain raw Git bytes."""
    from tests.maintenance.branch_audit_mapping import requirements_identity_projection
    document = audit.load(audit.ROOT / REQUIREMENTS_SOURCE) if document is None else document
    return audit.digest(requirements_identity_projection(document, mapping_bindings, root=audit.ROOT))


def r51_current_sources():
    sources = source_seals()
    sources[REQUIREMENTS_SOURCE] = current_requirements_source_seal()
    name = 'tests/maintenance/branch_audit_mapping.py'
    sources[name] = hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest()
    return sources


def git_current_source_seals(candidate, names, *, root=None):
    """Own current semantic policy with that Git pin, never the live document."""
    root = audit.ROOT if root is None else Path(root)
    names = set(names)
    sources = git_source_seals(candidate, names - {REQUIREMENTS_SOURCE}, root=root)
    if REQUIREMENTS_SOURCE in names:
        sources[REQUIREMENTS_SOURCE] = _git_requirements_source_seal(str(root.resolve()), candidate)
    return sources


def _git_requirements_source_seal(root_name, candidate):
    """Read immutable Git policy; recheck mutable sealed mapping files each time."""
    import re
    import subprocess
    import tempfile
    from tests.maintenance.branch_audit_mapping import requirements_identity_projection
    from tests.semantic.support.codex_archive_paths import parse_archive_relative_path
    root = Path(root_name)
    if not isinstance(candidate, str) or not re.fullmatch('[0-9a-f]{40}', candidate):
        raise ValueError('Current metadata policy requires an exact Git candidate')
    def read(name):
        parsed = parse_archive_relative_path(name)
        if parsed.canonical != name:
            raise ValueError('Current metadata Git source requires its canonical path')
        result = subprocess.run(['git', '--no-replace-objects', 'show', candidate + ':' + name],
            cwd=root, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode or len(result.stdout) > audit.AUDIT_MAX_DOCUMENT_BYTES:
            raise ValueError('Current metadata Git policy source unavailable or oversized')
        return result.stdout
    raw = read(REQUIREMENTS_SOURCE)
    index = json.loads(read('docs/branch-coverage-evidence-index.json'))
    # Reuse the ordinary chunk parser and full raw part/document seals. These
    # temporary files contain exact Git source bytes, not recreated evidence.
    with tempfile.TemporaryDirectory(prefix='waapi-metadata-git-policy-') as folder:
        path = Path(folder) / 'requirements.json'
        path.write_bytes(raw)
        manifest = json.loads(raw)
        if manifest.get('contract') == audit.REQUIREMENTS_INDEX_CONTRACT:
            parts = manifest.get('parts')
            if not isinstance(parts, list) or not 1 <= len(parts) <= audit.REQUIREMENTS_MAX_PARTS:
                raise ValueError('Current metadata Git requirements parts invalid')
            total = 0
            for descriptor in parts:
                if (not isinstance(descriptor, dict) or set(descriptor) != {'path', 'sha256'}
                        or not isinstance(descriptor['path'], str)
                        or descriptor['path'] in {'', '.', '..'}
                        or any(char in descriptor['path'] for char in '/\\:')):
                    raise ValueError('Current metadata Git requirements part must be adjacent')
                body = read('docs/' + descriptor['path'])
                total += len(body)
                if len(body) > audit.REQUIREMENTS_MAX_PART_BYTES or total > audit.REQUIREMENTS_MAX_TOTAL_BYTES:
                    raise ValueError('Current metadata Git requirements parts exceed bounds')
                (path.parent / descriptor['path']).write_bytes(body)
        document = audit.load(path)
    return audit.digest(requirements_identity_projection(document, root=root, index_document=index))


# Reviewed successor of the accepted R59 program source map. This data is
# separate from immutable original R51/R54/R55 raw maps. The named metadata
# list/detail/cache/normalization flow is unchanged; Gateway preflight changes
# are attenuation-only. Additive reference-kind evidence is preserved by the
# metadata record, not a new class default or native fact. Other additions are
# already-reviewed query/constructor/UI/runtime contracts and their source or
# evidence plumbing; exact bytes/roster remain required and confer no native
# credit. Final publication must replace only the requirements semantic target
# and any subsequently reviewed owned-source deltas before actual replay.
R59_REPLAY_PROGRAM = {
    'artifact': 'tests/fixtures/branch-evidence/product/r54-class-replay-r59-4e3c2800-r3/case-0/program.json',
    'sha256': '0a95bc9eb5f1d94cc3941801fab0429133214d2aa78eb45b89c39375a314c45a'}
R59_REPLAY_CANDIDATE = '4e3c28007093bb7a90aad5d93e2565d498eba7c0'
R59_REPLAY_SOURCE_SHA256 = 'b5f9328ca8992b040f357e121b24e88df938f5eac25abf19945c3c020da24cb7'
CURRENT_REPLAY_MUTABLE_SOURCES = frozenset(('tests/maintenance/branch_audit_completion.py',
 'tests/maintenance/branch_coverage_audit.py',
 'tests/maintenance/collect_class_metadata.py',
 'tests/support/media_pool_branch_evidence.py',
 'tests/support/metadata_replay_branch_evidence.py',
 'tests/unit/test_class_metadata_collection.py',
 'tests/unit/test_metadata_default_branch_evidence.py',
 'tests/unit/test_metadata_discovery_gateway.py',
 'tests/unit/test_metadata_replay_attachments.py'))
R51_CURRENT_FIXED_SOURCES = frozenset(('docs/branch-coverage-requirements.json',
 'tests/conftest.py',
 'tests/maintenance/branch_audit_completion.py',
 'tests/maintenance/branch_audit_mapping.py',
 'tests/maintenance/branch_coverage_audit.py',
 'tests/support/exact_evidence_finalization.py',
 'tests/support/media_pool_branch_evidence.py',
 'tests/support/metadata_read_branch_evidence.py',
 'tests/support/metadata_replay_branch_evidence.py',
 'tests/support/metadata_replay_cases.json',
 'tests/support/metadata_result_case_bank.py',
 'tests/unit/test_branch_coverage_completion_cli.py',
 'tests/unit/test_branch_evidence_readers.py',
 'tests/unit/test_media_build_business_gateway.py',
 'tests/unit/test_metadata_default_branch_evidence.py',
 'tests/unit/test_metadata_discovery_gateway.py',
 'tests/unit/test_metadata_replay_attachments.py'))
CURRENT_REPLAY_SOURCE_CHANGES = {'docs/branch-coverage-requirements.json': {'after': 'e0b7ff81f7224ed23690048bd8df641dc520e17039a6b0175c2851a6ab0810f6',
                                            'before': '99ad508b7fca40ea0db30542115ce90e421e46ed276200d5fbb63a8e39cada3a'},
 'skills/waapi-skill/evals/request_mapping_registry.json': {'after': '7f821850b53941554061aea7d2acc473ac92817b4dac02368a843abbdea79a87',
                                                            'before': '081457f1ec1c901342eaf7b0432abdff719d388737e81f9b094c27079e2a3f77'},
 'skills/waapi-skill/references/semantic/2021.1/platform-copy-sources.json': {'after': 'de813ca9a59eacfdfff54598a2f3c35d9579c7edf7eedd3673ac8f72691a0b32',
                                                                              'before': None},
 'skills/waapi-skill/references/semantic/2021.1/playlist-native-boundary.json': {'after': '3d6e9034576e9f601a6df4d0b33fe4890200bbcc9d582d51c5e7a396ac0ef301',
                                                                                 'before': None},
 'skills/waapi-skill/references/semantic/2021.1/query-active-source-native-boundary.json': {'after': '43754eeade75411f5fdbcbe6efc0ea8048bff0ed40f977a3461cea5dc6269f80',
                                                                                            'before': None},
 'skills/waapi-skill/references/semantic/2021.1/query-curve-points-native-boundary.json': {'after': 'd2a9c8b053330c467221f7ea27d17ea9037b06d900f66cd58dba1cfaabbf2f0e',
                                                                                           'before': None},
 'skills/waapi-skill/references/semantic/2021.1/query-field-condition-sources.json': {'after': 'c05c32b6f904c55c519bc46761451b5588438cc394cb0c23f79a753bd3cfa9de',
                                                                                      'before': None},
 'skills/waapi-skill/references/semantic/2021.1/query-list-output-sources.json': {'after': '4ca2cb2d6a33e0218f71aa917554e86e14b4c04ed3195cc9a1d42b73caaf04fa',
                                                                                  'before': None},
 'skills/waapi-skill/references/semantic/2021.1/query-namespaced-property-sources.json': {'after': '6727ddf2e423b1bb548786b0fd51b25ca5c7bd02be76695e775af816229beca4',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2021.1/query-randomizer-sources.json': {'after': '5e157b7fd31e74d288d63d047655bd5cb30a593a3085146f9abeb9a609e27f1a',
                                                                                 'before': None},
 'skills/waapi-skill/references/semantic/2021.1/query-reference-condition-sources.json': {'after': '79b90f069f95bfb34f2347479ec8db52a9c77d5ca9fe96f6373167555c28240e',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2021.1/query-reference-value-sources.json': {'after': '045ebaed2be4c9211169bf7b45a98b1ee6405de58de6e99084657437244f6edc',
                                                                                      'before': None},
 'skills/waapi-skill/references/semantic/2021.1/query-related-output-sources.json': {'after': '86bd443323f2d555c83d1baea2b475b3fcf8a71055ff18dce7e8ec7246ce10d3',
                                                                                     'before': None},
 'skills/waapi-skill/references/semantic/2021.1/query-return-options.json': {'after': 'e1135c6f35c4706860ca327d8b5dbcb5cd6f07342966a85121b58007b0b684cb',
                                                                             'before': None},
 'skills/waapi-skill/references/semantic/2021.1/source-marker-object-model-boundary.json': {'after': 'cbf38d10d47a74703bd56da8b98ed5821420d64ab30f9da6922312e717033c93',
                                                                                            'before': None},
 'skills/waapi-skill/references/semantic/2022.1/platform-copy-sources.json': {'after': 'ad0a235a5e28bc4396a18fd8f84f286c892de1a62dad70f639c589a4aee47ca7',
                                                                              'before': None},
 'skills/waapi-skill/references/semantic/2022.1/playlist-native-boundary.json': {'after': '76ddb7909a6c7770c2e8eb772cc86f1552359a69c9e1683a879d2ab09bbe5295',
                                                                                 'before': None},
 'skills/waapi-skill/references/semantic/2022.1/query-field-condition-sources.json': {'after': 'fc43b01489ad38d573f386c3d8a1af1253b83c29b495f104c0afb0a2004ca718',
                                                                                      'before': None},
 'skills/waapi-skill/references/semantic/2022.1/query-list-output-sources.json': {'after': '02dae4ef5bce28c05132ba78717c75dd55237f21152d922d3a70e36085f0230c',
                                                                                  'before': None},
 'skills/waapi-skill/references/semantic/2022.1/query-local-list-bridge.json': {'after': '832ec2fda677a1b728aee13481a8fe951ff2e2ffdfb72dfacd7bf539e1df330c',
                                                                                'before': None},
 'skills/waapi-skill/references/semantic/2022.1/query-namespaced-property-sources.json': {'after': '83738aeb3dd961ff78ca3b9804c8682887b6ab55c831bb6397922fb948221a45',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2022.1/query-randomizer-sources.json': {'after': '1be63c55f4906db1ea267668298a4cb08aeffd34328ee1cb9be0e20c0e03695f',
                                                                                 'before': None},
 'skills/waapi-skill/references/semantic/2022.1/query-reference-condition-sources.json': {'after': 'ebdd2932a52953793ddfa5a7bd207cd985eee1950236e8d7ff569f98fcf7139f',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2022.1/query-reference-value-sources.json': {'after': 'f7122c5b73cf15f760945a278c1d09288cf29c071a464072e0f2f82401b75690',
                                                                                      'before': None},
 'skills/waapi-skill/references/semantic/2022.1/query-related-output-sources.json': {'after': 'dcafbecf682fd7351c257e68886549083810c29068f65ddcf19e63fa3d49afd5',
                                                                                     'before': None},
 'skills/waapi-skill/references/semantic/2022.1/query-return-options.json': {'after': 'e1135c6f35c4706860ca327d8b5dbcb5cd6f07342966a85121b58007b0b684cb',
                                                                             'before': None},
 'skills/waapi-skill/references/semantic/2022.1/source-marker-object-model-boundary.json': {'after': 'f88030959957037a8d087fc4bab6df8bcbac5b59e71a9c7eeaa04771e844cb99',
                                                                                            'before': None},
 'skills/waapi-skill/references/semantic/2023.1/manual-marker-construction-source.json': {'after': '8968f55fd43b0d07ed3a38534d8fda9cc6544e65756457a63cf1231bf7c60ede',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2023.1/music-playlist-sources/ak_wwise_core_object_set_example_create_a_music_playlist_container_with_segment_and_playlist.html': {'after': '10fdc3112e485e03009daa3e3822ec4d30644ac4a524436fdfab1e961b7a8cbf',
                                                                                                                                                                            'before': None},
 'skills/waapi-skill/references/semantic/2023.1/music-playlist-sources/wwiseobject_musicplaylistitem.html': {'after': 'deaf5d5dce2f0d2f7e045d8d84c81545077cbcc27fcb4306620c757708384efa',
                                                                                                             'before': None},
 'skills/waapi-skill/references/semantic/2023.1/music-transition-sources/WObjects.xml.gz': {'after': '8e7d2664ddf26f81f1d9cc4823a6782205072306d97656a6bea517fd69550e37',
                                                                                            'before': None},
 'skills/waapi-skill/references/semantic/2023.1/music-transition-sources/ak_wwise_core_object_set.html.gz': {'after': '3eceebdd260cc6bce67e74c67862a380dfc4ad7fcf73d4aa7a881a5711225b5c',
                                                                                                             'before': None},
 'skills/waapi-skill/references/semantic/2023.1/music-transition-sources/source-contract.json': {'after': '6e3d7fa43cd732b533e4f8b62cf86e750d291e62eaf70c6e7dcd41e9507f953a',
                                                                                                 'before': None},
 'skills/waapi-skill/references/semantic/2023.1/platform-copy-sources.json': {'after': '4f48862341f81a1e9dea45c1e6edb8d01c5228a063607c41538640ccc421a71d',
                                                                              'before': None},
 'skills/waapi-skill/references/semantic/2023.1/query-context-sources.json': {'after': 'ebb59dccf08e140cd667fb4a8138395402fbb43c0af08085b1e746afe14f38a8',
                                                                              'before': None},
 'skills/waapi-skill/references/semantic/2023.1/query-field-condition-sources.json': {'after': 'acad9ee3bafb4a646b28c4fbc9c790cdd5c2a12c7ebfb3d60d37ae6b2fa387eb',
                                                                                      'before': None},
 'skills/waapi-skill/references/semantic/2023.1/query-list-output-sources.json': {'after': '97ed03d45000fda7ca12c95bb414c23c2ad846c24eb8aaa464385686d9253e88',
                                                                                  'before': None},
 'skills/waapi-skill/references/semantic/2023.1/query-local-list-bridge.json': {'after': '9c5f267fc3d103b06501007abb433bcaa3a1ba6d1e7e70a8e867327fdc9efc19',
                                                                                'before': None},
 'skills/waapi-skill/references/semantic/2023.1/query-marker-records-sources.json': {'after': 'cda46faae59f0e9dfe9078c19f50c224badc906af34a42d67f8b2e0e6c82b509',
                                                                                     'before': None},
 'skills/waapi-skill/references/semantic/2023.1/query-namespaced-property-sources.json': {'after': '44d6938b7f217643db4728f1d62932cf2487b8f2d2526d1251fc79eb985db673',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2023.1/query-randomizer-sources.json': {'after': '44732310745ace000c61b4663159d305fe2269a556742abb994dd0fae7db4292',
                                                                                 'before': None},
 'skills/waapi-skill/references/semantic/2023.1/query-reference-condition-sources.json': {'after': 'e3dec2c6f449bcbfbd66c56d31a0dd1dbf84d6df026b955895f37c52b8bbd363',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2023.1/query-reference-value-sources.json': {'after': '20c937648ace8ab1c0229f5ef468944d10451f6ed13574f3319f43f072fae78c',
                                                                                      'before': None},
 'skills/waapi-skill/references/semantic/2023.1/query-related-output-sources.json': {'after': 'bb8d257161e0faac7f02e52f2d36589db5b14deb4857276dab832eeba3a5c5ac',
                                                                                     'before': None},
 'skills/waapi-skill/references/semantic/2023.1/query-return-options.json': {'after': '854d9da6ef588bac87476abccf346c86d83902685a418e8de0363e5db7d3346f',
                                                                             'before': None},
 'skills/waapi-skill/references/semantic/2024.1/blend-assignment-source.json': {'after': '1b6a21ffd0502c15b5f28bd131e8c26237bac2e6bd16abccbe1f2090b13a0cfc',
                                                                                'before': None},
 'skills/waapi-skill/references/semantic/2024.1/manual-marker-construction-source.json': {'after': '986e9959574320aa5e7506c0003d8a18619ee2362642ca17764644b464d2b149',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2024.1/music-playlist-sources/ak_wwise_core_object_set_example_create_a_music_playlist_container_with_segment_and_playlist.html': {'after': '71decf0495bb28ab251ec457ea3f056e5bb7c195260b742d26c3897fec4c2ab1',
                                                                                                                                                                            'before': None},
 'skills/waapi-skill/references/semantic/2024.1/music-playlist-sources/wwiseobject_musicplaylistitem.html': {'after': 'ed6ce04c586d3dd5faed4e608d2ad1bb7bf30770a3870676547e8d051fbbdd91',
                                                                                                             'before': None},
 'skills/waapi-skill/references/semantic/2024.1/music-transition-sources/WObjects.xml.gz': {'after': '3dd986a153a73ff4f15bd5f16238afaa1b153e49f9e904bac080213927c7a53a',
                                                                                            'before': None},
 'skills/waapi-skill/references/semantic/2024.1/music-transition-sources/ak_wwise_core_object_set.html.gz': {'after': '4476affb06220c4a87fc07f3ba6493052632f48b09f553ba20415fcd74d7f2a5',
                                                                                                             'before': None},
 'skills/waapi-skill/references/semantic/2024.1/music-transition-sources/source-contract.json': {'after': 'f1877f93f2fafe372030c17f7fe64c7de5c2ff7f294dfb8033c83257fbab5fdc',
                                                                                                 'before': None},
 'skills/waapi-skill/references/semantic/2024.1/platform-copy-sources.json': {'after': '96593858be6a9b1f9fb5da2c819cbc593f070c6c2384827a61a8a5f7de02260e',
                                                                              'before': None},
 'skills/waapi-skill/references/semantic/2024.1/query-context-sources.json': {'after': 'b2bc4ab25553c0855a988ec6a29c1289d761068c909c19f8bc0117e3c33b13ce',
                                                                              'before': None},
 'skills/waapi-skill/references/semantic/2024.1/query-field-condition-sources.json': {'after': '7ad1786f0e67fd78f99a0e8ac162b3df136b0ffadafcc95d17bbe37ee294ecb2',
                                                                                      'before': None},
 'skills/waapi-skill/references/semantic/2024.1/query-list-output-sources.json': {'after': 'cfa6a54651a7aa139c6c7a55891d9201172129b4ec0ad3b2c86fd5537a153083',
                                                                                  'before': None},
 'skills/waapi-skill/references/semantic/2024.1/query-local-list-bridge.json': {'after': '7d6110dae34af631e79829e34e08ab0ec0e6080c1c21723608ec3ecce84aa682',
                                                                                'before': None},
 'skills/waapi-skill/references/semantic/2024.1/query-marker-records-sources.json': {'after': '63f4a1bd46e5acde7997fda5f50fcaf5c0901b050a46f7c3d8ab607476438613',
                                                                                     'before': None},
 'skills/waapi-skill/references/semantic/2024.1/query-namespaced-property-sources.json': {'after': '5f5ee14ea06d47e08b0b166d2e17282f264c2862d0a23aeb6f6d0da524bb9cc6',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2024.1/query-randomizer-sources.json': {'after': '2ef99f8f44e0897a1ca185cf8a091033769abc4a717311fc0d2d8ebe15f8d577',
                                                                                 'before': None},
 'skills/waapi-skill/references/semantic/2024.1/query-reference-condition-sources.json': {'after': 'a4adc8b8abeca8492e45d16732c366957b11cad51c28a154c8fd033fcb8426ae',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2024.1/query-reference-value-sources.json': {'after': '7f0fe4f0b20208fc80d601e48b6a238299473a89d9d08958d4ec11ef6f2fbe1f',
                                                                                      'before': None},
 'skills/waapi-skill/references/semantic/2024.1/query-related-output-sources.json': {'after': 'baf5ed934b1d95666eb8bdff386d7f03c511a793199c7ce0226d39aed9a729a5',
                                                                                     'before': None},
 'skills/waapi-skill/references/semantic/2024.1/query-return-options.json': {'after': '854d9da6ef588bac87476abccf346c86d83902685a418e8de0363e5db7d3346f',
                                                                             'before': None},
 'skills/waapi-skill/references/semantic/2025.1/blend-assignment-source.json': {'after': '6c721df2e08a5e4e3232ace9105d0e4baa481a47a77c0af4a360306e6422d2af',
                                                                                'before': None},
 'skills/waapi-skill/references/semantic/2025.1/manual-marker-construction-source.json': {'after': '44c59e95afc4be534b063298333dad257c49784aaeb9344dbdace2b0ec49fb2f',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2025.1/media-pool-database-sources/ak_wwise_core_object_set_example_creating_a_media_pool_database.html': {'after': 'de5de9c1908f5dbcd810714bb1f9dc693bb05764da85a1cdd0493cc75bc5d708',
                                                                                                                                                    'before': None},
 'skills/waapi-skill/references/semantic/2025.1/music-playlist-sources/ak_wwise_core_object_set_example_creating_a_music_playlist_container_with_segment_and_playlist.html': {'after': '64c0f930c51ef7dbc99ca6ac9899eec48b972195c25de439927dab71456f4794',
                                                                                                                                                                              'before': None},
 'skills/waapi-skill/references/semantic/2025.1/music-playlist-sources/native-lifecycle.original.json': {'after': '4311c617f6588d7547b80c86e02ae40a6f55820dbeeacd8ae77fc873bdbce6c8',
                                                                                                         'before': None},
 'skills/waapi-skill/references/semantic/2025.1/music-playlist-sources/native-readback.original.json': {'after': '1b65f7cbff6ecd83fb20059157f6b78b70eef375eca0e1bc15ae8a067e0a47b1',
                                                                                                        'before': None},
 'skills/waapi-skill/references/semantic/2025.1/music-playlist-sources/wwiseobject_musicplaylistitem.html': {'after': '89f54369c93c47b6f5ce2262795c1c629d0ebdf459737507f7a1bbcd6893fda6',
                                                                                                             'before': None},
 'skills/waapi-skill/references/semantic/2025.1/music-transition-sources/WObjects.xml.gz': {'after': '827f9e61bcd510c153ea0346fa6b313b7172aeb0427ac6dc590feaef0ab0d280',
                                                                                            'before': None},
 'skills/waapi-skill/references/semantic/2025.1/music-transition-sources/ak_wwise_core_object_set.html.gz': {'after': 'c9f868a236dfae1df38f26813b79048edfcc1c4ee33fbc44f14a3e0842353804',
                                                                                                             'before': None},
 'skills/waapi-skill/references/semantic/2025.1/music-transition-sources/source-contract.json': {'after': 'c445803a07738f4c83bb3eb16fd20a4dbbcfc3675678800a4c95b067db63fde2',
                                                                                                 'before': None},
 'skills/waapi-skill/references/semantic/2025.1/platform-copy-sources.json': {'after': '55406d4209c9d06572a49666d3e800e5cd63ec810bd6bd5e4ea61bedeeaa780d',
                                                                              'before': None},
 'skills/waapi-skill/references/semantic/2025.1/playlist-slot-name-native-boundary.json': {'after': '8d7e60dd8531958037214c0789c3a3a8302da80d72c499ba6773af9f0f63eb0d',
                                                                                           'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-context-sources.json': {'after': 'da872a826b37b8debc39a0ab0866277fa7632fac4d9d6f4a0b1dd2da61e63c85',
                                                                              'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-field-condition-sources.json': {'after': '396b40009f6d6de95f1e2c30707f97ad57e5e076b744ad3979a8f0f4f97c4b1c',
                                                                                      'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-function-sources.json': {'after': '01ae8e2ad2efc5a7833567875ea1b4383e6ec623ad2a3e2fcb9db32b03e66178',
                                                                               'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-list-output-sources.json': {'after': '29e702548656b07d4a39d04a751b52cd5a214f482d9d0a5aa41649341f83501d',
                                                                                  'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-local-list-bridge.json': {'after': 'a304dddf1b293206602071895256c1f2ec1cc957038ce0ef9c8eab899df5765a',
                                                                                'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-marker-records-sources.json': {'after': '2559d80fd20099e51dd31c0ef0322e3b5fde628b952adf8f9e3c9790e8a2892c',
                                                                                     'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-namespaced-property-sources.json': {'after': '90de79f3b256cac8ff7ccf5af09e1ecdd912241928f67f934b09b300bac629ec',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-randomizer-sources.json': {'after': '434519f2a54ca4b4339799fda2df6d07708f438a6e72d9cb514a33294ffcfd67',
                                                                                 'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-reference-condition-sources.json': {'after': '5f3460a8659d4efa8bdede2c564be14def3e91b21f3e46afc6413fc15df83375',
                                                                                          'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-reference-value-sources.json': {'after': 'e5ef8fbaf8256a78217e2227fc1dfeaa2149dc3caaa3526e9398c7fd1cb63648',
                                                                                      'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-related-output-sources.json': {'after': 'cf440b96ac5851cb30effa37ff44edcd05b3c2c1720385c461bea53fa81189cb',
                                                                                     'before': None},
 'skills/waapi-skill/references/semantic/2025.1/query-return-options.json': {'after': '854d9da6ef588bac87476abccf346c86d83902685a418e8de0363e5db7d3346f',
                                                                             'before': None},
 'skills/waapi-skill/references/semantic/2025.1/semantic-builder-import.md': {'after': '0c7ff5a76ee250de9169ff8b8012400d04aff29456811ddb59ba1abfc4e7e878',
                                                                              'before': 'f126c4fd9ab8f94bafc0d2db4cb8a6c947602f569a84cd9174a00473d5b1b9bb'},
 'skills/waapi-skill/resources/manifest/typed-request-surface.json': {'after': 'b98bc190245da02e443ab4b2f24e66cb2c9d9830b2f1d883fb769e9fefc09571',
                                                                      'before': '02ae01f17c25e8a291f6492c877e6d10c3d96867033611d96627cfe6aae5169a'},
 'skills/waapi-skill/resources/metadata/2021.1/installed-owned-list-fields.json': {'after': 'bdbc5b33059de0b86bb8f1fd8b791a8dd738a03546e241fa4a9e7f6b222e4e6b',
                                                                                   'before': None},
 'skills/waapi-skill/resources/metadata/2023.1/music-playlist-construction.json': {'after': 'd8fc7312ba7cc229288f93e5cca4ca7ba41bc8af75783658870d6fd57f3b30df',
                                                                                   'before': None},
 'skills/waapi-skill/resources/metadata/2024.1/music-playlist-construction.json': {'after': '5c4cfa03e22d787661f76c2da9e1cfbdde7b03980a405bfc0deaf67559c92118',
                                                                                   'before': None},
 'skills/waapi-skill/resources/metadata/2025.1/music-playlist-construction.json': {'after': '8a745145cfb458d4f3afc8f4f62db1df033fe58a5c2a71e539c26dd592b413f1',
                                                                                   'before': None},
 'skills/waapi-skill/resources/metadata/action-constructor-sources.json': {'after': '4f8384611ceb30c4d7c0c6a4cab7ce3b7160e363b251066cff831fc40df335aa',
                                                                           'before': None},
 'skills/waapi-skill/resources/metadata/control-surface-constructor-sources.json': {'after': 'a0839b455f66074a418ebd178bf6cf4823396970b95acad5f7013cb5132e1e02',
                                                                                    'before': None},
 'skills/waapi-skill/resources/metadata/owned-list-mode-sources.json': {'after': '69481b4fa1b1e51842599f86eaebd598a8a62dffceaba21eb16f5ae4a4598ab8',
                                                                        'before': None},
 'skills/waapi-skill/resources/metadata/reference-kind-sources.json': {'after': '53266121afdca23ca92eae6dfc591c47ac2416edb026edae70831abf49c8134c',
                                                                       'before': None},
 'skills/waapi-skill/resources/metadata/reference-master-bus-applicability.json': {'after': '3a2b4c520ee5dcd440abe0fce5102b337c42a567acaa09d5a80d985330f7b245',
                                                                                   'before': None},
 'skills/waapi-skill/resources/metadata/reference-master-sink-capabilities.json': {'after': '0c2567a74adcc562b96bb02faf9ad28ede9ef239d768b1b112bb405d6adbad34',
                                                                                   'before': None},
 'skills/waapi-skill/resources/metadata/saved-object-constructor-sources.json': {'after': '14c4b6c51c097ed9754f62b598332ba6c0ad4745d66986fbfe77511c5d4433b1',
                                                                                 'before': None},
 'skills/waapi-skill/resources/native_surface_policy.json': {'after': '258877cc25df78df2f3418459720d823730eee7b5336d8349ef5c1b4345be810',
                                                             'before': 'c801af08f4a4abd37128c2f343454c6b32877d46921efb0aed26a9fbba3ba641'},
 'skills/waapi-skill/resources/semantic/2021.1/project_default_language.json': {'after': 'c90472edb5cc4819a1f032729322dd2c54ad0b364059ba155b7289c77827b67d',
                                                                                'before': None},
 'skills/waapi-skill/resources/semantic/2021.1/project_media_storage_default.json': {'after': '21df2e3df93c6d46857b9951c7c11a876055de1d5a6d8cdce123cde8f6121c61',
                                                                                     'before': None},
 'skills/waapi-skill/resources/semantic/2022.1/project_default_language.json': {'after': 'c847e414fcb5a47eb197d8cd1c4076e3dc38faa2557c3f6fdfe4c909e718b411',
                                                                                'before': None},
 'skills/waapi-skill/resources/semantic/2022.1/project_media_storage_default.json': {'after': 'f81526ac8e4189eab17ae8fadd4205ced42bf74bedd7d3aa67b3b50a0c3a6708',
                                                                                     'before': None},
 'skills/waapi-skill/resources/semantic/2023.1/project_default_language.json': {'after': '796adfc435da565c1706b582414649372504fe7822c65b89f0bea14809986658',
                                                                                'before': None},
 'skills/waapi-skill/resources/semantic/2023.1/project_media_storage_default.json': {'after': '061392be800ad672a17dc6800bc5862090f1444c8571616060ba887af77ce5b9',
                                                                                     'before': None},
 'skills/waapi-skill/resources/semantic/2024.1/project_default_language.json': {'after': '4277dc478d043cc5072b9b82c95ade9d8a774f4d8e7a7403c57d42d296fc896f',
                                                                                'before': None},
 'skills/waapi-skill/resources/semantic/2024.1/project_media_storage_default.json': {'after': '4f0df78e8b34ae2fc2e164196ea4baadb4ab76bbc6e70f762ae809b238e25ff4',
                                                                                     'before': None},
 'skills/waapi-skill/resources/semantic/2025.1/project_default_language.json': {'after': '9724d29cf96af56e9c29240bfa973686f0093880478ecb734fd752a0a8620e7b',
                                                                                'before': None},
 'skills/waapi-skill/resources/semantic/2025.1/project_media_storage_default.json': {'after': '6430a50abb554ce0efa236de3c30bb0bae290ffed4fc4e77722324290add4157',
                                                                                     'before': None},
 'skills/waapi-skill/scripts/gateway.py': {'after': 'f5c7f537836a4483070085a07fd58336dc54f0d14c9891480b664fdf556e1d04',
                                           'before': '837ee2edee8e40d5cc9cad87cba1ff1c536ccb61eb9a5c1119581f0f0de30ab4'},
 'skills/waapi-skill/wwise_waapi/action_construction.py': {'after': 'd61a807d6ad0a16c6b56bd341a90f85da247ad44c9e0517718317520ebccb19d',
                                                           'before': None},
 'skills/waapi-skill/wwise_waapi/anonymous_list_construction.py': {'after': 'a177b225e60e96f8a3389cdbc415f4defdcbab63e4d88d397f8a9811991c055f',
                                                                   'before': None},
 'skills/waapi-skill/wwise_waapi/audio_import_business.py': {'after': '3e7e92a19dc4d2ec4170cb536d98986e3b9b3643a0bc6ec0d9b5bd4f9d8d36fb',
                                                             'before': 'e70d09d520b08d275bf56af8718af40aa9733b2fc9e9b405f84229bdba39bb32'},
 'skills/waapi-skill/wwise_waapi/audio_import_business_contracts.py': {'after': '4ec0939215f05f340ab4934640f3eecaff7b72ae3b39ab6e9003b94cb3b3b8ce',
                                                                       'before': 'd06a04e38e224fb32301996c4aa0a4cf5ec46f75f1dcded354d64bf3ff87bd7c'},
 'skills/waapi-skill/wwise_waapi/authoring_launch.py': {'after': '61a147411072bd0a1f3176f80ae9b2ccaa53e0d3a9f79da4e10c26fff9144c6f',
                                                        'before': '3e8ae023854f8de3118d512ab717f477a8236014ab046531f1e09c0a11c62cb5'},
 'skills/waapi-skill/wwise_waapi/authoring_layout_business.py': {'after': '31fce6ac8c7f45c7f161f98b8adf0c4aee7571c063c9e20261209c869f743d4d',
                                                                 'before': '931fe9fc2fd7c8d075b59fd13ead2f1de6c57d5d4e6c6f5221e1a6a74f259cfb'},
 'skills/waapi-skill/wwise_waapi/authoring_model_business.py': {'after': '4a87af1714d98cf4308301074e76b082830d59638bf1cfc6f5e3c0d175f49d33',
                                                                'before': '5379ed2ffb444591dab7d0c8561de40c76081a951689528f378bf896a4e8c9f6'},
 'skills/waapi-skill/wwise_waapi/blend_assignment.py': {'after': 'ae18dc98be570849cdb44c256dbe014252f0ca45203d4ae7ce698fb4bc485e54',
                                                        'before': None},
 'skills/waapi-skill/wwise_waapi/builders/metadata.py': {'after': 'ac58211914543aca3e3fdfdbe77095d2b8179f53091bb045fd5cf3452aea1cbf',
                                                         'before': '97d23609944be401d1aaf62d63ceb3613008cabb3e83d3f29d452c091ea26343'},
 'skills/waapi-skill/wwise_waapi/builders/properties.py': {'after': 'cf2fbbaf51b5fcbf56baccf19980df72ec8a4ad716a1e539f1e9831f5734e858',
                                                           'before': 'e4a966a62bb680c37224a29a70bba388876fa7c460e76dbedca92c3a7bad9577'},
 'skills/waapi-skill/wwise_waapi/builders/schema.py': {'after': 'cd11309c557b68ea7bcb7d82c2bcbc1a448d08f8e283fab50a0424555fc4f8f2',
                                                       'before': '4a1ac5146edc65eb8e58defd689051f79a198bafb2d5d2134d912bd9a862fd6d'},
 'skills/waapi-skill/wwise_waapi/builders/stable_reads.py': {'after': 'ea1c39a5480afc5720f99a0acb85015c7c7d028d8ee53eb1937ff079fce9d7d8',
                                                             'before': '74e37957692c6748f6c7f8f6c4dd795dc31c10b78ba0d30500a90d59b818412d'},
 'skills/waapi-skill/wwise_waapi/builders/switchcontainer.py': {'after': '93c460c0ed55238c01b8845f6f25a9b7b3a6b5a82fa2de6b6a17ecf16a2f0397',
                                                                'before': '14d1171d68c904946fddf9f0487721e460b616ccf2869ea73c299bbaac06e8da'},
 'skills/waapi-skill/wwise_waapi/business_adapters.py': {'after': 'fdf81bd83017ff29b8b451152795680f5454de24ddad33842139eea5afed5500',
                                                         'before': '1e4d5ecf0a16de4459543bde1297b7a237f9b1e02363f4ed0ff9eb2489e6acf7'},
 'skills/waapi-skill/wwise_waapi/business_declaration_state.py': {'after': '0d7720ca41ff9e497c620c30502f8650a3344c065d629e4bc3a2e4cbdc8a121c',
                                                                  'before': '0c913fca1120d114c2268d052fce368d304c6588f1e1aff5872019dc8363f0a2'},
 'skills/waapi-skill/wwise_waapi/business_declarations.py': {'after': '8e3988f7111099d0680a290663a682f59f4e3e386496354178d9a9d69c04c229',
                                                             'before': 'ea3d22b2c0c9eca269916b12a4dcaf25fde42cba6df77e7d5887b5eb0423d9f1'},
 'skills/waapi-skill/wwise_waapi/cli_console_business_contracts.py': {'after': '15614b750e580996dcf25a91d5255f742a6e8ff448b2ee47eb827d07bbc90999',
                                                                      'before': '79f3d510a26539b703cff4118baec4adb185e9d87e86ecd7f7747315f51795fa'},
 'skills/waapi-skill/wwise_waapi/compound_undo_business_contracts.py': {'after': '3e9e302e28610a6b296fa6cfe6a463d8f7e1705ebb4aef3992cd8575da8b31dd',
                                                                        'before': 'ed411a5adb4903227062ce1b76387d80a8cfe0d2c2c1f0d255526ced6c25d377'},
 'skills/waapi-skill/wwise_waapi/console_media_ids.py': {'after': 'e65404636b837e3f3a255c66a1283196b0b694ed37c7aae0fb540b879111a888',
                                                         'before': '259c31c10e4bc44176349316dda674367888a82a7a5f748fe2601ab2259afdaf'},
 'skills/waapi-skill/wwise_waapi/console_platform_copy.py': {'after': '7d11e3d52d9c74b5cc3ae69b6f9fa6c2d1289ca650ff7710a4921400763faf64',
                                                             'before': None},
 'skills/waapi-skill/wwise_waapi/console_project_operations.py': {'after': '67ffd474726e80ea3b21e8c1561dbe330f23c1fa8f7ff73fa1f9c19fc8ad75ee',
                                                                  'before': 'c577b798ec800c85c59fc210783c0e3b7e696067b86079b025f6f505964c834d'},
 'skills/waapi-skill/wwise_waapi/constructor_inputs.py': {'after': '9f24d65d41fd62e86bd21ea7b1b8511b2a13aa0c13d21159c56dcb0b4c1922c1',
                                                          'before': None},
 'skills/waapi-skill/wwise_waapi/control_surface_construction.py': {'after': 'db975c21bd063e2c124e10854abdb627768fcf005b5b66d480ba50b96c871e8e',
                                                                    'before': None},
 'skills/waapi-skill/wwise_waapi/conversion_plugin.py': {'after': '3da97e1ab4114d02870991750bbd0f6bf42bd728cfee9e6ce56145e4e9ed3766',
                                                         'before': None},
 'skills/waapi-skill/wwise_waapi/core_business.py': {'after': 'cabc1d46de13fbb3f7700a348f9441ecc0cb9d0ebca3a754dd014b56bd17e09f',
                                                     'before': '62e361dd638a53af8b62455ec5c414bff7e5e9a9fdf6a2a419edb44a6f970bb6'},
 'skills/waapi-skill/wwise_waapi/core_business_contracts.py': {'after': 'c527ce24a9e33478808fa60309f166b191e265892cfcf312e4665fbb7d274ffa',
                                                               'before': 'f9fe51a42199b137420dc906e3ceea57a64e6f3d302940887747d7616f61d61a'},
 'skills/waapi-skill/wwise_waapi/creation_observations.py': {'after': 'b9ee038d56b0e395d16ff9b4eb386023695164794b6872d0efb9b5bc85b45392',
                                                             'before': '880b3e71f6834702b4a4614f8ed3ed4f3b67d0cf897dcf059da9c33c5dc3e3d2'},
 'skills/waapi-skill/wwise_waapi/derived_reference_history.py': {'after': '7f052e015da34e5b661f950e7512c328e79b760e68d445cd361d849f6884ecdf',
                                                                 'before': None},
 'skills/waapi-skill/wwise_waapi/documented_list_fields.py': {'after': 'ac7a5155d51874f85498c470dab71fc4d2a9cd1de7e611d7b480c767055257c2',
                                                              'before': 'bbdaf4d69c02ea9dfadaf7b95e4ed8627484493eb284aca4613751d770bc284f'},
 'skills/waapi-skill/wwise_waapi/edit_history_business.py': {'after': 'c25b688772384c663556f760c6a47b05ffd99fa27e60fca4a2ec6c8e1d305d57',
                                                             'before': 'fa6dbe710055250fb5c84cc51d447ed9965f7b7efede4571b6936f818546bd3c'},
 'skills/waapi-skill/wwise_waapi/host_ui_debug_business_contracts.py': {'after': '02baab67b2767f11bfaf59a9bb493f4e8835c55d94650f7048ef02d48c5caefb',
                                                                        'before': 'ce27359dbfb4414bcc9b96e51c271036206f773e78ee22dc8b3b52fcec56da33'},
 'skills/waapi-skill/wwise_waapi/layout_blueprint.py': {'after': '65f489b715971bfedd724f68760b5ab3fb2ea403384f6fca1474247ad3d52f56',
                                                        'before': '1547bedb5439bfbbb9b2b549c448cd2e64ee81cb27ae7aceae3a2e8fd82892af'},
 'skills/waapi-skill/wwise_waapi/media_pool_database.py': {'after': 'eff48f7a6403c0e11807cc35c2d611ac7200414a8545d3d999d9962653d3675b',
                                                           'before': None},
 'skills/waapi-skill/wwise_waapi/metadata_condition_contracts.py': {'after': 'bb822135646976e67575e02d49c6682f164c5060968de2767390cc561b3b1390',
                                                                    'before': '2ed302c961f16388a0e8e3d32d3c20440c6cd03f3bafd0bcc4358403f91421b1'},
 'skills/waapi-skill/wwise_waapi/metadata_plugin_placement.py': {'after': '4abcda0c0d9856df1f2efb2d97bbe079ec634ce0d1474debf63e6cde99e19521',
                                                                 'before': None},
 'skills/waapi-skill/wwise_waapi/music_playlist.py': {'after': '3b45e8dca7934c61d08541aeab1ae3c3e3b2d0bdf04258e249cc0b2ce632be72',
                                                      'before': None},
 'skills/waapi-skill/wwise_waapi/music_transitions.py': {'after': '475f6086162f3a99b312e10cc40481d1b7e61cb7350c195b5dc5517c1c641726',
                                                         'before': None},
 'skills/waapi-skill/wwise_waapi/object_capabilities.py': {'after': '00659f9b2a51bfe8f058010a9077f57c5c0bb2a0c58168cf3ebb3648dcc6d509',
                                                           'before': '75e8605fd1e435ea5df6b152a36d1d9adeaca197ab2dee2454bc8caf071374c1'},
 'skills/waapi-skill/wwise_waapi/object_graph_business.py': {'after': 'c58e3eae8673ffb1e73dc556de0198c8bb00c400820179f24b3461d3ed45f4cd',
                                                             'before': '17d96c6f8a663cd4d8bdf3c34717b958ae16ebc36c88ceb59c3f18937389dcb7'},
 'skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py': {'after': '9dda16f652f9d04e083d20ae2adbf8d4bd7be36d43ce6475887bc27edf80b577',
                                                                       'before': '487422db65a32cedb157a4e5d3cd5865688a4e5dff3b529a6e95d8250792882f'},
 'skills/waapi-skill/wwise_waapi/object_graph_paths.py': {'after': '346758989e4be60466d75ece2b6ded8956ddffb6db7bb4911df63e0d7ac2d0e4',
                                                          'before': '82ffbdaa9da088b790d5fa255508b5f6058ec8a47d8b14afe077595d710b89b7'},
 'skills/waapi-skill/wwise_waapi/object_lifecycle_business_contracts.py': {'after': 'f1f14d66cf58fc04eed91e94b4fe655a3d0aef3a4778374c1d94e86d4645ad02',
                                                                           'before': 'f6f8a4c343cb4b223566f89473be618ec3c2305849ce5023315563a05d9d32d9'},
 'skills/waapi-skill/wwise_waapi/object_metadata_business.py': {'after': 'd6b3de49b4461c376e1e014e2145893279b9abe78f8406743d6918539c95d060',
                                                                'before': '616d6e63fb35d9615cf8b6dab3311ada8caae8a64ca85c2d04044e54f35d9bdc'},
 'skills/waapi-skill/wwise_waapi/object_metadata_business_contracts.py': {'after': '297a6f2a9d06d34d12fe8c47022ee286a8d4b88843f35b41137821a1b7d5fcd0',
                                                                          'before': '8d6ad65d41bc98cb39f5f73e29d600f3d73be6fba0fa4ad631e1641764b3be18'},
 'skills/waapi-skill/wwise_waapi/object_query_active_source.py': {'after': '1ff7337a67ece4c9b7df090e0753e43be04ef7cee030b3a77fc53c018d503ceb',
                                                                  'before': 'd325020b2ac79c9fc32618b9b33a29bb52641f392244300b57f60192f6c66772'},
 'skills/waapi-skill/wwise_waapi/object_query_contexts.py': {'after': 'ceb9f8e563e249ea51af13f627d50d81a7fd53a8636b035716eef72cb0953bba',
                                                             'before': None},
 'skills/waapi-skill/wwise_waapi/object_query_field_conditions.py': {'after': '5a1c23509e6cb01ded82b792ee22e0872af79ae43269aedab211b83baf75f1ca',
                                                                     'before': None},
 'skills/waapi-skill/wwise_waapi/object_query_functions.py': {'after': '94af00791019e4c7189b113da0370fff79d0569c38d47f59bd114e435de5daf0',
                                                              'before': None},
 'skills/waapi-skill/wwise_waapi/object_query_local_lists.py': {'after': 'a0ea295981f10c7d954f1628ad2f13b3fe569c0c566da67b00a67acf39ea43a2',
                                                                'before': None},
 'skills/waapi-skill/wwise_waapi/object_query_outputs.py': {'after': '6909cf0fd21d66c06b3e5963806fc0c738046134eaaf6dd1dea4ae0c6464b36b',
                                                            'before': '8211f64a3e5dce149f37de1b75f2c89bc63698a8b5daa4911f3c11d0e2eb11d2'},
 'skills/waapi-skill/wwise_waapi/object_query_randomizer.py': {'after': 'f190ab600442bb92df85ef338ad8e0eab533268e4ee938bff8fd9cefca75e56f',
                                                               'before': None},
 'skills/waapi-skill/wwise_waapi/object_query_related.py': {'after': 'a41062d43d8b503dcff2e2b4e413492d0ae85eae52f00a10923ad1848a9a609e',
                                                            'before': None},
 'skills/waapi-skill/wwise_waapi/object_query_related_lists.py': {'after': 'b0c3c44da7e0f23b7f30f9fe1b1d814d61fe2a066adc01be87b513cc01f11389',
                                                                  'before': None},
 'skills/waapi-skill/wwise_waapi/object_query_related_metadata.py': {'after': '8d4c3601c3cf733b78d99747a54ca4f3e2803b3fc5e319c90cfbe6444b67a61d',
                                                                     'before': None},
 'skills/waapi-skill/wwise_waapi/object_query_related_runtime.py': {'after': '699c8ad77845fcb6345c2778de4dced5a383e84cb15138779bd9b722983aace6',
                                                                    'before': None},
 'skills/waapi-skill/wwise_waapi/object_query_result_pages.py': {'after': '530f282cf7920414fcac4dddb3ebe16ea86e028c387a6b891e0cd4c672c054d7',
                                                                 'before': '633ab098d8ba24038741a5fe9c45f4ea03d7f0482c098ae67f3f0f2e3b772b83'},
 'skills/waapi-skill/wwise_waapi/operation_import.py': {'after': '07b70781e73061320877f1d854bf27ee08269ba1dcd70e119b1f12fd7b6bcbdd',
                                                        'before': '8c5e646a7cf0af22ef3e5835c5fc51b850d7f7a50d92c0e378c6c80119d02882'},
 'skills/waapi-skill/wwise_waapi/operation_object.py': {'after': '73599eea347430340950db5c753700db24410e6a85877f419101a8c84307c080',
                                                        'before': '606efc27030d81559adba6f5bf0aa827aed4ff3c4ef6c5aa666f4529a15db29e'},
 'skills/waapi-skill/wwise_waapi/operation_plugin.py': {'after': '389eab03780303a3079f252c40d9ab817812054feb8b3be21d44b0df93de419c',
                                                        'before': '15f1358c0eda3152116ecc4f7ea7519facb11386e43e8d7dbcd69437a6f15b7d'},
 'skills/waapi-skill/wwise_waapi/operation_registry.py': {'after': 'cb5afa5c92d5074fc93b4875a166c3120ab2c3887d97f33799ecc21120c6e5cd',
                                                          'before': '3d619275df7106ac14bf75f6a6f221ff5ca01e2417850d4509fea13698a4718b'},
 'skills/waapi-skill/wwise_waapi/operation_soundbank.py': {'after': 'fa910d40c2e88ecd56295ae5c56faa010680acddf0542edbcc6fb55cdfb07283',
                                                           'before': 'cbc517977a4d9a3b42cfb051631a62bc40977da2eb4a6c81d26c01bf57cea044'},
 'skills/waapi-skill/wwise_waapi/operation_tone.py': {'after': 'd8d28bc40021f7de7abe6690b417153088e36fba37308e0a78c578f8abaee120',
                                                      'before': '231521ce3931ed2f1cbde931ef21e8db4c582af2718f38f4765a239c5e908550'},
 'skills/waapi-skill/wwise_waapi/owned_control_inputs.py': {'after': '5c5d187549b48b41edf13ab32a543ffeb355fe586d4a43a68e06422a2b221716',
                                                            'before': '3f0e642025564ccd501cc3e07909b80372eaa36ced2b1c3aab46a215282b162b'},
 'skills/waapi-skill/wwise_waapi/owned_result_stages.py': {'after': '4d718fccf4d027ec439af06cc6238559c22b5a8bed47a78916395ecb0e3f761a',
                                                           'before': None},
 'skills/waapi-skill/wwise_waapi/planned_references.py': {'after': '1d0539d23a7ea4f027d8e20c4f11dcec8e3835cf9c26397392fe879e9d5bd715',
                                                          'before': '6455105f7c25923c360b68f5883e64d5b8927dd904b621597e8d7150bf1c9401'},
 'skills/waapi-skill/wwise_waapi/platform_paths.py': {'after': '0e4f592cc866a6620eff01304859595d0f0b560a5bc7c1c7dc00b47c663eaf60',
                                                      'before': '00149d5c4213da5d76d748ef21607051677f6364625853e7838c75701693a527'},
 'skills/waapi-skill/wwise_waapi/playlist_reference_conditions.py': {'after': '1b1b8288aa6969bc99539570287da40ae10f2a27d85a21d1081b608625953088',
                                                                     'before': None},
 'skills/waapi-skill/wwise_waapi/profiler_capture_artifact.py': {'after': '12ee2ebd89a17d75fce0f126da57a7b1f001dd49e39e8a45363dea598f77ddec',
                                                                 'before': None},
 'skills/waapi-skill/wwise_waapi/profiler_meter_objects.py': {'after': '7f11333651f5671b108585b5f50b21310cc3018102700c2635f4718ae4893341',
                                                              'before': None},
 'skills/waapi-skill/wwise_waapi/project_setting_business.py': {'after': '82d8bf1bf744264ca0da5d294f402f4d3b557c683c101cda7d8091bfbed14152',
                                                                'before': '87e116602cdc4c1b7ad58f6bf4405c4dd6d2cdea4c9e353e8276b7bd9cf84c70'},
 'skills/waapi-skill/wwise_waapi/project_setting_business_contracts.py': {'after': 'a8e459df9ff091446bbf6cb1a05e8a273761fd8f8256392e5d668c172939cc09',
                                                                          'before': '5b94b93d61193b1ba69fc06e4d0bc1edee246854b2328e0cd13135ce2ff1df90'},
 'skills/waapi-skill/wwise_waapi/reference_applicability.py': {'after': '2c1eef23f7f4d0b7535fea4fb883bd55cf9242df0e9861411c996cc14e2ed6ee',
                                                               'before': None},
 'skills/waapi-skill/wwise_waapi/reference_kind_evidence.py': {'after': 'eee039338379022e2935d5acfe7fef8ca5ca601abe10bc14b7129944e57d2065',
                                                               'before': None},
 'skills/waapi-skill/wwise_waapi/runtime_inspection_business.py': {'after': 'dcdfdaab82e8bd5faac9d762bd08ee917067dade291594c34e125a67be570712',
                                                                   'before': 'ee10e4ab4c1f9b6214286d70addc03ed5ed85f3864461cdc36237d6cfd731390'},
 'skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py': {'after': '14fb6f062baf80566961b9304eff1d13b89fdab5afaa731910261bfcfbf02594',
                                                                             'before': 'ff19b8517bd8bb4325fccfc3824375d5d4f56a340c7a936ef3c3c943820e4c46'},
 'skills/waapi-skill/wwise_waapi/runtime_log_effects.py': {'after': '1f03a038ba77a0ab62fba014329eeeb6962de86902f14fcb60cbfb4de19dea00',
                                                           'before': None},
 'skills/waapi-skill/wwise_waapi/runtime_log_observer.py': {'after': '105fd70d805a9c4bae9e72ab8c436af436e9f3241c48a6638ff33ec2d50a3582',
                                                            'before': None},
 'skills/waapi-skill/wwise_waapi/saved_object_construction.py': {'after': 'd1a7da145b00c0c3360fd08b363b31102f73ea29e1749acee67ab2cf4e39f605',
                                                                 'before': None},
 'skills/waapi-skill/wwise_waapi/selection_guidance.py': {'after': 'b311c0334783e180ff85b17d3539518356ef466af459d66a2a51dd668506133d',
                                                          'before': 'ea220a6f814a44002c1d25d22936dd28f2707d6dcc7f644a297afbc7206f22a3'},
 'skills/waapi-skill/wwise_waapi/soundbank_business.py': {'after': 'c37058559c63051bc4a167c93635351a01db81d7564f59569411a5b6622989ec',
                                                          'before': 'a4f6e0938b6167420d5e58fb5fdcfcc97c1770770dfb0ef00233c18520a4c056'},
 'skills/waapi-skill/wwise_waapi/soundbank_business_cli.py': {'after': '3ff1d1cc2ac16611d98fbb0b68a7370c7fb7380c939a55c2f9b716ff393a5a69',
                                                              'before': '709e0be0ba845f882e09962ab2b330308232bdf469ba35953ed18adee6f5bf0f'},
 'skills/waapi-skill/wwise_waapi/soundbank_business_contracts.py': {'after': 'ab8fe493deb40548e6d385d0201a257a4275bd9c8450df61ef30e6eccabdbe4d',
                                                                    'before': '68cff30fc77a78c220fdcd08c6051fb35e08409f3f01e5a322d06d91a96ac6ca'},
 'skills/waapi-skill/wwise_waapi/soundengine_business_contracts.py': {'after': 'ed4378b06a411d428b2a231c0ffc6c6f42377c6de10cd16b8671ba692388c0d6',
                                                                      'before': 'b851a92ba25e3509304a99ba2912dc456564ff1d98cf9963cee8ccd5d8268070'},
 'skills/waapi-skill/wwise_waapi/soundengine_object_returns.py': {'after': 'e1e35920af7a57248cab8449ddf3c5782ed74f60e7f16de77dcc5c1f1a57d2bb',
                                                                  'before': None},
 'skills/waapi-skill/wwise_waapi/soundengine_related_outputs.py': {'after': 'ca397c5e72f4912fe4d123081b4be53bd8289f23e1a0b1eed13829c23d571f7e',
                                                                   'before': None},
 'skills/waapi-skill/wwise_waapi/switch_child_context.py': {'after': 'd28389f2492a526ea9a608db1a44e2f12b44bbe57c5f38d51b765c9866fa5f96',
                                                            'before': None},
 'skills/waapi-skill/wwise_waapi/switch_child_history.py': {'after': 'c83d3d0206a535d540502453c35fad4dbfdb8ce8d2bee839eabab7e29343a6a8',
                                                            'before': None},
 'skills/waapi-skill/wwise_waapi/topic_business.py': {'after': 'a28e2a96bf89bc09e5a8401ac2c0728a5ce60412041c563f0bf030e46ff7e6bd',
                                                      'before': '1e56daf8efb678b3b582b335c2b5c567ecf673de4427421e5ff4f1aec2739648'},
 'skills/waapi-skill/wwise_waapi/transaction_runtime.py': {'after': '44e7e2e62afbc0fd212b96d5e4b06f0ac56c7b444acbfb7987590319c6c69c8f',
                                                           'before': 'eca18101c572eb89c6af494235e7957602a4851073db4c99430f6086a7727baf'},
 'skills/waapi-skill/wwise_waapi/transport_action.py': {'after': 'f1dfed2fc9e2697d37e022262d440a7d3ace7005d4f5e57b939d7550d7efa2a5',
                                                        'before': None},
 'tests/conftest.py': {'after': 'c9f13bdfb2450c025726c606b4f5d43b51d23cd165f5becc11a533bb5b561655',
                       'before': '4737a4fe3c6352eae705f837b2a667a47e0a61c221b9c9b86a535b48fe5c0a55'},
 'tests/destructive/support/audio_import_acceptance.py': {'after': 'f751b916c9387e334b860529495b9cc98563bbad05dd002aee659dc92902692c',
                                                          'before': None},
 'tests/destructive/support/authoring_batch.py': {'after': '8b16b061b8ff402a400358155a4e2f54fb980feba2b9b113872b96510c472a7b',
                                                  'before': 'd82bd3b36fa06f2a2fe30971f1c323523a4b41cfa638832caba069c65b8195aa'},
 'tests/destructive/support/console_log_diagnostic.py': {'after': 'd1539bc47f9253f2a76a6738c51934e5c6e2a0eb0c2d4091d584c62516e594f5',
                                                         'before': None},
 'tests/destructive/support/console_log_peer.py': {'after': 'd989e32c1ef951afdf4f9c9baed05427d63bf7b8c6c6529666695ecd550f00a3',
                                                   'before': None},
 'tests/destructive/support/console_profiler_probe.py': {'after': '08b8ce7f98c62d6cc033b2812a2ed368842bd5fd510f34e74c72e8243378ea22',
                                                         'before': None},
 'tests/destructive/support/console_project_acceptance.py': {'after': '29eda8c611f1207cebee73210ca65dd0a219cc7c6f78c93958376af8c0b8d7f6',
                                                             'before': None},
 'tests/destructive/support/conversion_plugin_acceptance.py': {'after': '295da1f8269a1f5bb7e83913e3c7e63fb6dfaa762e1575106e99967c516fffdb',
                                                               'before': None},
 'tests/destructive/support/integration_demo.py': {'after': '844bc6fb081aed4aee593d27ed06e886771c442927729459d284b3f523cda546',
                                                   'before': None},
 'tests/destructive/support/language_registration_diagnostic.py': {'after': '60b3fc191c5bac2b8c6338a5444733bfe012566e30a3786188c2142fe5f48b12',
                                                                   'before': None},
 'tests/destructive/support/layout_workflows.py': {'after': '8a7e87b48a60da2c53223543d294f8a8f747738a77ddac505b789573108bab8d',
                                                   'before': None},
 'tests/destructive/support/loaded_media_probe.py': {'after': 'a325daee984aa8a70f89f7f2ebf2dbbd84eda081104f5bc2abd03f306e23502b',
                                                     'before': None},
 'tests/destructive/support/meter_spelling_diagnostic.py': {'after': '18154d530afd8c85d191ebc24d1152bd359c6802702e1c1f405271ac5d20ae82',
                                                            'before': None},
 'tests/destructive/support/model_workflows.py': {'after': '42f6e30d3f255e2835c539e122abaa7425be7fcaef196feb112e56f583d2dbda',
                                                  'before': None},
 'tests/destructive/support/music_fade_lifecycle.py': {'after': '495d5cf58d1ded2b3c01a07d38c4a69b8038fa675a6aaed0fd11469c7fba7f89',
                                                       'before': None},
 'tests/destructive/support/music_playlist_diagnostic.py': {'after': 'ef330938fa24ef37cf4372778dd74d1acdbd02d077fdab6212db876b2318ae99',
                                                            'before': None},
 'tests/destructive/support/namespaced_query_fixture.py': {'after': '82d555a46e79bc4b33d7194f832699beffcc45e6d71b840ae616c4edf22d9a2c',
                                                           'before': None},
 'tests/destructive/support/object_constructor_collision.py': {'after': '60df3368a190ea7f296ee61897d1dda3ed08a126826244259f6a113e56ddc6a0',
                                                               'before': None},
 'tests/destructive/support/owned_role_survey.py': {'after': '2e435b8cb0dc3d3d96bdcb7d2e7b34efaefa88d04315f1a3ca0ca08a4de18826',
                                                    'before': None},
 'tests/destructive/support/profiler_capture.py': {'after': 'e9c4b240a199a38757d15407ad77341af4395c2f82ffee1dc21d933f9c546c34',
                                                   'before': None},
 'tests/destructive/support/profiler_input_shapes.py': {'after': '330893817501066ed9ac11f536bb59e4bf632cde6b461ba94c5b5ef51c69c501',
                                                        'before': None},
 'tests/destructive/support/sandbox_fixture.py': {'after': '743097c4e072724029e0ba2bb5fb1929395c1c555ba9f446966ec2395aa71bb5',
                                                  'before': '9cee11f5f8beda4d1cbd1330bf029e5146b1a75b0ef343200ca89b4a513bf879'},
 'tests/destructive/support/soundbank_acceptance.py': {'after': 'c2986f260962e7de7337ec02bd9de8c9fc10d15fbd9873e6c4b02f4fef270017',
                                                       'before': None},
 'tests/destructive/support/transport_semantics.py': {'after': '484a2249ff4f7255eda7165b4f6999c3cb5853c380546ed62c0b3ab0a7b4ed65',
                                                      'before': None},
 'tests/maintenance/branch_audit_mapping.py': {'after': 'c3966b611d0b70219967761d041cffff01500c96a573255a256bf908d6acc74e',
                                               'before': None},
 'tests/semantic/support/codex_compound_heavy_v1.py': {'after': '5f36562dcadce2f85266ecb33aaebd991fb952b175830f1493f3bcfca1ea1f88',
                                                       'before': '45b0422943f395c69b0c799126311b314af4c84aa9747620bf2e1e0d047c3e15'},
 'tests/semantic/support/codex_draft_commands.py': {'after': '9ee32cb68581709c3edf12da57cf72797bae03ee768a218a8f1caf5d6799a5fd',
                                                    'before': '0452113ed5e3ffad72561ac5150a0cb24936a40fe992ce42e3b9540af0e90000'},
 'tests/semantic/support/codex_eval_bundle_v3.py': {'after': 'b630f8e93ad56cfa08cc185b15968c51f31ee52fab30fd7a3fad1c03aacf7a70',
                                                    'before': 'e555fb3a8457eccf38d798ff20e60b0149af5387972fe9d16c522596d091cc9b'},
 'tests/semantic/support/codex_heavy_project_runner_v3.py': {'after': '10acb42001405430160a2079c1c09b7b04cebfde981d6452e9c377eb19d8cc2e',
                                                             'before': '4603d25d5a2a8d0f5870e5ccd10d89d186465b1193d96c1cecf2ed4b9fdc9a92'},
 'tests/semantic/support/codex_import_assets_v3.py': {'after': 'c989981ef0fec1e6c28a21590a35e1b971dbcdc79c447116de9834d76a4039eb',
                                                      'before': 'bc8786fd336bee26a7308bb9d2e170e3a412a146129ffef98129e7890cc2d93c'},
 'tests/semantic/support/codex_music_oracle_probes.py': {'after': '392879122ee1c2a7971a43d95719fd0d600d651279e3c639fecf72604db5ad5c',
                                                         'before': '1f727ed84be5ed87fe5bd4a9e9c26f5f429f42eb414daa8ee309f0a756652afa'},
 'tests/semantic/support/codex_scenario_lifecycle_v3.py': {'after': 'd92ada1ed73ba8b5766e9377ab4c7a8f2f34b035a87f1088ff95c03f0be8a1bc',
                                                           'before': '58bfb4f6e8605b54dab26b478ffdd11d9c6bbe0d8131043ebe3116256ddf6b80'},
 'tests/semantic/support/codex_typed_draft_evidence_v3.py': {'after': '155722a4a3c5250f9aeb8dbdad5517d6170221772a7342ca49e70ead3435d8f7',
                                                             'before': '37841446878515c1484dfecf0cf35ac304c87b9f13ee39c6e0ec35c66d3d4189'},
 'tests/semantic/support/codex_typed_input_profile.py': {'after': 'fe5ea90a892b89fb4690bc143982c9c440ac912ab2be24134a5fb888103c7304',
                                                         'before': 'a03eb5afc5b633030a62bfe042ea6b40b9e9abbec35a2fa8b956377e73de9a8e'},
 'tests/support/applicability_completion_mapping.py': {'after': 'f7b350ccb1f43b7d8b44808ea646969ba0afd1df2075afe3cd8d9f6ed66fab06',
                                                       'before': None},
 'tests/support/applicability_program.py': {'after': '80c4eddfacdd7ed418be89395099bda776851f43aba9fbcd61b773952ca9a279',
                                            'before': None},
 'tests/support/condition_branch_evidence.py': {'after': 'e52ecc05ca5b41d13be691de7f5d226418a00c2b210885b56141ad1c5b042018',
                                                'before': '93b603a66b612af84758d0273415d34467aee60ef8773ea1736b4e9b805116f2'},
 'tests/support/condition_completion_mapping.py': {'after': '68ee0fbe9c682480ef74ce06162d9c289c508c2272adb71e7245d038b18a843a',
                                                   'before': None},
 'tests/support/condition_mechanism_reuse.py': {'after': 'b6159776e6fb217fc5bba01372f50c8438c4dc4704caa4e2ad61344b2ccbdf0d',
                                                'before': None},
 'tests/support/condition_source_resolution.py': {'after': '45f2f44d0674f4d1d89ba2499f6ddcfa297aee40def0f4d9d7b376424dd5bf1d',
                                                  'before': None},
 'tests/support/console_runtime_read_evidence.py': {'after': '413b8d7d60e4780e82f8d7a25effd5277e1276da1315381f3d4800fc924ae5b1',
                                                    'before': None},
 'tests/support/core_completion_mapping.py': {'after': '9a430fa152a9d8e6c48487fa87b69069b5560e4484964a27463e2395328b962a',
                                              'before': None},
 'tests/support/empty_candidate_evidence.py': {'after': '4805dd71488053a6ddcb7dcf04bc4710c26614d63327e4184785d8931aabaa17',
                                               'before': None},
 'tests/support/extra_runtime_read_evidence.py': {'after': '5d171ce74cf863a16570ef3565a66b1f5e0d85be71e4ef0714559ccbe0a88bd2',
                                                  'before': None},
 'tests/support/files_completion_mapping.py': {'after': 'bc1ecb2e48d1de32cfc8b389cd5758be0c659bf40d0c714c500b1dadf2455d26',
                                               'before': None},
 'tests/support/fixed_runtime_read_evidence.py': {'after': 'd89e3f94fbc13e86f8952abe4065169127413f44a12c3381432f4685df61e56d',
                                                  'before': None},
 'tests/support/fresh_branch_evidence.py': {'after': 'c94667edfd24139651ae38d8a916235cb9c92a8bb15f87b05f22ca09aa597dfd',
                                            'before': None},
 'tests/support/history_completion_mapping.py': {'after': 'd6935a90e648b19591ca21c524ad8f927a6349037bb50474968293de03c6e1a8',
                                                 'before': None},
 'tests/support/host_completion_mapping.py': {'after': '663dae93ec83a8f2fb18fc38d41fb300515d29a7b9c2e0d071a11c6cfcc4db7c',
                                              'before': None},
 'tests/support/imports_completion_mapping.py': {'after': '0263061ba417a4bb9dcebb77c6207dcd225733bdb3f244b7971cc23344fa6b1d',
                                                 'before': None},
 'tests/support/loaded_media_runtime_evidence.py': {'after': '8fa0ce0b2331fe14c7897b4e25c7396ad10650a64a7b8ed12720493adc3ee8ae',
                                                    'before': None},
 'tests/support/meter_runtime_read_evidence.py': {'after': 'f2516b984c9ab45175f58fcff2a2ce452b390b151d9266d0260d12235b59b6b3',
                                                  'before': None},
 'tests/support/new_condition_completion.py': {'after': 'ee989f858d4ccacb6b8328ee7b114b4cbbb463f844f950f43fa7665506eda912',
                                               'before': None},
 'tests/support/object_completion_mapping.py': {'after': '8d1f75db5d02ed6326b397e43cafeb81241c897ce78b0690e289ed7a58e09475',
                                                'before': None},
 'tests/support/ordinary_test_run_evidence.py': {'after': 'ed44b27cfb34be577c088dcf3db614122f4299947d450aa38beae8ce42b3a573',
                                                 'before': None},
 'tests/support/playlist_reference_observation.py': {'after': '380a22d141075555e6a6ce32d1acefc9e2806780aecf8cd52a45c2d6c4c0899e',
                                                     'before': None},
 'tests/support/qualified_runtime_read_evidence.py': {'after': '7c7c2105893e87e3a12b4f638396e98d12969a2b0f98178016886843419dfc5f',
                                                      'before': None},
 'tests/support/query_completion_mapping.py': {'after': '0d836e689fa5e38de98e840b31c010ec4b430bb06c8ba019cc5440c1e734c42c',
                                               'before': None},
 'tests/support/riff_wave.py': {'after': 'cf6fee97dc46d287a0a6aca0a8da7bf0e7d640a7f6c169672d9a9f9d9be9f64b',
                                'before': None},
 'tests/support/runtime_capture_control_evidence.py': {'after': 'bf63f18869b2ffe1ba0cec6b818742a2f4c11e48de012c00e455e4623c639b55',
                                                       'before': None},
 'tests/support/runtime_cursor_evidence.py': {'after': 'd5de84a7bdff6098a1ab225c6f7b053a964657dda9c4a435d6bb87b1340811eb',
                                              'before': None},
 'tests/support/runtime_log_retained_evidence.py': {'after': '9be116d0caca0e28dae66c301ac9d1370ac6c3b8af4b0f792f61abcf51dbedcc',
                                                    'before': None},
 'tests/support/runtime_observation_evidence.py': {'after': '84f1bf99a9d40df720e4e712a9d1eb9bab3a7e0c1636f38c1ec4c99248bd947c',
                                                   'before': None},
 'tests/support/runtime_owned_control_evidence.py': {'after': 'cf7cd74383bac8c6fa96683457a8fc2aa368ac4abfe552aad74420ac634a369c',
                                                     'before': None},
 'tests/support/runtime_remaining_completion_mapping.py': {'after': '4a2003be2f540a452ec9a8edab7c2f126f5b23072a3690e268cbe4c258815e98',
                                                           'before': None},
 'tests/support/runtime_remaining_evidence.py': {'after': '886adee848c6ad34302b263fd141ffecccb2dd53081cb5291ac32319fcfef12e',
                                                 'before': None},
 'tests/support/runtime_transport_evidence.py': {'after': 'a08f0a1ff904f30650cce85465692cbd034d1614f9e324c588ec28910bab30b6',
                                                 'before': None},
 'tests/support/source_copy_branch_evidence.py': {'after': 'de255dc11e0cb81e625eb23b1a4c63ac61f61529673b8bf1f609988470ee974a',
                                                  'before': 'd4d1e5ae5e5736c01362ed25f7ec0745c4a324bddca5a88695811e852cc88e06'},
 'tests/support/source_copy_native_evidence.py': {'after': 'b6d7470133c67f8f5da88b449932c44518ef42d1477df8b06994c371ce52944c',
                                                  'before': 'a7ac635f8b4964cab93d84479d64f6af1ca6dad2f1d2bfc2daffb5c3b6ec38d6'},
 'tests/support/test_run_result.py': {'after': '711a2240e8515515e81abd0624bfdd197b7ad798a32812aee7fd7713c2c528a4',
                                      'before': None},
 'tests/support/topic_completion_mapping.py': {'after': '8789f16b69a7b1044454d71dca69fc4768f9198959fa02a3f474fad19a5a192e',
                                               'before': None},
 'tests/support/ui_completion_mapping.py': {'after': 'b77f98185f76725f632c56b8c5fa236315cc21ae092e4d36cd448b2fca47444b',
                                            'before': None},
 'tests/unit/test_branch_coverage_completion_cli.py': {'after': '9e639447b57f675ca6fd9554b54ae677f0a6abedf73b27853c58c1d672c5cdea',
                                                       'before': 'b6fcec39b5994eae73205ac9616b03a02e2c8475340e8036b1092485bd516ead'}}


def reviewed_replay_sources(cohort):
    """Exact reviewed current roster/bytes; no caller-provided admission map."""
    from tests.maintenance.branch_audit_completion import read_sealed_artifact
    accepted = read_sealed_artifact(R59_REPLAY_PROGRAM, audit.ROOT)
    sources = accepted['relevant_sources']
    if (accepted['git_candidate'] != R59_REPLAY_CANDIDATE
            or len(sources) != 572 or audit.digest(sources) != R59_REPLAY_SOURCE_SHA256
            or git_source_seals(R59_REPLAY_CANDIDATE, sources) != sources):
        raise ValueError('Exact accepted R59 raw source context changed')
    sources = dict(sources)
    for name, pair in CURRENT_REPLAY_SOURCE_CHANGES.items():
        if sources.get(name) != pair['before']:
            raise ValueError('Reviewed current metadata source before value changed')
        if pair['after'] is None:
            sources.pop(name, None)
        else:
            sources[name] = pair['after']
    if cohort == 'r51':
        sources = {name: value for name, value in sources.items()
            if (name.startswith('skills/waapi-skill/') and Path(name).suffix in {'.py', '.json', '.md'})
            or name in R51_CURRENT_FIXED_SOURCES}
    elif cohort not in {'r54', 'r55'}:
        raise ValueError('Unreviewed current metadata cohort')
    return sources


def validate_current_replay_sources(before, after, *, cohort):
    reviewed = reviewed_replay_sources(cohort)
    changes, expected = source_changes(before, after), source_changes(before, reviewed)
    if (set(after) != set(reviewed)
            or any(changes.get(name) != expected.get(name)
                   for name in set(changes) | set(expected)
                   if name not in CURRENT_REPLAY_MUTABLE_SOURCES)):
        raise ValueError('Exact reviewed metadata source delta missing; unreviewed runtime drift is not equivalent')


ORIGINAL = '90c1089b77e9a9d5695224d312bff9a3ab8b5c18'
R51_ORIGINAL_SOURCE_NAMES = ('skills/waapi-skill/SKILL.md',
 'skills/waapi-skill/evals/adapter_registry.json',
 'skills/waapi-skill/evals/evals-v2.json',
 'skills/waapi-skill/evals/modification-policy-9.json',
 'skills/waapi-skill/evals/offline_tests.json',
 'skills/waapi-skill/evals/online/2022.1/core_object.json',
 'skills/waapi-skill/evals/online/2022.1/other.json',
 'skills/waapi-skill/evals/online/2022.1/runtime.json',
 'skills/waapi-skill/evals/online/debug_lua.json',
 'skills/waapi-skill/evals/online/version_specific/authoring.json',
 'skills/waapi-skill/evals/online/version_specific/other.json',
 'skills/waapi-skill/evals/online/version_specific/runtime.json',
 'skills/waapi-skill/evals/online_tests.json',
 'skills/waapi-skill/evals/request_mapping_registry.json',
 'skills/waapi-skill/evals/suite-v3.json',
 'skills/waapi-skill/references/semantic/2021.1/semantic-builder-import.md',
 'skills/waapi-skill/references/semantic/2021.1/semantic-builder-notebooklm-gate.md',
 'skills/waapi-skill/references/semantic/2021.1/semantic-builder-object-mutation.md',
 'skills/waapi-skill/references/semantic/2021.1/semantic-builder-property-reference.md',
 'skills/waapi-skill/references/semantic/2021.1/semantic-builder-protocol.md',
 'skills/waapi-skill/references/semantic/2021.1/semantic-builder-query.md',
 'skills/waapi-skill/references/semantic/2021.1/semantic-builder-soundbank.md',
 'skills/waapi-skill/references/semantic/2021.1/semantic-builder-switchcontainer.md',
 'skills/waapi-skill/references/semantic/2021.1/short-id-query-sources.json',
 'skills/waapi-skill/references/semantic/2022.1/semantic-builder-import.md',
 'skills/waapi-skill/references/semantic/2022.1/semantic-builder-notebooklm-gate.md',
 'skills/waapi-skill/references/semantic/2022.1/semantic-builder-object-mutation.md',
 'skills/waapi-skill/references/semantic/2022.1/semantic-builder-property-reference.md',
 'skills/waapi-skill/references/semantic/2022.1/semantic-builder-protocol.md',
 'skills/waapi-skill/references/semantic/2022.1/semantic-builder-query.md',
 'skills/waapi-skill/references/semantic/2022.1/semantic-builder-soundbank.md',
 'skills/waapi-skill/references/semantic/2022.1/semantic-builder-switchcontainer.md',
 'skills/waapi-skill/references/semantic/2022.1/short-id-query-sources.json',
 'skills/waapi-skill/references/semantic/2023.1/semantic-builder-import.md',
 'skills/waapi-skill/references/semantic/2023.1/semantic-builder-notebooklm-gate.md',
 'skills/waapi-skill/references/semantic/2023.1/semantic-builder-object-mutation.md',
 'skills/waapi-skill/references/semantic/2023.1/semantic-builder-property-reference.md',
 'skills/waapi-skill/references/semantic/2023.1/semantic-builder-protocol.md',
 'skills/waapi-skill/references/semantic/2023.1/semantic-builder-query.md',
 'skills/waapi-skill/references/semantic/2023.1/semantic-builder-soundbank.md',
 'skills/waapi-skill/references/semantic/2023.1/semantic-builder-switchcontainer.md',
 'skills/waapi-skill/references/semantic/2023.1/short-id-query-sources.json',
 'skills/waapi-skill/references/semantic/2024.1/semantic-builder-import.md',
 'skills/waapi-skill/references/semantic/2024.1/semantic-builder-notebooklm-gate.md',
 'skills/waapi-skill/references/semantic/2024.1/semantic-builder-object-mutation.md',
 'skills/waapi-skill/references/semantic/2024.1/semantic-builder-property-reference.md',
 'skills/waapi-skill/references/semantic/2024.1/semantic-builder-protocol.md',
 'skills/waapi-skill/references/semantic/2024.1/semantic-builder-query.md',
 'skills/waapi-skill/references/semantic/2024.1/semantic-builder-soundbank.md',
 'skills/waapi-skill/references/semantic/2024.1/semantic-builder-switchcontainer.md',
 'skills/waapi-skill/references/semantic/2024.1/short-id-query-sources.json',
 'skills/waapi-skill/references/semantic/2025.1/discrepancy-register.md',
 'skills/waapi-skill/references/semantic/2025.1/semantic-builder-import.md',
 'skills/waapi-skill/references/semantic/2025.1/semantic-builder-notebooklm-gate.md',
 'skills/waapi-skill/references/semantic/2025.1/semantic-builder-object-mutation.md',
 'skills/waapi-skill/references/semantic/2025.1/semantic-builder-property-reference.md',
 'skills/waapi-skill/references/semantic/2025.1/semantic-builder-protocol.md',
 'skills/waapi-skill/references/semantic/2025.1/semantic-builder-query.md',
 'skills/waapi-skill/references/semantic/2025.1/semantic-builder-soundbank.md',
 'skills/waapi-skill/references/semantic/2025.1/semantic-builder-switchcontainer.md',
 'skills/waapi-skill/references/semantic/2025.1/short-id-query-sources.json',
 'skills/waapi-skill/references/waapi-coverage.md',
 'skills/waapi-skill/references/waapi-operate.md',
 'skills/waapi-skill/references/waapi-query.md',
 'skills/waapi-skill/references/waapi-setup.md',
 'skills/waapi-skill/resources/deferred/2021.1.json',
 'skills/waapi-skill/resources/deferred/2022.1.json',
 'skills/waapi-skill/resources/deferred/2023.1.json',
 'skills/waapi-skill/resources/deferred/2024.1.json',
 'skills/waapi-skill/resources/deferred/2025.1.json',
 'skills/waapi-skill/resources/manifest/2021.1/authoring-ui-command-inventory.json',
 'skills/waapi-skill/resources/manifest/2021.1/authoring-ui-commands-supplement.json',
 'skills/waapi-skill/resources/manifest/2021.1/definitions.json',
 'skills/waapi-skill/resources/manifest/2021.1/functions.json',
 'skills/waapi-skill/resources/manifest/2021.1/manifest.json',
 'skills/waapi-skill/resources/manifest/2021.1/schemas.json',
 'skills/waapi-skill/resources/manifest/2021.1/topics.json',
 'skills/waapi-skill/resources/manifest/2022.1/authoring-ui-command-inventory.json',
 'skills/waapi-skill/resources/manifest/2022.1/authoring-ui-commands-supplement.json',
 'skills/waapi-skill/resources/manifest/2022.1/definitions.json',
 'skills/waapi-skill/resources/manifest/2022.1/functions.json',
 'skills/waapi-skill/resources/manifest/2022.1/manifest.json',
 'skills/waapi-skill/resources/manifest/2022.1/schemas.json',
 'skills/waapi-skill/resources/manifest/2022.1/topics.json',
 'skills/waapi-skill/resources/manifest/2023.1/authoring-ui-command-inventory.json',
 'skills/waapi-skill/resources/manifest/2023.1/authoring-ui-commands-supplement.json',
 'skills/waapi-skill/resources/manifest/2023.1/definitions.json',
 'skills/waapi-skill/resources/manifest/2023.1/functions.json',
 'skills/waapi-skill/resources/manifest/2023.1/manifest.json',
 'skills/waapi-skill/resources/manifest/2023.1/schemas.json',
 'skills/waapi-skill/resources/manifest/2023.1/topics.json',
 'skills/waapi-skill/resources/manifest/2024.1/authoring-core-supplement.json',
 'skills/waapi-skill/resources/manifest/2024.1/authoring-layout-mutation-supplement.json',
 'skills/waapi-skill/resources/manifest/2024.1/authoring-layout-read-supplement.json',
 'skills/waapi-skill/resources/manifest/2024.1/authoring-model-supplement.json',
 'skills/waapi-skill/resources/manifest/2024.1/authoring-ui-command-inventory.json',
 'skills/waapi-skill/resources/manifest/2024.1/authoring-ui-commands-supplement.json',
 'skills/waapi-skill/resources/manifest/2024.1/authoring-ui-topics-supplement.json',
 'skills/waapi-skill/resources/manifest/2024.1/definitions.json',
 'skills/waapi-skill/resources/manifest/2024.1/functions.json',
 'skills/waapi-skill/resources/manifest/2024.1/manifest.json',
 'skills/waapi-skill/resources/manifest/2024.1/schemas.json',
 'skills/waapi-skill/resources/manifest/2024.1/topics.json',
 'skills/waapi-skill/resources/manifest/2025.1/added-since-2024.1.json',
 'skills/waapi-skill/resources/manifest/2025.1/authoring-core-supplement.json',
 'skills/waapi-skill/resources/manifest/2025.1/authoring-layout-mutation-supplement.json',
 'skills/waapi-skill/resources/manifest/2025.1/authoring-layout-read-supplement.json',
 'skills/waapi-skill/resources/manifest/2025.1/authoring-model-supplement.json',
 'skills/waapi-skill/resources/manifest/2025.1/authoring-ui-command-inventory.json',
 'skills/waapi-skill/resources/manifest/2025.1/authoring-ui-commands-supplement.json',
 'skills/waapi-skill/resources/manifest/2025.1/authoring-ui-topics-supplement.json',
 'skills/waapi-skill/resources/manifest/2025.1/definitions.json',
 'skills/waapi-skill/resources/manifest/2025.1/functions.json',
 'skills/waapi-skill/resources/manifest/2025.1/manifest.json',
 'skills/waapi-skill/resources/manifest/2025.1/schemas.json',
 'skills/waapi-skill/resources/manifest/2025.1/topics.json',
 'skills/waapi-skill/resources/manifest/typed-request-surface.json',
 'skills/waapi-skill/resources/metadata/2021.1/documented-list-fields.json',
 'skills/waapi-skill/resources/metadata/2021.1/object-types.json',
 'skills/waapi-skill/resources/metadata/2021.1/override-applicability.json',
 'skills/waapi-skill/resources/metadata/2022.1/documented-list-fields.json',
 'skills/waapi-skill/resources/metadata/2022.1/object-types.json',
 'skills/waapi-skill/resources/metadata/2022.1/override-applicability.json',
 'skills/waapi-skill/resources/metadata/2023.1/documented-list-fields.json',
 'skills/waapi-skill/resources/metadata/2023.1/object-types.json',
 'skills/waapi-skill/resources/metadata/2023.1/override-applicability.json',
 'skills/waapi-skill/resources/metadata/2024.1/documented-list-fields.json',
 'skills/waapi-skill/resources/metadata/2024.1/object-types.json',
 'skills/waapi-skill/resources/metadata/2024.1/override-applicability.json',
 'skills/waapi-skill/resources/metadata/2025.1/documented-list-fields.json',
 'skills/waapi-skill/resources/metadata/2025.1/object-types.json',
 'skills/waapi-skill/resources/metadata/2025.1/override-applicability.json',
 'skills/waapi-skill/resources/native-catalog/2021.1/wwise-authoring.json',
 'skills/waapi-skill/resources/native-catalog/2021.1/wwise-console.json',
 'skills/waapi-skill/resources/native-catalog/2022.1/wwise-authoring.json',
 'skills/waapi-skill/resources/native-catalog/2022.1/wwise-console.json',
 'skills/waapi-skill/resources/native-catalog/2023.1/wwise-authoring.json',
 'skills/waapi-skill/resources/native-catalog/2023.1/wwise-console.json',
 'skills/waapi-skill/resources/native-catalog/2024.1/wwise-authoring.json',
 'skills/waapi-skill/resources/native-catalog/2024.1/wwise-console.json',
 'skills/waapi-skill/resources/native-catalog/2025.1/wwise-authoring.json',
 'skills/waapi-skill/resources/native-catalog/2025.1/wwise-console.json',
 'skills/waapi-skill/resources/native-catalog/capture-provenance.json',
 'skills/waapi-skill/resources/native-catalog/definition-provenance.json',
 'skills/waapi-skill/resources/native-catalog/host-schema-parity.json',
 'skills/waapi-skill/resources/native-catalog/index.json',
 'skills/waapi-skill/resources/native_surface_policy.json',
 'skills/waapi-skill/resources/semantic/2021.1/none_state_materialization.json',
 'skills/waapi-skill/resources/semantic/2021.1/source_notes.json',
 'skills/waapi-skill/resources/semantic/2022.1/none_state_materialization.json',
 'skills/waapi-skill/resources/semantic/2022.1/source_notes.json',
 'skills/waapi-skill/resources/semantic/2023.1/none_state_materialization.json',
 'skills/waapi-skill/resources/semantic/2023.1/source_notes.json',
 'skills/waapi-skill/resources/semantic/2024.1/none_state_materialization.json',
 'skills/waapi-skill/resources/semantic/2024.1/source_notes.json',
 'skills/waapi-skill/resources/semantic/2025.1/none_state_materialization.json',
 'skills/waapi-skill/resources/semantic/2025.1/source_notes.json',
 'skills/waapi-skill/resources/waql/2021.1/object-get-examples.json',
 'skills/waapi-skill/resources/waql/2022.1/object-get-examples.json',
 'skills/waapi-skill/resources/waql/2023.1/object-get-examples.json',
 'skills/waapi-skill/resources/waql/2024.1/object-get-examples.json',
 'skills/waapi-skill/resources/waql/2025.1/object-get-examples.json',
 'skills/waapi-skill/scripts/__init__.py',
 'skills/waapi-skill/scripts/config.py',
 'skills/waapi-skill/scripts/gateway.py',
 'skills/waapi-skill/scripts/run.py',
 'skills/waapi-skill/scripts/setup_environment.py',
 'skills/waapi-skill/wwise_waapi/__init__.py',
 'skills/waapi-skill/wwise_waapi/audio_import_business.py',
 'skills/waapi-skill/wwise_waapi/audio_import_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/authoring_core_manifest.py',
 'skills/waapi-skill/wwise_waapi/authoring_launch.py',
 'skills/waapi-skill/wwise_waapi/authoring_layout.py',
 'skills/waapi-skill/wwise_waapi/authoring_layout_business.py',
 'skills/waapi-skill/wwise_waapi/authoring_layout_handles.py',
 'skills/waapi-skill/wwise_waapi/authoring_model_business.py',
 'skills/waapi-skill/wwise_waapi/authoring_resources.py',
 'skills/waapi-skill/wwise_waapi/authoring_ui_business.py',
 'skills/waapi-skill/wwise_waapi/authoring_ui_business_cli.py',
 'skills/waapi-skill/wwise_waapi/authoring_ui_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/authoring_ui_commands_manifest.py',
 'skills/waapi-skill/wwise_waapi/authoring_ui_topics_manifest.py',
 'skills/waapi-skill/wwise_waapi/authoring_wafm.py',
 'skills/waapi-skill/wwise_waapi/authorization.py',
 'skills/waapi-skill/wwise_waapi/builders/__init__.py',
 'skills/waapi-skill/wwise_waapi/builders/common.py',
 'skills/waapi-skill/wwise_waapi/builders/container_suitability.py',
 'skills/waapi-skill/wwise_waapi/builders/debug_lua.py',
 'skills/waapi-skill/wwise_waapi/builders/identity.py',
 'skills/waapi-skill/wwise_waapi/builders/metadata.py',
 'skills/waapi-skill/wwise_waapi/builders/object_mutation.py',
 'skills/waapi-skill/wwise_waapi/builders/properties.py',
 'skills/waapi-skill/wwise_waapi/builders/query.py',
 'skills/waapi-skill/wwise_waapi/builders/schema.py',
 'skills/waapi-skill/wwise_waapi/builders/soundbank.py',
 'skills/waapi-skill/wwise_waapi/builders/source_notes.py',
 'skills/waapi-skill/wwise_waapi/builders/stable_reads.py',
 'skills/waapi-skill/wwise_waapi/builders/switchcontainer.py',
 'skills/waapi-skill/wwise_waapi/business_adapters.py',
 'skills/waapi-skill/wwise_waapi/business_declaration_state.py',
 'skills/waapi-skill/wwise_waapi/business_declarations.py',
 'skills/waapi-skill/wwise_waapi/business_fields.py',
 'skills/waapi-skill/wwise_waapi/business_planning.py',
 'skills/waapi-skill/wwise_waapi/canonical.py',
 'skills/waapi-skill/wwise_waapi/capabilities.py',
 'skills/waapi-skill/wwise_waapi/category_policy.py',
 'skills/waapi-skill/wwise_waapi/cli_console_business.py',
 'skills/waapi-skill/wwise_waapi/cli_console_business_cli.py',
 'skills/waapi-skill/wwise_waapi/cli_console_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/compound_undo_business.py',
 'skills/waapi-skill/wwise_waapi/compound_undo_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/compound_undo_observation.py',
 'skills/waapi-skill/wwise_waapi/condition_limits.py',
 'skills/waapi-skill/wwise_waapi/config.py',
 'skills/waapi-skill/wwise_waapi/console_media_ids.py',
 'skills/waapi-skill/wwise_waapi/console_project_operations.py',
 'skills/waapi-skill/wwise_waapi/core_business.py',
 'skills/waapi-skill/wwise_waapi/core_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/creation_observations.py',
 'skills/waapi-skill/wwise_waapi/debug_business.py',
 'skills/waapi-skill/wwise_waapi/debug_business_cli.py',
 'skills/waapi-skill/wwise_waapi/debug_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/deferred_registry.py',
 'skills/waapi-skill/wwise_waapi/dispatcher.py',
 'skills/waapi-skill/wwise_waapi/documented_list_fields.py',
 'skills/waapi-skill/wwise_waapi/edit_history_business.py',
 'skills/waapi-skill/wwise_waapi/edit_history_contracts.py',
 'skills/waapi-skill/wwise_waapi/effect_render_conditions.py',
 'skills/waapi-skill/wwise_waapi/endpoint_scope.py',
 'skills/waapi-skill/wwise_waapi/exact_artifact_business.py',
 'skills/waapi-skill/wwise_waapi/exact_artifact_business_cli.py',
 'skills/waapi-skill/wwise_waapi/exact_artifact_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/execution_contracts.py',
 'skills/waapi-skill/wwise_waapi/existing_field_observations.py',
 'skills/waapi-skill/wwise_waapi/filesystem_security.py',
 'skills/waapi-skill/wwise_waapi/headless.py',
 'skills/waapi-skill/wwise_waapi/host_paths.py',
 'skills/waapi-skill/wwise_waapi/host_ui_debug_business.py',
 'skills/waapi-skill/wwise_waapi/host_ui_debug_business_cli.py',
 'skills/waapi-skill/wwise_waapi/host_ui_debug_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/identity_limits.py',
 'skills/waapi-skill/wwise_waapi/io_policy.py',
 'skills/waapi-skill/wwise_waapi/layout_blueprint.py',
 'skills/waapi-skill/wwise_waapi/manifest.py',
 'skills/waapi-skill/wwise_waapi/media_build_business.py',
 'skills/waapi-skill/wwise_waapi/media_build_business_cli.py',
 'skills/waapi-skill/wwise_waapi/media_build_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/media_pool_continuation.py',
 'skills/waapi-skill/wwise_waapi/media_pool_field_discovery.py',
 'skills/waapi-skill/wwise_waapi/metadata_cache.py',
 'skills/waapi-skill/wwise_waapi/metadata_catalog.py',
 'skills/waapi-skill/wwise_waapi/metadata_condition_contracts.py',
 'skills/waapi-skill/wwise_waapi/metadata_detail.py',
 'skills/waapi-skill/wwise_waapi/metadata_discovery.py',
 'skills/waapi-skill/wwise_waapi/metadata_restrictions.py',
 'skills/waapi-skill/wwise_waapi/native_catalog.py',
 'skills/waapi-skill/wwise_waapi/native_surface_policy.py',
 'skills/waapi-skill/wwise_waapi/new_object_defaults.py',
 'skills/waapi-skill/wwise_waapi/object_capabilities.py',
 'skills/waapi-skill/wwise_waapi/object_graph_business.py',
 'skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/object_graph_paths.py',
 'skills/waapi-skill/wwise_waapi/object_inline_curve.py',
 'skills/waapi-skill/wwise_waapi/object_lifecycle_business.py',
 'skills/waapi-skill/wwise_waapi/object_lifecycle_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/object_lifecycle_graph.py',
 'skills/waapi-skill/wwise_waapi/object_metadata_business.py',
 'skills/waapi-skill/wwise_waapi/object_metadata_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/object_query_active_source.py',
 'skills/waapi-skill/wwise_waapi/object_query_outputs.py',
 'skills/waapi-skill/wwise_waapi/object_query_result_pages.py',
 'skills/waapi-skill/wwise_waapi/operation_composer.py',
 'skills/waapi-skill/wwise_waapi/operation_drafts.py',
 'skills/waapi-skill/wwise_waapi/operation_import.py',
 'skills/waapi-skill/wwise_waapi/operation_object.py',
 'skills/waapi-skill/wwise_waapi/operation_plugin.py',
 'skills/waapi-skill/wwise_waapi/operation_registry.py',
 'skills/waapi-skill/wwise_waapi/operation_soundbank.py',
 'skills/waapi-skill/wwise_waapi/operation_tone.py',
 'skills/waapi-skill/wwise_waapi/operation_ui_commands.py',
 'skills/waapi-skill/wwise_waapi/override_applicability.py',
 'skills/waapi-skill/wwise_waapi/peak_read_continuation.py',
 'skills/waapi-skill/wwise_waapi/planned_references.py',
 'skills/waapi-skill/wwise_waapi/platform_commands.py',
 'skills/waapi-skill/wwise_waapi/platform_paths.py',
 'skills/waapi-skill/wwise_waapi/project_setting_business.py',
 'skills/waapi-skill/wwise_waapi/project_setting_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/recovery.py',
 'skills/waapi-skill/wwise_waapi/remote_transition.py',
 'skills/waapi-skill/wwise_waapi/render_history_observations.py',
 'skills/waapi-skill/wwise_waapi/runtime_game_object_handles.py',
 'skills/waapi-skill/wwise_waapi/runtime_inspection_business.py',
 'skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/runtime_inspection_observations.py',
 'skills/waapi-skill/wwise_waapi/runtime_playing_handles.py',
 'skills/waapi-skill/wwise_waapi/runtime_transport_handles.py',
 'skills/waapi-skill/wwise_waapi/safety.py',
 'skills/waapi-skill/wwise_waapi/schema_inventory.py',
 'skills/waapi-skill/wwise_waapi/selection_guidance.py',
 'skills/waapi-skill/wwise_waapi/short_id_query_sources.py',
 'skills/waapi-skill/wwise_waapi/soundbank_business.py',
 'skills/waapi-skill/wwise_waapi/soundbank_business_cli.py',
 'skills/waapi-skill/wwise_waapi/soundbank_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/soundengine_business.py',
 'skills/waapi-skill/wwise_waapi/soundengine_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/soundengine_lifecycle.py',
 'skills/waapi-skill/wwise_waapi/source_control_business.py',
 'skills/waapi-skill/wwise_waapi/source_control_business_cli.py',
 'skills/waapi-skill/wwise_waapi/source_control_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/source_control_object_files.py',
 'skills/waapi-skill/wwise_waapi/source_control_object_moves.py',
 'skills/waapi-skill/wwise_waapi/source_control_profiles.py',
 'skills/waapi-skill/wwise_waapi/source_control_protected_dispatch.py',
 'skills/waapi-skill/wwise_waapi/source_control_status_read.py',
 'skills/waapi-skill/wwise_waapi/source_control_windows_permissions.py',
 'skills/waapi-skill/wwise_waapi/subscriptions.py',
 'skills/waapi-skill/wwise_waapi/switch_assignment_business.py',
 'skills/waapi-skill/wwise_waapi/switch_assignment_business_contracts.py',
 'skills/waapi-skill/wwise_waapi/topic_business.py',
 'skills/waapi-skill/wwise_waapi/transaction_cleanup.py',
 'skills/waapi-skill/wwise_waapi/transaction_locality.py',
 'skills/waapi-skill/wwise_waapi/transaction_runtime.py',
 'skills/waapi-skill/wwise_waapi/transactions.py',
 'skills/waapi-skill/wwise_waapi/typed_operations.py',
 'skills/waapi-skill/wwise_waapi/typed_queries.py',
 'skills/waapi-skill/wwise_waapi/typed_requests.py',
 'skills/waapi-skill/wwise_waapi/typed_topics.py',
 'skills/waapi-skill/wwise_waapi/versions.py',
 'skills/waapi-skill/wwise_waapi/voice_source_staging.py',
 'skills/waapi-skill/wwise_waapi/wal_read_continuation.py',
 'skills/waapi-skill/wwise_waapi/waql.py',
 'tests/conftest.py',
 'tests/maintenance/branch_audit_completion.py',
 'tests/maintenance/branch_coverage_audit.py',
 'tests/support/exact_evidence_finalization.py',
 'tests/support/media_pool_branch_evidence.py',
 'tests/support/metadata_read_branch_evidence.py',
 'tests/support/metadata_result_case_bank.py',
 'tests/unit/test_branch_coverage_completion_cli.py',
 'tests/unit/test_branch_evidence_readers.py',
 'tests/unit/test_media_build_business_gateway.py',
 'tests/unit/test_metadata_default_branch_evidence.py',
 'tests/unit/test_metadata_discovery_gateway.py')
R51_ORIGINAL_SOURCE_MAP_SHA256 = '9f59dd64d2d7e856fae5f55cd71e5b1f471e1d32883d78a6ad53b860cde3ee9a'

OBJECT = '{CE99046D-D354-422D-A7BB-F1305FF00B2F}'
URI = 'ak.wwise.core.object.getPropertyInfo'
NODE = 'tests/unit/test_metadata_discovery_gateway.py::test_original_r51_metadata_default_replays_through_current_public_gateway'
CASES = {'Color': 'Color-0', 'ControlInput': 'ControlInput-None', 'OverrideColor': 'OverrideColor-False'}
R54_ORIGINAL = '8a8d5f8e006fd56dd5c78ebe6429ee24450abf26'
R54_SOURCE_MAP_SHA256 = 'd747725b40ad86c1c7fbaa515f441b7b3b8137b6845faf0983a1282783d9a929'
R54_NODE = 'tests/unit/test_metadata_discovery_gateway.py::test_original_r54_class_metadata_replays_through_current_public_gateway'


R55_ORIGINAL = '860965d3368a92032061e5b3045c9a916d185b4b'
R55_SOURCE_MAP_SHA256 = 'b2226e4baef9518c7fd19e3b105ba08179e83c11035a227329424401a429d927'
R55_NODE = 'tests/unit/test_metadata_discovery_gateway.py::test_original_r55_class_metadata_replays_through_current_public_gateway'
R55_ORIGINAL_SEALS = {
    '2021.1':'430198f804dbbcfef95974b2e08b4982f24ad9fab3a642bcedf8ffe0dc7855c4',
    '2022.1':'26db7b59adb38a1ea5ae40b16c554cceb4795e3893870e9ecb31bb48caec39b2',
    '2023.1':'f7d964a60d23d364ca292e3dd89af129fa536d28d47a505b4caf799e22fe937e',
    '2024.1':'bb0588f23f9af5a8df9ce33c1dc8c1b903affa3dd5e2558fb629380ed8bb574b'}



# Accepted411e8173949020bad26e4302f1e9428a21bcac7d Source consumers/fixture.
# R54 and R55 independently checked original Git maps have these same before
# blobs; both new helpers are explicitly absent in both originals. These auxiliary
# pairs permit historical-native/current-program attribution only.
CLASS_AUXILIARY_CHANGES = {'tests/destructive/support/source_copy_fixture.py': {'after': 'f9c8ba22f8b69e01bd9e5cf2424699efad4bafce71b1d10a712caf2b3d80177d',
                                                      'before': None},
 'tests/semantic/support/codex_business_oracle_plan_v3.py': {'after': 'acdc65339374bf5109e7e4d8ba13ddab3a5367f10c87b95db64f251aaf97ce2c',
                                                             'before': '65f7943443a91520e535570345e6b43ac4d09e72b519f5ffd57c7c9be51b5eb9'},
 'tests/semantic/support/codex_eval_protocol_v3.py': {'after': '8350a1f08c70468d84c62b74711454354d78bd8c30d24fbe043110d9fee04ca1',
                                                      'before': 'aa0593dee563fa000c026460825cbaa4ae250f7ae567117906fe68a098ee3b4d'},
 'tests/semantic/support/codex_gateway_broker.py': {'after': '06afa360d56dc3227300289fe6867783060578c064240fe5e982a9af7a7a777b',
                                                    'before': '10806fd223d22c199aa3ebcc0a10391854e73ccfff6b91de1356b75ecf77e210'},
 'tests/semantic/support/codex_harness.py': {'after': 'd711cb6978e310407e69e22882eec93dd8275d45a4056a4c4caf9e0860b1ddea',
                                             'before': '44b8888ee682a37d46882bdfbbf5c701a7b2108f310cc40cdd4f14e1658934b2'},
 'tests/semantic/support/codex_prompt_provenance_v3.py': {'after': 'e1a85408dd2f0ed25e75bda00c82d0c3180172ff885ab23d602404da6c478bb1',
                                                          'before': '38a6082b6a95e485dc62f5a52d74e50592a5424d7aa1b1b86500b5a07161e669'},
 'tests/semantic/support/codex_source_copy_protocol.py': {'after': 'b469b24ae64be096d314eb66da81b28833e0e45283d0cc66184199af2a089fdf',
                                                          'before': None},
 'tests/semantic/support/codex_task_runner_v3.py': {'after': '8250851354409dca2c6f789f776951f7174927279e5e495f0e7b01dc7e76bcef',
                                                    'before': 'b33e240e3c20ff5999e7ef773ade357a10222af9fb2b7f47ff3ff94015fc5e02'},
 'tests/semantic/support/codex_typed_draft_evidence_v3.py': {'after': '37841446878515c1484dfecf0cf35ac304c87b9f13ee39c6e0ec35c66d3d4189',
                                                             'before': '05205d05f9c0bf56939297081e69f7db107f50f1808eb9a0274df3d11c06a588'},
 'tests/support/source_copy_branch_evidence.py': {'after': 'd4d1e5ae5e5736c01362ed25f7ec0745c4a324bddca5a88695811e852cc88e06',
                                                  'before': None},
 'tests/support/source_copy_native_evidence.py': {'after': 'a7ac635f8b4964cab93d84479d64f6af1ca6dad2f1d2bfc2daffb5c3b6ec38d6',
                                                  'before': None}}


def class_original_profile(cohort):
    if cohort not in ('r54','r55'):raise ValueError('Unreviewed original class cohort')
    return {'candidate':R54_ORIGINAL if cohort=='r54' else R55_ORIGINAL,
        'source_count':560 if cohort=='r54' else 561,
        'source_digest':R54_SOURCE_MAP_SHA256 if cohort=='r54' else R55_SOURCE_MAP_SHA256,
        'node':R54_NODE if cohort=='r54' else R55_NODE,'cases':16 if cohort=='r54' else 6,
        'branches':41 if cohort=='r54' else 10,
        'versions':('2021.1','2022.1','2023.1','2024.1','2025.1') if cohort=='r54' else tuple(R55_ORIGINAL_SEALS),
        'bridge_contract':'waapi-skill.'+cohort+'-class-metadata-leaf-replay/v2',
        'capture_contract':'waapi-skill.'+cohort+'-metadata-replay-context/v2'}


def class_original_reads(cohort,index_path=None,*,originals=None):
    """Two closed identities; portable anchors first, explicit preparatory inputs only."""
    import os
    from tests.maintenance import branch_audit_completion as completion
    from tests.maintenance.collect_class_metadata import metadata_descriptors,collection_plan
    profile=class_original_profile(cohort)
    path=Path(index_path) if index_path else audit.ROOT/'docs/branch-coverage-evidence-index.json'
    index=audit.load(path);base=(path.parent/index['base']).resolve();roots={}
    def register(original,base):
        original=deepcopy(original);root=(base/original['root']).resolve()
        seal=completion.read_sealed_artifact(original['seal'],base)
        entry,=[row for row in seal['files'] if row['path']=='plan.json'];raw=(root/'plan.json').read_bytes()
        if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('Original index-bound plan seal changed')
        plan=json.loads(raw)
        if plan['repositories'][0]['commit']!=profile['candidate']:return
        if plan.get('cohort','r54')!=cohort:raise ValueError('Closed original class native cohort changed')
        if cohort=='r55' and original['seal']['sha256']!=R55_ORIGINAL_SEALS.get(plan['version']):
            raise ValueError('Original accepted R55 seal anchor changed')
        original['root']=str(root);original['seal']['artifact']=str((base/original['seal']['artifact']).resolve())
        if root in roots:
            if original['seal']!=roots[root]['seal']:raise ValueError('Conflicting original index-bound seal')
        else:
            completion.read_metadata_run(original,base,historical_class=True);roots[root]=original
    if originals is None:
        for desc in index.get('metadata_attachments',[]):
            item=completion.read_sealed_artifact(desc,base)
            if item['contract']!='waapi-skill.class-metadata-attachment/v1':continue
            record=completion.read_sealed_artifact(item['evidence'],base);register(record['metadata_run'],base)
        # Transitional source-only input; committed portable originals win and
        # no historical absolute location is followed implicitly on other hosts.
        preparatory=os.environ.get('WAAPI_R55_CLASS_METADATA_ORIGINALS') if cohort=='r55' and index_path is None else None
        if not roots and preparatory:originals=json.loads(Path(preparatory).read_bytes())
    if originals is not None:
        for descriptor in originals.values():register(descriptor,audit.ROOT)
    found={}
    for root,original in sorted(roots.items()):
        for case,descriptor in metadata_descriptors(root).items():
            descriptor['seal']=deepcopy(original['seal'])
            if case in found:raise ValueError('Duplicate original class/field occurrence')
            found[case]=descriptor
    expected={v+'|'+scope+'|'+field for v in profile['versions']
        for scope,fields in collection_plan(v,cohort=cohort)['targets'].items() for field in fields}
    if set(found)!=expected or len(found)!=profile['cases']:
        raise ValueError('Complete closed original '+cohort+' class reads required')
    return found


def r54_original_reads(index_path=None):
    return class_original_reads('r54',index_path)


def r55_original_reads(index_path=None,*,originals=None):
    return class_original_reads('r55',index_path,originals=originals)


def validate_class_original_sources(candidate,sources,cohort):
    profile=class_original_profile(cohort)
    digest=hashlib.sha256(json.dumps(sources,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if (candidate!=profile['candidate'] or len(sources)!=profile['source_count'] or digest!=profile['source_digest']
            or git_source_seals(candidate,sources)!=sources):
        raise ValueError('Exact full original '+cohort+' Git/source map changed')


def validate_r54_original_sources(candidate,sources):
    validate_class_original_sources(candidate,sources,'r54')


def r55_replay_case(case,descriptor=None,*,base=None):
    return r54_replay_case(case,descriptor,base=base,cohort='r55')


def r54_replay_case(case,descriptor=None,*,base=None,cohort='r54'):
    """Raw original response objects only, never normalized public reconstruction."""
    from tests.maintenance import branch_audit_completion as completion
    base=Path(base) if base else audit.ROOT
    descriptor=deepcopy(descriptor or class_original_reads(cohort)[case])
    context=completion.read_metadata_run(descriptor,base,historical_class=True)
    if context['cohort']!=cohort or case!='|'.join((context['version'],context['class_name'],context['field'])):
        raise ValueError('Exact original R54 class/field occurrence changed')
    root=Path(descriptor['root']);root=root if root.is_absolute() else base/root
    seal=completion.read_sealed_artifact(descriptor['seal'],base)
    entries={row['path']:row for row in seal['files']}
    def read(name):
        raw=(root/name).read_bytes();entry=entries[name]
        if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('Original R54 replay dependency digest/size changed')
        return json.loads(raw)
    target=read('targets.json')[descriptor['target_index']]
    listed=read(target['list_receipt']+'.stdout')
    name_dispatch,=[row for row in listed['calls'] if row['api']=='ak.wwise.core.object.getPropertyAndReferenceNames']
    packets={};hashes={}
    for name in entries:
        if not name.startswith('dispatcher-evidence/'):continue
        packet=read(name);api=packet['api']
        if api not in {'ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo','ak.wwise.core.object.get',
                'ak.wwise.core.object.getTypes','ak.wwise.core.object.getPropertyAndReferenceNames'}:continue
        if api=='ak.wwise.core.object.getPropertyAndReferenceNames' and packet['evidence_path']!=name_dispatch['evidence_path']:continue
        if api not in packets:
            packets[api]=packet;hashes[api]=entries[name]['sha256']
    if ('ak.wwise.core.getInfo' not in packets or 'ak.wwise.core.object.getTypes' not in packets
            or 'ak.wwise.core.object.getPropertyAndReferenceNames' not in packets
            or context['field'] not in packets['ak.wwise.core.object.getPropertyAndReferenceNames']['result']['return']):
        raise ValueError('Original raw host/class/field replay inputs missing')
    return {'context':context,'packets':packets,'packet_sha256s':hashes,'descriptor':descriptor}


def r54_current_sources():
    from tests.maintenance.collect_class_metadata import source_links,collection_source_map,REPO
    sources = collection_source_map(source_links('',{})[1],REPO)
    sources[REQUIREMENTS_SOURCE] = current_requirements_source_seal()
    name = 'tests/maintenance/branch_audit_mapping.py'
    sources[name] = hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest()
    return sources


def make_r54_replay_receipt(capture,case,observed,reports):
    from tests.support.metadata_read_branch_evidence import _witness
    outcome='PASS' if all(reports.get(p)=='passed' for p in ('setup','call','teardown')) else 'FAIL'
    record={'candidate_sha256':capture['candidate_sha256'],'scope_kind':capture.get('scope_kind','product'),
        'evidence_kind':'injected_client_program','git_candidate':capture['git_candidate'],
        'current_requirements_identity': CURRENT_REQUIREMENTS_IDENTITY,
        'relevant_sources':deepcopy(capture['relevant_sources']),
        'invocation':{'phase':'final','outcome':outcome,'node_outcomes':[{'nodeid':class_original_profile(capture.get('cohort','r54'))['node']+'['+case+']','outcome':outcome}]},
        **deepcopy(observed),'branch_assertions':{}}
    bindings={}
    for branch in capture['branches']:
        if branch['id'] not in capture['case_branch_ids'][case]:continue
        witness=_witness(branch,observed['native_call']['result'],capture['edges'])
        if witness is None:raise ValueError('Current replay did not observe original R54 leaf')
        public=witness['observation_pointer'].replace('/native_call/result','/gateway/payload/agent_result/metadata',1)
        record['branch_assertions'][branch['id']]={'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],
            'checks':[witness['check'],{**witness['check'],'pointer':public},
                {'pointer':'/gateway/payload/agent_result','equals':deepcopy(observed['gateway']['payload']['agent_result'])}]}
        bindings[branch['id']]={'branch_id':branch['id'],'native_shape_sha256':branch['shape_sha256'],
            'input':{'gateway_argv':deepcopy(observed['gateway']['argv']),'selector':'original_'+capture.get('cohort','r54')+'_class_field_replay'},
            'dispatch_pointer':'/native_call','observation_pointer':witness['observation_pointer'],
            'gateway_observation_pointer':public,'reference_chain':witness['reference_chain']}
    return record,bindings


def make_r54_attachment_record(capture,case,replay_descriptor,replay_record,replay_bindings,*,base):
    from tests.maintenance import branch_audit_completion as completion
    context=completion.read_metadata_run(capture['originals'][case],base,historical_class=True)
    profile=class_original_profile(capture.get('cohort','r54'))
    if context['cohort']!=capture.get('cohort','r54'):raise ValueError('Original/current class cohort differs')
    record={'candidate_sha256':capture['candidate_sha256'],'scope_kind':capture.get('scope_kind','product'),
        'evidence_kind':'historical_class_metadata_current_program_replay','metadata_run':deepcopy(capture['originals'][case]),
        'invocation':deepcopy(replay_record['invocation']),'replay':deepcopy(replay_descriptor),
        'replay_bindings':deepcopy(replay_bindings),'source_bridge':{'contract':profile['bridge_contract'],
            'attribution':'historical_native_current_program_not_current_native','historical_candidate':profile['candidate'],
            'historical_sources':deepcopy(capture['historical_sources']),'current_sources':deepcopy(capture['relevant_sources']),
            'changed_files':source_changes(capture['historical_sources'],capture['relevant_sources'])},
        'branch_assertions':{},'category_inputs':{'historical':context['gateway']['argv'],'replay':replay_record['gateway']['argv']}}
    for branch in capture['branches']:
        if branch['id'] not in replay_bindings:continue
        record['branch_assertions'][branch['id']]={'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],
            'checks':[{'pointer':replay_bindings[branch['id']]['gateway_observation_pointer'],
                'equals':deepcopy(context['native_result']['default'])},
                {'pointer':'/gateway/payload/agent_result','equals':deepcopy(context['gateway']['payload']['agent_result'])}]}
    return record


def replay_case(field):
    if field not in CASES:
        raise ValueError('Unreviewed R51 replay field')
    return json.loads((audit.ROOT / 'tests/support/metadata_replay_cases.json').read_text())


def source_seals():
    sources = metadata_source_seals()
    for name in ('tests/support/metadata_replay_cases.json', 'tests/support/metadata_replay_branch_evidence.py',
                 'tests/unit/test_metadata_replay_attachments.py', 'docs/branch-coverage-requirements.json'):
        sources[name] = hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest()
    return dict(sorted(sources.items()))


def replay_observation(argv, code, payload, client, field, list_argv, listed):
    packet = replay_case(field)['packets'][field]['native']
    calls = [(uri, args, options) for uri, args, options in client.calls if uri == URI]
    if len(calls) != 1:
        raise ValueError('Replay needs one exact getPropertyInfo dispatch')
    uri, args, options = calls[0]
    return {**public_read_observation(gateway_argv=argv, exit_code=code, payload=payload,
        uri=uri, args=args, options=options, result=packet['result']),
        'discovery': {'argv': deepcopy(list_argv), 'payload': deepcopy(listed)},
        'client_disconnected': client.disconnected, 'replayed_original_native_sha256': replay_case(field)['packets'][field]['original_sha256']}


def _descriptor(path, **extra):
    return {'artifact': str(path), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(), **extra}


def original_read(root, field):
    """Describe preserved R51 bytes; never repair, copy, or regrade originals."""
    if field not in CASES:
        raise ValueError('Unreviewed R51 replay field')
    root = Path(root)
    category = root / 'category.jsonl'
    rows = category.read_bytes().splitlines()
    final = json.loads(rows[-1])
    observation = next(row for row in final['categories'] if row['category'] == 'legacy-original-source-owned-read')
    body_path = Path(observation['observation_path'])
    body = json.loads(body_path.read_bytes())
    calls = [(i, row) for i, row in enumerate(body['calls']) if row['argv'][:4] == ['metadata', 'detail', '--exact-id', OBJECT]
             and json.loads(Path(row['reply']['path']).read_bytes())['agent_result']['metadata']['name'] == field]
    (index, call), = calls
    reply = json.loads(Path(call['reply']['path']).read_bytes())
    native_path = next(row['evidence_path'] for row in reply['calls'] if row['api'] == URI)
    native = next(row for row in body['native_evidence'] if row['native_path'] == native_path)
    return {'contract': 'waapi-skill.r51-metadata-read/v1',
        'category': _descriptor(category, record_index=len(rows)-1, nodeid=final['invocation']['node_outcomes'][0]['nodeid']),
        'observation': _descriptor(body_path), 'status': _descriptor(Path(body['calls'][0]['reply']['path'])),
        'identity': _descriptor(Path(body['calls'][3]['reply']['path'])),
        'reply': _descriptor(Path(call['reply']['path'])), 'native': _descriptor(Path(native['path'])), 'call_index': index}


def portable_original_reads(index_path=None):
    """Resolve committed sealed transport, without following historical host paths.

    Original/source-freeze Git objects are still required by the later full
    source bridge; portable receipt transport does not imply shallow support.
    """
    from tests.maintenance import branch_audit_completion as completion
    index_path = Path(index_path) if index_path else audit.ROOT/'docs/branch-coverage-evidence-index.json'
    # Resolve retained native anchors independently of current program policy.
    # Full portable import still validates every copied requirement later.
    index = audit.load(index_path)
    base = (index_path.parent / index['base']).resolve()
    selected = selected_ids()
    policy = audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json')['branches']
    seen, validated = set(), []
    for link in index.get('metadata_attachments', []):
        attachment = completion.read_sealed_artifact(link, base)
        if attachment['contract'] != 'waapi-skill.r51-metadata-attachment/v1':
            continue
        identity = attachment['branch_id']
        if (set(attachment) != {'contract', 'branch_id', 'native_shape_sha256', 'category_inputs', 'evidence'}
                or identity not in selected or identity in seen):
            raise ValueError('R51 selected anchor identities must be exact and unique')
        seen.add(identity)
        expected_policy = policy.get(identity, {})
        shape = expected_policy.get('native_shape_sha256')
        if (not shape or expected_policy.get('categories') != ['program', 'live_metadata']
                or attachment['native_shape_sha256'] != shape):
            raise ValueError('R51 selected anchor shape or category differs')
        evidence = attachment['evidence']
        if set(evidence) != {'artifact', 'sha256', 'nodeid'}:
            raise ValueError('R51 selected anchor evidence binding differs')
        record = completion.read_sealed_artifact(evidence, base)
        descriptor = deepcopy(record['metadata_run'])
        context = completion.read_metadata_run(descriptor, base)
        field = context['native_result']['name']
        if (context['candidate'] != ORIGINAL or context['version'] != '2021.1'
                or context['host'] != 'wwise-console' or context['build'] != '2021.1.14.8108'
                or field not in CASES or branch_case({'pointer': identity.rsplit('|', 1)[1]}) != field):
            raise ValueError('R51 original selected anchor differs')
        replay_link = record['replay']
        if (set(replay_link) != {'artifact', 'sha256', 'nodeid'}
                or replay_link['nodeid'] != evidence['nodeid']
                or evidence['nodeid'] != NODE + '[' + CASES[field] + ']'):
            raise ValueError('R51 selected anchor node binding differs')
        replay = completion.read_sealed_artifact(replay_link, base)
        categories = record.get('category_inputs', {})
        if (attachment['category_inputs'] != categories or set(categories) != {'historical', 'replay'}
                or categories['historical'] != context['gateway']['argv']
                or categories['replay'] != replay['gateway']['argv']):
            raise ValueError('R51 selected anchor category binding differs')
        assertion = record.get('branch_assertions', {}).get(identity)
        expected = {'native_shape_sha256': shape, 'native_route': identity.rsplit('|', 1)[0],
            'checks': [{'pointer': '/gateway/payload/agent_result/metadata/default',
                        'equals': context['native_result']['default']},
                       {'pointer': '/gateway/payload/agent_result',
                        'equals': context['gateway']['payload']['agent_result']}]}
        if json.dumps(assertion, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
            raise ValueError('R51 selected anchor assertion binding differs')
        for role in ('category','observation','status','identity','reply','native'):
            descriptor[role]['artifact'] = str((base/descriptor[role]['artifact']).resolve())
        validated.append((field, descriptor))
    if seen != selected or len(seen) != 9:
        raise ValueError('R51 original reader requires all nine selected anchors')
    originals = {}
    for field, descriptor in validated:
        if field in originals and originals[field] != descriptor:
            raise ValueError('Conflicting portable original metadata read')
        originals[field] = descriptor
    return originals


def selected_ids():
    prefix = '2021.1|wwise-console|2021.1.14.8108|function|' + URI + '|'
    definition = '/resultSchema/@definition/waapi_definitions.json/definitions/propertyValue'
    pointers = ['/resultSchema/properties/default/@presence/present', '/resultSchema/properties/default',
        '/resultSchema/properties/default/$ref', definition, definition+'/anyOf/0', definition+'/anyOf/0/@nullable',
        definition+'/anyOf/2', definition+'/anyOf/3', definition+'/anyOf/3/@boolean/false']
    return {prefix+p for p in pointers}


def selected_branches(inventory):
    rows = [row for row in inventory['native_coverage']['obligations'] if row['id'] in selected_ids()]
    if len(rows) != 9:
        raise ValueError('Exact nine R51 default obligations changed')
    return rows


def branch_case(branch):
    pointer = branch['pointer']
    return 'ControlInput' if '/anyOf/0' in pointer else 'OverrideColor' if '/anyOf/3' in pointer else 'Color'


def git_source_seals(candidate, names, *, root=None):
    import subprocess
    names = list(names)
    result = subprocess.run(['git', '--no-replace-objects', 'cat-file', '--batch'], cwd=audit.ROOT if root is None else root, check=True,
        input=''.join(candidate+':'+name+'\n' for name in names).encode(), stdout=subprocess.PIPE).stdout
    position, sources = 0, {}
    for name in names:
        end = result.index(b'\n', position)
        header = result[position:end].decode()
        if header.endswith(' missing'):
            raise ValueError('Full committed metadata source closure unavailable')
        count = int(header.rsplit(' ', 1)[1]); position = end+1
        sources[name] = hashlib.sha256(result[position:position+count]).hexdigest(); position += count+1
    return dict(sorted(sources.items()))


def historical_sources():
    # The native R51 closure is independent of current imports. New current
    # dependencies appear only as explicit before=None changes, never old names.
    sources = git_source_seals(ORIGINAL, R51_ORIGINAL_SOURCE_NAMES)
    if len(sources) != 343 or audit.digest(sources) != R51_ORIGINAL_SOURCE_MAP_SHA256:
        raise ValueError('Exact immutable original R51 source map changed')
    return sources


def source_changes(before, after):
    return {name: {'before': before.get(name), 'after': after.get(name)} for name in sorted(set(before)|set(after))
            if before.get(name) != after.get(name)}


def make_replay_receipt(capture, field, observed, reports):
    from tests.support.metadata_read_branch_evidence import _witness
    outcome = 'PASS' if all(reports.get(phase) == 'passed' for phase in ('setup', 'call', 'teardown')) else 'FAIL'
    record = {'candidate_sha256': capture['candidate_sha256'], 'scope_kind': capture.get('scope_kind', 'product'),
        'evidence_kind': 'injected_client_program', 'git_candidate': capture['git_candidate'],
        'current_requirements_identity': CURRENT_REQUIREMENTS_IDENTITY,
        'relevant_sources': deepcopy(capture['relevant_sources']), 'invocation': {'phase': 'final', 'outcome': outcome,
            'node_outcomes': [{'nodeid': NODE+'['+CASES[field]+']', 'outcome': outcome}]},
        **deepcopy(observed), 'branch_assertions': {}}
    bindings = {}
    for branch in capture['branches']:
        if branch_case(branch) != field:
            continue
        witness = _witness(branch, observed['native_call']['result'], capture['edges'])
        if witness is None:
            raise ValueError('Actual current replay did not observe the selected branch')
        public_pointer = witness['observation_pointer'].replace('/native_call/result','/gateway/payload/agent_result/metadata',1)
        checks = [witness['check'], {**deepcopy(witness['check']), 'pointer': public_pointer},
            {'pointer':'/gateway/payload/agent_result','equals':deepcopy(observed['gateway']['payload']['agent_result'])}]
        record['branch_assertions'][branch['id']] = {'native_shape_sha256':branch['shape_sha256'], 'native_route':branch['route'], 'checks':checks}
        bindings[branch['id']] = {'branch_id':branch['id'], 'native_shape_sha256':branch['shape_sha256'],
            'input':{'gateway_argv':deepcopy(observed['gateway']['argv']), 'selector':'original_R51_exact_object_field_replay'},
            'dispatch_pointer':'/native_call', 'observation_pointer':witness['observation_pointer'],
            'gateway_observation_pointer':public_pointer, 'reference_chain':witness['reference_chain']}
    return record, bindings


def make_attachment_record(capture, field, replay_descriptor, replay_record, replay_bindings, *, base):
    from tests.maintenance import branch_audit_completion as completion
    context = completion.read_metadata_run(capture['originals'][field], base)
    record = {'candidate_sha256':capture['candidate_sha256'], 'scope_kind':capture.get('scope_kind','product'),
        'evidence_kind':'historical_metadata_current_program_replay', 'metadata_run':deepcopy(capture['originals'][field]),
        'invocation':deepcopy(replay_record['invocation']), 'replay':deepcopy(replay_descriptor),
        'replay_bindings':deepcopy(replay_bindings), 'source_bridge':{'contract':'waapi-skill.r51-metadata-leaf-replay/v2',
            'attribution':'historical_native_current_program_not_current_native',
            'historical_candidate':ORIGINAL, 'historical_sources':deepcopy(capture['historical_sources']),
            'current_sources':deepcopy(capture['relevant_sources']),
            'changed_files':source_changes(capture['historical_sources'],capture['relevant_sources'])},
        'branch_assertions':{}, 'category_inputs':{'historical':context['gateway']['argv'], 'replay':replay_record['gateway']['argv']}}
    for branch in capture['branches']:
        if branch['id'] not in replay_bindings:
            continue
        pointer = replay_bindings[branch['id']]['gateway_observation_pointer']
        record['branch_assertions'][branch['id']] = {'native_shape_sha256':branch['shape_sha256'], 'native_route':branch['route'],
            'checks':[{'pointer':pointer,'equals':deepcopy(context['gateway']['payload']['agent_result']['metadata']['default'])},
                {'pointer':'/gateway/payload/agent_result','equals':deepcopy(context['gateway']['payload']['agent_result'])}]}
    return record


def validate_default_replay_requirements(inventory, policy):
    """Retain the complete exact default slice with only the reviewed decoder split."""
    from tests.support.metadata_read_branch_evidence import validate_selected_metadata_requirement
    defaults = {row['id']: row for row in inventory['native_coverage']['obligations']
        if row['route'] and '|wwise-console|' in row['route']
        and row['route'].endswith('|' + URI)
        and (row['pointer'].startswith('/resultSchema/properties/default')
             or any(row['pointer'].startswith('/resultSchema/@definition/' + document + '/definitions/propertyValue')
                    for document in ('waapi_definitions.json', 'common_definitions.json')))}
    assigned = {identity for identity in policy['branches']
        if '|wwise-console|' in identity and '|function|' + URI + '|' in identity}
    if len(defaults) != 65 or assigned != set(defaults):
        raise ValueError('Original65 default requirements changed')
    for identity, branch in defaults.items():
        validate_selected_metadata_requirement(branch, policy['branches'][identity])
    return assigned


def _capture_inventory(inventory_descriptor=None):
    """Reuse a root-owned standard build seal, never a caller's inventory dict.

    The final assembly owner supplies this existing artifact/sha256 descriptor
    from its one completed standard build. The descriptor is the trusted input;
    deriving a new expected hash from the file being admitted is not permitted.
    """
    import ast
    from tests.maintenance.branch_audit_completion import read_sealed_artifact, candidate_identity
    from tests.semantic.support.codex_archive_paths import parse_archive_relative_path
    if inventory_descriptor is None:
        return audit.build_inventory()
    if (not isinstance(inventory_descriptor, dict)
            or set(inventory_descriptor) != {'artifact', 'sha256'}):
        raise ValueError('Prepared metadata requires an independently pinned inventory descriptor')
    path = Path(inventory_descriptor['artifact'])
    path = path if path.is_absolute() else audit.ROOT / path
    if path.is_symlink():
        raise ValueError('Prepared metadata inventory cannot be a symlink')
    sealed = read_sealed_artifact(inventory_descriptor, audit.ROOT)
    native = sealed.get('native_coverage', {})
    packed = native.get('obligations_artifact', {})
    if (sealed.get('contract') != 'waapi-skill.branch-audit/v2'
            or native.get('completion', {}).get('evaluated') is not False
            or packed.get('rows') != 272313
            or not sealed.get('sources') or not sealed.get('source_index')):
        raise ValueError('Prepared metadata requires the unevaluated standard five-version inventory')
    name = parse_archive_relative_path(packed['path'])
    if name.canonical != packed['path'] or len(name.parts) != 1:
        raise ValueError('Prepared metadata native rows must be an adjacent sealed artifact')
    packed_path = path.parent / name.canonical
    if packed_path.is_symlink() or not packed_path.resolve().is_relative_to(path.parent.resolve()):
        raise ValueError('Prepared metadata native rows escape their sealed directory')
    # audit.load verifies the packed file SHA, complete native row SHA and count.
    inventory = audit.load(path)
    native = inventory['native_coverage']
    if len(native['obligations']) != 272313:
        raise ValueError('Prepared metadata native denominator changed')
    indexed_paths = {item['path'] for item in inventory['source_index'].values()}
    texts, trees = {}, {}
    for name, expected in inventory['sources'].items():
        parsed = parse_archive_relative_path(name)
        if parsed.canonical != name:
            raise ValueError('Prepared metadata source path is not canonical')
        source = audit.ROOT.joinpath(*parsed.parts)
        if source.is_symlink() or not source.resolve().is_relative_to(audit.ROOT.resolve()):
            raise ValueError('Prepared metadata source escapes the current repository')
        text = source.read_text(encoding='utf-8')
        texts[name] = text
        observed = audit.digest(text) if name in indexed_paths else audit.digest(audit.load(source))
        if observed != expected:
            raise ValueError('Prepared metadata inventory source is stale: ' + name)
    for item in inventory['source_index'].values():
        text, symbol = texts[item['path']], item['symbol']
        node = None
        if symbol:
            if item['path'] not in trees:
                trees[item['path']] = ast.parse(text)
            tree = trees[item['path']]
            node = next((entry for entry in ast.walk(tree)
                if isinstance(entry, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and entry.name == symbol), None)
            if node is None:
                raise ValueError('Prepared metadata source symbol is stale')
        if (item['sha256'] != audit.digest(ast.dump(node, include_attributes=False) if node else text)
                or item['line'] != (node.lineno if node else 1)):
            raise ValueError('Prepared metadata public/source join is stale')
    current = candidate_identity(audit.ROOT, inventory, native['catalogs'], digest=audit.digest)
    if native['candidate_sha256'] != current:
        raise ValueError('Prepared metadata inventory candidate is stale')
    return inventory


def prepare_capture(root, original_root=None, *, inventory_descriptor=None):
    """After source approval only: one fresh context, three selected public nodes."""
    import subprocess
    import shutil
    import gzip
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.media_pool_branch_evidence import _git_candidate, _write
    if subprocess.check_output(['git','status','--porcelain'],cwd=audit.ROOT,text=True).strip():
        raise ValueError('Product metadata replay needs a clean committed source')
    root = Path(root).resolve()
    root.mkdir(parents=True,exist_ok=False)
    (root/'originals').mkdir()
    inventory = _capture_inventory(inventory_descriptor)
    rows = selected_branches(inventory)
    policy = audit.load(audit.ROOT/'docs/branch-coverage-requirements.json')
    assigned = validate_default_replay_requirements(inventory, policy)
    if not {row['id'] for row in rows} <= assigned:
        raise ValueError('Original65 default requirements changed')
    for row in rows:
        if policy['branches'][row['id']]['native_shape_sha256'] != row['shape_sha256']:
            raise ValueError('Exact original default requirement shape changed')
    retained = portable_original_reads() if original_root is None else None
    if retained is not None and set(retained) != set(CASES):
        raise ValueError('Exact three portable R51 original fields required')
    originals = {}
    for field in CASES:
        original = deepcopy(retained[field]) if retained is not None else original_read(original_root,field)
        completion.read_metadata_run(original,root.parent)
        for role in ('category','observation','status','identity','reply','native'):
            desc = original[role]
            name = role+'.original.json' if role in ('category','observation','status','identity') else field+'-'+role+'.original.json'
            dest = root/'originals'/name
            raw = Path(desc['artifact']).read_bytes()
            if dest.exists():
                if dest.read_bytes() != raw:
                    raise ValueError('Conflicting original metadata archive')
            else:
                shutil.copyfile(desc['artifact'],dest)
                if dest.read_bytes() != raw:
                    raise ValueError('Original metadata copy differs')
            desc['artifact'] = root.name+'/originals/'+name
        originals[field] = original
    context = {'contract':'waapi-skill.r51-metadata-replay-context/v2','root':str(root),
        'candidate_sha256':inventory['native_coverage']['candidate_sha256'],'git_candidate':_git_candidate(),
        'relevant_sources':r51_current_sources(),'historical_sources':historical_sources(), 'originals':originals,
        'branches':rows,'edges':{r['id']:r for r in inventory['native_coverage']['obligations'] if r['kind']=='reference'
            and r['route'] == rows[0]['route']},
        'assigned_unobserved_branch_ids':sorted(assigned-{row['id'] for row in rows})}
    if inventory_descriptor is None:
        with gzip.open(root/'frozen-inventory.json.gz','wt',encoding='utf-8') as stream:
            json.dump(inventory,stream,separators=(',',':'))
    else:
        context['inventory_source'] = deepcopy(inventory_descriptor)
    _write(root/'context.json',context)
    return root/'context.json'


def load_capture(path, nodeid, field):
    from tests.support.media_pool_branch_evidence import _git_candidate
    context = json.loads(Path(path).read_bytes())
    if (context['contract'] != 'waapi-skill.r51-metadata-replay-context/v2' or field not in CASES
            or nodeid != NODE+'['+CASES[field]+']' or context['git_candidate'] != _git_candidate()
            or context['relevant_sources'] != r51_current_sources() or context['historical_sources'] != historical_sources()):
        raise ValueError('Prepared current replay node or full source closure changed')
    return context


def finish_capture(capture, reports, observed):
    from tests.support.media_pool_branch_evidence import _git_candidate, _write
    field = observed['native_call']['result']['name']
    root = Path(capture['root'])
    unchanged = capture['git_candidate'] == _git_candidate() and capture['relevant_sources'] == r51_current_sources()
    replay,bindings = make_replay_receipt(capture,field,observed,reports if unchanged else {})
    dest = root/field;dest.mkdir(exist_ok=False)
    program = _write(dest/'program.json',replay)
    program['artifact'] = root.name+'/'+field+'/program.json'
    program['nodeid'] = NODE+'['+CASES[field]+']'
    record = make_attachment_record(capture,field,program,replay,bindings,base=root.parent)
    receipt = _write(dest/'live-metadata.json',record)
    receipt['artifact'] = root.name+'/'+field+'/live-metadata.json'
    receipt['nodeid'] = program['nodeid']
    attachments = []
    for branch in capture['branches']:
        if branch['id'] not in bindings:
            continue
        item = {'contract':'waapi-skill.r51-metadata-attachment/v1','branch_id':branch['id'],
            'native_shape_sha256':branch['shape_sha256'],'category_inputs':record['category_inputs'],'evidence':receipt}
        descriptor = _write(dest/('attachment-'+str(len(attachments))+'.json'),item)
        descriptor['artifact'] = root.name+'/'+field+'/'+Path(descriptor['artifact']).name
        attachments.append(descriptor)
    _write(dest/'attachments.json',{'metadata_attachments':attachments})
    _write(dest/'capture.json',{'outcome':replay['invocation']['outcome'],'source_unchanged':unchanged,
        'phase_reports':reports,'observed_branch_ids':sorted(bindings),
        'attribution':'historical_native_current_program_not_current_native'})



def r54_case_assignments(branches,edges,contexts):
    from tests.support.metadata_read_branch_evidence import _witness
    used=set();owners={}
    for case,context in contexts.items():
        owned=[r['id'] for r in branches if r['id'] not in used and r['route'].split('|')[0]==context['version']
            and _witness(r,context['native_result'],edges) is not None]
        owners[case]=owned;used.update(owned)
    if used!={r['id'] for r in branches}:raise ValueError('Original R54 facts do not witness all exact assigned leaves')
    return owners


def prepare_r54_capture(root,*,cohort='r54',source_originals=None,inventory_descriptor=None):
    """After review: same finalizer/transport, sixteen R54 or six R55 public nodes."""
    import subprocess,shutil,gzip
    from tests.maintenance import branch_audit_completion as completion
    from tests.maintenance.collect_class_metadata import collection_plan
    from tests.support.media_pool_branch_evidence import _git_candidate,_write
    if subprocess.check_output(['git','status','--porcelain'],cwd=audit.ROOT,text=True).strip():
        raise ValueError('Current R54 replay requires a clean source pin')
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    profile=class_original_profile(cohort)
    inventory=_capture_inventory(inventory_descriptor);source_originals=class_original_reads(cohort,originals=source_originals);originals={};contexts={}
    copied={}
    for case,descriptor in source_originals.items():
        context=completion.read_metadata_run(descriptor,audit.ROOT,historical_class=True);contexts[case]=context
        original_root=Path(descriptor['root'])
        if original_root not in copied:
            dest=root/'originals'/original_root.name;dest.mkdir(parents=True,exist_ok=False)
            seal=completion.read_sealed_artifact(descriptor['seal'],audit.ROOT)
            for entry in seal['files']:
                path=original_root/entry['path'];raw=path.read_bytes()
                if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                    raise ValueError('Original R54 archive changed before replay preparation')
                target=dest/entry['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
            shutil.copyfile(original_root/'evidence-seal.json',dest/'evidence-seal.json');copied[original_root]=dest
        item=deepcopy(descriptor);item['root']=root.name+'/originals/'+original_root.name
        item['seal']['artifact']=item['root']+'/evidence-seal.json';originals[case]=item
    assigned=set().union(*(set(collection_plan(v,cohort=cohort)['eligible_branch_ids']) for v in profile['versions']))
    branches=[r for r in inventory['native_coverage']['obligations'] if r['id'] in assigned]
    if len(branches)!=profile['branches']:raise ValueError('Closed original class requirement set changed')
    edges={r['id']:r for r in inventory['native_coverage']['obligations'] if r['kind']=='reference'}
    owners=r54_case_assignments(branches,edges,contexts)
    context={'contract':profile['capture_contract'],'cohort':cohort,'root':str(root),
        'candidate_sha256':inventory['native_coverage']['candidate_sha256'],'git_candidate':_git_candidate(),
        'relevant_sources':r54_current_sources(),'historical_sources':next(iter(contexts.values()))['relevant_sources'],
        'originals':originals,'case_branch_ids':owners,'branches':branches,'edges':edges}
    if inventory_descriptor is None:
        with gzip.open(root/'frozen-inventory.json.gz','wt',encoding='utf-8') as stream:json.dump(inventory,stream)
    else:
        context['inventory_source'] = deepcopy(inventory_descriptor)
    _write(root/'context.json',context);return root/'context.json'


def load_r54_capture(path,nodeid,case):
    from tests.support.media_pool_branch_evidence import _git_candidate
    capture=json.loads(Path(path).read_bytes())
    profile=class_original_profile(capture.get('cohort','r54'))
    if (capture['contract']!=profile['capture_contract'] or case not in capture['originals']
            or nodeid!=class_original_profile(capture.get('cohort','r54'))['node']+'['+case+']' or capture['git_candidate']!=_git_candidate()
            or capture['relevant_sources']!=r54_current_sources()):
        raise ValueError('Current R54 public replay source/node changed')
    validate_class_original_sources(profile['candidate'],capture['historical_sources'],capture.get('cohort','r54'))
    return capture


def finish_r54_capture(capture,reports,case,observed):
    from tests.support.media_pool_branch_evidence import _git_candidate,_write
    root=Path(capture['root']);unchanged=capture['git_candidate']==_git_candidate() and capture['relevant_sources']==r54_current_sources()
    program,bindings=make_r54_replay_receipt(capture,case,observed,reports if unchanged else {})
    dest=root/('case-'+str(list(capture['originals']).index(case)));dest.mkdir(exist_ok=False)
    descriptor=_write(dest/'program.json',program);descriptor.update(artifact=root.name+'/'+dest.name+'/program.json',nodeid=class_original_profile(capture.get('cohort','r54'))['node']+'['+case+']')
    record=make_r54_attachment_record(capture,case,descriptor,program,bindings,base=root.parent)
    evidence=_write(dest/'live-metadata.json',record);evidence.update(artifact=root.name+'/'+dest.name+'/live-metadata.json',nodeid=descriptor['nodeid'])
    attachments=[]
    for branch in capture['branches']:
        if branch['id'] not in bindings:continue
        item={'contract':'waapi-skill.class-metadata-attachment/v1','branch_id':branch['id'],
            'native_shape_sha256':branch['shape_sha256'],'category_inputs':record['category_inputs'],'evidence':evidence}
        desc=_write(dest/('attachment-'+str(len(attachments))+'.json'),item)
        desc['artifact']=root.name+'/'+dest.name+'/'+Path(desc['artifact']).name;attachments.append(desc)
    _write(dest/'attachments.json',{'metadata_attachments':attachments})
    _write(dest/'capture.json',{'outcome':program['invocation']['outcome'],'source_unchanged':unchanged,
        'phase_reports':reports,'observed_branch_ids':sorted(bindings),'attribution':'historical_native_current_program_not_current_native'})
