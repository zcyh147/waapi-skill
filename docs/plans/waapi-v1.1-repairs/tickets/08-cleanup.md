# 08：从产品输出移除测试工程清理指令

**规格：** [#163](https://github.com/zcyh147/waapi-skill/issues/163)

**GitHub：** [#171](https://github.com/zcyh147/waapi-skill/issues/171)

**状态：** ready-for-agent（已发布，尚未开始实现）

**交付：** 正常生成/导入/替换后保留用户工程与产物，只有测试运行器处理自己创建的临时副本。

**Blocked by：** 无

## 验收条件

- [ ] 移除正式结果中的 discard case-owned project、seal/never reuse 等测试指令。
- [ ] 遍查所有 Preview、成功、失败、indeterminate 和 legacy projection，清理同类残留，不只改 SoundBank。
- [ ] 必要的配对资源释放仍保留，明确与工程/输出删除分开。
- [ ] 测试生命周期继续凭资源所有权执行原清理和隔离规则，不依赖产品输出猜测。
- [ ] 保留历史记录与失败证据；许可证失败独立归因。

## 验证

Gateway 输出测试覆盖持久工程各终态、import/replace/generate；测试运行器的资源所有权/清理回归。无需额外 Fresh。

## 执行约束

使用规格中的测试预算和公开 Gateway 边界；运行前重新确认当前候选及仓库指导。不得操作 Lyra 正式工程或重放现场事务。先补可复现行为测试再修实现，完成后报告实际证据及限制。
