from __future__ import annotations

from pathlib import Path

import pytest

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    SUPPORTED_WWISE_VERSIONS,
)
from wwise_waapi.operation_registry import (
    BUSINESS_DECLARATION_INPUT_MODE,
    operation_input_mode,
)
from wwise_waapi.soundbank_business import (
    materialize_soundbank_business_request,
)
from wwise_waapi.soundbank_business_contracts import (
    soundbank_business_contract_data,
)


BANK_ID = "{11111111-1111-1111-1111-111111111111}"
EVENT_ID = "{22222222-2222-2222-2222-222222222222}"
AUX_ID = "{33333333-3333-3333-3333-333333333333}"
OBJECT_ID = "{44444444-4444-4444-4444-444444444444}"
OPERATIONS = {
    "soundbank.generate": SUPPORTED_WWISE_VERSIONS,
    "soundbank.setInclusions": SUPPORTED_WWISE_VERSIONS,
    "soundbank.convertExternalSources": SUPPORTED_WWISE_VERSIONS[1:],
    "soundbank.processDefinitionFiles": SUPPORTED_WWISE_VERSIONS[1:],
}


def _session(
    version: str,
) -> tuple[BusinessDeclarationSession, dict[str, str]]:
    context = BusinessContext.create(
        task_authority="da1-" + "1" * 40,
        project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        project_path="/fixtures/SampleProject.wproj",
        wwise_version=version,
        wwise_build=f"{version}.fixture",
    )
    session = BusinessDeclarationSession.create(context)
    handles = {
        "bank": session.handles.bind_object(
            object_id=BANK_ID,
            name="Harbor",
            object_type="SoundBank",
            path=r"\SoundBanks\Default Work Unit\Harbor",
        ).handle,
        "event": session.handles.bind_object(
            object_id=EVENT_ID,
            name="Play_Harbor",
            object_type="Event",
            path=r"\Events\Default Work Unit\Play_Harbor",
        ).handle,
        "aux": session.handles.bind_object(
            object_id=AUX_ID,
            name="Harbor_Reverb",
            object_type="AuxBus",
            path=r"\Master-Mixer Hierarchy\Default Work Unit\Harbor_Reverb",
        ).handle,
        "object": session.handles.bind_object(
            object_id=OBJECT_ID,
            name="Harbor_Ambience",
            object_type="ActorMixer",
            path=r"\Actor-Mixer Hierarchy\Default Work Unit\Harbor_Ambience",
        ).handle,
    }
    return session, handles


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation, versions in OPERATIONS.items()
        for version in versions
    ],
)
def test_every_soundbank_lane_uses_one_business_plan_adapter(
    operation: str,
    version: str,
) -> None:
    contract = soundbank_business_contract_data(operation, version)

    assert operation_input_mode(operation, version) == (
        BUSINESS_DECLARATION_INPUT_MODE
    )
    assert contract["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert contract["declaration"]["subcommand"] == (
        "draft-declare-soundbank-plan"
    )
    assert contract["gateway_derivations"] == [
        "native_object_paths_and_identity_selectors",
        "wire_types_and_request_envelope",
        "dependency_order_and_batch_layout",
        "language_skip_and_artifact_plan",
    ]
    adapter = business_adapter(operation)
    assert adapter.family == "soundbank-planning"
    assert adapter.accepts_update_command(
        "draft-declare-soundbank-plan"
    )
    assert contract["declaration"]["schema"]["additionalProperties"] is False


@pytest.mark.parametrize(
    ("operation", "collection", "limit"),
    (
        ("soundbank.generate", "soundbanks", 64),
        ("soundbank.setInclusions", "inclusions", 128),
        ("soundbank.convertExternalSources", "sources", 32),
        ("soundbank.processDefinitionFiles", "files", 32),
    ),
)
def test_soundbank_business_contract_discloses_exact_collection_limits(
    operation: str,
    collection: str,
    limit: int,
) -> None:
    contract = soundbank_business_contract_data(operation, "2025.1")

    assert contract["declaration"]["schema"]["properties"][collection][
        "maxItems"
    ] == limit

    contract["declaration"]["schema"]["properties"][collection][
        "maxItems"
    ] = 1
    fresh = soundbank_business_contract_data(operation, "2025.1")
    assert fresh["declaration"]["schema"]["properties"][collection][
        "maxItems"
    ] == limit


def test_generate_business_plan_derives_native_rows_and_language_switch() -> None:
    session, handles = _session("2025.1")
    session = session.with_settings(
        {
            "soundbank_plan": {
                "soundbanks": [
                    {
                        "soundbank_handle": handles["bank"],
                        "artifact_expectation": "nonlocalized",
                        "rebuild": False,
                        "event_handles": [handles["event"]],
                        "aux_bus_handles": [handles["aux"]],
                        "inclusions": ["events", "structures", "media"],
                    }
                ],
                "platforms": ["Windows"],
                "io_root": "/fixtures/io",
            }
        }
    )

    request = materialize_soundbank_business_request(
        "soundbank.generate",
        session,
    )

    assert request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "soundbank.generate",
        "arguments": {
            "soundbanks": [
                {
                    "name": "Harbor",
                    "artifact_expectation": "nonlocalized",
                    "rebuild": False,
                    "events": [{"kind": "id", "value": EVENT_ID}],
                    "aux_busses": [{"kind": "id", "value": AUX_ID}],
                    "inclusions": ["event", "structure", "media"],
                }
            ],
            "platforms": ["Windows"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": "/fixtures/io",
        },
    }


def test_set_inclusions_business_plan_compiles_bound_objects() -> None:
    session, handles = _session("2022.1")
    session = session.with_settings(
        {
            "soundbank_plan": {
                "soundbank_handle": handles["bank"],
                "mode": "replace",
                "inclusions": [
                    {
                        "object_handle": handles["object"],
                        "filters": ["events", "media"],
                    }
                ],
            }
        }
    )

    request = materialize_soundbank_business_request(
        "soundbank.setInclusions",
        session,
    )

    assert request["arguments"] == {
        "soundbank": {"kind": "id", "value": BANK_ID},
        "mode": "replace",
        "inclusions": [
            {
                "object": {"kind": "id", "value": OBJECT_ID},
                "filters": ["events", "media"],
            }
        ],
    }


def test_replace_may_clear_one_soundbank_without_synthesizing_rows() -> None:
    session, handles = _session("2025.1")
    session = session.with_settings(
        {
            "soundbank_plan": {
                "soundbank_handle": handles["bank"],
                "mode": "replace",
                "inclusions": [],
            }
        }
    )

    request = materialize_soundbank_business_request(
        "soundbank.setInclusions",
        session,
    )

    assert request["arguments"]["inclusions"] == []


def test_inclusion_plan_accepts_128_rows_and_rejects_row_129() -> None:
    session, handles = _session("2025.1")
    rows: list[dict[str, object]] = []
    for index in range(128):
        handle = session.handles.bind_object(
            object_id=f"{{{index:08X}-5555-5555-5555-555555555555}}",
            name=f"Object_{index}",
            object_type="Event",
            path=rf"\Events\Default Work Unit\Object_{index}",
        ).handle
        rows.append({"object_handle": handle, "filters": ["events"]})
    accepted = session.with_settings(
        {
            "soundbank_plan": {
                "soundbank_handle": handles["bank"],
                "mode": "replace",
                "inclusions": rows,
            }
        }
    )
    assert len(
        materialize_soundbank_business_request(
            "soundbank.setInclusions",
            accepted,
        )["arguments"]["inclusions"]
    ) == 128

    extra_handle = session.handles.bind_object(
        object_id="{FFFFFFFF-5555-5555-5555-555555555555}",
        name="Overflow",
        object_type="Event",
        path=r"\Events\Default Work Unit\Overflow",
    ).handle
    overflow = session.with_settings(
        {
            "soundbank_plan": {
                "soundbank_handle": handles["bank"],
                "mode": "replace",
                "inclusions": [
                    *rows,
                    {"object_handle": extra_handle, "filters": ["events"]},
                ],
            }
        }
    )
    with pytest.raises(BusinessDeclarationError) as error:
        materialize_soundbank_business_request(
            "soundbank.setInclusions",
            overflow,
        )
    assert error.value.error_code == "BUSINESS_VALUE_LIMIT_EXCEEDED"
    assert error.value.repair["count"] == 129
    assert error.value.repair["limit"] == 128


@pytest.mark.parametrize(
    ("operation", "plan", "expected"),
    (
        (
            "soundbank.convertExternalSources",
            {
                "sources": [
                    {
                        "input": "/fixtures/Harbor.wsources",
                        "platform": "Windows",
                        "output": "/fixtures/io/Windows",
                    }
                ],
                "io_root": "/fixtures/io",
            },
            {
                "sources": [
                    {
                        "input": "/fixtures/Harbor.wsources",
                        "platform": "Windows",
                        "output": "/fixtures/io/Windows",
                    }
                ],
                "io_root": "/fixtures/io",
            },
        ),
        (
            "soundbank.processDefinitionFiles",
            {
                "files": ["/fixtures/Harbor.tsv"],
                "io_root": "/fixtures/io",
            },
            {
                "files": ["/fixtures/Harbor.tsv"],
                "io_root": "/fixtures/io",
            },
        ),
    ),
)
def test_exact_soundbank_artifacts_remain_exact_inside_gateway_envelope(
    operation: str,
    plan: dict[str, object],
    expected: dict[str, object],
) -> None:
    session, _handles = _session("2025.1")
    session = session.with_settings({"soundbank_plan": plan})

    request = materialize_soundbank_business_request(operation, session)

    assert request["arguments"] == expected


def test_hostile_exact_artifact_paths_are_preserved_without_file_rewrite(
    tmp_path: Path,
) -> None:
    source = tmp_path / 'I O 根 $(literal) ; "quoted".wsources'
    source.write_bytes(b"<ExternalSourcesList/>\n")
    output = tmp_path / "out $HOME ; literal"
    io_root = tmp_path / "I O 根"
    before = source.read_bytes()
    session, _handles = _session("2025.1")
    session = session.with_settings(
        {
            "soundbank_plan": {
                "sources": [
                    {
                        "input": str(source),
                        "platform": "Windows",
                        "output": str(output),
                    }
                ],
                "io_root": str(io_root),
            }
        }
    )

    request = materialize_soundbank_business_request(
        "soundbank.convertExternalSources",
        session,
    )

    assert request["arguments"] == {
        "sources": [
            {
                "input": str(source),
                "platform": "Windows",
                "output": str(output),
            }
        ],
        "io_root": str(io_root),
    }
    assert source.read_bytes() == before


def test_soundbank_business_plan_rejects_native_fields_and_stale_handles() -> None:
    session, handles = _session("2025.1")
    native = session.with_settings(
        {
            "soundbank_plan": {
                "soundbank_handle": handles["bank"],
                "mode": "add",
                "inclusions": [],
                "native_request": {},
            }
        }
    )
    with pytest.raises(BusinessDeclarationError) as native_error:
        materialize_soundbank_business_request(
            "soundbank.setInclusions",
            native,
        )
    assert native_error.value.error_code == "NATIVE_FIELD_FORBIDDEN"

    stale = session.with_settings(
        {
            "soundbank_plan": {
                "soundbank_handle": "boh1-" + "f" * 32,
                "mode": "replace",
                "inclusions": [],
            }
        }
    )
    with pytest.raises(BusinessDeclarationError) as stale_error:
        materialize_soundbank_business_request(
            "soundbank.setInclusions",
            stale,
        )
    assert stale_error.value.error_code == "OBJECT_HANDLE_NOT_AVAILABLE"
