use crate::diagnostics::Diagnostic;
use crate::i18n::t;
use crate::provider::SessionGroup;
use crate::query::Query;
use crate::query_text::Mode;
use std::io::Write;

pub fn run(
    query: Option<Query>,
    days: i64,
    summary: bool,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<bool> {
    let scan = crate::scanner::discover(query.as_ref(), days, zh, warnings)?;
    if scan.groups.is_empty() {
        let roots = match crate::registry::search_roots() {
            Ok(roots) => roots,
            Err(error) => {
                write!(
                    out,
                    "{}{}",
                    crate::render::list_banner(),
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
            crate::render::list_banner(),
            Diagnostic::empty_list(names.as_deref(), roots, zh).render(zh)
        )?;
        return Ok(names.is_some());
    }
    let selection = query
        .as_ref()
        .map(|query| crate::query_filter::select(&scan.groups, query, zh, warnings))
        .transpose()?;
    if let Some(query) = &query
        && query.mode == Mode::Terms
    {
        write!(out, "{}", crate::render::list_banner())?;
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
                crate::render::formatted_title(session)
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
                    crate::render::safe_line(&value)
                )?;
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
        crate::render::list(
            &groups,
            query.as_ref().map(|q| q.summary(zh)).as_deref(),
            days,
            summary,
            zh
        )
    )?;
    Ok(true)
}

fn rank_text(rank: f64) -> String {
    if rank == 0.0 {
        return "0".into();
    }
    let exponent = rank.abs().log10().floor() as i32;
    if !(-4..6).contains(&exponent) {
        let text = format!("{rank:.5e}");
        let (mantissa, exp) = text.split_once('e').unwrap();
        let exp: i32 = exp.parse().unwrap();
        format!(
            "{}e{exp:+03}",
            mantissa.trim_end_matches('0').trim_end_matches('.')
        )
    } else {
        let digits = (5 - exponent).max(0) as usize;
        let text = format!("{rank:.digits$}");
        if text.contains('.') {
            text.trim_end_matches('0').trim_end_matches('.').into()
        } else {
            text
        }
    }
}
