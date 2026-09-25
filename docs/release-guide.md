# 版本发布与落地页更新指南 (Release Guide)

本文档是 `agent-dump` 版本发布的标准执行 SOP。当用户提供目标版本号（例如 `发布 v0.16.0`）时，AI Agent 与维护者按本指南依次执行，确保发版动作完整、准确、不遗漏。

---

## 核心认知：两套更新日志的分工

发版时必须同步维护两套定位完全不同的更新日志：

1. **代码库开发更新日志 (`CHANGELOG.md` & `docs/zh/CHANGELOG.md`)**：
   - **面向受众**：开源贡献者、打包者、深度开发者。
   - **记录重点**：Commit、PR 编号、内部重构、模块调整、边界修复、技术实现细节。
2. **产品落地页更新日志 (`web/src/lib/i18n.ts`)**：
   - **面向受众**：产品用户、普通开发者、技术评估者、搜索引擎爬虫 (SEO/AEO)。
   - **记录重点**：用户能获得什么实际价值、解决了什么痛点、如何通过新命令体验、产品的整体演进方向与里程碑。
   - **SEO 考量**：自然融入支持的工具名（Codex, Claude Code, Cursor, Kimi, OpenCode, ZCode, Pi）和核心场景词（AI session export, full-text search, prompt handoff, AI collect 等），提供中英日（`en`, `zh`, `ja`）三语支持。

---

## 标准发版执行步骤 (Release Checklist)

```
[1. 分析变更] ──> [2. 同步版本号] ──> [3. 编写 CHANGELOG] ──> [4. 更新落地页日志]
                                                                     │
[向用户汇报 PR] <── [6. 提交 PR & CI 验证] <── [5. 全量本地校验 just isok] <┘
```

### 步骤 1：分析自上一版本以来的 Git 变更
```bash
# 获取自上一个 tag 以来的所有 commit
git log $(git describe --tags --abbrev=0)..HEAD --oneline
```
- 提炼面向开发者的技术修复与改动（用于 CHANGELOG）。
- 提炼面向用户的核心能力、体验改进与产品演进方向（用于落地页 Updates）。

### 步骤 2：更新项目版本号
1. 修改 Rust 单一版本源 `Cargo.toml`：
   ```toml
   [package]
   version = "X.Y.Z"
   ```
2. 在仓库根运行 `cargo check --workspace`，同步 `Cargo.lock` 中的产品版本。
3. 运行 npm workspace 版本同步命令：
   ```bash
   just build-npm
   ```
   *(会自动将版本号同步到 `npm/package.json`、`npm/packages/cli/package.json` 及所有原生平台包)*。

### 步骤 3：更新中英文开发 CHANGELOG
1. **`CHANGELOG.md` (英文)**：
   - 在 `## [Unreleased]` 下方新增 `## [X.Y.Z] - YYYY-MM-DD`。
   - 文件末尾新增 `[X.Y.Z]: https://github.com/xingkaixin/agent-dump/releases/tag/vX.Y.Z`。
2. **`docs/zh/CHANGELOG.md` (中文)**：
   - 在 `## [未发布]` 下方新增 `## [X.Y.Z] - YYYY-MM-DD`。
   - 文件末尾新增 `[X.Y.Z]: https://github.com/xingkaixin/agent-dump/releases/tag/vX.Y.Z`。
3. **按需更新 CLI 文档**：
   - 若有新参数或功能，检查并同步更新 `npm/packages/cli/README.md`、`README.md`、`README_zh.md`。

### 步骤 4：更新产品落地页更新日志 (web)
在 `web/src/lib/i18n.ts` 中，为 `en`、`zh`、`ja` 的 `updates` 列表顶部添加最新版本条目：
```ts
{
  version: "vX.Y.Z",
  date: "YYYY-MM-DD",
  isLatest: true,
  title: "...",        // 价值导向的核心亮点标题
  description: "...",  // 通俗易懂的功能说明与用户价值（自然融入 SEO 场景词）
  command: "...",      // 可直接复制体验的典型命令示例
  tags: ["..."],       // 场景标签
}
```
*(同时将上一版本的 `isLatest` 移除，保持最新条目有 `isLatest: true`)*。

### 步骤 5：运行本地全量自动化验证
在终端运行：
```bash
just isok
```
必须确认以下全部通过：
- `uv lock --check`：依赖锁定文件一致
- `ruff check` & `ruff format`：代码风格与格式化检查
- Clippy 与 `ty`：Rust 和辅助工具类型检查通过
- `cargo test --locked --workspace` 与 `pytest`：Rust 单元、CLI 差分和工具验证通过
- `npm test`：npm 包装器单元测试全部通过
- `check-web`：Astro 静态构建与 Playwright E2E 测试全部通过

### 步骤 6：创建 PR 与 CI 验证（Agent 流程终点）
1. 创建分支并提交：
   ```bash
   git checkout -b release/vX.Y.Z
   git add -A
   git commit -m "chore(release): prepare vX.Y.Z" -m "Update version to X.Y.Z and synchronize changelogs, web updates, and documentation."
   git push -u origin release/vX.Y.Z
   ```
2. 创建 PR（PR 描述必须使用英文）：
   ```bash
   gh pr create --title "chore(release): prepare vX.Y.Z" --body "..."
   ```
3. 等待 GitHub Actions CI 矩阵测试全部通过：
   ```bash
   gh pr checks <PR编号> --watch
   ```
4. 向用户汇报 PR 链接、变更摘要与 CI 检查状态，发版准备流程结束。

---

## 用户自主发布阶段 (User Controlled)

以下合并与发布动作**完全由用户自行控制**，Agent 严禁擅自执行：

1. 用户审查 PR 并执行 Squash Merge（通过 GitHub UI 或 CLI）：
   ```bash
   gh pr merge <PR编号> --squash --delete-branch
   ```
2. 用户在本地拉取最新 `main` 分支并创建推送 Tag 触发发布流水线：
   ```bash
   git checkout main && git pull origin main
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
   *(GitHub Actions 监测到 `vX.Y.Z` Tag 会自动执行统一流水线，完成 PyPI、npm 与 GitHub Release 发布)*。

---

## 构建约束

- `npm/packages/cli/lib/native-targets.json` 是原生目标闭集的唯一机器可读定义；runtime、npm 发布脚本和 release matrix 从该文件派生。
- `packaging/build-constraints.in` 保存直接构建后端的精确版本，由 Dependabot 的 pip 入口更新。
- `packaging/build-constraints.txt` 保存完整传递闭包和可信 hash，只通过 `just update-build-constraints` 重新生成。
- 本地 `just build`、CI/release 共用的四平台制品 job 使用同一约束文件及 `--require-hashes`，不得关闭 PEP 517 build isolation。
- 合并和发布仍属于上节定义的用户控制阶段。构建约束不扩大 Agent 的发布权限。

## Rust 制品与验收

v1.0.0 是首个 Rust 发布目标。Cargo 与 npm 产品版本同步为 1.0.0；外部 Python 差分参考继续固定为 0.15.9，不随产品发版升级。不得以已发布的 0.15.9 发布 Rust 制品。版本准备不代表已发布；合并与 tag 仍由用户控制。

- `pyproject.toml` 使用 Maturin `bin`，版本取自 Cargo；wheel 只安装原生 `agent-dump`，没有 Python API、模块入口或 Python runtime dependencies。
- 旧 Python 应用已移出主树，差分参考由 `tests/reference/requirements.txt` 固定并独立安装。旧 API 使用方可固定 Python 0.15.9。
- `.github/workflows/build-artifacts.yml` 同时被 PR CI 和 tag release 调用。四目标由 `npm/packages/cli/lib/native-targets.json` 派生，不在 workflow 复制平台列表。
- `packaging/build_release.py` 在固定 Rust 工具链下使用 PEP 517 隔离构建，Maturin 由完整 hash constraints 约束；先构建 sdist，再从 sdist 构建 wheel。npm 原生文件直接提取自 wheel，字节一致。
- Linux 使用固定 Zig 0.13.0 链接，Maturin 检查 `manylinux_2_17`；另在固定镜像 digest 的 manylinux2014 容器运行隔离会话验证。最低 glibc 为 2.17；不发布 musllinux/Alpine wheel。
- macOS x64 最低 10.12，arm64 最低 11.0；Windows x64 使用 MSVC。macOS/Windows 验证在当前 GitHub runner，wheel 标签不代表对每个历史 OS 版本做过实机测试。
- 四目标分别验证 Python 3.10 与 3.14 的 pip、uv tool install、uvx，以及 npm、npx、bunx。测试生成合成来源，验证版本、帮助、print、JSON 导出和源未改写，所有临时安装自动清理。
- 每个目标输出 `artifact-report.json`，记录 wheel、sdist、native 的大小与 SHA-256。发布 job 下载已验证的四个 wheel 和 Linux 生成的 sdist，不重新构建。

本地：`just build`、`just verify-wheel`；使用 `node npm/scripts/stage-binaries.mjs <manifest target> dist/native/<target>/<executable>` 暂存后运行 `just test-npm-smoke`。发布前仍需 `just isok`、PR 全部 CI 通过及无冲突。用户控制 merge 和 tag；构建制品不等于授权发布。
