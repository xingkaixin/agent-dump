use super::*;
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
        profiles: Box::new(|| Ok(None)),
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

fn varint(number: u32, value: u64) -> Vec<u8> {
    let mut bytes = encode(u64::from(number) << 3);
    bytes.extend(encode(value));
    bytes
}

fn bytes(number: u32, value: impl AsRef<[u8]>) -> Vec<u8> {
    let value = value.as_ref();
    let mut bytes = encode(u64::from(number) << 3 | 2);
    bytes.extend(encode(u64::try_from(value.len()).unwrap()));
    bytes.extend(value);
    bytes
}

fn encode(mut value: u64) -> Vec<u8> {
    let mut bytes = Vec::new();
    while value >= 0x80 {
        bytes.push(u8::try_from(value & 0x7f).unwrap() | 0x80);
        value >>= 7;
    }
    bytes.push(u8::try_from(value).unwrap());
    bytes
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
fn step_model_fallback_does_not_guess_retry_models() {
    let root = tempfile::tempdir().unwrap();
    let path = fixture(&root.path().join("conversations"), "session");
    let db = Connection::open(&path).unwrap();
    db.execute("DELETE FROM steps", []).unwrap();
    db.execute(
        "INSERT INTO gen_metadata VALUES (0, ?1)",
        [bytes(1, [varint(3, 7), bytes(19, "mapped-model")].concat())],
    )
    .unwrap();
    let cases = [
        (Some(7), false, "api-model", Some("mapped-model")),
        (None, false, "api-model", Some("api-model")),
        (None, false, "", Some("display-model")),
        (Some(99), false, "api-model", None),
        (None, true, "api-model", None),
    ];
    for (index, (model_id, retry, api_name, _)) in cases.iter().enumerate() {
        let mut usage = varint(2, 1);
        if let Some(id) = model_id {
            usage.extend(varint(1, *id));
        }
        let usage = if *retry {
            bytes(28, bytes(2, usage))
        } else {
            bytes(9, usage)
        };
        let metadata = [
            usage,
            bytes(
                24,
                [bytes(8, "display-model"), bytes(12, api_name)].concat(),
            ),
        ]
        .concat();
        db.execute(
            "INSERT INTO steps VALUES (?1, 15, 3, ?2)",
            rusqlite::params![
                i64::try_from(index).unwrap(),
                [bytes(5, metadata), bytes(20, bytes(1, "Answer"))].concat()
            ],
        )
        .unwrap();
    }
    let mut provider = provider(root.path());
    let session = discover(&mut provider).sessions.remove(0);
    assert_eq!(session.model, "display-model");
    let data = read(&provider, &session);
    for (message, (_, _, _, expected)) in
        data["messages"].as_array().unwrap().iter().zip(cases)
    {
        assert_eq!(message["model"], json!(expected));
    }
    assert_eq!(data["stats"]["total_input_tokens"], 5);
}

#[test]
fn multi_workspace_selection_resolves_context_command_history_and_parent() {
    let root = tempfile::tempdir().unwrap();
    let conversations = root.path().join("conversations");
    std::fs::create_dir_all(&conversations).unwrap();
    let aux_dir = root.path().join("aux-space");
    let project_dir = root.path().join("proj-space");
    let unrelated_dir = root.path().join("other-space");
    let aux_uri = url::Url::from_file_path(&aux_dir).unwrap();
    let project_uri = url::Url::from_file_path(&project_dir).unwrap();
    let workspaces_json =
        json!([aux_uri.as_str(), project_uri.as_str()]).to_string();

    let summaries =
        Connection::open(root.path().join("conversation_summaries.db"))
            .unwrap();
    summaries
        .execute_batch(
            "CREATE TABLE conversation_summaries (\
             conversation_id TEXT PRIMARY KEY, title TEXT, \
             workspace_uris TEXT, last_modified_time TEXT, \
             parent_conversation_id TEXT, agent_name TEXT);",
        )
        .unwrap();

    let create_session =
        |id: &str, parent: &str, steps: Vec<(i64, Vec<u8>)>| {
            let db_path = conversations.join(format!("{id}.db"));
            let db = Connection::open(&db_path).unwrap();
            db.execute_batch(
                "CREATE TABLE steps (idx INTEGER PRIMARY KEY, \
             step_type INTEGER NOT NULL, status INTEGER NOT NULL, \
             step_payload BLOB, error_details BLOB); \
             CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB);",
            )
            .unwrap();
            for (idx, payload) in steps {
                let kind = if idx == 0 { 14 } else { 132 };
                db.execute(
                    "INSERT INTO steps (idx,step_type,status,step_payload) \
                 VALUES (?1,?2,3,?3)",
                    rusqlite::params![idx, kind, payload],
                )
                .unwrap();
            }
            summaries
                .execute(
                    "INSERT INTO conversation_summaries \
                 (conversation_id,title,workspace_uris,last_modified_time,\
                 parent_conversation_id) VALUES \
                 (?1,'',?2,'2026-09-02 16:57:28.971105+00:00',?3)",
                    [id, &workspaces_json, parent],
                )
                .unwrap();
            db_path
        };

    let file_ctx_uri =
        url::Url::from_file_path(project_dir.join("src/main.rs")).unwrap();
    let user_items_prompt = bytes(
        19,
        [
            bytes(2, ""),
            bytes(3, bytes(1, "Check ")),
            bytes(
                3,
                [
                    bytes(1, "@main.rs"),
                    bytes(2, bytes(1, bytes(5, file_ctx_uri.as_str()))),
                ]
                .concat(),
            ),
        ]
        .concat(),
    );
    create_session("ctx-session", "", vec![(0, user_items_prompt)]);

    let cmd_input =
        json!({"command": format!("cd {} && cargo test", project_dir.display())})
            .to_string();
    create_session(
        "cmd-session",
        "",
        vec![
            (0, bytes(19, bytes(2, "Run tests"))),
            (
                1,
                bytes(
                    5,
                    bytes(
                        4,
                        [
                            bytes(1, "call-cmd"),
                            bytes(2, "run_command"),
                            bytes(3, cmd_input),
                        ]
                        .concat(),
                    ),
                ),
            ),
        ],
    );

    let parent_tool =
        json!({"path": project_dir.join("Cargo.toml")}).to_string();
    create_session(
        "parent-z",
        "",
        vec![
            (0, bytes(19, bytes(2, "Parent"))),
            (
                1,
                bytes(
                    5,
                    bytes(
                        4,
                        [
                            bytes(1, "call-parent"),
                            bytes(2, "read_file"),
                            bytes(3, parent_tool),
                        ]
                        .concat(),
                    ),
                ),
            ),
        ],
    );

    let unrelated_tool =
        json!({"path": unrelated_dir.join("notes.md")}).to_string();
    let child_db = create_session(
        "child-a",
        "parent-z",
        vec![
            (0, bytes(19, bytes(2, "Child"))),
            (
                1,
                bytes(
                    5,
                    bytes(
                        4,
                        [
                            bytes(1, "call-child"),
                            bytes(2, "read_file"),
                            bytes(3, unrelated_tool),
                        ]
                        .concat(),
                    ),
                ),
            ),
        ],
    );

    create_session("cycle-a", "cycle-b", vec![(0, bytes(19, bytes(2, "A")))]);
    create_session("cycle-b", "cycle-a", vec![(0, bytes(19, bytes(2, "B")))]);
    create_session("greeting", "", vec![(0, bytes(19, bytes(2, "Hello")))]);

    let mut prov = provider(root.path());
    let sessions = discover(&mut prov).sessions;
    let dir_of = |sessions: &[Session], id: &str| {
        sessions
            .iter()
            .find(|session| session.id == id)
            .unwrap()
            .directory
            .clone()
    };
    let title_of = |sessions: &[Session], id: &str| {
        sessions
            .iter()
            .find(|session| session.id == id)
            .unwrap()
            .title
            .clone()
    };
    let project_str = crate::storage::source_io::path_text(&project_dir);
    let aux_str = crate::storage::source_io::path_text(&aux_dir);

    assert_eq!(dir_of(&sessions, "ctx-session"), project_str);
    assert_eq!(title_of(&sessions, "ctx-session"), "Check @main.rs");
    assert_eq!(dir_of(&sessions, "cmd-session"), project_str);
    assert_eq!(dir_of(&sessions, "parent-z"), project_str);
    assert_eq!(dir_of(&sessions, "child-a"), project_str);
    assert_eq!(dir_of(&sessions, "cycle-a"), aux_str);
    assert_eq!(dir_of(&sessions, "greeting"), aux_str);

    let looked_up = prov
        .find("child-a", &mut |_| Ok(()))
        .unwrap()
        .session
        .unwrap();
    assert_eq!(looked_up.directory, project_str);

    let history_path = root.path().join("history.jsonl");
    let history_lines = format!(
        "{{invalid-json\n{{\"workspace\":\"{}\"}}\n{}\n",
        project_dir.display(),
        json!({"conversationId": "greeting", "workspace": project_str}),
    );
    std::fs::write(&history_path, history_lines).unwrap();
    let refreshed = discover(&mut prov).sessions;
    assert_eq!(dir_of(&refreshed, "greeting"), project_str);
    assert!(
        !prov
            .change_sources(&Session::new(
                "greeting".into(),
                "Hello".into(),
                child_db,
                Timestamp::from_microsecond(0).unwrap(),
                Timestamp::from_microsecond(0).unwrap(),
            ))
            .contains(&history_path)
    );
}

#[test]
fn tool_outputs_explicit_errors_child_titles_and_swarm_subagent() {
    let root = tempfile::tempdir().unwrap();
    let conversations = root.path().join("conversations");
    let path = fixture(&conversations, "session");
    let db = Connection::open(&path).unwrap();
    db.execute_batch(
        "DROP TABLE steps;
         CREATE TABLE steps (idx INTEGER PRIMARY KEY, \
         step_type INTEGER NOT NULL, status INTEGER NOT NULL, \
         step_payload BLOB, error_details BLOB);",
    )
    .unwrap();
    let cases = [
        (
            132,
            "read_file",
            bytes(140, bytes(2, bytes(1, "10: const x = 1;"))),
            "10: const x = 1;",
        ),
        (
            8,
            "view_file",
            bytes(14, bytes(4, "const pattern = /\\n/;")),
            "const pattern = /\\n/;",
        ),
        (
            21,
            "run_command",
            bytes(28, [varint(6, 0), bytes(21, bytes(1, "done\r\n"))].concat()),
            "done",
        ),
        (
            38,
            "call_mcp_tool",
            bytes(47, bytes(3, r#"{"width":728}"#)),
            r#"{"width":728}"#,
        ),
    ];
    for (index, (kind, name, result, _)) in cases.iter().enumerate() {
        let call = bytes(
            5,
            bytes(
                4,
                [bytes(1, format!("call-{index}")), bytes(2, name)].concat(),
            ),
        );
        db.execute(
            "INSERT INTO steps (idx,step_type,status,step_payload) \
             VALUES (?1,?2,3,?3)",
            rusqlite::params![
                i64::try_from(index).unwrap(),
                kind,
                [call, result.clone()].concat()
            ],
        )
        .unwrap();
    }
    let dedup_err = [
        bytes(2, "invalid line range"),
        bytes(3, "invalid line range"),
    ]
    .concat();
    let joined_err =
        [bytes(2, "Permission denied"), bytes(3, "outside workspace")].concat();
    for (offset, (col_err, payload_err)) in
        [(Some(&dedup_err), None), (None, Some(&joined_err))]
            .into_iter()
            .enumerate()
    {
        let idx = i64::try_from(cases.len() + offset).unwrap();
        let mut payload = [
            bytes(
                5,
                bytes(
                    4,
                    [bytes(1, format!("err-{offset}")), bytes(2, "read_file")]
                        .concat(),
                ),
            ),
            bytes(140, bytes(2, bytes(1, "partial output"))),
        ]
        .concat();
        if let Some(err) = payload_err {
            payload.extend(bytes(31, err));
        }
        db.execute(
            "INSERT INTO steps (idx,step_type,status,step_payload,error_details) \
             VALUES (?1,132,7,?2,?3)",
            rusqlite::params![idx, payload, col_err],
        )
        .unwrap();
    }
    let swarm_idx = i64::try_from(cases.len() + 2).unwrap();
    let swarm_payload = [
        bytes(
            5,
            bytes(
                4,
                [
                    bytes(1, "call-swarm"),
                    bytes(2, "swarm"),
                    bytes(
                        3,
                        r#"{"action":"add","name":"worker","brief":"Check"}"#,
                    ),
                ]
                .concat(),
            ),
        ),
        bytes(
            140,
            bytes(
                2,
                bytes(
                    1,
                    "Created At: 2026-11-14T10:00:00+08:00\n\
                     Completed At: 2026-11-14T10:00:01+08:00\n\
                     {\"status\":\"added\",\"name\":\"worker\",\
                     \"conversation_id\":\"child-id\"}",
                ),
            ),
        ),
    ]
    .concat();
    db.execute(
        "INSERT INTO steps (idx,step_type,status,step_payload) \
         VALUES (?1,132,3,?2)",
        rusqlite::params![swarm_idx, swarm_payload],
    )
    .unwrap();

    let summaries =
        Connection::open(root.path().join("conversation_summaries.db"))
            .unwrap();
    summaries
        .execute_batch(
            "CREATE TABLE conversation_summaries (\
             conversation_id TEXT PRIMARY KEY, title TEXT, \
             workspace_uris TEXT, last_modified_time TEXT, \
             parent_conversation_id TEXT, agent_name TEXT); \
             INSERT INTO conversation_summaries VALUES \
             ('session','','[]','2026-09-02 16:57:28.971105+00:00',\
             '','worker');",
        )
        .unwrap();

    let mut prov = provider(root.path());
    let session = discover(&mut prov).sessions.remove(0);
    assert_eq!(session.title, "Untitled Session");
    let data = read(&prov, &session);
    let messages = data["messages"].as_array().unwrap();
    for (message, (_, name, _, expected)) in messages.iter().zip(&cases) {
        let part = &message["parts"][0];
        assert_eq!(part["tool"], *name);
        assert_eq!(part["state"]["status"], "unknown");
        assert_eq!(part["state"]["output"], *expected);
        assert!(part["state"].get("error").is_none());
    }
    let err_col_part = &messages[cases.len()]["parts"][0];
    assert_eq!(err_col_part["state"]["status"], "error");
    assert_eq!(err_col_part["state"]["output"], "partial output");
    assert_eq!(err_col_part["state"]["error"], "invalid line range");

    let err_tag_part = &messages[cases.len() + 1]["parts"][0];
    assert_eq!(err_tag_part["state"]["status"], "error");
    assert_eq!(
        err_tag_part["state"]["error"],
        "Permission denied\noutside workspace"
    );

    let swarm_message = &messages[cases.len() + 2];
    assert_eq!(swarm_message["subagent_id"], "child-id");

    summaries
        .execute(
            "UPDATE conversation_summaries SET parent_conversation_id='parent'",
            [],
        )
        .unwrap();
    assert_eq!(discover(&mut prov).sessions[0].title, "worker");

    summaries
        .execute(
            "UPDATE conversation_summaries SET title='Summary title'",
            [],
        )
        .unwrap();
    assert_eq!(discover(&mut prov).sessions[0].title, "Summary title");

    let mut failed_swarm = swarm_payload;
    failed_swarm.extend(bytes(31, bytes(2, "swarm failed")));
    db.execute(
        "INSERT INTO steps (idx,step_type,status,step_payload) \
         VALUES (?1,132,7,?2)",
        rusqlite::params![swarm_idx + 1, failed_swarm],
    )
    .unwrap();
    let session = discover(&mut prov).sessions.remove(0);
    let updated = read(&prov, &session);
    let failed_msg = updated["messages"].as_array().unwrap().last().unwrap();
    assert!(failed_msg.get("subagent_id").is_none());

    let broken = fixture(&conversations, "broken");
    Connection::open(&broken)
        .unwrap()
        .execute_batch(
            "DROP TABLE steps;
             CREATE TABLE steps (idx INTEGER PRIMARY KEY, \
             step_type INTEGER NOT NULL, status INTEGER NOT NULL, \
             step_payload BLOB, error_details BLOB);
             INSERT INTO steps VALUES (0, 132, 7, X'2a00', X'ffff');",
        )
        .unwrap();
    let result = discover(&mut prov);
    assert_eq!(result.sessions.len(), 1);
    assert_eq!(result.failures.len(), 1);
}
