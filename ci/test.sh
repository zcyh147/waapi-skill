#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ci/test.sh --version <version> --mode <mode> [-- <extra pytest args...>]
  ci/test.sh -v <version> -m <mode> [-- <extra pytest args...>]
  ci/test.sh <version> <mode> [-- <extra pytest args...>]  # backwards compatible

Versions:
  2021.1 | 2022.1 | 2023.1 | 2024.1 | 2025.1 | all | none

Modes:
  nonlive      Run default non-live test suite
  all          Run non-live suite first, then strict real matrix
  smoke        Run focused WAAPI getInfo smoke via HeadlessLifecycle
  live         Run focused live suite for the selected version
  destructive  Run focused destructive suite for the selected version
  matrix       Run focused live + destructive sequentially (2021.1/2022.1/2023.1/2024.1/2025.1)

Notes:
  - Environment overrides are respected if already set:
      WWISE_CONSOLE, WWISE_SAMPLE_PROJECT_PATH, WWISE_SANDBOX_ROOT,
      WWISE_STARTUP_TIMEOUT, WWISE_READINESS_TIMEOUT,
      WWISE_PROBE_TIMEOUT, WWISE_SHUTDOWN_TIMEOUT
  - Default sandbox root if not set:
      .sisyphus/runtime/wwise-waapi-sandboxes/<version>-<mode>

Examples:
  ci/test.sh --version 2021.1 --mode live
  ci/test.sh --mode nonlive
  ci/test.sh --version all --mode all -- -q -ra
  ci/test.sh -v all -m matrix
  ci/test.sh --version 2024.1 --mode live -- -k object_topics -q
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
SKILL_DIR="$ROOT_DIR/skills/waapi-skill"
DEFAULT_SANDBOX_BASE="$ROOT_DIR/.sisyphus/runtime/wwise-waapi-sandboxes"
export PYTHONPATH="$SKILL_DIR${PYTHONPATH:+:$PYTHONPATH}"

INITIAL_WWISE_CONSOLE=""
INITIAL_WWISE_SAMPLE_PROJECT_PATH=""
INITIAL_WWISE_SANDBOX_ROOT=""
HAS_INITIAL_WWISE_CONSOLE="0"
HAS_INITIAL_WWISE_SAMPLE_PROJECT_PATH="0"
HAS_INITIAL_WWISE_SANDBOX_ROOT="0"

if [[ -n "${WWISE_CONSOLE+x}" ]]; then
  INITIAL_WWISE_CONSOLE="$WWISE_CONSOLE"
  HAS_INITIAL_WWISE_CONSOLE="1"
fi
if [[ -n "${WWISE_SAMPLE_PROJECT_PATH+x}" ]]; then
  INITIAL_WWISE_SAMPLE_PROJECT_PATH="$WWISE_SAMPLE_PROJECT_PATH"
  HAS_INITIAL_WWISE_SAMPLE_PROJECT_PATH="1"
fi
if [[ -n "${WWISE_SANDBOX_ROOT+x}" ]]; then
  INITIAL_WWISE_SANDBOX_ROOT="$WWISE_SANDBOX_ROOT"
  HAS_INITIAL_WWISE_SANDBOX_ROOT="1"
fi

declare -a PYTEST_EXTRA_ARGS=()
declare -a POSITIONAL_ARGS=()

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi

VERSION=""
MODE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -v|--version)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        usage
        exit 1
      fi
      VERSION="$2"
      shift 2
      ;;
    -m|--mode)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        usage
        exit 1
      fi
      MODE="$2"
      shift 2
      ;;
    --)
      shift
      if [[ $# -gt 0 ]]; then
        PYTEST_EXTRA_ARGS=("$@")
      fi
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
    *)
      POSITIONAL_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$VERSION" && ${#POSITIONAL_ARGS[@]} -ge 1 ]]; then
  VERSION="${POSITIONAL_ARGS[0]}"
fi
if [[ -z "$MODE" && ${#POSITIONAL_ARGS[@]} -ge 2 ]]; then
  MODE="${POSITIONAL_ARGS[1]}"
fi

if [[ -z "$MODE" ]]; then
  echo "Mode is required (use --mode or positional form)." >&2
  usage
  exit 1
fi

case "$MODE" in
  nonlive|default)
    VERSION="${VERSION:-none}"
    ;;
  all)
    VERSION="${VERSION:-all}"
    ;;
  matrix|focused)
    VERSION="${VERSION:-all}"
    ;;
  *)
    if [[ -z "$VERSION" ]]; then
      echo "Version is required for mode '$MODE' (use --version or positional form)." >&2
      usage
      exit 1
    fi
    ;;
esac

resolve_version_paths() {
  local v="$1"
  case "$v" in
    2021.1)
      RESOLVED_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh"
      RESOLVED_PROJECT="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj"
      ;;
    2022.1)
      RESOLVED_CONSOLE="/Applications/Audiokinetic/Wwise2022.1.19.8584/Wwise.app/Contents/Tools/WwiseConsole.sh"
      RESOLVED_PROJECT="$ROOT_DIR/tests/_org/2022.1/SampleProject.wproj"
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
  if [[ "$HAS_INITIAL_WWISE_CONSOLE" == "1" ]]; then
    export WWISE_CONSOLE="$INITIAL_WWISE_CONSOLE"
  else
    export WWISE_CONSOLE="$RESOLVED_CONSOLE"
  fi

  if [[ "$HAS_INITIAL_WWISE_SAMPLE_PROJECT_PATH" == "1" ]]; then
    export WWISE_SAMPLE_PROJECT_PATH="$INITIAL_WWISE_SAMPLE_PROJECT_PATH"
  else
    export WWISE_SAMPLE_PROJECT_PATH="$RESOLVED_PROJECT"
  fi

  if [[ "$HAS_INITIAL_WWISE_SANDBOX_ROOT" == "1" ]]; then
    export WWISE_SANDBOX_ROOT="$INITIAL_WWISE_SANDBOX_ROOT"
  else
    export WWISE_SANDBOX_ROOT="$DEFAULT_SANDBOX_BASE/${v}-${m}"
  fi
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
      export WWISE_STRICT_REAL="1"
      ;;
    destructive)
      export WWISE_LIVE="1"
      export WWISE_DESTRUCTIVE="1"
      export WWISE_STRICT_REAL="1"
      ;;
    smoke)
      export WWISE_LIVE="1"
      export WWISE_DESTRUCTIVE="0"
      export WWISE_STRICT_REAL="1"
      ;;
    nonlive|default)
      export WWISE_LIVE="0"
      export WWISE_DESTRUCTIVE="0"
      export WWISE_STRICT_REAL="0"
      ;;
  esac
}

require_real_prerequisites() {
  local v="$1"
  local m="$2"
  if [[ "${WWISE_STRICT_REAL:-0}" != "1" ]]; then
    return 0
  fi
  if [[ -z "${WWISE_CONSOLE:-}" ]]; then
    echo "Strict real $m for $v requires WWISE_CONSOLE to be set" >&2
    exit 1
  fi
  if [[ ! -f "$WWISE_CONSOLE" || ! -x "$WWISE_CONSOLE" ]]; then
    echo "Strict real $m for $v requires executable WWISE_CONSOLE: $WWISE_CONSOLE" >&2
    exit 1
  fi
  if [[ -z "${WWISE_SAMPLE_PROJECT_PATH:-}" ]]; then
    echo "Strict real $m for $v requires WWISE_SAMPLE_PROJECT_PATH to be set" >&2
    exit 1
  fi
  if [[ ! -f "$WWISE_SAMPLE_PROJECT_PATH" || "$WWISE_SAMPLE_PROJECT_PATH" != *.wproj ]]; then
    echo "Strict real $m for $v requires an existing .wproj WWISE_SAMPLE_PROJECT_PATH: $WWISE_SAMPLE_PROJECT_PATH" >&2
    exit 1
  fi
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
  require_real_prerequisites "$v" "smoke"
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
  require_real_prerequisites "$v" "live"
  print_context "$v" "live"

  case "$v" in
    2021.1)
      run_pytest \
        tests/live/test_2021_1_live_prerequisites.py::test_2021_1_live_read_only_prerequisites_validate_exact_get_info_before_matrix \
        tests/live/test_2021_1_reflection_prerequisites.py::test_2021_1_live_reflection_prerequisites_and_resource_generation \
        tests/live/test_2021_1_object_get_matrix.py::test_2021_1_live_waql_object_get_matrix_runs_read_only_against_sandbox \
        tests/live/test_2021_1_object_topics_sandbox.py::test_2021_1_live_safe_object_topics_against_sandbox
      ;;
    2022.1)
      run_pytest \
        tests/live/test_2022_live_prerequisites.py::test_2022_live_environment_prerequisites_fail_fast \
        tests/live/test_2022_reflection_inventory.py::test_2022_live_reflection_inventory_runs_against_sandbox \
        tests/live/test_2022_waql_live_matrix.py::test_2022_live_waql_object_get_matrix_runs_read_only_against_sandbox
      ;;
    2023.1)
      run_pytest \
        tests/live/test_2023_reflection_inventory.py::test_2023_live_reflection_inventory_runs_against_sandbox \
        tests/live/test_2023_waql_live_matrix.py::test_2023_live_waql_object_get_matrix_runs_read_only_against_sandbox
      ;;
    2024.1)
      run_pytest \
        tests/live/test_2024_reflection_inventory.py::test_2024_live_reflection_inventory_runs_against_sandbox \
        tests/live/test_2024_waql_live_matrix.py::test_2024_live_waql_object_get_matrix_runs_read_only_against_sandbox \
        tests/live/test_2024_object_topics_sandbox.py::test_2024_1_live_safe_object_topics_against_sandbox
      ;;
    2025.1)
      run_pytest \
        tests/live/test_2025_1_reflection_inventory.py::test_2025_live_reflection_inventory_runs_against_sandbox \
        tests/live/test_2025_1_waql_live_matrix.py::test_2025_live_waql_object_get_matrix_runs_read_only_against_sandbox \
        tests/live/test_2025_1_object_topics_sandbox.py::test_2025_1_live_safe_object_topics_against_sandbox
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
  require_real_prerequisites "$v" "destructive"
  print_context "$v" "destructive"

  case "$v" in
    2021.1)
      run_pytest \
        tests/destructive/test_2021_1_project_mutation_sandbox.py \
        tests/destructive/test_2021_1_soundbank_audio_sandbox.py \
        tests/destructive/test_2021_1_switchcontainer_assignment_sandbox.py
      ;;
    2022.1)
      run_pytest \
        tests/destructive/test_2022_project_mutation_sandbox.py \
        tests/destructive/test_2022_soundbank_audio_sandbox.py \
        tests/destructive/test_2022_switchcontainer_assignment_sandbox.py
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
  local versions=(2021.1 2022.1 2023.1 2024.1 2025.1)
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
  all)
    if [[ "$VERSION" != "all" ]]; then
      echo "all mode requires version 'all'" >&2
      exit 1
    fi
    run_nonlive
    run_matrix_all
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
      for v in 2021.1 2022.1 2023.1 2024.1 2025.1; do
        run_live_for_version "$v"
      done
    else
      run_live_for_version "$VERSION"
    fi
    ;;
  destructive)
    if [[ "$VERSION" == "all" ]]; then
      for v in 2021.1 2022.1 2023.1 2024.1 2025.1; do
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
