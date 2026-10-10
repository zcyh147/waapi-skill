# 测试扩展第一阶段：公开参数与现有 Python 断言审计

日期：2026-09-27。检查时HEAD：`284899536fc469cecf075643d3942ddc3f98d04e`。范围：`audio.import`、`audio.importTabDelimited`、`object.create`、`object.set`、`object.createPlugin`、`object.setRTPC`。本次只读检查实现、契约、测试函数及已有运行记录，只新增本文；没有运行 pytest、Fresh Codex 或 Wwise，没有改动 runtime、测试或三个既有未跟踪文档。

结论：这些操作已有大量可复用的编译、Gateway 和 verifier 测试，不能从零重建一套“参数测试”。扩展应优先补齐公共入口到明确业务回读的连接，保留版本和弱验证边界。`audio.import` 的 15 个 declaration 字段及全部 settings 已在下表逐项归属；“有测试定义”“过去执行过”“当前候选通过”是三件不同的事。

## 口径与证据层级

- **P-A**：Python Adapter/编译器测试，通常构造 session 和 handles，检查内部 materialization；不证明 Agent 会使用公开 CLI，也不证明 Wwise 接受请求。
- **P-G**：公开 Gateway CLI + fake client 测试，检查公开字段、revision、continuation、Preview；仍不是真实 Wwise。
- **P-V**：Registry/原生构建器/verifier 的 Python 单元测试。支持校验机制和回读语义，不能替代公共业务入口覆盖。
- **L-def**：已存在真实 sandbox 测试函数；仅检查定义不授予一次运行的 PASS。
- **L-record**：已有文档明确记录的历史真实执行，限于其候选、主机、版本、工作流。本次未重新审计全部 sealed JSONL。
- **reuse**：复用现有测试及断言；**extend**：已有基础，扩展其入口、参数或业务 oracle；**confirmed gap**：已从实现/断言确认的特定证明缺口，不能泛化成“全仓库没有测试”；**unresolved**：本次未证明覆盖或能力，需下一阶段核实。

一个参数只需一个有效代表值，不穷举枚举笛卡尔积；但互斥输入、new/existing、版本门槛、defaults 覆盖、身份保持与替换属于不同业务路径。`field_values` 按代表性类型和绑定约束计义务，不无界枚举所有插件属性。原生 `objectPath/objectType/args/options`、内部 handle 存储和派生 continuation 不计为用户参数。

以下文件代号均相对仓库根目录；表内给出测试函数与其定义行号，描述的是实际阅读到的断言，而非只按名字推断。

| 代号 | 文件 |
| --- | --- |
| AI-C | `skills/waapi-skill/wwise_waapi/audio_import_business_contracts.py` |
| AI-A | `tests/unit/test_audio_import_business_adapter.py` |
| AI-G | `tests/unit/test_audio_import_business_gateway.py` |
| IM-P | `tests/unit/test_operation_import.py` |
| IM-V | `tests/unit/test_operation_registry_import_verifier.py` |
| OG-C | `skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py` |
| OG-A | `tests/unit/test_object_graph_business_adapter.py` |
| OG-G | `tests/unit/test_object_graph_business_gateway.py` |
| WF | `tests/destructive/test_gateway_workflow_transaction_matrix.py` |

## 1. audio.import：15 个声明字段逐项审计

契约来源 AI-C:19–34；其中六个通用字段来自 `business_fields.py:12`，排除了仅适用于 Action 的 `fade_time_ms/delay_ms`。支持五版本，但对象、语言和选项仍有条件限制。

| 公开字段 | 具体测试与已读断言 | 层级／决定 |
| --- | --- | --- |
| `media_file` | AI-A:83 `test_new_media_declaration_compiles_all_common_business_fields`：`audio_file == str(media)`；WF:571 `test_closed_music_import_media_and_track_volume` 走公开 import batch 到 execute/verify | P-A + L-def；reuse。音乐五版本历史 L-record 见下文 |
| `inline_wav` | AI-A:309 `test_structure_inline_existing_and_explicit_replace_modes`：base64结果以指定文件名前缀开头；IM-P:568 `test_audio_import_plan_accepts_bounded_canonical_base64_wav`；IM-P:627 拒绝同一行同时提供文件和base64 | P-A/P-V；reuse，实际音频业务回读需按素材fixture补证 |
| `language` | AI-A:177 `test_sound_sfx_kind_derives_the_only_valid_import_language`、:198 `test_music_track_import_language_default_preserves_explicit_values`、:261 `test_sound_voice_still_requires_an_exact_project_language`、:282 existing SFX；区分推导SFX、显式值和Voice缺参 | P-A；reuse。WF:603起的多语言Voice测试保留另一语言及Sound身份，不能用SFX导入替代 |
| `volume_db` | AI-A:83断言 `Volume=-4.0`；:577默认-2被单行-6覆盖；WF:571通过 `set_volume` 参数区分纯媒体与-6dB | P-A + L-def/L-record；reuse |
| `loop` | AI-A:83断言生成 `IsLoopingEnabled=True`、`IsLoopingInfinite=True` | P-A；reuse代表值 infinite；不据此声称有限循环或关闭分支已真实验证 |
| `max_instances` | AI-A:83断言 `UseMaxSoundPerInstance=True` 和 `MaxSoundPerInstance=3` | P-A；reuse |
| `ignore_parent_instance_limit` | AI-A:83断言 `IgnoreParentMaxSoundInstance=True` | P-A；reuse |
| `output_bus` | AI-A:83断言引用由bus handle编译为指定GUID；禁止把路径当引用值的规则在AI-C:116–124 | P-A；reuse；真实目标Bus及路由回读应进入跨操作案例 |
| `notes` | AI-A:577 `test_live_field_handles_event_directive_and_batch_defaults_are_lossless`：`row.notes == batch note`；IM-V:1468 `test_use_existing_sfx_row_may_update_notes_on_an_existing_target` 检查dispatch与Notes目的地oracle；IM-V:1535拒绝两个竞争source-notes字段 | P-A/P-V；extend new与existing的Notes目标差异；不可当统一“写对象notes” |
| `audio_source_notes` | AI-A:83传入该字段，但该函数没有直接断言其materialized结果；IM-P:196 `test_audio_import_plan_normalizes_structured_fields_and_provenance` 对整个native row做相等断言，含 `audioSourceNotes=take 2` | P-A输入 + P-V明确映射；extend Adapter或公共Gateway的精确值断言。已确认是所审函数的断言缺口，不是全仓库无覆盖 |
| `originals_subfolder` | AI-A:83传入但未直接断言；IM-P:196全row断言 `originalsSubFolder=Chapter06\\Japanese`；IM-V:1631 `test_originals_subfolder_is_derived_without_legacy_relative_field` 断言verifier成功及精确derived relative path | P-V较强；extend公共业务层衔接；另有路径逃逸、wproj/root漂移测试，不能只测字符串透传 |
| `switch_value` | AI-A:83断言 `switch_assignment=Rain`；AI-G:1262 `test_audio_import_switch_value_is_a_first_class_business_argument`：receipt只有指定switch_value；用泛用`--field`修改被拒绝且draft文件字节不变 | P-A/P-G；reuse输入边界；完整assignment效果另列confirmed gap，见下文 |
| `dialogue_event_directive` | AI-A:577断言 `dialogue_event=Dialogue_Custom`；实际编译在 `audio_import_business.py:447`；现有verifier显式保留directive弱验证标签 | P-A；reuse透传；完整Dialogue关系重建为confirmed gap，不可把native结果成功算业务完成 |
| `event` | AI-A:577断言 `{path, action: Play}`；IM-V:2305 `test_closed_audio_import_verifies_exact_event_action_and_target_in_every_version` 与:2375错误/缺失/歧义Action反例 | P-A/P-V；reuse。覆盖目标是Event→Action→导入对象关系，不是仅Event存在 |
| `field_values` | AI-A:577同时断言class-scoped Pitch数值及CustomOutput引用；AI-A:492 `test_object_scoped_field_handle_cannot_cross_existing_targets` 拒绝对象scope串用 | P-A；reuse数值/引用及scope边界；更多enum/quantity使用共享字段测试，不能自动给所有插件字段信用 |

### settings、目标形式与重要分支

| 公开设置／分支 | 契约与测试／断言 | 决定 |
| --- | --- | --- |
| `defaults`继承与单行覆盖 | AI-C:13、`audio_import_business.py:290`；AI-A:577：language/notes继承，volume单行覆盖，完整properties结果相等 | reuse P-A；新测试不必按每个字段重复defaults笛卡尔积 |
| `add_to_source_control` | AI-C:13；AI-A:83明确 `auto_add_to_source_control is True`；IM-P:697 `test_audio_import_plan_exposes_auto_add_to_source_control` | reuse参数映射；provider实际添加为unresolved条件环境，不以显式false冒充添加效果 |
| `check_out_from_source_control` | AI-C:155；AI-A:657 `test_source_control_version_boundary_and_implicit_existing_reimport`：2023–25 native值True；2021/22报 `VERSION_BEHAVIOR_BOUNDARY` | reuse五版本正负分流；provider实际checkout未在本审计授信 |
| 显式`replace`；隐式create/reimport | AI-C:73只公开replace选择，其余由目标形式推导；AI-G:35 `test_audio_import_contract_exposes_only_explicit_replace_mode`；AI-A:309替换编译；:657已有对象推导useExisting；IM-V:2267要求新GUID且旧GUID消失 | reuse；必须保留“身份保持”与“身份替换”两种oracle |
| new/existing、结构行、planned parent | AI-A:309结构行；:381保留Sound subtype；:412允许混合existing/missing；:532 `ordered_effect_ids`及子路径、batch数断言 | reuse P-A；不要把12种semantic kind全当相同媒体拓扑 |
| batch≤6、累计分块与原子失败 | AI-C:12/:137；AI-G:686 `test_audio_import_batch_chunks_are_atomic_cumulative_and_compact`；:1066 `test_audio_import_batch_count_mismatch_is_atomic`；无效media-directory尝试前后draft字节相同 | reuse P-G；六是单命令上限，不是整任务上限 |
| MusicTrack隐式SFX与自动Clip拓扑 | AI-A:198/:239；AI-G:1016缺省language完成batch但未native dispatch；IM-V:396有missing_clip/wrong_media等变体；WF:571公开正向路径 | reuse；verifier只证明同Track Clip媒体路径，不证明Clip→Source GUID引用或播放效果 |
| 已有本地化Voice仅媒体更新 | IM-P:1216 `test_localized_existing_boundary_rejects_every_unproven_wire_field`；IM-V:988/:1128分别拒绝非音频字段、验证精确三字段wire shape；WF多语言用例单独保留其他语言 | reuse明确边界；不能把notes/subfolder/Event硬塞同次localized reimport |

**明确的业务证明缺口**：IM-V:435 `test_closed_audio_import_native_directive_boundary_is_weak_success` 实际断言 `status == result_schema_checked`、`ok is True`、`business_state_verified is False`。实现 `operation_registry.py:11538` 同时列出Dialogue与Switch的 `side_effect_not_fully_reconstructed` 标签。因此directive的输入、dispatch与目标媒体可以有测试，而完整关系效果仍不能授信。后续要么增加独立公开业务读取oracle，要么保留弱边界；不是删除此正确的降级测试。

## 2. audio.importTabDelimited

公开契约 `exact_artifact_business_contracts.py:139`：`table_file/location_handle/language/mode/add_to_source_control` 五字段，2023–25另有checkout，共六字段。TSV是精确用户artifact；其列语法属于artifact解析义务，不能混成“Agent应构造原生JSON”。

| 字段／分支 | 具体已有断言 | 层级／决定 |
| --- | --- | --- |
| 上述六字段 | `test_exact_artifact_business_adapter.py:86::test_tab_import_plan_derives_native_fields_from_bound_location` 使用2025、English(US)、replace、add=True、checkout=False，对完整arguments相等断言并parse | P-A；reuse所有六字段代表值；extend旧版本public adapter的checkout拒绝路径，不把下层覆盖误称同一入口 |
| 新建真实导入及原表不改 | WF:2106 `test_exact_tab_import_business_draft_binds_location_and_preserves_table`：精确导入路径及table SHA256不变，finally清理 | L-def；reuse，但不是六参数全部真机验证。该测试经`_complete_transaction`及共享preview helper转公共路径，应复用helper，不复制其内部request为Agent输入 |
| checkout版本边界 | IM-P:107/:155 `test_tab_import_exposes_versioned_auto_check_out` / `test_tab_import_rejects_explicit_auto_check_out_in_old_lanes` | P-V；reuse，不借给公共入口未检查的路径 |
| Unicode、动态列、重复Event、base64 | IM-P:761 `test_tab_parser_derives_unicode_oracle_from_file_bytes` 断言Unicode notes；:920动态properties/references；:970Dialogue/Switch directive；:1002base64；:1029重复Event列 | P-V；reuse解析器义务；真实作用和弱验证规则仍分别审计 |
| 坏表/坏文件不可执行 | IM-P:821物理tab/newline、:1058缺失/重复header、:1080BOM/UTF-8/列数、:1100相对/缺失/symlink media、:1233文件替换漂移 | P-V；reuse负面边界，Fresh用例只选代表性用户纠错，不重复全部parser矩阵 |

## 3. object.create 与 object.set

OG-C:298起为create契约；:176起为set契约。create五版本，set仅2022–25；set附属媒体仅2023–25。以下覆盖的是本轮直接检查到的主要公共字段及路径，不宣称所有动态字段/类型已闭合。

| 公开字段／分支 | 具体测试与断言 | 决定 |
| --- | --- | --- |
| create `parent_handle/name/kind`、planned parent | OG-A:41 `test_object_create_compiles_named_hierarchy_without_native_types_or_paths`；OG-A:90 bound long-tail kind；:117 live type drift报 `TYPE_HANDLE_STALE`；OG-G:382通过发现type后仅用handle编译 | reuse P-A/P-G；新Agent只需覆盖一次真实发现与层级构造 |
| create `loop/max_instances/output_bus/ignore_parent_instance_limit/volume_db/field_values` | OG-A:140 `test_object_create_compiles_common_and_bound_fields_without_tokens` 对完整arguments相等断言，含CustomGain、OutputBus及五固定字段；OG-G:876公开CLI到相同canonical结果 | reuse P-A/P-G；其中2025专用正例不能单独证明五版本每个字段 |
| create settings `platform/add_to_source_control/name_conflict` | 同OG-A:140、OG-G:876；platform Windows、auto-add True明确断言；OG-G:566 `test_gateway_closes_merge_configuration_before_root_declaration`覆盖merge时序；Registry schema测试 `test_operation_registry.py:1229`固定各版本merge契约 | reuse基本/merge；`rename/replace_owner_handle`业务入口与真机替换图的完整映射 unresolved，不能仅凭schema列举算覆盖 |
| create `notes`与Action时间字段 | notes经公共共享fields；`test_field_interface_closure_gateway.py:205`及:340明确覆盖set上的250ms→0.25s、80ms→0.08s和Preview无mutation | set时间字段reuse；create在Action类型发现后的对应时间路径本次未证，unresolved；不能借set测试给create计分 |
| create Voice与内部音乐对象边界 | OG-A:815 `test_object_create_rejects_voice_outcome_that_native_route_cannot_express`断言 `OBJECT_CREATE_VOICE_UNAVAILABLE`及合法替代；`test_operation_registry.py:2429::test_music_internal_creation_rejects_real_reflected_type_names` | reuse禁止边界；Clip/Sequence/Stinger不能为测试覆盖率强行创建 |
| set `object_handle`、new `parent_handle/name/kind`、`field_values/notes/volume_db` | OG-A:331 `test_object_set_compiles_multi_object_changes_and_new_descendants` 完整objects数组相等，含两个existing对象及一个新child，typed property/reference与notes | reuse P-A；WF:3011有real business create→plugin→bulk set→RTPC，但仅选择2022/2025 |
| set `new_name`及固定业务字段 | OG-G:1685 `test_object_set_batch_keeps_disclosed_stable_fields_out_of_metadata`检查batch receipt含new_name；OG-G:1107拒绝派生名称对象rename；:1488逐对象metadata绑定 | reuse P-G；不把receipt等同实际rename回读，real字段组合需要补映射 |
| set `fade_time_ms/delay_ms` | `test_field_interface_closure_gateway.py:205::test_action_fixed_durations_materialize_seconds` 精确native秒值；:340 `test_fixed_action_durations_reach_immutable_preview` 断言transaction存在且无object.set调用 | reuse P-G；extend一次真实Action时间回读，不能当已执行 |
| set `language/platform/media_files`及嵌套`inline_wav/kind/language/originals_subfolder` | OG-A:658完整子对象/import.files相等；:710在2022报 `OBJECT_SET_IMPORT_UNAVAILABLE`；OG-G:1823 `test_gateway_adds_subordinate_media_without_model_authored_json`检查公共media命令 | reuse P-A/P-G；两个source_forms都在契约，但本轮所读正例重点inline，media-file真实分支保留unresolved |
| set `object_list/list_behavior`、显式empty clear | OG-A:734具名list和replaceAll；:776精确空列表；:798 append+empty拒绝；OG-G:1983/:2081公开list declaration/clear；`test_cross_family_collection_gateway.py:92`附近Stingers clear为fake Gateway | reuse P-A/P-G；真实音乐列表顺序不是集合成员验证的等价物，不能据此授信Playlist排序 |
| set settings `name_conflict/list_behavior/add_to_source_control` | OG-C:267公开；已明确检查list mode的完整request；name-conflict/auto-add需继续追到set专属测试，不能借create全row断言 | unresolved部分字段的入口映射；扩展前先审现有Registry及跨版本tests，不新建重复测试 |

## 4. 插件与RTPC

| 公开字段／分支 | 具体测试与已读断言 | 层级／决定 |
| --- | --- | --- |
| plugin `object_handle/plugin_role/plugin_name/plugin_type_handle/field_values/language/notes/platform` | OG-C:60；OG-A:209 `test_create_plugin_compiles_role_type_and_properties_from_handles` 对完整source plugin request相等：role、name、classId、Frequency=440、English(US)、notes、Windows，参数化2022–25 | P-A；reuse全部八字段；动态classId为Gateway派生，不列用户参数 |
| source/effect角色、错误role、SFX Source不接受language选项 | OG-A:834 `test_create_plugin_rejects_type_handle_from_the_wrong_role`、:865 `test_create_plugin_rejects_language_for_sound_sfx_before_preview`：即使显式SFX也报`PLUGIN_LANGUAGE_UNAVAILABLE`；:900 hostile notes与保留名 | P-A；reuse。source正例不能替代effect拓扑 |
| effect固定slot/引用slot、追加保留旧插件 | `test_operation_plugin_registry.py:468::test_2022_effect_prepare_uses_complete_fixed_slot_snapshot_and_verifies_plugin`、:567 slot→Effect GUID、:756缺Effect引用、:799重用旧slot拒绝；WF:3234尾部连续创建两个effect，第二次仍要求完整business verify | P-V + L-def；reuse版本拓扑。需按候选核对执行记录，不将L-def当PASS |
| plugin源元数据、漂移及verifier | `test_operation_plugin_registry.py:135`重读class metadata和child guard；:278既有child漂移；:324 sealed dynamic view与requested state验证 | P-V；reuse，真实installed plugin缺失是环境条件而非普通PASS |
| RTPC `object_handle/field_handle/control_input_handle/curve_points{x,y,shape}/mode/notes` | OG-C:104；OG-A:269 `test_set_rtpc_compiles_bound_property_control_and_business_curve` 完整request相等，末点SCurve归一化Linear、mode转换、notes原值；OG-G:636 `test_gateway_builds_rtpc_curve_from_bound_business_facts`公开绑定/声明 | P-A/P-G；reuse；枚举不全排列，但必须有非末段shape的真实意义 |
| RTPC range、point limit、scope | OG-A:434越界y拒绝；:473超过256点拒绝；`test_operation_platform_rtpc.py:138/:155`精确control type与prefix lookalike拒绝 | P-A/P-V；reuse负面测试，不移植到所有Fresh任务 |
| RTPC add-only/add-or-update、空列表证明、身份保持 | `test_operation_platform_rtpc.py:266`closed append与完整list；:400独立empty proof；:662 update不replaceAll；WF:3234 `test_rtpc_empty_create_update_delete_recreate_across_selected_version`显式检查curve中点、更新GUID不变、owner重建后RTPC GUID不同 | P-V + L-def；reuse现成生命周期，不另造裸native fixture路径 |
| 2021版本与删除边界 | WF:3234在2021断言 `UNAVAILABLE_IN_VERSION`；支持版本直接delete RTPC在check前报 `EMBEDDED_OBJECT_DELETE_BOUNDARY` | reuse；函数名虽有delete，实际删除的是fixture owner，不能宣称RTPC单独删除已支持 |

## 5. 真实证据怎样复用

1. `tests/TEST_INVENTORY.md:71`记录音乐两工作流×五版本、macOS WwiseConsole 10/10，绑定历史候选`9df82a77`；范围仅媒体及Track属性、source/Clip媒体关系。`docs/research/music-import-topology-repair-2026-09-14.md`保留精确候选与弱fixture-save区别。可复用其fixture和oracle，不能借给Playlist、Transition、MIDI或Stinger播放。
2. `tests/TEST_INVENTORY.md:36`记录跨对象族65/65，包含禁止/不可用边界；只有指定149笔business-verified交易，不是65种成功mutation。多语言Voice、derived identities和音乐层级测试可复用，且没有Fresh或Windows信用。
3. WF:288 `_complete_business_draft`不只检查退出码：要求execute后`EXECUTED_UNVERIFIED`，verify后`VERIFIED`及`business_state_verified is True`。迁移用例应继续复用这一公共Draft链。对Directive弱验证必须另用相应弱结果预期，不能放宽这个强helper骗过测试。
4. WF:3011明确只选2022.1/2025.1，其他版本skip。它不能变成五版本graph/plugin/RTPC全参数覆盖证据。WF:2106的表格导入仅验证那一张createNew表及table不变，也不能给所有六字段授予live信用。
5. 本次没有重跑任何节点，未对当前HEAD宣称Program/Non-live/real/Fresh通过。历史总数只是证据定位，不是本审计的覆盖分母。

## 6. 四项追加核实与可直接实施的 Python 补项

收到进一步审计要求后，额外检查了专属business测试、`test_object_create_replace.py`、`test_object_set_merge.py`、`test_transaction_gateway.py`中的命中函数、共享字段Gateway测试及实际compiler分支。下面的confirmed gap仅指这些已审公共入口测试与对应分支之间缺少直接断言，不声称全仓库不存在任何间接执行。下层已有测试继续复用，不重写。

| 项目 | 已确认可复用的基础／为什么还不能授予公共入口覆盖 | 拟扩展位置与必要断言 |
| --- | --- | --- |
| create `rename/replace_owner_handle` | `test_object_create_replace.py:219`直接调用`parse_operation_request`；:715完整旧子树/owner准备，:961漂移复检，:986新拓扑及每个旧GUID缺席的verifier均可reuse。`test_transaction_gateway.py:2425`附近的replace命中是人工artifact摘要测试。OG-G:382只披露`--replace-owner-handle`，不是执行配置。compiler `object_graph_business.py:659–690`还有独立owner-handle解析和条件必填分支 | **extend / 公共business入口confirmed gap**：扩展OG-G现有configure测试，用一个rename正例、一个replace+已绑定owner正例、一个replace缺owner负例；断言canonical conflict、owner GUID及缺owner修复码。拒绝时机按实际声明/编译阶段检查，不能臆造revision行为。旧子树和删除回读继续reuse下层verifier，不复制 |
| set全局 settings | OG-A:734和OG-G:1983针对declaration上的`list_behavior`，不是全局settings；OG-C:267公开全局`name_conflict/list_behavior/add_to_source_control`，`object_graph_business.py:1348–1388`分别编译。`test_object_set_merge.py:884`直接prepare/verify证明native merge，不证明settings输入。schema中列举三字段也不是行为断言 | **extend / 专属public配置链confirmed gap**：在OG-G的existing+new-child基础上增加一次`draft-business-configure`，组合merge、replace-all、auto-add=True，断言完整request含`on_name_conflict=merge/list_mode=replaceAll/auto_add_to_source_control=True`；保留原有默认省略正例。另选一个无效设置值证明在dispatch前拒绝，不穷举枚举 |
| create Action时间字段 | `test_field_interface_closure_gateway.py:205/:340`只在object.set上证明250ms→0.25s、80ms→0.08s；:172的create用例是拒绝原始class/token入口，非成功创建Action。`business_fields.py:12`与OG-C:310将时间字段也公开给create | **extend / create专属路径confirmed gap**：复用OG-G long-tail type发现fixture取得Action type handle，声明有`fade_time_ms=250/delay_ms=80`的新Action，断言准确的两个秒值；结合真实Action父级规则选择fake Event fixture。先到materialization即可，已有set Preview测试不重做。若此fixture被当前公开角色规则拒绝，应将结果记能力边界并转runtime议题，不伪造类型绕过 |
| set `media-file`来源 | OG-G:1823完整函数确实只调用`--inline-wav`并断言`audio_file_base64`；OG-A:658也是inline。compiler `object_graph_business.py:247–279`有独立`media_file→audio_file`分支和恰好一个来源约束 | **extend / 来源分支confirmed gap**：将现有OG-G:1823参数化为inline-wav、media-file两种；沿用同一个language/kind/subfolder断言，仅来源key和值不同。额外选同一行同时两来源的拒绝检查；2022版本拒绝直接reuse OG-A:710，不新建整套矩阵 |

Audio Source Notes/Originals追加核查：两个字段在AI-A:83只有输入未直接assert、AI-G两字段没有对应公开声明正例；IM-P:196全row断言与IM-V Originals断言仍足以复用下层机制。另外`tests/semantic/test_codex_import_runtime_v3.py:1490::test_nonempty_audio_source_notes_mismatch_remains_strict`使用模拟backend，将source.notes改为空并断言特定mismatch失败，证明现有semantic oracle严格，但不是新business CLI字段传播证明。最小补法是在AI-A:83追加这两个结果值断言，必要时扩展现有AI-G declaration正例；不新建第二个Originals/verifier或semantic harness。

这四组是确定的实现落点，不是要求下一阶段再做一遍泛审计。新pytest节点数由扩展参数化产生，不在未实现/未收集前宣称一个精确通过数；它们也不自动等于四个Fresh任务。

## 7. 下一步的最小补充计划

| 优先级 | 工作 | 判定条件 |
| --- | --- | --- |
| P1 | 在现有AI-A:83补`audio_source_notes`与`originals_subfolder`输出断言，扩展现有AI-G declaration正例传播字段 | 下层native全row、Originals verifier及semantic notes mismatch直接reuse；不新建镜像oracle |
| P1 | 单列Switch/Dialogue导入directive业务结果义务 | 独立公开查询能证明关系才计business PASS；否则保留显式弱验证，记录能力/证据待定 |
| P1 | 建立field→公开入口→verifier→历史run四段映射 | 下层native builder测试不能补齐公共参数入口；测试定义不能补齐历史run |
| P2 | 把tab六参数的2025 Adapter正例与旧版checkout边界接入公开入口映射 | 无需把所有TSV列组合变成Fresh用例；保持原表hash不变 |
| P2 | 实施第6节四组公共入口扩展 | 复用既有fixture和下层oracle，按列出的canonical结果及拒绝边界验收；不借历史native测试给business入口补分 |
| P2 | 复用插件版本slot与RTPC生命周期到少量新Agent集成案例 | 选能改变业务结果的分支，保留插件安装条件、2021不可用与禁止删除边界 |

## 未审范围与禁止外推

本文件不是全仓库的参数覆盖报告；没有逐项完成query、topics、其他Core/SoundEngine/UI/CLI业务契约、所有semantic kinds、全部插件类型、全部属性类型、所有控制点形状与平台组合，也未遍历所有ignored evidence根。第3节初筛标unresolved的四组已由第6节收敛为具体公共入口补项；真实运行信用及其余未映射字段仍不外推。音乐Playlist树顺序、Transition调度、MusicSwitch多组路径不因generic object.set或原生文档存在而成为已通过能力。

本阶段不产出“完整覆盖率”或承诺固定新增测试数量。后续在各审计分片汇合后生成义务清单，再决定哪些Python节点直接复用、哪些扩展、哪些进入用户要求的新Agent集成案例。该清单以公共参数与可观察业务结果为分母，不以native API字段数、pytest通过总数或历史六workflow数代替。
