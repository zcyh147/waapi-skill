"""Cross-platform WwiseConsole and WAAPI wire-path helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping

from .endpoint_scope import is_loopback_waapi_host

try:  # ``pwd`` is unavailable on native Windows.
    import pwd
except ImportError:  # pragma: no cover - native Windows uses identity dispatch
    pwd = None  # type: ignore[assignment]


WINDOWS_WWISE_CONSOLE_PARTS = ("Authoring", "x64", "Release", "bin", "WwiseConsole.exe")
WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE = r"%WWISEROOT%\Authoring\x64\Release\bin\WwiseConsole.exe"
WWISE_WIRE_PATH_ADAPTATION_CONTRACT = "waapi-skill.wwise-wire-path-adaptation/v1"
WWISE_WIRE_PATH_INPUT_AUDIT_CONTRACT = (
    "waapi-skill.wwise-wire-path-input-audit/v1"
)
WINE_WIRE_PATH_WAAPI_URIS = frozenset(
    {
        "ak.wwise.console.project.create",
        "ak.wwise.console.project.open",
        "ak.wwise.core.audio.importTabDelimited",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.ui.project.create",
        "ak.wwise.ui.project.open",
    }
)
_AUTHORING_PROJECT_TRANSITION_URIS = frozenset(
    {
        "ak.wwise.ui.project.create",
        "ak.wwise.ui.project.open",
    }
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_WIRE_DRIVE_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")
_WINDOWS_UNSAFE_COMPONENT = re.compile(r'[<>:"|?*]')


class WwiseWirePathError(ValueError):
    """A host path cannot be proven equivalent to a Wwise/Wine wire path."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class WwiseWireDispatch:
    """One transient dispatch plus its bounded host/wire equivalence proof."""

    args: Mapping[str, Any]
    options: Mapping[str, Any]
    proof: Mapping[str, Any]


def adapt_cli_dispatch_paths(
    *,
    uri: str,
    args: Mapping[str, Any],
    options: Mapping[str, Any],
    io_audit: Mapping[str, Any],
    project_guard: Mapping[str, Any],
    current_project_guard: Mapping[str, Any] | None = None,
    host_os_name: str | None = None,
    account_home: str | Path | None = None,
) -> WwiseWireDispatch:
    """Translate audited POSIX paths only for a proven local Wine runtime.

    The immutable transaction request and I/O audit remain host-native.  This
    helper deep-copies the dispatch and replaces only the exact JSON paths
    named by that audit.  A translated path must round-trip through the same
    sealed Wine drive mapping before the transient dispatch is returned.  The
    translation surface is closed to Wwise CLI calls plus reviewed Console and
    Core WAAPI functions whose reflected payloads contain OS paths.
    """

    host_dispatch = {"args": _strict_json_copy(args), "options": _strict_json_copy(options)}
    live_project_guard = project_guard if current_project_guard is None else current_project_guard
    sealed_fingerprint = project_guard.get("fingerprint")
    current_fingerprint = live_project_guard.get("fingerprint")
    if current_project_guard is not None and sealed_fingerprint != current_fingerprint:
        raise WwiseWirePathError(
            "WIRE_PATH_PROJECT_GUARD_MISMATCH",
            "The live project guard no longer matches the sealed transaction preview.",
            details={
                "expected_fingerprint": sealed_fingerprint,
                "actual_fingerprint": current_fingerprint,
            },
        )
    effective_os_name = os.name if host_os_name is None else host_os_name
    if effective_os_name == "nt" or not requires_wwise_wire_path_adaptation(uri):
        mode = (
            "native_windows_identity"
            if effective_os_name == "nt"
            else "non_path_adapted_uri_identity"
        )
        proof = _identity_adaptation_proof(
            uri,
            host_dispatch,
            project_guard,
            current_project_guard=live_project_guard,
            mode=mode,
        )
        return WwiseWireDispatch(
            args=host_dispatch["args"],
            options=host_dispatch["options"],
            proof=proof,
        )

    audit_uri = io_audit.get("uri")
    audit_paths = io_audit.get("paths")
    if audit_uri != uri or not isinstance(audit_paths, list):
        raise WwiseWirePathError(
            "WIRE_PATH_AUDIT_MISMATCH",
            "The sealed isolated-I/O audit does not match the CLI dispatch.",
            details={"uri": uri, "audit_uri": audit_uri},
        )

    endpoint = live_project_guard.get("endpoint")
    wwise = live_project_guard.get("wwise")
    project = live_project_guard.get("project")
    if not isinstance(endpoint, Mapping) or not isinstance(wwise, Mapping) or not isinstance(project, Mapping):
        raise WwiseWirePathError(
            "WIRE_PATH_CONTEXT_UNAVAILABLE",
            "The sealed project guard lacks endpoint, Wwise, or project path evidence.",
        )
    endpoint_host = endpoint.get("host")
    process_path = wwise.get("processPath")
    project_wire_path = next(
        (
            project.get(field)
            for field in ("path", "projectPath", "filePath")
            if (
                isinstance(project.get(field), str)
                and (
                    _WINDOWS_ABSOLUTE_PATH.match(project.get(field)) is not None
                    or Path(project.get(field)).is_absolute()
                )
            )
        ),
        None,
    )
    windows_runtime = isinstance(process_path, str) and _WINDOWS_ABSOLUTE_PATH.match(process_path) is not None
    if not windows_runtime:
        native_posix_process = (
            isinstance(process_path, str)
            and PurePosixPath(process_path).is_absolute()
        )
        local_endpoint = (
            isinstance(endpoint_host, str)
            and is_loopback_waapi_host(endpoint_host)
        )
        if native_posix_process and local_endpoint:
            proof = _identity_adaptation_proof(
                uri,
                host_dispatch,
                project_guard,
                current_project_guard=live_project_guard,
                mode="native_posix_identity",
            )
            return WwiseWireDispatch(
                args=host_dispatch["args"],
                options=host_dispatch["options"],
                proof=proof,
            )
        raise WwiseWirePathError(
            "WIRE_PATH_CONTEXT_UNAVAILABLE",
            "The local CLI runtime is neither a proven native POSIX process nor a proven Wine process.",
            details={"process_path": process_path, "project_path": project_wire_path},
        )
    if not isinstance(endpoint_host, str) or not is_loopback_waapi_host(
        endpoint_host
    ):
        raise WwiseWirePathError(
            "REMOTE_WWISE_PATH_MAPPING_UNAVAILABLE",
            "Host paths cannot be mapped into a remote Windows Wwise filesystem.",
            details={"endpoint_host": endpoint_host},
        )
    home = _account_home(account_home)
    if isinstance(project_wire_path, str):
        drive, _, anchor_host = _prove_wire_mapping(
            project_wire_path,
            account_home=home,
        )
        anchor_wire_path = _normalize_wire_path(project_wire_path)
        anchor_source = "current_project"
        if (
            not anchor_host.is_file()
            or anchor_host.is_symlink()
            or anchor_host.suffix.casefold() != ".wproj"
        ):
            raise WwiseWirePathError(
                "WIRE_PATH_ANCHOR_INVALID",
                "The sealed Wine project path does not round-trip to one regular local .wproj file.",
                details={"localized_project_path": str(anchor_host)},
            )
    else:
        postcondition = live_project_guard.get("postcondition")
        target_path = (
            postcondition.get("canonical_path")
            if isinstance(postcondition, Mapping)
            else None
        )
        if (
            uri not in _AUTHORING_PROJECT_TRANSITION_URIS
            or project.get("state") != "none"
            or live_project_guard.get("project_guard_mode") != "transition_to_path"
            or not isinstance(target_path, str)
        ):
            raise WwiseWirePathError(
                "WIRE_PATH_CONTEXT_UNAVAILABLE",
                "The local Wine project guard has no absolute project path anchor.",
            )
        if not target_path.startswith("posix:/"):
            raise WwiseWirePathError(
                "WIRE_PATH_CONTEXT_UNAVAILABLE",
                "The Authoring project transition target is not a canonical local POSIX path.",
                details={"canonical_target_project_path": target_path},
            )
        anchor_host = Path(target_path.removeprefix("posix:")).resolve(strict=False)
        if (
            not anchor_host.is_absolute()
            or anchor_host.is_symlink()
            or anchor_host.suffix.casefold() != ".wproj"
            or (
                uri == "ak.wwise.ui.project.open"
                and not anchor_host.is_file()
            )
            or (
                uri == "ak.wwise.ui.project.create"
                and not anchor_host.parent.is_dir()
            )
        ):
            raise WwiseWirePathError(
                "WIRE_PATH_ANCHOR_INVALID",
                "The Authoring project transition target is not a valid local .wproj anchor.",
                details={"target_project_path": str(anchor_host)},
            )
        drive, mapping_root = _mapping_for_host_path(
            anchor_host,
            account_home=home,
        )
        anchor_wire_path = _host_to_wire_path(
            anchor_host,
            drive=drive,
            mapping_root=mapping_root,
        )
        if (
            _wire_to_host_path(anchor_wire_path, account_home=home).resolve(
                strict=False
            )
            != anchor_host
        ):
            raise WwiseWirePathError(
                "WIRE_PATH_ROUND_TRIP_FAILED",
                "The Authoring project transition target did not round-trip through its Wine mapping.",
                details={"drive": drive},
            )
        anchor_source = "transition_target"

    indexed_audit: dict[tuple[str, str], Mapping[str, Any]] = {}
    for index, row in enumerate(audit_paths):
        if not isinstance(row, Mapping):
            raise WwiseWirePathError(
                "WIRE_PATH_AUDIT_MISMATCH",
                "The isolated-I/O audit contains a malformed path row.",
                details={"index": index},
            )
        section = row.get("section")
        json_path = row.get("json_path")
        if section not in {"args", "options"} or not isinstance(json_path, str):
            raise WwiseWirePathError(
                "WIRE_PATH_AUDIT_MISMATCH",
                "The isolated-I/O audit contains an unsupported path location.",
                details={"index": index, "section": section, "json_path": json_path},
            )
        key = (section, json_path)
        if key in indexed_audit:
            raise WwiseWirePathError(
                "WIRE_PATH_AUDIT_MISMATCH",
                "The isolated-I/O audit contains a duplicate JSON path.",
                details={"section": section, "json_path": json_path},
            )
        indexed_audit[key] = row

    consumed: set[tuple[str, str]] = set()
    bindings: list[dict[str, Any]] = []

    def transform(value: Any, *, section: str, path: tuple[str | int, ...]) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): transform(item, section=section, path=(*path, str(key)))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                transform(item, section=section, path=(*path, index))
                for index, item in enumerate(value)
            ]
        if not isinstance(value, str):
            return value
        json_path = _json_path(path)
        row = indexed_audit.get((section, json_path))
        if row is None:
            return value
        key = (section, json_path)
        consumed.add(key)
        raw_path = row.get("raw_path")
        resolved_path = row.get("resolved_path")
        if raw_path != value or not isinstance(resolved_path, str):
            raise WwiseWirePathError(
                "WIRE_PATH_AUDIT_MISMATCH",
                "The CLI request no longer matches its sealed isolated-I/O audit.",
                details={"section": section, "json_path": json_path},
            )
        raw_host_path = Path(value)
        resolved_host_path = Path(resolved_path)
        if not resolved_host_path.is_absolute():
            raise WwiseWirePathError(
                "WIRE_PATH_AUDIT_MISMATCH",
                "An audited host path has no absolute resolved path.",
                details={"section": section, "json_path": json_path},
            )
        path_drive, path_mapping_root = _mapping_for_host_path(
            resolved_host_path,
            account_home=home,
        )
        wire_path = _host_to_wire_path(
            resolved_host_path,
            drive=path_drive,
            mapping_root=path_mapping_root,
        )
        round_trip = _wire_to_host_path(
            wire_path,
            account_home=home,
        ).resolve(strict=False)
        expected_host = resolved_host_path.resolve(strict=False)
        if round_trip != expected_host:
            raise WwiseWirePathError(
                "WIRE_PATH_ROUND_TRIP_FAILED",
                "A translated Wwise path did not round-trip to the audited host path.",
                details={"section": section, "json_path": json_path},
            )
        bindings.append(
            {
                "section": section,
                "json_path": json_path,
                "mode": (
                    "translated"
                    if raw_host_path.is_absolute()
                    else "relative_resolved_then_translated"
                ),
                "drive": path_drive,
                "host_path_sha256": hashlib.sha256(str(expected_host).encode("utf-8")).hexdigest(),
                "wire_path_sha256": hashlib.sha256(wire_path.encode("utf-8")).hexdigest(),
                "round_trip_verified": True,
            }
        )
        return wire_path

    wire_dispatch = {
        "args": transform(host_dispatch["args"], section="args", path=("args",)),
        "options": transform(host_dispatch["options"], section="options", path=("options",)),
    }
    missing = sorted(set(indexed_audit) - consumed)
    if missing:
        raise WwiseWirePathError(
            "WIRE_PATH_AUDIT_MISMATCH",
            "The CLI dispatch did not contain every path sealed by its isolated-I/O audit.",
            details={
                "missing": [
                    {"section": section, "json_path": json_path}
                    for section, json_path in missing
                ]
            },
        )
    translated_count = sum(
        row["mode"] in {"translated", "relative_resolved_then_translated"}
        for row in bindings
    )
    proof = {
        "contract": WWISE_WIRE_PATH_ADAPTATION_CONTRACT,
        "uri": uri,
        "mode": "local_posix_wine",
        "applied": translated_count > 0,
        "project_guard_fingerprint": sealed_fingerprint,
        "current_project_guard_fingerprint": current_fingerprint,
        "mapping": {
            "anchor_drive": drive,
            "anchor_source": anchor_source,
            "supported_drives": ["Y", "Z"],
            "anchor_host_path_sha256": hashlib.sha256(str(anchor_host).encode("utf-8")).hexdigest(),
            "anchor_wire_path_sha256": hashlib.sha256(
                anchor_wire_path.encode("utf-8")
            ).hexdigest(),
            "round_trip_verified": True,
        },
        "path_count": len(bindings),
        "translated_path_count": translated_count,
        "path_bindings": bindings,
        "host_dispatch_sha256": _json_sha256(host_dispatch),
        "wire_dispatch_sha256": _json_sha256(wire_dispatch),
    }
    return WwiseWireDispatch(
        args=wire_dispatch["args"],
        options=wire_dispatch["options"],
        proof=proof,
    )


def requires_wwise_wire_path_adaptation(uri: str) -> bool:
    """Return whether *uri* is in the closed Wine wire-path translation set."""

    return isinstance(uri, str) and (
        uri.startswith("ak.wwise.cli.") or uri in WINE_WIRE_PATH_WAAPI_URIS
    )


def localize_live_wwise_project_path(
    value: str,
    *,
    endpoint: Mapping[str, Any],
    wwise: Mapping[str, Any],
    host_os_name: str | None = None,
    account_home: str | Path | None = None,
) -> str:
    """Map one live local-Wine project path back to its host identity.

    Project-transition previews retain the caller's host path, while Wwise
    running through Wine reports the opened project through its Y:/Z: drive.
    Verification compares those identities only after the returned wire path
    round-trips to one existing regular local WPROJ file.
    """

    if not isinstance(value, str) or not value:
        raise WwiseWirePathError(
            "WIRE_PATH_CONTEXT_UNAVAILABLE",
            "The live Wwise project path is empty or malformed.",
        )
    effective_os_name = os.name if host_os_name is None else host_os_name
    if effective_os_name == "nt":
        return value
    process_path = wwise.get("processPath")
    windows_runtime = (
        isinstance(process_path, str)
        and _WINDOWS_ABSOLUTE_PATH.match(process_path) is not None
    )
    if not windows_runtime:
        return value
    endpoint_host = endpoint.get("host")
    if not isinstance(endpoint_host, str) or not is_loopback_waapi_host(
        endpoint_host
    ):
        return value
    localized = _wire_to_host_path(value, account_home=_account_home(account_home))
    if localized.is_symlink():
        raise WwiseWirePathError(
            "WIRE_PATH_ANCHOR_INVALID",
            "The live Wine project path must not be a symlink.",
            details={"project_path": value, "localized_project_path": str(localized)},
        )
    try:
        resolved = localized.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WwiseWirePathError(
            "WIRE_PATH_ANCHOR_INVALID",
            "The live Wine project path does not resolve to a local file.",
            details={"project_path": value, "reason": str(exc)},
        ) from exc
    if (
        not resolved.is_file()
        or resolved.suffix.casefold() != ".wproj"
    ):
        raise WwiseWirePathError(
            "WIRE_PATH_ANCHOR_INVALID",
            "The live Wine project path does not identify one regular local .wproj file.",
            details={"project_path": value, "localized_project_path": str(resolved)},
        )
    return str(resolved)


def _identity_adaptation_proof(
    uri: str,
    dispatch: Mapping[str, Any],
    project_guard: Mapping[str, Any],
    *,
    current_project_guard: Mapping[str, Any],
    mode: str,
) -> dict[str, Any]:
    digest = _json_sha256(dispatch)
    return {
        "contract": WWISE_WIRE_PATH_ADAPTATION_CONTRACT,
        "uri": uri,
        "mode": mode,
        "applied": False,
        "project_guard_fingerprint": project_guard.get("fingerprint"),
        "current_project_guard_fingerprint": current_project_guard.get("fingerprint"),
        "mapping": None,
        "path_count": 0,
        "translated_path_count": 0,
        "path_bindings": [],
        "host_dispatch_sha256": digest,
        "wire_dispatch_sha256": digest,
    }


def _account_home(value: str | Path | None) -> Path:
    if value is not None:
        candidate = Path(value)
    else:
        if pwd is None:  # pragma: no cover - native Windows exits earlier
            raise WwiseWirePathError(
                "WIRE_PATH_CONTEXT_UNAVAILABLE",
                "The login account home is unavailable for Wine Y: mapping.",
            )
        try:
            candidate = Path(pwd.getpwuid(os.getuid()).pw_dir)
        except (KeyError, OSError) as exc:
            raise WwiseWirePathError(
                "WIRE_PATH_CONTEXT_UNAVAILABLE",
                "The login account home is unavailable for Wine Y: mapping.",
                details={"reason": str(exc)},
            ) from exc
    if not candidate.is_absolute():
        raise WwiseWirePathError(
            "WIRE_PATH_CONTEXT_UNAVAILABLE",
            "The login account home must be an absolute path.",
            details={"account_home": str(candidate)},
        )
    try:
        return candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WwiseWirePathError(
            "WIRE_PATH_CONTEXT_UNAVAILABLE",
            "The login account home could not be resolved.",
            details={"account_home": str(candidate), "reason": str(exc)},
        ) from exc


def _prove_wire_mapping(
    project_wire_path: str,
    *,
    account_home: Path,
) -> tuple[str, Path, Path]:
    normalized = _normalize_wire_path(project_wire_path)
    match = _WIRE_DRIVE_PATH.fullmatch(normalized)
    if match is None:
        raise WwiseWirePathError(
            "WIRE_PATH_CONTEXT_UNAVAILABLE",
            "The local Wine project path is not an absolute drive path.",
            details={"project_path": project_wire_path},
        )
    drive = match.group(1).upper()
    if drive == "Y":
        mapping_root = account_home
    elif drive == "Z":
        mapping_root = Path("/")
    else:
        raise WwiseWirePathError(
            "WIRE_PATH_DRIVE_UNSUPPORTED",
            "Only a live Y: or Z: Wine project anchor can authorize host-path translation.",
            details={"drive": drive},
        )
    anchor_host = _wire_to_host_path(normalized, account_home=account_home)
    expected_wire = _host_to_wire_path(
        anchor_host.resolve(strict=False),
        drive=drive,
        mapping_root=mapping_root,
    )
    if expected_wire.casefold() != normalized.casefold():
        raise WwiseWirePathError(
            "WIRE_PATH_ROUND_TRIP_FAILED",
            "The sealed Wine project path did not round-trip through its host mapping.",
            details={"drive": drive},
        )
    return drive, mapping_root, anchor_host.resolve(strict=False)


def _wire_to_host_path(value: str, *, account_home: Path) -> Path:
    normalized = _normalize_wire_path(value)
    match = _WIRE_DRIVE_PATH.fullmatch(normalized)
    if match is None:
        raise WwiseWirePathError(
            "WIRE_PATH_CONTEXT_UNAVAILABLE",
            "Wwise wire path must be an absolute drive path.",
        )
    drive = match.group(1).upper()
    mapping_root = account_home if drive == "Y" else Path("/") if drive == "Z" else None
    if mapping_root is None:
        raise WwiseWirePathError(
            "WIRE_PATH_DRIVE_UNSUPPORTED",
            "Wwise wire path uses an unsupported drive.",
            details={"drive": drive},
        )
    suffix = match.group(2)
    components = suffix.split("\\") if suffix else []
    _validate_wire_components(components)
    return mapping_root.joinpath(*components)


def _host_to_wire_path(
    value: Path,
    *,
    drive: str,
    mapping_root: Path,
) -> str:
    path = value.resolve(strict=False)
    root = mapping_root.resolve(strict=False)
    try:
        components = path.relative_to(root).parts
    except ValueError as exc:
        raise WwiseWirePathError(
            "WIRE_PATH_OUTSIDE_PROVEN_MAPPING",
            "An audited host path is outside the live Wine drive mapping.",
            details={"drive": drive},
        ) from exc
    _validate_wire_components(list(components))
    suffix = "\\".join(components)
    return f"{drive}:\\{suffix}" if suffix else f"{drive}:\\"


def _mapping_for_host_path(
    value: Path,
    *,
    account_home: Path,
) -> tuple[str, Path]:
    path = value.resolve(strict=False)
    try:
        path.relative_to(account_home)
    except ValueError:
        return "Z", Path("/")
    return "Y", account_home


def _validate_wire_components(components: list[str]) -> None:
    for component in components:
        if (
            not component
            or component in {".", ".."}
            or "\x00" in component
            or "\\" in component
            or "/" in component
            or _WINDOWS_UNSAFE_COMPONENT.search(component) is not None
            or component.endswith((" ", "."))
        ):
            raise WwiseWirePathError(
                "WIRE_PATH_COMPONENT_UNSAFE",
                "A host path component cannot be represented safely on the Wwise Wine drive.",
            )


def _normalize_wire_path(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise WwiseWirePathError(
            "WIRE_PATH_CONTEXT_UNAVAILABLE",
            "Wwise wire path must be a non-empty exact string.",
        )
    if value.startswith(("\\\\", "//")):
        raise WwiseWirePathError(
            "WIRE_PATH_CONTEXT_UNAVAILABLE",
            "UNC paths cannot establish a local Wine drive mapping.",
        )
    return value.replace("/", "\\")


def _json_path(parts: tuple[str | int, ...]) -> str:
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def _strict_json_copy(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise WwiseWirePathError(
            "WIRE_PATH_DISPATCH_INVALID",
            "CLI dispatch must contain strict JSON values before path adaptation.",
            details={"reason": str(exc)},
        ) from exc


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def windows_wwise_console_path(wwise_root: str) -> PureWindowsPath:
    """Return the Windows WwiseConsole path below a WWISEROOT value."""

    return PureWindowsPath(wwise_root).joinpath(*WINDOWS_WWISE_CONSOLE_PARTS)


def resolve_windows_wwise_console_from_env(env: Mapping[str, str]) -> PureWindowsPath | None:
    """Resolve WwiseConsole from WWISEROOT without shell expansion."""

    wwise_root = env.get("WWISEROOT")
    if not wwise_root:
        return None
    return windows_wwise_console_path(wwise_root)


def build_wwise_console_command(
    console_path: str | Path | PurePath,
    port: int,
    project_path: str | Path | PurePath | None = None,
    extra_args: Iterable[str] = (),
) -> list[str]:
    """Build a shell-safe argv list for a WAMP-only WwiseConsole WAAPI server.

    WwiseConsole otherwise starts the unused HTTP POST endpoint on its fixed
    default port 8090.  Explicitly disabling that endpoint keeps a headless
    WAMP lifecycle independent from an already-running Authoring instance.
    """

    project_args = [str(project_path)] if project_path is not None else []
    return [
        str(console_path),
        "waapi-server",
        *project_args,
        "--wamp-port",
        str(port),
        "--http-port",
        "0",
        *[str(arg) for arg in extra_args],
    ]
