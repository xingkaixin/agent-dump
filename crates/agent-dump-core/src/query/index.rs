use crate::output::i18n::t;
use crate::providers::contract::{Provider, ProviderInfo};
use crate::query::text::{Mode, TextQuery};
use crate::session::Session;
use crate::session::cache::{SessionDataCache, SessionSignal};
use rusqlite::{Connection, OptionalExtension, params};
use std::collections::{HashMap, HashSet};
use std::io::Write;
use std::path::Path;

pub struct SearchIndex {
    connection: Connection,
}

struct IndexedRow {
    signature: String,
    rowid: i64,
    observed: f64,
}

pub struct SearchResult {
    pub provider: String,
    pub id: String,
    pub snippet: String,
    pub rank: f64,
}

fn now() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}

fn cjk(c: char) -> bool {
    ('\u{4e00}'..='\u{9fff}').contains(&c)
}

fn separate_cjk(text: &str) -> String {
    let mut output = String::new();
    let mut previous = None;
    for c in text.chars() {
        if previous.is_some_and(|p| {
            (cjk(p) && !crate::query::text::whitespace(c))
                || (cjk(c) && !crate::query::text::whitespace(p))
        }) {
            output.push(' ');
        }
        output.push(c);
        previous = Some(c);
    }
    output
}

fn fts_table(query: &TextQuery) -> Option<&'static str> {
    if query.literals.is_empty()
        || (query.mode == Mode::Phrase && query.literals[0].contains(' '))
    {
        return None;
    }
    if query.literals.iter().all(|s| s.chars().all(cjk)) {
        return Some("sessions_fts");
    }
    if query
        .literals
        .iter()
        .any(|s| s.contains(['i', 'I', 'İ', 'ı']))
    {
        return None;
    }
    if query
        .literals
        .iter()
        .all(|s| s.chars().count() >= 3 && !s.chars().any(cjk))
    {
        return Some("sessions_fts_trigram");
    }
    None
}

fn delete(connection: &Connection, rowid: i64) -> crate::Result<()> {
    connection
        .execute("DELETE FROM index_state WHERE fts_rowid = ?", [rowid])?;
    delete_text(connection, rowid)
}

fn delete_text(connection: &Connection, rowid: i64) -> crate::Result<()> {
    connection.execute("DELETE FROM sessions_fts WHERE rowid = ?", [rowid])?;
    connection
        .execute("DELETE FROM sessions_fts_trigram WHERE rowid = ?", [rowid])?;
    Ok(())
}

impl SearchIndex {
    pub fn open(
        sources: impl IntoIterator<Item = std::path::PathBuf>,
    ) -> crate::Result<Self> {
        let root = std::env::var_os("XDG_CACHE_HOME")
            .filter(|s| !s.is_empty())
            .map_or(
                crate::providers::files::environment_root("HOME", ".cache")?,
                std::path::PathBuf::from,
            );
        let path = root.join("agent-dump/search-index.db");
        let resolved = crate::query::project_path(
            &crate::storage::source_io::path_text(&path),
        )?;
        for source in sources {
            let source = crate::query::project_path(
                &crate::storage::source_io::path_text(&source),
            )?;
            if resolved.starts_with(source) {
                return Err("Search index must be outside the Provider source directory".into());
            }
        }
        Self::at(&path)
    }

    pub fn at(path: &Path) -> crate::Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                crate::storage::source_io::Error::native(parent, &e)
            })?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = std::fs::set_permissions(
                    parent,
                    std::fs::Permissions::from_mode(0o700),
                );
            }
        }
        let mut connection = Connection::open(path)?;
        connection.busy_timeout(std::time::Duration::from_secs(5))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(
                path,
                std::fs::Permissions::from_mode(0o600),
            );
        }
        let transaction = connection.transaction_with_behavior(
            rusqlite::TransactionBehavior::Immediate,
        )?;
        let version: i64 =
            transaction
                .query_row("PRAGMA user_version", [], |row| row.get(0))?;
        let columns: Vec<(String, i64)> = transaction
            .prepare("PRAGMA table_info(index_state)")?
            .query_map([], |r| Ok((r.get(1)?, r.get(5)?)))?
            .collect::<Result<_, _>>()?;
        let valid = ["updated_signature", "last_seen_at", "session_updated_at"]
            .iter()
            .all(|name| columns.iter().any(|(n, _)| n == name))
            && columns
                .iter()
                .filter(|(_, pk)| *pk != 0)
                .map(|(name, _)| name.as_str())
                .collect::<Vec<_>>()
                == ["fts_rowid"];
        if !columns.is_empty() && (version != 3 || !valid) {
            transaction.execute_batch("DROP TABLE IF EXISTS sessions_fts; DROP TABLE IF EXISTS sessions_fts_trigram; DROP TABLE IF EXISTS index_state;")?;
        }
        transaction.execute_batch("CREATE TABLE IF NOT EXISTS index_state (
            fts_rowid INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, session_id TEXT NOT NULL,
            source_path TEXT NOT NULL, updated_signature TEXT NOT NULL, indexed_at REAL NOT NULL,
            last_seen_at REAL NOT NULL, session_updated_at REAL NOT NULL, session_created_at REAL NOT NULL,
            UNIQUE (agent, session_id));
            CREATE INDEX IF NOT EXISTS index_state_last_seen_idx ON index_state(last_seen_at);
            CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(agent_name UNINDEXED, session_id UNINDEXED, title, content, tokenize='unicode61 remove_diacritics 1');
            CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts_trigram USING fts5(agent_name UNINDEXED, session_id UNINDEXED, title, content, tokenize='trigram');
            PRAGMA user_version = 3;")?;
        let expired: Vec<i64> = transaction
            .prepare(
                "SELECT fts_rowid FROM index_state WHERE last_seen_at < ?",
            )?
            .query_map([30.0f64.mul_add(-86400.0, now())], |r| r.get(0))?
            .collect::<Result<_, _>>()?;
        for rowid in expired {
            delete(&transaction, rowid)?;
        }
        transaction.commit()?;
        Ok(Self { connection })
    }

    pub fn clear(&mut self, provider: &str) -> crate::Result<()> {
        let transaction = self.connection.transaction_with_behavior(
            rusqlite::TransactionBehavior::Immediate,
        )?;
        let rows: Vec<i64> = transaction
            .prepare("SELECT fts_rowid FROM index_state WHERE agent = ?")?
            .query_map([provider], |r| r.get(0))?
            .collect::<Result<_, _>>()?;
        for rowid in rows {
            delete(&transaction, rowid)?;
        }
        transaction.commit()?;
        Ok(())
    }

    #[allow(
        clippy::cast_precision_loss,
        reason = "The shared SQLite schema stores timestamps as floating-point seconds"
    )]
    pub fn update(
        &mut self,
        info: &ProviderInfo,
        provider: &dyn Provider,
        sessions: &[Session],
        zh: bool,
        warnings: &mut impl Write,
    ) -> crate::Result<(usize, Vec<String>)> {
        let observed = now();
        let indexed: HashMap<String, IndexedRow> = self.connection.prepare("SELECT session_id, updated_signature, fts_rowid, indexed_at FROM index_state WHERE agent = ?")?.query_map([info.name], |r| Ok((r.get(0)?, IndexedRow { signature: r.get(1)?, rowid: r.get(2)?, observed: r.get(3)? })))?.collect::<Result<_, _>>()?;
        let transaction = self.connection.transaction()?;
        for session in sessions {
            transaction.execute("UPDATE index_state SET last_seen_at = MAX(last_seen_at, ?) WHERE agent = ? AND session_id = ?", params![observed, info.name, session.id])?;
        }
        transaction.commit()?;
        let pending: Vec<_> = sessions
            .iter()
            .filter_map(|session| {
                let signature =
                    SessionSignal::new(provider, session).signature();
                (indexed
                    .get(&session.id)
                    .is_none_or(|old| old.signature != signature))
                .then_some((session, signature))
            })
            .collect();
        if pending.len() >= 10 {
            writeln!(
                warnings,
                "{}",
                t(
                    "INDEX_UPDATE_PROGRESS",
                    zh,
                    &[
                        ("agent", info.display_name.into()),
                        ("count", pending.len().to_string())
                    ]
                )
            )?;
        }
        let cache = SessionDataCache::default();
        let mut added = 0;
        let mut failed = Vec::new();
        for batch in pending.chunks(32) {
            let texts = std::thread::scope(|scope| {
                let jobs: Vec<_> = batch
                    .iter()
                    .map(|(session, _)| {
                        let cache = &cache;
                        scope.spawn(move || {
                            let mut diagnostics = Vec::new();
                            let text = cache
                                .lease(
                                    info.name,
                                    provider,
                                    session,
                                    zh,
                                    &mut |d| {
                                        diagnostics.push(d);
                                        Ok(())
                                    },
                                )
                                .map(|data| {
                                    crate::query::transcript::searchable(&data)
                                });
                            (text, diagnostics)
                        })
                    })
                    .collect();
                jobs.into_iter()
                    .map(|job| {
                        job.join().map_err(|_| "Index reader panicked".into())
                    })
                    .collect::<crate::Result<Vec<_>>>()
            })?;
            for (_, diagnostics) in &texts {
                for diagnostic in diagnostics {
                    writeln!(
                        warnings,
                        "{}",
                        crate::output::diagnostics::record_warning(
                            diagnostic, zh
                        )
                    )?;
                }
            }
            let transaction = self.connection.transaction_with_behavior(
                rusqlite::TransactionBehavior::Immediate,
            )?;
            for ((session, signature), (text, _)) in batch.iter().zip(texts) {
                let latest = transaction.query_row("SELECT updated_signature, fts_rowid, indexed_at FROM index_state WHERE agent = ? AND session_id = ?", params![info.name, session.id], |r| Ok(IndexedRow { signature: r.get(0)?, rowid: r.get(1)?, observed: r.get(2)? })).optional()?;
                if latest.as_ref().is_some_and(|row| {
                    row.signature == *signature || row.observed > observed
                }) || (latest.is_none() && indexed.contains_key(&session.id))
                {
                    continue;
                }
                let Ok(text) = text else {
                    if let Some(row) = latest {
                        delete(&transaction, row.rowid)?;
                    }
                    failed.push(session.id.clone());
                    continue;
                };
                let rowid = if let Some(row) = latest {
                    delete_text(&transaction, row.rowid)?;
                    transaction.execute("UPDATE index_state SET source_path = ?, updated_signature = ?, indexed_at = ?, last_seen_at = MAX(last_seen_at, ?), session_updated_at = ?, session_created_at = ? WHERE fts_rowid = ?", params![crate::storage::source_io::path_text(&session.source_path), signature, observed, observed, session.updated_at.as_microsecond() as f64 / 1e6, session.created_at.as_microsecond() as f64 / 1e6, row.rowid])?;
                    row.rowid
                } else {
                    transaction.execute("INSERT INTO index_state (agent, session_id, source_path, updated_signature, indexed_at, last_seen_at, session_updated_at, session_created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", params![info.name, session.id, crate::storage::source_io::path_text(&session.source_path), signature, observed, observed, session.updated_at.as_microsecond() as f64 / 1e6, session.created_at.as_microsecond() as f64 / 1e6])?;
                    transaction.last_insert_rowid()
                };
                transaction.execute("INSERT INTO sessions_fts (rowid, agent_name, session_id, title, content) VALUES (?, ?, ?, ?, ?)", params![rowid, info.name, session.id, separate_cjk(&session.title), separate_cjk(&text)])?;
                transaction.execute("INSERT INTO sessions_fts_trigram (rowid, agent_name, session_id, title, content) VALUES (?, ?, ?, ?, ?)", params![rowid, info.name, session.id, session.title, text])?;
                added += 1;
            }
            transaction.commit()?;
        }
        if !failed.is_empty() {
            writeln!(
                warnings,
                "{}",
                crate::output::i18n::terminal(
                    "WARN_INDEX_SKIPPED_SESSIONS",
                    zh,
                    &[
                        ("agent", info.display_name.into()),
                        ("count", failed.len().to_string()),
                        (
                            "examples",
                            failed
                                .iter()
                                .take(3)
                                .cloned()
                                .collect::<Vec<_>>()
                                .join(", ")
                        )
                    ]
                )
            )?;
        }
        Ok((added, failed))
    }

    pub fn search(
        &self,
        query: &TextQuery,
        keys: &HashSet<(String, String)>,
    ) -> crate::Result<Vec<SearchResult>> {
        let Some(table) = fts_table(query) else {
            return self.literal_search(query, keys);
        };
        let raw = if table == "sessions_fts" {
            "JOIN sessions_fts_trigram raw ON raw.rowid = f.rowid"
        } else {
            ""
        };
        let fields = if table == "sessions_fts" {
            "raw.title, raw.content"
        } else {
            "f.title, f.content"
        };
        let sql = format!(
            "SELECT f.agent_name, f.session_id, {fields}, snippet({table}, 3, '**', '**', '...', 10), bm25({table}) FROM {table} f {raw} JOIN index_state s ON s.fts_rowid = f.rowid WHERE {table} MATCH ? ORDER BY bm25({table}), s.session_updated_at DESC, s.session_created_at DESC, f.agent_name, f.session_id"
        );
        let expression = query
            .literals
            .iter()
            .map(|s| {
                let text = if table == "sessions_fts" {
                    separate_cjk(s)
                } else {
                    s.clone()
                };
                format!("\"{}\"", text.replace('"', "\"\""))
            })
            .collect::<Vec<_>>()
            .join(" ");
        let mut statement = self.connection.prepare(&sql)?;
        let mut rows = statement.query([expression])?;
        let mut results = Vec::new();
        while let Some(row) = rows.next()? {
            let provider: String = row.get(0)?;
            let id: String = row.get(1)?;
            if !keys.contains(&(provider.clone(), id.clone())) {
                continue;
            }
            let title: String = row.get(2)?;
            let content: String = row.get(3)?;
            let Some(evidence) = query.find(&[&title, &content]) else {
                continue;
            };
            let mut snippet: String = row.get(4)?;
            if table == "sessions_fts" || !query.has_evidence(&snippet) {
                snippet = evidence.snippet;
            }
            results.push(SearchResult {
                provider,
                id,
                snippet,
                rank: -row.get::<_, f64>(5)?,
            });
        }
        Ok(results)
    }

    fn literal_search(
        &self,
        query: &TextQuery,
        keys: &HashSet<(String, String)>,
    ) -> crate::Result<Vec<SearchResult>> {
        let mut results = Vec::new();
        let keys: Vec<_> = keys.iter().collect();
        for batch in keys.chunks(400) {
            let filters =
                vec!["(s.agent = ? AND s.session_id = ?)"; batch.len()]
                    .join(" OR ");
            let sql = format!(
                "SELECT s.agent, s.session_id, f.title, f.content FROM index_state s JOIN sessions_fts_trigram f ON f.rowid = s.fts_rowid WHERE {filters}"
            );
            let mut statement = self.connection.prepare(&sql)?;
            let mut rows = statement.query(rusqlite::params_from_iter(
                batch.iter().flat_map(|(provider, id)| [provider, id]),
            ))?;
            while let Some(row) = rows.next()? {
                let title: String = row.get(2)?;
                let content: String = row.get(3)?;
                if let Some(evidence) = query.find(&[&title, &content]) {
                    results.push(SearchResult {
                        provider: row.get(0)?,
                        id: row.get(1)?,
                        snippet: evidence.snippet,
                        rank: if evidence.title_matches { 1.0 } else { 0.0 },
                    });
                }
            }
        }
        Ok(results)
    }
}

#[cfg(test)]
mod tests;
