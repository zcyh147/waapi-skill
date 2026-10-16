"""Bounded fixture helpers which execute only the public Gateway CLI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from wwise_waapi.host_paths import localize_waapi_host_path

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
from tests.semantic.support.codex_filesystem_security import path_is_link_or_reparse


class CaseBoundaryError(RuntimeError):
    """The public interface or owned fixture cannot prove a case prerequisite."""


_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATEWAY_RUNNER = _REPO_ROOT / "skills" / "waapi-skill" / "scripts" / "run.py"
_GATEWAY_CWD = _GATEWAY_RUNNER.parent.parent
_GATEWAY_OUTPUT_LIMIT_BYTES = 1_048_576
_GATEWAY_RECEIPT_PAYLOAD_LIMIT_BYTES = 32_768
_GATEWAY_DIAGNOSTIC_EXCERPT_BYTES = 8_192
_GATEWAY_RECEIPT_LIMIT = 128
_GATEWAY_CALL_TIMEOUT_SECONDS = 60


def _bounded_diagnostic_bytes(value: bytes, limit: int = _GATEWAY_DIAGNOSTIC_EXCERPT_BYTES) -> str:
    if len(value) <= limit:
        return value.decode("utf-8", errors="replace")
    half = limit // 2
    return (
        value[:half].decode("utf-8", errors="replace")
        + f"\n... <{len(value) - limit} bytes omitted> ...\n"
        + value[-half:].decode("utf-8", errors="replace")
    )


def _receipt_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def _gateway_receipt_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep small failure facts when a full structured Gateway receipt is too large."""
    summary: dict[str, Any] = {}
    for key in ("status", "operation", "verification_strength"):
        value = _receipt_text(payload.get(key), 128)
        if value is not None:
            summary[key] = value
    if type(payload.get("ok")) is bool:
        summary["ok"] = payload["ok"]
    error = payload.get("error")
    if isinstance(error, Mapping):
        error_summary = {}
        code = _receipt_text(error.get("code"), 128)
        message = _receipt_text(error.get("message"), 256)
        if code is not None:
            error_summary["code"] = code
        if message is not None:
            error_summary["message"] = message
        if error_summary:
            summary["error"] = error_summary
    verification = payload.get("verification")
    if isinstance(verification, Mapping):
        verification_summary: dict[str, Any] = {}
        for key in ("status", "operation", "verification_strength"):
            value = _receipt_text(verification.get(key), 128)
            if value is not None:
                verification_summary[key] = value
        for key in ("business_state_verified", "assertion_count", "passed_assertion_count",
                    "failed_assertion_count", "readback_count"):
            value = verification.get(key)
            if type(value) in {bool, int}:
                verification_summary[key] = value
        assertions = verification.get("assertions")
        if isinstance(assertions, list):
            failed = [row for row in assertions
                      if isinstance(row, Mapping) and row.get("passed") is False]
            names = [name for row in failed
                     if (name := _receipt_text(row.get("name"), 192)) is not None]
            verification_summary["assertion_count"] = len(assertions)
            verification_summary["failed_assertion_count"] = len(failed)
            verification_summary["failed_assertions"] = names[:12]
            if len(names) > 12:
                verification_summary["omitted_failed_assertion_names"] = len(names) - 12
        if verification_summary:
            summary["verification"] = verification_summary
    return summary


def make_public_gateway(
    *,
    host: str,
    port: int,
    version: str,
    config_path: Path,
    state_dir: Path,
    environment: Mapping[str, str],
    receipts: list[dict[str, Any]],
    live_commands: frozenset[str],
) -> Callable[[Sequence[str]], Mapping[str, Any]]:
    """Create a bounded Gateway callable isolated in the packaged CLI process.

    Setup drafts intentionally span several CLI invocations, so each call gets
    the same owned config and state directory. Keeping the subprocess boundary
    also prevents WAAPI client's txaio loop from colliding with the independent
    read-only oracle actor in the pytest process.
    """
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise CaseBoundaryError("fixture Gateway endpoint must be loopback")
    if type(port) is not int or not 1 <= port <= 65535:
        raise CaseBoundaryError("fixture Gateway endpoint port is invalid")
    if version not in {"2022.1", "2025.1"}:
        raise CaseBoundaryError("fixture Gateway has no reviewed version lane")
    if (not config_path.is_absolute() or not state_dir.is_absolute()
            or config_path.is_symlink() or not config_path.is_file()):
        raise CaseBoundaryError("fixture Gateway needs the exact owned config and state paths")
    configuration = json.loads(config_path.read_text(encoding="utf-8"))
    if any(configuration.get(key) != value for key, value in {
        "waapi_host": host, "waapi_port": port, "wwise_version": version,
    }.items()):
        raise CaseBoundaryError("fixture Gateway configuration does not match its owned endpoint")
    if _GATEWAY_RUNNER.is_symlink() or not _GATEWAY_RUNNER.is_file():
        raise CaseBoundaryError("packaged public Gateway runner is unavailable")
    if len(receipts) != 0:
        raise CaseBoundaryError("fixture Gateway receipts must start empty for this case")

    def invoke(command: Sequence[str]) -> Mapping[str, Any]:
        from tests.semantic.support.codex_expansion_reconciliation import (
            ReconciliationCleanupError, run_owned_gateway,
        )
        argv = tuple(command)
        if (not argv or len(argv) > 128
                or any(not isinstance(item, str) or not item or "\0" in item for item in argv)
                or sum(len(item.encode("utf-8")) for item in argv) > 65_536):
            raise CaseBoundaryError("fixture Gateway command is empty or exceeds its fixed bounds")
        if len(receipts) >= _GATEWAY_RECEIPT_LIMIT:
            raise CaseBoundaryError("fixture Gateway exceeded its case-owned call ceiling")

        process_argv = [
            sys.executable,
            str(_GATEWAY_RUNNER),
            "gateway.py",
            "--timeout", "30",
            "--state-dir", str(state_dir),
            *argv,
        ]
        child_environment = {
            **os.environ,
            **environment,
            "WAAPI_SKILL_CONFIG_PATH": str(config_path),
            "WAAPI_SKILL_STATE_DIR": str(state_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8:strict",
        }
        started = time.monotonic()
        try:
            completed = run_owned_gateway(
                process_argv,
                cwd=_GATEWAY_CWD,
                environment=child_environment,
                timeout_seconds=_GATEWAY_CALL_TIMEOUT_SECONDS,
                text=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
            stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
            receipts.append({
                "argv": list(argv),
                "command": process_argv,
                "timeout_seconds": _GATEWAY_CALL_TIMEOUT_SECONDS,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "stdout_excerpt": _bounded_diagnostic_bytes(stdout),
                "stderr_excerpt": _bounded_diagnostic_bytes(stderr),
                "error": "subprocess_timeout",
            })
            raise CaseBoundaryError(
                f"public fixture Gateway exceeded {_GATEWAY_CALL_TIMEOUT_SECONDS} seconds"
            ) from exc
        except OSError as exc:
            receipts.append({
                "argv": list(argv),
                "command": process_argv,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "error": f"{type(exc).__name__}: {exc}",
            })
            raise CaseBoundaryError("public fixture Gateway process could not start") from exc
        except ReconciliationCleanupError as exc:
            receipts.append({
                "argv": list(argv), "command": process_argv,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "error": "gateway_process_cleanup_unproved",
                "cleanup_proven": False,
                "message": str(exc).encode("utf-8")[:2_048].decode("utf-8", "ignore"),
            })
            raise

        stdout = completed.stdout if isinstance(completed.stdout, bytes) else b""
        stderr = completed.stderr if isinstance(completed.stderr, bytes) else b""
        receipt: dict[str, Any] = {
            "argv": list(argv),
            "command": process_argv,
            "returncode": completed.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
        }
        if len(stdout) + len(stderr) > _GATEWAY_OUTPUT_LIMIT_BYTES:
            receipt.update({
                "error": "gateway_output_ceiling_exceeded",
                "stdout_excerpt": _bounded_diagnostic_bytes(stdout),
                "stderr_excerpt": _bounded_diagnostic_bytes(stderr),
            })
            receipts.append(receipt)
            raise CaseBoundaryError("public fixture Gateway exceeded its output ceiling")

        try:
            payload = json.loads(stdout.decode("utf-8", errors="strict"))
        except (UnicodeError, ValueError, TypeError) as exc:
            receipt.update({
                "error": "invalid_json_receipt",
                "stdout_excerpt": _bounded_diagnostic_bytes(stdout),
                "stderr_excerpt": _bounded_diagnostic_bytes(stderr),
            })
            receipts.append(receipt)
            raise CaseBoundaryError("public fixture Gateway returned no complete UTF-8 JSON receipt") from exc

        try:
            encoded_payload = json.dumps(
                payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            receipt.update({
                "error": "non_json_gateway_payload",
                "stdout_excerpt": _bounded_diagnostic_bytes(stdout),
                "stderr_excerpt": _bounded_diagnostic_bytes(stderr),
            })
            receipts.append(receipt)
            raise CaseBoundaryError("public fixture Gateway returned a non-JSON payload") from exc
        receipt["payload_bytes"] = len(encoded_payload)
        if len(encoded_payload) <= _GATEWAY_RECEIPT_PAYLOAD_LIMIT_BYTES:
            receipt["payload"] = payload
        else:
            receipt["payload_sha256"] = hashlib.sha256(encoded_payload).hexdigest()
            receipt["payload_excerpt"] = _bounded_diagnostic_bytes(encoded_payload)
            receipt["payload_summary"] = _gateway_receipt_summary(payload)
        if stderr:
            receipt["stderr_excerpt"] = _bounded_diagnostic_bytes(stderr)
        receipts.append(receipt)

        if not isinstance(payload, dict):
            raise CaseBoundaryError("public fixture Gateway returned a non-object receipt")
        if completed.returncode != 0 or payload.get("ok") is not True:
            status = payload.get("status")
            error = payload.get("error")
            raise CaseBoundaryError(
                f"public fixture Gateway failed (exit={completed.returncode}, status={status}, error={error})"
            )
        if argv[0] in live_commands:
            endpoint = payload.get("endpoint")
            if (not isinstance(endpoint, Mapping) or endpoint.get("host") != host
                    or endpoint.get("port") != port or payload.get("detected_version") != version):
                raise CaseBoundaryError("public fixture Gateway reached another endpoint or Wwise version")
        return payload

    return invoke


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
    """Reuse existing media, generating only a proven distinct-content shortfall."""
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
    # The committed 2025 fixture has many names but only one distinct waveform.
    # Media-mapping oracles need different content; create the smallest missing
    # set only in this already-owned project copy, never in the source fixture.
    generated_root = ctx.project_path.parent / "ExpansionGeneratedMedia"
    if generated_root.exists() or generated_root.is_symlink():
        raise CaseBoundaryError("generated fixture media destination already exists")
    generated_root.mkdir()
    for index in range(count - len(found)):
        path = generated_root / f"distinct_{index + 1}.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"".join(
                (((frame * (index + 1)) % 64 - 32) * 128).to_bytes(2, "little", signed=True)
                for frame in range(800)
            ))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in digests:
            raise CaseBoundaryError("generated media did not provide distinct content")
        digests.add(digest)
        found.append(_owned_file(path, ctx.project_path.parent))
    return tuple(found)


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
