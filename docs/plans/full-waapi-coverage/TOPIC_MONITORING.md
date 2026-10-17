# Topic monitoring implementation and required native proof (#187)

This is a partial implementation checkpoint, not completion of #187 or #174.
The independent native denominator remains
`docs/branch-coverage-inventory.native-obligations.json.gz`. Its original route,
pointer, shape, owner and required-evidence identities remain authoritative;
this document grants no native, Fresh, family or descendant acceptance credit.

## Native comparison

Compare `resources/native-catalog/<version>/wwise-console.json` and
`wwise-authoring.json` under the packaged Skill, including their exact-build
provenance, definitions and schema source seals. The existing
`host-schema-parity.json` records shared-schema equality as reflection only.

| Release | Captured build | Console Topics | Authoring Topics | Public union |
| --- | --- | ---: | ---: | ---: |
| 2021.1 | 2021.1.14.8108 | 27 | 27 | 27 |
| 2022.1 | 2022.1.19.8584 | 32 | 32 | 32 |
| 2023.1 | 2023.1.19.8928 | 32 | 32 | 32 |
| 2024.1 | 2024.1.13.9056 | 30 | 34 | 34 |
| 2025.1 | 2025.1.7.9143 | 31 | 35 | 35 |

The public `topic-schema` union matches all captured Topic URI lists. That is
discovery evidence, not delivery evidence. The fixed `ui.signal.click/toggle`
URIs are absent from the captured 2021–2023 Authoring lists; this establishes
only those exact URI/build observations, not absence of a business alternative.

Subscription options compile through `topic_options_contract`; the recursive
optional event predicate compiles through `topic_match_contract` and the closed
business facts/row/exact-entry interface. `topic-schema` discloses the matching
semantics: object subset, positional arrays of exact length, JSON scalar
equality with distinct booleans, and separately counted duplicate callbacks.
No native args/options or arbitrary publisher is introduced.

Delivered events resolve reachable local, external and recursive definitions
against the pinned version graph before filtering. Unknown references fail
closed. Definition/type/range/union validity and subscription acknowledgement
are separate from actual matching delivery and cleanup.

The 2021 `ak.wwise.core.soundbank.generated` source contains legacy properties
outside the `properties` wrapper. Construction and event validation now use the
inventory's existing exact `_is_legacy_implicit_property` parser and approved
`LEGACY_2021_SOUNDBANK_IMPLICIT_PROPERTY_PATHS`. Original native resources and
pointers remain unchanged. Ten actual implicit members plus their reachable
children expand the business row catalog from five to eighteen collections:
media lists, GameParameters, AuxBusses, State/States, Switch/Switches, Triggers,
and IncludedEvents' media/SwitchContainers/Media. The two additional paths in
the twelve-path inventory allowlist are already wrapped; they are preserved.
Native publication and comparison semantics for these rows remain required proof.

Wait and stream monitoring now fail on queue loss, invalid strict JSON and
schema mismatch; filtering does not conceal a malformed received event. Both
retain cleanup evidence. `monitoring_outcome.target_completed` requires the
requested count and successful monitoring/cleanup. A duration or idle stop
before the count reports `stopped`; a partial wait timeout retains its matching
count. Event limits, existing total/idle deadlines and bounded output remain
Skill policy, not claims about native limits.

## Exact 2025 Notes-shape question and controlled probe

Owned native route identities:

- `2025.1|wwise-console|2025.1.7.9143|topic|ak.wwise.core.object.structureChanged`
- `2025.1|wwise-authoring|2025.1.7.9143|topic|ak.wwise.core.object.structureChanged`

The source pointer is
`/publishSchema/properties/objects/items/properties/changes/items/properties/notesChange`.
Its `properties` declare `oldName/newName`, its `required` array instead declares
`oldNotes/newNotes`, and `additionalProperties` is the string `"false"`.
The recognized six string-false source paths are retained without inventing a
Boolean normalization or silently renaming fields. Determine the emitted field
names, types and required presence on the matching native build before changing
the closed contract or claiming native schema correctness.

Run only in a future authorized native session, sequentially, through the
existing isolated sandbox lifecycle and public Gateway path. No process or
native test was launched for this checkpoint.

1. Attest an owned disposable SampleProject copy, its source hash/mtime,
   configured connection, actual `getInfo` host/version/build/session and
   Gateway candidate. Never open a committed source or user project. Set the
   isolated config through `config-set`; preserve its modification policy.
2. Create one disposable ActorMixer through its closed operation, with Notes
   `topic-notes-before`. Verify the exact GUID/name/type/path/notes through the
   simple exact-ID read. Prepare a separate immutable `object.setNotes` Preview
   changing only that GUID's Notes to `topic-notes-after`. Use
   `operation-schema object.setNotes` and copy its generated Draft/authorization
   continuations; observation itself authorizes no write.
3. Read `topic-schema ak.wwise.core.object.structureChanged`. Copy its digest
   into `stream-topic`, with global `--timeout 10`, explicit `--event-count 1`,
   and `--topic-option include` repeated for `id`, `name`, `type`, `path`,
   `notes`. Omit the native optional
   `includeLoadedAndUnloadedNestedObjects` option. The resulting subscription
   options are Gateway-built `return` for those five fields. Do not supply an
   event filter on the disputed fields or synthesize a raw subscription.
4. Wait for the public flushed `started` record, which proves subscription
   setup only. Execute the separately authorized Notes Preview at most once.
   With no concurrent sandbox edits, inspect the sole event for the tracked
   GUID and `changes[].type == "notesChange"`; distinguish `oldNotes/newNotes`,
   `oldName/newName`, both, or another shape, with exact before/after strings.
   If schema validation fails, retain `TOPIC_EVENT_SCHEMA_MISMATCH` and its
   small exact `details.event_diagnostic.json` instead of accepting the event.
   This diagnostic is bounded to 2048 UTF-8 bytes; `complete=false` requires
   a separately reviewed evidence-capture extension, not guessed fields.
5. Independently verify the GUID's Notes equals `topic-notes-after`, retain the
   terminal count/reason/unsubscribe result and prove no subscription remains.
   Delete the owned object through a separately authorized Preview and exact
   absence readback. Prove source immutability and owned-process cleanup.
   Quarantine failed/indeterminate evidence and never replay the Notes write.

This is a minimal owned trigger specification, not a second harness. The older
`versioned_object_topics_sandbox.py` direct-client smoke does not establish the
new public Gateway contract or this Notes variant. The future runner must use
the established lifecycle plus public Gateway producer/observer, retain the
original received packet or bounded diagnostic and compare its exact source
seal. #195 owns scheduling and native acceptance; #187 owns the Topic shape fix
after that observation.

## Remaining delivery obligations and dependencies

- Real events and unsubscribe/resource cleanup remain required for object
  mutations (including the Notes contradiction), imported object arrays,
  version-specific SoundBank nested rows, log entries, runtime/profiler and
  transport events, project lifecycle, command/selection and frontend signals.
  Reflection equality permits no automatic host/version behavioral credit.
- #189 owns model/WAFM/window resource lifetimes and the closed signal-emission
  trigger. Signal delivery under #187 depends on those owned resources; an
  invented handle/widget or fake callback cannot satisfy that dependency.
- Native alternatives not yet exercised retain their exact original #187
  owner and evidence obligations. New scoped tests prove only their selected
  public construction/validation behavior; they do not complete the 115,676
  original #187 native obligations or update their evidence states.
- #194 retains separate Fresh/Broker/archive routing acceptance, and no Fresh
  expense is authorized. Program and Non-live gates run centrally after the
  combined candidate's source seals are reconciled.
