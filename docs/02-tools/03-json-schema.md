# 第 3 课：用 JSON Schema 描述工具参数

> **阶段**：2 · 可靠工具系统  
> **状态**：已完成  
> **前置**：第 2 课的安全工具边界  
> **导航**：[文档中心](../README.md) · [上一课](02-safe-tool-execution.md) · [下一课](04-argument-validation.md)

## 本课要解决的问题

目前 Agent 传给模型的工具信息只有：

```text
name = "calculator"
description = "Evaluate arithmetic ..."
```

人类可以从描述中猜出它需要一个算术表达式，但模型没有一个稳定、机器可读的参数契约。
它可能生成：

```python
{"formula": "6 * 7"}
{"expression": 42}
{}
```

而我们的工具实际要求：

```python
{"expression": "6 * 7"}
```

Function Calling 的核心不是让模型直接执行函数，而是给模型一份工具目录和参数 Schema，
让模型生成结构化的“调用请求”。主程序仍然拥有是否执行的最终控制权。

## 1. JSON Schema 是什么

JSON Schema 是描述 JSON 数据形状的一套标准。计算器的参数可以表示为：

```python
{
    "type": "object",
    "properties": {
        "expression": {
            "type": "string",
            "description": "The arithmetic expression to evaluate.",
        }
    },
    "required": ["expression"],
    "additionalProperties": False,
}
```

逐项理解：

- `type: object`：整个参数必须是一个 JSON 对象；
- `properties`：对象允许有哪些字段；
- `expression.type: string`：表达式必须是字符串；
- `required`：缺少 `expression` 就不是完整调用；
- `additionalProperties: false`：拒绝未声明字段，避免模型悄悄添加参数。

## 2. Schema 在 Agent 中如何流动

```text
CalculatorTool.parameters
          |
          v
Agent 构造 ToolDefinition
          |
          v
Model.decide(messages, tools)
          |
          v
未来的 DeepSeek Adapter
          |
          v
DeepSeek Function Calling 请求
```

这一课只完成前三层。下一阶段实现 Provider Adapter 时，再把 `ToolDefinition` 翻译成
DeepSeek API 所需的 `tools=[{"type": "function", ...}]` 格式。

## 3. 为什么 Schema 不能替代本地校验

Schema 有两个作用：

1. 引导模型生成正确形状的参数；
2. 让主程序在执行前进行通用结构校验。

但它不能替代第二课的安全计算器：

- Schema 能规定 `expression` 是字符串，却不能自动证明字符串里的 AST 安全；
- 模型仍可能生成无效参数；
- 不同 Provider 对 Schema 的支持程度可能不同；
- 恶意调用者可以绕过模型，直接请求工具执行层。

因此最终会形成两层防线：

```text
JSON Schema 校验       → 参数形状是否正确？
CalculatorTool 内部校验 → 表达式内容是否安全？
```

本课先描述 Schema；通用的执行前校验会放到下一课。

## 4. 你的实现任务

这次需要修改四个位置，因为我们正在演练“公共契约发生变化时，所有实现者和消费者都必须
一起演进”。

### 第一步：扩展 `ToolDefinition`

在 `src/agent_lab/contracts.py` 中，让它多一个字段：

```python
parameters: Mapping[str, Any]
```

### 第二步：扩展 `Tool` 协议

同一个文件的 `Tool` 中声明：

```python
parameters: Mapping[str, Any]
```

这里只是接口声明，不需要给它写执行逻辑。

### 第三步：让具体工具提供 Schema

在 `CalculatorTool` 上定义 `parameters`，内容使用本课前面的完整 Schema。

测试工具 `RecordingTool` 也必须满足新的协议。可以在其构造方法中设置一个允许任意对象参数
的通用 Schema：

```python
{
    "type": "object",
    "additionalProperties": True,
}
```

为什么允许任意字段？因为它是测试替身，要记录各个测试传入的不同参数，而不是模拟某一个
固定业务工具。

### 第四步：Agent 负责传递 Schema

在 `Agent.run()` 构造 `ToolDefinition` 时，除了 `name` 和 `description`，还要传入：

```python
parameters = tool.parameters
```

Agent 不应该知道计算器有哪些字段；它只负责忠实地把每个工具的契约交给模型。

## 5. 为什么要修改四个地方

这里有四个不同角色：

| 位置 | 角色 |
| --- | --- |
| `Tool` | 规定所有工具必须提供什么 |
| `CalculatorTool` / `RecordingTool` | 提供具体 Schema |
| `ToolDefinition` | 在 Agent 与模型之间携带 Schema |
| `Agent.run()` | 负责从工具收集并传递 Schema |

如果只修改其中一处，信息链路就会断开。例如工具声明了 Schema，但 Agent 没有传给模型，
对 Function Calling 就没有任何实际作用。

## 6. 验证

运行：

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

完成标准：

- 之前的 9 个测试保持通过；
- 新增的 2 个 Schema 测试通过；
- Ruff 检查与格式检查通过。

## 7. 思考题

1. 为什么 `description` 和 JSON Schema 两者都需要？
2. `additionalProperties` 设为 `True` 会带来什么风险？
3. `ToolDefinition` 使用 `Mapping` 而不是 `dict`，表达了什么设计意图？
4. 如果 Agent 修改了工具提供的 Schema，会发生什么？谁应该拥有这份数据？

## 8. 思考题参考答案

### 1. 为什么 `description` 和 JSON Schema 两者都需要？

它们解决不同问题：

- `description` 表达语义，帮助模型判断“什么时候应该使用这个工具”；
- JSON Schema 表达结构，帮助模型判断“调用时应该生成哪些字段和类型”。

只有 Schema，模型知道参数长什么样，却可能不知道工具适用于什么任务；只有描述，模型理解
用途，却只能猜测参数结构。

### 2. `additionalProperties` 设为 `True` 会带来什么风险？

模型或调用者可以加入契约没有声明的字段。这可能导致：

- 拼写错误没有被及时发现，例如把 `expression` 写成 `expresson`；
- 下游代码意外读取了攻击者提供的额外配置；
- 工具接口悄悄膨胀，不同实现对额外字段产生不同解释；
- 审计时无法确定一次调用真正使用了哪些受支持参数。

生产工具通常采用 `False`；测试替身为了记录各种参数，可以有意识地采用 `True`。

### 3. 使用 `Mapping` 而不是 `dict` 表达了什么设计意图？

`dict` 是一种具体的可变容器；`Mapping` 是“能够按键读取”的抽象接口。使用 `Mapping` 表示
消费者只需要读取 Schema，不应该依赖 `dict` 特有的修改操作，同时也允许调用者传入只读
映射或其他映射实现。

但类型标注不是运行时权限控制：如果实际对象仍是 `dict`，它依然可以被修改。真正需要不可变
时，还要复制、深度冻结或使用不可变数据结构。

### 4. 谁应该拥有 Schema？Agent 修改它会怎样？

具体工具最了解自己的输入，因此工具应该拥有 Schema；Agent 的职责只是读取、传递和校验。
如果 Agent 原地修改共享 Schema，后续请求、其他 Agent 或测试可能观察到不同契约，造成难以
复现的共享状态问题。原则上应把 Schema 当作不可变值；需要 Provider 特定格式时，适配器应
创建新的请求对象，而不是修改工具原始定义。
