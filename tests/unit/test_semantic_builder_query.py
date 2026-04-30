from __future__ import annotations

import json

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticErrorCode,
    SemanticValidationError,
    SourceNoteCheck,
)
from wwise_waapi.builders.query import QueryPredicate, build_object_get_query  # pyright: ignore[reportMissingImports]


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
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\A \"Quoted\" Sound",
        select="descendants",
        where={"field": "name", "operator": ":", "value": "Tone*"},
        take=1,
        return_fields=["id", "name", "path"],
        source_note_checker=checker,
    )
    assert path_preview.dispatch_payload()["args"] == {
        "waql": '"\\\\Actor-Mixer Hierarchy\\\\Default Work Unit\\\\A \\\\\\"Quoted\\\\\\" Sound" select descendants where name : "Tone*" take 1'
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

    with pytest.raises(SemanticValidationError) as select:
        build_object_get_query(type="Sound", select="children", return_fields=("id",), source_note_checker=checker)
    assert select.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_source_note_is_required_before_preview() -> None:
    checker = FakeSourceNoteChecker(SourceNoteCheck(False, "query", reason="missing", error_code=SemanticErrorCode.MISSING_SOURCE_NOTE))

    with pytest.raises(SemanticValidationError) as exc:
        build_object_get_query(type="Sound", return_fields=("id",), source_note_checker=checker)

    assert exc.value.error_code == SemanticErrorCode.MISSING_SOURCE_NOTE
    assert checker.calls == [("query", "2022.1")]
