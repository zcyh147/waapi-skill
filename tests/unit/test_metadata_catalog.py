from __future__ import annotations

import json
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from tests.maintenance.build_object_type_catalogs import (
    ObjectTypeCatalogBuildError,
    build_catalog_file,
)
from wwise_waapi.metadata_catalog import (
    GET_TYPES_URI,
    MetadataCatalogError,
    MetadataCatalogMissingError,
    ObjectTypeCatalogStore,
    build_object_type_catalog_payload,
    parse_object_type_catalog,
)
from wwise_waapi.versions import (
    SUPPORTED_WWISE_VERSION_KEYS,
    WWISE_VERSION_CONTRACTS,
)


EXPECTED_ROW_COUNTS = {
    "2021.1": 105,
    "2022.1": 107,
    "2023.1": 109,
    "2024.1": 109,
    "2025.1": 125,
}


def _source(
    version: str = "2022.1",
    *,
    extra: bool = False,
) -> dict[str, object]:
    row: dict[str, object] = {
        "classId": 65552,
        "name": "Sound",
        "type": "WObject",
    }
    if extra:
        row["hostOnlyField"] = "must not be packaged"
    return {
        "api": GET_TYPES_URI,
        "evidence_path": "/ignored/campaign/path",
        "ok": True,
        "result": {
            "return": [
                row,
                {
                    "classId": 16,
                    "name": "AudioFileSource",
                    "type": "WObject",
                },
            ]
        },
        "version": version,
    }


def test_packaged_catalogs_load_for_all_pinned_versions() -> None:
    store = ObjectTypeCatalogStore()

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        catalog = store.load(version)
        assert catalog.version == version
        assert catalog.wwise_build == WWISE_VERSION_CONTRACTS[version].build
        assert catalog.row_count == EXPECTED_ROW_COUNTS[version]
        assert len(catalog.resource_sha256) == 64
        assert catalog.by_name("sound") is not None


def test_catalog_keyword_search_is_filtered_ranked_and_bounded() -> None:
    catalog = ObjectTypeCatalogStore().load("2022.1")

    matches = catalog.search(
        "audio source",
        object_type="WObject",
        limit=5,
    )

    assert matches
    assert matches[0].name == "AudioFileSource"
    assert all(record.type == "WObject" for record in matches)
    assert catalog.by_class_id(65552) == catalog.by_name("Sound")
    assert catalog.search("not-a-real-wwise-type") == ()
    with pytest.raises(MetadataCatalogError, match="limit"):
        catalog.search("sound", limit=101)


def test_catalog_builder_strips_campaign_fields_and_is_deterministic() -> None:
    payload = build_object_type_catalog_payload(
        _source(extra=True),
        version="2022.1",
    )
    repeated = build_object_type_catalog_payload(
        _source(extra=True),
        version="2022.1",
    )

    assert payload == repeated
    assert payload["metadata"]["row_count"] == 2
    assert payload["metadata"]["inventory_source"] == "live-getTypes"
    assert "/ignored/campaign/path" not in json.dumps(payload)
    assert "hostOnlyField" not in json.dumps(payload)
    assert [row["name"] for row in payload["types"]] == [
        "AudioFileSource",
        "Sound",
    ]
    parsed = parse_object_type_catalog(
        payload,
        expected_version="2022.1",
    )
    assert parsed.row_count == 2


def test_catalog_parser_fails_closed_on_digest_or_sort_drift() -> None:
    payload = build_object_type_catalog_payload(
        _source(),
        version="2022.1",
    )
    payload["types"][0]["name"] = "Tampered"
    with pytest.raises(MetadataCatalogError, match="deterministic order|sha256"):
        parse_object_type_catalog(payload, expected_version="2022.1")

    unsorted = build_object_type_catalog_payload(
        _source(),
        version="2022.1",
    )
    unsorted["types"].reverse()
    with pytest.raises(MetadataCatalogError, match="deterministic order"):
        parse_object_type_catalog(unsorted, expected_version="2022.1")

    forged_source = build_object_type_catalog_payload(
        _source(),
        version="2022.1",
    )
    forged_source["metadata"]["source_result_sha256"] = "0" * 64
    with pytest.raises(MetadataCatalogError, match="source_result_sha256"):
        parse_object_type_catalog(
            forged_source,
            expected_version="2022.1",
        )


def test_catalog_store_missing_version_resource_fails_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(MetadataCatalogMissingError):
        ObjectTypeCatalogStore(root=tmp_path).load("2022.1")


def test_maintenance_builder_supports_preview_write_and_check(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "get-types.json"
    evidence_path.write_text(json.dumps(_source()), encoding="utf-8")
    output_root = tmp_path / "catalogs"

    preview = build_catalog_file(
        version="2022.1",
        evidence_path=evidence_path,
        output_root=output_root,
    )
    assert preview["write_performed"] is False
    assert not Path(preview["output_path"]).exists()

    written = build_catalog_file(
        version="2022.1",
        evidence_path=evidence_path,
        output_root=output_root,
        write=True,
    )
    assert Path(written["output_path"]).is_file()

    checked = build_catalog_file(
        version="2022.1",
        evidence_path=evidence_path,
        output_root=output_root,
        check=True,
    )
    assert checked["checked"] is True

    evidence_path.write_text(
        json.dumps(
            {
                **_source(),
                "result": {
                    "return": [
                        {
                            "classId": 65552,
                            "name": "Different",
                            "type": "WObject",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ObjectTypeCatalogBuildError, match="stale"):
        build_catalog_file(
            version="2022.1",
            evidence_path=evidence_path,
            output_root=output_root,
            check=True,
        )
