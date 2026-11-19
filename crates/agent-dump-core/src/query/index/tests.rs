use super::*;
use crate::providers::contract::{DiagnosticSink, Discovery, Lookup, Window};
use crate::session::timestamp::Timestamp;
use crate::session::{Message, Part, SessionData, Stats};

struct Reader<F>(F);
impl<F: Fn(&Session) -> crate::Result<String> + Send + Sync> Provider
    for Reader<F>
{
    fn discover(
        &mut self,
        _: Window,
        _: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Discovery> {
        unreachable!()
    }
    fn find(
        &mut self,
        _: &str,
        _: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Lookup> {
        unreachable!()
    }
    fn read(
        &self,
        session: &Session,
        _: bool,
        _: &mut DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        Ok(session.payload(
            vec![Message::new(
                "m".into(),
                "user",
                0,
                vec![Part::text((self.0)(session)?, 0)],
            )],
            Stats::default(),
        ))
    }
    fn source_root(&self) -> &Path {
        Path::new(".")
    }
    fn select_source(&mut self) -> crate::Result<Option<&Path>> {
        Ok(None)
    }
    fn search_roots(
        &self,
    ) -> crate::Result<crate::providers::contract::SearchRoots> {
        Ok(Vec::new())
    }
}

fn info() -> &'static ProviderInfo {
    &crate::providers::registry::for_name("codex").unwrap().info
}
fn session(root: &Path, id: &str, revision: i64) -> Session {
    session_with_title(root, id, "task", revision)
}
fn session_with_title(
    root: &Path,
    id: &str,
    title: &str,
    revision: i64,
) -> Session {
    Session::new(
        id.into(),
        title.into(),
        root.join(id),
        Timestamp::UNIX_EPOCH,
        Timestamp::from_microsecond(revision).unwrap(),
    )
}
fn update(
    index: &mut SearchIndex,
    provider: &dyn Provider,
    sessions: &[Session],
) -> (usize, Vec<String>) {
    index
        .update(info(), provider, sessions, false, &mut Vec::new())
        .unwrap()
}
fn keys(ids: &[&str]) -> HashSet<(String, String)> {
    ids.iter()
        .map(|id| ("codex".into(), (*id).into()))
        .collect()
}
fn search(index: &SearchIndex, text: &str, id: &str) -> Vec<SearchResult> {
    index
        .search(&TextQuery::new(text, Mode::Terms), &keys(&[id]))
        .unwrap()
}
fn assert_equivalent_to_literal(
    index: &SearchIndex,
    query: &TextQuery,
    scope: &HashSet<(String, String)>,
) -> Vec<SearchResult> {
    let indexed = index.search(query, scope).unwrap();
    let fallback = index.literal_search(query, scope).unwrap();
    let indexed_map: HashMap<_, _> = indexed
        .iter()
        .map(|r| ((r.provider.clone(), r.id.clone()), r.snippet.clone()))
        .collect();
    let fallback_map: HashMap<_, _> = fallback
        .iter()
        .map(|r| ((r.provider.clone(), r.id.clone()), r.snippet.clone()))
        .collect();
    assert_eq!(
        indexed_map, fallback_map,
        "indexed search diverged from literal_search for {:?}",
        query.literals
    );
    indexed
}

#[test]
fn case_variants_sqlite_folds_apart_match_like_the_text_query() {
    let directory = tempfile::tempdir().unwrap();
    let mut index =
        SearchIndex::at(&directory.path().join("index.db")).unwrap();
    let body = "ᲐᲑᲒᲓ ᏣᎳᎩ 𞤀𞤁𞤂 ᲀᲁᲂ ﬆab ſun \u{212a}elvin Σigma";
    let reader = Reader(move |_: &Session| Ok(body.into()));
    update(&mut index, &reader, &[session(directory.path(), "s", 0)]);
    for text in [
        "აბგდ",
        "ꮳꮃꭹ",
        "𞤢𞤣𞤤",
        "ВДО",
        "вдо",
        "ﬅab",
        "SUN",
        "kelvin",
        "ςigma",
    ] {
        let query = TextQuery::new(text, Mode::Terms);
        assert!(
            matches!(search_plan(&query), SearchPlan::Trigram(_)),
            "{text}"
        );
        assert!(query.find(&[body]).is_some(), "{text}");
        let hits = assert_equivalent_to_literal(&index, &query, &keys(&["s"]));
        assert_eq!(hits.len(), 1, "{text}");
    }
}

#[test]
fn dotted_and_dotless_i_route_through_trigram_and_preserve_raw_snippets() {
    let directory = tempfile::tempdir().unwrap();
    let mut index =
        SearchIndex::at(&directory.path().join("index.db")).unwrap();
    let bodies: HashMap<&str, &str> = HashMap::from([
        ("lower", "istanbul migration pipeline"),
        ("upper", "ISTANBUL MIGRATION PIPELINE"),
        ("dotted", "İstanbul mİgration pİpeline"),
        ("dotless", "ıstanbul mıgration pıpeline"),
        ("miss", "quartz basalt granite"),
    ]);
    let sessions: Vec<_> = bodies
        .keys()
        .map(|id| session(directory.path(), id, 0))
        .collect();
    let reader = Reader(move |s: &Session| Ok(bodies[s.id.as_str()].into()));
    update(&mut index, &reader, &sessions);
    let scope = keys(&["lower", "upper", "dotted", "dotless", "miss"]);
    for text in ["istanbul", "ISTANBUL", "İstanbul", "ıstanbul", "migration"]
    {
        let query = TextQuery::new(text, Mode::Terms);
        assert!(
            matches!(search_plan(&query), SearchPlan::Trigram(_)),
            "{text}"
        );
        let hits = assert_equivalent_to_literal(&index, &query, &scope);
        assert_eq!(hits.len(), 4, "{text}");
        let dotted = hits.iter().find(|h| h.id == "dotted").unwrap();
        assert!(
            dotted.snippet.contains("**İstanbul**")
                || dotted.snippet.contains("**mİgration**"),
            "raw text should be preserved in snippet: {}",
            dotted.snippet
        );
    }
}

#[test]
fn every_cased_unicode_char_folds_equivalently_to_regex_in_trigram() {
    let connection = Connection::open_in_memory().unwrap();
    connection
        .execute_batch(
            "CREATE VIRTUAL TABLE t USING fts5(body, content='', \
             tokenize='trigram');",
        )
        .unwrap();
    let mut samples = Vec::new();
    let mut rowid = 1_i64;
    let mut insert = connection
        .prepare("INSERT INTO t (rowid, body) VALUES (?, ?)")
        .unwrap();
    for c in '\0'..=char::MAX {
        let mut lower = c.to_lowercase();
        let l = match (lower.next(), lower.next()) {
            (Some(x), None) if x != c => Some(x),
            _ => None,
        };
        let mut upper = c.to_uppercase();
        let u = match (upper.next(), upper.next()) {
            (Some(x), None) if x != c => Some(x),
            _ => None,
        };
        let partner = match c {
            'İ' | 'ı' => Some('i'),
            _ => l.or(u),
        };
        let Some(other) = partner else {
            continue;
        };
        let query =
            TextQuery::new(&format!("{other}{other}{other}"), Mode::Terms);
        let doc = format!("{c}{c}{c}");
        if query.find(&[&doc]).is_none() {
            continue;
        }
        let folded_doc = fold_trigram(&doc);
        insert
            .execute(params![rowid, folded_doc.as_deref().unwrap_or(&doc)])
            .unwrap();
        samples.push((rowid, c, other));
        rowid += 1;
    }
    let mut lookup = connection
        .prepare("SELECT 1 FROM t WHERE t MATCH ? AND rowid = ?")
        .unwrap();
    for (id, c, other) in samples {
        let needle = format!("{other}{other}{other}");
        let folded = fold_trigram(&needle);
        let expr = fts_phrase(folded.as_deref().unwrap_or(&needle));
        let matched: Option<i64> = lookup
            .query_row(params![expr, id], |r| r.get(0))
            .optional()
            .unwrap();
        assert!(
            matched.is_some(),
            "trigram missed case pair U+{:04X} vs U+{:04X}",
            u32::from(c),
            u32::from(other)
        );
    }
}

#[test]
fn mixed_cjk_latin_and_short_terms_route_and_match_equivalently() {
    let directory = tempfile::tempdir().unwrap();
    let mut index =
        SearchIndex::at(&directory.path().join("index.db")).unwrap();
    let sessions = vec![
        session_with_title(directory.path(), "both", "迁移指南", 0),
        session_with_title(directory.path(), "cjk_only", "迁移指南", 0),
        session_with_title(directory.path(), "latin_only", "guide", 0),
        session_with_title(directory.path(), "short_miss", "迁移指南", 0),
        session_with_title(directory.path(), "intra", "修复bug 中a", 0),
    ];
    let reader = Reader(|s: &Session| {
        Ok(match s.id.as_str() {
            "both" => "go migration middleware pipeline".into(),
            "cjk_only" => "只有中文 go".into(),
            "latin_only" => "go migration middleware".into(),
            "short_miss" => "rust migration middleware".into(),
            "intra" => "前缀修复BUG后缀 前缀中A后缀".into(),
            _ => unreachable!(),
        })
    });
    update(&mut index, &reader, &sessions);
    let scope =
        keys(&["both", "cjk_only", "latin_only", "short_miss", "intra"]);

    let mixed = TextQuery::new("迁移 migration", Mode::Terms);
    assert!(matches!(search_plan(&mixed), SearchPlan::Both { .. }));
    let hits = assert_equivalent_to_literal(&index, &mixed, &scope);
    let ids: HashSet<_> = hits.iter().map(|h| h.id.as_str()).collect();
    assert_eq!(ids, HashSet::from(["both", "short_miss"]));

    let mixed_short = TextQuery::new("迁移 migration go", Mode::Terms);
    assert!(matches!(search_plan(&mixed_short), SearchPlan::Both { .. }));
    let hits = assert_equivalent_to_literal(&index, &mixed_short, &scope);
    assert_eq!(
        hits.iter().map(|h| h.id.as_str()).collect::<Vec<_>>(),
        vec!["both"]
    );

    let latin_short = TextQuery::new("middleware go", Mode::Terms);
    assert!(matches!(search_plan(&latin_short), SearchPlan::Trigram(_)));
    let hits = assert_equivalent_to_literal(&index, &latin_short, &scope);
    let ids: HashSet<_> = hits.iter().map(|h| h.id.as_str()).collect();
    assert_eq!(ids, HashSet::from(["both", "latin_only"]));

    let cjk_short = TextQuery::new("迁移 go", Mode::Terms);
    assert!(matches!(search_plan(&cjk_short), SearchPlan::Cjk(_)));
    let hits = assert_equivalent_to_literal(&index, &cjk_short, &scope);
    let ids: HashSet<_> = hits.iter().map(|h| h.id.as_str()).collect();
    assert_eq!(ids, HashSet::from(["both", "cjk_only"]));

    let intra_long = TextQuery::new("修复bug", Mode::Terms);
    assert!(matches!(search_plan(&intra_long), SearchPlan::Trigram(_)));
    let hits = assert_equivalent_to_literal(&index, &intra_long, &scope);
    assert_eq!(
        hits.iter().map(|h| h.id.as_str()).collect::<Vec<_>>(),
        vec!["intra"]
    );

    let intra_short = TextQuery::new("中a", Mode::Terms);
    assert!(matches!(search_plan(&intra_short), SearchPlan::Cjk(_)));
    let hits = assert_equivalent_to_literal(&index, &intra_short, &scope);
    assert_eq!(
        hits.iter().map(|h| h.id.as_str()).collect::<Vec<_>>(),
        vec!["intra"]
    );

    let short_only = TextQuery::new("go", Mode::Terms);
    assert!(matches!(search_plan(&short_only), SearchPlan::Fallback));
    let hits = assert_equivalent_to_literal(&index, &short_only, &scope);
    let ids: HashSet<_> = hits.iter().map(|h| h.id.as_str()).collect();
    assert_eq!(ids, HashSet::from(["both", "cjk_only", "latin_only"]));
}

#[test]
fn bm25_ranking_is_preserved_for_i_terms_and_mixed_queries() {
    let directory = tempfile::tempdir().unwrap();
    let mut index =
        SearchIndex::at(&directory.path().join("index.db")).unwrap();
    let filler = "padding words without target ".repeat(40);
    let sessions = vec![
        session(directory.path(), "low", 1),
        session(directory.path(), "high", 1),
        session(directory.path(), "other", 1),
    ];
    let reader = Reader(move |s: &Session| {
        Ok(match s.id.as_str() {
            "low" => format!("{filler} migration 迁移"),
            "high" => "migration migration migration 迁移 迁移 迁移".into(),
            "other" => filler.clone(),
            _ => unreachable!(),
        })
    });
    update(&mut index, &reader, &sessions);
    let scope = keys(&["low", "high", "other"]);

    let latin_hits = index
        .search(&TextQuery::new("migration", Mode::Terms), &scope)
        .unwrap();
    assert_eq!(
        latin_hits.iter().map(|h| h.id.as_str()).collect::<Vec<_>>(),
        vec!["high", "low"]
    );
    assert!(latin_hits[0].rank > latin_hits[1].rank);
    assert!(latin_hits[1].rank > 0.0);

    let mixed_hits = index
        .search(&TextQuery::new("迁移 migration", Mode::Terms), &scope)
        .unwrap();
    assert_eq!(
        mixed_hits.iter().map(|h| h.id.as_str()).collect::<Vec<_>>(),
        vec!["high", "low"]
    );
    assert!(mixed_hits[0].rank > mixed_hits[1].rank);
    assert!(mixed_hits[1].rank > 0.0);

    let scoped_low = index
        .search(
            &TextQuery::new("迁移 migration", Mode::Terms),
            &keys(&["low"]),
        )
        .unwrap();
    assert_eq!(scoped_low.len(), 1);
    assert!((scoped_low[0].rank - mixed_hits[1].rank).abs() < 1e-9);
}

#[test]
fn schema_v4_migrates_cleanly_to_v5_wal() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("index.db");
    {
        let conn = Connection::open(&path).unwrap();
        conn.execute_batch(
            "CREATE TABLE index_state (
                fts_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL, session_id TEXT NOT NULL,
                source_path TEXT NOT NULL, updated_signature TEXT NOT NULL,
                indexed_at REAL NOT NULL, last_seen_at REAL NOT NULL,
                session_updated_at REAL NOT NULL, session_created_at REAL NOT NULL,
                UNIQUE (agent, session_id));
            CREATE VIRTUAL TABLE sessions_fts USING fts5(
                agent_name UNINDEXED, session_id UNINDEXED, title, content,
                content='', contentless_delete=1,
                tokenize='unicode61 remove_diacritics 1');
            CREATE VIRTUAL TABLE sessions_fts_trigram USING fts5(
                agent_name UNINDEXED, session_id UNINDEXED, title, content,
                tokenize='trigram');
            INSERT INTO index_state VALUES
                (1, 'codex', 'legacy', '/tmp/a', 'sig', 1.0, 1.0, 1.0, 1.0);
            INSERT INTO sessions_fts_trigram(rowid, agent_name, session_id, title, content)
                VALUES (1, 'codex', 'legacy', 'old', 'legacy body');
            PRAGMA user_version = 4;",
        )
        .unwrap();
    }

    let mut index = SearchIndex::at(&path).unwrap();
    let version: i64 = index
        .connection
        .query_row("PRAGMA user_version", [], |r| r.get(0))
        .unwrap();
    let mode: String = index
        .connection
        .query_row("PRAGMA journal_mode", [], |r| r.get(0))
        .unwrap();
    let count: i64 = index
        .connection
        .query_row("SELECT COUNT(*) FROM index_state", [], |r| r.get(0))
        .unwrap();
    assert_eq!(version, 5);
    assert_eq!(mode.to_lowercase(), "wal");
    assert_eq!(count, 0);

    let reader = Reader(|_: &Session| Ok("migrated migration content".into()));
    let (added, failed) =
        update(&mut index, &reader, &[session(directory.path(), "s", 1)]);
    assert_eq!(added, 1);
    assert!(failed.is_empty());
    assert_eq!(search(&index, "migration", "s").len(), 1);
}

#[test]
fn unchanged_content_skips_fts_rewrite_via_content_hash() {
    let directory = tempfile::tempdir().unwrap();
    let mut index =
        SearchIndex::at(&directory.path().join("index.db")).unwrap();
    let body = std::sync::Mutex::new("stable migration text".to_string());
    let reader = Reader(|_: &Session| Ok(body.lock().unwrap().clone()));
    update(&mut index, &reader, &[session(directory.path(), "s", 1)]);

    let (rowid, stored_hash): (i64, Vec<u8>) = index
        .connection
        .query_row(
            "SELECT fts_rowid, content_hash FROM index_state WHERE session_id = 's'",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!(stored_hash, content_hash("task", "stable migration text"));

    index
        .connection
        .execute_batch(
            "CREATE TEMP TABLE rewrite_log (n INTEGER);
             CREATE TEMP TRIGGER track_rewrite BEFORE DELETE ON session_content
             BEGIN INSERT INTO rewrite_log VALUES (1); END;",
        )
        .unwrap();

    update(&mut index, &reader, &[session(directory.path(), "s", 2)]);
    let rewrites: i64 = index
        .connection
        .query_row("SELECT COUNT(*) FROM rewrite_log", [], |r| r.get(0))
        .unwrap();
    let rowid_after: i64 = index
        .connection
        .query_row(
            "SELECT fts_rowid FROM index_state WHERE session_id = 's'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(rewrites, 0);
    assert_eq!(rowid_after, rowid);
    assert_eq!(search(&index, "migration", "s").len(), 1);

    *body.lock().unwrap() = "updated quartz text".into();
    update(&mut index, &reader, &[session(directory.path(), "s", 3)]);
    let rewrites: i64 = index
        .connection
        .query_row("SELECT COUNT(*) FROM rewrite_log", [], |r| r.get(0))
        .unwrap();
    assert_eq!(rewrites, 1);
    assert!(search(&index, "migration", "s").is_empty());
    assert_eq!(search(&index, "quartz", "s").len(), 1);
}

#[test]
fn warm_open_update_and_search_take_no_write_lock_and_throttle_expiry() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("index.db");
    let reader = Reader(|_: &Session| Ok("concurrent migration search".into()));
    let sessions = [session(directory.path(), "s", 1)];
    {
        let mut index = SearchIndex::at(&path).unwrap();
        update(&mut index, &reader, &sessions);
    }

    let writer = Connection::open(&path).unwrap();
    writer.execute_batch("BEGIN IMMEDIATE;").unwrap();
    {
        let mut warm = SearchIndex::at(&path).unwrap();
        let (added, failed) = update(&mut warm, &reader, &sessions);
        assert_eq!(added, 0);
        assert!(failed.is_empty());
        assert_eq!(search(&warm, "migration", "s").len(), 1);
    }
    writer.execute_batch("ROLLBACK;").unwrap();

    writer
        .execute(
            "UPDATE index_state SET last_seen_at = ? WHERE session_id = 's'",
            [31.0f64.mul_add(-DAY_SECONDS, now())],
        )
        .unwrap();
    {
        let throttled = SearchIndex::at(&path).unwrap();
        assert_eq!(search(&throttled, "migration", "s").len(), 1);
    }

    writer
        .execute(
            "UPDATE index_meta SET value = ? WHERE key = 'last_cleanup_at'",
            [now() - DAY_SECONDS - 60.0],
        )
        .unwrap();
    drop(writer);
    let cleaned = SearchIndex::at(&path).unwrap();
    let remaining: i64 = cleaned
        .connection
        .query_row("SELECT COUNT(*) FROM index_state", [], |r| r.get(0))
        .unwrap();
    let content_remaining: i64 = cleaned
        .connection
        .query_row("SELECT COUNT(*) FROM session_content", [], |r| r.get(0))
        .unwrap();
    assert_eq!(remaining, 0);
    assert_eq!(content_remaining, 0);
}
