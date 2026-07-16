from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]

from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    ENV_WWISE_LIVE,
    ENV_WWISE_VERSION,
    LiveEnvironmentError,
    path_is_under,
    resolve_sample_project_source,
)
from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    SandboxFixtureError,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from tests.support.active_gate_failures import (  # pyright: ignore[reportMissingImports]
    skip_or_fail_strict_real,
    skip_or_fail_unavailable,
)
from wwise_waapi.headless import HeadlessLifecycleError  # pyright: ignore[reportMissingImports]
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = REPO_ROOT / "skills" / "waapi-skill" / "scripts" / "gateway.py"
EVIDENCE_ROOT = REPO_ROOT / ".waapi-skill-state" / "evidence" / "waapi-gateway-live-matrix"
GATEWAY_CONTRACT = "waapi-skill.gateway-result/v1"
PREFERRED_METADATA_TYPES = ("Sound", "ActorMixer", "Bus", "MusicTrack", "Event")
PREFERRED_PROPERTY_NAMES = ("Volume", "Pitch", "Lowpass", "Highpass", "InitialDelay", "MakeUpGain")
MAX_PROPERTY_INFO_ATTEMPTS = 40
EXACT_ROOT_PATHS = {
    "2021.1": r"\Actor-Mixer Hierarchy",
    "2022.1": r"\Actor-Mixer Hierarchy",
    "2023.1": r"\Actor-Mixer Hierarchy",
    "2024.1": r"\Actor-Mixer Hierarchy",
    "2025.1": r"\Containers",
}


def _load_gateway_module() -> Any:
    spec = importlib.util.spec_from_file_location("waapi_gateway_live_matrix_script", GATEWAY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATEWAY = _load_gateway_module()


@pytest.mark.live
def test_gateway_read_only_matrix_runs_once_against_copied_sandbox() -> None:
    """Exercise the fixed read gateway against one real WwiseConsole lifecycle.

    The matrix runner invokes this test once per ``WWISE_VERSION``. Every gateway
    command opens its own short-lived WAAPI client, while the copied project and
    real WwiseConsole process are deliberately shared for the whole test.

    Topic behavior is not approximated here: a meaningful topic assertion needs
    a deterministic real publisher and is kept in the dedicated topic sandbox
    tests instead of manufacturing an event in this read-only gateway matrix.
    """

    env = dict(os.environ)
    if env.get(ENV_WWISE_LIVE) != "1":
        skip_or_fail_strict_real(f"{ENV_WWISE_LIVE}=1 is required for the gateway live matrix")

    version = env.get(ENV_WWISE_VERSION)
    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        skip_or_fail_strict_real(
            f"{ENV_WWISE_VERSION} must be one of {', '.join(SUPPORTED_WWISE_VERSION_KEYS)}; got {version!r}"
        )
    assert version is not None

    sandbox = None
    lifecycle = None
    failed = True
    shutdown_failed = False
    source_hash_before = None
    source_hash_after = None
    source_mtime_before = None
    source_mtime_after = None
    matrix_result: dict[str, Any] = {}
    performance_result: dict[str, Any] = {}
    evidence_dir = EVIDENCE_ROOT / version / "dispatcher"

    try:
        with LiveSandboxLock(_safe_lock_root(env, version=version)):
            sandbox = prepare_sample_project_sandbox(env, hash_strategy="bounded")
            source_mtime_before = sandbox.source_project.stat().st_mtime
            source_hash_before = hash_project(sandbox.source_root, preferred_strategy="bounded")
            try:
                lifecycle = launch_sandboxed_wwise(sandbox, env)
                assert lifecycle.port is not None and lifecycle.port > 0
                assert str(sandbox.sandbox_project) in lifecycle.command
                assert str(sandbox.source_project) not in lifecycle.command

                common = _gateway_prefix(
                    port=lifecycle.port,
                    version=version,
                    evidence_dir=evidence_dir,
                )
                gateway_matrix_started = time.monotonic()
                command_durations: dict[str, float] = {}

                status_result, command_durations["status"] = _invoke_gateway_timed(
                    common,
                    ("status",),
                    env=env,
                )
                status = _require_gateway_success(
                    status_result,
                    command="status",
                    version=version,
                )
                _assert_status(status, version=version, port=lifecycle.port)

                buses_result, command_durations["buses"] = _invoke_gateway_timed(
                    common,
                    ("buses",),
                    env=env,
                )
                buses = _require_gateway_success(
                    buses_result,
                    command="buses",
                    version=version,
                )
                _assert_buses(buses)

                selected_result, command_durations["selected"] = _invoke_gateway_timed(
                    common,
                    ("selected",),
                    env=env,
                )
                selected = _assert_headless_selection_boundary(
                    selected_result,
                    version=version,
                )

                functions_result, command_durations["reflection_functions"] = _invoke_gateway_timed(
                    common,
                    ("call", "ak.wwise.waapi.getFunctions"),
                    env=env,
                )
                functions = _require_gateway_success(
                    functions_result,
                    command="call ak.wwise.waapi.getFunctions",
                    version=version,
                )
                _assert_reflection_functions(functions)

                topic_timeout_common = _gateway_prefix(
                    port=lifecycle.port,
                    version=version,
                    evidence_dir=evidence_dir,
                    timeout=0.5,
                )
                topic_timeout_result, command_durations["wait_topic_timeout_cleanup"] = (
                    _invoke_gateway_timed(
                        topic_timeout_common,
                        (
                            "wait-topic",
                            "ak.wwise.core.object.created",
                            "--options-json",
                            '{"return":["id"]}',
                            "--match-json",
                            '{"object":{"id":"{FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF}"}}',
                        ),
                        env=env,
                    )
                )
                topic_timeout = _assert_clean_topic_timeout(
                    topic_timeout_result,
                    version=version,
                )

                project_query = _require_gateway_success(
                    _invoke_gateway(common, ("query-object", "--type", "Project", "--take", "1"), env=env),
                    command="query-object",
                    version=version,
                )
                _assert_project_query(project_query)

                project_all_results = _require_gateway_success(
                    _invoke_gateway(
                        common,
                        ("query-object", "--type", "Project", "--all-results"),
                        env=env,
                    ),
                    command="query-object --all-results",
                    version=version,
                )
                _assert_query_preview(
                    project_all_results,
                    expected_waql="from type Project",
                    minimum_count=1,
                )
                assert project_all_results["query_bound"] == {
                    "mode": "all-results-explicit"
                }

                exact_path = EXACT_ROOT_PATHS[version]
                path_query_result, command_durations["exact_path_query"] = _invoke_gateway_timed(
                    common,
                    (
                        "query-object",
                        "--path",
                        exact_path,
                        "--return-field",
                        "id",
                        "--return-field",
                        "name",
                        "--return-field",
                        "type",
                        "--return-field",
                        "path",
                    ),
                    env=env,
                )
                path_query = _require_gateway_success(
                    path_query_result,
                    command="query-object --path",
                    version=version,
                )
                _assert_exact_path_query(path_query, expected_path=exact_path)

                root_row = path_query["objects"][0]
                root_id = str(root_row["id"])
                exact_guid_query = _require_gateway_success(
                    _invoke_gateway(
                        common,
                        (
                            "query-object",
                            "--object-id",
                            root_id,
                            "--return-field",
                            "id",
                            "--return-field",
                            "name",
                            "--return-field",
                            "type",
                            "--return-field",
                            "path",
                        ),
                        env=env,
                    ),
                    command="query-object --object-id",
                    version=version,
                )
                _assert_exact_guid_query(
                    exact_guid_query,
                    expected_id=root_id,
                    expected_path=exact_path,
                )

                missing_path_query = _require_gateway_success(
                    _invoke_gateway(
                        common,
                        (
                            "query-object",
                            "--path",
                            exact_path + r"\__WAAPI_SKILL_MISSING__",
                            "--return-field",
                            "id",
                            "--return-field",
                            "path",
                        ),
                        env=env,
                    ),
                    command="query-object --path missing",
                    version=version,
                )
                _assert_empty_exact_query(missing_path_query)

                missing_guid_query = _require_gateway_success(
                    _invoke_gateway(
                        common,
                        (
                            "query-object",
                            "--object-id",
                            "{FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF}",
                            "--return-field",
                            "id",
                        ),
                        env=env,
                    ),
                    command="query-object --object-id missing",
                    version=version,
                )
                _assert_empty_exact_query(missing_guid_query)

                project_row = project_query["objects"][0]
                project_name = str(project_row["name"])
                type_where_take = _require_gateway_success(
                    _invoke_gateway(
                        common,
                        (
                            "query-object",
                            "--type",
                            "Project",
                            "--where-json",
                            json.dumps(
                                {"field": "name", "operator": "=", "value": project_name},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            "--take",
                            "1",
                        ),
                        env=env,
                    ),
                    command="query-object --type --where-json --take",
                    version=version,
                )
                _assert_query_preview(
                    type_where_take,
                    expected_waql=f'from type Project where name = "{project_name}" take 1',
                    minimum_count=1,
                )

                search_where_take = _require_gateway_success(
                    _invoke_gateway(
                        common,
                        (
                            "query-object",
                            "--search",
                            "Default Work Unit",
                            "--where-json",
                            '{"field":"name","operator":"=","value":"Default Work Unit"}',
                            "--take",
                            "1",
                        ),
                        env=env,
                    ),
                    command="query-object --search --where-json --take",
                    version=version,
                )
                _assert_query_preview(
                    search_where_take,
                    expected_waql='from search "Default Work Unit" where name = "Default Work Unit" take 1',
                    minimum_count=1,
                )

                children_query = _require_gateway_success(
                    _invoke_gateway(
                        common,
                        (
                            "query-object",
                            "--path",
                            exact_path,
                            "--select",
                            "children",
                            "--take",
                            "1",
                        ),
                        env=env,
                    ),
                    command="query-object --select children",
                    version=version,
                )
                _assert_query_preview(
                    children_query,
                    expected_waql=f'from object "{exact_path}" select children take 1',
                    minimum_count=1,
                )
                child_row = children_query["objects"][0]
                child_id = str(child_row["id"])

                select_payloads: dict[str, Mapping[str, Any]] = {}
                for select, source_id, minimum_count in (
                    ("parent", child_id, 1),
                    ("ancestors", child_id, 1),
                    ("descendants", root_id, 1),
                    ("referencesTo", child_id, 0),
                ):
                    select_payload = _require_gateway_success(
                        _invoke_gateway(
                            common,
                            (
                                "query-object",
                                "--object-id",
                                source_id,
                                "--select",
                                select,
                                "--take",
                                "1",
                            ),
                            env=env,
                        ),
                        command=f"query-object --select {select}",
                        version=version,
                    )
                    _assert_query_preview(
                        select_payload,
                        expected_waql=f'from object "{source_id}" select {select} take 1',
                        minimum_count=minimum_count,
                    )
                    select_payloads[select] = select_payload

                query_discovery = _require_gateway_success(
                    _invoke_gateway(
                        common,
                        (
                            "query-object",
                            "--type",
                            "Query",
                            "--where-json",
                            '{"field":"name","operator":"=","value":"Sound = SFX"}',
                            "--take",
                            "1",
                        ),
                        env=env,
                    ),
                    command="query-object discover Query Editor object",
                    version=version,
                )
                _assert_query_preview(
                    query_discovery,
                    expected_waql='from type Query where name = "Sound = SFX" take 1',
                    minimum_count=1,
                )
                query_row = query_discovery["objects"][0]
                query_id = str(query_row["id"])
                query_path = str(query_row["path"])
                assert query_path.startswith("\\Queries\\")

                query_by_guid = _require_gateway_success(
                    _invoke_gateway(
                        common,
                        ("query-object", "--query", query_id, "--take", "1"),
                        env=env,
                    ),
                    command="query-object --query GUID",
                    version=version,
                )
                _assert_query_preview(
                    query_by_guid,
                    expected_waql=f'from query "{query_id}" take 1',
                    minimum_count=1,
                )
                query_by_path = _require_gateway_success(
                    _invoke_gateway(
                        common,
                        ("query-object", "--query", query_path, "--take", "1"),
                        env=env,
                    ),
                    command="query-object --query path",
                    version=version,
                )
                _assert_query_preview(
                    query_by_path,
                    expected_waql=f'from query "{query_path}" take 1',
                    minimum_count=1,
                )
                query_guid_ids = {
                    str(row["id"]).casefold() for row in query_by_guid["objects"]
                }
                query_path_ids = {
                    str(row["id"]).casefold() for row in query_by_path["objects"]
                }
                assert query_guid_ids
                assert query_guid_ids == query_path_ids

                types_result, command_durations["metadata_types"] = _invoke_gateway_timed(
                    common,
                    ("metadata", "types"),
                    env=env,
                )
                types = _require_gateway_success(
                    types_result,
                    command="metadata types",
                    version=version,
                )
                type_rows = _assert_type_metadata(types)
                property_scope = _find_live_property_scope(
                    common,
                    env=env,
                    version=version,
                    type_rows=type_rows,
                )
                performance_result = {
                    "wwise_ready_seconds": sandbox.metadata.ready_duration_seconds,
                    "gateway_matrix_seconds": round(time.monotonic() - gateway_matrix_started, 6),
                    "representative_command_seconds": command_durations,
                }
                assert isinstance(performance_result["wwise_ready_seconds"], float)
                assert performance_result["wwise_ready_seconds"] > 0
                assert performance_result["gateway_matrix_seconds"] > 0
                assert set(command_durations) == {
                    "status",
                    "buses",
                    "selected",
                    "reflection_functions",
                    "wait_topic_timeout_cleanup",
                    "exact_path_query",
                    "metadata_types",
                }
                assert all(duration > 0 for duration in command_durations.values())

                for payload in (
                    status,
                    buses,
                    selected,
                    functions,
                    project_query,
                    project_all_results,
                    path_query,
                    exact_guid_query,
                    missing_path_query,
                    missing_guid_query,
                    type_where_take,
                    search_where_take,
                    children_query,
                    *select_payloads.values(),
                    query_discovery,
                    query_by_guid,
                    query_by_path,
                    types,
                    property_scope["names"],
                    property_scope["property_info"],
                ):
                    paths = _dispatcher_evidence_paths(payload)
                    assert paths, f"gateway command {payload.get('command')!r} did not record dispatcher evidence"
                    assert all(path.exists() for path in paths)
                timeout_paths = _dispatcher_evidence_paths(topic_timeout)
                assert timeout_paths
                assert all(path.exists() for path in timeout_paths)

                assert sandbox.source_project.stat().st_mtime == source_mtime_before
                assert (
                    hash_project(sandbox.source_root, preferred_strategy="bounded").digest
                    == source_hash_before.digest
                )
                matrix_result = {
                    "status": {
                        "detected_version": status["detected_version"],
                        "is_command_line": status["is_command_line"],
                        "project_name": status["project"]["name"],
                    },
                    "buses": {
                        "count": buses["count"],
                        "possibly_truncated": buses["possibly_truncated"],
                    },
                    "selected": {
                        "status": selected["status"],
                        "count": selected["count"],
                    },
                    "reflection_functions": {
                        "count": functions["inventory"]["count"],
                        "matches_packaged": functions["inventory"]["packaged_manifest"]["matches"],
                    },
                    "topic_timeout_cleanup": {
                        "cleanup": topic_timeout["cleanup"],
                        "deadline_exhausted": topic_timeout["call"]["details"]["deadline_exhausted"],
                        "cleanup_pending": topic_timeout["call"]["details"]["cleanup_pending"],
                    },
                    "query_object": {
                        "count": project_query["count"],
                        "object": project_query["objects"][0],
                    },
                    "exact_path_query": {
                        "count": path_query["count"],
                        "object": path_query["objects"][0],
                    },
                    "query_capability_matrix": {
                        "exact_guid_count": exact_guid_query["count"],
                        "missing_path_count": missing_path_query["count"],
                        "missing_guid_count": missing_guid_query["count"],
                        "type_where_take_count": type_where_take["count"],
                        "project_all_results_count": project_all_results["count"],
                        "search_where_take_count": search_where_take["count"],
                        "children_count": children_query["count"],
                        "select_counts": {
                            select: payload["count"]
                            for select, payload in select_payloads.items()
                        },
                        "query_editor_object": {
                            "id": query_id,
                            "path": query_path,
                            "guid_result_count": query_by_guid["count"],
                            "path_result_count": query_by_path["count"],
                            "matching_result_ids": sorted(query_guid_ids),
                        },
                    },
                    "metadata": {
                        "type_count": len(type_rows),
                        "selected_type": property_scope["type_row"],
                        "selected_property": property_scope["property_name"],
                        "property_info": property_scope["property_info"]["normalized"],
                        "property_info_attempts": property_scope["attempts"],
                    },
                }
                failed = False
            finally:
                try:
                    if lifecycle is not None:
                        shutdown_sandboxed_wwise(lifecycle, sandbox)
                except BaseException:
                    shutdown_failed = True
                    raise
                finally:
                    source_mtime_after = sandbox.source_project.stat().st_mtime
                    source_hash_after = hash_project(sandbox.source_root, preferred_strategy="bounded")
                    cleanup_sandbox(sandbox, failed=failed or shutdown_failed)
    except (LiveEnvironmentError, SandboxFixtureError, HeadlessLifecycleError, OSError) as exc:
        skip_or_fail_unavailable(exc, "gateway live matrix environment blocked execution")

    assert sandbox is not None
    assert lifecycle is not None
    assert source_hash_before is not None and source_hash_after is not None
    assert source_mtime_before == source_mtime_after
    assert source_hash_before.digest == source_hash_after.digest
    assert not sandbox.sandbox_path.exists()
    assert lifecycle.cleanup_report is not None and lifecycle.cleanup_report.is_clean is True

    _write_matrix_evidence(
        version,
        {
            "status": "passed",
            "wwise_version": version,
            "gateway_contract": GATEWAY_CONTRACT,
            "single_lifecycle": True,
            "sandbox_project": str(sandbox.sandbox_project),
            "source_project": str(sandbox.source_project),
            "source_hash_before": source_hash_before.digest,
            "source_hash_after": source_hash_after.digest,
            "source_hash_strategy": source_hash_before.strategy,
            "source_mtime_before": source_mtime_before,
            "source_mtime_after": source_mtime_after,
            "process_cleanup_result": sandbox.metadata.process_cleanup_result,
            "sandbox_cleanup_result": "deleted",
            "topic_boundary": "not_run_here; requires a deterministic real publisher and is covered separately",
            "performance": performance_result,
            "matrix": matrix_result,
        },
    )


def _gateway_prefix(
    *,
    port: int,
    version: str,
    evidence_dir: Path,
    timeout: float = 10.0,
) -> tuple[str, ...]:
    return (
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--version",
        version,
        "--timeout",
        f"{timeout:g}",
        "--evidence-dir",
        str(evidence_dir),
    )


def _invoke_gateway(
    common: Sequence[str],
    command: Sequence[str],
    *,
    env: Mapping[str, str],
) -> tuple[int, dict[str, Any]]:
    exit_code, payload = GATEWAY.execute_gateway([*common, *command], env=env)
    assert isinstance(payload, dict)
    return exit_code, payload


def _invoke_gateway_timed(
    common: Sequence[str],
    command: Sequence[str],
    *,
    env: Mapping[str, str],
) -> tuple[tuple[int, dict[str, Any]], float]:
    started = time.monotonic()
    result = _invoke_gateway(common, command, env=env)
    return result, round(time.monotonic() - started, 6)


def _require_gateway_success(
    result: tuple[int, dict[str, Any]],
    *,
    command: str,
    version: str,
) -> dict[str, Any]:
    exit_code, payload = result
    assert exit_code == 0, f"gateway {command} failed: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    assert payload.get("contract") == GATEWAY_CONTRACT
    assert payload.get("ok") is True
    assert payload.get("status") == "ok"
    assert payload.get("detected_version") == version
    return payload


def _assert_status(payload: Mapping[str, Any], *, version: str, port: int) -> None:
    assert payload["command"] == "status"
    assert payload["endpoint"]["host"] == "127.0.0.1"
    assert payload["endpoint"]["port"] == port
    assert payload["detected_version"] == version
    assert payload["is_command_line"] is True
    assert isinstance(payload.get("wwise"), Mapping)
    project = payload.get("project")
    assert isinstance(project, Mapping)
    assert isinstance(project.get("name"), str) and project["name"]


def _assert_buses(payload: Mapping[str, Any]) -> None:
    assert payload["command"] == "buses"
    assert isinstance(payload.get("count"), int) and payload["count"] > 0
    buses = payload.get("buses")
    assert isinstance(buses, list) and len(buses) == payload["count"]
    for row in buses:
        assert isinstance(row, Mapping)
        assert row.get("type") == "Bus"
        for field in ("id", "name", "type", "path"):
            assert isinstance(row.get(field), str) and row[field]
    assert isinstance(payload.get("possibly_truncated"), bool)


def _assert_headless_selection_boundary(
    result: tuple[int, dict[str, Any]],
    *,
    version: str,
) -> dict[str, Any]:
    exit_code, payload = result
    assert exit_code == 0, payload
    assert payload.get("contract") == GATEWAY_CONTRACT
    assert payload.get("ok") is True
    assert payload.get("command") == "selected"
    assert payload.get("detected_version") == version
    assert payload.get("is_command_line") is True
    assert payload.get("status") == "unsupported_boundary"
    assert payload.get("count") is None
    assert payload.get("objects") is None
    call = payload.get("call")
    assert isinstance(call, Mapping) and call.get("ok") is False
    return payload


def _assert_reflection_functions(payload: Mapping[str, Any]) -> None:
    assert payload["command"] == "call"
    inventory = payload.get("inventory")
    assert isinstance(inventory, Mapping)
    assert inventory.get("kind") == "function"
    assert isinstance(inventory.get("count"), int) and inventory["count"] > 0
    uris = inventory.get("uris")
    assert isinstance(uris, list) and len(uris) == inventory["count"]
    assert uris == sorted(uris)
    assert len(uris) == len(set(uris))
    assert all(isinstance(uri, str) and uri.startswith("ak.") for uri in uris)
    packaged = inventory.get("packaged_manifest")
    assert isinstance(packaged, Mapping)
    assert isinstance(packaged.get("matches"), bool)


def _assert_clean_topic_timeout(
    result: tuple[int, dict[str, Any]],
    *,
    version: str,
) -> dict[str, Any]:
    exit_code, payload = result
    assert exit_code == 2, payload
    assert payload.get("contract") == GATEWAY_CONTRACT
    assert payload.get("ok") is False
    assert payload.get("status") == "error"
    assert payload.get("command") == "wait-topic"
    assert payload.get("detected_version") == version
    assert payload.get("topic") == "ak.wwise.core.object.created"
    assert payload.get("event") is None
    assert payload.get("cleanup") == "unsubscribed"
    call = payload.get("call")
    assert isinstance(call, Mapping)
    assert call.get("error_code") == "TIMEOUT"
    details = call.get("details")
    assert isinstance(details, Mapping)
    assert details.get("deadline_exhausted") is False
    assert details.get("cleanup_pending") is False
    assert details.get("abort_requested") is False
    operation_timeout = details.get("operation_timeout_seconds")
    assert isinstance(operation_timeout, float)
    assert 0 < operation_timeout < 0.5
    return payload


def _assert_project_query(payload: Mapping[str, Any]) -> None:
    assert payload["command"] == "query-object"
    assert payload["count"] == 1
    objects = payload.get("objects")
    assert isinstance(objects, list) and len(objects) == 1
    project = objects[0]
    assert isinstance(project, Mapping)
    assert project.get("type") == "Project"
    for field in ("id", "name", "type", "path"):
        assert field in project
    preview = payload.get("semantic_preview")
    assert isinstance(preview, Mapping)
    assert preview["envelope"]["uri"] == "ak.wwise.core.object.get"


def _assert_exact_path_query(payload: Mapping[str, Any], *, expected_path: str) -> None:
    assert payload["command"] == "query-object"
    assert payload["count"] == 1
    objects = payload.get("objects")
    assert isinstance(objects, list) and len(objects) == 1
    row = objects[0]
    assert isinstance(row, Mapping)
    assert row.get("path") == expected_path
    for field in ("id", "name", "type", "path"):
        assert isinstance(row.get(field), str) and row[field]
    preview = payload.get("semantic_preview")
    assert isinstance(preview, Mapping)
    envelope = preview.get("envelope")
    assert isinstance(envelope, Mapping)
    assert envelope.get("args") == {"waql": f'from object "{expected_path}"'}
    assert envelope.get("options") == {"return": ["id", "name", "type", "path"]}


def _assert_exact_guid_query(
    payload: Mapping[str, Any],
    *,
    expected_id: str,
    expected_path: str,
) -> None:
    assert payload["count"] == 1
    row = payload["objects"][0]
    assert row["id"].casefold() == expected_id.casefold()
    assert row["path"] == expected_path
    _assert_query_preview(
        payload,
        expected_waql=f'from object "{expected_id}"',
        minimum_count=1,
    )


def _assert_empty_exact_query(payload: Mapping[str, Any]) -> None:
    assert payload["count"] == 0
    assert payload["objects"] == []
    call = payload.get("call")
    assert isinstance(call, Mapping) and call.get("ok") is True
    if "normalization" in call:
        normalization = call["normalization"]
        assert isinstance(normalization, Mapping)
        assert normalization.get("kind") == "exact-object-absence"
        assert normalization.get("source") in {
            "ak.wwise.query.unknown_object",
            "ak.wwise.query.invalid_query:object-not-found",
        }


def _assert_query_preview(
    payload: Mapping[str, Any],
    *,
    expected_waql: str,
    minimum_count: int,
) -> None:
    assert payload["command"] == "query-object"
    count = payload.get("count")
    assert isinstance(count, int) and count >= minimum_count
    objects = payload.get("objects")
    assert isinstance(objects, list) and len(objects) == count
    preview = payload.get("semantic_preview")
    assert isinstance(preview, Mapping)
    envelope = preview.get("envelope")
    assert isinstance(envelope, Mapping)
    assert envelope.get("args") == {"waql": expected_waql}
    call = payload.get("call")
    assert isinstance(call, Mapping) and call.get("ok") is True


def _assert_type_metadata(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    assert payload["command"] == "metadata"
    assert payload["operation"] == "types"
    normalized = payload.get("normalized")
    assert isinstance(normalized, list) and normalized
    rows: list[dict[str, Any]] = []
    for row in normalized:
        assert isinstance(row, Mapping)
        assert isinstance(row.get("classId"), int) and row["classId"] >= 0
        assert isinstance(row.get("name"), str) and row["name"]
        assert isinstance(row.get("type"), str) and row["type"]
        rows.append(dict(row))
    assert any(row["name"] == "Project" for row in rows)
    return rows


def _find_live_property_scope(
    common: Sequence[str],
    *,
    env: Mapping[str, str],
    version: str,
    type_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    attempts = 0

    for type_row in _ordered_type_rows(type_rows):
        class_id = type_row["classId"]
        names_result = _invoke_gateway(
            common,
            ("metadata", "names", "--class-id", str(class_id)),
            env=env,
        )
        if names_result[0] != 0:
            diagnostics.append(_failure_summary(type_row, None, names_result[1]))
            continue
        names = _require_gateway_success(names_result, command="metadata names", version=version)
        normalized_names = names.get("normalized")
        if not isinstance(normalized_names, list):
            diagnostics.append({"type": dict(type_row), "reason": "normalized names was not a list"})
            continue
        discovered = [
            str(item["name"])
            for item in normalized_names
            if isinstance(item, Mapping) and isinstance(item.get("name"), str) and item["name"]
        ]

        for property_name in _ordered_property_names(discovered):
            attempts += 1
            info_result = _invoke_gateway(
                common,
                (
                    "metadata",
                    "property-info",
                    "--class-id",
                    str(class_id),
                    "--property",
                    property_name,
                ),
                env=env,
            )
            if info_result[0] == 0:
                info = _require_gateway_success(info_result, command="metadata property-info", version=version)
                normalized = info.get("normalized")
                if isinstance(normalized, Mapping) and normalized.get("name") == property_name:
                    assert isinstance(normalized.get("type"), str) and normalized["type"]
                    return {
                        "type_row": dict(type_row),
                        "property_name": property_name,
                        "names": names,
                        "property_info": info,
                        "attempts": attempts,
                    }
            diagnostics.append(_failure_summary(type_row, property_name, info_result[1]))
            if attempts >= MAX_PROPERTY_INFO_ATTEMPTS:
                break
        if attempts >= MAX_PROPERTY_INFO_ATTEMPTS:
            break

    pytest.fail(
        "getTypes returned no classId/property scope accepted by metadata property-info; "
        f"attempts={attempts}, diagnostics={json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)}"
    )


def _ordered_type_rows(type_rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    preference = {name: index for index, name in enumerate(PREFERRED_METADATA_TYPES)}
    return sorted(
        type_rows,
        key=lambda row: (
            preference.get(str(row.get("name")), len(preference)),
            str(row.get("name", "")),
            int(row["classId"]),
        ),
    )


def _ordered_property_names(names: Sequence[str]) -> list[str]:
    discovered = list(dict.fromkeys(names))
    preference = {name: index for index, name in enumerate(PREFERRED_PROPERTY_NAMES)}
    return sorted(discovered, key=lambda name: (preference.get(name, len(preference)), name))


def _failure_summary(
    type_row: Mapping[str, Any],
    property_name: str | None,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "type": {
            "classId": type_row.get("classId"),
            "name": type_row.get("name"),
            "type": type_row.get("type"),
        },
        "property": property_name,
        "error_code": payload.get("error_code"),
        "message": payload.get("message"),
    }


def _dispatcher_evidence_paths(payload: Mapping[str, Any]) -> tuple[Path, ...]:
    paths: list[Path] = []
    calls = payload.get("calls")
    candidates: list[Any] = list(calls) if isinstance(calls, list) else []
    if isinstance(payload.get("call"), Mapping):
        candidates.append(payload["call"])
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        raw_path = candidate.get("evidence_path")
        if isinstance(raw_path, str) and raw_path:
            paths.append(Path(raw_path))
    return tuple(paths)


def _safe_lock_root(env: Mapping[str, str], *, version: str) -> Path:
    raw_root = env.get("WWISE_SANDBOX_ROOT")
    root = (
        Path(raw_root).expanduser()
        if raw_root
        else REPO_ROOT / ".waapi-skill-state" / "runtime" / "waapi-gateway-live-matrix" / version
    ).resolve(strict=False)
    source_project = resolve_sample_project_source(env)
    if source_project is not None:
        source_root = source_project.parent.resolve(strict=False)
        if root == source_root or path_is_under(root, source_root) or path_is_under(source_root, root):
            raise SandboxFixtureError("gateway matrix sandbox lock root must not overlap the immutable source project")
    return root


def _write_matrix_evidence(version: str, payload: Mapping[str, Any]) -> None:
    target = EVIDENCE_ROOT / version / "read-only-gateway-matrix.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
