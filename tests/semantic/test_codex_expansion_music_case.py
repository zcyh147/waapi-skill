from copy import deepcopy
from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_music_case import (
    M01_ASSERTIONS, approve_m01_preview, verify_m01,
)


def artifact(version="2025.1"):
    base = r"\Containers\Default Work Unit\Owned\<MusicSegment>Imported"
    return {"request": {"operation": "audio.import", "version": version, "arguments": {
        "imports": [
            {"object_type": "MusicSegment", "object_path": base},
            {"object_type": "MusicTrack", "object_path": base + r"\<MusicTrack>Quiet",
             "audio_file": "/assets/Quiet.wav", "import_language": "SFX",
             "properties": [{"name": "Volume", "value": -6.0}]},
            {"object_type": "MusicTrack", "object_path": base + r"\<MusicTrack>Full",
             "audio_file": "/assets/Full.wav", "import_language": "SFX"},
        ],
    }}}


def approve(value, version="2025.1"):
    return approve_m01_preview(value, version=version,
        parent_path=r"\Containers\Default Work Unit\Owned", segment_name="Imported",
        media={"Quiet": Path("/assets/Quiet.wav"), "Full": Path("/assets/Full.wav")})


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_preview_closes_media_track_property_and_target_scope(version):
    value = artifact(version)
    assert approve(value, version)
    for mutate in (
        lambda rows: rows[1].update(audio_file="/assets/Full.wav"),
        lambda rows: rows[2].update(properties=[{"name": "Volume", "value": -6.0}]),
        lambda rows: rows[1].update(references=[{"name": "OutputBus", "target": {"kind": "path", "value": "other"}}]),
        lambda rows: rows[0].update(object_type="ActorMixer"),
        lambda rows: rows.append(deepcopy(rows[1])),
    ):
        changed = deepcopy(value)
        mutate(changed["request"]["arguments"]["imports"])
        assert not approve(changed, version)


def snapshots():
    parent = {"id": "parent", "name": "Owned"}
    keep = {"id": "keep", "type": "MusicSegment", "parent": {"id": "parent"}}
    before = {"parent": parent, "protected": keep, "children": [keep], "segment": None, "tracks": {}}
    segment = {"id": "new", "type": "MusicSegment", "parent": {"id": "parent"}}
    after = deepcopy(before) | {"segment": segment, "children": [keep, segment], "tracks": {}}
    for name, volume in (("Quiet", -6), ("Full", 0)):
        media = {"path": f"/Originals/{name}.wav", "sha256": name}
        after["tracks"][name] = {
            "track": {"id": name, "parent": {"id": "new"}, "@Volume": volume,
                      "@Sequences": [{"id": name + "seq", "name": ""}]},
            "source": {"id": name + "src", "parent": {"id": name},
                       "@VolumeOffset": 0, "audioSource:language": "SFX"},
            "sequence": {"id": name + "seq", "type": "MusicTrackSequence",
                         "@Clips": [{"id": name + "clip"}]},
            "clip": {"id": name + "clip", "type": "MusicClip", "@Volume": 0},
            "source_media": media, "clip_media": deepcopy(media),
        }
    return before, after


def test_music_oracle_rejects_right_hierarchy_with_wrong_media_or_property_owner():
    before, after = snapshots()
    hashes = {"Quiet": "Quiet", "Full": "Full"}
    result = verify_m01(before, after, expected_hashes=hashes)
    assert set(result) == M01_ASSERTIONS and all(result.values())
    wrong_media = deepcopy(after)
    wrong_media["tracks"]["Quiet"]["source_media"]["sha256"] = "Full"
    assert not verify_m01(before, wrong_media, expected_hashes=hashes)["media_hashes_match_each_requested_track"]
    wrong_owner = deepcopy(after)
    wrong_owner["tracks"]["Quiet"]["clip"]["@Volume"] = -6
    assert not verify_m01(before, wrong_owner, expected_hashes=hashes)["only_track_has_requested_volume"]
    wrong_parent = deepcopy(after)
    wrong_parent["tracks"]["Quiet"]["source"]["parent"]["id"] = "Full"
    assert not verify_m01(before, wrong_parent, expected_hashes=hashes)["exact_segment_track_source_topology"]
    wrong_source = deepcopy(after)
    wrong_source["tracks"]["Quiet"]["source"]["@VolumeOffset"] = -6
    assert not verify_m01(before, wrong_source, expected_hashes=hashes)["only_track_has_requested_volume"]
