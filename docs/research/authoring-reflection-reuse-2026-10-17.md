# Authoring history: factual exploration

Read-only inspection, 2026-10-17, repository /Users/xiye/Documents/Git/waapi-skills. No Wwise, Gateway, tests, Fresh campaign, configuration, or repository writes. Only this report written.

## Surviving evidence

All five full function/Topic URI lists survive under .waapi-skill-state/evidence/authoring-topics-20260913/. None of the requested historical roots contains a full Authoring schema reflection. The saved getFunctions/getTopics outputs are complete Gateway inventory projections, not original native WAAPI array envelopes. getInfo survives inside status outputs except the 2024 topic discovery record.

| Version/build | Functions / Topics | Exact inventory file | getInfo / narrow schema provenance |
|---|---:|---|---|
| 2021.1.14.8108 | 99 / 27 | 2021.1-reflection.json | status.wwise; selectionChanged schema |
| 2022.1.19.8584 | 112 / 32 | 2022.1-reflection.json | status.wwise; selectionChanged schema |
| 2023.1.19.8928 | 149 / 32 | 2023.1-reflection.json | status.wwise; selectionChanged schema |
| 2024.1.13.9056 | 170 / 34 | 2024.1-inventory.json | NO same-session status/getInfo; three schemas in 2024.1-schemas.json |
| 2025.1.7.9143 | 179 / 35 | 2025.1-reflection.json | status.wwise; three Topic schemas |

Full lists are functions.inventory.uris and topics.inventory.uris, duplicated as final agent_result. All saved calls report ok, correct detected version, is_command_line=false. The 2024 inventory includes a top-level build label but lacks a same-session getInfo object: later .waapi-skill-state/evidence/authoring-core-20260913/2024.1/status.json proves the matching build was observed later, not the original inventory session. Its session is 547F4C0B-5ADA-43E0-A4FB-B51409C7A520, processId320, version schema123. 2025 topic session is C9FD7A5A-636C-4526-A66C-E5D0CB4D1055, processId260, version schema133; later core status is a different session.

For 2021–2023, Authoring URI lists exactly equal canonical Console sets. This does not establish host schema or runtime behavior parity. For 2024/2025, three narrow Topic schemas are selectionChanged, signal.click and signal.toggle. All six exact payloads match committed authoring-ui-topics-supplement.json. All nineteen core raw ak.*.json payloads (nine2024, ten2025) match committed authoring-core-supplement.json exactly and report ok. These are schema evidence, not execution evidence.

Host provenance: inspected envelopes use ws://127.0.0.1:8080/waapi, report Wwise.exe and isCommandLine=false. Surviving status project paths use Z:/Applications/Audiokinetic/SampleProject... in Windows spelling. Topic audit explicitly says macOS, consistent with macOS wrapper/Wine. Core doc says Windows Authoring builds but Gateway/collector on macOS; raw loopback/Z-drive records do not establish a native-Windows host execution. Some statuses have isDirty=true. No project-cleanliness/source-integrity claim follows.

## Count reconciliation from source sets

2024 Console:148 functions +30 Topics. Authoring shares132 functions, adds38, lacks16; it has30 shared +4 extra Topics. Actual Authoring total170+34=204. Before core additions the packaged-present intersection was132 shared functions +4 command functions +34 Topics=170/204. After nine core additions it is179/204, with25 functions still outside the reviewed profile.

2025 Console:154 functions +31 Topics. Authoring shares138 functions, adds41, lacks16; it has31 shared +4 extra Topics. Actual total179+35=214. Before core additions packaged intersection was138+4+35=177/214. After ten core additions it is187/214, with27 functions outside profile.

The170 in “170 functions” and “170/204 present” are coincidentally equal but refer to different sets. Current union-style packaged Authoring profiles total195/203 rows, each retaining16 Console-only rows. Across five versions126+144+181+195+203=849 packaged rows. None of these is a business-coverage or execution count.

The16 absent Console functions are13 ak.wwise.cli.* functions (addNewPlatform, convertExternalSource, createNewProject, dumpObjects, executeLuaScript, generateSoundbank, migrate, moveMediaIdsToSingleFile, moveMediaIdsToWorkUnits, tabDelimitedImport, updateMediaIdsInSingleFile, verify, waapiServer), plus ak.wwise.console.project.close/create/open. These are host-boundary rows, not unidentified Authoring APIs.

## Newly clarified scope and truly missing schema captures

Historical September exclusion was27 unique URIs /52 version rows:25 functions on2024 and27 on2025. They are known Authoring functions deliberately omitted then, not Wwise unsupported APIs. Human now includes ordinary Authoring APIs while continuing to exclude ak.wwise.ui.cli.executeLuaScript and ak.wwise.ui.cli.launch. This removes exactly four version rows from the newly required capture set. Do not change existing public Core/CLI Lua support based on this Authoring exclusion.

The minimum newly required native schema set is therefore23 schemas on2024 and25 on2025 =48 version rows /25 unique ordinary functions. Every URI below has prefix ak.wwise.ui.; all occur in both versions except noted:

- layout.dockView
- layout.getCurrentLayoutName
- layout.getElementRectangle
- layout.getLayout
- layout.getLayoutNames
- layout.getOrCreateView
- layout.getViewHandle
- layout.getViewInstances
- layout.getViewTypes
- layout.moveSplitter
- layout.removeLayout
- layout.setLayout
- layout.switchLayout
- layout.undockView
- model.createHandle
- model.destroyHandle
- model.getState
- model.registerWafm
- model.setState
- signal.emit
- window.close
- window.create
- window.present
- layout.closeView (2025 only)
- layout.resetLayouts (2025 only)

No exact version-matched schema for these48 rows exists in the inspected historical roots or packaged manifests. Shapes must not be inferred from names or old-version analogues. Capture through public waapi-schema later, with matching Authoring build/host check and referenced-definition review. Existing nine/ten core schemas, three Topic schemas each, and fixed command reflection can be reused without redundant capture.

To bind later captures to current hosts, establish getInfo/status plus bounded getFunctions/getTopics in each matching2024/2025 session, sequentially, and preserve exact build/session evidence. This also repairs the2024 inventory provenance weakness and detects drift. The old inventory is sufficient to identify known missing URIs; it is not a fresh environment attestation.

If the eventual claim requires complete independently reflected Authoring schema parity across all five versions, current evidence remains insufficient: most shared Console schemas were not separately collected on Authoring. That claim requires new reads of unproven shared schemas or another complete retained Authoring source. This is separate from the minimum48 schemas needed for the new ordinary Authoring scope. 2021–2023 URI inventories do not need historical recollection just to establish URI presence. Which host-parity claim is required remains a planning decision.

No historical schema/inventory record proves Gateway business seams, branch completion, successful mutations or verification. Business implementation/evidence remain separate obligations.

## Reusable packaged resources

- skills/waapi-skill/resources/manifest/<version>/{functions,topics,schemas,manifest,definitions}.json: complete canonical Console reflection schemas126/144/181/178/185 with zero recorded schema failures; referenced definitions included. Console provenance must remain explicit.
- authoring-ui-commands-supplement.json and authoring-ui-command-inventory.json in all five lanes: five fixed command URIs with build/digests. In2021–2023 supplement schemas/overrides are empty because reflection matched canonical commands; reflection digest records parity rather than a full original seven-call transcript. In2024/2025 five schema rows are retained. Command counts317/451/475/594/623 describe environments, never runtime allowlists.
- authoring-ui-topics-supplement.json in2024/2025: three exact Topic payloads, verified against retained raw records.
- authoring-core-supplement.json in2024/2025: nine/ten exact schemas, verified against retained raw records. Pinned canonical SHA-256 in wwise_waapi/authoring_core_manifest.py:2024 0c8ad3a286ce9c2ffcd76701c84b51629fe70e5d55f169180db142e0173f845e;2025 c6b8c815ecd0c6fe18c3a69d3dc5b500cded78ab9b57ca40a57b1a159325faa2.
- 2024.1-subscription-probe.json: one of requested two selection events, duration elapsed, unsubscribed. Not count completion/Fresh evidence.
- Core2025 probe-selected.json and probe-typed-zero-call.json: empty selection/files reads. Not nonempty-selection or mutation evidence.

## Collector compatibility

collect_authoring_core.py:33–37 always passes root --version to status and waapi-schema. Current scripts/gateway.py:3455–3464 rejects it for live commands before dispatch. Thus collector is stale and cannot run unchanged. It also covers only nine/ten core URIs, not all Authoring. Later collection requires an explicit isolated config selected through WAAPI_SKILL_CONFIG_PATH/config-set, omitting live root version override and validating detected build/version/host. No config was inspected or changed here.

Historical topic probe commands likewise pass root --version; they are evidence, not currently runnable continuations.

collect_authoring_ui_commands.py:298–346,462–464 is the explicitly allowed developer-only direct-client exception, uses --url, and does not traverse Gateway config. It performs exactly getInfo +five fixed getSchema +getCommands. It is neither a general reflection collector nor a config-only Gateway collector. Do not broaden it to the missing ordinary functions without separate review. Public Gateway status, sole getFunctions/getTopics continuations and waapi-schema remain the read-only collection path, with live host/profile selected by getInfo.

## Source context

AGENTS.md host/profile/configuration rules; tests/AGENTS.md evidence boundaries; docs/research/authoring-topic-monitoring-audit-2026-09-13.md; docs/research/authoring-core-scope-2026-09-13.md. Nothing here converts prior product exclusions into present closure decisions.

## Original file and derived URI digests

File SHA-256 identifies retained bytes as inspected, not a historical sealed attestation. URI digest uses SHA-256 of UTF-8 json.dumps(sorted(set(uris)), separators=(comma, colon)). It is distinct from packaged digest algorithms.

| Version | File SHA-256 | Functions URI SHA-256 | Topics URI SHA-256 |
|---|---|---|---|
| 2021.1 | 069cf7eca371f27cba1e0f522a717b249aebe2ac54fabf714953878c783c4aba | 5f08bdcacc1dcce9a5759b6970aad1f3fcda417f2e27e35eb171c35b9f4be0b4 | d5269073d63bd53de19bf717673cba4ceea72d330f61fa551edf674b088894e1 |
| 2022.1 | 470ba740e58ebf1154b84c53ffb77739455e0c10c13c4d77a7437eb7ef6c63b8 | 419bdf73d036f21eda7f9ba08ba8a117479b08a0c662ca2c99d5ea27172955d7 | 09915bfe7dd052e24eb9575397c4329862cccdfb91cc99e89621a6df2b26dc98 |
| 2023.1 | aaebcd7c0c1eb50e90d4d3f82cfc10185a2dabf72fa07f2d39382372d0560601 | e95948db46b5e8fe30e41ed821a6da7078116dd73e85276778f906766fecdffc | 09915bfe7dd052e24eb9575397c4329862cccdfb91cc99e89621a6df2b26dc98 |
| 2024.1 | 6a0c83eb47aa510275b7fb68ae0a0a8163930d11f71f0a4fb79051f3a3e136ed | 0df718394bafa00be46878bb6f4b0dace6bb7a9cb4695930eb5174832f43db78 | ce869f6db723f17b8eda007fb5d60557d22b80e46bceec1395a2870cad60dcd4 |
| 2025.1 | 09141a057a3cc78c0d5304be2a21ff20c731dd0de94d4a993e06fb447ddf75b8 | ae60969862b96d9c2991c8aaebc8e3c262fedd2d52a1a2ce94a309a8a543c93c | 5d7c95e893f777684fee92eec79ac304fb171bd3328ec22f7591d8838f081732 |
