from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support.platform_filesystem import create_symlink_or_skip
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_direct_protocol,
    build_metadata_transaction_protocol,
    build_optional_query_repair_protocol,
    build_schema_query_transaction_protocol,
    build_transaction_protocol,
    query_object_step,
    query_schema_step,
)
from tests.semantic.support.codex_compound_heavy_v1 import (
    load_compound_heavy_profile,
)
from tests.semantic.support.codex_typed_input_profile import (
    load_typed_input_profile,
)
from tests.semantic.support.codex_gateway_broker import (
    DraftActionMetadataBinding,
    DraftTypedActionBatchArgument,
    MetadataTokenProjection,
)
from tests.semantic.support.codex_object_business_plan_v3 import (
    ObjectBusinessPlanError,
    TYPED_PROFILE_QUERY_REPAIR_UNIT_ID,
    build_object_merge_query_protocol,
    compile_object_business_plan,
    parse_object_business_plan_sections,
    seal_object_input_file_manifest,
    validate_archived_object_business_plan,
    validate_object_archived_verification,
    validate_object_business_plan,
)
from tests.semantic.support.codex_object_heavy_v3 import (
    OBJECT_HEAVY_CASE_IDS,
    OBJECT_SET_CASE_IDS,
    OperationRequestSpec,
    QueryObjectRequestSpec,
    build_object_heavy_v3_recipe,
    typed_input_merge_recipe,
    typed_input_rename_recipe,
)
from tests.semantic.support.codex_object_runtime_v3 import (
    MaterializedObject,
    MaterializedReference,
    ObjectRuntimeSnapshot,
    _sealed_active_source_row,
    _verify_query_final_answer,
)


def _case(
    case_id: str,
    root: Path,
    version: str = "2022.1",
):
    recipe = build_object_heavy_v3_recipe(case_id, version)
    ids = {
        item.key: (
            "{" + f"00000000-0000-0000-0000-{index:012d}" + "}"
        )
        for index, item in enumerate(recipe.fixture.objects, start=1)
    }
    ids_by_path = {
        item.path: ids[item.key] for item in recipe.fixture.objects
    }
    materialized = []
    input_paths: dict[str, Path] = {}
    for index, item in enumerate(recipe.fixture.objects, start=1):
        if item.object_type == "Sound" and item.source_language is not None:
            path = root / f"{item.key}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((f"fixture-{case_id}-{item.key}" * 4).encode("utf-8"))
            input_paths[item.key] = path
        properties = item.properties
        reference_rows = item.references
        if case_id == "OBJ22-F-SET-03" and item.key.endswith("_child"):
            inherited_parent = recipe.fixture.object(
                item.key.removesuffix("_child")
            )
            properties = inherited_parent.properties
            reference_rows = inherited_parent.references
        materialized.append(
            MaterializedObject(
                key=item.key,
                id=ids[item.key],
                name=item.name,
                type=item.object_type,
                path=item.path,
                parent_id=ids_by_path.get(
                    item.parent_path or "",
                    "{FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF}",
                ),
                notes=item.notes,
                properties=properties,
                references=tuple(
                    MaterializedReference(row.name, ids[row.target_key])
                    for row in reference_rows
                ),
                source_language=item.source_language,
                is_included=item.is_included,
                children_count=sum(
                    child.parent_path == item.path
                    for child in recipe.fixture.objects
                ),
                active_source_id=(
                    "{" + f"10000000-0000-0000-0000-{index:012d}" + "}"
                    if item.source_language is not None
                    else None
                ),
                active_source_name=(
                    item.key if item.source_language is not None else None
                ),
                active_source_path=(
                    f"{item.path}\\{item.key}"
                    if item.source_language is not None
                    else None
                ),
            )
        )
    prefixes = tuple(
        (f"{parent}|{prefix}", ())
        for parent, prefix in recipe.fixture.absent_sibling_prefixes
    )
    override_output_rows = tuple(
        (
            item.key,
            (
                any(reference.name == "OutputBus" for reference in item.references)
                if item.object_type
                in {
                    "ActorMixer",
                    "PropertyContainer",
                    "RandomSequenceContainer",
                    "Sound",
                }
                else None
            ),
        )
        for item in recipe.fixture.objects
    )
    digest_payload = {
        "objects": [asdict(item) for item in materialized],
        "absent_paths": list(recipe.fixture.absent_paths),
        "sibling_prefix_rows": prefixes,
        "override_output_rows": override_output_rows,
    }
    digest = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    before = ObjectRuntimeSnapshot(
        objects=tuple(materialized),
        absent_paths=recipe.fixture.absent_paths,
        sibling_prefix_rows=prefixes,
        digest=digest,
        override_output_rows=override_output_rows,
    )
    request = recipe.request
    protocol = (
        build_transaction_protocol([request.as_dict(version=recipe.version)])
        if isinstance(request, OperationRequestSpec)
        else build_direct_protocol(
            ([query_schema_step()] if "--max-results" in request.argv else [])
            + [
                query_object_step("query-object", request.argv[3:]),
            ]
        )
    )
    scenario = SimpleNamespace(
        id=recipe.scenario_id,
        api=recipe.api,
        versions=(recipe.version,),
    )
    manifest = seal_object_input_file_manifest(input_paths)
    return scenario, recipe, protocol, before, manifest


def _reseal_object_fixture_spec(payload: dict) -> None:
    fixture_value = {
        "static": payload["static_expectation"],
        "live": payload["live_binding"],
    }
    payload["fixture_spec"]["sha256"] = hashlib.sha256(
        json.dumps(
            fixture_value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize("case_id", OBJECT_HEAVY_CASE_IDS)
def _archive_test_all_fifteen_object_cases_compile_and_archive_validate(
    case_id: str,
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(case_id, tmp_path)
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    validate_object_business_plan(
        sections,
        scenario=scenario,
        recipe=recipe,
        protocol=protocol,
        before=before,
        input_file_manifest=manifest,
        verify_files=True,
    )
    payload = sections.writer_kwargs()
    parsed = parse_object_business_plan_sections(payload)
    assert parsed.writer_kwargs() == sections.writer_kwargs()
    archived = validate_archived_object_business_plan(
        payload,
        scenario=scenario,
        recipe=recipe,
        protocol=protocol,
        verify_files=True,
    )
    assert archived.writer_kwargs() == sections.writer_kwargs()
    assert sections.fixture_spec["kind"] == "object_materialized_v1"
    assert sections.payload_bindings["primary_steps"] in (
        ["query-schema", "query-object"],
        ["query-object"],
        ["tx01.execute"],
    )


def test_typed_profile_set03_metadata_protocol_binds_exact_unit_in_archive(
    tmp_path: Path,
) -> None:
    scenario, recipe, _base, before, manifest = _case(
        "OBJ22-F-SET-03",
        tmp_path,
    )
    protocol = build_metadata_transaction_protocol(
        (recipe.request.as_dict(version=recipe.version),),
        object_type="ActorMixer",
        metadata_queries=("volume", "pitch", "notes", "output bus"),
        required_tokens=("Volume", "Pitch", "OutputBus"),
        expected_required_token_projection=(
            MetadataTokenProjection("Volume", "property", "Real32"),
            MetadataTokenProjection("Pitch", "property", "Real32"),
            MetadataTokenProjection("OutputBus", "reference", "Object"),
        ),
        equivalence="object_set_v1",
        schema_first=True,
    )
    unit_id = "TYP22-METADATA-OBJECT-SET"

    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
        profile_unit_id=unit_id,
    )
    validate_object_business_plan(
        sections,
        scenario=scenario,
        recipe=recipe,
        protocol=protocol,
        before=before,
        input_file_manifest=manifest,
        verify_files=True,
        profile_unit_id=unit_id,
    )
    archived = validate_archived_object_business_plan(
        sections.writer_kwargs(),
        scenario=scenario,
        recipe=recipe,
        protocol=protocol,
        verify_files=True,
        profile_unit_id=unit_id,
    )

    assert archived.static_expectation["profile_unit_id"] == unit_id
    with pytest.raises(ObjectBusinessPlanError, match="exact reviewed request"):
        validate_archived_object_business_plan(
            sections.writer_kwargs(),
            scenario=scenario,
            recipe=recipe,
            protocol=protocol,
            verify_files=False,
        )


def test_typed_profile_query_repair_protocol_binds_exact_unit_in_archive(
    tmp_path: Path,
) -> None:
    scenario, recipe, _base, before, manifest = _case(
        "OBJ22-F-GET-03",
        tmp_path,
    )
    assert isinstance(recipe.request, QueryObjectRequestSpec)
    protocol = build_optional_query_repair_protocol(
        query_object_step("query-object", recipe.request.argv[3:])
    )

    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
        profile_unit_id=TYPED_PROFILE_QUERY_REPAIR_UNIT_ID,
    )
    archived = validate_archived_object_business_plan(
        sections.writer_kwargs(),
        scenario=scenario,
        recipe=recipe,
        protocol=protocol,
        verify_files=True,
        profile_unit_id=TYPED_PROFILE_QUERY_REPAIR_UNIT_ID,
    )

    assert archived.static_expectation["profile_unit_id"] == (
        TYPED_PROFILE_QUERY_REPAIR_UNIT_ID
    )
    with pytest.raises(ObjectBusinessPlanError, match="exact reviewed request"):
        validate_archived_object_business_plan(
            sections.writer_kwargs(),
            scenario=scenario,
            recipe=recipe,
            protocol=protocol,
            verify_files=True,
        )
@pytest.mark.parametrize(
    "case_id",
    (
        "OBJ22-F-CREATE-02",
        "OBJ22-F-CREATE-03",
        "OBJ22-F-SET-01",
        "OBJ22-F-SET-02",
    ),
)
def _archive_test_compound_object_2025_business_plan_compiles_and_archive_validates(
    case_id: str,
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        case_id,
        tmp_path,
        "2025.1",
    )

    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    validate_object_business_plan(
        sections,
        scenario=scenario,
        recipe=recipe,
        protocol=protocol,
        before=before,
        input_file_manifest=manifest,
        verify_files=True,
    )
    archived = validate_archived_object_business_plan(
        sections.writer_kwargs(),
        scenario=scenario,
        recipe=recipe,
        protocol=protocol,
        verify_files=True,
    )

    assert archived.writer_kwargs() == sections.writer_kwargs()
    assert sections.static_expectation["version"] == "2025.1"
    assert sections.static_expectation["request"]["value"]["version"] == "2025.1"
    assert any(
        row["type"] == "PropertyContainer"
        for row in sections.live_binding["before_snapshot"]["objects"]
    )


def _archive_test_typed_profile_collision_protocol_queries_before_schema(
    tmp_path: Path,
) -> None:
    scenario, recipe, _base, _before, _manifest = _case(
        "OBJ22-F-CREATE-03",
        tmp_path,
        "2023.1",
    )
    recipe = typed_input_rename_recipe(
        recipe,
        unit_id="TYP23-DEDICATED-OBJECT-CREATE",
    )
    base = build_transaction_protocol(
        (recipe.request.as_dict(version=recipe.version),)
    )

    protocol = build_object_merge_query_protocol(
        scenario,
        recipe,
        base_protocol=base,
        profile_unit_id="TYP23-DEDICATED-OBJECT-CREATE",
    )

    assert protocol is not None
    assert [step.subcommand for step in protocol.steps[:3]] == [
        "query-object",
        "operation-schema",
        "draft-start",
    ]
    assert protocol.steps[0].arguments == (
        "--path",
        r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Weapons\Impact_Library",
        "--return-field",
        "id",
        "--return-field",
        "name",
        "--return-field",
        "type",
        "--return-field",
        "path",
    )


@pytest.mark.parametrize(
    "case_id",
    (
        "OBJ22-F-CREATE-03",
        "OBJ22-F-SET-01",
        "OBJ22-F-SET-02",
    ),
)
@pytest.mark.parametrize(
    ("version", "object_type"),
    (
        ("2022.1", "ActorMixer"),
        ("2025.1", "PropertyContainer"),
    ),
)
def _archive_test_compound_object_metadata_protocol_is_archived_and_revalidated(
    case_id: str,
    version: str,
    object_type: str,
    tmp_path: Path,
) -> None:
    profile_path = (
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in load_compound_heavy_profile(profile_path).units
        if row.base_scenario_id == case_id and row.version == version
    )
    _scenario_value, recipe, _protocol, before, manifest = _case(
        case_id,
        tmp_path,
        version,
    )
    protocol = build_metadata_transaction_protocol(
        (recipe.request.as_dict(version=version),),
        object_type=object_type,
        metadata_queries=("volume",),
        required_tokens=("Volume",),
        expected_required_token_projection=(
            MetadataTokenProjection("Volume", "property", "Real32"),
        ),
        equivalence=(
            "object_set_v1"
            if recipe.request.operation == "object.set"
            else "wire_exact"
        ),
        schema_first=True,
    )

    sections = compile_object_business_plan(
        unit.scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    validate_object_business_plan(
        sections,
        scenario=unit.scenario,
        recipe=recipe,
        protocol=protocol,
        before=before,
        input_file_manifest=manifest,
        verify_files=True,
    )
    archived = validate_archived_object_business_plan(
        sections.writer_kwargs(),
        scenario=unit.scenario,
        recipe=recipe,
        protocol=protocol,
        verify_files=True,
    )

    assert archived.writer_kwargs() == sections.writer_kwargs()
    assert sections.payload_bindings["primary_steps"] == ["tx01.execute"]
    assert "metadata.discover" in sections.payload_bindings["verification_steps"]
    metadata_binding = next(
        binding
        for step in protocol.steps
        for argument in (None, *step.arguments)
        for binding in (
            (step.metadata_binding,)
            if argument is None
            else (
                tuple(action.metadata_binding for action in argument.actions)
                if isinstance(argument, DraftTypedActionBatchArgument)
                else (getattr(argument, "metadata_binding", None),)
            )
        )
        if isinstance(binding, DraftActionMetadataBinding)
    )
    assert metadata_binding.expected_projection == (
        MetadataTokenProjection("Volume", "property", "Real32"),
    )


def test_compound_object_metadata_protocol_requires_trusted_projection(
    tmp_path: Path,
) -> None:
    profile_path = (
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in load_compound_heavy_profile(profile_path).units
        if row.unit_id == "CMP22-OBJ22-F-SET-01"
    )
    _scenario_value, recipe, _protocol, before, manifest = _case(
        unit.base_scenario_id,
        tmp_path,
        unit.version,
    )
    protocol = build_metadata_transaction_protocol(
        (recipe.request.as_dict(version=unit.version),),
        object_type="ActorMixer",
        metadata_queries=("volume",),
        required_tokens=("Volume",),
        schema_first=True,
    )

    with pytest.raises(
        ObjectBusinessPlanError,
        match="trusted live metadata projection",
    ):
        compile_object_business_plan(
            unit.scenario,
            recipe,
            protocol,
            before,
            manifest,
        )


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def _archive_test_compound_merge_query_protocol_is_archived_and_revalidated(
    version: str,
    tmp_path: Path,
) -> None:
    profile_path = (
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in load_compound_heavy_profile(profile_path).units
        if row.base_scenario_id == "OBJ22-F-CREATE-02"
        and row.version == version
    )
    _scenario_value, recipe, _protocol, before, manifest = _case(
        unit.base_scenario_id,
        tmp_path,
        version,
    )
    protocol = build_object_merge_query_protocol(unit.scenario, recipe)
    assert protocol is not None

    sections = compile_object_business_plan(
        unit.scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    archived = validate_archived_object_business_plan(
        sections.writer_kwargs(),
        scenario=unit.scenario,
        recipe=recipe,
        protocol=protocol,
        verify_files=True,
    )

    assert archived.writer_kwargs() == sections.writer_kwargs()
    assert "object.merge-root" in sections.payload_bindings["verification_steps"]
    assert sections.payload_bindings["verification_steps"][-1] == "tx01.verify"


def _archive_test_compound_merge_query_protocol_rejects_a_different_root(
    tmp_path: Path,
) -> None:
    profile_path = (
        Path(__file__).resolve().parent
        / "data"
        / "compound-heavy-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in load_compound_heavy_profile(profile_path).units
        if row.unit_id == "CMP25-OBJ22-F-CREATE-02"
    )
    _scenario_value, recipe, _protocol, before, manifest = _case(
        unit.base_scenario_id,
        tmp_path,
        unit.version,
    )
    wrong_protocol = build_schema_query_transaction_protocol(
        (recipe.request.as_dict(version=unit.version),),
        query_step=query_object_step(
            "object.merge-root",
            (
                "query-object",
                "--path",
                r"\Containers\Default Work Unit\SemanticLab\NPC\Other",
                "--return-field",
                "id",
                "--return-field",
                "name",
                "--return-field",
                "type",
                "--return-field",
                "path",
            ),
        ),
    )

    with pytest.raises(
        ObjectBusinessPlanError,
        match="exact reviewed request",
    ):
        compile_object_business_plan(
            unit.scenario,
            recipe,
            wrong_protocol,
            before,
            manifest,
        )


def _archive_test_typed_profile_merge_reads_the_exact_root_before_schema_continuation() -> None:
    profile_path = (
        Path(__file__).resolve().parent
        / "data"
        / "typed-input-v1"
        / "profile.json"
    )
    unit = next(
        row
        for row in load_typed_input_profile(profile_path).units
        if row.unit_id == "TYP21-DEDICATED-OBJECT-CREATE"
    )
    recipe = typed_input_merge_recipe(
        build_object_heavy_v3_recipe(unit.base_scenario_id, unit.version),
        unit_id=unit.unit_id,
    )

    protocol = build_object_merge_query_protocol(unit.scenario, recipe)

    assert protocol is not None
    assert tuple(step.subcommand for step in protocol.steps[:3]) == (
        "query-object",
        "operation-schema",
        "draft-start",
    )
    assert protocol.steps[0].arguments == (
        "--path",
        r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\NPC\Robot_VO",
        "--return-field",
        "id",
        "--return-field",
        "name",
        "--return-field",
        "type",
        "--return-field",
        "path",
    )
    assert (
        "先核对现有 `\\Actor-Mixer Hierarchy\\Default Work Unit"
        "\\SemanticLab\\NPC\\Robot_VO` 的完整路径和类型"
        in unit.scenario.prompt
    )


def _archive_test_object_archive_rejects_static_live_file_delta_and_extra_field_tamper(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-CREATE-01",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    payload = sections.writer_kwargs()
    attacks = []
    static = dict(payload["static_expectation"])
    static["request_sha256"] = "0" * 64
    attacks.append({**payload, "static_expectation": static})
    live = dict(payload["live_binding"])
    live["before_snapshot_sha256"] = "0" * 64
    attacks.append({**payload, "live_binding": live})
    live_extra = dict(payload["live_binding"])
    live_extra["extra"] = True
    attacks.append({**payload, "live_binding": live_extra})
    rules = [dict(item) for item in payload["delta_rules"]]
    rules[1]["new_keys"] = []
    attacks.append({**payload, "delta_rules": rules})
    fixture = dict(payload["fixture_spec"])
    fixture["sha256"] = "0" * 64
    attacks.append({**payload, "fixture_spec": fixture})
    for attack in attacks:
        with pytest.raises(ObjectBusinessPlanError):
            validate_archived_object_business_plan(
                attack,
                scenario=scenario,
                recipe=recipe,
                protocol=protocol,
            )


def test_object_archive_rejects_file_tamper_but_remains_verifiable_after_cleanup(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-GET-05",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    payload = sections.writer_kwargs()
    source = Path(manifest[0]["path"])
    source.write_bytes(b"tampered")
    with pytest.raises(ObjectBusinessPlanError, match="current fixture file"):
        validate_archived_object_business_plan(
            payload,
            scenario=scenario,
            recipe=recipe,
            protocol=protocol,
            verify_files=True,
        )
    source.unlink()
    validate_archived_object_business_plan(
        payload,
        scenario=scenario,
        recipe=recipe,
        protocol=protocol,
        verify_files=False,
    )


def test_object_rejects_cross_bound_or_incomplete_protocol(tmp_path: Path) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-SET-01",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    wrong_protocol = build_direct_protocol(
        [query_object_step("object.get", ("query-object", "--from", "project", "--take", "1"))]
    )
    with pytest.raises(ObjectBusinessPlanError, match="protocol"):
        validate_archived_object_business_plan(
            sections.writer_kwargs(),
            scenario=scenario,
            recipe=recipe,
            protocol=wrong_protocol,
        )
    cross_scenario = SimpleNamespace(
        id="OBJ22-F-SET-02",
        api=scenario.api,
        versions=scenario.versions,
    )
    with pytest.raises(ObjectBusinessPlanError, match="misbound"):
        validate_object_business_plan(
            sections,
            scenario=cross_scenario,
            recipe=recipe,
            protocol=protocol,
            before=before,
            input_file_manifest=manifest,
        )


def test_object_input_manifest_rejects_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"wav")
    link = tmp_path / "link.wav"
    create_symlink_or_skip(link, source)
    with pytest.raises(ObjectBusinessPlanError, match="regular file"):
        seal_object_input_file_manifest({"fixture": link})


def test_object_input_manifest_rejects_hard_links_during_seal(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF-source")
    (tmp_path / "source-alias.wav").hardlink_to(source)

    with pytest.raises(ObjectBusinessPlanError, match="exclusive"):
        seal_object_input_file_manifest({"fixture": source})


def test_object_input_manifest_rejects_hard_links_during_verification(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-GET-05",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    source = Path(manifest[0]["path"])
    (tmp_path / "source-alias.wav").hardlink_to(source)

    with pytest.raises(ObjectBusinessPlanError, match="current fixture file"):
        validate_archived_object_business_plan(
            sections.writer_kwargs(),
            scenario=scenario,
            recipe=recipe,
            protocol=protocol,
            verify_files=True,
        )


def test_object_archive_accepts_windows_paths_without_host_os_reinterpretation(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-GET-05",
        tmp_path,
    )
    payload = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    ).writer_kwargs()
    for index, row in enumerate(payload["live_binding"]["input_files"]):
        row["path"] = rf"C:\Fixture Inputs\Sound {index}.wav"
    _reseal_object_fixture_spec(payload)

    validate_archived_object_business_plan(
        payload,
        scenario=scenario,
        recipe=recipe,
        protocol=protocol,
        verify_files=False,
    )


def test_object_archive_path_uniqueness_uses_producer_case_semantics(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-GET-05",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )

    windows_attack = sections.writer_kwargs()
    windows_rows = windows_attack["live_binding"]["input_files"]
    windows_rows[0]["path"] = r"C:\Fixture Inputs\Thunder.wav"
    windows_rows[1]["path"] = r"c:\fixture inputs\THUNDER.WAV"
    for index, row in enumerate(windows_rows[2:], start=2):
        row["path"] = rf"C:\Fixture Inputs\Sound {index}.wav"
    _reseal_object_fixture_spec(windows_attack)
    with pytest.raises(ObjectBusinessPlanError, match="manifest values"):
        validate_archived_object_business_plan(
            windows_attack,
            scenario=scenario,
            recipe=recipe,
            protocol=protocol,
        )

    posix_payload = sections.writer_kwargs()
    posix_rows = posix_payload["live_binding"]["input_files"]
    posix_rows[0]["path"] = "/fixture-inputs/Thunder.wav"
    posix_rows[1]["path"] = "/fixture-inputs/thunder.wav"
    for index, row in enumerate(posix_rows[2:], start=2):
        row["path"] = f"/fixture-inputs/sound-{index}.wav"
    _reseal_object_fixture_spec(posix_payload)
    validate_archived_object_business_plan(
        posix_payload,
        scenario=scenario,
        recipe=recipe,
        protocol=protocol,
        verify_files=False,
    )


def test_object_archive_rejects_resealed_wrong_fixture_fields_and_prefix_rows(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-SET-05",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    payload = sections.writer_kwargs()
    for field, value in (
        ("notes", "wrong notes"),
        ("properties", [{"name": "Volume", "value": 999}]),
    ):
        attack = json.loads(json.dumps(payload))
        snapshot = attack["live_binding"]["before_snapshot"]
        target = next(row for row in snapshot["objects"] if row["key"] == "confirm")
        target[field] = value
        snapshot["digest"] = _snapshot_digest(snapshot)
        attack["live_binding"]["before_snapshot_sha256"] = snapshot["digest"]
        attack["live_binding"]["key_bindings"] = snapshot["objects"]
        with pytest.raises(ObjectBusinessPlanError):
            validate_archived_object_business_plan(
                attack,
                scenario=scenario,
                recipe=recipe,
                protocol=protocol,
            )

    prefix_attack = json.loads(json.dumps(payload))
    snapshot = prefix_attack["live_binding"]["before_snapshot"]
    snapshot["sibling_prefix_rows"][0][1] = [
        ["{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", "Injected", "\\Injected"]
    ]
    snapshot["digest"] = _snapshot_digest(snapshot)
    prefix_attack["live_binding"]["before_snapshot_sha256"] = snapshot["digest"]
    with pytest.raises(ObjectBusinessPlanError, match="sibling-prefix"):
        validate_archived_object_business_plan(
            prefix_attack,
            scenario=scenario,
            recipe=recipe,
            protocol=protocol,
        )


def _archive_test_object_archived_verification_joins_exact_create_topology_and_fields(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-CREATE-01",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    verification = _mutation_verification(sections)
    validate_object_archived_verification(sections, verification)

    attacks = []
    for key, field, value in (
        ("player_foley", "name", "WrongName"),
        ("player_foley", "path", r"\Actor-Mixer Hierarchy\Wrong"),
        ("footsteps", "parent_id", "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}"),
        ("player_foley", "properties", [{"name": "Volume", "value": 12.0}]),
        ("player_foley", "id", sections.live_binding["before_snapshot"]["objects"][0]["id"]),
    ):
        attack = json.loads(json.dumps(verification))
        attack["evidence"]["resolved"][key][field] = value
        attacks.append(attack)
    for attack in attacks:
        with pytest.raises(ObjectBusinessPlanError):
            validate_object_archived_verification(sections, attack)


@pytest.mark.parametrize("case_id", OBJECT_SET_CASE_IDS)
def test_object_archived_verification_joins_existing_and_resolved_set_children(
    case_id: str,
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(case_id, tmp_path)
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    expected_objects = sections.delta_rules[0]["expected_objects"]
    expected_keys = {item["key"] for item in expected_objects}
    before_keys = {
        item["key"] for item in sections.live_binding["before_snapshot"]["objects"]
    }
    protected_keys = set(sections.delta_rules[1]["protected_snapshot_keys"])
    existing_children = {
        child_key
        for item in expected_objects
        for child_key in item["children"]
        if child_key not in expected_keys
    }
    assert existing_children
    assert existing_children <= before_keys
    assert existing_children <= protected_keys

    validate_object_archived_verification(
        sections,
        _mutation_verification(sections),
    )


def test_object_archived_verification_rejects_unresolved_child_key(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-SET-01",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    payload = sections.writer_kwargs()
    payload["delta_rules"][0]["expected_objects"][0]["children"][0] = (
        "missing_child"
    )
    tampered = parse_object_business_plan_sections(payload)

    with pytest.raises(ObjectBusinessPlanError, match="expected child is absent"):
        validate_object_archived_verification(
            tampered,
            _mutation_verification(tampered),
        )


def test_object_archived_verification_rejects_unresolved_parent_key(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-SET-01",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    payload = sections.writer_kwargs()
    payload["delta_rules"][0]["expected_objects"][0]["parent_key"] = (
        "missing_parent"
    )
    tampered = parse_object_business_plan_sections(payload)

    with pytest.raises(ObjectBusinessPlanError, match="parent is absent"):
        validate_object_archived_verification(
            tampered,
            _mutation_verification(tampered),
        )


def test_object_archived_verification_joins_query_sets_and_before_snapshot(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-GET-01",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    rule = sections.delta_rules[0]
    request = sections.static_expectation["request"]["value"]
    expected_payload = (
        rule["bounded_superset_keys"]
        if request["result_strategy"] == "bounded_superset_final_answer_filter"
        else rule["exact_expected_keys"]
    )
    verification = {
        "phase": "query",
        "passed": True,
        "failures": [],
        "evidence": {
            "before": sections.live_binding["before_snapshot"],
            "after": sections.live_binding["before_snapshot"],
            "observed_keys": expected_payload,
            "expected_payload_keys": expected_payload,
            "primary_row_policy": rule["primary_row_policy"],
            "raw_row_count": len(expected_payload),
            "query_bound": {"mode": "take", "value": request["take"]},
            "bound_reached": len(expected_payload) == request["take"],
            "derived_row_policy": "none",
            "derived_rows": [],
            "required_keys": rule["exact_expected_keys"],
            "excluded_keys": rule["excluded_keys"],
            "final_answer_policy": "name_and_id",
            "required_identity_tokens": [
                {
                    "key": key,
                    "name": next(
                        row["name"]
                        for row in sections.live_binding["before_snapshot"]["objects"]
                        if row["key"] == key
                    ),
                    "id": next(
                        row["id"]
                        for row in sections.live_binding["before_snapshot"]["objects"]
                        if row["key"] == key
                    ),
                    "name_present": True,
                    "id_present": True,
                }
                for key in rule["exact_expected_keys"]
            ],
            "excluded_identity_tokens": [
                {
                    "key": key,
                    "id": next(
                        row["id"]
                        for row in sections.live_binding["before_snapshot"]["objects"]
                        if row["key"] == key
                    ),
                    "id_present": False,
                }
                for key in rule["excluded_keys"]
            ],
            "paired_rows": [],
            "deduplicated_parent_rows": [],
            "coverage_summary": None,
            "observed_answer_order": [],
            "final_response_sha256": "a" * 64,
        },
    }
    validate_object_archived_verification(sections, verification)
    attack = json.loads(json.dumps(verification))
    attack["evidence"]["required_keys"] = []
    with pytest.raises(ObjectBusinessPlanError):
        validate_object_archived_verification(sections, attack)


def test_get02_archived_verification_binds_sources_and_paired_answer(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-GET-02",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    rule = sections.delta_rules[0]
    by_key = before.by_key()
    id_to_key = {row.id: key for key, row in by_key.items()}
    lines = ["| Parent | Sound | Language | Volume | Notes |", "|---|---|---|---:|---|"]
    for key in rule["expected_order_keys"]:
        child = by_key[key]
        parent_key = id_to_key.get(child.parent_id or "")
        if child.type != "Sound" or parent_key not in rule["exact_expected_keys"]:
            continue
        parent = by_key[parent_key]
        volume = next(value.value for value in child.properties if value.name == "Volume")
        lines.append(
            f"| `{parent.path}` | `{child.path}` | {child.source_language} | "
            f"{float(volume):.1f} dB | {child.notes} |"
        )
    answer = "\n".join(lines)
    (
        required,
        excluded,
        paired,
        deduplicated,
        coverage,
        order,
        failures,
    ) = _verify_query_final_answer(
        recipe.request,
        by_key,
        excluded_keys=recipe.oracle.excluded_keys,
        expected_order_keys=recipe.oracle.expected_order_keys,
        final_response=answer,
    )
    assert failures == ()
    derived = [
        _sealed_active_source_row(by_key[key])
        for key in recipe.request.bounded_superset_keys
        if by_key[key].type == "Sound"
    ]
    verification = {
        "phase": "query",
        "passed": True,
        "failures": [],
        "evidence": {
            "before": sections.live_binding["before_snapshot"],
            "after": sections.live_binding["before_snapshot"],
            "observed_keys": list(recipe.request.bounded_superset_keys),
            "expected_payload_keys": list(recipe.request.bounded_superset_keys),
            "primary_row_policy": recipe.request.primary_row_policy,
            "raw_row_count": len(recipe.request.bounded_superset_keys) + len(derived),
            "query_bound": {"mode": "take", "value": recipe.request.take},
            "bound_reached": (
                len(recipe.request.bounded_superset_keys) + len(derived)
                == recipe.request.take
            ),
            "derived_row_policy": recipe.request.derived_row_policy,
            "derived_rows": derived,
            "required_keys": list(recipe.request.exact_expected_keys),
            "excluded_keys": list(recipe.oracle.excluded_keys),
            "final_answer_policy": recipe.request.final_answer_policy,
            "required_identity_tokens": required,
            "excluded_identity_tokens": excluded,
            "paired_rows": paired,
            "deduplicated_parent_rows": deduplicated,
            "coverage_summary": coverage,
            "observed_answer_order": order,
            "final_response_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        },
    }
    validate_object_archived_verification(sections, verification)

    attacks = []
    wrong_source = json.loads(json.dumps(verification))
    wrong_source["evidence"]["derived_rows"][0]["id"] = (
        "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}"
    )
    attacks.append(wrong_source)
    wrong_policy = json.loads(json.dumps(verification))
    wrong_policy["evidence"]["derived_row_policy"] = "none"
    attacks.append(wrong_policy)
    wrong_volume = json.loads(json.dumps(verification))
    wrong_volume["evidence"]["paired_rows"][0]["volume"] = -99.0
    attacks.append(wrong_volume)
    wrong_parent_path = json.loads(json.dumps(verification))
    wrong_parent_path["evidence"]["paired_rows"][0]["parent_path"] = r"\Wrong"
    attacks.append(wrong_parent_path)
    for attack in attacks:
        with pytest.raises(ObjectBusinessPlanError):
            validate_object_archived_verification(sections, attack)


def test_get04_archived_verification_binds_duplicate_rows_and_parent_summary(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-GET-04",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    rule = sections.delta_rules[0]
    by_key = before.by_key()
    by_id = {row.id: row for row in by_key.values()}
    answer_rows = []
    for key in recipe.request.exact_expected_keys:
        parent = by_key[key]
        bus_id = next(
            row.target_id for row in parent.references if row.name == "OutputBus"
        )
        bus = by_id[bus_id]
        answer_rows.append(
            f"| {parent.name} | {parent.id} | `{parent.path}` | "
            f"{parent.children_count} | {parent.notes} | {bus.name} |"
        )
    answer = "\n".join(
        (
            "| 名称 | GUID | 路径 | 直接子对象数 | 备注 | Output Bus |",
            "|---|---|---|---:|---|---|",
            *answer_rows,
            "汇总：命中 3 个父容器，确认覆盖 10 个直接子 Sound；10 条上限已触及，结果可能不完整。",
        )
    )
    (
        required,
        excluded,
        paired,
        deduplicated,
        coverage,
        order,
        failures,
    ) = _verify_query_final_answer(
        recipe.request,
        by_key,
        excluded_keys=recipe.oracle.excluded_keys,
        expected_order_keys=recipe.oracle.expected_order_keys,
        final_response=answer,
    )
    assert failures == ()
    observed = [
        *("q4_pistol",) * 3,
        *("q4_rifle",) * 4,
        *("q4_shotgun",) * 3,
    ]
    verification = {
        "phase": "query",
        "passed": True,
        "failures": [],
        "evidence": {
            "before": sections.live_binding["before_snapshot"],
            "after": sections.live_binding["before_snapshot"],
            "observed_keys": observed,
            "expected_payload_keys": list(recipe.request.exact_expected_keys),
            "primary_row_policy": recipe.request.primary_row_policy,
            "raw_row_count": 10,
            "query_bound": {"mode": "take", "value": 10},
            "bound_reached": True,
            "derived_row_policy": recipe.request.derived_row_policy,
            "derived_rows": [],
            "required_keys": list(recipe.request.exact_expected_keys),
            "excluded_keys": list(recipe.oracle.excluded_keys),
            "final_answer_policy": recipe.request.final_answer_policy,
            "required_identity_tokens": required,
            "excluded_identity_tokens": excluded,
            "paired_rows": paired,
            "deduplicated_parent_rows": deduplicated,
            "coverage_summary": coverage,
            "observed_answer_order": order,
            "final_response_sha256": hashlib.sha256(
                answer.encode("utf-8")
            ).hexdigest(),
        },
    }
    validate_object_archived_verification(sections, verification)

    attacks = []
    duplicate_tamper = json.loads(json.dumps(verification))
    duplicate_tamper["evidence"]["observed_keys"] = list(
        recipe.request.exact_expected_keys
    )
    attacks.append(duplicate_tamper)
    bound_tamper = json.loads(json.dumps(verification))
    bound_tamper["evidence"]["bound_reached"] = False
    attacks.append(bound_tamper)
    count_tamper = json.loads(json.dumps(verification))
    count_tamper["evidence"]["deduplicated_parent_rows"][2][
        "children_count"
    ] = 4
    attacks.append(count_tamper)
    coverage_tamper = json.loads(json.dumps(verification))
    coverage_tamper["evidence"]["coverage_summary"][
        "confirmed_sound_count"
    ] = 12
    attacks.append(coverage_tamper)
    for attack in attacks:
        with pytest.raises(ObjectBusinessPlanError):
            validate_object_archived_verification(sections, attack)


def test_get05_archived_verification_binds_ancestor_chain_and_summary(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-GET-05",
        tmp_path,
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    by_key = before.by_key()
    answer_rows = []
    for ordinal, key in enumerate(recipe.request.exact_expected_keys, start=1):
        ancestor = by_key[key]
        answer_rows.append(
            f"| {ordinal} | {ancestor.name} | {ancestor.id} | {ancestor.type} | "
            f"`{ancestor.path}` | {ancestor.children_count} | "
            f"{ancestor.notes or '无'} |"
        )
    answer = "\n".join(
        (
            "| 层级 | 名称 | GUID | 类型 | 完整路径 | childrenCount | 备注 |",
            "|---:|---|---|---|---|---:|---|",
            *answer_rows,
            "类型汇总：恰好 1 个 Random Container、2 个 Actor Mixer、2 个 Work Unit。",
            "并且经过 Default Work Unit。",
        )
    )
    (
        required,
        excluded,
        paired,
        ancestors,
        coverage,
        order,
        failures,
    ) = _verify_query_final_answer(
        recipe.request,
        by_key,
        excluded_keys=recipe.oracle.excluded_keys,
        expected_order_keys=recipe.oracle.expected_order_keys,
        final_response=answer,
    )
    assert failures == ()
    observed = [
        "q5_root",
        "actor_root",
        "q5_movement",
        "actor_dwu",
        "q5_player",
    ]
    verification = {
        "phase": "query",
        "passed": True,
        "failures": [],
        "evidence": {
            "before": sections.live_binding["before_snapshot"],
            "after": sections.live_binding["before_snapshot"],
            "observed_keys": observed,
            "expected_payload_keys": list(recipe.request.exact_expected_keys),
            "primary_row_policy": recipe.request.primary_row_policy,
            "raw_row_count": 5,
            "query_bound": {"mode": "take", "value": 8},
            "bound_reached": False,
            "derived_row_policy": recipe.request.derived_row_policy,
            "derived_rows": [],
            "required_keys": list(recipe.request.exact_expected_keys),
            "excluded_keys": list(recipe.oracle.excluded_keys),
            "final_answer_policy": recipe.request.final_answer_policy,
            "required_identity_tokens": required,
            "excluded_identity_tokens": excluded,
            "paired_rows": paired,
            "deduplicated_parent_rows": ancestors,
            "coverage_summary": coverage,
            "observed_answer_order": order,
            "final_response_sha256": hashlib.sha256(
                answer.encode("utf-8")
            ).hexdigest(),
        },
    }
    validate_object_archived_verification(sections, verification)

    attacks = []
    duplicate_raw = json.loads(json.dumps(verification))
    duplicate_raw["evidence"]["observed_keys"][0] = duplicate_raw["evidence"][
        "observed_keys"
    ][1]
    attacks.append(duplicate_raw)
    for field, value in (
        ("type", "Sound"),
        ("children_count", 99),
        ("path", r"\Wrong"),
        ("notes", "wrong notes"),
    ):
        attack = json.loads(json.dumps(verification))
        attack["evidence"]["deduplicated_parent_rows"][0][field] = value
        attacks.append(attack)
    wrong_order = json.loads(json.dumps(verification))
    wrong_order["evidence"]["observed_answer_order"][:2] = reversed(
        wrong_order["evidence"]["observed_answer_order"][:2]
    )
    attacks.append(wrong_order)
    missing_dwu = json.loads(json.dumps(verification))
    missing_dwu["evidence"]["coverage_summary"][
        "default_work_unit_count"
    ] = 0
    attacks.append(missing_dwu)
    wrong_summary = json.loads(json.dumps(verification))
    wrong_summary["evidence"]["coverage_summary"]["actor_mixer_count"] = 3
    attacks.append(wrong_summary)
    wrong_bound = json.loads(json.dumps(verification))
    wrong_bound["evidence"]["coverage_summary"]["bound_reached"] = True
    attacks.append(wrong_bound)
    wrong_ordinal = json.loads(json.dumps(verification))
    wrong_ordinal["evidence"]["deduplicated_parent_rows"][0]["ordinal"] = 9
    attacks.append(wrong_ordinal)
    wrong_numeric = json.loads(json.dumps(verification))
    wrong_numeric["evidence"]["deduplicated_parent_rows"][0][
        "numeric_values"
    ] = [1.0, 99.0]
    attacks.append(wrong_numeric)
    truncation = json.loads(json.dumps(verification))
    truncation["evidence"]["coverage_summary"]["truncation_claimed"] = True
    attacks.append(truncation)
    decoy = json.loads(json.dumps(verification))
    decoy["evidence"]["excluded_identity_tokens"][0]["id_present"] = True
    attacks.append(decoy)
    for attack in attacks:
        with pytest.raises(ObjectBusinessPlanError):
            validate_object_archived_verification(sections, attack)


def _snapshot_digest(snapshot: dict) -> str:
    payload = {
        "objects": snapshot["objects"],
        "absent_paths": snapshot["absent_paths"],
        "sibling_prefix_rows": snapshot["sibling_prefix_rows"],
    }
    if "override_output_rows" in snapshot:
        payload["override_output_rows"] = snapshot["override_output_rows"]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _mutation_verification(sections) -> dict:
    before = sections.live_binding["before_snapshot"]
    before_by_key = {row["key"]: row for row in before["objects"]}
    expected_rows = sections.delta_rules[0]["expected_objects"]
    resolved: dict[str, dict] = {}
    for index, expected in enumerate(expected_rows, start=1):
        previous = before_by_key.get(expected["key"])
        parent = resolved.get(expected["parent_key"]) or before_by_key.get(
            expected["parent_key"]
        )
        if (
            previous is not None
            and expected["identity_policy"] in {"preserve", "borrowed_snapshot"}
        ):
            row = json.loads(json.dumps(previous))
        else:
            name = expected["requested_name"]
            if expected["identity_policy"] == "new_renamed":
                name = f"{name}_1"
            path = expected["path"]
            if path is None and parent is not None:
                path = f"{parent['path']}\\{name}"
            elif path is None and expected["parent_path"] is not None:
                path = f"{expected['parent_path']}\\{name}"
            row = {
                "key": expected["key"],
                "id": "{" + f"AAAAAAAA-AAAA-AAAA-AAAA-{index:012d}" + "}",
                "name": name,
                "type": expected["object_type"],
                "path": path,
                "parent_id": parent["id"] if parent is not None else None,
                "notes": None,
                "properties": [],
                "references": [],
                "source_language": None,
                "is_included": None,
                "children_count": len(expected["children"]),
                "active_source_id": None,
                "active_source_name": None,
                "active_source_path": None,
            }
        row["parent_id"] = parent["id"] if parent is not None else None
        row["children_count"] = len(expected["children"])
        properties = {
            item["name"]: item["value"] for item in row["properties"]
        }
        references = {
            item["name"]: item["target_id"] for item in row["references"]
        }
        for field in expected["fields"]:
            name = field["name"]
            mode = field["mode"]
            value = field["value"]
            if mode == "object_key_id":
                target = resolved.get(field["value"]) or before_by_key[field["value"]]
                references[name] = target["id"]
            elif mode == "derived_children_count":
                row["children_count"] = len(expected["children"])
            elif mode == "sealed_fixture_snapshot":
                continue
            elif name.startswith("@"):
                properties[name[1:]] = value
            elif name == "notes":
                row["notes"] = value
            elif name == "audioSource:language":
                row["source_language"] = value
            elif name == "isIncluded":
                row["is_included"] = value
            elif name == "parent":
                row["parent_id"] = value
            elif name == "childrenCount":
                row["children_count"] = value
            elif name in {"id", "name", "type", "path"}:
                row[name] = value
            else:
                references[name] = value
        row["properties"] = [
            {"name": name, "value": value}
            for name, value in sorted(properties.items())
        ]
        row["references"] = [
            {"name": name, "target_id": value}
            for name, value in sorted(references.items())
        ]
        resolved[expected["key"]] = row
    identity = sections.delta_rules[1]
    protected = {
        key: before_by_key[key]
        for key in identity["protected_snapshot_keys"]
    }
    return {
        "phase": "after",
        "passed": True,
        "failures": [],
        "evidence": {
            "before": before,
            "after": before,
            "resolved": resolved,
            "expected_resolved_keys": [item["key"] for item in expected_rows],
            "removed_keys": identity["removed_keys"],
            "removed_readback": {key: [] for key in identity["removed_keys"]},
            "protected_keys": identity["protected_snapshot_keys"],
            "protected_before": protected,
            "protected_after": protected,
        },
    }


def _intrinsic_projection(
    row: dict,
    *,
    ignored_derived_fields: tuple[str, ...],
) -> dict:
    result = json.loads(json.dumps(row))
    ignored = set(ignored_derived_fields)
    result["properties"] = [
        item
        for item in result["properties"]
        if f"@{item['name']}" not in ignored
    ]
    if "OutputBus" in ignored:
        result["references"] = [
            item
            for item in result["references"]
            if item["name"] != "OutputBus"
        ]
    return result


def _add_protected_comparisons(
    verification: dict,
    *,
    inherited_keys: set[str],
    strict_volume_pitch_keys: set[str] | None = None,
) -> None:
    evidence = verification["evidence"]
    comparisons = {}
    strict_values = strict_volume_pitch_keys or set()
    for key, before in evidence["protected_before"].items():
        after = evidence["protected_after"][key]
        inherited = key in inherited_keys
        before_override = False if inherited else None
        after_override = False if inherited else None
        ignored_fields = (
            (
                ("OutputBus",)
                if key in strict_values
                else ("@Volume", "@Pitch", "OutputBus")
            )
            if inherited
            else ()
        )
        before_projection = _intrinsic_projection(
            before,
            ignored_derived_fields=ignored_fields,
        )
        after_projection = _intrinsic_projection(
            after,
            ignored_derived_fields=ignored_fields,
        )
        comparisons[key] = {
            "override_output_before": before_override,
            "override_output_after": after_override,
            "ignored_derived_fields": list(ignored_fields),
            "before_projection": before_projection,
            "after_projection": after_projection,
            "passed": before_projection == after_projection,
        }
    evidence["protected_comparisons"] = comparisons


def test_archived_set03_accepts_only_reviewed_inherited_effective_delta(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-SET-03", tmp_path
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    verification = _mutation_verification(sections)
    evidence = verification["evidence"]
    evidence["protected_after"] = json.loads(
        json.dumps(evidence["protected_after"])
    )
    bus_ids = {
        "day_child": evidence["protected_before"]["ambience_bus"]["id"],
        "night_child": evidence["protected_before"]["ambience_bus"]["id"],
        "storm_child": evidence["protected_before"]["weather_bus"]["id"],
    }
    for key, bus_id in bus_ids.items():
        after = json.loads(json.dumps(evidence["protected_before"][key]))
        parent = evidence["resolved"][key.removesuffix("_child")]
        after["properties"] = json.loads(json.dumps(parent["properties"]))
        after["references"] = [
            {"name": "OutputBus", "target_id": bus_id}
        ]
        evidence["protected_after"][key] = after
    _add_protected_comparisons(
        verification,
        inherited_keys={"day_child", "night_child", "storm_child"},
    )

    validate_object_archived_verification(sections, verification)


def test_archived_set03_keeps_stable_noninherited_volume_pitch_strict(
    tmp_path: Path,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-SET-03", tmp_path
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    verification = _mutation_verification(sections)
    evidence = verification["evidence"]
    evidence["protected_after"] = json.loads(
        json.dumps(evidence["protected_after"])
    )
    bus_ids = {
        "day_child": evidence["protected_before"]["ambience_bus"]["id"],
        "night_child": evidence["protected_before"]["ambience_bus"]["id"],
        "storm_child": evidence["protected_before"]["weather_bus"]["id"],
    }
    protected_keys = set(bus_ids)
    for key, bus_id in bus_ids.items():
        after = json.loads(json.dumps(evidence["protected_before"][key]))
        after["references"] = [{"name": "OutputBus", "target_id": bus_id}]
        evidence["protected_after"][key] = after
    _add_protected_comparisons(
        verification,
        inherited_keys=protected_keys,
        strict_volume_pitch_keys=protected_keys,
    )

    validate_object_archived_verification(sections, verification)


@pytest.mark.parametrize(
    "tamper",
    (
        "notes",
        "effective-volume",
        "structure",
        "override",
        "explicit-reference",
        "forged-projection",
    ),
)
def test_archived_set03_rejects_intrinsic_protected_tampering(
    tmp_path: Path,
    tamper: str,
) -> None:
    scenario, recipe, protocol, before, manifest = _case(
        "OBJ22-F-SET-03", tmp_path
    )
    sections = compile_object_business_plan(
        scenario,
        recipe,
        protocol,
        before,
        manifest,
    )
    verification = _mutation_verification(sections)
    evidence = verification["evidence"]
    evidence["protected_after"] = json.loads(
        json.dumps(evidence["protected_after"])
    )
    key = "day_child"
    bus_id = evidence["protected_before"]["ambience_bus"]["id"]
    after = json.loads(json.dumps(evidence["protected_before"][key]))
    after["properties"] = json.loads(
        json.dumps(evidence["resolved"]["day"]["properties"])
    )
    after["references"] = [{"name": "OutputBus", "target_id": bus_id}]
    evidence["protected_after"][key] = after
    inherited_keys = {"day_child", "night_child", "storm_child"}
    _add_protected_comparisons(
        verification,
        inherited_keys=inherited_keys,
    )
    comparison = evidence["protected_comparisons"][key]
    if tamper == "notes":
        after["notes"] = "tampered"
    elif tamper == "effective-volume":
        next(
            row for row in after["properties"] if row["name"] == "Volume"
        )["value"] = -7.0
    elif tamper == "structure":
        after["parent_id"] = evidence["resolved"]["night"]["id"]
    elif tamper == "override":
        comparison["override_output_after"] = True
        comparison["ignored_derived_fields"] = []
    elif tamper == "explicit-reference":
        comparison["override_output_before"] = True
        comparison["override_output_after"] = True
        comparison["ignored_derived_fields"] = []
    else:
        comparison["after_projection"] = comparison["before_projection"]
        after["notes"] = "tampered"

    with pytest.raises(ObjectBusinessPlanError):
        validate_object_archived_verification(sections, verification)
