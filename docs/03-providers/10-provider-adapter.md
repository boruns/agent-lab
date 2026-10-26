# 第 10 课：Provider Adapter 与协议映射

> **阶段**：3 · 模型 Provider  
> **状态**：已完成
> **最后核验**：2026-10-26  
> **前置**：第 9 课的 Token、消息、结束语义与结构化输出  
> **导航**：[文档中心](../README.md) · [上一课](09-llm-foundations.md) · [下一课](11-deepseek-transport.md) · [课程总纲](../00-overview/curriculum.md)

## 本课要解决的问题

当前 Agent 只依赖项目自己的 Model 协议：

    Message + ToolDefinition
              ↓
          Model.decide()
              ↓
            Decision

真实 Provider 使用另一套 JSON 协议。如果 Agent 直接创建 SDK 对象或读取供应商字段，工具循环、
测试替身和错误处理都会与某个 API 绑定。本课引入 Adapter，把变化限制在边界：

    项目契约 → Provider Adapter → JSON Transport → Provider
    项目决策 ← Provider Adapter ← JSON Response  ← Provider

本课只实现纯映射和注入式 Transport，不安装 SDK、不读取 API Key、不发送网络请求。

## 1. 三层边界

| 层 | 输入输出 | 职责 |
| --- | --- | --- |
| Agent Core | Message、ToolDefinition、Decision | 循环、权限、验证、预算与终止 |
| Provider Adapter | 项目类型 ↔ Provider JSON | 字段映射、名称编码、响应分类 |
| Transport | JSON ↔ HTTP/SDK | 认证、超时、网络、状态码和重试 |

Adapter 不应读取环境变量，也不负责 HTTP 重试。Transport 不应理解 Agent 的权限或工具业务。
第 11 课才会为 Transport 加入真实 DeepSeek 调用、配置、超时和错误映射。

### 补充：Harness 是什么？

Harness 原意是“马具”或“线束”。在 Agent 工程里，它通常指围绕模型、让模型能够持续完成
任务的整套运行时骨架，常见职责包括：

- Agent 循环、消息历史、计划与终止条件；
- Provider 适配、工具注册与执行、文件或 Shell 能力；
- 权限、审批、沙箱、预算、取消与故障恢复；
- Session、工作区、日志、轨迹、UI 和插件扩展点。

可以把模型看作“发动机”，harness 是让它可控、可观测、可使用工具的“底盘和控制系统”。
Provider Adapter 只是 harness 里负责协议翻译的一层，不等于整个 harness。我们的 Agent Lab
正在从零实现一个最小 harness，以便理解框架隐藏的控制边界。

**DeepSeek Harness** 则是 DeepSeek AI 开源的一个具体产品，命令为 `dsh`，强调
“everything is a plugin”的架构。它能组装 Session、模型、工具、工作区、子 Agent、Web UI 等能力。
截至核验日期，官方仍将其标记为 developer preview，公共 API 可能破坏性变更，而且安全文档
明确说明它未经安全审计、不应被视为生产安全边界。课程会把它当作可对照的工程实现，
而不是要求我们照搬的依赖。

## 2. 为什么本课选择 DeepSeek Responses API

截至核验日期，DeepSeek 原生支持 Responses API。该接口用 input items 表示消息和工具结果，
用 output items 表示文本、reasoning 和 function call，适合后续显式保留 call ID 与多项输出。

但“兼容 OpenAI Responses”不代表行为相同：

- DeepSeek Responses 当前是无状态的，多轮调用需要客户端重传历史；
- developer 角色当前会被 DeepSeek 当作 user；
- 部分 OpenAI 参数或 item 类型不受支持，某些不支持参数会被忽略；
- DeepSeek 与 OpenAI 的模型、内建工具和状态管理能力不同。

因此本课实现 DeepSeekResponsesAdapter，而不是用一个 base_url 开关伪装成万能 Adapter。

## 3. Transport 必须可替换

脚手架提供 ProviderTransport：

    create_response(payload: Mapping[str, Any]) -> Mapping[str, Any]

DeepSeekResponsesAdapter 只调用这个协议。测试传入 RecordingTransport，在内存中记录请求并返回
预制 JSON；第 11 课再提供真实实现。这样可以分别判断：

- 映射测试失败：Adapter 逻辑有问题；
- 在线冒烟测试失败：配置、网络、账户或 Provider 有问题。

SDK 类型不能出现在 Agent、Model 协议或确定性测试中。

## 4. 工具公开名称需要可逆编码

第 8 课允许公开名称使用点号，例如 web.search。DeepSeek 当前要求函数名非空、不超过 128 个
字符，并且只包含字母、数字、下划线和连字符。

直接删除点号会产生冲突；简单替换为双下划线也可能与原始下划线名称冲突。本课采用可逆编码：

| Registry 字符 | Provider 编码 |
| --- | --- |
| 下划线 | _u |
| 点号 | _d |
| 字母、数字、连字符 | 原样保留 |

例如：

    web.search     → web_dsearch
    docs.search_v2 → docs_dsearch_uv2

必须先转义原始下划线，再编码点号。decode 遇到未知转义或非法名称时应 fail closed。编码结果
超过 128 字符时抛出 ProviderMappingError，不能截断，因为截断会破坏可逆性并可能制造重名。

## 5. 本课的请求子集

build_request() 只接受当前能够无损表达的内容：

- user 和 assistant 文本消息；
- function 工具定义；
- 非流式调用；
- 显式使用 reasoning effort none，避免依赖 Provider 默认值。

请求形状：

    {
        "model": "deepseek-flash",
        "input": [
            {"type": "message", "role": "user", "content": "hello"}
        ],
        "tools": [
            {
                "type": "function",
                "name": "web_dsearch",
                "description": "Search the web",
                "parameters": {...}
            }
        ],
        "reasoning": {"effort": "none"},
        "stream": false
    }

没有工具时省略 tools，而不是发送空列表。模型 ID 由构造参数注入，不能在 Adapter 内写死。

当前 Message 的 tool 角色缺少 call ID，无法正确构造 function_call_output。不得把它伪装成
user 文本，否则会改变协议语义并丢失调用关联。本课应抛出包含 call ID 提示的
ProviderMappingError；第 12 课会扩展消息契约后再支持它。

## 6. 本课的响应子集

parse_response() 暂时只接受：

- 顶层 status 为 completed；
- output 只包含一个完成的 assistant message；
- message content 包含一个或多个 output_text，按顺序拼接为 FinalAnswer。

以下情况必须显式失败：

- status 为 incomplete、failed 或缺失；
- output 为空或结构错误；
- 出现 function_call；
- 出现当前课程未支持的 output item 或 content part。

尤其不能从包含 function_call 的响应中只提取一段文字并丢弃调用。第 12 课会扩展 Decision 和
历史协议；第 13 课再处理一次返回多个调用。

## 7. 已准备的脚手架

- src/agent_lab/providers.py：异常、Transport 协议、名称 Codec 和 Adapter 骨架；
- tests/test_provider_adapter.py：纯内存请求与响应映射测试。

开始时运行：

    uv run pytest tests/test_provider_adapter.py

测试应因 NotImplementedError 失败。只修改 src/agent_lab/providers.py，不修改测试，也不要安装
OpenAI SDK 或发出网络请求。

## 8. 你的实现任务

### 第一步：实现工具名称 Codec

实现 ProviderToolNameCodec.encode()：

1. 按表格编码下划线和点号；
2. 验证结果符合供应商字符集；
3. 验证长度不超过 128；
4. 无法表示时抛出 ProviderMappingError。

实现 decode()：

1. 从左到右识别 _u 和 _d；
2. 未知或不完整的下划线转义立即失败；
3. 返回原始 Registry 公开名称。

不要用连续 replace() 实现 decode，因为替换顺序容易让编码文本被二次解释。

### 第二步：构造请求

实现 build_request(messages, tools)：

1. user 和 assistant 映射为显式 type=message 的 input item；
2. tool 消息抛出 ProviderMappingError，并说明当前缺少 call ID；
3. 用 Codec 编码每个 ToolDefinition.name；
4. 复制 description 和 parameters，不把 SDK 类型引入核心；
5. 明确设置 reasoning effort none 和 stream false；
6. tools 为空时省略该字段。

保持输入顺序，不修改调用者传入的 Message、ToolDefinition 或 Schema 映射。

### 第三步：解析完成文本

实现 parse_response(response)：

1. 先检查 status；
2. incomplete、failed 或缺失状态均不能变成 FinalAnswer；
3. 检查 output、message、role、item status 和 content 的类型；
4. 按顺序拼接非空 output_text；
5. 没有文本或出现未知 item 时抛出 UnsupportedProviderResponseError；
6. function_call 的错误信息中明确指出将在第 12 课支持。

不要使用未经检查的深层索引直接读取 output 的第一项。

### 第四步：保持 decide() 的职责简单

脚手架已经实现 decide()：

1. build_request()；
2. transport.create_response()；
3. parse_response()。

不要在 decide() 中读取环境变量、创建 SDK Client、捕获所有异常或重试。真实 Transport 属于
第 11 课。

## 9. 验证

实现后运行：

    uv run pytest
    uv run ruff check .
    uv run ruff format --check .

完成标准：

- 名称编码可逆且不会与原始下划线名称冲突；
- 超长或非法名称 fail closed；
- 消息与工具顺序保持不变；
- 工具公开名称只在 Provider 边界编码；
- 缺少 call ID 的工具历史不会被错误降级为 user 消息；
- 完成文本被解析为 FinalAnswer；
- incomplete、failed、function_call 和未知结构不会被当作最终答案；
- 测试不访问网络，不需要 API Key；
- 第 1～9 课原有测试继续通过。

## 10. 思考题

1. 为什么 Adapter 和 Transport 应分开，而不是由一个类同时负责字段映射与 HTTP？
2. 为什么 Provider 工具名编码必须可逆，而不能只删除不支持的字符？
3. 为什么把 tool 结果伪装成 user 消息比直接报错更危险？
4. 为什么“兼容 Responses API”仍不足以让 DeepSeek 和 OpenAI 共用同一个 Adapter？
5. 为什么解析响应时应先检查 status 和 item type，再读取文本？

## 11. 官方参考

- [DeepSeek Responses API](https://api-docs.deepseek.com/api/create-response/)
- [DeepSeek Responses API Guide](https://api-docs.deepseek.com/guides/responses_api/)
- [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
- [DeepSeek Harness Safety](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md)
- [OpenAI Responses API](https://developers.openai.com/api/reference/responses/overview)
- [OpenAI Function Calling](https://developers.openai.com/api/docs/guides/function-calling)

## 12. 思考题参考答案

### 1. Adapter 与 Transport 为什么要分开？

Adapter 处理确定性的协议映射：项目消息如何变成 Provider JSON，Provider 输出如何变成
项目决策。Transport 处理带副作用的 I/O：认证、超时、网络、SDK 和 HTTP 错误。两者的变化
原因也不同：Provider 字段或项目协议变化会影响 Adapter，网络库、代理、重试和连接配置变化会
影响 Transport。

分开后可以获得三个直接收益：

- Adapter 使用内存假对象即可做快速、确定性的映射测试；
- Transport 可以单独验证超时和错误分类，不必构造完整 Agent 对话；
- 更换 SDK 或 HTTP 实现时，不需要改动 Agent 的 `Message`、`Decision` 和控制循环。

如果合在一个类里，纯映射测试也会依赖 Client 配置，网络异常与协议错误容易被混成同一类错误，
职责和测试边界都会变得模糊。

### 2. 工具名编码为什么必须可逆？

响应中只会返回 Provider 看到的工具名。宿主必须把它稳定还原成 Registry 公开名称，才能查找
正确工具、应用正确权限并记录可重放轨迹。删除或普通替换不支持字符会让不同公开名称映射到
同一名称，形成路由和权限混淆。例如直接删除点号会让 `web.search` 与 `websearch` 都变成
`websearch`。

可逆编码还必须没有歧义。本课不仅把 `.` 编码为 `_d`，也先把原始 `_` 编码为 `_u`，因此
`docs.search_v2` 可以被唯一还原。解码时遇到未知或不完整转义必须 fail closed，不能猜测模型
原本指向哪个工具。

### 3. 为什么不能把 tool 结果伪装成 user 消息？

工具结果是对某个具体 call ID 的回复，user 消息则是新的用户输入。降级为 user 会丢失调用关联，
改变模型对内容来源和指令优先级的理解，还会把不可信的工具输出伪装成用户意图。缺少 call ID
时应 fail closed，而不是猜测语义。

这不仅影响回答质量，也影响安全性和重放能力：模型可能把网页或命令输出中的提示注入文本当成
用户要求；多个并发调用时无法判断结果属于哪次调用；审计轨迹也无法证明“调用—结果”配对。
因此正确做法是等待第 12 课扩展消息契约，显式保存 assistant 的调用和对应 `tool_call_id`。

### 4. 为什么 API 兼容仍需独立 Adapter？

兼容通常只代表主要 JSON 形状接近。Provider 仍可能在状态保存、角色映射、推理字段、支持的
item 类型、默认值、错误码、usage 和不支持参数的处理上不同。独立 Adapter 使这些差异显式且
可以通过各自的契约测试固定。

更准确地说，SDK 兼容可以帮助两个 Provider 共用部分 **Transport 机制**，却不能自动证明它们
具有相同的 **协议语义**。即使请求都能成功，某个 Provider 也可能忽略字段、返回不同的结束原因，
或使用不同的工具调用和推理内容结构。通过各自 Adapter 或各自契约测试把差异固定下来，比在
核心代码里散布 Provider 条件分支更安全。

### 5. 为什么先检查 status 和 item type？

文本字段可能出现在被截断、拒绝、失败或同时包含工具调用的响应中。如果先找文本就返回，
Agent 可能把部分输出当成最终答案，或静默丢掉需要执行的工具调用。先验证顶层状态和 item 类型，
再按对应结构读取文本，才能保证结束语义和类型安全。

解析顺序实际上是在验证一个逐层收窄的状态机：先确认响应整体已完成，再确认输出项确实是
assistant message，然后确认 message 与 content part 的状态和类型，最后才读取 `output_text`。
任何未知类型都应显式失败，留给后续课程增加支持；不能把“当前解析器不认识”误判为“模型已经
给出最终答案”。
