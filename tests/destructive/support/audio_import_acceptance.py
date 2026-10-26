"""Two bounded import witnesses using the existing owned workflow lifecycle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid

from wwise_waapi.host_paths import localize_waapi_host_path


def _collect(runtime, *, localized):
    from tests.destructive.test_gateway_workflow_transaction_matrix import (
        _start_business_draft, _update_business_draft, _bind_business_object,
        _complete_business_draft, _write_fixture_wav, _save_sandbox_project,
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
        def gateway(self, argv, *, live):
            assert len(receipt["calls"]) < receipt["limits"]["calls"]
            if argv[0] == "execute":
                assert argv[1] not in attempted, "Import execution is never retried"
                attempted.add(argv[1])
            row = {"argv": list(argv)}; receipt["calls"].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                row.update(exit_code=code, payload=payload)
                assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= receipt["limits"]["reply_bytes"]
                assert code == 0 and payload.get("ok") is True, payload
                if live:
                    assert payload["detected_version"] == runtime.version
                    assert payload["endpoint"] == {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url}
                return payload
            finally:
                persist()
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
                "--field", "audio_source_notes", "Keep Japanese notes", "--field", "originals_subfolder", "Other",
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
                row, = dispatch["args"]["imports"]
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
                "old_id_rows": query(["--exact-id", existing], maximum=2),
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
