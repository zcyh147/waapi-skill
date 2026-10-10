"""Frozen incomplete-comparison controls at the prospective-notice seam."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.semantic.test_codex_guid_comparison_notices import _notice


_MATRIX = Path(__file__).parents[1] / "fixtures/semantic/expansion-guid-opaque-qualifier-review-20261007.json"
_CASES = json.loads(_MATRIX.read_text(encoding="utf-8"))["cases"]


def test_opaque_qualifier_review_expectations_remain_frozen():
    assert hashlib.sha256(_MATRIX.read_bytes()).hexdigest() == "208f4ce3dcf3c034b21f1f346dffef7d0321a06d98d0142ebdc9b0471407eb11"


@pytest.mark.parametrize("vector", _CASES, ids=[vector["id"] for vector in _CASES])
def test_opaque_qualifier_comparison_is_accounted_at_preview_notice(vector):
    assert _notice(vector) is vector["expected_gate"], vector["reason"]


_SEPARATOR = _MATRIX.with_name("expansion-guid-opaque-qualifier-separator-control-20261007.json")
_SEPARATOR_CASES = json.loads(_SEPARATOR.read_text(encoding="utf-8"))["cases"]


def test_separator_control_expectation_remains_frozen():
    assert hashlib.sha256(_SEPARATOR.read_bytes()).hexdigest() == "233ed915938c6fc65b72caf28eab7645d426ac30fc80eb436fc99cd69ef55fa4"


@pytest.mark.parametrize("vector", _SEPARATOR_CASES, ids=[vector["id"] for vector in _SEPARATOR_CASES])
def test_verbal_coordination_does_not_hide_a_standalone_comparator(vector):
    assert _notice(vector) is vector["expected_gate"], vector["reason"]
