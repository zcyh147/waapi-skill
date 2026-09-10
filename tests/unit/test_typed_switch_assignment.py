from __future__ import annotations

import pytest

from wwise_waapi.operation_registry import (
    BUSINESS_DECLARATION_INPUT_MODE,
    operation_input_mode,
)
from wwise_waapi.typed_operations import (
    INLINE_OPERATIONS,
    TypedOperationInputError,
    inline_operation_contract,
    materialize_inline_operation_request,
)


@pytest.mark.parametrize("version", ("2021.1", "2025.1"))
@pytest.mark.parametrize(
    "operation",
    (
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
    ),
)
def test_switch_assignment_inline_typed_surface_is_removed(
    version: str,
    operation: str,
) -> None:
    assert operation_input_mode(operation, version) == (
        BUSINESS_DECLARATION_INPUT_MODE
    )
    assert operation not in INLINE_OPERATIONS

    with pytest.raises(TypedOperationInputError, match="No inline typed adapter"):
        inline_operation_contract(operation, version)
    with pytest.raises(TypedOperationInputError, match="No inline typed adapter"):
        materialize_inline_operation_request(
            operation,
            version,
            {
                "switch_container": ("id-string", "{1}"),
                "child": ("id-string", "{2}"),
                "state_or_switch": ("id-string", "{3}"),
            },
        )
