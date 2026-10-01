# Music expansion investigation dispositions

Date: 2026-10-01. Scope: #119, #120, and #121 under #108. This document completes the bounded evidence review and proposes follow-up scopes; it does not claim that those issues' complete configuration acceptance criteria have passed or authorize implementation. No new Wwise, Codex, or test execution was performed for this document.

The acceptance target is structural configuration, with meaningful order and preservation, as defined in [the expansion specification](../specs/authoring-integration-expansion.md) and [the three investigation tickets](../specs/authoring-integration-ticket-proposal.md). Playback, listening, beat scheduling, and audible fade behavior receive no credit from these proposed cases.

## Evidence authority

[The capability investigation](music-capability-expansion-2026-09-28.md) records inspected metadata, fixture anchors, and the subsequent executed updates. [The read projection](music-capability-probe-results-2026-09-28.json) preserves original record digests; [the maintenance projection](music-maintenance-probe-results-2026-09-28.json) preserves narrow mutation outcomes. These are macOS Console observations on **2022.1.19 build 8584** and **2025.1.7 build 9143**, not Windows or all-build evidence.

| Evidence key | Candidate / original record SHA-256 | Exact scope |
| --- | --- | --- |
| R22 | `3781167d9c42058fa2bad06bdd6a6a37b118725a` / `c83fcc804a77ee9f95ff91252ee6440d04880c23db4305dae374eee1bdcbb19b` | Seven selected read nodes passed, four failed; no transactions. |
| R25 | Same candidate / `36aed1113faaea69309cda0e08f178261093467853606490d8a1215b5a50328d` | Eleven selected read nodes passed; no transactions. |
| L22 | `6601ab1bddc5a842afaf0951a58ac51603ce7b21` / `07cd10c0b67ae1b09b37c2136f91205ba75b76660dd6a2b3c3ad89cc5e18ddcf` | Existing item LoopCount changed 1→2, transaction `tx1-xe7p85v89rz472fz8y47`, artifact `e092d93db2d03305e9fed64a76aa02fb358ae7287b6e4cc6242a3d8c1237178b`; that node passed, the overall invocation failed on Transition. |
| L25 | Same candidate / `ed0d0a2ec75127adce97a8dc7f72ceea7e5599e86953d3e297b4443e9c657184` | Loop edit failed before a transaction; live discovery reported FIELD_DISABLED under IsLoopingInfinite. |
| T22 | #124 repair `4231c52ed929c2924c2430f1f27224cbda5f0d7e` / `c08db5a7141a449bd5ea6db883542eee4120adf114261680fb910c1265734c32` | PlaySourcePostExit true→false passed; artifact `8044120b7ce628d492800f7c8dfddb0206f873f0fafbb317b32e1251a2947111`. |
| T25 | Same repair / `d3f89466954bbc4f8bc4f0a77c75b5dd4f214287c634b61618f1cfa0ab54fdce` | Same boolean edit passed; artifact `de54c011785d012922940d8067471e8971b8d2c0d62449d9dca5244cbe88b929`; the overall invocation still failed its Loop node. |

The records show equal source before/after hashes, project mtimes, and tree metadata, with empty final scoped process lists. Failed invocations retained quarantined sandboxes. A later 2025 finite-loop dependency-read attempt resolved two meanings to the same output field and failed before loop mutation, as recorded in the investigation's executed update; the compact maintenance JSON is not a separate passing record for that attempt. No failed record is regraded here.

## Per-version disposition

“Upstream boundary” below means an observed native rejection of the particular read, not an inference that an entire feature is impossible. “Missing oracle” means that current evidence cannot independently prove the complete business outcome.

| Investigation / lane | Existing capability established | Missing complete oracle | Missing public Gateway / unresolved scope | Observed upstream boundary |
| --- | --- | --- | --- | --- |
| #119 Playlist / 2022.1 | LoopCount read (R22) and exact existing item 1→2 edit (L22). | Ordered recursive tree, each occurrence's Segment, finite/infinite state, preservation. | Playlist Root required clarification; “Segment” resolved to PlaylistItemType, not a reference. Complete arrangement construction/reordering is not exposed by a reviewed music business contract. | No proof that native Playlist authoring is impossible. The failed disclosure is a public metadata boundary. |
| #119 Playlist / 2025.1 | Root, Segment, and LoopCount reads (R25). | Same ordered-tree obligations. | Finite-loop dependency handling remains unsuccessful; later duplicate-field disclosure did not resolve it. Reference-owned/anonymous graph construction remains outside the complete business seam. | FIELD_DISABLED was observed for the selected LoopCount edit (L25); this does not prove that switching to finite loops is unsupported. |
| #120 existing Transition / 2022.1 | Three selected scalar reads (R22); exact-GUID display-identity binding and post-exit boolean edit passed after #124 (T22). | Complete source/destination context, exit/sync/cue settings, owned fade roles/values, sibling rule order. | Existing field handles may suffice for further scalar/reference edits; MusicFade role traversal, units, and dependent configuration are not proven. | None established for complete timing/fade configuration. |
| #120 existing Transition / 2025.1 | Same selected reads and post-exit boolean edit (R25/T25). | Same complete-rule obligations, including TransitionRoot ownership. | Same unresolved role/dependency scope; a fade-enable flag is insufficient evidence for fade values. | None established for complete timing/fade configuration. |
| #121 Music Switch / 2022.1 | Offline fixture has ordered ArgumentList/EntryList; that is source evidence, not executable capability. | Complete ordered group list and condition-tuple→target mapping. | No proven closed mapping disclosure or compiler for the earlier representation. | R22's attempted @Arguments and @Entries reads returned native unknown-property errors. This bounds those accessors only; alternative native support remains unproven. |
| #121 Music Switch / 2025.1 | R25 returned two argument-slot identities and nine entry identities completely. | Slots' group references, each ordered EntryPath tuple, AudioNode association, group membership, and preserved routes. | Complete mapping maintenance is not exposed. Installed AudioNode/EntryPath metadata makes an existing-entry reference edit plausible, but it has no mutation PASS here. | None established; collection existence is not full path support. |

Current code corroborates the public gaps: [owned identity semantics](../../skills/waapi-skill/wwise_waapi/object_capabilities.py), [business target normalization](../../skills/waapi-skill/wwise_waapi/business_declaration_state.py), and [object graph materialization](../../skills/waapi-skill/wwise_waapi/object_graph_business.py) do not constitute a general anonymous/reference-owned music graph contract; nested object-list composition is explicitly rejected with `OBJECT_SET_NESTED_LIST_UNAVAILABLE`. [Operation registry verification](../../skills/waapi-skill/wwise_waapi/operation_registry.py) compares generic list memberships as GUID sets, which cannot certify playback sequence or condition tuple association. Existing property/reference handles and live metadata remain the first path to investigate, rather than adding a broad music DSL.

## Complete configuration cases and oracles

These are proposed runner-materialized allow-mode cases, not executable cases in the current profile. Each requires an owned copied project, exact live identities, version-disclosed enum labels/units, complete bounded pre-state, an immutable approved Preview, durable allow authorization, at most one execution per Preview, and independent post-state. The runner must present exact selected identities to avoid ambiguities between same-named Stealth objects. No raw WAAPI request, enum number, display-path selector, or XML mutation is permitted.

### #119 / M03: ordered Playlist with repeated Segment

Use Stealth Playlist `{492A2BCA-08ED-4ED9-BDA3-B4D876D2D830}` and its three existing item occurrences. Request first→second→first Segment order, Sequence Continuous, finite loop count 2 on the first occurrence. The third occurrence references the first Segment but remains a distinct item; the original third Segment object is preserved.

Oracle: exact owner/root identity and ownership; recursive **ordered** item GUID tree; item kind; Segment GUID per occurrence; mode; finite/infinite flag and count at each relevant level; unchanged non-target items, Segment objects, sibling containers, and other references. Reject missing/extra items, duplicate item GUIDs, exchanged occurrences, or a correct unordered set in the wrong order. Returned query row order needs independent authority. If no authoritative order accessor exists, inspect the saved owned sandbox WWU read-only after a separately authorized save; its schema must be version-pinned. An order oracle remains blocked until one of those sources is proven.

Proposed prompt:

> 请直接修改已指定的 Stealth 播放列表：保留三个现有条目及根节点，让它们依次引用 Stealth_Seg_01、Stealth_Seg_02、Stealth_Seg_01，使用连续顺序模式，并把第一个条目设为有限循环 2 次。两个引用 Stealth_Seg_01 的条目必须仍是不同条目。原来的 Stealth_Seg_03 音乐段、其他条目设置、其他播放列表和音乐对象保持不变。展示预期变更后执行并核验完整条目顺序、引用和循环配置，无需播放或试听。

### #120 / M04: existing Transition configuration

Use existing rule `{B24173D4-7534-4C19-ACE0-F1F1B0EBD535}`. The proposed fixture must first seal source/destination context choices and exact Segment GUIDs, then expose those choices to the Agent. The requested source/destination are the first two Playlist Segments, not inferred display labels. Exit at source end and synchronize to destination entry; source post-exit false, destination pre-entry true; source fade-out 0.5 seconds, zero offset, linear curve. Those are intended configuration meanings, not guessed native enum/unit values.

Oracle: exact rule and owner identity; source/destination context kinds and GUIDs; exit/synchronization/cue settings; pre/post flags; each fade's role, GUID/ownership, enable state, time with attested units, offset, and curve; preserved destination fade and other fade roles; unchanged sibling rule contents **and order**; unchanged owner/root references and Segments. The existing boolean PASS covers none of the new timing/fade obligations. A dependency that requires several transactions needs an explicit ordered multi-Preview case, rather than an assumed atomic batch.

Proposed prompt:

> 请直接修改已指定的现有 Stealth Transition 规则：来源指定为 Stealth_Seg_01，目标指定为 Stealth_Seg_02；在来源音乐段结束时离开，与目标入口同步；关闭来源的 post-exit 播放，保留目标的 pre-entry 播放。启用来源淡出，时间为 0.5 秒、偏移为 0、曲线为线性。目标淡入及其他淡变设置、其他规则及其顺序、音乐段本身保持不变。展示预期变更后执行并核验完整规则配置，无需播放或试听。

### #121 / M06: preserve a complete two-condition mapping

Use `02_In-Game Music` `{A9D070F3-3BD9-49EB-9D8B-5D3312173FB4}`. Preserve argument order Music_Global then Music_inGame. Retarget only tuple `(InGame, None)` to the existing Fight `{1D0ECA1F-2749-4DBB-B92C-0DBDFDA7A825}`; preserve all other specific and group-valued routes. The 2025 existing tuple entry is `{903A30EC-F1F4-49FF-9CBC-99B89539598B}`; do not reuse that identity as a 2022 entry GUID.

Oracle: ordered argument-group GUIDs; complete tuple→AudioNode mapping; tuple width; each value's membership in the corresponding group; stable entry/slot identities where available; exact preservation of all unselected routes, group-valued routes, weights/probabilities, container references, and target objects. Reject duplicate tuples, missing/extra routes, dimension swaps, or a set of values without tuple association. Entry ordering is preserved where versioned evidence establishes it as meaningful; wildcard/priority behavior is not inferred from group-valued XML references or display names.

Proposed prompt:

> 请直接修改已指定的 02_In-Game Music：条件组顺序保持 Music_Global、Music_inGame，只把 InGame 与 None 这一组合的目标改为已指定的 Fight 音乐对象。其他组合、使用条件组本身的路径、权重和概率、现有目标对象都保持不变，不新增或删除路径。展示预期变更后执行，并逐项核验完整的条件组合到目标映射及条件组顺序，无需播放或试听。

## Smallest separate follow-up scopes

| Proposal | Minimal deliverable and dependency | Completion boundary |
| --- | --- | --- |
| Playlist finite-loop maintenance | Resolve the evidenced 2025 field dependency and duplicate-meaning disclosure using live versioned metadata; retain current field-handle operation where sufficient. Depends on precise fixture/native finite-loop evidence, not a new graph feature. | Fresh owned 2025 scalar edit, exact finite state/count, preserved fields; does not close M03. |
| Playlist complete arrangement | First prove the selected native reference/order mechanism and authoritative order readback in each lane. Add only existing-owner occurrence ordering/Segment assignment needed by M03; scope anonymous/root creation separately if required later. Extend the existing business seam and ordered verifier with fail-closed version boundaries. | Full M03 ordered graph and preservation, negative wrong-order/repeated-occurrence controls, real per-lane proof before Agent acceptance. |
| Existing Transition configuration | Build complete rule/fade role readback first; probe disclosed existing scalar/reference fields and units. Add a bounded existing-rule plan or specific fade-role traversal only where those probes demonstrate a gap. Depends on #124 identity repair and demonstrated ownership/dependency rules. New-rule creation is outside scope. | Full M04 configuration and sibling-order preservation; boolean maintenance evidence remains separate. |
| Existing Music Switch tuple maintenance | Close complete tuple readback first, prioritizing 2025 wrapper references; assess 2022's own representation independently. Reuse ordinary existing reference edit if sufficient, otherwise expose a closed existing-container, exact-tuple→existing-target business outcome. No general nested-list API, ordinary Switch assignment substitution, or new path creation. | Full M06 mapping preservation with negative dimension-swap/duplicate/omission controls; unsupported lanes get the exact demonstrated boundary. |

Each runtime extension requires separate scope agreement, version-aware Gateway schema/registry exposure, drift checks, execute-once semantics, and an appropriate verifier. The research disposition can inform #119–#121 ticket updates; closing implementation or acceptance work requires the corresponding criteria and completed evidence, and none is newly supplied by this document.
