from __future__ import annotations

import inspect
import json
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from tests.semantic.support.codex_object_heavy_v3 import (
    OBJECT_CREATE_CASE_IDS,
    OBJECT_COMPOUND_CROSS_VERSION_CASE_IDS,
    OBJECT_GET_CASE_IDS,
    OBJECT_HEAVY_CASE_IDS,
    OBJECT_SET_CASE_IDS,
    MaterializedObject,
    ObjectHeavyRecipeError,
    OperationRequestSpec,
    QueryObjectRequestSpec,
    all_object_heavy_v3_recipes,
    build_object_heavy_v3_recipe,
)
from wwise_waapi.operation_registry import parse_operation_request


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_OBJECT_V3 = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "evals"
    / "online"
    / "2022.1"
    / "core_object.json"
)


def _prompts() -> dict[str, str]:
    payload = json.loads(CORE_OBJECT_V3.read_text(encoding="utf-8"))
    return {
        row["id"]: row["prompt"]
        for row in payload["cases"]
        if row["id"] in OBJECT_HEAVY_CASE_IDS
    }


def _walk(value: Any):
    yield value
    if is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            yield from _walk(getattr(value, item.name))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield key
            yield from _walk(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _walk(item)


def _walk_mapping_keys(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_mapping_keys(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _walk_mapping_keys(item)


def _rule_values(case_id: str, kind: str) -> dict[str, Any]:
    recipe = build_object_heavy_v3_recipe(case_id)
    rule = next(item for item in recipe.oracle.rules if item.kind == kind)
    return dict(rule.expected)


def test_all_fifteen_object_heavy_ids_build_deterministically() -> None:
    recipes = all_object_heavy_v3_recipes()

    assert tuple(item.scenario_id for item in recipes) == OBJECT_HEAVY_CASE_IDS
    assert len(recipes) == 15
    assert len({item.digest for item in recipes}) == 15
    assert all(len(item.digest) == 64 for item in recipes)
    for recipe in recipes:
        rebuilt = build_object_heavy_v3_recipe(recipe.scenario_id)
        assert rebuilt is recipe
        assert rebuilt.digest == recipe.digest

    with pytest.raises(ObjectHeavyRecipeError, match="unknown object-heavy V3 scenario"):
        build_object_heavy_v3_recipe("OBJ22-F-GET-99")


def test_every_agent_visible_literal_is_grounded_in_the_approved_prompt() -> None:
    prompts = _prompts()

    assert set(prompts) == set(OBJECT_HEAVY_CASE_IDS)
    for recipe in all_object_heavy_v3_recipes():
        prompt = prompts[recipe.scenario_id]
        assert recipe.prompt_literals
        assert all(literal in prompt for literal in recipe.prompt_literals)


def test_object_create_prompt_type_labels_map_to_every_approved_request_token() -> None:
    prompts = _prompts()
    natural_type_tokens = {
        "Actor Mixer": "ActorMixer",
        "随机容器": "RandomSequenceContainer",
        "混合容器": "BlendContainer",
        "Sound": "Sound",
    }

    def collect_types(node: Mapping[str, Any]) -> set[str]:
        tokens = {str(node["type"])}
        for child in node.get("children", []):
            assert isinstance(child, Mapping)
            tokens.update(collect_types(child))
        return tokens

    request_tokens: set[str] = set()
    prompt_labels: set[str] = set()
    for case_id in OBJECT_CREATE_CASE_IDS:
        recipe = build_object_heavy_v3_recipe(case_id)
        assert isinstance(recipe.request, OperationRequestSpec)
        arguments = recipe.request.as_dict()["arguments"]
        assert isinstance(arguments, Mapping)
        request_tokens.update(collect_types(arguments))
        prompt_labels.update(label for label in natural_type_tokens if label in prompts[case_id])

    assert prompt_labels == set(natural_type_tokens)
    assert request_tokens == set(natural_type_tokens.values())


def test_mutation_requests_parse_through_the_production_closed_contract() -> None:
    expected_conflicts = {
        "OBJ22-F-CREATE-01": "fail",
        "OBJ22-F-CREATE-02": "merge",
        "OBJ22-F-CREATE-03": "rename",
        "OBJ22-F-CREATE-04": "fail",
        "OBJ22-F-CREATE-05": "replace",
        "OBJ22-F-SET-01": "fail",
        "OBJ22-F-SET-02": "fail",
        "OBJ22-F-SET-03": "fail",
        "OBJ22-F-SET-04": "fail",
        "OBJ22-F-SET-05": "rename",
    }

    for case_id, expected_conflict in expected_conflicts.items():
        recipe = build_object_heavy_v3_recipe(case_id)
        assert isinstance(recipe.request, OperationRequestSpec)
        payload = recipe.request.as_dict()
        parsed = parse_operation_request(payload)
        assert parsed.version == "2022.1"
        assert parsed.operation == recipe.request.operation
        assert parsed.arguments["on_name_conflict"] == expected_conflict
        assert json.loads(recipe.request.canonical_json()) == payload

    replace = build_object_heavy_v3_recipe("OBJ22-F-CREATE-05").request
    assert isinstance(replace, OperationRequestSpec)
    assert replace.as_dict()["arguments"] == {
        "parent": {
            "kind": "path",
            "value": r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Generated",
        },
        "type": "ActorMixer",
        "name": "Prototype_Footsteps",
        "notes": "新脚步原型",
        "children": [
            {
                "type": "RandomSequenceContainer",
                "name": name,
                "children": [
                    {"type": "Sound", "name": "Walk"},
                    {"type": "Sound", "name": "Run"},
                ],
            }
            for name in ("Sneakers", "Boots", "Barefoot")
        ],
        "on_name_conflict": "replace",
        "replace_owned_root": {
            "kind": "path",
            "value": r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Generated",
        },
    }


@pytest.mark.parametrize("case_id", OBJECT_COMPOUND_CROSS_VERSION_CASE_IDS)
def test_compound_object_recipe_translates_paths_and_reflected_types_for_2025(
    case_id: str,
) -> None:
    old = build_object_heavy_v3_recipe(case_id)
    new = build_object_heavy_v3_recipe(case_id, "2025.1")

    assert old.version == "2022.1"
    assert new.version == "2025.1"
    assert new is build_object_heavy_v3_recipe(case_id, "2025.1")
    assert new.digest != old.digest
    assert all(
        not (
            isinstance(value, str)
            and value.startswith(
                (r"\Actor-Mixer Hierarchy", r"\Master-Mixer Hierarchy")
            )
        )
        for value in _walk(new)
    )
    assert all(
        item.path.startswith(r"\Containers\Default Work Unit\SemanticLab")
        for item in new.fixture.objects
    )
    old_fixture = {item.key: item for item in old.fixture.objects}
    new_fixture = {item.key: item for item in new.fixture.objects}
    assert {
        key
        for key, item in new_fixture.items()
        if item.object_type == "PropertyContainer"
    } == {
        key
        for key, item in old_fixture.items()
        if item.object_type == "ActorMixer"
    }
    assert all(
        item.object_type != "ActorMixer" for item in new.oracle.expected_objects
    )

    assert isinstance(new.request, OperationRequestSpec)
    payload = new.request.as_dict(version=new.version)
    parsed = parse_operation_request(payload)
    assert parsed.version == "2025.1"
    assert parsed.operation == new.request.operation
    assert json.loads(
        new.request.canonical_json(version=new.version)
    ) == payload
    if new.api.endswith(".create"):
        assert payload["arguments"]["type"] == "ActorMixer"


def test_unreviewed_object_cases_and_layout_versions_fail_closed() -> None:
    with pytest.raises(ObjectHeavyRecipeError, match="not approved"):
        build_object_heavy_v3_recipe("OBJ22-F-GET-01", "2025.1")
    with pytest.raises(ObjectHeavyRecipeError, match="unsupported"):
        build_object_heavy_v3_recipe("OBJ22-F-CREATE-02", "2024.1")


def test_set_03_uses_raw_pitch_cents_and_exact_bus_references() -> None:
    recipe = build_object_heavy_v3_recipe("OBJ22-F-SET-03")
    assert isinstance(recipe.request, OperationRequestSpec)
    request_objects = recipe.request.as_dict()["arguments"]["objects"]

    assert [
        next(field["value"] for field in row["properties"] if field["name"] == "Pitch")
        for row in request_objects
    ] == [100, -100, -200]
    assert [
        row["references"][0]["target"]["value"] for row in request_objects
    ] == [
        r"\Master-Mixer Hierarchy\Default Work Unit\Ambience_Bus",
        r"\Master-Mixer Hierarchy\Default Work Unit\Ambience_Bus",
        r"\Master-Mixer Hierarchy\Default Work Unit\Weather_Bus",
    ]
    expected = {item.key: item for item in recipe.oracle.expected_objects}
    assert [
        next(field.value for field in expected[key].fields if field.name == "@Pitch")
        for key in ("day", "night", "storm")
    ] == [100, -100, -200]


def test_set_04_targets_existing_roots_and_footsteps_without_merge() -> None:
    recipe = build_object_heavy_v3_recipe("OBJ22-F-SET-04")
    assert isinstance(recipe.request, OperationRequestSpec)

    assert recipe.request.as_dict()["arguments"] == {
        "objects": [
            {
                "object": {
                    "kind": "path",
                    "value": r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Foley\Player",
                },
                "notes": "玩家 Foley",
                "properties": [{"name": "Volume", "value": -1.0}],
                "children": [
                    {
                        "type": "RandomSequenceContainer",
                        "name": "Cloth",
                        "children": [
                            {"type": "Sound", "name": "Cloth_Light"},
                            {"type": "Sound", "name": "Cloth_Heavy"},
                        ],
                    }
                ],
            },
            {
                "object": {
                    "kind": "path",
                    "value": r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Foley\Player\Footsteps",
                },
                "children": [{"type": "Sound", "name": "Walk_B"}],
            },
            {
                "object": {
                    "kind": "path",
                    "value": r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Foley\NPC",
                },
                "notes": "NPC Foley",
                "properties": [{"name": "Volume", "value": -3.0}],
                "children": [
                    {
                        "type": "RandomSequenceContainer",
                        "name": "Armor",
                        "children": [
                            {"type": "Sound", "name": "Armor_Light"},
                            {"type": "Sound", "name": "Armor_Heavy"},
                        ],
                    }
                ],
            },
            {
                "object": {
                    "kind": "path",
                    "value": r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Foley\NPC\Footsteps",
                },
                "children": [{"type": "Sound", "name": "Walk_B"}],
            },
        ],
        "on_name_conflict": "fail",
    }


def test_every_get_is_one_bounded_query_object_with_closed_return_fields() -> None:
    expected_takes = {
        "OBJ22-F-GET-01": 24,
        "OBJ22-F-GET-02": 24,
        "OBJ22-F-GET-03": 12,
        "OBJ22-F-GET-04": 10,
        "OBJ22-F-GET-05": 8,
    }
    required_fields = {
        "OBJ22-F-GET-01": {"id", "name", "type", "path", "@Volume", "notes", "OutputBus"},
        "OBJ22-F-GET-02": {"id", "name", "type", "path", "parent", "audioSource:language", "@Volume", "notes"},
        "OBJ22-F-GET-03": {"id", "name", "type", "path", "@Volume", "notes", "audioSource:language", "isIncluded", "OutputBus"},
        "OBJ22-F-GET-04": {"id", "name", "type", "path", "childrenCount", "notes", "OutputBus"},
        "OBJ22-F-GET-05": {"id", "name", "type", "path", "childrenCount", "notes"},
    }

    for case_id in OBJECT_GET_CASE_IDS:
        recipe = build_object_heavy_v3_recipe(case_id)
        assert isinstance(recipe.request, QueryObjectRequestSpec)
        request = recipe.request
        assert request.argv[:4] == ("gateway.py", "--version", "2022.1", "query-object")
        assert request.argv.count("query-object") == 1
        assert request.argv.count("--take") == 1
        assert request.take == expected_takes[case_id]
        assert request.argv[request.argv.index("--take") + 1] == str(request.take)
        assert set(request.return_fields) == required_fields[case_id]
        assert "--all-results" not in request.argv
        assert "--args-json" not in request.argv
        assert "--options-json" not in request.argv
        assert request.exact_expected_keys == recipe.oracle.exact_row_keys


def test_get_01_and_get_02_expose_bounded_supersets_but_hide_exact_rows() -> None:
    get_01 = build_object_heavy_v3_recipe("OBJ22-F-GET-01")
    get_02 = build_object_heavy_v3_recipe("OBJ22-F-GET-02")
    get_02_prompt = _prompts()["OBJ22-F-GET-02"]
    assert "每个直接子 Sound 单独一行" in get_02_prompt
    assert "父容器和子 Sound 各自的完整路径" in get_02_prompt
    assert isinstance(get_01.request, QueryObjectRequestSpec)
    assert isinstance(get_02.request, QueryObjectRequestSpec)

    for recipe in (get_01, get_02):
        request = recipe.request
        assert request.result_strategy == "bounded_superset_final_answer_filter"
        assert set(request.exact_expected_keys) < set(request.bounded_superset_keys)
        assert request.final_filter.combine != "identity"
        assert set(recipe.oracle.excluded_keys) == (
            set(request.bounded_superset_keys) - set(request.exact_expected_keys)
        )
        assert any(rule.kind == "final_answer_filters_superset" for rule in recipe.oracle.rules)

    assert get_01.request.final_filter.required[0].operator == "relative_depth_at_most"
    assert get_01.request.final_filter.required[0].value == 3
    assert {item.operator for item in get_01.request.final_filter.any_of} == {
        "less_than",
        "contains",
    }
    assert "depth_four_match" in get_01.request.bounded_superset_keys
    assert "depth_four_match" in get_01.oracle.excluded_keys
    assert "depth_four_match" not in get_01.oracle.exact_row_keys

    assert {item.operator for item in get_02.request.final_filter.any_of} == {
        "is_vo_random_container",
        "is_direct_sound_child_of_vo_container",
    }
    assert {"hero_nested_line", "vox_parent", "music_parent", "vo_wrong_type"} <= set(
        get_02.oracle.excluded_keys
    )
    assert get_02.oracle.exact_row_keys == (
        "vo_hero",
        "hero_damage",
        "hero_greeting",
        "vo_npc",
        "npc_alert",
        "npc_idle",
    )


def test_get_03_through_get_05_have_exact_rows_limits_and_decoy_oracles() -> None:
    for case_id in ("OBJ22-F-GET-03", "OBJ22-F-GET-04", "OBJ22-F-GET-05"):
        recipe = build_object_heavy_v3_recipe(case_id)
        assert isinstance(recipe.request, QueryObjectRequestSpec)
        assert recipe.request.result_strategy == "exact_rows"
        assert recipe.request.bounded_superset_keys == recipe.request.exact_expected_keys
        assert recipe.request.final_filter.combine == "identity"
        assert recipe.oracle.excluded_keys
        assert set(recipe.oracle.excluded_keys).isdisjoint(recipe.oracle.exact_row_keys)
        assert any(rule.kind == "query_rows_exact" for rule in recipe.oracle.rules)
        assert any(rule.kind == "bound_reached_equal" for rule in recipe.oracle.rules)

    get_03 = build_object_heavy_v3_recipe("OBJ22-F-GET-03")
    assert get_03.request.return_fields == (
        "id",
        "name",
        "type",
        "path",
        "@Volume",
        "notes",
        "audioSource:language",
        "OutputBus",
        "isIncluded",
    )
    assert len(get_03.oracle.exact_row_keys) == 8
    assert len(get_03.oracle.excluded_keys) == 8
    assert _rule_values("OBJ22-F-GET-03", "answer_counts_equal") == {
        "q3_bus_a": 5,
        "q3_bus_b": 3,
        "total": 8,
    }
    q3_by_key = {item.key: item for item in get_03.fixture.objects}
    assert q3_by_key["q3_decoy_type"].object_type == "ActorMixer"
    assert q3_by_key["q3_combat"].object_type == "ActorMixer"
    assert q3_by_key["q3_decoy_type"].path.rsplit("\\", 1)[0] == q3_by_key["q3_combat"].path

    get_04 = build_object_heavy_v3_recipe("OBJ22-F-GET-04")
    assert get_04.oracle.exact_row_keys == ("q4_pistol", "q4_rifle", "q4_shotgun")
    assert get_04.request.primary_row_policy == "parent_projection_per_source_row"
    assert get_04.request.final_answer_policy == "deduplicated_parent_summary"
    assert _rule_values("OBJ22-F-GET-04", "answer_counts_equal") == {
        "unique_parents": 3,
        "returned_sound_edges": 10,
        "direct_child_objects": 12,
        "fixture_eligible_sound_edges": 12,
    }
    assert _rule_values("OBJ22-F-GET-04", "bound_reached_equal") == {
        "take": 10,
        "reached": True,
    }

    get_05 = build_object_heavy_v3_recipe("OBJ22-F-GET-05")
    assert get_05.request.primary_row_policy == "ancestor_identity_rows"
    assert get_05.request.final_answer_policy == "ordered_ancestor_summary"
    assert get_05.oracle.expected_order_keys == (
        "q5_movement",
        "q5_player",
        "q5_root",
        "actor_dwu",
        "actor_root",
    )
    assert _rule_values("OBJ22-F-GET-05", "answer_counts_equal") == {
        "RandomSequenceContainer": 1,
        "ActorMixer": 2,
        "WorkUnit": 2,
        "Default Work Unit": 1,
    }


def test_fixtures_oracles_and_cleanup_are_closed_under_owned_project_copies() -> None:
    for recipe in all_object_heavy_v3_recipes():
        fixture_keys = {item.key for item in recipe.fixture.objects}
        fixture_paths = {item.path for item in recipe.fixture.objects}
        assert len(fixture_keys) == len(recipe.fixture.objects)
        assert len(fixture_paths) == len(recipe.fixture.objects)
        assert not fixture_paths.intersection(recipe.fixture.absent_paths)
        assert recipe.fixture.materialization_policy == "runner_direct_waapi_then_seal_before_codex"
        assert recipe.cleanup.owned_object_roots
        assert recipe.cleanup.success_policy == "close_wwise_and_delete_scenario_project_copy"
        assert recipe.cleanup.failure_policy == "seal_quarantine_and_never_reuse_scenario_project_copy"

        allowed_roots = (
            *recipe.cleanup.owned_object_roots,
            *recipe.cleanup.protected_object_roots,
        )
        for item in recipe.fixture.objects:
            if item.role != "borrowed":
                assert any(
                    item.path == root or item.path.startswith(root + "\\")
                    for root in allowed_roots
                ), (recipe.scenario_id, item.key, item.path, allowed_roots)
            assert all(reference.target_key in fixture_keys for reference in item.references)

        expected_keys = {item.key for item in recipe.oracle.expected_objects}
        assert set(recipe.oracle.new_keys) <= expected_keys
        assert set(recipe.oracle.preserved_keys) <= fixture_keys
        assert set(recipe.oracle.protected_snapshot_keys) <= fixture_keys


def test_object_heavy_fixtures_do_not_seed_actor_mixers_below_random_containers() -> None:
    for recipe in all_object_heavy_v3_recipes():
        by_path = {item.path: item for item in recipe.fixture.objects}
        for child in recipe.fixture.objects:
            parent = by_path.get(child.path.rsplit("\\", 1)[0])
            if parent is None:
                continue
            assert not (
                parent.object_type == "RandomSequenceContainer"
                and child.object_type == "ActorMixer"
            ), f"{recipe.scenario_id}: invalid {parent.key} -> {child.key} fixture edge"


def test_materialized_object_contract_has_every_hidden_oracle_binding_field() -> None:
    assert tuple(item.name for item in fields(MaterializedObject)) == (
        "key",
        "id",
        "name",
        "type",
        "path",
        "parent_id",
        "notes",
        "properties",
        "references",
        "source_language",
        "is_included",
        "children_count",
        "active_source_id",
        "active_source_name",
        "active_source_path",
    )


def test_public_builder_accepts_no_code_callback_or_command_extension() -> None:
    assert tuple(inspect.signature(build_object_heavy_v3_recipe).parameters) == (
        "scenario_id",
        "version",
    )
    assert not inspect.signature(build_object_heavy_v3_recipe).parameters[
        "scenario_id"
    ].kind == inspect.Parameter.VAR_KEYWORD

    forbidden_keys = {"callback", "script", "code", "hook", "command", "custom"}
    shell_fragments = (";", "&&", "||", "|", "`", "$(", "\n", "\r")
    for recipe in all_object_heavy_v3_recipes():
        assert all(not callable(value) for value in _walk(recipe))
        assert "no_model_authored_code" in recipe.model_policy
        assert "no_temporary_script" in recipe.model_policy
        assert "no_arbitrary_callback_or_command_hook" in recipe.model_policy
        if isinstance(recipe.request, OperationRequestSpec):
            payload = recipe.request.as_dict()
            for key in _walk_mapping_keys(payload):
                normalized = key.casefold().replace("-", "_")
                assert not any(fragment in normalized for fragment in forbidden_keys)
        else:
            assert isinstance(recipe.request, QueryObjectRequestSpec)
            assert "python" not in recipe.request.argv
            assert "python3" not in recipe.request.argv
            assert all(
                fragment not in argument
                for argument in recipe.request.argv
                for fragment in shell_fragments
            )


def test_operation_arguments_are_deeply_immutable() -> None:
    recipe = build_object_heavy_v3_recipe("OBJ22-F-CREATE-01")
    assert isinstance(recipe.request, OperationRequestSpec)

    with pytest.raises(TypeError):
        recipe.request.arguments["name"] = "Injected"  # type: ignore[index]
    children = recipe.request.arguments["children"]
    assert isinstance(children, tuple)
    assert isinstance(children[0], Mapping)
    with pytest.raises(TypeError):
        children[0]["name"] = "Injected"  # type: ignore[index]
