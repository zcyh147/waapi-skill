"""Bind source-control file scopes to exact live object identities and accessors."""
from __future__ import annotations

from typing import Any, Callable, Mapping
from pathlib import Path
import re

from .filesystem_security import path_is_link_or_reparse
from .host_paths import localize_waapi_host_path

from .business_declarations import normalize_live_object_identity
from .identity_limits import MULTI_IDENTITY_READ_MAX_IDS

MAX_SOURCE_CONTROL_OBJECT_SCOPES = min(64, MULTI_IDENTITY_READ_MAX_IDS)
GET = "ak.wwise.core.object.get"
_GUID = re.compile(r"^\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}$")
_IDENTITY = ("id", "name", "type", "path")
SCOPES = {"containing-file": "filePath", "original-media": "originalFilePath"}
_FILE_URIS = frozenset("ak.wwise.core.sourceControl." + name for name in
                       ("add", "checkOut", "commit", "delete", "getStatus", "revert", "move"))
Read = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]


def validate_object_file_binding(operation: str, value: Any) -> list[dict[str, Any]]:
    if operation not in _FILE_URIS or not isinstance(value, Mapping) or set(value) not in ({"objects"}, {"objects", "moves"}):
        raise ValueError("Object-file binding belongs only to disclosed source-control file actions")
    if "moves" in value and operation != "ak.wwise.core.sourceControl.move":
        raise ValueError("Move associations belong only to sourceControl.move")
    rows = value["objects"]
    keys = {"id", "name", "type", "path", "scope", "file_path"}
    minimum = 0 if operation == "ak.wwise.core.sourceControl.move" and "moves" in value else 1
    if not isinstance(rows, list) or not minimum <= len(rows) <= MAX_SOURCE_CONTROL_OBJECT_SCOPES:
        raise ValueError("Object-file binding requires a bounded object scope list; only sealed move rows may have no object endpoints")
    result = []
    seen = set()
    for row in rows:
        sound_scope = isinstance(row, Mapping) and row.get("scope") == "sound-original-media"
        if sound_scope:
            _validate_sound_row(row)
        elif not isinstance(row, Mapping) or set(row) != keys or row.get("scope") not in SCOPES:
            raise ValueError("Object-file binding has unknown fields or scope")
        identity = normalize_live_object_identity(row)
        if row["scope"] == "original-media" and identity.object_type != "AudioFileSource":
            raise ValueError("Original-media scope requires one exact AudioFileSource; select a disclosed Sound source/language scope for Sound")
        path = row["file_path"]
        if not isinstance(path, str) or not path or "\x00" in path or len(path.encode("utf-8")) > 4096:
            raise ValueError("Object-file binding requires an observed bounded native file path")
        key = (identity.object_id, row["scope"], *(
            (row["media_selection"]["mode"], row["media_selection"]["language"], row["source"]["id"])
            if sound_scope else ()))
        if key in seen:
            raise ValueError("Object-file scopes must be distinct")
        seen.add(key)
        result.append({**dict(row), "id": identity.object_id})
    if "moves" in value:
        from .source_control_object_moves import validate_move_binding
        validate_move_binding(value, result)
    return result


def _reference(value: Any) -> str:
    object_id = value.get("id") if isinstance(value, Mapping) else None
    if not isinstance(object_id, str) or not _GUID.fullmatch(object_id):
        raise ValueError("Sound media requires an observed canonical reference GUID")
    return object_id.upper()


def _identity(row: Mapping[str, Any]) -> dict[str, Any]:
    identity = normalize_live_object_identity(row)
    return {"id": identity.object_id, "name": identity.name, "type": identity.object_type, "path": identity.path}


def _exact_rows(ids: list[str], *, fields: list[str], read: Read, language: str | None = None) -> dict[str, Mapping[str, Any]]:
    unique = list(dict.fromkeys(ids))
    options = {"return": fields, **({"language": language} if language is not None else {})}
    result = read(GET, {"from": {"id": unique}}, options)
    rows = result.get("return") if isinstance(result, Mapping) else None
    if not isinstance(rows, list) or len(rows) != len(unique):
        raise ValueError("Object-file readback must contain every exact GUID once")
    by_id = {}
    for row in rows:
        identity = normalize_live_object_identity(row)
        if identity.object_id not in unique or identity.object_id in by_id:
            raise ValueError("Object-file readback contains duplicate or extra GUIDs")
        by_id[identity.object_id] = row
    return by_id


def _language_matches(requested: str, actual: Any) -> bool:
    if not isinstance(actual, Mapping):
        return False
    if "id" in actual and (not isinstance(actual["id"], str) or not _GUID.fullmatch(actual["id"])):
        return False
    if "name" in actual and not isinstance(actual["name"], str):
        return False
    return (str(actual.get("id", "")).upper() == requested.upper() if _GUID.fullmatch(requested)
            else actual.get("name") == requested)


def _file_name(path: str) -> str:
    return Path(localize_waapi_host_path(path)).name


def _validate_sound_row(row: Mapping[str, Any]) -> None:
    expected = {"id", "name", "type", "path", "scope", "file_path", "media_selection", "source", "active_source", "active_file_path"}
    selection = row.get("media_selection")
    if isinstance(selection, Mapping) and selection.get("mode") != "active":
        expected -= {"active_source", "active_file_path"}
    if set(row) != expected or row.get("type") != "Sound" or not isinstance(selection, Mapping) or set(selection) != ({"mode", "language", "source"} if selection.get("mode") == "source" else {"mode", "language"}):
        raise ValueError("Sound media binding requires an exact Sound and a closed source/language selection")
    language = selection["language"]
    if selection["mode"] not in {"active", "language", "source"} or not isinstance(language, str) or not language or len(language.encode("utf-8")) > 4096:
        raise ValueError("Select an explicit language name or GUID and disclosed Sound source mode")
    source = row["source"]
    if not isinstance(source, Mapping) or set(source) != {*_IDENTITY, "parent", "language", "file_name"}:
        raise ValueError("Sound media requires exact source identity, parent, language and filename proof")
    source_identity = normalize_live_object_identity(source)
    if (isinstance(source["parent"], Mapping) and "name" in source["parent"] and source["parent"]["name"] != row["name"]
        or selection["mode"] == "active" and isinstance(row["active_source"], Mapping)
        and "name" in row["active_source"] and row["active_source"]["name"] != source_identity.name):
        raise ValueError("Sound/source reference names disagree with exact live identities")
    if selection["mode"] == "source" and _identity(selection["source"]) != _identity(source):
        raise ValueError("The explicitly bound source identity changed")
    if (source_identity.object_type != "AudioFileSource" or _reference(source["parent"]) != str(row["id"]).upper()
        or not _language_matches(language, source["language"]) or source["file_name"] != _file_name(row["file_path"])
        or (selection["mode"] == "active" and (
            not _active_matches(row["active_source"], source)
            or localize_waapi_host_path(row["active_file_path"]) != localize_waapi_host_path(row["file_path"])))):
        raise ValueError("Sound/source parent, language, active identity or original filename relationship is unproved")


def _observed_language(value: Any, *, read: Read) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("AudioFileSource readback omitted its language reference")
    language = dict(value)
    if "id" in language:
        language["id"] = _reference(language)
    if "name" not in language and "id" in language:
        identity = _exact_rows([language["id"]], fields=list(_IDENTITY), read=read)[language["id"]]
        if identity.get("type") != "Language":
            raise ValueError("AudioFileSource language reference does not resolve to Language")
        language["name"] = identity["name"]
    if not isinstance(language.get("name"), str) or not language["name"]:
        raise ValueError("AudioFileSource language reference is incomplete")
    return language


def _language_source(sound_id: str, language: str, *, read: Read, name: str | None = None) -> str:
    result = read(GET, {"waql": f'from object "{sound_id}" select children take {MAX_SOURCE_CONTROL_OBJECT_SCOPES + 1}'},
                  {"return": [*_IDENTITY, "parent", "audioSource:language"], "language": language})
    rows = result.get("return") if isinstance(result, Mapping) else None
    if not isinstance(rows, list) or len(rows) > MAX_SOURCE_CONTROL_OBJECT_SCOPES:
        raise ValueError("Sound source discovery exceeded its bounded child limit")
    seen, selected = set(), []
    for row in rows:
        identity = _identity(row)
        if identity["id"] in seen or _reference(row.get("parent")) != sound_id:
            raise ValueError("Sound source discovery returned duplicate or unrelated children")
        seen.add(identity["id"])
        if identity["type"] == "AudioFileSource" and (name is None or identity["name"] == name):
            actual = _observed_language(row.get("audioSource:language"), read=read)
            if _language_matches(language, actual):
                selected.append(identity["id"])
    if len(selected) != 1:
        raise ValueError("Sound requires exactly one AudioFileSource in the explicit language; select a bound source for ambiguous languages")
    return selected[0]


def _active_matches(reference: Any, source: Mapping[str, Any]) -> bool:
    if not isinstance(reference, Mapping) or not reference:
        return False
    if "id" in reference and _reference(reference) != source["id"]:
        return False
    if "name" in reference and reference["name"] != source["name"]:
        return False
    return "id" in reference or isinstance(reference.get("name"), str) and bool(reference["name"])


def _active_source_id(sound: Mapping[str, Any], language: str, *, read: Read) -> str:
    reference = sound.get("activeSource")
    if isinstance(reference, Mapping) and "id" in reference:
        return _reference(reference)
    name = reference.get("name") if isinstance(reference, Mapping) else None
    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 4096:
        raise ValueError("Active source reference requires an observed GUID or exact bounded source name")
    return _language_source(_identity(sound)["id"], language, read=read, name=name)


def _observe_sound_file(expected: Mapping[str, Any], selection: Mapping[str, Any], *, read: Read) -> dict[str, Any]:
    language, mode = selection.get("language"), selection.get("mode")
    if mode not in {"active", "language", "source"} or not isinstance(language, str) or not language or len(language.encode()) > 4096:
        raise ValueError("Sound media requires the disclosed source mode and explicit language")
    fields = [*_IDENTITY, "activeSource", "originalFilePath"] if mode == "active" else list(_IDENTITY)
    sound = _exact_rows([expected["id"]], fields=fields, read=read, language=language)[expected["id"]]
    if _identity(sound) != _identity(expected) or sound.get("type") != "Sound":
        raise ValueError("The bound Sound identity changed before its source file was resolved")
    source_id = (_active_source_id(sound, language, read=read) if mode == "active" else
                 _identity(selection["source"])["id"] if mode == "source" else
                 _language_source(expected["id"], language, read=read))
    source = _exact_rows([source_id], fields=[*_IDENTITY, "parent", "audioSource:language", "originalFilePath"], read=read, language=language)[source_id]
    path = source.get("originalFilePath")
    if not isinstance(path, str) or not path:
        raise ValueError("Selected source original file accessor is missing in the explicit language view")
    source_proof = {**_identity(source), "parent": source.get("parent"),
                    "language": _observed_language(source.get("audioSource:language"), read=read), "file_name": _file_name(path)}
    row = {**_identity(sound), "scope": "sound-original-media", "file_path": path,
           "media_selection": dict(selection), "source": source_proof}
    if mode == "active":
        if not isinstance(sound.get("originalFilePath"), str):
            raise ValueError("Sound original file accessor is missing in the explicit language view")
        row.update(active_source=dict(sound["activeSource"]), active_file_path=sound["originalFilePath"])
    _validate_sound_row(row)
    return row


def observe_object_file_binding(operation: str, value: Any, *, read: Read) -> dict[str, Any]:
    expected = validate_object_file_binding(operation, value)
    direct = [row for row in expected if row["scope"] != "sound-original-media"]
    by_id = (_exact_rows([row["id"] for row in direct],
        fields=[*_IDENTITY, *dict.fromkeys(SCOPES[row["scope"]] for row in direct)], read=read) if direct else {})
    observed = []
    for expected_row in expected:
        if expected_row["scope"] == "sound-original-media":
            observed.append(_observe_sound_file(expected_row, expected_row["media_selection"], read=read))
            continue
        row = by_id[expected_row["id"]]
        accessor = SCOPES[expected_row["scope"]]
        if accessor not in row:
            raise ValueError("Object-file readback omitted its exact file accessor")
        observed.append({**_identity(row), "scope": expected_row["scope"], "file_path": row[accessor]})
    binding = {"objects": observed, **({"moves": value["moves"]} if "moves" in value else {})}
    validate_object_file_binding(operation, binding)
    return binding


def _bound_identity(session: Any, handle: str) -> dict[str, Any]:
    bound = session.handles.resolve_object(handle)
    return {"id": bound.object_id, "name": bound.name, "type": bound.object_type, "path": bound.path}


def capture_object_file_binding(operation: str, session: Any, selections: Any, *, read: Read) -> dict[str, Any]:
    if not isinstance(selections, list) or not 1 <= len(selections) <= MAX_SOURCE_CONTROL_OBJECT_SCOPES:
        raise ValueError("Select between one and the disclosed maximum exact object-file scopes")
    prepared = []
    for selection in selections:
        if not isinstance(selection, Mapping) or "handle" not in selection or "scope" not in selection:
            raise ValueError("Select only a bound Object Handle and disclosed file scope")
        expected = {**_bound_identity(session, selection["handle"]), "scope": selection["scope"], "file_path": "pending-live-read"}
        if selection["scope"] == "sound-original-media":
            allowed = {"handle", "scope", "mode", "language"}
            if selection.get("mode") == "source":
                allowed.add("source_handle")
            if set(selection) != allowed:
                raise ValueError("Select only disclosed Sound source/language scope fields")
            media = {key: selection[key] for key in ("mode", "language")}
            if selection.get("mode") == "source":
                media["source"] = _bound_identity(session, selection["source_handle"])
            prepared.append((expected, media))
        elif set(selection) == {"handle", "scope"}:
            prepared.append((expected, None))
        else:
            raise ValueError("Select only disclosed object-file scope fields")
    direct = [expected for expected, media in prepared if media is None]
    direct_rows = (iter(observe_object_file_binding(operation, {"objects": direct}, read=read)["objects"]) if direct else iter(()))
    observed = []
    for expected, media in prepared:
        row = _observe_sound_file(expected, media, read=read) if media is not None else next(direct_rows)
        if _identity(expected) != _identity(row):
            raise ValueError("The selected Object Handle changed before its file scope was bound")
        observed.append(row)
    binding = {"objects": observed}
    validate_object_file_binding(operation, binding)
    return binding


def observe_bound_file_state(operation: str, binding: Any) -> list[dict[str, Any]]:
    """Bind ordinary local file identity; this does not prove provider state."""
    rows = validate_object_file_binding(operation, binding)
    result = []
    seen = set()
    paths = [row["file_path"] for row in rows]
    if isinstance(binding, Mapping) and "moves" in binding:
        paths.extend(row[side + "_path"] for row in binding["moves"] for side in ("source", "destination"))
    for file_path in paths:
        candidate = Path(localize_waapi_host_path(file_path))
        if not candidate.is_absolute():
            raise ValueError("An observed source-control file must be absolute for this host")
        for component in (candidate, *candidate.parents):
            try:
                metadata = component.lstat()
            except FileNotFoundError:
                continue
            if path_is_link_or_reparse(component, metadata=metadata):
                raise ValueError("The bound source-control file path contains a link or reparse point")
        path = candidate.resolve(strict=False)
        if str(path) in seen:
            continue
        seen.add(str(path))
        if not path.exists():
            result.append({"path": str(path), "exists": False})
            continue
        if not path.is_file():
            raise ValueError("The bound source-control path is not an ordinary file")
        stat = path.stat()
        result.append({"path": str(path), "exists": True, "device": stat.st_dev, "inode": stat.st_ino,
                       "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "mode": stat.st_mode})
    return result
