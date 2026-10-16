# 09：集中验收并交付准确覆盖结论

**规格：** [#163](https://github.com/zcyh147/waapi-skill/issues/163)

**GitHub：** [#172](https://github.com/zcyh147/waapi-skill/issues/172)

**状态：** ready-for-agent（已发布，尚未开始实现）

**交付：** 在同一冻结候选上完成程序、相关真实 Wwise 及四个 Mac Fresh 工作流，并明确交付范围。

**Blocked by：** 01,02,03,04,05,06,07,08

## 验收条件

- [ ] 固定五版本 Program、完整 Non-live 完成；真实 Wwise 用沙盒顺序执行，缺前提不算 PASS。
- [ ] 复用正式 harness 形成 F1 属性/分页/配置、F2 查询失败后继续、F3 GameParameter 创建配置、F4 ShareSet 创建四项 Mac 工作流，各首轮一次。
- [ ] 花费前固定候选/版本/模型/选项/回合与事务数，先证明所需插件许可可用和程序前提。
- [ ] Windows 不跑 Fresh，不宣称 native Windows 已验收；不推定 Wine 行为等于 Windows。
- [ ] 普通失败完成冻结批次再修；额外 Fresh 或重跑先报告理由/数量并获批准，不启动全量矩阵。
- [ ] 复核审计账本与最终实现，保留 raw verdict，业务结果与判定分别报告；不改写旧失败。
- [ ] 交付代码/范围/验证/未解决漏项，README 与测试计数只引用实际完成运行。

## 验证

此票负责组合 gate、现有 code-review 的标准/规格审查及预算受控的 Fresh，不重复逐票已充分完成的无关 live 场景。

## 执行约束

使用规格中的测试预算和公开 Gateway 边界；运行前重新确认当前候选及仓库指导。不得操作 Lyra 正式工程或重放现场事务。先补可复现行为测试再修实现，完成后报告实际证据及限制。
