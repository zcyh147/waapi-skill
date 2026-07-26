from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.authoring_ui_commands_manifest import (  # pyright: ignore[reportMissingImports]
    AUTHORING_HOST_SURFACE,
    AUTHORING_UI_COMMAND_FUNCTION_URIS,
    AUTHORING_UI_COMMAND_TOPIC_URIS,
    AUTHORING_UI_COMMAND_URIS,
    CONSOLE_HOST_SURFACE,
    AuthoringUiCommandsSupplement,
    AuthoringUiCommandsSupplementError,
    AuthoringUiCommandsSupplementMissingError,
    build_authoring_ui_commands_supplement,
    merge_authoring_ui_commands_surface,
)
from wwise_waapi.manifest import (  # pyright: ignore[reportMissingImports]
    GET_FUNCTIONS_URI,
    GET_TOPICS_URI,
    ManifestStore,
    build_manifest_from_caller,
)


VERSION = "2024.1"
BASE_URI = "ak.wwise.core.getInfo"


def _function(uri: str) -> dict[str, Any]:
    return {
        "reflection": {"uri": uri},
        "type": "function",
        "uri": uri,
    }


def _topic(uri: str) -> dict[str, Any]:
    return {
        "reflection": {"uri": uri},
        "type": "topic",
        "uri": uri,
    }


def _schema(uri: str, *, marker: str = "base") -> dict[str, Any]:
    return {
        "schema": {
            "uri": uri,
            "marker": marker,
        },
        "status": "ok",
        "uri": uri,
    }


def _manifest(
    *,
    functions: list[dict[str, Any]],
    topics: list[dict[str, Any]],
    schemas: list[dict[str, Any]],
    host_surface: str,
) -> dict[str, Any]:
    return {
        "audit": {"fixture": True},
        "functions": functions,
        "metadata": {
            "host_surface": host_surface,
            "wwise_build": "fixture",
            "wwise_version_target": VERSION,
        },
        "schemas": schemas,
        "topics": topics,
    }


def _console_without_ui_commands() -> dict[str, Any]:
    return _manifest(
        functions=[_function(BASE_URI)],
        topics=[],
        schemas=[_schema(BASE_URI)],
        host_surface=CONSOLE_HOST_SURFACE,
    )


def _authoring_with_ui_commands(
    *,
    execute_schema_marker: str = "authoring",
) -> dict[str, Any]:
    functions = [
        _function(BASE_URI),
        *[
            _function(uri)
            for uri in sorted(AUTHORING_UI_COMMAND_FUNCTION_URIS)
        ],
    ]
    topics = [
        _topic(uri) for uri in sorted(AUTHORING_UI_COMMAND_TOPIC_URIS)
    ]
    schemas = [_schema(BASE_URI)]
    schemas.extend(
        _schema(
            uri,
            marker=(
                execute_schema_marker
                if uri == "ak.wwise.ui.commands.execute"
                else "authoring"
            ),
        )
        for uri in sorted(AUTHORING_UI_COMMAND_URIS)
    )
    return _manifest(
        functions=functions,
        topics=topics,
        schemas=schemas,
        host_surface=AUTHORING_HOST_SURFACE,
    )


def _metadata() -> dict[str, Any]:
    return {
        "authoring_ui_commands_reflection_sha256": "0" * 64,
        "base_host_surface": CONSOLE_HOST_SURFACE,
        "console_reflection_inventory_sha256": "1" * 64,
        "host_surface": AUTHORING_HOST_SURFACE,
        "scope_uris": sorted(AUTHORING_UI_COMMAND_URIS),
        "surface_scope": "ak.wwise.ui.commands",
        "wwise_version_target": VERSION,
    }


def test_reflection_records_and_validates_host_surface() -> None:
    class EmptyReflectionCaller:
        def call(self, uri: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            if uri == GET_FUNCTIONS_URI:
                return {"functions": []}
            if uri == GET_TOPICS_URI:
                return {"topics": []}
            raise AssertionError(uri)

    reflected = build_manifest_from_caller(
        EmptyReflectionCaller(),
        version=VERSION,
        host_surface=AUTHORING_HOST_SURFACE,
    )

    assert reflected.metadata["host_surface"] == AUTHORING_HOST_SURFACE
    assert reflected.metadata["manifest_origin"] == "direct-reflection"
    with pytest.raises(ValueError, match="Unsupported reflection host surface"):
        build_manifest_from_caller(
            EmptyReflectionCaller(),
            version=VERSION,
            host_surface="unmarked-union",
        )


def test_console_load_stays_default_and_missing_explicit_supplement_fails() -> None:
    console = _console_without_ui_commands()
    store = ManifestStore()
    store.record(VERSION, console)

    assert store.load(VERSION) is console
    with pytest.raises(AuthoringUiCommandsSupplementMissingError):
        store.load_with_authoring_ui_commands(VERSION)


def test_added_functions_topic_and_schemas_are_explicitly_origin_marked() -> None:
    console = _console_without_ui_commands()
    supplement = build_authoring_ui_commands_supplement(
        console,
        _authoring_with_ui_commands(),
        version=VERSION,
    )

    assert {row["uri"] for row in supplement.functions} == (
        AUTHORING_UI_COMMAND_FUNCTION_URIS
    )
    assert {row["uri"] for row in supplement.topics} == (
        AUTHORING_UI_COMMAND_TOPIC_URIS
    )
    assert {row["uri"] for row in supplement.schemas} == (
        AUTHORING_UI_COMMAND_URIS
    )
    assert supplement.schema_overrides == []

    merged = merge_authoring_ui_commands_surface(console, supplement)
    functions = {row["uri"]: row for row in merged["functions"]}
    topics = {row["uri"]: row for row in merged["topics"]}

    assert functions[BASE_URI]["host_surface"] == CONSOLE_HOST_SURFACE
    assert functions[BASE_URI]["manifest_origin"] == "console-manifest"
    for uri in AUTHORING_UI_COMMAND_FUNCTION_URIS:
        assert functions[uri]["host_surface"] == AUTHORING_HOST_SURFACE
        assert (
            functions[uri]["manifest_origin"]
            == "authoring-ui-commands-supplement"
        )
    assert (
        topics["ak.wwise.ui.commands.executed"]["host_surface"]
        == AUTHORING_HOST_SURFACE
    )
    assert merged["metadata"]["full_authoring_inventory_reflected"] is False
    assert (
        merged["metadata"]["surface_profile"]
        == "console-with-authoring-ui-commands"
    )


def test_changed_common_schema_is_an_authoring_override() -> None:
    authoring = _authoring_with_ui_commands(
        execute_schema_marker="authoring-v2"
    )
    console = deepcopy(authoring)
    console["metadata"]["host_surface"] = CONSOLE_HOST_SURFACE
    for row in console["schemas"]:
        if row["uri"] == "ak.wwise.ui.commands.execute":
            row["schema"]["marker"] = "console-v1"

    supplement = build_authoring_ui_commands_supplement(
        console,
        authoring,
        version=VERSION,
    )
    assert supplement.functions == []
    assert supplement.topics == []
    assert [row["uri"] for row in supplement.schema_overrides] == [
        "ak.wwise.ui.commands.execute"
    ]

    merged = merge_authoring_ui_commands_surface(console, supplement)
    schemas = {row["uri"]: row for row in merged["schemas"]}
    execute = schemas["ak.wwise.ui.commands.execute"]
    assert execute["schema"]["marker"] == "authoring-v2"
    assert execute["host_surface"] == AUTHORING_HOST_SURFACE
    assert (
        execute["manifest_origin"]
        == "authoring-ui-commands-schema-override"
    )


def test_duplicate_and_out_of_scope_rows_fail_closed() -> None:
    execute = _function("ak.wwise.ui.commands.execute")
    execute_schema = _schema("ak.wwise.ui.commands.execute")
    with pytest.raises(
        AuthoringUiCommandsSupplementError,
        match="duplicate URI",
    ):
        AuthoringUiCommandsSupplement(
            version=VERSION,
            metadata=_metadata(),
            functions=[execute, execute],
            schemas=[execute_schema],
        )

    with pytest.raises(
        AuthoringUiCommandsSupplementError,
        match="outside its fixed scope",
    ):
        AuthoringUiCommandsSupplement(
            version=VERSION,
            metadata=_metadata(),
            functions=[_function("ak.wwise.core.object.get")],
            schemas=[_schema("ak.wwise.core.object.get")],
        )

    with pytest.raises(
        AuthoringUiCommandsSupplementError,
        match="schemas must match",
    ):
        AuthoringUiCommandsSupplement(
            version=VERSION,
            metadata=_metadata(),
            functions=[execute],
            schemas=[],
        )


def test_same_count_uri_substitution_changes_digest_and_stale_audit_fails() -> None:
    execute = AuthoringUiCommandsSupplement(
        version=VERSION,
        metadata=_metadata(),
        functions=[_function("ak.wwise.ui.commands.execute")],
        schemas=[_schema("ak.wwise.ui.commands.execute")],
    )
    register = AuthoringUiCommandsSupplement(
        version=VERSION,
        metadata=_metadata(),
        functions=[_function("ak.wwise.ui.commands.register")],
        schemas=[_schema("ak.wwise.ui.commands.register")],
    )

    assert execute.audit.added_function_count == register.audit.added_function_count
    assert execute.audit.added_schema_count == register.audit.added_schema_count
    assert execute.audit.inventory_sha256 != register.audit.inventory_sha256

    tampered = execute.as_dict()
    tampered["functions"] = register.functions
    tampered["schemas"] = register.schemas
    with pytest.raises(
        AuthoringUiCommandsSupplementError,
        match="audit or inventory digest",
    ):
        AuthoringUiCommandsSupplement.from_dict(tampered)


def test_store_round_trip_is_versioned_and_deterministic(tmp_path) -> None:
    console = _console_without_ui_commands()
    supplement = build_authoring_ui_commands_supplement(
        console,
        _authoring_with_ui_commands(),
        version=VERSION,
    )
    store = ManifestStore(root=tmp_path)
    store.record(VERSION, console)

    path = store.write_authoring_ui_commands_supplement(supplement)
    loaded = store.load_authoring_ui_commands_supplement(VERSION)

    assert path == (
        tmp_path / VERSION / "authoring-ui-commands-supplement.json"
    )
    assert loaded is not None
    assert loaded.as_dict() == supplement.as_dict()
