"""Dispatcher placeholder for Wwise WAAPI commands."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WwiseDispatcher:
    """Placeholder command dispatcher for future WAAPI calls."""

    def dispatch(self, command: str, **kwargs: object) -> dict[str, object]:
        raise NotImplementedError(f"Dispatch is not implemented for {command!r}")
