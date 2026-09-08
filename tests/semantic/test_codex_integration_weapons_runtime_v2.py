from __future__ import annotations

import copy
import hashlib
import json
import shlex
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from tests.semantic.support.codex_campaign import canonical_json_bytes
from tests.semantic.support.codex_integration_fixture_tree_v2 import (
    wwise_fixture_tree_sha256,
)
from tests.semantic.support.codex_integration_weapons_runtime_v2 import (
    OBJECT_SET_API,
    WEAPONS_CANONICAL_STATE_FIELDS,
    WeaponsIntegrationRuntimeError,
    prepare_weapons_integration_runtime,
)
from tests.semantic.support.codex_integration_workflows_v2 import (
    BaselineManifest,
    load_integration_workflows_v2_profile,
)
from tests.semantic.support.codex_gateway_broker import (
    CodexGatewayBroker,
    DraftActionMetadataBinding,
    DraftTypedActionBatchArgument,
    DraftTypedActionArgument,
    DraftActionQueryIdentityBinding,
    GatewayInvocationError,
    MetadataQueryArgument,
    ResponseBinding,
    SealedQueryIdentityBoundJsonArgument,
    SemanticJsonArgument,
    gateway_step_sequence_matches,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    PromptProvenanceError,
    deserialize_protocol,
    serialize_protocol,
)
from wwise_waapi.builders.common import split_wwise_path
from wwise_waapi.builders.metadata import (
    GET_PROPERTY_AND_REFERENCE_NAMES_URI,
    GET_PROPERTY_INFO_URI,
    GET_TYPES_URI,
)
from wwise_waapi.operation_composer import typed_action_cli_arguments
from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.operation_composer import (
    apply_composer_action,
    composition_projection,
    materialize_operation_request,
    new_composition,
)


DATA_ROOT = Path(__file__).resolve().parent / "data" / "integration-workflows-v2"
PROFILE_PATH = DATA_ROOT / "profile.json"
OBJECT_GET_API = "ak.wwise.core.object.get"
RTPC_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "notes",
    "@PropertyName",
    "@ControlInput",
    "@Curve",
)
IN_SCOPE = (
    "audit_close",
    "audit_tail",
    "audit_mechanical",
    "audit_exception_legacy",
    "audit_exception_hot",
    "audit_compliant",
)


def _guid(label: str) -> str:
    return "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"weapons-v2:{label}")).upper() + "}"


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


class FakeWeaponsWaapi:
    def __init__(self, workflow: Any, *, version: str, sandbox_root: Path) -> None:
        self.workflow = workflow
        self.version = version
        self.sandbox_root = sandbox_root
        self.rows: dict[str, dict[str, Any]] = {}
        self.path_to_id: dict[str, str] = {}
        self.roles: dict[str, str] = {}
        self.media_roles: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self._build_baseline()

    def _insert(
        self,
        role: str,
        *,
        path: str,
        object_type: str,
        state: Mapping[str, Any],
        object_id: str | None = None,
    ) -> str:
        identity = object_id or _guid(role)
        row = {
            "id": identity,
            "name": path.rsplit("\\", 1)[-1],
            "type": object_type,
            "path": path,
            **copy.deepcopy(dict(state)),
        }
        self.rows[identity.casefold()] = row
        self.path_to_id[path.casefold()] = identity
        self.roles[role] = identity
        return identity

    def _build_baseline(self) -> None:
        specs = {row.role: row for row in self.workflow.fixture.object_graph}
        path = lambda role: specs[role].path_for(self.version)
        actor_parent = _guid("actor-parent")
        event_parent = _guid("event-parent")
        bus_parent = _guid(f"bus-parent-{self.version}")
        parameter_parent = _guid("parameter-parent")
        root_id = self._insert(
            "audit_root",
            path=path("audit_root"),
            object_type=("PropertyContainer" if self.version == "2025.1" else "ActorMixer"),
            state={"parent": {"id": actor_parent}, "children": []},
        )
        bus_id = self._insert(
            "weapons_bus",
            path=path("weapons_bus"),
            object_type="Bus",
            state={"parent": {"id": bus_parent}, "@Volume": 0.0},
        )
        wrong_bus_id = self._insert(
            "footsteps_bus",
            path=path("footsteps_bus"),
            object_type="Bus",
            state={"parent": {"id": bus_parent}, "@Volume": -1.0},
        )
        parameter_id = self._insert(
            "rifle_distance_parameter",
            path=path("rifle_distance_parameter"),
            object_type="GameParameter",
            state={"parent": {"id": parameter_parent}},
        )
        values = {
            "audit_close": (2.0, "close-needs-review", wrong_bus_id),
            "audit_tail": (1.0, "release-ready | tail", bus_id),
            "audit_mechanical": (0.0, "mechanical-needs-review", wrong_bus_id),
            "audit_exception_legacy": (0.0, "legacy-reference", wrong_bus_id),
            "audit_exception_hot": (6.0, "release-ready | intentional-hot", bus_id),
            "audit_compliant": (-3.0, "release-ready | clean", bus_id),
            "audit_out_of_scope": (4.0, "outside", wrong_bus_id),
        }
        for role, (volume, notes, output_bus) in values.items():
            parent = root_id if role in IN_SCOPE else _guid("pistol-parent")
            source_id = _guid(f"{role}-source")
            rtpc_refs: list[dict[str, str]] = []
            if role == "audit_mechanical":
                rtpc_id = _guid("mechanical-volume-rtpc")
                self.rows[rtpc_id.casefold()] = {
                    "id": rtpc_id,
                    "name": "",
                    "type": "RTPC",
                    "path": path(role) + "\\Volume",
                    "notes": "distance curve",
                    "@PropertyName": "Volume",
                    "@ControlInput": {"id": parameter_id},
                    "@Curve": {
                        "points": [
                            {"x": 0.0, "y": -12.0, "shape": "Linear"},
                            {"x": 100.0, "y": 0.0, "shape": "Linear"},
                        ]
                    },
                }
                rtpc_refs = [{"id": rtpc_id}]
            sound_id = self._insert(
                role,
                path=path(role),
                object_type="Sound",
                state={
                    "parent": {"id": parent},
                    "notes": notes,
                    "@Volume": volume,
                    "@Pitch": 0.0,
                    "@IsLoopingEnabled": False,
                    "@UseMaxSoundPerInstance": False,
                    "@MaxSoundPerInstance": 50,
                    "OutputBus": {"id": output_bus},
                    "activeSource": {"id": source_id},
                    "@RTPC": rtpc_refs,
                },
            )
            media = self.sandbox_root / "Originals" / "SFX" / f"{role}.wav"
            media.parent.mkdir(parents=True, exist_ok=True)
            media.write_bytes(f"baseline:{self.version}:{role}".encode())
            source_path = path(role) + f"\\{role}_source"
            self.rows[source_id.casefold()] = {
                "id": source_id,
                "name": f"{role}_source",
                "type": "AudioFileSource",
                "path": source_path,
                "parent": {"id": sound_id},
                "notes": f"{role} source notes",
                "originalFilePath": str(media),
                "audioSource:language": {"name": "SFX"},
            }
            self.path_to_id[source_path.casefold()] = source_id
            self.media_roles[role] = source_id
        self.rows[root_id.casefold()]["children"] = [
            {"id": self.roles[role]} for role in IN_SCOPE
        ]
        event_id = self._insert(
            "audit_close_event",
            path=path("audit_close_event"),
            object_type="Event",
            state={"parent": {"id": event_parent}, "children": []},
        )
        action_id = self._insert(
            "audit_close_action",
            path=path("audit_close_action"),
            object_type="Action",
            state={
                "parent": {"id": event_id},
                "ActionType": 1,
                "Target": {"id": self.roles["audit_close"]},
            },
        )
        self.rows[event_id.casefold()]["children"] = [{"id": action_id}]

    def manifest(self, *, source_project: Path, source_root: Path) -> BaselineManifest:
        specs = {row.role: row for row in self.workflow.fixture.object_graph}
        objects: list[Mapping[str, Any]] = []
        media: list[Mapping[str, str]] = []
        for role, spec in specs.items():
            row = self.rows[self.roles[role].casefold()]
            state: dict[str, Any] = {}
            for field in WEAPONS_CANONICAL_STATE_FIELDS[role]:
                if field == "rtpc_rows":
                    state[field] = [
                        {
                            key: copy.deepcopy(self.rows[ref["id"].casefold()].get(key))
                            for key in RTPC_FIELDS
                        }
                        for ref in row.get("@RTPC", [])
                    ]
                elif field == "children":
                    state[field] = [{"id": value["id"]} for value in row[field]]
                elif field in {"parent", "OutputBus", "activeSource", "Target"}:
                    state[field] = {"id": row[field]["id"]}
                else:
                    state[field] = copy.deepcopy(row[field])
            objects.append(
                {
                    "role": role,
                    "id": row["id"],
                    "path": row["path"],
                    "type": spec.type,
                    "state": state,
                    "state_sha256": _digest(state),
                }
            )
            if spec.type == "Sound":
                source = self.rows[self.media_roles[role].casefold()]
                original = Path(source["originalFilePath"])
                media.append(
                    {
                        "role": role,
                        "active_source_id": source["id"],
                        "relative_path": original.relative_to(self.sandbox_root).as_posix(),
                        "sha256": _sha256(original),
                    }
                )
        return BaselineManifest(
            source_root / "baseline.json",
            self.version,
            "0" * 64,
            _sha256(source_project),
            wwise_fixture_tree_sha256(source_root),
            tuple(objects),
            tuple(media),
        )

    def __call__(
        self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]
    ) -> Any:
        self.calls.append((uri, copy.deepcopy(dict(args)), copy.deepcopy(dict(options))))
        if uri == OBJECT_GET_API:
            source = args["from"]
            values: list[dict[str, Any]] = []
            if "path" in source:
                object_id = self.path_to_id.get(str(source["path"][0]).casefold())
                if object_id is not None:
                    values = [self.rows[object_id.casefold()]]
            else:
                values = [
                    self.rows[str(object_id).casefold()]
                    for object_id in source["id"]
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
            fields = options["return"]
            # Wwise 2022.1 rejects children as a return accessor.  The
            # cross-version shape uses the select transform instead.
            assert "children" not in fields
            return {
                "return": [
                    {
                        field: copy.deepcopy(row.get(field, [] if field == "@RTPC" else None))
                        for field in fields
                    }
                    for row in values
                ]
            }
        if uri == GET_TYPES_URI:
            return {"return": [{"classId": 65552, "name": "Sound", "type": "WObject"}]}
        if uri == GET_PROPERTY_AND_REFERENCE_NAMES_URI:
            return {"return": ["OutputBus", "OverrideOutput", "Volume"]}
        if uri == GET_PROPERTY_INFO_URI:
            name = str(args["property"])
            if name == "OutputBus":
                return {
                    "name": name,
                    "type": "Reference",
                    "default": None,
                    "display": {"name": "Output Bus"},
                    "restriction": {"type": "reference"},
                    "dependencies": [
                        {
                            "type": "override",
                            "action": "Enable",
                            "context": "Self",
                            "property": "OverrideOutput",
                        }
                    ],
                }
            if name == "OverrideOutput":
                return {
                    "name": name,
                    "type": "Boolean",
                    "default": False,
                    "display": {"name": name},
                    "dependencies": [],
                }
            if name == "Volume":
                return {
                    "name": name,
                    "type": "Real32",
                    "default": 0.0,
                    "display": {"name": name},
                    "dependencies": [],
                }
        raise AssertionError(f"unexpected fake WAAPI call: {uri} {args} {options}")

    def audit_row(self, role: str) -> Mapping[str, Any]:
        row = self.rows[self.roles[role].casefold()]
        return {
            "id": copy.deepcopy(row["id"]),
            "name": copy.deepcopy(row["name"]),
            "type": copy.deepcopy(row["type"]),
            "path": copy.deepcopy(row["path"]),
            "output_bus": copy.deepcopy(row["OutputBus"]),
            "volume_db": copy.deepcopy(row["@Volume"]),
            "notes": copy.deepcopy(row["notes"]),
        }

    def audit_payload(self) -> Mapping[str, Any]:
        return {
            "ok": True,
            "command": "query-object",
            "count": len(IN_SCOPE),
            "objects": [self.audit_row(role) for role in IN_SCOPE],
        }

    def identity_payload(self, role: str) -> Mapping[str, Any]:
        row = self.rows[self.roles[role].casefold()]
        return self.object_id_payload(row["id"])

    def object_id_payload(self, object_id: str) -> Mapping[str, Any]:
        row = self.rows[object_id.casefold()]
        return {
            "ok": True,
            "command": "query-object",
            "count": 1,
            "objects": [
                {
                    field: copy.deepcopy(row[field])
                    for field in ("id", "name", "type", "path")
                }
            ],
        }

    def apply_set(self, request: Mapping[str, Any]) -> None:
        request = _plain(request)
        assert request["operation"] == "object.set"
        rows = request["arguments"]["objects"]
        for index, item in enumerate(rows):
            object_id = item["object"]["value"]
            row = self.rows[object_id.casefold()]
            if index == 0:
                old_path = row["path"]
                new_path = old_path.rsplit("\\", 1)[0] + "\\" + item["name"]
                self.path_to_id.pop(old_path.casefold())
                self.path_to_id[new_path.casefold()] = object_id
                row["name"] = item["name"]
                row["path"] = new_path
                row["notes"] = item["notes"]
                row["OutputBus"] = {"id": self.roles["weapons_bus"]}
                action = self.rows[
                    self.roles["audit_close_action"].casefold()
                ]
                old_action_path = action["path"]
                action_parent, separator, action_name = (
                    old_action_path.rpartition("\\")
                )
                assert separator and action_name.count("Rifle_Close") == 1
                new_action_name = action_name.replace(
                    "Rifle_Close", "RFL_Close"
                )
                new_action_path = (
                    action_parent + separator + new_action_name
                )
                self.path_to_id.pop(old_action_path.casefold())
                self.path_to_id[new_action_path.casefold()] = action["id"]
                action["name"] = new_action_name
                action["path"] = new_action_path
            elif index == 1:
                row["@Volume"] = item["properties"][0]["value"]
            else:
                row["notes"] = item["notes"]
                row["OutputBus"] = {"id": self.roles["weapons_bus"]}

    def mutate(self, mutation: str) -> None:
        if mutation == "exception":
            self.rows[self.roles["audit_exception_hot"].casefold()]["notes"] = "changed"
        elif mutation == "rtpc":
            ref = self.rows[self.roles["audit_mechanical"].casefold()]["@RTPC"][0]
            self.rows[ref["id"].casefold()]["@Curve"]["points"][0]["y"] = 99.0
        elif mutation == "event":
            self.rows[self.roles["audit_close_action"].casefold()]["Target"] = {
                "id": self.roles["audit_tail"]
            }
        elif mutation == "source":
            self.rows[self.roles["audit_tail"].casefold()]["activeSource"] = {
                "id": self.media_roles["audit_close"]
            }
        else:
            raise AssertionError(mutation)


def _unit(version: str = "2022.1") -> Any:
    profile = load_integration_workflows_v2_profile(PROFILE_PATH)
    return next(
        unit
        for unit in profile.units
        if unit.workflow_id == "weapons_query_guided_batch_cleanup"
        and unit.version == version
    )


def _paths(tmp_path: Path) -> tuple[Any, Path, Path]:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_project = source_root / "SampleProject.wproj"
    source_project.write_text("immutable source\n", encoding="utf-8")
    scenario_root = tmp_path / "scenario"
    asset_root = scenario_root / "owned" / "assets"
    io_root = scenario_root / "owned" / "io"
    sandbox_path = scenario_root / "owned" / "sandbox" / "SampleProject-copy"
    for path in (asset_root, io_root, sandbox_path):
        path.mkdir(parents=True, exist_ok=True)
    sandbox_project = sandbox_path / "SampleProject.wproj"
    sandbox_project.write_text("copy\n", encoding="utf-8")
    runtime = SimpleNamespace(
        scenario_root=scenario_root,
        asset_root=asset_root,
        io_root=io_root,
        sandbox=SimpleNamespace(
            source_root=source_root,
            source_project=source_project,
            sandbox_path=sandbox_path,
            sandbox_project=sandbox_project,
        ),
    )
    return runtime, source_root, source_project


def _prepared(tmp_path: Path, *, version: str = "2022.1") -> tuple[Any, FakeWeaponsWaapi, Any]:
    unit = _unit(version)
    runtime, source_root, source_project = _paths(tmp_path)
    fake = FakeWeaponsWaapi(
        unit.workflow,
        version=version,
        sandbox_root=runtime.sandbox.sandbox_path,
    )
    manifest = fake.manifest(source_project=source_project, source_root=source_root)
    prepared = prepare_weapons_integration_runtime(
        unit.workflow,
        unit.scenario,
        version=version,
        runtime=runtime,
        baseline_manifest=manifest,
        direct_call=fake,
    )
    return prepared, fake, runtime


def test_weapons_business_protocol_compiles_as_one_complete_workflow_transaction(
    tmp_path: Path,
) -> None:
    from tests.semantic.support import codex_heavy_project_runner_v3 as project_runner

    unit = _unit("2022.1")
    prepared, _fake, _runtime = _prepared(tmp_path)

    sections = project_runner._compile_integration_workflow_plan(
        unit=unit,
        protocol=prepared.protocol,
        visible_values=prepared.visible_values,
        oracle_requirements=prepared.oracle_requirements,
        baseline_manifest_digest="a" * 64,
    )

    transaction_steps = [
        row
        for row in sections.static_expectation["workflow_steps"]
        if row["transaction_id"] == "tx01"
    ]
    assert transaction_steps[0]["kind"] == "operation_schema"
    assert transaction_steps[1]["kind"] == "operation_compose"
    assert transaction_steps[-6]["kind"] == "operation_compose_check"
    assert transaction_steps[-5]["kind"] == "preview"

    wrapped, rebuilt = project_runner.integration_operations_protocol_and_plan(
        unit=unit,
        protocol=prepared.protocol,
        sections=sections,
    )
    assert wrapped.steps[0].name == "routing.operations"
    assert wrapped.steps[1].name == "routing.query-schema"
    assert rebuilt.static_expectation["workflow_id"] == unit.workflow_id
    CodexGatewayBroker(
        skill_source=(
            Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
        ),
        expected_steps=wrapped.steps,
        commutative_read_only_step_groups=(
            wrapped.commutative_read_only_step_groups
        ),
    )


def _typed_action_broker(
    prepared: Any,
    *,
    action: str,
    occurrence: int = 0,
) -> tuple[CodexGatewayBroker, Any, dict[str, Any]]:
    def matches_requested_action(expected: Mapping[str, Any]) -> bool:
        if action == "set_property":
            return bool(expected.get("properties"))
        if action == "set_reference":
            return bool(expected.get("references"))
        return expected.get("action") == action

    matches = [
        (step, argument)
        for step in prepared.protocol.steps
        if step.subcommand == "draft-apply"
        for argument in _draft_action_members(step)
        if matches_requested_action(argument.expected)
    ]
    step, argument = matches[occurrence]
    start = next(
        candidate
        for candidate in prepared.protocol.steps
        if candidate.subcommand == "draft-start"
    )
    broker = CodexGatewayBroker(
        skill_source=(
            Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
        ),
        expected_steps=prepared.protocol.steps,
        commutative_read_only_step_groups=(
            prepared.protocol.commutative_read_only_step_groups
        ),
    )
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": "da1-" + "1" * 40,
        "draft": {
            "draft_id": "od1-" + "2" * 32,
            "revision": 1,
            "current_facts": [],
        },
    }
    broker._payloads_by_step["tx01.metadata"] = (  # noqa: SLF001
        _weapons_metadata_payload()
    )
    for member in _draft_action_members(step):
        for binding in member.query_identity_bindings:
            source_step = next(
                candidate
                for candidate in prepared.protocol.steps
                if candidate.name == binding.step
            )
            target = member.expected["references"][0]["target"]
            broker._payloads_by_step[binding.step] = {  # noqa: SLF001
                "ok": True,
                "command": "query-object",
                "count": 1,
                "objects": [
                    {
                        "id": source_step.arguments[1],
                        "name": "Weapons_Bus",
                        "type": "Bus",
                        "path": target["value"],
                    }
                ],
            }
    supplied_action = copy.deepcopy(dict(argument.expected))
    return broker, step, supplied_action


def _weapons_metadata_payload() -> dict[str, object]:
    def row(name: str) -> dict[str, object]:
        dependency = name == "OutputBus"
        return {
            "name": name,
            "kind": "reference" if dependency else "property",
            "matched_queries": ["requested field"],
            "same_object_dependencies": ["OverrideOutput"] if dependency else [],
            "dependency_requirements": (
                [
                    {
                        "action": "Enable",
                        "context": "Self",
                        "property": "OverrideOutput",
                        "required_values": [True],
                        "type": "override",
                    }
                ]
                if dependency
                else []
            ),
            "metadata": {
                "name": name,
                "type": (
                    ""
                    if dependency
                    else "Boolean"
                    if name == "OverrideOutput"
                    else "Real32"
                ),
                "default": None,
                "display": {"name": name},
                "restriction": {},
            },
        }

    return {
        "agent_result": {
            "contract": "waapi-skill.metadata-discovery/v2",
            "authority": "live-waapi",
            "result_detail": "compact",
            "scope": {
                "kind": "object_type",
                "requested": "Sound",
                "resolved": {"classId": 1, "name": "Sound", "type": "Sound"},
            },
            "candidates": [row("Volume"), row("OutputBus")],
            "dependency_candidates": [row("OverrideOutput")],
            "dependency_closure_complete": True,
            "unresolved_dependencies": [],
            "selection_required": True,
            "exact_live_name_required_for_mutation": True,
        }
    }


def _draft_action_members(step: Any) -> tuple[DraftTypedActionArgument, ...]:
    argument = step.arguments[-1]
    if isinstance(argument, DraftTypedActionArgument):
        return (argument,)
    if isinstance(argument, DraftTypedActionBatchArgument):
        return argument.actions
    return ()


def _typed_action_argv(step: Any, action: Mapping[str, Any]) -> tuple[str, ...]:
    revision_binding = step.arguments[4]
    assert isinstance(revision_binding, ResponseBinding)
    revision = "1" if revision_binding.step.endswith(".draft-start") else "99"
    actual_actions = []
    for member in _draft_action_members(step):
        actual = copy.deepcopy(dict(member.expected))
        if actual.get("selector") == action.get("selector"):
            actual = copy.deepcopy(dict(action))
        actual_actions.append(actual)
    return (
        step.subcommand,
        "od1-" + "2" * 32,
        "--task-authority",
        "da1-" + "1" * 40,
        "--expected-revision",
        revision,
        "--compact",
        "--facts",
        *tuple(
            token
            for actual in actual_actions
            for token in typed_action_cli_arguments(actual)
        ),
    )


def _set_action_pointer(action: dict[str, Any], pointer: str, value: Any) -> None:
    parts = pointer.removeprefix("/").split("/")
    current: Any = action
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    if isinstance(current, list):
        current[int(parts[-1])] = value
    else:
        current[parts[-1]] = value


def _observe(
    prepared: Any,
    fake: FakeWeaponsWaapi,
    *,
    apply: bool = True,
    reverse_output_bus_pair: bool = False,
    add_all_targets_before_fields: bool = False,
) -> None:
    steps = list(prepared.protocol.steps)
    if reverse_output_bus_pair:
        steps[1:3] = reversed(steps[1:3])
    if add_all_targets_before_fields:
        assert all(
            member.expected.get("action") == "add_target"
            for step in steps
            if step.subcommand == "draft-apply"
            for member in _draft_action_members(step)
        )
    for step in steps:
        if step.name == "tx01.execute" and apply:
            fake.apply_set(prepared.operation_request)
        payload = (
            fake.audit_payload()
            if step.name == "audit.scope"
            else (
                fake.object_id_payload(str(step.arguments[1]))
                if step.name.startswith("relationship.output_bus.")
                else {"ok": True, "command": step.subcommand}
            )
        )
        if step.name.startswith("identity."):
            payload = fake.identity_payload(step.name.removeprefix("identity."))
        prepared.observe_payload(step, payload)


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_prepares_scoped_complete_query_and_one_strict_batch(
    tmp_path: Path, version: str
) -> None:
    prepared, _fake, _runtime = _prepared(tmp_path, version=version)

    assert prepared.visible_values["weapons_bus_path"] == (
        r"\Master-Mixer Hierarchy\Default Work Unit\WAAPI_V2_Weapons"
        if version == "2022.1"
        else r"\Busses\Default Work Unit\WAAPI_V2_Weapons"
    )
    assert tuple(step.name for step in prepared.protocol.steps[:8]) == (
        "audit.scope",
        "relationship.output_bus.01",
        "relationship.output_bus.02",
        "identity.audit_close",
        "identity.audit_tail",
        "identity.audit_mechanical",
        "tx01.operation-schema",
        "tx01.draft-start",
    )
    assert prepared.protocol.turn_prefix_counts == (3, 15, 19)
    assert prepared.protocol.commutative_read_only_step_groups == (
        (
            "relationship.output_bus.01",
            "relationship.output_bus.02",
        ),
    )
    serialized = serialize_protocol(prepared.protocol)
    assert deserialize_protocol(serialized) == prepared.protocol
    business_steps = prepared.protocol.steps[7:15]
    assert business_steps[0].subcommand == "draft-start"
    assert [step.subcommand for step in business_steps[-2:]] == [
        "draft-check",
        "preview-from-draft",
    ]
    assert not any(
        step.subcommand == "draft-apply" for step in business_steps
    )
    binding_steps = [
        step for step in business_steps if step.subcommand == "draft-bind-object"
    ]
    assert [step.name for step in binding_steps] == [
        "tx01.bind-target-01-01",
        "tx01.bind-reference-01-02",
        "tx01.bind-target-02-03",
        "tx01.bind-target-03-04",
    ]
    declarations = [
        step
        for step in business_steps
        if step.subcommand == "draft-declare-existing-batch"
    ]
    assert len(declarations) == 1
    assert declarations[0].arguments.count("--row-order") == 3
    assert declarations[0].arguments.count("--row") == 3
    assert declarations[0].arguments.count("--field") == 6
    audit = prepared.protocol.steps[0]
    assert audit.subcommand == "query-object"
    audit_path_arguments = tuple(
        item
        for segment in split_wwise_path(
            prepared.visible_values["weapons_audit_root_path"]
        )
        for item in ("--path-segment", segment)
    )
    assert audit.arguments == (
        *audit_path_arguments,
        "--relationship",
        "descendants",
        "--predicate",
        "kind-is",
        "all-sounds",
        "--max-results",
        "6",
        "--include",
        "notes",
        "--include",
        "volume-db",
        "--include",
        "output-bus",
    )
    before = prepared.before_snapshot.objects_by_role()
    expected_bus_ids = (
        before["footsteps_bus"].object_id,
        before["weapons_bus"].object_id,
    )
    for step, object_id in zip(
        prepared.protocol.steps[1:3], expected_bus_ids, strict=True
    ):
        assert step.subcommand == "query-object"
        assert step.arguments == (
            "--exact-id",
            object_id,
        )
    for step, role in zip(
        prepared.protocol.steps[3:6],
        ("audit_close", "audit_tail", "audit_mechanical"),
        strict=True,
    ):
        assert step.subcommand == "query-object"
        assert step.arguments == (
            "--exact-id",
            before[role].object_id,
        )
    request = _plain(prepared.operation_request)
    assert request["contract"] == "waapi-skill.operation-request/v1"
    assert request["version"] == version
    assert request["operation"] == "object.set"
    assert len(request["arguments"]["objects"]) == 3
    assert request["arguments"]["objects"][0]["name"] == "RFL_Close"
    assert request["arguments"]["objects"][1]["properties"] == [
        {"name": "Volume", "value": -3.0}
    ]
    assert request["arguments"]["objects"][2]["notes"] == (
        "release-ready | mechanical"
    )
    assert prepared.expected_dispatches[0].api == OBJECT_SET_API
    assert prepared.expected_dispatches[0].count == 1
    assert len(prepared.before_snapshot.objects) == 13
    assert len(prepared.before_snapshot.media) == 7


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_weapons_business_draft_keeps_canonical_volume_field(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, _fake, _runtime = _prepared(tmp_path, version=version)
    declaration = next(
        step
        for step in prepared.protocol.steps
        if step.name == "tx01.declare-existing-batch"
    )

    volume_group = declaration.arguments[
        declaration.arguments.index("volume_db") - 2 :
        declaration.arguments.index("volume_db") + 2
    ]
    assert volume_group[:3] == ("--field", "target-02", "volume_db")
    assert volume_group[3].values == ("-3", "-3.0")
    assert "@Volume" not in declaration.arguments


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_business_draft_binds_one_exact_reviewed_output_bus(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, _fake, _runtime = _prepared(tmp_path, version=version)
    reference_bindings = [
        step
        for step in prepared.protocol.steps
        if step.name.startswith("tx01.bind-reference-")
    ]
    assert len(reference_bindings) == 1
    binding = reference_bindings[0]
    expected_segments = tuple(
        segment
        for segment in prepared.visible_values["weapons_bus_path"].split("\\")
        if segment
    )
    actual_segments = tuple(
        binding.arguments[index + 1]
        for index, value in enumerate(binding.arguments[:-1])
        if value == "--object-path-segment"
    )
    assert actual_segments == expected_segments

    declarations = [
        step
        for step in prepared.protocol.steps
        if step.subcommand == "draft-declare-existing-batch"
    ]
    assert len(declarations) == 1
    arguments = declarations[0].arguments
    output_bus_bindings = [
        arguments[index + 3]
        for index, argument in enumerate(arguments[:-3])
        if argument == "--field" and arguments[index + 2] == "output_bus"
    ]
    assert len(output_bus_bindings) == 2
    assert output_bus_bindings[0] == output_bus_bindings[1]


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def _archive_test_compact_draft_replay_accepts_only_the_exact_queried_bus_guid(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path, version=version)
    broker = CodexGatewayBroker(
        skill_source=Path(__file__).resolve().parents[2] / "skills" / "waapi-skill",
        expected_steps=prepared.protocol.steps,
        commutative_read_only_step_groups=(
            prepared.protocol.commutative_read_only_step_groups
        ),
    )
    for source_step in prepared.protocol.steps[1:3]:
        broker._payloads_by_step[source_step.name] = fake.object_id_payload(  # noqa: SLF001
            str(source_step.arguments[1])
        )
    start = next(
        step for step in prepared.protocol.steps if step.subcommand == "draft-start"
    )
    broker._payloads_by_step[start.name] = {  # noqa: SLF001
        "task_authority": "da1-" + "1" * 40,
        "draft": {
            "draft_id": "od1-" + "2" * 32,
            "revision": 1,
            "binding": {"operation": "object.set", "version": version},
        },
    }

    composition = new_composition("object.set", version)
    canonical_action_steps = [
        step for step in prepared.protocol.steps if step.subcommand == "draft-apply"
    ]
    assert len(canonical_action_steps) == 1
    action_step = canonical_action_steps[0]
    action_members = _draft_action_members(action_step)
    assert len(action_members) == 3
    created_handles: list[str] = []
    for index, argument in enumerate(action_members, start=1):
        actual_action = copy.deepcopy(dict(argument.expected))
        for binding in argument.query_identity_bindings:
            source_step = next(
                step for step in prepared.protocol.steps if step.name == binding.step
            )
            _set_action_pointer(
                actual_action,
                binding.pointer,
                {"kind": "id", "value": str(source_step.arguments[1])},
            )
        created_handle = f"odh1-{index:024x}"
        composition, _action_name = apply_composer_action(
            "object.set",
            version,
            composition,
            actual_action,
            handle_factory=lambda value=created_handle: value,
        )
        created_handles.append(created_handle)
    facts = composition_projection(
        "object.set",
        version,
        composition,
    )["current_facts"]
    completion_argv = [
        "python",
        "/owned/run.py",
        "gateway.py",
        "draft-check",
        "od1-" + "2" * 32,
        "--task-authority",
        "da1-" + "1" * 40,
        "--expected-revision",
        "4",
    ]
    broker._payloads_by_step[action_step.name] = {  # noqa: SLF001
        "draft": {
            "draft_id": "od1-" + "2" * 32,
            "revision": 4,
            "action_result": {
                "contract": "waapi-skill.operation-draft-action-result/v1",
                "action": "batch",
                "last_action": "add_target",
                "action_count": 3,
                "applied_atomically": True,
                "created_handles": created_handles,
                "affected_handles": [],
            },
            "current_facts_summary": {
                "contract": "waapi-skill.operation-draft-facts-summary/v1",
                "target_count": len(facts),
                "handle_count": len(
                    {
                        row["handle"]
                        for row in facts
                        if isinstance(row, Mapping) and "handle" in row
                    }
                ),
                "canonical_sha256": canonical_sha256(facts),
            },
            "next_action_binding": {
                "shell_tool_timeout_ms": 30_000,
                "completion_candidate": {
                    "condition": (
                        "all_current_business_request_facts_and_"
                        "disclosures_submitted"
                    ),
                    "business_completion_check": {
                        "source": "current_user_business_request",
                        "schema_required_fields_complete_is_insufficient": True,
                        "all_user_present_optional_map_and_constant_facts_required": True,
                        "exact_values_and_object_types_required": True,
                    },
                    "is_next_command_when_condition_true": True,
                    "fixed_argv_prefix": completion_argv,
                    "copy_exactly": True,
                    "copy_instruction": {
                        "contract": (
                            "waapi-skill.operation-draft-command-copy-instruction/v1"
                        ),
                        "source_field": "copy_command",
                        "action": "execute_verbatim_as_one_shell_tool_call",
                        "forbidden_transformations": [
                            "reconstruct",
                            "shorten",
                            "normalize",
                            "substitute_path_segments",
                            "select_another_field",
                        ],
                    },
                    "copy_command": shlex.join(completion_argv),
                    "allowed_suffix_source": "request_schema_terminal_arguments_only",
                    "draft_apply_action_check": "invalid",
                    "when_condition_false": (
                        "continue_with_one_atomic_typed_action_batch_or_dynamic_disclosure"
                    ),
                },
            },
        }
    }

    preview = next(
        step
        for step in prepared.protocol.steps
        if step.subcommand == "preview-from-draft"
    )
    actual_request = materialize_operation_request(
        "object.set",
        version,
        composition,
    )
    payload = {
        "transaction_id": "tx1-compact-guid-replay",
        "state": "awaiting_confirmation",
        "agent_result": {"request": actual_request},
    }
    broker._validate_operation_draft_payload(preview, payload)  # noqa: SLF001

    compact_action = next(
        step
        for step in reversed(prepared.protocol.steps)
        if step.subcommand == "draft-apply"
    )
    compact_response = broker._payloads_by_step[compact_action.name]  # noqa: SLF001
    compact_response["draft"]["current_facts_summary"]["canonical_sha256"] = (
        "0" * 64
    )
    with pytest.raises(
        GatewayInvocationError,
        match="deterministic composition",
    ):
        broker._validate_operation_draft_payload(preview, payload)  # noqa: SLF001
    compact_response["draft"]["current_facts_summary"]["canonical_sha256"] = (
        canonical_sha256(facts)
    )

    tampered = copy.deepcopy(payload)
    tampered["agent_result"]["request"]["arguments"]["objects"][0][
        "references"
    ][0]["target"]["value"] = _guid("wrong-preview-bus")
    with pytest.raises(
        GatewayInvocationError,
        match="canonical request does not replay",
    ):
        broker._validate_operation_draft_payload(preview, tampered)  # noqa: SLF001


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_children_use_select_transform_not_return_accessor(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path, version=version)

    object_calls = [
        (args, options)
        for uri, args, options in fake.calls
        if uri == OBJECT_GET_API
    ]
    assert object_calls
    assert all("children" not in options["return"] for _, options in object_calls)
    child_calls = [
        (args, options)
        for args, options in object_calls
        if args.get("transform") == [{"select": ["children"]}]
    ]
    assert len(child_calls) == 2
    assert {
        str(args["from"]["id"][0]).casefold() for args, _ in child_calls
    } == {
        prepared.before_snapshot.objects_by_role()[role].object_id.casefold()
        for role in ("audit_root", "audit_close_event")
    }
    assert all(
        options["return"] == ["id", "name", "type", "path", "parent"]
        for _, options in child_calls
    )
    action = prepared.before_snapshot.objects_by_role()["audit_close_action"]
    assert any(
        args.get("from") == {"id": [action.object_id]}
        and "transform" not in args
        for args, _ in object_calls
    )
    assert not any(
        args.get("from") == {"path": [action.path]}
        for args, _ in object_calls
    )
    prepared.cleanup().assert_passed()


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_successful_batch_passes_all_ten_business_assertions(
    tmp_path: Path, version: str
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path, version=version)

    _observe(prepared, fake)
    verification = prepared.verify_final()

    verification.assert_passed()
    assert verification.passed is True
    assert tuple(verification.assertions) == (
        "audit_candidates_exact",
        "excluded_scope_absent",
        "selected_ids_revalidated",
        "selected_guids_and_parents_preserved",
        "selected_corrections_exact",
        "single_object_set_batch",
        "event_action_links_unchanged",
        "rtpc_and_audio_sources_unchanged",
        "exceptions_and_controls_unchanged",
        "source_project_unchanged",
    )
    assert all(verification.assertions.values())
    assert fake.rows[fake.roles["audit_close"].casefold()]["name"] == "RFL_Close"


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_derived_action_display_path_may_follow_renamed_target(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path, version=version)
    old_action = prepared.before_snapshot.objects_by_role()[
        "audit_close_action"
    ]

    _observe(prepared, fake)
    verification = prepared.verify_final()

    verification.assert_passed()
    assert verification.assertions["event_action_links_unchanged"] is True
    assert verification.after is not None
    new_action = verification.after.objects_by_role()["audit_close_action"]
    assert new_action.object_id == old_action.object_id
    assert new_action.name == old_action.name.replace(
        "Rifle_Close", "RFL_Close"
    )
    assert new_action.path == (
        old_action.path.rsplit("\\", 1)[0] + "\\" + new_action.name
    )
    assert new_action.state == old_action.state


def test_action_must_remain_the_event_exact_live_child(tmp_path: Path) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    _observe(prepared, fake)
    fake.rows[fake.roles["audit_close_action"].casefold()]["parent"] = {
        "id": _guid("unexpected-event")
    }

    verification = prepared.verify_final()

    assert verification.passed is False
    assert verification.after is None
    assert any(
        "exactly one direct Action" in failure
        for failure in verification.failures
    )


@pytest.mark.parametrize(
    ("mutation", "failed_assertion"),
    [
        ("exception", "exceptions_and_controls_unchanged"),
        ("rtpc", "rtpc_and_audio_sources_unchanged"),
        ("event", "event_action_links_unchanged"),
        ("source", "rtpc_and_audio_sources_unchanged"),
    ],
)
def test_oracle_detects_protected_state_drift(
    tmp_path: Path, mutation: str, failed_assertion: str
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    _observe(prepared, fake)
    fake.mutate(mutation)

    verification = prepared.verify_final()

    assert verification.passed is False
    assert verification.assertions[failed_assertion] is False


def test_audit_payload_fails_closed_on_scope_escape(tmp_path: Path) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    payload = copy.deepcopy(fake.audit_payload())
    payload["objects"].append(fake.audit_row("audit_out_of_scope"))

    with pytest.raises(WeaponsIntegrationRuntimeError, match="escaped"):
        prepared.observe_payload(prepared.protocol.steps[0], payload)


def test_audit_payload_fails_closed_on_unreviewed_output_bus(tmp_path: Path) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    payload = copy.deepcopy(fake.audit_payload())
    payload["objects"][0]["output_bus"] = {"id": _guid("unreviewed-bus")}

    with pytest.raises(WeaponsIntegrationRuntimeError, match="distinct OutputBus set"):
        prepared.observe_payload(prepared.protocol.steps[0], payload)


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
@pytest.mark.parametrize("reverse", [False, True])
def test_output_bus_hops_accept_both_orders_and_finish_only_after_both(
    tmp_path: Path,
    version: str,
    reverse: bool,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path, version=version)
    audit_payload = copy.deepcopy(fake.audit_payload())
    bus_steps = list(prepared.protocol.steps[1:3])
    if reverse:
        audit_payload["objects"].reverse()
        bus_steps.reverse()

    prepared.observe_payload(prepared.protocol.steps[0], audit_payload)
    prepared.observe_payload(
        bus_steps[0],
        fake.object_id_payload(str(bus_steps[0].arguments[1])),
    )
    assert prepared.verify_turn(1).passed is False

    prepared.observe_payload(
        bus_steps[1],
        fake.object_id_payload(str(bus_steps[1].arguments[1])),
    )

    assert prepared.verify_turn(1).passed is True
    canonical = tuple(step.name for step in prepared.protocol.steps[:3])
    observed = (canonical[0], *(step.name for step in bus_steps))
    assert gateway_step_sequence_matches(
        canonical,
        observed,
        prepared.protocol.commutative_read_only_step_groups,
    )


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_reversed_output_bus_hops_pass_final_business_oracle(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path, version=version)

    _observe(prepared, fake, reverse_output_bus_pair=True)
    verification = prepared.verify_final()

    verification.assert_passed()
    assert verification.assertions["single_object_set_batch"] is True
    prepared.cleanup().assert_passed()


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_dependency_valid_draft_action_order_passes_business_observer(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path, version=version)

    _observe(prepared, fake, add_all_targets_before_fields=True)
    verification = prepared.verify_final()

    verification.assert_passed()
    assert verification.assertions["single_object_set_batch"] is True
    prepared.cleanup().assert_passed()


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("id", "different OutputBus GUID"),
        ("type", "did not resolve to a Bus"),
        ("path", "sealed OutputBus identity"),
        ("missing_path", "identity shape is not closed"),
    ),
)
def test_output_bus_hop_rejects_untrusted_identity_shapes(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    prepared.observe_payload(prepared.protocol.steps[0], fake.audit_payload())
    step = prepared.protocol.steps[1]
    payload = copy.deepcopy(fake.object_id_payload(str(step.arguments[1])))
    if mutation == "id":
        payload["objects"][0]["id"] = fake.roles["weapons_bus"]
    elif mutation == "type":
        payload["objects"][0]["type"] = "Sound"
    elif mutation == "path":
        payload["objects"][0]["path"] += "_Drifted"
    else:
        payload["objects"][0].pop("path")

    with pytest.raises(WeaponsIntegrationRuntimeError, match=message):
        prepared.observe_payload(step, payload)


def test_output_bus_target_classification_uses_path_not_same_name(
    tmp_path: Path,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    prepared.observe_payload(prepared.protocol.steps[0], fake.audit_payload())
    wrong_bus_step, target_bus_step = prepared.protocol.steps[1:3]
    wrong_bus_payload = copy.deepcopy(
        fake.object_id_payload(str(wrong_bus_step.arguments[1]))
    )
    target_bus_payload = fake.object_id_payload(str(target_bus_step.arguments[1]))
    wrong_bus_payload["objects"][0]["name"] = target_bus_payload["objects"][0][
        "name"
    ]

    prepared.observe_payload(wrong_bus_step, wrong_bus_payload)
    prepared.observe_payload(target_bus_step, target_bus_payload)

    assert prepared.verify_turn(1).passed is True


def test_output_bus_hops_reject_duplicate_before_second_distinct_read(
    tmp_path: Path,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    prepared.observe_payload(prepared.protocol.steps[0], fake.audit_payload())
    first = prepared.protocol.steps[1]
    payload = fake.object_id_payload(str(first.arguments[1]))
    prepared.observe_payload(first, payload)

    with pytest.raises(WeaponsIntegrationRuntimeError, match="duplicated or observed"):
        prepared.observe_payload(first, payload)


def test_preview_and_audit_turns_are_read_only(tmp_path: Path) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    audit_step = prepared.protocol.steps[0]
    prepared.observe_payload(audit_step, fake.audit_payload())
    for step in prepared.protocol.steps[1:prepared.protocol.turn_prefix_counts[1]]:
        payload = (
            fake.object_id_payload(str(step.arguments[1]))
            if step.name.startswith("relationship.output_bus.")
            else (
                fake.identity_payload(step.name.removeprefix("identity."))
                if step.name.startswith("identity.")
                else {"ok": True, "command": step.subcommand}
            )
        )
        prepared.observe_payload(step, payload)

    assert prepared.verify_turn(1).passed is True
    assert prepared.verify_turn(2).passed is True


def test_exact_id_readback_fails_closed_before_preview_on_identity_drift(
    tmp_path: Path,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    prepared.observe_payload(prepared.protocol.steps[0], fake.audit_payload())
    for step in prepared.protocol.steps[1:3]:
        prepared.observe_payload(
            step,
            fake.object_id_payload(str(step.arguments[1])),
        )
    step = prepared.protocol.steps[3]
    payload = copy.deepcopy(
        fake.identity_payload(step.name.removeprefix("identity."))
    )
    payload["objects"][0]["path"] += "_Drifted"

    with pytest.raises(
        WeaponsIntegrationRuntimeError,
        match="sealed selected object identity",
    ):
        prepared.observe_payload(step, payload)


def test_manifest_rejects_noncanonical_state_shape(tmp_path: Path) -> None:
    unit = _unit()
    runtime, source_root, source_project = _paths(tmp_path)
    fake = FakeWeaponsWaapi(
        unit.workflow,
        version="2022.1",
        sandbox_root=runtime.sandbox.sandbox_path,
    )
    manifest = fake.manifest(source_project=source_project, source_root=source_root)
    rows = [copy.deepcopy(dict(row)) for row in manifest.objects]
    row = next(item for item in rows if item["role"] == "audit_close")
    row["state"]["unexpected"] = True
    row["state_sha256"] = _digest(row["state"])
    drifted = BaselineManifest(
        manifest.path,
        manifest.version,
        manifest.digest,
        manifest.project_file_sha256,
        manifest.full_tree_sha256,
        tuple(rows),
        manifest.media,
    )

    with pytest.raises(WeaponsIntegrationRuntimeError, match="state shape"):
        prepare_weapons_integration_runtime(
            unit.workflow,
            unit.scenario,
            version="2022.1",
            runtime=runtime,
            baseline_manifest=drifted,
            direct_call=fake,
        )


def test_cleanup_owns_no_project_or_input_deletion(tmp_path: Path) -> None:
    prepared, _fake, runtime = _prepared(tmp_path)

    proof = prepared.cleanup()
    repeated = prepared.cleanup()

    proof.assert_passed()
    assert proof.sandbox_untouched is True
    assert proof.source_untouched is True
    assert runtime.sandbox.sandbox_project.exists()
    assert repeated.already_clean is True
