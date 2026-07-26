"""Closed pre-launch normalization for one V3 Wwise project copy.

The reviewed heavy scenarios require a few languages/platforms that are not
present in every committed SampleProject.  They also need every generated file
to stay below the scenario-owned I/O root and must not depend on optional
third-party plug-ins.  This module changes only the copied project tree before
Wwise starts; callers never write the immutable source tree.
"""

from __future__ import annotations

import hashlib
import os
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from tests.destructive.support.sandbox_fixture import SandboxProject


PROJECT_PRELAUNCH_CONTRACT = "waapi-skill.codex-project-prelaunch/v3"
SUPPORTED_LANGUAGES = frozenset(
    {"SFX", "English(US)", "Chinese(PRC)", "Japanese", "External", "Mixed"}
)
SUPPORTED_PLATFORMS = frozenset({"Windows", "Mac", "Android"})
_GUID_NAMESPACE = uuid.UUID("36a18127-0ecf-44bb-b159-59b40fdf24c9")
_OPTIONAL_SAMPLE_EFFECT_PLUGINS = frozenset(
    {
        ("64", "6368", "3"),  # ReWwire Sender
        ("263", "1100", "3"),  # Auro Headphone
    }
)
_OPTIONAL_EFFECT_REFERENCE_IDS = {
    ("64", "6368", "3"): frozenset(
        {"{F388642C-2218-41E6-9E5A-266312A2EB17}"}
    ),
    ("263", "1100", "3"): frozenset(
        {"{21E40BE7-7B3A-4DE4-BC78-FA8EB81736CD}"}
    ),
}
_OPTIONAL_SAMPLE_WORK_UNITS = {
    Path("Effects") / "Factory McDSP Effects.wwu": frozenset(
        {
            ("Effect", "McDSP FutzBox", "256", "110", "3"),
            ("Effect", "McDSP ML1", "256", "103", "3"),
        }
    ),
}
_OPTIONAL_SAMPLE_WORK_UNIT_SHA256 = {
    Path("Effects") / "Factory McDSP Effects.wwu": (
        "483e34608ded68949ccd967f815d59bb90a792cb38ded55a6f55a58d27a1428a"
    )
}
_CRANKCASE_SOUND_NAME = "Camaro SS - CrankcaseAudio REV"
_CRANKCASE_SOUND_ID = "{4CD69CEB-521B-4C27-84DC-FFAED616E091}"
_CRANKCASE_PLUGIN_IDENTITIES = frozenset(
    {
        ("SourcePlugin", "CrankcaseAudio REV", "261", "416", None),
        ("PluginInnerObject", "EngineSimulationControlData", "261", "417", None),
        ("PluginInnerObject", "AccelDecelModelControlData", "261", "418", None),
    }
)
_REFERENCE_ID_TAGS = frozenset({"ActiveSource", "MediaID", "ObjectRef"})
_OPTIONAL_PLUGIN_NAMES = frozenset(
    {
        "AccelDecelModelControlData",
        "Auro Headphone",
        "CrankcaseAudio REV",
        "EngineSimulationControlData",
        "McDSP FutzBox",
        "McDSP ML1",
        "ReWwire Sender",
    }
)
_PRESERVED_ANCHOR_IDS = frozenset(
    {
        "{0D70F925-AB3C-477A-A7CA-D0571B293302}",
        "{97A58685-6231-4227-9BAB-451E089615A8}",
        "{F9627628-0B10-4272-BC30-D4C20423CB38}",
    }
)


class ProjectPrelaunchError(RuntimeError):
    """The copied project cannot be normalized without guessing its layout."""


@dataclass(frozen=True, slots=True)
class ArchivedWorkUnitProof:
    relative_path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class OptionalPluginIsolationReport:
    removed_object_ids: tuple[str, ...]
    archived_work_units: tuple[ArchivedWorkUnitProof, ...]
    remaining_optional_plugin_instances: int
    preserved_anchor_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectPrelaunchReport:
    contract: str
    scenario_id: str
    project_path: str
    io_root: str
    owned_root: str
    languages: tuple[str, ...]
    platforms: tuple[str, ...]
    optional_plugin_isolation: OptionalPluginIsolationReport | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProjectPrelaunchRequest:
    scenario_id: str
    languages: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    clear_soundbank_hooks: bool = True
    isolate_optional_sample_plugins: bool = False

    def __post_init__(self) -> None:
        if not self.scenario_id or not self.scenario_id.strip():
            raise ValueError("scenario_id must be non-empty")
        unknown_languages = sorted(set(self.languages) - SUPPORTED_LANGUAGES)
        if unknown_languages:
            raise ValueError(f"unsupported fixture languages: {unknown_languages}")
        unknown_platforms = sorted(set(self.platforms) - SUPPORTED_PLATFORMS)
        if unknown_platforms:
            raise ValueError(f"unsupported fixture platforms: {unknown_platforms}")
        if len(self.languages) != len(set(self.languages)):
            raise ValueError("fixture languages must be unique")
        if len(self.platforms) != len(set(self.platforms)):
            raise ValueError("fixture platforms must be unique")
        if type(self.clear_soundbank_hooks) is not bool:
            raise ValueError("clear_soundbank_hooks must be a boolean")
        if type(self.isolate_optional_sample_plugins) is not bool:
            raise ValueError("isolate_optional_sample_plugins must be a boolean")


def make_project_prelaunch_hook(request: ProjectPrelaunchRequest):
    """Return the exact hook shape accepted by :class:`ScenarioLifecycle`."""

    def hook(sandbox: SandboxProject, _asset_root: Path, io_root: Path) -> None:
        normalize_project_copy(
            sandbox.sandbox_project,
            io_root=io_root,
            owned_root=io_root.parent,
            request=request,
        )

    return hook


def normalize_project_copy(
    project_path: Path,
    *,
    io_root: Path,
    owned_root: Path,
    request: ProjectPrelaunchRequest,
) -> ProjectPrelaunchReport:
    """Normalize one copied Wwise project and prove every path is case-owned."""

    project_input = Path(project_path).expanduser()
    root_input = Path(io_root).expanduser()
    owned_input = Path(owned_root).expanduser()
    if (
        project_input.is_symlink()
        or root_input.is_symlink()
        or owned_input.is_symlink()
    ):
        raise ProjectPrelaunchError(
            "project, io_root, and owned_root must be real paths, not symlinks"
        )
    project = project_input.resolve(strict=True)
    root = root_input.resolve(strict=True)
    owned = owned_input.resolve(strict=True)
    _require_owned_path(project, owned_root=owned, label="project")
    _require_owned_path(root, owned_root=owned, label="io_root")
    _reject_symlink_chain(project_input, owned_input=owned_input, label="project")
    _reject_symlink_chain(root_input, owned_input=owned_input, label="io_root")
    if root == project.parent or root in project.parents or project.parent in root.parents:
        raise ProjectPrelaunchError("project tree and io_root must be disjoint")

    tree = ET.parse(project)
    document = tree.getroot()
    project_element = _require_one(document, "./ProjectInfo/Project")
    platforms_element = _require_one(project_element, "./Platforms")
    languages_element = _require_one(project_element, "./LanguageList")

    requested_platforms = _ordered_union(
        (item.get("Name", "") for item in platforms_element.findall("./Platform")),
        request.platforms,
    )
    requested_languages = _ordered_union(
        (item.get("Name", "") for item in languages_element.findall("./Language")),
        request.languages,
    )
    _ensure_named_rows(
        platforms_element,
        tag="Platform",
        names=requested_platforms,
        scenario_id=request.scenario_id,
        extra=lambda name: {"ReferencePlatform": name},
    )
    _ensure_named_rows(
        languages_element,
        tag="Language",
        names=requested_languages,
        scenario_id=request.scenario_id,
    )

    soundbank_root = _contained_directory(root, "soundbanks")
    cache_root = _contained_directory(root, "cache")
    external_root = _contained_directory(root, "external")
    project_root = project.parent
    property_list = _require_one(project_element, "./PropertyList")
    _set_scalar_property(
        property_list,
        "SoundBankHeaderFilePath",
        _wwise_relative_path(project_root, soundbank_root),
    )
    _set_platform_property(
        property_list,
        "SoundBankPaths",
        {
            platform: _wwise_relative_path(
                project_root,
                _contained_directory(soundbank_root, platform),
            )
            for platform in requested_platforms
        },
    )
    _set_platform_property(
        property_list,
        "ExternalSourcesOutputPath",
        {
            platform: _wwise_relative_path(
                project_root,
                _contained_directory(external_root, platform),
            )
            for platform in requested_platforms
        },
    )
    if request.clear_soundbank_hooks:
        for element in property_list.findall("./Property"):
            name = element.get("Name", "")
            if "SoundBank" in name and "Custom" in name and name.endswith("CmdLines"):
                _clear_property_values(element)

    misc_settings = _require_one(project_element, "./MiscSettings")
    cache_rows = [
        item
        for item in misc_settings.findall("./MiscSettingEntry")
        if item.get("Name") == "Cache"
    ]
    if len(cache_rows) != 1:
        raise ProjectPrelaunchError(
            f"copied project must contain exactly one Cache setting, found {len(cache_rows)}"
        )
    cache_rows[0].text = _wwise_relative_path(project_root, cache_root)

    _write_tree_atomically(project, tree)
    optional_plugin_isolation: OptionalPluginIsolationReport | None = None
    if request.isolate_optional_sample_plugins:
        optional_plugin_isolation = _remove_optional_sample_effect_references(
            project_root,
            io_root=root,
        )
    return ProjectPrelaunchReport(
        contract=PROJECT_PRELAUNCH_CONTRACT,
        scenario_id=request.scenario_id,
        project_path=str(project),
        io_root=str(root),
        owned_root=str(owned),
        languages=requested_languages,
        platforms=requested_platforms,
        optional_plugin_isolation=optional_plugin_isolation,
    )


def _remove_optional_sample_effect_references(
    project_root: Path,
    *,
    io_root: Path,
) -> OptionalPluginIsolationReport:
    """Remove the two optional effects that make the 2022 SampleProject non-portable.

    WwiseConsole always generates ``Init`` alongside a requested SoundBank.  The
    committed 2022 SampleProject routes two buses through third-party effects
    that are not part of a standard Wwise installation, so generation reports
    an error even though the requested Bank files are written.  Remove only the
    closed, identity-pinned effect slots and definitions from the private
    project copy, relocating two optional-only Work Units below ``io_root`` so
    they remain available as evidence.  The immutable fixture stays untouched.
    """

    work_unit_input = project_root / "Master-Mixer Hierarchy" / "Default Work Unit.wwu"
    if work_unit_input.is_symlink():
        raise ProjectPrelaunchError(
            "optional-effect cleanup work unit must not be a symlink"
        )
    try:
        work_unit = work_unit_input.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ProjectPrelaunchError(
            "optional-effect cleanup requires the 2022 SampleProject master-mixer work unit"
        ) from exc
    if project_root.resolve(strict=True) not in work_unit.parents:
        raise ProjectPrelaunchError(
            "optional-effect cleanup work unit escapes the copied project"
        )

    tree = ET.parse(work_unit)
    root = tree.getroot()
    matches: dict[tuple[str, str, str], list[tuple[ET.Element, ET.Element]]] = {
        key: [] for key in _OPTIONAL_SAMPLE_EFFECT_PLUGINS
    }
    removed_ids: set[str] = set()
    for reference_list in root.findall(".//ReferenceList"):
        for reference in reference_list.findall("./Reference"):
            identities = _effect_plugin_identities(reference)
            selected = identities & _OPTIONAL_SAMPLE_EFFECT_PLUGINS
            if len(selected) > 1:
                raise ProjectPrelaunchError(
                    "one SampleProject effect slot unexpectedly references multiple optional plugins"
                )
            if selected:
                all_ids = frozenset(
                    value
                    for element in reference.iter()
                    if (value := element.get("ID")) is not None
                )
                expected_ids = _OPTIONAL_EFFECT_REFERENCE_IDS[next(iter(selected))]
                if all_ids != expected_ids:
                    raise ProjectPrelaunchError(
                        "optional SampleProject effect-slot identity drifted"
                    )
                matches[next(iter(selected))].append((reference_list, reference))

    counts = {key: len(rows) for key, rows in matches.items()}
    if any(count != 1 for count in counts.values()):
        raise ProjectPrelaunchError(
            "optional SampleProject effect references drifted: "
            + ", ".join(
                f"{company_id}/{plugin_id}/{plugin_type}="
                f"{counts[(company_id, plugin_id, plugin_type)]}"
                for company_id, plugin_id, plugin_type in sorted(counts)
            )
        )
    for rows in matches.values():
        parent, reference = rows[0]
        removed_ids.update(_all_element_ids(reference))
        parent.remove(reference)
    _write_tree_atomically(work_unit, tree)
    removed_ids.update(_remove_auro_effect_definition(project_root))
    removed_ids.update(_remove_crankcase_sound(project_root))
    archived = _relocate_optional_plugin_work_units(project_root, io_root=io_root)
    remaining, preserved = _optional_plugin_postcondition(project_root)
    return OptionalPluginIsolationReport(
        removed_object_ids=tuple(sorted(removed_ids)),
        archived_work_units=archived,
        remaining_optional_plugin_instances=remaining,
        preserved_anchor_ids=preserved,
    )


def _remove_auro_effect_definition(project_root: Path) -> frozenset[str]:
    work_unit_input = project_root / "Effects" / "Ambisonics.wwu"
    if work_unit_input.is_symlink():
        raise ProjectPrelaunchError("Auro cleanup work unit must not be a symlink")
    try:
        work_unit = work_unit_input.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ProjectPrelaunchError(
            "Auro cleanup requires the 2022 SampleProject Ambisonics effect work unit"
        ) from exc
    if project_root.resolve(strict=True) not in work_unit.parents:
        raise ProjectPrelaunchError("Auro cleanup work unit escapes the copied project")
    tree = ET.parse(work_unit)
    root = tree.getroot()
    target = ("263", "1100", "3")
    matches: list[tuple[ET.Element, ET.Element]] = []
    for children in root.findall(".//ChildrenList"):
        for effect in children.findall("./Effect"):
            identity = (
                effect.get("CompanyID"),
                effect.get("PluginID"),
                effect.get("PluginType"),
            )
            if identity == target:
                if (
                    effect.get("Name") != "SLS_Big_Church_AHP_02"
                    or effect.get("ID")
                    != "{21E40BE7-7B3A-4DE4-BC78-FA8EB81736CD}"
                ):
                    raise ProjectPrelaunchError(
                        "optional SampleProject Auro object identity drifted"
                    )
                matches.append((children, effect))
    if len(matches) != 1:
        raise ProjectPrelaunchError(
            f"optional SampleProject Auro definition drifted: {len(matches)}"
        )
    parent, effect = matches[0]
    _assert_removed_ids_unreferenced(
        project_root,
        owner=work_unit,
        removed_ids=_owned_element_ids(effect),
    )
    parent.remove(effect)
    _write_tree_atomically(work_unit, tree)
    return _owned_element_ids(effect)


def _remove_crankcase_sound(project_root: Path) -> frozenset[str]:
    """Remove only the optional Camaro source while preserving Porsche content."""

    work_unit_input = project_root / "Actor-Mixer Hierarchy" / "Car Engine.wwu"
    if work_unit_input.is_symlink():
        raise ProjectPrelaunchError("Crankcase cleanup work unit must not be a symlink")
    try:
        work_unit = work_unit_input.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ProjectPrelaunchError(
            "Crankcase cleanup requires the 2022 SampleProject Car Engine work unit"
        ) from exc
    if project_root.resolve(strict=True) not in work_unit.parents:
        raise ProjectPrelaunchError(
            "Crankcase cleanup work unit escapes the copied project"
        )

    tree = ET.parse(work_unit)
    root = tree.getroot()
    matches: list[tuple[ET.Element, ET.Element]] = []
    for children in root.findall(".//WorkUnit/ChildrenList"):
        for sound in children.findall("./Sound"):
            if (
                sound.get("Name") == _CRANKCASE_SOUND_NAME
                and sound.get("ID") == _CRANKCASE_SOUND_ID
            ):
                matches.append((children, sound))
    if len(matches) != 1:
        raise ProjectPrelaunchError(
            f"optional SampleProject Crankcase Sound drifted: {len(matches)}"
        )
    parent, sound = matches[0]
    actual_identities = frozenset(
        (
            element.tag,
            element.get("PluginName"),
            element.get("CompanyID"),
            element.get("PluginID"),
            element.get("PluginType"),
        )
        for element in sound.iter()
        if element.get("PluginName") is not None
    )
    if actual_identities != _CRANKCASE_PLUGIN_IDENTITIES:
        raise ProjectPrelaunchError(
            "optional SampleProject Crankcase plug-in inventory drifted"
        )
    _assert_removed_ids_unreferenced(
        project_root,
        owner=work_unit,
        removed_ids=_owned_element_ids(sound),
    )
    parent.remove(sound)
    _write_tree_atomically(work_unit, tree)
    return _owned_element_ids(sound)


def _relocate_optional_plugin_work_units(
    project_root: Path,
    *,
    io_root: Path,
) -> tuple[ArchivedWorkUnitProof, ...]:
    disabled_root = _contained_directory(io_root, "disabled-fixture-work-units")
    proofs: list[ArchivedWorkUnitProof] = []
    for relative, expected_identities in _OPTIONAL_SAMPLE_WORK_UNITS.items():
        source_input = project_root / relative
        if source_input.is_symlink():
            raise ProjectPrelaunchError(
                f"optional plug-in work unit must not be a symlink: {relative}"
            )
        try:
            source = source_input.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ProjectPrelaunchError(
                f"optional SampleProject work unit is missing: {relative}"
            ) from exc
        if project_root.resolve(strict=True) not in source.parents:
            raise ProjectPrelaunchError(
                f"optional SampleProject work unit escapes the copied project: {relative}"
            )
        actual_identities = frozenset(
            (
                element.tag,
                element.get("PluginName"),
                element.get("CompanyID"),
                element.get("PluginID"),
                element.get("PluginType"),
            )
            for element in ET.parse(source).getroot().iter()
            if element.get("PluginName") is not None
        )
        if actual_identities != expected_identities:
            raise ProjectPrelaunchError(
                f"optional SampleProject work unit plug-in inventory drifted: {relative}"
            )
        actual_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual_sha256 != _OPTIONAL_SAMPLE_WORK_UNIT_SHA256[relative]:
            raise ProjectPrelaunchError(
                f"optional SampleProject work unit content drifted: {relative}"
            )
        _assert_removed_ids_unreferenced(
            project_root,
            owner=source,
            removed_ids=_owned_element_ids(ET.parse(source).getroot()),
        )
        destination_parent = _contained_directory(
            disabled_root,
            *relative.parts[:-1],
        )
        destination = destination_parent / relative.name
        if destination.exists() or destination.is_symlink():
            raise ProjectPrelaunchError(
                f"optional SampleProject work-unit archive already exists: {destination}"
            )
        size = source.stat().st_size
        os.replace(source, destination)
        proofs.append(
            ArchivedWorkUnitProof(
                relative_path=relative.as_posix(),
                sha256=actual_sha256,
                size=size,
            )
        )
    return tuple(proofs)


def _optional_plugin_postcondition(
    project_root: Path,
) -> tuple[int, tuple[str, ...]]:
    remaining: list[str] = []
    present_ids: set[str] = set()
    for path in sorted(project_root.rglob("*.wwu"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ProjectPrelaunchError(
                f"optional plug-in postcondition found a symlink: {path}"
            )
        for element in ET.parse(path).getroot().iter():
            plugin_name = element.get("PluginName")
            if plugin_name in _OPTIONAL_PLUGIN_NAMES:
                remaining.append(f"{path.relative_to(project_root)}:{plugin_name}")
            if (object_id := element.get("ID")) in _PRESERVED_ANCHOR_IDS:
                present_ids.add(object_id)
    if remaining:
        raise ProjectPrelaunchError(
            "optional SampleProject plug-in instances remain after isolation: "
            + ", ".join(remaining[:8])
        )
    if present_ids != _PRESERVED_ANCHOR_IDS:
        raise ProjectPrelaunchError(
            "optional SampleProject isolation lost a preserved built-in anchor"
        )
    return 0, tuple(sorted(present_ids))


def _require_owned_path(path: Path, *, owned_root: Path, label: str) -> None:
    if path == owned_root or owned_root not in path.parents:
        raise ProjectPrelaunchError(f"{label} must be strictly below owned_root")


def _reject_symlink_chain(path: Path, *, owned_input: Path, label: str) -> None:
    current = path
    owned_resolved = owned_input.resolve(strict=True)
    while True:
        if current.is_symlink():
            raise ProjectPrelaunchError(f"{label} path chain contains a symlink")
        if current.resolve(strict=True) == owned_resolved:
            return
        if current.parent == current:
            raise ProjectPrelaunchError(f"{label} path chain does not reach owned_root")
        current = current.parent


def _owned_element_ids(element: ET.Element) -> frozenset[str]:
    return frozenset(
        value
        for row in element.iter()
        if row.tag not in _REFERENCE_ID_TAGS
        if (value := row.get("ID")) is not None
    )


def _all_element_ids(element: ET.Element) -> frozenset[str]:
    return frozenset(
        value
        for row in element.iter()
        if (value := row.get("ID")) is not None
    )


def _assert_removed_ids_unreferenced(
    project_root: Path,
    *,
    owner: Path,
    removed_ids: frozenset[str],
) -> None:
    if not removed_ids:
        raise ProjectPrelaunchError("optional SampleProject node has no closed ID inventory")
    owner_resolved = owner.resolve(strict=True)
    candidates = sorted(
        (
            path
            for suffix in ("*.wproj", "*.wwu")
            for path in project_root.rglob(suffix)
        ),
        key=lambda path: path.as_posix(),
    )
    for candidate in candidates:
        if candidate.is_symlink():
            raise ProjectPrelaunchError(
                f"optional plug-in reference scan found a symlink: {candidate}"
            )
        resolved = candidate.resolve(strict=True)
        if resolved == owner_resolved:
            continue
        for row in ET.parse(resolved).getroot().iter():
            if any(value in removed_ids for value in row.attrib.values()):
                raise ProjectPrelaunchError(
                    "optional SampleProject node is referenced outside its owner: "
                    f"{candidate.relative_to(project_root)}"
                )


def _effect_plugin_identities(reference: ET.Element) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for element in (reference, *reference.findall(".//Effect")):
        company_id = element.get("CompanyID")
        plugin_id = element.get("PluginID")
        plugin_type = element.get("PluginType")
        if company_id is not None and plugin_id is not None and plugin_type is not None:
            result.add((company_id, plugin_id, plugin_type))
    return result


def _write_tree_atomically(path: Path, tree: ET.ElementTree) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.prelaunch.tmp")
    if temporary.exists():
        raise ProjectPrelaunchError(f"prelaunch temporary path already exists: {temporary}")
    tree.write(temporary, encoding="utf-8", xml_declaration=True)
    os.replace(temporary, path)


def _require_one(root: ET.Element, selector: str) -> ET.Element:
    rows = root.findall(selector)
    if len(rows) != 1:
        raise ProjectPrelaunchError(
            f"copied project selector {selector!r} must match exactly once, found {len(rows)}"
        )
    return rows[0]


def _ordered_union(existing: Iterable[str], requested: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in (*tuple(existing), *tuple(requested)):
        if value and value not in result:
            result.append(value)
    return tuple(result)


def _ensure_named_rows(
    parent: ET.Element,
    *,
    tag: str,
    names: tuple[str, ...],
    scenario_id: str,
    extra=None,
) -> None:
    existing = {item.get("Name", ""): item for item in parent.findall(f"./{tag}")}
    if len(existing) != len(parent.findall(f"./{tag}")):
        raise ProjectPrelaunchError(f"copied project has duplicate {tag} names")
    for name in names:
        if name in existing:
            continue
        attributes = {"Name": name}
        if extra is not None:
            attributes.update(extra(name))
        attributes["ID"] = _stable_guid(scenario_id, tag, name)
        ET.SubElement(parent, tag, attributes)


def _stable_guid(scenario_id: str, kind: str, name: str) -> str:
    value = uuid.uuid5(_GUID_NAMESPACE, f"{scenario_id}:{kind}:{name}")
    return "{" + str(value).upper() + "}"


def _contained_directory(root: Path, *segments: str) -> Path:
    target = root.joinpath(*segments).resolve(strict=False)
    if target != root and root not in target.parents:
        raise ProjectPrelaunchError(f"derived project path escapes io_root: {target}")
    target.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ProjectPrelaunchError(f"derived project path must not be a symlink: {target}")
    return target


def _wwise_relative_path(project_root: Path, target: Path) -> str:
    """Render a host target as a safe project-relative Wwise path.

    Wwise running through Wine interprets a POSIX-looking absolute value in a
    ``.wproj`` as a project-relative Windows path.  Use an explicit relative
    spelling instead, so its eventual Wine path resolves to the same
    case-owned host directory.
    """

    relative = Path(os.path.relpath(target, start=project_root))
    if relative.is_absolute() or not relative.parts:
        raise ProjectPrelaunchError(
            f"derived Wwise path must be non-empty and relative: {target}"
        )
    if (project_root / relative).resolve(strict=False) != target.resolve(strict=False):
        raise ProjectPrelaunchError(
            f"derived Wwise path does not resolve to its case-owned target: {target}"
        )
    return "\\".join(relative.parts)


def _find_property(property_list: ET.Element, name: str) -> ET.Element:
    rows = [item for item in property_list.findall("./Property") if item.get("Name") == name]
    if len(rows) != 1:
        raise ProjectPrelaunchError(
            f"copied project property {name!r} must exist exactly once, found {len(rows)}"
        )
    return rows[0]


def _set_scalar_property(property_list: ET.Element, name: str, value: str) -> None:
    element = _find_property(property_list, name)
    element.set("Value", value)
    for child in list(element):
        element.remove(child)


def _set_platform_property(
    property_list: ET.Element,
    name: str,
    values: dict[str, str],
) -> None:
    element = _find_property(property_list, name)
    element.attrib.pop("Value", None)
    for child in list(element):
        element.remove(child)
    value_list = ET.SubElement(element, "ValueList")
    for platform, value in values.items():
        row = ET.SubElement(value_list, "Value", {"Platform": platform})
        row.text = value


def _clear_property_values(element: ET.Element) -> None:
    if "Value" in element.attrib:
        element.set("Value", "")
    for row in element.findall("./ValueList/Value"):
        row.text = ""


__all__ = [
    "ArchivedWorkUnitProof",
    "OptionalPluginIsolationReport",
    "PROJECT_PRELAUNCH_CONTRACT",
    "ProjectPrelaunchReport",
    "ProjectPrelaunchError",
    "ProjectPrelaunchRequest",
    "make_project_prelaunch_hook",
    "normalize_project_copy",
]
