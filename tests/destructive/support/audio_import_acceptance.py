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
    assert witness_kind in {"notes-columns", "ordinary-owner-source", "explicit-source-tsv", "guid-source-tsv", "owner-fields-tsv", "owner-fields-media-tsv", "distinct-owner-fields-media-tsv"}
    distinct_sources = witness_kind == "distinct-owner-fields-media-tsv"
    combined_owner_media = witness_kind in {"owner-fields-media-tsv", "distinct-owner-fields-media-tsv"}
    owner_fields = witness_kind in {"owner-fields-tsv", "owner-fields-media-tsv", "distinct-owner-fields-media-tsv"}
    explicit_source_table = witness_kind in {"explicit-source-tsv", "guid-source-tsv"}
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
            ("Volume", "OutputBus", "OverrideOutput") if (ordinary or owner_fields) and identities.get("VoiceNotes" if owner_fields else "VoiceSource") == identity else ())
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
        # A valid typed Source wire path must be unique across languages.
        # Preserve the old failed roots; only this future path-based fixture
        # gives the unrelated Japanese Source a distinct filename/name.
        japanese = audio(3, "OtherLineNotes" if witness_kind == "explicit-source-tsv" or distinct_sources else "LineNotes")
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
                if distinct_sources:
                    english, other = by_language["English(US)"]["object"], by_language["Japanese"]["object"]
                    assert english["name"] == "LineNotes" and other["name"] == "OtherLineNotes"
                    assert english["path"] != other["path"] and english["id"] != other["id"]
                    report["distinct_source_configuration"] = {"English(US)": english, "Japanese": other}
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
            # This 2025.1 witness uses the exact Main Audio Bus from the
            # committed SampleProject and retained public baseline reply.
            # Other valid direct Buses belong to unrelated workflow fixtures.
            bus_root = "Busses" if runtime.version == "2025.1" else "Master-Mixer Hierarchy"
            bus_work_unit = at(bus_root, "Default Work Unit")
            buses = query(["--exact-id", bus_work_unit, "--relationship", "children"], ("parent",))
            bus_id = "{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}"
            selected = [row for row in buses if row["id"] == bus_id]
            expected_bus = {"id": bus_id, "name": "Main Audio Bus", "type": "Bus",
                "path": "\\".join(("", bus_root, "Default Work Unit", "Main Audio Bus"))}
            assert len(selected) == 1 and all(selected[0].get(key) == value for key, value in expected_bus.items()), buses
            assert selected[0]["parent"]["id"] == bus_work_unit, selected
            report["bus_before"] = exact(bus_id)
            assert all(report["bus_before"].get(key) == value for key, value in expected_bus.items()), report["bus_before"]
            assert report["bus_before"]["parent"]["id"] == bus_work_unit
            bus = _bind_business_object(gateway, draft, object_id=bus_id)
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
            replacement = ({"VoiceNotes": audio(4, "LineNotes")} if combined_owner_media else {} if owner_fields else {"VoiceNotes": audio(4, "DifferentMedia")} if explicit_source_table else
                {key: audio(index + 4, stem) for index, (key, stem) in enumerate((("VoiceNotes", "LineNotes"), ("VoiceSource", "LineSource")))})
            table = owned / "GatewayTSVWitness/exact-localized.tsv"
            if explicit_source_table or combined_owner_media:
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
            if owner_fields:
                bus_work_unit = at("Busses", "Default Work Unit")
                report["buses_before"] = {}
                # Both exact Work Unit elements are Bus, not AuxBus. The
                # pinned 2025.1.7 getTypes catalog binds Bus to 1376272;
                # 524304 belongs to PropertyContainer, not a Bus subclass.
                for label, identity, bus_name, class_id in (
                    ("Main", "{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}", "Main Audio Bus", 1376272),
                    ("Secondary", "{D2E0BC7E-7B3F-4FFE-A670-FAE02761B631}", "Secondary Bus", 1376272),
                ):
                    bus = exact(identity)
                    expected = {"id": identity, "name": bus_name, "type": "Bus", "class_id": class_id,
                        "path": "\\Busses\\Default Work Unit\\" + bus_name}
                    assert all(bus.get(key) == value for key, value in expected.items()) and bus["parent"]["id"] == bus_work_unit, bus
                    report["buses_before"][label] = bus
                secondary_id = report["buses_before"]["Secondary"]["id"]
                assert before["VoiceNotes"]["owner"]["references"]["OutputBus"]["id"] == report["buses_before"]["Main"]["id"] != secondary_id
                assert before["VoiceNotes"]["owner"]["properties"] == {"Volume": 0.0, "OverrideOutput": False}
                header = "Object Path\tProperty[Volume]\tProperty[OverrideOutput]\tReference[OutputBus]\n"
                cells = f"<Sound Voice>VoiceNotes\t-6\ttrue\t{secondary_id}\n"
                table.write_text(("Audio File\t" + header + native_media_path + "\t" + cells if combined_owner_media else header + cells),
                    encoding="utf-8", newline="\n")
            elif explicit_source_table:
                if witness_kind == "guid-source-tsv":
                    source, = [row["object"] for row in before["VoiceNotes"]["sources"]
                        if row["object"]["source_language"]["name"] == "English(US)"]
                    assert source["type"] == "AudioFileSource" and source["class_id"] == 16
                    report["guid_target_bindings"] = {"owner": before["VoiceNotes"]["owner"], "source": source}
                    # The primary GUID example supplies Object Type explicitly.
                    # Copy the existing Source's native class name, never infer
                    # a Sound type from this replacement WAV's different stem.
                    table.write_text("Audio File\tObject Path\tObject Type\tNotes\tOriginalsSubFolder\n"
                        + f"\t{identities['VoiceNotes']}\tSound Voice\tTSV requested object Notes\t\n"
                        + f"{native_media_path}\t{source['id']}\t{source['type']}\tTSV requested source Notes\tAfter\n",
                        encoding="utf-8", newline="\n")
                else:
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
        if distinct_sources:
            host = shown["artifact"]["project_guard"]["wwise"]
            assert host["isCommandLine"] is True and all(host["version"].get(key) == value
                for key, value in (("year", 2025), ("major", 1), ("minor", 7), ("build", 9143))), host
            report["selected_console_host"] = host
        dispatch = shown["artifact"]["prepared_operation"]["dispatch"]; witness["compiled_native_request"] = dispatch
        if ordinary:
            assert dispatch["uri"] == "ak.wwise.core.audio.import" and dispatch["args"]["importOperation"] == "useExisting"
            owner_row, source_row = dispatch["args"]["imports"]
            assert owner_row["@Volume"] == -6 and owner_row["@OutputBus"] == bus_id
            assert owner_row["@OverrideOutput"] is True and "@OverrideOutput" not in source_row
            assert "audioFileBase64" not in owner_row and "notes" not in owner_row
            assert source_row["objectPath"].endswith("\\<Sound Voice>VoiceSource\\<AudioFileSource>LineSource__" + hashlib.sha256(b"Japanese").hexdigest()[:12])
            assert source_row["notes"] == "Japanese explicit Source notes" and source_row["importLanguage"] == "Japanese"
            assert "importLocation" not in source_row and "audioSourceNotes" not in source_row
            assert source_row["audioFileBase64"] == inline.partition("|")[0].replace("/", "\\") + "|" + inline.partition("|")[2]
            assert source_row["originalsSubFolder"] == "After"
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
            if owner_fields:
                report["buses_after"] = {label: exact(bus["id"]) for label, bus in report["buses_before"].items()}
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
            assert Path(selected["media"]["path"]).relative_to(owned) == Path("Originals/Voices/Japanese/After/LineSource.wav")
            assert {key: value for key, value in current["owner"].items() if key not in {"properties", "references"}} == {
                key: value for key, value in prior["owner"].items() if key not in {"properties", "references"}}
            assert current["owner"]["properties"]["Volume"] == -6
            assert current["owner"]["properties"]["OverrideOutput"] is True
            assert current["owner"]["references"]["OutputBus"]["id"] == bus_id
        elif owner_fields:
            assert after["VoiceSource"] == before["VoiceSource"]
            if combined_owner_media:
                old = {row["object"]["source_language"]["name"]: row for row in before["VoiceNotes"]["sources"]}
                new = {row["object"]["source_language"]["name"]: row for row in after["VoiceNotes"]["sources"]}
                assert len(new) == len(after["VoiceNotes"]["sources"]) == len(old) == 2 and set(new) == set(old) == {"English(US)", "Japanese"}
                assert new["Japanese"] == old["Japanese"]
                assert new["English(US)"]["object"] == old["English(US)"]["object"]
                assert new["English(US)"]["media"]["path"] == old["English(US)"]["media"]["path"]
                assert new["English(US)"]["object"]["name"] == Path(new["English(US)"]["media"]["path"]).stem == "LineNotes"
                assert new["English(US)"]["media"]["sha256"] == report["inputs"][str(replacement["VoiceNotes"])]["sha256"] != old["English(US)"]["media"]["sha256"]
            else:
                assert after["VoiceNotes"]["sources"] == before["VoiceNotes"]["sources"]
            assert report["buses_after"] == report["buses_before"]
            prior, current = before["VoiceNotes"]["owner"], after["VoiceNotes"]["owner"]
            assert {key: value for key, value in current.items() if key not in {"properties", "references"}} == {
                key: value for key, value in prior.items() if key not in {"properties", "references"}}
            assert current["properties"] == {"Volume": -6, "OverrideOutput": True}
            assert current["references"]["OutputBus"]["id"] == secondary_id
        elif explicit_source_table:
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


def collect_localized_guid_source_tsv_acceptance(runtime):
    return collect_localized_tsv_import_acceptance(runtime, witness_kind="guid-source-tsv")


def collect_localized_owner_fields_tsv_acceptance(runtime):
    return collect_localized_tsv_import_acceptance(runtime, witness_kind="owner-fields-tsv")


def collect_localized_combined_owner_media_tsv_acceptance(runtime):
    return collect_localized_tsv_import_acceptance(runtime, witness_kind="owner-fields-media-tsv")


def collect_localized_distinct_source_tsv_acceptance(runtime):
    return collect_localized_tsv_import_acceptance(runtime, witness_kind="distinct-owner-fields-media-tsv")


def collect_switch_import_acceptance(runtime, *, tab_delimited=False):
    """Two imports under the sandbox's source-backed nonempty Switch graph."""
    from tests.destructive.test_gateway_workflow_transaction_matrix import (
        _start_business_draft, _update_business_draft, _bind_business_object,
        _complete_business_draft, _write_fixture_wav,
    )
    assert runtime.version == "2025.1", "This representative Switch witness is pinned to 2025.1"
    output = runtime.state_dir / ("switch-columns-tsv-witness.json" if tab_delimited else "switch-import-witness.json")
    assert not output.exists(), "Never overwrite original Switch observations"
    category = {"category": "audio-import-switch-columns-tsv" if tab_delimited else "audio-import-switch-owner-media", "status": "FAIL", "transaction_ids": [],
        "verifier_strength": "public_verifier_plus_exact_group_pairs_source_media_and_subtree_preservation",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    report = {"contract": "waapi-skill.switch-import-witness/v1", "candidate": runtime.candidate,
        "version": runtime.version, "setup_coverage_credit": False, "business_effect_verified": False,
        "transaction_budget": {"setup": 1, "witness": 1, "maximum_total": 2}, "stage": "baseline",
        "calls": [], "setup": {}, "witness": {}, "observations": {}, "inputs": {}, "failure": None,
        "limits": {"calls": 96, "reply_bytes": 262144, "receipt_bytes": 2097152},
        "lifecycle_acceptance": "Requires existing final host-category-evidence/v3 source-integrity and cleanup record"}
    attempted = set()

    def persist():
        body = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= report["limits"]["receipt_bytes"], "Switch witness receipt bound exceeded"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp"); temporary.write_bytes(body); temporary.replace(output)
        category["observation_sha256"] = hashlib.sha256(body).hexdigest()

    class Gateway:
        version, lifecycle, port = runtime.version, runtime.lifecycle, runtime.port
        def raw_gateway(self, argv):
            assert len(report["calls"]) < report["limits"]["calls"]
            if argv[0] == "execute":
                assert argv[1] not in attempted, "Never retry Switch import execution"
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
                assert payload["detected_version"] == runtime.version, payload
                assert payload["endpoint"] == {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url}, payload
            return payload
    gateway = Gateway()
    owned = runtime.sandbox.sandbox_path.resolve(strict=True)

    def proof(raw):
        lexical = Path(localize_waapi_host_path(raw)); assert not lexical.is_symlink(), lexical
        path = lexical.resolve(strict=True)
        assert path.is_relative_to(owned) and path.is_file(), path
        body = path.read_bytes(); assert 0 < len(body) <= 65536
        return {"path": str(path), "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}

    def query(argv, *, fields=(), maximum=64):
        payload = gateway.gateway(["query-object", *argv, "--include", "notes", "--include", "parent", "--include", "class-id",
            *(word for field in fields for word in ("--include-field", field)), "--max-results", str(maximum)], live=True)
        assert payload.get("projection_complete") is not False and payload.get("limit_reached") is not True and payload.get("status") != "partial", payload
        rows = payload["objects"]; assert payload["count"] == len(rows) and len(rows) <= maximum, payload
        return rows

    def exact(identity, *, fields=()):
        rows = query(["--exact-id", identity], fields=fields, maximum=2)
        assert len(rows) == 1 and rows[0]["id"] == identity and isinstance(rows[0].get("notes"), str), rows
        return rows[0]

    def pairs(identity):
        payload = gateway.gateway(["core-call", "ak.wwise.core.switchContainer.getAssignments", "--object-id", identity], live=True)
        rows = payload["agent_result"]["return"]
        assert isinstance(rows, list) and len(rows) <= 64, payload
        result = []
        for row in rows:
            child, value = row["child"], row["stateOrSwitch"]
            child = child["id"] if isinstance(child, Mapping) else child
            value = value["id"] if isinstance(value, Mapping) else value
            assert uuid.UUID(child).int and uuid.UUID(value).int, row
            result.append({"child": child.upper(), "stateOrSwitch": value.upper()})
        assert len({(row["child"], row["stateOrSwitch"]) for row in result}) == len(result), result
        return sorted(result, key=lambda row: (row["child"], row["stateOrSwitch"]))

    def subtree(identity):
        payload = gateway.gateway(["query-object", "--exact-id", identity, "--relationship", "descendants",
            "--include", "notes", "--include", "parent", "--include", "class-id", "--include", "source-language",
            "--include", "original-file-path", "--max-results", "64"], live=True)
        assert payload.get("projection_complete") is not False and payload.get("limit_reached") is not True and payload.get("status") != "partial", payload
        rows = payload["objects"]; assert payload["count"] == len(rows) <= 64, payload
        result = {}
        for row in rows:
            assert row["id"] not in result, row
            result[row["id"]] = {"object": row}
            if row["type"] == "AudioFileSource":
                assert row["class_id"] == 16 and row["source_language"]["name"] == "SFX", row
                result[row["id"]]["media"] = proof(row["original_file_path"])
        return result

    def audio(index, stem):
        path = _write_fixture_wav(owned / "GatewaySwitchWitness" / str(index), stem, frequency=330 + index * 110)
        report["inputs"][str(path)] = proof(str(path))
        return path

    try:
        # Exact identities/classes from the pinned SampleProject and catalog.
        container_id = "{72A207A3-DA06-4467-8E18-3FDAB77DC66B}"
        group_id = "{4F5CED25-BA00-4C46-88AB-CE2CFBEFDD2D}"
        value_id = "{8E435F66-9998-4396-8BBC-1BEAF62FD304}"
        container = exact(container_id, fields=("SwitchGroupOrStateGroup",))
        assert (container["name"], container["type"], container["class_id"], container["path"], container["parent"]["id"]) == (
            "Player_Footsteps", "SwitchContainer", 655376, r"\Containers\Default Work Unit\WAAPI Skill Integration V2\PlayerFootstepsMaintenance\Player_Footsteps", "{8570736F-FDCF-4C43-AF64-C99A25B16722}"), container
        assert container["references"]["SwitchGroupOrStateGroup"]["id"] == group_id, container
        group = exact(group_id)
        assert (group["name"], group["type"], group["class_id"], group["path"], group["parent"]["id"]) == (
            "WAAPI_V2_Surface", "SwitchGroup", 1245200, r"\Switches\Default Work Unit\WAAPI_V2_Surface", "{943EAFED-3A2C-4325-9F3C-E4CD8AEE33DC}"), group
        value = exact(value_id)
        assert (value["name"], value["type"], value["class_id"], value["path"], value["parent"]["id"]) == (
            "Snow", "Switch", 1310736, group["path"] + r"\Snow", group_id), value
        values = sorted(query(["--exact-id", group_id, "--relationship", "children"]), key=lambda row: row["id"])
        metal_id = "{D457E7BF-4C4D-41A9-93F9-C127198EC739}"
        if tab_delimited:
            metal = exact(metal_id)
            assert (metal["name"], metal["type"], metal["class_id"], metal["path"], metal["parent"]["id"]) == (
                "Metal", "Switch", 1310736, group["path"] + r"\Metal", group_id), metal
            assert all(any(row["id"] == identity for row in values) for identity in (value_id, metal_id)), values
        baseline = report["observations"]["baseline"] = {"container": container, "group": group, "values": values,
            "pairs": pairs(container_id), "subtree": subtree(container_id)}
        assert baseline["pairs"] and all(row["stateOrSwitch"] != value_id for row in baseline["pairs"]), baseline["pairs"]
        assert all(row["child"] in baseline["subtree"] for row in baseline["pairs"]), baseline["pairs"]
        assert any("media" in row for row in baseline["subtree"].values()), "Nonempty original media baseline required"
        suffix = uuid.uuid4().hex[:10]
        existing_name, spare_name, new_name = ("ImportSwitch_" + suffix + tail for tail in ("Existing", "Spare", "New"))
        first, spare = audio(0, existing_name), audio(1, spare_name)
        draft = _start_business_draft(gateway, "audio.import")
        parent = _bind_business_object(gateway, draft, object_id=container_id)
        _update_business_draft(gateway, draft, "draft-declare-import-batch", ["--row-order", "existing", "spare",
            "--new-row", "existing", parent, existing_name, "sound-sfx", "--field", "existing", "media_file", str(first),
            "--new-row", "spare", parent, spare_name, "sound-sfx", "--field", "spare", "media_file", str(spare)], live=False)
        def inspect_setup(preview):
            category["transaction_ids"].append(preview["transaction_id"])
        _complete_business_draft(gateway, draft, inspect_preview=inspect_setup, phase_receipt=report["setup"])
        before = report["observations"]["before"] = subtree(container_id)
        assert all(before[identity] == row for identity, row in baseline["subtree"].items())
        existing, = [row["object"] for row in before.values() if row["object"]["name"] == existing_name and row["object"]["parent"]["id"] == container_id]
        spare_owner, = [row["object"] for row in before.values() if row["object"]["name"] == spare_name and row["object"]["parent"]["id"] == container_id]
        old_source, = [row for row in before.values() if row["object"]["type"] == "AudioFileSource" and row["object"]["parent"]["id"] == existing["id"]]
        spare_ids = {spare_owner["id"], *(identity for identity, row in before.items() if row["object"]["parent"]["id"] == spare_owner["id"])}
        assert len(before) == len(baseline["subtree"]) + 4 and len(spare_ids) == 2, before
        assert old_source["media"]["sha256"] == report["inputs"][str(first)]["sha256"]
        assert pairs(container_id) == baseline["pairs"]
        created = audio(3, new_name)
        table = table_proof = None
        if tab_delimited:
            from wwise_waapi.platform_paths import adapt_cli_dispatch_paths
            shown_setup = gateway.gateway(["transaction-show", report["setup"]["transaction_id"]], live=False)
            media_path = str(created.resolve(strict=True))
            uri = "ak.wwise.core.audio.importTabDelimited"
            adapted = adapt_cli_dispatch_paths(uri=uri, args={"importFile": media_path}, options={},
                io_audit={"uri": uri, "paths": [{"section": "args", "json_path": "$.args.importFile",
                    "field": "importFile", "role": "read", "raw_path": media_path, "resolved_path": media_path}]},
                project_guard=shown_setup["artifact"]["project_guard"])
            native_media_path = adapted.args["importFile"]
            assert proof(native_media_path) == report["inputs"][media_path]
            report["media_cell_path_adaptation"] = adapted.proof
            table = owned / "GatewaySwitchWitness/repeated-switch.tsv"
            table.write_text("Object Path\tAudio File\tSwitch Assignation\tSwitch Assignation\n"
                + f"<Sound SFX>{new_name}\t{native_media_path}\t<Switch Group:WAAPI_V2_Surface>Snow\t<Switch Group:WAAPI_V2_Surface>Metal\n",
                encoding="utf-8", newline="\n")
            table_proof = proof(str(table))
            report["table"] = {**table_proof, "utf8": table.read_text(encoding="utf-8")}
            draft = _start_business_draft(gateway, "audio.importTabDelimited")
            parent = _bind_business_object(gateway, draft, role="import_location", object_id=container_id)
            _update_business_draft(gateway, draft, "draft-declare-artifact-plan", ["--table-file", str(table),
                "--location-handle", parent, "--language", "SFX", "--mode", "reimport"], live=False)
        else:
            replacement = audio(2, existing_name)
            draft = _start_business_draft(gateway, "audio.import")
            owner = _bind_business_object(gateway, draft, object_id=existing["id"])
            parent = _bind_business_object(gateway, draft, object_id=container_id)
            _update_business_draft(gateway, draft, "draft-declare-import-batch", ["--row-order", "existing", "new",
                "--existing-row", "existing", owner, "--field", "existing", "media_file", str(replacement), "--switch-value", "existing", "Snow",
                "--new-row", "new", parent, new_name, "sound-sfx", "--field", "new", "media_file", str(created), "--switch-value", "new", "Snow"], live=False)
        report["stage"] = "witness"
        _update_business_draft(gateway, draft, "draft-check", live=True)
        preview = _update_business_draft(gateway, draft, "preview-from-draft", live=True)
        witness = report["witness"]; transaction = preview["transaction_id"]
        witness.update(transaction_id=transaction, preview=preview); category["transaction_ids"].append(transaction)
        shown = gateway.gateway(["transaction-show", transaction], live=False)
        dispatch = witness["compiled_native_request"] = shown["artifact"]["prepared_operation"]["dispatch"]
        if tab_delimited:
            assert dispatch["uri"] == "ak.wwise.core.audio.importTabDelimited", dispatch
            assert dispatch["args"]["importOperation"] == "useExisting" and dispatch["args"]["importFile"] == str(table), dispatch
            assert "imports" not in dispatch["args"] and proof(str(table)) == table_proof, dispatch
            target, = shown["artifact"]["prepared_operation"]["verification_plan"]["targets"]
            assert target["switch_assignment_binding"]["value_ids"] == [value_id, metal_id], target
        else:
            assert dispatch["uri"] == "ak.wwise.core.audio.import" and dispatch["args"]["importOperation"] == "useExisting", dispatch
            rows = dispatch["args"]["imports"]
            owner_row, = [row for row in rows if row.get("switchAssignation") and existing_name in row["objectPath"]]
            assert owner_row == {"objectPath": existing["path"], "objectType": "Sound SFX",
                "switchAssignation": "<Switch Group:WAAPI_V2_Surface>Snow"}, owner_row
            assert owner_row["switchAssignation"] == "<Switch Group:WAAPI_V2_Surface>Snow"
            media_row, = [row for row in rows if row.get("importLocation") == old_source["object"]["id"]]
            assert media_row["objectPath"] == "" and "switchAssignation" not in media_row and media_row["audioFile"] == str(replacement), media_row
            assert sum("switchAssignation" in row for row in rows) == 2 and len(rows) <= 4, rows
        gateway.gateway(["confirm", transaction, "--confirmation-token", shown["confirmation"]["token"]], live=False)
        code, executed = gateway.raw_gateway(["execute", transaction]); witness.update(execute_exit_code=code, execute=executed); persist()
        if code != 0 or executed.get("state") != "executed_unverified":
            category["status"] = "blocked"
            raise AssertionError("Switch import outcome is indeterminate; no follow-up calls")
        code, verified = gateway.raw_gateway(["verify", transaction]); witness.update(verify_exit_code=code, verify=verified); persist()
        if verified.get("state") == "indeterminate" or verified.get("status") == "indeterminate":
            category["status"] = "blocked"
            raise AssertionError("Switch import verification is indeterminate; no follow-up calls")
        saved = gateway.gateway(["transaction-show", transaction], live=False)
        witness["actual_verifications"] = [event["details"]["verification"] for event in saved.get("events", []) if event.get("event_type") == "verification_recorded"]
        after = report["observations"]["after"] = {"subtree": subtree(container_id), "pairs": pairs(container_id),
            "container": exact(container_id, fields=("SwitchGroupOrStateGroup",)), "group": exact(group_id),
            "values": sorted(query(["--exact-id", group_id, "--relationship", "children"]), key=lambda row: row["id"])}
        persist()
        assert all(after[key] == baseline[key] for key in ("container", "group", "values")), after
        assert all(after["subtree"][identity] == row for identity, row in baseline["subtree"].items())
        assert all(after["subtree"][identity] == before[identity] for identity in spare_ids)
        if tab_delimited:
            assert all(after["subtree"][identity] == row for identity, row in before.items()), after
            assert proof(str(table)) == table_proof
        else:
            assert after["subtree"][existing["id"]]["object"] == existing
            current_source = after["subtree"][old_source["object"]["id"]]
            assert current_source["object"] == old_source["object"]
            assert current_source["media"]["sha256"] == report["inputs"][str(replacement)]["sha256"] != old_source["media"]["sha256"]
        new_owner, = [row["object"] for row in after["subtree"].values() if row["object"]["name"] == new_name and row["object"]["parent"]["id"] == container_id]
        new_source, = [row for row in after["subtree"].values() if row["object"]["type"] == "AudioFileSource" and row["object"]["parent"]["id"] == new_owner["id"]]
        assert new_owner["type"] == "Sound" and new_owner["class_id"] == 65552 and new_source["media"]["sha256"] == report["inputs"][str(created)]["sha256"]
        if tab_delimited:
            assert new_owner["path"] == container["path"] + "\\" + new_name and new_owner["parent"]["id"] == container_id, new_owner
            assert (new_source["object"]["name"], new_source["object"]["path"], new_source["object"]["class_id"]) == (
                new_name, new_owner["path"] + "\\" + new_name, 16), new_source

        assert set(after["subtree"]) == set(before) | {new_owner["id"], new_source["object"]["id"]}
        requested_pairs = ([{"child": new_owner["id"].upper(), "stateOrSwitch": identity} for identity in (value_id, metal_id)]
            if tab_delimited else [{"child": identity.upper(), "stateOrSwitch": value_id} for identity in (existing["id"], new_owner["id"])])
        expected = sorted([*baseline["pairs"], *requested_pairs], key=lambda row: (row["child"], row["stateOrSwitch"]))
        assert after["pairs"] == expected, {"expected": expected, "actual": after["pairs"]}
        assert all(proof(path) == original for path, original in report["inputs"].items())
        assert len(witness["actual_verifications"]) == 1 and witness["actual_verifications"][0]["readbacks"]
        assert code == 0 and verified.get("verified") is True, verified
        report.update(stage="complete", business_effect_verified=True); category["status"] = "PASS"
        return category
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        raise
    finally:
        persist()


def collect_dialogue_read_probe(runtime):
    """Observe an existing nonempty decision graph; never infer default import effects."""
    import xml.etree.ElementTree as ET
    assert runtime.version == "2025.1"
    owned = runtime.sandbox.sandbox_path.resolve(strict=True)
    assert owned != runtime.sandbox.source_root.resolve(strict=True)
    output = runtime.state_dir / "dialogue-read-probe.json"
    assert not output.exists(), "Never overwrite a Dialogue observation"
    category = {"category": "dialogue-read-only-observation", "status": "FAIL", "transaction_ids": [],
        "observation_path": str(output), "verifier_strength": "bounded_read_collection_only_no_business_credit",
        "business_effect_verified": False, "coverage_credit": False}
    runtime.category_results.append(category)
    report = {"contract": "waapi-skill.dialogue-read-probe/v1", "candidate": runtime.candidate,
        "version": runtime.version, "calls": [], "boundaries": [], "metadata": [], "objects": [],
        "collection_complete": False, "business_effect_verified": False, "coverage_credit": False,
        "default_association_proven": False, "association_status": "unresolved", "mutation_allowed": False,
        "transaction_budget": 0, "limits": {"calls": 48, "reply_bytes": 524288, "receipt_bytes": 4194304,
            "metadata_pages": 2, "detail_pages": 4, "referrers": 8}, "failure": None}
    endpoint = {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url}

    def persist():
        body = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= report["limits"]["receipt_bytes"], "Dialogue observation byte limit exceeded"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp"); temporary.write_bytes(body); temporary.replace(output)
        category["observation_sha256"] = hashlib.sha256(body).hexdigest()

    def boundary(stage, reason, **facts):
        report["boundaries"].append({"stage": stage, "reason": reason, **facts})

    def read(stage, argv):
        assert argv[0] in {"status", "metadata", "query-object"}, "Dialogue probe is read-only"
        assert len(report["calls"]) < report["limits"]["calls"]
        call = {"stage": stage, "argv": list(argv)}; report["calls"].append(call)
        try:
            code, packet = runtime.raw_gateway(argv)
            call.update(exit_code=code, payload=packet)
            assert len(json.dumps(packet, ensure_ascii=False).encode("utf-8")) <= report["limits"]["reply_bytes"]
            if code != 0 or packet.get("ok") is not True:
                boundary(stage, "structured_read_rejected", error_code=packet.get("error_code"))
                return None
            assert packet.get("detected_version") == runtime.version and packet.get("endpoint") == endpoint, packet
            return packet
        except Exception as exc:
            call["exception"] = {"type": type(exc).__name__, "message": str(exc)[:1024]}
            raise
        finally:
            persist()

    def pages(stage, argv, key=None, *, maximum_pages=2):
        rows, command = [], list(argv)
        for _ in range(maximum_pages):
            packet = read(stage, command)
            if packet is None:
                return rows
            page = packet["agent_result"]
            if key:
                assert isinstance(page.get(key), list) and len(page[key]) <= 64, page
                rows.extend(page[key])
            else:
                rows.append(page)
            if page.get("complete") is True:
                return rows
            command = page.get("next_command", {}).get("gateway_argv")
            assert isinstance(command, list) and command[:1] == ["metadata"], "Incomplete metadata page lacks public continuation"
        raise AssertionError("Dialogue metadata did not complete within its page bound")

    def query(stage, identity, *, related=False, field=None, expected=None):
        argv = ["query-object", "--exact-id", identity, "--max-results", "2", "--include", "class-id",
            "--include", "parent", "--include", "owner", "--detail"]
        if related:
            argv += ["--include-related", "references-to", "parent", "--include-related", "references-to", "owner"]
        if field:
            argv += ["--include-field", field]
        packet = read(stage, argv)
        if packet is None:
            return None
        assert packet.get("projection_complete") is not False and packet.get("limit_reached") is not True and packet.get("status") != "partial", packet
        rows = packet["objects"]
        assert isinstance(rows, list) and packet["count"] == len(rows) <= 1, packet
        if not rows:
            boundary(stage, "exact_identity_not_returned_not_native_absence", object_id=identity)
            return None
        row, = rows
        assert row["id"].upper() == identity.upper(), row
        if expected:
            assert all(row.get(key) == value for key, value in expected.items()), {"expected": expected, "actual": row}
        for relationship in ("parent", "owner"):
            if relationship not in row:
                boundary(stage, "requested_relationship_omitted", relationship=relationship)
        report["objects"].append({"stage": stage, "row": row})
        return row

    def metadata(stage, scope, wanted):
        fields = pages(stage + "-list", ["metadata", "list", *scope, "--page-size", "64"], "fields")
        result = {"stage": stage, "scope": scope, "fields": fields, "details": []}; report["metadata"].append(result)
        for name in wanted:
            selected = [field for field in fields if field.get("name") == name]
            if len(selected) != 1:
                boundary(stage, "requested_field_not_uniquely_listed", field=name, count=len(selected))
                continue
            detail = pages(stage + "-" + name, ["metadata", "detail", *scope, "--selection", selected[0]["selection"]],
                maximum_pages=report["limits"]["detail_pages"])
            result["details"].append({"field": selected[0], "pages": detail})
        return result

    try:
        # Parse only the private copy. XML list membership does not specify a
        # queryable member path or native parent/owner response.
        from tests.destructive.test_gateway_workflow_transaction_matrix import REPO_ROOT
        catalog_path = REPO_ROOT / "skills/waapi-skill/resources/metadata/2025.1/object-types.json"
        classes = {row["name"]: row["classId"] for row in json.loads(catalog_path.read_text())["types"]}
        documents = {}
        for relative in ("Dynamic Dialogue/Dialogue.wwu", "Containers/Dialogues.wwu"):
            path = (owned / relative).resolve(strict=True); assert path.is_relative_to(owned)
            documents[relative] = ET.parse(path)
        dialogue = documents["Dynamic Dialogue/Dialogue.wwu"]
        event = dialogue.find('.//DialogueEvent[@ID="{3C874205-5335-4290-830F-A8BFF3AE8A6B}"]')
        entry = event.find('./ObjectLists/ObjectList[@Name="Entries"]/MultiSwitchEntry[@ID="{A1AEBDF2-1B8E-4E92-9CE8-336DB7CB44CA}"]')
        audio_node = entry.find('./ReferenceList/Reference[@Name="AudioNode"]/ObjectRef').attrib["ID"]
        sound_doc = documents["Containers/Dialogues.wwu"]
        sound = sound_doc.find('.//Sound[@ID="' + audio_node + '"]')
        assert sound is not None and audio_node == "{CFA81CFE-9D22-4078-9738-83471EF92418}"
        def identity(document, node, hierarchy):
            parents = {child: parent for parent in document.iter() for child in parent}
            ancestry, current = [], node
            while current is not None:
                if current.attrib.get("Name") and current.attrib.get("ID"):
                    ancestry.append(current)
                current = parents.get(current)
            chain = list(reversed(ancestry))
            return {"id": node.attrib["ID"], "name": node.attrib["Name"], "type": node.tag,
                "class_id": classes[node.tag], "path": "\\" + "\\".join([hierarchy, *(item.attrib["Name"] for item in chain)])}
        report["source_scope"] = {"event": identity(dialogue, event, "Dynamic Dialogue"),
            "sound": identity(sound_doc, sound, "Containers"), "entry": {"id": entry.attrib["ID"], "type": entry.tag,
                "class_id": classes[entry.tag], "xml_name": entry.attrib["Name"], "xml_list_owner": event.attrib["ID"]},
            "entry_path_slot_count": len(entry.findall('./ObjectLists/ObjectList[@Name="EntryPath"]/*')),
            "event_entry_count": len(event.findall('./ObjectLists/ObjectList[@Name="Entries"]/MultiSwitchEntry')),
            "argument_count": len(event.findall('./ObjectLists/ObjectList[@Name="Arguments"]/*')),
            "entry_path_slots": [{"xml_id": slot.attrib["ID"], "reference": slot.find('./ReferenceList/Reference[@Name="EntryPathObject"]/ObjectRef').attrib}
                for slot in entry.findall('./ObjectLists/ObjectList[@Name="EntryPath"]/*')],
            "event_entry_ids": [member.attrib["ID"] for member in event.findall('./ObjectLists/ObjectList[@Name="Entries"]/MultiSwitchEntry')],
            "other_events": [{"id": other.attrib["ID"], "name": other.attrib["Name"],
                "entry_count": len(other.findall('./ObjectLists/ObjectList[@Name="Entries"]/MultiSwitchEntry'))}
                for other in dialogue.findall('.//DialogueEvent') if other is not event],
            "source_files": [{"relative_path": relative, "sha256": hashlib.sha256((owned / relative).read_bytes()).hexdigest()}
                for relative in documents], "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
            "warning": "Existing conditional path is NONEMPTY; XML membership is not a native parent/owner/default-association observation"}
        assert report["source_scope"]["entry_path_slot_count"] == report["source_scope"]["argument_count"] == 3
        persist()
        status = read("owned-project", ["status", "--detail"])
        assert status is not None
        project_path = Path(localize_waapi_host_path(status["agent_result"]["project"]["path"])).resolve(strict=True)
        assert project_path == runtime.sandbox.sandbox_project.resolve(strict=True) != runtime.sandbox.source_project.resolve(strict=True)
        types = pages("types", ["metadata", "types", "--meaning", "DialogueEvent", "--meaning", "MultiSwitchEntry", "--page-size", "64"], "types")
        for name, wanted in (("DialogueEvent", ("Entries", "Arguments")), ("MultiSwitchEntry", ("AudioNode", "EntryPath"))):
            selections = [row for row in types if row.get("name") == name and row.get("classId") == classes[name]]
            if len(selections) == 1:
                metadata(name, ["--type-selection", selections[0]["selection"]], wanted)
            else:
                boundary("types", "class_selection_unavailable", name=name, class_id=classes[name])
        scope = report["source_scope"]
        query("event", event.attrib["ID"], expected=scope["event"])
        query("entry", entry.attrib["ID"], expected={key: scope["entry"][key] for key in ("id", "type", "class_id")})
        observed_sound = query("sound-referrers", audio_node, related=True, expected=scope["sound"])
        referrers = []
        if observed_sound:
            sequence = observed_sound.get("related", {}).get("references-to")
            if not isinstance(sequence, Mapping) or not isinstance(sequence.get("items"), list):
                boundary("sound-referrers", "reference_list_omitted_not_native_absence")
            else:
                assert len(sequence["items"]) <= report["limits"]["referrers"]
                for member in sequence["items"]:
                    actual = member.get("object")
                    if isinstance(actual, Mapping) and actual.get("id"):
                        canonical = "{" + str(uuid.UUID(actual["id"])).upper() + "}"
                        assert canonical == actual["id"].upper()
                        referrers.append(canonical)
                    else:
                        boundary("sound-referrers", "reference_member_identity_unavailable", member=member)
        for referrer in dict.fromkeys(referrers):
            query("exact-referrer", referrer)
        entry_fields = metadata("actual-entry", ["--exact-id", entry.attrib["ID"]], ("AudioNode", "EntryPath"))
        for detail in entry_fields["details"]:
            if detail["field"]["name"] != "AudioNode":
                continue
            info = detail["pages"][0].get("metadata", {}) if detail["pages"] else {}
            restriction = info.get("restriction")
            if str(info.get("type", "")).casefold() == "reference" or (isinstance(restriction, Mapping) and restriction.get("type") == "reference"):
                query("actual-entry-audio-node", entry.attrib["ID"], field=detail["field"]["name"])
            else:
                boundary("actual-entry", "audio_node_reference_metadata_unavailable")
        report.update(collection_complete=True, association_status="observed_requires_review")
        category["status"] = "PASS"
        return category
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        raise
    finally:
        persist()
