use crate::i18n::{t, terminal};
use crate::session::Session;
use crate::tui::Row;
use std::io::{BufRead, Write};

fn input(
    out: &mut impl Write,
    reader: &mut impl BufRead,
    zh: bool,
) -> crate::Result<Option<String>> {
    write!(out, "> ")?;
    out.flush()?;
    let mut text = String::new();
    if reader.read_line(&mut text)? == 0 {
        writeln!(out, "\n{}", t("NO_INPUT_EXITING", zh, &[]))?;
        return Ok(None);
    }
    Ok(Some(text.trim().into()))
}

pub fn provider(
    rows: &[Row],
    zh: bool,
    out: &mut impl Write,
    reader: &mut impl BufRead,
) -> crate::Result<Option<usize>> {
    if crate::tui::available() {
        out.flush()?;
        return Ok(
            crate::tui::select(&t("SELECT_AGENT_PROMPT", zh, &[]), rows, false, 0, zh)?
                .and_then(|v| v.first().copied()),
        );
    }
    writeln!(
        out,
        "{}\n{}",
        t("AVAILABLE_AGENTS", zh, &[]),
        "-".repeat(80)
    )?;
    for (index, row) in rows.iter().enumerate() {
        writeln!(out, "{}. {}", index + 1, row.title)?;
    }
    writeln!(out, "\n{}", t("SELECT_AGENT_NUMBER", zh, &[]))?;
    let Some(text) = input(out, reader, zh)? else {
        return Ok(None);
    };
    match integer(&text) {
        Some(index) if index > 0 && index as usize <= rows.len() => Ok(Some(index as usize - 1)),
        Some(_) => {
            writeln!(
                out,
                "{}",
                terminal("INVALID_SELECTION", zh, &[("selection", text)])
            )?;
            Ok(None)
        }
        None => {
            writeln!(out, "{}", t("INVALID_INPUT_NUMBER", zh, &[]))?;
            Ok(None)
        }
    }
}

fn integer(value: &str) -> Option<i128> {
    let normalized: String = value.chars().map(crate::value::decimal_digit).collect();
    if normalized.contains("__")
        || normalized.starts_with('_')
        || normalized.ends_with('_')
        || normalized.starts_with("+_")
        || normalized.starts_with("-_")
    {
        return None;
    }
    normalized.replace('_', "").parse().ok()
}

pub fn sessions(
    sessions: &[Session],
    scheme: &str,
    summary: bool,
    zh: bool,
    out: &mut impl Write,
    reader: &mut impl BufRead,
) -> crate::Result<Vec<usize>> {
    let today = jiff::Zoned::now().date();
    let keys = [
        "TIME_TODAY",
        "TIME_YESTERDAY",
        "TIME_THIS_WEEK",
        "TIME_THIS_MONTH",
        "TIME_OLDER",
    ];
    let mut groups: [Vec<usize>; 5] = Default::default();
    for (index, session) in sessions.iter().enumerate() {
        let days = today
            .since((jiff::Unit::Day, session.created_at.local_date()))?
            .get_days();
        let group = match days {
            ..=0 => 0,
            1 => 1,
            2..=7 => 2,
            8..=30 => 3,
            _ => 4,
        };
        groups[group].push(index);
    }
    let mut rows = Vec::new();
    let mut map = Vec::new();
    for (group, indices) in groups.iter().enumerate().filter(|(_, v)| !v.is_empty()) {
        let group_title = t(keys[group], zh, &[]);
        for (position, &index) in indices.iter().enumerate() {
            let session = &sessions[index];
            let mut title = crate::render::formatted_title(session);
            let detail = if summary {
                crate::render::metadata_summary(session, scheme, zh)
            } else {
                title += &format!(
                    " {}",
                    crate::render::safe_line(&format!("{scheme}://{}", session.id))
                );
                String::new()
            };
            rows.push(Row {
                title,
                detail,
                group: if position == 0 {
                    format!(
                        "[{group_title}] ({} {})",
                        indices.len(),
                        t("SESSION_COUNT_SUFFIX", zh, &[])
                    )
                } else {
                    String::new()
                },
            });
            map.push(index);
        }
    }
    if crate::tui::available() {
        out.flush()?;
        return Ok(
            crate::tui::select(&t("SELECT_SESSIONS_PROMPT", zh, &[]), &rows, true, 0, zh)?
                .unwrap_or_default()
                .iter()
                .map(|i| map[*i])
                .collect(),
        );
    }
    writeln!(
        out,
        "{}\n{}",
        t("AVAILABLE_SESSIONS", zh, &[]),
        "-".repeat(80)
    )?;
    for (index, row) in rows.iter().enumerate() {
        if !row.group.is_empty() {
            writeln!(out, "\n{}", row.group)?;
        }
        writeln!(out, "{}. {}", index + 1, row.title)?;
        if !row.detail.is_empty() {
            writeln!(out, "    {}", row.detail)?;
        }
    }
    writeln!(out, "\n{}", t("ENTER_SESSION_NUMBERS", zh, &[]))?;
    let Some(text) = input(out, reader, zh)? else {
        return Ok(Vec::new());
    };
    if text.eq_ignore_ascii_case("all") {
        return Ok((0..sessions.len()).collect());
    }
    let Some(indices) = text
        .split(',')
        .map(|v| integer(v.trim()))
        .collect::<Option<Vec<_>>>()
    else {
        writeln!(out, "{}", t("INVALID_INPUT_NUMBERS", zh, &[]))?;
        return Ok(Vec::new());
    };
    let mut selected = Vec::new();
    for index in indices {
        if index > 0 && (index as usize) <= map.len() {
            selected.push(map[index as usize - 1]);
        } else {
            writeln!(
                out,
                "{}",
                t("INVALID_SELECTION", zh, &[("selection", index.to_string())])
            )?;
        }
    }
    Ok(selected)
}
