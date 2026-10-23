"""Public saved-capture artifact proof; opaque bytes do not prove native .prof validity."""
from pathlib import Path
import os
import sys

import pytest

from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env
from tests.support.gateway_config import set_gateway_config
from wwise_waapi.transactions import TransactionStore
from scripts import gateway


SAVE_CAPTURE = "ak.wwise.core.profiler.saveCapture"
VERSIONS = ("2023.1", "2024.1", "2025.1")


class CaptureTask:
    def __init__(self, tmp_path: Path, version: str = "2025.1", name: str = "Weather"):
        self.state = tmp_path / "state"
        self.output = tmp_path / "captures"
        self.output.mkdir()
        self.destination = self.output / (name if name.casefold().endswith(".prof") else name + ".prof")
        self.client = _RuntimeControlDraftClient(tmp_path, version=version)
        self.env = _env(tmp_path, version=version)
        self.calls = []
        self.effect = lambda: self.destination.write_bytes(b"opaque fixture capture bytes")
        original = self.client.call

        def call(uri, args=None, options=None):
            self.calls.append((uri, args, options))
            if uri == SAVE_CAPTURE:
                self.effect()
                return {}
            return original(uri, args, options)

        self.client.call = call
        self.name = name

    def execute(self, *argv):
        return gateway.execute_gateway(["--state-dir", str(self.state), *argv],
            env=self.env, client_factory=lambda _: self.client)

    def run(self, *argv):
        code, payload = self.execute(*argv)
        assert code == 0, payload
        return payload

    def preview(self):
        started = self.run("draft-start", SAVE_CAPTURE)
        draft, authority = started["draft"]["draft_id"], started["task_authority"]
        declared = self.run("draft-declare-runtime-control-plan", draft, "--task-authority", authority,
            "--expected-revision", str(started["draft"]["revision"]),
            "--capture-output-directory", str(self.output), "--capture-name", self.name)
        checked = self.run("draft-check", draft, "--task-authority", authority,
            "--expected-revision", str(declared["draft"]["revision"]))
        preview = self.run("preview-from-draft", draft, "--task-authority", authority,
            "--expected-revision", str(checked["draft"]["revision"]))
        self.tx = preview["transaction_id"]
        self.artifact = TransactionStore(self.state).load_preview(self.tx).artifact
        return preview

    def confirm(self):
        snapshot = TransactionStore(self.state).load_snapshot(self.tx)
        self.run("confirm", self.tx, "--confirmation-token", snapshot.confirmation_token)

    def evidence(self):
        shown = self.run("transaction-show", self.tx)
        return next(event["details"]["verification"] for event in reversed(shown["events"])
            if event["event_type"] == "verification_recorded")


@pytest.mark.parametrize("version", VERSIONS)
def test_saved_capture_public_transaction_proves_exact_created_artifact_and_preservation(tmp_path, version):
    task = CaptureTask(tmp_path, version)
    sibling = task.output / "unrelated.txt"
    sibling.write_bytes(b"preserve me")
    task.preview()
    assert not task.destination.exists()
    assert not any(uri == SAVE_CAPTURE for uri, _, _ in task.calls)
    task.confirm()
    task.run("execute", task.tx)
    verified = task.run("verify", task.tx)
    assert verified["verification"]["business_state_verified"] is True, verified
    assert verified["verification"]["verification_strength"] == "profiler_capture_artifact"
    scope = verified["verification"]["verification_scope"]
    assert scope["capture_content_completeness_verified"] is False
    assert scope["capture_format_validity_verified"] is False
    observed = task.evidence()["readbacks"][0]
    assert observed["path"] == str(task.destination)
    assert observed["created"] is True and observed["changed"] is True
    assert observed["unrelated_files_preserved"] is True
    assert sibling.read_bytes() == b"preserve me"
    assert (SAVE_CAPTURE, {"file": str(task.destination)}, {}) in task.calls
    assert len([call for call in task.calls if call[0] == SAVE_CAPTURE]) == 1
    assert task.execute("execute", task.tx)[0] == 2
    assert len([call for call in task.calls if call[0] == SAVE_CAPTURE]) == 1


@pytest.mark.parametrize("version", VERSIONS)
def test_capture_schema_discloses_artifact_scope_and_gateway_resource_bounds(tmp_path, version):
    task = CaptureTask(tmp_path, version)
    schema = task.run("request-schema", SAVE_CAPTURE)
    verification = schema["business_adapter"]["declaration"]["verification"]
    assert verification["capture_format_validity_verified"] is False
    assert verification["capture_content_completeness_verified"] is False
    assert verification["requires_created_or_content_changed_nonempty_file"] is True
    assert verification["resource_bounds"]["max_file_bytes"] == 512 * 1024 * 1024
    assert task.calls == []


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("existing", (False, True))
def test_saved_capture_requires_new_nonempty_contents_not_empty_success_or_touch(tmp_path, version, existing):
    task = CaptureTask(tmp_path, version)
    if existing:
        task.destination.write_bytes(b"preexisting opaque bytes")
    task.effect = lambda: task.destination.touch() if existing else None
    task.preview()
    task.confirm()
    task.run("execute", task.tx)
    code, result = task.execute("verify", task.tx)
    assert code == 2 and result["state"] == "verification_failed", result
    assert result["verification"]["business_state_verified"] is False
    assert result["automatic_retry"] is False
    assert task.execute("execute", task.tx)[0] == 2
    observed = task.evidence()["readbacks"][0]
    assert observed["created"] is False and observed["changed"] is False
    assert len([call for call in task.calls if call[0] == SAVE_CAPTURE]) == 1


@pytest.mark.parametrize("outcome", ("empty", "directory", "symlink", "sibling-change", "unreadable", "root-replaced"))
def test_saved_capture_invalid_or_unprotected_artifact_cannot_verify_empty_native_success(tmp_path, monkeypatch, outcome):
    task = CaptureTask(tmp_path)
    sibling = task.output / "untouched.dat"
    sibling.write_bytes(b"preserve me")
    task.preview()
    task.confirm()
    if outcome == "empty":
        task.effect = lambda: task.destination.write_bytes(b"")
    elif outcome == "directory":
        task.effect = lambda: task.destination.mkdir()
    elif outcome == "symlink":
        task.effect = lambda: task.destination.symlink_to(sibling)
    elif outcome == "sibling-change":
        def write_both():
            task.destination.write_bytes(b"opaque capture fixture")
            sibling.write_bytes(b"unexpected change")
        task.effect = write_both
    elif outcome == "root-replaced":
        def replace_root():
            task.output.rename(tmp_path / "old-captures")
            task.output.mkdir()
            (task.output / sibling.name).write_bytes(b"preserve me")
            task.destination.write_bytes(b"opaque capture fixture")
        task.effect = replace_root
    task.run("execute", task.tx)
    if outcome == "unreadable":
        real_open = os.open
        def deny_output(path, flags, *args, **kwargs):
            if Path(path) == task.destination:
                raise PermissionError("fixture denies capture artifact reads")
            return real_open(path, flags, *args, **kwargs)
        monkeypatch.setattr(os, "open", deny_output)
    code, result = task.execute("verify", task.tx)
    assert code == 2 and result["state"] == "verification_failed", result
    assert result["verification"]["business_state_verified"] is False
    assert result["automatic_retry"] is False
    assert task.execute("execute", task.tx)[0] == 2
    assert len([call for call in task.calls if call[0] == SAVE_CAPTURE]) == 1


@pytest.mark.parametrize("drift", ("destination", "sibling", "root", "symlink"))
def test_capture_preview_filesystem_drift_blocks_save_before_dispatch(tmp_path, drift):
    task = CaptureTask(tmp_path)
    task.preview()
    task.confirm()
    if drift == "destination":
        task.destination.write_bytes(b"a different actor created this")
    elif drift == "sibling":
        (task.output / "other.prof").write_bytes(b"new unrelated contents")
    elif drift == "root":
        task.output.rename(tmp_path / "original-captures")
        task.output.mkdir()
    else:
        target = tmp_path / "elsewhere"
        target.write_bytes(b"must stay intact")
        task.destination.symlink_to(target)
    code, result = task.execute("execute", task.tx)
    assert code == 2, result
    assert not any(uri == SAVE_CAPTURE for uri, _, _ in task.calls)


@pytest.mark.parametrize("name", ["Weather.PROF", "Harbor 雨 & $(literal)"] + ([] if sys.platform == "win32" else ['Weather "A"', r"Weather\A"]))
def test_capture_existing_host_name_and_extension_contract_is_preserved(tmp_path, name):
    task = CaptureTask(tmp_path, name=name)
    task.destination.write_bytes(b"old opaque fixture")
    task.preview()
    task.confirm()
    task.run("execute", task.tx)
    result = task.run("verify", task.tx)
    assert result["verification"]["business_state_verified"] is True
    observed = task.evidence()["readbacks"][0]
    assert observed["created"] is False and observed["changed"] is True


@pytest.mark.parametrize("nested", (False, True))
def test_capture_missing_output_directory_retains_existing_public_contract(tmp_path, nested):
    task = CaptureTask(tmp_path)
    task.output.rmdir()
    if nested:
        task.output = tmp_path / "missing" / "captures"
        task.destination = task.output / "Weather.prof"
    task.effect = lambda: (task.output.mkdir(parents=True), task.destination.write_bytes(b"opaque fixture"))
    task.preview()
    task.confirm()
    task.run("execute", task.tx)
    assert task.run("verify", task.tx)["verification"]["business_state_verified"] is True


def test_missing_capture_ancestor_cannot_redirect_exact_authorized_destination(tmp_path, monkeypatch):
    task = CaptureTask(tmp_path)
    task.output.rmdir()
    task.output = tmp_path / "missing" / "captures"
    task.destination = task.output / "Weather.prof"
    redirected = tmp_path / "redirected"
    (redirected / "captures").mkdir(parents=True)
    task.preview()
    task.confirm()

    def redirected_save():
        (tmp_path / "missing").symlink_to(redirected, target_is_directory=True)
        task.destination.write_bytes(b"opaque fixture capture bytes")

    task.effect = redirected_save
    task.run("execute", task.tx)
    content_reads = []
    real_open, real_scandir = os.open, os.scandir

    def track_open(path, *args, **kwargs):
        if Path(path).resolve().is_relative_to(redirected):
            content_reads.append(("file", str(path)))
        return real_open(path, *args, **kwargs)

    def track_scandir(path):
        if Path(path).resolve().is_relative_to(redirected):
            content_reads.append(("tree", str(path)))
        return real_scandir(path)

    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "scandir", track_scandir)
    code, result = task.execute("verify", task.tx)
    assert code == 2 and result["verification"]["business_state_verified"] is False, result
    assert content_reads == [], "Unapproved redirected contents must not be read before binding fails"
    assert result["state"] == "verification_failed" and result["automatic_retry"] is False
    assert any(row.get("evidence", {}).get("error_code") == "FILE_CHANGED"
        for row in task.evidence()["assertions"])
    assert task.execute("execute", task.tx)[0] == 2
    assert len([call for call in task.calls if call[0] == SAVE_CAPTURE]) == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
@pytest.mark.parametrize("command", ("request-schema", "draft-start"))
def test_capture_route_is_not_offered_on_older_packaged_definitions(tmp_path, version, command):
    code, result = gateway.execute_gateway([command, SAVE_CAPTURE], env=_env(tmp_path, version=version),
        client_factory=lambda _: pytest.fail("unavailable route must remain offline"))
    assert code == 2 and result["error_code"] == "TypedRequestError", result


def test_capture_save_requires_material_authorization_before_effect(tmp_path):
    task = CaptureTask(tmp_path)
    task.preview()
    code, result = task.execute("execute", task.tx)
    assert code == 2, result
    assert not task.destination.exists()
    assert not any(uri == SAVE_CAPTURE for uri, _, _ in task.calls)


@pytest.mark.parametrize("change", ({"waapi_port": 31338}, {"project_modification_policy": "read_only"}))
def test_capture_save_retains_configuration_and_read_only_policy_guards(tmp_path, change):
    task = CaptureTask(tmp_path)
    task.preview()
    task.confirm()
    set_gateway_config(task.env, **change)
    code, result = task.execute("execute", task.tx)
    assert code == 2, result
    assert not task.destination.exists()
    assert not any(uri == SAVE_CAPTURE for uri, _, _ in task.calls)


def test_capture_uncertain_native_failure_retains_output_without_replaying_save(tmp_path):
    task = CaptureTask(tmp_path)
    def ambiguous_write():
        task.destination.write_bytes(b"possible partial native output")
        raise RuntimeError("write outcome lost")
    task.effect = ambiguous_write
    task.preview()
    task.confirm()
    code, result = task.execute("execute", task.tx)
    assert code == 2, result
    assert result["automatic_retry"] is False
    assert task.destination.exists()
    assert task.execute("execute", task.tx)[0] == 2
    assert len([call for call in task.calls if call[0] == SAVE_CAPTURE]) == 1


def test_capture_oversized_artifact_has_explicit_bounded_failure_after_one_save(tmp_path):
    task = CaptureTask(tmp_path)
    def oversized_output():
        with task.destination.open("wb") as output:
            output.truncate(512 * 1024 * 1024 + 1)
    task.effect = oversized_output
    task.preview()
    task.confirm()
    task.run("execute", task.tx)
    code, result = task.execute("verify", task.tx)
    assert code == 2 and result["verification"]["business_state_verified"] is False, result
    assert any(row.get("evidence", {}).get("error_code") == "LIMIT_EXCEEDED"
        for row in task.evidence()["assertions"])
    assert task.execute("execute", task.tx)[0] == 2
    assert len([call for call in task.calls if call[0] == SAVE_CAPTURE]) == 1
