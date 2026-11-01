"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

from pathlib import Path

import gzip

import hashlib

import json

import os

import shutil

import pytest

from tests.maintenance.branch_coverage_audit import digest, load

from tests.support.platform_filesystem import create_symlink_or_skip

ROOT = Path(__file__).parents[2]

def test_representative_new_condition_creation_and_verified_configuration(tmp_path):
    """Actual public Gateway code path; injected Wwise boundary, no native credit."""
    from tests.unit.test_new_object_conditions_gateway import ClassTask, restart, CREATED, EXISTING
    for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'):
        path = tmp_path / version; path.mkdir()
        task = ClassTask(path, version)
        before = deepcopy(task.objects[EXISTING])
        # Missing default requires user intent. Rejection is not constructor proof.
        del task.metadata['TimeModLoops']['default']
        task.declare(EnvelopeStopPlayback=False)
        code, rejected = task.step('draft-check')
        assert code == 2 and 'REFERENCE_ACTIVATION_REQUIRED' in str(rejected)
        assert CREATED not in task.objects
        restart(task, 'object.create')
        task.declare(EnvelopeStopPlayback=False, TimeModLoops=5)
        code, created = task.transaction('ask_before_changes')
        assert code == 0 and created['verified'] is True, created
        creation = created['transaction_id']
        restart(task, 'object.setProperty')
        code, bound = task.step('draft-bind-object', '--verified-created-from', creation)
        assert code == 0, bound
        handle = bound['bound_object']['handle']
        field = task.discover(handle, 'EnvelopeStopPlayback')
        code, declared = task.step('draft-declare-field-change', '--object-handle', handle,
            '--field-handle', field, '--business-value', 'true')
        assert code == 0, declared
        code, configured = task.transaction('ask_before_changes')
        assert code == 0 and configured['verified'] is True, configured
        assert configured['transaction_id'] != creation
        assert task.objects[EXISTING] == before
        assert task.objects[CREATED]['EnvelopeStopPlayback'] is True
        assert task.objects[CREATED]['TimeModLoops'] == 5
        writes = [{'uri': u, 'args': a, 'options': o} for u, a, o in task.calls
                  if u.endswith(('object.create', 'setProperty'))]
        assert len(writes) == 2
