# Wwise 2021.1 classic ShareSet creation: scoped feasibility result

The packaged `object.createPlugin` operation remains unavailable on 2021.1.
Its current backend requires `object.set`, which is absent in that reflected
lane. This is a packaged implementation boundary, **not proof that every native
ShareSet creation route is unavailable**.

A source-guided, one-attempt classic `object.create` probe on Wwise
2021.1.14.8108 failed with `ak.wwise.invalid_arguments`, message `type is unknown`.
The rejected `type` was the exact live `getTypes` name `Wwise Gain`, not an
invented token. No alternative encoding was tried. This remains a failed native
feasibility attempt, with no public Gateway or Agent PASS credit.

## Source basis and limits

The pinned `resources/manifest/2021.1/schemas.json` entry for
`ak.wwise.core.object.create` requires `parent`, `type` and `name`. Both root and
recursive children have `additionalProperties: false` and no `classId` member.
The documented `@property` pattern does not authorize inventing a plug-in
selection property. The later `object.set` payload containing `type: Effect`
and `classId` cannot simply be sent to this older API.

The matching official SDK source was read from the installed
`/Applications/Audiokinetic/Wwise2021.1.14.8108/SDK/Help/WwiseSDK-Windows.chm`,
whose pages identify themselves as Wwise SDK 2021.1.14. This is static
Windows SDK documentation, not native-Windows execution evidence.

- `ak_wwise_core_object_create.html` directs `type` to Wwise Objects Reference.
- `waapi_import.html` documents limitations for Sounds, Work Units and Queries;
  it does not document an Effect creation prohibition.
- `wobjects_index.html` exposes Name, PluginID and ClassID columns.
- `ak_wwise_core_object_gettypes.html` describes its result as the equivalent of
  that reference. The reflected result exposes `name`, `type`, and `classId`.
- `wwiseobject_effect_wwise_gain.html` exposes Wwise Gain, PluginID 139 and
  ClassID 9109507, plus its properties. The RoomVerb page similarly exposes its
  display name, numeric identifiers and properties. Neither discloses a separate
  canonical string token for `object.create`.

The versioned public-library links in the existing semantic note could not be
retrieved through the web tool during this review. The matching installed SDK
pages, pinned reflection and live catalog therefore supply the concrete evidence.
The semantic note's prohibition on generic mutation builders is a repository
boundary; it is not independent proof of native impossibility. SDK library or
factory identifiers such as `AkRoomVerbFX` are not documented create tokens and
were not tried.

## Native attempt

Candidate: `cc99ea98` (the probe's first committed revision).
Test: `tests/destructive/test_shareset_2021_creation_feasibility.py::test_2021_classic_create_effect_shareset_feasibility`.
Result: **1 failed / 32 deselected, 11.09 seconds**, via `ci/test.sh --version
2021.1 --mode destructive` with the exact test selection and a new explicit
`WAAPI_SHARESET_2021_PROBE_ROOT`.

The existing `ScenarioLifecycle` used private HOME and its attested effective
Wine prefix. The live catalog returned `{name: Wwise Gain, type: Effect,
classId: 9109507}`. An exact path query verified the parent as the WorkUnit at
`\Effects\Default Work Unit`. The request used that returned parent GUID,
`type: Wwise Gain`, a probe-owned name and `onNameConflict: fail`; it passed the
packaged request-schema validator before Wwise rejected the type. No successful
created-object result or post-creation readback exists.

Evidence is retained in the ShareSet worktree under
`.waapi-skill-state/shareset-classic-cc99ea98-2021-r1/evidence/`:

| Artifact | SHA-256 |
| --- | --- |
| `lifecycle.json` | `9e337cd92570df1ed0a842d9c214db2508265a1ef9cb021e6c1df1ac51d3f80d` |
| `shareset-classic-create.json` | `591e2c91840e2a19361e7b6f5e870561124bc0a18b45c3f770476dfac6ba79d4` |

The lifecycle is FAIL with the native rejection recorded, not PASS. Its full
source-project hash and project mtime are identical before/after. The failed
sandbox is retained and quarantined. The owned client closed and the terminal
process check found no residual Wwise/WwiseConsole process. The preserved
candidate and failure are not replaced by later fixture scoping or documentation
changes.

## Remaining decision

A supported alternate 2021.1 topology still needs a matching primary-source
contract or explicit native schema evidence before another controlled probe.
The current evidence rejects the tested plug-in-name encoding only. Do not
claim all-five-version positive ShareSet support, universal native impossibility,
or a successful unsupported-boundary test from this failed attempt. Later
2022.1–2025.1 public `object.set` ShareSet PASS evidence remains separately valid.

## Static SDK page hashes

SHA-256 of the exact decompressed HTML page bytes:

| Page | SHA-256 |
| --- | --- |
| `ak_wwise_core_object_create.html` | `e3fb51209ca0726ce88e3349dfb5eb52ebf1a9d946c56762e0b20cd7f1e59784` |
| `waapi_import.html` | `07c62457f1179f73fedeeb8746ad382bea023c80d0002201450401e75f767fed` |
| `wobjects_index.html` | `10bec7e4784f5f4ed55ee25ebb3ef791970ef2521d43495620cf67ac1e75950a` |
| `ak_wwise_core_object_gettypes.html` | `98688037e604f0c15d174218b6e318b2eeaa2f2432775ac39c6e309dc072a67f` |
| `wwiseobject_effect_wwise_gain.html` | `afc4df1dbde4a55b8afdcadfa27929ffa189dce0af42d7dd37dbbd044df893c4` |
| `wwiseobject_effect_wwise_roomverb.html` | `fe822d67a6d2538c4567f838f2d03d611c4a553fbe0bc47bf04904c45624816e` |

## Preserved location after worktree cleanup

The byte-identical root is also preserved in the main project at
`.waapi-skill-state/repair-evidence/waapi-sharesets/.waapi-skill-state/shareset-classic-cc99ea98-2021-r1/`.
The relocation inventory is `.waapi-skill-state/repair-evidence/relocation-manifest.json`;
original paths remain provenance. The lifecycle and evidence hashes above remain
unchanged. The failed sandbox was preserved with the root, not deleted.
