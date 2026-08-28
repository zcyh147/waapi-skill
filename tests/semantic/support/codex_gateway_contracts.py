"""Closed public Gateway response-envelope contracts for semantic evidence."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

from wwise_waapi.metadata_discovery import (
    metadata_candidate_limit_for_query_count,
)


GATEWAY_RESULT_CONTRACT = "waapi-skill.gateway-result/v1"
TYPED_REQUEST_SCHEMA_CONTRACT = "waapi-skill.typed-request-schema/v1"
FIXED_COMMAND_ROUTE_CONTRACT = "waapi-skill.fixed-command-route/v1"
BUSINESS_QUERY_SCHEMA_CONTRACT = "waapi-skill.object-query-business-schema/v1"
ADVANCED_QUERY_SCHEMA_CONTRACT = (
    "waapi-skill.advanced-object-query-business-schema/v1"
)
TYPED_TOPIC_INPUT_CONTRACT = "waapi-skill.typed-topic-input/v1"
TYPED_CONTAINER_HANDLE_CONTRACT = "waapi-skill.typed-container-handle/v1"
TYPED_MAP_CONTAINER_CHOICES_CONTRACT = (
    "waapi-skill.typed-map-container-choices/v1"
)
TYPED_ARRAY_ITEM_CHOICES_CONTRACT = (
    "waapi-skill.typed-array-item-choices/v1"
)
TASK_LOCAL_RUNNER_POSIX = ".agents/skills/waapi-skill/scripts/run.py"
TASK_LOCAL_RUNNER_WINDOWS = r".agents\skills\waapi-skill\scripts\run.py"


def task_local_runner_matches_normalized(
    raw_runner: str,
    normalized_runner: str,
) -> bool:
    """Bind one exact task-local spelling to its absolute installed runner."""

    if raw_runner == TASK_LOCAL_RUNNER_POSIX:
        path = PurePosixPath(normalized_runner)
        expected_tail = PurePosixPath(TASK_LOCAL_RUNNER_POSIX).parts
    elif raw_runner == TASK_LOCAL_RUNNER_WINDOWS:
        path = PureWindowsPath(normalized_runner)
        expected_tail = PureWindowsPath(TASK_LOCAL_RUNNER_WINDOWS).parts
    else:
        return False
    return path.is_absolute() and path.parts[-len(expected_tail) :] == expected_tail


def gateway_payload_contracts(subcommand: str) -> frozenset[str]:
    """Return the exact public success envelopes allowed for one command."""

    if subcommand == "request-schema":
        return frozenset(
            {TYPED_REQUEST_SCHEMA_CONTRACT, FIXED_COMMAND_ROUTE_CONTRACT}
        )
    if subcommand == "query-schema":
        return frozenset(
            {
                BUSINESS_QUERY_SCHEMA_CONTRACT,
                ADVANCED_QUERY_SCHEMA_CONTRACT,
                GATEWAY_RESULT_CONTRACT,
            }
        )
    if subcommand == "topic-schema":
        return frozenset({TYPED_TOPIC_INPUT_CONTRACT})
    if subcommand == "request-map-container":
        return frozenset(
            {TYPED_CONTAINER_HANDLE_CONTRACT, TYPED_MAP_CONTAINER_CHOICES_CONTRACT}
        )
    if subcommand == "request-array-item":
        return frozenset(
            {TYPED_CONTAINER_HANDLE_CONTRACT, TYPED_ARRAY_ITEM_CHOICES_CONTRACT}
        )
    return frozenset({GATEWAY_RESULT_CONTRACT})


__all__ = [
    "GATEWAY_RESULT_CONTRACT",
    "ADVANCED_QUERY_SCHEMA_CONTRACT",
    "BUSINESS_QUERY_SCHEMA_CONTRACT",
    "FIXED_COMMAND_ROUTE_CONTRACT",
    "TASK_LOCAL_RUNNER_POSIX",
    "TASK_LOCAL_RUNNER_WINDOWS",
    "TYPED_ARRAY_ITEM_CHOICES_CONTRACT",
    "TYPED_CONTAINER_HANDLE_CONTRACT",
    "TYPED_MAP_CONTAINER_CHOICES_CONTRACT",
    "TYPED_REQUEST_SCHEMA_CONTRACT",
    "TYPED_TOPIC_INPUT_CONTRACT",
    "gateway_payload_contracts",
    "metadata_candidate_limit_for_query_count",
    "task_local_runner_matches_normalized",
]
