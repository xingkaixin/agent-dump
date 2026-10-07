---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "weekly-report-from-ai-sessions"
category: "reports"
order: 5
updated: "2026-10-05"
title: "Create a work report from AI coding sessions"
description: "Turn saved AI coding conversations into a daily or weekly work report. Preview the session scope, use AI collect or a prompt handoff, and check coverage."
---

Agent Dump can collect saved coding conversations into a report of requested work, decisions, and reported results. Use it to prepare a daily note or weekly review, then verify the claims before sharing. A report summarizes dialogue; it does not independently verify that a change shipped.

Start with an [installed CLI](/#install) and locally available session records.

## Preview the report scope

Choose explicit dates so the report can be reproduced. These are example dates; replace them with your reporting period:

```sh
agent-dump --collect --since 2026-09-28 --until 2026-10-02 --query 'provider:codex,claude path:.' --dry-run
```

Run from the project directory. Dates include both endpoints and select visible text by its actual local date. Long sessions are split into daily units: this week’s text in an older session is included, while text outside the requested period is excluded. Text without a reliable timestamp is excluded; session dates are never substituted. Remove `path:.` if you want a report across projects.

Inspect the selected sources and any diagnostics before requesting summaries. A missing or unreadable source is a coverage gap, not proof that no work happened.

## Generate with your configured AI provider

Configure the `[ai]` section using `agent-dump --config`; see the [configuration reference](https://github.com/xingkaixin/agent-dump#collect-configuration-file). Then run:

```sh
agent-dump --collect --since 2026-09-28 --until 2026-10-02 --query 'provider:codex,claude path:.' --save ./reports/weekly.md
```

Unlike local search and export, AI collect sends selected conversation content to the configured model provider. Choose an appropriate provider for your project and review the scope first.

Collect processes eligible user and assistant text in chunks. It excludes system/developer messages, tool results, reasoning, and plan data. Sessions without eligible visible text are skipped. The default PM report groups work by date and known working directory; `--collect-mode insight` selects the alternate analysis mode. Built-in report instructions currently produce Chinese reports.

## Use an existing agent instead

You can generate a self-contained prompt without configuring an AI API key:

```sh
agent-dump --collect --emit-prompt --since 2026-09-28 --until 2026-10-02 --query 'provider:codex,claude path:.' --save ./reports/weekly.md
```

This prints a prompt containing a candidate manifest and reading instructions. `--save` names the eventual report; it does not save the prompt or run the report task. Give the complete prompt to an agent able to execute its commands in the original environment, and explicitly ask it to create the report.

The agent must validate the manifest, read the eligible conversation text to completion, and report missing sources. An empty prompt with exit code 0 means there were no candidates; there is nothing to summarize.

## Check the result

Open `./reports/weekly.md` and review its date range, source attribution, omitted sessions, and incomplete sections. Full input coverage does not guarantee that every detail survived summarization. Check important conclusions against the original sessions using [search and message context](/guides/search-ai-coding-history/).

For a durable project notebook, see [saving conversations to Obsidian](/guides/save-ai-conversations-to-obsidian/).
