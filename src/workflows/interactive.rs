use agent_dump_core::config::Config;
use agent_dump_core::output::diagnostics::{self, Diagnostic};
use agent_dump_core::output::formats::OutputFormat;
use agent_dump_core::output::i18n::{t, terminal};
use agent_dump_core::output::{export, render};
use agent_dump_core::parallel;
use agent_dump_core::providers::contract::{RawExport, render_search_roots};
use agent_dump_core::providers::error::ProviderError;
use agent_dump_core::providers::registry;
use agent_dump_core::query::scanner::{ScannedProvider, WindowScope};
use agent_dump_core::query::{Query, filter, project_path, scanner};
use agent_dump_core::session::cache::SessionDataCache;
use agent_dump_core::storage::source_io::path_text;
use std::collections::{BTreeSet, HashMap, HashSet};
use std::io::{BufRead, Write};
use std::path::PathBuf;
use unicode_normalization::UnicodeNormalization;

pub struct Operation {
    pub query: Option<Query>,
    pub scope: WindowScope,
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
    let configured = match configured_output(operation, zh)? {
        Ok(configured) => configured,
        Err(error) => {
            writeln!(out, "{error}")?;
            return Ok(false);
        }
    };
    write!(out, "{}", render::list_banner())?;
    let time_field = operation
        .query
        .as_ref()
        .map(|query| query.time_field)
        .unwrap_or_default();
    let mut scan = scanner::discover(
        operation.query.as_ref(),
        operation.scope,
        time_field,
        zh,
        warnings,
    )?;
    if scan.groups.is_empty() {
        let roots = registry::search_roots()?;
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
    let unfiltered = Query::default();
    let selection = filter::select(
        &scan.groups,
        operation.query.as_ref().unwrap_or(&unfiltered),
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
    if operation.query.is_some() {
        scan.groups.retain(|g| !g.sessions.is_empty());
    }
    if scan.groups.is_empty() {
        let query_text = operation
            .query
            .as_ref()
            .map_or(String::new(), |q| q.summary(zh));
        let message = match operation.scope {
            WindowScope::Days(days) => terminal(
                "NO_SESSIONS_MATCHING_KEYWORD",
                zh,
                &[("days", days.to_string()), ("query", query_text)],
            ),
            WindowScope::Range(since, until) => terminal(
                "NO_SESSIONS_MATCHING_KEYWORD_RANGE",
                zh,
                &[
                    ("since", since.to_string()),
                    ("until", until.to_string()),
                    ("query", query_text),
                ],
            ),
        };
        writeln!(out, "{message}")?;
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
        let message = match operation.scope {
            WindowScope::Days(days) => {
                t("NO_SESSIONS_FOUND", zh, &[("days", days.to_string())])
            }
            WindowScope::Range(since, until) => t(
                "NO_SESSIONS_FOUND_RANGE",
                zh,
                &[("since", since.to_string()), ("until", until.to_string())],
            ),
        };
        writeln!(out, "{message}")?;
        return Ok(false);
    }
    let mut values = vec![("count", group.sessions.len().to_string())];
    match operation.scope {
        WindowScope::Days(days) => values.push(("days", days.to_string())),
        WindowScope::Range(since, until) => {
            values.push(("since", since.to_string()));
            values.push(("until", until.to_string()));
        }
    }
    if let Some(q) = &operation.query {
        values.push(("query", q.summary(zh)));
    }
    let found_key = match (operation.scope, operation.query.is_some()) {
        (WindowScope::Days(_), true) => "SESSIONS_FOUND_FILTERED",
        (WindowScope::Days(_), false) => "SESSIONS_FOUND",
        (WindowScope::Range(_, _), true) => "SESSIONS_FOUND_FILTERED_RANGE",
        (WindowScope::Range(_, _), false) => "SESSIONS_FOUND_RANGE",
    };
    writeln!(out, "{}", terminal(found_key, zh, &values))?;
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
        time_field,
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
    let picks: Vec<_> = selected.into_iter().map(|s| (index, s)).collect();
    let exported = export(
        &scan.groups,
        &picks,
        operation,
        &configured,
        zh,
        out,
        warnings,
    )?;
    Ok(exported > 0)
}

pub fn configured_output(
    operation: &Operation,
    zh: bool,
) -> crate::Result<Result<String, String>> {
    if operation.output.is_some()
        || !operation.formats.iter().any(|f| *f != OutputFormat::Print)
    {
        return Ok(Ok(String::new()));
    }
    let config = Config::load()?;
    Ok(match config.require_valid(zh) {
        Ok(()) => Ok(config.output()),
        Err(error) => Err(error.to_string()),
    })
}

#[derive(Default)]
struct Written {
    out: Vec<u8>,
    warnings: Vec<u8>,
    exported: usize,
    directories: Vec<String>,
}

struct Batch<'a> {
    groups: &'a [ScannedProvider],
    operation: &'a Operation,
    configured: &'a str,
    collisions: HashSet<(usize, usize)>,
    output_dirs: HashMap<usize, Result<export::OutputDir, String>>,
    cache: Option<SessionDataCache>,
    needs_raw: bool,
    zh: bool,
}

impl Batch<'_> {
    fn export(
        &self,
        position: usize,
        (g, index): (usize, usize),
        written: &mut Written,
    ) -> crate::Result<()> {
        let &Self {
            groups,
            operation,
            configured,
            ref collisions,
            ref output_dirs,
            ref cache,
            needs_raw,
            zh,
        } = self;
        let group = &groups[g];
        let session = &group.sessions[index];
        let uri = format!("{}://{}", group.info.scheme, session.id);
        let raw = if needs_raw {
            group.provider.raw_export(session)
        } else {
            Ok(RawExport::Session)
        };
        let needs_session_data =
            operation.formats.iter().any(|f| *f != OutputFormat::Raw)
                || matches!(raw, Ok(RawExport::Session));
        let mut owned_data = None;
        let mut leased_data = None;
        if needs_session_data {
            if let Some(cache) = cache {
                leased_data = Some(cache.lease(
                    group.info.name,
                    group.provider.as_ref(),
                    session,
                    zh,
                    &mut |d| {
                        writeln!(
                            written.warnings,
                            "{}",
                            diagnostics::record_warning(&d, zh)
                        )?;
                        Ok(())
                    },
                ));
            } else {
                owned_data = Some(group.provider.read(session, zh, &mut |d| {
                    writeln!(
                        written.warnings,
                        "{}",
                        diagnostics::record_warning(&d, zh)
                    )?;
                    Ok(())
                }));
            }
        }
        let read_error = owned_data
            .as_ref()
            .and_then(|r| r.as_ref().err())
            .or_else(|| leased_data.as_ref().and_then(|r| r.as_ref().err()));
        let prepared = owned_data
            .as_ref()
            .and_then(|r| r.as_ref().ok())
            .or_else(|| {
                leased_data
                    .as_ref()
                    .and_then(|r| r.as_ref().ok())
                    .map(std::ops::Deref::deref)
            });
        for (f, &format) in operation.formats.iter().enumerate() {
            if collisions.contains(&(position, f)) {
                let base = export::output_base(
                    operation.output.as_deref(),
                    configured,
                )
                .join(group.info.name);
                let path = export::target(
                    &session.id,
                    &base,
                    format,
                    raw.as_ref().ok(),
                )?;
                let error = ProviderError::Cause {
                    kind: "ExportPathCollisionError",
                    message: format!(
                        "multiple exports resolve to the same output path: {}",
                        path_text(&path)
                    ),
                };
                write!(
                    written.out,
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
            let error = match (&raw, read_error) {
                (Err(e), _) if format == OutputFormat::Raw => Some(e),
                (_, Some(e)) if needs_data => Some(e),
                _ => None,
            };
            if let Some(error) = error {
                write!(
                    written.out,
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
            let export_result = match output_dirs.get(&g) {
                Some(Ok(dir)) => (export::SessionExport {
                    provider: group.provider.as_ref(),
                    session,
                    uri: &uri,
                    data: prepared,
                    raw: &raw,
                })
                .write_to(dir, format, None),
                Some(Err(message)) => Err(message.clone().into()),
                None => {
                    let base = export::output_base(
                        operation.output.as_deref(),
                        configured,
                    )
                    .join(group.info.name);
                    (export::SessionExport {
                        provider: group.provider.as_ref(),
                        session,
                        uri: &uri,
                        data: prepared,
                        raw: &raw,
                    })
                    .write(format, &base, None)
                }
            };
            match export_result {
                Ok(path) => {
                    written.exported += 1;
                    written.directories.push(path_text(path.parent().unwrap()));
                    writeln!(
                        written.out,
                        "{}",
                        terminal(
                            "EXPORT_SUCCESS_FORMAT",
                            zh,
                            &[
                                (
                                    "title",
                                    session.title.chars().take(50).collect()
                                ),
                                ("format", format.name().into()),
                                (
                                    "filename",
                                    path_text(std::path::Path::new(
                                        path.file_name().unwrap()
                                    ))
                                )
                            ]
                        )
                    )?;
                }
                Err(error) => write!(
                    written.out,
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
        Ok(())
    }
}

pub fn export(
    groups: &[ScannedProvider],
    picks: &[(usize, usize)],
    operation: &Operation,
    configured: &str,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<usize> {
    let needs_raw = operation.formats.contains(&OutputFormat::Raw);
    let mut seen_picks = HashSet::with_capacity(picks.len());
    let has_duplicate_picks =
        picks.iter().any(|&pick| !seen_picks.insert(pick));
    let cache = has_duplicate_picks.then(SessionDataCache::default);
    let mut base_dirs: HashMap<usize, (PathBuf, PathBuf, String)> =
        HashMap::new();
    let mut output_dirs: HashMap<usize, Result<export::OutputDir, String>> =
        HashMap::new();
    let mut targets: HashMap<String, Vec<(usize, usize)>> = HashMap::new();
    let output_root =
        export::output_base(operation.output.as_deref(), configured);
    for (position, &(g, index)) in picks.iter().enumerate() {
        let group = &groups[g];
        let (base, absolute_base, folded_prefix) = match base_dirs.entry(g) {
            std::collections::hash_map::Entry::Occupied(entry) => {
                entry.into_mut()
            }
            std::collections::hash_map::Entry::Vacant(entry) => {
                let base = output_root.join(group.info.name);
                let absolute = project_path(&path_text(&base))?;
                let mut prefix = path_text(&absolute);
                if !prefix.ends_with('/') {
                    prefix.push('/');
                }
                let normalized: String = prefix.nfc().collect();
                let folded = caseless::default_case_fold_str(&normalized);
                output_dirs.insert(
                    g,
                    export::OutputDir::prepare(&base)
                        .map_err(|error| error.to_string()),
                );
                entry.insert((base, absolute, folded))
            }
        };
        let session = &group.sessions[index];
        let raw = needs_raw.then(|| group.provider.raw_export(session));
        for (f, &format) in operation.formats.iter().enumerate() {
            let raw_ref = raw.as_ref().and_then(|r| r.as_ref().ok());
            if let Ok(path) = export::target(&session.id, base, format, raw_ref)
            {
                let file_name = path.file_name().unwrap();
                let key = if let Some(name_str) = file_name.to_str()
                    && name_str.bytes().all(|b| {
                        b.is_ascii_lowercase()
                            || b.is_ascii_digit()
                            || matches!(b, b'_' | b'-' | b'.' | b'~')
                    }) {
                    let mut combined = String::with_capacity(
                        folded_prefix.len() + name_str.len(),
                    );
                    combined.push_str(folded_prefix);
                    combined.push_str(name_str);
                    combined
                } else {
                    let absolute = absolute_base.join(file_name);
                    let normalized: String =
                        path_text(&absolute).nfc().collect();
                    caseless::default_case_fold_str(&normalized)
                };
                targets.entry(key).or_default().push((position, f));
            }
        }
    }
    let collisions: HashSet<_> = targets
        .values()
        .filter(|v| v.len() > 1)
        .flatten()
        .copied()
        .collect();
    let batch = Batch {
        groups,
        operation,
        configured,
        collisions,
        output_dirs,
        cache,
        needs_raw,
        zh,
    };
    let mut exported = 0;
    let mut paths = BTreeSet::new();
    let items: Vec<_> = picks.iter().copied().enumerate().collect();
    parallel::ordered(
        &items,
        |&(position, pick)| {
            let mut written = Written::default();
            let result = batch.export(position, pick, &mut written);
            (written, result)
        },
        |(written, result)| {
            warnings.write_all(&written.warnings)?;
            out.write_all(&written.out)?;
            exported += written.exported;
            paths.extend(written.directories);
            result
        },
    )?;
    let path = if paths.is_empty() {
        path_text(
            &export::output_base(operation.output.as_deref(), configured)
                .join(groups[picks[0].0].info.name),
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
    Ok(exported)
}
