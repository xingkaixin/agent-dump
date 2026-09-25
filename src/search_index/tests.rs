use super::*;
use crate::provider::{DiagnosticSink, Discovery, Lookup};
use crate::session::{Message, Part, SessionData, Stats};
use crate::timestamp::Timestamp;
use std::sync::{Arc, Condvar, Mutex, mpsc};
use std::time::Duration;

struct Reader<F>(F);
impl<F: Fn(&Session) -> crate::Result<String> + Send + Sync> Provider for Reader<F> {
    fn discover(&mut self, _: i64, _: &mut DiagnosticSink<'_>) -> crate::Result<Discovery> {
        unreachable!()
    }
    fn find(&mut self, _: &str, _: &mut DiagnosticSink<'_>) -> crate::Result<Lookup> {
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
    fn search_roots(&self) -> crate::Result<crate::provider::SearchRoots> {
        Ok(Vec::new())
    }
}

fn info() -> &'static ProviderInfo {
    &crate::registry::for_name("codex").unwrap().info
}
fn session(root: &Path, id: &str, revision: i64) -> Session {
    Session::new(
        id.into(),
        "task".into(),
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
fn search(index: &SearchIndex, text: &str, id: &str) -> Vec<SearchResult> {
    index
        .search(
            &TextQuery::new(text, Mode::Terms),
            &HashSet::from([("codex".into(), id.into())]),
        )
        .unwrap()
}

#[test]
fn slow_success_or_failure_cannot_overwrite_a_later_refresh() {
    for seeded in [false, true] {
        for fail in [false, true] {
            let directory = tempfile::tempdir().unwrap();
            let path = directory.path().join("index.db");
            let mut index = SearchIndex::at(&path).unwrap();
            if seeded {
                update(
                    &mut index,
                    &Reader(|_: &Session| Ok("initialbody".into())),
                    &[session(directory.path(), "same", 0)],
                );
            }
            let (started, wait) = mpsc::sync_channel(1);
            let released = Arc::new((Mutex::new(false), Condvar::new()));
            let release = released.clone();
            let old = session(directory.path(), "same", 1);
            let slow = std::thread::spawn(move || {
                update(
                    &mut index,
                    &Reader(move |_: &Session| {
                        started.send(()).unwrap();
                        let (lock, condition) = &*released;
                        let (_guard, timeout) = condition
                            .wait_timeout_while(
                                lock.lock().unwrap(),
                                Duration::from_secs(5),
                                |done| !*done,
                            )
                            .unwrap();
                        assert!(!timeout.timed_out());
                        if fail {
                            Err("read failed".into())
                        } else {
                            Ok("stalebody".into())
                        }
                    }),
                    &[old],
                )
            });
            wait.recv_timeout(Duration::from_secs(3)).unwrap();
            let mut fresh = SearchIndex::at(&path).unwrap();
            let result = update(
                &mut fresh,
                &Reader(|_: &Session| Ok("freshbody".into())),
                &[session(directory.path(), "same", 2)],
            );
            *release.0.lock().unwrap() = true;
            release.1.notify_all();
            assert_eq!(result.0, 1);
            assert_eq!(slow.join().unwrap().0, 0);
            assert_eq!(search(&fresh, "freshbody", "same").len(), 1);
            assert!(search(&fresh, "stalebody", "same").is_empty());
            for table in ["index_state", "sessions_fts", "sessions_fts_trigram"] {
                assert_eq!(
                    fresh
                        .connection
                        .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r
                            .get::<_, i64>(0))
                        .unwrap(),
                    1
                );
            }
        }
    }
}

#[test]
fn clear_during_read_does_not_restore_deleted_row() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("index.db");
    let mut index = SearchIndex::at(&path).unwrap();
    update(
        &mut index,
        &Reader(|_: &Session| Ok("initialbody".into())),
        &[session(directory.path(), "same", 0)],
    );
    let provider = Reader(|_: &Session| {
        SearchIndex::at(&path)?.clear("codex")?;
        Ok("stalebody".into())
    });
    assert_eq!(
        update(
            &mut index,
            &provider,
            &[session(directory.path(), "same", 1)]
        )
        .0,
        0
    );
    assert!(search(&index, "stalebody", "same").is_empty());
}

#[test]
fn failed_batch_rolls_back_state_and_both_full_text_tables() {
    let directory = tempfile::tempdir().unwrap();
    let mut index = SearchIndex::at(&directory.path().join("index.db")).unwrap();
    index.connection.execute_batch("CREATE TRIGGER reject_bad BEFORE INSERT ON index_state WHEN NEW.session_id = 'bad' BEGIN SELECT RAISE(ABORT, 'test failure'); END;").unwrap();
    let provider = Reader(|_: &Session| Ok("body".into()));
    let result = index.update(
        info(),
        &provider,
        &[
            session(directory.path(), "good", 0),
            session(directory.path(), "bad", 0),
        ],
        false,
        &mut Vec::new(),
    );
    assert!(result.is_err());
    for table in ["index_state", "sessions_fts", "sessions_fts_trigram"] {
        assert_eq!(
            index
                .connection
                .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            0
        );
    }
}

#[test]
fn incremental_reads_retry_failure_keep_scoped_absences_and_expire_unseen_rows() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("index.db");
    let mut index = SearchIndex::at(&path).unwrap();
    let a = session(directory.path(), "a", 0);
    let b = session(directory.path(), "b", 0);
    let provider = Reader(|_: &Session| Ok("body".into()));
    assert_eq!(update(&mut index, &provider, &[a.clone(), b.clone()]).0, 2);
    assert_eq!(
        update(
            &mut index,
            &Reader(|_: &Session| panic!("unchanged source read")),
            &[a]
        )
        .0,
        0
    );
    assert_eq!(search(&index, "body", "b").len(), 1);
    assert_eq!(
        update(
            &mut index,
            &Reader(|_: &Session| Err("transient".into())),
            &[session(directory.path(), "a", 1)]
        )
        .1,
        ["a"]
    );
    assert_eq!(
        update(&mut index, &provider, &[session(directory.path(), "a", 1)]).0,
        1
    );
    index
        .connection
        .execute(
            "UPDATE index_state SET last_seen_at = 0 WHERE session_id = 'b'",
            [],
        )
        .unwrap();
    let index = SearchIndex::at(&path).unwrap();
    assert!(search(&index, "body", "b").is_empty());
    assert_eq!(search(&index, "body", "a").len(), 1);
}
