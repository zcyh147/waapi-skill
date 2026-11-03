# Full WAAPI coverage: ticket proposal

Parent: [Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).
Status: user-approved and published on 2026-10-17. All 21 native sub-issue links and 36 native blocking edges were verified. Implementation is active on codex/full-waapi-coverage; no Fresh run has been authorized.

## Review summary

Two enabling slices establish native truth and an executable completion check.
Seventeen functional slices close complete public workflows, including their
schema, construction, dispatch, verifier and tests. Two integration slices check
cross-family discovery/harness compatibility and final acceptance. Reflection and
tooling can finish while correctly showing missing product work; they cannot
close the implementation parent.

Every ticket covers 2021.1–2025.1 explicitly. Native absence and approved exclusion
remain visible but are not successful implementation evidence. Newly discovered
in-scope gaps remain under the parent. If a family is too large for one fresh
context, split its frozen exact branch roster into bounded child slices and make
final acceptance depend on all of them; do not treat these 21 rows as a cap on work.

This is an initial graph of known prerequisites. Add a native edge for a genuinely
new shared prerequisite revealed by reflection. Do not block unrelated families
merely for sequential convenience. Shared request/validation prefactoring belongs
in the first affected complete public slice, with explicit dependent consumers;
no new generic execution engine or broad horizontal rewrite is assumed.

The public Gateway is the common test seam. Program tests carry five-version
coverage; deterministic native tests prove effects and native differences;
Fresh stays Mac-only, small and separately approved. Each functional ticket owns
its routing and tests already: ticket 20 checks their cross-family consistency,
not a postponed first integration of otherwise incomplete components.

## Proposed slices

| Draft | English title | Blocked by | Delivered behavior |
| --- | --- | --- | --- |
| 01 | [Establish complete five-version native catalogs and schema discovery](tickets/01-establish-complete-five-version-native-catalogs-and-schema-discovery.md) | None | A maintainer can inspect the complete independently evidenced Console and in-scope Authoring capability set through versioned discovery, with missing wrapper support reported separately from missing native support. |
| 02 | [Make branch completion and gap ownership executable](tickets/02-make-branch-completion-and-gap-ownership-executable.md) | 01 | The coverage checker explains exactly which native-supported uses are unavailable or unverified, which implementation ticket owns each gap, and whether the overall effort is actually complete. |
| 03 | [Support native metadata conditions for existing-object changes](tickets/03-support-native-metadata-conditions-for-existing-object-changes.md) | 02 | Valid property and reference changes work across applicable object classes because the Gateway understands their native activation conditions, rather than accepting only previously encountered examples. |
| 04 | [Complete conditional configuration of newly created objects](tickets/04-complete-conditional-configuration-of-newly-created-objects.md) | 03 | A user can create an object with its requested valid initial fields even when those fields depend on class defaults or prerequisite settings. |
| 05 | [Complete all native plugin kinds and placements](tickets/05-complete-plugin-creation-for-source-owner-effect-and-shareset-placements.md) | 04 | Users can create every in-scope native-supported plugin placement with the correct parent, class and properties, including supported alternatives on older Wwise versions. |
| 06 | [Complete generic object graph and lifecycle operations](tickets/06-complete-generic-object-graph-and-lifecycle-operations.md) | 04 | Users can create or edit valid object trees and perform copy, move, rename, delete, property and reference workflows without losing permitted target or conflict-mode alternatives. |
| 07 | [Complete object queries and metadata discovery projections](tickets/07-complete-object-queries-and-metadata-discovery-projections.md) | 02 | Users can express valid in-scope read semantics and inspect every applicable property/reference detail through bounded public queries and metadata discovery. |
| 08 | [Complete audio import, reimport and replacement workflows](tickets/08-complete-audio-import-reimport-and-replacement-workflows.md) | 04 | Users can import, update and replace media and object structures with all in-scope native-supported row and option alternatives through closed import declarations. |
| 09 | [Complete SoundBank definition, conversion and build options](tickets/09-complete-soundbank-definition-conversion-and-build-options.md) | 02 | Users can manage inclusions, process definitions, convert external sources and generate requested banks without wrapper omissions in valid build branches. |
| 10 | [Complete Console project and file-operation alternatives](tickets/10-complete-console-project-and-file-operation-alternatives.md) | 02 | Users can perform the permitted Console project/file/migration workflows with complete native option handling and accurate terminal outcomes. |
| 11 | [Complete SoundEngine control branches and capability lifetimes](tickets/11-complete-soundengine-control-branches-and-capability-lifetimes.md) | 02 | Users can perform every in-scope reflected runtime control through meaningful business inputs, with valid game-object and playing-resource lifetimes. |
| 12 | [Complete runtime inspection, profiling and transport workflows](tickets/12-complete-runtime-inspection-profiling-and-transport-workflows.md) | 02 | Users can inspect and control the permitted profiling/transport sessions and receive complete bounded results with correct resource cleanup. |
| 13 | [Complete Topic filtering, event shapes and monitoring outcomes](tickets/13-complete-topic-filtering-event-shapes-and-monitoring-outcomes.md) | 02 | Users can monitor every in-scope Topic using its legal filtering/options and obtain correctly validated events and truthful completion status. |
| 14 | [Expose complete ordinary Authoring layout and view workflows](tickets/14-expose-complete-ordinary-authoring-layout-and-view-workflows.md) | 02 | Users can inspect and manipulate the reflected ordinary Authoring layouts and views through controlled Gateway operations on the correct Wwise host. |
| 15 | [Expose Authoring model, window and signal workflows](tickets/15-expose-authoring-model-window-and-signal-workflows.md) | 02 | Users can use native-supported ordinary Authoring model/window/signal capabilities through complete typed business contracts and owned resource lifetimes. |
| 16 | [Complete Authoring project, remote and command workflows](tickets/16-complete-authoring-project-remote-and-command-workflows.md) | 02 | Users can use the existing Authoring project/remote/selection/command capabilities with all permitted branches and accurate project/session transitions. |
| 17 | [Complete specialized project and object authoring operations](tickets/17-complete-specialized-project-and-object-authoring-operations.md) | 03 | Users can perform the native-specific authoring operations that generic object edits cannot faithfully substitute, with all legal parameters and meaningful target variants. |
| 18 | [Complete source-control and compound edit-history workflows](tickets/18-complete-source-control-and-compound-edit-history-workflows.md) | 02 | Users can perform supported source-control and compound edit-history operations through complete closed requests with accurate outcomes and authorization. |
| 19 | [Complete permitted host-control and remaining fixed Core contracts](tickets/19-complete-permitted-host-control-and-remaining-fixed-core-contracts.md) | 02 | Users receive complete permitted host-control/fixed Core inputs and truthful terminal results, including routes whose zero-input shape previously concealed missing outcome handling. |
| 20 | [Validate Skill discovery and formal-harness compatibility end to end](tickets/20-validate-skill-discovery-and-formal-harness-compatibility-end-to-end.md) | 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19 | An Agent following only the Skill and Gateway discoveries can reach every completed task family without guessing implementation details, and the formal test harness accepts those legal paths. |
| 21 | [Complete integrated five-version coverage and scoped acceptance](tickets/21-complete-integrated-five-version-coverage-and-scoped-acceptance.md) | 20 | The integrated Skill is ready for delivery only when every in-scope native-supported business branch is implemented, reachable and proven at its required evidence level. |

## Dependency overview

- 01 → 02.
- 02 → 03, 07, 09–16, 18–19.
- 03 → 04 and 17.
- 04 → 05, 06 and 08.
- All functional slices 03–19 → 20.
- 20 → 21 (01–19 are transitive prerequisites). Every later mandatory same-parent child also blocks 21 and any affected routing integration.

The exact machine-readable edges are in ticket-proposal.json. The approved tickets are native GitHub sub-issues of the parent, with native
blocking links verified after creation. The parent specification remains unchanged.
The machine-readable proposal maps every local draft ID to its published issue.

## No missing-family escape

- Object/lifecycle/specialized Core rows are owned by 03–06 and 17; new-class
  conditions and plugin placement have separate explicit owners.
- Query/metadata rows belong to 07; conditions as mutation semantics belong to 03.
- Media/import/build/Console rows belong to 08–10.
- SoundEngine/runtime inspection/transport rows belong to 11–12.
- Topic rows belong to 13, with explicit links to any new event producer needed.
- Ordinary Authoring layout/model/window/signal/project/remote/command rows belong
  to 14–16; excluded Authoring ui.cli Lua/launch additions remain excluded.
- Source-control/compound undo rows belong to 18; permitted host-control and the
  bounded remaining fixed Core roster belong to 19. Unrelated or oversized
  remainder groups must become named bounded children, not a miscellaneous sink.
- Shared definitions and result alternatives are assigned to every reachable
  consumer by 02 and proved by the owning functional slice. No group receives
  PASS merely because a shared parent or sibling passed.
- The complete source inventory, including every residual group, must reconcile
  to exact owned branches or justified native/policy boundaries. Anything that
  cannot be assigned creates new in-scope implementation work and blocks 21.

## Published issues

- [01: Establish complete five-version native catalogs and schema discovery](https://github.com/zcyh147/waapi-skill/issues/175)
- [02: Make branch completion and gap ownership executable](https://github.com/zcyh147/waapi-skill/issues/176)
- [03: Support native metadata conditions for existing-object changes](https://github.com/zcyh147/waapi-skill/issues/177)
- [04: Complete conditional configuration of newly created objects](https://github.com/zcyh147/waapi-skill/issues/178)
- [05: Complete all native plugin kinds and placements](https://github.com/zcyh147/waapi-skill/issues/179)
- [06: Complete generic object graph and lifecycle operations](https://github.com/zcyh147/waapi-skill/issues/180)
- [07: Complete object queries and metadata discovery projections](https://github.com/zcyh147/waapi-skill/issues/181)
- [08: Complete audio import, reimport and replacement workflows](https://github.com/zcyh147/waapi-skill/issues/182)
- [09: Complete SoundBank definition, conversion and build options](https://github.com/zcyh147/waapi-skill/issues/183)
- [10: Complete Console project and file-operation alternatives](https://github.com/zcyh147/waapi-skill/issues/184)
- [11: Complete SoundEngine control branches and capability lifetimes](https://github.com/zcyh147/waapi-skill/issues/185)
- [12: Complete runtime inspection, profiling and transport workflows](https://github.com/zcyh147/waapi-skill/issues/186)
- [13: Complete Topic filtering, event shapes and monitoring outcomes](https://github.com/zcyh147/waapi-skill/issues/187)
- [14: Expose complete ordinary Authoring layout and view workflows](https://github.com/zcyh147/waapi-skill/issues/188)
- [15: Expose Authoring model, window and signal workflows](https://github.com/zcyh147/waapi-skill/issues/189)
- [16: Complete Authoring project, remote and command workflows](https://github.com/zcyh147/waapi-skill/issues/190)
- [17: Complete specialized project and object authoring operations](https://github.com/zcyh147/waapi-skill/issues/191)
- [18: Complete source-control and compound edit-history workflows](https://github.com/zcyh147/waapi-skill/issues/192)
- [19: Complete permitted host-control and remaining fixed Core contracts](https://github.com/zcyh147/waapi-skill/issues/193)
- [20: Validate Skill discovery and formal-harness compatibility end to end](https://github.com/zcyh147/waapi-skill/issues/194)
- [21: Complete integrated five-version coverage and scoped acceptance](https://github.com/zcyh147/waapi-skill/issues/195)


## Approved delivery adjustment — 2026-10-25

The original 21 issues remain. New prerequisite [#197](https://github.com/zcyh147/waapi-skill/issues/197)
blocks every open original issue and the seven new implementation children:

| Original parent | Implementation children |
| --- | --- |
| #186 | #198 runtime/log reads; #199 playback transport; #200 capture/cursor/files; #201 meters |
| #193 | #202 generated audio files; #203 fixed/debug inspection; #204 host/server and existing user-source execution |

All children block their parent and #195. Native parent and blocking links were
read back after publication. Exact URI partitions and 40 added blocking edges
are in [delivery-batches.json](delivery-batches.json). This changes delivery
scheduling, not canonical coverage ownership or required functionality.
Complete #197, then pause and report before starting the children or other
business work. #194 owns separately approved Fresh selection; #195 reuses its
results and coordinates final combined gates.
