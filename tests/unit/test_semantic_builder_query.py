from __future__ import annotations

import json

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticErrorCode,
    SemanticValidationError,
    SourceNoteCheck,
)
from wwise_waapi.builders.query import (  # pyright: ignore[reportMissingImports]
    MAX_QUERY_TAKE,
    QueryPredicate,
    build_object_get_query,
)


class FakeSourceNoteChecker:
    def __init__(self, status: SourceNoteCheck | None = None) -> None:
        self.status = status or SourceNoteCheck(True, BuilderFamily.QUERY.value, cited_fields=("waql", "options.return"))
        self.calls: list[tuple[str, str]] = []

    def check(self, family: str, version: str = "2022.1") -> SourceNoteCheck:
        self.calls.append((family, version))
        return self.status


def test_sound_volume_query_envelope() -> None:
    checker = FakeSourceNoteChecker()

    preview = build_object_get_query(
        type="Sound",
        where=QueryPredicate("@Volume", "<", 0),
        return_fields=("id", "name", "path", "@Volume"),
        source_note_checker=checker,
    )

    assert preview.dispatch_payload() == {
        "uri": "ak.wwise.core.object.get",
        "args": {"waql": "from type Sound where @Volume < 0"},
        "options": {"return": ["id", "name", "path", "@Volume"]},
    }
    assert preview.source_note_family == "query"
    assert preview.requires_destructive_gate is False
    assert preview.raw_dispatch_allowed is False
    assert checker.calls == [("query", "2022.1")]
    assert preview.readback_plan[0].as_dict() == {
        "uri": "ak.wwise.core.object.get",
        "args": {"waql": "from type Sound where @Volume < 0"},
        "options": {"return": ["id", "name", "path", "@Volume"]},
        "description": "read back WAQL object discovery rows requested by caller",
    }
    assert preview.envelope.metadata["read_only"] is True


def test_path_guid_search_query_select_take_and_returns_are_compiled() -> None:
    checker = FakeSourceNoteChecker()

    path_preview = build_object_get_query(
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\A Sound",
        select="descendants",
        where={"field": "name", "operator": ":", "value": "Tone*"},
        take=1,
        return_fields=["id", "name", "path"],
        source_note_checker=checker,
    )
    assert path_preview.dispatch_payload()["args"] == {
        "waql": r'from object "\Actor-Mixer Hierarchy\Default Work Unit\A Sound" select descendants where name : "Tone*" take 1'
    }
    assert json.dumps(path_preview.dispatch_payload(), sort_keys=True)

    guid_preview = build_object_get_query(
        object_id="{11111111-1111-1111-1111-111111111111}",
        select=["ancestors", "referencesTo"],
        return_fields=("id",),
        source_note_checker=checker,
    )
    assert guid_preview.dispatch_payload()["args"] == {
        "waql": 'from object "{11111111-1111-1111-1111-111111111111}" select ancestors select referencesTo'
    }

    search_preview = build_object_get_query(search="Default Work Unit", return_fields=("id", "name"), source_note_checker=checker)
    assert search_preview.dispatch_payload()["args"] == {"waql": 'from search "Default Work Unit"'}

    query_preview = build_object_get_query(query="{22222222-2222-2222-2222-222222222222}", return_fields=("id",), source_note_checker=checker)
    assert query_preview.dispatch_payload()["args"] == {"waql": 'from query "{22222222-2222-2222-2222-222222222222}"'}

    query_path_preview = build_object_get_query(
        query=r"\Queries\Shared Queries\Events With Play Actions",
        return_fields=("id", "name"),
        source_note_checker=checker,
    )
    assert query_path_preview.dispatch_payload()["args"] == {
        "waql": r'from query "\Queries\Shared Queries\Events With Play Actions"'
    }

    with pytest.raises(SemanticValidationError) as quoted:
        build_object_get_query(
            path=r'\Actor-Mixer Hierarchy\A "Quoted" Sound',
            return_fields=("id",),
            source_note_checker=checker,
        )
    assert quoted.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert quoted.value.details["boundary"] == "canonical-wwise-object-path"


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_exact_path_uses_standard_from_object_with_single_separators(version: str) -> None:
    preview = build_object_get_query(
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Leaf",
        return_fields=("id", "name", "type", "path"),
        source_note_checker=FakeSourceNoteChecker(),
        version=version,
    )

    assert preview.dispatch_payload() == {
        "uri": "ak.wwise.core.object.get",
        "args": {"waql": r'from object "\Actor-Mixer Hierarchy\Default Work Unit\Leaf"'},
        "options": {"return": ["id", "name", "type", "path"]},
    }
    assert preview.readback_plan[0].args == preview.envelope.args


@pytest.mark.parametrize(
    "kwargs",
    (
        {"path": r"Actor-Mixer Hierarchy\Leaf"},
        {"path": r"\\Actor-Mixer Hierarchy\\Leaf"},
        {"path": "\\Actor-Mixer Hierarchy\nLeaf"},
        {"object_id": "11111111-1111-1111-1111-111111111111"},
        {"object_id": "{not-a-guid}"},
        {"object_id": 123},
    ),
)
def test_exact_object_sources_require_canonical_path_or_guid(kwargs: dict[str, object]) -> None:
    with pytest.raises(SemanticValidationError) as exc:
        build_object_get_query(
            **kwargs,  # type: ignore[arg-type]
            return_fields=("id",),
            source_note_checker=FakeSourceNoteChecker(),
        )

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


@pytest.mark.parametrize(
    "kwargs",
    (
        {"type": 3},
        {"search": 3},
        {"query": 3},
    ),
)
def test_query_sources_reject_non_string_runtime_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(SemanticValidationError):
        build_object_get_query(
            **kwargs,  # type: ignore[arg-type]
            return_fields=("id",),
            source_note_checker=FakeSourceNoteChecker(),
        )


def test_return_fields_rejects_bare_string_sequence() -> None:
    with pytest.raises(SemanticValidationError) as exc:
        build_object_get_query(
            type="Sound",
            return_fields="id",  # type: ignore[arg-type]
            source_note_checker=FakeSourceNoteChecker(),
        )

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_name_type_category_and_documented_property_predicates() -> None:
    preview = build_object_get_query(
        type="Sound",
        where=(
            {"field": "name", "operator": "=", "value": "Tone"},
            {"field": "type", "operator": "=", "value": "Sound"},
            {"field": "category", "operator": "!=", "value": "Events"},
            {"field": "childrenCount", "operator": ">=", "value": 0},
            {"field": "isIncluded", "operator": "=", "value": True},
        ),
        return_fields=("id", "name"),
        source_note_checker=FakeSourceNoteChecker(),
    )

    assert preview.dispatch_payload()["args"] == {
        "waql": 'from type Sound where name = "Tone" and type = "Sound" and category != "Events" and childrenCount >= 0 and isIncluded = true'
    }
    assert preview.dispatch_payload()["options"] == {"return": ["id", "name"]}


@pytest.mark.parametrize(
    "where",
    (
        {"field": "name", "operator": "=", "value": "Tone", "unexpected": True},
        {"field": "childrenCount", "operator": ">", "value": float("nan")},
        {"field": "childrenCount", "operator": ">", "value": float("inf")},
        "field=name",
    ),
)
def test_where_predicates_reject_extra_fields_nonfinite_numbers_and_nonobjects(where: object) -> None:
    with pytest.raises(SemanticValidationError) as exc:
        build_object_get_query(
            type="Sound",
            where=where,  # type: ignore[arg-type]
            return_fields=("id",),
            source_note_checker=FakeSourceNoteChecker(),
        )

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_mutating_or_legacy_query_shape_rejected() -> None:
    checker = FakeSourceNoteChecker()

    with pytest.raises(SemanticValidationError) as legacy_from:
        build_object_get_query(from_={"ofType": ["Sound"]}, return_fields=("id",), source_note_checker=checker)  # type: ignore[call-arg]
    assert legacy_from.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert legacy_from.value.details["unknown_keys"] == ["from_"]

    with pytest.raises(SemanticValidationError) as legacy_transform:
        build_object_get_query(type="Sound", transform=[{"select": ["children"]}], return_fields=("id",), source_note_checker=checker)
    assert legacy_transform.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert legacy_transform.value.details["legacy_keys"] == ["transform"]

    with pytest.raises(SemanticValidationError) as mutating:
        build_object_get_query(type="delete", return_fields=("id",), source_note_checker=checker)
    assert mutating.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert mutating.value.details["mutating_words"] == ["delete"]


def test_missing_return_fields_and_unsupported_semantics_fail_closed() -> None:
    checker = FakeSourceNoteChecker()

    with pytest.raises(SemanticValidationError) as missing_return:
        build_object_get_query(type="Sound", source_note_checker=checker)
    assert missing_return.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH

    with pytest.raises(SemanticValidationError) as operator:
        build_object_get_query(type="Sound", where={"field": "name", "operator": "like", "value": "Tone"}, return_fields=("id",), source_note_checker=checker)
    assert operator.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert operator.value.details["operator"] == "like"

    with pytest.raises(SemanticValidationError) as accessor:
        build_object_get_query(type="Sound", where={"field": "unknownAccessor", "operator": "=", "value": "x"}, return_fields=("id",), source_note_checker=checker)
    assert accessor.value.error_code == SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED
    assert accessor.value.details["accessor"] == "unknownAccessor"

    for supported_select in ("children", "parent"):
        preview = build_object_get_query(
            type="Sound",
            select=supported_select,
            return_fields=("id",),
            source_note_checker=checker,
        )
        assert preview.dispatch_payload()["args"] == {
            "waql": f"from type Sound select {supported_select}"
        }

    for unsupported_select in ("this", "owner"):
        with pytest.raises(SemanticValidationError) as select:
            build_object_get_query(
                type="Sound",
                select=unsupported_select,
                return_fields=("id",),
                source_note_checker=checker,
            )
        assert select.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
        assert select.value.details["select"] == unsupported_select


@pytest.mark.parametrize(
    "query",
    (
        "from type Sound",
        "22222222-2222-2222-2222-222222222222",
        "{22222222-2222-2222-2222-222222222222} trailing",
        r"\Events\Default Work Unit",
        r"\\Queries\Shared Query",
        r"\Queries\\Shared Query",
        r"\Queries\Shared/Query",
        "\\Queries\\",
        '\\Queries\\A "Quoted" Query',
        "\\Queries\\Line\nBreak",
        "\\Queries\\Delete\u2028Line",
    ),
)
def test_query_source_rejects_raw_waql_and_noncanonical_object_specifiers(query: str) -> None:
    with pytest.raises(SemanticValidationError) as exc:
        build_object_get_query(
            query=query,
            return_fields=("id",),
            source_note_checker=FakeSourceNoteChecker(),
        )

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["boundary"] == "query-editor-object-specifier"
    assert "raw WAQL is not accepted" in str(exc.value)


@pytest.mark.parametrize("where", (3, True, 3.5))
def test_where_rejects_scalar_json_with_structured_semantic_error(where: object) -> None:
    with pytest.raises(SemanticValidationError) as exc:
        build_object_get_query(
            type="Sound",
            where=where,  # type: ignore[arg-type]
            return_fields=("id",),
            source_note_checker=FakeSourceNoteChecker(),
        )

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["where_type"] == type(where).__name__


def test_query_take_has_a_hard_maximum_but_boundary_value_is_valid() -> None:
    preview = build_object_get_query(
        type="Sound",
        take=MAX_QUERY_TAKE,
        return_fields=("id",),
        source_note_checker=FakeSourceNoteChecker(),
    )
    assert preview.envelope.args == {"waql": f"from type Sound take {MAX_QUERY_TAKE}"}

    with pytest.raises(SemanticValidationError) as exc:
        build_object_get_query(
            type="Sound",
            take=MAX_QUERY_TAKE + 1,
            return_fields=("id",),
            source_note_checker=FakeSourceNoteChecker(),
        )
    assert exc.value.details == {
        "take": MAX_QUERY_TAKE + 1,
        "minimum": 0,
        "maximum": MAX_QUERY_TAKE,
    }


def test_read_only_literals_may_contain_mutation_words_without_false_rejection() -> None:
    preview = build_object_get_query(
        search="please delete this old sound",
        where={"field": "name", "operator": "=", "value": "move then rename"},
        take=1,
        return_fields=("id",),
        source_note_checker=FakeSourceNoteChecker(),
    )

    assert preview.envelope.args == {
        "waql": (
            'from search "please delete this old sound" '
            'where name = "move then rename" take 1'
        )
    }


def test_source_note_is_required_before_preview() -> None:
    checker = FakeSourceNoteChecker(SourceNoteCheck(False, "query", reason="missing", error_code=SemanticErrorCode.MISSING_SOURCE_NOTE))

    with pytest.raises(SemanticValidationError) as exc:
        build_object_get_query(type="Sound", return_fields=("id",), source_note_checker=checker)

    assert exc.value.error_code == SemanticErrorCode.MISSING_SOURCE_NOTE
    assert checker.calls == [("query", "2022.1")]
