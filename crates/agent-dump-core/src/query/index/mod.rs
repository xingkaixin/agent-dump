use crate::output::i18n::t;
use crate::providers::contract::{Provider, ProviderInfo};
use crate::query::text::{Mode, TextQuery};
use crate::session::Session;
use crate::session::cache::{SessionDataCache, SessionSignal};
use rusqlite::{Connection, OptionalExtension, params};
use sha2::{Digest, Sha256};
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
    last_seen_at: f64,
    content_hash: Vec<u8>,
}

struct PreparedText {
    raw: String,
    hash: [u8; 32],
    cjk_title: Option<String>,
    cjk_content: Option<String>,
    trigram_title: Option<String>,
    trigram_content: Option<String>,
}

enum SearchPlan {
    Fallback,
    Cjk(String),
    Trigram(String),
    Both { cjk: String, trigram: String },
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

// Derived text a batch holds until its write transaction commits. Past this,
// saving commits is not worth keeping more large transcripts alive.
const BATCH_BYTES: usize = 64 << 20;
const SCHEMA_VERSION: i64 = 5;
const DAY_SECONDS: f64 = 86_400.0;
const EXPIRY_SECONDS: f64 = 30.0 * DAY_SECONDS;

const fn cjk(c: char) -> bool {
    matches!(c, '\u{4e00}'..='\u{9fff}')
}

fn separate_cjk(text: &str) -> Option<String> {
    if !text.chars().any(cjk) {
        return None;
    }
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
    Some(output)
}

// Collapses every Unicode simple-case-folding class (plus [iIİı]) that
// bundled SQLite's trigram tokenizer folds apart, leaving ASCII untouched so
// SQLite handles ASCII case folding without allocating on ASCII-only text.
fn fold_trigram_char(c: char) -> char {
    if c.is_ascii() || cjk(c) {
        return c;
    }
    match c {
        'İ' | 'ı' => 'i',
        '\u{00b5}' => '\u{03bc}',
        '\u{017f}' => 's',
        '\u{0345}' | '\u{1fbe}' => '\u{03b9}',
        '\u{03c2}' => '\u{03c3}',
        '\u{03d0}' => '\u{03b2}',
        '\u{03d1}' => '\u{03b8}',
        '\u{03d5}' => '\u{03c6}',
        '\u{03d6}' => '\u{03c0}',
        '\u{03f0}' => '\u{03ba}',
        '\u{03f1}' => '\u{03c1}',
        '\u{03f5}' => '\u{03b5}',
        '\u{1c80}' => '\u{0432}',
        '\u{1c81}' => '\u{0434}',
        '\u{1c82}' => '\u{043e}',
        '\u{1c83}' => '\u{0441}',
        '\u{1c84}' | '\u{1c85}' => '\u{0442}',
        '\u{1c86}' => '\u{044a}',
        '\u{1c87}' => '\u{0463}',
        '\u{1c88}' => '\u{a64b}',
        '\u{1e9b}' => '\u{1e61}',
        '\u{1fd3}' => '\u{0390}',
        '\u{1fe3}' => '\u{03b0}',
        '\u{fb06}' => '\u{fb05}',
        _ => {
            let mut lower = c.to_lowercase();
            match (lower.next(), lower.next()) {
                (Some(folded), None) => folded,
                _ => c,
            }
        }
    }
}

fn fold_trigram(text: &str) -> Option<String> {
    if text.is_ascii() {
        return None;
    }
    let first = text
        .char_indices()
        .find(|&(_, c)| fold_trigram_char(c) != c)?;
    let mut output = String::with_capacity(text.len());
    output.push_str(&text[..first.0]);
    for c in text[first.0..].chars() {
        output.push(fold_trigram_char(c));
    }
    Some(output)
}

fn content_hash(title: &str, content: &str) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update((title.len() as u64).to_le_bytes());
    hasher.update(title.as_bytes());
    hasher.update(content.as_bytes());
    hasher.finalize().into()
}

fn fts_phrase(text: &str) -> String {
    format!("\"{}\"", text.replace('"', "\"\""))
}

fn push_unique(terms: &mut Vec<String>, phrase: String) {
    if !terms.contains(&phrase) {
        terms.push(phrase);
    }
}

fn cjk_runs(text: &str) -> Vec<&str> {
    let mut runs = Vec::new();
    let mut start = None;
    for (idx, c) in text.char_indices() {
        if cjk(c) {
            start.get_or_insert(idx);
        } else if let Some(begin) = start.take() {
            runs.push(&text[begin..idx]);
        }
    }
    if let Some(begin) = start {
        runs.push(&text[begin..]);
    }
    runs
}

fn search_plan(query: &TextQuery) -> SearchPlan {
    if query.literals.is_empty()
        || (query.mode == Mode::Phrase && query.literals[0].contains(' '))
    {
        return SearchPlan::Fallback;
    }
    let mut cjk_terms = Vec::new();
    let mut trigram_terms = Vec::new();
    for literal in &query.literals {
        if literal.contains('\0') {
            continue;
        }
        if literal.chars().all(cjk) {
            let separated = separate_cjk(literal);
            push_unique(
                &mut cjk_terms,
                fts_phrase(separated.as_deref().unwrap_or(literal)),
            );
        } else if literal.chars().count() >= 3 {
            let folded = fold_trigram(literal);
            push_unique(
                &mut trigram_terms,
                fts_phrase(folded.as_deref().unwrap_or(literal)),
            );
        } else {
            for run in cjk_runs(literal) {
                let separated = separate_cjk(run);
                push_unique(
                    &mut cjk_terms,
                    fts_phrase(separated.as_deref().unwrap_or(run)),
                );
            }
        }
    }
    match (cjk_terms.is_empty(), trigram_terms.is_empty()) {
        (true, true) => SearchPlan::Fallback,
        (false, true) => SearchPlan::Cjk(cjk_terms.join(" ")),
        (true, false) => SearchPlan::Trigram(trigram_terms.join(" ")),
        (false, false) => SearchPlan::Both {
            cjk: cjk_terms.join(" "),
            trigram: trigram_terms.join(" "),
        },
    }
}

fn table_columns(
    connection: &Connection,
    table: &str,
) -> crate::Result<Vec<(String, i64)>> {
    Ok(connection
        .prepare(&format!("PRAGMA table_info({table})"))?
        .query_map([], |r| Ok((r.get(1)?, r.get(5)?)))?
        .collect::<Result<_, _>>()?)
}

fn schema_valid(connection: &Connection) -> crate::Result<bool> {
    let state = table_columns(connection, "index_state")?;
    let state_ok = [
        "updated_signature",
        "content_hash",
        "last_seen_at",
        "session_updated_at",
    ]
    .iter()
    .all(|name| state.iter().any(|(n, _)| n == name))
        && state
            .iter()
            .filter(|(_, pk)| *pk != 0)
            .map(|(name, _)| name.as_str())
            .collect::<Vec<_>>()
            == ["fts_rowid"];
    if !state_ok {
        return Ok(false);
    }
    let content = table_columns(connection, "session_content")?;
    let content_ok = ["fts_rowid", "title", "content"]
        .iter()
        .all(|name| content.iter().any(|(n, _)| n == name));
    if !content_ok {
        return Ok(false);
    }
    let meta = table_columns(connection, "index_meta")?;
    let meta_ok = ["key", "value"]
        .iter()
        .all(|name| meta.iter().any(|(n, _)| n == name));
    if !meta_ok {
        return Ok(false);
    }
    let fts_count: i64 = connection.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name IN \
         ('sessions_fts', 'sessions_fts_trigram')",
        [],
        |row| row.get(0),
    )?;
    Ok(fts_count == 2)
}

fn last_cleanup_at(connection: &Connection) -> crate::Result<Option<f64>> {
    Ok(connection
        .query_row(
            "SELECT value FROM index_meta WHERE key = 'last_cleanup_at'",
            [],
            |row| row.get(0),
        )
        .optional()?)
}

fn run_expiry_cleanup(
    connection: &Connection,
    current: f64,
) -> crate::Result<()> {
    let expired: Vec<i64> = connection
        .prepare("SELECT fts_rowid FROM index_state WHERE last_seen_at < ?")?
        .query_map([current - EXPIRY_SECONDS], |r| r.get(0))?
        .collect::<Result<_, _>>()?;
    for rowid in expired {
        delete(connection, rowid)?;
    }
    connection.execute(
        "INSERT OR REPLACE INTO index_meta (key, value) VALUES \
         ('last_cleanup_at', ?)",
        [current],
    )?;
    Ok(())
}

fn delete(connection: &Connection, rowid: i64) -> crate::Result<()> {
    connection
        .execute("DELETE FROM index_state WHERE fts_rowid = ?", [rowid])?;
    delete_text(connection, rowid)
}

fn delete_text(connection: &Connection, rowid: i64) -> crate::Result<()> {
    connection
        .execute("DELETE FROM session_content WHERE fts_rowid = ?", [rowid])?;
    connection.execute("DELETE FROM sessions_fts WHERE rowid = ?", [rowid])?;
    connection
        .execute("DELETE FROM sessions_fts_trigram WHERE rowid = ?", [rowid])?;
    Ok(())
}

impl SearchIndex {
    pub fn open() -> crate::Result<Self> {
        let root = std::env::var_os("XDG_CACHE_HOME")
            .filter(|s| !s.is_empty())
            .map_or(
                crate::providers::files::environment_root("HOME", ".cache")?,
                std::path::PathBuf::from,
            );
        let path = root.join("agent-dump/search-index.db");
        if crate::providers::registry::inside_source(&path)? {
            return Err(
                "Search index must be outside the Provider source directory"
                    .into(),
            );
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
        connection.execute_batch("PRAGMA synchronous = NORMAL;")?;
        let version: i64 =
            connection
                .query_row("PRAGMA user_version", [], |row| row.get(0))?;
        let journal_mode: String =
            connection
                .query_row("PRAGMA journal_mode", [], |row| row.get(0))?;
        if version == SCHEMA_VERSION
            && journal_mode.eq_ignore_ascii_case("wal")
            && schema_valid(&connection)?
        {
            let current = now();
            if last_cleanup_at(&connection)?
                .is_none_or(|ts| current - ts >= DAY_SECONDS)
            {
                let transaction = connection.transaction_with_behavior(
                    rusqlite::TransactionBehavior::Immediate,
                )?;
                if last_cleanup_at(&transaction)?
                    .is_none_or(|ts| current - ts >= DAY_SECONDS)
                {
                    run_expiry_cleanup(&transaction, current)?;
                }
                transaction.commit()?;
            }
            return Ok(Self { connection });
        }
        if !journal_mode.eq_ignore_ascii_case("wal") {
            let _: String = connection.query_row(
                "PRAGMA journal_mode = WAL",
                [],
                |row| row.get(0),
            )?;
        }
        let transaction = connection.transaction_with_behavior(
            rusqlite::TransactionBehavior::Immediate,
        )?;
        let version: i64 =
            transaction
                .query_row("PRAGMA user_version", [], |row| row.get(0))?;
        let valid = schema_valid(&transaction)?;
        if version != SCHEMA_VERSION || !valid {
            transaction.execute_batch(
                "DROP TABLE IF EXISTS sessions_fts; DROP TABLE IF EXISTS \
                 sessions_fts_trigram; DROP TABLE IF EXISTS session_content; \
                 DROP TABLE IF EXISTS index_state; DROP TABLE IF EXISTS \
                 index_meta;",
            )?;
            transaction.execute_batch(concat!(
                "CREATE TABLE index_state (\n",
                "    fts_rowid INTEGER PRIMARY KEY AUTOINCREMENT,\n",
                "    agent TEXT NOT NULL, session_id TEXT NOT NULL,\n",
                "    source_path TEXT NOT NULL, updated_signature TEXT NOT \
                 NULL,\n",
                "    content_hash BLOB NOT NULL, indexed_at REAL NOT NULL,\n",
                "    last_seen_at REAL NOT NULL, session_updated_at REAL NOT \
                 NULL,\n",
                "    session_created_at REAL NOT NULL,\n",
                "    UNIQUE (agent, session_id));\n",
                "CREATE INDEX index_state_last_seen_idx ON \
                 index_state(last_seen_at);\n",
                "CREATE TABLE session_content (\n",
                "    fts_rowid INTEGER PRIMARY KEY,\n",
                "    title TEXT NOT NULL, content TEXT NOT NULL);\n",
                "CREATE TABLE index_meta (\n",
                "    key TEXT PRIMARY KEY, value REAL NOT NULL);\n",
                "CREATE VIRTUAL TABLE sessions_fts USING fts5(\n",
                "    agent_name UNINDEXED, session_id UNINDEXED, title, \
                 content,\n",
                "    content='', contentless_delete=1,\n",
                "    tokenize='unicode61 remove_diacritics 1');\n",
                "CREATE VIRTUAL TABLE sessions_fts_trigram USING fts5(\n",
                "    agent_name UNINDEXED, session_id UNINDEXED, title, \
                 content,\n",
                "    content='', contentless_delete=1,\n",
                "    tokenize='trigram');\n",
                "PRAGMA user_version = 5;",
            ))?;
        }
        let current = now();
        if last_cleanup_at(&transaction)?
            .is_none_or(|ts| current - ts >= DAY_SECONDS)
        {
            run_expiry_cleanup(&transaction, current)?;
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
        let indexed: HashMap<String, IndexedRow> = self
            .connection
            .prepare(
                "SELECT session_id, updated_signature, fts_rowid, indexed_at, \
                 last_seen_at, content_hash FROM index_state WHERE agent = ?",
            )?
            .query_map([info.name], |r| {
                Ok((
                    r.get(0)?,
                    IndexedRow {
                        signature: r.get(1)?,
                        rowid: r.get(2)?,
                        observed: r.get(3)?,
                        last_seen_at: r.get(4)?,
                        content_hash: r.get(5)?,
                    },
                ))
            })?
            .collect::<Result<_, _>>()?;
        // Rows expire after 30 unseen days. Skipping the UPDATE when no row is
        // stale avoids acquiring a SQLite write lock on warm searches.
        let stale_seen: Vec<&str> = sessions
            .iter()
            .filter_map(|session| {
                indexed
                    .get(&session.id)
                    .is_some_and(|row| {
                        row.last_seen_at < observed - DAY_SECONDS
                    })
                    .then_some(session.id.as_str())
            })
            .collect();
        if !stale_seen.is_empty() {
            self.connection.execute(
                "UPDATE index_state SET last_seen_at = ? WHERE agent = ? AND \
                 last_seen_at < ? AND session_id IN (SELECT value FROM \
                 json_each(?))",
                params![
                    observed,
                    info.name,
                    observed - DAY_SECONDS,
                    serde_json::to_string(&stale_seen)?
                ],
            )?;
        }
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
        if pending.is_empty() {
            return Ok((0, Vec::new()));
        }
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
        let workers = std::thread::available_parallelism()
            .map_or(4, std::num::NonZero::get);
        let read = |reads: &[(&Session, String)]| {
            std::thread::scope(|scope| {
                let jobs: Vec<_> = reads
                    .iter()
                    .map(|(session, _)| {
                        let cache = &cache;
                        scope.spawn(move || {
                            let mut diagnostics = Vec::new();
                            let prepared = cache
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
                                    let raw =
                                        crate::query::transcript::searchable(
                                            &data,
                                        );
                                    let hash =
                                        content_hash(&session.title, &raw);
                                    let cjk_title =
                                        separate_cjk(&session.title);
                                    let cjk_content = separate_cjk(&raw);
                                    let trigram_title =
                                        fold_trigram(&session.title);
                                    let trigram_content = fold_trigram(&raw);
                                    PreparedText {
                                        raw,
                                        hash,
                                        cjk_title,
                                        cjk_content,
                                        trigram_title,
                                        trigram_content,
                                    }
                                });
                            (prepared, diagnostics)
                        })
                    })
                    .collect();
                jobs.into_iter()
                    .map(|job| {
                        job.join().map_err(|_| "Index reader panicked".into())
                    })
                    .collect::<crate::Result<Vec<_>>>()
            })
        };
        let mut added = 0;
        let mut failed = Vec::new();
        let mut rest = &pending[..];
        while !rest.is_empty() {
            let limit = rest.len().min(32);
            let mut texts = Vec::new();
            let mut bytes = 0;
            while texts.len() < limit && bytes < BATCH_BYTES {
                let reads =
                    read(&rest[texts.len()..limit.min(texts.len() + workers)])?;
                bytes += reads
                    .iter()
                    .filter_map(|(prepared, _)| prepared.as_ref().ok())
                    .map(|prepared| {
                        prepared.raw.len()
                            + prepared
                                .cjk_content
                                .as_ref()
                                .map_or(0, String::len)
                            + prepared
                                .trigram_content
                                .as_ref()
                                .map_or(0, String::len)
                    })
                    .sum::<usize>();
                texts.extend(reads);
            }
            let (batch, remaining) = rest.split_at(texts.len());
            rest = remaining;
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
            {
                let mut select_latest = transaction.prepare(
                    "SELECT updated_signature, fts_rowid, indexed_at, \
                     last_seen_at, content_hash FROM index_state WHERE agent \
                     = ? AND session_id = ?",
                )?;
                let mut update_state = transaction.prepare(
                    "UPDATE index_state SET source_path = ?, \
                     updated_signature = ?, content_hash = ?, indexed_at = ?, \
                     last_seen_at = MAX(last_seen_at, ?), session_updated_at \
                     = ?, session_created_at = ? WHERE fts_rowid = ?",
                )?;
                let mut insert_state = transaction.prepare(
                    "INSERT INTO index_state (agent, session_id, source_path, \
                     updated_signature, content_hash, indexed_at, \
                     last_seen_at, session_updated_at, session_created_at) \
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                )?;
                let mut insert_content = transaction.prepare(
                    "INSERT INTO session_content (fts_rowid, title, content) \
                     VALUES (?, ?, ?)",
                )?;
                let mut insert_fts = transaction.prepare(
                    "INSERT INTO sessions_fts (rowid, agent_name, session_id, \
                     title, content) VALUES (?, ?, ?, ?, ?)",
                )?;
                let mut insert_trigram = transaction.prepare(
                    "INSERT INTO sessions_fts_trigram (rowid, agent_name, \
                     session_id, title, content) VALUES (?, ?, ?, ?, ?)",
                )?;
                for ((session, signature), (prepared, _)) in
                    batch.iter().zip(texts)
                {
                    let latest = select_latest
                        .query_row(params![info.name, session.id], |r| {
                            Ok(IndexedRow {
                                signature: r.get(0)?,
                                rowid: r.get(1)?,
                                observed: r.get(2)?,
                                last_seen_at: r.get(3)?,
                                content_hash: r.get(4)?,
                            })
                        })
                        .optional()?;
                    if latest.as_ref().is_some_and(|row| {
                        row.signature == *signature || row.observed > observed
                    }) || (latest.is_none()
                        && indexed.contains_key(&session.id))
                    {
                        continue;
                    }
                    let Ok(prepared) = prepared else {
                        if let Some(row) = latest {
                            delete(&transaction, row.rowid)?;
                        }
                        failed.push(session.id.clone());
                        continue;
                    };
                    let (rowid, changed) = if let Some(row) = latest {
                        let unchanged = row.content_hash.as_slice()
                            == prepared.hash.as_slice();
                        if !unchanged {
                            delete_text(&transaction, row.rowid)?;
                        }
                        update_state.execute(params![
                            crate::storage::source_io::path_text(
                                &session.source_path
                            ),
                            signature,
                            prepared.hash.as_slice(),
                            observed,
                            observed,
                            session.updated_at.as_microsecond() as f64 / 1e6,
                            session.created_at.as_microsecond() as f64 / 1e6,
                            row.rowid
                        ])?;
                        (row.rowid, !unchanged)
                    } else {
                        insert_state.execute(params![
                            info.name,
                            session.id,
                            crate::storage::source_io::path_text(
                                &session.source_path
                            ),
                            signature,
                            prepared.hash.as_slice(),
                            observed,
                            observed,
                            session.updated_at.as_microsecond() as f64 / 1e6,
                            session.created_at.as_microsecond() as f64 / 1e6
                        ])?;
                        (transaction.last_insert_rowid(), true)
                    };
                    if changed {
                        insert_content.execute(params![
                            rowid,
                            session.title,
                            prepared.raw
                        ])?;
                        insert_fts.execute(params![
                            rowid,
                            info.name,
                            session.id,
                            prepared
                                .cjk_title
                                .as_deref()
                                .unwrap_or(&session.title),
                            prepared
                                .cjk_content
                                .as_deref()
                                .unwrap_or(&prepared.raw)
                        ])?;
                        insert_trigram.execute(params![
                            rowid,
                            info.name,
                            session.id,
                            prepared
                                .trigram_title
                                .as_deref()
                                .unwrap_or(&session.title),
                            prepared
                                .trigram_content
                                .as_deref()
                                .unwrap_or(&prepared.raw)
                        ])?;
                    }
                    added += 1;
                }
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
        if keys.is_empty() {
            return Ok(Vec::new());
        }
        let snapshot = self.connection.unchecked_transaction()?;
        let candidates = match search_plan(query) {
            SearchPlan::Fallback => return self.literal_search(query, keys),
            SearchPlan::Cjk(expression) => {
                self.single_fts_candidates("sessions_fts", &expression, keys)?
            }
            SearchPlan::Trigram(expression) => self.single_fts_candidates(
                "sessions_fts_trigram",
                &expression,
                keys,
            )?,
            SearchPlan::Both { cjk, trigram } => {
                self.mixed_fts_candidates(&cjk, &trigram, keys)?
            }
        };
        let mut text = snapshot.prepare(
            "SELECT title, content FROM session_content WHERE fts_rowid = ?",
        )?;
        let mut results = Vec::new();
        for (provider, id, rowid, score) in candidates {
            let Some((title, content)) = text
                .query_row([rowid], |r| {
                    Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
                })
                .optional()?
            else {
                continue;
            };
            let Some(evidence) = query.find(&[&title, &content]) else {
                continue;
            };
            results.push(SearchResult {
                provider,
                id,
                snippet: evidence.snippet,
                rank: -score,
            });
        }
        drop(text);
        snapshot.commit()?;
        Ok(results)
    }

    fn single_fts_candidates(
        &self,
        table: &str,
        expression: &str,
        keys: &HashSet<(String, String)>,
    ) -> crate::Result<Vec<(String, String, i64, f64)>> {
        // Unary + keeps MATCH as the FTS scan instead of repeating it per key.
        // Filtering returned rows retains the global BM25 corpus.
        let sql = format!(
            "SELECT s.agent, s.session_id, f.rowid, bm25({table}) FROM {table} \
             f JOIN index_state s ON s.fts_rowid = f.rowid WHERE {table} MATCH \
             ? AND +f.rowid IN (SELECT scoped.fts_rowid FROM json_each(?) \
             scope JOIN index_state scoped ON scoped.agent = \
             json_extract(scope.value, '$[0]') AND scoped.session_id = \
             json_extract(scope.value, '$[1]')) ORDER BY bm25({table}), \
             s.session_updated_at DESC, s.session_created_at DESC, s.agent, \
             s.session_id"
        );
        let mut ranked = self.connection.prepare(&sql)?;
        let rows = ranked
            .query_map(
                params![expression, serde_json::to_string(keys)?],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    fn mixed_fts_candidates(
        &self,
        cjk_expression: &str,
        trigram_expression: &str,
        keys: &HashSet<(String, String)>,
    ) -> crate::Result<Vec<(String, String, i64, f64)>> {
        // MATERIALIZED forces each FTS5 MATCH to scan its own index and score
        // against the global corpus before intersecting rowids.
        let sql = "WITH scoped(rowid) AS MATERIALIZED ( \
             SELECT s.fts_rowid FROM json_each(?3) scope JOIN index_state s \
             ON s.agent = json_extract(scope.value, '$[0]') \
             AND s.session_id = json_extract(scope.value, '$[1]')), \
             cjk AS MATERIALIZED ( \
             SELECT rowid, bm25(sessions_fts) AS score FROM sessions_fts \
             WHERE sessions_fts MATCH ?1 AND +rowid IN scoped), \
             tri AS MATERIALIZED ( \
             SELECT rowid, bm25(sessions_fts_trigram) AS score FROM \
             sessions_fts_trigram WHERE sessions_fts_trigram MATCH ?2 \
             AND +rowid IN scoped) \
             SELECT s.agent, s.session_id, s.fts_rowid, cjk.score + tri.score \
             AS score FROM cjk JOIN tri ON tri.rowid = cjk.rowid JOIN \
             index_state s ON s.fts_rowid = cjk.rowid \
             ORDER BY score, s.session_updated_at DESC, s.session_created_at \
             DESC, s.agent, s.session_id";
        let mut ranked = self.connection.prepare(sql)?;
        let rows = ranked
            .query_map(
                params![
                    cjk_expression,
                    trigram_expression,
                    serde_json::to_string(keys)?
                ],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
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
                "SELECT s.agent, s.session_id, c.title, c.content FROM \
                 index_state s JOIN session_content c ON c.fts_rowid = \
                 s.fts_rowid WHERE {filters}"
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
