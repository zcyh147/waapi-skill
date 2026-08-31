"""Independent exact oracle for the Media Pool Gateway business projection."""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Any, Mapping

from .codex_gateway_broker import ExactArgumentAlternatives, ExpectedGatewayStep
from .codex_media_pool_runtime_v3 import (
    MEDIA_POOL_GET_URI,
    SealedMediaPoolOracle,
    VerificationResult,
)


class MediaPoolBusinessOracleError(ValueError):
    """The observed business projection differs from its sealed protocol."""


def _strict_json_equal(actual: Any, expected: Any) -> bool:
    """Compare JSON values recursively without Python bool/number coercion."""

    if isinstance(expected, Mapping):
        return (
            isinstance(actual, Mapping)
            and set(actual) == set(expected)
            and all(_strict_json_equal(actual[key], value) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                _strict_json_equal(actual_value, expected_value)
                for actual_value, expected_value in zip(actual, expected, strict=True)
            )
        )
    return type(actual) is type(expected) and actual == expected


def verify_media_pool_business_projection(
    oracle: SealedMediaPoolOracle,
    step: ExpectedGatewayStep,
    payload: Mapping[str, Any],
    business_request: Mapping[str, Any],
) -> VerificationResult:
    """Check one Gateway business result against the sealed protocol and index."""

    try:
        if (
            step.name != "media.get"
            or step.subcommand != "core-call"
            or not step.arguments
            or step.arguments[0] != MEDIA_POOL_GET_URI
        ):
            raise MediaPoolBusinessOracleError(
                "Media Pool projection requires the sealed media.get core-call step"
            )
        option_arity = {
            "--max-results": 1,
            "--database-scope": 1,
            "--database-id": 1,
            "--search-text": 1,
            "--text-filter": 3,
            "--number-filter": 3,
            "--audio-description": 1,
            "--weighted-audio-description": 2,
            "--audio-similarity-file": 1,
            "--weighted-audio-similarity-file": 2,
            "--include-field": 1,
            "--exact-name-contains": 1,
            "--final-limit": 1,
            "--sort-by": 2,
        }
        groups: list[tuple[Any, ...]] = []
        cursor = 1
        while cursor < len(step.arguments):
            option = step.arguments[cursor]
            arity = option_arity.get(option) if isinstance(option, str) else None
            if arity is None or cursor + arity >= len(step.arguments):
                raise MediaPoolBusinessOracleError(
                    "sealed Media Pool business step has an invalid option group"
                )
            groups.append(tuple(step.arguments[cursor : cursor + arity + 1]))
            cursor += arity + 1

        def choices(value: Any) -> tuple[str, ...]:
            if isinstance(value, ExactArgumentAlternatives):
                return value.values
            if isinstance(value, str) and value:
                return (value,)
            raise MediaPoolBusinessOracleError(
                "sealed Media Pool business option lacks closed string choices"
            )

        def selected_groups(option: str) -> tuple[tuple[Any, ...], ...]:
            return tuple(group for group in groups if group[0] == option)

        def one_value(option: str) -> str | None:
            selected = selected_groups(option)
            if not selected:
                return None
            if len(selected) != 1:
                raise MediaPoolBusinessOracleError(
                    f"sealed Media Pool business step repeats {option}"
                )
            values = choices(selected[0][1])
            if len(values) != 1:
                raise MediaPoolBusinessOracleError(
                    f"sealed Media Pool scalar {option} is not exact"
                )
            return values[0]

        request_keys = {
            "operation",
            "database_scopes",
            "database_ids",
            "search_text",
            "filter_count",
            "max_results",
            "return_field_meanings",
            "exact_name_contains",
            "final_limit",
            "sort_rules",
        }
        if not isinstance(business_request, Mapping) or set(business_request) != request_keys:
            raise MediaPoolBusinessOracleError(
                "Media Pool business request evidence has an unexpected field set"
            )
        if business_request.get("operation") != MEDIA_POOL_GET_URI:
            raise MediaPoolBusinessOracleError(
                "Media Pool business request evidence names the wrong operation"
            )
        raw_limit = one_value("--max-results")
        if raw_limit is None:
            raise MediaPoolBusinessOracleError(
                "sealed Media Pool business step lacks max-results"
            )
        candidate_limit = int(raw_limit)
        if business_request.get("max_results") != candidate_limit:
            raise MediaPoolBusinessOracleError(
                "Media Pool business candidate limit differs from the sealed step"
            )

        def selected_values(option: str, field: str) -> tuple[str, ...]:
            actual = business_request.get(field)
            if not isinstance(actual, list):
                raise MediaPoolBusinessOracleError(
                    f"Media Pool business request {field} is not a list"
                )
            expected = selected_groups(option)
            if len(actual) != len(expected) or any(
                not isinstance(value, str) or value not in choices(group[1])
                for value, group in zip(actual, expected, strict=True)
            ):
                raise MediaPoolBusinessOracleError(
                    f"Media Pool business request {field} differs from the sealed step"
                )
            return tuple(actual)

        database_scopes = selected_values("--database-scope", "database_scopes")
        database_ids = selected_values("--database-id", "database_ids")
        if any(
            not re.fullmatch(
                r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}",
                value,
            )
            for value in database_ids
        ):
            raise MediaPoolBusinessOracleError(
                "Media Pool business database evidence contains an invalid GUID"
            )
        search_text = one_value("--search-text")
        exact_name = one_value("--exact-name-contains")
        raw_final_limit = one_value("--final-limit")
        final_limit = int(raw_final_limit) if raw_final_limit is not None else None
        if (
            business_request.get("search_text") != search_text
            or business_request.get("exact_name_contains") != exact_name
            or business_request.get("final_limit") != final_limit
        ):
            raise MediaPoolBusinessOracleError(
                "Media Pool business scalar evidence differs from the sealed step"
            )

        include_groups = selected_groups("--include-field")
        return_meanings = business_request.get("return_field_meanings")
        if (
            not isinstance(return_meanings, list)
            or len(return_meanings) != len(include_groups)
            or any(
                not isinstance(value, str) or value not in choices(group[1])
                for value, group in zip(return_meanings, include_groups, strict=True)
            )
        ):
            raise MediaPoolBusinessOracleError(
                "Media Pool return projection differs from the sealed step"
            )
        sort_groups = selected_groups("--sort-by")
        raw_sort_rules = business_request.get("sort_rules")
        if not isinstance(raw_sort_rules, list) or len(raw_sort_rules) != len(
            sort_groups
        ):
            raise MediaPoolBusinessOracleError(
                "Media Pool sort projection differs from the sealed step"
            )
        sort_rules: list[tuple[str, str, str]] = []
        for raw_rule, group in zip(raw_sort_rules, sort_groups, strict=True):
            if (
                not isinstance(raw_rule, Mapping)
                or set(raw_rule) != {"field_meaning", "direction"}
                or raw_rule.get("field_meaning") not in choices(group[1])
                or raw_rule.get("direction") != group[2]
            ):
                raise MediaPoolBusinessOracleError(
                    "Media Pool sort evidence differs from the sealed step"
                )
            sort_rules.append(
                (str(raw_rule["field_meaning"]), choices(group[1])[0], str(group[2]))
            )

        server_filter_groups = tuple(
            group
            for group in groups
            if group[0]
            in {
                "--text-filter",
                "--number-filter",
                "--audio-description",
                "--weighted-audio-description",
                "--audio-similarity-file",
                "--weighted-audio-similarity-file",
            }
        )
        expected_filter_count = len(server_filter_groups)
        if exact_name is not None:
            filename_aliases = {"Filename", "filename", "name", "name/file"}
            duplicate_candidate_filter = any(
                group[0] == "--text-filter"
                and bool(filename_aliases.intersection(choices(group[1])))
                and group[2] == "contains"
                and group[3] == exact_name
                for group in server_filter_groups
            )
            if not duplicate_candidate_filter:
                expected_filter_count += 1
        if business_request.get("filter_count") != expected_filter_count:
            raise MediaPoolBusinessOracleError(
                "Media Pool business filter count differs from the sealed step"
            )

        selected_bindings = [
            (str(value), choices(group[1])[0])
            for value, group in zip(return_meanings, include_groups, strict=True)
        ]
        selected_bindings.extend(
            (meaning, field) for meaning, field, _direction in sort_rules
        )
        output_bindings: list[tuple[str, str]] = []
        seen_meanings: set[str] = set()
        seen_keys: set[str] = set()
        for meaning, field in selected_bindings:
            if meaning in seen_meanings:
                continue
            seen_meanings.add(meaning)
            key = re.sub(r"[^a-z0-9]+", "_", meaning.casefold()).strip("_")
            if not key or key in seen_keys:
                raise MediaPoolBusinessOracleError(
                    "Media Pool business projection keys are not unique"
                )
            seen_keys.add(key)
            output_bindings.append((key, field))

        candidate_keys = oracle.candidate_keys
        complete = not (
            exact_name is not None and len(candidate_keys) >= candidate_limit
        )
        selected_keys = list(candidate_keys) if complete else []
        if exact_name is not None and complete:
            filename_field = oracle.request.binding.exact("name")
            selected_keys = [
                key
                for key in selected_keys
                if exact_name in str(oracle.row(key).values[filename_field])
            ]

        def sort_value(value: Any) -> tuple[int, Any]:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return (0, float(value))
            if isinstance(value, str):
                return (1, value.casefold())
            return (2, repr(value))

        for _meaning, field, direction in reversed(sort_rules):
            present = [
                key for key in selected_keys if oracle.row(key).values.get(field) is not None
            ]
            missing = [
                key for key in selected_keys if oracle.row(key).values.get(field) is None
            ]
            present.sort(
                key=lambda key: sort_value(oracle.row(key).values.get(field)),
                reverse=direction == "descending",
            )
            selected_keys = [*present, *missing]
        if final_limit is not None:
            selected_keys = selected_keys[:final_limit]

        items: list[dict[str, Any]] = []
        includes_database = "Db" in tuple(oracle.request.options["return"])
        for key in selected_keys:
            row = oracle.row(key)
            item: dict[str, Any] = {
                "path": row.path,
                "file_id": row.file_id,
            }
            if includes_database:
                item.update(
                    {
                        "database_id": str(row.db["id"]).upper(),
                        "database_name": row.db["name"],
                    }
                )
            item["values"] = {
                name: row.values[field] for name, field in output_bindings
            }
            items.append(item)
        expected_payload = {
            "contract": "waapi-skill.media-build-result/v1",
            "kind": "media_pool_rows",
            "complete": complete,
            "candidate_count": len(candidate_keys),
            "returned_count": len(items),
            "candidate_limit": candidate_limit,
            "incomplete_reason": (
                None
                if complete
                else "candidate_limit_reached_before_exact_case_post_filter"
            ),
            "items": items,
        }
        expected_request = {
            "operation": MEDIA_POOL_GET_URI,
            "database_scopes": list(database_scopes),
            "database_ids": list(database_ids),
            "search_text": search_text,
            "filter_count": expected_filter_count,
            "max_results": candidate_limit,
            "return_field_meanings": list(return_meanings),
            "exact_name_contains": exact_name,
            "final_limit": final_limit,
            "sort_rules": [
                {"field_meaning": meaning, "direction": direction}
                for meaning, _field, direction in sort_rules
            ],
        }
        if not _strict_json_equal(business_request, expected_request):
            raise MediaPoolBusinessOracleError(
                "Media Pool business request evidence is not exactly sealed"
            )
        if not _strict_json_equal(payload, expected_payload):
            raise MediaPoolBusinessOracleError(
                "Media Pool business result differs from the sealed projection"
            )
        return VerificationResult(
            ok=True,
            code="MEDIA_POOL_BUSINESS_RESULT_EXACT",
            details=MappingProxyType(
                {
                    "scenario_id": oracle.scenario_id,
                    "file_ids": tuple(oracle.row(key).file_id for key in selected_keys),
                    "row_count": len(items),
                }
            ),
        )
    except (MediaPoolBusinessOracleError, KeyError, TypeError, ValueError) as exc:
        return VerificationResult(
            ok=False,
            code="MEDIA_POOL_BUSINESS_RESULT_MISMATCH",
            details=MappingProxyType({"error": str(exc)}),
        )

__all__ = ["verify_media_pool_business_projection"]

