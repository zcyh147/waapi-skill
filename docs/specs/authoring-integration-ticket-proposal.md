# Integration Test Expansion: Approved Task Breakdown

Approved and published on 2026-09-28. Implementation and tests have not been started.

Design numbers below map to GitHub issues; they are not GitHub issue numbers. The completed audit is not duplicated as another generic research ticket.

## 01 — Close public-entrypoint coverage gaps for object creation

**Issue:** [109](https://github.com/zcyh147/waapi-skill/issues/109)

**What it delivers:** Verify conflict policies and replacement owners from public Business Declarations through Preview, and verify millisecond conversion for Action timing during creation.

**Blocked by:**

None — can start independently once implementation is scheduled.

- [ ] Reuse existing lower-level replacement and timing tests; add only missing public-entrypoint positives and necessary negatives, such as a missing replacement owner.
- [ ] Check canonical results and side-effect-free Preview behavior for every applicable version.
- [ ] Track any runtime bug as a separate repair; avoid unrelated refactoring.

## 02 — Close public-entrypoint coverage gaps for edits and imports

**Issue:** [110](https://github.com/zcyh147/waapi-skill/issues/110)

**What it delivers:** Add precise public-entrypoint assertions for object.set global settings, file-based media input, imported source notes, and Originals subdirectories.

**Blocked by:**

None — can start independently once implementation is scheduled.

- [ ] Parameterize existing media tests to cover both public file and inline input paths.
- [ ] Verify global conflict, list, and source-control settings; per-object assertions do not substitute for global-setting coverage.
- [ ] Deduplicate existing notes and directory coverage before adding assertions; parameter mapping does not prove real source-control provider behavior.

## 03 — Deliver music import as the first complete path in the new acceptance profile

**Issue:** [111](https://github.com/zcyh147/waapi-skill/issues/111)

**What it delivers:** Deliver M01 end to end: an isolated SampleProject copy, a Chinese-language request, allow-mode authorization, and independent verification of music media, hierarchy, and Track properties through the existing formal harness.

**Blocked by:**

None — can start independently once implementation is scheduled.

- [ ] Support explicitly frozen GPT-6 model settings in the new profile while preserving the meaning of old Terra profiles and historical evidence.
- [ ] Define the same business case for 2022.1 and 2025.1, adapting structure and preferring existing assets.
- [ ] Independently verify outcomes and preservation requirements. Accept valid irrelevant-order differences and reject omissions, duplicates, and wrong values; keep live and archive grading consistent.
- [ ] Separate cumulative case-level Agent time, the seven-minute slow flag, and the initial ten-minute cap from startup and cleanup timing.
- [ ] First validate with program tests and necessary isolated Gateway checks. Leave formal model comparison to the dedicated pilot issue; do not silently expand Fresh execution here.

## 04 — Verify multilingual updates and the confirmation workflow

**Issue:** [112](https://github.com/zcyh147/waapi-skill/issues/112)

**What it delivers:** Deliver C01 in ask_before_changes mode: update only the requested language while preserving the other language, Sound identity, routing, and Event Target.

**Blocked by:**

- #111 — Deliver music import as the first complete path in the new acceptance profile

- [ ] Use actual project languages and existing assets, with exact media hashes sealed before and checked after the change.
- [ ] Make no project change during Preview; a later user confirmation must bind only the current preview.
- [ ] Use the same business request and permission mode in 2022.1 and 2025.1, with an independent outcome oracle.

## 05 — Verify existing RTPC updates and preservation

**Issue:** [113](https://github.com/zcyh147/waapi-skill/issues/113)

**What it delivers:** Deliver C06 in allow_changes mode: update an existing curve while preserving its GUID and the other RTPC relationships and values.

**Blocked by:**

- #111 — Deliver music import as the first complete path in the new acceptance profile

- [ ] Seed a genuinely matching relationship so that the case exercises update rather than creation.
- [ ] Check the complete point sequence, updated identity, and untouched relationships separately.
- [ ] Provide the same business definition and independent verification in 2022.1 and 2025.1.

## 06 — Run the GPT-6 model-selection pilot

**Issue:** [114](https://github.com/zcyh147/waapi-skill/issues/114)

**What it delivers:** Compare Luna high and Sol medium on the same frozen candidate and host, and recommend the formal model and reasoning effort.

**Blocked by:**

- #111 — Deliver music import as the first complete path in the new acceptance profile
- #112 — Verify multilingual updates and the confirmation workflow
- #113 — Verify existing RTPC updates and preservation

- [ ] Start with three 2025.1 cases and two model configurations, totaling six tasks; use an independent project copy and Fresh context for every attempt.
- [ ] Report business outcomes, preservation, safety, first-attempt completion, elapsed time, and tokens separately, using the same service tier.
- [ ] Add three Luna medium attempts only after Luna high performs reliably. State evidence limitations; three successes do not prove a long-term success rate.
- [ ] Confirm and freeze the selected effort and revised timeout settings afterward; do not switch models mid-run to conceal a failure.

## 07 — Verify exact matching of same-named media

**Issue:** [115](https://github.com/zcyh147/waapi-skill/issues/115)

**What it delivers:** Deliver C03 in ask_before_changes mode: update the correct objects from same-named files in two different directories while protecting similarly named objects.

**Blocked by:**

- #111 — Deliver music import as the first complete path in the new acceptance profile

- [ ] Match each target to the intended input hash, preserve GUIDs, and create no extra copies.
- [ ] Ensure the public Import Batch can represent both directories; when declarations require multiple chunks, let the Gateway compile them and verify the combined result.
- [ ] If the business operation requires separate transactions, update the confirmation-turn budget first; never bypass the interface to preserve an estimated count.
- [ ] Use the same request and mode in 2022.1 and 2025.1.

## 08 — Verify attenuation-curve configuration

**Issue:** [116](https://github.com/zcyh147/waapi-skill/issues/116)

**What it delivers:** Deliver C08 in allow_changes mode: edit the selected attenuation curve, independently read back its complete configuration, and preserve other curves.

**Blocked by:**

- #111 — Deliver music import as the first complete path in the new acceptance profile

- [ ] Verify the curve source, control points, and values rather than only the result schema.
- [ ] Use the same business goal in 2022.1 and 2025.1; do not use listening or perceived sound as assertions.

## 09 — Verify effect appending across version-specific structures

**Issue:** [117](https://github.com/zcyh147/waapi-skill/issues/117)

**What it delivers:** Deliver C09 in allow_changes mode: append an installed effect while preserving existing slot and plug-in bindings.

**Blocked by:**

- #111 — Deliver music import as the first complete path in the new acceptance profile

- [ ] Verify fixed slots in 2022.1 and EffectSlot objects in 2025.1 separately.
- [ ] Do not promise arbitrary insertion or reordering; classify a missing plug-in as an environment prerequisite.
- [ ] Use an independent oracle to compare the complete new and existing item sets and relevant properties.

## 10 — Verify reference maintenance for an existing Stinger

**Issue:** [118](https://github.com/zcyh147/waapi-skill/issues/118)

**What it delivers:** Deliver M05 in allow_changes mode: change an existing Trigger reference while preserving the Segment, and explicitly report versions that cannot perform the operation.

**Blocked by:**

- #111 — Deliver music import as the first complete path in the new acceptance profile

- [ ] Verify the actual change and preservation requirements in 2025.1.
- [ ] Determine 2022.1 availability from live metadata. If the field is not exposed, do not guess or mutate, and do not count the boundary as business success.
- [ ] Do not expand this case into Stinger creation or playback validation.

## 11 — Investigate Playlist authoring and independent verification

**Issue:** [119](https://github.com/zcyh147/waapi-skill/issues/119)

**What it delivers:** Establish whether public interfaces can author and read back entries, ordering, and loops in 2022.1 and 2025.1, and define the smallest evidence-backed implementation scope.

**Blocked by:**

None — can start independently once implementation is scheduled.

- [ ] Inspect current contracts, code, and existing projects first. Any necessary real probe must use an isolated SampleProject copy and the public Gateway.
- [ ] Define verification for the complete entry graph, order, loops, and preservation requirements; an empty container is not a completed arrangement.
- [ ] Distinguish existing capability, missing oracle, missing Gateway functionality, and upstream boundaries; draft one natural-language allow-mode acceptance case.
- [ ] If functionality must be added, submit its concrete scope and dependencies for confirmation; this investigation does not implicitly include all implementation.

## 12 — Investigate Transition configuration and independent verification

**Issue:** [120](https://github.com/zcyh147/waapi-skill/issues/120)

**What it delivers:** Define public maintenance and independent readback for an existing Transition rule's source, destination, exit timing, and fades in both versions.

**Blocked by:**

None — can start independently once implementation is scheduled.

- [ ] Resolve field ambiguity with actual metadata rather than guessed native enums.
- [ ] Change the target rule while preserving other rules; verify configuration, not playback timing.
- [ ] Document the four capability outcomes and follow-up scope, and draft an allow-mode case; obtain separate agreement for missing functionality.

## 13 — Investigate Music Switch paths across multiple condition groups

**Issue:** [121](https://github.com/zcyh147/waapi-skill/issues/121)

**What it delivers:** Establish how public interfaces can maintain and fully read back condition groups and target paths in both versions, and propose the smallest implementation scope.

**Blocked by:**

None — can start independently once implementation is scheduled.

- [ ] Do not substitute ordinary Switch assignments for Music Switch paths.
- [ ] Check the 2025 wrapper-structure differences and define the exact mapping set and preservation requirements.
- [ ] Draft an allow-mode case. Support any inability to complete it with evidence rather than treating object existence as success.

## 14 — Freeze the campaign and complete macOS acceptance

**Issue:** [122](https://github.com/zcyh147/waapi-skill/issues/122)

**What it delivers:** Run the final explicit selection on macOS with Wwise 2022.1 and 2025.1 using the agreed batch-and-repair workflow, and publish an accurate acceptance report.

**Blocked by:**

- #109 — Close public-entrypoint coverage gaps for object creation
- #110 — Close public-entrypoint coverage gaps for edits and imports
- #111 — Deliver music import as the first complete path in the new acceptance profile
- #112 — Verify multilingual updates and the confirmation workflow
- #113 — Verify existing RTPC updates and preservation
- #114 — Run the GPT-6 model-selection pilot
- #115 — Verify exact matching of same-named media
- #116 — Verify attenuation-curve configuration
- #117 — Verify effect appending across version-specific structures
- #118 — Verify reference maintenance for an existing Stinger
- #119 — Investigate Playlist authoring and independent verification
- #120 — Investigate Transition configuration and independent verification
- #121 — Investigate Music Switch paths across multiple condition groups

- [ ] Record the final disposition of all seven initial cases and all three priority music investigations; list conditional cases and version boundaries separately rather than silently removing them.
- [ ] Freeze the model, reasoning effort, service tier, versions, permission modes, project baselines, oracles, and timeout settings.
- [ ] Finish the initial full pass while collecting ordinary successes and failures, then consolidate repairs. Rerun failed cases first; after they all pass, run the full selection again.
- [ ] Stop early for systemic source-project, evidence, or cleanup faults; do not retry indeterminate mutations.
- [ ] Base final acceptance on a complete run of one candidate; do not combine different candidates or rewrite initial FAIL records.
- [ ] Report business PASS, version boundaries, environment blocks, model/Skill/grader failures, and slow cases separately.

## Dependency rationale

Task 03 establishes the first complete business path rather than building an entire infrastructure layer in isolation. Tasks 04, 05, and 07–10 reuse its profile conventions but do not block one another. Tasks 01 and 02 and the three music investigations can begin independently once implementation is scheduled. Task 06 gates formal model selection and final execution, not preparation of other cases.

Tasks 11–13 are bounded capability investigations. Define any necessary functionality after discovering the actual gaps, obtain scope agreement, and add the corresponding implementation tickets and dependencies to task 14. Do not conceal new feature development inside a research ticket.

The user approved this breakdown. The child issues and native parent/dependency relationships have been published and verified. No implementation or test execution has been dispatched.

## GitHub index

Parent specification: [#108](https://github.com/zcyh147/waapi-skill/issues/108).

| Design ID | GitHub issue | Blocked by |
| --- | --- | --- |
| 01 | [#109 Close public-entrypoint coverage gaps for object creation](https://github.com/zcyh147/waapi-skill/issues/109) | None |
| 02 | [#110 Close public-entrypoint coverage gaps for edits and imports](https://github.com/zcyh147/waapi-skill/issues/110) | None |
| 03 | [#111 Deliver music import as the first complete path in the new acceptance profile](https://github.com/zcyh147/waapi-skill/issues/111) | None |
| 04 | [#112 Verify multilingual updates and the confirmation workflow](https://github.com/zcyh147/waapi-skill/issues/112) | #111 |
| 05 | [#113 Verify existing RTPC updates and preservation](https://github.com/zcyh147/waapi-skill/issues/113) | #111 |
| 06 | [#114 Run the GPT-6 model-selection pilot](https://github.com/zcyh147/waapi-skill/issues/114) | #111, #112, #113 |
| 07 | [#115 Verify exact matching of same-named media](https://github.com/zcyh147/waapi-skill/issues/115) | #111 |
| 08 | [#116 Verify attenuation-curve configuration](https://github.com/zcyh147/waapi-skill/issues/116) | #111 |
| 09 | [#117 Verify effect appending across version-specific structures](https://github.com/zcyh147/waapi-skill/issues/117) | #111 |
| 10 | [#118 Verify reference maintenance for an existing Stinger](https://github.com/zcyh147/waapi-skill/issues/118) | #111 |
| 11 | [#119 Investigate Playlist authoring and independent verification](https://github.com/zcyh147/waapi-skill/issues/119) | None |
| 12 | [#120 Investigate Transition configuration and independent verification](https://github.com/zcyh147/waapi-skill/issues/120) | None |
| 13 | [#121 Investigate Music Switch paths across multiple condition groups](https://github.com/zcyh147/waapi-skill/issues/121) | None |
| 14 | [#122 Freeze the campaign and complete macOS acceptance](https://github.com/zcyh147/waapi-skill/issues/122) | #109, #110, #111, #112, #113, #114, #115, #116, #117, #118, #119, #120, #121 |
