# Agent Lab

一个从零实现 AI Agent 的学习型工程。我们以 Shannon 的架构思路为参照，但不依赖
LangChain、LangGraph、CrewAI 等 Agent 框架；每个能力先理解问题和模式，再自己实现。

## 当前进度

- 阶段 0：学习路线与工程约定（已完成）
- 模型 Provider：DeepSeek 优先，OpenAI 备用（约定已完成，适配器待第 2 阶段实现）
- 阶段 1 / 第 1 课：最小 ReAct 循环（已完成）
- 阶段 2 / 第 2 课：工具契约与安全执行（已完成）
- 阶段 2 / 第 3 课：JSON Schema 工具参数契约（已完成）
- 阶段 2 / 第 4 课：执行前参数校验（进行中）

## 为什么先用 Python

第一阶段的目标是看清 Agent 的控制循环，而不是处理跨语言通信。Python 的反馈周期短，
模型和数据生态完整，适合先验证抽象。后续在问题真正出现时引入：

- Go：并发编排、任务调度、工作流与多 Agent 协作。
- Rust：工具执行边界、资源限制、沙箱与高可靠运行时。

语言是解决问题的手段，不是学习目标本身。

## 开始第一课

```bash
uv sync
uv run pytest
```

当前新增的参数校验测试会按设计失败：它们对应第四道练习——在工具执行前验证 Schema 和
实际参数。阅读 [`docs/04-tool-argument-validation.md`](docs/04-tool-argument-validation.md)
后完成它。

## 文档

- [`docs/00-python-environment.md`](docs/00-python-environment.md)：uv、Python 与依赖管理约定
- [`docs/00-model-providers.md`](docs/00-model-providers.md)：DeepSeek 优先与 OpenAI 备用策略
- [`docs/00-learning-roadmap.md`](docs/00-learning-roadmap.md)：完整路线、语言选择和阶段产物
- [`docs/01-minimal-react-agent.md`](docs/01-minimal-react-agent.md)：Agent 本质与最小 ReAct 循环
- [`docs/02-tool-contracts.md`](docs/02-tool-contracts.md)：工具契约、不可信输入与 AST 白名单
- [`docs/03-tool-json-schema.md`](docs/03-tool-json-schema.md)：JSON Schema 与 Function Calling 前置契约
- [`docs/04-tool-argument-validation.md`](docs/04-tool-argument-validation.md)：Schema 校验与执行边界

## 参考资料

- [《AI Agent 架构：从单体到企业级多智能体》](https://waylandz.com/ai-agent-book/)
- [Shannon](https://github.com/Kocoro-lab/Shannon)
