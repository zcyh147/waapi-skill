#!/usr/bin/env python3
"""Seal one integration-workflows-v2 committed SampleProject baseline.

The collector connects only to an already-running matching Wwise process whose
project is an explicitly named sandbox copy.  It performs live reads exclusively
through the public Skill Gateway CLI, leaves the committed source fixture closed,
and never starts Wwise, mutates a project, or imports/calls ``WaapiClient``.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from tests.semantic.support.codex_campaign import (  # noqa: E402
    CampaignEvidenceError,
    canonical_json_bytes,
    sha256_file,
)
from tests.semantic.support.codex_integration_fixture_tree_v2 import (  # noqa: E402
    IntegrationFixtureTreeError,
    wwise_fixture_tree_sha256,
)
from tests.semantic.support.codex_integration_footsteps_runtime_v2 import (  # noqa: E402
    FOOTSTEPS_CANONICAL_STATE_FIELDS,
)
from tests.semantic.support.codex_integration_rifle_runtime_v2 import (  # noqa: E402
    RIFLE_CANONICAL_STATE_FIELDS,
)
from tests.semantic.support.codex_integration_weapons_runtime_v2 import (  # noqa: E402
    WEAPONS_CANONICAL_STATE_FIELDS,
)
from tests.semantic.support.codex_integration_workflows_v2 import (  # noqa: E402
    BASELINE_MANIFEST_CONTRACT,
    BaselineLayout,
    ObjectSpec,
    WorkflowProfile,
    load_integration_workflows_v2_profile,
)
from wwise_waapi.host_paths import (  # noqa: E402
    HostPathError,
    localize_waapi_host_path,
    parse_absolute_host_path,
)


SUPPORTED_VERSIONS = ("2022.1", "2025.1")
PROFILE_PATH = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "integration-workflows-v2"
    / "profile.json"
)
GATEWAY_RUNNER = SKILL_ROOT / "scripts" / "run.py"
GET_ASSIGNMENTS_API = "ak.wwise.core.switchContainer.getAssignments"
MAINTENANCE_CONTRACT = (
    "waapi-skill.integration-workflows-v2-baseline-maintenance/v1"
)
_GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
_MAX_OBJECT_ROWS = 64
_MAX_ASSIGNMENT_ROWS = 32
_MAX_RTPC_ROWS = 32
_RTPC_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "notes",
    "@PropertyName",
    "@ControlInput",
    "@Curve",
)
_SOURCE_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "parent",
    "notes",
    "originalFilePath",
    "audioSource:language",
)
_IDENTITY_FIELDS = {
    "parent",
    "SwitchGroupOrStateGroup",
    "activeSource",
    "Target",
}


class IntegrationBaselineCollectionError(RuntimeError):
    """The live baseline could not be sealed without ambiguity."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


GatewayCommandRunner = Callable[[tuple[str, ...]], CommandResult]


@dataclass(frozen=True, slots=True)
class BaselineCollection:
    version: str
    manifest_path: Path
    payload: Mapping[str, Any]

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.payload)).hexdigest()

    def summary(self, *, wrote: bool) -> dict[str, Any]:
        return {
            "contract": MAINTENANCE_CONTRACT,
            "ok": True,
            "mode": "write" if wrote else "preview",
            "repository_write_performed": wrote,
            "version": self.version,
            "manifest_path": str(self.manifest_path),
            "object_count": len(self.payload["objects"]),
            "media_count": len(self.payload["media"]),
            "storage_file_count": len(self.payload["storage_files"]),
            "manifest_sha256": self.manifest_sha256,
        }


class PublicGateway:
    """Small subprocess boundary around the packaged public Gateway CLI."""

    def __init__(
        self,
        *,
        version: str,
        host: str | None = None,
        port: int | None = None,
        timeout_seconds: float = 30.0,
        runner: GatewayCommandRunner | None = None,
        gateway_runner: Path = GATEWAY_RUNNER,
    ) -> None:
        if version not in SUPPORTED_VERSIONS:
            raise IntegrationBaselineCollectionError(
                f"Unsupported integration baseline version {version!r}"
            )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int | float)
            or not math.isfinite(float(timeout_seconds))
            or float(timeout_seconds) <= 0
        ):
            raise IntegrationBaselineCollectionError(
                "Gateway timeout must be one positive finite number"
            )
        self.version = version
        self.host = host
        self.port = port
        self.timeout_seconds = float(timeout_seconds)
        self.gateway_runner = gateway_runner.resolve(strict=False)
        self._runner = runner or self._run_subprocess

    def status(self) -> Mapping[str, Any]:
        return self._invoke(("status",), expected_command="status")

    def query_path(
        self,
        path: str,
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        arguments: list[str] = ["query-object", "--path", path]
        for field in _closed_fields(fields):
            arguments.extend(("--return-field", field))
        payload = self._invoke(tuple(arguments), expected_command="query-object")
        return _object_rows(payload, "query-object path", _MAX_OBJECT_ROWS)

    def query_id(
        self,
        object_id: str,
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        arguments: list[str] = [
            "query-object",
            "--object-id",
            _guid(object_id, "object id"),
        ]
        for field in _closed_fields(fields):
            arguments.extend(("--return-field", field))
        payload = self._invoke(tuple(arguments), expected_command="query-object")
        return _object_rows(payload, "query-object id", _MAX_OBJECT_ROWS)

    def query_ids(
        self,
        object_ids: Sequence[str],
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        ids = tuple(_guid(value, "object id") for value in object_ids)
        if not ids or len(ids) > _MAX_RTPC_ROWS:
            raise IntegrationBaselineCollectionError(
                "multi-id query is empty or exceeds the RTPC ceiling"
            )
        if len({value.casefold() for value in ids}) != len(ids):
            raise IntegrationBaselineCollectionError(
                "multi-id query contains duplicate GUIDs"
            )
        request = {
            "contract": "waapi-skill.object-query/v1",
            "source": {
                "kind": "object",
                "objects": [
                    {"kind": "id", "value": value} for value in ids
                ],
            },
            "transforms": [{"kind": "take", "value": len(ids)}],
            "return": list(_closed_fields(fields)),
        }
        payload = self._invoke(
            (
                "query-object",
                "--request-json",
                _compact_json(request),
            ),
            expected_command="query-object",
        )
        return _object_rows(payload, "query-object ids", len(ids))

    def query_children(
        self,
        object_id: str,
    ) -> tuple[Mapping[str, Any], ...]:
        arguments: list[str] = [
            "query-object",
            "--object-id",
            _guid(object_id, "children owner id"),
            "--select",
            "children",
            "--take",
            str(_MAX_OBJECT_ROWS),
        ]
        for field in ("id", "name", "type", "path", "parent"):
            arguments.extend(("--return-field", field))
        payload = self._invoke(tuple(arguments), expected_command="query-object")
        return _object_rows(payload, "query-object children", _MAX_OBJECT_ROWS)

    def get_assignments(
        self,
        switch_container_id: str,
    ) -> tuple[Mapping[str, Any], ...]:
        request = {
            "contract": "waapi-skill.operation-request/v1",
            "version": self.version,
            "operation": "waapi.call",
            "arguments": {
                "api": GET_ASSIGNMENTS_API,
                "args": {
                    "id": _guid(
                        switch_container_id,
                        "Switch Container id",
                    )
                },
                "options": {},
            },
        }
        # ``getAssignments`` is a reflected read, but its reviewed public lane
        # is an explicit-confirmation transaction rather than generic ``call``.
        # Keep the maintenance transaction isolated and ephemeral while still
        # exercising every public Gateway phase exactly once.
        with tempfile.TemporaryDirectory(
            prefix="waapi-skill-integration-v2-read-"
        ) as temporary_root:
            transaction_root = Path(temporary_root).resolve(strict=True)
            state_dir = transaction_root / "state"
            evidence_dir = transaction_root / "evidence"
            state_dir.mkdir(mode=0o700)
            evidence_dir.mkdir(mode=0o700)

            preview = self._invoke(
                (
                    "preview",
                    "--request-json",
                    _compact_json(request),
                ),
                expected_command="preview",
                state_dir=state_dir,
                evidence_dir=evidence_dir,
            )
            transaction_id = _transaction_field(
                preview,
                "transaction_id",
                "getAssignments preview",
            )
            artifact_hash = _transaction_hash(
                preview,
                "getAssignments preview",
            )
            preview_summary = preview.get("preview_summary")
            if (
                preview.get("state") != "awaiting_confirmation"
                or preview.get("executed") is not False
                or not isinstance(preview_summary, Mapping)
                or preview_summary.get("request") != request
            ):
                raise IntegrationBaselineCollectionError(
                    "getAssignments preview did not preserve the exact awaiting read transaction"
                )

            shown = self._invoke(
                (
                    "transaction-show",
                    transaction_id,
                    "--summary-only",
                ),
                expected_command="transaction-show",
                state_dir=state_dir,
                evidence_dir=evidence_dir,
                require_live_version=False,
            )
            confirmation = shown.get("confirmation")
            token = (
                confirmation.get("token")
                if isinstance(confirmation, Mapping)
                else None
            )
            if (
                shown.get("transaction_id") != transaction_id
                or shown.get("artifact_hash") != artifact_hash
                or shown.get("state") != "awaiting_confirmation"
                or not isinstance(token, str)
                or not token
            ):
                raise IntegrationBaselineCollectionError(
                    "getAssignments transaction-show omitted its exact confirmation binding"
                )

            confirmed = self._invoke(
                (
                    "confirm",
                    transaction_id,
                    "--confirmation-token",
                    token,
                ),
                expected_command="confirm",
                state_dir=state_dir,
                evidence_dir=evidence_dir,
                require_live_version=False,
            )
            if (
                confirmed.get("transaction_id") != transaction_id
                or confirmed.get("artifact_hash") != artifact_hash
                or confirmed.get("state") != "confirmed"
            ):
                raise IntegrationBaselineCollectionError(
                    "getAssignments confirmation did not bind the immutable preview"
                )

            executed = self._invoke(
                ("execute", transaction_id),
                expected_command="execute",
                state_dir=state_dir,
                evidence_dir=evidence_dir,
            )
            if (
                executed.get("transaction_id") != transaction_id
                or executed.get("artifact_hash") != artifact_hash
                or executed.get("state") != "executed_unverified"
                or executed.get("executed") is not True
            ):
                raise IntegrationBaselineCollectionError(
                    "getAssignments execute did not persist one unverified result"
                )

            payload = self._invoke(
                ("verify", transaction_id),
                expected_command="verify",
                state_dir=state_dir,
                evidence_dir=evidence_dir,
            )
        agent_result = payload.get("agent_result")
        if (
            payload.get("transaction_id") != transaction_id
            or payload.get("artifact_hash") != artifact_hash
            or payload.get("state") != "result_schema_checked"
            or payload.get("result_schema_checked") is not True
            or not isinstance(agent_result, Mapping)
            or agent_result.get("request") != request
            or agent_result.get("executed") is not True
        ):
            raise IntegrationBaselineCollectionError(
                "getAssignments verification did not return the exact terminal read transaction"
            )
        result = agent_result.get("result")
        if not isinstance(result, Mapping):
            raise IntegrationBaselineCollectionError(
                "getAssignments Gateway result is not an object"
            )
        rows = result.get("return")
        if (
            not isinstance(rows, list)
            or len(rows) > _MAX_ASSIGNMENT_ROWS
            or any(not isinstance(row, Mapping) for row in rows)
        ):
            raise IntegrationBaselineCollectionError(
                "getAssignments returned malformed or unbounded rows"
            )
        return tuple(copy.deepcopy(dict(row)) for row in rows)

    def _invoke(
        self,
        arguments: tuple[str, ...],
        *,
        expected_command: str,
        state_dir: Path | None = None,
        evidence_dir: Path | None = None,
        require_live_version: bool = True,
    ) -> Mapping[str, Any]:
        command: list[str] = [
            sys.executable,
            str(self.gateway_runner),
            "gateway.py",
            "--version",
            self.version,
            "--timeout",
            _number_text(self.timeout_seconds),
        ]
        if self.host is not None:
            command.extend(("--host", self.host))
        if self.port is not None:
            command.extend(("--port", str(self.port)))
        if state_dir is not None:
            command.extend(("--state-dir", str(state_dir)))
        if evidence_dir is not None:
            command.extend(("--evidence-dir", str(evidence_dir)))
        command.extend(arguments)
        result = self._runner(tuple(command))
        if not isinstance(result, CommandResult):
            raise IntegrationBaselineCollectionError(
                "Gateway command runner returned an invalid result"
            )
        try:
            payload = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise IntegrationBaselineCollectionError(
                "Gateway did not return exactly one JSON document"
            ) from exc
        if not isinstance(payload, Mapping):
            raise IntegrationBaselineCollectionError(
                "Gateway result root is not an object"
            )
        if (
            result.returncode != 0
            or payload.get("ok") is not True
            or payload.get("command") != expected_command
            or (
                require_live_version
                and payload.get("detected_version") != self.version
            )
        ):
            message = payload.get("message")
            if not isinstance(message, str) or not message:
                message = result.stderr.strip()[:2000] or "unknown Gateway failure"
            raise IntegrationBaselineCollectionError(
                f"Gateway {expected_command} failed closed: {message}"
            )
        return copy.deepcopy(dict(payload))

    def _run_subprocess(self, command: tuple[str, ...]) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds + 10.0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise IntegrationBaselineCollectionError(
                f"could not complete the public Gateway command: {exc}"
            ) from exc
        return CommandResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )


def collect_integration_workflows_v2_baseline(
    *,
    version: str,
    live_project: Path,
    repo_root: Path = REPO_ROOT,
    gateway: PublicGateway | None = None,
) -> BaselineCollection:
    """Collect and validate one deterministic in-memory baseline manifest."""

    repository = _real_directory(repo_root, "repository root")
    profile_path = (
        repository
        / "tests"
        / "semantic"
        / "data"
        / "integration-workflows-v2"
        / "profile.json"
    )
    profile = load_integration_workflows_v2_profile(profile_path)
    if version not in SUPPORTED_VERSIONS or version not in profile.baseline_layouts:
        raise IntegrationBaselineCollectionError(
            f"Integration v2 has no reviewed baseline for {version!r}"
        )
    layout = profile.baseline_layouts[version]
    source_project = _repository_file(
        repository,
        layout.source_project,
        "source project",
    )
    source_root = _real_directory(source_project.parent, "source project root")
    try:
        tree_sha_before = wwise_fixture_tree_sha256(source_root)
    except IntegrationFixtureTreeError as exc:
        raise IntegrationBaselineCollectionError(
            f"committed source tree is unsafe: {exc}"
        ) from exc
    sandbox_project = _isolated_live_project(
        live_project,
        source_project=source_project,
        source_root=source_root,
    )
    sandbox_root = _real_directory(
        sandbox_project.parent,
        "live sandbox project root",
    )
    manifest_path = _repository_destination(
        repository,
        layout.manifest,
        "baseline manifest",
    )
    storage_before = _storage_rows(source_root, layout)
    project_sha_before = sha256_file(source_project)
    sandbox_authored_before = _require_matching_sandbox_authored_payload(
        source_project=source_project,
        source_root=source_root,
        sandbox_project=sandbox_project,
        sandbox_root=sandbox_root,
        layout=layout,
    )

    live = gateway or PublicGateway(version=version)
    _validate_live_status(
        live.status(),
        version=version,
        live_project=sandbox_project,
    )

    specs = _all_object_specs(profile)
    fields_by_role, lane_by_role = _canonical_state_contracts(specs)
    object_rows: list[dict[str, Any]] = []
    sound_rows: list[tuple[str, str, Mapping[str, Any]]] = []
    seen_object_ids: set[str] = set()

    for role, spec in specs.items():
        path = spec.path_for(version)
        if spec.baseline_state == "absent":
            rows = live.query_path(path, fields=("id", "type", "path"))
            if rows:
                raise IntegrationBaselineCollectionError(
                    f"reviewed absent baseline role is present: {role}"
                )
            continue

        state_fields = fields_by_role[role]
        lane = lane_by_role[role]
        live_fields = tuple(
            field
            for field in state_fields
            if field not in {"children", "assignment_pairs", "rtpc_rows"}
        )
        query_fields = tuple(
            dict.fromkeys(("id", "name", "type", "path", *live_fields))
        )
        row = _read_present_object(
            live,
            role=role,
            spec=spec,
            path=path,
            fields=query_fields,
        )
        object_id = _guid(row.get("id"), f"{role} id").upper()
        if object_id.casefold() in seen_object_ids:
            raise IntegrationBaselineCollectionError(
                f"baseline object GUID is reused by role {role}"
            )
        seen_object_ids.add(object_id.casefold())
        if row.get("path") != path:
            raise IntegrationBaselineCollectionError(
                f"{role} resolved to a different path"
            )
        live_type = row.get("type")
        if not _reviewed_type_match(
            version=version,
            role=role,
            live_type=live_type,
            declared_type=spec.type,
        ):
            raise IntegrationBaselineCollectionError(
                f"{role} returned type {live_type!r}, expected {spec.type!r}"
            )
        state = _capture_canonical_state(
            gateway=live,
            role=role,
            lane=lane,
            object_id=object_id,
            raw=row,
            fields=state_fields,
        )
        state_sha = hashlib.sha256(canonical_json_bytes(state)).hexdigest()
        object_rows.append(
            {
                "role": role,
                "id": object_id,
                "path": path,
                # Keep the reviewed workflow type.  Wwise 2025 reports the
                # reviewed ActorMixer role as PropertyContainer at runtime.
                "type": spec.type,
                "state": state,
                "state_sha256": state_sha,
            }
        )
        if _type_token(spec.type) == "sound":
            sound_rows.append((role, object_id, state))

    media_rows = _capture_media_rows(
        live,
        sound_rows=sound_rows,
        source_root=source_root,
        live_root=sandbox_root,
    )
    _validate_live_status(
        live.status(),
        version=version,
        live_project=sandbox_project,
    )

    sandbox_authored_after = _require_matching_sandbox_authored_payload(
        source_project=source_project,
        source_root=source_root,
        sandbox_project=sandbox_project,
        sandbox_root=sandbox_root,
        layout=layout,
    )
    storage_after = _storage_rows(source_root, layout)
    project_sha_after = sha256_file(source_project)
    try:
        tree_sha_after = wwise_fixture_tree_sha256(source_root)
    except IntegrationFixtureTreeError as exc:
        raise IntegrationBaselineCollectionError(
            f"committed source tree became unsafe: {exc}"
        ) from exc
    if (
        sandbox_authored_after != sandbox_authored_before
        or storage_after != storage_before
        or project_sha_after != project_sha_before
        or tree_sha_after != tree_sha_before
    ):
        raise IntegrationBaselineCollectionError(
            "committed source or sandbox authored payload changed during collection"
        )

    payload: dict[str, Any] = {
        "contract": BASELINE_MANIFEST_CONTRACT,
        "version": version,
        "source_project": {
            "relative_path": layout.source_project,
            "project_file_sha256": project_sha_after,
            "full_tree_sha256": tree_sha_after,
        },
        "storage_files": storage_after,
        "objects": object_rows,
        "media": media_rows,
    }
    canonical_json_bytes(payload)
    return BaselineCollection(version, manifest_path, payload)


def _read_present_object(
    gateway: PublicGateway,
    *,
    role: str,
    spec: ObjectSpec,
    path: str,
    fields: Sequence[str],
) -> Mapping[str, Any]:
    """Read one present object, resolving nameless Actions through their Event.

    Wwise exposes a useful display ``path`` for an Action whose stored name is
    empty, but some versions do not accept that display path as a ``from.path``
    selector.  The parent Event path is stable, so its one exact Action child
    supplies the GUID used for the detailed read.
    """

    if _type_token(spec.type) != "action":
        return _one_row(
            gateway.query_path(path, fields=fields),
            f"baseline role {role}",
        )
    if "\\" not in path:
        raise IntegrationBaselineCollectionError(
            f"baseline Action role {role} has no parent Event path"
        )
    parent_path = path.rsplit("\\", 1)[0]
    parent = _one_row(
        gateway.query_path(parent_path, fields=("id", "type", "path")),
        f"baseline Action parent for {role}",
    )
    parent_id = _guid(parent.get("id"), f"{role} parent Event id")
    if _type_token(parent.get("type")) != "event" or parent.get("path") != parent_path:
        raise IntegrationBaselineCollectionError(
            f"baseline Action role {role} did not resolve through its exact Event"
        )
    candidates = [
        row
        for row in gateway.query_children(parent_id)
        if _type_token(row.get("type")) == "action"
        and row.get("path") == path
        and _identity(row.get("parent"), f"{role} Action child parent").casefold()
        == parent_id.casefold()
    ]
    child = _one_row(candidates, f"baseline Action child for {role}")
    child_id = _guid(child.get("id"), f"{role} child Action id")
    detailed = _one_row(
        gateway.query_id(child_id, fields=fields),
        f"baseline Action detail for {role}",
    )
    if (
        _guid(detailed.get("id"), f"{role} detailed Action id").casefold()
        != child_id.casefold()
        or detailed.get("path") != path
        or _type_token(detailed.get("type")) != "action"
    ):
        raise IntegrationBaselineCollectionError(
            f"baseline Action role {role} detailed identity drifted"
        )
    return detailed


def write_baseline(collection: BaselineCollection) -> None:
    """Atomically replace one reviewed manifest without following symlinks."""

    destination = collection.manifest_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination_metadata = os.lstat(destination)
    except FileNotFoundError:
        destination_metadata = None
    except OSError as exc:
        raise IntegrationBaselineCollectionError(
            f"could not inspect baseline manifest destination {destination}: {exc}"
        ) from exc
    if (
        destination_metadata is not None
        and stat.S_ISLNK(destination_metadata.st_mode)
    ):
        raise IntegrationBaselineCollectionError(
            f"refusing to replace symlink baseline manifest: {destination}"
        )
    data = (
        json.dumps(
            collection.payload,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    except OSError as exc:
        raise IntegrationBaselineCollectionError(
            f"could not atomically write {destination}: {exc}"
        ) from exc
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def execute_maintenance(
    argv: Sequence[str] | None = None,
    *,
    runner: GatewayCommandRunner | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    gateway = PublicGateway(
        version=args.version,
        host=args.host,
        port=args.port,
        timeout_seconds=args.timeout,
        runner=runner,
        gateway_runner=(
            Path(repo_root) / "skills" / "waapi-skill" / "scripts" / "run.py"
        ),
    )
    collection = collect_integration_workflows_v2_baseline(
        version=args.version,
        live_project=args.live_project,
        repo_root=Path(repo_root),
        gateway=gateway,
    )
    if args.write:
        write_baseline(collection)
    return collection.summary(wrote=args.write)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, choices=SUPPORTED_VERSIONS)
    parser.add_argument(
        "--live-project",
        required=True,
        type=Path,
        help=(
            "absolute .wproj path of the already-running sandbox copy; the "
            "committed tests/_org source is never opened"
        ),
    )
    parser.add_argument("--host", help="WAAPI host for the already-running Wwise")
    parser.add_argument("--port", type=int, help="WAAPI port for the already-running Wwise")
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="positive whole-command Gateway timeout in seconds",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="atomically write baseline-<version>.json; default is preview-only",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        summary = execute_maintenance(argv)
    except (IntegrationBaselineCollectionError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "contract": MAINTENANCE_CONTRACT,
                    "ok": False,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _capture_canonical_state(
    *,
    gateway: PublicGateway,
    role: str,
    lane: str,
    object_id: str,
    raw: Mapping[str, Any],
    fields: Sequence[str],
) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for field in fields:
        if field == "children":
            rows = gateway.query_children(object_id)
            children: list[dict[str, str]] = []
            for index, row in enumerate(rows):
                parent = _identity(row.get("parent"), f"{role} child {index} parent")
                if parent.casefold() != object_id.casefold():
                    raise IntegrationBaselineCollectionError(
                        f"{role} direct child has another parent"
                    )
                children.append(
                    {"id": _guid(row.get("id"), f"{role} child {index} id").upper()}
                )
            if lane in {"footsteps", "rifle", "shared"}:
                children.sort(key=lambda item: item["id"].casefold())
            state[field] = children
        elif field == "assignment_pairs":
            pairs: list[dict[str, str]] = []
            for index, row in enumerate(gateway.get_assignments(object_id)):
                pairs.append(
                    {
                        "child": _identity(
                            row.get("child"), f"assignment {index} child"
                        ).upper(),
                        "stateOrSwitch": _identity(
                            row.get("stateOrSwitch"),
                            f"assignment {index} stateOrSwitch",
                        ).upper(),
                    }
                )
            pairs.sort(
                key=lambda item: (
                    item["child"].casefold(),
                    item["stateOrSwitch"].casefold(),
                )
            )
            if len(
                {
                    (item["child"].casefold(), item["stateOrSwitch"].casefold())
                    for item in pairs
                }
            ) != len(pairs):
                raise IntegrationBaselineCollectionError(
                    f"{role} assignment table contains duplicate pairs"
                )
            state[field] = pairs
        elif field == "rtpc_rows":
            state[field] = _capture_rtpc_rows(
                gateway,
                object_id=object_id,
                role=role,
            )
        elif field in _IDENTITY_FIELDS:
            if field not in raw:
                raise IntegrationBaselineCollectionError(
                    f"{role} omitted canonical state field {field}"
                )
            state[field] = {
                "id": _identity(raw[field], f"{role} {field}").upper()
            }
        elif field == "OutputBus":
            if field not in raw:
                raise IntegrationBaselineCollectionError(
                    f"{role} omitted canonical state field {field}"
                )
            value = raw[field]
            state[field] = (
                None
                if value is None
                else {"id": _identity(value, f"{role} OutputBus").upper()}
            )
        else:
            if field not in raw:
                raise IntegrationBaselineCollectionError(
                    f"{role} omitted canonical state field {field}"
                )
            state[field] = _plain_json(raw[field], f"{role} {field}")
    if tuple(state) != tuple(fields):
        raise IntegrationBaselineCollectionError(
            f"{role} canonical state insertion order drifted"
        )
    return state


def _capture_rtpc_rows(
    gateway: PublicGateway,
    *,
    object_id: str,
    role: str,
) -> list[dict[str, Any]]:
    owner = _one_row(
        gateway.query_id(object_id, fields=("id", "@RTPC")),
        f"{role} RTPC owner",
    )
    references = owner.get("@RTPC")
    if references is None:
        references = []
    if not isinstance(references, list) or len(references) > _MAX_RTPC_ROWS:
        raise IntegrationBaselineCollectionError(
            f"{role} RTPC reference list is malformed or unbounded"
        )
    ids = tuple(
        _identity(value, f"{role} RTPC reference {index}").upper()
        for index, value in enumerate(references)
    )
    if len({value.casefold() for value in ids}) != len(ids):
        raise IntegrationBaselineCollectionError(
            f"{role} RTPC reference list contains duplicates"
        )
    if not ids:
        return []
    rows = gateway.query_ids(ids, fields=_RTPC_FIELDS)
    by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        rtpc_id = _guid(row.get("id"), f"{role} RTPC row {index} id").upper()
        key = rtpc_id.casefold()
        if key in by_id or _type_token(row.get("type")) != "rtpc":
            raise IntegrationBaselineCollectionError(
                f"{role} RTPC detail rows repeat an id or have the wrong type"
            )
        normalized: dict[str, Any] = {}
        for field in _RTPC_FIELDS:
            if field not in row:
                raise IntegrationBaselineCollectionError(
                    f"{role} RTPC detail omitted {field}"
                )
            value = row[field]
            if field == "id":
                normalized[field] = rtpc_id
            elif field == "@ControlInput" and value not in (None, "", {}):
                normalized[field] = {
                    "id": _identity(value, f"{role} RTPC ControlInput").upper()
                }
            else:
                normalized[field] = _plain_json(
                    value, f"{role} RTPC {field}"
                )
        by_id[key] = normalized
    if set(by_id) != {value.casefold() for value in ids}:
        raise IntegrationBaselineCollectionError(
            f"{role} RTPC detail differs from its reference list"
        )
    return [by_id[value.casefold()] for value in ids]


def _capture_media_rows(
    gateway: PublicGateway,
    *,
    sound_rows: Sequence[tuple[str, str, Mapping[str, Any]]],
    source_root: Path,
    live_root: Path,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    source_ids: set[str] = set()
    for role, sound_id, state in sound_rows:
        active_source = _identity(
            state.get("activeSource"), f"{role} activeSource"
        ).upper()
        if active_source.casefold() in source_ids:
            raise IntegrationBaselineCollectionError(
                f"AudioSource GUID is reused by Sound role {role}"
            )
        source_ids.add(active_source.casefold())
        source = _one_row(
            gateway.query_id(active_source, fields=_SOURCE_FIELDS),
            f"{role} activeSource",
        )
        if (
            _guid(source.get("id"), f"{role} AudioSource id").casefold()
            != active_source.casefold()
            or _type_token(source.get("type"))
            not in {"audiofilesource", "audiosource"}
            or _identity(source.get("parent"), f"{role} AudioSource parent").casefold()
            != sound_id.casefold()
            or _name_value(
                source.get("audioSource:language"),
                f"{role} AudioSource language",
            )
            != "SFX"
        ):
            raise IntegrationBaselineCollectionError(
                f"{role} activeSource identity, parent, type, or language drifted"
            )
        original = _original_file(
            source.get("originalFilePath"),
            project_root=live_root,
            label=f"{role} Original",
        )
        relative = original.relative_to(live_root).as_posix()
        committed_original = _contained_file(
            source_root,
            relative,
            f"{role} committed Original",
        )
        live_sha = sha256_file(original)
        committed_sha = sha256_file(committed_original)
        if live_sha != committed_sha:
            raise IntegrationBaselineCollectionError(
                f"{role} sandbox Original differs from the committed source"
            )
        result.append(
            {
                "role": role,
                "active_source_id": active_source,
                "relative_path": relative,
                "sha256": committed_sha,
            }
        )
    return result


def _all_object_specs(profile: WorkflowProfile) -> OrderedDict[str, ObjectSpec]:
    result: OrderedDict[str, ObjectSpec] = OrderedDict()
    for workflow in profile.workflows:
        for spec in workflow.fixture.object_graph:
            previous = result.get(spec.role)
            if previous is not None and previous != spec:
                raise IntegrationBaselineCollectionError(
                    f"workflow role {spec.role} has conflicting object specs"
                )
            result.setdefault(spec.role, spec)
    if not result:
        raise IntegrationBaselineCollectionError(
            "integration v2 has no reviewed object graph"
        )
    return result


def _canonical_state_contracts(
    specs: Mapping[str, ObjectSpec],
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    maps = (
        ("rifle", RIFLE_CANONICAL_STATE_FIELDS),
        ("footsteps", FOOTSTEPS_CANONICAL_STATE_FIELDS),
        ("weapons", WEAPONS_CANONICAL_STATE_FIELDS),
    )
    fields: dict[str, tuple[str, ...]] = {}
    owners: dict[str, list[str]] = {}
    for lane, mapping in maps:
        for role, values in mapping.items():
            normalized = tuple(values)
            previous = fields.get(role)
            if previous is not None and previous != normalized:
                raise IntegrationBaselineCollectionError(
                    f"canonical state contract conflicts for shared role {role}"
                )
            fields[role] = normalized
            owners.setdefault(role, []).append(lane)
    present_roles = {
        role for role, spec in specs.items() if spec.baseline_state == "present"
    }
    if set(fields) != present_roles:
        raise IntegrationBaselineCollectionError(
            "runtime canonical state roles do not exactly cover present workflow roles; "
            f"missing={sorted(present_roles - set(fields))}, "
            f"extra={sorted(set(fields) - present_roles)}"
        )
    lane_by_role = {
        role: lanes[0] if len(lanes) == 1 else "shared"
        for role, lanes in owners.items()
    }
    return fields, lane_by_role


def _validate_live_status(
    payload: Mapping[str, Any],
    *,
    version: str,
    live_project: Path,
) -> None:
    if payload.get("detected_version") != version:
        raise IntegrationBaselineCollectionError(
            "live Wwise version differs from the requested baseline version"
        )
    project = payload.get("project")
    if not isinstance(project, Mapping):
        raise IntegrationBaselineCollectionError(
            "Gateway status omitted the current project"
        )
    live_path_value = project.get("path")
    if not isinstance(live_path_value, str) or not live_path_value:
        raise IntegrationBaselineCollectionError(
            "Gateway status omitted the current project path"
        )
    observed_project = _localize_live_project_path(live_path_value)
    if observed_project != live_project:
        raise IntegrationBaselineCollectionError(
            "already-running Wwise is not using the requested sandbox project: "
            f"{observed_project}"
        )
    if project.get("isDirty") is not False:
        raise IntegrationBaselineCollectionError(
            "current Wwise project must be saved and clean before collection"
        )


def _localize_live_project_path(
    value: str,
    *,
    account_home: Path | None = None,
    host_os_name: str | None = None,
) -> Path:
    """Resolve one native or local Wine ``Y:`` project path exactly.

    Wwise 2022 on macOS reports the host account home through Wine's ``Y:``
    drive.  No other drive is inferred here: a native absolute path remains
    native, and an unknown Windows drive fails closed.
    """

    effective_os_name = os.name if host_os_name is None else host_os_name
    try:
        parsed = parse_absolute_host_path(value)
        if (
            effective_os_name == "posix"
            and parsed.flavor == "drive"
            and parsed.drive != "Y"
        ):
            raise IntegrationBaselineCollectionError(
                f"live project path uses unsupported Wine drive {parsed.drive}:"
            )
        localized = localize_waapi_host_path(
            value,
            host_os_name=effective_os_name,
            account_home=account_home,
        )
    except HostPathError as exc:
        raise IntegrationBaselineCollectionError(
            f"live project path is not an absolute native or Wine Y: path: {exc}"
        ) from exc
    candidate = Path(localized)
    try:
        project = candidate.resolve(strict=True)
    except OSError as exc:
        raise IntegrationBaselineCollectionError(
            f"live project path is unavailable: {value}"
        ) from exc
    if not project.is_file() or project.suffix.casefold() != ".wproj":
        raise IntegrationBaselineCollectionError(
            "live project path does not resolve to one .wproj file"
        )
    return project


def _isolated_live_project(
    value: Path,
    *,
    source_project: Path,
    source_root: Path,
) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise IntegrationBaselineCollectionError(
            "--live-project must be an absolute .wproj path"
        )
    project = _contained_file(
        _real_directory(candidate.parent, "live sandbox project root"),
        candidate.name,
        "live sandbox project",
    )
    if project.suffix.casefold() != ".wproj":
        raise IntegrationBaselineCollectionError(
            "--live-project must name one .wproj file"
        )
    live_root = project.parent
    if (
        project == source_project
        or live_root == source_root
        or _path_is_within(live_root, source_root)
        or _path_is_within(source_root, live_root)
    ):
        raise IntegrationBaselineCollectionError(
            "--live-project must be an isolated sandbox copy, never the committed source"
        )
    if project.name != source_project.name:
        raise IntegrationBaselineCollectionError(
            "sandbox project filename differs from the committed source"
        )
    return project


def _require_matching_sandbox_authored_payload(
    *,
    source_project: Path,
    source_root: Path,
    sandbox_project: Path,
    sandbox_root: Path,
    layout: BaselineLayout,
) -> dict[str, Any]:
    source = {
        "project_sha256": sha256_file(source_project),
        "storage_files": _storage_rows(source_root, layout),
        "media_files": _media_file_rows(source_root),
    }
    sandbox = {
        "project_sha256": sha256_file(sandbox_project),
        "storage_files": _storage_rows(sandbox_root, layout),
        "media_files": _media_file_rows(sandbox_root),
    }
    if sandbox != source:
        raise IntegrationBaselineCollectionError(
            "sandbox project, fixed storage files, or Originals media differ "
            "from the committed baseline source"
        )
    return sandbox


def _media_file_rows(root: Path) -> list[dict[str, Any]]:
    originals = _real_directory(root / "Originals", "Originals root")
    rows: list[dict[str, Any]] = []
    for directory, directory_names, file_names in os.walk(
        originals,
        followlinks=False,
    ):
        directory_names.sort()
        file_names.sort()
        base = Path(directory)
        for name in (*directory_names, *file_names):
            candidate = base / name
            try:
                metadata = os.lstat(candidate)
            except OSError as exc:
                raise IntegrationBaselineCollectionError(
                    f"cannot inspect Originals entry: {candidate}"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise IntegrationBaselineCollectionError(
                    f"Originals tree contains a symlink: {candidate}"
                )
        for name in file_names:
            path = _contained_file(
                root,
                (base / name).relative_to(root).as_posix(),
                "Originals media",
            )
            rows.append(
                {
                    "relative_path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    rows.sort(key=lambda row: row["relative_path"])
    if not rows:
        raise IntegrationBaselineCollectionError(
            "committed integration baseline has no Originals media"
        )
    return rows


def _storage_rows(
    source_root: Path,
    layout: BaselineLayout,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for relative in layout.storage_files:
        path = _contained_file(source_root, relative, "storage file")
        rows.append({"relative_path": relative, "sha256": sha256_file(path)})
    return rows


def _reviewed_type_match(
    *,
    version: str,
    role: str,
    live_type: Any,
    declared_type: Any,
) -> bool:
    live = _type_token(live_type)
    declared = _type_token(declared_type)
    if live == declared:
        return True
    return (
        version == "2025.1"
        and role == "audit_root"
        and declared == "actormixer"
        and live == "propertycontainer"
    )


def _object_rows(
    payload: Mapping[str, Any],
    label: str,
    maximum: int,
) -> tuple[Mapping[str, Any], ...]:
    rows = payload.get("objects")
    if (
        not isinstance(rows, list)
        or len(rows) > maximum
        or any(not isinstance(row, Mapping) for row in rows)
    ):
        raise IntegrationBaselineCollectionError(
            f"{label} returned malformed or unbounded objects"
        )
    if payload.get("count") != len(rows):
        raise IntegrationBaselineCollectionError(
            f"{label} count disagrees with its objects"
        )
    return tuple(copy.deepcopy(dict(row)) for row in rows)


def _one_row(
    rows: Sequence[Mapping[str, Any]],
    label: str,
) -> Mapping[str, Any]:
    if len(rows) != 1:
        raise IntegrationBaselineCollectionError(
            f"{label} did not resolve exactly once"
        )
    return rows[0]


def _closed_fields(fields: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    for field in fields:
        if (
            not isinstance(field, str)
            or not field
            or len(field) > 256
            or field != field.strip()
            or any(ord(character) < 32 for character in field)
        ):
            raise IntegrationBaselineCollectionError(
                f"invalid object return field {field!r}"
            )
        if field not in result:
            result.append(field)
    if not result or len(result) > 64:
        raise IntegrationBaselineCollectionError(
            "object return field list is empty or unbounded"
        )
    return tuple(result)


def _plain_json(value: Any, label: str) -> Any:
    try:
        encoded = canonical_json_bytes(value)
        return json.loads(encoded)
    except (CampaignEvidenceError, TypeError, ValueError) as exc:
        raise IntegrationBaselineCollectionError(
            f"{label} is not strict JSON"
        ) from exc


def _identity(value: Any, label: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("id")
    return _guid(value, label)


def _guid(value: Any, label: str) -> str:
    if not isinstance(value, str) or _GUID_RE.fullmatch(value) is None:
        raise IntegrationBaselineCollectionError(
            f"{label} must be one canonical GUID"
        )
    return value


def _transaction_field(
    payload: Mapping[str, Any],
    field: str,
    label: str,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise IntegrationBaselineCollectionError(
            f"{label} omitted non-empty {field}"
        )
    return value


def _transaction_hash(payload: Mapping[str, Any], label: str) -> str:
    value = _transaction_field(payload, "artifact_hash", label)
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise IntegrationBaselineCollectionError(
            f"{label} returned an invalid artifact_hash"
        )
    return value


def _name_value(value: Any, label: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("name")
    if not isinstance(value, str) or not value or "\x00" in value:
        raise IntegrationBaselineCollectionError(
            f"{label} must expose one non-empty name"
        )
    return value


def _type_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _compact_json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _number_text(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _original_file(
    value: Any,
    *,
    project_root: Path,
    label: str,
    account_home: Path | None = None,
    host_os_name: str | None = None,
) -> Path:
    effective_os_name = os.name if host_os_name is None else host_os_name
    try:
        parsed = parse_absolute_host_path(value)
        if parsed.flavor == "unc":
            raise IntegrationBaselineCollectionError(
                f"{label} uses an unsupported UNC path"
            )
        localized = localize_waapi_host_path(
            value,
            host_os_name=effective_os_name,
            account_home=account_home,
        )
    except HostPathError as exc:
        if exc.error_code == "HOST_PATH_DRIVE_UNAVAILABLE":
            drive = exc.details.get("drive", "unknown")
            raise IntegrationBaselineCollectionError(
                f"{label} uses unsupported Wine drive {drive}:"
            ) from exc
        raise IntegrationBaselineCollectionError(
            f"{label} requires one absolute local path: {exc}"
        ) from exc
    candidate = Path(localized)
    try:
        relative = candidate.relative_to(project_root)
    except ValueError as exc:
        raise IntegrationBaselineCollectionError(
            f"{label} escapes its project copy"
        ) from exc
    if not relative.parts or relative.parts[0] != "Originals":
        raise IntegrationBaselineCollectionError(
            f"{label} is outside the project Originals tree"
        )
    return _contained_file(project_root, relative.as_posix(), label)


def _path_is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def _repository_file(root: Path, relative: str, label: str) -> Path:
    return _contained_file(root, relative, label)


def _repository_destination(root: Path, relative: str, label: str) -> Path:
    parts = Path(relative).parts
    if (
        not parts
        or Path(relative).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise IntegrationBaselineCollectionError(
            f"{label} has an unsafe relative path: {relative!r}"
        )
    try:
        repository = root.resolve(strict=True)
        candidate = repository.joinpath(*parts)
        candidate.parent.resolve(strict=True).relative_to(repository)
    except (OSError, ValueError) as exc:
        raise IntegrationBaselineCollectionError(
            f"{label} escapes the repository"
        ) from exc
    # Keep the final component lexical so the writer can reject both live and
    # broken leaf symlinks with lstat instead of silently following them.
    return candidate


def _contained_file(root: Path, relative: str, label: str) -> Path:
    parts = Path(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise IntegrationBaselineCollectionError(
            f"{label} has an unsafe relative path: {relative!r}"
        )
    current = root
    for part in parts:
        current /= part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise IntegrationBaselineCollectionError(
                f"{label} is unavailable: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise IntegrationBaselineCollectionError(
                f"{label} path contains a symlink: {current}"
            )
    if not current.is_file():
        raise IntegrationBaselineCollectionError(
            f"{label} is not a regular file: {current}"
        )
    try:
        current.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise IntegrationBaselineCollectionError(
            f"{label} resolves outside its root"
        ) from exc
    return current.resolve(strict=True)


def _real_directory(path: Path, label: str) -> Path:
    candidate = Path(path)
    try:
        metadata = os.lstat(candidate)
    except OSError as exc:
        raise IntegrationBaselineCollectionError(
            f"{label} is unavailable: {candidate}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise IntegrationBaselineCollectionError(
            f"{label} must be one real directory: {candidate}"
        )
    return candidate.resolve(strict=True)


if __name__ == "__main__":  # pragma: no cover - CLI wrapper
    raise SystemExit(main())
