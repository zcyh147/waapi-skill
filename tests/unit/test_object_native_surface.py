from __future__ import annotations

import base64
from collections import deque
from pathlib import Path
from typing import Any, Mapping

import pytest

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    OperationContractError,
    _read_object_list_rows_with_evidence,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
    verify_prepared_operation,
)


OWNER_ID = "{41000000-0000-0000-0000-000000000001}"
OWNER_PATH = r"\Actor-Mixer Hierarchy\Default Work Unit\Owner"


class Reader:
    def __init__(self, responses: Mapping[str, list[Mapping[str, Any]]]) -> None:
        self.responses = {key: deque(value) for key, value in responses.items()}
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def __call__(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls.append((uri, dict(args), dict(options)))
        return self.responses[uri].popleft()


def _owner_row() -> dict[str, Any]:
    return {
        "id": OWNER_ID,
        "name": "Owner",
        "type": "ActorMixer",
        "path": OWNER_PATH,
        "parent": {"id": "{WORK-UNIT}"},
        "notes": "before",
    }


def _types() -> dict[str, Any]:
    return {
        "return": [
            {"classId": 1, "name": "ActorMixer", "type": "ActorMixer"},
            {"classId": 2, "name": "Sound", "type": "Sound"},
            {
                "classId": 3,
                "name": "AudioFileSource",
                "type": "AudioFileSource",
            },
            {"classId": 4, "name": "MusicSegment", "type": "MusicSegment"},
            {"classId": 5, "name": "MusicTrack", "type": "MusicTrack"},
        ]
    }


def _project_info(project_root: Path, *, language: str = "Japanese") -> dict[str, Any]:
    project_root.mkdir(parents=True, exist_ok=True)
    originals = project_root / "Originals"
    originals.mkdir(parents=True, exist_ok=True)
    language_id = "{43000000-0000-0000-0000-000000000001}"
    return {
        "id": "{43000000-0000-0000-0000-000000000002}",
        "name": "ObjectSetImport",
        "displayTitle": "ObjectSetImport",
        "path": str(project_root / "ObjectSetImport.wproj"),
        "isDirty": False,
        "currentLanguageId": language_id,
        "referenceLanguageId": language_id,
        "currentPlatformId": "{43000000-0000-0000-0000-000000000003}",
        "directories": {
            "root": str(project_root),
            "cache": str(project_root / ".cache"),
            "originals": str(originals),
            "soundBankOutputRoot": str(project_root / "GeneratedSoundBanks"),
            "commands": str(project_root / "Commands"),
            "properties": str(project_root / "Properties"),
        },
        "platforms": [
            {
                "id": "{43000000-0000-0000-0000-000000000003}",
                "name": "Mac",
                "baseName": "Mac",
                "baseDisplayName": "Mac",
                "soundBankPath": str(project_root / "GeneratedSoundBanks/Mac"),
                "copiedMediaPath": str(
                    project_root / "GeneratedSoundBanks/Mac/Media"
                ),
            }
        ],
        "languages": [
            {
                "id": language_id,
                "name": language,
                "shortId": 31,
            }
        ],
        "defaultConversion": {
            "id": "{43000000-0000-0000-0000-000000000004}",
            "name": "Default",
        },
    }


def test_object_create_exposes_platform_list_and_source_control_without_raw_payload() -> None:
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "object.create",
            "arguments": {
                "parent": {"kind": "id", "value": OWNER_ID},
                "type": "Sound",
                "name": "CreatedInList",
                "platform": "Windows",
                "list": "CustomList",
                "auto_add_to_source_control": True,
            },
        }
    )
    reader = Reader(
        {
            "ak.wwise.core.object.get": [
                {"return": [_owner_row()]},
                {
                    "return": [
                        {"id": OWNER_ID, "@CustomList": []}
                    ]
                },
            ],
            "ak.wwise.core.object.getTypes": [_types()],
        }
    )

    prepared = prepare_operation(request, read_call=reader).as_dict()

    assert prepared["dispatch"]["args"] == {
        "parent": OWNER_ID,
        "type": "Sound",
        "name": "CreatedInList",
        "onNameConflict": "fail",
        "autoAddToSourceControl": True,
        "platform": "Windows",
        "list": "CustomList",
    }
    assert prepared["verification_plan"]["list"] == "CustomList"
    assert prepared["pre_state"]["object_graph_guard"]["list_snapshots"][0][
        "platform"
    ] == "Windows"


@pytest.mark.parametrize(
    "version",
    ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
)
def test_object_create_list_snapshot_uses_bounded_two_step_reads_in_every_version(
    version: str,
) -> None:
    member_id = "{41000000-0000-0000-0000-000000000002}"
    member_row = {
        "id": member_id,
        "name": "ExistingListMember",
        "type": "Sound",
        "path": OWNER_PATH + r"\ExistingListMember",
        "parent": None,
        "owner": {"id": OWNER_ID},
        "notes": "existing",
    }
    reader = Reader(
        {
            "ak.wwise.core.object.get": [
                {"return": [_owner_row()]},
                {
                    "return": [
                        {
                            "id": OWNER_ID,
                            "@CustomList": [{"id": member_id}],
                        }
                    ]
                },
                {"return": [member_row]},
            ],
            "ak.wwise.core.object.getTypes": [_types()],
        }
    )

    prepared = prepare_operation(
        parse_operation_request(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": version,
                "operation": "object.create",
                "arguments": {
                    "parent": {"kind": "id", "value": OWNER_ID},
                    "type": "Sound",
                    "name": "NewListMember",
                    "platform": "Windows",
                    "list": "CustomList",
                },
            }
        ),
        read_call=reader,
    ).as_dict()

    object_reads = [
        call for call in reader.calls if call[0] == "ak.wwise.core.object.get"
    ]
    assert object_reads[1] == (
        "ak.wwise.core.object.get",
        {"from": {"id": [OWNER_ID]}},
        {"return": ["id", "@CustomList"], "platform": "Windows"},
    )
    assert object_reads[2][1] == {"from": {"id": [member_id]}}
    assert object_reads[2][2]["platform"] == "Windows"
    assert all(
        not any(
            isinstance(selector, str) and selector.startswith("@")
            for transform in call[1].get("transform", [])
            if isinstance(transform, Mapping)
            for selector in transform.get("select", [])
        )
        for call in object_reads
    )
    assert prepared["pre_state"]["object_graph_guard"]["list_snapshots"][0][
        "rows"
    ] == [member_row]


@pytest.mark.parametrize(
    ("case", "error_code"),
    (
        ("duplicate-member", "INVALID_READBACK"),
        ("missing-detail", "INVALID_READBACK"),
        ("extra-detail", "INVALID_READBACK"),
        ("wrong-owner", "LIST_OWNER_MISMATCH"),
        ("over-limit", "LIST_SNAPSHOT_LIMIT_EXCEEDED"),
    ),
)
def test_object_create_list_snapshot_fails_closed_on_inexact_membership(
    case: str,
    error_code: str,
) -> None:
    member_id = "{41000000-0000-0000-0000-000000000002}"
    extra_id = "{41000000-0000-0000-0000-000000000003}"
    references = [{"id": member_id}]
    details: list[Mapping[str, Any]] = [
        {
            "id": member_id,
            "name": "ExistingListMember",
            "type": "Sound",
            "path": OWNER_PATH + r"\ExistingListMember",
            "parent": None,
            "owner": {"id": OWNER_ID},
            "notes": "existing",
        }
    ]
    if case == "duplicate-member":
        references.append({"id": member_id})
        details = []
    elif case == "missing-detail":
        details = []
    elif case == "extra-detail":
        details.append(
            {
                "id": extra_id,
                "name": "Unexpected",
                "type": "Sound",
                "path": OWNER_PATH + r"\Unexpected",
                "parent": None,
                "owner": {"id": OWNER_ID},
                "notes": "unexpected",
            }
        )
    elif case == "wrong-owner":
        details[0] = {**details[0], "owner": {"id": extra_id}}
    else:
        references = [
            {
                "id": (
                    "{41000000-0000-0000-0000-"
                    f"{index:012x}" + "}"
                )
            }
            for index in range(129)
        ]
        details = []
    object_get_responses: list[Mapping[str, Any]] = [
        {"return": [_owner_row()]},
        {"return": [{"id": OWNER_ID, "@CustomList": references}]},
    ]
    if details or case == "missing-detail":
        object_get_responses.append({"return": details})

    with pytest.raises(OperationContractError) as caught:
        prepare_operation(
            parse_operation_request(
                {
                    "contract": OPERATION_REQUEST_CONTRACT,
                    "version": "2025.1",
                    "operation": "object.create",
                    "arguments": {
                        "parent": {"kind": "id", "value": OWNER_ID},
                        "type": "Sound",
                        "name": "NewListMember",
                        "list": "CustomList",
                    },
                }
            ),
            read_call=Reader(
                {
                    "ak.wwise.core.object.get": object_get_responses,
                    "ak.wwise.core.object.getTypes": [_types()],
                }
            ),
        )

    assert caught.value.error_code == error_code


@pytest.mark.parametrize(
    ("owner_row", "allow_missing_empty", "expected_error"),
    (
        ({"id": OWNER_ID, "@CustomList": []}, False, None),
        ({"id": OWNER_ID}, True, "INVALID_READBACK"),
        ({"id": OWNER_ID}, False, "INVALID_READBACK"),
        ({"id": OWNER_ID, "@CustomList": {}}, True, "INVALID_READBACK"),
    ),
)
def test_object_list_owner_accessor_missing_empty_compatibility_is_explicit(
    owner_row: Mapping[str, Any],
    allow_missing_empty: bool,
    expected_error: str | None,
) -> None:
    reader = Reader(
        {"ak.wwise.core.object.get": [{"return": [owner_row]}]}
    )

    if expected_error is not None:
        with pytest.raises(OperationContractError) as caught:
            _read_object_list_rows_with_evidence(
                OWNER_ID,
                "CustomList",
                fields=("id", "name", "type"),
                read=reader,
                context="test-object-list",
                allow_missing_empty=allow_missing_empty,
            )
        assert caught.value.error_code == expected_error
        return

    rows, readbacks = _read_object_list_rows_with_evidence(
        OWNER_ID,
        "CustomList",
        fields=("id", "name", "type"),
        read=reader,
        context="test-object-list",
        allow_missing_empty=allow_missing_empty,
    )
    assert rows == []
    assert len(readbacks) == 1
    if "@CustomList" not in owner_row:
        assert readbacks[0]["compatibility_normalization"]["field"] == (
            "@CustomList"
        )


@pytest.mark.parametrize(
    "reference",
    ("not-an-object", {"id": "not-a-guid"}),
)
def test_object_list_owner_accessor_rejects_malformed_member_references(
    reference: Any,
) -> None:
    with pytest.raises(OperationContractError) as caught:
        _read_object_list_rows_with_evidence(
            OWNER_ID,
            "CustomList",
            fields=("id", "name", "type"),
            read=Reader(
                {
                    "ak.wwise.core.object.get": [
                        {
                            "return": [
                                {
                                    "id": OWNER_ID,
                                    "@CustomList": [reference],
                                }
                            ]
                        }
                    ]
                }
            ),
            context="test-object-list",
        )

    assert caught.value.error_code == "INVALID_READBACK"


@pytest.mark.parametrize(
    "details",
    (
        [{"id": "not-a-guid", "name": "Malformed", "type": "Sound"}],
        [
            {
                "id": "{41000000-0000-0000-0000-000000000002}",
                "name": "Duplicate",
                "type": "Sound",
            },
            {
                "id": "{41000000-0000-0000-0000-000000000002}",
                "name": "Duplicate",
                "type": "Sound",
            },
        ],
    ),
)
def test_object_list_detail_read_rejects_malformed_or_duplicate_rows(
    details: list[Mapping[str, Any]],
) -> None:
    member_id = "{41000000-0000-0000-0000-000000000002}"
    with pytest.raises(OperationContractError) as caught:
        _read_object_list_rows_with_evidence(
            OWNER_ID,
            "CustomList",
            fields=("id", "name", "type"),
            read=Reader(
                {
                    "ak.wwise.core.object.get": [
                        {
                            "return": [
                                {
                                    "id": OWNER_ID,
                                    "@CustomList": [{"id": member_id}],
                                }
                            ]
                        },
                        {"return": details},
                    ]
                }
            ),
            context="test-object-list",
        )

    assert caught.value.error_code == "INVALID_READBACK"


def test_object_list_detail_read_restores_owner_membership_order() -> None:
    first_id = "{41000000-0000-0000-0000-000000000002}"
    second_id = "{41000000-0000-0000-0000-000000000003}"
    first = {"id": first_id, "name": "First", "type": "Sound"}
    second = {"id": second_id, "name": "Second", "type": "Sound"}
    reader = Reader(
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": OWNER_ID,
                            "@CustomList": [
                                {"id": first_id},
                                {"id": second_id},
                            ],
                        }
                    ]
                },
                {"return": [second, first]},
            ]
        }
    )

    rows, readbacks = _read_object_list_rows_with_evidence(
        OWNER_ID,
        "CustomList",
        fields=("id", "name", "type"),
        read=reader,
        platform="Windows",
        context="test-object-list",
    )

    assert rows == [first, second]
    assert len(readbacks) == 2
    assert all(row["options"].get("platform") == "Windows" for row in readbacks)
    assert all("transform" not in row["args"] for row in readbacks)


def test_object_set_exposes_global_defaults_row_overrides_rename_and_closed_list() -> None:
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "object.set",
            "arguments": {
                "platform": "Windows",
                "list_mode": "replaceAll",
                "on_name_conflict": "fail",
                "auto_add_to_source_control": True,
                "objects": [
                    {
                        "object": {"kind": "id", "value": OWNER_ID},
                        "name": "RenamedOwner",
                        "platform": "Mac",
                        "list_mode": "append",
                        "on_name_conflict": "rename",
                        "lists": [
                            {
                                "name": "CustomList",
                                "objects": [
                                    {
                                        "type": "Sound",
                                        "name": "ListSound",
                                        "platform": "Linux",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        }
    )
    reader = Reader(
        {
            "ak.wwise.core.object.getTypes": [_types()],
            "ak.wwise.core.object.get": [
                {"return": [_owner_row()]},
                {"return": []},
                {
                    "return": [
                        {"id": OWNER_ID, "@CustomList": []}
                    ]
                },
                {"return": [_owner_row()]},
                {"return": []},
            ],
        }
    )

    prepared = prepare_operation(request, read_call=reader).as_dict()
    args = prepared["dispatch"]["args"]

    assert args["platform"] == "Windows"
    assert args["listMode"] == "replaceAll"
    assert args["autoAddToSourceControl"] is True
    assert args["objects"] == [
        {
            "object": OWNER_ID,
            "platform": "Mac",
            "onNameConflict": "rename",
            "listMode": "append",
            "name": "RenamedOwner",
            "@CustomList": [
                {
                    "type": "Sound",
                    "name": "ListSound",
                    "platform": "Linux",
                }
            ],
        }
    ]
    list_spec = next(
        row
        for row in prepared["verification_plan"]["nodes"]
        if row.get("list_name") == "CustomList"
    )
    assert list_spec["collection"] == "CustomList"
    assert list_spec["platform"] == "Linux"


def test_object_set_replace_all_seals_each_old_list_subtree_before_clear() -> None:
    old_id = "{41000000-0000-0000-0000-000000000002}"
    old_row = {
        "id": old_id,
        "name": "OldListObject",
        "type": "Sound",
        "path": OWNER_PATH + r"\OldListObject",
        "parent": None,
        "owner": {"id": OWNER_ID},
        "notes": "old",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "object.set",
            "arguments": {
                "list_mode": "replaceAll",
                "objects": [
                    {
                        "object": {"kind": "id", "value": OWNER_ID},
                        "lists": [{"name": "CustomList", "objects": []}],
                    }
                ],
            },
        }
    )
    reader = Reader(
        {
            "ak.wwise.core.object.getTypes": [_types()],
            "ak.wwise.core.object.get": [
                {"return": [_owner_row()]},
                {
                    "return": [
                        {
                            "id": OWNER_ID,
                            "@CustomList": [{"id": old_id}],
                        }
                    ]
                },
                {"return": [old_row]},
                {"return": [old_row]},
                {"return": []},
                {"return": [_owner_row()]},
                {"return": []},
            ],
        }
    )

    prepared = prepare_operation(request, read_call=reader).as_dict()

    assert prepared["dispatch"]["args"]["objects"][0]["@CustomList"] == []
    guard = prepared["pre_state"]["object_graph_guard"]
    assert guard["list_snapshots"][0]["rows"] == [old_row]
    assert guard["list_subtree_snapshots"][0]["root_id"] == old_id
    assert prepared["verification_plan"]["replaced_list_subtree_rows"] == [
        old_row
    ]


def test_object_set_2023_child_language_and_import_are_closed_and_proven(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF\x04\x00\x00\x00WAVEpayload")
    project_info = _project_info(tmp_path / "Project")
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2023.1",
            "operation": "object.set",
            "arguments": {
                "objects": [
                    {
                        "object": {"kind": "id", "value": OWNER_ID},
                        "children": [
                            {
                                "type": "Sound",
                                "name": "VoiceLine",
                                "platform": "Windows",
                                "language": "Japanese",
                                "import": {
                                    "files": [
                                        {
                                            "audio_file": str(source),
                                            "originals_subfolder": "Dialogue/Chapter01",
                                            "language": "Japanese",
                                            "object_type": "AudioFileSource",
                                        }
                                    ],
                                    "auto_add_to_source_control": False,
                                },
                            }
                        ],
                    }
                ]
            },
        }
    )
    reader = Reader(
        {
            "ak.wwise.core.object.getTypes": [_types()],
            "ak.wwise.core.object.get": [
                {"return": [_owner_row()]},
                {"return": []},
                {"return": [_owner_row()]},
                {"return": []},
            ],
            "ak.wwise.core.getProjectInfo": [project_info],
        }
    )

    prepared = prepare_operation(request, read_call=reader).as_dict()

    assert prepared["dispatch"]["args"]["objects"][0]["children"] == [
        {
            "type": "Sound",
            "name": "VoiceLine",
            "platform": "Windows",
            "language": "Japanese",
            "import": {
                "files": [
                        {
                            "audioFile": str(source),
                            "originalsSubFolder": r"Dialogue\Chapter01",
                            "language": "Japanese",
                            "objectType": "AudioFileSource",
                    }
                ],
                "autoAddToSourceControl": False,
            },
        }
    ]
    child_spec = next(
        row
        for row in prepared["verification_plan"]["nodes"]
        if row["request_path"].endswith(".children[0]")
    )
    assert child_spec["requested_language"] == "Japanese"
    assert child_spec["platform"] == "Windows"
    assert child_spec["import"]["sources"][0]["sha256"]
    assert child_spec["import"]["sources"][0]["requested_language"] == "Japanese"
    assert (
        child_spec["import"]["sources"][0]["requested_object_type"]
        == "AudioFileSource"
    )
    assert prepared["pre_state"]["import_guard"]["file_proofs"][0]["proof"][
        "path"
    ] == str(source)
    assert len(
        [
            call
            for call in reader.calls
            if call[0] == "ak.wwise.core.getProjectInfo"
        ]
    ) == 1


def test_object_set_2023_inline_wav_import_is_canonicalized(
    tmp_path: Path,
) -> None:
    wav = b"RIFF\x04\x00\x00\x00WAVE"
    encoded = base64.b64encode(wav).decode("ascii")
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2023.1",
            "operation": "object.set",
            "arguments": {
                "objects": [
                    {
                        "object": {"kind": "id", "value": OWNER_ID},
                        "children": [
                            {
                                "type": "Sound",
                                "name": "InlineSfx",
                                "import": {
                                    "files": [
                                        {
                                            "audio_file_base64": (
                                                f"Generated/Inline.wav|{encoded}"
                                            )
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                ]
            },
        }
    )
    reader = Reader(
        {
            "ak.wwise.core.object.getTypes": [_types()],
            "ak.wwise.core.object.get": [
                {"return": [_owner_row()]},
                {"return": []},
                {"return": [_owner_row()]},
                {"return": []},
            ],
            "ak.wwise.core.getProjectInfo": [
                _project_info(tmp_path / "Project")
            ],
        }
    )

    prepared = prepare_operation(request, read_call=reader).as_dict()

    import_arg = prepared["dispatch"]["args"]["objects"][0]["children"][0][
        "import"
    ]
    assert import_arg == {
        "files": [
            {"audioFileBase64": rf"Generated\Inline.wav|{encoded}"}
        ],
        "autoAddToSourceControl": False,
    }
    assert prepared["pre_state"]["import_guard"]["file_proofs"] == []


@pytest.mark.parametrize(
    ("global_auto_add", "nested_auto_add", "expected"),
    [
        (None, None, False),
        (True, None, True),
        (False, True, True),
        (True, False, False),
    ],
)
def test_object_set_import_source_control_uses_effective_closed_default(
    tmp_path: Path,
    global_auto_add: bool | None,
    nested_auto_add: bool | None,
    expected: bool,
) -> None:
    wav = base64.b64encode(b"RIFF\x04\x00\x00\x00WAVE").decode("ascii")
    import_arg: dict[str, Any] = {
        "files": [
            {"audio_file_base64": rf"Generated\Default.wav|{wav}"}
        ]
    }
    if nested_auto_add is not None:
        import_arg["auto_add_to_source_control"] = nested_auto_add
    arguments: dict[str, Any] = {
        "objects": [
            {
                "object": {"kind": "id", "value": OWNER_ID},
                "children": [
                    {
                        "type": "Sound",
                        "name": "DefaultedImport",
                        "import": import_arg,
                    }
                ],
            }
        ]
    }
    if global_auto_add is not None:
        arguments["auto_add_to_source_control"] = global_auto_add
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2023.1",
            "operation": "object.set",
            "arguments": arguments,
        }
    )
    prepared = prepare_operation(
        request,
        read_call=Reader(
            {
                "ak.wwise.core.object.getTypes": [_types()],
                "ak.wwise.core.object.get": [
                    {"return": [_owner_row()]},
                    {"return": []},
                    {"return": [_owner_row()]},
                    {"return": []},
                ],
                "ak.wwise.core.getProjectInfo": [
                    _project_info(
                        tmp_path
                        / f"Project-{global_auto_add}-{nested_auto_add}"
                    )
                ],
            }
        ),
    ).as_dict()

    nested_dispatch = prepared["dispatch"]["args"]["objects"][0]["children"][
        0
    ]["import"]
    assert nested_dispatch["autoAddToSourceControl"] is expected


def test_object_set_merge_seals_effective_node_views_for_preview_and_guard(
    tmp_path: Path,
) -> None:
    child_id = "{42000000-0000-0000-0000-000000000001}"
    list_id = "{42000000-0000-0000-0000-000000000002}"
    child_path = OWNER_PATH + r"\MergedChild"
    child_row = {
        "id": child_id,
        "name": "MergedChild",
        "type": "Sound",
        "path": child_path,
        "parent": {"id": OWNER_ID},
        "notes": None,
        "activeSource": None,
        "audioSource:language": {"name": "Japanese"},
    }
    list_row = {
        "id": list_id,
        "name": "MergedListVoice",
        "type": "Sound",
        "path": OWNER_PATH + r"\MergedListVoice",
        "parent": None,
        "owner": {"id": OWNER_ID},
        "notes": None,
        "activeSource": None,
        "audioSource:language": {"name": "Japanese"},
    }
    project_info = _project_info(tmp_path / "MergeProject")

    class ViewReader:
        def __init__(self) -> None:
            self.calls: list[
                tuple[str, Mapping[str, Any], Mapping[str, Any]]
            ] = []

        def __call__(
            self,
            uri: str,
            args: Mapping[str, Any],
            options: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            self.calls.append((uri, dict(args), dict(options)))
            if uri == "ak.wwise.core.object.getTypes":
                return _types()
            if uri == "ak.wwise.core.getProjectInfo":
                return project_info
            source = args.get("from", {})
            if isinstance(source, Mapping) and "path" in source:
                return {"return": [child_row]}
            ids = source.get("id", []) if isinstance(source, Mapping) else []
            object_id = ids[0] if isinstance(ids, list) and ids else None
            transforms = args.get("transform", [])
            selected = (
                transforms[0].get("select", [])
                if isinstance(transforms, list)
                and transforms
                and isinstance(transforms[0], Mapping)
                else []
            )
            return_fields = options.get("return", [])
            if (
                object_id == OWNER_ID
                and isinstance(return_fields, list)
                and "@CustomList" in return_fields
            ):
                return {
                    "return": [
                        {
                            "id": OWNER_ID,
                            "@CustomList": [{"id": list_id}],
                        }
                    ]
                }
            if object_id == OWNER_ID and selected == ["children"]:
                return {"return": [child_row]}
            if object_id == child_id and selected == ["children"]:
                return {"return": []}
            if object_id == list_id:
                return {"return": [list_row]}
            if object_id == OWNER_ID:
                return {"return": [_owner_row()]}
            raise AssertionError((uri, args, options))

    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2023.1",
            "operation": "object.set",
            "arguments": {
                "platform": "Mac",
                "on_name_conflict": "merge",
                "objects": [
                    {
                        "object": {"kind": "id", "value": OWNER_ID},
                        "children": [
                            {
                                "type": "Sound",
                                "name": "MergedChild",
                                "platform": "Windows",
                                "language": "Japanese",
                            }
                        ],
                        "lists": [
                            {
                                "name": "CustomList",
                                "objects": [
                                    {
                                        "type": "Sound",
                                        "name": "MergedListVoice",
                                        "platform": "Linux",
                                        "language": "Japanese",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        }
    )
    preview_reader = ViewReader()
    prepared = prepare_operation(
        request,
        read_call=preview_reader,
    ).as_dict()

    path_snapshot = next(
        row
        for row in prepared["pre_state"]["object_graph_guard"][
            "path_snapshots"
        ]
        if row["path"] == child_path
    )
    assert path_snapshot["platform"] == "Windows"
    assert path_snapshot["language"] == "Japanese"
    list_field_snapshot = next(
        row
        for row in prepared["pre_state"]["object_graph_guard"][
            "field_snapshots"
        ]
        if row["object_id"] == list_id
    )
    assert list_field_snapshot["platform"] == "Linux"
    assert list_field_snapshot["language"] == "Japanese"

    preview_path_call = next(
        call
        for call in preview_reader.calls
        if call[0] == "ak.wwise.core.object.get"
        and call[1].get("from", {}).get("path") == [child_path]
    )
    assert preview_path_call[2]["platform"] == "Windows"
    assert preview_path_call[2]["language"] == "Japanese"
    preview_list_field_call = next(
        call
        for call in preview_reader.calls
        if call[0] == "ak.wwise.core.object.get"
        and call[1].get("from", {}).get("id") == [list_id]
        and call[2].get("platform") == "Linux"
        and call[2].get("language") == "Japanese"
    )
    assert preview_list_field_call[2]["platform"] == "Linux"
    assert preview_list_field_call[2]["language"] == "Japanese"

    guard_reader = ViewReader()
    validation = validate_prepared_roles(
        prepared,
        read_call=guard_reader,
    )
    assert validation["status"] == "valid"
    guard_path_call = next(
        call
        for call in guard_reader.calls
        if call[1].get("from", {}).get("path") == [child_path]
    )
    assert guard_path_call[2]["platform"] == "Windows"
    assert guard_path_call[2]["language"] == "Japanese"
    guard_list_field_call = next(
        call
        for call in guard_reader.calls
        if call[1].get("from", {}).get("id") == [list_id]
        and "transform" not in call[1]
        and call[2].get("platform") == "Linux"
        and call[2].get("language") == "Japanese"
    )
    assert guard_list_field_call[2]["platform"] == "Linux"
    assert guard_list_field_call[2]["language"] == "Japanese"


def test_object_set_import_and_language_respect_version_and_target_boundaries(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    with pytest.raises(
        ValueError,
        match="available only in Wwise 2023.1-2025.1",
    ):
        parse_operation_request(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": "2022.1",
                "operation": "object.set",
                "arguments": {
                    "objects": [
                        {
                            "object": {"kind": "id", "value": OWNER_ID},
                            "import": {
                                "files": [{"audio_file": str(source)}]
                            },
                        }
                    ]
                },
            }
        )

    bad_language = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "object.set",
            "arguments": {
                "objects": [
                    {
                        "object": {"kind": "id", "value": OWNER_ID},
                        "children": [
                            {
                                "type": "ActorMixer",
                                "name": "NotAVoice",
                                "language": "Japanese",
                            }
                        ],
                    }
                ]
            },
        }
    )
    reader = Reader(
        {
            "ak.wwise.core.object.getTypes": [_types()],
            "ak.wwise.core.object.get": [{"return": [_owner_row()]}],
        }
    )
    with pytest.raises(
        ValueError,
        match="meaningful only for a newly created Sound Voice",
    ):
        prepare_operation(bad_language, read_call=reader)


def test_object_set_import_file_type_and_language_fail_closed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")

    unknown_type = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2023.1",
            "operation": "object.set",
            "arguments": {
                "objects": [
                    {
                        "object": {"kind": "id", "value": OWNER_ID},
                        "children": [
                            {
                                "type": "Sound",
                                "name": "UnknownImportType",
                                "import": {
                                    "files": [
                                        {
                                            "audio_file": str(source),
                                            "object_type": "ImaginarySource",
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                ]
            },
        }
    )
    with pytest.raises(
        ValueError,
        match="must resolve to exactly one live metadata name",
    ):
        prepare_operation(
            unknown_type,
            read_call=Reader(
                {
                    "ak.wwise.core.object.getTypes": [_types()],
                    "ak.wwise.core.object.get": [
                        {"return": [_owner_row()]}
                    ],
                }
            ),
        )

    unknown_language = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2023.1",
            "operation": "object.set",
            "arguments": {
                "objects": [
                    {
                        "object": {"kind": "id", "value": OWNER_ID},
                        "children": [
                            {
                                "type": "Sound",
                                "name": "UnknownLanguage",
                                "import": {
                                    "files": [
                                        {
                                            "audio_file": str(source),
                                            "language": "Klingon",
                                            "object_type": "AudioFileSource",
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                ]
            },
        }
    )
    with pytest.raises(ValueError, match="exactly match the live Project"):
        prepare_operation(
            unknown_language,
            read_call=Reader(
                {
                    "ak.wwise.core.object.getTypes": [_types()],
                    "ak.wwise.core.object.get": [
                        {"return": [_owner_row()]},
                        {"return": []},
                        {"return": [_owner_row()]},
                        {"return": []},
                    ],
                    "ak.wwise.core.getProjectInfo": [
                        _project_info(tmp_path / "Project")
                    ],
                }
            ),
        )


def test_object_set_import_verification_hashes_the_copied_original(
    tmp_path: Path,
) -> None:
    wav = b"RIFF\x04\x00\x00\x00WAVEverified-payload"
    source = tmp_path / "Incoming" / "voice.wav"
    source.parent.mkdir()
    source.write_bytes(wav)
    project_info = _project_info(tmp_path / "Project")
    copied = (
        Path(project_info["directories"]["originals"])
        / "Dialogue"
        / "Chapter01"
        / "voice.wav"
    )
    copied.parent.mkdir(parents=True)
    copied.write_bytes(wav)
    child_id = "{44000000-0000-0000-0000-000000000001}"
    source_id = "{44000000-0000-0000-0000-000000000002}"
    child_path = OWNER_PATH + r"\VoiceLine"
    child_row = {
        "id": child_id,
        "name": "VoiceLine",
        "type": "Sound",
        "path": child_path,
        "parent": {"id": OWNER_ID},
        "notes": None,
        "activeSource": {"id": source_id},
        "audioSource:language": {"name": "Japanese"},
    }
    source_row = {
        "id": source_id,
        "name": "voice",
        "type": "AudioFileSource",
        "path": child_path + r"\voice",
        "parent": {"id": child_id},
        "activeSource": None,
        "audioSource:language": {"name": "Japanese"},
        "originalFilePath": str(copied),
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2023.1",
            "operation": "object.set",
            "arguments": {
                "objects": [
                    {
                        "object": {"kind": "id", "value": OWNER_ID},
                        "children": [
                            {
                                "type": "Sound",
                                "name": "VoiceLine",
                                "language": "Japanese",
                                "import": {
                                    "files": [
                                        {
                                            "audio_file": str(source),
                                            "originals_subfolder": "Dialogue/Chapter01",
                                            "language": "Japanese",
                                            "object_type": "AudioFileSource",
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                ]
            },
        }
    )
    prepared = prepare_operation(
        request,
        read_call=Reader(
            {
                "ak.wwise.core.object.getTypes": [_types()],
                "ak.wwise.core.object.get": [
                    {"return": [_owner_row()]},
                    {"return": []},
                    {"return": [_owner_row()]},
                    {"return": []},
                ],
                "ak.wwise.core.getProjectInfo": [project_info],
            }
        ),
    ).as_dict()
    verification_reader = Reader(
        {
            "ak.wwise.core.object.get": [
                {"return": [_owner_row()]},
                {"return": [child_row]},
                {"return": [source_row]},
                {"return": [source_row]},
                {"return": [child_row]},
                {"return": [source_row]},
            ]
        }
    )

    verified = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "objects": [
                        {
                            "id": OWNER_ID,
                            "name": "Owner",
                            "children": [
                                {
                                    "id": child_id,
                                    "name": "VoiceLine",
                                    "children": [
                                        {
                                            "id": source_id,
                                            "name": "voice",
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
        },
        read_call=verification_reader,
    )

    assert verified.status == "verified"
    copied_assertion = next(
        row
        for row in verified.assertions
        if "was copied once with the exact hash" in row["name"]
    )
    assert copied_assertion["passed"] is True
    language_assertion = next(
        row
        for row in verified.assertions
        if "Sound Voice language matches exactly" in row["name"]
    )
    assert language_assertion["passed"] is True


def test_object_set_row_import_verifies_implicit_topology_and_same_hash_files(
    tmp_path: Path,
) -> None:
    wav = b"RIFF\x04\x00\x00\x00WAVEsame-payload"
    incoming = tmp_path / "Incoming"
    incoming.mkdir()
    source_a = incoming / "alpha.wav"
    source_b = incoming / "beta.wav"
    source_a.write_bytes(wav)
    source_b.write_bytes(wav)
    project_info = _project_info(tmp_path / "Project")
    copied_dir = (
        Path(project_info["directories"]["originals"]) / "Imported"
    )
    copied_dir.mkdir()
    copied_a = copied_dir / "alpha.wav"
    copied_b = copied_dir / "beta.wav"
    copied_a.write_bytes(wav)
    copied_b.write_bytes(wav)

    sound_a_id = "{46000000-0000-0000-0000-000000000001}"
    source_a_id = "{46000000-0000-0000-0000-000000000002}"
    sound_b_id = "{46000000-0000-0000-0000-000000000003}"
    source_b_id = "{46000000-0000-0000-0000-000000000004}"

    def sound_row(
        object_id: str,
        name: str,
        source_id: str,
    ) -> dict[str, Any]:
        return {
            "id": object_id,
            "name": name,
            "type": "Sound",
            "path": OWNER_PATH + "\\" + name,
            "parent": {"id": OWNER_ID},
            "activeSource": {"id": source_id},
            "audioSource:language": {"name": "SFX"},
        }

    def source_row(
        object_id: str,
        name: str,
        parent_id: str,
        copied: Path,
    ) -> dict[str, Any]:
        return {
            "id": object_id,
            "name": name,
            "type": "AudioFileSource",
            "path": OWNER_PATH + "\\" + name + "\\" + name,
            "parent": {"id": parent_id},
            "activeSource": None,
            "audioSource:language": {"name": "SFX"},
            "originalFilePath": str(copied),
        }

    imported_sound_a = sound_row(sound_a_id, "alpha", source_a_id)
    imported_source_a = source_row(
        source_a_id,
        "alpha",
        sound_a_id,
        copied_a,
    )
    imported_sound_b = sound_row(sound_b_id, "beta", source_b_id)
    imported_source_b = source_row(
        source_b_id,
        "beta",
        sound_b_id,
        copied_b,
    )
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2023.1",
            "operation": "object.set",
            "arguments": {
                "objects": [
                    {
                        "object": {"kind": "id", "value": OWNER_ID},
                        "import": {
                            "files": [
                                {
                                    "audio_file": str(source_a),
                                    "originals_subfolder": "Imported",
                                    "object_type": "Sound",
                                },
                                {
                                    "audio_file": str(source_b),
                                    "originals_subfolder": "Imported",
                                    "object_type": "Sound",
                                },
                            ]
                        },
                    }
                ]
            },
        }
    )
    prepared = prepare_operation(
        request,
        read_call=Reader(
            {
                "ak.wwise.core.object.getTypes": [_types()],
                "ak.wwise.core.object.get": [
                    {"return": [_owner_row()]},
                    {"return": [_owner_row()]},
                    {"return": []},
                ],
                "ak.wwise.core.getProjectInfo": [project_info],
            }
        ),
    ).as_dict()

    sources = prepared["verification_plan"]["nodes"][0]["import"]["sources"]
    assert [row["expected_original_filename"] for row in sources] == [
        "alpha.wav",
        "beta.wav",
    ]
    assert [row["expected_object_name"] for row in sources] == [
        "alpha",
        "beta",
    ]

    verified = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "objects": [
                    {
                        "id": OWNER_ID,
                        "name": "Owner",
                        "children": [
                            {
                                "id": sound_a_id,
                                "name": "alpha",
                                "children": [
                                    {
                                        "id": source_a_id,
                                        "name": "alpha",
                                    }
                                ],
                            },
                            {
                                "id": sound_b_id,
                                "name": "beta",
                                "children": [
                                    {
                                        "id": source_b_id,
                                        "name": "beta",
                                    }
                                ],
                            },
                        ],
                    }
                ]
            }
        },
        read_call=Reader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [_owner_row()]},
                    {
                        "return": [
                            imported_sound_a,
                            imported_source_a,
                            imported_sound_b,
                            imported_source_b,
                        ]
                    },
                    {"return": [imported_sound_a, imported_sound_b]},
                ]
            }
        ),
    )

    assert verified.status == "verified"
    copied_assertions = [
        row
        for row in verified.assertions
        if "was copied once with the exact hash" in row["name"]
    ]
    assert len(copied_assertions) == 2
    assert all(row["passed"] for row in copied_assertions)
    type_assertions = [
        row
        for row in verified.assertions
        if "created the requested object type" in row["name"]
    ]
    assert len(type_assertions) == 2
    assert all(row["passed"] for row in type_assertions)
    closure = next(
        row
        for row in verified.assertions
        if "direct child GUID set equals" in row["name"]
    )
    assert closure["passed"] is True


def test_object_set_list_member_is_not_misclassified_as_direct_child() -> None:
    new_id = "{45000000-0000-0000-0000-000000000001}"
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "object.set",
            "arguments": {
                "objects": [
                    {
                        "object": {"kind": "id", "value": OWNER_ID},
                        "lists": [
                            {
                                "name": "CustomList",
                                "objects": [
                                    {"type": "Sound", "name": "ListSound"}
                                ],
                            }
                        ],
                    }
                ]
            },
        }
    )
    prepared = prepare_operation(
        request,
        read_call=Reader(
            {
                "ak.wwise.core.object.getTypes": [_types()],
                "ak.wwise.core.object.get": [
                    {"return": [_owner_row()]},
                    {
                        "return": [
                            {"id": OWNER_ID, "@CustomList": []}
                        ]
                    },
                    {"return": [_owner_row()]},
                    {"return": []},
                ],
            }
        ),
    ).as_dict()
    list_row = {
        "id": new_id,
        "name": "ListSound",
        "type": "Sound",
        "path": OWNER_PATH + r"\ListSound",
        "parent": None,
        "owner": {"id": OWNER_ID},
        "notes": None,
    }

    verified = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "objects": [
                    {
                        "id": OWNER_ID,
                        "name": "Owner",
                        "@CustomList": [
                            {"id": new_id, "name": "ListSound"}
                        ],
                    }
                ]
            }
        },
        read_call=Reader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [_owner_row()]},
                    {"return": [list_row]},
                    {"return": []},
                    {
                        "return": [
                            {
                                "id": OWNER_ID,
                                "@CustomList": [{"id": new_id}],
                            }
                        ]
                    },
                    {"return": [list_row]},
                ]
            }
        ),
    )

    assert verified.status == "verified"
    direct_child = next(
        row
        for row in verified.assertions
        if "direct child GUID set equals" in row["name"]
    )
    assert direct_child["passed"] is True
    list_check = next(
        row
        for row in verified.assertions
        if "@CustomList GUID set matches" in row["name"]
    )
    assert list_check["passed"] is True
