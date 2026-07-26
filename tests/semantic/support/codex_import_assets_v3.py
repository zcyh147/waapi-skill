"""Deterministic file/request materializer for the ten v3 core import cases."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .codex_eval_bundle_v3 import OnlineScenario


OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
IMPORT_ASSET_CONTRACT = "waapi-skill.import-eval-assets/v2"
IMPORT_APIS = frozenset(
    {"ak.wwise.core.audio.import", "ak.wwise.core.audio.importTabDelimited"}
)
CANONICAL_WWISE_LANGUAGE = {
    "Chinese": "Chinese(PRC)",
    "English": "English(US)",
    "Japanese": "Japanese",
    "SFX": "SFX",
}
_HEADER_TO_ROW_KEY = {
    "Object Path": "object_path",
    "Object Type": "object_type",
    "OriginalsSubFolder": "originals_subfolder",
    "Notes": "notes",
    "Audio Source Notes": "audio_source_notes",
}


class ImportAssetMaterializationError(ValueError):
    """A reviewed import asset specification cannot be materialized safely."""


@dataclass(frozen=True, slots=True)
class MaterializedFile:
    key: str
    path: Path
    present: bool
    size: int | None
    sha256: str | None


@dataclass(frozen=True, slots=True)
class MaterializedImportCase:
    scenario_id: str
    visible_values: Mapping[str, str]
    operation_requests: tuple[Mapping[str, Any], ...]
    source_files: tuple[MaterializedFile, ...]
    pre_state_files: tuple[MaterializedFile, ...]
    tab_files: tuple[MaterializedFile, ...]
    expected_rows: tuple[Mapping[str, Any], ...]
    expected_primary_dispatch_count: int


def materialize_import_case(
    scenario: OnlineScenario,
    *,
    version: str,
    asset_root: Path,
) -> MaterializedImportCase:
    """Create immutable WAV/TSV inputs and closed named-operation requests."""

    if scenario.api not in IMPORT_APIS:
        raise ImportAssetMaterializationError(
            f"unsupported import scenario API: {scenario.api}"
        )
    if version not in scenario.versions:
        raise ImportAssetMaterializationError(
            f"{scenario.id} does not support Wwise {version}"
        )
    spec = scenario.fixture.get("asset_spec")
    if not isinstance(spec, Mapping) or spec.get("contract") != IMPORT_ASSET_CONTRACT:
        raise ImportAssetMaterializationError(
            f"{scenario.id} lacks the reviewed import asset contract"
        )
    root = Path(asset_root).expanduser().resolve(strict=False)
    if root.exists():
        raise ImportAssetMaterializationError(
            f"import asset root already exists and cannot be reused: {root}"
        )
    source_root = root / "sources"
    pre_state_root = root / "pre-state"
    tab_root = root / "tables"
    for path in (source_root, pre_state_root, tab_root):
        path.mkdir(parents=True, exist_ok=False)

    sources = _materialize_sources(spec["sources"], source_root)
    pre_state = _materialize_pre_state(spec["pre_state_sources"], pre_state_root)
    source_by_key = {item.key: item for item in sources}
    rows = tuple(dict(row) for row in _mapping_rows(spec["rows"], field="rows"))

    if scenario.api == "ak.wwise.core.audio.import":
        requests = (
            _operation_request(
                version,
                "audio.import",
                {
                    "imports": [
                        _audio_import_row(row, source_by_key=source_by_key)
                        for row in rows
                    ],
                    "import_operation": _required_string(
                        spec.get("audio_import_operation"),
                        field="audio_import_operation",
                    ),
                },
            ),
        )
        visible_values = {
            "media_directory": str(source_root),
            "import_rows": _visible_json(requests[0]["arguments"]["imports"]),
        }
        tab_files: tuple[MaterializedFile, ...] = ()
    else:
        tab_files = _materialize_tables(
            spec["tsv"],
            rows=rows,
            source_by_key=source_by_key,
            tab_root=tab_root,
        )
        tab_by_name = {item.key: item for item in tab_files}
        location = _required_string(spec.get("import_location"), field="import_location")
        requests = tuple(
            _operation_request(
                version,
                "audio.importTabDelimited",
                {
                    "import_file": str(tab_by_name[_required_string(table["name"], field="tsv.name")].path),
                    "import_location": {"kind": "path", "value": location},
                    "import_language": canonical_wwise_language(
                        _required_string(table["language"], field="tsv.language")
                    ),
                    "import_operation": _required_string(
                        table["import_operation"], field="tsv.import_operation"
                    ),
                },
            )
            for table in _mapping_rows(spec["tsv"], field="tsv")
        )
        if len(requests) == 1:
            visible_values = {
                "import_file": requests[0]["arguments"]["import_file"],
                "import_location": location,
            }
        else:
            visible_values = {
                "language_import_files": _visible_json(
                    [
                        {
                            "file": request["arguments"]["import_file"],
                            "language": request["arguments"]["import_language"],
                            "import_operation": request["arguments"]["import_operation"],
                        }
                        for request in requests
                    ]
                ),
                "import_location": location,
            }

    expected_visible = {item.name for item in scenario.visible_inputs}
    if set(visible_values) != expected_visible:
        raise ImportAssetMaterializationError(
            f"{scenario.id} visible input mismatch; expected={sorted(expected_visible)} "
            f"actual={sorted(visible_values)}"
        )
    if len(requests) != scenario.primary_dispatch.count and scenario.primary_dispatch.count != 0:
        raise ImportAssetMaterializationError(
            f"{scenario.id} request count does not match the reviewed primary dispatch count"
        )
    # The missing-file refusal still owns one preview request whose validation
    # must fail before any WAAPI business dispatch.
    if scenario.primary_dispatch.count == 0 and len(requests) != 1:
        raise ImportAssetMaterializationError(
            f"{scenario.id} zero-dispatch refusal must have one preflight request"
        )

    return MaterializedImportCase(
        scenario_id=scenario.id,
        visible_values=visible_values,
        operation_requests=requests,
        source_files=sources,
        pre_state_files=pre_state,
        tab_files=tab_files,
        expected_rows=rows,
        expected_primary_dispatch_count=scenario.primary_dispatch.count,
    )


def canonical_wwise_language(value: str) -> str:
    try:
        return CANONICAL_WWISE_LANGUAGE[value]
    except KeyError as exc:
        raise ImportAssetMaterializationError(
            f"import fixture uses an unreviewed language alias: {value!r}"
        ) from exc


def _materialize_sources(
    rows: Any,
    root: Path,
) -> tuple[MaterializedFile, ...]:
    materialized: list[MaterializedFile] = []
    for row in _mapping_rows(rows, field="sources"):
        key = _required_string(row.get("source_key"), field="sources.source_key")
        relative = _safe_relative(row.get("relative_path"), field="sources.relative_path")
        path = root / relative
        presence = _required_string(row.get("presence"), field="sources.presence")
        if presence == "present":
            _write_pcm_wav(
                path,
                duration_ms=_positive_int(row.get("duration_ms"), field="sources.duration_ms"),
                frequency_hz=_positive_int(row.get("frequency_hz"), field="sources.frequency_hz"),
            )
            materialized.append(_file_row(key, path, present=True))
        elif presence == "absent":
            if row.get("duration_ms") is not None or row.get("frequency_hz") is not None:
                raise ImportAssetMaterializationError(
                    f"absent source {key} cannot declare signal fields"
                )
            materialized.append(_file_row(key, path, present=False))
        else:
            raise ImportAssetMaterializationError(
                f"source {key} has unsupported presence {presence!r}"
            )
    _require_unique([item.key for item in materialized], field="source keys")
    return tuple(materialized)


def _materialize_pre_state(
    rows: Any,
    root: Path,
) -> tuple[MaterializedFile, ...]:
    materialized: list[MaterializedFile] = []
    for index, row in enumerate(_mapping_rows(rows, field="pre_state_sources")):
        key = _required_string(
            row.get("media_sha256_key"), field="pre_state_sources.media_sha256_key"
        )
        relative = _safe_relative(
            row.get("relative_path"), field="pre_state_sources.relative_path"
        )
        path = root / relative
        _write_pcm_wav(
            path,
            duration_ms=_positive_int(
                row.get("duration_ms"), field=f"pre_state_sources[{index}].duration_ms"
            ),
            frequency_hz=_positive_int(
                row.get("frequency_hz"), field=f"pre_state_sources[{index}].frequency_hz"
            ),
        )
        materialized.append(_file_row(key, path, present=True))
    _require_unique([item.key for item in materialized], field="pre-state keys")
    return tuple(materialized)


def _materialize_tables(
    tables: Any,
    *,
    rows: Sequence[Mapping[str, Any]],
    source_by_key: Mapping[str, MaterializedFile],
    tab_root: Path,
) -> tuple[MaterializedFile, ...]:
    result: list[MaterializedFile] = []
    for table in _mapping_rows(tables, field="tsv"):
        name = _required_string(table.get("name"), field="tsv.name")
        relative = _safe_relative(name, field="tsv.name")
        path = tab_root / relative
        headers = tuple(
            _required_string(value, field="tsv.headers")
            for value in _sequence(table.get("headers"), field="tsv.headers")
        )
        selected = sorted(
            (row for row in rows if row.get("tsv_name") == name),
            key=lambda row: _positive_int(row.get("tsv_row"), field="rows.tsv_row"),
        )
        if len(selected) != table.get("row_count"):
            raise ImportAssetMaterializationError(
                f"{name} row count does not match the reviewed table contract"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(
                handle,
                delimiter="\t",
                quoting=csv.QUOTE_MINIMAL,
                doublequote=True,
                lineterminator="\n",
            )
            writer.writerow(headers)
            for row in selected:
                writer.writerow(
                    [
                        _tab_cell(header, row=row, source_by_key=source_by_key)
                        for header in headers
                    ]
                )
        result.append(_file_row(name, path, present=True))
    _require_unique([item.key for item in result], field="TSV names")
    return tuple(result)


def _tab_cell(
    header: str,
    *,
    row: Mapping[str, Any],
    source_by_key: Mapping[str, MaterializedFile],
) -> str:
    if header == "Audio File":
        source_key = _required_string(row.get("source_key"), field="rows.source_key")
        try:
            cell = str(source_by_key[source_key].path)
        except KeyError as exc:
            raise ImportAssetMaterializationError(
                f"TSV row references unknown source {source_key!r}"
            ) from exc
    elif header == "Event":
        event = row.get("event")
        cell = (
            ""
            if event is None
            else _required_string(event.get("path"), field="rows.event.path")
        )
    else:
        key = _HEADER_TO_ROW_KEY.get(header)
        if key is None:
            raise ImportAssetMaterializationError(
                f"unsupported reviewed TSV header: {header!r}"
            )
        value = row.get(key)
        cell = "" if value is None else str(value)
    if any(separator in cell for separator in ("\t", "\r", "\n")):
        raise ImportAssetMaterializationError(
            f"TSV {header!r} cells cannot contain physical row or column separators"
        )
    return cell


def _audio_import_row(
    row: Mapping[str, Any],
    *,
    source_by_key: Mapping[str, MaterializedFile],
) -> dict[str, Any]:
    source_key = _required_string(row.get("source_key"), field="rows.source_key")
    try:
        source = source_by_key[source_key]
    except KeyError as exc:
        raise ImportAssetMaterializationError(
            f"audio.import row references unknown source {source_key!r}"
        ) from exc
    if not source.present:
        raise ImportAssetMaterializationError(
            "audio.import dispatch rows cannot reference intentionally absent sources"
        )
    request: dict[str, Any] = {
        "object_path": _required_string(row.get("object_path"), field="rows.object_path"),
        "audio_file": str(source.path),
        "object_type": _required_string(row.get("object_type"), field="rows.object_type"),
        "import_language": canonical_wwise_language(
            _required_string(row.get("language"), field="rows.language")
        ),
    }
    for source_name, request_name in (
        ("originals_subfolder", "originals_subfolder"),
        ("notes", "notes"),
        ("audio_source_notes", "audio_source_notes"),
    ):
        value = row.get(source_name)
        if value is not None:
            request[request_name] = str(value)
    event = row.get("event")
    if event is not None:
        request["event"] = {
            "path": _required_string(event.get("path"), field="rows.event.path"),
            "action": _required_string(event.get("action"), field="rows.event.action"),
        }
    return request


def _operation_request(
    version: str,
    operation: str,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": dict(arguments),
    }


def _write_pcm_wav(path: Path, *, duration_ms: int, frequency_hz: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 48_000
    frame_count = sample_rate * duration_ms // 1000
    if frame_count < 1:
        raise ImportAssetMaterializationError("deterministic WAV must contain at least one frame")
    with path.open("xb") as raw:
        with wave.open(raw, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            chunk = bytearray()
            for frame in range(frame_count):
                sample = int(
                    12_000
                    * math.sin(2.0 * math.pi * frequency_hz * frame / sample_rate)
                )
                chunk.extend(struct.pack("<h", sample))
            handle.writeframes(bytes(chunk))


def _file_row(key: str, path: Path, *, present: bool) -> MaterializedFile:
    if present:
        data = path.read_bytes()
        return MaterializedFile(
            key=key,
            path=path.resolve(strict=True),
            present=True,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
    if path.exists() or path.is_symlink():
        raise ImportAssetMaterializationError(
            f"intentionally absent input unexpectedly exists: {path}"
        )
    return MaterializedFile(
        key=key,
        path=path.resolve(strict=False),
        present=False,
        size=None,
        sha256=None,
    )


def _visible_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _mapping_rows(value: Any, *, field: str) -> tuple[Mapping[str, Any], ...]:
    rows = _sequence(value, field=field)
    if any(not isinstance(row, Mapping) for row in rows):
        raise ImportAssetMaterializationError(f"{field} must contain JSON objects")
    return tuple(rows)  # type: ignore[return-value]


def _sequence(value: Any, *, field: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ImportAssetMaterializationError(f"{field} must be a JSON array")
    return tuple(value)


def _required_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ImportAssetMaterializationError(f"{field} must be a non-empty string")
    return value


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ImportAssetMaterializationError(f"{field} must be a positive integer")
    return value


def _safe_relative(value: Any, *, field: str) -> Path:
    text = _required_string(value, field=field)
    path = Path(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ImportAssetMaterializationError(f"{field} must be a contained relative path")
    return path


def _require_unique(values: Sequence[str], *, field: str) -> None:
    if len(values) != len(set(values)):
        raise ImportAssetMaterializationError(f"{field} must be unique")


__all__ = [
    "CANONICAL_WWISE_LANGUAGE",
    "ImportAssetMaterializationError",
    "MaterializedFile",
    "MaterializedImportCase",
    "canonical_wwise_language",
    "materialize_import_case",
]
