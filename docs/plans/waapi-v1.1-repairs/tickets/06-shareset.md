# 06：创建独立 Effect ShareSet 并拒绝错误目标

**规格：** [#163](https://github.com/zcyh147/waapi-skill/issues/163)

**GitHub：** [#169](https://github.com/zcyh147/waapi-skill/issues/169)

**状态：** ready-for-agent（已发布，尚未开始实现）

**交付：** 用户能明确选择给对象添加效果或在 Effects Work Unit 下创建独立 ShareSet，两种用途都生成正确请求。

**Blocked by：** 无

## 验收条件

- [ ] 公开契约披露放置用途及目标要求，插件由现场 Type Handle 决定。
- [ ] 实现经验证的 Work Unit children ShareSet 创建结构，与 owner EffectSlot 路径区分。
- [ ] 错误目标、插件不可用、冲突在写入前拒绝；不将 Work Unit 当效果槽 owner。
- [ ] 独立解析 ShareSet 结果并验证 GUID/父对象/类型/名称/参数，空对象结果不能报成功。
- [ ] 支持版本明确；回归已有插件实例路径，2022.1/2025.1 差异有针对性证据。

## 验证

公开 Gateway tests；无额外许可证插件的沙盒 ShareSet 创建及读回。通过已公开或此票新增的元数据路径配置，不能先假定 03 必须完成。最终 F4。

## 执行约束

使用规格中的测试预算和公开 Gateway 边界；运行前重新确认当前候选及仓库指导。不得操作 Lyra 正式工程或重放现场事务。先补可复现行为测试再修实现，完成后报告实际证据及限制。
