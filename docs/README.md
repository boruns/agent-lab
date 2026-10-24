# Agent Lab 文档中心

这是项目文档的唯一入口。课程按照能力依赖组织，不需要一次读完所有文档；完成当前课并通过
审阅后，再进入下一课。

## 当前学习位置

| 项目 | 内容 |
| --- | --- |
| 当前阶段 | 阶段 3：模型 Provider |
| 当前课程 | [第 9 课：LLM 基本词汇与 Provider 边界](03-providers/09-llm-foundations.md) |
| 已完成 | 环境、ReAct、可靠工具系统（含 Registry、命名空间与生命周期） |
| 下一课 | 第 10 课：Provider Adapter |

运行当前验收：

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## 从哪里开始

1. 先读[系统课程总纲](00-overview/curriculum.md)，了解整体目标和当前阶段；
2. 阅读当前课程文档，理解“为什么需要这个功能”；
3. 运行测试观察失败；
4. 完成练习后再次运行测试；
5. 让我进行代码审阅并回答思考题；
6. 审阅通过后进入下一课。

## 目录结构

```text
docs/
├── README.md
├── 00-overview/                  # 全局约定与课程地图
│   ├── curriculum.md             # 唯一的完整课程顺序
│   ├── course-method.md          # 学习方法与工程原则
│   ├── python-environment.md     # uv 与 Python 环境
│   ├── model-providers.md        # DeepSeek 优先的 Provider 策略
│   └── desktop-ui.md             # Tauri + Vue Desktop 技术路线
├── 01-foundations/               # Agent 基础
│   └── 01-minimal-react-agent.md
├── 02-tools/                     # 工具与执行边界
│   ├── 02-safe-tool-execution.md
│   ├── 03-json-schema.md
│   ├── 04-argument-validation.md
│   ├── 05-tool-results.md
│   ├── 06-retries-timeouts-cancellation.md
│   ├── 07-side-effects-and-permissions.md
│   └── 08-tool-registry.md
└── 03-providers/                 # 模型协议与 Provider 适配
    └── 09-llm-foundations.md
```

未来阶段只在真正开始时创建目录，避免出现大量空目录。

## 全局文档

- [系统课程总纲](00-overview/curriculum.md)：阶段依赖、完整课序、验收项目和语言选择；
- [学习方法与工程原则](00-overview/course-method.md)：每课如何学习以及为什么暂不复制 Shannon；
- [Python 环境管理](00-overview/python-environment.md)：uv、依赖、锁文件和常用命令；
- [模型 Provider 约定](00-overview/model-providers.md)：DeepSeek 默认、OpenAI 备用和密钥管理。
- [Desktop UI 技术路线](00-overview/desktop-ui.md)：Tauri/Wails 评估、控制面边界和课程安排。

## 已有课程

### 阶段 1：Agent 基础

- [第 1 课：Agent 的本质与最小 ReAct 循环](01-foundations/01-minimal-react-agent.md) — 已完成

### 阶段 2：可靠工具系统

- [第 2 课：工具契约与安全执行](02-tools/02-safe-tool-execution.md) — 已完成
- [第 3 课：用 JSON Schema 描述工具参数](02-tools/03-json-schema.md) — 已完成
- [第 4 课：执行前校验工具参数](02-tools/04-argument-validation.md) — 已完成
- [第 5 课：结构化 ToolResult 与工具错误分类](02-tools/05-tool-results.md) — 已完成
- [第 6 课：可重试错误、退避、超时与取消](02-tools/06-retries-timeouts-cancellation.md) — 已完成
- [第 7 课：副作用、幂等键、确认与权限分级](02-tools/07-side-effects-and-permissions.md) — 已完成
- [第 8 课：Tool Registry、命名空间与生命周期](02-tools/08-tool-registry.md) — 已完成

### 阶段 3：模型 Provider

- [第 9 课：LLM 基本词汇与 Provider 边界](03-providers/09-llm-foundations.md) — 进行中

## 文档约定

- `00-overview/` 只放全项目级约定，不放具体课程；
- 阶段目录使用两位数字，课程文件名保留课号；
- 每篇课程包含问题、作用、实现、验证、思考题；
- 课程状态只在本页和系统总纲维护，避免多个进度表互相矛盾；
- 代码路径相对仓库根目录书写，文档链接使用相对路径；
- 新概念首次出现时使用中文解释，并保留常见英文术语方便检索。
