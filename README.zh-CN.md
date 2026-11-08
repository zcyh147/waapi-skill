[English](./README.md) · [简体中文](./README.zh-CN.md)

<div align="center">

# WAAPI Skill

**用自然语言操作 Wwise Authoring。**

不再让 AI Agent 手写 WAAPI 参数和 JSON。

[![平台](https://img.shields.io/badge/Platforms-macOS%20%7C%20Windows-0078D4?style=flat-square)](#使用要求)
[![Wwise](https://img.shields.io/badge/Wwise-2021.1–2025.1-5965E0?style=flat-square)](#支持版本)
[![Python](https://img.shields.io/badge/Python-3.11–3.13-00897B?style=flat-square)](#使用要求)
[![MIT](https://img.shields.io/badge/License-MIT-64748B?style=flat-square)](./LICENSE)

### [下载最新版](https://github.com/zcyh147/waapi-skill/releases/latest)

[安装](#安装) · [快速开始](#快速开始) · [覆盖范围](./skills/waapi-skill/references/waapi-coverage.md) · [反馈问题](https://github.com/zcyh147/waapi-skill/issues)

</div>

---

WAAPI Skill 让 AI Agent 根据自然语言需求查询和修改 Wwise 工程。本地 Gateway
负责生成适合当前 Wwise 版本的 WAAPI 请求、预览修改并检查结果。

只要 Agent 能加载 Skill 目录并运行本地脚本，就可以使用，无需常驻 MCP Server。

## 主要特点

- **直接描述任务**：查询对象、导入音频、修改设置、生成 SoundBank，无需编写 WAAPI 请求。
- **控制工程修改**：可选择只读、修改前确认，或无需二次确认即可执行。
- **按版本处理操作**：Gateway 使用已配置 Wwise 版本的接口定义，并明确说明不支持的请求。
- **本地执行**：Gateway 在你的 macOS 或 Windows 电脑上运行。

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

部分操作取决于 Wwise 版本，或需要连接 Authoring 而非 WwiseConsole。
Skill 尚未开放部分对象创建操作，详见[已知创建限制](docs/plans/full-waapi-coverage/SPEC.md#user-approved-remaining-creation-limits--2026-10-29)。

## 支持版本

支持 Wwise **2021.1、2022.1、2023.1、2024.1 和 2025.1**。

支持连接 **Wwise Authoring** 和 **WwiseConsole**，Gateway 会自动识别宿主。
读取当前选中对象、控制界面和监控 UI 事件需要 Authoring。

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
npx skills add zcyh147/waapi-skill --skill waapi-skill
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

Agent 会代你操作 Gateway，无需编写 Python 或 WAAPI 请求。

## 修改策略

- `read_only`：允许查询，禁止修改工程
- `ask_before_changes`：先展示 Preview，得到确认后再执行；这是默认模式
- `allow_changes`：先告知用户，然后直接执行并验证 Preview，不再等待第二次确认

Gateway 会在 API 允许的范围内检查结果，并明确说明哪些结果无法完全验证。

## 工作原理

```text
你描述任务
    ↓
Agent 选择 Skill 操作
    ↓
本地 Gateway 为当前 Wwise 版本准备请求
    ↓
直接读取，或预览 → 授权 → 执行 → 检查结果
```

Agent 理解你的需求；Gateway 负责 WAAPI 参数和执行。Gateway 内部没有语言模型。
对话和工具返回的结果仍受你使用的 Agent 客户端的模型与数据处理设置影响。

<details>
<summary>开发与诊断：直接使用 Gateway</summary>

通常由 Agent 代替用户操作 Gateway。开发、诊断或外部自动化场景也可以在源码仓库中
直接调用：

```bash
python skills/waapi-skill/scripts/run.py gateway.py config-set --wwise-version 2025.1 --waapi-host 127.0.0.1 --waapi-port 8080 --project-modification-policy ask_before_changes
python skills/waapi-skill/scripts/run.py gateway.py status
```

在线命令和草稿只使用已保存的连接配置，不接受临时 host/port 参数或连接环境变量
覆盖；`--version` 仅用于离线目录和 schema 浏览。沙盒或独立 Skill 副本应明确选择
不同的 `WAAPI_SKILL_CONFIG_PATH`，再通过 `config-set` 配置。仅复制 Skill 目录
仍会共享用户配置。

首次调用会自动准备 Skill 自带的 Python 环境。如果 Windows 中的 Python 命令是
`py`，将上面的 `python` 替换为 `py` 即可。

</details>

## 覆盖范围与验证

项目包含 Python 测试、隔离工程中的真实 Wwise 测试，以及全新 Agent 会话的工作流测试，
并保留了 macOS 和原生 Windows 上的运行记录。验证结果按版本和工作流区分，
不代表每项操作都在所有支持的平台和版本上完成了实测。

- [详细覆盖范围](./skills/waapi-skill/references/waapi-coverage.md)
- [测试结果与已知限制](./tests/TEST_INVENTORY.md)
- [Agent 使用说明](./skills/waapi-skill/SKILL.md)

## Skill 还是 MCP？

如果 Agent 能加载本地 Skill 并运行脚本，就可以使用本项目。
如果客户端要求通过 MCP 连接，请选择 Wwise MCP Server。

## 问题反馈

遇到问题欢迎[提交 Issue](https://github.com/zcyh147/waapi-skill/issues)，请附上
Wwise 版本、操作系统、Agent 客户端、复现步骤及报错。分享日志或对话片段前，
请隐去工程敏感信息。

## 许可证

[MIT](./LICENSE)

欢迎在遵守 MIT 许可证的前提下，使用本项目进行 AI 训练。
