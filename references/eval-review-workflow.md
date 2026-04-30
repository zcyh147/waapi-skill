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

## Prepare a review workspace

Create a sibling workspace for generated outputs. Keep generated model outputs out of the skill package unless a plan asks for committed evidence.

```bash
mkdir -p wwise-waapi-workspace/iteration-1
```

For each eval in `evals/evals.json`, run the prompt with the `wwise-waapi` skill loaded and save the response under a descriptive directory such as:

```text
wwise-waapi-workspace/iteration-1/safe-object-query/with_skill/outputs/response.md
```

If you compare against a baseline, save it beside the skill run:

```text
wwise-waapi-workspace/iteration-1/safe-object-query/without_skill/outputs/response.md
```

Each eval directory should include an `eval_metadata.json` copied from the eval id, prompt, and assertions so the viewer and graders can show the reviewer what to check.

## Human review viewer

Use the Skill Creator review viewer after outputs exist:

```bash
python <skill-creator-path>/eval-viewer/generate_review.py   wwise-waapi-workspace/iteration-1   --skill-name "wwise-waapi"
```

If a benchmark has been generated from assertion grading, include it:

```bash
python <skill-creator-path>/eval-viewer/generate_review.py   wwise-waapi-workspace/iteration-1   --skill-name "wwise-waapi"   --benchmark wwise-waapi-workspace/iteration-1/benchmark.json
```

## Static fallback for headless environments

When a browser cannot open, generate a standalone HTML file instead:

```bash
python <skill-creator-path>/eval-viewer/generate_review.py   wwise-waapi-workspace/iteration-1   --skill-name "wwise-waapi"   --static wwise-waapi-workspace/iteration-1/review.html
```

Open or share `review.html` with the reviewer. When the reviewer clicks Submit All Reviews, copy the downloaded `feedback.json` back into the iteration directory before revising evals or skill instructions.

## Assertions and pytest

The assertions in `evals/evals.json` are objective checks for reviewing model outputs. They are intentionally simple text checks so reviewers can understand failures quickly. They do not prove runtime behavior.

Keep the normal test suite as the verification source:

```bash
python -m pytest tests/unit/test_eval_metadata.py -q
python -m pytest -q
```

Do not run full model benchmarking unless a plan explicitly asks for it.
