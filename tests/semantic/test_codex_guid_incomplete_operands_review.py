"""Frozen incomplete-comparison controls at the prospective-notice seam."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.semantic.test_codex_guid_comparison_notices import _notice


_MATRIX = Path(__file__).parents[1] / "fixtures/semantic/expansion-guid-incomplete-operands-review-20261007.json"
_CASES = json.loads(_MATRIX.read_text(encoding="utf-8"))["cases"]


def test_qualified_operand_review_expectations_remain_frozen():
    assert hashlib.sha256(_MATRIX.read_bytes()).hexdigest() == "27350694b24eb9b75368cdf996373047faeab969a0655a916b292144264dcfa9"


@pytest.mark.parametrize("vector", _CASES, ids=[vector["id"] for vector in _CASES])
def test_existing_operand_alternatives_are_accounted_at_preview_notice(vector):
    assert _notice(vector) is vector["expected_gate"], vector["reason"]
