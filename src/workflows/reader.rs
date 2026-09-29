use crate::terminal::reader::{Action, Reader};
use agent_dump_core::output::{diagnostics, i18n::t, render};
use std::io::Write;

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
    let scan = agent_dump_core::query::scanner::discover(
        operation.query.as_ref(),
        operation.days,
        zh,
        warnings,
    )?;
    let mut positions: Vec<_> = if let Some(query) = &operation.query {
        agent_dump_core::query::filter::select(
            &scan.groups,
            query,
            zh,
            warnings,
        )?
        .matches
        .into_iter()
        .map(|m| (m.group, m.session))
        .collect()
    } else {
        scan.groups
            .iter()
            .enumerate()
            .flat_map(|(g, group)| {
                (0..group.sessions.len()).map(move |s| (g, s))
            })
            .collect()
    };
    positions.sort_by_key(|&(g, s)| {
        std::cmp::Reverse(scan.groups[g].sessions[s].updated_at)
    });
    if positions.is_empty() {
        writeln!(out, "{}", t("READER_EMPTY", zh, &[]))?;
        return Ok(scan.failed_providers.is_empty() && !scan.groups.is_empty());
    }
    let rows = positions
        .iter()
        .map(|&(g, s)| {
            let group = &scan.groups[g];
            let session = &group.sessions[s];
            crate::terminal::tui::Row {
                title: render::safe_line(if session.title.trim().is_empty() {
                    &session.id
                } else {
                    &session.title
                }),
                detail: render::safe_line(&format!(
                    "{} · {}",
                    group.info.display_name,
                    session.updated_at.format_local("%m-%d %H:%M")
                )),
                group: format!("{}://{}", group.info.scheme, session.id),
            }
        })
        .collect();
    out.flush()?;
    let mut reader = Reader::new(rows, zh)?;
    let cache = agent_dump_core::session::cache::SessionDataCache::default();
    loop {
        let (g, s) = positions[reader.selected()];
        let group = &scan.groups[g];
        let session = &group.sessions[s];
        let mut notices = Vec::new();
        let data = cache.get(
            group.info.name,
            group.provider.as_ref(),
            session,
            zh,
            &mut |d| {
                writeln!(notices, "{}", diagnostics::record_warning(&d, zh))?;
                Ok(())
            },
        );
        if !notices.is_empty() {
            reader.status =
                render::safe_line(&String::from_utf8_lossy(&notices));
        }
        let error = data.as_ref().err().map(|e| {
            diagnostics::Diagnostic::unexpected(e.as_ref(), zh).render(zh)
        });
        match reader.next(
            data.as_ref().ok().map(std::convert::AsRef::as_ref),
            error.as_deref(),
        )? {
            Action::Select => {}
            Action::Quit => return Ok(true),
            Action::Export => {
                let mut result = Vec::new();
                let mut notices = Vec::new();
                let exported = super::uri::run(
                    &super::uri::UriOperation {
                        uri: format!("{}://{}", group.info.scheme, session.id),
                        head: false,
                        summary: false,
                        message: None,
                        before: 0,
                        after: 0,
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
