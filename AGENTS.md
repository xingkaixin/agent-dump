# AGENTS.md

只放所有任务都需要的约束和文档路由；实现细节以代码和按需文档为准。只在约束、职责边界或路由变化时修改本文件。

agent-dump 是本地只读的会话 CLI，同时服务终端用户和 AI Agent：每个能力都要有稳定的 JSON 输出、退出码和续读游标。

## 原则
- 未知显式呈现：未知计数与时间、发现或读取失败、部分结果必须标出，不当成 0、不匹配或空会话。
- 有界不截断：读取、导出、汇总超出预算时给续读游标或明确报告遗漏，不静默截断。

## 约束

### 数据安全
- Provider 会话源只读：导出、搜索、统计、collect 不得修改数据库、JSONL 或会话目录。
- 索引、配置、日志、导出只写入本项目拥有的路径或用户指定的输出目录。
- 测试只用 `tmp_path`、临时 SQLite 或显式注入路径，不读写真实用户目录。

### 兼容性
- CLI 参数、输出格式、退出码和默认路径是公开契约。改变需明确要求，并同步测试、README 和 skill recipes。
- 发布物只有 CLI，不提供 Python API 或 Rust 库。
- 历史兼容不是基准：Python v0.15.9 只用于性能对照，修复可以偏离它并用默认契约测试断言新行为，不改动对照版本；core `compat/` 已冻结，只为保留既有输出，新代码不使用、不扩展。

### 架构边界
- 依赖方向只允许 CLI → core。core 不依赖终端、参数解析或 LLM 客户端。
- `cli_args.rs` 声明参数，`command.rs` 归一化并分发；业务逻辑进入 `workflows/`、`collect/` 或 core。
- Provider 私有 schema 只在 core `providers/` 内解释。其他层只依赖 `providers/contract.rs` 的 `Provider` 契约和 Session facts；列表、head、统计和筛选投影同一份 facts。
- `terminal/` 只展示调用方传入的数据，不触发 Provider 发现或正文读取。

### 代码与测试
- 只在新增或变更可观察行为、修复回归、保护高风险边界时加测试。CLI 变更覆盖参数归一化、分发、输出或退出码。mock 只用于 Provider、终端和外部系统边界。
- CLI 契约测试放 `tests/cli/`，由 pytest 驱动真实二进制；core 逻辑用 inline `mod tests`。
- 新增文案同时写入 `resources/locales/en.json` 和 `zh.json`；缺 key 会在运行时 panic。
- 不随意新增第三方依赖；未被代码直接 import 的依赖在声明处写明原因。
- 函数体内默认不写注释，只解释 workaround、magic value 等无法从代码看出的原因。

## 文档

| 文档 | 何时读 | 何时同步 |
| --- | --- | --- |
| `docs/product.md` | 新增能力或改变方向前 | 目标、非目标、原则变化 |
| `CONTEXT.md` | 改 Session facts、计数、时间、路径或 Collect 归属前 | 术语或事实边界变化 |
| `docs/architecture.md` | 改模块职责、Provider、Query、Collect | 职责边界变化 |
| `docs/providers/` | 改特定 Provider | 该 Provider 读取规则变化 |
| `docs/development-guide.md` | 测试、lint、本地验证 | 工具链或门禁变化 |
| `docs/benchmarking.md` | 性能优化；需同机配对测量并校验输出与优化前一致 | 测量方法或场景变化 |
| `docs/release-guide.md` | 构建、打包、发版 | 发布流程变化 |
| `web/README.md` | 改落地页、部署、统计 | 落地页流程变化 |
| `README.md`、`README_zh.md`、`docs/cli-compatibility.md`、`skills/agent-dump/` | 改 CLI 可见行为 | CLI 可见行为变化 |

`CHANGELOG.md` 和 `docs/zh/CHANGELOG.md` 只在发版 PR 中更新。

## 验证
- 开发中先跑相关测试。pytest 直接使用 `target/release/agent-dump`，不会重新构建；改 Rust 后先 `cargo build --locked --release`，或用 `just test`。
- 未启用 mise shell 激活时，命令加 `mise exec --` 前缀。
- 提交 PR 前运行 `just isok`。
