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
        if uri == "ak.wwise.core.object.setReference":
            self.calls.append((uri, args, options))
            self.objects[args["object"]]["@" + args["reference"]] = None
            return {}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", VERSIONS[2:])
def test_state_column_selection_routes_existing_custom_state_value_to_instance_field(tmp_path: Path, version: str) -> None:
    task = PropertyTask(tmp_path, version, "object.setProperty")
    columns_uri = "ak.wwise.core.object.setStateProperties"
    code, described = task.run("describe", columns_uri)
    assert code == 0, described
    guidance = described["availability"][version]["capability"]["interface"]["selection_guidance"]
    # The SDK distinguishes the States tab's visible columns from an existing
    # CustomState's scalar values. The latter must lead to a callable field route.
    edit_route, = [item for item in guidance["choose_instead"] if item["target"] == "object.setProperty"]
    assert "CustomState" in edit_route["when"]
    assert "column" in " ".join(guidance["use_when"]).lower()
    code, runtime = task.run("describe", "ak.soundengine.setState")
    assert code == 0, runtime
    alternatives = runtime["availability"][version]["capability"]["interface"]["selection_guidance"]["choose_instead"]
    assert any(item["target"] == edit_route["target"] and "CustomState" in item["when"] for item in alternatives)
    assert any(item["target"] == columns_uri and "column" in item["when"].lower() for item in alternatives)
    code, columns = task.run("request-schema", columns_uri)
    assert code == 0, columns
    assert set(columns["business_adapter"]["declaration"]["required_fields"]) == {"object_handle", "field_handles"}
    code, schema = task.run("operation-schema", edit_route["target"])
    assert code == 0, schema

    task.set_object_type(FIRST, "CustomState", 5177360)
    task.objects[FIRST].update(name="", path="[Fight (Custom)]", **{"@Volume": 0.0})
    task.metadata = {"Volume": {"name": "Volume", "type": "Real32",
        "restriction": {"type": "range", "min": -96.3, "max": 12}}}
    target = task.bind(FIRST)
    field = task.discover(target, "Volume")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "-4")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert task.objects[FIRST]["@Volume"] == 0.0
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["@Volume"] == -4
    assert [args for uri, args, _ in task.calls if uri.endswith("setProperty")] == [
        {"object": FIRST, "property": "Volume", "value": -4}]
    assert all(uri != columns_uri for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation,token,native_name_present", [
    ("object.setProperty", "Volume", True), ("object.setProperty", "NativeProperty" + "x" * 600, True),
    ("object.setProperty", "声" * 300, True), ("object.setProperty", "NativeProperty" + "x" * 12000, True),
    ("object.setReference", "OutputBus", True),
    ("object.setProperty", "Volume", False), ("object.setReference", "OutputBus", False)],
    ids=["ordinary", "long-ascii", "long-utf8", "paged-token", "reference-clear", "property-name-absent", "reference-name-absent"])
@pytest.mark.parametrize("drift", [None, "restriction", "type", "default-null", "unit", "postwrite-default"])
def test_selected_field_reaches_preview_execution_and_verified_value(tmp_path: Path, version: str, operation: str, token: str, native_name_present: bool, drift: str | None) -> None:
    task = PropertyTask(tmp_path, version, operation)
    reference = operation == "object.setReference"
    before, after = ({"id": SECOND}, None) if reference else (0.0, -4)
    task.metadata = {token: {"name": token, "type": "Real32",
                                "display": {"name": "声量"},
                                "restriction": {"type": "range", "min": -96.3, "max": 12}}}
    if reference:
        task.metadata[token].update(type="Reference", restriction={"type": "reference", "restrictions": [{"type": ["Bus"]}]})
    if not native_name_present:
        task.metadata[token].pop("name")
    task.objects[FIRST].update({"name": "Alarm", "type": "Sound", "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Alarm", "@" + token: before})
    target = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", target, "--list")
    assert code == 0, listed
    code, detail = task.step("draft-discover-fields", "--object-handle", target,
                             "--selection", listed["agent_result"]["fields"][0]["selection"])
    assert code == 0, detail
    assert ("name" in detail["field_candidates"][0]["metadata"]) is native_name_present
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", detail["field_candidates"][0]["handle"],
                              *(["--clear-reference"] if reference else ["--business-value", "-4"]))
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, json.dumps(checked)
    code, preview = task.step("preview-from-draft")
    assert code == 0, json.dumps(preview)
    assert task.objects[FIRST]["@" + token] == before
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, json.dumps(shown)
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, json.dumps(confirmed)
    if drift == "restriction":
        task.metadata[token]["restriction"] = ({"type": "reference", "restrictions": [{"type": ["Sound"]}]}
                                                 if reference else {"type": "range", "min": -96.3, "max": 0})
    elif drift == "type":
        task.metadata[token]["type"] = "Real64"
    elif drift == "default-null":
        task.metadata[token]["default"] = None
    elif drift == "unit":
        task.metadata[token]["ui"] = {"dataMeaning": "Frequency"}
    code, executed = task.run("execute", tx)
    if drift and drift != "postwrite-default":
        assert code == 2, executed
        assert task.objects[FIRST]["@" + token] == before
        assert not any(uri.endswith(("setProperty", "setReference")) for uri, _, _ in task.calls)
        return
    assert code == 0, json.dumps(executed)
    if drift == "postwrite-default":
        task.metadata[token]["default"] = None
    code, verified = task.run("verify", tx)
    if drift == "postwrite-default":
        assert code == 2 and verified["verified"] is False, verified
        assert sum(uri.endswith(("setProperty", "setReference")) for uri, _, _ in task.calls) == 1
        return
    assert code == 0, json.dumps(verified)
    assert verified["verified"] is True
    assert task.objects[FIRST]["@" + token] == after
    assert [args for uri, args, _ in task.calls if uri.endswith(("setProperty", "setReference"))] == [
        {"object": FIRST, "reference" if reference else "property": token,
         "value": "{00000000-0000-0000-0000-000000000000}" if reference else -4}]
    assert all(args["property"] == token for uri, args, _ in task.calls if uri.endswith("getPropertyInfo"))
    assert any(token in options.get("return", []) for uri, _, options in task.calls
               if uri.endswith("object.get") and options)
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
@pytest.mark.parametrize("native_name_present", [True, False])
def test_selected_field_without_native_type_rejects_handle_acquisition(tmp_path: Path, version: str, native_name_present: bool) -> None:
    task = FieldTask(tmp_path, version, "object.setProperty")
    task.metadata = {"Mode": {"name": "Mode", "default": 0}}
    if not native_name_present:
        task.metadata["Mode"].pop("name")
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


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("native_name_present", [True, False])
def test_exact_draft_selection_reports_unavailable_scalar_type_without_claiming_bad_metadata(tmp_path, version, native_name_present):
    task = FieldTask(tmp_path, version, "object.setProperty")
    target = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", target, "--list")
    assert code == 0, listed
    selection = listed["agent_result"]["fields"][0]["selection"]
    task.metadata["FadeTime"].pop("type")
    if not native_name_present:
        task.metadata["FadeTime"].pop("name")
    revision = task.revision
    code, rejected = task.step("draft-discover-fields", "--object-handle", target, "--selection", selection)
    assert code == 2, rejected
    issue = rejected["details"]["rejected_candidates"][0]
    assert issue["error_code"] == "FIELD_TYPE_UNAVAILABLE", rejected
    assert issue["field"] == "FadeTime"
    assert issue["unavailable_facts"] == ["type"]
    assert rejected["details"]["draft_changed"] is False
    assert task.revision == revision
    assert not any(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ["object.setProperty", "object.setReference"])
@pytest.mark.parametrize("issue,error_code", [
    ("null", "INVALID_LIVE_METADATA"), ("wrong-name", "LIVE_METADATA_NAME_MISMATCH"),
    ("removed-from-inventory", "METADATA_SELECTION_SCOPE_CHANGED"),
    ("removed-during-read", "METADATA_SELECTION_SCOPE_CHANGED")])
def test_selected_field_never_replaces_missing_name_proof_with_null_or_unrelated_metadata(tmp_path, version, operation, issue, error_code):
    class DropFieldAfterRead(PropertyTask):
        def call(self, uri, args=None, options=None):
            result = super().call(uri, args, options)
            if uri.endswith("getPropertyInfo"):
                self.metadata.pop("Volume", None)
            return result
    task = (DropFieldAfterRead if issue == "removed-during-read" else PropertyTask)(tmp_path, version, operation)
    task.metadata = {"Volume": {"name": "Volume", "type": "Real32"},
                     "Unrelated": {"name": "Unrelated", "type": "Real32"}}
    if operation == "object.setReference":
        task.metadata["Volume"].update(type="Reference", restriction={"type": "reference", "restrictions": [{"type": ["Bus"]}]})
    target = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", target, "--list")
    assert code == 0, listed
    selection = next(row["selection"] for row in listed["agent_result"]["fields"] if row["name"] == "Volume")
    revision, before = task.revision, len(task.calls)
    if issue == "removed-from-inventory":
        task.metadata.pop("Volume")
    elif issue != "removed-during-read":
        task.metadata["Volume"]["name"] = None if issue == "null" else "Unrelated"
    code, rejected = task.step("draft-discover-fields", "--object-handle", target, "--selection", selection)
    assert code == 2 and rejected["error_code"] == error_code, rejected
    assert task.revision == revision
    reads = [args for uri, args, _ in task.calls[before:] if uri.endswith("getPropertyInfo")]
    assert reads == ([] if issue == "removed-from-inventory" else [{"object": FIRST, "property": "Volume"}])
    assert not any(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls)
