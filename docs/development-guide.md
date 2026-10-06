# 开发与验证指南

仓库根是包含两个成员的 Cargo workspace，同时也是 CLI package。`Cargo.toml` 统一管理依赖、lint 和产品版本，`Cargo.lock` 与 `target/` 共享，工具链固定为 Rust 1.90.0。直接从根目录运行 Cargo。

本地开发工具统一在根目录的 `mise.toml` 声明，安装 mise 后运行：

```bash
mise install
mise exec -- uv sync --locked --dev
```

Node、Python、uv 和 just 的版本与 CI 对齐，pnpm 与 `web/package.json` 的 `packageManager` 保持一致；Bun 与安装验证一样使用最新版。Rust 保留 mr-boxington 配置，并与供 rustup 和源码构建使用的 `rust-toolchain.toml` 保持一致。更新这些版本时同步相应声明。已启用 mise shell 激活时可直接运行下文命令，否则使用 `mise exec --` 前缀，例如 `mise exec -- just isok`。

## 1. 目录与测试

- `src/`：CLI 参数、分发、`workflows/`、`collect/` 与 `terminal/`。
- `crates/agent-dump-core/src/`：Provider、Session、Query/Search、输出与存储；模块内保留 Rust 单元测试。
- `resources/locales/`、`resources/prompts/`：编译时嵌入的文案与提示词。
- `tests/cli/`：通过真实子进程执行的 CLI 契约、差分和终端测试。
- `tests/tooling/`：构建、发布、文档和 benchmark 的行为验证。
- `tests/reference/`：Python v0.15.9 的精确依赖及 hash 清单；不包含旧应用源码。
- `scripts/`、`packaging/`：性能评估和 pip wheel 工具。Python 不是产品运行依赖。

测试只使用临时 JSONL、SQLite 和显式注入的目录，禁止访问真实用户的 Provider 会话或导出路径。CLI 变更覆盖参数、分发、输出与退出码；只在行为变化、回归或高风险边界需要时增加测试。

CLI 文案位于 `resources/locales/`。测试按中英文参数运行；需要格式化期望文案时读取对应 JSON，不导入旧 Python 应用。

## 2. 验证命令

```bash
cargo build --locked --release
cargo test --locked --workspace

# 可选的历史差分验证：安装固定参考、核对 hash，再比较两套 CLI
just test-differential

# 完整本地门禁：Rust、CLI、工具、npm、网站
just isok
```

`just test` 先构建 release 二进制，再运行 Rust 单元测试和不依赖历史 Python 的 pytest 契约。`just check-rust` 只运行 Rust 与 CLI 验证。`AGENT_DUMP_TEST_BINARY` 可指定实际安装的制品；缺少二进制会失败，不回退到其他命令。

`pytest` 默认排除带 `differential` 标记的测试；CI 和 `just isok` 不安装或执行历史 Python 对照。需要比较时运行 `just test-differential`，或先 `just reference`，再用 `uv run pytest -q -m differential tests/cli` 选择差分测试。混合模块按测试函数标记，纯差分模块使用模块标记；新增差分测试必须显式标记。HTTP 凭据、响应边界和 Collect 合并测试直接断言 Rust 行为，仍进入默认验证。

Python 参考安装在忽略的 `.venv-reference/` 中，版本及完整依赖 hash 来自 `tests/reference/requirements.txt`。安装器核对包内全部 Python 文件的源码 hash，与 P6 冻结参考一致。对照只用于差分和配对性能测量，不进入主开发环境、Cargo 构建、wheel 或 npm。不要随依赖升级改变此历史参考。

`uv sync --locked --dev` 安装 pytest、Ruff、ty 等辅助工具；`pyproject.toml` 同时保留 pip/Maturin 所需元数据。pytest 配置只位于该文件，禁止额外配置覆盖。Python 应用的旧单元测试和覆盖率门禁已随源码退场，历史结果保留在 Git 历史中。

`just fmt` 格式化整个 Rust workspace 和 Python 验证工具，`just fmt-check` 只检查格式；`just lint-format` 保留为 `fmt` 的别名。`just lint` 执行 Rustfmt、Clippy 和 Ruff；`just check` 执行 Cargo check 与辅助 Python 的 ty。Ruff 配置位于 `ruff.toml`，单行最大长度 120。CI 在 Linux、macOS、Windows 各执行一组 Rust 单元测试、CLI 契约和工具验证。四目标安装 CI 另行检查 pip/uv tool/uvx 与 npm/npx/bunx。

### CI 构建缓存与耗时报告

Rust 依赖缓存按 OS、架构和构建用途隔离。CLI 验证沿用 parity 缓存键以复用现有缓存，由 main 写入；四目标打包使用独立 packaging 缓存，由 main 写入。PR 只恢复已有缓存，首次运行或工具链/依赖变化时仍可能冷编译。

CLI 验证输出最慢 30 项测试及 `dist/ci/contracts.xml`，CI 将报告上传为 `contracts-<os>` artifact，保留 14 天。JUnit 时间包含 setup、call 和 teardown。移除常规差分验证后不再分片，也不再维护历史分片耗时基线。

### Rust 格式与 lint

`rustfmt.toml` 使用 edition 2024、80 列、字段初始化和 `?` 简写，只启用 stable 选项。Rustfmt 无法重排的宏内文本与长字符串不强行拆分。

两个 crate 均显式继承 `[workspace.lints]`：`unsafe_code = deny`，Clippy `all`、`pedantic = deny`，`nursery = warn`。本地和 CI 使用 `cargo clippy --locked --workspace --all-targets -- -D warnings`，因此 nursery 警告也阻断门禁。

全局逐项允许以下规则，不关闭任何规则组：

- `module_name_repetitions`：允许领域类型沿用模块术语。
- `missing_errors_doc`、`missing_panics_doc`、`must_use_candidate`：内部 crate 不要求逐函数重复文档或候选属性。
- `too_many_lines`：80 列格式会增加物理行数，不为行数拆散完整 schema 解码或分发流程。
- `option_if_let_else`：保留清晰的显式分支，避免嵌套闭包。
- `similar_names`：允许 Provider 中 created/updated、input/output 等成对字段名称。

Python 数值兼容、统一 Provider 工厂、平台差异和并发锁等例外仅放在对应函数上，每处注明 `reason`。新例外需要具体原因；能够消除的多余复制、未检查转换和不必要所有权应直接修正。

## 3. 交互式 CLI

selector 只展示工作流传入的会话与计数，不发现来源或读取正文。Ratatui/Crossterm 处理终端；stdin 管道保留行输入。RAII 恢复终端模式；真实 PTY 验证位于 `tests/cli/test_tui.py`，Windows 用 TestBackend 验证绘制。

第三方文本经 core 的 `output/render.rs` 净化。UI 布局不逐帧复刻旧 questionary；选择、取消、导出和终端恢复属于契约。

## 4. 构建与性能

`cargo build --locked --release` 产物为 `target/release/agent-dump`（Windows 为 `.exe`）。资源通过 `include_str!` 嵌入，无需运行时查找仓库。CLI 依赖内部 core，core 不依赖 Clap、Ratatui 或 LLM HTTP 客户端；具体 Provider 模块不对 CLI 可见。新增依赖必须有实际用途，不为目录整理继续拆分 crate 或新增抽象层。

`just build` 使用 Maturin 从 sdist 构建 wheel，并提取完全相同的 npm 原生文件；`just verify-wheel` 验证隔离安装。PEP 517 版本及完整 hash 约束位于 `packaging/build-constraints.*`，由 `just update-build-constraints` 更新。四目标与发布控制见[发布指南](release-guide.md)。

`just benchmark --profile smoke --repeats 1 --warmups 0 --output dist/benchmarks/smoke.json` 默认测量 Rust release。两种实现的交错比较先运行 `just reference`，再使用 `scripts/eval_rust_release.py` 或 `scripts/eval_rust_workflows.py`。全部输入为隔离合成数据，结果校验不进入计时。场景、测量边界和专用基准脚本见[性能评估](benchmarking.md)。

## 5. 落地页性能与 Cloudflare Workers

落地页使用 Cloudflare Workers Static Assets 托管，无需 Worker 运行时代码。`just check-web` 检查构建与浏览器行为；`just deploy-web` 才会发布，创建或合并 PR 本身不会部署网站。

- `Base.astro` 预加载首屏实际使用的两个 Latin 字体文件，URL 由构建生成，并使用 `crossorigin="anonymous"` 与字体请求保持一致。
- `astro.config.mjs` 从生成的 HTML 提取样式表和字体预加载，写入 `dist/_headers` 的逐页面 `Link` 头。不要手写带 hash 的资源路径，也不要预加载首屏以下的图片或 React 组件。
- 部署后检查 `/`、`/zh/`、`/ja/` 的 `Link` 头与资源 URL；`103` 是否发出受缓存和浏览器支持影响，不能只靠一次请求判断。
- 保留 `public/_headers` 中 `/_astro/*` 的一年期 immutable 缓存。HTML 使用 Workers Static Assets 默认缓存策略，避免叠加 Cache Everything 后出现旧版本。
- 首屏标题与优化后的 WebP 主视觉直接显示，不依赖 JavaScript 或 WebGL。动效遵循 `prefers-reduced-motion`。交互示例使用虚构会话，在浏览器内筛选和展示，不访问真实数据。
- 使用说明保存在 `web/src/pages/guides/` 和 `web/src/pages/zh/guides/` 的 Markdown 文件中。frontmatter 的 `slug`、`locale`、`category`、`order`、`updated`、`title`、`description` 驱动目录、语言切换和文章元数据；相同内容的翻译共用 slug。保留既有文章 URL。
- 新文章同步英文和中文，更新日期必须反映实际内容修改。日文目录明确标记英文文章。正文要包含适用场景、有效命令、输出与限制，并同步 `public/llms.txt`。文章渲染为静态 HTML；筛选仅作渐进增强。
- `web/tests/e2e` 覆盖目录筛选、示例交互、移动导航、无 JavaScript 内容、文章结构化数据与内链。`tests/tooling/test_docs_sync.py` 对照真实 CLI 校验指南参数、URI scheme 和导出目录。
- `404.astro` 生成顶层 `404.html`，配合 `notFoundHandling: "404-page"` 让未知路径返回 404。错误页使用 `noindex`，不输出 canonical 或结构化数据。`public/_redirects` 将旧 `/sitemap.xml` 永久重定向到 `/sitemap-index.xml`；在 GSC 提交后者，部署时核对完整的 18 个可索引页面。
- Umami 仅采集正式域名 `agent-dump.xingkaixin.me`，忽略 hash 并启用 Core Web Vitals。保留 query 以支持 UTM 来源分析。本地、CI 和 Workers 预览不计入正式流量。
- 转化事件：`install-cta` 表示点击安装入口；`install-copy` 表示成功复制 CLI 安装或免安装命令（`method` 区分工具）；`guide-copy` 表示成功复制指南示例；`outbound-click` 表示点击页脚外链。事件仅记录语言、入口或安装方式，不发送命令正文、会话内容。复制命令只是使用意向，不代表安装或执行成功；skill 命令不算 CLI 安装转化。
- Umami 历史数据按 Hostname = `agent-dump.xingkaixin.me` 筛选后再比较。观察 GSC 的非品牌查询曝光、指南点击及 Umami 的安装命令复制率，避免用含测试流量的总浏览量判断 SEO 效果。

部署只使用通过 mise 全局安装并已登录的 `cf`，不在项目依赖或 `mise.toml` 中安装 cf / Wrangler。当前已验证版本为 `cf 1.0.0-beta.12`。`web/scripts/prepare-worker.mjs` 把 Astro 的 `dist/` 复制到 Cloudflare Build Output Specification v0 目录，并写入 Worker 名称、正式域名及 HTML/404 行为。生成目录 `.cloudflare/` 不提交。该格式仍处于 beta；升级全局 cf 后先运行 dry run：

```bash
just build-web
cd web
node scripts/prepare-worker.mjs
cf deploy --prebuilt --dry-run
```

正式发布运行 `just deploy-web`。首次从 Pages 迁移时，先发布并验证 Worker，再解除 Pages 的 `agent-dump.xingkaixin.me` 域名绑定并切换到 Worker Custom Domain。保留旧 Pages 部署供回退，停止向 Pages 发布。后续部署由配置中的 `domains` 维护正式域名。

仅使用 Umami 采集访问和 Core Web Vitals。关闭旧 Pages 项目的 Web Analytics，并保留正式域名的 `disable_rum: true` Configuration Rule，防止域级 Cloudflare RUM 自动注入。该规则由 Cloudflare 控制台/API 管理，不由静态资源部署创建。部署后确认正式页面包含 Umami、没有 `static.cloudflareinsights.com/beacon.min.js`，并检查三种语言、指南、404、sitemap 重定向、`Link` 响应头及 immutable 缓存。

### 阅读器验证

`tests/cli/test_reader.py` 使用隔离来源与 POSIX PTY 验证搜索、复制请求、导出、resize 和退出恢复。`terminal/reader.rs` 的 TestBackend 测试覆盖宽窄布局、中文和工具搜索，Windows 同样执行。复制测试只检查 PTY 中的 OSC 52 序列，不访问系统剪贴板。
