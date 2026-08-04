from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_LANE_ROOTS = (
    REPO_ROOT / "tests" / "live",
    REPO_ROOT / "tests" / "destructive",
)


@dataclass(frozen=True, slots=True)
class _AssertionNameViolation:
    path: Path
    line: int
    column: int

    def render(self) -> str:
        return f"{self.path.relative_to(REPO_ROOT)}:{self.line}:{self.column + 1}"


def _constant_string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _key_receiver(node: ast.AST, key: str) -> ast.AST | None:
    if isinstance(node, ast.Subscript) and _constant_string(node.slice) == key:
        return node.value
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and _constant_string(node.args[0]) == key
    ):
        return node.func.value
    return None


def _contains_key_access(node: ast.AST, key: str) -> bool:
    return any(_key_receiver(candidate, key) is not None for candidate in ast.walk(node))


def _verification_like(
    node: ast.AST,
    verification_names: set[str] | None = None,
) -> bool:
    if isinstance(node, ast.Name):
        normalized = node.id.casefold()
        if (
            node.id in (verification_names or set())
            or "verification" in normalized
            or normalized == "verified"
        ):
            return True
    return _contains_key_access(node, "verification")


def _target_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.List, ast.Tuple)):
        return {
            name
            for element in node.elts
            for name in _target_names(element)
        }
    return set()


def _function_scope_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    nodes: list[ast.AST] = []

    class ScopeVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            if node is function:
                for statement in node.body:
                    self.visit(statement)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            if node is function:
                for statement in node.body:
                    self.visit(statement)

        def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
            return

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            return

        def generic_visit(self, node: ast.AST) -> None:
            nodes.append(node)
            super().generic_visit(node)

    ScopeVisitor().visit(function)
    return nodes


def _assigned_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {name for target in targets for name in _target_names(target)}
    return set()


def _assignment_value(node: ast.AST) -> ast.AST | None:
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
        return node.value
    return None


def _assertion_collection_expression(
    node: ast.AST,
    collection_names: set[str],
    verification_names: set[str],
) -> bool:
    if isinstance(node, ast.Name) and node.id in collection_names:
        return True
    receiver = _key_receiver(node, "assertions")
    return receiver is not None and _verification_like(receiver, verification_names)


def _assertion_item_expression(
    node: ast.AST,
    *,
    collection_names: set[str],
    item_names: set[str],
    verification_names: set[str],
) -> bool:
    if isinstance(node, ast.Name):
        return node.id in item_names
    if isinstance(node, ast.Subscript):
        return _assertion_collection_expression(
            node.value,
            collection_names,
            verification_names,
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "next":
        return bool(
            node.args
            and isinstance(node.args[0], (ast.GeneratorExp, ast.ListComp))
            and any(
                _assertion_collection_expression(
                    generator.iter,
                    collection_names,
                    verification_names,
                )
                for generator in node.args[0].generators
            )
        )
    return False


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id.casefold()
    if isinstance(node.func, ast.Attribute):
        return node.func.attr.casefold()
    return ""


def _call_outsources_assertion_name_selection(
    node: ast.AST,
    *,
    collection_names: set[str],
    verification_names: set[str],
) -> bool:
    if not isinstance(node, ast.Call):
        return False
    arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
    if not any(_constant_string(argument) is not None for argument in arguments):
        return False
    if any(
        _assertion_collection_expression(
            argument,
            collection_names,
            verification_names,
        )
        for argument in arguments
    ):
        return True
    normalized_name = _call_name(node)
    return (
        "assertion" in normalized_name or "verifier" in normalized_name
    ) and any(
        _verification_like(argument, verification_names) for argument in arguments
    )


def _function_assertion_name_violations(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    path: Path,
) -> list[_AssertionNameViolation]:
    nodes = _function_scope_nodes(function)
    positional_parameters = [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]
    verification_names = {
        parameter.arg
        for parameter in positional_parameters
        if "verification" in parameter.arg.casefold()
        or parameter.arg.casefold() == "verified"
    }
    changed = True
    while changed:
        changed = False
        for node in nodes:
            value = _assignment_value(node)
            if value is None or not _verification_like(value, verification_names):
                continue
            for name in _assigned_names(node).difference(verification_names):
                verification_names.add(name)
                changed = True

    collection_names = {
        parameter.arg
        for parameter in positional_parameters
        if parameter.arg.casefold() == "assertions"
        or parameter.arg.casefold().endswith("_assertions")
    }

    changed = True
    while changed:
        changed = False
        for node in nodes:
            value = _assignment_value(node)
            if value is None or not _assertion_collection_expression(
                value,
                collection_names,
                verification_names,
            ):
                continue
            for name in _assigned_names(node).difference(collection_names):
                collection_names.add(name)
                changed = True

    item_names: set[str] = set()
    for node in nodes:
        if isinstance(node, (ast.For, ast.AsyncFor)) and _assertion_collection_expression(
            node.iter,
            collection_names,
            verification_names,
        ):
            item_names.update(_target_names(node.target))
        if isinstance(node, ast.comprehension) and _assertion_collection_expression(
            node.iter,
            collection_names,
            verification_names,
        ):
            item_names.update(_target_names(node.target))

    changed = True
    while changed:
        changed = False
        for node in nodes:
            value = _assignment_value(node)
            if value is None or not _assertion_item_expression(
                value,
                collection_names=collection_names,
                item_names=item_names,
                verification_names=verification_names,
            ):
                continue
            for name in _assigned_names(node).difference(item_names):
                item_names.add(name)
                changed = True

    violations: list[_AssertionNameViolation] = []
    seen: set[tuple[int, int]] = set()
    for node in nodes:
        receiver = _key_receiver(node, "name")
        local_name_selection = receiver is not None and _assertion_item_expression(
            receiver,
            collection_names=collection_names,
            item_names=item_names,
            verification_names=verification_names,
        )
        outsourced_name_selection = _call_outsources_assertion_name_selection(
            node,
            collection_names=collection_names,
            verification_names=verification_names,
        )
        if not local_name_selection and not outsourced_name_selection:
            continue
        identity = (node.lineno, node.col_offset)
        if identity in seen:
            continue
        seen.add(identity)
        violations.append(
            _AssertionNameViolation(
                path=path,
                line=node.lineno,
                column=node.col_offset,
            )
        )
    return violations


def _source_assertion_name_violations(
    source: str,
    *,
    path: Path,
) -> list[_AssertionNameViolation]:
    tree = ast.parse(source, filename=str(path))
    return [
        violation
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for violation in _function_assertion_name_violations(node, path=path)
    ]


def test_real_lanes_do_not_select_transaction_verifier_assertions_by_name() -> None:
    violations = [
        violation
        for root in REAL_LANE_ROOTS
        for path in sorted(root.rglob("*.py"))
        for violation in _source_assertion_name_violations(
            path.read_text(encoding="utf-8"),
            path=path,
        )
    ]

    assert not violations, (
        "live/destructive tests must use structured business results or readbacks, "
        "not verifier assertion display names:\n"
        + "\n".join(violation.render() for violation in violations)
    )


@pytest.mark.parametrize(
    "source",
    (
        """
def direct(verified):
    return next(
        item
        for item in verified["verification"]["assertions"]
        if item["name"] == "display text"
    )
""",
        """
def extracted(verification_evidence):
    assertions = verification_evidence.get("assertions")
    return [item for item in assertions if item.get("name") == "display text"]
""",
        """
def helper(assertions, expected_name):
    return [row for row in assertions if row["name"] == expected_name]
""",
        """
def imported_helper(verification_evidence):
    return select_verifier_assertion(verification_evidence, "display text")
""",
        """
def aliased(payload):
    evidence = payload["verification"]
    checks = evidence["assertions"]
    return [row for row in checks if row["name"] == "display text"]
""",
    ),
)
def test_policy_rejects_verifier_assertion_name_selection(source: str) -> None:
    assert _source_assertion_name_violations(
        source,
        path=REPO_ROOT / "tests" / "destructive" / "synthetic.py",
    )


def test_policy_allows_pass_aggregation_and_unrelated_business_names() -> None:
    source = """
def allowed(verified, rows, case):
    assert all(
        item["passed"] is True
        for item in verified["verification"]["assertions"]
    )
    object_names = [row["name"] for row in rows]
    case_assertion_names = [row["name"] for row in case["assertions"]]
    return object_names, case_assertion_names
"""

    assert _source_assertion_name_violations(
        source,
        path=REPO_ROOT / "tests" / "live" / "synthetic.py",
    ) == []
