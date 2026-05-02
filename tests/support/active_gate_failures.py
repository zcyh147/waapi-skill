from __future__ import annotations

from collections.abc import Iterator

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.headless import (  # pyright: ignore[reportMissingImports]
    EarlyProcessExit,
    HeadlessLifecycleError,
    ReadinessTimeout,
    StartupTimeout,
)


ACTIVE_RUNTIME_FAILURES = (StartupTimeout, ReadinessTimeout, EarlyProcessExit, HeadlessLifecycleError)


def fail_if_active_runtime_failure(exc: BaseException, context: str) -> None:
    runtime_failure = active_runtime_failure(exc)
    if runtime_failure is None:
        return

    diagnostics = getattr(runtime_failure, "diagnostics", {})
    pytest.fail(
        f"{context}: active Wwise runtime failure after prerequisites passed: "
        f"{type(runtime_failure).__name__}: {runtime_failure}; diagnostics={diagnostics!r}"
    )


def skip_or_fail_unavailable(exc: BaseException, context: str | None = None) -> None:
    fail_if_active_runtime_failure(exc, context or str(exc))
    pytest.skip(str(exc))


def active_runtime_failure(exc: BaseException) -> BaseException | None:
    for candidate in _exception_chain(exc):
        if isinstance(candidate, ACTIVE_RUNTIME_FAILURES):
            return candidate
    return None


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        candidate = pending.pop(0)
        identity = id(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        yield candidate
        for linked in (candidate.__cause__, candidate.__context__):
            if linked is not None:
                pending.append(linked)
