"""Bounded fixture helpers which execute only the public Gateway CLI."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.host_paths import localize_waapi_host_path

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
from tests.semantic.support.codex_filesystem_security import path_is_link_or_reparse


class CaseBoundaryError(RuntimeError):
    """The public interface or owned fixture cannot prove a case prerequisite."""


def rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("objects")
    integrity = payload.get("response_integrity")
    bound = payload.get("query_bound")
    if (payload.get("ok") is not True or not isinstance(value, list)
            or len(value) > 64 or payload.get("limit_reached") is True
            or payload.get("count") != len(value)
            or (integrity is not None and (not isinstance(integrity, Mapping)
                or integrity.get("complete") is not True or integrity.get("truncated") is not False))
            or any(not isinstance(row, dict) for row in value)):
        raise CaseBoundaryError("bounded complete public object read is unavailable")
    if not isinstance(bound, Mapping) or not (
        (bound.get("mode") == "exact-object" and len(value) <= 1)
        or (bound.get("mode") == "take" and type(bound.get("value")) is int
            and 1 <= bound["value"] <= 64 and len(value) < bound["value"])
    ):
        raise CaseBoundaryError("public object read may have reached its row ceiling")
    ids = [row.get("id") for row in value]
    if (any(not isinstance(item, str) or not re.fullmatch(
            r"\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}", item)
            for item in ids) or len({item.upper() for item in ids}) != len(ids)):
        raise CaseBoundaryError("public object read contains malformed or duplicate identities")
    return value


def read_object(ctx: ExpansionCaseContext, object_id: str, *,
                includes: Sequence[str] = (), fields: Sequence[str] = ()) -> dict[str, Any]:
    command = ["query-object", "--exact-id", object_id, "--max-results", "2"]
    for flag, values in (("--include", includes), ("--include-field", fields)):
        for value in values:
            command.extend((flag, value))
    found = rows(ctx.gateway(command))
    if len(found) != 1 or found[0]["id"] != object_id:
        raise CaseBoundaryError("exact object read does not bind the requested GUID")
    return found[0]


def query_path(ctx: ExpansionCaseContext, path_segments: Sequence[str], *,
               includes: Sequence[str] = ()) -> dict[str, Any]:
    command = ["query-object", "--max-results", "2"]
    for segment in path_segments:
        command.extend(("--path-segment", segment))
    for include in includes:
        command.extend(("--include", include))
    found = rows(ctx.gateway(command))
    if len(found) != 1:
        raise CaseBoundaryError("fixture path is missing or ambiguous")
    return found[0]


def case_name(ctx: ExpansionCaseContext, suffix: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", ctx.scenario_id):
        raise CaseBoundaryError("scenario id is not a bounded fixture name")
    return f"Expansion_{ctx.scenario_id}_{suffix}"


def container_root(ctx: ExpansionCaseContext) -> tuple[str, str]:
    if ctx.version not in {"2022.1", "2025.1"}:
        raise CaseBoundaryError("expansion fixture supports only reviewed 2022.1/2025.1 lanes")
    return ("Containers" if ctx.version == "2025.1" else "Actor-Mixer Hierarchy",
            "Default Work Unit")


def _owned_file(path: Path, root: Path) -> Path:
    root = root.resolve(strict=True)
    if not path.is_absolute():
        raise CaseBoundaryError("fixture file must be absolute")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise CaseBoundaryError("file escapes its owned fixture root") from exc
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        try:
            linked = path_is_link_or_reparse(cursor)
        except OSError as exc:
            raise CaseBoundaryError("fixture media is missing or unreadable") from exc
        if part in {".", ".."} or linked:
            raise CaseBoundaryError("fixture media cannot traverse links or parent segments")
    if not path.is_file() or not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise CaseBoundaryError("fixture requires a bounded regular media file")
    return path


def file_evidence(ctx: ExpansionCaseContext, waapi_path: str) -> dict[str, Any]:
    path = _owned_file(Path(localize_waapi_host_path(waapi_path)), ctx.project_path.parent)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def wav_assets(ctx: ExpansionCaseContext, count: int) -> tuple[Path, ...]:
    """Reuse distinct existing sandbox WAVs; absence is an explicit fixture block."""
    if not 1 <= count <= 4:
        raise CaseBoundaryError("asset selection exceeds the fixed fixture bound")
    found: list[Path] = []
    digests: set[str] = set()
    for path in sorted((ctx.project_path.parent / "Originals").rglob("*.wav")):
        path = _owned_file(path, ctx.project_path.parent)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in digests:
            continue
        found.append(path)
        digests.add(digest)
        if len(found) == count:
            return tuple(found)
    raise CaseBoundaryError(f"fixture needs {count} distinct existing WAV assets")


def copy_asset(ctx: ExpansionCaseContext, source: Path, directory: str, name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", directory) or Path(name).name != name:
        raise CaseBoundaryError("asset destination must be a simple owned name")
    _owned_file(source, ctx.project_path.parent)
    destination = ctx.asset_root / directory / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink() or any(path_is_link_or_reparse(p)
                                   for p in (ctx.asset_root, destination.parent)):
        raise CaseBoundaryError("fixture asset destination already exists or is linked")
    shutil.copyfile(source, destination)
    return destination


class BusinessDraft:
    """Runner-owned setup transaction, never an alternate Agent mutation ingress."""

    def __init__(self, ctx: ExpansionCaseContext, operation: str) -> None:
        self.ctx = ctx
        started = ctx.gateway(["draft-start", operation])
        self.draft_id = started["draft"]["draft_id"]
        self.authority = started["task_authority"]
        self.revision = started["draft"]["revision"]

    def step(self, command: str, *arguments: str) -> Mapping[str, Any]:
        result = self.ctx.gateway([
            command, self.draft_id, "--task-authority", self.authority,
            "--expected-revision", str(self.revision), *arguments,
        ])
        draft = result.get("draft")
        if isinstance(draft, Mapping) and isinstance(draft.get("revision"), int):
            self.revision = draft["revision"]
        return result

    def bind(self, *, object_id: str | None = None,
             segments: Sequence[str] = (), role: str | None = None) -> str:
        if bool(object_id) == bool(segments):
            raise CaseBoundaryError("binding needs exactly one closed identity")
        arguments = ["--object-id", object_id] if object_id else [
            token for segment in segments for token in ("--object-path-segment", segment)
        ]
        if role is not None:
            arguments.extend(("--role", role))
        return str(self.step("draft-bind-object", *arguments)["bound_object"]["handle"])

    def discover_type(self, meaning: str, *, role: str = "object") -> str:
        result = self.step("draft-discover-types", "--meaning", meaning, "--role", role)
        candidates = result.get("type_candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise CaseBoundaryError("fixture type is unavailable or ambiguous")
        return str(candidates[0]["handle"])

    def discover_field(self, handle: str, meaning: str) -> str:
        result = self.step("draft-discover-fields", "--object-handle", handle,
                           "--meaning", meaning)
        groups = result.get("meaning_results")
        if not isinstance(groups, list) or len(groups) != 1:
            raise CaseBoundaryError("field discovery did not return one requested meaning")
        candidates = groups[0].get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise CaseBoundaryError("fixture field is unavailable or ambiguous")
        return str(candidates[0]["handle"])

    def finish(self) -> dict[str, Mapping[str, Any]]:
        self.step("draft-check")
        preview = self.step("preview-from-draft")
        transaction_id = preview["transaction_id"]
        shown = self.ctx.gateway(["transaction-show", transaction_id, "--summary-only"])
        confirmation = shown.get("confirmation")
        if isinstance(confirmation, Mapping) and isinstance(confirmation.get("token"), str):
            self.ctx.gateway(["confirm", transaction_id, "--confirmation-token", confirmation["token"]])
        elif shown.get("state") != "policy_authorized":
            raise CaseBoundaryError("setup Preview has no durable authorization path")
        executed = self.ctx.gateway(["execute", transaction_id])
        verified = self.ctx.gateway(["verify", transaction_id])
        if (executed.get("state") != "executed_unverified"
                or verified.get("state") != "verified"
                or verified.get("verification", {}).get("business_state_verified") is not True):
            raise CaseBoundaryError("fixture transaction lacks strong business verification")
        return {"preview": preview, "execute": executed, "verify": verified}
