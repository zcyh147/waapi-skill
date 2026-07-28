#!/usr/bin/env python3
"""Build one compact object-type catalog from captured real getTypes evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from wwise_waapi.manifest import DeterministicJsonWriter  # noqa: E402
from wwise_waapi.metadata_catalog import (  # noqa: E402
    METADATA_CATALOG_ROOT,
    OBJECT_TYPE_CATALOG_FILENAME,
    build_object_type_catalog_payload,
)
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS  # noqa: E402


class ObjectTypeCatalogBuildError(RuntimeError):
    """Raised when source evidence cannot produce a deterministic catalog."""


def build_catalog_file(
    *,
    version: str,
    evidence_path: Path,
    output_root: Path = METADATA_CATALOG_ROOT,
    write: bool = False,
    check: bool = False,
) -> dict[str, Any]:
    if write and check:
        raise ObjectTypeCatalogBuildError(
            "write and check modes are mutually exclusive"
        )
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObjectTypeCatalogBuildError(
            f"Could not read getTypes evidence: {evidence_path}: {exc}"
        ) from exc
    payload = build_object_type_catalog_payload(evidence, version=version)
    writer = DeterministicJsonWriter()
    output_path = output_root / version / OBJECT_TYPE_CATALOG_FILENAME
    rendered = writer.dumps(payload)
    if check:
        if not output_path.is_file():
            raise ObjectTypeCatalogBuildError(
                f"Object-type catalog is missing: {output_path}"
            )
        if output_path.read_text(encoding="utf-8") != rendered:
            raise ObjectTypeCatalogBuildError(
                f"Object-type catalog is stale: {output_path}"
            )
    elif write:
        writer.write(output_path, payload)
    metadata = payload["metadata"]
    return {
        "checked": check,
        "contract": metadata["contract"],
        "output_path": str(output_path),
        "resource_sha256": metadata["resource_sha256"],
        "row_count": metadata["row_count"],
        "source_result_sha256": metadata["source_result_sha256"],
        "version": version,
        "write_performed": write,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        required=True,
        choices=SUPPORTED_WWISE_VERSION_KEYS,
    )
    parser.add_argument(
        "--evidence",
        required=True,
        type=Path,
        help="JSON result or dispatcher evidence for core.object.getTypes",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=METADATA_CATALOG_ROOT,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="Write the deterministic resource; default is preview only",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Fail unless the existing resource exactly matches the evidence",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        summary = build_catalog_file(
            version=args.version,
            evidence_path=args.evidence,
            output_root=args.output_root,
            write=args.write,
            check=args.check,
        )
    except (ObjectTypeCatalogBuildError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "ok": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {"ok": True, **summary},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main
    raise SystemExit(main())
