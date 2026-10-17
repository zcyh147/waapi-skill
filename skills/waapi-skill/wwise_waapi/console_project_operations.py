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
