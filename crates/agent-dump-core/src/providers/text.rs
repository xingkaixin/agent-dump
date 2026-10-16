use crate::session::{Message, Part};
use regex::Regex;
use serde_json::Value;
use std::sync::LazyLock;

static PATTERNS: LazyLock<Vec<(Regex, &'static str)>> = LazyLock::new(|| {
    let mut patterns = Vec::new();
    for tag in [
        "command-message",
        "command-name",
        "local-command-caveat",
        "local-command-stdout",
        "system-reminder",
    ] {
        // ASCII word boundaries keep `<system-reminder中文>` a tag, as in
        // CodeSesh.
        for (pattern, replacement) in [
            (
                format!(
                    r"(?is)(^|\r?\n)[ \t]*<{tag}(?-u:\b)[^>]*>.*?</{tag}>[ \t]*(?:\r?\n|$)"
                ),
                "$1",
            ),
            (format!(r"(?is)<{tag}(?-u:\b)[^>]*>.*?</{tag}>"), ""),
            (format!(r"(?is)\n*<{tag}(?-u:\b)[^>]*>.*$"), ""),
        ] {
            patterns.push((Regex::new(&pattern).unwrap(), replacement));
        }
    }
    patterns.push((
        Regex::new(
            r"(?i)</?(?:command-message|command-name|local-command-caveat|local-command-stdout|system-reminder|command-args)(?-u:\b)[^>]*>",
        )
        .unwrap(),
        "",
    ));
    patterns
});

pub fn clean(value: &str) -> String {
    let mut stripped = value.to_owned();
    if stripped.contains('<') {
        for (pattern, replacement) in PATTERNS.iter() {
            if let std::borrow::Cow::Owned(updated) =
                pattern.replace_all(&stripped, *replacement)
            {
                stripped = updated;
            }
        }
    }
    let mut output = String::with_capacity(stripped.len());
    for (index, line) in stripped.split('\n').enumerate() {
        if index > 0 {
            output.push('\n');
        }
        match line.strip_suffix('\r') {
            Some(line) => {
                output.push_str(line.trim_end_matches([' ', '\t']));
                output.push('\r');
            }
            None => output.push_str(line.trim_end_matches([' ', '\t'])),
        }
    }
    if output.trim().is_empty() {
        return String::new();
    }
    output.truncate(output.trim_end_matches(['\r', '\n']).len());
    output
}

pub fn clean_messages(messages: &mut Vec<Message>) {
    messages.retain_mut(|message| {
        let had_parts = !message.parts.is_empty();
        message.parts.retain_mut(clean_part);
        !had_parts || !message.parts.is_empty() || has_usage(message)
    });
}

fn clean_part(part: &mut Part) -> bool {
    match part {
        Part::Text(text) | Part::Reasoning(text) => {
            text.text = clean(&text.text);
            !text.text.is_empty()
        }
        Part::Plan(plan) => {
            plan.input = clean(&plan.input);
            !plan.input.is_empty()
        }
        Part::Tool(tool) => {
            tool.title = clean(&tool.title);
            for key in ["input", "output", "error", "metadata"] {
                if let Some(value) = tool.state.get_mut(key) {
                    clean_value(value);
                }
            }
            true
        }
        _ => true,
    }
}

fn clean_value(value: &mut Value) {
    match value {
        Value::String(text) => *text = clean(text),
        Value::Array(values) => values.iter_mut().for_each(clean_value),
        Value::Object(values) => values.values_mut().for_each(clean_value),
        _ => {}
    }
}

fn has_usage(message: &Message) -> bool {
    fn positive(value: &Value) -> bool {
        match value {
            Value::Number(number) => number.as_f64().is_some_and(|n| n > 0.0),
            Value::Object(values) => values.values().any(positive),
            _ => false,
        }
    }
    message.cost.as_f64().is_some_and(|cost| cost > 0.0)
        || message.tokens.values().any(positive)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::session::TextPart;

    #[test]
    fn strips_system_tags_and_trailing_whitespace() {
        for (input, expected) in [
            (
                "<command-name>/clear</command-name>\n<command-message>clear</command-message>\n<command-args></command-args>",
                "",
            ),
            (
                "before \n<system-reminder>\nhidden\n</system-reminder>\nafter\t\n\n",
                "before\nafter",
            ),
            (
                "keep <system-reminder>inline</system-reminder>text",
                "keep text",
            ),
            ("visible\n<system-reminder>unterminated", "visible"),
            (
                "<system-reminder中文>hidden</system-reminder>visible",
                "visible",
            ),
            (
                "<system-reminder_extra>visible",
                "<system-reminder_extra>visible",
            ),
            ("  indented\r\nline  \r\n", "  indented\r\nline"),
        ] {
            assert_eq!(clean(input), expected, "{input:?}");
        }
    }

    #[test]
    fn drops_only_messages_emptied_by_cleaning() {
        let text = |text: &str| {
            Part::Text(TextPart {
                text: text.into(),
                time_created: 0,
            })
        };
        let mut used = Message::new(
            "used".into(),
            "assistant",
            0,
            vec![text("<system-reminder>x</system-reminder>")],
        );
        used.tokens.insert("output_tokens".into(), 3.into());
        let mut messages = vec![
            Message::new(
                "tags".into(),
                "user",
                0,
                vec![text("<local-command-stdout>ok</local-command-stdout>")],
            ),
            Message::new("empty".into(), "user", 0, Vec::new()),
            Message::new("text".into(), "user", 0, vec![text("hi \n")]),
            used,
        ];
        clean_messages(&mut messages);
        let ids: Vec<_> =
            messages.iter().map(|message| message.id.as_str()).collect();
        assert_eq!(ids, ["empty", "text", "used"]);
        assert!(messages[2].parts.is_empty());
        assert!(
            matches!(&messages[1].parts[0], Part::Text(part) if part.text == "hi")
        );
    }
}
