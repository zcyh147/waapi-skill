"""Pure-program fixtures for exercising every packaged public WAAPI route."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Callable, Mapping


PROBE_GUID = "{00000000-0000-0000-0000-000000000001}"
PROBE_IO_ROOT = (Path(gettempdir()) / "waapi-skill-program-probe").resolve()


def synthesize_schema_value(schema: Mapping[str, Any], *, field_name: str = "value") -> Any:
    """Build a deterministic minimal JSON value for a trusted reflected schema."""

    if "const" in schema:
        return schema["const"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    expected = schema.get("type")
    if isinstance(expected, list):
        expected = next((item for item in expected if item != "null"), expected[0] if expected else None)
    branches = schema.get("oneOf") or schema.get("anyOf")
    if isinstance(expected, str) and expected not in {"object", "array"} and isinstance(branches, list):
        branch = next((item for item in branches if isinstance(item, Mapping)), None)
        if isinstance(branch, Mapping):
            # Scalar reflected schemas often keep ``type`` on the parent and
            # put the usable enum/const values only in oneOf/anyOf branches.
            # Merge one branch with the parent so generated program probes are
            # valid under the same complete-branch rules as production input.
            merged = {key: value for key, value in schema.items() if key not in {"oneOf", "anyOf"}}
            merged.update(branch)
            return synthesize_schema_value(merged, field_name=field_name)
    if not isinstance(expected, str):
        if isinstance(schema.get("properties"), Mapping) or isinstance(schema.get("required"), list):
            expected = "object"
        elif isinstance(schema.get("items"), Mapping):
            expected = "array"
        elif isinstance(schema.get("$ref"), str):
            return _reference_value(str(schema["$ref"]), field_name)
        else:
            if isinstance(branches, list):
                branch = next((item for item in branches if isinstance(item, Mapping)), None)
                if isinstance(branch, Mapping):
                    return synthesize_schema_value(branch, field_name=field_name)
            return {}
    if expected == "object":
        properties = schema.get("properties")
        property_schemas = properties if isinstance(properties, Mapping) else {}
        required = [item for item in schema.get("required", []) if isinstance(item, str)]
        result: dict[str, Any] = {
            name: synthesize_schema_value(
                property_schemas.get(name, {}) if isinstance(property_schemas.get(name), Mapping) else {},
                field_name=name,
            )
            for name in required
        }
        if isinstance(branches, list):
            branch = next((item for item in branches if isinstance(item, Mapping)), None)
            if isinstance(branch, Mapping):
                branch_properties = branch.get("properties")
                branch_property_schemas = branch_properties if isinstance(branch_properties, Mapping) else {}
                for name in branch.get("required", []):
                    if not isinstance(name, str) or name in result:
                        continue
                    candidate = branch_property_schemas.get(name, property_schemas.get(name, {}))
                    result[name] = synthesize_schema_value(
                        candidate if isinstance(candidate, Mapping) else {},
                        field_name=name,
                    )
        return result
    if expected == "array":
        item_schema = schema.get("items")
        minimum = schema.get("minItems")
        count = max(1, minimum) if isinstance(minimum, int) and minimum > 0 else 0
        if count == 0:
            return []
        return [
            synthesize_schema_value(item_schema if isinstance(item_schema, Mapping) else {}, field_name=field_name)
            for _ in range(count)
        ]
    if expected == "string":
        pattern = schema.get("pattern")
        return _pattern_string(pattern if isinstance(pattern, str) else "", field_name)
    if expected == "integer":
        minimum = schema.get("minimum")
        return int(minimum) if isinstance(minimum, (int, float)) else 0
    if expected == "number":
        minimum = schema.get("minimum")
        return float(minimum) if isinstance(minimum, (int, float)) else 0.0
    if expected == "boolean":
        return False
    if expected == "null":
        return None
    return {}


def request_and_result_from_schema(schema: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], Any]:
    args_schema = schema.get("argsSchema")
    options_schema = schema.get("optionsSchema")
    result_schema = schema.get("resultSchema")
    args = synthesize_schema_value(args_schema if isinstance(args_schema, Mapping) else {}, field_name="args")
    options = synthesize_schema_value(
        options_schema if isinstance(options_schema, Mapping) else {},
        field_name="options",
    )
    result = synthesize_schema_value(
        result_schema if isinstance(result_schema, Mapping) else {},
        field_name="result",
    )
    return dict(args) if isinstance(args, Mapping) else {}, dict(options) if isinstance(options, Mapping) else {}, result


def _reference_value(reference: str, field_name: str) -> Any:
    lowered = f"{reference} {field_name}".lower()
    if "array" in lowered:
        return []
    filesystem_path = _filesystem_probe_path(field_name, lowered)
    if filesystem_path is not None:
        return filesystem_path
    if any(token in lowered for token in ("uint", "int", "gameobject", "playingid", "pipelineid", "cursor")):
        return 1
    if any(token in lowered for token in ("guid", "object", "state", "switch", "event", "soundbank", "platform")):
        return PROBE_GUID
    return "probe"


def _pattern_string(pattern: str, field_name: str) -> str:
    lowered = f"{pattern} {field_name}".lower()
    normalized_field = "".join(character for character in field_name.casefold() if character.isalnum())
    if normalized_field in {"objectpath", "importlocation"}:
        return r"\ProgramProbe"
    if normalized_field == "originalssubfolder":
        return "ProgramProbe"
    filesystem_path = _filesystem_probe_path(field_name, lowered)
    if filesystem_path is not None:
        return filesystem_path
    if pattern and pattern.isalnum():
        return pattern
    if "ak\\." in pattern or field_name == "api":
        return "ak.probe"
    if "wproj" in lowered or "[ww][pp][rr][oo][jj]" in lowered:
        return str(PROBE_IO_ROOT / "ProgramProbe.wproj")
    if "guid" in lowered or "[0-9a-f" in lowered or "[a-f0-9" in lowered:
        return PROBE_GUID
    if "\\\\" in pattern or "path" in lowered:
        return r"\Probe"
    return "probe"


def _filesystem_probe_path(field_name: str, schema_hint: str) -> str | None:
    normalized_field = "".join(character for character in field_name.casefold() if character.isalnum())
    filesystem_fields = {
        "audiofile",
        "directory",
        "file",
        "files",
        "folder",
        "headerfilepath",
        "importdefinitionfile",
        "importfile",
        "input",
        "licensefile",
        "newfiles",
        "output",
        "path",
        "project",
        "rootoutputpath",
        "soundbankpath",
        "sourcebyplatform",
        "sourcefile",
        "tabdelimitedimportfile",
    }
    if normalized_field in filesystem_fields or normalized_field.endswith(
        ("directory", "file", "files", "folder", "path", "project")
    ):
        is_project = (
            normalized_field == "project"
            or "wproj" in schema_hint
            or "[ww][pp][rr][oo][jj]" in schema_hint
            or (normalized_field == "path" and "project" in schema_hint)
        )
        suffix = ".wproj" if is_project else ".dat"
        return str(PROBE_IO_ROOT / f"{normalized_field or 'path'}{suffix}")
    return None


@dataclass(slots=True)
class ProgramCallClient:
    result: Any
    calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = field(default_factory=list)

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        return self.result


@dataclass(slots=True)
class ProgramTopicHandler:
    unsubscribe_count: int = 0

    def unsubscribe(self) -> bool:
        self.unsubscribe_count += 1
        return True


@dataclass(slots=True)
class ProgramTopicClient:
    payload: Any
    subscriptions: list[str] = field(default_factory=list)
    handler: ProgramTopicHandler = field(default_factory=ProgramTopicHandler)

    def subscribe(
        self,
        uri: str,
        callback: Callable[..., None],
        options: Mapping[str, Any] | None = None,
    ) -> ProgramTopicHandler:
        del options
        self.subscriptions.append(uri)
        callback(self.payload)
        return self.handler
