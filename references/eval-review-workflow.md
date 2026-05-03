# Wwise WAAPI eval review workflow

Use this workflow when you want human review of `evals/evals.json`. These evals are review aids, not release gates, and they do not replace `pytest`.

## Scope

The eval set covers six Wwise WAAPI behaviors that are easy to regress in prose answers:

1. Safe read-only object queries through the generic dispatcher.
2. WAQL generation that uses the source-grounded WAQL reference gate.
3. Bounded subscription waits with timeout and cleanup guidance.
4. Refusal for destructive calls without explicit opt-in.
5. Missing or non-starting Wwise diagnostics without committing local state.
6. Deferred API explanations that separate inventory coverage from behavioral coverage.

Additional 2021.1 eval examples are version-scoped. They must point to versioned resources such as `resources/manifest/2021.1/`, `resources/semantic/2021.1/source_notes.json`, `resources/capabilities/2021.1/`, `resources/deferred/2021.1.json`, `resources/waql/2021.1/`, and `references/semantic/2021.1/`. They must keep 2021.1 claims limited to 99 reflected functions, one live read-only URI, nine copied-sandbox mutating URIs, 43 deferred entries, 46 excluded entries, and unknown 0. They must not claim broad 2021.1 WAAPI behavioral coverage, must label NotebookLM and source notes as source-only, and must state that destructive tests require copied sandboxes under `.sisyphus/runtime/wwise-waapi-sandboxes`.

Additional 2023.1 eval examples are version-scoped. They must point to versioned resources such as `resources/manifest/2023.1/`, `resources/semantic/2023.1/source_notes.json`, `resources/capabilities/2023.1/`, and `references/semantic/2023.1/`. They must not point 2023.1 answers at the older global `references/semantic-builder-*.md` files, and they must not claim full 2023.1 WAAPI behavioral coverage.

Additional 2024.1 eval examples are version-scoped. They must point to versioned resources such as `resources/manifest/2024.1/`, `resources/semantic/2024.1/source_notes.json`, `resources/capabilities/2024.1/`, `resources/deferred/2024.1.json`, `resources/waql/2024.1/`, and `references/semantic/2024.1/`. They must keep 2024.1 claims limited to complete reflected inventory and parity classification, one live read-only URI, ten copied-sandbox mutating URIs, and remaining deferred or excluded entries. They must not claim broad 2024.1 WAAPI behavioral coverage.

Additional 2025.1 eval examples are version-scoped. They must point to versioned resources such as `resources/manifest/2025.1/`, `resources/semantic/2025.1/source_notes.json`, `resources/capabilities/2025.1/`, `resources/deferred/2025.1.json`, `resources/waql/2025.1/`, and `references/semantic/2025.1/`. They must keep 2025.1 claims limited to complete reflected inventory and parity classification for 154 functions, one live read-only URI, ten copied-sandbox mutating URIs, and 143 remaining deferred or excluded entries. They must not claim broad 2025.1 WAAPI behavioral coverage, must not count 2024 comparison metadata as 2025.1 proof, must not treat skipped live or destructive tests as proof, and must not describe macOS evidence as Windows-host validation.

## Prepare a review workspace

Create a sibling workspace for generated outputs. Keep generated model outputs out of the skill package unless a plan asks for committed evidence.

```bash
mkdir -p waapi-skill-workspace/iteration-1
```

For each eval in `evals/evals.json`, run the prompt with the `waapi-skill` skill loaded and save the response under a descriptive directory such as:

```text
waapi-skill-workspace/iteration-1/safe-object-query/with_skill/outputs/response.md
```

If you compare against a baseline, save it beside the skill run:

```text
waapi-skill-workspace/iteration-1/safe-object-query/without_skill/outputs/response.md
```

Each eval directory should include an `eval_metadata.json` copied from the eval id, prompt, and assertions so the viewer and graders can show the reviewer what to check.

## Human review viewer

Use the Skill Creator review viewer after outputs exist:

```bash
python <skill-creator-path>/eval-viewer/generate_review.py   waapi-skill-workspace/iteration-1   --skill-name "waapi-skill"
```

If a benchmark has been generated from assertion grading, include it:

```bash
python <skill-creator-path>/eval-viewer/generate_review.py   waapi-skill-workspace/iteration-1   --skill-name "waapi-skill"   --benchmark waapi-skill-workspace/iteration-1/benchmark.json
```

## Static fallback for headless environments

When a browser cannot open, generate a standalone HTML file instead:

```bash
python <skill-creator-path>/eval-viewer/generate_review.py   waapi-skill-workspace/iteration-1   --skill-name "waapi-skill"   --static waapi-skill-workspace/iteration-1/review.html
```

Open or share `review.html` with the reviewer. When the reviewer clicks Submit All Reviews, copy the downloaded `feedback.json` back into the iteration directory before revising evals or skill instructions.

## Assertions and pytest

The assertions in `evals/evals.json` are objective checks for reviewing model outputs. They are intentionally simple text checks so reviewers can understand failures quickly. They do not prove runtime behavior.

For 2021.1 prompts, treat NotebookLM and source notes as source-only evidence generation or refresh. Runtime examples should read local persisted evidence and source-note resources, not query NotebookLM while constructing builders or dispatcher requests. Keep readback helpers such as `ak.wwise.core.soundbank.getInclusions` and `ak.wwise.core.switchContainer.getAssignments` unpromoted unless a later plan changes the coverage resources.

For 2023.1 prompts, treat NotebookLM as source evidence generation or refresh only. Runtime examples should read local persisted evidence and source-note resources, not query NotebookLM while constructing builders or dispatcher requests.

For 2024.1 prompts, treat NotebookLM as source evidence generation or refresh only. Runtime examples should read local persisted evidence and source-note resources, not query NotebookLM while constructing builders or dispatcher requests. Keep readback helpers such as `ak.wwise.core.soundbank.getInclusions` and `ak.wwise.core.switchContainer.getAssignments` unpromoted unless a later plan changes the coverage resources.

For 2025.1 prompts, treat NotebookLM as source evidence generation or refresh only. Runtime examples should read local persisted evidence and source-note resources, not query NotebookLM while constructing builders or dispatcher requests. Keep 2025.1 NotebookLM caveats visible: URL candidates are not fetched proof, hierarchy naming changed to Containers/Busses/Devices/Property Container, and SoundBank size metadata needs generated SoundBanks before trust.

Keep the normal test suite as the verification source:

```bash
python -m pytest tests/unit/test_eval_metadata.py -q
python -m pytest -q
```

Do not run full model benchmarking unless a plan explicitly asks for it.
