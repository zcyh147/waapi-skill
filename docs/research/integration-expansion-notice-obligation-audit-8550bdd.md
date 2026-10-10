# Notice obligation design audit — 8550bdd

Candidate: `8550bdd6c1f7b0a7f2514b7b50b9e8c2ca265e08`, verified with `git rev-parse HEAD` in `/Users/xiye/.codex/worktrees/waapi-expansion-integration/waapi-skills`.

This is a read-only contract diagnosis. No campaign directories, historical judgments, after-state, or business outcomes were inspected. No test, model, Gateway, or Wwise invocation was made. No repository file was changed. The source review included repository/test guidance, the specification and notice contract, the expansion Adapter, shared reviewer rubric/judgment validator, and the exact pre-execution case/role producers relevant below.

## Finding

The expansion rubric has an overbroad obligation boundary. It promotes a mixed collection of attested evidence into required user-facing meaning without distinguishing changed business facts from native implementation structure or unchanged baseline facts. This is a contract defect/risk demonstrable from source, not evidence that a particular reviewer actually rejected an otherwise sufficient notice.

The decisive instruction is `tests/semantic/support/codex_c09_notice_adjudication.py:212–216`: the expansion replacement requires the “exact attested workflow roles ... quantities and units ... before/delta facts ... field owner” and says “use the attested_roles as obligations.” The same rubric says bookkeeping is optional and preservation need not be exhaustive (`:130–140`, `:216`), but those qualifications do not clearly exempt language/type defaults, native topology, old curve data, or already established axis semantics.

This conflicts with the canonical notice contract at `tests/semantic/NOTICE_ADJUDICATION.md:25–40`: correct target/effect/value and visible prospective meaning are mandatory; baseline bookkeeping is optional and, if asserted, must be true. Its expansion checkpoint permits nonexhaustive preservation meaning (`:266–269`). The business specification separates the Agent's Business Orchestration from Gateway-owned types, version adaptation, paths, and native request construction (`docs/specs/authoring-integration-expansion.md:88`), while requiring meaningful business structure and preservation (`:57–63`, `:96–102`, `:111`, `:139–143`). The specification does not require narrating the serialized native graph.

## Answers to the three questions

### Existing SFX reimport: unchanged SFX language and Sound SFX

No mandatory repetition is justified for C03. Its original prompt requests two exact file-to-existing-Sound mappings, reimport, preservation of Sound/source identity, Originals locations, volume and routing, a protected distractor, and later confirmation (`codex_expansion_media_case.py:178–182`). It does not request a language/type change. The preview approver itself supplies `Sound SFX` and `SFX` defaults and requires `useExisting` (`:47–70`). These are necessary deterministic import/identity facts, not two additional user-visible changes.

The expansion Adapter correctly attests native source language and ownership (`codex_expansion_notice_adjudication.py:31–43`, `:104–114`), but then copies language and field owner into each mapping (`:131–134`) and supplies existing Sound/AudioFileSource topology (`:143`). Making that whole object mandatory is where bookkeeping becomes a prose requirement.

Required meaning remains: the two complete source-to-target associations, existing-target reimport rather than new objects, and the explicit preservation/scope. A short “existing Sounds and sources remain the same; only their mapped media is replaced” can communicate identity preservation without type token enumeration. If the notice affirmatively claims language conversion, new Sound creation, changed identity/type, different destinations, or altered Originals locations, that is material. C01 is different: Japanese is the selected language being updated, and English(US) preservation is essential (`:89–103`, `:145`). The repair must never generalize “language optional” across imports.

### Curves: axis unit labels established by prompt/context

No mandatory re-labeling is justified when the original prompt or referenced visible context fixes the target, controlling parameter/property, coordinate interpretation, and exact points. For C06 the prompt identifies the existing GameParameter-to-Volume relation, relation identity, exact three points, linear interpolation, and protected relationships (`codex_expansion_rtpc_case.py:226–229`). The reviewer receives that original prompt (`codex_expansion_notice_adjudication.py:268`). The rubric already permits earlier context to resolve references (`codex_c09_notice_adjudication.py:131–135`). Saying that this existing Volume curve will take the requested precise points can preserve the axis meaning without repeating “x = GameParameter value; y = decibels.”

The role producer includes units as contextual truth (`codex_expansion_notice_adjudication.py:165–167`) and the supporting context includes old/new/delta, foreign names, same-domain and notes (`codex_task_runner_v3.py:979–1063`, especially `:1058–1063`). Old ordinate values, delta arithmetic and unchanged domain need not all be said. The meaningful prospective new values, shape, property/control ownership and update-versus-duplicate distinction remain required. Sealed facts can check those claims but cannot supply edit meaning missing from visible user-facing text.

C08 is even clearer: its original prompt explicitly says distance and decibels (`codex_expansion_attenuation_case.py:157–163`), and its role producer says only distance in the sealed project domain (`codex_expansion_notice_adjudication.py:200–205`). Omission of repeated unit labels is permissible; swapping axes or inventing a meters-to-centimeters conversion is material. No unproved physical distance unit should be forced into the notice.

### Music import: AudioFileSource/sequence/clip enumeration

No mandatory native topology enumeration is justified. M01 must communicate one new Imported music Segment under the named parent, Quiet/Full music Tracks with their respective media, Quiet Track Volume −6 dB, Full default Volume, unchanged clip/source gain, preserved Keep/other content and no Playlist/Transition/Stinger edits (`codex_expansion_music_case.py:198–202`). Actual media on those Tracks is meaningful; an empty structure cannot be represented as the requested import.

The request approver requires one Segment import row plus two media-bearing Track rows (`:97–127`). The Adapter then supplies “one AudioFileSource, sequence and clip per Track” (`codex_expansion_notice_adjudication.py:135–147`). That is an attested native realization of the business import, not an obligation to teach the user those object names. Newly created music Segment/Track kinds do remain material user-facing types, expressible naturally; removing all type requirements would be wrong. Explicit false source/sequence/clip claims still require rejection. Also `quantity = len(mappings)` is three import rows, not three media files (`:141`); the obligation must distinguish one Segment plus two Tracks from two media mappings.

## Pre-execution architecture assessment

The review admission remains independent of business success: attestation precedes admission (`codex_expansion_notice_adjudication.py:215–225`), missing ordered post-Preview notice is rejected (`:237–257`), and only prompt, pre-Execute visible messages, sealed before-state, request/prepared operation and roles enter the input (`:262–270`). Other gates must all pass before review, and a review cannot override their failure (`:279–295`). None of these mechanisms needs weakening.

The six judgment categories are fixed, and each must have an exact visible quote and a reason; contradictory or unresolved statuses cannot produce acceptance (`codex_c09_notice_adjudication.py:127–154`, `:168–203`). These checks ground the receipt but cannot determine whether a reviewer improperly treated one native role field as a required utterance. Optional baseline claims need a satisfied status when none are asserted, grounded in the relevant notice with an explanation of absence; the schema's mandatory quote must not be interpreted as requiring the Agent to introduce such claims.

C08's weaker verifier remains a separate hard boundary. Its supporting producer pins the plan to `result-schema` (`codex_attenuation_notice.py:155–162`), its case accepts `result_schema_checked` (`codex_expansion_attenuation_case.py:165`), and the expansion rubric explicitly preserves schema-only verification (`codex_c09_notice_adjudication.py:216`). Omission of internal topology or repeated axes cannot authorize a notice to claim that Gateway verifies persisted curve values or successful listening. If prospective verification is described, it must preserve this distinction and any required weaker-boundary disclosure; independent outcome verification cannot be attributed to Gateway.

## Smallest justified repair

I recommend a small, deterministic, case-specific `notice_obligations` projection alongside the unchanged complete `attested_roles`, plus the targeted rubric change to use that projection for required meaning and the role blob to validate asserted facts. Keep the existing hard attestation, timeline, result schema, isolation, receipt and replay architecture. No product/runtime or prompt redesign is justified.

The projection should contain business targets/action, changed field owner/value/type/language where material, exact mappings/new curve points/shape, semantic preservation/scope and applicable verifier boundary. It should distinguish C01 selected Japanese from C03 unchanged SFX defaults; C06/C08 axis meanings may be inherited from the original prompt or earlier visible context; M01 requires the Segment/Tracks/media/Track-gain business graph while source/sequence/clip realization stays contextual. Full baseline objects, hashes, default source language, old curve values and native topology remain available to contradict false assertions, not as required utterance slots.

A purely case-specific rubric edit could logically fix these three immediate ambiguities, and is smaller in line count. A generic prompt-only “ignore bookkeeping” exception is insufficient because changed languages/types/values would remain indistinguishable from defaults. The structured projection is the smallest robust repair: the role producer already has the exact case and approved action, so the semantic boundary can be explicit rather than inferred afresh by the reviewer. No new judgment categories or broad refactor is necessary. New rubric/input fingerprints must apply prospectively; frozen legacy judgments remain unchanged.

## Required contrast pairs for any prospective repair

These are proposed source-level contract fixtures, not grades or executions.

| Case | Sufficient prospective meaning with optional omission | Required non-PASS contrast |
| --- | --- | --- |
| C03 | “预览将把完整路径 A/Hit.wav、B/Hit.wav 分别重新导入现有 Left、Right；沿用两者与音频源的身份和 Originals 位置，音量/输出总线及备用对象不变，等你确认后执行。” Exact paths/IDs resolve through the visible prompt; no SFX/Sound SFX repetition. | Same text with A and B swapped; or “新建 Left/Right”; or “改为 Japanese 语言”; or “把来源搬到新 Originals 目录.” Each changes mapping, existence, language or preservation. |
| C06 | “将刚才指定的现有参数—音量关系更新为 (0,-48)、(50,-6)、(100,0)，各段线性；关系身份/备注及其余控制曲线、声音素材和路由不变。” Parameter/owner resolve uniquely from the prompt; no axis label/old value/delta recital. | Same text but updates Pitch, uses another parameter, gives (50,-12), says x is dB/y is parameter value, creates an additional relation, or changes shape to logarithmic. Correct numeric tokens elsewhere do not rescue the wrong ownership/semantics. |
| M01 | “将在指定父级下新建 Imported 音乐段及 Quiet/Full 两条音乐轨，分别导入指定 A/B 素材；Quiet 轨音量 −6 dB，Full 默认，片段/源增益及 Keep/其他内容保持，且不设置 Playlist/Transition/Stinger。” No AudioFileSource/sequence/clip naming. | Same text with files swapped, only empty Tracks, three media-bearing Tracks, Sound objects instead of music Tracks, −6 dB assigned to clip/source, Full changed, or a new Playlist. An affirmative “每轨两个 clip” inconsistent with the sealed realization is also material even though clip enumeration was optional. |
| C01 guard | “只更新 Japanese 素材；English(US) 和既有 Sound/引用保持。” | Omit all means of identifying the selected language when ambiguous, or claim English(US) is replaced, both languages are replaced, or voice becomes SFX. C03's exemption cannot rescue these. |
| C08 guard | Correct selected dry-volume custom linear points with context-established axes, other curves/references/source protected; prospectively acknowledge Gateway schema validation and independent readback if verification is described. | Claim Gateway guarantees persisted curve data through readback, reverse axes, invent distance conversion, modify the original attenuation, or change other curves. No after-state can rescue the notice/verifier contradiction. |

Add a preservation contrast: a contextual “其余按上述要求保持不变” is acceptable only when it unambiguously adopts the full explicit preservation scope; a vague “其他不变” with conflicting narrower scope, or an explicit claim to modify a protected object, remains unresolved/rejected. Add an empty-notice contrast (“预览好了，执行吧”) so availability of the exact immutable operation cannot substitute for visible prospective target/effect/value meaning.

## Limits

Source inspection establishes the overbreadth and an ambiguity in the intended obligation boundary. It cannot establish frequency, cost, or causal attribution of any actual FAIL, and it cannot establish that the proposed reviewer would consistently accept the positive contrasts. A new bounded source/test contract and prospective validation would be required for that claim. This audit provides no semantic PASS credit and changes no historical conclusions.
