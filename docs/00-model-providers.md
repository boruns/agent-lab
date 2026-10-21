# 模型 Provider 约定：DeepSeek 优先，OpenAI 备用

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

## 为什么可以共享大部分适配逻辑

DeepSeek 提供 OpenAI 兼容的 API 格式，官方 OpenAI 格式 Base URL 是：

```text
https://api.deepseek.com
```

因此我们可以复用 OpenAI Python SDK 的请求/响应类型和 HTTP 能力，但“协议兼容”不等于
“行为完全相同”。不同 Provider 的模型名、推理字段、工具调用限制、错误码、速率限制和
Token 统计仍然需要放在各自的配置或适配层中。

## 模型选择

当前学习环境默认：

```text
Provider: DeepSeek
Model:    deepseek-flash
Thinking: disabled
```

选择 `deepseek-flash` 是为了以较低成本快速迭代控制循环与工具 Schema。需要更强规划或复杂
综合能力时，可以通过环境变量切换到 `deepseek-v4-pro`，不修改业务代码。

第一版关闭 Thinking 的原因不是它不好，而是我们正在学习 Agent 的显式控制循环。先减少
一个变量，等工具调用、终止条件和 Token 统计稳定后，再对比 Thinking 模式的行为与成本。

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
3. 实现 OpenAI-compatible transport；
4. 首先完成 DeepSeek Adapter 和一条手动冒烟测试；
5. 再加入 OpenAI 配置，验证同一 Agent 核心可以切换 Provider；
6. 所有自动化测试继续使用假模型，避免网络、费用和随机性。

## DeepSeek 工具调用注意事项

- 工具参数由模型生成，即使声明了 JSON Schema，执行前仍要在本地验证。
- 工具名必须唯一；本地注册表也要执行相同约束。
- 模型可能一次请求多个工具，而当前教学版 `Decision` 只支持一个；这是后续需要显式演进的
  接口，不能在适配器里静默丢掉多余调用。
- Thinking、`tool_choice` 和 strict mode 存在组合限制；我们会用契约测试固定实际支持范围。
- Token 用量、结束原因和请求 ID 应进入运行轨迹，不能只保留最终文本。
