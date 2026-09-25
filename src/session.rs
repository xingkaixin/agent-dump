use crate::timestamp::Timestamp;
use serde::Serialize;
use std::path::PathBuf;

#[derive(Clone)]
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
    pub subtargets: Vec<String>,
    pub source_metadata: serde_json::Value,
}

#[derive(Clone, Serialize)]
pub struct SessionData {
    #[serde(flatten)]
    pub extra: serde_json::Map<String, serde_json::Value>,
    pub id: String,
    pub title: String,
    pub slug: serde_json::Value,
    pub directory: serde_json::Value,
    pub version: serde_json::Value,
    pub time_created: i64,
    pub time_updated: i64,
    pub summary_files: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<serde_json::Value>,
    pub stats: Stats,
    pub messages: Vec<Message>,
}

#[derive(Clone, Serialize)]
pub struct Stats {
    #[serde(flatten)]
    pub extra: serde_json::Map<String, serde_json::Value>,
    pub total_cost: serde_json::Number,
    pub total_input_tokens: serde_json::Number,
    pub total_output_tokens: serde_json::Number,
    pub message_count: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_tokens: Option<serde_json::Number>,
}

impl Default for Stats {
    fn default() -> Self {
        Self {
            extra: Default::default(),
            total_cost: 0.into(),
            total_input_tokens: 0.into(),
            total_output_tokens: 0.into(),
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
        crate::value::add_integer(&mut self.total_input_tokens, input);
        crate::value::add_integer(&mut self.total_output_tokens, output);
        Ok(())
    }
}

#[derive(Clone, Serialize)]
pub struct Message {
    #[serde(flatten)]
    pub extra: serde_json::Map<String, serde_json::Value>,
    pub id: String,
    pub role: String,
    pub agent: Option<String>,
    pub mode: Option<String>,
    pub model: Option<serde_json::Value>,
    pub provider: Option<String>,
    pub time_created: i64,
    pub time_completed: serde_json::Value,
    pub tokens: serde_json::Map<String, serde_json::Value>,
    pub cost: serde_json::Number,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<serde_json::Map<String, serde_json::Value>>,
}

impl Message {
    pub fn new(id: String, role: &str, time_created: i64, parts: Vec<Part>) -> Self {
        let role = match role {
            "user" | "assistant" | "developer" | "system" | "tool" | "branch_summary"
            | "compaction" | "custom" => role,
            _ => "unknown",
        };
        Self {
            extra: Default::default(),
            id,
            role: role.into(),
            agent: None,
            mode: None,
            model: None,
            provider: None,
            time_created,
            time_completed: serde_json::Value::Null,
            tokens: Default::default(),
            cost: 0.into(),
            parts,
            nickname: None,
            subagent_id: None,
            tool_call_id: None,
            entry_id: None,
            entry_type: None,
            parent_id: None,
            metadata: None,
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
    #[serde(rename = "step-start")]
    StepStart(StepPart),
    #[serde(rename = "step-finish")]
    StepFinish(StepPart),
    #[serde(untagged)]
    Unknown(UnknownPart),
}

#[derive(Clone, PartialEq, Serialize)]
pub struct StepPart {
    pub time_created: i64,
    pub reason: serde_json::Value,
    pub tokens: serde_json::Value,
    pub cost: serde_json::Value,
}

#[derive(Clone, PartialEq, Serialize)]
pub struct UnknownPart {
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<serde_json::Value>,
    pub time_created: i64,
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
    pub output: serde_json::Value,
    pub approval_status: String,
    pub time_created: i64,
}

#[derive(Clone, PartialEq, Serialize)]
pub struct ToolPart {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subagent_type: Option<String>,
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
    pub fn tool(name: &str, call_id: &str, state: serde_json::Value, timestamp: i64) -> Self {
        Self::Tool(Box::new(ToolPart {
            tool: name.into(),
            call_id: call_id.into(),
            title: name.into(),
            state: state.as_object().cloned().unwrap_or_default(),
            time_created: timestamp,
            nickname: None,
            subagent_id: None,
            subagent_type: None,
        }))
    }

    pub fn event(kind: String, data: serde_json::Value, timestamp: i64) -> Self {
        Self::Unknown(UnknownPart {
            kind,
            data: Some(data),
            time_created: timestamp,
        })
    }

    pub fn text(text: String, time_created: i64) -> Self {
        Self::Text(TextPart { text, time_created })
    }

    pub fn content(&self) -> Option<&str> {
        match self {
            Self::Text(part) | Self::Reasoning(part) => Some(&part.text),
            Self::Plan(part) => Some(&part.input),
            Self::Tool(_)
            | Self::Image(_)
            | Self::StepStart(_)
            | Self::StepFinish(_)
            | Self::Unknown(_) => None,
        }
    }
}

pub fn parse_timestamp(value: &str) -> Option<Timestamp> {
    value.parse().ok()
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
    pub fn new(
        id: String,
        title: String,
        source_path: PathBuf,
        created_at: Timestamp,
        updated_at: Timestamp,
    ) -> Self {
        Self {
            id,
            title,
            source_path,
            created_at,
            updated_at,
            directory: String::new(),
            model: String::new(),
            version: serde_json::Value::Null,
            project: None,
            message_count: None,
            subtargets: Vec::new(),
            source_metadata: serde_json::Value::Null,
        }
    }

    pub fn payload(&self, messages: Vec<Message>, stats: Stats) -> SessionData {
        SessionData {
            extra: Default::default(),
            id: self.id.clone(),
            title: self.title.clone(),
            slug: serde_json::Value::Null,
            directory: self.directory.clone().into(),
            version: self.version.clone(),
            time_created: self.created_at.as_millisecond(),
            time_updated: self.updated_at.as_millisecond(),
            summary_files: serde_json::Value::Null,
            metadata: None,
            stats,
            messages,
        }
    }

    pub fn working_directory(&self) -> String {
        let path = std::path::Path::new(self.directory.trim())
            .components()
            .collect::<PathBuf>();
        crate::source_io::path_text(&path)
    }

    pub fn display_location(&self) -> String {
        let directory = self.working_directory();
        if !directory.is_empty() {
            return directory;
        }
        if let Some(project) = &self.project {
            return project.clone();
        }
        if self.source_path.is_dir() {
            return crate::source_io::path_text(&self.source_path);
        }
        crate::source_io::path_text(self.source_path.parent().unwrap_or(&self.source_path))
    }
}
