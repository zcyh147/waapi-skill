"""Closed developer-only 2021 synthetic input and independent saved graph oracle."""
import hashlib
import json
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

from tests.semantic.support.codex_filesystem_security import read_bounded_exclusive_regular_file
from tests.semantic.support.codex_project_prelaunch_v3 import _require_owned_path, _reject_symlink_chain, _replace_closed_file_batch

PROFILE = '2021-native-donor-two-properties/v1'
SOURCE = '{95DDA32B-B666-4269-A54C-5ABF4E201C99}'
SOURCE_OWNER = '{63E5A1E6-4265-463E-A5C5-322F742423E1}'
MIDI = Path('Actor-Mixer Hierarchy/MIDI.wwu')
ORIGINAL_SHA = '4f4839e0457831e6d85c012847159b6f410c8716ec9a6c4ab6e9f888ff3c39e3'
DONOR_SHA = '2022d6d1e9ca0badae31ce635ed802234b79dc862201a7b101a8a963b3ff9ed6'
SPAN_SHA = 'ab36cdf4299caa517ffb376b19cf9724f6640b1c63864128cd91e7ae2bc8cbdf'
DONOR_ROOT = Path(__file__).parents[2] / 'fixtures/source-copy'
REPEATED_COLLECTOR_LIMITS = {'calls': 160, 'native_files': 1280}
# Closed developer profile only: measured original128-call/1024-file failure
# requires138calls/1130files, with a1192-file conservative remaining bound.
CLASSES = {'SourcePlugin': 9699330, 'RTPC': 1441808, 'ModulatorLfo': 4194320, 'Curve': 917520}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_file(path, maximum=8 * 1024 * 1024):
    return read_bounded_exclusive_regular_file(path, max_bytes=maximum, require_private_posix_mode=False).raw


def xml(raw):
    assert len(raw) <= 8 * 1024 * 1024 and b'<!DOCTYPE' not in raw.upper(), 'Unsafe fixture XML'
    root = ET.fromstring(raw)
    stack, count = [(root, 0)], 0
    while stack:
        node, depth = stack.pop(); count += 1
        assert count <= 32768 and depth <= 64, 'Fixture XML bound exceeded'
        stack.extend((child, depth + 1) for child in node)
    return root


def guid(value):
    if isinstance(value, dict): value = value.get('id')
    result = uuid.UUID(value)
    assert result.int, 'Missing fixture GUID'
    return '{' + str(result).upper() + '}'


def source_graph(images, source_id, owner_id):
    assert 1 <= len(images) <= 2
    found, declarations = [], []
    for raw in images:
        root = xml(raw)
        parents = {child: node for node in root.iter() for child in node}
        declarations.extend(node for node in root.iter() if node.tag in CLASSES or node.tag == 'Sound')
        for node in root.iter('SourcePlugin'):
            if guid(node.get('ID')) != guid(source_id): continue
            parent = parents.get(node); owner = parents.get(parent)
            assert parent.tag == 'ChildrenList' and owner.tag == 'Sound' and guid(owner.get('ID')) == guid(owner_id), 'Source owner differs'
            found.append(node)
    assert len(found) == 1, 'Repeated fixture Source is missing or duplicated'
    source, = found
    assert source.get('PluginName') == 'Wwise Synth One' and source.get('PluginID') == '148' and source.get('CompanyID') == '0'
    assert not list(source.iter('ObjectRef')), 'Unreviewed fixture reference'
    nodes = {'source': source}
    for prop in ('OutputLevel', 'Osc1Level'):
        rtpcs = source.findall("PropertyList/Property[@Name='" + prop + "']/RTPCList/RTPC")
        assert len(rtpcs) == 1, 'Repeated fixture property RTPC group missing or duplicated: ' + prop
        rtpc, = rtpcs
        control, = rtpc.findall("ReferenceList/Reference[@Name='ControlInput']/Custom/ModulatorLfo")
        curve, = rtpc.findall('Curve')
        nodes.update({prop + '.rtpc': rtpc, prop + '.control': control, prop + '.curve': curve})
    assert {node for node in source.iter() if 'ID' in node.attrib} == set(nodes.values()), 'Unclassified fixture declaration'
    ids = [guid(node.get('ID')) for node in nodes.values()]
    assert len(set(ids)) == 7 and all(sum(guid(row.get('ID')) == identity for row in declarations) == 1 for identity in ids), 'Fixture declaration alias'
    assert sum(len(node.findall('PointList/Point')) for key, node in nodes.items() if key.endswith('.curve')) == 4
    return nodes


def canonical(node, nodes=None):
    attrs = dict(node.attrib)
    if nodes and node in nodes.values():
        role = next(key for key, value in nodes.items() if value is node)
        attrs['ID'] = 'owned:' + role
        if 'ShortID' in attrs: attrs['ShortID'] = 'live-bound:' + role
    text, tail = node.text, node.tail
    if len(node) and text is not None and not text.strip() and '\n' in text: text = None
    if tail is not None and not tail.strip() and '\n' in tail: tail = None
    return [node.tag, sorted(attrs.items()), text, tail, [canonical(child, nodes) for child in node]]


def validate_frames(nodes, live, owner_id):
    assert set(nodes) == set(live), 'Incomplete live fixture graph'
    for role, node in nodes.items():
        row = live[role]
        assert guid(row['id']) == guid(node.get('ID')) and row['class_id'] == CLASSES[node.tag], 'Fixture live class or GUID differs'
        assert row['type'] in ({'Source', 'SourcePlugin'} if role == 'source' else {node.tag})
        owner = owner_id if role == 'source' else nodes['source' if role.endswith('.rtpc') else role.split('.')[0] + '.rtpc'].get('ID')
        assert guid(row.get('parent' if role == 'source' else 'owner')) == guid(owner), 'Fixture live owner differs'
        assert row['name'] == node.get('Name') and row.get('notes', '') == node.findtext('Comment', '')
        if 'ShortID' in node.attrib:
            assert type(row.get('short_id')) is int and str(row['short_id']) == node.get('ShortID'), 'Fixture live ShortID differs'


def prepare_repeated_source_fixture(sandbox, *, owned_root, io_root):
    root, owned, io = Path(sandbox.sandbox_path), Path(owned_root), Path(io_root)
    target = root / MIDI
    assert not io.resolve().is_relative_to(root.resolve()) and not root.resolve().is_relative_to(io.resolve()), 'Fixture report must be outside project tree'
    assert not (io / 'source-copy-prelaunch.json').exists(), 'Never replace an earlier fixture report'
    for path in (root, Path(sandbox.sandbox_project), target, io):
        _require_owned_path(path.resolve(strict=True), owned_root=owned.resolve(strict=True), label='Source fixture')
        _reject_symlink_chain(path, owned_input=owned, label='Source fixture')
    assert not target.resolve().is_relative_to(Path(sandbox.source_root).resolve()), 'Cannot mutate immutable source'
    original = read_file(target)
    assert sha(original) == ORIGINAL_SHA, 'Source fixture preimage drift'
    provenance = json.loads(read_file(DONOR_ROOT / '2021-native-donor.json', 16384))
    donor = read_file(DONOR_ROOT / '2021-native-donor.wwu', 4016)
    assert len(donor) == 4016 and sha(donor) == DONOR_SHA == provenance['sha256'], 'Native donor drift'
    assert provenance['rtpc_list_span'] == [2239, 3641] and provenance['rtpc_list_sha256'] == SPAN_SHA
    group = donor[2239:3641]
    assert sha(group) == SPAN_SHA, 'Native donor span drift'
    donor_nodes = [node for node in xml(group).iter() if 'ID' in node.attrib]
    donor_ids = {guid(node.get('ID')) for node in donor_nodes}
    donor_shorts = {int(node.get('ShortID')) for node in donor_nodes if 'ShortID' in node.attrib}
    paths = sorted(path for path in root.rglob('*') if path.suffix.casefold() == '.wwu') + [Path(sandbox.sandbox_project)]
    assert len(paths) <= 513, 'Fixture model inventory over bound'
    inventory = []
    for path in paths:
        _reject_symlink_chain(path, owned_input=owned, label='Fixture collision inventory')
        raw = read_file(path)
        inventory.append({'relative_path': path.relative_to(root).as_posix(), 'bytes': len(raw), 'sha256': sha(raw)})
        for node in xml(raw).iter():
            try:
                identity = guid(node.get('ID'))
            except (TypeError, ValueError, AttributeError):
                identity = None
            short_id = int(node.get('ShortID')) if 'ShortID' in node.attrib else None
            assert identity not in donor_ids and short_id not in donor_shorts, 'Native donor identity collision'
    needle = b'<Property Name="Osc1Level" Type="Real32" Value="-5"/>'
    start = original.index(b'<SourcePlugin Name="Wwise Synth One" ID="' + SOURCE.encode() + b'"')
    end = original.index(b'</SourcePlugin>', start)
    assert original[start:end].count(needle) == 1, 'Ambiguous target property'
    offset = original.index(needle, start, end)
    replacement = needle[:-2] + b'>' + group + b'</Property>'
    transformed = original[:offset] + replacement + original[offset + len(needle):]
    nodes = source_graph([transformed], SOURCE, SOURCE_OWNER)
    assert len(nodes) == 7
    # Existing atomic prelaunch replacement revalidates the exact preimage
    # without truncating a possibly replaced or hard-linked source inode.
    assert read_file(target) == original, 'Fixture preimage changed before splice'
    _replace_closed_file_batch([(target, original, transformed)])
    assert read_file(target) == transformed, 'Fixture splice did not persist exactly'
    report = {'profile': PROFILE, 'native_acceptance': False, 'coverage_credit': 'none', 'donor': provenance,
        'relative_path': MIDI.as_posix(), 'input_sha256': sha(original), 'output_sha256': sha(transformed),
        'input_bytes': len(original), 'output_bytes': len(transformed), 'splice_offset': offset,
        'source_id': SOURCE, 'source_owner': SOURCE_OWNER, 'collision_inventory': inventory,
        'role_ids': {key: node.get('ID') for key, node in nodes.items()}}
    with (io / 'source-copy-prelaunch.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2); stream.write('\n')
    return report


def repeated_copy_oracle(before_images, after_images, *, source_id, copied_id, original_owner_id, destination_id, before_live, copied_live):
    before = source_graph(before_images, source_id, original_owner_id)
    retained = source_graph(after_images, source_id, original_owner_id)
    copied = source_graph(after_images, copied_id, destination_id)
    validate_frames(before, before_live, original_owner_id)
    validate_frames(copied, copied_live, destination_id)
    old_ids, new_ids = ({key: node.get('ID') for key, node in graph.items()} for graph in (before, copied))
    assert set(old_ids.values()).isdisjoint(new_ids.values()), 'Copied fixture aliases original'
    assert canonical(before['source']) == canonical(retained['source']), 'Original fixture changed'
    assert canonical(before['source'], before) == canonical(copied['source'], copied), 'Copied fixture values or order differ'
    return {'original_preserved': True, 'serialized_subtree_preserved': True, 'ordered_point_count': 4,
        'object_ref_count': 0, 'owned_guid_mapping': {old_ids[key]: new_ids[key] for key in before},
        'scope': 'native-donor synthetic fixture; exact 2021 two-property graph only'}
