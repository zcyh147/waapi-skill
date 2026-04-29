from __future__ import annotations

import json
from typing import Any

from wwise_waapi.manifest import (  # pyright: ignore[reportMissingImports]
    GET_FUNCTIONS_URI,
    GET_SCHEMA_URI,
    GET_TOPICS_URI,
    ManifestStore,
    SchemaFetchResult,
    WaapiReflectionClient,
    audit_manifest,
    build_manifest_from_caller,
)


class PartiallyFailingSchemaCaller:
    def call(self, uri: str, args: dict[str, str] | None = None) -> Any:
        if uri == GET_FUNCTIONS_URI:
            return {"functions": [{"uri": "ak.function.ok"}, {"uri": "ak.function.fail"}]}
        if uri == GET_TOPICS_URI:
            return {"topics": [{"uri": "ak.topic.ok"}]}
        if uri == GET_SCHEMA_URI:
            assert args is not None
            if args["uri"] == "ak.function.fail":
                raise RuntimeError("fixture schema unavailable")
            return {"schemaFor": args["uri"]}
        raise AssertionError(f"unexpected uri: {uri}")


def test_store_writes_loads_and_audits_versioned_manifest(tmp_path) -> None:
    manifest = build_manifest_from_caller(
        PartiallyFailingSchemaCaller(),
        inventory_source="fixture-reflection",
        wwise_build="fixture-build",
    )
    store = ManifestStore(root=tmp_path)

    written = store.write_manifest(manifest)
    loaded = store.load("2022.1")
    audit = audit_manifest(loaded)

    assert {path.name for path in written} == {"manifest.json", "functions.json", "topics.json", "schemas.json"}
    assert audit.counts_match is True
    assert audit.manifest_function_count == 2
    assert audit.manifest_topic_count == 1
    assert audit.schema_count == 3
    assert audit.schema_failure_count == 1
    assert loaded["metadata"]["inventory_source"] == "fixture-reflection"


def test_resource_file_payloads_include_top_level_metadata(tmp_path) -> None:
    manifest = build_manifest_from_caller(
        PartiallyFailingSchemaCaller(),
        inventory_source="fixture-reflection",
        wwise_build="fixture-build",
    )
    ManifestStore(root=tmp_path).write_manifest(manifest)

    for filename, payload_key in (
        ("functions.json", "functions"),
        ("topics.json", "topics"),
        ("schemas.json", "schemas"),
    ):
        payload = json.loads((tmp_path / "2022.1" / filename).read_text(encoding="utf-8"))
        assert payload["metadata"]["wwise_version_target"] == "2022.1"
        assert payload["metadata"]["inventory_source"] == "fixture-reflection"
        assert payload_key in payload


def test_schema_failures_are_explicit_in_generated_snapshot(tmp_path) -> None:
    manifest = build_manifest_from_caller(PartiallyFailingSchemaCaller(), inventory_source="fixture-reflection")
    store = ManifestStore(root=tmp_path)
    store.write_manifest(manifest)

    schemas = json.loads((tmp_path / "2022.1" / "schemas.json").read_text(encoding="utf-8"))["schemas"]
    failed = [schema for schema in schemas if schema["status"] == "error"]

    assert failed == [
        {
            "error_type": "RuntimeError",
            "message": "fixture schema unavailable",
            "status": "error",
            "uri": "ak.function.fail",
        }
    ]


def test_placeholder_versions_are_gitkeep_only(tmp_path) -> None:
    store = ManifestStore(root=tmp_path)
    paths = store.ensure_placeholder_versions(["2023", "2024", "2025"])

    assert [path.relative_to(tmp_path).as_posix() for path in paths] == [
        "2023/.gitkeep",
        "2024/.gitkeep",
        "2025/.gitkeep",
    ]
    assert store.load("2023") == {}


def test_legacy_in_memory_record_load_contract_still_works() -> None:
    store = ManifestStore()
    store.record("2022.1", {"functions": []})

    assert store.load("2022.1") == {"functions": []}


def test_in_memory_store_write_and_placeholder_noop_contracts() -> None:
    manifest = build_manifest_from_caller(PartiallyFailingSchemaCaller(), inventory_source="fixture-reflection")
    store = ManifestStore()

    assert store.write_manifest(manifest) == []
    assert store.ensure_placeholder_versions(["2023"]) == []
    assert store.load("2022.1")["audit"]["schema_failure_count"] == 1


def test_store_load_returns_memory_fallback_when_filesystem_manifest_missing(tmp_path) -> None:
    store = ManifestStore(root=tmp_path)
    store.record("2022.1", {"from_memory": True})

    assert store.load("2022.1") == {"from_memory": True}


def test_store_load_tolerates_partial_resource_files(tmp_path) -> None:
    version_dir = tmp_path / "2022.1"
    version_dir.mkdir(parents=True)
    (version_dir / "manifest.json").write_text('{"audit": {}, "metadata": {}}\n', encoding="utf-8")
    (version_dir / "functions.json").write_text('{"metadata": {}, "functions": [{"uri": "ak.only"}]}\n', encoding="utf-8")

    loaded = ManifestStore(root=tmp_path).load("2022.1")

    assert loaded["functions"] == [{"uri": "ak.only"}]
    assert "topics" not in loaded
    assert "schemas" not in loaded


def test_existing_placeholder_file_is_preserved(tmp_path) -> None:
    placeholder = tmp_path / "2023" / ".gitkeep"
    placeholder.parent.mkdir()
    placeholder.write_text("", encoding="utf-8")

    paths = ManifestStore(root=tmp_path).ensure_placeholder_versions(["2023"])

    assert paths == [placeholder]
    assert placeholder.read_text(encoding="utf-8") == ""


def test_schema_error_defaults_are_explicit() -> None:
    result = SchemaFetchResult(uri="ak.schema.missing", status="error")

    assert result.as_manifest_entry() == {
        "error_type": "SchemaFetchError",
        "message": "schema fetch failed",
        "status": "error",
        "uri": "ak.schema.missing",
    }


def test_reflection_client_accepts_list_return_values_and_string_entries() -> None:
    class ListCaller:
        def call(self, uri: str, args: dict[str, str] | None = None) -> Any:
            if uri == GET_FUNCTIONS_URI:
                return ["ak.string.entry"]
            if uri == GET_TOPICS_URI:
                return {"return": [{"name": "ak.named.topic"}]}
            if uri == GET_SCHEMA_URI:
                return {"schemaFor": args["uri"]}  # type: ignore[index]
            raise AssertionError(uri)

    client = WaapiReflectionClient(ListCaller())

    assert client.get_functions()[0].reflection == {"uri": "ak.string.entry"}
    assert client.get_topics()[0].uri == "ak.named.topic"


def test_reflection_client_rejects_malformed_inventory() -> None:
    class MalformedCaller:
        def __init__(self, result: Any) -> None:
            self.result = result

        def call(self, uri: str, args: dict[str, str] | None = None) -> Any:
            return self.result

    import pytest  # pyright: ignore[reportMissingImports]

    with pytest.raises(ValueError, match="did not include a list"):
        WaapiReflectionClient(MalformedCaller({"functions": {}})).get_functions()
    with pytest.raises(ValueError, match="missing a URI"):
        WaapiReflectionClient(MalformedCaller({"functions": [{"displayName": "No URI"}]})).get_functions()
    with pytest.raises(ValueError, match="Unsupported reflection entry"):
        WaapiReflectionClient(MalformedCaller({"functions": [object()]})).get_functions()


def test_audit_manifest_defaults_to_current_counts_when_audit_missing() -> None:
    audit = audit_manifest(
        {
            "functions": [{"uri": "ak.function"}],
            "topics": [{"uri": "ak.topic"}],
            "schemas": [{"status": "ok"}, {"status": "error"}],
        }
    )

    assert audit.reflected_function_count == 1
    assert audit.reflected_topic_count == 1
    assert audit.schema_failure_count == 1
