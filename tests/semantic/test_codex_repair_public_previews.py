from copy import deepcopy
from pathlib import Path
from tests.semantic.support.codex_repair_cases import approve_f3_preview, approve_f4_preview


def test_gameparameter_preview_from_public_gateway_matches_independent_repair_scope(tmp_path):
    from tests.unit.test_gameparameter_class_fields_gateway import NativeParameterTask, FIRST
    task = NativeParameterTask(tmp_path, "2025.1")
    task.declare_complete_parameter()
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    code, shown = task.run("transaction-show", preview["transaction_id"])
    assert code == 0, shown
    expected = {"name": "WeatherIntensity"}
    assert approve_f3_preview(shown["artifact"], parent_id=FIRST, expected=expected)
    wrong = deepcopy(shown["artifact"])
    wrong["prepared_operation"]["dispatch"]["args"]["@InitialValue"] = 8
    assert not approve_f3_preview(wrong, parent_id=FIRST, expected=expected)


def test_shareset_preview_from_public_gateway_cannot_attach_an_owner_or_extra_property(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "unit"))
    from tests.unit.test_plugin_shareset_gateway import declare_plugin, ShareSetClient, PARENT, CLASS_ID
    code, declared, step, env = declare_plugin(tmp_path, "2025.1", ShareSetClient("2025.1"))
    assert code == 0, declared
    code, checked = step("draft-check")
    assert code == 0, checked
    code, preview = step("preview-from-draft")
    assert code == 0, preview
    from tests.unit.test_plugin_shareset_gateway import gateway
    code, shown = gateway.execute_gateway(["transaction-show", preview["transaction_id"]], env=env)
    assert code == 0, shown
    expected = {"name": "Room", "class_id": CLASS_ID}
    assert approve_f4_preview(shown["artifact"], parent_id=PARENT, expected=expected)
    wrong = deepcopy(shown["artifact"])
    wrong["prepared_operation"]["dispatch"]["args"]["objects"][0]["children"][0]["@RoomSize"] = 1
    assert not approve_f4_preview(wrong, parent_id=PARENT, expected=expected)
