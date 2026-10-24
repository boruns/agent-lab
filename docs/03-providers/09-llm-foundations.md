# 第 9 课：LLM 基本词汇与 Provider 边界

> **阶段**：3 · 模型 Provider  
> **状态**：进行中  
> **最后核验**：2026-10-24  
> **前置**：第 8 课的 Tool Registry 与生命周期  
> **导航**：[文档中心](../README.md) · [上一课](../02-tools/08-tool-registry.md) · [课程总纲](../00-overview/curriculum.md)

## 本课要解决的问题

接入真实 LLM 前，需要先准确理解：

- Token 为什么不等于字数或单词数；
- 上下文窗口、模型最大输出和本次请求输出上限的区别；
- 消息角色为什么是 API 协议，而不是跨 Provider 不变的真理；
- temperature 和 top_p 为什么不能提供确定性保证；
- JSON mode、Structured Outputs 和 Tool Calling 的职责差异；
- 为什么 HTTP 成功或返回了文本，仍不一定代表任务完成。

本课是概念关卡，不修改 src/。第 10 课再把这些概念落实为可测试的 Adapter 契约，避免为了
“每课都写代码”而提前制造错误抽象。

## 1. Token 是模型的处理单位

Token 是 tokenizer 把输入切分后得到的 ID 序列单位，不等于一个英文单词、一个中文字或固定
数量的字符。同一文本在不同模型上可能得到不同 Token 数。

工程上要区分：

- **请求前预估**：用于截断、预留输出空间和预算；
- **服务端 usage**：响应中的 input、output、cached、reasoning 等实际计数，用于轨迹和计费。

预估值不是精确账单，也不能作为安全边界。后续系统要同时保留预估值和 Provider 报告值。

## 2. 上下文窗口是共享容量

一次请求的上下文通常包含：

    指令 + 历史消息 + 工具定义 + 工具调用/结果 + 当前输入 + 生成输出

推理 Token、缓存 Token 和多模态输入如何计入，必须以当前 Provider 文档和响应 usage 为准，
不能把单一供应商的规则写成普遍真理。

| 概念 | 含义 |
| --- | --- |
| Context window | 模型一次可以处理的总容量 |
| Model max output | 模型或 API 允许的最大生成量 |
| Requested output limit | 应用为本次请求主动设置的更小上限 |

即使窗口很大，也不应刚好填满。输出需要预留空间，工具定义会消耗上下文，长上下文还会增加
成本和延迟。

## 3. 消息角色是 API 协议

常见角色包括 system、developer、user、assistant，以及工具调用或工具结果。但其支持范围、
优先级和编码形状由具体 API 决定，同名角色在不同 Provider 中也可能有不同映射。

当前项目的 Message、Decision 和 Model 是教学简化：

- Role 只有 user、assistant 和 tool；
- content 只能是字符串，不能表示多模态 content part；
- 没有保留 assistant 发出的工具调用；
- 没有 call ID，不能把多个调用与结果一一关联；
- Decision 一次只能表示一个工具调用；
- 没有 finish reason、usage 和 Provider request ID。

这些是第 10～15 课要有意识演进的契约，不要求在本课提前修改。

## 4. 采样参数调整分布，不保证正确或可复现

模型逐步从候选分布中选择下一个 Token：

- **temperature** 通常越低越集中，越高越分散；
- **top_p** 只从累计概率质量达到阈值的候选集中采样。

实践中通常只调整其中一个。低 temperature 不等于数学上的完全可复现；模型版本、服务端实现
和 Provider 策略变化都可能改变结果。某些推理模型还会限制、忽略或重新解释采样参数。

因此确定性单元测试继续使用 ScriptedModel，不能用“真实模型 + temperature=0”代替测试替身。

## 5. 三种“结构化”机制

| 机制 | 它保证或表达什么 | 宿主仍必须做什么 |
| --- | --- | --- |
| JSON mode / JSON Output | 输出是可解析的 JSON | 验证业务 Schema、语义和完整性 |
| Structured Outputs | 输出按声明的 Schema 生成 | 处理拒绝、截断、Schema 子集和本地业务规则 |
| Function/Tool Calling | 模型提出一项应用可执行的调用请求 | 解析、校验、授权、执行，并关联返回结果 |

JSON 合法不代表符合预期 Schema；符合 Schema 不代表业务事实正确；Tool Calling 也不代表工具
已经执行。第 2～8 课建立的本地校验、权限、确认和生命周期不能因为 Provider 声明 strict 而删除。

## 6. 响应文本之外还有结束语义

应用还需要区分：

- 模型正常完成回答；
- 模型请求一个或多个工具调用；
- 输出因长度或上下文限制被截断；
- 模型因安全策略拒绝或停止；
- 传输层或 Provider 返回错误。

具体字段名会随 API 方言变化，但“结束原因属于控制流输入”是稳定原则。被长度限制截断的 JSON
即使看起来接近完整，也不能直接作为成功结果。

## 7. 时效性：模型能力是带日期的配置

截至 2026-10-24，DeepSeek 官方列出的模型 ID 是 deepseek-flash 和 deepseek-v4-pro，并为
两者列出 Thinking、JSON Output、Tool Calls 和 Responses API 支持。这只是当日快照，不是永久
事实；OpenAI 的推荐 API、模型 ID 和工具组合同样会变化。

课程遵守三条规则：

1. 核心契约不引用具体 SDK 类型；
2. 模型 ID、限制、价格和能力矩阵来自配置或官方信息，不散落在业务逻辑中；
3. 接入真实 API 前重新核对官方文档，并以手动冒烟测试验证当前账户的真实可用性。

## 8. 本课任务

本课不修改代码。请完成以下四项，并在下次审阅时用自己的话回答。

### 第一步：解释 Token 与容量

1. 说明 Token 为什么不等于字数或单词数；
2. 区分请求前预估和响应 usage；
3. 假设 context window 是 128K，应用为输出预留 8K，说明为什么输入预算仍应小于 120K，
   而不是刚好填满。

### 第二步：审计当前契约

阅读 src/agent_lab/contracts.py，列出 Message、Decision 和 Model 与真实 Provider 之间至少四个
已知简化。只记录问题，不要提前修改契约。

### 第三步：区分输出机制

为以下场景选择 JSON mode、Structured Outputs 或 Tool Calling，并解释理由：

1. 返回一份给 UI 渲染的固定字段研究摘要；
2. 请求宿主查询实时天气；
3. 只要求合法 JSON，字段由用户动态指定。

### 第四步：识别非成功结束

说明为什么以下情况不能直接构造 FinalAnswer：

- 因长度限制截断的文本；
- 包含工具调用请求的响应；
- HTTP 成功但输出内容为拒绝；
- 流式连接中断后收到的部分文本。

## 9. 完成标准

- 能解释 Token、context window、max output 和 usage；
- 不把 temperature=0 当成确定性测试保证；
- 能区分 JSON mode、Structured Outputs 和 Tool Calling；
- 能指出当前教学契约至少四个简化；
- 能说明 finish reason、usage 和 call ID 为什么属于控制流数据；
- 能区分稳定原则和带核验日期的 Provider 快照。

## 10. 思考题

1. 为什么 Token 预估误差对普通聊天可能只是体验问题，对自动化 Agent 却可能是可靠性问题？
2. 为什么工具 Schema 也要计入上下文预算？
3. 为什么 Structured Outputs 不能替代本地业务校验？
4. 为什么 Provider Adapter 不应只返回一个字符串？
5. 为什么测试不应写死当日价格或模型别名指向的底层版本？

## 11. 官方参考

- [OpenAI Key concepts: Tokens](https://developers.openai.com/api/docs/concepts)
- [OpenAI Responses API](https://developers.openai.com/api/reference/responses/overview)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI Function Calling](https://developers.openai.com/api/docs/guides/function-calling)
- [DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)
- [DeepSeek Responses API](https://api-docs.deepseek.com/api/create-response/)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
- [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)
