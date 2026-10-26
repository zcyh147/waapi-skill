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
CONSOLE_PROJECT_LOAD_URIS = frozenset({
    'ak.wwise.console.project.create', 'ak.wwise.console.project.open',
})
PROJECT_FILE_URIS = CLI_PROJECT_FILE_URIS | CONSOLE_PROJECT_URIS
_MEDIA_ID_URIS = frozenset({
    'ak.wwise.cli.moveMediaIdsToSingleFile',
    'ak.wwise.cli.moveMediaIdsToWorkUnits',
    'ak.wwise.cli.updateMediaIdsInSingleFile',
})


def exact_console_project_absence(call: Mapping[str, Any], version: str, live_info: Mapping[str, Any] | None) -> bool:
    """Recognize the owned native error, never a transport error or message match."""
    import re
    if version not in {'2023.1', '2024.1', '2025.1'} or not isinstance(live_info, Mapping):
        return False
    details = call.get('waapi_error_details')
    native = details.get('details') if isinstance(details, Mapping) else None
    runtime = live_info.get('version')
    session = live_info.get('sessionId')
    return bool(call.get('ok') is False and call.get('api') == 'ak.wwise.core.getProjectInfo'
        and call.get('version') == version and call.get('failure_origin') == 'exception'
        and call.get('error_code') == 'WaapiRequestFailed'
        and call.get('waapi_error_uri') == 'ak.wwise.no_project_loaded'
        and isinstance(native, Mapping) and native.get('procedureUri') == 'ak.wwise.core.getProjectInfo'
        and live_info.get('isCommandLine') is True
        and isinstance(session, str) and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}', session)
        and session != '{00000000-0000-0000-0000-000000000000}'
        and type(live_info.get('processId')) is int and live_info['processId'] > 0
        and isinstance(live_info.get('processPath'), str) and bool(live_info['processPath'].strip())
        and isinstance(runtime, Mapping) and type(runtime.get('year')) is int and runtime['year'] == int(version[:4])
        and type(runtime.get('major')) is int and runtime['major'] == 1
        and type(runtime.get('build')) is int and runtime['build'] > 0
        and isinstance(runtime.get('displayName'), str) and bool(runtime['displayName']))


def observe_cli_project_outcome(uri: str, version: str, result: Any) -> dict[str, Any]:
    """Interpret only documented exit outcomes, separately from file effects.

    processResultCli in each pinned definition describes 0 success, 1 errors
    (possibly warnings), and 2 warnings only. Earlier media-ID schemas declare
    an empty result. Matching 2021–2023 native move-to-single-file observations
    also returned the process result; retain both shapes without inferring an
    exit code from an empty result. Neither shape proves file effects.
    """
    if uri not in CLI_PROJECT_FILE_URIS:
        raise ValueError('Not an owned Console project/file command')
    if uri in _MEDIA_ID_URIS and version in {'2021.1', '2022.1', '2023.1'}:
        if isinstance(result, Mapping) and not result:
            return {'kind': 'cli-process-outcome', 'uri': uri, 'version': version,
                'outcome': 'not_reported', 'business_effect_proven': False}
        if (uri != 'ak.wwise.cli.moveMediaIdsToSingleFile'
                or not isinstance(result, Mapping) or set(result) != {'result'}):
            raise ValueError('This version returns no process outcome; expected its empty result object')
    code = result.get('result') if isinstance(result, Mapping) else None
    if isinstance(code, bool) or not isinstance(code, (int, float)) or code not in (0, 1, 2):
        raise ValueError('The native process result is not one of the documented outcomes 0, 1, or 2')
    return {'kind': 'cli-process-outcome', 'uri': uri, 'version': version,
        'exit_code': code, 'outcome': {0: 'success', 1: 'errors', 2: 'warnings_only'}[code],
        'reported_errors': code == 1, 'business_effect_proven': False,
        'partial_effects_possible': code == 1, 'automatic_retry': False}


CONSOLE_CREATE_URI = 'ak.wwise.console.project.create'
AUTHORING_CREATE_URI = 'ak.wwise.ui.project.create'
PROJECT_CREATE_URIS = frozenset({CONSOLE_CREATE_URI, AUTHORING_CREATE_URI})
MAX_PROJECT_FILE_BYTES = 8 * 1024 * 1024
MAX_PROJECT_XML_NODES = 32768
MAX_PROJECT_XML_DEPTH = 64
MAX_OBJECT_DUMP_JSON_DEPTH = 64
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


def prepare_console_project_creation(args: Mapping[str, Any], audit: Mapping[str, Any], version: str, *, uri: str = CONSOLE_CREATE_URI) -> dict[str, Any]:
    from pathlib import Path
    from .operation_soundbank import SoundBankContractError, prove_artifact_path

    if uri not in PROJECT_CREATE_URIS:
        raise ValueError('Not a reviewed saved-project creation URI')
    paths = [row for row in audit['paths'] if row['json_path'] == '$.args.path']
    if len(paths) != 1:
        raise SoundBankContractError('INVALID_PATH', 'Project creation requires its exact isolated output path')
    path, root = paths[0]['resolved_path'], audit['io_root']
    if uri == AUTHORING_CREATE_URI and Path(path).stem != Path(path).parent.name:
        raise SoundBankContractError('INVALID_PROJECT_PATH', 'Authoring creation requires matching project-file and parent-directory names')
    ancestor, missing = _project_creation_ancestor(root)
    before = prove_artifact_path(path, io_root=ancestor['resolved_path'], field='new project', must_exist=False, expect_directory=False)
    if before['exists']:
        raise SoundBankContractError('PROJECT_ALREADY_EXISTS', 'New project creation cannot replace an existing file')
    return {'kind': 'authoring-project-create' if uri == AUTHORING_CREATE_URI else 'console-project-create', 'uri': uri, 'version': version,
        'args': dict(args), 'path': path, 'io_root': root, 'root_identity': ancestor,
        'missing_root_directories': missing, 'before': before}


def validate_console_project_creation(plan, args, audit, version, *, uri=CONSOLE_CREATE_URI):
    from .operation_soundbank import SoundBankContractError

    if dict(plan) != prepare_console_project_creation(args, audit, version, uri=uri):
        raise SoundBankContractError('FILE_CHANGED', 'Project destination or its isolated path changed after Preview')


def _read_saved_project_document(path: str, root: str):
    """One bounded regular-file/XML observer shared by create and open."""
    import hashlib
    import os
    import re
    from xml.etree import ElementTree as ET
    from .operation_soundbank import SoundBankContractError, capture_file_proof, open_regular_artifact_file, prove_artifact_path

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
        if document is None or document.tag != 'WwiseDocument' or document.get('Type') != 'Project':
            raise ValueError('Saved artifact does not identify a Wwise project')
        projects = document.findall('./ProjectInfo/Project')
        if len(document.findall('ProjectInfo')) != 1 or len(projects) != 1:
            raise ValueError('Saved project must contain exactly one ProjectInfo/Project')
        project = projects[0]
        if not re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}', project.get('ID', '')) or not project.get('Name'):
            raise ValueError('Saved project lacks its explicit GUID/name identity')
        return proof, document, project
    except SoundBankContractError:
        raise
    except (UnicodeError, ValueError, ET.ParseError) as exc:
        raise SoundBankContractError('INVALID_PROJECT_ARTIFACT', str(exc)) from exc


def prepare_console_project_open(args: Mapping[str, Any], audit: Mapping[str, Any], version: str) -> dict[str, Any]:
    from .operation_soundbank import SoundBankContractError
    paths = [row for row in audit['paths'] if row['json_path'] == '$.args.path']
    if len(paths) != 1:
        raise SoundBankContractError('INVALID_PATH', 'Console open requires its exact isolated project input')
    path, root = paths[0]['resolved_path'], audit['io_root']
    proof, _document, project = _read_saved_project_document(path, root)
    # Opening can migrate an older project. Its GUID/name remain the selected
    # identity; requiring the input's engine version to equal the host is wrong.
    return {'kind': 'console-project-open', 'uri': 'ak.wwise.console.project.open', 'version': version,
        'args': dict(args), 'path': path, 'io_root': root, 'file_proof': proof,
        'project': {'id': project.get('ID'), 'name': project.get('Name')}}


def validate_console_project_open(plan, args, audit, version):
    from .operation_soundbank import SoundBankContractError
    if dict(plan) != prepare_console_project_open(args, audit, version):
        raise SoundBankContractError('FILE_CHANGED', 'Selected project input identity or bytes changed after Preview')


def inspect_created_project(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Read the bounded saved project; no endpoint calls or inferred native classes.

    ProjectInfo/Project, Platforms, LanguageList and DefaultLanguage are the
    explicit format in the matching five-lane packaged SDK project samples.
    Source-format evidence is separate from native execution/effect evidence.
    """
    import re
    from xml.etree import ElementTree as ET
    from .operation_soundbank import SoundBankContractError

    path, root = plan['path'], plan['io_root']
    observed_root = _created_project_root_identity(plan)
    proof, document, project = _read_saved_project_document(path, root)
    try:
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
    return {'kind': 'authoring-created-project-artifact' if plan.get('uri') == AUTHORING_CREATE_URI else 'console-created-project-artifact', 'file_proof': proof,
        'project': {'id': project.get('ID'), 'name': project.get('Name')},
        'platforms': platforms, 'languages': languages, 'default_language': defaults[0].get('Value'),
        'platforms_match': platform_matches if expected_platforms else True,
        'languages_match': language_matches, 'default_language_matches': default_matches,
        'unresolved': unresolved}


CLI_CREATE_URI = 'ak.wwise.cli.createNewProject'


def prepare_cli_project_effect(uri, args, audit, version):
    """Freeze independent filesystem evidence without changing the terminal plan."""
    if uri in _MEDIA_ID_URIS:
        from pathlib import Path
        from .operation_soundbank import capture_file_proof, prove_artifact_path
        path, root = args['project'], audit['io_root']
        mapping = str(Path(path).with_suffix('.mediaid'))
        mapping_before = prove_artifact_path(mapping, io_root=root, field='media ID mapping', must_exist=False, expect_directory=False)
        if mapping_before['exists']:
            mapping_before = {**mapping_before, 'file_proof': capture_file_proof(mapping,
                field='media ID mapping', max_bytes=MAX_PROJECT_FILE_BYTES, io_root=root),
                'observation': _media_mapping_snapshot(mapping, root)}
            if mapping_before['file_proof'] != mapping_before['observation']['file_proof']:
                from .operation_soundbank import SoundBankContractError
                raise SoundBankContractError('FILE_CHANGED', 'Media mapping changed during Preview observation')
        return {'uri': uri, 'version': version, 'native_args': dict(args), 'path': path, 'io_root': root,
            'mapping_path': mapping, 'mapping_before': mapping_before,
            'project_before': _saved_project_snapshot(path, root, version),
            'model_before': _model_snapshot(path, root, exclude_media_storage=True,
                none_state_version=version if uri == 'ak.wwise.cli.moveMediaIdsToSingleFile' else None)}
    if uri == 'ak.wwise.cli.migrate':
        import re
        from .operation_soundbank import SoundBankContractError
        path, root = args['project'], audit['io_root']
        document, _ = _read_xml_artifact(path, root)
        match = re.fullmatch(r'v(\d{4}\.\d+)\..+', document.get('WwiseVersion', ''))
        if match is None:
            raise SoundBankContractError('INVALID_PROJECT_ARTIFACT', 'Migration input lacks its explicit saved Wwise version')
        return {'uri': uri, 'version': version, 'native_args': dict(args), 'path': path, 'io_root': root,
            'project_before': _saved_project_snapshot(path, root, match.group(1)),
            'model_before': _model_snapshot(path, root)}
    if uri == 'ak.wwise.cli.dumpObjects':
        from pathlib import Path
        from .operation_soundbank import capture_file_proof, prove_artifact_path
        root = audit['io_root']
        ancestor, missing = _project_creation_ancestor(root)
        before = prove_artifact_path(args['output'], io_root=ancestor['resolved_path'],
            field='object dump', must_exist=False, expect_directory=False)
        if before['exists']:
            before = capture_file_proof(args['output'], field='object dump',
                max_bytes=MAX_PROJECT_FILE_BYTES, io_root=root)
        input_root = str(Path(args['project']).parent)
        return {'uri': uri, 'version': version, 'native_args': dict(args), 'path': args['output'],
            'io_root': root, 'root_identity': ancestor, 'missing_root_directories': missing, 'before': before,
            'input_root_identity': _project_io_root_identity(input_root),
            'input_proof': capture_file_proof(args['project'], field='dump input project',
                max_bytes=MAX_PROJECT_FILE_BYTES, io_root=input_root)}
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
                selected_platforms=(source, name) if source is not None else (name,))}
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
    if effect['uri'] in _MEDIA_ID_URIS:
        from .operation_soundbank import SoundBankContractError, prove_artifact_path
        old_model = effect['model_before']
        model = _model_snapshot(effect['path'], effect['io_root'], exclude_media_storage=True,
            none_state_expected=old_model.get('optional_none_state_materialization'))
        remainder = model.get('none_state_remainder', model)
        remaining_preserved = (model['root_identity'] == old_model['root_identity']
            and old_model['anchors'] == remainder['anchors']
            and {key: row['preserved_model_sha256'] for key, row in remainder['files'].items()}
             == {key: row['preserved_model_sha256'] for key, row in old_model['files'].items()})
        none_observations = []
        if 'none_state_remainder' in model:
            none_observations = [{'kind': 'optional-none-custom-state-materialization',
                'actual_additions': model['none_state_additions'], 'actual_addition_count': len(model['none_state_additions']),
                'actual_additions_complete': remaining_preserved,
                'recognized_additions_complete': True, 'remaining_model_preserved': remaining_preserved,
                'actual_addition_count_scope': 'recognized_empty_None_saved_records; unexpected_differences_fail_preservation',
                'source': old_model['optional_none_state_materialization']['source'],
                'freshness_proof': ('canonical_GUID_occurs_only_at_new_definition_in_complete_observed_model_and_strict_old_remainder_preserved'
                    if remaining_preserved else 'not_established_for_complete_difference; recognized_candidates_have_unique_GUID_occurrences'),
                'added_saved_model_identities_observed': bool(model['none_state_additions']) and remaining_preserved,
                'observation_scope': 'saved_project_and_bounded_Work_Unit_XML; live_object_creation_not_observed'}]
        project = _saved_project_snapshot(effect['path'], effect['io_root'], effect['version'])
        mapping = prove_artifact_path(effect['mapping_path'], io_root=effect['io_root'],
            field='media ID mapping', must_exist=False, expect_directory=False)
        source_count = sum(rows['count'] for rows in old_model['media_ids'].values())
        if (effect['uri'].endswith('moveMediaIdsToSingleFile') and source_count > 0
                or effect['uri'].endswith('updateMediaIdsInSingleFile') and effect['mapping_before']['exists']) and not mapping['exists']:
            raise SoundBankContractError('MISSING_ARTIFACT', 'Requested media ID mapping artifact is missing')
        if mapping['exists']:
            mapping = _media_mapping_snapshot(effect['mapping_path'], effect['io_root'])
        unresolved = ['central_media_id_mapping_representation']
        mapping_checks = []
        if mapping.get('format') == 'wwise-media-ids-xml' and effect['uri'].endswith('moveMediaIdsToSingleFile'):
            unresolved = sorted(set(old_model['media_mapping_unresolved'] + model['media_mapping_unresolved']))
            expected = old_model['media_mapping']
            if old_model['media_storage_mode'] is True:
                previous = effect['mapping_before'].get('observation', {})
                if previous.get('format') == 'wwise-media-ids-xml' and source_count == 0:
                    expected = previous['records']
                else:
                    unresolved.append('mixed_or_unestablished_previous_media_storage')
            mapping_checks = [
                {'name': 'Central mapping preserves every source, language, filename and media ID',
                 'passed': mapping['records'] == expected
                    and mapping['sources'] == old_model['media_sources'] == model['media_sources']},
                {'name': 'Media IDs moved out of Work Units and project storage mode is enabled',
                 'passed': model['media_mapping']['count'] == 0
                    and sum(row['count'] for row in model['media_ids'].values()) == 0
                    and model['media_storage_mode'] is True},
            ]
        elif effect['uri'].endswith('moveMediaIdsToWorkUnits'):
            previous = effect['mapping_before'].get('observation', {})
            if previous.get('format') == 'wwise-media-ids-xml':
                unresolved = sorted(set(old_model['media_mapping_unresolved'] + model['media_mapping_unresolved']))
                if old_model['media_storage_mode'] is not True or source_count != 0:
                    unresolved.append('mixed_or_unestablished_previous_media_storage')
                mapping_checks = [
                    {'name': 'Work Units preserve every central source, language, filename and media ID',
                     'passed': model['media_mapping'] == previous['records']
                        and previous['sources'] == old_model['media_sources'] == model['media_sources']
                        and sum(row['count'] for row in model['media_ids'].values()) == previous['records']['count']},
                    {'name': 'Project media storage mode is disabled after transfer to Work Units',
                     'passed': model['media_storage_mode'] is False},
                ]
        elif effect['uri'].endswith('updateMediaIdsInSingleFile'):
            unresolved = sorted(set(old_model['media_mapping_unresolved'] + model['media_mapping_unresolved']))
            mapping_checks = [
                {'name': 'Refreshing the central file preserves Work Unit media IDs and project storage mode',
                 'passed': old_model['media_ids'] == model['media_ids']
                    and old_model['media_mapping'] == model['media_mapping']
                    and old_model['media_storage_mode'] == model['media_storage_mode']},
            ]
            if not effect['mapping_before']['exists']:
                mapping_checks.append({'name': 'Refresh leaves an absent central media ID file absent',
                    'passed': mapping['exists'] is False})
            elif mapping.get('format') == 'wwise-media-ids-xml':
                expected = old_model['media_mapping']
                if old_model['media_storage_mode'] is True:
                    previous = effect['mapping_before'].get('observation', {})
                    if previous.get('format') == 'wwise-media-ids-xml' and source_count == 0:
                        expected = previous['records']
                    else:
                        unresolved.append('mixed_or_unestablished_previous_media_storage')
                mapping_checks.append({
                    'name': 'Refreshed central mapping matches every saved source, language, filename and media ID',
                    'passed': mapping['records'] == expected
                        and mapping['sources'] == old_model['media_sources'] == model['media_sources']})
            else:
                unresolved.append('central_media_id_mapping_representation')
        return {'observations': [{'kind': 'cli-media-id-artifacts', 'mapping_file': mapping,
            'saved_model_files': len(model['files']), 'work_unit_media_id_count_before': source_count,
            'work_unit_media_id_count_after': sum(rows['count'] for rows in model['media_ids'].values()),
            'project_storage_mode_before': old_model.get('media_storage_observation'),
            'project_storage_mode_after': model.get('media_storage_observation'),
            'unresolved': unresolved}, *none_observations], 'checks': [
            {'name': 'Project identity, platforms and languages were preserved during media ID maintenance',
                'passed': project == effect['project_before']},
            {'name': 'Remaining model preserved outside media storage and explicitly reported optional None CustomState additions'
                    if none_observations else 'Model content outside the requested media ID storage fields was preserved',
                'passed': remaining_preserved}, *mapping_checks],
            'unresolved': unresolved}
    if effect['uri'] == 'ak.wwise.cli.migrate':
        before = effect['project_before']
        after = _saved_project_snapshot(effect['path'], effect['io_root'], effect['version'])
        old_model = effect['model_before']
        model = _model_snapshot(effect['path'], effect['io_root'])
        existing_files = set(old_model['files']) <= set(model['files'])
        checks = [
            {'name': 'Migrated project identity, platforms and languages were preserved', 'passed': before == after},
            {'name': 'Existing saved Work Units and object identities were preserved',
             'passed': existing_files and old_model['anchors'] == model['anchors']
                and old_model['media_ids'] == model['media_ids']},
            {'name': 'Migration remained in its original owned project directory',
             'passed': old_model['root_identity'] == model['root_identity']}]
        unresolved = []
        if {key: row['preserved_model_sha256'] for key, row in model['files'].items()} != {
                key: row['preserved_model_sha256'] for key, row in old_model['files'].items()}:
            unresolved.append('migration_model_transformation_semantics')
        if all(model['files'].get(key, {}).get('proof') == row['proof'] for key, row in old_model['files'].items()):
            unresolved.append('migration_save_has_no_observed_write')
        return {'observations': [{'kind': 'cli-migrated-project-artifact', 'project': after,
            'target_version': effect['version'], 'saved_model_files': len(model['files']),
            'source_file_versions': sorted({row['wwise_version'] for row in old_model['files'].values()}, key=str),
            'unresolved': unresolved}], 'checks': checks, 'unresolved': unresolved}
    if effect['uri'] == 'ak.wwise.cli.dumpObjects':
        from .operation_soundbank import SoundBankContractError, capture_file_proof, prove_artifact_path
        _created_project_root_identity(effect)
        target = prove_artifact_path(effect['path'], io_root=effect['io_root'],
            field='object dump', must_exist=False, expect_directory=False)
        if not target['exists']:
            raise SoundBankContractError('MISSING_ARTIFACT', 'Requested object dump file is missing')
        raw, proof = _read_bounded_artifact(effect['path'], effect['io_root'])
        _, json_observation = inspect_object_dump_artifact(raw)
        input_root = effect['input_root_identity']['resolved_path']
        input_proof = capture_file_proof(effect['native_args']['project'], field='dump input project',
            max_bytes=MAX_PROJECT_FILE_BYTES, io_root=input_root)
        unresolved = ['object_model_content_and_session_representation']
        if proof == effect['before']:
            unresolved.append('preexisting_dump_file_has_no_observed_new_write')
        return {'observations': [{'kind': 'cli-object-dump-artifact', 'file_proof': proof,
            'json_valid': True, **json_observation, 'requested_content': effect['native_args'].get('content', 'name'),
            'unresolved': unresolved}], 'checks': [
            {'name': 'Dump source project bytes and directory identity were preserved', 'passed':
                _project_io_root_identity(input_root) == effect['input_root_identity']
                and all(input_proof[key] == effect['input_proof'][key] for key in ('size', 'sha256'))}],
            'unresolved': unresolved}
    if effect['uri'] == 'ak.wwise.cli.addNewPlatform':
        args, name = effect['native_args'], effect['name']
        before = effect['project_before']
        after = _saved_project_snapshot(effect['path'], effect['io_root'], effect['version'])
        source = args.get('copy-from-platform')
        old_model = effect['model_before']
        model = _model_snapshot(effect['path'], effect['io_root'], excluded_platform=name,
            selected_platforms=(source, name) if source is not None else (name,))
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
        unresolved = (['preexisting_unregistered_platform_values']
            if old_model['platform_settings'][name] else [])
        copy_settings = None
        if source is not None:
            from .console_platform_copy import compare_platform_copy
            source_base = next(row['ReferencePlatform'] for row in before['platforms'] if row['Name'] == source)
            copy_settings = compare_platform_copy(old_model['platform_copy'], model['platform_copy'], source, name,
                cross_base=source_base != args['new-platform-base'])
            required = copy_settings['required_entries']
            conflicts = (copy_settings['conflicting_entries'] or copy_settings['unexpected_entries']
                or not copy_settings['codec_identities_valid'])
            fallback = copy_settings['native_fallback_uncertain_entries']
            if required and not conflicts and not copy_settings['missing_entries'] and not fallback:
                checks.append({'name': 'Explicit source platform settings were copied throughout the saved model', 'passed': True})
            else:
                # Native may elide inherited values. That representation needs
                # matching native evidence; absence alone is not failure proof.
                checks.append({'name': 'Copied settings contain no observed conflicting explicit values', 'passed': not conflicts})
                unresolved.append('copy_settings_cross_base_native_fallback_unestablished' if fallback else
                    'copy_settings_inherited_or_elided_native_representation' if required else
                    'copy_settings_no_explicit_source_values')
        return {'observations': [{'kind': 'cli-added-platform-artifact', 'project': after,
            'saved_model_files': len(model['files']), 'copy_settings_source': source,
            **({'copy_settings': copy_settings} if copy_settings is not None else {}),
            'unresolved': unresolved}], 'checks': checks, 'unresolved': unresolved}
    raise ValueError('Unknown Console project/file effect')


MAX_MODEL_FILES = 512
MAX_MODEL_DIRECTORIES = 2048
MAX_MODEL_DEPTH = 64
MAX_MODEL_ENTRIES = 16384
MAX_MODEL_BYTES = 32 * 1024 * 1024
MAX_MODEL_SNAPSHOT_BYTES = 512 * 1024


def _media_mapping_snapshot(path, root):
    from .console_media_ids import mapping_records, compact_records
    from .operation_soundbank import SoundBankContractError
    _, proof = _read_bounded_artifact(path, root)
    observation = {'exists': True, 'file_proof': proof, 'format': 'unestablished'}
    try:
        document, parsed_proof = _read_xml_artifact(path, root, require_wwise_document=False)
    except SoundBankContractError as exc:
        if exc.error_code != 'INVALID_PROJECT_ARTIFACT':
            raise
        return observation
    if parsed_proof != proof:
        raise SoundBankContractError('FILE_CHANGED', 'Media mapping changed while its representation was observed')
    try:
        records = mapping_records(document)
    except ValueError as exc:
        raise SoundBankContractError('INVALID_PROJECT_ARTIFACT', str(exc)) from exc
    if records is not None:
        sources = list({row[0]: row[:4] for row in records}.values())
        observation.update(format='wwise-media-ids-xml', media_count=len(records),
            records=compact_records(records), sources=compact_records(sources))
    return observation


def _read_bounded_artifact(path, root):
    """Stable, confined byte observation shared by project/file effects."""
    import hashlib
    import os
    from .operation_soundbank import SoundBankContractError, capture_file_proof, open_regular_artifact_file
    proof = capture_file_proof(path, field='project model', max_bytes=MAX_PROJECT_FILE_BYTES, io_root=root)
    _, descriptor, before = open_regular_artifact_file(path, field='project model', io_root=root)
    try:
        opened = os.fdopen(descriptor, 'rb')
    except OSError as exc:
        os.close(descriptor)
        raise SoundBankContractError('INVALID_FILE', 'Project artifact reader cannot be opened') from exc
    try:
        with opened:
            raw = opened.read(MAX_PROJECT_FILE_BYTES + 1)
            after = os.fstat(opened.fileno())
    except OSError as exc:
        raise SoundBankContractError('INVALID_FILE', 'Project artifact bytes cannot be observed') from exc
    if (len(raw) != proof['size'] or hashlib.sha256(raw).hexdigest() != proof['sha256']
            or any(getattr(before, key) != getattr(after, key)
                for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
            or capture_file_proof(path, field='project model', max_bytes=MAX_PROJECT_FILE_BYTES, io_root=root) != proof):
        raise SoundBankContractError('FILE_CHANGED', 'Project model changed during its bounded observation')
    return raw, proof


def inspect_object_dump_artifact(raw: bytes) -> tuple[Any, dict[str, int]]:
    """Inspect external JSON under its byte/depth bounds, never a reply/XML node cap."""
    import json
    import math
    from .operation_soundbank import SoundBankContractError
    if len(raw) > MAX_PROJECT_FILE_BYTES:
        raise SoundBankContractError('LIMIT_EXCEEDED', 'Object dump exceeds its artifact byte limit')

    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError('Object dump JSON contains duplicate keys')
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError('Object dump JSON contains a nonfinite number')

    try:
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=nonfinite)
    except RecursionError as exc:
        raise SoundBankContractError('LIMIT_EXCEEDED', 'Object dump exceeds JSON decoder depth resources') from exc
    except (UnicodeError, ValueError) as exc:
        raise SoundBankContractError('INVALID_PROJECT_ARTIFACT', 'Object dump is not one valid finite UTF-8 JSON document') from exc

    # Parsing and traversal are linear in the already bounded artifact bytes.
    # Iterator frames retain only the current ancestry, not every pending child.
    stack, count, deepest = [(iter((value,)), 1)], 0, 0
    while stack:
        children, depth = stack[-1]
        try:
            item = next(children)
        except StopIteration:
            stack.pop()
            continue
        count += 1
        deepest = max(deepest, depth)
        if depth > MAX_OBJECT_DUMP_JSON_DEPTH:
            raise SoundBankContractError('LIMIT_EXCEEDED', 'Object dump exceeds its JSON depth limit')
        if isinstance(item, float) and not math.isfinite(item):
            # JSONDecoder can turn a legal numeric token such as 1e999 into inf.
            raise SoundBankContractError('INVALID_PROJECT_ARTIFACT', 'Object dump contains a nonfinite numeric value')
        if isinstance(item, (dict, list)):
            stack.append((iter(item.values()) if isinstance(item, dict) else iter(item), depth + 1))
    return value, {'json_nodes': count, 'json_depth': deepest}


def _read_xml_artifact(path, root, *, require_wwise_document=True):
    from xml.etree import ElementTree as ET
    from .operation_soundbank import SoundBankContractError
    raw, proof = _read_bounded_artifact(path, root)
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
        if document is None or require_wwise_document and document.tag != 'WwiseDocument':
            raise ValueError('Project model lacks WwiseDocument')
        return document, proof
    except (UnicodeError, ValueError, ET.ParseError) as exc:
        raise SoundBankContractError('INVALID_PROJECT_ARTIFACT', str(exc)) from exc


def _xml_value(node, *, excluded_platform=None, document_root=False, exclude_media_storage=False, _path=()):
    if excluded_platform is not None and (node.get('Platform') == excluded_platform
            or node.tag == 'Platform' and node.get('Name') == excluded_platform):
        return None
    if exclude_media_storage and (node.tag == 'MediaIDList' and _path and _path[-1] in {'AudioFileSource', 'MidiFileSource', 'PluginMediaSource'}
            or node.tag == 'Property' and node.get('Name') == 'MediaIDsInSingleFile'
                and _path == ('WwiseDocument', 'ProjectInfo', 'Project', 'PropertyList')):
        return None
    # Wwise serialization may omit an empty EffectSlot/Bus ReferenceList and turn
    # a scalar Property Value attribute into one unqualified ValueList/Value.
    # Compare the exact value, type and name; never collapse platform-specific,
    # dual-encoded, attributed, nested or nonempty reference representations.
    if (node.tag == 'ReferenceList' and _path and _path[-1] in {'EffectSlot', 'Bus'}
            and not node.attrib and not len(node) and not (node.text or '').strip()):
        return None
    if (node.tag == 'Property' and _path and _path[-1] == 'PropertyList'
            and set(node.attrib) == {'Name', 'Type'} and 1 <= len(node) <= 2
            and not (node.text or '').strip()):
        value_lists = [child for child in node if child.tag == 'ValueList']
        retained = [child for child in node if child.tag != 'ValueList']
        if len(value_lists) == 1 and all(child.tag == 'RTPCList' for child in retained):
            values = value_lists[0]
            if (not values.attrib and len(values) == 1 and not (values.text or '').strip()):
                value = values[0]
                if value.tag == 'Value' and not value.attrib and not len(value):
                    # Scalar storage can change beside an RTPC binding. Preserve
                    # that entire binding, including curve, IDs and point order.
                    children = [_xml_value(child, excluded_platform=excluded_platform,
                        exclude_media_storage=exclude_media_storage, _path=(*_path, node.tag))
                        for child in retained]
                    return [node.tag, sorted([*node.attrib.items(), ('Value', value.text or '')]), '',
                        [child for child in children if child is not None]]
    children = list(node)
    if (node.tag == 'PluginInnerObjectList' and not node.attrib and not (node.text or '').strip()
            and all(child.tag == 'List' and set(child.attrib) == {'Name'} and child.get('Name')
                and not (child.text or '').strip() and not (child.tail or '').strip()
                and all(member.tag == 'PluginInnerObject' and not (member.tail or '').strip() for member in child)
                for child in children)
            and len({child.get('Name') for child in children}) == len(children)):
        # HostObjectStore.h (all five pinned SDKs): list-name enumeration is
        # arbitrary across project loads. Each named list is an indexed vector;
        # canonicalize only the outer names, retaining every inner member.
        children.sort(key=lambda child: child.get('Name'))
    excluded = {'WwiseVersion', 'WwiseBuild', 'SchemaVersion'} if document_root else set()
    return [node.tag, sorted((k, v) for k, v in node.attrib.items() if k not in excluded),
        (node.text if node.text and node.text.strip() else ''), [value for child in children
            if (value := _xml_value(child, excluded_platform=excluded_platform, exclude_media_storage=exclude_media_storage,
                _path=(*_path, node.tag))) is not None]]


def _project_model_paths(project_path, root):
    import os
    from pathlib import Path
    from .filesystem_security import metadata_is_link_or_reparse
    from .operation_soundbank import SoundBankContractError
    files, directories, entries = [str(project_path)], 0, 0
    try:
        def walk_error(exc):
            raise SoundBankContractError('INVALID_IO_ROOT', 'Project model directory cannot be enumerated') from exc
        for directory, children, names in os.walk(root, followlinks=False, onerror=walk_error):
            if len(Path(directory).relative_to(root).parts) > MAX_MODEL_DEPTH:
                raise SoundBankContractError('LIMIT_EXCEEDED', 'Project model exceeds its directory depth observation budget')
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
    return sorted(files)


def _model_snapshot(project_path, root, *, excluded_platform=None, selected_platforms=(), exclude_media_storage=False,
        none_state_version=None, none_state_expected=None):
    import hashlib
    import json
    import os
    from pathlib import Path
    from .filesystem_security import metadata_is_link_or_reparse
    from .operation_soundbank import SoundBankContractError, prove_artifact_path
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    identity = _project_io_root_identity(root)
    from .console_platform_copy import PlatformCopyObservation
    platform_copy = PlatformCopyObservation(selected_platforms, str(Path(project_path).relative_to(root)))
    files = _project_model_paths(project_path, root)
    summary = {'files': {}, 'platform_settings': {name: {} for name in selected_platforms}, 'anchors': {}, 'media_ids': {}}
    media_rows, media_sources, media_unresolved, media_mode = [], [], set(), None
    storage_observation = None
    total_bytes = 0
    documents = {}
    for path in sorted(files):
        prove_artifact_path(path, io_root=root, field='project model', must_exist=True, expect_directory=False)
        document, proof = _read_xml_artifact(path, root)
        total_bytes += proof['size']
        if total_bytes > MAX_MODEL_BYTES:
            raise SoundBankContractError('LIMIT_EXCEEDED', 'Project model exceeds its total byte observation budget')
        relative = str(Path(path).relative_to(root))
        if none_state_version is not None or none_state_expected is not None:
            documents[relative] = (document, proof)
        if exclude_media_storage:
            from .console_media_ids import work_unit_records, project_storage_observation
            rows, descriptors, unresolved = work_unit_records(document)
            media_rows.extend(rows)
            media_sources.extend(descriptors)
            media_unresolved.update(unresolved)
            if Path(path) == Path(project_path):
                try:
                    storage_observation = project_storage_observation(document)
                    media_mode = storage_observation['value']
                except ValueError:
                    media_unresolved.add('project_media_storage_mode')
        summary['files'][relative] = {'proof': proof,
            'preserved_model_sha256': digest(_xml_value(document, excluded_platform=excluded_platform, document_root=True, exclude_media_storage=exclude_media_storage)),
            'wwise_version': document.get('WwiseVersion')}
        def visit(node, context, owner, ancestors):
            label = (node.tag, node.get('ID', ''), node.get('Name', ''))
            current = [*context, label]
            if node.get('ID', '').startswith('{') and node.tag not in {'ObjectRef', 'MediaID', 'Platform'}:
                owner = node.get('ID').upper()
                summary['anchors'].setdefault(relative, []).append([node.tag, owner, node.get('Name')])
            platform = node.get('Platform')
            key, value = None, None
            if platform in selected_platforms:
                key = digest([relative, context, node.tag, sorted((k, v) for k, v in node.attrib.items() if k != 'Platform')])
                value = _xml_value(node)
                value[1] = [(k, v) for k, v in value[1] if k != 'Platform']
                summary['platform_settings'][platform].setdefault(key, []).append(digest(value))
            if selected_platforms:
                platform_copy.visit(node, ancestors, relative, key, value, digest)
            if node.tag == 'MediaID':
                summary['media_ids'].setdefault(relative, []).append([owner, [[key, value] for key, value in sorted(node.attrib.items())]])
            for child in node:
                visit(child, current, owner, [*ancestors, node])
        visit(document, [], None, [])
    # Equality guards need the complete multiset, not thousands of repeated
    # names in every immutable Preview. Hash every row (including duplicates)
    # in deterministic order; keep counts for the media observation. The file,
    # XML and total-byte limits still bound collection before this projection.
    for field in ('anchors', 'media_ids'):
        summary[field] = {relative: {'count': len(rows), 'sha256': digest(sorted(rows, key=repr))}
            for relative, rows in summary[field].items()}
    if exclude_media_storage:
        from .console_media_ids import compact_records
        summary.update(media_mapping=compact_records(media_rows), media_sources=compact_records(media_sources), media_mapping_unresolved=sorted(media_unresolved),
            media_storage_mode=media_mode, media_storage_observation=storage_observation)
    if none_state_version is not None:
        from .console_media_ids import none_state_eligibility
        summary['optional_none_state_materialization'] = none_state_eligibility(
            {key: row[0] for key, row in documents.items()}, none_state_version)
    if none_state_expected is not None:
        from .console_media_ids import project_none_state_additions
        summary['none_state_additions'] = project_none_state_additions(
            {key: row[0] for key, row in documents.items()}, none_state_expected)
        remaining = {'files': {}, 'anchors': {}}
        for relative, (document, _) in documents.items():
            remaining['files'][relative] = {'preserved_model_sha256': digest(_xml_value(document,
                excluded_platform=excluded_platform, document_root=True, exclude_media_storage=exclude_media_storage))}
            rows = [[node.tag, node.get('ID').upper(), node.get('Name')] for node in document.iter()
                if node.get('ID', '').startswith('{') and node.tag not in {'ObjectRef', 'MediaID', 'Platform'}]
            if rows:
                remaining['anchors'][relative] = {'count': len(rows), 'sha256': digest(sorted(rows, key=repr))}
        summary['none_state_remainder'] = remaining
    for values in summary['platform_settings'].values():
        for rows in values.values():
            rows.sort()
    if selected_platforms:
        summary['platform_copy'] = platform_copy.finish()
    if files != _project_model_paths(project_path, root):
        raise SoundBankContractError('FILE_CHANGED', 'Project model file membership changed during observation')
    from .operation_soundbank import capture_file_proof
    for path in files:
        relative = str(Path(path).relative_to(root))
        if capture_file_proof(path, field='project model', max_bytes=MAX_PROJECT_FILE_BYTES, io_root=root) != summary['files'][relative]['proof']:
            raise SoundBankContractError('FILE_CHANGED', 'Project model file changed during the complete snapshot')
    if _project_io_root_identity(root) != identity:
        raise SoundBankContractError('FILE_CHANGED', 'Project model root changed during observation')
    if len(json.dumps(summary, ensure_ascii=False).encode()) > MAX_MODEL_SNAPSHOT_BYTES:
        raise SoundBankContractError('LIMIT_EXCEEDED', 'Project model snapshot exceeds its bounded evidence budget')
    return {'root_identity': identity, **summary}


def _saved_project_snapshot(path, root, version):
    observed = inspect_created_project({'path': path, 'io_root': root, 'root_identity': _project_io_root_identity(root),
        'missing_root_directories': [], 'version': version, 'args': {}})
    return {key: observed[key] for key in ('project', 'platforms', 'languages', 'default_language')}
