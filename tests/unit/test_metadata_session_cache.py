from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.platform_filesystem import create_symlink_or_skip

from wwise_waapi.metadata_cache import (
    DURABLE_METADATA_CACHE_DIRECTORY,
    DurableMetadataCache,
    GET_ATTENUATION_CURVE_URI,
    IS_PROPERTY_ENABLED_URI,
    MetadataCacheError,
    MetadataCacheLookup,
    MetadataSessionIdentity,
    SessionMetadataCache,
)


RESOURCE_DIGEST = "a" * 64


def _identity() -> MetadataSessionIdentity:
    return MetadataSessionIdentity(
        endpoint="ws://127.0.0.1:8080/waapi",
        wwise_build="2022.1.19.8584",
        schema_version="110",
        session_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        process_id=4242,
        project_id="{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        resource_digest=RESOURCE_DIGEST,
    )


def test_live_context_identity_binds_runtime_project_and_catalog() -> None:
    identity = MetadataSessionIdentity.from_live_context(
        endpoint="ws://127.0.0.1:8080/waapi",
        live_info={
            "processId": 4242,
            "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            "version": {
                "build": 8584,
                "major": 1,
                "minor": 19,
                "schema": 110,
                "year": 2022,
            },
        },
        project={
            "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        },
        resource_digest=RESOURCE_DIGEST,
    )

    assert identity == _identity()


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("endpoint", "ws://127.0.0.1:8081/waapi"),
        ("wwise_build", "2022.1.19.9999"),
        ("schema_version", "111"),
        ("session_id", "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"),
        ("process_id", 4343),
        ("project_id", "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}"),
        ("resource_digest", "b" * 64),
    ),
)
def test_cache_misses_when_any_session_identity_fact_changes(
    field_name: str,
    value: object,
) -> None:
    cache = SessionMetadataCache()
    lookup = MetadataCacheLookup.property_info(
        class_id=65552,
        property_name="Volume",
    )
    cache.put(_identity(), lookup, {"name": "Volume", "type": "Real32"})

    changed = replace(_identity(), **{field_name: value})

    assert cache.get(changed, lookup) is None
    assert cache.get(_identity(), lookup) == {
        "name": "Volume",
        "type": "Real32",
    }


def test_cache_returns_defensive_copies_and_invalidates_one_session() -> None:
    cache = SessionMetadataCache()
    identity = _identity()
    lookup = MetadataCacheLookup.types()
    source = [{"classId": 65552, "name": "Sound", "type": "WObject"}]

    cache.put(identity, lookup, source)
    source[0]["name"] = "mutated outside cache"
    returned = cache.get(identity, lookup)
    returned[0]["name"] = "mutated returned copy"

    assert cache.get(identity, lookup)[0]["name"] == "Sound"
    assert cache.invalidate_session(identity) == 1
    assert cache.get(identity, lookup) is None


def test_dynamic_metadata_is_explicitly_never_cacheable() -> None:
    for uri in (IS_PROPERTY_ENABLED_URI, GET_ATTENUATION_CURVE_URI):
        with pytest.raises(MetadataCacheError, match="dynamic"):
            MetadataCacheLookup(uri)


def test_lookup_shapes_are_closed() -> None:
    assert MetadataCacheLookup.names(class_id=65552).class_id == 65552
    assert (
        MetadataCacheLookup.property_info(
            object_id="{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}",
            property_name="Volume",
        ).as_dict()
        == {
            "class_id": None,
            "object_id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            "property_name": "Volume",
            "uri": "ak.wwise.core.object.getPropertyInfo",
        }
    )
    with pytest.raises(MetadataCacheError, match="exactly one"):
        MetadataCacheLookup.names()
    with pytest.raises(MetadataCacheError, match="exactly one"):
        MetadataCacheLookup.names(class_id=1, object_id="{object}")
    with pytest.raises(MetadataCacheError, match="property_name"):
        MetadataCacheLookup.property_info(
            class_id=1,
            property_name=" ",
        )


def test_cache_is_bounded_by_lru_count_and_value_size() -> None:
    cache = SessionMetadataCache(
        max_entries=2,
        max_entry_bytes=128,
        max_total_bytes=256,
    )
    identity = _identity()
    first = MetadataCacheLookup.property_info(
        class_id=1,
        property_name="First",
    )
    second = MetadataCacheLookup.property_info(
        class_id=1,
        property_name="Second",
    )
    third = MetadataCacheLookup.property_info(
        class_id=1,
        property_name="Third",
    )

    cache.put(identity, first, {"name": "First"})
    cache.put(identity, second, {"name": "Second"})
    assert cache.get(identity, first) == {"name": "First"}
    cache.put(identity, third, {"name": "Third"})

    assert cache.get(identity, second) is None
    assert cache.get(identity, first) == {"name": "First"}
    assert cache.stats().evictions == 1
    with pytest.raises(MetadataCacheError, match="per-entry"):
        cache.put(identity, second, {"value": "x" * 256})


def test_durable_cache_reuses_validated_class_metadata_across_instances(
    tmp_path: Path,
) -> None:
    first = DurableMetadataCache(state_dir=tmp_path)
    second = DurableMetadataCache(state_dir=tmp_path)
    lookup = MetadataCacheLookup.property_info(
        class_id=65552,
        property_name="Volume",
    )
    value = {
        "name": "Volume",
        "type": "Real32",
        "restriction": {"min": -96.3, "max": 12.0},
    }

    assert first.put(_identity(), lookup, value) is True
    assert second.get(_identity(), lookup) == value


def test_durable_cache_misses_when_identity_changes_and_never_persists_object_scope(
    tmp_path: Path,
) -> None:
    cache = DurableMetadataCache(state_dir=tmp_path)
    class_lookup = MetadataCacheLookup.names(class_id=65552)
    object_lookup = MetadataCacheLookup.names(
        object_id=r"\Actor-Mixer Hierarchy\Default Work Unit\Target",
    )

    assert cache.put(_identity(), class_lookup, {"return": ["Volume"]}) is True
    assert (
        cache.get(
            replace(_identity(), session_id="{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"),
            class_lookup,
        )
        is None
    )
    assert cache.put(_identity(), object_lookup, {"return": ["Volume"]}) is False
    assert cache.get(_identity(), object_lookup) is None


def test_durable_cache_persists_only_canonical_guid_object_scope(
    tmp_path: Path,
) -> None:
    cache = DurableMetadataCache(state_dir=tmp_path)
    lookup = MetadataCacheLookup.property_info(
        object_id="{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}",
        property_name="Volume",
    )
    value = {"name": "Volume", "type": "Real32"}

    assert lookup.durable_safe is True
    assert cache.put(_identity(), lookup, value) is True
    equivalent_case = MetadataCacheLookup.property_info(
        object_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        property_name="Volume",
    )
    assert cache.get(_identity(), equivalent_case) == value


def test_durable_cache_corruption_and_unsafe_directory_are_best_effort_misses(
    tmp_path: Path,
) -> None:
    cache = DurableMetadataCache(state_dir=tmp_path)
    lookup = MetadataCacheLookup.types()
    value = {
        "return": [
            {"classId": 65552, "name": "Sound", "type": "WObject"},
        ]
    }

    assert cache.put(_identity(), lookup, value) is True
    entry = next(
        (tmp_path / DURABLE_METADATA_CACHE_DIRECTORY).glob("*.json")
    )
    entry.write_text("{not-json", encoding="utf-8")
    assert DurableMetadataCache(state_dir=tmp_path).get(
        _identity(),
        lookup,
    ) is None

    unsafe_state = tmp_path / "unsafe-state"
    unsafe_state.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    cache_directory = unsafe_state / DURABLE_METADATA_CACHE_DIRECTORY
    create_symlink_or_skip(cache_directory, outside, target_is_directory=True)
    unsafe = DurableMetadataCache(state_dir=unsafe_state)
    assert unsafe.get(_identity(), lookup) is None
    assert unsafe.put(_identity(), lookup, value) is False


def test_durable_cache_unsafe_managed_entry_blocks_publication(
    tmp_path: Path,
) -> None:
    cache = DurableMetadataCache(state_dir=tmp_path)
    cache.directory.mkdir()
    outside = tmp_path / "outside-entry.json"
    outside.write_text("outside", encoding="utf-8")
    unsafe_entry = cache.directory / f"{'f' * 64}.json"
    create_symlink_or_skip(unsafe_entry, outside)

    assert cache.put(
        _identity(),
        MetadataCacheLookup.property_info(
            class_id=65552,
            property_name="Volume",
        ),
        {"name": "Volume", "type": "Real32"},
    ) is False
    assert [
        path
        for path in cache.directory.glob("*.json")
        if not path.is_symlink()
    ] == []
    assert outside.read_text(encoding="utf-8") == "outside"


def test_durable_cache_cleans_stale_crash_temp_and_bounds_fresh_temps(
    tmp_path: Path,
) -> None:
    cache = DurableMetadataCache(
        state_dir=tmp_path,
        max_entries=1,
        max_file_bytes=2_048,
        max_total_bytes=4_096,
    )
    cache.directory.mkdir()
    stale = cache.directory / f".{'e' * 64}.{'d' * 32}.tmp"
    stale.write_text("abandoned", encoding="utf-8")
    old = time.time() - 3_600
    os.utime(stale, (old, old))
    lookup = MetadataCacheLookup.property_info(
        class_id=65552,
        property_name="Volume",
    )

    assert cache.put(
        _identity(),
        lookup,
        {"name": "Volume", "type": "Real32"},
    ) is True
    assert not stale.exists()

    active = cache.directory / f".{'c' * 64}.{'b' * 32}.tmp"
    active.write_text("active", encoding="utf-8")
    assert cache.put(
        _identity(),
        MetadataCacheLookup.property_info(
            class_id=65552,
            property_name="Pitch",
        ),
        {"name": "Pitch", "type": "Real32"},
    ) is False
    assert active.is_file()
    assert len(
        [
            path
            for path in cache.directory.glob("*.json")
            if not path.is_symlink()
        ]
    ) == 1


def test_durable_cache_enforces_file_and_entry_bounds(tmp_path: Path) -> None:
    bounded = DurableMetadataCache(
        state_dir=tmp_path,
        max_entries=1,
        max_file_bytes=2_048,
        max_total_bytes=4_096,
    )
    first = MetadataCacheLookup.property_info(
        class_id=65552,
        property_name="Volume",
    )
    second = MetadataCacheLookup.property_info(
        class_id=65552,
        property_name="Pitch",
    )

    assert bounded.put(
        _identity(),
        first,
        {"name": "Volume", "type": "Real32"},
    )
    assert bounded.put(
        _identity(),
        second,
        {"name": "Pitch", "type": "Real32"},
    )
    assert bounded.get(_identity(), first) is None
    assert bounded.get(_identity(), second) == {
        "name": "Pitch",
        "type": "Real32",
    }
    assert len(
        list((tmp_path / DURABLE_METADATA_CACHE_DIRECTORY).glob("*.json"))
    ) == 1

    too_small = DurableMetadataCache(
        state_dir=tmp_path / "small",
        max_entries=2,
        max_file_bytes=512,
        max_total_bytes=1_024,
    )
    (tmp_path / "small").mkdir()
    assert too_small.put(
        _identity(),
        first,
        {"name": "Volume", "type": "String", "default": "x" * 1_024},
    ) is False
