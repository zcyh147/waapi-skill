# History selected CODE source review

This companion repairs the direct test-dependency seal for four selected CODE
anchors. It uses the existing portable evidence index, branch-bindings,
requirements and ordinary-test-run attachment contracts. There is no mapping
attachment or new reader. `export-r1/` remains the unchanged historical packet.

The component candidate is
`dcaeb1dbc567acf629e97d945020ec04eed855d3f32631de8503d82c790b73ab`.
All anchors retain the original candidate
`59daee38fa92f4ad6610a5698be464334718585c` and byte-identical original plan,
result, summary, log and exit: 56 passed, zero skipped, 47.35 seconds.

| Anchor | Mechanism | Binding |
| --- | --- | --- |
| `program-anchor-01.json` | `history195-files-v1` | `selected-01.json` |
| `program-anchor-02.json` | `history195-group-v1` | `selected-02.json` |
| `program-anchor-03.json` | `history195-history-v1` | `selected-03.json` |
| `program-anchor-04.json` | `history195-provider-v1` | `selected-04.json` |

`evidence-index.json` loads these four exact selected bindings through
`branch_coverage_audit.portable_binding_inputs`; `summary.json` records their
identities and evidence descriptors. Each program descriptor is accepted by
`ordinary_test_run_evidence.read_ordinary_test_run` at the recorded component
candidate only after original Git-source validation and current-source checks.
No per-node Gateway observation or native/provider/history effect is inferred.

Run the persisted companion through both existing readers from the repository
root (use a fresh absolute basetemp for every invocation):

```bash
WAAPI_TEST_PYTHON=/Users/xiye/Library/Caches/pypoetry/virtualenvs/non-package-mode-nsP1lGog-py3.11/bin/python \
  ci/test.sh --mode nonlive -- -q -ra \
  tests/unit/test_history_completion_mapping.py::test_history_source_review_companion_reaches_existing_portable_and_code_readers \
  --basetemp=/tmp/waapi-history195-companion-join-new
```

For a later combined candidate, retain these reviewed source dependencies and
use the existing `history_program_anchors(root, inventory, destination, run)`
producer with `run=.../history-195-r1/export-r1/original`. It returns the four
ordinary selected anchors for that exact candidate; source drift rejects before
emission. Join those anchors through the existing combined mapping consumer.
This companion makes no combined/global completion claim and does not re-export
the roughly 106 MiB historical mapping packet.
