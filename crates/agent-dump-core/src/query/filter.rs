use crate::query::Query;
use crate::query::scanner::ScannedProvider;
use crate::query::text::{Mode, TextQuery};
use crate::session::cache::SessionDataCache;
use std::collections::{HashMap, HashSet};
use std::io::Write;

pub struct Match {
    pub group: usize,
    pub session: usize,
    pub snippet: String,
    pub rank: f64,
}

#[derive(Default)]
pub struct Selection {
    pub matches: Vec<Match>,
    pub failures: HashSet<(String, String)>,
}

pub fn select(
    groups: &[ScannedProvider],
    query: &Query,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<Selection> {
    let text =
        TextQuery::new(query.keyword.as_deref().unwrap_or(""), query.mode);
    let mut selection = None;
    if query.roles.is_none() && !text.literals.is_empty() && !groups.is_empty()
    {
        let result = indexed(groups, query, &text, zh, warnings);
        match result {
            Ok(result) => selection = Some(result),
            Err(error) => {
                let kind = if error.is::<rusqlite::Error>() {
                    "DatabaseError"
                } else if let Some(error) =
                    error.downcast_ref::<crate::storage::source_io::Error>()
                {
                    error.kind
                } else {
                    "OSError"
                };
                writeln!(
                    warnings,
                    "{}",
                    crate::output::i18n::terminal(
                        "WARN_INDEX_UNUSABLE",
                        zh,
                        &[
                            ("agent", groups[0].info.display_name.into()),
                            ("error_type", kind.into()),
                            ("error", error.to_string())
                        ]
                    )
                )?;
            }
        }
    }
    let indexed = selection.is_some();
    let mut selection = match selection {
        Some(s) => s,
        None => fallback(groups, query, &text, zh, warnings)?,
    };
    selection.matches.sort_by(|a, b| {
        let sa = &groups[a.group].sessions[a.session];
        let sb = &groups[b.group].sessions[b.session];
        let time = || {
            sb.updated_at
                .cmp(&sa.updated_at)
                .then_with(|| sb.created_at.cmp(&sa.created_at))
                .then_with(|| {
                    groups[a.group].info.name.cmp(groups[b.group].info.name)
                })
                .then_with(|| sa.id.cmp(&sb.id))
        };
        if query.mode == Mode::Terms {
            b.rank.total_cmp(&a.rank).then_with(time)
        } else if query.limit.is_some() {
            time()
        } else if indexed {
            a.group
                .cmp(&b.group)
                .then_with(|| b.rank.total_cmp(&a.rank))
                .then_with(time)
        } else {
            a.group
                .cmp(&b.group)
                .then_with(|| a.session.cmp(&b.session))
        }
    });
    if let Some(limit) = query.limit {
        selection.matches.truncate(limit);
    }
    Ok(selection)
}

fn indexed(
    groups: &[ScannedProvider],
    query: &Query,
    text: &TextQuery,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<Selection> {
    let mut index = crate::query::index::SearchIndex::open(
        groups.iter().map(|g| g.provider.source_root().to_owned()),
    )?;
    let mut selection = Selection::default();
    let mut positions = HashMap::new();
    for (g, group) in groups.iter().enumerate() {
        for (s, session) in group.sessions.iter().enumerate() {
            if query.includes_path(&session.directory) {
                positions.insert(
                    (group.info.name.to_owned(), session.id.clone()),
                    (g, s),
                );
            }
        }
        let (_, failed) = index.update(
            group.info,
            group.provider.as_ref(),
            &group.sessions,
            zh,
            warnings,
        )?;
        for id in failed {
            let key = (group.info.name.to_owned(), id);
            if positions.contains_key(&key) {
                selection.failures.insert(key);
            }
        }
    }
    let keys = positions.keys().cloned().collect();
    for result in index.search(text, &keys)? {
        if let Some(&(group, session)) =
            positions.get(&(result.provider, result.id))
        {
            selection.matches.push(Match {
                group,
                session,
                snippet: result.snippet,
                rank: result.rank,
            });
        }
    }
    Ok(selection)
}

fn fallback(
    groups: &[ScannedProvider],
    query: &Query,
    text: &TextQuery,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<Selection> {
    let mut selection = Selection::default();
    let cache = SessionDataCache::default();
    for (g, group) in groups.iter().enumerate() {
        for (s, session) in group.sessions.iter().enumerate() {
            if !query.includes_path(&session.directory) {
                continue;
            }
            if text.literals.is_empty() && query.roles.is_none() {
                selection.matches.push(Match {
                    group: g,
                    session: s,
                    snippet: session.title.clone(),
                    rank: 0.0,
                });
                continue;
            }
            let data = match cache.lease(
                group.info.name,
                group.provider.as_ref(),
                session,
                zh,
                &mut |d| {
                    writeln!(
                        warnings,
                        "{}",
                        crate::output::diagnostics::record_warning(&d, zh)
                    )?;
                    Ok(())
                },
            ) {
                Ok(data) => data,
                Err(error) => {
                    selection
                        .failures
                        .insert((group.info.name.into(), session.id.clone()));
                    writeln!(
                        warnings,
                        "{}",
                        crate::output::i18n::terminal(
                            "WARN_SESSION_READ_SKIPPED",
                            zh,
                            &[
                                (
                                    "uri",
                                    format!(
                                        "{}://{}",
                                        group.info.scheme, session.id
                                    )
                                ),
                                ("error", error.to_string())
                            ]
                        )
                    )?;
                    continue;
                }
            };
            let evidence = if let Some(roles) = &query.roles {
                data.messages
                    .iter()
                    .filter(|message| {
                        roles.contains(&message.role.to_lowercase())
                    })
                    .find_map(|message| {
                        let content =
                            crate::query::transcript::message_texts(message)
                                .join("\n");
                        if text.literals.is_empty() {
                            let normalized =
                                crate::query::text::normalize(&content);
                            let excerpt: String =
                                normalized.chars().take(96).collect();
                            let snippet = if normalized.chars().count() > 96 {
                                format!("{}...", excerpt.trim_end())
                            } else {
                                excerpt
                            };
                            Some((snippet, 0.0))
                        } else {
                            text.find(&[&content]).map(|e| (e.snippet, 0.0))
                        }
                    })
            } else {
                text.find(&[
                    &session.title,
                    &crate::query::transcript::searchable(&data),
                ])
                .map(|e| (e.snippet, if e.title_matches { 1.0 } else { 0.0 }))
            };
            if let Some((snippet, rank)) = evidence {
                selection.matches.push(Match {
                    group: g,
                    session: s,
                    snippet,
                    rank,
                });
            }
        }
    }
    Ok(selection)
}
