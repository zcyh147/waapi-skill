from __future__ import annotations

import hashlib
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests.semantic.support import codex_project_prelaunch_v3 as prelaunch
from tests.semantic.support.codex_project_prelaunch_v3 import (
    ProjectPrelaunchError,
    ProjectPrelaunchRequest,
    WWISE_2025_SOUNDBANK_AURO_PROFILE,
    normalize_project_copy,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PROJECT = REPO_ROOT / "tests" / "_org" / "2022.1" / "SampleProject.wproj"
SOURCE_PROJECT_2025 = (
    REPO_ROOT / "tests" / "_org" / "2025.1" / "SampleProject.wproj"
)


def test_normalizes_only_copy_with_case_owned_paths(tmp_path: Path) -> None:
    source_before = SOURCE_PROJECT.read_bytes()
    project = tmp_path / "sandbox" / "SampleProject.wproj"
    project.parent.mkdir()
    shutil.copy2(SOURCE_PROJECT, project)
    io_root = tmp_path / "owned" / "io"
    io_root.mkdir(parents=True)

    report = normalize_project_copy(
        project,
        io_root=io_root,
        owned_root=tmp_path,
        request=ProjectPrelaunchRequest(
            scenario_id="O22-SB-GENERATE-02",
            languages=("Chinese(PRC)", "Japanese"),
            platforms=("Windows", "Mac"),
        ),
    )

    assert SOURCE_PROJECT.read_bytes() == source_before
    assert report.contract == "waapi-skill.codex-project-prelaunch/v3"
    assert report.optional_plugin_isolation is None
    root = ET.parse(project).getroot()
    language_names = {
        row.get("Name") for row in root.findall("./ProjectInfo/Project/LanguageList/Language")
    }
    assert {"English(US)", "Chinese(PRC)", "Japanese", "SFX"}.issubset(language_names)
    platform_names = {
        row.get("Name") for row in root.findall("./ProjectInfo/Project/Platforms/Platform")
    }
    assert {"Windows", "Mac"}.issubset(platform_names)
    values = {
        (prop.get("Name"), row.get("Platform")): row.text
        for prop in root.findall("./ProjectInfo/Project/PropertyList/Property")
        for row in prop.findall("./ValueList/Value")
    }
    def resolve_wwise_relative(value: str) -> Path:
        candidate = Path(value.replace("\\", "/"))
        assert not candidate.is_absolute()
        return (project.parent / candidate).resolve(strict=False)

    header = next(
        row
        for row in root.findall("./ProjectInfo/Project/PropertyList/Property")
        if row.get("Name") == "SoundBankHeaderFilePath"
    )
    assert resolve_wwise_relative(header.get("Value") or "") == io_root / "soundbanks"
    assert resolve_wwise_relative(values[("SoundBankPaths", "Windows")]) == (
        io_root / "soundbanks" / "Windows"
    )
    assert resolve_wwise_relative(values[("ExternalSourcesOutputPath", "Mac")]) == (
        io_root / "external" / "Mac"
    )
    cache = next(
        row
        for row in root.findall("./ProjectInfo/Project/MiscSettings/MiscSettingEntry")
        if row.get("Name") == "Cache"
    )
    assert resolve_wwise_relative(cache.text or "") == io_root / "cache"


def test_isolates_only_closed_optional_plugins_from_copy(
    tmp_path: Path,
) -> None:
    source_root = SOURCE_PROJECT.parent
    source_before = {
        path.relative_to(source_root): path.read_bytes()
        for path in source_root.rglob("*")
        if path.is_file()
    }
    project_root = tmp_path / "sandbox"
    shutil.copytree(source_root, project_root)
    project = project_root / SOURCE_PROJECT.name
    io_root = tmp_path / "owned" / "io"
    io_root.mkdir(parents=True)

    report = normalize_project_copy(
        project,
        io_root=io_root,
        owned_root=tmp_path,
        request=ProjectPrelaunchRequest(
            scenario_id="O22-CLI-GENERATE-BANK-02",
            isolate_optional_sample_plugins=True,
        ),
    )

    assert source_before == {
        path.relative_to(source_root): path.read_bytes()
        for path in source_root.rglob("*")
        if path.is_file()
    }
    isolation = report.optional_plugin_isolation
    assert isolation is not None
    assert isolation.remaining_optional_plugin_instances == 0
    assert set(isolation.preserved_anchor_ids) == {
        "{0D70F925-AB3C-477A-A7CA-D0571B293302}",
        "{97A58685-6231-4227-9BAB-451E089615A8}",
        "{F9627628-0B10-4272-BC30-D4C20423CB38}",
    }
    assert [row.relative_path for row in isolation.archived_work_units] == [
        "Effects/Factory McDSP Effects.wwu"
    ]
    work_unit = project_root / "Master-Mixer Hierarchy" / "Default Work Unit.wwu"
    root = ET.parse(work_unit).getroot()
    identities = {
        (
            element.get("CompanyID"),
            element.get("PluginID"),
            element.get("PluginType"),
        )
        for reference in root.findall(".//ReferenceList/Reference")
        for element in (reference, *reference.findall(".//Effect"))
    }
    assert ("64", "6368", "3") not in identities
    assert ("263", "1100", "3") not in identities
    assert ET.parse(project_root / "Effects" / "Ambisonics.wwu").find(
        ".//Effect[@PluginName='Auro Headphone']"
    ) is None
    ambisonics = ET.parse(project_root / "Effects" / "Ambisonics.wwu").getroot()
    assert {
        row.get("ID")
        for row in ambisonics.findall(".//Effect[@PluginName='Wwise Parametric EQ']")
    } == {
        "{0D70F925-AB3C-477A-A7CA-D0571B293302}",
        "{F9627628-0B10-4272-BC30-D4C20423CB38}",
    }
    car_engine = project_root / "Actor-Mixer Hierarchy" / "Car Engine.wwu"
    assert car_engine.is_file()
    car_root = ET.parse(car_engine).getroot()
    assert car_root.find(
        ".//Sound[@ID='{4CD69CEB-521B-4C27-84DC-FFAED616E091}']"
    ) is None
    assert car_root.find(
        ".//BlendContainer[@ID='{97A58685-6231-4227-9BAB-451E089615A8}']"
    ) is not None
    event_root = ET.parse(project_root / "Events" / "Car Engine.wwu").getroot()
    assert len(
        event_root.findall(
            ".//ObjectRef[@ID='{97A58685-6231-4227-9BAB-451E089615A8}']"
        )
    ) == 2
    assert not (project_root / "Effects" / "Factory McDSP Effects.wwu").exists()
    disabled = io_root / "disabled-fixture-work-units"
    assert (disabled / "Effects" / "Factory McDSP Effects.wwu").is_file()


def test_isolates_only_pinned_auro_nodes_for_2025_soundbank_copy(
    tmp_path: Path,
) -> None:
    source_root = SOURCE_PROJECT_2025.parent
    source_before = {
        path.relative_to(source_root): path.read_bytes()
        for path in source_root.rglob("*")
        if path.is_file()
    }
    project_root = tmp_path / "sandbox"
    shutil.copytree(source_root, project_root)
    io_root = tmp_path / "owned" / "io"
    io_root.mkdir(parents=True)

    report = normalize_project_copy(
        project_root / SOURCE_PROJECT_2025.name,
        io_root=io_root,
        owned_root=tmp_path,
        request=ProjectPrelaunchRequest(
            scenario_id="CMP25-O22-SB-GENERATE-01",
            auro_isolation_profile=WWISE_2025_SOUNDBANK_AURO_PROFILE,
        ),
    )

    assert source_before == {
        path.relative_to(source_root): path.read_bytes()
        for path in source_root.rglob("*")
        if path.is_file()
    }
    assert report.optional_plugin_isolation is None
    isolation = report.auro_soundbank_isolation
    assert isolation is not None
    assert isolation.profile == WWISE_2025_SOUNDBANK_AURO_PROFILE
    assert isolation.remaining_auro_plugin_instances == 0
    assert isolation.remaining_auro_object_references == 0
    assert isolation.removed_bus_reference_object_ids == (
        "{21E40BE7-7B3A-4DE4-BC78-FA8EB81736CD}",
    )
    assert isolation.removed_effect_definition_ids == (
        "{21E40BE7-7B3A-4DE4-BC78-FA8EB81736CD}",
    )
    proofs = {row.relative_path: row for row in isolation.work_units}
    assert {
        relative: row.input_sha256
        for relative, row in proofs.items()
    } == {
        "Busses/Default Work Unit.wwu": (
            "abaefb80d17cb9f2f3f64b8d786eb02fface5e13066eaeaaac204cf2a3b4da06"
        ),
        "Effects/Ambisonics.wwu": (
            "66ef565e7b4e28ed39b189284700d44f67cdb8c4f9035fa5a04842d2c050e29a"
        ),
    }
    for relative, proof in proofs.items():
        content = (project_root / relative).read_bytes()
        assert hashlib.sha256(content).hexdigest() == proof.output_sha256
        assert len(content) == proof.output_size

    bus_root = ET.parse(
        project_root / "Busses" / "Default Work Unit.wwu"
    ).getroot()
    assert bus_root.find(
        ".//Reference[@PluginName='Auro Headphone']"
    ) is None
    effect_root = ET.parse(
        project_root / "Effects" / "Ambisonics.wwu"
    ).getroot()
    assert effect_root.find(
        ".//Effect[@ID='{21E40BE7-7B3A-4DE4-BC78-FA8EB81736CD}']"
    ) is None
    assert {
        row.get("ID")
        for row in effect_root.findall(
            ".//Effect[@PluginName='Wwise Parametric EQ']"
        )
    } == {
        "{0D70F925-AB3C-477A-A7CA-D0571B293302}",
        "{F9627628-0B10-4272-BC30-D4C20423CB38}",
    }
    assert (
        project_root / "Effects" / "Factory McDSP Effects.wwu"
    ).is_file()
    assert ET.parse(
        project_root / "Effects" / "Factory McDSP Effects.wwu"
    ).find(".//*[@PluginName='McDSP FutzBox']") is not None


def test_2025_auro_work_unit_hash_drift_fails_before_any_project_write(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "sandbox"
    shutil.copytree(SOURCE_PROJECT_2025.parent, project_root)
    project = project_root / SOURCE_PROJECT_2025.name
    bus = project_root / "Busses" / "Default Work Unit.wwu"
    effect = project_root / "Effects" / "Ambisonics.wwu"
    bus.write_bytes(bus.read_bytes() + b"\n")
    before = {path: path.read_bytes() for path in (project, bus, effect)}
    io_root = tmp_path / "io"
    io_root.mkdir()

    with pytest.raises(
        ProjectPrelaunchError,
        match=r"content drifted: Busses/Default Work Unit\.wwu",
    ):
        normalize_project_copy(
            project,
            io_root=io_root,
            owned_root=tmp_path,
            request=ProjectPrelaunchRequest(
                scenario_id="CMP25-O22-SB-GENERATE-01",
                auro_isolation_profile=WWISE_2025_SOUNDBANK_AURO_PROFILE,
            ),
        )

    assert before == {path: path.read_bytes() for path in before}


def test_2025_auro_identity_drift_fails_before_any_project_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "sandbox"
    shutil.copytree(SOURCE_PROJECT_2025.parent, project_root)
    project = project_root / SOURCE_PROJECT_2025.name
    bus = project_root / "Busses" / "Default Work Unit.wwu"
    effect = project_root / "Effects" / "Ambisonics.wwu"
    tree = ET.parse(effect)
    auro = tree.find(".//Effect[@PluginName='Auro Headphone']")
    assert auro is not None
    auro.set("Name", "Drifted_Auro_Effect")
    tree.write(effect, encoding="utf-8", xml_declaration=True)
    monkeypatch.setitem(
        prelaunch._WWISE_2025_AURO_WORK_UNIT_SHA256,
        Path("Effects") / "Ambisonics.wwu",
        hashlib.sha256(effect.read_bytes()).hexdigest(),
    )
    before = {path: path.read_bytes() for path in (project, bus, effect)}
    io_root = tmp_path / "io"
    io_root.mkdir()

    with pytest.raises(
        ProjectPrelaunchError,
        match="Auro effect definition identity drifted",
    ):
        normalize_project_copy(
            project,
            io_root=io_root,
            owned_root=tmp_path,
            request=ProjectPrelaunchRequest(
                scenario_id="CMP25-O22-SB-GENERATE-01",
                auro_isolation_profile=WWISE_2025_SOUNDBANK_AURO_PROFILE,
            ),
        )

    assert before == {path: path.read_bytes() for path in before}


def test_added_guids_are_deterministic(tmp_path: Path) -> None:
    outputs: list[tuple[str, str]] = []
    for index in range(2):
        project = tmp_path / f"copy-{index}" / "SampleProject.wproj"
        project.parent.mkdir()
        shutil.copy2(SOURCE_PROJECT, project)
        io_root = tmp_path / f"io-{index}"
        io_root.mkdir()
        normalize_project_copy(
            project,
            io_root=io_root,
            owned_root=tmp_path,
            request=ProjectPrelaunchRequest(
                scenario_id="same-case",
                languages=("Japanese",),
                platforms=("Android",),
            ),
        )
        root = ET.parse(project).getroot()
        language = next(
            row
            for row in root.findall("./ProjectInfo/Project/LanguageList/Language")
            if row.get("Name") == "Japanese"
        )
        platform = next(
            row
            for row in root.findall("./ProjectInfo/Project/Platforms/Platform")
            if row.get("Name") == "Android"
        )
        outputs.append((language.get("ID") or "", platform.get("ID") or ""))
    assert outputs[0] == outputs[1]


def test_rejects_symlinked_project(tmp_path: Path) -> None:
    project = tmp_path / "project.wproj"
    project.symlink_to(SOURCE_PROJECT)
    io_root = tmp_path / "io"
    io_root.mkdir()

    with pytest.raises(ProjectPrelaunchError, match="symlinks"):
        normalize_project_copy(
            project,
            io_root=io_root,
            owned_root=tmp_path,
            request=ProjectPrelaunchRequest(scenario_id="case"),
        )


def test_rejects_project_outside_owned_root_before_writing(tmp_path: Path) -> None:
    source_before = SOURCE_PROJECT.read_bytes()
    io_root = tmp_path / "io"
    io_root.mkdir()

    with pytest.raises(ProjectPrelaunchError, match="strictly below owned_root"):
        normalize_project_copy(
            SOURCE_PROJECT,
            io_root=io_root,
            owned_root=tmp_path,
            request=ProjectPrelaunchRequest(scenario_id="case"),
        )

    assert SOURCE_PROJECT.read_bytes() == source_before


def test_optional_plugin_flag_must_be_boolean() -> None:
    with pytest.raises(ValueError, match="must be a boolean"):
        ProjectPrelaunchRequest(
            scenario_id="case",
            isolate_optional_sample_plugins=1,  # type: ignore[arg-type]
        )


def test_factory_work_unit_content_drift_fails_closed(tmp_path: Path) -> None:
    source_root = SOURCE_PROJECT.parent
    project_root = tmp_path / "sandbox"
    shutil.copytree(source_root, project_root)
    factory = project_root / "Effects" / "Factory McDSP Effects.wwu"
    tree = ET.parse(factory)
    children = tree.find("./Effects/WorkUnit/ChildrenList")
    assert children is not None
    ET.SubElement(
        children,
        "Folder",
        {"Name": "Unexpected Built-In Content", "ID": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"},
    )
    tree.write(factory, encoding="utf-8", xml_declaration=True)
    io_root = tmp_path / "io"
    io_root.mkdir()

    with pytest.raises(ProjectPrelaunchError, match="content drifted"):
        normalize_project_copy(
            project_root / SOURCE_PROJECT.name,
            io_root=io_root,
            owned_root=tmp_path,
            request=ProjectPrelaunchRequest(
                scenario_id="case",
                isolate_optional_sample_plugins=True,
            ),
        )
