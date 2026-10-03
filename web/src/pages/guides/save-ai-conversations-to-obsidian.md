---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "save-ai-conversations-to-obsidian"
category: "export"
order: 6
updated: "2026-10-03"
title: "Save AI conversations to an Obsidian vault"
description: "Keep Codex and Claude Code conversations as Markdown notes in Obsidian. Export to a dedicated vault folder, preserve useful context, and understand archive limits."
---

Agent Dump exports supported AI coding sessions as ordinary Markdown files. Point the output directory at a dedicated folder inside your Obsidian vault, and those files become notes you can open, link, and search. No Obsidian plugin is required for this workflow.

This is a manual export workflow, not continuous synchronization. Use it for a discussion worth keeping, a debugging explanation, or a project handoff.

## Find the conversation to keep

After [installing Agent Dump](/#install), list recent sessions:

```sh
agent-dump --list --days 30 --query 'provider:codex,claude'
```

Copy the URI from the matching entry. If you remember only the subject, [search the conversation text](/guides/search-ai-coding-history/) first. Run the CLI on the machine where the original session is stored.

## Export to a dedicated vault folder

Replace both the session ID and the example vault path. The following path is a macOS/Linux example:

```sh
agent-dump 'codex://YOUR_SESSION_ID' --format markdown --output '/path/to/Your Vault/AI Sessions'
```

Quote paths containing spaces. On Windows, use your actual path, such as `C:\Notes\My Vault\AI Sessions`. The output directory must be writable. Choose a folder you own, separate from the AI tool's session-source directory.

Exports are grouped by source tool. For Codex, look for `AI Sessions/codex/<session-id>.md` inside the vault. For Claude Code, use the `claude://...` URI; its Markdown files go under `AI Sessions/claude/`. The CLI prints the exact saved path.

## Add your own project note

Open the exported file in Obsidian. Keep your own decisions and follow-up tasks in a separate note and link to the export. That separates the original conversation record from your interpretation and avoids relying on an export file as your editable project plan.

Re-exporting the same session uses the same destination filename. Keep edits you want to preserve in a separate note, or use a new output directory for another snapshot. The export is not automatically updated when the source conversation continues.

## Keep only the relevant context

A full conversation can be long. Use [message locations and excerpt export](/guides/search-ai-coding-history/#keep-a-small-excerpt) when you only need the decision and nearby discussion. Excerpt files preserve the source URI and message range, which makes later verification easier.

For a readable summary across several conversations, generate a [work report](/guides/weekly-report-from-ai-sessions/) and save that report into the vault. Unlike a direct Markdown export, a report is a model-generated summary.

## Understand the archive limits

Markdown export is a readable transcript, not a backup of the original agent database, attachments, execution environment, or running task. Format support varies by provider: Cursor does not support Markdown export. Run `agent-dump --providers` to inspect available formats.

Review exported content before enabling vault sync or sharing notes. The export itself is local, but your vault's sync configuration controls where the saved files go afterward.
