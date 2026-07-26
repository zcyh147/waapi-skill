from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_import import (  # pyright: ignore[reportMissingImports]
    AUDIO_IMPORT_PLAN_CONTRACT,
    AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS,
    MAX_IMPORT_ITEMS,
    MAX_TAB_ROWS,
    SUPPORTED_WWISE_VERSIONS,
    TAB_IMPORT_PLAN_CONTRACT,
    ImportContractError,
    build_audio_import_plan,
    canonical_import_target,
    import_operation_policy,
    parse_tab_delimited_import_file,
    regular_file_proof,
    unsupported_localized_existing_fields,
    verify_regular_file_proof,
)


OLD_ROOT = r"\Actor-Mixer Hierarchy\Default Work Unit"
NEW_ROOT = r"\Containers\Default Work Unit"


def _write_media(root: Path, name: str = "source.wav", content: bytes = b"RIFF-test-WAVE") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_tsv(root: Path, headers: list[str], rows: list[list[str]], name: str = "import.tsv") -> Path:
    path = root / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)
    return path


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
@pytest.mark.parametrize("operation", ["createNew", "useExisting", "replaceExisting"])
def test_operation_policy_is_closed_for_every_supported_lane(version: str, operation: str, tmp_path: Path) -> None:
    root = NEW_ROOT if version == "2025.1" else OLD_ROOT
    media = _write_media(tmp_path, f"{version}-{operation}.wav")

    plan = build_audio_import_plan(
        [{"object_path": rf"{root}\Import_{operation}", "audio_file": str(media)}],
        version=version,
        import_operation=operation,
    )

    assert plan["contract"] == AUDIO_IMPORT_PLAN_CONTRACT
    assert plan["operation_policy"] == import_operation_policy(operation)
    assert plan["operation_policy"]["automatic_retry"] is False
    assert plan["dispatch_args"]["importOperation"] == operation
    assert plan["dispatch_args"]["autoAddToSourceControl"] is False
    if version in {"2023.1", "2024.1", "2025.1"}:
        assert plan["dispatch_args"]["autoCheckOutToSourceControl"] is False
        assert plan["oracle"]["result_contract"] == "required_log_files_objects"
    else:
        assert "autoCheckOutToSourceControl" not in plan["dispatch_args"]
        assert plan["oracle"]["result_contract"] == "objects_only"
    json.dumps(plan)


@pytest.mark.parametrize("version", AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS)
@pytest.mark.parametrize("enabled", [False, True])
def test_audio_import_exposes_versioned_auto_check_out(
    version: str,
    enabled: bool,
    tmp_path: Path,
) -> None:
    root = NEW_ROOT if version == "2025.1" else OLD_ROOT
    media = _write_media(tmp_path, f"audio-checkout-{version}-{enabled}.wav")

    plan = build_audio_import_plan(
        [{"object_path": root + r"\CheckoutTarget", "audio_file": str(media)}],
        version=version,
        import_operation="createNew",
        auto_check_out_to_source_control=enabled,
    )

    assert plan["dispatch_args"]["autoCheckOutToSourceControl"] is enabled


@pytest.mark.parametrize("version", AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS)
@pytest.mark.parametrize("enabled", [False, True])
def test_tab_import_exposes_versioned_auto_check_out(
    version: str,
    enabled: bool,
    tmp_path: Path,
) -> None:
    root = NEW_ROOT if version == "2025.1" else OLD_ROOT
    media = _write_media(tmp_path, f"tab-checkout-{version}-{enabled}.wav")
    tsv = _write_tsv(
        tmp_path,
        ["Audio File", "Object Path"],
        [[str(media), "CheckoutTarget"]],
        name=f"checkout-{version}-{enabled}.tsv",
    )

    plan = parse_tab_delimited_import_file(
        tsv,
        version=version,
        import_location=root,
        import_language="SFX",
        import_operation="createNew",
        auto_check_out_to_source_control=enabled,
    )

    assert plan["dispatch_args"]["autoCheckOutToSourceControl"] is enabled


@pytest.mark.parametrize("version", ["2021.1", "2022.1"])
@pytest.mark.parametrize("enabled", [False, True])
def test_audio_import_rejects_explicit_auto_check_out_in_old_lanes(
    version: str,
    enabled: bool,
    tmp_path: Path,
) -> None:
    media = _write_media(tmp_path, f"old-audio-checkout-{version}-{enabled}.wav")

    with pytest.raises(ImportContractError) as caught:
        build_audio_import_plan(
            [{"object_path": OLD_ROOT + r"\CheckoutTarget", "audio_file": str(media)}],
            version=version,
            import_operation="createNew",
            auto_check_out_to_source_control=enabled,
        )

    assert caught.value.error_code == "VERSION_BEHAVIOR_BOUNDARY"


@pytest.mark.parametrize("version", ["2021.1", "2022.1"])
@pytest.mark.parametrize("enabled", [False, True])
def test_tab_import_rejects_explicit_auto_check_out_in_old_lanes(
    version: str,
    enabled: bool,
    tmp_path: Path,
) -> None:
    media = _write_media(tmp_path, f"old-tab-checkout-{version}-{enabled}.wav")
    tsv = _write_tsv(
        tmp_path,
        ["Audio File", "Object Path"],
        [[str(media), "CheckoutTarget"]],
        name=f"old-checkout-{version}-{enabled}.tsv",
    )

    with pytest.raises(ImportContractError) as caught:
        parse_tab_delimited_import_file(
            tsv,
            version=version,
            import_location=OLD_ROOT,
            import_language="SFX",
            import_operation="createNew",
            auto_check_out_to_source_control=enabled,
        )

    assert caught.value.error_code == "VERSION_BEHAVIOR_BOUNDARY"


@pytest.mark.parametrize("value", [0, 1, "true"])
def test_import_auto_check_out_requires_a_json_boolean(value: Any, tmp_path: Path) -> None:
    media = _write_media(tmp_path, f"invalid-checkout-{value}.wav")

    with pytest.raises(ImportContractError) as caught:
        build_audio_import_plan(
            [{"object_path": OLD_ROOT + r"\CheckoutTarget", "audio_file": str(media)}],
            version="2023.1",
            import_operation="createNew",
            auto_check_out_to_source_control=value,
        )

    assert caught.value.error_code == "INVALID_ARGUMENT"


def test_audio_import_plan_normalizes_structured_fields_and_provenance(tmp_path: Path) -> None:
    media = _write_media(tmp_path, "对白 01.wav", b"dialogue-v2")
    plan = build_audio_import_plan(
        [
            {
                "object_path": OLD_ROOT + r"\<Random Container>Dialogue\<Sound Voice>Line_01",
                "audio_file": str(media),
                "object_type": "Sound Voice",
                "import_language": "Japanese",
                "originals_subfolder": "Chapter06/Japanese",
                "notes": "修订对白",
                "audio_source_notes": "take 2",
                "event": {"path": r"\Events\Default Work Unit\Dialogue\Play_Line_01", "action": "Play"},
            }
        ],
        version="2022.1",
        import_operation="useExisting",
    )

    row = plan["dispatch_args"]["imports"][0]
    assert row == {
        "objectPath": OLD_ROOT + r"\<Random Container>Dialogue\<Sound Voice>Line_01",
        "audioFile": str(media.resolve()),
        "objectType": "Sound Voice",
        "importLanguage": "Japanese",
        "originalsSubFolder": r"Chapter06\Japanese",
        "notes": "修订对白",
        "audioSourceNotes": "take 2",
        "event": r"\Events\Default Work Unit\Dialogue\Play_Line_01@Play",
    }
    oracle = plan["oracle"]["targets"][0]
    assert oracle["canonical_target_path"] == OLD_ROOT + r"\Dialogue\Line_01"
    assert oracle["canonical_parent_path"] == OLD_ROOT + r"\Dialogue"
    assert oracle["expected_audio_file_source_result_path"] == (
        OLD_ROOT + r"\Dialogue\Line_01\对白 01"
    )
    assert oracle["requested_event"] == {
        "path": r"\Events\Default Work Unit\Dialogue\Play_Line_01",
        "action": "Play",
    }
    assert oracle["source_file"]["sha256"] == regular_file_proof(media, field="media")["sha256"]
    assert plan["oracle"]["language_requires_live_project_validation"] is True


def test_audio_import_language_validation_exempts_sfx_but_not_mixed_localized_rows(
    tmp_path: Path,
) -> None:
    media = _write_media(tmp_path, "language-policy.wav")
    sfx_plan = build_audio_import_plan(
        [
            {
                "object_path": OLD_ROOT + r"\SfxTarget",
                "audio_file": str(media),
                "import_language": "sfx",
            }
        ],
        version="2022.1",
        import_operation="createNew",
    )

    assert sfx_plan["dispatch_args"]["imports"][0]["importLanguage"] == "SFX"
    assert sfx_plan["oracle"]["language_requires_live_project_validation"] is False

    mixed_plan = build_audio_import_plan(
        [
            {
                "object_path": OLD_ROOT + r"\SfxTarget",
                "audio_file": str(media),
                "import_language": "SFX",
            },
            {
                "object_path": OLD_ROOT + r"\JapaneseTarget",
                "audio_file": str(media),
                "import_language": "Japanese",
            },
        ],
        version="2022.1",
        import_operation="createNew",
    )

    assert mixed_plan["oracle"]["language_requires_live_project_validation"] is True


def test_audio_import_plan_rejects_open_ended_fields_and_raw_event(tmp_path: Path) -> None:
    media = _write_media(tmp_path)
    base = {"object_path": OLD_ROOT + r"\Target", "audio_file": str(media)}

    for unsupported in ("switchAssignation", "dialogueEvent", "@Volume", "properties"):
        with pytest.raises(ImportContractError) as caught:
            build_audio_import_plan(
                [base | {unsupported: "unsafe"}],
                version="2022.1",
                import_operation="createNew",
            )
        assert caught.value.error_code == "INVALID_ARGUMENT"
        assert unsupported in caught.value.details["unsupported"]

    with pytest.raises(ImportContractError) as raw_event:
        build_audio_import_plan(
            [base | {"event": r"\Events\Default Work Unit\Play_Target@Play"}],
            version="2022.1",
            import_operation="createNew",
        )
    assert raw_event.value.error_code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("originals_subfolder", "../escape"),
        ("originals_subfolder", r"C:\escape"),
        ("import_language", "  "),
        ("object_type", "MadeUpContainer"),
        ("event", {"path": r"\Events\Default Work Unit\Bad", "action": "Delete"}),
    ],
)
def test_audio_import_plan_rejects_invalid_structured_values(
    field: str,
    value: object,
    tmp_path: Path,
) -> None:
    media = _write_media(tmp_path)
    with pytest.raises(ImportContractError):
        build_audio_import_plan(
            [{"object_path": OLD_ROOT + r"\Target", "audio_file": str(media), field: value}],
            version="2022.1",
            import_operation="createNew",
        )


def test_audio_import_plan_rejects_duplicate_targets_and_item_limit(tmp_path: Path) -> None:
    media = _write_media(tmp_path)
    first = {"object_path": OLD_ROOT + r"\<Sound SFX>Target", "audio_file": str(media)}
    duplicate = {"object_path": OLD_ROOT + r"\target", "audio_file": str(media)}
    with pytest.raises(ImportContractError) as duplicate_error:
        build_audio_import_plan([first, duplicate], version="2022.1", import_operation="createNew")
    assert duplicate_error.value.error_code == "DUPLICATE_TARGET"

    with pytest.raises(ImportContractError) as limit:
        build_audio_import_plan(
            [first] * (MAX_IMPORT_ITEMS + 1),
            version="2022.1",
            import_operation="createNew",
        )
    assert limit.value.error_code == "LIMIT_EXCEEDED"


def test_regular_file_proof_rejects_relative_missing_directory_and_symlink(tmp_path: Path) -> None:
    media = _write_media(tmp_path)
    with pytest.raises(ImportContractError) as relative:
        regular_file_proof("relative.wav", field="media")
    assert relative.value.error_code == "INVALID_FILE"
    with pytest.raises(ImportContractError) as missing:
        regular_file_proof(tmp_path / "missing.wav", field="media")
    assert missing.value.error_code == "INPUT_FILE_NOT_FOUND"
    with pytest.raises(ImportContractError) as directory:
        regular_file_proof(tmp_path, field="media")
    assert directory.value.error_code == "INVALID_FILE"

    link = tmp_path / "link.wav"
    link.symlink_to(media)
    with pytest.raises(ImportContractError) as symlink:
        regular_file_proof(link, field="media")
    assert symlink.value.error_code == "INVALID_FILE"


def test_regular_file_proof_detects_preview_drift(tmp_path: Path) -> None:
    media = _write_media(tmp_path, content=b"before")
    proof = regular_file_proof(media, field="media")
    assert verify_regular_file_proof(proof, field="media") == proof

    media.write_bytes(b"after")
    with pytest.raises(ImportContractError) as drift:
        verify_regular_file_proof(proof, field="media")
    assert drift.value.error_code == "FILE_CHANGED"


def test_tab_parser_derives_unicode_oracle_from_file_bytes(tmp_path: Path) -> None:
    media = _write_media(tmp_path, "森林 夜晚.wav", b"forest-night")
    headers = [
        "Audio File",
        "Object Path",
        "Object Type",
        "OriginalsSubFolder",
        "Notes",
        "Audio Source Notes",
        "Event",
    ]
    tsv = _write_tsv(
        tmp_path,
        headers,
        [
            [
                str(media),
                r"Forest\<Random Container>Night\<Sound SFX>Owl",
                "Sound SFX",
                "Ambience/Forest",
                "夜间·远景",
                "录音：东京",
                r"\Events\Default Work Unit\Ambience\Play_Owl@Play",
            ]
        ],
    )

    plan = parse_tab_delimited_import_file(
        tsv,
        version="2022.1",
        import_location=OLD_ROOT + r"\Ambience",
        import_language="SFX",
        import_operation="useExisting",
    )

    assert plan["contract"] == TAB_IMPORT_PLAN_CONTRACT
    assert plan["dispatch_args"] == {
        "importFile": str(tsv.resolve()),
        "importLocation": OLD_ROOT + r"\Ambience",
        "importLanguage": "SFX",
        "importOperation": "useExisting",
        "autoAddToSourceControl": False,
    }
    assert plan["rows"][0]["canonical_target_path"] == OLD_ROOT + r"\Ambience\Forest\Night\Owl"
    assert plan["rows"][0]["notes"] == "夜间·远景"
    assert plan["rows"][0]["event"] == {
        "path": r"\Events\Default Work Unit\Ambience\Play_Owl",
        "action": "Play",
    }
    assert plan["oracle"]["derived_from"]["caller_expected_rows_accepted"] is False
    assert plan["oracle"]["language_requires_live_project_validation"] is False
    assert plan["oracle"]["missing_or_unreadable_source_policy"] == "reject_before_preview_and_dispatch"
    assert plan["oracle"]["targets"][0]["source_file"]["sha256"] == regular_file_proof(media, field="media")["sha256"]
    assert plan["oracle"]["targets"][0][
        "expected_audio_file_source_result_path"
    ] == OLD_ROOT + r"\Ambience\Forest\Night\Owl\森林 夜晚"
    json.dumps(plan)


@pytest.mark.parametrize("notes", ["夜间\t远景", "夜间\n远景"])
def test_tab_parser_rejects_csv_quoted_physical_separators_before_dispatch(
    notes: str,
    tmp_path: Path,
) -> None:
    media = _write_media(tmp_path, "quoted-separator.wav")
    tsv = _write_tsv(
        tmp_path,
        ["Audio File", "Object Path", "Notes"],
        [[str(media), "Target", notes]],
        name="quoted-separator.tsv",
    )

    with pytest.raises(ImportContractError) as caught:
        parse_tab_delimited_import_file(
            tsv,
            version="2022.1",
            import_location=OLD_ROOT,
            import_language="SFX",
            import_operation="createNew",
    )

    assert caught.value.error_code == "INVALID_TAB_FILE"
    assert "CSV-style quoted separators" in str(caught.value)
    assert caught.value.details["mismatches"]


def test_tab_parser_requires_live_language_validation_only_for_localized_rows(
    tmp_path: Path,
) -> None:
    media = _write_media(tmp_path, "localized.wav")
    tsv = _write_tsv(
        tmp_path,
        ["Audio File", "Object Path"],
        [[str(media), "LocalizedTarget"]],
    )

    localized = parse_tab_delimited_import_file(
        tsv,
        version="2022.1",
        import_location=OLD_ROOT,
        import_language="Japanese",
        import_operation="createNew",
    )

    assert localized["oracle"]["language_requires_live_project_validation"] is True


def test_tab_parser_supports_exact_absolute_target_and_2025_root(tmp_path: Path) -> None:
    media = _write_media(tmp_path)
    tsv = _write_tsv(
        tmp_path,
        ["Object Path", "Audio File"],
        [[NEW_ROOT + r"\Imported", str(media)]],
    )

    plan = parse_tab_delimited_import_file(
        tsv,
        version="2025.1",
        import_location=NEW_ROOT,
        import_language="SFX",
        import_operation="createNew",
    )

    assert plan["oracle"]["targets"][0]["canonical_target_path"] == NEW_ROOT + r"\Imported"
    assert plan["dispatch_args"]["autoCheckOutToSourceControl"] is False


@pytest.mark.parametrize(
    "unsupported_header",
    [
        "Originals Sub Folder",
        "Import Language",
        "Switch Assignation",
        "Dialogue Event",
        "@Volume",
        "Property[Volume]",
        "Reference[Output Bus]",
    ],
)
def test_tab_parser_rejects_unreviewed_columns(unsupported_header: str, tmp_path: Path) -> None:
    media = _write_media(tmp_path)
    tsv = _write_tsv(
        tmp_path,
        ["Audio File", "Object Path", unsupported_header],
        [[str(media), "Target", "value"]],
    )

    with pytest.raises(ImportContractError) as caught:
        parse_tab_delimited_import_file(
            tsv,
            version="2022.1",
            import_location=OLD_ROOT,
            import_language="SFX",
            import_operation="createNew",
        )
    assert caught.value.error_code == "UNSUPPORTED_COLUMN"
    assert unsupported_header in caught.value.details["unsupported"]


def test_tab_parser_rejects_missing_duplicate_and_malformed_headers(tmp_path: Path) -> None:
    media = _write_media(tmp_path)
    missing = _write_tsv(tmp_path, ["Object Path"], [["Target"]], name="missing.tsv")
    duplicate = _write_tsv(
        tmp_path,
        ["Audio File", "Audio File", "Object Path"],
        [[str(media), str(media), "Target"]],
        name="duplicate.tsv",
    )

    for path in (missing, duplicate):
        with pytest.raises(ImportContractError) as caught:
            parse_tab_delimited_import_file(
                path,
                version="2022.1",
                import_location=OLD_ROOT,
                import_language="SFX",
                import_operation="createNew",
            )
        assert caught.value.error_code == "INVALID_TAB_FILE"


def test_tab_parser_rejects_bom_invalid_utf8_and_malformed_column_count(tmp_path: Path) -> None:
    bom = tmp_path / "bom.tsv"
    bom.write_bytes(b"\xef\xbb\xbfAudio File\tObject Path\n/x.wav\tTarget\n")
    invalid = tmp_path / "invalid.tsv"
    invalid.write_bytes(b"Audio File\tObject Path\n\xff\tTarget\n")
    malformed = tmp_path / "malformed.tsv"
    malformed.write_text("Audio File\tObject Path\nonly-one-cell\n", encoding="utf-8")

    for path, code in ((bom, "INVALID_ENCODING"), (invalid, "INVALID_ENCODING"), (malformed, "INVALID_TAB_FILE")):
        with pytest.raises(ImportContractError) as caught:
            parse_tab_delimited_import_file(
                path,
                version="2022.1",
                import_location=OLD_ROOT,
                import_language="SFX",
                import_operation="createNew",
            )
        assert caught.value.error_code == code


def test_tab_parser_rejects_relative_missing_and_symlink_media_before_dispatch(tmp_path: Path) -> None:
    media = _write_media(tmp_path)
    link = tmp_path / "linked.wav"
    link.symlink_to(media)
    cases = [
        ("relative.wav", "INVALID_FILE"),
        (str(tmp_path / "missing.wav"), "INPUT_FILE_NOT_FOUND"),
        (str(link), "INVALID_FILE"),
    ]
    for index, (audio_file, error_code) in enumerate(cases):
        tsv = _write_tsv(
            tmp_path,
            ["Audio File", "Object Path"],
            [[audio_file, f"Target_{index}"]],
            name=f"invalid-media-{index}.tsv",
        )
        with pytest.raises(ImportContractError) as caught:
            parse_tab_delimited_import_file(
                tsv,
                version="2022.1",
                import_location=OLD_ROOT,
                import_language="SFX",
                import_operation="createNew",
            )
        assert caught.value.error_code == error_code


def test_tab_parser_rejects_duplicate_targets_and_too_many_rows(tmp_path: Path) -> None:
    media = _write_media(tmp_path)
    duplicate = _write_tsv(
        tmp_path,
        ["Audio File", "Object Path"],
        [[str(media), "Target"], [str(media), "target"]],
        name="duplicate-target.tsv",
    )
    with pytest.raises(ImportContractError) as caught:
        parse_tab_delimited_import_file(
            duplicate,
            version="2022.1",
            import_location=OLD_ROOT,
            import_language="SFX",
            import_operation="createNew",
        )
    assert caught.value.error_code == "DUPLICATE_TARGET"

    too_many = _write_tsv(
        tmp_path,
        ["Audio File", "Object Path"],
        [[str(media), f"Target_{index}"] for index in range(MAX_TAB_ROWS + 1)],
        name="too-many.tsv",
    )
    with pytest.raises(ImportContractError) as limit:
        parse_tab_delimited_import_file(
            too_many,
            version="2022.1",
            import_location=OLD_ROOT,
            import_language="SFX",
            import_operation="createNew",
        )
    assert limit.value.error_code == "LIMIT_EXCEEDED"


def test_versioned_hierarchy_roots_do_not_cross_lanes(tmp_path: Path) -> None:
    media = _write_media(tmp_path)
    with pytest.raises(ImportContractError) as old_lane:
        build_audio_import_plan(
            [{"object_path": NEW_ROOT + r"\Target", "audio_file": str(media)}],
            version="2022.1",
            import_operation="createNew",
        )
    assert old_lane.value.error_code == "INVALID_TARGET"

    with pytest.raises(ImportContractError) as new_lane:
        canonical_import_target(OLD_ROOT + r"\Target", version="2025.1")
    assert new_lane.value.error_code == "INVALID_TARGET"


def test_replace_existing_truthfully_requires_disposable_project() -> None:
    replace = import_operation_policy("replaceExisting")
    use = import_operation_policy("useExisting")

    assert replace["disposable_project_required"] is True
    assert replace["owned_project_copy_required_for_clean_test"] is True
    assert replace["in_place_restore_supported"] is False
    assert replace["existing_target_postcondition"] == "old_guid_absent_and_new_guid_distinct"
    assert use["disposable_project_required"] is False
    assert use["owned_project_copy_required_for_clean_test"] is True
    assert use["in_place_restore_supported"] is False
    assert use["existing_target_postcondition"] == "guid_preserved_and_media_source_updated"
    assert use["notes_destination_policy"] == (
        "preexisting_target_routes_notes_to_new_audio_file_source;"
        "absent_target_routes_notes_to_created_target"
    )


@pytest.mark.parametrize(
    ("language", "subfolder", "notes", "source_notes", "event", "expected"),
    [
        ("Japanese", True, False, False, False, ("originals_subfolder",)),
        ("English(US)", False, True, False, False, ("notes",)),
        ("Japanese", False, False, True, False, ("audio_source_notes",)),
        ("English(US)", False, False, False, True, ("event",)),
        (
            "Chinese(PRC)",
            True,
            True,
            True,
            True,
            ("originals_subfolder", "notes", "audio_source_notes", "event"),
        ),
        ("SFX", True, True, True, True, ()),
        (None, True, True, True, True, ()),
    ],
)
def test_localized_existing_boundary_rejects_every_unproven_wire_field(
    language: object,
    subfolder: bool,
    notes: bool,
    source_notes: bool,
    event: bool,
    expected: tuple[str, ...],
) -> None:
    assert unsupported_localized_existing_fields(
        import_language=language,
        originals_subfolder_supplied=subfolder,
        notes_supplied=notes,
        audio_source_notes_supplied=source_notes,
        event_supplied=event,
    ) == expected


def test_tab_file_proof_detects_file_replacement(tmp_path: Path) -> None:
    media = _write_media(tmp_path)
    tsv = _write_tsv(tmp_path, ["Audio File", "Object Path"], [[str(media), "Target"]])
    plan = parse_tab_delimited_import_file(
        tsv,
        version="2022.1",
        import_location=OLD_ROOT,
        import_language="SFX",
        import_operation="createNew",
    )
    old_proof = plan["import_file_proof"]

    replacement = tmp_path / "replacement.tsv"
    replacement.write_text(tsv.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    os.replace(replacement, tsv)
    with pytest.raises(ImportContractError) as changed:
        verify_regular_file_proof(old_proof, field="import_file")
    assert changed.value.error_code == "FILE_CHANGED"
