"""Code-owned fixture and independent-oracle seam for expansion workflows.

Adapters use the public Gateway supplied by the owned scenario runtime. The
interface itself grants neither a live connection nor execution permission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


GatewayCall = Callable[[Sequence[str]], Mapping[str, Any]]
Snapshot = Mapping[str, Any]
TrustedOracleRead = Callable[[str, Sequence[str]], Sequence[Mapping[str, Any]]]


class ExpectedCapabilityBoundary(RuntimeError):
    """A case's reviewed unavailable branch was affirmatively proven.

    This is not a business PASS, a generic fixture failure, or permission to
    convert missing prerequisites into successful capability evidence.
    """

    def __init__(self, case_id: str, version: str, evidence: Mapping[str, Any], *,
                 boundary_code: str = "CAPABILITY_UNAVAILABLE") -> None:
        if not case_id or not version or not boundary_code or not evidence:
            raise ValueError("expected boundary requires explicit identity and evidence")
        self.case_id = case_id
        self.version = version
        self.boundary_code = boundary_code
        self.evidence = dict(evidence)
        super().__init__(f"{case_id}/{version}: expected capability boundary {boundary_code}")


@dataclass(frozen=True)
class ExpansionCaseContext:
    version: str
    scenario_id: str
    project_path: Path
    asset_root: Path
    gateway: GatewayCall
    trusted_read: TrustedOracleRead | None = None


@dataclass(frozen=True)
class PreparedExpansionCase:
    prompt: str
    operation: str
    policy: str
    before: Snapshot
    read_object_ids: frozenset[str]
    relationship_sources: frozenset[str]
    read_includes: frozenset[str]
    required_assertions: frozenset[str]
    approve_preview: Callable[[Mapping[str, Any]], bool]
    snapshot: Callable[[], Snapshot]
    verify: Callable[[Snapshot, Snapshot], Mapping[str, bool]]
    read_fields: frozenset[str] = frozenset()
    request_schema_uri: str | None = None
    accepted_verification_states: frozenset[str] = frozenset({"verified"})
    read_curve_roles: frozenset[str] = frozenset()
    read_platforms: frozenset[str] = frozenset()
    archive_oracle_parameters: Mapping[str, Any] = field(default_factory=dict)
