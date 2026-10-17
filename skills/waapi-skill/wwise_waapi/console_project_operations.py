"""Pinned Console project/file outcomes; no process or native client launches."""
from __future__ import annotations

from typing import Any, Mapping


CLI_PROJECT_FILE_URIS = frozenset({
    'ak.wwise.cli.addNewPlatform',
    'ak.wwise.cli.createNewProject',
    'ak.wwise.cli.dumpObjects',
    'ak.wwise.cli.migrate',
    'ak.wwise.cli.moveMediaIdsToSingleFile',
    'ak.wwise.cli.moveMediaIdsToWorkUnits',
    'ak.wwise.cli.updateMediaIdsInSingleFile',
    'ak.wwise.cli.verify',
})
CONSOLE_PROJECT_URIS = frozenset({
    'ak.wwise.console.project.create',
    'ak.wwise.console.project.open',
    'ak.wwise.console.project.close',
})
PROJECT_FILE_URIS = CLI_PROJECT_FILE_URIS | CONSOLE_PROJECT_URIS
_MEDIA_ID_URIS = frozenset({
    'ak.wwise.cli.moveMediaIdsToSingleFile',
    'ak.wwise.cli.moveMediaIdsToWorkUnits',
    'ak.wwise.cli.updateMediaIdsInSingleFile',
})


def observe_cli_project_outcome(uri: str, version: str, result: Any) -> dict[str, Any]:
    """Interpret only documented exit outcomes, separately from file effects.

    processResultCli in each pinned definition describes 0 success, 1 errors
    (possibly warnings), and 2 warnings only. The earlier media-ID routes return
    an empty object and disclose no process code. Neither proves file effects.
    """
    if uri not in CLI_PROJECT_FILE_URIS:
        raise ValueError('Not an owned Console project/file command')
    if uri in _MEDIA_ID_URIS and version in {'2021.1', '2022.1', '2023.1'}:
        if not isinstance(result, Mapping) or result:
            raise ValueError('This version returns no process outcome; expected its empty result object')
        return {'kind': 'cli-process-outcome', 'uri': uri, 'version': version,
            'outcome': 'not_reported', 'business_effect_proven': False}
    code = result.get('result') if isinstance(result, Mapping) else None
    if isinstance(code, bool) or not isinstance(code, (int, float)) or code not in (0, 1, 2):
        raise ValueError('The native process result is not one of the documented outcomes 0, 1, or 2')
    return {'kind': 'cli-process-outcome', 'uri': uri, 'version': version,
        'exit_code': code, 'outcome': {0: 'success', 1: 'errors', 2: 'warnings_only'}[code],
        'reported_errors': code == 1, 'business_effect_proven': False,
        'partial_effects_possible': code == 1, 'automatic_retry': False}


CONSOLE_CREATE_URI = 'ak.wwise.console.project.create'
MAX_PROJECT_FILE_BYTES = 8 * 1024 * 1024
MAX_PROJECT_XML_NODES = 32768
MAX_PROJECT_XML_DEPTH = 64
MAX_PROJECT_DECLARATION_ROWS = 128
MAX_MISSING_PROJECT_DIRECTORIES = 64


def _project_io_root_identity(root: str) -> dict[str, Any]:
    from pathlib import Path
    from .filesystem_security import metadata_is_link_or_reparse
    from .operation_soundbank import SoundBankContractError

    try:
        path = Path(root)
        metadata = path.lstat()
        if metadata_is_link_or_reparse(metadata) or not path.is_dir():
            raise SoundBankContractError('INVALID_IO_ROOT', 'Project output root must remain a real directory')
        return {'resolved_path': str(path.resolve(strict=True)), 'device': metadata.st_dev, 'inode': metadata.st_ino}
    except OSError as exc:
        raise SoundBankContractError('INVALID_IO_ROOT', 'Project output root cannot be observed') from exc


def _project_creation_ancestor(root: str) -> tuple[dict[str, Any], list[str]]:
    """Freeze the existing directory above a not-yet-created output root."""
    from pathlib import Path
    from .operation_soundbank import SoundBankContractError

    cursor = Path(root)
    missing = []
    while True:
        try:
            cursor.lstat()
        except FileNotFoundError:
            if len(missing) >= MAX_MISSING_PROJECT_DIRECTORIES or cursor == cursor.parent:
                raise SoundBankContractError('LIMIT_EXCEEDED', 'Project output exceeds its bounded missing-directory chain')
            missing.append(str(cursor))
            cursor = cursor.parent
        except OSError as exc:
            raise SoundBankContractError('INVALID_IO_ROOT', 'Project output ancestor cannot be observed') from exc
        else:
            return _project_io_root_identity(str(cursor)), list(reversed(missing))


def _created_project_root_identity(plan: Mapping[str, Any]) -> dict[str, Any]:
    from .operation_soundbank import SoundBankContractError

    ancestor = plan['root_identity']
    if _project_io_root_identity(ancestor['resolved_path']) != ancestor:
        raise SoundBankContractError('FILE_CHANGED', 'Project output ancestor changed after Preview')
    for path in plan['missing_root_directories']:
        try:
            observed = _project_io_root_identity(path)
        except SoundBankContractError as exc:
            if exc.__cause__ is not None and not isinstance(exc.__cause__, FileNotFoundError):
                raise  # An unavailable observation is not proof of a missing artifact.
            raise SoundBankContractError('MISSING_ARTIFACT', 'Requested project directory was not created as a real directory') from exc
        if observed['resolved_path'] != path:
            raise SoundBankContractError('FILE_CHANGED', 'Created project directory resolves outside its frozen path')
    return _project_io_root_identity(plan['io_root'])


def prepare_console_project_creation(args: Mapping[str, Any], audit: Mapping[str, Any], version: str) -> dict[str, Any]:
    from .operation_soundbank import SoundBankContractError, prove_artifact_path

    paths = [row for row in audit['paths'] if row['json_path'] == '$.args.path']
    if len(paths) != 1:
        raise SoundBankContractError('INVALID_PATH', 'Project creation requires its exact isolated output path')
    path, root = paths[0]['resolved_path'], audit['io_root']
    ancestor, missing = _project_creation_ancestor(root)
    before = prove_artifact_path(path, io_root=ancestor['resolved_path'], field='new project', must_exist=False, expect_directory=False)
    if before['exists']:
        raise SoundBankContractError('PROJECT_ALREADY_EXISTS', 'New project creation cannot replace an existing file')
    return {'kind': 'console-project-create', 'uri': CONSOLE_CREATE_URI, 'version': version,
        'args': dict(args), 'path': path, 'io_root': root, 'root_identity': ancestor,
        'missing_root_directories': missing, 'before': before}


def validate_console_project_creation(plan, args, audit, version):
    from .operation_soundbank import SoundBankContractError

    if dict(plan) != prepare_console_project_creation(args, audit, version):
        raise SoundBankContractError('FILE_CHANGED', 'Project destination or its isolated path changed after Preview')


def inspect_created_project(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Read the bounded saved project; no endpoint calls or inferred native classes.

    ProjectInfo/Project, Platforms, LanguageList and DefaultLanguage are the
    explicit format in the matching five-lane packaged SDK project samples.
    Source-format evidence is separate from native execution/effect evidence.
    """
    import hashlib
    import os
    import re
    from xml.etree import ElementTree as ET
    from .operation_soundbank import (
        SoundBankContractError, capture_file_proof, open_regular_artifact_file, prove_artifact_path,
    )

    path, root = plan['path'], plan['io_root']
    observed_root = _created_project_root_identity(plan)
    target = prove_artifact_path(path, io_root=root, field='created project', must_exist=False, expect_directory=False)
    if not target['exists']:
        raise SoundBankContractError('MISSING_ARTIFACT', 'Requested saved project artifact is missing')
    proof = capture_file_proof(path, field='created project', max_bytes=MAX_PROJECT_FILE_BYTES, io_root=root)
    _, descriptor, before = open_regular_artifact_file(path, field='created project', io_root=root)
    with os.fdopen(descriptor, 'rb') as opened:
        raw = opened.read(MAX_PROJECT_FILE_BYTES + 1)
        after = os.fstat(opened.fileno())
    if (len(raw) != proof['size'] or hashlib.sha256(raw).hexdigest() != proof['sha256']
            or any(getattr(before, key) != getattr(after, key)
                for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
            or capture_file_proof(path, field='created project', max_bytes=MAX_PROJECT_FILE_BYTES, io_root=root) != proof):
        raise SoundBankContractError('FILE_CHANGED', 'Created project changed during its bounded observation')
    try:
        text = raw.decode('utf-8-sig')
        if '\x00' in text or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise ValueError('Project XML must be UTF-8 without DTD/entity declarations')
        parser = ET.XMLPullParser(events=('start', 'end'))
        document, nodes, depth = None, 0, 0
        for offset in range(0, len(text), 65536):
            parser.feed(text[offset:offset + 65536])
            for event, node in parser.read_events():
                if event == 'start':
                    nodes, depth = nodes + 1, depth + 1
                    if document is None:
                        document = node
                    if nodes > MAX_PROJECT_XML_NODES or depth > MAX_PROJECT_XML_DEPTH:
                        raise SoundBankContractError('LIMIT_EXCEEDED', 'Project XML exceeds the bounded node/depth observation')
                else:
                    depth -= 1
        parser.close()
        if (document is None or document.tag != 'WwiseDocument' or document.get('Type') != 'Project'
                or not document.get('WwiseVersion', '').startswith('v' + plan['version'] + '.')
                or not document.get('SchemaVersion', '').isdigit()
                or int(document.get('SchemaVersion')) < 1):
            raise ValueError('Saved artifact does not identify a project in the requested Wwise version lane')
        infos = document.findall('ProjectInfo')
        projects = document.findall('./ProjectInfo/Project')
        if len(infos) != 1 or len(projects) != 1:
            raise ValueError('Saved project must contain exactly one ProjectInfo/Project')
        project = projects[0]
        guid = re.compile(r'^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$')
        if not guid.fullmatch(project.get('ID', '')) or not project.get('Name'):
            raise ValueError('Saved project lacks its explicit GUID/name identity')
        def records(parent, tag, fields):
            if len(project.findall(parent)) != 1:
                raise ValueError(f'Saved project lacks exactly one {parent}')
            rows = [{key: node.get(key) for key in fields} for node in project.findall(f'./{parent}/{tag}')]
            if len(rows) > MAX_PROJECT_DECLARATION_ROWS:
                raise SoundBankContractError('LIMIT_EXCEEDED', f'Saved {parent} exceeds the bounded row observation')
            if any(any(not isinstance(value, str) or not value for value in row.values())
                    or not guid.fullmatch(row['ID']) for row in rows):
                raise ValueError(f'Saved {parent} contains malformed rows')
            if len({row['ID'].upper() for row in rows}) != len(rows) or len({row['Name'] for row in rows}) != len(rows):
                raise ValueError(f'Saved {parent} contains duplicate identities/names')
            return rows
        platforms = records('Platforms', 'Platform', ('ID', 'Name', 'ReferencePlatform'))
        languages = records('LanguageList', 'Language', ('ID', 'Name'))
        defaults = project.findall("./PropertyList/Property[@Name='DefaultLanguage']")
        if len(defaults) != 1 or defaults[0].get('Type') != 'string' or not defaults[0].get('Value'):
            raise ValueError('Saved project lacks one explicit string DefaultLanguage')
    except SoundBankContractError:
        raise
    except (UnicodeError, ValueError, ET.ParseError) as exc:
        raise SoundBankContractError('INVALID_PROJECT_ARTIFACT', str(exc)) from exc
    if _created_project_root_identity(plan) != observed_root:
        raise SoundBankContractError('FILE_CHANGED', 'Project output root changed during verification')
    args = plan['args']
    expected_platforms = args.get('platforms', {'basePlatform': 'Windows'})
    if isinstance(expected_platforms, Mapping):
        expected_platforms = [expected_platforms]
    remaining = list(platforms)
    platform_matches = True
    # Match exact named constraints before base-only rows can consume them.
    # This changes observation matching, never the declared native row order.
    for expected in sorted(expected_platforms, key=lambda row: 'name' not in row):
        matches = [row for row in remaining if row['ReferencePlatform'] == expected['basePlatform']
            and ('name' not in expected or row['Name'] == expected['name'])]
        if not matches:
            platform_matches = False
            break
        remaining.remove(matches[0])
    platform_matches = platform_matches and not remaining
    expected_languages = args.get('languages', ['English(US)'])
    language_matches = all(name in {row['Name'] for row in languages} for name in expected_languages)
    default_matches = not expected_languages or defaults[0].get('Value') == expected_languages[0]
    unresolved = []
    # The schema permits an empty list but does not state whether the native
    # implementation creates implicit defaults. Preserve construction while
    # withholding effect acceptance until matching native semantics are known.
    for field in ('platforms', 'languages'):
        if args.get(field) == []:
            unresolved.append(f'{field}_explicit_empty_native_semantics')
    return {'kind': 'console-created-project-artifact', 'file_proof': proof,
        'project': {'id': project.get('ID'), 'name': project.get('Name')},
        'platforms': platforms, 'languages': languages, 'default_language': defaults[0].get('Value'),
        'platforms_match': platform_matches if expected_platforms else True,
        'languages_match': language_matches, 'default_language_matches': default_matches,
        'unresolved': unresolved}


CLI_CREATE_URI = 'ak.wwise.cli.createNewProject'


def prepare_cli_project_effect(uri, args, audit, version):
    """Freeze independent filesystem evidence without changing the terminal plan."""
    if uri == 'ak.wwise.cli.addNewPlatform':
        from .operation_soundbank import SoundBankContractError
        path, root = args['project'], audit['io_root']
        name = args.get('new-platform-name', args['new-platform-base'])
        before = _saved_project_snapshot(path, root, version)
        if any(row['Name'] == name for row in before['platforms']):
            raise SoundBankContractError('PLATFORM_ALREADY_EXISTS', 'The new platform must not already exist')
        source = args.get('copy-from-platform')
        if source is not None and not any(row['Name'] == source for row in before['platforms']):
            raise SoundBankContractError('MISSING_PLATFORM', 'The platform to copy settings from must exist')
        return {'uri': uri, 'version': version, 'native_args': dict(args), 'path': path, 'io_root': root,
            'name': name, 'project_before': before,
            'model_before': _model_snapshot(path, root, excluded_platform=name,
                selected_platforms=(source, name) if source is not None else ())}
    if uri != CLI_CREATE_URI:
        return None
    translated = {'path': args['project']}
    if 'platform' in args:
        platforms = args['platform']
        if isinstance(platforms, str):
            platforms = [platforms]
        translated['platforms'] = [{'basePlatform': value, 'name': value} for value in platforms]
    translated_audit = dict(audit)
    translated_audit['paths'] = [{**row, 'json_path': '$.args.path'}
        for row in audit['paths'] if row['json_path'] == '$.args.project']
    plan = prepare_console_project_creation(translated, translated_audit, version)
    return {'uri': uri, 'version': version, 'native_args': dict(args), 'creation': plan}


def validate_cli_project_effect(effect, uri, args, audit, version):
    from .operation_soundbank import SoundBankContractError
    if effect != prepare_cli_project_effect(uri, args, audit, version):
        raise SoundBankContractError('FILE_CHANGED', 'Console project/file inputs changed after Preview')


def inspect_cli_project_effect(effect):
    from pathlib import Path
    if effect['uri'] == CLI_CREATE_URI:
        observed = inspect_created_project(effect['creation'])
        # CLI create has no language option or documented language default.
        # Reuse the saved-format proof without assuming Console language semantics.
        observed['kind'] = 'cli-created-project-artifact'
        return {'observations': [observed], 'checks': [
            {'name': 'Created project name matches its exact destination',
             'passed': observed['project']['name'] == Path(effect['creation']['path']).stem},
            {'name': 'Created project contains exactly the requested platforms',
             'passed': observed['platforms_match']}],
            'unresolved': observed['unresolved']}
    if effect['uri'] == 'ak.wwise.cli.addNewPlatform':
        args, name = effect['native_args'], effect['name']
        before = effect['project_before']
        after = _saved_project_snapshot(effect['path'], effect['io_root'], effect['version'])
        source = args.get('copy-from-platform')
        old_model = effect['model_before']
        model = _model_snapshot(effect['path'], effect['io_root'], excluded_platform=name,
            selected_platforms=(source, name) if source is not None else ())
        added = [row for row in after['platforms'] if row['Name'] == name]
        checks = [
            {'name': 'Requested platform name and base were saved exactly once',
             'passed': len(added) == 1 and added[0]['ReferencePlatform'] == args['new-platform-base']},
            {'name': 'Existing project identity, platforms and languages were preserved',
             'passed': before['project'] == after['project'] and before['languages'] == after['languages']
                and before['default_language'] == after['default_language']
                and before['platforms'] == [row for row in after['platforms'] if row['Name'] != name]},
            {'name': 'Existing saved model was preserved outside the new platform',
             'passed': model['root_identity'] == old_model['root_identity']
                and {key: row['preserved_model_sha256'] for key, row in model['files'].items()}
                 == {key: row['preserved_model_sha256'] for key, row in old_model['files'].items()}}]
        unresolved = []
        if source is not None:
            expected = old_model['platform_settings'][source]
            actual = model['platform_settings'][name]
            if expected and expected == actual:
                checks.append({'name': 'Explicit source platform settings were copied throughout the saved model', 'passed': True})
            else:
                # Native may elide inherited values. That representation needs
                # matching native evidence; absence alone is not failure proof.
                conflicts = any(key in actual and actual[key] != rows for key, rows in expected.items())
                checks.append({'name': 'Copied settings contain no observed conflicting explicit values', 'passed': not conflicts})
                unresolved.append('copy_settings_inherited_or_elided_native_representation' if expected
                    else 'copy_settings_no_explicit_source_values')
        return {'observations': [{'kind': 'cli-added-platform-artifact', 'project': after,
            'saved_model_files': len(model['files']), 'copy_settings_source': source,
            'unresolved': unresolved}], 'checks': checks, 'unresolved': unresolved}
    raise ValueError('Unknown Console project/file effect')


MAX_MODEL_FILES = 512
MAX_MODEL_DIRECTORIES = 2048
MAX_MODEL_ENTRIES = 16384
MAX_MODEL_BYTES = 32 * 1024 * 1024
MAX_MODEL_SNAPSHOT_BYTES = 512 * 1024


def _read_xml_artifact(path, root):
    """Stable, confined UTF-8 XML observation shared by project/file effects."""
    import hashlib
    import os
    from xml.etree import ElementTree as ET
    from .operation_soundbank import SoundBankContractError, capture_file_proof, open_regular_artifact_file
    proof = capture_file_proof(path, field='project model', max_bytes=MAX_PROJECT_FILE_BYTES, io_root=root)
    _, descriptor, before = open_regular_artifact_file(path, field='project model', io_root=root)
    with os.fdopen(descriptor, 'rb') as opened:
        raw = opened.read(MAX_PROJECT_FILE_BYTES + 1)
        after = os.fstat(opened.fileno())
    if (len(raw) != proof['size'] or hashlib.sha256(raw).hexdigest() != proof['sha256']
            or any(getattr(before, key) != getattr(after, key)
                for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
            or capture_file_proof(path, field='project model', max_bytes=MAX_PROJECT_FILE_BYTES, io_root=root) != proof):
        raise SoundBankContractError('FILE_CHANGED', 'Project model changed during its bounded observation')
    try:
        text = raw.decode('utf-8-sig')
        if '\x00' in text or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise ValueError('Project model must be UTF-8 XML without DTD/entities')
        parser = ET.XMLPullParser(events=('start', 'end'))
        document, count, depth = None, 0, 0
        for offset in range(0, len(text), 65536):
            parser.feed(text[offset:offset + 65536])
            for event, node in parser.read_events():
                if event == 'start':
                    count, depth = count + 1, depth + 1
                    if document is None:
                        document = node
                    if count > MAX_PROJECT_XML_NODES or depth > MAX_PROJECT_XML_DEPTH:
                        raise SoundBankContractError('LIMIT_EXCEEDED', 'Project model XML exceeds its node/depth limit')
                else:
                    depth -= 1
        parser.close()
        if document is None or document.tag != 'WwiseDocument':
            raise ValueError('Project model lacks WwiseDocument')
        return document, proof
    except (UnicodeError, ValueError, ET.ParseError) as exc:
        raise SoundBankContractError('INVALID_PROJECT_ARTIFACT', str(exc)) from exc


def _xml_value(node, *, excluded_platform=None, document_root=False):
    if excluded_platform is not None and (node.get('Platform') == excluded_platform
            or node.tag == 'Platform' and node.get('Name') == excluded_platform):
        return None
    excluded = {'WwiseVersion', 'WwiseBuild', 'SchemaVersion'} if document_root else set()
    return [node.tag, sorted((k, v) for k, v in node.attrib.items() if k not in excluded),
        (node.text or '').strip(), [value for child in node
            if (value := _xml_value(child, excluded_platform=excluded_platform)) is not None]]


def _model_snapshot(project_path, root, *, excluded_platform=None, selected_platforms=()):
    import hashlib
    import json
    import os
    from pathlib import Path
    from .filesystem_security import metadata_is_link_or_reparse
    from .operation_soundbank import SoundBankContractError, prove_artifact_path
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    identity = _project_io_root_identity(root)
    files, directories, entries = [str(project_path)], 0, 0
    try:
        def walk_error(exc):
            raise SoundBankContractError('INVALID_IO_ROOT', 'Project model directory cannot be enumerated') from exc
        for directory, children, names in os.walk(root, followlinks=False, onerror=walk_error):
            directories += 1
            entries += len(children) + len(names)
            if directories > MAX_MODEL_DIRECTORIES or entries > MAX_MODEL_ENTRIES:
                raise SoundBankContractError('LIMIT_EXCEEDED', 'Project model exceeds its directory/entry observation budget')
            for child in children:
                path = Path(directory) / child
                if metadata_is_link_or_reparse(path.lstat()):
                    raise SoundBankContractError('SYMLINK_NOT_ALLOWED', 'Project model cannot traverse linked directories')
            for name in names:
                if name.casefold().endswith('.wwu'):
                    files.append(str(Path(directory) / name))
                    if len(files) > MAX_MODEL_FILES:
                        raise SoundBankContractError('LIMIT_EXCEEDED', 'Project model exceeds its Work Unit observation budget')
    except OSError as exc:
        raise SoundBankContractError('INVALID_IO_ROOT', 'Project model directory metadata cannot be observed') from exc
    summary = {'files': {}, 'platform_settings': {name: {} for name in selected_platforms}, 'anchors': {}, 'media_ids': {}}
    total_bytes = 0
    for path in sorted(files):
        prove_artifact_path(path, io_root=root, field='project model', must_exist=True, expect_directory=False)
        document, proof = _read_xml_artifact(path, root)
        total_bytes += proof['size']
        if total_bytes > MAX_MODEL_BYTES:
            raise SoundBankContractError('LIMIT_EXCEEDED', 'Project model exceeds its total byte observation budget')
        relative = str(Path(path).relative_to(root))
        summary['files'][relative] = {'proof': proof,
            'preserved_model_sha256': digest(_xml_value(document, excluded_platform=excluded_platform, document_root=True)),
            'wwise_version': document.get('WwiseVersion')}
        def visit(node, context, owner):
            label = (node.tag, node.get('ID', ''), node.get('Name', ''))
            current = [*context, label]
            if node.get('ID', '').startswith('{') and node.tag not in {'ObjectRef', 'MediaID', 'Platform'}:
                owner = node.get('ID').upper()
                summary['anchors'].setdefault(relative, []).append([node.tag, owner, node.get('Name')])
            platform = node.get('Platform')
            if platform in selected_platforms:
                key = digest([relative, context, node.tag, sorted((k, v) for k, v in node.attrib.items() if k != 'Platform')])
                value = _xml_value(node)
                value[1] = [(k, v) for k, v in value[1] if k != 'Platform']
                summary['platform_settings'][platform].setdefault(key, []).append(digest(value))
            if node.tag == 'MediaID':
                summary['media_ids'].setdefault(relative, []).append([owner, sorted(node.attrib.items())])
            for child in node:
                visit(child, current, owner)
        visit(document, [], None)
    for rows in summary['anchors'].values():
        rows.sort(key=repr)
    for rows in summary['media_ids'].values():
        rows.sort(key=repr)
    for values in summary['platform_settings'].values():
        for rows in values.values():
            rows.sort()
    if _project_io_root_identity(root) != identity:
        raise SoundBankContractError('FILE_CHANGED', 'Project model root changed during observation')
    if len(json.dumps(summary, ensure_ascii=False).encode()) > MAX_MODEL_SNAPSHOT_BYTES:
        raise SoundBankContractError('LIMIT_EXCEEDED', 'Project model snapshot exceeds its bounded evidence budget')
    return {'root_identity': identity, **summary}


def _saved_project_snapshot(path, root, version):
    observed = inspect_created_project({'path': path, 'io_root': root, 'root_identity': _project_io_root_identity(root),
        'missing_root_directories': [], 'version': version, 'args': {}})
    return {key: observed[key] for key in ('project', 'platforms', 'languages', 'default_language')}
