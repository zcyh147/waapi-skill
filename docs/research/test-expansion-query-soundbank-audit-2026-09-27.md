# 测试扩充：查询与 SoundBank 的补充审计

日期：2026-09-27。静态基线：`284899536fc469cecf075643d3942ddc3f98d04e`。
本文件只记录阅读代码和断言所得结论，没有运行测试或连接 Wwise。引用的测试实现不是本次 PASS。

## 判断口径

公开契约定义输入分母；具体测试的输入、被调用路径和断言定义已有覆盖。测试名称、字符串搜索命中、native 请求构造测试、历史 passing 数量均不能单独证明当前公开字段已覆盖。

本文件补充三个子审计之外的查询、SoundBank 和媒体读取；这是有明确范围的逐项核对，不是全仓所有公开参数已经闭合。特别是动态属性、Advanced 查询表达式和外部插件不能假定存在有限的“全部字段”分母。

## SoundBank：优先复用，不另增一个普通发布故事

公开定义：`skills/waapi-skill/wwise_waapi/soundbank_business_contracts.py`，`_DECLARATIONS` 与 `_DECLARATION_SCHEMAS`。

| 公开输入/分支 | 已读的测试及实际断言 | 审计决策 |
| --- | --- | --- |
| generate 的 soundbanks、platforms、io_root；bank 的 handle、artifact_expectation、rebuild、event_handles、aux_bus_handles、inclusions | `tests/unit/test_soundbank_business_adapter.py::test_generate_business_plan_derives_native_rows_and_language_switch` 比较完整 materialized request；nonlocalized、rebuild=false、Event/AuxBus 和三种 inclusion 均有代表值 | 复用程序测试，不因新案例库再写一份同构测试 |
| languages、localized、bank rebuild=true、clear_audio_file_cache=true | `tests/unit/test_soundbank_business_gateway.py::test_generate_plan_binds_business_objects_and_derives_native_switches` 从 Draft 声明入口到 materialize，完整比较 languages、skip_languages=false、字段与路径 | 有公开入口正向程序覆盖；不能由此推导真实多语言产物正确 |
| rebuild_soundbanks、clear_audio_file_cache、rebuild_init_bank 的显式 false | 同文件 `test_generate_plan_preserves_every_explicit_false_rebuild_choice` 逐项比较生成的 arguments，防止 false 被当成省略 | 满足“每参数至少一个有效值”的这一代表性要求；若评估 true 的独立语义，另列分支，不能称该测试已测 true |
| setInclusions 的 soundbank_handle、mode、inclusions[].object_handle/filters | Adapter 的 `test_set_inclusions_business_plan_compiles_bound_objects`，Gateway 的 `test_set_inclusions_binds_objects_then_declares_only_business_rows` | 公共字段已有代表性编译断言；add/remove/replace 的完整状态覆盖另看 live 证据 |
| replace + 空 inclusions | Adapter 的 `test_replace_may_clear_one_soundbank_without_synthesizing_rows`；另有上限 128/129 的测试 | 复用，不把非空 replace 当作清空分支 |
| convertExternalSources 的 sources[].input/platform/output、io_root | Gateway 的 `test_external_source_plan_keeps_exact_artifacts_inside_business_envelope`，Adapter 的 `test_exact_soundbank_artifacts_remain_exact_inside_gateway_envelope` | 现有测试是复用入口；真实转换产物仍需按已有 campaign/real case 的具体范围记账 |
| processDefinitionFiles 的 files、io_root | Gateway 的 `test_definition_file_plan_is_one_complete_offline_business_declaration` 与上述 exact-artifact Adapter 测试 | 复用公开声明与精确文件边界测试，不追加普通接口题 |

`tests/destructive/test_gateway_workflow_transaction_matrix.py` 内已有 add→remove→replace→clear 的 inclusion 状态断言，以及 generate/external-source 流程。这里不把该文件中所有历史 helper 用法直接计为最新 Agent 公共接口覆盖；迁移后的调用入口与 completed run 候选仍要匹配。

现有 Harbor 集成已经承担普通 SoundBank 发布。若以后新增 localized/mixed 发布，必须以“语言产物与非本地化产物的完整集合不同”为增量理由，而非换个 SoundBank 名称。本轮 17 个候选无需额外再加一个普通发布案例。

## 查询：嵌入业务案例，避免每个 predicate 单开 Fresh

公开来源是 `skills/waapi-skill/scripts/gateway.py` 中 `QUERY_BUSINESS_PREDICATES`、`QUERY_BUSINESS_RELATIONSHIPS`、`QUERY_BUSINESS_OUTPUTS` 与 `query-schema`；不能从旧 typed-query helper 反推公开输入。

| 已读测试（均位于 `tests/unit/test_waapi_gateway.py`） | 已证明的程序行为 | 对新案例的用途 |
| --- | --- | --- |
| `test_query_object_compiles_business_predicates_without_native_tuple_fields` | volume-db-at-most 与 notes-contain 编译成准确有界条件 | C02/C06 的候选筛选可复用，不需要新造“音量查询”接口级 Fresh |
| `test_query_object_compiles_closed_business_kind_predicate_without_native_type` | descendants + kind-is(sound-voice) 使用正确类型和 Voice 条件 | C01 的 Voice 查询；不能将 Sound SFX 结果当 Voice |
| `test_query_object_compiles_and_renames_business_and_custom_outputs` | 五版本参数化；返回 volume_db/output_bus 及 live metadata 绑定的自定义 property/reference，精确比较 agent_result 和 return projection | 动态字段与引用查询已有公开入口断言，实际对象族需要真实 fixture |
| `test_query_object_event_children_expose_closed_action_target_without_metadata_scope`、`test_query_object_event_actions_preset_owns_bound_and_projection` | ActionType/Target 与预设输出边界已有专项测试 | C10 搬迁后的 Event Target 独立读取可从这些现有公共路径设计 |
| `test_multi_object_query_returns_conditional_selected_subset_readbacks` | 多候选返回后、用户选择子集的精确回读指引 | 在有近似/同名对象的业务中测试 Agent 选择，不按查询数量机械判分 |
| `test_query_object_detail_restores_compiler_and_dispatch_evidence`、`test_query_object_success_projection_preserves_terminal_agent_result_exactly` | 默认紧凑视图与诊断视图、终端结果保持 | 不要求 Agent 为成功查询重复加 detail，只为满足日志外形 |
| `test_query_object_original_file_reference_match_returns_closed_candidate_records` 及同族 ceiling/duplicate/version negatives | 2025 文件引用匹配有专门有界读取与负例 | 不能把该版本独有读法扩写为五版本同一工作流 |

进一步核对 `QUERY_BUSINESS_PREDICATES` 的四类值与特殊 kind 分支，并在 tests 的 Python/JSON 中搜索公开 token、常量名及 schema 动态遍历后，确认一个值得补充的**程序测试候选**：现有公开 Gateway 正例清楚覆盖 string、number 与 kind；`children-at-least` 的 integer 正例只找到文档文本断言，boolean 的 `included-is` 找到语义 recipe/Broker 用例，尚未找到相应公开 Gateway fake-dispatch 正向断言。建议补一组 integer 和 boolean 的代表值，通过公开入口断言精确派发与返回；实施前再核对 recipe 是否实际调用 Gateway，已有则登记复用。它不需要独立 Fresh 任务，也不要求把十三种 predicate 全排列。搜索结果本身不作为“全仓完全没有覆盖”的证明。

尚未完成的工作是每一个公开 source/predicate/output 到正向断言的全表 join。本次证据足以否定“查询没有程序覆盖”，但不提供查询参数 100% 的分母或比例。实施前若某案例使用这里未映射的字段，先补映射，只有没有对应断言时才新增测试。

## 媒体读取：已有业务结果比较，非本轮 Agent 扩充主轴

公开字段位于 `media_build_business_contracts.py`。

- `tests/unit/test_media_build_business_gateway.py::test_media_pool_core_call_binds_live_fields_and_returns_business_rows` 实际经过 core-call，输入 max_results、database_scopes、search_text、text_filters、return_field_meanings、exact_name_contains、final_limit、sort_rules。它比较完整业务结果（含顺序、数量、字段值、数据库身份）和实际派发请求。不能将这些字段列作已确认的 Python 缺口。
- 同文件 `test_media_pool_exact_case_filter_fails_closed_at_candidate_ceiling` 专门检查候选集到上限时不能把客户端筛选结果谎称完整。
- `test_peak_region_core_call_returns_decoded_business_result` 和 Adapter 的 `test_peak_region_business_read_compiles_and_decodes_known_pcm_pairs`、`test_cross_channel_peak_result_requires_one_returned_channel` 已覆盖波峰请求与解码一致性。
- 音频相似度、权重、number_filters、数据库 ID 等其余字段需要逐项读完对应断言后再判定；本次没有将未细审字段自动标成缺测，也不因此扩大 17 个 Agent 候选。

## 范围外项目如何处理

本轮业务扩充集中于 Authoring 内容编辑。SoundEngine、profiling/debug、Lua、Source Control provider、Authoring UI commands、Topics 的生命周期与环境依赖不同，不从这 17 个案例获得覆盖信用。现有测试与公开契约保留，不删除、不追加通用“全部 API”语义矩阵。

若最终要求是全 Skill 每个公开参数都具有真实执行证据，应继续完成这些领域的分母与证据映射，单独预算；当前候选集不作该承诺。
