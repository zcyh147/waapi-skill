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
- `resources/metadata/<version>/object-types.json`
- `resources/native_surface_policy.json`
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
- 三种直观的修改模式：`read_only`、`ask_before_changes`、`allow_changes`
- 不可变 preview 会绑定 Gateway 确认 token，或独立、可审计的策略授权
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

覆盖率按 **Wwise 版本/API 行**统计，因为同一个 URI 在不同 Wwise 版本中可能具有不同的 schema、执行路由或安全结论。只有 packaged gateway 已提供公共执行合同的行才算覆盖；只返回 hard boundary 或只提供文档说明不算覆盖。真正 dispatch 前仍必须通过实时宿主、版本和安全前置条件。

默认 `wwise-console` profile 是由 WwiseConsole 反射得到的基准接口：

| Wwise 版本 | 反射总行数 | 已封装路由行数 | 已封装 functions | 已封装 topics | Registry 排除行数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2021.1` | 126 | 124 | 97 | 27 | 2 |
| `2022.1` | 144 | 142 | 110 | 32 | 2 |
| `2023.1` | 181 | 179 | 147 | 32 | 2 |
| `2024.1` | 178 | 178 | 148 | 30 | 0 |
| `2025.1` | 185 | 185 | 154 | 31 | 0 |
| **合计** | **814** | **808** | **656** | **152** | **6** |

这 808 个版本/API 行对应 **198 个唯一已封装 WAAPI URI**。这是接口合同
覆盖数，不表示 808 行都能在 WwiseConsole 上 dispatch：2021.1–2023.1
各自保留的 3 个 UI command 路由仍要求实时宿主为 Authoring；连接
WwiseConsole 时会在业务调用前失败。另有一个
`wwise-authoring-ui` profile，只在基准接口上补入从真实 Wwise Authoring
反射得到的五个固定 `ak.wwise.ui.commands.*` URI：

| Wwise 版本 | Packaged overlay 行数 | 已封装路由行数 | 已封装 functions | 已封装 topics | Registry 排除行数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2021.1` | 126 | 126 | 99 | 27 | 0 |
| `2022.1` | 144 | 144 | 112 | 32 | 0 |
| `2023.1` | 181 | 181 | 149 | 32 | 0 |
| `2024.1` | 183 | 183 | 152 | 31 | 0 |
| `2025.1` | 190 | 190 | 158 | 32 | 0 |
| **合计** | **824** | **824** | **670** | **154** | **0** |

Authoring profile 对应 **200 个唯一已封装 WAAPI URI**；连接匹配的
Authoring 宿主时，824 行都有公共执行路由。它只是 Console
manifest 加上窄范围的 UI command supplement，并不表示仓库反射了完整的
Authoring API。Gateway 根据实时 `getInfo.isCommandLine` 自动判断宿主；
连接 WwiseConsole 时，UI command 会在业务调用前被拒绝。五个版本采集到的
命令 ID 数量分别为 317、451、475、594、623；它们只是当前工程、插件和
add-on 环境下的观察快照，不是运行时 allowlist。真正执行前始终以实时
`getCommands` 结果为准。

五个 Authoring 版本的资源采集总共只做了 35 次只读 WAAPI 调用：每个版本
一次 `getInfo`、五个固定 URI 的 `getSchema`，以及一次 `getCommands`。
本轮没有在真实 Wwise 中执行、注册或注销 UI command；这些 transaction
路径和强化后的 `object.createPlugin` 读回验证器，当前证据来自程序测试和
fake client，不是新增的真实业务修改证据。

可用 `gateway.py capabilities --profile wwise-console` 或
`gateway.py capabilities --profile wwise-authoring-ui` 离线查看相应接口表；
这个 catalog 选项不能覆盖实时宿主探测得到的 profile。

五个版本的公开 Function 完整审计共有 167 个不同 URI。其中 118 个使用
没有 URI 专属限制的 generic reflected-schema route；49 个使用 fixed
command、专用 transaction，或六个带明确字段/值域/组合限制的 generic
route。所有 generic 调用仍共同受时间、大小、结果和安全上限约束。打包的
native-surface policy 固定了完整的 118/49 分区，并对其中 15 个公开请求结构与反射差异较大
的高风险 URI 做逐 selector 分类。所谓“等价规范化”，例如把
`properties` 中经过类型校验的条目转换成原生 `@Property`，是保留业务能力
但不开放未经检查的 raw escape hatch。明确阻止的字段只包括实现内部字段、
任意进程 hook，或无法安全绑定和验证效果的形式；它们不会被静默丢弃。

对象类型发现另有一套由真实 `ak.wwise.core.object.getTypes` 结果生成的紧凑
版本化索引。五个版本分别包含 105、107、109、109、125 条记录，总体积约
55 KiB。`gateway.py object-types` 可离线搜索该索引，并只返回有界结果页，
不会把所有类型塞进 Agent 上下文。修改操作仍以实时属性和引用元数据为准。
只有当 endpoint、完整 Wwise build/schema/session/process、工程及打包目录
摘要全部一致时，稳定的类型、class 级元数据和规范 GUID 对象元数据才会跨
gateway 调用复用；可变对象路径/名称作用域只在当前调用封装内复用，动态
属性启用状态和曲线状态永不缓存。

两套 profile 都通过 fixed command、bounded direct call、bounded topic
wait、策略约束 transaction、隔离 I/O transaction 或同连接 Undo Group
执行。Lua 文件路由只接受已经存在并重新绑定路径、大小和哈希的 `.lua`
文件；Wwise 2025.1 另有精确 inline source 路由。`source_authority`
只是调用方声明，不是运行时对对话来源的证明；Skill 不会生成、修复或包装
Lua。Private debug API 使用有界读取/订阅或明确的不可重试 transaction，
restart/assert/crash 会以生命周期不确定状态终止。

命名操作层还为对象创建与修改、插件创建、RTPC/平台 link、音频导入、SoundBank 工作流、Lua/debug、截图，以及 Authoring UI command 的执行、注册和注销提供闭合、按版本约束的业务合同。直接 `audio.import` 现已支持 defaults、逐行导入位置、文件或有界 WAV base64、只建结构、属性、引用、Event/Dialogue Event/Switch 指令及源代码管理选项；Tab Delimited 路径也识别对应的原生列和重复 Event 列。用户用自然语言描述设置时，Skill 会通过一次有界的实时 metadata discovery 查询精确的属性/引用候选和依赖关系，不依赖对象专用预设；与当前 Wwise 会话和工程绑定的 class 元数据及规范 GUID 对象元数据会供后续不可变 preview 复用。选定的实时名称会在同一个导入事务里继续校验并物化，从而避免模型猜字段，也不需要拆成第二次修改。`object.create` 与 `object.set` 通过闭合描述符开放经过审核的平台、列表、重命名、源代码管理、递归 child、属性、引用、插件和 RTPC 形式，并做漂移感知读回。其中递归 `object.set` 的 platform/language 字段从 `2022.1` 起可用；逐对象音频导入描述（文件/Base64、Originals 子目录、语言及实时解析的 source type）从 `2023.1` 起可用，与反射出的版本边界一致。`object.createPlugin` 只接受明确的 class ID 和闭合的 Source/Effect 描述；`2022.1` 使用固定 Effect 引用，后续版本追加 EffectSlot，并通过实时读回验证新建插件。UI command execute 只能验证反射出的空结果结构，不能声称任意 GUI 或工程效果已经验证；register/unregister 还会验证实时命令 ID 的存在状态。Wwise `2021.1` 的 SoundBank 生成只从实时 Project 的 `filePath`、`workunitIsDirty` 和受约束、带哈希、严格解析的 `.wproj` 获取工程上下文；后续版本绑定实时 `core.getProjectInfo`。这些路由把不可变 preview 绑定到显式确认或持久化的 `allow_changes` 策略授权，并使用各操作能提供的最强读回，而不是只相信 WAAPI 返回成功。一旦 URI 已有实现完成的命名操作，generic `waapi.call` 会以 `DEDICATED_OPERATION_REQUIRED` 拒绝该 URI，避免原始 payload 绕过专用合同。

当前固定的纯程序 gate 包含 **2635 项程序测试**，另有两项仅原生 Windows 执行的固定编码 shell 与 NTFS junction 校验；其中每一个已覆盖的默认 profile 版本/API 行都有一项已封装路由合同用例，并另外覆盖 Authoring overlay/UI command、五版本结构化查询编译，以及逐层披露的高级 WAQL 固定路由、最终结果上限、单查询帧、返回结构和修改隔离矩阵。它还覆盖有界的实时元数据发现与缓存合同、功能重叠时的业务意图选择指引、可配置有限时长或显式不限时但仍受事件数量约束的 Topic wait，以及持续的 `stream-topic`、三种修改策略分支（包括 `read_only` 下由目录合同证明的只读 transaction）、gateway 会话提示上下文、跨平台事务锁、闭合的 `SwitchGroup -> Switch` 与 `StateGroup -> State` 创建关系，以及上述命名操作的合同/验证矩阵。五项上下文/读取优化也有专门的程序测试：默认 query 回复压缩、通过 `--detail` 显式恢复诊断、直接沿规范关系 GUID 跳转、在单次 request/preview 内复用相同 identity 解析和 property metadata 读取，以及对 prepared role 做去重、有界的 multi-ID 重新校验。它验证 packaged 路由、schema、安全边界、I/O 约束、transaction 行为、fake dispatch 执行和确定性的 onboarding 信息；这不等于已经在真实 Wwise 进程中逐一运行了全部 808 行，也不等于所有高级 WAQL 语法都经过了真实 Wwise 验证。关闭 memory 的 `modification_policy_9-c7` campaign 曾在其精确冻结候选上通过全部 9 个 Wwise 2022.1 任务：`read_only`、提问式 `ask_before_changes` 和同回合执行的 `allow_changes` 各独立重复 3 次。6 个获准写入的任务都创建并验证了 7 个对象和 46 项业务断言，所有源工程哈希保持不变，sandbox 也全部清理。更早的 `h80-release-c38` 真实 Wwise campaign 另行通过了全部 80 个获批重型 API 场景（2022.1 为 70 个，2024.1 和 2025.1 各 5 个）。这些历史证据只覆盖各自封存候选及其场景，均不是对当前结构化/高级查询与闭合 selector 候选的新鲜语义验证。完整口径见[五版本覆盖契约](./skills/waapi-skill/references/waapi-coverage.md)。

---

## 和 Wwise MCP 的区别

这个 skill 和 Wwise MCP server 有重叠，但不是同一种工具。

### 这个 skill 更强的地方

- **按需加载资源**，而不是默认把大范围内容长期挂在上下文里
- **版本化运行资源**，覆盖 `2021.1` 到 `2025.1`
- **skill-local 的 Python 工作流**，不需要单独起 server
- **更明确的三模式 preview / authoring 流程**
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
4. 通过闭合 transaction 路由应用 `read_only`、`ask_before_changes` 或 `allow_changes`
5. 对结果做 verification

### 优先支持 read-first 的安全 inspection

当 config 和连接信息已经明确时，普通 inspection 请求应优先直接执行 read-only 路径，而不是先漂移到文档研究模式。

### Bounded topic handling

所有 Topic wait 的 gateway 默认值都是 10 秒，也接受用户通过 gateway 全局 `--timeout` 指定任意正有限时长。若用户订阅 `ak.wwise.core.soundbank.generated` 时没有指定时长，Skill 会显式给同一个 gateway 传入 `--timeout 120`，并在开始前告知本次实际使用 120 秒；这是 Skill 的选择，不是另一套 gateway 默认值。用户明确要求不限时，才使用 `wait-topic --no-timeout`，持续到收齐目标事件或由用户取消。不限时只取消等待期限，并不是无限输出流：`wait-topic` 仍只收集 1–64 个事件、最终只返回一个 JSON 文档，聚合结果仍受 256 KiB 上限约束。持续逐条输出走单独路径：只有用户明确要求 continuous/stream 时才选择 `stream-topic`；它保持单个持久订阅并输出有界 NDJSON 记录，直到用户取消或健康检查/传输边界终止。递归 JSON 条件会逐个匹配候选事件，成功、超时、取消或 stream 终止后都会 unsubscribe。单事件 wait 成功会把校验后的 WAAPI publish payload 放在 `event` 下，多事件 wait 则返回有序 `events` 和请求/实际数量。不要用目标最终名称匹配 `object.created`，因为通知发生时命名尚未完成。对于 packaged ActorMixer 探针，Wwise 2021.1-2024.1 在通知时报告 `ActorMixer`，Wwise 2025.1 则报告底层 `PropertyContainer`；需要证明事件归属时，应把返回的对象 GUID 与可信 publisher 的 GUID 对账。

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

三种规范模式分别是：

- `read_only`：禁止工程修改，但仍允许读取，包括已封装、仅接受显式确认的只读 transaction。
- `ask_before_changes`（默认）：先说明将修改什么、预期得到什么，再询问用户是否执行。
- `allow_changes`：先告知用户，然后无需第二条确认消息，直接执行不可变 preview 并验证。

旧配置值 `never`、`preview_then_confirm`、`allow_with_notice` 仍可作为迁移
别名读取，但新的输出和保存只使用上述规范名称。

### 3. 所有 read-only 工作都走 gateway

无需拼装 WAAPI 代码即可检查实时版本/工程并查询对象：

```bash
python scripts/run.py gateway.py status
python scripts/run.py gateway.py object-types --query 'audio source' --limit 20
python scripts/run.py gateway.py query-object \
  --path '\Events\Default Work Unit' \
  --return-field id --return-field name --return-field type --return-field path
```

简单查询继续使用上面的紧凑参数。只有这些参数无法表达所需的嵌套布尔条件
或有顺序的关系链时，才读取 `query-schema`，按它返回的 JSON Schema
构造闭合的 `waapi-skill.object-query/v1` 请求，再传给
`query-object --request-json`。Python Builder 会把结构稳定地编译成有结果
上限的 WAQL。如果返回的结构化 Schema 仍表达不了所需的只读语法，则显式
读取 `query-schema --advanced`，再把严格符合
`waapi-skill.advanced-object-query/v1` 的文档传给
`query-object --advanced-request-json`。第三层允许原生 WAQL 和高级返回表达式，
但 API 固定为只读 `object.get`，Gateway 会追加最终结果上限并保留超时和字节
限制，具体语法由当前连接的 Wwise 版本验证。修改对象选择器仍不接受原始
WAQL；高级查询结果只是只读候选，不能证明目标唯一。后续若要修改，必须先
让用户明确选择一个候选，再用第一层精确 GUID 查询验证该对象的 GUID、名称、
类型和路径完全一致，随后才能进入另一个闭合修改事务。返回的高级 Schema 还会
明确原生输入边界：WAQL 和每个返回表达式都有 UTF-8 字节上限，必须去除首尾空白、
保持单行，且不能含注释、分号或未闭合的字符串/正则字面量。

### 4. 工程修改必须走 closed transaction lane

先查询 packaged request contract。实际修改使用 `preview --apply`，它会返回
不可变 transaction id 和完整 artifact hash。`ask_before_changes` 会停在
`awaiting_confirmation`，Agent 先说明预期结果并询问用户；后续的
`transaction-show --summary-only` 会返回与当前状态绑定的确认 token。
`allow_changes` 则返回 `policy_authorized` 和准确的 `execute` 命令，Agent 告知
后可在同一轮继续。`read_only` 会阻止 `--apply`。

```bash
python scripts/run.py gateway.py operation-schema object.setNotes
python scripts/run.py gateway.py preview --apply \
  --request-json '{"contract":"waapi-skill.operation-request/v1","version":"2022.1","operation":"object.setNotes","arguments":{"object":{"kind":"path","value":"\\Events\\Default Work Unit\\Target"},"value":"Reviewed"}}'
python scripts/run.py gateway.py transaction-show <transaction-id> --summary-only
python scripts/run.py gateway.py confirm <transaction-id> --confirmation-token <confirmation-token>
python scripts/run.py gateway.py execute <transaction-id>
python scripts/run.py gateway.py verify <transaction-id>
```

每个返回阶段应分开执行，并仅使用完整的 `next_command.copy_instruction.source_field` 所指定的字段，不要自行重建命令。
`transaction-show` 和 `confirm` 属于 `ask_before_changes`；`allow_changes`
从 `policy_authorized` 直接进入 `execute`。
`confirm <transaction-id> --artifact-hash <full-artifact-hash>` 只作为旧 transaction 和程序兼容入口保留；
新的 agent 工作流应使用 `transaction-show` 返回的 token。

Gateway 是唯一公开接口。完成普通 Wwise 任务时，不要 import 内部 runtime module、构造 `WaapiClient`、创建一次性 helper script，也不要使用 inline Python。如果 gateway 返回没有 packaged route，就直接报告 unsupported boundary，不要自行合成代码。

Manifest 反射只用于发现能力，不等于授权执行。generic `call` 只开放经过 immutable review、递归校验且结果有界的读取集合；两个零输入反射列表只是其中的快速路径。Wwise `2025.1` 的 Media Pool 查询会先通过 `mediaPool.getFields` 发现精确字段名，再调用 `mediaPool.get`，并强制限制最多 200 个结果、16 个过滤器、8 个数据库和 32 个唯一返回字段。更广的读取必须进入已授权 transaction，fixed command 和 bounded topic wait 仍只开放精确 allowlist。新的或尚未 review 的 function/topic 即使名字以 `get`、`verify`、`dump` 开头也会 fail closed；`--dry-run` 不能绕过 fixed、transaction、topic 或 unsupported 路由边界。

---

## 安全模型

- destructive operations 默认阻止
- project-changing steps 应先 preview 再执行
- confirmation 或策略授权必须匹配当前不可变 preview artifact
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
