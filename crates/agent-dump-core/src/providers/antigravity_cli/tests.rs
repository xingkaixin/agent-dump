use super::*;
use proto::tests::{bytes, varint};
use rusqlite::Connection;
use serde_json::json;

const FIXTURE: &str = "
CREATE TABLE steps (idx INTEGER PRIMARY KEY, step_type INTEGER NOT NULL, \
    status INTEGER NOT NULL, step_payload BLOB);
CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB);
INSERT INTO steps VALUES (1, 14, 3, X'9a010412024869');
INSERT INTO steps VALUES (2, 15, 3, X'a201060a04446f6e65');
INSERT INTO steps VALUES (3, 132, 3, \
    X'2a2322210a0663616c6c2d311209726561645f66696c65\
    1a0c7b2270617468223a2261227d');
INSERT INTO steps VALUES (4, 23, 3, X'f20109220741207469746c65');
INSERT INTO steps VALUES (5, 999, 3, X'a00601');
";

fn fixture(base: &Path, id: &str) -> PathBuf {
    std::fs::create_dir_all(base).unwrap();
    let path = base.join(format!("{id}.db"));
    Connection::open(&path)
        .unwrap()
        .execute_batch(FIXTURE)
        .unwrap();
    path
}

fn provider(root: &Path) -> AntigravityCli {
    AntigravityCli {
        roots: SourceRoots::fixed(
            root.to_owned(),
            "conversations",
            root.join("fallback"),
            "Synthetic source",
        ),
    }
}

fn discover(provider: &mut AntigravityCli) -> Discovery {
    provider.discover(Window::All, &mut |_| Ok(())).unwrap()
}

fn read(provider: &AntigravityCli, session: &Session) -> serde_json::Value {
    serde_json::to_value(
        provider.read(session, false, &mut |_| Ok(())).unwrap(),
    )
    .unwrap()
}

#[test]
fn native_steps_keep_order_tools_titles_and_summary_facts() {
    let root = tempfile::tempdir().unwrap();
    fixture(&root.path().join("conversations"), "session");
    let summaries =
        Connection::open(root.path().join("conversation_summaries.db"))
            .unwrap();
    summaries
        .execute_batch(
            "CREATE TABLE conversation_summaries (\
             conversation_id TEXT PRIMARY KEY, title TEXT, \
             workspace_uris TEXT, last_modified_time TEXT, \
             parent_conversation_id TEXT);",
        )
        .unwrap();
    let workspace = root.path().join("agy-fixture");
    summaries
        .execute(
            "INSERT INTO conversation_summaries VALUES \
             ('session', 'Summary title', ?1, \
             '2026-09-02 16:57:28.971105+00:00', '')",
            [json!([
                "not a uri",
                url::Url::from_file_path(&workspace).unwrap().as_str(),
            ])
            .to_string()],
        )
        .unwrap();
    let mut provider = provider(root.path());
    let discovery = discover(&mut provider);
    assert!(discovery.failures.is_empty());
    let [session] = &discovery.sessions[..] else {
        panic!("expected one session")
    };
    assert_eq!(session.id, "session");
    assert_eq!(session.title, "A title");
    assert_eq!(Path::new(&session.directory), workspace);
    assert_eq!(session.message_count, Some(3));
    assert_eq!(
        session.created_at.iso_utc(),
        "2026-09-02T16:57:28.971000+00:00"
    );
    assert_eq!(session.created_at, session.updated_at);
    let data = read(&provider, session);
    let messages = data["messages"].as_array().unwrap();
    assert_eq!(
        messages
            .iter()
            .map(|message| &message["id"])
            .collect::<Vec<_>>(),
        ["session:1", "session:2", "session:3"]
    );
    assert!(
        messages
            .iter()
            .all(|message| message["inferred_time"] == true)
    );
    assert_eq!(
        messages
            .iter()
            .map(|message| &message["role"])
            .collect::<Vec<_>>(),
        ["user", "assistant", "assistant"]
    );
    assert_eq!(messages[1]["agent"], "antigravity-cli");
    let tool = &messages[2]["parts"][0];
    assert_eq!(
        (&tool["tool"], &tool["callID"]),
        (&json!("read_file"), &json!("call-1"))
    );
    assert_eq!(
        tool["state"],
        json!({
            "status": "unknown",
            "input": {"path": "a"},
            "output": null,
            "metadata": {
                "antigravity_step_type": 132,
                "antigravity_status": 3,
            },
        })
    );
    assert_eq!(
        data["stats"],
        json!({
            "total_cost": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "message_count": 3,
        })
    );
    assert_eq!(
        provider
            .find("session", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap()
            .title,
        "A title"
    );
}

#[test]
fn usage_deduplicates_retries_and_attaches_to_the_next_assistant_message() {
    let root = tempfile::tempdir().unwrap();
    let path = fixture(&root.path().join("conversations"), "session");
    let usage = |response: &str, input, cache_read, visible, reasoning| {
        [
            varint(1, 7),
            varint(2, input),
            varint(3, visible + reasoning),
            varint(5, cache_read),
            bytes(7, format!("bot-{response}")),
            varint(9, reasoning),
            varint(10, visible),
            bytes(11, response),
        ]
        .concat()
    };
    let created = |seconds| {
        bytes(1, [varint(1, seconds), varint(2, 500_000_000)].concat())
    };
    let db = Connection::open(&path).unwrap();
    db.execute(
        "INSERT INTO gen_metadata VALUES (0, ?1)",
        [bytes(
            1,
            [varint(3, 7), bytes(19, "gemini-2.5-flash")].concat(),
        )],
    )
    .unwrap();
    for (index, kind, payload) in [
        (
            6,
            15,
            bytes(
                5,
                [
                    created(1_788_000_000),
                    bytes(9, usage("r1", 100, 40, 20, 10)),
                    bytes(28, bytes(2, usage("r0", 50, 0, 5, 0))),
                    bytes(28, bytes(2, usage("r1", 100, 40, 20, 10))),
                ]
                .concat(),
            ),
        ),
        (
            7,
            132,
            bytes(
                5,
                [
                    created(1_788_000_001),
                    bytes(
                        4,
                        [bytes(1, "call-2"), bytes(2, "list_dir")].concat(),
                    ),
                ]
                .concat(),
            ),
        ),
        (
            8,
            15,
            bytes(5, bytes(9, [varint(2, 3), varint(10, 2)].concat())),
        ),
    ] {
        db.execute(
            "INSERT INTO steps VALUES (?1, ?2, 3, ?3)",
            rusqlite::params![index, kind, payload],
        )
        .unwrap();
    }
    let mut provider = provider(root.path());
    let session = discover(&mut provider).sessions.remove(0);
    assert_eq!(session.model, "gemini-2.5-flash");
    assert_eq!(session.message_count, Some(5));
    let data = read(&provider, &session);
    let messages = data["messages"].as_array().unwrap();
    let tool = &messages[3];
    assert_eq!(tool["id"], "session:7");
    assert_eq!(tool["time_created"], 1_788_000_001_500_i64);
    assert!(tool.get("inferred_time").is_none());
    assert_eq!(tool["model"], "gemini-2.5-flash");
    assert_eq!(
        tool["tokens"],
        json!({"input": 190, "output": 25, "reasoning": 10, "cache": {"read": 40, "write": 0}})
    );
    let usage = &messages[4];
    assert_eq!(usage["id"], "session:8:usage");
    assert_eq!(usage["inferred_time"], true);
    assert_eq!(usage["parts"], json!([]));
    assert_eq!(usage["model"], serde_json::Value::Null);
    assert_eq!(usage["tokens"]["output"], 2);
    assert_eq!(
        data["stats"],
        json!({
            "total_cost": 0,
            "total_input_tokens": 193,
            "total_output_tokens": 37,
            "message_count": 5,
            "total_tokens": 230,
        })
    );
    assert_eq!(session.created_at.as_millisecond(), 1_788_000_001_500);
}

#[test]
fn empty_databases_are_skipped_and_invalid_ones_fail_alone() {
    let root = tempfile::tempdir().unwrap();
    let base = root.path().join("conversations");
    fixture(&base, "kept");
    let empty = fixture(&base, "empty");
    Connection::open(&empty)
        .unwrap()
        .execute("DELETE FROM steps", [])
        .unwrap();
    let corrupt = fixture(&base.join("nested"), "corrupt");
    Connection::open(&corrupt)
        .unwrap()
        .execute(
            "UPDATE steps SET step_payload = X'a201ff' WHERE idx = 2",
            [],
        )
        .unwrap();
    let unsupported = base.join("unsupported.db");
    Connection::open(&unsupported)
        .unwrap()
        .execute_batch("CREATE TABLE steps (idx INTEGER)")
        .unwrap();
    let before: Vec<_> = [&empty, &corrupt, &unsupported]
        .iter()
        .map(|path| std::fs::read(path).unwrap())
        .collect();
    let discovery = discover(&mut provider(root.path()));
    assert_eq!(
        discovery
            .sessions
            .iter()
            .map(|session| &session.id)
            .collect::<Vec<_>>(),
        ["kept"]
    );
    let mut failures: Vec<_> = discovery
        .failures
        .iter()
        .map(|failure| (failure.source.clone(), failure.error.to_string()))
        .collect();
    failures.sort();
    assert_eq!(
        failures,
        [
            (
                crate::storage::source_io::path_text(&corrupt),
                "invalid Antigravity CLI step 2: truncated protobuf varint".into()
            ),
            (
                crate::storage::source_io::path_text(&unsupported),
                "unsupported Antigravity CLI database: no such table: gen_metadata".into()
            ),
        ]
    );
    assert_eq!(
        [&empty, &corrupt, &unsupported]
            .iter()
            .map(|path| std::fs::read(path).unwrap())
            .collect::<Vec<_>>(),
        before
    );
}

#[test]
fn source_selection_retries_absence_and_keeps_selected_root() {
    crate::providers::source_tests::source_selection(
        "conversations",
        false,
        |roots| AntigravityCli { roots },
        |base| fixture(base, "kept"),
    );
}
