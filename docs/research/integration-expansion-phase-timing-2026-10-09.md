# Expansion phase timing development record

Original #108/#122 scope, based on `8079061`. This change adds no business cases,
CLI options, runtime service, process isolation, or product behavior.

New expansion runs seal a fixed timing policy in task-plan v2 and final phase
evidence in outcome v2, outside removed owned directories. Existing v1 archives
retain their verdicts and receive no invented timing credit. The ordinary profiles
remain opt-out. Actual monotonic intervals cover prelaunch and postlaunch
preparation, launch through readiness, independent snapshot/verification callbacks
(including CPU/media work), direct reads, and lifecycle/actor cleanup. Failed
calls and source-proof errors retain elapsed evidence. Nested intervals record
parent attribution; phase totals use their union rather than double counting.

The engineering allowances are preparation 600s, oracle work 600s, cleanup 180s.
Startup records the existing effective lifecycle component bounds. Preparation
and oracle work cap existing Gateway/RPC waits by positive remaining allowance
and reject further normal work after exhaustion. Cleanup and read-only failure
reconciliation continue after exhaustion with their existing bounded ownership;
source protection is never skipped and ambiguous writes are never retried.
Agent cumulative 600s/slow 420s and reviewer 120s remain unchanged. Oracle work
inside Agent turns stays inside that established Agent wall-time measurement.

These are cooperative bounds. Synchronous filesystem/CPU work can overrun;
measured overruns remain explicit incomplete infrastructure and cannot produce
outer PASS/boundary credit. A verified task/transaction retains its original
business verdict when cleanup overruns. Telemetry alone grants no business PASS.

TDD seams were the existing fixture Gateway, lifecycle, direct actor, Broker
callback and archive verifier. Recorded REDs covered missing successful/invalid
receipt timing, absent deadline-aware setup/lifecycle/direct interfaces, callback
CPU timing, missing mandatory evidence/plan policy, and an overlarge RPC wait.
GREEN checks include fake-clock overlap and cumulative limits, before-dispatch
rejection, cleanup/source proof after exhaustion, source drift blocking, legacy
compatibility, and malformed/reordered/tampered measurements.

Focused developer verification used the locked Poetry interpreter through
`ci/test.sh --mode nonlive -- -q` with the affected runtime, task, archive,
Broker, direct actor, lifecycle, CLI wiring, reconciliation and seven adapter
files: **2593 passed**, exit 0, 17.33s. An earlier combined focused run exposed
five legacy fixture/transport compatibility failures; these were repaired before
the final run. This record grants no real-Wwise, Fresh Agent or Windows credit.
The coordinator owns combined review, the broad gate and final frozen acceptance.
