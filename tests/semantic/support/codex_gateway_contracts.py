"""Closed public Gateway response-envelope contracts for semantic evidence."""

from __future__ import annotations


GATEWAY_RESULT_CONTRACT = "waapi-skill.gateway-result/v1"
TYPED_REQUEST_SCHEMA_CONTRACT = "waapi-skill.typed-request-schema/v1"
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


def gateway_payload_contracts(subcommand: str) -> frozenset[str]:
    """Return the exact public success envelopes allowed for one command."""

    if subcommand in {"request-schema", "query-schema"}:
        return frozenset({TYPED_REQUEST_SCHEMA_CONTRACT})
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
    "TASK_LOCAL_RUNNER_POSIX",
    "TASK_LOCAL_RUNNER_WINDOWS",
    "TYPED_ARRAY_ITEM_CHOICES_CONTRACT",
    "TYPED_CONTAINER_HANDLE_CONTRACT",
    "TYPED_MAP_CONTAINER_CHOICES_CONTRACT",
    "TYPED_REQUEST_SCHEMA_CONTRACT",
    "TYPED_TOPIC_INPUT_CONTRACT",
    "gateway_payload_contracts",
]
