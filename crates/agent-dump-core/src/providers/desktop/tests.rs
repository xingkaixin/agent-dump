use super::*;
use crate::output::diagnostics::Diagnostic;
use std::fmt::Write as _;

#[test]
fn each_operation_selects_current_candidates_and_reads_keep_session_source() {
    for kind in [Kind::DeepChat, Kind::Cherry, Kind::MiniMax] {
        for find_first in [false, true] {
            let (directory, mut provider, old_session, _) = fixture(kind);
            let fallback = old_session.source_path.clone();
            let primary = directory.path().join("primary/source.sqlite");
            let changed = directory.path().join("changed/source.sqlite");
            std::fs::create_dir_all(primary.parent().unwrap()).unwrap();
            std::fs::create_dir_all(changed.parent().unwrap()).unwrap();
            let roots = std::sync::Arc::new(std::sync::Mutex::new(vec![
                ("Primary", primary.clone()),
                ("Fallback", fallback.clone()),
            ]));
            provider.search_roots = Box::new({
                let roots = roots.clone();
                move || Ok(roots.lock().unwrap().clone())
            });
            if find_first {
                assert_eq!(
                    provider
                        .find(&old_session.id, &mut |_| Ok(()))
                        .unwrap()
                        .session
                        .unwrap()
                        .source_path,
                    fallback
                );
            } else {
                assert_eq!(
                    provider
                        .discover(Window::Created(36500), &mut |_| Ok(()))
                        .unwrap()
                        .sessions[0]
                        .source_path,
                    fallback
                );
            }
            std::fs::copy(&fallback, &primary).unwrap();
            std::fs::copy(&fallback, &changed).unwrap();
            for expected in [&primary, &fallback] {
                assert_eq!(
                    provider
                        .find(&old_session.id, &mut |_| Ok(()))
                        .unwrap()
                        .session
                        .unwrap()
                        .source_path,
                    *expected
                );
                assert_eq!(
                    provider
                        .discover(Window::Created(36500), &mut |_| Ok(()))
                        .unwrap()
                        .sessions[0]
                        .source_path,
                    *expected
                );
                assert_eq!(provider.source_root(), expected.parent().unwrap());
                std::fs::remove_file(expected).unwrap();
            }
            assert!(
                provider
                    .find(&old_session.id, &mut |_| Ok(()))
                    .unwrap()
                    .session
                    .is_none()
            );
            assert!(
                !provider
                    .discover(Window::Created(36500), &mut |_| Ok(()))
                    .unwrap()
                    .available
            );
            *roots.lock().unwrap() = vec![("Changed", changed.clone())];
            assert_eq!(provider.search_roots().unwrap()[0].1, changed);
            assert_eq!(
                provider
                    .find(&old_session.id, &mut |_| Ok(()))
                    .unwrap()
                    .session
                    .unwrap()
                    .source_path,
                changed
            );
            assert_eq!(
                provider
                    .discover(Window::Created(36500), &mut |_| Ok(()))
                    .unwrap()
                    .sessions[0]
                    .source_path,
                changed
            );
            assert_eq!(provider.source_root(), changed.parent().unwrap());
            assert!(
                provider.read(&old_session, false, &mut |_| Ok(())).is_err()
            );
            assert!(!fallback.exists());
        }
    }
}

fn fixture(kind: Kind) -> (tempfile::TempDir, Desktop, Session, &'static str) {
    let directory = tempfile::tempdir().unwrap();
    let database = directory.path().join("source.sqlite");
    let connection = Connection::open(&database).unwrap();
    let (sql, id, table) = match kind {
        Kind::DeepChat => (
            "CREATE TABLE new_sessions (id TEXT, title TEXT, created_at INTEGER, updated_at INTEGER, project_dir TEXT, agent_id TEXT, parent_session_id TEXT, session_kind TEXT, is_draft INTEGER);
             CREATE TABLE deepchat_sessions (id TEXT, model_id TEXT, provider_id TEXT);
             CREATE TABLE deepchat_messages (id TEXT, session_id TEXT, order_seq INTEGER, role TEXT, content TEXT, status TEXT, metadata TEXT, created_at INTEGER, updated_at INTEGER);
             INSERT INTO new_sessions VALUES ('kept', 'Kept', 1768478400000, 1768478400000, '/project', NULL, NULL, 'conversation', 0);
             INSERT INTO deepchat_messages VALUES ('kept-user', 'kept', 1, 'user', '{\"text\":\"Prompt\"}', 'sent', '{}', 1768478400000, 1768478400000);",
            "kept",
            "new_sessions",
        ),
        Kind::Cherry => (
            "CREATE TABLE topic (id TEXT, name TEXT, created_at INTEGER, updated_at INTEGER, active_node_id TEXT, deleted_at INTEGER);
             CREATE TABLE message (id TEXT);
             CREATE TABLE agent_workspace (id TEXT, path TEXT);
             CREATE TABLE agent_session (id TEXT, name TEXT, created_at INTEGER, updated_at INTEGER, workspace_id TEXT);
             CREATE TABLE agent_session_message (id TEXT, session_id TEXT, role TEXT, data TEXT, model_id TEXT, message_snapshot TEXT, created_at INTEGER);
             INSERT INTO agent_session VALUES ('kept', 'Kept', 1768478400000, 1768478400000, NULL);
             INSERT INTO agent_session_message VALUES ('kept-user', 'kept', 'user', '{\"parts\":[{\"type\":\"text\",\"text\":\"Prompt\"}]}', NULL, NULL, 1768478400000);",
            "session-kept",
            "agent_session",
        ),
        Kind::MiniMax => (
            "CREATE TABLE local_runtime_sessions (session_id TEXT, columnar_version INTEGER, runtime TEXT, visibility TEXT, session_kind TEXT, archived INTEGER, title TEXT, workspace_dir TEXT, parent_session_id TEXT, created_at_ms INTEGER, updated_at_ms INTEGER, extra_data_json TEXT);
             CREATE TABLE local_runtime_message_rows (id INTEGER, session_id TEXT, msg_id TEXT, role TEXT, turn_id TEXT, source TEXT, created_at_ms INTEGER, data_json TEXT);
             CREATE TABLE local_runtime_messages (session_id TEXT, display_messages_json TEXT);
             CREATE TABLE local_runtime_message_row_migrations (session_id TEXT);
             INSERT INTO local_runtime_sessions VALUES ('kept', 3, 'pi-agent', 'visible', 'conversation', 0, 'Kept', '/project', NULL, 1768478400000, 1768478400000, '{}');
             INSERT INTO local_runtime_message_rows VALUES (1, 'kept', 'kept-user', 'user', 'turn', 'agent', 1768478400000, '{\"msg_id\":\"kept-user\",\"role\":\"user\",\"msg_content\":\"Prompt\"}');",
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
fn cherry_boot_config_edits_failures_and_recovery_keep_existing_sessions_readable()
 {
    let (directory, mut provider, fallback_session, _) = fixture(Kind::Cherry);
    let fallback = fallback_session.source_path;
    let boot = directory.path().join("boot-config.json");
    let roots = [
        directory.path().join("first"),
        directory.path().join("second"),
    ];
    for root in &roots {
        std::fs::create_dir_all(root.join("Data")).unwrap();
        std::fs::copy(&fallback, root.join("Data/cherrystudio.sqlite"))
            .unwrap();
    }
    provider.search_roots = Box::new({
        let boot = boot.clone();
        let fallback = fallback.clone();
        move || {
            crate::providers::desktop::cherry::storage_roots(
                &boot,
                fallback.clone(),
            )
        }
    });
    let mut selected = Vec::new();
    for root in &roots {
        std::fs::write(
            &boot,
            serde_json::json!({"app.user_data_path": {"current": root}})
                .to_string(),
        )
        .unwrap();
        let session = provider
            .find("session-kept", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap();
        assert_eq!(session.source_path, root.join("Data/cherrystudio.sqlite"));
        assert_eq!(
            provider
                .discover(Window::Created(36500), &mut |_| Ok(()))
                .unwrap()
                .sessions[0]
                .source_path,
            session.source_path
        );
        selected.push(session);
    }
    for bad in [
        b"{".as_slice(),
        b"[]",
        b"{\"app.user_data_path\":null}",
        b"\xff",
    ] {
        std::fs::write(&boot, bad).unwrap();
        assert!(provider.find("session-kept", &mut |_| Ok(())).is_err());
        assert!(
            provider
                .discover(Window::Created(36500), &mut |_| Ok(()))
                .is_err()
        );
        for session in &selected {
            let before = std::fs::read(&session.source_path).unwrap();
            assert_eq!(
                provider.read(session, false, &mut |_| Ok(())).unwrap().id,
                session.id
            );
            assert_eq!(std::fs::read(&session.source_path).unwrap(), before);
        }
        assert_eq!(std::fs::read(&boot).unwrap(), bad);
    }
    std::fs::write(
        &boot,
        serde_json::json!({"app.user_data_path": {"restored": roots[0]}})
            .to_string(),
    )
    .unwrap();
    assert_eq!(
        provider
            .find("session-kept", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap()
            .source_path,
        selected[0].source_path
    );
    std::fs::remove_file(&boot).unwrap();
    assert_eq!(
        provider
            .find("session-kept", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap()
            .source_path,
        fallback
    );
    assert!(!boot.exists());
}

#[test]
fn source_removed_after_lookup_keeps_missing_path_and_provider_roots() {
    for (kind, name) in [
        (Kind::DeepChat, "DeepChat"),
        (Kind::Cherry, "Cherry Studio"),
        (Kind::MiniMax, "MiniMax Code"),
    ] {
        let (_directory, provider, session, _) = fixture(kind);
        std::fs::remove_file(&session.source_path).unwrap();
        for zh in [false, true] {
            let error =
                provider.read(&session, zh, &mut |_| Ok(())).err().unwrap();
            let diagnostic = Diagnostic::read_failed(
                error.as_ref(),
                vec!["must not replace provider roots".into()],
                zh,
            );
            let path = session.source_path.display();
            let mut expected = if zh {
                format!(
                    "诊断信息\n结论: {name} 会话数据源不存在。\n证据:\n  - missing path: {path}\n"
                )
            } else {
                format!(
                    "Diagnostic\nSummary: {name} session source is missing.\nDetails:\n  - missing path: {path}\n"
                )
            };
            if !matches!(kind, Kind::Cherry) {
                expected.push_str(if zh {
                    "已检查路径:\n"
                } else {
                    "Searched roots:\n"
                });
                writeln!(expected, "  - Synthetic source: {path}").unwrap();
            }
            assert_eq!(diagnostic.render(zh), expected);
        }
        assert!(!session.source_path.exists());
    }
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
        assert!(
            !diagnostic.contains("Next steps")
                && !diagnostic.contains("Searched roots")
        );
        assert_eq!(std::fs::read(&session.source_path).unwrap(), before);
    }
}

#[test]
fn source_replaced_after_lookup_preserves_capability_details() {
    for (kind, table) in [
        (Kind::DeepChat, None),
        (Kind::Cherry, Some("agent_workspace")),
        (Kind::MiniMax, Some("local_runtime_messages")),
    ] {
        let (_directory, provider, session, _) = fixture(kind);
        if let Some(table) = table {
            Connection::open(&session.source_path)
                .unwrap()
                .execute_batch(&format!("DROP TABLE {table}"))
                .unwrap();
        } else {
            std::fs::write(
                &session.source_path,
                b"synthetic unreadable source",
            )
            .unwrap();
        }
        let before = std::fs::read(&session.source_path).unwrap();
        let error = provider
            .read(&session, false, &mut |_| Ok(()))
            .err()
            .unwrap();
        for zh in [false, true] {
            let diagnostic =
                Diagnostic::read_failed(error.as_ref(), Vec::new(), zh)
                    .render(zh);
            assert!(
                diagnostic.contains(&format!(
                    "  - {}\n",
                    session.source_path.display()
                ))
            );
            assert!(diagnostic.contains(if zh {
                "缺失能力: "
            } else {
                "Capability gap: "
            }));
            assert!(!diagnostic.contains(if zh {
                "读取会话数据失败"
            } else {
                "Failed to read session data"
            }));
            if matches!(kind, Kind::MiniMax) {
                assert!(diagnostic.contains("  - local_runtime_messages\n"));
            }
        }
        assert_eq!(std::fs::read(&session.source_path).unwrap(), before);
    }
}

#[test]
fn migration_required_after_lookup_uses_localized_read_failure() {
    let (_directory, provider, session, _) = fixture(Kind::MiniMax);
    Connection::open(&session.source_path)
        .unwrap()
        .execute_batch("UPDATE local_runtime_sessions SET columnar_version = 2")
        .unwrap();
    let before = std::fs::read(&session.source_path).unwrap();
    let error = provider
        .read(&session, false, &mut |_| Ok(()))
        .err()
        .unwrap();
    for zh in [false, true] {
        let diagnostic = Diagnostic::read_failed(
            error.as_ref(),
            vec!["Synthetic source".into()],
            zh,
        )
        .render(zh);
        assert!(diagnostic.contains(if zh {
            "结论: 读取会话数据失败。"
        } else {
            "Summary: Failed to read session data."
        }));
        assert!(diagnostic.contains(if zh {
            "agent-dump 不会迁移源数据。"
        } else {
            "agent-dump never migrates source data."
        }));
        assert!(diagnostic.contains("  - Synthetic source\n"));
        assert!(!diagnostic.contains(if zh {
            "缺失能力"
        } else {
            "Capability gap"
        }));
    }
    assert_eq!(std::fs::read(&session.source_path).unwrap(), before);
}

#[test]
fn minimax_lists_child_sessions_with_messages() {
    let (_directory, mut provider, _, _) = fixture(Kind::MiniMax);
    Connection::open(&provider.database)
        .unwrap()
        .execute_batch(
            r#"CREATE TABLE local_runtime_token_usage (id INTEGER, session_id TEXT, turn_id TEXT, model TEXT, ts INTEGER);
            INSERT INTO local_runtime_sessions VALUES
              ('hidden-v2', 2, 'pi-agent', 'hidden', 'conversation', 0, NULL, NULL, NULL, 1, 1, '{}'),
              ('cron-pending', 3, 'pi-agent', 'visible', 'cron', 0, NULL, NULL, NULL, 1, 1, '{}'),
              ('empty', 3, 'pi-agent', 'visible', 'conversation', 0, 'Empty', NULL, NULL, 1, 1, '{}'),
              ('child', 3, 'opencode', 'hidden', 'subagent', 0, '  ', NULL, 'kept', 1, 1, '{}');
            INSERT INTO local_runtime_messages VALUES ('cron-pending', '[{}]');
            INSERT INTO local_runtime_message_rows VALUES
              (2, 'child', 'c1', 'user', 't', 'cron', 2, '{"msg_id":"c1","role":"user","msg_content":"Scheduled"}'),
              (3, 'child', 'c2', 'user', 't', 'agent', 3, '{"msg_id":"c2","role":"user","msg_content":"<system-reminder>x</system-reminder>"}'),
              (4, 'child', 'c3', 'user', 't', 'agent', 4, '{"msg_id":"c3","role":"user","msg_content":"\n  Fix   the bug\nnow"}');
            INSERT INTO local_runtime_token_usage VALUES (1, 'child', 't', 'm', 9000);"#,
        )
        .unwrap();
    let found = provider.discover(Window::All, &mut |_| Ok(())).unwrap();
    assert!(found.failures.is_empty());
    assert_eq!(
        found
            .sessions
            .iter()
            .map(|s| (
                s.id.as_str(),
                s.title.as_str(),
                s.updated_at.as_millisecond(),
                s.message_count
            ))
            .collect::<Vec<_>>(),
        [
            ("kept", "Kept", 1_768_478_400_000, Some(1)),
            ("child", "Fix the bug", 9000, Some(3))
        ]
    );
    for id in ["hidden-v2", "cron-pending", "empty"] {
        assert!(
            provider
                .find(id, &mut |_| Ok(()))
                .unwrap()
                .session
                .is_none()
        );
    }
}

#[test]
fn minimax_messages_carry_events_tools_and_turn_usage() {
    let (_directory, mut provider, _, _) = fixture(Kind::MiniMax);
    Connection::open(&provider.database)
        .unwrap()
        .execute_batch(
            r#"CREATE TABLE local_runtime_token_usage (id INTEGER, session_id TEXT, turn_id TEXT, model TEXT, ts INTEGER, input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER, cost_usd REAL);
            INSERT INTO local_runtime_message_rows VALUES
              (2, 'kept', 'a1', 'assistant', 'turn', 'agent', 2, '{"msg_id":"a1","role":"assistant","msg_content":"Draft"}'),
              (3, 'kept', 'a2', 'assistant', 'turn', 'agent', 3, '{"msg_id":"a2","role":"assistant","thinking_content":"Think","msg_content":"Done","error":"Rate limited","usage":{"input_tokens":99},"attachments":[{"desktop_path":"/d/a.png","mime_type":"image/png"}],"tool_calls":[{"tool_name":"task","tool_call_id":"t1","tool_call_status":2,"tool_call_result_data":"{\"isError\":true,\"text\":\"boom\",\"details\":{\"sub_session_id\":\"child\"}}"},{"tool_call_id":"t2"},{"tool_name":"bash","tool_call_id":"t3","tool_call_status":2,"tool_call_result_data":"ok"}]}'),
              (4, 'kept', 'c1', 'assistant', 'turn', 'agent', 4, '{"msg_id":"c1","role":"assistant","kind":"compaction","msg_content":"Summary"}'),
              (5, 'kept', 'u2', 'user', 'multi', 'agent', 5, '{"msg_id":"u2","role":"user","kind":"review_x"}'),
              (6, 'kept', 'a3', 'assistant', 'multi', 'agent', 6, '{"msg_id":"a3","role":"assistant","msg_content":"Mixed"}');
            INSERT INTO local_runtime_token_usage VALUES
              (1, 'kept', 'turn', 'm', 10, 100, 20, 5, 40, 10, 0.025),
              (2, 'kept', 'turn', 'm', 11, 50, 10, 0, 0, 0, NULL),
              (3, 'kept', 'multi', 'a', 12, 1, 1, 0, 0, 0, 0),
              (4, 'kept', 'multi', 'b', 13, 1, 1, 0, 0, 0, 0);"#,
        )
        .unwrap();
    let data = read_json(&mut provider, "kept");
    let messages = data["messages"].as_array().unwrap();
    let answer = &messages[2];
    assert_eq!(
        part_texts(answer),
        [
            "Think",
            "Done",
            "Attachment: /d/a.png (image/png)",
            "Rate limited"
        ]
    );
    assert_eq!(
        answer["parts"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|part| part["type"] == "tool")
            .map(|part| (
                &part["tool"],
                &part["state"]["status"],
                &part["state"]["error"]
            ))
            .collect::<Vec<_>>(),
        [
            (&"task".into(), &"error".into(), &"boom".into()),
            (
                &"bash".into(),
                &"completed".into(),
                &serde_json::Value::Null
            )
        ]
    );
    assert_eq!(
        (
            &answer["subagent_id"],
            &answer["model"],
            &answer["cost"],
            &answer["tokens"]
        ),
        (
            &"child".into(),
            &"m".into(),
            &0.025.into(),
            &serde_json::json!({"input": 150, "output": 30, "reasoning": 5, "cache": {"read": 40, "write": 10}})
        )
    );
    assert!(messages[1]["tokens"].as_object().unwrap().is_empty());
    assert!(messages[5]["tokens"].as_object().unwrap().is_empty());
    assert_eq!(
        messages[3..5]
            .iter()
            .map(|m| (&m["role"], &m["mode"], part_texts(m)))
            .collect::<Vec<_>>(),
        [
            (
                &"assistant".into(),
                &"compaction".into(),
                vec!["Context compacted", "Summary"]
            ),
            (&"user".into(), &"review_x".into(), vec!["Event: review_x"])
        ]
    );
    assert_eq!(
        data["stats"],
        serde_json::json!({"total_cost": 0.025, "total_input_tokens": 152, "total_output_tokens": 32, "message_count": 6, "total_tokens": 239})
    );
}

#[test]
fn deepchat_lists_rooted_sessions_with_messages() {
    let (_directory, mut provider, _, _) = fixture(Kind::DeepChat);
    Connection::open(&provider.database)
        .unwrap()
        .execute_batch(
            r#"CREATE TABLE deepchat_assistant_blocks (message_id TEXT, block_index INTEGER, updated_at INTEGER);
            CREATE TABLE deepchat_usage_stats (session_id TEXT, created_at INTEGER);
            INSERT INTO new_sessions VALUES
              ('empty', 'Empty', 1, 1, NULL, NULL, NULL, NULL, 0),
              ('loop-a', 'A', 1, 1, NULL, NULL, 'loop-b', NULL, 0),
              ('loop-b', 'B', 1, 1, NULL, NULL, 'loop-a', NULL, 0),
              ('child', '  ', 1, 1, NULL, NULL, 'kept', NULL, 0),
              ('main', '<system-reminder>x</system-reminder>
  First   line
Second', 1, 1000, NULL, NULL, 'missing', NULL, 0);
            INSERT INTO deepchat_messages VALUES
              ('loop-a-m', 'loop-a', 1, 'user', '"hi"', 'sent', '{}', 1, 1),
              ('loop-b-m', 'loop-b', 1, 'user', '"hi"', 'sent', '{}', 1, 1),
              ('child-m', 'child', 1, 'user', '"hi"', 'sent', '{}', 1, 1),
              ('m', 'main', 1, 'user', '"hi"', 'sent', '{}', 1, 2000);
            INSERT INTO deepchat_assistant_blocks VALUES ('m', 0, 4000);
            INSERT INTO deepchat_usage_stats VALUES ('main', 3000);"#,
        )
        .unwrap();
    let found = provider.discover(Window::All, &mut |_| Ok(())).unwrap();
    assert_eq!(
        found
            .sessions
            .iter()
            .map(|s| (
                s.id.as_str(),
                s.title.as_str(),
                s.updated_at.as_millisecond()
            ))
            .collect::<Vec<_>>(),
        [
            ("kept", "Kept", 1_768_478_400_000),
            ("child", "Untitled Session", 1),
            ("main", "First line", 4000)
        ]
    );
    for id in ["empty", "loop-a"] {
        assert!(
            provider
                .find(id, &mut |_| Ok(()))
                .unwrap()
                .session
                .is_none()
        );
    }
}

fn read_json(provider: &mut Desktop, id: &str) -> serde_json::Value {
    let session = provider.find(id, &mut |_| Ok(())).unwrap().session.unwrap();
    serde_json::to_value(
        provider.read(&session, false, &mut |_| Ok(())).unwrap(),
    )
    .unwrap()
}

fn part_texts(message: &serde_json::Value) -> Vec<&str> {
    message["parts"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|part| part["text"].as_str())
        .collect()
}

#[test]
fn deepchat_messages_carry_references_and_usage() {
    let (_directory, mut provider, _, _) = fixture(Kind::DeepChat);
    Connection::open(&provider.database)
        .unwrap()
        .execute_batch(
            r#"CREATE TABLE deepchat_user_messages (message_id TEXT, text TEXT);
            CREATE TABLE deepchat_user_message_files (message_id TEXT, ordinal INTEGER, name TEXT, path TEXT, mime_type TEXT, size INTEGER);
            CREATE TABLE deepchat_user_message_links (message_id TEXT, ordinal INTEGER, url TEXT);
            CREATE TABLE deepchat_assistant_blocks (message_id TEXT, block_index INTEGER, block_type TEXT, status TEXT, text_content TEXT, tool_call_id TEXT, tool_name TEXT, tool_params TEXT, tool_response TEXT, action_type TEXT, image_mime_type TEXT, extra_json TEXT, updated_at INTEGER);
            CREATE TABLE deepchat_usage_stats (usage_id TEXT, session_id TEXT, message_id TEXT, model_id TEXT, provider_id TEXT, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, cached_input_tokens INTEGER, cache_write_input_tokens INTEGER, created_at INTEGER);
            INSERT INTO new_sessions VALUES ('main', 'Main', 1, 1, '/p', NULL, NULL, NULL, 0);
            INSERT INTO deepchat_sessions VALUES ('main', 'session-model', 'session-provider');
            INSERT INTO deepchat_messages VALUES
              ('u', 'main', 1, 'user', '{"text":"stale","inlineItems":[{"type":"session","sessionId":"other","title":"Other"},{"type":"session","sessionId":"bare"}]}', 'sent', '{}', 1, 1),
              ('a', 'main', 2, 'assistant', '[]', 'sent', '{"model":"meta","inputTokens":9,"outputTokens":9}', 1, 1),
              ('b', 'main', 3, 'assistant', '"plain answer"', 'sent', '{"model":"meta","inputTokens":10,"outputTokens":2,"cachedInputTokens":30}', 1, 1),
              ('c', 'main', 4, 'assistant', '{"not":"array"}', 'sent', '{}', 1, 1);
            INSERT INTO deepchat_user_messages VALUES ('u', 'Prompt');
            INSERT INTO deepchat_user_message_files VALUES ('u', 0, 'notes.txt', '/p/notes.txt', 'text/plain', 4);
            INSERT INTO deepchat_user_message_links VALUES ('u', 0, 'https://example.invalid');
            INSERT INTO deepchat_assistant_blocks (message_id, block_index, block_type, status, text_content, tool_call_id, tool_name, updated_at) VALUES
              ('a', 0, 'search', 'success', 'Search results', NULL, NULL, 1),
              ('a', 1, 'action', 'success', '', NULL, NULL, 1),
              ('a', 2, 'tool_call', 'error', 'denied by user', 'call', 'shell', 1);
            INSERT INTO deepchat_usage_stats VALUES
              ('1', 'main', 'a', 'usage', 'usage-provider', 100, 20, 130, 150, 5, 1),
              ('2', 'main', NULL, NULL, NULL, 7, 3, NULL, 0, 0, 1);"#,
        )
        .unwrap();
    let data = read_json(&mut provider, "main");
    let messages = data["messages"].as_array().unwrap();
    assert_eq!(
        part_texts(&messages[0]),
        [
            "Prompt",
            "Session: Other (other)",
            "Session: bare",
            "Attachment: /p/notes.txt",
            "https://example.invalid"
        ]
    );
    assert!(messages[0]["model"].is_null());
    assert_eq!(part_texts(&messages[1]), ["Search results"]);
    assert_eq!(messages[1]["parts"][1]["state"]["error"], "denied by user");
    assert_eq!(
        messages[1]["tokens"],
        serde_json::json!({"input": 100, "output": 20, "cache": {"read": 100, "write": 0}})
    );
    assert_eq!(
        (&messages[1]["model"], &messages[1]["provider"]),
        (&"usage".into(), &"usage-provider".into())
    );
    assert_eq!(part_texts(&messages[2]), ["plain answer"]);
    assert_eq!(messages[2]["tokens"]["cache"]["read"], 10);
    assert_eq!(
        (&messages[2]["model"], &messages[2]["provider"]),
        (&"meta".into(), &"session-provider".into())
    );
    assert!(messages[3]["parts"].as_array().unwrap().is_empty());
    assert_eq!(
        (
            &data["stats"]["total_input_tokens"],
            &data["stats"]["total_output_tokens"]
        ),
        (&117.into(), &25.into())
    );
}

#[test]
fn cherry_lists_sessions_with_content_or_usage() {
    let (_directory, mut provider, _, _) = fixture(Kind::Cherry);
    Connection::open(&provider.database)
        .unwrap()
        .execute_batch(
            r#"ALTER TABLE agent_session ADD COLUMN last_activity_at INTEGER;
            ALTER TABLE agent_session_message ADD COLUMN stats TEXT;
            ALTER TABLE agent_session_message ADD COLUMN deleted_at INTEGER;
            INSERT INTO topic VALUES ('idle', 'Idle', 1, 1, NULL, NULL);
            INSERT INTO agent_session (id, name, created_at, updated_at, last_activity_at) VALUES
              ('empty', 'Empty', 1, 1, 1),
              ('deleted', 'Deleted', 1, 1, 1),
              ('named', '  ', 1, 1, 9000),
              ('usage', NULL, 1, 1, NULL);
            INSERT INTO agent_session_message (id, session_id, role, data, stats, deleted_at, created_at) VALUES
              ('d', 'deleted', 'user', '{"parts":[{"type":"text","text":"gone"}]}', NULL, 5, 1),
              ('n1', 'named', 'system', '{"parts":[{"type":"text","text":"setup"}]}', NULL, NULL, 1),
              ('n2', 'named', 'user', '{"parts":[{"type":"text","text":"<system-reminder>x</system-reminder>"}]}', NULL, NULL, 2),
              ('n3', 'named', 'user', '{"parts":[{"type":"text","text":"\n  Fix   the bug\nnow"}]}', NULL, NULL, 3),
              ('n4', 'named', 'assistant', '{"parts":[{"type":"text","text":"Done"}]}', NULL, NULL, 4),
              ('n5', 'named', 'assistant', '{"parts":[]}', NULL, NULL, 5),
              ('u1', 'usage', 'assistant', '{"parts":[]}', '{"inputTokens":3}', NULL, 1);"#,
        )
        .unwrap();
    let found = provider.discover(Window::All, &mut |_| Ok(())).unwrap();
    assert_eq!(
        found
            .sessions
            .iter()
            .map(|s| (
                s.id.as_str(),
                s.title.as_str(),
                s.updated_at.as_millisecond(),
                s.message_count
            ))
            .collect::<Vec<_>>(),
        [
            ("session-kept", "Kept", 1_768_478_400_000, Some(1)),
            ("session-named", "Fix the bug", 9000, Some(2)),
            ("session-usage", "Cherry Studio", 1, Some(1))
        ]
    );
    for id in ["session-empty", "session-deleted", "topic-idle"] {
        assert!(
            provider
                .find(id, &mut |_| Ok(()))
                .unwrap()
                .session
                .is_none()
        );
    }
    let data = read_json(&mut provider, "session-named");
    assert_eq!(
        (
            &data["title"],
            &data["time_updated"],
            &data["stats"]["message_count"]
        ),
        (&"Fix the bug".into(), &9000.into(), &2.into())
    );
    assert_eq!(
        data["messages"]
            .as_array()
            .unwrap()
            .iter()
            .map(|message| message["id"].as_str().unwrap())
            .collect::<Vec<_>>(),
        ["n3", "n4"]
    );
}

#[test]
fn cherry_reads_files_compact_summaries_and_usage() {
    let (_directory, mut provider, _, _) = fixture(Kind::Cherry);
    Connection::open(&provider.database)
        .unwrap()
        .execute_batch(
            r#"ALTER TABLE agent_session_message ADD COLUMN stats TEXT;
            INSERT INTO agent_session (id, name, created_at, updated_at) VALUES ('parts', 'Parts', 1, 1);
            INSERT INTO agent_session_message (id, session_id, role, data, stats, created_at) VALUES
              ('u', 'parts', 'user', '{"parts":[{"type":"file","url":"data:image/png;base64,AA","mediaType":"image/png"},{"type":"file","url":"file:///p/report.pdf","filename":"report.pdf","mediaType":"application/pdf"},{"type":"file","url":"file:///p/raw.bin"},{"type":"file"}]}', '{"inputTokens":99}', 1),
              ('a', 'parts', 'assistant', '{"parts":[{"type":"data-compact","data":{"content":"Summary"}}]}', '{"inputTokenDetails":{"noCacheTokens":5,"cacheReadTokens":3,"cacheWriteTokens":2},"outputTokenDetails":{"textTokens":4,"reasoningTokens":6},"costs":[{"currency":"USD","amount":0.25},{"currency":"USD","amount":0.5}]}', 2),
              ('b', 'parts', 'assistant', '{"parts":[{"type":"text","text":"Priced"}]}', '{"inputTokens":1,"outputTokens":1,"costs":[{"currency":"CNY","amount":3}]}', 3);"#,
        )
        .unwrap();
    let data = read_json(&mut provider, "session-parts");
    let messages = data["messages"].as_array().unwrap();
    assert_eq!(
        messages[0]["parts"][0],
        serde_json::json!({"type": "image", "mime_type": "image/png", "data": "data:image/png;base64,AA", "time_created": 1})
    );
    assert_eq!(
        part_texts(&messages[0]),
        ["Attachment: report.pdf", "Attachment: file:///p/raw.bin"]
    );
    assert_eq!(messages[0]["tokens"]["input"], 0);
    assert_eq!(part_texts(&messages[1]), ["Summary"]);
    assert_eq!(
        (&messages[1]["tokens"], &messages[1]["cost"]),
        (
            &serde_json::json!({"input": 10, "output": 10, "reasoning": 6, "cache": {"read": 3, "write": 2}}),
            &0.75.into()
        )
    );
    assert_eq!(messages[2]["cost"], 0);
    assert_eq!(
        (
            &data["stats"]["total_input_tokens"],
            &data["stats"]["total_output_tokens"],
            &data["stats"]["total_cost"]
        ),
        (&11.into(), &11.into(), &0.75.into())
    );
}
