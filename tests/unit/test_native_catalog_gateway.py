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


def test_native_directory_filters_category_and_discloses_detail_on_request(tmp_path, monkeypatch):
    _write_native_fixture(tmp_path, monkeypatch)
    command = ["--version", "2025.1", "capabilities", "--native-host", "wwise-authoring", "--category", "ui.layout", "--query", "LAYOUT", "--item-type", "function"]
    code, compact = gateway.execute_gateway(command, env={})
    assert code == 0, compact
    assert compact["match_count"] == 1
    assert compact["capabilities"][0]["category"] == "ui.layout"
    assert "provenance" not in compact["capabilities"][0]
    code, detailed = gateway.execute_gateway([*command, "--detail"], env={})
    assert code == 0, detailed
    assert detailed["capabilities"][0]["provenance"]["session_id"] == "native-session"
    assert detailed["capabilities"][0]["schema"]["sha256"]


@pytest.mark.parametrize("offset, expected_count", [(1, 1), (2, 0), (8, 0)])
def test_execution_directory_last_page_has_no_remaining_truncation(offset, expected_count):
    code, payload = gateway.execute_gateway(["--version", "2025.1", "capabilities", "--query", "waapi.get", "--item-type", "function", "--offset", str(offset + 1), "--limit", "1"], env={})
    assert code == 0, payload
    # Native reflection has getFunctions, getSchema, getTopics: exactly three.
    assert payload["match_count"] == 3
    assert payload["returned_count"] == expected_count
    assert payload["truncated"] is False


@pytest.mark.parametrize("command", ["capabilities", "describe"])
def test_native_host_and_execution_profile_are_not_silently_combined(command):
    argv = ["--version", "2025.1", command]
    if command == "describe":
        argv.append(URI)
    with pytest.raises(SystemExit):
        gateway.execute_gateway([*argv, "--native-host", "wwise-authoring", "--profile", "wwise-console"], env={})


@pytest.mark.parametrize("field, value", [
    ("process_id", True), ("process_id", 0), ("process_id", "123"),
    ("session_id", []), ("session_id", "  "),
    ("sources", {"capture.json": "not-a-digest"}),
    ("sources", {"../capture.json": "a" * 64}),
    ("sources", []),
])
def test_native_discovery_rejects_malformed_provenance(tmp_path, monkeypatch, field, value):
    _write_native_fixture(tmp_path, monkeypatch, lambda data: data["provenance"].update({field: value}))
    code, payload = gateway.execute_gateway(["--version", "2025.1", "describe", URI, "--native-host", "wwise-authoring"], env={})
    assert code == 2, payload
    assert "provenance" in payload["message"].lower()


@pytest.mark.parametrize("tamper", ["body-digest", "same-count-uri", "index-digest", "missing-file", "wrong-host"])
def test_native_discovery_detects_source_seal_and_membership_drift(tmp_path, monkeypatch, tamper):
    replacement = "ak.wwise.ui.window.present"
    def change(data):
        if tamper == "body-digest":
            data["schemas"][URI]["description"] = "changed"
        if tamper == "same-count-uri":
            data["functions"] = [replacement]
            data["schemas"] = {replacement: SCHEMA}
        if tamper == "wrong-host":
            data["provenance"]["host"] = "wwise-console"
    root = _write_native_fixture(tmp_path, monkeypatch, change, reseal=tamper == "wrong-host")
    if tamper == "index-digest":
        (root / "index.json").write_text(json.dumps({"2025.1/wwise-authoring.json": "0" * 64}))
    if tamper == "missing-file":
        (root / "2025.1/wwise-authoring.json").unlink()
    code, payload = gateway.execute_gateway(["--version", "2025.1", "capabilities", "--native-host", "wwise-authoring"], env={})
    assert code == 2, payload
    assert payload["ok"] is False


@pytest.mark.parametrize("version, build", [
    ("2021.1", "2021.1.14.8108"), ("2022.1", "2022.1.19.8584"),
    ("2023.1", "2023.1.19.8928"), ("2024.1", "2024.1.13.9056"),
    ("2025.1", "2025.1.7.9143"),
])
@pytest.mark.parametrize("host", ["wwise-authoring", "wwise-console"])
def test_each_version_and_host_collects_through_its_public_gateway(tmp_path, monkeypatch, version, build, host):
    import hashlib
    config = tmp_path / "config.json"
    env = {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence")}
    assert gateway.execute_gateway(["config-set", "--wwise-version", version, "--waapi-host", "127.0.0.1", "--waapi-port", "31337", "--project-modification-policy", "read_only"], env=env)[0] == 0
    client = NativeClient()
    client.info["isCommandLine"] = host == "wwise-console"
    client.info["version"] = dict(zip(("year", "major", "minor", "build"), map(int, build.split("."))))
    client.info["version"]["displayName"] = build
    original_call = client.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.get":
            client.calls.append((uri, args, options))
            return {"return": [{"id": "{12345678-1234-1234-1234-123456789012}", "name": "Owned", "type": "Project", "path": "\\Owned"}]}
        return original_call(uri, args, options)
    client.call = call
    def run(argv, **kwargs):
        assert "--version" not in argv
        if version in ("2021.1", "2022.1", "2023.1"):
            assert "--exclude-examples" not in argv
        code, payload = gateway.execute_gateway(argv[3:], env=kwargs["env"], client_factory=lambda url: client)
        return SimpleNamespace(returncode=code, stdout=json.dumps(payload), stderr="")
    capture = tmp_path / "capture"
    assert collector.main(["--version", version, "--build", build, "--host", host, "--config", str(config), "--output", str(capture)], run=run) == 0
    catalog_root = tmp_path / "native"
    (catalog_root / version).mkdir(parents=True)
    raw = (capture / "native-catalog.json").read_bytes()
    (catalog_root / version / f"{host}.json").write_bytes(raw)
    (catalog_root / "index.json").write_text(json.dumps({f"{version}/{host}.json": hashlib.sha256(raw).hexdigest()}))
    monkeypatch.setattr(gateway, "NATIVE_CATALOG_ROOT", catalog_root)
    code, result = gateway.execute_gateway(["--version", version, "describe", URI, "--native-host", host, "--full-schema"], env={}, client_factory=lambda url: pytest.fail("offline"))
    assert code == 0, result
    row = result["availability"][version]["capability"]
    assert row["schema"]["full"] == SCHEMA
    assert row["provenance"]["build"] == build
    assert row["host_surface"] == host
    assert row["interface"]["status"] == "missing_implementation"


def test_native_schema_difference_does_not_inherit_execution_readiness(tmp_path, monkeypatch):
    known_uri = "ak.wwise.waapi.getFunctions"
    def native_change(data):
        data["functions"] = [known_uri]
        data["schemas"] = {known_uri: SCHEMA}
    _write_native_fixture(tmp_path, monkeypatch, native_change)
    code, payload = gateway.execute_gateway(["--version", "2025.1", "describe", known_uri, "--native-host", "wwise-authoring", "--full-schema"], env={})
    assert code == 0, payload
    row = payload["availability"]["2025.1"]["capability"]
    assert row["schema"]["full"] == SCHEMA
    assert row["execution_schema_comparison"]["status"] == "different"
    assert row["interface"]["status"] == "native_schema_drift_pending_review"
    assert row["execution_schema_comparison"]["business_execution_proven"] is False


@pytest.mark.parametrize("change, message", [
    (lambda data: data["definitions"].update({"contract": "wrong"}), "definition"),
    (lambda data: data["definitions"].update({"source_file_names": ["absent.json"]}), "definition"),
    (lambda data: data["definitions"]["documents"]["common_definitions.json"].update({"definitions": []}), "definition"),
])
def test_native_discovery_requires_attested_definition_document_structure(tmp_path, monkeypatch, change, message):
    def reseal_definition_change(data):
        change(data)
        data["definitions"]["inventory_sha256"] = collector.digest({k: v for k, v in data["definitions"].items() if k != "inventory_sha256"})
    _write_native_fixture(tmp_path, monkeypatch, reseal_definition_change)
    code, payload = gateway.execute_gateway(["--version", "2025.1", "describe", URI, "--native-host", "wwise-authoring"], env={})
    assert code == 2, payload
    assert message in payload["message"].lower()


def test_native_reference_closure_follows_nested_external_definitions(tmp_path, monkeypatch):
    def nested(data):
        data["schemas"][URI]["resultSchema"]["properties"]["names"]["items"] = {"$ref": "common_definitions.json#/definitions/label"}
        definitions = data["definitions"]
        definitions["documents"]["common_definitions.json"]["definitions"]["label"] = {"anyOf": [{"type": "string"}, {"$ref": "#/definitions/missing"}]}
        definitions["inventory_sha256"] = collector.digest({k: v for k, v in definitions.items() if k != "inventory_sha256"})
    _write_native_fixture(tmp_path, monkeypatch, nested)
    code, payload = gateway.execute_gateway(["--version", "2025.1", "describe", URI, "--native-host", "wwise-authoring", "--full-schema"], env={})
    assert code == 2, payload
    assert "reference" in payload["message"].lower()


def test_full_native_schema_discloses_content_bound_source_pointers(tmp_path, monkeypatch):
    _write_native_fixture(tmp_path, monkeypatch)
    code, payload = gateway.execute_gateway(["--version", "2025.1", "describe", URI, "--native-host", "wwise-authoring", "--full-schema"], env={})
    assert code == 0, payload
    row = payload["availability"]["2025.1"]["capability"]
    assert row["schema"]["source"]["pointer"] == "/schemas/ak.wwise.ui.layout.getLayoutNames"
    assert row["schema"]["source"]["definitions_pointer"] == "/definitions/documents"
    assert len(row["schema"]["source"]["catalog_sha256"]) == 64
    assert row["provenance"]["sources"] == {"capture.json": "a" * 64}
