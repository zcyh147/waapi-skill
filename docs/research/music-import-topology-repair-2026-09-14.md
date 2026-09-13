# Music Track import topology repair

Date: 2026-09-14. Branch: `codex/music-track-import-language`.
Base includes the language-default repair `48ad683`; unrelated README commit
`76d85df` is preserved. This is a local music import repair, not full interactive
music authoring acceptance.

## Evidence and cause

The visible Sol/High preview task `01a09bc8-259a-7861-871f-94785d29dbb7`
first reproduced omitted MusicTrack language, then
`IMPORT_DYNAMIC_MEDIA_TOPOLOGY_UNSUPPORTED`. No demonstration project mutation
was performed. The prior record is `music-track-import-language-2026-09-14.md`.

Five NotebookLM answers were treated as research leads. The primary-source
corrections and exact SDK pages are in `music-primary-factcheck-2026-09-14.md`.
In particular, Track modes are properties, MusicClip has its own Volume, and
ordinary Switch assignments must not be assumed to implement Music Switch
paths. `object.set` exists in the packaged 2022–2025 lanes, not 2021; the
2022–2025 schemas document append/replaceAll list modes and default append.
These observations contradict several broad statements in the supplied answers.

Small native probes against copied projects established on each installed
2021.1.14, 2022.1.19, 2023.1.19, 2024.1.13 and 2025.1.7 host:

- One import can set Track Volume on a structure row and import media through
  an explicit child AudioFileSource row, creating an actual MusicClip.
- Track has no useful Sound `activeSource` readback. Its returned source GUID,
  exact path, live parent and type must be checked instead.
- Clip media paths are readable with `originalWavFilePath` on 2021 and
  `originalFilePath` on 2022–2025. The older manuals' narrower descriptions
  alone did not establish Clip support; these were verified experimentally.
- A 2025 comparison showed that reusing an already-created Track path without
  the explicit source could create no media. Music WAV/AMB rows therefore use
  explicit source materialization even when no property is requested.

The original public prepare regression went red with the exact topology error.
The added verifier regression went red on all five positive music cases while
the existing Sound path still passed. The fix retains source collision,
metadata, pre-state, file hash, language, authorization and single-execution
checks; unsupported/MIDI dynamic topology is not broadly allowed.

## Repair

Changes are confined to import preparation/materialization and verification in
`operation_registry.py`. No Draft state-machine or public prompt changes.

- Sound and MusicTrack use reviewed owner/source separation.
- Music verification follows the Track's bounded Sequence/Clip lists, validates
  exact returned identities/types and confirms a MusicClip uses the same media
  path as the imported source. It does not claim an unavailable Clip-to-source
  GUID reference has been inspected.
- Missing media, wrong source parent, wrong Clip media/type, duplicate/extra
  identities and oversized lists remain failures.
- No user engineering project was reset, imported into, or used destructively.

## Validation accounting

During development, the targeted four program files passed 615 cases. The
native topology probe passed once on each version. The two closed Gateway
workflows (media only; media plus -6 dB) then passed on each version, ten cases.
These initial runs were development worktree evidence, not an immutable Git
candidate release result. Frozen-candidate final results are recorded below
after completion.

Runtime candidate `af783b7` passed the final Program gate: **5266 passed,
2 skipped**, exit 0, 258.57 seconds. The skips require native Windows.
The four targeted program files passed **615 tests**.

The subsequent complete Non-live invocation returned **10840 passed, 2 failed,
113 skipped, 27 deselected**, exit 1, 767.65 seconds. During that run,
independent README/test commit `cbf60ee` changed the installation command;
its already-loaded assertion disagreed with the then-current README. The
packaged Skill tree did not change (`git diff af783b7..cbf60ee --
skills/waapi-skill` is empty), but this is not an immutable all-green gate.
The other failure required an obsolete fixed "latest passing" sentence in
the inventory, despite its current newest-first dated full-run/follow-up
format. The current README assertion passed unchanged; the inventory test
now checks measured dated results and preserves the explicit distinction
between a failed full run and successful focused follow-ups. Both complete
affected test files passed **23 tests**. Do not describe this as a single
all-green full Non-live run; no runtime fix followed Program.

The visible Sol/High task also completed a new D Preview successfully through
the synchronized music-only repair. Draft `od1-8f05a2736bf391069e42296fed5a046a`
produced transaction `tx1-ssg68xy0xmwxzy9yenq1`, artifact hash
`a7fce582da94c6a287183f040b96c1d9e958c7c36ac36218d1618485b991b901`.
Its command history stops at `preview-from-draft`; no execute was issued.
This is an existing visible application-task replay against Authoring 2025.1,
not a fresh memory-isolated semantic campaign. The demonstration copy retains
an unrelated older Authoring-core routing hunk; only this music patch and the
previous MusicTrack language fix were synchronized, not the entire Skill.

One early invocation mistakenly supplied a file without `-k` to `ci/test.sh`,
which appends selected-version defaults rather than replacing them. It ran 28
tests in 31 seconds: 10 passed and 18 unrelated legacy-helper failures (including
compact verification output assumptions). Those are not music acceptance, were
not repaired here and were not folded into the focused results. Later commands
explicitly selected only the music tests. A temporary native probe also used an
unsupported `@AudioSource` field, then the official media-path accessor replaced
it. The old-version probe removed the unsupported `children` accessor and used
the existing module-owned fixture to preserve exact evidence bookkeeping.
No broad Fresh Agent, Windows or semantic matrix was started.

## Release boundary

This proves the specified Music Segment/Track audio import and Track property
workflow, not every Playlist, Music Switch path, transition, cue, MIDI or
Stinger parameter combination. The NotebookLM reports do not establish those
as tested or justify adding raw payload/XML escape hatches. Do not claim
complete music-system editing acceptance in the article.
