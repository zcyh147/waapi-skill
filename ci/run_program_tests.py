from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
PROGRAM_PYTEST_ARGS = (
    "-m",
    "not live and not destructive",
    "--ignore=tests/semantic",
    "--ignore=tests/live",
    "--ignore=tests/destructive",
)
PROGRAM_PYTEST_OPTIONS_REQUIRING_VALUE = frozenset(
    {"-k", "--maxfail", "--tb", "--color", "--durations", "--capture"}
)


class ProgramManifestError(ValueError):
    """Raised when the fixed program-gate manifest is unsafe or malformed."""


class ProgramPytestArgsError(ValueError):
    """Raised when caller arguments could widen the fixed program gate."""


def load_program_nodes(manifest_path: Path, *, repo_root: Path = REPO_ROOT) -> list[str]:
    try:
        lines = manifest_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ProgramManifestError(f"cannot read {manifest_path}: {exc}") from exc

    try:
        unit_root = (repo_root / "tests" / "unit").resolve(strict=True)
    except OSError as exc:
        raise ProgramManifestError(f"cannot resolve tests/unit below {repo_root}: {exc}") from exc

    nodes: list[str] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line or line.startswith("#"):
            continue
        if any(character.isspace() for character in line):
            raise ProgramManifestError(
                f"line {line_number} contains whitespace instead of one pytest node"
            )

        test_path = line.split("::", 1)[0]
        path_parts = test_path.split("/")
        if (
            not line.startswith("tests/unit/")
            or "\\" in line
            or any(part in {"", ".", ".."} for part in path_parts)
        ):
            raise ProgramManifestError(
                f"line {line_number} is outside the tests/unit boundary: {line}"
            )
        candidate = repo_root / test_path
        try:
            resolved_candidate = candidate.resolve(strict=True)
            resolved_candidate.relative_to(unit_root)
        except (OSError, ValueError) as exc:
            raise ProgramManifestError(
                f"line {line_number} names a missing or escaping test file: {test_path}"
            ) from exc
        if not resolved_candidate.is_file():
            raise ProgramManifestError(f"line {line_number} is not a test file: {test_path}")
        if line in seen:
            raise ProgramManifestError(f"line {line_number} duplicates a pytest node: {line}")

        seen.add(line)
        nodes.append(line)

    if not nodes:
        raise ProgramManifestError(f"contains no pytest nodes: {manifest_path}")
    return nodes


def validate_program_pytest_args(arguments: Sequence[str]) -> list[str]:
    """Return exact pytest arguments after rejecting collection-widening inputs."""

    validated = list(arguments)
    expects_value_for: str | None = None
    for argument in validated:
        if expects_value_for is not None:
            expects_value_for = None
            continue
        if argument in PROGRAM_PYTEST_OPTIONS_REQUIRING_VALUE:
            expects_value_for = argument
            continue
        if argument == "--pyargs" or argument.startswith("--pyargs="):
            raise ProgramPytestArgsError(f"program mode does not allow --pyargs: {argument}")
        if argument.startswith("-"):
            continue
        raise ProgramPytestArgsError(
            "program mode accepts pytest flags and filter values, "
            f"not additional test paths: {argument}"
        )

    if expects_value_for is not None:
        raise ProgramPytestArgsError(
            "program mode received a pytest option without its required value: "
            f"{expects_value_for}"
        )
    return validated


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print("usage: run_program_tests.py <manifest> [pytest args...]", file=sys.stderr)
        return 2

    try:
        nodes = load_program_nodes(Path(arguments[0]))
    except ProgramManifestError as exc:
        print(f"program test manifest error: {exc}", file=sys.stderr)
        return 2
    try:
        pytest_arguments = validate_program_pytest_args(arguments[1:])
    except ProgramPytestArgsError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    import pytest

    return int(pytest.main([*nodes, *PROGRAM_PYTEST_ARGS, *pytest_arguments]))


if __name__ == "__main__":
    raise SystemExit(main())
