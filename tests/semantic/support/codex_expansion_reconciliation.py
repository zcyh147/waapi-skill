"""Bounded failure reconciliation for expansion's fixed snapshot recipes only.

Native reads run in a disposable spawn child; the parent's snapshot never calls
an actor from a timeout thread. Parent CPU/media work retains the case's fixed
ceilings and checks the shared deadline between reads. This does not claim hard
cancellation of arbitrary Python. No Agent receives this guard or IPC channel.
"""

from __future__ import annotations

import json
import multiprocessing
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError
from tests.semantic.support.codex_expansion_oracle_reads import expansion_oracle_reader
from tests.semantic.support.codex_expansion_policy import canonical_digest
from tests.semantic.support.codex_harness import kill_process_group, subprocess_process_group_options


_MAX_BYTES = 131_072


class ReconciliationCleanupError(CaseBoundaryError):
    """An owned reconciliation subprocess could not prove termination/reap."""


def run_owned_gateway(command: Sequence[str], *, environment: Mapping[str, str],
                      timeout_seconds: float, cwd: Path | None = None,
                      text: bool = True) -> subprocess.CompletedProcess:
    text_options = {"encoding": "utf-8", "errors": "strict"} if text else {}
    process = subprocess.Popen(command, env=dict(environment), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        **text_options, **subprocess_process_group_options())
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except BaseException:
        # run.py owns a gateway.py child; killing only the launcher is unsafe.
        try:
            kill_process_group(process)
            process.communicate(timeout=2)
            if process.poll() is None:
                raise RuntimeError("Gateway launcher did not reap")
        except Exception as exc:
            raise ReconciliationCleanupError(f"Gateway process-group reap failed: {type(exc).__name__}: {exc}") from exc
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _reconciliation_worker(host: str, port: int, version: str, channel: socket.socket) -> None:
    from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall
    direct = None
    try:
        direct = OwnedDirectWaapiCall(host=host, port=port)
        read = expansion_oracle_reader(version=version, read_call=direct)
        with channel.makefile("rb") as stream:
            while line := stream.readline(8193):
                try:
                    if len(line) > 8192 or not line.endswith(b"\n"):
                        raise CaseBoundaryError("reconciliation request exceeds its fixed ceiling")
                    request = json.loads(line)
                    rows = read(request["view"], request["ids"])
                    response = {"ok": True, "rows": rows}
                except Exception as exc:
                    response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:2048]}
                wire = json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
                if len(wire) > _MAX_BYTES:
                    wire = b'{"ok":false,"error":"oracle response exceeds byte ceiling"}\n'
                channel.sendall(wire)
    finally:
        if direct is not None:
            direct.close(wait_seconds=0.5)
        channel.close()


class ExpansionReconciliationGuard:
    """One deadline shared by the fixed oracle, Gateway reads, and child reap."""

    def __init__(self, *, version: str, host: str, port: int,
                 trusted_read: Callable, gateway: Callable,
                 seconds: float = 30, read_seconds: float = 10) -> None:
        if (host not in {"127.0.0.1", "localhost", "::1"} or type(port) is not int or not 1 <= port <= 65535
                or not 0 < read_seconds <= 10 or not 0 < seconds <= 30):
            raise ValueError("reconciliation needs a fixed loopback endpoint and bounded deadlines")
        self.version, self.host, self.port = version, host, port
        self.seconds, self.read_seconds = seconds, read_seconds
        self._trusted_read, self._gateway = trusted_read, gateway
        # Validate the fixed view/selector contract before spawning or sending.
        self._validate = expansion_oracle_reader(version=version, read_call=lambda _uri, args, _options:
            {"return": [{"id": identifier} for identifier in args["from"]["id"]]})
        self._deadline: float | None = None
        self._process = None
        self._channel: socket.socket | None = None

    def _remaining(self) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("fixed reconciliation deadline expired")
        return min(self.read_seconds, remaining)

    def gateway(self, argv: Sequence[str]) -> Mapping[str, Any]:
        if self._deadline is None:
            return self._gateway(argv)
        if not argv or argv[0] not in {"query-object", "metadata"}:
            raise CaseBoundaryError("reconciliation admits only fixed snapshot read commands")
        result = self._gateway(argv, timeout_seconds=self._remaining())
        self._remaining()
        return result

    def trusted_read(self, view: str, ids: Sequence[str]):
        if self._deadline is None:
            return self._trusted_read(view, ids)
        self._validate(view, ids)
        self._remaining()
        if self._process is None:
            parent, child = socket.socketpair()
            self._channel = parent
            self._process = multiprocessing.get_context("spawn").Process(
                target=_reconciliation_worker, args=(self.host, self.port, self.version, child), daemon=True)
            try:
                self._process.start()
            finally:
                child.close()
        channel = self._channel
        read_deadline = min(self._deadline, time.monotonic() + self.read_seconds)
        channel.settimeout(self._remaining())
        channel.sendall(json.dumps({"view": view, "ids": list(ids)}).encode("utf-8") + b"\n")
        wire = bytearray()
        while not wire.endswith(b"\n"):
            remaining = min(read_deadline, self._deadline) - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("reconciliation oracle read timed out")
            channel.settimeout(remaining)
            chunk = channel.recv(min(8192, _MAX_BYTES + 1 - len(wire)))
            if not chunk:
                raise CaseBoundaryError("reconciliation child exited without a complete reply")
            wire.extend(chunk)
            if len(wire) > _MAX_BYTES:
                raise CaseBoundaryError("reconciliation reply exceeded its byte ceiling")
        response = json.loads(wire)
        if response.get("ok") is not True:
            raise CaseBoundaryError(str(response.get("error", "reconciliation read failed")))
        self._remaining()
        return expansion_oracle_reader(version=self.version, read_call=lambda *_:
            {"return": response.get("rows")})(view, ids)

    def reconcile(self, snapshot: Callable[[], Mapping[str, Any]]) -> Mapping[str, Any]:
        if self._deadline is not None:
            raise CaseBoundaryError("reconciliation cannot overlap")
        cleanup_failed = False
        started = time.monotonic()
        self._deadline = started + self.seconds
        receipt: dict[str, Any] = {"status": "error", "seconds": self.seconds, "read_seconds": self.read_seconds}
        try:
            self._remaining()
            result = snapshot()
            self._remaining()
            if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > _MAX_BYTES:
                raise CaseBoundaryError("reconciliation snapshot exceeds its byte ceiling")
            receipt.update(status="completed", snapshot=result, snapshot_sha256=canonical_digest(result))
        except Exception as exc:
            cleanup_failed = isinstance(exc, ReconciliationCleanupError)
            receipt["error"] = {"type": type(exc).__name__, "message": str(exc).encode("utf-8")[:2048].decode("utf-8", "ignore")}
        finally:
            if self._channel is not None:
                self._channel.close()
            process = self._process
            if process is not None and process.pid is not None:
                process.join(timeout=0.5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
                receipt["child_reaped"] = not process.is_alive()
                if receipt["child_reaped"]:
                    process.close()
            else:
                receipt["child_reaped"] = True
                if process is not None:
                    process.close()
            receipt["subprocesses_reaped"] = not cleanup_failed
            receipt["elapsed_seconds"] = time.monotonic() - started
            self._deadline, self._process, self._channel = None, None, None
        return receipt
