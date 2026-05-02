# Test helper usage (`ci/test.sh`)

Use `ci/test.sh` to run the project test modes with consistent environment setup.

## Common commands

- `ci/test.sh --mode nonlive`
- `ci/test.sh --version 2021.1 --mode live`
- `ci/test.sh --version 2025.1 --mode destructive`
- `ci/test.sh --version all --mode smoke`
- `ci/test.sh --version all --mode matrix`

Positional form is still supported (for example: `ci/test.sh 2021.1 live`).

## Extra pytest args passthrough

Append pytest args after `--`:

- `ci/test.sh --version 2024.1 --mode live -- -k object_topics -q`
- `ci/test.sh 2022.1 smoke -- -q`

## Matrix safety note

`--mode matrix` with `--version all` runs supported versions **sequentially**. Do not run all versions in parallel.
