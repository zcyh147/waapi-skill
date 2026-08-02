from __future__ import annotations

import copy
import re

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticErrorCode,
    SemanticValidationError,
    SourceNoteCheck,
)
from wwise_waapi.builders.query import (  # pyright: ignore[reportMissingImports]
    ADVANCED_QUERY_CONTRACT,
    MAX_ADVANCED_RETURN_EXPRESSION_BYTES,
    MAX_ADVANCED_RETURN_EXPRESSIONS,
    MAX_ADVANCED_WAQL_BYTES,
    MAX_QUERY_TAKE,
    MAX_STRUCTURED_BOOLEAN_DEPTH,
    MAX_STRUCTURED_LITERAL_LENGTH,
    MAX_STRUCTURED_QUERY_NODES,
    MAX_STRUCTURED_RETURN_FIELDS,
    MAX_STRUCTURED_SELECT_EXPRESSIONS,
    MAX_STRUCTURED_SOURCE_ITEMS,
    MAX_STRUCTURED_TRANSFORMS,
    STRUCTURED_QUERY_CONTRACT,
    WaqlQueryBuilder,
    advanced_query_schema,
    build_advanced_object_get_query,
    build_structured_object_get_query,
    structured_query_schema,
)


GUID_A = "{11111111-1111-1111-1111-111111111111}"
GUID_B = "{22222222-2222-2222-2222-222222222222}"
VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")


def _schema_variant(schema: dict[str, object], kind: str) -> dict[str, object]:
    branches = schema["oneOf"]
    assert isinstance(branches, list)
    for branch in branches:
        assert isinstance(branch, dict)
        properties = branch.get("properties")
        if not isinstance(properties, dict):
            continue
        discriminator = properties.get("kind")
        if isinstance(discriminator, dict) and discriminator.get("const") == kind:
            return branch
    raise AssertionError(f"missing schema branch for kind={kind!r}")


def _schema_leaf_accepts(schema: dict[str, object], value: object) -> bool:
    expected = schema.get("type")
    expected_types = [expected] if isinstance(expected, str) else expected
    if isinstance(expected_types, list):
        matches = {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }
        if not any(matches.get(item, False) for item in expected_types):
            return False
    if "const" in schema and value != schema["const"]:
        return False
    allowed = schema.get("enum")
    if isinstance(allowed, list) and value not in allowed:
        return False
    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            return False
        if isinstance(maximum, int) and len(value) > maximum:
            return False
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            return False
    return True


def _comparison_schema_accepts(
    predicate_schema: dict[str, object],
    *,
    operator: str,
    value: object,
) -> bool:
    branches = predicate_schema["oneOf"]
    assert isinstance(branches, list)
    matches = 0
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        properties = branch.get("properties")
        if not isinstance(properties, dict):
            continue
        kind_schema = properties.get("kind")
        operator_schema = properties.get("operator")
        value_schema = properties.get("value")
        if not (
            isinstance(kind_schema, dict)
            and kind_schema.get("const") == "compare"
            and isinstance(operator_schema, dict)
            and isinstance(value_schema, dict)
        ):
            continue
        if _schema_leaf_accepts(
            operator_schema, operator
        ) and _schema_leaf_accepts(value_schema, value):
            matches += 1
    return matches == 1


class FakeSourceNoteChecker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def check(self, family: str, version: str) -> SourceNoteCheck:
        self.calls.append((family, version))
        return SourceNoteCheck(
            True,
            BuilderFamily.QUERY.value,
            version=version,
            cited_fields=("waql", "options.return"),
        )


def request(
    *,
    source: dict[str, object] | None = None,
    transforms: list[dict[str, object]] | None = None,
    return_fields: list[str] | None = None,
) -> dict[str, object]:
    return {
        "contract": STRUCTURED_QUERY_CONTRACT,
        "source": source
        or {
            "kind": "object",
            "objects": [{"kind": "id", "value": GUID_A}],
        },
        "transforms": transforms or [],
        "return": return_fields or ["id", "name", "type", "path"],
    }


def advanced_request(
    *,
    waql: str = "from type Sound orderby name",
    return_fields: list[str] | None = None,
    max_results: int = 25,
) -> dict[str, object]:
    return {
        "contract": ADVANCED_QUERY_CONTRACT,
        "waql": waql,
        "return": return_fields or ["id", "name", "type", "path"],
        "max_results": max_results,
    }


@pytest.mark.parametrize("version", VERSIONS)
def test_advanced_query_five_version_contract_appends_gateway_cap(version: str) -> None:
    checker = FakeSourceNoteChecker()
    preview = build_advanced_object_get_query(
        advanced_request(
            waql=(
                'from type Sound where effects.any(effect.name = "Compressor") '
                "orderby name distinct"
            ),
            return_fields=[
                "id",
                "name",
                "effects.name as EffectNames",
                "OutputBus.{name, shortid}",
            ],
            max_results=17,
        ),
        version=version,
        source_note_checker=checker,
    )

    assert preview.envelope.uri == "ak.wwise.core.object.get"
    assert preview.envelope.args == {
        "waql": (
            'from type Sound where effects.any(effect.name = "Compressor") '
            "orderby name distinct take 17"
        )
    }
    assert preview.envelope.options == {
        "return": [
            "id",
            "name",
            "effects.name as EffectNames",
            "OutputBus.{name, shortid}",
        ]
    }
    assert preview.envelope.metadata["query_contract"] == ADVANCED_QUERY_CONTRACT
    assert preview.envelope.metadata["query_bound"] == {
        "mode": "gateway-appended-take",
        "value": 17,
    }
    assert preview.envelope.metadata["read_only"] is True
    assert checker.calls == [(BuilderFamily.QUERY.value, version)]


def test_advanced_query_preserves_existing_transforms_and_adds_a_second_take() -> None:
    preview = build_advanced_object_get_query(
        advanced_request(
            waql="from type Sound skip 10 take 40 orderby name reverse   ",
            max_results=7,
        )
    )

    assert preview.envelope.args == {
        "waql": "from type Sound skip 10 take 40 orderby name reverse take 7"
    }


def test_advanced_query_does_not_confuse_read_only_search_terms_with_mutation() -> None:
    preview = build_advanced_object_get_query(
        advanced_request(
            waql=r'from search "delete; create // import" where notes = /[/;]set/',
            max_results=3,
        )
    )

    assert preview.envelope.args["waql"].endswith(" take 3")


@pytest.mark.parametrize(
    "payload",
    (
        {**advanced_request(), "contract": "wrong"},
        {**advanced_request(), "unknown": True},
        {**advanced_request(), "waql": ""},
        {**advanced_request(), "waql": "   "},
        {**advanced_request(), "waql": 7},
        {**advanced_request(), "return": "id"},
        {**advanced_request(), "return": [7]},
        {**advanced_request(), "max_results": True},
        {**advanced_request(), "max_results": 2.5},
        {**advanced_request(), "max_results": "2"},
        {**advanced_request(), "max_results": 0},
        {**advanced_request(), "max_results": MAX_QUERY_TAKE + 1},
        {**advanced_request(), "return": []},
        {**advanced_request(), "return": ["id", "id"]},
        {**advanced_request(), "return": [" id"]},
        {
            **advanced_request(),
            "return": ["id"] * (MAX_ADVANCED_RETURN_EXPRESSIONS + 1),
        },
        {
            **advanced_request(),
            "return": ["x" * (MAX_ADVANCED_RETURN_EXPRESSION_BYTES + 1)],
        },
    ),
)
def test_advanced_query_rejects_contract_and_budget_drift(
    payload: dict[str, object],
) -> None:
    with pytest.raises(SemanticValidationError) as caught:
        build_advanced_object_get_query(payload)

    assert caught.value.error_code is SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


@pytest.mark.parametrize(
    "waql",
    (
        "$ from type Sound",
        "from type Sound\norderby name",
        "from type Sound; from type Event",
        "from type Sound // second query",
        "from type Sound /* comment */",
        'from search "unterminated',
        "from type Sound where name = /unterminated",
    ),
)
def test_advanced_query_rejects_ambiguous_query_frames(waql: str) -> None:
    with pytest.raises(SemanticValidationError):
        build_advanced_object_get_query(advanced_request(waql=waql))


def test_advanced_query_utf8_byte_limits_are_runtime_enforced() -> None:
    with pytest.raises(SemanticValidationError):
        build_advanced_object_get_query(
            advanced_request(waql="界" * (MAX_ADVANCED_WAQL_BYTES // 2))
        )


@pytest.mark.parametrize("version", VERSIONS)
def test_advanced_query_schema_is_closed_and_versioned(version: str) -> None:
    schema = advanced_query_schema(version=version)

    assert schema["$id"] == ADVANCED_QUERY_CONTRACT
    assert schema["x-wwise-version"] == version
    assert schema["x-limits"]["gateway_json_document_bytes"] == 256 * 1024
    assert schema["required"] == ["contract", "waql", "return", "max_results"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["return"]["uniqueItems"] is True
    assert schema["properties"]["waql"]["x-maxUtf8Bytes"] == MAX_ADVANCED_WAQL_BYTES
    assert schema["properties"]["waql"]["x-framing"] == {
        "singleLine": True,
        "queryEditorDollarPrefix": False,
        "comments": False,
        "statementSeparators": False,
        "balancedDoubleQuotedStrings": True,
        "balancedSlashRegexLiterals": True,
        "trailingWhitespace": "removed-before-final-take",
    }
    assert schema["properties"]["return"]["items"]["x-maxUtf8Bytes"] == (
        MAX_ADVANCED_RETURN_EXPRESSION_BYTES
    )
    assert schema["properties"]["return"]["items"]["x-framing"]["trimmed"] is True
    assert schema["properties"]["max_results"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": MAX_QUERY_TAKE,
        "description": (
            "Gateway-owned final row cap. It does not bound Wwise's "
            "internal scan or sort cost."
        ),
    }


@pytest.mark.parametrize("version", VERSIONS)
def test_five_version_golden_compiles_the_same_closed_query(version: str) -> None:
    checker = FakeSourceNoteChecker()
    preview = build_structured_object_get_query(
        request(
            source={"kind": "type", "types": ["Sound", "Event"]},
            transforms=[
                {
                    "kind": "where",
                    "predicate": {
                        "kind": "all",
                        "operands": [
                            {
                                "kind": "compare",
                                "path": ["type"],
                                "operator": "!=",
                                "value": "Project",
                            },
                            {
                                "kind": "any",
                                "operands": [
                                    {
                                        "kind": "compare",
                                        "path": ["@Volume"],
                                        "operator": "<=",
                                        "value": -6,
                                    },
                                    {
                                        "kind": "not",
                                        "operand": {
                                            "kind": "truthy",
                                            "path": ["isIncluded"],
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
                {"kind": "take", "value": 25},
            ],
            return_fields=["id", "name", "type", "path", "@Volume", "isIncluded"],
        ),
        version=version,
        source_note_checker=checker,
    )

    assert preview.dispatch_payload() == {
        "uri": "ak.wwise.core.object.get",
        "args": {
            "waql": (
                'from type Sound, Event where type != "Project" and '
                '(@Volume <= -6 or ! (isIncluded)) take 25'
            )
        },
        "options": {
            "return": ["id", "name", "type", "path", "@Volume", "isIncluded"]
        },
    }
    assert preview.envelope.metadata["query_contract"] == (
        STRUCTURED_QUERY_CONTRACT
    )
    assert preview.envelope.metadata["read_only"] is True
    assert preview.envelope.metadata["query_bound"] == {
        "mode": "take",
        "value": 25,
    }
    assert preview.envelope.metadata["exact_identity"] is None
    assert checker.calls == [("query", version)]


def test_all_and_project_sources_have_distinct_canonical_rendering() -> None:
    transforms = [
        {
            "kind": "where",
            "predicate": {
                "kind": "compare",
                "path": ["type"],
                "operator": "=",
                "value": "Sound",
            },
        },
        {"kind": "take", "value": 3},
    ]

    implicit = build_structured_object_get_query(
        request(source={"kind": "all"}, transforms=transforms)
    )
    explicit = build_structured_object_get_query(
        request(source={"kind": "project"}, transforms=transforms)
    )

    assert implicit.envelope.args == {
        "waql": 'where type = "Sound" take 3'
    }
    assert explicit.envelope.args == {
        "waql": 'from project where type = "Sound" take 3'
    }
    source_schema = structured_query_schema()["properties"]["source"]
    descriptions = str(source_schema)
    assert "implicit all-project source" in descriptions
    assert "explicit from project source" in descriptions


def test_object_search_and_query_editor_sources_are_closed_and_bounded() -> None:
    objects = build_structured_object_get_query(
        request(
            source={
                "kind": "object",
                "objects": [
                    {"kind": "id", "value": GUID_A},
                    {
                        "kind": "path",
                        "value": r"\Actor-Mixer Hierarchy\Default Work Unit\Leaf",
                    },
                ],
            },
            transforms=[{"kind": "take", "value": 2}],
        )
    )
    search = build_structured_object_get_query(
        request(
            source={"kind": "search", "text": r"footstep C:\Originals"},
            transforms=[{"kind": "take", "value": 4}],
        )
    )
    query = build_structured_object_get_query(
        request(
            source={
                "kind": "query",
                "object": {
                    "kind": "path",
                    "value": r"\Queries\Shared Queries\Review",
                },
            },
            transforms=[{"kind": "take", "value": 5}],
        )
    )

    assert objects.envelope.args == {
        "waql": (
            f'from object "{GUID_A}", '
            r'"\Actor-Mixer Hierarchy\Default Work Unit\Leaf" take 2'
        )
    }
    assert search.envelope.args == {
        "waql": r'from search "footstep C:\Originals" take 4'
    }
    assert query.envelope.args == {
        "waql": r'from query "\Queries\Shared Queries\Review" take 5'
    }


def test_ordered_select_where_select_and_take_are_preserved() -> None:
    preview = WaqlQueryBuilder().build(
        request(
            source={"kind": "type", "types": ["Event"]},
            transforms=[
                {
                    "kind": "select",
                    "expressions": [["children"]],
                },
                {
                    "kind": "where",
                    "predicate": {
                        "kind": "compare",
                        "path": ["type"],
                        "operator": "=",
                        "value": "Action",
                    },
                },
                {
                    "kind": "select",
                    "expressions": [["Target"], ["this"], ["descendants"]],
                },
                {"kind": "take", "value": 20},
            ],
        )
    )

    assert preview.envelope.args == {
        "waql": (
            'from type Event select children where type = "Action" '
            "select Target, this, descendants take 20"
        )
    }


def test_expression_paths_are_tokenized_and_empty_string_and_null_are_literals() -> None:
    preview = build_structured_object_get_query(
        request(
            transforms=[
                {
                    "kind": "where",
                    "predicate": {
                        "kind": "all",
                        "operands": [
                            {
                                "kind": "compare",
                                "path": ["parent", "name"],
                                "operator": ":",
                                "value": r"C:\Review",
                            },
                            {
                                "kind": "compare",
                                "path": ["contentHash"],
                                "operator": "!=",
                                "value": "",
                            },
                            {
                                "kind": "compare",
                                "path": ["@OutputBus"],
                                "operator": "!=",
                                "value": None,
                            },
                        ],
                    },
                }
            ],
        )
    )

    assert preview.envelope.args == {
        "waql": (
            r'from object "{11111111-1111-1111-1111-111111111111}" '
            r'where parent.name : "C:\Review" and contentHash != "" '
            r"and @OutputBus != null"
        )
    }


@pytest.mark.parametrize(
    "source",
    (
        {"kind": "all"},
        {"kind": "project"},
        {"kind": "type", "types": ["Sound"]},
        {"kind": "search", "text": "Tone"},
        {"kind": "query", "object": {"kind": "id", "value": GUID_A}},
        {
            "kind": "object",
            "objects": [
                {"kind": "id", "value": GUID_A},
                {"kind": "id", "value": GUID_B},
            ],
        },
    ),
)
def test_every_broad_source_requires_a_final_take(
    source: dict[str, object],
) -> None:
    with pytest.raises(SemanticValidationError, match="require a final take"):
        build_structured_object_get_query(request(source=source))


def test_single_exact_object_can_remain_untransformed_and_unbounded() -> None:
    preview = build_structured_object_get_query(request())

    assert preview.envelope.args == {"waql": f'from object "{GUID_A}"'}
    assert preview.envelope.metadata["query_bound"] == {
        "mode": "exact-object",
        "value": 1,
    }
    assert preview.envelope.metadata["exact_identity"] == {
        "kind": "id",
        "value": GUID_A,
    }


def test_select_is_expanding_and_take_must_be_unique_and_final() -> None:
    with pytest.raises(SemanticValidationError, match="require a final take"):
        build_structured_object_get_query(
            request(
                transforms=[
                    {"kind": "select", "expressions": [["parent"]]},
                ]
            )
        )

    with pytest.raises(SemanticValidationError, match="must be final"):
        build_structured_object_get_query(
            request(
                transforms=[
                    {"kind": "take", "value": 1},
                    {
                        "kind": "where",
                        "predicate": {"kind": "truthy", "path": ["isPlayable"]},
                    },
                ]
            )
        )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update({"waql": "from type Sound"}),
        lambda value: value["source"].update(
            {"raw": "from type Sound"}
        ),
        lambda value: value["transforms"].append(
            {"kind": "where", "expression": "type = Sound"}
        ),
        lambda value: value["transforms"].append(
            {
                "kind": "where",
                "predicate": {"kind": "raw", "value": "type = Sound"},
            }
        ),
    ),
)
def test_raw_expression_and_waql_escape_hatches_are_rejected(mutate) -> None:
    payload = request()
    mutate(payload)

    with pytest.raises(SemanticValidationError):
        build_structured_object_get_query(payload)


@pytest.mark.parametrize(
    "token",
    (
        'name) or type = "Sound"',
        "children.target",
        "children where true",
        "randomizer(\"Pitch\")",
        "@",
    ),
)
def test_expression_path_tokens_reject_query_splicing(token: str) -> None:
    with pytest.raises(SemanticValidationError, match="closed WAQL path token"):
        build_structured_object_get_query(
            request(
                transforms=[
                    {
                        "kind": "where",
                        "predicate": {"kind": "truthy", "path": [token]},
                    }
                ]
            )
        )


@pytest.mark.parametrize(
    "text",
    (
        'quoted " value',
        "line\nbreak",
        "separator\u2028break",
    ),
)
def test_string_literals_outside_the_packaged_quote_boundary_are_rejected(
    text: str,
) -> None:
    with pytest.raises(SemanticValidationError):
        build_structured_object_get_query(
            request(
                transforms=[
                    {
                        "kind": "where",
                        "predicate": {
                            "kind": "compare",
                            "path": ["name"],
                            "operator": "=",
                            "value": text,
                        },
                    }
                ]
            )
        )


def test_take_and_major_array_limits_fail_closed() -> None:
    invalid_payloads = [
        request(
            source={"kind": "type", "types": ["Sound"]},
            transforms=[{"kind": "take", "value": MAX_QUERY_TAKE + 1}],
        ),
        request(
            transforms=[
                {
                    "kind": "select",
                    "expressions": [
                        ["children"]
                        for _ in range(MAX_STRUCTURED_SELECT_EXPRESSIONS + 1)
                    ],
                },
                {"kind": "take", "value": 1},
            ]
        ),
        request(
            source={
                "kind": "object",
                "objects": [
                    {
                        "kind": "path",
                        "value": rf"\Actor-Mixer Hierarchy\Object{index}",
                    }
                    for index in range(MAX_STRUCTURED_SOURCE_ITEMS + 1)
                ],
            },
            transforms=[{"kind": "take", "value": 1}],
        ),
        request(
            transforms=[
                {
                    "kind": "where",
                    "predicate": {"kind": "truthy", "path": ["isPlayable"]},
                }
                for _ in range(MAX_STRUCTURED_TRANSFORMS + 1)
            ]
        ),
        request(
            return_fields=[
                f"field{index}"
                for index in range(MAX_STRUCTURED_RETURN_FIELDS + 1)
            ]
        ),
    ]

    for payload in invalid_payloads:
        with pytest.raises(SemanticValidationError):
            build_structured_object_get_query(payload)


def test_boolean_depth_string_length_and_document_node_limits_fail_closed() -> None:
    predicate: dict[str, object] = {
        "kind": "truthy",
        "path": ["isPlayable"],
    }
    for _ in range(MAX_STRUCTURED_BOOLEAN_DEPTH + 1):
        predicate = {"kind": "not", "operand": predicate}
    too_deep = request(
        transforms=[{"kind": "where", "predicate": predicate}]
    )
    too_long = request(
        transforms=[
            {
                "kind": "where",
                "predicate": {
                    "kind": "compare",
                    "path": ["name"],
                    "operator": "=",
                    "value": "x" * (MAX_STRUCTURED_LITERAL_LENGTH + 1),
                },
            }
        ]
    )
    too_many_nodes = request(
        transforms=[
            {
                "kind": "where",
                "predicate": {
                    "kind": "all",
                    "operands": [
                        {"kind": "truthy", "path": [f"field{index}"]}
                        for index in range(MAX_STRUCTURED_QUERY_NODES)
                    ],
                },
            }
        ]
    )

    for payload in (too_deep, too_long, too_many_nodes):
        with pytest.raises(SemanticValidationError):
            build_structured_object_get_query(payload)


def test_duplicate_source_return_and_select_values_are_rejected() -> None:
    invalid = [
        request(
            source={"kind": "type", "types": ["Sound", "Sound"]},
            transforms=[{"kind": "take", "value": 1}],
        ),
        request(return_fields=["id", "id"]),
        request(
            transforms=[
                {
                    "kind": "select",
                    "expressions": [["children"], ["children"]],
                },
                {"kind": "take", "value": 1},
            ]
        ),
    ]

    for payload in invalid:
        with pytest.raises(SemanticValidationError, match="duplicate"):
            build_structured_object_get_query(payload)


@pytest.mark.parametrize(
    "return_field",
    (
        "id, name",
        "parent.{id}",
        "name as displayName",
        'id) where type = "Sound"',
        "parent..id",
    ),
)
def test_return_fields_reject_raw_expressions_and_query_splicing(
    return_field: str,
) -> None:
    with pytest.raises(SemanticValidationError):
        build_structured_object_get_query(
            request(return_fields=["id", return_field])
        )


def test_schema_is_fresh_closed_recursive_and_contains_no_raw_waql_property() -> None:
    first = structured_query_schema()
    second = structured_query_schema()

    assert first == second
    assert first is not second
    assert first["$id"] == STRUCTURED_QUERY_CONTRACT
    assert first["additionalProperties"] is False
    assert first["x-limits"]["take"] == MAX_QUERY_TAKE
    assert first["x-limits"]["document_nodes"] == MAX_STRUCTURED_QUERY_NODES
    return_description = first["properties"]["return"]["items"]["description"]
    assert "closed dot-separated accessor path" in return_description
    assert "Raw return expressions" in return_description
    assert first["$defs"]["predicate"]["oneOf"]
    assert '"raw"' not in str(first)
    assert '"waql"' not in str(first)
    assert '"expression"' not in str(first)

    mutated = copy.deepcopy(first)
    mutated["title"] = "changed"
    assert structured_query_schema()["title"] != "changed"


def test_schema_and_runtime_share_closed_token_and_path_rules() -> None:
    schema = structured_query_schema()
    source_schema = schema["properties"]["source"]
    assert isinstance(source_schema, dict)

    type_branch = _schema_variant(source_schema, "type")
    type_properties = type_branch["properties"]
    assert isinstance(type_properties, dict)
    types_schema = type_properties["types"]
    assert isinstance(types_schema, dict)
    type_item_schema = types_schema["items"]
    assert isinstance(type_item_schema, dict)
    assert _schema_leaf_accepts(type_item_schema, "AudioFileSource")
    assert not _schema_leaf_accepts(type_item_schema, "Sound where true")
    build_structured_object_get_query(
        request(
            source={"kind": "type", "types": ["AudioFileSource"]},
            transforms=[{"kind": "take", "value": 1}],
        )
    )
    with pytest.raises(SemanticValidationError):
        build_structured_object_get_query(
            request(
                source={"kind": "type", "types": ["Sound where true"]},
                transforms=[{"kind": "take", "value": 1}],
            )
        )

    predicate_schema = schema["$defs"]["predicate"]
    assert isinstance(predicate_schema, dict)
    truthy_branch = _schema_variant(predicate_schema, "truthy")
    truthy_properties = truthy_branch["properties"]
    assert isinstance(truthy_properties, dict)
    path_schema = truthy_properties["path"]
    assert isinstance(path_schema, dict)
    expression_item_schema = path_schema["items"]
    assert isinstance(expression_item_schema, dict)
    assert _schema_leaf_accepts(expression_item_schema, "@Volume")
    assert not _schema_leaf_accepts(
        expression_item_schema,
        'name) or type = "Sound"',
    )
    build_structured_object_get_query(
        request(
            transforms=[
                {
                    "kind": "where",
                    "predicate": {"kind": "truthy", "path": ["@Volume"]},
                }
            ]
        )
    )
    with pytest.raises(SemanticValidationError):
        build_structured_object_get_query(
            request(
                transforms=[
                    {
                        "kind": "where",
                        "predicate": {
                            "kind": "truthy",
                            "path": ['name) or type = "Sound"'],
                        },
                    }
                ]
            )
        )

    return_schema = schema["properties"]["return"]["items"]
    assert isinstance(return_schema, dict)
    assert _schema_leaf_accepts(return_schema, "parent.id")
    assert not _schema_leaf_accepts(return_schema, "id, name")
    build_structured_object_get_query(request(return_fields=["parent.id"]))
    with pytest.raises(SemanticValidationError):
        build_structured_object_get_query(request(return_fields=["id, name"]))

    query_branch = _schema_variant(source_schema, "query")
    query_properties = query_branch["properties"]
    assert isinstance(query_properties, dict)
    query_identity_schema = query_properties["object"]
    assert isinstance(query_identity_schema, dict)
    query_path_branch = _schema_variant(query_identity_schema, "path")
    query_path_properties = query_path_branch["properties"]
    assert isinstance(query_path_properties, dict)
    query_path_schema = query_path_properties["value"]
    assert isinstance(query_path_schema, dict)
    valid_query_path = r"\Queries\Shared Queries\Review"
    invalid_query_path = r"\Events\Default Work Unit\Review"
    assert _schema_leaf_accepts(query_path_schema, valid_query_path)
    assert not _schema_leaf_accepts(query_path_schema, invalid_query_path)
    build_structured_object_get_query(
        request(
            source={
                "kind": "query",
                "object": {"kind": "path", "value": valid_query_path},
            },
            transforms=[{"kind": "take", "value": 1}],
        )
    )
    with pytest.raises(SemanticValidationError):
        build_structured_object_get_query(
            request(
                source={
                    "kind": "query",
                    "object": {"kind": "path", "value": invalid_query_path},
                },
                transforms=[{"kind": "take", "value": 1}],
            )
        )


@pytest.mark.parametrize(
    ("operator", "value", "accepted"),
    (
        ("=", "Dummy", True),
        ("!=", None, True),
        (":", "Play", True),
        ("<=", -6, True),
        (">", 3.5, True),
        (":", 3, False),
        (">", "3", False),
        ("<=", True, False),
        ("=", 'bad"literal', False),
        ("!=", " padded ", False),
    ),
)
def test_schema_and_runtime_agree_on_comparison_operator_value_pairs(
    operator: str,
    value: object,
    accepted: bool,
) -> None:
    schema = structured_query_schema()
    predicate_schema = schema["$defs"]["predicate"]
    assert isinstance(predicate_schema, dict)
    assert _comparison_schema_accepts(
        predicate_schema,
        operator=operator,
        value=value,
    ) is accepted

    payload = request(
        transforms=[
            {
                "kind": "where",
                "predicate": {
                    "kind": "compare",
                    "path": ["@Volume"],
                    "operator": operator,
                    "value": value,
                },
            }
        ]
    )
    if accepted:
        build_structured_object_get_query(payload)
    else:
        with pytest.raises(SemanticValidationError):
            build_structured_object_get_query(payload)


def test_contract_and_json_shape_errors_use_semantic_schema_mismatch() -> None:
    invalid = request()
    invalid["contract"] = "waapi-skill.object-query/v999"

    with pytest.raises(SemanticValidationError) as exc:
        build_structured_object_get_query(invalid)

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH

    with pytest.raises(SemanticValidationError):
        build_structured_object_get_query(["not", "an", "object"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "predicate",
    (
        {
            "kind": "compare",
            "path": ["notes"],
            "operator": ":",
            "value": 3,
        },
        {
            "kind": "compare",
            "path": ["childrenCount"],
            "operator": ">",
            "value": "3",
        },
    ),
)
def test_comparison_operator_literal_families_fail_closed(
    predicate: dict[str, object],
) -> None:
    with pytest.raises(SemanticValidationError):
        build_structured_object_get_query(
            request(
                transforms=[
                    {"kind": "where", "predicate": predicate},
                ]
            )
        )


def test_schema_records_requested_version_without_changing_the_contract() -> None:
    schema = structured_query_schema(version="2025.1")

    assert schema["$id"] == STRUCTURED_QUERY_CONTRACT
    assert schema["x-wwise-version"] == "2025.1"
