# 第 5 课：结构化 ToolResult 与工具错误分类

> **阶段**：2 · 可靠工具系统  
> **状态**：进行中  
> **前置**：第 4 课的执行前参数校验  
> **导航**：[文档中心](../README.md) · [上一课](04-argument-validation.md) · [课程总纲](../00-overview/curriculum.md)

## 本课要解决的问题

第 4 课遇到参数错误时直接抛异常。安全边界已经成立：错误参数不会触达工具；但 Agent 也立即
结束了，模型没有机会根据错误修正调用。

工具自身同样会遇到预期内失败，例如天气服务暂不可用或计算器发生除零。若成功和失败都只是
字符串，上层只能解析自然语言猜测结果；若所有失败都抛异常，又无法区分可交给模型处理的业务
失败和应该暴露给开发者的程序缺陷。

本课引入结构化 `ToolResult`，让预期结果成为数据，并保留异常表示意外故障。

## 1. 三条不同的失败路径

| 场景 | 表示方式 | 本课的处理 |
| --- | --- | --- |
| 工具声明了非法 Schema | `InvalidToolSchemaError` | 初始化失败，交给开发者修复 |
| 参数或工具执行出现预期内失败 | `ToolResult.failure(...)` | 形成工具观察结果，反馈给模型 |
| 工具存在程序缺陷 | 原始异常 | 不隐藏，交给开发者和监控系统 |

“失败是一等数据”不等于捕获所有 `Exception`。如果把 `TypeError`、`AssertionError` 等程序缺陷
伪装成普通工具结果，Agent 可能在损坏的状态上继续运行，也会让问题更难被发现。

## 2. ToolResult 的结构

项目已经提供以下最小契约：

```python
class ToolErrorKind(StrEnum):
    INVALID_ARGUMENTS = "invalid_arguments"
    EXECUTION_ERROR = "execution_error"


@dataclass(frozen=True)
class ToolError:
    kind: ToolErrorKind
    message: str


@dataclass(frozen=True)
class ToolResult:
    output: str | None = None
    error: ToolError | None = None
```

合法结果必须恰好处于一种状态：

```text
成功：output 是字符串，error 是 None
失败：output 是 None，error 是 ToolError
```

不能两者都有，也不能两者都没有。`__post_init__` 维护这个不变量；调用者使用
`ToolResult.success(...)` 和 `ToolResult.failure(...)` 构造结果。

## 3. 分类描述原因，不决定策略

本课只有两个错误类别：

- `INVALID_ARGUMENTS`：参数形状或内容不符合工具要求，调用者可能通过修改参数解决；
- `EXECUTION_ERROR`：参数有效，但工具未能完成操作，例如除零或依赖服务不可用。

错误类别说明“发生了什么”，并不直接说明“是否应该重试”。同样是 `EXECUTION_ERROR`，临时网络
中断可能值得重试，账户永久停用则不应该重试。`retryable`、退避和最大尝试次数属于第 6 课。

## 4. 结果在 Agent 中如何流动

```text
模型产生 ToolCall
        |
        v
Schema 校验 -----失败----> ToolResult.failure(INVALID_ARGUMENTS, ...)
        |
       成功
        v
tool.run(arguments) ------> ToolResult.success(...) 或已分类的 failure(...)
        |
        v
Agent 转成 tool Message ----> 模型决定修正、换工具或回答
```

给模型的文本格式在本课固定为：

```text
成功：<output>
失败：Tool error [<kind>]: <message>
```

`ToolResult` 是程序可以可靠检查的内部契约；文本只是当前简化消息协议中的模型观察。阶段 3 接入
真实 Provider 时，会进一步补充调用 ID 和供应商消息映射。

## 5. 你的实现任务

契约、测试替身和失败测试已经准备好。请修改 `src/agent_lab/tools.py` 和
`src/agent_lab/agent.py`，不要修改测试来迁就旧行为。

### 第一步：让 CalculatorTool 返回 ToolResult

把 `CalculatorTool.run()` 的所有预期结果转换成结构化结果：

- 正常计算返回 `ToolResult.success(str(value))`；
- 缺少参数、类型错误、语法错误和不安全 AST 返回
  `ToolResult.failure(ToolErrorKind.INVALID_ARGUMENTS, message)`；
- `ZeroDivisionError` 返回
  `ToolResult.failure(ToolErrorKind.EXECUTION_ERROR, message)`。

`_evaluate()` 可以继续通过 `UnsafeExpressionError` 阻止不安全节点，`run()` 在工具边界捕获这个
已知异常并转换。不要捕获宽泛的 `Exception`。

### 第二步：让参数校验失败成为结果

在 `Agent.run()` 中，`ValidationError` 不再转换成终止运行的
`ToolArgumentsValidationError`，而是创建：

```python
ToolResult.failure(
    ToolErrorKind.INVALID_ARGUMENTS,
    error.message,
)
```

校验失败时仍然不能调用工具。Agent 应把错误结果追加为 `tool` 消息，然后进入下一轮，让模型
决定是否修正。每一次失败仍占用一个 step，因此现有最大步数是第一道循环上限。

### 第三步：处理工具返回的结果

参数合法时调用 `tool.run()`，得到 `ToolResult`：

- 成功结果的消息内容使用 `result.output`；
- 失败结果格式化为 `Tool error [kind]: message`；
- 工具抛出的意外异常自然向上传播，不要用 `except Exception` 隐藏。

成功和失败最终都追加：

```python
Message(role="tool", content=observation, name=tool.name)
```

可以提取一个小的私有格式化函数，避免让主循环承担过多表示细节。

## 6. 运行失败测试

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

进入本课时，测试应当失败，因为生产代码仍返回字符串并在参数校验失败时抛异常。完成标准：

- `ToolResult` 不允许成功与失败两种状态混杂；
- 计算器的成功、无效表达式和除零都得到正确分类；
- Schema 校验失败不会执行工具，并允许模型下一步修正；
- 工具主动返回的执行错误会带类别进入模型消息；
- 意外的 `RuntimeError` 不会被 Agent 隐藏；
- 之前的行为无回归，Pytest 和 Ruff 全部通过。

## 7. 思考题

1. 为什么 `ToolResult` 要强制“输出和错误恰好二选一”？
2. 为什么不应该在 Agent 中捕获所有 `Exception` 并统一返回给模型？
3. 为什么错误类别和“是否可重试”应该是两个维度？
4. 参数校验失败交给模型修正后，现有 `max_steps` 能防止什么，又不能防止什么？
