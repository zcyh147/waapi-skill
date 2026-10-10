# 测试扩展：现有证据、Agent 判分与成本边界

日期：2026-09-27。静态审计基线：`284899536fc469cecf075643d3942ddc3f98d04e`。
阶段一产物；只读检查源码、测试定义和历史记录，未运行 pytest、Fresh Codex 或 Wwise，未重放或改写旧证据。本文件不增加任何 PASS 或当前候选验收结论。

## 判断范围

本次已完成所列候选相关测试与harness的静态实审，并给出Core 19入口/49顶层字段的具体断言索引和未核实项；不是仅提出将来审计建议。审计沿公开 Gateway → 声明编译 → native materialization → verifier → 测试断言 → 历史运行记录检查，也不声称找到所有实现缺陷或实现全Skill参数100%闭合。已有测试缺少某条断言，只能先证明覆盖不足；实现是否错误，要另给可复现的代码或运行证据。

需要补的是“公开参数/业务分支 → 场景 → 独立断言 → 实际证据”的账本。URI 行数、pytest passing 数量、声明存在、一次完整工作流分别是不同证据，不互相替代。当前完整面报告有 **849 lanes（689 Function、160 Topic）**，但计数的是入口构造与资源一致性；不是849种业务效果，更不是参数覆盖率。[报告](../full-surface-release-report.json#L19)、[生成器](../../tests/maintenance/generate_full_surface_release_report.py#L68)

现有通用 probe 明确只生成最小 schema 值：首个 enum、首个 union branch、required 字段、通常为空的数组、false 和最小数字。故其逐 URI 执行不能证明 optional 字段或其他分支；部分路线还明确只测 native bottom call，公开 business boundary 另测。[值生成器](../../tests/support/public_route_probes.py#L15)、[program matrix](../../tests/unit/test_public_route_program_matrix.py#L144)

## 已有 Agent 套件，不能重新算成扩展成果

| 范围 | 固定定义 | 当前证据含义 |
| --- | --- | --- |
| public `integration` | Weather、Alarm、Harbor、Rifle、Footsteps、Weapons；2022.1/2025.1；12 fresh tasks、36 user turns、20 transactions | 跨操作验收；无额外 per-API credit；固定基线只用于后三项 |
| `heavy_cross_version_80` | 16 API各5例；2022.1 70、2024.1 5、2025.1 5；80 tasks、145 turns、65 confirmation turns | 已有闭合执行子集；其中两例是零主调用拒绝，不是成功写入 |
| `compound_heavy_cross_version_24` | 12逻辑场景×2版本；24 tasks、48 turns；import、table import、create、set、SoundBank generation/inclusions各2逻辑场景 | 复杂批次回归；不能当全参数矩阵 |
| 完整 V3 review catalog | 444 online定义、198 unique URI；2022/23/24/25分别326/74/27/17；计划783 turns；另12 offline cases | 大部仍是声明；不是444可立即执行的案例 |

来源：[integration常量](../../tests/semantic/support/codex_integration_workflows.py#L34)、[heavy选择与计数](../../tests/semantic/support/codex_eval_execution_v3.py#L18)、[compound与V3解释](../../tests/semantic/README.md#L93)。444定义的静态统计来自`online_tests.json`列出的7个case文件；不导入运行库。V3 coverage audit只检查URI、代表版本、不同prompt/family和oracle计划，未记录每个公开field/value/branch的覆盖义务。[audit](../../tests/semantic/support/codex_eval_bundle_v3.py#L1047)

`adapter_registry.json`列有87 fixture、9 trigger、148 oracle、31 cleanup identifiers，总275项，状态仍是`specification_only_pending_user_review`，不能称275个已实现adapter。14项request mapping要求中3 closed，11未关闭（6 missing、5 available_not_exposed），阻塞35场景、21 API。heavy之外364个review定义不自动可运行；同时已有typed/deep-business等其他代表性profile，不能说它们完全没有执行基础。[registry](../../skills/waapi-skill/evals/adapter_registry.json#L3)、[mapping registry](../../skills/waapi-skill/evals/request_mapping_registry.json#L3)、[profile边界](../../tests/semantic/README.md#L21)

历史heavy c38的80/80耗时1h38m10s，只属于旧冻结候选；之后harness改变，不能当当前候选接受。最近记载的integration `0682c1a`是Windows单root12/12；Mac 11/12加同候选fresh Rifle 1/1，累计12/12，不能写Mac单root通过。[heavy记录](../../tests/TEST_INVENTORY.md#L499)、[integration记录](../../tests/TEST_INVENTORY.md#L588)

## 已核实的判分机械性与已有容错

### 判分并非只看最终业务状态

V3每turn的common gate要求退出0、非timeout、session完整、无文件改变；还检查允许的Skill读取、Gateway命令数量和命令类别。业务oracle完成也不能自动抵消这些失败。这是实际代码事实，不代表每条约束都应该放宽。[common gates](../../tests/semantic/support/codex_task_runner_v3.py#L981)

已记录两种应区分的失败：

- **Harness等价判断过严**：Weapons提交同样对象/字段/值，但独立row和CLI flag位置不同，旧Broker在Gateway/Wwise前拒绝；后续修复只规范化独立existing-object edit，仍拒绝缺失、重复、额外或改值，并保留create/import依赖顺序。旧FAIL未被改写。[事件及修复](../../tests/semantic/HARNESS_PITFALLS.md#L3305)
- **业务已有产物但turn未完成**：Windows Harbor十个已接受Gateway调用并生成Preview后，360秒到期，缺最终回复；`one_completed_turn`失败。记录要求在新root用600秒容量重跑，不能重新解释旧timeout为PASS。[记录](../../tests/semantic/HARNESS_PITFALLS.md#L3190)

相反，Agent自己错误地将明确完整结果称为truncated并提前停下，或漏掉后续预览，是真实任务未完成，不能因为已生成部分结果就归为grader误判。[Rifle记录](../../tests/TEST_INVENTORY.md#L588)、[有序工作流完成规则](../../tests/semantic/HARNESS_PITFALLS.md#L3122)

### 当前已支持的合理等价，先复用而非再加一套

| 已有支持 | 保留的边界 | 代码 |
| --- | --- | --- |
| query-first任务一次提前读取operate reference，作diagnostic | 只接受指定单次顺序，不允许任意额外文件、命令或重复读 | [read gate](../../tests/semantic/support/codex_task_runner_v3.py#L1031) |
| business query CLI选项等价规范化 | 闭合option/arity、来源、predicate和数据值 | [query matcher](../../tests/semantic/support/codex_gateway_broker.py#L4663) |
| 单对象bind冗余`--role object` | 只接受该唯一等价，不接受错误role、重复role或多role改动 | [role normalization](../../tests/semantic/support/codex_gateway_broker.py#L4519) |
| 显式批准的只读step permutation group | 不是任意workflow重新排序 | [read group validation](../../tests/semantic/support/codex_gateway_broker.py#L2381) |
| Topic独立match assignments可交换 | projection顺序与同slot冲突不放宽 | [Topic matcher](../../tests/semantic/support/codex_gateway_broker.py#L1563) |
| public integration把first-use介绍委托给专项profile | 不省掉业务、安全和来源证据 | [profile属性](../../tests/semantic/support/codex_integration_workflows.py#L163)、[observer](../../tests/semantic/support/codex_heavy_project_runner_v3.py#L1591) |

仍有局部机械限制，例如旧`query-object --return-field`matcher允许值顺序不同，但要求重复flag的位置相同；这证明仍有精确序列机制，**不证明当前新业务query一定能触发误判**。应仅在最小语义等价回归证明确实误拒时扩展对应matcher，不能据此删除所有command count/order gates。[代码](../../tests/semantic/support/codex_gateway_broker.py#L4068)

精确白名单实际落在三层：Broker先要求当前step的global flags/subcommand prefix完全相同（`:12806`），经过已批准normalizer后仍要求参数数相同（`:13042`），普通literal逐项相同或通过局部等价函数（`:13091`）；任务层另要求`gateway_count_exact`（task runner`:1003`），Broker终态要求成功数、record数和selected expected step数相同（broker`:9905`）。因此**语义合法但不在已批准等价集中的额外read/替代路径**可能在进入Gateway前失败；这里是机制风险，不是宣称已经复现所有这类路径。已证实的历史实例是上述Weapons flag/row顺序误拒。[prefix](../../tests/semantic/support/codex_gateway_broker.py#L12806)、[arity](../../tests/semantic/support/codex_gateway_broker.py#L13042)、[literal](../../tests/semantic/support/codex_gateway_broker.py#L13091)、[count](../../tests/semantic/support/codex_task_runner_v3.py#L1003)

### 结果优先的最小修改建议（尚未实现）

1. 扩展profile复用现有Broker与task runner。每例声明必需的业务效果、禁止效果、对象/文件保护集和必要的事务偏序；把可交换read、纯声明选项位置、明确等价selector归入已存在的局部规范化机制。
2. 判分报告分别列`business_outcome`、`safety_provenance`、`protocol_equivalence`、`completion`、`efficiency_diagnostics`。这是建议的新报告视图，不是现有状态。extra但有界、授权范围内的只读查询可先标成本诊断；允许哪些额外read必须有封闭策略和负例，不能直接泛化所有查询。
3. 保持硬失败：未授权写、目标/值漂移、模型写原始native输入、绕过Gateway、重试不明确mutation、Preview改变工程、缺execute/verify、结果/清理证据缺失、source被改。仅“结果看起来对”不能抵消这些问题。
4. 真正业务最终状态由独立readback/snapshot/文件hash/Topic身份或明确较弱边界确认。不要只检查`verified=true`，也不要让同一compiler同时生成唯一expected和actual。现有observer已在Preview检查隐藏snapshot，末次verify调用business oracle，可复用。[observer](../../tests/semantic/support/codex_heavy_project_runner_v3.py#L1552)
5. harness修复必须同时更新live matcher、terminal classification和archive validation，并提供同值等价通过与漏字段/重复/改值拒绝的配对回归。历史已经出现live接受而archive误拒，不能只改一端。[archive问题](../../tests/semantic/HARNESS_PITFALLS.md#L2519)

最小版本化方案是**冻结现有profile及其默认判分语义，为扩展profile绑定一个显式版本的equivalence policy**，仍复用同一个campaign、matrix、Broker与安全验证。只给新profile启用已review的bounded optional reads/偏序/等价声明；记录policy版本与digest于immutable config及archive。旧profile默认保持原判断，旧sealed roots不换grader。若需要改共享函数，旧policy必须有兼容分支与回放契约测试。此方案尚未实现；C01/M01/C06三个pilot应先沿用既有`gpt-5.6-terra`、medium、default设置，模型切换不作为判分修复。

## Timeout、选择、resume与旧FAIL

现有campaign支持`--case-id`、`--version`、`--offline-only`、`--timeout`、`--wwise-readiness-timeout`。profile的固定选择器不允许用case filter悄悄扩大完整approved集合。默认model turn timeout在matrix为240秒，typed/deep与public integration为360秒；Wwise readiness默认60秒，是不同计时器。[默认](../../tests/semantic/run_codex_skill_matrix.py#L629)、[CLI和profile选择](../../tests/semantic/run_codex_skill_campaign.py#L15543)

这里建议的**两分钟软目标、五分钟进展评估不是当前已配置功能**。软目标是设计案例长度与记录延迟分布的指标，不能120秒直接判错；五分钟评估应区分模型推理、有效Gateway进展、Wwise等待、服务阻塞与无进展。如果当前hard timeout是360秒，五分钟只剩60秒，不能临时延长同root或重试mutation。应在pilot后为新profile/host预先冻结合理hard timeout，明确单位是turn还是workflow。要实现安全的进度监视/超时分类，需另做runner设计与回归，本阶段不承诺已有adaptive watchdog。

现有resume只选pending和被证明pre-action retryable的unit，按suite顺序运行fresh sandbox；没有“失败就自动重跑”的承诺。retry要求失败turn无命令、Gateway记录、协作、文件改变或非法event，之前turn与Broker prefix可信、source不变、cleanup/quarantine明确。普通FAIL、BLOCKED、INDETERMINATE不会因为重试愿望变PASS。[选择代码](../../tests/semantic/run_codex_skill_campaign.py#L1164)、[规则](../../tests/semantic/README.md#L701)

`--resume --verify-only`是按原冻结Skill/suite/harness/options重验seal与证据，不是把新grader应用到旧FAIL。repo多处规定已封存FAIL root不作verify-only replay；不得为本次扩展解除该规则，也不能承诺“修好判分后直接重判所有历史case”。现有CLI即使能验某些失败档案，仍不授予修改历史结论的权力。[verify-only语义](../../tests/semantic/README.md#L725)、[冻结FAIL实例](../../tests/AGENTS.md#L616)

如以后要开发**独立regrade派生证据**，需先设计：只读旧seal、旧grader与新grader双版本、明确授权的等价变化、每个结论的业务证据充分性、全程无模型/WAAPI重执行、单独输出新artifact、不覆写原FAIL，不把重判当新candidate真实运行。缺失的after snapshot、没实际执行的步骤、未完成用户交付不能靠regrade补出。这仅是未来设计选项，不是当前能力。

## Python其他域：先登记复用，不因新增Agent而复制相同测试

| 域 | 已存在具体断言 | 新扩展需要确认的剩余范围 |
| --- | --- | --- |
| metadata发现 | live候选single/multiple/no-match、display fallback、依赖闭包/cycle、bounded scan；Gateway五版本meaning→property-state native read | Agent如何处理歧义/缺候选，不等于需要再写相同编译测试；各class/plugin覆盖尚未逐一闭合 |
| platform | 同platform preflight/dispatch/verify；linked pre/post；真实Volume -3.25、OutputBus、clear Attenuation、2023+ unlink | omitted/explicit、跨平台保留、不同字段适用性需要逐obligation对照；不能把一次Windows属性设置称全platform覆盖 |
| State/Switch对象 | 正确parent创建、错误parent拒绝；2021/22跨group move，2023–25明确边界；rename与sibling保留 | 这些是game-sync对象CRUD，不是state驱动声音/transition；`setStateGroups`已有materialization断言，完整真实状态行为未由本审计证实 |
| Attenuation | copy/rename/delete保持原件；metadata curve-role→native；curve custom与none/volume-dry/project materialization | 对象生命周期不证明曲线声音效果；各曲线role/shape的真实效果和Agent组合覆盖待账本核实 |
| object生命周期 | 五verifier真实链、compound undo成功/取消、不重试；derived name拒绝；Music ownership | 每种collision、version/host、protected reference影响需继续逐条比对，不先假设不存在测试 |
| 多语言Voice | English/Japanese四步导入重导入，保持Sound/source身份，另一语言不变，Originals字节hash | 已有独立真实断言，应复用为Agentoracle依据；未验证的语言/多平台组合单列 |

出处：[metadata分支](../../tests/unit/test_metadata_discovery.py#L297)、[Gateway property-state](../../tests/unit/test_metadata_discovery_gateway.py#L302)、[platform](../../tests/unit/test_operation_platform_rtpc.py#L161)、[真实metadata链](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L2814)、[State/Switch](../../tests/destructive/test_cross_family_lifecycle.py#L124)、[setStateGroups](../../tests/unit/test_core_business_adapter.py#L277)、[Attenuation CRUD](../../tests/destructive/test_cross_family_lifecycle.py#L196)、[curve编译](../../tests/unit/test_core_business_adapter.py#L491)、[lifecycle](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L2584)、[Voice](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L603)。

这些都是**已读到测试实现**，不意味着在当前HEAD重跑过。历史跨对象族65/65记录是5版本×13选中测试，其中包含正确拒绝的边界；不能称65个工作mutation能力。[历史证据](../../tests/TEST_INVENTORY.md#L37)

### Core公开字段到现有断言的初步索引

静态解析`core_business_contracts.py`的`_CONTRACTS`字面量得到**19入口、49个顶层字段出现位置**（同名跨入口分别计数）；不含`points`/`edges`内部字段、枚举值、分支和Gateway其他入口。以下P表示已找到Python值映射断言，L表示只找到逐版本最小合法lane materialization，U表示本轮未找到精确值断言；均不是本轮执行结果。完整字段分母来自[公开契约](../../skills/waapi-skill/wwise_waapi/core_business_contracts.py#L10)，L测试只检查materialize成功及operation/version，因此不能把L升为字段值验证。[lane测试](../../tests/unit/test_core_business_adapter.py#L733)

| 入口 | 全部顶层字段 | 已核实证据及待核实点 |
| --- | --- | --- |
| `object.setAttenuationCurve` | `attenuation_handle`, `curve_kind`, `curve_source`, `points`, `platform_name` | P全部：volume-dry/custom、Windows、两点linear/constant；另none/volume-dry/project源和empty points。其余curve_kind/shape未逐一核实。[test](../../tests/unit/test_core_business_adapter.py#L491) |
| `object.setRandomizer` | `object_handle`, `field_handle`, `enabled`, `minimum_offset`, `maximum_offset`, `platform_name` | P全部：Volume、true、-3/+5、Windows；false/省略/零边界需继续匹配。[test](../../tests/unit/test_core_business_adapter.py#L350) |
| `switchContainer.getAssignments` | `switch_container_handle` | P：handle→id。[test](../../tests/unit/test_core_business_adapter.py#L255) |
| `object.diff` | `source_handle`, `target_handle` | 公开Gateway精确两对象read证明，两字段可复用。[test](../../tests/unit/test_core_business_gateway.py#L380) |
| `object.pasteProperties` | `source_handle`, `target_handles`, `include_field_handles`, `exclude_field_handles`, `list_mode` | P source、两个targets、include Volume、merge-replace；U exclude非空精确值。其他list_mode未逐一核实。[test](../../tests/unit/test_core_business_adapter.py#L414) |
| `audio.mute` | `object_handles`, `muted` | P多对象、true；L合法lane；false分支待核实。[test](../../tests/unit/test_core_business_adapter.py#L262) |
| `audio.solo` | `object_handles`, `soloed` | P多对象、false；L另true，但L不含该字段逐值断言。[test](../../tests/unit/test_core_business_adapter.py#L269) |
| `object.isLinked` | `object_handle`, `field_handle`, `platform_name` | P全部：Volume/Windows；Gateway还有meaning发现字段。[adapter](../../tests/unit/test_core_business_adapter.py#L400)、[Gateway](../../tests/unit/test_core_business_gateway.py#L576) |
| `object.setStateGroups` | `object_handle`, `state_group_handles` | P owner、单StateGroup→native；2023–25 L。empty/multi/replace及真实后态待核实。[test](../../tests/unit/test_core_business_adapter.py#L277) |
| `object.setStateProperties` | `object_handle`, `field_handles` | P owner、Volume/Pitch两handles→stateProperties；2023–25 L。清空与不适用字段、真实State效果待核实。[test](../../tests/unit/test_core_business_adapter.py#L383) |
| `project.save` | `auto_check_out` | P显式true，Gateway同为true；schema披露默认/true/false。false精确materialization断言本轮未找到，不能把schema文字算三值执行。[adapter](../../tests/unit/test_core_business_adapter.py#L182)、[Gateway](../../tests/unit/test_core_business_gateway.py#L259) |
| `audio.convert` | `audio_object_handles`, `platform_names`, `languages`, `io_root` | P多对象、Windows/Mac、SFX/English；同test未在native args断言io_root（它是隔离边界），Gateway专项含exact I/O root。[adapter](../../tests/unit/test_core_business_adapter.py#L445)、[Gateway](../../tests/unit/test_core_business_gateway.py#L765) |
| `audio.setConversionPlugin` | `conversion_handle`, `platform_name`, `plugin_name` | P全部：Windows/Vorbis；其他installed插件/平台待核实。[test](../../tests/unit/test_core_business_adapter.py#L470) |
| `blendContainer.addAssignment` | `blend_track_handle`, `child_handle`, `insertion_index`, `edges` | P全部：index1、两个edge；manual/automatic、linear/s-curve；边界与其余shape待核实。[test](../../tests/unit/test_core_business_adapter.py#L550) |
| `blendContainer.addTrack` | `blend_container_handle`, `track_name` | P全部：Weather Blend。[test](../../tests/unit/test_core_business_adapter.py#L597) |
| `blendContainer.getAssignments` | `blend_track_handle` | P handle→object。[test](../../tests/unit/test_core_business_adapter.py#L284) |
| `blendContainer.removeAssignment` | `blend_track_handle`, `child_handle` | P两身份精确映射。[test](../../tests/unit/test_core_business_adapter.py#L613) |
| `workUnit.load` | `work_unit_handle` | P handle→object；L全部合法version lane；另stale/wrong-role负例。真实加载后态待核实。[mapping](../../tests/unit/test_core_business_adapter.py#L290)、[负例](../../tests/unit/test_core_business_adapter.py#L751) |
| `workUnit.unload` | `work_unit_handle` | P handle→object；L全部合法version lane；真实卸载后态待核实。[mapping](../../tests/unit/test_core_business_adapter.py#L297) |

与本轮候选最相关的platform/State/attenuation不能止于上表：platform要分**显式平台、字段handle绑定平台、省略平台**，setProperty/setReference/setLinked属于另一公开operation seam；其Windows真实链在`:2814`，link_state=`unlinked`精确映射在object metadata adapter`:180`，缺platform拒绝在`:245`。State的**组对象CRUD**与**对象的StateGroups/StateProperties配置**必须分开记账；Attenuation的**对象copy**与**curve_source/points编辑**亦分开。上表P可作为不重复补Python的依据，但未来新增Agent case必须有自己的效果oracle，不能只调用P中的compiler获得同源expected。[platform handle](../../tests/unit/test_object_metadata_business_adapter.py#L180)、[缺平台拒绝](../../tests/unit/test_object_metadata_business_adapter.py#L245)

## 音乐示例：不能从层级存在推导音乐行为

当前公开Gateway音乐导入覆盖media-only及Track -6dB两种case。冻结候选5版本共10/10真实Console；没有Fresh Agent/native-Windows音乐接受记录。原生topology probe标明诊断性质，另一个可见Sol/High任务只到Preview，不是formal fresh campaign。[测试](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L570)、[精确运行记录](music-import-topology-repair-2026-09-14.md#L94)、[Preview边界](music-import-topology-repair-2026-09-14.md#L84)

Playlist测试只证明canonical query/create/import parent；MusicSwitch→Playlist move只证明ownership；Stinger测试2021/22是未暴露引用边界，2023–25只改Trigger并保持Segment。现有代码主动声明不证明排序、transition或播放，应沿用这一诚实边界。[Playlist](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L674)、[move](../../tests/destructive/test_cross_family_lifecycle.py#L221)、[Stinger](../../tests/destructive/test_cross_family_derived_identity.py#L135)

新增音乐Agentcase可复用import资产生成、正式campaign、Draft与sandbox，增加适合音乐的recipe和独立oracle。分别记录：结构身份；创作语义（source/Sequence/Clip、媒体hash、Track与Clip属性各自的owner、适用时playlist条目/transition配置readback）；真实运行行为（trigger与时序的可信观察）。只有结构阶段成功，不得给播放credit。当前import verifier证明Clip与source同media路径，不声称读到了未暴露的Clip→source GUID关系。[音乐验证边界](music-import-topology-repair-2026-09-14.md#L48)

Playlist/Transition/Cue/MIDI/Music Switch路径尚不能从这些测试推导支持或不支持；本阶段只确认它们未被上述工作流的断言证明。必须先确认公开契约和可观察oracle，再决定正向案例、unsupported boundary或待前提，禁止用XML/native payload绕开公开接口。

## 执行成本与选择规则

当前阶段一计划采用**17个候选workflow**，先选C01、M01、C06三个pilot。候选数不是已经实现或通过数量，也不声明全Skill所有参数闭合。把独立探针合并进workflow只在前置状态兼容、失败可归因、每项独立断言仍保留时成立；多个mutation仍各有Preview/授权/verify，不因合并prompt消失。每个pilot的实际version/host/turn/transaction必须以主计划的选中清单为准，本报告不另扩执行范围。

预算表应按以下规则从最终选中清单计算，而不是先给总金额：

- task数 `N = Σ(workflow × 实际选择的version × host × 独立prompt variant)`；host必须明确macOS/native Windows，Console/Authoring是另一个执行lane维度。
- turn数 `T = Σ(unit的request/diagnosis/selection/confirmation/follow-up turns)`；不能一概`2N`。现有integration正是12 tasks/36 turns/20 transactions。
- transaction数 `X = Σ(每个unit实际计划的独立Preview链)`；正确拒绝case的X可为0，仍有断言与成本。
- wall time计划使用pilot中各host/lane的startup、turn、Wwise操作、oracle与cleanup时间分布；保留P50/P95及最慢原因。各version/case按现有规则顺序跑，不靠未批准并发缩短预算。
- token/费用只从实测usage与明确模型计价计算；本审计未提取usage，无可诚实提供的token/dollar估计。历史80例约98分钟只能作该冻结候选的事实，不线性外推音乐/Authoring/新host。
- 例如17候选全部选择2版本×2hosts就是68 tasks；全部5版本×2hosts是170 tasks，二者都不是推荐或已授权执行数量。三个pilot若各只选一个明确version/host则3 tasks；若实际选2版本×2hosts则12 tasks。版本不可用或host不匹配须另记boundary/blocked，不能凑足数量。turn/transaction仍从每例定义计算，不从task数猜测。

先做所有支持版本的廉价公开Gateway program契约与负例；真实Wwise按业务语义/version delta/host分类选择；Fresh Agent集中验证自然语言理解、discovery、身份选择、跨operation与确认流程。若要求每个参数都由Agent在每个版本执行，必须明确采用更大分母，不能用代表版本暗中代替。新增semantic场景始终挂现有campaign/matrix，不建第二套harness。[正式入口](../../tests/semantic/README.md#L3)、[测试阶梯](../../tests/AGENTS.md#L106)

## 阶段一交付后的准入检查

下一阶段实现前应有可review的清单：每个public字段/分支的来源及version/host；已有测试和精确证据；缺口状态（确定/待核实/blocked）；fixture/oracle owner；将用的Python/real/Fresh层；任务、turn、transaction数；硬timeout配置与软目标解释。仅在这份清单闭合后称“完整生成”。不更新`TEST_INVENTORY.md` passing计数，不改历史FAIL，也不把本报告当执行授权或运行证据。
