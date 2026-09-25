use crate::collect_model::Event;
use crate::session::SessionData;
use std::collections::HashSet;
use std::sync::LazyLock;

pub fn extract(data: &SessionData) -> (Vec<Vec<Event>>, bool) {
    static IGNORE: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"(?i)^(?:hi|hello|thanks|thank you|你好|您好|好的|收到|明白|嗯嗯|ok|okay)[!！,.，。?？\s]*$").unwrap()
    });
    let mut events = Vec::new();
    let mut used = 0;
    let mut truncated = false;
    'messages: for message in &data.messages {
        if !matches!(message.role.as_str(), "user" | "assistant") {
            continue;
        }
        let mut seen = HashSet::new();
        for text in crate::transcript::visible_texts(message) {
            let text = crate::query_text::normalize(&text);
            if text.is_empty()
                || IGNORE.is_match(&text)
                || !seen.insert(caseless::default_case_fold_str(&text))
            {
                continue;
            }
            let mut event = Event {
                role: message.role.clone(),
                text,
            };
            let size = event.render().chars().count() + 1;
            if used + size > 12_000 {
                let remaining =
                    12_000_usize.saturating_sub(used + size - event.text.chars().count());
                if remaining > 0 {
                    event.text = event.text.chars().take(remaining).collect();
                    events.push(event);
                }
                truncated = true;
                break 'messages;
            }
            used += size;
            events.push(event);
        }
    }
    let mut chunks = Vec::new();
    let mut chunk = Vec::new();
    let mut size = 0;
    for event in events {
        let event_size = event.render().chars().count() + 1;
        if !chunk.is_empty() && size + event_size > 3200 {
            chunks.push(std::mem::take(&mut chunk));
            size = 0;
        }
        chunk.push(event);
        size += event_size;
    }
    if !chunk.is_empty() {
        chunks.push(chunk);
    }
    (chunks, truncated)
}
