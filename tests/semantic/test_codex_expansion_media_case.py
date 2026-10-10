"""Outcome controls for same-basename reimport, independent of a live host."""

from copy import deepcopy
from pathlib import Path

from tests.semantic.support.codex_expansion_media_case import approve_c03_preview, verify_c03


def _snapshot():
    return {
        "sounds": {
            "left": {"object": {"id": "left", "volume_db": -3},
                     "source_volume_offset": 0,
                     "source": {"id": "source-left", "parent": {"id": "left"}},
                     "media": {"sha256": "old-left", "path": "/owned/left/Hit.wav"}},
            "right": {"object": {"id": "right", "volume_db": -6},
                      "source_volume_offset": 0,
                      "source": {"id": "source-right", "parent": {"id": "right"}},
                      "media": {"sha256": "old-right", "path": "/owned/right/Hit.wav"}},
        },
        "members": ["left", "right", "spare"],
        "distractor": {"id": "spare", "volume_db": -9},
    }


def test_c03_accepts_exact_media_mapping_and_independent_object_order():
    before = _snapshot()
    after = deepcopy(before)
    for key in ("left", "right"):
        after["sounds"][key]["media"]["sha256"] = "new-" + key
    after["sounds"] = dict(reversed(list(after["sounds"].items())))
    after["members"].reverse()
    assert all(verify_c03(before, after, expected={"left": "new-left", "right": "new-right"}).values())


def test_c03_rejects_basename_swap_recreated_source_and_collateral_edit():
    before = _snapshot()
    after = deepcopy(before)
    after["sounds"]["left"]["media"]["sha256"] = "new-right"
    after["sounds"]["right"]["media"]["sha256"] = "new-left"
    result = verify_c03(before, after, expected={"left": "new-left", "right": "new-right"})
    assert not result["exact_media_mapping"]
    after["sounds"]["left"]["source"]["id"] = "new-id"
    after["distractor"]["volume_db"] = 0
    result = verify_c03(before, after, expected={"left": "new-left", "right": "new-right"})
    assert not result["source_identities_and_configuration_preserved"]
    assert not result["distractor_unchanged"]


def test_c03_preview_accepts_row_permutation_but_rejects_wrong_mapping():
    mappings = {r"\Containers\Left": Path("/left/Hit.wav"),
                r"\Containers\Right": Path("/right/Hit.wav")}
    imports = [{"object_path": key, "object_type": "Sound SFX", "audio_file": str(value),
                "import_language": "SFX"} for key, value in mappings.items()]
    artifact = {"request": {"operation": "audio.import", "version": "2025.1",
                            "arguments": {"import_operation": "useExisting", "imports": imports}}}
    target_ids = {path: str(index) for index, path in enumerate(mappings)}
    artifact["prepared_operation"] = {"verification_plan": {"kind": "closed-audio-import", "targets": [
        {"canonical_target_path": path, "preexisting_id": target} for path, target in target_ids.items()]}}
    assert approve_c03_preview(artifact, version="2025.1", mappings=mappings, target_ids=target_ids)
    imports.reverse()
    assert approve_c03_preview(artifact, version="2025.1", mappings=mappings, target_ids=target_ids)
    plan = artifact["prepared_operation"]["verification_plan"]
    plan["targets"][0]["preexisting_id"] = "replacement-identity"
    assert not approve_c03_preview(artifact, version="2025.1", mappings=mappings, target_ids=target_ids)
    plan["targets"][0]["preexisting_id"] = "0"
    imports[0]["audio_file"] = "/left/Hit.wav"
    assert not approve_c03_preview(artifact, version="2025.1", mappings=mappings, target_ids=target_ids)
