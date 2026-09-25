use crate::i18n::t;
use crate::query::Query;
use std::collections::BTreeMap;
use std::io::Write;

pub fn providers(zh: bool, out: &mut impl Write) -> crate::Result<bool> {
    writeln!(out, "{}\n", t("PROVIDERS_HEADER", zh, &[]))?;
    writeln!(
        out,
        "{}\n--- | --- | --- | --- | ---",
        t("PROVIDERS_TABLE_HEADER", zh, &[])
    )?;
    let mut roots = Vec::new();
    for registration in crate::registry::all() {
        let provider = (registration.open)()?;
        let search_roots = provider.search_roots()?;
        let states: Vec<_> = search_roots
            .into_iter()
            .map(|(label, path)| {
                let exists = path.exists();
                (label, path, exists)
            })
            .collect();
        let formats = [
            crate::output_formats::OutputFormat::Json,
            crate::output_formats::OutputFormat::Markdown,
            crate::output_formats::OutputFormat::Print,
            crate::output_formats::OutputFormat::Raw,
        ];
        let supported = formats
            .iter()
            .filter(|f| provider.supports_format(**f))
            .map(|f| f.name())
            .collect::<Vec<_>>()
            .join(", ");
        let unsupported = formats
            .iter()
            .filter(|f| !provider.supports_format(**f))
            .map(|f| f.name())
            .collect::<Vec<_>>()
            .join(", ");
        let counts = t(
            "PROVIDERS_ROOT_COUNT",
            zh,
            &[
                (
                    "existing",
                    states
                        .iter()
                        .filter(|(_, _, exists)| *exists)
                        .count()
                        .to_string(),
                ),
                ("total", states.len().to_string()),
            ],
        );
        writeln!(
            out,
            "{} | {}:// | {} | {} | {}",
            registration.info.display_name,
            registration.info.scheme,
            supported,
            counts,
            if unsupported.is_empty() {
                t("PROVIDERS_NONE", zh, &[])
            } else {
                unsupported
            }
        )?;
        roots.push((&registration.info, states));
    }
    writeln!(out, "\n{}", t("PROVIDERS_SEARCH_ROOTS", zh, &[]))?;
    for (info, roots) in roots {
        writeln!(out, "{}:", info.display_name)?;
        if roots.is_empty() {
            writeln!(out, "{}", t("PROVIDERS_ROOT_NONE", zh, &[]))?;
        }
        for (label, path, exists) in roots {
            writeln!(
                out,
                "  - [{}] {}: {}",
                t(
                    if exists {
                        "PROVIDERS_ROOT_EXISTS"
                    } else {
                        "PROVIDERS_ROOT_MISSING"
                    },
                    zh,
                    &[]
                ),
                label,
                crate::render::safe_line(&crate::source_io::path_text(&path))
            )?;
        }
    }
    Ok(true)
}

pub fn run(
    query: Option<Query>,
    days: i64,
    reindex: bool,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<bool> {
    let scan = crate::scanner::discover(query.as_ref(), days, zh, warnings)?;
    if scan.groups.is_empty() {
        let names = query
            .as_ref()
            .and_then(|q| q.providers.as_ref())
            .map(|names| names.iter().cloned().collect::<Vec<_>>().join(","));
        write!(
            out,
            "{}",
            crate::diagnostics::Diagnostic::empty_list(
                names.as_deref(),
                crate::registry::search_roots()?,
                zh
            )
            .render(zh)
        )?;
        return Ok(names.is_some());
    }
    if reindex {
        let mut index = crate::search_index::SearchIndex::open(
            scan.groups
                .iter()
                .map(|g| g.provider.source_root().to_owned()),
        )?;
        writeln!(out, "{}\n", t("REINDEX_START", zh, &[]))?;
        let mut total = 0;
        for group in &scan.groups {
            if group.sessions.is_empty() {
                continue;
            }
            index.clear(group.info.name)?;
            let (count, _) = index.update(
                group.info,
                group.provider.as_ref(),
                &group.sessions,
                zh,
                warnings,
            )?;
            total += count;
            writeln!(
                out,
                "{}",
                t(
                    "REINDEX_AGENT_DONE",
                    zh,
                    &[
                        ("agent", group.info.display_name.into()),
                        ("count", count.to_string())
                    ]
                )
            )?;
        }
        writeln!(
            out,
            "\n{}",
            t("REINDEX_DONE", zh, &[("count", total.to_string())])
        )?;
        return Ok(true);
    }
    let selection = query
        .as_ref()
        .map(|q| crate::query_filter::select(&scan.groups, q, zh, warnings))
        .transpose()?;
    let mut stats: BTreeMap<&str, MessageStats> = BTreeMap::new();
    let selected = selection.as_ref().map(|s| {
        s.matches
            .iter()
            .map(|m| (m.group, m.session))
            .collect::<std::collections::HashSet<_>>()
    });
    let mut total = MessageStats::default();
    let mut ages = [0_usize; 5];
    let today = jiff::Zoned::now().date();
    for (g, group) in scan.groups.iter().enumerate() {
        for (s, session) in group.sessions.iter().enumerate() {
            if selected
                .as_ref()
                .is_some_and(|selected| !selected.contains(&(g, s)))
            {
                continue;
            }
            stats
                .entry(group.info.display_name)
                .or_default()
                .add(session.message_count);
            total.add(session.message_count);
            let date: jiff::civil::Date = session.created_at.format_local("%Y-%m-%d").parse()?;
            let days = today.since((jiff::Unit::Day, date))?.get_days();
            ages[if days <= 0 {
                0
            } else if days == 1 {
                1
            } else if days <= 7 {
                2
            } else if days <= 30 {
                3
            } else {
                4
            }] += 1;
        }
    }
    if total.sessions == 0 {
        writeln!(
            out,
            "{}",
            t("STATS_NO_SESSIONS", zh, &[("days", days.to_string())])
        )?;
        return Ok(true);
    }
    writeln!(
        out,
        "{}\n",
        t("STATS_HEADER", zh, &[("days", days.to_string())])
    )?;
    writeln!(
        out,
        "{}",
        t(
            "STATS_TOTAL_SESSIONS",
            zh,
            &[("count", total.sessions.to_string())]
        )
    )?;
    writeln!(
        out,
        "{}\n",
        t(
            if total.unknown == 0 {
                "STATS_TOTAL_MESSAGES"
            } else {
                "STATS_KNOWN_MESSAGES"
            },
            zh,
            &[
                ("count", total.messages.to_string()),
                ("unknown_sessions", total.unknown.to_string())
            ]
        )
    )?;
    writeln!(out, "{}", t("STATS_BY_AGENT", zh, &[]))?;
    for (name, stats) in stats {
        writeln!(
            out,
            "{}",
            t(
                if stats.unknown == 0 {
                    "STATS_AGENT_ROW"
                } else {
                    "STATS_AGENT_ROW_WITH_UNKNOWN"
                },
                zh,
                &[
                    ("name", name.into()),
                    ("sessions", stats.sessions.to_string()),
                    ("messages", stats.messages.to_string()),
                    ("unknown_sessions", stats.unknown.to_string())
                ]
            )
        )?;
    }
    writeln!(out, "\n{}", t("STATS_BY_TIME", zh, &[]))?;
    for (key, count) in [
        "TIME_TODAY",
        "TIME_YESTERDAY",
        "TIME_THIS_WEEK",
        "TIME_THIS_MONTH",
        "TIME_OLDER",
    ]
    .into_iter()
    .zip(ages)
    {
        if count > 0 {
            writeln!(
                out,
                "{}",
                t(
                    "STATS_TIME_ROW",
                    zh,
                    &[("label", t(key, zh, &[])), ("count", count.to_string())]
                )
            )?;
        }
    }
    Ok(true)
}

#[derive(Default)]
struct MessageStats {
    sessions: usize,
    messages: usize,
    unknown: usize,
}

impl MessageStats {
    fn add(&mut self, count: Option<usize>) {
        self.sessions += 1;
        if let Some(count) = count {
            self.messages += count;
        } else {
            self.unknown += 1;
        }
    }
}
