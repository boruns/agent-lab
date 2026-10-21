# 第 4 课：执行前校验工具参数

> **阶段**：2 · 可靠工具系统  
> **状态**：进行中  
> **前置**：第 3 课的工具 JSON Schema  
> **导航**：[文档中心](../README.md) · [上一课](03-json-schema.md) · [课程总纲](../00-overview/curriculum.md)

## 本课要解决的问题

第 3 课把 JSON Schema 交给了模型，但“告诉模型应该怎么做”不等于“模型一定会这么做”。
即便 DeepSeek 支持 Function Calling，也仍可能出现：

```python
ToolCall("weather", {"city": 42})  # 类型错误
ToolCall("weather", {})  # 缺少必填字段
ToolCall("weather", {"city": "上海", "x": 1})  # 出现额外字段
```

调用还可能来自测试、其他服务或攻击者，完全绕过模型。因此执行工具之前，Agent 自己必须校验
参数。安全边界必须由我们控制的确定性代码建立，不能依赖模型“听话”。

## 1. 两种不同的校验

本课区分两种错误来源：

| 检查时间 | 检查对象 | 错误类型 | 谁需要修复 |
| --- | --- | --- | --- |
| Agent 初始化 | 工具声明的 Schema | `InvalidToolSchemaError` | 工具开发者 |
| 每次工具执行前 | 模型生成的 arguments | `ToolArgumentsValidationError` | 模型/调用者 |

Schema 是工具开发者写的配置。如果 Schema 本身错误，应在 Agent 启动时尽早失败，而不是等到
用户请求到来后才发现。

arguments 是每次运行产生的数据，必须在每一次工具调用前验证。验证失败时绝不能调用工具。

## 2. 为什么使用成熟的 `jsonschema` 库

JSON Schema 包含嵌套对象、数组、组合规则、引用、格式和不同规范版本。自己写几个 `if` 只能
覆盖很小的子集，还容易让“发给模型的规则”和“本地执行的规则”不一致。

我们使用 `jsonschema` 的 `Draft202012Validator`：

```python
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
```

- `Draft202012Validator.check_schema(schema)` 检查 Schema 本身是否合法；
- `validator = Draft202012Validator(schema)` 创建可重复使用的校验器；
- `validator.validate(arguments)` 校验一次实际参数。

## 3. 校验发生在哪里

```text
Agent.__init__
    ├── 收集工具
    ├── 检查每份 Schema
    └── 为每个工具创建 Validator

Agent.run
    ├── 模型产生 ToolCall
    ├── 检查工具是否存在
    ├── Validator.validate(arguments)  <-- 新增门槛
    └── tool.run(arguments)
```

校验必须位于“找到工具”和“执行工具”之间。未知工具没有 Schema 可查；已经执行之后再校验则
失去了保护意义。

## 4. 你的实现任务

依赖已经加入项目，两个异常类和测试脚手架也已准备好。你只需要修改
`src/agent_lab/agent.py`。

### 第一步：导入校验器和底层异常

```python
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
```

### 第二步：在初始化时建立校验器

为每个工具：

1. 调用 `Draft202012Validator.check_schema(tool.parameters)`；
2. 如果抛出 `SchemaError`，转成包含工具名的 `InvalidToolSchemaError`；
3. Schema 合法时创建 `Draft202012Validator(tool.parameters)`；
4. 按工具名保存，供每次运行复用。

不要在每次循环里重新编译 Schema。Schema 属于工具定义，不会随一次 Agent 运行而变化。

### 第三步：执行前校验参数

在 `tool.run()` 之前：

1. 取出对应 Validator；
2. 调用 `.validate(dict(decision.arguments))`；
3. 捕获 `ValidationError`；
4. 转成包含工具名和 `error.message` 的 `ToolArgumentsValidationError`；
5. 只有校验成功才执行工具。

使用 `raise ... from error` 保留底层错误链，方便排查具体违反了哪条 Schema 规则。

## 5. 为什么当前选择抛异常

另一种策略是把校验错误作为工具观察结果交还给模型，让模型修正参数后重试。这个策略很有
价值，但它会引入重试次数、错误消息泄露和预算消耗等新问题。

本课先采用 fail-fast：校验失败立即终止，使安全边界和错误类型清晰。下一课会专门设计工具
错误如何反馈给模型，以及哪些错误可以重试。

## 6. 验证

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

完成标准：

- 合法参数能够到达工具；
- 类型错误在工具执行前被拒绝；
- 非法 Schema 在 Agent 初始化时被拒绝；
- 原有测试全部保持通过；
- Ruff 全部通过。

## 7. 思考题

1. 为什么 Validator 应该在初始化时创建，而不是每次调用工具时创建？
2. 为什么要把 `SchemaError` 和 `ValidationError` 转换成项目自己的异常？
3. 参数校验失败后直接终止，与交给模型重试，各有什么优缺点？
4. JSON Schema 验证通过，为什么工具内部仍然不能完全信任输入？
