"""Typed pre-Codex business plans for the twenty reviewed CLI V3 cases."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_cli_runtime_v3 import (
    CLI_APIS, SUPPORTED_VERSION, CliRuntimeSnapshot, CliRuntimeVerification,
    PreparedCliRuntime, _types_equivalent,
)
from tests.semantic.support.codex_eval_protocol_v3 import V3GatewayProtocol, build_transaction_protocol
from tests.semantic.support.codex_prompt_provenance_v3 import serialize_protocol


CLI_BUSINESS_PLAN_SCHEMA = "waapi-skill.cli-business-plan/v1"
CLI_FIXTURE_KIND = "cli_prepared_runtime_v1"
_ASSERTIONS = ("cli.request.exact", "cli.request_provenance", "cli.lifecycle", "cli.live.before", "cli.inputs.immutable", "cli.delta.closed")
_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$")
_CACHE_VERSION_BYTES = b"F\x00\x00\x00"
_CACHE_VERSION_SHA256 = hashlib.sha256(_CACHE_VERSION_BYTES).hexdigest()


class CliBusinessPlanError(ValueError): pass


@dataclass(frozen=True, slots=True)
class CliBusinessPlanSections:
    fixture_spec: Mapping[str, Any]
    payload_bindings: Mapping[str, Any]
    assertion_ids: tuple[str, ...]
    static_expectation: Mapping[str, Any]
    live_binding: Mapping[str, Any]
    delta_rules: tuple[Mapping[str, Any], ...]
    def writer_kwargs(self) -> dict[str, Any]:
        return {"fixture_spec": _plain(self.fixture_spec), "payload_bindings": _plain(self.payload_bindings), "assertion_ids": list(self.assertion_ids), "static_expectation": _plain(self.static_expectation), "live_binding": _plain(self.live_binding), "delta_rules": [_plain(x) for x in self.delta_rules]}


def compile_cli_business_plan(runtime: PreparedCliRuntime, protocol: V3GatewayProtocol) -> CliBusinessPlanSections:
    if not isinstance(runtime, PreparedCliRuntime): raise CliBusinessPlanError("CLI compiler requires PreparedCliRuntime")
    before = runtime.before
    request = _plain(runtime.operation_request())
    expected = build_transaction_protocol((request,), terminal_execute=runtime.plan.business_disconnect_may_occur)
    if _plain(serialize_protocol(protocol)) != _plain(serialize_protocol(expected)):
        raise CliBusinessPlanError("CLI protocol does not exactly bind request topology")
    _owned(runtime.plan.case_root, [*runtime.root_bindings.values(), runtime.plan.project_path, runtime.plan.asset_root, runtime.plan.io_root])
    static = {"family_schema_version": CLI_BUSINESS_PLAN_SCHEMA, "family": "cli", "scenario_id": runtime.plan.scenario.id, "api": runtime.plan.scenario.api, "version": runtime.plan.version, "operation": runtime.plan.operation, "asset_spec": _plain(runtime.plan.asset_spec), "asset_spec_sha256": _hash(runtime.plan.asset_spec), "operation_request": request, "operation_request_sha256": _hash(request), "request_provenance": _plain(runtime.request_provenance()), "lifecycle": _plain(runtime.lifecycle_contract), "expected_outputs": _plain(runtime.expected_outputs), "control_output_paths": [str(p) for p in runtime.control_output_paths], "protocol_sha256": _hash(serialize_protocol(protocol)), "terminal_execute": runtime.plan.business_disconnect_may_occur}
    live = {"family_schema_version": CLI_BUSINESS_PLAN_SCHEMA, "before_snapshot": _plain(before), "before_snapshot_sha256": _hash(before), "input_proofs": _plain(runtime.input_proofs), "tab_source_bindings": _compile_tab_source_bindings(runtime), "root_bindings": {k: str(v) for k,v in runtime.root_bindings.items()}, "visible_values": _plain(runtime.visible_values), "case_root": str(runtime.plan.case_root)}
    rules = _rules(static, live)
    return _sections(static, live, rules, ["tx01.execute"], [x["name"] for x in serialize_protocol(protocol)["steps"] if x["name"] != "tx01.execute"])


def validate_cli_business_plan(sections: CliBusinessPlanSections, runtime: PreparedCliRuntime, protocol: V3GatewayProtocol, *, verify_files: bool=False) -> None:
    expected = compile_cli_business_plan(runtime, protocol)
    if not isinstance(sections, CliBusinessPlanSections) or sections.writer_kwargs() != expected.writer_kwargs(): raise CliBusinessPlanError("CLI plan differs from independently recomputed runtime")
    if verify_files: _validate_proofs(sections.live_binding["input_proofs"], verify_files=True)


def parse_cli_business_plan_sections(payload: Mapping[str, Any]) -> CliBusinessPlanSections:
    names={"fixture_spec","payload_bindings","assertion_ids","static_expectation","live_binding","delta_rules"}
    if not isinstance(payload, Mapping) or not names.issubset(payload): raise CliBusinessPlanError("CLI plan lacks typed sections")
    if not all(isinstance(payload[n], Mapping) for n in ("fixture_spec","payload_bindings","static_expectation","live_binding")) or not isinstance(payload["assertion_ids"], list) or not isinstance(payload["delta_rules"], list): raise CliBusinessPlanError("CLI typed section shape is invalid")
    result=CliBusinessPlanSections(MappingProxyType(_plain(payload["fixture_spec"])),MappingProxyType(_plain(payload["payload_bindings"])),tuple(_plain(payload["assertion_ids"])),MappingProxyType(_plain(payload["static_expectation"])),MappingProxyType(_plain(payload["live_binding"])),tuple(MappingProxyType(_plain(x)) for x in payload["delta_rules"]))
    _shape(result); return result


def validate_cli_business_plan_archive(payload: Mapping[str, Any] | CliBusinessPlanSections, *, scenario: Any, version: str, protocol: V3GatewayProtocol, verify_files: bool=False) -> CliBusinessPlanSections:
    s = payload if isinstance(payload, CliBusinessPlanSections) else parse_cli_business_plan_sections(payload)
    _shape(s); static,live=s.static_expectation,s.live_binding
    if version != SUPPORTED_VERSION or static["scenario_id"] != getattr(scenario,"id",None) or static["api"] != getattr(scenario,"api",None) or static["api"] not in CLI_APIS or static["version"] != version or static["operation"] != CLI_APIS[static["api"]]: raise CliBusinessPlanError("CLI archive common identity is misbound")
    fixture=getattr(scenario,"fixture",{}); asset=fixture.get("asset_spec") if isinstance(fixture,Mapping) else None
    if _plain(asset) != static["asset_spec"] or static["asset_spec_sha256"] != _hash(asset): raise CliBusinessPlanError("CLI archive asset specification drifted")
    request=static["operation_request"]
    if static["operation_request_sha256"] != _hash(request) or not isinstance(request,Mapping) or request.get("arguments",{}).get("api") != static["api"]: raise CliBusinessPlanError("CLI archive operation request drifted")
    expected=build_transaction_protocol((request,), terminal_execute=bool(static["terminal_execute"]))
    if _plain(serialize_protocol(expected)) != _plain(serialize_protocol(protocol)) or static["protocol_sha256"] != _hash(serialize_protocol(protocol)): raise CliBusinessPlanError("CLI archive protocol topology drifted")
    names=[x["name"] for x in serialize_protocol(protocol)["steps"]]
    bindings={"primary_steps":["tx01.execute"],"verification_steps":[x for x in names if x!="tx01.execute"]}
    if _plain(s.payload_bindings)!=bindings or tuple(s.assertion_ids)!=_ASSERTIONS: raise CliBusinessPlanError("CLI archive bindings/assertions drifted")
    if live["before_snapshot_sha256"]!=_hash(live["before_snapshot"]): raise CliBusinessPlanError("CLI archive before digest drifted")
    _validate_proofs(live["input_proofs"],verify_files=verify_files)
    _validate_tab_source_bindings(static, live)
    _validate_lifecycle_and_provenance(static)
    root=Path(live["case_root"]); _owned(root,[Path(x) for x in live["root_bindings"].values()]); _owned(root,[Path(x) for x in live["visible_values"].values() if isinstance(x,str) and os.path.isabs(x)])
    if s.fixture_spec != {"kind":CLI_FIXTURE_KIND,"sha256":_hash({"static":static,"live":live})}: raise CliBusinessPlanError("CLI archive fixture digest drifted")
    if [_plain(x) for x in s.delta_rules] != _rules(static,live): raise CliBusinessPlanError("CLI archive delta rules drifted")
    return s


def validate_cli_archived_verification(sections: CliBusinessPlanSections, verification: Mapping[str, Any]) -> None:
    _shape(sections); evidence=verification.get("evidence",verification) if isinstance(verification,Mapping) else None
    if isinstance(evidence,Mapping) and isinstance(evidence.get("verification"),Mapping): evidence=evidence["verification"]
    if not isinstance(evidence,Mapping) or set(evidence)!={"scenario_id","phase","passed","failures","before","after"}: raise CliBusinessPlanError("CLI verification schema is not closed")
    static,live=sections.static_expectation,sections.live_binding
    if evidence["scenario_id"]!=static["scenario_id"] or evidence["phase"]!="after" or evidence["passed"] is not True or evidence["failures"]!=[] or evidence["before"]!=live["before_snapshot"]: raise CliBusinessPlanError("CLI verification is not exact passed after evidence")
    before,after=evidence["before"],evidence["after"]
    op=static["operation"]
    if after.get("source_template_tree")!=before.get("source_template_tree"): raise CliBusinessPlanError("CLI immutable source/template changed")
    if op=="convertExternalSource":
        validate_cli_convert_archived_side_effects(
            before,
            after,
            project_path=static["operation_request"]["arguments"]["args"]["project"],
        )
    elif after.get("asset_tree")!=before.get("asset_tree"):
        raise CliBusinessPlanError("CLI immutable input assets changed")
    if op in {"convertExternalSource","generateSoundbank"}:
        files={x.get("path"):x for x in after["output_tree"]["files"]}
        before_files={x.get("path"):x for x in before["output_tree"]["files"]}
        if len(files)!=len(after["output_tree"]["files"]) or len(before_files)!=len(before["output_tree"]["files"]): raise CliBusinessPlanError("CLI output proof paths are duplicated or invalid")
        expected_paths={x["path"] for x in static["expected_outputs"]}
        if not expected_paths.issubset(set(files)): raise CliBusinessPlanError("CLI exact expected output set is incomplete")
        for output in static["expected_outputs"]:
            row=files.get(output["path"])
            if not isinstance(row,Mapping) or row.get("size",0)<=0: raise CliBusinessPlanError("CLI expected output is absent or empty")
            old=before_files.get(output["path"])
            if output["required_change"] and old is not None and row.get("sha256")==old.get("sha256"): raise CliBusinessPlanError("CLI required output did not change")
        before_controls={x.get("path"):x for x in before["output_tree"]["files"] if x.get("path") in static["control_output_paths"]}
        after_controls={x.get("path"):x for x in after["output_tree"]["files"] if x.get("path") in static["control_output_paths"]}
        if before_controls!=after_controls: raise CliBusinessPlanError("CLI output control changed")
        if op=="generateSoundbank": _validate_generate_rebuild_archive(static,live,before_files,files)
    elif op=="tabDelimitedImport":
        expected=static["asset_spec"].get("expected",{})
        object_rows=after.get("objects",[]); before_object_rows=before.get("objects",[])
        if not isinstance(object_rows,list) or not isinstance(before_object_rows,list): raise CliBusinessPlanError("tab object evidence is invalid")
        objects={x.get("path"):x for x in object_rows if isinstance(x,Mapping)}; before_objects={x.get("path"):x for x in before_object_rows if isinstance(x,Mapping)}
        if len(objects)!=len(object_rows) or len(before_objects)!=len(before_object_rows): raise CliBusinessPlanError("tab object paths are duplicated or invalid")
        source_bindings=_tab_source_binding_map(static,live)
        before_ids={x.get("object_id") for x in before_object_rows if isinstance(x,Mapping)}; seen:dict[str,str]={}
        for row in expected.get("objects",[]):
            current=objects.get(row.get("path")); old=before_objects.get(row.get("path"))
            if not isinstance(current,Mapping) or _GUID.fullmatch(str(current.get("object_id") or "")) is None: raise CliBusinessPlanError("tab object/GUID drifted")
            if not _types_equivalent(str(current.get("object_type") or ""),str(row.get("type") or "")) or current.get("language")!=row.get("language"): raise CliBusinessPlanError("tab object type/language drifted")
            key=str(row.get("source_key") or ""); binding=source_bindings.get(key)
            if binding is None or current.get("source_sha256")!=binding["sha256"]: raise CliBusinessPlanError("tab source SHA-256 drifted")
            policy=row.get("guid_policy")
            if policy=="preserved" and (not old or old.get("object_id")!=current.get("object_id")): raise CliBusinessPlanError("tab preserved GUID drifted")
            if policy=="replaced" and (not old or old.get("object_id")==current.get("object_id")): raise CliBusinessPlanError("tab replacement GUID drifted")
            if policy=="new_unique" and old is not None: raise CliBusinessPlanError("tab new object existed before")
            if policy in {"new_unique","replaced"} and current.get("object_id") in before_ids: raise CliBusinessPlanError("tab new/replaced GUID reused before identity")
            prior=seen.setdefault(str(row.get("path")),str(current.get("object_id")))
            if prior!=current.get("object_id"): raise CliBusinessPlanError("tab same path has inconsistent GUID")
        if len(set(seen.values()))!=len(seen): raise CliBusinessPlanError("tab distinct paths share one GUID")

        event_rows=after.get("events",[]); before_event_rows=before.get("events",[])
        if not isinstance(event_rows,list) or not isinstance(before_event_rows,list): raise CliBusinessPlanError("tab Event evidence is invalid")
        events={x.get("path"):x for x in event_rows if isinstance(x,Mapping)}; before_events={x.get("path"):x for x in before_event_rows if isinstance(x,Mapping)}
        if len(events)!=len(event_rows) or len(before_events)!=len(before_event_rows): raise CliBusinessPlanError("tab Event paths are duplicated or invalid")
        expected_events={"\\Events\\Default Work Unit\\"+str(row["event"]):row for row in expected.get("objects",[]) if row.get("event")}
        event_controls={str(path) for path in expected.get("controls",[]) if str(path).startswith("\\Events\\")}
        if set(events)!=set(expected_events)|event_controls or set(before_events)!=event_controls: raise CliBusinessPlanError("tab Event inventory drifted")
        for path,row in expected_events.items():
            event=events.get(path); current=objects.get(row["path"])
            if not isinstance(event,Mapping) or not isinstance(current,Mapping) or _GUID.fullmatch(str(event.get("object_id") or "")) is None or event.get("action_types")!=[1] or event.get("target_ids")!=[current.get("object_id")] or not isinstance(event.get("action_ids"),list) or len(event["action_ids"])!=1 or _GUID.fullmatch(str(event["action_ids"][0])) is None: raise CliBusinessPlanError("tab Event/Play Action target drifted")
        for path in event_controls:
            if before_events.get(path)!=events.get(path): raise CliBusinessPlanError("tab control Event changed")
        for path in {str(value) for value in expected.get("controls",[])}-event_controls:
            if before_objects.get(path)!=objects.get(path): raise CliBusinessPlanError("tab control object changed")
    elif op=="migrate":
        if not str(after.get("project_version") or "").startswith("v2022.1") or after.get("migration_inventory")!=before.get("migration_inventory"): raise CliBusinessPlanError("migrate version or inventory drifted")


def validate_cli_convert_archived_side_effects(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    project_path: str | Path | None = None,
) -> None:
    """Validate the closed convert side-effect relation retained in TreeProof.

    The live runtime reads the newly written files before cleanup and proves the
    AKD magic bytes plus the crossover settings XML root/type.  Archived
    ``TreeProof`` rows intentionally retain only path, size, digest, and mtime,
    so this validator independently recomputes every relation available from
    those sealed facts without pretending it can parse deleted file contents.
    """

    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        raise CliBusinessPlanError("convert archive snapshots are invalid")

    asset_root, before_assets = _archived_tree_rows(
        before.get("asset_tree"), label="convert before asset tree"
    )
    after_asset_root, after_assets = _archived_tree_rows(
        after.get("asset_tree"), label="convert after asset tree"
    )
    allowed_akd = frozenset(
        PurePosixPath(relative).with_suffix(".akd").as_posix()
        for relative in before_assets
        if PurePosixPath(relative).suffix.casefold() == ".wav"
    )
    asset_additions = _closed_archived_tree_delta(
        asset_root,
        before_assets,
        after_asset_root,
        after_assets,
        allowed_additions=allowed_akd,
        label="convert asset tree",
    )
    for relative in asset_additions:
        if after_assets[relative]["size"] < 24:
            raise CliBusinessPlanError("convert AKD proof is too small")

    project_root, before_project = _archived_tree_rows(
        before.get("project_tree"), label="convert before project tree"
    )
    after_project_root, after_project = _archived_tree_rows(
        after.get("project_tree"), label="convert after project tree"
    )
    project_relative = _archived_project_relative_path(
        project_root,
        before_project,
        project_path=project_path,
    )
    settings_relative = f"{PurePosixPath(project_relative).stem}.crossover.wsettings"
    project_additions = _closed_archived_tree_delta(
        project_root,
        before_project,
        after_project_root,
        after_project,
        allowed_additions=frozenset({".cache/CacheVersion", settings_relative}),
        label="convert project tree",
    )
    cache = (
        after_project[".cache/CacheVersion"]
        if ".cache/CacheVersion" in project_additions
        else None
    )
    if cache is not None and (
        cache["size"] != len(_CACHE_VERSION_BYTES)
        or cache["sha256"] != _CACHE_VERSION_SHA256
    ):
        raise CliBusinessPlanError("convert CacheVersion proof is invalid")
    settings = (
        after_project[settings_relative]
        if settings_relative in project_additions
        else None
    )
    if settings is not None and settings["size"] <= 0:
        raise CliBusinessPlanError("convert crossover settings proof is empty")


def _archived_tree_rows(
    value: Any,
    *,
    label: str,
) -> tuple[str, dict[str, Mapping[str, Any]]]:
    if not isinstance(value, Mapping) or set(value) != {"root", "files", "sha256"}:
        raise CliBusinessPlanError(f"{label} schema is not closed")
    root = value.get("root")
    files = value.get("files")
    if (
        not isinstance(root, str)
        or not root
        or not os.path.isabs(root)
        or not isinstance(files, list)
        or not isinstance(value.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
    ):
        raise CliBusinessPlanError(f"{label} shape is invalid")

    rows: dict[str, Mapping[str, Any]] = {}
    absolute_paths: set[str] = set()
    relatives: list[str] = []
    digest = hashlib.sha256()
    for row in files:
        if not isinstance(row, Mapping) or set(row) != {
            "path", "relative_path", "size", "sha256", "mtime_ns"
        }:
            raise CliBusinessPlanError(f"{label} file proof schema is not closed")
        relative = row.get("relative_path")
        path = row.get("path")
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise CliBusinessPlanError(f"{label} relative path is invalid")
        pure_relative = PurePosixPath(relative)
        if (
            pure_relative.is_absolute()
            or pure_relative.as_posix() != relative
            or any(part in {"", ".", ".."} for part in pure_relative.parts)
            or not isinstance(path, str)
            or path != str(Path(root).joinpath(*pure_relative.parts))
            or type(row.get("size")) is not int
            or row["size"] < 0
            or type(row.get("mtime_ns")) is not int
            or row["mtime_ns"] < 0
            or not isinstance(row.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
        ):
            raise CliBusinessPlanError(f"{label} file proof is invalid")
        if relative in rows or path in absolute_paths:
            raise CliBusinessPlanError(f"{label} file proof identity is duplicated")
        rows[relative] = row
        absolute_paths.add(path)
        relatives.append(relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["size"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(row["sha256"].encode("ascii"))
        digest.update(b"\0")
    if relatives != sorted(relatives) or value["sha256"] != digest.hexdigest():
        raise CliBusinessPlanError(f"{label} order or digest is invalid")
    return root, rows


def _closed_archived_tree_delta(
    before_root: str,
    before_rows: Mapping[str, Mapping[str, Any]],
    after_root: str,
    after_rows: Mapping[str, Mapping[str, Any]],
    *,
    allowed_additions: frozenset[str],
    label: str,
) -> frozenset[str]:
    if before_root != after_root:
        raise CliBusinessPlanError(f"{label} root changed")
    if any(after_rows.get(relative) != row for relative, row in before_rows.items()):
        raise CliBusinessPlanError(f"{label} changed a sealed pre-existing file")
    additions = frozenset(after_rows) - frozenset(before_rows)
    if not additions.issubset(allowed_additions):
        raise CliBusinessPlanError(f"{label} contains an unreviewed added file")
    return additions


def _archived_project_relative_path(
    project_root: str,
    before_rows: Mapping[str, Mapping[str, Any]],
    *,
    project_path: str | Path | None,
) -> str:
    if project_path is not None:
        expected = str(project_path)
        candidates = [
            relative for relative, row in before_rows.items()
            if row["path"] == expected
        ]
    else:
        candidates = [
            relative for relative in before_rows
            if PurePosixPath(relative).suffix.casefold() == ".wproj"
            and len(PurePosixPath(relative).parts) == 1
        ]
    if (
        len(candidates) != 1
        or PurePosixPath(candidates[0]).suffix.casefold() != ".wproj"
        or before_rows[candidates[0]]["path"]
        != str(Path(project_root).joinpath(*PurePosixPath(candidates[0]).parts))
    ):
        raise CliBusinessPlanError("convert project proof is not bound to one project")
    return candidates[0]


def _compile_tab_source_bindings(runtime: PreparedCliRuntime) -> list[dict[str, str]]:
    if runtime.plan.operation != "tabDelimitedImport":
        return []
    bindings = _derive_tab_source_bindings(
        runtime.plan.asset_spec,
        _plain(runtime.input_proofs),
    )
    for binding in bindings:
        path = Path(binding["path"])
        if _file_hash(path) != binding["sha256"]:
            raise CliBusinessPlanError("tab source changed while compiling the plan")
    _owned(runtime.plan.case_root, [Path(binding["path"]) for binding in bindings])
    return bindings


def _validate_generate_rebuild_archive(
    static: Mapping[str, Any],
    live: Mapping[str, Any],
    before_files: Mapping[str, Mapping[str, Any]],
    after_files: Mapping[str, Mapping[str, Any]],
) -> None:
    spec = static["asset_spec"]
    seeds = spec["fixture_manifest"].get("rebuild_seeds")
    if seeds is None:
        return
    bindings = spec["request"]["path_bindings"]
    roots = live["root_bindings"]

    def seeded_path(binding: Mapping[str, Any], seed: Mapping[str, Any]) -> Path:
        root_key = str(binding["root_key"])
        if root_key not in roots:
            raise CliBusinessPlanError("generate rebuild root binding is absent")
        base = Path(roots[root_key]) / str(binding["relative_path"])
        path = (base / str(seed["relative_path"])).resolve(strict=False)
        _owned(Path(live["case_root"]), [path])
        return path

    cache_path = str(seeded_path(bindings["cache"], seeds["cache"]))
    header_path = str(seeded_path(bindings["root_output_path"], seeds["header"]))
    before_cache = before_files.get(cache_path)
    before_header = before_files.get(header_path)
    after_header = after_files.get(header_path)
    if before_cache is None or cache_path in after_files:
        raise CliBusinessPlanError("generate rebuild did not clear exact stale cache marker")
    if (
        before_header is None
        or after_header is None
        or after_header.get("size", 0) <= 0
        or before_header.get("sha256") == after_header.get("sha256")
    ):
        raise CliBusinessPlanError("generate rebuild did not replace exact stale header")
    header_paths = {
        path for path in after_files if Path(str(path)).name.casefold() == "wwise_ids.h"
    }
    if header_paths != {header_path}:
        raise CliBusinessPlanError("generate rebuild header inventory/location drifted")


def _derive_tab_source_bindings(
    asset_spec: Mapping[str, Any],
    input_proofs: Any,
) -> list[dict[str, str]]:
    if asset_spec.get("operation") != "tabDelimitedImport":
        return []
    if not isinstance(input_proofs, list):
        raise CliBusinessPlanError("CLI input proofs are invalid")
    proofs_by_relative: dict[str, Mapping[str, Any]] = {}
    for proof in input_proofs:
        if not isinstance(proof, Mapping):
            raise CliBusinessPlanError("CLI input proof shape is invalid")
        relative = str(proof.get("relative_path") or "")
        if relative in proofs_by_relative:
            raise CliBusinessPlanError("CLI input proof paths are duplicated")
        proofs_by_relative[relative] = proof
    files = asset_spec.get("assets", {}).get("wav", {}).get("files", [])
    if not isinstance(files, list):
        raise CliBusinessPlanError("tab WAV declaration is invalid")
    result: list[dict[str, str]] = []
    source_keys: set[str] = set()
    absolute_paths: set[str] = set()
    for row in files:
        if not isinstance(row, Mapping):
            raise CliBusinessPlanError("tab WAV declaration is invalid")
        source_key = str(row.get("key") or "")
        relative_path = f"wav/{row.get('name')}"
        proof = proofs_by_relative.get(relative_path)
        if (
            not source_key
            or source_key in source_keys
            or not isinstance(proof, Mapping)
            or not os.path.isabs(str(proof.get("path") or ""))
            or re.fullmatch(r"[0-9a-f]{64}", str(proof.get("sha256") or "")) is None
        ):
            raise CliBusinessPlanError("tab source binding is incomplete or ambiguous")
        path = str(proof["path"])
        if path in absolute_paths:
            raise CliBusinessPlanError("tab source binding reuses one WAV path")
        source_keys.add(source_key)
        absolute_paths.add(path)
        result.append(
            {
                "source_key": source_key,
                "path": path,
                "relative_path": relative_path,
                "sha256": str(proof["sha256"]),
            }
        )
    expected_keys = {
        str(row.get("source_key") or "")
        for row in asset_spec.get("expected", {}).get("objects", [])
        if isinstance(row, Mapping)
    }
    if expected_keys != source_keys:
        raise CliBusinessPlanError("tab source binding does not cover exact expected keys")
    return result


def _validate_tab_source_bindings(
    static: Mapping[str, Any],
    live: Mapping[str, Any],
) -> None:
    rows = live.get("tab_source_bindings")
    if not isinstance(rows, list):
        raise CliBusinessPlanError("tab source bindings are invalid")
    expected = _derive_tab_source_bindings(static["asset_spec"], live["input_proofs"])
    if rows != expected:
        raise CliBusinessPlanError("tab source bindings drifted from exact WAV proofs")
    if static["operation"] != "tabDelimitedImport" and rows:
        raise CliBusinessPlanError("non-tab CLI plan has tab source bindings")
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "source_key", "path", "relative_path", "sha256"
        }:
            raise CliBusinessPlanError("tab source binding schema is not closed")
    _owned(Path(live["case_root"]), [Path(row["path"]) for row in rows])


def _tab_source_binding_map(
    static: Mapping[str, Any],
    live: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    _validate_tab_source_bindings(static, live)
    return {str(row["source_key"]): row for row in live["tab_source_bindings"]}


def _rules(static: Mapping[str,Any], live: Mapping[str,Any]) -> list[dict[str,Any]]:
    return [{"kind":"cli.request_protocol_v1","request_sha256":static["operation_request_sha256"],"protocol_sha256":static["protocol_sha256"],"terminal_execute":static["terminal_execute"]},{"kind":"cli.immutable_inputs_v1","before_snapshot_sha256":live["before_snapshot_sha256"],"input_proofs_sha256":_hash(live["input_proofs"])},{"kind":"cli.expected_outputs_controls_v1","operation":static["operation"],"expected_outputs":static["expected_outputs"],"controls":static["control_output_paths"]},{"kind":"cli.migration_inventory_v1","operation":static["operation"],"before_inventory":live["before_snapshot"].get("migration_inventory"),"before_version":live["before_snapshot"].get("project_version")}]

def _sections(static,live,rules,primary,verification):
    return CliBusinessPlanSections(MappingProxyType({"kind":CLI_FIXTURE_KIND,"sha256":_hash({"static":static,"live":live})}),MappingProxyType({"primary_steps":list(primary),"verification_steps":list(verification)}),_ASSERTIONS,MappingProxyType(_plain(static)),MappingProxyType(_plain(live)),tuple(MappingProxyType(_plain(x)) for x in rules))

def _shape(s: CliBusinessPlanSections)->None:
    if not isinstance(s,CliBusinessPlanSections) or set(s.fixture_spec)!={"kind","sha256"} or set(s.payload_bindings)!={"primary_steps","verification_steps"} or tuple(s.assertion_ids)!=_ASSERTIONS: raise CliBusinessPlanError("CLI section shape is not closed")
    static={"family_schema_version","family","scenario_id","api","version","operation","asset_spec","asset_spec_sha256","operation_request","operation_request_sha256","request_provenance","lifecycle","expected_outputs","control_output_paths","protocol_sha256","terminal_execute"}; live={"family_schema_version","before_snapshot","before_snapshot_sha256","input_proofs","tab_source_bindings","root_bindings","visible_values","case_root"}
    if set(s.static_expectation)!=static or set(s.live_binding)!=live: raise CliBusinessPlanError("CLI static/live schema is not closed")

def _validate_proofs(rows:Any,*,verify_files:bool)->None:
    if not isinstance(rows,list): raise CliBusinessPlanError("CLI input proofs are invalid")
    for row in rows:
        if not isinstance(row,Mapping) or set(row)!={"path","relative_path","size","sha256","mtime_ns"} or not os.path.isabs(str(row.get("path")or"")) or type(row.get("size")) is not int or type(row.get("mtime_ns")) is not int or not isinstance(row.get("sha256"),str) or re.fullmatch(r"[0-9a-f]{64}",row["sha256"]) is None: raise CliBusinessPlanError("CLI input proof shape is invalid")
        if verify_files:
            p=Path(row["path"]); meta=os.lstat(p)
            if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode) or meta.st_size!=row["size"] or _file_hash(p)!=row["sha256"]: raise CliBusinessPlanError("CLI input proof changed")

def _validate_lifecycle_and_provenance(static: Mapping[str,Any])->None:
    op=static["operation"]; lifecycle=static["lifecycle"]; provenance=static["request_provenance"]; args=static["operation_request"]["arguments"]["args"]
    if not isinstance(lifecycle,Mapping) or set(lifecycle)!={"contract","setup_required","business_server_project","oracle_required","phase_order","residual_process_policy","business_disconnect_may_occur"}: raise CliBusinessPlanError("CLI lifecycle schema is not closed")
    setup=op in {"generateSoundbank","tabDelimitedImport"}; oracle=op in {"tabDelimitedImport","migrate"}; terminal=op=="migrate"
    if lifecycle.get("contract")!="waapi-skill.codex-cli-runtime/v3" or lifecycle.get("setup_required") is not setup or lifecycle.get("oracle_required") is not oracle or lifecycle.get("business_disconnect_may_occur") is not terminal or static["terminal_execute"] is not terminal: raise CliBusinessPlanError("CLI lifecycle operation properties drifted")
    if not isinstance(provenance,Mapping) or set(provenance)!={"/contract","/version","/operation","/arguments/api","/arguments/options","/arguments/io_root",*(f"/arguments/args/{key}" for key in args)}: raise CliBusinessPlanError("CLI request provenance is not closed to exact arguments")

def _owned(root:Path,paths:Sequence[Path])->None:
    root=Path(root).resolve(strict=False)
    for path in paths:
        resolved=Path(path).resolve(strict=False)
        if resolved!=root and root not in resolved.parents: raise CliBusinessPlanError("CLI path escapes scenario-owned root")

def _hash(value:Any)->str:return hashlib.sha256(json.dumps(_plain(value),ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _file_hash(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()
def _plain(v:Any)->Any:
    if v is None or type(v) in {str,int,float,bool}:return v
    if isinstance(v,Path):return str(v)
    if is_dataclass(v) and not isinstance(v,type):return {x.name:_plain(getattr(v,x.name)) for x in fields(v)}
    if isinstance(v,Mapping):return {str(k):_plain(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [_plain(x) for x in v]
    if isinstance(v,(set,frozenset)):return sorted((_plain(x) for x in v),key=lambda x:json.dumps(x,sort_keys=True,separators=(",",":")))
    raise CliBusinessPlanError(f"unserializable CLI value: {type(v).__name__}")

__all__=["CLI_BUSINESS_PLAN_SCHEMA","CLI_FIXTURE_KIND","CliBusinessPlanError","CliBusinessPlanSections","compile_cli_business_plan","validate_cli_business_plan","parse_cli_business_plan_sections","validate_cli_business_plan_archive","validate_cli_archived_verification","validate_cli_convert_archived_side_effects"]
