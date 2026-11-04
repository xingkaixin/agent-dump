use super::*;
use crate::providers::contract::{Discovery, Lookup, Window};
use crate::session::Stats;
use crate::session::timestamp::Timestamp;
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};

struct Reader<F>(F);

impl<F: Fn(&Session) -> crate::Result<SessionData> + Send + Sync> Provider
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
        (self.0)(session)
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
            2 => std::fs::write(&session.source_path, "longer replacement")
                .unwrap(),
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
