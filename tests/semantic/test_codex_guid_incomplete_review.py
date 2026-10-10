"""Frozen incomplete-comparison controls at the prospective-notice seam."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.semantic.test_codex_guid_comparison_notices import _notice


_MATRIX = Path(__file__).parents[1] / "fixtures/semantic/expansion-guid-incomplete-review-20261007.json"
_CASES = json.loads(_MATRIX.read_text(encoding="utf-8"))["cases"]


def test_incomplete_review_expectations_remain_frozen():
    assert hashlib.sha256(_MATRIX.read_bytes()).hexdigest() == "9ba4adcebd0e6ae3ebc10e59451ef28e102ac0cc5bb4d0dd0c9931df75f73b3a"


@pytest.mark.parametrize("vector", _CASES, ids=[vector["id"] for vector in _CASES])
def test_incomplete_guid_comparison_is_accounted_at_preview_notice(vector):
    assert _notice(vector) is vector["expected_gate"], vector["reason"]
