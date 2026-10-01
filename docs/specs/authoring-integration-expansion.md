# WAAPI Skill: Outcome-Based Integration Test Expansion

Specification date: 2026-09-27. Task breakdown approved and published on 2026-09-28.

This specification records the final decisions agreed during planning. It supersedes earlier research proposals for representative-version scheduling, the Terra model, generated assets by default, and playback acceptance. The current authorization covers specification and ticket publication only; it does not start implementation, Wwise, or Fresh Agent tests.

## Implementation authorization and model amendment — 2026-10-01

The user authorized implementation with an active Goal after publishing this specification, paused it to conserve quota, and explicitly resumed on 2026-10-01. Earlier planning-only authorization statements in this document are historical and do not prevent the resumed implementation or approved tests.

The coordinating model is now GPT-6.1 Sol high. Implementation subagents use GPT-6 Luna max or GPT-6.1 Sol medium. For the still-unexecuted model-selection pilot, the Sol comparator is GPT-6.1 Sol medium; the approved Luna high then conditional medium comparison and six-task first pilot remain otherwise unchanged. Existing frozen profiles and historical model evidence retain their original meaning.

The audited Action-creation timing gap was resolved through repair #123's permitted explicit unsupported boundary. Direct Action creation does not receive positive timing coverage; existing Action edits and import-owned Event/Action generation retain their separate supported contracts.

## Problem Statement

The existing six business integration workflows demonstrate several common tasks, but do not represent every public parameter, object family, or music-authoring behavior. The large Python test suite also cannot establish parameter coverage from test counts alone. We need more valuable real-workflow coverage without duplicating tests, relying on rigid grading, or incurring unnecessary model costs.

Previous acceptance runs failed on irrelevant ordering and command-shape differences. Correctly completed complex tasks can also exceed overly tight timing expectations. This expansion must address workflow selection, independent outcome verification, model selection, and the cost of recovering from failures.

## Solution

Reuse the public Gateway and the formal Fresh Codex campaign to design seven additional complete business workflows and prioritize capability validation for three important music workflows. Judge actual project structure, fields, media, and references against the requested outcome, and protect explicitly identified objects and fields from unintended changes.

Complete macOS coverage for Wwise 2022.1 and 2025.1 first. Reuse the repository SampleProject and its assets, with an isolated project copy for every real attempt. Add Python coverage only for confirmed public-entrypoint gaps and necessary verification code. Run formal batches using: full pass, consolidated repairs, failed-case reruns, then another full pass.

## User Stories

1. As a maintainer, I want public parameters mapped to concrete inputs, assertions, and run evidence, so that I add only genuinely missing coverage.
2. As a maintainer, I want program tests, real Gateway tests, and Fresh Agent integration tests reported separately, so that evidence from one layer does not stand in for another.
3. As a sound designer, I want to update dialogue in one language, so that other languages, the Sound identity, and existing playback references remain unchanged.
4. As a sound designer, I want identically named files from different directories to update the correct objects, so that basename matching cannot confuse their media.
5. As a sound designer, I want to update an existing RTPC curve, so that values change without creating a duplicate control relationship.
6. As a sound designer, I want to edit one attenuation curve, so that other curves and references remain unchanged.
7. As a sound designer, I want to append an effect, so that existing plug-ins and bindings are preserved.
8. As a music designer, I want correct Segment, Track, and media relationships and Track properties, so that the project contains actual inspectable music content.
9. As a music designer, I want to change an existing Stinger's Trigger, so that its associated Segment remains unchanged.
10. As a music designer, I want Playlist entries, ordering, and loop settings to match my request, so that readback can verify the arrangement.
11. As a music designer, I want an existing Transition's source, destination, exit timing, and fades configured correctly, so that unrelated rules remain unchanged.
12. As a music designer, I want Music Switch condition combinations mapped to the correct target paths, so that music-selection configuration is correct.
13. As a maintainer, I want public expression and readback capabilities established for complex music tasks, so that empty objects or weak verification are not reported as completed workflows.
14. As a maintainer, I want ordinary Switch assignments distinguished from Music Switch paths, so that tests use the correct interface.
15. As a user, I want ask mode to show a preview and wait for a later confirmation, so that I approve a concrete change.
16. As a user, I want allow mode to authorize, execute, and verify an explicitly requested change, so that the workflow does not pause unnecessarily.
17. As a maintainer, I want each case to use the same business goal and permission mode in 2022.1 and 2025.1, so that version differences can be compared.
18. As a maintainer, I want unavailable versions reported as explicit boundaries, so that correct refusal is not counted as business success.
19. As a maintainer, I want to reuse SampleProject and existing media, so that fixture work stays focused on useful gaps.
20. As a maintainer, I want isolated copies and proof that the source project is unchanged, so that failures cannot contaminate the baseline.
21. As a maintainer, I want irrelevant object order, independent field order, and valid equivalent operations accepted, so that grading reflects business outcomes.
22. As a maintainer, I want missing, duplicate, incorrect, unintended, and unauthorized changes rejected, so that tolerant grading preserves correctness.
23. As a maintainer, I want Luna high and Sol medium compared on actual completion, time, and usage, so that model choice is evidence-based.
24. As a maintainer, I want to evaluate Luna medium after Luna high proves reliable, so that costs can fall without sacrificing correctness.
25. As a maintainer, I want case-level Agent time separated from startup, preparation, and cleanup, so that timing targets are meaningful.
26. As a maintainer, I want to finish a frozen batch before consolidating repairs and rerunning failures, so that debugging costs stay bounded.
27. As a maintainer, I want a final complete pass on one frozen candidate, so that acceptance does not combine results from different repair candidates.
28. As a maintainer, I want failed project copies and original evidence retained, so that model, Skill, grader, and environment failures can be distinguished.

## Implementation Decisions

### Reuse the existing interfaces

The highest common test interface is the public Gateway. The Agent performs Business Orchestration and submits Business Declarations. The Gateway owns types, Field Handles, version adaptation, paths, and native request construction. An Operation Draft is not write authorization. Every change continues through an immutable Change Preview, confirmation or durable policy authorization, at-most-once execution, and verification.

Reuse the existing real-test, project-copy, and evidence lifecycles. Agent semantic execution must use the existing Fresh campaign/matrix. Do not add a second harness or allow Agent-authored code, raw WAAPI payloads, or direct clients to bypass capability gaps.

### Workflows and scope

| ID | Business goal | Permission mode | Disposition |
| --- | --- | --- | --- |
| C01 | Update one dialogue language while preserving others | ask_before_changes | Initial set; model-selection pilot |
| C03 | Match same-named media to exact objects | ask_before_changes | Initial set |
| C06 | Update an existing RTPC curve while preserving other relationships | allow_changes | Initial set; model-selection pilot |
| C08 | Maintain a selected attenuation curve | allow_changes | Initial set |
| C09 | Append an effect while preserving existing items | allow_changes | Initial set; arbitrary reordering is not promised |
| M01 | Import music media, Segment/Track structure, and Track properties | allow_changes | Initial set; model-selection pilot |
| M05 | Change an existing Stinger's Trigger | allow_changes | Initial set; report a separate boundary where 2022 cannot perform it |
| M03 | Configure Playlist ordering and loops | allow_changes | Priority capability validation; define implementation work after identifying gaps |
| M04 | Maintain Transition rules | allow_changes | Priority capability validation; define implementation work after identifying gaps |
| M06 | Configure Music Switch paths across multiple condition groups | allow_changes | Priority capability validation; define implementation work after identifying gaps |

Reuse existing cases for C02 defaults and exceptions and C05 routing. Revise a new profile only for a concrete additional obligation; do not silently change frozen historical suites. C07 State configuration, C10 music relocation with reference preservation, C11 platform differences, and M02 music-layer parameters remain conditional candidates, without authorization to execute their entire scope. C04 Dialogue is deferred.

Each priority music investigation must produce one of four evidence-backed conclusions: the public interface already completes the task; only an independent oracle is missing; additional Gateway functionality is needed; or an explicit upstream/version boundary applies. Scope new functionality separately and obtain agreement before expanding implementation. Testing needs do not implicitly authorize a complete music-editing subsystem. All three investigations need an explicit disposition rather than silently disappearing from the final selection.

Each case owns one complete business goal. Do not split a single-transaction task artificially. When multiple transactions are genuinely necessary, preview, authorize, and verify each separately. Preservation assertions belong to the business goal and should not become separate Fresh cases merely to increase counts.

### Versions, hosts, and assets

The first host is macOS only. Every finally selected Agent case covers 2022.1 and 2025.1 with the same goal and permission mode; the Gateway adapts native types and hierarchy. Unavailable-version units provide boundary evidence, not business-success credit. Do not add a separate 2024.1 Fresh matrix. Schedule Windows separately after macOS is complete.

Python program contracts cover all applicable supported versions. Select additional real Gateway evidence based on actual differences and existing evidence; never grant an untested version credit from a representative version.

Prefer the repository SampleProject and its existing media, with an isolated copy for every attempt. Generate additional audio only for a demonstrated gap. Obtain objects, language names, media, and control parameters from the fixture's actual inventory; do not assume a new language must be added. Business test prompts remain in Chinese; this English issue is for contributor accessibility.

### Python additions

Reuse existing tests and add public-entrypoint assertions for create conflicts/replacement owners, Action timing on creation, object.set global settings, and file-based media input through set. Deduplicate existing assertions before extending coverage of imported source notes and Originals subdirectories. An unconfirmed gap does not automatically justify a new test.

New business oracles, fixtures, and profiles are integration infrastructure work; record them separately rather than counting them as another set of business cases. Track functional bugs and new capabilities as distinct repairs, without unrelated refactoring.

### Model selection

Do not use the 5.6 family. First compare GPT-6 Luna high and GPT-6 Sol medium on identical baselines and acceptance criteria: C01, M01, and C06, one 2025.1 attempt per model configuration, for six Fresh tasks. These are model-selection samples, not the final 2022/2025 campaign or proof of statistical reliability.

If Luna high completes the tasks reliably, evaluate Luna medium on the same three cases. Additional repetitions depend on failure attribution; do not default to max. Compare first-attempt complete outcomes, preservation, safety, recovery cost, elapsed time, and tokens, using the same frozen service tier. Select the formal model and reasoning effort after measurement. A Sol success following a Luna failure is not a Luna PASS.

Preserve the Terra pin and historical interpretation of old profiles. The new comparison profile explicitly records model, effort, and service tier; do not replace the model inside a frozen historical campaign.

## Testing Decisions

### Success criteria

An independent oracle seals expected outcomes before execution and reads actual project state or media bytes afterward. Check the target set, object identity/type/hierarchy, values, media ownership, references, and explicit preservation requirements. Agent claims, self-consistent requests/previews, or a Gateway success string are insufficient.

Music acceptance covers structure and configuration only, not playback, listening, or runtime beat behavior. Read back Playlist ordering/loops, Transition configuration, and Music Switch condition paths. Domain knowledge and documentation inform expectations but do not replace version-matched live evidence.

Allow valid permutations of unordered sets, independent fields, and independent object edits. Preserve meaningful order in curve points, Playlist entries, and dependent operations. Equivalence requires closed rules and negative controls. Do not penalize bounded, in-scope, reasonable reads solely through an exact command count. Wrong targets, duplicates/omissions, extra changes, unauthorized actions, Gateway bypasses, and retries of indeterminate writes remain failures.

### Evidence and timing

Historical data from nine complete local macOS batches includes 108 attempts, 76 successful cases, and 232 Agent turns within successful cases. Successful case-level Agent time averaged approximately 197 seconds, with a 176-second median, 374-second P95, and 406-second maximum. All used Terra medium on historical candidates; these are not current GPT-6 performance measurements.

Use an initial normal expectation of 3–5 minutes per case, flag cases exceeding 7 minutes as slow, and cap cumulative Agent execution time at 10 minutes per case. Exclude human waiting. Record startup, preparation, independent oracle work, and cleanup separately with their own bounds. The ten-minute case budget is not a ten-minute allowance for each turn. Three minutes without a tool call is not sufficient reason to terminate. Calibrate after the new-model pilot using a newly frozen configuration, not an arbitrary in-flight limit change.

At the resource limit, distinguish incomplete business work, infrastructure failure, and indeterminate outcomes. Do not skip cleanup or read-only reconciliation when the Agent budget expires. Preserve the prohibition on retrying indeterminate mutations.

### Batch and repair workflow

Freeze the candidate, then run the entire selected batch, collecting ordinary successes and failures without changing code mid-batch. Stop early only for systemic source-project protection, evidence, or cleanup faults that could invalidate later results.

Consolidate repairs afterward. Start a new root with failed-case reruns and any directly affected cases. Once all failures pass, rerun the entire selection on the final frozen candidate. Do not combine different repair candidates into final acceptance. Report business PASS or a genuine version boundary for every selected 2022/2025 unit; do not count boundaries as successful mutations.

Retain original FAIL records and project copies. Existing verify-only audits recheck the original frozen evidence; they do not apply a new grader to rewrite history. Any future derived regrade must preserve both graders and conclusions and must not invent missing execution or readback evidence. Such a mechanism is not a required deliverable for this iteration.

### Validation order

Run affected program tests and the fixed five-version Program gate first; add Non-live validation for substantial harness or contract changes. Run real Gateway and Fresh attempts sequentially, with isolated copies, frozen candidates, and explicit selections. Preparing model comparisons does not authorize running them now: the current deliverable is the specification and ticket breakdown.

## Out of Scope

- Formal Windows acceptance in this iteration, an additional full 2024 Fresh matrix, subscription retesting, and load-skill retesting.
- Playback, listening, perceived sound quality, and runtime beat-synchronization validation.
- Cartesian products of every parameter option, exhaustive plug-in-property coverage, or claims that 17 candidates cover all cases.
- General refactoring, a second Agent harness, direct-client workarounds, or raw-payload escape hatches.
- Music functionality expansion without separate scope agreement, and the complete Dialogue workflow.
- Rewriting historical PASS/FAIL records or counting documentation work as execution evidence.

## Further Notes

Use small, independently verifiable vertical slices with genuine dependencies. Do not divide the work horizontally into all fixtures, all oracles, and all business cases. The three priority music investigations can proceed independently and do not block preparation of the initial cases; their implementation scope follows from their findings. The user approved the ticket breakdown on 2026-09-28, and the child issues have been published. Publication does not automatically start implementation or testing.
