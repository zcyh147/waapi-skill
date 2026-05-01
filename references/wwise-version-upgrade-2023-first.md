# Wwise Version Upgrade Planning Reference, 2023 First

This reference preserves the user context for future Prometheus planning. It is planning context only. It does not mean 2023.1 support is implemented.

## Version order decision

Do the Wwise version upgrades sequentially:

1. 2023 first
2. 2024 next
3. 2025 last

Start with 2023 because WAAPI likely changed around the 2023 and 2024 boundary, while 2025 is expected to contain larger changes. Serial work keeps AI focus tighter, makes diffs easier to review, and isolates version-specific failures before carrying patterns forward to 2024 and 2025.

Use the current 2022.1 semantic builder implementation as the template. Do not rewrite the builder system from scratch.

## Environment paths and tools

2023 WwiseConsole path:

```text
/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh
```

WwiseConsole usage syntax:

```text
/Path/to/Authoring/Wwise.app/Contents/Tools/WwiseConsole.sh operation [arguments] [--option1 [parameters]] [--option2 [parameters]]
```

2023 SampleProject path:

```text
/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj
```

NotebookLM notebook id:

```text
wwise-2023.1-docs
```

The NotebookLM notebook is configured and active. Later tasks can query it directly through the NotebookLM skill. Use NotebookLM for source evidence generation and refresh, not as semantic builder runtime behavior.

## Versioned references and resources

Existing 2022.1 reference files are mostly global names, such as `references/semantic-builder-*.md`, and currently serve the 2022.1 implementation. References are not yet systematically versioned, so the 2023 work should introduce a versioned reference, source-note, and evidence layout instead of modifying the 2022.1 files in place.

Suggested 2023.1 paths:

```text
references/semantic/2023.1/
resources/manifest/2023.1/
resources/semantic/2023.1/source_notes.json
resources/coverage/2023.1/
resources/waql/2023.1/
resources/deferred/2023.1.json
tests/_org/2023.1/
```

Tests, resources, fixtures, live evidence, and destructive evidence need version separation so 2023.1 validation does not overwrite or blur 2022.1 proof.

## Sample project fixture guidance

Copy the 2023 SampleProject into `tests/_org/2023.1/` and modify only that copied fixture when a source project fixture is needed.

Live and destructive tests must copy fixtures to a sandbox before mutation. Destructive tests must copy into the sandbox root before mutation and must never mutate the `tests/_org/2023.1/` source fixture or installed Audiokinetic project under `/Applications/Audiokinetic/...` directly.

## Semantic builder scope

Included semantic builder families for 2023.1 planning:

- query
- object-mutation
- property-reference
- import
- soundbank
- switchcontainer

Excluded unless a new plan explicitly adds them:

- profiler
- transport
- soundengine
- UI
- CLI
- remote
- debug

## Suggested 2023.1 verification commands

Default Wwise-free tests:

```sh
python -m pytest -q
```

Live 2023.1 tests, read-only or sandbox-safe only:

```sh
WWISE_VERSION=2023.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" WWISE_LIVE=1 python -m pytest tests/live -q
```

Destructive 2023.1 tests, sandbox copy required before mutation:

```sh
WWISE_VERSION=2023.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 python -m pytest tests/destructive -q
```

Use the installed SampleProject path only as the immutable source for copying. Destructive testing should copy from `WWISE_SAMPLE_PROJECT_PATH` into `WWISE_SANDBOX_ROOT` before mutation; it must never mutate the installed `/Applications/Audiokinetic/...` project or the `tests/_org/2023.1/` source fixture directly.
