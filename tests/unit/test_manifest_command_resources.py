"""Public Gateway commands reuse packaged evidence without retaining authority."""
from pathlib import Path

import pytest

from tests.unit.test_waapi_gateway import gateway_env, waapi_gateway as gateway


def test_authoring_description_reuses_evidence_only_within_one_command(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2] / 'skills/waapi-skill/resources/manifest/2025.1/authoring-model-supplement.json'
    read_text = Path.read_text
    reads = []
    damaged = False

    def read(path, *args, **kwargs):
        text = read_text(path, *args, **kwargs)
        if path == source:
            reads.append(path)
            if damaged:
                return text.replace('Creates a window', 'Damages a window')
        return text

    monkeypatch.setattr(Path, 'read_text', read)
    argv = ['--version', '2025.1', 'describe', 'ak.wwise.ui.window.create',
            '--profile', 'wwise-authoring-ui', '--full-schema']
    env = gateway_env(tmp_path)

    def describe():
        return gateway.execute_gateway(argv, env=env,
            client_factory=lambda _: pytest.fail('offline description opened a live client'))

    code, response = describe()
    assert code == 0, response
    capability = response['availability']['2025.1']['capability']
    assert capability['interface']['read_only'] is False
    assert capability['interface']['preferred_route'] == 'transaction_operation'
    args_schema = capability['schema']['full']['argsSchema']
    assert args_schema['required'] == ['title', 'size']
    assert args_schema['properties']['size']['required'] == ['width', 'height']
    assert len(reads) == 1, 'one command must compose one fresh Authoring profile'

    # Returned mutable output cannot poison a later command's resource view.
    args_schema['required'].clear()
    code, repeated = describe()
    assert code == 0, repeated
    assert repeated['availability']['2025.1']['capability']['schema']['full']['argsSchema']['required'] == ['title', 'size']
    assert len(reads) == 2

    # Same-length source corruption must be rechecked, not hidden by process caching.
    damaged = True
    code, rejected = describe()
    assert code != 0 and 'digest mismatch' in str(rejected), rejected
    assert len(reads) == 3
