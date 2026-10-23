# 第 6 课：可重试错误、退避、超时与取消

> **阶段**：2 · 可靠工具系统  
> **状态**：进行中  
> **前置**：第 5 课的结构化工具结果  
> **导航**：[文档中心](../README.md) · [上一课](05-tool-results.md) · [课程总纲](../00-overview/curriculum.md)

## 本课要解决的问题

第 5 课让工具可以报告 `EXECUTION_ERROR`，但 Agent 只能立刻把错误交给模型。对于短暂网络中断、
限流或服务抖动，让模型重新生成完全相同的调用既浪费 Token，也没有改变工具参数。

自动重试可以吸收短暂故障，却也会带来新的风险：无限循环、请求风暴、任务无法取消，以及一次
调用占满全部时间。因此重试必须同时具备明确的资格、退避、次数上限、截止时间和取消检查。

## 1. 两种重试不要混淆

```text
模型修正重试：重新调用 model.decide，参数可能改变，消耗一个 max_steps
工具自动重试：不调用模型，重复同一 ToolCall，消耗一个 max_attempts
```

`INVALID_ARGUMENTS` 应交给模型修改参数。只有工具明确返回 `retryable=True` 的失败，宿主才可以
自动尝试同一个调用。

## 2. 错误类别与可重试性

`ToolError` 现在增加：

```python
retryable: bool = False
```

工具必须显式选择加入重试：

```python
ToolResult.failure(
    ToolErrorKind.EXECUTION_ERROR,
    "temporary outage",
    retryable=True,
)
```

默认值是 `False`，因为误重试通常比漏重试更危险。尤其是发送消息、扣款、创建订单等有副作用
的操作，在第 7 课引入幂等键之前不能仅凭“临时错误”自动重试。

## 3. 有界指数退避

课程已经提供 `RetryPolicy`：

```python
RetryPolicy(
    max_attempts=3,
    initial_delay=0.1,
    backoff_multiplier=2.0,
    max_delay=5.0,
)
```

`max_attempts` 包含第一次调用，所以值为 3 时最多只发生两次等待。第 n 次失败后的等待为：

```text
min(initial_delay * backoff_multiplier ** (n - 1), max_delay)
```

退避能降低故障服务的压力；上限防止等待无限增长。生产系统通常还会加入随机抖动（jitter），
避免大量客户端在同一时刻再次请求，本课先保持确定性以便测试。

## 4. 三种彼此独立的边界

| 边界 | 限制对象 | 用尽后的行为 |
| --- | --- | --- |
| `max_steps` | 模型决策次数 | `StepLimitExceeded` |
| `max_attempts` | 同一个工具调用的尝试次数 | 把最后一次失败交给模型 |
| `timeout` | 整次 `Agent.run()` 的墙钟时间 | `AgentTimeoutError` |

取消由调用者通过 `CancellationToken.cancel()` 主动触发，Agent 在模型调用、工具尝试和退避的
边界检查，并抛出 `AgentCancelledError`。

超时和取消是宿主的控制信号，不是工具业务失败，不能包装成 `ToolResult` 后让模型决定是否
忽略。否则模型就能绕过用户取消或系统预算。

## 5. 同步执行的真实限制

当前项目仍是单线程同步调用。Agent 可以在调用前后检查截止时间，但无法安全地中断一个正在
执行的任意 Python 函数：线程超时返回并不等于后台代码已经停止。

因此本课实现的是边界检查和协作式取消：

- 已取消或已超时则不启动下一项工作；
- 工具返回后再次检查，过期结果不继续传播；
- 退避前检查剩余时间，等待会越过截止时间时直接超时；
- 正在阻塞的模型或工具要等它返回后才能观察取消。

真正的强制终止需要工具自身支持超时，或把执行放入可终止的进程/沙箱。这会在后续 Provider、
Rust Runtime 和工作流阶段继续完善。

## 6. 你的实现任务

契约、`ScriptedTool` 和确定性测试已经准备好。只修改 `src/agent_lab/agent.py`。

### 第一步：注入策略、时钟和等待函数

扩展 `Agent.__init__()`：

```python
retry_policy: RetryPolicy | None = None
clock: Callable[[], float] = time.monotonic
sleep: Callable[[float], None] = time.sleep
```

`None` 时创建默认 `RetryPolicy()`。注入时钟和等待函数不是为了生产配置，而是让测试无需真实
等待就能确定性验证退避与超时。

### 第二步：为 run 增加控制参数

```python
def run(
    self,
    question: str,
    *,
    timeout: float | None = None,
    cancellation_token: CancellationToken | None = None,
) -> RunResult:
```

拒绝负数 `timeout`。运行开始时使用单调时钟计算一次 deadline；不要使用系统日期时间，因为
系统时钟可能被校准或回拨。

提取一个私有检查方法，在以下边界调用：

- 每次调用模型之前和之后；
- 每次调用工具之前和之后；
- 每次退避之前和之后。

取消优先于超时检查，这样用户主动取消时得到稳定的取消原因。

### 第三步：实现工具自动重试

为一次已经通过 Schema 校验的调用实现循环：

1. 调用工具并得到 `ToolResult`；
2. 成功或 `retryable=False` 时立即返回；
3. 已达到 `max_attempts` 时返回最后一次失败；
4. 根据失败次数计算下一次 delay；
5. 如果等待会达到或越过 deadline，抛出 `AgentTimeoutError`；
6. 等待后再次检查取消和超时，再开始下一次尝试。

参数校验失败没有进入工具，因此不走自动重试。

### 第四步：不要改变模型 step 语义

自动工具重试发生在一次 `ToolCall` 决策内部，不增加 `RunResult.steps`。模型只有在收到最终工具
观察后才作出下一次决策。这样 `max_steps` 和 `max_attempts` 各自限制不同循环。

## 7. 验证

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

完成标准：

- 可重试失败经过退避后可以成功；
- 非可重试失败不自动重试；
- 达到最大尝试次数后把最后一次失败交给模型；
- 退避按指数增长并受到上限约束；
- 等待会越过 deadline 时不再等待或重试；
- 预先取消时模型和工具均不执行；
- 退避期间发生取消时不启动下一次工具调用；
- 原有测试全部通过，且测试不进行真实等待。

## 8. 思考题

1. 为什么 `max_attempts=3` 只应该等待两次？
2. 为什么参数错误不应该由宿主使用相同参数自动重试？
3. 为什么线程 Future 报告超时不代表工具已经停止？
4. 为什么带副作用的工具即使遇到临时错误，也不能直接自动重试？
