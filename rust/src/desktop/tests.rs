use super::*;
use crate::diagnostics::Diagnostic;

fn fixture(kind: Kind) -> (tempfile::TempDir, Desktop, Session, &'static str) {
    let directory = tempfile::tempdir().unwrap();
    let database = directory.path().join("source.sqlite");
    let connection = Connection::open(&database).unwrap();
    let (sql, id, table) = match kind {
        Kind::DeepChat => (
            "CREATE TABLE new_sessions (id TEXT, title TEXT, created_at INTEGER, updated_at INTEGER, project_dir TEXT, agent_id TEXT, parent_session_id TEXT, session_kind TEXT, is_draft INTEGER);
             CREATE TABLE deepchat_sessions (id TEXT, model_id TEXT, provider_id TEXT);
             CREATE TABLE deepchat_messages (session_id TEXT);
             INSERT INTO new_sessions VALUES ('kept', 'Kept', 1768478400000, 1768478400000, '/project', NULL, NULL, 'conversation', 0);",
            "kept",
            "new_sessions",
        ),
        Kind::Cherry => (
            "CREATE TABLE topic (id TEXT, name TEXT, created_at INTEGER, updated_at INTEGER, active_node_id TEXT, deleted_at INTEGER);
             CREATE TABLE message (id TEXT);
             CREATE TABLE agent_workspace (id TEXT, path TEXT);
             CREATE TABLE agent_session (id TEXT, name TEXT, created_at INTEGER, updated_at INTEGER, workspace_id TEXT);
             CREATE TABLE agent_session_message (id TEXT, session_id TEXT, role TEXT, model_id TEXT, message_snapshot TEXT, created_at INTEGER);
             INSERT INTO agent_session VALUES ('kept', 'Kept', 1768478400000, 1768478400000, NULL);",
            "session-kept",
            "agent_session",
        ),
        Kind::MiniMax => (
            "CREATE TABLE local_runtime_sessions (session_id TEXT, columnar_version INTEGER, runtime TEXT, visibility TEXT, session_kind TEXT, archived INTEGER, title TEXT, workspace_dir TEXT, parent_session_id TEXT, created_at_ms INTEGER, updated_at_ms INTEGER, extra_data_json TEXT);
             CREATE TABLE local_runtime_message_rows (id INTEGER, session_id TEXT, msg_id TEXT, role TEXT, turn_id TEXT, source TEXT, created_at_ms INTEGER, data_json TEXT);
             CREATE TABLE local_runtime_messages (session_id TEXT, display_messages_json TEXT);
             CREATE TABLE local_runtime_message_row_migrations (session_id TEXT);
             INSERT INTO local_runtime_sessions VALUES ('kept', 3, 'pi-agent', 'visible', 'conversation', 0, 'Kept', '/project', NULL, 1768478400000, 1768478400000, '{}');",
            "kept",
            "local_runtime_sessions",
        ),
    };
    connection.execute_batch(sql).unwrap();
    drop(connection);
    let mut provider = Desktop {
        kind,
        search_roots: vec![("Synthetic source", database.clone())],
        database,
    };
    let session = provider.find(id, &mut |_| Ok(())).unwrap().session.unwrap();
    (directory, provider, session, table)
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
            let error = provider.read(&session, zh, &mut |_| Ok(())).err().unwrap();
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
                expected.push_str(&format!("  - Synthetic source: {path}\n"));
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
        let diagnostic = Diagnostic::read_failed(error.as_ref(), Vec::new(), false).render(false);
        assert!(diagnostic.contains(&format!(
            "  - missing path: {}\n  - session id: {}\n",
            session.source_path.display(),
            session.id
        )));
        assert!(!diagnostic.contains("Next steps") && !diagnostic.contains("Searched roots"));
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
            std::fs::write(&session.source_path, b"synthetic unreadable source").unwrap();
        }
        let before = std::fs::read(&session.source_path).unwrap();
        let error = provider
            .read(&session, false, &mut |_| Ok(()))
            .err()
            .unwrap();
        for zh in [false, true] {
            let diagnostic = Diagnostic::read_failed(error.as_ref(), Vec::new(), zh).render(zh);
            assert!(diagnostic.contains(&format!("  - {}\n", session.source_path.display())));
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
        let diagnostic =
            Diagnostic::read_failed(error.as_ref(), vec!["Synthetic source".into()], zh).render(zh);
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
        assert!(!diagnostic.contains(if zh { "缺失能力" } else { "Capability gap" }));
    }
    assert_eq!(std::fs::read(&session.source_path).unwrap(), before);
}
