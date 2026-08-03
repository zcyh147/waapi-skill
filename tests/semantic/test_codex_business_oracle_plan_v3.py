from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from tests.support.platform_filesystem import create_symlink_or_skip
from tests.semantic.support import codex_business_oracle_plan_v3 as plan_module
from tests.semantic.support.codex_business_oracle_plan_v3 import (
    BUSINESS_FAMILIES,
    BUSINESS_ORACLE_PLAN_CONTRACT,
    BUSINESS_ORACLE_PLAN_FILE,
    MAX_BUSINESS_ORACLE_PLAN_BYTES,
    BusinessOraclePlanError,
    business_family_for_api,
    read_business_oracle_plan,
    read_business_oracle_plan_envelope,
    write_business_oracle_plan,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64

API_FAMILIES = {
    "ak.wwise.core.object.get": "object",
    "ak.wwise.core.object.create": "object",
    "ak.wwise.core.object.set": "object",
    "ak.wwise.core.audio.import": "audio_import",
    "ak.wwise.core.audio.importTabDelimited": "audio_import",
    "ak.wwise.core.audio.convert": "audio_conversion",
    "ak.wwise.core.mediaPool.get": "media_pool",
    "ak.wwise.core.soundbank.generate": "soundbank",
    "ak.wwise.core.soundbank.processDefinitionFiles": "soundbank",
    "ak.wwise.core.soundbank.convertExternalSources": "soundbank",
    "ak.wwise.core.soundbank.setInclusions": "soundbank",
    "ak.wwise.core.soundbank.generated": "soundbank_topic",
    "ak.wwise.cli.generateSoundbank": "cli",
    "ak.wwise.cli.tabDelimitedImport": "cli",
    "ak.wwise.cli.convertExternalSource": "cli",
    "ak.wwise.cli.migrate": "cli",
}


def _root(tmp_path: Path, name: str = "scenario") -> Path:
    root = tmp_path / name
    (root / "evidence").mkdir(parents=True)
    return root


def _kwargs(
    root: Path,
    *,
    api: str = "ak.wwise.core.object.get",
    scenario_id: str = "OBJ22-GET-01",
) -> dict[str, Any]:
    family = API_FAMILIES[api]
    return {
        "scenario_id": scenario_id,
        "version": "2022.1",
        "api": api,
        "runner": "cli" if family == "cli" else "project",
        "family": family,
        "scenario_root": root,
        "fixture_spec": {"kind": "sealed.fixture", "sha256": SHA_A},
        "protocol_sha256": SHA_B,
        "provenance_sha256": SHA_C,
        "primary_dispatch_count": 1,
        "payload_bindings": {
            "primary_steps": ["turn1.object-get"],
            "verification_steps": ["oracle.object-readback"],
        },
        "assertion_ids": ["object.target-present", "object.control-absent"],
        "static_expectation": {
            "rows": [
                {"name": "Rain_雨", "type": "Sound", "volume": -2.5},
                {"name": "Control", "type": "Sound", "volume": 0},
            ]
        },
        "live_binding": {
            "target_guid_source": "fixture.hidden.target_guid",
            "query": {"from": ["fixture.target_guid"], "return": ["id", "name"]},
        },
        "delta_rules": [
            {"kind": "unchanged", "subject": "source_project"},
            {"kind": "exact_rows", "subject": "target_query"},
        ],
    }


def _canonical(value: Any) -> bytes:
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


def _common_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        name: kwargs[name]
        for name in (
            "scenario_id",
            "version",
            "api",
            "runner",
            "family",
            "scenario_root",
            "fixture_spec",
            "protocol_sha256",
            "provenance_sha256",
            "primary_dispatch_count",
        )
    }


def _rewrite(path: Path, payload: dict[str, Any], *, canonical: bool = True) -> None:
    if canonical:
        path.write_bytes(_canonical(payload))
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize("api,family", sorted(API_FAMILIES.items()))
def test_closed_api_family_registry_maps_all_sixteen_heavy_apis(
    api: str, family: str
) -> None:
    assert business_family_for_api(api) == family
    assert family in BUSINESS_FAMILIES


@pytest.mark.parametrize(
    "api",
    [
        "ak.wwise.core.object.delete",
        "ak.wwise.core.soundbank.generationDone",
        "",
        None,
    ],
)
def test_api_family_registry_fails_closed(api: Any) -> None:
    with pytest.raises(BusinessOraclePlanError, match="outside the closed"):
        business_family_for_api(api)


def test_write_and_read_round_trip_fixed_canonical_closed_plan(tmp_path: Path) -> None:
    root = _root(tmp_path)
    kwargs = _kwargs(root)

    written = write_business_oracle_plan(**kwargs)
    reread = read_business_oracle_plan(written.path, **kwargs)

    assert written == reread
    assert written.path == root / "evidence" / BUSINESS_ORACLE_PLAN_FILE
    assert written.payload["contract"] == BUSINESS_ORACLE_PLAN_CONTRACT
    assert set(written.payload) == {
        "contract",
        "scenario_id",
        "version",
        "api",
        "runner",
        "family",
        "scenario_root",
        "fixture_spec",
        "protocol_sha256",
        "provenance_sha256",
        "primary_dispatch_count",
        "payload_bindings",
        "assertion_ids",
        "static_expectation",
        "live_binding",
        "delta_rules",
    }
    raw = written.path.read_bytes()
    assert raw == _canonical(written.payload)
    assert written.sha256 == hashlib.sha256(raw).hexdigest()
    assert written.payload["static_expectation"] == kwargs["static_expectation"]
    assert written.payload["live_binding"] == kwargs["live_binding"]
    assert written.payload["delta_rules"] == kwargs["delta_rules"]
    mode = os.lstat(written.path).st_mode
    assert stat.S_ISREG(mode)
    assert stat.S_IMODE(mode) & 0o077 == 0


def test_zero_dispatch_and_empty_common_optional_structures_are_valid(
    tmp_path: Path,
) -> None:
    kwargs = _kwargs(root := _root(tmp_path))
    kwargs.update(
        primary_dispatch_count=0,
        payload_bindings={
            "primary_steps": [],
            "verification_steps": ["turn1.structured-refusal"],
        },
        static_expectation={},
        live_binding={},
        delta_rules=[],
    )

    evidence = write_business_oracle_plan(**kwargs)

    assert evidence.path == root / "evidence" / BUSINESS_ORACLE_PLAN_FILE
    assert evidence.payload["primary_dispatch_count"] == 0
    assert evidence.payload["payload_bindings"]["primary_steps"] == []
    assert evidence.payload["payload_bindings"]["verification_steps"] == [
        "turn1.structured-refusal"
    ]
    assert evidence.payload["delta_rules"] == []


@pytest.mark.parametrize(
    "count,primary_steps",
    [
        (0, ["turn1.structured-refusal"]),
        (1, []),
        (3, []),
    ],
)
def test_primary_step_presence_is_cross_bound_to_dispatch_count(
    tmp_path: Path, count: int, primary_steps: list[str]
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    kwargs["primary_dispatch_count"] = count
    kwargs["payload_bindings"] = {
        "primary_steps": primary_steps,
        "verification_steps": ["turn1.structured-refusal"],
    }

    with pytest.raises(BusinessOraclePlanError, match="emptiness.*zero"):
        write_business_oracle_plan(**kwargs)


def test_common_reader_safely_returns_full_payload_without_family_expectations(
    tmp_path: Path,
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    written = write_business_oracle_plan(**kwargs)

    common = read_business_oracle_plan_envelope(
        written.path, **_common_kwargs(kwargs)
    )

    assert common == written
    assert common.payload["payload_bindings"] == kwargs["payload_bindings"]
    assert common.payload["assertion_ids"] == kwargs["assertion_ids"]
    assert common.payload["static_expectation"] == kwargs["static_expectation"]
    assert common.payload["live_binding"] == kwargs["live_binding"]
    assert common.payload["delta_rules"] == kwargs["delta_rules"]


def test_common_reader_binds_common_fields_but_leaves_typed_family_comparison_to_caller(
    tmp_path: Path,
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    written = write_business_oracle_plan(**kwargs)
    payload = copy.deepcopy(written.payload)
    payload["static_expectation"] = {"different_but_basic_json": True}
    _rewrite(written.path, payload)

    common = read_business_oracle_plan_envelope(
        written.path, **_common_kwargs(kwargs)
    )
    assert common.payload["static_expectation"] == {"different_but_basic_json": True}
    with pytest.raises(BusinessOraclePlanError, match="runner-owned expected values"):
        read_business_oracle_plan(written.path, **kwargs)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("protocol_sha256", SHA_A),
        ("provenance_sha256", SHA_A),
        ("primary_dispatch_count", 2),
        ("fixture_spec", {"kind": "other.fixture", "sha256": SHA_A}),
    ],
)
def test_common_reader_rejects_common_binding_mismatch(
    tmp_path: Path, field: str, bad: Any
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    written = write_business_oracle_plan(**kwargs)
    common = _common_kwargs(kwargs)
    common[field] = bad

    with pytest.raises(BusinessOraclePlanError, match="common envelope"):
        read_business_oracle_plan_envelope(written.path, **common)


def test_exclusive_writer_rejects_rewrite(tmp_path: Path) -> None:
    kwargs = _kwargs(_root(tmp_path))
    first = write_business_oracle_plan(**kwargs)

    with pytest.raises(BusinessOraclePlanError, match="exclusively create"):
        write_business_oracle_plan(**kwargs)

    assert read_business_oracle_plan(first.path, **kwargs) == first


def test_reader_rejects_missing_plan(tmp_path: Path) -> None:
    kwargs = _kwargs(root := _root(tmp_path))

    with pytest.raises(BusinessOraclePlanError, match="cannot open"):
        read_business_oracle_plan(
            root / "evidence" / BUSINESS_ORACLE_PLAN_FILE, **kwargs
        )


def test_reader_rejects_nonfixed_path(tmp_path: Path) -> None:
    kwargs = _kwargs(root := _root(tmp_path))
    other = root / "evidence" / "other.json"
    other.write_text("{}\n", encoding="utf-8")

    with pytest.raises(BusinessOraclePlanError, match="fixed scenario evidence path"):
        read_business_oracle_plan(other, **kwargs)


def test_reader_rejects_cross_scenario_identity(tmp_path: Path) -> None:
    kwargs = _kwargs(_root(tmp_path), scenario_id="OBJ22-GET-A")
    evidence = write_business_oracle_plan(**kwargs)
    other = dict(kwargs, scenario_id="OBJ22-GET-B")

    with pytest.raises(BusinessOraclePlanError, match="runner-owned expected values"):
        read_business_oracle_plan(evidence.path, **other)


def test_reader_rejects_cross_api_and_family_plan(tmp_path: Path) -> None:
    root = _root(tmp_path)
    stored = _kwargs(root, api="ak.wwise.core.audio.import", scenario_id="AUD22-IMPORT")
    evidence = write_business_oracle_plan(**stored)
    expected = _kwargs(root, api="ak.wwise.core.object.get", scenario_id="AUD22-IMPORT")

    with pytest.raises(BusinessOraclePlanError, match="runner-owned expected values"):
        read_business_oracle_plan(evidence.path, **expected)


def test_reader_rejects_cross_scenario_root(tmp_path: Path) -> None:
    first = _kwargs(_root(tmp_path, "first"))
    evidence = write_business_oracle_plan(**first)
    second = dict(first, scenario_root=_root(tmp_path, "second"))

    with pytest.raises(BusinessOraclePlanError, match="fixed scenario evidence path"):
        read_business_oracle_plan(evidence.path, **second)


def test_writer_rejects_symlink_scenario_root(tmp_path: Path) -> None:
    real = _root(tmp_path, "real")
    alias = tmp_path / "alias"
    create_symlink_or_skip(alias, real, target_is_directory=True)

    with pytest.raises(BusinessOraclePlanError, match="scenario root must be a real"):
        write_business_oracle_plan(**_kwargs(alias))


def test_writer_rejects_symlink_evidence_root(tmp_path: Path) -> None:
    root = tmp_path / "scenario"
    root.mkdir()
    actual = tmp_path / "actual-evidence"
    actual.mkdir()
    create_symlink_or_skip(root / "evidence", actual, target_is_directory=True)

    with pytest.raises(BusinessOraclePlanError, match="evidence root must be a real"):
        write_business_oracle_plan(**_kwargs(root))


def test_reader_does_not_follow_plan_symlink(tmp_path: Path) -> None:
    kwargs = _kwargs(root := _root(tmp_path))
    target = tmp_path / "target.json"
    target.write_bytes(b"{}\n")
    path = root / "evidence" / BUSINESS_ORACLE_PLAN_FILE
    create_symlink_or_skip(path, target)

    with pytest.raises(BusinessOraclePlanError, match="cannot open|path changed"):
        read_business_oracle_plan(path, **kwargs)


def test_reader_rejects_fixed_path_swap_after_descriptor_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    evidence = write_business_oracle_plan(**kwargs)
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(evidence.path.read_bytes())
    original_read = plan_module.os.read
    swapped = False

    def read_then_swap(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        chunk = original_read(descriptor, count)
        if not swapped:
            os.replace(replacement, evidence.path)
            swapped = True
        return chunk

    monkeypatch.setattr(plan_module.os, "read", read_then_swap)

    with pytest.raises(BusinessOraclePlanError, match="path changed during read"):
        read_business_oracle_plan(evidence.path, **kwargs)
    assert swapped is True


def test_reader_rejects_directory_instead_of_regular_file(tmp_path: Path) -> None:
    kwargs = _kwargs(root := _root(tmp_path))
    path = root / "evidence" / BUSINESS_ORACLE_PLAN_FILE
    path.mkdir()

    with pytest.raises(BusinessOraclePlanError, match="regular file"):
        read_business_oracle_plan(path, **kwargs)


def test_reader_rejects_oversized_file_before_json_parsing(tmp_path: Path) -> None:
    kwargs = _kwargs(root := _root(tmp_path))
    path = root / "evidence" / BUSINESS_ORACLE_PLAN_FILE
    path.write_bytes(b" " * (MAX_BUSINESS_ORACLE_PLAN_BYTES + 1))

    with pytest.raises(BusinessOraclePlanError, match="size ceiling"):
        read_business_oracle_plan(path, **kwargs)


def test_reader_rejects_noncanonical_but_equivalent_json(tmp_path: Path) -> None:
    kwargs = _kwargs(_root(tmp_path))
    evidence = write_business_oracle_plan(**kwargs)
    _rewrite(evidence.path, dict(evidence.payload), canonical=False)

    with pytest.raises(BusinessOraclePlanError, match="not canonical JSON"):
        read_business_oracle_plan(evidence.path, **kwargs)


def test_reader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    kwargs = _kwargs(_root(tmp_path))
    evidence = write_business_oracle_plan(**kwargs)
    raw = _canonical(evidence.payload).decode("utf-8")
    raw = raw.replace(
        '"contract":', '"contract":"shadowed","contract":', 1
    )
    evidence.path.write_text(raw, encoding="utf-8")

    with pytest.raises(BusinessOraclePlanError, match="duplicate JSON key"):
        read_business_oracle_plan(evidence.path, **kwargs)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_reader_rejects_open_top_level_schema(tmp_path: Path, mutation: str) -> None:
    kwargs = _kwargs(_root(tmp_path))
    evidence = write_business_oracle_plan(**kwargs)
    payload = copy.deepcopy(evidence.payload)
    if mutation == "missing":
        payload.pop("live_binding")
    else:
        payload["untrusted"] = True
    _rewrite(evidence.path, payload)

    with pytest.raises(BusinessOraclePlanError, match="top-level schema is not closed"):
        read_business_oracle_plan(evidence.path, **kwargs)


def test_reader_rejects_canonical_valid_external_rewrite(tmp_path: Path) -> None:
    kwargs = _kwargs(_root(tmp_path))
    evidence = write_business_oracle_plan(**kwargs)
    payload = copy.deepcopy(evidence.payload)
    payload["static_expectation"]["rows"][0]["volume"] = 12
    _rewrite(evidence.path, payload)

    with pytest.raises(BusinessOraclePlanError, match="runner-owned expected values"):
        read_business_oracle_plan(evidence.path, **kwargs)


@pytest.mark.parametrize("field", ["protocol_sha256", "provenance_sha256"])
@pytest.mark.parametrize("bad", ["A" * 64, "f" * 63, 1])
def test_hash_bindings_require_lowercase_sha256(
    tmp_path: Path, field: str, bad: Any
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    kwargs[field] = bad

    with pytest.raises(BusinessOraclePlanError, match=field):
        write_business_oracle_plan(**kwargs)


@pytest.mark.parametrize("bad", [-1, True, 1.0, "1"])
def test_dispatch_count_requires_plain_nonnegative_integer(
    tmp_path: Path, bad: Any
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    kwargs["primary_dispatch_count"] = bad

    with pytest.raises(BusinessOraclePlanError, match="plain nonnegative int"):
        write_business_oracle_plan(**kwargs)


@pytest.mark.parametrize(
    "api,runner,family",
    [
        ("ak.wwise.core.object.get", "cli", "object"),
        ("ak.wwise.cli.migrate", "project", "cli"),
        ("ak.wwise.core.object.get", "project", "audio_import"),
        ("ak.wwise.core.object.get", "unknown", "object"),
    ],
)
def test_runner_and_family_are_cross_bound_to_api(
    tmp_path: Path, api: str, runner: str, family: str
) -> None:
    kwargs = _kwargs(_root(tmp_path), api=api)
    kwargs.update(runner=runner, family=family)

    with pytest.raises(BusinessOraclePlanError, match="runner|family"):
        write_business_oracle_plan(**kwargs)


@pytest.mark.parametrize(
    "fixture_spec",
    [
        {},
        {"kind": "fixture"},
        {"kind": "fixture", "sha256": SHA_A, "extra": True},
        {"kind": "", "sha256": SHA_A},
        {"kind": "fixture", "sha256": "bad"},
    ],
)
def test_fixture_spec_has_closed_kind_and_digest_schema(
    tmp_path: Path, fixture_spec: dict[str, Any]
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    kwargs["fixture_spec"] = fixture_spec

    with pytest.raises(BusinessOraclePlanError, match="fixture_spec"):
        write_business_oracle_plan(**kwargs)


@pytest.mark.parametrize(
    "payload_bindings",
    [
        {},
        {"primary_steps": ["one"]},
        {"primary_steps": ["one"], "verification_steps": [], "extra": []},
        {"primary_steps": [], "verification_steps": []},
        {"primary_steps": ["one", "one"], "verification_steps": []},
        {"primary_steps": ["one"], "verification_steps": ["verify", "verify"]},
        {"primary_steps": "one", "verification_steps": []},
    ],
)
def test_payload_bindings_have_closed_unique_step_lists(
    tmp_path: Path, payload_bindings: dict[str, Any]
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    kwargs["payload_bindings"] = payload_bindings

    with pytest.raises(BusinessOraclePlanError, match="payload_bindings"):
        write_business_oracle_plan(**kwargs)


@pytest.mark.parametrize(
    "assertion_ids",
    [[], ["same", "same"], [""], [1], "one"],
)
def test_assertion_ids_are_nonempty_unique_identifiers(
    tmp_path: Path, assertion_ids: Any
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    kwargs["assertion_ids"] = assertion_ids

    with pytest.raises(BusinessOraclePlanError, match="assertion_ids"):
        write_business_oracle_plan(**kwargs)


@pytest.mark.parametrize("field", ["static_expectation", "live_binding"])
@pytest.mark.parametrize("bad", [[], "value", 1, None])
def test_static_and_live_sections_must_be_json_objects(
    tmp_path: Path, field: str, bad: Any
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    kwargs[field] = bad

    with pytest.raises(BusinessOraclePlanError, match=field):
        write_business_oracle_plan(**kwargs)


@pytest.mark.parametrize("bad", [{"rule": True}, ["bad"], [1], None])
def test_delta_rules_must_be_an_array_of_json_objects(
    tmp_path: Path, bad: Any
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    kwargs["delta_rules"] = bad

    with pytest.raises(BusinessOraclePlanError, match="delta_rules"):
        write_business_oracle_plan(**kwargs)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("static_expectation", {"path": Path("not-json")}),
        ("live_binding", {1: "non-string-key"}),
        ("delta_rules", [{"value": float("nan")}]),
    ],
)
def test_nested_plan_values_must_be_closed_finite_json(
    tmp_path: Path, field: str, bad: Any
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    kwargs[field] = bad

    with pytest.raises(BusinessOraclePlanError, match="JSON|non-finite|non-string"):
        write_business_oracle_plan(**kwargs)


@pytest.mark.parametrize("version", ["2020.1", "2022", "2026.1", 2022])
def test_version_is_limited_to_supported_lanes(tmp_path: Path, version: Any) -> None:
    kwargs = _kwargs(_root(tmp_path))
    kwargs["version"] = version

    with pytest.raises(BusinessOraclePlanError, match="version is unsupported"):
        write_business_oracle_plan(**kwargs)


@pytest.mark.parametrize("field", ["version", "api", "family", "runner"])
@pytest.mark.parametrize("bad", [[], {"hostile": True}, True])
def test_unhashable_and_nonstring_common_inputs_fail_with_plan_error(
    tmp_path: Path, field: str, bad: Any
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    kwargs[field] = bad

    with pytest.raises(BusinessOraclePlanError):
        write_business_oracle_plan(**kwargs)


@pytest.mark.parametrize("field", ["version", "api", "family", "runner"])
@pytest.mark.parametrize("bad", [[], {"hostile": True}, True])
def test_unhashable_and_nonstring_persisted_common_values_fail_with_plan_error(
    tmp_path: Path, field: str, bad: Any
) -> None:
    kwargs = _kwargs(_root(tmp_path))
    evidence = write_business_oracle_plan(**kwargs)
    payload = copy.deepcopy(evidence.payload)
    payload[field] = bad
    _rewrite(evidence.path, payload)

    with pytest.raises(BusinessOraclePlanError):
        read_business_oracle_plan(evidence.path, **kwargs)
