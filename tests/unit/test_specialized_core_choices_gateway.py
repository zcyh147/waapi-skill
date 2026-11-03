"""Specialized choices are discoverable before the user authorizes a Draft."""
import pytest
from tests.unit.test_core_business_gateway import gateway, _env


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
def test_paste_schema_discloses_all_list_outcomes_and_documented_default(tmp_path, version):
    code, schema = gateway.execute_gateway(['--version', version, 'request-schema',
        'ak.wwise.core.object.pasteProperties'], env=_env(tmp_path),
        client_factory=lambda _: pytest.fail('offline schema connected'))
    assert code == 0, schema
    assert schema['business_adapter']['declaration']['value_domains']['list_mode'] == {
        'choices': ['merge-keep', 'merge-replace', 'replace'], 'omitted_effect': 'replace'}


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_blend_schema_discloses_closed_edge_modes_shapes_and_order(tmp_path, version):
    code, schema = gateway.execute_gateway(['--version', version, 'request-schema',
        'ak.wwise.core.blendContainer.addAssignment'], env=_env(tmp_path),
        client_factory=lambda _: pytest.fail('offline schema connected'))
    assert code == 0, schema
    edges = schema['business_adapter']['declaration']['value_domains']['edges']
    assert edges['fade_mode_choices'] == ['automatic', 'manual', 'none']
    assert edges['shape_choices'] == ['constant', 'exp-1', 'exp-2', 'exp-3', 'inverted-s-curve',
        'linear', 'log-1', 'log-2', 'log-3', 's-curve']
    assert edges['items'] == 2
    assert edges['order'] == ['left', 'right']
    assert edges['fade_position'] == {'required_for': 'manual', 'otherwise': 'optional; native ignores it'}


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_range_schema_discloses_both_dependent_curve_outcomes(tmp_path, version):
    code, schema = gateway.execute_gateway(['--version', version, 'request-schema',
        'ak.wwise.core.gameParameter.setRange'], env=_env(tmp_path),
        client_factory=lambda _: pytest.fail('offline schema connected'))
    assert code == 0, schema
    assert schema['business_adapter']['declaration']['value_domains']['curve_update_outcome']['choices'] == ['preserve-x', 'stretch']
