use crate::provider::{ProviderInfo, SessionFailure, SessionGroup};
use crate::registry::{self, Registration};
use std::collections::BTreeSet;
use std::io::Write;

fn scope(query: Option<&str>) -> crate::Result<Option<BTreeSet<String>>> {
    let Some(query) = query else {
        return Ok(None);
    };
    let (key, value) = query
        .trim()
        .split_once(':')
        .ok_or("Rust list currently supports only provider:NAME queries")?;
    if !key.eq_ignore_ascii_case("provider") || value.split_whitespace().count() > 1 {
        return Err("Rust list currently supports only provider:NAME queries".into());
    }
    let mut names = BTreeSet::new();
    for name in value
        .split(',')
        .map(str::trim)
        .filter(|name| !name.is_empty())
    {
        let name = name.to_lowercase();
        let name = if name == "claude" {
            "claudecode"
        } else {
            &name
        };
        registry::for_name(name)?;
        names.insert(name.to_owned());
    }
    if names.is_empty() {
        return Err("Empty provider scope".into());
    }
    Ok(Some(names))
}

fn session_warning(provider: &ProviderInfo, failure: &SessionFailure, zh: bool) -> String {
    let source = crate::render::safe_line(&failure.source);
    let error = crate::render::safe_line(&failure.error);
    if matches!(provider.name, "cherry" | "minimax") {
        let name = provider.display_name;
        if zh {
            format!("读取 {name} 会话 {source} 失败：{error}")
        } else {
            format!("Failed to read {name} session {source}: {error}")
        }
    } else if zh {
        format!("警告: 解析会话文件失败 {source}: {error}")
    } else {
        format!("⚠️  Failed to parse session file {source}: {error}")
    }
}

fn discover(
    registration: &'static Registration,
    days: i64,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<Option<SessionGroup>> {
    let result = (registration.open)().and_then(|mut provider| provider.discover(days));
    match result {
        Ok(discovery) => {
            for failure in &discovery.failures {
                writeln!(
                    warnings,
                    "{}",
                    session_warning(&registration.info, failure, zh)
                )?;
            }
            Ok(discovery.available.then_some(SessionGroup {
                provider: &registration.info,
                sessions: discovery.sessions,
            }))
        }
        Err(error) => {
            let name = registration.info.display_name;
            let error = crate::render::safe_line(&error.to_string());
            writeln!(
                warnings,
                "{}",
                if zh {
                    format!("警告: {name} provider 操作失败: {error}")
                } else {
                    format!("⚠️  {name} provider operation failed: {error}")
                }
            )?;
            Ok(None)
        }
    }
}

pub fn run(
    query: Option<&str>,
    days: i64,
    summary: bool,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<bool> {
    let scope = scope(query)?;
    let mut groups = Vec::new();
    for registration in registry::all() {
        if scope
            .as_ref()
            .is_some_and(|names| !names.contains(registration.info.name))
        {
            continue;
        }
        if let Some(group) = discover(registration, days, zh, warnings)? {
            groups.push(group);
        }
    }
    let names = scope
        .as_ref()
        .map(|names| names.iter().cloned().collect::<Vec<_>>().join(","));
    if groups.is_empty() {
        let mut roots = Vec::new();
        for registration in registry::all() {
            if let Ok(provider) = (registration.open)() {
                roots.extend(provider.search_roots().into_iter().map(|(label, path)| {
                    format!(
                        "{}: {label}: {}",
                        registration.info.display_name,
                        path.display()
                    )
                }));
            }
        }
        write!(
            out,
            "{}",
            crate::render::empty_list(names.as_deref(), &roots, zh)
        )?;
        return Ok(scope.is_some());
    }
    write!(
        out,
        "{}",
        crate::render::list(&groups, names.as_deref(), days, summary, zh)
    )?;
    Ok(true)
}
