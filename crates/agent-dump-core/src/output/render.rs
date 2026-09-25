use crate::session::{Part, Session, SessionData};
use std::fmt::Write;

const fn unsafe_char(c: char) -> bool {
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
pub fn head(
    uri: &str,
    session: &Session,
    display_name: &str,
    zh: bool,
) -> String {
    let unknown = if zh { "未知" } else { "unknown" };
    let fields = [
        ("URI", uri.to_owned()),
        ("Agent", display_name.into()),
        ("Title", session.title.clone()),
        (
            "Created",
            session.created_at.format_local("%Y-%m-%d %H:%M:%S %Z"),
        ),
        (
            "Updated",
            session.updated_at.format_local("%Y-%m-%d %H:%M:%S %Z"),
        ),
        ("CWD/Project", session.display_location()),
        ("Model", session.model.clone()),
        (
            "Message Count",
            session
                .message_count
                .map_or_else(|| unknown.into(), |n| n.to_string()),
        ),
        (
            "Subtargets",
            session
                .subtargets
                .iter()
                .filter(|text| !text.trim().is_empty())
                .take(5)
                .map(|text| truncate(text, 48))
                .collect::<Vec<_>>()
                .join(", "),
        ),
    ];
    let mut output = String::from("# Session Head\n\n");
    for (label, value) in fields {
        let value = if label == "Subtargets" {
            value
        } else {
            truncate(&value, 120)
        };
        let value = if value.is_empty() { "-" } else { &value };
        writeln!(output, "- {label}: {}", safe_line(value)).unwrap();
    }
    output
}

fn append_section(
    output: &mut String,
    index: &mut usize,
    role: &str,
    texts: &[&str],
) {
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
    let mut output =
        format!("# Session Dump\n\n- URI: `{}`\n\n", safe_line(uri));
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
                        prompt =
                            crate::compat::value::field(arguments, "message")
                                .trim()
                                .into();
                        if prompt.is_empty() {
                            prompt =
                                crate::compat::value::pretty_json(arguments);
                        }
                    }
                    Some(serde_json::Value::String(text)) => {
                        prompt = text.trim().into();
                    }
                    _ => (),
                }
            }
            if !prompt.is_empty() {
                let role = tool.nickname.as_ref().map_or_else(
                    || "Assistant".into(),
                    |name| format!("Assistant ({name})"),
                );
                append_section(&mut output, &mut index, &role, &[&prompt]);
            }
        }
    }
    // Python joins a trailing empty line; print adds the second newline.
    output.pop();
    output
}
pub fn list(
    groups: &[crate::providers::contract::SessionGroup],
    query: Option<&str>,
    days: i64,
    summary: bool,
    zh: bool,
) -> String {
    let mut output = list_banner();
    let header = match (zh, query) {
        (true, Some(names)) => {
            format!("📋 列出最近 {days} 天且匹配「{names}」的会话:")
        }
        (false, Some(names)) => {
            format!(
                "📋 Listing sessions from last {days} days matching '{names}':"
            )
        }
        (true, None) => format!("📋 列出最近 {days} 天的会话:"),
        (false, None) => format!("📋 Listing sessions from last {days} days:"),
    };
    writeln!(output, "{header}\n\n{}", "-".repeat(60)).unwrap();
    for group in groups {
        append_list_group(
            &mut output,
            &group.sessions,
            group.provider,
            days,
            summary,
            zh,
        );
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
pub fn list_banner() -> String {
    format!("🚀 Agent Session Exporter\n\n{}\n\n", "=".repeat(60))
}

fn append_list_group(
    output: &mut String,
    sessions: &[Session],
    provider: &crate::providers::contract::ProviderInfo,
    days: i64,
    summary: bool,
    zh: bool,
) {
    let display_name = provider.display_name;
    let scheme = provider.scheme;
    writeln!(
        output,
        "\n📁 {display_name} ({} {})",
        sessions.len(),
        if zh { "个会话" } else { "sessions" }
    )
    .unwrap();
    for session in sessions {
        let title = formatted_title(session);
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
        writeln!(output, "     {}", metadata_summary(session, scheme, zh))
            .unwrap();
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
}
pub fn formatted_title(session: &Session) -> String {
    let title = if session.title.chars().count() > 60 {
        format!("{}...", session.title.chars().take(60).collect::<String>())
    } else {
        session.title.clone()
    };
    safe_line(&format!(
        "{title} ({})",
        session.created_at.format_local("%Y-%m-%d %H:%M")
    ))
}
pub fn metadata_summary(session: &Session, scheme: &str, zh: bool) -> String {
    let mut fields = Vec::new();
    let location = session.display_location();
    if !location.trim().is_empty() {
        let parts: Vec<_> = std::path::Path::new(location.trim())
            .components()
            .filter(|part| {
                matches!(
                    part,
                    std::path::Component::Normal(_)
                        | std::path::Component::ParentDir
                )
            })
            .map(|part| part.as_os_str().to_string_lossy())
            .collect();
        let compact = if parts.is_empty() {
            location.clone()
        } else {
            parts[parts.len().saturating_sub(2)..].join("/")
        };
        fields.push(format!("cwd={}", truncate(&compact, 32)));
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
        session.updated_at.format_local("%Y-%m-%d %H:%M")
    ));
    fields.push(format!("uri={scheme}://{}", session.id));
    safe_line(&fields.join(" | "))
}
