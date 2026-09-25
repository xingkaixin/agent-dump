# P6 最终验收

P6 的实现、性能复测和四目标制品安装验收完成。当前分支的运行与构建实现已切换为 Rust，Python v0.15.9 作为冻结参考保留。审阅入口为 [Draft PR #396](https://github.com/xingkaixin/agent-dump/pull/396)，交付要求该 PR 的[最终提交检查](https://github.com/xingkaixin/agent-dump/pull/396/checks)全部通过。没有合并、打 tag 或发布。

## 交付范围

| P6 项目 | 结果与证据 |
| --- | --- |
| 完整 CLI 验收 | 全部差分套件改用 release 二进制；P2 和 P3～P5 契约保持，新增帮助、参数及路径兼容性验收 |
| 批量导出回退 | Apple 文件同步对齐 Python `fsync`；最终批量 JSON 导出 905.94 → 367.69 ms |
| 最终性能 | 原 17＋扩展 6 场景全部交错测量，结果等价、源数据不变，原始样本归档 |
| pip 分发 | Maturin `bin` wheel，仅 CLI；从 sdist 构建 wheel，安装不依赖 Rust 编译器 |
| npm 分发 | 四平台包沿用现有安装器、校验和及重试约束；原生文件直接从 wheel 提取，逐字节一致 |
| 安装矩阵 | macOS arm64/x64、Linux x64、Windows x64 的 pip、uv tool、uvx、npm、npx、bunx 验证通过 |
| 构建与文档 | Cargo 作为版本来源，共享制品 CI，移除 PyInstaller/Hatchling 构建；README、recipes、架构和发布指南同步 |

十个 Provider 与导出契约见 [P2 最终验收](rust-p2-completion.md)；查询、索引、Collect、配置、shortcut、诊断和 Ratatui 契约见 [P3～P5 最终验收](rust-p3-p5-completion.md)。这些是功能证据，性能基准不替代功能矩阵。

## 最终兼容性

- 无参数、`--help` 和 `-h` 均输出帮助并成功退出；中英文覆盖所有操作说明及兼容别名。重复标量参数保留最后一个值，长选项支持无歧义缩写。
- `--version` / `-v` 来自 `rust/Cargo.toml`。测试分别检查 Rust 当前版本与冻结 Python 的 0.15.9，不要求后续 Rust 发版时修改参考源码。
- 配置与项目查询共用 home 展开，补齐 `~用户名` 的 Unix/Windows 行为；测试只使用合成会话和路径字符串，不访问真实会话数据。
- Apple 原子写入使用与 Python 一致的 `fsync`，保留私有权限、错误传播、源目录保护和临时文件替换。其他平台保留原同步实现。

明确保留的差异：Clap 的帮助排版和参数解析错误措辞不逐字复刻 argparse；Ratatui 画面布局不逐帧复刻 questionary；JSON 文件空白排版不作为契约，字段和值、Markdown/raw 内容仍做校验。Rust 拒绝向 Provider 来源写入索引、导出、报告或日志，遵守数据源只读边界。SQLite `-shm` 协调文件与数据库/WAL 持久数据分别判断。

PyPI 只提供 CLI 是本次已选定的产品变化：新 wheel 不含 Python import API 或 `python -m agent_dump`。旧 API 使用方可固定 `agent-dump==0.15.9`。这项变化在提交和 PR 中标记为 breaking change。

## 验证记录

本机完整 `just isok` 通过：Python 2,603 passed / 1 skipped，Rust 44 个单元测试、1,547 个 release CLI 差分/边界用例，npm 74 个测试、Web E2E 13 个测试；锁文件、Ruff、pyright、ty、fmt 和 Clippy 均通过。随后增加 1 个安装器工作目录回归测试及 2 个版本来源用例，相关 56 项测试再次通过。当前套件分别为 Python 2,604 个通过项、Rust CLI 1,549 项；最终 PR CI 对新增用例再次完整检查。

制品实现提交 `a4fee7b` 的[CI 记录](https://github.com/xingkaixin/agent-dump/actions/runs/36078392209)包含四目标安装门禁；最终提交状态以 PR 检查为准。所有平台执行 Rust 单元测试和完整 CLI 契约，按条件跳过的平台边界与 P3～P5 相同：Linux 6 项 ZCode 默认路径限制，Windows 16 项 POSIX PTY、权限、符号链接、时区及文件名限制。macOS/Linux 执行真实 PTY，Windows 执行可移植 TestBackend 绘制测试。

| 制品目标 | runner | wheel 平台标签 | 安装与运行 |
| --- | --- | --- | --- |
| macOS arm64 | macos-14 | macosx_11_0_arm64 | 通过 |
| macOS x64 | macos-15-intel | macosx_10_12_x86_64 | 通过 |
| Linux x64 | ubuntu-latest | manylinux_2_17_x86_64 / manylinux2014_x86_64 | 通过，另在 glibc 2.17 容器执行 |
| Windows x64 | windows-latest | win_amd64 | 通过 |

每个目标在 Python 3.10 和 3.14 上安装 wheel，分别运行 pip 入口、`uv tool install` 和 `uv tool run`（uvx）；另运行 npm 安装入口、`npm exec`（npx）和 `bun x`。验证版本、帮助、合成 Codex 正文、JSON 导出和源文件未改写。安装环境独立，wheel 不含 Python 模块和运行依赖，npm 文件与 wheel 文件校验一致。

Linux 使用 Zig 构建并执行 auditwheel 检查，运行验证使用固定 digest 的 manylinux2014 镜像。glibc 2.17 是明确的兼容基线；Alpine/musl 不在预构建目标中。macOS/Windows 在当前 GitHub runner 验证，没有声称实机遍历每个历史 OS 版本。

四目标 CI 产物还在本地组合执行 `verify_release_set.py`，完整集通过，故意替换一个 npm 文件后被拒绝。发布 workflow 在第一个 registry 上传前执行相同检查，避免重试恢复旧二进制后与 wheel 不一致。

## 性能与体积

完整方法、原始样本和制品 SHA-256 见 [P6 性能报告](benchmarks/rust-p6.md)。在同机合成数据中：

| 工作负载 | Python → Rust | 加速比 |
| --- | --- | ---: |
| version 启动 | 141.53 → 5.09 ms | 27.79× |
| 跨 Provider 列表 | 260.06 → 56.83 ms | 4.58× |
| 批量 JSON 导出 | 905.94 → 367.69 ms | 2.46× |
| 冷索引搜索 | 3,283.86 → 1,271.93 ms | 2.58× |
| Collect dry-run | 1,890.63 → 313.19 ms | 6.04× |
| Collect 模拟每请求 20 ms | 514.95 → 289.20 ms | 1.78× |

23 个场景均更快，不合并成整个应用的统一倍数。原 17 场景峰值 RSS 中位数下降 48.5%～91.2%。四平台原生文件较已发布 PyInstaller 文件缩小 29.6%～37.3%；wheel 包含完整 CLI 后压缩包更大。没有测量真实模型质量/延迟、终端交互延迟或下载/安装耗时。

## 发布边界

当前 Cargo/npm 仍为 0.15.9，用于迁移验证；release workflow 明确拒绝以该已发布 Python 版本号发布 Rust 制品。下一步由用户审阅 PR 并确定新版本。届时按[发布指南](release-guide.md)更新 Cargo/Cargo.lock 与 npm 版本、CHANGELOG 和网站更新记录，再执行合并和受控发布。

Python 生产源码与原 benchmark 文件保持冻结，未删除其行为依据。P6 不自动推进 merge、tag、PyPI/npm 上传或网站部署。
