from __future__ import annotations

import dataclasses
import re
import uuid
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping

import pytest

from tests.semantic.support.codex_integration_alarm_runtime_v1 import (
    ACTOR_LAB,
    ALARM_ACTOR_ROOT,
    ALARM_EVENT_PATH,
    ALARM_EVENT_ROOT,
    ALARM_SOUND_PATH,
    DEAD_BUS_PATH,
    DECOY_BUS_PATHS,
    DECOY_EVENT_PATHS,
    DECOY_SOUND_PATHS,
    TARGET_BUS_PATH,
    AlarmIntegrationRuntimeError,
    alarm_fixture_paths,
    prepare_alarm_integration_runtime,
)
from tests.semantic.support.codex_integration_workflows_v1 import (
    load_integration_workflows_profile,
)
from tests.semantic.support.codex_gateway_broker import (
    ExactArgumentAlternatives,
    ResponseBinding,
    ResponseBindingOrExactArgument,
)


DATA_ROOT = (
    Path(__file__).resolve().parent
    / "data"
    / "integration-workflows-v1"
)
ACTOR_DWU = r"\Actor-Mixer Hierarchy\Default Work Unit"
EVENT_DWU = r"\Events\Default Work Unit"
MASTER_BUS = r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"
_TYPED_SOUND = re.compile(r"^(.*)\\<Sound SFX>([^\\]+)$")


def _guid(label: str) -> str:
    return "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"alarm:{label}")).upper() + "}"


class FakeAlarmWaapi:
    def __init__(self, version: str = "2022.1") -> None:
        self.version = version
        self.fixture_paths = alarm_fixture_paths(version)
        self.rows: dict[str, dict[str, Any]] = {}
        self.path_to_id: dict[str, str] = {}
        self.calls: list[
            tuple[str, dict[str, Any], dict[str, Any]]
        ] = []
        self.save_count = 0
        self.action_type = 1
        self.refuse_delete = False
        self.malformed_create_name: str | None = None
        self._insert_root(
            self.fixture_paths.actor_dwu,
            "Default Work Unit",
            "WorkUnit",
        )
        self._insert_root(
            self.fixture_paths.event_dwu,
            "Default Work Unit",
            "WorkUnit",
        )
        self._insert_root(
            self.fixture_paths.master_bus,
            self.fixture_paths.master_bus.rsplit("\\", 1)[-1],
            "Bus",
            volume=0.0,
        )

    def _insert_root(
        self,
        path: str,
        name: str,
        object_type: str,
        *,
        volume: float | None = None,
    ) -> str:
        object_id = _guid(path)
        row = {
            "id": object_id,
            "name": name,
            "type": object_type,
            "path": path,
            "parent": None,
            "shortId": len(self.rows) + 100,
            "notes": "",
        }
        if volume is not None:
            row["@Volume"] = volume
        self.rows[object_id.casefold()] = row
        self.path_to_id[path.casefold()] = object_id
        return object_id

    def _insert(
        self,
        *,
        parent_path: str,
        name: str,
        object_type: str,
    ) -> str:
        parent_id = self.path_to_id.get(parent_path.casefold())
        assert parent_id is not None
        path = f"{parent_path}\\{name}"
        if path.casefold() in self.path_to_id:
            raise AssertionError(f"duplicate fake path: {path}")
        object_id = _guid(path)
        self.rows[object_id.casefold()] = {
            "id": object_id,
            "name": name,
            "type": object_type,
            "path": path,
            "parent": {"id": parent_id},
            "shortId": len(self.rows) + 100,
            "notes": "",
        }
        self.path_to_id[path.casefold()] = object_id
        return object_id

    def call(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Any:
        self.calls.append((uri, dict(args), dict(options)))
        if uri == "ak.wwise.core.object.get":
            return self._get(args, options)
        if uri == "ak.wwise.core.object.create":
            parent = str(args["parent"])
            object_type = str(args["type"])
            if object_type == "ActorMixer" and self.version == "2025.1":
                object_type = "PropertyContainer"
            object_id = self._insert(
                parent_path=parent,
                name=str(args["name"]),
                object_type=object_type,
            )
            if args["name"] == self.malformed_create_name:
                return {"id": "not-a-guid"}
            return {"id": object_id}
        if uri == "ak.wwise.core.audio.import":
            return self._import(args)
        if uri == "ak.wwise.core.object.setProperty":
            row = self.rows[str(args["object"]).casefold()]
            property_name = str(args["property"])
            value = args["value"]
            if property_name == "OverrideOutput":
                row["OverrideOutput"] = value
                row["@OverrideOutput"] = value
            else:
                row[f"@{property_name}"] = value
            return {}
        if uri == "ak.wwise.core.object.setReference":
            row = self.rows[str(args["object"]).casefold()]
            target = args.get("value", args.get("target"))
            if isinstance(target, Mapping):
                target = target.get("value", target.get("id"))
            row[str(args["reference"])] = {"id": str(target)}
            return {}
        if uri == "ak.wwise.core.object.delete":
            if self.refuse_delete:
                raise RuntimeError("delete refused")
            self._delete(str(args["object"]))
            return {}
        if uri == "ak.wwise.core.project.save":
            self.save_count += 1
            return {}
        raise AssertionError(f"unexpected fake WAAPI URI: {uri}")

    def _get(
        self,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> dict[str, Any]:
        source = args.get("from")
        assert isinstance(source, Mapping)
        if "path" in source:
            paths = source["path"]
            assert isinstance(paths, list) and len(paths) == 1
            object_id = self.path_to_id.get(str(paths[0]).casefold())
            values = [] if object_id is None else [self.rows[object_id.casefold()]]
        else:
            ids = source["id"]
            assert isinstance(ids, list) and len(ids) == 1
            row = self.rows.get(str(ids[0]).casefold())
            values = [] if row is None else [row]
        if args.get("transform") == [{"select": ["children"]}]:
            if len(values) != 1:
                values = []
            else:
                parent_id = str(values[0]["id"]).casefold()
                values = [
                    row
                    for row in self.rows.values()
                    if isinstance(row.get("parent"), Mapping)
                    and str(row["parent"].get("id")).casefold() == parent_id
                ]
        fields = options.get("return")
        assert isinstance(fields, list)
        return {
            "return": [
                {field: self._copy_value(row.get(field)) for field in fields}
                for row in values
            ]
        }

    @staticmethod
    def _copy_value(value: Any) -> Any:
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, list):
            return list(value)
        return value

    def _import(self, args: Mapping[str, Any]) -> dict[str, Any]:
        imports = args["imports"]
        assert isinstance(imports, list) and len(imports) == 1
        item = imports[0]
        match = _TYPED_SOUND.fullmatch(str(item["objectPath"]))
        assert match is not None
        sound_parent, sound_name = match.groups()
        event_path, action = str(item["event"]).rsplit("@", 1)
        assert action == "Play"
        event_parent, _, event_name = event_path.rpartition("\\")

        sound_id = self._insert(
            parent_path=sound_parent,
            name=sound_name,
            object_type="Sound SFX",
        )
        source_name = Path(str(item["audioFile"])).stem
        source_id = self._insert(
            parent_path=f"{sound_parent}\\{sound_name}",
            name=source_name,
            object_type="AudioFileSource",
        )
        source = self.rows[source_id.casefold()]
        source["originalFilePath"] = str(item["audioFile"])
        source["audioSource:language"] = {"name": "SFX"}
        sound = self.rows[sound_id.casefold()]
        sound.update(
            {
                "@Volume": 0.0,
                "@Pitch": 0.0,
                "OverrideOutput": False,
                "@OverrideOutput": False,
                "@UseMaxSoundPerInstance": False,
                "@MaxSoundPerInstance": 50,
                "OutputBus": None,
                "activeSource": {"id": source_id},
            }
        )

        event_id = self._insert(
            parent_path=event_parent,
            name=event_name,
            object_type="Event",
        )
        action_id = self._insert(
            parent_path=event_path,
            name=f"[Play - {sound_name}]",
            object_type="Action",
        )
        action_row = self.rows[action_id.casefold()]
        # Real Wwise Action rows use an empty `name`; their descriptive
        # identity lives in `path`, `ActionType`, and `Target`.
        action_row["name"] = ""
        action_row["ActionType"] = self.action_type
        action_row["Target"] = {"id": sound_id}
        return {
            "objects": [
                {"id": sound_id},
                {"id": source_id},
                {"id": event_id},
                {"id": action_id},
            ]
        }

    def _delete(self, object_id: str) -> None:
        key = object_id.casefold()
        row = self.rows.get(key)
        if row is None:
            raise RuntimeError("missing delete identity")
        descendants = [
            candidate["id"]
            for candidate in self.rows.values()
            if isinstance(candidate.get("parent"), Mapping)
            and str(candidate["parent"].get("id")).casefold() == key
        ]
        for child_id in descendants:
            self._delete(str(child_id))
        self.path_to_id.pop(str(row["path"]).casefold(), None)
        self.rows.pop(key)

    def raw_row(self, path: str) -> dict[str, Any]:
        object_id = self.path_to_id[path.casefold()]
        return self.rows[object_id.casefold()]

    def set_output_bus(self, sound_path: str, bus_path: str) -> None:
        sound_id = self.path_to_id[sound_path.casefold()]
        bus_id = self.path_to_id[bus_path.casefold()]
        self.call(
            "ak.wwise.core.object.setReference",
            {
                "object": sound_id,
                "reference": "OutputBus",
                "value": bus_id,
            },
            {},
        )


def _unit(version: str = "2022.1"):
    profile = load_integration_workflows_profile(DATA_ROOT / "profile.json")
    return next(
        unit
        for unit in profile.units
        if unit.workflow_id == "alarm_diagnose_and_repair"
        and unit.version == version
    )


def _paths(tmp_path: Path) -> SimpleNamespace:
    scenario_root = tmp_path / "scenario"
    asset_root = scenario_root / "assets"
    io_root = scenario_root / "io"
    asset_root.mkdir(parents=True)
    io_root.mkdir()
    return SimpleNamespace(
        scenario_root=scenario_root,
        asset_root=asset_root,
        io_root=io_root,
    )


def _prepared(tmp_path: Path, *, version: str = "2022.1"):
    unit = _unit(version)
    fake = FakeAlarmWaapi(version)
    prepared = prepare_alarm_integration_runtime(
        unit.workflow,
        unit.scenario,
        version=version,
        paths=_paths(tmp_path),
        direct_call=fake.call,
    )
    return prepared, fake


def _payload_row(state: Any) -> dict[str, Any]:
    details = state.details
    row = {
        "id": state.object_id,
        "name": state.name,
        "type": state.object_type,
        "path": state.path,
        "parent": (
            None if state.parent_id is None else {"id": state.parent_id}
        ),
        "shortId": details["short_id"],
        "notes": details["notes"],
    }
    if state.key == "sound":
        row.update(
            {
                "@Volume": details["volume"],
                "@Pitch": details["pitch"],
                "OverrideOutput": details["override_output"],
                "@UseMaxSoundPerInstance": (
                    details["use_max_sound_per_instance"]
                ),
                "@MaxSoundPerInstance": details["max_sound_per_instance"],
                "OutputBus": {"id": details["output_bus_id"]},
                "activeSource": {"id": details["active_source_id"]},
            }
        )
    elif state.key in {"dead_bus", "target_bus"}:
        row["@Volume"] = details["volume"]
    elif state.key == "action":
        row.update(
            {
                "ActionType": details["action_type"],
                "Target": {"id": details["target_id"]},
            }
        )
    elif state.key == "source":
        row.update(
            {
                "originalFilePath": details["original_file_path"],
                "audioSource:language": {"name": details["language"]},
            }
        )
    return row


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_prepare_builds_exact_alarm_chain_and_frozen_runner_seam(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, _fake = _prepared(tmp_path, version=version)
    rows = prepared.before_snapshot.by_key()
    fixture_paths = alarm_fixture_paths(version)

    assert prepared.workflow_id == "alarm_diagnose_and_repair"
    assert prepared.version == version
    assert prepared.visible_values == {
        "alarm_event_path": fixture_paths.event,
        "alarm_target_bus_path": fixture_paths.target_bus,
    }
    assert rows["event"].name == "Play_Generator_Alarm"
    assert rows["action"].details["action_type"] == 1
    assert rows["action"].details["target_id"] == rows["sound"].object_id
    assert rows["sound"].name == "Generator_Alarm"
    assert rows["sound"].details["volume"] == 0.0
    assert rows["sound"].details["override_output"] is True
    assert rows["sound"].details["output_bus_id"] == rows["dead_bus"].object_id
    assert rows["source"].object_type == "AudioFileSource"
    assert rows["source"].parent_id == rows["sound"].object_id
    assert rows["dead_bus"].details["volume"] == -96.0
    assert rows["target_bus"].details["volume"] == 0.0
    assert len([key for key in rows if key.startswith("decoy_")]) == 10
    assert isinstance(prepared.visible_values, MappingProxyType)
    assert isinstance(rows["sound"].details, MappingProxyType)
    assert "direct_call" not in {field.name for field in dataclasses.fields(prepared)}
    assert "backend" not in {field.name for field in dataclasses.fields(prepared)}


def test_protocol_exposes_six_exact_chain_reads_then_one_standard_transaction(
    tmp_path: Path,
) -> None:
    prepared, _fake = _prepared(tmp_path)
    protocol = prepared.protocol

    assert protocol.turn_prefix_counts == (6, 14, 18)
    assert tuple(step.name for step in protocol.steps[:6]) == (
        "diag.event",
        "diag.action",
        "diag.sound",
        "diag.source",
        "diag.dead_bus",
        "diag.target_bus",
    )
    assert protocol.commutative_read_only_step_groups == (
        ("diag.source", "diag.dead_bus", "diag.target_bus"),
    )
    assert {step.subcommand for step in protocol.steps[:6]} == {"query-object"}
    assert "--take" not in protocol.steps[0].arguments
    assert "--take" in protocol.steps[1].arguments
    assert all(
        "--take" not in step.arguments
        for step in protocol.steps[2:6]
    )
    assert protocol.steps[1].arguments[1] == ResponseBindingOrExactArgument(
        binding=ResponseBinding("diag.event", "/objects/0/id"),
        exact_values=(alarm_fixture_paths("2022.1").event,),
    )
    assert protocol.steps[1].arguments[0] == ExactArgumentAlternatives(
        ("--object-id", "--path")
    )
    assert protocol.steps[2].arguments[1] == ResponseBinding(
        "diag.action",
        "/objects/0/target/id",
    )
    assert protocol.steps[3].arguments[1] == ResponseBinding(
        "diag.sound",
        "/objects/0/activeSource/id",
    )
    assert protocol.steps[4].arguments[1] == ResponseBinding(
        "diag.sound",
        "/objects/0/OutputBus/id",
    )
    sound_fields = protocol.steps[2].arguments[3::2]
    dead_bus_fields = protocol.steps[4].arguments[3::2]
    target_bus_fields = protocol.steps[5].arguments[3::2]
    assert sound_fields == (
        "id",
        "name",
        "type",
        "path",
        "OverrideOutput",
        "activeSource",
        "OutputBus",
    )
    assert "@Volume" not in sound_fields
    assert dead_bus_fields == target_bus_fields == (
        "id",
        "name",
        "type",
        "path",
        "@Volume",
    )
    assert tuple(step.subcommand for step in protocol.steps[6:]) == (
        "operation-schema",
        "draft-start",
        "draft-bind-object",
        "draft-discover-fields",
        "draft-bind-object",
        "draft-declare-field-change",
        "draft-check",
        "preview-from-draft",
        "transaction-show",
        "confirm",
        "execute",
        "verify",
    )
    discovery = protocol.steps[9]
    sound_id = prepared.before_snapshot.by_key()["sound"].object_id
    source_binding = protocol.steps[8]
    assert source_binding.arguments[-2:] == ("--object-id", sound_id)
    assert "--meaning" in discovery.arguments
    assert discovery.arguments[discovery.arguments.index("--meaning") + 1] == "output bus"
    assert "--token" not in discovery.arguments
    target_id = prepared.before_snapshot.by_key()["target_bus"].object_id
    target_binding = protocol.steps[10]
    assert target_binding.arguments[-2:] == ("--object-id", target_id)
    preview = protocol.steps[13]
    assert preview.expected_operation_request == prepared.operation_request
    assert [row.api for row in prepared.expected_dispatches] == [
        "ak.wwise.core.object.setReference",
    ]
    assert [row.count for row in prepared.expected_dispatches] == [1]
    assert len(prepared.oracle_requirements) == 9


def test_operation_request_is_bound_to_live_sound_and_target_bus_ids(
    tmp_path: Path,
) -> None:
    prepared, _fake = _prepared(tmp_path)
    rows = prepared.before_snapshot.by_key()
    request = prepared.operation_request

    assert request["contract"] == "waapi-skill.operation-request/v1"
    assert request["operation"] == "object.setReference"
    assert request["arguments"]["object"] == {
        "kind": "id",
        "value": rows["sound"].object_id,
    }
    assert request["arguments"]["reference"] == "OutputBus"
    assert request["arguments"]["target"] == {
        "kind": "id",
        "value": rows["target_bus"].object_id,
    }
    preview_step = next(
        step for step in prepared.protocol.steps if step.name == "tx01.preview"
    )
    assert preview_step.expected_operation_request == request
    with pytest.raises(TypeError):
        request["arguments"]["reference"] = "Attenuation"  # type: ignore[index]


def test_diagnostic_payload_observer_seals_exact_chain_evidence(
    tmp_path: Path,
) -> None:
    prepared, _fake = _prepared(tmp_path)
    rows = prepared.before_snapshot.by_key()
    key_by_step = {
        "diag.event": "event",
        "diag.action": "action",
        "diag.sound": "sound",
        "diag.source": "source",
        "diag.dead_bus": "dead_bus",
        "diag.target_bus": "target_bus",
    }
    for step in prepared.protocol.steps[:6]:
        row = _payload_row(rows[key_by_step[step.name]])
        prepared.observe_payload(
            step,
            {
                "ok": True,
                "command": "query-object",
                "count": 1,
                "objects": [row],
            },
        )


def test_diagnostic_action_observer_accepts_gateway_business_projection(
    tmp_path: Path,
) -> None:
    prepared, _fake = _prepared(tmp_path)
    action = dict(_payload_row(prepared.before_snapshot.by_key()["action"]))
    action["action_type"] = action.pop("ActionType")
    action["target"] = action.pop("Target")

    prepared.observe_payload(
        prepared.protocol.steps[1],
        {
            "ok": True,
            "command": "query-object",
            "count": 1,
            "objects": [action],
        },
    )


def test_diagnostic_payload_observer_rejects_wrong_chain_identity(
    tmp_path: Path,
) -> None:
    prepared, _fake = _prepared(tmp_path)
    rows = prepared.before_snapshot.by_key()
    wrong_sound = _payload_row(rows["decoy_sound_1"])

    with pytest.raises(
        AlarmIntegrationRuntimeError,
        match="sealed sound evidence",
    ):
        prepared.observe_payload(
            prepared.protocol.steps[2],
            {
                "ok": True,
                "command": "query-object",
                "count": 1,
                "objects": [wrong_sound],
            },
        )


def test_diagnosis_and_preview_turns_prove_zero_project_delta(
    tmp_path: Path,
) -> None:
    prepared, _fake = _prepared(tmp_path)

    diagnosis = prepared.verify_turn(1)
    preview = prepared.verify_turn(2)

    diagnosis.assert_passed()
    preview.assert_passed()
    assert diagnosis.after == diagnosis.before == prepared.before_snapshot
    assert preview.after == preview.before == prepared.before_snapshot
    assert prepared.snapshot() == prepared.before_snapshot
    assert diagnosis.changed_fields == ()
    assert preview.changed_fields == ()


def test_final_verifier_accepts_only_the_output_bus_repair(
    tmp_path: Path,
) -> None:
    prepared, fake = _prepared(tmp_path)
    fake.set_output_bus(ALARM_SOUND_PATH, TARGET_BUS_PATH)

    verification = prepared.verify_final(None, None)

    verification.assert_passed()
    assert verification.changed_fields == ("sound.details.output_bus_id",)
    assert verification.after is not None
    assert (
        verification.after.by_key()["sound"].details["output_bus_id"]
        == prepared.before_snapshot.by_key()["target_bus"].object_id
    )


@pytest.mark.parametrize(
    ("path", "field", "value", "failure"),
    [
        (ALARM_SOUND_PATH, "@Volume", -3.0, "non-OutputBus"),
        (DEAD_BUS_PATH, "@Volume", -95.0, "dead_bus"),
        (DECOY_SOUND_PATHS[0], "@Pitch", 9.0, "decoy_sound_1"),
        (ALARM_EVENT_PATH, "notes", "changed", "event"),
    ],
)
def test_final_verifier_rejects_property_control_and_decoy_drift(
    tmp_path: Path,
    path: str,
    field: str,
    value: Any,
    failure: str,
) -> None:
    prepared, fake = _prepared(tmp_path)
    fake.set_output_bus(ALARM_SOUND_PATH, TARGET_BUS_PATH)
    fake.raw_row(path)[field] = value

    verification = prepared.verify_final(None, None)

    assert not verification.passed
    assert any(failure in item for item in verification.failures)


def test_final_verifier_rejects_missing_repair(tmp_path: Path) -> None:
    prepared, _fake = _prepared(tmp_path)

    verification = prepared.verify_final(None, None)

    assert not verification.passed
    assert any(
        "OutputBus is not SFX_Machinery" in item
        for item in verification.failures
    )


def test_first_turn_verifier_detects_an_illicit_early_mutation(
    tmp_path: Path,
) -> None:
    prepared, fake = _prepared(tmp_path)
    fake.set_output_bus(ALARM_SOUND_PATH, TARGET_BUS_PATH)

    verification = prepared.verify_turn(1)

    assert not verification.passed
    assert verification.changed_fields == ("sound.details.output_bus_id",)


def test_final_verifier_rejects_action_target_drift(tmp_path: Path) -> None:
    prepared, fake = _prepared(tmp_path)
    fake.set_output_bus(ALARM_SOUND_PATH, TARGET_BUS_PATH)
    action = fake.raw_row(
        ALARM_EVENT_PATH + r"\[Play - Generator_Alarm]"
    )
    action["Target"] = {
        "id": fake.path_to_id[DECOY_SOUND_PATHS[0].casefold()]
    }

    verification = prepared.verify_final(None, None)

    assert not verification.passed
    assert "action: protected object changed" in verification.failures


def test_cleanup_removes_owned_wwise_and_local_state_and_is_idempotent(
    tmp_path: Path,
) -> None:
    prepared, fake = _prepared(tmp_path)

    proof = prepared.cleanup()
    second = prepared.cleanup()

    proof.assert_passed()
    assert proof.already_clean is False
    assert proof.remaining_paths == ()
    assert second.passed is True and second.already_clean is True
    for path in (
        ACTOR_LAB,
        ALARM_ACTOR_ROOT,
        ALARM_EVENT_ROOT,
        ALARM_SOUND_PATH,
        ALARM_EVENT_PATH,
        *DECOY_SOUND_PATHS,
        *DECOY_EVENT_PATHS,
        DEAD_BUS_PATH,
        TARGET_BUS_PATH,
        *DECOY_BUS_PATHS,
    ):
        assert path.casefold() not in fake.path_to_id
    assert not (tmp_path / "scenario" / "assets" / "alarm-fixture").exists()


def test_cleanup_reports_delete_failure_and_remaining_owned_state(
    tmp_path: Path,
) -> None:
    prepared, fake = _prepared(tmp_path)
    fake.refuse_delete = True

    proof = prepared.cleanup()

    assert not proof.passed
    assert proof.failures
    assert proof.remaining_paths


def test_prepare_fails_closed_on_malformed_play_action_and_rolls_back(
    tmp_path: Path,
) -> None:
    unit = _unit()
    fake = FakeAlarmWaapi()
    fake.action_type = 2

    with pytest.raises(
        AlarmIntegrationRuntimeError,
        match="Play Action",
    ):
        prepare_alarm_integration_runtime(
            unit.workflow,
            unit.scenario,
            version=unit.version,
            paths=_paths(tmp_path),
            direct_call=fake.call,
        )

    assert ACTOR_LAB.casefold() not in fake.path_to_id
    assert ALARM_EVENT_ROOT.casefold() not in fake.path_to_id
    assert DEAD_BUS_PATH.casefold() not in fake.path_to_id


def test_prepare_recovers_object_created_before_malformed_create_reply(
    tmp_path: Path,
) -> None:
    unit = _unit()
    fake = FakeAlarmWaapi()
    fake.malformed_create_name = "IntegrationLab"

    with pytest.raises(
        AlarmIntegrationRuntimeError,
        match="created object id",
    ):
        prepare_alarm_integration_runtime(
            unit.workflow,
            unit.scenario,
            version=unit.version,
            paths=_paths(tmp_path),
            direct_call=fake.call,
        )

    assert ACTOR_LAB.casefold() not in fake.path_to_id


def test_prepare_surfaces_cleanup_failure_after_malformed_create_reply(
    tmp_path: Path,
) -> None:
    unit = _unit()
    fake = FakeAlarmWaapi()
    fake.malformed_create_name = "IntegrationLab"
    fake.refuse_delete = True

    with pytest.raises(
        AlarmIntegrationRuntimeError,
        match="cleanup was incomplete",
    ):
        prepare_alarm_integration_runtime(
            unit.workflow,
            unit.scenario,
            version=unit.version,
            paths=_paths(tmp_path),
            direct_call=fake.call,
        )

    assert ACTOR_LAB.casefold() in fake.path_to_id


def test_prepare_rejects_preexisting_owned_identity(tmp_path: Path) -> None:
    unit = _unit()
    fake = FakeAlarmWaapi()
    fake._insert(
        parent_path=ACTOR_DWU,
        name="IntegrationLab",
        object_type="Folder",
    )

    with pytest.raises(
        AlarmIntegrationRuntimeError,
        match="already exists",
    ):
        prepare_alarm_integration_runtime(
            unit.workflow,
            unit.scenario,
            version=unit.version,
            paths=_paths(tmp_path),
            direct_call=fake.call,
        )


def test_prepare_rejects_wrong_version_workflow_and_path_escape(
    tmp_path: Path,
) -> None:
    unit = _unit()
    fake = FakeAlarmWaapi()
    paths = _paths(tmp_path)

    with pytest.raises(AlarmIntegrationRuntimeError, match="unsupported"):
        prepare_alarm_integration_runtime(
            unit.workflow,
            unit.scenario,
            version="2024.1",
            paths=paths,
            direct_call=fake.call,
        )

    escaped = SimpleNamespace(
        scenario_root=paths.scenario_root,
        asset_root=tmp_path / "outside-assets",
        io_root=paths.io_root,
    )
    escaped.asset_root.mkdir()
    with pytest.raises(AlarmIntegrationRuntimeError, match="strict descendant"):
        prepare_alarm_integration_runtime(
            unit.workflow,
            unit.scenario,
            version=unit.version,
            paths=escaped,
            direct_call=fake.call,
        )
