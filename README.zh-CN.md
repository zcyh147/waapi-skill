[English](./README.md) · [简体中文](./README.zh-CN.md)

# Wwise WAAPI Skill

这个 skill 用来通过 **WAAPI 自动化 Wwise Authoring**，采用的是**版本感知（version-aware）**、**gateway 优先**的本地工作流。

它面向的是**任何可以加载 skill 目录和本地辅助脚本的 agent / 工具运行器**，不是绑定某一个特定的编码助手，也不依赖单独部署的 MCP server。

---

## 这个 skill 解决什么问题

当任务涉及以下内容时，这个 skill 很有用：

- 查询 Wwise 对象和工程状态
- 把结构化意图路由到已经封装好的 gateway 命令，而不是临时手写 payload
- 同时适配多个 Wwise 版本
- 在执行工程修改前先生成 preview
- 让行为能力建立在真实测试之上，而不是只靠文档描述

它本质上提供的是一层 **skill-local 的 WAAPI 接口**：本地 runner、单一 packaged gateway、版本化 manifest、有边界的 topic wait、闭合 transaction operation，以及安全约束。

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
- 由 Gateway 签发、绑定不可变 transaction preview 的确认 token
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

## Packaged API 覆盖情况

覆盖率按 **Wwise 版本/API 行**统计，因为同一个 URI 在不同 Wwise 版本中可能具有不同的 schema、执行路由或安全结论。只有 packaged gateway 能真正执行的行才算覆盖；只返回 hard boundary 或只提供文档说明不算覆盖。

| Wwise 版本 | 反射总行数 | 可执行行数 | 可执行 functions | 可执行 topics | 排除行数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2021.1` | 126 | 119 | 93 | 26 | 7 |
| `2022.1` | 144 | 137 | 106 | 31 | 7 |
| `2023.1` | 181 | 170 | 139 | 31 | 11 |
| `2024.1` | 178 | 168 | 139 | 29 | 10 |
| `2025.1` | 185 | 175 | 145 | 30 | 10 |
| **合计** | **814** | **769** | **622** | **147** | **45** |

这 769 个版本/API 行对应 **188 个唯一可执行 WAAPI URI**，分别通过 fixed command、bounded direct call、bounded topic wait、确认式 transaction、隔离 I/O transaction，或同连接 Undo Group 组合执行。45 个排除行对应 12 个唯一 URI，仅限任意 Lua 执行、危险/private debug 接口，以及不受限的 UI command 注册与执行。

命名操作层还为 `ak.wwise.core.object.create`、`ak.wwise.core.object.set`、`ak.wwise.core.audio.import`、`ak.wwise.core.audio.importTabDelimited`、`ak.wwise.core.soundbank.generate`、`ak.wwise.core.soundbank.convertExternalSources` 和 `ak.wwise.core.soundbank.processDefinitionFiles` 提供闭合、按版本约束的业务合同。`object.create`、两种导入和 `soundbank.generate` 覆盖五个版本；`object.set`、External Sources 转换和 Definition Files 处理从 `2022.1` 起提供，因为 `2021.1` 清单没有这些 URI。Wwise `2021.1` 的 SoundBank 生成只从实时 Project 的 `filePath`、`workunitIsDirty` 和受约束、带哈希、严格解析的 `.wproj` 获取工程上下文；后续版本绑定实时 `core.getProjectInfo`。一旦 URI 已有实现完成的命名操作，generic `waapi.call` 会以 `DEDICATED_OPERATION_REQUIRED` 拒绝该 URI，避免原始 payload 绕过专用合同。

当前固定的纯程序 gate 包含 **1457 项程序测试**，其中每一个已覆盖的版本/API 行都有一项可执行路由用例，并覆盖由 gateway 提供的会话提示上下文和上述命名操作的合同/验证矩阵。它验证 packaged 路由、schema、安全边界、I/O 约束、transaction 行为、fake dispatch 执行和确定性的 onboarding 信息；这不等于已经在真实 Wwise 进程中逐一运行了全部 769 行。另有一轮关闭 memory 的 `h80-release-c38` 真实 Wwise campaign，已通过全部 80 个获批重型 API 场景（2022.1 为 70 个，2024.1 和 2025.1 各 5 个）；这份证据只覆盖这些场景及其封存候选版本，不代表整个接口都做过真实语义测试。完整口径见[五版本覆盖契约](./skills/waapi-skill/references/waapi-coverage.md)。

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

### Packaged gateway 执行模型

正常路径大致是：

1. 检测或选择 Wwise 版本
2. 为意图选择固定的 packaged gateway 路由
3. 执行直接 read-only 命令，或生成不可变 mutation preview
4. 只通过闭合 transaction 路由确认和执行
5. 对结果做 verification

### 优先支持 read-first 的安全 inspection

当 config 和连接信息已经明确时，普通 inspection 请求应优先直接执行 read-only 路径，而不是先漂移到文档研究模式。

### Bounded topic handling

支持 topic waits，但采用的是有边界的等待模型，而不是假设无限期 listener 生命周期。命令 timeout 是端到端预算，事件等待会从中预留一小段时间用于 unsubscribe、写 evidence 和关闭 transport。成功的 `wait-topic` 会把校验后的 WAAPI publish payload 直接放在 `event` 下，dispatcher 内部 callback envelope 不会泄漏到公开结果。不要用目标最终名称匹配 `object.created`，因为通知发生时命名尚未完成。对于 packaged ActorMixer 探针，Wwise 2021.1-2024.1 在通知时报告 `ActorMixer`，Wwise 2025.1 则报告底层 `PropertyContainer`；需要证明事件归属时，应把返回的对象 GUID 与可信 publisher 的 GUID 对账。

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

Runner 只接受 packaged `gateway.py` 和 `setup_environment.py` 两个入口。未知、绝对路径、越界或 symlink script target 即使在本地真实存在也会被拒绝。

### 2. 配置版本和 WAAPI endpoint

正常的持久化配置位于已安装 Skill 之外。Gateway 会按以下顺序使用第一个可用路径：

```text
$WAAPI_SKILL_CONFIG_PATH
$XDG_CONFIG_HOME/waapi-skill/config.json
$HOME/.config/waapi-skill/config.json
```

只通过 `gateway.py config-show` 和 `gateway.py config-set` 查看或修改配置，不要手动编辑。
`skills/waapi-skill/data/config.json` 只是在外部配置不存在时使用的只读旧版兼容回退，
永远不是正常写入目标。

公开的持久化字段故意保持很小：

- `wwise_version`
- `waapi_host`
- `waapi_port`
- `project_modification_policy`

### 3. 所有 read-only 工作都走 gateway

无需拼装 WAAPI 代码即可检查实时版本/工程并查询对象：

```bash
python scripts/run.py gateway.py status
python scripts/run.py gateway.py query-object \
  --path '\Events\Default Work Unit' \
  --return-field id --return-field name --return-field type --return-field path
```

### 4. 工程修改必须走 closed transaction lane

先查询 packaged request contract。`preview` 会返回不可变 transaction id 和供审核的完整
artifact hash。用户在后续消息中确认该 preview 后，先用
`transaction-show --summary-only` 重新读取已保存的 transaction；其结果会提供一个与当前状态绑定的短
`confirmation.token` 和准确的下一条命令。正常确认流程使用这个 token：

```bash
python scripts/run.py gateway.py operation-schema object.setNotes
python scripts/run.py gateway.py preview \
  --request-json '{"contract":"waapi-skill.operation-request/v1","operation":"object.setNotes","arguments":{"object":{"kind":"path","value":"\\Events\\Default Work Unit\\Target"},"value":"Reviewed"}}'
python scripts/run.py gateway.py transaction-show <transaction-id> --summary-only
python scripts/run.py gateway.py confirm <transaction-id> --confirmation-token <confirmation-token>
python scripts/run.py gateway.py execute <transaction-id>
python scripts/run.py gateway.py verify <transaction-id>
```

每个阶段应分开执行，并直接使用完整返回的 `next_command.shell_command`，不要自行重建命令。
`confirm <transaction-id> --artifact-hash <full-artifact-hash>` 只作为旧 transaction 和程序兼容入口保留；
新的 agent 工作流应使用 `transaction-show` 返回的 token。

Gateway 是唯一公开接口。完成普通 Wwise 任务时，不要 import 内部 runtime module、构造 `WaapiClient`、创建一次性 helper script，也不要使用 inline Python。如果 gateway 返回没有 packaged route，就直接报告 unsupported boundary，不要自行合成代码。

Manifest 反射只用于发现能力，不等于授权执行。generic `call` 只开放经过 immutable review、递归校验且结果有界的读取集合；两个零输入反射列表只是其中的快速路径。Wwise `2025.1` 的 Media Pool 查询会先通过 `mediaPool.getFields` 发现精确字段名，再调用 `mediaPool.get`，并强制限制最多 200 个结果、16 个过滤器、8 个数据库和 32 个唯一返回字段。更广的读取必须进入确认式 transaction，fixed command 和 bounded topic wait 仍只开放精确 allowlist。新的或尚未 review 的 function/topic 即使名字以 `get`、`verify`、`dump` 开头也会 fail closed；`--dry-run` 不能绕过 fixed、transaction、topic 或 unsupported 路由边界。

---

## 安全模型

- destructive operations 默认阻止
- project-changing steps 应先 preview 再执行
- confirmation 必须匹配当前不可变 preview artifact
- unsupported runtime boundary 要清楚失败，而不是假装支持
- reflected function/topic 必须先有显式 reviewed public route
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
- `skills/waapi-skill/scripts/gateway.py` — 唯一公开的 packaged WAAPI 接口
- `skills/waapi-skill/references/` — 按需加载的 lane-specific gateway guidance
- `skills/waapi-skill/wwise_waapi/capabilities.py` — 离线 public-route catalog
- `skills/waapi-skill/wwise_waapi/operation_registry.py` — closed transaction operations 和明确边界
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

不绑定。它是一个包含 packaged runner/gateway 和 markdown guidance 的本地 skill 包。任何能加载并遵循 skill 目录的本地 agent 工作流都可以使用。

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
- **闭合、可由 agent 直接执行的 gateway 路由**
- **更安全的 mutation flow**
- **测试覆盖更完整**

如果你想要的是一个本地的、版本感知的、经过充分验证的 WAAPI skill，而不是一个长期驻留的通用 server 抽象，那么这就是更合适的形态。
