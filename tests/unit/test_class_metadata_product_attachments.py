"""Validate the committed portable class observations with independent program proof."""
from pathlib import Path

from tests.maintenance import branch_audit_completion as reader
from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import collect_class_metadata as collector
from tests.support import metadata_replay_branch_evidence as replay


def test_actual_portable_class_attachments_bind_native_sources_and_independent_program(monkeypatch):
    monkeypatch.delenv("WAAPI_R51_METADATA_ORIGINAL_ROOT", raising=False)
    monkeypatch.delenv("WAAPI_R55_CLASS_METADATA_ORIGINALS", raising=False)
    read_bytes = Path.read_bytes

    def portable_only(path):
        if ".waapi-skill-state" in path.parts:
            raise FileNotFoundError("Original machine-local evidence is unavailable")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", portable_only)
    inventory = audit.load(audit.ROOT / "docs/branch-coverage-inventory.json")
    policy = audit.load(audit.ROOT / "docs/branch-coverage-requirements.json")
    index_path = audit.ROOT / "docs/branch-coverage-evidence-index.json"
    index = audit.load(index_path)
    bindings, base, _ = audit.portable_binding_inputs(index_path, policy)
    branches = {row["id"]: row for row in inventory["native_coverage"]["obligations"]}
    edges = {identity: row for identity, row in branches.items() if row["kind"] == "reference"}
    candidate = inventory["native_coverage"]["candidate_sha256"]
    profiles = {cohort: replay.class_original_profile(cohort) for cohort in ("r54", "r55")}
    assert profiles["r55"]["versions"] == ("2021.1", "2022.1", "2023.1", "2024.1")
    cohort_ids = {
        cohort: set().union(*(set(collector.collection_plan(version, cohort=cohort)["eligible_branch_ids"])
                              for version in profile["versions"]))
        for cohort, profile in profiles.items()
    }
    r51_ids = replay.selected_ids()
    assert len(cohort_ids["r54"]) == 41 and len(cohort_ids["r55"]) == 10 and len(r51_ids) == 9
    expected_ids = [*r51_ids, *cohort_ids["r54"], *cohort_ids["r55"]]
    assert len(set(expected_ids)) == len(expected_ids) == 60
    expected_ids = set(expected_ids)
    current_class_sources = replay.r54_current_sources()
    current_r51_sources = replay.source_seals()
    original_r51_sources = replay.historical_sources()
    assert len(original_r51_sources) == 343
    original_class_sources = {}
    attached = {}
    for descriptor in index["metadata_attachments"]:
        assert not Path(descriptor["artifact"]).is_absolute()
        attachment = reader.read_sealed_artifact(descriptor, base)
        identity = attachment["branch_id"]
        assert identity in expected_ids and identity not in attached
        attached[identity] = attachment
        assert not Path(attachment["evidence"]["artifact"]).is_absolute()
        record = reader.read_sealed_artifact(attachment["evidence"], base)
        assert record["scope_kind"] == "product"
        bridge = record["source_bridge"]
        assert bridge["attribution"] == "historical_native_current_program_not_current_native"
        assert set(record["category_inputs"]) == {"historical", "replay"}
        assert record["category_inputs"] == attachment["category_inputs"]
        assert not Path(record["replay"]["artifact"]).is_absolute()
        current = reader.read_sealed_artifact(record["replay"], base)
        assert current["git_candidate"] != bridge["historical_candidate"]
        assert current["gateway"]["argv"] == record["category_inputs"]["replay"]
        if identity in r51_ids:
            assert attachment["contract"] == "waapi-skill.r51-metadata-attachment/v1"
            assert record["evidence_kind"] == "historical_metadata_current_program_replay"
            assert bridge["contract"] == "waapi-skill.r51-metadata-leaf-replay/v1"
            assert bridge["historical_candidate"] == replay.ORIGINAL
            assert bridge["historical_sources"] == original_r51_sources
            assert bridge["current_sources"] == current_r51_sources
            for role in ("category", "observation", "status", "identity", "reply", "native"):
                assert not Path(record["metadata_run"][role]["artifact"]).is_absolute()
        else:
            assert attachment["contract"] == "waapi-skill.class-metadata-attachment/v1"
            assert record["evidence_kind"] == "historical_class_metadata_current_program_replay"
            cohort, = [name for name, identities in cohort_ids.items() if identity in identities]
            profile = profiles[cohort]
            assert bridge["contract"] == profile["bridge_contract"]
            assert bridge["historical_candidate"] == profile["candidate"]
            assert len(bridge["historical_sources"]) == profile["source_count"]
            if cohort not in original_class_sources:
                replay.validate_class_original_sources(profile["candidate"], bridge["historical_sources"], cohort)
                original_class_sources[cohort] = bridge["historical_sources"]
            assert bridge["historical_sources"] == original_class_sources[cohort]
            assert bridge["current_sources"] == current_class_sources
            assert not Path(record["metadata_run"]["root"]).is_absolute()
            assert not Path(record["metadata_run"]["seal"]["artifact"]).is_absolute()
        assert current["relevant_sources"] == bridge["current_sources"]
        assert bridge["changed_files"] == replay.source_changes(bridge["historical_sources"], bridge["current_sources"])
        assert bindings["bindings"][identity]["evidence"]["program"]["sha256"] != record["replay"]["sha256"]
    assert set(attached) == expected_ids
    assert set(original_class_sources) == {"r54", "r55"}
    assert original_class_sources["r54"] != original_class_sources["r55"]
    selected = {identity for identity, row in policy["branches"].items()
                if "|wwise-console|" in identity
                and "|function|ak.wwise.core.object.getPropertyInfo|" in identity}
    assert len(selected) == 65
    assert {identity for identity in selected
            if policy["branches"][identity]["categories"] == ["program", "live_metadata"]} == expected_ids
    missing_ids = selected - expected_ids
    assert expected_ids <= selected and len(missing_ids) == 5
    assert all(policy["branches"][identity]["categories"] == ["program"] for identity in missing_ids)
    assert {branches[identity]["pointer"] for identity in missing_ids} == {
        "/resultSchema/properties/default/@presence/absent"
    }
    assert {identity.split("|", 1)[0] for identity in missing_ids} == set(collector.BUILDS)
    for identity in selected:
        branch, binding = branches[identity], bindings["bindings"][identity]
        assert reader.evidence_result(binding["evidence"]["program"], branch, candidate,
            "program", "product", base, binding, source_root=audit.ROOT,
            reference_edges=edges) == ("passed", None)
        live = reader.evidence_result(binding["evidence"].get("live_metadata"), branch, candidate,
            "live_metadata", "product", base, binding, source_root=audit.ROOT,
            reference_edges=edges)
        if identity in expected_ids:
            assert live == ("passed", None), (identity, live)
        else:
            assert live[0] == "missing", (identity, live)
        if identity in expected_ids:
            assert binding["category_inputs"]["live_metadata"] == attached[identity]["category_inputs"]
