# Test helper usage (`ci/test.sh`)

Use `ci/test.sh` to run project test modes with consistent environment setup. See `tests/TEST_INVENTORY.md` for the human test inventory.

## Common commands

- `ci/test.sh --mode nonlive`
- `ci/test.sh --version all --mode matrix -- -q -ra`
- `ci/test.sh --version 2021.1 --mode live -- -q -ra`
- `ci/test.sh --version 2021.1 --mode destructive -- -q -ra`
- `ci/test.sh --version all --mode smoke`

Positional form is still supported, for example `ci/test.sh 2021.1 live`.

## Strict real modes

`live`, `destructive`, `smoke`, and `matrix` are strict real modes. They set `WWISE_STRICT_REAL=1`, require an executable `WWISE_CONSOLE`, and require an existing `.wproj` at `WWISE_SAMPLE_PROJECT_PATH`. Missing WwiseConsole or SampleProject prerequisites fail before pytest execution instead of becoming soft skips.

Real launches append proof to `.sisyphus/evidence/waapi-test-remediation/real-wwise-launches.jsonl`. Check the audit with:

- `wc -l .sisyphus/evidence/waapi-test-remediation/real-wwise-launches.jsonl`
- `tail -n 4 .sisyphus/evidence/waapi-test-remediation/real-wwise-launches.jsonl`

Audit rows include the pid, port, command, sandbox project, `getInfo` version proof, `ready_duration_seconds`, and cleanup result. `ready_duration_seconds` measures WAAPI readiness, not the total foreground GUI or plugin warning lifetime.

## Extra pytest args passthrough

Append pytest args after `--`:

- `ci/test.sh --version 2024.1 --mode live -- -k object_topics -q`
- `ci/test.sh --version all --mode matrix -- --collect-only -q`

## Matrix safety note

`--mode matrix` with `--version all` runs supported versions sequentially. Do not run all versions in parallel.
