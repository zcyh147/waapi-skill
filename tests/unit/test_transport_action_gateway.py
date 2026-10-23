from __future__ import annotations

from pathlib import Path
import pytest

from tests.unit.test_runtime_business_gateway import (
    _RuntimeControlDraftClient, _issue_transport_handle, _public_runtime_preview,
    gateway, _env,
)


ACTION = "ak.wwise.core.transport.executeAction"
STATE = "ak.wwise.core.transport.getState"


class TransportActionClient(_RuntimeControlDraftClient):
    def __init__(self, tmp_path: Path, *, version: str = "2025.1") -> None:
        super().__init__(tmp_path, version=version)
        self.calls = []
        self.state = "playing"
        self.after = "stopped"
        self.rows = [{"transport": 74, "object": self.target_id, "gameObject": 1}]
        self.states = {}
        self.read_error = None
        self.state_result = None
        self.list_error = None

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.transport.create":
            return {"transport": self.rows[0]["transport"]}
        if uri == ACTION:
            self.state = self.after
            self.states = {native_id: self.after for native_id in self.states}
            return {}
        if uri == STATE:
            if self.read_error is not None:
                raise self.read_error
            return self.state_result if self.state_result is not None else {"state": self.states.get(args["transport"], self.state)}
        if uri == "ak.wwise.core.transport.getList":
            if self.list_error is not None:
                raise self.list_error
            return {"list": self.rows}
        return super().call(uri, args, options)


def create_handle(tmp_path, client, state_dir):
    preview, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.create")
    executed = invoke(["execute", preview["transaction_id"]])
    return invoke(executed["next_command"]["gateway_argv"])["agent_result"]["business_result"]["transport_handle"]


def test_one_transport_stop_observes_stopped_state_through_public_transaction(tmp_path: Path) -> None:
    client = TransportActionClient(tmp_path)
    state_dir = tmp_path / "state"
    handle = _issue_transport_handle(state_dir, project_path=client.project_file)
    preview, invoke = _public_runtime_preview(tmp_path, client, state_dir, ACTION,
        ("--audition-action", "stop", "--transport-scope", "one-transport", "--transport-handle", handle))
    executed = invoke(["execute", preview["transaction_id"]])
    before_verify = len(client.calls)
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is True
    assert verified["verification"]["business_state_verified"] is True
    assert any(row["uri"] == STATE and row["args"] == {"transport": 74}
        and row["result"] == {"state": "stopped"} for row in verified["verification"]["readbacks"])
    assert sum(uri == STATE for uri, _, _ in client.calls[before_verify:]) == 1
    assert sum(uri == ACTION for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("native_id", (0, 74))
def test_known_retire_recreate_cannot_verify_the_old_action_even_with_identical_native_row(tmp_path: Path, native_id: int) -> None:
    class LifecycleClient(TransportActionClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.transport.destroy":
                self.calls.append((uri, args, options))
                self.rows = []
                return {}
            if uri == "ak.wwise.core.transport.create":
                self.rows = [{"transport": native_id, "object": self.target_id, "gameObject": 1}]
            return super().call(uri, args, options)

    client = LifecycleClient(tmp_path)
    state_dir = tmp_path / "state"
    old_handle = create_handle(tmp_path, client, state_dir)
    preview, invoke = _public_runtime_preview(tmp_path, client, state_dir, ACTION,
        ("--audition-action", "stop", "--transport-scope", "one-transport", "--transport-handle", old_handle))
    executed = invoke(["execute", preview["transaction_id"]])
    destroyed, invoke_destroy = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.destroy",
        ("--transport-handle", old_handle))
    destroy_executed = invoke_destroy(["execute", destroyed["transaction_id"]])
    assert invoke_destroy(destroy_executed["next_command"]["gateway_argv"])["verified"] is True
    new_handle = create_handle(tmp_path, client, state_dir)
    assert new_handle != old_handle
    before_verify = len(client.calls)
    code, rejected = gateway.execute_gateway(["--state-dir", str(state_dir), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2 and rejected["verified"] is False, rejected
    assert rejected["verification"]["verification_strength"] == "gateway_transport_lifetime_invalidated"
    assert not any(uri == STATE for uri, _, _ in client.calls[before_verify:])
    assert sum(uri == ACTION for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("scope", ("one-transport", "all-active"))
def test_transport_list_read_failure_defers_only_verification_and_allows_manual_observation_retry(tmp_path: Path, scope: str) -> None:
    client = TransportActionClient(tmp_path)
    state_dir = tmp_path / "state"
    declaration = ("--audition-action", "stop", "--transport-scope", scope)
    if scope == "one-transport":
        handle = create_handle(tmp_path, client, state_dir)
        declaration += ("--transport-handle", handle)
    preview, invoke = _public_runtime_preview(tmp_path, client, state_dir, ACTION, declaration)
    executed = invoke(["execute", preview["transaction_id"]])
    client.list_error = RuntimeError("transport list observation unavailable")
    code, deferred = gateway.execute_gateway(["--state-dir", str(state_dir), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2 and deferred["status"] == "verification_deferred", deferred
    assert deferred["state"] == "executed_unverified"
    assert deferred["error_code"] == "READBACK_FAILED"
    assert deferred["automatic_retry"] is False
    assert deferred["manual_verification_retry_allowed"] is True
    client.list_error = None
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is True
    code, rejected = gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2, rejected
    assert sum(uri == ACTION for uri, _, _ in client.calls) == 1


def test_observed_malformed_transport_list_fails_verification_instead_of_deferring(tmp_path: Path) -> None:
    client = TransportActionClient(tmp_path)
    state_dir = tmp_path / "state"
    preview, invoke = _public_runtime_preview(tmp_path, client, state_dir, ACTION,
        ("--audition-action", "stop", "--transport-scope", "all-active"))
    executed = invoke(["execute", preview["transaction_id"]])
    client.rows = [{}]
    code, failed = gateway.execute_gateway(["--state-dir", str(state_dir), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2 and failed["state"] == "verification_failed", failed
    assert failed["verified"] is False
    assert failed["verification"]["business_state_verified"] is False
    assert failed["verification"]["verification_scope"]["observation"]["membership_matches"] is False
    assert sum(uri == ACTION for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_stop_verification_discloses_one_observation_and_rejects_wrong_state(tmp_path: Path, version: str) -> None:
    client = TransportActionClient(tmp_path, version=version)
    client.after = "playing"
    state_dir = tmp_path / "state"
    handle = create_handle(tmp_path, client, state_dir)
    preview, invoke = _public_runtime_preview(tmp_path, client, state_dir, ACTION,
        ("--audition-action", "stop", "--transport-scope", "one-transport", "--transport-handle", handle))
    executed = invoke(["execute", preview["transaction_id"]])
    code, verified = gateway.execute_gateway(["--state-dir", str(state_dir), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2
    assert verified["verification"]["business_state_verified"] is False
    scope = verified["verification"]["verification_scope"]
    assert scope["continuous_state_verified"] is False
    assert scope["atomic_scope_verified"] is False
    assert scope["observation"]["targets"][0]["outcome"] == "different_state"


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_transport_schema_explains_pause_toggle_and_observation_boundary(tmp_path: Path, version: str) -> None:
    code, result = gateway.execute_gateway(["request-schema", ACTION], env=_env(tmp_path, version=version),
        client_factory=lambda _: pytest.fail("schema must be offline"))
    assert code == 0, result
    declaration = result["business_adapter"]["declaration"]
    assert declaration["field_semantics"]["audition_action"]["pause"] == "toggle pause/resume; stopped behavior remains unresolved"
    assert declaration["verification"]["maximum_targets"] == 64


VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("action,before,after,expected,outcome", (
    ("stop", "stopped", "stopped", True, "matched"),
    ("play", "stopped", "playing", True, "matched"),
    ("play", "stopped", "stopped", False, "transient_play_unobserved"),
    ("pause", "playing", "paused", True, "matched"),
    ("pause", "paused", "playing", True, "matched"),
    ("pause", "paused", "stopped", False, "transient_play_unobserved"),
    ("pause", "stopped", "stopped", False, "semantics_unresolved"),
    ("toggle-play-stop", "playing", "stopped", True, "matched"),
    ("toggle-play-stop", "stopped", "playing", True, "matched"),
    ("toggle-play-stop", "paused", "stopped", False, "semantics_unresolved"),
    ("play-directly", "stopped", "playing", False, "semantics_unresolved"),
))
def test_actions_observe_only_source_supported_postconditions(
    tmp_path: Path, version: str, action: str, before: str, after: str, expected: bool, outcome: str,
) -> None:
    client = TransportActionClient(tmp_path, version=version)
    state_dir = tmp_path / "state"
    handle = create_handle(tmp_path, client, state_dir)
    client.state, client.after = before, after
    preview, invoke = _public_runtime_preview(tmp_path, client, state_dir, ACTION,
        ("--audition-action", action, "--transport-scope", "one-transport", "--transport-handle", handle))
    executed = invoke(["execute", preview["transaction_id"]])
    before_verify = len(client.calls)
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is expected
    assert verified["verification"]["business_state_verified"] is expected
    assert verified["verification"]["verification_scope"]["observation"]["targets"][0]["outcome"] == outcome
    assert sum(uri == STATE for uri, _, _ in client.calls[before_verify:]) == 1
    assert sum(uri == ACTION for uri, _, _ in client.calls) == 1
    code, repeated = gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2, repeated
    assert sum(uri == ACTION for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("intervention", ("none", "before-membership", "after-membership", "before-state"))
def test_all_scope_binds_membership_and_toggle_prestate(tmp_path: Path, version: str, intervention: str) -> None:
    client = TransportActionClient(tmp_path, version=version)
    client.rows.append({"transport": 0, "object": client.target_id, "gameObject": 2})
    client.states = {0: "stopped", 74: "playing"}
    # pause has a specified playing→paused edge; the stopped target remains
    # unresolved, preventing a partial matched row from granting whole-scope credit.
    client.after = "paused"
    state_dir = tmp_path / "state"
    preview, invoke = _public_runtime_preview(tmp_path, client, state_dir, ACTION,
        ("--audition-action", "pause", "--transport-scope", "all-active"))
    if intervention == "before-membership":
        client.rows.pop()
    elif intervention == "before-state":
        client.states[74] = "paused"
    code, executed = gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    if intervention.startswith("before"):
        assert code == 2 and executed["status"] == "repreview_required", executed
        assert not any(uri == ACTION for uri, _, _ in client.calls)
        return
    assert code == 0, executed
    if intervention == "after-membership":
        client.rows.pop()
    code, verified = gateway.execute_gateway(["--state-dir", str(state_dir), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert verified["verified"] is False
    assert verified["verification"]["business_state_verified"] is False
    observation = verified["verification"]["verification_scope"]["observation"]
    if intervention == "after-membership":
        assert code == 2 and observation["membership_matches"] is False
    else:
        assert code == 0, verified
        assert [row["outcome"] for row in observation["targets"]] == ["semantics_unresolved", "matched"]
    assert sum(uri == ACTION for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("target_count", (0, 2, 64, 65))
def test_all_stop_has_bounded_targets_and_no_vacuous_state_proof(tmp_path: Path, version: str, target_count: int) -> None:
    client = TransportActionClient(tmp_path, version=version)
    client.rows = [{"transport": i, "object": client.target_id, "gameObject": 1} for i in range(target_count)]
    state_dir = tmp_path / "state"
    if target_count > 64:
        with pytest.raises(AssertionError, match="64-target"):
            _public_runtime_preview(tmp_path, client, state_dir, ACTION,
                ("--audition-action", "stop", "--transport-scope", "all-active"))
        assert not any(uri == ACTION for uri, _, _ in client.calls)
        return
    preview, invoke = _public_runtime_preview(tmp_path, client, state_dir, ACTION,
        ("--audition-action", "stop", "--transport-scope", "all-active"))
    executed = invoke(["execute", preview["transaction_id"]])
    before_verify = len(client.calls)
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is (target_count > 0)
    assert sum(uri == STATE for uri, _, _ in client.calls[before_verify:]) == target_count
    assert sum(uri == ACTION for uri, _, _ in client.calls) == 1
    import json
    assert len(json.dumps(verified, ensure_ascii=False).encode()) < gateway.MAX_GATEWAY_RESULT_JSON_BYTES


@pytest.mark.parametrize("version", VERSIONS)
def test_one_transport_can_observe_zero_id_among_more_than_64_unrelated_transports(tmp_path: Path, version: str) -> None:
    client = TransportActionClient(tmp_path, version=version)
    client.rows = [{"transport": i, "object": client.target_id, "gameObject": 1} for i in range(65)]
    state_dir = tmp_path / "state"
    handle = create_handle(tmp_path, client, state_dir)
    preview, invoke = _public_runtime_preview(tmp_path, client, state_dir, ACTION,
        ("--audition-action", "stop", "--transport-scope", "one-transport", "--transport-handle", handle))
    executed = invoke(["execute", preview["transaction_id"]])
    before_verify = len(client.calls)
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is True
    assert [args for uri, args, _ in client.calls[before_verify:] if uri == STATE] == [{"transport": 0}]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("intervention", ("missing", "duplicate", "object", "game-object", "prestate"))
def test_one_scope_rejects_identity_and_prestate_drift_before_mutation(tmp_path: Path, version: str, intervention: str) -> None:
    client = TransportActionClient(tmp_path, version=version)
    state_dir = tmp_path / "state"
    handle = create_handle(tmp_path, client, state_dir)
    preview, _ = _public_runtime_preview(tmp_path, client, state_dir, ACTION,
        ("--audition-action", "pause", "--transport-scope", "one-transport", "--transport-handle", handle))
    if intervention == "missing":
        client.rows = []
    elif intervention == "duplicate":
        client.rows.append(dict(client.rows[0]))
    elif intervention == "object":
        client.rows[0]["object"] = "{22222222-2222-2222-2222-222222222222}"
    elif intervention == "game-object":
        client.rows[0]["gameObject"] = 9
    else:
        client.state = "paused"
    code, rejected = gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2 and rejected["status"] == "repreview_required", rejected
    assert not any(uri == ACTION for uri, _, _ in client.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("intervention", ("unavailable", "non-object", "malformed-state", "missing-state", "wrong-association"))
def test_executed_stop_keeps_failed_or_unavailable_observation_distinct(tmp_path: Path, version: str, intervention: str) -> None:
    client = TransportActionClient(tmp_path, version=version)
    state_dir = tmp_path / "state"
    handle = create_handle(tmp_path, client, state_dir)
    preview, invoke = _public_runtime_preview(tmp_path, client, state_dir, ACTION,
        ("--audition-action", "stop", "--transport-scope", "one-transport", "--transport-handle", handle))
    executed = invoke(["execute", preview["transaction_id"]])
    if intervention == "unavailable":
        client.read_error = RuntimeError("state observer unavailable")
    elif intervention == "non-object":
        client.state_result = []
    elif intervention == "malformed-state":
        client.state_result = {"state": ["stopped"]}
    elif intervention == "missing-state":
        client.state_result = {}
    else:
        client.rows[0]["object"] = "{22222222-2222-2222-2222-222222222222}"
    code, verified = gateway.execute_gateway(["--state-dir", str(state_dir), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2, verified
    if intervention in {"unavailable", "non-object"}:
        assert verified["status"] == "verification_deferred"
        assert verified["state"] == "executed_unverified"
        assert verified["manual_verification_retry_allowed"] is True
        assert verified["automatic_retry"] is False
        assert verified["error_code"] == ("READBACK_FAILED" if intervention == "unavailable" else "INVALID_READBACK")
    else:
        assert verified["verified"] is False
        assert verified["state"] == "verification_failed"
        assert verified["verification"]["business_state_verified"] is False
    code, rejected = gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2, rejected
    assert sum(uri == ACTION for uri, _, _ in client.calls) == 1
