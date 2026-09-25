use crate::provider_error::ProviderError;
use crate::session::{Session, SessionData};
use std::path::{Path, PathBuf};

pub type DiagnosticSink<'a> = dyn FnMut(RecoverableDiagnostic) -> crate::Result<()> + 'a;
pub type SearchRoots = Vec<(&'static str, PathBuf)>;
pub type SourceResolver = Box<dyn Fn() -> crate::Result<SearchRoots> + Send + Sync>;

pub enum RecoverableDiagnostic {
    JsonlRecordsSkipped {
        path: PathBuf,
        count: usize,
        lines: Vec<usize>,
    },
    MessageDataParseFailed(String),
    PartDataParseFailed(String),
    MessageConvertFailed(String),
    PiRecordConvertFailed(String),
    TitleCacheFailed(String),
    TitleCacheEntriesSkipped {
        path: PathBuf,
        count: usize,
    },
}

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
    pub error: crate::Error,
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

pub trait Provider: Send + Sync {
    fn discover(
        &mut self,
        days: i64,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Discovery>;
    fn find(&mut self, id: &str, diagnostics: &mut DiagnosticSink<'_>) -> crate::Result<Lookup>;
    fn read(
        &self,
        session: &Session,
        zh: bool,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<SessionData>;
    fn source_root(&self) -> &Path;
    fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>>;

    fn change_sources(&self, session: &Session) -> Vec<PathBuf> {
        vec![session.source_path.clone()]
    }

    fn json_payload(&self, data: &SessionData) -> serde_json::Value {
        serde_json::to_value(data).unwrap()
    }

    fn supports_format(&self, _format: crate::output_formats::OutputFormat) -> bool {
        true
    }

    fn raw_export(&self, session: &Session) -> crate::Result<RawExport> {
        let path = &session.source_path;
        if !path.exists() {
            return Err(ProviderError::missing(
                ["raw session source is missing"; 2],
                path,
                Vec::new(),
                source_roots(self)?,
                vec![
                    [
                        "Confirm the original session file is still on this machine.",
                        "确认原始会话文件仍在本地。",
                    ],
                    [
                        "Re-run `agent-dump --list` to check whether the session is still visible.",
                        "重新运行 `agent-dump --list` 检查该会话是否仍可见。",
                    ],
                ],
            )
            .into());
        }
        if !path.is_file() {
            return Err(ProviderError::Diagnostic {
                summary: ["raw export is not supported for this session source"; 2],
                details: vec![format!("source path: {}", crate::source_io::path_text(path))],
                roots: Vec::new(),
                capability: Some(["session source is a directory, not a single raw file"; 2]),
                next_steps: vec![
                    ["Use `--format json` or `--format markdown` instead.", "改用 `--format json` 或 `--format markdown`。"],
                    ["If you need the original file, check whether this provider keeps a standalone raw file.", "若需要原始文件，请检查该 provider 是否有独立 raw 文件。"],
                ],
            }.into());
        }
        Ok(RawExport::File(path.clone()))
    }
}

pub fn source_roots(provider: &(impl Provider + ?Sized)) -> crate::Result<Vec<String>> {
    Ok(provider
        .search_roots()?
        .into_iter()
        .map(|(label, path)| format!("{label}: {}", crate::source_io::path_text(&path)))
        .collect())
}

pub fn render_search_roots(info: &ProviderInfo, provider: &dyn Provider) -> Vec<String> {
    source_roots(provider)
        .unwrap_or_default()
        .into_iter()
        .map(|root| format!("{}: {root}", info.display_name))
        .collect()
}
