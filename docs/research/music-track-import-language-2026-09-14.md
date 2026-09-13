# Music Track import language regression — 2026-09-14

Base main: `54228d9` (PR #103). Repair candidate: `48ad683` on
`codex/music-track-import-language`. This is a scoped default-value repair,
not completed music-workflow acceptance.

## Real reproduction

Visible application task: `01a09bc8-259a-7861-871f-94785d29dbb7`, Sol / High,
working in `/Users/xiye/Documents/Git/waapi_skill_test`, connected through the
public Gateway to the already-running Wwise Authoring 2025.1 on port 8080.
This is a visible app-task test, not a formal memory-isolated Fresh campaign.

The first prompt incorrectly used `Interactive Music Hierarchy`. A subsequent
read-only exact query showed the actual path as `Containers`; strict identity
validation rejected the alias mismatch. This was coordinator-authored test
input, not an Agent path invention. The user also noted that Containers paths
had worked in earlier versions; this observation is not treated as a new
2025-only capability claim.

Using `Containers > Default Work Unit`, a new draft for
`Music_Import_Probe_20260914_B` bound the parent successfully. Its batch declared
a Music Segment, child Music Track, existing `wind_bed.wav` media and -6 dB,
without a language field. `draft-declare-import-batch` returned
`REQUIRED_FIELD_MISSING`, field `language`, `draft_revision: 2`,
`draft_changed: false`. No Wwise import or other project mutation occurred.

## Repair and program evidence

The compiler had derived SFX only for Sound SFX. It now also derives SFX from
the exact MusicTrack target type, for both new and already-bound targets,
only when language is omitted. Explicit row/default languages are preserved;
empty language remains invalid and Voice still requires its explicit language.
The patch changes one conditional in `audio_import_business.py`, without
changing Draft storage, revision handling, authorization or execution.

- Before repair, the new five-version Music Track matrix returned **10 failed,
  40 passed**; all ten omitted-language new/existing cases reproduced the bug.
- Final scoped Adapter/Gateway files: **142 passed**, exit 0.
- Final fixed Program: **5224 passed, 2 skipped**, exit 0, 260.74 seconds.
  Skips require native Windows shell/NTFS behavior. No full Non-live rerun or
  cross-version real campaign was needed for this conditional-only repair.
- A new Gateway batch regression covers Segment + Track + media + volume on
  all five versions without any import dispatch. Its first 2021 fixture lacked
  that version's Project object-get response; correcting this fake response
  produced **5 passed** without any runtime change.

Only the changed Python file was synchronized to the demonstration Skill after
proving its pre-repair bytes matched main. Other demonstration instructions
remain older than PR #103; neither the whole installed Skill nor its local
state/configuration was replaced.

## Follow-up preview: next boundary, not a music PASS

New draft `Music_Import_Probe_20260914_C` repeated the same business declaration
without manually supplying language. Declaration succeeded, proving the
original missing-language failure no longer reproduced. However `draft-check`
returned:

```text
IMPORT_DYNAMIC_MEDIA_TOPOLOGY_UNSUPPORTED
Dynamic fields with media require a live-validated Sound target.
index: 1
metadata_object_type: MusicTrack
```

No final Preview was produced and no project modification executed. All failed
drafts and task outputs were retained. Do not interpret this as Music Track
import/volume business acceptance. The next investigation must establish the
Music Track/AudioFileSource/Clip ownership and readback rules before extending
the Sound-specific topology guard; do not simply remove the guard.

The user requested a music-only knowledge-base audit, excluding already heavily
tested Sound/Event/RTPC workflows and Dialogue Events. Use Wwise 2022.1 as the
baseline and explicitly check documented differences for 2021.1, 2023.1,
2024.1 and 2025.1. Missing documentation is not evidence of unsupported behavior.
