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
        Regex::new(concat!(
            r"(?i)</?(?:command-message|command-name|local-command-caveat|",
            r"local-command-stdout|system-reminder|command-args)(?-u:\b)[^>]*>",
        ))
        .unwrap(),
        "",
    ));
    patterns
});

// Every pattern needs one of these openers, so most text skips all of them.
static TAG: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(concat!(
        r"(?i)</?(?:command-message|command-name|local-command-caveat|",
        r"local-command-stdout|system-reminder|command-args)",
    ))
    .unwrap()
});

fn has_trailing_line_space(value: &str) -> bool {
    let bytes = value.as_bytes();
    let len = bytes.len();
    for (i, &b) in bytes.iter().enumerate() {
        if matches!(b, b' ' | b'\t')
            && (i + 1 == len || matches!(bytes[i + 1], b'\n' | b'\r'))
        {
            return true;
        }
    }
    false
}

fn trim_lines_into(source: &str, output: &mut String) {
    for (index, line) in source.split('\n').enumerate() {
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
}

fn strip_tags(value: &str) -> Option<String> {
    if !value.contains('<') || !TAG.is_match(value) {
        return None;
    }
    let mut stripped = value.to_owned();
    for (pattern, replacement) in PATTERNS.iter() {
        if let std::borrow::Cow::Owned(updated) =
            pattern.replace_all(&stripped, *replacement)
        {
            stripped = updated;
        }
    }
    Some(stripped)
}

pub fn clean(value: &str) -> String {
    let stripped = strip_tags(value);
    let source = stripped.as_deref().unwrap_or(value);
    if !has_trailing_line_space(source) {
        if source.trim().is_empty() {
            return String::new();
        }
        let len = source.trim_end_matches(['\r', '\n']).len();
        return if let Some(mut owned) = stripped {
            owned.truncate(len);
            owned
        } else {
            source[..len].to_owned()
        };
    }
    let mut output = String::with_capacity(source.len());
    trim_lines_into(source, &mut output);
    if output.trim().is_empty() {
        return String::new();
    }
    output.truncate(output.trim_end_matches(['\r', '\n']).len());
    output
}

pub fn clean_in_place(value: &mut String) {
    if let Some(stripped) = strip_tags(value) {
        *value = stripped;
    }
    if !has_trailing_line_space(value) {
        if value.trim().is_empty() {
            value.clear();
        } else {
            let len = value.trim_end_matches(['\r', '\n']).len();
            value.truncate(len);
        }
        return;
    }
    let mut output = String::with_capacity(value.len());
    trim_lines_into(value, &mut output);
    if output.trim().is_empty() {
        value.clear();
        return;
    }
    output.truncate(output.trim_end_matches(['\r', '\n']).len());
    *value = output;
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
            clean_in_place(&mut text.text);
            !text.text.is_empty()
        }
        Part::Plan(plan) => {
            clean_in_place(&mut plan.input);
            !plan.input.is_empty()
        }
        Part::Tool(tool) => {
            clean_in_place(&mut tool.title);
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
        Value::String(text) => clean_in_place(text),
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
