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
from tests.semantic.support import codex_gateway_broker as broker_module
from tests.semantic.support.codex_campaign import (
    CampaignEvidenceError,
    canonical_json_bytes,
)
from tests.semantic.support.codex_integration_fixture_tree_v2 import (
    wwise_fixture_tree_sha256,
)
from tests.semantic.support.codex_integration_rifle_runtime_v2 import (
    IMPORT_API,
    METADATA_QUERIES,
    METADATA_TOKENS,
    RIFLE_CANONICAL_STATE_FIELDS,
    RIFLE_COMMUTATIVE_COMPOSER_SETUP_STEP_GROUPS,
    RIFLE_COMMUTATIVE_READ_ONLY_STEP_GROUPS,
    RifleIntegrationRuntimeError,
    prepare_rifle_integration_runtime,
)
from tests.semantic.support.codex_gateway_broker import (
    DraftActionJsonArgument,
    gateway_step_sequence_matches,
)
from tests.semantic.support.codex_integration_workflows_v2 import (
    BaselineManifest,
    load_integration_workflows_v2_profile,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    PromptProvenanceError,
    deserialize_protocol,
    serialize_protocol,
)
from wwise_waapi.builders.metadata import (
    GET_PROPERTY_AND_REFERENCE_NAMES_URI,
    GET_PROPERTY_INFO_URI,
    GET_TYPES_URI,
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


def _guid(label: str) -> str:
    return "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"rifle-v2:{label}")).upper() + "}"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeRifleWaapi:
    """Read-only runtime backend plus one explicit test-owned import simulator."""

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
        self.rows: dict[str, dict[str, Any]] = {}
        self.path_to_id: dict[str, str] = {}
        self.roles: dict[str, str] = {}
        self.media_roles: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.delete_calls = 0
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

        container_id = self._insert(
            "rifle_container",
            path=path("rifle_container"),
            object_type="RandomSequenceContainer",
            state={"parent": {"id": actor_parent}, "children": []},
        )
        bus_id = self._insert(
            "weapons_bus",
            path=path("weapons_bus"),
            object_type="Bus",
            state={"parent": {"id": bus_parent}, "@Volume": -1.0},
        )
        parameter_id = self._insert(
            "rifle_distance_parameter",
            path=path("rifle_distance_parameter"),
            object_type="GameParameter",
            state={"parent": {"id": parameter_parent}},
        )
        sound_values = {
            "rifle_close": (-2.0, "close notes", 2),
            "rifle_tail": (-4.0, "tail notes", 4),
            "rifle_mechanical": (-6.0, "mechanical notes", 3),
            "rifle_close_backup": (-18.0, "backup distractor", 1),
            "rifle_tails_distractor": (-21.0, "tails distractor", 1),
        }
        for role, (volume, notes, maximum) in sound_values.items():
            parent = (
                container_id
                if role in {"rifle_close", "rifle_tail", "rifle_mechanical"}
                else _guid("distractor-parent")
            )
            rtpc_refs: list[dict[str, str]] = []
            if role == "rifle_close":
                rtpc_id = _guid("rifle-close-volume-rtpc")
                rtpc_path = path(role) + "\\Volume"
                rtpc = {
                    "id": rtpc_id,
                    "name": "",
                    "type": "RTPC",
                    "path": rtpc_path,
                    "notes": "distance curve",
                    "@PropertyName": "Volume",
                    "@ControlInput": {"id": parameter_id},
                    "@Curve": {
                        "points": [
                            {"x": 0.0, "y": 0.0, "shape": "Linear"},
                            {"x": 100.0, "y": -24.0, "shape": "Linear"},
                        ]
                    },
                }
                self.rows[rtpc_id.casefold()] = rtpc
                self.path_to_id[rtpc_path.casefold()] = rtpc_id
                rtpc_refs = [{"id": rtpc_id}]
            source_id = _guid(f"{role}-source")
            state = {
                "parent": {"id": parent},
                "notes": notes,
                "@Volume": volume,
                "@Pitch": float(maximum),
                "@IsLoopingEnabled": role != "rifle_tails_distractor",
                "@UseMaxSoundPerInstance": True,
                "@MaxSoundPerInstance": maximum,
                "OutputBus": {"id": bus_id},
                "activeSource": {"id": source_id},
                "@RTPC": rtpc_refs,
            }
            sound_id = self._insert(
                role,
                path=path(role),
                object_type="Sound",
                state=state,
            )
            media = self.sandbox_root / "Originals" / "SFX" / f"{role}.wav"
            media.parent.mkdir(parents=True, exist_ok=True)
            media.write_bytes(f"old:{self.version}:{role}".encode())
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

        event_id = self._insert(
            "play_rifle_event",
            path=path("play_rifle_event"),
            object_type="Event",
            state={"parent": {"id": event_parent}, "children": []},
        )
        action_id = self._insert(
            "play_rifle_action",
            path=path("play_rifle_action"),
            object_type="Action",
            state={
                "parent": {"id": event_id},
                "ActionType": 1,
                "Target": {"id": self.roles["rifle_container"]},
            },
        )
        # Real Wwise Actions are nameless objects.  Their bracketed path is a
        # dynamic display path and is not a reliable from.path selector.
        self.rows[action_id.casefold()]["name"] = ""
        self.rows[event_id.casefold()]["children"] = [{"id": action_id}]
        self.rows[container_id.casefold()]["children"] = [
            {"id": self.roles[role]} for role in ("rifle_close", "rifle_tail", "rifle_mechanical")
        ]

    def manifest(
        self,
        *,
        source_project: Path,
        source_root: Path,
    ) -> BaselineManifest:
        specs = {row.role: row for row in self.workflow.fixture.object_graph}
        object_rows: list[Mapping[str, Any]] = []
        media_rows: list[Mapping[str, str]] = []
        for role, spec in specs.items():
            if spec.baseline_state != "present":
                continue
            row = self.rows[self.roles[role].casefold()]
            state: dict[str, Any] = {}
            for field in RIFLE_CANONICAL_STATE_FIELDS[role]:
                if field == "rtpc_rows":
                    rtpc_ids = [value["id"] for value in row.get("@RTPC", [])]
                    state[field] = []
                    for value in rtpc_ids:
                        detail = {
                            key: copy.deepcopy(
                                self.rows[value.casefold()][key]
                            )
                            for key in RTPC_FIELDS
                        }
                        control_input = detail.get("@ControlInput")
                        if isinstance(control_input, Mapping):
                            detail["@ControlInput"] = {
                                "id": control_input["id"]
                            }
                        state[field].append(detail)
                elif field == "children":
                    state[field] = [
                        {"id": value["id"]}
                        for value in sorted(
                            row[field],
                            key=lambda item: str(item["id"]).casefold(),
                        )
                    ]
                elif field in {
                    "parent",
                    "OutputBus",
                    "activeSource",
                    "Target",
                }:
                    state[field] = {"id": row[field]["id"]}
                else:
                    state[field] = copy.deepcopy(row[field])
            object_rows.append(
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
                source = self.rows[self.media_roles[role].casefold()]
                media = Path(source["originalFilePath"])
                media_rows.append(
                    {
                        "role": role,
                        "active_source_id": source["id"],
                        "relative_path": media.relative_to(self.sandbox_root).as_posix(),
                        "sha256": _sha256(media),
                    }
                )
        return BaselineManifest(
            path=source_root / "baseline.json",
            version=self.version,
            digest="0" * 64,
            project_file_sha256=_sha256(source_project),
            full_tree_sha256=wwise_fixture_tree_sha256(source_root),
            objects=tuple(object_rows),
            media=tuple(media_rows),
        )

    def __call__(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Any:
        self.calls.append((uri, copy.deepcopy(dict(args)), copy.deepcopy(dict(options))))
        if uri == OBJECT_GET_API:
            return self._get(args, options)
        if uri == GET_TYPES_URI:
            return {"return": [{"classId": 65552, "name": "Sound", "type": "WObject"}]}
        if uri == GET_PROPERTY_AND_REFERENCE_NAMES_URI:
            assert args == {"classId": 65552}
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
            raise AssertionError(f"unexpected metadata property: {name}")
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
                and str(row["parent"].get("id")).casefold() in parent_ids
            ]
        fields = options.get("return")
        assert isinstance(fields, list)
        # Wwise 2022.1 reports Unknown accessor children when it appears in
        # options.return.  Direct children must come from the select transform.
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

    def apply_import(
        self,
        request: Mapping[str, Any],
        *,
        preserve_existing_source_guids: bool = False,
    ) -> None:
        request = copy.deepcopy(_plain(request))
        assert request["operation"] == "audio.import"
        arguments = request["arguments"]
        assert arguments["import_operation"] == "useExisting"
        imports = arguments["imports"]
        assert len(imports) == 4
        specs = {row.role: row for row in self.workflow.fixture.object_graph}
        path_to_role = {
            spec.path_for(self.version): role for role, spec in specs.items()
        }
        for item in imports[:3]:
            role = path_to_role[item["object_path"]]
            assert role in {"rifle_close", "rifle_tail", "rifle_mechanical"}
            copied = self.sandbox_root / "Originals" / "SFX" / Path(item["audio_file"]).name
            copied.write_bytes(Path(item["audio_file"]).read_bytes())
            old_source_id = self.media_roles[role]
            old_source = self.rows[old_source_id.casefold()]
            if preserve_existing_source_guids:
                old_source["originalFilePath"] = str(copied)
                continue

            source_name = Path(item["audio_file"]).stem
            assert source_name != old_source["name"]
            sound_id = self.roles[role]
            source_id = _guid(f"{role}-source-imported-{self.version}")
            source_path = item["object_path"] + f"\\{source_name}"
            self.rows[source_id.casefold()] = {
                "id": source_id,
                "name": source_name,
                "type": "AudioFileSource",
                "path": source_path,
                "parent": {"id": sound_id},
                "notes": "",
                "originalFilePath": str(copied),
                "audioSource:language": {"name": "SFX"},
            }
            self.path_to_id[source_path.casefold()] = source_id
            self.media_roles[role] = source_id
            self.rows[sound_id.casefold()]["activeSource"] = {"id": source_id}

        item = imports[3]
        assert path_to_role[item["object_path"]] == "rifle_distant"
        container_id = self.roles["rifle_container"]
        bus_id = self.roles["weapons_bus"]
        sound_id = _guid(f"rifle-distant-new-{self.version}")
        source_id = _guid(f"rifle-distant-source-new-{self.version}")
        sound_state = {
            "parent": {"id": container_id},
            "notes": "",
            "@Volume": -12.0,
            "@Pitch": 0.0,
            "@IsLoopingEnabled": False,
            "@UseMaxSoundPerInstance": False,
            "@MaxSoundPerInstance": 50,
            "OutputBus": {"id": bus_id},
            "activeSource": {"id": source_id},
            "@RTPC": [],
        }
        self._insert(
            "rifle_distant",
            path=item["object_path"],
            object_type="Sound",
            state=sound_state,
            object_id=sound_id,
        )
        copied = self.sandbox_root / "Originals" / "SFX" / Path(item["audio_file"]).name
        copied.write_bytes(Path(item["audio_file"]).read_bytes())
        source_path = item["object_path"] + "\\rifle_distant_source"
        self.rows[source_id.casefold()] = {
            "id": source_id,
            "name": "rifle_distant_source",
            "type": "AudioFileSource",
            "path": source_path,
            "parent": {"id": sound_id},
            "notes": "",
            "originalFilePath": str(copied),
            "audioSource:language": {"name": "SFX"},
        }
        self.path_to_id[source_path.casefold()] = source_id
        self.media_roles["rifle_distant"] = source_id
        self.rows[container_id.casefold()]["children"].append({"id": sound_id})

    def mutate(self, mutation: str) -> None:
        if mutation == "existing_guid":
            old = self.roles["rifle_tail"]
            row = self.rows.pop(old.casefold())
            new = _guid("tampered-tail")
            row["id"] = new
            self.rows[new.casefold()] = row
            self.path_to_id[row["path"].casefold()] = new
            self.roles["rifle_tail"] = new
        elif mutation == "active_source_wrong_parent":
            source = self.rows[self.media_roles["rifle_close"].casefold()]
            source["parent"] = {"id": self.roles["rifle_tail"]}
        elif mutation == "active_source_shared":
            self.rows[self.roles["rifle_close"].casefold()]["activeSource"] = {
                "id": self.media_roles["rifle_tail"]
            }
        elif mutation == "active_source_missing":
            self.rows[self.roles["rifle_close"].casefold()]["activeSource"] = {
                "id": _guid("missing-active-source")
            }
        elif mutation == "media_hash":
            source = self.rows[self.media_roles["rifle_close"].casefold()]
            Path(source["originalFilePath"]).write_bytes(b"wrong imported media")
        elif mutation == "volume":
            self.rows[self.roles["rifle_mechanical"].casefold()]["@Volume"] = 9.0
        elif mutation == "rtpc":
            rtpc_id = self.rows[self.roles["rifle_close"].casefold()]["@RTPC"][0]["id"]
            self.rows[rtpc_id.casefold()]["@Curve"]["points"][1]["y"] = -3.0
        elif mutation == "event":
            self.rows[self.roles["play_rifle_action"].casefold()]["Target"] = {
                "id": self.roles["rifle_tail"]
            }
        elif mutation == "distractor":
            self.rows[self.roles["rifle_close_backup"].casefold()]["notes"] = "changed"
        elif mutation == "extra_child":
            path = self.workflow.fixture.object_graph[0].path_for(self.version) + "\\Rifle_Extra"
            self._insert(
                "extra",
                path=path,
                object_type="Sound",
                state={"parent": {"id": self.roles["rifle_container"]}},
            )
        else:
            raise AssertionError(mutation)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _replace_manifest_state(
    manifest: BaselineManifest,
    role: str,
    state: Mapping[str, Any],
) -> BaselineManifest:
    objects: list[Mapping[str, Any]] = []
    for raw in manifest.objects:
        if raw["role"] == role:
            objects.append(
                {
                    **raw,
                    "state": copy.deepcopy(dict(state)),
                    "state_sha256": _digest(state),
                }
            )
        else:
            objects.append(raw)
    return BaselineManifest(
        manifest.path,
        manifest.version,
        manifest.digest,
        manifest.project_file_sha256,
        manifest.full_tree_sha256,
        tuple(objects),
        manifest.media,
    )


def _unit(version: str = "2022.1") -> Any:
    profile = load_integration_workflows_v2_profile(PROFILE_PATH)
    return next(
        row
        for row in profile.units
        if row.workflow_id == "rifle_safe_reimport" and row.version == version
    )


def _paths(tmp_path: Path) -> tuple[Any, Path, Path]:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_project = source_root / "SampleProject.wproj"
    source_project.write_text("immutable source\n", encoding="utf-8")
    scenario_root = tmp_path / "scenario"
    asset_root = scenario_root / "owned" / "assets"
    io_root = scenario_root / "owned" / "io"
    sandbox_path = scenario_root / "owned" / "sandbox-root" / "SampleProject-copy"
    for path in (asset_root, io_root, sandbox_path):
        path.mkdir(parents=True, exist_ok=True)
    sandbox_project = sandbox_path / "SampleProject.wproj"
    sandbox_project.write_text("copied source\n", encoding="utf-8")
    runtime = SimpleNamespace(
        scenario_root=scenario_root,
        asset_root=asset_root,
        io_root=io_root,
        sandbox=SimpleNamespace(
            source_root=source_root,
            source_project=source_project,
            sandbox_root=sandbox_path.parent,
            sandbox_path=sandbox_path,
            sandbox_project=sandbox_project,
        ),
    )
    return runtime, source_root, source_project


def _prepared(tmp_path: Path, *, version: str = "2022.1") -> tuple[Any, FakeRifleWaapi, Any]:
    unit, runtime, fake, manifest = _unprepared(tmp_path, version=version)
    prepared = prepare_rifle_integration_runtime(
        unit.workflow,
        unit.scenario,
        version=version,
        runtime=runtime,
        baseline_manifest=manifest,
        direct_call=fake,
    )
    return prepared, fake, runtime


def _unprepared(
    tmp_path: Path,
    *,
    version: str = "2022.1",
) -> tuple[Any, Any, FakeRifleWaapi, BaselineManifest]:
    unit = _unit(version)
    runtime, source_root, source_project = _paths(tmp_path)
    fake = FakeRifleWaapi(
        unit.workflow,
        version=version,
        sandbox_root=runtime.sandbox.sandbox_path,
    )
    manifest = fake.manifest(source_project=source_project, source_root=source_root)
    return unit, runtime, fake, manifest


def _observe_successful_protocol(
    prepared: Any,
    fake: FakeRifleWaapi,
    *,
    preserve_existing_source_guids: bool = False,
    preamble_order: str = "canonical",
) -> None:
    steps = list(prepared.protocol.steps)
    if preamble_order == "metadata-first":
        steps[:2] = reversed(steps[:2])
    elif preamble_order == "draft-before-metadata":
        steps[1:3] = reversed(steps[1:3])
    elif preamble_order == "static-action-before-metadata":
        steps[:4] = (steps[0], steps[2], steps[3], steps[1])
    elif preamble_order != "canonical":
        raise ValueError("unsupported Rifle preamble order")
    for step in steps:
        if step.name == "tx01.execute":
            fake.apply_import(
                prepared.operation_request,
                preserve_existing_source_guids=preserve_existing_source_guids,
            )
        payload = {"ok": True, "command": step.subcommand}
        prepared.observe_payload(step, payload)


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_prepares_exact_metadata_bound_use_existing_batch(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, fake, runtime = _prepared(tmp_path, version=version)

    assert prepared.visible_values["rifle_source_directory"].startswith(
        str(runtime.asset_root)
    )
    assert prepared.visible_values["rifle_bus_path"] == (
        r"\Master-Mixer Hierarchy\Default Work Unit\WAAPI_V2_Weapons"
        if version == "2022.1"
        else r"\Busses\Default Work Unit\WAAPI_V2_Weapons"
    )
    request = _plain(prepared.operation_request)
    assert request["contract"] == "waapi-skill.operation-request/v1"
    assert request["version"] == version
    assert request["operation"] == "audio.import"
    assert request["arguments"]["import_operation"] == "useExisting"
    defaults = request["arguments"].get("defaults", {})
    assert "import_location" not in defaults
    rows = request["arguments"]["imports"]
    assert len(rows) == 4
    assert all(row["object_path"].startswith("\\") for row in rows)
    assert all("import_location" not in row for row in rows)
    assert [Path(row["audio_file"]).name for row in rows] == [
        "rifle_close_v2.wav",
        "rifle_tail_v2.wav",
        "rifle_mechanical_v2.wav",
        "rifle_distant.wav",
    ]
    assert all(row["object_type"] == "Sound SFX" for row in rows)
    assert all(row["import_language"] == "SFX" for row in rows)
    assert all("event" not in row for row in rows)
    assert rows[-1]["properties"] == [{"name": "Volume", "value": -12.0}]
    assert rows[-1]["references"] == [
        {
            "name": "OutputBus",
            "target": {
                "kind": "path",
                "value": prepared.visible_values["rifle_bus_path"],
            },
        }
    ]
    assert tuple(step.name for step in prepared.protocol.steps[:3]) == (
        "tx01.operation-schema",
        "metadata.discover",
        "tx01.draft-start",
    )
    assert tuple(step.name for step in prepared.protocol.steps[-5:]) == (
        "tx01.preview",
        "tx01.transaction-show",
        "tx01.confirm",
        "tx01.execute",
        "tx01.verify",
    )
    assert prepared.protocol.turn_prefix_counts == (10, 14)
    assert prepared.protocol.commutative_read_only_step_groups == (
        RIFLE_COMMUTATIVE_READ_ONLY_STEP_GROUPS
    )
    assert prepared.protocol.commutative_composer_setup_step_groups == (
        RIFLE_COMMUTATIVE_COMPOSER_SETUP_STEP_GROUPS
    )
    assert METADATA_QUERIES == ("volume", "output bus")
    assert METADATA_TOKENS == ("Volume", "OutputBus")
    assert prepared.protocol.steps[1].arguments[-2:] == ("--limit", "8")
    assert prepared.expected_dispatches[0].api == IMPORT_API
    assert prepared.expected_dispatches[0].count == 1
    assert len(prepared.before_snapshot.objects) == 10
    assert prepared.before_snapshot.absent_roles == ("rifle_distant",)
    assert len(prepared.before_snapshot.input_files) == 4
    assert fake.delete_calls == 0


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_rifle_composer_preserves_every_exact_import_row_and_metadata_binding(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, _fake, _runtime = _prepared(tmp_path, version=version)
    action_arguments = [
        step.arguments[-1]
        for step in prepared.protocol.steps
        if step.name.startswith("tx01.action.")
    ]
    assert len(action_arguments) == 5
    assert all(
        isinstance(argument, DraftActionJsonArgument)
        and argument.operation == "audio.import"
        for argument in action_arguments
    )
    assert action_arguments[0].expected == {
        "contract": "waapi-skill.operation-draft-action/v1",
        "action": "set_import_option",
        "name": "import_operation",
        "value": "useExisting",
    }
    rows = _plain(prepared.operation_request)["arguments"]["imports"]
    assert [argument.expected for argument in action_arguments[1:]] == [
        {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": "add_import_row",
            "assignment": {"mode": "none"},
            **row,
        }
        for row in rows
    ]
    assert action_arguments[-1].metadata_binding is not None
    assert action_arguments[-1].metadata_binding.step == "metadata.discover"
    assert action_arguments[-1].metadata_binding.required_tokens == METADATA_TOKENS


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_campaign_archive_accepts_real_nameless_action_rows(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, _fake, _runtime = _prepared(tmp_path, version=version)
    snapshot = prepared.before_snapshot.as_dict()
    action = next(
        row for row in snapshot["objects"] if row["role"] == "play_rifle_action"
    )

    assert action["name"] == ""
    assert action["type"] == "Action"
    assert action["path"].rsplit("\\", 1)[-1] == "[Play - Rifle]"
    assert (
        campaign._validate_integration_v2_snapshot(
            snapshot,
            workflow_id="rifle_safe_reimport",
            version=version,
            label="rifle archive",
        )
        == snapshot
    )


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_campaign_archive_accepts_sorted_rifle_verification(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path, version=version)
    _observe_successful_protocol(prepared, fake)
    archived = json.loads(
        json.dumps(
            prepared.verify_final().as_dict(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
    )

    campaign._validate_integration_v2_verification(
        archived,
        workflow_id="rifle_safe_reimport",
        version=version,
        label="rifle archive",
    )


@pytest.mark.parametrize(
    ("role", "field", "value"),
    [
        ("rifle_close", "name", ""),
        ("play_rifle_action", "path", r"\Events\Play_Rifle\NotBracketed"),
    ],
)
def test_campaign_archive_rejects_other_empty_name_shapes(
    tmp_path: Path,
    role: str,
    field: str,
    value: str,
) -> None:
    prepared, _fake, _runtime = _prepared(tmp_path)
    snapshot = prepared.before_snapshot.as_dict()
    row = next(item for item in snapshot["objects"] if item["role"] == role)
    row[field] = value
    snapshot["digest"] = _digest(
        {key: item for key, item in snapshot.items() if key != "digest"}
    )

    with pytest.raises(CampaignEvidenceError, match="object row is invalid"):
        campaign._validate_integration_v2_snapshot(
            snapshot,
            workflow_id="rifle_safe_reimport",
            version="2022.1",
            label="rifle archive",
        )


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_rifle_preamble_accepts_only_declared_dependency_safe_orders(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, _fake, _runtime = _prepared(tmp_path, version=version)
    canonical = tuple(step.name for step in prepared.protocol.steps[:8])
    groups = prepared.protocol.commutative_read_only_step_groups
    setup_groups = prepared.protocol.commutative_composer_setup_step_groups

    assert canonical == (
        "tx01.operation-schema",
        "metadata.discover",
        "tx01.draft-start",
        "tx01.action.001",
        "tx01.action.002",
        "tx01.action.003",
        "tx01.action.004",
        "tx01.action.005",
    )
    assert gateway_step_sequence_matches(
        canonical, canonical, groups, setup_groups
    )
    assert gateway_step_sequence_matches(
        canonical,
        (
            "metadata.discover",
            "tx01.operation-schema",
            "tx01.draft-start",
            "tx01.action.001",
            "tx01.action.002",
            "tx01.action.003",
            "tx01.action.004",
            "tx01.action.005",
        ),
        groups,
        setup_groups,
    )
    assert gateway_step_sequence_matches(
        canonical,
        (
            "tx01.operation-schema",
            "tx01.draft-start",
            "metadata.discover",
            "tx01.action.001",
            "tx01.action.002",
            "tx01.action.003",
            "tx01.action.004",
            "tx01.action.005",
        ),
        groups,
        setup_groups,
    )
    assert gateway_step_sequence_matches(
        canonical,
        (
            "tx01.operation-schema",
            "tx01.draft-start",
            "tx01.action.001",
            "tx01.action.002",
            "tx01.action.003",
            "metadata.discover",
            "tx01.action.004",
            "tx01.action.005",
        ),
        groups,
        setup_groups,
    )
    assert gateway_step_sequence_matches(
        canonical,
        (
            "tx01.operation-schema",
            "tx01.draft-start",
            "tx01.action.001",
            "tx01.action.002",
            "tx01.action.003",
            "tx01.action.004",
            "metadata.discover",
            "tx01.action.005",
        ),
        groups,
        setup_groups,
    )

    # The fifth action adds the new row carrying Volume and OutputBus, so
    # metadata may not move beyond that first metadata-bound action.
    assert not gateway_step_sequence_matches(
        canonical,
        (
            "tx01.operation-schema",
            "tx01.draft-start",
            "tx01.action.001",
            "tx01.action.002",
            "tx01.action.003",
            "tx01.action.004",
            "tx01.action.005",
            "metadata.discover",
        ),
        groups,
        setup_groups,
    )

    # Schema and metadata remain mandatory before the first metadata-bound action.
    assert not gateway_step_sequence_matches(
        canonical,
        (
            "metadata.discover",
            "tx01.draft-start",
            "tx01.action.001",
        ),
        groups,
        setup_groups,
    )
    assert not gateway_step_sequence_matches(
        canonical,
        (
            "tx01.operation-schema",
            "tx01.draft-start",
            "tx01.action.001",
        ),
        groups,
        setup_groups,
    )
    assert not gateway_step_sequence_matches(
        canonical,
        (
            "metadata.discover",
            "tx01.draft-start",
            "tx01.operation-schema",
            "tx01.action.001",
            "tx01.action.002",
            "tx01.action.003",
            "tx01.action.004",
            "tx01.action.005",
        ),
        groups,
        setup_groups,
    )
    assert not gateway_step_sequence_matches(
        canonical,
        (
            "tx01.draft-start",
            "tx01.operation-schema",
            "metadata.discover",
            "tx01.action.001",
            "tx01.action.002",
            "tx01.action.003",
            "tx01.action.004",
            "tx01.action.005",
        ),
        groups,
        setup_groups,
    )


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_rifle_metadata_free_setup_group_round_trips_prompt_provenance(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, _fake, _runtime = _prepared(tmp_path, version=version)

    serialized = serialize_protocol(prepared.protocol)

    assert serialized["commutative_composer_setup_step_groups"] == [
        list(RIFLE_COMMUTATIVE_COMPOSER_SETUP_STEP_GROUPS[0])
    ]
    assert deserialize_protocol(serialized) == prepared.protocol

    tampered = copy.deepcopy(serialized)
    tampered["commutative_read_only_step_groups"][0].append(
        "tx01.draft-start"
    )
    with pytest.raises(
        PromptProvenanceError,
        match="commutative read-only protocol groups",
    ):
        deserialize_protocol(tampered)


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
@pytest.mark.parametrize(
    "preamble_order",
    (
        "canonical",
        "metadata-first",
        "draft-before-metadata",
        "static-action-before-metadata",
    ),
)
def test_rifle_observer_and_final_oracle_accept_declared_preamble_orders(
    tmp_path: Path,
    version: str,
    preamble_order: str,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path, version=version)

    _observe_successful_protocol(
        prepared,
        fake,
        preamble_order=preamble_order,
    )
    verification = prepared.verify_final()

    verification.assert_passed()
    assert verification.assertions["single_import_transaction"] is True
    prepared.cleanup().assert_passed()


def test_rifle_observer_rejects_duplicate_or_incomplete_read_pair(
    tmp_path: Path,
) -> None:
    duplicate_root = tmp_path / "duplicate"
    duplicate_root.mkdir()
    duplicate, _fake, _runtime = _prepared(duplicate_root)
    operation_schema = duplicate.protocol.steps[0]
    duplicate.observe_payload(
        operation_schema,
        {"ok": True, "command": operation_schema.subcommand},
    )
    with pytest.raises(
        RifleIntegrationRuntimeError,
        match="duplicated or observed out of order",
    ):
        duplicate.observe_payload(
            operation_schema,
            {"ok": True, "command": operation_schema.subcommand},
        )
    duplicate.cleanup().assert_passed()

    incomplete_root = tmp_path / "incomplete"
    incomplete_root.mkdir()
    incomplete, _fake, _runtime = _prepared(incomplete_root)
    operation_schema = incomplete.protocol.steps[0]
    draft_start = incomplete.protocol.steps[2]
    metadata_free_actions = incomplete.protocol.steps[3:7]
    first_metadata_bound_action = incomplete.protocol.steps[7]
    incomplete.observe_payload(
        operation_schema,
        {"ok": True, "command": operation_schema.subcommand},
    )
    incomplete.observe_payload(
        draft_start,
        {"ok": True, "command": draft_start.subcommand},
    )
    for action in metadata_free_actions:
        incomplete.observe_payload(
            action,
            {"ok": True, "command": action.subcommand},
        )
    with pytest.raises(
        RifleIntegrationRuntimeError,
        match="duplicated or observed out of order",
    ):
        incomplete.observe_payload(
            first_metadata_bound_action,
            {"ok": True, "command": first_metadata_bound_action.subcommand},
        )
    incomplete.cleanup().assert_passed()


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
        for role in ("rifle_container", "play_rifle_event")
    }
    assert all(
        options["return"] == ["id", "name", "type", "path", "parent"]
        for _, options in child_calls
    )
    prepared.cleanup().assert_passed()


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_action_oracle_uses_manifest_id_and_event_children_before_and_after(
    tmp_path: Path,
    version: str,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path, version=version)
    action_id = fake.roles["play_rifle_action"]
    action_path = fake.rows[action_id.casefold()]["path"]
    event_id = fake.roles["play_rifle_event"]

    _observe_successful_protocol(prepared, fake)
    verification = prepared.verify_final()
    verification.assert_passed()
    assert verification.after is not None

    object_calls = [
        (args, options)
        for uri, args, options in fake.calls
        if uri == OBJECT_GET_API
    ]
    action_calls = [
        (args, options)
        for args, options in object_calls
        if args == {"from": {"id": [action_id]}}
    ]
    assert len(action_calls) == 3
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
    assert len(event_child_calls) == 3
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
            prepared.before_snapshot.objects_by_role()["play_rifle_action"],
            verification.after.objects_by_role()["play_rifle_action"],
        )
    )
    prepared.cleanup().assert_passed()


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
@pytest.mark.parametrize(
    ("drift", "message"),
    [
        ("detail_absent", "committed Rifle object is absent"),
        ("detail_id", "differs from manifest role play_rifle_action"),
        ("detail_name", "child and sealed Action detail disagree"),
        ("child_path", "child and sealed Action detail disagree"),
        ("missing_event_action", "differs from manifest role play_rifle_event"),
        ("extra_event_action", "differs from manifest role play_rifle_event"),
    ],
)
def test_action_oracle_fails_closed_on_identity_name_or_relationship_drift(
    tmp_path: Path,
    version: str,
    drift: str,
    message: str,
) -> None:
    unit, runtime, fake, manifest = _unprepared(tmp_path, version=version)
    action_id = fake.roles["play_rifle_action"]
    action_path = fake.rows[action_id.casefold()]["path"]
    event_id = fake.roles["play_rifle_event"]
    direct_call: Any = fake
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
            result = fake(uri, args, options)
            if uri == OBJECT_GET_API and args == {"from": {"id": [action_id]}}:
                if drift == "detail_absent":
                    result["return"] = []
                elif drift == "detail_id":
                    result["return"][0]["id"] = _guid(
                        "substituted-action-detail"
                    )
                elif drift == "detail_name":
                    result["return"][0]["name"] = "mismatched detail name"
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
        rogue_id = _guid(f"rogue-rifle-action-{version}")
        fake.rows[rogue_id.casefold()] = {
            "id": rogue_id,
            "name": "",
            "type": "Action",
            "path": fake.rows[event_id.casefold()]["path"] + "\\[Stop - Rifle]",
            "parent": {"id": event_id},
            "ActionType": 2,
            "Target": {"id": fake.roles["rifle_container"]},
        }

    with pytest.raises(RifleIntegrationRuntimeError, match=message):
        prepare_rifle_integration_runtime(
            unit.workflow,
            unit.scenario,
            version=version,
            runtime=runtime,
            baseline_manifest=manifest,
            direct_call=direct_call,
        )
    assert not (
        runtime.asset_root / "integration-v2" / "rifle" / "incoming"
    ).exists()
    assert not any(
        uri == OBJECT_GET_API
        and args.get("from") == {"path": [action_path]}
        for uri, args, _options in fake.calls
    )


def test_snapshot_normalizes_expanded_live_references_to_canonical_ids(
    tmp_path: Path,
) -> None:
    unit = _unit()
    runtime, source_root, source_project = _paths(tmp_path)
    fake = FakeRifleWaapi(
        unit.workflow,
        version="2022.1",
        sandbox_root=runtime.sandbox.sandbox_path,
    )
    manifest = fake.manifest(
        source_project=source_project,
        source_root=source_root,
    )
    for row in fake.rows.values():
        for field in ("parent", "OutputBus", "activeSource", "Target"):
            value = row.get(field)
            if isinstance(value, Mapping):
                row[field] = {**value, "name": f"expanded-{field}"}
        children = row.get("children")
        if isinstance(children, list):
            row["children"] = [
                {**value, "name": "expanded-child"}
                for value in reversed(children)
            ]
        control_input = row.get("@ControlInput")
        if isinstance(control_input, Mapping):
            row["@ControlInput"] = {
                **control_input,
                "name": "expanded-control-input",
            }

    prepared = prepare_rifle_integration_runtime(
        unit.workflow,
        unit.scenario,
        version="2022.1",
        runtime=runtime,
        baseline_manifest=manifest,
        direct_call=fake,
    )

    states = prepared.before_snapshot.objects_by_role()
    for role, fields in RIFLE_CANONICAL_STATE_FIELDS.items():
        state = states[role].state
        for field in fields:
            value = state[field]
            if field in {"parent", "OutputBus", "activeSource", "Target"}:
                assert set(value) == {"id"}
            elif field == "children":
                children = _plain(value)
                assert all(set(row) == {"id"} for row in children)
                assert [row["id"] for row in children] == sorted(
                    (row["id"] for row in children), key=str.casefold
                )
    close_rtpc = _plain(states["rifle_close"].state["rtpc_rows"])[0]
    assert set(close_rtpc["@ControlInput"]) == {"id"}
    assert states["play_rifle_action"].state["Target"] == {
        "id": states["rifle_container"].object_id
    }
    prepared.cleanup().assert_passed()


@pytest.mark.parametrize(
    ("role", "field"),
    [
        ("weapons_bus", "parent"),
        ("rifle_close", "OutputBus"),
        ("rifle_close", "activeSource"),
        ("play_rifle_action", "Target"),
        ("rifle_close", "rtpc_rows"),
        ("rifle_container", "children"),
    ],
)
def test_manifest_rejects_noncanonical_reference_state(
    tmp_path: Path,
    role: str,
    field: str,
) -> None:
    unit = _unit()
    runtime, source_root, source_project = _paths(tmp_path)
    fake = FakeRifleWaapi(
        unit.workflow,
        version="2022.1",
        sandbox_root=runtime.sandbox.sandbox_path,
    )
    manifest = fake.manifest(
        source_project=source_project,
        source_root=source_root,
    )
    raw = next(row for row in manifest.objects if row["role"] == role)
    state = copy.deepcopy(dict(raw["state"]))
    if field == "children":
        state[field] = list(reversed(state[field]))
    elif field == "rtpc_rows":
        state[field][0]["@ControlInput"]["name"] = "not canonical"
    else:
        state[field]["name"] = "not canonical"
    manifest = _replace_manifest_state(manifest, role, state)

    with pytest.raises(
        RifleIntegrationRuntimeError,
        match="state is not canonical",
    ):
        prepare_rifle_integration_runtime(
            unit.workflow,
            unit.scenario,
            version="2022.1",
            runtime=runtime,
            baseline_manifest=manifest,
            direct_call=fake,
        )


def test_live_children_fail_closed_on_duplicate_guid(
    tmp_path: Path,
) -> None:
    unit = _unit()
    runtime, source_root, source_project = _paths(tmp_path)
    fake = FakeRifleWaapi(
        unit.workflow,
        version="2022.1",
        sandbox_root=runtime.sandbox.sandbox_path,
    )
    manifest = fake.manifest(
        source_project=source_project,
        source_root=source_root,
    )
    container = fake.rows[fake.roles["rifle_container"].casefold()]
    container_id = str(container["id"]).casefold()

    def duplicate_child_call(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Any:
        result = fake(uri, args, options)
        source = args.get("from")
        if (
            uri == OBJECT_GET_API
            and args.get("transform") == [{"select": ["children"]}]
            and isinstance(source, Mapping)
            and [str(value).casefold() for value in source.get("id", [])]
            == [container_id]
        ):
            result["return"].append(copy.deepcopy(result["return"][0]))
        return result

    with pytest.raises(
        RifleIntegrationRuntimeError,
        match="children contain duplicate GUIDs",
    ):
        prepare_rifle_integration_runtime(
            unit.workflow,
            unit.scenario,
            version="2022.1",
            runtime=runtime,
            baseline_manifest=manifest,
            direct_call=duplicate_child_call,
        )
    assert not (
        runtime.asset_root / "integration-v2" / "rifle" / "incoming"
    ).exists()


def test_hidden_oracle_accepts_only_the_complete_business_delta(tmp_path: Path) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    before_media = prepared.before_snapshot.media_by_role()

    prepared.verify_turn(1).assert_passed()
    _observe_successful_protocol(prepared, fake)
    verification = prepared.verify_final(None, None)

    verification.assert_passed()
    assert tuple(verification.assertions) == (
        "existing_sound_guids_preserved",
        "existing_active_sources_bound_to_sounds",
        "updated_media_hashes_match_inputs",
        "distant_created_once_with_new_guid",
        "distant_media_hash_matches_input",
        "rifle_container_child_set_exact",
        "play_event_chain_unchanged",
        "sound_design_state_unchanged",
        "distractors_unchanged",
        "single_import_transaction",
        "source_project_unchanged",
    )
    assert all(verification.assertions.values())
    assert verification.after is not None
    assert len(verification.after.container_children) == 4
    after_media = verification.after.media_by_role()
    for role in ("rifle_close", "rifle_tail", "rifle_mechanical"):
        assert (
            after_media[role].active_source_id
            != before_media[role].active_source_id
        )
    assert verification.assertions["sound_design_state_unchanged"] is True
    # The fake models Wwise 2022's full-existing-ancestor result internally by
    # leaving all committed ancestors present; the hidden oracle judges exact
    # business state, not result.objects cardinality or Event side effects.
    assert verification.after.objects_by_role()["play_rifle_event"] == (
        verification.before.objects_by_role()["play_rifle_event"]
    )


def test_hidden_oracle_also_accepts_preserved_active_source_guids(
    tmp_path: Path,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    before_media = prepared.before_snapshot.media_by_role()
    _observe_successful_protocol(
        prepared,
        fake,
        preserve_existing_source_guids=True,
    )

    verification = prepared.verify_final(None, None)

    verification.assert_passed()
    assert verification.after is not None
    after_media = verification.after.media_by_role()
    for role in ("rifle_close", "rifle_tail", "rifle_mechanical"):
        assert (
            after_media[role].active_source_id
            == before_media[role].active_source_id
        )
    assert verification.assertions[
        "existing_active_sources_bound_to_sounds"
    ] is True


@pytest.mark.parametrize(
    ("mutation", "failed_assertion"),
    [
        ("existing_guid", "existing_sound_guids_preserved"),
        (
            "active_source_wrong_parent",
            "existing_active_sources_bound_to_sounds",
        ),
        (
            "active_source_shared",
            "existing_active_sources_bound_to_sounds",
        ),
        (
            "active_source_missing",
            "existing_active_sources_bound_to_sounds",
        ),
        ("media_hash", "updated_media_hashes_match_inputs"),
        ("volume", "sound_design_state_unchanged"),
        ("rtpc", "sound_design_state_unchanged"),
        ("event", "play_event_chain_unchanged"),
        ("distractor", "distractors_unchanged"),
        ("extra_child", "rifle_container_child_set_exact"),
    ],
)
def test_hidden_oracle_rejects_identity_property_rtpc_chain_and_scope_drift(
    tmp_path: Path,
    mutation: str,
    failed_assertion: str,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    _observe_successful_protocol(prepared, fake)
    fake.mutate(mutation)

    verification = prepared.verify_final(None, None)

    assert not verification.passed
    assert verification.assertions[failed_assertion] is False
    if mutation == "event":
        assert verification.failures == (
            "live copied Rifle object differs from manifest role play_rifle_action",
        )
    elif mutation == "active_source_missing":
        assert verification.failures == (
            "rifle_close activeSource did not resolve exactly once",
        )
    else:
        assert any(
            failure.startswith(f"{failed_assertion}:")
            for failure in verification.failures
        )


@pytest.mark.parametrize("drift", ["id", "state", "media", "unexpected_distant"])
def test_prepare_fails_closed_when_live_copy_differs_from_manifest(
    tmp_path: Path,
    drift: str,
) -> None:
    unit = _unit()
    runtime, source_root, source_project = _paths(tmp_path)
    fake = FakeRifleWaapi(
        unit.workflow,
        version="2022.1",
        sandbox_root=runtime.sandbox.sandbox_path,
    )
    manifest = fake.manifest(source_project=source_project, source_root=source_root)
    if drift == "id":
        objects = list(manifest.objects)
        objects[0] = {**objects[0], "id": _guid("wrong-manifest-id")}
        manifest = BaselineManifest(
            manifest.path,
            manifest.version,
            manifest.digest,
            manifest.project_file_sha256,
            manifest.full_tree_sha256,
            tuple(objects),
            manifest.media,
        )
    elif drift == "state":
        fake.rows[fake.roles["rifle_tail"].casefold()]["notes"] = "live drift"
    elif drift == "media":
        source = fake.rows[fake.media_roles["rifle_close"].casefold()]
        Path(source["originalFilePath"]).write_bytes(b"tampered old media")
    else:
        distant_spec = next(
            spec
            for spec in unit.workflow.fixture.object_graph
            if spec.role == "rifle_distant"
        )
        fake._insert(
            "rifle_distant",
            path=distant_spec.path_for("2022.1"),
            object_type="Sound",
            state={
                "parent": {"id": fake.roles["rifle_container"]},
                "notes": "unexpected",
                "@Volume": 0.0,
                "@Pitch": 0.0,
                "@IsLoopingEnabled": False,
                "@UseMaxSoundPerInstance": False,
                "@MaxSoundPerInstance": 50,
                "OutputBus": {"id": fake.roles["weapons_bus"]},
                "activeSource": {"id": _guid("unexpected-source")},
            },
        )

    with pytest.raises(RifleIntegrationRuntimeError):
        prepare_rifle_integration_runtime(
            unit.workflow,
            unit.scenario,
            version="2022.1",
            runtime=runtime,
            baseline_manifest=manifest,
            direct_call=fake,
        )
    assert not (
        runtime.asset_root / "integration-v2" / "rifle" / "incoming"
    ).exists()


def test_source_project_drift_is_a_hidden_final_failure(tmp_path: Path) -> None:
    prepared, fake, runtime = _prepared(tmp_path)
    _observe_successful_protocol(prepared, fake)
    runtime.sandbox.source_project.write_text("source changed\n", encoding="utf-8")

    verification = prepared.verify_final(None, None)

    assert not verification.passed
    assert verification.assertions["source_project_unchanged"] is False


def test_success_cleanup_removes_only_owned_inputs_and_leaves_lifecycle_state(
    tmp_path: Path,
) -> None:
    prepared, fake, runtime = _prepared(tmp_path)
    _observe_successful_protocol(prepared, fake)
    prepared.verify_final(None, None).assert_passed()
    sandbox_before = runtime.sandbox.sandbox_project.read_bytes()
    source_before = runtime.sandbox.source_project.read_bytes()

    cleanup = prepared.cleanup()

    cleanup.assert_passed()
    assert cleanup.sandbox_untouched
    assert cleanup.source_untouched
    assert not Path(prepared.visible_values["rifle_source_directory"]).exists()
    assert runtime.sandbox.sandbox_project.read_bytes() == sandbox_before
    assert runtime.sandbox.source_project.read_bytes() == source_before
    assert runtime.sandbox.sandbox_path.exists()
    assert fake.delete_calls == 0
    assert prepared.cleanup().already_clean


def test_cleanup_refuses_to_delete_an_unowned_input_entry(
    tmp_path: Path,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    _observe_successful_protocol(prepared, fake)
    prepared.verify_final(None, None).assert_passed()
    input_root = Path(prepared.visible_values["rifle_source_directory"])
    foreign = input_root / "foreign.txt"
    foreign.write_text("not owned by the Rifle adapter\n", encoding="utf-8")

    cleanup = prepared.cleanup()

    assert not cleanup.passed
    assert foreign.exists()
    assert all(path.exists() for path in input_root.glob("*.wav"))


def test_final_oracle_requires_the_complete_one_transaction_observation(
    tmp_path: Path,
) -> None:
    prepared, fake, _runtime = _prepared(tmp_path)
    fake.apply_import(prepared.operation_request)

    verification = prepared.verify_final(None, None)

    assert not verification.passed
    assert verification.assertions["single_import_transaction"] is False
