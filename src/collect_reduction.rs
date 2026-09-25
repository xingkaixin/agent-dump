use crate::collect_log::Logger;
use crate::collect_model::{Entry, Group, Mode, Summary};
use crate::collect_progress::progress;
use crate::collect_summary::{self, Context};
use crate::config::{AiConfig, CollectConfig};
use serde_json::json;
use std::collections::HashMap;
use std::io::Write;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    mpsc,
};

enum Event {
    Chunk,
    Complete(usize, crate::Result<Summary>),
}

fn summarize(
    entry: &Entry,
    ai: &AiConfig,
    timeout: u64,
    mode: Mode,
    logger: &Logger,
    sender: &mpsc::Sender<Event>,
) -> crate::Result<Summary> {
    let uri = entry.uri();
    let mut payloads = Vec::new();
    for (index, chunk) in entry.chunks.iter().enumerate() {
        payloads.push(collect_summary::request(
            ai,
            &crate::collect_prompts::chunk(entry, chunk, index, mode),
            timeout,
            mode,
            Context {
                label: format!("{uri} chunk {}/{}", index + 1, entry.chunks.len()),
                phase: "chunk_summary",
                uri: Some(&uri),
                chunk: Some(index + 1),
                chunks: Some(entry.chunks.len()),
            },
            logger,
        )?);
        let _ = sender.send(Event::Chunk);
    }
    let mut merged = collect_summary::merge(&payloads, mode);
    if payloads.len() > 1 && collect_summary::needs_compression(&merged) {
        match collect_summary::request(ai, &crate::collect_prompts::merge(&uri, &payloads, "session", mode), timeout, mode, Context {
            label: format!("{uri} session merge"), phase: "session_merge", uri: Some(&uri), chunk: None, chunks: Some(entry.chunks.len()),
        }, logger) {
            Ok(summary) => merged = summary,
            Err(error) => logger.log("llm_merge_fallback", json!({"phase":"session_merge", "session_uri":uri, "chunk_total":entry.chunks.len(), "error":error.to_string()})),
        }
    }
    Ok(merged)
}

pub fn run(
    entries: &[Entry],
    ai: &AiConfig,
    config: &CollectConfig,
    mode: Mode,
    logger: &Logger,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<(Vec<Group>, usize, usize)> {
    let total_chunks: usize = entries.iter().map(|e| e.chunks.len()).sum();
    let chunk_values = |count: usize| {
        [
            ("current", count.to_string()),
            ("total", total_chunks.to_string()),
            ("concurrency", config.concurrency.to_string()),
        ]
    };
    let session_values = |count: usize| {
        [
            ("current", count.to_string()),
            ("total", entries.len().to_string()),
        ]
    };
    progress(
        "COLLECT_PROGRESS_SUMMARIZE_CHUNKS",
        &chunk_values(0),
        zh,
        warnings,
    )?;
    progress(
        "COLLECT_PROGRESS_MERGE_SESSIONS",
        &session_values(0),
        zh,
        warnings,
    )?;
    let (sender, receiver) = mpsc::channel();
    let next = AtomicUsize::new(0);
    let mut results = vec![None; entries.len()];
    let mut failed = 0;
    let mut last_error = None;
    std::thread::scope(|scope| -> crate::Result<()> {
        for _ in 0..config.concurrency.min(entries.len()) {
            let sender = sender.clone();
            let next = &next;
            scope.spawn(move || {
                loop {
                    let index = next.fetch_add(1, Ordering::Relaxed);
                    let Some(entry) = entries.get(index) else {
                        break;
                    };
                    let result = summarize(entry, ai, config.timeout, mode, logger, &sender);
                    if sender.send(Event::Complete(index, result)).is_err() {
                        break;
                    }
                }
            });
        }
        drop(sender);
        let mut chunks = 0;
        let mut merged = 0;
        for event in receiver {
            match event {
                Event::Chunk => {
                    chunks += 1;
                    progress(
                        "COLLECT_PROGRESS_SUMMARIZE_CHUNKS",
                        &chunk_values(chunks),
                        zh,
                        warnings,
                    )?;
                }
                Event::Complete(index, Ok(summary)) => {
                    results[index] = Some(summary);
                    merged += 1;
                    progress(
                        "COLLECT_PROGRESS_MERGE_SESSIONS",
                        &session_values(merged),
                        zh,
                        warnings,
                    )?;
                }
                Event::Complete(index, Err(error)) => {
                    failed += 1;
                    let uri = entries[index].uri();
                    writeln!(
                        warnings,
                        "{}",
                        crate::i18n::terminal(
                            "WARN_SESSION_SUMMARY_SKIPPED",
                            zh,
                            &[("uri", uri.clone()), ("error", error.to_string())]
                        )
                    )?;
                    logger.log(
                        "session_summary_failed",
                        json!({"session_uri":uri, "error":error.to_string()}),
                    );
                    last_error = Some(error);
                }
            }
        }
        Ok(())
    })?;
    let included = entries.len() - failed;
    if included == 0
        && let Some(error) = last_error
    {
        return Err(error);
    }
    if failed > 0 {
        writeln!(
            warnings,
            "{}",
            crate::i18n::t(
                "WARN_SESSION_SUMMARY_FAILURES",
                zh,
                &[("count", failed.to_string())]
            )
        )?;
    }
    progress(
        "COLLECT_PROGRESS_RENDER_FINAL",
        &[("current", "0".into()), ("total", "2".into())],
        zh,
        warnings,
    )?;
    let mut working: Vec<Group> = entries
        .iter()
        .zip(results)
        .filter_map(|(entry, summary)| {
            summary.map(|summary| Group {
                date: entry.date.to_string(),
                project_directory: entry.session.working_directory(),
                session_uris: vec![entry.uri()],
                summary,
            })
        })
        .collect();
    let mut depth = 0;
    loop {
        let mut buckets: Vec<Vec<Group>> = Vec::new();
        let mut positions = HashMap::new();
        for group in &working {
            let scope = if mode == Mode::Insight || group.project_directory.is_empty() {
                group.session_uris[0].as_str()
            } else {
                ""
            };
            let key = (&group.date, &group.project_directory, scope);
            let index = *positions.entry(key).or_insert_with(|| {
                buckets.push(Vec::new());
                buckets.len() - 1
            });
            buckets[index].push(group.clone());
        }
        if buckets.len() == working.len() {
            break;
        }
        depth += 1;
        let total: usize = buckets.iter().map(|b| b.len().div_ceil(8)).sum();
        let values = |current: usize| {
            [
                ("level", depth.to_string()),
                ("current", current.to_string()),
                ("total", total.to_string()),
            ]
        };
        progress("COLLECT_PROGRESS_TREE_REDUCTION", &values(0), zh, warnings)?;
        let mut next = Vec::new();
        for bucket in buckets {
            for batch in bucket.chunks(8) {
                let payloads: Vec<_> = batch.iter().map(|g| g.summary.clone()).collect();
                let mut merged = collect_summary::merge(&payloads, mode);
                let index = next.len() + 1;
                let source = format!("collect://group-level-{depth}/group-{index}");
                if batch.len() > 1 && collect_summary::needs_compression(&merged) {
                    match collect_summary::request(ai, &crate::collect_prompts::merge(&source, &payloads, &format!("group-level-{depth}"), mode), config.timeout, mode, Context { label:source.clone(), phase:"group_merge", uri:None, chunk:None, chunks:None }, logger) {
                        Ok(summary) => merged = summary,
                        Err(error) => logger.log("llm_merge_fallback", json!({"phase":"group_merge", "context":source,"level":depth,"group_index":index,"error":error.to_string()})),
                    }
                }
                next.push(Group {
                    date: batch[0].date.clone(),
                    project_directory: batch[0].project_directory.clone(),
                    session_uris: batch.iter().flat_map(|g| g.session_uris.clone()).collect(),
                    summary: merged,
                });
                progress(
                    "COLLECT_PROGRESS_TREE_REDUCTION",
                    &values(index),
                    zh,
                    warnings,
                )?;
            }
        }
        working = next;
    }
    progress(
        "COLLECT_PROGRESS_RENDER_FINAL",
        &[("current", "1".into()), ("total", "2".into())],
        zh,
        warnings,
    )?;
    Ok((working, depth, included))
}
