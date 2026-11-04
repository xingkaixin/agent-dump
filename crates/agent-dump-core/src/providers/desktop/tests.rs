use super::*;
use crate::output::diagnostics::Diagnostic;

fn fixture(kind: Kind) -> (tempfile::TempDir, Desktop, Session, &'static str) {
    let directory = tempfile::tempdir().unwrap();
    let database = directory.path().join("source.sqlite");
    let connection = Connection::open(&database).unwrap();
    let (sql, id, table) = match kind {
        Kind::DeepChat => (
            "CREATE TABLE new_sessions (id TEXT, title TEXT, created_at INTEGER,
              updated_at INTEGER, project_dir TEXT, agent_id TEXT,
              parent_session_id TEXT, session_kind TEXT, is_draft INTEGER);
             CREATE TABLE deepchat_sessions (id TEXT, model_id TEXT, provider_id TEXT);
             CREATE TABLE deepchat_messages (id TEXT, session_id TEXT,
               order_seq INTEGER, role TEXT, content TEXT, status TEXT,
               metadata TEXT, created_at INTEGER, updated_at INTEGER);
             INSERT INTO new_sessions VALUES ('kept', 'Kept', 1768478400000,
               1768478400000, '/project', NULL, NULL, 'conversation', 0);
             INSERT INTO deepchat_messages VALUES ('kept-user', 'kept', 1,
               'user', '{\"text\":\"Prompt\"}', 'sent', '{}', 1768478400000,
               1768478400000);",
            "kept",
            "new_sessions",
        ),
        Kind::Cherry => (
            "CREATE TABLE topic (id TEXT, name TEXT, created_at INTEGER,
              updated_at INTEGER, active_node_id TEXT, deleted_at INTEGER);
             CREATE TABLE message (id TEXT);
             CREATE TABLE agent_workspace (id TEXT, path TEXT);
             CREATE TABLE agent_session (id TEXT, name TEXT, created_at INTEGER,
               updated_at INTEGER, workspace_id TEXT);
             CREATE TABLE agent_session_message (id TEXT, session_id TEXT,
               role TEXT, data TEXT, model_id TEXT, message_snapshot TEXT,
               created_at INTEGER);
             INSERT INTO agent_session VALUES ('kept', 'Kept', 1768478400000, 1768478400000, NULL);
             INSERT INTO agent_session_message VALUES ('kept-user', 'kept',
               'user', '{\"parts\":[{\"type\":\"text\",\"text\":\"Prompt\"}]}',
               NULL, NULL, 1768478400000);",
            "session-kept",
            "agent_session",
        ),
        Kind::MiniMax => (
            "CREATE TABLE local_runtime_sessions (session_id TEXT,
              columnar_version INTEGER, runtime TEXT, visibility TEXT,
              session_kind TEXT, archived INTEGER, title TEXT,
              workspace_dir TEXT, parent_session_id TEXT, created_at_ms INTEGER,
              updated_at_ms INTEGER, extra_data_json TEXT);
             CREATE TABLE local_runtime_message_rows (id INTEGER,
               session_id TEXT, msg_id TEXT, role TEXT, turn_id TEXT,
               source TEXT, created_at_ms INTEGER, data_json TEXT);
             CREATE TABLE local_runtime_messages (session_id TEXT, display_messages_json TEXT);
             CREATE TABLE local_runtime_message_row_migrations (session_id TEXT);
             INSERT INTO local_runtime_sessions VALUES ('kept', 3, 'pi-agent',
               'visible', 'conversation', 0, 'Kept', '/project', NULL,
               1768478400000, 1768478400000, '{}');
             INSERT INTO local_runtime_message_rows VALUES (1, 'kept',
               'kept-user', 'user', 'turn', 'agent', 1768478400000,
               '{\"msg_id\":\"kept-user\",\"role\":\"user\",
               \"msg_content\":\"Prompt\"}');",
            "kept",
            "local_runtime_sessions",
        ),
    };
    connection.execute_batch(sql).unwrap();
    drop(connection);
    let mut provider = Desktop {
        kind,
        search_roots: Box::new({
            let database = database.clone();
            move || Ok(vec![("Synthetic source", database.clone())])
        }),
        database,
    };
    let session = provider.find(id, &mut |_| Ok(())).unwrap().session.unwrap();
    (directory, provider, session, table)
}

#[test]
fn session_removed_after_lookup_is_not_exported_as_empty_content() {
    for kind in [Kind::DeepChat, Kind::Cherry, Kind::MiniMax] {
        let (_directory, provider, session, table) = fixture(kind);
        Connection::open(&session.source_path)
            .unwrap()
            .execute_batch(&format!("DELETE FROM {table}"))
            .unwrap();
        let before = std::fs::read(&session.source_path).unwrap();
        let error = provider
            .read(&session, false, &mut |_| Ok(()))
            .err()
            .unwrap();
        let diagnostic =
            Diagnostic::read_failed(error.as_ref(), Vec::new(), false)
                .render(false);
        assert!(diagnostic.contains(&format!(
            "  - missing path: {}\n  - session id: {}\n",
            session.source_path.display(),
            session.id
        )));
        assert_eq!(std::fs::read(&session.source_path).unwrap(), before);
    }
}

#[test]
fn minimax_turn_usage_is_counted_once() {
    let (_directory, mut provider, _, _) = fixture(Kind::MiniMax);
    Connection::open(&provider.database)
        .unwrap()
        .execute_batch(
            r#"CREATE TABLE local_runtime_token_usage (id INTEGER,
              session_id TEXT, turn_id TEXT, model TEXT, ts INTEGER,
              input_tokens INTEGER, output_tokens INTEGER,
              reasoning_tokens INTEGER, cache_read_tokens INTEGER,
              cache_write_tokens INTEGER, cost_usd REAL);
            INSERT INTO local_runtime_message_rows VALUES
              (2, 'kept', 'a1', 'assistant', 'turn', 'agent', 2,
                '{"msg_id":"a1","role":"assistant","msg_content":"Draft"}'),
              (3, 'kept', 'a2', 'assistant', 'turn', 'agent', 3,
                '{"msg_id":"a2","role":"assistant","msg_content":"Done",
                "usage":{"input_tokens":99}}'),
              (4, 'kept', 'a3', 'assistant', 'multi', 'agent', 4,
                '{"msg_id":"a3","role":"assistant","msg_content":"Mixed"}');
            INSERT INTO local_runtime_token_usage VALUES
              (1, 'kept', 'turn', 'm', 10, 100, 20, 5, 40, 10, 0.025),
              (2, 'kept', 'turn', 'm', 11, 50, 10, 0, 0, 0, NULL),
              (3, 'kept', 'multi', 'a', 12, 1, 1, 0, 0, 0, 0),
              (4, 'kept', 'multi', 'b', 13, 1, 1, 0, 0, 0, 0);"#,
        )
        .unwrap();
    let data = read_json(&mut provider, "kept");
    let messages = data["messages"].as_array().unwrap();
    assert!(messages[1]["tokens"].as_object().unwrap().is_empty());
    assert_eq!(
        messages[2]["tokens"],
        serde_json::json!({
            "input": 150,
            "output": 30,
            "reasoning": 5,
            "cache": {"read": 40, "write": 10}
        })
    );
    assert!(messages[3]["tokens"].as_object().unwrap().is_empty());
    assert_eq!(
        (
            &data["stats"]["total_input_tokens"],
            &data["stats"]["total_output_tokens"],
            &data["stats"]["total_cost"]
        ),
        (&152.into(), &32.into(), &0.025.into())
    );
}

fn read_json(provider: &mut Desktop, id: &str) -> serde_json::Value {
    let session = provider.find(id, &mut |_| Ok(())).unwrap().session.unwrap();
    serde_json::to_value(
        provider.read(&session, false, &mut |_| Ok(())).unwrap(),
    )
    .unwrap()
}

#[test]
fn deepchat_usage_rows_replace_message_metadata_usage() {
    let (_directory, mut provider, _, _) = fixture(Kind::DeepChat);
    Connection::open(&provider.database)
        .unwrap()
        .execute_batch(
            r#"CREATE TABLE deepchat_assistant_blocks (message_id TEXT,
              block_index INTEGER, block_type TEXT, status TEXT,
              text_content TEXT, tool_call_id TEXT, tool_name TEXT,
              tool_params TEXT, tool_response TEXT, action_type TEXT,
              image_mime_type TEXT, extra_json TEXT, updated_at INTEGER);
            CREATE TABLE deepchat_usage_stats (usage_id TEXT, session_id TEXT,
              message_id TEXT, model_id TEXT, provider_id TEXT,
              input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER,
              cached_input_tokens INTEGER, cache_write_input_tokens INTEGER,
              created_at INTEGER);
            INSERT INTO new_sessions VALUES ('main', 'Main', 1, 1, '/p', NULL, NULL, NULL, 0);
            INSERT INTO deepchat_messages VALUES
              ('u', 'main', 1, 'user', '"Prompt"', 'sent', '{}', 1, 1),
              ('a', 'main', 2, 'assistant', '[]', 'sent', '{"model":"meta",
                "inputTokens":9,"outputTokens":9}', 1, 1),
              ('b', 'main', 3, 'assistant', '"plain answer"', 'sent',
                '{"model":"meta","inputTokens":10,"outputTokens":2}', 1, 1);
            INSERT INTO deepchat_assistant_blocks (message_id, block_index,
              block_type, status, text_content, updated_at) VALUES
              ('a', 0, 'content', 'success', 'Answer', 1);
            INSERT INTO deepchat_usage_stats VALUES
              ('1', 'main', 'a', 'usage', 'usage-provider', 100, 20, 130, 150, 5, 1),
              ('2', 'main', NULL, NULL, NULL, 7, 3, NULL, 0, 0, 1);"#,
        )
        .unwrap();
    let data = read_json(&mut provider, "main");
    assert_eq!(
        data["messages"][1]["tokens"],
        serde_json::json!({"input": 100, "output": 20, "cache": {"read": 100, "write": 0}})
    );
    assert_eq!(
        (
            &data["stats"]["total_input_tokens"],
            &data["stats"]["total_output_tokens"]
        ),
        (&117.into(), &25.into())
    );
}
