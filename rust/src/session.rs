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

#[derive(Serialize)]
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

#[derive(Default, Serialize)]
pub struct Stats {
    pub total_cost: u64,
    pub total_input_tokens: i64,
    pub total_output_tokens: i64,
    pub message_count: usize,
}

#[derive(Serialize)]
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
}

#[derive(PartialEq, Serialize)]
pub struct Part {
    #[serde(rename = "type")]
    pub kind: String,
    pub text: String,
    pub time_created: i64,
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
