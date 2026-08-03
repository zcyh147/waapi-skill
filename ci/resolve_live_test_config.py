from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


CONFIG_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("WWISE_CONSOLE", ("wwise_console", "console_path")),
    (
        "WWISE_SAMPLE_PROJECT_PATH",
        ("sample_project", "sample_project_path"),
    ),
    ("WWISE_SANDBOX_ROOT", ("sandbox_root",)),
)


class LiveTestConfigError(ValueError):
    """Raised when a live-test configuration cannot be resolved safely."""


def _resolve_path(value: str, *, repo_root: Path) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    resolved = str(path.resolve(strict=False))
    if "\n" in resolved or "\r" in resolved:
        raise LiveTestConfigError("live-test paths must not contain line breaks")
    return resolved


def resolve_version_config(
    payload: Mapping[str, Any],
    *,
    version: str,
    repo_root: Path,
) -> dict[str, str]:
    """Resolve one version's configured paths with host-native ``pathlib`` rules."""

    versions = payload.get("versions", {})
    if not isinstance(versions, Mapping):
        raise LiveTestConfigError("live-test config field 'versions' must be an object")
    entry = versions.get(version, {})
    if not isinstance(entry, Mapping):
        raise LiveTestConfigError(
            f"live-test config entry for {version!r} must be an object"
        )

    root = repo_root.expanduser().resolve(strict=False)
    resolved: dict[str, str] = {}
    for environment_name, aliases in CONFIG_KEYS:
        for alias in aliases:
            value = entry.get(alias)
            if value is None:
                continue
            if not isinstance(value, str) or not value:
                raise LiveTestConfigError(
                    f"live-test config field {version}.{alias} must be a non-empty string"
                )
            resolved[environment_name] = _resolve_path(value, repo_root=root)
            break
    return resolved


def load_version_config(
    config_path: Path,
    *,
    version: str,
    repo_root: Path,
) -> dict[str, str]:
    try:
        payload = json.loads(config_path.expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LiveTestConfigError(
            f"could not read live-test config {config_path}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise LiveTestConfigError("live-test config root must be an object")
    return resolve_version_config(payload, version=version, repo_root=repo_root)


def _write_environment_lines(values: Mapping[str, str], output: Path | None) -> None:
    contents = "".join(f"{key}={value}\n" for key, value in values.items())
    if output is None:
        sys.stdout.write(contents)
        return
    output.write_text(contents, encoding="utf-8", newline="\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve versioned Wwise test paths using host-native pathlib rules."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        values = load_version_config(
            args.config,
            version=args.version,
            repo_root=args.repo_root,
        )
        _write_environment_lines(values, args.output)
    except (LiveTestConfigError, OSError) as exc:
        print(f"live-test config error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
