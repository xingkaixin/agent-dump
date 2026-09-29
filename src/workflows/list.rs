use agent_dump_core::output::diagnostics::Diagnostic;
use agent_dump_core::output::i18n::t;
use agent_dump_core::providers::contract::SessionGroup;
use agent_dump_core::query::Query;
use agent_dump_core::query::text::Mode;
use std::io::Write;

pub struct Options {
    pub summary: bool,
    pub ignored: (bool, bool),
    pub json: bool,
    pub locate: bool,
}

pub fn run(
    query: Option<&Query>,
    days: i64,
    options: &Options,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<bool> {
    let scan =
        agent_dump_core::query::scanner::discover(query, days, zh, warnings)?;
    if scan.groups.is_empty() && !options.json {
        let roots = match agent_dump_core::providers::registry::search_roots() {
            Ok(roots) => roots,
            Err(error) => {
                write!(
                    out,
                    "{}{}",
                    agent_dump_core::output::render::list_banner(),
                    Diagnostic::unexpected(error.as_ref(), zh).render(zh)
                )?;
                return Ok(false);
            }
        };
        let names = query
            .as_ref()
            .and_then(|q| q.providers.as_ref())
            .map(|names| names.iter().cloned().collect::<Vec<_>>().join(","));
        write!(
            out,
            "{}{}",
            agent_dump_core::output::render::list_banner(),
            Diagnostic::empty_list(names.as_deref(), roots, zh).render(zh)
        )?;
        return Ok(names.is_some());
    }
    let mut selection = query
        .as_ref()
        .map(|query| {
            agent_dump_core::query::filter::select(
                &scan.groups,
                query,
                zh,
                warnings,
            )
        })
        .transpose()?;
    let mut locations = std::collections::BTreeMap::new();
    if options.locate
        && let (Some(selection), Some(query)) = (&mut selection, query)
    {
        let cache =
            agent_dump_core::session::cache::SessionDataCache::default();
        for matched in &selection.matches {
            let group = &scan.groups[matched.group];
            let session = &group.sessions[matched.session];
            let result = cache
                .get(
                    group.info.name,
                    group.provider.as_ref(),
                    session,
                    zh,
                    &mut |diagnostic| {
                        writeln!(warnings, "{}", agent_dump_core::output::diagnostics::record_warning(&diagnostic, zh))?;
                        Ok(())
                    },
                )
                .and_then(|data| agent_dump_core::query::context::locate(&data, query));
            match result {
                Ok(found) => {
                    locations.insert((matched.group, matched.session), found);
                }
                Err(error) => {
                    selection
                        .failures
                        .insert((group.info.name.into(), session.id.clone()));
                    writeln!(
                        warnings,
                        "{}",
                        Diagnostic::unexpected(error.as_ref(), zh).render(zh)
                    )?;
                }
            }
        }
    }
    if options.json {
        for (present, key) in [
            (options.ignored.0, "LIST_IGNORE_FORMAT"),
            (options.ignored.1, "LIST_IGNORE_OUTPUT"),
        ] {
            if present {
                writeln!(warnings, "{}", t(key, zh, &[]))?;
            }
        }
        return super::machine::list(
            &scan,
            selection.as_ref(),
            query,
            options.locate.then_some(&locations),
            out,
        );
    }
    let mut ignored_text = String::new();
    for (present, key) in [
        (options.ignored.0, "LIST_IGNORE_FORMAT"),
        (options.ignored.1, "LIST_IGNORE_OUTPUT"),
    ] {
        if present {
            ignored_text += &(t(key, zh, &[]) + "\n");
        }
    }
    if let Some(query) = &query
        && query.mode == Mode::Terms
    {
        write!(
            out,
            "{}{}",
            agent_dump_core::output::render::list_banner(),
            ignored_text
        )?;
        writeln!(
            out,
            "{}",
            t(
                "SEARCH_HEADER",
                zh,
                &[("days", days.to_string()), ("query", query.summary(zh))]
            )
        )?;
        writeln!(out, "{}", "-".repeat(60))?;
        let matches = &selection.as_ref().unwrap().matches;
        if matches.is_empty() {
            writeln!(out, "{}", t("SEARCH_NO_RESULTS", zh, &[]))?;
        }
        for (i, matched) in matches.iter().enumerate() {
            let group = &scan.groups[matched.group];
            let session = &group.sessions[matched.session];
            writeln!(
                out,
                "\n{}. {}",
                i + 1,
                agent_dump_core::output::render::formatted_title(session)
            )?;
            for (key, value) in [
                ("SEARCH_RESULT_PROVIDER", group.info.display_name.to_owned()),
                (
                    "SEARCH_RESULT_UPDATED",
                    session.updated_at.format_local("%Y-%m-%d %H:%M:%S %Z"),
                ),
                (
                    "SEARCH_RESULT_URI",
                    format!("{}://{}", group.info.scheme, session.id),
                ),
                ("SEARCH_RESULT_RANK", rank_text(matched.rank)),
                ("SEARCH_RESULT_SNIPPET", matched.snippet.clone()),
            ] {
                writeln!(
                    out,
                    "   {}: {}",
                    t(key, zh, &[]),
                    agent_dump_core::output::render::safe_line(&value)
                )?;
            }
            if let Some(found) =
                locations.get(&(matched.group, matched.session))
            {
                for location in found {
                    writeln!(
                        out,
                        "   #{} [{}] {}\n      {}",
                        location.position,
                        location.role,
                        location.locator,
                        agent_dump_core::output::render::safe_line(
                            &location.snippet
                        )
                    )?;
                }
            }
        }
        writeln!(out, "\n{}", "=".repeat(60))?;
        return Ok(true);
    }
    let groups: Vec<_> = scan
        .groups
        .iter()
        .enumerate()
        .map(|(g, group)| SessionGroup {
            provider: group.info,
            sessions: selection.as_ref().map_or_else(
                || group.sessions.clone(),
                |selection| {
                    selection
                        .matches
                        .iter()
                        .filter(|m| m.group == g)
                        .map(|m| group.sessions[m.session].clone())
                        .collect()
                },
            ),
        })
        .collect();
    write!(
        out,
        "{}",
        agent_dump_core::output::render::list(
            &groups,
            query.map(|q| q.summary(zh)).as_deref(),
            days,
            options.summary,
            zh
        )
        .replacen(
            &agent_dump_core::output::render::list_banner(),
            &(agent_dump_core::output::render::list_banner() + &ignored_text),
            1
        )
    )?;
    Ok(true)
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "Finite BM25 scores have a bounded base-10 exponent"
)]
fn rank_text(rank: f64) -> String {
    if rank == 0.0 {
        return "0".into();
    }
    let exponent = rank.abs().log10().floor() as i32;
    if (-4..6).contains(&exponent) {
        let digits = usize::try_from((5 - exponent).max(0)).unwrap();
        let text = format!("{rank:.digits$}");
        if text.contains('.') {
            text.trim_end_matches('0').trim_end_matches('.').into()
        } else {
            text
        }
    } else {
        let text = format!("{rank:.5e}");
        let (mantissa, exp) = text.split_once('e').unwrap();
        let exp: i32 = exp.parse().unwrap();
        format!(
            "{}e{exp:+03}",
            mantissa.trim_end_matches('0').trim_end_matches('.')
        )
    }
}
