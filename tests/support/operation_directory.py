"""Expand disclosed static operations-directory metadata for test consumers."""

from typing import Any, Mapping


def expand_operations_directory_row(
    directory: Mapping[str, Any], row: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconstruct one catalog row without treating templates as continuations."""

    if "api" in row:
        expanded = {**directory.get("request_schema_route_defaults", {}), **row}
        template_key, command, marker, identity = (
            "request_schema_command_template", "request-schema", "<api>", row["api"],
        )
    else:
        expanded = dict(row)
        template_key, command, marker, identity = (
            "operation_schema_command_template", "operation-schema", "<name>", row["name"],
        )
    if "next_command" not in expanded:
        template = directory[template_key]
        assert template == [command, marker]
        expanded["next_command"] = [
            identity if part == marker else part for part in template
        ]
    return expanded
