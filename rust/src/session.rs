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
    pub version: serde_json::Value,
    pub model: String,
    pub project: Option<String>,
    pub message_count: Option<usize>,
}

#[derive(Clone, Serialize)]
pub struct SessionData {
    pub id: String,
    pub title: String,
    pub slug: Option<String>,
    pub directory: String,
    pub version: serde_json::Value,
    pub time_created: i64,
    pub time_updated: i64,
    pub summary_files: Option<Vec<String>>,
    pub stats: Stats,
    pub messages: Vec<Message>,
}

#[derive(Clone, Serialize)]
pub struct Stats {
    pub total_cost: serde_json::Number,
    pub total_input_tokens: i64,
    pub total_output_tokens: i64,
    pub message_count: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_tokens: Option<i64>,
}

impl Default for Stats {
    fn default() -> Self {
        Self {
            total_cost: 0.into(),
            total_input_tokens: 0,
            total_output_tokens: 0,
            message_count: 0,
            total_tokens: None,
        }
    }
}

impl Stats {
    pub fn add_tokens(
        &mut self,
        input: &serde_json::Value,
        output: &serde_json::Value,
    ) -> crate::Result<()> {
        self.total_input_tokens = self
            .total_input_tokens
            .checked_add(crate::value::integer(input))
            .ok_or("input token total is out of range")?;
        self.total_output_tokens = self
            .total_output_tokens
            .checked_add(crate::value::integer(output))
            .ok_or("output token total is out of range")?;
        Ok(())
    }
}

#[derive(Clone, Serialize)]
pub struct Message {
    pub id: String,
    pub role: String,
    pub agent: Option<String>,
    pub mode: Option<String>,
    pub model: Option<serde_json::Value>,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub entry_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub entry_type: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_id: Option<serde_json::Value>,
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
            entry_id: None,
            entry_type: None,
            parent_id: None,
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
    Image(ImagePart),
}

#[derive(Clone, PartialEq, Serialize)]
pub struct ImagePart {
    pub mime_type: Option<String>,
    pub data: serde_json::Value,
    pub time_created: i64,
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
            Self::Tool(_) | Self::Image(_) => None,
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

pub fn epoch_seconds(seconds: f64) -> Option<Timestamp> {
    // Keep the Python coercion limit and datetime's microsecond precision.
    if !seconds.is_finite() || seconds.abs() > 32_503_680_000.0 {
        return None;
    }
    let micros = (seconds * 1_000_000.0).round_ties_even() as i128;
    Timestamp::from_nanosecond(micros * 1_000).ok()
}

impl Session {
    pub fn payload(&self, messages: Vec<Message>, stats: Stats) -> SessionData {
        SessionData {
            id: self.id.clone(),
            title: self.title.clone(),
            slug: None,
            directory: self.directory.clone(),
            version: self.version.clone(),
            time_created: self.created_at.as_millisecond(),
            time_updated: self.updated_at.as_millisecond(),
            summary_files: None,
            stats,
            messages,
        }
    }

    pub fn display_location(&self) -> String {
        if !self.directory.trim().is_empty() {
            return std::path::Path::new(self.directory.trim())
                .components()
                .collect::<PathBuf>()
                .display()
                .to_string();
        }
        if let Some(project) = &self.project {
            return project.clone();
        }
        if self.source_path.is_dir() {
            return self.source_path.display().to_string();
        }
        self.source_path
            .parent()
            .unwrap_or(&self.source_path)
            .display()
            .to_string()
    }
}
