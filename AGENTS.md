# AGENTS.md

只放所有任务都需要的约束和文档路由；实现细节以代码和按需文档为准。只在约束、职责边界或路由变化时修改本文件。

## 约束

### 数据安全
- Provider 会话源只读：导出、搜索、统计、collect 不得修改数据库、JSONL 或会话目录。
- 索引、配置、日志、导出只写入本项目拥有的路径或用户指定的输出目录。
- 测试只用 `tmp_path`、临时 SQLite 或显式注入路径，不读写真实用户目录。

### 兼容性
- CLI 参数、输出格式、退出码和默认路径是公开契约。改变需明确要求，并同步测试、README 和 skill recipes。
- 发布物只有 CLI，不提供 Python API 或 Rust 库。
- Python v0.15.9 只是历史对照，不是行为基准。修复可以偏离它，并用默认契约测试断言新行为；不改动对照版本。

### 架构边界
- 依赖方向只允许 CLI → core。core 不依赖终端、参数解析或 LLM 客户端。
- `cli_args.rs` 声明参数，`command.rs` 归一化并分发；业务逻辑进入 `workflows/`、`collect/` 或 core。
- Provider 私有 schema 只在 core `providers/` 内解释。其他层只依赖 `providers/contract.rs` 的 `Provider` 契约和 Session facts。
- `terminal/` 只展示调用方传入的数据，不触发 Provider 发现或正文读取。

### 代码与测试
- 只在新增或变更可观察行为、修复回归、保护高风险边界时加测试。CLI 变更覆盖参数归一化、分发、输出或退出码。mock 只用于 Provider、终端和外部系统边界。
- 不随意新增第三方依赖；未被代码直接 import 的依赖在声明处写明原因。
- 正文默认不写注释，只解释 workaround、magic value 等无法从代码看出的原因。

## 文档

| 文档 | 何时读 | 何时同步 |
| --- | --- | --- |
| `docs/product.md` | 新增能力或改变方向前 | 目标、非目标、原则变化 |
| `CONTEXT.md` | 涉及术语、Session facts | 术语或事实边界变化 |
| `docs/architecture.md` | 改模块职责、Provider、Query、Collect | 职责边界变化 |
| `docs/providers/` | 改特定 Provider | 该 Provider 读取规则变化 |
| `docs/development-guide.md` | 测试、lint、本地验证 | 工具链或门禁变化 |
| `docs/release-guide.md` | 构建、打包、发版 | 发布流程变化 |
| `web/README.md` | 改落地页、部署、统计 | 落地页流程变化 |
| `README.md`、`README_zh.md`、`skills/agent-dump/` | 改 CLI 可见行为 | CLI 可见行为变化 |

## 验证
- 提交 PR 前运行 `just isok`。
