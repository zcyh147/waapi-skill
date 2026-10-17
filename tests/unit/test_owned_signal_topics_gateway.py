"""Signal observations consume resources created through public transactions."""
from __future__ import annotations

import pytest

from tests.unit.test_authoring_model_gateway import (
    ModelClient, confirm_execute_verify, model_preview, rain_template,
)
from tests.unit.test_waapi_gateway import waapi_gateway as gateway


TOPIC = "ak.wwise.ui.signal.toggle"
NATIVE_MODEL = "{44444444-4444-4444-4444-444444444444}"


@pytest.mark.parametrize("signal", ("click", "toggle"))
def test_reviewed_signal_observation_does_not_authorize_the_emitter(signal):
    from wwise_waapi.safety import classify_api_safety
    observation = classify_api_safety("ak.wwise.ui.signal." + signal, "topic", "ui.signal")
    assert observation.read_only is True
    assert observation.requires_destructive_gate is False
    assert classify_api_safety("ak.wwise.ui.signal.emit", "function", "ui.signal").requires_authorization is True
    assert classify_api_safety("ak.wwise.ui.signal.unknown", "topic", "ui.signal").requires_destructive_gate is True


class SignalClient(ModelClient):
    def subscribe(self, uri, callback, options=None):
        self.subscription_options = options
        return super().subscribe(uri, callback, options=options)


def owned_model(tmp_path, version):
    client = SignalClient(tmp_path, version=version)
    env, state, _, preview = model_preview(tmp_path, "window.create",
        {"title": "Weather", "width": 400, "height": 300}, version=version, client=client)
    window = confirm_execute_verify(env, state, client, preview)["agent_result"]["business_result"]["resource_handle"]
    env, state, _, preview = model_preview(tmp_path, "model.registerWafm", rain_template(), version=version, client=client)
    template = confirm_execute_verify(env, state, client, preview)["agent_result"]["business_result"]["resource_handle"]
    env, state, _, preview = model_preview(tmp_path, "model.createHandle", {"window": window, "template": template}, version=version, client=client)
    model = confirm_execute_verify(env, state, client, preview)["agent_result"]["business_result"]["resource_handle"]
    return env, state, client, model


@pytest.fixture(scope="module", params=("2024.1", "2025.1"))
def signal_resources(request, tmp_path_factory):
    return request.param, *owned_model(tmp_path_factory.mktemp("owned-signal-" + request.param), request.param)


@pytest.mark.parametrize("mode", ("wait-topic", "stream-topic"))
def test_signal_observation_derives_native_filter_from_owned_model(signal_resources, mode):
    version, env, state, client, model = signal_resources
    client.subscription_events[TOPIC] = [
        {"handleID": "{55555555-5555-5555-5555-555555555555}", "widgetID": "Rain"},
        {"handleID": NATIVE_MODEL, "widgetID": "Rain"},
    ]
    code, schema = gateway.execute_gateway(["topic-schema", TOPIC], env=env)
    assert code == 0, schema
    records = []
    code, result = gateway.execute_gateway([
        *state, "--timeout", "5", mode, TOPIC,
        "--topic-contract-digest", schema["business_input"]["contract_digest"],
        "--signal-model", model, "--signal-widget", "Rain",
        *(["--event-count", "1"] if mode == "stream-topic" else []),
    ], env=env, client_factory=lambda _url: client, stream_sink=records.append)
    assert code == 0, result
    assert client.subscription_options == {"handleID": NATIVE_MODEL, "widgetID": "Rain"}
    event = result["event"] if mode == "wait-topic" else records[1]["event"]
    assert event == {"handleID": NATIVE_MODEL, "widgetID": "Rain"}
    assert result["monitoring_outcome"]["target_completed"] is True
    assert client.handlers[-1].unsubscribe_calls == 1


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
def test_signal_schema_discloses_owned_observation_flags(version):
    code, schema = gateway.execute_gateway(["--version", version, "topic-schema", TOPIC], env={})
    assert code == 0, schema
    assert schema["continuation"]["owned_signal_observation"] == {
        "model": "--signal-model <owned-model-resource>", "widget": "--signal-widget <owned-widget-key>",
        "binding": "configuration_host_build_session_project_and_active_model_parents",
        "filter": "gateway_derived_native_options_and_exact_callback_identity",
        "unbounded_monitor_scope_read_timeout_seconds": 10.0,
    }
    assert schema["business_input"]["options"]["rows"] == []
    assert schema["business_input"]["gateway_derived_identity_fields"] == ["handle-id", "widget-id"]


@pytest.mark.parametrize("case", ("unknown_model", "unknown_widget", "stale_session", "foreign_configuration", "console_host"))
def test_signal_observation_rejects_unowned_or_stale_target_before_subscribing(signal_resources, tmp_path, monkeypatch, case):
    version, env, state, client, model = signal_resources
    env = dict(env)
    topic, widget = TOPIC, "Rain"
    if case == "unknown_model": model = "ar1-" + "0" * 32
    if case == "unknown_widget": widget = "OtherWidget"
    if case == "stale_session": monkeypatch.setitem(client.responses["ak.wwise.core.getInfo"], "sessionId", "other-session")
    if case == "console_host": monkeypatch.setitem(client.responses["ak.wwise.core.getInfo"], "isCommandLine", True)
    if case == "foreign_configuration":
        from pathlib import Path
        other_config = tmp_path / "foreign.json"
        other_config.write_bytes(Path(env["WAAPI_SKILL_CONFIG_PATH"]).read_bytes())
        env["WAAPI_SKILL_CONFIG_PATH"] = str(other_config)
    code, schema = gateway.execute_gateway(["topic-schema", topic], env=env)
    assert code == 0, schema
    previous = len(client.handlers)
    code, result = gateway.execute_gateway([
        *state, "--timeout", "5", "wait-topic", topic,
        "--topic-contract-digest", schema["business_input"]["contract_digest"],
        "--signal-model", model, "--signal-widget", widget,
    ], env=env, client_factory=lambda _url: client)
    assert code != 0, result
    assert len(client.handlers) == previous
    if case == "console_host": assert result["error_code"] == "AUTHORING_HOST_REQUIRED"


def test_owned_checkbox_can_observe_explicit_click(signal_resources):
    version, env, state, client, model = signal_resources
    topic = "ak.wwise.ui.signal.click"
    client.subscription_events[topic] = [{"handleID": NATIVE_MODEL, "widgetID": "Rain"}]
    code, schema = gateway.execute_gateway(["topic-schema", topic], env=env)
    assert code == 0, schema
    code, result = gateway.execute_gateway([
        *state, "--timeout", "5", "wait-topic", topic,
        "--topic-contract-digest", schema["business_input"]["contract_digest"],
        "--signal-model", model, "--signal-widget", "Rain",
    ], env=env, client_factory=lambda _url: client)
    assert code == 0, result
    assert result["event"] == {"handleID": NATIVE_MODEL, "widgetID": "Rain"}


@pytest.mark.parametrize("policy", ("read_only", "ask_before_changes", "allow_changes"))
def test_signal_observation_is_read_only_under_all_modification_policies(signal_resources, policy):
    version, env, state, client, model = signal_resources
    code, _ = gateway.execute_gateway(["config-set", "--project-modification-policy", policy], env=env)
    assert code == 0
    try:
        client.subscription_events[TOPIC] = [{"handleID": NATIVE_MODEL, "widgetID": "Rain"}]
        code, schema = gateway.execute_gateway(["topic-schema", TOPIC], env=env)
        assert code == 0

        before = len(client.calls)
        code, result = gateway.execute_gateway([
            *state, "--timeout", "5", "wait-topic", TOPIC,
            "--topic-contract-digest", schema["business_input"]["contract_digest"],
            "--signal-model", model, "--signal-widget", "Rain",
        ], env=env, client_factory=lambda _url: client)
        assert code == 0, result
        assert result["monitoring_outcome"]["target_completed"] is True
        assert all(call[0] in {"ak.wwise.core.getInfo", "ak.wwise.core.getProjectInfo"} for call in client.calls[before:])
    finally:
        code, _ = gateway.execute_gateway(["config-set", "--project-modification-policy", "ask_before_changes"], env=env)
        assert code == 0


@pytest.mark.parametrize("arguments", (
    [], ["--signal-model", NATIVE_MODEL, "--signal-widget", "Rain"],
    ["--signal-model", "ar1-" + "0" * 32, "--signal-widget", "Rain", "--topic-option", "handle-id", NATIVE_MODEL],
    ["--signal-model", "ar1-" + "0" * 32, "--signal-widget", "Rain", "--event-match", "widget-id", "Rain"],
))
def test_signal_native_identity_facts_are_not_a_resource_bypass(arguments, tmp_path):
    env = {"WAAPI_SKILL_CONFIG_PATH": str(tmp_path / "absent.json")}
    # Configuration is isolated even though this failure is entirely offline.
    code, _ = gateway.execute_gateway(["config-set", "--wwise-version", "2025.1"], env=env)
    assert code == 0
    code, schema = gateway.execute_gateway(["topic-schema", TOPIC], env=env)
    assert code == 0
    code, result = gateway.execute_gateway([
        "wait-topic", TOPIC, "--topic-contract-digest", schema["business_input"]["contract_digest"], *arguments,
    ], env=env, client_factory=lambda _url: pytest.fail("invalid signal identities connected"))
    assert code == 2, result


def test_owned_signal_stream_without_total_timeout_keeps_resource_reads_bounded(signal_resources):
    version, env, state, client, model = signal_resources
    client.subscription_events[TOPIC] = [{"handleID": NATIVE_MODEL, "widgetID": "Rain"}]
    code, schema = gateway.execute_gateway(["topic-schema", TOPIC], env=env)
    assert code == 0
    records = []
    code, result = gateway.execute_gateway([
        *state, "stream-topic", TOPIC, "--event-count", "1",
        "--topic-contract-digest", schema["business_input"]["contract_digest"],
        "--signal-model", model, "--signal-widget", "Rain",
    ], env=env, client_factory=lambda _url: client, stream_sink=records.append)
    assert code == 0, result
    assert result["subscription_timeout"]["mode"] == "unbounded"
    assert result["idle_timeout"] == {"seconds": 300.0, "source": "default_count_monitor"}
    assert result["monitoring_outcome"]["target_completed"] is True
