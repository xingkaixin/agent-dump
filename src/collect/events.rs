use crate::collect::model::Event;
use agent_dump_core::session::SessionData;
use std::collections::HashSet;
use std::sync::LazyLock;

pub fn extract(data: &SessionData) -> Vec<Vec<Event>> {
    static IGNORE: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"(?i)^(?:hi|hello|thanks|thank you|你好|您好|好的|收到|明白|嗯嗯|ok|okay)[!！,.，。?？\s]*$").unwrap()
    });
    let mut chunks = Vec::new();
    let mut chunk = Vec::new();
    let mut size = 0;
    for message in &data.messages {
        if !matches!(message.role.as_str(), "user" | "assistant") {
            continue;
        }
        let mut seen = HashSet::new();
        for text in agent_dump_core::query::transcript::visible_texts(message) {
            let text = agent_dump_core::query::text::normalize(&text);
            if text.is_empty()
                || IGNORE.is_match(&text)
                || !seen.insert(caseless::default_case_fold_str(&text))
            {
                continue;
            }
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
                if !chunk.is_empty()
                    && size + overhead + characters.clone().take(3201).count()
                        > 3200
                {
                    chunks.push(std::mem::take(&mut chunk));
                    size = 0;
                }
                let fragment: String =
                    characters.by_ref().take(3200 - size - overhead).collect();
                size += overhead + fragment.chars().count();
                chunk.push(Event {
                    role: message.role.clone(),
                    text: fragment,
                });
            }
        }
    }
    if !chunk.is_empty() {
        chunks.push(chunk);
    }
    chunks
}
