# 04: Support conditional activation dependencies for attenuation references

## Parent

#163

## What to build

A user can associate attenuation with a Sound or container, with necessary positioning changes disclosed in Preview and verified after execution.

## Acceptance criteria

- [ ] Interpret the observed conditions/property/override dependency semantics; merely accepting additional keys is insufficient.
- [ ] Deduplicate repeated requirements; avoid needless changes when already satisfied; reject conflicting, cyclic or unknown requirements before dispatch.
- [ ] Preview identifies both reference and required property changes; independent readback proves both and preservation of unrelated fields.
- [ ] Exercise the public object.set path for Sound and container targets. Implement applicable behavior in all five versions and explicitly verify native version boundaries.

## Blocked by

None

## Validation

Use real incident metadata as fixtures, five-version positive/negative program tests, then coordinated sandbox association and independent readback. No separate Fresh.

## Execution constraints

The user approved implementation on 2026-10-17. All five supported version lanes must be covered; documented native unavailability is an explicit tested boundary, not silent omission. Use the approved public Gateway/FakeClient seams and TDD. Follow repository guidance and the spec budget. Do not modify the Lyra user project or replay its transactions. Report program, real-Wwise and Fresh evidence separately.
