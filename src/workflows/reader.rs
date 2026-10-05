use crate::terminal::reader::{Action, Reader};
use crate::terminal::tui::Row;
use agent_dump_core::output::{
    diagnostics, formats::OutputFormat, i18n::t, render,
};
use agent_dump_core::query::{Query, TimeField, scanner::Scan, text::Mode};
use std::io::Write;

struct Results {
    positions: Vec<(usize, usize)>,
    rows: Vec<Row>,
    status: String,
}

fn results(scan: &Scan, query: &Query, zh: bool) -> crate::Result<Results> {
    let mut notices = Vec::new();
    let mut selection = agent_dump_core::query::filter::select(
        &scan.groups,
        query,
        zh,
        &mut notices,
    )?;
    if query.mode != Mode::Terms {
        selection.matches.sort_by_key(|matched| {
            std::cmp::Reverse(
                scan.groups[matched.group].sessions[matched.session].updated_at,
            )
        });
    }
    let rows = selection
        .matches
        .iter()
        .map(|matched| {
            let group = &scan.groups[matched.group];
            let session = &group.sessions[matched.session];
            let mut detail = render::safe_line(&format!(
                "{} · {}",
                group.info.display_name,
                session.updated_at.format_local("%m-%d %H:%M")
            ));
            if !matched.snippet.is_empty() {
                detail.push('\n');
                detail.push_str(&render::safe_line(&matched.snippet));
            }
            Row {
                title: render::safe_line(if session.title.trim().is_empty() {
                    &session.id
                } else {
                    &session.title
                }),
                detail,
                group: format!("{}://{}", group.info.scheme, session.id),
            }
        })
        .collect();
    let mut status = t(
        if selection.matches.is_empty() {
            "READER_NO_MATCHES"
        } else {
            "READER_RESULTS"
        },
        zh,
        &[("count", selection.matches.len().to_string())],
    );
    if !scan.failed_providers.is_empty() || !selection.failures.is_empty() {
        status = format!("{} {status}", t("READER_PARTIAL", zh, &[]));
    }
    if !notices.is_empty() {
        status.push(' ');
        status.push_str(&render::safe_line(&String::from_utf8_lossy(&notices)));
    }
    Ok(Results {
        positions: selection
            .matches
            .iter()
            .map(|matched| (matched.group, matched.session))
            .collect(),
        rows,
        status,
    })
}

fn scope(query: &Query, days: i64, zh: bool) -> String {
    let all = t("READER_ALL", zh, &[]);
    t(
        "READER_SCOPE",
        zh,
        &[
            (
                "providers",
                query.providers.as_ref().map_or_else(
                    || all.clone(),
                    |names| names.iter().cloned().collect::<Vec<_>>().join(","),
                ),
            ),
            (
                "path",
                query.path.as_ref().map_or_else(
                    || all.clone(),
                    |path| render::safe_line(&path.display().to_string()),
                ),
            ),
            (
                "roles",
                query.roles.as_ref().map_or_else(
                    || all.clone(),
                    |roles| roles.iter().cloned().collect::<Vec<_>>().join(","),
                ),
            ),
            ("limit", query.limit.map_or(all, |limit| limit.to_string())),
            ("days", days.to_string()),
            (
                "time",
                t(
                    if query.time_field == TimeField::Updated {
                        "READER_UPDATED"
                    } else {
                        "READER_CREATED"
                    },
                    zh,
                    &[],
                ),
            ),
        ],
    )
}

pub fn run(
    operation: &super::interactive::Operation,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<bool> {
    if !crate::terminal::tui::available() {
        writeln!(warnings, "{}", t("READER_REQUIRES_TTY", zh, &[]))?;
        return Ok(false);
    }
    let mut query = operation.query.clone().unwrap_or_default();
    let scan = agent_dump_core::query::scanner::discover(
        Some(&query),
        operation.days,
        zh,
        warnings,
    )?;
    if scan.groups.is_empty() {
        writeln!(out, "{}", t("READER_EMPTY", zh, &[]))?;
        return Ok(false);
    }
    let selected = results(&scan, &query, zh)?;
    let mut positions = selected.positions;
    out.flush()?;
    let mut reader = Reader::new(
        selected.rows,
        &query,
        scope(&query, operation.days, zh),
        zh,
    )?;
    reader.status = selected.status;
    let cache = agent_dump_core::session::cache::SessionDataCache::default();
    loop {
        let mut notices = Vec::new();
        let loaded = positions.get(reader.selected()).map(|&(g, s)| {
            let group = &scan.groups[g];
            cache.get(
                group.info.name,
                group.provider.as_ref(),
                &group.sessions[s],
                zh,
                &mut |d| {
                    writeln!(
                        notices,
                        "{}",
                        diagnostics::record_warning(&d, zh)
                    )?;
                    Ok(())
                },
            )
        });
        if !notices.is_empty() {
            reader.status =
                render::safe_line(&String::from_utf8_lossy(&notices));
        }
        let data = loaded
            .as_ref()
            .and_then(|data| data.as_ref().ok())
            .map(std::convert::AsRef::as_ref);
        let error =
            loaded
                .as_ref()
                .and_then(|data| data.as_ref().err())
                .map(|error| {
                    diagnostics::Diagnostic::unexpected(error.as_ref(), zh)
                        .render(zh)
                });
        match reader.next(data, error.as_deref())? {
            Action::Select => {}
            Action::Quit => return Ok(true),
            Action::Search(keyword) => {
                let mut next = query.clone();
                next.keyword = (!keyword.trim().is_empty()).then_some(keyword);
                next.mode = Mode::Terms;
                match results(&scan, &next, zh) {
                    Ok(selected) => {
                        positions = selected.positions;
                        query = next;
                        reader.set_results(selected.rows, &query);
                        reader.status = selected.status;
                    }
                    Err(error) => {
                        reader.status = render::safe_line(&error.to_string());
                    }
                }
            }
            Action::Export { locator, context } => {
                let Some(&(g, s)) = positions.get(reader.selected()) else {
                    continue;
                };
                if locator.is_some()
                    && operation.formats.iter().any(|format| {
                        !matches!(
                            format,
                            OutputFormat::Json | OutputFormat::Markdown
                        )
                    })
                {
                    reader.status = t("MESSAGE_EXPORT_FORMAT_ERROR", zh, &[]);
                    continue;
                }
                let group = &scan.groups[g];
                let session = &group.sessions[s];
                let mut result = Vec::new();
                let mut notices = Vec::new();
                let exported = super::uri::run(
                    &super::uri::UriOperation {
                        read: None,
                        uri: format!("{}://{}", group.info.scheme, session.id),
                        head: false,
                        summary: false,
                        message: locator,
                        before: context,
                        after: context,
                        json: false,
                        formats: operation.formats.clone(),
                        output: operation.output.clone(),
                    },
                    zh,
                    &mut result,
                    &mut notices,
                );
                reader.status = match exported {
                    Ok(_) => render::safe_line(&format!(
                        "{} {}",
                        String::from_utf8_lossy(&result),
                        String::from_utf8_lossy(&notices)
                    )),
                    Err(error) => render::safe_line(&error.to_string()),
                };
            }
        }
    }
}
