from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic.support.codex_campaign import CampaignEvidenceError
from tests.semantic.support import codex_heavy_project_runner_v3 as project_runner
from tests.semantic.support.codex_campaign import (
    canonical_json_bytes,
)
from tests.semantic.support.codex_integration_fixture_tree_v2 import (
    wwise_fixture_tree_sha256,
)
from tests.semantic.support.codex_gateway_broker import (
    DraftActionJsonArgument,
    CodexGatewayBroker,
    GatewayInvocationError,
    SemanticJsonArgument,
)
from tests.semantic.support.codex_integration_footsteps_runtime_v2 import (
    FOOTSTEPS_CANONICAL_STATE_FIELDS,
    GET_ASSIGNMENTS_API,
    IMPORT_API,
    OBJECT_GET_API,
    REMOVE_ASSIGNMENT_API,
    FootstepsIntegrationRuntimeError,
    prepare_footsteps_integration_runtime,
)
from tests.semantic.support.codex_integration_workflows_v2 import (
    BaselineManifest,
    load_integration_workflows_v2_profile,
)


DATA_ROOT = Path(__file__).resolve().parent / "data" / "integration-workflows-v2"
PROFILE_PATH = DATA_ROOT / "profile.json"


def _guid(label: str) -> str:
    return "{" + str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"footsteps-v2:{label}")
    ).upper() + "}"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


class FakeFootstepsWaapi:
    """Read-only direct backend with explicit test-owned mutation simulators."""

    def __init__(
        self,
        workflow: Any,
        *,
        version: str,
        sandbox_root: Path,
    ) -> None:
        self.workflow = workflow
        self.version = version
        self.sandbox_root = sandbox_root
        self.specs = {row.role: row for row in workflow.fixture.object_graph}
        self.rows: dict[str, dict[str, Any]] = {}
        self.path_to_id: dict[str, str] = {}
        self.roles: dict[str, str] = {}
        self.source_roles: dict[str, str] = {}
        self.assignments: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.delete_calls = 0
        self._build_baseline()

    def _path(self, role: str) -> str:
        return self.specs[role].path_for(self.version)

    def _insert(
        self,
        role: str,
        *,
        object_type: str,
        parent_id: str,
        fields: Mapping[str, Any] = {},
        object_id: str | None = None,
    ) -> str:
        identity = object_id or _guid(role)
        path = self._path(role)
        row = {
            "id": identity,
            "name": path.rsplit("\\", 1)[-1],
            "type": object_type,
            "path": path,
            "parent": {"id": parent_id},
            **copy.deepcopy(dict(fields)),
        }
        self.rows[identity.casefold()] = row
        self.path_to_id[path.casefold()] = identity
        self.roles[role] = identity
        return identity

    def _insert_source(
        self,
        role: str,
        *,
        sound_id: str,
        content: bytes,
    ) -> str:
        source_id = _guid(f"{role}-source")
        media = self.sandbox_root / "Originals" / "SFX" / f"{role}.wav"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(content)
        sound_path = self._path(role)
        source_path = sound_path + f"\\{role}_source"
        self.rows[source_id.casefold()] = {
            "id": source_id,
            "name": f"{role}_source",
            "type": "AudioFileSource",
            "path": source_path,
            "parent": {"id": sound_id},
            "originalFilePath": str(media),
            "audioSource:language": {"name": "SFX"},
        }
        self.path_to_id[source_path.casefold()] = source_id
        self.source_roles[role] = source_id
        return source_id

    def _build_baseline(self) -> None:
        actor_parent = _guid("actor-parent")
        switch_parent = _guid("switch-parent")
        event_parent = _guid("event-parent")
        bus_parent = _guid(f"bus-parent-{self.version}")
        bus_id = self._insert(
            "footsteps_bus",
            object_type="Bus",
            parent_id=bus_parent,
            fields={"@Volume": -2.0},
        )
        group_id = self._insert(
            "surface_group",
            object_type="SwitchGroup",
            parent_id=switch_parent,
        )
        for role in (
            "surface_metal",
            "surface_wood",
            "surface_mud",
            "surface_snow",
        ):
            self._insert(role, object_type="Switch", parent_id=group_id)
        player_id = self._insert(
            "player_footsteps",
            object_type="SwitchContainer",
            parent_id=actor_parent,
            fields={
                "SwitchGroupOrStateGroup": {"id": group_id},
                "OutputBus": {"id": bus_id},
            },
        )
        for prefix in ("metal", "wood", "mud"):
            container_role = f"{prefix}_container"
            sound_role = f"{prefix}_sound"
            container_id = self._insert(
                container_role,
                object_type="RandomSequenceContainer",
                parent_id=player_id,
                fields={"OutputBus": {"id": bus_id}},
            )
            sound_id = self._insert(
                sound_role,
                object_type="Sound",
                parent_id=container_id,
                fields={"OutputBus": {"id": bus_id}},
            )
            source_id = self._insert_source(
                sound_role,
                sound_id=sound_id,
                content=f"old:{self.version}:{sound_role}".encode(),
            )
            self.rows[sound_id.casefold()]["activeSource"] = {
                "id": source_id
            }
        event_id = self._insert(
            "play_footsteps_event",
            object_type="Event",
            parent_id=event_parent,
        )
        action_id = self._insert(
            "play_footsteps_action",
            object_type="Action",
            parent_id=event_id,
            fields={"ActionType": 1, "Target": {"id": player_id}},
        )
        # Real Wwise Actions are nameless objects.  Their bracketed path is a
        # dynamic display path and is not a reliable from.path selector.
        self.rows[action_id.casefold()]["name"] = ""
        self.assignments = [
            {
                "child": {"id": self.roles[f"{prefix}_container"]},
                "stateOrSwitch": {"id": self.roles[f"surface_{prefix}"]},
            }
            for prefix in ("metal", "wood", "mud")
        ]

    def _children(self, owner_id: str) -> list[dict[str, Any]]:
        return [
            row
            for row in self.rows.values()
            if isinstance(row.get("parent"), Mapping)
            and str(row["parent"].get("id")).casefold()
            == owner_id.casefold()
        ]

    def _canonical_state(self, role: str) -> dict[str, Any]:
        row = self.rows[self.roles[role].casefold()]
        result: dict[str, Any] = {}
        for field in FOOTSTEPS_CANONICAL_STATE_FIELDS[role]:
            if field == "children":
                result[field] = [
                    {"id": child["id"]}
                    for child in sorted(
                        self._children(row["id"]),
                        key=lambda item: str(item["id"]).casefold(),
                    )
                ]
            elif field == "assignment_pairs":
                result[field] = sorted(
                    (
                        {
                            "child": item["child"]["id"],
                            "stateOrSwitch": item["stateOrSwitch"]["id"],
                        }
                        for item in self.assignments
                    ),
                    key=lambda item: (
                        item["child"].casefold(),
                        item["stateOrSwitch"].casefold(),
                    ),
                )
            else:
                result[field] = copy.deepcopy(row[field])
        return result

    def manifest(
        self,
        *,
        source_project: Path,
        source_root: Path,
    ) -> BaselineManifest:
        objects: list[Mapping[str, Any]] = []
        media: list[Mapping[str, str]] = []
        for role, spec in self.specs.items():
            if spec.baseline_state != "present":
                continue
            row = self.rows[self.roles[role].casefold()]
            state = self._canonical_state(role)
            objects.append(
                {
                    "role": role,
                    "id": row["id"],
                    "path": row["path"],
                    "type": row["type"],
                    "state": state,
                    "state_sha256": _digest(state),
                }
            )
            if spec.type == "Sound":
                source = self.rows[self.source_roles[role].casefold()]
                live_media = Path(source["originalFilePath"])
                relative = live_media.relative_to(self.sandbox_root)
                source_media = source_root / relative
                source_media.parent.mkdir(parents=True, exist_ok=True)
                source_media.write_bytes(live_media.read_bytes())
                media.append(
                    {
                        "role": role,
                        "active_source_id": source["id"],
                        "relative_path": relative.as_posix(),
                        "sha256": _sha256(source_media),
                    }
                )
        return BaselineManifest(
            path=source_root / "baseline.json",
            version=self.version,
            digest="0" * 64,
            project_file_sha256=_sha256(source_project),
            full_tree_sha256=wwise_fixture_tree_sha256(source_root),
            objects=tuple(objects),
            media=tuple(media),
        )

    def __call__(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Any:
        self.calls.append(
            (uri, copy.deepcopy(dict(args)), copy.deepcopy(dict(options)))
        )
        if uri == OBJECT_GET_API:
            return self._get(args, options)
        if uri == GET_ASSIGNMENTS_API:
            assert args == {"id": self.roles["player_footsteps"]}
            return {"return": copy.deepcopy(self.assignments)}
        if uri == "ak.wwise.core.object.delete":
            self.delete_calls += 1
        raise AssertionError(f"unexpected fake WAAPI URI: {uri}")

    def _get(
        self,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        source = args.get("from")
        assert isinstance(source, Mapping)
        values: list[dict[str, Any]] = []
        if "path" in source:
            requested = source["path"]
            assert isinstance(requested, list) and len(requested) == 1
            object_id = self.path_to_id.get(str(requested[0]).casefold())
            if (
                object_id is not None
                and self.rows[object_id.casefold()].get("type") != "Action"
            ):
                values = [self.rows[object_id.casefold()]]
        else:
            requested = source["id"]
            assert isinstance(requested, list)
            values = [
                self.rows[str(object_id).casefold()]
                for object_id in requested
                if str(object_id).casefold() in self.rows
            ]
        if args.get("transform") == [{"select": ["children"]}]:
            parent_ids = {str(row["id"]).casefold() for row in values}
            values = [
                row
                for row in self.rows.values()
                if isinstance(row.get("parent"), Mapping)
                and str(row["parent"].get("id")).casefold()
                in parent_ids
            ]
        fields = options.get("return")
        assert isinstance(fields, list)
        return {
            "return": [
                {
                    field: copy.deepcopy(row.get(field))
                    for field in fields
                }
                for row in values
            ]
        }

    def apply_import(self, request: Mapping[str, Any]) -> None:
        assert request["operation"] == "audio.import"
        imports = request["arguments"]["imports"]
        assert len(imports) == 5
        structure = imports[0]
        assert structure == {
            "object_path": self._path("snow_container"),
            "object_type": "RandomSequenceContainer",
            "switch_assignment": "Snow",
        }
        player_id = self.roles["player_footsteps"]
        bus_id = self.roles["footsteps_bus"]
        snow_id = self._insert(
            "snow_container",
            object_type="RandomSequenceContainer",
            parent_id=player_id,
            fields={"OutputBus": {"id": bus_id}},
            object_id=_guid("created-snow-container"),
        )
        for item, role in zip(imports[1:], (
            "snow_step_01",
            "snow_step_02",
            "snow_step_03",
            "snow_step_04",
        ), strict=True):
            assert item["object_path"] == self._path(role)
            assert item["object_type"] == "Sound SFX"
            assert item["import_language"] == "SFX"
            sound_id = self._insert(
                role,
                object_type="Sound",
                parent_id=snow_id,
                fields={"OutputBus": {"id": bus_id}},
                object_id=_guid(f"created-{role}"),
            )
            source_id = _guid(f"created-{role}-source")
            source_path = self._path(role) + f"\\{role}_source"
            copied = self.sandbox_root / "Originals" / "SFX" / Path(
                item["audio_file"]
            ).name
            copied.write_bytes(Path(item["audio_file"]).read_bytes())
            self.rows[source_id.casefold()] = {
                "id": source_id,
                "name": f"{role}_source",
                "type": "AudioFileSource",
                "path": source_path,
                "parent": {"id": sound_id},
                "originalFilePath": str(copied),
                "audioSource:language": {"name": "SFX"},
            }
            self.path_to_id[source_path.casefold()] = source_id
            self.source_roles[role] = source_id
            self.rows[sound_id.casefold()]["activeSource"] = {
                "id": source_id
            }
        self.assignments.append(
            {
                "child": {"id": snow_id},
                "stateOrSwitch": {"id": self.roles["surface_snow"]},
            }
        )

    def apply_remove(self, request: Mapping[str, Any]) -> None:
        assert request["operation"] == "switchContainer.removeAssignment"
        arguments = request["arguments"]
        assert arguments == {
            "switch_container": {
                "kind": "path",
                "value": self._path("player_footsteps"),
            },
            "child": {
                "kind": "scoped-name",
                "name": "Mud",
                "type": "RandomSequenceContainer",
                "parent": {
                    "kind": "path",
                    "value": self._path("player_footsteps"),
                },
            },
            "state_or_switch": {
                "kind": "scoped-name",
                "name": "Mud",
                "type": "Switch",
                "parent": {
                    "kind": "path",
                    "value": self._path("surface_group"),
                },
            },
        }
        mud = self.roles["mud_container"].casefold()
        surface = self.roles["surface_mud"].casefold()
        self.assignments = [
            row
            for row in self.assignments
            if not (
                row["child"]["id"].casefold() == mud
                and row["stateOrSwitch"]["id"].casefold() == surface
            )
        ]

    def delete_role(self, role: str) -> None:
        object_id = self.roles[role]
        row = self.rows.pop(object_id.casefold())
        self.path_to_id.pop(row["path"].casefold())


def _unit(version: str = "2022.1") -> Any:
    profile = load_integration_workflows_v2_profile(PROFILE_PATH)
    matches = [
        unit
        for unit in profile.units
        if unit.workflow_id == "footsteps_snow_assignment_maintenance"
        and unit.version == version
    ]
    assert len(matches) == 1
    return matches[0]


def _unprepared_case(
    tmp_path: Path,
    *,
    version: str = "2022.1",
) -> SimpleNamespace:
    unit = _unit(version)
    scenario_root = tmp_path / "scenario"
    asset_root = scenario_root / "owned" / "assets"
    io_root = scenario_root / "owned" / "io"
    sandbox_root = scenario_root / "sandbox" / "SampleProject"
    source_root = tmp_path / "source" / "SampleProject"
    for path in (asset_root, io_root, sandbox_root, source_root):
        path.mkdir(parents=True, exist_ok=True)
    sandbox_project = sandbox_root / "SampleProject.wproj"
    source_project = source_root / "SampleProject.wproj"
    sandbox_project.write_text("sandbox project\n", encoding="utf-8")
    source_project.write_text("source project\n", encoding="utf-8")
    fake = FakeFootstepsWaapi(
        unit.workflow,
        version=version,
        sandbox_root=sandbox_root,
    )
    manifest = fake.manifest(
        source_project=source_project,
        source_root=source_root,
    )
    runtime = SimpleNamespace(
        scenario_root=scenario_root,
        asset_root=asset_root,
        io_root=io_root,
        sandbox=SimpleNamespace(
            sandbox_project=sandbox_project,
            sandbox_path=sandbox_root,
            source_project=source_project,
            source_root=source_root,
        ),
    )
    return SimpleNamespace(
        unit=unit,
        fake=fake,
        manifest=manifest,
        runtime=runtime,
    )


def _case(tmp_path: Path, *, version: str = "2022.1") -> SimpleNamespace:
    case = _unprepared_case(tmp_path, version=version)
    case.prepared = prepare_footsteps_integration_runtime(
        case.unit.workflow,
        case.unit.scenario,
        version=version,
        runtime=case.runtime,
        baseline_manifest=case.manifest,
        direct_call=case.fake,
    )
    return case


def _observe(
    case: SimpleNamespace,
    *,
    stop_after: str | None = None,
) -> None:
    for step in case.prepared.protocol.steps:
        if step.name == "tx01.execute":
            case.fake.apply_import(case.prepared.operation_requests[0])
        elif step.name == "tx02.execute":
            case.fake.apply_remove(case.prepared.operation_requests[1])
        case.prepared.observe_payload(
            step,
            {"ok": True, "command": step.subcommand},
        )
        if step.name == stop_after:
            return


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_prepare_seals_baseline_inputs_and_exact_two_transaction_protocol(
    tmp_path: Path,
    version: str,
) -> None:
    case = _case(tmp_path, version=version)
    prepared = case.prepared
    before = prepared.before_snapshot

    assert prepared.visible_values == {
        "snow_source_directory": str(
            case.runtime.asset_root / "integration-v2/footsteps/incoming"
        ),
        "footsteps_container_path": case.fake._path("player_footsteps"),
        "surface_group_path": case.fake._path("surface_group"),
        "footsteps_event_path": case.fake._path("play_footsteps_event"),
    }
    assert prepared.protocol.turn_prefix_counts == (9, 15, 19)
    assert len(prepared.protocol.steps) == 19
    assert [
        (step.name, step.subcommand)
        for step in prepared.protocol.steps[:2]
    ] == [
        ("tx01.operation-schema", "operation-schema"),
        ("tx01.draft-start", "draft-start"),
    ]
    assert prepared.protocol.steps[0].arguments == ("audio.import",)
    assert all(
        step.subcommand != "metadata" for step in prepared.protocol.steps
    )
    assert prepared.protocol.commutative_read_only_step_groups == ()
    assert [(row.api, row.count) for row in prepared.expected_dispatches] == [
        (IMPORT_API, 1),
        (REMOVE_ASSIGNMENT_API, 1),
    ]
    assert set(before.absent_roles) == {
        "snow_container",
        "snow_step_01",
        "snow_step_02",
        "snow_step_03",
        "snow_step_04",
    }
    assert len(before.input_files) == 4
    assert all(Path(proof.path).is_file() for _, proof in before.input_files)
    assert {row[0] for row in case.fake.calls} <= {
        OBJECT_GET_API,
        GET_ASSIGNMENTS_API,
    }
    assert case.fake.delete_calls == 0

    import_request, remove_request = prepared.operation_requests
    assert import_request["arguments"]["import_operation"] == "createNew"
    import_preview_step = next(
        step for step in prepared.protocol.steps if step.name == "tx01.preview"
    )
    assert import_preview_step.subcommand == "preview-from-draft"
    assert "--request-json" not in import_preview_step.arguments
    import_actions = [
        step.arguments[-1]
        for step in prepared.protocol.steps
        if step.name.startswith("tx01.action.")
    ]
    assert len(import_actions) == 5
    assert all(
        isinstance(argument, DraftActionJsonArgument)
        and argument.operation == "audio.import"
        for argument in import_actions
    )
    imports = import_request["arguments"]["imports"]
    assert len(imports) == 5
    assert imports[0] == {
        "object_path": case.fake._path("snow_container"),
        "object_type": "RandomSequenceContainer",
        "switch_assignment": "Snow",
    }
    assert all(row["object_type"] == "Sound SFX" for row in imports[1:])
    assert sum("switch_assignment" in row for row in imports) == 1
    assert remove_request["arguments"] == {
        "switch_container": {
            "kind": "path",
            "value": case.fake._path("player_footsteps"),
        },
        "child": {
            "kind": "scoped-name",
            "name": "Mud",
            "type": "RandomSequenceContainer",
            "parent": {
                "kind": "path",
                "value": case.fake._path("player_footsteps"),
            },
        },
        "state_or_switch": {
            "kind": "scoped-name",
            "name": "Mud",
            "type": "Switch",
            "parent": {
                "kind": "path",
                "value": case.fake._path("surface_group"),
            },
        },
    }

    assert [argument.expected for argument in import_actions] == [
        {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": (
                "add_switch_assigned_import_row"
                if "switch_assignment" in row
                else "add_import_row_without_switch_assignment"
            ),
            **row,
        }
        for row in imports
    ]


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_scoped_remove_request_accepts_only_its_exact_path_equivalents(
    tmp_path: Path,
    version: str,
) -> None:
    case = _case(tmp_path, version=version)
    remove_request = case.prepared.operation_requests[1]
    preview_step = next(
        step
        for step in case.prepared.protocol.steps
        if step.name == "tx02.preview"
    )
    semantic_argument = preview_step.arguments[2]
    assert isinstance(semantic_argument, SemanticJsonArgument)
    assert semantic_argument.equivalence == (
        "switch_container_remove_assignment_v1"
    )
    broker = CodexGatewayBroker(
        skill_source=(
            Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
        ),
        expected_steps=(preview_step,),
    )
    encoded_request = json.dumps(
        _plain(remove_request),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    semantic_hash, execution_arguments = broker._validate_step(  # noqa: SLF001
        preview_step,
        ("preview", "--apply", "--request-json", encoded_request),
    )
    assert len(semantic_hash) == 64
    assert execution_arguments == (
        "preview",
        "--apply",
        "--request-json",
        encoded_request,
    )

    for child_as_path, value_as_path in (
        (True, False),
        (False, True),
        (True, True),
    ):
        equivalent = copy.deepcopy(_plain(remove_request))
        if child_as_path:
            equivalent["arguments"]["child"] = {
                "kind": "path",
                "value": case.fake._path("mud_container"),
            }
        if value_as_path:
            equivalent["arguments"]["state_or_switch"] = {
                "kind": "path",
                "value": case.fake._path("surface_mud"),
            }
        equivalent_json = json.dumps(equivalent, separators=(",", ":"))
        _, equivalent_arguments = broker._validate_step(  # noqa: SLF001
            preview_step,
            ("preview", "--apply", "--request-json", equivalent_json),
        )
        assert equivalent_arguments[-1] == equivalent_json

    exact_name_container = copy.deepcopy(_plain(remove_request))
    exact_name_container["arguments"]["switch_container"] = {
        "kind": "exact-type-name",
        "type": "SwitchContainer",
        "name": "Player_Footsteps",
    }
    exact_name_json = json.dumps(exact_name_container, separators=(",", ":"))
    _, exact_name_arguments = broker._validate_step(  # noqa: SLF001
        preview_step,
        ("preview", "--apply", "--request-json", exact_name_json),
    )
    assert exact_name_arguments[-1] == exact_name_json

    for invalid_container in (
        {"kind": "path", "value": r"\Player_Footsteps"},
        {
            "kind": "exact-type-name",
            "type": "SwitchContainer",
            "name": "Other",
        },
        {
            "kind": "exact-type-name",
            "type": "RandomSequenceContainer",
            "name": "Player_Footsteps",
        },
    ):
        invalid = copy.deepcopy(_plain(remove_request))
        invalid["arguments"]["switch_container"] = invalid_container
        with pytest.raises(GatewayInvocationError, match="semantically equal"):
            broker._validate_step(  # noqa: SLF001
                preview_step,
                (
                    "preview",
                    "--apply",
                    "--request-json",
                    json.dumps(invalid, separators=(",", ":")),
                ),
            )

    extra_group_segment = copy.deepcopy(_plain(remove_request))
    extra_group_segment["arguments"]["child"] = {
        "kind": "path",
        "value": case.fake._path("mud_container"),
    }
    extra_group_segment["arguments"]["state_or_switch"] = {
        "kind": "path",
        "value": case.fake._path("surface_group") + r"\Surface\Mud",
    }
    with pytest.raises(GatewayInvocationError, match="semantically equal"):
        broker._validate_step(  # noqa: SLF001
            preview_step,
            (
                "preview",
                "--apply",
                "--request-json",
                json.dumps(extra_group_segment, separators=(",", ":")),
            ),
        )


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_observer_preserves_exact_terminal_indeterminate_execute(
    tmp_path: Path,
    version: str,
) -> None:
    case = _case(tmp_path, version=version)
    steps = case.prepared.protocol.steps
    execute_index = next(
        index for index, step in enumerate(steps) if step.name == "tx01.execute"
    )
    for step in steps[:execute_index]:
        case.prepared.observe_payload(
            step,
            {"ok": True, "command": step.subcommand},
        )

    execute = steps[execute_index]
    case.prepared.observe_payload(
        execute,
        {
            "contract": "waapi-skill.gateway-result/v1",
            "ok": False,
            "command": "execute",
            "status": "indeterminate",
            "state": "indeterminate",
            "automatic_retry": False,
        },
    )

    assert case.prepared.protocol.turn_prefix_counts == (9, 15, 19)
    assert case.prepared.operation_requests[0]["arguments"]["imports"][0][
        "switch_assignment"
    ] == "Snow"
    assert case.prepared.verify_turn(1).passed
    with pytest.raises(
        FootstepsIntegrationRuntimeError,
        match="duplicated or observed out of order",
    ):
        case.prepared.observe_payload(
            execute,
            {
                "contract": "waapi-skill.gateway-result/v1",
                "ok": False,
                "command": "execute",
                "status": "indeterminate",
                "state": "indeterminate",
                "automatic_retry": False,
            },
        )
    assert "snow_container" in case.prepared.before_snapshot.absent_roles
    case.prepared.cleanup().assert_passed()


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_weak_import_verification_continues_to_external_business_oracle(
    tmp_path: Path,
    version: str,
) -> None:
    case = _case(tmp_path, version=version)
    for step in case.prepared.protocol.steps:
        if step.name == "tx01.execute":
            case.fake.apply_import(case.prepared.operation_requests[0])
        elif step.name == "tx02.execute":
            case.fake.apply_remove(case.prepared.operation_requests[1])
        payload: dict[str, Any] = {
            "ok": True,
            "command": step.subcommand,
        }
        if step.name == "tx01.verify":
            payload.update(
                {
                    "status": "result_schema_checked",
                    "state": "result_schema_checked",
                    "verified": False,
                    "result_schema_checked": True,
                    "verification": {
                        "business_state_verified": False,
                        "verification_strength": (
                            "operation_specific_readback_with_explicit_native_directive_boundary"
                        ),
                    },
                }
            )
        case.prepared.observe_payload(step, payload)

    verification = case.prepared.verify_final()

    assert verification.passed, verification.failures
    assert verification.assertions["snow_assignment_present"] is True
    assert verification.assertions["mud_assignment_absent"] is True
    assert verification.assertions["two_transaction_sequence_exact"] is True
    case.prepared.cleanup().assert_passed()


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (
        ("contract", "wrong-contract"),
        ("command", "verify"),
        ("status", "failed"),
        ("state", "failed"),
        ("automatic_retry", True),
    ),
)
def test_observer_rejects_non_exact_terminal_indeterminate_execute(
    tmp_path: Path,
    field: str,
    bad_value: Any,
) -> None:
    case = _case(tmp_path)
    steps = case.prepared.protocol.steps
    execute_index = next(
        index for index, step in enumerate(steps) if step.name == "tx01.execute"
    )
    for step in steps[:execute_index]:
        case.prepared.observe_payload(
            step,
            {"ok": True, "command": step.subcommand},
        )
    payload: dict[str, Any] = {
        "contract": "waapi-skill.gateway-result/v1",
        "ok": False,
        "command": "execute",
        "status": "indeterminate",
        "state": "indeterminate",
        "automatic_retry": False,
    }
    payload[field] = bad_value

    with pytest.raises(FootstepsIntegrationRuntimeError):
        case.prepared.observe_payload(steps[execute_index], payload)

    case.prepared.observe_payload(
        steps[execute_index],
        {
            "contract": "waapi-skill.gateway-result/v1",
            "ok": False,
            "command": "execute",
            "status": "indeterminate",
            "state": "indeterminate",
            "automatic_retry": False,
        },
    )
    case.prepared.cleanup().assert_passed()


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_business_oracle_plan_has_two_unambiguous_transaction_deltas(
    tmp_path: Path,
    version: str,
) -> None:
    case = _case(tmp_path, version=version)
    requirements = case.prepared.oracle_requirements

    assert tuple(row.transaction_id for row in requirements) == (
        "tx01",
        "tx02",
    )
    assert all(
        set(row.as_dict()) == {"transaction_id", "expectation"}
        for row in requirements
    )
    tx01 = _plain(requirements[0].expectation)
    tx02 = _plain(requirements[1].expectation)
    assert set(tx01) == {
        "kind",
        "operation",
        "before",
        "preview",
        "checkpoint",
    }
    assert set(tx02) == {
        "kind",
        "operation",
        "precondition",
        "final",
        "protocol",
        "cleanup",
    }
    assert tx01["kind"] == "footsteps.snow-import-delta/v1"
    assert tx02["kind"] == "footsteps.mud-assignment-removal-delta/v1"
    tx01_assertions = tuple(tx01["checkpoint"]["assertion_ids"])
    tx02_assertions = tuple(tx02["final"]["assertion_ids"])
    assert set(tx01_assertions).isdisjoint(tx02_assertions)
    assert tx01_assertions + tx02_assertions == (
        "snow_hierarchy_created_once",
        "snow_media_hashes_match_inputs",
        "snow_assignment_present",
        "mud_objects_and_value_preserved",
        "metal_wood_assignments_unchanged",
        "footstep_event_chain_unchanged",
        "existing_footstep_content_unchanged",
        "footsteps_bus_unchanged",
        "source_project_unchanged",
        "mud_assignment_absent",
        "two_transaction_sequence_exact",
    )

    sections = project_runner._compile_integration_workflow_plan(
        unit=case.unit,
        protocol=case.prepared.protocol,
        visible_values=case.prepared.visible_values,
        oracle_requirements=requirements,
        baseline_manifest_digest=case.manifest.digest,
    )
    rules = _plain(sections.delta_rules)
    assert len(rules) == 2
    assert [row["transaction_id"] for row in rules] == ["tx01", "tx02"]
    assert [row["expectation"] for row in rules] == [tx01, tx02]

    static = _plain(sections.static_expectation)
    transactions = static["transactions"]
    assert [
        (
            row["transaction_id"],
            row["api"],
            row["operation"],
            row["primary_step"],
        )
        for row in transactions
    ] == [
        (
            "tx01",
            "ak.wwise.core.audio.import",
            "audio.import",
            "tx01.execute",
        ),
        (
            "tx02",
            "ak.wwise.core.switchContainer.removeAssignment",
            "switchContainer.removeAssignment",
            "tx02.execute",
        ),
    ]
    workflow_steps = static["workflow_steps"]
    assert len(workflow_steps) == len(case.prepared.protocol.steps) + 1
    assert [row["name"] for row in workflow_steps[:-1]] == [
        step.name for step in case.prepared.protocol.steps
    ]
    assert [row["transaction_id"] for row in workflow_steps[:-1]] == [
        step.name.split(".", 1)[0] for step in case.prepared.protocol.steps
    ]
    assert workflow_steps[-1] == {
        "name": "cleanup.success",
        "kind": "cleanup",
        "phase": (
            "footsteps_snow_assignment_maintenance.cleanup"
        ),
        "transaction_id": None,
        "api": None,
    }
    assert sections.payload_bindings["primary_steps"] == (
        "tx01.execute",
        "tx02.execute",
    )
    case.prepared.cleanup().assert_passed()


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_action_oracle_uses_manifest_id_and_event_children_before_and_after(
    tmp_path: Path,
    version: str,
) -> None:
    case = _case(tmp_path, version=version)
    action_id = case.fake.roles["play_footsteps_action"]
    action_path = case.fake.rows[action_id.casefold()]["path"]
    event_id = case.fake.roles["play_footsteps_event"]

    _observe(case)
    verification = case.prepared.verify_final()
    verification.assert_passed()
    assert verification.after is not None

    object_calls = [
        (args, options)
        for uri, args, options in case.fake.calls
        if uri == OBJECT_GET_API
    ]
    action_calls = [
        (args, options)
        for args, options in object_calls
        if args == {"from": {"id": [action_id]}}
    ]
    assert len(action_calls) == 4
    assert all(
        options["return"]
        == ["id", "name", "type", "path", "parent", "ActionType", "Target"]
        for _, options in action_calls
    )
    assert not any(
        args.get("from") == {"path": [action_path]}
        for args, _options in object_calls
    )
    event_child_calls = [
        (args, options)
        for args, options in object_calls
        if args
        == {
            "from": {"id": [event_id]},
            "transform": [{"select": ["children"]}],
        }
    ]
    assert len(event_child_calls) == 4
    assert all(
        options["return"] == ["id", "name", "type", "path", "parent"]
        for _, options in event_child_calls
    )
    assert all(
        row.name == ""
        and row.object_id.casefold() == action_id.casefold()
        and row.path == action_path
        and row.object_type == "Action"
        for row in (
            case.prepared.before_snapshot.objects_by_role()[
                "play_footsteps_action"
            ],
            verification.after.objects_by_role()["play_footsteps_action"],
        )
    )
    case.prepared.cleanup().assert_passed()


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
@pytest.mark.parametrize(
    ("drift", "message"),
    [
        ("detail_absent", "committed Footsteps object is absent"),
        ("detail_id", "differs from manifest role play_footsteps_action"),
        ("detail_name", "child and sealed Action detail disagree"),
        ("child_path", "child and sealed Action detail disagree"),
        (
            "missing_event_action",
            "differs from manifest role play_footsteps_event",
        ),
        (
            "extra_event_action",
            "differs from manifest role play_footsteps_event",
        ),
    ],
)
def test_action_oracle_fails_closed_on_identity_name_or_relationship_drift(
    tmp_path: Path,
    version: str,
    drift: str,
    message: str,
) -> None:
    case = _unprepared_case(tmp_path, version=version)
    action_id = case.fake.roles["play_footsteps_action"]
    action_path = case.fake.rows[action_id.casefold()]["path"]
    event_id = case.fake.roles["play_footsteps_event"]
    direct_call: Any = case.fake
    if drift in {
        "detail_absent",
        "detail_id",
        "detail_name",
        "child_path",
        "missing_event_action",
    }:

        def drifted_read(
            uri: str,
            args: Mapping[str, Any],
            options: Mapping[str, Any],
        ) -> Any:
            result = case.fake(uri, args, options)
            if uri == OBJECT_GET_API and args == {"from": {"id": [action_id]}}:
                if drift == "detail_absent":
                    result["return"] = []
                elif drift == "detail_id":
                    result["return"][0]["id"] = _guid(
                        "substituted-footsteps-action-detail"
                    )
                elif drift == "detail_name":
                    result["return"][0]["name"] = (
                        "mismatched footsteps detail name"
                    )
            if (
                uri == OBJECT_GET_API
                and args
                == {
                    "from": {"id": [event_id]},
                    "transform": [{"select": ["children"]}],
                }
            ):
                if drift == "missing_event_action":
                    result["return"] = []
                elif drift == "child_path":
                    result["return"][0]["path"] += "-mismatch"
            return result

        direct_call = drifted_read
    else:
        rogue_id = _guid(f"rogue-footsteps-action-{version}")
        case.fake.rows[rogue_id.casefold()] = {
            "id": rogue_id,
            "name": "",
            "type": "Action",
            "path": (
                case.fake.rows[event_id.casefold()]["path"]
                + "\\[Stop - Player_Footsteps]"
            ),
            "parent": {"id": event_id},
            "ActionType": 2,
            "Target": {"id": case.fake.roles["player_footsteps"]},
        }

    with pytest.raises(FootstepsIntegrationRuntimeError, match=message):
        prepare_footsteps_integration_runtime(
            case.unit.workflow,
            case.unit.scenario,
            version=version,
            runtime=case.runtime,
            baseline_manifest=case.manifest,
            direct_call=direct_call,
        )
    assert not (
        case.runtime.asset_root
        / "integration-v2"
        / "footsteps"
        / "incoming"
    ).exists()
    assert not any(
        uri == OBJECT_GET_API
        and args.get("from") == {"path": [action_path]}
        for uri, args, _options in case.fake.calls
    )


def test_turn_oracles_require_no_preview_change_then_exact_snow_checkpoint(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path)
    assert case.prepared.verify_turn(1).passed

    case.fake.apply_import(case.prepared.operation_requests[0])
    checkpoint = case.prepared.verify_turn(2)
    assert checkpoint.passed, checkpoint.failures
    assert checkpoint.assertions["snow_hierarchy_created_once"]
    assert checkpoint.assertions["snow_media_hashes_match_inputs"]
    assert checkpoint.assertions["snow_assignment_present"]

    mud = case.fake.roles["mud_container"].casefold()
    case.fake.assignments = [
        row
        for row in case.fake.assignments
        if row["child"]["id"].casefold() != mud
    ]
    early_remove = case.prepared.verify_turn(2)
    assert not early_remove.passed
    assert not early_remove.assertions["snow_assignment_present"]


def test_preview_oracle_detects_early_business_mutation(tmp_path: Path) -> None:
    case = _case(tmp_path)
    bus = case.fake.rows[case.fake.roles["footsteps_bus"].casefold()]
    bus["@Volume"] = -9.0

    verification = case.prepared.verify_turn(1)
    assert not verification.passed
    assert verification.assertions == {"preview_unchanged": False}


def test_full_protocol_and_final_business_oracle_pass_exact_delta(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path)
    _observe(case)

    verification = case.prepared.verify_final()
    assert verification.passed, verification.failures
    assert tuple(verification.assertions) == (
        "snow_hierarchy_created_once",
        "snow_media_hashes_match_inputs",
        "snow_assignment_present",
        "mud_assignment_absent",
        "mud_objects_and_value_preserved",
        "metal_wood_assignments_unchanged",
        "footstep_event_chain_unchanged",
        "existing_footstep_content_unchanged",
        "footsteps_bus_unchanged",
        "two_transaction_sequence_exact",
        "source_project_unchanged",
    )
    assert all(verification.assertions.values())
    assert case.fake.delete_calls == 0


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_campaign_archive_accepts_real_nameless_action_relationship_rows(
    tmp_path: Path,
    version: str,
) -> None:
    case = _case(tmp_path, version=version)
    before = case.prepared.before_snapshot.as_dict()
    action = next(
        row
        for row in before["children"]
        if row["owner_role"] == "play_footsteps_event"
    )

    assert action["name"] == ""
    assert action["type"] == "Action"
    assert action["path"].rsplit("\\", 1)[-1] == "[Play - Player_Footsteps]"
    assert (
        campaign._validate_integration_v2_snapshot(
            before,
            workflow_id="footsteps_snow_assignment_maintenance",
            version=version,
            label="footsteps archive",
        )
        == before
    )

    _observe(case)
    after = case.prepared.verify_final().after
    assert after is not None
    archived_after = after.as_dict()
    assert (
        campaign._validate_integration_v2_snapshot(
            archived_after,
            workflow_id="footsteps_snow_assignment_maintenance",
            version=version,
            label="footsteps archive",
        )
        == archived_after
    )


@pytest.mark.parametrize(
    ("object_type", "path"),
    [
        ("Sound", r"\Events\Default Work Unit\Play_Footsteps\[Play - Player_Footsteps]"),
        ("Action", r"\Events\Default Work Unit\Play_Footsteps\Play - Player_Footsteps"),
    ],
)
def test_campaign_archive_rejects_other_empty_relationship_name_shapes(
    tmp_path: Path,
    object_type: str,
    path: str,
) -> None:
    case = _case(tmp_path)
    snapshot = case.prepared.before_snapshot.as_dict()
    action = next(
        row
        for row in snapshot["children"]
        if row["owner_role"] == "play_footsteps_event"
    )
    action["type"] = object_type
    action["path"] = path
    snapshot["digest"] = _digest(
        {key: value for key, value in snapshot.items() if key != "digest"}
    )

    with pytest.raises(CampaignEvidenceError, match="relationship row is invalid"):
        campaign._validate_integration_v2_snapshot(
            snapshot,
            workflow_id="footsteps_snow_assignment_maintenance",
            version="2022.1",
            label="footsteps archive",
        )


@pytest.mark.parametrize(
    ("drift", "failed_assertion"),
    [
        ("delete_mud", "mud_objects_and_value_preserved"),
        ("action_target", "footstep_event_chain_unchanged"),
        ("extra_assignment", "snow_assignment_present"),
        ("metal_media", "existing_footstep_content_unchanged"),
    ],
)
def test_final_oracle_rejects_deletes_and_unrelated_changes(
    tmp_path: Path,
    drift: str,
    failed_assertion: str,
) -> None:
    case = _case(tmp_path)
    _observe(case)
    if drift == "delete_mud":
        case.fake.delete_role("mud_sound")
    elif drift == "action_target":
        action = case.fake.rows[
            case.fake.roles["play_footsteps_action"].casefold()
        ]
        action["Target"] = {"id": case.fake.roles["metal_container"]}
    elif drift == "extra_assignment":
        case.fake.assignments.append(
            {
                "child": {"id": case.fake.roles["wood_container"]},
                "stateOrSwitch": {"id": case.fake.roles["surface_snow"]},
            }
        )
    else:
        source = case.fake.rows[
            case.fake.source_roles["metal_sound"].casefold()
        ]
        Path(source["originalFilePath"]).write_bytes(b"changed metal media")

    verification = case.prepared.verify_final()
    assert not verification.passed
    assert not verification.assertions[failed_assertion]


def test_final_oracle_requires_intermediate_and_complete_broker_evidence(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path)
    case.fake.apply_import(case.prepared.operation_requests[0])
    assert case.prepared.verify_turn(2).passed
    case.fake.apply_remove(case.prepared.operation_requests[1])

    verification = case.prepared.verify_final()
    assert not verification.passed
    assert not verification.assertions["two_transaction_sequence_exact"]
    assert all(
        value
        for name, value in verification.assertions.items()
        if name != "two_transaction_sequence_exact"
    )


def test_manifest_state_is_closed_and_live_drift_fails_before_protocol(
    tmp_path: Path,
) -> None:
    unit = _unit()
    built = _case(tmp_path / "valid")
    manifest = built.manifest
    objects = list(manifest.objects)
    player_index = next(
        index
        for index, row in enumerate(objects)
        if row["role"] == "player_footsteps"
    )
    player = dict(objects[player_index])
    state = copy.deepcopy(player["state"])
    state["opaque_extra"] = True
    player["state"] = state
    player["state_sha256"] = _digest(state)
    objects[player_index] = player
    malformed = BaselineManifest(
        manifest.path,
        manifest.version,
        manifest.digest,
        manifest.project_file_sha256,
        manifest.full_tree_sha256,
        tuple(objects),
        manifest.media,
    )

    with pytest.raises(
        FootstepsIntegrationRuntimeError,
        match="state keys are not closed",
    ):
        prepare_footsteps_integration_runtime(
            unit.workflow,
            unit.scenario,
            version="2022.1",
            runtime=built.runtime,
            baseline_manifest=malformed,
            direct_call=built.fake,
        )

    live = _case(tmp_path / "live-drift")
    player_row = live.fake.rows[
        live.fake.roles["player_footsteps"].casefold()
    ]
    player_row["SwitchGroupOrStateGroup"] = {
        "id": live.fake.roles["surface_mud"]
    }
    # A fresh input root is required for a second preparation attempt.
    live.prepared.cleanup().assert_passed()
    with pytest.raises(
        FootstepsIntegrationRuntimeError,
        match="differs from manifest",
    ):
        prepare_footsteps_integration_runtime(
            live.unit.workflow,
            live.unit.scenario,
            version="2022.1",
            runtime=live.runtime,
            baseline_manifest=live.manifest,
            direct_call=live.fake,
        )


def test_cleanup_is_idempotent_and_never_calls_wwise_delete(tmp_path: Path) -> None:
    case = _case(tmp_path)
    proof = case.prepared.cleanup()
    proof.assert_passed()
    assert proof.sandbox_untouched
    assert proof.source_untouched
    assert case.prepared.cleanup().already_clean
    assert case.fake.delete_calls == 0
    assert not Path(case.prepared.visible_values["snow_source_directory"]).exists()


def test_cleanup_refuses_unexpected_input_entry(tmp_path: Path) -> None:
    case = _case(tmp_path)
    input_root = Path(case.prepared.visible_values["snow_source_directory"])
    unexpected = input_root / "do-not-delete.txt"
    unexpected.write_text("sentinel\n", encoding="utf-8")

    proof = case.prepared.cleanup()
    assert not proof.passed
    assert unexpected.exists()
    assert any("unexpected entry" in failure for failure in proof.failures)
