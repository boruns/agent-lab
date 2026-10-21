# Agent Lab

一个从零实现 AI Agent 的学习型工程。我们以 Shannon 的架构思路为参照，但不依赖
LangChain、LangGraph、CrewAI 等 Agent 框架；每个能力先理解问题和模式，再自己实现。

## 当前进度

- 阶段 0：学习路线与工程约定（已完成）
- 模型 Provider：DeepSeek 优先，OpenAI 备用（约定已完成，适配器待阶段 3 实现）
- 阶段 1 / 第 1 课：最小 ReAct 循环（已完成）
- 阶段 2 / 第 2 课：工具契约与安全执行（已完成）
- 阶段 2 / 第 3 课：JSON Schema 工具参数契约（已完成）
- 阶段 2 / 第 4 课：执行前参数校验（已完成）
- 阶段 2 / 第 5 课：结构化 ToolResult 与工具错误分类（进行中）

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
```

当前新增的结果契约测试会按设计失败：它们对应第 5 课——用结构化结果表示工具成功与预期
失败，并把分类后的错误反馈给模型。阅读
[`docs/02-tools/05-tool-results.md`](docs/02-tools/05-tool-results.md) 后完成它。

完整课程已经按能力依赖重构为 13 个阶段。阶段顺序、验收项目和语言选择见
[`docs/00-overview/curriculum.md`](docs/00-overview/curriculum.md)。当前只需关注正在进行的一课，
不必一次预习全部主题。

## 文档

- [`docs/README.md`](docs/README.md)：文档中心、当前课程和分类目录
- [`docs/00-overview/curriculum.md`](docs/00-overview/curriculum.md)：系统课程总纲与阶段验收
- [`docs/00-overview/desktop-ui.md`](docs/00-overview/desktop-ui.md)：Desktop 技术选型与架构边界
- [`docs/02-tools/05-tool-results.md`](docs/02-tools/05-tool-results.md)：当前课程

## 参考资料

- [《AI Agent 架构：从单体到企业级多智能体》](https://waylandz.com/ai-agent-book/)
- [Shannon](https://github.com/Kocoro-lab/Shannon)
