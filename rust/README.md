# Rust CLI（P1 实验阶段）

此目录是 Rust 重写的第一条端到端路径。Python 仍是默认实现和发布来源；Rust 二进制尚不能替代完整的 `agent-dump`。迁移状态见[计划](../docs/rust-migration-plan.md)。

## 构建与验证

需要 rustup 和项目现有的 uv/just 环境，工具链固定为 Rust 1.90.0，依赖固定在 `Cargo.lock`。

```bash
just check-rust
just build-rust
./rust/target/release/agent-dump --help
```

`check-rust` 运行 fmt、Clippy、debug 构建与 `rust/tests/test_cli_parity.py`。差分套件通过子进程调用两种 CLI，只使用隔离的合成会话目录；比较完整 stdout/stderr、JSON 结构、源数据 hash。异常诊断文案暂未对齐，损坏行测试单独比较恢复后的 JSON 并检查警告。

## 已实现范围

```bash
./rust/target/release/agent-dump --list -d 36500 -q provider:codex
./rust/target/release/agent-dump codex://SESSION_ID --head
./rust/target/release/agent-dump codex://SESSION_ID --format print
./rust/target/release/agent-dump codex://SESSION_ID --format json --output ./exports
```

- Codex `CODEX_HOME/sessions`、默认 home 和 `data/codex` 回退；索引标题、第二条 user 消息标题、目录与文件名回退。
- 日期窗口、列表顺序与 metadata summary；当前要求显式 `-q provider:codex`，避免让部分 Provider 的结果看起来像全部结果。
- `codex://ID`、`codex://threads/ID`；head 的已知/未知消息数量和有界首尾读取。
- 普通 text/reasoning、assistant 分组与相邻 part 去重、显式 developer 过滤、token 汇总；print 与 JSON 的字段及内容对齐。
- 中英文成功输出，终端控制字符清理，JSON 文件名身份保留与原子私有写入；拒绝写入 Provider 根目录及覆盖符号链接。
- `-days`、`-query`、`-format`、`-output`、`-v` 等本阶段参数别名。

JSON 导出必须显式指定 `--output`。URI 默认 `print`，输出文件位于 `<output>/codex/`。文件名与 JSON 内容对齐，JSON 空白排版不作为契约。

## 尚未实现的行为

- Codex 工具调用/输出、patch、计划审批、skill/subagent 转换、注入上下文识别、多模态和未知 response item。
- 上述消息目前在完整读取阶段明确失败，不输出或保存截断的会话。head/list 仍可读取它们的轻量 metadata。普通正文中出现相关 XML 标签也会保守拒绝，后续由完整 decoder 消除这个临时限制。
- 其余 Provider、Markdown/raw、批量交互导出、通用 Query/Search、统计、索引、Collect、摘要、配置、shortcut、Ratatui。
- 配置文件尚不读取；因此不应用保存的语言、默认目录等配置。帮助、错误文案、错误组合的退出码与部分失败策略未完成全量对齐；未支持的参数会报错。
- 本地验证只代表 macOS arm64。CI 增加 Linux/macOS 差分任务；Windows 行为和全部发布平台在后续阶段验证。

这不是完整 Codex Provider 验收，也不是迁移矩阵的完成声明。下一步先补齐 Codex decoder，再扩展 Provider。

## 模块归属

`main.rs` 解析参数并装配工作流。`codex.rs` 负责发现与轻量 metadata，`codex_transcript.rs` 独占 Codex 正文 schema；共享 JSONL 字节读取在 `jsonl.rs`。`session.rs` 是稳定的会话/消息字段，`render.rs` 负责展示，`export.rs` 负责文件身份、权限与原子写入。只有一个 Provider 时不添加注册框架或 trait。

直接依赖各有明确用途：Clap 解析参数，Serde/serde_json 处理契约与源记录，Jiff 处理时间与本地时区名称，WalkDir 递归发现，SHA-256 保持特殊 ID 的文件身份，tempfile 保证导出原子替换和异常清理。不调用 Python 作为 Rust 的运行时依赖。

## 性能评估

使用原有 [CLI evaluator](../docs/benchmarks/README.md)，不为 Rust 改写 fixture 或验收摘要。本阶段只运行以下已实现子集：

```bash
just benchmark --command './rust/target/release/agent-dump' \
  --label rust-p1 --profile standard \
  --case startup-version --case list-jsonl \
  --case head-large-jsonl --case print-large-jsonl \
  --output dist/benchmarks/rust-p1.json
```

Python 用同样的 `--case` 组合重测；Rust 再传入该报告的 `--baseline` 做严格比较。原有 `export-large-json-md` 同时要求 Markdown，因此 P1 不将它列为通过；JSON 导出先由差分套件验证。不得把四个性能场景解释为应用整体加速比。
