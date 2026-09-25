use crate::collect_model::{Action, Operation};
use crate::config::Config;
use crate::i18n::{t, terminal};
use crate::scanner::Scan;
use jiff::civil::Date;
use serde_json::json;
use std::collections::BTreeMap;
use std::io::Write;
use std::path::{Path, PathBuf};

use crate::collect_progress::progress;

fn report(
    message: &str,
    emit: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<()> {
    if emit {
        writeln!(warnings, "{message}")?;
    } else {
        writeln!(out, "{message}")?;
    }
    Ok(())
}

pub fn save_path(save: Option<&str>, since: Date, until: Date) -> crate::Result<PathBuf> {
    let filename = format!(
        "agent-dump-collect-{}-{}.md",
        since.strftime("%Y%m%d"),
        until.strftime("%Y%m%d")
    );
    let Some(save) = save else {
        return Ok(std::env::current_dir()?.join(filename));
    };
    let path = PathBuf::from(save);
    if path.exists() {
        return Ok(if path.is_dir() {
            path.join(filename)
        } else {
            path
        });
    }
    Ok(
        if path
            .extension()
            .is_some_and(|suffix| suffix.eq_ignore_ascii_case("md"))
        {
            path
        } else {
            path.join(filename)
        },
    )
}

fn guard_output(path: &Path, scan: &Scan) -> crate::Result<()> {
    let path = crate::query::project_path(&crate::source_io::path_text(path))?;
    for group in &scan.groups {
        let source =
            crate::query::project_path(&crate::source_io::path_text(group.provider.source_root()))?;
        if path.starts_with(source) {
            return Err("Collect output must be outside the Provider source directory".into());
        }
    }
    Ok(())
}

pub fn run(
    operation: Operation,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<bool> {
    let emit = matches!(operation.action, Action::EmitPrompt);
    let (since, until) = match crate::date_input::collect_range(
        operation.since.as_deref(),
        operation.until.as_deref(),
        operation.days,
        zh,
    ) {
        Ok(dates) => dates,
        Err(error) => {
            report(&error.to_string(), emit, out, warnings)?;
            return Ok(false);
        }
    };
    let config = match Config::load().and_then(|config| {
        config.validate_collect()?;
        Ok(config)
    }) {
        Ok(config) => config,
        Err(error) => {
            report(
                &terminal("COLLECT_CONFIG_UNSAFE", zh, &[("field", error.to_string())]),
                emit,
                out,
                warnings,
            )?;
            return Ok(false);
        }
    };
    let ai = if matches!(operation.action, Action::Execute) {
        let ai = config.ai();
        let errors = crate::config::validate_ai(ai.as_ref(), config.exists);
        if !errors.is_empty() {
            writeln!(out, "{}", crate::config::collect_ai_error(&errors, zh))?;
            return Ok(false);
        }
        ai
    } else {
        None
    };
    let collect = config.collect();
    progress(
        "COLLECT_PROGRESS_START",
        &[("since", since.to_string()), ("until", until.to_string())],
        zh,
        warnings,
    )?;
    let scan_days = (jiff::Zoned::now()
        .date()
        .since((jiff::Unit::Day, since))?
        .get_days()
        + 1)
    .max(1);
    let mut scan =
        crate::scanner::discover(operation.query.as_ref(), i64::from(scan_days), zh, warnings)?;
    if scan.groups.is_empty()
        && operation
            .query
            .as_ref()
            .is_none_or(|q| q.providers.is_none())
    {
        report(&t("NO_AGENTS_FOUND", zh, &[]), emit, out, warnings)?;
        return Ok(false);
    }
    for group in &mut scan.groups {
        let denied: Vec<_> = collect
            .denies
            .get(group.info.name)
            .into_iter()
            .flatten()
            .map(|path| crate::query::project_path(path))
            .collect::<crate::Result<_>>()?;
        group.sessions.retain(|session| {
            let date = Some(session.created_at.local_date());
            if date.is_none_or(|date| date < since || date > until) {
                return false;
            }
            let path = (!session.directory.trim().is_empty())
                .then(|| crate::query::project_path(&session.directory))
                .transpose()
                .ok()
                .flatten();
            !path.is_some_and(|path| denied.iter().any(|root| path.starts_with(root)))
        });
    }
    let selected = operation
        .query
        .as_ref()
        .map(|q| crate::query_filter::select(&scan.groups, q, zh, warnings))
        .transpose()?;
    let query_failures = selected.as_ref().map_or(0, |s| s.failures.len());
    let positions: Vec<_> = selected.map_or_else(
        || {
            scan.groups
                .iter()
                .enumerate()
                .flat_map(|(g, group)| (0..group.sessions.len()).map(move |s| (g, s)))
                .collect()
        },
        |s| s.matches.iter().map(|m| (m.group, m.session)).collect(),
    );
    let output_path = save_path(operation.save.as_deref(), since, until)?;
    if emit {
        if positions.is_empty() {
            report(
                &t(
                    "COLLECT_NO_SESSIONS",
                    zh,
                    &[("since", since.to_string()), ("until", until.to_string())],
                ),
                true,
                out,
                warnings,
            )?;
            return Ok(scan.failed_providers.is_empty() && query_failures == 0);
        }
        writeln!(
            out,
            "{}",
            crate::collect_handoff::handoff(
                &operation,
                &scan,
                &positions,
                since,
                until,
                &output_path,
                query_failures
            )?
        )?;
        return Ok(true);
    }
    let logger = if ai.is_some() {
        let logging = config.logging()?;
        if logging.enabled {
            guard_output(&logging.path, &scan)?;
        }
        Some(crate::collect_log::Logger::new(logging, zh))
    } else {
        None
    };
    let (entries, read_failed) = match crate::collect_sessions::read_entries(
        &scan,
        &positions,
        zh,
        warnings,
        logger.as_ref(),
    ) {
        Ok(result) => result,
        Err(error) => {
            if let Some(logger) = &logger {
                logger.log(
                    "collect_run_fail",
                    json!({"phase":"read", "error":error.to_string()}),
                );
            }
            writeln!(
                out,
                "{}",
                terminal("COLLECT_READ_FAILED", zh, &[("error", error.to_string())])
            )?;
            return Ok(false);
        }
    };
    if entries.is_empty() {
        writeln!(
            out,
            "{}",
            t(
                "COLLECT_NO_SESSIONS",
                zh,
                &[("since", since.to_string()), ("until", until.to_string())]
            )
        )?;
        return Ok(false);
    }
    if let Some(logger) = &logger {
        logger.log("collect_run_start", json!({"since":since.to_string(), "until":until.to_string(), "summary_concurrency":collect.concurrency, "agent_count":scan.groups.len(), "session_count":entries.len()}));
    }
    let mut count = 0;
    progress(
        "COLLECT_PROGRESS_PLAN_CHUNKS",
        &[
            ("current", "0".into()),
            ("total", entries.len().to_string()),
        ],
        zh,
        warnings,
    )?;
    let mut breakdown: serde_json::Map<String, serde_json::Value> = Default::default();
    for (i, entry) in entries.iter().enumerate() {
        count += entry.chunks.len();
        let total = breakdown
            .entry(entry.provider.display_name)
            .or_insert(0.into());
        *total = (total.as_u64().unwrap() + 1).into();
        let values = [
            ("current", (i + 1).to_string()),
            ("session_count", (i + 1).to_string()),
            ("total", entries.len().to_string()),
            ("chunk_count", count.to_string()),
        ];
        progress(
            if i + 1 == entries.len() {
                "COLLECT_PROGRESS_PLAN_CHUNKS_DONE"
            } else {
                "COLLECT_PROGRESS_PLAN_CHUNKS"
            },
            &values,
            zh,
            warnings,
        )?;
    }
    let values = [
        ("session_count", entries.len().to_string()),
        ("chunk_count", count.to_string()),
        ("concurrency", collect.concurrency.to_string()),
    ];
    let breakdown_text = breakdown
        .iter()
        .map(|(name, count)| format!("{name} {count}"))
        .collect::<Vec<_>>()
        .join(", ");
    writeln!(
        warnings,
        "{}",
        crate::render::safe_line(&format!(
            "{}\n{}",
            t("COLLECT_PROGRESS_OVERVIEW", zh, &values),
            t(
                "COLLECT_PROGRESS_AGENT_BREAKDOWN",
                zh,
                &[("breakdown", breakdown_text)]
            )
        ))
    )?;
    if matches!(operation.action, Action::DryRun) {
        let sorted: BTreeMap<_, _> = breakdown.iter().collect();
        let breakdown = sorted
            .iter()
            .map(|(name, count)| format!("{name} {count}"))
            .collect::<Vec<_>>()
            .join(", ");
        for (key, values) in [
            ("COLLECT_DRY_RUN_HEADER", vec![]),
            (
                "COLLECT_DRY_RUN_DATE_RANGE",
                vec![("since", since.to_string()), ("until", until.to_string())],
            ),
            (
                "COLLECT_DRY_RUN_PROVIDER_BREAKDOWN",
                vec![("breakdown", breakdown)],
            ),
            (
                "COLLECT_DRY_RUN_SESSION_COUNT",
                vec![("count", entries.len().to_string())],
            ),
            (
                "COLLECT_DRY_RUN_CHUNK_COUNT",
                vec![("count", count.to_string())],
            ),
            (
                "COLLECT_DRY_RUN_CONCURRENCY",
                vec![("concurrency", collect.concurrency.to_string())],
            ),
            (
                "COLLECT_DRY_RUN_SAVE_PATH",
                vec![("path", crate::source_io::path_text(&output_path))],
            ),
        ] {
            writeln!(out, "{}", terminal(key, zh, &values))?;
        }
        return Ok(true);
    }
    let logger = logger.as_ref().unwrap();
    let ai = ai.as_ref().unwrap();
    let (groups, depth, included) = match crate::collect_reduction::run(
        &entries,
        ai,
        &collect,
        operation.mode,
        logger,
        zh,
        warnings,
    ) {
        Ok(result) => result,
        Err(error) => {
            logger.log(
                "collect_run_fail",
                json!({"phase":"summarize", "error":error.to_string()}),
            );
            writeln!(
                out,
                "{}",
                terminal("COLLECT_API_FAILED", zh, &[("error", error.to_string())])
            )?;
            return Ok(false);
        }
    };
    let rendered = crate::collect_prompts::final_prompt(
        since,
        until,
        &groups,
        depth,
        entries.iter().any(|e| e.truncated),
        operation.mode,
        zh,
    )
    .and_then(|prompt| crate::llm::summary(ai, &prompt, collect.timeout));
    let mut markdown = match rendered {
        Ok(markdown) => markdown,
        Err(error) => {
            logger.log(
                "collect_run_fail",
                json!({"phase":"render", "error":error.to_string()}),
            );
            writeln!(
                out,
                "{}",
                terminal("COLLECT_API_FAILED", zh, &[("error", error.to_string())])
            )?;
            return Ok(false);
        }
    };
    progress(
        "COLLECT_PROGRESS_RENDER_FINAL",
        &[("current", "2".into()), ("total", "2".into())],
        zh,
        warnings,
    )?;
    let failed = read_failed + query_failures;
    let summary_failed = entries.len() - included;
    if failed + summary_failed > 0 {
        markdown = format!(
            "> {}\n\n{markdown}",
            t(
                "COLLECT_INCOMPLETE_REPORT",
                zh,
                &[
                    ("read_failed", failed.to_string()),
                    ("summary_failed", summary_failed.to_string()),
                    ("included", included.to_string())
                ]
            )
        );
    }
    if !scan.failed_providers.is_empty() {
        markdown = format!(
            "> {}\n\n{markdown}",
            t(
                "COLLECT_DISCOVERY_INCOMPLETE_REPORT",
                zh,
                &[("count", scan.failed_providers.len().to_string())]
            )
        );
    }
    progress(
        "COLLECT_PROGRESS_WRITE_OUTPUT",
        &[("current", "0".into()), ("total", "1".into())],
        zh,
        warnings,
    )?;
    let write = guard_output(&output_path, &scan)
        .and_then(|_| crate::private_files::write_text(&output_path, &markdown));
    if let Err(error) = write {
        logger.log(
            "collect_run_fail",
            json!({"phase":"write", "error":error.to_string()}),
        );
        writeln!(
            out,
            "{}",
            terminal("COLLECT_WRITE_FAILED", zh, &[("error", error.to_string())])
        )?;
        return Ok(false);
    }
    progress(
        "COLLECT_PROGRESS_WRITE_OUTPUT",
        &[("current", "1".into()), ("total", "1".into())],
        zh,
        warnings,
    )?;
    logger.log("collect_run_finish", json!({"output_path":crate::source_io::path_text(&output_path), "session_count":included, "read_failed_count":failed, "discovery_failed_count":scan.failed_providers.len(), "summary_failed_count":summary_failed}));
    writeln!(out, "{}", crate::render::safe_body(&markdown))?;
    writeln!(
        out,
        "{}",
        terminal(
            "COLLECT_OUTPUT_SAVED",
            zh,
            &[("path", crate::source_io::path_text(&output_path))]
        )
    )?;
    Ok(true)
}
