# 落地页改版验收记录

日期：2026-10-03。分支：`feat/landing-redesign-guides`。

## 设计与内容

面向开发者的技术编辑风格，保留 Geist、IBM Plex Mono、现有标识与朱红强调色。设计取值为 `DESIGN_VARIANCE: 8`、`MOTION_INTENSITY: 5`、`VISUAL_DENSITY: 3`。独特性来自纸张主视觉、版式和可操作的会话示例；动效用于进入层级与操作反馈。

首页依次解释产品价值、支持工具、核心操作、使用场景、安装、近期更新和常见问题。较早版本保留在可展开区域。示例明确标注虚构会话与简化输出，不读取用户数据。

使用说明覆盖六个主题，每个主题均有中英版本：Codex 导出、Claude Code 导出、历史搜索、Agent 上下文交接、工作报告、Obsidian 归档。日文目录明确指向英文文章。原有 Codex 教程地址保持不变。

文章以静态 HTML 输出，支持目录、相关推荐和命令复制。筛选只是渐进增强，无 JavaScript 时所有文章链接仍然可用。每篇文章提供独立 title、description、canonical、语言替代链接、Article 与 BreadcrumbList 数据，并进入 sitemap。`llms.txt` 与 README 同步。

## 自检与修正

| 检查轮次 | 实际发现 | 修正 |
| --- | --- | --- |
| 结构与整体视觉 | 原首屏说明过长，装饰场景依赖 WebGL，十个版本占据过多页面空间 | 缩短首屏，使用优化后的生成主视觉，加入可操作示例，收起较早版本 |
| 排版与响应式 | 工具列表标题层级过大，浅色文章代码块过重，移动端目录先于标题 | 修正选择器与语法主题，调整文章布局，让标题先于目录 |
| 实际操作与可访问性 | 示例延迟初始化可能漏掉首次输入，品牌可访问名称与显示名称不一致，中文标题拆开词语 | 提前初始化示例，统一名称，用构建期中文分词保留标题词组，补充命令复制 |

移动检查覆盖 360、768、1024、1440 像素宽度，深浅两种主题，三语首页、三语目录及中英文章代表页，共 64 组。页面未出现横向溢出。实际检查了桌面与手机尺寸截图、键盘导航、主题切换、搜索空结果及减少动态效果。

## 自动化与性能

- `just check-web`：类型检查、18 个静态页面构建、17 项 Playwright 浏览器测试通过。
- 指南命令校验：对照 CLI 参数、Provider scheme 和隔离会话的实际导出目录。
- WebKit 手机尺寸：会话搜索、格式切换、主题切换、指南筛选与文章渲染检查通过。
- 本地 Lighthouse 13.5.0 移动配置：首页性能 99，可访问性、最佳实践、SEO 均 100。LCP 2.0 秒、TBT 0 毫秒、CLS 0。中文交接文章四项均 100。分数属于本地实验室结果，不能代替上线后的真实用户指标。
- 仓库检查使用 `rust-toolchain.toml` 固定的 Rust 1.90：锁文件、格式、Clippy、类型检查、49 项 Rust 单元测试（另有 1 项忽略）、1,795 项 Python/CLI 测试、84 项 npm 测试通过。`just isok` 的最后一个网站步骤因本地预览服务占用启动入口中断；停止预览后单独重跑 `just check-web`，结果见上。

## 参考与边界

验收参考 [Webby 官方标准](https://www.webbyawards.com/judging-criteria/)中的内容、结构、视觉、功能与交互，以及 [Google 的 Article 结构化数据说明](https://developers.google.com/search/docs/appearance/structured-data/article)。Awwwards、Webby、FWA 是设计目标，内部自检和 Lighthouse 不构成获奖认证。收录、搜索排名与真实用户性能需要部署后观察。本次没有发布线上网站。

## 主视觉来源

资产：`web/src/assets/editorial/session-paper.png`。使用内置 `image_gen` 生成，生产页面由 Astro 输出响应式 WebP。社交分享图 `web/public/assets/og-image.png` 使用相同资产和品牌排版，通过浏览器渲染生成。

生成提示词原文：

> Use case: stylized-concept. Create a premium art-directed 3D editorial image for Agent Dump, an open-source developer tool that makes scattered AI coding conversations readable and portable. This is an image asset, no website UI, no typography, no letters, no logos, no symbols. Subject: a sculptural fan of numerous extraordinarily thin translucent warm-white paper sheets arching together into one neatly aligned flat document stack on a matte very light gray-green studio surface, one single deep vermilion-red sheet threads continuously through the center of the fan and lays out as a broad gently curved strip in the foreground. The fan should have an elegant precise structural form, like an archival sculpture or Japanese paper study, dramatic asymmetrical diagonal sweep from upper right to lower left, side view with a little elevation. Color palette only soft off-white #f1f3ef, charcoal soft shadows, and restrained oxide red #b63824. Beautiful subtle paper fiber microtexture, realistic soft daylight from upper left, ambient occlusion between thin edges, architectural product photography, editorial art direction, exquisite physical realism. Wide landscape aspect ratio 3:2. The object should fill the frame horizontally, with negative space around it, no crop at the top. No glass, no shiny metallic chrome, no glowing neon, no sci-fi, no computers, no screens, no arrows, no confetti, no text.
