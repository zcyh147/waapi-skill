"""Bounded import witnesses using the existing owned workflow lifecycle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping
import uuid

from wwise_waapi.host_paths import localize_waapi_host_path


def _collect(runtime, *, localized):
    from tests.destructive.test_gateway_workflow_transaction_matrix import (
        _start_business_draft, _update_business_draft, _bind_business_object,
        _complete_business_draft, _write_fixture_wav, _save_sandbox_project, waapi_gateway,
    )
    if localized:
        assert runtime.version == "2025.1", "The source-GUID localized witness is pinned to 2025.1"
    name = "Import_Witness_" + uuid.uuid4().hex[:10]
    category_name = "audio-import-localized-notes-placement-event" if localized else "audio-import-mixed-replace-create"
    output = runtime.state_dir / (category_name + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists(), "Never overwrite original import observations"
    category = {"category": category_name, "status": "FAIL", "transaction_ids": [],
        "observation_path": str(output), "verifier_strength": "public_verification_plus_independent_identity_source_media_and_preservation"}
    runtime.category_results.append(category)
    receipt = {"contract": "waapi-skill.audio-import-acceptance/v1", "version": runtime.version,
        "candidate": runtime.candidate, "setup_coverage_credit": False, "stage": "setup", "business_effect_verified": False,
        "limits": {"calls": 128, "reply_bytes": 262144, "receipt_bytes": 2097152},
        "calls": [], "phases": [], "observations": {}, "inputs": {}, "failure": None}
    attempted = set()

    def persist():
        data = json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(data) <= receipt["limits"]["receipt_bytes"]
        temporary = output.with_suffix(".tmp"); temporary.write_bytes(data); temporary.replace(output)
        category["observation_sha256"] = hashlib.sha256(data).hexdigest()

    class Gateway:
        def raw_gateway(self, argv):
            assert len(receipt["calls"]) < receipt["limits"]["calls"]
            if argv[0] == "execute":
                assert argv[1] not in attempted, "Import execution is never retried"
                attempted.add(argv[1])
            row = {"argv": list(argv)}; receipt["calls"].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                row.update(exit_code=code, payload=payload)
                assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= receipt["limits"]["reply_bytes"]
                return code, payload
            finally:
                persist()

        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get("ok") is True, payload
            if live:
                assert payload["detected_version"] == runtime.version
                assert payload["endpoint"] == {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url}
            return payload
    gateway = Gateway()
    root = "Containers" if runtime.version == "2025.1" else "Actor-Mixer Hierarchy"

    def query(argv, *, includes=(), maximum=8):
        payload = gateway.gateway(["query-object", *argv,
            *(value for field in includes for value in ("--include", field)), "--max-results", str(maximum)], live=True)
        assert payload.get("projection_complete") is not False and payload.get("limit_reached") is not True, payload
        assert payload["count"] == len(payload["objects"]), payload
        return payload["objects"]

    def exact(identity, *, includes=()):
        rows = query(["--exact-id", identity], includes=includes, maximum=2)
        assert len(rows) == 1, rows
        return rows[0]

    def destroyed_old_id_rows(identity):
        # Reuse the owned-ControlInput collector's exact public failure binding;
        # no other query or failure in these witnesses receives normalization.
        code, payload = gateway.raw_gateway(["query-object", "--exact-id", identity, "--max-results", "2", "--detail"])
        assert payload.get("detected_version") == runtime.version, payload
        assert payload.get("endpoint") == {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url}, payload
        if code == 0:
            assert payload.get("ok") is True, payload
            rows = payload.get("objects")
            assert isinstance(rows, list) and len(rows) <= 1 and payload.get("count") == len(rows), payload
            assert payload.get("projection_complete") is not False and payload.get("limit_reached") is not True and payload.get("status") != "partial", payload
            return rows
        assert code == 2 and payload.get("ok") is False and payload.get("status") == "error", payload
        preview = payload["semantic_preview"]; call = payload["call"]
        args = {"waql": f'from object "{identity}" take 2'}
        assert preview["version"] == runtime.version and preview["envelope"]["uri"] == "ak.wwise.core.object.get", payload
        assert preview["envelope"]["args"] == args and payload["query_bound"] == {"mode": "take", "value": 2}, payload
        assert preview["envelope"]["options"] == {"return": ["id", "name", "type", "path"]}, payload
        assert call["api"] == "ak.wwise.core.object.get" and call["version"] == runtime.version, payload
        if call.get("waapi_error_uri") == "ak.wwise.query.invalid_query":
            details = call.get("waapi_error_details")
            assert isinstance(details, Mapping) and details.get("details") == {"procedureUri": call["api"]}, payload
        normalized = waapi_gateway.normalize_exact_object_absence(api=call["api"], args=args, result=call, exact_object_lookup=True)
        assert normalized.get("ok") is True and normalized.get("result") == {"return": []}, payload
        receipt["absence_normalization"] = normalized["normalization"]
        return []

    def path_id(*segments):
        rows = query([value for segment in segments for value in ("--path-segment", segment)], maximum=2)
        assert len(rows) == 1, rows
        return rows[0]["id"]

    owned_root = runtime.sandbox.sandbox_path.resolve(strict=True)
    def proof(raw_path):
        path = Path(localize_waapi_host_path(raw_path)).resolve(strict=True)
        assert path.is_relative_to(owned_root) and path.is_file() and not path.is_symlink(), path
        data = path.read_bytes(); assert 0 < len(data) <= 65536
        return {"path": str(path), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def sources(identity):
        rows = query(["--exact-id", identity, "--relationship", "children"],
            includes=("class-id", "parent", "source-language", "original-file-path", "notes"))
        assert rows and all(row["type"] == "AudioFileSource" and row["class_id"] == 16
            and row["parent"]["id"] == identity for row in rows), rows
        return [{"object": row, "media": proof(row["original_file_path"])} for row in rows]

    def complete(draft, phase_name, inspect=None):
        phase = {"name": phase_name, "effect_verified": False}; receipt["phases"].append(phase)
        def inspect_preview(preview):
            identity = preview["transaction_id"]; category["transaction_ids"].append(identity)
            phase.update(transaction_id=identity, artifact_hash=preview["artifact_hash"])
            shown = gateway.gateway(["transaction-show", identity], live=False)
            phase["compiled_native_request"] = shown["artifact"]["prepared_operation"]["dispatch"]
            if inspect:
                inspect(phase["compiled_native_request"])
        result = _complete_business_draft(gateway, draft, inspect_preview=inspect_preview)
        phase.update(execute=result["execute"], verify=result["verify"])
        return phase

    def audio(index, stem):
        path = _write_fixture_wav(owned_root / "GatewayImportWitness" / str(index), stem, frequency=330 + index * 110)
        receipt["inputs"][str(path)] = proof(str(path))
        return path

    try:
        if runtime.version == "2021.1":
            _save_sandbox_project(runtime)
        first, spare = audio(0, "Line" if localized else "Existing"), audio(1, "Spare")
        draft = _start_business_draft(gateway, "audio.import")
        parent = _bind_business_object(gateway, draft, path_segments=(root, "Default Work Unit"))
        _update_business_draft(gateway, draft, "draft-declare-import-batch", [
            "--row-order", "root", "existing", "spare",
            "--new-row", "root", parent, name, "actor-mixer",
            "--new-row", "existing", "root", "Voice" if localized else "Existing", "sound-voice" if localized else "sound-sfx",
            "--new-row", "spare", "root", "Spare", "sound-sfx",
            "--field", "existing", "media_file", str(first),
            "--field", "spare", "media_file", str(spare),
            *( ["--field", "existing", "language", "English(US)", "--field", "existing", "notes", "Keep owner notes",
                "--field", "existing", "audio_source_notes", "Before source notes", "--field", "existing", "originals_subfolder", "Before"] if localized else []),
        ], live=False)
        complete(draft, "setup")
        container = path_id(root, "Default Work Unit", name)
        existing = path_id(root, "Default Work Unit", name, "Voice" if localized else "Existing")
        spare_id = path_id(root, "Default Work Unit", name, "Spare")
        if localized:
            japanese_media = audio(2, "Line")
            draft = _start_business_draft(gateway, "audio.import")
            voice = _bind_business_object(gateway, draft, object_id=existing)
            _update_business_draft(gateway, draft, "draft-declare-existing", [
                "--declaration-id", "japanese", "--object-handle", voice,
                "--field", "media_file", str(japanese_media), "--field", "language", "Japanese",
                "--field", "originals_subfolder", "Other",
            ], live=False)
            complete(draft, "setup_other_language")
        spare_before = {"object": exact(spare_id, includes=("notes", "parent", "class-id")), "sources": sources(spare_id)}
        receipt["observations"]["before"] = {"existing": exact(existing, includes=("notes", "parent", "class-id")),
            "sources": sources(existing), "spare": spare_before}
        persist()
        if localized:
            before = receipt["observations"]["before"]
            by_language = {row["object"]["source_language"]["name"]: row for row in before["sources"]}
            assert len(before["sources"]) == len(by_language) == 2 and set(by_language) == {"English(US)", "Japanese"}
            requested_notes = "Requested literal Notes"
            media = audio(3, "Line")
            draft = _start_business_draft(gateway, "audio.import")
            voice = _bind_business_object(gateway, draft, object_id=existing)
            events = _bind_business_object(gateway, draft, path_segments=("Events", "Default Work Unit"))
            event_name = "Play_" + name
            _update_business_draft(gateway, draft, "draft-declare-existing", [
                "--declaration-id", "voice", "--object-handle", voice,
                "--field", "media_file", str(media), "--field", "language", "English(US)",
                "--field", "notes", requested_notes, "--field", "originals_subfolder", "After",
                "--event-parent-handle", events, "--event-name", event_name, "--event-action", "Play",
            ], live=False)
            receipt["stage"] = "witness"
            def inspect(dispatch):
                assert dispatch["uri"] == "ak.wwise.core.audio.import" and dispatch["args"]["importOperation"] == "useExisting"
                owner_row, row = dispatch["args"]["imports"]
                assert owner_row == {"objectPath": before["existing"]["path"], "event": "\\Events\\Default Work Unit\\" + event_name + "@Play"}
                assert "event" not in row and row["objectPath"] == ""
                assert row["notes"] == requested_notes and "audioSourceNotes" not in row
                assert row["importLocation"] == by_language["English(US)"]["object"]["id"]
                assert row["originalsSubFolder"] == "After"
            phase = complete(draft, "witness", inspect)
            after = {"owner": exact(existing, includes=("notes", "parent", "class-id")), "sources": sources(existing)}
            receipt["observations"]["after"] = after; persist()
            by_language_after = {row["object"]["source_language"]["name"]: row for row in after["sources"]}
            assert len(after["sources"]) == len(by_language_after) == 2 and set(by_language_after) == set(by_language)
            assert after["owner"] == before["existing"]
            selected = by_language_after["English(US)"]
            assert selected["object"]["id"] == by_language["English(US)"]["object"]["id"]
            assert selected["object"]["notes"] == requested_notes
            assert selected["media"]["sha256"] == receipt["inputs"][str(media)]["sha256"]
            assert Path(selected["media"]["path"]).parent.name == "After"
            assert selected["media"]["path"] != by_language["English(US)"]["media"]["path"]
            assert by_language_after["Japanese"] == by_language["Japanese"]
            event_id = path_id("Events", "Default Work Unit", event_name)
            actions = query(["--exact-id", event_id, "--relationship", "children"], includes=("action-type", "target", "parent"))
            after.update(event=exact(event_id), actions=actions); persist()
            assert len(actions) == 1 and actions[0]["type"] == "Action" and actions[0]["action_type"] == 1
            assert actions[0]["parent"]["id"] == event_id and actions[0]["target"]["id"] == existing
        else:
            replacement, new_media = audio(2, "Replacement"), audio(3, "New")
            draft = _start_business_draft(gateway, "audio.import")
            old_handle = _bind_business_object(gateway, draft, object_id=existing)
            parent = _bind_business_object(gateway, draft, object_id=container)
            _update_business_draft(gateway, draft, "draft-business-configure", ["--mode", "replace"], live=False)
            _update_business_draft(gateway, draft, "draft-declare-import-batch", [
                "--row-order", "existing", "new", "--existing-row", "existing", old_handle,
                "--new-row", "new", parent, "New", "sound-sfx",
                "--field", "existing", "media_file", str(replacement),
                "--field", "new", "media_file", str(new_media),
            ], live=False)
            receipt["stage"] = "witness"
            def inspect(dispatch):
                assert dispatch["uri"] == "ak.wwise.core.audio.import" and dispatch["args"]["importOperation"] == "replaceExisting"
                assert len(dispatch["args"]["imports"]) == 2
            phase = complete(draft, "witness", inspect)
            replacement_id = path_id(root, "Default Work Unit", name, "Existing")
            created_id = path_id(root, "Default Work Unit", name, "New")
            after = {"replacement": exact(replacement_id, includes=("parent", "class-id")),
                "created": exact(created_id, includes=("parent", "class-id")),
                "old_id_rows": destroyed_old_id_rows(existing),
                "replacement_sources": sources(replacement_id), "created_sources": sources(created_id)}
            receipt["observations"]["after"] = after; persist()
            assert replacement_id != existing and created_id not in {existing, replacement_id} and after["old_id_rows"] == []
            assert all(row["type"] == "Sound" and row["class_id"] == 65552 and row["parent"]["id"] == container
                for row in (after["replacement"], after["created"]))
            for identity, rows, media in ((replacement_id, after["replacement_sources"], replacement), (created_id, after["created_sources"], new_media)):
                assert len(rows) == 1 and rows[0]["object"]["parent"]["id"] == identity
                assert rows[0]["object"]["source_language"]["name"] == "SFX"
                assert rows[0]["media"]["sha256"] == receipt["inputs"][str(media)]["sha256"]
        spare_after = {"object": exact(spare_id, includes=("notes", "parent", "class-id")), "sources": sources(spare_id)}
        receipt["observations"]["spare_after"] = spare_after
        assert spare_after == spare_before
        assert all(proof(path) == expected for path, expected in receipt["inputs"].items())
        phase["effect_verified"] = True
        receipt.update(stage="complete", business_effect_verified=True)
        category["status"] = "PASS"
        return category
    except Exception as exc:
        receipt["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        raise
    finally:
        persist()


def collect_mixed_import_acceptance(runtime):
    return _collect(runtime, localized=False)


def collect_localized_import_acceptance(runtime):
    return _collect(runtime, localized=True)


def collect_localized_tsv_import_acceptance(runtime, *, witness_kind="notes-columns"):
    """One unchanged table, two independent Notes columns; preserve failed facts."""
    from tests.destructive.test_gateway_workflow_transaction_matrix import (
        _start_business_draft, _update_business_draft, _bind_business_object,
        _complete_business_draft, _write_fixture_wav,
    )
    assert runtime.version == "2025.1", "Representative unchanged-table witness is pinned to 2025.1"
    assert witness_kind in {"notes-columns", "ordinary-owner-source", "explicit-source-tsv"}
    ordinary = witness_kind == "ordinary-owner-source"
    name = "TSV_Witness_" + uuid.uuid4().hex[:10]
    output = runtime.state_dir / ("localized-exact-tsv-notes-witness.json" if witness_kind == "notes-columns" else "localized-" + witness_kind + "-witness.json")
    assert not output.exists(), "Never overwrite original native observations"
    category = {"category": "audio-import-localized-exact-tsv-notes" if witness_kind == "notes-columns" else "audio-import-localized-" + witness_kind, "status": "FAIL",
        "verifier_strength": "gateway_verifier_plus_independent_owner_source_notes_identity_media_and_preservation",
        "observation_path": str(output), "transaction_ids": []}
    runtime.category_results.append(category)
    report = {"contract": "waapi-skill.localized-tsv-witness/v1", "candidate": runtime.candidate,
        "version": runtime.version, "witness_kind": witness_kind, "setup_coverage_credit": False, "business_effect_verified": False,
        "transaction_budget": {"setup": 2, "witness": 1, "maximum_total": 3},
        "stage": "setup", "calls": [], "setup": [], "witness": {}, "rows": [],
        "observations": {}, "observation_errors": [], "inputs": {}, "failure": None,
        "limits": {"calls": 128, "reply_bytes": 262144, "receipt_bytes": 2097152},
        "lifecycle_acceptance": "Requires existing final host-category-evidence/v3 source-integrity and cleanup record"}
    attempted = set()
    def persist():
        body = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= report["limits"]["receipt_bytes"], "TSV witness receipt bound exceeded"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp"); temporary.write_bytes(body); temporary.replace(output)
        category["observation_sha256"] = hashlib.sha256(body).hexdigest()
    class Gateway:
        version, lifecycle, port = runtime.version, runtime.lifecycle, runtime.port
        def raw_gateway(self, argv):
            assert len(report["calls"]) < report["limits"]["calls"]
            if argv[0] == "execute":
                assert argv[1] not in attempted, "Never retry native witness execution"
                attempted.add(argv[1])
            call = {"argv": list(argv)}; report["calls"].append(call)
            try:
                code, payload = runtime.raw_gateway(argv)
                call.update(exit_code=code, payload=payload)
                assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= report["limits"]["reply_bytes"]
                return code, payload
            finally:
                persist()
        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get("ok") is True, payload
            if live:
                assert payload["detected_version"] == runtime.version
                assert payload["endpoint"] == {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url}
            return payload
    gateway = Gateway()
    owned = runtime.sandbox.sandbox_path.resolve(strict=True)
    def proof(raw):
        lexical = Path(localize_waapi_host_path(raw))
        assert not lexical.is_symlink(), lexical
        path = lexical.resolve(strict=True)
        assert path.is_relative_to(owned) and path.is_file(), path
        body = path.read_bytes(); assert 0 < len(body) <= 65536
        return {"path": str(path), "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    def query(argv, includes=(), fields=()):
        payload = gateway.gateway(["query-object", *argv,
            *(word for field in fields for word in ("--include-field", field)),
            *(word for field in includes for word in ("--include", field)), "--max-results", "8"], live=True)
        assert payload.get("projection_complete") is not False and payload.get("limit_reached") is not True and payload.get("status") != "partial", payload
        assert payload["count"] == len(payload["objects"]), payload
        return payload["objects"]
    def exact(identity):
        rows = query(["--exact-id", identity], ("notes", "parent", "class-id"),
            ("Volume", "OutputBus") if ordinary and identities.get("VoiceSource") == identity else ())
        assert len(rows) == 1 and rows[0]["id"] == identity and isinstance(rows[0].get("notes"), str), rows
        return rows[0]
    def at(*segments):
        rows = query([word for segment in segments for word in ("--path-segment", segment)])
        assert len(rows) == 1, rows
        return rows[0]["id"]
    def sources(identity):
        rows = query(["--exact-id", identity, "--relationship", "children"],
            ("class-id", "parent", "source-language", "original-file-path", "notes"))
        assert rows and all(row["type"] == "AudioFileSource" and row["class_id"] == 16
            and row["parent"]["id"] == identity and isinstance(row.get("notes"), str) for row in rows), rows
        return [{"object": row, "media": proof(row["original_file_path"])} for row in rows]
    def observe(identity, bucket):
        # Capture both independent facts even if one read is incomplete. Raw
        # bounded replies and actual failed verifier readbacks remain durable.
        for key, read in (("owner", lambda: exact(identity)), ("sources", lambda: sources(identity))):
            try: bucket[key] = read()
            except Exception as exc:
                report["observation_errors"].append({"identity": identity, "part": key, "type": type(exc).__name__, "message": str(exc)[:2048]})
            persist()
    def audio(index, stem):
        path = _write_fixture_wav(owned / "GatewayTSVWitness" / str(index), stem, frequency=330 + index * 110)
        report["inputs"][str(path)] = proof(str(path))
        return path
    def setup(draft, phase_name):
        phase = {"name": phase_name}; report["setup"].append(phase)
        def inspect(preview):
            category["transaction_ids"].append(preview["transaction_id"])
            phase["transaction_id"] = preview["transaction_id"]
        result = _complete_business_draft(gateway, draft, inspect_preview=inspect, phase_receipt=phase)
        phase.update(execute=result["execute"], verify=result["verify"]); persist()
    try:
        initial = {key: audio(index, stem) for index, (key, stem) in enumerate((
            ("VoiceNotes", "LineNotes"), ("VoiceSource", "LineSource"), ("Spare", "Spare")))}
        draft = _start_business_draft(gateway, "audio.import")
        parent = _bind_business_object(gateway, draft, path_segments=("Containers", "Default Work Unit"))
        args = ["--row-order", "root", "notes", "source", "spare", "--new-row", "root", parent, name, "actor-mixer"]
        for key, row, kind in (("VoiceNotes", "notes", "sound-voice"), ("VoiceSource", "source", "sound-voice"), ("Spare", "spare", "sound-sfx")):
            args.extend(["--new-row", row, "root", key, kind, "--field", row, "media_file", str(initial[key])])
            if kind == "sound-voice": args.extend(["--field", row, "language", "English(US)"])
        _update_business_draft(gateway, draft, "draft-declare-import-batch", args, live=False)
        setup(draft, "basic_english_and_spare")
        container = at("Containers", "Default Work Unit", name)
        identities = {key: at("Containers", "Default Work Unit", name, key) for key in initial}
        japanese = audio(3, "LineNotes")
        draft = _start_business_draft(gateway, "audio.import")
        voice = _bind_business_object(gateway, draft, object_id=identities["VoiceNotes"])
        _update_business_draft(gateway, draft, "draft-declare-existing", ["--declaration-id", "japanese", "--object-handle", voice,
            "--field", "media_file", str(japanese), "--field", "language", "Japanese"], live=False)
        setup(draft, "basic_japanese_media_only")
        before = report["observations"]["before"] = {}
        for key, identity in identities.items():
            before[key] = {}; observe(identity, before[key])
        assert not report["observation_errors"], report["observation_errors"]
        for key, languages in (("VoiceNotes", {"English(US)", "Japanese"}), ("VoiceSource", {"English(US)"})):
            by_language = {row["object"]["source_language"]["name"]: row for row in before[key]["sources"]}
            assert len(by_language) == len(before[key]["sources"]) and set(by_language) == languages, before[key]
            assert by_language["English(US)"]["media"]["sha256"] == report["inputs"][str(initial[key])]["sha256"]
            if "Japanese" in languages:
                assert by_language["Japanese"]["media"]["sha256"] == report["inputs"][str(japanese)]["sha256"]
            report["rows"].append({"name": key, "owner_id": identities[key],
                "baseline_owner_notes": before[key]["owner"]["notes"],
                "baseline_source_notes": {row["object"]["source_language"]["name"]: row["object"]["notes"] for row in before[key]["sources"]}})
        table = table_proof = None
        report["stage"] = "witness"
        if ordinary:
            import base64
            from tests.semantic.support.typed_gateway_input import discovered_business_field_handle
            replacement = {"VoiceSource": audio(4, "LineSource")}
            draft = _start_business_draft(gateway, "audio.import")
            voice = _bind_business_object(gateway, draft, object_id=identities["VoiceSource"])
            bus = _bind_business_object(gateway, draft, path_segments=("Master-Mixer Hierarchy", "Default Work Unit", "Master Audio Bus"))
            bus_id = at("Master-Mixer Hierarchy", "Default Work Unit", "Master Audio Bus")
            report["bus_before"] = exact(bus_id)
            fields = {}
            for meaning in ("Volume", "OutputBus"):
                found = _update_business_draft(gateway, draft, "draft-discover-fields",
                    ["--object-handle", voice, "--meaning", meaning], live=True)
                fields[meaning] = discovered_business_field_handle(found, meaning)
            inline = "Voices/Japanese/After/LineSource.wav|" + base64.b64encode(replacement["VoiceSource"].read_bytes()).decode("ascii")
            _update_business_draft(gateway, draft, "draft-declare-existing", ["--declaration-id", "japanese", "--object-handle", voice,
                "--field", "inline_wav", inline, "--field", "language", "Japanese",
                "--field", "audio_source_notes", "Japanese explicit Source notes", "--field", "originals_subfolder", "After",
                "--field-value", fields["Volume"], "-6", "--field-value", fields["OutputBus"], bus], live=False)
        else:
            replacement = ({"VoiceNotes": audio(4, "DifferentMedia")} if witness_kind == "explicit-source-tsv" else
                {key: audio(index + 4, stem) for index, (key, stem) in enumerate((("VoiceNotes", "LineNotes"), ("VoiceSource", "LineSource")))})
            table = owned / "GatewayTSVWitness/exact-localized.tsv"
            if witness_kind == "explicit-source-tsv":
                from wwise_waapi.platform_paths import adapt_cli_dispatch_paths
                shown_setup = gateway.gateway(["transaction-show", report["setup"][0]["transaction_id"]], live=False)
                media_path = str(replacement["VoiceNotes"].resolve(strict=True))
                media_uri = "ak.wwise.core.audio.importTabDelimited"
                adapted = adapt_cli_dispatch_paths(uri=media_uri, args={"importFile": media_path}, options={},
                    io_audit={"uri": media_uri, "paths": [{"section": "args", "json_path": "$.args.importFile",
                        "field": "importFile", "role": "read", "raw_path": media_path, "resolved_path": media_path}]},
                    project_guard=shown_setup["artifact"]["project_guard"])
                native_media_path = adapted.args["importFile"]
                assert proof(native_media_path) == report["inputs"][media_path]
                report["media_cell_path_adaptation"] = adapted.proof
                table.write_text("Audio File\tObject Path\tNotes\tOriginalsSubFolder\n"
                    + "\t<Sound Voice>VoiceNotes\tTSV requested object Notes\t\n"
                    + f"{native_media_path}\t<Sound Voice>VoiceNotes\\<AudioFileSource>LineNotes\tTSV requested source Notes\tAfter\n",
                    encoding="utf-8", newline="\n")
            else:
                table.write_text("Audio File\tObject Path\tNotes\tAudio Source Notes\tOriginalsSubFolder\n"
                    + "".join(f"{replacement[key]}\t<Sound Voice>{key}\t{notes}\t{source_notes}\tAfter\n"
                        for key, notes, source_notes in (("VoiceNotes", "TSV requested object Notes", ""), ("VoiceSource", "", "TSV requested source Notes"))),
                    encoding="utf-8", newline="\n")
            table_proof = proof(str(table)); report["table"] = {**table_proof, "utf8": table.read_text(encoding="utf-8")}
            draft = _start_business_draft(gateway, "audio.importTabDelimited")
            location = _bind_business_object(gateway, draft, role="import_location", object_id=container)
            _update_business_draft(gateway, draft, "draft-declare-artifact-plan", ["--table-file", str(table), "--location-handle", location,
                "--language", "English(US)", "--mode", "reimport"], live=False)
        _update_business_draft(gateway, draft, "draft-check", live=True)
        preview = _update_business_draft(gateway, draft, "preview-from-draft", live=True)
        witness = report["witness"]; transaction = preview["transaction_id"]
        category["transaction_ids"].append(transaction)
        witness.update(transaction_id=transaction, preview=preview)
        shown = gateway.gateway(["transaction-show", transaction], live=False)
        dispatch = shown["artifact"]["prepared_operation"]["dispatch"]; witness["compiled_native_request"] = dispatch
        if ordinary:
            assert dispatch["uri"] == "ak.wwise.core.audio.import" and dispatch["args"]["importOperation"] == "useExisting"
            owner_row, source_row = dispatch["args"]["imports"]
            assert owner_row["@Volume"] == -6 and owner_row["@OutputBus"] == bus_id
            assert "audioFileBase64" not in owner_row and "notes" not in owner_row
            assert source_row["objectPath"].endswith("\\<Sound Voice>VoiceSource\\<AudioFileSource>LineSource")
            assert source_row["notes"] == "Japanese explicit Source notes" and source_row["importLanguage"] == "Japanese"
            assert "importLocation" not in source_row and "audioSourceNotes" not in source_row
            assert source_row["audioFileBase64"] == inline.partition("|")[0].replace("/", "\\") + "|" + inline.partition("|")[2]
        else:
            assert dispatch["uri"] == "ak.wwise.core.audio.importTabDelimited"
            assert dispatch["args"] == {"importFile": str(table), "importLocation": container,
                "importLanguage": "English(US)", "importOperation": "useExisting", "autoAddToSourceControl": False, "autoCheckOutToSourceControl": False}
            assert proof(str(table)) == table_proof
        gateway.gateway(["confirm", transaction, "--confirmation-token", shown["confirmation"]["token"]], live=False)
        code, executed = gateway.raw_gateway(["execute", transaction]); witness.update(execute_exit_code=code, execute=executed); persist()
        if code != 0 or executed.get("state") != "executed_unverified":
            category["status"] = "blocked"
            raise AssertionError("Native TSV outcome is not determinate; no follow-up writes or reads")
        code, verified = gateway.raw_gateway(["verify", transaction]); witness.update(verify_exit_code=code, verify=verified); persist()
        if verified.get("state") == "indeterminate" or verified.get("status") == "indeterminate":
            category["status"] = "blocked"
            raise AssertionError("Verification is indeterminate; no follow-up calls")
        # Successful Verify stdout is compact; one public journal read retains
        # the original verifier's readbacks without repeating native Verify.
        saved_code, saved = gateway.raw_gateway(["transaction-show", transaction])
        witness["journal_exit_code"] = saved_code
        actual = [event["details"]["verification"] for event in saved.get("events", []) if event.get("event_type") == "verification_recorded"]
        if saved_code != 0:
            report["observation_errors"].append({"part": "verifier_journal", "message": "Public transaction evidence unavailable"})
        witness["actual_verifications"] = actual
        after = report["observations"]["after"] = {}
        for key, identity in identities.items():
            after[key] = {}; observe(identity, after[key])
        if ordinary:
            report["bus_after"] = exact(bus_id)
        else:
            report["table_after"] = proof(str(table))
        persist()
        assert not report["observation_errors"], report["observation_errors"]
        assert len(actual) == 1 and isinstance(actual[0].get("readbacks"), list), "Actual verifier readbacks missing"
        if not ordinary:
            assert report["table_after"] == table_proof
        assert all(proof(path) == original for path, original in report["inputs"].items())
        assert after["Spare"] == before["Spare"]
        if ordinary:
            assert after["VoiceNotes"] == before["VoiceNotes"] and report["bus_after"] == report["bus_before"]
            prior, current = before["VoiceSource"], after["VoiceSource"]
            old = {row["object"]["source_language"]["name"]: row for row in prior["sources"]}
            new = {row["object"]["source_language"]["name"]: row for row in current["sources"]}
            assert len(new) == len(current["sources"]) == 2 and set(new) == {"English(US)", "Japanese"}
            assert new["English(US)"] == old["English(US)"]
            selected = new["Japanese"]
            assert selected["object"]["id"] not in {identities["VoiceSource"], old["English(US)"]["object"]["id"]}
            assert selected["object"]["notes"] == "Japanese explicit Source notes"
            assert selected["media"]["sha256"] == report["inputs"][str(replacement["VoiceSource"])]["sha256"]
            assert Path(selected["media"]["path"]).parent.name == "After"
            assert {key: value for key, value in current["owner"].items() if key not in {"properties", "references"}} == {
                key: value for key, value in prior["owner"].items() if key not in {"properties", "references"}}
            assert current["owner"]["properties"]["Volume"] == -6
            assert current["owner"]["references"]["OutputBus"]["id"] == bus_id
        elif witness_kind == "explicit-source-tsv":
            assert after["VoiceSource"] == before["VoiceSource"]
            prior, current = before["VoiceNotes"], after["VoiceNotes"]
            old = {row["object"]["source_language"]["name"]: row for row in prior["sources"]}
            new = {row["object"]["source_language"]["name"]: row for row in current["sources"]}
            assert len(new) == len(current["sources"]) == 2 and set(new) == set(old)
            assert current["owner"] == {**prior["owner"], "notes": "TSV requested object Notes"}
            assert new["Japanese"] == old["Japanese"]
            for key in ("id", "name", "path", "parent", "class_id", "type", "source_language"):
                assert new["English(US)"]["object"][key] == old["English(US)"]["object"][key]
            assert new["English(US)"]["object"]["name"] == "LineNotes"
            assert new["English(US)"]["object"]["notes"] == "TSV requested source Notes"
            assert new["English(US)"]["media"]["sha256"] == report["inputs"][str(replacement["VoiceNotes"])]["sha256"]
            assert Path(new["English(US)"]["media"]["path"]).name == "DifferentMedia.wav"
            assert Path(new["English(US)"]["media"]["path"]).parent.name == "After"
        else:
            for key in ("VoiceNotes", "VoiceSource"):
                prior, current = before[key], after[key]
                old = {row["object"]["source_language"]["name"]: row for row in prior["sources"]}
                new = {row["object"]["source_language"]["name"]: row for row in current["sources"]}
                assert len(new) == len(current["sources"]) == len(old) == len(prior["sources"])
                assert set(new) == set(old)
                assert current["owner"] == {**prior["owner"], "notes": "TSV requested object Notes" if key == "VoiceNotes" else prior["owner"]["notes"]}
                assert new["English(US)"]["object"]["id"] == old["English(US)"]["object"]["id"]
                assert new["English(US)"]["object"]["notes"] == (old["English(US)"]["object"]["notes"] if key == "VoiceNotes" else "TSV requested source Notes")
                assert new["English(US)"]["media"]["sha256"] == report["inputs"][str(replacement[key])]["sha256"]
                assert Path(new["English(US)"]["media"]["path"]).parent.name == "After"
                assert new["English(US)"]["media"]["path"] != old["English(US)"]["media"]["path"]
                if "Japanese" in old: assert new["Japanese"] == old["Japanese"]
        assert code == 0 and verified.get("verified") is True, verified
        report.update(stage="complete", business_effect_verified=True); category["status"] = "PASS"
        return category
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        raise
    finally:
        persist()


def collect_localized_owner_source_import_acceptance(runtime):
    return collect_localized_tsv_import_acceptance(runtime, witness_kind="ordinary-owner-source")


def collect_localized_explicit_source_tsv_acceptance(runtime):
    return collect_localized_tsv_import_acceptance(runtime, witness_kind="explicit-source-tsv")
