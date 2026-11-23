use crate::output::i18n::t;
use crate::providers::contract::{Provider, ProviderInfo};
use crate::query::text::{Mode, TextQuery};
use crate::session::Session;
use crate::session::cache::SessionSignal;
use rusqlite::{Connection, OptionalExtension, params};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::io::Write;
use std::path::Path;

pub struct SearchIndex {
    connection: Connection,
}

pub struct IndexGroup<'a> {
    pub info: &'a ProviderInfo,
    pub provider: &'a dyn Provider,
    pub sessions: &'a [Session],
}

struct IndexedRow {
    signature: String,
    rowid: i64,
    observed: f64,
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

fn first_cjk_byte(text: &str) -> Option<usize> {
    if text.is_ascii() {
        return None;
    }
    let bytes = text.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if (0xE4..=0xE9).contains(&bytes[i])
            && let Some(c) = text[i..].chars().next()
        {
            if cjk(c) {
                return Some(i);
            }
            i += c.len_utf8();
            continue;
        }
        i += 1;
    }
    None
}

fn separate_cjk(text: &str) -> Option<String> {
    let first = first_cjk_byte(text)?;
    let mut output =
        String::with_capacity(text.len() + (text.len() - first) / 3);
    output.push_str(&text[..first]);
    let bytes = text.as_bytes();
    let mut prev_cjk = false;
    let mut prev_ws = text[..first]
        .chars()
        .next_back()
        .is_none_or(crate::query::text::whitespace);
    let mut i = first;
    while i < bytes.len() {
        if bytes[i] < 0x80 {
            let run_start = i;
            if prev_cjk && !crate::query::text::whitespace(bytes[i] as char) {
                output.push(' ');
            }
            while i < bytes.len() && bytes[i] < 0x80 {
                i += 1;
            }
            output.push_str(&text[run_start..i]);
            prev_cjk = false;
            prev_ws = crate::query::text::whitespace(bytes[i - 1] as char);
            continue;
        }
        let c = text[i..].chars().next().unwrap();
        let cur_cjk = cjk(c);
        let cur_ws = !cur_cjk && crate::query::text::whitespace(c);
        if (prev_cjk && !cur_ws) || (cur_cjk && !prev_ws) {
            output.push(' ');
        }
        output.push(c);
        prev_cjk = cur_cjk;
        prev_ws = cur_ws;
        i += c.len_utf8();
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
    let bytes = text.as_bytes();
    let mut i = 0;
    let mut first = None;
    while i < bytes.len() {
        if bytes[i] < 0x80 {
            i += 1;
            continue;
        }
        let c = text[i..].chars().next()?;
        if fold_trigram_char(c) != c {
            first = Some(i);
            break;
        }
        i += c.len_utf8();
    }
    let first = first?;
    let mut output = String::with_capacity(text.len());
    output.push_str(&text[..first]);
    for c in text[first..].chars() {
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

struct TxGuard<'c> {
    conn: &'c Connection,
    active: bool,
}

impl Drop for TxGuard<'_> {
    fn drop(&mut self) {
        if self.active {
            let _ = self.conn.execute_batch("ROLLBACK");
        }
    }
}

struct ByteBudget {
    limit: usize,
    state: std::sync::Mutex<(usize, bool)>,
    cvar: std::sync::Condvar,
}

impl ByteBudget {
    const fn new(limit: usize) -> Self {
        Self {
            limit,
            state: std::sync::Mutex::new((0, false)),
            cvar: std::sync::Condvar::new(),
        }
    }

    fn acquire(&self, bytes: usize) -> Option<BudgetPermit<'_>> {
        let mut guard = self.state.lock().unwrap();
        while !guard.1
            && guard.0 > 0
            && guard.0.saturating_add(bytes) > self.limit
        {
            guard = self.cvar.wait(guard).unwrap();
        }
        if guard.1 {
            return None;
        }
        guard.0 = guard.0.saturating_add(bytes);
        drop(guard);
        Some(BudgetPermit {
            budget: self,
            bytes,
        })
    }

    fn release(&self, bytes: usize) {
        let mut guard = self.state.lock().unwrap();
        guard.0 = guard.0.saturating_sub(bytes);
        drop(guard);
        self.cvar.notify_all();
    }

    fn grow(&self, extra: usize) {
        if extra > 0 {
            let mut guard = self.state.lock().unwrap();
            guard.0 = guard.0.saturating_add(extra);
        }
    }

    fn cancel(&self) {
        let mut guard = self.state.lock().unwrap();
        guard.1 = true;
        drop(guard);
        self.cvar.notify_all();
    }
}

struct CancelBudget<'a>(&'a ByteBudget);

impl Drop for CancelBudget<'_> {
    fn drop(&mut self) {
        self.0.cancel();
    }
}

struct BudgetPermit<'a> {
    budget: &'a ByteBudget,
    bytes: usize,
}

impl BudgetPermit<'_> {
    fn grow_to(&mut self, actual: usize) {
        if actual > self.bytes {
            self.budget.grow(actual - self.bytes);
            self.bytes = actual;
        }
    }

    fn disarm(mut self) -> usize {
        let bytes = self.bytes;
        self.bytes = 0;
        bytes
    }
}

impl Drop for BudgetPermit<'_> {
    fn drop(&mut self) {
        if self.bytes > 0 {
            self.budget.release(self.bytes);
        }
    }
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
        connection.execute_batch(
            "PRAGMA synchronous = NORMAL; PRAGMA temp_store = MEMORY; PRAGMA cache_size = -16000;",
        )?;
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
        let page_count: i64 =
            connection.query_row("PRAGMA page_count", [], |row| row.get(0))?;
        if page_count == 0 {
            connection.execute_batch("PRAGMA page_size = 16384;")?;
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
                "INSERT INTO sessions_fts_trigram(sessions_fts_trigram, rank) \
                 VALUES('pgsz', 16384);\n",
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
        self.clear_many(&[provider])
    }

    pub fn clear_many(&mut self, providers: &[&str]) -> crate::Result<()> {
        if providers.is_empty() {
            return Ok(());
        }
        let transaction = self.connection.transaction_with_behavior(
            rusqlite::TransactionBehavior::Immediate,
        )?;
        let mut select = transaction
            .prepare("SELECT fts_rowid FROM index_state WHERE agent = ?")?;
        let mut rows = Vec::new();
        for &provider in providers {
            let mut ids = select.query([provider])?;
            while let Some(r) = ids.next()? {
                rows.push(r.get::<_, i64>(0)?);
            }
        }
        drop(select);
        for rowid in rows {
            delete(&transaction, rowid)?;
        }
        transaction.commit()?;
        Ok(())
    }

    pub fn update(
        &mut self,
        info: &ProviderInfo,
        provider: &dyn Provider,
        sessions: &[Session],
        zh: bool,
        warnings: &mut impl Write,
    ) -> crate::Result<(usize, Vec<String>)> {
        let mut results = self.update_groups(
            &[IndexGroup {
                info,
                provider,
                sessions,
            }],
            zh,
            warnings,
        )?;
        Ok(results.pop().unwrap_or_default())
    }

    #[allow(
        clippy::cast_precision_loss,
        clippy::too_many_lines,
        reason = "The shared SQLite schema stores timestamps as floating-point seconds"
    )]
    pub fn update_groups(
        &mut self,
        groups: &[IndexGroup<'_>],
        zh: bool,
        warnings: &mut impl Write,
    ) -> crate::Result<Vec<(usize, Vec<String>)>> {
        if groups.is_empty() {
            return Ok(Vec::new());
        }
        let observed = now();
        let mut stat_cache = HashMap::new();
        let mut indexed_by_group: Vec<HashMap<String, (String, f64)>> =
            Vec::with_capacity(groups.len());
        let mut pending: Vec<(usize, &Session, String, u64)> = Vec::new();
        let mut load_stmt = self.connection.prepare(
            "SELECT session_id, updated_signature, last_seen_at \
             FROM index_state WHERE agent = ?",
        )?;
        let mut stale_stmt = self.connection.prepare(
            "UPDATE index_state SET last_seen_at = ? WHERE agent = ? AND \
             last_seen_at < ? AND session_id IN (SELECT value FROM \
             json_each(?))",
        )?;
        for (g, group) in groups.iter().enumerate() {
            let indexed: HashMap<String, (String, f64)> = load_stmt
                .query_map([group.info.name], |r| {
                    Ok((r.get(0)?, (r.get(1)?, r.get(2)?)))
                })?
                .collect::<Result<_, _>>()?;
            // Rows expire after 30 unseen days. Skipping the UPDATE when no
            // row is stale avoids acquiring a SQLite write lock on warm searches.
            let stale_seen: Vec<&str> = group
                .sessions
                .iter()
                .filter_map(|session| {
                    indexed
                        .get(&session.id)
                        .is_some_and(|&(_, last_seen)| {
                            last_seen < observed - DAY_SECONDS
                        })
                        .then_some(session.id.as_str())
                })
                .collect();
            if !stale_seen.is_empty() {
                stale_stmt.execute(params![
                    observed,
                    group.info.name,
                    observed - DAY_SECONDS,
                    serde_json::to_string(&stale_seen)?
                ])?;
            }
            let start_len = pending.len();
            for session in group.sessions {
                let signature = SessionSignal::new_with_cache(
                    group.provider,
                    session,
                    &mut stat_cache,
                )
                .signature();
                if indexed
                    .get(&session.id)
                    .is_none_or(|(old_sig, _)| *old_sig != signature)
                {
                    let size = stat_cache
                        .get(&session.source_path)
                        .and_then(|entry| entry.2)
                        .unwrap_or(0);
                    pending.push((g, session, signature, size));
                }
            }
            let group_pending = pending.len() - start_len;
            if group_pending >= 10 {
                writeln!(
                    warnings,
                    "{}",
                    t(
                        "INDEX_UPDATE_PROGRESS",
                        zh,
                        &[
                            ("agent", group.info.display_name.into()),
                            ("count", group_pending.to_string())
                        ]
                    )
                )?;
            }
            indexed_by_group.push(indexed);
        }
        drop(load_stmt);
        drop(stale_stmt);
        if pending.is_empty() {
            return Ok(vec![(0, Vec::new()); groups.len()]);
        }
        let mut seen_keys = HashSet::with_capacity(pending.len());
        let has_duplicates = pending.iter().any(|&(g, session, _, _)| {
            !seen_keys.insert((g, session.id.as_str()))
        });
        let mut path_counts: HashMap<&Path, usize> = HashMap::new();
        for &(_, session, _, _) in &pending {
            *path_counts
                .entry(session.source_path.as_path())
                .or_insert(0) += 1;
        }
        let estimated_bytes: Vec<usize> = pending
            .iter()
            .map(|&(_, session, _, size)| {
                let unknown_expanded = size == 0
                    || crate::storage::zstd::compressed(&session.source_path)
                    || session
                        .source_path
                        .extension()
                        .is_some_and(|ext| ext.eq_ignore_ascii_case("gz"));
                if unknown_expanded {
                    return BATCH_BYTES;
                }
                let shared = path_counts
                    .get(session.source_path.as_path())
                    .copied()
                    .unwrap_or(1)
                    .max(1) as u64;
                usize::try_from(size / shared)
                    .unwrap_or(BATCH_BYTES)
                    .saturating_mul(2)
                    .max(4096)
            })
            .collect();
        let mut dispatch: Vec<usize> = (0..pending.len()).collect();
        if !has_duplicates {
            dispatch.sort_by(|&a, &b| pending[b].3.cmp(&pending[a].3));
        }
        let mut added = vec![0usize; groups.len()];
        let mut failed_by_idx: Vec<(usize, usize, String)> = Vec::new();
        let mut diags_by_idx: Vec<(
            usize,
            Vec<crate::providers::contract::RecoverableDiagnostic>,
        )> = Vec::new();
        let workers = if has_duplicates {
            1
        } else {
            std::thread::available_parallelism()
                .map_or(4, std::num::NonZero::get)
                .min(pending.len())
        };
        let next = std::sync::atomic::AtomicUsize::new(0);
        let budget = ByteBudget::new(BATCH_BYTES);
        let conn = &mut self.connection;
        std::thread::scope(|scope| -> crate::Result<()> {
            let _cancel = CancelBudget(&budget);
            let (sender, receiver) = std::sync::mpsc::sync_channel(workers * 2);
            for _ in 0..workers {
                let sender = sender.clone();
                let next = &next;
                let budget = &budget;
                let pending = &pending;
                let dispatch = &dispatch;
                let estimated_bytes = &estimated_bytes;
                scope.spawn(move || {
                    loop {
                        let pos = next
                            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        let Some(&idx) = dispatch.get(pos) else {
                            break;
                        };
                        let Some(mut permit) =
                            budget.acquire(estimated_bytes[idx])
                        else {
                            break;
                        };
                        let (g, session, _, _) = pending[idx];
                        let mut diagnostics = Vec::new();
                        let prepared = groups[g]
                            .provider
                            .read(session, zh, &mut |d| {
                                diagnostics.push(d);
                                Ok(())
                            })
                            .map(|data| {
                                let raw =
                                    crate::query::transcript::searchable(&data);
                                let hash = content_hash(&session.title, &raw);
                                let cjk_title = separate_cjk(&session.title);
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
                        if let Ok(ref prepared) = prepared {
                            let actual = prepared.raw.len()
                                + prepared
                                    .cjk_content
                                    .as_ref()
                                    .map_or(0, String::len)
                                + prepared
                                    .trigram_content
                                    .as_ref()
                                    .map_or(0, String::len);
                            permit.grow_to(actual);
                        }
                        let reserved = permit.disarm();
                        if sender
                            .send((idx, reserved, prepared, diagnostics))
                            .is_err()
                        {
                            budget.release(reserved);
                            break;
                        }
                    }
                });
            }
            drop(sender);
            let mut batch_bytes = 0usize;
            let mut in_tx = false;
            let mut tx_guard = TxGuard {
                conn,
                active: false,
            };
            let mut select_latest = conn.prepare(
                "SELECT updated_signature, fts_rowid, indexed_at, \
                 content_hash FROM index_state WHERE \
                 agent = ? AND session_id = ?",
            )?;
            let mut update_state = conn.prepare(
                "UPDATE index_state SET source_path = ?, \
                 updated_signature = ?, content_hash = ?, indexed_at \
                 = ?, last_seen_at = MAX(last_seen_at, ?), \
                 session_updated_at = ?, session_created_at = ? WHERE \
                 fts_rowid = ?",
            )?;
            let mut insert_state = conn.prepare(
                "INSERT INTO index_state (agent, session_id, \
                 source_path, updated_signature, content_hash, \
                 indexed_at, last_seen_at, session_updated_at, \
                 session_created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )?;
            let mut insert_content = conn.prepare(
                "INSERT INTO session_content (fts_rowid, title, \
                 content) VALUES (?, ?, ?)",
            )?;
            let mut insert_fts = conn.prepare(
                "INSERT INTO sessions_fts (rowid, agent_name, \
                 session_id, title, content) VALUES (?, ?, ?, ?, ?)",
            )?;
            let mut insert_trigram = conn.prepare(
                "INSERT INTO sessions_fts_trigram (rowid, agent_name, \
                 session_id, title, content) VALUES (?, ?, ?, ?, ?)",
            )?;
            for (idx, reserved, prepared, diagnostics) in receiver {
                let _release = BudgetPermit {
                    budget: &budget,
                    bytes: reserved,
                };
                if !diagnostics.is_empty() {
                    diags_by_idx.push((idx, diagnostics));
                }
                if !in_tx {
                    tx_guard.conn.execute_batch("BEGIN IMMEDIATE")?;
                    tx_guard.active = true;
                    in_tx = true;
                }
                let step = (|| -> crate::Result<()> {
                    let (g, session, ref signature, _) = pending[idx];
                    let info = groups[g].info;
                    let latest = select_latest
                        .query_row(params![info.name, session.id], |r| {
                            Ok(IndexedRow {
                                signature: r.get(0)?,
                                rowid: r.get(1)?,
                                observed: r.get(2)?,
                                content_hash: r.get(3)?,
                            })
                        })
                        .optional()?;
                    if latest.as_ref().is_some_and(|row| {
                        row.signature == *signature || row.observed > observed
                    }) || (latest.is_none()
                        && indexed_by_group[g].contains_key(&session.id))
                    {
                        return Ok(());
                    }
                    let Ok(prepared) = prepared else {
                        if let Some(row) = latest {
                            delete(tx_guard.conn, row.rowid)?;
                        }
                        failed_by_idx.push((idx, g, session.id.clone()));
                        return Ok(());
                    };
                    let doc_bytes = prepared.raw.len()
                        + prepared.cjk_content.as_ref().map_or(0, String::len)
                        + prepared
                            .trigram_content
                            .as_ref()
                            .map_or(0, String::len);
                    let (rowid, changed) = if let Some(row) = latest {
                        let unchanged = row.content_hash.as_slice()
                            == prepared.hash.as_slice();
                        if !unchanged {
                            delete_text(tx_guard.conn, row.rowid)?;
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
                        (tx_guard.conn.last_insert_rowid(), true)
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
                    added[g] += 1;
                    batch_bytes += doc_bytes;
                    if batch_bytes >= BATCH_BYTES {
                        tx_guard.conn.execute_batch("COMMIT")?;
                        tx_guard.active = false;
                        in_tx = false;
                        batch_bytes = 0;
                    }
                    Ok(())
                })();
                if let Err(err) = step {
                    budget.cancel();
                    return Err(err);
                }
            }
            if in_tx {
                tx_guard.conn.execute_batch("COMMIT")?;
                tx_guard.active = false;
            }
            Ok(())
        })?;
        diags_by_idx.sort_by_key(|(idx, _)| *idx);
        for (_, diagnostics) in diags_by_idx {
            for diagnostic in &diagnostics {
                writeln!(
                    warnings,
                    "{}",
                    crate::output::diagnostics::record_warning(diagnostic, zh)
                )?;
            }
        }
        failed_by_idx.sort_by_key(|(idx, _, _)| *idx);
        let mut failed_by_group: Vec<Vec<String>> =
            vec![Vec::new(); groups.len()];
        for (_, g, id) in failed_by_idx {
            failed_by_group[g].push(id);
        }
        for (g, failed) in failed_by_group.iter().enumerate() {
            if !failed.is_empty() {
                writeln!(
                    warnings,
                    "{}",
                    crate::output::i18n::terminal(
                        "WARN_INDEX_SKIPPED_SESSIONS",
                        zh,
                        &[
                            ("agent", groups[g].info.display_name.into()),
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
        }
        Ok(added.into_iter().zip(failed_by_group).collect())
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
        let sql = format!(
            "SELECT s.agent, s.session_id, f.rowid, bm25({table}) FROM {table} \
             f JOIN index_state s ON s.fts_rowid = f.rowid WHERE {table} MATCH \
             ? ORDER BY bm25({table}), s.session_updated_at DESC, \
             s.session_created_at DESC, s.agent, s.session_id"
        );
        let mut ranked = self.connection.prepare(&sql)?;
        let mut rows = ranked.query([expression])?;
        let mut out = Vec::new();
        while let Some(r) = rows.next()? {
            let provider: String = r.get(0)?;
            let id: String = r.get(1)?;
            if keys.contains(&(provider.clone(), id.clone())) {
                out.push((provider, id, r.get(2)?, r.get(3)?));
            }
        }
        Ok(out)
    }

    fn mixed_fts_candidates(
        &self,
        cjk_expression: &str,
        trigram_expression: &str,
        keys: &HashSet<(String, String)>,
    ) -> crate::Result<Vec<(String, String, i64, f64)>> {
        let sql = "WITH cjk AS MATERIALIZED ( \
             SELECT rowid, bm25(sessions_fts) AS score FROM sessions_fts \
             WHERE sessions_fts MATCH ?1), \
             tri AS MATERIALIZED ( \
             SELECT rowid, bm25(sessions_fts_trigram) AS score FROM \
             sessions_fts_trigram WHERE sessions_fts_trigram MATCH ?2) \
             SELECT s.agent, s.session_id, s.fts_rowid, cjk.score + tri.score \
             AS score FROM cjk JOIN tri ON tri.rowid = cjk.rowid JOIN \
             index_state s ON s.fts_rowid = cjk.rowid \
             ORDER BY score, s.session_updated_at DESC, s.session_created_at \
             DESC, s.agent, s.session_id";
        let mut ranked = self.connection.prepare(sql)?;
        let mut rows =
            ranked.query(params![cjk_expression, trigram_expression])?;
        let mut out = Vec::new();
        while let Some(r) = rows.next()? {
            let provider: String = r.get(0)?;
            let id: String = r.get(1)?;
            if keys.contains(&(provider.clone(), id.clone())) {
                out.push((provider, id, r.get(2)?, r.get(3)?));
            }
        }
        Ok(out)
    }

    fn literal_search(
        &self,
        query: &TextQuery,
        keys: &HashSet<(String, String)>,
    ) -> crate::Result<Vec<SearchResult>> {
        let mut results = Vec::new();
        if keys.len() > 64 {
            let mut agents: Vec<&str> =
                keys.iter().map(|(provider, _)| provider.as_str()).collect();
            agents.sort_unstable();
            agents.dedup();
            let placeholders = vec!["?"; agents.len()].join(", ");
            let sql = format!(
                "SELECT s.agent, s.session_id, c.title, c.content FROM \
                 index_state s JOIN session_content c ON c.fts_rowid = \
                 s.fts_rowid WHERE s.agent IN ({placeholders})"
            );
            let mut statement = self.connection.prepare(&sql)?;
            let mut rows =
                statement.query(rusqlite::params_from_iter(agents))?;
            while let Some(row) = rows.next()? {
                let provider: String = row.get(0)?;
                let id: String = row.get(1)?;
                if !keys.contains(&(provider.clone(), id.clone())) {
                    continue;
                }
                let title = row.get_ref(2)?.as_str()?;
                let content = row.get_ref(3)?.as_str()?;
                if let Some(evidence) = query.find(&[title, content]) {
                    results.push(SearchResult {
                        provider,
                        id,
                        snippet: evidence.snippet,
                        rank: if evidence.title_matches { 1.0 } else { 0.0 },
                    });
                }
            }
            return Ok(results);
        }
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
                let title = row.get_ref(2)?.as_str()?;
                let content = row.get_ref(3)?.as_str()?;
                if let Some(evidence) = query.find(&[title, content]) {
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
