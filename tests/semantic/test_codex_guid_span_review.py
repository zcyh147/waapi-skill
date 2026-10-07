"""Frozen review regressions exercise the actual prospective-notice boundary."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.semantic.test_codex_guid_comparison_notices import _notice


_MATRIX = Path(__file__).parents[1] / "fixtures/semantic/expansion-guid-span-review-final-20261007.json"
_CASES = json.loads(_MATRIX.read_text(encoding="utf-8"))["cases"]
_COORDINATED = _MATRIX.with_name("expansion-guid-span-review-coordinated-20261007.json")
_COORDINATED_CASES = json.loads(_COORDINATED.read_text(encoding="utf-8"))["cases"]


def test_review_vector_expectations_remain_frozen():
    assert hashlib.sha256(_MATRIX.read_bytes()).hexdigest() == "cd97fadcef28f49c58992fddeeea8f8ae68b5ae28f9181e0ca5af65e80c03ddc"
    assert hashlib.sha256(_MATRIX.with_name("expansion-guid-span-review-corrected-20261007.json").read_bytes()).hexdigest() == "62da6aabfe27da72d849dbbd1b249921d920a4e810dcbcc46fd6d1d741664454"
    assert hashlib.sha256(_MATRIX.with_name("expansion-guid-span-review-20261007.json").read_bytes()).hexdigest() == "82d9f71bf6110b1d17fb44a8089aa5593cfcd53d8156fc9b9e8e0c56bcb488fa"
    assert hashlib.sha256(_COORDINATED.read_bytes()).hexdigest() == "daf025c3c372be6597a0a789f525af8f4a2af055ec43808f37396ac7b43afda1"


@pytest.mark.parametrize("vector", _CASES, ids=[vector["id"] for vector in _CASES])
def test_every_comparison_component_is_accounted_at_preview_notice(vector):
    assert _notice(vector) is vector["expected_gate"], vector["reason"]


@pytest.mark.parametrize("vector", _COORDINATED_CASES, ids=[vector["id"] for vector in _COORDINATED_CASES])
def test_coordinated_guid_suffix_cannot_discard_a_preceding_component(vector):
    assert _notice(vector) is vector["expected_gate"], vector["reason"]
