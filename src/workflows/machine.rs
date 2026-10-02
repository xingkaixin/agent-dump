use agent_dump_core::query::{Query, filter::Selection, scanner::Scan};
use agent_dump_core::{providers::contract::ProviderInfo, session::Session};
use serde_json::{Value, json};
use std::io::Write;

pub type Locations = std::collections::BTreeMap<
    (usize, usize),
    Vec<agent_dump_core::query::context::Location>,
>;

pub fn session_record(info: &ProviderInfo, session: &Session) -> Value {
    json!({
        "uri": format!("{}://{}", info.scheme, session.id),
        "provider": info.name,
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at.iso_utc(),
        "updated_at": session.updated_at.iso_utc(),
        "working_directory": optional(&session.directory),
        "model": optional(&session.model),
        "message_count": session.message_count,
        "message_count_completeness": if session.message_count.is_some() { "exact" } else { "unknown" }
    })
}

pub fn list(
    scan: &Scan,
    selection: Option<&Selection>,
    query: Option<&Query>,
    locations: Option<&Locations>,
    out: &mut impl Write,
) -> crate::Result<bool> {
    let record = |g: usize, s: usize| {
        let group = &scan.groups[g];
        session_record(group.info, &group.sessions[s])
    };
    let search = query
        .is_some_and(|q| q.mode == agent_dump_core::query::text::Mode::Terms);
    let records: Vec<_> = if let Some(selection) = selection {
        selection
            .matches
            .iter()
            .map(|matched| {
                let mut value = record(matched.group, matched.session);
                if search {
                    value["rank"] = json!(matched.rank);
                    value["snippet"] = json!(matched.snippet);
                    if let Some(locations) = locations {
                        value["locations"] = json!(
                            locations.get(&(matched.group, matched.session))
                        );
                    }
                }
                value
            })
            .collect()
    } else {
        scan.groups
            .iter()
            .enumerate()
            .flat_map(|(g, group)| {
                let record = &record;
                (0..group.sessions.len()).map(move |s| record(g, s))
            })
            .collect()
    };
    write(
        if search { "search" } else { "list" },
        scan,
        selection,
        query,
        &json!(records),
        out,
    )
}

fn optional(text: &str) -> Option<&str> {
    (!text.is_empty()).then_some(text)
}

pub fn write(
    kind: &str,
    scan: &Scan,
    selection: Option<&Selection>,
    query: Option<&Query>,
    data: &Value,
    out: &mut impl Write,
) -> crate::Result<bool> {
    let mut failed_sessions: Vec<_> = selection
        .into_iter()
        .flat_map(|s| &s.failures)
        .map(|(provider, id)| json!({"provider": provider, "id": id}))
        .collect();
    failed_sessions.sort_by_key(Value::to_string);
    let success = !scan.groups.is_empty()
        || (scan.failed_providers.is_empty()
            && query.is_some_and(|q| q.providers.is_some()));
    serde_json::to_writer(
        &mut *out,
        &json!({
            "schema_version": 1,
            "kind": kind,
            "status": if !success { "error" } else if !scan.failed_providers.is_empty() || !failed_sessions.is_empty() { "partial" } else { "ok" },
            "failed_providers": scan.failed_providers,
            "failed_sessions": failed_sessions,
            "error": if success { None } else { Some("no_available_provider") },
            "data": data
        }),
    )?;
    writeln!(out)?;
    Ok(success)
}
