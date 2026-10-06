import type { Locale } from "./i18n";

export type CapabilityCopy = { verb: string; label: string; body: string };

type LandingCopy = {
  nav: { browse: string; tools: string; faq: string };
  stage: {
    sources: string;
    sample: string;
    output: string;
    hits: string;
    untouched: string;
    handoff: string;
  };
  sample: { s1: string; s2: string; s3: string; q1: string; q2: string };
  notes: {
    search: string;
    read: string;
    scan: string;
    chunk: string;
    prompt: string;
    collect: string;
  };
  codexGuide: string;
  capabilities: {
    heading: string;
    summary: string;
    items: [CapabilityCopy, CapabilityCopy, CapabilityCopy, CapabilityCopy];
  };
  browse: {
    heading: string;
    summary: string;
    autoplay: string;
    replay: string;
    label: string;
    keysLabel: string;
    note: string;
    keys: string[];
  };
  audience: {
    headingLead: string;
    headingTail: string;
    developer: {
      tag: string;
      title: string;
      body: string;
      steps: [string, string, string];
    };
    agent: {
      tag: string;
      title: string;
      body: string;
      steps: [string, string, string];
    };
  };
  boundary: {
    tag: string;
    heading: string;
    items: { title: string; body: string }[];
  };
  updates: { latest: string; older: string };
  menu: string;
};

export const landing: Record<Locale, LandingCopy> = {
  en: {
    nav: { browse: "Browse", tools: "Tools", faq: "FAQ" },
    stage: {
      sources: "Sources · read-only",
      sample: "agent-dump · sample output",
      output: "Output",
      hits: "3 sessions · 7 hits · locators kept",
      untouched: "source untouched",
      handoff: "weekly.md handoff",
    },
    sample: {
      s1: "Fix login timeout retry",
      s2: "Gateway timeout config review",
      s3: "Session refresh logic",
      q1: "auth timeout retries after 30s, so we need…",
      q2: "Before raising auth timeout, confirm upstream…",
    },
    notes: {
      search:
        "Searches titles, messages, reasoning, and tool state · filter by Provider / path / role",
      read: "Bounded pages + cursors; reading ends only at has_more=false",
      scan: "last 7 days · all Providers",
      chunk: "user / assistant text, read in chunks",
      prompt: "external Agent instructions → stdout",
      collect: "No API setup · any failed read is marked incomplete",
    },
    codexGuide: "Export a Codex session to Markdown",
    capabilities: {
      heading: "Four moves for everything after the chat ends.",
      summary:
        "Recover a decision, read the full discussion, export it with sources, and hand it off complete. Output below is from sample sessions.",
      items: [
        {
          verb: "Find",
          label: "Recover the decision",
          body: "Search titles, messages, reasoning, and tool state. Filter by Provider, project path, role, or recent activity.",
        },
        {
          verb: "Read",
          label: "Read it in context",
          body: "Browse in the terminal, open a Session URI, or give an Agent bounded JSON pages with cursors.",
        },
        {
          verb: "Export",
          label: "Reuse with sources",
          body: "Export to Markdown or JSON. Context exports keep the URI and message locators.",
        },
        {
          verb: "Collect",
          label: "Full coverage, then hand off",
          body: "Read every eligible message in chunks and emit report instructions for an external Agent. Failures are marked incomplete.",
        },
      ],
    },
    browse: {
      heading: "A session reader in your terminal.",
      summary:
        "Sessions on the left, the transcript on the right. Search sessions, find text in one, preview matching excerpts, and mark sessions for batch export without leaving the terminal. The demo is live: click into it and use your keyboard, or press the keys below.",
      autoplay: "Auto demo · click the terminal to take over",
      replay: "Replay demo",
      label: "Interactive agent-dump --browse demo, keyboard operable",
      keysLabel: "Demo keys",
      note: "Sample sessions · layout, keys, and status text match the CLI",
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
        tag: "For developers",
        title: "Three commands for last week's work",
        body: "Browse recently active sessions, search within this project, then export by URI.",
        steps: ["browse the last week", "search this project", "export by URI"],
      },
      agent: {
        tag: "For AI Agents",
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
      tag: "Data boundary",
      heading: "Reads your sessions. Never touches your data.",
      items: [
        {
          title: "Zero writes to sources",
          body: "Export, search, stats, and collect never modify databases, JSONL, or session directories.",
        },
        {
          title: "Output stays in its own place",
          body: "Indexes, config, logs, and exports go only to paths agent-dump owns.",
        },
        {
          title: "Incomplete says incomplete",
          body: "Failed reads or summaries are marked; unknown facts stay unknown.",
        },
      ],
    },
    updates: { latest: "Latest", older: "Earlier releases" },
    menu: "Navigation menu",
  },
  zh: {
    nav: { browse: "会话阅读器", tools: "支持工具", faq: "常见问题" },
    stage: {
      sources: "来源 · 只读",
      sample: "agent-dump · 示例输出",
      output: "输出",
      hits: "3 sessions · 7 hits · 保留消息定位",
      untouched: "源会话未改动",
      handoff: "weekly.md 交接",
    },
    sample: {
      s1: "修复登录超时重试",
      s2: "网关超时配置梳理",
      s3: "会话刷新逻辑",
      q1: "auth timeout 在 30s 后触发重试，需要…",
      q2: "提高 auth timeout 之前先确认上游…",
    },
    notes: {
      search: "搜索标题、消息、推理与工具状态 · 按 Provider / 路径 / 角色筛选",
      read: "有界分页 + 游标，读到 has_more=false 才算读完",
      scan: "最近 7 天 · 全部 Provider",
      chunk: "user / assistant 正文，按块读取",
      prompt: "外部 Agent 指令 → stdout",
      collect: "无需配置 API · 任何读取失败都会标记为不完整",
    },
    codexGuide: "将 Codex 会话导出为 Markdown",
    capabilities: {
      heading: "四个动作，覆盖一段对话的后半生。",
      summary:
        "找回当时的决策，读懂完整讨论，带着来源导出，再完整地交给下一次工作。下面的输出为示例会话。",
      items: [
        {
          verb: "查找",
          label: "找回当时的决策",
          body: "搜索标题、消息、推理与工具状态，按 Provider、项目路径、角色或最近活动筛选。",
        },
        {
          verb: "阅读",
          label: "在上下文里读",
          body: "在终端浏览，打开 Session URI，或让 Agent 用有界 JSON 分页和游标读取。",
        },
        {
          verb: "导出",
          label: "带着来源复用",
          body: "导出为 Markdown 或 JSON；上下文片段保留 URI 与消息定位。",
        },
        {
          verb: "汇总",
          label: "完整覆盖再交接",
          body: "分块读取全部符合条件的正文，生成给外部 Agent 的报告指令。失败会标记为不完整。",
        },
      ],
    },
    browse: {
      heading: "终端里的会话阅读器。",
      summary:
        "左边是会话，右边是正文。搜索会话、在会话内查找、预览命中摘录、标记后批量导出，都不离开终端。下面的演示可以操作：点进终端用键盘，或点下方按键。",
      autoplay: "自动演示中 · 点击终端接管",
      replay: "重播演示",
      label: "agent-dump --browse 交互演示，可用键盘操作",
      keysLabel: "演示按键",
      note: "示例会话 · 界面布局、按键和提示文案与 CLI 一致",
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
        tag: "给开发者",
        title: "三条命令找回上周的工作",
        body: "浏览最近活跃的会话，在当前项目里搜索，再用 URI 导出。",
        steps: ["浏览最近一周", "在当前项目里搜索", "按 URI 导出"],
      },
      agent: {
        tag: "给 AI Agent",
        title: "可验证的完整读取",
        body: "检查退出码和 status；部分结果不会被当成完整读取。",
        steps: ["能力与路径", "候选会话", "分页指令"],
      },
    },
    boundary: {
      tag: "数据边界",
      heading: "只读你的会话，不碰你的数据。",
      items: [
        {
          title: "源数据零写入",
          body: "导出、搜索、统计和 collect 都不会修改数据库、JSONL 或会话目录。",
        },
        {
          title: "产物写在自己的地方",
          body: "索引、配置、日志和导出文件只进入 agent-dump 拥有的路径。",
        },
        {
          title: "不完整就说不完整",
          body: "读取或摘要失败会被明确标记；未知的事实保持未知。",
        },
      ],
    },
    updates: { latest: "最新版本", older: "更早版本" },
    menu: "导航菜单",
  },
  ja: {
    nav: { browse: "閲覧", tools: "対応ツール", faq: "よくある質問" },
    stage: {
      sources: "読み取り元 · 読み取り専用",
      sample: "agent-dump · サンプル出力",
      output: "出力",
      hits: "3 sessions · 7 hits · 位置情報を保持",
      untouched: "元セッションは変更なし",
      handoff: "weekly.md 引き継ぎ",
    },
    sample: {
      s1: "ログインのタイムアウト再試行を修正",
      s2: "ゲートウェイのタイムアウト設定",
      s3: "セッション更新ロジック",
      q1: "auth timeout は 30 秒後に再試行するので…",
      q2: "auth timeout を上げる前に上流を確認…",
    },
    notes: {
      search:
        "タイトル、メッセージ、推論、ツール状態を検索 · Provider / パス / ロールで絞り込み",
      read: "上限付きページ + カーソル。has_more=false まで読んで完了",
      scan: "直近 7 日 · すべての Provider",
      chunk: "user / assistant 本文を分割して読み取り",
      prompt: "外部 Agent 向け指示 → stdout",
      collect: "API 設定不要 · 読み取りの失敗は不完全として明示",
    },
    codexGuide: "Codex セッションを Markdown にエクスポート（英語）",
    capabilities: {
      heading: "対話が終わったあとの、4つの使い方。",
      summary:
        "判断を見つけ、議論を読み、出典付きで書き出し、漏れなく引き継ぐ。以下はサンプルセッションの出力です。",
      items: [
        {
          verb: "検索",
          label: "当時の判断を探す",
          body: "タイトル、メッセージ、推論、ツール状態を検索。Provider、プロジェクトパス、ロール、最近の更新で絞り込み。",
        },
        {
          verb: "閲覧",
          label: "文脈ごと読む",
          body: "ターミナルで閲覧、Session URI を開く、または Agent に JSON ページとカーソルで読ませる。",
        },
        {
          verb: "書き出し",
          label: "出典付きで再利用",
          body: "Markdown や JSON にエクスポート。文脈の書き出しには URI とメッセージ位置を残します。",
        },
        {
          verb: "集約",
          label: "すべて読んでから引き継ぐ",
          body: "対象本文を分割してすべて読み、外部 Agent 向けのレポート指示を生成。失敗は不完全として明示。",
        },
      ],
    },
    browse: {
      heading: "ターミナルで動くセッションリーダー。",
      summary:
        "左にセッション、右に本文。セッション検索、セッション内の検索、ヒットした抜粋のプレビュー、まとめてエクスポートまで、ターミナルから離れずに操作できます。下のデモは操作できます。クリックしてキーボードで、または下のキーを押してください。",
      autoplay: "自動デモ中 · クリックで操作",
      replay: "デモを再生",
      label: "agent-dump --browse の操作できるデモ（キーボード対応）",
      keysLabel: "デモのキー",
      note: "サンプルのセッション · CLI の表示は英語または中国語です",
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
        tag: "開発者向け",
        title: "先週の作業を3つのコマンドで",
        body: "最近更新されたセッションを閲覧し、このプロジェクト内を検索して、URI でエクスポート。",
        steps: ["直近1週間を閲覧", "このプロジェクトを検索", "URI でエクスポート"],
      },
      agent: {
        tag: "AI Agent 向け",
        title: "検証できる完全な読み取り",
        body: "終了コードと status を確認。部分的な結果を完全な読み取りとして扱いません。",
        steps: ["機能とパス", "候補セッション", "ページング手順"],
      },
    },
    boundary: {
      tag: "データの境界",
      heading: "セッションは読むだけ。データには触れない。",
      items: [
        {
          title: "元データへの書き込みゼロ",
          body: "エクスポート、検索、統計、collect はデータベース、JSONL、セッションディレクトリを変更しません。",
        },
        {
          title: "生成物は専用の場所へ",
          body: "インデックス、設定、ログ、エクスポートは agent-dump 管理下のパスにのみ書き込みます。",
        },
        {
          title: "不完全は不完全と示す",
          body: "読み取りや要約の失敗は明示され、不明な事実は不明のまま残ります。",
        },
      ],
    },
    updates: { latest: "最新", older: "以前のバージョン" },
    menu: "メニュー",
  },
};
