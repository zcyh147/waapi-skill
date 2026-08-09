from __future__ import annotations

from pathlib import PureWindowsPath

import pytest

from tests.semantic.support.codex_windows_path_budget import (
    WINDOWS_MAX_PROCESS_CWD_UTF16_UNITS,
    WindowsCampaignPathBudgetError,
    require_windows_campaign_path_budget,
)


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def test_windows_campaign_path_budget_is_inactive_off_windows() -> None:
    assert (
        require_windows_campaign_path_budget(
            "not-an-absolute-windows-path",
            (),
            platform_name="posix",
        )
        is None
    )


def test_windows_campaign_path_budget_accepts_exact_createprocess_cwd_limit() -> None:
    root = PureWindowsPath(r"C:\w")
    # C:\w + separator + 120 + separator + 132 = 258 UTF-16 units.
    relative = PureWindowsPath("a" * 120) / ("b" * 132)

    budget = require_windows_campaign_path_budget(
        root,
        (("exact-boundary", relative),),
        platform_name="nt",
        long_paths_enabled=True,
    )

    assert budget is not None
    assert budget.passed is True
    assert budget.worst.utf16_units == WINDOWS_MAX_PROCESS_CWD_UTF16_UNITS
    assert budget.long_paths_enabled is True
    assert budget.max_campaign_root_utf16_units == _utf16_units(str(root))
    assert budget.as_dict()["worst"] == budget.worst.as_dict()


def test_windows_campaign_path_budget_rejects_even_when_long_paths_are_enabled() -> None:
    root = PureWindowsPath(r"C:\w")
    relative = PureWindowsPath("a" * 120) / ("b" * 133)

    with pytest.raises(WindowsCampaignPathBudgetError) as captured:
        require_windows_campaign_path_budget(
            root,
            (("too-deep-cwd", relative),),
            platform_name="nt",
            long_paths_enabled=True,
        )

    budget = captured.value.budget
    assert budget.passed is False
    assert budget.worst.utf16_units == WINDOWS_MAX_PROCESS_CWD_UTF16_UNITS + 1
    message = str(captured.value)
    assert "too-deep-cwd" in message
    assert "excess 1" in message
    assert "LongPathsEnabled=enabled does not remove" in message
    assert "use a shorter real --campaign-root" in message
    assert "subst, junction, 8.3" in message


def test_windows_campaign_path_budget_counts_utf16_not_python_characters() -> None:
    root = PureWindowsPath("C:/campaign-\U0001f600")
    relative = PureWindowsPath("attempts") / "worker"

    budget = require_windows_campaign_path_budget(
        root,
        (("unicode", relative),),
        platform_name="nt",
        long_paths_enabled=False,
    )

    assert budget is not None
    rendered = str(root / relative)
    assert budget.worst.utf16_units == _utf16_units(rendered)
    assert budget.worst.utf16_units == len(rendered) + 1


@pytest.mark.parametrize(
    "relative",
    (
        PureWindowsPath(r"C:\absolute"),
        PureWindowsPath(r"\rooted-without-drive"),
        PureWindowsPath("/slash-rooted-without-drive"),
        PureWindowsPath("..") / "escape",
    ),
)
def test_windows_campaign_path_budget_rejects_non_clean_relative_paths(
    relative: PureWindowsPath,
) -> None:
    with pytest.raises(ValueError, match="clean relative path"):
        require_windows_campaign_path_budget(
            PureWindowsPath(r"C:\campaign"),
            (("invalid", relative),),
            platform_name="nt",
            long_paths_enabled=None,
        )
