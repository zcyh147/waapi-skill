"""Schema-derived typed request facts for the public Gateway.

This module owns the deterministic conversion from short, typed facts into a
WAAPI ``args``/``options`` pair.  Callers never submit a JSON request tree:
they copy opaque field handles from :func:`request_contract` and the Gateway
materializes the tree under the exact reflected versioned schema.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .canonical import canonical_json_bytes, canonical_sha256
from .capabilities import CapabilityCatalog, CapabilityNotFoundError
from .schema_inventory import (
    DefinitionGraph,
    SchemaInventoryError,
    contextual_schema_target,
    load_definition_graph,
    resolve_schema_reference,
)
from .versions import SUPPORTED_WWISE_VERSION_KEYS


TYPED_REQUEST_CONTRACT = "waapi-skill.typed-request/v1"
TYPED_REQUEST_SCHEMA_CONTRACT = "waapi-skill.typed-request-schema/v1"
TYPED_REQUEST_HANDLE_PREFIX = "trh1-"
TYPED_REQUEST_TRACER_URI = "ak.wwise.core.profiler.getVoiceContributions"
TYPED_REQUEST_COMPLEX_TRACER_URI = "ak.wwise.debug.validateCall"
TYPED_DYNAMIC_HANDLE_PREFIX = "trm1-"
TYPED_DYNAMIC_CHOICE_PREFIX = "trc1-"
TYPED_SCHEMA_LINEAGE_PREFIX = "trl2-"
# Full handles avoid a model-side prefix/suffix join on ordinary field tables.
# Larger reflected tables use the lossless shared-prefix encoding so their
# complete final topic-schema envelope remains inside the fixed 32 KiB ceiling.
COPY_READY_FIELD_TABLE_MAX_ROWS = 128
DIRECT_ACTION_FIELD_TABLE_MIN_ROWS = 64
# The largest reviewed closed request is one complete 256-point RTPC curve.
# Each point needs one array-membership fact plus its three scalar fields.  The
# remaining headroom covers the two identities and curve options without
# weakening the independent canonical-document ceiling.
MAX_TYPED_REQUEST_FACTS = 1280
# Six complete fact actions keep the worst reviewed Fresh Agent batch inside
# the native-Windows encoded PowerShell/CreateProcess command boundary while
# still collapsing the long one-fact-at-a-time construction chain.
MAX_TYPED_ACTIONS_PER_APPLY = 6
MAX_TYPED_ARRAY_ITEMS = 256
MAX_TYPED_STRING_BYTES = 64 * 1024
MAX_TYPED_REQUEST_BYTES = 256 * 1024
MAX_TYPED_SCHEMA_NODES = 1024
MAX_TYPED_SCHEMA_DEPTH = 16


def _copy_ready_fact_action(uri: str, action: str) -> str:
    """Render one compact-table action as the exact public Topic flag."""

    prefix = (
        "option"
        if uri.startswith("topic.options:")
        else "match" if uri.startswith("topic.match:") else ""
    )
    if not prefix:
        return action
    return {
        "set": f"--{prefix}-set",
        "choose": f"--{prefix}-choose",
        "append-or-present": (
            f"--{prefix}-append(nonempty)|--{prefix}-present(empty)"
        ),
        "map-put-or-present": (
            f"--{prefix}-map-put(nonempty)|--{prefix}-present(empty)"
        ),
        "disclose-array-item-or-present": (
            f"request-array-item(nonempty)|--{prefix}-present(empty)"
        ),
        "static-child-facts": "child_contract_facts",
    }.get(action, action)


class TypedRequestError(ValueError):
    """A typed request cannot be disclosed or materialized safely."""


@dataclass(frozen=True, slots=True)
class TypedFieldContract:
    """One exact schema location addressed by a Gateway-owned handle."""

    handle: str
    section: str
    name: str
    path: tuple[str, ...]
    required: bool
    shape: str
    variants: tuple[Mapping[str, Any], ...]
    parent_handle: str | None = None
    minimum_items: int | None = None
    maximum_items: int | None = None
    maximum_properties: int | None = None
    maximum_bytes: int | None = None
    maximum_key_bytes: int | None = None
    unique_items: bool = False
    map_patterns: tuple[tuple[str, tuple[Mapping[str, Any], ...]], ...] = ()
    additional_variants: tuple[Mapping[str, Any], ...] = ()
    open_map: bool = False
    handle_path: tuple[str, ...] | None = None
    node_schema: Mapping[str, Any] | None = None
    overlay: bool = False
    required_map_keys: tuple[str, ...] = ()
    fixed_map_keys: tuple[str, ...] = ()
    variant_groups: tuple[tuple[Mapping[str, Any], ...], ...] = ()
    branch_keyword: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "handle": self.handle,
            "section": self.section,
            "name": self.name,
            "path": [self.section, *self.path],
            "required": self.required,
            "shape": self.shape,
            "accepted_types": sorted(
                {
                    str(variant["type"])
                    for variant in self.variants
                    if isinstance(variant.get("type"), str)
                }
            ),
        }
        if self.shape == "scalar":
            payload["fact_construction"] = {
                "phase": "before_dynamic_disclosure",
                "fact_action": "set",
            }
        elif self.shape == "branch":
            payload["fact_construction"] = {
                "phase": "before_dynamic_disclosure",
                "fact_action": "choose",
            }
        elif self.shape == "array":
            payload["fact_construction"] = {
                "nonempty_scalar_items": {
                    "phase": "before_dynamic_disclosure",
                    "fact_action": "append",
                    "repeat_for_each_item": True,
                },
                "empty_array_only": {
                    "phase": "before_dynamic_disclosure",
                    "fact_action": "present",
                    "must_not_accompany": ["append"],
                },
                **(
                    {
                        "complex_item_phase": "dynamic_disclosure",
                        "complex_item_disclosure": "request-array-item",
                        "business_cardinality_authority": {
                            "source": "current_business_request",
                            "schema_does_not_require_another_item": True,
                            "do_not_disclose_absent_index": True,
                        },
                    }
                    if any(
                        variant.get("type") in {"object", "array"}
                        for variant in self.variants
                    )
                    else {}
                ),
            }
        elif self.shape == "map":
            payload["fact_construction"] = {
                "nonempty_scalar_members": {
                    "phase": "before_dynamic_disclosure",
                    "fact_action": "map-put",
                    "repeat_for_each_member": True,
                },
                "empty_map_only": {
                    "phase": "before_dynamic_disclosure",
                    "fact_action": "present",
                    "must_not_accompany": ["map-put"],
                },
                **(
                    {
                        "complex_member_phase": "dynamic_disclosure",
                        "complex_member_disclosure": "request-map-container",
                    }
                    if any(
                        variant.get("type") in {"object", "array"}
                        for variant in self.variants
                    )
                    else {}
                ),
            }
        else:
            payload["fact_construction"] = {
                "phase": "static_child_facts_or_dynamic_container_handle",
                "empty_fact_action": "present",
            }
        enum_values = [
            value
            for variant in self.variants
            for value in variant.get("enum", ())
            if isinstance(variant.get("enum"), list)
        ]
        if enum_values:
            payload["enum"] = enum_values
        constant_values = [
            variant["const"]
            for variant in self.variants
            if "const" in variant
        ]
        if constant_values:
            payload["constant_values"] = constant_values
            payload["fact_construction"]["constant_fact_required"] = True
        patterns = sorted(
            {
                str(variant["pattern"])
                for variant in self.variants
                if isinstance(variant.get("pattern"), str)
            }
        )
        if patterns:
            payload["patterns"] = patterns
        if self.shape == "array":
            payload["minimum_items"] = self.minimum_items
            payload["maximum_items"] = self.maximum_items
            payload["unique_items"] = self.unique_items
        if self.parent_handle is not None:
            payload["parent_handle"] = self.parent_handle
        if self.shape == "map":
            payload["map"] = {
                "open": self.open_map,
                "key_patterns": [pattern for pattern, _variants in self.map_patterns],
                "schema_authorized_additional_keys": bool(self.additional_variants),
                "one_key_per_fact": True,
            }
            payload["maximum_properties"] = self.maximum_properties
            payload["maximum_bytes"] = self.maximum_bytes
            payload["maximum_key_bytes"] = self.maximum_key_bytes
        return payload


@dataclass(frozen=True, slots=True)
class TypedRequestContract:
    """One immutable exact-version request construction contract."""

    version: str
    uri: str
    schema_digest: str
    fields: tuple[TypedFieldContract, ...]
    schema_roots: Mapping[str, Mapping[str, Any]]
    definition_graph: DefinitionGraph
    effect: str = "read"
    route: str = "bounded_call"
    gateway_commands: tuple[str, ...] = ()
    timeout_seconds: float = 10.0

    @property
    def fields_by_handle(self) -> Mapping[str, TypedFieldContract]:
        return {field.handle: field for field in self.fields}

    def gateway_field_payloads(self) -> list[dict[str, Any]]:
        """Project fields once for every public Gateway discovery surface."""

        field_payloads = [field.as_dict() for field in self.fields]
        fields_by_parent: dict[str, list[TypedFieldContract]] = {}
        for field in self.fields:
            if field.parent_handle is not None:
                fields_by_parent.setdefault(field.parent_handle, []).append(field)
        for field, field_payload in zip(self.fields, field_payloads, strict=True):
            if field.shape != "object" or field.parent_handle is None:
                continue
            parent = self.fields_by_handle.get(field.parent_handle)
            if parent is None or parent.shape != "branch":
                continue
            constants = {
                child.name: child.variants[0]["const"]
                for child in fields_by_parent.get(field.handle, ())
                if len(child.variants) == 1 and "const" in child.variants[0]
            }
            if constants:
                field_payload["branch_choice_constants"] = constants
            field_payload["fact_construction"] = {
                "phase": "before_dynamic_disclosure",
                "role": "branch_choice_handle",
                "parent_fact_action": "choose",
            }
        return field_payloads

    def gateway_construction_order(self) -> dict[str, str]:
        """Describe the one request-wide fact/disclosure linearization."""

        return {
            "top_level_facts": "follow top_level_fact_plan before disclosures",
            "constant_facts": "set selected constants",
            "branch_constants": "set selected branch constants before disclosure",
            "independent_facts": (
                "submit each business-present top-level fact once; omit absent defaults"
            ),
            "scalar_map_values": (
                "map-put scalars; container commands only for object or array"
            ),
            "complex_values": "disclose nested values in schema order",
            "dependent_facts": (
                "after disclosures drain the outermost response tree preorder"
            ),
        }

    def top_level_fact_plan(self) -> dict[str, Any]:
        """Return the compact plan that precedes all dynamic disclosures."""

        field_payloads = self.gateway_field_payloads()
        child_fields_by_parent: dict[str, list[dict[str, Any]]] = {}
        for child_field in field_payloads:
            parent_handle = child_field.get("parent_handle")
            if isinstance(parent_handle, str):
                child_fields_by_parent.setdefault(parent_handle, []).append(
                    child_field
                )
        rows: list[list[Any]] = []
        for field in field_payloads:
            path = field.get("path")
            if (
                field.get("parent_handle") is not None
                or not isinstance(path, list)
                or len(path) != 2
            ):
                continue
            accepted_types = field.get("accepted_types")
            dynamic = field.get("shape") == "array" and isinstance(
                accepted_types, list
            ) and any(
                value in {"object", "array"} for value in accepted_types
            )
            shape = field.get("shape")
            fact_handle = field.get("handle")
            child_fields = child_fields_by_parent.get(fact_handle, [])
            if (
                shape == "object"
                and len(child_fields) == 1
                and child_fields[0].get("shape") == "map"
            ):
                shape = "map"
                fact_handle = child_fields[0].get("handle")
            action = (
                "set"
                if shape == "scalar"
                else "choose"
                if shape == "branch"
                else "array"
                if shape == "array"
                else "map"
                if shape == "map"
                else "child"
            )
            rows.append(
                [
                    fact_handle,
                    field.get("name"),
                    "disclosure" if dynamic else "fact",
                    action,
                ]
            )
        rows.sort(key=lambda row: row[2] == "disclosure")
        return {
            "business_fact_selection": (
                "submit only prompt-present values; omit absent defaults"
            ),
            "business_pointer_source": "typed_request_fields.path",
            "fact_batching": (
                "submit schema-ordered facts in full batches of 6; the final "
                "fact batch contains every remaining fact"
            ),
            "branch_fact_expansion": (
                "after choose, immediately set every required selected-branch "
                "constant and business value before the next top-level fact"
            ),
            "columns": ["handle", "name", "phase", "action"],
            "rows": rows,
        }

    def gateway_field_table(self) -> dict[str, Any]:
        """Return a compact, lossless table for large discovery documents."""

        fields = self.gateway_field_payloads()
        sections = {field.section for field in self.fields}
        if not sections:
            section = "options" if self.uri.startswith("topic.options:") else "args"
        elif len(sections) == 1:
            section = next(iter(sections))
        else:
            raise TypedRequestError("Typed field table requires one request section")
        copy_ready = len(fields) <= COPY_READY_FIELD_TABLE_MAX_ROWS
        direct_actions = (
            DIRECT_ACTION_FIELD_TABLE_MIN_ROWS
            <= len(fields)
            <= COPY_READY_FIELD_TABLE_MAX_ROWS
        )
        handle_prefix = (
            "trh1-"
            if not copy_ready
            and all(str(field["handle"]).startswith("trh1-") for field in fields)
            else ""
        )
        row_by_handle = {
            str(field["handle"]): index for index, field in enumerate(fields)
        }
        shape_codes: list[str] = []
        accepted_type_sets: list[list[str]] = []
        fact_action_codes: list[str] = []
        fact_action_definitions: list[dict[str, Any]] = []
        constraint_sets: list[dict[str, Any]] = []
        constraint_indexes: dict[str, int] = {}
        rows: list[list[Any]] = []
        for field in fields:
            shape = str(field["shape"])
            if shape not in shape_codes:
                shape_codes.append(shape)
            accepted_types = list(field["accepted_types"])
            if accepted_types not in accepted_type_sets:
                accepted_type_sets.append(accepted_types)
            constraints = {
                key: value
                for key, value in field.items()
                if key
                not in {
                    "handle",
                    "parent_handle",
                    "name",
                    "shape",
                    "accepted_types",
                    "section",
                    "path",
                }
                and not (key == "required" and value is False)
                and not (
                    key
                    in {
                        "minimum_items",
                        "maximum_items",
                        "maximum_properties",
                        "maximum_bytes",
                        "maximum_key_bytes",
                    }
                    and value is None
                )
                and not (key == "unique_items" and value is False)
            }
            fact_construction = constraints.pop("fact_construction", {})
            map_payload = constraints.get("map")
            if isinstance(map_payload, Mapping):
                compact_map = dict(map_payload)
                if compact_map.get("key_patterns") == []:
                    compact_map.pop("key_patterns")
                if compact_map.get("schema_authorized_additional_keys") is False:
                    compact_map.pop("schema_authorized_additional_keys")
                if compact_map.get("one_key_per_fact") is True:
                    compact_map.pop("one_key_per_fact")
                constraints["map"] = compact_map
            constraint_key = canonical_json_bytes(constraints).decode("utf-8")
            constraint_index = constraint_indexes.get(constraint_key)
            if constraint_index is None:
                constraint_index = len(constraint_sets)
                constraint_indexes[constraint_key] = constraint_index
                constraint_sets.append(constraints)
            parent_handle = field.get("parent_handle")
            fact_action_code = "static-child-facts"
            if isinstance(fact_construction, Mapping):
                if isinstance(
                    fact_construction.get("complex_item_disclosure"), str
                ):
                    fact_action_code = "disclose-array-item-or-present"
                elif isinstance(fact_construction.get("fact_action"), str):
                    fact_action_code = str(fact_construction["fact_action"])
                elif isinstance(
                    fact_construction.get("nonempty_scalar_items"), Mapping
                ):
                    fact_action_code = "append-or-present"
                elif isinstance(
                    fact_construction.get("nonempty_scalar_members"), Mapping
                ):
                    fact_action_code = "map-put-or-present"
                elif fact_construction.get("role") == "branch_choice_handle":
                    fact_action_code = "choose"
            public_fact_action = (
                _copy_ready_fact_action(self.uri, fact_action_code)
                if direct_actions
                else fact_action_code
            )
            if public_fact_action in fact_action_codes:
                fact_action_index = fact_action_codes.index(public_fact_action)
                if fact_action_definitions[fact_action_index] != fact_construction:
                    raise TypedRequestError(
                        "Compact field action code has inconsistent semantics"
                    )
            else:
                fact_action_index = len(fact_action_codes)
                fact_action_codes.append(public_fact_action)
                fact_action_definitions.append(dict(fact_construction))
            rows.append(
                [
                    str(field["handle"]).removeprefix(handle_prefix),
                    row_by_handle.get(str(parent_handle)) if parent_handle else None,
                    field["name"],
                    shape_codes.index(shape),
                    accepted_type_sets.index(accepted_types),
                    public_fact_action if direct_actions else fact_action_index,
                    constraint_index,
                ]
            )
        name_counts: dict[str, int] = {}
        for field in fields:
            name = str(field["name"])
            name_counts[name] = name_counts.get(name, 0) + 1
        duplicate_name_paths = [
            [index, ".".join(str(part) for part in field["path"][1:])]
            for index, field in enumerate(fields)
            if str(field["name"]) == "name"
            and name_counts.get("name", 0) > 1
            and isinstance(field.get("path"), list)
            and len(field["path"]) > 1
        ]
        return {
            "contract": "waapi-skill.compact-typed-field-table/v1",
            "section": section,
            **({"handle_prefix": handle_prefix} if handle_prefix else {}),
            "columns": [
                "handle_suffix" if handle_prefix else "handle",
                "parent_row",
                "name",
                "shape_code",
                "accepted_type_set",
                "fact_action" if direct_actions else "fact_action_code",
                "constraint_set",
            ],
            "shape_codes": shape_codes,
            "accepted_type_sets": accepted_type_sets,
            "fact_action_codes": fact_action_codes,
            "fact_action_definitions": fact_action_definitions,
            "constraint_sets": constraint_sets,
            "constraint_defaults": {
                "required": False,
                "null_limits": True,
                "array_unique_items": False,
                "map": {
                    "key_patterns": [],
                    "schema_authorized_additional_keys": False,
                    "one_key_per_fact": True,
                },
            },
            "path": "omitted; construct with handles and parent_row lineage",
            "duplicate_name_paths": duplicate_name_paths,
            "rows": rows,
        }

    def as_gateway_payload(self) -> dict[str, Any]:
        if not self.fields:
            gateway_argv = [
                "typed-zero-call",
                self.uri,
                "--schema-digest",
                self.schema_digest,
            ]
            if self.effect != "read":
                gateway_argv.append("--apply")
            continuation: dict[str, Any] = {
                "subcommand": "typed-zero-call",
                "uri": self.uri,
                "schema_digest": self.schema_digest,
                "gateway_argv": gateway_argv,
                "business_values_required": False,
                **({"apply": True} if self.effect != "read" else {}),
            }
            if self.route == "fixed_command" and self.uri != "ak.wwise.core.getInfo":
                command = self.gateway_commands[0].split()
                continuation = {
                    "subcommand": command[0],
                    "arguments": command[1:],
                    "business_values_required": False,
                }
        else:
            flat_inline = _contract_is_flat_inline(self)
            if flat_inline:
                shapes = {field.shape for field in self.fields}
                fact_flags: dict[str, str] = {}
                if "scalar" in shapes:
                    fact_flags["scalar"] = "--set <field_handle> <type> <value>"
                if "array" in shapes:
                    fact_flags["array_item"] = (
                        "--append <field_handle> <type> <value>"
                    )
                    fact_flags["container"] = "--present <array_handle>"
                if "branch" in shapes:
                    fact_flags["branch"] = (
                        "--choose <branch_handle> <choice_handle>"
                    )
            else:
                fact_flags = {
                    "scalar": "--set <field_handle> <type> <value>",
                    "array_item": "--append <field_handle> <type> <value>",
                    "container": "--present <object_or_array_handle>",
                    "branch": "--choose <branch_handle> <choice_handle>",
                    "dynamic_branch": (
                        "--choose-dynamic <object_handle> <key> <choice_handle>"
                    ),
                    "map_put": "--map-put <map_handle> <key> <type> <value>",
                    "map_correct": "--map-correct <map_handle> <key> <type> <value>",
                    "map_remove": "--map-remove <map_handle> <key>",
                }
            if (
                flat_inline
                or self.uri == TYPED_REQUEST_COMPLEX_TRACER_URI
                or self.route == "isolated_transaction"
            ):
                gateway_argv_prefix = [
                    "typed-call",
                    self.uri,
                    "--schema-digest",
                    self.schema_digest,
                ]
                if self.effect != "read":
                    gateway_argv_prefix.append("--apply")
                if self.route == "isolated_transaction":
                    gateway_argv_prefix.extend(
                        ("--io-root", "<absolute-allowed-root>")
                    )
                continuation = {
                    "subcommand": "typed-call",
                    "uri": self.uri,
                    "schema_digest": self.schema_digest,
                    "gateway_argv_prefix": gateway_argv_prefix,
                    "fact_flags": fact_flags,
                    **({"apply": True} if self.effect != "read" else {}),
                }
                if not flat_inline:
                    continuation["dynamic_container_commands"] = {
                        "map_value": "request-map-container",
                        "array_item": "request-array-item",
                        "map_value_argv": [
                            "request-map-container",
                            self.uri,
                            "--schema-digest",
                            self.schema_digest,
                            "--map-handle",
                            "<parent_handle>",
                            "--key",
                            "<key>",
                            "--shape",
                            "<object|array>",
                        ],
                        "array_item_argv": [
                            "request-array-item",
                            self.uri,
                            "--schema-digest",
                            self.schema_digest,
                            "--array-handle",
                            "<parent_handle>",
                            "--index",
                            "<zero_based_index>",
                            "--shape",
                            "<object|array>",
                        ],
                        "draft_binding": False,
                        "nested_parent_argv": [
                            "--parent-schema-token",
                            "<schema_lineage_token_from_parent_disclosure>",
                        ],
                        "scalar_map_entry_action": (
                            "append one --map-put <map_handle> <key> <type> <value> "
                            "fact directly; request-map-container is only for an "
                            "object or array value"
                        ),
                        "sequence": (
                            "use the root template only for a top-level handle; "
                            "for a returned child handle append nested_parent_argv "
                            "with that same response's schema_lineage_token"
                        ),
                    }
                input_shape = "inline"
            else:
                continuation = {
                    "subcommand": "draft-start",
                    "operation": self.uri,
                    "gateway_argv_prefix": ["draft-start", self.uri],
                    "start_command": {
                        "argv": ["draft-start", self.uri],
                        "execute_alone": True,
                        "typed_facts_on_draft_start": "invalid",
                    },
                    "after_start": {
                        "fact_command_prefix_pointer": (
                            "/draft/next_action_binding/fixed_argv_prefix"
                        ),
                        "append_one_or_more_complete_actions": True,
                        "minimum_actions": 1,
                        "maximum_actions": MAX_TYPED_ACTIONS_PER_APPLY,
                        "ordered_atomic_batch": True,
                        "then_read_next_response": True,
                    },
                    "fact_value_argv_policy": {
                        "one_business_value_is_one_argv_token": True,
                        "whitespace_or_shell_metacharacters": (
                            "shell-quote the complete value; splitting it is invalid"
                        ),
                        "preserve_value_text_exactly": True,
                    },
                    "schema_digest_usage": (
                        "the digest binds request-map-container/request-array-item; "
                        "do not pass it to draft-start"
                    ),
                    "business_values_required": True,
                    "action_argv": {
                        "add_typed_fact": (
                            "--action add_typed_fact --fact-action "
                            "(set|append) --field-handle HANDLE --value-type TYPE "
                            "--fact-value VALUE | --fact-action present "
                            "--field-handle HANDLE | --fact-action choose "
                            "--field-handle HANDLE --fact-value CHOICE_HANDLE | "
                            "--fact-action choose-dynamic --field-handle HANDLE "
                            "--key KEY --fact-value CHOICE_HANDLE | --fact-action "
                            "map-put --field-handle HANDLE --key KEY "
                            "--value-type TYPE --fact-value VALUE"
                        ),
                        "correct_typed_fact": (
                            "--action correct_typed_fact --fact-handle FACT_HANDLE "
                            "then one complete add_typed_fact shape"
                        ),
                        "remove_typed_fact": (
                            "--action remove_typed_fact --fact-handle FACT_HANDLE"
                        ),
                    },
                    "dynamic_container_commands": {
                        "map_value": "request-map-container",
                        "array_item": "request-array-item",
                        "map_value_argv": [
                            "request-map-container",
                            self.uri,
                            "--schema-digest",
                            self.schema_digest,
                            "--map-handle",
                            "<parent_handle>",
                            "--key",
                            "<key>",
                            "--shape",
                            "<object|array>",
                        ],
                        "array_item_argv": [
                            "request-array-item",
                            self.uri,
                            "--schema-digest",
                            self.schema_digest,
                            "--array-handle",
                            "<parent_handle>",
                            "--index",
                            "<zero_based_index>",
                            "--shape",
                            "<object|array>",
                        ],
                        "draft_binding": False,
                        "nested_parent_argv": [
                            "--parent-schema-token",
                            "<schema_lineage_token_from_parent_disclosure>",
                        ],
                        "scalar_map_entry_action": (
                            "use draft-apply add_typed_fact with fact-action map-put "
                            "directly; request-map-container is only for an object "
                            "or array value"
                        ),
                        "sequence": (
                            "disclose a complex item without --member-key first; "
                            "follow a returned choice continuation exactly; for a "
                            "returned child handle append nested_parent_argv with "
                            "that same response's schema_lineage_token"
                        ),
                    },
                    "completion": (
                        "draft-check executes this read directly"
                        if self.effect == "read"
                        else "draft-check then preview-from-draft"
                    ),
                }
                input_shape = "draft"
        if not self.fields:
            input_shape = "zero"
        field_payloads = self.gateway_field_payloads()
        payload = {
            "contract": TYPED_REQUEST_SCHEMA_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "request-schema",
            "version": self.version,
            "uri": self.uri,
            "input_shape": input_shape,
            "schema_digest": self.schema_digest,
            **(
                {
                    "construction_order": self.gateway_construction_order(),
                    "top_level_fact_plan": self.top_level_fact_plan(),
                }
                if input_shape == "draft"
                else {}
            ),
            "fields": field_payloads,
            "continuation": continuation,
        }
        if self.uri == "ak.wwise.core.mediaPool.get":
            payload["result_filter"] = {
                "contract": "waapi-skill.media-pool-post-filter/v1",
                "availability": "optional_after_complete_typed_candidate_request",
                "completion_subcommand": "draft-check",
                "typed_scalars": {
                    "value": "--post-filter-value <exact case-sensitive text>",
                    "limit": "--post-filter-limit <1..1000>",
                },
                "requirements": [
                    "typed request filters includes Filename contains with the same value",
                    "typed request options return includes Filename",
                    "typed request maxResults is greater than or equal to the filter limit",
                ],
            }
        return payload


@dataclass(frozen=True, slots=True)
class TypedRequestFact:
    action: str
    handle: str
    value_type: str
    value: str
    key: str | None = None


@dataclass(frozen=True, slots=True)
class TypedRequestDisclosure:
    """One public dynamic-container capability needed by a typed fact stream."""

    command: str
    parent_handle: str
    key: str
    shape: str
    child_handle: str
    choice_handle: str | None = None
    choice_index: int | None = None
    parent_child_handle: str | None = None
    parent_choice_group_index: int | None = None


@dataclass(frozen=True, slots=True)
class TypedRequestConstruction:
    facts: tuple[TypedRequestFact, ...]
    disclosures: tuple[TypedRequestDisclosure, ...]


@dataclass(frozen=True, slots=True)
class MaterializedTypedRequest:
    version: str
    uri: str
    schema_digest: str
    args: Mapping[str, Any]
    options: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": TYPED_REQUEST_CONTRACT,
            "version": self.version,
            "uri": self.uri,
            "schema_digest": self.schema_digest,
            "args": dict(self.args),
            "options": dict(self.options),
        }


def request_contract(version: str, uri: str) -> TypedRequestContract:
    """Compile one authorized reflected function into its typed contract."""

    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise TypedRequestError(f"Unsupported Wwise version {version!r}")
    catalog = CapabilityCatalog()
    try:
        capability = catalog.describe(version, uri)
    except CapabilityNotFoundError as exc:
        try:
            capability = catalog.authoring_ui_describe(version, uri)
        except CapabilityNotFoundError:
            raise TypedRequestError(str(exc)) from exc
    if capability.item_type != "function":
        raise TypedRequestError(f"Typed request construction requires a function URI: {uri}")
    graph = load_definition_graph(version)
    compiled = compile_typed_request_contract(
        version=version,
        uri=uri,
        schema=capability.schema,
        graph=graph,
    )
    if capability.execution_contract["route"] == "compound_transaction_member":
        raise TypedRequestError(
            f"WAAPI URI {uri!r} requires the typed compound-operation adapter"
        )
    generic = _generic_typed_contract_is_public(capability)
    if compiled.fields and uri not in {
        TYPED_REQUEST_TRACER_URI,
        TYPED_REQUEST_COMPLEX_TRACER_URI,
    } and not generic:
        raise TypedRequestError(
            f"WAAPI URI {uri!r} has not migrated to an executable typed adapter"
        )
    return TypedRequestContract(
        version=compiled.version,
        uri=compiled.uri,
        schema_digest=compiled.schema_digest,
        fields=compiled.fields,
        schema_roots=compiled.schema_roots,
        definition_graph=compiled.definition_graph,
        effect=str(capability.execution_contract["effect"]),
        route=str(capability.execution_contract["route"]),
        gateway_commands=tuple(
            str(item) for item in capability.execution_contract["gateway_commands"]
        ),
        timeout_seconds=float(capability.execution_contract["timeout_seconds"]),
    )


def _generic_typed_contract_is_public(capability: Any) -> bool:
    return (
        capability.execution_contract["route"] != "compound_transaction_member"
        and not capability.transaction_boundaries
        and (
            capability.preferred_route == "manifest_dispatch"
            or tuple(capability.transaction_operations) == ("waapi.call",)
        )
    )


def _contract_is_flat_inline(contract: TypedRequestContract) -> bool:
    """Accept only top-level scalars, scalar arrays, and their explicit branches."""

    if not contract.fields:
        return False
    by_handle = contract.fields_by_handle
    for field in contract.fields:
        if field.shape in {"object", "map"}:
            return False
        if field.parent_handle is None:
            if field.shape not in {"scalar", "array", "branch"}:
                return False
        else:
            parent = by_handle.get(field.parent_handle)
            if parent is None or parent.shape != "branch":
                return False
            if field.shape not in {"scalar", "array"}:
                return False
        if field.shape == "array" and any(
            variant.get("type") not in {
                "string", "integer", "number", "boolean", "null"
            }
            for variant in field.variants
        ):
            return False
    return True


def compile_typed_request_contract(
    *,
    version: str,
    uri: str,
    schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> TypedRequestContract:
    """Compile one already-authorized function schema into opaque field handles."""

    if graph.version != version:
        raise TypedRequestError("Typed request definition graph version does not match")
    schema_digest = canonical_sha256(
        {
            "contract": TYPED_REQUEST_SCHEMA_CONTRACT,
            "version": version,
            "uri": uri,
            "schema": schema,
            "definition_graph_sha256": graph.inventory_sha256,
            "limits": {
                "facts": MAX_TYPED_REQUEST_FACTS,
                "array_items": MAX_TYPED_ARRAY_ITEMS,
                "string_bytes": MAX_TYPED_STRING_BYTES,
                "request_bytes": MAX_TYPED_REQUEST_BYTES,
                "schema_nodes": MAX_TYPED_SCHEMA_NODES,
                "schema_depth": MAX_TYPED_SCHEMA_DEPTH,
            },
        }
    )
    fields: list[TypedFieldContract] = []
    node_count = [0]
    schema_roots: dict[str, Mapping[str, Any]] = {}
    for section_name in ("args", "options"):
        schema_name = f"{section_name}Schema"
        root = schema.get(schema_name)
        if not isinstance(root, Mapping):
            raise TypedRequestError(f"{uri} {schema_name} must be an object")
        expanded_root = _expanded_schema(root, root_schema=root, graph=graph)
        schema_roots[section_name] = root
        node_count[0] += _count_reachable_schema_nodes(
            expanded_root,
            root_schema=root,
            graph=graph,
            active_references=frozenset(),
        )
        if node_count[0] > MAX_TYPED_SCHEMA_NODES:
            raise TypedRequestError(
                "Typed request schema exceeds its packaged structure limits"
            )
        _collect_object_fields(
            expanded_root,
            section=section_name,
            path=(),
            root_schema=root,
            graph=graph,
            schema_digest=schema_digest,
            fields=fields,
            node_count=[0],
            depth=0,
            parent_handle=None,
        )
    return TypedRequestContract(
        version=version,
        uri=uri,
        schema_digest=schema_digest,
        fields=tuple(fields),
        schema_roots=schema_roots,
        definition_graph=graph,
        effect="read",
        route="bounded_call",
        gateway_commands=(),
        timeout_seconds=10.0,
    )


def dynamic_map_entry_handle(
    contract: TypedRequestContract,
    *,
    map_handle: str,
    key: str,
    shape: str,
    choice_handle: str | None = None,
    parent_schema: Mapping[str, Any] | None = None,
    parent_section: str | None = None,
) -> str:
    """Issue one deterministic handle for a caller-named open-map container."""

    field = contract.fields_by_handle.get(map_handle)
    dynamic_parent = map_handle.startswith(TYPED_DYNAMIC_HANDLE_PREFIX)
    if field is None and dynamic_parent and parent_schema is not None:
        section = parent_section or "args"
        field = _dynamic_container_contract(
            handle=map_handle,
            name="dynamic-parent",
            shape=str(parent_schema.get("type")),
            schema=parent_schema,
            root_schema=contract.schema_roots[section],
            graph=contract.definition_graph,
            section=section,
        )
    if not dynamic_parent and (
        field is None or field.shape != "map"
    ):
        raise TypedRequestError("Dynamic map entries require an open-map handle")
    if shape not in {"object", "array"}:
        raise TypedRequestError("Dynamic map container shape must be object or array")
    if dynamic_parent:
        _require_bounded_map_key(key)
    else:
        assert field is not None
        _map_key_variants(field, key)
    variant_index: int | None = None
    if field is not None:
        matching = [
            (index, variant)
            for index, variant in enumerate(_map_key_variants(field, key))
            if variant.get("type") == shape
        ]
        if len(matching) > 1:
            choices = _dynamic_map_container_choices(
                contract, field=field, key=key, shape=shape
            )
            selected = [
                index for handle, index, _variant in choices if handle == choice_handle
            ]
            if len(selected) != 1:
                raise TypedRequestError(
                    "Typed map container branch requires a disclosed choice handle"
                )
            variant_index = selected[0]
        elif len(matching) == 1 and choice_handle is not None:
            raise TypedRequestError("Typed map container choice is unknown or stale")
    return TYPED_DYNAMIC_HANDLE_PREFIX + canonical_sha256(
        {
            "schema_digest": contract.schema_digest,
            "parent_handle": map_handle,
            "key": key,
            "shape": shape,
            **({"variant_index": variant_index} if variant_index is not None else {}),
        }
    )[:24]


def _dynamic_map_container_choices(
    contract: TypedRequestContract,
    *,
    field: TypedFieldContract,
    key: str,
    shape: str,
) -> tuple[tuple[str, int, Mapping[str, Any]], ...]:
    matching = [
        (index, variant)
        for index, variant in enumerate(_map_key_variants(field, key))
        if variant.get("type") == shape
    ]
    return tuple(
        (
            TYPED_DYNAMIC_CHOICE_PREFIX + canonical_sha256(
                {
                    "schema_digest": contract.schema_digest,
                    "object_handle": field.handle,
                    "key": key,
                    "index": index,
                }
            )[:24],
            index,
            variant,
        )
        for index, variant in matching
    )


def dynamic_map_container_choices(
    contract: TypedRequestContract,
    *,
    map_handle: str,
    key: str,
    shape: str,
    parent_schema: Mapping[str, Any] | None = None,
    parent_section: str | None = None,
) -> tuple[tuple[str, int, Mapping[str, Any]], ...]:
    """Disclose opaque choices for an ambiguous object/array map member."""

    field = contract.fields_by_handle.get(map_handle)
    if field is None and parent_schema is not None:
        section = parent_section or "args"
        field = _dynamic_container_contract(
            handle=map_handle,
            name="dynamic-parent",
            shape=str(parent_schema.get("type")),
            schema=parent_schema,
            root_schema=contract.schema_roots[section],
            graph=contract.definition_graph,
            section=section,
        )
    if field is None or field.shape != "map":
        return ()
    return _dynamic_map_container_choices(
        contract, field=field, key=key, shape=shape
    )


def _map_container_variant_for_handle(
    contract: TypedRequestContract,
    *,
    field: TypedFieldContract,
    key: str,
    shape: str,
    handle: str,
) -> Mapping[str, Any]:
    for _choice, index, variant in _dynamic_map_container_choices(
        contract, field=field, key=key, shape=shape
    ):
        expected = TYPED_DYNAMIC_HANDLE_PREFIX + canonical_sha256(
            {
                "schema_digest": contract.schema_digest,
                "parent_handle": field.handle,
                "key": key,
                "shape": shape,
                "variant_index": index,
            }
        )[:24]
        if handle == expected:
            return variant
    raise TypedRequestError("Typed map container handle is unknown or stale")


def dynamic_array_item_handle(
    contract: TypedRequestContract,
    *,
    array_handle: str,
    index: int,
    shape: str,
    choice_handle: str | None = None,
    parent_schema: Mapping[str, Any] | None = None,
    parent_section: str | None = None,
) -> str:
    """Issue one deterministic handle for one ordered complex array item."""

    field = contract.fields_by_handle.get(array_handle)
    if field is None and parent_schema is not None:
        section = parent_section or "args"
        field = _dynamic_container_contract(
            handle=array_handle,
            name="dynamic-parent",
            shape=str(parent_schema.get("type")),
            schema=parent_schema,
            root_schema=contract.schema_roots[section],
            graph=contract.definition_graph,
            section=section,
        )
    if field is None and not array_handle.startswith(TYPED_DYNAMIC_HANDLE_PREFIX):
        raise TypedRequestError("Dynamic array items require an array handle")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise TypedRequestError("Dynamic array item index must be non-negative")
    if shape not in {"object", "array"} or (
        field is not None and field.shape != "array"
    ):
        raise TypedRequestError("Dynamic array item shape violates its schema")
    selected_index: int | None = None
    if field is not None:
        choices = _dynamic_array_item_choices_for_field(
            contract, field=field, index=index, shape=shape
        )
        if len(choices) > 1:
            matching = [
                variant_index
                for handle, variant_index, _variant in choices
                if handle == choice_handle
            ]
            if len(matching) != 1:
                raise TypedRequestError(
                    "Typed array item branch requires a disclosed choice handle"
                )
            selected_index = matching[0]
        elif len(choices) == 1:
            if choice_handle not in {None, choices[0][0]}:
                raise TypedRequestError("Typed array item choice is unknown or stale")
            selected_index = None
        else:
            raise TypedRequestError("Dynamic array item shape violates its schema")
    return TYPED_DYNAMIC_HANDLE_PREFIX + canonical_sha256(
        {
            "schema_digest": contract.schema_digest,
            "parent_handle": array_handle,
            "key": str(index),
            "shape": shape,
            **(
                {"variant_index": selected_index}
                if selected_index is not None
                else {}
            ),
        }
    )[:24]


def _array_item_variant_for_handle(
    contract: TypedRequestContract,
    *,
    field: TypedFieldContract,
    index: int,
    shape: str,
    handle: str,
) -> Mapping[str, Any]:
    choices = _dynamic_array_item_choices_for_field(
        contract,
        field=field,
        index=index,
        shape=shape,
    )
    for choice_handle, variant_index, variant in choices:
        expected = TYPED_DYNAMIC_HANDLE_PREFIX + canonical_sha256(
            {
                "schema_digest": contract.schema_digest,
                "parent_handle": field.handle,
                "key": str(index),
                "shape": shape,
                "variant_index": variant_index,
            }
        )[:24]
        if handle == expected:
            return variant
    raise TypedRequestError("Typed array item handle is unknown or stale")


def dynamic_array_item_choices(
    contract: TypedRequestContract,
    *,
    array_handle: str,
    index: int,
    shape: str,
    parent_schema: Mapping[str, Any] | None = None,
    parent_section: str | None = None,
) -> tuple[tuple[str, int, Mapping[str, Any]], ...]:
    """Disclose opaque choices for an ambiguous complex array element."""

    field = contract.fields_by_handle.get(array_handle)
    if field is None and parent_schema is not None:
        section = parent_section or "args"
        field = _dynamic_container_contract(
            handle=array_handle,
            name="dynamic-parent",
            shape=str(parent_schema.get("type")),
            schema=parent_schema,
            root_schema=contract.schema_roots[section],
            graph=contract.definition_graph,
            section=section,
        )
    if field is None or field.shape != "array":
        raise TypedRequestError("Dynamic array item choices require an array handle")
    return _dynamic_array_item_choices_for_field(
        contract,
        field=field,
        index=index,
        shape=shape,
    )


def _dynamic_array_item_choices_for_field(
    contract: TypedRequestContract,
    *,
    field: TypedFieldContract,
    index: int,
    shape: str,
) -> tuple[tuple[str, int, Mapping[str, Any]], ...]:
    matching = [
        (variant_index, variant)
        for variant_index, variant in enumerate(field.variants)
        if variant.get("type") == shape
    ]
    return tuple(
        (
            TYPED_DYNAMIC_CHOICE_PREFIX + canonical_sha256(
                {
                    "schema_digest": contract.schema_digest,
                    "array_handle": field.handle,
                    "index": index,
                    "shape": shape,
                    "variant_index": variant_index,
                }
            )[:24],
            variant_index,
            variant,
        )
        for variant_index, variant in matching
    )


def dynamic_branch_choices(
    contract: TypedRequestContract,
    *,
    object_handle: str,
    key: str,
    value_schema: Mapping[str, Any],
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    """Disclose opaque choices for one already schema-bound dynamic member."""

    variants = _structural_variants(
        value_schema,
        root_schema=contract.schema_roots["args"],
        graph=contract.definition_graph,
    )
    if len(variants) < 2:
        raise TypedRequestError("Dynamic member does not require a branch choice")
    return tuple(
        (
            TYPED_DYNAMIC_CHOICE_PREFIX + canonical_sha256(
                {
                    "schema_digest": contract.schema_digest,
                    "object_handle": object_handle,
                    "key": key,
                    "index": index,
                }
            )[:24],
            variant,
        )
        for index, variant in enumerate(variants)
    )


def _variant_constant_fields(variant: Mapping[str, Any]) -> dict[str, Any]:
    properties = variant.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    return {
        str(name): value_schema["const"]
        for name, value_schema in properties.items()
        if isinstance(value_schema, Mapping) and "const" in value_schema
    }


def _fixed_container_members(
    schema: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> list[dict[str, Any]]:
    """Project direct schema-owned object/array members in property order."""

    expanded = _expanded_schema(schema, root_schema=root_schema, graph=graph)
    properties = expanded.get("properties")
    if not isinstance(properties, Mapping):
        return []
    required = expanded.get("required", ())
    required_names = set(required) if isinstance(required, list) else set()
    members: list[dict[str, Any]] = []
    for name, member_schema in properties.items():
        if not isinstance(name, str) or not isinstance(member_schema, Mapping):
            continue
        variants = _structural_variants(
            member_schema,
            root_schema=root_schema,
            graph=graph,
        )
        shapes = {
            str(variant.get("type"))
            for variant in variants
            if variant.get("type") in {"object", "array"}
        }
        if len(shapes) == 1:
            members.append(
                {
                    "key": name,
                    "shape": next(iter(shapes)),
                    "required": name in required_names,
                }
            )
    return members


def _fixed_scalar_members(
    schema: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> list[dict[str, Any]]:
    """Project direct single-branch scalar members in property order."""

    expanded = _expanded_schema(schema, root_schema=root_schema, graph=graph)
    properties = expanded.get("properties")
    if not isinstance(properties, Mapping):
        return []
    required = expanded.get("required", ())
    required_names = set(required) if isinstance(required, list) else set()
    members: list[dict[str, Any]] = []
    for name, member_schema in properties.items():
        if not isinstance(name, str) or not isinstance(member_schema, Mapping):
            continue
        expanded_member = _expanded_schema(
            member_schema,
            root_schema=root_schema,
            graph=graph,
        )
        if "const" in expanded_member:
            continue
        variants = _structural_variants(
            member_schema,
            root_schema=root_schema,
            graph=graph,
        )
        if len(variants) != 1:
            # Multi-branch values use the existing opaque branch-choice rows.
            continue
        value_type = variants[0].get("type")
        if value_type not in {"string", "integer", "number", "boolean", "null"}:
            continue
        row: dict[str, Any] = {
            "key": name,
            "required": name in required_names,
            "accepted_types": [str(value_type)],
        }
        description = expanded_member.get("description")
        if isinstance(description, str) and description:
            row["description"] = description
        enum_values = variants[0].get("enum")
        if isinstance(enum_values, list):
            row["enum"] = list(enum_values)
        members.append(row)
    return members


def dynamic_container_disclosure(
    contract: TypedRequestContract,
    *,
    parent_handle: str,
    key: str,
    shape: str,
    child_handle: str,
    member_key: str | None = None,
    parent_schema: Mapping[str, Any] | None = None,
    parent_section: str | None = None,
    choice_handle: str | None = None,
) -> dict[str, Any]:
    """Describe one schema-known dynamic container without exposing a document."""

    parent = contract.fields_by_handle.get(parent_handle)
    if parent is None:
        if parent_schema is None:
            return {
                "shape": shape,
                "open": True,
                "required_keys": [],
                "branch_choices": [],
                "member_key_disclosure_required": False,
                "schema_lineage": {},
            }
        lineage_parent = _dynamic_container_contract(
            handle=parent_handle,
            name="dynamic-parent",
            shape=str(parent_schema.get("type")),
            schema=parent_schema,
            root_schema=contract.schema_roots[parent_section or "args"],
            graph=contract.definition_graph,
            section=parent_section or "args",
        )
        if lineage_parent.shape == "array":
            choices = _dynamic_array_item_choices_for_field(
                contract,
                field=lineage_parent,
                index=int(key),
                shape=shape,
            )
            matching = [
                variant
                for handle, _variant_index, variant in choices
                if handle == choice_handle
            ]
            if len(choices) > 1:
                if len(matching) != 1:
                    raise TypedRequestError(
                        "Typed array item disclosure requires its issued choice handle"
                    )
                schema = matching[0]
            else:
                schema = _require_unique_container_variant(
                    lineage_parent.variants, shape
                )
        elif lineage_parent.shape == "map":
            matching = [
                variant
                for variant in _map_key_variants(lineage_parent, key)
                if variant.get("type") == shape
            ]
            schema = (
                _map_container_variant_for_handle(
                    contract,
                    field=lineage_parent,
                    key=key,
                    shape=shape,
                    handle=child_handle,
                )
                if len(matching) > 1
                else _map_container_variant(lineage_parent, key, shape)
            )
        else:
            raise TypedRequestError("Dynamic container parent is not a collection")
        root_schema = contract.schema_roots[parent_section or "args"]
    elif parent.shape == "array":
        matching = [
            variant for variant in parent.variants if variant.get("type") == shape
        ]
        schema = (
            _array_item_variant_for_handle(
                contract,
                field=parent,
                index=int(key),
                shape=shape,
                handle=child_handle,
            )
            if len(matching) > 1
            else _require_unique_container_variant(parent.variants, shape)
        )
        root_schema = contract.schema_roots[parent.section]
    elif parent.shape == "map":
        matching = [
            variant
            for variant in _map_key_variants(parent, key)
            if variant.get("type") == shape
        ]
        schema = (
            _map_container_variant_for_handle(
                contract,
                field=parent,
                key=key,
                shape=shape,
                handle=child_handle,
            )
            if len(matching) > 1
            else _map_container_variant(parent, key, shape)
        )
        root_schema = contract.schema_roots[parent.section]
    else:
        raise TypedRequestError("Dynamic container parent is not a collection")
    child = _dynamic_container_contract(
        handle=child_handle,
        name=key,
        shape=shape,
        schema=schema,
        root_schema=root_schema,
        graph=contract.definition_graph,
        section=parent.section if parent is not None else (parent_section or "args"),
    )
    branches = _dynamic_map_branch_payloads(
        contract,
        child=child,
        object_handle=child_handle,
        member_key=member_key,
    )
    constant_fields = _variant_constant_fields(
        _expanded_schema(
            schema,
            root_schema=root_schema,
            graph=contract.definition_graph,
        )
    )
    constant_field_facts = []
    for constant_key, constant_value in constant_fields.items():
        value_type = _typed_value_type(constant_value)
        constant_field_facts.append(
            {
                "typed_fact": {
                    "action": "map-put",
                    "handle": child_handle,
                    "key": constant_key,
                    "value_type": value_type,
                    "value": _typed_value_text(constant_value, value_type),
                }
            }
        )
    return {
        "shape": shape,
        "open": child.open_map,
        "required_keys": list(child.required_map_keys),
        **({"constant_fields": constant_fields} if constant_fields else {}),
        **(
            {"constant_field_facts": constant_field_facts}
            if constant_field_facts
            else {}
        ),
        "fixed_container_members": _fixed_container_members(
            schema,
            root_schema=root_schema,
            graph=contract.definition_graph,
        ),
        "fixed_scalar_members": _fixed_scalar_members(
            schema,
            root_schema=root_schema,
            graph=contract.definition_graph,
        ),
        "branch_choices": branches,
        "member_key_disclosure_required": (
            member_key is None
            and (
                any(
                    _optional_literal_pattern_key(pattern) is None
                    and len(variants) > 1
                    for pattern, variants in child.map_patterns
                )
                or len(child.additional_variants) > 1
            )
        ),
        "schema_lineage": dict(schema),
    }


def _dynamic_map_branch_payloads(
    contract: TypedRequestContract,
    *,
    child: TypedFieldContract,
    object_handle: str,
    member_key: str | None,
) -> list[dict[str, Any]]:
    branches: list[dict[str, Any]] = []
    if child.shape != "map":
        return branches
    branch_members: list[tuple[str, tuple[Mapping[str, Any], ...]]] = []
    if member_key is not None:
        _require_bounded_map_key(member_key)
        variants = _map_key_variants(child, member_key)
        matching_groups = [
            group
            for pattern, group in child.map_patterns
            if re.search(pattern, member_key) is not None
        ]
        choice_required = any(len(group) > 1 for group in matching_groups)
        if not matching_groups:
            choice_required = len(child.additional_variants) > 1
        if choice_required:
            branch_members.append((member_key, variants))
    else:
        for pattern, variants in child.map_patterns:
            literal_key = _optional_literal_pattern_key(pattern)
            if literal_key is not None and len(variants) > 1:
                branch_members.append((literal_key, variants))
    construction_keys = tuple(
        dict.fromkeys((*child.required_map_keys, *child.fixed_map_keys))
    )
    construction_order = {
        key: index for index, key in enumerate(construction_keys)
    }
    branch_members.sort(
        key=lambda member: construction_order.get(
            member[0], len(construction_order)
        )
    )
    for branch_key, variants in branch_members:
        choices = dynamic_branch_choices(
            contract,
            object_handle=object_handle,
            key=branch_key,
            value_schema={"oneOf": list(variants)},
        )
        branches.append(
            {
                "key": branch_key,
                "choices": [
                    {
                        "handle": choice_handle,
                        "accepted_types": [str(variant.get("type"))],
                        "required_keys": list(variant.get("required", ())),
                        "constant_fields": _variant_constant_fields(variant),
                        **(
                            {"enum": list(variant["enum"])}
                            if isinstance(variant.get("enum"), list)
                            else {}
                        ),
                    }
                    for choice_handle, variant in choices
                ],
            }
        )
    return branches


def typed_schema_lineage_token(
    contract: TypedRequestContract,
    *,
    child_handle: str,
    parent_token: str | None = None,
    parent_handle: str,
    key: str,
    shape: str,
    choice_handle: str | None = None,
) -> str:
    """Encode bounded route steps; the Gateway always rederives their schema."""

    from base64 import urlsafe_b64encode

    steps = [
        *(_decode_lineage_steps(parent_token) if parent_token is not None else []),
        {
            "parent_handle": parent_handle,
            "key": key,
            "shape": shape,
            "choice_handle": choice_handle,
        },
    ]
    compact_steps = [
        [
            step["parent_handle"],
            step["key"],
            step["shape"],
            step["choice_handle"],
        ]
        for step in steps
    ]
    encoded = urlsafe_b64encode(canonical_json_bytes(compact_steps)).decode(
        "ascii"
    ).rstrip("=")
    return f"{TYPED_SCHEMA_LINEAGE_PREFIX}{encoded}"


def parse_typed_schema_lineage_token(
    contract: TypedRequestContract,
    *,
    parent_handle: str,
    token: str | None,
) -> tuple[Mapping[str, Any], str] | None:
    """Validate and decode one Gateway-issued recursive disclosure token."""

    if token is None:
        return None
    from base64 import urlsafe_b64decode
    import json

    if not token.startswith(TYPED_SCHEMA_LINEAGE_PREFIX):
        raise TypedRequestError("Typed schema lineage token is unknown or stale")
    raw = token[len(TYPED_SCHEMA_LINEAGE_PREFIX):]
    if len(raw) > MAX_TYPED_REQUEST_BYTES * 2:
        raise TypedRequestError("Typed schema lineage token exceeds its byte limit")
    try:
        decoded = urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TypedRequestError("Typed schema lineage token is malformed") from exc
    if canonical_json_bytes(payload) != decoded:
        raise TypedRequestError("Typed schema lineage token is noncanonical")
    steps = _expand_compact_lineage_steps(payload)
    derived = _derive_schema_from_lineage_steps(contract, steps)
    if derived is None or derived[1] != parent_handle:
        raise TypedRequestError("Typed schema lineage token is unknown or stale")
    return derived[0], derived[2]


def typed_schema_lineage_business_pointer(
    contract: TypedRequestContract,
    *,
    child_handle: str,
    token: str,
) -> str:
    """Return the exact canonical request location named by a lineage token."""

    # The caller has just issued this token from the already validated
    # container request. Nested callers independently revalidate it through
    # parse_typed_schema_lineage_token before it can authorize another handle.
    if not child_handle.startswith(TYPED_DYNAMIC_HANDLE_PREFIX):
        raise TypedRequestError("Typed schema lineage child handle is invalid")
    steps = _decode_lineage_steps(token)
    if not steps:
        raise TypedRequestError("Typed schema lineage token is empty")
    root_handle = steps[0]["parent_handle"]
    root = next(
        (field for field in contract.fields if field.handle == root_handle),
        None,
    )
    if root is None:
        raise TypedRequestError("Typed schema lineage token has no request root")

    def escape(value: object) -> str:
        return str(value).replace("~", "~0").replace("/", "~1")

    parts = [root.section, *root.path]
    parts.extend(str(step["key"]) for step in steps)
    return "/" + "/".join(escape(part) for part in parts)


def typed_schema_lineage_root_business_pointer(
    contract: TypedRequestContract,
    *,
    child_handle: str,
    token: str,
) -> str:
    """Return the outermost dynamic value location named by a lineage token."""

    if not child_handle.startswith(TYPED_DYNAMIC_HANDLE_PREFIX):
        raise TypedRequestError("Typed schema lineage child handle is invalid")
    steps = _decode_lineage_steps(token)
    if not steps:
        raise TypedRequestError("Typed schema lineage token is empty")
    root_handle = steps[0]["parent_handle"]
    root = next(
        (field for field in contract.fields if field.handle == root_handle),
        None,
    )
    if root is None:
        raise TypedRequestError("Typed schema lineage token has no request root")

    def escape(value: object) -> str:
        return str(value).replace("~", "~0").replace("/", "~1")

    parts = [root.section, *root.path, str(steps[0]["key"])]
    return "/" + "/".join(escape(part) for part in parts)


def _decode_lineage_steps(token: str) -> list[Mapping[str, Any]]:
    from base64 import urlsafe_b64decode
    import json

    if not token.startswith(TYPED_SCHEMA_LINEAGE_PREFIX):
        raise TypedRequestError("Typed schema lineage token is unknown or stale")
    raw = token[len(TYPED_SCHEMA_LINEAGE_PREFIX):]
    if len(raw) > MAX_TYPED_REQUEST_BYTES * 2:
        raise TypedRequestError("Typed schema lineage token exceeds its byte limit")
    try:
        payload = json.loads(
            urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise TypedRequestError("Typed schema lineage token is malformed") from exc
    return _expand_compact_lineage_steps(payload)


def _expand_compact_lineage_steps(payload: Any) -> list[Mapping[str, Any]]:
    """Expand the compact public token only after validating its closed shape."""

    if not isinstance(payload, list) or len(payload) > MAX_TYPED_SCHEMA_DEPTH:
        raise TypedRequestError("Typed schema lineage token is malformed")
    steps: list[Mapping[str, Any]] = []
    for row in payload:
        if not isinstance(row, list) or len(row) != 4:
            raise TypedRequestError("Typed schema lineage token is malformed")
        parent_handle, key, shape, choice_handle = row
        if (
            not isinstance(parent_handle, str)
            or not isinstance(key, str)
            or shape not in {"object", "array"}
            or (choice_handle is not None and not isinstance(choice_handle, str))
        ):
            raise TypedRequestError("Typed schema lineage token is malformed")
        steps.append(
            {
                "parent_handle": parent_handle,
                "key": key,
                "shape": shape,
                "choice_handle": choice_handle,
            }
        )
    return steps


def _derive_schema_from_lineage_steps(
    contract: TypedRequestContract,
    raw_steps: Sequence[Any],
) -> tuple[Mapping[str, Any], str, str] | None:
    current_field: TypedFieldContract | None = None
    current_schema: Mapping[str, Any] | None = None
    expected_handle: str | None = None
    origin_section: str | None = None
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, Mapping) or set(raw_step) != {
            "parent_handle", "key", "shape", "choice_handle"
        }:
            return None
        parent_handle = raw_step.get("parent_handle")
        key = raw_step.get("key")
        shape = raw_step.get("shape")
        choice_handle = raw_step.get("choice_handle")
        if not isinstance(parent_handle, str) or not isinstance(key, str) or shape not in {
            "object", "array"
        } or (choice_handle is not None and not isinstance(choice_handle, str)):
            return None
        if index == 0:
            current_field = contract.fields_by_handle.get(parent_handle)
            if current_field is None:
                return None
            origin_section = current_field.section
        elif parent_handle != expected_handle or current_schema is None:
            return None
        if index > 0:
            current_field = _dynamic_container_contract(
                handle=parent_handle,
                name="lineage-parent",
                shape=str(current_schema.get("type")),
                schema=current_schema,
                root_schema=contract.schema_roots[origin_section or "args"],
                graph=contract.definition_graph,
                section=origin_section or "args",
            )
        assert current_field is not None
        if current_field.shape == "array":
            if re.fullmatch(r"0|[1-9][0-9]*", key) is None:
                return None
            choices = _dynamic_array_item_choices_for_field(
                contract,
                field=current_field,
                index=int(key),
                shape=shape,
            )
            selected = [
                (variant_index, variant)
                for handle, variant_index, variant in choices
                if handle == choice_handle
            ]
            if len(choices) > 1:
                if len(selected) != 1:
                    return None
                variant_index, current_schema = selected[0]
            elif len(choices) == 1 and choice_handle in {None, choices[0][0]}:
                variant_index, current_schema = choices[0][1], choices[0][2]
            else:
                return None
        elif current_field.shape == "map":
            choices = _dynamic_map_container_choices(
                contract,
                field=current_field,
                key=key,
                shape=shape,
            )
            selected = [
                (variant_index, variant)
                for handle, variant_index, variant in choices
                if handle == choice_handle
            ]
            if len(choices) > 1:
                if len(selected) != 1:
                    return None
                variant_index, current_schema = selected[0]
            elif len(choices) == 1 and choice_handle in {None, choices[0][0]}:
                variant_index, current_schema = choices[0][1], choices[0][2]
            else:
                return None
        else:
            return None
        expected_handle = TYPED_DYNAMIC_HANDLE_PREFIX + canonical_sha256(
            {
                "schema_digest": contract.schema_digest,
                "parent_handle": parent_handle,
                "key": key,
                "shape": shape,
                **(
                    {"variant_index": variant_index}
                    if len(choices) > 1
                    else {}
                ),
            }
        )[:24]
    if current_schema is None or expected_handle is None:
        return None
    return current_schema, expected_handle, origin_section or "args"


def _optional_literal_pattern_key(pattern: str) -> str | None:
    if pattern.startswith("^") and pattern.endswith("$"):
        candidate = pattern[1:-1].replace("\\", "")
        if re.escape(candidate) == pattern[1:-1]:
            return candidate
    return None


def materialize_typed_request(
    contract: TypedRequestContract,
    *,
    schema_digest: str,
    facts: Sequence[TypedRequestFact],
) -> MaterializedTypedRequest:
    """Atomically validate typed facts and materialize canonical request trees."""

    if schema_digest != contract.schema_digest:
        raise TypedRequestError(
            "Typed request schema digest is stale or belongs to another version"
        )
    for field in contract.fields:
        expected_handle = TYPED_REQUEST_HANDLE_PREFIX + canonical_sha256(
            {
                "schema_digest": contract.schema_digest,
                "section": field.section,
                "path": list(field.handle_path or field.path),
            }
        )[:24]
        if field.handle != expected_handle:
            raise TypedRequestError("Typed request contract handles are corrupt or stale")
    if len(facts) > MAX_TYPED_REQUEST_FACTS:
        raise TypedRequestError(
            f"Typed request accepts at most {MAX_TYPED_REQUEST_FACTS} facts"
        )
    by_handle = contract.fields_by_handle
    dynamic_fields: dict[
        str, tuple[str, str, str, int, TypedFieldContract]
    ] = {}
    invalidated_dynamic_fields: set[str] = set()
    scalar_values: dict[str, Any] = {}
    array_values: dict[str, list[Any]] = {}
    array_object_values: dict[str, dict[str, Any]] = {}
    map_values: dict[str, dict[str, Any]] = {}
    branch_choices: dict[str, str] = {}
    present_handles: set[str] = set()
    pending_facts = list(facts)
    deferred_facts = 0
    while pending_facts:
        fact = pending_facts.pop(0)
        field = by_handle.get(fact.handle)
        dynamic = dynamic_fields.get(fact.handle)
        if field is None and dynamic is not None:
            field = dynamic[4]
        if field is None:
            if (
                fact.handle.startswith(TYPED_DYNAMIC_HANDLE_PREFIX)
                and deferred_facts < len(pending_facts)
            ):
                pending_facts.append(fact)
                deferred_facts += 1
                continue
            raise TypedRequestError("Typed request field handle is unknown or stale")
        deferred_facts = 0
        if fact.action == "set":
            if field.shape != "scalar":
                raise TypedRequestError(f"Field {field.name!r} requires --append")
            if fact.handle in scalar_values:
                raise TypedRequestError(f"Field {field.name!r} may be set only once")
            scalar_values[fact.handle] = _parse_typed_scalar(
                fact.value_type,
                fact.value,
                variants=field.variants,
                field_name=field.name,
            )
        elif fact.action == "append":
            if field.shape != "array":
                raise TypedRequestError(f"Field {field.name!r} requires --set")
            values = array_values.setdefault(fact.handle, [])
            maximum_items = min(
                MAX_TYPED_ARRAY_ITEMS,
                field.maximum_items
                if field.maximum_items is not None
                else MAX_TYPED_ARRAY_ITEMS,
            )
            if len(values) >= maximum_items:
                raise TypedRequestError(
                    f"Field {field.name!r} accepts at most {maximum_items} items"
                )
            if fact.value_type in {"object", "array"}:
                if not any(
                    variant.get("type") == fact.value_type
                    for variant in field.variants
                ):
                    raise TypedRequestError(
                        f"Field {field.name!r} does not accept {fact.value_type} items"
                    )
                matching_variants = [
                    variant
                    for variant in field.variants
                    if variant.get("type") == fact.value_type
                ]
                if len(matching_variants) == 1:
                    expected = dynamic_array_item_handle(
                        contract,
                        array_handle=field.handle,
                        index=len(values),
                        shape=fact.value_type,
                    )
                    selected_variant = matching_variants[0]
                    if fact.value != expected:
                        raise TypedRequestError("Typed array item handle is unknown or stale")
                else:
                    selected_variant = _array_item_variant_for_handle(
                        contract,
                        field=field,
                        index=len(values),
                        shape=fact.value_type,
                        handle=fact.value,
                    )
                    expected = fact.value
                parent_depth = dynamic[3] if dynamic is not None else 0
                if parent_depth + 1 > MAX_TYPED_SCHEMA_DEPTH:
                    raise TypedRequestError("Typed array nesting exceeds its depth limit")
                values.append({} if fact.value_type == "object" else [])
                dynamic_fields[expected] = (
                    field.handle,
                    str(len(values) - 1),
                    fact.value_type,
                    parent_depth + 1,
                    _dynamic_container_contract(
                        handle=expected,
                        name=f"{field.name}[{len(values) - 1}]",
                        shape=fact.value_type,
                        schema=selected_variant,
                        root_schema=contract.schema_roots[field.section],
                        graph=contract.definition_graph,
                        section=field.section,
                    ),
                )
                array_object_values[expected] = values[-1]
            else:
                parsed_item = _parse_typed_scalar(
                    fact.value_type,
                    fact.value,
                    variants=field.variants,
                    field_name=field.name,
                )
                if field.unique_items and parsed_item in values:
                    raise TypedRequestError(
                        f"Field {field.name!r} requires unique array items"
                    )
                values.append(parsed_item)
            present_handles.add(fact.handle)
        elif fact.action == "present":
            if field.shape not in {"object", "array", "map"}:
                raise TypedRequestError(
                    f"Field {field.name!r} is not an object or array container"
                )
            if fact.handle in present_handles:
                raise TypedRequestError(
                    f"Field {field.name!r} may be marked present only once"
                )
            present_handles.add(fact.handle)
        elif fact.action == "choose":
            if field.shape != "branch":
                raise TypedRequestError(f"Field {field.name!r} is not a branch")
            selected = by_handle.get(fact.value)
            if selected is None or selected.parent_handle != field.handle:
                raise TypedRequestError("Typed request branch choice is unknown or stale")
            if fact.handle in branch_choices:
                raise TypedRequestError(f"Field {field.name!r} branch may be chosen once")
            branch_choices[fact.handle] = selected.handle
            present_handles.add(field.handle)
        elif fact.action == "choose-dynamic":
            if field.shape != "map" or not isinstance(fact.key, str):
                raise TypedRequestError("Dynamic branch choice requires an object handle and key")
            variants = _map_key_variants(field, fact.key)
            choices = tuple(
                TYPED_DYNAMIC_CHOICE_PREFIX + canonical_sha256(
                    {
                        "schema_digest": contract.schema_digest,
                        "object_handle": field.handle,
                        "key": fact.key,
                        "index": index,
                    }
                )[:24]
                for index in range(len(variants))
            )
            if fact.value not in choices:
                raise TypedRequestError("Dynamic branch choice is unknown or stale")
            branch_index = choices.index(fact.value)
            branch_choices[f"{field.handle}:{fact.key}"] = str(branch_index)
        elif fact.action in {"map-put", "map-correct", "map-remove"}:
            if field.shape != "map" or not isinstance(fact.key, str):
                raise TypedRequestError("Typed map action requires a map handle and key")
            _require_bounded_map_key(
                fact.key, maximum_bytes=field.maximum_key_bytes
            )
            if fact.key in field.fixed_map_keys:
                raise TypedRequestError(
                    "Typed map facts cannot override a fixed reflected property"
                )
            values = map_values.setdefault(field.handle, {})
            if fact.action == "map-remove":
                if fact.key not in values:
                    raise TypedRequestError("Typed map key cannot be removed before it exists")
                prior = values[fact.key]
                del values[fact.key]
                if isinstance(prior, (dict, list)):
                    invalidated_dynamic_fields.update(
                        handle
                        for handle, (parent, key, _shape, _depth, _field) in dynamic_fields.items()
                        if parent == field.handle and key == fact.key
                    )
            else:
                if fact.action == "map-put" and fact.key in values:
                    raise TypedRequestError("Typed map key already exists; use correction")
                if (
                    fact.action == "map-put"
                    and field.maximum_properties is not None
                    and len(values) >= field.maximum_properties
                ):
                    raise TypedRequestError(
                        f"Field {field.name!r} accepts at most "
                        f"{field.maximum_properties} properties"
                    )
                if fact.action == "map-correct" and fact.key not in values:
                    raise TypedRequestError("Typed map key must exist before correction")
                variants = _map_key_variants(field, fact.key)
                explicit_branch_required = any(
                    len(group) > 1
                    for pattern, group in field.map_patterns
                    if re.search(pattern, fact.key) is not None
                ) or len(field.additional_variants) > 1
                if explicit_branch_required:
                    selected_index = branch_choices.get(f"{field.handle}:{fact.key}")
                    if selected_index is None:
                        raise TypedRequestError(
                            "Typed dynamic branch requires an explicit choice"
                        )
                    variants = (variants[int(selected_index)],)
                if fact.value_type in {"object", "array"}:
                    if not _map_key_accepts_container(field, fact.key, fact.value_type):
                        raise TypedRequestError(
                            "Typed map container violates its reflected value schema"
                        )
                    _require_all_matching_map_container_constraints(
                        field, fact.key, fact.value_type
                    )
                    parent_depth = dynamic[3] if dynamic is not None else 0
                    if parent_depth + 1 > MAX_TYPED_SCHEMA_DEPTH:
                        raise TypedRequestError("Typed map nesting exceeds its depth limit")
                    matching_containers = [
                        variant
                        for variant in variants
                        if variant.get("type") == fact.value_type
                    ]
                    unrestricted_open_container = (
                        field.open_map
                        and not field.additional_variants
                        and not any(
                            re.search(pattern, fact.key) is not None
                            for pattern, _group in field.map_patterns
                        )
                    )
                    if unrestricted_open_container:
                        selected_variant = _map_container_variant(
                            field, fact.key, fact.value_type
                        )
                    elif len(matching_containers) != 1:
                        raise TypedRequestError(
                            "Typed map container branch requires an explicit choice"
                        )
                    else:
                        selected_variant = matching_containers[0]
                    original_variants = _map_key_variants(field, fact.key)
                    matching_original = [
                        (index, variant)
                        for index, variant in enumerate(original_variants)
                        if variant.get("type") == fact.value_type
                    ]
                    selected_original_index = next(
                        (
                            index
                            for index, variant in matching_original
                            if variant is selected_variant or variant == selected_variant
                        ),
                        None,
                    )
                    expected = TYPED_DYNAMIC_HANDLE_PREFIX + canonical_sha256(
                        {
                            "schema_digest": contract.schema_digest,
                            "parent_handle": field.handle,
                            "key": fact.key,
                            "shape": fact.value_type,
                            **(
                                {"variant_index": selected_original_index}
                                if not unrestricted_open_container
                                and len(matching_original) > 1
                                else {}
                            ),
                        }
                    )[:24]
                    if fact.value != expected:
                        raise TypedRequestError("Typed map container handle is unknown or stale")
                    previous_generation = [
                        handle
                        for handle, (parent, key, _shape, _depth, _field) in dynamic_fields.items()
                        if parent == field.handle and key == fact.key
                    ]
                    for handle in previous_generation:
                        invalidated_dynamic_fields.add(handle)
                        map_values.pop(handle, None)
                        array_values.pop(handle, None)
                    values[fact.key] = {} if fact.value_type == "object" else []
                    invalidated_dynamic_fields.discard(expected)
                    dynamic_fields[expected] = (
                        field.handle,
                        fact.key,
                        fact.value_type,
                        parent_depth + 1,
                        _dynamic_container_contract(
                            handle=expected,
                            name=fact.key,
                            shape=fact.value_type,
                            schema=selected_variant,
                            root_schema=contract.schema_roots[field.section],
                            graph=contract.definition_graph,
                            section=field.section,
                        ),
                    )
                else:
                    invalidated_dynamic_fields.update(
                        handle
                        for handle, (parent, key, _shape, _depth, _field) in dynamic_fields.items()
                        if parent == field.handle and key == fact.key
                    )
                    parsed_value = _parse_typed_scalar(
                        fact.value_type, fact.value, variants=variants, field_name=fact.key
                    )
                    _require_all_matching_map_constraints(
                        field, fact.key, fact.value_type, parsed_value
                    )
                    values[fact.key] = parsed_value
            present_handles.add(field.handle)
        else:
            raise TypedRequestError(f"Unsupported typed fact action {fact.action!r}")

    for dynamic_handle, (parent_handle, key, shape, _depth, dynamic_field) in sorted(
        dynamic_fields.items(), key=lambda item: item[1][3], reverse=True
    ):
        if dynamic_handle in invalidated_dynamic_fields:
            continue
        container = map_values.get(dynamic_handle) if shape == "object" else array_values.get(dynamic_handle)
        if shape == "object" and dynamic_field.required_map_keys:
            missing = set(dynamic_field.required_map_keys) - set(
                map_values.get(dynamic_handle, {})
            )
            if missing:
                raise TypedRequestError(
                    f"Typed object {dynamic_field.name!r} is missing required keys"
                )
        if shape == "object" and container is not None:
            _require_materialized_map_limits(dynamic_field, container)
        if parent_handle in array_values:
            index = int(key)
            if container is not None and array_values[parent_handle][index] in ({}, []):
                array_values[parent_handle][index] = dict(container) if shape == "object" else list(container)
        elif container is not None and map_values.get(parent_handle, {}).get(key) in ({}, []):
            map_values[parent_handle][key] = dict(container) if shape == "object" else list(container)

    for handle in (*scalar_values, *array_values, *map_values, *present_handles):
        if handle in dynamic_fields:
            continue
        parent_handle = by_handle[handle].parent_handle
        while parent_handle is not None:
            present_handles.add(parent_handle)
            parent_handle = by_handle[parent_handle].parent_handle

    args: dict[str, Any] = {}
    options: dict[str, Any] = {}
    materialized_containers: set[str] = set()
    ordered_fields = sorted(contract.fields, key=lambda item: len(item.path))
    # Fixed members must materialize before a same-path patterned overlay so
    # the overlay augments the object instead of being overwritten by it.
    ordered_fields.sort(key=lambda item: item.overlay)
    for field in ordered_fields:
        parent_present = (
            field.parent_handle is None
            or field.parent_handle in materialized_containers
        )
        present = (
            field.handle in scalar_values
            or field.handle in array_values
            or field.handle in present_handles
        )
        if field.parent_handle is not None:
            parent = by_handle[field.parent_handle]
            if parent.shape == "branch":
                selected = branch_choices.get(parent.handle)
                if present and selected != field.handle:
                    raise TypedRequestError("Typed branch value requires its explicit branch choice")
                if selected != field.handle:
                    continue
                present = True
        if field.overlay and field.parent_handle is not None:
            present = present and parent_present
        if field.required and parent_present and field.shape in {"object", "array", "map", "branch"}:
            present = True
        if field.required and parent_present and field.shape == "scalar" and not present:
            raise TypedRequestError(f"Required field {field.name!r} is missing")
        if not present:
            continue
        if field.shape == "branch":
            if field.handle not in branch_choices:
                raise TypedRequestError(f"Required field {field.name!r} branch is missing")
            materialized_containers.add(field.handle)
            continue
        if field.shape == "object":
            value: Any = {}
            materialized_containers.add(field.handle)
        elif field.shape == "array":
            value = list(array_values.get(field.handle, ()))
            materialized_containers.add(field.handle)
        elif field.shape == "map":
            value = dict(map_values.get(field.handle, {}))
            _require_materialized_map_limits(field, value)
            materialized_containers.add(field.handle)
        else:
            if field.handle not in scalar_values:
                raise TypedRequestError(f"Required field {field.name!r} is missing")
            value = scalar_values[field.handle]
        if (
            field.shape == "array"
            and field.minimum_items is not None
            and len(value) < field.minimum_items
        ):
            raise TypedRequestError(
                f"Field {field.name!r} requires at least {field.minimum_items} items"
            )
        target = args if field.section == "args" else options
        if field.overlay:
            existing = _nested_mapping(target, field.path)
            for key, item in value.items():
                if key in existing:
                    raise TypedRequestError("Typed request fixed and patterned keys overlap")
                existing[key] = item
        else:
            _set_nested_value(target, field.path, value)
    request = MaterializedTypedRequest(
        version=contract.version,
        uri=contract.uri,
        schema_digest=contract.schema_digest,
        args=args,
        options=options,
    )
    if len(canonical_json_bytes(request.as_dict())) > MAX_TYPED_REQUEST_BYTES:
        raise TypedRequestError(
            f"Typed request exceeds the {MAX_TYPED_REQUEST_BYTES}-byte limit"
        )
    return request


def typed_request_facts_for_values(
    contract: TypedRequestContract,
    *,
    args: Mapping[str, Any],
    options: Mapping[str, Any],
) -> tuple[TypedRequestFact, ...]:
    """Encode one exact materialized request back into its typed fact stream.

    This is the deterministic inverse of :func:`materialize_typed_request`.
    It is used by trusted protocol compilers and evidence validators that
    already own a canonical request.  It never accepts a caller-authored
    schema, and verifies the generated stream by rematerializing it before
    returning.
    """

    return typed_request_construction_for_values(
        contract,
        args=args,
        options=options,
    ).facts


def typed_request_construction_for_values(
    contract: TypedRequestContract,
    *,
    args: Mapping[str, Any],
    options: Mapping[str, Any],
) -> TypedRequestConstruction:
    """Return exact facts plus every public dynamic-handle disclosure."""

    if not isinstance(args, Mapping) or not isinstance(options, Mapping):
        raise TypedRequestError("Typed request values must be args/options objects")
    expected_sections = {"args": dict(args), "options": dict(options)}
    facts: list[TypedRequestFact] = []
    disclosures: list[TypedRequestDisclosure] = []
    top_level = tuple(
        field for field in contract.fields if field.parent_handle is None
    )
    for section in ("args", "options"):
        values = expected_sections[section]
        schema = _expanded_schema(
            contract.schema_roots[section],
            root_schema=contract.schema_roots[section],
            graph=contract.definition_graph,
        )
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise TypedRequestError("Typed request root properties are malformed")
        known = {
            field.path[0]
            for field in top_level
            if field.section == section and field.path
        }
        overlay_fields = tuple(
            field
            for field in contract.fields
            if field.section == section
            and field.parent_handle is None
            and field.overlay
        )
        overlay_keys = {
            key
            for key in values
            if any(
                _map_key_is_authorized(field, key)
                for field in overlay_fields
            )
        }
        unknown = set(values) - known - overlay_keys
        if unknown:
            raise TypedRequestError(
                "Typed request values contain fields outside the disclosed contract"
            )
        ordered_names = [name for name in properties if name in values]
        ordered_names.extend(sorted(set(values) - set(ordered_names)))
        for name in ordered_names:
            value = values[name]
            field = next(
                (
                    item
                    for item in top_level
                    if item.section == section
                    and item.path == (name,)
                    and not item.overlay
                ),
                None,
            )
            node = properties.get(name)
            if field is None and name in overlay_keys:
                field = next(
                    item
                    for item in overlay_fields
                    if _map_key_is_authorized(item, name)
                )
                node = schema
                _append_dynamic_object_members(
                    contract,
                    facts,
                    handle=field.handle,
                    value={name: value},
                    schema=node,
                    section=section,
                    disclosures=disclosures,
                )
                continue
            if field is not None and field.shape == "map" and field.overlay:
                _append_dynamic_object_members(
                    contract,
                    facts,
                    handle=field.handle,
                    value={name: value},
                    schema=schema,
                    section=section,
                    disclosures=disclosures,
                )
                continue
            if field is None or not isinstance(node, Mapping):
                raise TypedRequestError(
                    f"Typed request field {name!r} is not disclosed"
                )
            _append_value_facts(
                contract,
                facts,
                field=field,
                value=value,
                schema=node,
                section=section,
                disclosures=disclosures,
            )
    generated = tuple(facts)
    materialized = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=generated,
    )
    if materialized.args != dict(args) or materialized.options != dict(options):
        raise TypedRequestError(
            "Typed request facts do not replay to the canonical request values"
        )
    return TypedRequestConstruction(generated, tuple(disclosures))


def _map_key_is_authorized(field: TypedFieldContract, key: str) -> bool:
    try:
        _map_key_variants(field, key)
    except TypedRequestError:
        return False
    return True


def _typed_value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypedRequestError("Typed request number must be finite")
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    raise TypedRequestError("Typed request value has no supported fact type")


def _typed_value_text(value: Any, value_type: str) -> str:
    if value_type == "null":
        return "null"
    if value_type == "boolean":
        return "true" if value else "false"
    return str(value)


def _schema_variant_matches_value(
    schema: Mapping[str, Any],
    value: Any,
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> bool:
    try:
        return _value_matches_schema(
            value,
            schema,
            root_schema=root_schema,
            graph=graph,
            depth=0,
        )
    except (RecursionError, TypedRequestError):
        return False


def _preferred_matching_variants(
    variants: Sequence[Mapping[str, Any]],
    value: Any,
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> tuple[int, ...]:
    """Select the most specific reflected branch for one exact value."""

    matches = tuple(
        index
        for index, variant in enumerate(variants)
        if _schema_variant_matches_value(
            variant,
            value,
            root_schema=root_schema,
            graph=graph,
        )
    )
    if len(matches) <= 1:
        return matches

    def specificity(variant: Mapping[str, Any]) -> int:
        expanded = _expanded_schema(
            variant,
            root_schema=root_schema,
            graph=graph,
        )
        return (
            4
            if "const" in expanded
            else 3
            if "enum" in expanded
            else 2
            if "pattern" in expanded
            else 1
            if "required" in expanded
            else 0
        )

    highest = max(specificity(variants[index]) for index in matches)
    preferred = tuple(
        index for index in matches if specificity(variants[index]) == highest
    )
    if len(preferred) > 1:
        canonical = {
            canonical_json_bytes(
                {
                    key: value
                    for key, value in variants[index].items()
                    if key not in {"description", "synopsis"}
                }
            ): index
            for index in preferred
        }
        if len(canonical) == 1:
            return (preferred[0],)
    return preferred


def _value_matches_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
    depth: int,
) -> bool:
    if depth > MAX_TYPED_SCHEMA_DEPTH:
        raise TypedRequestError("Typed request value exceeds its schema depth")
    expanded = _expanded_schema(schema, root_schema=root_schema, graph=graph)
    for keyword in ("oneOf", "anyOf"):
        branches = expanded.get(keyword)
        if isinstance(branches, list):
            matches = sum(
                isinstance(branch, Mapping)
                and _value_matches_schema(
                    value,
                    branch,
                    root_schema=root_schema,
                    graph=graph,
                    depth=depth + 1,
                )
                for branch in branches
            )
            return matches == 1 if keyword == "oneOf" else matches >= 1
    value_type = _typed_value_type(value)
    declared = expanded.get("type")
    allowed_types = (
        tuple(declared) if isinstance(declared, list) else (declared,)
    )
    if declared is not None and value_type not in allowed_types and not (
        value_type == "integer" and "number" in allowed_types
    ):
        return False
    if value_type not in {"object", "array"}:
        inferred = dict(expanded)
        inferred.setdefault("type", value_type)
        return _scalar_matches_variant(value, inferred)
    if value_type == "array":
        minimum = expanded.get("minItems")
        maximum = expanded.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            return False
        if isinstance(maximum, int) and len(value) > maximum:
            return False
        items = expanded.get("items")
        return not isinstance(items, Mapping) or all(
            _value_matches_schema(
                item,
                items,
                root_schema=root_schema,
                graph=graph,
                depth=depth + 1,
            )
            for item in value
        )
    assert isinstance(value, Mapping)
    properties = expanded.get("properties", {})
    patterns = expanded.get("patternProperties", {})
    required = expanded.get("required", [])
    if (
        not isinstance(properties, Mapping)
        or not isinstance(patterns, Mapping)
        or not isinstance(required, list)
        or not set(required).issubset(value)
    ):
        return False
    additional = expanded.get("additionalProperties", True)
    ordered_keys = [key for key in properties if key in value]
    ordered_keys.extend(sorted(set(value) - set(ordered_keys)))
    for key in ordered_keys:
        item = value[key]
        if not isinstance(key, str):
            return False
        fixed = properties.get(key)
        if isinstance(fixed, Mapping) and not _value_matches_schema(
            item,
            fixed,
            root_schema=root_schema,
            graph=graph,
            depth=depth + 1,
        ):
            return False
        matched = False
        for pattern, pattern_schema in patterns.items():
            if (
                isinstance(pattern, str)
                and isinstance(pattern_schema, Mapping)
                and re.search(pattern, key) is not None
            ):
                matched = True
                if not _value_matches_schema(
                    item,
                    pattern_schema,
                    root_schema=root_schema,
                    graph=graph,
                    depth=depth + 1,
                ):
                    return False
        if fixed is None and not matched:
            if additional is False:
                return False
            if isinstance(additional, Mapping) and not _value_matches_schema(
                item,
                additional,
                root_schema=root_schema,
                graph=graph,
                depth=depth + 1,
            ):
                return False
    return True


def _select_branch_child(
    contract: TypedRequestContract,
    field: TypedFieldContract,
    value: Any,
) -> TypedFieldContract:
    children = tuple(
        child for child in contract.fields if child.parent_handle == field.handle
    )
    child_schemas = tuple(
        _branch_child_schema(contract, child=child, section=field.section)
        for child in children
    )
    selected = _preferred_matching_variants(
        child_schemas,
        value,
        root_schema=contract.schema_roots[field.section],
        graph=contract.definition_graph,
    )
    candidates: list[TypedFieldContract] = []
    for index, child in enumerate(children):
        child_schema = _branch_child_schema(
            contract,
            child=child,
            section=field.section,
        )
        if index in selected:
            candidates.append(child)
    if len(candidates) != 1:
        raise TypedRequestError(
            f"Typed request branch {field.name!r} is ambiguous for its value"
        )
    return candidates[0]


def _branch_child_schema(
    contract: TypedRequestContract,
    *,
    child: TypedFieldContract,
    section: str,
) -> Mapping[str, Any]:
    node: Mapping[str, Any] = contract.schema_roots[section]
    for part in child.path:
        expanded = _expanded_schema(
            node,
            root_schema=contract.schema_roots[section],
            graph=contract.definition_graph,
        )
        properties = expanded.get("properties", {})
        if not isinstance(properties, Mapping) or not isinstance(
            properties.get(part), Mapping
        ):
            raise TypedRequestError("Typed request branch path is malformed")
        node = properties[part]
    variants = _structural_variants(
        node,
        root_schema=contract.schema_roots[section],
        graph=contract.definition_graph,
    )
    try:
        index = int(child.name.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        # Static scalar branch children are disclosed by their type name
        # (for example ``integer`` / ``string``), whereas structural branch
        # children carry an explicit ``branch:N`` name. Resolve the former
        # from the exact child variant instead of inventing an index.
        matches = tuple(
            index
            for index, variant in enumerate(variants)
            if canonical_json_bytes(variant)
            == canonical_json_bytes(child.variants[0])
        ) if len(child.variants) == 1 else ()
        if len(matches) != 1:
            raise TypedRequestError("Typed request branch child is malformed")
        index = matches[0]
    if not 0 <= index < len(variants):
        raise TypedRequestError("Typed request branch child is stale")
    return variants[index]


def _append_value_facts(
    contract: TypedRequestContract,
    facts: list[TypedRequestFact],
    *,
    field: TypedFieldContract,
    value: Any,
    schema: Mapping[str, Any],
    section: str,
    disclosures: list[TypedRequestDisclosure],
) -> None:
    if field.shape == "branch":
        child = _select_branch_child(contract, field, value)
        facts.append(TypedRequestFact("choose", field.handle, "branch", child.handle))
        child_schema = _branch_child_schema(contract, child=child, section=section)
        if child.shape == "object":
            _append_static_object_facts(
                contract,
                facts,
                parent=child,
                value=value,
                schema=child_schema,
                section=section,
                disclosures=disclosures,
            )
            return
        _append_value_facts(
            contract,
            facts,
            field=child,
            value=value,
            schema=child_schema,
            section=section,
            disclosures=disclosures,
        )
        return
    if field.shape == "scalar":
        value_type = _typed_value_type(value)
        facts.append(
            TypedRequestFact(
                "set",
                field.handle,
                value_type,
                _typed_value_text(value, value_type),
            )
        )
        return
    if field.shape == "array":
        if not isinstance(value, list):
            raise TypedRequestError(f"Typed request field {field.name!r} must be an array")
        if not value:
            facts.append(TypedRequestFact("present", field.handle, "null", "null"))
            return
        item_schema = _expanded_schema(
            schema,
            root_schema=contract.schema_roots[section],
            graph=contract.definition_graph,
        ).get("items")
        if not isinstance(item_schema, Mapping):
            raise TypedRequestError("Typed request array item schema is missing")
        for index, item in enumerate(value):
            item_type = _typed_value_type(item)
            if item_type in {"object", "array"}:
                choices = dynamic_array_item_choices(
                    contract,
                    array_handle=field.handle,
                    index=index,
                    shape=item_type,
                )
                matching = [
                    (choice, variant)
                    for choice, _variant_index, variant in choices
                    if _schema_variant_matches_value(
                        variant,
                        item,
                        root_schema=contract.schema_roots[section],
                        graph=contract.definition_graph,
                    )
                ]
                if len(matching) != 1:
                    raise TypedRequestError(
                        f"Typed request array {field.name!r} has an ambiguous item"
                    )
                choice = matching[0][0] if len(choices) > 1 else None
                handle = dynamic_array_item_handle(
                    contract,
                    array_handle=field.handle,
                    index=index,
                    shape=item_type,
                    choice_handle=choice,
                )
                disclosures.append(
                    TypedRequestDisclosure(
                        command="request-array-item",
                        parent_handle=field.handle,
                        key=str(index),
                        shape=item_type,
                        child_handle=handle,
                        choice_handle=choice,
                        choice_index=(
                            next(
                                choice_index
                                for choice_index, (candidate, _variant_index, _variant) in enumerate(choices)
                                if candidate == choice
                            )
                            if choice is not None
                            else None
                        ),
                    )
                )
                facts.append(TypedRequestFact("append", field.handle, item_type, handle))
                disclosure = dynamic_container_disclosure(
                    contract,
                    parent_handle=field.handle,
                    key=str(index),
                    shape=item_type,
                    child_handle=handle,
                    choice_handle=choice,
                )
                _append_dynamic_container_facts(
                    contract,
                    facts,
                    handle=handle,
                    value=item,
                    schema=disclosure["schema_lineage"],
                    section=section,
                    disclosures=disclosures,
                )
            else:
                facts.append(
                    TypedRequestFact(
                        "append",
                        field.handle,
                        item_type,
                        _typed_value_text(item, item_type),
                    )
                )
        return
    if field.shape in {"object", "map"}:
        if not isinstance(value, Mapping):
            raise TypedRequestError(f"Typed request field {field.name!r} must be an object")
        if field.shape == "object":
            _append_static_object_facts(
                contract,
                facts,
                parent=field,
                value=value,
                schema=schema,
                section=section,
                disclosures=disclosures,
            )
        else:
            if not value:
                facts.append(TypedRequestFact("present", field.handle, "null", "null"))
            _append_dynamic_object_members(
                contract,
                facts,
                handle=field.handle,
                value=value,
                schema=schema,
                section=section,
                disclosures=disclosures,
            )
        return
    raise TypedRequestError(f"Typed request field {field.name!r} has an unsupported shape")


def _append_static_object_facts(
    contract: TypedRequestContract,
    facts: list[TypedRequestFact],
    *,
    parent: TypedFieldContract,
    value: Any,
    schema: Mapping[str, Any],
    section: str,
    disclosures: list[TypedRequestDisclosure],
) -> None:
    if not isinstance(value, Mapping):
        raise TypedRequestError("Typed request branch object value must be an object")
    children = {
        child.name: child
        for child in contract.fields
        if child.parent_handle == parent.handle and not child.overlay
    }
    overlays = tuple(
        child
        for child in contract.fields
        if child.parent_handle == parent.handle and child.overlay
    )
    if len(overlays) > 1:
        raise TypedRequestError("Typed request object has ambiguous map overlays")
    expanded = _expanded_schema(
        schema,
        root_schema=contract.schema_roots[section],
        graph=contract.definition_graph,
    )
    properties = expanded.get("properties", {})
    if not isinstance(properties, Mapping):
        raise TypedRequestError("Typed request object properties are malformed")
    if not value:
        facts.append(TypedRequestFact("present", parent.handle, "null", "null"))
    ordered_keys = [key for key in properties if key in value]
    ordered_keys.extend(sorted(set(value) - set(ordered_keys)))
    for key in ordered_keys:
        item = value[key]
        child = children.get(key)
        child_schema = properties.get(key)
        if key in properties:
            if child is None or not isinstance(child_schema, Mapping):
                raise TypedRequestError(
                    f"Typed request object key {key!r} is not disclosed"
                )
            _append_value_facts(
                contract,
                facts,
                field=child,
                value=item,
                schema=child_schema,
                section=section,
                disclosures=disclosures,
            )
            continue
        else:
            if not overlays:
                raise TypedRequestError(
                    f"Typed request object key {key!r} is not disclosed"
                )
            _append_dynamic_object_members(
                contract,
                facts,
                handle=overlays[0].handle,
                value={key: item},
                schema=schema,
                section=section,
                disclosures=disclosures,
            )
            continue


def _append_dynamic_container_facts(
    contract: TypedRequestContract,
    facts: list[TypedRequestFact],
    *,
    handle: str,
    value: Any,
    schema: Mapping[str, Any],
    section: str,
    disclosures: list[TypedRequestDisclosure],
) -> None:
    if isinstance(value, Mapping):
        _append_dynamic_object_members(
            contract,
            facts,
            handle=handle,
            value=value,
            schema=schema,
            section=section,
            disclosures=disclosures,
        )
        return
    if isinstance(value, list):
        dynamic = _dynamic_container_contract(
            handle=handle,
            name="dynamic-array",
            shape="array",
            schema=schema,
            root_schema=contract.schema_roots[section],
            graph=contract.definition_graph,
            section=section,
        )
        if not value:
            return
        for index, item in enumerate(value):
            item_type = _typed_value_type(item)
            if item_type in {"object", "array"}:
                choices = dynamic_array_item_choices(
                    contract,
                    array_handle=handle,
                    index=index,
                    shape=item_type,
                    parent_schema=schema,
                    parent_section=section,
                )
                matching = [
                    (choice, variant)
                    for choice, _variant_index, variant in choices
                    if _schema_variant_matches_value(
                        variant,
                        item,
                        root_schema=contract.schema_roots[section],
                        graph=contract.definition_graph,
                    )
                ]
                if len(matching) != 1:
                    raise TypedRequestError("Typed dynamic array item is ambiguous")
                choice = matching[0][0] if len(choices) > 1 else None
                child = dynamic_array_item_handle(
                    contract,
                    array_handle=handle,
                    index=index,
                    shape=item_type,
                    choice_handle=choice,
                    parent_schema=schema,
                    parent_section=section,
                )
                disclosures.append(
                    TypedRequestDisclosure(
                        command="request-array-item",
                        parent_handle=handle,
                        key=str(index),
                        shape=item_type,
                        child_handle=child,
                        choice_handle=choice,
                        choice_index=(
                            next(
                                choice_index
                                for choice_index, (candidate, _variant_index, _variant) in enumerate(choices)
                                if candidate == choice
                            )
                            if choice is not None
                            else None
                        ),
                        parent_child_handle=handle,
                    )
                )
                facts.append(TypedRequestFact("append", handle, item_type, child))
                disclosure = dynamic_container_disclosure(
                    contract,
                    parent_handle=handle,
                    key=str(index),
                    shape=item_type,
                    child_handle=child,
                    parent_schema=schema,
                    parent_section=section,
                    choice_handle=choice,
                )
                _append_dynamic_container_facts(
                    contract,
                    facts,
                    handle=child,
                    value=item,
                    schema=disclosure["schema_lineage"],
                    section=section,
                    disclosures=disclosures,
                )
            else:
                facts.append(
                    TypedRequestFact(
                        "append",
                        handle,
                        item_type,
                        _typed_value_text(item, item_type),
                    )
                )
        return
    raise TypedRequestError("Typed dynamic container value is malformed")


def _append_dynamic_object_members(
    contract: TypedRequestContract,
    facts: list[TypedRequestFact],
    *,
    handle: str,
    value: Mapping[str, Any],
    schema: Mapping[str, Any],
    section: str,
    disclosures: list[TypedRequestDisclosure],
) -> None:
    dynamic = _dynamic_container_contract(
        handle=handle,
        name="dynamic-object",
        shape="object",
        schema=schema,
        root_schema=contract.schema_roots[section],
        graph=contract.definition_graph,
        section=section,
    )
    expanded_schema = _expanded_schema(
        schema,
        root_schema=contract.schema_roots[section],
        graph=contract.definition_graph,
    )
    fixed_properties = expanded_schema.get("properties", {})
    if not isinstance(fixed_properties, Mapping):
        raise TypedRequestError("Typed dynamic object properties are malformed")
    schema_keys = (
        *dynamic.required_map_keys,
        *(key for key in fixed_properties if isinstance(key, str)),
    )
    ordered_keys = list(dict.fromkeys(key for key in schema_keys if key in value))
    ordered_keys.extend(sorted(set(value) - set(ordered_keys)))
    for key in ordered_keys:
        item = value[key]
        item_type = _typed_value_type(item)
        variants = _map_key_variants(dynamic, key)
        selected_indexes = _preferred_matching_variants(
            variants,
            item,
            root_schema=contract.schema_roots[section],
            graph=contract.definition_graph,
        )
        if not selected_indexes:
            raise TypedRequestError(f"Typed map key {key!r} has no matching value schema")
        choice_handle: str | None = None
        explicit_choice = any(
            len(group) > 1
            for pattern, group in dynamic.map_patterns
            if re.search(pattern, key) is not None
        ) or len(dynamic.additional_variants) > 1
        if explicit_choice:
            choices = dynamic_branch_choices(
                contract,
                object_handle=handle,
                key=key,
                value_schema={"oneOf": list(variants)},
            )
            preferred = _preferred_matching_variants(
                tuple(variant for _choice, variant in choices),
                item,
                root_schema=contract.schema_roots[section],
                graph=contract.definition_graph,
            )
            selected = [choices[index][0] for index in preferred]
            if len(selected) != 1:
                raise TypedRequestError(f"Typed map key {key!r} has an ambiguous branch")
            choice_handle = selected[0]
            facts.append(
                TypedRequestFact(
                    "choose-dynamic", handle, "choice", choice_handle, key=key
                )
            )
        if item_type in {"object", "array"}:
            parent_choice_group_index = None
            if choice_handle is not None and handle not in contract.fields_by_handle:
                branch_rows = _dynamic_map_branch_payloads(
                    contract,
                    child=dynamic,
                    object_handle=handle,
                    member_key=None,
                )
                parent_choice_group_index = next(
                    (
                        index
                        for index, row in enumerate(branch_rows)
                        if row.get("key") == key
                    ),
                    None,
                )
                if parent_choice_group_index is None:
                    raise TypedRequestError(
                        f"Typed map key {key!r} lacks its parent-published branch"
                    )
            child = dynamic_map_entry_handle(
                contract,
                map_handle=handle,
                key=key,
                shape=item_type,
                choice_handle=choice_handle,
                parent_schema=schema,
                parent_section=section,
            )
            disclosures.append(
                TypedRequestDisclosure(
                    command="request-map-container",
                    parent_handle=handle,
                    key=key,
                    shape=item_type,
                    child_handle=child,
                    choice_handle=choice_handle,
                    choice_index=(
                        next(
                            choice_index
                            for choice_index, (candidate, _variant) in enumerate(choices)
                            if candidate == choice_handle
                        )
                        if choice_handle is not None
                        else None
                    ),
                    parent_child_handle=(
                        handle if handle not in contract.fields_by_handle else None
                    ),
                    parent_choice_group_index=parent_choice_group_index,
                )
            )
            facts.append(TypedRequestFact("map-put", handle, item_type, child, key=key))
            disclosure = dynamic_container_disclosure(
                contract,
                parent_handle=handle,
                key=key,
                shape=item_type,
                child_handle=child,
                parent_schema=schema,
                parent_section=section,
                choice_handle=choice_handle,
            )
            _append_dynamic_container_facts(
                contract,
                facts,
                handle=child,
                value=item,
                schema=disclosure["schema_lineage"],
                section=section,
                disclosures=disclosures,
            )
        else:
            facts.append(
                TypedRequestFact(
                    "map-put",
                    handle,
                    item_type,
                    _typed_value_text(item, item_type),
                    key=key,
                )
            )


def _flatten_structural_branch_nodes(
    branches: Sequence[Any],
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> tuple[Mapping[str, Any], ...]:
    """Resolve nested reflected oneOf/anyOf wrappers into concrete branches."""

    flattened: list[Mapping[str, Any]] = []
    for raw_branch in branches:
        if not isinstance(raw_branch, Mapping):
            raise TypedRequestError("Typed request branch must be an object")
        branch = _expanded_schema(
            raw_branch,
            root_schema=root_schema,
            graph=graph,
        )
        nested = branch.get("oneOf", branch.get("anyOf"))
        if isinstance(nested, list) and set(branch).issubset(
            {"oneOf", "anyOf", "description", "synopsis"}
        ):
            flattened.extend(
                _flatten_structural_branch_nodes(
                    nested,
                    root_schema=root_schema,
                    graph=graph,
                )
            )
        else:
            flattened.append(branch)
    return tuple(flattened)


def _collect_object_fields(
    node: Mapping[str, Any],
    *,
    section: str,
    path: tuple[str, ...],
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
    schema_digest: str,
    fields: list[TypedFieldContract],
    node_count: list[int],
    depth: int,
    parent_handle: str | None,
    handle_path_prefix: tuple[str, ...] | None = None,
) -> None:
    node_count[0] += 1
    if node_count[0] > MAX_TYPED_SCHEMA_NODES or depth >= MAX_TYPED_SCHEMA_DEPTH:
        raise TypedRequestError("Typed request schema exceeds its packaged structure limits")
    if node.get("type") != "object":
        raise TypedRequestError(f"Typed request {section} root must be an object")
    additional_properties = node.get("additionalProperties", True)
    if additional_properties is not False and not (
        additional_properties is True
        or isinstance(additional_properties, Mapping)
        or isinstance(node.get("patternProperties"), Mapping)
    ):
        raise TypedRequestError(
            "This typed request object requires a later open-map or branch adapter"
        )
    if (
        additional_properties is True
        or isinstance(additional_properties, Mapping)
        or isinstance(node.get("patternProperties"), Mapping)
    ):
        _append_map_overlay(
            node,
            section=section,
            path=path,
            root_schema=root_schema,
            graph=graph,
            schema_digest=schema_digest,
            fields=fields,
            parent_handle=parent_handle,
            required=False,
            name=path[-1] if path else section,
            node_count=node_count,
            handle_path_prefix=handle_path_prefix,
        )
    properties = node.get("properties", {})
    if not isinstance(properties, Mapping):
        raise TypedRequestError("Typed request object properties must be an object")
    required_raw = node.get("required", [])
    if not isinstance(required_raw, list) or not all(
        isinstance(name, str) for name in required_raw
    ):
        raise TypedRequestError("Typed request required fields must be a string array")
    required = frozenset(required_raw)
    for name, raw_child in properties.items():
        node_count[0] += 1
        if node_count[0] > MAX_TYPED_SCHEMA_NODES:
            raise TypedRequestError(
                "Typed request schema exceeds its packaged structure limits"
            )
        if not isinstance(name, str) or not isinstance(raw_child, Mapping):
            raise TypedRequestError("Typed request properties must contain schema objects")
        child_path = (*path, name)
        child_handle_path = (*(
            path if handle_path_prefix is None else handle_path_prefix
        ), name)
        child = _expanded_schema(raw_child, root_schema=root_schema, graph=graph)
        branch_nodes = child.get("oneOf", child.get("anyOf"))
        if isinstance(branch_nodes, list):
            branch_nodes = list(
                _flatten_structural_branch_nodes(
                    branch_nodes,
                    root_schema=root_schema,
                    graph=graph,
                )
            )
        child_type = child.get("type")
        # Some reflected CLI definitions express an array shape solely through
        # oneOf/anyOf branches (for example one tuple versus an array of
        # tuples). Do not misclassify those structural branches as scalars.
        if isinstance(branch_nodes, list) and child_type is None:
            branch_types = {
                _expanded_schema(
                    branch,
                    root_schema=root_schema,
                    graph=graph,
                ).get("type")
                for branch in branch_nodes
                if isinstance(branch, Mapping)
            }
            if len(branch_types) == 1:
                child_type = next(iter(branch_types))
        handle = TYPED_REQUEST_HANDLE_PREFIX + canonical_sha256(
            {
                "schema_digest": schema_digest,
                "section": section,
                "path": list(child_handle_path),
            }
        )[:24]
        if isinstance(branch_nodes, list):
            if not branch_nodes:
                raise TypedRequestError(f"Typed request field {name!r} has an empty branch")
            fields.append(
                TypedFieldContract(
                    handle=handle,
                    section=section,
                    name=name,
                    path=child_path,
                    required=name in required,
                    shape="branch",
                    variants=(),
                    parent_handle=parent_handle,
                    handle_path=child_handle_path,
                )
            )
            for index, raw_branch in enumerate(branch_nodes):
                node_count[0] += 1
                if node_count[0] > MAX_TYPED_SCHEMA_NODES:
                    raise TypedRequestError(
                        "Typed request schema exceeds its packaged structure limits"
                    )
                if not isinstance(raw_branch, Mapping):
                    raise TypedRequestError("Typed request branch must be an object")
                branch = _expanded_schema(
                    raw_branch, root_schema=root_schema, graph=graph
                )
                branch_type = branch.get("type", child_type)
                if "type" not in branch and isinstance(branch_type, str):
                    branch = {"type": branch_type, **branch}
                branch_path = (*child_handle_path, f"<branch:{index}>")
                branch_handle = TYPED_REQUEST_HANDLE_PREFIX + canonical_sha256(
                    {
                        "schema_digest": schema_digest,
                        "section": section,
                        "path": list(branch_path),
                    }
                )[:24]
                branch_name = f"{branch_type}:{index}"
                if branch_type == "object":
                    fields.append(
                        TypedFieldContract(
                            handle=branch_handle,
                            section=section,
                            name=branch_name,
                            path=child_path,
                            required=False,
                            shape="object",
                            variants=(),
                            parent_handle=handle,
                            handle_path=branch_path,
                        )
                    )
                    _collect_object_fields(
                        branch,
                        section=section,
                        path=child_path,
                        root_schema=root_schema,
                        graph=graph,
                        schema_digest=schema_digest,
                        fields=fields,
                        node_count=node_count,
                        depth=depth + 1,
                        parent_handle=branch_handle,
                        handle_path_prefix=branch_path,
                    )
                elif branch_type == "array":
                    value_schema = branch.get("items")
                    if not isinstance(value_schema, Mapping):
                        raise TypedRequestError(
                            "Typed request array branch has no item schema"
                        )
                    fields.append(
                        TypedFieldContract(
                            handle=branch_handle,
                            section=section,
                            name=branch_name,
                            path=child_path,
                            required=False,
                            shape="array",
                            variants=_structural_variants(
                                value_schema,
                                root_schema=root_schema,
                                graph=graph,
                            ),
                            parent_handle=handle,
                            minimum_items=_optional_nonnegative_integer(
                                branch.get("minItems"), label=f"{name}.minItems"
                            ),
                            maximum_items=_optional_nonnegative_integer(
                                branch.get("maxItems"), label=f"{name}.maxItems"
                            ),
                            unique_items=branch.get("uniqueItems") is True,
                            handle_path=branch_path,
                        )
                    )
                else:
                    variants = _scalar_variants(
                        branch, root_schema=root_schema, graph=graph
                    )
                    fields.append(
                        TypedFieldContract(
                            handle=branch_handle,
                            section=section,
                            name=str(branch_type),
                            path=child_path,
                            required=False,
                            shape="scalar",
                            variants=variants,
                            parent_handle=handle,
                            handle_path=branch_path,
                        )
                    )
            continue
        if child_type == "object":
            pattern_properties = child.get("patternProperties", {})
            additional = child.get("additionalProperties")
            open_map = additional is True
            if (pattern_properties or open_map or isinstance(additional, Mapping)) and not child.get("properties"):
                if not isinstance(pattern_properties, Mapping):
                    raise TypedRequestError("Typed map patternProperties must be an object")
                map_patterns: list[tuple[str, tuple[Mapping[str, Any], ...]]] = []
                for pattern, raw_value_schema in pattern_properties.items():
                    if not isinstance(pattern, str) or not isinstance(raw_value_schema, Mapping):
                        raise TypedRequestError("Typed map pattern must bind a schema object")
                    try:
                        re.compile(pattern)
                    except re.error as exc:
                        raise TypedRequestError("Typed map key pattern is invalid") from exc
                    map_patterns.append(
                        (
                            pattern,
                            _structural_variants(
                                raw_value_schema,
                                root_schema=root_schema,
                                graph=graph,
                            ),
                        )
                    )
                fields.append(
                    TypedFieldContract(
                        handle=handle,
                        section=section,
                        name=name,
                        path=child_path,
                        required=name in required,
                        shape="map",
                        variants=(),
                        parent_handle=parent_handle,
                        handle_path=child_handle_path,
                        map_patterns=tuple(map_patterns),
                        additional_variants=(
                            _structural_variants(
                                additional,
                                root_schema=root_schema,
                                graph=graph,
                            )
                            if isinstance(additional, Mapping)
                            else ()
                        ),
                        open_map=open_map,
                        maximum_properties=_optional_nonnegative_integer(
                            child.get("maxProperties"),
                            label=f"{name}.maxProperties",
                        ),
                        maximum_bytes=_optional_nonnegative_integer(
                            child.get("maximumBytes"),
                            label=f"{name}.maximumBytes",
                        ),
                        maximum_key_bytes=_optional_nonnegative_integer(
                            child.get("x-keyMaximumBytes"),
                            label=f"{name}.x-keyMaximumBytes",
                        ),
                    )
                )
                continue
            fields.append(
                TypedFieldContract(
                    handle=handle,
                    section=section,
                    name=name,
                    path=child_path,
                    required=name in required,
                    shape="object",
                    variants=(),
                    parent_handle=parent_handle,
                    handle_path=child_handle_path,
                )
            )
            _collect_object_fields(
                child,
                section=section,
                path=child_path,
                root_schema=root_schema,
                graph=graph,
                schema_digest=schema_digest,
                fields=fields,
                node_count=node_count,
                depth=depth + 1,
                parent_handle=handle,
                handle_path_prefix=child_handle_path,
            )
            continue
        collection = child_type == "array"
        value_schema = child.get("items") if collection else child
        if not isinstance(value_schema, Mapping):
            raise TypedRequestError(f"Typed request field {name!r} has no item schema")
        value_schema = _expanded_schema(
            value_schema,
            root_schema=root_schema,
            graph=graph,
        )
        variants = (
            _structural_variants(
                value_schema,
                root_schema=root_schema,
                graph=graph,
            )
            if collection
            else _scalar_variants(
                value_schema,
                root_schema=root_schema,
                graph=graph,
            )
        )
        fields.append(
            TypedFieldContract(
                handle=handle,
                section=section,
                name=name,
                path=child_path,
                required=name in required,
                shape="array" if collection else "scalar",
                variants=variants,
                parent_handle=parent_handle,
                handle_path=child_handle_path,
                minimum_items=_optional_nonnegative_integer(
                    child.get("minItems"),
                    label=f"{name}.minItems",
                ),
                maximum_items=_optional_nonnegative_integer(
                    child.get("maxItems"),
                    label=f"{name}.maxItems",
                ),
                unique_items=child.get("uniqueItems") is True,
            )
        )


def _expanded_schema(
    node: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> dict[str, Any]:
    reference = node.get("$ref", node.get("#ref"))
    if reference is None:
        return dict(node)
    if not isinstance(reference, str) or not reference:
        raise TypedRequestError("Typed request schema reference must be non-empty")
    try:
        resolved = resolve_schema_reference(
            reference,
            root_schema=root_schema,
            graph=graph,
        )
    except SchemaInventoryError as exc:
        raise TypedRequestError(str(exc)) from exc
    merged = dict(contextual_schema_target(resolved))
    merged.update({key: value for key, value in node.items() if key not in {"$ref", "#ref"}})
    return merged


def _count_reachable_schema_nodes(
    node: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
    active_references: frozenset[str],
) -> int:
    reference = node.get("$ref", node.get("#ref"))
    if isinstance(reference, str):
        if reference in active_references:
            return 1
        active_references = frozenset((*active_references, reference))
    expanded = _expanded_schema(node, root_schema=root_schema, graph=graph)
    count = 1
    for keyword in ("properties", "patternProperties"):
        children = expanded.get(keyword, {})
        if isinstance(children, Mapping):
            for child in children.values():
                if isinstance(child, Mapping):
                    count += _count_reachable_schema_nodes(
                        child,
                        root_schema=root_schema,
                        graph=graph,
                        active_references=active_references,
                    )
    for keyword in ("items", "additionalProperties"):
        child = expanded.get(keyword)
        if isinstance(child, Mapping):
            count += _count_reachable_schema_nodes(
                child,
                root_schema=root_schema,
                graph=graph,
                active_references=active_references,
            )
    for keyword in ("oneOf", "anyOf"):
        children = expanded.get(keyword, [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, Mapping):
                    count += _count_reachable_schema_nodes(
                        child,
                        root_schema=root_schema,
                        graph=graph,
                        active_references=active_references,
                    )
    return count


def _append_map_overlay(
    node: Mapping[str, Any],
    *,
    section: str,
    path: tuple[str, ...],
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
    schema_digest: str,
    fields: list[TypedFieldContract],
    parent_handle: str | None,
    required: bool,
    name: str,
    node_count: list[int],
    handle_path_prefix: tuple[str, ...] | None = None,
) -> None:
    pattern_properties = node.get("patternProperties", {})
    if not isinstance(pattern_properties, Mapping):
        raise TypedRequestError("Typed map patternProperties must be an object")
    map_patterns: list[tuple[str, tuple[Mapping[str, Any], ...]]] = []
    for pattern, raw_value_schema in pattern_properties.items():
        if not isinstance(pattern, str) or not isinstance(raw_value_schema, Mapping):
            raise TypedRequestError("Typed map pattern must bind a schema object")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise TypedRequestError("Typed map key pattern is invalid") from exc
        map_patterns.append(
            (
                pattern,
                _structural_variants(
                    raw_value_schema,
                    root_schema=root_schema,
                    graph=graph,
                ),
            )
        )
    additional = node.get("additionalProperties", True)
    overlay_path = (*(
        path if handle_path_prefix is None else handle_path_prefix
    ), "<map>")
    fields.append(
        TypedFieldContract(
            handle=TYPED_REQUEST_HANDLE_PREFIX + canonical_sha256(
                {
                    "schema_digest": schema_digest,
                    "section": section,
                    "path": list(overlay_path),
                }
            )[:24],
            section=section,
            name=f"{name}:map",
            path=path,
            required=required,
            shape="map",
            variants=(),
            parent_handle=parent_handle,
            map_patterns=tuple(map_patterns),
            additional_variants=(
                _structural_variants(
                    additional,
                    root_schema=root_schema,
                    graph=graph,
                )
                if isinstance(additional, Mapping)
                else ()
            ),
            open_map=additional is True,
            maximum_properties=_optional_nonnegative_integer(
                node.get("maxProperties"), label=f"{name}.maxProperties"
            ),
            maximum_bytes=_optional_nonnegative_integer(
                node.get("maximumBytes"), label=f"{name}.maximumBytes"
            ),
            maximum_key_bytes=_optional_nonnegative_integer(
                node.get("x-keyMaximumBytes"),
                label=f"{name}.x-keyMaximumBytes",
            ),
            handle_path=overlay_path,
            overlay=True,
            fixed_map_keys=tuple(
                key
                for key in node.get("properties", {})
                if isinstance(key, str)
            ),
            variant_groups=tuple(
                variants for _pattern, variants in map_patterns
            ),
        )
    )


def _structural_variants(
    node: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> tuple[Mapping[str, Any], ...]:
    expanded = _expanded_schema(node, root_schema=root_schema, graph=graph)
    branches = expanded.get("oneOf", expanded.get("anyOf"))
    candidates: Sequence[Any] = branches if isinstance(branches, list) else (expanded,)
    variants: list[Mapping[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise TypedRequestError("Typed map value branch must be an object")
        resolved = _expanded_schema(candidate, root_schema=root_schema, graph=graph)
        nested_branches = resolved.get("oneOf", resolved.get("anyOf"))
        if isinstance(nested_branches, list):
            variants.extend(
                _structural_variants(
                    resolved,
                    root_schema=root_schema,
                    graph=graph,
                )
            )
            continue
        if "type" not in resolved and "const" in resolved:
            constant = resolved["const"]
            inferred = (
                "null"
                if constant is None
                else "boolean"
                if isinstance(constant, bool)
                else "integer"
                if isinstance(constant, int)
                else "number"
                if isinstance(constant, float)
                else "string"
                if isinstance(constant, str)
                else None
            )
            if inferred is not None:
                resolved = {"type": inferred, **resolved}
        if "type" not in resolved and isinstance(resolved.get("enum"), list):
            inferred_types = {
                "null"
                if value is None
                else "boolean"
                if isinstance(value, bool)
                else "integer"
                if isinstance(value, int)
                else "number"
                if isinstance(value, float)
                else "string"
                if isinstance(value, str)
                else None
                for value in resolved["enum"]
            }
            if len(inferred_types) == 1 and None not in inferred_types:
                resolved = {"type": inferred_types.pop(), **resolved}
        value_type = resolved.get("type")
        if isinstance(value_type, list):
            for item_type in value_type:
                if item_type not in {
                    "string",
                    "integer",
                    "number",
                    "boolean",
                    "null",
                    "object",
                    "array",
                }:
                    raise TypedRequestError(
                        "Typed structural field declares an unsupported type"
                    )
                variants.append({**resolved, "type": item_type})
            continue
        variants.append(resolved)
    return tuple(variants)


def _scalar_variants(
    node: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
) -> tuple[Mapping[str, Any], ...]:
    expanded = _expanded_schema(node, root_schema=root_schema, graph=graph)
    branches = expanded.get("oneOf", expanded.get("anyOf"))
    candidates: Sequence[Any] = branches if isinstance(branches, list) else (expanded,)
    variants: list[Mapping[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise TypedRequestError("Typed request scalar branch must be an object")
        resolved = _expanded_schema(candidate, root_schema=root_schema, graph=graph)
        inherited_type = expanded.get("type")
        inherited_constraints = {
            key: value
            for key, value in expanded.items()
            if key not in {"oneOf", "anyOf", "description"}
        }
        resolved = {**inherited_constraints, **resolved}
        if "type" not in resolved and isinstance(inherited_type, str):
            resolved["type"] = inherited_type
        value_type = resolved.get("type")
        if value_type is None and "const" in resolved:
            constant = resolved["const"]
            value_type = (
                "null"
                if constant is None
                else "boolean"
                if isinstance(constant, bool)
                else "integer"
                if isinstance(constant, int)
                else "number"
                if isinstance(constant, float)
                else "string"
                if isinstance(constant, str)
                else None
            )
            if value_type is not None:
                resolved["type"] = value_type
        if isinstance(value_type, list):
            for item_type in value_type:
                if item_type not in {
                    "string", "integer", "number", "boolean", "null"
                }:
                    raise TypedRequestError(
                        "This typed request field requires a later complex-shape adapter"
                    )
                variants.append({**resolved, "type": item_type})
            continue
        if value_type not in {"string", "integer", "number", "boolean", "null"}:
            raise TypedRequestError(
                "This typed request field requires a later complex-shape adapter"
            )
        variants.append(resolved)
    return tuple(variants)


def _parse_typed_scalar(
    value_type: str,
    raw_value: str,
    *,
    variants: Sequence[Mapping[str, Any]],
    field_name: str,
) -> Any:
    if value_type == "string":
        value: Any = raw_value
    elif value_type == "integer":
        if re.fullmatch(r"-?(0|[1-9][0-9]*)", raw_value) is None:
            raise TypedRequestError(f"Field {field_name!r} requires a canonical integer")
        value = int(raw_value)
    elif value_type == "number":
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise TypedRequestError(f"Field {field_name!r} requires a number") from exc
        if not math.isfinite(value):
            raise TypedRequestError(f"Field {field_name!r} requires a finite number")
    elif value_type == "boolean":
        if raw_value not in {"true", "false"}:
            raise TypedRequestError(f"Field {field_name!r} requires true or false")
        value = raw_value == "true"
    elif value_type == "null":
        if raw_value != "null":
            raise TypedRequestError(f"Field {field_name!r} requires the literal null")
        value = None
    else:
        raise TypedRequestError(f"Unsupported typed scalar type {value_type!r}")
    matching = [
        variant
        for variant in variants
        if variant.get("type") == value_type
        or (variant.get("type") == "number" and value_type == "integer")
    ]
    if not matching:
        raise TypedRequestError(
            f"Field {field_name!r} does not accept typed value {value_type!r}"
        )
    if isinstance(value, str):
        for variant in matching:
            declared = variant.get("x-maxUtf8Bytes")
            if declared is not None and (
                isinstance(declared, bool)
                or not isinstance(declared, int)
                or not 1 <= declared <= MAX_TYPED_REQUEST_BYTES
            ):
                raise TypedRequestError(
                    f"Field {field_name!r} has an invalid packaged UTF-8 byte limit"
                )
    if not any(_scalar_matches_variant(value, variant) for variant in matching):
        raise TypedRequestError(f"Field {field_name!r} violates its reflected schema")
    return value


def _scalar_matches_variant(value: Any, variant: Mapping[str, Any]) -> bool:
    if "const" in variant and value != variant["const"]:
        return False
    enum = variant.get("enum")
    if isinstance(enum, list) and value not in enum:
        return False
    minimum = variant.get("minimum")
    maximum = variant.get("maximum")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(minimum, (int, float)) and value < minimum:
            return False
        if isinstance(maximum, (int, float)) and value > maximum:
            return False
    pattern = variant.get("pattern")
    byte_limit = variant.get("x-maxUtf8Bytes", MAX_TYPED_STRING_BYTES)
    if isinstance(value, str) and len(value.encode("utf-8")) > byte_limit:
        return False
    if isinstance(value, str) and isinstance(pattern, str):
        try:
            if re.search(pattern, value) is None:
                return False
        except re.error as exc:
            raise TypedRequestError("Packaged request schema contains an invalid pattern") from exc
    minimum_length = variant.get("minLength")
    if (
        isinstance(value, str)
        and isinstance(minimum_length, int)
        and not isinstance(minimum_length, bool)
        and len(value) < minimum_length
    ):
        return False
    maximum_length = variant.get("maxLength")
    if (
        isinstance(value, str)
        and isinstance(maximum_length, int)
        and not isinstance(maximum_length, bool)
        and len(value) > maximum_length
    ):
        return False
    return True


def _set_nested_value(target: dict[str, Any], path: Sequence[str], value: Any) -> None:
    if not path:
        raise TypedRequestError("Typed request field path must not be empty")
    current = target
    for part in path[:-1]:
        existing = current.setdefault(part, {})
        if not isinstance(existing, dict):
            raise TypedRequestError("Typed request field paths overlap")
        current = existing
    current[path[-1]] = value


def _nested_mapping(target: dict[str, Any], path: Sequence[str]) -> dict[str, Any]:
    current = target
    for part in path:
        existing = current.setdefault(part, {})
        if not isinstance(existing, dict):
            raise TypedRequestError("Typed request field paths overlap")
        current = existing
    return current


def _map_key_variants(
    field: TypedFieldContract,
    key: str,
) -> tuple[Mapping[str, Any], ...]:
    _require_bounded_map_key(key, maximum_bytes=field.maximum_key_bytes)
    matches = [
        variants
        for pattern, variants in field.map_patterns
        if re.search(pattern, key) is not None
    ]
    if matches:
        return tuple(variant for variants in matches for variant in variants)
    if field.additional_variants:
        return field.additional_variants
    if field.open_map:
        return tuple({"type": value_type} for value_type in ("string", "integer", "number", "boolean", "null"))
    raise TypedRequestError("Typed map key does not match an allowed key pattern")


def _map_key_accepts_container(
    field: TypedFieldContract,
    key: str,
    shape: str,
) -> bool:
    matching = [
        variants
        for pattern, variants in field.map_patterns
        if re.search(pattern, key) is not None
    ]
    if matching:
        return any(
            variant.get("type") == shape
            for variants in matching
            for variant in variants
        )
    if field.additional_variants:
        return any(variant.get("type") == shape for variant in field.additional_variants)
    return field.open_map


def _require_all_matching_map_constraints(
    field: TypedFieldContract,
    key: str,
    value_type: str,
    value: Any,
) -> None:
    matched_groups = [
        variants
        for pattern, variants in field.map_patterns
        if re.search(pattern, key) is not None
    ]
    for variants in matched_groups:
        compatible = [
            variant
            for variant in variants
            if variant.get("type") == value_type
            or (variant.get("type") == "number" and value_type == "integer")
        ]
        if not compatible or not any(
            _scalar_matches_variant(value, variant) for variant in compatible
        ):
            raise TypedRequestError(
                "Typed map value violates a matching reflected key schema"
            )


def _require_all_matching_map_container_constraints(
    field: TypedFieldContract,
    key: str,
    shape: str,
) -> None:
    matched_groups = [
        variants
        for pattern, variants in field.map_patterns
        if re.search(pattern, key) is not None
    ]
    if matched_groups and not all(
        any(variant.get("type") == shape for variant in variants)
        for variants in matched_groups
    ):
        raise TypedRequestError(
            "Typed map container violates a matching reflected key schema"
        )


def _map_container_variant(
    field: TypedFieldContract,
    key: str,
    shape: str,
) -> Mapping[str, Any]:
    if field.open_map and not any(
        re.search(pattern, key) is not None for pattern, _variants in field.map_patterns
    ) and not field.additional_variants:
        return {"type": shape, "additionalProperties": True, "items": {}}
    variants = _map_key_variants(field, key)
    return _require_unique_container_variant(variants, shape)


def _require_unique_container_variant(
    variants: Sequence[Mapping[str, Any]],
    shape: str,
) -> Mapping[str, Any]:
    matching = [variant for variant in variants if variant.get("type") == shape]
    if len(matching) != 1:
        raise TypedRequestError("Typed container shape is ambiguous or unsupported")
    return matching[0]


def _dynamic_container_contract(
    *,
    handle: str,
    name: str,
    shape: str,
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any],
    graph: DefinitionGraph,
    section: str,
) -> TypedFieldContract:
    schema = _expanded_schema(schema, root_schema=root_schema, graph=graph)
    if shape == "array":
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise TypedRequestError("Typed dynamic array has no item schema")
        variants = (
            tuple(
                {"type": value_type}
                for value_type in (
                    "string", "integer", "number", "boolean", "null", "object", "array"
                )
            )
            if not items
            else _structural_variants(
                items, root_schema=root_schema, graph=graph
            )
        )
        return TypedFieldContract(
            handle=handle,
            section=section,
            name=name,
            path=(),
            required=False,
            shape="array",
            variants=variants,
            minimum_items=_optional_nonnegative_integer(
                schema.get("minItems"), label=f"{name}.minItems"
            ),
            maximum_items=_optional_nonnegative_integer(
                schema.get("maxItems"), label=f"{name}.maxItems"
            ),
            unique_items=schema.get("uniqueItems") is True,
        )
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise TypedRequestError("Typed dynamic object properties must be an object")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise TypedRequestError("Typed dynamic object required keys are malformed")
    patterns = schema.get("patternProperties", {})
    if not isinstance(patterns, Mapping):
        raise TypedRequestError("Typed dynamic object patterns are malformed")
    map_patterns = tuple(
        (
            pattern,
            _scalar_variants(
                value_schema, root_schema=root_schema, graph=graph
            )
            if _expanded_schema(
                value_schema, root_schema=root_schema, graph=graph
            ).get("type")
            not in {"object", "array"}
            and not isinstance(
                _expanded_schema(
                    value_schema, root_schema=root_schema, graph=graph
                ).get("oneOf", _expanded_schema(
                    value_schema, root_schema=root_schema, graph=graph
                ).get("anyOf")),
                list,
            )
            else _structural_variants(
                value_schema, root_schema=root_schema, graph=graph
            ),
        )
        for pattern, value_schema in patterns.items()
        if isinstance(pattern, str) and isinstance(value_schema, Mapping)
    ) + tuple(
        (
            rf"^{re.escape(property_name)}$",
            _structural_variants(
                property_schema, root_schema=root_schema, graph=graph
            ),
        )
        for property_name, property_schema in properties.items()
        if isinstance(property_name, str) and isinstance(property_schema, Mapping)
    )
    additional = schema.get("additionalProperties", True)
    return TypedFieldContract(
        handle=handle,
        section=section,
        name=name,
        path=(),
        required=False,
        shape="map",
        variants=(),
        map_patterns=map_patterns,
        additional_variants=(
            _structural_variants(
                additional, root_schema=root_schema, graph=graph
            )
            if isinstance(additional, Mapping)
            else ()
        ),
        open_map=additional is True,
        maximum_properties=_optional_nonnegative_integer(
            schema.get("maxProperties"), label=f"{name}.maxProperties"
        ),
        maximum_bytes=_optional_nonnegative_integer(
            schema.get("maximumBytes"), label=f"{name}.maximumBytes"
        ),
        maximum_key_bytes=_optional_nonnegative_integer(
            schema.get("x-keyMaximumBytes"),
            label=f"{name}.x-keyMaximumBytes",
        ),
        required_map_keys=tuple(required),
    )


def _require_bounded_map_key(
    key: str, *, maximum_bytes: int | None = None
) -> None:
    limit = MAX_TYPED_STRING_BYTES if maximum_bytes is None else min(
        maximum_bytes, MAX_TYPED_STRING_BYTES
    )
    if len(key.encode("utf-8")) > limit:
        raise TypedRequestError("Typed map key exceeds its UTF-8 byte limit")


def _require_materialized_map_limits(
    field: TypedFieldContract,
    value: Mapping[str, Any],
) -> None:
    if (
        field.maximum_properties is not None
        and len(value) > field.maximum_properties
    ):
        raise TypedRequestError(
            f"Field {field.name!r} accepts at most "
            f"{field.maximum_properties} properties"
        )
    if (
        field.maximum_bytes is not None
        and len(canonical_json_bytes(value)) > field.maximum_bytes
    ):
        raise TypedRequestError(
            f"Field {field.name!r} exceeds its "
            f"{field.maximum_bytes}-byte limit"
        )


def _optional_nonnegative_integer(value: Any, *, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypedRequestError(f"Typed request schema {label} must be non-negative")
    return value
