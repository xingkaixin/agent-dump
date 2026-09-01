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
1. 修改 Python 单一版本源 `src/agent_dump/__about__.py`：
   ```python
   __version__ = "X.Y.Z"
   ```
2. 运行 npm workspace 版本同步命令：
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
- `pyright` & `ty`：类型检查 0 错误 0 告警
- `pytest`：Python 测试与覆盖率底线达标
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
