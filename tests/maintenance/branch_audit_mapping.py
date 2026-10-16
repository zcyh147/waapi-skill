"""Source-backed joins for the branch audit; declaration is never execution proof."""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import inspect
from pathlib import Path
import sys

from tests.maintenance.source_identity import repository_source_identity

LIB = "skills/waapi-skill/wwise_waapi/"
POLICY = "skills/waapi-skill/resources/native_surface_policy.json"
GATEWAY = "skills/waapi-skill/scripts/gateway.py"

# These are reviewed family entrypoints, not claims about each enum alternative.
FAMILY_MODULES = {
    "generic-cli-console": "cli_console_business.py",
    "generic-core-media-build": "media_build_business.py",
    "generic-core-project-object": "core_business.py",
    "generic-core-remaining": "core_business.py",
    "generic-core-runtime-inspection": "runtime_inspection_business.py",
    "generic-host-ui-debug-waapi": "host_ui_debug_business.py",
    "generic-soundengine-runtime": "soundengine_business.py",
    "generic-topics": "topic_business.py",
    "generic-fixed-query-metadata": "metadata_discovery.py",
    "generic-dedicated-route-boundary": "operation_registry.py",
    "generic-fixed-command-audited-deep": "operation_registry.py",
    "generic-zero-input-audited-deep": "operation_registry.py",
}


FAMILY_FINDINGS = {
    "generic-cli-console": "CLI option spelling, repeatable bank/platform/language rows, default omission and hook exclusions need exact declaration-to-native correspondence; process success is not generated-bank verification.",
    "generic-core-media-build": "Import path/source replacement and SoundBank inclusion/build alternatives need independent public value mapping and output verification, including partial results.",
    "generic-core-project-object": "Reference/property, identity, destination and conflict-mode alternatives need exact target-type and dependency mappings; route attribution does not prove each nested value.",
    "generic-core-remaining": "Remaining core contracts need URI-local field/enum mapping; inherited family materializer attribution does not identify which declaration emits each native leaf.",
    "generic-core-runtime-inspection": "Inspection selector/filter and runtime-control alternatives need bounded readback and lifetime-specific evidence; result-schema validation is weaker than state verification.",
    "generic-host-ui-debug-waapi": "UI command/registration and debug option alternatives need fresh catalog, correct-host and cleanup boundary mapping; catalog snapshots cannot establish current command availability.",
    "generic-soundengine-runtime": "Game object, playing/transport capability, enum and numeric union meanings need exact business encoding, revocation/lifetime and wrong-handle negatives per API.",
    "generic-topics": "Subscription match/options, publish payload alternatives, count/time/idle bounds and cancellation cleanup need per-topic mapping; publish-schema enumeration alone does not prove delivered events.",
    "generic-fixed-query-metadata": "Query selectors/return projections and metadata result alternatives need exact closed/advanced contract correspondence, default bounds and reference-target reachability.",
    "generic-dedicated-route-boundary": "Named operation alternatives must be separated by target type, placement, mode and verifier; plugin owner/ShareSet and class/instance property semantics cannot inherit family PASS.",
    "generic-fixed-command-audited-deep": "Fixed commands need native option and result-alternative mapping to their actual Gateway branch; a fixed CLI command name does not prove every schema alternative.",
    "generic-zero-input-audited-deep": "Zero-input routes still have host restrictions, return alternatives, side effects and paired cleanup; empty args establish no branch-specific effect verification.",
    "shared-definitions": "Resolve every reference edge from its route/profile to the definition document before assigning public reachability; structurally identical definition nodes alone establish no reachable business combination.",
}


def enrich_inventory(inventory, root, public, schemas, policy, *, digest):
    sys.path.insert(0, str(root / "skills/waapi-skill"))
    from wwise_waapi.business_adapters import business_adapter, business_adapter_operations
    from wwise_waapi.native_surface_policy import validate_native_surface_policy

    # This validates selector completeness against the independently packaged
    # reflection, including normalized-equivalence evidence requirements.
    validate_native_surface_policy(policy)
    source_index, contract_index, mappings = {}, {}, {}
    module_trees = {}

    def source(path, symbol=None):
        key = path + ("#" + symbol if symbol else "")
        if key in source_index:
            return key
        full = root / path
        text = full.read_text(encoding="utf-8")
        if path not in module_trees:
            module_trees[path] = ast.parse(text) if path.endswith(".py") else None
        node = None
        if symbol:
            node = next((item for item in ast.walk(module_trees[path])
                         if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and item.name == symbol), None)
            if node is None:
                raise ValueError(f"source symbol missing: {path}#{symbol}")
        key = path + ("#" + symbol if symbol else "")
        source_index[key] = {"path": path, "symbol": symbol, "line": node.lineno if node else 1,
                             "sha256": digest(ast.dump(node, include_attributes=False) if node else text)}
        inventory["sources"][path] = digest(text)
        return key

    def callable_sources(function):
        path = repository_source_identity(Path(inspect.getsourcefile(function)).resolve(), root.resolve())
        refs = [source(path, function.__name__)]
        node = next(item for item in ast.walk(module_trees[path]) if isinstance(item, ast.FunctionDef) and item.name == function.__name__)
        # Adapter wrappers import their operation compiler locally. Record that
        # concrete compiler as well as the authoritative registered wrapper.
        for item in ast.walk(node):
            if isinstance(item, ast.ImportFrom) and item.level == 1 and item.module:
                target = LIB + item.module.replace(".", "/") + ".py"
                for alias in item.names:
                    refs.append(source(target, alias.name))
        return refs

    adapter_names = business_adapter_operations()
    routes = {row["id"]: row for row in inventory["routes"]}
    for key, row in routes.items():
        version, kind, uri = key.split("|", 2)
        family = public[key]["classification"]
        row["family"] = family
        row["reviewed_snapshot"] = {"field_contract_sha256": row.pop("public_schema"),
                                     "current_execution_credit": False}
        compiler_refs, contracts = [], []
        for operation in sorted({uri, *(item["name"] for item in row["named_operations"])}):
            if operation not in adapter_names:
                continue
            adapter = business_adapter(operation)
            try:
                contract = adapter.contract(version)
            except ValueError:
                continue
            contract_id = digest(contract)
            definition = callable_sources(adapter._contract_builder)
            compiler_refs.extend(callable_sources(adapter._materializer))
            # Public values remain indexed by current registry digest. Do not
            # copy a second full schema ledger or infer native equivalence.
            declaration = contract.get("declaration", {})
            contract_index[contract_id] = {
                "operation": operation, "version": version, "definition": definition,
                "sha256": contract_id,
                "declared_fields": sorted(declaration.get("field_value_types", {})),
                "required_fields": declaration.get("required_fields", []),
                "optional_fields": declaration.get("optional_fields", []),
                "business_dimensions": {key: contract[key] for key in ("binding", "type_discovery", "declaration", "safety") if key in contract},
                "status": "current_registry_declaration_not_execution",
            }
            contracts.append(contract_id)
        row["public_contracts"] = contracts or [source(GATEWAY, "dispatch_offline_command")]
        row["compiler"] = sorted(set(compiler_refs)) or [source(LIB + FAMILY_MODULES[family])]
        row["compiler_attribution"] = "registered_adapter" if compiler_refs else "reviewed_family_entrypoint_not_branch_proof"
        row["gateway_entrypoint"] = source(GATEWAY, "dispatch_command")
        row["verifier_source"] = [source(LIB + "operation_registry.py", "verify_prepared_operation")] if row["execution_policy"]["effect"] != "read" and kind == "function" else [source(LIB + "builders/schema.py", "validate_semantic_result")]
        if kind == "topic":
            row["verifier_source"] = [source(LIB + "subscriptions.py", "SubscriptionManager")]
        if uri == "ak.wwise.core.object.get":
            row["public_contracts"] = [source(GATEWAY, "query_business_schema_payload")]
            row["compiler"] = [source(GATEWAY, "_compile_query_business_projection"),
                               source(LIB + "builders/query.py")]
            row["compiler_attribution"] = "fixed_query_entrypoint_not_branch_proof"
            row["verifier_source"] = [source(GATEWAY, "validate_query_business_view_result")]
        row["branch_mapping"] = "source_attribution_joined; see per-branch mapping"

    inventory["family_findings"] = FAMILY_FINDINGS
    inventory["policy_rule_index"] = {
        str(index): {key: value for key, value in rule.items() if key != "scopes"}
        for index, rule in enumerate(policy["rules"])
    }
    mapping_candidates = defaultdict(list)
    declared = 0
    for index, rule in enumerate(policy["rules"]):
        for scope_index, scope in enumerate(rule["scopes"]):
            for disposition, selectors in scope["classifications"].items():
                for selector in selectors:
                    declared += 1
                    if selector.startswith("pattern:"):
                        pointer = scope["pointer"] + "/patternProperties/" + selector[8:].replace("~", "~0").replace("/", "~1")
                    elif selector.startswith("$ref:"):
                        pointer = scope["pointer"] + "/$ref"
                    else:
                        pointer = scope["pointer"] + "/properties/" + selector.replace("~", "~0").replace("/", "~1")
                    mapping_id = f"policy:{index}:{scope_index}:{selector}"
                    mappings[mapping_id] = {
                        "basis": "native_surface_policy_selector", "disposition": disposition,
                        "policy_rule": str(index),
                        "source": f"{POLICY}#/rules/{index}/scopes/{scope_index}/classifications/{disposition}",
                        "selector": selector, "native_pointer": pointer, "profile": rule["profile"],
                        "public_operations": rule["operations"], "fixed_commands": rule["fixed_commands"],
                        "public_contract_and_compiler_join": "branch.route -> routes.public_contracts/compiler/verifier_source",
                        "public_value_binding": "selector disposition declared; exact value/enum correspondence still requires review",
                        "program_result": "not_established_by_source_mapping", "native_result": "not_established_by_source_mapping",
                    }
                    for version in rule["versions"]:
                        mapping_candidates[f"{version}|function|{rule['uri']}"].append((pointer, mapping_id))
    inventory["sources"][POLICY] = digest(policy)
    for route in mapping_candidates:
        mapping_candidates[route].sort(key=lambda item: len(item[0]), reverse=True)

    native_shapes = defaultdict(set)
    for version, _, uri, schema in schemas:
        native_shapes[(version, uri)].add(digest(schema))
    residuals = {}
    counts = Counter()
    for branch in inventory["branches"]:
        route = routes.get(branch["route"])
        mapping = next((mapping_id for pointer, mapping_id in mapping_candidates.get(branch["route"], [])
                        if branch["pointer"] == pointer or branch["pointer"].startswith(pointer + "/")), None)
        branch["mapping"] = mapping or "no_selector_disposition"
        branch["mapping_relation"] = (
            "selector" if mapping and branch["pointer"] == mappings[mapping]["native_pointer"]
            else "descendant_scope_only" if mapping else "not_joined"
        )
        counts[branch["mapping_relation"]] += 1
        if route:
            version, _, uri = branch["route"].split("|", 2)
            family, hashes = route["family"], sorted(native_shapes[(version, uri)])
        else:
            family, hashes = "shared-definitions", [branch["schema_sha256"]]
        # Enum and union alternatives never inherit their parent's policy as
        # execution proof. Every unresolved branch is assigned a finite group.
        group_id = digest([family, hashes])[:24]
        branch["residual_group"] = group_id
        group = residuals.setdefault(group_id, {
            "family": family, "native_schema_sha256": hashes, "routes": set(), "branch_count": 0,
            "kinds": Counter(), "selector_mapping_relations": Counter(), "sample_pointers": [],
            "missing": ["exact native branch to public value/boundary correspondence", "branch-specific positive and fail-closed program evidence", "native version evidence where behavior depends on Wwise"],
            "priority": "P1" if family != "shared-definitions" else "P2",
            "disposition": "unproven_not_unsupported",
        })
        group["branch_count"] += 1
        group["kinds"][branch["kind"]] += 1
        group["selector_mapping_relations"][branch["mapping_relation"]] += 1
        if route:
            group["routes"].add(route["id"])
        if len(group["sample_pointers"]) < 4:
            group["sample_pointers"].append(branch["pointer"])
    for group in residuals.values():
        group["routes"] = sorted(group["routes"])
        group["kinds"] = dict(sorted(group["kinds"].items()))
        group["selector_mapping_relations"] = dict(group["selector_mapping_relations"])
        if group["kinds"].get("reference"):
            group["missing"].append("reference target reachability from each public contract")
        if group["kinds"].get("enum_value") or group["kinds"].get("type_variant"):
            group["missing"].append("each enum/union alternative's business encoding or explicit boundary")
        if group["kinds"].get("optional_presence"):
            group["missing"].append("omitted value native default versus explicit public value semantics")
    # Compare, never silently reseal, the earlier depth review against current
    # public contracts. Its classification remains historical attribution.
    import json
    from tests.maintenance.interface_depth_inventory import (
        _operation_contract_rows, _public_continuation_rows,
        _gateway_parser_contract_rows, canonical_sha256)
    surface = json.loads((root / "skills/waapi-skill/resources/manifest/typed-request-surface.json").read_text())
    reviewed = json.loads((root / "docs/interface-depth-review-policy.json").read_text())["source_contracts"]
    observed = {
        "typed_request_surface_sha256": surface["inventory_sha256"],
        "operation_contract_sha256": canonical_sha256(_operation_contract_rows()),
        "public_continuation_sha256": canonical_sha256(_public_continuation_rows(surface)),
        "gateway_parser_sha256": canonical_sha256(_gateway_parser_contract_rows()),
    }
    inventory["reviewed_snapshot_seal"] = {
        "reviewed": reviewed, "current": observed,
        "status": "current" if reviewed == observed else "stale_requires_reviewed_regeneration",
        "execution_credit": False,
    }
    current_business_path = "docs/branch-coverage-current-business.json"
    inventory["current_business_branches"] = json.loads((root / current_business_path).read_text())["rows"]
    source(current_business_path)
    for business in inventory["current_business_branches"]:
        for field in ("public_contract", "compiler", "preflight", "verifier", "program_definition"):
            if field in business:
                path, _, symbol = business[field].partition("#")
                source(path, symbol or None)
    source("docs/interface-depth-review-policy.json")
    source("tests/maintenance/branch_audit_mapping.py")
    source("tests/maintenance/branch_coverage_audit.py")
    inventory.update(source_index=source_index, contract_index=contract_index, mappings=mappings,
                     residual_groups=residuals)
    inventory["summary"].update(declared_selector_dispositions=declared, mapping_relations=dict(counts),
                                residual_groups=len(residuals), current_registry_contracts=len(contract_index))
