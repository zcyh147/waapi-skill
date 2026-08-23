"""Stateful fake Gateway backed by the real #52 MVP compiler and Preview."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tests.semantic.support.codex_import_declaration_mvp import (
    ImportBusinessMvp,
    MvpRepairError,
)
from wwise_waapi.transactions import TransactionStore


GATEWAY_RESULT_CONTRACT = "waapi-skill.gateway-result/v1"
RUNTIME_ROOT_ENV = "WAAPI_MVP_RUNTIME_ROOT"
SKILL_ROOT_ENV = "WAAPI_MVP_SKILL_ROOT"
VERSION_ENV = "WAAPI_MVP_VERSION"
STATE_DIR_ENV = "WAAPI_SKILL_STATE_DIR"
PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
ROOT_ID = "{11111111-1111-1111-1111-111111111111}"
BUS_ID = "{22222222-2222-2222-2222-222222222222}"
RIFLE_ID = "{33333333-3333-3333-3333-333333333333}"
FOOTSTEPS_ID = "{44444444-4444-4444-4444-444444444444}"
WEAPONS_ID = "{55555555-5555-5555-5555-555555555555}"
AUX_BUS_ID = "{66666666-6666-6666-6666-666666666666}"


@dataclass(frozen=True, slots=True)
class ObjectSpec:
    role: str
    object_id: str
    name: str
    object_type: str
    path: str


@dataclass(frozen=True, slots=True)
class FamilySpec:
    family: str
    version: str
    objects: tuple[ObjectSpec, ...]
    media_keys: tuple[str, ...]
    expected_asset_count: int
    expected_structure_count: int = 0
    custom_wetness: bool = False
    custom_aux_bus: bool = False


class MvpCliRepair(ValueError):
    """Closed CLI parsing failed before any Draft state was loaded."""


class _ClosedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise MvpCliRepair(message)


def prepare_import_mvp_runtime(root: Path) -> Path:
    """Create only the fake media/project files needed by the real Preview."""

    runtime = Path(root).expanduser().resolve(strict=False)
    media = runtime / "media"
    media.mkdir(parents=True, exist_ok=False)
    for key in ("rain", "wind", "rifle", "snow_step", "mechanical", "tail"):
        (media / f"{key}.wav").write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    project = runtime / "SampleProject"
    (project / "Originals").mkdir(parents=True)
    return runtime


def family_spec(family: str, version: str) -> FamilySpec:
    root = (
        r"\Containers\Default Work Unit"
        if version == "2025.1"
        else r"\Actor-Mixer Hierarchy\Default Work Unit"
    )
    common = (
        ObjectSpec("root", ROOT_ID, "Default Work Unit", "WorkUnit", root),
        ObjectSpec(
            "output_bus",
            BUS_ID,
            "MVP_Bus",
            "Bus",
            r"\Master-Mixer Hierarchy\Default Work Unit\MVP_Bus",
        ),
    )
    additions = {
        "weather": (),
        "rifle": (
            ObjectSpec(
                "parent",
                WEAPONS_ID,
                "Weapons",
                "ActorMixer",
                root + r"\Weapons",
            ),
            ObjectSpec(
                "target",
                RIFLE_ID,
                "Rifle",
                "Sound",
                root + r"\Weapons\Rifle",
            ),
        ),
        "footsteps": (
            ObjectSpec(
                "parent",
                FOOTSTEPS_ID,
                "Footsteps",
                "SwitchContainer",
                root + r"\Footsteps",
            ),
        ),
        "weapons": (
            ObjectSpec(
                "parent",
                WEAPONS_ID,
                "Weapons",
                "ActorMixer",
                root + r"\Weapons",
            ),
            ObjectSpec(
                "aux_bus_target",
                AUX_BUS_ID,
                "Weapons_Aux",
                "Bus",
                r"\Master-Mixer Hierarchy\Default Work Unit\Weapons_Aux",
            ),
        ),
    }
    media = {
        "weather": ("rain", "wind"),
        "rifle": ("rifle",),
        "footsteps": ("snow_step",),
        "weapons": ("mechanical", "tail"),
    }
    if family not in additions or version not in {"2022.1", "2025.1"}:
        raise ValueError("unsupported MVP family or version")
    return FamilySpec(
        family=family,
        version=version,
        objects=(*common, *additions[family]),
        media_keys=media[family],
        expected_asset_count=2 if family in {"weather", "weapons"} else 1,
        expected_structure_count=1 if family == "weather" else 0,
        custom_wetness=family == "weapons",
        custom_aux_bus=family == "weapons",
    )


def _new_mvp(
    spec: FamilySpec,
    runtime_root: Path,
) -> tuple[ImportBusinessMvp, dict[str, str]]:
    mvp = ImportBusinessMvp.create(
        version=spec.version,
        task_authority=f"fresh-mvp:{spec.version}:{spec.family}",
        project_id=PROJECT_ID,
    )
    handles = {
        item.role: mvp.bind_object(
            object_id=item.object_id,
            name=item.name,
            object_type=item.object_type,
            path=item.path,
        )
        for item in spec.objects
    }
    if spec.custom_wetness:
        handles["custom_wetness"] = mvp.bind_field(
            metadata_scope="Sound",
            name="CustomWetness",
            field_kind="property",
            value_type="number",
            minimum=0,
            maximum=1,
            metadata_digest="fresh-mvp-custom-wetness-v1",
        )
    if spec.custom_aux_bus:
        handles["custom_aux_bus"] = mvp.bind_field(
            metadata_scope="Sound",
            name="CustomAuxBus",
            field_kind="reference",
            value_type="reference",
            metadata_digest="fresh-mvp-custom-aux-bus-v1",
        )
    return mvp, handles


def _replay(
    state: Mapping[str, Any],
    *,
    runtime_root: Path,
) -> tuple[ImportBusinessMvp, dict[str, str]]:
    spec = family_spec(str(state.get("family")), str(state.get("version")))
    mvp, handles = _new_mvp(spec, runtime_root)
    for item in state.get("declarations", []):
        if not isinstance(item, Mapping):
            raise ValueError("MVP declaration state is malformed")
        kind = item.get("declaration")
        if kind == "structure":
            result = mvp.declare_structure(
                parent=str(item.get("parent")),
                name=str(item.get("name")),
                kind=str(item.get("kind")),
            )
            handles[str(item.get("role"))] = result.handle
        elif kind == "asset":
            fields: dict[str, Any] = {}
            field_handle = item.get("field_handle")
            if field_handle is not None:
                fields[str(field_handle)] = item.get("field_number")
            reference_field = item.get("reference_field_handle")
            if reference_field is not None:
                fields[str(reference_field)] = item.get("reference_target_handle")
            mvp.declare_asset(
                parent=str(item.get("parent")),
                name=str(item.get("name")),
                kind=str(item.get("kind")),
                media_file=runtime_root / "media" / f"{item.get('media')}.wav",
                language=str(item.get("language")),
                volume_db=item.get("volume_db"),
                loop=item.get("loop"),
                output_bus=(
                    str(item.get("output_bus"))
                    if item.get("output_bus") is not None
                    else None
                ),
                switch_value=(
                    str(item.get("switch_value"))
                    if item.get("switch_value") is not None
                    else None
                ),
                fields=fields or None,
            )
        elif kind == "existing":
            mvp.declare_existing_asset(
                target=str(item.get("target")),
                media_file=runtime_root / "media" / f"{item.get('media')}.wav",
                language=str(item.get("language")),
                replace=item.get("replace") is True,
            )
        else:
            raise ValueError("MVP declaration kind is malformed")
    return mvp, handles


def _parser() -> argparse.ArgumentParser:
    parser = _ClosedArgumentParser(add_help=False)
    parser.add_argument("script")
    sub = parser.add_subparsers(dest="command", required=True)
    context = sub.add_parser("mvp-context", add_help=False)
    context.add_argument("--family", required=True)
    structure = sub.add_parser("mvp-structure", add_help=False)
    structure.add_argument("--parent", required=True)
    structure.add_argument("--name", required=True)
    structure.add_argument("--kind", required=True)
    asset = sub.add_parser("mvp-asset", add_help=False)
    asset.add_argument("--parent", required=True)
    asset.add_argument("--name", required=True)
    asset.add_argument("--kind", required=True)
    asset.add_argument("--media", required=True)
    asset.add_argument("--language", required=True)
    asset.add_argument("--volume-db", type=float)
    asset.add_argument("--loop")
    asset.add_argument("--output-bus")
    asset.add_argument("--switch-value")
    asset.add_argument("--field-handle")
    asset.add_argument("--field-number", type=float)
    asset.add_argument("--reference-field-handle")
    asset.add_argument("--reference-target-handle")
    existing = sub.add_parser("mvp-existing-asset", add_help=False)
    existing.add_argument("--target", required=True)
    existing.add_argument("--media", required=True)
    existing.add_argument("--language", required=True)
    existing.add_argument("--replace", action="store_true")
    sub.add_parser("mvp-preview", add_help=False)
    return parser


def _state_path() -> Path:
    return Path(os.environ[STATE_DIR_ENV]).resolve(strict=True) / "deep-import-mvp.json"


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"family": None, "version": os.environ[VERSION_ENV], "declarations": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("MVP state is malformed")
    return value


def _save_state(value: Mapping[str, Any]) -> None:
    path = _state_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _context_payload(spec: FamilySpec, handles: Mapping[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract": "waapi-skill.audio-import-mvp-context/v1",
        "family": spec.family,
        "media_keys": list(spec.media_keys),
        "business_kinds": ["actor-mixer", "sound-sfx"],
        "loop_values": ["infinite"],
        "parent_handle": (
            handles["root"] if spec.family == "weather" else handles["parent"]
        ),
        "output_bus_handle": handles["output_bus"],
        "command_schemas": {
            "mvp-structure": {
                "required": ["--parent", "--name", "--kind"],
            },
            "mvp-asset": {
                "required": ["--parent", "--name", "--kind", "--media", "--language"],
                "optional_when_requested": [
                    "--volume-db",
                    "--loop",
                    "--output-bus",
                    "--switch-value",
                    "--field-handle with --field-number",
                    "--reference-field-handle with --reference-target-handle",
                ],
            },
            "mvp-existing-asset": {
                "required": ["--target", "--media", "--language"],
                "explicit_replacement": "append --replace only when requested",
            },
        },
        "compiler_owns": [
            "wwise_path",
            "wire_type",
            "metadata_scope",
            "native_row_order",
            "batching",
            "continuation",
        ],
    }
    for role in (
        "parent",
        "target",
        "custom_wetness",
        "custom_aux_bus",
        "aux_bus_target",
    ):
        if role in handles:
            result[f"{role}_handle"] = handles[role]
    return result


class _FakePreviewRead:
    def __init__(self, spec: FamilySpec, runtime_root: Path) -> None:
        self.spec = spec
        self.runtime_root = runtime_root
        self.objects = {item.path: _object_row(item) for item in spec.objects}
        self.objects_by_id = {
            item.object_id: self.objects[item.path] for item in spec.objects
        }

    def __call__(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del options
        if uri == "ak.wwise.core.object.getTypes":
            return {
                "return": [
                    {"classId": 1, "name": "PropertyContainer", "type": "WObject"},
                    {"classId": 65550, "name": "ActorMixer", "type": "WObject"},
                    {"classId": 65552, "name": "Sound", "type": "WObject"},
                ]
            }
        if uri == "ak.wwise.core.object.getPropertyInfo":
            return _property_info(str(args.get("property")))
        if uri == "ak.wwise.core.getProjectInfo":
            return _project_info(self.runtime_root / "SampleProject")
        if uri == "ak.wwise.core.object.get":
            source = args.get("from")
            if not isinstance(source, Mapping):
                return {"return": []}
            if isinstance(source.get("id"), list):
                return {
                    "return": [
                        self.objects_by_id[value]
                        for value in source["id"]
                        if value in self.objects_by_id
                    ]
                }
            if isinstance(source.get("path"), list):
                return {
                    "return": [
                        self.objects[value]
                        for value in source["path"]
                        if value in self.objects
                    ]
                }
        raise AssertionError(f"unexpected fake Preview read: {uri} {dict(args)}")


def _object_row(spec: ObjectSpec) -> dict[str, Any]:
    return {
        "id": spec.object_id,
        "name": spec.name,
        "type": spec.object_type,
        "path": spec.path,
        "parent": {"id": PROJECT_ID},
        "notes": "",
    }


def _property_info(name: str) -> dict[str, Any]:
    if name in {"IsLoopingEnabled", "IsLoopingInfinite"}:
        return {"name": name, "type": "Bool", "restriction": {}}
    if name == "Volume":
        return {
            "name": name,
            "type": "Real32",
            "restriction": {"type": "range", "min": -200.0, "max": 200.0},
        }
    if name == "CustomWetness":
        return {
            "name": name,
            "type": "Real32",
            "restriction": {"type": "range", "min": 0.0, "max": 1.0},
        }
    if name in {"OutputBus", "CustomAuxBus"}:
        return {
            "name": name,
            "type": "Reference",
            "restriction": {"type": "reference", "restrictions": [{"type": ["Bus"]}]},
        }
    raise AssertionError(f"unexpected fake property metadata: {name}")


def _project_info(project_root: Path) -> dict[str, Any]:
    return {
        "id": PROJECT_ID,
        "name": "SampleProject",
        "displayTitle": "SampleProject",
        "path": str(project_root / "SampleProject.wproj"),
        "isDirty": False,
        "currentLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
        "referenceLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
        "currentPlatformId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        "directories": {
            "root": str(project_root),
            "cache": str(project_root / ".cache"),
            "originals": str(project_root / "Originals"),
            "soundBankOutputRoot": str(project_root / "GeneratedSoundBanks"),
            "commands": str(project_root / "Commands"),
            "properties": str(project_root / "Properties"),
        },
        "platforms": [
            {
                "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "name": "Mac",
                "baseName": "Mac",
                "baseDisplayName": "Mac",
                "soundBankPath": str(project_root / "GeneratedSoundBanks/Mac"),
                "copiedMediaPath": str(project_root / "GeneratedSoundBanks/Mac/Media"),
            }
        ],
        "languages": [
            {
                "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "name": "SFX",
                "shortId": 1,
            }
        ],
        "defaultConversion": {
            "id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}",
            "name": "Default",
        },
    }


def _preview_result(
    mvp: ImportBusinessMvp,
    *,
    spec: FamilySpec,
    runtime_root: Path,
) -> dict[str, Any]:
    compilation = mvp.compile()
    artifact = mvp.build_preview_artifact(
        read_call=_FakePreviewRead(spec, runtime_root),
        project_guard={
            "contract": "waapi-skill.project-guard/v1",
            "project_guard_mode": "invariant",
            "project": {"state": "open", "id": PROJECT_ID},
        },
        skill_root=Path(os.environ[SKILL_ROOT_ENV]).resolve(strict=True),
    )
    artifact_payload = artifact.as_dict()
    digest = hashlib.sha256(
        json.dumps(compilation.request, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    transaction_id = f"tx-mvp-{digest}"
    store = TransactionStore(_state_path().parent / "mvp-preview-state")
    store.create_preview(transaction_id, artifact_payload)
    sealed = store.load_preview(transaction_id)
    prepared = sealed.artifact["prepared_operation"]
    preview_lines = _business_preview_lines(compilation.request)
    return {
        "contract": "waapi-skill.audio-import-business-preview/v1",
        "test_only": True,
        "wwise_connected": False,
        "wwise_mutated": False,
        "production_accepted": False,
        "transaction_id": transaction_id,
        "immutable_preview_sha256": sealed.artifact_hash,
        "native_call_count": compilation.native_call_count,
        "compiler_evidence": {
            "canonical_request": sealed.artifact["request"],
            "dispatch": prepared["dispatch"],
            "metadata_scopes": list(compilation.metadata_scopes),
            "native_row_mapping": list(compilation.native_row_mapping),
            "next_command": dict(compilation.next_command),
        },
        "preview": preview_lines,
    }


def _business_preview_lines(request: Mapping[str, Any]) -> list[str]:
    arguments = request["arguments"]
    lines = [f"操作：{arguments.get('import_operation', 'createNew')}"]
    for row in arguments["imports"]:
        leaf = str(row["object_path"]).rpartition("\\")[2]
        name = leaf.rpartition(">")[-1]
        lines.extend((f"对象：{name}", f"类型：{row['object_type']}"))
        for prop in row.get("properties", []):
            label = {
                "Volume": "音量",
                "IsLoopingInfinite": "循环方式",
                "CustomWetness": "CustomWetness",
            }.get(prop["name"])
            if label == "音量":
                lines.append(f"音量：{prop['value']:g} dB")
            elif label == "循环方式" and prop["value"] is True:
                lines.append("循环方式：Infinite")
            elif label:
                lines.append(f"{label}：{prop['value']:g}")
        for reference in row.get("references", []):
            lines.append(f"引用：{reference['name']}")
        if "switch_assignment" in row:
            lines.append(f"Switch 值：{row['switch_assignment']}")
    return lines


def _emit(command: str, *, ok: bool, agent_result: Mapping[str, Any]) -> int:
    payload = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": ok,
        "command": command,
        "session_context": {
            "test_only": True,
            "wwise_connected": False,
            "project_modification_policy": "read_only",
        },
        "agent_result": dict(agent_result),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if ok else 2


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    try:
        args = _parser().parse_args(argv)
    except MvpCliRepair as exc:
        command = raw_argv[1] if len(raw_argv) > 1 else "mvp-request"
        return _emit(
            command,
            ok=False,
            agent_result={
                "contract": "waapi-skill.business-repair/v1",
                "error_code": "INCOMPLETE_OR_MISTYPED_DECLARATION",
                "field": "command_arguments",
                "draft_changed": False,
                "action": "resubmit the disclosed high-level command shape",
                "detail": str(exc),
            },
        )
    if args.script != "gateway.py":
        return 2
    runtime_root = Path(os.environ[RUNTIME_ROOT_ENV]).resolve(strict=True)
    version = os.environ[VERSION_ENV]
    try:
        if args.command == "mvp-context":
            spec = family_spec(args.family, version)
            state = {"family": spec.family, "version": spec.version, "declarations": []}
            mvp, handles = _replay(state, runtime_root=runtime_root)
            del mvp
            _save_state(state)
            return _emit(args.command, ok=True, agent_result=_context_payload(spec, handles))

        state = _load_state()
        spec = family_spec(str(state.get("family")), str(state.get("version")))
        declarations = list(state.get("declarations", []))
        if args.command == "mvp-structure":
            declarations.append(
                {
                    "declaration": "structure",
                    "role": "declared_structure",
                    "parent": args.parent,
                    "name": args.name,
                    "kind": args.kind,
                }
            )
        elif args.command == "mvp-asset":
            field_pair_invalid = (
                (args.field_handle is None) != (args.field_number is None)
            )
            reference_pair_invalid = (
                (args.reference_field_handle is None)
                != (args.reference_target_handle is None)
            )
            if (
                args.media not in spec.media_keys
                or field_pair_invalid
                or reference_pair_invalid
            ):
                raise MvpRepairError(
                    {
                        "contract": "waapi-skill.business-repair/v1",
                        "error_code": "BUSINESS_INPUT_UNAVAILABLE",
                        "field": "media_or_field",
                        "draft_changed": False,
                        "action": "use disclosed media and paired field handle/value",
                    }
                )
            declarations.append(
                {
                    "declaration": "asset",
                    "parent": args.parent,
                    "name": args.name,
                    "kind": args.kind,
                    "media": args.media,
                    "language": args.language,
                    "volume_db": args.volume_db,
                    "loop": args.loop,
                    "output_bus": args.output_bus,
                    "switch_value": args.switch_value,
                    "field_handle": args.field_handle,
                    "field_number": args.field_number,
                    "reference_field_handle": args.reference_field_handle,
                    "reference_target_handle": args.reference_target_handle,
                }
            )
        elif args.command == "mvp-existing-asset":
            if args.media not in spec.media_keys:
                raise MvpRepairError(
                    {
                        "contract": "waapi-skill.business-repair/v1",
                        "error_code": "MEDIA_KEY_UNAVAILABLE",
                        "field": "media",
                        "draft_changed": False,
                        "action": "use one disclosed media key",
                    }
                )
            declarations.append(
                {
                    "declaration": "existing",
                    "target": args.target,
                    "media": args.media,
                    "language": args.language,
                    "replace": args.replace,
                }
            )
        elif args.command == "mvp-preview":
            mvp, _handles = _replay(state, runtime_root=runtime_root)
            return _emit(
                args.command,
                ok=True,
                agent_result=_preview_result(
                    mvp,
                    spec=spec,
                    runtime_root=runtime_root,
                ),
            )
        else:
            return 2

        candidate = {**state, "declarations": declarations}
        mvp, handles = _replay(candidate, runtime_root=runtime_root)
        _save_state(candidate)
        inspection = mvp.inspect()
        preview_ready = (
            inspection["asset_count"] == spec.expected_asset_count
            and inspection["structure_count"] == spec.expected_structure_count
        )
        declaration_result: dict[str, Any] = {
            "declared": True,
            "draft_changed": True,
            "draft": inspection,
        }
        if preview_ready:
            declaration_result["next_command"] = dict(mvp.compile().next_command)
            declaration_result["next_action"] = (
                "execute next_command.copy_instruction.source_field verbatim now"
            )
        if args.command == "mvp-structure":
            declaration_result["object_handle"] = handles["declared_structure"]
        if args.command == "mvp-existing-asset":
            declaration_result["mode"] = "replace" if args.replace else "re-import"
        return _emit(
            args.command,
            ok=True,
            agent_result=declaration_result,
        )
    except MvpRepairError as exc:
        return _emit(args.command, ok=False, agent_result=exc.repair)


__all__ = [
    "FamilySpec",
    "family_spec",
    "main",
    "prepare_import_mvp_runtime",
]
