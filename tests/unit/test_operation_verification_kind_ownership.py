from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "wwise_waapi"
    / "operation_registry.py"
)
LEGACY_PREPARED_PREVIEW_KIND_FIXTURES = {
    "created-guid-present": {
        (
            "tests/unit/test_operation_registry.py",
            "_legacy_created_guid_present_prepared_preview_compatibility_fixture",
        )
    },
    "audio-import-created-objects": {
        (
            "tests/unit/test_operation_registry.py",
            "_legacy_audio_import_created_objects_prepared_preview_compatibility_fixture",
        )
    },
}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _enclosing_function(
    node: ast.AST,
    *,
    parents: dict[ast.AST, ast.AST],
) -> str | None:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
            return current.name
        current = parents.get(current)
    return None


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1, {"function": name, "matches": matches}
    return matches[0]


def _called_function_names(node: ast.AST) -> set[str]:
    return {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }


def _public_operation_branch_calls(
    prepare_function: ast.FunctionDef,
    operation: str,
) -> set[str]:
    matching_branches: list[ast.If] = []
    for node in ast.walk(prepare_function):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Attribute)
            and isinstance(test.left.value, ast.Name)
            and test.left.value.id == "request"
            and test.left.attr == "operation"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == operation
        ):
            matching_branches.append(node)
    assert len(matching_branches) == 1, {
        "operation": operation,
        "matching_branch_lines": [node.lineno for node in matching_branches],
    }
    return {
        function_name
        for statement in matching_branches[0].body
        for function_name in _called_function_names(statement)
    }


def _literal_kind_functions(tree: ast.Module, kind: str) -> set[str | None]:
    parents = _parent_map(tree)
    return {
        _enclosing_function(node, parents=parents)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == kind
    }


def _dict_kind_sites(
    tree: ast.Module,
    kinds: Iterable[str],
) -> dict[str, list[tuple[str | None, int]]]:
    requested = set(kinds)
    parents = _parent_map(tree)
    sites = {kind: [] for kind in requested}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if (
                isinstance(key, ast.Constant)
                and key.value == "kind"
                and isinstance(value, ast.Constant)
                and value.value in requested
            ):
                sites[str(value.value)].append(
                    (_enclosing_function(value, parents=parents), value.lineno)
                )
    return sites


def _test_literal_sites(kind: str) -> set[tuple[str, str | None]]:
    sites: set[tuple[str, str | None]] = set()
    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        if path.resolve() == Path(__file__).resolve():
            continue
        tree = _parse(path)
        parents = _parent_map(tree)
        relative = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == kind:
                sites.add((relative, _enclosing_function(node, parents=parents)))
    return sites


def test_public_operation_producers_own_the_current_verification_kinds() -> None:
    tree = _parse(REGISTRY_PATH)
    prepare = _function(tree, "prepare_operation")

    assert "_prepare_object_create" in _public_operation_branch_calls(
        prepare,
        "object.create",
    )
    assert "_prepare_audio_import" in _public_operation_branch_calls(
        prepare,
        "audio.import",
    )
    assert "_prepare_audio_import_tab_delimited" in _public_operation_branch_calls(
        prepare,
        "audio.importTabDelimited",
    )
    assert "_prepare_closed_import_plan" in _called_function_names(
        _function(tree, "_prepare_audio_import")
    )
    assert "_prepare_closed_import_plan" in _called_function_names(
        _function(tree, "_prepare_audio_import_tab_delimited")
    )

    kind_sites = _dict_kind_sites(
        tree,
        {
            "object-create-graph",
            "closed-audio-import",
            *LEGACY_PREPARED_PREVIEW_KIND_FIXTURES,
        },
    )
    assert {function for function, _line in kind_sites["object-create-graph"]} == {
        "_prepare_object_create"
    }
    assert len(kind_sites["object-create-graph"]) == 2
    assert {
        function for function, _line in kind_sites["closed-audio-import"]
    } == {"_prepare_closed_import_plan"}
    assert len(kind_sites["closed-audio-import"]) == 1
    assert kind_sites["created-guid-present"] == []
    assert kind_sites["audio-import-created-objects"] == []


def test_legacy_verification_kinds_are_verifier_only_and_fixture_allowlisted() -> None:
    registry_tree = _parse(REGISTRY_PATH)
    for kind, expected_fixture_sites in LEGACY_PREPARED_PREVIEW_KIND_FIXTURES.items():
        assert _literal_kind_functions(registry_tree, kind) == {
            "verify_prepared_operation"
        }
        assert _test_literal_sites(kind) == expected_fixture_sites
