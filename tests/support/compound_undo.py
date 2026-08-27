"""Test-only helpers for canonical compound Undo requests.

The public Gateway accepts checked child Draft identities.  Unit tests that
exercise lower transaction layers do not own a Draft store, so they construct
the same immutable child snapshots directly through the production Adapter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import BusinessContext
from wwise_waapi.compound_undo_business import (
    build_compound_undo_child_snapshot,
    materialize_compound_undo_business_request,
)


def compound_undo_request(
    *,
    version: str,
    child_requests: Sequence[Mapping[str, Any]],
    display_name: str = "Program Undo Group",
) -> dict[str, Any]:
    """Wrap closed child requests in the production checked-snapshot seam."""

    snapshots = [
        build_compound_undo_child_snapshot(
            version=version,
            source_draft_id=f"od1-{index:032x}",
            source_revision=1,
            request=request,
        )
        for index, request in enumerate(child_requests, start=1)
    ]
    session = BusinessDeclarationSession.create(
        BusinessContext.create(
            task_authority="da1-" + "1" * 40,
            project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            project_path="/fixtures/SampleProject.wproj",
            wwise_version=version,
            wwise_build=f"{version}.fixture",
        )
    ).with_settings(
        {
            "undo_plan": {
                "display_name": display_name,
                "children": snapshots,
            }
        }
    )
    return dict(
        materialize_compound_undo_business_request("waapi.undoGroup", session)
    )


__all__ = ["compound_undo_request"]
