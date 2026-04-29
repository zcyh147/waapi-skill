from __future__ import annotations

import re
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.waql import (  # pyright: ignore[reportMissingImports]
    WAQL_EXAMPLES,
    validate_stored_waql_examples,
    validate_waql_example,
)


FIXTURE_OBJECTS = (
    {
        "id": "sound-1",
        "name": "MyTone",
        "type": "Sound",
        "category": "Actor-Mixer Hierarchy",
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\MyTone",
        "parent": "actor-root",
        "@Volume": -3,
    },
    {
        "id": "sound-2",
        "name": "OtherSound",
        "type": "Sound",
        "category": "Actor-Mixer Hierarchy",
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\OtherSound",
        "parent": "actor-root",
        "@Volume": 2,
    },
    {
        "id": "event-1",
        "name": "Play_Tone",
        "type": "Event",
        "category": "Events",
        "path": r"\Events\Default Work Unit\Play_Tone",
        "parent": "event-root",
    },
    {
        "id": "actor-root",
        "name": "Actor-Mixer Hierarchy",
        "type": "Folder",
        "category": "Actor-Mixer Hierarchy",
        "path": r"\Actor-Mixer Hierarchy",
        "parent": None,
    },
)


class FakeWaqlExecutor:
    def __init__(self, objects: tuple[Mapping[str, Any], ...]) -> None:
        self.objects = objects

    def execute(self, example: Mapping[str, Any]) -> list[dict[str, Any]]:
        validate_waql_example(example)
        waql = example["args"]["waql"]
        rows = list(self.objects)
        if waql.startswith("from type "):
            rows = self._from_type(rows, waql)
        elif waql.startswith("from search "):
            rows = self._from_search(rows, waql)
        elif waql.startswith('"\\Actor-Mixer Hierarchy"'):
            rows = [row for row in rows if row.get("path", "").startswith("\\Actor-Mixer Hierarchy\\")]
        else:
            raise AssertionError(f"Unsupported fixture WAQL: {waql}")

        rows = self._where(rows, waql)
        return_fields = example["options"]["return"]
        return [{field: row[field] for field in return_fields if field in row} for row in rows]

    def _from_type(self, rows: list[Mapping[str, Any]], waql: str) -> list[Mapping[str, Any]]:
        object_type = waql.split("from type ", 1)[1].split(" ", 1)[0]
        return [row for row in rows if str(row.get("type", "")).lower() == object_type.lower()]

    def _from_search(self, rows: list[Mapping[str, Any]], waql: str) -> list[Mapping[str, Any]]:
        token = waql.split('"', 2)[1].lower()
        return [row for row in rows if token in str(row.get("name", "")).lower()]

    def _where(self, rows: list[Mapping[str, Any]], waql: str) -> list[Mapping[str, Any]]:
        if 'where category = "Actor-Mixer Hierarchy"' in waql:
            rows = [row for row in rows if row.get("category") == "Actor-Mixer Hierarchy"]
        if "where @Volume < 0" in waql:
            rows = [row for row in rows if row.get("@Volume", 0) < 0]
        if "where name = /^My/" in waql:
            rows = [row for row in rows if re.match(r"^My", str(row.get("name", "")))]
        return rows


def test_stored_examples_are_valid_and_live_safe() -> None:
    validate_stored_waql_examples()

    assert {example["name"] for example in WAQL_EXAMPLES} == {
        "sounds_by_type",
        "tone_actor_mixer_search",
        "actor_mixer_descendant_regex",
        "negative_sound_volume",
    }
    assert all(example["expect_live_safe"] is True for example in WAQL_EXAMPLES)


@pytest.mark.parametrize("example", WAQL_EXAMPLES, ids=lambda example: example["name"])
def test_stored_examples_execute_against_fake_fixture(example: Mapping[str, Any]) -> None:
    result = FakeWaqlExecutor(FIXTURE_OBJECTS).execute(example)

    assert result
    assert all(set(row) <= set(example["options"]["return"]) for row in result)


def test_examples_have_deterministic_expected_results() -> None:
    executor = FakeWaqlExecutor(FIXTURE_OBJECTS)
    by_name = {example["name"]: executor.execute(example) for example in WAQL_EXAMPLES}

    assert by_name["sounds_by_type"] == [
        {"id": "sound-1", "name": "MyTone", "type": "Sound"},
        {"id": "sound-2", "name": "OtherSound", "type": "Sound"},
    ]
    assert by_name["tone_actor_mixer_search"] == [
        {"id": "sound-1", "name": "MyTone", "path": r"\Actor-Mixer Hierarchy\Default Work Unit\MyTone"}
    ]
    assert by_name["actor_mixer_descendant_regex"] == [
        {"id": "sound-1", "name": "MyTone", "path": r"\Actor-Mixer Hierarchy\Default Work Unit\MyTone"}
    ]
    assert by_name["negative_sound_volume"] == [{"id": "sound-1", "name": "MyTone", "@Volume": -3}]


def test_mutating_or_badly_shaped_examples_are_rejected() -> None:
    with pytest.raises(ValueError, match="read-only"):
        validate_waql_example(
            {
                "name": "bad",
                "uri": "ak.wwise.core.object.get",
                "args": {"waql": "from type Sound delete"},
                "options": {"return": ["id"]},
                "expect_live_safe": True,
            }
        )
    with pytest.raises(ValueError, match="options.return"):
        validate_waql_example(
            {
                "name": "bad",
                "uri": "ak.wwise.core.object.get",
                "args": {"waql": "from type Sound"},
                "options": {"return": []},
                "expect_live_safe": True,
            }
        )
