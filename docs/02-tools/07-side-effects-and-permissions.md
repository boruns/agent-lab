# 第 7 课：副作用、幂等键、确认与权限分级

> **阶段**：2 · 可靠工具系统  
> **状态**：进行中  
> **前置**：第 6 课的重试、超时和取消  
> **导航**：[文档中心](../README.md) · [上一课](06-retries-timeouts-cancellation.md) · [课程总纲](../00-overview/curriculum.md)

## 本课要解决的问题

第 6 课能够自动重试短暂失败，但“可以重试”不等于“重复执行是安全的”。天气查询执行两次通常
没有影响；发送邮件、扣款或追加文件执行两次会产生真实副作用。

模型也不能因为知道某个工具名称就自动获得写权限。本课为工具执行增加三层独立控制：

```text
工具声明 READ / WRITE
          ↓
Agent 是否被静态授予该权限
          ↓
有效的 WRITE 调用是否得到逐次确认
```

写操作重试还必须携带同一个幂等键，让工具能够识别同一逻辑请求的重复尝试。

## 1. 能力描述不是权限

`description` 和 JSON Schema 告诉模型工具能做什么、参数长什么样，但它们不授予执行权限。
工具现在必须声明：

```python
permission = ToolPermission.READ  # 或 WRITE
supports_idempotency = False  # 是否承诺按幂等键去重
```

`READ` 表示不应改变外部状态，默认允许；`WRITE` 表示可能产生副作用，默认拒绝。分类必须由工具
开发者声明并由宿主执行，不能让模型在调用参数里自行选择。

## 2. 静态授权与逐次确认解决不同问题

- `allowed_permissions` 回答“这个 Agent 实例最多能做什么”；
- `confirmation_handler` 回答“这一次具体写操作是否允许”。

即使 Agent 获得了 `WRITE` 权限，每一次有效写调用仍要确认。没有确认处理器时 fail closed；明确
拒绝后立即终止，不把决定交还给模型反复请求。

本课使用同步回调模拟确认。后续 Human-in-the-Loop 阶段会把它升级为可暂停、持久化和恢复的
审批流程。

## 3. 为什么先校验参数，再请求确认

用户应该确认一项具体、有效的操作。若参数连 Schema 都不满足，工具不会执行，也没有必要弹出
确认。因此单次调用顺序是：

```text
查找工具 → 检查静态权限 → 校验参数 → 生成幂等键 → 请求确认 → 执行
```

静态权限放在参数校验之前，避免未授权调用者利用详细校验错误探测写工具接口。

## 4. 幂等键保护的是什么

幂等键标识一次逻辑写操作。第一次尝试和所有自动重试必须使用同一个键：

```text
attempt=1, idempotency_key=email-123
attempt=2, idempotency_key=email-123
```

支持幂等的工具应在真正产生副作用之前原子地记录该键，并对重复键返回第一次操作的结果。仅仅
生成字符串并不能自动实现幂等；`supports_idempotency=True` 是工具对宿主作出的契约承诺。

不支持幂等的写工具即使返回 `retryable=True`，Agent 也只能把第一次失败交给模型，不能自动
重试。读工具仍沿用第 6 课的重试规则。

## 5. ToolExecutionContext

幂等键不是模型参数，也不应塞入工具的业务 Schema。项目新增宿主拥有的执行上下文：

```python
ToolExecutionContext(
    attempt=1,
    idempotency_key="email-123",
)
```

- `arguments` 是模型提出的业务输入；
- `context` 是宿主生成的控制元数据；
- `attempt` 从 1 开始，每次物理重试递增；
- 读工具的 `idempotency_key` 为 `None`。

这种分离避免模型伪造幂等键，也避免为了宿主控制字段放宽业务 Schema。

## 6. 你的实现任务

契约、具体工具、测试替身和失败测试已经准备好。只修改 `src/agent_lab/agent.py`。

### 第一步：扩展 Agent 配置

新增三个仅限关键字参数：

```python
allowed_permissions: Iterable[ToolPermission] = (ToolPermission.READ,)
confirmation_handler: Callable[[ToolConfirmationRequest], bool] | None = None
idempotency_key_factory: Callable[[], str] = lambda: uuid4().hex
```

初始化时把权限复制为 `frozenset`，不要保留调用者可变集合的引用。

### 第二步：执行静态权限门槛

找到工具后，先检查 `tool.permission` 是否在授权集合中。不在时抛出
`ToolPermissionDeniedError`，并确保校验、确认和工具执行都没有发生。

### 第三步：准备写调用

参数校验成功后：

1. 读工具使用 `idempotency_key=None`，不请求确认；
2. 写工具没有确认处理器时抛 `ToolConfirmationRequiredError`；
3. 为写调用生成一次非空幂等键；
4. 用参数副本构造 `ToolConfirmationRequest`；
5. 处理器返回 `False` 时抛 `ToolConfirmationRejectedError`；
6. 只有确认通过才进入工具执行。

确认只针对一次逻辑调用执行一次，不能在每次自动重试前重复询问。

### 第四步：把上下文传给每次尝试

扩展 `_run_tool_with_retries()`，每次调用工具时传入：

```python
context = ToolExecutionContext(
    attempt=attempt,
    idempotency_key=idempotency_key,
)
```

写工具返回可重试错误时，只有 `supports_idempotency=True` 才继续退避和重试。所有尝试复用同一
幂等键，但 `attempt` 递增。

## 7. 验证

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

完成标准：

- 读工具默认可执行，不确认、不生成幂等键；
- 写工具默认无权限；
- 获得写权限但没有确认处理器时仍然拒绝；
- 拒绝确认不会执行工具；
- 确认请求只包含参数副本和宿主生成的键；
- 支持幂等的写工具重试时复用同一键并递增 attempt；
- 不支持幂等的写工具绝不自动重试；
- 无效参数不会触发确认；
- 原有测试、Ruff 和格式检查全部通过。

## 8. 思考题

1. 为什么 `WRITE` 静态授权不能替代逐次确认？
2. 为什么幂等键不能由模型作为普通参数提供？
3. 为什么确认应该发生在参数校验之后、工具执行之前？
4. 工具声明 `supports_idempotency=True`，为什么仍不能证明它真的安全？
