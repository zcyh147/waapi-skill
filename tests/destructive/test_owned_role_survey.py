"""Parent-selected read-only source survey in one lifecycle-owned 2025 copy."""
import os
from pathlib import Path
import sys
import pytest

from tests.destructive.support.owned_role_survey import run_survey
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle

# Uses the destructive lane only to enforce its owned-copy launch prerequisites.
# The collector itself has no mutation URI, save, setup write or field probe.
pytestmark = [pytest.mark.live, pytest.mark.destructive]


def make_role_survey_lifecycle(root, *, live_environment):
    home = root / 'owned/wwise-user-home' if sys.platform == 'darwin' else None
    return ScenarioLifecycle(scenario_id='owned-role-survey-195-2025.1', version='2025.1',
        scenario_root=root, live_environment=live_environment,
        launch_environment_overrides={'HOME': str(home)} if home else None,
        owned_wine_prefix=home / 'Library/Application Support/Wwise2019/Bottles/Wwise2019x64' if home else None)


def test_2025_owned_role_instance_survey():
    if os.environ['WWISE_VERSION'] != '2025.1':
        pytest.skip('One 2025.1 source survey only')
    root_text = os.environ.get('WAAPI_ROLE_SURVEY_ROOT')
    if not root_text:
        pytest.skip('Requires a parent-selected fresh WAAPI_ROLE_SURVEY_ROOT')
    root = Path(root_text)
    assert root.is_absolute() and not root.exists()
    run_survey(make_role_survey_lifecycle(root, live_environment=dict(os.environ)))
