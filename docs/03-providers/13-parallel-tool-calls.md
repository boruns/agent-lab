# 第 13 课：多个工具调用的顺序与并行策略

> **状态**：进行中
> **前置课程**：[第 12 课：Function Calling 与调用关联](12-function-calling.md)
> **本课范围**：一个非流式、非 Thinking 响应中的多个 Function Call，以及安全的批次执行与历史重放
> **非目标**：流式参数、DAG 依赖、每工具并发组、事务回滚、模型调用预算和跨进程执行
> **资料核对日期**：2026-10-28
> **导航**：[课程总纲](../00-overview/curriculum.md) · [文档中心](../README.md) · [上一课](12-function-calling.md) · 下一课：流式响应、取消与连接中断

## 1. 本课解决的问题

第 12 课只接受一个 `function_call`。真实 Provider 却可能在一次响应中返回多个调用：

```json
{
  "status": "completed",
  "output": [
    {
      "type": "function_call",
      "status": "completed",
      "call_id": "call_search",
      "name": "web_dsearch",
      "arguments": "{\"query\":\"agents\"}"
    },
    {
      "type": "function_call",
      "status": "completed",
      "call_id": "call_weather",
      "name": "weather",
      "arguments": "{\"city\":\"Shanghai\"}"
    }
  ]
}
```

DeepSeek Responses API 当前忽略请求中的 `parallel_tool_calls`，并始终允许模型提出并行工具调用。
这只表示模型可以在一轮中提出多个调用，不表示本地 Harness 必须让它们同时运行。是否并发要由
本地权限、副作用、线程安全、资源限制和确定性要求共同决定。

本课建立下面的数据流：

```text
模型一次响应
  └── Provider output 中的多个 function_call
        ↓ Adapter：完整解析、保序、拒绝重复 call_id
     ToolCallBatch
        ↓ Agent/Harness：整批预检并选择执行策略
     顺序执行（默认）或只读并发（显式开启）
        ↓ 按 Provider 顺序稳定归并
     assistant 调用块 + tool 结果块
        ↓ Adapter：完整历史重放
     下一次模型请求
```

模型负责提出调用；Adapter 负责协议映射；Agent/Harness 负责校验、权限和调度；工具负责执行一个
动作；外部环境产生真实结果。Provider 返回多个调用，并没有把本地调度权交给模型。

## 2. 当前 Provider 事实与本地工程策略

下面两类结论必须分开：

| 类型 | 本课采用的结论 |
| --- | --- |
| DeepSeek 当前产品事实 | Responses API 无状态；`parallel_tool_calls` 被忽略且并行调用始终启用；`call_id` 必须非空、唯一，每个调用都必须有匹配输出 |
| 项目长期工程策略 | 默认顺序执行；只有 Host 显式开启且整批均为 `READ` 工具时才并发；历史始终按 Provider 调用顺序记录 |

Provider 产品行为以后可能变化，因此上表第一行需要按官方资料重新核验。第二行是本项目主动选择
的安全策略，不随 Provider 默认值自动变化。

## 3. 批次是一个模型决策

脚手架新增了项目自有协议：

```python
@dataclass(frozen=True)
class ToolCallBatch:
    calls: tuple[ToolCall, ...]
```

| 字段名 | 数据类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `calls` | `tuple[ToolCall, ...]` | 是 | 至少两个调用，顺序与 Provider `output` 一致 |

一个调用仍使用 `ToolCall`，两个及以上调用使用 `ToolCallBatch`。这样第 1～12 课的单调用路径保持
兼容，同时批次作为一次 `Decision` 只消耗一个 Agent step。Agent 必须执行完整批次并收集全部预期
结果后，才再次询问模型；不能执行一个调用就提前发起下一次模型请求。

`ToolCallBatch` 不包含“必须并行”的字段。Provider 的输出描述模型提出了哪些调用，并不拥有本地
线程、权限和副作用策略。

## 4. Adapter 必须完整解析批次

当响应 `output` 包含两个及以上项目时，本课只接受所有项目均为已完成 `function_call` 的情况。
Adapter 要：

1. 按 `output` 原顺序复用第 12 课 `_parse_function_call()` 解析每一项；
2. 验证每个 `call_id` 非空且在本批次中唯一；
3. 不按工具名排序，不合并相同工具，也不只取第一项；
4. 返回 `ToolCallBatch(calls=tuple(parsed_calls))`；
5. 对重复 `call_id` 抛出包含 `call ID` 的 `UnsupportedProviderResponseError`。

同一响应混合 `function_call`、普通 `message` 或其他输出类型时，本课明确拒绝。Thinking 模式中的
`reasoning` 项以及流式参数属于后续课程，不能在这里静默忽略。

## 5. 执行前先做整批预检

顺序执行并不意味着可以边发现问题边执行。Agent 在任何工具开始运行前，先检查整个批次：

1. `call_id` 都是非空字符串且批次内唯一；
2. 每个公开工具名都能在 Registry 中解析；
3. 每个工具的权限都属于 `allowed_permissions`；
4. 每组参数都使用对应 Registry Schema 校验；
5. 参数无效时为该调用准备 `INVALID_ARGUMENTS` 的 `ToolResult`，不要调用工具，也不要阻止其他合法调用；
6. 对合法的 `WRITE` 调用，先完成确认并生成各自的幂等键；任何确认缺失或被拒绝时，整批尚未执行任何工具。

这叫 preflight。它降低“第一个工具已经产生副作用，随后才发现第二个调用无权限”的风险。它
不能让一组写操作自动具备事务性：执行阶段仍可能在部分写入后遇到意外异常，回滚不属于本课。

## 6. 默认顺序，显式选择只读并发

脚手架为 `Agent` 增加两个构造参数：

| 参数名 | 数据类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `parallel_tool_calls` | `bool` | `False` | Host 是否允许本 Agent 的只读批次并发 |
| `max_parallel_tools` | `int` | `4` | 并发批次的最大工作线程数，必须大于等于 1 |

执行规则如下：

```text
parallel_tool_calls == False
    └── 整批按 Provider 顺序执行

parallel_tool_calls == True
    ├── 整批所有已解析工具都是 READ → 使用有界线程池并发
    └── 只要存在 WRITE 工具         → 整批按 Provider 顺序执行
```

`READ` 表示工具不应产生外部业务副作用，但不自动证明实现线程安全。Host 打开
`parallel_tool_calls`，也就承担了确认该 Agent 中只读工具可并发调用的责任。更细的每工具并发组、
连接池容量和速率限制留到后续资源调度课程。

并发执行必须使用 `max_parallel_tools` 形成有界线程池，不能为每个调用无限创建线程。已有的工具
重试、截止时间和取消检查仍通过 `_run_tool_with_retries()` 复用；本课不尝试强行终止已经进入工具
实现的 Python 线程。

## 7. 完成顺序不能改变历史顺序

并发工具可能按照 `weather → search` 的顺序完成，但下一轮历史仍固定为：

```json
[
  {
    "type": "function_call",
    "call_id": "call_search",
    "name": "web_dsearch",
    "arguments": "{\"query\":\"agents\"}"
  },
  {
    "type": "function_call",
    "call_id": "call_weather",
    "name": "weather",
    "arguments": "{\"city\":\"Shanghai\"}"
  },
  {
    "type": "function_call_output",
    "call_id": "call_search",
    "output": "search result"
  },
  {
    "type": "function_call_output",
    "call_id": "call_weather",
    "output": "sunny"
  }
]
```

项目历史先保存同一轮的全部 assistant 调用，再按相同顺序保存全部 tool 结果。Agent 可以用调用
索引或 `call_id` 把 Future 结果归位，不能按线程完成顺序追加消息。稳定顺序让测试、重放和轨迹
比较保持确定性。

Adapter 重放批次历史时采用一个小状态机：读取连续的 assistant 调用块，再读取数量相同、顺序
相同的 tool 结果块。孤立结果、重复 ID、缺少结果、结果乱序、名称不匹配或普通消息插入批次，都
必须在网络请求前抛出包含 `call ID` 的 `ProviderMappingError`。

这里“结果必须按调用顺序”是项目自己的规范化约束；Provider 依靠 `call_id` 建立关联，并不意味
所有 Provider 都要求相同的物理排列。

## 8. 预期失败与意外异常

工具返回的 `ToolResult.failure(...)` 和参数校验失败都是预期结果：它们各自形成带原始
`call_id` 的 `function_call_output`，同批其他调用继续执行。

工具直接抛出的编程错误或未知异常仍让本次 Agent run 失败。并发情况下，其他已经提交的只读
工具可能已经运行；本课不承诺撤销它们，也不把异常伪装成成功输出。后续可靠工作流阶段会继续
处理检查点、恢复和部分失败策略。

## 9. 已准备的脚手架

- `src/agent_lab/contracts.py`：新增 `ToolCallBatch`，并把它加入 `Decision`；
- `src/agent_lab/providers.py`：批次响应解析和批次历史重放入口；
- `src/agent_lab/agent.py`：批次预检、顺序/并发执行与稳定记录入口；
- `tests/test_parallel_tool_calls.py`：完全离线的批次协议、历史和调度测试。

开始时运行：

```bash
uv run pytest tests/test_parallel_tool_calls.py
```

测试应只因以下三个预留入口的 `NotImplementedError` 失败：

- `DeepSeekResponsesAdapter._parse_function_call_batch()`；
- `DeepSeekResponsesAdapter._build_batched_function_call_history()`；
- `Agent._execute_tool_call_batch()`。

只修改 `src/agent_lab/providers.py` 和 `src/agent_lab/agent.py`。不要修改测试，不要执行真实 Provider
调用。

## 10. 你的实现任务

### 第一步：解析完整调用批次

实现 `_parse_function_call_batch(items)`：

1. 按传入顺序对每一项调用 `_parse_function_call()`；
2. 用集合跟踪已见 `call_id`；
3. 重复 ID 抛出包含 `call ID` 的 `UnsupportedProviderResponseError`；
4. 返回 `ToolCallBatch(calls=tuple(calls))`；
5. 不修改原始响应对象。

不要在这里查询 Registry 或决定是否并发。Adapter 不拥有本地执行策略。

### 第二步：重放批次历史

实现 `_build_batched_function_call_history(messages)`：

1. `role` 值为 `user` 或 `assistant` 的普通消息仍映射为 `message` 输入项；
2. 遇到 assistant Function Call 时，读取完整的连续调用块；
3. 验证调用块中的 ID 非空且不与此前历史重复；
4. 接下来必须读取数量相同的 tool 结果，并逐项核对 `call_id` 与公开工具名；
5. 分别复用 `_build_function_call()` 和 `_build_function_call_output()`；
6. 任何缺失、重复、错序、名称不匹配或消息插入都抛出包含 `call ID` 的
   `ProviderMappingError`；
7. 返回完整 `input_items`，不要在此构造 Transport 或访问网络。

该方法也应正确处理同一历史中的多个已闭合批次，以及批次前后的普通消息。

### 第三步：整批预检

在 `_execute_tool_call_batch()` 中先完成第 5 节的全部预检。推荐为每个调用准备一个内部记录，
保存原始索引、`RegisteredTool`、预先生成的参数错误结果和可选幂等键，但不要把 Provider SDK
类型放进核心。

完成预检前不得调用任何工具。重复/空 `call_id` 建议抛出包含 `call ID` 的 `ValueError`；未知
工具和权限/确认错误继续复用现有异常类型。不要修改 `ToolCall.arguments`。

### 第四步：执行并稳定归并

1. 默认按调用顺序复用 `_run_tool_with_retries()`；
2. 显式开启并发且整批所有已解析工具均为 `READ` 时，用 `ThreadPoolExecutor` 并发执行；
3. 工作线程数不超过 `max_parallel_tools` 和实际待执行调用数；
4. 参数无效的调用不提交线程，直接使用预检阶段准备的失败结果；
5. 无论 Future 完成顺序如何，都按原始调用索引收集结果；
6. 先向历史追加全部 assistant 调用消息，再追加全部 tool 结果消息；
7. 每对消息使用相同的公开工具名和原始 `call_id`；
8. 在调度边界继续调用 `_raise_if_stopped()`，不要声称能强制终止已经运行的线程。

含任一 `WRITE` 工具的批次必须整批顺序执行。每个合法写调用使用自己预检阶段生成的幂等键，
不能让多个调用共享一个键。

### 第五步：离线验收

```bash
uv run pytest tests/test_parallel_tool_calls.py
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

完成标准：

- 多个 Function Call 被完整、保序地解析为一个 `ToolCallBatch`；
- 重复或空 `call_id` 在任何工具运行前失败；
- 默认执行顺序与 Provider 输出顺序一致；
- 只读批次只有在 Host 显式开启时才有界并发；
- 含写工具的批次不会并发；
- 参数错误和预期工具错误各自形成关联输出，不阻止同批其他合法调用；
- 并发完成顺序不改变历史顺序；
- 批次历史的孤立、缺失、重复、错序和不匹配全部 fail closed；
- 第 1～12 课回归测试继续通过；
- 所有测试离线运行，不需要 API Key。

## 11. 思考题

1. Provider 允许 parallel tool calls，为什么不等于 Agent 必须并发执行？
2. 为什么整批预检要发生在第一个工具运行之前？
3. 为什么 `READ` 权限仍不能自动证明工具实现是线程安全的？
4. 为什么并发完成顺序不应该直接决定历史消息顺序？
5. 一个调用参数无效时，为什么通常不应丢弃同批其他合法调用？
6. 如果并发工具之一抛出意外异常，为什么 Harness 不能声称其他调用都没有执行？

## 12. 官方参考

- [DeepSeek Responses API](https://api-docs.deepseek.com/api/create-response/)
- [DeepSeek Responses API Guide](https://api-docs.deepseek.com/guides/responses_api/)
- [DeepSeek Tool Calls Guide](https://api-docs.deepseek.com/guides/tool_calls/)
