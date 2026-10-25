"""One public codec-selection/field workflow inside the existing owned sandbox."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid

from wwise_waapi.host_paths import localize_waapi_host_path
from wwise_waapi.native_catalog import load_native_catalog


PCM = "{D469C8FB-1FA9-4C2B-8250-3F8FFBCD1B40}"
PCM_PATH = "\\Conversion Settings\\Default Work Unit\\PCM"
SETTER = "ak.wwise.core.audio.setConversionPlugin"


def collect_conversion_plugin_acceptance(runtime):
    from tests.destructive.test_gateway_workflow_transaction_matrix import (
        _start_business_draft, _update_business_draft, _bind_business_object,
        _discover_business_type,
    )
    assert runtime.version in {"2024.1", "2025.1"}
    output = runtime.state_dir / "conversion-plugin-acceptance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists(), "Never overwrite original codec evidence"
    category = {"category": "conversion-plugin-placement", "status": "FAIL", "transaction_ids": [],
        "observation_path": str(output),
        "verifier_strength": "public_verification_plus_independent_platform_codec_class_owner_fields_and_preservation"}
    runtime.category_results.append(category)
    receipt = {"contract": "waapi-skill.conversion-plugin-acceptance/v1", "candidate": runtime.candidate,
        "version": runtime.version, "calls": [], "phases": [], "observations": {},
        "transaction_ids": category["transaction_ids"], "collection_complete": False,
        "business_effect_verified": False, "stage": "prewrite-native-shape",
        "scope": "one_existing_Conversion_in_private_SampleProject_copy_one_platform_one_scalar",
        "scope_exclusions": ["other_versions_and_hosts", "conversion_build", "audio_quality", "per_codec_or_value_QA",
                             "older_codec_replacement", "implicit_Project_target"],
        "limits": {"calls": 96, "receipt_bytes": 8 * 1024 * 1024, "reply_bytes": 1024 * 1024},
        "lifecycle_final_reference": {"contract": "waapi-skill.host-category-evidence/v3", "phase": "final",
            "candidate": runtime.candidate, "category": category["category"],
            "transaction_ids": category["transaction_ids"],
            "path": runtime.env.get("WWISE_CATEGORY_EVIDENCE_PATH") or runtime.env.get("WWISE_MACOS_CATEGORY_EVIDENCE_PATH"),
            "cleanup_status": "unresolved_until_final_row"}}
    attempted = set()

    def persist():
        raw = json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(raw) <= receipt["limits"]["receipt_bytes"], "Codec receipt exceeds its byte bound"
        temporary = output.with_suffix(".tmp"); temporary.write_bytes(raw); temporary.replace(output)
        category["observation_sha256"] = hashlib.sha256(raw).hexdigest()

    class Gateway:
        def gateway(self, argv, *, live):
            assert len(receipt["calls"]) < receipt["limits"]["calls"], "Codec public call bound exceeded"
            if argv[0] == "execute":
                assert argv[1] not in attempted, "Never retry a codec or field write"
                attempted.add(argv[1])
            row = {"argv": list(argv)}; receipt["calls"].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                row.update(exit_code=code, payload=payload)
                assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= receipt["limits"]["reply_bytes"]
                assert code == 0 and payload.get("ok") is True, payload
                if live:
                    assert payload.get("detected_version") == runtime.version and payload.get("endpoint") == endpoint, payload
                return payload
            finally:
                persist()
    endpoint = {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url}
    gateway = Gateway()
    projection = [arg for field in ("class-id", "owner", "plugin-name") for arg in ("--include", field)]

    def query(argv):
        result = gateway.gateway(["query-object", *argv], live=True)
        assert result.get("projection_complete") is not False and result.get("limit_reached") is not True, result
        rows = result.get("objects")
        assert isinstance(rows, list) and result.get("count") == len(rows) == 1, result
        assert uuid.UUID(rows[0]["id"]).int != 0
        return rows[0]

    def names(identity):
        values, page = [], None
        for _ in range(2):
            result = gateway.gateway(["metadata", "list", "--exact-id", identity, "--page-size", "64",
                *(["--page", page] if page else [])], live=True)["agent_result"]
            values.extend(row["name"] for row in result["fields"])
            if result["complete"] is True:
                assert len(values) == result["total_count"] == len(set(values)), result
                return sorted(values)
            page = result["next_page"]
        raise AssertionError("Codec metadata exceeds its bounded complete read")

    def codecs(platforms):
        observed = {}
        for platform in platforms:
            # This SDK-documented native source cannot be expressed by a closed
            # ordinary business kind. It observes codecs only; the mutation's
            # Conversion target is already independently pinned by exact ID.
            row = query(["--advanced-waql", f'from type ConversionPlugin where owner.id = "{PCM}"',
                "--max-results", "2", "--platform", platform["id"], *projection])
            assert row.get("type") == "ConversionPlugin", "Unexpected native anonymous codec type; stop before mutation"
            from wwise_waapi.business_declarations import normalize_live_object_identity
            normalize_live_object_identity(row, version=runtime.version)
            assert row.get("owner", {}).get("id") == PCM, row
            assert type(row.get("class_id")) is int and isinstance(row.get("plugin_name"), str), row
            fields = names(row["id"])
            values = {}
            for start in range(0, len(fields), 8):
                exact = query(["--exact-id", row["id"], "--max-results", "2", "--platform", platform["id"],
                    *projection, *(arg for name in fields[start:start + 8] for arg in ("--include-field", name))])
                assert all(exact.get(key) == row.get(key) for key in ("id", "name", "type", "path", "class_id", "owner", "plugin_name")), exact
                returned = exact.get("properties", {})
                assert set(returned) == set(fields[start:start + 8]), exact
                values.update(returned)
            observed[platform["id"]] = {"object": row, "fields": values}
        return observed

    def complete(draft, name):
        phase = {"name": name, "effect_verified": False}; receipt["phases"].append(phase)
        _update_business_draft(gateway, draft, "draft-check", live=True)
        preview = _update_business_draft(gateway, draft, "preview-from-draft", live=True)
        identity = preview["transaction_id"]; category["transaction_ids"].append(identity)
        phase.update(transaction_id=identity, artifact_hash=preview["artifact_hash"])
        shown = gateway.gateway(["transaction-show", identity], live=False)
        phase["immutable_preview"] = shown["artifact"]
        gateway.gateway(["confirm", identity, "--confirmation-token", shown["confirmation"]["token"]], live=False)
        phase["execute"] = gateway.gateway(["execute", identity], live=True)
        phase["verify"] = gateway.gateway(["verify", identity], live=True)
        assert phase["verify"]["state"] == "verified" and phase["verify"]["verification"]["business_state_verified"] is True
        return phase

    try:
        status = gateway.gateway(["status", "--detail"], live=True); receipt["initial_status"] = status
        project_info = status["agent_result"]["project"]
        catalog = load_native_catalog(runtime.version, "wwise-console")
        receipt["native_catalog"] = {"build": catalog["provenance"]["build"], "content_sha256": catalog["content_sha256"]}
        native = status["wwise"]["version"]
        assert ".".join(str(native[key]) for key in ("year", "major", "minor", "build")) == catalog["provenance"]["build"]
        project = Path(localize_waapi_host_path(project_info["path"])).resolve(strict=True)
        assert project == runtime.sandbox.sandbox_project.resolve(strict=True)
        assert project != runtime.sandbox.source_project.resolve(strict=True)
        owner = query(["--exact-id", PCM, "--include", "class-id", "--max-results", "2"])
        receipt["observations"]["owner_before"] = owner
        assert (owner["id"], owner["name"], owner["type"], owner["path"], owner.get("class_id")) == (PCM, "PCM", "Conversion", PCM_PATH, 3604496)
        # getProjectInfo's matching reflected schema explicitly owns this
        # reference. This is not an invented Project mutation target.
        default = project_info.get("defaultConversion")
        diagnostic = {"status": "unresolved", "project_reference": default}
        receipt["default_conversion_observation"] = diagnostic
        try:
            assert isinstance(default, dict) and uuid.UUID(default["id"]).int != 0
            actual_default = owner if default["id"] == PCM else query([
                "--exact-id", default["id"], "--include", "class-id", "--max-results", "2"])
            diagnostic["object"] = actual_default
            assert actual_default["id"] == default["id"] and actual_default["name"] == default["name"]
            assert actual_default["type"] == "Conversion" and actual_default["class_id"] == 3604496
            diagnostic.update(status="observed", uses_named_conversion_route=True,
                is_selected_conversion=actual_default["id"] == PCM)
        except (AssertionError, KeyError, TypeError, ValueError) as exc:
            diagnostic["failure"] = {"type": type(exc).__name__, "message": str(exc)[:1024]}
        platforms = [{"id": row["id"], "name": row["name"]} for row in project_info["platforms"]]
        assert 1 <= len(platforms) <= 64 and len({row["id"] for row in platforms}) == len(platforms)
        selected = [row for row in platforms if row["id"] == project_info["currentPlatformId"]]
        assert len(selected) == 1; selected = selected[0]
        before = codecs(platforms); receipt["observations"]["before"] = before
        assert before[selected["id"]]["object"]["plugin_name"] == "PCM" and before[selected["id"]]["object"]["class_id"] == 65537
        # Native anonymous identity and all preservation reads must work before
        # authorizing a write; unexpected shapes are a retained setup stop.
        receipt["prewrite_observation_complete"] = True
        draft = _start_business_draft(gateway, SETTER)
        handle = _bind_business_object(gateway, draft, object_id=PCM, role="conversion")
        kind = _discover_business_type(gateway, draft, meaning="Vorbis", role="conversion", expected_label="Vorbis")
        _update_business_draft(gateway, draft, "draft-declare-core-plan", ["--role", "conversion_handle", handle,
            "--value", "platform_name", selected["name"], "--type", "plugin_type_handle", kind], live=True)
        receipt["stage"] = "attachment"
        selection = complete(draft, "select_platform_codec")
        after = codecs(platforms); receipt["observations"]["after_selection"] = after
        codec = after[selected["id"]]["object"]
        assert codec["class_id"] == 262145 and codec["plugin_name"] == "Vorbis" and codec["owner"]["id"] == PCM
        assert all(after[key] == value for key, value in before.items() if key != selected["id"])
        selection["effect_verified"] = True
        draft = _start_business_draft(gateway, "object.setProperty")
        handle = _bind_business_object(gateway, draft, object_id=codec["id"])
        fields = _update_business_draft(gateway, draft, "draft-discover-fields", ["--object-handle", handle,
            "--platform", selected["name"], "--meaning", "quality"], live=True)
        choices = fields["field_candidates"]; assert len(choices) == 1 and choices[0]["label"] == "QualityFactor"
        _update_business_draft(gateway, draft, "draft-declare-field-change", ["--object-handle", handle,
            "--field-handle", choices[0]["handle"], "--business-value", "6"], live=False)
        receipt["stage"] = "field_configuration"
        field = complete(draft, "configure_codec_quality")
        final = codecs(platforms); receipt["observations"]["after_configuration"] = final
        assert final[selected["id"]]["object"] == codec
        expected = dict(after[selected["id"]]["fields"]); assert "QualityFactor" in expected
        expected["QualityFactor"] = 6.0
        assert final[selected["id"]]["fields"] == expected
        assert all(final[key] == value for key, value in before.items() if key != selected["id"])
        owner_after = query(["--exact-id", PCM, "--include", "class-id", "--max-results", "2"])
        receipt["observations"]["owner_after"] = owner_after
        assert owner_after == owner
        field["effect_verified"] = True
        receipt.update(collection_complete=True, business_effect_verified=True, stage="complete")
        category["status"] = "PASS"
        return category
    except Exception as exc:
        receipt["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        raise
    finally:
        persist()
