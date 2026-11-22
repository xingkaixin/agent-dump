---
layout: "../../../layouts/Guide.astro"
locale: "ja"
slug: "export-claude-code-conversations"
category: "export"
order: 2
updated: "2026-11-22"
title: "Claude Code セッションを Markdown・JSON にエクスポート"
description: "ローカルの Claude Code セッションや会話履歴を Markdown や構造化 JSON（トークン統計・メッセージ配列付き）で保存。一括エクスポートや履歴が見つからない時の確認方法も解説。"
---

Agent Dump を使うと、ローカルに保存された Claude Code CLI のセッションを Markdown や構造化 JSON ファイルとして書き出せます。Markdown はプロジェクトメモやレビュー記録に、JSON はスクリプト処理や集計に向いています。元の Claude Code セッション記録は変更されません（本ガイドはローカルの Claude Code CLI セッションを対象としており、claude.ai Web 版のデータエクスポートとは異なります）。

## インストールしてセッションを探す

Claude Code を実行したマシン上で操作します。npm と Node.js 22 以降がある場合：

```sh
npm install -g @agent-dump/cli
agent-dump --list --days 30 --query 'provider:claude'
```

[ネイティブバイナリ、Homebrew、Scoop、uv など他のインストール方法](/ja/#install)も利用できます。一覧表示は直近 30 日以内に更新されたセッションを抽出するため、作成が古くても最近再開した対話が含まれます。作成日時で絞り込む場合は `--time-field created` を追加してください。

タイトルと作業ディレクトリから対象の対話を確認し、完全な `claude://...` URI をコピーします。現在のプロジェクトだけに絞る場合は、プロジェクトディレクトリで実行します：

```sh
agent-dump --list --days 30 --query 'provider:claude path:.'
```

## 読みやすい Markdown としてエクスポート

`YOUR_SESSION_ID` を一覧の実際のセッション ID に置き換えて実行します：

```sh
agent-dump 'claude://YOUR_SESSION_ID' --format markdown --output ./exports
```

実行後に保存パスが表示されます。Markdown ファイルは現在の作業ディレクトリ配下の `./exports/claude/` に書き出されます。表示されたファイルをエディタで開けば内容を確認できます。これは持ち運び可能な対話記録であり、元の Agent プロセスや実行状態を再開するものではありません。

## 構造化 JSON も同時に残す

人間が読むメモと、スクリプト処理用の構造化データを一度に書き出せます：

```sh
agent-dump 'claude://YOUR_SESSION_ID' --format json,markdown --output ./exports
```

`--format json` は正規化された JSON ファイルを書き出します。セッションメタデータ（`id`、`title`、`directory`、`version`、`time_created`、`time_updated`）、集計 `stats`（`total_input_tokens`、`total_output_tokens`、`total_cost`、`message_count`）、および `messages` 配列（`role`、`model`、`time_created`、`tokens`、`cost`、構造化 `parts`）が含まれます。未加工の元ファイルが必要な場合は `--format raw` で `.raw.jsonl` をそのままコピーできます。

`--format json` はファイルへのエクスポートであり、検索や読み取りモードで標準出力へ構造化 JSON を出す `--json` とは別です。長い会話の一部だけをスクリプトで取得したい場合は、[bounded session reading（英語）](/guides/handoff-context-to-ai-agent/) を使ってページ単位で読み取ってください。

## 複数セッションをまとめてエクスポート

ターミナル上で対話的に複数セッションを選ぶ場合：

```sh
agent-dump --interactive --query 'provider:claude' --format markdown --output ./exports
```

画面の案内に従ってセッションを選択します。この操作には対話型ターミナルが必要です。自動化スクリプトで単一セッションを出力する場合は URI を直接指定してください。

## 履歴が見つからない場合

`agent-dump --providers` でデータソースが認識されているか確認し、古い対話なら `--days` を広げてください。Claude Code を実行したのと同じ OS アカウント・同じマシンで操作しているかも確認します。`path:.` は記録された作業ディレクトリと一致するセッションだけを返すため、除外されていないか外して試してください。

Agent Dump はローカル保存済みの履歴のみを読み取ります。リモートアカウントから取得したり、削除された元ファイルを復元したりはできません。エクスポートしたファイルを共有する前に、公開すべきでないプロジェクト情報が含まれていないか確認してください。

続けて [Search AI Coding History（英語）](/guides/search-ai-coding-history/) や [Save AI conversations to Obsidian（英語）](/guides/save-ai-conversations-to-obsidian/) も活用できます。
