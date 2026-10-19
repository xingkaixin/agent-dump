# 落地页性能与 Cloudflare Workers

落地页使用 Cloudflare Workers Static Assets 托管，无需 Worker 运行时代码。`just check-web` 检查构建与浏览器行为；`just deploy-web` 才会发布，创建或合并 PR 本身不会部署网站。

OG 图使用落地页字体、Logo 和配色。在安装 web 依赖及 Playwright Chromium 后，运行 `node web/scripts/generate-og.mjs`，生成网站的 `web/public/assets/og-image.png`（1200×631）和 GitHub 的 `assets/github-og.png`（1280×640）。GitHub 图片需在仓库 Settings → Social preview 中上传。

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
