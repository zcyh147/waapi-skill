# Specialized authoring lightweight wrapper slice (#191)

Candidate base: `a7fa66c9`. This slice applies the 2026-10-27
[lightweight wrapper acceptance successor](SPEC.md#user-approved-lightweight-wrapper-acceptance--2026-10-27)
to [local ticket 17 / live #191](tickets/17-complete-specialized-project-and-object-authoring-operations.md).
It fixes actual input restrictions and a false verification failure. It does not
claim native effect coverage or close the whole ticket.

## Implemented boundary

- Blend assignment insertion: the retained R90 Console 2024.1.13.9056 attempt
  observed the prior last assignment's Automatic right-edge positions change.
  That failed attempt remains failed; see `tests/TEST_INVENTORY.md` R90/R91.
  `blend_assignment.py` no longer promises unchanged geometry for an adjacent
  Automatic edge facing a newly inserted child. Preview discloses that scope as
  unverified, and verification returns partial observation. Modes, shapes,
  opposite edges, unrelated assignments, owner/child/track identity and indexed
  order remain checked. The full execution-time prewrite snapshot remains exact.
  This expresses uncertainty rather than predicting a native geometry formula.
- `object.setStateGroups` and `object.setStateProperties`: the public Core
  declaration now accepts explicit empty replacement through
  `--empty state_group_handles` or `--empty field_handles`, respectively.
  `request-schema` discloses the new form. Omission still fails the required
  field check; a repeated empty or mixed empty/item declaration is rejected
  atomically. Only these two operation fields admit empty collections; generic
  object/field lists keep their nonempty requirement. Supported lanes remain
  2023.1, 2024.1 and 2025.1. The setter result remains schema-only verification.
- `switchContainer.addAssignment`: a distinct child/value pair is allowed when
  that child already has another value. Both Registry and Builder restrictions
  were removed. Exact duplicates, wrong groups/parents, assignment prewrite
  drift and loss of an original pair still fail. The expected complete pair set
  and exact pair-removal contract are unchanged across 2021.1–2025.1.
- `object.pasteProperties`: both documented inclusion and exclusion lists can
  be forwarded together, through existing source-bound Field Handles. No
  precedence, set subtraction or copied-field effect is inferred. A compact
  preauthorization notice states that their combined effect is unverified;
  verification remains result-schema-only. List mode mapping and version scope
  (2022.1–2025.1) are unchanged.

The only new public flag is `--empty` on `draft-declare-core-plan`, closed to
schema-disclosed State fields. All named operations, exact reflected URIs,
object/field binding commands and other declaration flags remain the same.
No raw arguments, options, fields, WAQL or direct client escape is introduced.
Configuration binding, policies, immutable Preview, execute-once, drift checks
and bounded results retain their existing control paths.

## Pinned grounding

The following references are existing retained source/reflection, not new
research or native observations:

- `skills/waapi-skill/resources/native-catalog/{2024.1,2025.1}/wwise-console.json`,
  `schemas.ak.wwise.core.object.setStateGroups.description`: the setter sets
  associated State Groups and removes prior associations.
- The same two catalogs,
  `schemas.ak.wwise.core.object.setStateProperties.description`: the setter
  removes previous state properties, including defaults.
- The 2023.1, 2024.1 and 2025.1 catalogs: `setStateGroups.argsSchema.stateGroups`
  and `definitions.documents.waapi_definitions.json.definitions.statePropertiesArg`
  are arrays without `minItems`; no extra 2023 semantics are invented.
- The 2024.1 and 2025.1 catalogs,
  `schemas.ak.wwise.core.switchContainer.addAssignment.description`: assignment
  is equivalent to dragging the child to a state; the child is appended for
  each state. Existing five-lane
  `skills/waapi-skill/references/semantic/<version>/semantic-builder-switchcontainer.md`
  retains the corresponding assignment source notes and relationship boundary.
- All 2022.1–2025.1 catalogs,
  `schemas.ak.wwise.core.object.pasteProperties.argsSchema`: `inclusion` and
  `exclusion` are independently optional arrays. Their descriptions specify
  omitted behavior; they do not specify precedence when both are supplied.
- Existing `references/semantic/{2024.1,2025.1}/blend-assignment-source.json`
  under the Skill preserves index/edge applicability and weak reassignment
  boundaries. `tests/TEST_INVENTORY.md` R90 records changed Automatic geometry;
  R91 records the already-completed clamp/collector repairs. This slice does
  not alter that history or grant the unstarted 2025 attempt credit.

## Focused code validation

All commands used `ci/test.sh --mode nonlive --` with the locked developer
interpreter supplied as:

```text
WAAPI_TEST_PYTHON=/Users/xiye/Library/Caches/pypoetry/virtualenvs/non-package-mode-nsP1lGog-py3.11/bin/python
```

The public seam was Gateway schema discovery and the existing Draft → Preview →
confirmation → execute → verify flow with a fake external WAAPI boundary.
TDD reproduced the missing Blend scope, missing State input, Switch relationship
rejection and paste mutual-exclusion rejection before their fixes. Early test
fixture mistakes (artifact key, metadata label and 2021 Project guard response)
were repaired separately; they were not classified as product/native failures.
The original execution outputs remain in the development chat; no separate raw
pytest log files were created or retroactively reconstructed.

Successful affected selections (separate, overlapping runs; not a combined gate):

| Pytest selection after `-q` | Completed outcome |
| --- | --- |
| `test_core_business_gateway.py -k test_blend_automatic_neighbor_geometry_remains_disclosed_partial_observation` | 2 passed, 270 deselected, 1.21s |
| Same file, `-k 'test_blend_automatic_neighbor_does_not_waive_stable_or_unrelated_fields or test_blend_assignment_prewrite_snapshot_drift_never_dispatches or test_blend_assignment_existing_admitted_lanes_keep_truthful_weak_result'` | 24 passed, 252 deselected, 10.18s |
| Same file, `-k test_state_replacement_explicit_empty_is_callable_and_result_only` | 6 passed, 276 deselected, 2.68s |
| Same file, `-k 'test_state_empty_declaration_rejects_conflicts_atomically or test_core_mutation_check_rejects_bound_object_drift_before_dispatch'` | 4 passed, 281 deselected, 1.06s |
| `test_switch_assignment_business_gateway.py -k test_switch_child_accepts_an_additional_distinct_value_and_preserves_old_pair` | 4 passed and 1 fixture failure, 14 deselected, 1.63s; the 2021-only fixture failure is corrected below |
| `test_switch_assignment_business_gateway.py::test_switch_child_accepts_an_additional_distinct_value_and_preserves_old_pair[2021.1]` plus `test_semantic_builder_switchcontainer.py::test_add_and_remove_fail_closed_when_assignment_state_is_unknown_or_noop` | 2 passed, 0.58s |
| `test_switch_assignment_business_gateway.py -k test_additional_switch_pair_keeps_relationship_and_preservation_guards` | 4 passed, 19 deselected, 1.11s |
| `test_core_business_gateway.py -k test_paste_accepts_both_documented_lists_without_claiming_combined_effect` | 2 passed, 285 deselected, 1.33s |
| `test_core_business_gateway.py::test_paste_combined_selection_still_requires_source_scoped_fields`, `test_core_business_adapter.py::test_paste_convert_and_conversion_plugin_compile_business_collections`, `test_operation_registry.py::test_operation_catalog_is_truthful_about_closed_and_boundary_operations` | 3 passed, 0.74s |

Every file in the table is below `tests/unit/`. The final Switch 2021 repair was
restricted to the fake Project guard response; the other four successful
version results were retained rather than repeated.

No Wwise, Authoring, Console, reflection, Fresh, full Program or full Non-live
run was started. #195 owns the stable combined code gates and reconciliation.
Fresh remains zero. Existing native failures, quarantines, receipts and
inventories were left untouched.

## Superseded acceptance work

The old readiness packet's blanket requirement for new specialized independent
effect verifiers is superseded by the lightweight successor. Ordinary
attenuation/randomizer/State/paste/mute/solo/reset and Blend track/removal
wrappers may retain truthfully disclosed result-only verification. Blend
requested-edge effects and existing-assignment semantics were already callable
through explicitly weak lanes. Min/Max readback must not be advertised as proof
of dependent GameParameter curve/Action effects; this slice adds no such claim
and requires no new vendor QA to infer those effects.
