"""Validate the committed portable class observations with independent program proof."""
from pathlib import Path

from tests.maintenance import branch_audit_completion as reader
from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import collect_class_metadata as collector
from tests.support import metadata_replay_branch_evidence as replay


def test_actual_portable_class_attachments_bind_native_sources_and_independent_program(monkeypatch):
    monkeypatch.delenv("WAAPI_R51_METADATA_ORIGINAL_ROOT", raising=False)
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
    class_ids = set().union(*(set(collector.collection_plan(version)["eligible_branch_ids"])
                              for version in collector.BUILDS))
    historical_ids = replay.selected_ids()
    assert len(class_ids) == 41 and len(historical_ids) == 9
    assert class_ids.isdisjoint(historical_ids)
    attached = {}
    for descriptor in index["metadata_attachments"]:
        assert not Path(descriptor["artifact"]).is_absolute()
        attachment = reader.read_sealed_artifact(descriptor, base)
        if attachment["contract"] == "waapi-skill.class-metadata-attachment/v1":
            identity = attachment["branch_id"]
            assert identity not in attached
            attached[identity] = attachment
            record = reader.read_sealed_artifact(attachment["evidence"], base)
            assert record["evidence_kind"] == "current_public_class_metadata"
            assert record["scope_kind"] == "product"
            assert record["source_context"]["native_candidate"] == "8a8d5f8e006fd56dd5c78ebe6429ee24450abf26"
            assert len(record["source_context"]["relevant_sources"]) == 560
            assert not Path(record["metadata_run"]["root"]).is_absolute()
    assert set(attached) == class_ids
    selected = {identity for identity, row in policy["branches"].items()
                if "|wwise-console|" in identity
                and "|function|ak.wwise.core.object.getPropertyInfo|" in identity
                and row["categories"] == ["program", "live_metadata"]}
    assert len(selected) == 65
    assert len(selected - class_ids - historical_ids) == 15
    for identity in selected:
        branch, binding = branches[identity], bindings["bindings"][identity]
        assert reader.evidence_result(binding["evidence"]["program"], branch, candidate,
            "program", "product", base, binding, source_root=audit.ROOT,
            reference_edges=edges) == ("passed", None)
        live = reader.evidence_result(binding["evidence"].get("live_metadata"), branch, candidate,
            "live_metadata", "product", base, binding, source_root=audit.ROOT,
            reference_edges=edges)
        if identity in class_ids | historical_ids:
            assert live == ("passed", None), (identity, live)
        else:
            assert live[0] == "missing", (identity, live)
        if identity in class_ids:
            assert binding["input"]["gateway_argv"] != attached[identity]["category_inputs"]["native"]
            assert binding["category_inputs"]["live_metadata"] == attached[identity]["category_inputs"]
