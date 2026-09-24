use crate::session::{Session, SessionData};
use std::path::{Path, PathBuf};

pub struct ProviderInfo {
    pub name: &'static str,
    pub display_name: &'static str,
    pub scheme: &'static str,
    pub identifier_label: &'static str,
    pub uri_prefixes: &'static [&'static str],
}

pub struct SessionGroup {
    pub provider: &'static ProviderInfo,
    pub sessions: Vec<Session>,
}

pub enum RawExport {
    File(PathBuf),
    Session,
}

#[derive(Default)]
pub struct Discovery {
    pub available: bool,
    pub sessions: Vec<Session>,
    pub failures: Vec<SessionFailure>,
}

pub struct SessionFailure {
    pub source: String,
    pub error: Box<dyn std::error::Error>,
}

#[derive(Default)]
pub struct Lookup {
    pub session: Option<Session>,
    pub failures: Vec<SessionFailure>,
}

impl Lookup {
    pub fn new(session: Option<Session>) -> Self {
        Self {
            session,
            failures: Vec::new(),
        }
    }
}

impl Discovery {
    pub fn available(sessions: Vec<Session>) -> Self {
        Self {
            available: true,
            sessions,
            failures: Vec::new(),
        }
    }
}

pub trait Provider {
    fn discover(&mut self, days: i64) -> crate::Result<Discovery>;
    fn find(&mut self, id: &str) -> crate::Result<Lookup>;
    fn read(&self, session: &Session, zh: bool) -> crate::Result<SessionData>;
    fn source_root(&self) -> &Path;
    fn search_roots(&self) -> Vec<(&'static str, PathBuf)>;

    fn json_payload(&self, data: &SessionData) -> serde_json::Value {
        serde_json::to_value(data).unwrap()
    }

    fn supports_format(&self, _format: crate::output_formats::OutputFormat) -> bool {
        true
    }

    fn raw_export(&self, session: &Session) -> RawExport {
        RawExport::File(session.source_path.clone())
    }
}

pub fn render_search_roots(info: &ProviderInfo, provider: &dyn Provider) -> Vec<String> {
    provider
        .search_roots()
        .into_iter()
        .map(|(label, path)| format!("{}: {label}: {}", info.display_name, path.display()))
        .collect()
}
