# Host source-closure reconciliation

This companion repairs the P2 omitted-source review for seven selected ordinary
CODE anchors. It uses the existing `branch-evidence-index/v1`,
`branch-bindings/v1`, `branch-evidence-requirements/v1` and
`ordinary-test-run-attachment/v1` contracts. No reader or overlay protocol was
added.

The five files in `original/` are byte-identical copies from `../export-r1/original/`:
**70 passed, zero skipped, 190.22s**, clean candidate
`727187ced057643927a6f692f66d4eabe86293dd`. They are not a new test run.
`source-review.json` lists the complete runtime and selected dependency seals; the seven
`program-anchor-*.json` records enforce them through the ordinary reader's
original Git source and current source checks.

The finite Host component candidate is
`1a6bc8f75b1975f3904233e18a8d8302aa7d1586ed75e038e48b5dac462d04b8`.
It is neither the global candidate nor a sibling completion claim. Original
`export-r1` mappings remain frozen historical evidence. The settled integration
join must use current representative mappings and requirements, with these
selected bindings/anchors only where their exact source and candidate review
still applies. No stale mapping becomes current by loading this companion.

| Anchor | Mechanism | Selected route |
| --- | --- | --- |
| `program-anchor-01.json` | commands | 2021.1 Authoring `ui.captureScreen` |
| `program-anchor-02.json` | debug-read | 2023.1 Authoring `debug.getWalTree` |
| `program-anchor-03.json` | fixed-read | 2021.1 Authoring `core.getInfo` |
| `program-anchor-04.json` | lua-server | 2021.1 Authoring `cli.waapiServer` |
| `program-anchor-05.json` | project | 2021.1 Authoring `core.project.save` |
| `program-anchor-06.json` | remote | 2021.1 Authoring `core.remote.connect` |
| `program-anchor-07.json` | tone | 2023.1 Authoring `debug.generateToneWAV` |

All selected identities are their exact `/argsSchema` member. Representative
labels identify their original Host mechanism; the companion grants no sibling
or native evidence credit. The actual selected tests are sealed individually
in each anchor's `mechanism.selected_tests`.

The existing loader and reader consume this companion directly:

```python
from tests.maintenance import branch_coverage_audit as audit
from tests.support.host_completion_mapping import BASE, host_component
from tests.support.ordinary_test_run_evidence import read_ordinary_test_run

companion = audit.ROOT / BASE / 'source-repair-r1'
requirements = audit.load(companion / 'requirements.json')
bindings, base, _ = audit.portable_binding_inputs(
    companion / 'evidence-index.json', requirements)
inventory = host_component(audit.ROOT)
rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
for identity, binding in bindings['bindings'].items():
    assert read_ordinary_test_run(
        binding['evidence']['program'], rows[identity],
        inventory['native_coverage']['candidate_sha256'], 'program', 'product',
        base, binding, audit.ROOT) == ('reviewed_aggregate_code_mechanism', None)
```

The persisted-reader regression executes that same chain:

```bash
WAAPI_TEST_PYTHON=/Users/xiye/Library/Caches/pypoetry/virtualenvs/non-package-mode-nsP1lGog-py3.11/bin/python \
  ci/test.sh --mode nonlive -- -q -ra \
  tests/unit/test_host_completion_mapping.py::test_host_source_reconciliation_keeps_original_run_and_reads_seven_selected_anchors \
  --basetemp=/tmp/waapi-195-host-source-companion-review-new
```

Use a fresh basetemp for a new invocation. No Fresh, native Wwise or full gate
was run for this repair. Combined gates, candidate reconciliation and canonical
publication remain integration-owned.

The final source review seals all **202 tracked packaged Python files** below
`scripts/` and `wwise_waapi/`, plus the precise selected tests/helpers,
`pyproject.toml`, the four ordinary runner files and `ci/test_readiness.py`:
**224 relevant sources** per anchor. The finite runtime roster comes from
`git ls-files`; the producer compares it with `git ls-tree` at the original
candidate and checks every original/current byte before emission. No source
from a generated tree, cache or local virtual environment is enumerated.

This conservative closure includes parser registration in
`cli_console_business_cli.py`, manifest/schema helpers, all setter/readback
builders and canonical serialization. It deliberately invalidates reuse after
an unrelated packaged Python change. It grants no extra execution coverage.
The full lists and exact original/current seals live in `source-review.json`
and the seven standard program anchors; no reader or dependency framework changed.
