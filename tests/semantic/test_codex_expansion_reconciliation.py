"""Expansion reconciliation confines every timed read to a disposable child."""

import json
import time

import pytest

from tests.semantic.support import codex_expansion_reconciliation as reconciliation


FIRST = "{11111111-1111-1111-1111-111111111111}"


def _reply_worker(host, port, version, channel):
    with channel, channel.makefile("rb") as stream:
        request = json.loads(stream.readline())
        payload = {"ok": True, "rows": [{"id": request["ids"][0], "name": "Actual"}]}
        channel.sendall((json.dumps(payload) + "\n").encode())
        stream.readline()


def _partial_worker(host, port, version, channel):
    with channel, channel.makefile("rb") as stream:
        stream.readline()
        channel.sendall(b'{"ok": true')
        time.sleep(30)


def test_actual_snapshot_and_read_only_gateway_share_separate_bounded_guard(monkeypatch):
    monkeypatch.setattr(reconciliation, "_reconciliation_worker", _reply_worker)
    gateway_calls = []
    guard = reconciliation.ExpansionReconciliationGuard(version="2025.1", host="127.0.0.1", port=41234,
        trusted_read=lambda *_: pytest.fail("parent actor used during reconciliation"),
        gateway=lambda argv, **kwargs: gateway_calls.append((argv, kwargs)) or {"ok": True},
        seconds=5, read_seconds=3)
    def snapshot():
        guard.gateway(["query-object", "--exact-id", FIRST])
        return {"actual": list(guard.trusted_read("identity", [FIRST]))}
    receipt = guard.reconcile(snapshot)
    assert receipt["status"] == "completed" and receipt["child_reaped"] is True
    assert receipt["snapshot"]["actual"] == [{"id": FIRST, "name": "Actual"}]
    assert 0 < gateway_calls[0][1]["timeout_seconds"] <= 3
    assert receipt["elapsed_seconds"] <= 7


def test_partial_ipc_reply_expires_and_child_is_reaped(monkeypatch):
    monkeypatch.setattr(reconciliation, "_reconciliation_worker", _partial_worker)
    guard = reconciliation.ExpansionReconciliationGuard(version="2025.1", host="127.0.0.1", port=41234,
        trusted_read=lambda *_: (), gateway=lambda *_: None, seconds=3, read_seconds=1)
    receipt = guard.reconcile(lambda: {"actual": list(guard.trusted_read("identity", [FIRST]))})
    assert receipt["status"] == "error" and receipt["child_reaped"] is True
    assert receipt["elapsed_seconds"] <= 5
    assert len(receipt["error"]["message"].encode()) <= 2048


@pytest.mark.parametrize("command", (["execute", "tx1-owned"], ["draft-start", "audio.import"], ["call", "ak.wwise.core.object.set"]))
def test_guard_never_dispatches_a_mutation_gateway_command(command):
    guard = reconciliation.ExpansionReconciliationGuard(version="2025.1", host="127.0.0.1", port=41234,
        trusted_read=lambda *_: (), gateway=lambda *_: pytest.fail("mutation dispatched"))
    receipt = guard.reconcile(lambda: guard.gateway(command))
    assert receipt["status"] == "error" and receipt["child_reaped"] is True


def test_guarded_gateway_timeout_kills_the_owned_process_group_and_reaps_launcher(monkeypatch):
    import subprocess
    calls = []
    class Process:
        returncode = 0
        def communicate(self, *, timeout):
            calls.append(("communicate", timeout))
            if len(calls) == 2:
                raise subprocess.TimeoutExpired(["runner"], timeout)
            return "", ""
        def poll(self):
            return 0
    def launch(command, **kwargs):
        calls.append(("launch", kwargs))
        return Process()
    monkeypatch.setattr(reconciliation.subprocess, "Popen", launch)
    monkeypatch.setattr(reconciliation, "kill_process_group", lambda process: calls.append(("kill-group", True)))
    with pytest.raises(subprocess.TimeoutExpired):
        reconciliation.run_owned_gateway(["python", "run.py", "gateway.py", "query-object"], environment={}, timeout_seconds=.1)
    assert calls[0][1].get("start_new_session") is True or "creationflags" in calls[0][1]
    assert calls[2] == ("kill-group", True)
    assert calls[3] == ("communicate", 2)


def _exit_worker(host, port, version, channel):
    channel.close()


def test_exited_read_child_cannot_leave_a_pending_snapshot(monkeypatch):
    monkeypatch.setattr(reconciliation, "_reconciliation_worker", _exit_worker)
    guard = reconciliation.ExpansionReconciliationGuard(version="2025.1", host="127.0.0.1", port=41234,
        trusted_read=lambda *_: (), gateway=lambda *_: None, seconds=3, read_seconds=1)
    receipt = guard.reconcile(lambda: {"actual": list(guard.trusted_read("identity", [FIRST]))})
    assert receipt["status"] == "error" and receipt["child_reaped"] is True
    assert receipt["elapsed_seconds"] <= 5


@pytest.mark.parametrize("view,ids", [("ak.wwise.core.object.set", [FIRST]), ("identity", [FIRST, FIRST]),
                                     ("identity", [FIRST] * 65)])
def test_guard_rejects_unreviewed_views_or_unbounded_identifiers_before_child_dispatch(view, ids):
    guard = reconciliation.ExpansionReconciliationGuard(version="2025.1", host="127.0.0.1", port=41234,
        trusted_read=lambda *_: pytest.fail("parent native actor called"), gateway=lambda *_: None)
    receipt = guard.reconcile(lambda: {"actual": list(guard.trusted_read(view, ids))})
    assert receipt["status"] == "error" and receipt["child_reaped"] is True
