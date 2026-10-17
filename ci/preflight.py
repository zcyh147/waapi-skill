"""Run existing cheap fake-client regressions through the normal test driver."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
NODES = (
    "tests/unit/test_ci_test_bat.py::test_program_manifest_is_the_single_ordered_cross_platform_node_source",
    "tests/unit/test_operation_composer_gateway.py::test_non_object_set_operation_schema_digest_inventory_is_reviewed",
    "tests/unit/test_public_route_program_matrix.py",
    "tests/unit/test_host_ui_debug_business_adapter.py::test_tone_large_marker_request_survives_exact_terminal_delivery",
    "tests/unit/test_host_ui_debug_business_adapter.py::test_maximum_tone_marker_plan_and_count_survive_artifact_and_actual_stdout",
    "tests/unit/test_host_ui_debug_business_adapter.py::test_unowned_tone_shapes_cannot_gain_extra_terminal_capacity",
)


def main() -> int:
    if len(sys.argv) != 1:
        print("preflight takes no arguments; use ci/test.sh for other selections", file=sys.stderr)
        return 2
    return subprocess.run(
        [sys.executable, str(ROOT / "ci/test_driver.py"), "--mode", "nonlive",
         "--", *NODES, "-q", "-ra"],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
