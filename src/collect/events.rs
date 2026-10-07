use crate::collect::model::Event;
use agent_dump_core::session::SessionData;
use jiff::civil::Date;
use std::collections::{BTreeMap, HashSet};
use std::sync::LazyLock;

pub fn extract(
    data: &SessionData,
    range: &std::ops::RangeInclusive<Date>,
    plan_chunks: bool,
) -> BTreeMap<Date, Vec<Vec<Event>>> {
    static IGNORE: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"(?i)^(?:hi|hello|thanks|thank you|你好|您好|好的|收到|明白|嗯嗯|ok|okay)[!！,.，。?？\s]*$").unwrap()
    });
    let mut dates: BTreeMap<Date, Vec<Vec<Event>>> = BTreeMap::new();
    for message in &data.messages {
        if !matches!(message.role.as_str(), "user" | "assistant") {
            continue;
        }
        let mut seen = HashSet::new();
        let segments =
            agent_dump_core::query::transcript::visible_segments(message);
        let repeated = segments.len() > 1;
        for (text, time) in segments {
            let text = agent_dump_core::query::text::normalize(&text);
            if text.is_empty()
                || IGNORE.is_match(&text)
                || (repeated
                    && !seen.insert((
                        time.map(agent_dump_core::session::timestamp::Timestamp::as_microsecond),
                        caseless::default_case_fold_str(&text),
                    )))
            {
                continue;
            }
            let Some(date) = time
                .map(agent_dump_core::session::timestamp::Timestamp::local_date)
                .filter(|date| range.contains(date))
            else {
                continue;
            };
            let chunks = dates.entry(date).or_default();
            if !plan_chunks {
                continue;
            }
            if chunks.is_empty() {
                chunks.push(Vec::new());
            }
            let mut size: usize = chunks
                .last()
                .unwrap()
                .iter()
                .map(|event: &Event| event.render().chars().count() + 1)
                .sum();
            let overhead = Event {
                role: message.role.clone(),
                text: String::new(),
            }
            .render()
            .chars()
            .count()
                + 1;
            let mut characters = text.chars().peekable();
            while characters.peek().is_some() {
                if !chunks.last().unwrap().is_empty()
                    && size + overhead + characters.clone().take(3201).count()
                        > 3200
                {
                    chunks.push(Vec::new());
                    size = 0;
                }
                let fragment: String =
                    characters.by_ref().take(3200 - size - overhead).collect();
                size += overhead + fragment.chars().count();
                chunks.last_mut().unwrap().push(Event {
                    role: message.role.clone(),
                    text: fragment,
                });
            }
        }
    }
    dates
}
