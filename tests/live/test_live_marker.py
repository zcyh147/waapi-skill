from __future__ import annotations

import pytest  # pyright: ignore[reportMissingImports]


@pytest.mark.live
def test_live_placeholder_requires_explicit_opt_in() -> None:
    assert True
