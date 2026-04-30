from __future__ import annotations

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.live_environment import require_live_environment  # pyright: ignore[reportMissingImports]


@pytest.mark.live
def test_live_environment_prerequisites_fail_fast() -> None:
    require_live_environment()
