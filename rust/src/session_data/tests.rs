use super::*;
use crate::provider::{Discovery, Lookup};
use crate::session::Stats;
use jiff::Timestamp;
use std::path::Path;
use std::sync::Barrier;
use std::sync::atomic::{AtomicUsize, Ordering};

struct Reader<F>(F);

impl<F: Fn(&Session) -> crate::Result<SessionData>> Provider for Reader<F> {
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
        (self.0)(session)
    }
    fn source_root(&self) -> &Path {
        Path::new(".")
    }
    fn search_roots(&self) -> crate::Result<crate::provider::SearchRoots> {
        Ok(Vec::new())
    }
}

fn session(root: &Path, id: &str) -> Session {
    Session::new(
        id.into(),
        id.into(),
        root.join(id),
        Timestamp::UNIX_EPOCH,
        Timestamp::UNIX_EPOCH,
    )
}

fn payload(session: &Session) -> SessionData {
    session.payload(Vec::new(), Stats::default())
}

#[test]
fn retained_payloads_are_isolated_and_lru_bounded() {
    let root = tempfile::tempdir().unwrap();
    let reads = Mutex::new(Vec::new());
    let provider = Reader(|session: &Session| {
        reads.lock().unwrap().push(session.id.clone());
        Ok(payload(session))
    });
    let cache = SessionDataCache::new(2);
    for id in ["first", "second", "first", "third", "first", "second"] {
        let mut data = cache
            .get(
                "test",
                &provider,
                &session(root.path(), id),
                false,
                &mut |_| Ok(()),
            )
            .unwrap();
        assert_eq!(data.title, id);
        Arc::make_mut(&mut data).title = "consumer mutation".into();
    }
    assert_eq!(
        *reads.lock().unwrap(),
        ["first", "second", "third", "second"]
    );
    let zero = SessionDataCache::new(0);
    for _ in 0..2 {
        zero.get(
            "test",
            &provider,
            &session(root.path(), "zero"),
            false,
            &mut |_| Ok(()),
        )
        .unwrap();
    }
    assert_eq!(
        reads
            .lock()
            .unwrap()
            .iter()
            .filter(|id| *id == "zero")
            .count(),
        2
    );
}

#[test]
fn concurrent_leases_coalesce_isolate_and_release_payloads() {
    let root = tempfile::tempdir().unwrap();
    let session = session(root.path(), "shared");
    let reads = AtomicUsize::new(0);
    let provider = Reader(|session: &Session| {
        reads.fetch_add(1, Ordering::SeqCst);
        Ok(payload(session))
    });
    let cache = SessionDataCache::default();
    let ready = Barrier::new(4);
    std::thread::scope(|scope| {
        for index in 0..4 {
            let (provider, session, cache, ready) = (&provider, &session, &cache, &ready);
            scope.spawn(move || {
                let mut lease = cache
                    .lease("test", provider, session, false, &mut |_| Ok(()))
                    .unwrap();
                ready.wait();
                assert_eq!(lease.title, "shared");
                lease.title = index.to_string();
                ready.wait();
                assert_eq!(lease.title, index.to_string());
            });
        }
    });
    assert_eq!(reads.load(Ordering::SeqCst), 1);
    cache
        .lease("test", &provider, &session, false, &mut |_| Ok(()))
        .unwrap();
    assert_eq!(reads.load(Ordering::SeqCst), 2);
}

#[test]
fn transient_large_payloads_are_released_and_get_promotes_a_lease() {
    let root = tempfile::tempdir().unwrap();
    let provider = Reader(|session: &Session| {
        let mut data = payload(session);
        data.extra
            .insert("large".into(), "x".repeat(256 * 1024).into());
        Ok(data)
    });
    let cache = SessionDataCache::default();
    let mut references = Vec::new();
    for index in 0..100 {
        let lease = cache
            .lease(
                "test",
                &provider,
                &session(root.path(), &index.to_string()),
                false,
                &mut |_| Ok(()),
            )
            .unwrap();
        references.push(Arc::downgrade(&lease.data));
    }
    assert!(references.iter().all(|data| data.upgrade().is_none()));
    let session = session(root.path(), "retained");
    let lease = cache
        .lease("test", &provider, &session, false, &mut |_| Ok(()))
        .unwrap();
    let retained = cache
        .get("test", &provider, &session, false, &mut |_| Ok(()))
        .unwrap();
    assert!(Arc::ptr_eq(&lease.data, &retained));
    drop(lease);
    let again = cache
        .get("test", &provider, &session, false, &mut |_| Ok(()))
        .unwrap();
    assert!(Arc::ptr_eq(&retained, &again));
}

#[test]
fn leased_entries_survive_eviction_and_detached_leases_preserve_new_generation() {
    let root = tempfile::tempdir().unwrap();
    let reads = AtomicUsize::new(0);
    let provider = Reader(|session: &Session| {
        reads.fetch_add(1, Ordering::SeqCst);
        Ok(payload(session))
    });
    let cache = SessionDataCache::new(1);
    let mut session = session(root.path(), "held");
    let old = cache
        .lease("test", &provider, &session, false, &mut |_| Ok(()))
        .unwrap();
    for id in ["second", "third"] {
        let other = super::tests::session(root.path(), id);
        cache
            .get("test", &provider, &other, false, &mut |_| Ok(()))
            .unwrap();
    }
    cache
        .get("test", &provider, &session, false, &mut |_| Ok(()))
        .unwrap();
    assert_eq!(reads.load(Ordering::SeqCst), 3);
    session.title = "renamed".into();
    let new = cache
        .get("test", &provider, &session, false, &mut |_| Ok(()))
        .unwrap();
    drop(old);
    let again = cache
        .get("test", &provider, &session, false, &mut |_| Ok(()))
        .unwrap();
    assert!(Arc::ptr_eq(&new, &again));
    assert_eq!(reads.load(Ordering::SeqCst), 4);
}

#[test]
fn source_and_session_signals_invalidate_cached_payloads() {
    let root = tempfile::tempdir().unwrap();
    let reads = AtomicUsize::new(0);
    let provider = Reader(|session: &Session| {
        reads.fetch_add(1, Ordering::SeqCst);
        Ok(payload(session))
    });
    let cache = SessionDataCache::default();
    let mut session = session(root.path(), "source");
    for step in 0..6 {
        match step {
            1 => std::fs::write(&session.source_path, "first").unwrap(),
            2 => std::fs::write(&session.source_path, "longer replacement").unwrap(),
            3 => std::fs::remove_file(&session.source_path).unwrap(),
            4 => session.title = "new title".into(),
            5 => session.updated_at = Timestamp::from_microsecond(1).unwrap(),
            _ => {}
        }
        let first = cache
            .get("test", &provider, &session, false, &mut |_| Ok(()))
            .unwrap();
        let second = cache
            .get("test", &provider, &session, false, &mut |_| Ok(()))
            .unwrap();
        assert!(Arc::ptr_eq(&first, &second));
    }
    assert_eq!(reads.load(Ordering::SeqCst), 6);
    cache
        .get("another provider", &provider, &session, false, &mut |_| {
            Ok(())
        })
        .unwrap();
    assert_eq!(reads.load(Ordering::SeqCst), 7);
}

#[test]
fn inflight_reads_survive_eviction_and_stale_requests_wait_for_reload() {
    let root = tempfile::tempdir().unwrap();
    let first = session(root.path(), "source");
    let mut changed = first.clone();
    changed.title = "changed".into();
    let active = AtomicUsize::new(0);
    let started = Barrier::new(2);
    let release = Barrier::new(2);
    let provider = Reader(|session: &Session| {
        if session.id == "source" {
            assert_eq!(active.fetch_add(1, Ordering::SeqCst), 0);
            if session.title == "source" {
                started.wait();
                release.wait();
            }
            active.fetch_sub(1, Ordering::SeqCst);
        }
        Ok(payload(session))
    });
    let cache = SessionDataCache::new(1);
    std::thread::scope(|scope| {
        let original = scope.spawn(|| {
            cache
                .get("test", &provider, &first, false, &mut |_| Ok(()))
                .unwrap()
        });
        started.wait();
        for id in ["second", "third"] {
            cache
                .get(
                    "test",
                    &provider,
                    &session(root.path(), id),
                    false,
                    &mut |_| Ok(()),
                )
                .unwrap();
        }
        let updated = scope.spawn(|| {
            cache
                .get("test", &provider, &changed, false, &mut |_| Ok(()))
                .unwrap()
        });
        release.wait();
        assert_eq!(original.join().unwrap().title, "source");
        assert_eq!(updated.join().unwrap().title, "changed");
    });
}

#[test]
fn failed_reads_retry_and_preserve_localized_error_identity() {
    let root = tempfile::tempdir().unwrap();
    let reads = AtomicUsize::new(0);
    let provider = Reader(|session: &Session| {
        if reads.fetch_add(1, Ordering::SeqCst) == 0 {
            return Err(
                crate::provider_error::ProviderError::Message(["unavailable", "不可用"]).into(),
            );
        }
        Ok(payload(session))
    });
    let session = session(root.path(), "retry");
    let cache = SessionDataCache::default();
    let error = cache
        .get("test", &provider, &session, false, &mut |_| Ok(()))
        .err()
        .unwrap();
    assert_eq!(
        crate::provider_error::operation_message(error.as_ref(), true),
        "ValueError: 不可用"
    );
    assert_eq!(
        cache
            .get("test", &provider, &session, false, &mut |_| Ok(()))
            .unwrap()
            .title,
        "retry"
    );
    assert_eq!(reads.load(Ordering::SeqCst), 2);
}

#[test]
fn panicking_reader_does_not_poison_cache_or_prevent_retry() {
    let root = tempfile::tempdir().unwrap();
    let reads = AtomicUsize::new(0);
    let provider = Reader(|session: &Session| {
        assert_ne!(reads.fetch_add(1, Ordering::SeqCst), 0, "reader panic");
        Ok(payload(session))
    });
    let session = session(root.path(), "retry");
    let cache = SessionDataCache::default();
    assert!(
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| cache.get(
            "test",
            &provider,
            &session,
            false,
            &mut |_| Ok(())
        )))
        .is_err()
    );
    assert_eq!(
        cache
            .get("test", &provider, &session, false, &mut |_| Ok(()))
            .unwrap()
            .title,
        "retry"
    );
}

#[test]
fn provider_change_sources_include_payload_files_and_wal_only() {
    let root = tempfile::tempdir().unwrap();
    let mut session = session(root.path(), "source");
    for registration in crate::registry::all() {
        let provider = (registration.open)().unwrap();
        if registration.info.name == "kimi" {
            session.source_path = root.path().join("kimi");
            std::fs::create_dir(&session.source_path).unwrap();
            std::fs::write(session.source_path.join("metadata.json"), "{}").unwrap();
            assert!(provider.change_sources(&session).is_empty());
            std::fs::write(session.source_path.join("wire.jsonl"), "").unwrap();
            let wire_signal = SessionSignal::new(provider.as_ref(), &session);
            std::fs::write(session.source_path.join("context.jsonl"), "").unwrap();
            assert_ne!(wire_signal, SessionSignal::new(provider.as_ref(), &session));
            assert_eq!(
                provider.change_sources(&session),
                [
                    session.source_path.join("context.jsonl"),
                    session.source_path.join("wire.jsonl")
                ]
            );
        } else {
            session.source_path = root.path().join("source");
            let expected = match registration.info.name {
                "codex" | "claudecode" | "pi" => vec![session.source_path.clone()],
                _ => vec![session.source_path.clone(), root.path().join("source-wal")],
            };
            assert_eq!(
                provider.change_sources(&session),
                expected,
                "{}",
                registration.info.name
            );
        }
    }
}

#[test]
fn sqlite_wal_updates_invalidate_without_changing_database_bytes() {
    let root = tempfile::tempdir().unwrap();
    let session = session(root.path(), "source");
    let connection = rusqlite::Connection::open(&session.source_path).unwrap();
    connection
        .execute_batch(
            "PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0;
        CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, data TEXT);
        CREATE TABLE part (id TEXT, message_id TEXT, time_created INTEGER, data TEXT);
        INSERT INTO message VALUES ('message','source',0,'{\"role\":\"user\"}');
        INSERT INTO part VALUES ('part','message',0,'{\"type\":\"text\",\"text\":\"First\"}');",
        )
        .unwrap();
    let before = std::fs::read(&session.source_path).unwrap();
    let provider =
        crate::sqlite_provider::SqliteProvider::open(crate::sqlite_provider::Kind::OpenCode)
            .unwrap();
    let cache = SessionDataCache::default();
    let first = cache
        .get("opencode", &provider, &session, false, &mut |_| Ok(()))
        .unwrap();
    assert_eq!(
        serde_json::to_value(first.as_ref()).unwrap()["messages"][0]["parts"][0]["text"],
        "First"
    );
    connection
        .execute(
            "UPDATE part SET data = ?",
            ["{\"type\":\"text\",\"text\":\"Second\"}"],
        )
        .unwrap();
    let wal_path = root.path().join("source-wal");
    let wal = std::fs::read(&wal_path).unwrap();
    let second = cache
        .get("opencode", &provider, &session, false, &mut |_| Ok(()))
        .unwrap();
    assert_eq!(
        serde_json::to_value(second.as_ref()).unwrap()["messages"][0]["parts"][0]["text"],
        "Second"
    );
    assert_eq!(std::fs::read(&session.source_path).unwrap(), before);
    assert_eq!(std::fs::read(wal_path).unwrap(), wal);
    connection
        .execute_batch("PRAGMA wal_checkpoint(TRUNCATE)")
        .unwrap();
    let third = cache
        .get("opencode", &provider, &session, false, &mut |_| Ok(()))
        .unwrap();
    assert!(!Arc::ptr_eq(&second, &third));
    assert_eq!(
        serde_json::to_value(second.as_ref()).unwrap(),
        serde_json::to_value(third.as_ref()).unwrap()
    );
}
