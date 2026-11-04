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
fn case_variants_sqlite_folds_apart_match_like_the_text_query() {
    let directory = tempfile::tempdir().unwrap();
    let mut index =
        SearchIndex::at(&directory.path().join("index.db")).unwrap();
    let body = "ᲐᲑᲒᲓ ᏣᎳᎩ 𞤀𞤁𞤂";
    let reader = Reader(move |_: &Session| Ok(body.into()));
    update(&mut index, &reader, &[session(directory.path(), "s", 0)]);
    for text in ["აბგდ", "ꮳꮃꭹ", "𞤢𞤣𞤤"] {
        assert!(TextQuery::new(text, Mode::Terms).find(&[body]).is_some());
        assert_eq!(search(&index, text, "s").len(), 1, "{text}");
    }
}
