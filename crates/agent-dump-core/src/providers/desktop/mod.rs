pub(super) mod cherry;
pub(super) mod deepchat;
pub(super) mod minimax;

use crate::output::formats::OutputFormat;
use crate::providers::contract::Provider;
use crate::providers::error::ProviderError;
use crate::session::timestamp::Timestamp;
use crate::session::{Session, SessionData};
use jiff::SignedDuration;
use rusqlite::Connection;
use serde_json::Value;
use std::path::{Path, PathBuf};

#[derive(Clone, Copy)]
pub enum Kind {
    DeepChat,
    Cherry,
    MiniMax,
}

impl Kind {
    pub fn missing_source(
        self,
        path: &Path,
        id: Option<&str>,
        roots: Vec<String>,
    ) -> ProviderError {
        let summary = match self {
            Self::DeepChat => [
                "DeepChat session source is missing.",
                "DeepChat 会话数据源不存在。",
            ],
            Self::Cherry => [
                "Cherry Studio session source is missing.",
                "Cherry Studio 会话数据源不存在。",
            ],
            Self::MiniMax => [
                "MiniMax Code session source is missing.",
                "MiniMax Code 会话数据源不存在。",
            ],
        };
        ProviderError::missing(
            summary,
            path,
            id.map(|id| format!("session id: {id}"))
                .into_iter()
                .collect(),
            roots,
            Vec::new(),
        )
    }
}

pub struct Desktop {
    kind: Kind,
    database: PathBuf,
    search_roots: crate::providers::contract::SourceResolver,
}

impl Desktop {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; source access is deferred"
    )]
    pub fn open(kind: Kind) -> crate::Result<Self> {
        Ok(Self {
            kind,
            database: PathBuf::from("."),
            search_roots: Box::new(move || search_roots(kind)),
        })
    }

    fn select_database(&mut self) -> crate::Result<bool> {
        let roots = (self.search_roots)()?;
        if let Some((_, path)) =
            roots.into_iter().find(|(_, path)| path.exists())
        {
            self.database = path;
            return Ok(true);
        }
        Ok(false)
    }

    fn sessions(
        &self,
        connection: &Connection,
        id: Option<&str>,
        cutoff: Option<i64>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        match self.kind {
            Kind::DeepChat => crate::providers::desktop::deepchat::sessions(
                connection,
                &self.database,
                id,
                cutoff,
            )
            .map(crate::providers::contract::Discovery::available),
            Kind::Cherry => crate::providers::desktop::cherry::sessions(
                connection,
                &self.database,
                id,
                cutoff,
            ),
            Kind::MiniMax => crate::providers::desktop::minimax::sessions(
                connection,
                &self.database,
                id,
                cutoff,
            ),
        }
    }

    fn with_database<T>(
        &self,
        path: &Path,
        read: impl FnOnce(&Connection) -> crate::Result<T>,
    ) -> crate::Result<T> {
        if !path.is_file() {
            let roots = if matches!(self.kind, Kind::Cherry) {
                Vec::new()
            } else {
                self.search_roots()?
                    .iter()
                    .map(|(label, path)| {
                        format!(
                            "{label}: {}",
                            crate::storage::source_io::path_text(path)
                        )
                    })
                    .collect()
            };
            return Err(self.kind.missing_source(path, None, roots).into());
        }
        let result = crate::providers::sqlite::connection::connect(path)
            .and_then(|connection| read(&connection));
        if matches!(self.kind, Kind::DeepChat)
            && result.as_ref().err().is_some_and(|error| matches!(
                error.downcast_ref::<rusqlite::Error>(),
                Some(rusqlite::Error::SqliteFailure(failure, _)) if failure.code == rusqlite::ErrorCode::NotADatabase
            ))
        {
            return Err(ProviderError::capability(
                ["DeepChat database is encrypted or is not a readable SQLite database.", "DeepChat 数据库已加密，或不是可读取的 SQLite 数据库。"],
                ["Only unencrypted DeepChat databases are supported; SQLCipher decryption is unavailable.", "仅支持未加密的 DeepChat 数据库，暂不支持 SQLCipher 解密。"],
                vec![crate::storage::source_io::path_text(path)],
            ).into());
        }
        result
    }
}

impl Provider for Desktop {
    fn discover(
        &mut self,
        days: i64,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        if !self.select_database()? {
            return Ok(crate::providers::contract::Discovery::default());
        }
        let cutoff = Timestamp::now()
            .checked_sub(SignedDuration::from_secs(
                days.checked_mul(86400).ok_or("days is out of range")?,
            ))?
            .as_millisecond();
        self.with_database(&self.database, |connection| {
            self.sessions(connection, None, Some(cutoff))
        })
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Lookup> {
        if !self.select_database()? {
            return Ok(crate::providers::contract::Lookup::default());
        }
        Ok(crate::providers::contract::Lookup::new(
            self.with_database(&self.database, |connection| {
                self.sessions(connection, Some(id), None)
            })?
            .sessions
            .into_iter()
            .next(),
        ))
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        self.with_database(&session.source_path, |connection| match self.kind {
            Kind::DeepChat => {
                crate::providers::desktop::deepchat::read(connection, session)
            }
            Kind::Cherry => {
                crate::providers::desktop::cherry::read(connection, session)
            }
            Kind::MiniMax => {
                crate::providers::desktop::minimax::read(connection, session)
            }
        })
    }

    fn search_roots(
        &self,
    ) -> crate::Result<crate::providers::contract::SearchRoots> {
        (self.search_roots)()
    }

    fn change_sources(&self, session: &Session) -> Vec<PathBuf> {
        crate::providers::sqlite::connection::change_sources(
            &session.source_path,
        )
    }

    fn source_root(&self) -> &Path {
        self.database.parent().unwrap()
    }

    fn supports_format(&self, format: OutputFormat) -> bool {
        format != OutputFormat::Raw
    }

    fn json_payload(&self, data: &SessionData) -> Value {
        let mut payload = serde_json::to_value(data).unwrap();
        let fields = payload.as_object_mut().unwrap();
        for field in ["slug", "version", "summary_files"] {
            fields.remove(field);
        }
        if matches!(self.kind, Kind::MiniMax) {
            fields.insert(
                "stats".into(),
                serde_json::json!({"message_count": data.messages.len()}),
            );
        }
        payload
    }
}

fn search_roots(
    kind: Kind,
) -> crate::Result<crate::providers::contract::SearchRoots> {
    match kind {
        Kind::DeepChat => {
            let root = match std::env::var_os("DEEPCHAT_USER_DATA_DIR")
                .filter(|v| !v.is_empty())
            {
                Some(root) => PathBuf::from(root),
                None => app_data("DeepChat")?,
            };
            Ok(vec![(
                "DeepChat userData/app_db/agent.db",
                root.join("app_db/agent.db"),
            )])
        }
        Kind::Cherry => crate::providers::desktop::cherry::search_roots(),
        Kind::MiniMax => crate::providers::desktop::minimax::search_roots(),
    }
}

pub fn app_data(name: &str) -> crate::Result<PathBuf> {
    let root = if cfg!(target_os = "macos") {
        crate::providers::files::environment_root("HOME", "")?
            .join("Library/Application Support")
    } else if cfg!(target_os = "windows") {
        crate::providers::files::environment_root("APPDATA", "AppData/Roaming")?
    } else {
        crate::providers::files::environment_root("XDG_CONFIG_HOME", ".config")?
    };
    Ok(root.join(name))
}

pub fn timestamp(value: &Value) -> Option<Timestamp> {
    value
        .as_f64()
        .or_else(|| value.as_str()?.trim().parse().ok())
        .and_then(|value| crate::session::epoch_seconds(value / 1000.0))
}

pub fn has_tables(
    connection: &Connection,
    tables: &[&str],
) -> crate::Result<bool> {
    for table in tables {
        if !crate::providers::sqlite::connection::has_table(connection, table)?
        {
            return Ok(false);
        }
    }
    Ok(true)
}

#[cfg(test)]
mod tests;
