from __future__ import annotations

import pytest  # pyright: ignore[reportMissingImports]


@pytest.mark.destructive
def test_destructive_placeholder_requires_explicit_opt_in() -> None:
    assert True
