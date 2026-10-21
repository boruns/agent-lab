# Desktop UI 技术路线

> **文档类型**：架构决策  
> **状态**：已选定方向，暂不开始实现  
> **导航**：[文档中心](../README.md) · [系统课程总纲](curriculum.md)

## 1. 结论

Agent Lab 的 Desktop UI 默认采用：

```text
Tauri v2 + Rust
Vue 3 + TypeScript + Vite
Element Plus
```

Wails + Go 保留为备选方案，不作为当前默认实现。

这不是现在就增加桌面工程。我们会先让 Agent 后端拥有稳定的运行状态、流式事件、取消、审批、
持久化和权限协议，再实现 Desktop 控制面。否则 UI 很容易直接依赖尚未稳定的 Python 内部对象，
后续每改一次 Agent 核心都要重写界面。

## 2. Desktop UI 在 Agent 中有什么作用

普通聊天框只能显示文字，但真正的 Agent 还需要让用户看见和控制：

- 当前目标、计划和执行进度；
- 模型正在生成的内容；
- 调用了哪个工具、参数是什么、结果是否成功；
- 哪个高风险动作正在等待人工审批；
- Token、金额、时间和工具调用预算；
- 任务的暂停、取消、恢复和失败重试；
- Skills、MCP Server、模型 Provider 和权限配置；
- 可供排障和评测使用的完整运行轨迹。

因此 Desktop UI 不是 Agent 的“大脑”，而是观察和控制 Agent 的**控制面**。

## 3. 推荐架构

```text
┌─────────────────────────────────────────────┐
│ Vue 3 + TypeScript + Element Plus           │
│ 页面、组件、表单、时间线、审批交互           │
└───────────────────┬─────────────────────────┘
                    │ typed commands / channels
┌───────────────────▼─────────────────────────┐
│ Tauri v2 / Rust Desktop Shell               │
│ 窗口、系统能力、权限、密钥入口、进程生命周期 │
└───────────────────┬─────────────────────────┘
                    │ 稳定的本地 API / IPC
┌───────────────────▼─────────────────────────┐
│ Agent Backend                               │
│ Python Agent Core / Go Orchestrator          │
│ Rust Tool Runtime                           │
└─────────────────────────────────────────────┘
```

边界规则：

1. Vue 只维护展示状态，不拥有任务的权威状态；
2. 页面不能直接执行 Shell、读任意文件或接触 Provider API Key；
3. Tauri Command 必须是窄而明确的应用命令，例如 `start_run`、`cancel_run`、
   `approve_tool_call`，不能暴露“执行任意命令”接口；
4. 高频且要求顺序的 Token/轨迹输出使用 Channel；低频生命周期通知才使用 Event；
5. 刷新或关闭窗口不能破坏正在执行的任务，任务状态由后端持久化；
6. 所有跨边界数据使用显式版本的结构化契约，不直接序列化内部类。

## 4. 为什么默认选择 Tauri

| 维度 | Tauri v2 + Rust | Wails + Go | 本项目判断 |
| --- | --- | --- | --- |
| 与 Vue/TypeScript 集成 | 支持 Vite 和 Vue 模板 | 支持前端框架和 TS 绑定 | 都满足 |
| 前后端通信 | Command、Event、Channel | Go 方法绑定、类型化 Event | 都满足 |
| 流式事件 | Channel 有序且适合高吞吐 | 类型化 Event 易用 | Tauri 更贴合 Token/轨迹流 |
| 权限边界 | Capability/Permission 可按窗口约束 | 主要依赖应用自身设计 | Tauri 更适合最小授权教学 |
| 后期代码复用 | 可连接 Rust Tool Runtime | 可连接 Go Orchestrator | 两者都有复用点 |
| 当前稳定性 | v2 稳定路线 | v3 截至 2026-10-19 仍为 beta | 默认选择 Tauri |

Wails 不是“不好”。如果以后满足下面条件，可以重新做架构决策：

- Wails v3 已稳定；
- Desktop 只是 Go Orchestrator 的轻量外壳；
- 项目不需要复用 Rust 权限和安全执行组件；
- Go 的开发效率对当时的项目比更细粒度的桌面权限模型更重要。

## 5. Vue 层约定

- 使用 Vue 3 Composition API 和 TypeScript；
- 使用 Vite 构建 SPA，不引入 SSR；
- Element Plus 使用按需自动导入，控制安装包和首屏体积；
- Pinia 只保存筛选条件、临时表单和后端状态的 UI 投影；
- 运行记录、审批状态和任务生命周期以后端为事实来源；
- 前后端事件使用可辨识联合类型，例如 `run.started`、`model.delta`、
  `tool.awaiting_approval`、`run.finished`。

## 6. 为什么安排在后期

Desktop 页面依赖的不是“能调用一次模型”，而是下面这些已经稳定的能力：

```text
运行轨迹 + 流式响应 + 取消
        ↓
人工审批 + 权限 + Skills/MCP 配置
        ↓
会话持久化 + 后台任务 + 故障恢复
        ↓
Desktop 控制面
```

在进入 Desktop 阶段前，我们会先设计一版 UI API 契约。这样开发界面时是在消费已经理解过的
Agent 能力，而不是一边猜后端行为一边堆组件。

## 7. 计划实现的页面

1. **运行工作台**：提交目标、查看流式回答和取消任务；
2. **轨迹时间线**：查看模型决策、工具参数、观察结果和结束原因；
3. **审批中心**：批准、拒绝或修改高风险工具调用；
4. **任务中心**：查看运行中、暂停、失败和已完成任务；
5. **能力中心**：管理 Tools、Skills 和 MCP Servers；
6. **设置中心**：配置 DeepSeek/OpenAI、预算和权限，不向 Vue 暴露明文密钥；
7. **诊断页面**：查看脱敏日志、Tracing、用量并导出问题报告。

## 8. 官方资料

- [Tauri：Frontend Configuration](https://v2.tauri.app/start/frontend/)
- [Tauri：Calling Rust from the Frontend](https://v2.tauri.app/develop/calling-rust/)
- [Tauri：Calling the Frontend from Rust](https://v2.tauri.app/develop/calling-frontend/)
- [Tauri：Capabilities](https://v2.tauri.app/security/capabilities/)
- [Tauri：Updater](https://v2.tauri.app/plugin/updater/)
- [Wails v3 Changelog](https://v3.wails.io/changelog/)
- [Wails：Method Bindings](https://v3.wails.io/features/bindings/methods/)
- [Vue：TypeScript Overview](https://vuejs.org/guide/typescript/overview)
- [Element Plus：Installation](https://element-plus.org/en-US/guide/installation.html)

