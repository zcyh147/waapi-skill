from __future__ import annotations

import json
import time
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from tests.destructive.test_gateway_transaction_matrix import (
    _parse_packaged_gateway_result,
    _read_subscription_ack,
)
from tests.semantic.support import codex_gateway_broker
from wwise_waapi.subscriptions import SUBSCRIPTION_ACK_CONTRACT


def _ack_payload(*, nonce: str, topic: str, step: str) -> dict[str, object]:
    return {
        "contract": SUBSCRIPTION_ACK_CONTRACT,
        "step_name": step,
        "topic": topic,
        "nonce": nonce,
        "runner_parent_process_id": 101,
        "gateway_process_id": 202,
        "subscribed_at_unix_ns": time.time_ns(),
        "subscribed_at_monotonic_ns": time.monotonic_ns(),
    }


def _write_canonical_ack(path: Path, payload: dict[str, object]) -> None:
    path.write_bytes(
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )


def test_read_subscription_ack_accepts_exact_gateway_owned_document(
    tmp_path: Path,
) -> None:
    nonce = "a" * 43
    topic = "ak.wwise.core.object.created"
    step = "destructive.gateway.wait-topic"
    started_at_unix_ns = time.time_ns()
    payload = _ack_payload(nonce=nonce, topic=topic, step=step)
    path = tmp_path / "subscription-ack-test.json"
    _write_canonical_ack(path, payload)

    loaded = _read_subscription_ack(
        path,
        nonce=nonce,
        topic=topic,
        step=step,
        started_at_unix_ns=started_at_unix_ns,
        runner_parent_process_id=101,
        platform_name="posix",
    )

    assert loaded == payload


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("nonce", "wrong"),
        ("topic", "ak.wwise.core.object.deleted"),
        ("step_name", "wrong-step"),
        ("runner_parent_process_id", 999),
        ("gateway_process_id", "202"),
        ("subscribed_at_monotonic_ns", 0),
    ),
)
def test_read_subscription_ack_rejects_wrong_identity_or_scalar_type(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    nonce = "b" * 43
    topic = "ak.wwise.core.object.created"
    step = "destructive.gateway.wait-topic"
    payload = _ack_payload(nonce=nonce, topic=topic, step=step)
    payload[field] = value
    path = tmp_path / "subscription-ack-test.json"
    _write_canonical_ack(path, payload)

    with pytest.raises(AssertionError):
        _read_subscription_ack(
            path,
            nonce=nonce,
            topic=topic,
            step=step,
            started_at_unix_ns=1,
            runner_parent_process_id=101,
            platform_name="posix",
        )


def test_read_subscription_ack_accepts_windows_venv_redirector_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_gateway_broker,
        "_windows_process_parent_map",
        lambda: {200: 100, 300: 200, 400: 300},
    )
    nonce = "c" * 43
    topic = "ak.wwise.core.object.created"
    step = "destructive.gateway.wait-topic"
    payload = _ack_payload(nonce=nonce, topic=topic, step=step)
    payload["runner_parent_process_id"] = 300
    payload["gateway_process_id"] = 400
    path = tmp_path / "subscription-ack-test.json"
    _write_canonical_ack(path, payload)

    loaded = _read_subscription_ack(
        path,
        nonce=nonce,
        topic=topic,
        step=step,
        started_at_unix_ns=1,
        runner_parent_process_id=100,
        platform_name="nt",
    )

    assert loaded == payload


def test_parse_packaged_gateway_result_accepts_one_success_object() -> None:
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "ok": True,
        "command": "wait-topic",
        "cleanup": "unsubscribed",
    }

    assert _parse_packaged_gateway_result(
        returncode=0,
        stdout="\n" + json.dumps(payload) + "\n",
        stderr="",
    ) == payload


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    (
        (0, '{}\n{}\n'),
        (0, '[]\n'),
        (0, '{"ok":false}\n'),
        (2, '{"ok":true}\n'),
    ),
)
def test_parse_packaged_gateway_result_rejects_non_unique_or_failed_terminal_output(
    returncode: int,
    stdout: str,
) -> None:
    with pytest.raises(AssertionError):
        _parse_packaged_gateway_result(
            returncode=returncode,
            stdout=stdout,
            stderr="bounded diagnostic",
        )
