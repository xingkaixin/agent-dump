---
layout: ../../../layouts/Guide.astro
slug: export-codex-session
category: export
order: 1
updated: "2026-11-24"
locale: ja
title: Codex セッションを Markdown・JSON にエクスポート
description: ローカルの Codex セッションを CLI 1コマンドで Markdown や JSON にエクスポート。セッション URI の確認手順、メモへのコピー方法、見つからない時の対処まで解説します。
---

Agent Dump を使うと、ローカルに保存された Codex の対話セッションを Markdown や JSON ファイルとしてエクスポートできます。CLI をインストールしてセッション一覧を確認し、実際のセッション URI を渡すだけです。元のセッションデータは変更されず、出力ファイルはエディタやメモアプリですぐに開けます。

## 1. Agent Dump をインストール

npm と Node.js 22 以降がある場合：

```sh
npm install -g @agent-dump/cli
agent-dump --version
```

uv を使う場合は `uv tool install agent-dump` を実行します。その他の方法は[インストール手順](/ja/#install)を参照してください。

以降のコマンドは、Codex のセッションが保存されているマシンおよびユーザーアカウントで実行してください。Agent Dump はローカル記録のみを読み取り、OpenAI アカウントから対話を取得しません。

## 2. セッション URI を探す

直近 30 日間の Codex セッションを一覧表示します：

```sh
agent-dump --list --days 30 --query "provider:codex"
```

タイトルと作業ディレクトリから対象の対話を見つけ、一覧に表示された完全な `codex://…` URI をコピーします。`codex://<session-id>` と `codex://threads/<session-id>` の両方に対応しています。

デフォルトの検索期間は 7 日間です。`--days 30` で対象期間を広げられます。一覧表示だけではファイルは出力されません。

## 3. Markdown にエクスポート

以下の `YOUR_SESSION_ID` を実際のセッション ID に置き換えるか、引用符内の URI 全体をコピーしたものに差し替えて実行します：

```sh
agent-dump "codex://YOUR_SESSION_ID" --format markdown --output ./exports
```

`YOUR_SESSION_ID` はプレースホルダーであり、実在するセッションではありません。実行すると出力ファイルのパスが表示されます。この出力先を指定した場合、現在のディレクトリを基準に `./exports/codex/<session-id>.md` へ書き出されます。

## 4. 出力ファイルを開く

表示された `.md` ファイルをエディタや Markdown メモアプリで開いて内容を確認します。`--output` を省略した場合、Markdown は `./sessions/codex/<session-id>.md` に保存されます。

スクリプト処理向けに JSON 形式で出力したり、1 回のコマンドで両方の形式を書き出したりすることもできます：

```sh
agent-dump "codex://YOUR_SESSION_ID" --format json,markdown --output ./exports
```

一覧表示とエクスポートはすべてローカルで完結し、AI API キーは不要です。エクスポートされるのは閲覧用の記録であり、実行中の Agent や環境、実行状態を復元するものではありません。

## Codex の対話を Markdown としてコピーできますか？

はい。`--format markdown` でセッションをエクスポートし、出力された `.md` ファイルをテキストエディタで開いてコピーすれば、Issue やドキュメント、新しい Agent への引き継ぎにそのまま貼り付けられます。このガイド上のコピーボタンはサンプルコマンドのみをコピーするため、実際のセッション URI に置き換えて実行してください。

ノート管理と組み合わせる場合は [Save AI conversations to Obsidian（英語）](/guides/save-ai-conversations-to-obsidian/)、長い会話から必要な箇所だけを引用付きで抜き出す場合は [Search AI Coding History（英語）](/guides/search-ai-coding-history/) を参照してください。

## セッションが見つからない場合

- 古いセッションの場合は `--days 90` のように対象期間を広げてください。
- `agent-dump --providers` を実行すると、セッションをスキャンせずに Codex のデータソースが認識されているか確認できます。
- 実行ユーザーアカウントと `CODEX_HOME` 環境変数を確認してください。Codex の探索順は `CODEX_HOME`、`~/.codex`、開発用フォールバック `data/codex` です。カスタム `CODEX_HOME` には個別ファイルではなく Codex のルートディレクトリを指定してください。
- 最新の一覧から完全な URI をコピーし、サンプルのプレースホルダーをそのまま実行しないようにしてください。
- セッション記録が別マシンにある場合は、そのマシン上でエクスポートしてください。削除済みまたはアクセス不能な元データは復元できません。

その他の出力形式やフィルタ条件は [CLI パラメータリファレンス](https://github.com/xingkaixin/agent-dump#full-parameter-reference) を参照してください。Claude Code 向けの手順は [Claude Code セッションのエクスポート](/ja/guides/export-claude-code-conversations/) にまとめています。
