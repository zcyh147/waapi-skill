"""Closed Wwise project-layout facts shared by compound-heavy V3 adapters.

Wwise 2025 renamed the Authoring hierarchy roots and the reflected
``ActorMixer`` object type without changing the create request token.  Keeping
those facts in one immutable table prevents individual runtime adapters from
inventing path or type aliases.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


SUPPORTED_LAYOUT_VERSIONS: Final = (
    "2021.1",
    "2022.1",
    "2023.1",
    "2024.1",
    "2025.1",
)


class CodexVersionLayoutError(ValueError):
    """A requested Wwise version is outside the reviewed layout table."""


@dataclass(frozen=True, slots=True)
class CodexVersionLayoutV3:
    """One reviewed Wwise lane's canonical hierarchy and type spellings."""

    version: str
    containers_root: str
    containers_dwu: str
    busses_root: str
    busses_dwu: str
    main_bus: str
    requested_actor_mixer: str
    reflected_actor_mixer: str

    @property
    def actor_hierarchy(self) -> str:
        return self.containers_root

    @property
    def actor_default_work_unit(self) -> str:
        return self.containers_dwu

    @property
    def master_hierarchy(self) -> str:
        return self.busses_root

    @property
    def master_default_work_unit(self) -> str:
        return self.busses_dwu

    @property
    def master_audio_bus(self) -> str:
        return self.main_bus

    def reflected_type(self, requested_type: str) -> str:
        """Return the exact type expected from readback for a request token."""

        return (
            self.reflected_actor_mixer
            if requested_type == self.requested_actor_mixer
            else requested_type
        )

    def requested_type(self, reflected_type: str) -> str:
        """Return the create token corresponding to one reflected type."""

        return (
            self.requested_actor_mixer
            if reflected_type == self.reflected_actor_mixer
            else reflected_type
        )

    def translate_2022_path(self, value: str) -> str:
        """Translate one canonical 2022 path into this version's layout."""

        if not isinstance(value, str):
            raise TypeError("Wwise path must be a string")
        source = _LAYOUTS["2022.1"]
        for old_prefix, new_prefix in (
            (source.main_bus, self.main_bus),
            (source.containers_root, self.containers_root),
            (source.busses_root, self.busses_root),
        ):
            if value == old_prefix:
                return new_prefix
            if value.startswith(old_prefix + "\\"):
                return new_prefix + value[len(old_prefix) :]
        return value


def _legacy_layout(version: str) -> CodexVersionLayoutV3:
    return CodexVersionLayoutV3(
            version=version,
            containers_root=r"\Actor-Mixer Hierarchy",
            containers_dwu=r"\Actor-Mixer Hierarchy\Default Work Unit",
            busses_root=r"\Master-Mixer Hierarchy",
            busses_dwu=r"\Master-Mixer Hierarchy\Default Work Unit",
            main_bus=(
                r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"
            ),
            requested_actor_mixer="ActorMixer",
            reflected_actor_mixer="ActorMixer",
        )


_LAYOUTS = MappingProxyType(
    {
        version: _legacy_layout(version)
        for version in SUPPORTED_LAYOUT_VERSIONS[:-1]
    }
    | {
        "2025.1": CodexVersionLayoutV3(
            version="2025.1",
            containers_root=r"\Containers",
            containers_dwu=r"\Containers\Default Work Unit",
            busses_root=r"\Busses",
            busses_dwu=r"\Busses\Default Work Unit",
            main_bus=r"\Busses\Default Work Unit\Main Audio Bus",
            requested_actor_mixer="ActorMixer",
            reflected_actor_mixer="PropertyContainer",
        ),
    }
)


def get_codex_version_layout_v3(version: str) -> CodexVersionLayoutV3:
    """Return one immutable reviewed layout; unknown versions fail closed."""

    try:
        return _LAYOUTS[version]
    except KeyError as exc:
        raise CodexVersionLayoutError(
            f"unsupported compound-heavy Wwise layout: {version!r}"
        ) from exc


get_version_layout = get_codex_version_layout_v3


__all__ = [
    "SUPPORTED_LAYOUT_VERSIONS",
    "CodexVersionLayoutError",
    "CodexVersionLayoutV3",
    "get_codex_version_layout_v3",
    "get_version_layout",
]
