"""Integer field semantics remain independent of source accounting."""
import json
import pytest

from tests.unit.test_scalar_condition_product_gateway import scalar_workflow


def test_integer_field_with_real_range_uses_an_integer_public_change(tmp_path):
    scalar_workflow(tmp_path, '2025.1', 'GameAuxSendHPF',
        {'type': 'int16', 'restriction': {'type': 'range', 'min': 0.0, 'max': 100.0}}, 100)


def test_parent_collector_refuses_a_changed_installed_file_before_extracting_its_type(tmp_path):
    from tests.maintenance.condition_parent_sources import collect
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/branch-coverage-condition-sources.json").write_text(json.dumps({"corpora": [{
        "name": "condition", "lanes": [{"build": "2025.1.7.9143",
        "files": [{"path": "WObjects/WObjects.xml", "sha256": "0" * 64}], "rows": [{
            "file": "WObjects/WObjects.xml", "path": "PluginModule/WwiseObject[Sound]/Properties/Property[PreFetchLength]/Dependencies",
            "tag": "PropertyDependency", "attributes": {"Name": "IsStreamingEnabled", "Action": "Enable"},
            "xml": '<PropertyDependency Name="IsStreamingEnabled"><Condition><Enumeration Type="bool"><Value>true</Value></Enumeration></Condition></PropertyDependency>'}]}]}]}))
    path = tmp_path / "installed/Wwise 2025.1.7.9143/Authoring/Data/WObjects/WObjects.xml"
    path.parent.mkdir(parents=True)
    path.write_text('<PluginModule><WwiseObject Name="Sound"><Properties><Property Name="PreFetchLength" Type="bool" /></Properties></WwiseObject></PluginModule>')
    with pytest.raises(ValueError, match="pinned installed source digest mismatch"):
        collect(tmp_path, tmp_path / "installed")
