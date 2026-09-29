use crate::query::{Query, text::TextQuery, transcript::searchable_message};
use crate::session::SessionData;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fmt::Write;
use std::ops::Range;

#[derive(Serialize)]
pub struct Location {
    pub position: usize,
    pub locator: String,
    pub role: String,
    pub snippet: String,
}

pub fn revision(data: &SessionData) -> crate::Result<String> {
    let bytes = serde_json::to_vec(&(&data.id, &data.messages))?;
    let mut hash = String::with_capacity(64);
    for byte in Sha256::digest(bytes) {
        write!(hash, "{byte:02x}")?;
    }
    Ok(hash)
}

pub fn locate(
    data: &SessionData,
    query: &Query,
) -> crate::Result<Vec<Location>> {
    let revision = revision(data)?;
    let text =
        TextQuery::new(query.keyword.as_deref().unwrap_or(""), query.mode);
    let terms: Vec<_> = text
        .literals
        .iter()
        .map(|term| TextQuery::new(term, crate::query::text::Mode::Phrase))
        .collect();
    Ok(data
        .messages
        .iter()
        .enumerate()
        .filter_map(|(index, message)| {
            if query
                .roles
                .as_ref()
                .is_some_and(|roles| !roles.contains(&message.role))
            {
                return None;
            }
            let content = searchable_message(message);
            let evidence =
                terms.iter().find_map(|term| term.find(&[&content]))?;
            let position = index + 1;
            Some(Location {
                position,
                locator: format!("{revision}:{position}"),
                role: message.role.clone(),
                snippet: evidence.snippet,
            })
        })
        .collect())
}

pub fn window(
    data: &SessionData,
    locator: &str,
    before: usize,
    after: usize,
    zh: bool,
) -> crate::Result<Range<usize>> {
    let Some((expected, position)) = locator.split_once(':') else {
        return Err(
            crate::output::i18n::t("MESSAGE_LOCATOR_INVALID", zh, &[]).into()
        );
    };
    let position = position
        .parse::<usize>()
        .ok()
        .filter(|p| *p > 0 && *p <= data.messages.len());
    if expected != revision(data)? || position.is_none() {
        return Err(
            crate::output::i18n::t("MESSAGE_LOCATOR_STALE", zh, &[]).into()
        );
    }
    let index = position.unwrap() - 1;
    Ok(index.saturating_sub(before)
        ..index
            .saturating_add(after)
            .saturating_add(1)
            .min(data.messages.len()))
}
