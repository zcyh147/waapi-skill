#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ci/test.sh <version> <mode> [-- <extra pytest args...>]

Versions:
  2021.1 | 2022.1 | 2023.1 | 2024.1 | 2025.1 | all | none

Modes:
  nonlive      Run default non-live test suite
  smoke        Run focused WAAPI getInfo smoke via HeadlessLifecycle
  live         Run focused live suite for the selected version
  destructive  Run focused destructive suite for the selected version
  matrix       Run focused live + destructive sequentially (2021.1/2023.1/2024.1/2025.1)

Notes:
  - Environment overrides are respected if already set:
      WWISE_CONSOLE, WWISE_SAMPLE_PROJECT_PATH, WWISE_SANDBOX_ROOT,
      WWISE_STARTUP_TIMEOUT, WWISE_READINESS_TIMEOUT,
      WWISE_PROBE_TIMEOUT, WWISE_SHUTDOWN_TIMEOUT
  - Default sandbox root if not set:
      .sisyphus/runtime/wwise-waapi-sandboxes/<version>-<mode>

Examples:
  ci/test.sh 2021.1 live
  ci/test.sh 2025.1 destructive
  ci/test.sh all matrix
  ci/test.sh all smoke
  ci/test.sh none nonlive
  ci/test.sh 2022.1 smoke -- -q
  ci/test.sh 2024.1 live -- -k object_topics -q
EOF
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_SANDBOX_BASE="$ROOT_DIR/.sisyphus/runtime/wwise-waapi-sandboxes"

declare -a PYTEST_EXTRA_ARGS=()

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 2 ]]; then
  usage
  exit 1
fi

VERSION="$1"
MODE="$2"
shift 2

if [[ ${1:-} == "--" ]]; then
  shift
fi
if [[ $# -gt 0 ]]; then
  PYTEST_EXTRA_ARGS=("$@")
fi

resolve_version_paths() {
  local v="$1"
  case "$v" in
    2021.1)
      RESOLVED_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh"
      RESOLVED_PROJECT="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj"
      ;;
    2022.1)
      RESOLVED_CONSOLE="/Applications/Audiokinetic/Wwise2022.1.19.8584/Wwise.app/Contents/Tools/WwiseConsole.sh"
      RESOLVED_PROJECT="/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject/SampleProject.wproj"
      ;;
    2023.1)
      RESOLVED_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh"
      RESOLVED_PROJECT="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj"
      ;;
    2024.1)
      RESOLVED_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh"
      RESOLVED_PROJECT="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj"
      ;;
    2025.1)
      RESOLVED_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh"
      RESOLVED_PROJECT="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj"
      ;;
    *)
      echo "Unsupported version: $v" >&2
      exit 1
      ;;
  esac
}

set_version_environment() {
  local v="$1"
  local m="$2"
  resolve_version_paths "$v"

  export WWISE_VERSION="$v"
  export WWISE_CONSOLE="${WWISE_CONSOLE:-$RESOLVED_CONSOLE}"
  export WWISE_SAMPLE_PROJECT_PATH="${WWISE_SAMPLE_PROJECT_PATH:-$RESOLVED_PROJECT}"
  export WWISE_SANDBOX_ROOT="${WWISE_SANDBOX_ROOT:-$DEFAULT_SANDBOX_BASE/${v}-${m}}"
}

print_context() {
  local v="$1"
  local m="$2"
  echo "== Test Context =="
  echo "version:      $v"
  echo "mode:         $m"
  echo "console:      ${WWISE_CONSOLE:-<unset>}"
  echo "project:      ${WWISE_SAMPLE_PROJECT_PATH:-<unset>}"
  echo "sandbox_root: ${WWISE_SANDBOX_ROOT:-<unset>}"
  echo "pytest args:  ${PYTEST_EXTRA_ARGS[*]:-<none>}"
  echo
}

set_mode_flags() {
  local m="$1"
  export WWISE_LIVE="${WWISE_LIVE:-0}"
  export WWISE_DESTRUCTIVE="${WWISE_DESTRUCTIVE:-0}"

  case "$m" in
    live)
      export WWISE_LIVE="1"
      export WWISE_DESTRUCTIVE="0"
      ;;
    destructive)
      export WWISE_LIVE="1"
      export WWISE_DESTRUCTIVE="1"
      ;;
    smoke)
      export WWISE_LIVE="1"
      export WWISE_DESTRUCTIVE="0"
      ;;
    nonlive|default)
      export WWISE_LIVE="0"
      export WWISE_DESTRUCTIVE="0"
      ;;
  esac
}

run_pytest() {
  local -a args=("$@")
  (
    cd "$ROOT_DIR"
    python -m pytest "${args[@]}" "${PYTEST_EXTRA_ARGS[@]}"
  )
}

run_nonlive() {
  set_mode_flags "nonlive"
  print_context "none" "nonlive"
  run_pytest -m "not live and not destructive"
}

run_smoke_for_version() {
  local v="$1"
  set_version_environment "$v" "smoke"
  set_mode_flags "smoke"
  print_context "$v" "smoke"
  (
    cd "$ROOT_DIR"
    python - <<'PY'
import os

from wwise_waapi.headless import HeadlessLifecycle, LifecycleTimeouts, default_waapi_client_factory

console_path = os.environ["WWISE_CONSOLE"]
project_path = os.environ["WWISE_SAMPLE_PROJECT_PATH"]
timeouts = LifecycleTimeouts(
    startup=float(os.getenv("WWISE_STARTUP_TIMEOUT", "10")),
    readiness=float(os.getenv("WWISE_READINESS_TIMEOUT", "60")),
    probe=float(os.getenv("WWISE_PROBE_TIMEOUT", "5")),
    shutdown=float(os.getenv("WWISE_SHUTDOWN_TIMEOUT", "10")),
)

lifecycle = HeadlessLifecycle(
    console_path=console_path,
    project_path=project_path,
    timeouts=timeouts,
)
client = None
try:
    lifecycle.run_until_ready()
    client = default_waapi_client_factory(lifecycle.waapi_url)
    info = client.call("ak.wwise.core.getInfo")
    display_name = info.get("displayName") if isinstance(info, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    print(f"smoke ok: displayName={display_name!r} version={version!r}")
finally:
    if client is not None:
        client.disconnect()
    lifecycle.shutdown(suppress_errors=True)
PY
  )
}

run_live_for_version() {
  local v="$1"
  set_version_environment "$v" "live"
  set_mode_flags "live"
  print_context "$v" "live"

  case "$v" in
    2021.1)
      run_pytest \
        tests/live/test_2021_1_live_prerequisites.py \
        tests/live/test_2021_1_reflection_prerequisites.py \
        tests/live/test_2021_1_object_get_matrix.py \
        tests/live/test_2021_1_object_topics_sandbox.py
      ;;
    2022.1)
      echo "Focused live matrix is not defined for 2022.1; use smoke mode for this version." >&2
      exit 1
      ;;
    2023.1)
      run_pytest \
        tests/live/test_2023_live_prerequisites.py \
        tests/live/test_2023_reflection_inventory.py \
        tests/live/test_2023_waql_live_matrix.py
      ;;
    2024.1)
      run_pytest \
        tests/live/test_2024_live_prerequisites.py \
        tests/live/test_2024_reflection_inventory.py \
        tests/live/test_2024_waql_live_matrix.py \
        tests/live/test_2024_object_topics_sandbox.py
      ;;
    2025.1)
      run_pytest \
        tests/live/test_2025_1_live_prerequisites.py \
        tests/live/test_2025_1_reflection_inventory.py \
        tests/live/test_2025_1_waql_live_matrix.py \
        tests/live/test_2025_1_object_topics_sandbox.py
      ;;
    *)
      echo "Unsupported live version: $v" >&2
      exit 1
      ;;
  esac
}

run_destructive_for_version() {
  local v="$1"
  set_version_environment "$v" "destructive"
  set_mode_flags "destructive"
  print_context "$v" "destructive"

  case "$v" in
    2021.1)
      run_pytest \
        tests/destructive/test_2021_1_project_mutation_sandbox.py \
        tests/destructive/test_2021_1_soundbank_audio_sandbox.py \
        tests/destructive/test_2021_1_switchcontainer_assignment_sandbox.py
      ;;
    2022.1)
      echo "Focused destructive matrix is not defined for 2022.1; use smoke mode for this version." >&2
      exit 1
      ;;
    2023.1)
      run_pytest \
        tests/destructive/test_2023_project_mutation_sandbox.py \
        tests/destructive/test_2023_soundbank_audio_sandbox.py \
        tests/destructive/test_2023_switchcontainer_assignment_sandbox.py
      ;;
    2024.1)
      run_pytest \
        tests/destructive/test_2024_project_mutation_sandbox.py \
        tests/destructive/test_2024_soundbank_audio_sandbox.py \
        tests/destructive/test_2024_switchcontainer_assignment_sandbox.py
      ;;
    2025.1)
      run_pytest \
        tests/destructive/test_2025_1_project_mutation_sandbox.py \
        tests/destructive/test_2025_1_soundbank_audio_sandbox.py \
        tests/destructive/test_2025_1_switchcontainer_assignment_sandbox.py
      ;;
    *)
      echo "Unsupported destructive version: $v" >&2
      exit 1
      ;;
  esac
}

run_matrix_all() {
  local versions=(2021.1 2023.1 2024.1 2025.1)
  local v
  for v in "${versions[@]}"; do
    run_live_for_version "$v"
    run_destructive_for_version "$v"
  done
}

case "$MODE" in
  nonlive|default)
    run_nonlive
    ;;
  smoke)
    if [[ "$VERSION" == "all" ]]; then
      for v in 2021.1 2022.1 2023.1 2024.1 2025.1; do
        run_smoke_for_version "$v"
      done
    else
      run_smoke_for_version "$VERSION"
    fi
    ;;
  live)
    if [[ "$VERSION" == "all" ]]; then
      for v in 2021.1 2023.1 2024.1 2025.1; do
        run_live_for_version "$v"
      done
    else
      run_live_for_version "$VERSION"
    fi
    ;;
  destructive)
    if [[ "$VERSION" == "all" ]]; then
      for v in 2021.1 2023.1 2024.1 2025.1; do
        run_destructive_for_version "$v"
      done
    else
      run_destructive_for_version "$VERSION"
    fi
    ;;
  matrix|focused)
    if [[ "$VERSION" != "all" ]]; then
      echo "matrix/focused mode requires version 'all'" >&2
      exit 1
    fi
    run_matrix_all
    ;;
  *)
    echo "Unsupported mode: $MODE" >&2
    usage
    exit 1
    ;;
esac
