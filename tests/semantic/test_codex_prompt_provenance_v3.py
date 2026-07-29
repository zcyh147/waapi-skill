from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.semantic.support.codex_business_oracle_plan_v3 import (
    business_family_for_api,
    write_business_oracle_plan,
)
from tests.semantic.support.codex_eval_bundle_v3 import (
    ExpectedDispatch,
    OnlineScenario,
    VisibleInput,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    OPERATION_REQUEST_CONTRACT,
    V3GatewayProtocol,
    build_direct_protocol,
    build_metadata_transaction_protocol,
    build_transaction_protocol,
    call_step,
    wait_topic_step,
)
from tests.semantic.support.codex_gateway_broker import (
    ExpectedGatewayStep,
    MetadataTokenProjection,
    ResponseBinding,
    SemanticJsonArgument,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    PROMPT_MATERIALIZATION_RECEIPT_CONTRACT,
    PROMPT_PROVENANCE_FILE,
    PromptProvenanceError,
    _protocol_requests,
    _select_shared_cli_manifest,
    deserialize_protocol,
    prompt_materialization_receipt,
    read_prompt_provenance,
    serialize_protocol,
    write_prompt_provenance,
)
from tests.semantic.support.codex_soundbank_runtime_v3 import (
    render_soundbank_generation_build_locations,
)


VERSION = "2022.1"
CONFIRMATION = "这个预览可以，执行吧。"


def _scenario_root(tmp_path: Path, name: str = "scenario") -> Path:
    root = tmp_path / name
    (root / "evidence").mkdir(parents=True)
    (root / "owned").mkdir()
    return root


def _scenario(
    *,
    api: str,
    visible_inputs: tuple[VisibleInput, ...] = (),
    prompt: str = (
        "请读取当前项目里测试对象的名称、类型、父级和基础属性，并汇总结果。"
    ),
    protocol: str = "single",
    dispatch_count: int = 1,
    scenario_id: str = "PROVENANCE-01",
) -> OnlineScenario:
    return OnlineScenario(
        id=scenario_id,
        api=api,
        item_type="function",
        versions=(VERSION,),
        lane="online_authoring",
        scenario_family="prompt_provenance",
        scenario_index=1,
        prompt=prompt,
        visible_inputs=visible_inputs,
        protocol=protocol,
        confirmation_prompt=CONFIRMATION if protocol == "preview_confirm" else None,
        fixture={},
        trigger=None,
        expected_dispatches=(ExpectedDispatch(api, dispatch_count, "read"),),
        oracle_assertions=(),
        cleanup={},
    )


def _direct_protocol(api: str) -> V3GatewayProtocol:
    return build_direct_protocol((call_step("read", api),))


def _operation_request(
    operation: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": VERSION,
        "operation": operation,
        "arguments": arguments,
    }


def _prompts(
    scenario: OnlineScenario,
    visible_values: dict[str, str],
) -> tuple[str, ...]:
    first = scenario.render_prompt(visible_values)
    return (first, *((CONFIRMATION,) * scenario.confirmation_turn_count))


def test_shared_cli_manifests_are_selected_from_closed_platform_union() -> None:
    pairs = [
        ["Windows", "/assets/ambience.wsources"],
        ["Windows", "/assets/mission.wsources"],
        ["Mac", "/assets/ambience.wsources"],
        ["Mac", "/assets/mission.wsources"],
    ]

    assert _select_shared_cli_manifest(
        pairs,
        platforms=["Windows", "Mac"],
        manifest_index=0,
    ) == ("/assets/ambience.wsources", "/0/1")
    assert _select_shared_cli_manifest(
        pairs,
        platforms=["Windows", "Mac"],
        manifest_index=1,
    ) == ("/assets/mission.wsources", "/1/1")


@pytest.mark.parametrize(
    ("pairs", "platforms", "manifest_index", "message"),
    (
        (
            [
                ["Windows", "/assets/ambience.wsources"],
                ["Mac", "/assets/different.wsources"],
            ],
            ["Windows", "Mac"],
            0,
            "differs across platforms",
        ),
        (
            [
                ["Windows", "/assets/ambience.wsources"],
                ["Windows", "/assets/mission.wsources"],
                ["Mac", "/assets/ambience.wsources"],
            ],
            ["Windows", "Mac"],
            1,
            "rows are incomplete",
        ),
        (
            [
                ["Windows", "/assets/ambience.wsources"],
                ["Linux", "/assets/ambience.wsources"],
            ],
            ["Windows", "Mac"],
            0,
            "platform row is invalid",
        ),
        (
            [["Windows", "/assets/ambience.wsources"]],
            ["Windows", "Windows"],
            0,
            "platform mapping is invalid",
        ),
        (
            [["Windows"]],
            ["Windows"],
            0,
            "platform row is invalid",
        ),
    ),
    ids=(
        "cross-platform-path-drift",
        "unequal-manifest-count",
        "unknown-platform",
        "duplicate-platform",
        "malformed-pair",
    ),
)
def test_shared_cli_manifest_selection_rejects_open_or_drifting_shapes(
    pairs: list[list[str]],
    platforms: list[str],
    manifest_index: int,
    message: str,
) -> None:
    with pytest.raises(PromptProvenanceError, match=message):
        _select_shared_cli_manifest(
            pairs,
            platforms=platforms,
            manifest_index=manifest_index,
        )


def _write(
    *,
    scenario: OnlineScenario,
    root: Path,
    protocol: V3GatewayProtocol,
    visible_values: dict[str, str] | None = None,
    trusted_sources: dict[str, Any] | None = None,
):
    values = visible_values or {}
    return write_prompt_provenance(
        scenario=scenario,
        version=VERSION,
        scenario_root=root,
        prompts=_prompts(scenario, values),
        visible_values=values,
        protocol=protocol,
        trusted_sources=trusted_sources,
    )


def _business_plan(
    *,
    scenario: OnlineScenario,
    root: Path,
    protocol: V3GatewayProtocol,
    provenance: Any,
):
    fixture_sha256 = hashlib.sha256(b"{}").hexdigest()
    return write_business_oracle_plan(
        scenario_id=scenario.id,
        version=VERSION,
        api=scenario.api,
        runner="cli" if scenario.api.startswith("ak.wwise.cli.") else "project",
        family=business_family_for_api(scenario.api),
        scenario_root=root,
        fixture_spec={"kind": "scenario_fixture", "sha256": fixture_sha256},
        protocol_sha256=provenance.payload["protocol"]["sha256"],
        provenance_sha256=provenance.sha256,
        primary_dispatch_count=scenario.primary_dispatch.count,
        payload_bindings={
            "primary_steps": [step.name for step in protocol.steps],
            "verification_steps": [],
        },
        assertion_ids=("common.prompt-receipt",),
        static_expectation={},
        live_binding={},
        delta_rules=(),
    )


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _rewrite_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_bytes(_canonical_bytes(payload))


def _read_again(
    path: Path,
    *,
    scenario: OnlineScenario,
    root: Path,
    protocol: V3GatewayProtocol,
    visible_values: dict[str, str] | None = None,
    require_paths: bool = True,
):
    return read_prompt_provenance(
        path,
        scenario=scenario,
        version=VERSION,
        scenario_root=root,
        expected_prompts=_prompts(scenario, visible_values or {}),
        expected_protocol=protocol,
        require_paths=require_paths,
    )


def _audio_convert_case(
    root: Path,
    *,
    io_root: Path | None = None,
) -> tuple[OnlineScenario, V3GatewayProtocol, dict[str, str]]:
    selected = io_root or root / "owned" / "io"
    if io_root is None:
        selected.mkdir()
    scenario = _scenario(
        api="ak.wwise.core.audio.convert",
        visible_inputs=(
            VisibleInput("io_root", "absolute_directory_path", "音频转换工作目录"),
        ),
        prompt="请在这个目录中完成测试音频的转换：{io_root}",
        protocol="preview_confirm",
    )
    protocol = build_transaction_protocol(
        (
            _operation_request(
                "audio.convert",
                {"io_root": str(selected), "objects": ["{AUDIO-OBJECT}"]},
            ),
        )
    )
    return scenario, protocol, {"io_root": str(selected)}


def _migrate_case(
    root: Path,
    *,
    project_path: Path,
) -> tuple[OnlineScenario, V3GatewayProtocol, dict[str, str]]:
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("project", encoding="utf-8")
    api = "ak.wwise.cli.migrate"
    scenario = _scenario(
        api=api,
        visible_inputs=(
            VisibleInput("project_path", "absolute_file_path", "待迁移工程"),
        ),
        prompt="请迁移这个测试工程：{project_path}",
        protocol="preview_confirm",
    )
    protocol = build_transaction_protocol(
        (
            _operation_request(
                "cli.call",
                {
                    "api": api,
                    "args": {"project": str(project_path)},
                    "options": {},
                },
            ),
        )
    )
    return scenario, protocol, {"project_path": str(project_path)}


def _audio_import_case(
    root: Path,
) -> tuple[OnlineScenario, V3GatewayProtocol, dict[str, str]]:
    sources = root / "owned" / "assets" / "import-case" / "sources"
    sources.mkdir(parents=True)
    audio = sources / "ambience.wav"
    audio.write_bytes(b"RIFF-test-audio")
    rows = [
        {
            "audio_file": str(audio),
            "import_language": "SFX",
            "object_path": "\\Actor-Mixer Hierarchy\\Default Work Unit\\Forest",
            "metadata": {"loop": True, "priority": 7},
        }
    ]
    encoded_rows = json.dumps(
        rows, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    scenario = _scenario(
        api="ak.wwise.core.audio.import",
        visible_inputs=(
            VisibleInput(
                "media_directory", "absolute_directory_path", "待导入媒体目录"
            ),
            VisibleInput("import_rows", "structured_array", "批量导入定义"),
        ),
        prompt="请按这组定义导入目录 {media_directory} 中的素材：{import_rows}",
        protocol="preview_confirm",
    )
    protocol = build_transaction_protocol(
        (_operation_request("audio.import", {"imports": rows}),)
    )
    return scenario, protocol, {
        "media_directory": str(sources),
        "import_rows": encoded_rows,
    }


def _soundbank_case(
    root: Path,
) -> tuple[
    OnlineScenario,
    V3GatewayProtocol,
    dict[str, str],
    dict[str, Any],
]:
    owned = root / "owned"
    project = owned / "project" / "SampleProject.wproj"
    cache = owned / "cache"
    bank = owned / "GeneratedSoundBanks" / "Windows"
    media = owned / "CopiedMedia" / "Windows"
    project.parent.mkdir()
    project.write_text("project", encoding="utf-8")
    for directory in (cache, bank, media):
        directory.mkdir(parents=True)
    projection = {
        "path": str(project),
        "directories": {"cache": str(cache)},
        "platforms": [
            {
                "name": "Windows",
                "soundBankPath": str(bank),
                "copiedMediaPath": str(media),
            }
        ],
    }
    generation_request = {
        "io_root": str(owned),
        "platforms": ["Windows"],
        "soundbanks": [{"name": "Main"}],
    }
    build_locations = render_soundbank_generation_build_locations(
        projection, io_root=owned
    )
    encode = lambda value: json.dumps(  # noqa: E731 - compact fixture encoder
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    scenario = _scenario(
        api="ak.wwise.core.soundbank.generate",
        visible_inputs=(
            VisibleInput(
                "generation_request", "structured_object", "SoundBank 生成请求"
            ),
            VisibleInput("build_locations", "structured_object", "构建位置"),
        ),
        prompt="请按这个请求生成 SoundBank：{generation_request}。构建位置：{build_locations}",
        protocol="preview_confirm",
    )
    protocol = build_transaction_protocol(
        (_operation_request("soundbank.generate", generation_request),)
    )
    return (
        scenario,
        protocol,
        {
            "generation_request": encode(generation_request),
            "build_locations": encode(build_locations),
        },
        {"soundbank_generate_project_info": projection},
    )


def test_fixed_provenance_path_round_trip_and_o_excl_preserves_first_document(
    tmp_path: Path,
) -> None:
    root = _scenario_root(tmp_path)
    scenario = _scenario(api="ak.wwise.core.object.get")
    protocol = _direct_protocol(scenario.api)

    evidence = _write(scenario=scenario, root=root, protocol=protocol)
    original = evidence.path.read_bytes()

    assert evidence.path == root / "evidence" / PROMPT_PROVENANCE_FILE
    assert evidence.sha256 == hashlib.sha256(original).hexdigest()
    assert evidence.prompts == (scenario.prompt,)
    assert evidence.visible_values == {}
    with pytest.raises(FileExistsError):
        _write(scenario=scenario, root=root, protocol=protocol)
    assert evidence.path.read_bytes() == original


def test_read_rejects_non_fixed_provenance_path(tmp_path: Path) -> None:
    root = _scenario_root(tmp_path)
    scenario = _scenario(api="ak.wwise.core.object.get")
    protocol = _direct_protocol(scenario.api)
    evidence = _write(scenario=scenario, root=root, protocol=protocol)
    other = root / "evidence" / "copy.json"
    other.write_bytes(evidence.path.read_bytes())

    with pytest.raises(PromptProvenanceError, match="fixed scenario path"):
        _read_again(other, scenario=scenario, root=root, protocol=protocol)


def test_read_rejects_missing_directory_and_symlink_provenance_file(
    tmp_path: Path,
) -> None:
    scenario = _scenario(api="ak.wwise.core.object.get")
    protocol = _direct_protocol(scenario.api)

    missing_root = _scenario_root(tmp_path, "missing")
    with pytest.raises(PromptProvenanceError, match="cannot open"):
        _read_again(
            missing_root / "evidence" / PROMPT_PROVENANCE_FILE,
            scenario=scenario,
            root=missing_root,
            protocol=protocol,
        )

    directory_root = _scenario_root(tmp_path, "directory")
    provenance_path = directory_root / "evidence" / PROMPT_PROVENANCE_FILE
    provenance_path.mkdir()
    with pytest.raises(PromptProvenanceError, match="regular file|cannot open"):
        _read_again(
            provenance_path,
            scenario=scenario,
            root=directory_root,
            protocol=protocol,
        )

    symlink_root = _scenario_root(tmp_path, "symlink")
    external = tmp_path / "external.json"
    external.write_text("{}", encoding="utf-8")
    (symlink_root / "evidence" / PROMPT_PROVENANCE_FILE).symlink_to(external)
    with pytest.raises(PromptProvenanceError, match="cannot open|regular file"):
        _read_again(
            symlink_root / "evidence" / PROMPT_PROVENANCE_FILE,
            scenario=scenario,
            root=symlink_root,
            protocol=protocol,
        )


def test_rejects_symlink_scenario_root_and_symlink_input_path(tmp_path: Path) -> None:
    real_root = _scenario_root(tmp_path, "real")
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root, target_is_directory=True)
    scenario = _scenario(api="ak.wwise.core.object.get")
    with pytest.raises(PromptProvenanceError, match="root must not be a symlink"):
        _write(
            scenario=scenario,
            root=linked_root,
            protocol=_direct_protocol(scenario.api),
        )

    root = _scenario_root(tmp_path, "input")
    outside = tmp_path / "outside-io"
    outside.mkdir()
    io_link = root / "owned" / "io"
    io_link.symlink_to(outside, target_is_directory=True)
    scenario, protocol, values = _audio_convert_case(root, io_root=io_link)
    with pytest.raises(PromptProvenanceError, match="symlink"):
        _write(
            scenario=scenario,
            root=root,
            protocol=protocol,
            visible_values=values,
        )


@pytest.mark.parametrize("variant", ("traversal", "other_root"))
def test_audio_convert_rejects_traversal_and_other_root(
    tmp_path: Path,
    variant: str,
) -> None:
    root = _scenario_root(tmp_path)
    real_io = root / "owned" / "io"
    real_io.mkdir()
    if variant == "traversal":
        selected = Path(str(root / "owned" / "shadow" / ".." / "io"))
    else:
        selected = tmp_path / "OtherRoot" / "io"
        selected.mkdir(parents=True)
    scenario, protocol, values = _audio_convert_case(root, io_root=selected)

    with pytest.raises(PromptProvenanceError, match="normalized|escapes"):
        _write(
            scenario=scenario,
            root=root,
            protocol=protocol,
            visible_values=values,
        )


def test_audio_convert_rejects_wrong_owned_io_directory(tmp_path: Path) -> None:
    root = _scenario_root(tmp_path)
    wrong = root / "owned" / "conversion-work"
    wrong.mkdir()
    scenario, protocol, values = _audio_convert_case(root, io_root=wrong)

    with pytest.raises(PromptProvenanceError, match="audio.convert io_root"):
        _write(
            scenario=scenario,
            root=root,
            protocol=protocol,
            visible_values=values,
        )


def test_migrate_rejects_wrong_owned_project_path(tmp_path: Path) -> None:
    root = _scenario_root(tmp_path)
    wrong = root / "owned" / "case" / "project" / "Other.wproj"
    scenario, protocol, values = _migrate_case(root, project_path=wrong)

    with pytest.raises(PromptProvenanceError, match="fixed owned target"):
        _write(
            scenario=scenario,
            root=root,
            protocol=protocol,
            visible_values=values,
        )


def test_verify_only_accepts_missing_input_but_rejects_archived_kind_substitution(
    tmp_path: Path,
) -> None:
    root = _scenario_root(tmp_path)
    scenario, protocol, values = _audio_convert_case(root)
    evidence = _write(
        scenario=scenario,
        root=root,
        protocol=protocol,
        visible_values=values,
    )
    Path(values["io_root"]).rmdir()

    archived = _read_again(
        evidence.path,
        scenario=scenario,
        root=root,
        protocol=protocol,
        visible_values=values,
        require_paths=False,
    )
    assert archived.visible_values == values

    payload = json.loads(evidence.path.read_text(encoding="utf-8"))
    binding = payload["request"]["inputs"][0]["leaf_bindings"][0]
    binding["path_kind"] = "file"
    _rewrite_payload(evidence.path, payload)
    with pytest.raises(PromptProvenanceError, match="proof fields|reproducible"):
        _read_again(
            evidence.path,
            scenario=scenario,
            root=root,
            protocol=protocol,
            visible_values=values,
            require_paths=False,
        )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.update({"unexpected": True}),
        lambda payload: payload["request"].update({"unexpected": True}),
        lambda payload: payload["request"]["inputs"][0].update(
            {"unexpected": True}
        ),
        lambda payload: payload["request"]["inputs"][0]["leaf_bindings"][
            0
        ].update({"unexpected": True}),
        lambda payload: payload["protocol"]["value"]["steps"][0].update(
            {"unexpected": True}
        ),
    ),
    ids=("top", "request", "input", "leaf", "protocol-step"),
)
def test_closed_schemas_reject_extra_fields(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    root = _scenario_root(tmp_path)
    scenario, protocol, values = _audio_convert_case(root)
    evidence = _write(
        scenario=scenario,
        root=root,
        protocol=protocol,
        visible_values=values,
    )
    payload = json.loads(evidence.path.read_text(encoding="utf-8"))
    mutate(payload)
    if "unexpected" in payload.get("protocol", {}).get("value", {}).get("steps", [{}])[0]:
        protocol_value = payload["protocol"]["value"]
        payload["protocol"]["sha256"] = hashlib.sha256(
            json.dumps(
                protocol_value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    _rewrite_payload(evidence.path, payload)

    with pytest.raises(PromptProvenanceError):
        _read_again(
            evidence.path,
            scenario=scenario,
            root=root,
            protocol=protocol,
            visible_values=values,
        )


def test_structured_input_binds_every_leaf_to_exact_pointer(tmp_path: Path) -> None:
    root = _scenario_root(tmp_path)
    scenario, protocol, values = _audio_import_case(root)
    evidence = _write(
        scenario=scenario,
        root=root,
        protocol=protocol,
        visible_values=values,
    )
    row = evidence.payload["request"]["inputs"][1]
    bindings = {item["pointer"]: item for item in row["leaf_bindings"]}

    assert set(bindings) == {
        "/0/audio_file",
        "/0/import_language",
        "/0/metadata/loop",
        "/0/metadata/priority",
        "/0/object_path",
    }
    for pointer, binding in bindings.items():
        assert binding["origin_pointer"].endswith(
            "/arguments/imports" + pointer
        )
    assert bindings["/0/audio_file"]["origin_kind"] == "owned_path"
    assert bindings["/0/audio_file"]["path_kind"] == "file"
    assert all(
        binding["origin_kind"] == "protocol"
        for pointer, binding in bindings.items()
        if pointer != "/0/audio_file"
    )


def test_compound_import_visible_rows_are_sealed_as_trusted_prompt_source(
    tmp_path: Path,
) -> None:
    root = _scenario_root(tmp_path)
    scenario, _base_protocol, values = _audio_import_case(root)
    scenario = replace(
        scenario,
        fixture={
            "asset_spec": {
                "compound": {
                    "contract": "waapi-skill.compound-import/v1",
                }
            }
        },
    )
    rows = json.loads(values["import_rows"])
    request = _operation_request(
        "audio.import",
        {
            "imports": [
                {
                    **{
                        key: value
                        for key, value in rows[0].items()
                        if key != "metadata"
                    },
                    "properties": [
                        {"name": "IsLoopingEnabled", "value": True}
                    ],
                }
            ]
        },
    )
    protocol = build_metadata_transaction_protocol(
        (request,),
        object_type="Sound",
        metadata_queries=("looping enabled",),
        required_tokens=("IsLoopingEnabled",),
        expected_required_token_projection=(
            MetadataTokenProjection(
                "IsLoopingEnabled",
                "property",
                "bool",
            ),
        ),
        equivalence="audio_import_v1",
    )
    evidence = _write(
        scenario=scenario,
        root=root,
        protocol=protocol,
        visible_values=values,
        trusted_sources={"compound_import_visible_rows": rows},
    )
    stored_source = evidence.payload["trusted_sources"][
        "compound_import_visible_rows"
    ]
    bindings = evidence.payload["request"]["inputs"][1]["leaf_bindings"]

    assert stored_source["value"] == rows
    assert len(stored_source["path_proofs"]) == 1
    assert all(
        binding["origin_pointer"].startswith(
            "/compound_import_visible_rows/value/"
        )
        for binding in bindings
    )
    assert any(
        binding["origin_kind"] == "owned_path"
        for binding in bindings
    )
    assert all(
        binding["origin_kind"] == "trusted_source"
        for binding in bindings
        if binding["origin_kind"] != "owned_path"
    )
    restored = _read_again(
        evidence.path,
        scenario=scenario,
        root=root,
        protocol=protocol,
        visible_values=values,
    )
    assert restored.payload == evidence.payload


@pytest.mark.parametrize("tamper", ("pointer", "origin", "missing"))
def test_structured_leaf_binding_tamper_is_rejected(
    tmp_path: Path,
    tamper: str,
) -> None:
    root = _scenario_root(tmp_path)
    scenario, protocol, values = _audio_import_case(root)
    evidence = _write(
        scenario=scenario,
        root=root,
        protocol=protocol,
        visible_values=values,
    )
    payload = json.loads(evidence.path.read_text(encoding="utf-8"))
    bindings = payload["request"]["inputs"][1]["leaf_bindings"]
    if tamper == "pointer":
        bindings[1]["pointer"] = "/0/object_path"
    elif tamper == "origin":
        bindings[1]["origin_pointer"] = bindings[2]["origin_pointer"]
    else:
        bindings.pop()
    _rewrite_payload(evidence.path, payload)

    with pytest.raises(PromptProvenanceError, match="reproducible"):
        _read_again(
            evidence.path,
            scenario=scenario,
            root=root,
            protocol=protocol,
            visible_values=values,
        )


def test_protocol_strict_round_trip_preserves_all_argument_kinds() -> None:
    protocol = V3GatewayProtocol(
        steps=(
            ExpectedGatewayStep(
                name="preview",
                subcommand="preview",
                arguments=(
                    "--request-json",
                    SemanticJsonArgument(
                        {"nested": [1, True, None, {"x": "y"}]},
                        equivalence="object_operation_v1",
                    ),
                    "--exact-json",
                    SemanticJsonArgument({"exact": True}),
                ),
                gateway_global_arguments=("--timeout", "12.5"),
            ),
            ExpectedGatewayStep(
                name="transaction-show",
                subcommand="transaction-show",
                arguments=(
                    ResponseBinding("preview", "/transaction_id"),
                    "--summary-only",
                ),
            ),
            ExpectedGatewayStep(
                name="confirm",
                subcommand="confirm",
                arguments=(
                    ResponseBinding("transaction-show", "/transaction_id"),
                    "--confirmation-token",
                    ResponseBinding("transaction-show", "/confirmation/token"),
                ),
            ),
        ),
        turn_prefix_counts=(1, 3),
    )

    serialized = serialize_protocol(protocol)
    restored = deserialize_protocol(serialized)

    assert restored == protocol
    assert serialize_protocol(restored) == serialized
    assert serialized["steps"][0]["arguments"][1]["kind"] == (
        "semantic_json_object_operation_v1"
    )
    assert serialized["steps"][0]["arguments"][3]["kind"] == "semantic_json"
    assert serialized["steps"][2]["arguments"][2] == {
        "kind": "response_binding",
        "step": "transaction-show",
        "pointer": "/confirmation/token",
    }


def test_soundbank_generate_equivalence_round_trips_and_rejects_wrong_route() -> None:
    request = _operation_request(
        "soundbank.generate",
        {
            "soundbanks": [
                {
                    "name": "Main_UI",
                    "artifact_expectation": "nonlocalized",
                    "rebuild": False,
                }
            ],
            "platforms": ["Windows"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": "/owned",
            "rebuild_soundbanks": False,
            "clear_audio_file_cache": False,
            "rebuild_init_bank": False,
        },
    )
    protocol = build_transaction_protocol((request,))
    serialized = serialize_protocol(protocol)
    argument = serialized["steps"][1]["arguments"][2]

    assert argument["kind"] == "semantic_json_soundbank_generate_v1"
    assert deserialize_protocol(serialized) == protocol
    assert serialize_protocol(deserialize_protocol(serialized)) == serialized
    assert _protocol_requests(serialized) == (
        ("/steps/1/arguments/2/value", request),
    )

    wrong_route = json.loads(json.dumps(serialized))
    wrong_argument = wrong_route["steps"][1]["arguments"][2]
    wrong_argument["value"]["operation"] = "soundbank.setInclusions"
    wrong_argument["sha256"] = hashlib.sha256(
        json.dumps(
            wrong_argument["value"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(
        PromptProvenanceError,
        match="equivalence contract",
    ):
        _protocol_requests(wrong_route)


def test_protocol_round_trip_preserves_omitted_default_event_count_flag() -> None:
    protocol = build_direct_protocol(
        [
            wait_topic_step(
                "generated",
                "ak.wwise.core.soundbank.generated",
                event_count=1,
                match={"platform": "Windows"},
            )
        ]
    )

    serialized = serialize_protocol(protocol)
    restored = deserialize_protocol(serialized)

    assert restored == protocol
    assert (
        serialized["steps"][0]["allow_omitted_default_event_count_one"]
        is True
    )


def test_metadata_transaction_protocol_round_trips_its_scope_and_token_binding(
    tmp_path: Path,
) -> None:
    request = _operation_request(
        "object.set",
        {
            "object": {"kind": "path", "value": r"\Root\Target"},
            "properties": [{"name": "Volume", "value": -3}],
        },
    )
    protocol = build_metadata_transaction_protocol(
        (request,),
        object_type="ActorMixer",
        metadata_queries=("output volume",),
        required_tokens=("Volume",),
        expected_required_token_projection=(
            MetadataTokenProjection("Volume", "property", "Real32"),
        ),
    )

    serialized = serialize_protocol(protocol)
    restored = deserialize_protocol(serialized)

    assert restored == protocol
    assert serialize_protocol(restored) == serialized
    assert _protocol_requests(serialized) == (
        ("/steps/2/arguments/2/value", request),
    )
    assert serialized["steps"][0]["arguments"][4] == {
        "kind": "metadata_query",
        "label": "output volume",
        "maximum_chars": 160,
    }
    assert serialized["steps"][2]["arguments"][2] == {
        "kind": "metadata_bound_json",
        "value": request,
        "sha256": hashlib.sha256(
            json.dumps(
                request,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "equivalence": "wire_exact",
        "metadata_step": "metadata.discover",
        "object_type": "ActorMixer",
        "required_tokens": ["Volume"],
        "expected_required_token_projection": [
            {
                "name": "Volume",
                "kind": "property",
                "metadata_type": "Real32",
            }
        ],
    }
    scenario = _scenario(
        api="ak.wwise.core.object.set",
        protocol="preview_confirm",
    )
    evidence = _write(
        scenario=scenario,
        root=_scenario_root(tmp_path),
        protocol=protocol,
    )
    assert evidence.prompts == (
        scenario.prompt,
        CONFIRMATION,
    )


def test_object_set_metadata_equivalence_round_trips_and_archive_revalidates(
    tmp_path: Path,
) -> None:
    request = _operation_request(
        "object.set",
        {
            "objects": [
                {
                    "object": {
                        "kind": "path",
                        "value": r"\Actor-Mixer Hierarchy\Target",
                    },
                    "properties": [{"name": "Volume", "value": -3}],
                }
            ]
        },
    )
    protocol = build_metadata_transaction_protocol(
        (request,),
        object_type="ActorMixer",
        metadata_queries=("volume",),
        required_tokens=("Volume",),
        expected_required_token_projection=(
            MetadataTokenProjection("Volume", "property", "Real32"),
        ),
        equivalence="object_set_v1",
    )
    serialized = serialize_protocol(protocol)
    argument = serialized["steps"][2]["arguments"][2]

    assert argument["equivalence"] == "object_set_v1"
    assert deserialize_protocol(serialized) == protocol
    assert _protocol_requests(serialized) == (
        ("/steps/2/arguments/2/value", request),
    )

    scenario = _scenario(
        api="ak.wwise.core.object.set",
        protocol="preview_confirm",
    )
    root = _scenario_root(tmp_path)
    evidence = _write(
        scenario=scenario,
        root=root,
        protocol=protocol,
    )
    restored = _read_again(
        evidence.path,
        scenario=scenario,
        root=root,
        protocol=protocol,
    )
    assert restored.payload == evidence.payload

    payload = json.loads(evidence.path.read_text(encoding="utf-8"))
    payload["protocol"]["value"]["steps"][2]["arguments"][2][
        "equivalence"
    ] = "wire_exact"
    payload["protocol"]["sha256"] = hashlib.sha256(
        json.dumps(
            payload["protocol"]["value"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    _rewrite_payload(evidence.path, payload)

    with pytest.raises(
        PromptProvenanceError,
        match="in-memory protocol differs",
    ):
        _read_again(
            evidence.path,
            scenario=scenario,
            root=root,
            protocol=protocol,
        )


def test_audio_import_metadata_equivalence_is_round_tripped_and_manifest_sealed(
    tmp_path: Path,
) -> None:
    request = _operation_request(
        "audio.import",
        {
            "imports": [
                {
                    "object_path": r"\Actor-Mixer Hierarchy\Target",
                    "audio_file": "/owned/source.wav",
                }
            ],
            "defaults": {
                "properties": [
                    {"name": "IsLoopingEnabled", "value": True}
                ]
            },
        },
    )
    protocol = build_metadata_transaction_protocol(
        (request,),
        object_type="Sound",
        metadata_queries=("looping enabled",),
        required_tokens=("IsLoopingEnabled",),
        equivalence="audio_import_v1",
    )
    serialized = serialize_protocol(protocol)
    argument = serialized["steps"][2]["arguments"][2]

    assert argument["equivalence"] == "audio_import_v1"
    assert deserialize_protocol(serialized) == protocol
    assert _protocol_requests(serialized) == (
        ("/steps/2/arguments/2/value", request),
    )

    scenario = _scenario(
        api="ak.wwise.core.audio.import",
        protocol="preview_confirm",
    )
    root = _scenario_root(tmp_path)
    evidence = _write(
        scenario=scenario,
        root=root,
        protocol=protocol,
    )
    payload = json.loads(evidence.path.read_text(encoding="utf-8"))
    payload["protocol"]["value"]["steps"][2]["arguments"][2][
        "equivalence"
    ] = "wire_exact"
    payload["protocol"]["sha256"] = hashlib.sha256(
        json.dumps(
            payload["protocol"]["value"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    _rewrite_payload(evidence.path, payload)

    with pytest.raises(
        PromptProvenanceError,
        match="in-memory protocol differs",
    ):
        _read_again(
            evidence.path,
            scenario=scenario,
            root=root,
            protocol=protocol,
        )


def test_tab_import_metadata_equivalence_round_trips_and_rejects_wrong_route() -> None:
    request = _operation_request(
        "audio.importTabDelimited",
        {
            "import_file": "/owned/import.tsv",
            "import_location": {
                "kind": "path",
                "value": r"\Actor-Mixer Hierarchy\Default Work Unit",
            },
            "import_language": "SFX",
        },
    )
    protocol = build_metadata_transaction_protocol(
        (request,),
        object_type="Sound",
        metadata_queries=("looping enabled",),
        required_tokens=("IsLoopingEnabled",),
        equivalence="audio_import_tab_v1",
    )
    serialized = serialize_protocol(protocol)
    argument = serialized["steps"][2]["arguments"][2]

    assert argument["equivalence"] == "audio_import_tab_v1"
    assert deserialize_protocol(serialized) == protocol
    assert _protocol_requests(serialized) == (
        ("/steps/2/arguments/2/value", request),
    )

    wrong_route = json.loads(json.dumps(serialized))
    wrong_argument = wrong_route["steps"][2]["arguments"][2]
    wrong_argument["value"]["operation"] = "audio.import"
    wrong_argument["sha256"] = hashlib.sha256(
        json.dumps(
            wrong_argument["value"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(
        PromptProvenanceError,
        match="equivalence contract",
    ):
        _protocol_requests(wrong_route)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update({"extra": 1}),
        lambda value: value["turn_prefix_counts"].__setitem__(0, True),
        lambda value: value["steps"][0]["allowed_exit_codes"].__setitem__(0, True),
        lambda value: value["steps"][0].__setitem__(
            "allow_omitted_empty_json_objects", 1
        ),
        lambda value: value["steps"][0].__setitem__(
            "allow_omitted_default_event_count_one", 1
        ),
        lambda value: value["steps"][0]["arguments"][1].__setitem__(
            "sha256", "0" * 64
        ),
        lambda value: value["steps"][1]["arguments"][0].__setitem__(
            "pointer", 7
        ),
        lambda value: value["steps"][0].update({"extra": 1}),
    ),
    ids=(
        "top-extra",
        "bool-prefix",
        "bool-exit-code",
        "non-bool-flag",
        "non-bool-event-count-flag",
        "semantic-digest",
        "binding-pointer-type",
        "step-extra",
    ),
)
def test_protocol_deserialization_rejects_schema_and_type_tampering(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    protocol = V3GatewayProtocol(
        steps=(
            ExpectedGatewayStep(
                name="preview",
                subcommand="preview",
                arguments=(
                    "--request-json",
                    SemanticJsonArgument({"value": [1, 2]}),
                ),
            ),
            ExpectedGatewayStep(
                name="transaction-show",
                subcommand="transaction-show",
                arguments=(
                    ResponseBinding("preview", "/transaction_id"),
                    "--summary-only",
                ),
            ),
            ExpectedGatewayStep(
                name="confirm",
                subcommand="confirm",
                arguments=(
                    ResponseBinding("transaction-show", "/transaction_id"),
                    "--confirmation-token",
                    ResponseBinding("transaction-show", "/confirmation/token"),
                ),
            ),
        ),
        turn_prefix_counts=(1, 3),
    )
    value = serialize_protocol(protocol)
    mutate(value)

    with pytest.raises((PromptProvenanceError, TypeError, ValueError)):
        deserialize_protocol(value)


def test_soundbank_trusted_projection_is_closed_and_leaf_bound(tmp_path: Path) -> None:
    root = _scenario_root(tmp_path)
    scenario, protocol, values, trusted = _soundbank_case(root)
    evidence = _write(
        scenario=scenario,
        root=root,
        protocol=protocol,
        visible_values=values,
        trusted_sources=trusted,
    )

    sealed_source = evidence.payload["trusted_sources"][
        "soundbank_generate_project_info"
    ]
    assert set(sealed_source) == {"value", "sha256", "path_proofs"}
    assert sealed_source["value"] == trusted["soundbank_generate_project_info"]
    assert len(sealed_source["path_proofs"]) == 4
    build_row = evidence.payload["request"]["inputs"][1]
    pointers = {row["pointer"]: row["origin_pointer"] for row in build_row["leaf_bindings"]}
    assert pointers == {
        "/cache": "/soundbank_generate_project_info/value/directories/cache",
        "/platforms/0/copiedMediaPath": (
            "/soundbank_generate_project_info/value/platforms/0/copiedMediaPath"
        ),
        "/platforms/0/name": (
            "/soundbank_generate_project_info/value/platforms/0/name"
        ),
        "/platforms/0/soundBankPath": (
            "/soundbank_generate_project_info/value/platforms/0/soundBankPath"
        ),
        "/project": "/soundbank_generate_project_info/value/path",
    }
    assert all(
        row["origin_kind"] == "trusted_source"
        for row in build_row["leaf_bindings"]
    )


def test_soundbank_rejects_untrusted_projection_fields_and_projection_tamper(
    tmp_path: Path,
) -> None:
    root = _scenario_root(tmp_path, "extra")
    scenario, protocol, values, trusted = _soundbank_case(root)
    expanded = json.loads(json.dumps(trusted))
    expanded["soundbank_generate_project_info"]["hiddenGuid"] = "{SECRET}"
    with pytest.raises(PromptProvenanceError, match="fields drifted"):
        _write(
            scenario=scenario,
            root=root,
            protocol=protocol,
            visible_values=values,
            trusted_sources=expanded,
        )

    root = _scenario_root(tmp_path, "tamper")
    scenario, protocol, values, trusted = _soundbank_case(root)
    evidence = _write(
        scenario=scenario,
        root=root,
        protocol=protocol,
        visible_values=values,
        trusted_sources=trusted,
    )
    payload = json.loads(evidence.path.read_text(encoding="utf-8"))
    source = payload["trusted_sources"]["soundbank_generate_project_info"]
    source["value"]["platforms"][0]["name"] = "Mac"
    source["sha256"] = hashlib.sha256(
        json.dumps(
            source["value"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    _rewrite_payload(evidence.path, payload)
    with pytest.raises(PromptProvenanceError, match="reproducible|differs"):
        _read_again(
            evidence.path,
            scenario=scenario,
            root=root,
            protocol=protocol,
            visible_values=values,
        )


def test_prompt_materialization_receipt_binds_identity_digests_and_turns(
    tmp_path: Path,
) -> None:
    root = _scenario_root(tmp_path)
    scenario, protocol, values = _audio_convert_case(root)
    evidence = _write(
        scenario=scenario,
        root=root,
        protocol=protocol,
        visible_values=values,
    )

    business_plan = _business_plan(
        scenario=scenario,
        root=root,
        protocol=protocol,
        provenance=evidence,
    )
    receipt = prompt_materialization_receipt(
        evidence,
        business_oracle_plan=business_plan,
    )

    assert receipt == {
        "contract": PROMPT_MATERIALIZATION_RECEIPT_CONTRACT,
        "scenario_id": scenario.id,
        "version": VERSION,
        "provenance_path": str(
            root / "evidence" / PROMPT_PROVENANCE_FILE
        ),
        "provenance_sha256": hashlib.sha256(evidence.path.read_bytes()).hexdigest(),
        "protocol_sha256": evidence.payload["protocol"]["sha256"],
        "business_oracle_plan_path": str(business_plan.path),
        "business_oracle_plan_sha256": business_plan.sha256,
        "expected_turn_count": 2,
        "turns": [
            {
                "index": 1,
                "kind": "request",
                "prompt_sha256": hashlib.sha256(
                    evidence.prompts[0].encode("utf-8")
                ).hexdigest(),
            },
            {
                "index": 2,
                "kind": "confirmation",
                "prompt_sha256": hashlib.sha256(
                    evidence.prompts[1].encode("utf-8")
                ).hexdigest(),
            },
        ],
    }
    assert receipt["protocol_sha256"] == hashlib.sha256(
        json.dumps(
            serialize_protocol(protocol),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_receipt_changes_when_scenario_or_protocol_binding_changes(tmp_path: Path) -> None:
    first_root = _scenario_root(tmp_path, "first")
    first_scenario = _scenario(
        api="ak.wwise.core.object.get", scenario_id="PROVENANCE-FIRST"
    )
    first_protocol = _direct_protocol(first_scenario.api)
    first = _write(
        scenario=first_scenario,
        root=first_root,
        protocol=first_protocol,
    )

    second_root = _scenario_root(tmp_path, "second")
    second_scenario = _scenario(
        api="ak.wwise.core.object.get", scenario_id="PROVENANCE-SECOND"
    )
    second_protocol = build_direct_protocol(
        (
            call_step(
                "read",
                second_scenario.api,
                args={"from": {"path": ["\\Actor-Mixer Hierarchy"]}},
            ),
        )
    )
    second = _write(
        scenario=second_scenario,
        root=second_root,
        protocol=second_protocol,
    )

    first_plan = _business_plan(
        scenario=first_scenario,
        root=first_root,
        protocol=first_protocol,
        provenance=first,
    )
    second_plan = _business_plan(
        scenario=second_scenario,
        root=second_root,
        protocol=second_protocol,
        provenance=second,
    )
    first_receipt = prompt_materialization_receipt(
        first,
        business_oracle_plan=first_plan,
    )
    second_receipt = prompt_materialization_receipt(
        second,
        business_oracle_plan=second_plan,
    )
    assert first_receipt["scenario_id"] != second_receipt["scenario_id"]
    assert first_receipt["provenance_path"] != second_receipt["provenance_path"]
    assert first_receipt["provenance_sha256"] != second_receipt["provenance_sha256"]
    assert first_receipt["protocol_sha256"] != second_receipt["protocol_sha256"]
