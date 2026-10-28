# 第 12 课：Function Calling 与调用关联

> **状态**：进行中
> **前置课程**：[第 11 课：DeepSeek Transport](11-deepseek-transport.md)
> **本课范围**：一次响应中的一个 Function Call，以及它与一个 Tool Result 的完整关联
> **非目标**：多个并行调用、流式参数、内置工具、Thinking 模式和 strict beta
> **资料核对日期**：2026-10-26
> **导航**：[课程总纲](../00-overview/curriculum.md) · [文档中心](../README.md) · [上一课](11-deepseek-transport.md) · 下一课：多个工具调用

## 1. 本课解决的问题

前十一课已经能把工具 Schema 发给模型，也能执行本地工具，但真实 Provider 返回工具调用时，
还缺少一条完整的数据链：

```text
Provider function_call
  call_id + encoded name + JSON arguments
                    │
                    ▼
项目 ToolCall ──→ Agent 校验并执行工具
                    │
                    ▼
assistant 调用记录 + tool 结果记录
  使用同一个 call_id
                    │
                    ▼
Provider function_call + function_call_output
```

`call_id` 不是日志装饰，而是调用和结果之间的关联键。工具名称或执行顺序都不能替代它：同一个
工具可以连续调用多次，将来还会出现并行调用。丢失关联后，模型无法确定某个结果回答了哪个请求。

DeepSeek Responses API 当前是无状态的，后续请求必须重放完整历史。对一次工具调用而言，历史中
既要有 assistant 发出的 `function_call`，也要有使用相同 `call_id` 的
`function_call_output`，不能只发送工具结果。

## 2. 三种不要混淆的 ID 和名称

| 字段 | 谁产生 | 作用 | 是否允许改写 |
| --- | --- | --- | --- |
| response `id` | Provider | 标识一次模型响应 | 否 |
| `call_id` | Provider | 关联一次调用与它的结果 | 否，必须原样保存 |
| Tool `name` | Registry / Adapter | 路由到本地工具 | 只允许通过可逆 Codec 转换 |

`function_call` 还可能带有 output item 自身的 `id`。本课不使用它来关联工具结果；官方协议用于
配对的字段是 `call_id`。

## 3. 模型只提出调用，不执行工具

Provider 返回：

```json
{
  "type": "function_call",
  "call_id": "call_123",
  "name": "web_dsearch",
  "arguments": "{\"query\":\"agents\"}"
}
```

Adapter 要把它解析为项目内的 `ToolCall`：

```python
ToolCall(
    name="web.search",
    arguments={"query": "agents"},
    call_id="call_123",
)
```

这里包含三个独立的信任边界：

1. `name` 必须通过第 10 课的 Codec 解码，未知转义不能猜测；
2. `arguments` 虽然是字符串，但必须是合法 JSON **对象**，数组、字符串和数字都不能作为工具参数；
3. JSON 解析成功不代表参数有效，Agent 仍必须使用 Tool Registry 中的 JSON Schema 校验后才能执行。

官方文档也明确说明模型可能生成无效 JSON 或 Schema 中没有的参数。Function Calling 是结构化的
动作提议，不是可信的远程过程调用。

## 4. Provider 历史中的调用与结果

第二轮请求需要包含：

`build_request()` 会在 Agent 每次调用模型前执行，不是只构造第一轮请求。第一轮调用它时，历史
里通常只有 user 消息，不会触发 `_build_function_call_output()`；模型返回 `function_call`、Agent
执行工具并把结果写入历史后，第二轮才会由这个方法把已有结果序列化为
`function_call_output`。它只负责重放已经发生的工具执行，不负责调用工具。

```json
[
  {"type": "message", "role": "user", "content": "search for agents"},
  {
    "type": "function_call",
    "call_id": "call_123",
    "name": "web_dsearch",
    "arguments": "{\"query\":\"agents\"}"
  },
  {
    "type": "function_call_output",
    "call_id": "call_123",
    "output": "result text"
  }
]
```

项目的 `Message` 脚手架新增了 `call_id` 和 `arguments`：

- assistant 调用记录：`name + call_id + arguments`，`content` 为空；
- tool 结果记录：`name + call_id + content`，`arguments` 为空；
- 普通 user/assistant 消息继续只使用 `content`。

Adapter 构造请求时必须验证：tool 结果具有非空 `call_id`，并且它紧跟一个相同 `call_id` 的
assistant 调用。孤立结果、未闭合调用或不匹配 ID 都要在发出网络请求前失败。

## 5. Agent 为什么必须保存 assistant 调用

旧循环只保存了：

```text
user → tool result → assistant final answer
```

本课要变成：

```text
user → assistant function_call → tool result → assistant final answer
```

当 `ToolCall.call_id` 非空时，Agent 在工具执行完成后把调用和结果作为相邻的两条消息写入历史，
二者使用完全相同的 ID 与 Registry 公开名称。即使参数校验失败或工具返回预期错误，也要保留这
一对记录，因为错误结果同样是在回答那次调用。

为保持第 1～11 课的确定性 `ScriptedModel` 测试兼容，`ToolCall.call_id=None` 暂时保留旧路径；
真实 Provider Adapter 解析出的调用必须始终带 ID。这个兼容缝只服务旧课程测试，不应由真实
Provider 使用。

## 6. 为什么本课拒绝多个调用

DeepSeek 当前会始终启用并行工具调用，`parallel_tool_calls` 参数会被忽略，所以真实响应可能
包含多个 `function_call`。正确处理它需要定义顺序、并行、安全审批、部分失败与结果回传规则，
不能在解析器里随手取第一项。

本课遇到多个调用时明确抛出包含 `lesson 13` 的 `UnsupportedProviderResponseError`。第 13 课会
把 `Decision` 从单个 `ToolCall` 扩展为调用批次，并设计顺序与并行策略。

## 7. 已准备的脚手架

- `src/agent_lab/contracts.py`：`Message` 与 `ToolCall` 已加入可选关联字段；
- `src/agent_lab/providers.py`：三个 Function Calling 映射入口；
- `src/agent_lab/agent.py`：保存调用—结果对的入口；
- `tests/test_function_calling.py`：单调用、非法参数、历史重放和 Agent 关联测试。

开始时运行：

```bash
uv run pytest tests/test_function_calling.py
```

测试应只因以下三组 `NotImplementedError` 入口失败：

- `DeepSeekResponsesAdapter._parse_function_call()`；
- `DeepSeekResponsesAdapter._build_function_call()` / `_build_function_call_output()`；
- `Agent._append_function_call_exchange()`。

只修改 `src/agent_lab/contracts.py`、`src/agent_lab/providers.py` 和 `src/agent_lab/agent.py`。不要修改
测试，不要执行真实 API 调用。

## 8. 你的实现任务

### 第一步：解析一个 Function Call

实现 `_parse_function_call(item)`：

1. 验证 item `status` 为 `completed`；
2. 验证 `call_id` 和 Provider `name` 是非空字符串；
3. 用 `ProviderToolNameCodec.decode()` 还原 Registry 公开名称；
4. 验证 `arguments` 是字符串并使用 `json.loads()` 解析；
5. JSON 语法错误或解析结果不是对象时，抛出 `UnsupportedProviderResponseError`；
6. 返回包含原始 `call_id`、公开名称和参数映射的 `ToolCall`。

不要在 Adapter 中执行 JSON Schema 校验。Adapter 不拥有 Tool Registry；Agent 会在执行前完成
Schema 校验。

### 第二步：序列化调用和工具结果

实现 `_build_function_call(message)`：

1. 要求 `role == "assistant"`；
2. 验证 `name`、`call_id` 非空，`arguments` 是映射，`content` 为空；
3. 用 Codec 编码公开工具名；
4. 使用 `json.dumps(..., separators=(",", ":"), ensure_ascii=False)` 生成稳定的紧凑 JSON；
5. 返回包含以下四个字段的对象，其中 `type` 的值固定为 `function_call`：

```python
{
    "type": "function_call",
    "call_id": message.call_id,
    "name": encoded_name,
    "arguments": serialized_arguments,
}
```

实现 `_build_function_call_output(message)`：

1. 要求 `role == "tool"`；
2. 验证 `call_id` 和 `name` 非空，`arguments is None`；
3. 返回包含以下三个字段的对象，其中 `type` 的值固定为 `function_call_output`：

```python
{
    "type": "function_call_output",
    "call_id": message.call_id,
    "output": message.content,
}
```

这个 Provider 输出项不包含 `name`。`call_id` 已经负责关联原始 `function_call`；本地工具名只用于
Adapter 构造前的历史一致性检查，不发送到该输出项中。

所有本地历史映射错误统一抛出 `ProviderMappingError`，不要让 `AttributeError` 或 `TypeError` 泄漏。

### 第三步：验证历史关联

在 `build_request()` 中跟踪尚未获得结果的调用：

1. assistant function call 开启一个 pending call；
2. 下一条必须是相同 `call_id` 和相同公开工具名的 tool 结果；
3. tool 结果不能孤立出现；
4. 普通消息不能插入调用与结果之间；
5. 循环结束时不能留下未闭合调用；
6. 发现重复、错序或不匹配时抛出包含 `call ID` 的 `ProviderMappingError`。

本课只有单调用，所以只需要保存一个 pending call，不要提前实现批次结构。

### 第四步：让 Agent 保存完整交换

实现 `_append_function_call_exchange()`：

1. 再次确认 `decision.call_id` 是非空字符串；
2. 先追加 assistant 消息，保存公开名称、参数副本和 call ID；
3. 再追加 tool 消息，保存格式化后的结果、公开名称和同一个 call ID；
4. 不修改 `decision.arguments`；
5. 继续保留 `call_id=None` 的旧 ScriptedModel 兼容分支。

注意：`ToolResult.failure(...)` 也必须形成 tool 输出，其 `content` 继续使用现有
`_format_tool_result()` 格式。

### 第五步：离线验收

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

完成标准：

- 单个 Function Call 被解析为带原始 call ID 的项目 `ToolCall`；
- 参数必须是 JSON 对象，且在执行前仍经过 Registry Schema 校验；
- Agent 历史同时保存 assistant 调用和 tool 结果；
- 第二轮请求使用同一个 call ID 重放调用与结果；
- 孤立、错序、不匹配和未闭合关联全部 fail closed；
- 多调用明确留给第 13 课，不丢弃任何调用；
- 第 1～11 课测试继续通过；
- 全部测试离线运行，不需要 API Key。

## 9. 思考题

1. 为什么工具名称和执行顺序都不能替代 `call_id`？
2. 为什么 JSON 解析成功后仍必须做 JSON Schema 校验？
3. 为什么历史中必须同时保存 assistant 的调用和 tool 的结果？
4. 为什么工具执行失败也应该返回关联到原调用的 `function_call_output`？
5. 为什么 Adapter 不应该直接查询 Tool Registry？
6. DeepSeek 始终可能并行调用工具时，本课为什么选择明确拒绝而不是只执行第一项？

## 10. 官方参考

- [DeepSeek Responses API](https://api-docs.deepseek.com/api/create-response/)
- [DeepSeek Responses API Guide](https://api-docs.deepseek.com/guides/responses_api/)
- [DeepSeek Tool Calls Guide](https://api-docs.deepseek.com/guides/tool_calls/)
- [OpenAI Function Calling Guide](https://developers.openai.com/api/docs/guides/function-calling)

