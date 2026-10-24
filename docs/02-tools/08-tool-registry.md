# 第 8 课：Tool Registry、命名空间与生命周期

> **阶段**：2 · 可靠工具系统
> **状态**：进行中
> **前置**：第 7 课的副作用、幂等键、确认与权限
> **导航**：[文档中心](../README.md) · [上一课](07-side-effects-and-permissions.md) · [课程总纲](../00-overview/curriculum.md)

## 本课要解决的问题

目前 `Agent` 在构造函数里临时创建一个字典：

```python
self._tools[tool.name] = (tool, validator)
```

这在只有一个计算器时足够，但工具来源增加后会出现三个问题：

1. 两个工具重名时，后注册者会静默覆盖前一个；
2. 本地工具、MCP Server 和后续 Skill 可能都提供 `search`，缺少稳定的公开名称；
3. 数据库连接、MCP 会话等资源何时启动和关闭没有统一所有者。

本课把这些职责从 Agent 控制循环中提取到 `ToolRegistry`：

```text
Tool / ToolRegistration
          ↓ register：名称 + Schema + 冲突检查
     ToolRegistry (OPEN)
          ↓ start：冻结集合 + 启动资源
     ToolRegistry (STARTED)
          ↓ definitions / resolve
        Agent Loop
          ↓ close：逆序释放
     ToolRegistry (CLOSED)
```

## 1. Registry 不是一个普通字典

普通字典只能完成查找，Registry 还要维护以下不变量：

- 模型看到的名称与执行时解析的名称完全相同；
- 重复名称在启动前显式失败，不能依赖覆盖顺序；
- 每个 Schema 只在注册时检查一次；
- Agent 运行期间工具集合保持不变；
- 已启动的外部资源最终按相反顺序关闭。

如果模型拿到一份工具列表后 Registry 仍可随意变化，模型所依据的能力快照和宿主真正可执行的
能力就可能不一致。因此 `start()` 不只是“调用初始化函数”，还会冻结注册集合。

## 2. 本地名称与公开名称

工具只拥有本地名称，例如 `search`。部署它的宿主决定命名空间：

```python
ToolRegistration(search_tool, namespace="web")
```

Registry 生成公开名称：

```text
namespace.local_name
web.search
```

命名空间属于注册配置，而不是工具业务参数，也不由模型选择。同一个本地名称可以存在于不同
命名空间：

```text
web.search
docs.search
```

但相同的完整公开名称必须抛出 `DuplicateToolError`。本课规定本地名称和命名空间都必须匹配：

```text
[A-Za-z][A-Za-z0-9_-]*
```

点号保留给 Registry 组合名称。后续 Provider Adapter 如果需要不同编码，再在适配边界转换，
不能让供应商限制渗透到工具实现里。

## 3. 为什么不能静默覆盖

假设两个插件都注册 `send_email`。静默覆盖会让下列内容取决于加载顺序：

- 模型实际调用哪个实现；
- 哪个权限声明生效；
- 哪份 JSON Schema 用于参数校验；
- 哪个外部账户收到副作用。

这不是便利的扩展规则，而是权限和供应链风险。默认策略应当是启动失败，让宿主通过命名空间
或显式配置解决冲突。

## 4. 生命周期与所有权

大多数纯 Python 工具无需初始化，因此继续只实现 `Tool` 即可。持有外部资源的工具可以额外
实现 `ManagedTool`：

```python
class ManagedTool(Protocol):
    def start(self) -> None: ...
    def close(self) -> None: ...
```

`ToolRegistry` 使用运行时协议判断是否需要管理它。生命周期顺序采用常见的栈规则：

```text
start: database → browser → mcp
close: mcp → browser → database
```

如果 `browser.start()` 失败，已经成功启动的 `database` 必须关闭，尚未启动的 `mcp` 不能收到
`close()`。失败后的 Registry 进入 `CLOSED`，不能带着不确定的半初始化状态重试。

`close()` 必须幂等，因为正常退出、异常处理和上层清理可能重复调用它。

## 5. Agent 与 Registry 的职责边界

完成后职责如下：

| 组件 | 拥有的职责 |
| --- | --- |
| `ToolRegistry` | 命名、冲突、Schema、稳定快照、启动与关闭 |
| `Agent` | 模型循环、参数校验、权限、确认、重试、超时与取消 |
| `Tool` | 业务动作及其局部资源实现 |

Agent 构造时创建并启动 Registry，因此 Agent 拥有传入工具的生命周期。对资源型工具使用上下文
管理器：

```python
with Agent(model, tools) as agent:
    result = agent.run("搜索资料")
```

`Agent.close()` 和 `with` 只负责资源生命周期，不应改变某次 `run()` 的错误处理规则。

## 6. 你的实现任务

本课已经准备好以下脚手架：

- `src/agent_lab/registry.py`：公开类型、异常和待实现的 Registry 方法；
- `ManagedTool`：可选的运行时生命周期协议；
- `ToolRegistration`：把 namespace 与工具实现分离；
- `tests/test_tool_registry.py`：名称、冲突、状态和生命周期测试。

只修改 `src/agent_lab/registry.py` 和 `src/agent_lab/agent.py`。

### 第一步：实现注册

`register()` 只能在 `OPEN` 状态调用，并按以下顺序建立条目：

1. 校验本地名称和可选 namespace；
2. 组合公开名称；
3. 拒绝重复公开名称；
4. 使用 `Draft202012Validator.check_schema()` 检查 Schema，并把 `SchemaError` 转换成包含公开名称的
   `InvalidToolSchemaError`；
5. 保存 `RegisteredTool`，返回公开名称。

不要先写入字典再检查重复，也不要继续在 Agent 中维护第二份工具字典。

### 第二步：实现启动和失败回滚

`start()` 只能从 `OPEN` 进入。按注册顺序遍历工具：

- 普通 `Tool` 不需要启动；
- `isinstance(tool, ManagedTool)` 为真时调用 `start()`；
- 只有启动成功后才加入 `_started_tools`；
- 任意启动失败时，逆序关闭此前成功启动的工具，将状态设为 `CLOSED`，然后重新抛出原异常；
- 全部成功后将状态设为 `STARTED`。

### 第三步：实现稳定查询与关闭

`resolve()` 和 `definitions()` 只允许在 `STARTED` 状态调用；在 `OPEN` 或
`CLOSED` 状态调用时抛出 `ToolRegistryStateError`。

- `resolve(public_name)` 用完整的公开名称精确查找；找到时返回对应的
  `RegisteredTool`，未找到时返回 `None`；
- `definitions()` 返回 `tuple[ToolDefinition, ...]`，每个定义的 `name` 使用
  `public_name`，顺序必须与注册顺序相同；
- 查询方法只读，不应修改 Registry 状态或条目顺序。

`close()` 的规则是：

- 从 `STARTED` 关闭时逆序处理 `_started_tools`；
- 从 `OPEN` 关闭时不启动任何工具，直接进入 `CLOSED`；
- 已经 `CLOSED` 时直接返回；
- 关闭完成后清空 `_started_tools` 并把状态设为 `CLOSED`；
- 无论从正常路径还是异常路径退出，都不能重复关闭同一工具。本课不要额外设计
  多个 `close()` 异常的聚合策略，这一点留给思考题。

### 第四步：让 Agent 只依赖 Registry

重构 `Agent`：

1. 将 `Agent.__init__()` 的 `tools` 参数类型改为 `Iterable[ToolSource]`，以便同时接受
   普通 `Tool` 和带 namespace 的 `ToolRegistration`；
2. 构造 `ToolRegistry(tools)` 并立即调用 `start()`。移除 Agent 内部自己维护的
   `name -> (tool, validator)` 字典，避免存在两份工具清单；
3. 每次请求模型时，把 `registry.definitions()` 作为工具定义传入；
4. 模型返回 `ToolCall` 后，使用 `registry.resolve(tool_call.name)` 查找条目。返回
   `None` 时保持现有行为，抛出 `UnknownToolError`；
5. 找到条目后，用 `registered.validator` 校验参数，用 `registered.tool` 完成
   权限、确认、重试、超时与实际执行；
6. 凡是对模型或用户可见的工具名称都使用 `registered.public_name`，包括 tool 历史
   消息和 `ToolConfirmationRequest.tool_name`，不要退回底层 `tool.name`；
7. `Agent.close()` 委托给 `registry.close()`；`__enter__()` 返回 `self`；
   `__exit__()` 调用 `close()` 且不吞掉 `with` 代码块中的异常。

原有权限、确认、幂等键和重试行为必须保持不变。

## 7. 验证

开始时运行：

```bash
uv run pytest
```

新增测试会按设计失败。完成后运行完整验收：

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

完成标准：

- 重复公开名称不会静默覆盖；
- 相同本地名称可以用不同 namespace 共存；
- 无效名称和 namespace 被拒绝；
- Registry 启动后不能继续注册；
- 模型定义、调用解析和历史消息使用同一个公开名称；
- ManagedTool 按注册顺序启动、逆序且只关闭一次；
- 启动失败会回滚此前已启动的资源；
- 第 1～7 课的全部测试继续通过。

## 8. 思考题

1. 为什么 namespace 应由宿主注册时指定，而不是由 Tool 或模型自行决定？
2. 为什么重复名称应该 fail closed，而不是提供“最后注册者获胜”的规则？
3. 为什么关闭顺序通常与启动顺序相反？
4. 为什么 Registry 启动后要冻结，而不能允许 Agent 运行期间动态增删工具？
5. 如果某个工具的 `close()` 抛出异常，Registry 应如何尽量关闭其余工具并报告多个错误？
