"""Native discovery is observable through the Gateway and maintainer CLI."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gateway = load_module("native_catalog_gateway_test", ROOT / "skills/waapi-skill/scripts/gateway.py")
collector = load_module("native_catalog_collector_test", ROOT / "tests/maintenance/collect_authoring_core.py")
URI = "ak.wwise.ui.layout.getLayoutNames"
SCHEMA = {"argsSchema": {"type": "object", "properties": {}, "additionalProperties": False}, "optionsSchema": {"type": "object", "properties": {}}, "resultSchema": {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}}}}


class NativeClient:
    def __init__(self):
        self.calls = []
        self.info = {"displayName": "Wwise", "isCommandLine": False, "processId": 123, "sessionId": "test-session", "version": {"year": 2025, "major": 1, "minor": 7, "build": 9143, "displayName": "2025.1.7.9143"}}

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        return {"ak.wwise.core.getInfo": self.info,
                "ak.wwise.core.getProjectInfo": {"id": "{12345678-1234-1234-1234-123456789012}", "name": "Owned", "path": "\\Owned"},
                "ak.wwise.waapi.getFunctions": {"functions": [URI]},
                "ak.wwise.waapi.getTopics": {"topics": []},
                "ak.wwise.waapi.getSchema": SCHEMA}[uri]

    def disconnect(self):
        pass


def test_maintainer_collects_unknown_native_schema_without_enabling_execution(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    env = {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence")}
    code, payload = gateway.execute_gateway(["config-set", "--wwise-version", "2025.1", "--waapi-host", "127.0.0.1", "--waapi-port", "31337", "--project-modification-policy", "read_only"], env=env)
    assert code == 0, payload
    client = NativeClient()
    def run(argv, **kwargs):
        assert "--version" not in argv, "live version comes only from selected config"
        code, payload = gateway.execute_gateway(argv[3:], env=kwargs["env"], client_factory=lambda url: client)
        return SimpleNamespace(returncode=code, stdout=json.dumps(payload), stderr="")
    output = tmp_path / "capture"
    assert collector.main(["--version", "2025.1", "--build", "2025.1.7.9143", "--host", "wwise-authoring", "--config", str(config), "--output", str(output)], run=run) == 0
    captured = json.loads((output / "native-catalog.json").read_text())
    assert captured["functions"] == [URI]
    assert captured["schemas"][URI] == SCHEMA
    assert captured["provenance"]["session_id"] == "test-session"
    assert {call[0] for call in client.calls} == {"ak.wwise.core.getInfo", "ak.wwise.core.getProjectInfo", "ak.wwise.waapi.getFunctions", "ak.wwise.waapi.getTopics", "ak.wwise.waapi.getSchema"}
    code, result = gateway.execute_gateway(["request-schema", URI], env=env)
    assert code == 2
    assert result["ok"] is False

    catalog_root = tmp_path / "catalog"
    (catalog_root / "2025.1").mkdir(parents=True)
    (catalog_root / "2025.1/wwise-authoring.json").write_bytes((output / "native-catalog.json").read_bytes())
    import hashlib
    (catalog_root / "index.json").write_text(json.dumps({"2025.1/wwise-authoring.json": hashlib.sha256((output / "native-catalog.json").read_bytes()).hexdigest()}))
    monkeypatch.setattr(gateway, "NATIVE_CATALOG_ROOT", catalog_root, raising=False)
    code, discovered = gateway.execute_gateway(["--version", "2025.1", "describe", URI, "--native-host", "wwise-authoring", "--full-schema"], env=env, client_factory=lambda url: pytest.fail("native discovery must be offline"))
    assert code == 0, discovered
    row = discovered["availability"]["2025.1"]["capability"]
    assert row["schema"]["full"] == SCHEMA
    assert row["native_status"] == "present"
    assert row["interface"]["status"] == "missing_implementation"
    assert row["interface"]["execution_enabled_by_catalog"] is False
    assert row["provenance"]["evidence_kind"] == "reflection_only"


@pytest.mark.parametrize("change, message", [("host", "host/version"), ("build", "build mismatch"), ("session", "session changed")])
def test_collection_rejects_wrong_native_attestation(tmp_path, change, message):
    config = tmp_path / "config.json"
    env = {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence")}
    assert gateway.execute_gateway(["config-set", "--wwise-version", "2025.1", "--waapi-host", "127.0.0.1", "--waapi-port", "31337", "--project-modification-policy", "read_only"], env=env)[0] == 0
    client = NativeClient()
    if change == "host":
        client.info["isCommandLine"] = True
    if change == "build":
        client.info["version"]["build"] = 9000
    def run(argv, **kwargs):
        if change == "session" and argv[3] == "waapi-schema":
            client.info["sessionId"] = "changed-session"
        elif change == "session":
            client.info["sessionId"] = "test-session"
        code, payload = gateway.execute_gateway(argv[3:], env=kwargs["env"], client_factory=lambda url: client)
        return SimpleNamespace(returncode=code, stdout=json.dumps(payload), stderr="")
    with pytest.raises(RuntimeError, match=message):
        collector.main(["--version", "2025.1", "--build", "2025.1.7.9143", "--host", "wwise-authoring", "--config", str(config), "--output", str(tmp_path / "capture")], run=run)
    assert not (tmp_path / "capture/native-catalog.json").exists()


def _write_native_fixture(tmp_path, monkeypatch, change=None, reseal=True):
    import hashlib
    root = tmp_path / "native"
    (root / "2025.1").mkdir(parents=True)
    definitions = {"contract": "waapi-skill.definition-graph/v1", "version": "2025.1", "wwise_build": "2025.1.7.9143", "source_file_names": ["common_definitions.json"], "documents": {"common_definitions.json": {"definitions": {"label": {"type": "string"}}}}}
    definitions["inventory_sha256"] = collector.digest(definitions)
    catalog = {"contract": "waapi-skill.native-catalog/v1", "version": "2025.1", "functions": [URI], "topics": [], "schemas": {URI: json.loads(json.dumps(SCHEMA))}, "definitions": definitions, "provenance": {"host": "wwise-authoring", "build": "2025.1.7.9143", "session_id": "native-session", "process_id": 123, "evidence_kind": "reflection_only", "sources": {"capture.json": "a" * 64}}}
    catalog["content_sha256"] = collector.digest(catalog)
    if change:
        change(catalog)
    if reseal:
        catalog["content_sha256"] = collector.digest({k: v for k, v in catalog.items() if k != "content_sha256"})
    raw = json.dumps(catalog).encode()
    (root / "2025.1/wwise-authoring.json").write_bytes(raw)
    (root / "index.json").write_text(json.dumps({"2025.1/wwise-authoring.json": hashlib.sha256(raw).hexdigest()}))
    monkeypatch.setattr(gateway, "NATIVE_CATALOG_ROOT", root)
    return root


@pytest.mark.parametrize("change, expected", [
    (lambda data: data["schemas"].clear(), "schema"),
    (lambda data: data["schemas"][URI]["resultSchema"]["properties"].update({"broken": {"$ref": "common_definitions.json#/definitions/missing"}}), "reference"),
    (lambda data: data["definitions"].update({"wwise_build": "2025.1.6.9000"}), "build"),
])
def test_offline_discovery_rejects_incomplete_native_evidence(tmp_path, monkeypatch, change, expected):
    _write_native_fixture(tmp_path, monkeypatch, change)
    code, payload = gateway.execute_gateway(["--version", "2025.1", "describe", URI, "--native-host", "wwise-authoring", "--full-schema"], env={}, client_factory=lambda url: pytest.fail("offline"))
    assert code == 2, payload
    assert expected in payload["message"].lower()


def test_native_directory_paginates_and_keeps_approved_exclusion_visible(tmp_path, monkeypatch):
    excluded = "ak.wwise.ui.cli.launch"
    def add_excluded(data):
        data["functions"].append(excluded)
        data["schemas"][excluded] = SCHEMA
    _write_native_fixture(tmp_path, monkeypatch, add_excluded)
    command = ["--version", "2025.1", "capabilities", "--native-host", "wwise-authoring", "--limit", "1"]
    code, first = gateway.execute_gateway(command, env={})
    assert code == 0, first
    assert first["match_count"] == 2
    assert first["truncated"] is True
    assert first["capabilities"][0]["uri"] == excluded
    assert first["capabilities"][0]["interface"]["status"] == "approved_exclusion"
    code, second = gateway.execute_gateway(first["continuation"]["gateway_argv"], env={})
    assert code == 0, second
    assert second["capabilities"][0]["uri"] == URI
    assert second["capabilities"][0]["interface"]["status"] == "missing_implementation"
    assert second["truncated"] is False
    assert second["continuation"] is None


@pytest.mark.parametrize("damage", ["missing-context", "wrong-context-host", "same-count-substitution"])
def test_collection_requires_complete_stable_read_attestation(tmp_path, damage):
    config = tmp_path / "config.json"
    env = {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence")}
    assert gateway.execute_gateway(["config-set", "--wwise-version", "2025.1", "--waapi-host", "127.0.0.1", "--waapi-port", "31337", "--project-modification-policy", "read_only"], env=env)[0] == 0
    client = NativeClient()
    function_reads = 0
    def run(argv, **kwargs):
        nonlocal function_reads
        code, payload = gateway.execute_gateway(argv[3:], env=kwargs["env"], client_factory=lambda url: client)
        if argv[3] == "waapi-schema":
            if damage == "missing-context":
                payload.pop("reflection_context", None)
            elif damage == "wrong-context-host":
                payload["reflection_context"]["isCommandLine"] = True
        if argv[3:5] == ["typed-zero-call", "ak.wwise.waapi.getFunctions"]:
            function_reads += 1
            if damage == "same-count-substitution" and function_reads == 2:
                payload["agent_result"]["uris"] = ["ak.wwise.ui.window.present"]
        return SimpleNamespace(returncode=code, stdout=json.dumps(payload), stderr="")
    with pytest.raises(RuntimeError, match="attestation|host|inventory changed"):
        collector.main(["--version", "2025.1", "--build", "2025.1.7.9143", "--host", "wwise-authoring", "--config", str(config), "--output", str(tmp_path / "capture")], run=run)
    assert not (tmp_path / "capture/native-catalog.json").exists()
