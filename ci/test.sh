#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec poetry --directory "$SCRIPT_DIR/.." run -- python "$SCRIPT_DIR/test_driver.py" "$@"
