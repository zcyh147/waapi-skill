#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${WAAPI_TEST_PYTHON:-}" ]]; then
  if [[ ! -x "$WAAPI_TEST_PYTHON" ]]; then
    echo "TEST_ENVIRONMENT_BLOCKED: WAAPI_TEST_PYTHON is not executable: $WAAPI_TEST_PYTHON" >&2
    exit 4
  fi
  exec "$WAAPI_TEST_PYTHON" "$SCRIPT_DIR/test_driver.py" "$@"
fi
exec poetry --directory "$SCRIPT_DIR/.." run -- python "$SCRIPT_DIR/test_driver.py" "$@"
