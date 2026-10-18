"""Extract compact explicit-class closure facts from pinned installed XML; no WAAPI."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

BUILDS = {'2021.1': '2021.1.14.8108', '2022.1': '2022.1.19.8584', '2023.1': '2023.1.19.8928',
          '2024.1': '2024.1.13.9056', '2025.1': '2025.1.7.9143'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def extract(source, *, version, build, types):
    raw = source.read_bytes()
    if len(raw) > 16 * 1024 * 1024 or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise ValueError('XML source exceeds the bounded trusted format')
    root = ET.fromstring(raw)
    nodes = {}
    for node in root:
        if node.tag not in {'ObjectBase', 'WwiseObject'}:
            continue
        key = node.tag + ':' + node.attrib['Name']
        if key in nodes or len(nodes) >= 4096:
            raise ValueError('Duplicate/oversized source index')
        nodes[key] = node
    selected = {}
    def visit(key, path=()):
        if key in path or len(path) >= 128:
            raise ValueError('Invalid explicit class closure')
        if key in selected:
            return
        node = nodes[key]
        refs = ['ObjectBase:' + ref.attrib['Name'] for ref in node.findall('ObjectBaseRef')]
        fields = []
        for properties in node.findall('Properties'):
            for field in properties:
                if field.tag not in {'Property', 'Reference'}:
                    raise ValueError('Unrecognized property declaration in relevant closure')
                fields.append({'name': field.attrib['Name'], 'kind': field.tag,
                    'has_own_dependencies': bool(list(field.findall('./Dependencies/*')))})
        selected[key] = {'key': key, 'refs': refs, 'fields': fields,
                         'source_node_sha256': hashlib.sha256(ET.tostring(node)).hexdigest()}
        for ref in refs:
            visit(ref, (*path, key))
    classes = []
    for name in ('AuxBus', 'Bus', 'Sound'):
        key = 'WwiseObject:' + name
        visit(key)
        matches = [row for row in types if row['name'] == name]
        if len(matches) != 1:
            raise ValueError('Concrete class is not unique in pinned native type source')
        classes.append({'name': name, 'class_id': matches[0]['classId'], 'root': key})
    group = nodes['ObjectBase:UserAuxSends']
    dependencies = []
    for dep in group.findall('./Dependencies/*'):
        if dep.tag == 'OverrideDependency' and dep.attrib == {'Name': 'OverrideUserAuxSends'}:
            dependencies.append({'type': 'override', 'action': 'Enable', 'context': 'Self', 'property': 'OverrideUserAuxSends'})
        elif dep.tag == 'IsMasterBusDependency' and dep.attrib.get('Value', '').casefold() == 'false':
            dependencies.append({'type': 'isMasterBus', 'action': 'Show', 'context': 'Self', 'value': False})
        else:
            raise ValueError('Unreviewed UserAuxSends dependency grammar')
    payload = {'contract': 'waapi-skill.override-applicability-source/v1', 'version': version,
        'source': {'build': build, 'member': 'Authoring/Data/WObjects/WObjects.xml',
                   'sha256': hashlib.sha256(raw).hexdigest(), 'indexed_nodes': len(nodes)},
        'classes': classes, 'nodes': [selected[key] for key in sorted(selected)],
        'group': {'node': 'ObjectBase:UserAuxSends', 'controller': 'OverrideUserAuxSends', 'dependencies': dependencies}}
    return {**payload, 'catalog_sha256': digest(payload)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed-root', type=Path, default=Path('/Library/Application Support/Audiokinetic'))
    metadata_root = Path(__file__).resolve().parents[2] / 'skills/waapi-skill/resources/metadata'
    parser.add_argument('--types-root', type=Path, default=metadata_root)
    parser.add_argument('--output-root', type=Path, default=metadata_root)
    args = parser.parse_args()
    for version, build in BUILDS.items():
        directory = args.output_root / version
        types = json.loads((args.types_root / version / 'object-types.json').read_text())['types']
        directory.mkdir(parents=True, exist_ok=True)
        payload = extract(args.installed_root / ('Wwise ' + build) / 'Authoring/Data/WObjects/WObjects.xml',
                          version=version, build=build, types=types)
        target = directory / 'override-applicability.json'
        target.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
        print(version, len(target.read_bytes()), payload['catalog_sha256'])


if __name__ == '__main__':
    main()
