// Strings mirror resources/locales/{zh,en}.json READER_*; the CLI ships zh and en only.
export const tuiStrings = {
  zh: {
    sessions: "会话",
    body: "正文",
    ready: "s 搜索会话；/ 查找当前会话。",
    matches: "命中 {count} 条消息 · n/N 下一个/上一个",
    copyRequest: "已向终端发送复制请求（需要支持 OSC 52）。",
    help: "s 搜索会话 · / 会话内查找 · n/N 命中 · x 摘录 · +/- 上下文\nTab 切换 · 空格 选择 · e 导出 · y URI · c 清词 · ? 帮助 · q 退出",
    results: "{count} 个会话 · s 搜索 · x 预览命中摘录",
    noMatches:
      "没有匹配会话。s 修改搜索，c 清除关键词。? 查看范围；重新打开时可扩大 --days 或减少 --query 筛选。",
    scope: "来源: 全部 · 最近 7 天（更新）\n目录: 全部 · 角色: 全部 · 上限: 全部",
    state: "{count} 个会话 · 搜索（{mode}）: {query}",
    terms: "全部词",
    inputSessions: "搜索会话",
    inputMessages: "当前会话",
    marked: "已选 {count} 个会话 · e 导出所选 · 空格切换",
    needHit: "请先用 / 或 s 找到命中消息，再预览摘录。",
    excerptHelp: "摘录预览 · +/- 调整前后消息数 · e 导出 · x/Esc 返回",
    excerptRange: "摘录 #{start}–{end}/{total} · +/- 上下文",
    helpTitle: "帮助 · ↑/↓ 滚动 · ?/Esc 关闭",
    helpFull:
      "s：搜索当前范围内会话，全部词均须命中\n/：在当前会话内查找字面短语\nc：清除关键词，保留来源、目录、日期和角色筛选\nn/N：下一条/上一条命中消息\nx：预览命中消息，默认包含前后各 3 条\n+/-：前后各增加/减少一条消息\n空格：选择会话用于批量导出\ne：导出预览范围；未预览时导出已选会话或当前完整会话\nx/Esc：退出摘录预览\nTab/左右：切换栏 · 上下/j/k：移动\nt：工具详情 · y：复制会话 URI\nq/Ctrl-C：退出 · ?/Esc：关闭帮助\n\n浏览期间来源、目录、日期筛选保持固定。重新打开时使用 --query / --days / --time-field 更改范围。",
    exported: "导出 {count} 个所选会话…",
    exportedOne: "导出当前完整会话…",
    exportedRange: "导出摘录 #{start}–{end}…",
    quit: "演示不会退出；在真实终端里 q 关闭阅读器。",
  },
  en: {
    sessions: "Sessions",
    body: "Transcript",
    ready: "s searches sessions; / finds text in this session.",
    matches: "{count} matching messages · n/N next/previous",
    copyRequest: "Copy request sent to terminal (OSC 52 support required).",
    help: "s search sessions · / find here · n/N hits · x excerpt · +/- context\nTab panes · Space select · e export · y URI · c clear search · ? help · q quit",
    results: "{count} sessions · s search · x preview matching excerpt",
    noMatches:
      "No matching sessions. s changes search; c clears it. Check scope with ?; widen --days or remove --query filters when reopening.",
    scope: "Provider: all · updated: last 7 days\nPath: all · Role: all · Limit: all",
    state: "{count} sessions · Search ({mode}): {query}",
    terms: "all words",
    inputSessions: "Sessions",
    inputMessages: "This session",
    marked: "{count} selected · e exports selected sessions · Space toggles",
    needHit: "Find a matching message with / or s before previewing an excerpt.",
    excerptHelp:
      "Excerpt preview · +/- changes surrounding messages · e exports · x/Esc returns",
    excerptRange: "Excerpt #{start}–{end}/{total} · +/- context",
    helpTitle: "Help · ↑/↓ scroll · ?/Esc close",
    helpFull:
      "s: search sessions in this scope (all words must match)\n/: find a literal phrase in the current session\nc: clear search words, keep Provider/path/date/role filters\nn/N: next/previous matching message\nx: preview the match with 3 messages on either side\n+/-: add/remove one message on each side\nSpace: select sessions for batch export\ne: export the previewed range, selected sessions, or the full session\nx/Esc: leave excerpt preview\nTab/Left/Right: switch panes · arrows/j/k: move\nt: toggle tool details · y: copy session URI\nq/Ctrl-C: quit · ?/Esc: close help\n\nProvider/path/date filters stay fixed while browsing. Reopen with different --query / --days / --time-field options to change scope.",
    exported: "Exporting {count} selected sessions…",
    exportedOne: "Exporting the full session…",
    exportedRange: "Exporting excerpt #{start}–{end}…",
    quit: "The demo stays open; q closes the reader in a real terminal.",
  },
};

export type TuiStrings = (typeof tuiStrings)["en"];

export type DemoSession = {
  uri: string;
  title: string;
  provider: string;
  when: string;
  path: string;
  // [role, text, tool detail shown by `t`]
  messages: [string, string, string?][];
};

export const demoSessions: Record<"zh" | "en", DemoSession[]> = {
  zh: [
    {
      uri: "codex://019a7c2e",
      title: "网关超时配置梳理",
      provider: "codex",
      when: "2 小时前",
      path: "~/work/gateway",
      messages: [
        ["user", "上游偶发 504，auth timeout 要不要从 30s 提到 60s？"],
        ["assistant", "先别改。日志显示超时集中在 token 刷新那一步，重试时 refresh token 已经过期。", '  [tool] rg "auth_timeout" config/ → 3 matches'],
        ["user", "那先修刷新顺序？"],
        ["assistant", "对。重试前先刷新 token，再给 auth timeout 的边界补测试。", "  [tool] cargo test auth::retry → 12 passed"],
        ["user", "好，记一下：60s 方案暂缓。"],
        ["assistant", "已记录。待办：刷新顺序修复、auth timeout 边界测试、观察一周 504 比例。"],
      ],
    },
    {
      uri: "claude://7f3c91",
      title: "修复登录超时重试",
      provider: "claude",
      when: "1 天前",
      path: "~/work/web",
      messages: [
        ["user", "登录页在 auth timeout 之后一直转圈。"],
        ["assistant", "前端重试没有上限。改成指数退避，最多 3 次。", "  [tool] Edit src/login/retry.ts"],
        ["user", "失败后的提示文案呢？"],
        ["assistant", "第三次失败后提示“网络较慢，请稍后重试”，并保留输入内容。"],
      ],
    },
    {
      uri: "cursor://b21e04",
      title: "会话刷新逻辑",
      provider: "cursor",
      when: "3 天前",
      path: "~/work/web",
      messages: [
        ["user", "refresh 和 logout 同时发生会怎样？"],
        ["assistant", "可能把已注销的 token 写回存储。给 refresh 加版本号，过期写入直接丢弃。"],
      ],
    },
    {
      uri: "opencode://ses_4k2",
      title: "数据库迁移方案",
      provider: "opencode",
      when: "4 天前",
      path: "~/work/api",
      messages: [
        ["user", "怎么迁移才不丢已有记录？"],
        ["assistant", "先加新列，回填旧数据，再切读路径。旧列保留到下个版本。", '  [tool] psql -c "\\d sessions"'],
      ],
    },
    {
      uri: "kimi://c9e1",
      title: "周报素材整理",
      provider: "kimi",
      when: "5 天前",
      path: "~/notes",
      messages: [
        ["user", "列出本周和 auth 相关的改动。"],
        ["assistant", "三项：token 刷新顺序、登录重试上限、refresh 版本号。"],
      ],
    },
    {
      uri: "pi://p_77",
      title: "搜索索引增量更新",
      provider: "pi",
      when: "6 天前",
      path: "~/work/agent-dump",
      messages: [
        ["user", "没变化的会话能不能跳过索引？"],
        ["assistant", "比较源版本和缓存版本，只重建变化的记录，并删除已消失来源的条目。"],
      ],
    },
  ],
  en: [
    {
      uri: "codex://019a7c2e",
      title: "Gateway timeout config review",
      provider: "codex",
      when: "2h ago",
      path: "~/work/gateway",
      messages: [
        ["user", "Upstream returns an occasional 504. Should auth timeout go from 30s to 60s?"],
        ["assistant", "Not yet. The logs show timeouts during token refresh; the refresh token has expired by the time we retry.", '  [tool] rg "auth_timeout" config/ → 3 matches'],
        ["user", "So fix the refresh order first?"],
        ["assistant", "Yes. Refresh the token before retrying, then add tests for the auth timeout boundary.", "  [tool] cargo test auth::retry → 12 passed"],
        ["user", "OK. Note that the 60s change is on hold."],
        ["assistant", "Noted. Todo: fix refresh order, test the auth timeout boundary, watch the 504 rate for a week."],
      ],
    },
    {
      uri: "claude://7f3c91",
      title: "Fix login timeout retry",
      provider: "claude",
      when: "1d ago",
      path: "~/work/web",
      messages: [
        ["user", "The login page spins forever after an auth timeout."],
        ["assistant", "The client retries without a limit. Switch to exponential backoff, at most 3 attempts.", "  [tool] Edit src/login/retry.ts"],
        ["user", "What should the error say?"],
        ["assistant", 'After the third failure, show "The network is slow, try again shortly" and keep the input.'],
      ],
    },
    {
      uri: "cursor://b21e04",
      title: "Session refresh logic",
      provider: "cursor",
      when: "3d ago",
      path: "~/work/web",
      messages: [
        ["user", "What happens if refresh and logout run at the same time?"],
        ["assistant", "A revoked token could be written back. Version each refresh and drop stale writes."],
      ],
    },
    {
      uri: "opencode://ses_4k2",
      title: "Database migration plan",
      provider: "opencode",
      when: "4d ago",
      path: "~/work/api",
      messages: [
        ["user", "How do we migrate without losing existing records?"],
        ["assistant", "Add the new column, backfill, then switch reads. Keep the old column until the next release.", '  [tool] psql -c "\\d sessions"'],
      ],
    },
    {
      uri: "kimi://c9e1",
      title: "Weekly report notes",
      provider: "kimi",
      when: "5d ago",
      path: "~/notes",
      messages: [
        ["user", "List this week’s auth-related changes."],
        ["assistant", "Three: token refresh order, login retry limit, refresh versioning."],
      ],
    },
    {
      uri: "pi://p_77",
      title: "Incremental search index",
      provider: "pi",
      when: "6d ago",
      path: "~/work/agent-dump",
      messages: [
        ["user", "Can we skip indexing sessions that have not changed?"],
        ["assistant", "Compare source and cached revisions, rebuild only changed records, and drop entries for missing sources."],
      ],
    },
  ],
};

// "__" pauses one tick; "RESET" restarts the loop.
export const demoScript = [
  "__", "j", "j", " ", "k", " ", "__", "s", "a", "u", "t", "h", "Enter", "__", "__",
  "n", "__", "x", "__", "+", "__", "Escape", "ArrowRight", "t", "__", "__",
  "ArrowLeft", "e", "__", "__", "?", "__", "__", "__", "?", "c", "__", "RESET",
];
