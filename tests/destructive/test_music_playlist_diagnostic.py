"""Parent-owned, single-version discriminator; no automatic campaign selection."""
import os
from pathlib import Path
import sys
import pytest
from tests.destructive.support.music_playlist_diagnostic import run_diagnostic
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle

pytestmark = [pytest.mark.live, pytest.mark.destructive]


def make_playlist_lifecycle(root, *, live_environment):
    home = root / 'owned/wwise-user-home' if sys.platform == 'darwin' else None
    return ScenarioLifecycle(scenario_id='music-playlist-206-2025.1', version='2025.1',
        scenario_root=root, live_environment=live_environment,
        launch_environment_overrides={'HOME': str(home)} if home else None,
        owned_wine_prefix=home / 'Library/Application Support/Wwise2019/Bottles/Wwise2019x64' if home else None)


def test_2025_music_playlist_order_discriminator():
    if os.environ['WWISE_VERSION'] != '2025.1':
        pytest.skip('One 2025.1 discriminator only')
    root_text = os.environ.get('WAAPI_MUSIC_PLAYLIST_PROBE_ROOT')
    if not root_text:
        pytest.skip('Requires a parent-selected fresh WAAPI_MUSIC_PLAYLIST_PROBE_ROOT')
    root = Path(root_text)
    assert root.is_absolute() and not root.exists()
    run_diagnostic(make_playlist_lifecycle(root, live_environment=dict(os.environ)))
