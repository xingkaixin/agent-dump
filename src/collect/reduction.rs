use crate::collect::log::Logger;
use crate::collect::model::{Entry, Group, Mode, Summary};
use crate::collect::pool;
use crate::collect::progress::progress;
use crate::collect::summary::{self as collect_summary, Context};
use agent_dump_core::config::{AiConfig, CollectConfig};
use agent_dump_core::output::i18n::{t, terminal};
use serde_json::json;
use std::collections::{HashMap, VecDeque};
use std::io::Write;

enum Job {
    Chunk(usize, usize),
    Merge(usize, usize, Vec<Summary>),
}

struct Session {
    slots: Vec<Option<Summary>>,
    merging: bool,
    failed: bool,
}

impl Session {
    fn advance(
        &mut self,
        entry: usize,
        queue: &mut VecDeque<Job>,
    ) -> Option<Summary> {
        let payloads: Vec<_> = std::mem::take(&mut self.slots)
            .into_iter()
            .flatten()
            .collect();
        if self.merging && payloads.len() == 1 {
            return payloads.into_iter().next();
        }
        self.merging = true;
        let batches: Vec<_> = payloads.chunks(8).map(<[_]>::to_vec).collect();
        self.slots = vec![None; batches.len()];
        for (index, batch) in batches.into_iter().enumerate().rev() {
            queue.push_front(Job::Merge(entry, index, batch));
        }
        None
    }
}

fn summarize_chunk(
    entry: &Entry,
    index: usize,
    ai: &AiConfig,
    timeout: u64,
    mode: Mode,
    logger: &Logger,
) -> crate::Result<Summary> {
    let uri = entry.uri();
    collect_summary::request(
        ai,
        &crate::collect::prompts::chunk(
            entry,
            &entry.chunks[index],
            index,
            mode,
        ),
        timeout,
        mode,
        &Context {
            label: format!("{uri} chunk {}/{}", index + 1, entry.chunks.len()),
            phase: "chunk_summary",
            uri: Some(&uri),
            chunk: Some(index + 1),
            chunks: Some(entry.chunks.len()),
        },
        logger,
    )
}

fn merge_session(
    entry: &Entry,
    payloads: &[Summary],
    ai: &AiConfig,
    timeout: u64,
    mode: Mode,
    logger: &Logger,
) -> crate::Result<Summary> {
    let uri = entry.uri();
    let mut merged = collect_summary::merge(payloads, mode);
    if payloads.len() > 1 && collect_summary::needs_compression(&merged) {
        let prompt =
            crate::collect::prompts::merge(&uri, payloads, "session", mode);
        if prompt.chars().count() > 64_000 {
            return Err(format!(
                "{uri}: session merge input exceeds 64000 characters"
            )
            .into());
        }
        match collect_summary::request(
            ai,
            &prompt,
            timeout,
            mode,
            &Context {
                label: format!("{uri} session merge"),
                phase: "session_merge",
                uri: Some(&uri),
                chunk: None,
                chunks: Some(entry.chunks.len()),
            },
            logger,
        ) {
            Ok(summary) => merged = summary,
            Err(error) => logger.log(
                "llm_merge_fallback",
                json!({
                    "phase": "session_merge",
                    "session_uri": uri,
                    "chunk_total": entry.chunks.len(),
                    "error": error.to_string()
                }),
            ),
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
) -> crate::Result<(Vec<Group>, usize, Vec<String>)> {
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
    let mut sessions: Vec<_> = entries
        .iter()
        .map(|entry| Session {
            slots: vec![None; entry.chunks.len()],
            merging: false,
            failed: false,
        })
        .collect();
    let queue = entries
        .iter()
        .enumerate()
        .flat_map(|(entry, e)| {
            (0..e.chunks.len()).map(move |index| Job::Chunk(entry, index))
        })
        .collect();
    let mut results = vec![None; entries.len()];
    let mut failed = Vec::new();
    let mut last_error = None;
    let mut chunks = 0;
    let mut merged = 0;
    pool::run(
        config.concurrency,
        queue,
        |job| match job {
            Job::Chunk(entry, index) => (
                entry,
                index,
                true,
                summarize_chunk(
                    &entries[entry],
                    index,
                    ai,
                    config.timeout,
                    mode,
                    logger,
                ),
            ),
            Job::Merge(entry, index, payloads) => (
                entry,
                index,
                false,
                merge_session(
                    &entries[entry],
                    &payloads,
                    ai,
                    config.timeout,
                    mode,
                    logger,
                ),
            ),
        },
        |(entry, index, chunk, result), queue| {
            let session = &mut sessions[entry];
            if session.failed {
                return Ok(());
            }
            match result {
                Ok(summary) => {
                    session.slots[index] = Some(summary);
                    if chunk {
                        chunks += 1;
                        progress(
                            "COLLECT_PROGRESS_SUMMARIZE_CHUNKS",
                            &chunk_values(chunks),
                            zh,
                            warnings,
                        )?;
                    }
                    if session.slots.iter().all(Option::is_some)
                        && let Some(summary) = session.advance(entry, queue)
                    {
                        results[entry] = Some(summary);
                        merged += 1;
                        progress(
                            "COLLECT_PROGRESS_MERGE_SESSIONS",
                            &session_values(merged),
                            zh,
                            warnings,
                        )?;
                    }
                }
                Err(error) => {
                    session.failed = true;
                    queue.retain(|job| {
                        !matches!(job, Job::Chunk(i, _) | Job::Merge(i, ..) if *i == entry)
                    });
                    let uri = entries[entry].uri();
                    failed.push(uri.clone());
                    writeln!(
                        warnings,
                        "{}",
                        terminal(
                            "WARN_SESSION_SUMMARY_SKIPPED",
                            zh,
                            &[
                                ("uri", uri.clone()),
                                ("error", error.to_string())
                            ]
                        )
                    )?;
                    logger.log(
                        "session_summary_failed",
                        json!({"session_uri":uri, "error":error.to_string()}),
                    );
                    last_error = Some(error);
                }
            }
            Ok(())
        },
    )?;
    let included = entries.len() - failed.len();
    if included == 0
        && let Some(error) = last_error
    {
        return Err(error);
    }
    failed.sort();
    failed.dedup();
    if !failed.is_empty() {
        writeln!(
            warnings,
            "{}",
            t(
                "WARN_SESSION_SUMMARY_FAILURES",
                zh,
                &[("count", failed.len().to_string())]
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
            let scope = if mode == Mode::Insight
                || group.project_directory.is_empty()
            {
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
                let payloads: Vec<_> =
                    batch.iter().map(|g| g.summary.clone()).collect();
                let mut merged = collect_summary::merge(&payloads, mode);
                let index = next.len() + 1;
                let source =
                    format!("collect://group-level-{depth}/group-{index}");
                if batch.len() > 1
                    && collect_summary::needs_compression(&merged)
                {
                    match collect_summary::request(
                        ai,
                        &crate::collect::prompts::merge(
                            &source,
                            &payloads,
                            &format!("group-level-{depth}"),
                            mode,
                        ),
                        config.timeout,
                        mode,
                        &Context {
                            label: source.clone(),
                            phase: "group_merge",
                            uri: None,
                            chunk: None,
                            chunks: None,
                        },
                        logger,
                    ) {
                        Ok(summary) => merged = summary,
                        Err(error) => logger.log(
                            "llm_merge_fallback",
                            json!({
                                "phase": "group_merge",
                                "context": source,
                                "level": depth,
                                "group_index": index,
                                "error": error.to_string()
                            }),
                        ),
                    }
                }
                next.push(Group {
                    date: batch[0].date.clone(),
                    project_directory: batch[0].project_directory.clone(),
                    session_uris: batch
                        .iter()
                        .flat_map(|g| g.session_uris.clone())
                        .collect(),
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
    Ok((working, depth, failed))
}
