"""Compile Debug business intents into canonical operation requests."""

from __future__ import annotations

from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .debug_business_contracts import (
    DEBUG_BOOLEAN_OPERATIONS,
    DEBUG_BUSINESS_LANES,
)


def materialize_debug_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    versions = DEBUG_BUSINESS_LANES.get(operation)
    if versions is None:
        raise ValueError("unsupported Debug business operation")
    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    if session.context.wwise_version not in versions:
        raise _repair(session, "VERSION_BEHAVIOR_BOUNDARY")
    if set(session.settings) != {"debug_intent"}:
        raise _repair(session, "BUSINESS_DECLARATION_INCOMPLETE")
    raw = session.settings["debug_intent"]
    if not isinstance(raw, Mapping):
        raise _repair(session, "INVALID_ARGUMENT")
    intent = dict(raw)
    if operation in DEBUG_BOOLEAN_OPERATIONS:
        if set(intent) != {"enabled"} or type(intent.get("enabled")) is not bool:
            raise _repair(session, "INVALID_ARGUMENT")
        arguments = {"enable": intent["enabled"]}
    else:
        if intent:
            raise _repair(session, "INVALID_ARGUMENT")
        arguments = {}
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": session.context.wwise_version,
        "operation": operation,
        "arguments": arguments,
    }


def _repair(session: BusinessDeclarationSession, error_code: str):
    return business_repair(
        error_code,
        field="debug_intent",
        draft_revision=session.revision,
        action="use only the disclosed Debug business intent",
    )


__all__ = ["materialize_debug_business_request"]
