"""CLI projection for one closed Debug business intent."""

from __future__ import annotations

import argparse
from typing import Any

from .debug_business_contracts import DEBUG_BOOLEAN_OPERATIONS


class DebugBusinessCliError(ValueError):
    """One Debug business declaration is invalid."""


def add_debug_intent_arguments(parser: argparse.ArgumentParser) -> None:
    outcome = parser.add_mutually_exclusive_group()
    outcome.add_argument("--enable", dest="enabled", action="store_true")
    outcome.add_argument("--disable", dest="enabled", action="store_false")
    parser.set_defaults(enabled=None)


def debug_intent_from_namespace(
    args: argparse.Namespace,
    *,
    operation: str,
) -> dict[str, Any]:
    if operation in DEBUG_BOOLEAN_OPERATIONS:
        if args.enabled is None:
            raise DebugBusinessCliError(f"{operation} requires --enable or --disable")
        return {"enabled": args.enabled}
    if args.enabled is not None:
        raise DebugBusinessCliError(f"{operation} accepts no business values")
    return {}


__all__ = [
    "DebugBusinessCliError",
    "add_debug_intent_arguments",
    "debug_intent_from_namespace",
]
