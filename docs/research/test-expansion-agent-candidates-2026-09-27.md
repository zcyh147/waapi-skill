# Agent 业务集成扩展：17 个候选的第一阶段审计

日期：2026-09-27。只读审计基线：`284899536fc469cecf075643d3942ddc3f98d04e`。
本次只新增本文，不运行测试、Fresh Codex、Wwise 或 live Gateway，不修改 runtime、suite、fixture 或既有证据。
下文是案例设计和实施前置条件，不是新增 PASS，也不是用户对工程修改的授权。

## 结论与计数口径

17 是保留追踪身份的候选数，不是 17 个可执行案例。此前没有正式 ID，本次固定为 C01–C11、M01–M06；音乐 Segment 搬迁沿用通用搬迁位置 C10，不再在音乐组重复计数。

各案例下的第二版本是可考虑的验证方向，不是全部排入首轮。经总预算取舍，首轮具体调度以[总计划的版本与主机表](test-expansion-plan-2026-09-27.md)为准：七个主版本案例，仅优先增加 C09/M01 的 2022.1 Fresh 单元，其余版本首先复用或补充 program/real Gateway 证据。

| 状态 | 数量 | ID | 含义 |
| --- | ---: | --- | --- |
| 保留正式设计 | 7 | C01、C03、C06、C08、C09、M01、M05 | 已找到相关公共路径及可具体设计的状态 oracle；仍须实现/封存 fixture、adapter 和审计规则，才可执行 |
| 合并已有案例 | 2 | C02、C05 | 基础题意已被 integration/compound 覆盖；仅把有明确新义务的增量加入既有案例修订，不默认新增 fresh task |
| 待能力或 oracle 验证 | 4 | C07、C10、C11、M02 | 局部接口存在，但完整题意的公共读取、状态约束或独立验收尚未闭合 |
| 本轮能力门槛阻塞 | 4 | C04、M03、M04、M06 | 不能把有限返回/对象存在判成完整业务成功；不表示底层 Wwise 一概不支持 |

首批三个试点固定为 **C01 多语言对白、M01 音乐导入、C06 已有 RTPC 更新**。先各设计一个 Wwise 2025.1 的小案例，验证公共路径和独立 oracle，再进入现有正式 Fresh harness。选 2025.1 是首轮设计范围，不授予其他版本或 Windows 证据。三例后续优先补 2022.1；M05 已有 Stinger Trigger 修改列为下一项，正向先 2025.1 后 2023.1，而 2021/2022 保留真实 metadata 不暴露引用的边界。

“保留正式设计”的 7 例不是 runnable 7/7：目前本次新增可执行案例为 0。C10 的引用保持 oracle 未闭合，因此单列 conditional，不得仅凭 move 成功进入业务 campaign。C02/C05 只合并到新修订 profile 的设计，不默改或重贴历史 frozen suite 的证据。

不能把每个字段、行为义务、操作步骤和 fresh task 混用。一个 workflow 可以包含 3–5 个业务步骤、多个独立状态断言和多次分别预览的事务；涉及不同前态的冲突分支则应分成不同 fixture 变体。最终调度数由实际冻结的 workflow × 适用版本 × 主机决定，本文不估算 passing 数或给出统一乘五的执行总数。

## 证据与去重基线

以当前源代码为事实入口；较早研究文档只用于说明能力边界和历史，不能替代当前公共 contract、测试实现或已完成运行记录。

| 来源 | 当前可核对范围 | 对本次去重的影响 |
| --- | --- | --- |
| [integration V1 workflows](../../tests/semantic/data/integration-workflows-v1/workflows.json) | Weather：批量层级/导入、逐 Sound 字段、Action 时间、RTPC；Alarm：Event→Action→Sound→Source→Bus 诊断与路由修复；Harbor：SoundBank 发布 | 普通默认值/逐行例外、单对象 OutputBus 修复、从零加 RTPC 不应换题名重算 |
| [integration V2 workflows](../../tests/semantic/data/integration-workflows-v2/workflows.json) | Rifle：已有媒体更新＋新增、身份/声音设计/引用保持；Footsteps：普通 Switch assignment 维护；Weapons：查询筛选后的批量修改和清理 | 同目标 reimport、普通 Switch assignment、简单筛选批量 Volume 已有题型；不代表多语言、MusicSwitch 或内嵌音乐对象已覆盖 |
| [object-heavy recipes](../../tests/semantic/support/codex_object_heavy_v3.py) | `_create_01`–`_create_05`、`_set_01`–`_set_05`、`_get_01`–`_get_05` 的 runner-owned prestate、expected rows 和 cleanup | generic object 图、冲突、批量字段和查询已有专门 recipe；是否已有 exact branch 应逐 recipe 比对，不能只按 URI 判断 |
| [compound audio](../../tests/semantic/data/compound-heavy-v1/audio-import.json)、[compound object](../../tests/semantic/data/compound-heavy-v1/object-create-set.json) | 默认值＋单行例外、混合已有/新对象、merge/rename 冲突、已有分支保持、三个对象不同值 | C02 高度重复；C03 只保留不同输入目录同 basename、身份消歧等确有新验收点的部分 |
| [compound profile](../../tests/semantic/data/compound-heavy-v1/profile.json) | 定义 12 个 logical cases，2022/2025 共 24 tasks | 定义数量本身不是完成证据；不能把本次候选归入该已冻结 profile |
| [compound Undo profile](../../tests/semantic/data/compound-undo-business/profile.json)、[real Undo test](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L2668) | Fresh 专项为两个 checked child 合一个最终 preview、不执行；真实测试另验成功、取消、不可重试 | 新场景使用多个事务不等于新 Undo 覆盖；不得将取消误写为业务状态已回滚 |
| [TEST_INVENTORY](../../tests/TEST_INVENTORY.md) | exact candidate/root/host 的历史已完成证据；包含 heavy 子集、public integration 与专项 | 本次不修改其数字；V3 剩余 review definitions、测试文件存在和历史 PASS 都不自动成为新候选 PASS |

后续实现仍使用既有 Fresh campaign/matrix、独立沙箱与 sealed business oracle，不建立第二套语义 harness。下面的“独立 oracle”指 runner 在 Agent 开始前封存预期值和保持项，结束后独立查询/检查文件；不能只检查 Agent 自述、preview 请求或 Gateway 自己的 `verified` 字符串。

## 所有候选共同采用的协议

业务提示只给用户能理解的目标、精确路径/GUID、素材清单、语言/平台名和保持要求，不夹带 native args/options、enum 数字或自写代码。占位符由 runner-owned fixture 填充，不让 Agent 从磁盘猜测素材或 fixture。

下列 prompt 是业务正文，policy 后缀在冻结案例时另行确定，不默认所有案例 ask。C01 采用 `ask_before_changes`，附加“先读取并核对当前状态，展示变更预览，等我确认后再执行”；后续确认必须是**新用户 turn**，只绑定当前 immutable preview。M01/C06 采用 `allow_changes`，附加“这是要实际完成的修改，请核对当前状态、告知变更并完成执行和核验；不能表达或不能核验的部分请明确说明”。allow 案例必须由清楚的修改请求获得独立、持久化的 policy authorization，不能仅凭配置值、设计请求或旧确认执行。其余候选的 mode 在 profile 冻结时决定。

任何多事务案例都先完成当前执行/核验，再进入下一 immutable preview；使用 ask 时每笔均有后续明确确认，使用 allow 时每笔均遵循 Gateway 的独立授权绑定。fixture setup 不计 Agent 主业务事务，但需另记实际 lifecycle/成本。

每例都要检查目标精确集合、GUID/parent/reference、明确保持项、source-project 不变、一次执行、最终事务状态及清理。普通 property/reference 的已验证状态、`result_schema_checked`、能力阻塞和基础设施阻塞分账。需要听感或时序验收的题目不能拿对象结构 readback 代替。

## C01 多语言对白：只更新指定语言

**状态/Priority：保留正式设计 / P0，试点 1，ask。** 版本建议 2025.1 后 2022.1；其他 lane 单独扩展。

- **中文 prompt 草案：**“`{voice_sound}` 已有中文和英文对白。请用 `{zh_replacement}` 只更新中文版本，英文素材与语言关联保持不变；沿用现有声音对象，音量、输出总线、事件播放目标也不变。完成后分别说明两种语言实际关联的素材。”
- **Prestate：**同一 Sound 有两个已知语言的不同 hash 媒体；固定 Event/Action；另设近似名称 Sound。语言名来自 fixture 的实际项目 inventory。
- **目标/保持项：**中文文件内容匹配输入；Sound GUID、英文源身份/路径/hash、非目标语言、routing、Action Target 与 distractor 不变。不要预设 reimport 一定保留被替换 AudioFileSource GUID，除非该分支已被证明。
- **Public 路径：**`query-object`→`draft-start audio.import`→已有 Sound/语言业务声明→preview/execute/verify；无额外自写 native language 请求。
- **验收与去重：**区别于 Rifle 的单语言 reimport。可借鉴 `test_voice_languages_reimport_preserves_other_language_and_sound_identity`，但新增 Fresh 业务题仍需自己的双语言 oracle 和协议审计。[声音 workflow 测试](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L603)、[import verifier](../../skills/waapi-skill/wwise_waapi/operation_registry.py#L17300)。

## C02 批量默认值与例外

**状态/Priority：合并已有案例 / P2。** 版本建议沿用被修订案例的 2022.1/2025.1。

- **中文 prompt 草案：**“把 `{target_list}` 的默认最大播放实例数设为 5，其中 `{exception}` 设为 2；它的近景总线保持专用，其他声音统一使用 `{default_bus}`。未列出的声音不要修改。”
- **Prestate：**有公共值、不同例外值和未选对象；如果作为 import 变体，素材、已有对象与新增对象均预先固定。
- **目标/保持项：**逐 GUID 期望值，不仅检查默认值；未选对象及例外 routing 保持。字段存在不等于 instance-limit 开关依赖正确，必须分别检查启用、忽略父级和数值。
- **Public 路径：**已存在批量对象用 `object.set` business row；导入场景用 `audio.import` defaults＋逐行业务值，不混淆两种入口。
- **验收与去重：**compound audio 已明确“默认 5，Rifle_Close 2 且专用总线”；Weather 也逐 Sound 指定数值。不另开同义 fresh case。只有新增“筛选后仅子集＋例外优先级”义务才修订原 fixture/断言。[compound audio](../../tests/semantic/data/compound-heavy-v1/audio-import.json)、[object.set contract](../../skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py#L165)。

## C03 同名素材与对象冲突

**状态/Priority：保留正式设计，先去除重叠变体 / P1。** 版本建议 2022.1/2025.1。

- **中文 prompt 草案：**“`{near_file}` 与 `{far_file}` 都叫 impact.wav，但分别属于近景和远景。按给定完整路径分别更新 `{near_sound}`、`{far_sound}`，不要按文件名合并，不要修改 `{decoy_sound}`，也不要创建带编号的重复对象。”
- **Prestate：**不同目录、相同 basename、不同 hash；两个精确目标和同名/近似名 distractor；如果目标身份不够明确，保留用户选择 turn。
- **目标/保持项：**目标→输入 hash 一一匹配，目标 GUID 集不变，无额外对象，decoy 原样。不能用“两个对象存在”替代媒体对应关系。
- **Public 路径：**bounded business query→如用户从多个候选选子集则逐选中 GUID exact-ID readback→`audio.import` 已有对象业务声明。`draft-declare-import-batch` 每次只有一个 media directory，filename 必须是 leaf；两目录必须在同一 Draft 分两个声明 chunk，第二个显式指定自己的 media directory，不把绝对路径塞入 filename。最终能否合成一个 preview 由 fixture/adapter 的累计声明检查确认，不在此伪报已运行成功。[batch directory/leaf guard](../../skills/waapi-skill/scripts/gateway.py#L15574)。
- **验收与去重：**Rifle 已覆盖精确已有对象 reimport；compound/heavy 已覆盖 object merge/rename 冲突。新义务仅为相同 basename 的不同输入身份与混淆保护；create/merge/replace/rename 不在一条 prompt 中全塞。[选择 gate](../../skills/waapi-skill/scripts/gateway.py#L21907)、[compound object](../../tests/semantic/data/compound-heavy-v1/object-create-set.json)。

## C04 Dialogue Event 关联

**状态/Priority：完整业务验收能力阻塞 / P3。** 当前不安排业务成功 campaign；有限 directive 行为另列边界题。

- **中文 prompt 草案：**“按 `{dialogue_mapping}` 导入对白并关联 `{dialogue_event}`；先确认当前 Skill 能否读取并核对每项关联，无法完整核验时不要把导入成功当作关联成功。”
- **Prestate：**固定 Dialogue Event、参数/路径映射和既有关联快照；不能把普通 Event 的 Action/Target fixture 当成 Dialogue 决策树。
- **目标/保持项：**最终关联/决策结构与映射完全一致、旧关联保持；这套独立 oracle 尚未证明。
- **Public 路径与边界：**audio-import business 暴露 `dialogue_event_directive`；存在 directive 时 verifier 明确降级为 `result_schema_checked`、`business_state_verified=False`，理由是 side effect 未完整重建。
- **验收与去重：**保留 ID，先审定真实可读关联结构、版本差异及 runner oracle。可以考核 Agent 如实说明边界，但边界通过不得记成 Dialogue 功能通过。[import business 字段](../../skills/waapi-skill/wwise_waapi/audio_import_business_contracts.py#L23)、[directive boundary](../../skills/waapi-skill/wwise_waapi/operation_registry.py#L11538)、[verifier 降级](../../skills/waapi-skill/wwise_waapi/operation_registry.py#L17355)。

## C05 总线路由与继承

**状态/Priority：基础题合并 Alarm；继承增量待独立义务闭合 / P2。** 版本建议 2022.1/2025.1。

- **中文 prompt 草案：**“先核对 `{event}` 的播放链和 `{parent}` 下几个声音的输出设置。只让 `{override_sound}` 使用 `{special_bus}`，其余继续按现有父级设置工作；不要修改声音内容、音量或事件目标。”
- **Prestate：**明确已覆写与未覆写的 sibling、parent routing、正确/错误 bus；不要让 Agent 自己推导 runner 未固定的继承前态。
- **目标/保持项：**OutputBus reference、override 开关、parent/sibling 与完整 Event/Action/Source 关系。若题意要求“最终实际听到哪个 bus”，须另有可验证的有效路由证据，不能只凭一个 reference。
- **Public 路径：**`event-actions`、`sound-routing-diagnostics` 读取；live field discovery 后 `object.setReference`/`object.setProperty`，每个独立事务正常预览。
- **验收与去重：**Alarm 已覆盖单 Sound OutputBus 修复及非目标保持；Weather 已设置批量 bus。仅继承/override 交互为增量；无明确新 oracle 时不另建题。[Alarm definition](../../tests/semantic/data/integration-workflows-v1/workflows.json)、[query presets](../../skills/waapi-skill/scripts/gateway.py#L8319)、[output_bus compiler](../../skills/waapi-skill/wwise_waapi/object_graph_business.py#L559)。

## C06 更新已有 RTPC，保留其他曲线

**状态/Priority：保留正式设计 / P0，试点 3，allow。** 版本建议先 2025.1，再 2022.1；2021.1 是 unavailable boundary。

- **中文 prompt 草案：**“`{sound}` 已有 `{parameter}` 控制音量的曲线。只把这条曲线改为 (0,-48)、(50,-6)、(100,0)，各段线性；保留这条控制关系的身份和其他控制曲线，声音、素材、路由均不变。”
- **Prestate：**相同 property＋ControlInput 的现有 RTPC 已存在，另有不同 ControlInput/属性的 RTPC；封存 GUID、points、notes 和完整列表。
- **目标/保持项：**命中恰好一条并保留 GUID；完整 GUID 集不变；其他行逐项相等；精确曲线和可选 notes 正确。选择 add-or-update 但从空列表开始不算 update 覆盖。
- **Public 路径：**exact Sound/ControlInput binding→field discovery→`object.setRTPC`、`draft-declare-rtpc` 的 add-or-update。
- **验收与去重：**Weather 已有 RTPC 步骤，但新题固定真正 update 前态并检查 sibling preservation。现有 RTPC lifecycle 测试有该分支；新 Fresh 增量是 Agent 正确发现、识别已有关系和保留项。[RTPC contract](../../skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py#L99)、[state verifier](../../skills/waapi-skill/wwise_waapi/operation_registry.py#L17180)、[lifecycle test](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L3234)。

## C07 State 属性维护

**状态/Priority：待完整公共路径和 oracle 验证 / P2。** 版本建议 2025.1；公开 setStateGroups/setStateProperties 从 2023.1 起。

- **中文 prompt 草案：**“为 `{owner}` 保留 `{existing_state_group}`，增加 `{new_state_group}`，并把音量纳入 State 可控制属性；已有组和未指定的可控制属性都保留。先报告哪些内容能完整读取并核验。”
- **Prestate：**已有 State Group 引用列表和 State-property 列表，至少一个保持项；不把 SoundEngine 当前 State 当成 Authoring 配置。
- **目标/保持项：**两个列表的完整预期状态。暂不扩成“为每个 State 配置独立音量值”，因为这不是现有两个声明的同义操作。
- **Public 路径：**exact Core business `setStateGroups` / `setStateProperties`，business object/field handles；当前通用 verifier 为 result-schema。
- **验收与去重：**须先证明版本对应的 list/embedded readback、完整集合及保持项。接口存在不抵业务 PASS；不凭空构造 State 私有结构。[Core contracts](../../skills/waapi-skill/wwise_waapi/core_business_contracts.py#L107)、[Core compiler](../../skills/waapi-skill/wwise_waapi/core_business.py#L420)、[generic verification](../../skills/waapi-skill/wwise_waapi/operation_registry.py#L4328)。

## C08 衰减曲线维护

**状态/Priority：保留正式设计 / P1。** 首选 2025.1，再验证 2022.1；public curve route 五版本都有。

- **中文 prompt 草案：**“只修改 `{attenuation}` 的声音干声音量衰减曲线，使用清单 `{distance_volume_points}`；低通、扩散等其他曲线和使用这个衰减的声音引用保持不变。报告实际保存的曲线点，不评价听感。”
- **Prestate：**至少两条不相同曲线、一个引用此 Attenuation 的 Sound；固定 curve source 与平台视图，points 来自有序 runner 输入。
- **目标/保持项：**目标曲线 use/points 精确匹配，非目标 curves 与引用保持；不以“远处更安静”替代数据 oracle。
- **Public 路径：**`metadata attenuation`→Core business `setAttenuationCurve`→独立 metadata readback。
- **验收与去重：**cross-family 的 attenuation copy/rename/delete 不等于 curve 编辑。写操作的 result-schema verification 需要额外曲线 oracle。[Core contract](../../skills/waapi-skill/wwise_waapi/core_business_contracts.py#L11)、[Gateway attenuation result](../../skills/waapi-skill/scripts/gateway.py#L14180)、[existing lifecycle](../../tests/destructive/test_cross_family_lifecycle.py#L196)。

## C09 追加效果器并保留已有项

**状态/Priority：收窄后保留正式设计 / P1。** 2022.1 固定 slot 与 2025.1 EffectSlot 分开设计；2021.1 unavailable。

- **中文 prompt 草案：**“在 `{owner}` 上增加一个名为 `{new_gain}` 的 Wwise Gain 效果器，设置 `{gain_value}`；已有两个效果器及其参数、对象身份和绑定都保留。不要替换已有效果器，也不要重新排列它们。”
- **Prestate：**已有两个不同参数、已记录 GUID/绑定的 effect；2022 fixture 留有至少一个 proven-empty slot，另外设计满 slot 边界时不计成功变体。
- **目标/保持项：**新增一个正确 plugin/slot binding，全部旧 slot/effect GUID、绑定、请求保持的属性不变。完整播放处理顺序和听感不在本例证明范围。
- **Public 路径：**`object.createPlugin`＋live type/field handles；2022 首个空 Effect0–3，2023+ append EffectSlot；不提供“任意插入/重排”任务。
- **验收与去重：**真实 cross-family test 已连续追加两项并检查旧 bindings，明确 `not_audible_order`。Fresh 只增加自然语言→发现→正确追加的 Agent 证据，不能再声称新的 native 功能覆盖。[plugin rules](../../skills/waapi-skill/wwise_waapi/operation_plugin.py#L8)、[cross-family effects](../../tests/destructive/test_cross_family_effects.py#L55)。

## C10 音乐 Segment 搬迁与引用保持

**状态/Priority：待引用 oracle 验证 / P1。** 先 2025.1，再 2022.1；不在 M 组复制。独立引用保持未证明时，本例保持 conditional。

- **中文 prompt 草案：**“把 `{segment}` 移到 `{destination_music_container}`，保留 Segment 和其下 Track/媒体的身份；`{reference_owners}` 对这个 Segment 的现有引用也要保持。目标父级其他内容不变，不改播放编排或 Transition。”
- **Prestate：**合法源/目标 music containers、一个带已知 Track/media 的 Segment、至少一种经能力验证可读取的现有引用。不要通过尚未证明的 Playlist/Stinger 创建来制造 fixture。
- **目标/保持项：**Segment GUID、子图身份/媒体、引用 owner GUID→Segment GUID 不变；parent/path 改变；旧路径不再解析为原对象，目标 sibling 集保持。
- **Public 路径：**bounded query/relationship 或已披露 advanced read→`object.move`→exact-ID 读回。搬迁能力和引用保持分别评分。
- **验收与去重：**`test_cross_family_music_segment_move_between_music_containers` 已证明层级 ownership，明确不证明 playlist/transition/playback；其 fixture 是新建空 Segment，没有本例引用 oracle。先选一种已证可读取的 reference 类型，不能泛称“所有音乐引用已保持”。[music move test](../../tests/destructive/test_cross_family_lifecycle.py#L221)、[move verifier](../../skills/waapi-skill/wwise_waapi/operation_registry.py#L16965)。

## C11 平台差异与 link/unlink

**状态/Priority：待双平台值 oracle 闭合 / P2。** 首选 2025.1；setLinked/isLinked 仅 2023.1–2025.1。

- **中文 prompt 草案：**“`{owner}` 的音量目前跨平台联动。只在 `{target_platform}` 取消联动并改为 `{target_value}`，其他平台的数值保持；最后分别报告该字段的联动状态和能核实的实际值。”
- **Prestate：**两个实际存在平台、link 状态和两侧初值已封存；目标是支持 unlink 的 live-discovered field，不能任意选属性。
- **目标/保持项：**目标平台 unlinked＋目标值，另一平台值和链接关系按明确预期保持。可另列 relink 变体，但 relink 后的值传播语义要先实测固定。
- **Public 路径：**平台封入 `draft-discover-fields` handle→`object.setLinked`→`object.setProperty`；`core-call isLinked` 有独立读路径。
- **验收边界：**普通 query-object 没有已证明的双平台 property-value view；`metadata property-state` 返回 enabled，不是当前属性值。需审定 runner-owned 双平台 oracle，不能让 Agent 自造 object.get options。当前只能保证 link-state 路径有代码依据。[metadata compiler](../../skills/waapi-skill/wwise_waapi/object_metadata_business.py#L197)、[isLinked public read](../../skills/waapi-skill/scripts/gateway.py#L11315)、[property-state result](../../skills/waapi-skill/scripts/gateway.py#L14126)。

## M01 音乐导入与媒体 owner

**状态/Priority：保留正式设计 / P0，试点 2，allow。** 先 2025.1，再 2022.1；五版本差异不以同一 wire topology 预设。

- **中文 prompt 草案：**“把 `{music_files}` 导入 `{music_parent}`，建立 `{segment_name}`，并按清单建立两个 Music Track。每条 Track 对应清单中的一条素材；只把 `{quiet_track}` 的 Track 音量设为 -6 dB。保留父级其他内容，不设置 Playlist、Transition 或 Stinger。”
- **Prestate：**合法 MusicPlaylistContainer/MusicSwitchContainer parent；两个 hash 可区别的文件；同名 distractor；必要的已存在兄弟 Segment。
- **目标/保持项：**Segment→Track→Wwise 生成的 Source/Sequence/Clip owner 关系准确，媒体 hash 与行映射一致；Track 的 Volume 不误写到 Clip/Source，父级/兄弟不变。不要求 Agent 手工创建受禁嵌入类型。
- **Public 路径：**music business kinds、`audio.import` music declarations；同一次导入中声明 Track 的 `volume_db`，不为了该字段另加事务；query/advanced 只读检查已生成内嵌对象。已有 `test_closed_music_import_media_and_track_volume` 正是一次导入包含 Track 音量的具体实现。
- **验收与去重：**已有真实 `test_closed_music_import_media_and_track_volume` 和结构/owner probe 可复用证据方法；Rifle/Weather 的 Sound import 不代表 music owner 路径。新题仍须独立 Fresh adapter。[music tests](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L514)、[media＋Track Volume](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L571)、[semantic music kinds](../../skills/waapi-skill/wwise_waapi/business_declarations.py#L292)。

## M02 已有 Track/Clip/Source 分层属性与 Track 模式

**状态/Priority：先能力验证 / P2。** 首选 2025.1，其他版本分别核 metadata，不生成全版本成功清单。

- **中文 prompt 草案：**“在现有 `{track}` 中，把 Track 音量设为 `{track_volume}`，只把 `{clip}` 的片段音量设为 `{clip_volume}`，源对象其余属性不变；另核对该 Track 是否能安全改为顺序步进模式。不能证明会保留当前片段结构时，先说明限制，不重建 Track。”
- **Prestate：**有至少两个 clip、明确 source/owner 关系和非默认值的已填充 Track；模式改变与 scalar 编辑先拆成独立变体，避免一例同时跨两个未知边界。
- **目标/保持项：**Track 与 Clip 的不同 Volume scope、Source 保持；模式变化若执行须证明 GUID、完整 clip/sequence 关系和其他模式依赖字段。不可只检查 MusicTrackType 数值。
- **Public 路径：**精确 existing-object binding＋live field discovery→普通 `object.setProperty`。当前不假定 invisible Clip field 一定会被公开发现，也不把 native metadata 名直接写入 mutation。
- **验收边界：**已有源研究证明 Track mode 不是不可变 Class ID，Clip 确有 Volume；但这不证明当前 Skill 完整编辑路径和 populated mode transition 保持。先做 disposable capability probe，再决定是否拆为两个正式案例。[music factcheck](music-primary-factcheck-2026-09-14.md)、[field metadata revalidation](../../skills/waapi-skill/wwise_waapi/business_declarations.py#L1210)。

## M03 Playlist 编排

**状态/Priority：完整编排能力未证明，本轮阻塞 / P3。** 不预定可执行版本；从 2025.1 小能力探针开始。

- **中文 prompt 草案：**“让 `{playlist}` 按 A→B→A 的顺序播放 `{segment_a}` 和 `{segment_b}`，按 `{repeat_policy}` 重复；先核对是否能通过当前 Skill 建立并完整读取这个有序编排，不能时不要用空容器代替。”
- **Prestate：**两个 existing Segment 和真实 MusicPlaylistContainer；有序树、重复规则及旧项保持策略必须被 runner 明确固定。
- **目标/保持项：**MusicPlaylistItem 树、引用、位置、repeat/loop 规则和非目标条目。成员集合相同不等于顺序正确。
- **Public 路径与缺口：**container query/create/import-parent 已有路径；完整 PlaylistRoot/MusicPlaylistItem construction 不因此成立。不要误把普通 `PlaylistSlot` 当作 music playlist item。
- **验收边界：**历史修复仅证 parent/create；完整编排未到可接受状态。有序 readback 和必要的 bounded playback 场景须单独设计；不重用 generic object list set equality 当顺序 oracle。[complex music review](music-complex-feature-risk-2026-09-14.md)、[container-only test](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L674)。

## M04 Transition 维护

**状态/Priority：完整规则维护未证明，本轮阻塞 / P3。** 先 2025.1 existing-rule 探针，不预设新规则创建可行。

- **中文 prompt 草案：**“只调整 `{transition_rule}`：从 `{source_segment}` 转到 `{destination_segment}` 时，按 `{exit_rule}` 退出并以 `{fade_rule}` 进入；其他 Transition 规则和优先关系保持。先读取原规则，不能完整表达或核对时停止在说明阶段。”
- **Prestate：**existing Transition root/rule、至少一个非目标规则、source/destination/context 与 fades/cues 固定；题面每项有明确业务含义，不能让 Agent 猜 enum。
- **目标/保持项：**精确 rule graph/引用、规则选择顺序、fade/cue/scheduling 依赖；数据 readback 与播放行为分账。
- **Public 路径与缺口：**existing-rule discovery 有历史观察；完整请求的 metadata 选择、嵌套字段、更新能力和 oracle 均未证明。不能宣称所有 Transition 不支持，也不能将单个 scalar 修改判作完成规则维护。
- **验收与去重：**Event Action FadeTime/Delay 的 Weather 覆盖不能转给 music Transition。先完成能力探针，随后才冻结业务 prompt。[complex music review](music-complex-feature-risk-2026-09-14.md)。

## M05 已有 Stinger 的 Trigger 修改

**状态/Priority：保留正式设计 / P1，三个试点后的下一项。** 正向先 2025.1、再 2023.1；2021/2022 仅保留 metadata 不暴露引用的边界案例。

- **中文 prompt 草案：**“把现有 `{stinger}` 的触发器从 `{old_trigger}` 改为 `{new_trigger}`。沿用这个 Stinger，它关联的 `{segment}` 和其他设置保持不变；不要新建 Stinger，也不要改 Segment。”
- **Prestate：**已有 Stinger、old/new Trigger、固定 Segment；identity 可能是空 name＋派生 bracketed display path，必须绑定 exact GUID 而非伪造路径。
- **目标/保持项：**Stinger GUID/type 保持，Trigger 指向新 GUID，Segment reference 和未指定设置原样；不宣称触发后的节拍/播放时序已验证。
- **Public 路径：**`query-object --exact-id`＋`--include-field`→`object.setReference` 的 live discovered field handle→独立同对象回读。
- **验收与去重：**当前 `test_cross_family_existing_stinger_versioned_reference_boundary_and_change` 已有 2023–25 mutation/readback 路径，2021/22 显式检查引用不暴露。因此不能沿用 9/14 文档中“仅 preview”的旧结论；新增的是 Fresh Agent 的派生身份/引用维护能力。该测试实现不是本次新运行证据。[existing Stinger test](../../tests/destructive/test_cross_family_derived_identity.py#L135)、[independent read](../../tests/destructive/test_cross_family_derived_identity.py#L122)。

## M06 Music Switch 路径维护

**状态/Priority：完整路径维护未证明，本轮阻塞 / P3。** 先分别审 2022.1 与 2025.1 topology，再选择能力探针。

- **中文 prompt 草案：**“在 `{music_switch}` 中，为 `{state_switch_combination}` 指向 `{segment}`，保留其余组合和默认路径。先核对当前 Skill 是否能读取并维护这类音乐路径，不能时不要按普通脚步 Switch assignment 处理。”
- **Prestate：**真实 MusicSwitchContainer 的 Arguments/EntryPath 与至少两个组合；2025 的 wrapper 变化须分 lane 固定，不直接复制旧版本结构。
- **目标/保持项：**组合维度、顺序/优先关系、Segment target 与默认/其他路径保持；必要时再验证 bounded playback selection。
- **Public 路径与缺口：**目前不能把 `switchContainer.addAssignment/removeAssignment` 当 Music Switch 管理接口；普通 Footsteps 已有证据不抵本例。必须找到真实 public business seam、可读 topology 和独立 oracle 后才执行。
- **验收边界：**原生类型/反射资源/metadata 存在都不是完整路径编辑证明；不教 Agent 合成 native lists。保留候选，不计功能成功。[music primary factcheck](music-primary-factcheck-2026-09-14.md)、[complex/version topology review](music-complex-feature-risk-2026-09-14.md)、[ordinary Switch contract](../../skills/waapi-skill/wwise_waapi/switch_assignment_business_contracts.py#L17)。

## 三个试点的实施出口

| 试点 | 最小 fixture | 必须独立通过的 oracle | 冻结前必须补齐 | 规划预算 |
| --- | --- | --- | --- | --- |
| C01 / 2025.1 / ask | 同一 Sound 的两个语言源、一个替换 WAV、固定 Event | 指定语言媒体正确；另一语言/声音 GUID/播放链保持 | 双语言 oracle、精确可见对象与语言输入、一笔后续确认 | 1 task、2 turns、1 业务事务 |
| M01 / 2025.1 / allow | 一个已有音乐父级、两条不同 WAV、一个 sibling | Segment/Track/media owner 正确；hash 一一对应；Track Volume 与 sibling 保持 | 从现有 music real test 提取 independent recipe，不把内部 compiled request 暴露给 Agent；同一 import 含 Track 音量；独立 policy authorization | 1 task、1 turn、1 业务事务 |
| C06 / 2025.1 / allow | 一个 Sound、两条 RTPC、一个待更新 key | 命中 GUID 保持；完整列表集合/其他行不变；points 精确 | existing RTPC query/field discovery 的正式可见 inputs；禁止误走 add-only；独立 policy authorization | 1 task、1 turn、1 业务事务 |

因此首轮**单主机、仅 2025.1**的冻结目标为 3 tasks、4 user turns、3 业务事务；这是无额外澄清/故障重试的计划值，不是完成结果。fixture 设置、sandbox 生命周期与 supporting reads 另计，不给予主操作功能覆盖信用。尚未冻结的其余候选不填虚构事务数或统一 mode；即使题意可收窄为单事务，也要待 oracle/adapter 设计确认。

每个试点先完成可审阅的 fixture/visible input/dispatch predicate/oracle/cleanup 设计，再按仓库测试梯级做开发验证，最后使用现有 Fresh CLI harness。一次 Agent 业务成功不替代版本、host 或所有参数分支覆盖；独立 oracle 尚未闭合时保持 blocked，不通过删掉保持项“修成可跑”。

本文的下一步仅是这些设计与实现工作，当前没有启动任何执行单元，也没有增加测试覆盖或通过数。
