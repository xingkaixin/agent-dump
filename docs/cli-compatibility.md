# CLI compatibility

[English README](../README.md) · [中文说明](#中文)

New commands should use the standard spellings below. Existing aliases remain accepted; this documentation change does not remove CLI behavior.

| Existing spelling | Standard spelling |
| --- | --- |
| `-days` | `--days` (`-d` also works) |
| `-query` | `--query` (`-q` also works) |
| `-format` | `--format` |
| `-output` | `--output` |
| `-summary` | `--summary` |
| `-config` | `--config` |
| `-since`, `-until` | `--since`, `--until` |
| `-v` | `--version` |
| `--capabilities` | `--providers` |
| `--format md` | `--format markdown` |
| `cwd:` in a structured query | `path:` |
| `--query 'codex,kimi:error'` | `--query 'error provider:codex,kimi'` |

`-page-size`, `--page-size`, and `-p` are accepted but ignored. They do not paginate lists or control `--read`. Use `--read --limit N --max-chars N` for bounded reading and continue with the returned cursor.

The short options `-i`, `-d`, `-q`, and `-h` remain supported. Running without arguments shows help; `--interactive` opens batch export and `--browse` opens the session reader.

## Source builds and Python API migration

Prebuilt wheels need no Rust compiler. Building from Git or an sdist requires Rust 1.90.0 and a C toolchain. Linux ARM64, Linux musl/Alpine, and Windows ARM64 have no prebuilt artifacts.

```bash
git clone https://github.com/xingkaixin/agent-dump.git
cd agent-dump
cargo build --locked --release
./target/release/agent-dump --help

# Install the local checkout, or build directly from Git
uv tool install . --force
uv tool install git+https://github.com/xingkaixin/agent-dump

# Run from Git without a persistent tool installation
uvx --from git+https://github.com/xingkaixin/agent-dump agent-dump --help
```

See the [development guide](development-guide.md) for validation and build details.

Version 0.15.9 is the last Python release. Since v1.0.0, wheels provide only the `agent-dump` command: Python imports and `python -m agent_dump` are not included. Existing API consumers can pin `agent-dump==0.15.9`, or migrate to subprocess calls with JSON output or JSON file exports. Current Rust features are not all available in 0.15.9; the frozen Python environment is used only for differential verification. Historical Python source remains in Git history.

## 中文

[返回 README](../README_zh.md)

新命令使用标准写法，旧参数继续兼容。本次文档整理不删除 CLI 行为。

| 旧写法 | 标准写法 |
| --- | --- |
| `-days` | `--days`（也支持 `-d`） |
| `-query` | `--query`（也支持 `-q`） |
| `-format` | `--format` |
| `-output` | `--output` |
| `-summary` | `--summary` |
| `-config` | `--config` |
| `-since`、`-until` | `--since`、`--until` |
| `-v` | `--version` |
| `--capabilities` | `--providers` |
| `--format md` | `--format markdown` |
| 结构化查询中的 `cwd:` | `path:` |
| `--query 'codex,kimi:error'` | `--query 'error provider:codex,kimi'` |

`-page-size`、`--page-size` 和 `-p` 会被接受，但不生效。它们既不让列表分页，也不控制 `--read`。有界读取使用 `--read --limit N --max-chars N`，并使用返回的游标继续。

短参数 `-i`、`-d`、`-q`、`-h` 继续支持。不带参数运行显示帮助；`--interactive` 进入批量导出，`--browse` 打开会话阅读器。

## 源码构建与 Python API 迁移

预构建 wheel 无需 Rust 编译器。从 Git 或 sdist 构建需要 Rust 1.90.0 和 C 工具链。Linux ARM64、Linux musl/Alpine、Windows ARM64 没有预构建产物。源码安装和临时运行命令见[上方示例](#source-builds-and-python-api-migration)，验证流程见[开发指南](development-guide.md)。

0.15.9 是最后一个 Python 版本。从 v1.0.0 起，wheel 仅提供 `agent-dump` 命令，不包含 Python 导入 API 或 `python -m agent_dump`。旧 API 使用方可固定 `agent-dump==0.15.9`，或迁移到子进程调用，用 JSON 输出或 JSON 文件导出交换结构化数据。当前 Rust 功能并非全部适用于 0.15.9；冻结的 Python 环境只用于差分验证，历史源码保留在 Git 历史中。
