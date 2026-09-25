use crate::collect_model::Entry;
use crate::collect_progress::progress;
use crate::i18n::{t, terminal};
use crate::scanner::Scan;
use serde_json::json;
use std::io::Write;

pub fn read_entries(
    scan: &Scan,
    positions: &[(usize, usize)],
    zh: bool,
    warnings: &mut impl Write,
    logger: Option<&crate::collect_log::Logger>,
) -> crate::Result<(Vec<Entry>, usize)> {
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
    let mut failed = 0;
    let mut last_error = None;
    let mut completed = 0;
    for batch in positions.chunks(32) {
        let results = std::thread::scope(|scope| {
            let jobs: Vec<_> = batch
                .iter()
                .map(|&(g, s)| {
                    let group = &scan.groups[g];
                    let session = &group.sessions[s];
                    scope.spawn(move || {
                        let mut diagnostics = Vec::new();
                        let result = group
                            .provider
                            .read(session, zh, &mut |d| {
                                diagnostics.push(d);
                                Ok(())
                            })
                            .map(|data| crate::collect_events::extract(&data));
                        (group, session, result, diagnostics)
                    })
                })
                .collect();
            jobs.into_iter()
                .map(|job| job.join().unwrap())
                .collect::<Vec<_>>()
        });
        for (group, session, result, diagnostics) in results {
            for diagnostic in diagnostics {
                writeln!(
                    warnings,
                    "{}",
                    crate::diagnostics::record_warning(&diagnostic, zh)
                )?;
            }
            match result {
                Ok((chunks, truncated)) => {
                    if !chunks.is_empty() {
                        entries.push(Entry {
                            date: crate::date_input::parse(
                                &session.created_at.format_local("%Y-%m-%d"),
                            )
                            .unwrap(),
                            session: session.clone(),
                            provider: group.info,
                            chunks,
                            truncated,
                        });
                    }
                }
                Err(error) => {
                    failed += 1;
                    let uri = format!("{}://{}", group.info.scheme, session.id);
                    writeln!(
                        warnings,
                        "{}",
                        terminal(
                            "WARN_SESSION_READ_SKIPPED",
                            zh,
                            &[
                                ("uri", uri.clone()),
                                ("error", crate::provider_error::message(error.as_ref(), zh))
                            ]
                        )
                    )?;
                    if let Some(logger) = logger {
                        logger.log("session_read_failed", json!({"agent":group.info.name, "session_uri":uri, "error_type":crate::provider_error::kind(error.as_ref()).unwrap_or("RuntimeError"), "error":crate::provider_error::message(error.as_ref(), zh)}));
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
        }
    }
    if entries.is_empty()
        && let Some(error) = last_error
    {
        return Err(error);
    }
    if failed > 0 {
        writeln!(
            warnings,
            "{}",
            t(
                "WARN_SESSION_READ_FAILURES",
                zh,
                &[("count", failed.to_string())]
            )
        )?;
    }
    entries.sort_by_key(|entry| entry.session.created_at);
    Ok((entries, failed))
}
