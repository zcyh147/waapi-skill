"""Highest public Authoring-project seams with actual saved-project observations."""
from __future__ import annotations

from pathlib import Path
import json
import os

import pytest

from tests.unit.test_host_ui_debug_business_adapter import gateway, _env
from tests.unit.test_transaction_gateway import live_info, expected_wine_dispatch_path
from wwise_waapi.transactions import TransactionStore


CREATE = "ak.wwise.ui.project.create"
PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
OTHER_ID = "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"


def _saved_project(version: str, configuration: str, effect: str) -> str:
    # Independent literal fixture: the writer never derives its effect from
    # the dispatched request. Matching SDK samples own the XML element names.
    platform = ('<Platform Name="Studio" ReferencePlatform="Mac" ID="{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}" />'
        if configuration in {"configured", "base-only"} else
        '<Platform Name="Windows" ReferencePlatform="Windows" ID="{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}" />')
    languages = ('<Language Name="Japanese" ID="{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}" />'
        '<Language Name="English(US)" ID="{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}" />'
        if configuration == "configured" else
        '<Language Name="English(US)" ID="{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}" />')
    default = "Japanese" if configuration == "configured" else "English(US)"
    if effect == "wrong-platform":
        platform = platform.replace('ReferencePlatform="Mac"', 'ReferencePlatform="Windows"')
    if effect == "wrong-language":
        languages = languages.replace('Name="Japanese"', 'Name="French"')
    if effect == "wrong-default":
        default = "English(US)"
    name = "Wrong" if effect == "wrong-name" else "NewProject"
    schema = {"2023.1": 119, "2024.1": 123, "2025.1": 133}[version]
    return (f'<WwiseDocument Type="Project" SchemaVersion="{schema}" WwiseVersion="v{version}.0">'
        f'<ProjectInfo><Project Name="{name}" ID="{PROJECT_ID}"><Platforms>{platform}</Platforms>'
        f'<LanguageList>{languages}</LanguageList><PropertyList>'
        f'<Property Name="DefaultLanguage" Type="string" Value="{default}" />'
        '</PropertyList></Project></ProjectInfo></WwiseDocument>')


class _ProjectClient:
    def __init__(self, version: str, target: Path, expected: dict, *, configuration: str, effect: str, wine: bool = False):
        self.version, self.target, self.expected = version, target, expected
        self.configuration, self.effect = configuration, effect
        self.wine = wine
        self.native_expected = ({**expected, "path": expected_wine_dispatch_path(target, account_home=target.parent.parent.resolve())}
            if wine else expected)
        self.opened = False
        self.info_overrides = {}
        self.calls = []

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            info = live_info(year=int(self.version[:4]), is_command_line=False)
            if self.wine:
                info.update(platform="x64", processPath=r"c:\Program Files\Audiokinetic\Wwise\Wwise.exe")
            info.update(self.info_overrides)
            return info
        if uri == "ak.wwise.core.object.get":
            assert args == {"waql": "from type Project take 2"}, args
            assert options == {"return": ["id", "name", "type", "path", "filePath"]}, options
            if not self.opened:
                return {"return": []}
            return {"return": [{"id": OTHER_ID if self.effect == "wrong-guid" else PROJECT_ID,
                "name": "Wrong" if self.effect == "wrong-name" else "NewProject", "type": "Project",
                "path": "\\", "filePath": self.native_expected["path"]}]}
        assert uri == CREATE and args == self.native_expected and options == {}, (uri, args, options)
        assert not self.opened and not self.target.exists()
        if self.effect != "missing-artifact":
            self.target.parent.mkdir(exist_ok=True)
            self.target.write_text(_saved_project(self.version, self.configuration, self.effect), encoding="utf-8")
        self.opened = True
        return {}

    def disconnect(self):
        pass


def _preview_creation(tmp_path, version, configuration, effect="exact", *, wine=False):
    target = tmp_path / "NewProject" / "NewProject.wproj"
    if configuration != "new-directory":
        target.parent.mkdir()
    declaration = ["--value", "project_file", str(target)]
    expected = {"path": str(target)}
    if configuration == "configured":
        declaration += ["--item", "languages", "Japanese", "--item", "languages", "English(US)",
            "--mapping", "platforms", "Mac", "Studio"]
        expected.update(languages=["Japanese", "English(US)"], platforms=[{"basePlatform": "Mac", "name": "Studio"}])
    elif configuration == "base-only":
        declaration += ["--item", "platforms", "Mac"]
        expected["platforms"] = [{"basePlatform": "Mac"}]
    else:
        for field in ("languages", "platforms"):
            if configuration in {f"empty-{field}", "empty-both"}:
                declaration += ["--empty", field]
                expected[field] = []
    client = _ProjectClient(version, target, expected, configuration=configuration, effect=effect, wine=wine)
    state = tmp_path / "state"
    env = _env(tmp_path, version)
    def run(*argv):
        gateway.build_parser().parse_args(list(argv))
        return gateway.execute_gateway(["--state-dir", str(state), *argv], env=env, client_factory=lambda _: client)
    code, schema = run("request-schema", CREATE)
    assert code == 0 and schema["continuation"]["gateway_argv"] == ["draft-start", CREATE], schema
    forms = schema["business_adapter"]["declaration"]["input_forms"]
    assert forms["platforms"]["base_only_form"]["flag"] == "--item"
    assert forms["platforms"]["empty_form"]["arguments"] == ["platforms"]
    assert forms["languages"]["empty_form"]["arguments"] == ["languages"]
    code, started = run(*schema["continuation"]["gateway_argv"])
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    code, declared = run("draft-declare-host-plan", draft_id, "--task-authority", authority,
        "--expected-revision", "1", *declaration)
    assert code == 0, declared
    code, checked = run("draft-check", draft_id, "--task-authority", authority,
        "--expected-revision", str(declared["draft"]["revision"]))
    assert code == 0, checked
    code, previewed = run("preview-from-draft", draft_id, "--task-authority", authority,
        "--expected-revision", str(checked["draft"]["revision"]))
    assert code == 0, previewed
    transaction = previewed["transaction_id"]
    snapshot = TransactionStore(state).load_snapshot(transaction)
    artifact = TransactionStore(state).load_preview(transaction).artifact
    assert artifact["request"]["arguments"]["args"] == expected
    assert not target.exists() and not any(uri == CREATE for uri, _, _ in client.calls)
    return run, client, transaction, snapshot


@pytest.mark.parametrize("drift", ["destination", "ancestor", "session", "console-host", "version", "config", "project"])
def test_authoring_project_create_blocks_preview_drift_before_dispatch(tmp_path, drift):
    run, client, transaction, snapshot = _preview_creation(tmp_path, "2023.1", "defaults")
    code, confirmed = run("confirm", transaction, "--confirmation-token", snapshot.confirmation_token)
    assert code == 0, confirmed
    if drift == "destination":
        client.target.write_bytes(b"externally created project")
    elif drift == "ancestor":
        client.target.parent.rename(tmp_path / "MovedProject")
        client.target.parent.mkdir()
    elif drift == "session":
        client.info_overrides["sessionId"] = OTHER_ID
    elif drift == "console-host":
        client.info_overrides["isCommandLine"] = True
    elif drift == "version":
        client.info_overrides["version"] = live_info(year=2024)["version"]
    elif drift == "config":
        code, configured = run("config-set", "--waapi-port", "31338")
        assert code == 0, configured
    else:
        client.opened = True
    code, rejected = run("execute", transaction)
    assert code == 2, json.dumps(rejected)
    assert not any(uri == CREATE for uri, _, _ in client.calls)
    if drift == "destination":
        assert client.target.read_bytes() == b"externally created project"
    else:
        assert not client.target.exists()


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.skipif(os.name == "nt", reason="Wine mapping is POSIX-only")
def test_authoring_project_create_missing_directory_uses_sealed_wine_mapping(tmp_path, monkeypatch, version):
    from wwise_waapi import platform_paths
    monkeypatch.setattr(platform_paths, "_account_home", lambda value: tmp_path.resolve())
    run, client, transaction, snapshot = _preview_creation(tmp_path, version, "new-directory", wine=True)
    code, confirmed = run("confirm", transaction, "--confirmation-token", snapshot.confirmation_token)
    assert code == 0, confirmed
    code, executed = run("execute", transaction)
    assert code == 0, json.dumps(executed)
    assert len([call for call in client.calls if call[0] == CREATE]) == 1
    code, verified = run("verify", transaction)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("configuration,effect", [
    (configuration, "exact") for configuration in ["defaults", "configured", "base-only", "empty-languages", "empty-platforms", "empty-both", "new-directory"]
] + [("configured", effect) for effect in ["missing-artifact", "wrong-platform", "wrong-language", "wrong-default", "wrong-guid", "wrong-name"]])
def test_authoring_project_create_verifies_saved_requested_effect(tmp_path, version, configuration, effect):
    run, client, transaction, snapshot = _preview_creation(tmp_path, version, configuration, effect)
    code, confirmed = run("confirm", transaction, "--confirmation-token", snapshot.confirmation_token)
    assert code == 0, confirmed
    code, executed = run("execute", transaction)
    assert code == 0, executed
    code, verified = run("verify", transaction)
    diagnostic = json.dumps(verified, ensure_ascii=False)
    retained = next(event["details"]["verification"]
        for event in TransactionStore(tmp_path / "state").read_events(transaction)
        if event["event_type"] == "verification_recorded")
    if effect != "exact":
        assert code == 2 and verified["verified"] is False, diagnostic
    elif configuration.startswith("empty-"):
        assert code == 0 and verified["verified"] is False, diagnostic
        assert verified["verification"]["business_state_verified"] is False
        assert any(row.get("kind") == "project-transition-observation" for row in retained["readbacks"])
    else:
        assert code == 0 and verified["verified"] is True, diagnostic
        assert verified["verification"]["business_state_verified"] is True
        assert any(row.get("kind") == "authoring-created-project-artifact" for row in retained["readbacks"])
    assert len([uri for uri, _, _ in client.calls if uri == CREATE]) == 1
    code, repeated = run("execute", transaction)
    assert code == 2, repeated
    assert len([uri for uri, _, _ in client.calls if uri == CREATE]) == 1


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_authoring_project_close_accepts_observed_no_project(tmp_path, version):
    close = "ak.wwise.ui.project.close"
    calls = []
    class Client:
        def call(self, uri, args=None, options=None):
            calls.append((uri, args, options))
            if uri == "ak.wwise.core.getInfo":
                return live_info(year=int(version[:4]), is_command_line=False)
            if uri == "ak.wwise.core.object.get":
                assert args == {"waql": "from type Project take 2"}
                assert options == {"return": ["id", "name", "type", "path", "filePath"]}
                return {"return": []}
            assert (uri, args, options) == (close, {"bypassSave": False}, {})
            return {"hadProjectOpen": False}
        def disconnect(self):
            pass
    state, env = tmp_path / "state", _env(tmp_path, version)
    def run(*argv):
        gateway.build_parser().parse_args(list(argv))
        return gateway.execute_gateway(["--state-dir", str(state), *argv], env=env, client_factory=lambda _: Client())
    code, schema = run("request-schema", close)
    assert code == 0, schema
    code, started = run(*schema["continuation"]["gateway_argv"])
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    code, declared = run("draft-declare-host-plan", draft_id, "--task-authority", authority, "--expected-revision", "1")
    assert code == 0, declared
    code, checked = run("draft-check", draft_id, "--task-authority", authority, "--expected-revision", str(declared["draft"]["revision"]))
    assert code == 0, checked
    code, previewed = run("preview-from-draft", draft_id, "--task-authority", authority, "--expected-revision", str(checked["draft"]["revision"]))
    assert code == 0, previewed
    transaction = previewed["transaction_id"]
    token = TransactionStore(state).load_snapshot(transaction).confirmation_token
    code, confirmed = run("confirm", transaction, "--confirmation-token", token)
    assert code == 0, confirmed
    code, executed = run("execute", transaction)
    assert code == 0, executed
    code, verified = run("verify", transaction)
    assert code == 0 and verified["verified"] is True, verified
    code, rejected = run("execute", transaction)
    assert code == 2, rejected
    assert len([uri for uri, _, _ in calls if uri == close]) == 1
