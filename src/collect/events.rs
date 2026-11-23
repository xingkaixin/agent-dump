use crate::collect::model::Event;
use agent_dump_core::query::text as query_text;
use agent_dump_core::query::transcript::visible_segments;
use agent_dump_core::session::SessionData;
use agent_dump_core::session::timestamp::Timestamp;
use jiff::civil::Date;
use std::collections::{BTreeMap, HashSet};
use std::sync::LazyLock;

fn is_ignored_greeting(raw: &str, ignore: &regex::Regex) -> bool {
    let mut normalized = String::new();
    let mut prev_ws = false;
    let mut saw_non_ws = false;
    for c in raw.chars() {
        if query_text::whitespace(c) {
            if saw_non_ws {
                prev_ws = true;
            }
        } else {
            if prev_ws {
                if normalized.len() < 16 {
                    normalized.push(' ');
                }
                prev_ws = false;
            }
            saw_non_ws = true;
            if normalized.len() >= 16 {
                if !matches!(
                    c,
                    '!' | '！' | ',' | '.' | '，' | '。' | '?' | '？'
                ) {
                    return false;
                }
            } else {
                normalized.push(c);
            }
        }
    }
    !saw_non_ws || ignore.is_match(&normalized)
}

pub fn extract(
    data: &SessionData,
    range: &std::ops::RangeInclusive<Date>,
    plan_chunks: bool,
) -> BTreeMap<Date, Vec<Vec<Event>>> {
    static IGNORE: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(concat!(
            r"(?i)^(?:hi|hello|thanks|thank you|",
            r"你好|您好|好的|收到|明白|嗯嗯|ok|okay)[!！,.，。?？\s]*$"
        ))
        .unwrap()
    });
    let mut dates: BTreeMap<Date, (Vec<Vec<Event>>, usize)> = BTreeMap::new();
    for message in &data.messages {
        if !matches!(message.role.as_str(), "user" | "assistant") {
            continue;
        }
        let mut seen = HashSet::new();
        let segments = visible_segments(message);
        let repeated = segments.len() > 1;
        let overhead = Event {
            role: message.role.clone(),
            text: String::new(),
        }
        .render()
        .chars()
        .count()
            + 1;
        for (text, time) in segments {
            let Some(date) = time
                .map(Timestamp::local_date)
                .filter(|date| range.contains(date))
            else {
                continue;
            };
            if !plan_chunks {
                if dates.contains_key(&date)
                    || is_ignored_greeting(&text, &IGNORE)
                {
                    continue;
                }
                dates.entry(date).or_default();
                continue;
            }
            let text = query_text::normalize(&text);
            if text.is_empty()
                || IGNORE.is_match(&text)
                || (repeated
                    && !seen.insert((
                        time.map(Timestamp::as_microsecond),
                        caseless::default_case_fold_str(&text),
                    )))
            {
                continue;
            }
            let (chunks, size) = dates.entry(date).or_default();
            if chunks.is_empty() {
                chunks.push(Vec::new());
            }
            let mut rest = text.as_str();
            while !rest.is_empty() {
                let available = 3200usize.saturating_sub(*size + overhead);
                if !chunks.last().unwrap().is_empty()
                    && (available == 0
                        || (rest.len() > available
                            && rest.char_indices().nth(available).is_some()))
                {
                    chunks.push(Vec::new());
                    *size = 0;
                }
                let take = 3200 - *size - overhead;
                let (split_byte, taken_chars) = if rest.len() <= take {
                    (rest.len(), rest.chars().count())
                } else {
                    let mut count = 0;
                    let mut byte = rest.len();
                    for (idx, _) in rest.char_indices() {
                        if count == take {
                            byte = idx;
                            break;
                        }
                        count += 1;
                    }
                    (byte, count)
                };
                let (fragment, tail) = rest.split_at(split_byte);
                rest = tail;
                *size += overhead + taken_chars;
                chunks.last_mut().unwrap().push(Event {
                    role: message.role.clone(),
                    text: fragment.to_owned(),
                });
            }
        }
    }
    dates
        .into_iter()
        .map(|(date, (chunks, _))| (date, chunks))
        .collect()
}
