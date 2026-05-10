from __future__ import annotations

import os
import tempfile

from wwise_waapi.headless import HeadlessLifecycle, LifecycleTimeouts, default_waapi_client_factory  # pyright: ignore[reportMissingImports]


def main() -> int:
    console_path = os.environ["WWISE_CONSOLE"]
    project_path = os.environ["WWISE_SAMPLE_PROJECT_PATH"]
    timeouts = LifecycleTimeouts(
        startup=float(os.getenv("WWISE_STARTUP_TIMEOUT", "10")),
        readiness=float(os.getenv("WWISE_READINESS_TIMEOUT", "60")),
        probe=float(os.getenv("WWISE_PROBE_TIMEOUT", "5")),
        shutdown=float(os.getenv("WWISE_SHUTDOWN_TIMEOUT", "10")),
    )

    with tempfile.TemporaryDirectory(prefix="wwise-smoke-wineprefix-") as wine_prefix:
        launch_env = dict(os.environ)
        launch_env["WINEPREFIX"] = wine_prefix
        lifecycle = HeadlessLifecycle(
            console_path=console_path,
            project_path=project_path,
            timeouts=timeouts,
            launch_env=launch_env,
        )
        client = None
        try:
            lifecycle.run_until_ready()
            client = default_waapi_client_factory(lifecycle.waapi_url)
            info = client.call("ak.wwise.core.getInfo")
            display_name = info.get("displayName") if isinstance(info, dict) else None
            version = info.get("version") if isinstance(info, dict) else None
            print(f"smoke ok: displayName={display_name!r} version={version!r}")
            return 0
        finally:
            if client is not None:
                client.disconnect()
            lifecycle.shutdown(suppress_errors=True)
            if lifecycle.cleanup_report is not None and not lifecycle.cleanup_report.is_clean:
                raise RuntimeError(f"smoke cleanup left residual processes: {lifecycle.cleanup_report.residual_processes!r}")


if __name__ == "__main__":
    raise SystemExit(main())
