# Agent Lab

一个从零实现 AI Agent 的学习型工程。我们以 Shannon 的架构思路为参照，但不依赖
LangChain、LangGraph、CrewAI 等 Agent 框架；每个能力先理解问题和模式，再自己实现。

## 当前进度

| 项目 | 状态 |
| --- | --- |
| 当前阶段 | 阶段 3：模型 Provider |
| 当前课程 | [第 11 课：DeepSeek 基础调用与 Transport 边界](docs/03-providers/11-deepseek-transport.md)（已完成） |
| 已完成课程 | 第 1～11 课 |
| 下一课 | 第 12 课：Function Calling |

目前已经完成最小 ReAct 循环、可靠工具系统、Tool Registry、LLM 基础和 Provider Adapter。
DeepSeek Transport 已接入显式配置、物理超时、稳定错误分类和 Token Usage 记录，同时保持 Agent
核心与供应商 SDK 解耦。

## 为什么先用 Python

第一阶段的目标是看清 Agent 的控制循环，而不是处理跨语言通信。Python 的反馈周期短，
模型和数据生态完整，适合先验证抽象。后续在问题真正出现时引入：

- Go：并发编排、任务调度、工作流与多 Agent 协作。
- Rust：工具执行边界、资源限制、沙箱与高可靠运行时。
- Desktop：Tauri v2 + Rust + Vue 3 + TypeScript + Element Plus，作为后期控制面。

语言是解决问题的手段，不是学习目标本身。

## 当前课程

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

第 11 课已经通过离线验收。真实 DeepSeek 冒烟测试仍为显式、可选步骤，默认测试不访问网络，
也不需要 API Key。第 12 课尚未开始。

完整课程已经按能力依赖重构为 13 个阶段。阶段顺序、验收项目和语言选择见
[`docs/00-overview/curriculum.md`](docs/00-overview/curriculum.md)。当前只需关注正在进行的一课，
不必一次预习全部主题。

## 文档

- [`AGENTS.md`](AGENTS.md)：跨聊天窗口持续生效的项目协作与课程维护约定
- [`docs/README.md`](docs/README.md)：文档中心、当前课程和分类目录
- [`docs/00-overview/curriculum.md`](docs/00-overview/curriculum.md)：系统课程总纲与阶段验收
- [`docs/00-overview/desktop-ui.md`](docs/00-overview/desktop-ui.md)：Desktop 技术选型与架构边界
- [`docs/03-providers/10-provider-adapter.md`](docs/03-providers/10-provider-adapter.md)：上一课与思考题答案
- [`docs/03-providers/11-deepseek-transport.md`](docs/03-providers/11-deepseek-transport.md)：当前课程

## 参考资料

- [《AI Agent 架构：从单体到企业级多智能体》](https://waylandz.com/ai-agent-book/)
- [Shannon](https://github.com/Kocoro-lab/Shannon)
