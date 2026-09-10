from __future__ import annotations

import pytest

from wwise_waapi.business_declarations import SUPPORTED_WWISE_VERSIONS
from wwise_waapi.object_capabilities import (
    NON_INTRINSIC_NAME_OBJECT_TYPES,
    object_child_capability,
)


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_object_child_capability_owns_versioned_container_rules(version: str) -> None:
    ordinary = object_child_capability(
        version=version,
        parent_type="ActorMixer",
        child_types=("Sound",),
    )
    reflected = object_child_capability(
        version=version,
        parent_type="PropertyContainer",
        child_types=("Sound",),
    )

    assert ordinary.allowed is True
    assert reflected.allowed is (version == "2025.1")


@pytest.mark.parametrize(
    "object_type",
    sorted(NON_INTRINSIC_NAME_OBJECT_TYPES),
)
def test_non_intrinsic_object_types_are_not_generic_child_containers(
    object_type: str,
) -> None:
    capability = object_child_capability(
        version="2025.1",
        parent_type=object_type,
        child_types=("Sound",),
    )

    assert capability.writable_parent is False
    assert capability.allowed is False


def test_game_sync_children_keep_both_parent_and_child_constraints() -> None:
    valid = object_child_capability(
        version="2025.1",
        parent_type="StateGroup",
        child_types=("State",),
    )
    wrong_child = object_child_capability(
        version="2025.1",
        parent_type="StateGroup",
        child_types=("Switch",),
    )
    wrong_parent = object_child_capability(
        version="2025.1",
        parent_type="ActorMixer",
        child_types=("State",),
    )

    assert valid.allowed is True
    assert valid.allowed_child_types == ("State",)
    assert wrong_child.invalid_child_types == ("Switch",)
    assert wrong_parent.invalid_child_types == ("State",)
    assert wrong_parent.required_parent_types_for("State") == ("StateGroup",)
