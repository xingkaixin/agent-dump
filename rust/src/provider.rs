use crate::session::{Session, SessionData};
use std::path::{Path, PathBuf};

pub struct ProviderInfo {
    pub name: &'static str,
    pub display_name: &'static str,
    pub scheme: &'static str,
    pub uri_prefixes: &'static [&'static str],
}

pub trait Provider {
    fn discover(&mut self, days: i64) -> crate::Result<Vec<Session>>;
    fn find(&mut self, id: &str) -> crate::Result<Session>;
    fn read(&self, session: &Session, zh: bool) -> crate::Result<SessionData>;
    fn source_root(&self) -> &Path;

    fn json_payload(&self, data: &SessionData) -> SessionData {
        let mut payload = data.clone();
        payload
            .messages
            .retain(|message| message.role != "developer");
        payload
    }

    fn raw_source(&self, session: &Session) -> crate::Result<PathBuf> {
        Ok(session.source_path.clone())
    }
}
