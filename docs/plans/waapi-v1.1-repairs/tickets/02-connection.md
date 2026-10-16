# 02：所有正常操作只使用配置连接

**规格：** [#163](https://github.com/zcyh147/waapi-skill/issues/163)

**GitHub：** [#165](https://github.com/zcyh147/waapi-skill/issues/165)

**状态：** ready-for-agent（已发布，尚未开始实现）

**交付：** 用户设置一次配置，所有只读和写操作使用该配置；已有 Draft/事务不因 CLI 参数丢失而切换工程。

**Blocked by：** 无

## 验收条件

- [ ] 取消普通在线业务的 host/port/version 临时 flags 与连接环境覆盖；保留 config-set 与离线版本浏览。
- [ ] 独立副本明确关联独立配置，不误认为目录复制会隔离默认用户配置。
- [ ] 草稿硬盘记录选定连接，首次 live 绑定版本/build/项目 GUID，Preview/事务继续保存；无 Draft 路由也走统一配置。
- [ ] 每步先比较配置与已存绑定；配置变化、实际版本/项目变化均在业务派发前拒绝，不静默回退。
- [ ] 覆盖重启 CLI、config 变更、旧状态缺字段及所有 continuation；维护测试启动器改用隔离配置。
- [ ] 更新公开 schema/help/Skill 与受影响的配置指导，不靠 Agent export 环境变量。

## 验证

Gateway 端到端 fake tests 覆盖五版本和 Windows 命令形态；沙盒读取证明正确连接，不访问另一个用户工程。F1–F4 共用新配置路径，不另加 Fresh。

## 执行约束

使用规格中的测试预算和公开 Gateway 边界；运行前重新确认当前候选及仓库指导。不得操作 Lyra 正式工程或重放现场事务。先补可复现行为测试再修实现，完成后报告实际证据及限制。
