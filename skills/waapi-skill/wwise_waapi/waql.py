"""Fail-closed WAQL resource gate and read-only runtime examples."""

from __future__ import annotations

import json

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

WAQL_API_URI = "ak.wwise.core.object.get"
DEFAULT_WAQL_REFERENCE = Path("resources/waql/2022.1/object-get-examples.json")
REQUIRED_WAQL_REFERENCE_METADATA = ("name", "uri", "schema_source", "reference")

WAQL_EXAMPLES: tuple[dict[str, Any], ...] = (
    {
        "name": "sounds_by_type",
        "uri": WAQL_API_URI,
        "args": {"waql": "from type Sound"},
        "options": {"return": ["id", "name", "type"]},
        "expect_live_safe": True,
    },
    {
        "name": "tone_actor_mixer_search",
        "uri": WAQL_API_URI,
        "args": {"waql": 'from search "Tone" where category = "Actor-Mixer Hierarchy"'},
        "options": {"return": ["id", "name", "path"]},
        "expect_live_safe": True,
    },
    {
        "name": "actor_mixer_descendant_regex",
        "uri": WAQL_API_URI,
        "args": {"waql": '"\\Actor-Mixer Hierarchy" select descendants where name = /^My/'},
        "options": {"return": ["id", "name", "path"]},
        "expect_live_safe": True,
    },
    {
        "name": "negative_sound_volume",
        "uri": WAQL_API_URI,
        "args": {"waql": "from type Sound where @Volume < 0"},
        "options": {"return": ["id", "name", "@Volume"]},
        "expect_live_safe": True,
    },
)


@dataclass(slots=True, frozen=True)
class WaqlReferenceStatus:
    """Result of validating source-grounded WAQL reference notes."""

    allowed: bool
    reason: str
    reference_path: Path
    missing: tuple[str, ...] = ()


class WaqlReferenceGate:
    """Validate packaged WAQL resources before helper generation."""

    def __init__(self, reference_path: Path = DEFAULT_WAQL_REFERENCE) -> None:
        self.reference_path = reference_path

    def check(self) -> WaqlReferenceStatus:
        if not self.reference_path.exists():
            return WaqlReferenceStatus(False, "WAQL resource evidence is missing.", self.reference_path)
        try:
            payload = json.loads(self.reference_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return WaqlReferenceStatus(False, f"WAQL resource evidence could not be read: {exc}", self.reference_path)

        try:
            validate_waql_reference(payload)
            validate_stored_waql_examples()
        except ValueError as exc:
            return WaqlReferenceStatus(False, f"WAQL resource evidence is incomplete: {exc}", self.reference_path)

        return WaqlReferenceStatus(True, "WAQL resource evidence is present.", self.reference_path)


def waql_matrix_path(version: str) -> Path:
    """Return the packaged WAQL runtime example resource for a Wwise version."""

    return Path("resources") / "waql" / version / "object-get-examples.json"


def waql_api_uris(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    """Return reflected API URIs whose schema exposes a WAQL argument."""

    uris: list[str] = []
    for entry in manifest.get("schemas", []):
        if not isinstance(entry, Mapping):
            continue
        uri = entry.get("uri")
        schema = entry.get("schema")
        if not isinstance(uri, str) or not isinstance(schema, Mapping):
            continue
        args = schema.get("argsSchema")
        if not isinstance(args, Mapping):
            continue
        properties = args.get("properties")
        if isinstance(properties, Mapping) and "waql" in properties:
            uris.append(uri)
    return tuple(sorted(set(uris)))


def require_waql_helper_generation(
    manifest: Mapping[str, Any],
    reference_path: Path = DEFAULT_WAQL_REFERENCE,
) -> tuple[str, ...]:
    """Return WAQL APIs only when packaged WAQL evidence is complete."""

    uris = waql_api_uris(manifest)
    if not uris:
        return ()
    status = WaqlReferenceGate(reference_path).check()
    if not status.allowed:
        details = f" Missing: {', '.join(status.missing)}." if status.missing else ""
        raise RuntimeError(f"WAQL helper generation blocked: {status.reason}{details}")
    return uris


def validate_waql_example(example: Mapping[str, Any]) -> None:
    """Validate that a stored WAQL example is read-only and WAAPI-shaped."""

    if example.get("uri") != WAQL_API_URI:
        raise ValueError("WAQL examples must use ak.wwise.core.object.get")
    args = example.get("args")
    if not isinstance(args, Mapping):
        raise ValueError("WAQL example args must be a mapping")
    waql = args.get("waql")
    if not isinstance(waql, str) or not waql.strip():
        raise ValueError("WAQL example must include a non-empty waql string")
    if _looks_mutating(waql):
        raise ValueError("WAQL example must be read-only")
    options = example.get("options")
    if not isinstance(options, Mapping):
        raise ValueError("WAQL example options must be a mapping")
    returns = options.get("return")
    if not isinstance(returns, list) or not returns or not all(isinstance(item, str) for item in returns):
        raise ValueError("WAQL example options.return must be a non-empty string list")
    if example.get("expect_live_safe") is not True:
        raise ValueError("WAQL example must be marked live-safe")


def validate_stored_waql_examples(examples: tuple[Mapping[str, Any], ...] = WAQL_EXAMPLES) -> None:
    """Validate every stored read-only WAQL example."""

    names: set[str] = set()
    for example in examples:
        name = example.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("WAQL example must include a name")
        if name in names:
            raise ValueError(f"Duplicate WAQL example name: {name}")
        names.add(name)
        validate_waql_example(example)


def validate_waql_reference(matrix: Mapping[str, Any]) -> None:
    """Validate the packaged runtime WAQL example resource."""

    metadata = matrix.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("WAQL reference metadata must be a mapping")
    for key in REQUIRED_WAQL_REFERENCE_METADATA:
        if key not in metadata:
            raise ValueError(f"WAQL reference metadata is missing {key}")
    if metadata.get("uri") != WAQL_API_URI:
        raise ValueError("WAQL reference metadata must target ak.wwise.core.object.get")

    examples = matrix.get("examples")
    if not isinstance(examples, list) or not examples:
        raise ValueError("WAQL reference examples must be a non-empty list")

    for case in examples:
        if not isinstance(case, Mapping):
            raise ValueError("WAQL reference example must be a mapping")
        synthesized = {
            "name": case.get("id"),
            "uri": case.get("uri"),
            "args": case.get("args"),
            "options": case.get("options"),
            "expect_live_safe": True,
        }
        validate_waql_example(synthesized)
        if case.get("no_mutation") is not True:
            raise ValueError("WAQL examples must remain read-only")
        sources = case.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError("WAQL examples must include source references")
        if not all(isinstance(source, str) for source in sources):
            raise ValueError("WAQL example sources must be strings")


def validate_waql_live_matrix(matrix: Mapping[str, Any]) -> None:
    """Validate a test-only live WAQL matrix fixture."""

    metadata = matrix.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("WAQL matrix metadata must be a mapping")
    for key in REQUIRED_WAQL_REFERENCE_METADATA:
        if key not in metadata:
            raise ValueError(f"WAQL matrix metadata is missing {key}")
    if metadata.get("uri") != WAQL_API_URI:
        raise ValueError("WAQL matrix metadata must target ak.wwise.core.object.get")

    live_cases = matrix.get("live_cases")
    if not isinstance(live_cases, list) or not live_cases:
        raise ValueError("WAQL matrix live_cases must be a non-empty list")

    validate_waql_reference({"metadata": metadata, "examples": live_cases})


def _looks_mutating(waql: str) -> bool:
    lowered = waql.lower()
    mutating_words = (" set ", " delete ", " create ", " import ", " move ", " rename ")
    padded = f" {lowered} "
    return any(word in padded for word in mutating_words)
