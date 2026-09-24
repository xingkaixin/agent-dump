use crate::session::Session;
use jiff::civil::Date;
use serde::Serialize;

#[derive(Clone, Copy, PartialEq, clap::ValueEnum)]
pub enum Mode {
    Pm,
    Insight,
}
impl Mode {
    pub fn name(self) -> &'static str {
        match self {
            Self::Pm => "pm",
            Self::Insight => "insight",
        }
    }
    pub fn fields(self) -> [&'static str; 3] {
        match self {
            Self::Pm => ["requests", "decisions", "outcomes"],
            Self::Insight => ["scene", "stuck", "turning"],
        }
    }
}

pub enum Action {
    Execute,
    DryRun,
    EmitPrompt,
}

pub struct Operation {
    pub days: Option<i64>,
    pub since: Option<String>,
    pub until: Option<String>,
    pub save: Option<String>,
    pub mode: Mode,
    pub action: Action,
    pub query: Option<crate::query::Query>,
}

#[derive(Clone)]
pub struct Event {
    pub role: String,
    pub text: String,
}
impl Event {
    pub fn render(&self) -> String {
        format!(
            "[{}] role={} text={}",
            if self.role == "user" {
                "user_message"
            } else {
                "agent_message"
            },
            self.role,
            self.text
        )
    }
}

pub struct Entry {
    pub date: Date,
    pub session: Session,
    pub provider: &'static crate::provider::ProviderInfo,
    pub chunks: Vec<Vec<Event>>,
    pub truncated: bool,
}
impl Entry {
    pub fn uri(&self) -> String {
        format!("{}://{}", self.provider.scheme, self.session.id)
    }
}

pub type Summary = serde_json::Map<String, serde_json::Value>;

#[derive(Clone, Serialize)]
pub struct Group {
    pub date: String,
    pub project_directory: String,
    pub session_uris: Vec<String>,
    pub summary: Summary,
}
