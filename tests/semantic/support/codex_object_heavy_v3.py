"""Closed runner-owned recipes for the reviewed object-heavy cases.

The declarative V3 suite describes natural prompts and business assertions.  A
real fresh-Codex campaign additionally needs deterministic fixture state, one
closed packaged request, hidden expected rows, and scenario-owned cleanup.
This module supplies that missing data without starting Codex or Wwise.

The surface is intentionally data-only:

* callers select one of fifteen reviewed scenario IDs;
* mutation cases expose an immutable ``object.create`` or ``object.set``
  operation request;
* read cases expose exactly one bounded ``query-object`` argv;
* fixture GUIDs remain symbolic keys until a trusted runner materializes and
  seals the real objects; and
* no caller-provided code, command hook, callback, or direct WAAPI client is
  accepted.

GET-01 and GET-02 deliberately use small bounded supersets because the current
packaged query builder cannot express their OR/depth and compound parent-child
conditions in one exact query.  Their exact final rows and closed semantic
filters remain hidden from the evaluated model.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass, replace
from types import MappingProxyType
from typing import Any, Literal, TypeAlias

from tests.semantic.support.codex_version_layout_v3 import (
    CodexVersionLayoutError,
    CodexVersionLayoutV3,
    get_codex_version_layout_v3,
)


VERSION = "2022.1"
COMPOUND_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
OBJECT_CREATE_URI = "ak.wwise.core.object.create"
OBJECT_GET_URI = "ak.wwise.core.object.get"
OBJECT_SET_URI = "ak.wwise.core.object.set"
OBJECT_HEAVY_RECIPE_CONTRACT = "waapi-skill.codex-object-heavy-recipe/v3"

_BASE_LAYOUT = get_codex_version_layout_v3(VERSION)
ACTOR_DWU = _BASE_LAYOUT.containers_dwu
ACTOR_ROOT = _BASE_LAYOUT.containers_root
MASTER_DWU = _BASE_LAYOUT.busses_dwu
SEMANTIC_LAB = ACTOR_DWU + r"\SemanticLab"

OBJECT_CREATE_CASE_IDS = tuple(f"OBJ22-F-CREATE-{index:02d}" for index in range(1, 6))
OBJECT_GET_CASE_IDS = tuple(f"OBJ22-F-GET-{index:02d}" for index in range(1, 6))
OBJECT_SET_CASE_IDS = tuple(f"OBJ22-F-SET-{index:02d}" for index in range(1, 6))
OBJECT_HEAVY_CASE_IDS = OBJECT_CREATE_CASE_IDS + OBJECT_GET_CASE_IDS + OBJECT_SET_CASE_IDS
OBJECT_COMPOUND_CROSS_VERSION_CASE_VERSIONS = MappingProxyType(
    {
        "OBJ22-F-GET-01": ("2021.1",),
        "OBJ22-F-GET-02": ("2023.1",),
        "OBJ22-F-CREATE-02": ("2021.1", "2025.1"),
        "OBJ22-F-CREATE-03": ("2023.1", "2025.1"),
        "OBJ22-F-SET-01": ("2024.1", "2025.1"),
        "OBJ22-F-SET-02": ("2025.1",),
    }
)
OBJECT_COMPOUND_CROSS_VERSION_CASE_IDS = tuple(
    OBJECT_COMPOUND_CROSS_VERSION_CASE_VERSIONS
)

Scalar: TypeAlias = str | int | float | bool | None
FrozenJSON: TypeAlias = Scalar | tuple["FrozenJSON", ...] | Mapping[str, "FrozenJSON"]
FixtureRole: TypeAlias = Literal["owned", "protected", "decoy", "borrowed"]
ExpectedValueMode: TypeAlias = Literal[
    "literal", "object_key_id", "derived_children_count", "sealed_fixture_snapshot"
]
IdentityPolicy: TypeAlias = Literal[
    "preserve", "new", "new_renamed", "replace_with_new", "borrowed_snapshot"
]
QueryResultStrategy: TypeAlias = Literal[
    "exact_rows", "bounded_superset_final_answer_filter"
]
DerivedRowPolicy: TypeAlias = Literal[
    "none", "active_audio_sources_for_sound_rows"
]
PrimaryRowPolicy: TypeAlias = Literal[
    "unique_identity_rows",
    "parent_projection_per_source_row",
    "ancestor_identity_rows",
]
FinalAnswerPolicy: TypeAlias = Literal[
    "name_and_id",
    "paired_path_rows",
    "deduplicated_parent_summary",
    "ordered_ancestor_summary",
]


class ObjectHeavyRecipeError(ValueError):
    """One object-heavy recipe or requested scenario ID is outside the contract."""


@dataclass(frozen=True, slots=True)
class ObjectProperty:
    name: str
    value: Scalar


@dataclass(frozen=True, slots=True)
class ObjectReference:
    name: str
    target_key: str


@dataclass(frozen=True, slots=True)
class FixtureObject:
    """One trusted pre-task Wwise object, keyed independently of its live GUID."""

    key: str
    path: str
    object_type: str
    role: FixtureRole = "owned"
    notes: str | None = None
    properties: tuple[ObjectProperty, ...] = ()
    references: tuple[ObjectReference, ...] = ()
    source_language: str | None = None
    is_included: bool | None = None

    @property
    def name(self) -> str:
        return self.path.rsplit("\\", 1)[-1]

    @property
    def parent_path(self) -> str | None:
        if self.path in {"\\", ACTOR_ROOT}:
            return None
        return self.path.rsplit("\\", 1)[0]


@dataclass(frozen=True, slots=True)
class FixtureRecipe:
    """Closed materialization inputs for a runner-owned project copy."""

    adapter: str
    sandbox: str
    objects: tuple[FixtureObject, ...]
    absent_paths: tuple[str, ...] = ()
    absent_sibling_prefixes: tuple[tuple[str, str], ...] = ()
    seal_fields: tuple[str, ...] = (
        "id",
        "name",
        "type",
        "path",
        "parent",
        "notes",
        "@Volume",
        "@Pitch",
        "OverrideOutput",
        "OutputBus",
        "childrenCount",
        "activeSource",
        "audioSource:language",
        "isIncluded",
    )
    materialization_policy: str = "runner_direct_waapi_then_seal_before_codex"

    def object(self, key: str) -> FixtureObject:
        for item in self.objects:
            if item.key == key:
                return item
        raise ObjectHeavyRecipeError(f"unknown fixture object key: {key}")


@dataclass(frozen=True, slots=True)
class MaterializedReference:
    """One live reference resolved by a trusted runner after fixture creation."""

    name: str
    target_id: str


@dataclass(frozen=True, slots=True)
class MaterializedObject:
    """Minimum live binding that the future V3 engine returns to hidden oracles."""

    key: str
    id: str
    name: str
    type: str
    path: str
    parent_id: str | None
    notes: str | None
    properties: tuple[ObjectProperty, ...]
    references: tuple[MaterializedReference, ...]
    source_language: str | None
    is_included: bool | None
    children_count: int
    active_source_id: str | None = None
    active_source_name: str | None = None
    active_source_path: str | None = None


@dataclass(frozen=True, slots=True)
class ExpectedField:
    name: str
    mode: ExpectedValueMode
    value: Scalar | str = None


@dataclass(frozen=True, slots=True)
class ExpectedObject:
    """One hidden after-state or exact query-row identity."""

    key: str
    object_type: str
    identity_policy: IdentityPolicy
    path: str | None
    requested_name: str
    parent_key: str | None = None
    parent_path: str | None = None
    fields: tuple[ExpectedField, ...] = ()
    children: tuple[str, ...] = ()


OracleRuleKind: TypeAlias = Literal[
    "exact_topology",
    "protected_snapshot_unchanged",
    "identity_preserved",
    "identity_new",
    "identity_absent",
    "renamed_sibling_exactly_one",
    "no_automatic_rename",
    "query_rows_exact",
    "final_answer_filters_superset",
    "answer_counts_equal",
    "answer_order_equal",
    "bound_reached_equal",
    "reference_equals",
]


@dataclass(frozen=True, slots=True)
class OracleRule:
    kind: OracleRuleKind
    subject_keys: tuple[str, ...] = ()
    expected: tuple[tuple[str, Scalar | tuple[str, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class OraclePlan:
    """Model-hidden independent expectations, bound to real GUIDs by the runner."""

    adapter: str
    expected_objects: tuple[ExpectedObject, ...] = ()
    exact_row_keys: tuple[str, ...] = ()
    expected_order_keys: tuple[str, ...] = ()
    excluded_keys: tuple[str, ...] = ()
    preserved_keys: tuple[str, ...] = ()
    new_keys: tuple[str, ...] = ()
    removed_keys: tuple[str, ...] = ()
    protected_snapshot_keys: tuple[str, ...] = ()
    rules: tuple[OracleRule, ...] = ()


@dataclass(frozen=True, slots=True)
class CleanupPlan:
    adapter: str
    owned_object_roots: tuple[str, ...]
    protected_object_roots: tuple[str, ...] = ()
    success_policy: str = "close_wwise_and_delete_scenario_project_copy"
    failure_policy: str = "seal_quarantine_and_never_reuse_scenario_project_copy"
    source_project_policy: str = "immutable_source_digest_and_mtime_unchanged"


@dataclass(frozen=True, slots=True)
class FinalFilterRule:
    field: str
    operator: Literal[
        "equals",
        "less_than",
        "contains",
        "starts_with",
        "relative_depth_at_most",
        "direct_child_of_selected_parent",
        "is_vo_random_container",
        "is_direct_sound_child_of_vo_container",
    ]
    value: Scalar


@dataclass(frozen=True, slots=True)
class FinalAnswerFilter:
    """Closed model-side semantic filtering; never executable code."""

    combine: Literal["identity", "all", "any_with_required"]
    required: tuple[FinalFilterRule, ...] = ()
    any_of: tuple[FinalFilterRule, ...] = ()
    deduplicate_by: str = "id"
    sort_by: tuple[str, ...] = ("path",)


@dataclass(frozen=True, slots=True)
class OperationRequestSpec:
    operation: Literal["object.create", "object.set"]
    arguments: Mapping[str, FrozenJSON]
    allowed_gateway_subcommands: tuple[str, ...] = (
        "operation-schema",
        "preview",
        "transaction-show",
        "confirm",
        "execute",
        "verify",
    )

    def as_dict(self, *, version: str = VERSION) -> dict[str, Any]:
        try:
            get_codex_version_layout_v3(version)
        except CodexVersionLayoutError as exc:
            raise ObjectHeavyRecipeError(str(exc)) from exc
        return {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": version,
            "operation": self.operation,
            "arguments": _plain(self.arguments),
        }

    def canonical_json(self, *, version: str = VERSION) -> str:
        return json.dumps(
            self.as_dict(version=version),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class QueryObjectRequestSpec:
    argv: tuple[str, ...]
    take: int
    return_fields: tuple[str, ...]
    result_strategy: QueryResultStrategy
    exact_expected_keys: tuple[str, ...]
    bounded_superset_keys: tuple[str, ...]
    final_filter: FinalAnswerFilter
    primary_row_policy: PrimaryRowPolicy = "unique_identity_rows"
    derived_row_policy: DerivedRowPolicy = "none"
    final_answer_policy: FinalAnswerPolicy = "name_and_id"


AllowedRequest: TypeAlias = OperationRequestSpec | QueryObjectRequestSpec


@dataclass(frozen=True, slots=True)
class ObjectHeavyRecipe:
    contract: str
    scenario_id: str
    version: str
    api: str
    prompt_literals: tuple[str, ...]
    fixture: FixtureRecipe
    request: AllowedRequest
    oracle: OraclePlan
    cleanup: CleanupPlan
    model_policy: tuple[str, ...] = (
        "packaged_gateway_only",
        "one_primary_business_dispatch",
        "no_model_authored_code",
        "no_direct_waapi_client",
        "no_temporary_script",
        "no_arbitrary_callback_or_command_hook",
    )

    @property
    def digest(self) -> str:
        payload = json.dumps(
            _plain(self), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def _freeze(value: Any) -> FrozenJSON:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    raise ObjectHeavyRecipeError(
        f"operation request contains non-JSON value: {type(value).__name__}"
    )


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _translate_scalar(
    value: Scalar,
    layout: CodexVersionLayoutV3,
) -> Scalar:
    return layout.translate_2022_path(value) if isinstance(value, str) else value


def _translate_frozen_json(
    value: FrozenJSON,
    layout: CodexVersionLayoutV3,
) -> FrozenJSON:
    if value is None or isinstance(value, (str, int, float, bool)):
        return _translate_scalar(value, layout)
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _translate_frozen_json(item, layout)
                for key, item in value.items()
            }
        )
    return tuple(_translate_frozen_json(item, layout) for item in value)


def _translate_fixture_object(
    value: FixtureObject,
    layout: CodexVersionLayoutV3,
) -> FixtureObject:
    return replace(
        value,
        path=layout.translate_2022_path(value.path),
        object_type=layout.reflected_type(value.object_type),
        properties=tuple(
            replace(item, value=_translate_scalar(item.value, layout))
            for item in value.properties
        ),
    )


def _translate_expected_object(
    value: ExpectedObject,
    layout: CodexVersionLayoutV3,
) -> ExpectedObject:
    return replace(
        value,
        object_type=layout.reflected_type(value.object_type),
        path=(
            layout.translate_2022_path(value.path)
            if value.path is not None
            else None
        ),
        parent_path=(
            layout.translate_2022_path(value.parent_path)
            if value.parent_path is not None
            else None
        ),
        fields=tuple(
            replace(item, value=_translate_scalar(item.value, layout))
            for item in value.fields
        ),
    )


def _translate_object_recipe(
    recipe: ObjectHeavyRecipe,
    layout: CodexVersionLayoutV3,
) -> ObjectHeavyRecipe:
    if recipe.version != VERSION:
        raise ObjectHeavyRecipeError("only the reviewed 2022 recipe may be translated")
    if recipe.scenario_id not in OBJECT_COMPOUND_CROSS_VERSION_CASE_IDS:
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} is not approved for Wwise {layout.version}"
        )
    request = recipe.request
    if isinstance(request, OperationRequestSpec):
        translated_request: AllowedRequest = replace(
            request,
            arguments=_translate_frozen_json(request.arguments, layout),
        )
    elif isinstance(request, QueryObjectRequestSpec):
        translated_request = replace(
            request,
            argv=tuple(
                layout.version
                if index == 2
                else layout.translate_2022_path(value)
                for index, value in enumerate(request.argv)
            ),
        )
    else:  # pragma: no cover - static union plus constructor coverage.
        raise ObjectHeavyRecipeError("cross-version object request is unsupported")
    translated = replace(
        recipe,
        version=layout.version,
        prompt_literals=tuple(
            layout.translate_2022_path(item) for item in recipe.prompt_literals
        ),
        fixture=replace(
            recipe.fixture,
            objects=tuple(
                _translate_fixture_object(item, layout)
                for item in recipe.fixture.objects
            ),
            absent_paths=tuple(
                layout.translate_2022_path(item)
                for item in recipe.fixture.absent_paths
            ),
            absent_sibling_prefixes=tuple(
                (layout.translate_2022_path(parent), prefix)
                for parent, prefix in recipe.fixture.absent_sibling_prefixes
            ),
        ),
        request=translated_request,
        oracle=replace(
            recipe.oracle,
            expected_objects=tuple(
                _translate_expected_object(item, layout)
                for item in recipe.oracle.expected_objects
            ),
            rules=tuple(
                replace(
                    rule,
                    expected=tuple(
                        (
                            name,
                            (
                                tuple(
                                    layout.translate_2022_path(item)
                                    for item in expected
                                )
                                if isinstance(expected, tuple)
                                else _translate_scalar(expected, layout)
                            ),
                        )
                        for name, expected in rule.expected
                    ),
                )
                for rule in recipe.oracle.rules
            ),
        ),
        cleanup=replace(
            recipe.cleanup,
            owned_object_roots=tuple(
                layout.translate_2022_path(item)
                for item in recipe.cleanup.owned_object_roots
            ),
            protected_object_roots=tuple(
                layout.translate_2022_path(item)
                for item in recipe.cleanup.protected_object_roots
            ),
        ),
    )
    _validate_recipe(translated)
    return translated


def _identity(path: str) -> dict[str, str]:
    return {"kind": "path", "value": path}


def _property(name: str, value: Scalar) -> dict[str, Scalar]:
    return {"name": name, "value": value}


def _reference(name: str, target_path: str) -> dict[str, Any]:
    return {"name": name, "target": _identity(target_path)}


def _node(
    object_type: str,
    name: str,
    *,
    notes: str | None = None,
    properties: Sequence[Mapping[str, Any]] = (),
    references: Sequence[Mapping[str, Any]] = (),
    children: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    result: dict[str, Any] = {"type": object_type, "name": name}
    if notes is not None:
        result["notes"] = notes
    if properties:
        result["properties"] = list(properties)
    if references:
        result["references"] = list(references)
    if children:
        result["children"] = list(children)
    return result


def _operation(operation: Literal["object.create", "object.set"], arguments: Mapping[str, Any]) -> OperationRequestSpec:
    frozen = _freeze(arguments)
    if not isinstance(frozen, Mapping):  # pragma: no cover - helper always receives a mapping.
        raise ObjectHeavyRecipeError("operation arguments must be an object")
    return OperationRequestSpec(operation=operation, arguments=frozen)


def _field(name: str, value: Scalar) -> ObjectProperty:
    return ObjectProperty(name=name, value=value)


def _seed(
    key: str,
    path: str,
    object_type: str,
    *,
    role: FixtureRole = "owned",
    notes: str | None = None,
    volume: float | None = None,
    pitch: float | None = None,
    output_bus: str | None = None,
    language: str | None = None,
    included: bool | None = None,
) -> FixtureObject:
    properties = tuple(
        item
        for item in (
            _field("Volume", volume) if volume is not None else None,
            _field("Pitch", pitch) if pitch is not None else None,
        )
        if item is not None
    )
    references = (
        (ObjectReference("OutputBus", output_bus),) if output_bus is not None else ()
    )
    return FixtureObject(
        key=key,
        path=path,
        object_type=object_type,
        role=role,
        notes=notes,
        properties=properties,
        references=references,
        source_language=language,
        is_included=included,
    )


def _literal(name: str, value: Scalar) -> ExpectedField:
    return ExpectedField(name=name, mode="literal", value=value)


def _key_id(name: str, key: str) -> ExpectedField:
    return ExpectedField(name=name, mode="object_key_id", value=key)


def _child_count() -> ExpectedField:
    return ExpectedField(
        name="childrenCount", mode="derived_children_count", value=None
    )


def _snapshot(name: str) -> ExpectedField:
    return ExpectedField(name=name, mode="sealed_fixture_snapshot", value=None)


def _expected_from_seed(
    seed: FixtureObject,
    objects: Sequence[FixtureObject],
    *,
    return_fields: Sequence[str],
) -> ExpectedObject:
    """Derive one exact hidden row without inventing a live GUID."""

    by_path = {item.path: item for item in objects}
    properties = {item.name: item.value for item in seed.properties}
    references = {item.name: item.target_key for item in seed.references}
    expected_fields: list[ExpectedField] = []
    for field_name in return_fields:
        if field_name in {"id", "name", "type", "path"}:
            continue
        if field_name == "notes":
            if seed.role == "borrowed":
                expected_fields.append(_snapshot(field_name))
            else:
                expected_fields.append(_literal(field_name, seed.notes or ""))
        elif field_name.startswith("@"):
            property_name = field_name[1:]
            if property_name not in properties:
                raise ObjectHeavyRecipeError(
                    f"{seed.key} lacks expected property {property_name}"
                )
            expected_fields.append(_literal(field_name, properties[property_name]))
        elif field_name == "OutputBus":
            target_key = references.get("OutputBus")
            if target_key is None:
                raise ObjectHeavyRecipeError(f"{seed.key} lacks expected OutputBus")
            expected_fields.append(_key_id(field_name, target_key))
        elif field_name == "audioSource:language":
            if seed.source_language is None:
                expected_fields.append(_literal(field_name, None))
            else:
                expected_fields.append(_literal(field_name, seed.source_language))
        elif field_name == "isIncluded":
            if seed.is_included is None:
                raise ObjectHeavyRecipeError(f"{seed.key} lacks expected isIncluded")
            expected_fields.append(_literal(field_name, seed.is_included))
        elif field_name == "childrenCount":
            expected_fields.append(
                _snapshot(field_name) if seed.role == "borrowed" else _child_count()
            )
        elif field_name == "parent":
            parent = by_path.get(seed.parent_path or "")
            if parent is None:
                raise ObjectHeavyRecipeError(
                    f"{seed.key} parent is not represented in the fixture"
                )
            expected_fields.append(_key_id(field_name, parent.key))
        else:
            raise ObjectHeavyRecipeError(
                f"unsupported exact-row return field: {field_name}"
            )
    children = tuple(
        item.key for item in objects if item.parent_path == seed.path
    )
    identity_policy: IdentityPolicy = (
        "borrowed_snapshot" if seed.role == "borrowed" else "preserve"
    )
    parent = by_path.get(seed.parent_path or "")
    return _expected(
        seed.key,
        seed.path,
        seed.object_type,
        identity_policy=identity_policy,
        parent_key=parent.key if parent is not None else None,
        parent_path=seed.parent_path if parent is None else None,
        expected_fields=expected_fields,
        children=children,
    )


def _expected(
    key: str,
    path: str | None,
    object_type: str,
    *,
    identity_policy: IdentityPolicy,
    requested_name: str | None = None,
    parent_key: str | None = None,
    parent_path: str | None = None,
    expected_fields: Sequence[ExpectedField] = (),
    children: Sequence[str] = (),
) -> ExpectedObject:
    if requested_name is None:
        if path is None:
            raise ObjectHeavyRecipeError(f"{key} requires requested_name when path is dynamic")
        requested_name = path.rsplit("\\", 1)[-1]
    return ExpectedObject(
        key=key,
        object_type=object_type,
        identity_policy=identity_policy,
        path=path,
        requested_name=requested_name,
        parent_key=parent_key,
        parent_path=parent_path,
        fields=tuple(expected_fields),
        children=tuple(children),
    )


def _where_scalar(value: Any) -> tuple[str, str]:
    if isinstance(value, bool):
        return "boolean", "true" if value else "false"
    if isinstance(value, int):
        return "integer", str(value)
    if isinstance(value, float):
        return "number", str(value)
    if isinstance(value, str):
        return "string", value
    raise ObjectHeavyRecipeError("query predicate scalar is not supported")


def _query(
    *,
    source: tuple[str, str],
    selects: Sequence[str] = (),
    predicates: Sequence[Mapping[str, Any]] = (),
    take: int,
    return_fields: Sequence[str],
    strategy: QueryResultStrategy,
    exact_keys: Sequence[str],
    superset_keys: Sequence[str],
    final_filter: FinalAnswerFilter,
    primary_row_policy: PrimaryRowPolicy = "unique_identity_rows",
    derived_row_policy: DerivedRowPolicy = "none",
    final_answer_policy: FinalAnswerPolicy = "name_and_id",
) -> QueryObjectRequestSpec:
    argv = ["gateway.py", "--version", VERSION, "query-object", source[0], source[1]]
    for select in selects:
        argv.extend(("--select", select))
    for predicate in predicates:
        if set(predicate) != {"field", "operator", "value"}:
            raise ObjectHeavyRecipeError("query predicate shape is not closed")
        value_type, value = _where_scalar(predicate["value"])
        argv.extend(
            (
                "--where",
                str(predicate["field"]),
                str(predicate["operator"]),
                value_type,
                value,
            )
        )
    argv.extend(("--take", str(take)))
    for field_name in return_fields:
        argv.extend(("--return-field", field_name))
    return QueryObjectRequestSpec(
        argv=tuple(argv),
        take=take,
        return_fields=tuple(return_fields),
        result_strategy=strategy,
        exact_expected_keys=tuple(exact_keys),
        bounded_superset_keys=tuple(superset_keys),
        final_filter=final_filter,
        primary_row_policy=primary_row_policy,
        derived_row_policy=derived_row_policy,
        final_answer_policy=final_answer_policy,
    )


def _fixture(objects: Sequence[FixtureObject], *, absent: Sequence[str] = (), prefixes: Sequence[tuple[str, str]] = ()) -> FixtureRecipe:
    return FixtureRecipe(
        adapter="core_object_runner_fixture_v3",
        sandbox="scenario_project_copy",
        objects=tuple(objects),
        absent_paths=tuple(absent),
        absent_sibling_prefixes=tuple(prefixes),
    )


def _cleanup(*owned: str, protected: Sequence[str] = ()) -> CleanupPlan:
    return CleanupPlan(
        adapter="scenario_project_cleanup",
        owned_object_roots=tuple(owned),
        protected_object_roots=tuple(protected),
    )


def _recipe(
    scenario_id: str,
    api: str,
    *,
    prompt_literals: Sequence[str],
    fixture: FixtureRecipe,
    request: AllowedRequest,
    oracle: OraclePlan,
    cleanup: CleanupPlan,
) -> ObjectHeavyRecipe:
    result = ObjectHeavyRecipe(
        contract=OBJECT_HEAVY_RECIPE_CONTRACT,
        scenario_id=scenario_id,
        version=VERSION,
        api=api,
        prompt_literals=tuple(prompt_literals),
        fixture=fixture,
        request=request,
        oracle=oracle,
        cleanup=cleanup,
    )
    _validate_recipe(result)
    return result


def _create_01() -> ObjectHeavyRecipe:
    control_path = SEMANTIC_LAB + r"\Keep_Existing"
    root_path = SEMANTIC_LAB + r"\Player_Foley"
    footsteps_path = root_path + r"\Footsteps"
    cloth_path = root_path + r"\Cloth"
    objects = (
        _seed("semantic", SEMANTIC_LAB, "ActorMixer"),
        _seed("keep_existing", control_path, "Sound", role="protected", notes="fixture control"),
    )
    arguments = {
        "parent": _identity(SEMANTIC_LAB),
        "type": "ActorMixer",
        "name": "Player_Foley",
        "notes": "角色脚步统一入口",
        "properties": [_property("Volume", -2.0)],
        "children": [
            _node(
                "RandomSequenceContainer",
                "Footsteps",
                children=(
                    _node("Sound", "Footstep_A"),
                    _node("Sound", "Footstep_B"),
                ),
            ),
            _node(
                "BlendContainer",
                "Cloth",
                children=(_node("Sound", "Cloth_A"), _node("Sound", "Cloth_B")),
            ),
        ],
        "on_name_conflict": "fail",
    }
    expected = (
        _expected(
            "player_foley",
            root_path,
            "ActorMixer",
            identity_policy="new",
            parent_key="semantic",
            expected_fields=(_literal("notes", "角色脚步统一入口"), _literal("@Volume", -2.0)),
            children=("footsteps", "cloth"),
        ),
        _expected(
            "footsteps",
            footsteps_path,
            "RandomSequenceContainer",
            identity_policy="new",
            parent_key="player_foley",
            children=("footstep_a", "footstep_b"),
        ),
        _expected("footstep_a", footsteps_path + r"\Footstep_A", "Sound", identity_policy="new", parent_key="footsteps"),
        _expected("footstep_b", footsteps_path + r"\Footstep_B", "Sound", identity_policy="new", parent_key="footsteps"),
        _expected(
            "cloth",
            cloth_path,
            "BlendContainer",
            identity_policy="new",
            parent_key="player_foley",
            children=("cloth_a", "cloth_b"),
        ),
        _expected("cloth_a", cloth_path + r"\Cloth_A", "Sound", identity_policy="new", parent_key="cloth"),
        _expected("cloth_b", cloth_path + r"\Cloth_B", "Sound", identity_policy="new", parent_key="cloth"),
    )
    new_keys = tuple(item.key for item in expected)
    return _recipe(
        "OBJ22-F-CREATE-01",
        OBJECT_CREATE_URI,
        prompt_literals=(SEMANTIC_LAB, "Player_Foley", "角色脚步统一入口", "Footsteps", "Cloth", "Footstep_A", "Footstep_B", "Cloth_A", "Cloth_B", "-2 dB"),
        fixture=_fixture(objects, absent=(root_path,)),
        request=_operation("object.create", arguments),
        oracle=OraclePlan(
            adapter="waapi_object_readback",
            expected_objects=expected,
            new_keys=new_keys,
            preserved_keys=("semantic", "keep_existing"),
            protected_snapshot_keys=("keep_existing",),
            rules=(
                OracleRule("exact_topology", new_keys),
                OracleRule("identity_new", new_keys),
                OracleRule("protected_snapshot_unchanged", ("keep_existing",)),
                OracleRule("no_automatic_rename", ("player_foley",)),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB, protected=(control_path,)),
    )


def _create_02() -> ObjectHeavyRecipe:
    npc_path = SEMANTIC_LAB + r"\NPC"
    robot_path = npc_path + r"\Robot_VO"
    idle_path = robot_path + r"\Idle"
    objects = (
        _seed("semantic", SEMANTIC_LAB, "ActorMixer"),
        _seed("npc", npc_path, "ActorMixer"),
        _seed("robot", robot_path, "ActorMixer", role="protected", notes="legacy Robot VO"),
        _seed("idle", idle_path, "RandomSequenceContainer", role="protected", notes="idle baseline"),
        _seed("idle_a", idle_path + r"\Idle_A", "Sound", role="protected", notes="idle A baseline"),
        _seed("npc_control", npc_path + r"\Keep_NPC", "Sound", role="protected", notes="fixture control"),
    )
    groups = (
        ("alert", "Alert", "警戒对白", ("Alert_A", "Alert_B")),
        ("combat", "Combat", "战斗对白", ("Combat_A", "Combat_B")),
        ("damage", "Damage", "受击对白", ("Damage_A", "Damage_B")),
    )
    children = tuple(
        _node(
            "RandomSequenceContainer",
            name,
            notes=notes,
            children=tuple(_node("Sound", child) for child in child_names),
        )
        for _, name, notes, child_names in groups
    )
    arguments = {
        "parent": _identity(npc_path),
        "type": "ActorMixer",
        "name": "Robot_VO",
        "children": children,
        "on_name_conflict": "merge",
    }
    expected: list[ExpectedObject] = [
        _expected(
            "robot",
            robot_path,
            "ActorMixer",
            identity_policy="preserve",
            parent_key="npc",
            children=("idle", "alert", "combat", "damage"),
        ),
        _expected("idle", idle_path, "RandomSequenceContainer", identity_policy="preserve", parent_key="robot", children=("idle_a",)),
        _expected("idle_a", idle_path + r"\Idle_A", "Sound", identity_policy="preserve", parent_key="idle"),
    ]
    new_keys: list[str] = []
    for group_key, name, notes, child_names in groups:
        group_path = robot_path + "\\" + name
        child_keys = tuple(f"{group_key}_{suffix.casefold()}" for suffix in ("A", "B"))
        expected.append(
            _expected(
                group_key,
                group_path,
                "RandomSequenceContainer",
                identity_policy="new",
                parent_key="robot",
                expected_fields=(_literal("notes", notes),),
                children=child_keys,
            )
        )
        new_keys.append(group_key)
        for child_key, child_name in zip(child_keys, child_names, strict=True):
            expected.append(_expected(child_key, group_path + "\\" + child_name, "Sound", identity_policy="new", parent_key=group_key))
            new_keys.append(child_key)
    absent = tuple(robot_path + "\\" + name for _, name, _, _ in groups) + (npc_path + r"\Robot_VO_01",)
    return _recipe(
        "OBJ22-F-CREATE-02",
        OBJECT_CREATE_URI,
        prompt_literals=(npc_path, "Robot_VO", "Idle_A", "Alert", "Combat", "Damage", "警戒对白", "战斗对白", "受击对白", "Robot_VO_01"),
        fixture=_fixture(objects, absent=absent),
        request=_operation("object.create", arguments),
        oracle=OraclePlan(
            adapter="waapi_object_readback",
            expected_objects=tuple(expected),
            preserved_keys=("robot", "idle", "idle_a", "npc_control"),
            new_keys=tuple(new_keys),
            protected_snapshot_keys=("idle", "idle_a", "npc_control"),
            rules=(
                OracleRule("exact_topology", tuple(item.key for item in expected)),
                OracleRule("identity_preserved", ("robot", "idle", "idle_a")),
                OracleRule("identity_new", tuple(new_keys)),
                OracleRule("no_automatic_rename", ("robot",)),
                OracleRule("protected_snapshot_unchanged", ("idle", "idle_a", "npc_control")),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB, protected=(idle_path, npc_path + r"\Keep_NPC")),
    )


def _create_03() -> ObjectHeavyRecipe:
    weapons_path = SEMANTIC_LAB + r"\Weapons"
    old_path = weapons_path + r"\Impact_Library"
    legacy_path = old_path + r"\Legacy"
    objects = (
        _seed("semantic", SEMANTIC_LAB, "ActorMixer"),
        _seed("weapons", weapons_path, "ActorMixer"),
        _seed("old_impact", old_path, "ActorMixer", role="protected", notes="旧材质碰撞库", volume=-6.0),
        _seed("legacy", legacy_path, "RandomSequenceContainer", role="protected", notes="legacy branch"),
        _seed("legacy_hit", legacy_path + r"\Legacy_Hit", "Sound", role="protected", notes="legacy hit"),
        _seed("weapons_control", weapons_path + r"\Keep_Weapons", "Sound", role="protected", notes="fixture control"),
    )
    arguments = {
        "parent": _identity(weapons_path),
        "type": "ActorMixer",
        "name": "Impact_Library",
        "notes": "新版材质碰撞库",
        "properties": [_property("Volume", -1.5)],
        "children": [
            _node("RandomSequenceContainer", "Metal", children=(_node("Sound", "Light"), _node("Sound", "Heavy"))),
            _node("RandomSequenceContainer", "Wood", children=(_node("Sound", "Light"), _node("Sound", "Heavy"))),
        ],
        "on_name_conflict": "rename",
    }
    expected = (
        _expected(
            "new_impact",
            None,
            "ActorMixer",
            identity_policy="new_renamed",
            requested_name="Impact_Library",
            parent_key="weapons",
            expected_fields=(_literal("notes", "新版材质碰撞库"), _literal("@Volume", -1.5)),
            children=("new_metal", "new_wood"),
        ),
        _expected("new_metal", None, "RandomSequenceContainer", identity_policy="new", requested_name="Metal", parent_key="new_impact", children=("new_metal_light", "new_metal_heavy")),
        _expected("new_metal_light", None, "Sound", identity_policy="new", requested_name="Light", parent_key="new_metal"),
        _expected("new_metal_heavy", None, "Sound", identity_policy="new", requested_name="Heavy", parent_key="new_metal"),
        _expected("new_wood", None, "RandomSequenceContainer", identity_policy="new", requested_name="Wood", parent_key="new_impact", children=("new_wood_light", "new_wood_heavy")),
        _expected("new_wood_light", None, "Sound", identity_policy="new", requested_name="Light", parent_key="new_wood"),
        _expected("new_wood_heavy", None, "Sound", identity_policy="new", requested_name="Heavy", parent_key="new_wood"),
    )
    new_keys = tuple(item.key for item in expected)
    return _recipe(
        "OBJ22-F-CREATE-03",
        OBJECT_CREATE_URI,
        prompt_literals=(weapons_path, "Impact_Library", "新版材质碰撞库", "-1.5 dB", "Metal", "Wood", "Light", "Heavy"),
        fixture=_fixture(objects, prefixes=((weapons_path, "Impact_Library"),)),
        request=_operation("object.create", arguments),
        oracle=OraclePlan(
            adapter="waapi_object_readback",
            expected_objects=expected,
            preserved_keys=("old_impact", "legacy", "legacy_hit", "weapons_control"),
            new_keys=new_keys,
            protected_snapshot_keys=("old_impact", "legacy", "legacy_hit", "weapons_control"),
            rules=(
                OracleRule("renamed_sibling_exactly_one", ("new_impact",), (("requested_name", "Impact_Library"),)),
                OracleRule("exact_topology", new_keys),
                OracleRule("identity_new", new_keys),
                OracleRule("protected_snapshot_unchanged", ("old_impact", "legacy", "legacy_hit", "weapons_control")),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB, protected=(old_path, weapons_path + r"\Keep_Weapons")),
    )


def _create_04() -> ObjectHeavyRecipe:
    characters_path = SEMANTIC_LAB + r"\Characters"
    bus_path = MASTER_DWU + r"\VO_Bus"
    root_path = characters_path + r"\Hero_VO"
    story_path = root_path + r"\Story"
    combat_path = root_path + r"\Combat"
    objects = (
        _seed("vo_bus", bus_path, "Bus", role="protected", notes="VO fixture bus"),
        _seed("semantic", SEMANTIC_LAB, "ActorMixer"),
        _seed("characters", characters_path, "ActorMixer"),
        _seed("characters_control", characters_path + r"\Keep_Characters", "Sound", role="protected", notes="fixture control"),
    )
    arguments = {
        "parent": _identity(characters_path),
        "type": "ActorMixer",
        "name": "Hero_VO",
        "notes": "主角对白入口",
        "properties": [_property("Volume", -4.0)],
        "references": [_reference("OutputBus", bus_path)],
        "children": [
            _node("RandomSequenceContainer", "Story", children=(_node("Sound", "Greeting"), _node("Sound", "Quest"))),
            _node("RandomSequenceContainer", "Combat", children=(_node("Sound", "Attack"), _node("Sound", "Damage"), _node("Sound", "Death"))),
        ],
        "on_name_conflict": "fail",
    }
    expected = (
        _expected("hero_vo", root_path, "ActorMixer", identity_policy="new", parent_key="characters", expected_fields=(_literal("notes", "主角对白入口"), _literal("@Volume", -4.0), _key_id("OutputBus", "vo_bus")), children=("story", "hero_combat")),
        _expected("story", story_path, "RandomSequenceContainer", identity_policy="new", parent_key="hero_vo", children=("greeting", "quest")),
        _expected("greeting", story_path + r"\Greeting", "Sound", identity_policy="new", parent_key="story"),
        _expected("quest", story_path + r"\Quest", "Sound", identity_policy="new", parent_key="story"),
        _expected("hero_combat", combat_path, "RandomSequenceContainer", identity_policy="new", parent_key="hero_vo", children=("attack", "damage", "death")),
        _expected("attack", combat_path + r"\Attack", "Sound", identity_policy="new", parent_key="hero_combat"),
        _expected("damage", combat_path + r"\Damage", "Sound", identity_policy="new", parent_key="hero_combat"),
        _expected("death", combat_path + r"\Death", "Sound", identity_policy="new", parent_key="hero_combat"),
    )
    new_keys = tuple(item.key for item in expected)
    return _recipe(
        "OBJ22-F-CREATE-04",
        OBJECT_CREATE_URI,
        prompt_literals=(characters_path, "Hero_VO", "主角对白入口", "-4 dB", bus_path, "Story", "Combat", "Greeting", "Quest", "Attack", "Damage", "Death"),
        fixture=_fixture(objects, absent=tuple(item.path for item in expected if item.path is not None)),
        request=_operation("object.create", arguments),
        oracle=OraclePlan(
            adapter="waapi_object_readback",
            expected_objects=expected,
            preserved_keys=("vo_bus", "characters_control"),
            new_keys=new_keys,
            protected_snapshot_keys=("vo_bus", "characters_control"),
            rules=(
                OracleRule("exact_topology", new_keys),
                OracleRule("identity_new", new_keys),
                OracleRule("reference_equals", ("hero_vo", "vo_bus")),
                OracleRule("no_automatic_rename", ("hero_vo",)),
                OracleRule("protected_snapshot_unchanged", ("vo_bus", "characters_control")),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB, protected=(bus_path, characters_path + r"\Keep_Characters")),
    )


def _create_05() -> ObjectHeavyRecipe:
    generated_path = SEMANTIC_LAB + r"\Generated"
    root_path = generated_path + r"\Prototype_Footsteps"
    old_group_path = root_path + r"\Old_Group"
    keep_path = generated_path + r"\Keep_Me"
    objects = (
        _seed("semantic", SEMANTIC_LAB, "ActorMixer"),
        _seed("generated", generated_path, "ActorMixer"),
        _seed("old_proto", root_path, "ActorMixer", notes="旧脚步原型", volume=-8.0),
        _seed("old_group", old_group_path, "RandomSequenceContainer", notes="old group"),
        _seed("old_walk", old_group_path + r"\Old_Walk", "Sound", notes="old walk"),
        _seed("keep_me", keep_path, "ActorMixer", role="protected", notes="protected keep", volume=-7.0),
        _seed("keep_sound", keep_path + r"\Keep_Sound", "Sound", role="protected", notes="protected child"),
    )
    group_names = ("Sneakers", "Boots", "Barefoot")
    arguments = {
        "parent": _identity(generated_path),
        "type": "ActorMixer",
        "name": "Prototype_Footsteps",
        "notes": "新脚步原型",
        "children": [
            _node("RandomSequenceContainer", name, children=(_node("Sound", "Walk"), _node("Sound", "Run")))
            for name in group_names
        ],
        "on_name_conflict": "replace",
        "replace_owned_root": _identity(generated_path),
    }
    expected: list[ExpectedObject] = [
        _expected("new_proto", root_path, "ActorMixer", identity_policy="replace_with_new", parent_key="generated", expected_fields=(_literal("notes", "新脚步原型"),), children=tuple(name.casefold() for name in group_names))
    ]
    for name in group_names:
        key = name.casefold()
        group_path = root_path + "\\" + name
        expected.extend(
            (
                _expected(key, group_path, "RandomSequenceContainer", identity_policy="new", parent_key="new_proto", children=(f"{key}_walk", f"{key}_run")),
                _expected(f"{key}_walk", group_path + r"\Walk", "Sound", identity_policy="new", parent_key=key),
                _expected(f"{key}_run", group_path + r"\Run", "Sound", identity_policy="new", parent_key=key),
            )
        )
    new_keys = tuple(item.key for item in expected)
    removed = ("old_proto", "old_group", "old_walk")
    return _recipe(
        "OBJ22-F-CREATE-05",
        OBJECT_CREATE_URI,
        prompt_literals=(generated_path, "Prototype_Footsteps", "新脚步原型", "Sneakers", "Boots", "Barefoot", "Walk", "Run", "Keep_Me"),
        fixture=_fixture(objects),
        request=_operation("object.create", arguments),
        oracle=OraclePlan(
            adapter="waapi_object_readback",
            expected_objects=tuple(expected),
            preserved_keys=("generated", "keep_me", "keep_sound"),
            new_keys=new_keys,
            removed_keys=removed,
            protected_snapshot_keys=("keep_me", "keep_sound"),
            rules=(
                OracleRule("identity_absent", removed),
                OracleRule("identity_new", new_keys),
                OracleRule("exact_topology", new_keys),
                OracleRule("protected_snapshot_unchanged", ("keep_me", "keep_sound")),
                OracleRule("no_automatic_rename", ("new_proto",)),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB, protected=(keep_path,)),
    )


def _set_01() -> ObjectHeavyRecipe:
    combat_path = SEMANTIC_LAB + r"\Combat"
    ranged_path = combat_path + r"\Ranged"
    melee_path = combat_path + r"\Melee"
    objects = (
        _seed("semantic", SEMANTIC_LAB, "ActorMixer"),
        _seed("combat", combat_path, "ActorMixer", notes="legacy combat", volume=0.0),
        _seed("ranged", ranged_path, "RandomSequenceContainer", role="protected", notes="ranged baseline", volume=-5.0),
        _seed("ranged_a", ranged_path + r"\Ranged_A", "Sound", role="protected", notes="ranged A"),
        _seed("ranged_b", ranged_path + r"\Ranged_B", "Sound", role="protected", notes="ranged B"),
    )
    arguments = {
        "objects": [
            {
                "object": _identity(combat_path),
                "notes": "战斗音频入口",
                "properties": [_property("Volume", -3.0)],
                "children": [
                    _node("RandomSequenceContainer", "Melee", children=(_node("Sound", "Light"), _node("Sound", "Heavy")))
                ],
            }
        ],
        "on_name_conflict": "fail",
    }
    expected = (
        _expected("combat", combat_path, "ActorMixer", identity_policy="preserve", parent_key="semantic", expected_fields=(_literal("notes", "战斗音频入口"), _literal("@Volume", -3.0)), children=("ranged", "melee")),
        _expected("melee", melee_path, "RandomSequenceContainer", identity_policy="new", parent_key="combat", children=("melee_light", "melee_heavy")),
        _expected("melee_light", melee_path + r"\Light", "Sound", identity_policy="new", parent_key="melee"),
        _expected("melee_heavy", melee_path + r"\Heavy", "Sound", identity_policy="new", parent_key="melee"),
    )
    return _recipe(
        "OBJ22-F-SET-01",
        OBJECT_SET_URI,
        prompt_literals=(combat_path, "战斗音频入口", "-3 dB", "Melee", "Light", "Heavy", "Ranged"),
        fixture=_fixture(objects, absent=(melee_path,)),
        request=_operation("object.set", arguments),
        oracle=OraclePlan(
            adapter="waapi_object_readback",
            expected_objects=expected,
            preserved_keys=("combat", "ranged", "ranged_a", "ranged_b"),
            new_keys=("melee", "melee_light", "melee_heavy"),
            protected_snapshot_keys=("ranged", "ranged_a", "ranged_b"),
            rules=(
                OracleRule("identity_preserved", ("combat", "ranged", "ranged_a", "ranged_b")),
                OracleRule("identity_new", ("melee", "melee_light", "melee_heavy")),
                OracleRule("exact_topology", tuple(item.key for item in expected)),
                OracleRule("protected_snapshot_unchanged", ("ranged", "ranged_a", "ranged_b")),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB, protected=(ranged_path,)),
    )


def _set_02() -> ObjectHeavyRecipe:
    ui_path = SEMANTIC_LAB + r"\UI"
    confirm_path = ui_path + r"\Confirm"
    cancel_path = ui_path + r"\Cancel"
    error_path = ui_path + r"\Error"
    objects = (
        _seed("semantic", SEMANTIC_LAB, "ActorMixer"),
        _seed("ui", ui_path, "ActorMixer"),
        _seed("confirm", confirm_path, "ActorMixer", notes="old confirm", volume=-8.0, pitch=25.0),
        _seed("confirm_old", confirm_path + r"\Confirm_Old", "Sound", role="protected", notes="confirm child"),
        _seed("cancel", cancel_path, "ActorMixer", notes="old cancel", volume=-8.0, pitch=-25.0),
        _seed("cancel_old", cancel_path + r"\Cancel_Old", "Sound", role="protected", notes="cancel child"),
        _seed("error", error_path, "ActorMixer", notes="old error", volume=-8.0, pitch=-50.0),
        _seed("error_old", error_path + r"\Error_Old", "Sound", role="protected", notes="error child"),
    )
    target_rows = (
        ("confirm", confirm_path, "确认操作反馈", -1.0),
        ("cancel", cancel_path, "取消操作反馈", -2.0),
        ("error", error_path, "错误操作反馈", -4.0),
    )
    request_objects: list[dict[str, Any]] = []
    expected: list[ExpectedObject] = []
    for key, path, notes, volume in target_rows:
        row: dict[str, Any] = {
            "object": _identity(path),
            "notes": notes,
            "properties": [_property("Volume", volume)],
        }
        children = (f"{key}_old",)
        if key == "error":
            row["children"] = [_node("Sound", "Error_Layer")]
            children = ("error_old", "error_layer")
        request_objects.append(row)
        expected.append(
            _expected(
                key,
                path,
                "ActorMixer",
                identity_policy="preserve",
                parent_key="ui",
                expected_fields=(_literal("notes", notes), _literal("@Volume", volume), _snapshot("@Pitch")),
                children=children,
            )
        )
    expected.append(_expected("error_layer", error_path + r"\Error_Layer", "Sound", identity_policy="new", parent_key="error"))
    return _recipe(
        "OBJ22-F-SET-02",
        OBJECT_SET_URI,
        prompt_literals=(ui_path, "Confirm", "Cancel", "Error", "-1", "-2", "-4", "确认操作反馈", "取消操作反馈", "错误操作反馈", "Error_Layer"),
        fixture=_fixture(objects, absent=(error_path + r"\Error_Layer",)),
        request=_operation("object.set", {"objects": request_objects, "on_name_conflict": "fail"}),
        oracle=OraclePlan(
            adapter="waapi_object_readback",
            expected_objects=tuple(expected),
            preserved_keys=("confirm", "cancel", "error", "confirm_old", "cancel_old", "error_old"),
            new_keys=("error_layer",),
            protected_snapshot_keys=("confirm_old", "cancel_old", "error_old"),
            rules=(
                OracleRule("identity_preserved", ("confirm", "cancel", "error")),
                OracleRule("identity_new", ("error_layer",)),
                OracleRule("protected_snapshot_unchanged", ("confirm_old", "cancel_old", "error_old")),
                OracleRule("no_automatic_rename", ("error_layer",)),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB, protected=(confirm_path + r"\Confirm_Old", cancel_path + r"\Cancel_Old", error_path + r"\Error_Old")),
    )


def _set_03() -> ObjectHeavyRecipe:
    ambience_path = SEMANTIC_LAB + r"\Ambience"
    ambience_bus_path = MASTER_DWU + r"\Ambience_Bus"
    weather_bus_path = MASTER_DWU + r"\Weather_Bus"
    rows = (
        ("day", "Day", "白天环境层", -2.0, 100, "ambience_bus"),
        ("night", "Night", "夜间环境层", -5.0, -100, "ambience_bus"),
        ("storm", "Storm", "风暴环境层", -3.0, -200, "weather_bus"),
    )
    objects: list[FixtureObject] = [
        _seed("ambience_bus", ambience_bus_path, "Bus", role="protected", notes="ambience bus"),
        _seed("weather_bus", weather_bus_path, "Bus", role="protected", notes="weather bus"),
        _seed("semantic", SEMANTIC_LAB, "ActorMixer"),
        _seed("ambience", ambience_path, "ActorMixer"),
    ]
    for key, name, _, _, _, _ in rows:
        path = ambience_path + "\\" + name
        objects.extend(
            (
                _seed(key, path, "ActorMixer", notes=f"old {name}", volume=-9.0, pitch=0.0, output_bus="weather_bus" if key != "storm" else "ambience_bus"),
                _seed(f"{key}_child", path + f"\\{name}_Existing", "Sound", role="protected", notes=f"{name} child"),
            )
        )
    request_objects: list[dict[str, Any]] = []
    expected: list[ExpectedObject] = []
    for key, name, notes, volume, pitch, bus_key in rows:
        path = ambience_path + "\\" + name
        bus_path = ambience_bus_path if bus_key == "ambience_bus" else weather_bus_path
        request_objects.append(
            {
                "object": _identity(path),
                "notes": notes,
                "properties": [_property("Volume", volume), _property("Pitch", pitch)],
                "references": [_reference("OutputBus", bus_path)],
            }
        )
        expected.append(
            _expected(
                key,
                path,
                "ActorMixer",
                identity_policy="preserve",
                parent_key="ambience",
                expected_fields=(_literal("notes", notes), _literal("@Volume", volume), _literal("@Pitch", pitch), _key_id("OutputBus", bus_key)),
                children=(f"{key}_child",),
            )
        )
    return _recipe(
        "OBJ22-F-SET-03",
        OBJECT_SET_URI,
        prompt_literals=(ambience_path, "Day", "Night", "Storm", "-2 dB", "1 semitone", "-5 dB", "-1 semitone", "-3 dB", "-2 semitones", "白天环境层", "夜间环境层", "风暴环境层", ambience_bus_path, weather_bus_path),
        fixture=_fixture(objects),
        request=_operation("object.set", {"objects": request_objects, "on_name_conflict": "fail"}),
        oracle=OraclePlan(
            adapter="waapi_object_readback",
            expected_objects=tuple(expected),
            preserved_keys=("day", "night", "storm", "day_child", "night_child", "storm_child", "ambience_bus", "weather_bus"),
            protected_snapshot_keys=("day_child", "night_child", "storm_child", "ambience_bus", "weather_bus"),
            rules=(
                OracleRule("identity_preserved", ("day", "night", "storm")),
                OracleRule("reference_equals", ("day", "night", "storm", "ambience_bus", "weather_bus")),
                OracleRule("protected_snapshot_unchanged", ("day_child", "night_child", "storm_child", "ambience_bus", "weather_bus")),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB, protected=(ambience_bus_path, weather_bus_path)),
    )


def _set_04() -> ObjectHeavyRecipe:
    foley_path = SEMANTIC_LAB + r"\Foley"
    objects: list[FixtureObject] = [
        _seed("semantic", SEMANTIC_LAB, "ActorMixer"),
        _seed("foley", foley_path, "ActorMixer"),
    ]
    for key, name in (("player", "Player"), ("npc", "NPC")):
        root_path = foley_path + "\\" + name
        footsteps_path = root_path + r"\Footsteps"
        objects.extend(
            (
                _seed(key, root_path, "ActorMixer", notes=f"old {name}", volume=-8.0),
                _seed(f"{key}_footsteps", footsteps_path, "RandomSequenceContainer", notes=f"{name} footsteps"),
                _seed(f"{key}_walk_a", footsteps_path + r"\Walk_A", "Sound", role="protected", notes=f"{name} Walk A"),
                _seed(f"{key}_protected", root_path + f"\\{name}_Keep", "ActorMixer", role="protected", notes=f"{name} protected"),
                _seed(f"{key}_protected_sound", root_path + f"\\{name}_Keep\\Keep_Sound", "Sound", role="protected", notes="protected sound"),
            )
        )
    player_path = foley_path + r"\Player"
    npc_path = foley_path + r"\NPC"
    arguments = {
        "objects": [
            {
                "object": _identity(player_path),
                "notes": "玩家 Foley",
                "properties": [_property("Volume", -1.0)],
                "children": [
                    _node("RandomSequenceContainer", "Cloth", children=(_node("Sound", "Cloth_Light"), _node("Sound", "Cloth_Heavy"))),
                ],
            },
            {
                "object": _identity(player_path + r"\Footsteps"),
                "children": [_node("Sound", "Walk_B")],
            },
            {
                "object": _identity(npc_path),
                "notes": "NPC Foley",
                "properties": [_property("Volume", -3.0)],
                "children": [
                    _node("RandomSequenceContainer", "Armor", children=(_node("Sound", "Armor_Light"), _node("Sound", "Armor_Heavy"))),
                ],
            },
            {
                "object": _identity(npc_path + r"\Footsteps"),
                "children": [_node("Sound", "Walk_B")],
            },
        ],
        "on_name_conflict": "fail",
    }
    expected: list[ExpectedObject] = []
    new_keys: list[str] = []
    for key, root_path, notes, volume, branch, leaves in (
        ("player", player_path, "玩家 Foley", -1.0, "Cloth", ("Cloth_Light", "Cloth_Heavy")),
        ("npc", npc_path, "NPC Foley", -3.0, "Armor", ("Armor_Light", "Armor_Heavy")),
    ):
        footsteps_key = f"{key}_footsteps"
        footsteps_path = root_path + r"\Footsteps"
        branch_key = f"{key}_{branch.casefold()}"
        branch_path = root_path + "\\" + branch
        expected.extend(
            (
                _expected(key, root_path, "ActorMixer", identity_policy="preserve", parent_key="foley", expected_fields=(_literal("notes", notes), _literal("@Volume", volume)), children=(footsteps_key, f"{key}_protected", branch_key)),
                _expected(footsteps_key, footsteps_path, "RandomSequenceContainer", identity_policy="preserve", parent_key=key, children=(f"{key}_walk_a", f"{key}_walk_b")),
                _expected(f"{key}_walk_b", footsteps_path + r"\Walk_B", "Sound", identity_policy="new", parent_key=footsteps_key),
                _expected(branch_key, branch_path, "RandomSequenceContainer", identity_policy="new", parent_key=key, children=tuple(f"{branch_key}_{index}" for index in range(2))),
            )
        )
        new_keys.extend((f"{key}_walk_b", branch_key))
        for index, leaf in enumerate(leaves):
            leaf_key = f"{branch_key}_{index}"
            expected.append(_expected(leaf_key, branch_path + "\\" + leaf, "Sound", identity_policy="new", parent_key=branch_key))
            new_keys.append(leaf_key)
    protected_keys = ("player_walk_a", "npc_walk_a", "player_protected", "player_protected_sound", "npc_protected", "npc_protected_sound")
    absent = (
        player_path + r"\Footsteps\Walk_B",
        player_path + r"\Cloth",
        npc_path + r"\Footsteps\Walk_B",
        npc_path + r"\Armor",
        player_path + r"\Footsteps_01",
        npc_path + r"\Footsteps_01",
    )
    return _recipe(
        "OBJ22-F-SET-04",
        OBJECT_SET_URI,
        prompt_literals=(foley_path, "Player", "NPC", "Footsteps", "Walk_A", "Walk_B", "Footsteps_01", "Cloth", "Cloth_Light", "Cloth_Heavy", "Armor", "Armor_Light", "Armor_Heavy", "玩家 Foley", "NPC Foley", "-1 dB", "-3 dB"),
        fixture=_fixture(objects, absent=absent),
        request=_operation("object.set", arguments),
        oracle=OraclePlan(
            adapter="waapi_object_readback",
            expected_objects=tuple(expected),
            preserved_keys=("player", "npc", "player_footsteps", "npc_footsteps", *protected_keys),
            new_keys=tuple(new_keys),
            protected_snapshot_keys=protected_keys,
            rules=(
                OracleRule("identity_preserved", ("player", "npc", "player_footsteps", "npc_footsteps", "player_walk_a", "npc_walk_a")),
                OracleRule("identity_new", tuple(new_keys)),
                OracleRule("no_automatic_rename", ("player_footsteps", "npc_footsteps")),
                OracleRule("protected_snapshot_unchanged", protected_keys),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB, protected=(player_path + r"\Player_Keep", npc_path + r"\NPC_Keep")),
    )


def _set_05() -> ObjectHeavyRecipe:
    ui_path = SEMANTIC_LAB + r"\UI"
    objects: list[FixtureObject] = [
        _seed("semantic", SEMANTIC_LAB, "ActorMixer"),
        _seed("ui", ui_path, "ActorMixer"),
    ]
    rows = (
        ("confirm", "Confirm", "确认反馈双层", -1.0, ("Confirm_Soft", "Confirm_Hard")),
        ("error", "Error", "错误反馈双层", -4.0, ("Error_Soft", "Error_Hard")),
    )
    for key, name, _, _, _ in rows:
        root_path = ui_path + "\\" + name
        old_layer_path = root_path + r"\Feedback_Layer"
        objects.extend(
            (
                _seed(key, root_path, "ActorMixer", notes=f"old {name}", volume=-8.0),
                _seed(f"{key}_old_layer", old_layer_path, "RandomSequenceContainer", role="protected", notes=f"old {name} feedback"),
                _seed(f"{key}_legacy", old_layer_path + r"\Legacy", "Sound", role="protected", notes=f"{name} legacy"),
                _seed(f"{key}_control", root_path + f"\\{name}_Keep", "Sound", role="protected", notes="fixture control"),
            )
        )
    request_objects: list[dict[str, Any]] = []
    expected: list[ExpectedObject] = []
    new_keys: list[str] = []
    for key, name, notes, volume, child_names in rows:
        root_path = ui_path + "\\" + name
        request_objects.append(
            {
                "object": _identity(root_path),
                "notes": notes,
                "properties": [_property("Volume", volume)],
                "children": [
                    _node("RandomSequenceContainer", "Feedback_Layer", children=tuple(_node("Sound", child) for child in child_names))
                ],
            }
        )
        layer_key = f"{key}_new_layer"
        child_keys = (f"{key}_new_soft", f"{key}_new_hard")
        expected.extend(
            (
                _expected(key, root_path, "ActorMixer", identity_policy="preserve", parent_key="ui", expected_fields=(_literal("notes", notes), _literal("@Volume", volume)), children=(f"{key}_control", f"{key}_old_layer", layer_key)),
                _expected(layer_key, None, "RandomSequenceContainer", identity_policy="new_renamed", requested_name="Feedback_Layer", parent_key=key, children=child_keys),
                _expected(child_keys[0], None, "Sound", identity_policy="new", requested_name=child_names[0], parent_key=layer_key),
                _expected(child_keys[1], None, "Sound", identity_policy="new", requested_name=child_names[1], parent_key=layer_key),
            )
        )
        new_keys.extend((layer_key, *child_keys))
    protected_keys = ("confirm_old_layer", "confirm_legacy", "confirm_control", "error_old_layer", "error_legacy", "error_control")
    return _recipe(
        "OBJ22-F-SET-05",
        OBJECT_SET_URI,
        prompt_literals=(ui_path, "Confirm", "Error", "Feedback_Layer", "Legacy", "Confirm_Soft", "Confirm_Hard", "Error_Soft", "Error_Hard", "确认反馈双层", "错误反馈双层", "-1 dB", "-4 dB"),
        fixture=_fixture(objects, prefixes=((ui_path + r"\Confirm", "Feedback_Layer"), (ui_path + r"\Error", "Feedback_Layer"))),
        request=_operation("object.set", {"objects": request_objects, "on_name_conflict": "rename"}),
        oracle=OraclePlan(
            adapter="waapi_object_readback",
            expected_objects=tuple(expected),
            preserved_keys=("confirm", "error", *protected_keys),
            new_keys=tuple(new_keys),
            protected_snapshot_keys=protected_keys,
            rules=(
                OracleRule("identity_preserved", ("confirm", "error", *protected_keys)),
                OracleRule("identity_new", tuple(new_keys)),
                OracleRule("renamed_sibling_exactly_one", ("confirm_new_layer", "error_new_layer"), (("requested_name", "Feedback_Layer"),)),
                OracleRule("protected_snapshot_unchanged", protected_keys),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB, protected=(ui_path + r"\Confirm\Feedback_Layer", ui_path + r"\Error\Feedback_Layer")),
    )


def _get_01() -> ObjectHeavyRecipe:
    combat_path = SEMANTIC_LAB + r"\Combat"
    combat_bus_path = MASTER_DWU + r"\Combat_Query_Bus"
    review_bus_path = MASTER_DWU + r"\Review_Query_Bus"
    weapons_path = combat_path + r"\Weapons"
    rifle_path = weapons_path + r"\Rifle"
    impacts_path = combat_path + r"\Impacts"
    metal_path = impacts_path + r"\Metal"
    deep_path = rifle_path + r"\Deep"
    objects = (
        _seed("combat_bus", combat_bus_path, "Bus", role="protected", notes="combat query bus"),
        _seed("review_bus", review_bus_path, "Bus", role="protected", notes="review query bus"),
        _seed("semantic", SEMANTIC_LAB, "ActorMixer"),
        _seed("combat", combat_path, "ActorMixer", notes="query root"),
        _seed("weapons", weapons_path, "ActorMixer", notes="weapons level one"),
        _seed("rifle", rifle_path, "RandomSequenceContainer", notes="rifle level two"),
        _seed("rifle_close", rifle_path + r"\Rifle_Close", "Sound", notes="close shot", volume=-8.0, output_bus="combat_bus", language="SFX"),
        _seed("rifle_tail", rifle_path + r"\Rifle_Tail", "Sound", notes="needs-review tail", volume=-2.0, output_bus="review_bus", language="SFX"),
        _seed("rifle_ok", rifle_path + r"\Rifle_OK", "Sound", role="decoy", notes="approved", volume=-2.0, output_bus="combat_bus", language="SFX"),
        _seed("deep", deep_path, "RandomSequenceContainer", notes="depth three"),
        _seed("depth_four_match", deep_path + r"\Depth_Four_Review", "Sound", role="decoy", notes="needs-review true-match decoy", volume=-10.0, output_bus="review_bus", language="SFX"),
        _seed("impacts", impacts_path, "ActorMixer", notes="impacts level one"),
        _seed("metal", metal_path, "RandomSequenceContainer", notes="metal level two"),
        _seed("metal_heavy", metal_path + r"\Metal_Heavy", "Sound", notes="heavy impact", volume=-7.0, output_bus="combat_bus", language="SFX"),
        _seed("metal_light", metal_path + r"\Metal_Light", "Sound", notes="needs-review transient", volume=-1.0, output_bus="review_bus", language="SFX"),
        _seed("metal_ok", metal_path + r"\Metal_OK", "Sound", role="decoy", notes="approved", volume=-1.0, output_bus="combat_bus", language="SFX"),
    )
    return_fields = ("id", "name", "type", "path", "@Volume", "notes", "OutputBus")
    exact_keys = tuple(
        sorted(
            ("rifle_close", "rifle_tail", "metal_heavy", "metal_light"),
            key=lambda key: next(item.path for item in objects if item.key == key),
        )
    )
    superset_keys = tuple(
        item.key
        for item in objects
        if item.object_type == "Sound" and item.path.startswith(combat_path + "\\")
    )
    expected = tuple(
        _expected_from_seed(
            next(item for item in objects if item.key == key),
            objects,
            return_fields=return_fields,
        )
        for key in exact_keys
    )
    final_filter = FinalAnswerFilter(
        combine="any_with_required",
        required=(FinalFilterRule("path", "relative_depth_at_most", 3),),
        any_of=(
            FinalFilterRule("@Volume", "less_than", -6.0),
            FinalFilterRule("notes", "contains", "needs-review"),
        ),
        sort_by=("path",),
    )
    return _recipe(
        "OBJ22-F-GET-01",
        OBJECT_GET_URI,
        prompt_literals=(combat_path, "三层以内", "Sound", "-6 dB", "needs-review", "完整路径", "Output Bus", "24 条"),
        fixture=_fixture(objects),
        request=_query(
            source=("--path", combat_path),
            selects=("descendants",),
            predicates=({"field": "type", "operator": "=", "value": "Sound"},),
            take=24,
            return_fields=return_fields,
            strategy="bounded_superset_final_answer_filter",
            exact_keys=exact_keys,
            superset_keys=superset_keys,
            final_filter=final_filter,
        ),
        oracle=OraclePlan(
            adapter="waapi_object_query_readback",
            expected_objects=expected,
            exact_row_keys=exact_keys,
            expected_order_keys=exact_keys,
            excluded_keys=tuple(key for key in superset_keys if key not in exact_keys),
            preserved_keys=tuple(item.key for item in objects),
            protected_snapshot_keys=tuple(item.key for item in objects),
            rules=(
                OracleRule("final_answer_filters_superset", exact_keys, (("raw_superset_count", len(superset_keys)), ("exact_count", len(exact_keys)))),
                OracleRule("query_rows_exact", exact_keys),
                OracleRule("answer_order_equal", exact_keys),
                OracleRule("answer_counts_equal", exact_keys, (("Sound", 4),)),
                OracleRule("protected_snapshot_unchanged", tuple(item.key for item in objects)),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB, combat_bus_path, review_bus_path),
    )


def _get_02() -> ObjectHeavyRecipe:
    hero_path = SEMANTIC_LAB + r"\VO_Hero"
    npc_path = SEMANTIC_LAB + r"\VO_NPC"
    nested_path = hero_path + r"\Nested"
    objects = (
        _seed("semantic", SEMANTIC_LAB, "ActorMixer", notes="query root"),
        _seed("vo_hero", hero_path, "RandomSequenceContainer", notes="hero VO", volume=-1.0),
        _seed("hero_greeting", hero_path + r"\Greeting", "Sound", notes="hero greeting", volume=-2.0, language="English(US)"),
        _seed("hero_damage", hero_path + r"\Damage", "Sound", notes="hero damage", volume=-4.0, language="Japanese"),
        _seed("hero_nested", nested_path, "RandomSequenceContainer", role="decoy", notes="nested group"),
        _seed("hero_nested_line", nested_path + r"\Nested_Line", "Sound", role="decoy", notes="not direct", volume=-6.0, language="English(US)"),
        _seed("vo_npc", npc_path, "RandomSequenceContainer", notes="npc VO", volume=-2.0),
        _seed("npc_alert", npc_path + r"\Alert", "Sound", notes="npc alert", volume=-3.0, language="Japanese"),
        _seed("npc_idle", npc_path + r"\Idle", "Sound", notes="npc idle", volume=-1.0, language="English(US)"),
        _seed("vox_parent", SEMANTIC_LAB + r"\VOX_NotPrefix", "RandomSequenceContainer", role="decoy", notes="prefix decoy"),
        _seed("vox_child", SEMANTIC_LAB + r"\VOX_NotPrefix\Line", "Sound", role="decoy", notes="prefix decoy child", volume=-2.0, language="English(US)"),
        _seed("music_parent", SEMANTIC_LAB + r"\Music", "RandomSequenceContainer", role="decoy", notes="name decoy"),
        _seed("music_child", SEMANTIC_LAB + r"\Music\Line", "Sound", role="decoy", notes="name decoy child", volume=-2.0, language="SFX"),
        _seed("vo_wrong_type", SEMANTIC_LAB + r"\VO_WrongType", "ActorMixer", role="decoy", notes="type decoy"),
        _seed("vo_wrong_child", SEMANTIC_LAB + r"\VO_WrongType\Line", "Sound", role="decoy", notes="type decoy child", volume=-2.0, language="English(US)"),
    )
    return_fields = (
        "id",
        "name",
        "type",
        "path",
        "parent",
        "audioSource:language",
        "@Volume",
        "notes",
    )
    exact_keys = (
        "vo_hero",
        "hero_damage",
        "hero_greeting",
        "vo_npc",
        "npc_alert",
        "npc_idle",
    )
    superset_keys = tuple(item.key for item in objects if item.key != "semantic")
    expected = tuple(
        _expected_from_seed(
            next(item for item in objects if item.key == key),
            objects,
            return_fields=return_fields,
        )
        for key in exact_keys
    )
    final_filter = FinalAnswerFilter(
        combine="any_with_required",
        any_of=(
            FinalFilterRule("record", "is_vo_random_container", True),
            FinalFilterRule("record", "is_direct_sound_child_of_vo_container", True),
        ),
        sort_by=("parent.path", "name"),
    )
    return _recipe(
        "OBJ22-F-GET-02",
        OBJECT_GET_URI,
        prompt_literals=(SEMANTIC_LAB, "VO_", "随机容器", "直接子", "Sound", "父容器和子 Sound 各自的完整路径", "语言", "音量", "备注", "24 条"),
        fixture=_fixture(objects),
        request=_query(
            source=("--path", SEMANTIC_LAB),
            selects=("descendants",),
            take=24,
            return_fields=return_fields,
            strategy="bounded_superset_final_answer_filter",
            exact_keys=exact_keys,
            superset_keys=superset_keys,
            final_filter=final_filter,
            derived_row_policy="active_audio_sources_for_sound_rows",
            final_answer_policy="paired_path_rows",
        ),
        oracle=OraclePlan(
            adapter="waapi_object_query_readback",
            expected_objects=expected,
            exact_row_keys=exact_keys,
            expected_order_keys=exact_keys,
            excluded_keys=tuple(key for key in superset_keys if key not in exact_keys),
            preserved_keys=tuple(item.key for item in objects),
            protected_snapshot_keys=tuple(item.key for item in objects),
            rules=(
                OracleRule("final_answer_filters_superset", exact_keys, (("raw_superset_count", len(superset_keys)), ("container_count", 2), ("direct_sound_count", 4))),
                OracleRule("query_rows_exact", exact_keys),
                OracleRule("answer_order_equal", exact_keys),
                OracleRule("protected_snapshot_unchanged", tuple(item.key for item in objects)),
            ),
        ),
        cleanup=_cleanup(SEMANTIC_LAB),
    )


def _get_03() -> ObjectHeavyRecipe:
    root_path = ACTOR_DWU + r"\SemanticLab_Query03"
    combat_path = root_path + r"\CombatMix"
    close_path = combat_path + r"\Close"
    distant_path = combat_path + r"\Distant"
    deep_path = distant_path + r"\Deep"
    outside_path = root_path + r"\OutsideMix"
    bus_a_path = MASTER_DWU + r"\Query03_Bus_A"
    bus_b_path = MASTER_DWU + r"\Query03_Bus_B"
    objects: list[FixtureObject] = [
        _seed("q3_bus_a", bus_a_path, "Bus", role="protected", notes="query03 A"),
        _seed("q3_bus_b", bus_b_path, "Bus", role="protected", notes="query03 B"),
        _seed("q3_root", root_path, "ActorMixer", notes="query03 root"),
        _seed("q3_combat", combat_path, "ActorMixer", notes="combat mix root"),
        _seed("q3_close", close_path, "RandomSequenceContainer", notes="close group"),
        _seed("q3_distant", distant_path, "RandomSequenceContainer", notes="distant group"),
        _seed("q3_deep", deep_path, "RandomSequenceContainer", notes="deep group"),
        _seed("q3_outside", outside_path, "ActorMixer", role="decoy", notes="outside control"),
    ]
    matches = (
        ("q3_match_01", close_path + r"\Rifle_Close", -6.0, "mix-review rifle close", "q3_bus_a", "SFX"),
        ("q3_match_02", close_path + r"\Shotgun_Close", -7.0, "mix-review shotgun close", "q3_bus_a", "SFX"),
        ("q3_match_03", close_path + r"\Impact_Close", -8.0, "mix-review impact", "q3_bus_a", "English(US)"),
        ("q3_match_04", distant_path + r"\Rifle_Tail", -9.0, "mix-review rifle tail", "q3_bus_a", "SFX"),
        ("q3_match_05", distant_path + r"\Shotgun_Tail", -10.0, "mix-review shotgun tail", "q3_bus_a", "English(US)"),
        ("q3_match_06", distant_path + r"\Wind_Layer", -6.0, "mix-review wind", "q3_bus_b", "SFX"),
        ("q3_match_07", deep_path + r"\Thunder_Layer", -11.0, "mix-review thunder", "q3_bus_b", "SFX"),
        ("q3_match_08", deep_path + r"\Debris_Layer", -12.0, "mix-review debris", "q3_bus_b", "English(US)"),
    )
    for key, path, volume, notes, bus, language in matches:
        objects.append(_seed(key, path, "Sound", notes=notes, volume=volume, output_bus=bus, language=language, included=True))
    decoys = (
        _seed("q3_decoy_type", combat_path + r"\Wrong_Type", "ActorMixer", role="decoy", notes="mix-review type", volume=-8.0, output_bus="q3_bus_a", included=True),
        _seed("q3_decoy_volume", close_path + r"\Wrong_Volume", "Sound", role="decoy", notes="mix-review volume", volume=-5.0, output_bus="q3_bus_a", language="SFX", included=True),
        _seed("q3_decoy_notes", close_path + r"\Wrong_Notes", "Sound", role="decoy", notes="approved", volume=-8.0, output_bus="q3_bus_a", language="SFX", included=True),
        _seed("q3_decoy_included", close_path + r"\Wrong_Inclusion", "Sound", role="decoy", notes="mix-review excluded", volume=-8.0, output_bus="q3_bus_a", language="SFX", included=False),
        _seed("q3_decoy_volume_2", distant_path + r"\Wrong_Volume_2", "Sound", role="decoy", notes="mix-review second", volume=-1.0, output_bus="q3_bus_b", language="SFX", included=True),
        _seed("q3_decoy_notes_2", distant_path + r"\Wrong_Notes_2", "Sound", role="decoy", notes="clean", volume=-9.0, output_bus="q3_bus_b", language="SFX", included=True),
        _seed("q3_decoy_included_2", deep_path + r"\Wrong_Inclusion_2", "Sound", role="decoy", notes="mix-review hidden", volume=-9.0, output_bus="q3_bus_b", language="SFX", included=False),
        _seed("q3_decoy_outside", outside_path + r"\Outside_Match", "Sound", role="decoy", notes="mix-review outside", volume=-9.0, output_bus="q3_bus_b", language="SFX", included=True),
    )
    objects.extend(decoys)
    return_fields = ("id", "name", "type", "path", "@Volume", "notes", "audioSource:language", "OutputBus", "isIncluded")
    exact_keys = tuple(key for key, *_ in sorted(matches, key=lambda row: row[1]))
    expected = tuple(
        _expected_from_seed(next(item for item in objects if item.key == key), objects, return_fields=return_fields)
        for key in exact_keys
    )
    predicates = (
        {"field": "type", "operator": "=", "value": "Sound"},
        {"field": "@Volume", "operator": "<=", "value": -6.0},
        {"field": "notes", "operator": ":", "value": "mix-review"},
        {"field": "isIncluded", "operator": "=", "value": True},
    )
    return _recipe(
        "OBJ22-F-GET-03",
        OBJECT_GET_URI,
        prompt_literals=(combat_path, "Sound", "-6 dB", "mix-review", "12 条", "Output Bus"),
        fixture=_fixture(objects),
        request=_query(
            source=("--path", combat_path),
            selects=("descendants",),
            predicates=predicates,
            take=12,
            return_fields=return_fields,
            strategy="exact_rows",
            exact_keys=exact_keys,
            superset_keys=exact_keys,
            final_filter=FinalAnswerFilter(combine="identity", sort_by=("path",)),
        ),
        oracle=OraclePlan(
            adapter="waapi_object_query_readback",
            expected_objects=expected,
            exact_row_keys=exact_keys,
            expected_order_keys=exact_keys,
            excluded_keys=tuple(item.key for item in decoys),
            preserved_keys=tuple(item.key for item in objects),
            protected_snapshot_keys=tuple(item.key for item in objects),
            rules=(
                OracleRule("query_rows_exact", exact_keys),
                OracleRule("answer_order_equal", exact_keys),
                OracleRule("answer_counts_equal", exact_keys, (("q3_bus_a", 5), ("q3_bus_b", 3), ("total", 8))),
                OracleRule("bound_reached_equal", exact_keys, (("take", 12), ("reached", False))),
                OracleRule("protected_snapshot_unchanged", tuple(item.key for item in objects)),
            ),
        ),
        cleanup=_cleanup(root_path, bus_a_path, bus_b_path),
    )


def _get_04() -> ObjectHeavyRecipe:
    root_path = ACTOR_DWU + r"\SemanticLab_Query04"
    review_path = root_path + r"\ParentReview"
    outside_path = root_path + r"\OutsideReview"
    bus_a_path = MASTER_DWU + r"\Query04_Bus_A"
    bus_b_path = MASTER_DWU + r"\Query04_Bus_B"
    objects: list[FixtureObject] = [
        _seed("q4_bus_a", bus_a_path, "Bus", role="protected", notes="query04 A"),
        _seed("q4_bus_b", bus_b_path, "Bus", role="protected", notes="query04 B"),
        _seed("q4_root", root_path, "ActorMixer", notes="query04 root"),
        _seed("q4_review", review_path, "ActorMixer", notes="parent review root"),
        _seed("q4_outside", outside_path, "ActorMixer", role="decoy", notes="outside root"),
    ]
    matching = (
        ("q4_pistol", "Pistol", 3, "q4_bus_a"),
        ("q4_rifle", "Rifle", 4, "q4_bus_a"),
        ("q4_shotgun", "Shotgun", 5, "q4_bus_b"),
    )
    direct_edges: list[tuple[str, str]] = []
    for parent_key, name, count, bus in matching:
        parent_path = review_path + "\\" + name
        objects.append(_seed(parent_key, parent_path, "RandomSequenceContainer", notes=f"parent-review {name}", output_bus=bus))
        for index in range(1, count + 1):
            child_key = f"{parent_key}_sound_{index}"
            objects.append(_seed(child_key, parent_path + f"\\{name}_{index}", "Sound", notes=f"{name} child {index}", volume=-float(index), language="SFX"))
            direct_edges.append((parent_key, child_key))
    two_path = review_path + r"\TwoChild"
    objects.extend(
        (
            _seed("q4_decoy_two", two_path, "RandomSequenceContainer", role="decoy", notes="parent-review too small", output_bus="q4_bus_a"),
            _seed("q4_decoy_two_1", two_path + r"\One", "Sound", role="decoy", notes="one", language="SFX"),
            _seed("q4_decoy_two_2", two_path + r"\Two", "Sound", role="decoy", notes="two", language="SFX"),
        )
    )
    wrong_type_path = review_path + r"\WrongType"
    objects.append(_seed("q4_decoy_type", wrong_type_path, "ActorMixer", role="decoy", notes="parent-review wrong type", output_bus="q4_bus_a"))
    for index in range(3):
        objects.append(_seed(f"q4_decoy_type_{index}", wrong_type_path + f"\\Sound_{index}", "Sound", role="decoy", notes="wrong type child", language="SFX"))
    outside_parent_path = outside_path + r"\OutsideQualified"
    objects.append(_seed("q4_decoy_outside", outside_parent_path, "RandomSequenceContainer", role="decoy", notes="parent-review outside", output_bus="q4_bus_b"))
    for index in range(3):
        objects.append(_seed(f"q4_decoy_outside_{index}", outside_parent_path + f"\\Sound_{index}", "Sound", role="decoy", notes="outside child", language="SFX"))
    indirect_path = review_path + r"\IndirectOnly"
    nested_path = indirect_path + r"\Nested"
    objects.extend(
        (
            _seed("q4_decoy_indirect", indirect_path, "RandomSequenceContainer", role="decoy", notes="parent-review indirect", output_bus="q4_bus_b"),
            _seed("q4_decoy_nested", nested_path, "RandomSequenceContainer", role="decoy", notes="nested parent"),
            _seed("q4_decoy_nested_sound", nested_path + r"\Indirect_Sound", "Sound", role="decoy", notes="indirect sound", language="SFX"),
        )
    )
    return_fields = ("id", "name", "type", "path", "childrenCount", "notes", "OutputBus")
    exact_keys = tuple(key for key, _, _, _ in matching)
    expected = tuple(
        _expected_from_seed(next(item for item in objects if item.key == key), objects, return_fields=return_fields)
        for key in exact_keys
    )
    predicates = (
        {"field": "path", "operator": ":", "value": review_path},
        {"field": "type", "operator": "=", "value": "RandomSequenceContainer"},
        {"field": "childrenCount", "operator": ">=", "value": 3},
        {"field": "notes", "operator": ":", "value": "parent-review"},
    )
    decoy_keys = tuple(item.key for item in objects if item.role == "decoy")
    return _recipe(
        "OBJ22-F-GET-04",
        OBJECT_GET_URI,
        prompt_literals=(review_path, "Sound", "直接父级", "Random Container", "3 个", "parent-review", "10 个", "去重"),
        fixture=_fixture(objects),
        request=_query(
            source=("--type", "Sound"),
            selects=("parent",),
            predicates=predicates,
            take=10,
            return_fields=return_fields,
            strategy="exact_rows",
            exact_keys=exact_keys,
            superset_keys=exact_keys,
            final_filter=FinalAnswerFilter(combine="identity", sort_by=("path",)),
            primary_row_policy="parent_projection_per_source_row",
            final_answer_policy="deduplicated_parent_summary",
        ),
        oracle=OraclePlan(
            adapter="waapi_object_query_readback",
            expected_objects=expected,
            exact_row_keys=exact_keys,
            expected_order_keys=exact_keys,
            excluded_keys=decoy_keys,
            preserved_keys=tuple(item.key for item in objects),
            protected_snapshot_keys=tuple(item.key for item in objects),
            rules=(
                OracleRule("query_rows_exact", exact_keys),
                OracleRule("answer_order_equal", exact_keys),
                OracleRule(
                    "answer_counts_equal",
                    exact_keys,
                    (
                        ("unique_parents", 3),
                        ("returned_sound_edges", 10),
                        ("direct_child_objects", len(direct_edges)),
                        ("fixture_eligible_sound_edges", len(direct_edges)),
                    ),
                ),
                OracleRule("bound_reached_equal", exact_keys, (("take", 10), ("reached", True))),
                OracleRule("protected_snapshot_unchanged", tuple(item.key for item in objects)),
            ),
        ),
        cleanup=_cleanup(root_path, bus_a_path, bus_b_path),
    )


def _get_05() -> ObjectHeavyRecipe:
    root_path = ACTOR_DWU + r"\SemanticLab_Query05"
    player_path = root_path + r"\Player"
    movement_path = player_path + r"\Movement"
    target_path = movement_path + r"\Footstep_Run"
    objects = (
        _seed("actor_root", ACTOR_ROOT, "WorkUnit", role="borrowed"),
        _seed("actor_dwu", ACTOR_DWU, "WorkUnit", role="borrowed"),
        _seed("q5_root", root_path, "ActorMixer", notes="query05 root"),
        _seed("q5_player", player_path, "ActorMixer", notes="player owner"),
        _seed("q5_movement", movement_path, "RandomSequenceContainer", notes="movement owner"),
        _seed("q5_target", target_path, "Sound", notes="target footstep", volume=-3.0, language="SFX"),
        _seed("q5_player_keep", player_path + r"\Player_Keep", "Sound", role="decoy", notes="player sibling", language="SFX"),
        _seed("q5_decoy_movement", root_path + r"\Movement", "RandomSequenceContainer", role="decoy", notes="same-name movement"),
        _seed("q5_decoy_target", root_path + r"\Movement\Footstep_Run", "Sound", role="decoy", notes="same-name target", language="SFX"),
        _seed("q5_decoy_player", ACTOR_DWU + r"\Player", "ActorMixer", role="decoy", notes="same-name player"),
        _seed("q5_decoy_player_movement", ACTOR_DWU + r"\Player\Movement", "RandomSequenceContainer", role="decoy", notes="unrelated movement"),
        _seed("q5_decoy_player_target", ACTOR_DWU + r"\Player\Movement\Footstep_Run", "Sound", role="decoy", notes="unrelated target", language="SFX"),
        _seed("q5_deeper_branch", movement_path + r"\Deeper", "RandomSequenceContainer", role="decoy", notes="non-ancestor deeper"),
        _seed("q5_deeper_target", movement_path + r"\Deeper\Footstep_Run", "Sound", role="decoy", notes="deep non-ancestor", language="SFX"),
    )
    return_fields = ("id", "name", "type", "path", "childrenCount", "notes")
    exact_keys = ("q5_movement", "q5_player", "q5_root", "actor_dwu", "actor_root")
    expected = tuple(
        _expected_from_seed(next(item for item in objects if item.key == key), objects, return_fields=return_fields)
        for key in exact_keys
    )
    decoy_keys = tuple(item.key for item in objects if item.role == "decoy")
    return _recipe(
        "OBJ22-F-GET-05",
        OBJECT_GET_URI,
        prompt_literals=(target_path, "直接父级", "排除 Project", "8 层", "Random Container", "两个 Actor Mixer", "Default Work Unit"),
        fixture=_fixture(objects),
        request=_query(
            source=("--path", target_path),
            selects=("ancestors",),
            predicates=({"field": "type", "operator": "!=", "value": "Project"},),
            take=8,
            return_fields=return_fields,
            strategy="exact_rows",
            exact_keys=exact_keys,
            superset_keys=exact_keys,
            final_filter=FinalAnswerFilter(combine="identity", sort_by=("sealed_direct_parent_distance",)),
            primary_row_policy="ancestor_identity_rows",
            final_answer_policy="ordered_ancestor_summary",
        ),
        oracle=OraclePlan(
            adapter="waapi_object_query_readback",
            expected_objects=expected,
            exact_row_keys=exact_keys,
            expected_order_keys=exact_keys,
            excluded_keys=decoy_keys,
            preserved_keys=tuple(item.key for item in objects),
            protected_snapshot_keys=tuple(item.key for item in objects),
            rules=(
                OracleRule("query_rows_exact", exact_keys),
                OracleRule("answer_order_equal", exact_keys),
                OracleRule(
                    "answer_counts_equal",
                    exact_keys,
                    (
                        ("RandomSequenceContainer", 1),
                        ("ActorMixer", 2),
                        ("WorkUnit", 2),
                        ("Default Work Unit", 1),
                    ),
                ),
                OracleRule("bound_reached_equal", exact_keys, (("take", 8), ("reached", False))),
                OracleRule("protected_snapshot_unchanged", tuple(item.key for item in objects)),
            ),
        ),
        cleanup=_cleanup(root_path, protected=(ACTOR_DWU, ACTOR_ROOT)),
    )


_FORBIDDEN_OPERATION_KEY_FRAGMENTS = (
    "callback",
    "script",
    "code",
    "hook",
    "command",
    "custom",
)
_FORBIDDEN_ARGV_TOKENS = (";", "&&", "||", "|", "`", "$(", "\n", "\r")


def _validate_recipe(recipe: ObjectHeavyRecipe) -> None:
    if recipe.contract != OBJECT_HEAVY_RECIPE_CONTRACT:
        raise ObjectHeavyRecipeError(f"{recipe.scenario_id} has the wrong contract")
    if recipe.scenario_id not in OBJECT_HEAVY_CASE_IDS:
        raise ObjectHeavyRecipeError(f"unknown object-heavy scenario: {recipe.scenario_id}")
    try:
        get_codex_version_layout_v3(recipe.version)
    except CodexVersionLayoutError as exc:
        raise ObjectHeavyRecipeError(str(exc)) from exc
    if (
        recipe.version != VERSION
        and recipe.scenario_id not in OBJECT_COMPOUND_CROSS_VERSION_CASE_IDS
    ):
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} is not approved for Wwise {recipe.version}"
        )
    expected_api = (
        OBJECT_CREATE_URI
        if recipe.scenario_id in OBJECT_CREATE_CASE_IDS
        else OBJECT_GET_URI
        if recipe.scenario_id in OBJECT_GET_CASE_IDS
        else OBJECT_SET_URI
    )
    if recipe.api != expected_api:
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} API mismatch: {recipe.api!r} != {expected_api!r}"
        )
    if not recipe.prompt_literals or any(
        not isinstance(item, str) or not item for item in recipe.prompt_literals
    ):
        raise ObjectHeavyRecipeError(f"{recipe.scenario_id} prompt literals are not closed")

    fixture_keys = tuple(item.key for item in recipe.fixture.objects)
    fixture_paths = tuple(item.path for item in recipe.fixture.objects)
    if len(fixture_keys) != len(set(fixture_keys)):
        raise ObjectHeavyRecipeError(f"{recipe.scenario_id} fixture keys are not unique")
    if len(fixture_paths) != len(set(fixture_paths)):
        raise ObjectHeavyRecipeError(f"{recipe.scenario_id} fixture paths are not unique")
    if set(recipe.fixture.absent_paths) & set(fixture_paths):
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} marks a materialized fixture path absent"
        )
    fixture_by_path = {item.path: item for item in recipe.fixture.objects}
    for item in recipe.fixture.objects:
        if not item.path.startswith("\\") or "\\\\" in item.path:
            raise ObjectHeavyRecipeError(
                f"{recipe.scenario_id} has a non-canonical Wwise path: {item.path!r}"
            )
        parent = fixture_by_path.get(item.path.rsplit("\\", 1)[0])
        if (
            parent is not None
            and parent.object_type == "RandomSequenceContainer"
            and item.object_type == "ActorMixer"
        ):
            raise ObjectHeavyRecipeError(
                f"{recipe.scenario_id} fixture has a Wwise-invalid "
                f"RandomSequenceContainer -> ActorMixer edge: {parent.key} -> {item.key}"
            )
        for reference in item.references:
            if reference.target_key not in fixture_keys:
                raise ObjectHeavyRecipeError(
                    f"{recipe.scenario_id} {item.key} references unknown key {reference.target_key}"
                )

    expected_keys = tuple(item.key for item in recipe.oracle.expected_objects)
    if len(expected_keys) != len(set(expected_keys)):
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} expected object keys are not unique"
        )
    for name, values in (
        ("preserved", recipe.oracle.preserved_keys),
        ("removed", recipe.oracle.removed_keys),
        ("protected", recipe.oracle.protected_snapshot_keys),
        ("excluded", recipe.oracle.excluded_keys),
    ):
        unknown = sorted(set(values) - set(fixture_keys))
        if unknown:
            raise ObjectHeavyRecipeError(
                f"{recipe.scenario_id} {name} keys are not fixture-bound: {unknown}"
            )
    unknown_new = sorted(set(recipe.oracle.new_keys) - set(expected_keys))
    if unknown_new:
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} new keys lack expected objects: {unknown_new}"
        )
    if set(recipe.oracle.new_keys) & set(recipe.oracle.preserved_keys):
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} new and preserved identities overlap"
        )

    for root in (*recipe.cleanup.owned_object_roots, *recipe.cleanup.protected_object_roots):
        if not root.startswith("\\") or "\\\\" in root:
            raise ObjectHeavyRecipeError(
                f"{recipe.scenario_id} cleanup root is not a canonical Wwise path: {root!r}"
            )
    if not recipe.cleanup.owned_object_roots:
        raise ObjectHeavyRecipeError(f"{recipe.scenario_id} lacks owned cleanup roots")

    if isinstance(recipe.request, OperationRequestSpec):
        if recipe.scenario_id in OBJECT_GET_CASE_IDS:
            raise ObjectHeavyRecipeError(f"{recipe.scenario_id} must use query-object")
        expected_operation = (
            "object.create"
            if recipe.scenario_id in OBJECT_CREATE_CASE_IDS
            else "object.set"
        )
        if recipe.request.operation != expected_operation:
            raise ObjectHeavyRecipeError(
                f"{recipe.scenario_id} operation mismatch: {recipe.request.operation}"
            )
        payload = recipe.request.as_dict(version=recipe.version)
        _reject_executable_request_values(payload, path="$request")
        if recipe.oracle.exact_row_keys:
            raise ObjectHeavyRecipeError(
                f"{recipe.scenario_id} mutation cannot declare query rows"
            )
    elif isinstance(recipe.request, QueryObjectRequestSpec):
        if recipe.scenario_id not in OBJECT_GET_CASE_IDS:
            raise ObjectHeavyRecipeError(f"{recipe.scenario_id} must use an operation request")
        _validate_query_request(recipe)
    else:  # pragma: no cover - static union plus constructor coverage.
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} has an unsupported request type"
        )
    _reject_callables(recipe, path="$recipe")


def _validate_query_request(recipe: ObjectHeavyRecipe) -> None:
    assert isinstance(recipe.request, QueryObjectRequestSpec)
    request = recipe.request
    argv = request.argv
    if argv[:4] != ("gateway.py", "--version", recipe.version, "query-object"):
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} query must use the packaged query-object route"
        )
    if argv.count("query-object") != 1 or argv.count("--take") != 1:
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} query must be one explicitly bounded command"
        )
    take_index = argv.index("--take")
    if argv[take_index + 1] != str(request.take) or not 1 <= request.take <= 1000:
        raise ObjectHeavyRecipeError(f"{recipe.scenario_id} query take is inconsistent")
    if "--all-results" in argv or "--args-json" in argv or "--options-json" in argv:
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} query bypasses the bounded query-object builder"
        )
    argv_return_fields = tuple(
        argv[index + 1]
        for index, item in enumerate(argv)
        if item == "--return-field"
    )
    if argv_return_fields != request.return_fields or not request.return_fields:
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} query return fields are inconsistent"
        )
    if any(token in argument for argument in argv for token in _FORBIDDEN_ARGV_TOKENS):
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} query argv contains shell composition"
        )
    fixture_keys = {item.key for item in recipe.fixture.objects}
    exact = set(request.exact_expected_keys)
    superset = set(request.bounded_superset_keys)
    if not exact or not exact <= superset or not superset <= fixture_keys:
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} exact/superset keys are not closed by the fixture"
        )
    if tuple(request.exact_expected_keys) != recipe.oracle.exact_row_keys:
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} request and oracle exact rows differ"
        )
    expected_object_keys = {item.key for item in recipe.oracle.expected_objects}
    if exact != expected_object_keys:
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} exact rows lack hidden expected objects"
        )
    if request.result_strategy == "bounded_superset_final_answer_filter":
        if recipe.scenario_id not in {"OBJ22-F-GET-01", "OBJ22-F-GET-02"}:
            raise ObjectHeavyRecipeError(
                f"{recipe.scenario_id} is not approved for model-side superset filtering"
            )
        if exact == superset or request.final_filter.combine == "identity":
            raise ObjectHeavyRecipeError(
                f"{recipe.scenario_id} superset strategy lacks an explicit filter"
            )
    elif request.result_strategy == "exact_rows":
        if exact != superset or request.final_filter.combine != "identity":
            raise ObjectHeavyRecipeError(
                f"{recipe.scenario_id} exact query cannot declare a wider superset"
            )
    else:  # pragma: no cover - Literal plus constructor coverage.
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} has an unknown result strategy"
        )
    if recipe.scenario_id == "OBJ22-F-GET-02":
        if (
            request.primary_row_policy != "unique_identity_rows"
            or request.derived_row_policy != "active_audio_sources_for_sound_rows"
            or request.final_answer_policy != "paired_path_rows"
        ):
            raise ObjectHeavyRecipeError(
                "OBJ22-F-GET-02 must bind its active-source and paired-answer policies"
            )
        fixture_by_key = {item.key: item for item in recipe.fixture.objects}
        source_sounds = tuple(
            fixture_by_key[key]
            for key in request.bounded_superset_keys
            if fixture_by_key[key].object_type == "Sound"
        )
        if not source_sounds or any(
            item.source_language is None for item in source_sounds
        ):
            raise ObjectHeavyRecipeError(
                "OBJ22-F-GET-02 derived sources require language-bound superset Sounds"
            )
    elif recipe.scenario_id == "OBJ22-F-GET-04":
        if (
            request.primary_row_policy != "parent_projection_per_source_row"
            or request.derived_row_policy != "none"
            or request.final_answer_policy != "deduplicated_parent_summary"
        ):
            raise ObjectHeavyRecipeError(
                "OBJ22-F-GET-04 must bind its parent-projection and deduplicated-answer policies"
            )
        fixture_by_key = {item.key: item for item in recipe.fixture.objects}
        exact_parent_paths = {
            fixture_by_key[key].path for key in request.exact_expected_keys
        }
        direct_sounds = tuple(
            item
            for item in recipe.fixture.objects
            if item.object_type == "Sound"
            and item.path.rsplit("\\", 1)[0] in exact_parent_paths
        )
        if (
            len(direct_sounds) <= request.take
            or request.take
            <= len(direct_sounds)
            - min(
                sum(
                    item.path.rsplit("\\", 1)[0] == parent_path
                    for item in direct_sounds
                )
                for parent_path in exact_parent_paths
            )
        ):
            raise ObjectHeavyRecipeError(
                "OBJ22-F-GET-04 fixture/take cannot prove bounded duplicate parent coverage"
            )
    elif recipe.scenario_id == "OBJ22-F-GET-05":
        if (
            request.primary_row_policy != "ancestor_identity_rows"
            or request.derived_row_policy != "none"
            or request.final_answer_policy != "ordered_ancestor_summary"
        ):
            raise ObjectHeavyRecipeError(
                "OBJ22-F-GET-05 must bind its ordered ancestor evidence policies"
            )
        fixture_by_key = {item.key: item for item in recipe.fixture.objects}
        if (
            tuple(request.exact_expected_keys)
            != tuple(recipe.oracle.expected_order_keys)
            or any(
                fixture_by_key[child].parent_path != fixture_by_key[parent].path
                for child, parent in zip(
                    ("q5_target", *request.exact_expected_keys[:-1]),
                    request.exact_expected_keys,
                    strict=True,
                )
            )
        ):
            raise ObjectHeavyRecipeError(
                "OBJ22-F-GET-05 ordered ancestors are not one closed ownership chain"
            )
    elif (
        request.primary_row_policy != "unique_identity_rows"
        or request.derived_row_policy != "none"
        or request.final_answer_policy != "name_and_id"
    ):
        raise ObjectHeavyRecipeError(
            f"{recipe.scenario_id} may not opt into specialized query evidence policies"
        )


def _reject_executable_request_values(value: Any, *, path: str) -> None:
    if callable(value):
        raise ObjectHeavyRecipeError(f"{path} contains a callable")
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(fragment in normalized for fragment in _FORBIDDEN_OPERATION_KEY_FRAGMENTS):
                raise ObjectHeavyRecipeError(
                    f"{path}.{key} is an executable extension field"
                )
            _reject_executable_request_values(item, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_executable_request_values(item, path=f"{path}[{index}]")


def _reject_callables(value: Any, *, path: str) -> None:
    if callable(value):
        raise ObjectHeavyRecipeError(f"{path} contains a callable")
    if is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            _reject_callables(getattr(value, item.name), path=f"{path}.{item.name}")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _reject_callables(item, path=f"{path}.{key}")
    elif isinstance(value, tuple):
        for index, item in enumerate(value):
            _reject_callables(item, path=f"{path}[{index}]")


_RECIPE_SEQUENCE = (
    _create_01(),
    _create_02(),
    _create_03(),
    _create_04(),
    _create_05(),
    _get_01(),
    _get_02(),
    _get_03(),
    _get_04(),
    _get_05(),
    _set_01(),
    _set_02(),
    _set_03(),
    _set_04(),
    _set_05(),
)
_RECIPES: Mapping[str, ObjectHeavyRecipe] = MappingProxyType(
    {item.scenario_id: item for item in _RECIPE_SEQUENCE}
)
if tuple(_RECIPES) != OBJECT_HEAVY_CASE_IDS:  # pragma: no cover - import-time seal.
    raise ObjectHeavyRecipeError("object-heavy recipe registry order or coverage drifted")

_CROSS_VERSION_RECIPES: Mapping[tuple[str, str], ObjectHeavyRecipe] = (
    MappingProxyType(
        {
            (scenario_id, version): _translate_object_recipe(
                _RECIPES[scenario_id],
                get_codex_version_layout_v3(version),
            )
            for scenario_id, versions in OBJECT_COMPOUND_CROSS_VERSION_CASE_VERSIONS.items()
            for version in versions
        }
    )
)


def build_object_heavy_v3_recipe(
    scenario_id: str,
    version: str = VERSION,
) -> ObjectHeavyRecipe:
    """Return one immutable reviewed recipe; arbitrary IDs fail closed."""

    try:
        get_codex_version_layout_v3(version)
    except CodexVersionLayoutError as exc:
        raise ObjectHeavyRecipeError(str(exc)) from exc
    try:
        base = _RECIPES[scenario_id]
    except KeyError as exc:
        raise ObjectHeavyRecipeError(
            f"unknown object-heavy V3 scenario: {scenario_id}"
        ) from exc
    if version == VERSION:
        return base
    try:
        return _CROSS_VERSION_RECIPES[(scenario_id, version)]
    except KeyError as exc:
        raise ObjectHeavyRecipeError(
            f"{scenario_id} is not approved for Wwise {version}"
        ) from exc


def all_object_heavy_v3_recipes() -> tuple[ObjectHeavyRecipe, ...]:
    """Return all fifteen recipes in create/get/set review order."""

    return tuple(_RECIPES[scenario_id] for scenario_id in OBJECT_HEAVY_CASE_IDS)


__all__ = [
    "ACTOR_DWU",
    "ACTOR_ROOT",
    "COMPOUND_VERSIONS",
    "MASTER_DWU",
    "OBJECT_COMPOUND_CROSS_VERSION_CASE_IDS",
    "OBJECT_COMPOUND_CROSS_VERSION_CASE_VERSIONS",
    "OBJECT_CREATE_CASE_IDS",
    "OBJECT_GET_CASE_IDS",
    "OBJECT_HEAVY_CASE_IDS",
    "OBJECT_HEAVY_RECIPE_CONTRACT",
    "OBJECT_SET_CASE_IDS",
    "CleanupPlan",
    "ExpectedField",
    "ExpectedObject",
    "FinalAnswerFilter",
    "FinalFilterRule",
    "FixtureObject",
    "FixtureRecipe",
    "MaterializedObject",
    "MaterializedReference",
    "ObjectHeavyRecipe",
    "ObjectHeavyRecipeError",
    "ObjectProperty",
    "ObjectReference",
    "OperationRequestSpec",
    "OraclePlan",
    "OracleRule",
    "QueryObjectRequestSpec",
    "all_object_heavy_v3_recipes",
    "build_object_heavy_v3_recipe",
]
