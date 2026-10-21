"""Read the exact 2025 PlaylistSlot field identified in installed WObjects.xml."""
from __future__ import annotations

import hashlib
import json


def collect_playlist_slot_reference_metadata(runtime) -> None:
    assert runtime.version == "2025.1", "PlaylistSlot field observation is pinned to 2025.1"
    output = runtime.state_dir / "playlist-reference-metadata.json"
    observation = {
        "candidate": runtime.candidate,
        "version": runtime.version,
        "class_name": "PlaylistSlot",
        "class_id": 5636096,
        "field": "PlaylistObject",
        "project_mutation_count": 0,
        "business_effect_verified": False,
        "hierarchy_semantics_proven": False,
        "calls": [],
    }
    category = {
        "category": "playlist-reference-native-metadata",
        "status": "FAIL",
        "verifier_strength": "native_class_metadata_only",
        "business_effect_verified": False,
        "observation_path": str(output),
    }
    runtime.category_results.append(category)

    def read(argv):
        assert len(observation["calls"]) < 9, "Playlist metadata call bound exceeded"
        code, payload = runtime.raw_gateway(argv)
        observation["calls"].append({"argv": argv, "exit_code": code, "payload": payload})
        assert code == 0 and payload.get("ok") is True, payload
        assert payload.get("detected_version") == "2025.1", payload
        return payload["agent_result"]

    try:
        cursor = None
        selection = None
        scope = None
        snapshot = None
        seen = set()
        for _ in range(8):
            argv = ["metadata", "list", "--custom-kind", "PlaylistSlot", "--page-size", "64"]
            if cursor is not None:
                argv += ["--page", cursor]
            page = read(argv)
            assert page.get("mutation_authority") is False, page
            if scope is None:
                scope, snapshot = page["scope"], page["snapshot"]
                assert scope["resolved"]["classId"] == 5636096, page
                assert scope["resolved"]["name"] == "PlaylistSlot", page
            assert (page["scope"], page["snapshot"]) == (scope, snapshot), page
            matches = [row for row in page["fields"] if row["name"] == "PlaylistObject"]
            assert len(matches) <= 1, page
            if matches:
                selection = matches[0]["selection"]
                break
            cursor = page.get("next_page")
            if cursor is None:
                break
            assert isinstance(cursor, str) and cursor not in seen, page
            seen.add(cursor)
        assert selection is not None, "Native PlaylistObject field not observed within the bounded inventory"
        detail = read(["metadata", "detail", "--custom-kind", "PlaylistSlot", "--selection", selection])
        assert detail.get("mutation_authority") is False and detail.get("complete") is True, detail
        assert detail["scope"] == scope and detail["selection"] == selection, detail
        metadata = detail["metadata"]
        assert metadata["name"] == "PlaylistObject", detail
        restriction = metadata["restriction"]
        assert restriction["type"] == "reference", detail
        assert "mustChildOf" in restriction["restrictions"], detail
        assert "notNull" in restriction["restrictions"], detail
        observation["metadata"] = metadata
        category.update(status="PASS", reason="Exact PlaylistSlot metadata observed; no hierarchy effect or mutation acceptance")
    except BaseException as exc:
        observation["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024, "Playlist metadata observation exceeded byte bound"
        output.write_bytes(body)
        category["observation_sha256"] = hashlib.sha256(body).hexdigest()


def collect_playlist_instance_identities(runtime) -> None:
    """Read source-selected instances, without treating XML tags as live types."""
    assert runtime.version == "2025.1"
    identities = {
        "slot": "{7571D6B0-D614-40B5-B02D-0012FE3743A7}",
        "peer": "{6298C41E-F7C6-40B6-BFFE-E0B02EE7DC72}",
        "owner": "{8C0FD1AD-E45D-408D-9BF3-874970CCC123}",
        "target": "{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}",
    }
    output = runtime.state_dir / "playlist-instance-identities.json"
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "project_mutation_count": 0, "business_effect_verified": False, "calls": [], "objects": {}}
    category = {"category": "playlist-instance-native-identities", "status": "FAIL",
        "verifier_strength": "read_only_identity_and_membership_observation",
        "business_effect_verified": False, "observation_path": str(output)}
    runtime.category_results.append(category)

    def read(label, selector):
        assert len(observation["calls"]) < 5
        argv = ["query-object", *selector, "--max-results", "4", "--include", "class-id",
                "--include", "owner", "--include", "parent"]
        code, payload = runtime.raw_gateway(argv)
        observation["calls"].append({"label": label, "argv": argv, "exit_code": code, "payload": payload})
        assert code == 0 and payload.get("ok") is True, payload
        rows = payload.get("objects", payload.get("agent_result"))
        assert isinstance(rows, list), payload
        observation["objects"][label] = rows
        return rows

    try:
        for label, identity in identities.items():
            rows = read(label, ["--exact-id", identity])
            assert len(rows) == 1 and rows[0]["id"].casefold() == identity.casefold(), rows
        members = read("playlist", ["--advanced-waql", f'from object "{identities["owner"]}" select @Playlist'])
        assert [row["id"].casefold() for row in members] == [
            identities["slot"].casefold(), identities["peer"].casefold()], members
        category.update(status="PASS", reason="Existing identities and ordered Playlist members observed; no write acceptance")
    except BaseException as exc:
        observation["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024
        output.write_bytes(body)
        category["observation_sha256"] = hashlib.sha256(body).hexdigest()
