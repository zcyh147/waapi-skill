"""Fail-closed Windows process-working-directory path budgets.

Windows long-path policy helps long-path-aware file APIs, but it does not make
an arbitrarily deep process current directory safe.  Microsoft documents that
``CreateProcessW`` fails when the current directory is longer than
``MAX_PATH``.  Campaigns therefore project every runner-owned directory that
will be passed as ``cwd`` before creating campaign state.

This module deliberately does not manufacture a short alias with ``subst``, a
junction, an 8.3 name, or a ``\\\\?\\`` prefix.  Those mechanisms either change
the path identity audited by the campaign or do not solve the process-current-
directory boundary.  The caller must use a sufficiently shallow real campaign
root instead.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import PurePath, PureWindowsPath
from typing import Sequence


# MAX_PATH is 260 UTF-16 code units including the terminating NUL.  The current
# directory representation also needs a trailing separator.  A directory path
# without that separator therefore gets at most MAX_PATH - 2 code units.
WINDOWS_MAX_PROCESS_CWD_UTF16_UNITS = 258


@dataclass(frozen=True, slots=True)
class WindowsProcessCwdProjection:
    label: str
    path: PureWindowsPath
    utf16_units: int

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "path": str(self.path),
            "utf16_units": self.utf16_units,
        }


@dataclass(frozen=True, slots=True)
class WindowsCampaignPathBudget:
    campaign_root: PureWindowsPath
    limit_utf16_units: int
    max_campaign_root_utf16_units: int
    long_paths_enabled: bool | None
    projections: tuple[WindowsProcessCwdProjection, ...]

    @property
    def worst(self) -> WindowsProcessCwdProjection:
        if not self.projections:
            raise ValueError("Windows campaign path budget has no projections")
        return max(self.projections, key=lambda item: item.utf16_units)

    @property
    def passed(self) -> bool:
        return self.worst.utf16_units <= self.limit_utf16_units

    def as_dict(self) -> dict[str, object]:
        return {
            "contract": "waapi-skill.windows-process-cwd-budget/v1",
            "campaign_root": str(self.campaign_root),
            "campaign_root_utf16_units": _utf16_units(str(self.campaign_root)),
            "limit_utf16_units": self.limit_utf16_units,
            "max_campaign_root_utf16_units": self.max_campaign_root_utf16_units,
            "long_paths_enabled": self.long_paths_enabled,
            "passed": self.passed,
            "worst": self.worst.as_dict(),
            "projections": [item.as_dict() for item in self.projections],
        }


class WindowsCampaignPathBudgetError(RuntimeError):
    """A selected campaign cannot safely launch every projected Windows cwd."""

    def __init__(self, budget: WindowsCampaignPathBudget) -> None:
        self.budget = budget
        worst = budget.worst
        excess = worst.utf16_units - budget.limit_utf16_units
        policy = (
            "enabled"
            if budget.long_paths_enabled is True
            else "disabled"
            if budget.long_paths_enabled is False
            else "unknown"
        )
        super().__init__(
            "Windows campaign process working-directory path budget exceeded: "
            f"{worst.label} projects to {worst.utf16_units} UTF-16 units "
            f"(limit {budget.limit_utf16_units}, excess {excess}); "
            f"campaign_root={budget.campaign_root}; "
            "use a shorter real --campaign-root whose full path is at most "
            f"{budget.max_campaign_root_utf16_units} UTF-16 units for this "
            f"selection. LongPathsEnabled={policy} does not remove the "
            "CreateProcessW current-directory boundary; subst, junction, 8.3, "
            "and extended-length path aliases are not accepted."
        )


def require_windows_campaign_path_budget(
    campaign_root: os.PathLike[str] | str,
    projected_relative_cwds: Sequence[tuple[str, os.PathLike[str] | str]],
    *,
    platform_name: str | None = None,
    long_paths_enabled: bool | None = None,
) -> WindowsCampaignPathBudget | None:
    """Validate all selected process ``cwd`` values before campaign creation.

    ``projected_relative_cwds`` contains logical paths below the campaign root.
    On non-Windows hosts the contract is intentionally inactive and returns
    ``None``.  ``platform_name`` and ``long_paths_enabled`` exist so the path
    calculation and both registry states can be tested on POSIX CI.
    """

    active_platform = os.name if platform_name is None else platform_name
    if active_platform != "nt":
        return None
    if not projected_relative_cwds:
        raise ValueError("Windows campaign path budget requires cwd projections")

    root = _absolute_windows_path(campaign_root)
    projections: list[WindowsProcessCwdProjection] = []
    maximum_suffix_units = 0
    for label, relative_value in projected_relative_cwds:
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Windows campaign cwd projection label is empty")
        relative = _relative_windows_path(relative_value)
        path = root.joinpath(relative)
        suffix_units = _joined_suffix_utf16_units(relative)
        maximum_suffix_units = max(maximum_suffix_units, suffix_units)
        projections.append(
            WindowsProcessCwdProjection(
                label=label,
                path=path,
                utf16_units=_utf16_units(str(path)),
            )
        )

    registry_state = (
        _windows_long_paths_enabled()
        if long_paths_enabled is None and platform_name is None
        else long_paths_enabled
    )
    budget = WindowsCampaignPathBudget(
        campaign_root=root,
        limit_utf16_units=WINDOWS_MAX_PROCESS_CWD_UTF16_UNITS,
        max_campaign_root_utf16_units=(
            WINDOWS_MAX_PROCESS_CWD_UTF16_UNITS - maximum_suffix_units
        ),
        long_paths_enabled=registry_state,
        projections=tuple(projections),
    )
    if not budget.passed:
        raise WindowsCampaignPathBudgetError(budget)
    return budget


def _absolute_windows_path(value: os.PathLike[str] | str) -> PureWindowsPath:
    path = PureWindowsPath(os.fspath(value))
    if not path.is_absolute():
        raise ValueError(f"Windows campaign root must be absolute: {path}")
    return path


def _relative_windows_path(value: os.PathLike[str] | str) -> PureWindowsPath:
    raw = os.fspath(value)
    # Callers normally build these values with the host ``Path`` class.  A
    # POSIX test therefore supplies slash-separated logical components; native
    # Windows accepts either slash here and persists the canonical backslashes.
    parts = PurePath(raw).parts if "\\" not in raw else PureWindowsPath(raw).parts
    path = PureWindowsPath(*parts)
    if (
        path.is_absolute()
        or bool(path.drive)
        or bool(path.root)
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"Windows campaign cwd projection must be a clean relative path: {raw}")
    return path


def _joined_suffix_utf16_units(relative: PureWindowsPath) -> int:
    # One separator joins an arbitrary non-root campaign path to the relative
    # projection.  Counting this independently gives the exact maximum allowed
    # root length even for non-BMP path characters.
    return 1 + _utf16_units(str(relative))


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le", errors="strict")) // 2


def _windows_long_paths_enabled() -> bool | None:
    """Read the host policy for diagnostics without changing system state."""

    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "LongPathsEnabled")
    except (ImportError, OSError):
        return None
    return value == 1


__all__ = [
    "WINDOWS_MAX_PROCESS_CWD_UTF16_UNITS",
    "WindowsCampaignPathBudget",
    "WindowsCampaignPathBudgetError",
    "WindowsProcessCwdProjection",
    "require_windows_campaign_path_budget",
]
