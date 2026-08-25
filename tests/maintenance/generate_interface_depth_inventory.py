"""Regenerate the reviewed exhaustive interface-depth inventory."""

from __future__ import annotations

import argparse
import json

from tests.maintenance.interface_depth_inventory import (
    INVENTORY_DOC_PATH,
    INVENTORY_PATH,
    build_interface_depth_inventory,
    render_interface_depth_inventory,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    inventory = build_interface_depth_inventory()
    expected = json.dumps(
        inventory,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if args.check:
        if not INVENTORY_PATH.is_file():
            raise SystemExit("interface-depth inventory is missing")
        if INVENTORY_PATH.read_text(encoding="utf-8") != expected:
            raise SystemExit("interface-depth inventory is stale")
        if not INVENTORY_DOC_PATH.is_file():
            raise SystemExit("interface-depth report is missing")
        if INVENTORY_DOC_PATH.read_text(encoding="utf-8") != render_interface_depth_inventory(inventory):
            raise SystemExit("interface-depth report is stale")
        return 0
    INVENTORY_PATH.write_text(expected, encoding="utf-8")
    INVENTORY_DOC_PATH.write_text(
        render_interface_depth_inventory(inventory), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
