use crate::providers::contract::{Provider, ProviderInfo};
use crate::query::{Query, TimeField};
use crate::session::Session;
use std::io::Write;

pub struct ScannedProvider {
    pub info: &'static ProviderInfo,
    pub provider: Box<dyn Provider>,
    pub sessions: Vec<Session>,
}

#[derive(Default)]
pub struct Scan {
    pub groups: Vec<ScannedProvider>,
    pub failed_providers: Vec<String>,
}

pub fn discover(
    query: Option<&Query>,
    days: i64,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<Scan> {
    discover_window(query, Some(days), zh, warnings)
}

pub fn discover_all(
    query: Option<&Query>,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<Scan> {
    discover_window(query, None, zh, warnings)
}

fn discover_window(
    query: Option<&Query>,
    days: Option<i64>,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<Scan> {
    let updated_since = query
        .is_none_or(|query| query.time_field == TimeField::Updated)
        .then_some(days)
        .flatten()
        .map(crate::session::timestamp::Timestamp::days_ago)
        .transpose()?;
    let mut scan = Scan::default();
    for registration in crate::providers::registry::all() {
        let info = &registration.info;
        if query
            .and_then(|q| q.providers.as_ref())
            .is_some_and(|names| !names.contains(info.name))
        {
            continue;
        }
        let result = (registration.open)().and_then(|mut provider| {
            let discovery = provider.discover(
                if updated_since.is_none() { days } else { None },
                &mut |diagnostic| {
                    writeln!(
                        warnings,
                        "{}",
                        crate::output::diagnostics::record_warning(
                            &diagnostic,
                            zh
                        )
                    )?;
                    Ok(())
                },
            )?;
            Ok((provider, discovery))
        });
        match result {
            Ok((provider, mut discovery)) => {
                if let Some(cutoff) = updated_since {
                    discovery
                        .sessions
                        .retain(|session| session.updated_at >= cutoff);
                }
                if !discovery.failures.is_empty() {
                    scan.failed_providers.push(info.name.into());
                }
                for failure in &discovery.failures {
                    writeln!(
                        warnings,
                        "{}",
                        crate::output::diagnostics::session_warning(
                            info, failure, zh
                        )
                    )?;
                }
                if discovery.available {
                    scan.groups.push(ScannedProvider {
                        info,
                        provider,
                        sessions: discovery.sessions,
                    });
                }
            }
            Err(error) => {
                scan.failed_providers.push(info.name.into());
                let error = crate::output::render::safe_line(
                    &crate::providers::error::operation_message(
                        error.as_ref(),
                        zh,
                    ),
                );
                let name = info.display_name;
                writeln!(
                    warnings,
                    "{}",
                    if zh {
                        format!("警告: {name} provider 操作失败: {error}")
                    } else {
                        format!("⚠️  {name} provider operation failed: {error}")
                    }
                )?;
            }
        }
    }
    Ok(scan)
}
