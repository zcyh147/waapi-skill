# 04：支持衰减引用的条件依赖

**规格：** [#163](https://github.com/zcyh147/waapi-skill/issues/163)

**GitHub：** [#167](https://github.com/zcyh147/waapi-skill/issues/167)

**状态：** ready-for-agent（已发布，尚未开始实现）

**交付：** 用户给 Sound/容器关联衰减，Gateway 将必要定位设置纳入 Preview 并验证结果。

**Blocked by：** 无

## 验收条件

- [ ] 解析本次 conditions/property/override 依赖，不仅放宽字段白名单。
- [ ] 已满足依赖不多改；重复项去重；冲突、循环、未知结构在派发前明确拒绝。
- [ ] 预览列明引用及必要属性变化，执行后读回两者并证明无关属性未变。
- [ ] 通过公开 object.set 路径完成 Sound 和容器场景，各版本支持状态明确。

## 验证

真实故障元数据作为固定测试输入，五版本程序负例；2025.1 沙盒关联与独立读回。无单独 Fresh。

## 执行约束

使用规格中的测试预算和公开 Gateway 边界；运行前重新确认当前候选及仓库指导。不得操作 Lyra 正式工程或重放现场事务。先补可复现行为测试再修实现，完成后报告实际证据及限制。
