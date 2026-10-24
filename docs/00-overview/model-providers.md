# 模型 Provider 约定：DeepSeek 优先，OpenAI 备用

> **文档类型**：架构决策  
> **状态**：约定完成，Adapter 尚未实现  
> **最后核验**：2026-10-24（以 DeepSeek 和 OpenAI 官方 API 文档为准）
> **导航**：[文档中心](../README.md) · [系统课程总纲](curriculum.md)

## 决策

本项目默认接入 DeepSeek，OpenAI 作为可切换的备用 Provider：

```text
Agent.run()
    |
    v
Model 协议（项目自己的稳定边界）
    |
    +--> DeepSeek Adapter（默认）
    |
    +--> OpenAI Adapter（备用）
```

Agent 核心只能依赖 `Model` 协议，不能直接依赖 DeepSeek 或 OpenAI SDK。这样切换模型时，
工具系统、控制循环、预算和记忆逻辑都不需要修改。

## 兼容格式不等于相同行为

DeepSeek 当前同时提供 OpenAI Chat Completions、OpenAI Responses 和 Anthropic 格式。
OpenAI 格式 Base URL 是：

```text
https://api.deepseek.com
```

可以复用官方 SDK 的 HTTP 能力和部分数据形状，但不在 Agent 核心中直接传递 SDK
对象。不同 Provider 即使使用同一 API 外形，在状态保存、消息角色、推理字段、工具调用限制、
错误码和 Token 统计上仍可能不同。例如 DeepSeek 当前的 Responses API 是无状态的，
多轮请求需要客户端重传必要历史。

本项目因此保留独立的 DeepSeek Adapter 和 OpenAI Adapter，并用 Provider 契约测试
验证各自映射，不实现一个靠 `base_url` 切换的“万能适配器”。

## 模型选择

当前学习环境默认：

```text
Provider: DeepSeek
Model:    deepseek-flash
Thinking: disabled
```

截至核验日期，DeepSeek 官方 API 的两个公开模型 ID 是 `deepseek-flash` 和
`deepseek-v4-pro`。`deepseek-flash` 是指向当前 Flash 版本的别名，不是永久固定的
权重版本。当前官方页面列出 1M 上下文窗口和最大 384K 输出，但这些数值属于时效
快照，不会写死在 Agent 核心中。运行时配置必须显式提供模型 ID，评测轨迹应记录
请求的 ID 和服务端返回的版本信息（如果有）。

当前 DeepSeek 的 Thinking 默认是启用的；项目中的 `disabled` 是我们将显式发送的
教学配置，不是对供应商默认值的描述。第一版关闭 Thinking，是为了先减少一个变量；
等工具调用、终止条件和 Token 统计稳定后，再用同一评测集对比推理努力的质量、成本
和延迟。不依赖服务端默认值，因为它可能变更。

## API Key 配置

从模板创建本地配置：

```bash
cp .env.example .env
```

然后只在本机的 `.env` 中填写：

```dotenv
AGENT_LAB_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_key
```

运行需要密钥的命令时显式加载：

```bash
uv run --env-file .env <command>
```

`.env` 已被 `.gitignore` 排除；`.env.example` 只记录变量名和安全的默认值，必须提交。

不要：

- 把真实 Key 写进 `.env.example`、源代码、测试或文档；
- 在日志中打印完整 Key；
- 把 Key 放进命令行参数，因为它可能进入 Shell 历史；
- 在单元测试里调用付费 API。

## 切换到 OpenAI

本地 `.env` 可以改成：

```dotenv
AGENT_LAB_PROVIDER=openai
OPENAI_API_KEY=你的_key
OPENAI_MODEL=你选择的模型名
```

OpenAI 模型名不在模板中写死。模型供应商会更新可用模型，而我们的代码只要求运行时提供
一个明确的模型标识。

## 实现顺序

真实 Provider 暂不抢在第 1 课之前实现：

1. 用 `ScriptedModel` 完成并测试 ReAct 控制循环；
2. 扩展 `ToolDefinition`，加入参数 JSON Schema；
3. 定义 Provider-neutral 的请求、响应和错误契约，不泄漏任一 SDK 类型；
4. 基于当时的官方文档选择 API 方言，首先完成 DeepSeek Adapter 和一条手动冒烟测试；
5. 再加入 OpenAI 配置，验证同一 Agent 核心可以切换 Provider；
6. 所有自动化测试继续使用假模型，避免网络、费用和随机性。

## DeepSeek 工具调用注意事项

- 工具参数由模型生成，即使声明了 JSON Schema，执行前仍要在本地验证。
- 工具名必须唯一；本地注册表也要执行相同约束。
- 模型可能一次请求多个工具，而当前教学版 `Decision` 只支持一个；这是后续需要显式演进的
  接口，不能在适配器里静默丢掉多余调用。
- Thinking、`tool_choice` 和 strict mode 存在组合限制；我们会用契约测试固定实际支持范围。
- Token 用量、结束原因和请求 ID 应进入运行轨迹，不能只保留最终文本。

## 官方参考

- [DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [DeepSeek Responses API](https://api-docs.deepseek.com/api/create-response/)
- [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)
- [OpenAI Responses API](https://developers.openai.com/api/reference/responses/overview)
- [OpenAI Function Calling](https://developers.openai.com/api/docs/guides/function-calling)
