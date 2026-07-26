#!/usr/bin/env python3
"""Collect the fixed Authoring ``ui.commands`` evidence for one Wwise version.

This maintenance tool intentionally does not call ``waapi.getFunctions`` or
``waapi.getTopics``.  It reads only ``getInfo``, the five fixed schemas, and
``ui.commands.getCommands`` from an already-running Wwise Authoring process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from wwise_waapi.authoring_ui_commands_manifest import (  # noqa: E402
    AUTHORING_HOST_SURFACE,
    AUTHORING_UI_COMMAND_FUNCTION_URIS,
    AUTHORING_UI_COMMAND_TOPIC_URIS,
    AUTHORING_UI_COMMAND_URIS,
    AUTHORING_UI_COMMANDS_SUPPLEMENT_FILENAME,
    AuthoringUiCommandsSupplement,
    build_authoring_ui_commands_supplement,
)
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256  # noqa: E402
from wwise_waapi.manifest import (  # noqa: E402
    DeterministicJsonWriter,
    ManifestStore,
)
from wwise_waapi.versions import (  # noqa: E402
    SUPPORTED_WWISE_VERSION_KEYS,
    WWISE_VERSION_CONTRACTS,
    version_key_from_get_info,
)


GET_INFO_URI = "ak.wwise.core.getInfo"
GET_SCHEMA_URI = "ak.wwise.waapi.getSchema"
GET_COMMANDS_URI = "ak.wwise.ui.commands.getCommands"
COMMAND_INVENTORY_FILENAME = "authoring-ui-command-inventory.json"
COMMAND_INVENTORY_CONTRACT = "waapi-authoring-ui-command-inventory/v1"
MAINTENANCE_PREVIEW_CONTRACT = (
    "waapi-authoring-ui-command-maintenance-preview/v1"
)
MAX_COMMAND_COUNT = 4096
MAX_COMMAND_ID_CHARS = 512
MAX_COMMAND_INVENTORY_BYTES = 1_000_000
COMMAND_PREVIEW_LIMIT = 20
DEFAULT_MANIFEST_ROOT = SKILL_ROOT / "resources" / "manifest"
_LOCAL_PATH_PATTERN = re.compile(
    r"(?:/(?:Applications|Users|Volumes|private|tmp)/[^\n\r\t\"'<>]+)"
    r"|(?:[A-Za-z]:\\[^\n\r\t\"'<>]+)"
)


class AuthoringUiCommandsCollectionError(RuntimeError):
    """Raised when targeted Authoring evidence is incomplete or inconsistent."""


class WaapiCaller(Protocol):
    def call(self, uri: str, *args: Any, **kwargs: Any) -> Any:
        """Call one WAAPI URI."""


@dataclass(frozen=True, slots=True)
class AuthoringUiCommandsArtifacts:
    """Validated in-memory artifacts produced before any repository write."""

    version: str
    wwise_build: str
    supplement: AuthoringUiCommandsSupplement
    command_inventory: dict[str, Any]
    manifest_root: Path

    @property
    def supplement_path(self) -> Path:
        return (
            self.manifest_root
            / self.version
            / AUTHORING_UI_COMMANDS_SUPPLEMENT_FILENAME
        )

    @property
    def command_inventory_path(self) -> Path:
        return (
            self.manifest_root
            / self.version
            / COMMAND_INVENTORY_FILENAME
        )

    def write(self) -> tuple[Path, Path]:
        store = ManifestStore(root=self.manifest_root)
        supplement_path = store.write_authoring_ui_commands_supplement(
            self.supplement
        )
        if supplement_path is None:  # pragma: no cover - root is always present
            raise AuthoringUiCommandsCollectionError(
                "A filesystem manifest root is required for --write"
            )
        DeterministicJsonWriter().write(
            self.command_inventory_path,
            self.command_inventory,
        )
        return supplement_path, self.command_inventory_path

    def summary(self, *, wrote: bool) -> dict[str, Any]:
        writer = DeterministicJsonWriter()
        supplement_payload = self.supplement.as_dict()
        command_payload = self.command_inventory
        commands = command_payload["commands"]
        return {
            "artifacts": [
                _artifact_summary(
                    "authoring_ui_commands_supplement",
                    self.supplement_path,
                    supplement_payload,
                    writer=writer,
                ),
                _artifact_summary(
                    "authoring_ui_command_inventory",
                    self.command_inventory_path,
                    command_payload,
                    writer=writer,
                ),
            ],
            "command_inventory": {
                "absolute_cross_machine_inventory": False,
                "command_count": command_payload["audit"]["command_count"],
                "inventory_sha256": command_payload["audit"][
                    "inventory_sha256"
                ],
                "observed_current_project_and_plugins": True,
                "sample": commands[:COMMAND_PREVIEW_LIMIT],
                "sample_truncated": len(commands) > COMMAND_PREVIEW_LIMIT,
            },
            "contract": MAINTENANCE_PREVIEW_CONTRACT,
            "mode": "write" if wrote else "preview",
            "repository_write_performed": wrote,
            "version": self.version,
            "wwise_build": self.wwise_build,
        }


def collect_authoring_ui_commands(
    caller: WaapiCaller,
    *,
    version: str,
    manifest_root: Path = DEFAULT_MANIFEST_ROOT,
) -> AuthoringUiCommandsArtifacts:
    """Collect exactly the fixed call plan and build both repository artifacts."""

    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise AuthoringUiCommandsCollectionError(
            f"Unsupported Wwise version {version!r}"
        )
    info = caller.call(GET_INFO_URI)
    wwise_build = _validate_authoring_info(info, expected_version=version)

    schema_rows: list[dict[str, Any]] = []
    for uri in sorted(AUTHORING_UI_COMMAND_URIS):
        schema = caller.call(GET_SCHEMA_URI, {"uri": uri})
        schema_rows.append(
            {
                "schema": _sanitize_json(schema),
                "status": "ok",
                "uri": uri,
            }
        )

    commands_result = caller.call(GET_COMMANDS_URI)
    command_inventory = build_command_inventory(
        commands_result,
        version=version,
        wwise_build=wwise_build,
    )
    authoring_manifest = {
        "functions": [
            _inventory_row(uri, "function")
            for uri in sorted(AUTHORING_UI_COMMAND_FUNCTION_URIS)
        ],
        "metadata": {
            "host_surface": AUTHORING_HOST_SURFACE,
            "inventory_source": "targeted-authoring-ui-commands-collection",
            "manifest_origin": "direct-targeted-reflection",
            "wwise_build": wwise_build,
            "wwise_version_target": version,
        },
        "schemas": schema_rows,
        "topics": [
            _inventory_row(uri, "topic")
            for uri in sorted(AUTHORING_UI_COMMAND_TOPIC_URIS)
        ],
    }
    console_manifest = ManifestStore(root=manifest_root).load(version)
    supplement = build_authoring_ui_commands_supplement(
        console_manifest,
        authoring_manifest,
        version=version,
        inventory_source="targeted-authoring-ui-commands-collection",
    )
    return AuthoringUiCommandsArtifacts(
        version=version,
        wwise_build=wwise_build,
        supplement=supplement,
        command_inventory=command_inventory,
        manifest_root=manifest_root.resolve(strict=False),
    )


def build_command_inventory(
    result: Any,
    *,
    version: str,
    wwise_build: str,
) -> dict[str, Any]:
    """Validate and bound the session-specific command IDs."""

    if not isinstance(result, Mapping):
        raise AuthoringUiCommandsCollectionError(
            "ui.commands.getCommands result must be an object"
        )
    if set(result) != {"commands"}:
        raise AuthoringUiCommandsCollectionError(
            "ui.commands.getCommands result must contain only 'commands'"
        )
    raw_commands = result.get("commands")
    if not isinstance(raw_commands, list):
        raise AuthoringUiCommandsCollectionError(
            "ui.commands.getCommands commands must be an array"
        )
    if len(raw_commands) > MAX_COMMAND_COUNT:
        raise AuthoringUiCommandsCollectionError(
            f"Command count exceeds the {MAX_COMMAND_COUNT} item ceiling"
        )
    commands: list[str] = []
    for index, command in enumerate(raw_commands):
        if (
            not isinstance(command, str)
            or not command
            or len(command) > MAX_COMMAND_ID_CHARS
        ):
            raise AuthoringUiCommandsCollectionError(
                f"commands[{index}] must be a non-empty string of at most "
                f"{MAX_COMMAND_ID_CHARS} characters"
            )
        commands.append(command)
    if len(set(commands)) != len(commands):
        raise AuthoringUiCommandsCollectionError(
            "ui.commands.getCommands returned duplicate command IDs"
        )
    commands.sort()
    metadata = {
        "absolute_cross_machine_inventory": False,
        "bounded": True,
        "host_surface": AUTHORING_HOST_SURFACE,
        "inventory_scope": "observed-current-authoring-session",
        "observed_current_project_and_plugins": True,
        "source_uri": GET_COMMANDS_URI,
        "variation_factors": [
            "current_project",
            "installed_plugins",
            "registered_add-ons",
            "wwise_build",
        ],
        "wwise_build": wwise_build,
        "wwise_version_target": version,
    }
    unsigned = {
        "commands": commands,
        "contract": COMMAND_INVENTORY_CONTRACT,
        "metadata": metadata,
    }
    payload = {
        "audit": {
            "command_count": len(commands),
            "inventory_sha256": canonical_sha256(unsigned),
        },
        **unsigned,
    }
    observed_bytes = len(canonical_json_bytes(payload))
    if observed_bytes > MAX_COMMAND_INVENTORY_BYTES:
        raise AuthoringUiCommandsCollectionError(
            "Command inventory exceeds the "
            f"{MAX_COMMAND_INVENTORY_BYTES} byte ceiling"
        )
    return payload


def execute_maintenance(
    argv: Sequence[str] | None = None,
    *,
    caller_factory: Callable[[str], WaapiCaller] | None = None,
) -> dict[str, Any]:
    """Run one preview/write action and return its bounded summary."""

    args = build_parser().parse_args(argv)
    factory = caller_factory or _default_caller_factory
    caller = factory(args.url)
    try:
        artifacts = collect_authoring_ui_commands(
            caller,
            version=args.version,
            manifest_root=args.manifest_root,
        )
        if args.write:
            artifacts.write()
        return artifacts.summary(wrote=bool(args.write))
    finally:
        disconnect = getattr(caller, "disconnect", None)
        if callable(disconnect):
            disconnect()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        required=True,
        choices=SUPPORTED_WWISE_VERSION_KEYS,
    )
    parser.add_argument(
        "--url",
        default="ws://127.0.0.1:8080/waapi",
        help="WAAPI URL for an already-running Wwise Authoring process",
    )
    parser.add_argument(
        "--manifest-root",
        type=Path,
        default=DEFAULT_MANIFEST_ROOT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write both deterministic resources; default is preview-only",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        summary = execute_maintenance(argv)
    except AuthoringUiCommandsCollectionError as exc:
        print(
            json.dumps(
                {
                    "contract": MAINTENANCE_PREVIEW_CONTRACT,
                    "error": str(exc),
                    "ok": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(DeterministicJsonWriter().dumps(summary), end="")
    return 0


def _validate_authoring_info(
    result: Any,
    *,
    expected_version: str,
) -> str:
    if not isinstance(result, Mapping):
        raise AuthoringUiCommandsCollectionError(
            "ak.wwise.core.getInfo result must be an object"
        )
    if result.get("isCommandLine") is not False:
        raise AuthoringUiCommandsCollectionError(
            "Collector requires Wwise Authoring with isCommandLine=false"
        )
    try:
        actual_version = version_key_from_get_info(result)
    except ValueError as exc:
        raise AuthoringUiCommandsCollectionError(str(exc)) from exc
    if actual_version != expected_version:
        raise AuthoringUiCommandsCollectionError(
            f"Connected Wwise version is {actual_version}, expected "
            f"{expected_version}"
        )
    version = result.get("version")
    assert isinstance(version, Mapping)
    values: list[int] = []
    for field_name in ("year", "major", "minor", "build"):
        value = version.get(field_name)
        if type(value) is not int:
            raise AuthoringUiCommandsCollectionError(
                f"getInfo version.{field_name} must be an integer"
            )
        values.append(value)
    actual_build = ".".join(str(value) for value in values)
    expected_build = WWISE_VERSION_CONTRACTS[expected_version].build
    if actual_build != expected_build:
        raise AuthoringUiCommandsCollectionError(
            f"Connected Wwise build is {actual_build}, expected {expected_build}"
        )
    return actual_build


def _inventory_row(uri: str, item_type: str) -> dict[str, Any]:
    return {
        "reflection": {"uri": uri},
        "type": item_type,
        "uri": uri,
    }


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_json(value[key])
            for key in sorted(value)
        }
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, str):
        return _LOCAL_PATH_PATTERN.sub("<path>", value)
    if value is None or type(value) in {bool, int, float}:
        try:
            canonical_json_bytes(value)
        except (TypeError, ValueError) as exc:
            raise AuthoringUiCommandsCollectionError(
                "WAAPI reflection must contain finite JSON values"
            ) from exc
        return value
    raise AuthoringUiCommandsCollectionError(
        f"WAAPI reflection contains unsupported JSON value {type(value).__name__}"
    )


def _artifact_summary(
    kind: str,
    path: Path,
    payload: Mapping[str, Any],
    *,
    writer: DeterministicJsonWriter,
) -> dict[str, Any]:
    encoded = writer.dumps(payload).encode("utf-8")
    return {
        "bytes": len(encoded),
        "kind": kind,
        "path": str(path),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _default_caller_factory(url: str) -> WaapiCaller:
    from waapi import WaapiClient  # type: ignore[import-not-found]

    return WaapiClient(url=url, allow_exception=True)


if __name__ == "__main__":
    raise SystemExit(main())
