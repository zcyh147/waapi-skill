"""Public scoped metadata selection and incompatible-field diagnostics."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.test_field_interface_closure_gateway import FieldTask, FIRST, SECOND, VERSIONS


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_rejected_exact_boolean_rtpc_never_substitutes_nearby_numeric_field(tmp_path: Path, version: str) -> None:
    task = FieldTask(tmp_path, version, "object.setRTPC")
    task.metadata = {
        "Enabled": {"name": "Enabled", "type": "bool", "supports": {"rtpc": "None"}},
        "EnabledAmount": {"name": "EnabledAmount", "type": "Real32", "supports": {"rtpc": "Additive"}},
    }
    target = task.bind(FIRST)
    code, payload = task.step("draft-discover-fields", "--object-handle", target, "--meaning", "Enabled")
    assert code == 2, payload
    rejected = payload["details"]["rejected_candidates"]
    assert rejected == [{"field": "Enabled", "reason": "RTPC requires a numeric property with live RTPC support", "operation": "object.setRTPC"}]
    assert all(uri != "ak.wwise.core.object.setRTPC" for uri, _, _ in task.calls)

@pytest.mark.parametrize("version", VERSIONS)
def test_draft_list_selection_preserves_full_supported_metadata(tmp_path: Path, version: str) -> None:
    task = FieldTask(tmp_path, version, "object.setProperty")
    task.metadata["FadeTime"].update({"default": 0.25, "supports": {"rtpc": "Additive"},
                                     "ui": {"dataMeaning": "Frequency"}})
    target = task.bind(FIRST)
    revision = task.revision
    code, listed = task.step("draft-discover-fields", "--object-handle", target, "--list")
    assert code == 0, listed
    assert task.revision == revision
    selection = listed["agent_result"]["fields"][0]["selection"]
    code, detail = task.step("draft-discover-fields", "--object-handle", target, "--selection", selection)
    assert code == 0, detail
    field = detail["field_candidates"][0]
    assert field["metadata"]["default"] == 0.25
    assert field["metadata"]["restriction"] == {"type": "range", "min": 0, "max": 60}
    assert field["metadata"]["supports"] == {"rtpc": "Additive"}
    assert field["unit"] == {"status": "known", "value": "Frequency"}

@pytest.mark.parametrize("version", VERSIONS)
def test_metadata_selection_rejects_other_scope_and_changed_inventory(tmp_path: Path, version: str) -> None:
    task = FieldTask(tmp_path, version, "object.setProperty")
    first, second = task.bind(FIRST), task.bind(SECOND)
    code, listed = task.step("draft-discover-fields", "--object-handle", first, "--list")
    assert code == 0, listed
    selection = listed["agent_result"]["fields"][0]["selection"]
    code, rejected = task.step("draft-discover-fields", "--object-handle", second, "--selection", selection)
    assert code == 2 and rejected["error_code"] == "METADATA_SELECTION_SCOPE_CHANGED", rejected
    task.metadata["NewParameter"] = {"name": "NewParameter", "type": "bool"}
    code, rejected = task.step("draft-discover-fields", "--object-handle", first, "--selection", selection)
    assert code == 2 and rejected["error_code"] == "METADATA_SELECTION_SCOPE_CHANGED", rejected


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("shell_family", ["native", "windows"])
def test_large_selected_metadata_is_paged_and_field_can_be_declared(tmp_path: Path, version: str, shell_family: str, monkeypatch) -> None:
    if shell_family == "windows":
        import types
        from tests.unit.test_object_graph_business_gateway import gateway
        original = gateway.transaction_next_command
        def windows_continuation(*args, **kwargs):
            actual_os = gateway.os
            gateway.os = types.SimpleNamespace(**{**vars(actual_os), "name": "nt"})
            try:
                return original(*args, **kwargs)
            finally:
                gateway.os = actual_os
        monkeypatch.setattr(gateway, "transaction_next_command", windows_continuation)
    task = FieldTask(tmp_path, version, "object.setProperty")
    text = "声" * 16000
    task.metadata["FadeTime"]["display"] = {"name": "Fade Time", "description": text}
    task.metadata["FadeTimeNearby"] = {"name": "FadeTimeNearby", "type": "bool"}
    target = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", target, "--list")
    assert code == 0, listed
    selection = listed["agent_result"]["fields"][0]["selection"]
    code, acquired = task.step("draft-discover-fields", "--object-handle", target, "--selection", selection)
    assert code == 0, json.dumps(acquired, ensure_ascii=False)
    assert acquired["candidate_count"] == 1
    field = acquired["field_candidates"][0]
    assert field["label"] == "Fade Time"
    pages = [acquired["metadata_detail"]]
    revision = task.revision
    while not pages[-1]["complete"]:
        code, detailed = task.run(*pages[-1]["next_command"]["gateway_argv"])
        assert code == 0, detailed
        pages.append(detailed["agent_result"])
        assert detailed["draft"]["revision"] == revision
    entries = [entry for page in pages for entry in page["entries"]]
    assert "".join(row["value"] for row in entries if row["pointer"] == "/display/description") == text
    assert all(len(json.dumps(page, ensure_ascii=False, indent=2).encode()) <= 28 * 1024 for page in pages)
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field["handle"], "--business-value", "0.5")
    assert code == 0, declared


def test_metadata_pages_obey_utf8_byte_budget(tmp_path: Path) -> None:
    task = FieldTask(tmp_path, "2025.1", "object.setProperty")
    task.metadata = {"声" * 240 + str(i): {"name": "声" * 240 + str(i), "type": "bool"} for i in range(100)}
    target = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", target, "--list", "--page-size", "64")
    assert code == 0, listed
    page = listed["agent_result"]
    assert 0 < len(page["fields"]) < 64
    assert page["remaining_count"] + len(page["fields"]) == 100
    assert len(json.dumps(page, ensure_ascii=False, indent=2).encode("utf-8")) < 28 * 1024

class PropertyTask(FieldTask):
    def call(self, uri, args=None, options=None):
        if uri == "ak.wwise.core.object.setProperty":
            self.calls.append((uri, args, options))
            self.objects[args["object"]]["@" + args["property"]] = args["value"]
            return {}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", VERSIONS)
def test_selected_field_reaches_preview_execution_and_verified_value(tmp_path: Path, version: str) -> None:
    task = PropertyTask(tmp_path, version, "object.setProperty")
    task.metadata = {"Volume": {"name": "Volume", "type": "Real32",
                                "restriction": {"type": "range", "min": -96.3, "max": 12}}}
    task.objects[FIRST].update({"name": "Alarm", "type": "Sound", "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Alarm", "@Volume": 0.0})
    target = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", target, "--list")
    assert code == 0, listed
    code, detail = task.step("draft-discover-fields", "--object-handle", target,
                             "--selection", listed["agent_result"]["fields"][0]["selection"])
    assert code == 0, detail
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", detail["field_candidates"][0]["handle"], "--business-value", "-4")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, json.dumps(checked)
    code, preview = task.step("preview-from-draft")
    assert code == 0, json.dumps(preview)
    assert task.objects[FIRST]["@Volume"] == 0
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, json.dumps(shown)
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, json.dumps(confirmed)
    code, executed = task.run("execute", tx)
    assert code == 0, json.dumps(executed)
    code, verified = task.run("verify", tx)
    assert code == 0, json.dumps(verified)
    assert verified["verified"] is True
    assert task.objects[FIRST]["@Volume"] == -4
    assert sum(uri == "ak.wwise.core.object.setProperty" for uri, _, _ in task.calls) == 1
    assert list(verified)[-1] == "agent_result"


def test_metadata_selection_expires_without_advancing_draft(tmp_path: Path, monkeypatch) -> None:
    import time
    task = FieldTask(tmp_path, "2025.1", "object.setProperty")
    target = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", target, "--list")
    assert code == 0, listed
    selection = listed["agent_result"]["fields"][0]["selection"]
    revision = task.revision
    later = time.time() + 901
    monkeypatch.setattr(time, "time", lambda: later)
    code, rejected = task.step("draft-discover-fields", "--object-handle", target, "--selection", selection)
    assert code == 2 and rejected["error_code"] == "METADATA_SELECTION_EXPIRED", rejected
    assert task.revision == revision


def test_selected_large_enum_exposes_bounded_choices_and_accepts_last_disclosed_value(tmp_path: Path) -> None:
    task = FieldTask(tmp_path, "2025.1", "object.setProperty")
    task.metadata = {"Mode": {"name": "Mode", "type": "int32", "restriction": {"type": "enum", "values": [
        {"value": index, "displayName": f"Mode {index}"} for index in range(1000)]}}}
    target = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", target, "--list")
    assert code == 0, listed
    selection = listed["agent_result"]["fields"][0]["selection"]
    code, acquired = task.step("draft-discover-fields", "--object-handle", target, "--selection", selection)
    assert code == 0, acquired
    assert len(json.dumps(acquired, ensure_ascii=False, indent=2).encode()) < 64 * 1024
    choices = acquired["metadata_detail"]["field"]["choices"]
    values = list(choices["items"])
    while not choices["complete"]:
        code, page = task.run(*choices["next_command"]["gateway_argv"])
        assert code == 0, page
        choices = page["agent_result"]["field"]["choices"]
        values.extend(choices["items"])
    assert values == [{"value": index, "displayName": f"Mode {index}"} for index in range(1000)]
    field = acquired["field_candidates"][0]
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field["handle"], "--business-value", "999")
    assert code == 0, declared


@pytest.mark.parametrize("version", VERSIONS)
def test_selected_long_enum_label_can_be_inspected_and_declared(tmp_path: Path, version: str) -> None:
    task = FieldTask(tmp_path, version, "object.setProperty")
    label = "声" * 24000
    task.metadata = {"Mode": {"name": "Mode", "type": "int32", "restriction": {"type": "enum", "values": [{"value": 42, "displayName": label}]}}}
    target = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", target, "--list")
    assert code == 0, listed
    code, acquired = task.step("draft-discover-fields", "--object-handle", target, "--selection", listed["agent_result"]["fields"][0]["selection"])
    assert code == 0, acquired
    assert len(json.dumps(acquired, ensure_ascii=False, indent=2).encode()) <= 64 * 1024
    field = acquired["field_candidates"][0]
    assert field["value_input"]["choices"][0]["labels_complete"] is False
    assert field["value_input"]["choices"][0]["input"] == "choice:0"
    item = acquired["metadata_detail"]["field"]["choices"]["items"][0]
    assert item["detail_required"] is True
    command = item["next_command"]
    fragments = []
    while command:
        code, page = task.run(*command["gateway_argv"])
        assert code == 0, page
        result = page["agent_result"]
        fragments.extend(entry["value"] for entry in result["entries"] if entry["pointer"] == "/displayName")
        command = result.get("next_command")
    assert "".join(fragments) == label
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
        "--field-handle", field["handle"], "--business-value", "choice:0")
    assert code == 0, declared


@pytest.mark.parametrize("version", VERSIONS)
def test_selected_field_without_native_type_rejects_handle_acquisition(tmp_path: Path, version: str) -> None:
    task = FieldTask(tmp_path, version, "object.setProperty")
    task.metadata = {"Mode": {"name": "Mode", "default": 0}}
    target = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", target, "--list")
    assert code == 0, listed
    revision = task.revision
    code, rejected = task.step("draft-discover-fields", "--object-handle", target, "--selection", listed["agent_result"]["fields"][0]["selection"])
    assert code == 2, rejected
    assert rejected["error_code"] == "GatewayInputError"
    assert rejected["details"]["draft_changed"] is False
    assert rejected["details"]["rejected_candidates"][0]["field"] == "Mode"
    assert task.revision == revision
