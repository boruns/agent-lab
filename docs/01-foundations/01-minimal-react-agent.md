# 第 1 课：Agent 的本质与最小 ReAct 循环

> **阶段**：1 · Agent 基础  
> **状态**：已完成  
> **前置**：Python 环境与基础类型知识  
> **导航**：[文档中心](../README.md) · [课程总纲](../00-overview/curriculum.md) · [下一课](../02-tools/02-safe-tool-execution.md)

## 本课目标

完成这一课后，你应该能：

- 用一句工程化定义解释 Agent；
- 说清 Chatbot 和 Agent 的控制流差异；
- 独立实现一个可测试、有限步数的 ReAct 循环；
- 理解为什么第一版不用真实 LLM。

## 1. 什么是 Agent

对本项目而言：

> Agent 是一个受程序约束的闭环系统：模型根据当前状态选择下一步，系统执行允许的动作，
> 再把观察结果交还给模型，直到产生最终答案或触发终止条件。

组成部分可以先压缩成五个：

```text
目标 + 状态 + 模型决策 + 可用动作 + 控制循环
```

LLM 只是“下一步决策器”。步数上限、工具权限、错误处理和是否继续运行，必须由普通程序控制。

## 2. Chatbot 与 Agent 的差异

普通 Chatbot 通常只有一次控制权转移：

```text
用户 -> 模型 -> 文本答案
```

最小 Agent 会多次在模型与环境之间往返：

```text
用户目标
   |
   v
模型决策 -----> 最终答案 -----> 结束
   |
   v
工具调用 -----> 观察结果
   ^                |
   +----------------+
```

关键差异不是“提示词更长”，而是模型可以提出动作，程序执行动作后再次调用模型。

## 3. ReAct 是什么

ReAct 可以理解为 Reason + Act 的交替：

1. **Reason**：模型根据目标和历史判断下一步；
2. **Act**：若需要外部信息，提出一个工具调用；
3. **Observe**：程序执行工具，把结果记入历史；
4. 重复，直到模型给出最终答案。

本课故意使用结构化的 `ToolCall` / `FinalAnswer`，而不是解析模型生成的自由文本。
这会把“Agent 控制流”与“某家模型 API 的消息格式”分开。

## 4. 为什么先用 ScriptedModel

真实模型有随机性、网络故障、费用和 API 格式差异。如果第一版就连接真实模型，测试失败时，
你很难判断问题来自循环、提示词、SDK 还是网络。

`ScriptedModel` 按预设顺序返回决策，使下面的轨迹完全确定：

```text
问题: 6 * 7 是多少？
决策 1: ToolCall(name="calculator", arguments={"expression": "6 * 7"})
观察: 42
决策 2: FinalAnswer(content="结果是 42")
```

真实 LLM Provider 以后只需要实现同一个 `Model` 协议。

## 5. 你的第一道练习

打开 `src/agent_lab/agent.py`，实现 `Agent.run(question)`。伪代码如下：

```text
history = [用户消息]

最多重复 max_steps 次：
    decision = model.decide(history, 可用工具说明)

    如果 decision 是 FinalAnswer：
        把答案加入 history
        返回 RunResult

    如果 decision 是 ToolCall：
        找到对应工具；找不到则抛 UnknownToolError
        执行工具
        把“调用了什么”和“观察到什么”加入 history

超过 max_steps：
    抛 StepLimitExceeded
```

要求：

- 不改测试来迁就实现；
- 不在循环中写死 `calculator`；
- 不吞掉未知工具错误；
- 不调用任何真实模型 API；
- 保持 `history` 的原始顺序。

运行：

```bash
uv run pytest
```

当 3 个测试全部通过后，把实现交给我审阅。下一步我们会讨论：模型一直调用工具怎么办、
工具失败应该如何进入上下文，以及为什么“最大步数”其实是最早出现的预算控制。

## 6. 思考题

1. `max_steps` 应该限制模型调用次数、工具调用次数，还是二者？为什么？
2. 工具返回字符串是否足够？如果需要表达“可重试错误”该怎么办？
3. 模型请求一个不存在的工具时，应该立即失败，还是把错误作为观察交还给模型？

这些问题没有唯一答案；它们会在后续的工具系统和生产治理阶段重新出现。
