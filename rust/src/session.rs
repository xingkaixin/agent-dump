use jiff::{Timestamp, civil::DateTime, tz::TimeZone};
use serde::Serialize;
use std::path::PathBuf;

pub struct Session {
    pub id: String,
    pub title: String,
    pub created_at: Timestamp,
    pub updated_at: Timestamp,
    pub source_path: PathBuf,
    pub directory: String,
    pub version: String,
    pub model: String,
    pub message_count: Option<usize>,
}

#[derive(Clone, Serialize)]
pub struct SessionData {
    pub id: String,
    pub title: String,
    pub slug: Option<String>,
    pub directory: String,
    pub version: String,
    pub time_created: i64,
    pub time_updated: i64,
    pub summary_files: Option<Vec<String>>,
    pub stats: Stats,
    pub messages: Vec<Message>,
}

#[derive(Clone, Default, Serialize)]
pub struct Stats {
    pub total_cost: u64,
    pub total_input_tokens: i64,
    pub total_output_tokens: i64,
    pub message_count: usize,
}

#[derive(Clone, Serialize)]
pub struct Message {
    pub id: String,
    pub role: String,
    pub agent: Option<String>,
    pub mode: Option<String>,
    pub model: Option<String>,
    pub provider: Option<String>,
    pub time_created: i64,
    pub time_completed: Option<i64>,
    pub tokens: serde_json::Map<String, serde_json::Value>,
    pub cost: u64,
    pub parts: Vec<Part>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub nickname: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subagent_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_call_id: Option<String>,
}

impl Message {
    pub fn new(id: String, role: &str, time_created: i64, parts: Vec<Part>) -> Self {
        let role = match role {
            "user" | "assistant" | "developer" | "system" | "tool" | "branch_summary"
            | "compaction" | "custom" => role,
            _ => "unknown",
        };
        Self {
            id,
            role: role.into(),
            agent: None,
            mode: None,
            model: None,
            provider: None,
            time_created,
            time_completed: None,
            tokens: Default::default(),
            cost: 0,
            parts,
            nickname: None,
            subagent_id: None,
            tool_call_id: None,
        }
    }
}

#[derive(Clone, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Part {
    Text(TextPart),
    Reasoning(TextPart),
    Plan(PlanPart),
    Tool(Box<ToolPart>),
}

#[derive(Clone, PartialEq, Serialize)]
pub struct TextPart {
    pub text: String,
    pub time_created: i64,
}

#[derive(Clone, PartialEq, Serialize)]
pub struct PlanPart {
    pub input: String,
    pub output: Option<String>,
    pub approval_status: String,
    pub time_created: i64,
}

#[derive(Clone, PartialEq, Serialize)]
pub struct ToolPart {
    pub tool: String,
    #[serde(rename = "callID")]
    pub call_id: String,
    pub title: String,
    pub state: serde_json::Map<String, serde_json::Value>,
    pub time_created: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub nickname: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subagent_id: Option<String>,
}

impl Part {
    pub fn text(text: String, time_created: i64) -> Self {
        Self::Text(TextPart { text, time_created })
    }

    pub fn content(&self) -> Option<&str> {
        match self {
            Self::Text(part) | Self::Reasoning(part) => Some(&part.text),
            Self::Plan(part) => Some(&part.input),
            Self::Tool(_) => None,
        }
    }
}

pub fn parse_timestamp(value: &str) -> Option<Timestamp> {
    value.parse().ok().or_else(|| {
        value
            .parse::<DateTime>()
            .ok()?
            .to_zoned(TimeZone::UTC)
            .ok()
            .map(|time| time.timestamp())
    })
}

impl Session {
    pub fn display_location(&self) -> String {
        if self.directory.trim().is_empty() {
            self.source_path
                .parent()
                .unwrap_or(&self.source_path)
                .display()
                .to_string()
        } else {
            std::path::Path::new(self.directory.trim())
                .components()
                .collect::<PathBuf>()
                .display()
                .to_string()
        }
    }
}
