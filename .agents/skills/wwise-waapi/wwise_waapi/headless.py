"""Headless Wwise lifecycle placeholder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class HeadlessLifecycle:
    """Placeholder for bounded WwiseConsole lifecycle management."""

    console_path: Path | None = None
    port: int | None = None

    def launch(self) -> None:
        raise NotImplementedError("Headless Wwise lifecycle is not implemented in the scaffold")

    def wait_ready(self) -> None:
        raise NotImplementedError("Readiness probing is not implemented in the scaffold")

    def shutdown(self) -> None:
        raise NotImplementedError("Shutdown handling is not implemented in the scaffold")
