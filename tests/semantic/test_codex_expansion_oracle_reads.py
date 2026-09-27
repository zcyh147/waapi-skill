from typing import Any

import pytest

from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError
from tests.semantic.support.codex_expansion_oracle_reads import expansion_oracle_reader


FIRST = "{11111111-1111-1111-1111-111111111111}"
SECOND = "{22222222-2222-2222-2222-222222222222}"


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_oracle_uses_fixed_read_only_projection_and_preserves_requested_identity_order(version):
    calls = []
    def call(uri, args, options):
        calls.append((uri, args, options))
        return {"return": [{"id": SECOND, "@Curve": [1]}, {"id": FIRST, "@Curve": [2]}]}
    read = expansion_oracle_reader(version=version, read_call=call)
    assert [row["id"] for row in read("rtpc", [FIRST, SECOND])] == [FIRST, SECOND]
    assert calls == [("ak.wwise.core.object.get", {"from": {"id": [FIRST, SECOND]}},
                      {"return": ["id", "name", "type", "path", "parent", "@PropertyName",
                                  "@ControlInput", "@Curve", "notes"]})]


@pytest.mark.parametrize("view,ids", [("ak.wwise.core.object.set", [FIRST]),
                                      ("rtpc", []), ("rtpc", [FIRST, FIRST]),
                                      ("rtpc", ["from objects"]), ("rtpc", [FIRST] * 65)])
def test_oracle_rejects_arbitrary_uri_or_unbounded_selector_before_dispatch(view, ids):
    read = expansion_oracle_reader(version="2025.1", read_call=lambda *_: pytest.fail("dispatched"))
    with pytest.raises(CaseBoundaryError):
        read(view, ids)


@pytest.mark.parametrize("result", [[], [{"id": SECOND}], [{"id": FIRST}, {"id": FIRST}],
                                    [{"id": FIRST, "junk": "x" * 131_072}]])
def test_oracle_rejects_missing_extra_wrong_and_oversized_receipts(result: Any):
    read = expansion_oracle_reader(version="2025.1", read_call=lambda *_: {"return": result})
    with pytest.raises(CaseBoundaryError):
        read("identity", [FIRST])


@pytest.mark.parametrize("version,fields", [
    ("2022.1", ["@Effect0", "@Effect1", "@Effect2", "@Effect3"]),
    ("2025.1", ["@Effects"]),
])
def test_effect_owner_projection_is_pinned_to_the_actual_version_layout(version, fields):
    calls = []
    def call(uri, args, options):
        calls.append(options)
        return {"return": [{"id": FIRST}]}
    read = expansion_oracle_reader(version=version, read_call=call)
    read("effect_owner", [FIRST])
    assert calls == [{"return": ["id", "name", "type", "path", "parent", *fields, "@Volume", "notes"]}]
