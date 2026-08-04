"""Deterministic runtime contract for the five heavy Media Pool V3 cases.

This module is owned by the semantic runner, never by the evaluated model.  It
materializes byte-distinct WAV/iXML inputs, stages Project Originals only into
the disposable project copy, closes the documented User Database provisioning
shape, binds exact-case fields returned by ``mediaPool.getFields``, and builds a
model-hidden business oracle from independently parsed files plus a sealed live
index snapshot.

The custom-database path fails closed.  Audiokinetic's 2025.1 documentation
states that User Databases are local-user state and persist across projects.  A
case that needs one therefore remains BLOCKED until the runner supplies a sealed
round-trip proof for the exact Wwise build and launches Wwise with a disposable
HOME whose effective CrossOver prefix is also scenario-owned.  Deletion and
global-user-state restoration are checked again before such a case may pass.

The exact database object shape below comes from the installed official
``WwiseSDK-Windows.chm`` for Wwise 2025.1.7.9143, example
``ak_wwise_core_object_set_example_creating_a_media_pool_database.html``:

* parent ``\\Databases\\User Databases`` (fixed GUID below);
* child type ``MediaPoolDatabase``;
* list ``@Paths`` containing ``MediaPoolDatabasePath``;
* path property ``@Path``.

No Codex process, Wwise process, network client, arbitrary callback, or
model-authored request is accepted here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

from .codex_eval_bundle_v3 import OnlineScenario
from .codex_host_paths import (
    ReflectedHostPathError,
    parse_posix_absolute_path,
    parse_windows_drive_path,
)
from .codex_filesystem_security import path_is_link_or_reparse


VERSION = "2025.1"
MEDIA_POOL_GET_URI = "ak.wwise.core.mediaPool.get"
MEDIA_POOL_GET_FIELDS_URI = "ak.wwise.core.mediaPool.getFields"
OBJECT_SET_URI = "ak.wwise.core.object.set"
OBJECT_DELETE_URI = "ak.wwise.core.object.delete"
OBJECT_GET_URI = "ak.wwise.core.object.get"
MEDIA_POOL_FIXTURE_CONTRACT = "waapi-skill.media-pool-fixture/v1"
MEDIA_POOL_RUNTIME_CONTRACT = "waapi-skill.media-pool-runtime/v3"
REFERENCE_MATCH_SCAN_LIMIT = 1000
REFERENCE_MATCH_RESULT_CONTRACT = "waapi-skill.original-file-reference-match/v1"
CUSTOM_DATABASE_PROOF_CONTRACT = (
    "waapi-skill.media-pool-custom-db-roundtrip-proof/v1"
)
CUSTOM_DATABASE_CLEANUP_CONTRACT = (
    "waapi-skill.media-pool-custom-db-cleanup-proof/v1"
)
USER_DATABASES_PATH = r"\Databases\User Databases"
USER_DATABASES_GUID = "{8452BD49-9264-4A56-A3BB-047FA7F119BE}"
PROJECT_ORIGINALS_PATH = r"\Databases\Project Originals"
SUPPORTED_BUILD = "2025.1.7.9143"
MACOS_WWISE_WINE_PREFIX_RELATIVE = Path(
    "Library/Application Support/Wwise2019/Bottles/Wwise2019x64"
)
WINE_Z_DRIVE_TARGET = "/"
WINE_C_DRIVE_TARGET = "../drive_c"
MEDIA_POOL_CASE_IDS = tuple(
    f"VS25-F-MEDIAPOOL-GET-{index:02d}" for index in range(1, 6)
)
MEDIA_POOL_ORDERED_CASE_IDS = frozenset(
    {
        "VS25-F-MEDIAPOOL-GET-01",
        "VS25-F-MEDIAPOOL-GET-02",
        "VS25-F-MEDIAPOOL-GET-05",
    }
)
MEDIA_POOL_CLOSED_GROUP_REPORT_CASE_ID = "VS25-F-MEDIAPOOL-GET-03"

# Exact standard names are documented by the installed 2025.1.7 SDK.  iXML
# names are data-dependent, so Scene/Take are bound from the actual getFields
# result and never reconstructed with guessed capitalization.
STANDARD_FIELDS = MappingProxyType(
    {
        "name": "Filename",
        "duration": "WAV/Duration",
        "sample_rate": "WAV/Sample Rate",
        "bit_depth": "WAV/Bit Depth",
        "channels": "WAV/Channels",
    }
)
FIXED_RETURN_FIELDS = frozenset({"Path", "FileId", "Db"})
MEDIA_POOL_CANONICAL_RETURN_FIELDS = (
    "Path",
    "FileId",
    "Db",
    *STANDARD_FIELDS.values(),
)
MEDIA_POOL_FIELD_OPERATORS = frozenset(
    {
        "equals",
        "notEquals",
        "contains",
        "startsWith",
        "endsWith",
        "matchesRegex",
        "lessThan",
        "greaterThan",
        "lessThanOrEqual",
        "greaterThanOrEqual",
    }
)
MEDIA_POOL_POST_FILTER_OPERATORS = frozenset({"containsCaseSensitive"})
_FIELD_TOKEN_RE = re.compile(r"^\{media_pool_fields\.([a-z_]+)\}$")
_GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)


class MediaPoolRuntimeError(ValueError):
    """A Media Pool fixture, request, or proof left the reviewed boundary."""


@dataclass(frozen=True, slots=True)
class TreeFingerprint:
    root: Path
    exists: bool
    sha256: str
    file_count: int
    byte_count: int


@dataclass(frozen=True, slots=True)
class ParsedWav:
    sample_rate: int
    channels: int
    bit_depth: int
    frame_count: int
    duration_seconds: float
    data_size: int
    ixml: Mapping[str, str]
    file_size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class MediaDatabaseFixture:
    key: str
    wwise_path: str
    name: str
    kind: Literal["project_originals", "user_database"]
    source_root: Path


@dataclass(frozen=True, slots=True)
class MediaAsset:
    key: str
    database_key: str
    relative_path: PurePosixPath
    source_path: Path
    parsed: ParsedWav
    referenced_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MaterializedMediaPoolCase:
    contract: str
    scenario_id: str
    version: str
    asset_root: Path
    databases: tuple[MediaDatabaseFixture, ...]
    assets: tuple[MediaAsset, ...]
    request_template: Mapping[str, Any]
    expected_file_keys: tuple[str, ...]
    expected_candidate_file_keys: tuple[str, ...]
    expected_groups: Mapping[str, tuple[str, ...]]
    association_expectations: Mapping[str, tuple[str, ...]] | None
    source_fingerprint: TreeFingerprint

    @property
    def requires_custom_database(self) -> bool:
        return any(item.kind == "user_database" for item in self.databases)

    @property
    def excluded_file_keys(self) -> tuple[str, ...]:
        expected = set(self.expected_file_keys)
        return tuple(item.key for item in self.assets if item.key not in expected)

    def database(self, key: str) -> MediaDatabaseFixture:
        for item in self.databases:
            if item.key == key:
                return item
        raise MediaPoolRuntimeError(f"unknown Media Pool database key: {key}")

    def asset(self, key: str) -> MediaAsset:
        for item in self.assets:
            if item.key == key:
                return item
        raise MediaPoolRuntimeError(f"unknown Media Pool asset key: {key}")


@dataclass(frozen=True, slots=True)
class StagedMediaAsset:
    asset: MediaAsset
    indexed_host_path: Path


@dataclass(frozen=True, slots=True)
class StagedMediaPoolCase:
    materialized: MaterializedMediaPoolCase
    sandbox_project: Path
    owned_root: Path
    assets: tuple[StagedMediaAsset, ...]
    staged_fingerprint: TreeFingerprint

    def staged_asset(self, key: str) -> StagedMediaAsset:
        for item in self.assets:
            if item.asset.key == key:
                return item
        raise MediaPoolRuntimeError(f"unknown staged Media Pool asset key: {key}")


@dataclass(frozen=True, slots=True)
class WaapiCall:
    uri: str
    args: Mapping[str, Any]
    options: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "args": _plain(self.args),
            "options": _plain(self.options),
        }


@dataclass(frozen=True, slots=True)
class CustomDatabaseRoundTripProof:
    wwise_build: str
    evidence_path: Path
    evidence_sha256: str
    payload_shape_sha256: str
    host_mode: Literal["macos_wine", "native_windows"]


@dataclass(frozen=True, slots=True)
class MacOSWineCustomDatabaseHost:
    """Runner-owned host binding for Wwise Authoring through Wine."""

    launch_home: Path
    wine_prefix: Path


@dataclass(frozen=True, slots=True)
class NativeWindowsCustomDatabaseHost:
    """Runner-owned host binding for native Windows Wwise Authoring."""

    user_profile: Path
    appdata: Path
    local_appdata: Path


CustomDatabaseHost = MacOSWineCustomDatabaseHost | NativeWindowsCustomDatabaseHost


@dataclass(frozen=True, slots=True)
class CustomDatabaseIsolation:
    owned_root: Path
    host: CustomDatabaseHost
    real_account_state_root: Path
    global_user_state_before: TreeFingerprint
    round_trip_proof: CustomDatabaseRoundTripProof


@dataclass(frozen=True, slots=True)
class MediaPoolPreflight:
    scenario_id: str
    status: Literal["READY", "BLOCKED"]
    code: str
    reason: str
    create_calls: tuple[WaapiCall, ...]
    isolation: CustomDatabaseIsolation | None

    @property
    def ready(self) -> bool:
        return self.status == "READY"


@dataclass(frozen=True, slots=True)
class MediaPoolFieldBinding:
    available_fields: tuple[str, ...]
    by_concept: Mapping[str, str]

    def exact(self, concept: str) -> str:
        try:
            return self.by_concept[concept]
        except KeyError as exc:
            raise MediaPoolRuntimeError(
                f"Media Pool field concept was not bound: {concept}"
            ) from exc


@dataclass(frozen=True, slots=True)
class BoundMediaPoolRequest:
    scenario_id: str
    args: Mapping[str, Any]
    options: Mapping[str, Any]
    binding: MediaPoolFieldBinding
    post_filter: Mapping[str, Any] | None = None

    def gateway_argv(self) -> tuple[str, ...]:
        result = (
            "call",
            MEDIA_POOL_GET_URI,
            "--args-json",
            json.dumps(
                _plain(self.args),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "--options-json",
            json.dumps(
                _plain(self.options),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        if self.post_filter is not None:
            result = (
                *result,
                "--post-filter-json",
                json.dumps(
                    _plain(self.post_filter),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        return result


@dataclass(frozen=True, slots=True)
class SealedMediaRow:
    key: str
    path: str
    host_path: Path
    file_id: str
    db: Mapping[str, str]
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SemanticAnswerPlan:
    ordered_keys: tuple[str, ...]
    expected_groups: Mapping[str, tuple[str, ...]]
    referenced_keys: tuple[str, ...]
    unreferenced_keys: tuple[str, ...]
    excluded_keys: tuple[str, ...]
    max_results: int


@dataclass(frozen=True, slots=True)
class MediaReportRowExpectation:
    """Closed final-report identity for one sealed Media Pool row."""

    key: str
    filenames: tuple[str, ...]
    database: str
    path: str


@dataclass(frozen=True, slots=True)
class SealedMediaPoolOracle:
    scenario_id: str
    request: BoundMediaPoolRequest
    rows: tuple[SealedMediaRow, ...]
    expected_keys: tuple[str, ...]
    semantic_answer: SemanticAnswerPlan
    source_fingerprint: TreeFingerprint
    staged_fingerprint: TreeFingerprint
    candidate_keys: tuple[str, ...]

    def row(self, key: str) -> SealedMediaRow:
        for item in self.rows:
            if item.key == key:
                return item
        raise MediaPoolRuntimeError(f"unknown sealed Media Pool row key: {key}")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    ok: bool
    code: str
    details: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CustomDatabaseCleanupProof:
    contract: str
    scenario_id: str
    baseline_user_database_ids: tuple[str, ...]
    created_database_ids: Mapping[str, str]
    final_user_database_ids: tuple[str, ...]
    global_user_state_after: TreeFingerprint
    wwise_process_stopped: bool


def materialize_media_pool_case(
    scenario: OnlineScenario,
    *,
    asset_root: Path,
) -> MaterializedMediaPoolCase:
    """Materialize one reviewed case without touching a Wwise project."""

    if scenario.id not in MEDIA_POOL_CASE_IDS or scenario.api != MEDIA_POOL_GET_URI:
        raise MediaPoolRuntimeError(
            f"unsupported Media Pool V3 scenario: {scenario.id} ({scenario.api})"
        )
    if scenario.versions != (VERSION,):
        raise MediaPoolRuntimeError(
            f"{scenario.id} must be pinned only to Wwise {VERSION}"
        )
    spec = scenario.fixture.get("asset_spec")
    if not isinstance(spec, Mapping) or spec.get("contract") != MEDIA_POOL_FIXTURE_CONTRACT:
        raise MediaPoolRuntimeError(
            f"{scenario.id} lacks the reviewed Media Pool fixture contract"
        )
    root = Path(asset_root).expanduser().resolve(strict=False)
    if root.exists():
        raise MediaPoolRuntimeError(
            f"Media Pool asset root already exists and cannot be reused: {root}"
        )
    source_root = root / "database-inputs"
    source_root.mkdir(parents=True, exist_ok=False)

    database_rows = _mapping_rows(spec.get("databases"), field="databases")
    databases: list[MediaDatabaseFixture] = []
    for row in database_rows:
        key = _required_string(row.get("key"), field="databases.key")
        wwise_path = _required_string(row.get("path"), field="databases.path")
        if not wwise_path.startswith("\\Databases\\"):
            raise MediaPoolRuntimeError(
                f"database {key} has a non-canonical Wwise path: {wwise_path}"
            )
        kind: Literal["project_originals", "user_database"]
        if wwise_path == PROJECT_ORIGINALS_PATH:
            kind = "project_originals"
        else:
            kind = "user_database"
        database_root = source_root / key
        database_root.mkdir(parents=True, exist_ok=False)
        databases.append(
            MediaDatabaseFixture(
                key=key,
                wwise_path=wwise_path,
                name=wwise_path.rsplit("\\", 1)[-1],
                kind=kind,
                source_root=database_root,
            )
        )
    _require_unique([item.key for item in databases], field="database keys")
    _require_unique([item.wwise_path for item in databases], field="database paths")
    database_by_key = {item.key: item for item in databases}

    assets: list[MediaAsset] = []
    for row in _mapping_rows(spec.get("rows"), field="rows"):
        key = _required_string(row.get("key"), field="rows.key")
        database_key = _required_string(row.get("database"), field="rows.database")
        try:
            database = database_by_key[database_key]
        except KeyError as exc:
            raise MediaPoolRuntimeError(
                f"asset {key} references unknown database {database_key}"
            ) from exc
        relative_path = _safe_relative(
            row.get("relative_path"), field="rows.relative_path"
        )
        target = database.source_root.joinpath(*relative_path.parts)
        _write_pcm_ixml_wav(
            target,
            key=key,
            sample_rate=_positive_int(row.get("sample_rate"), field="rows.sample_rate"),
            channels=_positive_int(row.get("channels"), field="rows.channels"),
            bit_depth=_positive_int(row.get("bit_depth"), field="rows.bit_depth"),
            duration_seconds=_positive_number(
                row.get("duration_seconds"), field="rows.duration_seconds"
            ),
            ixml=_string_mapping(row.get("ixml"), field="rows.ixml"),
        )
        parsed = parse_pcm_ixml_wav(target)
        referenced_by = tuple(
            _required_string(value, field="rows.referenced_by")
            for value in _sequence(row.get("referenced_by"), field="rows.referenced_by")
        )
        assets.append(
            MediaAsset(
                key=key,
                database_key=database_key,
                relative_path=relative_path,
                source_path=target,
                parsed=parsed,
                referenced_by=referenced_by,
            )
        )
    _require_unique([item.key for item in assets], field="asset keys")
    _require_unique(
        [(item.database_key, str(item.relative_path)) for item in assets],
        field="database-relative asset paths",
    )
    declared_count = spec.get("wav", {}).get("count") if isinstance(spec.get("wav"), Mapping) else None
    if declared_count != len(assets):
        raise MediaPoolRuntimeError(
            f"{scenario.id} WAV count drifted: declared={declared_count} actual={len(assets)}"
        )

    expected_keys = tuple(
        _required_string(value, field="expected_file_keys")
        for value in _sequence(spec.get("expected_file_keys"), field="expected_file_keys")
    )
    if not expected_keys or not set(expected_keys).issubset({item.key for item in assets}):
        raise MediaPoolRuntimeError(
            f"{scenario.id} expected_file_keys do not resolve to fixture assets"
        )
    candidate_raw = spec.get("expected_candidate_file_keys")
    expected_candidate_keys = (
        expected_keys
        if candidate_raw is None
        else tuple(
            _required_string(value, field="expected_candidate_file_keys")
            for value in _sequence(
                candidate_raw,
                field="expected_candidate_file_keys",
            )
        )
    )
    if (
        not expected_candidate_keys
        or len(expected_candidate_keys) != len(set(expected_candidate_keys))
        or not set(expected_candidate_keys).issubset({item.key for item in assets})
    ):
        raise MediaPoolRuntimeError(
            f"{scenario.id} expected_candidate_file_keys do not uniquely resolve to fixture assets"
        )
    if not set(expected_keys).issubset(expected_candidate_keys):
        raise MediaPoolRuntimeError(
            f"{scenario.id} expected_file_keys are not contained in expected_candidate_file_keys"
        )
    expected_groups = MappingProxyType(
        {
            _required_string(key, field="expected_groups.key"): tuple(
                _required_string(item, field="expected_groups.value")
                for item in _sequence(value, field="expected_groups.value")
            )
            for key, value in _mapping(spec.get("expected_groups"), field="expected_groups").items()
        }
    )
    association_raw = spec.get("association_expectations")
    association_expectations: Mapping[str, tuple[str, ...]] | None
    if association_raw is None:
        association_expectations = None
    else:
        association_expectations = MappingProxyType(
            {
                _required_string(key, field="association_expectations.key"): tuple(
                    _required_string(item, field="association_expectations.value")
                    for item in _sequence(value, field="association_expectations.value")
                )
                for key, value in _mapping(
                    association_raw, field="association_expectations"
                ).items()
            }
        )

    request_template = _freeze_json(
        _mapping(spec.get("request_template"), field="request_template")
    )
    _audit_request_template(scenario.id, request_template)
    has_post_filter = "post_filter" in request_template
    if has_post_filter and candidate_raw is None:
        raise MediaPoolRuntimeError(
            f"{scenario.id} requires expected_candidate_file_keys with post_filter"
        )
    if not has_post_filter and expected_candidate_keys != expected_keys:
        raise MediaPoolRuntimeError(
            f"{scenario.id} candidate keys must equal business keys without post_filter"
        )
    if spec.get("field_binding") != "supporting_mediaPool.getFields_exact_case":
        raise MediaPoolRuntimeError(
            f"{scenario.id} does not require exact-case getFields binding"
        )

    return MaterializedMediaPoolCase(
        contract=MEDIA_POOL_RUNTIME_CONTRACT,
        scenario_id=scenario.id,
        version=VERSION,
        asset_root=root,
        databases=tuple(databases),
        assets=tuple(assets),
        request_template=request_template,
        expected_file_keys=expected_keys,
        expected_candidate_file_keys=expected_candidate_keys,
        expected_groups=expected_groups,
        association_expectations=association_expectations,
        source_fingerprint=fingerprint_tree(source_root),
    )


def parse_pcm_ixml_wav(path: Path) -> ParsedWav:
    """Parse RIFF/fmt/data/iXML independently of the fixture declaration."""

    file_path = Path(path).resolve(strict=True)
    payload = file_path.read_bytes()
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        raise MediaPoolRuntimeError(f"not a RIFF/WAVE file: {file_path}")
    declared_riff_size = struct.unpack_from("<I", payload, 4)[0]
    if declared_riff_size + 8 != len(payload):
        raise MediaPoolRuntimeError(f"RIFF size mismatch: {file_path}")

    fmt: bytes | None = None
    data: bytes | None = None
    ixml: dict[str, str] = {}
    offset = 12
    while offset < len(payload):
        if offset + 8 > len(payload):
            raise MediaPoolRuntimeError(f"truncated RIFF chunk header: {file_path}")
        chunk_id = payload[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", payload, offset + 4)[0]
        start = offset + 8
        end = start + chunk_size
        if end > len(payload):
            raise MediaPoolRuntimeError(f"truncated RIFF chunk body: {file_path}")
        chunk = payload[start:end]
        if chunk_id == b"fmt ":
            if fmt is not None:
                raise MediaPoolRuntimeError(f"duplicate fmt chunk: {file_path}")
            fmt = chunk
        elif chunk_id == b"data":
            if data is not None:
                raise MediaPoolRuntimeError(f"duplicate data chunk: {file_path}")
            data = chunk
        elif chunk_id == b"iXML":
            if ixml:
                raise MediaPoolRuntimeError(f"duplicate iXML chunk: {file_path}")
            ixml = _parse_ixml(chunk, file_path)
        offset = end + (chunk_size & 1)
    if offset != len(payload) or fmt is None or data is None or len(fmt) < 16:
        raise MediaPoolRuntimeError(f"incomplete PCM WAV: {file_path}")

    audio_format, channels, sample_rate, byte_rate, block_align, bit_depth = struct.unpack_from(
        "<HHIIHH", fmt, 0
    )
    if audio_format != 1 or channels <= 0 or sample_rate <= 0:
        raise MediaPoolRuntimeError(f"unsupported WAV fmt contract: {file_path}")
    if bit_depth not in {16, 24}:
        raise MediaPoolRuntimeError(f"unsupported WAV bit depth: {bit_depth}")
    expected_align = channels * (bit_depth // 8)
    if block_align != expected_align or byte_rate != sample_rate * block_align:
        raise MediaPoolRuntimeError(f"inconsistent WAV fmt arithmetic: {file_path}")
    if len(data) % block_align:
        raise MediaPoolRuntimeError(f"WAV data is not frame-aligned: {file_path}")
    frame_count = len(data) // block_align
    return ParsedWav(
        sample_rate=sample_rate,
        channels=channels,
        bit_depth=bit_depth,
        frame_count=frame_count,
        duration_seconds=frame_count / sample_rate,
        data_size=len(data),
        ixml=MappingProxyType(dict(ixml)),
        file_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def stage_media_pool_case(
    case: MaterializedMediaPoolCase,
    *,
    sandbox_project: Path,
    immutable_source_root: Path,
    owned_root: Path,
) -> StagedMediaPoolCase:
    """Copy Project Originals only into the private sandbox project.

    User-database assets remain in their case-owned database directories.  The
    function rejects an already-staged destination and any path overlap with the
    immutable SampleProject source.
    """

    project = Path(sandbox_project).expanduser().resolve(strict=True)
    if project.suffix.casefold() != ".wproj":
        raise MediaPoolRuntimeError("sandbox_project must be an existing .wproj")
    source_root = Path(immutable_source_root).expanduser().resolve(strict=True)
    owned = Path(owned_root).expanduser().resolve(strict=True)
    if not _is_relative_to(project, owned):
        raise MediaPoolRuntimeError("sandbox project is outside the scenario-owned root")
    if _paths_overlap(project.parent, source_root) or _paths_overlap(owned, source_root):
        raise MediaPoolRuntimeError("Media Pool staging overlaps immutable source state")
    if not _is_relative_to(case.asset_root, owned):
        raise MediaPoolRuntimeError("Media Pool asset root is outside scenario ownership")

    staged: list[StagedMediaAsset] = []
    for asset in case.assets:
        database = case.database(asset.database_key)
        if database.kind == "project_originals":
            destination = (
                project.parent / "Originals" / "SFX"
            ).joinpath(*asset.relative_path.parts)
            if destination.exists():
                raise MediaPoolRuntimeError(
                    f"Project Originals fixture destination already exists: {destination}"
                )
            if _is_relative_to(destination.resolve(strict=False), source_root):
                raise MediaPoolRuntimeError("Project Originals target reached immutable source")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(asset.source_path, destination)
        else:
            destination = asset.source_path
        reparsed = parse_pcm_ixml_wav(destination)
        if reparsed.sha256 != asset.parsed.sha256:
            raise MediaPoolRuntimeError(
                f"staged WAV bytes differ from source fixture: {asset.key}"
            )
        staged.append(
            StagedMediaAsset(asset=asset, indexed_host_path=destination.resolve(strict=True))
        )
    staged_assets = tuple(staged)
    aggregate = fingerprint_staged_media_assets(staged_assets)
    return StagedMediaPoolCase(
        materialized=case,
        sandbox_project=project,
        owned_root=owned,
        assets=staged_assets,
        staged_fingerprint=aggregate,
    )


def expected_macos_wine_prefix(launch_home: Path) -> Path:
    """Return the exact prefix selected by Wwise 2025's macOS launcher."""

    home = _lexical_absolute_path(launch_home, field="launch_home")
    return home / MACOS_WWISE_WINE_PREFIX_RELATIVE


def resolve_macos_wine_y_drive_root(launch_home: Path) -> Path:
    """Bind Wine ``Y:`` to the exact HOME used to launch Wwise.

    This reads the effective Wwise bottle after launch.  It deliberately does
    not trust the evaluated model's disposable HOME or infer a mapping from a
    returned path suffix.
    """

    home_input = _lexical_absolute_path(launch_home, field="launch_home")
    home = _require_real_directory_chain(
        home_input,
        root=home_input,
        field="launch_home",
    )
    prefix = _require_real_directory_chain(
        expected_macos_wine_prefix(home),
        root=home,
        field="wine_prefix",
    )
    dosdevices = _require_real_directory_chain(
        prefix / "dosdevices",
        root=prefix,
        field="wine_prefix.dosdevices",
    )
    link = dosdevices / "y:"
    try:
        info = link.lstat()
    except OSError as exc:
        raise MediaPoolRuntimeError("Wine drive link is unavailable: y:") from exc
    if not stat.S_ISLNK(info.st_mode):
        raise MediaPoolRuntimeError("Wine drive y: is not a symlink")
    try:
        raw_target = os.readlink(link)
    except OSError as exc:
        raise MediaPoolRuntimeError("Wine drive link cannot be read: y:") from exc
    target = Path(raw_target)
    if not target.is_absolute():
        target = link.parent / target
    try:
        resolved_target = target.resolve(strict=True)
    except OSError as exc:
        raise MediaPoolRuntimeError("Wine drive y: target is unavailable") from exc
    if resolved_target != home:
        raise MediaPoolRuntimeError(
            f"Wine drive y: has unexpected target {raw_target!r}"
        )
    return home


def validate_macos_wine_prefix(
    *,
    owned_root: Path,
    launch_home: Path,
    wine_prefix: Path,
) -> Path:
    """Prove the live CrossOver bottle and its host-drive mappings.

    The installed 2025.1 launcher ignores an inherited ``WINEPREFIX`` and
    selects a bottle below ``HOME``.  This proof binds later requests and
    process cleanup to that effective prefix rather than to an unused project
    directory.
    """

    owned = _require_real_directory_chain(
        owned_root,
        root=owned_root,
        field="owned_root",
    )
    home = _require_real_directory_chain(
        launch_home,
        root=owned,
        field="launch_home",
    )
    prefix_input = _lexical_absolute_path(wine_prefix, field="wine_prefix")
    expected = expected_macos_wine_prefix(home)
    if prefix_input != expected:
        raise MediaPoolRuntimeError(
            "WINEPREFIX is not the exact Wwise 2025 bottle below disposable HOME"
        )
    prefix = _require_real_directory_chain(
        prefix_input,
        root=home,
        field="wine_prefix",
    )
    required_links = {
        "z:": WINE_Z_DRIVE_TARGET,
        "c:": WINE_C_DRIVE_TARGET,
        "y:": str(home),
    }
    dosdevices = prefix / "dosdevices"
    _require_real_directory_chain(
        dosdevices,
        root=prefix,
        field="wine_prefix.dosdevices",
    )
    for name, expected_target in required_links.items():
        link = dosdevices / name
        try:
            info = link.lstat()
        except OSError as exc:
            raise MediaPoolRuntimeError(
                f"Wine drive link is unavailable: {name}"
            ) from exc
        if not stat.S_ISLNK(info.st_mode):
            raise MediaPoolRuntimeError(f"Wine drive {name} is not a symlink")
        try:
            target = os.readlink(link)
        except OSError as exc:
            raise MediaPoolRuntimeError(
                f"Wine drive link cannot be read: {name}"
            ) from exc
        if target != expected_target:
            raise MediaPoolRuntimeError(
                f"Wine drive {name} has unexpected target {target!r}"
            )
    return prefix


def host_directory_to_wine_z_path(
    host_directory: Path,
    *,
    owned_root: Path,
    launch_home: Path,
    wine_prefix: Path,
) -> str:
    """Map one real case-owned POSIX directory through the proven Wine Z: drive."""

    validate_macos_wine_prefix(
        owned_root=owned_root,
        launch_home=launch_home,
        wine_prefix=wine_prefix,
    )
    owned = _require_real_directory_chain(
        owned_root,
        root=owned_root,
        field="owned_root",
    )
    directory = _require_real_directory_chain(
        host_directory,
        root=owned,
        field="custom_database.source_root",
    )
    components = directory.parts[1:]
    if not components:
        raise MediaPoolRuntimeError("Wine Z: mapping cannot target the host root")
    for component in components:
        if (
            not component
            or "\x00" in component
            or "\\" in component
            or ":" in component
            or component.endswith((" ", "."))
        ):
            raise MediaPoolRuntimeError(
                "custom database path contains a Windows-unsafe component"
            )
    return str(PureWindowsPath("Z:/", *components))


def _compile_native_windows_owned_directory(
    host_directory: str,
    *,
    owned_root: str,
) -> str:
    """Compile one already-resolved native Windows directory without host I/O.

    This pure seam lets non-Windows program tests cover Windows lexical rules.
    The runtime wrapper below supplies only paths that were resolved and checked
    for links/reparse points on the native Windows filesystem.
    """

    try:
        directory = parse_windows_drive_path(host_directory)
        owned = parse_windows_drive_path(owned_root)
    except ReflectedHostPathError as exc:
        raise MediaPoolRuntimeError(
            "native Windows custom database path is not canonical drive-absolute"
        ) from exc
    if directory is None or owned is None:
        raise MediaPoolRuntimeError(
            "native Windows custom database path must be drive-absolute"
        )
    try:
        relative = directory.pure.relative_to(owned.pure)
    except ValueError as exc:
        raise MediaPoolRuntimeError(
            "native Windows custom database path is outside case ownership"
        ) from exc
    if not relative.parts:
        raise MediaPoolRuntimeError(
            "native Windows custom database path cannot equal the case root"
        )
    return str(directory.pure)


def host_directory_to_native_windows_path(
    host_directory: Path,
    *,
    owned_root: Path,
) -> str:
    """Return one proven native Windows drive path below the case-owned root."""

    if os.name != "nt":
        raise MediaPoolRuntimeError(
            "native Windows custom database paths require a native Windows host"
        )
    owned = _require_real_directory_chain(
        owned_root,
        root=owned_root,
        field="owned_root",
    )
    directory = _require_real_directory_chain(
        host_directory,
        root=owned,
        field="custom_database.source_root",
    )
    return _compile_native_windows_owned_directory(
        str(directory),
        owned_root=str(owned),
    )


def _custom_database_host_mode(
    host: CustomDatabaseHost,
) -> Literal["macos_wine", "native_windows"]:
    if isinstance(host, MacOSWineCustomDatabaseHost):
        return "macos_wine"
    if isinstance(host, NativeWindowsCustomDatabaseHost):
        return "native_windows"
    raise MediaPoolRuntimeError("custom database host binding is unsupported")


def _custom_database_wire_path(
    host_directory: Path,
    *,
    owned_root: Path,
    host: CustomDatabaseHost,
) -> str:
    if isinstance(host, MacOSWineCustomDatabaseHost):
        return host_directory_to_wine_z_path(
            host_directory,
            owned_root=owned_root,
            launch_home=host.launch_home,
            wine_prefix=host.wine_prefix,
        )
    if isinstance(host, NativeWindowsCustomDatabaseHost):
        return host_directory_to_native_windows_path(
            host_directory,
            owned_root=owned_root,
        )
    raise MediaPoolRuntimeError("custom database host binding is unsupported")


def media_pool_preflight(
    case: MaterializedMediaPoolCase,
    *,
    isolation: CustomDatabaseIsolation | None = None,
) -> MediaPoolPreflight:
    """Return READY or an explicit BLOCKED result before touching User Databases."""

    if not case.requires_custom_database:
        return MediaPoolPreflight(
            scenario_id=case.scenario_id,
            status="READY",
            code="PROJECT_ORIGINALS_ISOLATED",
            reason="all indexed files live in the disposable project copy",
            create_calls=(),
            isolation=None,
        )
    if isolation is None:
        return _blocked_preflight(
            case,
            "CUSTOM_DATABASE_ROUNDTRIP_UNPROVEN",
            "User Databases persist across projects; no sealed build-specific isolation and deletion proof was supplied",
        )
    try:
        _validate_custom_database_isolation(case, isolation)
        calls = build_custom_database_create_calls(
            case,
            owned_root=isolation.owned_root,
            host=isolation.host,
        )
    except (MediaPoolRuntimeError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _blocked_preflight(case, "CUSTOM_DATABASE_ISOLATION_INVALID", str(exc))
    return MediaPoolPreflight(
        scenario_id=case.scenario_id,
        status="READY",
        code="CUSTOM_DATABASE_ISOLATED_AND_PROVEN",
        reason="build-specific round trip and case-owned user-state roots are sealed",
        create_calls=calls,
        isolation=isolation,
    )


def build_custom_database_create_calls(
    case: MaterializedMediaPoolCase,
    *,
    owned_root: Path,
    host: CustomDatabaseHost,
) -> tuple[WaapiCall, ...]:
    """Build only Audiokinetic's documented object.set database shape."""

    _validate_custom_database_host(host, owned_root=owned_root)
    result: list[WaapiCall] = []
    for database in case.databases:
        if database.kind != "user_database":
            continue
        wire_path = _custom_database_wire_path(
            database.source_root,
            owned_root=owned_root,
            host=host,
        )
        args = {
            "objects": [
                {
                    "object": USER_DATABASES_PATH,
                    "children": [
                        {
                            "type": "MediaPoolDatabase",
                            "name": database.name,
                            "@Paths": [
                                {
                                    "type": "MediaPoolDatabasePath",
                                    "name": "",
                                    "@Path": wire_path,
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        result.append(
            WaapiCall(
                uri=OBJECT_SET_URI,
                args=_freeze_json(args),
                options=MappingProxyType({}),
            )
        )
    return tuple(result)


def build_custom_database_delete_calls(
    case: MaterializedMediaPoolCase,
    created_database_ids: Mapping[str, str],
) -> tuple[WaapiCall, ...]:
    expected = {
        item.key for item in case.databases if item.kind == "user_database"
    }
    if set(created_database_ids) != expected:
        raise MediaPoolRuntimeError(
            "custom database cleanup IDs do not exactly match the case-owned databases"
        )
    calls: list[WaapiCall] = []
    for key in sorted(expected):
        guid = _required_guid(created_database_ids[key], field=f"created_database_ids.{key}")
        calls.append(
            WaapiCall(
                uri=OBJECT_DELETE_URI,
                args=MappingProxyType({"object": guid}),
                options=MappingProxyType({}),
            )
        )
    return tuple(calls)


def parse_custom_database_create_results(
    case: MaterializedMediaPoolCase,
    payloads: Sequence[Mapping[str, Any]],
) -> Mapping[str, str]:
    """Extract only exact database GUIDs from documented object.set results."""

    databases = tuple(
        item for item in case.databases if item.kind == "user_database"
    )
    if len(payloads) != len(databases):
        raise MediaPoolRuntimeError(
            "custom database result count does not match the create plan"
        )
    created: dict[str, str] = {}
    seen_ids: set[str] = set()
    for database, payload in zip(databases, payloads, strict=True):
        parents = _sequence(payload.get("objects"), field="object.set.objects")
        if len(parents) != 1:
            raise MediaPoolRuntimeError("object.set did not return exactly one parent")
        parent = _mapping(parents[0], field="object.set.objects[]")
        if _required_guid(parent.get("id"), field="object.set.parent.id") != USER_DATABASES_GUID:
            raise MediaPoolRuntimeError("object.set result parent is not User Databases")
        children = _sequence(parent.get("children"), field="object.set.parent.children")
        if len(children) != 1:
            raise MediaPoolRuntimeError("object.set did not return exactly one database child")
        child = _mapping(children[0], field="object.set.parent.children[]")
        if _required_string(child.get("name"), field="object.set.database.name") != database.name:
            raise MediaPoolRuntimeError("object.set returned another Media Pool database")
        database_id = _required_guid(child.get("id"), field="object.set.database.id")
        if database_id in seen_ids:
            raise MediaPoolRuntimeError("object.set repeated a Media Pool database GUID")
        seen_ids.add(database_id)
        paths = _sequence(child.get("@Paths"), field="object.set.database.@Paths")
        if len(paths) != 1:
            raise MediaPoolRuntimeError("object.set did not return one database path child")
        path_child = _mapping(paths[0], field="object.set.database.@Paths[]")
        _required_guid(path_child.get("id"), field="object.set.database.@Paths.id")
        if path_child.get("name") != "":
            raise MediaPoolRuntimeError("object.set database path child has a non-empty name")
        created[database.key] = database_id
    return MappingProxyType(created)


def bind_media_pool_fields(
    case: MaterializedMediaPoolCase,
    returned_fields: Sequence[Any],
) -> MediaPoolFieldBinding:
    """Bind every template concept to one verbatim getFields value."""

    fields = tuple(
        _required_string(value, field="mediaPool.getFields.return")
        for value in returned_fields
    )
    if not fields or len(fields) != len(set(fields)):
        raise MediaPoolRuntimeError(
            "mediaPool.getFields must return a non-empty exact-case unique string list"
        )
    # The business request may project only a subset, but the hidden oracle
    # always checks the full independently parsed PCM format.  Bind all five
    # documented standard fields from the same live getFields result.
    concepts = tuple(
        dict.fromkeys((*STANDARD_FIELDS.keys(), *_request_field_concepts(case.request_template)))
    )
    bound: dict[str, str] = {}
    for concept in concepts:
        if concept in STANDARD_FIELDS:
            exact = STANDARD_FIELDS[concept]
            if exact not in fields:
                raise MediaPoolRuntimeError(
                    f"required exact Media Pool field is absent: {exact}"
                )
            bound[concept] = exact
            continue
        if concept not in {"scene", "take"}:
            raise MediaPoolRuntimeError(
                f"unreviewed Media Pool field concept: {concept}"
            )
        suffix = concept.casefold()
        candidates = tuple(
            field
            for field in fields
            if field.casefold().startswith("bwfxml/")
            and field.rsplit("/", 1)[-1].casefold() == suffix
        )
        if len(candidates) != 1:
            raise MediaPoolRuntimeError(
                f"iXML {concept} field binding is not unique: {list(candidates)}"
            )
        bound[concept] = candidates[0]
    return MediaPoolFieldBinding(
        available_fields=fields,
        by_concept=MappingProxyType(bound),
    )


def bind_media_pool_request(
    case: MaterializedMediaPoolCase,
    binding: MediaPoolFieldBinding,
) -> BoundMediaPoolRequest:
    """Build the exact public Media Pool request from the reviewed mapping.

    The model-visible rule uses one stable projection for every field-filter
    query: the three Media Pool identities, all five standard WAV/file fields,
    then any non-standard fields named by the user's filters or reporting
    request in first-mention order.  Keeping this projection independent of a
    scenario's hidden expected result makes the same rule useful for ordinary
    Media Pool queries and gives the broker one unambiguous request.
    """

    rendered = _replace_field_tokens(_plain(case.request_template), binding)
    args = _mapping(rendered.get("args"), field="request.args")
    post_filter_raw = rendered.get("post_filter")
    post_filter = (
        None
        if post_filter_raw is None
        else _mapping(post_filter_raw, field="request.post_filter")
    )
    concepts = _request_field_concepts(case.request_template)
    dynamic_concepts = tuple(
        concept for concept in concepts if concept not in STANDARD_FIELDS
    )
    options = {
        "return": [
            *MEDIA_POOL_CANONICAL_RETURN_FIELDS,
            *(binding.exact(concept) for concept in dynamic_concepts),
        ]
    }
    _audit_bound_request(case, args, options, binding, post_filter=post_filter)
    return BoundMediaPoolRequest(
        scenario_id=case.scenario_id,
        args=_freeze_json(args),
        options=_freeze_json(options),
        binding=binding,
        post_filter=(
            None if post_filter is None else _freeze_json(post_filter)
        ),
    )


def get_fields_gateway_argv() -> tuple[str, ...]:
    return (
        "call",
        MEDIA_POOL_GET_FIELDS_URI,
        "--args-json",
        "{}",
        "--options-json",
        "{}",
    )


def build_index_probe_calls(
    staged: StagedMediaPoolCase,
    binding: MediaPoolFieldBinding,
) -> tuple[WaapiCall, ...]:
    """Build one exact Media Pool Filename probe per owned asset."""

    returns = (
        "Path",
        "FileId",
        "Db",
        binding.exact("name"),
        binding.exact("duration"),
        binding.exact("sample_rate"),
        binding.exact("channels"),
        binding.exact("bit_depth"),
        *(
            (binding.exact("scene"), binding.exact("take"))
            if "scene" in binding.by_concept
            else ()
        ),
    )
    result: list[WaapiCall] = []
    for staged_asset in staged.assets:
        database = staged.materialized.database(staged_asset.asset.database_key)
        result.append(
            WaapiCall(
                uri=MEDIA_POOL_GET_URI,
                args=_freeze_json(
                    {
                        "databases": [database.wwise_path],
                        "filters": [
                            {
                                "type": "field",
                                "field": binding.exact("name"),
                                "operator": "equals",
                                "value": _media_pool_filename(
                                    staged_asset.indexed_host_path
                                ),
                            }
                        ],
                        "maxResults": 8,
                    }
                ),
                options=_freeze_json({"return": list(returns)}),
            )
        )
    return tuple(result)


def build_reference_fixture_call(
    staged: StagedMediaPoolCase,
) -> WaapiCall | None:
    """Build the trusted pre-task import for case 04's known Audio Sources."""

    imports: list[dict[str, Any]] = []
    for item in staged.assets:
        for object_path in item.asset.referenced_by:
            imports.append(
                {
                    "audioFile": str(item.indexed_host_path),
                    "objectPath": _typed_audio_import_path(object_path),
                }
            )
    if not imports:
        return None
    return WaapiCall(
        uri="ak.wwise.core.audio.import",
        args=_freeze_json(
            {"importOperation": "useExisting", "imports": imports}
        ),
        options=MappingProxyType({}),
    )


def build_reference_read_call(
    staged: StagedMediaPoolCase,
) -> WaapiCall | None:
    """Read every AudioFileSource once so zero-reference claims are provable."""

    if staged.materialized.association_expectations is None:
        return None
    return WaapiCall(
        uri=OBJECT_GET_URI,
        args=MappingProxyType({"waql": "$ from type AudioFileSource"}),
        options=_freeze_json(
            {"return": ["id", "path", "originalFilePath"]}
        ),
    )


def build_reference_match_gateway_argv(
    original_file_paths: Sequence[str],
) -> tuple[str, ...]:
    """Build the compact public AudioFileSource query in stable path order."""

    paths = tuple(
        sorted(
            _required_string(value, field="reference match original file path")
            for value in original_file_paths
        )
    )
    if not paths:
        raise MediaPoolRuntimeError(
            "reference match query requires at least one original file path"
        )
    _require_unique(paths, field="reference match original file paths")
    argv: list[str] = [
        "query-object",
        "--type",
        "AudioFileSource",
        "--take",
        str(REFERENCE_MATCH_SCAN_LIMIT),
    ]
    for path in paths:
        argv.extend(("--match-original-file-path", path))
    return tuple(argv)


def reference_match_paths(oracle: SealedMediaPoolOracle) -> tuple[str, ...]:
    """Return the exact sealed candidate paths used by the public match query."""

    return tuple(
        sorted(
            _required_string(
                oracle.row(key).path,
                field=f"sealed reference match path for {key}",
            )
            for key in oracle.expected_keys
        )
    )


def verify_reference_match_agent_result(
    payload: Mapping[str, Any],
    *,
    expected_candidates: Sequence[tuple[str, Sequence[str]]],
) -> VerificationResult:
    """Verify the closed compact match result against path/parent expectations."""

    try:
        required_keys = {
            "contract",
            "candidates",
            "scanned_audio_source_count",
            "scan_limit",
            "scan_complete",
        }
        if set(payload) != required_keys:
            raise MediaPoolRuntimeError(
                "reference match agent_result has missing or extra fields"
            )
        if payload.get("contract") != REFERENCE_MATCH_RESULT_CONTRACT:
            raise MediaPoolRuntimeError("reference match agent_result contract is invalid")
        scan_limit = payload.get("scan_limit")
        scanned_count = payload.get("scanned_audio_source_count")
        if scan_limit != REFERENCE_MATCH_SCAN_LIMIT:
            raise MediaPoolRuntimeError(
                f"reference match scan_limit must be {REFERENCE_MATCH_SCAN_LIMIT}"
            )
        if (
            not isinstance(scanned_count, int)
            or isinstance(scanned_count, bool)
            or scanned_count < 0
            or scanned_count >= REFERENCE_MATCH_SCAN_LIMIT
        ):
            raise MediaPoolRuntimeError(
                "reference match scanned_audio_source_count is outside the complete scan boundary"
            )
        if payload.get("scan_complete") is not True:
            raise MediaPoolRuntimeError("reference match scan is not complete")

        normalized_expectations: list[tuple[str, tuple[str, ...]]] = []
        for raw_path, raw_parents in expected_candidates:
            path = _required_string(
                raw_path,
                field="reference match expected original file path",
            )
            parents = tuple(
                _required_string(
                    parent,
                    field=f"reference match expected parent for {path}",
                )
                for parent in raw_parents
            )
            _require_unique(parents, field=f"reference match parents for {path}")
            normalized_expectations.append((path, parents))
        normalized_expectations.sort(key=lambda item: item[0])
        expected_paths = tuple(path for path, _parents in normalized_expectations)
        if not expected_paths:
            raise MediaPoolRuntimeError(
                "reference match verification requires at least one candidate"
            )
        _require_unique(expected_paths, field="reference match expected paths")

        candidates = _mapping_rows(
            payload.get("candidates"),
            field="reference match candidates",
        )
        observed_paths = tuple(
            _required_string(
                candidate.get("originalFilePath"),
                field="reference match candidate originalFilePath",
            )
            for candidate in candidates
        )
        if observed_paths != expected_paths:
            raise MediaPoolRuntimeError(
                "reference match candidates differ from the sorted sealed paths"
            )

        seen_source_ids: set[str] = set()
        returned_reference_count = 0
        for candidate, (expected_path, expected_parents) in zip(
            candidates,
            normalized_expectations,
            strict=True,
        ):
            if set(candidate) != {
                "originalFilePath",
                "classification",
                "reference_count",
                "references",
                "references_truncated",
            }:
                raise MediaPoolRuntimeError(
                    f"reference match candidate {expected_path} has missing or extra fields"
                )
            expected_classification = (
                "referenced" if expected_parents else "unreferenced"
            )
            if candidate.get("classification") != expected_classification:
                raise MediaPoolRuntimeError(
                    f"reference match classification differs for {expected_path}"
                )
            references = _mapping_rows(
                candidate.get("references"),
                field=f"reference match references for {expected_path}",
            )
            reference_count = candidate.get("reference_count")
            if (
                not isinstance(reference_count, int)
                or isinstance(reference_count, bool)
                or reference_count < 0
                or reference_count != len(references)
                or reference_count != len(expected_parents)
            ):
                raise MediaPoolRuntimeError(
                    f"reference match count differs for {expected_path}"
                )
            if candidate.get("references_truncated") is not False:
                raise MediaPoolRuntimeError(
                    f"reference match references are truncated for {expected_path}"
                )
            matched_parents: list[str] = []
            for reference in references:
                if set(reference) != {"id", "path"}:
                    raise MediaPoolRuntimeError(
                        f"reference match reference for {expected_path} has missing or extra fields"
                    )
                source_id = _required_guid(
                    reference.get("id"),
                    field="reference match AudioFileSource.id",
                )
                if source_id in seen_source_ids:
                    raise MediaPoolRuntimeError(
                        "reference match returned a duplicate AudioFileSource GUID"
                    )
                seen_source_ids.add(source_id)
                object_path = _required_string(
                    reference.get("path"),
                    field="reference match AudioFileSource.path",
                )
                matches = tuple(
                    parent
                    for parent in expected_parents
                    if object_path.casefold().startswith((parent + "\\").casefold())
                )
                if len(matches) != 1 or matches[0] in matched_parents:
                    raise MediaPoolRuntimeError(
                        f"reference match AudioFileSource is not uniquely below a declared Sound for {expected_path}"
                    )
                matched_parents.append(matches[0])
            if set(matched_parents) != set(expected_parents):
                raise MediaPoolRuntimeError(
                    f"reference match parents differ for {expected_path}"
                )
            returned_reference_count += reference_count

        if scanned_count < returned_reference_count:
            raise MediaPoolRuntimeError(
                "reference match returned more references than the complete scan observed"
            )
        return VerificationResult(
            ok=True,
            code="MEDIA_POOL_REFERENCE_MATCH_EXACT",
            details=MappingProxyType(
                {
                    "candidate_count": len(candidates),
                    "returned_reference_count": returned_reference_count,
                    "scanned_audio_source_count": scanned_count,
                }
            ),
        )
    except MediaPoolRuntimeError as exc:
        return VerificationResult(
            ok=False,
            code="MEDIA_POOL_REFERENCE_MATCH_MISMATCH",
            details=MappingProxyType({"error": str(exc)}),
        )


def verify_reference_match_result(
    staged: StagedMediaPoolCase,
    oracle: SealedMediaPoolOracle,
    payload: Mapping[str, Any],
) -> VerificationResult:
    """Bind the compact public result to the four sealed business candidates."""

    try:
        association = staged.materialized.association_expectations
        if association is None:
            raise MediaPoolRuntimeError(
                "reference match verification is not part of this scenario"
            )
        classified_keys = (
            *tuple(association.get("referenced", ())),
            *tuple(association.get("unreferenced", ())),
        )
        if len(classified_keys) != len(set(classified_keys)) or set(
            classified_keys
        ) != set(oracle.expected_keys):
            raise MediaPoolRuntimeError(
                "reference match classifications do not close the sealed business keys"
            )
        expectations = tuple(
            (
                oracle.row(key).path,
                staged.staged_asset(key).asset.referenced_by,
            )
            for key in oracle.expected_keys
        )
    except MediaPoolRuntimeError as exc:
        return VerificationResult(
            ok=False,
            code="MEDIA_POOL_REFERENCE_MATCH_MISMATCH",
            details=MappingProxyType({"error": str(exc)}),
        )
    return verify_reference_match_agent_result(
        payload,
        expected_candidates=expectations,
    )


def verify_reference_associations(
    staged: StagedMediaPoolCase,
    payload: Mapping[str, Any],
    *,
    waapi_y_drive_root: Path | None = None,
) -> VerificationResult:
    """Match live AudioFileSources to staged bytes and exact declared parents."""

    case = staged.materialized
    try:
        association = case.association_expectations
        if association is None:
            raise MediaPoolRuntimeError(
                "reference association verification is not part of this scenario"
            )
        originals_root = staged.sandbox_project.parent / "Originals"
        by_host_path: dict[Path, StagedMediaAsset] = {}
        for item in staged.assets:
            database = case.database(item.asset.database_key)
            if database.kind != "project_originals":
                raise MediaPoolRuntimeError(
                    "reference association fixtures must use Project Originals"
                )
            sealed_path = _localize_waapi_path(
                str(item.indexed_host_path),
                owned_root=staged.owned_root,
                waapi_y_drive_root=waapi_y_drive_root,
            )
            if not _is_relative_to(sealed_path, originals_root):
                raise MediaPoolRuntimeError(
                    "sealed reference fixture is outside sandbox Project Originals"
                )
            by_host_path[sealed_path] = item
        observed: dict[str, list[str]] = {item.asset.key: [] for item in staged.assets}
        seen_ids: set[str] = set()
        for value in _sequence(payload.get("return"), field="object.get.return"):
            row = _mapping(value, field="object.get.return[]")
            original = row.get("originalFilePath")
            if not isinstance(original, str) or not original:
                continue
            try:
                host_path = _localize_waapi_path(
                    original,
                    relative_root=originals_root,
                    owned_root=staged.owned_root,
                    waapi_y_drive_root=waapi_y_drive_root,
                )
            except MediaPoolRuntimeError:
                continue
            item = by_host_path.get(host_path)
            if item is None:
                continue
            source_id = _required_guid(row.get("id"), field="AudioFileSource.id")
            if source_id in seen_ids:
                raise MediaPoolRuntimeError("object.get returned a duplicate AudioFileSource GUID")
            seen_ids.add(source_id)
            object_path = _required_string(row.get("path"), field="AudioFileSource.path")
            expected_parents = item.asset.referenced_by
            matching_parents = tuple(
                parent
                for parent in expected_parents
                if object_path.casefold().startswith((parent + "\\").casefold())
            )
            if len(matching_parents) != 1:
                raise MediaPoolRuntimeError(
                    f"AudioFileSource {source_id} is not below the declared Sound for {item.asset.key}"
                )
            observed[item.asset.key].append(source_id)

        for item in staged.assets:
            expected_count = len(item.asset.referenced_by)
            actual_ids = observed[item.asset.key]
            if len(actual_ids) != expected_count:
                raise MediaPoolRuntimeError(
                    f"fixture asset {item.asset.key} has {len(actual_ids)} live references; expected {expected_count}"
                )
        expected_referenced = tuple(association.get("referenced", ()))
        expected_unreferenced = tuple(association.get("unreferenced", ()))
        actual_referenced = tuple(
            key for key in case.expected_file_keys if observed[key]
        )
        actual_unreferenced = tuple(
            key for key in case.expected_file_keys if not observed[key]
        )
        if (
            actual_referenced != expected_referenced
            or actual_unreferenced != expected_unreferenced
        ):
            raise MediaPoolRuntimeError(
                "live AudioFileSource classification differs from the scenario oracle"
            )
        return VerificationResult(
            ok=True,
            code="MEDIA_POOL_REFERENCES_EXACT",
            details=MappingProxyType(
                {
                    "scenario_id": case.scenario_id,
                    "referenced_keys": actual_referenced,
                    "unreferenced_keys": actual_unreferenced,
                    "fixture_audio_source_count": sum(map(len, observed.values())),
                }
            ),
        )
    except MediaPoolRuntimeError as exc:
        return VerificationResult(
            ok=False,
            code="MEDIA_POOL_REFERENCES_MISMATCH",
            details=MappingProxyType({"error": str(exc)}),
        )


def seal_media_pool_index(
    staged: StagedMediaPoolCase,
    request: BoundMediaPoolRequest,
    observed_rows: Sequence[Mapping[str, Any]],
    *,
    waapi_y_drive_root: Path | None = None,
) -> SealedMediaPoolOracle:
    """Seal live FileId/Db/Path while checking all WAV fields independently."""

    if request.scenario_id != staged.materialized.scenario_id:
        raise MediaPoolRuntimeError("staged case and bound request scenario IDs differ")
    rows = tuple(observed_rows)
    if len(rows) != len(staged.assets):
        raise MediaPoolRuntimeError(
            "index sealing requires exactly one observed row per fixture asset"
        )
    remaining = list(rows)
    sealed: list[SealedMediaRow] = []
    seen_file_ids: set[str] = set()
    db_ids_by_key: dict[str, str] = {}
    for staged_asset in staged.assets:
        database = staged.materialized.database(staged_asset.asset.database_key)
        relative_root = (
            staged.sandbox_project.parent / "Originals"
            if database.kind == "project_originals"
            else database.source_root
        )
        matches = [
            row
            for row in remaining
            if _observed_row_matches_path(
                row,
                staged_asset.indexed_host_path,
                relative_root=relative_root,
                waapi_y_drive_root=waapi_y_drive_root,
            )
        ]
        if len(matches) != 1:
            raise MediaPoolRuntimeError(
                f"index row did not uniquely resolve staged asset {staged_asset.asset.key}"
            )
        row = matches[0]
        remaining.remove(row)
        file_id = _required_guid(row.get("FileId"), field="observed.FileId")
        if file_id in seen_file_ids:
            raise MediaPoolRuntimeError("Media Pool FileIds are not unique")
        seen_file_ids.add(file_id)
        db = _mapping(row.get("Db"), field="observed.Db")
        db_id = _required_guid(db.get("id"), field="observed.Db.id")
        db_name = _required_string(db.get("name"), field="observed.Db.name")
        if db_name != database.name:
            raise MediaPoolRuntimeError(
                f"Media Pool row {staged_asset.asset.key} belongs to unexpected database {db_name}"
            )
        prior_db_id = db_ids_by_key.setdefault(database.key, db_id)
        if prior_db_id != db_id:
            raise MediaPoolRuntimeError(
                f"database {database.key} produced inconsistent Db GUIDs"
            )
        _verify_observed_metadata(row, staged_asset.asset, request.binding)
        values = {
            field: _freeze_json(row[field])
            for field in request.options["return"]
            if field in row
        }
        if set(values) != set(request.options["return"]):
            missing = sorted(set(request.options["return"]) - set(values))
            raise MediaPoolRuntimeError(
                f"index row {staged_asset.asset.key} lacks requested values: {missing}"
            )
        sealed.append(
            SealedMediaRow(
                key=staged_asset.asset.key,
                path=_required_string(row.get("Path"), field="observed.Path"),
                host_path=staged_asset.indexed_host_path,
                file_id=file_id,
                db=MappingProxyType({"id": db_id, "name": db_name}),
                values=MappingProxyType(values),
            )
        )
    if remaining:
        raise MediaPoolRuntimeError("unmatched rows remained after index sealing")

    candidate_keys = _evaluate_fixture_query(staged, request)
    if set(candidate_keys) != set(
        staged.materialized.expected_candidate_file_keys
    ):
        raise MediaPoolRuntimeError(
            "declared Media Pool expected_candidate_file_keys differ from the independently evaluated server request"
        )
    expected_keys = _apply_fixture_post_filter(
        staged,
        request,
        candidate_keys,
    )
    if set(expected_keys) != set(staged.materialized.expected_file_keys):
        raise MediaPoolRuntimeError(
            "declared Media Pool expected_file_keys differ from the independently evaluated business request"
        )
    answer = build_semantic_answer(staged.materialized)
    return SealedMediaPoolOracle(
        scenario_id=staged.materialized.scenario_id,
        request=request,
        rows=tuple(sealed),
        expected_keys=expected_keys,
        semantic_answer=answer,
        source_fingerprint=staged.materialized.source_fingerprint,
        staged_fingerprint=staged.staged_fingerprint,
        candidate_keys=candidate_keys,
    )


def verify_media_pool_result(
    oracle: SealedMediaPoolOracle,
    payload: Mapping[str, Any],
) -> VerificationResult:
    """Verify the business result exactly, including values and exclusions."""

    return _verify_media_pool_result_keys(
        oracle,
        payload,
        keys=oracle.expected_keys,
        max_results=oracle.semantic_answer.max_results,
        success_code="MEDIA_POOL_RESULT_EXACT",
        failure_code="MEDIA_POOL_RESULT_MISMATCH",
        result_label="mediaPool.get business result",
    )


def verify_media_pool_candidate_result(
    oracle: SealedMediaPoolOracle,
    payload: Mapping[str, Any],
) -> VerificationResult:
    """Verify the complete raw server candidate set before post-filtering."""

    return _verify_media_pool_result_keys(
        oracle,
        payload,
        keys=oracle.candidate_keys,
        max_results=int(oracle.request.args["maxResults"]),
        success_code="MEDIA_POOL_CANDIDATES_EXACT",
        failure_code="MEDIA_POOL_CANDIDATES_MISMATCH",
        result_label="mediaPool.get raw candidate result",
    )


def apply_media_pool_post_filter(
    request: BoundMediaPoolRequest,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Apply the same closed, stable-order business post-filter as the gateway."""

    rows = _sequence(payload.get("return"), field="result.return")
    if request.post_filter is None:
        return MappingProxyType({"return": [_plain(item) for item in rows]})
    post_filter = request.post_filter
    field = _required_string(post_filter.get("field"), field="post_filter.field")
    operator = _required_string(
        post_filter.get("operator"),
        field="post_filter.operator",
    )
    value = _required_string(post_filter.get("value"), field="post_filter.value")
    limit = post_filter.get("limit")
    if operator != "containsCaseSensitive":
        raise MediaPoolRuntimeError(f"unsupported Media Pool post-filter: {operator}")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise MediaPoolRuntimeError("Media Pool post-filter limit is invalid")
    filtered: list[dict[str, Any]] = []
    for item in rows:
        row = _mapping(item, field="result.return[]")
        actual = row.get(field)
        if not isinstance(actual, str):
            raise MediaPoolRuntimeError(
                f"Media Pool post-filter field {field!r} is not a string"
            )
        if value in actual:
            filtered.append(_plain(row))
            if len(filtered) == limit:
                break
    return MappingProxyType({"return": filtered})


def _verify_media_pool_result_keys(
    oracle: SealedMediaPoolOracle,
    payload: Mapping[str, Any],
    *,
    keys: Sequence[str],
    max_results: int,
    success_code: str,
    failure_code: str,
    result_label: str,
) -> VerificationResult:
    """Verify one exact sealed row set without weakening it to subset matching."""

    try:
        if set(payload) != {"return"}:
            raise MediaPoolRuntimeError(
                f"{result_label} must contain exactly one top-level return array"
            )
        raw_rows = _sequence(payload.get("return"), field="result.return")
        if len(raw_rows) > max_results:
            raise MediaPoolRuntimeError(f"{result_label} exceeded its declared limit")
        expected = {oracle.row(key).file_id: oracle.row(key) for key in keys}
        actual: dict[str, Mapping[str, Any]] = {}
        for value in raw_rows:
            row = _mapping(value, field="result.return[]")
            file_id = _required_guid(row.get("FileId"), field="result.FileId")
            if file_id in actual:
                raise MediaPoolRuntimeError("mediaPool.get returned a duplicate FileId")
            actual[file_id] = row
        if set(actual) != set(expected):
            raise MediaPoolRuntimeError(
                f"{result_label} FileId set differs from the hidden fixture oracle"
            )
        requested = tuple(oracle.request.options["return"])
        for file_id, expected_row in expected.items():
            actual_row = actual[file_id]
            if set(actual_row) != set(requested):
                raise MediaPoolRuntimeError(
                    f"result row {file_id} has an unexpected exact field set"
                )
            for field in requested:
                if not _same_media_value(actual_row[field], expected_row.values[field]):
                    raise MediaPoolRuntimeError(
                        f"result row {file_id} field {field!r} differs from the sealed index"
                    )
        return VerificationResult(
            ok=True,
            code=success_code,
            details=MappingProxyType(
                {
                    "scenario_id": oracle.scenario_id,
                    "file_ids": tuple(sorted(actual)),
                    "row_count": len(actual),
                }
            ),
        )
    except MediaPoolRuntimeError as exc:
        return VerificationResult(
            ok=False,
            code=failure_code,
            details=MappingProxyType({"error": str(exc)}),
        )


def verify_semantic_report(
    oracle: SealedMediaPoolOracle,
    *,
    ordered_keys: Sequence[str],
    groups: Mapping[str, Sequence[str]] | None = None,
    referenced_keys: Sequence[str] = (),
    unreferenced_keys: Sequence[str] = (),
) -> VerificationResult:
    """Verify grader-extracted answer semantics independently of prose style."""

    plan = oracle.semantic_answer
    try:
        actual_order = tuple(ordered_keys)
        if media_answer_requires_order(oracle.scenario_id):
            order_matches = actual_order == plan.ordered_keys
        else:
            order_matches = (
                len(actual_order) == len(plan.ordered_keys)
                and set(actual_order) == set(plan.ordered_keys)
            )
        if not order_matches:
            raise MediaPoolRuntimeError(
                f"semantic answer order mismatch: expected={plan.ordered_keys} actual={actual_order}"
            )
        if len(actual_order) > plan.max_results or len(set(actual_order)) != len(actual_order):
            raise MediaPoolRuntimeError("semantic answer violates result bound or uniqueness")
        if set(actual_order) & set(plan.excluded_keys):
            raise MediaPoolRuntimeError("semantic answer includes an excluded fixture key")
        actual_groups = {
            key: tuple(value) for key, value in (groups or {}).items()
        }
        if actual_groups != dict(plan.expected_groups):
            raise MediaPoolRuntimeError("semantic answer duplicate groups are not exact")
        if tuple(referenced_keys) != plan.referenced_keys:
            raise MediaPoolRuntimeError("semantic answer referenced classification is not exact")
        if tuple(unreferenced_keys) != plan.unreferenced_keys:
            raise MediaPoolRuntimeError("semantic answer unreferenced classification is not exact")
        return VerificationResult(
            ok=True,
            code="MEDIA_POOL_SEMANTIC_ANSWER_EXACT",
            details=MappingProxyType({"scenario_id": oracle.scenario_id}),
        )
    except MediaPoolRuntimeError as exc:
        return VerificationResult(
            ok=False,
            code="MEDIA_POOL_SEMANTIC_ANSWER_MISMATCH",
            details=MappingProxyType({"error": str(exc)}),
        )


def verify_media_pool_read_unchanged(
    staged: StagedMediaPoolCase,
    oracle: SealedMediaPoolOracle,
) -> VerificationResult:
    """Prove that the read left fixture sources and indexed WAV bytes exact."""

    try:
        if staged.materialized.scenario_id != oracle.scenario_id:
            raise MediaPoolRuntimeError("unchanged proof belongs to another scenario")
        source_after = fingerprint_tree(
            staged.materialized.asset_root / "database-inputs"
        )
        if source_after != oracle.source_fingerprint:
            raise MediaPoolRuntimeError("Media Pool fixture source bytes changed")
        indexed_after = fingerprint_staged_media_assets(staged.assets)
        if indexed_after != oracle.staged_fingerprint:
            raise MediaPoolRuntimeError("Media Pool indexed WAV tree changed")
        return VerificationResult(
            ok=True,
            code="MEDIA_POOL_READ_UNCHANGED",
            details=MappingProxyType(
                {
                    "scenario_id": oracle.scenario_id,
                    "source_sha256": source_after.sha256,
                    "indexed_sha256": indexed_after.sha256,
                }
            ),
        )
    except (MediaPoolRuntimeError, OSError) as exc:
        return VerificationResult(
            ok=False,
            code="MEDIA_POOL_READ_STATE_DRIFT",
            details=MappingProxyType({"error": str(exc)}),
        )


def verify_custom_database_cleanup(
    case: MaterializedMediaPoolCase,
    preflight: MediaPoolPreflight,
    proof: CustomDatabaseCleanupProof,
) -> VerificationResult:
    """Require deletion, baseline restoration, process stop, and global-state parity."""

    try:
        if not preflight.ready or preflight.isolation is None:
            raise MediaPoolRuntimeError("custom database case never passed preflight")
        if proof.contract != CUSTOM_DATABASE_CLEANUP_CONTRACT:
            raise MediaPoolRuntimeError("custom database cleanup proof contract mismatch")
        if proof.scenario_id != case.scenario_id:
            raise MediaPoolRuntimeError("cleanup proof belongs to another scenario")
        expected_keys = {
            item.key for item in case.databases if item.kind == "user_database"
        }
        if set(proof.created_database_ids) != expected_keys:
            raise MediaPoolRuntimeError("cleanup proof omits a case-owned database")
        created_ids = tuple(
            _required_guid(value, field="cleanup.created_database_ids")
            for value in proof.created_database_ids.values()
        )
        if len(created_ids) != len(set(created_ids)):
            raise MediaPoolRuntimeError("cleanup proof repeats a created database GUID")
        baseline_values = tuple(
            _required_guid(value, field="cleanup.baseline_user_database_ids")
            for value in proof.baseline_user_database_ids
        )
        final_values = tuple(
            _required_guid(value, field="cleanup.final_user_database_ids")
            for value in proof.final_user_database_ids
        )
        if len(baseline_values) != len(set(baseline_values)) or len(final_values) != len(
            set(final_values)
        ):
            raise MediaPoolRuntimeError("cleanup database inventories contain duplicate GUIDs")
        baseline = tuple(sorted(baseline_values))
        final = tuple(sorted(final_values))
        if baseline != final or set(created_ids) & set(final):
            raise MediaPoolRuntimeError(
                "User Databases did not return exactly to the pre-case baseline"
            )
        if not proof.wwise_process_stopped:
            raise MediaPoolRuntimeError("Wwise process was not proven stopped")
        before = preflight.isolation.global_user_state_before
        after = proof.global_user_state_after
        if (
            before.root,
            before.exists,
            before.sha256,
            before.file_count,
            before.byte_count,
        ) != (
            after.root,
            after.exists,
            after.sha256,
            after.file_count,
            after.byte_count,
        ):
            raise MediaPoolRuntimeError("real-account Wwise user state changed")
        return VerificationResult(
            ok=True,
            code="CUSTOM_DATABASE_CLEANUP_EXACT",
            details=MappingProxyType({"scenario_id": case.scenario_id}),
        )
    except MediaPoolRuntimeError as exc:
        return VerificationResult(
            ok=False,
            code="CUSTOM_DATABASE_CLEANUP_BLOCKED",
            details=MappingProxyType({"error": str(exc)}),
        )


def fingerprint_tree(root: Path) -> TreeFingerprint:
    path = Path(root).expanduser().resolve(strict=False)
    if not path.exists():
        return TreeFingerprint(
            root=path,
            exists=False,
            sha256=hashlib.sha256(b"missing-tree\0").hexdigest(),
            file_count=0,
            byte_count=0,
        )
    if not path.is_dir():
        raise MediaPoolRuntimeError(f"fingerprint root is not a directory: {path}")
    digest = hashlib.sha256()
    file_count = 0
    byte_count = 0
    for item in sorted(path.rglob("*"), key=lambda value: value.relative_to(path).as_posix()):
        relative = item.relative_to(path).as_posix()
        if item.is_symlink():
            raise MediaPoolRuntimeError(f"fingerprint tree contains a symlink: {item}")
        if item.is_dir():
            digest.update(b"D\0" + relative.encode("utf-8") + b"\0")
            continue
        if not item.is_file():
            raise MediaPoolRuntimeError(f"fingerprint tree contains a special file: {item}")
        data = item.read_bytes()
        digest.update(b"F\0" + relative.encode("utf-8") + b"\0")
        digest.update(struct.pack("<Q", len(data)))
        digest.update(hashlib.sha256(data).digest())
        file_count += 1
        byte_count += len(data)
    return TreeFingerprint(
        root=path,
        exists=True,
        sha256=digest.hexdigest(),
        file_count=file_count,
        byte_count=byte_count,
    )


def fingerprint_staged_media_assets(
    assets: Sequence[StagedMediaAsset],
) -> TreeFingerprint:
    """Fingerprint only the exact indexed asset directories, not their common ancestor."""

    rows = tuple(assets)
    if not rows:
        raise MediaPoolRuntimeError("staged Media Pool fingerprint requires assets")
    return _fingerprint_paths(
        {item.indexed_host_path.parent for item in rows}
    )


def custom_database_payload_shape_sha256() -> str:
    shape = {
        "uri": OBJECT_SET_URI,
        "args": {
            "objects": [
                {
                    "object": USER_DATABASES_PATH,
                    "children": [
                        {
                            "type": "MediaPoolDatabase",
                            "name": "{database_name}",
                            "@Paths": [
                                {
                                    "type": "MediaPoolDatabasePath",
                                    "name": "",
                                    "@Path": "{case_owned_host_directory}",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        "options": {},
        "user_databases_guid": USER_DATABASES_GUID,
    }
    canonical = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def custom_database_round_trip_evidence(
    host: CustomDatabaseHost,
) -> dict[str, Any]:
    """Return the exact runner-owned proof payload for one host binding."""

    common: dict[str, Any] = {
        "contract": CUSTOM_DATABASE_PROOF_CONTRACT,
        "wwise_build": SUPPORTED_BUILD,
        "payload_shape_sha256": custom_database_payload_shape_sha256(),
        "created_under_user_databases": True,
        "delete_by_guid_verified": True,
        "baseline_children_restored": True,
        "global_user_state_unchanged": True,
    }
    if isinstance(host, MacOSWineCustomDatabaseHost):
        common["host_binding"] = {
            "mode": "macos_wine",
            "launch_home_isolated": True,
            "effective_wine_prefix_isolated": True,
            "wine_prefix_relative_to_launch_home": str(
                MACOS_WWISE_WINE_PREFIX_RELATIVE
            ),
            "wine_z_drive_target": WINE_Z_DRIVE_TARGET,
            "wine_c_drive_target": WINE_C_DRIVE_TARGET,
        }
    elif isinstance(host, NativeWindowsCustomDatabaseHost):
        common["host_binding"] = {
            "mode": "native_windows",
            "user_profile_isolated": True,
            "appdata_isolated": True,
            "local_appdata_isolated": True,
            "database_paths_are_native_drive_absolute": True,
        }
    else:  # pragma: no cover - closed union, retained as a runtime boundary
        raise MediaPoolRuntimeError("custom database host binding is unsupported")
    return common


def _validate_custom_database_host(
    host: CustomDatabaseHost,
    *,
    owned_root: Path,
) -> None:
    owned = _require_real_directory_chain(
        owned_root,
        root=owned_root,
        field="owned_root",
    )
    if isinstance(host, MacOSWineCustomDatabaseHost):
        if os.name == "nt":
            raise MediaPoolRuntimeError(
                "Wine custom database binding cannot run on native Windows"
            )
        launch_home = _require_real_directory_chain(
            host.launch_home,
            root=owned,
            field="launch_home",
        )
        wine_prefix = _require_real_directory_chain(
            host.wine_prefix,
            root=launch_home,
            field="wine_prefix",
        )
        validate_macos_wine_prefix(
            owned_root=owned,
            launch_home=launch_home,
            wine_prefix=wine_prefix,
        )
        return
    if isinstance(host, NativeWindowsCustomDatabaseHost):
        if os.name != "nt":
            raise MediaPoolRuntimeError(
                "native Windows custom database binding requires native Windows"
            )
        profile = _require_real_directory_chain(
            host.user_profile,
            root=owned,
            field="user_profile",
        )
        appdata = _require_real_directory_chain(
            host.appdata,
            root=owned,
            field="appdata",
        )
        local_appdata = _require_real_directory_chain(
            host.local_appdata,
            root=owned,
            field="local_appdata",
        )
        if len({profile, appdata, local_appdata}) != 3:
            raise MediaPoolRuntimeError(
                "native Windows user-state roots must be distinct"
            )
        return
    raise MediaPoolRuntimeError("custom database host binding is unsupported")


def _validate_custom_database_isolation(
    case: MaterializedMediaPoolCase,
    isolation: CustomDatabaseIsolation,
) -> None:
    owned = isolation.owned_root.expanduser().resolve(strict=True)
    if not _is_relative_to(case.asset_root, owned):
        raise MediaPoolRuntimeError("custom database asset root is outside ownership")
    _validate_custom_database_host(isolation.host, owned_root=owned)
    proof = isolation.round_trip_proof
    if proof.wwise_build != SUPPORTED_BUILD:
        raise MediaPoolRuntimeError(
            f"custom database proof is not for exact build {SUPPORTED_BUILD}"
        )
    if proof.payload_shape_sha256 != custom_database_payload_shape_sha256():
        raise MediaPoolRuntimeError("custom database proof used another payload shape")
    if proof.host_mode != _custom_database_host_mode(isolation.host):
        raise MediaPoolRuntimeError("custom database proof used another host mode")
    evidence = proof.evidence_path.expanduser().resolve(strict=True)
    if not _is_relative_to(evidence, owned):
        raise MediaPoolRuntimeError("custom database proof is outside case ownership")
    if hashlib.sha256(evidence.read_bytes()).hexdigest() != proof.evidence_sha256:
        raise MediaPoolRuntimeError("custom database proof digest mismatch")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    required = custom_database_round_trip_evidence(isolation.host)
    if payload != required:
        raise MediaPoolRuntimeError("custom database round-trip evidence is incomplete")
    global_state_root = isolation.global_user_state_before.root.expanduser().resolve(
        strict=False
    )
    expected_global_state_root = isolation.real_account_state_root.expanduser().resolve(
        strict=False
    )
    if global_state_root != expected_global_state_root:
        raise MediaPoolRuntimeError(
            "global user-state baseline is not the exact real-account Wwise state"
        )
    if _paths_overlap(global_state_root, owned):
        raise MediaPoolRuntimeError(
            "global user-state baseline overlaps case-owned state"
        )


def _blocked_preflight(
    case: MaterializedMediaPoolCase,
    code: str,
    reason: str,
) -> MediaPoolPreflight:
    return MediaPoolPreflight(
        scenario_id=case.scenario_id,
        status="BLOCKED",
        code=code,
        reason=reason,
        create_calls=(),
        isolation=None,
    )


def media_answer_requires_order(scenario_id: str) -> bool:
    """Return whether the user prompt explicitly requires a global row order."""

    if scenario_id not in MEDIA_POOL_CASE_IDS:
        raise MediaPoolRuntimeError(
            f"unknown Media Pool scenario order policy: {scenario_id}"
        )
    return scenario_id in MEDIA_POOL_ORDERED_CASE_IDS


def media_near_classification(
    text: str,
    filenames: Sequence[str] | str,
    *,
    referenced: bool,
) -> bool:
    """Classify one reported filename from nearby natural-language prose.

    Inline prose wins, otherwise a list item inherits its nearest preceding
    section label.  Code spans, filenames, and identifier fragments such as
    ``UnusedAuditRefs`` cannot prove a referenced/unreferenced classification.
    """

    folded = text.casefold()
    accepted = (filenames,) if isinstance(filenames, str) else tuple(filenames)
    normalized = tuple(
        value.casefold()
        for value in accepted
        if isinstance(value, str) and value
    )
    if not normalized:
        return False
    lines = folded.splitlines()
    target_index = next(
        (
            index
            for index, line in enumerate(lines)
            if any(filename in line for filename in normalized)
        ),
        None,
    )
    if target_index is None:
        return False

    positive = ("仍被", "被引用", "使用中", "referenced", "in use")
    negative = (
        "未引用",
        "未被引用",
        "无引用",
        "没有任何",
        "unreferenced",
        "not referenced",
        "unused",
        "not in use",
    )

    def marker_class(value: str) -> bool | None:
        prose = re.sub(r"`[^`]*`", "", value)
        for filename in normalized:
            prose = prose.replace(filename, "")

        def contains_marker(marker: str) -> bool:
            if marker.isascii():
                return (
                    re.search(
                        rf"(?<![a-z0-9_]){re.escape(marker)}(?![a-z0-9_])",
                        prose,
                    )
                    is not None
                )
            return marker in prose

        if any(contains_marker(marker) for marker in negative):
            return False
        if any(contains_marker(marker) for marker in positive):
            return True
        return None

    for index in range(target_index, min(len(lines), target_index + 2)):
        classification = marker_class(lines[index])
        if classification is not None:
            return classification is referenced
    for index in range(target_index - 1, max(-1, target_index - 13), -1):
        classification = marker_class(lines[index])
        if classification is not None:
            return classification is referenced
    return False


def media_grouped_report_failures(
    text: str,
    *,
    expected_groups: Mapping[str, Sequence[str]],
    rows: Mapping[str, MediaReportRowExpectation],
    excluded_keys: Sequence[str] = (),
) -> tuple[str, ...]:
    """Validate a grouped Media Pool report without imposing internal prose.

    The reviewed fixture stores groups as ``Scene|Take`` keys, but that is an
    oracle encoding rather than a user-facing output format.  A report may use
    that exact form, a natural ``Scene / Take 01`` heading, an explicit
    ``Scene: ..., Take: ...`` heading, a natural ``Scene + Take 01`` heading,
    or an equivalent Markdown table row.
    Scene and Take must still occur together on one bounded line.

    Each group is a structural block ending at the next recognized group.  A
    member counts only when one item block contains its exact sealed database
    name and complete Path (slash direction and case may differ).  This keeps
    natural formatting flexible while preventing cross-group membership swaps,
    database swaps, basename-only answers, and ellipsized paths from passing.
    """

    if not isinstance(text, str):
        raise MediaPoolRuntimeError("Media Pool final report must be text")
    normalized_groups: dict[str, tuple[str, ...]] = {}
    group_parts: dict[str, tuple[str, str]] = {}
    for raw_group, raw_keys in expected_groups.items():
        group = _required_string(raw_group, field="expected_groups.key")
        parts = tuple(part.strip() for part in group.split("|"))
        if len(parts) != 2 or not all(parts):
            raise MediaPoolRuntimeError(
                "grouped Media Pool report keys must be exact Scene|Take pairs"
            )
        keys = tuple(
            _required_string(item, field=f"expected_groups[{group!r}]")
            for item in raw_keys
        )
        if not keys or len(keys) != len(set(keys)):
            raise MediaPoolRuntimeError(
                f"grouped Media Pool report group {group} has invalid members"
            )
        normalized_groups[group] = keys
        group_parts[group] = (parts[0], parts[1])

    grouped_keys = tuple(
        key for keys in normalized_groups.values() for key in keys
    )
    excluded = tuple(
        _required_string(item, field="excluded_keys[]") for item in excluded_keys
    )
    if len(grouped_keys) != len(set(grouped_keys)):
        raise MediaPoolRuntimeError(
            "grouped Media Pool report assigns a member to multiple groups"
        )
    required_row_keys = {*grouped_keys, *excluded}
    if not required_row_keys.issubset(rows):
        missing = sorted(required_row_keys - set(rows))
        raise MediaPoolRuntimeError(
            f"grouped Media Pool report has no row identities for {missing}"
        )
    for key in required_row_keys:
        row = rows[key]
        if row.key != key:
            raise MediaPoolRuntimeError(
                f"grouped Media Pool report row key drifted for {key}"
            )
        if (
            not row.filenames
            or any(not isinstance(item, str) or not item for item in row.filenames)
            or not isinstance(row.database, str)
            or not row.database
            or not isinstance(row.path, str)
            or not row.path
        ):
            raise MediaPoolRuntimeError(
                f"grouped Media Pool report row {key} is incomplete"
            )

    lines = text.splitlines()
    combined_table_cells = _media_report_combined_group_table_cells(lines)
    raw_anchors: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        matches = tuple(
            group
            for group, (scene, take) in group_parts.items()
            if _media_report_line_has_group(line, scene=scene, take=take)
            or (
                index in combined_table_cells
                and _media_report_combined_group_cell_matches(
                    combined_table_cells[index],
                    scene=scene,
                    take=take,
                )
            )
        )
        # A line naming more than one group is a summary, not a structural
        # group heading.  It cannot bind the member rows that follow.
        if len(matches) == 1:
            raw_anchors.append((index, matches[0]))

    runs: list[tuple[int, int, str]] = []
    for index, group in raw_anchors:
        if runs and runs[-1][2] == group:
            continue
        if runs:
            start, _end, previous = runs[-1]
            runs[-1] = (start, index, previous)
        runs.append((index, len(lines), group))

    failures: list[str] = []
    all_grouped = set(grouped_keys)
    for key in excluded:
        if _media_report_block_has_complete_row(lines, rows[key], rows):
            failures.append(
                f"final response includes complete excluded Media Pool row {key}"
            )
    for group, keys in normalized_groups.items():
        candidates = [item for item in runs if item[2] == group]
        if not candidates:
            failures.append(
                f"final response omits a closed Scene/Take heading for {group}"
            )
            continue
        valid_candidates = 0
        for start, end, _candidate_group in candidates:
            block = lines[start:end]
            complete = {
                key
                for key in (*grouped_keys, *excluded)
                if _media_report_block_has_complete_row(block, rows[key], rows)
            }
            if set(keys).issubset(complete) and not (
                complete & ((all_grouped - set(keys)) | set(excluded))
            ):
                valid_candidates += 1
        if valid_candidates == 0:
            failures.append(
                f"group {group} does not bind its exact members, databases, and full paths"
            )
        elif valid_candidates > 1:
            failures.append(f"group {group} has ambiguous duplicate result blocks")
    return tuple(failures)


def _media_report_line_has_group(line: str, *, scene: str, take: str) -> bool:
    scene_token = _media_report_token_pattern(scene)
    take_token = _media_report_token_pattern(take)
    decoration = r"[`*_~\s/+,:：;；#|—–\-()\[\]{}]"
    canonical = rf"{scene_token}[`*_~\s]*\|[`*_~\s]*{take_token}"
    natural = (
        rf"{scene_token}{decoration}{{1,48}}"
        rf"(?<!\w)take(?!\w){decoration}{{0,24}}{take_token}"
    )
    explicit = (
        rf"(?<!\w)scene(?!\w){decoration}{{0,24}}{scene_token}"
        rf"{decoration}{{1,48}}(?<!\w)take(?!\w)"
        rf"{decoration}{{0,24}}{take_token}"
    )
    reverse = (
        rf"(?<!\w)take(?!\w){decoration}{{0,24}}{take_token}"
        rf"{decoration}{{1,48}}(?<!\w)scene(?!\w)"
        rf"{decoration}{{0,24}}{scene_token}"
    )
    return any(
        re.search(pattern, line, flags=re.IGNORECASE) is not None
        for pattern in (canonical, natural, explicit, reverse)
    )


def _media_report_combined_group_table_cells(
    lines: Sequence[str],
) -> Mapping[int, str]:
    result: dict[int, str] = {}
    for header_index in range(max(0, len(lines) - 1)):
        header = _media_report_markdown_cells(lines[header_index])
        separator = _media_report_markdown_cells(lines[header_index + 1])
        if (
            header is None
            or separator is None
            or len(header) != len(separator)
            or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)
        ):
            continue
        group_columns = tuple(
            index
            for index, cell in enumerate(header)
            if _media_report_contains_token(cell, "Scene")
            and _media_report_contains_token(cell, "Take")
        )
        if len(group_columns) != 1:
            continue
        group_column = group_columns[0]
        row_index = header_index + 2
        while row_index < len(lines):
            cells = _media_report_markdown_cells(lines[row_index])
            if cells is None or len(cells) != len(header):
                break
            result[row_index] = cells[group_column]
            row_index += 1
    return MappingProxyType(result)


def _media_report_markdown_cells(line: str) -> tuple[str, ...] | None:
    value = line.strip()
    if not value.startswith("|") or not value.endswith("|"):
        return None
    cells = tuple(item.strip() for item in value[1:-1].split("|"))
    if not cells or any(not item for item in cells):
        return None
    return cells


def _media_report_combined_group_cell_matches(
    cell: str,
    *,
    scene: str,
    take: str,
) -> bool:
    scene_token = _media_report_token_pattern(scene)
    take_token = _media_report_token_pattern(take)
    decoration = r"[`*_~\s/+,:：;；#—–\-()\[\]{}]"
    return (
        re.search(
            rf"{scene_token}{decoration}{{1,32}}{take_token}",
            cell,
            flags=re.IGNORECASE,
        )
        is not None
    )


def _media_report_token_pattern(value: str) -> str:
    return rf"(?<!\w){re.escape(value)}(?!\w)"


def _media_report_block_has_complete_row(
    block: Sequence[str],
    row: MediaReportRowExpectation,
    all_rows: Mapping[str, MediaReportRowExpectation],
) -> bool:
    path_lines: list[tuple[int, str]] = []
    for index, line in enumerate(block):
        matches = tuple(
            key
            for key, candidate in all_rows.items()
            if _normalized_report_path(candidate.path)
            in _normalized_report_path(line)
        )
        if len(matches) == 1:
            path_lines.append((index, matches[0]))

    previous_path_line = -1
    for index, key in path_lines:
        if key != row.key:
            previous_path_line = index
            continue
        item = "\n".join(block[previous_path_line + 1 : index + 1])
        observed_databases = {
            candidate.database
            for candidate in all_rows.values()
            if _media_report_contains_token(item, candidate.database)
        }
        if observed_databases == {row.database}:
            return True
        previous_path_line = index
    return False


def _media_report_contains_token(text: str, value: str) -> bool:
    return (
        re.search(_media_report_token_pattern(value), text, flags=re.IGNORECASE)
        is not None
    )


def _normalized_report_path(value: str) -> str:
    return value.replace("/", "\\").casefold()


def build_semantic_answer(case: MaterializedMediaPoolCase) -> SemanticAnswerPlan:
    """Build the canonical sealed answer plan from reviewed fixture evidence."""

    expected_assets = [case.asset(key) for key in case.expected_file_keys]
    if case.scenario_id == "VS25-F-MEDIAPOOL-GET-01":
        ordered = tuple(
            item.key
            for item in sorted(
                expected_assets,
                key=lambda item: (item.parsed.duration_seconds, str(item.relative_path)),
            )
        )
    elif case.scenario_id == "VS25-F-MEDIAPOOL-GET-02":
        ordered = tuple(
            item.key for item in sorted(expected_assets, key=lambda item: str(item.relative_path))
        )
    elif case.scenario_id == "VS25-F-MEDIAPOOL-GET-03":
        ordered = tuple(
            key
            for group_keys in case.expected_groups.values()
            for key in group_keys
        )
    elif case.scenario_id == "VS25-F-MEDIAPOOL-GET-04":
        association = case.association_expectations or {}
        ordered = (
            *tuple(association.get("referenced", ())),
            *tuple(association.get("unreferenced", ())),
        )
    elif case.scenario_id == "VS25-F-MEDIAPOOL-GET-05":
        ordered = tuple(
            item.key
            for item in sorted(
                expected_assets,
                key=lambda item: (-item.parsed.duration_seconds, str(item.relative_path)),
            )
        )
    else:  # pragma: no cover - materializer rejects IDs first
        raise MediaPoolRuntimeError(f"no semantic order for {case.scenario_id}")
    if len(ordered) != len(case.expected_file_keys) or set(ordered) != set(
        case.expected_file_keys
    ):
        raise MediaPoolRuntimeError(
            f"semantic answer plan does not close expected keys for {case.scenario_id}"
        )
    association = case.association_expectations or {}
    post_filter = case.request_template.get("post_filter")
    max_results = int(
        post_filter["limit"]
        if isinstance(post_filter, Mapping)
        else case.request_template["args"]["maxResults"]
    )
    return SemanticAnswerPlan(
        ordered_keys=ordered,
        expected_groups=case.expected_groups,
        referenced_keys=tuple(association.get("referenced", ())),
        unreferenced_keys=tuple(association.get("unreferenced", ())),
        excluded_keys=case.excluded_file_keys,
        max_results=max_results,
    )


def _evaluate_fixture_query(
    staged: StagedMediaPoolCase,
    request: BoundMediaPoolRequest,
) -> tuple[str, ...]:
    """Evaluate the closed field-filter subset from parsed fixture evidence."""

    databases = tuple(request.args["databases"])
    filters = tuple(request.args["filters"])
    matches: list[str] = []
    for item in staged.assets:
        database = staged.materialized.database(item.asset.database_key)
        if database.wwise_path not in databases:
            continue
        if all(_fixture_filter_matches(item, request.binding, value) for value in filters):
            matches.append(item.asset.key)
    max_results = request.args["maxResults"]
    if len(matches) > max_results:
        raise MediaPoolRuntimeError(
            "fixture query has more matches than maxResults and cannot form an exact oracle"
        )
    return tuple(matches)


def _apply_fixture_post_filter(
    staged: StagedMediaPoolCase,
    request: BoundMediaPoolRequest,
    candidate_keys: Sequence[str],
) -> tuple[str, ...]:
    """Evaluate the closed business post-filter over server candidates."""

    if request.post_filter is None:
        return tuple(candidate_keys)
    post_filter = request.post_filter
    field = _required_string(post_filter.get("field"), field="post_filter.field")
    operator = _required_string(
        post_filter.get("operator"),
        field="post_filter.operator",
    )
    expected = _required_string(post_filter.get("value"), field="post_filter.value")
    limit = post_filter.get("limit")
    if operator != "containsCaseSensitive":
        raise MediaPoolRuntimeError(f"unsupported Media Pool post-filter: {operator}")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise MediaPoolRuntimeError("Media Pool post-filter limit is invalid")
    by_key = {item.asset.key: item for item in staged.assets}
    matches: list[str] = []
    for key in candidate_keys:
        try:
            item = by_key[key]
        except KeyError as exc:
            raise MediaPoolRuntimeError(
                f"post-filter candidate does not name a staged asset: {key}"
            ) from exc
        actual = _fixture_field_value(item, request.binding, field)
        if not isinstance(actual, str):
            raise MediaPoolRuntimeError(
                f"post-filter field {field!r} is not a string"
            )
        if expected in actual:
            matches.append(key)
            if len(matches) == limit:
                break
    return tuple(matches)


def _fixture_filter_matches(
    item: StagedMediaAsset,
    binding: MediaPoolFieldBinding,
    raw_filter: Any,
) -> bool:
    row = _mapping(raw_filter, field="request.filters[]")
    if set(row) != {"type", "field", "operator", "value"} or row.get("type") != "field":
        raise MediaPoolRuntimeError("Media Pool fixture evaluator accepts only closed field filters")
    field = _required_string(row.get("field"), field="request.filters[].field")
    operator = _required_string(row.get("operator"), field="request.filters[].operator")
    actual = _fixture_field_value(item, binding, field)
    expected = row.get("value")
    if operator in {"equals", "notEquals"}:
        equal = _same_media_value(actual, expected)
        return equal if operator == "equals" else not equal
    if operator in {"contains", "startsWith", "endsWith", "matchesRegex"}:
        if not isinstance(actual, str) or not isinstance(expected, str):
            raise MediaPoolRuntimeError(f"text operator {operator} requires string values")
        if operator == "contains":
            # Wwise 2025.1.7 evaluates Media Pool ``contains`` without case
            # sensitivity.  Case-sensitive business intent is represented by
            # the separately sealed gateway post-filter.
            return expected.casefold() in actual.casefold()
        if operator == "startsWith":
            return actual.startswith(expected)
        if operator == "endsWith":
            return actual.endswith(expected)
        try:
            return re.search(expected, actual) is not None
        except re.error as exc:
            raise MediaPoolRuntimeError("fixture request contains an invalid regex") from exc
    comparisons = {
        "lessThan": lambda left, right: left < right,
        "greaterThan": lambda left, right: left > right,
        "lessThanOrEqual": lambda left, right: left <= right,
        "greaterThanOrEqual": lambda left, right: left >= right,
    }
    if operator not in comparisons:
        raise MediaPoolRuntimeError(f"unreviewed Media Pool field operator: {operator}")
    if (
        not isinstance(actual, (int, float))
        or isinstance(actual, bool)
        or not isinstance(expected, (int, float))
        or isinstance(expected, bool)
    ):
        raise MediaPoolRuntimeError(f"numeric operator {operator} requires numeric values")
    return comparisons[operator](float(actual), float(expected))


def _fixture_field_value(
    item: StagedMediaAsset,
    binding: MediaPoolFieldBinding,
    field: str,
) -> Any:
    concepts = {
        exact: concept for concept, exact in binding.by_concept.items()
    }
    try:
        concept = concepts[field]
    except KeyError as exc:
        raise MediaPoolRuntimeError(
            f"fixture request uses an unbound Media Pool field: {field}"
        ) from exc
    if concept == "name":
        return _media_pool_filename(item.indexed_host_path)
    if concept == "duration":
        return item.asset.parsed.duration_seconds
    if concept == "sample_rate":
        return item.asset.parsed.sample_rate
    if concept == "channels":
        return item.asset.parsed.channels
    if concept == "bit_depth":
        return item.asset.parsed.bit_depth
    if concept == "scene":
        return _ixml_value(item.asset.parsed, "SCENE")
    if concept == "take":
        return _ixml_value(item.asset.parsed, "TAKE")
    raise MediaPoolRuntimeError(f"unreviewed fixture field concept: {concept}")


def _typed_audio_import_path(value: str) -> str:
    """Render reviewed 2025.1 audio.import creation types for case 04."""

    target = _required_string(value, field="rows.referenced_by")
    prefix = r"\Containers\Default Work Unit"
    if not target.casefold().startswith((prefix + "\\").casefold()):
        raise MediaPoolRuntimeError(
            "reference fixture target escaped the Default Work Unit"
        )
    suffix = target[len(prefix) + 1 :]
    parts = suffix.split("\\")
    if len(parts) < 2 or any(not part or "<" in part or ">" in part for part in parts):
        raise MediaPoolRuntimeError("reference fixture target path is malformed")
    containers = "".join(
        f"\\<Sequence Container>{part}" for part in parts[:-1]
    )
    return f"{prefix}{containers}\\<Sound SFX>{parts[-1]}"


def _verify_observed_metadata(
    row: Mapping[str, Any],
    asset: MediaAsset,
    binding: MediaPoolFieldBinding,
) -> None:
    expected: dict[str, Any] = {
        binding.exact("name"): _media_pool_filename(asset.source_path),
        binding.exact("duration"): asset.parsed.duration_seconds,
        binding.exact("sample_rate"): asset.parsed.sample_rate,
        binding.exact("channels"): asset.parsed.channels,
        binding.exact("bit_depth"): asset.parsed.bit_depth,
    }
    if "scene" in binding.by_concept:
        expected[binding.exact("scene")] = _ixml_value(asset.parsed, "SCENE")
        expected[binding.exact("take")] = _ixml_value(asset.parsed, "TAKE")
    for field, expected_value in expected.items():
        if field not in row or not _same_media_value(row[field], expected_value):
            actual_value = row.get(field, "<missing>")
            raise MediaPoolRuntimeError(
                f"live index value for {asset.key} field {field!r} does not "
                "match independently parsed WAV/iXML: "
                f"actual={_bounded_repr(actual_value)} "
                f"expected={_bounded_repr(expected_value)}"
            )


def _media_pool_filename(path: Path) -> str:
    """Return Wwise's extensionless Media Pool ``Filename`` field value."""

    return path.stem


def _bounded_repr(value: Any, *, limit: int = 160) -> str:
    rendered = repr(value)
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 3] + "..."


def _ixml_value(parsed: ParsedWav, suffix: str) -> str:
    matches = [
        value
        for field, value in parsed.ixml.items()
        if field.rsplit("/", 1)[-1].casefold() == suffix.casefold()
    ]
    if len(matches) != 1:
        raise MediaPoolRuntimeError(f"fixture iXML field {suffix} is not unique")
    return matches[0]


def _observed_row_matches_path(
    row: Mapping[str, Any],
    expected: Path,
    *,
    relative_root: Path,
    waapi_y_drive_root: Path | None,
) -> bool:
    value = row.get("Path")
    if not isinstance(value, str) or not value:
        return False
    try:
        localized = _localize_waapi_path(
            value,
            relative_root=relative_root,
            owned_root=expected.parent,
            waapi_y_drive_root=waapi_y_drive_root,
        )
    except MediaPoolRuntimeError:
        return False
    return localized == expected.resolve(strict=True)


def _localize_waapi_path(
    value: str,
    *,
    relative_root: Path | None = None,
    owned_root: Path | None = None,
    waapi_y_drive_root: Path | None = None,
) -> Path:
    """Map one closed WAAPI path without following aliases or guessing drives.

    On macOS, Wwise may expose host paths as POSIX, Wine ``Z:`` paths, a
    proven Wine ``Y:`` path, or a database-relative path.  Relative and ``Y:``
    paths are accepted only when the caller supplies their authoritative roots.
    """

    if not isinstance(value, str) or not value or "\x00" in value or value != value.strip():
        raise MediaPoolRuntimeError("WAAPI file path is malformed")
    try:
        windows_path = parse_windows_drive_path(value)
    except ReflectedHostPathError as exc:
        raise MediaPoolRuntimeError("WAAPI file path is malformed") from exc
    if windows_path is not None:
        drive = windows_path.drive
        parts = windows_path.relative_parts
        native = Path(windows_path.pure) if os.name == "nt" else None
        if native is not None and _available_directory(Path(native.anchor)):
            candidate = native
        elif drive == "Y" and waapi_y_drive_root is not None:
            candidate = _lexical_absolute_path(
                waapi_y_drive_root,
                field="Wine Y drive root",
            ).joinpath(*parts)
        elif drive == "Z":
            if os.name == "nt":
                raise MediaPoolRuntimeError(
                    "Wine Z: path has no native filesystem-root binding"
                )
            else:
                base = Path("/")
            candidate = base.joinpath(*parts)
        elif os.name == "nt":
            candidate = Path(windows_path.pure)
        else:
            raise MediaPoolRuntimeError(
                f"unreviewed WAAPI virtual drive in Media Pool result: {drive}:"
            )
    else:
        try:
            candidate = Path(parse_posix_absolute_path(value))
        except ReflectedHostPathError:
            if relative_root is None:
                raise MediaPoolRuntimeError(
                    "WAAPI Media Pool Path is not absolute"
                ) from None
            parts = _closed_relative_waapi_path_parts(value)
            candidate = _lexical_absolute_path(
                relative_root,
                field="Project Originals root",
            ).joinpath(*parts)

    boundary = (
        _lexical_absolute_path(owned_root, field="WAAPI path owned root")
        if owned_root is not None
        else Path(candidate.anchor)
    )
    return _require_real_owned_file(
        candidate,
        root=boundary,
        field="WAAPI file path",
    )


def _parse_native_windows_absolute_path(value: str) -> tuple[str, tuple[str, ...]]:
    """Parse a local-drive Windows path without host-dependent ``Path`` rules."""

    try:
        parsed = parse_windows_drive_path(value)
    except ReflectedHostPathError as exc:
        raise MediaPoolRuntimeError(
            "WAAPI file path is not drive-absolute"
        ) from exc
    if parsed is None:
        raise MediaPoolRuntimeError("WAAPI file path is not drive-absolute")
    return parsed.drive, parsed.relative_parts


def _available_directory(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _closed_relative_waapi_path_parts(value: str) -> tuple[str, ...]:
    if (
        value.endswith(("/", "\\"))
        or re.search(r"[\\/]{2}", value)
        or re.search(r"(?:^|[\\/])(?:\.{1,2})(?:[\\/]|$)", value)
    ):
        raise MediaPoolRuntimeError(
            "WAAPI file path contains an empty, dot, or escaping component"
        )
    pure = PureWindowsPath(value) if "\\" in value else PurePosixPath(value)
    if pure.anchor or pure.drive:
        raise MediaPoolRuntimeError("WAAPI file path is not relative")
    parts = tuple(pure.parts)
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise MediaPoolRuntimeError(
            "WAAPI file path contains an empty, dot, or escaping component"
        )
    return parts


def _require_real_owned_file(
    value: Path,
    *,
    root: Path,
    field: str,
) -> Path:
    root_path = _lexical_absolute_path(root, field=f"{field}.root")
    value_path = _lexical_absolute_path(value, field=field)
    try:
        relative = value_path.relative_to(root_path)
    except ValueError as exc:
        raise MediaPoolRuntimeError(f"{field} is outside case ownership") from exc
    paths = (
        root_path,
        *(
            root_path.joinpath(*relative.parts[:index])
            for index in range(1, len(relative.parts) + 1)
        ),
    )
    for index, current in enumerate(paths):
        try:
            info = current.lstat()
        except OSError as exc:
            raise MediaPoolRuntimeError(f"{field} is unavailable: {current}") from exc
        if path_is_link_or_reparse(current, metadata=info):
            raise MediaPoolRuntimeError(
                f"{field} contains a link or reparse point: {current}"
            )
        is_final = index == len(paths) - 1
        if is_final:
            if not stat.S_ISREG(info.st_mode):
                raise MediaPoolRuntimeError(f"{field} is not a regular file: {current}")
        elif not stat.S_ISDIR(info.st_mode):
            raise MediaPoolRuntimeError(f"{field} parent is not a directory: {current}")
    resolved_root = root_path.resolve(strict=True)
    resolved_value = value_path.resolve(strict=True)
    if (
        resolved_root != root_path
        or resolved_value != value_path
        or not _is_relative_to(resolved_value, resolved_root)
    ):
        raise MediaPoolRuntimeError(f"{field} did not retain its lexical owned path")
    return resolved_value


def _audit_request_template(scenario_id: str, template: Mapping[str, Any]) -> None:
    if set(template) not in (
        {"args", "options"},
        {"args", "options", "post_filter"},
    ):
        raise MediaPoolRuntimeError(
            f"{scenario_id} request template must contain args/options and optional post_filter"
        )
    args = _mapping(template["args"], field="request_template.args")
    options = _mapping(template["options"], field="request_template.options")
    if set(args) != {"databases", "filters", "maxResults"}:
        raise MediaPoolRuntimeError(
            f"{scenario_id} Media Pool args must use only databases/filters/maxResults"
        )
    if set(options) != {"return"}:
        raise MediaPoolRuntimeError(
            f"{scenario_id} Media Pool options must contain only return"
        )
    max_results = args.get("maxResults")
    if not isinstance(max_results, int) or isinstance(max_results, bool) or not 1 <= max_results <= 200:
        raise MediaPoolRuntimeError(f"{scenario_id} has an invalid maxResults")
    filters = _sequence(args.get("filters"), field="request_template.filters")
    if not filters or len(filters) > 16:
        raise MediaPoolRuntimeError(f"{scenario_id} exceeds the filter ceiling")
    databases = tuple(
        _required_string(value, field="request_template.databases[]")
        for value in _sequence(
            args.get("databases"), field="request_template.databases"
        )
    )
    if not databases or len(databases) > 8 or len(databases) != len(set(databases)):
        raise MediaPoolRuntimeError(f"{scenario_id} exceeds the database ceiling")
    for index, value in enumerate(filters):
        row = _mapping(value, field=f"request_template.filters[{index}]")
        if set(row) != {"type", "field", "operator", "value"}:
            raise MediaPoolRuntimeError(
                f"{scenario_id} filter {index} is outside the closed field-filter shape"
            )
        if row.get("type") != "field":
            raise MediaPoolRuntimeError(
                f"{scenario_id} filter {index} is not a field filter"
            )
        field = _required_string(
            row.get("field"), field=f"request_template.filters[{index}].field"
        )
        if _FIELD_TOKEN_RE.fullmatch(field) is None:
            raise MediaPoolRuntimeError(
                f"{scenario_id} filter {index} does not use a reviewed field concept"
            )
        if row.get("operator") not in MEDIA_POOL_FIELD_OPERATORS:
            raise MediaPoolRuntimeError(
                f"{scenario_id} filter {index} has an unreviewed operator"
            )
        compared = row.get("value")
        if (
            isinstance(compared, bool)
            or not isinstance(compared, (str, int, float))
            or (isinstance(compared, str) and not compared)
        ):
            raise MediaPoolRuntimeError(
                f"{scenario_id} filter {index} has an invalid comparison value"
            )
    returns = _sequence(options.get("return"), field="request_template.options.return")
    if not returns or len(returns) > 32 or len(set(returns)) != len(returns):
        raise MediaPoolRuntimeError(f"{scenario_id} return fields are invalid")
    for value in returns:
        field = _required_string(value, field="request_template.options.return[]")
        if field not in FIXED_RETURN_FIELDS and _FIELD_TOKEN_RE.fullmatch(field) is None:
            raise MediaPoolRuntimeError(
                f"{scenario_id} return projection uses an unreviewed field"
            )
    post_filter_raw = template.get("post_filter")
    if post_filter_raw is not None:
        post_filter = _mapping(
            post_filter_raw,
            field="request_template.post_filter",
        )
        if set(post_filter) != {"field", "operator", "value", "limit"}:
            raise MediaPoolRuntimeError(
                f"{scenario_id} post_filter is outside the closed shape"
            )
        field = _required_string(
            post_filter.get("field"),
            field="request_template.post_filter.field",
        )
        field_match = _FIELD_TOKEN_RE.fullmatch(field)
        if field_match is None or field_match.group(1) != "name":
            raise MediaPoolRuntimeError(
                f"{scenario_id} post_filter must use the reviewed Filename concept"
            )
        if post_filter.get("operator") not in MEDIA_POOL_POST_FILTER_OPERATORS:
            raise MediaPoolRuntimeError(
                f"{scenario_id} post_filter uses an unreviewed operator"
            )
        _required_string(
            post_filter.get("value"),
            field="request_template.post_filter.value",
        )
        limit = post_filter.get("limit")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= max_results
        ):
            raise MediaPoolRuntimeError(
                f"{scenario_id} post_filter limit must be within server maxResults"
            )
        matching_candidates = [
            row
            for row in filters
            if isinstance(row, Mapping)
            and row.get("type") == "field"
            and row.get("field") == field
            and row.get("operator") == "contains"
            and row.get("value") == post_filter.get("value")
        ]
        if max_results != 200 or len(matching_candidates) != 1:
            raise MediaPoolRuntimeError(
                f"{scenario_id} post_filter is not bound to one complete contains candidate request"
            )
    _request_field_concepts(template)


def _audit_bound_request(
    case: MaterializedMediaPoolCase,
    args: Mapping[str, Any],
    options: Mapping[str, Any],
    binding: MediaPoolFieldBinding,
    *,
    post_filter: Mapping[str, Any] | None,
) -> None:
    serialized = json.dumps(
        {"args": args, "options": options, "post_filter": post_filter},
        ensure_ascii=False,
    )
    if "{media_pool_fields." in serialized:
        raise MediaPoolRuntimeError("bound Media Pool request still contains a field token")
    databases = tuple(args["databases"])
    fixture_databases = {item.wwise_path for item in case.databases}
    if not set(databases).issubset(fixture_databases):
        raise MediaPoolRuntimeError("bound request escaped the case-owned databases")
    fields_used = {
        item["field"] for item in args["filters"] if item.get("type") == "field"
    } | (set(options["return"]) - FIXED_RETURN_FIELDS)
    if post_filter is not None:
        fields_used.add(post_filter["field"])
    if not fields_used.issubset(set(binding.by_concept.values())):
        raise MediaPoolRuntimeError("bound request contains a field absent from getFields")


def _request_field_concepts(template: Mapping[str, Any]) -> tuple[str, ...]:
    concepts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for nested in value.values():
                walk(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                walk(nested)
        elif isinstance(value, str):
            match = _FIELD_TOKEN_RE.fullmatch(value)
            if match:
                concepts.append(match.group(1))
            elif "{media_pool_fields." in value:
                raise MediaPoolRuntimeError(
                    f"Media Pool field token must occupy the full string: {value}"
                )

    walk(template)
    if not concepts:
        raise MediaPoolRuntimeError("Media Pool request template has no field bindings")
    return tuple(dict.fromkeys(concepts))


def _replace_field_tokens(value: Any, binding: MediaPoolFieldBinding) -> Any:
    if isinstance(value, Mapping):
        return {key: _replace_field_tokens(nested, binding) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_replace_field_tokens(nested, binding) for nested in value]
    if isinstance(value, str):
        match = _FIELD_TOKEN_RE.fullmatch(value)
        if match:
            return binding.exact(match.group(1))
    return value


def _write_pcm_ixml_wav(
    path: Path,
    *,
    key: str,
    sample_rate: int,
    channels: int,
    bit_depth: int,
    duration_seconds: float,
    ixml: Mapping[str, str],
) -> None:
    if channels not in {1, 2}:
        raise MediaPoolRuntimeError(f"fixture {key} uses unsupported channels={channels}")
    if bit_depth not in {16, 24}:
        raise MediaPoolRuntimeError(f"fixture {key} uses unsupported bit_depth={bit_depth}")
    frame_decimal = Decimal(str(duration_seconds)) * sample_rate
    if frame_decimal != frame_decimal.to_integral_value():
        raise MediaPoolRuntimeError(
            f"fixture {key} duration is not an integral sample count"
        )
    frame_count = int(frame_decimal)
    seed = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:4], "little")
    bytes_per_sample = bit_depth // 8
    frame_parts: list[bytes] = []
    maximum = (1 << (bit_depth - 2)) - 1
    for channel in range(channels):
        magnitude = 1 + ((seed + channel * 7919) % maximum)
        value = magnitude if channel % 2 == 0 else -magnitude
        frame_parts.append(value.to_bytes(bytes_per_sample, "little", signed=True))
    data = b"".join(frame_parts) * frame_count
    block_align = channels * bytes_per_sample
    fmt = struct.pack(
        "<HHIIHH",
        1,
        channels,
        sample_rate,
        sample_rate * block_align,
        block_align,
        bit_depth,
    )
    chunks = [_riff_chunk(b"fmt ", fmt)]
    if ixml:
        root = ET.Element("BWFXML")
        ET.SubElement(root, "IXML_VERSION").text = "2.0"
        ET.SubElement(root, "PROJECT").text = "waapi-skill-v3"
        user = ET.SubElement(root, "USER")
        for name, value in ixml.items():
            tag = name.upper()
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", tag):
                raise MediaPoolRuntimeError(f"fixture {key} has unsafe iXML tag {name!r}")
            # Wwise 2025 Media Pool's documented extension point is
            # BWFXML/USER.  SCENE and TAKE remain live-bound concepts, while
            # their exact returned path/case comes from getFields.
            ET.SubElement(user, tag).text = value
        # Wwise's Media Pool scanner follows the iXML interchange form, whose
        # XML payload begins with an explicit UTF-8 declaration.  A bare root
        # is valid to generic XML parsers but was ignored by the real 2025.1
        # Media Pool indexer.
        xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>\r'
            + ET.tostring(root, encoding="utf-8")
        )
        # The iXML interchange contract requires an even payload byte count;
        # its padding is an ASCII space inside the chunk size, not RIFF's
        # generic out-of-band NUL pad byte.
        if len(xml) & 1:
            xml += b" "
        chunks.append(_riff_chunk(b"iXML", xml))
    chunks.append(_riff_chunk(b"data", data))
    body = b"WAVE" + b"".join(chunks)
    payload = b"RIFF" + struct.pack("<I", len(body)) + body
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)


def _riff_chunk(chunk_id: bytes, payload: bytes) -> bytes:
    if len(chunk_id) != 4:
        raise AssertionError("RIFF chunk ID must contain four bytes")
    return chunk_id + struct.pack("<I", len(payload)) + payload + (b"\0" if len(payload) & 1 else b"")


def _parse_ixml(payload: bytes, file_path: Path) -> dict[str, str]:
    try:
        root = ET.fromstring(payload.decode("utf-8"))
    except (UnicodeDecodeError, ET.ParseError) as exc:
        raise MediaPoolRuntimeError(f"invalid UTF-8 iXML in {file_path}") from exc
    if root.tag != "BWFXML":
        raise MediaPoolRuntimeError(f"iXML root is not BWFXML: {file_path}")
    result: dict[str, str] = {}

    def visit(node: ET.Element, prefix: str) -> None:
        children = list(node)
        path = f"{prefix}/{node.tag}" if prefix else node.tag
        if children:
            for child in children:
                visit(child, path)
            return
        value = node.text or ""
        if path in result:
            raise MediaPoolRuntimeError(f"duplicate iXML leaf {path}: {file_path}")
        result[path] = value

    visit(root, "")
    return result


def _same_media_value(actual: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and abs(float(actual) - expected) <= 1e-6
    return actual == expected


def _fingerprint_paths(roots: set[Path]) -> TreeFingerprint:
    if not roots:
        raise MediaPoolRuntimeError("aggregate fingerprint requires roots")
    digest = hashlib.sha256()
    files: dict[Path, bytes] = {}
    for root in roots:
        resolved = root.resolve(strict=True)
        for item in resolved.rglob("*"):
            if item.is_symlink():
                raise MediaPoolRuntimeError(
                    f"staged Media Pool tree contains a symlink: {item}"
                )
            if item.is_file() and not item.is_symlink():
                files[item.resolve(strict=True)] = item.read_bytes()
    for path in sorted(files, key=str):
        data = files[path]
        digest.update(str(path).encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(data).digest())
    common = Path(os.path.commonpath([str(path) for path in roots])).resolve(strict=True)
    return TreeFingerprint(
        root=common,
        exists=True,
        sha256=digest.hexdigest(),
        file_count=len(files),
        byte_count=sum(len(value) for value in files.values()),
    )


def _lexical_absolute_path(value: Path, *, field: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise MediaPoolRuntimeError(f"{field} must be absolute")
    if "\x00" in str(candidate):
        raise MediaPoolRuntimeError(f"{field} contains NUL")
    return Path(os.path.abspath(os.path.normpath(str(candidate))))


def _require_real_directory_chain(
    value: Path,
    *,
    root: Path,
    field: str,
) -> Path:
    root_path = _lexical_absolute_path(root, field=f"{field}.root")
    value_path = _lexical_absolute_path(value, field=field)
    try:
        relative = value_path.relative_to(root_path)
    except ValueError as exc:
        raise MediaPoolRuntimeError(f"{field} is outside case ownership") from exc
    current = root_path
    paths = (root_path, *(root_path.joinpath(*relative.parts[:index]) for index in range(1, len(relative.parts) + 1)))
    for current in paths:
        try:
            info = current.lstat()
        except OSError as exc:
            raise MediaPoolRuntimeError(
                f"{field} directory is unavailable: {current}"
            ) from exc
        if path_is_link_or_reparse(current, metadata=info):
            raise MediaPoolRuntimeError(
                f"{field} contains a link or reparse point: {current}"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise MediaPoolRuntimeError(f"{field} is not a directory: {current}")
    resolved_root = root_path.resolve(strict=True)
    resolved_value = value_path.resolve(strict=True)
    if resolved_value != value_path or not _is_relative_to(resolved_value, resolved_root):
        raise MediaPoolRuntimeError(f"{field} did not retain its lexical owned path")
    return resolved_value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(nested) for key, nested in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(nested) for nested in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise MediaPoolRuntimeError(f"non-JSON value in closed Media Pool contract: {type(value).__name__}")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(nested) for nested in value]
    return value


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MediaPoolRuntimeError(f"{field} must be an object")
    return value


def _mapping_rows(value: Any, *, field: str) -> tuple[Mapping[str, Any], ...]:
    return tuple(_mapping(item, field=f"{field}[]") for item in _sequence(value, field=field))


def _sequence(value: Any, *, field: str) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
        raise MediaPoolRuntimeError(f"{field} must be an array")
    return tuple(value)


def _required_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise MediaPoolRuntimeError(f"{field} must be a non-empty exact string")
    return value


def _required_guid(value: Any, *, field: str) -> str:
    text = _required_string(value, field=field)
    if not _GUID_RE.fullmatch(text):
        raise MediaPoolRuntimeError(f"{field} must be a braced GUID")
    return text.upper()


def _positive_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MediaPoolRuntimeError(f"{field} must be a positive integer")
    return value


def _positive_number(value: Any, *, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise MediaPoolRuntimeError(f"{field} must be a positive number")
    return float(value)


def _string_mapping(value: Any, *, field: str) -> Mapping[str, str]:
    mapping = _mapping(value, field=field)
    return MappingProxyType(
        {
            _required_string(key, field=f"{field}.key"): _required_string(
                item, field=f"{field}.value"
            )
            for key, item in mapping.items()
        }
    )


def _safe_relative(value: Any, *, field: str) -> PurePosixPath:
    text = _required_string(value, field=field)
    if "\\" in text:
        raise MediaPoolRuntimeError(f"{field} must use forward-slash separators")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise MediaPoolRuntimeError(f"{field} must be a safe relative path")
    if path.suffix.casefold() != ".wav":
        raise MediaPoolRuntimeError(f"{field} must end in .wav")
    return path


def _require_unique(values: Sequence[Any], *, field: str) -> None:
    if len(values) != len(set(values)):
        raise MediaPoolRuntimeError(f"{field} must be unique")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _paths_overlap(left: Path, right: Path) -> bool:
    return _is_relative_to(left, right) or _is_relative_to(right, left)


__all__ = [
    "CUSTOM_DATABASE_CLEANUP_CONTRACT",
    "CUSTOM_DATABASE_PROOF_CONTRACT",
    "MEDIA_POOL_CASE_IDS",
    "MEDIA_POOL_CANONICAL_RETURN_FIELDS",
    "MEDIA_POOL_CLOSED_GROUP_REPORT_CASE_ID",
    "MEDIA_POOL_ORDERED_CASE_IDS",
    "MEDIA_POOL_GET_FIELDS_URI",
    "MEDIA_POOL_GET_URI",
    "MEDIA_POOL_POST_FILTER_OPERATORS",
    "REFERENCE_MATCH_SCAN_LIMIT",
    "REFERENCE_MATCH_RESULT_CONTRACT",
    "MACOS_WWISE_WINE_PREFIX_RELATIVE",
    "OBJECT_DELETE_URI",
    "OBJECT_GET_URI",
    "OBJECT_SET_URI",
    "PROJECT_ORIGINALS_PATH",
    "STANDARD_FIELDS",
    "SUPPORTED_BUILD",
    "WINE_C_DRIVE_TARGET",
    "WINE_Z_DRIVE_TARGET",
    "USER_DATABASES_GUID",
    "USER_DATABASES_PATH",
    "BoundMediaPoolRequest",
    "CustomDatabaseCleanupProof",
    "CustomDatabaseHost",
    "CustomDatabaseIsolation",
    "CustomDatabaseRoundTripProof",
    "MacOSWineCustomDatabaseHost",
    "NativeWindowsCustomDatabaseHost",
    "MaterializedMediaPoolCase",
    "MediaAsset",
    "MediaDatabaseFixture",
    "MediaPoolFieldBinding",
    "MediaPoolPreflight",
    "MediaReportRowExpectation",
    "MediaPoolRuntimeError",
    "ParsedWav",
    "SealedMediaPoolOracle",
    "SealedMediaRow",
    "SemanticAnswerPlan",
    "StagedMediaAsset",
    "StagedMediaPoolCase",
    "TreeFingerprint",
    "VerificationResult",
    "WaapiCall",
    "bind_media_pool_fields",
    "bind_media_pool_request",
    "apply_media_pool_post_filter",
    "build_semantic_answer",
    "build_custom_database_create_calls",
    "build_custom_database_delete_calls",
    "build_index_probe_calls",
    "build_reference_fixture_call",
    "build_reference_match_gateway_argv",
    "build_reference_read_call",
    "custom_database_payload_shape_sha256",
    "custom_database_round_trip_evidence",
    "fingerprint_tree",
    "fingerprint_staged_media_assets",
    "host_directory_to_native_windows_path",
    "host_directory_to_wine_z_path",
    "expected_macos_wine_prefix",
    "get_fields_gateway_argv",
    "materialize_media_pool_case",
    "media_answer_requires_order",
    "media_near_classification",
    "media_grouped_report_failures",
    "media_pool_preflight",
    "parse_custom_database_create_results",
    "parse_pcm_ixml_wav",
    "resolve_macos_wine_y_drive_root",
    "reference_match_paths",
    "seal_media_pool_index",
    "stage_media_pool_case",
    "validate_macos_wine_prefix",
    "verify_custom_database_cleanup",
    "verify_media_pool_read_unchanged",
    "verify_media_pool_candidate_result",
    "verify_media_pool_result",
    "verify_reference_associations",
    "verify_reference_match_agent_result",
    "verify_reference_match_result",
    "verify_semantic_report",
]
