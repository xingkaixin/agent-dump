use crate::session::{Part, Session, SessionData};
use jiff::tz::TimeZone;
use std::fmt::Write;

fn unsafe_char(c: char) -> bool {
    matches!(c, '\u{0}'..='\u{8}' | '\u{b}'..='\u{1f}' | '\u{7f}'..='\u{9f}' | '\u{61c}' | '\u{200e}' | '\u{200f}' | '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')
}

pub fn safe_body(text: &str) -> String {
    text.chars().filter(|c| !unsafe_char(*c)).collect()
}

pub fn safe_line(text: &str) -> String {
    let replaced: String = text
        .chars()
        .map(|c| if unsafe_char(c) { ' ' } else { c })
        .collect();
    let collapsed = replaced.split_whitespace().collect::<Vec<_>>().join(" ");
    if collapsed.chars().count() > 500 {
        format!("{}…", collapsed.chars().take(499).collect::<String>())
    } else {
        collapsed
    }
}

fn truncate(text: &str, limit: usize) -> String {
    let text = text.trim();
    if text.chars().count() > limit {
        format!(
            "{}...",
            text.chars().take(limit - 3).collect::<String>().trim_end()
        )
    } else {
        text.to_owned()
    }
}

pub fn head(uri: &str, session: &Session, display_name: &str, zh: bool) -> String {
    let unknown = if zh { "未知" } else { "unknown" };
    let fields = [
        ("URI", uri.to_owned()),
        ("Agent", display_name.into()),
        ("Title", session.title.clone()),
        (
            "Created",
            session
                .created_at
                .to_zoned(TimeZone::system())
                .strftime("%Y-%m-%d %H:%M:%S %Z")
                .to_string(),
        ),
        (
            "Updated",
            session
                .updated_at
                .to_zoned(TimeZone::system())
                .strftime("%Y-%m-%d %H:%M:%S %Z")
                .to_string(),
        ),
        ("CWD/Project", session.display_location()),
        ("Model", session.model.clone()),
        (
            "Message Count",
            session
                .message_count
                .map_or_else(|| unknown.into(), |n| n.to_string()),
        ),
        ("Subtargets", "-".into()),
    ];
    let mut output = String::from("# Session Head\n\n");
    for (label, value) in fields {
        let value = truncate(&value, 120);
        let value = if value.is_empty() { "-" } else { &value };
        writeln!(output, "- {label}: {}", safe_line(value)).unwrap();
    }
    output
}

fn append_section(output: &mut String, index: &mut usize, role: &str, texts: &[&str]) {
    if texts.is_empty() {
        return;
    }
    writeln!(output, "## {index}. {}\n", safe_line(role)).unwrap();
    for text in texts {
        if !text.is_empty() {
            writeln!(output, "{}\n", safe_body(text)).unwrap();
        }
    }
    *index += 1;
}

pub fn transcript(uri: &str, data: &SessionData) -> String {
    let mut output = format!("# Session Dump\n\n- URI: `{}`\n\n", safe_line(uri));
    let mut index = 1;
    for message in &data.messages {
        if message.role == "developer" {
            continue;
        }
        if message.role != "tool" {
            let texts: Vec<_> = message
                .parts
                .iter()
                .filter_map(Part::content)
                .map(str::trim)
                .filter(|v| !v.is_empty())
                .collect();
            let mut role = message.role.clone();
            if let Some(first) = role.get_mut(..1) {
                first.make_ascii_uppercase();
            }
            if message.role == "assistant"
                && let Some(nickname) = &message.nickname
            {
                role = format!("Assistant ({nickname})");
            }
            append_section(&mut output, &mut index, &role, &texts);
        }
        if !matches!(message.role.as_str(), "assistant" | "tool") {
            continue;
        }
        for part in &message.parts {
            let Part::Tool(tool) = part else {
                continue;
            };
            if tool.tool != "subagent" {
                continue;
            }
            let mut prompt = tool
                .state
                .get("prompt")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("")
                .trim()
                .to_owned();
            if prompt.is_empty() {
                match tool
                    .state
                    .get("arguments")
                    .or_else(|| tool.state.get("input"))
                {
                    Some(arguments @ serde_json::Value::Object(_)) => {
                        prompt = crate::value::field(arguments, "message").trim().into();
                        if prompt.is_empty() {
                            prompt = crate::value::pretty_json(arguments);
                        }
                    }
                    Some(serde_json::Value::String(text)) => prompt = text.trim().into(),
                    _ => (),
                }
            }
            if !prompt.is_empty() {
                let role = tool
                    .nickname
                    .as_ref()
                    .map_or_else(|| "Assistant".into(), |name| format!("Assistant ({name})"));
                append_section(&mut output, &mut index, &role, &[&prompt]);
            }
        }
    }
    // Python joins a trailing empty line; print adds the second newline.
    output.pop();
    output
}

pub fn list(
    sessions: &[Session],
    provider: &crate::provider::ProviderInfo,
    days: i64,
    summary: bool,
    zh: bool,
) -> String {
    let name = provider.name;
    let scheme = provider.scheme;
    let display_name = provider.display_name;
    let header = format!("🚀 Agent Session Exporter\n\n{}\n\n", "=".repeat(60));
    let mut output = header
        + &if zh {
            format!("📋 列出最近 {days} 天且匹配「providers={name}」的会话:\n\n")
        } else {
            format!("📋 Listing sessions from last {days} days matching 'providers={name}':\n\n")
        };
    writeln!(output, "{}", "-".repeat(60)).unwrap();
    writeln!(
        output,
        "\n📁 {display_name} ({} {})",
        sessions.len(),
        if zh { "个会话" } else { "sessions" }
    )
    .unwrap();
    for session in sessions {
        let title = if session.title.chars().count() > 60 {
            format!("{}...", session.title.chars().take(60).collect::<String>())
        } else {
            session.title.clone()
        };
        let title = safe_line(&format!(
            "{title} ({})",
            session
                .created_at
                .to_zoned(TimeZone::system())
                .strftime("%Y-%m-%d %H:%M")
        ));
        if !summary {
            writeln!(
                output,
                "   • {title} {}",
                safe_line(&format!("{scheme}://{}", session.id))
            )
            .unwrap();
            continue;
        }
        writeln!(output, "   • {title}").unwrap();
        let mut fields = Vec::new();
        let location = session.display_location();
        if !location.trim().is_empty() {
            let parts: Vec<_> = location.split('/').filter(|v| !v.is_empty()).collect();
            fields.push(format!(
                "cwd={}",
                truncate(&parts[parts.len().saturating_sub(2)..].join("/"), 32)
            ));
        }
        if !session.model.trim().is_empty() {
            fields.push(format!("model={}", truncate(&session.model, 24)));
        }
        fields.push(format!(
            "msgs={}",
            session.message_count.map_or_else(
                || if zh { "未知" } else { "unknown" }.into(),
                |n| n.to_string()
            )
        ));
        fields.push(format!(
            "updated={}",
            session
                .updated_at
                .to_zoned(TimeZone::system())
                .strftime("%Y-%m-%d %H:%M")
        ));
        fields.push(format!("uri={scheme}://{}", session.id));
        writeln!(output, "     {}", safe_line(&fields.join(" | "))).unwrap();
    }
    if sessions.is_empty() {
        writeln!(
            output,
            "{}",
            if zh {
                format!("   (最近 {days} 天内无会话)")
            } else {
                format!("   (No sessions in last {days} days)")
            }
        )
        .unwrap();
    }
    writeln!(output, "\n{}", "=".repeat(60)).unwrap();
    writeln!(
        output,
        "{}\n",
        if zh {
            "提示: 使用 --interactive 进入交互式导出模式"
        } else {
            "Hint: Use --interactive for interactive export mode"
        }
    )
    .unwrap();
    output
}
