[English](./README.md) · [简体中文](./README.zh-CN.md)

# Wwise WAAPI Skill

这个 skill 用来通过 **WAAPI 自动化 Wwise Authoring**，采用的是**版本感知（version-aware）**、**Python 优先**的本地工作流。

它面向的是**任何可以加载 skill 目录和本地辅助脚本的 agent / 工具运行器**，不是绑定某一个特定的编码助手，也不依赖单独部署的 MCP server。

---

## 这个 skill 解决什么问题

当任务涉及以下内容时，这个 skill 很有用：

- 查询 Wwise 对象和工程状态
- 用结构化意图来构建 WAAPI 请求，而不是临时手写 payload
- 同时适配多个 Wwise 版本
- 在执行工程修改前先生成 preview
- 让行为能力建立在真实测试之上，而不是只靠文档描述

它本质上提供的是一套 **skill-local 的 WAAPI 工具链**：本地 runner、版本化 manifest、semantic builders、dispatcher、bounded subscriptions，以及一整套安全约束。

## 为什么需要它

通用 agent 可以“谈论” WAAPI，但这不等于它能稳定地“操作” Wwise。

真正容易出问题的地方通常不是第一条 API 调用，而是：

- 选错 Wwise 版本
- 没有加载该版本对应的约束
- 把过大的 schema / docs 塞进 prompt 里
- mutation safety 和确认流程做得不严谨
- 对“支持能力”的判断只基于文档而不是基于真实验证

这个 skill 的价值就在于：它用一套**本地、版本感知、按需加载**的运行模型来解决这些问题，而不是只靠 prompt 里的泛化说明。

---

## 主要优势

### 1. 按需加载，而不是把所有资料一次性塞进上下文

这个 skill 不会在一开始就把所有参考文档全部灌进上下文。

它只会按当前任务和版本加载所需资源，包括：

- `resources/manifest/<version>/`
- `resources/semantic/<version>/`
- `resources/waql/<version>/`
- `resources/deferred/<version>.json`

这样做的好处是：更聚焦、更容易控边界，也更适合多版本支持。

### 2. 多版本支持是内建能力，不是事后补丁

当前支持：

- `2021.1`
- `2022.1`
- `2023.1`
- `2024.1`
- `2025.1`

这个 skill 不会假装“一个 WAAPI prompt 能通吃所有版本”。它把 manifest、semantic notes、WAQL 资源和 deferred registry 都按版本拆开，让 agent 明确地在正确版本表面上工作。

### 3. 更安全的 mutation 工作流

工程修改不是随手就做的 follow-up。

这里支持的是：

- 普通 inspection 请求优先走 read-only 路径
- preview-then-confirm 的 mutation 流程
- semantic plan 的 preview hash 确认
- bounded destructive opt-in
- 执行后 verification / readback

### 4. 不只是“文档接入”，而是有完整测试体系

这个仓库不只是有文档，它还有：

- unit tests
- live read-only validation
- destructive sandbox validation
- semantic behavior validation
- version-scoped review packets 和 evidence model

目标不是“把 WAAPI 讲对”，而是“让 skill 在真实使用里做对”。

---

## 和 Wwise MCP 的区别

这个 skill 和 Wwise MCP server 有重叠，但不是同一种工具。

### 这个 skill 更强的地方

- **按需加载资源**，而不是默认把大范围内容长期挂在上下文里
- **版本化运行资源**，覆盖 `2021.1` 到 `2025.1`
- **skill-local 的 Python 工作流**，不需要单独起 server
- **更明确的 preview / confirm authoring 流程**
- **仓库内测试体系更完整**，包括 sandbox 和 semantic validation

### MCP server 可能更适合的地方

- 需要长期驻留的协议型工具暴露
- 你的客户端体系本来就统一在 MCP 上
- 你想要的是 server boundary，而不是 skill-local runtime

### 一个简单的选择原则

如果你要的是：

- 本地 skill 包
- 版本感知的 WAAPI 辅助能力
- 更严格的 mutation safety
- 依赖仓库本地资源、按需加载、测试充分的行为模型

那么这个 skill 更合适。

如果你要的是：

- 持久 server 集成
- MCP 客户端通用接入
- 以协议服务为中心的工具暴露

那么 MCP server 更合适。

---

## 核心能力

### 版本感知的 manifests 和 semantic resources

这个 skill 使用反射生成的 manifest 和按版本组织的 semantic notes，让 agent 能在正确的 WAAPI 表面上工作，而不是把所有版本当成一样。

### Semantic planner + dispatcher 模型

正常路径大致是：

1. 检测或选择 Wwise 版本
2. 抽取结构化 semantic intent
3. 生成 semantic preview 或直接 read-only plan
4. 通过验证过的 WAAPI dispatch 层执行
5. 对结果做 verification

### 优先支持 read-first 的安全 inspection

当 config 和连接信息已经明确时，普通 inspection 请求应优先直接执行 read-only 路径，而不是先漂移到文档研究模式。

### Bounded topic handling

支持 topic waits，但采用的是有边界的等待模型，而不是假设无限期 listener 生命周期。

### Unsupported boundary 明确返回

对于 scheduler-like delayed runtime posting、Game Object View emitter control、timed runtime sequencing、cross-app federation 等能力边界，skill 会明确返回 unsupported，而不是模糊成“看起来好像支持”。

---

## 快速开始

### 1. 初始化本地环境

在仓库根目录下先进入 skill 目录：

```bash
cd skills/waapi-skill
```

然后运行：

```bash
python scripts/run.py --help
python scripts/run.py setup_environment.py
```

### 2. 配置版本和 WAAPI endpoint

持久化配置在：

```text
skills/waapi-skill/data/config.json
```

公开的持久化字段故意保持很小：

- `wwise_version`
- `waapi_host`
- `waapi_port`
- `project_modification_policy`

### 3. 使用 skill-local runner

低层示例：

```python
from wwise_waapi import WwiseDispatcher

result = WwiseDispatcher(client=waapi_client).dispatch(
    "ak.wwise.core.getInfo",
    version="2025.1",
    args={},
    options={},
    timeout=10.0,
    dry_run=False,
    allow_destructive=False,
)
```

### 4. 非 trivial 任务优先走 semantic planning

对于 authoring、imports、soundbanks、switch assignments、结构化多步任务，优先用 semantic planner，而不是直接从零开始手写 WAAPI payload。

---

## 安全模型

- destructive operations 默认阻止
- project-changing steps 应先 preview 再执行
- semantic plan 的确认必须匹配当前 preview artifact
- unsupported runtime boundary 要清楚失败，而不是假装支持
- evidence、runtime data、local auth state 默认保持本地

这个 skill 追求的是**边界诚实、行为可复核**，不是“什么都答应”。

---

## 测试理念

这里非常重视验证层。

仓库里有几层测试：

- **unit tests**：builder、dispatcher、resource layout、contract rules
- **live read-only tests**：验证真实 WAAPI inspection 行为
- **destructive sandbox tests**：验证复制工程上的 mutation 安全性
- **semantic validation**：验证 agent 在本地 skill workspace 里的真实行为

核心原则很简单：支持声明应来自执行过的验证，而不是来自复制文档或乐观措辞。

---

## 目录结构

```text
.
├── README.md
├── README.zh-CN.md
└── skills/
    └── waapi-skill/
        ├── SKILL.md
        ├── data/
        ├── resources/
        ├── scripts/
        └── wwise_waapi/
```

关键路径：

- `skills/waapi-skill/SKILL.md` — skill contract
- `skills/waapi-skill/scripts/run.py` — skill-local runner
- `skills/waapi-skill/wwise_waapi/dispatcher.py` — 验证过的 WAAPI dispatch
- `skills/waapi-skill/wwise_waapi/semantic_planner.py` — 结构化 semantic planning
- `skills/waapi-skill/wwise_waapi/builders/` — preview-oriented builders
- `skills/waapi-skill/resources/manifest/<version>/` — 反射生成的版本化 manifests
- `skills/waapi-skill/resources/semantic/<version>/` — semantic source-note resources
- `skills/waapi-skill/resources/waql/<version>/` — WAQL guidance resources
- `skills/waapi-skill/resources/deferred/<version>.json` — 显式 deferred / unsupported 边界

---

## 什么时候该用它

当任务提到以下内容时，就应该考虑这个 skill：

- Wwise
- WAAPI
- Audiokinetic authoring APIs
- Wwise version selection
- object queries / creation / mutation / import / soundbanks / switch assignments
- bounded topic subscriptions
- safe destructive preview 或 sandbox validation

---

## FAQ

### 这个 skill 绑定某个特定 agent 吗？

不绑定。它是一个本地 skill 包，包含 Python helpers 和 markdown guidance。任何能加载并遵循 skill 目录的本地 agent 工作流都可以使用。

### 它是 MCP server 吗？

不是。它是 skill-local workflow，不是独立的 MCP 服务。

### 它真的支持多个 Wwise 版本吗？

支持，而且这是核心设计目标之一。

### 它能替代真实测试吗？

不能。它的设计目标是和真实验证体系协作，而不是替代 unit / live / destructive / semantic tests。

---

## 总结

这不是一个泛泛的文档包装器，而是一个真正的 **Wwise WAAPI skill**。

它的优势主要在于：

- **按需加载**
- **多版本支持**
- **结构化 semantic planning**
- **更安全的 mutation flow**
- **测试覆盖更完整**

如果你想要的是一个本地的、版本感知的、经过充分验证的 WAAPI skill，而不是一个长期驻留的通用 server 抽象，那么这就是更合适的形态。
