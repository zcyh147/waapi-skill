"""Explicit one-shot 2025.1 Console maintainer diagnostic, never public credit."""
import os
from pathlib import Path
import sys

import pytest

from tests.destructive.support.object_constructor_collision import run_diagnostic
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle

pytestmark = [pytest.mark.live, pytest.mark.destructive]


def test_2025_object_constructor_collision_diagnostic():
    if os.environ['WWISE_VERSION'] != '2025.1':
        pytest.skip('constructor collision diagnostic is scoped to 2025.1')
    root_text = os.environ.get('WAAPI_OBJECT_COLLISION_PROBE_ROOT')
    if not root_text:
        pytest.skip('requires a new explicit WAAPI_OBJECT_COLLISION_PROBE_ROOT')
    root = Path(root_text)
    assert root.is_absolute() and not root.exists()
    private_home = root / 'owned/wwise-user-home' if sys.platform == 'darwin' else None
    prefix = private_home / 'Library/Application Support/Wwise2019/Bottles/Wwise2019x64' if private_home else None
    lifecycle = ScenarioLifecycle(
        scenario_id='object-constructor-collision-2025.1', version='2025.1',
        scenario_root=root, live_environment=dict(os.environ),
        launch_environment_overrides={'HOME': str(private_home)} if private_home else None,
        owned_wine_prefix=prefix,
    )
    run_diagnostic(lifecycle)
