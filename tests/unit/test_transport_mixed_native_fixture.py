"""Exact version and ownership admission for retired transport observations."""
import pytest


@pytest.mark.parametrize('version,extra', [('2025.1', False), ('2024.1', False), ('2025.1', True)])
def test_mixed_semantics_node_requires_its_exact_single_2025_owner(tmp_path, monkeypatch, version, extra):
    from types import SimpleNamespace
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.transport_semantics import MIXED_NODEID
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    monkeypatch.setenv('WWISE_VERSION', version)
    monkeypatch.delenv('AK_AUTOMATION_MODE', raising=False)
    config = _config(tmp_path)
    config.args = [MIXED_NODEID, *([NODE] if extra else [])]
    items = [SimpleNamespace(nodeid=name) for name in config.args]
    if version != '2025.1' or extra:
        message = 'Selected owned Authoring node is not available on the requested version' if version != '2025.1' else 'only their matching 2025'
        with pytest.raises(pytest.UsageError, match=message):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [event[0] for event in events] == ['construct','start','install']
        assert events[0][1]['live_environment']['AK_AUTOMATION_MODE'] == '1'
        assert 'AK_AUTOMATION_MODE' not in authoring_batch.os.environ
