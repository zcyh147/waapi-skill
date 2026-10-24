"""Exercise the native observer's exact public read path without starting Wwise."""
from types import SimpleNamespace

import pytest

from tests.support.playlist_reference_observation import collect_playlist_slot_reference_metadata
from tests.unit import test_metadata_discovery_gateway as public


@pytest.mark.parametrize("has_flag", [True, False])
def test_playlist_observer_preserves_disclosed_restrictions(tmp_path, has_flag):
    responses = public._metadata_responses(tmp_path, version="2025.1", names=("PlaylistObject",))
    responses[public.GET_TYPES_URI] = {
        "return": [{"classId": 5636096, "name": "PlaylistSlot", "type": "WObject"}]
    }
    responses[public.GET_PROPERTY_INFO_URI] = {
        "name": "PlaylistObject", "type": "", "default": None,
        "restriction": {
            "type": "reference",
            "restrictions": [{"type": ["Sound", "RandomSequenceContainer", "SwitchContainer", "BlendContainer"]},
                             "notNull", *(["mustChildOf"] if has_flag else [])],
        },
    }
    client = public.FakeClient(responses)
    env = public._gateway_env(tmp_path, version="2025.1")
    code, payload = public.waapi_gateway.execute_gateway(
        ["config-set", "--project-modification-policy", "read_only"], env=env,
    )
    assert code == 0, payload
    runtime = SimpleNamespace(candidate="controlled-program-only", version="2025.1",
        state_dir=tmp_path / "observations", category_results=[], raw_gateway=lambda argv:
        public.waapi_gateway.execute_gateway(argv, env=env, client_factory=lambda _: client))
    if has_flag:
        collect_playlist_slot_reference_metadata(runtime)
        assert runtime.category_results[0]["status"] == "PASS"
    else:
        with pytest.raises(AssertionError):
            collect_playlist_slot_reference_metadata(runtime)
        assert runtime.category_results[0]["status"] == "FAIL"
    assert runtime.category_results[0]["business_effect_verified"] is False
    assert (tmp_path / "observations" / "playlist-reference-metadata.json").is_file()
