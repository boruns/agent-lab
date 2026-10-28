# 第 11 课：DeepSeek 基础调用、配置与 Transport 边界

> **状态**：已完成
> **前置课程**：[第 10 课：Provider Adapter 与协议映射](10-provider-adapter.md)
> **本课范围**：真实 SDK 的创建与单次同步调用；暂不实现 Function Calling、重试或流式响应
> **资料核对日期**：2026-10-26
> **导航**：[课程总纲](../00-overview/curriculum.md) · [文档中心](../README.md) · [下一课](12-function-calling.md)

## 1. 这节课解决什么问题

第 10 课的 Adapter 已能在项目协议与 DeepSeek JSON 之间转换，但它使用的是抽象的
`ResponsesTransport`，还不会真正访问模型。本课补上网络边界：

```text
Agent / DeepSeekResponsesAdapter
              │ 普通 Python Mapping
              ▼
DeepSeekResponsesTransport
              │ OpenAI Python SDK（DeepSeek 兼容接口）
              ▼
       DeepSeek Responses API
```

Transport 只负责以下事情：

- 从经过验证的配置创建 SDK Client；
- 为一次请求设置明确的物理超时；
- 把 SDK 对象转换为普通、JSON 兼容的映射；
- 把供应商/SDK 异常映射为项目内稳定的错误分类；
- 提取并记录调用 ID、模型和 Token 用量。

它不负责构造消息、解析 Agent 决策、重试、退避或选择工具。Adapter 与 Transport 分开后，
Provider 的字段映射仍可完全离线测试，而 SDK 升级不会把类型扩散到 Agent 核心。

## 2. 为什么本课使用 OpenAI Python SDK

DeepSeek 当前的 Responses API 与 OpenAI SDK 兼容，官方示例也使用 `OpenAI` Client 并把
`base_url` 指向 `https://api.deepseek.com`。项目因此引入 `openai` 作为**传输实现依赖**，但
`Message`、`Decision`、Adapter 和 Agent 核心都不导入 SDK 类型。

当前锁文件固定了可复现的实际版本。以后升级依赖时应重新运行本课契约测试，不能只因为 API
声称兼容就假设行为完全相同。

## 3. 配置与密钥边界

`DeepSeekSettings.from_env()` 读取以下变量：

| 环境变量 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | 是 | 无 | 去除首尾空白后不能为空 |
| `DEEPSEEK_MODEL` | 否 | `deepseek-flash` | 不能为空 |
| `DEEPSEEK_BASE_URL` | 否 | `https://api.deepseek.com` | 必须使用 HTTPS |
| `DEEPSEEK_TIMEOUT_SECONDS` | 否 | `30` | 必须是大于 0 的数字 |

密钥不应进入源码、Git、异常信息或对象的 `repr`。脚手架已经用 `field(repr=False)` 隐藏
`api_key`。`.env.example` 只记录变量名和非秘密默认值；本地真实值放入被忽略的 `.env`。

测试必须把显式映射传给 `from_env()`，避免测试结果受到开发机环境变量影响。只有调用者没有
传映射时才读取 `os.environ`。

## 4. 两种不同的超时

第 6 课中 `Agent.run(timeout=...)` 的超时是**协作式截止时间**：控制器会在步骤之间检查时间，
但不能强行中断一个正在阻塞的模型请求。本课 SDK 的 `timeout` 才是网络调用的物理超时。
生产系统通常两者都需要：

```text
Agent 总截止时间
└── 模型 HTTP 超时
    └── 工具执行超时
```

OpenAI Python SDK 当前默认会自动重试部分错误，并有较长的默认超时。本项目在 Client 创建时
显式传入 `timeout=settings.timeout` 和 `max_retries=0`：本课 Transport 不偷偷重试，后续课程
再由能感知预算、幂等性和全局截止时间的上层策略决定是否重试。

## 5. 稳定的错误模型

上层不应依赖 `openai.APITimeoutError` 等第三方异常。Transport 捕获 SDK 异常并抛出
`ProviderTransportError`，其中包含稳定的 `kind`、`retryable` 和可选 `status_code`。

| SDK/HTTP 情况 | `ProviderErrorKind` | 可重试 |
| --- | --- | --- |
| `APITimeoutError` 或 HTTP 408 | `TIMEOUT` | 是 |
| `APIConnectionError` | `CONNECTION` | 是 |
| HTTP 401 | `AUTHENTICATION` | 否 |
| HTTP 402 | `INSUFFICIENT_BALANCE` | 否 |
| HTTP 429 | `RATE_LIMIT` | 是 |
| HTTP 400 / 422 | `INVALID_REQUEST` | 否 |
| HTTP 5xx | `SERVER` | 是 |
| 其他 SDK/HTTP 错误 | `UNKNOWN` | 否 |

`retryable=True` 只是分类信息，不代表本层立即重试。认证失败、余额不足和请求错误不会因为等待
而自行恢复；限流、连接失败和服务端故障则可能恢复，但是否重试仍需考虑截止时间和调用预算。

不要用 `except Exception` 把代码错误也伪装成网络故障。只转换已知的 SDK 异常；响应结构错误
单独归类为不可重试的 `PROTOCOL`。

## 6. SDK 类型止步于边界

成功调用 `client.responses.create(**payload)` 后：

1. 调用响应对象的 `model_dump(mode="json")`；
2. 验证结果是映射；
3. 验证并提取 `id`、`model` 与 `usage`；
4. 需要时通过 `record_call` 回调记录 `ProviderCallRecord`；
5. 把普通映射返回给第 10 课的 Adapter。

用量至少包含 `input_tokens`、`output_tokens` 和 `total_tokens`；同时读取
`input_tokens_details.cached_tokens` 与 `output_tokens_details.reasoning_tokens`，缺失的明细按 0
处理。字段缺失、类型错误、负数或总数不一致都说明协议不符合本项目假设，应抛出
`ProviderTransportError(kind=PROTOCOL, retryable=False)`，不能静默记成 0。

本课用回调而不是全局日志器，是为了保持核心最小、让测试能直接观察记录。后续轨迹课程会把它
接入统一的运行记录。

## 7. Harness 在这里是什么

Harness（执行支架）是包住模型的工程系统：它装配上下文与工具，发起调用，执行工具，处理
超时/权限/重试，记录轨迹并判断何时结束。模型负责生成下一步内容，harness 负责让这一步在
真实环境中可控地发生。

在本项目里，Agent 循环、Tool Registry、Adapter 和本课 Transport 都属于 harness 的组成
部分；DeepSeek API 和模型本身不属于。DeepSeek 官方的 `deepseek-harness` 是一个具体参考实现，
不是“harness”这个通用概念本身，也不是本课需要引入的依赖。

## 8. 已准备的脚手架

- `src/agent_lab/deepseek.py`：配置、错误、用量记录和 Transport 骨架；
- `tests/test_deepseek_transport.py`：完全离线的 SDK 假对象与边界测试；
- `scripts/deepseek_smoke.py`：显式、可能产生费用的真实调用脚本；
- `.env.example`：非秘密配置示例。

开始前运行：

```bash
uv run pytest tests/test_deepseek_transport.py
```

首次开始本课时，测试会因三个预留的 `NotImplementedError` 失败。练习要求：**只修改
`src/agent_lab/deepseek.py`，不要修改测试。**

## 9. 你的实现任务

### 第一步：从环境读取并验证配置

实现 `DeepSeekSettings.from_env()`：

1. `env is None` 时读取 `os.environ`，否则只读取传入映射；
2. 取出 API Key，缺失或空白时抛出包含变量名的 `ValueError`；
3. 为模型、Base URL 和超时应用表格中的默认值；
4. 把超时解析成 `float`，解析失败时抛出包含 `DEEPSEEK_TIMEOUT_SECONDS` 的 `ValueError`；
5. 返回 `DeepSeekSettings`，复用 `__post_init__()` 做最终约束验证。

不要读取 `.env` 文件、打印配置或修改传入的映射。`.env` 的加载由命令行/部署环境负责。

### 第二步：显式创建 SDK Client

实现 `build_deepseek_transport()`：

1. 创建 `openai.OpenAI`；
2. 传入 `api_key`、`base_url`、`timeout`；
3. 传入 `max_retries=0`，明确由上层拥有重试策略；
4. 用 Client 和原样传递的 `record_call` 构造 `DeepSeekResponsesTransport`。

### 第三步：调用 API 并映射错误

实现 `DeepSeekResponsesTransport.create_response()`：

1. 复制 `payload` 后以关键字参数调用 `self._client.responses.create()`；
2. 不修改调用者传入的映射；
3. 按第 5 节规则捕获并转换 SDK 错误；
4. 保留原异常作为 `__cause__`（使用 `raise ... from error`）；
5. 本层不重试。

映射 HTTP 错误时读取 `APIStatusError.status_code`。先处理超时/连接异常，再处理有状态码的
`APIStatusError`，避免宽泛父类提前吞掉更精确的类型。

### 第四步：转换响应并记录 Usage

在调用成功后：

1. 用 `model_dump(mode="json")` 得到普通数据；
2. 验证顶层以及 `usage`、两个可选 details 的结构；
3. 验证所需字段的实际类型是 `str` 或 `int`；注意 Python 的 `bool` 是 `int` 的子类，Token
   字段不应接受布尔值；
4. 构造 `ProviderUsage` 与 `ProviderCallRecord`；
5. 只有提供了 `record_call` 时才调用它一次；
6. 返回普通响应映射。

SDK 调用失败时不得记录成功用量。回调自身抛出的异常不要误分类为 Provider 网络错误。

### 第五步：完成离线验收

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

完成标准：

- 单元测试无需 API Key、网络或账户余额；
- 密钥不会出现在对象表示或错误中；
- SDK 的默认超时与隐藏重试已被显式覆盖；
- 所有成功响应都返回普通映射，并产生准确的用量记录；
- 已知错误被稳定分类，未知错误默认不可重试；
- 第 1～10 课测试继续通过。

## 10. 可选真实冒烟测试

离线验收通过后，如你愿意使用自己的 Key 发起一次可能计费的请求，可显式运行：

```bash
uv run --env-file .env python scripts/deepseek_smoke.py
```

脚本应打印 `agent-lab-ok` 和一条不含密钥的用量记录。它不属于默认测试，也不要在 CI 中运行。
模型名称或账户权限变化时，以 DeepSeek 当前控制台与官方文档为准。

## 11. 思考题

1. 为什么 `max_retries=0` 不等于系统永远不应该重试？
2. 为什么 Agent 的总超时无法替代 HTTP Client 的物理超时？
3. 为什么 429 可以标记为可重试，而 401 和 402 通常不可以？
4. 为什么 Usage 结构错误应该让调用失败，而不是全部记为 0？
5. 为什么 Transport 返回普通映射，而不是把 SDK Response 对象继续传给 Adapter？
6. 如果记录回调失败，模型调用已经产生的费用和业务调用结果应如何处理？

## 12. 官方参考

- [DeepSeek：Your First API Call](https://api-docs.deepseek.com/api/responses)
- [DeepSeek：Create a Response](https://api-docs.deepseek.com/api/create-response/)
- [DeepSeek：API Error Codes](https://api-docs.deepseek.com/quick_start/error_codes/)
- [DeepSeek：Rate Limit](https://api-docs.deepseek.com/quick_start/rate_limit/)
- [OpenAI Python SDK：Retries and Timeouts](https://github.com/openai/openai-python#retries)
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)

## 13. 思考题参考答案

### 1. 为什么 `max_retries=0` 不等于系统永远不应该重试？

`max_retries=0` 只是关闭 SDK 内部不可见的自动重试，把重试所有权交还给 Harness。上层仍可根据
错误分类、剩余截止时间、调用预算和幂等性决定是否重试。这样每一次物理请求都会被计数和记录，
不会出现 Agent 以为调用一次、SDK 实际调用多次的情况。

### 2. 为什么 Agent 总超时不能替代 HTTP Client 的物理超时？

当前 Agent 总超时是协作式的，只能在模型或工具调用返回后检查截止时间。如果网络连接一直阻塞，
控制权没有回到 Agent，它就无法及时检查。HTTP Client 超时直接约束连接、读取和整个请求，负责
让阻塞操作有界；Agent 总超时则约束跨多个模型与工具步骤的整体任务，两者作用层级不同。

### 3. 为什么 429 可重试，而 401 和 402 通常不可重试？

429 表示当前速率或并发容量不足，等待服务端建议的时间或退避后，外部条件可能恢复。401 通常
意味着凭据缺失或无效，402 表示余额不足；不改变 Key、权限或账户余额就重复相同请求，只会再次
失败并浪费预算。因此前者可以标记为暂时性错误，后两者应尽快暴露给操作者处理。

### 4. 为什么 Usage 结构错误不能全部记为 0？

0 是一个真实业务值，不是“未知”的同义词。把缺失或错误的 Usage 记成 0，会低估成本、绕过
Token 预算、污染缓存命中率和模型对比数据，还让账单与本地轨迹无法核对。协议不满足预期时应
明确失败或记录为独立的未知状态；本课选择不可重试的 `PROTOCOL` 错误来 fail closed。

### 5. 为什么 Transport 返回普通映射，而不继续传 SDK Response？

普通映射把 SDK 类型限制在 Transport 边界，使 Adapter 能用内存数据做确定性测试，也避免核心
代码依赖 SDK 的 Pydantic 模型、懒加载属性和版本变化。它还便于序列化、记录和重放。代价是
Transport 必须显式验证并保留项目真正需要的字段，而不能依赖 SDK 对象帮忙隐藏协议差异。

### 6. 如果记录回调失败，已经产生的费用和调用结果怎么办？

模型请求已经在外部完成，费用不能因本地记录失败而回滚，也不能盲目重新调用模型，否则可能
重复计费并得到不同结果。本课让回调异常原样暴露，提醒调用者结果没有被可靠记录。生产实现应
把“模型结果”和“遥测持久化状态”分开，保留 response ID 与原始结果，单独重试记录或写入
outbox；是否仍把业务结果交给上层，需要由明确的可靠性策略决定。

