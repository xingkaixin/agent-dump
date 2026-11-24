import type { Locale } from "./i18n";

export type CapabilityCopy = { verb: string; body: string };

export type LandingCopy = {
  nav: { browse: string; faq: string };
  stage: {
    sources: string;
    sample: string;
    output: string;
    hits: string;
    untouched: string;
    handoff: string;
    meta: string;
    moreProviders: string;
    written: string;
    hitsList: {
      uri: string;
      loc: string;
      age: string;
      lead: string;
      match: string;
      tail: string;
      file: string;
      user: string;
      assistant: string;
    }[];
  };
  footer: {
    product: string;
    providers: string;
    guides: string;
    distribution: string;
    codexGuide: string;
    claudeGuide: string;
    handoffGuide: string;
    readOnlyNote: string;
  };
  sample: { s1: string; s2: string; s3: string; q1: string; q2: string };
  notes: { scan: string; chunk: string };
  codexGuide: string;
  uri: { label: string };
  demo: {
    days: string;
    provider: string;
    role: string;
    readDone: string;
    exportUser: string;
    exportAssistant: string;
    collectStdout: string;
  };
  capabilities: {
    heading: string;
    items: [CapabilityCopy, CapabilityCopy, CapabilityCopy, CapabilityCopy];
  };
  browse: {
    heading: string;
    autoplay: string;
    replay: string;
    label: string;
    keysLabel: string;
    space: string;
    keys: string[];
  };
  audience: {
    headingLead: string;
    headingTail: string;
    developer: {
      title: string;
      steps: [string, string, string];
    };
    agent: {
      title: string;
      body: string;
      steps: [string, string, string];
    };
  };
  boundary: {
    heading: string;
    flow: {
      source: string;
      sourceItems: [string, string, string];
      owned: string;
      ownedItems: [string, string, string];
    };
    note: { title: string; body: string };
  };
  updates: { latest: string; older: string };
  menu: string;
};

export const landing: Record<Locale, LandingCopy> = {
  en: {
    nav: { browse: "Browse", faq: "FAQ" },
    stage: {
      sources: "Discovered sources",
      sample: "agent-dump · sample output",
      output: "Output",
      hits: "3 sessions · 7 hits · locators kept",
      untouched: "Read-only · source untouched",
      handoff: "weekly.md handoff",
      meta: "19 local providers · FTS5 index",
      moreProviders: "13 more tools",
      written: "Written to",
      hitsList: [
        {
          uri: "codex://019a7c2e",
          loc: "msg 3",
          age: "2d ago",
          lead: "Gateway timeout config: hold off on raising ",
          match: "auth timeout",
          tail: ", failures cluster around token refresh.",
          file: "./sessions/codex/019a7c2e.md",
          user: "Upstream returns 504 now and then. Raise auth timeout from 30s to 60s?",
          assistant: "Not yet. Logs show timeouts cluster around token refresh. Reuse the HTTP pool and trace upstream latency first.",
        },
        {
          uri: "claude://7f3c91",
          loc: "msg 14",
          age: "5d ago",
          lead: "Fix login timeout retry: ",
          match: "auth timeout",
          tail: " triggers backoff after 30s; wire up cancellation context.",
          file: "./sessions/claude/7f3c91.md",
          user: "Login retries pile up when the auth upstream stalls past 30s.",
          assistant: "Pass the request AbortSignal into the retry loop so canceled logins stop immediately after auth timeout.",
        },
        {
          uri: "opencode://5c4b3a",
          loc: "msg 1",
          age: "9d ago",
          lead: "Session refresh logic: compare upstream 504 logs against local ",
          match: "auth timeout",
          tail: " thresholds.",
          file: "./sessions/opencode/5c4b3a.md",
          user: "Can we check if local auth timeout is shorter than the gateway idle window?",
          assistant: "Yes: client auth timeout is 30s while gateway refresh sits at 45s. Aligning both removes the spurious retries.",
        },
      ],
    },
    footer: {
      product: "Product",
      providers: "Supported tools",
      guides: "Guides",
      distribution: "Distribution",
      codexGuide: "Export Codex sessions",
      claudeGuide: "Export Claude Code",
      handoffGuide: "Agent context handoff",
      readOnlyNote: "Local read-only · source sessions are never modified",
    },
    sample: {
      s1: "Fix login timeout retry",
      s2: "Gateway timeout config review",
      s3: "Session refresh logic",
      q1: "auth timeout retries after 30s, so we need…",
      q2: "Before raising auth timeout, confirm upstream…",
    },
    notes: {
      scan: "last 7 days · all Providers",
      chunk: "user / assistant text, read in chunks",
    },
    codexGuide: "Export a Codex session to Markdown",
    uri: {
      label: "A session URI combines the source tool scheme and the session ID",
    },
    demo: {
      days: "last 30 days",
      provider: "Provider: all",
      role: "Role: all",
      readDone: "done",
      exportUser: "Upstream returns 504 now and then. Raise auth timeout from 30s to 60s?",
      exportAssistant: "Not yet. The logs show timeouts cluster around the token refresh…",
      collectStdout: "external Agent instructions · target ./reports/weekly.md",
    },
    capabilities: {
      heading: "Four moves for everything after the chat ends.",
      items: [
        {
          verb: "Find",
          body: "Search titles, messages, reasoning, and tool state. Filter by Provider, project path, role, or recent activity.",
        },
        {
          verb: "Read",
          body: "Browse in the terminal, open a Session URI, or give an Agent bounded JSON pages with cursors.",
        },
        {
          verb: "Export",
          body: "Export to Markdown or JSON. Context exports keep the URI and message locators.",
        },
        {
          verb: "Collect",
          body: "Read every eligible message in chunks and emit report instructions for an external Agent. Failures are marked incomplete.",
        },
      ],
    },
    browse: {
      heading: "A session reader in your terminal.",
      autoplay: "Auto demo · click the terminal to take over",
      replay: "Replay demo",
      label: "Interactive agent-dump --browse demo, keyboard operable",
      keysLabel: "Demo keys",
      space: "Space",
      keys: [
        "down",
        "up",
        "switch pane",
        "select",
        "export",
        "search sessions",
        "find here",
        "next hit",
        "excerpt",
        "tool details",
        "clear search",
        "help",
      ],
    },
    audience: {
      headingLead: "People read in the terminal. ",
      headingTail: "Agents read JSON.",
      developer: {
        title: "Three commands for last week's work",
        steps: ["browse the last week", "search this project", "export by URI"],
      },
      agent: {
        title: "Reading you can verify",
        body: "Check exit codes and status; a partial result never passes as a complete read.",
        steps: [
          "capabilities & paths",
          "candidate sessions",
          "paging instructions",
        ],
      },
    },
    boundary: {
      heading: "Reads your sessions. Never touches your data.",
      flow: {
        source: "Provider sessions",
        sourceItems: ["Databases", "JSONL", "Session directories"],
        owned: "Paths agent-dump owns",
        ownedItems: ["Index · config", "Logs", "Exports"],
      },
      note: {
        title: "Incomplete says incomplete",
        body: "Failed reads or summaries are marked; unknown facts stay unknown.",
      },
    },
    updates: { latest: "Latest", older: "Earlier releases" },
    menu: "Navigation menu",
  },
  zh: {
    nav: { browse: "会话阅读器", faq: "常见问题" },
    stage: {
      sources: "已发现会话源",
      sample: "agent-dump · 示例输出",
      output: "输出",
      hits: "3 sessions · 7 hits · 保留消息定位",
      untouched: "只读模式 · 源会话未改动",
      handoff: "weekly.md 交接",
      meta: "19 个本地 Provider · FTS5 索引",
      moreProviders: "其余 13 款工具",
      written: "已写入",
      hitsList: [
        {
          uri: "codex://019a7c2e",
          loc: "msg 3",
          age: "2 天前",
          lead: "网关超时配置梳理：先别提高 ",
          match: "auth timeout",
          tail: "，超时集中在 token 刷新阶段。",
          file: "./sessions/codex/019a7c2e.md",
          user: "上游偶发 504，auth timeout 要不要从 30s 提到 60s？",
          assistant: "先别改。日志显示超时集中在 token 刷新那一步，优先复用连接池并记录上游延迟。",
        },
        {
          uri: "claude://7f3c91",
          loc: "msg 14",
          age: "5 天前",
          lead: "修复登录超时重试：",
          match: "auth timeout",
          tail: " 在 30s 后触发退避，需补齐取消信号。",
          file: "./sessions/claude/7f3c91.md",
          user: "鉴权上游超过 30s 无响应时，登录重试会一直堆积。",
          assistant: "把请求的取消信号透传进重试循环，触发 auth timeout 后立即终止已取消的登录尝试。",
        },
        {
          uri: "opencode://5c4b3a",
          loc: "msg 1",
          age: "9 天前",
          lead: "会话刷新逻辑：对比上游 504 日志与本地 ",
          match: "auth timeout",
          tail: " 阈值。",
          file: "./sessions/opencode/5c4b3a.md",
          user: "帮我确认本地 auth timeout 是否比网关空闲窗口更短？",
          assistant: "是的，客户端 auth timeout 为 30s，网关刷新窗口是 45s，对齐阈值后即可消除误重试。",
        },
      ],
    },
    footer: {
      product: "产品",
      providers: "支持的工具",
      guides: "使用指南",
      distribution: "分发与源码",
      codexGuide: "导出 Codex 会话",
      claudeGuide: "导出 Claude Code",
      handoffGuide: "Agent 上下文交接",
      readOnlyNote: "本地只读 · 不修改任何 Provider 源数据",
    },
    sample: {
      s1: "修复登录超时重试",
      s2: "网关超时配置梳理",
      s3: "会话刷新逻辑",
      q1: "auth timeout 在 30s 后触发重试，需要…",
      q2: "提高 auth timeout 之前先确认上游…",
    },
    notes: {
      scan: "最近 7 天 · 全部 Provider",
      chunk: "user / assistant 正文，按块读取",
    },
    codexGuide: "将 Codex 会话导出为 Markdown",
    uri: {
      label: "会话 URI 由来源工具 scheme 与会话 ID 组成",
    },
    demo: {
      days: "近 30 天",
      provider: "Provider: 全部",
      role: "角色: 全部",
      readDone: "读完",
      exportUser: "上游偶发 504，auth timeout 要不要从 30s 提到 60s？",
      exportAssistant: "先别改。日志显示超时集中在 token 刷新那一步…",
      collectStdout: "外部 Agent 指令 · 目标报告 ./reports/weekly.md",
    },
    capabilities: {
      heading: "四个动作，覆盖一段对话的后半生。",
      items: [
        {
          verb: "查找",
          body: "搜索标题、消息、推理与工具状态，按 Provider、项目路径、角色或最近活动筛选。",
        },
        {
          verb: "阅读",
          body: "在终端浏览，打开 Session URI，或让 Agent 用有界 JSON 分页和游标读取。",
        },
        {
          verb: "导出",
          body: "导出为 Markdown 或 JSON；上下文片段保留 URI 与消息定位。",
        },
        {
          verb: "汇总",
          body: "分块读取全部符合条件的正文，生成给外部 Agent 的报告指令。失败会标记为不完整。",
        },
      ],
    },
    browse: {
      heading: "终端里的会话阅读器。",
      autoplay: "自动演示中 · 点击终端接管",
      replay: "重播演示",
      label: "agent-dump --browse 交互演示，可用键盘操作",
      keysLabel: "演示按键",
      space: "空格",
      keys: [
        "下移",
        "上移",
        "切换栏",
        "选择",
        "导出",
        "搜索会话",
        "会话内查找",
        "下一个命中",
        "命中摘录",
        "工具详情",
        "清除关键词",
        "帮助",
      ],
    },
    audience: {
      headingLead: "人用终端读，",
      headingTail: "Agent 用 JSON 读。",
      developer: {
        title: "三条命令找回上周的工作",
        steps: ["浏览最近一周", "在当前项目里搜索", "按 URI 导出"],
      },
      agent: {
        title: "可验证的完整读取",
        body: "检查退出码和 status；部分结果不会被当成完整读取。",
        steps: ["能力与路径", "候选会话", "分页指令"],
      },
    },
    boundary: {
      heading: "只读你的会话，不碰你的数据。",
      flow: {
        source: "Provider 会话源",
        sourceItems: ["数据库", "JSONL", "会话目录"],
        owned: "agent-dump 自有路径",
        ownedItems: ["索引 · 配置", "日志", "导出文件"],
      },
      note: {
        title: "不完整就说不完整",
        body: "读取或摘要失败会被明确标记；未知的事实保持未知。",
      },
    },
    updates: { latest: "最新版本", older: "更早版本" },
    menu: "导航菜单",
  },
  ja: {
    nav: { browse: "閲覧", faq: "よくある質問" },
    stage: {
      sources: "検出された読み取り元",
      sample: "agent-dump · サンプル出力",
      output: "出力",
      hits: "3 sessions · 7 hits · 位置情報を保持",
      untouched: "読み取り専用 · 元データは変更なし",
      handoff: "weekly.md 引き継ぎ",
      meta: "19 のローカル Provider · FTS5 インデックス",
      moreProviders: "ほか 13 ツール",
      written: "書き出し完了",
      hitsList: [
        {
          uri: "codex://019a7c2e",
          loc: "msg 3",
          age: "2 日前",
          lead: "ゲートウェイ設定確認：",
          match: "auth timeout",
          tail: " を上げる前にトークン更新時の遅延を確認。",
          file: "./sessions/codex/019a7c2e.md",
          user: "上流でときどき 504。auth timeout を 30 秒から 60 秒に上げる？",
          assistant: "まだ変えないで。ログではトークン更新の段階でタイムアウトが集中しています。接続再利用を先に確認しましょう。",
        },
        {
          uri: "claude://7f3c91",
          loc: "msg 14",
          age: "5 日前",
          lead: "ログイン再試行の修正：",
          match: "auth timeout",
          tail: " は 30 秒後にバックオフするため中断信号を伝播。",
          file: "./sessions/claude/7f3c91.md",
          user: "認証の上流が 30 秒止まるとログイン再試行が積み上がります。",
          assistant: "再試行ループに中断シグナルを渡し、auth timeout 後にキャンセル済み要求を即座に止めます。",
        },
        {
          uri: "opencode://5c4b3a",
          loc: "msg 1",
          age: "9 日前",
          lead: "セッション更新ロジック：504 ログとローカルの ",
          match: "auth timeout",
          tail: " 閾値を比較。",
          file: "./sessions/opencode/5c4b3a.md",
          user: "ローカルの auth timeout がゲートウェイの待機時間より短いか確認できますか？",
          assistant: "はい。クライアントは 30 秒、ゲートウェイ更新は 45 秒でした。揃えると不要な再試行が消えます。",
        },
      ],
    },
    footer: {
      product: "製品",
      providers: "対応ツール",
      guides: "ガイド",
      distribution: "配布・ソース",
      codexGuide: "Codex セッションをエクスポート",
      claudeGuide: "Claude Code をエクスポート",
      handoffGuide: "Agent への引き継ぎ",
      readOnlyNote: "ローカル読み取り専用 · 元セッションは変更しません",
    },
    sample: {
      s1: "ログインのタイムアウト再試行を修正",
      s2: "ゲートウェイのタイムアウト設定",
      s3: "セッション更新ロジック",
      q1: "auth timeout は 30 秒後に再試行するので…",
      q2: "auth timeout を上げる前に上流を確認…",
    },
    notes: {
      scan: "直近 7 日 · すべての Provider",
      chunk: "user / assistant 本文を分割して読み取り",
    },
    codexGuide: "Codex セッションを Markdown にエクスポート",
    uri: {
      label: "セッション URI はツールの scheme とセッション ID で構成されます",
    },
    demo: {
      days: "直近 30 日",
      provider: "Provider: すべて",
      role: "ロール: すべて",
      readDone: "完了",
      exportUser: "上流でときどき 504。auth timeout を 30 秒から 60 秒に上げる？",
      exportAssistant: "まだ変えないで。ログではトークン更新の段階でタイムアウトが集中…",
      collectStdout: "外部 Agent 向け指示 · 出力先 ./reports/weekly.md",
    },
    capabilities: {
      heading: "対話が終わったあとの、4つの使い方。",
      items: [
        {
          verb: "検索",
          body: "タイトル、メッセージ、推論、ツール状態を検索。Provider、プロジェクトパス、ロール、最近の更新で絞り込み。",
        },
        {
          verb: "閲覧",
          body: "ターミナルで閲覧、Session URI を開く、または Agent に JSON ページとカーソルで読ませる。",
        },
        {
          verb: "書き出し",
          body: "Markdown や JSON にエクスポート。文脈の書き出しには URI とメッセージ位置を残します。",
        },
        {
          verb: "集約",
          body: "対象本文を分割してすべて読み、外部 Agent 向けのレポート指示を生成。失敗は不完全として明示。",
        },
      ],
    },
    browse: {
      heading: "ターミナルで動くセッションリーダー。",
      autoplay: "自動デモ中 · クリックで操作",
      replay: "デモを再生",
      label: "agent-dump --browse の操作できるデモ（キーボード対応）",
      keysLabel: "デモのキー",
      space: "Space",
      keys: [
        "下へ",
        "上へ",
        "ペイン切替",
        "選択",
        "エクスポート",
        "セッション検索",
        "セッション内検索",
        "次のヒット",
        "抜粋",
        "ツール詳細",
        "検索をクリア",
        "ヘルプ",
      ],
    },
    audience: {
      headingLead: "人はターミナルで、",
      headingTail: "Agent は JSON で。",
      developer: {
        title: "先週の作業を3つのコマンドで",
        steps: ["直近1週間を閲覧", "このプロジェクトを検索", "URI でエクスポート"],
      },
      agent: {
        title: "検証できる完全な読み取り",
        body: "終了コードと status を確認。部分的な結果を完全な読み取りとして扱いません。",
        steps: ["機能とパス", "候補セッション", "ページング手順"],
      },
    },
    boundary: {
      heading: "セッションは読むだけ。データには触れない。",
      flow: {
        source: "Provider のセッション",
        sourceItems: ["データベース", "JSONL", "セッションディレクトリ"],
        owned: "agent-dump 管理下のパス",
        ownedItems: ["インデックス · 設定", "ログ", "エクスポート"],
      },
      note: {
        title: "不完全は不完全と示す",
        body: "読み取りや要約の失敗は明示され、不明な事実は不明のまま残ります。",
      },
    },
    updates: { latest: "最新", older: "以前のバージョン" },
    menu: "メニュー",
  },
};
