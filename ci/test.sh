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
  program      Run the focused pure-program public-route and transaction contract gate
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
      .waapi-skill-state/runtime/wwise-waapi-sandboxes/<version>-<mode>

Examples:
  ci/test.sh --mode program
  ci/test.sh --mode program -- -q -ra
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
DEFAULT_SANDBOX_BASE="$ROOT_DIR/.waapi-skill-state/runtime/wwise-waapi-sandboxes"
export PYTHONPATH="$SKILL_DIR${PYTHONPATH:+:$PYTHONPATH}"

INITIAL_WWISE_CONSOLE=""
INITIAL_WWISE_SAMPLE_PROJECT_PATH=""
INITIAL_WWISE_SANDBOX_ROOT=""
INITIAL_WWISE_TEST_CONFIG=""
RESOLVED_TEST_CONFIG=""
HAS_INITIAL_WWISE_CONSOLE="0"
HAS_INITIAL_WWISE_SAMPLE_PROJECT_PATH="0"
HAS_INITIAL_WWISE_SANDBOX_ROOT="0"
HAS_INITIAL_WWISE_TEST_CONFIG="0"

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
if [[ -n "${WWISE_TEST_CONFIG+x}" ]]; then
  INITIAL_WWISE_TEST_CONFIG="$WWISE_TEST_CONFIG"
  HAS_INITIAL_WWISE_TEST_CONFIG="1"
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
  program|nonlive|default)
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
  RESOLVED_SANDBOX=""
  RESOLVED_TEST_CONFIG=""
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
  load_version_config_paths "$v"
}

load_version_config_paths() {
  local v="$1"
  local config_path="${INITIAL_WWISE_TEST_CONFIG:-${WWISE_TEST_CONFIG:-$ROOT_DIR/tests/fixtures/local/live-environment.json}}"
  if [[ ! -f "$config_path" ]]; then
    return 0
  fi
  RESOLVED_TEST_CONFIG="$config_path"
  while IFS='=' read -r key value; do
    case "$key" in
      WWISE_CONSOLE) RESOLVED_CONSOLE="$value" ;;
      WWISE_SAMPLE_PROJECT_PATH) RESOLVED_PROJECT="$value" ;;
      WWISE_SANDBOX_ROOT) RESOLVED_SANDBOX="$value" ;;
    esac
  done < <(python3 - "$config_path" "$v" "$ROOT_DIR" <<'PYCONFIG'
from __future__ import annotations
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1]).expanduser().resolve(strict=False)
version = sys.argv[2]
repo_root = Path(sys.argv[3]).resolve(strict=False)
payload = json.loads(config_path.read_text(encoding="utf-8"))
entry = payload.get("versions", {}).get(version, {}) if isinstance(payload, dict) else {}
if not isinstance(entry, dict):
    entry = {}

def path_value(*keys: str) -> str | None:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = repo_root / path
            return str(path.resolve(strict=False))
    return None

values = {
    "WWISE_CONSOLE": path_value("wwise_console", "console_path"),
    "WWISE_SAMPLE_PROJECT_PATH": path_value("sample_project", "sample_project_path"),
    "WWISE_SANDBOX_ROOT": path_value("sandbox_root"),
}
for key, value in values.items():
    if value is not None:
        print(f"{key}={value}")
PYCONFIG
  )
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
  elif [[ -n "$RESOLVED_SANDBOX" ]]; then
    export WWISE_SANDBOX_ROOT="$RESOLVED_SANDBOX"
  else
    export WWISE_SANDBOX_ROOT="$DEFAULT_SANDBOX_BASE/${v}-${m}"
  fi
  if [[ "$HAS_INITIAL_WWISE_TEST_CONFIG" == "1" ]]; then
    export WWISE_TEST_CONFIG="$INITIAL_WWISE_TEST_CONFIG"
  elif [[ -n "$RESOLVED_TEST_CONFIG" ]]; then
    export WWISE_TEST_CONFIG="$RESOLVED_TEST_CONFIG"
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
    program|nonlive|default)
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
    if [[ ${#PYTEST_EXTRA_ARGS[@]} -gt 0 ]]; then
      python -m pytest "${args[@]}" "${PYTEST_EXTRA_ARGS[@]}"
    else
      python -m pytest "${args[@]}"
    fi
  )
}

run_nonlive() {
  set_mode_flags "nonlive"
  print_context "none" "nonlive"
  run_pytest -m "not live and not destructive"
}

validate_program_pytest_args() {
  local expects_value="0"
  local argument
  for argument in "${PYTEST_EXTRA_ARGS[@]}"; do
    if [[ "$expects_value" == "1" ]]; then
      expects_value="0"
      continue
    fi
    case "$argument" in
      -k|--maxfail|--tb|--color|--durations|--capture)
        expects_value="1"
        ;;
      --pyargs|--pyargs=*)
        echo "program mode does not allow --pyargs: $argument" >&2
        exit 1
        ;;
      -*) ;;
      *)
        echo "program mode accepts pytest flags and filter values, not additional test paths: $argument" >&2
        exit 1
        ;;
    esac
  done
  if [[ "$expects_value" == "1" ]]; then
    echo "program mode received a pytest option without its required value" >&2
    exit 1
  fi
}

run_program() {
  set_mode_flags "program"
  unset WWISE_CONSOLE WWISE_SAMPLE_PROJECT_PATH WWISE_SANDBOX_ROOT WWISE_TEST_CONFIG
  unset WWISE_WAAPI_HOST WWISE_WAAPI_PORT
  export PYTEST_ADDOPTS=""
  print_context "none" "program"
  validate_program_pytest_args

  local -a program_nodes=(
    tests/unit/test_gateway_session_context.py
    tests/unit/test_public_route_coverage_contract.py
    tests/unit/test_public_route_program_matrix.py
    tests/unit/test_stable_read_adapters.py
    tests/unit/test_cli_request_templates.py
    tests/unit/test_debug_read_gateway.py
    tests/unit/test_debug_lua_operations.py
    tests/unit/test_debug_lua_gateway_full_chain.py
    tests/unit/test_public_route_negative_contracts.py
    tests/unit/test_subscriptions.py
    tests/unit/test_dispatcher.py::test_topic_dispatch_accepts_unbounded_timeout
    tests/unit/test_dispatcher.py::test_topic_dispatch_rejects_other_non_finite_timeouts
    tests/unit/test_dispatcher.py::test_topic_cleanup_failure_does_not_swallow_keyboard_interrupt
    tests/unit/test_waapi_gateway.py::test_ordinary_wait_topic_honors_explicit_long_timeout_without_contract_cap
    tests/unit/test_waapi_gateway.py::test_ordinary_wait_topic_reports_default_ten_second_budget
    tests/unit/test_waapi_gateway.py::test_wait_topic_no_timeout_returns_strict_bounded_json
    tests/unit/test_waapi_gateway.py::test_wait_topic_rejects_ambiguous_or_implicit_unbounded_timeout_before_connecting
    tests/unit/test_waapi_gateway.py::test_wait_topic_keyboard_interrupt_closes_transport_subscription
    tests/unit/test_waapi_gateway.py::test_wait_topic_no_timeout_keeps_transport_connect_finitely_bounded
    tests/unit/test_script_helpers.py::test_run_main_returns_standard_interrupt_code_without_wrapper_traceback
    tests/unit/test_io_policy.py
    tests/unit/test_transaction_locality.py
    tests/unit/test_platform_paths.py
    tests/unit/test_transaction_cleanup.py
    tests/unit/test_operation_import.py
    tests/unit/test_operation_object.py
    tests/unit/test_operation_plugin.py
    tests/unit/test_operation_plugin_registry.py
    tests/unit/test_operation_platform_rtpc.py
    tests/unit/test_authoring_ui_commands_collector.py
    tests/unit/test_authoring_ui_commands_manifest.py
    tests/unit/test_authoring_ui_profile.py
    tests/unit/test_operation_ui_commands.py
    tests/unit/test_operation_ui_commands_registry.py
    tests/unit/test_authoring_ui_gateway.py
    tests/unit/test_operation_soundbank.py
    tests/unit/test_operation_registry.py
    tests/unit/test_operation_registry_import_verifier.py
    tests/unit/test_operation_registry_soundbank.py
    tests/unit/test_object_create_replace.py
    tests/unit/test_object_reference_activation.py
    tests/unit/test_object_set_merge.py
    tests/unit/test_operation_soundbank_version_matrix.py
    tests/unit/test_skill_contract_protocol.py
    tests/unit/test_transaction_gateway.py::test_preview_apply_read_only_blocks_before_connection_or_state_write
    tests/unit/test_transaction_gateway.py::test_preview_apply_rejects_transaction_read_without_persisting_a_transaction
    tests/unit/test_transaction_gateway.py::test_read_only_allows_explicitly_confirmed_sealed_read_transaction
    tests/unit/test_transaction_gateway.py::test_preview_apply_ask_before_changes_still_requires_show_token_and_confirm
    tests/unit/test_transaction_gateway.py::test_preview_apply_allow_changes_records_policy_authority_without_confirmation
    tests/unit/test_transaction_gateway.py::test_policy_authorized_allow_changes_executes_once_and_can_verify
    tests/unit/test_transaction_gateway.py::test_policy_authorized_allow_to_ask_drift_requires_repreview_without_business_dispatch
    tests/unit/test_transaction_gateway.py::test_policy_authorized_allow_to_read_only_drift_blocks_before_connection
    tests/unit/test_transaction_gateway.py::test_preview_without_apply_stays_review_only_under_allow_changes
    tests/unit/test_transaction_gateway.py::test_allow_changes_keeps_dangerous_host_control_on_confirmation_path
    tests/unit/test_transaction_gateway.py::test_operation_schema_owns_exact_audio_convert_fast_route_contract
    tests/unit/test_transaction_gateway.py::test_generic_manifest_call_runs_full_preview_confirm_execute_verify_chain
    tests/unit/test_transaction_gateway.py::test_object_create_plugin_runs_full_preview_confirm_execute_verify_chain
    tests/unit/test_transaction_gateway.py::test_generic_isolated_call_runs_full_chain_with_bound_io_audit
    tests/unit/test_transaction_gateway.py::test_remote_local_filesystem_previews_fail_before_project_or_path_proof
    tests/unit/test_transaction_gateway.py::test_confirmed_generic_isolated_transaction_stays_confirmed_on_remote_execute
    tests/unit/test_transaction_gateway.py::test_confirmed_named_soundbank_transaction_stays_confirmed_on_remote_execute
    tests/unit/test_transaction_gateway.py::test_remote_named_capture_screen_is_not_a_locality_transaction
    tests/unit/test_transaction_gateway.py::test_debug_test_crash_is_confirmed_dispatched_once_and_terminal_indeterminate
    tests/unit/test_transaction_gateway.py::test_local_wine_cli_execute_translates_only_the_transient_dispatch_paths
    tests/unit/test_transaction_gateway.py::test_local_wine_cli_mapping_failure_requires_repreview_before_execution_start
    tests/unit/test_transaction_gateway.py::test_generate_soundbank_verify_uses_sealed_result_context_and_runtime_without_project_probe
    tests/unit/test_transaction_gateway.py::test_tab_delimited_import_verify_uses_sealed_result_context_and_runtime_without_project_probe
    tests/unit/test_transaction_gateway.py::test_additional_reviewed_explicit_project_cli_calls_verify_without_project_probe
    tests/unit/test_transaction_gateway.py::test_generate_soundbank_preview_requires_strong_get_info_process_identity
    tests/unit/test_transaction_gateway.py::test_generate_soundbank_verify_rejects_same_version_process_identity_drift_without_project_probe
    tests/unit/test_transaction_gateway.py::test_generate_soundbank_verify_rejects_endpoint_drift_without_project_probe
    tests/unit/test_transaction_gateway.py::test_generate_soundbank_verify_rejects_runtime_drift_without_project_probe
    tests/unit/test_transaction_gateway.py::test_lifecycle_opener_cleanup_spec_survives_the_full_gateway_chain
    tests/unit/test_transaction_gateway.py::test_load_bank_cleanup_binding_cannot_be_overridden_by_execution_result
    tests/unit/test_transaction_gateway.py::test_transport_create_materializes_destroy_request_in_execute_verify_and_agent_result
    tests/unit/test_transaction_gateway.py::test_transport_verify_guard_failure_keeps_result_bound_destroy_request
    tests/unit/test_transaction_gateway.py::test_successful_mutation_with_journal_failure_keeps_execution_and_cleanup_facts
    tests/unit/test_transaction_gateway.py::test_transaction_readback_rejects_an_unreviewed_uri_before_dispatch
    tests/unit/test_transaction_gateway.py::test_lifecycle_opener_execution_exception_reports_unknown_cleanup
    tests/unit/test_transaction_gateway.py::test_work_unit_load_is_available_reversal_through_the_full_gateway_chain
    tests/unit/test_transaction_gateway.py::test_lifecycle_closer_is_not_reported_as_needing_more_cleanup
    tests/unit/test_transaction_gateway.py::test_undo_group_success_uses_one_client_and_verifies_only_result_schemas
    tests/unit/test_transaction_gateway.py::test_undo_group_success_keeps_one_phase_copy_below_the_final_gateway_ceiling
    tests/unit/test_transaction_gateway.py::test_undo_group_success_with_journal_failure_is_not_replayed
    tests/unit/test_transaction_gateway.py::test_undo_group_inner_timeout_reserves_budget_cancels_and_never_retries
    tests/unit/test_transaction_gateway.py::test_undo_group_cancel_failure_is_terminal_indeterminate
    tests/unit/test_transaction_gateway.py::test_undo_group_malformed_begin_result_best_effort_cancels_but_stays_indeterminate
    tests/unit/test_transaction_gateway.py::test_undo_group_malformed_end_result_best_effort_cancels_but_stays_indeterminate
    tests/unit/test_transaction_gateway.py::test_undo_group_phase_exception_best_effort_cancels_and_remains_indeterminate
    tests/unit/test_transaction_gateway.py::test_undo_group_accumulated_result_limit_stops_inner_and_attempts_cancel
  )
  if [[ -f "$ROOT_DIR/tests/unit/test_public_route_registry_integrity.py" ]]; then
    program_nodes+=(tests/unit/test_public_route_registry_integrity.py)
  fi

  local node
  for node in "${program_nodes[@]}"; do
    case "$node" in
      tests/unit/*) ;;
      *)
        echo "program mode refused a test node outside tests/unit: $node" >&2
        exit 1
        ;;
    esac
  done

  run_pytest \
    "${program_nodes[@]}" \
    -m "not live and not destructive" \
    --ignore=tests/semantic \
    --ignore=tests/live \
    --ignore=tests/destructive
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

from tests.destructive.support.sandbox_fixture import cleanup_sandbox, prepare_sample_project_sandbox
from wwise_waapi.headless import HeadlessLifecycle, LifecycleTimeouts, default_waapi_client_factory

env = dict(os.environ)
timeouts = LifecycleTimeouts(
    startup=float(os.getenv("WWISE_STARTUP_TIMEOUT", "10")),
    readiness=float(os.getenv("WWISE_READINESS_TIMEOUT", "60")),
    probe=float(os.getenv("WWISE_PROBE_TIMEOUT", "5")),
    shutdown=float(os.getenv("WWISE_SHUTDOWN_TIMEOUT", "10")),
)

sandbox = prepare_sample_project_sandbox(env, hash_strategy="bounded")
fixed_port = os.getenv("WWISE_WAAPI_PORT")
lifecycle = HeadlessLifecycle(
    console_path=env["WWISE_CONSOLE"],
    project_path=sandbox.sandbox_project,
    port=int(fixed_port) if fixed_port else None,
    timeouts=timeouts,
    launch_env={**env, **sandbox.env},
)
client = None
failed = True
try:
    lifecycle.launch()
    print(f"smoke project: {sandbox.sandbox_project}", flush=True)
    print(f"smoke argv: {lifecycle.command!r}", flush=True)
    print(f"smoke cwd: {str(lifecycle.launch_cwd)!r}", flush=True)
    print(f"smoke waapi_url: {lifecycle.waapi_url}", flush=True)
    lifecycle.wait_ready()
    client = default_waapi_client_factory(lifecycle.waapi_url)
    info = client.call("ak.wwise.core.getInfo")
    display_name = info.get("displayName") if isinstance(info, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    print(f"smoke ok: displayName={display_name!r} version={version!r}")
    failed = False
except BaseException as exc:
    print(f"smoke failed: {type(exc).__name__}: {exc}", flush=True)
    print(f"smoke stdout_tail: {lifecycle.output.tail('stdout', 80)!r}", flush=True)
    print(f"smoke stderr_tail: {lifecycle.output.tail('stderr', 80)!r}", flush=True)
    raise
finally:
    if client is not None:
        client.disconnect()
    lifecycle.shutdown(suppress_errors=True)
    cleanup_sandbox(sandbox, failed=failed)
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
        tests/live/test_2021_1_object_topics_sandbox.py::test_2021_1_live_safe_object_topics_against_sandbox \
        tests/live/test_gateway_live_matrix.py::test_gateway_read_only_matrix_runs_once_against_copied_sandbox
      ;;
    2022.1)
      run_pytest \
        tests/live/test_2022_live_prerequisites.py::test_2022_live_environment_prerequisites_fail_fast \
        tests/live/test_2022_reflection_inventory.py::test_2022_live_reflection_inventory_runs_against_sandbox \
        tests/live/test_2022_waql_live_matrix.py::test_2022_live_waql_object_get_matrix_runs_read_only_against_sandbox \
        tests/live/test_gateway_live_matrix.py::test_gateway_read_only_matrix_runs_once_against_copied_sandbox
      ;;
    2023.1)
      run_pytest \
        tests/live/test_2023_reflection_inventory.py::test_2023_live_reflection_inventory_runs_against_sandbox \
        tests/live/test_2023_waql_live_matrix.py::test_2023_live_waql_object_get_matrix_runs_read_only_against_sandbox \
        tests/live/test_gateway_live_matrix.py::test_gateway_read_only_matrix_runs_once_against_copied_sandbox
      ;;
    2024.1)
      run_pytest \
        tests/live/test_2024_reflection_inventory.py::test_2024_live_reflection_inventory_runs_against_sandbox \
        tests/live/test_2024_waql_live_matrix.py::test_2024_live_waql_object_get_matrix_runs_read_only_against_sandbox \
        tests/live/test_2024_object_topics_sandbox.py::test_2024_1_live_safe_object_topics_against_sandbox \
        tests/live/test_gateway_live_matrix.py::test_gateway_read_only_matrix_runs_once_against_copied_sandbox
      ;;
    2025.1)
      run_pytest \
        tests/live/test_2025_1_reflection_inventory.py::test_2025_live_reflection_inventory_runs_against_sandbox \
        tests/live/test_2025_1_waql_live_matrix.py::test_2025_live_waql_object_get_matrix_runs_read_only_against_sandbox \
        tests/live/test_2025_1_object_topics_sandbox.py::test_2025_1_live_safe_object_topics_against_sandbox \
        tests/live/test_gateway_live_matrix.py::test_gateway_read_only_matrix_runs_once_against_copied_sandbox
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
        tests/destructive/test_2021_1_switchcontainer_assignment_sandbox.py \
        tests/destructive/test_gateway_transaction_matrix.py \
        tests/destructive/test_gateway_workflow_transaction_matrix.py
      ;;
    2022.1)
      run_pytest \
        tests/destructive/test_2022_project_mutation_sandbox.py \
        tests/destructive/test_2022_soundbank_audio_sandbox.py \
        tests/destructive/test_2022_switchcontainer_assignment_sandbox.py \
        tests/destructive/test_gateway_transaction_matrix.py \
        tests/destructive/test_gateway_workflow_transaction_matrix.py
      ;;
    2023.1)
      run_pytest \
        tests/destructive/test_2023_project_mutation_sandbox.py \
        tests/destructive/test_2023_soundbank_audio_sandbox.py \
        tests/destructive/test_2023_switchcontainer_assignment_sandbox.py \
        tests/destructive/test_gateway_transaction_matrix.py \
        tests/destructive/test_gateway_workflow_transaction_matrix.py
      ;;
    2024.1)
      run_pytest \
        tests/destructive/test_2024_project_mutation_sandbox.py \
        tests/destructive/test_2024_soundbank_audio_sandbox.py \
        tests/destructive/test_2024_switchcontainer_assignment_sandbox.py \
        tests/destructive/test_gateway_transaction_matrix.py \
        tests/destructive/test_gateway_workflow_transaction_matrix.py
      ;;
    2025.1)
      run_pytest \
        tests/destructive/test_2025_1_project_mutation_sandbox.py \
        tests/destructive/test_2025_1_soundbank_audio_sandbox.py \
        tests/destructive/test_2025_1_switchcontainer_assignment_sandbox.py \
        tests/destructive/test_gateway_transaction_matrix.py \
        tests/destructive/test_gateway_workflow_transaction_matrix.py
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
  program)
    if [[ "$VERSION" != "none" ]]; then
      echo "program mode is all-version and requires version 'none'" >&2
      exit 1
    fi
    run_program
    ;;
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
