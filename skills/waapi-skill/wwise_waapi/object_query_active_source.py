"""Bounded same-view source identity proof for the 2021 file-backed query lane."""
from __future__ import annotations

from typing import Any, Callable, Mapping
from uuid import UUID

from .builders.query import MAX_QUERY_TAKE, build_object_get_query
from .business_declarations import normalize_live_object_identity
from .canonical import canonical_sha256
from .host_paths import HostPathError, parse_absolute_host_path
from .metadata_catalog import ObjectTypeCatalogStore


class ActiveSourceQueryError(ValueError):
    def __init__(self, code: str, message: str, *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


IDENTITY = ("id", "name", "type", "path")
SOURCE_FACTS = (*IDENTITY, "classId", "parent", "originalWavFilePath", "audioSource:language")


def _fail(code, message):
    raise ActiveSourceQueryError(code, message)


def _class_matches(value, expected):
    return type(value) is int and 0 < value <= 0xFFFFFFFF and value == expected


def _guid(value):
    if isinstance(value, Mapping):
        value = value.get("id")
    try:
        parsed = UUID(value) if isinstance(value, str) and len(value) == 38 and value.startswith("{") and value.endswith("}") else None
    except ValueError:
        parsed = None
    if parsed is None or not parsed.int or value.casefold() != ("{" + str(parsed) + "}"):
        _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "A canonical nonzero GUID is required.")
    return "{" + str(parsed).upper() + "}"


def _identity(row):
    identity = {key: row.get(key) for key in IDENTITY}
    identity["id"] = _guid(identity["id"])
    if any(not isinstance(identity[key], str) or not identity[key] for key in IDENTITY):
        _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "Object identity is incomplete.")
    if identity["type"] != "Project":
        try:
            actual = normalize_live_object_identity(row)
        except ValueError as exc:
            _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", str(exc))
        identity.update(name=actual.name, type=actual.object_type, path=actual.path)
    return identity


def _path(value):
    try:
        return parse_absolute_host_path(value).comparison_key()
    except HostPathError as exc:
        _fail("ACTIVE_SOURCE_SELECTION_UNRESOLVED", "A complete original file path is required: " + str(exc))


def _file_path(row):
    if "originalWavFilePath" not in row or row["originalWavFilePath"] is None:
        raise ActiveSourceQueryError("ACTIVE_SOURCE_SELECTION_UNRESOLVED", "The original path was not observed.",
            details={"field": "originalWavFilePath", "presence": "absent" if "originalWavFilePath" not in row else "null"})
    return _path(row["originalWavFilePath"])


def _sound_facts(row):
    result = {**row, **_identity(row), "parent": _guid(row.get("parent")),
              "originalWavFilePath": _file_path(row)}
    if "audioSource:language" in row:
        reference = row["audioSource:language"]
        if not isinstance(reference, Mapping) or not isinstance(reference.get("name"), str):
            _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "The Sound source language is malformed.")
        result["audioSource:language"] = {"id": _guid(reference), "name": reference["name"]}
    return result


def resolve_2021_active_source(*, read: Callable, selector: Mapping[str, str], platform: str,
                               language: str, return_fields: tuple[str, ...], live_info: Mapping[str, Any],
                               project_before: Mapping[str, Any] | None = None):
    """Return the unchanged requested Sound row plus an independently joined reference.

    No row order, import return value or serialized project file is an oracle.
    Repeat observations detect changes; they are not an atomic project lock.
    """
    def rows(*, maximum=MAX_QUERY_TAKE, **kwargs):
        preview = build_object_get_query(version="2021.1", **kwargs)
        result = read(preview.envelope.uri, preview.envelope.args, preview.envelope.options)
        values = result.get("return") if isinstance(result, Mapping) else None
        if not isinstance(values, list) or len(values) > maximum or any(not isinstance(row, Mapping) for row in values):
            _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "The bounded native object page is malformed.")
        ids = [_guid(row.get("id")) for row in values]
        if len(ids) != len(set(ids)):
            _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "The native page contains duplicate GUIDs.")
        return values, preview

    def scope(kind, requested):
        values, _ = rows(type=kind, take=MAX_QUERY_TAKE, return_fields=IDENTITY)
        if len(values) == MAX_QUERY_TAKE:
            _fail("ACTIVE_SOURCE_OBSERVATION_INCOMPLETE", "The view catalog reached its result fence.")
        matches = [row for row in values if row.get("type") == kind and
                   (row.get("name") == requested or str(row.get("id", "")).casefold() == requested.casefold())]
        if len(matches) != 1:
            _fail("ACTIVE_SOURCE_SELECTION_UNRESOLVED", "The explicit " + kind + " view is not unique.")
        return _identity(matches[0])

    selected_platform, selected_language = scope("Platform", platform), scope("Language", language)
    view = {"platform": selected_platform["id"], "language": selected_language["id"]}
    types_result = read("ak.wwise.core.object.getTypes", {}, {})
    catalog = types_result.get("return") if isinstance(types_result, Mapping) else None
    if not isinstance(catalog, list) or any(not isinstance(row, Mapping) for row in catalog):
        _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "The live class catalog is malformed.")
    pinned = ObjectTypeCatalogStore().load("2021.1")
    classes = {}
    for name in ("Sound", "AudioSource"):
        expected = pinned.by_name(name)
        matching = [row for row in catalog if expected and row.get("classId") == expected.class_id]
        if (len(matching) != 1 or any(matching[0].get(key) != value for key, value in expected.as_dict().items())
                or not _class_matches(matching[0]["classId"], expected.class_id)):
            _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "Actual source classes require the pinned semantic identity and matching live catalog.")
        classes[name] = expected.class_id

    def project():
        values, _ = rows(type="Project", take=1, return_fields=(*IDENTITY, "filePath"), maximum=1)
        if len(values) != 1 or values[0].get("type") != "Project" or not isinstance(values[0].get("filePath"), str):
            _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "Project identity cannot be bound.")
        return {**_identity(values[0]), "filePath": values[0]["filePath"]}

    if project_before is not None and (project_before.get("type") != "Project"
            or not isinstance(project_before.get("filePath"), str) or not project_before["filePath"]):
        _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "The already observed project identity is incomplete.")
    before_project = ({**_identity(project_before), "filePath": project_before["filePath"]}
                      if project_before is not None else project())
    fields = tuple(dict.fromkeys((*return_fields, *SOURCE_FACTS)))
    before, preview = rows(**selector, return_fields=fields, maximum=1, **view)
    if not before:
        return [], preview, {"method": "unique_same_view_original_path", "sound_count": 0}, before_project
    owner = before[0]
    identity = _identity(owner)
    if identity["type"] != "Sound" or not _class_matches(owner.get("classId"), classes["Sound"]):
        _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "Active-source derivation requires an actual class-proven Sound.")
    if "object_id" in selector and _guid(selector["object_id"]) != identity["id"] or "path" in selector and selector["path"] != identity["path"]:
        _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "The exact Sound selector returned another object.")
    before_sound = _sound_facts(owner)
    wanted_path = before_sound["originalWavFilePath"]

    def children():
        values, _ = rows(object_id=identity["id"], select=("children",), take=MAX_QUERY_TAKE,
                         return_fields=SOURCE_FACTS, **view)
        if len(values) == MAX_QUERY_TAKE:
            _fail("ACTIVE_SOURCE_OBSERVATION_INCOMPLETE", "The complete child set reached its result fence.")
        facts = {}
        for row in values:
            actual = _identity(row)
            if _guid(row.get("parent")) != identity["id"]:
                _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "A source child belongs to another parent.")
            if actual["path"] != identity["path"] + "\\" + actual["name"]:
                _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "A source child's actual hierarchy path differs from its direct parent.")
            if actual["type"] != "AudioFileSource":
                _fail("ACTIVE_SOURCE_SELECTION_UNRESOLVED", "Non-file source selection remains unresolved.")
            if not _class_matches(row.get("classId"), classes["AudioSource"]):
                _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "A source child's actual class differs from its semantic class.")
            source_language = row.get("audioSource:language")
            if not isinstance(source_language, Mapping) or not isinstance(source_language.get("name"), str):
                _fail("ACTIVE_SOURCE_INVALID_OBSERVATION", "The actual source language is incomplete.")
            language_id = _guid(source_language)
            facts[actual["id"]] = {**actual, "classId": row["classId"], "parent": identity["id"],
                "language": {"id": language_id, "name": source_language["name"]},
                "original_path": _file_path(row)}
        return facts

    before_children = children()
    matching = [row for row in before_children.values() if row["original_path"] == wanted_path
                and row["language"] == {"id": selected_language["id"], "name": selected_language["name"]}]
    if len(matching) != 1:
        _fail("ACTIVE_SOURCE_SELECTION_UNRESOLVED", "The selected Sound path does not identify one exact language-matching source.")
    if children() != before_children:
        _fail("ACTIVE_SOURCE_OBSERVATION_CHANGED", "Source membership or selection facts changed during observation.")
    after, _ = rows(object_id=identity["id"], return_fields=fields, maximum=1, **view)
    if len(after) != 1 or _sound_facts(after[0]) != before_sound or project() != before_project:
        _fail("ACTIVE_SOURCE_OBSERVATION_CHANGED", "The Sound or project changed during observation.")
    after_info = read("ak.wwise.core.getInfo", {}, {})
    if any(after_info.get(key) != live_info.get(key) for key in ("sessionId", "processId", "version", "isCommandLine")):
        _fail("ACTIVE_SOURCE_OBSERVATION_CHANGED", "The Wwise host changed during observation.")
    selected = matching[0]
    return [{**owner, "active_source": {"id": selected["id"], "name": selected["name"]}}], preview, {
        "method": "unique_same_view_original_path", "platform": selected_platform, "language": selected_language,
        "source_count": len(before_children), "complete": True, "stable_observation": True,
        "observation_sha256": canonical_sha256({"project": before_project, "sound": before_sound,
            "children": before_children, "view": view}),
        "atomic": False, "native_absence_proven": False,
    }, before_project
