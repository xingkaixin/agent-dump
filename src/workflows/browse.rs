use crate::terminal::reader::{Action, Entry, Reader};
use agent_dump_core::output::{
    diagnostics, formats::OutputFormat, i18n::t, render,
};
use agent_dump_core::query::{
    Query, TimeField, filter,
    scanner::{self, Scan, WindowScope},
    text::Mode,
};
use agent_dump_core::session::{
    Session, cache::SessionDataCache, timestamp::Timestamp,
};
use std::io::Write;

struct Results {
    positions: Vec<(usize, usize)>,
    rows: Vec<Entry>,
    status: String,
    partial: bool,
}

fn results(scan: &Scan, query: &Query, zh: bool) -> crate::Result<Results> {
    let mut notices = Vec::new();
    let unbounded = Query {
        limit: None,
        ..query.clone()
    };
    let mut selection =
        filter::select(&scan.groups, &unbounded, zh, &mut notices)?;
    let grouped = query.mode != Mode::Terms || query.keyword.is_none();
    let timestamp = |m: &filter::Match| {
        query
            .time_field
            .timestamp(&scan.groups[m.group].sessions[m.session])
    };
    selection.matches.sort_by(|a, b| {
        let by_time = || timestamp(b).cmp(&timestamp(a));
        if grouped {
            by_time()
        } else {
            b.rank.total_cmp(&a.rank).then_with(by_time)
        }
    });
    if let Some(limit) = query.limit {
        selection.matches.truncate(limit);
    }
    let days = Days {
        today: Timestamp::now().local_date(),
        yesterday: Timestamp::days_ago(1)?.local_date(),
        grouped,
        time_field: query.time_field,
    };
    let rows = selection
        .matches
        .iter()
        .map(|matched| {
            let group = &scan.groups[matched.group];
            entry(
                group.info.display_name,
                &format!("{}://", group.info.scheme),
                &group.sessions[matched.session],
                &matched.snippet,
                &days,
                zh,
            )
        })
        .collect();
    let mut status = if selection.matches.is_empty() {
        t("READER_NO_MATCHES", zh, &[])
    } else {
        String::new()
    };
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
        partial: !scan.failed_providers.is_empty()
            || !selection.failures.is_empty(),
    })
}

struct Days {
    today: jiff::civil::Date,
    yesterday: jiff::civil::Date,
    grouped: bool,
    time_field: TimeField,
}

fn entry(
    provider: &str,
    scheme: &str,
    session: &Session,
    snippet: &str,
    days: &Days,
    zh: bool,
) -> Entry {
    let shown = days.time_field.timestamp(session);
    let date = shown.local_date();
    let day = if !days.grouped {
        String::new()
    } else if date == days.today {
        t("READER_TODAY", zh, &[])
    } else if date == days.yesterday {
        t("READER_YESTERDAY", zh, &[])
    } else if date.year() == days.today.year() {
        shown.format_local("%m-%d")
    } else {
        shown.format_local("%Y-%m-%d")
    };
    let count = t(
        "READER_MESSAGES",
        zh,
        &[(
            "count",
            session
                .message_count
                .map_or_else(|| "?".into(), |count| count.to_string()),
        )],
    );
    let location = session.display_location();
    let place = std::path::Path::new(&location)
        .file_name()
        .map_or_else(String::new, |name| name.to_string_lossy().into_owned());
    let meta = [
        provider,
        session.model.as_str(),
        location.as_str(),
        count.as_str(),
        &format!(
            "{} → {}",
            session.created_at.format_local("%m-%d %H:%M"),
            session.updated_at.format_local("%m-%d %H:%M")
        ),
    ]
    .into_iter()
    .filter(|part| !part.trim().is_empty())
    .collect::<Vec<_>>()
    .join(" · ");
    Entry {
        title: render::safe_line(if session.title.trim().is_empty() {
            &session.id
        } else {
            &session.title
        }),
        provider: render::safe_line(provider),
        time: shown.format_local(if days.grouped {
            "%H:%M"
        } else {
            "%m-%d %H:%M"
        }),
        day,
        count,
        place: render::safe_line(&place),
        snippet: if snippet.trim() == session.title.trim() {
            String::new()
        } else {
            render::safe_line(snippet)
        },
        meta: render::safe_line(&meta),
        uri: format!("{scheme}{}", session.id),
    }
}

fn scope(query: &Query, window: WindowScope, zh: bool) -> String {
    let all = t("READER_ALL", zh, &[]);
    let mut values = vec![
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
    ];
    let key = match window {
        WindowScope::Days(days) => {
            values.push(("days", days.to_string()));
            "READER_SCOPE"
        }
        WindowScope::Range(since, until) => {
            values.push(("since", since.to_string()));
            values.push(("until", until.to_string()));
            "READER_SCOPE_RANGE"
        }
    };
    t(key, zh, &values)
}

fn export_marked(
    scan: &Scan,
    picks: &[(usize, usize)],
    operation: &super::interactive::Operation,
    zh: bool,
) -> crate::Result<String> {
    let groups: std::collections::BTreeSet<_> =
        picks.iter().map(|&(g, _)| g).collect();
    for g in groups {
        let group = &scan.groups[g];
        if let Some(diagnostic) = diagnostics::Diagnostic::unsupported_formats(
            group.info,
            group.provider.as_ref(),
            &operation.formats,
            zh,
        ) {
            return Ok(render::safe_line(&diagnostic.render(zh)));
        }
    }
    let configured = match super::interactive::configured_output(operation, zh)?
    {
        Ok(configured) => configured,
        Err(error) => return Ok(render::safe_line(&error)),
    };
    let mut result = Vec::new();
    let mut notices = Vec::new();
    Ok(
        match super::interactive::export(
            &scan.groups,
            picks,
            operation,
            &configured,
            zh,
            &mut result,
            &mut notices,
        ) {
            Ok(_) => render::safe_line(
                String::from_utf8_lossy(&result)
                    .lines()
                    .rfind(|line| !line.trim().is_empty())
                    .unwrap_or_default(),
            ),
            Err(error) => render::safe_line(&error.to_string()),
        },
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
    let scan = scanner::discover(
        Some(&query),
        operation.scope,
        query.time_field,
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
        scope(&query, operation.scope, zh),
        zh,
    )?;
    reader.status = selected.status;
    reader.partial = selected.partial;
    let cache = SessionDataCache::default();
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
                        reader.partial = selected.partial;
                    }
                    Err(error) => {
                        reader.status = render::safe_line(&error.to_string());
                    }
                }
            }
            Action::ExportMarked(rows) => {
                let picks: Vec<_> = rows
                    .iter()
                    .filter_map(|&row| positions.get(row).copied())
                    .collect();
                reader.status = export_marked(&scan, &picks, operation, zh)?;
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

#[cfg(test)]
mod tests {
    use super::*;
    use agent_dump_core::providers::contract::{
        DiagnosticSink, Discovery, Lookup, Provider, ProviderInfo, Window,
    };
    use agent_dump_core::query::scanner::ScannedProvider;
    use agent_dump_core::session::SessionData;
    use std::path::{Path, PathBuf};

    static TEST_PROVIDER: ProviderInfo = ProviderInfo {
        name: "codex",
        display_name: "Codex",
        scheme: "codex",
        identifier_label: "session_id",
        uri_prefixes: &["codex://"],
    };

    struct StubProvider;

    impl Provider for StubProvider {
        fn discover(
            &mut self,
            _window: Window,
            _diagnostics: &mut DiagnosticSink<'_>,
        ) -> crate::Result<Discovery> {
            Ok(Discovery::default())
        }

        fn find(
            &mut self,
            _id: &str,
            _diagnostics: &mut DiagnosticSink<'_>,
        ) -> crate::Result<Lookup> {
            Ok(Lookup::default())
        }

        fn read(
            &self,
            _session: &Session,
            _zh: bool,
            _diagnostics: &mut DiagnosticSink<'_>,
        ) -> crate::Result<SessionData> {
            Err("unused".into())
        }

        fn source_root(&self) -> &Path {
            Path::new("")
        }

        fn select_source(&mut self) -> crate::Result<Option<&Path>> {
            Ok(None)
        }

        fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
            Ok(Vec::new())
        }
    }

    fn test_session(
        id: &str,
        created_at: Timestamp,
        updated_at: Timestamp,
    ) -> Session {
        Session::new(
            id.into(),
            id.into(),
            PathBuf::new(),
            created_at,
            updated_at,
        )
    }

    #[test]
    fn results_sort_group_and_format_using_query_time_field() {
        let now = Timestamp::now();
        let yesterday = Timestamp::days_ago(1).unwrap();
        let three_days_ago = Timestamp::days_ago(3).unwrap();
        let newer_created = test_session("newer-created", yesterday, yesterday);
        let newer_updated = test_session("newer-updated", three_days_ago, now);
        let scan = Scan {
            groups: vec![ScannedProvider {
                info: &TEST_PROVIDER,
                provider: Box::new(StubProvider),
                sessions: vec![newer_updated, newer_created],
            }],
            failed_providers: Vec::new(),
        };

        let updated = results(&scan, &Query::default(), false).unwrap();
        assert_eq!(
            updated
                .rows
                .iter()
                .map(|row| row.title.as_str())
                .collect::<Vec<_>>(),
            ["newer-updated", "newer-created"]
        );
        assert_eq!(updated.rows[0].day, "Today");
        assert_eq!(updated.rows[0].time, now.format_local("%H:%M"));

        let created_query = Query {
            time_field: TimeField::Created,
            ..Query::default()
        };
        let created = results(&scan, &created_query, false).unwrap();
        assert_eq!(
            created
                .rows
                .iter()
                .map(|row| row.title.as_str())
                .collect::<Vec<_>>(),
            ["newer-created", "newer-updated"]
        );
        assert_eq!(created.rows[0].day, "Yesterday");
        assert_eq!(created.rows[0].time, yesterday.format_local("%H:%M"));
        assert_eq!(created.rows[1].time, three_days_ago.format_local("%H:%M"));
        assert_ne!(created.rows[1].day, "Today");
        let limited = results(
            &scan,
            &Query {
                limit: Some(1),
                ..created_query
            },
            false,
        )
        .unwrap();
        assert_eq!(limited.positions, [(0, 1)]);
        let expected_span = format!(
            "{} → {}",
            three_days_ago.format_local("%m-%d %H:%M"),
            now.format_local("%m-%d %H:%M")
        );
        assert!(
            created.rows[1].meta.contains(&expected_span),
            "{}",
            created.rows[1].meta
        );
    }

    #[test]
    fn entry_projects_time_field_in_grouped_and_ungrouped_views() {
        let created: Timestamp = "2026-03-08T04:15:00+00:00".parse().unwrap();
        let updated: Timestamp = "2026-03-10T09:45:00+00:00".parse().unwrap();
        let session = test_session("s1", created, updated);
        let today = updated.local_date();
        let yesterday = today.yesterday().unwrap();

        let grouped_created = entry(
            "Codex",
            "codex://",
            &session,
            "",
            &Days {
                today,
                yesterday,
                grouped: true,
                time_field: TimeField::Created,
            },
            false,
        );
        assert_eq!(grouped_created.day, created.format_local("%m-%d"));
        assert_eq!(grouped_created.time, created.format_local("%H:%M"));
        assert!(grouped_created.meta.contains(&format!(
            "{} → {}",
            created.format_local("%m-%d %H:%M"),
            updated.format_local("%m-%d %H:%M")
        )));

        let ungrouped_created = entry(
            "Codex",
            "codex://",
            &session,
            "",
            &Days {
                today,
                yesterday,
                grouped: false,
                time_field: TimeField::Created,
            },
            false,
        );
        assert!(ungrouped_created.day.is_empty());
        assert_eq!(ungrouped_created.time, created.format_local("%m-%d %H:%M"));
    }
}
