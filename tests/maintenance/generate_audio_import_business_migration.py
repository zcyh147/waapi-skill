"""Regenerate the reviewed ``audio.import`` deep-interface migration inventory."""

from __future__ import annotations

import argparse
import json

from audio_import_business_migration import (
    AUDIO_IMPORT_MIGRATION_RESOURCE,
    build_audio_import_migration_inventory,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    expected = json.dumps(
        build_audio_import_migration_inventory(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if arguments.check:
        if not AUDIO_IMPORT_MIGRATION_RESOURCE.is_file():
            raise SystemExit("audio.import migration inventory is missing")
        if AUDIO_IMPORT_MIGRATION_RESOURCE.read_text("utf-8") != expected:
            raise SystemExit("audio.import migration inventory is stale")
        return 0
    AUDIO_IMPORT_MIGRATION_RESOURCE.parent.mkdir(parents=True, exist_ok=True)
    AUDIO_IMPORT_MIGRATION_RESOURCE.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
