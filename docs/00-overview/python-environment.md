# Python 环境管理：使用 uv

> **文档类型**：工程环境约定  
> **导航**：[文档中心](../README.md) · [系统课程总纲](curriculum.md)

## 我们要管理的其实是四件事

Python 项目的“环境”不是一个概念，而是四层可复现性：

| 层次 | 本项目的文件/命令 | 解决的问题 |
| --- | --- | --- |
| Python 版本 | `.python-version` | 大家使用同一个 CPython 次版本 |
| 项目约束 | `pyproject.toml` | 声明运行依赖、开发依赖和支持的 Python 范围 |
| 精确解析 | `uv.lock` | 锁定所有直接与间接依赖的具体版本 |
| 隔离安装 | `.venv/` | 不污染系统 Python，不同项目互不影响 |

本项目使用 CPython 3.12。`.python-version` 请求 3.12 的最新补丁版本，而
`requires-python = ">=3.12,<3.13"` 明确项目只在这个次版本系列上运行。

## 第一次进入项目

```bash
uv sync
```

它会根据需要准备 Python、创建 `.venv`、检查或生成 `uv.lock`，然后同步依赖。
通常不需要先执行 `uv venv`，也不需要手动激活虚拟环境。

## 日常运行

优先使用 `uv run`：

```bash
uv run python --version
uv run pytest
uv run ruff check .
uv run ruff format .
```

`uv run` 会选择项目环境，并在运行前确认锁文件和环境与项目声明一致。因此无需依赖当前
Shell 是否已经执行过 `source .venv/bin/activate`。

如果编辑器需要解释器路径，选择：

```text
<项目目录>/.venv/bin/python
```

## 添加和删除依赖

运行时依赖：

```bash
uv add httpx
uv remove httpx
```

只在开发时使用的依赖：

```bash
uv add --dev pytest ruff
uv remove --dev pytest
```

不要同时使用 `uv add` 和 `pip install` 管理同一个项目。临时 `pip install` 得到的包没有进入
`pyproject.toml` 和 `uv.lock`，下次精确同步时可能被删除，也无法被其他开发者复现。

## `pyproject.toml` 与 `uv.lock` 的职责

`pyproject.toml` 表达我们的意图，例如“需要某个兼容范围内的 httpx”。`uv.lock` 记录解析
后的完整结果，例如具体版本和间接依赖。两者都应该提交版本控制：

- 修改依赖时使用 `uv add` / `uv remove`；
- 普通开发使用 `uv sync` / `uv run`；
- CI 使用 `uv sync --locked`，确保声明与锁文件不一致时立即失败；
- 主动升级依赖时使用 `uv lock --upgrade`，不要让升级悄悄发生。

`.venv/` 是本机生成物，不提交版本控制。环境损坏时可以重建，不应把它当作项目资产。

## 常用排查命令

```bash
uv run python --version   # 实际执行时使用的 Python
uv tree                   # 已解析的依赖树
uv lock --check           # 锁文件是否与 pyproject.toml 一致
uv sync --locked          # 严格按照已有锁文件同步
uv python list            # uv 能发现或安装的 Python
```

## 本项目约定

1. 不提交 `.venv/`、`.env` 或缓存文件。
2. 提交 `pyproject.toml`、`.python-version` 和 `uv.lock`。
3. 所有项目命令在文档中统一写成 `uv run ...`。
4. API Key 只通过环境变量或本地 `.env` 提供，绝不写入代码和版本控制。
5. 新增依赖时说明它解决了什么问题，避免 Agent 项目演变成不可解释的依赖集合。
