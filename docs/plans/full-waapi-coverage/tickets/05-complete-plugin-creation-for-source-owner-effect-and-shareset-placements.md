# 05: Complete all native plugin kinds and placements

Status: approved for implementation on 2026-10-17. Published as [05: Complete all native plugin kinds and placements](https://github.com/zcyh147/waapi-skill/issues/179).

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can create every in-scope native-supported plugin placement with the correct parent, class and properties, including supported alternatives on older Wwise versions.

## Current conversion association boundary — user-approved 2026-10-27

Existing conversion-getter attempts are sufficient; stop further platform/codec
QA and research. Their ambiguous results cannot independently prove which codec
belongs to a platform. Correctly wrap the setter through the pinned closed
contract and code tests; the setter code adjustment remains required. Disclose
the independent platform-association verification limit before authorization,
without guessing codec IDs or asserting a stronger verified effect. Reuse
existing observations only for their actual facts; ambiguity is not native
absence. Preserve configuration, policies, immutable Preview, execute-once and
truthful uncertainty. This acceptance boundary does not close #179 or #183,
and does not remove other plugin placement or conversion/build input work.

## Acceptance criteria

- [ ] Treat Source children, owner-local effects and independent Effect ShareSets as distinct business branches, including applicable parent types, platform behavior, conflict modes and class properties.
- [ ] Account explicitly for the installed SourcePlugin, EffectPlugin, SinkPlugin, ConversionPlugin and MetadataPlugin class kinds across all five builds. Determine each native-supported creation/attachment/configuration placement, including Wwise System Output Settings metadata (CompanyID 0 / PluginID 900 observed in installed XML), from matching native evidence. Installed class definitions alone prove neither creatability nor native absence; unsupported Skill discovery or placement remains implementation work.
- [ ] Coordinate plugin-class and placement mechanics with #178/#180 and field discovery/conditions with #177/#181. #183 retains the conversion/build workflow itself; its existence does not substitute for plugin-class placement coverage.
- [ ] Resolve live plugin kinds and fields through Type/Field Handles and expose complete placement guidance through compact catalogs, schemas and continuations.
- [ ] Investigate 2021 alternatives with matching native evidence. One rejected classic-create spelling or an absent newer backend does not justify closing 2021 support as impossible.
- [ ] Implement a supported native alternative where available; reject incompatible targets, stale classes, unavailable plugins and conflicting placements before writing.
- [ ] Verify identity, parent, plugin class, property values and effect ownership/slot state under the applicable acceptance method, with the current explicit conversion platform-association limit. Preserve existing effects and all unrelated objects; missing license/setup is a blocker, not a native-unavailable conclusion.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

## Blocked by

- [04: Complete conditional configuration of newly created objects](https://github.com/zcyh147/waapi-skill/issues/178)

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.

## Accepted closeout — 2026-10-27

The user accepted the disclosed 2021.1 donor-free selected-class AudioDevice and
Metadata constructor limitation. It remains a Skill boundary, not a claim that
all native alternatives are impossible. The reviewed modern placements,
including the 2022.1–2024.1 direct Metadata List and distinct 2025.1 MetadataSlot,
are delivered. Their original verification-strength limits remain unchanged.
Close #179 under this explicit exception; retain historical failures. Final
inventory reconciliation and combined gates stay with #195, and Fresh with #194.
