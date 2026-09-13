# Cross-object-family CRUD regressions — 2026-09-14

Baseline: `44d2420` (README-only successor to merged `main@416bfc5`).
Work branch: `codex/crud-object-family-regressions`.

## Agreed scope

The user approved public Gateway query and Draft → immutable Preview →
confirmation → execution → verification tests against disposable WwiseConsole
projects. This is not a Fresh Agent campaign, UI interaction check, listening
test, or implementation of full Playlist/Transition authoring. The original
five SampleProjects and the user's demonstration Authoring project are not
modified. Only the disposable Voice fixture gains a second language before
Wwise starts; adding a language is fixture preparation, not WAAPI coverage.

The intended partitions are localized Voice media, ordinary CRUD in non-Sound
hierarchies, non-intrinsic identity and prohibited operations, and owned-list
membership/reference preservation. Simple API routes retain their existing
program regressions rather than acquiring redundant Agent cases.

## Confirmed defects and repair direction

### Bus/AuxBus creation parents

The 2025 public declaration rejected a valid Bus parent with
`INVALID_CREATE_PARENT_TYPE`. Shared parent/child capabilities omitted Bus and
AuxBus. The repair gives each a restricted Bus/AuxBus child allowlist; it does
not make them arbitrary child containers. The independent State→StateGroup and
Switch→SwitchGroup requirements remain, while WorkUnit→Bus/AuxBus stays valid.
The new public-Gateway file reproduced the gap and then passed 126 program
cases. Cross-version real evidence is recorded below when complete.

### Localized Voice re-import

The tracer imports English and Japanese under one Sound Voice using the same
source filename, then re-imports each language with different bytes. It checks
Sound/source GUID stability, exact language membership, no duplicate sources,
and both copied Originals hashes. The first fixture mistake treated the
language relationship as a string; it was corrected without product changes.

On 2025, the old typed Sound-leaf re-import produced an extra same-language
source and omitted a source row from its native result. Relaxing result-row
cardinality alone therefore was not an acceptable fix: independent child
readback caught the unwanted object. Explicit same-name source paths also
failed to distinguish language siblings. Untyped Sound paths did not reliably
perform the import. These exploratory failures are not passing evidence.

The working 2025 repair resolves a source by exact parent GUID, filename/path,
and language in a bounded child scan, and supplies its GUID as the import
location. Source snapshots are compared again before execution. Native
version-specific construction and verification must be proven independently
in the older lanes; the 2025 result is not extrapolated to them.

Development probes subsequently established the old typed Sound Voice wire
shape on 2021–2024, and the exact-source GUID location on 2025. The compiler
now keeps that version split. Post-execution source snapshots also reject new
duplicate sources, missing siblings, or changed other-language identities;
fifteen injected collateral failures reproduced a verification gap before this
additional check and passed after repair. Ordinary SFX has not acquired a
missing-source-result exception.

### State/Switch creation versus movement

The graph compiler incorrectly translated StateGroup→State and
SwitchGroup→Switch into implicit `States`/`Switches` lists. Those projections
are not valid on the observed Groups. Removing this invented list mapping
restores ordinary `parent/type` creation and `children` bulk construction while
retaining the existing Group constraints. Eighteen public Gateway tracers
failed before the repair and passed afterward.

Creation permission is not movement permission. Matching Console probes show
State/Switch cross-Group moves succeeding on 2021/2022 and being rejected by
the native API on 2023/2024/2025. The Gateway now refuses only that latter
version/type/operation combination before Preview. Copy and same-parent
behavior remain unchanged. This is an observed five-version engine boundary,
not a claim that the SDK explicitly documents that restriction. Real tracers
retain positive old-version moves and newer-version refusal-plus-rename checks.

Source-guidance context: installed 2025.1.7 SDK, `WwiseSDK-Windows_01.pdf`,
physical pages 767–768, shows two languages with distinct explicit source
names. `WwiseHelp_en_01.pdf`, pages 159–160, explains import destination and
empty Object Path name derivation. These examples are not proof that an empty
path plus a source GUID works on every version; only the sandbox outcomes can
establish that behavior.

## Coverage boundaries

- Exact identity tests cover existing Action, MusicStinger, MusicPlaylistItem
  and RTPC, not every possible Wwise class or plugin.
- Stinger Trigger mutation on 2023–2025 checks that Segment is preserved;
  2021/2022 live metadata does not expose these references, so those lanes
  check explicit zero-match refusal and unchanged identity without a mutation.
  No new Stinger creation or playback claim follows. The initial `6af6c90`
  2021 run retained 12 PASS / 1 FAIL because the test incorrectly assumed the
  newer reference surface. The correction changes only the test and keeps the
  Gateway's existing fail-closed discovery behavior.
- Effect tests compare old slot GUIDs and effect references after append.
  They do not infer audible processing order from an arbitrary query order.
- Generic list clearing is a fake-WAAPI full Gateway regression. A returned
  empty list cannot hide still-existing removed member GUIDs. This does not
  prove every native list supports mutation.
- Unsupported-version refusals, fixture save transactions, generated metadata
  inventories and successful API schemas are distinct from verified business
  changes. Final results must retain those distinctions.

## Final validation

Frozen candidate `b2c7afb` completed the selected public-Gateway Console tests
on macOS, one version at a time: **13 passed / 31 deselected per version** on
2021.1.14.8108, 2022.1.19.8584, 2023.1.19.8928, 2024.1.13.9056 and
2025.1.7.9143. All five pytest processes exited zero: **65 selected nodes
passed**, including explicit unsupported-version and prohibited-operation
boundaries, not 65 successful mutation capabilities.

The 20 final module evidence records in
`.waapi-skill-state/evidence/full-typed-input/macos-category-evidence.jsonl`
seal that candidate. Verified transaction counts are respectively
**28 / 31 / 30 / 30 / 30**. Four additional 2021 fixture-save transactions are
only `result_schema_checked`, not business verification. Every source full
hash, project mtime and tree-metadata digest is unchanged; all 20 passing
sandboxes were deleted and all scoped residual-process lists are empty.

The first full Program run at `b2c7afb` returned **5762 passed, 4 failed,
2 skipped**. The failures were old schema snapshots/digests: new Bus/AuxBus
child pairs in create/set and the versioned localized-Voice constraint.
Removing exactly those reviewed additions from the in-memory contracts
reproduced the old golden digests. Updated expectations then passed all four
failed nodes, with no runtime change. The earlier failed run is retained
rather than relabeled.

Final **Program at `e19fff1`: 5766 passed, 2 skipped**, exit zero (253.56 s).
Both skips require native Windows. Its first full Non-live run returned
**11346 passed, 1 failed, 116 skipped, 27 deselected**. The sole failure was
the old Program manifest count (190 instead of 195). Updating that test and
explicitly asserting inclusion of the four new cross-family files passed the
whole CI-driver test file: **42 passed, 11 native-Windows-only skips**.

Final **Non-live at `b10b95e`: 11347 passed, 116 skipped, 27 deselected**,
exit zero (740.34 s). This is a complete, zero-failure rerun. The packaged
Skill and real-test files are byte-identical between `b2c7afb`, `e19fff1`
and `b10b95e`; only reviewed test expectations and this report changed.

The real command selected the existing Voice node plus the three new modules:

```bash
for version in 2021.1 2022.1 2023.1 2024.1 2025.1; do
  ci/test.sh --version "$version" --mode destructive -- \
    tests/destructive/test_cross_family_lifecycle.py \
    tests/destructive/test_cross_family_derived_identity.py \
    tests/destructive/test_cross_family_effects.py \
    -q -ra -k 'cross_family or test_voice_languages_reimport' --tb=short \
    || exit $?
done
```

The ordinary gates were `ci/test.sh --mode program -- -q -ra` and
`ci/test.sh --mode nonlive -- -q -ra`. All gates were run directly with
their actual exit statuses, without a status-masking pipeline. Independent
read-only subagent checks found no blocking issue in the localized-source
guard/verifier or the Bus/Game Sync relationship changes.

After adding the dated inventory entry, its focused documentation gate first
reported 22 passed / 1 failed because the entry did not use the required
`Full Non-live:` label. Correcting that label (without changing counts or
test expectations) produced **23 passed**. The evidence-only successor does
not alter the tested runtime or test implementation.

No native-Windows run or Fresh Agent campaign was performed for this repair.
