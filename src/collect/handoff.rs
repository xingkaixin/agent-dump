use crate::collect::model::Operation;
use agent_dump_core::query::scanner::Scan;
use jiff::civil::Date;
use serde_json::json;
use std::path::Path;

pub struct Gaps<'a> {
    pub query_failures: usize,
    pub read_failed: &'a [String],
}

pub fn handoff(
    operation: &Operation,
    scan: &Scan,
    positions: &[(usize, usize)],
    since: Date,
    until: Date,
    output: &Path,
    gaps: &Gaps<'_>,
) -> crate::Result<String> {
    let now = agent_dump_core::session::timestamp::Timestamp::now();
    let context = json!({"generated_at":now.iso_local(), "timezone":now.format_local("%Z"), "since":since.to_string(), "until":until.to_string(), "mode":operation.mode.name(), "working_directory":agent_dump_core::storage::source_io::path_text(&std::env::current_dir()?), "report_path":agent_dump_core::storage::source_io::path_text(&agent_dump_core::query::project_path(&agent_dump_core::storage::source_io::path_text(output))?), "shell":if cfg!(windows) {"PowerShell"} else {"POSIX"}, "session_count":positions.len(), "date_basis":"text_span_local_date", "discovery_failed_count":scan.failed_providers.len(), "query_read_failed_count":gaps.query_failures, "date_read_failed_count":gaps.read_failed.len(), "date_read_failed_sessions":gaps.read_failed});
    let mut prompt =
        crate::collect::prompts::handoff_header(operation.mode, since, until);
    prompt += &crate::collect::prompts::envelope(
        "collect_task",
        "collect://task",
        &agent_dump_core::query::transcript::search_value(&context),
    );
    let mut positions = positions.to_vec();
    positions.sort_by_key(|&(g, s)| {
        let group = &scan.groups[g];
        let session = &group.sessions[s];
        (session.created_at, group.info.name, session.id.clone())
    });
    for (g, s) in positions {
        let group = &scan.groups[g];
        let session = &group.sessions[s];
        let uri = format!("{}://{}", group.info.scheme, session.id);
        let argv = [
            agent_dump_core::storage::source_io::path_text(
                &std::env::current_exe()?,
            ),
            uri.clone(),
            "--read".into(),
            "--order".into(),
            "asc".into(),
            "--json".into(),
        ];
        let command = crate::command::shell_command(&argv);
        let record = json!({"uri":uri, "created_at":session.created_at.iso_local(), "updated_at":session.updated_at.iso_local(), "title":session.title, "project_directory":session.working_directory(), "read_argv":argv, "read_command":command});
        prompt += "\n";
        prompt += &crate::collect::prompts::envelope(
            "collect_session",
            &uri,
            &agent_dump_core::query::transcript::search_value(&record),
        );
    }
    Ok(prompt + "\n" + crate::collect::prompts::MANIFEST_END)
}
