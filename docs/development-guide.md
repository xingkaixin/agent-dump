# 开发与验证指南

本文档面向修改测试、终端交互、依赖或验证配置的贡献者和 Agent。

## 1. 测试原则

测试覆盖可观察行为、回归风险和高风险边界，不要求每个新增函数都有一一对应的测试。

- CLI 参数和模式变更覆盖 `command_plan` 归一化、顶层分发、输出或退出码。
- Provider 测试使用 `tmp_path` 创建临时 SQLite、JSONL 或目录结构，并通过环境变量或构造参数注入路径。
- 测试不得读取真实 `~/.codex`、`~/.claude`、`~/.kimi`、OpenCode、ZCode、Cursor 或 Pi 数据目录，也不得写入真实用户导出目录。
- 终端交互通过受控的 questionary 边界或 stdin/stdout 测试；只有需要隔离交互时才使用 mock。

### i18n 断言

- CLI 文案断言使用 `tests/locale_helpers.py` 的 `expect()` 或 `expect_contains()`，不要新增写死的中英文 UI 文案。
- 默认 locale 由 `conftest.py` 的 `set_language_zh` fixture 设置。
- 其他 locale 使用 `use_language` fixture；英文端到端覆盖位于 `tests/test_cli_locales.py`。
- fixture 中的中文会话内容属于测试数据，不按 UI 文案替换。

## 2. 验证命令

```bash
# 相关测试
uv run pytest -q tests/test_target.py

# 全部 Python 测试
just test

# 覆盖率与下限
just cov

# 完整本地门禁
just isok
```

pytest 配置只位于 `pyproject.toml` 的 `[tool.pytest.ini_options]`。不要新增 `pytest.ini`、`setup.cfg` 或 `tox.ini` 覆盖它。覆盖率不进入默认 addopts，避免单测筛选产生误导性的全包覆盖率报告。

`just check` 同时运行两个作用域不同的检查器：

- pyright 只检查 `src`。
- ty 检查全仓，包括 tests。

代码检查和格式化使用 Ruff，配置位于 `ruff.toml`，单行最大长度 120，字符串使用双引号。

## 3. 交互式 CLI

selector 负责展示和选择，不负责 Provider discovery 或完整内容读取：

- `select_agent_interactive(agents, session_counts)` 的计数由调用方提供。
- Session 标题、摘要和 URI 可以通过无 I/O 的 Provider 投影生成。
- questionary 的 `q`/`Q` 退出、空格选择、回车确认属于用户可见行为；修改时同步更新 selector 测试。
- `Ctrl+C` 返回取消结果。
- 非 TTY 环境回退到简单 stdin 模式。
- 第三方 Session 文本进入终端前必须经过现有安全净化入口。

实现以 `src/agent_dump/selector.py` 为准，行为测试以 `tests/test_selector.py` 为准。不要从文档复制 questionary 代码骨架。

## 4. 依赖

```bash
# 生产依赖
uv add package-name

# 开发依赖
uv add --dev package-name
```

不新增无法证明必要的第三方依赖。必要但不被代码直接 import 的依赖，应在 `pyproject.toml` 声明附近说明运行时关系；不要用泛化注释解释显而易见的依赖。

## 5. 落地页性能与 Cloudflare Pages

落地页继续使用 Pages 免费静态托管。`just check-web` 检查构建与浏览器行为；`just deploy-web` 才会发布，创建或合并 PR 本身不会部署网站。

- `Base.astro` 预加载首屏实际使用的两个 Latin 字体文件，URL 由构建生成，并使用 `crossorigin="anonymous"` 与字体请求保持一致。
- `astro.config.mjs` 从生成的 HTML 提取样式表和字体预加载，写入 `dist/_headers` 的逐页面 `Link` 头。不要手写带 hash 的资源路径，也不要预加载首屏以下的图片或 React 组件。
- Pages 自动支持 [Early Hints](https://developers.cloudflare.com/pages/configuration/early-hints/)。部署后检查 `/`、`/zh/`、`/ja/` 的 `Link` 头与资源 URL；`103` 是否发出受缓存和浏览器支持影响，不能只靠一次请求判断。
- 保留 `public/_headers` 中 `/_astro/*` 的一年期 immutable 缓存。HTML 使用 Pages 默认缓存策略，避免叠加 Cache Everything 后出现旧版本。
- 首屏标题直接显示。WebGL 在页面加载并完成首屏绘制后初始化；离开视口或隐藏标签页时暂停，减少动态效果时只绘制静态帧。

Cloudflare 统计由 Pages 项目的 Web Analytics 注入。自定义域名额外注入的 RUM 脚本通过以下 Configuration Rule 关闭，避免两份 CF 脚本竞争采集。该规则仅匹配落地页；Umami 保留。

```json
{
  "action": "set_config",
  "action_parameters": { "disable_rum": true },
  "description": "Keep Pages analytics as the single agent-dump beacon",
  "enabled": true,
  "expression": "http.host eq \"agent-dump.xingkaixin.me\""
}
```

规则属于 Cloudflare 域名配置，Pages 部署不会创建或覆盖它。首次配置后确认浏览器只加载一份 CF beacon、Pages 统计端点正常接收数据；回滚时禁用这一条规则即可。使用现有 Web Analytics 按地区、设备比较 LCP、INP、CLS，不新增计费产品。
