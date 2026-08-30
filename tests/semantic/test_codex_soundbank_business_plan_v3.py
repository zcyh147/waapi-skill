from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from types import MappingProxyType

import pytest

from tests.semantic.support.codex_eval_protocol_v3 import (
    StructuredRefusal,
    build_direct_protocol,
    build_transaction_protocol,
    topic_schema_step,
    wait_topic_step,
)
from tests.semantic.support.codex_soundbank_business_plan_v3 import (
    TOPIC_ACK_CONTRACT,
    TOPIC_ACK_REQUIREMENT_CONTRACT,
    SoundBankBusinessPlanError,
    _archive_output_policy,
    _artifact_relative,
    _relative_is_within,
    _tree_by_relative,
    _tree_maps_equal,
    _verify_files,
    compile_soundbank_business_plan,
    parse_soundbank_business_plan_sections,
    soundbank_archive_identity,
    validate_soundbank_archived_verification,
    validate_soundbank_business_plan,
    validate_soundbank_business_plan_archive,
)
from tests.semantic.support.codex_soundbank_runtime_v3 import (
    OPERATION_REQUEST_CONTRACT,
    PROCESS_REFUSAL_ERROR_CODE,
    SOUNDBANK_TOPIC,
    BankState,
    DefinitionDocumentPlan,
    DefinitionRowPlan,
    ExpectedArtifact,
    ExternalSourceDocument,
    ExternalSourceRow,
    FileProof,
    MaterializedSoundBankCase,
    ObjectFixture,
    ObjectState,
    SoundBankBlueprint,
    SoundBankFixture,
    SoundBankSnapshot,
    TopicExpectedEvent,
    TopicPlan,
    TopicPublisher,
    TreeEntry,
)


APIS = (
    "ak.wwise.core.soundbank.generate",
    "ak.wwise.core.soundbank.processDefinitionFiles",
    "ak.wwise.core.soundbank.convertExternalSources",
    "ak.wwise.core.soundbank.setInclusions",
    SOUNDBANK_TOPIC,
)
IDS = tuple(f"O22-SB-{kind}-{index:02d}" for kind in ("GENERATE", "PROCESS-DEF", "CONVERT-EXT", "SET-INCLUSIONS", "GENERATED") for index in range(1, 6))


def _request(api: str, arguments: MappingProxyType | dict[str, object]) -> MappingProxyType:
    operations = {
        "ak.wwise.core.soundbank.generate": "soundbank.generate",
        "ak.wwise.core.soundbank.processDefinitionFiles": "soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.convertExternalSources": "soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.setInclusions": "soundbank.setInclusions",
    }
    return MappingProxyType(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": operations[api],
            "arguments": dict(arguments),
        }
    )


def _case(api: str, scenario_id: str, root: Path, *, refusal: bool = False, topic: bool = False):
    root.mkdir(parents=True, exist_ok=True)
    source = root / "input.tsv"; source.write_text("Bank\tEvent\tHero\n", encoding="utf-8")
    output = root / "Bank.bnk"; output.write_bytes(b"BKHD")
    proof = FileProof(str(source), source.name, source.stat().st_size, _sha(source), source.stat().st_mtime_ns)
    tree = TreeEntry(output.name, output.stat().st_size, _sha(output), output.stat().st_mtime_ns)
    bank = SoundBankFixture("Bank", r"\SoundBanks\Default Work Unit\Bank", "existing_soundbank", (), False)
    definition = DefinitionDocumentPlan("input.tsv", source, (DefinitionRowPlan("Bank", "Event", "event", "Hero", "Event", "name", "runner_writes_double_quoted_literal_name", (), "resolved"),))
    external = ExternalSourceDocument("external.wsources", source, (ExternalSourceRow(source, None, "external.wem", None),))
    artifact = ExpectedArtifact("bank", output, "Bank", "Windows", "SFX", True)
    topic_count = {"01": 3, "02": 3, "03": 2, "04": 4, "05": 1}.get(scenario_id[-2:], 1)
    count = 0 if refusal else topic_count if topic else 1
    event_fixture = ObjectFixture("event", "Hero", "Event", r"\Events\Default Work Unit", r"\Events\Default Work Unit\Hero")
    asset_spec = MappingProxyType({"soundbank": "Bank", "expected_after": ({"object": "Hero", "filters": ()},)}) if api == APIS[3] else MappingProxyType({})
    reviewed = MappingProxyType({"id": scenario_id, "api": api, "asset_spec": asset_spec})
    blue = SoundBankBlueprint(scenario_id, api, "2022.1", SimpleNamespace(fixture=reviewed), root / "p.wproj", root, root, root, root, asset_spec, (event_fixture,), (), (bank,), (definition,), (external,), count, PROCESS_REFUSAL_ERROR_CODE if refusal else None)
    topic_plan = None
    operation_arguments: dict[str, object]
    if api in {APIS[0], SOUNDBANK_TOPIC}:
        operation_arguments = {
            "soundbanks": [
                {"name": "Bank", "artifact_expectation": "nonlocalized"}
            ],
            "platforms": ["Windows"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": str(root),
        }
    elif api == APIS[1]:
        operation_arguments = {
            "files": [str(source)],
            "io_root": str(root),
        }
    elif api == APIS[2]:
        operation_arguments = {
            "sources": [
                {
                    "input": str(source),
                    "platform": "Windows",
                    "output": str(root / "external.wem"),
                }
            ],
            "io_root": str(root),
        }
    else:
        operation_arguments = {
            "soundbank": {"kind": "path", "value": bank.path},
            "mode": "replace",
            "inclusions": [
                {
                    "object": {"kind": "path", "value": event_fixture.path},
                    "filters": ["events"],
                }
            ],
        }
    requests = () if topic else (_request(api, operation_arguments),)
    if topic:
        events = tuple(TopicExpectedEvent("Bank", "Windows", "SFX", f"{{00000000-0000-0000-0000-{i:012x}}}", f"{{00000000-0000-0000-0001-{i:012x}}}", f"{{00000000-0000-0000-0002-{i:012x}}}") for i in range(1, topic_count + 1))
        topic_plan = TopicPlan(
            api,
            topic_count,
            MappingProxyType({}),
            MappingProxyType({}),
            events,
            (TopicPublisher(_request(APIS[0], operation_arguments), events),),
            True,
            True,
            True,
        )
    dynamic_roots = (
        ((root / "io" / "cache").resolve(strict=False),)
        if api in {APIS[0], SOUNDBANK_TOPIC}
        else ()
    )
    materialized = MaterializedSoundBankCase(blue, MappingProxyType({}), MappingProxyType({}), requests, topic_plan, (proof,), (artifact,), dynamic_roots, MappingProxyType({"bank:Bank": "{00000000-0000-0000-0000-000000000010}", "event": "{00000000-0000-0000-0000-000000000040}"}), MappingProxyType({"bank:Bank": 1}), MappingProxyType({}), MappingProxyType({"Windows": "{00000000-0000-0000-0000-000000000020}"}), MappingProxyType({"SFX": "{00000000-0000-0000-0000-000000000030}"}))
    snapshot = SoundBankSnapshot(scenario_id, (ObjectState("event", "{00000000-0000-0000-0000-000000000040}", r"\Events\Default Work Unit\Hero", "Event"),), (BankState("Bank", "{00000000-0000-0000-0000-000000000010}", (("{00000000-0000-0000-0000-000000000040}", ()),)),), (), (proof,), (tree,))
    if topic:
        protocol = build_direct_protocol(
            [
                topic_schema_step("soundbank.generated.schema", api),
                wait_topic_step(
                    "soundbank.generated.wait",
                    api,
                    version="2022.1",
                    event_count=topic_count,
                    match={},
                    options={},
                )
            ]
        )
    else:
        protocol = build_transaction_protocol(
            requests,
            refusal=(
                StructuredRefusal(
                    PROCESS_REFUSAL_ERROR_CODE,
                    result_command="preview-from-draft",
                )
                if refusal
                else None
            ),
        )
    return materialized, snapshot, protocol


@pytest.mark.parametrize("scenario_id", IDS)
def test_all_25_real_soundbank_ids_compile_and_recompute(scenario_id: str, tmp_path: Path) -> None:
    if "GENERATE" in scenario_id and "GENERATED" not in scenario_id: api = APIS[0]
    elif "PROCESS" in scenario_id: api = APIS[1]
    elif "CONVERT" in scenario_id: api = APIS[2]
    elif "INCLUSIONS" in scenario_id: api = APIS[3]
    else: api = APIS[4]
    refusal = scenario_id.endswith("PROCESS-DEF-05")
    topic = api == SOUNDBANK_TOPIC
    materialized, before, protocol = _case(api, scenario_id, tmp_path / scenario_id, refusal=refusal, topic=topic)
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    validate_soundbank_business_plan(sections, materialized, before, protocol, verify_files=True)
    validate_soundbank_business_plan_archive(parse_soundbank_business_plan_sections(sections.writer_kwargs()), protocol, scenario=soundbank_archive_identity(materialized))
    assert sections.static_expectation["scenario_id"] == scenario_id
    assert (sections.payload_bindings["primary_steps"] == []) == refusal


def test_soundbank_file_verification_rejects_a_hard_linked_asset(
    tmp_path: Path,
) -> None:
    source = tmp_path / "definition.json"
    source.write_bytes(b'{"soundbanks":[]}')
    (tmp_path / "definition-alias.json").hardlink_to(source)
    proof = SimpleNamespace(
        path=str(source),
        size=source.stat().st_size,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )

    with pytest.raises(SoundBankBusinessPlanError, match="input file drifted"):
        _verify_files((proof,))


def test_rejects_wrong_bank_platform_language_file_artifact_definition_and_inclusion(tmp_path: Path) -> None:
    materialized, before, protocol = _case(APIS[0], "O22-SB-GENERATE-01", tmp_path)
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    for field, value in (
        ("live_binding", {**sections.live_binding, "platform_ids": {"Mac": "wrong"}}),
        ("live_binding", {**sections.live_binding, "language_ids": {"English": "wrong"}}),
        ("live_binding", {**sections.live_binding, "input_files": [{**sections.live_binding["input_files"][0], "sha256": "0" * 64}]}),
        ("static_expectation", {**sections.static_expectation, "expected_artifacts": []}),
        ("static_expectation", {**sections.static_expectation, "definitions": []}),
        ("delta_rules", (MappingProxyType({"enum": "bad"}),)),
    ):
        with pytest.raises(SoundBankBusinessPlanError):
            validate_soundbank_business_plan(replace(sections, **{field: MappingProxyType(value) if isinstance(value, dict) else value}), materialized, before, protocol)


def test_topic_rejects_event_n_plus_one_and_publisher_as_primary(tmp_path: Path) -> None:
    materialized, before, protocol = _case(SOUNDBANK_TOPIC, "O22-SB-GENERATED-04", tmp_path, topic=True)
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    requirement = sections.live_binding["topic"]["subscription_ack_requirement"]
    assert requirement == {
        "contract": TOPIC_ACK_REQUIREMENT_CONTRACT,
        "ack_contract": TOPIC_ACK_CONTRACT,
        "step_name": "soundbank.generated.wait",
        "topic": SOUNDBANK_TOPIC,
        "fresh_exclusive_path_required": True,
        "publisher_requires_valid_ack": True,
    }
    assert "soundbank.topic.subscribe_ack_before_publish" in sections.assertion_ids
    assert sections.delta_rules[0]["subscription_ack_requirement"] == requirement
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_business_plan(replace(sections, payload_bindings=MappingProxyType({"primary_steps": ["publisher.01"], "verification_steps": []})), materialized, before, protocol)
    bad = dict(sections.live_binding); bad_topic = dict(bad["topic"]); bad_topic["event_count"] = 3; bad["topic"] = bad_topic
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_business_plan(replace(sections, live_binding=MappingProxyType(bad)), materialized, before, protocol)
    bad = dict(sections.live_binding)
    bad_topic = dict(bad["topic"])
    bad_topic["subscription_ack_requirement"] = {
        **requirement,
        "topic": "ak.wwise.core.object.created",
    }
    bad["topic"] = bad_topic
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_business_plan(
            replace(sections, live_binding=MappingProxyType(bad)),
            materialized,
            before,
            protocol,
        )
    after = _after(sections)
    topic_result = {"scenario_id": sections.static_expectation["scenario_id"], "passed": True, "failures": [], "expected_keys": sections.delta_rules[0]["expected_event_keys"], "observed_keys": sections.delta_rules[0]["expected_event_keys"]}
    validate_soundbank_archived_verification(sections, {"topic": topic_result, "artifacts": _verification(sections, phase="topic_artifacts", after=after)})
    validate_soundbank_archived_verification(
        sections,
        {
            "topic": {
                **topic_result,
                "observed_keys": list(reversed(topic_result["observed_keys"])),
            },
            "artifacts": _verification(
                sections,
                phase="topic_artifacts",
                after=after,
            ),
        },
    )
    duplicate_and_missing = list(topic_result["observed_keys"])
    duplicate_and_missing[-1] = duplicate_and_missing[0]
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_archived_verification(
            sections,
            {
                "topic": {
                    **topic_result,
                    "observed_keys": duplicate_and_missing,
                },
                "artifacts": _verification(
                    sections,
                    phase="topic_artifacts",
                    after=after,
                ),
            },
        )
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_archived_verification(sections, {"topic": {**topic_result, "observed_keys": [*topic_result["observed_keys"], ["n-plus-one", "platform", "language"]]}, "artifacts": _verification(sections, phase="topic_artifacts", after=after)})
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_archived_verification(sections, {"topic": {**topic_result, "extra": True}, "artifacts": _verification(sections, phase="topic_artifacts", after=after)})


def test_archive_artifact_relative_path_uses_typed_windows_containment() -> None:
    outputs = {
        "bank.bnk": {"relative_path": "Bank.bnk"},
        "nested/bank.bnk": {"relative_path": "nested/Bank.bnk"},
    }

    assert _artifact_relative(
        r"C:\campaign\nested\Bank.bnk",
        r"C:\campaign",
        outputs,
    ) == "nested/bank.bnk"
    assert _artifact_relative(
        r"C:\campaign\Bank.bnk",
        r"C:\campaign",
        outputs,
    ) == "bank.bnk"
    with pytest.raises(SoundBankBusinessPlanError, match="outside output authority"):
        _artifact_relative(
            r"C:\other\Bank.bnk",
            r"C:\campaign",
            outputs,
        )


@pytest.mark.parametrize(
    ("io_root", "artifact", "managed"),
    (
        (
            r"C:\Campaign",
            r"C:\Campaign\outputs\Windows\Dialogue.wem",
            r"C:\Campaign\outputs\Windows\Wwise.dat",
        ),
        (
            r"\\StudioNas\Share\Campaign",
            r"\\StudioNas\Share\Campaign\outputs\Dialogue.wem",
            r"\\StudioNas\Share\Campaign\outputs\Wwise.dat",
        ),
    ),
)
def test_archive_output_policy_parses_windows_and_unc_off_host(
    io_root: str,
    artifact: str,
    managed: str,
) -> None:
    static = {
        "api": "ak.wwise.core.soundbank.convertExternalSources",
        "io_root": io_root,
        "dynamic_output_policy": {
            "enum": "none",
            "roots": [],
            "allowed_suffixes": [],
            "allowed_exact_names": [],
            "require_nonempty": False,
            "creation_only": False,
        },
        "expected_artifacts": [
            {
                "kind": "external",
                "path": artifact,
            }
        ],
        "managed_side_effects": [managed],
    }

    parsed_root, flavor, dynamic_roots, managed_paths = _archive_output_policy(static)

    assert parsed_root == io_root
    assert flavor == "windows"
    assert dynamic_roots == ()
    assert managed_paths == (managed,)


def test_archive_relative_containment_follows_source_filesystem_case_rules() -> None:
    assert _relative_is_within(
        "IO/CACHE/SFX/generated.wem",
        "io/cache",
        flavor="windows",
    )
    assert not _relative_is_within(
        "IO/CACHE/SFX/generated.wem",
        "io/cache",
        flavor="posix",
    )


def test_windows_output_policy_rejects_case_alias_overlap() -> None:
    static = {
        "api": "ak.wwise.core.soundbank.generate",
        "io_root": r"C:\Campaign",
        "dynamic_output_policy": {
            "enum": "soundbank_generation_cache_v1",
            "roots": ["io/cache"],
            "allowed_suffixes": [".wem"],
            "allowed_exact_names": ["Wwise.dat"],
            "require_nonempty": True,
            "creation_only": True,
        },
        "expected_artifacts": [
            {
                "kind": "bank",
                "path": r"C:\Campaign\IO\CACHE\Bank.bnk",
            }
        ],
        "managed_side_effects": [],
    }

    with pytest.raises(SoundBankBusinessPlanError, match="overlaps"):
        _archive_output_policy(static)


def test_archive_output_tree_canonicalizes_windows_relative_rows() -> None:
    row = {
        "relative_path": r"outputs\Windows\Bank.bnk",
        "size": 4,
        "sha256": "a" * 64,
        "mtime_ns": 1,
    }

    indexed = _tree_by_relative([row], source_flavor="windows")

    assert set(indexed) == {"outputs/windows/bank.bnk"}
    assert indexed["outputs/windows/bank.bnk"]["relative_path"] == (
        "outputs/Windows/Bank.bnk"
    )
    with pytest.raises(SoundBankBusinessPlanError, match="output tree is invalid"):
        _tree_by_relative(
            [
                row,
                {
                    **row,
                    "relative_path": "OUTPUTS/windows/bank.BNK",
                },
            ],
            source_flavor="windows",
        )


def test_archive_tree_keeps_posix_case_distinct_and_windows_delta_stable() -> None:
    upper = {
        "relative_path": "outputs/Bank.bnk",
        "size": 4,
        "sha256": "a" * 64,
        "mtime_ns": 1,
    }
    lower = {
        **upper,
        "relative_path": "outputs/bank.bnk",
    }

    posix = _tree_by_relative(
        [upper, lower],
        source_flavor="posix",
    )
    windows_before = _tree_by_relative(
        [upper],
        source_flavor="windows",
    )
    windows_after = _tree_by_relative(
        [lower],
        source_flavor="windows",
    )

    assert set(posix) == {"outputs/Bank.bnk", "outputs/bank.bnk"}
    assert _tree_maps_equal(
        windows_before,
        windows_after,
        source_flavor="windows",
    )
    assert not _tree_maps_equal(
        _tree_by_relative([upper], source_flavor="posix"),
        _tree_by_relative([lower], source_flavor="posix"),
        source_flavor="posix",
    )


def test_archived_verification_validates_project_file_path_set(
    tmp_path: Path,
) -> None:
    materialized, before, protocol = _case(
        APIS[0],
        "O22-SB-GENERATE-01",
        tmp_path,
    )
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    after = _after(sections)
    after["project_files"] = [
        {
            "relative_path": "../escaped.wwu",
            "size": 4,
            "sha256": "a" * 64,
            "mtime_ns": 1,
        }
    ]

    with pytest.raises(SoundBankBusinessPlanError, match="project tree is invalid"):
        validate_soundbank_archived_verification(
            sections,
            _verification(sections, phase="after_execution", after=after),
        )


def test_refusal_requires_zero_dispatch_unchanged_snapshot_and_exact_error(tmp_path: Path) -> None:
    materialized, before, protocol = _case(APIS[1], "O22-SB-PROCESS-DEF-05", tmp_path, refusal=True)
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    assert sections.payload_bindings["primary_steps"] == []
    evidence = _verification(sections, phase="zero_dispatch", after=sections.live_binding["before_snapshot"])
    validate_soundbank_archived_verification(sections, evidence)
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_archived_verification(sections, {**evidence, "after": {**evidence["after"], "output_files": []}})


def test_refusal_archive_validates_unchanged_path_sets(tmp_path: Path) -> None:
    materialized, before, protocol = _case(
        APIS[1],
        "O22-SB-PROCESS-DEF-05",
        tmp_path,
        refusal=True,
    )
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    live = _copy(sections.live_binding)
    live["before_snapshot"]["output_files"][0]["relative_path"] = "../Bank.bnk"
    live["before_snapshot_sha256"] = _digest_value(live["before_snapshot"])
    corrupted = replace(sections, live_binding=MappingProxyType(live))
    evidence = _verification(
        corrupted,
        phase="zero_dispatch",
        after=_copy(live["before_snapshot"]),
    )

    with pytest.raises(SoundBankBusinessPlanError, match="output tree is invalid"):
        validate_soundbank_archived_verification(corrupted, evidence)


def test_function_archive_accepts_control_artifact_absent_before_and_after(
    tmp_path: Path,
) -> None:
    materialized, before, protocol = _case(
        APIS[0],
        "O22-SB-GENERATE-02",
        tmp_path,
    )
    missing_control = ExpectedArtifact(
        "control",
        tmp_path / "Control_Not_Requested.bnk",
        "Control_Not_Requested",
        "Windows",
        None,
        False,
    )
    materialized = replace(
        materialized,
        expected_artifacts=(*materialized.expected_artifacts, missing_control),
    )
    sections = compile_soundbank_business_plan(materialized, before, protocol)

    validate_soundbank_archived_verification(
        sections,
        _verification(sections, phase="after_execution", after=_after(sections)),
    )


def test_definition_archive_maps_closed_filters_to_canonical_inclusions(
    tmp_path: Path,
) -> None:
    materialized, before, protocol = _case(
        APIS[1],
        "O22-SB-PROCESS-DEF-02",
        tmp_path,
    )
    original = materialized.blueprint.definitions[0]
    definition = DefinitionDocumentPlan(
        original.name,
        original.path,
        (
            DefinitionRowPlan(
                "Bank",
                "Event",
                "event",
                "Hero",
                "Event",
                "name",
                "runner_writes_double_quoted_literal_name",
                ("Event", "Structure", "Media"),
                "unique",
            ),
        ),
    )
    materialized = replace(
        materialized,
        blueprint=replace(materialized.blueprint, definitions=(definition,)),
    )
    debug_id = "{00000000-0000-0000-0000-000000000099}"
    before = replace(
        before,
        banks=(
            replace(
                before.banks[0],
                inclusions=((debug_id, ("events",)),),
            ),
        ),
    )
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    after = _after(sections)
    after["banks"] = [
        {
            **row,
            "inclusions": [
                [
                    "{00000000-0000-0000-0000-000000000040}",
                    ["events", "media", "structures"],
                ],
                [debug_id, ["events"]],
            ],
        }
        for row in after["banks"]
    ]

    validate_soundbank_archived_verification(
        sections,
        _verification(sections, phase="after_execution", after=after),
    )

    lost_preexisting = _copy(after)
    lost_preexisting["banks"][0]["inclusions"] = [
        row
        for row in lost_preexisting["banks"][0]["inclusions"]
        if row[0] != debug_id
    ]
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_archived_verification(
            sections,
            _verification(
                sections,
                phase="after_execution",
                after=lost_preexisting,
            ),
        )


@pytest.mark.parametrize(
    "filters",
    (
        [],
        ["Event", "Event"],
        ["Event", "Unknown"],
        ["events", "Media"],
        "Structure",
    ),
)
def test_definition_archive_rejects_nonclosed_filters(
    tmp_path: Path,
    filters: object,
) -> None:
    materialized, before, protocol = _case(
        APIS[1],
        "O22-SB-PROCESS-DEF-02",
        tmp_path,
    )
    original = materialized.blueprint.definitions[0]
    definition = DefinitionDocumentPlan(
        original.name,
        original.path,
        (
            DefinitionRowPlan(
                "Bank",
                "Event",
                "event",
                "Hero",
                "Event",
                "name",
                "runner_writes_double_quoted_literal_name",
                ("Event", "Structure", "Media"),
                "unique",
            ),
        ),
    )
    materialized = replace(
        materialized,
        blueprint=replace(materialized.blueprint, definitions=(definition,)),
    )
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    static = _copy(sections.static_expectation)
    static["definitions"][0]["rows"][0]["filters"] = filters
    sections = replace(
        sections,
        static_expectation=MappingProxyType(static),
    )
    after = _after(sections)
    after["banks"] = [
        {
            **row,
            "inclusions": [
                [
                    "{00000000-0000-0000-0000-000000000040}",
                    ["events", "media", "structures"],
                ]
            ],
        }
        for row in after["banks"]
    ]

    with pytest.raises(SoundBankBusinessPlanError, match="definition filters"):
        validate_soundbank_archived_verification(
            sections,
            _verification(sections, phase="after_execution", after=after),
        )


def test_topic_archive_allows_only_sealed_nonempty_dynamic_cache_artifacts(
    tmp_path: Path,
) -> None:
    materialized, before, protocol = _case(
        SOUNDBANK_TOPIC,
        "O22-SB-GENERATED-04",
        tmp_path,
        topic=True,
    )
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    after = _after(sections)
    cache_relative = sections.static_expectation["dynamic_output_policy"]["roots"][0]
    after["output_files"] = [
        *after["output_files"],
        {
            "relative_path": f"{cache_relative}/SFX/generated.wem",
            "size": 4,
            "sha256": "a" * 64,
            "mtime_ns": 1,
        },
        {
            "relative_path": f"{cache_relative}/SFX/Wwise.dat",
            "size": 4,
            "sha256": "b" * 64,
            "mtime_ns": 1,
        },
    ]
    expected_keys = sections.delta_rules[0]["expected_event_keys"]
    topic_result = {
        "scenario_id": sections.static_expectation["scenario_id"],
        "passed": True,
        "failures": [],
        "expected_keys": expected_keys,
        "observed_keys": list(reversed(expected_keys)),
    }
    verification = {
        "topic": topic_result,
        "artifacts": _verification(
            sections,
            phase="topic_artifacts",
            after=after,
        ),
    }
    validate_soundbank_archived_verification(sections, verification)

    empty = _copy(verification)
    empty["artifacts"]["after"]["output_files"][-2]["size"] = 0
    with pytest.raises(SoundBankBusinessPlanError, match="dynamic cache"):
        validate_soundbank_archived_verification(sections, empty)

    outside = _copy(verification)
    outside["artifacts"]["after"]["output_files"][-2][
        "relative_path"
    ] = "unsealed/generated.wem"
    with pytest.raises(SoundBankBusinessPlanError, match="outside sealed"):
        validate_soundbank_archived_verification(sections, outside)

    unknown = _copy(verification)
    unknown["artifacts"]["after"]["output_files"].append(
        {
            "relative_path": "unsealed/surprise.bin",
            "size": 4,
            "sha256": "c" * 64,
            "mtime_ns": 1,
        }
    )
    with pytest.raises(SoundBankBusinessPlanError, match="unrecognized"):
        validate_soundbank_archived_verification(sections, unknown)


@pytest.mark.parametrize(
    ("scenario_id", "relative_outputs"),
    (
        (
            "O22-SB-CONVERT-EXT-01",
            (
                "outputs/Windows/Chinese/Chapter14/Dialogue.wem",
                "outputs/Windows/English/Chapter14/Dialogue.wem",
                "outputs/Windows/Japanese/Chapter14/Dialogue.wem",
            ),
        ),
        (
            "O22-SB-CONVERT-EXT-02",
            (
                "outputs/Windows/Weapons/Rifle/Rifle.wem",
                "outputs/Windows/Weapons/Shotgun/Shotgun.wem",
                "outputs/Mac/Weapons/Rifle/Rifle.wem",
                "outputs/Mac/Weapons/Shotgun/Shotgun.wem",
            ),
        ),
        (
            "O22-SB-CONVERT-EXT-03",
            (
                "outputs/Windows/Nested/Deep/Ambience/Cave.wem",
                "outputs/Windows/Nested/Deep/Ambience/Forest.wem",
            ),
        ),
        (
            "O22-SB-CONVERT-EXT-04",
            (
                "outputs/Windows/UI/Menu/Confirm.wem",
                "outputs/Windows/UI/Menu/Cancel.wem",
            ),
        ),
        (
            "O22-SB-CONVERT-EXT-05",
            (
                "outputs/Windows/Abilities/Fire/Fire.wem",
                "outputs/Windows/Abilities/Heal/Heal.wem",
                "outputs/Windows/Abilities/Ice/Ice.wem",
            ),
        ),
    ),
)
def test_convert_archive_seals_exact_nonempty_wwise_indexes_for_all_five_cases(
    tmp_path: Path,
    scenario_id: str,
    relative_outputs: tuple[str, ...],
) -> None:
    materialized, before, protocol = _case(
        APIS[2],
        scenario_id,
        tmp_path / scenario_id,
    )
    artifacts = tuple(
        ExpectedArtifact(
            "external",
            (materialized.blueprint.io_root / relative).resolve(strict=False),
            None,
            "Windows",
            None,
            True,
        )
        for relative in relative_outputs
    )
    materialized = replace(materialized, expected_artifacts=artifacts)
    sections = compile_soundbank_business_plan(materialized, before, protocol)

    expected_indexes = sorted(
        {
            str((artifact.path.parent / "Wwise.dat").resolve(strict=False))
            for artifact in artifacts
        }
    )
    assert sections.static_expectation["managed_side_effects"] == expected_indexes

    after = _copy(sections.live_binding["before_snapshot"])
    after["output_files"].extend(
        [
            {
                "relative_path": artifact.path.relative_to(
                    materialized.blueprint.io_root
                ).as_posix(),
                "size": 4,
                "sha256": f"{index:x}" * 64,
                "mtime_ns": index,
            }
            for index, artifact in enumerate(artifacts, 1)
        ]
    )
    after["output_files"].extend(
        [
            {
                "relative_path": Path(path)
                .relative_to(materialized.blueprint.io_root)
                .as_posix(),
                "size": 8,
                "sha256": f"{index + 8:x}"[-1] * 64,
                "mtime_ns": index + 10,
            }
            for index, path in enumerate(expected_indexes, 1)
        ]
    )
    validate_soundbank_archived_verification(
        sections,
        _verification(sections, phase="after_execution", after=after),
    )


def test_convert_archive_rejects_missing_empty_misplaced_and_unexpected_outputs(
    tmp_path: Path,
) -> None:
    materialized, before, protocol = _case(
        APIS[2],
        "O22-SB-CONVERT-EXT-05",
        tmp_path,
    )
    artifacts = (
        ExpectedArtifact(
            "external",
            (tmp_path / "outputs/Abilities/Fire/Fire.wem").resolve(strict=False),
            None,
            "Windows",
            None,
            True,
        ),
        ExpectedArtifact(
            "external",
            (tmp_path / "outputs/Abilities/Ice/Ice.wem").resolve(strict=False),
            None,
            "Windows",
            None,
            True,
        ),
    )
    materialized = replace(materialized, expected_artifacts=artifacts)
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    after = _copy(sections.live_binding["before_snapshot"])
    artifact_rows = [
        {
            "relative_path": artifact.path.relative_to(tmp_path).as_posix(),
            "size": 4,
            "sha256": f"{index:x}" * 64,
            "mtime_ns": index,
        }
        for index, artifact in enumerate(artifacts, 1)
    ]
    index_rows = [
        {
            "relative_path": Path(path).relative_to(tmp_path).as_posix(),
            "size": 8,
            "sha256": f"{index + 8:x}"[-1] * 64,
            "mtime_ns": index + 10,
        }
        for index, path in enumerate(
            sections.static_expectation["managed_side_effects"],
            1,
        )
    ]
    after["output_files"].extend([*artifact_rows, *index_rows])

    missing = _copy(after)
    missing["output_files"].remove(index_rows[0])
    with pytest.raises(SoundBankBusinessPlanError, match="side effect is absent"):
        validate_soundbank_archived_verification(
            sections,
            _verification(sections, phase="after_execution", after=missing),
        )

    empty = _copy(after)
    next(
        row
        for row in empty["output_files"]
        if row["relative_path"] == index_rows[0]["relative_path"]
    )["size"] = 0
    with pytest.raises(SoundBankBusinessPlanError, match="side effect is empty"):
        validate_soundbank_archived_verification(
            sections,
            _verification(sections, phase="after_execution", after=empty),
        )

    misplaced = _copy(after)
    misplaced["output_files"].append(
        {
            "relative_path": "outputs/Abilities/Wwise.dat",
            "size": 8,
            "sha256": "c" * 64,
            "mtime_ns": 20,
        }
    )
    with pytest.raises(SoundBankBusinessPlanError, match="outside sealed"):
        validate_soundbank_archived_verification(
            sections,
            _verification(sections, phase="after_execution", after=misplaced),
        )

    unexpected = _copy(after)
    unexpected["output_files"].append(
        {
            "relative_path": "outputs/Abilities/Fire/surprise.bin",
            "size": 8,
            "sha256": "d" * 64,
            "mtime_ns": 21,
        }
    )
    with pytest.raises(SoundBankBusinessPlanError, match="unrecognized"):
        validate_soundbank_archived_verification(
            sections,
            _verification(sections, phase="after_execution", after=unexpected),
        )

    parsed = parse_soundbank_business_plan_sections(sections.writer_kwargs())
    static = _copy(parsed.static_expectation)
    static["managed_side_effects"] = [
        str((tmp_path / "outputs/Abilities/Wwise.dat").resolve(strict=False))
    ]
    fixture = {
        "kind": parsed.fixture_spec["kind"],
        "sha256": _plan_digest(static, parsed.live_binding),
    }
    with pytest.raises(SoundBankBusinessPlanError, match="side effects drifted"):
        validate_soundbank_business_plan_archive(
            replace(
                parsed,
                static_expectation=MappingProxyType(static),
                fixture_spec=MappingProxyType(fixture),
            ),
            protocol,
            scenario=soundbank_archive_identity(materialized),
        )


def test_archive_parser_protocol_and_cross_api_drift(tmp_path: Path) -> None:
    materialized, before, protocol = _case(APIS[3], "O22-SB-SET-INCLUSIONS-01", tmp_path)
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    parsed = parse_soundbank_business_plan_sections(sections.writer_kwargs())
    validate_soundbank_business_plan_archive(parsed, protocol, scenario=soundbank_archive_identity(materialized))
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_business_plan_archive(replace(parsed, fixture_spec=MappingProxyType({**parsed.fixture_spec, "kind": "wrong"})), protocol, scenario=soundbank_archive_identity(materialized))
    topic, topic_before, topic_protocol = _case(SOUNDBANK_TOPIC, "O22-SB-GENERATED-01", tmp_path / "topic", topic=True)
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_business_plan_archive(parsed, topic_protocol, scenario=soundbank_archive_identity(materialized))


@pytest.mark.parametrize(
    "roots",
    (
        ["."],
        ["../escape"],
        ["/tmp/escape"],
        ["cache", "cache/extra"],
    ),
)
def test_archive_rejects_dynamic_output_authority_expansion(
    tmp_path: Path,
    roots: list[str],
) -> None:
    materialized, before, protocol = _case(
        APIS[0],
        "O22-SB-GENERATE-01",
        tmp_path,
    )
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    parsed = parse_soundbank_business_plan_sections(sections.writer_kwargs())
    static = _copy(parsed.static_expectation)
    static["dynamic_output_policy"]["roots"] = roots
    fixture = {
        "kind": parsed.fixture_spec["kind"],
        "sha256": _plan_digest(static, parsed.live_binding),
    }
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_business_plan_archive(
            replace(
                parsed,
                static_expectation=MappingProxyType(static),
                fixture_spec=MappingProxyType(fixture),
            ),
            protocol,
            scenario=soundbank_archive_identity(materialized),
        )


def test_archive_identity_live_ids_artifacts_and_set_algebra_are_tamper_evident(tmp_path: Path) -> None:
    materialized, before, protocol = _case(APIS[3], "O22-SB-SET-INCLUSIONS-01", tmp_path)
    sections = compile_soundbank_business_plan(materialized, before, protocol)
    parsed = parse_soundbank_business_plan_sections(sections.writer_kwargs())
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_business_plan_archive(parsed, protocol, scenario={**soundbank_archive_identity(materialized), "api": APIS[0]})
    altered_identity = soundbank_archive_identity(materialized); altered_fixture = _copy(altered_identity["fixture"]); altered_fixture["asset_spec"] = {"tampered": True}; altered_identity["fixture"] = altered_fixture
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_business_plan_archive(parsed, protocol, scenario=altered_identity)
    bad_live = dict(parsed.live_binding); bad_live["platform_ids"] = {"Windows": "not-a-guid"}
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_business_plan_archive(replace(parsed, live_binding=MappingProxyType(bad_live)), protocol, scenario=soundbank_archive_identity(materialized))
    rehashed_static = _copy(parsed.static_expectation); rehashed_static["expected_artifacts"] = []; rehashed_static["definitions"] = []; rehashed_static["scenario_fixture_sha256"] = "f" * 64
    rehashed_live = _copy(parsed.live_binding); rehashed_live["input_files"][0]["sha256"] = "e" * 64; rehashed_live["before_snapshot"]["input_files"][0]["sha256"] = "e" * 64; rehashed_live["before_snapshot_sha256"] = _digest_value(rehashed_live["before_snapshot"])
    rehashed_rule = dict(parsed.delta_rules[0]); rehashed_rule["expected_artifacts"] = []; rehashed_rule["input_files_sha256"] = _digest_value(rehashed_live["before_snapshot"]["input_files"])
    rehashed_fixture = {"kind": parsed.fixture_spec["kind"], "sha256": _plan_digest(rehashed_static, rehashed_live)}
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_business_plan_archive(replace(parsed, static_expectation=MappingProxyType(rehashed_static), live_binding=MappingProxyType(rehashed_live), delta_rules=(MappingProxyType(rehashed_rule),), fixture_spec=MappingProxyType(rehashed_fixture)), protocol, scenario=soundbank_archive_identity(materialized))
    after = _after(sections)
    validate_soundbank_archived_verification(sections, _verification(sections, phase="after_execution", after=after))
    wrong = dict(after); wrong_banks = [dict(item) for item in wrong["banks"]]; wrong_banks[0]["inclusions"] = [] ; wrong["banks"] = wrong_banks
    with pytest.raises(SoundBankBusinessPlanError):
        validate_soundbank_archived_verification(sections, _verification(sections, phase="after_execution", after=wrong))


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verification(sections, *, phase: str, after: dict[str, object]) -> dict[str, object]:
    return {
        "scenario_id": sections.static_expectation["scenario_id"],
        "phase": phase,
        "passed": True,
        "failures": [],
        "before": sections.live_binding["before_snapshot"],
        "after": after,
    }


def _after(sections) -> dict[str, object]:
    after = dict(sections.live_binding["before_snapshot"])
    outputs = [dict(item) for item in after["output_files"]]
    outputs[0]["sha256"] = "f" * 64
    outputs[0]["mtime_ns"] += 1
    after["output_files"] = outputs
    return after


def _copy(value):
    import json
    return json.loads(json.dumps(dict(value) if isinstance(value, MappingProxyType) else value))


def _plan_digest(static, live) -> str:
    import hashlib
    import json
    payload = {"static": dict(static) if isinstance(static, MappingProxyType) else static, "live": dict(live) if isinstance(live, MappingProxyType) else live}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _digest_value(value) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
