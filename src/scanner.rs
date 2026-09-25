use crate::provider::{Provider, ProviderInfo};
use crate::query::Query;
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
    let mut scan = Scan::default();
    for registration in crate::registry::all() {
        let info = &registration.info;
        if query
            .and_then(|q| q.providers.as_ref())
            .is_some_and(|names| !names.contains(info.name))
        {
            continue;
        }
        let result = (registration.open)().and_then(|mut provider| {
            let discovery = provider.discover(days, &mut |diagnostic| {
                writeln!(
                    warnings,
                    "{}",
                    crate::diagnostics::record_warning(&diagnostic, zh)
                )?;
                Ok(())
            })?;
            Ok((provider, discovery))
        });
        match result {
            Ok((provider, discovery)) => {
                if !discovery.failures.is_empty() {
                    scan.failed_providers.push(info.name.into());
                }
                for failure in &discovery.failures {
                    writeln!(
                        warnings,
                        "{}",
                        crate::diagnostics::session_warning(info, failure, zh)
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
                let error = crate::render::safe_line(&crate::provider_error::operation_message(
                    error.as_ref(),
                    zh,
                ));
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
