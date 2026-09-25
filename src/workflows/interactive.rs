use agent_dump_core::output::diagnostics::{self, Diagnostic};
use agent_dump_core::output::formats::OutputFormat;
use agent_dump_core::output::i18n::{t, terminal};
use agent_dump_core::providers::contract::{RawExport, render_search_roots};
use agent_dump_core::query::Query;
use std::collections::{BTreeSet, HashMap, HashSet};
use std::io::{BufRead, Write};
use std::path::PathBuf;
use unicode_normalization::UnicodeNormalization;

pub struct Operation {
    pub query: Option<Query>,
    pub days: i64,
    pub formats: Vec<OutputFormat>,
    pub output: Option<PathBuf>,
    pub metadata: bool,
}

pub fn run(
    operation: &Operation,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
    input: &mut impl BufRead,
) -> crate::Result<bool> {
    let configured = if operation.output.is_none()
        && operation
            .formats
            .iter()
            .any(|f| matches!(f, OutputFormat::Json | OutputFormat::Raw))
    {
        let config = agent_dump_core::config::Config::load()?;
        if let Err(error) = config.require_valid(zh) {
            writeln!(out, "{error}")?;
            return Ok(false);
        }
        config.output()
    } else {
        String::new()
    };
    write!(out, "{}", agent_dump_core::output::render::list_banner())?;
    let mut scan = agent_dump_core::query::scanner::discover(
        operation.query.as_ref(),
        operation.days,
        zh,
        warnings,
    )?;
    if scan.groups.is_empty() {
        let roots = agent_dump_core::providers::registry::search_roots()?;
        let names = operation
            .query
            .as_ref()
            .and_then(|q| q.providers.as_ref())
            .map(|n| n.iter().cloned().collect::<Vec<_>>().join(","));
        write!(
            out,
            "{}",
            Diagnostic::empty_list(names.as_deref(), roots, zh).render(zh)
        )?;
        return Ok(false);
    }
    if let Some(query) = &operation.query {
        let selection = agent_dump_core::query::filter::select(
            &scan.groups,
            query,
            zh,
            warnings,
        )?;
        for (g, group) in scan.groups.iter_mut().enumerate() {
            group.sessions = selection
                .matches
                .iter()
                .filter(|m| m.group == g)
                .map(|m| group.sessions[m.session].clone())
                .collect();
        }
        scan.groups.retain(|g| !g.sessions.is_empty());
    }
    if scan.groups.is_empty() {
        writeln!(
            out,
            "{}",
            terminal(
                "NO_SESSIONS_MATCHING_KEYWORD",
                zh,
                &[
                    ("days", operation.days.to_string()),
                    (
                        "query",
                        operation
                            .query
                            .as_ref()
                            .map_or(String::new(), |q| q.summary(zh))
                    )
                ]
            )
        )?;
        return Ok(false);
    }
    let index = if scan.groups.len() == 1 {
        writeln!(
            out,
            "{}",
            terminal(
                "AUTO_SELECT_AGENT",
                zh,
                &[("agent_name", scan.groups[0].info.display_name.into())]
            )
        )?;
        0
    } else {
        let rows: Vec<_> = scan
            .groups
            .iter()
            .map(|g| crate::terminal::tui::Row {
                title: format!(
                    "{} ({} {})",
                    g.info.display_name,
                    g.sessions.len(),
                    t("SESSION_COUNT_SUFFIX", zh, &[])
                ),
                detail: String::new(),
                group: String::new(),
            })
            .collect();
        let Some(index) =
            crate::terminal::selector::provider(&rows, zh, out, input)?
        else {
            writeln!(out, "\n{}", t("NO_AGENT_SELECTED", zh, &[]))?;
            return Ok(false);
        };
        writeln!(
            out,
            "{}",
            terminal(
                "AGENT_SELECTED",
                zh,
                &[("agent_name", scan.groups[index].info.display_name.into())]
            )
        )?;
        index
    };
    let group = &scan.groups[index];
    if let Some(diagnostic) = Diagnostic::unsupported_formats(
        group.info,
        group.provider.as_ref(),
        &operation.formats,
        zh,
    ) {
        write!(out, "{}", diagnostic.render(zh))?;
        return Ok(false);
    }
    if group.sessions.is_empty() {
        writeln!(
            out,
            "{}",
            t(
                "NO_SESSIONS_FOUND",
                zh,
                &[("days", operation.days.to_string())]
            )
        )?;
        return Ok(false);
    }
    let mut values = vec![
        ("count", group.sessions.len().to_string()),
        ("days", operation.days.to_string()),
    ];
    if let Some(q) = &operation.query {
        values.push(("query", q.summary(zh)));
    }
    writeln!(
        out,
        "{}",
        terminal(
            if operation.query.is_some() {
                "SESSIONS_FOUND_FILTERED"
            } else {
                "SESSIONS_FOUND"
            },
            zh,
            &values
        )
    )?;
    if group.sessions.len() > 100 {
        writeln!(
            out,
            "{}\n{}",
            t("MANY_SESSIONS_WARNING", zh, &values),
            t("MANY_SESSIONS_EXAMPLE", zh, &[])
        )?;
    }
    let selected = crate::terminal::selector::sessions(
        &group.sessions,
        group.info.scheme,
        operation.metadata,
        zh,
        out,
        input,
    )?;
    if selected.is_empty() {
        writeln!(out, "\n{}", t("NO_SESSION_SELECTED", zh, &[]))?;
        return Ok(false);
    }
    writeln!(
        out,
        "{}",
        t(
            "SESSIONS_SELECTED_COUNT",
            zh,
            &[("count", selected.len().to_string())]
        )
    )?;
    writeln!(
        out,
        "{}",
        terminal(
            "EXPORTING_AGENT",
            zh,
            &[("agent_name", group.info.display_name.into())]
        )
    )?;
    let cache = agent_dump_core::session::cache::SessionDataCache::default();
    let mut targets: HashMap<String, Vec<(usize, usize)>> = HashMap::new();
    for (position, &index) in selected.iter().enumerate() {
        let session = &group.sessions[index];
        let raw = group.provider.raw_export(session);
        for (f, &format) in operation.formats.iter().enumerate() {
            let base = agent_dump_core::output::export::output_base(
                operation.output.as_deref(),
                &configured,
                format,
            )
            .join(group.info.name);
            if let Ok(path) = agent_dump_core::output::export::target(
                &session.id,
                &base,
                format,
                raw.as_ref().ok(),
            ) {
                let absolute = agent_dump_core::query::project_path(
                    &agent_dump_core::storage::source_io::path_text(&path),
                )?;
                let normalized: String =
                    agent_dump_core::storage::source_io::path_text(&absolute)
                        .nfc()
                        .collect();
                targets
                    .entry(caseless::default_case_fold_str(&normalized))
                    .or_default()
                    .push((position, f));
            }
        }
    }
    let collisions: HashSet<_> = targets
        .values()
        .filter(|v| v.len() > 1)
        .flatten()
        .copied()
        .collect();
    let mut exported = 0;
    let mut paths = BTreeSet::new();
    for (position, index) in selected.into_iter().enumerate() {
        let session = &group.sessions[index];
        let uri = format!("{}://{}", group.info.scheme, session.id);
        let raw = group.provider.raw_export(session);
        let data = (operation.formats.iter().any(|f| *f != OutputFormat::Raw)
            || matches!(raw, Ok(RawExport::Session)))
        .then(|| {
            cache.get(
                group.info.name,
                group.provider.as_ref(),
                session,
                zh,
                &mut |d| {
                    writeln!(
                        warnings,
                        "{}",
                        diagnostics::record_warning(&d, zh)
                    )?;
                    Ok(())
                },
            )
        });
        for (f, &format) in operation.formats.iter().enumerate() {
            if collisions.contains(&(position, f)) {
                let base = agent_dump_core::output::export::output_base(
                    operation.output.as_deref(),
                    &configured,
                    format,
                )
                .join(group.info.name);
                let path = agent_dump_core::output::export::target(
                    &session.id,
                    &base,
                    format,
                    raw.as_ref().ok(),
                )?;
                let error =
                    agent_dump_core::providers::error::ProviderError::Cause {
                        kind: "ExportPathCollisionError",
                        message: format!(
                            "multiple exports resolve to the same output path: {}",
                            agent_dump_core::storage::source_io::path_text(
                                &path
                            )
                        ),
                    };
                write!(
                    out,
                    "{}",
                    Diagnostic::read_failed(
                        &error,
                        render_search_roots(
                            group.info,
                            group.provider.as_ref()
                        ),
                        zh
                    )
                    .render(zh)
                )?;
                continue;
            }
            let needs_data = format != OutputFormat::Raw
                || matches!(raw, Ok(RawExport::Session));
            let error = match (&raw, &data) {
                (Err(e), _) if format == OutputFormat::Raw => Some(e),
                (_, Some(Err(e))) if needs_data => Some(e),
                _ => None,
            };
            if let Some(error) = error {
                write!(
                    out,
                    "{}",
                    Diagnostic::read_failed(
                        error.as_ref(),
                        render_search_roots(
                            group.info,
                            group.provider.as_ref()
                        ),
                        zh
                    )
                    .render(zh)
                )?;
                continue;
            }
            let base = agent_dump_core::output::export::output_base(
                operation.output.as_deref(),
                &configured,
                format,
            )
            .join(group.info.name);
            let prepared = data
                .as_ref()
                .and_then(|d| d.as_ref().ok())
                .map(std::convert::AsRef::as_ref);
            match (agent_dump_core::output::export::SessionExport {
                provider: group.provider.as_ref(),
                session,
                uri: &uri,
                data: prepared,
                raw: &raw,
            })
            .write(format, &base, None)
            {
                Ok(path) => {
                    exported += 1;
                    paths.insert(
                        agent_dump_core::storage::source_io::path_text(
                            path.parent().unwrap(),
                        ),
                    );
                    writeln!(
                        out,
                        "{}",
                        terminal(
                            "EXPORT_SUCCESS_FORMAT",
                            zh,
                            &[
                                ("title", session.title.chars().take(50).collect()),
                                ("format", format.name().into()),
                                (
                                    "filename",
                                    agent_dump_core::storage::source_io::path_text(std::path::Path::new(
                                        path.file_name().unwrap()
                                    ))
                                )
                            ]
                        )
                    )?;
                }
                Err(error) => write!(
                    out,
                    "{}",
                    Diagnostic::read_failed(
                        error.as_ref(),
                        render_search_roots(
                            group.info,
                            group.provider.as_ref()
                        ),
                        zh
                    )
                    .render(zh)
                )?,
            }
        }
    }
    let path = if paths.is_empty() {
        agent_dump_core::storage::source_io::path_text(
            &agent_dump_core::output::export::output_base(
                operation.output.as_deref(),
                &configured,
                operation.formats[0],
            )
            .join(group.info.name),
        )
    } else {
        paths.into_iter().collect::<Vec<_>>().join(", ")
    };
    writeln!(
        out,
        "{}",
        terminal(
            "EXPORT_SUMMARY",
            zh,
            &[("count", exported.to_string()), ("path", path)]
        )
    )?;
    Ok(exported > 0)
}
