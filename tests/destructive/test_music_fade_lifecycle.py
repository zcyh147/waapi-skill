"""Explicitly selected one-version lifecycle discriminator; never auto-launch."""
import os
from pathlib import Path
import pytest

from tests.destructive.support.music_fade_lifecycle import run_probe
from tests.destructive.test_owned_role_survey import make_role_survey_lifecycle

pytestmark = [pytest.mark.live, pytest.mark.destructive]


def test_2025_music_fade_lifecycle_discriminator():
    if os.environ['WWISE_VERSION'] != '2025.1':
        pytest.skip('One 2025.1 discriminator only')
    root_text = os.environ.get('WAAPI_MUSIC_FADE_PROBE_ROOT')
    if not root_text:
        pytest.skip('Requires a parent-selected fresh WAAPI_MUSIC_FADE_PROBE_ROOT')
    root = Path(root_text)
    assert root.is_absolute() and not root.exists()
    run_probe(make_role_survey_lifecycle(root, live_environment=dict(os.environ)))
