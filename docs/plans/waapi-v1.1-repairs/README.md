# WAAPI v1.1 修复：任务入口

状态：用户已确认；规格 [#163](https://github.com/zcyh147/waapi-skill/issues/163) 与九张任务票已发布，已于 2026-10-17 开始实现，任务票已改为英文。实现覆盖 Wwise 2021.1–2025.1，明确验证底层不可用的版本边界。

先读 [规格](SPEC.md)，再看下面的任务拆分。全部测试以公开 Gateway 行为为主；四个 Fresh 工作流只安排 Mac。

| 票 | 交付 | 前置票 |
| --- | --- | --- |
| [01](tickets/01-audit.md) | 审计全分支覆盖与 ShareSet 漏项 | 无 |
| [02](tickets/02-connection.md) | 所有正常操作只使用配置连接 | 无 |
| [03](tickets/03-metadata.md) | 列属性、准确查详情并分页 | 无 |
| [04](tickets/04-dependencies.md) | 支持衰减引用的条件依赖 | 无 |
| [05](tickets/05-gameparameter.md) | 完成 GameParameter 创建与范围配置 | 03 |
| [06](tickets/06-shareset.md) | 创建独立 Effect ShareSet 并拒绝错误目标 | 无 |
| [07](tickets/07-recovery.md) | 普通失败后在三种模式内继续 | 无 |
| [08](tickets/08-cleanup.md) | 从产品输出移除测试工程清理指令 | 无 |
| [09](tickets/09-acceptance.md) | 集中验收并交付准确覆盖结论 | 01,02,03,04,05,06,07,08 |

## 建议顺序

先交付 01 覆盖审计初稿，同时可处理 02 配置和 08 清理。随后 03 属性查询、04 条件依赖、05 GameParameter、06 ShareSet、07 继续规则；最后 09 集中验收。表中仅表示真正阻塞关系，不要求并行 Agent。

01 的新发现若超出已确认范围，单独列票，不自动加入本轮。09 再核对最终覆盖账本。

## 测试预算

- 纯代码：五版本覆盖与完整 Program/Non-live，无人为缩减覆盖；避免无变化重复跑。
- 真实 Wwise：现有 Python 测试及沙盒，按变更所需版本顺序执行，无 Fresh 模型费用。
- Fresh：首轮 F1–F4 共四个工作流，仅 Mac，拟用 2025.1；不是四次模型调用。额外 Fresh/重跑须先说明并获批准。
- Windows：本轮不跑 Fresh，不写 native Windows 验收通过。

## GitHub 任务

- 01：[#164](https://github.com/zcyh147/waapi-skill/issues/164)
- 02：[#165](https://github.com/zcyh147/waapi-skill/issues/165)
- 03：[#166](https://github.com/zcyh147/waapi-skill/issues/166)
- 04：[#167](https://github.com/zcyh147/waapi-skill/issues/167)
- 05：[#168](https://github.com/zcyh147/waapi-skill/issues/168)
- 06：[#169](https://github.com/zcyh147/waapi-skill/issues/169)
- 07：[#170](https://github.com/zcyh147/waapi-skill/issues/170)
- 08：[#171](https://github.com/zcyh147/waapi-skill/issues/171)
- 09：[#172](https://github.com/zcyh147/waapi-skill/issues/172)

已设置 GitHub 原生父子关系和阻塞依赖。
