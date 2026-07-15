from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import pytest

import tests.semantic.support.codex_campaign as campaign_module

from tests.semantic.support.codex_campaign import (
    ATTEMPT_LEDGER_FILE,
    ATTEMPT_MANIFEST_CONTRACT,
    ATTEMPT_MANIFEST_FILE,
    CampaignEvidenceError,
    atomic_write_json_with_digest,
    canonical_json_bytes,
    consolidate_units,
    create_attempt,
    create_immutable_campaign_config,
    load_immutable_campaign_config,
    load_verified_json,
    list_campaign_attempts,
    seal_attempt,
    stable_tree_manifest,
    stable_tree_sha256,
    verify_attempt_seal,
)


_TEST_CAMPAIGN_ID = "00000000-0000-4000-8000-000000000001"
_TEST_CONFIG_DIGEST = "a" * 64


def _observation(
    unit_id: str,
    status: str,
    *phases: tuple[str, str],
) -> dict[str, object]:
    return {
        "unit_id": unit_id,
        "status": status,
        "phases": [{"phase": phase, "status": phase_status} for phase, phase_status in phases],
    }


def _manifest(attempt_id: str, *observations: dict[str, object]) -> dict[str, object]:
    return {
        "contract": ATTEMPT_MANIFEST_CONTRACT,
        "campaign_id": _TEST_CAMPAIGN_ID,
        "campaign_config_sha256": _TEST_CONFIG_DIGEST,
        "attempt_id": attempt_id,
        "artifacts": [],
        "unit_observations": list(observations),
    }


def _campaign(tmp_path: Path) -> Path:
    root = tmp_path / "campaign"
    create_immutable_campaign_config(root, {"profile": "screening", "candidate": "abc"})
    return root


def test_canonical_json_is_deterministic_and_strict() -> None:
    assert canonical_json_bytes({"b": 2, "a": "中文"}) == canonical_json_bytes(
        {"a": "中文", "b": 2}
    )
    with pytest.raises(CampaignEvidenceError, match="strict JSON"):
        canonical_json_bytes({"bad": float("nan")})
    with pytest.raises(CampaignEvidenceError, match="keys must be strings"):
        canonical_json_bytes({"nested": {1: "ambiguous"}})


def test_stable_tree_hash_ignores_times_but_binds_content_mode_path_and_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    payload = root / "payload.txt"
    payload.write_text("one", encoding="utf-8")
    target_a = root / "target-a"
    target_b = root / "target-b"
    target_a.write_text("same", encoding="utf-8")
    target_b.write_text("same", encoding="utf-8")
    link = root / "link"
    link.symlink_to("target-a")

    baseline = stable_tree_sha256(root)
    os.utime(payload, (payload.stat().st_atime + 10, payload.stat().st_mtime + 10))
    assert stable_tree_sha256(root) == baseline

    os.chmod(payload, payload.stat().st_mode | 0o111)
    mode_hash = stable_tree_sha256(root)
    assert mode_hash != baseline
    os.chmod(payload, payload.stat().st_mode & ~0o111)
    assert stable_tree_sha256(root) == baseline

    payload.write_text("two", encoding="utf-8")
    assert stable_tree_sha256(root) != baseline
    payload.write_text("one", encoding="utf-8")
    assert stable_tree_sha256(root) == baseline

    link.unlink()
    link.symlink_to("target-b")
    assert stable_tree_sha256(root) != baseline
    link.unlink()
    link.symlink_to("target-a")
    assert stable_tree_sha256(root) == baseline

    payload.rename(root / "renamed.txt")
    assert stable_tree_sha256(root) != baseline


def test_stable_tree_manifest_records_symlink_without_following_and_supports_excludes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "keep").write_text("keep", encoding="utf-8")
    ignored = root / "ignored"
    ignored.mkdir()
    (ignored / "secret").write_text("secret", encoding="utf-8")
    (root / "link").symlink_to("missing-target")

    rows = stable_tree_manifest(root, exclude_names=("ignored",))

    assert {row["path"] for row in rows} == {"keep", "link"}
    assert next(row for row in rows if row["path"] == "link") == {
        "path": "link",
        "type": "symlink",
        "target": "missing-target",
    }


def test_atomic_json_digest_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    digest = atomic_write_json_with_digest(path, {"value": [1, 2, 3]})

    assert load_verified_json(path) == {"value": [1, 2, 3]}
    assert (path.with_name(path.name + ".sha256")).read_text(encoding="ascii") == digest + "\n"

    path.write_text('{"value":[1,2,4]}\n', encoding="utf-8")
    with pytest.raises(CampaignEvidenceError, match="SHA-256 mismatch"):
        load_verified_json(path)


def test_verified_json_rejects_duplicate_keys_even_with_matching_digest(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    data = b'{"same":1,"same":2}\n'
    path.write_bytes(data)
    path.with_name(path.name + ".sha256").write_text(
        hashlib.sha256(data).hexdigest() + "\n",
        encoding="ascii",
    )

    with pytest.raises(CampaignEvidenceError, match="duplicate JSON key"):
        load_verified_json(path)


def test_verified_json_uses_one_nofollow_read_per_attested_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "evidence.json"
    atomic_write_json_with_digest(path, {"safe": True})
    original = campaign_module._read_real_regular_file
    reads: list[Path] = []

    def recording_read(candidate: Path, *, label: str) -> bytes:
        reads.append(Path(candidate))
        return original(candidate, label=label)

    monkeypatch.setattr(campaign_module, "_read_real_regular_file", recording_read)

    assert load_verified_json(path) == {"safe": True}
    assert reads == [path, path.with_name(path.name + ".sha256")]

    real = tmp_path / "real.json"
    atomic_write_json_with_digest(real, {"safe": True})
    link = tmp_path / "link.json"
    link.symlink_to(real.name)
    shutil.copyfile(
        real.with_name(real.name + ".sha256"),
        link.with_name(link.name + ".sha256"),
    )
    with pytest.raises(CampaignEvidenceError, match="without following links"):
        load_verified_json(link)


def test_campaign_config_is_immutable_and_digest_verified(tmp_path: Path) -> None:
    root = tmp_path / "campaign"
    created = create_immutable_campaign_config(root, {"profile": "formal_98"})

    assert load_immutable_campaign_config(root) == created
    with pytest.raises(CampaignEvidenceError, match="already exists"):
        create_immutable_campaign_config(root, {"profile": "screening"})

    (root / "campaign-config.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(CampaignEvidenceError, match="SHA-256 mismatch"):
        load_immutable_campaign_config(root)


def test_campaign_config_adds_canonical_id_and_rejects_non_string_keys(tmp_path: Path) -> None:
    root = tmp_path / "campaign"
    created = create_immutable_campaign_config(root, {"profile": "screening"})

    assert created["campaign_id"]
    assert load_verified_json(root / ATTEMPT_LEDGER_FILE)["campaign_id"] == created[
        "campaign_id"
    ]

    with pytest.raises(CampaignEvidenceError, match="keys must be strings"):
        create_immutable_campaign_config(tmp_path / "bad", {1: "bad"})  # type: ignore[dict-item]


def test_attempt_ids_are_append_only_and_attempt_descriptor_is_attested(tmp_path: Path) -> None:
    root = _campaign(tmp_path)

    first_id, first = create_attempt(root)
    second_id, second = create_attempt(root)

    assert (first_id, second_id) == ("attempt-000001", "attempt-000002")
    config = load_immutable_campaign_config(root)
    first_descriptor = load_verified_json(first / "attempt.json")
    second_descriptor = load_verified_json(second / "attempt.json")
    ledger = load_verified_json(root / ATTEMPT_LEDGER_FILE)

    assert first_descriptor["attempt_id"] == first_id
    assert second_descriptor["attempt_id"] == second_id
    assert first_descriptor["campaign_id"] == config["campaign_id"]
    assert first_descriptor["campaign_config_sha256"] == ledger[
        "campaign_config_sha256"
    ]
    assert [path.name for path in list_campaign_attempts(root)] == [first_id, second_id]
    assert ledger["last_attempt_number"] == 2
    assert [row["attempt_id"] for row in ledger["attempts"]] == [first_id, second_id]


def test_attempt_ledger_detects_deletion_and_never_reuses_number(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    _first_id, _first = create_attempt(root)
    second_id, second = create_attempt(root)
    shutil.rmtree(second)

    with pytest.raises(CampaignEvidenceError, match="missing or unledgered"):
        list_campaign_attempts(root)
    with pytest.raises(CampaignEvidenceError, match="missing or unledgered"):
        create_attempt(root)

    assert second_id == "attempt-000002"
    assert not (root / "attempts" / "attempt-000002").exists()


def test_attempt_ledger_rejects_rollbacks_gaps_and_descriptor_replacement(
    tmp_path: Path,
) -> None:
    root = _campaign(tmp_path)
    _first_id, first = create_attempt(root)
    _second_id, _second = create_attempt(root)
    ledger_path = root / ATTEMPT_LEDGER_FILE
    ledger = load_verified_json(ledger_path)
    ledger["attempts"] = ledger["attempts"][:1]
    ledger["last_attempt_number"] = 1
    atomic_write_json_with_digest(ledger_path, ledger)

    with pytest.raises(CampaignEvidenceError, match="missing or unledgered"):
        list_campaign_attempts(root)

    # Restore the ledger, then prove a recomputed descriptor digest cannot
    # silently replace the descriptor recorded by the append-only head.
    shutil.rmtree(root)
    root = _campaign(tmp_path)
    _first_id, first = create_attempt(root)
    descriptor = load_verified_json(first / "attempt.json")
    descriptor["campaign_id"] = "00000000-0000-4000-8000-000000000099"
    atomic_write_json_with_digest(first / "attempt.json", descriptor)
    with pytest.raises(CampaignEvidenceError, match="attempt descriptor"):
        list_campaign_attempts(root)


def test_attempt_ledger_digest_and_campaign_config_digest_are_verified(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    create_attempt(root)
    ledger_path = root / ATTEMPT_LEDGER_FILE
    ledger_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(CampaignEvidenceError, match="SHA-256 mismatch"):
        list_campaign_attempts(root)

    shutil.rmtree(root)
    root = _campaign(tmp_path)
    create_attempt(root)
    config_path = root / "campaign-config.json"
    config = load_verified_json(config_path)
    config["profile"] = "different"
    atomic_write_json_with_digest(config_path, config)
    with pytest.raises(CampaignEvidenceError, match="wrong config"):
        list_campaign_attempts(root)


def test_attempt_seal_verifies_exact_regular_artifact_set(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    _attempt_id, attempt = create_attempt(root)
    output = attempt / "runs" / "offline" / "matrix" / "summary.json"
    output.parent.mkdir(parents=True)
    output.write_text('{"all_selected_passed":true}\n', encoding="utf-8")
    observation = _observation("screening:C1:2022.1:r1", "PASS", ("single", "PASS"))

    sealed = seal_attempt(attempt, [observation])
    verified = verify_attempt_seal(attempt)

    assert verified == sealed
    assert verified["unit_observations"] == [observation]
    config = load_immutable_campaign_config(root)
    assert verified["campaign_id"] == config["campaign_id"]
    assert verified["campaign_config_sha256"] == load_verified_json(
        root / ATTEMPT_LEDGER_FILE
    )["campaign_config_sha256"]
    assert {row["path"] for row in verified["artifacts"]} == {
        "attempt.json",
        "attempt.json.sha256",
        "runs/offline/matrix/summary.json",
    }


def test_attempt_seal_rejects_tampered_or_misbound_attempt_descriptor(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    _attempt_id, attempt = create_attempt(root)
    atomic_write_json_with_digest(
        attempt / "attempt.json",
        {
            "contract": "wrong",
            "attempt_id": attempt.name,
            "campaign_id": "00000000-0000-4000-8000-000000000099",
            "campaign_config_sha256": "b" * 64,
        },
    )

    with pytest.raises(CampaignEvidenceError, match="attempt descriptor"):
        seal_attempt(attempt, [])


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("campaign_id", "00000000-0000-4000-8000-000000000099"),
        ("campaign_config_sha256", "b" * 64),
    ],
)
def test_attempt_manifest_campaign_binding_is_verified(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    root = _campaign(tmp_path)
    _attempt_id, attempt = create_attempt(root)
    seal_attempt(attempt, [])
    manifest_path = attempt / ATTEMPT_MANIFEST_FILE
    manifest = load_verified_json(manifest_path)
    manifest[field] = replacement
    atomic_write_json_with_digest(manifest_path, manifest)

    with pytest.raises(CampaignEvidenceError, match="wrong campaign config"):
        verify_attempt_seal(attempt)


@pytest.mark.parametrize("mutation", ["modify", "extra"])
def test_attempt_seal_rejects_modified_or_extra_files(tmp_path: Path, mutation: str) -> None:
    root = _campaign(tmp_path)
    _attempt_id, attempt = create_attempt(root)
    artifact = attempt / "result.txt"
    artifact.write_text("original", encoding="utf-8")
    seal_attempt(attempt, [])

    if mutation == "modify":
        artifact.write_text("changed", encoding="utf-8")
    else:
        (attempt / "extra.txt").write_text("extra", encoding="utf-8")

    with pytest.raises(CampaignEvidenceError, match="missing, extra, or modified"):
        verify_attempt_seal(attempt)


def test_attempt_seal_rejects_symlinks_and_unsafe_manifest_paths(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    _attempt_id, attempt = create_attempt(root)
    (attempt / "real.txt").write_text("real", encoding="utf-8")
    (attempt / "link.txt").symlink_to("real.txt")
    with pytest.raises(CampaignEvidenceError, match="may not contain symlinks"):
        seal_attempt(attempt, [])

    (attempt / "link.txt").unlink()
    seal_attempt(attempt, [])
    manifest_path = attempt / ATTEMPT_MANIFEST_FILE
    manifest = load_verified_json(manifest_path)
    manifest["artifacts"][0]["path"] = "../escape"
    atomic_write_json_with_digest(manifest_path, manifest)
    with pytest.raises(CampaignEvidenceError, match="unsafe relative path"):
        verify_attempt_seal(attempt)


def test_attempt_artifact_walk_errors_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _campaign(tmp_path)
    _attempt_id, attempt = create_attempt(root)

    def denied_walk(
        _root: Path,
        *,
        topdown: bool,
        onerror: object,
        followlinks: bool,
    ) -> object:
        assert topdown is True
        assert followlinks is False
        assert callable(onerror)
        onerror(PermissionError("denied"))
        yield  # pragma: no cover - makes this a generator

    monkeypatch.setattr(campaign_module.os, "walk", denied_walk)
    with pytest.raises(CampaignEvidenceError, match="cannot walk attempt evidence"):
        seal_attempt(attempt, [])


def test_unit_observation_schema_is_exact_and_cannot_inject_provenance(
    tmp_path: Path,
) -> None:
    root = _campaign(tmp_path)
    _attempt_id, attempt = create_attempt(root)
    injected = _observation("screening:Q1:2022.1:r1", "PASS", ("single", "PASS"))
    injected["attempt_id"] = "attempt-999999"

    with pytest.raises(CampaignEvidenceError, match="exactly unit_id/status/phases"):
        seal_attempt(attempt, [injected])

    manifest = _manifest("attempt-000001", injected)
    with pytest.raises(CampaignEvidenceError, match="exactly unit_id/status/phases"):
        consolidate_units({"screening:Q1:2022.1:r1": ("single",)}, [manifest])


def test_consolidation_requires_all_pair_phases_in_one_attempt() -> None:
    unit = "screening:M1:2022.1:r1"
    required = {unit: ("preview", "confirm")}
    preview_only = _manifest(
        "attempt-000001",
        _observation(unit, "PASS", ("preview", "PASS")),
    )
    confirm_only = _manifest(
        "attempt-000002",
        _observation(unit, "PASS", ("confirm", "PASS")),
    )

    consolidated = consolidate_units(required, [preview_only, confirm_only])

    assert consolidated["units"][unit]["status"] == "BLOCKED"
    assert consolidated["all_selected_passed"] is False


def test_consolidation_allows_pre_action_retryable_then_complete_pass() -> None:
    unit = "screening:M1:2022.1:r1"
    required = {unit: ("preview", "confirm")}
    retryable = _manifest(
        "attempt-000001",
        _observation(unit, "RETRYABLE", ("preview", "PASS"), ("confirm", "RETRYABLE")),
    )
    passed = _manifest(
        "attempt-000002",
        _observation(unit, "PASS", ("preview", "PASS"), ("confirm", "PASS")),
    )

    consolidated = consolidate_units(required, [retryable, passed])

    assert consolidated["passed_unit_ids"] == [unit]
    assert consolidated["all_selected_passed"] is True


def test_consolidation_rejects_cross_campaign_and_non_continuous_attempts() -> None:
    unit = "screening:Q1:2022.1:r1"
    observation = _observation(unit, "PASS", ("single", "PASS"))
    first = _manifest("attempt-000001", observation)
    other_campaign = _manifest("attempt-000002", observation)
    other_campaign["campaign_id"] = "00000000-0000-4000-8000-000000000099"

    with pytest.raises(CampaignEvidenceError, match="different campaigns"):
        consolidate_units({unit: ("single",)}, [first, other_campaign])

    gap = _manifest("attempt-000003", observation)
    with pytest.raises(CampaignEvidenceError, match="continuous prefix"):
        consolidate_units({unit: ("single",)}, [first, gap])


@pytest.mark.parametrize(
    "observation",
    [
        _observation(
            "screening:M1:2022.1:r1",
            "RETRYABLE",
            ("confirm", "RETRYABLE"),
        ),
        _observation(
            "screening:M1:2022.1:r1",
            "RETRYABLE",
            ("preview", "PASS"),
        ),
        _observation(
            "screening:M1:2022.1:r1",
            "FAIL",
            ("preview", "FAIL"),
            ("confirm", "PASS"),
        ),
    ],
)
def test_consolidation_blocks_malformed_retryable_or_fail_phase_sequences(
    observation: dict[str, object],
) -> None:
    unit = "screening:M1:2022.1:r1"
    consolidated = consolidate_units(
        {unit: ("preview", "confirm")},
        [_manifest("attempt-000001", observation)],
    )

    assert consolidated["blocked_unit_ids"] == [unit]


@pytest.mark.parametrize("sticky", ["FAIL", "BLOCKED"])
def test_consolidation_never_erases_fail_or_blocked_with_later_pass(
    sticky: str,
) -> None:
    unit = "screening:Q1:2022.1:r1"
    required = {unit: ("single",)}
    first = _manifest(
        "attempt-000001",
        _observation(unit, sticky, ("single", sticky)),
    )
    later = _manifest(
        "attempt-000002",
        _observation(unit, "PASS", ("single", "PASS")),
    )

    consolidated = consolidate_units(required, [first, later])

    assert consolidated["units"][unit]["status"] == sticky
    assert consolidated["all_selected_passed"] is False


def test_consolidation_reports_pending_and_rejects_unknown_or_duplicate_evidence() -> None:
    required = {
        "screening:Q1:2022.1:r1": ("single",),
        "screening:Q2:2022.1:r1": ("single",),
    }
    known = _observation("screening:Q1:2022.1:r1", "PASS", ("single", "PASS"))
    consolidated = consolidate_units(required, [_manifest("attempt-000001", known)])
    assert consolidated["pending_unit_ids"] == ["screening:Q2:2022.1:r1"]

    unknown = _observation("screening:UNKNOWN:2022.1:r1", "PASS", ("single", "PASS"))
    with pytest.raises(CampaignEvidenceError, match="unknown unit"):
        consolidate_units(required, [_manifest("attempt-000001", unknown)])

    with pytest.raises(CampaignEvidenceError, match="duplicate unit observation"):
        consolidate_units(required, [_manifest("attempt-000001", known, known)])
