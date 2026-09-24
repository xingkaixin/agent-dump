use crate::collect_model::Operation;
use crate::scanner::Scan;
use jiff::civil::Date;
use serde_json::json;
use std::path::Path;

pub fn handoff(
    operation: &Operation,
    scan: &Scan,
    positions: &[(usize, usize)],
    since: Date,
    until: Date,
    output: &Path,
    query_failures: usize,
) -> crate::Result<String> {
    let now = crate::timestamp::Timestamp::now();
    let context = json!({"generated_at":now.iso_local(), "timezone":now.format_local("%Z"), "since":since.to_string(), "until":until.to_string(), "mode":operation.mode.name(), "working_directory":crate::source_io::path_text(&std::env::current_dir()?), "report_path":crate::source_io::path_text(&crate::query::project_path(&crate::source_io::path_text(output))?), "shell":if cfg!(windows) {"PowerShell"} else {"POSIX"}, "session_count":positions.len(), "discovery_failed_count":scan.failed_providers.len(), "query_read_failed_count":query_failures});
    let mut prompt = crate::collect_prompts::handoff_header(operation.mode, since, until);
    prompt += &crate::collect_prompts::envelope(
        "collect_task",
        "collect://task",
        &crate::transcript::search_value(&context),
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
            crate::source_io::path_text(&std::env::current_exe()?),
            uri.clone(),
            "--format".into(),
            "print".into(),
        ];
        let command = if cfg!(windows) {
            "& ".to_owned()
                + &argv
                    .iter()
                    .map(|s| format!("'{}'", s.replace('\'', "''")))
                    .collect::<Vec<_>>()
                    .join(" ")
        } else {
            argv.iter()
                .map(|s| shell_quote(s))
                .collect::<Vec<_>>()
                .join(" ")
        };
        let record = json!({"uri":uri, "date":session.created_at.format_local("%Y-%m-%d"), "created_at":session.created_at.iso_local(), "updated_at":session.updated_at.iso_local(), "title":session.title, "project_directory":session.directory, "read_argv":argv, "read_command":command});
        prompt += "\n";
        prompt += &crate::collect_prompts::envelope(
            "collect_session",
            &uri,
            &crate::transcript::search_value(&record),
        );
    }
    Ok(prompt + "\n" + crate::collect_prompts::MANIFEST_END)
}

fn shell_quote(value: &str) -> String {
    if !value.is_empty()
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "_@%+=:,./-".contains(c))
    {
        value.into()
    } else {
        format!("'{}'", value.replace('\'', "'\"'\"'"))
    }
}
