# Wwise WAAPI 2022.1 Live Coverage Matrix

This reference summarizes `resources/capabilities/2022.1/live-coverage-matrix.json`.
It is a Phase 2 planning matrix: it preserves Phase 1 inventory and fake-route evidence while separating future live/sandbox targets from achieved behavior.

## Counts

| Metric | Count |
| --- | ---: |
| Reflected functions | 112 |
| Reflected topics | 32 |
| Total reflected APIs | 144 |
| Phase 1 fake-route achieved | 27 |
| Phase 1 deferred/substitute achieved | 117 |
| Live behavior achieved today | 0 |

## Target status counts

| Target status | Count |
| --- | ---: |
| `deferred-with-substitute-test` | 2 |
| `fake-route-tested` | 8 |
| `live-candidate` | 102 |
| `skipped-approved` | 21 |
| `wrapper-only` | 11 |

## Category policy

| Policy | Categories / URIs | Notes |
| --- | --- | --- |
| `live-candidate` | `core.audio`, `core.object`, `core.profiler`, `core.profiler.captureLog`, `core.soundbank`, `core.switchContainer`, `core.transport`, `core.undo`, `soundengine`, non-excluded topics, and `ak.wwise.core.object.get` for WAQL | Requires live/sandbox fixtures and bounded assertions before promotion. |
| `wrapper-only` | `ui`, `ui.commands`, `ui.project` | UI/project-window behavior is not counted as live behavioral coverage. |
| `skipped-approved` | `cli`, `core.remote`, `debug` | User policy excludes these from Phase 2 live execution; inventory evidence remains. |
| `fake-route-tested` | Phase 1-safe APIs not otherwise targeted | Existing fake-route evidence remains valid. |
| `deferred-with-substitute-test` | Remaining non-candidates without a live policy | Deferred registry evidence remains inventory/substitute coverage only. |

## Evidence rules

- Every URI has exactly one `target_status` and exactly one `achieved_status`.
- `achieved_status` is copied from Phase 1 `api-coverage.json`; no API is promoted without new behavior evidence.
- `wrapper-only`, `skipped-approved`, and `deferred-with-substitute-test` entries must not be counted as live behavioral coverage.
- `live-candidate` entries must list fixture prerequisites before any future live test can promote them.
