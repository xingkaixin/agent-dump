use crate::session::{Session, SessionData};
use std::path::{Path, PathBuf};

pub struct ProviderInfo {
    pub name: &'static str,
    pub display_name: &'static str,
    pub scheme: &'static str,
    pub uri_prefixes: &'static [&'static str],
}

pub enum RawExport {
    File(PathBuf),
    Session,
}

pub trait Provider {
    fn discover(&mut self, days: i64) -> crate::Result<Vec<Session>>;
    fn find(&mut self, id: &str) -> crate::Result<Session>;
    fn read(&self, session: &Session, zh: bool) -> crate::Result<SessionData>;
    fn source_root(&self) -> &Path;

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
