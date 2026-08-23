from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from wwise_waapi.business_declaration_state import (
    BusinessDeclarationSession,
    BusinessPreview,
)
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    NewDescendantTarget,
)
from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.operation_drafts import (
    OperationDraftRevisionConflict,
    OperationDraftStore,
)
from wwise_waapi.operation_registry import operation_request_schema_digest


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
PARENT_ID = "{11111111-1111-1111-1111-111111111111}"


def _context(task_authority: str = "da1-" + "1" * 40) -> BusinessContext:
    return BusinessContext.create(
        task_authority=task_authority,
        project_id=PROJECT_ID,
        project_path="/fixtures/SampleProject.wproj",
        wwise_version="2022.1",
        wwise_build="2022.1.19.8584",
    )


def _session(task_authority: str = "da1-" + "1" * 40) -> BusinessDeclarationSession:
    session = BusinessDeclarationSession.create(_context(task_authority))
    parent = session.handles.bind_object(
        object_id=PARENT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )
    return session.with_new_declaration(
        declaration_id="rain-bed",
        target=NewDescendantTarget(
            parent_handle=parent.handle,
            name="Rain_Bed",
            kind="sound-sfx",
        ),
        fields={"media_file": "/tmp/rain.wav", "volume_db": -4.0},
    )


def test_business_session_round_trips_without_exposing_native_planning() -> None:
    session = _session()

    restored = BusinessDeclarationSession.from_dict(session.as_dict())

    assert restored.as_dict() == session.as_dict()
    assert restored.revision == 1
    declaration = restored.declarations[0]
    assert declaration.fields == {
        "media_file": "/tmp/rain.wav",
        "volume_db": -4.0,
    }
    assert "object_path" not in declaration.fields
    assert "object_type" not in declaration.fields
    assert "loop" not in declaration.fields


def test_invalid_or_incomplete_declaration_is_atomic() -> None:
    session = _session()
    before = session.as_dict()

    with pytest.raises(BusinessDeclarationError) as captured:
        session.with_new_declaration(
            declaration_id="broken",
            target=NewDescendantTarget(
                parent_handle=session.declarations[0].target.parent_handle,
                name="",
                kind="sound-sfx",
            ),
            fields={"volume_db": -4.0},
        )

    assert captured.value.repair["error_code"] == "DECLARATION_INCOMPLETE"
    assert captured.value.repair["missing_fields"] == ["name"]
    assert session.as_dict() == before


def test_revision_invalidates_active_preview_and_preserves_audit() -> None:
    session = _session().with_preview(
        BusinessPreview.create(
            source_revision=1,
            readable_lines=(
                "对象：Rain_Bed",
                "类型：Sound SFX",
                "音量：-4 dB",
            ),
            detail={"plan_digest": "a" * 64, "native_call_count": 1},
        )
    )
    assert session.active_preview is not None

    revised = session.revise_declaration(
        declaration_id="rain-bed",
        fields={"media_file": "/tmp/rain.wav", "volume_db": -6.0},
    )

    assert revised.revision == 2
    assert revised.active_preview is None
    assert len(revised.preview_audit) == 1
    assert revised.preview_audit[0]["source_revision"] == 1
    assert revised.preview_audit[0]["preview_digest"] == session.active_preview.preview_digest
    assert session.active_preview is not None


def test_operation_draft_business_update_is_durable_atomic_and_cas_bound(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    schema_digest = operation_request_schema_digest("audio.import", "2022.1")
    composer_digest = operation_composer_digest("audio.import", "2022.1")
    started = store.start(
        operation="audio.import",
        version="2022.1",
        schema_digest=schema_digest,
        composer_digest=composer_digest,
    )
    context = _context(started.task_authority)
    record_path = store.records_dir / f"{started.draft_id}.json"
    before = record_path.read_bytes()

    def reject(session: BusinessDeclarationSession) -> BusinessDeclarationSession:
        raise BusinessDeclarationError(
            {
                "contract": "waapi-skill.business-repair/v1",
                "error_code": "DECLARATION_INCOMPLETE",
                "field": "name",
                "draft_changed": False,
                "action": "provide the missing fact",
            }
        )

    with pytest.raises(BusinessDeclarationError):
        store.apply_business_update(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
            context=context,
            update=reject,
            event_type="declaration.added",
        )
    assert record_path.read_bytes() == before

    updated = store.apply_business_update(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=1,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        context=context,
        update=lambda session: _add_weather(session),
        event_type="declaration.added",
    )
    assert updated.revision == 2
    assert updated.check is None
    assert updated.seal is None

    restored = store.inspect(started.draft_id, task_authority=started.task_authority)
    assert restored.composition is not None
    session = BusinessDeclarationSession.from_dict(
        restored.composition["business_session"]
    )
    assert session.declarations[0].declaration_id == "rain-bed"

    previewed = store.apply_business_update(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=2,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        context=context,
        update=lambda current: current.with_preview(
            BusinessPreview.create(
                source_revision=current.revision,
                readable_lines=("对象：Rain_Bed", "音量：-4 dB"),
                detail={"plan_digest": "a" * 64},
            )
        ),
        event_type="preview.recorded",
    )
    assert previewed.revision == 3

    revised = store.apply_business_update(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=3,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        context=context,
        update=lambda current: current.revise_declaration(
            declaration_id="rain-bed",
            fields={"media_file": "/tmp/rain.wav", "volume_db": -6.0},
        ),
        event_type="declaration.revised",
    )
    durable_revised = BusinessDeclarationSession.from_dict(
        revised.composition["business_session"]
    )
    assert durable_revised.active_preview is None
    assert len(durable_revised.preview_audit) == 1

    with pytest.raises(OperationDraftRevisionConflict):
        store.apply_business_update(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
            context=context,
            update=lambda current: current,
                event_type="declaration.revised",
        )


def test_business_updates_serialize_concurrent_writers(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = OperationDraftStore(state_dir)
    schema_digest = operation_request_schema_digest("audio.import", "2022.1")
    composer_digest = operation_composer_digest("audio.import", "2022.1")
    started = store.start(
        operation="audio.import",
        version="2022.1",
        schema_digest=schema_digest,
        composer_digest=composer_digest,
    )
    context = _context(started.task_authority)
    barrier = Barrier(2)

    def writer() -> str:
        local = OperationDraftStore(state_dir)
        barrier.wait()
        try:
            local.apply_business_update(
                started.draft_id,
                task_authority=started.task_authority,
                expected_revision=1,
                schema_digest=schema_digest,
                composer_digest=composer_digest,
                context=context,
                update=_add_weather,
                event_type="declaration.added",
            )
        except OperationDraftRevisionConflict:
            return "conflict"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _: writer(), range(2)))

    assert outcomes == ["committed", "conflict"]
    record = store.inspect(started.draft_id, task_authority=started.task_authority)
    assert record.revision == 2


def test_business_update_storage_crash_preserves_previous_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    schema_digest = operation_request_schema_digest("audio.import", "2022.1")
    composer_digest = operation_composer_digest("audio.import", "2022.1")
    started = store.start(
        operation="audio.import",
        version="2022.1",
        schema_digest=schema_digest,
        composer_digest=composer_digest,
    )
    path = store.records_dir / f"{started.draft_id}.json"
    before = path.read_bytes()

    def crash(*args: object, **kwargs: object) -> None:
        raise OSError("simulated publish crash")

    monkeypatch.setattr(store, "_replace_record", crash)
    with pytest.raises(OSError, match="simulated publish crash"):
        store.apply_business_update(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
            context=_context(started.task_authority),
            update=_add_weather,
            event_type="declaration.added",
        )

    assert path.read_bytes() == before


def _add_weather(session: BusinessDeclarationSession) -> BusinessDeclarationSession:
    parent = session.handles.bind_object(
        object_id=PARENT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )
    return session.with_new_declaration(
        declaration_id="rain-bed",
        target=NewDescendantTarget(
            parent_handle=parent.handle,
            name="Rain_Bed",
            kind="sound-sfx",
        ),
        fields={"media_file": "/tmp/rain.wav", "volume_db": -4.0},
    )
