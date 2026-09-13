[English](./README.md) · [简体中文](./README.zh-CN.md)

# Wwise WAAPI Skill

用自然语言操作 Wwise Authoring，不再让 AI Agent 手写 WAAPI 参数和 JSON。

Wwise WAAPI Skill 是一个本地 Agent Skill，内置版本感知的 Gateway。你只需
描述想要的结果；Agent 负责选择合适的操作并提供少量业务参数，Gateway 则负责
生成精确的 WAAPI 请求、预览修改并验证结果。

它完全在本地运行，不需要常驻 MCP Server，也不绑定某一个 Agent。只要客户端
能够加载 Skill 目录并运行本地脚本，就可以使用。

## 主要特点

- **自然语言操作 Wwise**：关注想得到什么，不必理解 API 名称、对象类型、GUID、
  完整路径或 JSON payload。
- **覆盖常用 Authoring 工作流**：查询与修改对象、导入或重新导入音频、维护 Event
  和 Switch 分配、生成 SoundBank、使用 Profiler/运行时操作、订阅事件等。
- **支持五个 Wwise 版本系列**：为 `2021.1`、`2022.1`、`2023.1`、`2024.1` 和
  `2025.1` 提供独立的版本合同。
- **更安全的工程修改**：所有修改都经过不可变 Preview、明确授权、单次执行和结果
  验证。
- **本地且有边界**：凭据、工程数据、运行状态和测试证据保留在本地；不支持或不安全
  的请求会明确停止，而不是猜测参数。
- **双平台验证**：已在 macOS 与原生 Windows 上完成程序测试、真实 Wwise 测试和
  Fresh Agent 工作流验证。

## 能做什么？

典型任务包括：

- 查询当前选择、对象层级、属性、引用、Bus 和工程状态
- 创建、复制、移动、重命名、修改或删除 Wwise 对象
- 导入音频，并根据媒体文件创建对象与 Event 结构
- 设置音量、循环、Notes、Output Bus、RTPC、平台 Link 和元数据
- 维护 Switch Container 与 State/Switch 分配
- 生成或检查 SoundBank 及其输出文件
- 执行受支持的 Authoring UI、SoundEngine、Profiler、Transport、CLI、Lua 和
  Topic 订阅工作流

打包的 Profile 会开放各版本中经过审核且允许使用的路由。仅限特定宿主、特定版本、
危险或无法可靠验证的能力会返回明确边界，不会伪装成已支持。

## 支持版本

| Wwise | 打包支持 |
| --- | --- |
| `2021.1` | 支持 |
| `2022.1` | 支持 |
| `2023.1` | 支持 |
| `2024.1` | 支持 |
| `2025.1` | 支持 |

提供两种宿主 Profile：

- **WwiseConsole**：覆盖反射得到的命令行接口
- **Wwise Authoring UI**：在相同核心接口上增加受支持的 UI Command

Gateway 会自动识别当前连接的宿主。仅限 Authoring 的命令不会假装能在
WwiseConsole 中运行。

## 使用要求

- Python `3.11`–`3.13`
- 已安装受支持版本的 Wwise
- 本地 Wwise 工程可以使用 WAAPI
- 支持加载本地 Skill 的 Agent 或工具运行器

Skill 会在首次使用时自动创建并准备自己的 Python 环境。只有使用下方 Skills CLI
安装方式时才需要 Node.js 和 npm。

## 安装

### 由 Agent 安装

将[本仓库](https://github.com/zcyh147/waapi-skill)提供给支持本地 Skill 的 Agent，
并让它安装 `waapi-skill` Skill。

### Skills CLI

也可以使用 Skills CLI 直接安装：

```bash
npx skills@latest add zcyh147/waapi-skill --skill waapi-skill
```

## 快速开始

在 Wwise 中打开目标工程，进入 `Project > User Preferences`，启用
`Wwise Authoring API (WAAPI)` 并确认 WAMP 端口。本地默认端口为 `8080`；如果工程
使用其他端口，需要向 Skill 提供相同的值。

安装 Skill 后，直接在 Agent 对话中描述任务：

> 使用本地 WAAPI 地址和 8080 端口，为这个 Skill 配置 Wwise 2025.1，保持
> `ask_before_changes` 修改策略，并检查当前连接。

> 列出 Default Work Unit 下的所有 Event。

> 在 Weather 下导入 Rain 和 Wind，设为无限循环，音量分别为 -4 dB 和 -6 dB，
> 都走 Weather Bus；先给我看 Preview。

> 重新导入 Rifle Tail 的音频，不要改变这个 Sound 的其他设置。

Agent 会跟随 Gateway 返回的唯一后续操作。用户不需要把这些需求翻译成 WAAPI
Schema、Python 命令或命令行参数。

## 修改策略

- `read_only`：允许查询，禁止修改工程
- `ask_before_changes`：先展示 Preview，得到确认后再执行；这是默认模式
- `allow_changes`：先告知用户，然后直接执行并验证 Preview，不再等待第二次确认

三种模式都使用相同的闭合 Gateway 边界。仅收到 WAAPI 成功响应，并不代表业务结果
已经验证成功。

## 工作原理

```text
自然语言需求
    ↓
Agent 选择操作，并提供闭合的高层业务参数
    ↓
Gateway 生成当前版本准确的 WAAPI 请求与执行计划
    ↓
直接读取，或 Preview → 授权 → 单次执行 → 验证
    ↓
Wwise
```

核心分工很简单：

- **Agent** 处理自然语言，选择对象名称、媒体文件、`volume_db=-4`、
  `loop=Infinite` 等用户能理解的值。
- **Gateway** 负责 Wwise 类型、完整路径、元数据查询、原生枚举、GUID、依赖顺序、
  批处理、序列化、Preview 状态和结果验证。

Gateway 内部没有 LLM。它是确定性的，使用按版本反射的资源，并且只在当前任务需要
时加载详细说明。这样既保留了 Skill 的轻量使用方式，也提供了优秀 MCP 工具应有的
稳定工具边界。

## 直接使用 Gateway（可选）

通常由 Agent 代替用户操作 Gateway。开发、诊断或外部自动化场景也可以在源码仓库中
直接调用：

```bash
python skills/waapi-skill/scripts/run.py gateway.py config-set --wwise-version 2025.1 --waapi-host 127.0.0.1 --waapi-port 8080 --project-modification-policy ask_before_changes
python skills/waapi-skill/scripts/run.py gateway.py status
```

首次调用会自动准备 Skill 自带的 Python 环境。如果 Windows 中的 Python 命令是
`py`，将上面的 `python` 替换为 `py` 即可。

## 范围与验证

项目覆盖 WwiseConsole 和 Authoring Profile 中经过审核的完整公开接口。覆盖范围按
版本区分，也不会为了数字好看而开放不安全字段或把错误宿主算作支持。

仓库包含程序测试、真实只读测试、破坏性 Sandbox 测试，以及 macOS/Windows 上的
Fresh Agent 语义测试。精确路由数量、版本边界和完整证据放在独立文档中，不再堆在
用户首页：

- [详细覆盖范围](./skills/waapi-skill/references/waapi-coverage.md)
- [测试清单与证据](./tests/TEST_INVENTORY.md)
- [Skill 合同](./skills/waapi-skill/SKILL.md)

## Skill 还是 MCP？

如果你需要本地、版本感知、不依赖常驻 Server，并且行为边界已经打包好的 Agent
Skill，就使用这个项目。如果客户端明确要求 MCP 原生互操作，或你希望使用持久化的
服务边界，则更适合选择 Wwise MCP Server。
