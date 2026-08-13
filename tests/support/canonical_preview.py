from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from wwise_waapi.transactions import TransactionStore, resolve_state_directory


def bind_canonical_preview_fixture(gateway: Any) -> Callable[..., tuple[int, dict[str, Any]]]:
    """Adapt historical downstream tests without restoring a product command."""

    public_execute = gateway.execute_gateway

    def execute(
        argv: Sequence[str] | None = None,
        *,
        env: Mapping[str, str] | None = None,
        client_factory: Callable[[str], Any] | None = None,
        stream_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        arguments = list(argv or ())
        command_index = next(
            (
                index
                for index, value in enumerate(arguments)
                if value in {"preview", "legacy-preview", "confirm"}
            ),
            None,
        )
        if command_index is None:
            return public_execute(
                arguments,
                env=env,
                client_factory=client_factory,
                stream_sink=stream_sink,
            )
        command = arguments[command_index]
        if command == "confirm" and "--artifact-hash" in arguments:
            transaction_id = arguments[command_index + 1]
            state_dir = _option(arguments[:command_index], "--state-dir")
            store = TransactionStore(
                resolve_state_directory(Path(state_dir) if state_dir is not None else None)
            )
            token = store.load_snapshot(transaction_id).confirmation_token
            assert token is not None
            artifact_index = arguments.index("--artifact-hash")
            translated = arguments[:artifact_index] + [
                "--confirmation-token",
                token,
            ] + arguments[artifact_index + 2 :]
            return public_execute(
                translated,
                env=env,
                client_factory=client_factory,
                stream_sink=stream_sink,
            )
        if command not in {"preview", "legacy-preview"}:
            return public_execute(
                arguments,
                env=env,
                client_factory=client_factory,
                stream_sink=stream_sink,
            )

        source_env = dict(env or {})
        request_text = _required_option(arguments, "--request-json")
        request = json.loads(request_text)
        state_dir = _option(arguments[:command_index], "--state-dir")
        version = _option(arguments[:command_index], "--version") or request.get("version")
        namespace = argparse.Namespace(
            host=_option(arguments[:command_index], "--host"),
            port=_int_option(arguments[:command_index], "--port"),
            version=version,
            timeout=_float_option(arguments[:command_index], "--timeout"),
            evidence_dir=_option(arguments[:command_index], "--evidence-dir"),
            state_dir=state_dir,
            command="canonical-preview-test-fixture",
            apply="--apply" in arguments,
            ttl=int(_option(arguments, "--ttl") or gateway.DEFAULT_PREVIEW_TTL_SECONDS),
        )
        try:
            if namespace.apply:
                gateway.require_project_modification_policy(
                    env=source_env,
                    action="requested project change",
                )
            connection = gateway.resolve_connection(namespace, env=source_env)
            factory = client_factory or gateway.default_client_factory
            transport = gateway.GatewayTransport(
                connection.url,
                factory,
                deadline=connection.deadline,
            )
            timeout = connection.deadline.require_remaining("version_detection.getInfo")
            if math.isinf(timeout):
                timeout = gateway.DEFAULT_TIMEOUT
            live_info = transport.call_with_timeout(
                gateway.GET_INFO_URI,
                timeout=timeout,
                phase="version_detection.getInfo",
            )
            detected_version = gateway.version_key_from_get_info(
                gateway.require_mapping(live_info, "getInfo response")
            )
            if connection.version_hint and connection.version_hint != detected_version:
                raise gateway.GatewayInputError(
                    f"Connected Wwise is {detected_version}, but the requested version is {connection.version_hint}"
                )
            dispatcher = gateway.WwiseDispatcher(client=transport)
            if live_info.get("isCommandLine") is False:
                dispatcher.manifest_store = gateway.AuthoringUiRuntimeManifestStore(
                    dispatcher.manifest_store
                )
            common = {
                "contract": gateway.GATEWAY_RESULT_CONTRACT,
                "command": namespace.command,
                "endpoint": {
                    "host": connection.host,
                    "port": connection.port,
                    "url": connection.url,
                },
                "detected_version": detected_version,
                "is_command_line": bool(live_info.get("isCommandLine")),
            }
            payload = gateway.create_transaction_preview(
                request,
                args=namespace,
                env=source_env,
                connection=connection,
                detected_version=detected_version,
                live_info=gateway.require_mapping(live_info, "getInfo response"),
                dispatcher=dispatcher,
                common=common,
            )
        except Exception as exc:  # noqa: BLE001 - mirror the public structured boundary
            normalized = gateway.normalize_gateway_exception(exc)
            payload = {
                "contract": gateway.GATEWAY_RESULT_CONTRACT,
                "ok": False,
                "status": "error",
                "command": namespace.command,
                "error_code": normalized["error_code"],
                "message": normalized["message"],
                "details": normalized.get("details"),
            }
        finally:
            if "transport" in locals():
                transport.close()
        payload = gateway.attach_gateway_session_context(
            payload,
            args=namespace,
            env=source_env,
        )
        return gateway.constrain_live_gateway_result(
            0 if payload.get("ok") else 2,
            payload,
        )

    return execute


def _option(arguments: Sequence[str], name: str) -> str | None:
    try:
        index = arguments.index(name)
    except ValueError:
        return None
    return arguments[index + 1]


def _required_option(arguments: Sequence[str], name: str) -> str:
    value = _option(arguments, name)
    if value is None:
        raise AssertionError(f"test fixture requires {name}")
    return value


def _int_option(arguments: Sequence[str], name: str) -> int | None:
    value = _option(arguments, name)
    return None if value is None else int(value)


def _float_option(arguments: Sequence[str], name: str) -> float | None:
    value = _option(arguments, name)
    return None if value is None else float(value)
