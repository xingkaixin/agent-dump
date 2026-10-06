use crate::collect::model::Entry;
use crate::collect::progress::progress;
use agent_dump_core::output::i18n::{t, terminal};
use agent_dump_core::query::scanner::Scan;
use serde_json::json;
use std::io::Write;

pub fn read_entries(
    scan: &Scan,
    positions: &[(usize, usize)],
    range: &std::ops::RangeInclusive<jiff::civil::Date>,
    plan_chunks: bool,
    zh: bool,
    warnings: &mut impl Write,
    logger: Option<&crate::collect::log::Logger>,
) -> crate::Result<(Vec<Entry>, Vec<String>, Vec<String>)> {
    progress(
        "COLLECT_PROGRESS_SCAN_SESSIONS",
        &[
            ("current", "0".into()),
            ("total", positions.len().to_string()),
        ],
        zh,
        warnings,
    )?;
    let mut entries = Vec::new();
    let mut failed = Vec::new();
    let mut undated = Vec::new();
    let mut last_error = None;
    let mut completed = 0;
    agent_dump_core::parallel::ordered(
        positions,
        |&(g, s)| {
            let group = &scan.groups[g];
            let session = &group.sessions[s];
            let mut diagnostics = Vec::new();
            let result = group
                .provider
                .read(session, zh, &mut |d| {
                    diagnostics.push(d);
                    Ok(())
                })
                .map(|data| {
                    crate::collect::events::extract(&data, range, plan_chunks)
                });
            (group, session, result, diagnostics)
        },
        |(group, session, result, diagnostics)| {
            for diagnostic in diagnostics {
                writeln!(
                    warnings,
                    "{}",
                    agent_dump_core::output::diagnostics::record_warning(
                        &diagnostic,
                        zh
                    )
                )?;
            }
            match result {
                Ok((dates, missing_time)) => {
                    if missing_time {
                        undated.push(format!(
                            "{}://{}",
                            group.info.scheme, session.id
                        ));
                    }
                    for (date, chunks) in dates {
                        entries.push(Entry {
                            date,
                            session: session.clone(),
                            provider: group.info,
                            chunks,
                        });
                    }
                }
                Err(error) => {
                    let uri = format!("{}://{}", group.info.scheme, session.id);
                    failed.push(uri.clone());
                    writeln!(
                        warnings,
                        "{}",
                        terminal(
                            "WARN_SESSION_READ_SKIPPED",
                            zh,
                            &[
                                ("uri", uri.clone()),
                                (
                                    "error",
                                    agent_dump_core::providers::error::message(
                                        error.as_ref(),
                                        zh
                                    )
                                )
                            ]
                        )
                    )?;
                    if let Some(logger) = logger {
                        logger.log("session_read_failed", json!({"agent":group.info.name, "session_uri":uri, "error_type":agent_dump_core::providers::error::kind(error.as_ref()).unwrap_or("RuntimeError"), "error":agent_dump_core::providers::error::message(error.as_ref(), zh)}));
                    }
                    last_error = Some(error);
                }
            }
            completed += 1;
            progress(
                "COLLECT_PROGRESS_SCAN_SESSIONS",
                &[
                    ("current", completed.to_string()),
                    ("total", positions.len().to_string()),
                ],
                zh,
                warnings,
            )?;
            Ok(())
        },
    )?;
    if entries.is_empty()
        && let Some(error) = last_error
    {
        return Err(error);
    }
    if !failed.is_empty() {
        writeln!(
            warnings,
            "{}",
            t(
                "WARN_SESSION_READ_FAILURES",
                zh,
                &[("count", failed.len().to_string())]
            )
        )?;
    }
    entries.sort_by_key(|entry| entry.date);
    Ok((entries, failed, undated))
}
